# Spike-2 — UI security audit scoping against e4's incremental surface

**Slug:** `ui-attractive-polish-spike-2`
**Date:** 2026-05-31
**Validates soft dependency on `chris-dare-dev/arXMCP#9`** — the deferred UI security audit — before e4 promotes from Later → Next.
**Status:** **DECISION: hybrid (a) — define m4-specific audit-pass criteria; do NOT block m4 on the full issue #9 audit; issue #9 stays open as a separate tracking effort.**
**Budget:** ≤ 2 days. Actual: ~45 min (issue #9 reads clean; fragment-rendering precedent is well-established; e4 adds no novel attack surface beyond what's already audited-by-pattern).

---

## TL;DR

The roadmap framed Spike-2 as a binary fork:

> (a) define audit-pass criteria with the `security-reviewer` specialist + open a
> tracking issue for the audit's actual landing, OR (b) descope e4 to not-blocking
> by descoping UPL-12 to documentation-only ("plan to convert when the audit lands").

**The right answer is neither extreme.** Issue #9 is the tracking issue (it already
exists with full audit scope + 5 open questions); the audit landing is a separate,
larger effort that **does not need to gate m4**. e4's incremental code surface
follows an established pattern (`_paper_row_html`, `_display_name_fragment`,
`ui_status_badge`, `_ingest_status_fragment`) that's already in production with the
`html.escape()` per-value discipline. The pre-existing precedent IS the de-facto
audit; m4 just has to match the pattern.

**Decision:** ship m4 with UPL-12 in-place swaps as planned. Define an explicit
**e4 pre-flight checklist** (below) that the m4 milestone-pipeline (research +
adversary) verifies. Issue #9 stays open for the broader audit (CSRF posture,
upload polyglot, CSP `unsafe-inline` scope, etc. — the 5 open questions in the
issue body), independent of m4.

---

## Why the existing precedent IS the audit

Issue #9 itemizes 5 open questions; **none of them are widened by UPL-12**:

| #9 open question | UPL-12 incremental impact |
|---|---|
| 1. CSRF without explicit tokens — `SecFetchSiteMiddleware` sufficiency | **None.** UPL-12 reuses the existing `/ui/api/notebooks/*` mutation routes; the SecFetchSite carve-out at `("/ui",)` covers them already. No new mutation routes. |
| 2. Upload polyglot / zip-bomb completeness | **None.** UPL-12 doesn't touch upload paths. The Upload card at `notebook_detail.html:118-120` already uses `hx-swap="beforeend"` and `_paper_row_html` — no change. |
| 3. Path-traversal completeness on the preview route | **None.** UPL-12 doesn't touch the preview route. |
| 4. CSP `unsafe-inline` scope (inline JSON-shim) | **None.** UPL-12 + UPL-13 + UPL-22 all live within the existing `'unsafe-inline'` allowance (UPL-13 is a 1-line config flag per Spike-1; UPL-22 is CSS-only; UPL-12 is server-side fragment rendering with no new inline JS). |
| 5. Stored-XSS on operator-authored fields — render path divergence | **Marginal — managed by the pre-flight checklist.** UPL-12 introduces a new fragment for the create-notebook flow (currently `location.reload()` → instead, return a `<tr>` row to append to `#notebook-list`). The new fragment IS another render path for `display_name` + `slug` and `created_at`. Pattern-match `_paper_row_html` (which already does the same for `paper_id` + `added_at`) and the divergence risk is bounded. |

Stated plainly: **the audit's "things to check" list is about general posture; UPL-12 doesn't move any of those posture knobs**. The only marginal axis is #5 (the new render path for `display_name` in the create-fragment), and the existing per-value `html.escape()` discipline in `_paper_row_html` is the proven mitigation.

---

## UPL-12 incremental surface (what m4 actually adds)

UPL-12 v0 narrowed per the m2 final-report challenger: ship only the **add-paper
in-place swap** in m4 v0, hold the **create-notebook** and **remove-notebook**
conversions for a m4 v1 follow-on. That narrows the m4 audit surface to ONE new
fragment-rendering touch:

### 1. Add-paper by URL (`POST /ui/api/notebooks/{slug}/papers`) — return fragment instead of triggering `location.reload()`

- **Current behavior** (`notebook_detail.html:97`): the form's
  `hx-on::htmx:after-request` triggers `location.reload()` on success. The
  endpoint returns JSON.
- **New behavior**: when `HX-Request: true` is in the request headers, the
  endpoint returns an HTML `<tr>` fragment (same shape as `_paper_row_html`)
  for `hx-swap="beforeend" hx-target="#papers-tbody"`. JSON clients keep
  getting the JSON body.
- **Audit surface delta**: ONE new content-negotiation branch + ONE new
  helper function (or extend `_paper_row_html` to handle the URL-paste's
  resolved-paper-id shape, which differs from upload only in WHERE
  `paper_id` comes from — the URL-paste extracts it from the arXiv URL via
  `is_valid_arxiv_paper_id`, NOT from operator-typed input).
