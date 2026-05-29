# Critique — notebook-surface-expansion-m2

**Critic:** adversary
**Generated:** 2026-05-29T00:00:00Z
**Commit range:** 096be650bbe1cc673fa62a94f6e263551156c945..d073c0a2c63a863d1a951cae0f2d11e1f56392b3
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the security-critical surface (the primary lens) is clean — `validate_slug` fires first, mass-assignment is closed via a dedicated `NotebookRename` model, `max_length=256` rejects over-long names at the Pydantic boundary, control chars are stripped, and the fragment is `html.escape`'d. The findings are all latent/cosmetic, not security defects.
- Finding counts: 0 CRITICAL, 0 HIGH, 1 MEDIUM, 2 LOW.
- Highest-risk location: `server/routes/notebooks.py:404` (the `_display_name_fragment` f-string) vs `frontend/templates/notebook_detail.html:14` (the Jinja `<p>`) — two hand-maintained renderers of the same swap target with no test pinning their structural equivalence.
- Cross-axis pattern: this is the recurring "two renderers of one element" foot-gun the codebase already accepts for `_paper_row_html`/`_ingest_status_fragment`; m2 extends it without adding the equivalence guard.
- Axes 1 (cache byte-stability), 2 (math), 4 (MCP spec), 5 (local-first), 6 (tier), 7 (no-fork) are all axis-verified clean — `git diff --name-only` touches only `server/notebooks_store.py`, `server/routes/notebooks.py`, `frontend/templates/notebook_detail.html`, `tests/test_notebook_rename_delete.py` plus milestone notes; no `server/tools.py`, `server/prompts.py`, `EXPECTED_*_SHA256`, or `/mcp` bytes.
- `ruff check` clean on all changed files; the new `tests/test_notebook_rename_delete.py` (13 tests) passes; the "green at exit" claim is verified.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Fragment/template structural equivalence is not pinned by a test

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/routes/notebooks.py:404
- **What:** The swap target is rendered by TWO independent code paths: the f-string `_display_name_fragment` returns `<p class="display-name" id="display-name-block">{shown}</p>` (notebooks.py:404), while the initial page render uses the Jinja `<p class="display-name" id="display-name-block">{{ notebook.display_name or "—" }}</p>` (notebook_detail.html:14). The tests assert only `id="display-name-block"` and the name substring on each path — they never assert the two emit identical `<p>` structure (matching `class`, tag, and the `—` em-dash token).
- **Why it matters:** A future edit to one renderer (e.g. adding/removing the `display-name` class, changing the tag, or changing the empty-name placeholder on only one side) silently desynchronizes the post-swap DOM from the initial render. The htmx `outerHTML` swap keys on the `#display-name-block` ID so the swap will not visibly break, which is exactly what makes the drift invisible — styling/structure diverges with no failing test. This is the load-bearing reason the verdict is SHIP-WITH-FIXES rather than SHIP.
- **Proposed fix:** Add one test that renders the empty-name and a known-name case through BOTH paths and asserts the produced `<p ...>` strings are byte-identical. Cheapest form: in `tests/test_notebook_rename_delete.py`, parse the `<p id="display-name-block" ...>` element out of `GET /ui/notebooks/<slug>` and out of the `PATCH` fragment for the same stored `display_name` and assert equality (tag + class + id + inner text). Alternatively have the Jinja template call `_display_name_fragment` (one renderer) — larger blast radius, not required.
- **Regression guard:** `tests/test_notebook_rename_delete.py::TestRename::test_fragment_matches_template_render` — assert the `<p>` for `display_name=""` and `display_name="Foo"` is identical across the GET-page and the PATCH-fragment renderers.

### F2 — Rename-form input `value` goes stale after an in-page rename

- **Severity:** LOW
- **Source:** adversary
- **File:** frontend/templates/notebook_detail.html:30
- **What:** The rename `<input ... value="{{ notebook.display_name }}">` sits OUTSIDE `#display-name-block` (intentional, so the form survives the swap), but the `outerHTML` swap only replaces the `<p>`. After a successful rename the input still shows the OLD name until a full page reload.
- **Why it matters:** Operator-visible staleness: a second rename starts from the stale prefilled value, so an operator editing twice in a row may unintentionally revert. No security or data-integrity impact (the stored value is correct; only the prefilled form field lags).
- **Proposed fix:** Add `hx-on::htmx:after-request="if(event.detail.successful) this.querySelector('input[name=display_name]').value = ...''"` to clear/refresh the input, or have the returned fragment also include an OOB swap (`hx-swap-oob`) updating the input value. Lowest-effort: clear the input on success.
- **Regression guard:** Out of scope for a unit test (DOM/htmx runtime behavior); note in the template comment that the input is intentionally not refreshed, or add the OOB swap and assert its presence in the fragment.

### F3 — `_CONTROL_CHARS_RE` doc-comment overstates what html.escape does to C1

- **Severity:** LOW
- **Source:** adversary
- **File:** server/routes/notebooks.py:388
- **What:** The comment says the C1 range `0x80-0x9f` "is left to Jinja2/`html.escape`". Neither Jinja2 autoescape nor `html.escape` transforms C1 control bytes — they pass through verbatim as valid Unicode codepoints (escaping only touches `& < > " '`). The comment implies a sanitization that does not occur.
- **Why it matters:** Documentation-vs-behavior drift on a security-adjacent comment. No functional defect: C1 codepoints are valid Unicode and are not HTML-control-significant, and the prior milestone surfaces already permit them in `display_name`; this is purely a misleading comment, not a missing guard. (Same low-grade "comment says X, code does Y" shape this critic has flagged before, but here the code is correct and only the prose is wrong.)
- **Proposed fix:** Reword the comment to "C1 range 0x80-0x9f is intentionally NOT stripped (valid Unicode, not HTML-control-significant)" — drop the implication that html.escape handles them.
- **Regression guard:** None required (comment-only); covered implicitly by the existing `test_rename_strips_control_chars` which asserts only C0/DEL stripping.

