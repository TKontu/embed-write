# Readers-canon intake through MinerU (R252/A1, CO-04 / CO-12)

Counts only (I9). This report has no corpus text, titles or file names. Documents are keyed `doc-NN`
in sorted source-path order, and areas are the corpus folder names. The private key map stays
outside git.

## Run

- Source: `input/publications/readers-canon-validated/`, 65 PDFs (one per folder, 7 areas). The
  `.zip` beside it sits outside SRC and was not read. The manifests (`META_MANIFEST.md`, 7 ×
  `MANIFEST.md`) were left out of the run. To do that without a code change, intake read a staged
  tree of read-only symlinks, `AREA/doc-NN.pdf`, outside git. Without it, ingest would have
  converted the manifests as `.md` documents, and one pair of PDFs with the same file stem would
  have failed with an output-name collision.
- Command: `PARSER_BASE_URL=http://192.168.0.94:8008 python -m experiments.intake run SRC OUT --genre examples/demo/genre.json`
  (default `PARSER_TIMEOUT_S` 300). Files were processed sequentially. Exit 0.
- Service `/health` (MinerU 3.1.0, max_concurrent_requests 3): before the run, queued 0,
  processing 0, completed 0, failed 0. After the run, queued 0, processing 1, completed 67,
  failed 0.
- Intake steps: ingest ok (65 ok, 0 failed, 0 unsupported); conversion_quality ok (19 of 65
  flagged); corpus_stats ok (3332 sections, 107429 sentences); sections ok (64 have headings, 1
  inferred); boilerplate ok (13 repeated); annotation_sample ok (300 drawn, 32 test documents, 32
  strata). metadata, prelabel and discovery were skipped by design (no `--metadata`, no model
  endpoint, not requested).

## Per area

| area | files | parser used | ok | failed | failure types | flag codes |
| --- | ---: | --- | ---: | ---: | --- | --- |
| biology | 7 | mineru 7 | 7 | 0 | - | few_headings 1, long_line 4, merged_columns 1 |
| computing | 12 | mineru 12 | 12 | 0 | - | broken_table 1, few_headings 1, long_line 3 |
| engineering | 10 | mineru 8, pypdf 2 | 10 | 0 | - | long_line 53 |
| essays | 5 | mineru 5 | 5 | 0 | - | few_headings 1, long_line 2 |
| physics | 9 | mineru 9 | 9 | 0 | - | few_headings 2, long_line 4 |
| social-science | 12 | mineru 12 | 12 | 0 | - | broken_table 2, long_line 4 |
| top10 | 10 | mineru 9, pypdf 1 | 10 | 0 | - | few_headings 3, no_headings 1 |
| **total** | 65 | mineru 62, pypdf 3 | 65 | 0 | | broken_table 3, few_headings 8, long_line 70, merged_columns 1, no_headings 1 |

Three files fell back to pypdf after MinerU raised `TimeoutError` on both attempts: doc-25 and
doc-27 (engineering) and doc-57 (top10). All three still converted through pypdf. doc-25 carries
51 of the 53 engineering `long_line` flags.

## Per document