- **Pre-flight check** (m4 adversary): the new fragment MUST call
  `_paper_row_html` (or an equivalent that uses `html.escape()` per
  interpolated value); MUST NOT introduce `| safe` or `Markup(...)`;
  MUST NOT bypass `validate_slug`.

### 2. View Transitions config flag (UPL-13) — 1 LOC in `base.html`

Per Spike-1: `htmx.config.globalViewTransitions = true` in the existing inline
JSON-shim. No new inline-JS allowance (`'unsafe-inline'` already permits it).
No new event surface. No content-negotiation. **Zero audit-widening.**

### 3. Footer-badge flash (UPL-22) — CSS-only

Pure additions to `frontend/static/app.css`. No new JS, no new template
attributes, no new endpoints. **Zero audit-widening.**

---

## e4 pre-flight checklist (m4 milestone-pipeline must verify)

This list is the m4-narrow analogue of the full issue #9 audit. Each item is
mechanically verifiable by the m4 adversary critic during Phase 3:

### Server-fragment correctness (the load-bearing axis — issue #9 open Q5)

- [ ] **The new add-paper HTML branch uses `html.escape()` for every
      interpolated value.** Pattern-match the m8 `_paper_row_html` at
      `server/routes/notebooks.py:1575-1604` — every column value (`slug`,
      `paper_id`, `added_at`, `preview_url`) wraps through `html.escape()`.
      Forgetting one is the proven XSS vector. Regression guard: extend
      `tests/test_upload_handler.py` (or add a sibling `test_add_paper_*.py`)
      with a payload-injection unit test that sends `display_name="<script>"`
      and asserts the rendered fragment contains `&lt;script&gt;` not
      `<script>`.
- [ ] **NO `| safe` filter in any new template OR helper.** Grep
      `frontend/templates/ -name '*.html'` and `server/routes/` for `| safe`
      and `Markup(`. Expected count: 0 (m1/m2/m3 didn't introduce any; m4
      must preserve that).
- [ ] **Content-negotiation on `HX-Request: true` header** routes
      browser-htmx requests to the fragment branch and curl/non-htmx clients
      to the JSON branch. The HX-Request header is a CLIENT hint, not a
      trust boundary — confirm the JSON branch's existing input validation
      is still applied on the fragment branch (i.e. don't fork validation;
      fork only the response renderer).
- [ ] **The fragment renderer never echoes the raw request body or any
      header value.** Only validated, escaped, server-controlled values are
      interpolated (in this case: the parsed `paper_id` from
      `is_valid_arxiv_paper_id`, the canonical `added_at` ISO timestamp
      from the store, the canonical `slug` from the path parameter after
      `validate_slug`).

### Middleware integrity (issue #9 open Q1)

- [ ] **`SecFetchSiteMiddleware` carve-out at `("/ui",)`** still covers
      `/ui/api/notebooks/*`. The new fragment behavior doesn't change the
      route surface — it changes the response body for HX-Request clients
      only. Confirm `server/middleware.py` is not edited (`git diff`
      should show zero hunks there).
- [ ] **Origin + Host loopback validation** unchanged. Same as above —
      `server/middleware.py` is OUT of m4's diff.
- [ ] **No new CSP directive needed.** The fragment is `'self'`-served
      HTML; the existing `img-src 'self' data:` and `script-src 'self'
      'unsafe-inline'` cover everything UPL-12 + UPL-13 + UPL-22 introduce.
      Confirm by inspection of `CONTENT_SECURITY_POLICY_UI` (unchanged) and
      `CONTENT_SECURITY_POLICY_PREVIEW` (untouched — UPL-12 doesn't touch
      the preview route).

### Input validation invariants (issue #9 open Q3)

- [ ] **`validate_slug` is called at every new mutation entry-point.** The
      add-paper route already calls it; confirm the fragment-branch code
      path runs validate_slug BEFORE constructing the fragment (i.e. don't
      forget to gate on slug validity just because we're returning HTML
      now).
- [ ] **`is_valid_arxiv_paper_id` rejects unparseable URLs before any
      server-side state mutation.** Existing path, just confirm it's still
      the gate on the new branch.
- [ ] **`Pydantic Field(max_length=...)` bounds unchanged** on the
      `AddPaperByUrl` model (or whatever model handles the URL-paste
      payload). The fragment branch shares the model — confirm by grep.

### Test surface (the rectifier guarantee)

- [ ] **XSS payload injection test.** Add a test sending `display_name` =
      `<img src=x onerror=alert(1)>` through the new HX-Request fragment
      branch and assert the rendered HTML contains `&lt;img` not `<img`.
      File the test under `tests/test_notebook_api.py` or a new
      `tests/test_ui_m4_fragment_xss.py`.
- [ ] **Content-negotiation test.** Add a test sending the SAME request
      with and without `HX-Request: true` and assert the JSON branch
      returns `application/json` + the existing JSON body, while the
      fragment branch returns `text/html` + a `<tr>` fragment.
