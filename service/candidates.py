"""Candidate embedding models for G-03 and a local ONNX adapter (EM-02).

Production caller: ``experiments.move_discovery`` (``--embedder onnx``, MV-02);
the G-03 runner and SV-02 come next. G-03 chooses the default, not this module. Nothing is downloaded: model files
come from a local, gitignored model_dir. onnxruntime and tokenizers are
imported only inside the loader, so importing this module stays stdlib-only.
Memory per call is O(batch * max_tokens * hidden) for the session output;
service.embedder.embed bounds the batch.

Model-card facts below are LLM-recorded and not verified locally:
- BAAI/bge-m3 (huggingface.co/BAAI/bge-m3): XLM-RoBERTa based, multilingual,
  dense output 1024 dims, max sequence 8192 tokens, dense embedding is the
  normalized [CLS] hidden state, no query/passage instruction needed.
- jinaai/jina-embeddings-v3 (huggingface.co/jinaai/jina-embeddings-v3):
  multilingual, 1024 dims, Matryoshka dims 32/64/128/256/512/768/1024, max
  8194 tokens, mean pooling; task LoRA adapters are selected by a `task_id`
  ONNX input instead of a text prefix (index 4 = text-matching, unverified).
"""

from collections.abc import Sequence
from dataclasses import dataclass
import os

from service.embedder import EmbedderError
from service.normalize import l2_normalize
from service.vectors import Level, LevelVector

POOLINGS = ('cls', 'mean')


@dataclass(frozen=True)
class CandidateModel:
    model_id: str
    model_version: str
    dims: int
    truncatable_dims: tuple[int, ...]
    max_tokens: int
    pooling: str
    query_prefix: str = ''
    passage_prefix: str = ''
    extra_inputs: tuple[tuple[str, int], ...] = ()
    pad_token_id: int = 0
    end_token_id: int | None = None

    def __post_init__(self):
        if self.pooling not in POOLINGS:
            raise ValueError(f'pooling must be one of {POOLINGS}')
        if type(self.dims) is not int or self.dims < 1:
            raise ValueError('dims must be a positive integer')
        if type(self.max_tokens) is not int or self.max_tokens < 1:
            raise ValueError('max_tokens must be a positive integer')
        if any(type(d) is not int or not 1 <= d <= self.dims
               for d in self.truncatable_dims):
            raise ValueError('truncatable_dims must be integers within dims')


CANDIDATES: tuple[CandidateModel, ...] = (
    # XLM-R vocabulary: <pad> = 1, </s> = 2 (tokenizer.json of the bge-m3 snapshot).
    CandidateModel('BAAI/bge-m3', 'hf-unpinned', 1024, (1024,), 8192, 'cls',
                   pad_token_id=1, end_token_id=2),
    CandidateModel('jinaai/jina-embeddings-v3', 'hf-unpinned', 1024,
                   (32, 64, 128, 256, 512, 768, 1024), 8194, 'mean',
                   extra_inputs=(('task_id', 4),)),
)


class _NumpySession:
    """Feed int64 arrays to a real onnxruntime session."""

    def __init__(self, session, numpy):
        self._session, self._np = session, numpy
        self._names = {i.name for i in session.get_inputs()}

    def run(self, output_names, feeds):
        arrays = {k: self._np.asarray(v, dtype=self._np.int64)
                  for k, v in feeds.items() if k in self._names}
        if 'token_type_ids' in self._names and 'token_type_ids' not in arrays:
            arrays['token_type_ids'] = self._np.zeros_like(arrays['input_ids'])
        return self._session.run(output_names, arrays)


class OnnxEmbedder:
    """Embedder protocol over a local ONNX model; session/tokenizer injectable."""

    def __init__(self, candidate: CandidateModel, model_dir, *, session=None,
                 tokenizer=None):
        self.candidate = candidate
        self.model_dir = model_dir
        self.model_id = candidate.model_id
        self.model_version = candidate.model_version
        self.dims = candidate.dims
        self.truncatable_dims = candidate.truncatable_dims
        self._session = session
        self._tokenizer = tokenizer

    def _load(self):
        if self._session is not None and self._tokenizer is not None:
            return
        try:
            import onnxruntime
        except ImportError as exc:
            raise EmbedderError('OnnxEmbedder needs the onnxruntime package') from exc
        try:
            import tokenizers
        except ImportError as exc:
            raise EmbedderError('OnnxEmbedder needs the tokenizers package') from exc
        paths = {name: os.path.join(self.model_dir, name)
                 for name in ('model.onnx', 'tokenizer.json')}
        for name, path in paths.items():
            if not os.path.isfile(path):
                raise EmbedderError(f'missing {name} in model_dir {self.model_dir}')
        if self._tokenizer is None:
            self._tokenizer = tokenizers.Tokenizer.from_file(paths['tokenizer.json'])
        if self._session is None:
            import numpy
            self._session = _NumpySession(
                onnxruntime.InferenceSession(paths['model.onnx'],
                                             providers=['CPUExecutionProvider']),
                numpy)

    def _truncate(self, ids):
        """Cut to max_tokens; keep the end token when the candidate has one."""
        c = self.candidate
        if len(ids) <= c.max_tokens:
            return ids
        if c.end_token_id is None:
            return ids[:c.max_tokens]
        return ids[:c.max_tokens - 1] + [c.end_token_id]

    def embed(self, texts: Sequence[str], level: Level) -> list[LevelVector]:
        if not texts:
            return []
        self._load()
        c = self.candidate
        encodings = self._tokenizer.encode_batch([c.passage_prefix + t for t in texts])
        ids = [self._truncate(list(e.ids)) for e in encodings]
        masks = [list(e.attention_mask)[:c.max_tokens] for e in encodings]
        width = max(len(row) for row in ids)
        feeds = {
            'input_ids': [row + [c.pad_token_id] * (width - len(row)) for row in ids],
            'attention_mask': [row + [0] * (width - len(row)) for row in masks],
        }
        for name, value in c.extra_inputs:
            feeds[name] = [value]
        hidden = self._session.run(None, feeds)[0]
        if hasattr(hidden, 'tolist'):
            hidden = hidden.tolist()
        result = []
        for tokens, mask in zip(hidden, masks):
            if c.pooling == 'cls':
                pooled = list(tokens[0])
            else:
                kept = [tok for tok, m in zip(tokens, mask) if m]
                if not kept:
                    raise EmbedderError('input has no attended tokens')
                pooled = [sum(col) / len(kept) for col in zip(*kept)]
            if len(pooled) != self.dims:
                raise EmbedderError('session output does not match candidate dims')
            result.append(LevelVector(level, l2_normalize(pooled)))
        return result
