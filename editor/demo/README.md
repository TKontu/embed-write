# Thin demo (DE-01..DE-03)

Run from `editor/`:

```sh
npm run demo
```

The server prints its localhost URL. Open it; the page lists the `.md` files in the sample
folder, loads one into the editor, shows the provisional move overlay and saves edits through
`atomicWrite`. A strip above the editor is the document minimap (OV-01): one segment per run of same-move blocks, coloured by legendCss.

## One real report (DE-05 swap, D-011)

Swapping in a real report is this single step:

```sh
npm run demo -- --report "/path/to/Any Report.md"
npm run demo -- --report "/path/to/Any Report.md" --labels /path/to/labels.json
```

The page lists exactly that file (any name, including spaces and non-ASCII), opens it, and saves
edits back to that same file through `atomicWrite`; every other name is refused. Labels come from
`--labels`, else `<report>.moves.json` beside the report, else none. The legend says the labels are
provisional (not "synthetic"); `legend.json` beside the report is used if present. `--labels`
without `--report` is a usage error (one-line message, exit code 2).

The legend says "synthetic" only for the shipped `examples/demo` folder; any other `--dir`/`DEMO_DIR`
folder is labelled "unreviewed placeholders".

## Sample folder

The default folder is `examples/demo`. A real report folder is one argument or env var away:

```sh
npm run demo -- --dir /path/to/reports
DEMO_DIR=/path/to/reports npm run demo
npm run demo -- --dir /path/to/reports --port 8000
```

The folder may also contain:

- `<report>.moves.json` — `[{ "block": 0, "move": "finding" }]`, 0-based top-level block index;
  optional `"level"` (`section` on a heading block, `paragraph` default, or `sentence` with a 0-based `"sentence"`) is shown by the Granularity select (RE-09);
- `genre.json` — a genre file in the service/genre.py schema (DE-06); its moves and stored legend
  drive the legend panel (LG-07) and overlay colours (LG-02 legendCss). Falls back to the demo's.
- `legend.json` — provisional marking; `{ "provisional": true, "moves": { "finding": { "label": "...", "colour": "#..." } } }`.

If the folder has no `legend.json`, the demo's provisional legend is used. Without a sidecar the
report still opens and saves; it simply has no move labels.

## Offline modules

`server.js` builds a browser import map from the existing `editor/node_modules` and
`docmodel/node_modules`; `docmodel` is pinned to this checkout's source. No network download is
performed. CommonJS modules that the browser graph needs (for example `extend`, used by `unified`)
are served through a narrow wrapper for single-file modules that use no `require`.
