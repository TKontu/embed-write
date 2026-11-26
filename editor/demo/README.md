# Thin demo (DE-01..DE-03)

Run from `editor/`:

```sh
npm run demo
```

The server prints its localhost URL. Open it; the page lists the `.md` files in the sample
folder, loads one into the editor, shows the provisional move overlay and saves edits through
`atomicWrite`.

## Sample folder (DE-05 swap)

The default folder is `examples/demo`. A real report folder is one argument or env var away:

```sh
npm run demo -- --dir /path/to/reports
DEMO_DIR=/path/to/reports npm run demo
npm run demo -- --dir /path/to/reports --port 8000
```

The folder may also contain:

- `<report>.moves.json` — `[{ "block": 0, "move": "finding" }]`, 0-based top-level block index;
- `legend.json` — `{ "provisional": true, "moves": { "finding": { "label": "...", "colour": "#..." } } }`.

If the folder has no `legend.json`, the demo's provisional legend is used. Without a sidecar the
report still opens and saves; it simply has no move labels.

## Offline modules

`server.js` builds a browser import map from the existing `editor/node_modules` and
`docmodel/node_modules`; `docmodel` is pinned to this checkout's source. No network download is
performed. CommonJS modules that the browser graph needs (for example `extend`, used by `unified`)
are served through a narrow wrapper for single-file modules that use no `require`.
