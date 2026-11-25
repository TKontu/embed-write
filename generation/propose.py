"""GE-03 proposal flow: several candidates per request, near-duplicates removed.

``propose`` is the offline library-level flow behind one proposal request. It
renders the GE-01/GE-02 prompt with its ordered exemplar ids, asks the local
client for ``n`` candidates with varied sampling, records every raw candidate
so each is reproducible, drops near-duplicates through caller-supplied vectors,
and builds one verification panel per kept candidate. It only returns data:
no candidate is applied to a document, no edit is logged and nothing is
finalized (invariant I5).

Unwired by design until UX-01/VF-08 consume ``propose``; no editor or UI is
involved here.

Memory holds one prompt, ``n`` candidates, ``n`` vectors and the kept panels;
``n`` is bounded only by ``vary_sampling``'s validity check. There is no
request-size cap beyond that, and large-request performance is untested.
Vectors must share one level and dimension with ``cutoff`` from the caller; no
model, network policy or corpus access lives in this module (invariant I9).
"""

from dataclasses import dataclass
from typing import Callable, Iterable

from generation.candidates import remove_near_duplicates, vary_sampling
from generation.context import GenerationContext
from generation.exemplars import Exemplar, render_prompt
from generation.run_record import GenerationRunRecord, SamplingParams
from service.vectors import LevelVector
from service.verify_panel import VerificationPanel, build_panel


@dataclass(frozen=True)
class Proposal:
    """One request's record, kept candidates, aligned panels and drop count."""

    record: GenerationRunRecord
    candidates: tuple[str, ...]
    panels: tuple[VerificationPanel, ...]
    dropped_count: int


def propose(context: GenerationContext, exemplars: Iterable[Exemplar], *,
            client, base_sampling: SamplingParams, n: int,
            embed: Callable[[list[str]], list[LevelVector]], cutoff: float,
            current_document_id: str, section_type: str,
            exemplar_limit: int) -> Proposal:
    """Generate, record, deduplicate and panel one batch of candidate rewrites.

    Calls ``client.complete`` exactly once per varied sampling setting, in
    order, with the same rendered prompt; no retries and no streaming. The
    record keeps all raw candidates, while ``candidates`` and ``panels`` hold
    only those kept by ``remove_near_duplicates``, in input order. ``embed`` is
    called once with all raw candidates. Errors from the client, sampling,
    embedder or panel propagate and no partial ``Proposal`` is returned.
    """
    prompt, exemplar_ids = render_prompt(
        context, exemplars, current_document_id=current_document_id,
        section_type=section_type, limit=exemplar_limit)
    sampling = vary_sampling(base_sampling, n)
    raw = [client.complete(prompt, params) for params in sampling]
    record = GenerationRunRecord.build(prompt, exemplar_ids, client.model,
                                       sampling, raw)
    vectors = embed(raw)
    if len(vectors) != len(raw):
        raise ValueError('embed must return one vector per candidate')
    kept = remove_near_duplicates(raw, vectors, cutoff)
    panels = tuple(build_panel(context.passage.text, candidate) for candidate in kept)
    return Proposal(record, tuple(kept), panels, len(raw) - len(kept))
