# Research Brief — ui-htmx-json-fix-m1

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-06-01T00:00:00Z

## In-codebase context

### Current broken shim (base.html lines 25–62, verbatim)

```html
<script defer>
  document.addEventListener('htmx:configRequest', function (evt) {
    var verb = (evt.detail.verb || '').toLowerCase();
    if (verb !== 'post' && verb !== 'put' && verb !== 'patch') return;
    var el = evt.detail.elt;
    if (el && el.getAttribute && el.getAttribute('hx-encoding') === 'multipart/form-data') {
      return;
    }
    if (evt.detail.headers && evt.detail.headers['Content-Type'] === 'application/json') {
      return;
    }
    var params = evt.detail.parameters || {};
    if (Object.keys(params).length === 0) return;
    evt.detail.headers = evt.detail.headers || {};
    evt.detail.headers['Content-Type'] = 'application/json';
    var body = {};
    Object.keys(params).forEach(function (k) { body[k] = params[k]; });
    evt.detail.parameters = {};
    // htmx 2.x reads evt.detail.body when set; falls back to
    // serializing evt.detail.parameters otherwise.
    evt.detail.body = JSON.stringify(body);
  });
  htmx.config.globalViewTransitions = true;
</script>
```

**BUG 1 root cause confirmed:** htmx 2.0.10 minified source exposes no `evt.detail.body`
hook — the extension API has `encodeParameters(xhr, parameters, elt)` as the body-override
point (verified in htmx.min.js: `encodeParameters:function(e,t,n){return null}`). The shim
also clears `evt.detail.parameters = {}`, so htmx serializes an empty parameter map → empty
body. The `discover` form (no fields) hits the `Object.keys(params).length === 0` early-return
guard and sends no Content-Type header either, causing different 422 behavior.

**BUG 2 root cause confirmed:** `defer` on an inline `<script>` is silently ignored by all
browsers (HTML spec: `defer` applies only to external scripts). The `htmx.config.globalViewTransitions
= true` line runs at parse-time, before the deferred `htmx.min.js` loads → `htmx` is undefined
→ ReferenceError silently swallowed (or TypeError depending on browser). The `document.addEventListener`
call on the same `<script>` runs at parse-time too, but `htmx:configRequest` events only fire after
htmx is loaded and bound to the document — so the listener registration is actually fine even at
parse-time (it attaches to `document` before htmx loads; the event fires later, after load). ONLY
the `htmx.config.*` line needs ordering repair.

### Forms inventory

**JSON POST/PATCH forms (must get json-enc):**
- `index.html` — `hx-post="/ui/api/notebooks"` (create notebook; fields: slug, display_name, discovery_category, description)
- `notebook_detail.html` — `hx-patch="/ui/api/notebooks/{{ notebook.slug }}"` (rename; field: display_name)
- `notebook_detail.html` — `hx-patch="/ui/api/notebooks/{{ notebook.slug }}/topic"` (topic; fields: discovery_category, description)
- `notebook_detail.html` — `hx-post="/ui/api/notebooks/{{ notebook.slug }}/papers"` (add paper; field: arxiv_url)
- `notebook_detail.html` — `hx-post="/ui/api/notebooks/{{ notebook.slug }}/discover"` (discover; NO fields — bodyless POST)
- `notebook_detail.html` — `hx-post="/ui/api/notebooks/{{ notebook.slug }}/ingest"` (ingest; NO fields — bodyless POST)

**Must NOT get json-enc:**
- `notebook_detail.html` — `hx-post=".../papers/upload"` with `hx-encoding="multipart/form-data"` (multipart)
- `index.html` — `hx-delete=".../notebooks/{{ nb.slug }}"` (bodyless DELETE, no form)
- `notebook_detail.html` — `hx-delete=".../notebooks/{{ notebook.slug }}"` (bodyless DELETE, no button form)
- `notebook_detail.html` — `hx-delete=".../papers/{{ p.paper_id }}"` (bodyless DELETE)

**No `hx-ext` exists anywhere in current templates** — confirmed by inspection.

### CSP (verbatim from server/middleware.py lines 170–177)

