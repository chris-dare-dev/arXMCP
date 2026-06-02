# Critique (merged) — ui-htmx-json-fix-m1

**Critics run:** adversary only (infra-safety did not fire — no infra paths in
the diff; oss-scout not requested). This merged file is the adversary critique
verbatim, finding IDs preserved.
**Generated:** 2026-06-01T00:00:00Z
**Commit range:** `52b4397692402fd522f3363d723ece961c009e84..43eb2fdc92ec779141b3606f4d7fdee0c3e4e103`
**Verdict:** SHIP-WITH-FIXES (orchestrator concurs)

**Orchestrator merge note:** single-critic run, nothing to reconcile. F1
(MEDIUM) is cheap and directly closes the milestone's own failure class
(rendered-surface coverage) — fix in Phase 4. F2 (LOW) — defer.

## Executive summary

- **SHIP-WITH-FIXES.** The core fix is correct and verified against the
  vendored htmx 2.0.10 source: `encodeParameters` receives the FormData,
  `.forEach(value,key)` is the right iteration, bodyless POSTs serialise to
  `"{}"` (non-null) so the original empty-body 422 cannot recur. The single
  load-bearing gap is test strength, not behaviour.
- Finding counts: **0 CRITICAL, 0 HIGH, 1 MEDIUM, 1 LOW.**
- Highest-risk location: `tests/test_ui_htmx_json_contract.py:167` — the 5
  notebook-detail JSON forms are pinned only by raw-template regex, never by
  the already-available stronger TestClient served-HTML render.
- Axis 1 (htmx fix correctness): CLEAN — call site `wn(g,r,w)` →
  `encodeParameters(g,w,r)` passes FormData `w`; `E?null:wn(...)` only nulls
  for GET/DELETE (`methodsThatUseUrlParams:["get","delete"]`), so POST/PATCH
  always serialise. `overrideMimeType` runs pre-`send` (valid XHR state).
- Axis 2 (hx-ext scoping): CLEAN — the 6 JSON forms, the multipart upload
  form, and the 4 DELETE controls are sibling `<section>`/standalone controls;
  no inheritance bleed. `hx-ext` per-form is correct here (no nesting).
- Axis 4 / 5 / 6 / 7 / 8: CLEAN — DOMContentLoaded ordering + reduced-motion
  gating correct; CSP `script-src 'self' 'unsafe-inline'` already covers both
  the static file and the inline block (no widening); the project-authored
  deviation from "vendor verbatim" is sound and honestly recorded; both
  modified tests were legitimately updated (old contracts were genuinely
  buggy); all 7 `hx-post`/`hx-patch` forms are accounted for.
- The deviation from the synthesis (author a minimal extension vs. vendor the
  official one + SHA-pin) is a net de-risk, not a corner cut: it removes the
  `getExpressionVars`/`init(api)` dependency whose throw would have silently
  re-armed the 422 under htmx's `try/catch` fallback.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Cross-critic agreement

_None — no file:line region was flagged by ≥ 2 critics._

<!-- end:cross-critic-agreement -->

## Findings

