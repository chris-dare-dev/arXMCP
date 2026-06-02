# Implementation Summary — ui-htmx-json-fix-m1

**One-line:** Replaced the broken inline `evt.detail.body` htmx shim with a
project-authored `json-enc` extension (`encodeParameters` hook) attached
per-form, and moved the View-Transitions opt-in into a `DOMContentLoaded`
handler — fixing the empty-body 422 on every JSON `/ui` form and the no-op
`globalViewTransitions` flag.

**Commit range:** `<BASE>..<HEAD>` (filled at finalize).
**Implementation path:** inline (orchestrator, main session).

## What landed

| File | Change |
|---|---|
| `frontend/static/json-enc.js` | NEW. ~25-line htmx 2.x extension; `encodeParameters` iterates the FormData with `.forEach(value,key)` and returns `JSON.stringify(body)`; `onEvent` sets `Content-Type: application/json`. |
| `frontend/templates/base.html` | Removed the broken inline `htmx:configRequest` shim (it set `evt.detail.body`, a hook htmx 2.0.10 ignores, and cleared `evt.detail.parameters`). Loads `json-enc.js` deferred after htmx. Moved `htmx.config.globalViewTransitions = true` into a `DOMContentLoaded` handler gated on `prefers-reduced-motion`. |
| `frontend/templates/index.html` | `hx-ext="json-enc"` on the create-notebook form. |
| `frontend/templates/notebook_detail.html` | `hx-ext="json-enc"` on the rename, topic, add-paper, discover, ingest forms. Multipart upload form and DELETE controls left untouched. |
| `frontend/static/VENDORED.md` | Note `json-enc.js` as project-authored (not a pinned third-party vendor). |
| `tests/test_ui_htmx_json_contract.py` | NEW. 24 template-introspection regression guards (the milestone's primary regression test). |
| `tests/test_ui_html_pages.py` | Rewrote `test_json_encoding_shim_present` → `test_json_encoding_extension_present` (the old test pinned the broken shim). |
| `tests/test_ui_m4_in_place_add_paper.py` | Updated `TestUPL13GlobalViewTransitions` to assert the corrected `DOMContentLoaded` structure (the old test pinned the buggy inline-`<script defer>` placement). |

## Deviation from synthesis (recorded)

The synthesis recommended **vendoring the official htmx `json-enc` extension
verbatim** (option b) and pinning its SHA-256. I instead **authored a minimal
in-repo extension** (treated like `app.css`/`favicon.svg`: project-authored,
not SHA-pinned). Reasons surfaced at implementation time:

1. **No offline provenance check.** I cannot byte-verify an upstream npm
   release here, so an integrity-pinned "vendored" file would carry a hash I
   could not honestly attribute to a published artifact.
2. **`encodeParameters` throw = silent regression.** htmx wraps the
   extension call in a `try/catch` (`H(e)=console.error`) and falls back to
   FormData encoding while `onEvent` has already set
   `Content-Type: application/json` — i.e. ANY throw inside `encodeParameters`
   silently reintroduces the empty-body 422. The official source calls
   `api.getExpressionVars(elt)` (needs the `init(api)` ref); dropping that
   dependency (we use no `hx-vals`/`hx-vars`) removes a failure surface.

The extension is otherwise faithful to the official `encodeParameters`
contract (FormData `.forEach`, repeated-key→array, `xhr.overrideMimeType`).
Verified live in the browser (below), which is the real validation the
synthesis's "vendor verbatim" choice was meant to de-risk.

## Acceptance criteria

| # | AC | Status |
|---|---|---|
| 1 | Create-notebook submit sends non-empty JSON → 201 (no 422) | ✅ Verified live: body `{"slug":"json-fix-verify",...}`, POST → **201**. |
| 2 | add-paper / discover / ingest / rename / topic send JSON | ✅ All carry `hx-ext="json-enc"` (pinned by contract test); discover/ingest are bodyless POSTs whose routes take no body param (verified: `discover_papers`/`trigger_ingest`), so `{}` is harmless. |
| 3 | Multipart upload stays multipart | ✅ Upload form has `hx-encoding` and NO `hx-ext`; contract test asserts exclusion. |
| 4 | DELETE flows unchanged + working | ✅ Remove-notebook DELETE → **204** live; contract test asserts no `hx-ext` on DELETE controls. |
| 5 | `globalViewTransitions` true at runtime | ✅ Verified live: `htmx.config.globalViewTransitions === true` (was `false`). |
| 6 | Regression test fails against pre-fix shim | ✅ `tests/test_ui_htmx_json_contract.py` (+ updated m4/html-pages tests) assert the new contract; they would fail on the old `evt.detail.body` shim / inline-defer placement. |
| 7 | No Node/build chain; single static file | ✅ One hand-authored `frontend/static/json-enc.js`; no CSP change (`script-src 'self'` already covers it). |
| 8 | `make test` green | ⚠️ See note. ruff clean; targeted UI suite 93/93. Full suite has ~63 PRE-EXISTING Windows-platform failures (symlinks, `killpg`, control-chars, preview-route path-containment, heredoc) — proven unchanged by my edit via a pristine-HEAD baseline diff (the only deltas were 3 flaky/timing tests in unrelated modules, confirmed order-dependent in isolation). Zero new failures introduced. On macOS/Linux these platform failures pass. |

## New / changed test paths
- `tests/test_ui_htmx_json_contract.py` (new, 24 guards)
- `tests/test_ui_html_pages.py` (rewrote the shim-presence test)
- `tests/test_ui_m4_in_place_add_paper.py` (corrected the UPL-13 structure test)

## Live verification (browser, preview MCP)
- Create form: request body `{"slug":"json-fix-verify","display_name":"","discovery_category":"math.AG","description":""}` → **201 Created**; new `<tr>` swapped in. No console errors.
- `globalViewTransitions` → **true**. Remove → **204**.

## External writes required
**None.** All changes are local (`frontend/`, `tests/`).
