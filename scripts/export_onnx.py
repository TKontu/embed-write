"""One-time offline export of a local Hugging Face encoder to ONNX (MV-02/EM-02).

Usage: python3 scripts/export_onnx.py SRC_MODEL_DIR OUT_DIR

Export-time tooling only (torch + transformers from the system python; never a
runtime dependency). Loads SRC_MODEL_DIR with ``local_files_only`` (no
downloads), writes OUT_DIR/model.onnx (weights > 2 GB go to an external data
file next to it) and a copy of tokenizer.json. Graph inputs are
``input_ids`` and ``attention_mask`` (int64, dynamic batch and sequence axes);
output 0 is ``last_hidden_state`` [batch, seq, hidden], as
``service.candidates.OnnxEmbedder`` expects (it pools CLS itself).

Prints only paths, sizes and a parity figure: the max abs difference between
the L2-normalised torch CLS vector and the ONNX one on two fixed LLM-built
sentences. Uses the legacy TorchScript exporter (``dynamo=False``, eager
attention) so ``onnxscript`` is not needed; it and the weight gathering need
``onnx`` (requirements-export.txt). Parity runs through onnxruntime.

Production caller: the operator, once per model, before
``python -m experiments.move_discovery report ... --embedder onnx``.
"""
from __future__ import annotations

import os
import shutil
import sys

PARITY_SENTENCES = (  # LLM-built synthetic
    'The committee approved the revised budget after a short debate.',
    'Rainfall in the northern valley was unusually low this spring.',
)


def _size(path):
    return os.path.getsize(path) if os.path.isfile(path) else 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print('usage: export_onnx.py SRC_MODEL_DIR OUT_DIR', file=sys.stderr)
        return 2
    src, out = argv
    for name in ('config.json', 'tokenizer.json'):
        if not os.path.isfile(os.path.join(src, name)):
            print(f'error: missing {name} in {src}', file=sys.stderr)
            return 2
    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
    import numpy as np
    import torch
    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(src, local_files_only=True)
    model = AutoModel.from_pretrained(src, local_files_only=True,
                                      add_pooling_layer=False,
                                      attn_implementation='eager').eval()
    model.config.return_dict = False

    class Wrapper(torch.nn.Module):
        def __init__(self, inner):
            super().__init__()
            self.inner = inner

        def forward(self, input_ids, attention_mask):
            return self.inner(input_ids=input_ids, attention_mask=attention_mask,
                              return_dict=False)[0]

    os.makedirs(out, exist_ok=True)
    onnx_path = os.path.join(out, 'model.onnx')
    staging = os.path.join(out, '.staging')
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging)
    batch = tokenizer(list(PARITY_SENTENCES), padding=True, return_tensors='pt')
    with torch.no_grad():
        # Reference first: tracing leaves the module in a state that no longer
        # reproduces eager outputs (observed 4e-2 drift when taken afterwards).
        reference = model(**batch, return_dict=False)[0][:, 0].numpy()
        torch.onnx.export(
            Wrapper(model), (batch['input_ids'], batch['attention_mask']),
            os.path.join(staging, 'model.onnx'),
            input_names=['input_ids', 'attention_mask'], output_names=['last_hidden_state'],
            dynamic_axes={'input_ids': {0: 'batch', 1: 'sequence'},
                          'attention_mask': {0: 'batch', 1: 'sequence'},
                          'last_hidden_state': {0: 'batch', 1: 'sequence'}},
            opset_version=17, dynamo=False)
    # The exporter scatters >2 GB weights into one file per tensor; gather them
    # into a single model.onnx.data next to model.onnx.
    import onnx
    proto = onnx.load(os.path.join(staging, 'model.onnx'))
    for stale in ('model.onnx', 'model.onnx.data'):
        if os.path.exists(os.path.join(out, stale)):
            os.remove(os.path.join(out, stale))
    onnx.save_model(proto, onnx_path, save_as_external_data=True,
                    all_tensors_to_one_file=True, location='model.onnx.data')
    del proto
    shutil.rmtree(staging)
    shutil.copyfile(os.path.join(src, 'tokenizer.json'), os.path.join(out, 'tokenizer.json'))

    for name in sorted(os.listdir(out)):
        print(f'{os.path.join(out, name)}\t{_size(os.path.join(out, name))} bytes')
    try:
        import onnxruntime
    except ImportError:
        print('parity: skipped (onnxruntime not importable in this interpreter)')
        return 0
    session = onnxruntime.InferenceSession(onnx_path, providers=['CPUExecutionProvider'])
    got = session.run(None, {'input_ids': batch['input_ids'].numpy(),
                             'attention_mask': batch['attention_mask'].numpy()})[0][:, 0]

    def norm(x):
        return x / np.linalg.norm(x, axis=1, keepdims=True)

    print(f'parity: max abs diff (normalised CLS, torch vs onnx, '
          f'{len(PARITY_SENTENCES)} sentences) = {float(np.abs(norm(reference) - norm(got)).max()):.3e}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
