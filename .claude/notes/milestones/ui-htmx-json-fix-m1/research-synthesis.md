# Research Synthesis — ui-htmx-json-fix-m1

**Mode:** single (1× Sonnet). Source brief: `research-brief-1.md` (read in full).
**Orchestrator:** merged in main session; open questions resolved live below.

## Locked design

Replace the broken inline `htmx:configRequest` JSON shim with the **official
htmx `json-enc` extension, hand-vendored as a single static file** at
`frontend/static/json-enc.js`. This is the brief's recommended option (b), chosen
over a custom inline extension (a) because the official source iterates the htmx
`parameters` **Map** correctly (`parameters.forEach(value, key)` — a plain
`Object.keys()` on a Map yields nothing), restores `hx-vals` expression types, and
is battle-tested. License **0BSD** (same as vendored htmx 2.0.10) — vendor-safe.

### Root causes (both confirmed verbatim from source)

- **Bug 1:** htmx 2.0.10 has **no `evt.detail.body` hook** — the real body-override
  point is the extension `encodeParameters(xhr, parameters, elt)` (minified source:
  `encodeParameters:function(e,t,n){return null}`). The old shim sets
  `evt.detail.body` (ignored) AND clears `evt.detail.parameters = {}` → htmx
  serializes an empty Map → empty body → FastAPI 422.
- **Bug 2:** `defer` is silently ignored on **inline** `<script>` (HTML spec: applies
  only to external scripts). The inline block runs at parse time, before the deferred
  external `htmx.min.js` loads, so `htmx.config.globalViewTransitions = true` throws
  (htmx undefined). The `document.addEventListener('htmx:configRequest', …)` on the
  same block is *fine* — it binds to `document` at parse time and the event only fires
  after htmx loads — so **only the `htmx.config.*` line needs reordering**.

### Implementation steps (the contract for Phase 2)

1. **Vendor `frontend/static/json-enc.js`** — official `bigskysoftware/htmx-extensions`
   `json-enc` source (the exact IIFE quoted in the brief §"External sources"), with a
   one-line header comment giving source URL + version + license (mirror the
   `htmx.min.js` header convention).
2. **Track it as a vendored asset:** add an entry to `frontend/static/VENDORED.md`
   and pin its SHA-256 in `tests/test_vendored_assets_integrity.py` (mirror the
   `htmx.min.js` entry exactly). It IS a third-party vendored file, so this is required.
3. **Load it in `base.html` after htmx**, both deferred (execute in declaration order):
   ```html
   <script src="/ui/static/htmx.min.js" defer></script>
   <script src="/ui/static/json-enc.js" defer></script>
   ```
4. **Remove the entire broken inline `<script defer>` shim block** (base.html
   ~lines 25–51 — the `htmx:configRequest` body shim). Do NOT keep it alongside the
   extension: its `evt.detail.parameters = {}` would sabotage `encodeParameters`
   (FM-b).
5. **Add `hx-ext="json-enc"` per-form** to every JSON-bodied form — NOT on `<body>`
   (`hx-ext` inherits to children; on `<body>` it would convert the multipart upload):
   - `index.html`: create-notebook form (`hx-post /ui/api/notebooks`).
   - `notebook_detail.html`: rename (`hx-patch …/{slug}`), topic
     (`hx-patch …/{slug}/topic`), add-paper (`hx-post …/papers`), discover
     (`hx-post …/discover`), ingest (`hx-post …/ingest`).
   - **Do NOT** add it to the multipart upload form (`hx-encoding="multipart/form-data"`,
     `…/papers/upload`). DELETE buttons are standalone (no enclosing `hx-ext` form) →
     unaffected.
6. **Bug 2 fix:** replace the broken `htmx.config.globalViewTransitions = true` with a
   parse-time inline block that registers a `DOMContentLoaded` handler (which fires
   *after* deferred scripts run, so htmx is defined), guarded on `typeof htmx` and on
   `prefers-reduced-motion`:
   ```html
   <script>
     document.addEventListener('DOMContentLoaded', function () {
       if (typeof htmx !== 'undefined') {
         htmx.config.globalViewTransitions =
           !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
       }
     });
   </script>
   ```
7. **Regression test** `tests/test_ui_htmx_json_contract.py` — template-introspection
   (proxy, NOT a browser test; state this in the docstring). Assert the 12 structural
   invariants enumerated in brief §"Regression test strategy": broken `evt.detail.body`
   and `evt.detail.parameters = {}` patterns ABSENT from base.html; `json-enc.js` exists
   and contains `encodeParameters`; base.html loads it via `<script src>`; each JSON form
   carries `hx-ext="json-enc"`; the multipart upload form does NOT; the
   `globalViewTransitions` assignment lives inside a `DOMContentLoaded` listener.

## Orchestrator synthesis note (open questions resolved)

- **OQ1 — bodyless POST acceptance (discover, ingest):** RESOLVED. Verified live:
  `discover_papers` (server/routes/notebooks.py:762) and `trigger_ingest` (:2117)
  declare **no Pydantic body parameter** (`trigger_ingest` takes only `request: Request`).
  FastAPI ignores an unexpected request body, so the extension sending `{}` with
  `Content-Type: application/json` is harmless — no 422. The PATCH rename/topic handlers
  (`NotebookRename`/`NotebookTopicUpdate`) DO require JSON, which the extension supplies.
  No special-casing of bodyless forms needed.
- **OQ2 — `xhr.overrideMimeType('text/json')`:** standard htmx 2.x behavior (htmx passes
  the real XHR to `encodeParameters`); low risk, accept as-is. If a browser ever rejects
  `text/json` it is non-fatal (overrideMimeType only affects response parsing, not the
  request). Leave the official line unchanged.

## Failure modes carried forward (Phase 3 critic axes)

(a) `hx-ext` on `<body>` breaks multipart upload → per-form placement. (b) old shim left
in → sabotages `encodeParameters` → remove it entirely. (c) DELETE getting JSON →
standalone buttons, unaffected. (d) empty optional field (`discovery_category=""`) →
server treats `""` as "not specified" (the `<option value="">` contract). (e) CSP block
→ `script-src 'self' 'unsafe-inline'` (server/middleware.py CONTENT_SECURITY_POLICY_UI)
already permits same-origin `/ui/static/json-enc.js` and the inline reduced-motion block;
**no CSP change.** (f) Map-vs-object iteration → official source uses `.forEach(value,key)`,
correct for htmx's Map.

## Acceptance criteria (from brief — the Phase 2 checklist)
1. Create-notebook browser submit sends non-empty `application/json` → 201 (no 422).
2. add-paper / discover / ingest (+rename, topic PATCH) send correct JSON → succeed.
3. Multipart upload stays multipart and still uploads.
4. Remove-notebook / remove-paper DELETE unchanged + working.
5. `htmx.config.globalViewTransitions` is `true` at runtime post-load (when motion allowed).
6. Regression test exists that fails against the pre-fix shim contract.
7. No Node/build chain; new asset is a single vendored file (+VENDORED.md + integrity pin).
8. `make test` (ruff + pytest) green.

## External writes required
**None — purely local.** All changes in `frontend/`, `tests/`. No push/PR/infra/3rd-party.