```python
CONTENT_SECURITY_POLICY_UI: bytes = (
    b"default-src 'self'; "
    b"script-src 'self' 'unsafe-inline'; "
    b"style-src 'self' 'unsafe-inline'; "
    b"img-src 'self' data:; "
    b"connect-src 'self'; "
    b"frame-ancestors 'none'"
)
```

`script-src 'self' 'unsafe-inline'` permits BOTH same-origin static files AND inline scripts.
The comment at middleware.py:146–163 explicitly documents this as load-bearing for the F1 shim
and `hx-on::*` attributes. A newly vendored `frontend/static/json-enc.js` served from
`/ui/static/json-enc.js` is covered by `'self'` — **no CSP change required**.

### Body-size exemption (server/main.py confirmed)

`/ui/static` is in `BODY_SIZE_CAP_EXEMPT_PREFIXES`. Static file responses bypass the 256 KB cap.
The `/ui/api/*` mutation endpoints do NOT have the exemption, but their REQUEST bodies are small
(well under 256 KB) — only RESPONSE bodies are capped. Not relevant to this fix.

### Design note constraint (06-mcp-server-design.md, verbatim)

> **Hard constraint: no SPA, no Node/npm build chain.** htmx is vendored under
> `frontend/static/`; templates live under `frontend/templates/`.

Any new asset is a hand-authored or hand-vendored single static file under `frontend/static/`.

### VENDORED.md constraint

Only third-party vendored assets are tracked in `VENDORED.md` + `tests/test_vendored_assets_integrity.py`.
Project-authored files (`app.css`, `favicon.svg`) are explicitly NOT tracked. A project-authored inline
extension or a vendored `json-enc.js` from the htmx-extensions repo BOTH require updating `VENDORED.md`
and the integrity test ONLY if the file is a third-party vendored asset.

## Prior decisions and lessons

Git log (recent): `52b4397 docs(repo): split README into chapters + add LICENSE` — no UI changes in
the most recent commits; the broken shim has been in `base.html` since it was introduced in the m8
rect F1 commit.

The comment in `base.html` (`<!-- m8 rect F1 -->`) documents this shim as a deliberate fix for the
exact symptom it is now causing. The fix was wrong from the start (htmx 2.x has no `evt.detail.body`
hook) but passed CI because tests POST JSON directly to FastAPI endpoints, never exercising browser
serialization.

Memory note `2026-05-31 — ui-attractive-polish-m3 — htmx-request-class-on-form-not-button` is not
directly relevant here.

**No tool-schema re-pinning required** — this milestone touches only `frontend/` templates and
static assets, not `server/tools.py::ALL_TOOLS`.

## External sources

**htmx 2.0.10 extension API** (verified from minified source):
- `htmx.defineExtension(name, {init, onEvent, encodeParameters})` is the real API.
- `encodeParameters(xhr, parameters, elt)` — when the extension returns a non-null string,
  htmx uses that string as the request body (the real body-override point).
- `parameters` is a **Map** (not FormData, not plain object) — iteration is
  `parameters.forEach(function(value, key) {...})` per the official json-enc extension source.
- `onEvent('htmx:configRequest', evt)` — setting `evt.detail.headers['Content-Type']` here
  works and is the correct place to set the Content-Type header for an extension.

**Official json-enc extension source** (bigskysoftware/htmx-extensions, MIT license):
```javascript
(function() {
  let api
  htmx.defineExtension('json-enc', {
    init: function(apiRef) { api = apiRef },
    onEvent: function(name, evt) {
      if (name === 'htmx:configRequest') {
        evt.detail.headers['Content-Type'] = 'application/json'
      }
    },
    encodeParameters: function(xhr, parameters, elt) {
      xhr.overrideMimeType('text/json')
      const object = {}
      parameters.forEach(function(value, key) {
        if (Object.hasOwn(object, key)) {
          if (!Array.isArray(object[key])) { object[key] = [object[key]] }
          object[key].push(value)
        } else {
          object[key] = value
        }
      })
      const vals = api.getExpressionVars(elt)
      Object.keys(object).forEach(function(key) {
        object[key] = Object.hasOwn(vals, key) ? vals[key] : object[key]
      })
      return (JSON.stringify(object))
    }
  })
})()
```

License: **0BSD** (same as htmx itself, per the htmx-extensions repo). Safe to vendor.