- [ ] **Slug-validation gate test.** Add a test sending a path-traversal
      slug (`../../../etc/passwd`) and assert 422 BEFORE the renderer is
      reached (don't leak the slug into the fragment output).

---

## What e4 must NOT do (audit-blocking changes)

If any of the following land in m4, the adversary critic should fire a HIGH (or
CRITICAL) and the milestone should NOT ship:

- **Move the inline JSON-shim out of `base.html` and into a separate
  vendored file.** Issue #9 open Q4 explicitly asks whether this is worth
  doing, but m4 is NOT the right milestone for it — that's a posture
  change that affects the whole UI surface and requires the full audit's
  reasoning chain. Defer.
- **Introduce `| safe` or `Markup(...)` anywhere.** Hard line.
- **Add a new mutation route under `/ui/api/`** beyond the
  HX-Request branch in `add-paper`. The UPL-12 v0 scope is exactly ONE
  new HX-Request branch; if m4 grows to cover create-notebook OR
  remove-notebook (the v1 follow-ons), each new branch needs its own
  pre-flight check pass — but the m4 brief should NOT expand that scope.
- **Widen `CONTENT_SECURITY_POLICY_UI`**. Adding `connect-src` for a
  third party, adding `'unsafe-eval'`, removing `frame-ancestors 'none'`
  — all blocking.
- **Bypass `SecFetchSiteMiddleware` for the new fragment branch.** The
  carve-out is `("/ui",)`; new routes under `/ui/api/` inherit it.
  Don't add per-route exemptions.

---

## Why NOT (b) — "descope UPL-12 to documentation-only"

The roadmap's option (b) — "plan to convert when the audit lands" — would defer
UPL-12 indefinitely. The full issue #9 audit has no scheduled landing. The
visible UX defect UPL-12 fixes (full-page white flash on every successful
create / add / remove in the operator console) ships every operator session
until UPL-12 lands. The pattern-precedent argument above is sufficient to land
the narrow v0 (add-paper only) without blocking on the full audit.

Option (b) is the right call IF the m4 pre-flight checklist reveals novel
attack surface the existing precedent doesn't cover — but the analysis above
shows it doesn't. The HX-Request content-negotiation branch is a well-trodden
htmx pattern and the existing `_paper_row_html` is a direct precedent.

---

## Why NOT pure (a) — "wait for the full audit to land"

The roadmap's option (a) — "define audit-pass criteria + open a tracking issue" —
already exists. **Issue #9 IS the tracking issue.** Defining "audit-pass criteria"
in the abstract isn't the right artifact; defining e4-narrow audit-pass criteria
(this spike's checklist above) IS.

If the full audit landed first, m4 would still need its own narrow checklist —
the full audit's findings on (e.g.) CSP scope wouldn't change what m4 does. The
two efforts are orthogonal: full audit = posture review across the whole UI;
m4 pre-flight = the marginal-surface check for ONE new content-negotiation
branch.

---

## Recommendation for shaping m4

When `/roadmap ui-attractive-polish` next slices e4 into m4:

1. **m4 v0 scope:** UPL-12 v0 (add-paper in-place swap only) + UPL-13 (View
   Transitions config flag, per Spike-1) + UPL-22 (status-badge flash). Total
   M effort (Spike-1 dropped UPL-13 from S to XS; UPL-12 narrowed to one
   flow; UPL-22 is XS).
2. **m4 v0 brief MUST include** the pre-flight checklist above, verbatim, as
   acceptance criteria the milestone-pipeline adversary critic verifies.
3. **m4 v1 follow-on** (separate milestone, not bundled into m4): convert
   create-notebook + remove-notebook flows. Each gets its own pre-flight check
   pass (same checklist, applied to the additional surface).
4. **Issue #9 stays open** as a separate audit-coordination effort tracked
   independently of e4. The Phase-4 external-writes list does NOT need to
   reference issue #9; it's a posture audit, not a m4 dependency.

**Spike-2 verdict: e4 is unblocked.** UPL-12 v0 ships in m4 with the pre-flight
checklist as its security-correctness contract.

---

## Risks the spike did NOT cover

These are explicitly OUT of Spike-2's mandate (the issue #9 full audit owns
them):

- **CSRF posture vs malicious local processes / DNS rebinding.** Issue #9 Q1.
  Not e4-specific.
- **Upload polyglot completeness.** Issue #9 Q2. UPL-12 doesn't touch uploads.
- **Path-traversal completeness on the preview route.** Issue #9 Q3. UPL-12
  doesn't touch the preview.
- **CSP `unsafe-inline` reduction.** Issue #9 Q4. UPL-12 + UPL-13 + UPL-22
  all live within the existing allowance.
- **Render-path divergence across the full operator-controlled-field
  surface.** Issue #9 Q5. UPL-12's marginal contribution is bounded by the
  pre-flight checklist; the broader question (e.g. could a future renderer
  bypass autoescape via a `Markup(...)` construction in a yet-unwritten
  handler) remains the full audit's domain.

These belong in the audit's own scope — not m4's, not e4's.

---

*Spike-2 complete. e4 is unblocked with a narrow pre-flight contract; issue #9 stays open as a separate effort.*