### F1 — Detail-page JSON forms pinned only by raw-template regex, not served HTML

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_ui_htmx_json_contract.py:167` (class `TestPerFormHxExt`,
  cross-ref `tests/test_ui_html_pages.py:182`)
- **What:** The contract test asserts `hx-ext="json-enc"` on the 5
  notebook-detail forms (rename/topic/add-paper/discover/ingest) by reading
  the raw template file (`DETAIL_HTML = (TEMPLATES / "notebook_detail.html")
  .read_text()`) and regex-matching the `<form>` tag. The strictly stronger
  check — rendering the detail page through the existing TestClient fixture and
  asserting on the *served* HTML — is already in use in the SAME file's sibling
  test module (`tests/test_ui_html_pages.py:169` renders `/ui/notebooks/demo-nb`
  and at `:187-188` even asserts the multipart form's served attributes). Only
  the create form's hx-ext is validated against served HTML
  (`test_ui_html_pages.py:155` region asserts `hx-ext="json-enc" in body` for
  `/ui/`). The 5 detail forms — which are the bulk of the fix — are never
  asserted against rendered output.
- **Why it matters:** A raw-template regex passes even if the Jinja render path
  (a `{% block %}` override, an `{% if %}` guard, a future template-inheritance
  change) drops or relocates the attribute in the served HTML that htmx
  actually consumes. The browser sees rendered HTML, not the template file; the
  test should pin what the browser sees. This is the exact failure class the
  milestone exists to close (the JSON-direct route tests "never caught it"
  because they bypassed the rendered client surface).
- **Proposed fix:** Add one TestClient-based test to
  `tests/test_ui_htmx_json_contract.py` (or extend `test_ui_html_pages.py`)
  that POSTs a demo notebook, GETs `/ui/notebooks/demo-nb`, and asserts each of
  the 5 detail forms carries `hx-ext="json-enc"` in `r.text` while the
  `.../papers/upload` form does NOT. ~15 LOC; reuses the existing `client`
  fixture. Keep the raw-template guards too (they catch source drift cheaply).
- **Regression guard:** the new served-HTML assertions ARE the guard — they
  would fail if a future Jinja change strips hx-ext from the rendered detail
  page while leaving it in the template source.

### F2 — `_FORM_OPEN_RE` truncates on any future `>` inside a form attribute value

- **Severity:** LOW
- **Source:** adversary
- **File:** `tests/test_ui_htmx_json_contract.py:61`
  (`_FORM_OPEN_RE = re.compile(r"<form\b[^>]*?>")`)
- **What:** The form-tag extractor stops at the first literal `>`. The comment
  at `:59-60` correctly notes "none of these forms put a literal '>' inside an
  attribute value", which holds today — every `hx-on::htmx:response-error`
  handler (e.g. `notebook_detail.html:209`) uses `JSON.parse(t).detail||t` and
  classic `function(t){...}` forms, with no `=>` arrow and no `a > b`
  comparison. But if a future editor adds an arrow function or a `>` comparison
  to an `hx-on` attribute that PRECEDES the `hx-ext` attribute in the tag, the
  captured `tag` truncates before `hx-ext` and `'hx-ext="json-enc"' in tag`
  silently false-negatives (the test fails loudly with "found 0", which is at
  least not a silent pass — but it fails for the wrong reason and obscures the
  real form).
- **Why it matters:** Brittle test infrastructure that depends on an unenforced
  template convention. Low blast radius (the convention holds and a break fails
  loudly), so LOW.
- **Proposed fix:** Either (a) accept as-is (the comment documents the
  invariant), or (b) parse the form tag with an attribute-aware approach that
  respects quoted values, or (c) add a guard test asserting no form `hx-on`
  attribute contains `=>` or ` > `. Defer unless F1 is being touched anyway.
- **Regression guard:** N/A (LOW; defer).

## What was done well

- The htmx-source claims were verified against the actual vendored
  `frontend/static/htmx.min.js`, not assumed: the call site
  `wn(t,n,r){...encodeParameters(t,r,n)}` invoked as `wn(g,r,w)` confirms the
  extension receives the FormData `w` (`formData:w` in the request detail), so
  `parameters.forEach(value,key)` is provably correct.
- The bodyless-POST risk (discover/ingest) was correctly reasoned to be safe:
  `encodeParameters` returns `JSON.stringify({})` = `"{}"` (non-null), so the
  `E?null:wn(...)` path cannot reproduce the empty-body 422; the routes take no
  Pydantic body param so `{}` is harmless. Live-verified 201/204.
- The deviation from the synthesis (author a minimal extension instead of
  vendoring the official one + SHA-pin) is the better call and is honestly
  documented in both the file header and `VENDORED.md:40` — it drops the
  `getExpressionVars`/`init(api)` dependency whose throw would silently re-arm
  the 422 under htmx's `try/catch` fallback.
- Both modified tests were updated for the right reason: the old
  `test_json_encoding_shim_present` pinned the genuinely-broken `evt.detail.body`
  + `JSON.stringify` shim and an `m8 rect F1` marker that no longer exists;
  `TestUPL13` correctly swapped its inline-`<script defer>` CSP assertion for a
  DOMContentLoaded-structure assertion — neither was weakened to pass.
- The grep sweep confirms no orphaned test still asserts the old shim:
  `configRequest` / `JSON.stringify` / `globalViewTransitions` / `m8 rect F1` /
  `evt.detail` now appear only in the 3 changed files, all referencing the new
  contract.
- Per-form `hx-ext` placement is correct and minimal: the 6 JSON forms opt in,
  the multipart upload form (`hx-encoding="multipart/form-data"`) and the 4
  DELETE controls are non-descendant siblings that correctly stay out.
- CSP posture is genuinely unchanged: `CONTENT_SECURITY_POLICY_UI`
  (`server/middleware.py:172`) already permits `script-src 'self'
  'unsafe-inline'`, covering both the same-origin static file and the inline
  DOMContentLoaded block — no widening, loopback + same-origin preserved.
- The extension is pure serialization (FormData → object → `JSON.stringify`)
  with no `eval`/`innerHTML`/`Function`, so it adds no XSS surface; the
  reduced-motion gating correctly leaves htmx's `globalViewTransitions:false`
  default in place for motion-averse operators.
- The comment-stripping (`_strip_comments` / `BASE_CODE`) is well-judged: the
  base.html explanatory comments quote the very strings the guards assert the
  ABSENCE of, and stripping them before the structural assertions avoids
  false-positives without masking real code (it strips only `<!-- -->` / `{# #}`).

## Recommended rectification order

1. **F1 (MEDIUM)** — add the TestClient served-HTML assertion for the 5 detail
   JSON forms + multipart exclusion. Cheap (~15 LOC, reuses `client` fixture),
   closes the exact gap class the milestone exists for. Highest leverage.
2. **F2 (LOW)** — defer; record under `deferred_findings`. Optionally fold a
   one-line `=>`/`>`-in-`hx-on` guard in while touching the contract test for F1.

## Rectification status

- F1 (MEDIUM) — **fixed** in `c04d518` (`tests/test_ui_htmx_json_contract.py`,
  new `TestServedHtmlHxExt` + `_ui_client` TestClient fixture). Renders `/ui/`
  and `/ui/notebooks/<slug>` through the real notebooks+ui routers and asserts
  `hx-ext="json-enc"` on the SERVED forms, the multipart upload form excluded,
  and json-enc.js loaded after htmx. Regression guard: those served-HTML
  assertions. Raw-template guards retained as cheap source-drift coverage.
- F2 (LOW) — **deferred.** `_FORM_OPEN_RE` truncation only triggers on a future
  `>` inside a form attribute value; the invariant holds today and a break
  fails loudly (`found 0`), not silently. Not worth an attribute-aware parser
  now. Tracked here; revisit if an `hx-on` arrow function / `>` comparison is
  ever added to a form tag.

Re-verify gate: N/A — 0 CRITICAL / 0 HIGH findings (the gate runs only on those
severities). F1 was independently confirmed valid before fixing (the detail
forms were indeed pinned only by raw-template regex). No invalidations; no
critic invalidation-rate concern.