**Bodyless POST behavior:** when `parameters` is an empty Map (discover, ingest forms have no inputs),
`encodeParameters` returns `"{}"`. FastAPI accepts `{}` for endpoints with no required body fields or
`Optional` body — confirmed by milestone brief ("A direct fetch() with a real JSON body returns 201").
The discover and ingest endpoints either accept an empty JSON object or have a `Optional[Body]` — the
implementer must confirm, but sending `{}` is strictly better than sending `""` with no Content-Type.

## Recommendation

**Vendor the official json-enc extension as `frontend/static/json-enc.js`** (option b), using the
exact source above with a 1-line header comment (version + source URL + license, matching the
`htmx.min.js` convention). Do NOT write a custom inline extension.

Reasoning: the official extension is already battle-tested, handles the Map iteration correctly,
restores `hx-vals`/`hx-vars` expression types (future-proofing), and the `xhr.overrideMimeType`
call is correct defensive practice. The custom inline approach (option a) would require re-discovering
the Map iteration behavior and risks subtle bugs (e.g., iterating with `Object.keys()` on a Map
returns nothing).

**Implementation steps:**

1. Vendor `frontend/static/json-enc.js` — prepend the standard 1-line header comment, paste the
   official source. Add to `VENDORED.md` inventory. Update `tests/test_vendored_assets_integrity.py`
   to pin its SHA-256 (mirroring the htmx.min.js test entry).

2. Load it in `base.html` after `htmx.min.js`:
   ```html
   <script src="/ui/static/htmx.min.js" defer></script>
   <script src="/ui/static/json-enc.js" defer></script>
   ```
   Both external scripts with `defer` load in document order, with `htmx.min.js` first.
   `json-enc.js` calls `htmx.defineExtension` at the top level of the IIFE — this fires after
   htmx is loaded because both scripts are deferred (deferred scripts execute in declaration order
   after DOMContentLoaded parsing). This is correct.

3. **Remove the entire existing `<script defer>` block** (lines 25–62 in base.html). The
   `htmx:configRequest` listener is replaced by the extension's `onEvent`. The broken
   `evt.detail.body` assignment is gone. **Do not keep the old shim alongside the extension** —
   the old shim clears `evt.detail.parameters = {}` which would sabotage `encodeParameters`.

4. **Add `hx-ext="json-enc"` to each JSON POST/PATCH form** individually (NOT on `<body>`):
   - `index.html`: the create-notebook `<form hx-post="/ui/api/notebooks"`
   - `notebook_detail.html`: the rename form, topic form, add-paper form, discover form, ingest form

   `hx-ext` inherits to children per htmx inheritance rules, so placing it on `<body>` would
   propagate to the multipart upload form. Placing it per-form avoids this. The multipart upload
   form does NOT get `hx-ext="json-enc"`. DELETE buttons are standalone `<button>` elements with
   no enclosing form — they are unaffected regardless.

5. **Bug 2 fix:** add a `DOMContentLoaded` listener for `htmx.config.globalViewTransitions` in the
   same `json-enc.js` loaded file, OR as a separate small inline block that does NOT reference `htmx`
   at parse-time:
   ```html
   <script>
     document.addEventListener('DOMContentLoaded', function() {
       if (typeof htmx !== 'undefined') {
         htmx.config.globalViewTransitions =
           !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
       }
     });
   </script>
   ```
   This is a non-deferred inline block — runs at parse-time, registers a DOMContentLoaded handler
   that fires after deferred scripts execute, so `htmx` IS defined when the assignment runs.
   Note the `prefers-reduced-motion` guard per the milestone brief requirement.

## Failure modes

