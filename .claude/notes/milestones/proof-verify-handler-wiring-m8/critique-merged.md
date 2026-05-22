# Critique — proof-verify-handler-wiring-m8 (merged)

**Critics fired:** adversary (1; infra-safety / oss-scout / frontend-UX
did not fire — no infra paths in diff, no OSS-scout opt-in, no frontend
critic in arXMCP).

**Verdict:** SHIP-WITH-FIXES (adversary).

## Findings summary

| ID | Sev | Source | Title | Phase-4 status |
|---|---|---|---|---|
| F1 | CRITICAL | adversary | htmx create + paste forms broken in browser — `hx-ext="json-enc-form-conv"` references a non-existent extension; forms post `application/x-www-form-urlencoded` against JSON-only m7 routes → 422 in the browser | CLOSED — added `htmx:configRequest` shim in `base.html` that converts form-encoded POST/PUT/PATCH bodies to JSON (bypasses multipart uploads via `hx-encoding` check); removed bogus `hx-ext`; deleted the misleading "if posting fails, post JSON directly" note. Regression test `TestIndexPage::test_json_encoding_shim_present` pins the shim's presence + load-bearing pieces |
| F2 | HIGH | adversary | No CSP header on UI responses — defense-in-depth gap | CLOSED — added `CONTENT_SECURITY_POLICY_UI` constant + per-path emit in `SecurityHeadersMiddleware` scoped to `/ui/*`. Policy: `default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'`. `'unsafe-inline'` is a known trade-off (htmx `hx-on::` attributes + the F1 inline shim require it); the defense remaining after the allowance is third-party-origin blocking. Documented future-tightening path in the constant's docstring. 4 regression tests in `TestCSPHeaderOnUiSurface` |
| F3 | MEDIUM | adversary | `tmp_path` collision on concurrent uploads (same paper_id) — `write_bytes` is not atomic to itself | **DEFERRED** — operator-only access via loopback + same-origin makes the realistic concurrency window narrow; the documented "atomic" claim was overstated but the actual data risk is low. Concurrency test requires `httpx.AsyncClient` + `asyncio.gather` infrastructure beyond what the existing test fixture provides. Tracked for a future hardening pass alongside m9's background-worker concurrency design |
| F4 | MEDIUM | adversary | `_BYTE_CAP_EXEMPT_PREFIXES` extension to `/ui` is broader than needed; JSON sub-routes don't need 256 KB exemption | CLOSED — narrowed from `/ui` to `/ui/static`. The HTML page routes (`/ui/`, `/ui/notebooks/{slug}`) and the JSON routes (`/ui/api/*`) now all enforce the 256 KB response cap. 5 regression tests in `TestNarrowedByteCapExemptPrefixes` covering the static-exempt + api-not-exempt + html-not-exempt + existing-exempt + prefix-vs-substring boundary |
| F5 | MEDIUM | adversary | CHANGES.md says "+70 tests" / "14 middleware tests" but actual is "+67 in new files / 11 middleware" (the +3 from m7-test edits reconciles to the suite total) | CLOSED — corrected both CHANGES.md and the implementation-summary to "+67 net-new across three new files + ~3 from m7-test edits = +70 total suite delta"; corrected "14" → "11" for the middleware-test file |
| F6 | MEDIUM | adversary | Vendored htmx file has no recorded SHA-256 — re-vendor has no out-of-band integrity check | CLOSED — added `frontend/static/VENDORED.md` manifest recording the SHA-256 (`5e6ee42df72f91d6f5ddcfd746ed157f96071a9ad68df148ead526c864d3ddc7`). New test `tests/test_vendored_assets_integrity.py` (3 tests) pins the hash so a re-vendor must update both the file AND the test in lockstep |
| F7 | LOW | adversary | Upload error pane displays raw JSON; bad UX | CLOSED (rolled in with F1) — replaced `event.detail.xhr.responseText` with a try/JSON.parse/.detail extraction in all three error handlers (create, paste, upload) |
| F8 | LOW | adversary | `_paper_row_html` is Python string concat, not a Jinja2 partial | **DEFERRED** — refactor; existing escape protection is correct. Tracked for a future template-cleanup pass alongside m9's status-row rendering |

