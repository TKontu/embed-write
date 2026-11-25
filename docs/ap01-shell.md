# AP-01 — App shell: Tauri vs Electron (analysis record)

Status: **proposal for the operator** (R114/A1). Does not edit `docs/decisions.md` or
`docs/architecture.md`. D-007 (2026-11-24) already rules "the app shell is Tauri"; this record
is the AP-01 check ("both analysed in a short decision record") and tests that ruling against the
repo as it stands at base `3ea1976`.

## Measured facts (this host, offline, base 3ea1976)

| Fact | Evidence |
| --- | --- |
| `editor/` is an ESM package (`"type": "module"`) exporting `createEditor({ root, markdown })` | `editor/package.json`; `editor/src/index.js:42` |
| `editor/` depends on `docmodel` via `file:../docmodel` and Milkdown 7.23.0; tests run under Node + jsdom | `editor/package.json` |
| The analysis service is Python, stdlib-only HTTP on loopback (`GET /v1/health`, `POST /v1/batch`) | `service/server.py` docstring |
| Bind host is checked fail-closed and outbound sockets are guarded (I9) | `service/server.py`, `service/network_guard.py` |
| Local models: ONNX via `onnxruntime` in Python, from a gitignored `model_dir` | `service/candidates.py:1-5,64` |
| No Tauri or Electron code or dependency in the repo; only a `.gitignore` entry `src-tauri/target/` and a comment in `editor/src/index.js:3` | `git grep -i 'tauri\|electron'` |
| Node v22.23.2 and npm present | `node --version`, `which npm` |
| No Rust toolchain (`cargo`, `rustc` not on PATH, no `~/.cargo/bin`) | `which cargo rustc` |
| Python 3.12.3; pinned deps are pysbd, lmdb, pypdf | `python3 --version`, `requirements.txt` |

Everything below this table that is not in it is a **claim** from general knowledge of the two
frameworks, not measured here.

## Criteria and analysis

Same criteria for both options.

### 1. Hosting `editor/` and `docmodel`

- **Tauri:** frontend runs in the OS webview (WebKitGTK on Linux, WebView2 on Windows, WKWebView on
  macOS). The ESM editor must be bundled (e.g. Vite) into static assets; `createEditor` mounts into
  a DOM root as it does under jsdom. Risk (claim): engine differences between webviews, notably
  WebKitGTK, for ProseMirror selection/IME behaviour; must be tested on each target OS.
- **Electron:** bundled Chromium, one engine everywhere; same bundling step. Renderer behaviour
  matches Chrome, the most-tested ProseMirror target. Node in the main process could import
  `docmodel` directly, but this repo's design keeps analysis in Python, so that buys little.

### 2. Reaching the Python service and local models

The service already speaks loopback HTTP and has a Python client contract, so either shell only
needs to (a) spawn the Python process, (b) learn its port, (c) fetch it from the webview, and
(d) stop it on exit. Models stay inside Python (`onnxruntime`); neither shell loads them.

- **Tauri:** sidecar via `externalBin` + shell plugin; spawning is gated by capability
  permissions (claim). Webview `fetch` to `127.0.0.1` needs the CSP `connect-src` allowance.
  The sidecar must be a self-contained executable per target triple (e.g. PyInstaller-frozen).
- **Electron:** `child_process.spawn` from the main process; no permission layer, so the app's
  own code is the only gate. Same need to ship a frozen Python or a bundled interpreter.
- Equal on substance: the "model runtime integrates cleanly" test (AP-01) is decided by the
  Python sidecar, which is the same work in both. Neither needs a native ONNX binding in the shell.

### 3. Local-only (I9) and permissions

- **Tauri:** deny-by-default capabilities, CSP, and a Rust core with no Node in the renderer
  (claim) give a second fence around the network guard already in `service/`.
- **Electron:** safe only with `contextIsolation`, `sandbox`, no `nodeIntegration`, and a strict
  CSP configured by hand; misconfiguration exposes Node APIs to rendered content.

### 4. Packaging, size, offline build

- **Tauri:** small app binary (claim: a few MB plus the sidecar); needs Rust toolchain (**absent
  here**), system webview libraries on Linux (WebKitGTK dev packages), and crates fetched once
  then vendored/cached for offline builds.
- **Electron:** large binary (claim: ~100 MB+ for Chromium) and higher memory; needs only Node
  (**present here**); the Electron binary download must be cached for offline builds.
- Both: the frozen Python sidecar (pysbd, lmdb, onnxruntime, model files outside the bundle)
  likely dominates size anyway; model weights stay in the gitignored `model_dir`.

### 5. Cost to the thin demo (D-009 tier 2)

- **Tauri:** install Rust + system libs (operator action, D-005 pattern), scaffold `src-tauri/`,
  bundle `editor/`, spawn service. More setup, then low ongoing cost.
- **Electron:** fastest to a running window on this host today; ongoing cost is binary size and
  hardening.

## Summary

| Criterion | Tauri | Electron |
| --- | --- | --- |
| Hosts ESM editor | yes, after bundling; webview variance risk | yes, after bundling; one engine |
| Python service / models | sidecar + capability gate | spawn from main; no gate |
| I9 / permissions | deny-by-default (stronger) | hand-hardened |
| Size / memory | small | large |
| Toolchain on this host | Rust missing | ready |

## Recommendation

**Keep Tauri (consistent with D-007).** The deciding criterion named by AP-01 — clean model-runtime
integration — is a tie, because models live in the Python sidecar in both. The tie-breakers favour
Tauri: a permission model that backs I9, and small binaries for a local-first app. Electron's
advantages (Chromium consistency, toolchain already present) are real but are setup costs and a
testable webview risk, not design blockers.

Conditions: (1) a Rust toolchain and WebKitGTK dev libs are installed before the demo lane;
(2) the demo checks ProseMirror editing in WebKitGTK early, and Electron stays the fallback if
that fails.

## Open questions for the operator

1. Confirm D-007 stands given this record, or reopen it.
2. Approve installing Rust (rustup, pinned version) and WebKitGTK dev packages on this host,
   following D-005; which target OSes must the demo cover (Linux only?).
3. Sidecar packaging: PyInstaller-frozen binary, or a bundled venv started by the shell?
4. Port handshake: fixed loopback port, or service picks a free port and prints it on stdout?
5. Does `onnxruntime` join `requirements.txt` for the demo, or do overlays stay on stub signals?
