# Schema decisions (ED-02)

Record of the docmodel schema **as implemented** at base `cb75e91`. This is a description, not a
design change: undecided behaviour is listed under [Open questions](#open-questions) for the
expert/planner. The node/mark table below is checked mechanically by
`docmodel/test/schema-decisions.test.js`, which fails if it does not list exactly the names in
`docmodel/src/schema.js`.

Pipeline: `docmodel/src/parse.js` (remark-parse + remark-gfm + remark-frontmatter `['yaml','toml']`)
→ ProseMirror doc under `docmodel/src/schema.js` → `docmodel/src/serialize.js`. Every block node
(group `block`, plus `list_item`, `table_row`, `table_cell`) carries `id` (default null); ids never
appear in Markdown (sidecar only, NI-01/NI-02).

## (a) First-class nodes and marks

Tests: `P` = `docmodel/test/parse.test.js`, `RT` = round-trip fixtures in
`docmodel/test/fixtures/roundtrip/` run by `docmodel/test/roundtrip.test.js`; every row is also
covered by `docmodel/test/schema-coverage.test.js` (each type occurs in some round-trip fixture).

<!-- schema-table:start -->
| Kind | Name | Markdown form | Recorded attrs | Test |
| --- | --- | --- | --- | --- |
| node | doc | whole document | — | P "doc + paragraph + text" |
| node | paragraph | plain text block | — | P "doc + paragraph + text" |
| node | heading | `# x` (ATX) or `x` + `===`/`---` (setext) | level, setext | P "ATX heading…", "setext heading…"; RT setext-headings.md |
| node | blockquote | `> x` | — | P "blockquote"; RT lists-quotes.md |
| node | bullet_list | `- x` / `* x` / `+ x` | marker | P "bullet_list records marker…" |
| node | ordered_list | `1. x` | start | P "ordered_list records start" |
| node | list_item | list item, GFM task `[ ]`/`[x]` | checked | P "task list item keeps checked" |
| node | code_block | fenced (```` ``` ````/`~~~`) or indented code | lang, fence (`''` = indented) | P "fenced code_block…", "indented code_block…"; RT code-fence-markdown.md |
| node | thematic_break | `***` / `---` / `___` | marker | P "thematic_break records its source marker"; RT thematic-break.md |
| node | html_block | block-level raw HTML, kept verbatim | value | P "html_block"; RT html-blocks.md |
| node | table | GFM pipe table | — | P "table / table_row / table_cell with align"; RT aligned-table.md |
| node | table_row | table row | — | same |
| node | table_cell | table cell (inline content) | align | same; RT table-pipe-in-code.md |
| node | front_matter | leading YAML `---` … `---` | value | P "front_matter"; RT front-matter.md |
| node | footnote_definition | `[^label]: body` | label | P "footnote_definition and footnote_reference mark"; RT footnotes.md |
| node | image | `![alt](src "title")` or `![alt][ref]` | src, alt, title, ref | P "image", "reference image resolves src and keeps ref" |
| node | hard_break | trailing two spaces or `\` before newline | — | P "hard_break"; RT hard-breaks.md |
| node | text | inline text | — | P "doc + paragraph + text" |
| mark | link | `[t](href "title")` or `[t][ref]` + definition | href, title, ref | P "inline link…", "reference link resolves href and keeps ref label"; RT reference-links.md |
| mark | em | `*x*` / `_x_` | marker | P "em marker * vs _"; RT nested-emphasis.md |
| mark | strong | `**x**` / `__x__` | marker | P "strong marker ** vs __" |
| mark | code | `` `x` `` (excludes all other marks) | — | P "code mark" |
| mark | footnote_reference | `[^label]` (text = label, excludes other marks) | label | P "footnote_definition and footnote_reference mark" |
<!-- schema-table:end -->

Link/image reference `definition`s are not nodes: `parse.js` `blockChildren` drops them and folds
`href`/`title`/`ref` into the link mark or image (`collectDefinitions`, `resolveRef`). A reference
with no matching definition is parsed by remark as literal text (P "reference without definition
stays literal text").

## (b) HTML

- **Block HTML** (mdast `html` at block level) → `html_block` atom whose `value` is the raw source;
  `serialize.js` emits `value` unchanged (`case 'html_block'`). Source: `parse.js` `block()`
  `case 'html'`. Tests: P "html_block"; RT html-blocks.md.
- **Inline HTML** (mdast `html` inside a paragraph, e.g. `a <b>x</b>`) has no mapping: `parse.js`
  `inline()` falls to `default: throw unsupported(node)`. Tests: P "unsupported mdast node throws
  UnsupportedNodeError naming the type" (`a <b>x</b>` → nodeType `html`); `docmodel/test/open.test.js`
  "known-bad inline-html.md opens read-only, bytes unchanged".
- HTML is never interpreted, sanitised or rendered as HTML by the model; it is opaque text.

## (c) Unsupported constructs

`parse.js` throws `UnsupportedNodeError` (`docmodel/src/errors.js`; message
`Unsupported mdast node type "<type>" at line:col`, property `nodeType`) — nothing is silently
dropped. Throw sites:

| Construct | Where in parse.js | Test |
| --- | --- | --- |
| Any block mdast type without a case (default) | `block()` default | — (no dedicated test; remark-gfm emits no other block types today) |
| Any inline mdast type without a case, notably GFM strikethrough `~~x~~` (`delete`) and inline HTML (`html`) | `inline()` default | P "unsupported mdast node throws…"; open.test.js strikethrough.md, inline-html.md |
| TOML front matter `+++ … +++` at document start | `block()` `case 'toml'` (`toml (TOML front matter)`) | P "TOML front matter throws…"; roundtrip.test.js "TOML front matter throws UnsupportedNodeError" |
| Non-`tableRow`/`tableCell` inside a table, non-`listItem` inside a list | `block()` table case, `listItem()` | — (defensive; remark does not produce these) |
| `linkReference`/`imageReference` whose definition is missing | `resolveRef()` | — (defensive; remark emits text instead, see above) |

Front matter rules: only YAML at the very start of the file becomes `front_matter`
(serialized back as `---\n<value>\n---`); TOML at the start is rejected; `+++` elsewhere is ordinary
text (P "+++ not at document start still parses and round-trips"). A leading `---` thematic break
that would reopen as front matter is serialized as `***` (`docmodel/test/serialize.test.js`
"leading --- falls back to ***…").

GFM extensions enabled by remark-gfm: tables, task list items, footnotes → supported;
strikethrough → unsupported (the schema has no strike mark; `editor/test/inlinerules.test.js`
"strikethrough is skipped: the schema has no strike mark"); autolink literals are parsed by
remark-gfm as `link` nodes and become link marks (observed at base, e.g. `www.x.com` → href
`http://www.x.com`; no dedicated test — see open question 8).

## (d) What happens when a file contains one

- **`openMarkdown(src)`** (`docmodel/src/open.js`, DM-05): on `UnsupportedNodeError` returns
  `{doc: null, readOnly: true, warnings: ['Opened read-only: <message>']}`. If parsing succeeds but
  parse→serialize→parse changes the doc, or serialize is not a fixed point, it returns the doc with
  `readOnly: true` and a `does not round-trip (…)` warning. Other errors propagate. It is pure: it
  never writes files and never returns rewritten Markdown, so the file's bytes are unchanged.
  Tests: open.test.js (known-bad fixtures assert sha256 unchanged and no `markdown`/`text` field;
  TOML case; injected drift and non-fixed-point serializers; "non-Error/other parse failures
  propagate"; "clean file opens editable with no warnings").
- **Editor** (`editor/src/index.js` `createEditor`) calls `parseMarkdown` directly, not
  `openMarkdown`, so an unsupported file makes `createEditor` throw `UnsupportedNodeError`; there is
  no read-only editor mode yet. Switching from source view back to rich view with unsupported text
  throws and keeps the source view and its text (`editor/test/source.test.js` "throwing parse keeps
  source view and text").
- **Demo** (`editor/demo/app.js` `load`): the `createEditor` throw surfaces as a status-bar error
  ("Load failed: …"); nothing is saved, so the sample on disk is untouched. Leaving source view on
  unsupported text shows "Cannot leave source view: …".

## Open questions

Not decided here; for the expert/planner:

1. Strikethrough (`~~x~~`): add a mark, keep rejecting, or pass through as literal text?
2. Inline HTML: add an inline passthrough atom (mirroring `html_block`) or keep rejecting?
3. Should the editor/demo open path use `openMarkdown` and show a read-only view with the warning,
   instead of failing to load?
4. Should a drift-only file (parses, but does not round-trip) be viewable read-only in the editor
   with its doc, given `openMarkdown` already returns it?
5. Tables: cell content is inline only (no multi-paragraph cells) and there is no table editing UI —
   is that the intended scope for reports?
6. TOML front matter: keep rejecting, or store opaquely like YAML?
7. Should `html_block` content be sanitised or sandboxed when rendered by the editor?
8. GFM autolink literals become link marks; is their serialized form (and round-trip) acceptable?