## What was done well

- Security boundary order is exactly right: `validate_slug` fires FIRST (notebooks.py:435-440, identical to `delete_notebook`), so a malformed/traversal slug 422s before any store access — confirmed by `test_rename_malformed_slug_422`.
- Mass-assignment is genuinely closed: `NotebookRename` carries ONLY `display_name` (notebooks.py:225), the store method takes `(slug, display_name)` only, and `test_rename_ignores_mass_assignment` proves `slug`/`notebook_kind`/`parse_status` in the body are ignored and no `evil-nb` is conjured.
- Control-char strip ordering is sound: Pydantic `max_length=256` validates the RAW body first, then the strip only shrinks the string — length can only go down, no bypass. The regex `[\x00-\x1f\x7f]` is correct (C0 + DEL) and does not over-strip legitimate Unicode.
- XSS is closed on BOTH render paths: `html.escape` in the f-string fragment and Jinja autoescape (explicit `Environment(autoescape=select_autoescape(..., default_for_string=True))` in ui.py:85-91) on the page; `test_rename_escapes_html_xss` asserts no raw `<script>` on the fragment AND the GET page. No `| safe` introduced anywhere.
- The new `value="{{ notebook.display_name }}"` attribute interpolation is safe: HTML autoescape escapes `"` → `&#34;`, so a `display_name` containing a double-quote cannot break out of the attribute.
- CSRF posture is preserved without new gaps: the new PATCH route lives under `/ui/api`, covered by the existing `exempt_prefixes=("/ui",)` SecFetchSite carve-out (main.py:581) plus OriginValidation (all-methods, loopback-only) and HostValidation — a browser cross-site PATCH gets `Sec-Fetch-Site: cross-site` → 403.
- The store method correctly mirrors the established `delete_notebook`/`update_parse_status` concurrency pattern (`async with self._lock` → `asyncio.to_thread`) and correctly avoids a schema migration (`display_name` exists at SCHEMA_VERSION 4).
- The base.html JSON-shim already serializes PATCH bodies (base.html:21 handles `verb === 'patch'`), and the DELETE button correctly uses a body-less `hx-delete` — the verb wiring is consistent with the existing shim, no new client-side parsing introduced.
- Test surface is broad and matches the ACs: happy-path + persistence, empty→em-dash, 422 malformed slug, 422 over-long (257), 256 boundary accepted, 404 nonexistent, control-char strip, XSS escape, mass-assignment, delete round-trip + sibling survival, delete 422/404, and detail-page wiring — `ruff` clean and 13/13 green at exit, verified live.
- Effort honesty is good: every new symbol (`NotebookRename`, `_display_name_fragment`, `_CONTROL_CHARS_RE`, `update_display_name`, `rename_notebook`) is wired and exercised; no unused imports introduced (`re`, `html`, `status`, `Field` all pre-existed and are used).

## Recommended rectification order

1. F1 — add the fragment/template structural-equivalence test (highest leverage; prevents the invisible-desync class on a surface that now has two renderers). ≤ 20 LOC, isolated to the new test file.
2. F3 — reword the C1 doc-comment (one-line, zero blast radius). Bundle with F1's commit.
3. F2 — refresh/clear the rename-form input after a successful swap (optional UX polish; defer if Phase 4 is fix-only-if-cheap and the OOB-swap approach is judged too large).

## Rectification status (filled by Phase 4)

Adversary SHIP-WITH-FIXES (0C/0H/1M/2L). F1 fixed; F3 fixed (one-line, bundled);
F2 deferred with a clarifying template comment. m2 detail test count 13 → 17.
ruff clean.

- **F1 (MEDIUM) — FIXED.** Added `TestRendererEquivalence::test_fragment_matches_template_render`
  (parametrized over `""`, a plain name, an angle-bracket/ampersand name, and a
  quote name). For each, it PATCHes the name, GETs the detail page, extracts the
  `#display-name-block` `<p>` from BOTH renders, and asserts the opening tags are
  BYTE-identical (tag + class + id + attribute order) and the inner content is
  semantically identical (compared after `html.unescape`, so Jinja's `&#34;`/
  `&#39;` and `html.escape`'s `&quot;`/`&#x27;` quote-codepoint difference is
  collapsed — both decode to the same char). This pins the two renderers against
  the silent-desync class. ~25 LOC, isolated to the new test file.
- **F3 (LOW) — FIXED (bundled).** Reworded the `_CONTROL_CHARS_RE` doc-comment:
  it no longer says C1 is "left to Jinja2/`html.escape`" (neither transforms C1).
  Now states C1 is intentionally NOT stripped (valid Unicode, not
  HTML-control-significant) and that escaping only touches `& < > " '`. Also
  corrected the lead-in from "ASCII/C1 control characters" to "C0 control chars +
  DEL" (the regex `[\x00-\x1f\x7f]` never matched C1). Comment-only.
- **F2 (LOW) — DEFERRED with a clarifying comment.** The stale-`value`-attribute
  concern is cosmetic and largely theoretical: after an in-page rename the LIVE
  input DOM value already holds what the operator typed (= the new stored name),
  so a follow-up rename starts from the correct current value; only a hard reload
  would rewrite the stale `value` ATTRIBUTE. No data-integrity impact (the stored
  value is authoritative). An OOB-swap/clear fix adds template+test surface with
  worse UX trade-offs (clearing loses the value). Documented the intentional
  non-refresh in a `notebook_detail.html` comment (the adversary offered this as
  an acceptable resolution). No behavioral change.