| doc | area | parser | status | failure type | MinerU fallback | flags |
| --- | --- | --- | --- | --- | --- | ---: |
| doc-01 | biology | mineru | ok | - | - | 1 |
| doc-02 | biology | mineru | ok | - | - | 5 |
| doc-03 | biology | mineru | ok | - | - | 0 |
| doc-04 | biology | mineru | ok | - | - | 0 |
| doc-05 | biology | mineru | ok | - | - | 0 |
| doc-06 | biology | mineru | ok | - | - | 0 |
| doc-07 | biology | mineru | ok | - | - | 0 |
| doc-08 | computing | mineru | ok | - | - | 0 |
| doc-09 | computing | mineru | ok | - | - | 0 |
| doc-10 | computing | mineru | ok | - | - | 3 |
| doc-11 | computing | mineru | ok | - | - | 0 |
| doc-12 | computing | mineru | ok | - | - | 0 |
| doc-13 | computing | mineru | ok | - | - | 0 |
| doc-14 | computing | mineru | ok | - | - | 0 |
| doc-15 | computing | mineru | ok | - | - | 0 |
| doc-16 | computing | mineru | ok | - | - | 1 |
| doc-17 | computing | mineru | ok | - | - | 0 |
| doc-18 | computing | mineru | ok | - | - | 0 |
| doc-19 | computing | mineru | ok | - | - | 1 |
| doc-20 | engineering | mineru | ok | - | - | 0 |
| doc-21 | engineering | mineru | ok | - | - | 0 |
| doc-22 | engineering | mineru | ok | - | - | 1 |
| doc-23 | engineering | mineru | ok | - | - | 0 |
| doc-24 | engineering | mineru | ok | - | - | 0 |
| doc-25 | engineering | pypdf | ok | - | TimeoutError | 51 |
| doc-26 | engineering | mineru | ok | - | - | 0 |
| doc-27 | engineering | pypdf | ok | - | TimeoutError | 0 |
| doc-28 | engineering | mineru | ok | - | - | 1 |
| doc-29 | engineering | mineru | ok | - | - | 0 |
| doc-30 | essays | mineru | ok | - | - | 2 |
| doc-31 | essays | mineru | ok | - | - | 1 |
| doc-32 | essays | mineru | ok | - | - | 0 |
| doc-33 | essays | mineru | ok | - | - | 0 |
| doc-34 | essays | mineru | ok | - | - | 0 |
| doc-35 | physics | mineru | ok | - | - | 0 |
| doc-36 | physics | mineru | ok | - | - | 1 |
| doc-37 | physics | mineru | ok | - | - | 1 |
| doc-38 | physics | mineru | ok | - | - | 0 |
| doc-39 | physics | mineru | ok | - | - | 0 |
| doc-40 | physics | mineru | ok | - | - | 0 |
| doc-41 | physics | mineru | ok | - | - | 1 |
| doc-42 | physics | mineru | ok | - | - | 0 |
| doc-43 | physics | mineru | ok | - | - | 3 |
| doc-44 | social-science | mineru | ok | - | - | 0 |
| doc-45 | social-science | mineru | ok | - | - | 0 |
| doc-46 | social-science | mineru | ok | - | - | 0 |
| doc-47 | social-science | mineru | ok | - | - | 0 |
| doc-48 | social-science | mineru | ok | - | - | 0 |
| doc-49 | social-science | mineru | ok | - | - | 0 |
| doc-50 | social-science | mineru | ok | - | - | 0 |
| doc-51 | social-science | mineru | ok | - | - | 0 |
| doc-52 | social-science | mineru | ok | - | - | 0 |
| doc-53 | social-science | mineru | ok | - | - | 4 |
| doc-54 | social-science | mineru | ok | - | - | 0 |
| doc-55 | social-science | mineru | ok | - | - | 2 |
| doc-56 | top10 | mineru | ok | - | - | 0 |
| doc-57 | top10 | pypdf | ok | - | TimeoutError | 0 |
| doc-58 | top10 | mineru | ok | - | - | 0 |
| doc-59 | top10 | mineru | ok | - | - | 0 |
| doc-60 | top10 | mineru | ok | - | - | 0 |
| doc-61 | top10 | mineru | ok | - | - | 1 |
| doc-62 | top10 | mineru | ok | - | - | 1 |
| doc-63 | top10 | mineru | ok | - | - | 0 |
| doc-64 | top10 | mineru | ok | - | - | 2 |
| doc-65 | top10 | mineru | ok | - | - | 0 |

## Residuals

- The genre is a placeholder (`examples/demo/genre.json`). Choosing the genre is the operator's
  decision. No quality judgment is made here; the spot-check is the expert's (CO-05).
- The manifest skip and the stem-collision workaround were handled by staging, not in ingest. A
  real-corpus run without staging would ingest the manifests and fail one file.
- The 3 MinerU timeouts were not retried with a longer `PARSER_TIMEOUT_S`. After the run the
  service still showed 1 task processing, probably an abandoned timed-out request (inferred from
  the counters only).