| # | Trigger | Symptom | Mitigation |
|---|---|---|---|
| (a) | `hx-ext="json-enc"` placed on `<body>` | Multipart upload form sends JSON instead of multipart → server returns 422; file upload breaks | Place `hx-ext` per-form on only the JSON forms; multipart form has no `hx-ext` |
| (b) | Old shim left in place alongside extension | Shim fires `htmx:configRequest`, clears `evt.detail.parameters = {}`; extension's `encodeParameters` receives empty Map → sends `{}` for all forms including ones with data | Remove the entire old shim block; the extension replaces it completely |
| (c) | DELETE buttons accidentally get JSON | DELETEs are standalone `<button hx-delete>` elements, not inside a `<form hx-ext="json-enc">`. `hx-ext` does not apply because htmx inheritance walks DOM ancestors — a button not inside an `hx-ext` form has no extension active. DELETEs with no body are unaffected | Confirmed safe by the per-form placement strategy; no mitigation needed |
| (d) | Empty optional field serialization (`discovery_category=""`) | `encodeParameters` maps the empty string value to `{"discovery_category": ""}`. FastAPI's `NotebookCreate` has `discovery_category: Optional[str] = None` — server accepts `""` and treats it as "not specified" (confirmed by the `<option value="">Not specified</option>` pattern). No server-side breakage | Confirm server accepts empty string for optional fields before shipping |
| (e) | CSP blocks `json-enc.js` | If CSP were `script-src 'self'` without `'unsafe-inline'`, a same-origin static script is still allowed. Current CSP has `'self'` covering `/ui/static/json-enc.js` → no block. `hx-on::*` inline event handlers remain permitted by `'unsafe-inline'` | No action needed; CSP already permits same-origin scripts |
| (f) | `parameters.forEach` called on wrong type | If htmx passes a plain object instead of a Map to `encodeParameters`, `.forEach` is undefined → TypeError → extension silently fails. The htmx 2.0.10 source confirms `parameters` is always a Map (the IIFE closure passes the parameter collection as a Map). The official extension relies on this | Pin the htmx version (already done at 2.0.10); test verifies extension is present |

## Regression test strategy

No JS test runner, no Node. The achievable test is a **template-introspection pytest** at
`tests/test_ui_htmx_json_contract.py`. It is a proxy, not a browser test — it verifies
structural invariants only, not runtime serialization. Be explicit about this limitation in
the test docstring.

**Recommended concrete assertions:**

1. `base.html` does NOT contain the string `evt.detail.body` (old broken pattern absent).
2. `base.html` does NOT contain `evt.detail.parameters = {}` (the sabotage pattern absent).
3. `frontend/static/json-enc.js` exists and contains `encodeParameters` (extension present).
4. `base.html` loads `/ui/static/json-enc.js` via a `<script src=...>` tag.
5. `index.html` create-notebook form has `hx-ext="json-enc"`.
6. `notebook_detail.html` rename form has `hx-ext="json-enc"`.
7. `notebook_detail.html` topic form has `hx-ext="json-enc"`.
8. `notebook_detail.html` add-paper form has `hx-ext="json-enc"`.
9. `notebook_detail.html` discover form has `hx-ext="json-enc"`.
10. `notebook_detail.html` ingest form has `hx-ext="json-enc"`.
11. `notebook_detail.html` upload form (`hx-encoding="multipart/form-data"`) does NOT have `hx-ext="json-enc"`.
12. `base.html` `htmx.config.globalViewTransitions` assignment is inside a `DOMContentLoaded` listener
    (not a bare top-level statement).

The server-side JSON acceptance is already tested by existing routes tests (they POST JSON directly).
This does NOT catch the client bug (as the milestone brief notes); that is precisely why the template-
introspection test is the right complement.

## Open questions

1. **Bodyless POST endpoints (discover, ingest):** confirm that `POST /ui/api/notebooks/{slug}/discover`
   and `POST .../ingest` accept an empty JSON body `{}` with `Content-Type: application/json`. If the
   routes require `None` body (no Content-Type), the `onEvent` hook setting the header unconditionally
   for all POSTs may cause a 422. Check the Pydantic models for these routes.
   *Likely fine* — both routes appear to accept no body parameters — but the implementer should
   grep for the FastAPI route signatures before coding.

2. **`xhr.overrideMimeType('text/json')` side-effect:** the official extension calls this on the XHR
   object. Confirm htmx 2.0.10 passes the real XHR to `encodeParameters` (not a mock). This is
   standard behavior but worth a quick check in the minified source for the `encodeParameters` call site.

## External writes the implementation will require

None — this milestone is purely local.

| Type | Target | Why |
|---|---|---|
| (none) | — | All changes are in `frontend/`, `tests/`. No push, no PR, no infra, no third-party API calls. |
