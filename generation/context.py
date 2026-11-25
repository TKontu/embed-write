"""GE-01 deterministic, section-local generation context.

Unwired by design until the GE-03/GE-04 proposal flow supplies one Section,
selects a passage and sends render_prompt() to LLMClient.complete. No corpus
retrieval, model calls or edits occur here. Section passages are in document
order; their IDs need only be unique within that section.

The budget counts Unicode characters in the entire rendered prompt, including
JSON escaping and instructions (not tokens or UTF-8 bytes). Required passage,
move and section fields are never truncated: an insufficient budget raises.
Optional neighbours are dropped whole, farthest first; equal distances drop
the following neighbour first. Full section text remains even when explicit
neighbour entries are dropped.

Input storage belongs to the caller. Assembly scans only the supplied section,
uses constant space for lookup, and retains at most the prompt budget's worth
of neighbours. Serialization temporarily uses space proportional to one input
field; extremely large individual sections/fields have not been load-tested.
"""

from dataclasses import dataclass
import json


@dataclass(frozen=True)
class Passage:
    id: str
    text: str
    move: str

    def __post_init__(self):
        if not all(isinstance(x, str) for x in (self.id, self.text, self.move)):
            raise ValueError('passage fields must be strings')


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    text: str
    passages: tuple[Passage, ...]

    def __post_init__(self):
        if not all(isinstance(x, str) for x in (self.id, self.title, self.text)):
            raise ValueError('section fields must be strings')
        object.__setattr__(self, 'passages', tuple(self.passages))
        if not all(isinstance(p, Passage) for p in self.passages):
            raise ValueError('section passages must be Passage instances')


def _passage_dict(p):
    return {'id': p.id, 'text': p.text, 'move': p.move}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


@dataclass(frozen=True)
class GenerationContext:
    passage: Passage
    section_id: str
    section_title: str
    section_text: str
    before: tuple[Passage, ...] = ()
    after: tuple[Passage, ...] = ()

    def render_prompt(self) -> str:
        """Return stable instructions plus JSON context for LLMClient.complete."""
        return 'Propose a rewrite of the selected passage preserving its move and meaning.\n' + _json({
            'passage': _passage_dict(self.passage),
            'section': {'id': self.section_id, 'title': self.section_title,
                        'text': self.section_text},
            'before': [_passage_dict(p) for p in self.before],
            'after': [_passage_dict(p) for p in self.after],
        })


def build_context(section: Section, passage_id: str, *, k: int = 2,
                  max_chars: int = 16000) -> GenerationContext:
    """Snapshot a selected passage and a budgeted window within one section.

    Unknown or ambiguous selected IDs and invalid budgets/windows raise
    ValueError. Neighbours remain in document order. No partial neighbour is
    retained and no farther neighbour fills a gap left by an oversized one.
    """
    if any(type(v) is not int or v < 0 for v in (k, max_chars)):
        raise ValueError('k and max_chars must be nonnegative integers')
    index = None
    for i, passage in enumerate(section.passages):
        if passage.id == passage_id:
            if index is not None:
                raise ValueError('ambiguous passage id')
            index = i
    if index is None:
        raise ValueError('unknown passage id')
    selected = section.passages[index]
    core = GenerationContext(selected, section.id, section.title, section.text)
    size = len(core.render_prompt())
    if size > max_chars:
        raise ValueError('required passage and section exceed character budget')
    before, after = [], []
    # Adding nearest first is equivalent to removing farthest first, but never
    # materializes an unbounded window when k is large and the budget is small.
    for distance in range(1, min(k, max(index, len(section.passages) - index - 1)) + 1):
        for position, dest in ((index - distance, before), (index + distance, after)):
            if not 0 <= position < len(section.passages):
                continue
            neighbour = section.passages[position]
            cost = len(_json(_passage_dict(neighbour))) + bool(dest)
            if size + cost > max_chars:
                return GenerationContext(selected, section.id, section.title, section.text,
                                         tuple(reversed(before)), tuple(after))
            dest.append(neighbour)
            size += cost
    return GenerationContext(selected, section.id, section.title, section.text,
                             tuple(reversed(before)), tuple(after))