## Rectification artifacts

- `frontend/templates/base.html` — added the htmx:configRequest
  JSON-encoding shim (F1) + the m7 route compatibility note. The
  shim listens for `htmx:configRequest`, converts non-multipart
  POST/PUT/PATCH bodies to JSON, leaves DELETE and multipart
  uploads untouched.
- `frontend/templates/index.html` — removed bogus
  `hx-ext="json-enc-form-conv"`; replaced the JSON-blob error
  display with a `.detail`-extraction expression; deleted the
  misleading "if posting fails" note (F1 + F7).
- `frontend/templates/notebook_detail.html` — same `.detail`
  extraction for the paste-form + upload-form error handlers (F7).
- `server/middleware.py` — added `CONTENT_SECURITY_POLICY_UI`
  constant + `_CSP_UI_PREFIXES = (b"/ui",)` + per-path emit in
  `SecurityHeadersMiddleware.__call__` (F2). The `unsafe-inline`
  trade-off + future-tightening path documented in the constant's
  docstring.
- `server/main.py` — narrowed `_BYTE_CAP_EXEMPT_PREFIXES` from
  `/ui` to `/ui/static` (F4); updated the inline comment naming
  F4 + why `/ui/api/*` and `/ui/notebooks/{slug}` should NOT be
  exempt.
- `frontend/static/VENDORED.md` (NEW) — manifest of vendored
  third-party static assets with recorded SHA-256 per file +
  re-vendor recipe.
- `tests/test_vendored_assets_integrity.py` (NEW, 3 tests) —
  pins the htmx SHA-256, asserts the file exists, asserts the
  header comment is preserved (F6).
- `tests/test_ui_html_pages.py` — extended with
  `TestIndexPage::test_json_encoding_shim_present` (F1),
  `TestCSPHeaderOnUiSurface` (4 tests for F2), and
  `TestNarrowedByteCapExemptPrefixes` (5 tests for F4).
- `CHANGES.md` + `implementation-summary.md` — corrected the test
  counts to match reality (F5).

## Final test count

`make test`: **2438 passed** (+13 from rect: 5 narrowed-prefix +
4 CSP + 1 F1 shim + 3 vendored-integrity), 9 skipped, 1 xfailed.
Ruff clean.

## Deferred findings

- **F3 (MEDIUM)** — concurrent-upload tmp-write race. Operator-only
  access via loopback + same-origin makes the realistic concurrency
  window narrow. Concurrency test requires `httpx.AsyncClient` +
  `asyncio.gather` plumbing beyond the existing fixture. Tracked
  for a hardening pass alongside m9 (background-worker concurrency).
- **F8 (LOW)** — `_paper_row_html` Python string concat vs Jinja2
  partial. Existing `html.escape()` protection is correct; refactor
  is consistency-only. Defer.

## Re-verify gate notes

All CRITICAL + HIGH findings re-verified before fixing:

- **F1 (CRITICAL):** reproduced empirically — `client.post('/ui/api/notebooks',
  data={'slug': 'demo-nb'})` returned 422 with
  `{"detail":[{"type":"model_attributes_type", "loc":["body"], ...}]}`
  per the adversary's reproducer. The `hx-ext="json-enc-form-conv"`
  attribute resolves to a no-op (no such extension loaded). The
  templates currently render in a way that breaks the primary
  browser path despite the 70 JSON-direct tests passing.
- **F2 (HIGH):** confirmed `SecurityHeadersMiddleware` adds only
  `X-Content-Type-Options` + `X-Frame-Options`; no CSP set anywhere
  in the server middleware stack.

Zero findings invalidated. Adversary invalidation rate: **0 / 2
(0%)** for HIGH+CRITICAL; well under the 40% threshold.

## Cross-critic agreement

N/A — only one critic fired (adversary).
