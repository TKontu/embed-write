# MinerU vs pypdf on the 19 publications (R235/A1, D-016 check)

Counts only (I9). Documents are keyed by opaque index `doc-NN` in sorted file-name order; no names,
titles or text. Counts are machine-computed by `experiments/parser_compare.py`; no quality judgment
(that is CO-05, the expert's).

## Outcome: the MinerU path did not run

Every MinerU request timed out. All 19 files, each sent twice (the adapter's one retry) with
`PARSER_TIMEOUT_S=300`, raised `TimeoutError` and fell back to pypdf. The MinerU run therefore
reproduces the pypdf run exactly, and **the D-016 check is not done**: no MinerU counts exist, and
the scanned PDF (doc-09) yielded no text through MinerU.

Service state (`GET /health`, MinerU **3.1.0**, healthy, `failed_tasks` 0, `max_concurrent_requests` 3):
- before the run: `queued_tasks` 1, `processing_tasks` 3, `completed_tasks` 200;
- after the run: `queued_tasks` 57, `processing_tasks` 3, `completed_tasks` 219.

The service was saturated (3 of 3 slots busy). Only 19 tasks completed in about 191 minutes, while
the queue grew by 56. This run sent 38 requests. The timed-out requests were probably still
queued on the server, because the client gives up without cancelling them. This is an inference
from the counters only; nothing here shows which client queued what.

## Totals

| | pypdf run | MinerU run |
| --- | ---: | ---: |
| files | 19 | 19 |
| parsed (ok) | 14 | 14 |
| failed | 5 | 5 |
| ATX headings | 2118 | 2118 |
| tables | 0 | 0 |
| `$$` formula blocks | 0 | 0 |
| words | 460703 | 460703 |
| failure types | DependencyError 1, ValueError 4 | DependencyError 1, ValueError 4 |
| parser used | pypdf 19 | pypdf 19 |
| MinerU fallback exception | n/a | TimeoutError 19 |
| dropped chrome | n/a | 0 |

pypdf failures by kind, from the converter's own error category, not document text:
- 3 encrypted (doc-01, doc-07, doc-10);
- 1 AES needing `cryptography`, a `DependencyError` (doc-05);
- 1 with no text layer, the scanned PDF (doc-09).

## Per document

| doc | pypdf status | pypdf headings / tables / formulas / words | MinerU-run status | parser used | fallback | headings / tables / formulas / words | dropped |
| --- | --- | --- | --- | --- | --- | --- | ---: |
| doc-01 | failed (ValueError) | - / - / - / - | failed (ValueError) | pypdf | TimeoutError | - / - / - / - | 0 |
| doc-02 | ok | 6 / 0 / 0 / 6729 | ok | pypdf | TimeoutError | 6 / 0 / 0 / 6729 | 0 |
| doc-03 | ok | 2 / 0 / 0 / 871 | ok | pypdf | TimeoutError | 2 / 0 / 0 / 871 | 0 |
| doc-04 | ok | 513 / 0 / 0 / 68199 | ok | pypdf | TimeoutError | 513 / 0 / 0 / 68199 | 0 |
| doc-05 | failed (DependencyError) | - / - / - / - | failed (DependencyError) | pypdf | TimeoutError | - / - / - / - | 0 |
| doc-06 | ok | 9 / 0 / 0 / 7099 | ok | pypdf | TimeoutError | 9 / 0 / 0 / 7099 | 0 |
| doc-07 | failed (ValueError) | - / - / - / - | failed (ValueError) | pypdf | TimeoutError | - / - / - / - | 0 |
| doc-08 | ok | 566 / 0 / 0 / 91725 | ok | pypdf | TimeoutError | 566 / 0 / 0 / 91725 | 0 |
| doc-09 | failed (ValueError) | - / - / - / - | failed (ValueError) | pypdf | TimeoutError | - / - / - / - | 0 |
| doc-10 | failed (ValueError) | - / - / - / - | failed (ValueError) | pypdf | TimeoutError | - / - / - / - | 0 |
| doc-11 | ok | 386 / 0 / 0 / 105004 | ok | pypdf | TimeoutError | 386 / 0 / 0 / 105004 | 0 |
| doc-12 | ok | 18 / 0 / 0 / 22819 | ok | pypdf | TimeoutError | 18 / 0 / 0 / 22819 | 0 |
| doc-13 | ok | 12 / 0 / 0 / 14873 | ok | pypdf | TimeoutError | 12 / 0 / 0 / 14873 | 0 |
| doc-14 | ok | 4 / 0 / 0 / 5505 | ok | pypdf | TimeoutError | 4 / 0 / 0 / 5505 | 0 |
| doc-15 | ok | 4 / 0 / 0 / 6093 | ok | pypdf | TimeoutError | 4 / 0 / 0 / 6093 | 0 |
| doc-16 | ok | 28 / 0 / 0 / 10961 | ok | pypdf | TimeoutError | 28 / 0 / 0 / 10961 | 0 |
| doc-17 | ok | 55 / 0 / 0 / 32737 | ok | pypdf | TimeoutError | 55 / 0 / 0 / 32737 | 0 |
| doc-18 | ok | 369 / 0 / 0 / 78605 | ok | pypdf | TimeoutError | 369 / 0 / 0 / 78605 | 0 |
| doc-19 | ok | 146 / 0 / 0 / 9483 | ok | pypdf | TimeoutError | 146 / 0 / 0 / 9483 | 0 |

## Wall time

- pypdf run: 1 min 12 s.
- MinerU run: 191 min, almost all of it timeouts (19 files x 2 attempts x 300 s = 190 min).

## Commands (base f4df3e9, repo `.venv`, private outputs under the gitignored `/work/embed-write/output/`)

```sh
env -u PARSER_BASE_URL .venv/bin/python -m experiments.ingest convert \
  /work/embed-write/input/publications /work/embed-write/output/r235-parser-compare/pypdf
PARSER_BASE_URL=http://192.168.0.94:8008 PARSER_TIMEOUT_S=300 .venv/bin/python -m experiments.ingest convert \
  /work/embed-write/input/publications /work/embed-write/output/r235-parser-compare/mineru
.venv/bin/python -m experiments.parser_compare compare \
  /work/embed-write/output/r235-parser-compare/pypdf /work/embed-write/output/r235-parser-compare/mineru \
  /work/embed-write/output/r235-parser-compare/compare.json
curl -s http://192.168.0.94:8008/health
```

## Residuals

- The D-016 check needs a re-run when the service has free capacity: check `/health` first and
  run when `queued_tasks` is 0, or with a larger `PARSER_TIMEOUT_S` (an operator decision).
- The adapter does not cancel a timed-out request on the server, and the retry re-queues the file.
  On a busy service, each file can occupy two queue slots. Recorded, not fixed here (packet
  non-goal: no change to `experiments/mineru_native.py` or `experiments/ingest.py`).
- The empty-password encrypted PDFs (3) and the AES PDF (1) still fail under pypdf (out of scope).

