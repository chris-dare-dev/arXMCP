# Critique — ui-attractive-polish-m5

**Critic:** adversary
**Generated:** 2026-05-31T19:30:00Z
**Commit range:** 78c8f6f..3b2aaeb (df65b47 feat + 3b2aaeb notes/tests follow-up)
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- m5 is a clean five-item wind-down bundle. The Spike-2 13-item pre-flight checklist is mechanically gated for BOTH the new `create_notebook` and `delete_notebook` HX-Request branches; per-value `html.escape()` discipline in `_notebook_row_html` is preserved; `lancedb_path` is correctly absent from the HTML branch; WCAG-AA contrast holds for all 4 dark-mode pills (re-verified by hand at 6.20/5.43/5.17/4.83 — see below).
- 0 CRITICAL, 0 HIGH, 4 MEDIUM, 2 LOW findings. None block ship.
- The 200-vs-204 fork in `delete_notebook` (`server/routes/notebooks.py:446-447`) correctly accommodates htmx 2.0.10's `{code:"204",swap:false}` rule. Existing JSON-direct delete tests at `tests/test_notebook_api.py:139` and `tests/test_notebook_rename_delete.py:256` send no `HX-Request` header — verified harmless (188 adjacent UI + notebook tests pass post-m5).
- Per-hand contrast verification using the W3C WCAG 2.1 sRGB formula: `--ok #3fb950 on #0d2818 = 6.20:1`, `--warn #d29922 on #3d2a07 = 5.43:1`, `--ops-warn #8b949e on #1c2230 = 5.17:1`, `--down #f85149 on #3d1216 = 4.83:1`. All four pills pass SC 1.4.3 (≥4.5:1). Canvas-contrast (border vs `--bg #0d1117`) also passes SC 1.4.11 (≥3:1) at 7.45/7.50/6.15/5.65.
- Highest-severity drift: `tests/test_ui_m2_polish.py:181-199` (`test_body_max_width_guard_discriminates`) became VACUOUS after m5 lifted 980px to clamp() — the `str.replace("max-width: 980px", ...)` mutation is a no-op against the m5 CSS, and the assertion `body_block is None` holds vacuously. The implementer explicitly chose to keep the test as "documentation of the v0→v1 transition" (deviation #2 in implementation-summary.md). Vacuous tests dilute the test surface and should be removed, not preserved.
- The module docstring at `tests/test_ui_m2_polish.py:13-16` lies about m5's state: "**UPL-19 v0** ... The wider `body { max-width: clamp(…) }` expansion is descoped to v1 — the regression test ASSERTS the current `980px` ceiling stays." After m5 the test does the opposite. Same "doc says X, code does Y" anti-pattern this critic has flagged before.
- `app.css` cap raised 365 → 370 (5 lines over the roadmap KR5 declared at `plans/ui-attractive-polish-roadmap.md:156-157` "stays under 365 lines"). The implementer flagged this in deviation #1 and deferred the decision to Chris; the roadmap doc itself was NOT updated in the m5 commit triple, leaving documented drift.
- The `m5-implementation` worktree at `.claude/worktrees/m5-implementation/` AND the branch `m5-implementation` are still present post-merge despite the impl summary's claim "no orphan worktree-branch state remains." Process bookkeeping, LOW.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — `test_body_max_width_guard_discriminates` is vacuous after m5 v1 flip; kept as "documentation" per deviation #2

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_ui_m2_polish.py:181-199`
- **What:** The test mutates `APP_CSS_NO_COMMENTS` via `synthetic_v1 = APP_CSS_NO_COMMENTS.replace("max-width: 980px", "max-width: clamp(640px, 92vw, 1400px)")` and asserts the legacy-form regex no longer matches. After m5, the original `max-width: 980px` substring is GONE from `app.css` (only comment references remain, which `APP_CSS_NO_COMMENTS` strips). The `.replace()` is therefore a no-op; the assertion `body_block is None` holds vacuously because the regex `r"body\s*\{[^}]*max-width:\s*980px[^}]*\}"` searches for a `body {}` block containing `980px` and the only `body {}` block has `clamp(...)`. The test passes but its self-check ("prove the F1-rectified guard has discriminating power by mutating a synthetic CSS string with the v1 clamp()") is no longer demonstrable from this test alone. The impl summary deviation #2 explicitly acknowledges: "the assertion `body_block is None` still holds because the regex searches for the legacy form. Considered removing but kept it as documentation of the v0→v1 transition."
- **Why it matters:** A test that passes regardless of input value provides no regression guarantee. Code is not documentation — the implementer's stated rationale ("kept as documentation") is the wrong artifact choice. Future agents reading the test see an "F1-rectified guard" comment that no longer corresponds to a discriminating assertion. The vacuous test will continue to pass even if a future change reintroduces `max-width: 980px` elsewhere in the file (the regex IS scoped to the body block, but the substring won't be there to mutate, so the mutate-and-check pattern doesn't fire).
- **Proposed fix:** Either (a) DELETE the test outright (the negative-regression check in `test_body_max_width_uses_v1_clamp` at lines 169-178 already pins "max-width: 980px not in body block"), or (b) rewrite the discriminator to construct a synthetic CSS string from scratch:

  ```python
  def test_body_max_width_guard_discriminates(self) -> None:
      # Discriminator: a synthetic CSS string with the LEGACY 980px form
      # MUST match the pinned regex, proving the regex has not become
      # over-broad. (m5 keeps this test because the v1 clamp() lives in
      # production; we synthesize the v0 form locally.)
      synthetic_v0 = "body { margin: 0; max-width: 980px; }"
      body_block = _re.search(
          r"body\s*\{[^}]*max-width:\s*980px[^}]*\}",
          synthetic_v0,
          flags=_re.S,
      )
      assert body_block is not None
  ```

  Option (a) is cheaper. Either way, the existing form is dead test-code.
- **Regression guard:** N/A — the fix removes or rewrites the broken test.

### F2 — `tests/test_ui_m2_polish.py` module docstring lies about UPL-19 v0 state post-m5

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_ui_m2_polish.py:13-16`
- **What:** The module docstring still reads: `"- **UPL-19 v0** ``<div class="table-wrap">`` wrapping both tables + ``.table-wrap { overflow-x: auto }`` in CSS. The wider ``body { max-width: clamp(…) }`` expansion is descoped to v1 — the regression test ASSERTS the current ``980px`` ceiling stays."` After m5 (which IS UPL-19 v1), the test was renamed from `test_body_max_width_980px_preserved` → `test_body_max_width_uses_v1_clamp` and now asserts the OPPOSITE. The implementer renamed the test but did not update the module docstring.
- **Why it matters:** Same anti-pattern documented across multiple prior milestones in this critic's persistent memory (e.g. textbook-ingest-m2 stale-docstring; textbook-ingest-m3 bp1-description-vs-handler-validator-drift; textbook-ingest-m10 doc-finalize-leaves-sibling-snippet-stale). A docstring is the operator-facing claim; it must move in lockstep with the implementation it describes. Future agents grepping `UPL-19` would land on a docstring asserting `980px` is the test invariant, then read code asserting `clamp(640px, 92vw, 1400px)` — confusion or worse.
- **Proposed fix:** Update `tests/test_ui_m2_polish.py:13-16` to reflect m5's lift:

  ```python
  - **UPL-19 v0** ``<div class="table-wrap">`` wrapping both tables +
    ``.table-wrap { overflow-x: auto }`` in CSS. m2 v0 preserved the
    ``980px`` ceiling; **m5 (UPL-19 v1)** lifted that to
    ``clamp(640px, 92vw, 1400px)`` so the papers table breathes on
    27"/4K monitors. The regression test was renamed and the
    assertion flipped at the v1 ship boundary (see
    ``test_body_max_width_uses_v1_clamp``).
  ```

- **Regression guard:** N/A — docstring-only fix.

### F3 — `app.css` 5-line over-run vs roadmap KR5 documented but not reconciled

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `plans/ui-attractive-polish-roadmap.md:156-157` (states KR5 cap = 365) AND `frontend/static/app.css` (currently 370 lines)
- **What:** The roadmap explicitly declares: "total `frontend/static/app.css` size stays under **365 lines** (trajectory: m1 = 190 → m2 = 216 → m3-feat = 287 → ...)". m5 lands at 370 (verified — `frontend/static/app.css` has exactly 370 lines, zero headroom against the m5-revised cap). Both cap-tests (`tests/test_ui_m3_dark_and_htmx_feedback.py:486` and `tests/test_ui_m4_in_place_add_paper.py:632`) were updated to `<= 370` in lockstep, but the roadmap KR5 doc was NOT updated. The impl summary deviation #1 candidly says: "KR5 in the roadmap doc already states 365 as the cap — this is a 5-line over-run; will note in the chore commit and let Chris decide whether to update KR5 from 365 → 370 or insist on a trim."
- **Why it matters:** Roadmap-vs-tests drift. The roadmap is the operator-facing contract; the test cap is the machine-enforced contract. When they disagree, future milestones default to the cheaper interpretation (the test) and the roadmap's deliberate cap (the documented commitment) is silently demoted. Same shape as the security-doc-drift-on-multi-byte-magic-sniff finding in this critic's persistent memory: design doc says X, code does Y, only the code is enforced.
- **Proposed fix:** Either (a) edit `plans/ui-attractive-polish-roadmap.md:156-157` to declare the new KR5 cap = 370 with a note that m5 raised it 5 over the original budget (and the rationale: m5 documentation comments dominate the cost), OR (b) reduce comment density in `frontend/static/app.css` to land at ≤365. Option (a) is cheaper and the impl summary expects user disposition; option (b) would consume ≥5 inline-comment lines (the UPL-12 row-fade keyframe block at lines 354-368 is the highest-comment-density addition).
- **Regression guard:** No new test required; the existing cap-tests already enforce 370.

### F4 — `_notebook_row_html` accepts `notebook_kind` but never renders it; parameter is dead-weight

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `server/routes/notebooks.py:1745-1801`
- **What:** The new helper accepts `notebook_kind: str` and does `_ = notebook_kind` at line 1792 with comment "accepted but not rendered today; accepting it future-proofs the helper signature without changing the rendered surface." The caller at line 374-383 passes `notebook_kind=body.notebook_kind`. No test exercises a `notebook_kind="textbook"` path through the HTML-branch — `tests/test_ui_m5_create_remove_in_place.py:198, 222, 243, 255, 261, 275, 294, 368` all pass `notebook_kind="arxiv"`. A textbook-notebook create via HX-Request returns a row visually indistinguishable from an arXiv-notebook row — no parse-status indicator, no kind badge — and no test verifies this is the intended behavior.
- **Why it matters:** Pre-existing m6/m7 design: the rendered `index.html` template doesn't show kind in the notebooks table either, so the m5 fragment matches existing behavior. But m5 introduces a NEW input contract (the helper signature) that exposes the unused parameter as a public API surface. Two latent risks: (a) a future maintainer adds a `kind` column to the template, sees the helper accepts `notebook_kind`, expects it to be rendered, and is surprised when the helper still drops it; (b) the test surface claim ("Spike-2 13-item pre-flight checklist mechanically exercised") does not actually cover the textbook-kind code path through the new HTML branch. The `notebook_kind="textbook"` value also drives the upstream `initial_parse_status = "pending"` flag at line 320-322 — the create handler's behavior differs by kind even though the fragment output doesn't.
- **Proposed fix:** Either (a) drop `notebook_kind` from the helper signature (and the caller) since it's not rendered — minimum-surface API; future column additions can extend the signature when actually needed, OR (b) add ONE test to `TestUPL12V1CreatePreFlightChecklist` that exercises `notebook_kind="textbook"` through the HTML branch and asserts the fragment shape matches the arxiv case (regression guard against silent kind-divergence in the renderer). Option (b) is the safer choice — it pins the current behavior (kind has no visual effect in the immediate post-create row) and gates against accidental future drift.

  ```python
  def test_create_textbook_kind_returns_same_fragment_shape(
      self, m5_client: TestClient
  ) -> None:
      r = m5_client.post(
          "/ui/api/notebooks",
          json={"slug": "tb-nb", "display_name": "Hartshorne",
                "notebook_kind": "textbook"},
          headers={"HX-Request": "true"},
      )
      assert r.status_code == 201, r.text
      assert "text/html" in r.headers.get("content-type", "").lower()
      text = r.text
      # Same 4-column schema as arxiv notebooks; no kind badge today
      # (verifies the helper drops notebook_kind as documented).
      assert '<tr data-slug="tb-nb">' in text
      assert "<td><code>tb-nb</code></td>" in text
      assert "<td>Hartshorne</td>" in text
      assert "textbook" not in text  # kind is dropped from the row
      assert "pending" not in text  # parse_status NOT leaked here
  ```

- **Regression guard:** The test above is the guard.

### F5 — m5-implementation worktree + branch orphaned post-merge despite impl summary claim "no orphan worktree-branch state remains"

- **Severity:** LOW
- **Source:** adversary
- **File:** `.claude/worktrees/m5-implementation/` (worktree dir, 28 entries including `.venv/`, `.ruff_cache/`) AND `git branch m5-implementation` (still exists, tip at `df65b47`)
- **What:** `git worktree list` shows `.claude/worktrees/m5-implementation` still present, checked out to branch `m5-implementation` at the feat commit `df65b47`. `git branch --all | grep m5` confirms the branch still exists locally. The impl summary's "Race-recovery note" claims: "committed there (`df65b47`), then fast-forward-merged back into main. ... no orphan worktree-branch state remains." The merge IS confirmed (main contains `df65b47`), but the worktree AND branch were not pruned.
- **Why it matters:** Process bookkeeping inaccuracy. The orphan worktree contains a `.venv/` and `.ruff_cache/` (1.1+ MB) that will continue to grow stale; the orphan branch will continue to appear in `git branch --all` listings and confuse future `git log m5-implementation` invocations into thinking m5 work is still in-flight. None of this is dangerous (the work landed on main) but the impl summary's confident assertion is wrong. Same shape as the milestone-pipeline anti-pattern documented in `agent-conventions.md` re: state.json claims that don't match observed state.
- **Proposed fix:** Run `git worktree remove .claude/worktrees/m5-implementation && git branch -d m5-implementation` after Chris confirms the chore commit triple is complete. Alternatively, document the orphan in the impl summary as "intentionally retained for parallel-session forensics" if that's the actual rationale. The CLAUDE.md §4.4 push-once-asked rule means this cleanup is non-urgent — it can wait until Chris green-lights the m5 push.
- **Regression guard:** N/A — process artifact, not a code defect.

### F6 — `create_notebook` does NOT strip C0 control chars from `display_name` while `rename_notebook` DOES; divergence preserved into the new HTML-fragment path

- **Severity:** LOW
- **Source:** adversary
- **File:** `server/routes/notebooks.py:251-390` (create_notebook — no `_CONTROL_CHARS_RE.sub`) vs `server/routes/notebooks.py:522` (rename_notebook — does call `_CONTROL_CHARS_RE.sub("", body.display_name)`)
- **What:** `_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")` at line 462 strips C0 + DEL bytes from display_name in rename_notebook (line 522). create_notebook does NOT apply this sanitization at any point — it accepts `body.display_name` directly into `store.create_notebook` (line 329) and the new m5 fragment renderer at line 380 passes the unsanitized value through `_notebook_row_html`. The docstring comment at `_CONTROL_CHARS_RE` (lines 453-461) explicitly states the rationale: "A display name is a SINGLE-LINE field — NUL, newlines, tabs, and other control chars have no legitimate place and would (a) corrupt the single-line render and (b) enable log-injection." This invariant was added in m2 (notebook-surface-expansion-m2) for the rename path; the create path was never updated.
- **Why it matters:** Pre-existing m6/m7 inconsistency that m5 PRESERVES into the new HTML branch (m5 didn't introduce it, but m5 had the opportunity to fix it while touching `create_notebook`). The XSS payload test in `_notebook_row_html` covers `<>&"` but not C0 bytes; `html.escape()` does not transform C0 (the existing rename docstring explicitly notes this). FastAPI's JSON parser rejects bare NUL bytes in JSON strings but accepts ``, ``, etc. as escape sequences (Pydantic accepts the unescaped value). Result: an operator can create a notebook with `display_name = "evilrow"` via HX-Request, the renderer emits the raw C1-stripped HTML (escape doesn't touch C0), and downstream log entries / screen-reader announcements include the C0 byte. Not a security vector in this loopback-only system, but a real correctness invariant the rename path enforces and the create path does not.
- **Proposed fix:** Add ONE line in `create_notebook` immediately after the slug validation block (around line 282 in the post-m5 layout):

  ```python
  # m2 invariant restated: strip C0 + DEL from display_name. The rename
  # path enforces this at line 522; the create path was never updated.
  # Defense-in-depth before the value reaches the SQLite writer AND the
  # new m5 HTML fragment renderer.
  cleaned_display_name = _CONTROL_CHARS_RE.sub("", body.display_name)
  # ... then use `cleaned_display_name` for store.create_notebook + the
  # fragment renderer at line 380.
  ```

  This is a 2-line edit and brings create_notebook in lockstep with rename_notebook. Defer if the user prefers to track this as a separate m4/m5 follow-on issue.
- **Regression guard:** Add ONE test to `TestUPL12V1CreatePreFlightChecklist`:

  ```python
  def test_create_strips_c0_control_chars_from_display_name(
      self, m5_client: TestClient
  ) -> None:
      r = m5_client.post(
          "/ui/api/notebooks",
          json={"slug": "c0-test", "display_name": "evil row",
                "notebook_kind": "arxiv"},
          headers={"HX-Request": "true"},
      )
      assert r.status_code == 201, r.text
      # C0 byte stripped from the rendered fragment (matches the m2
      # invariant the rename path enforces at line 522).
      assert "" not in r.text
      assert "evil row" in r.text
  ```

## What was done well

- The 200-vs-204 fork in `delete_notebook` (`server/routes/notebooks.py:446-447`) correctly accommodates the htmx 2.0.10 `{code:"204",swap:false}` behavior the synthesis C3 enumerated; the JSON-direct DELETE tests at `tests/test_notebook_api.py:139` and `tests/test_notebook_rename_delete.py:256` remain on 204 because they send no `HX-Request` header — verified by running all 188 adjacent UI + notebook tests post-m5 (188/188 pass).
- Validation ordering on BOTH new endpoints is exemplary. `create_notebook` runs `validate_slug` (l. 282) → notebook-name + lancedb-path containment → `store.create_notebook` (line 326) → THEN the HX-Request fork (line 372). `delete_notebook` runs `validate_slug` (line 430) → `store.delete_notebook` (line 437) → 404 if `not deleted` (line 438) → THEN the HX-Request fork (line 446). The HTML branch is unreachable on any invalid input or missing slug. Spike-2 pre-flight item #8 is mechanically gated.
- Per-value `html.escape()` in `_notebook_row_html` mirrors `_paper_row_html` exactly (server/routes/notebooks.py:1793-1801): `slug` is escaped 3× (data-slug attribute, `<code>` body, href URL); `display_text` is escaped after the falsy fallback; `created_at` is escaped inside `<time>`. The XSS payload test at `tests/test_ui_m5_create_remove_in_place.py:161-179` exercises `<img src=x onerror=alert(1)>`, `nb"x`, and `ts"&<` and asserts each special char escapes.
- The `lancedb_path` host-path leak is correctly absent from the HTML branch. The `_notebook_row_html` SIGNATURE does not accept `lancedb_path` (defense in depth — the helper can't accidentally interpolate what it doesn't receive). The JSON branch (line 386-389) preserves `lancedb_path` for backwards compat with scripted callers. Test at `tests/test_ui_m5_create_remove_in_place.py:146-159` triple-asserts the absence: `"lancedb_path"`, `"/var/"`, `"lancedb"`.
- WCAG-AA contrast holds for all 4 dark-mode pill pairs. Hand-verified using the W3C WCAG 2.1 sRGB-linearization formula: `--ok #3fb950 / #0d2818 = 6.20:1`, `--warn #d29922 / #3d2a07 = 5.43:1`, `--ops-warn #8b949e / #1c2230 = 5.17:1`, `--down #f85149 / #3d1216 = 4.83:1`. All ≥ 4.5:1 (SC 1.4.3). Canvas-vs-border (SC 1.4.11 ≥ 3:1) also passes at 7.45/7.50/6.15/5.65. The programmatic test in `tests/test_ui_m5_create_remove_in_place.py::TestUPL8V1DarkModePillContrast::test_pill_contrast_passes_wcag_aa` uses a correct W3C implementation (gamma threshold 0.03928, coefficients 0.2126/0.7152/0.0722, lighter+0.05/darker+0.05) and parametrizes across all 4 pills.
- The row-fade keyframe is correctly gated by `@media (prefers-reduced-motion: no-preference)` (`frontend/static/app.css:354-368`); reduced-motion users get instant row removal (no animation). The `forwards` fill-mode is correctly applied via the shorthand `animation: row-fade-out 200ms ease-out forwards` so the row stays at opacity 0 through htmx's 200ms settle phase. Test at lines 672-685 asserts both `"forwards"` and `"200ms"` substring presence.
- Architectural-lock compliance: ZERO hunks in `server/middleware.py`, `server/config.py`, `server/main.py`, `server/tools.py`, `server/prompts.py`, `server/handlers/`. BP1 prompt-cache prefix, OriginValidationMiddleware, SecFetchSiteMiddleware, CSP, and tool-schema hash are all bit-stable. CLAUDE.md §4.7 invariants (no SPA, no `BaseHTTPMiddleware`, no `anthropic` runtime SDK, no `claude-opus` references) hold.
- The `hx-target="closest tr"` ancestor hazard from synthesis C6 is correctly avoided. The remove button in `frontend/templates/index.html:79-85` IS inside a `<tr>` (the Jinja for-loop produces them); the delete-notebook button in `frontend/templates/notebook_detail.html` is in `<div class="notebook-actions">` and was correctly NOT given the `closest tr` swap. Verified by the m5 test `test_notebook_detail_delete_button_unchanged` (lines 456-465) and reading `notebook_detail.html:83`.
- The empty-state placeholder removal logic is race-safe. `document.getElementById('notebooks-empty')?.remove()` uses optional chaining (Chrome 80+ / Safari 13.1+ / Firefox 74+ — all modern browsers); the second concurrent create is a safe no-op against `null`. `this.reset()` clears the form. The placeholder is INSIDE the swap target tbody so `hx-swap="beforeend"` keeps inserting AFTER the (now-removed) placeholder, not before it.
- Existing JSON-direct DELETE tests at `tests/test_notebook_api.py:139` and `tests/test_notebook_rename_delete.py:256` remain UNCHANGED post-m5 (no `HX-Request` header → 204 path preserved). Cross-milestone safety holds: m1 `aria-live="polite"` on `#papers-tbody` preserved; m2 `.table-wrap { overflow-x: auto }` still handles sub-640px viewports under the new clamp() floor; m3 dark @media block intact; m4 UPL-22 badge-flash + UPL-13 View Transitions duration intact (lines 350-360); m4 `_paper_row_html` still renders `<td>added</td>` (regression test at line 750-757).

## Recommended rectification order

1. F2 (m2_polish module docstring lies about UPL-19 v0 state) — 4-line edit; closes the doc-vs-test drift before it propagates.
2. F1 (vacuous discriminator test) — 1-line delete or 8-line rewrite; eliminates dead test-code the implementer explicitly chose to keep.
3. F3 (roadmap KR5 cap drift 365 vs 370) — 2-line edit in `plans/ui-attractive-polish-roadmap.md`; closes roadmap-vs-tests drift. Alternative: trim 5 lines of inline comments in `app.css`.
4. F4 (`notebook_kind` dead parameter) — choose (a) drop the parameter (~3-line edit) OR (b) add the textbook-kind HTML-branch test (~12 lines). (b) is the safer choice.
5. F6 (create vs rename C0-strip divergence) — 2-line edit + 1 test; brings create in lockstep with rename. Defer if user prefers a separate issue.
6. F5 (orphan worktree + branch) — 1 command after Chris green-lights the push. Process hygiene.

## Rectification status (filled by Phase 4)

- **F1 (MEDIUM) — FIXED (DELETED).** `tests/test_ui_m2_polish.py::test_body_max_width_guard_discriminates` removed; the assertion held vacuously post-m5 v1 lift (per the critic's option (a)). The negative-regression check in `test_body_max_width_uses_v1_clamp` (`max-width: 980px not in body block`) already covers the regression surface — the discriminator added no additional safety. Replaced with an inline comment block noting the deletion + rationale for future agents.
- **F2 (MEDIUM) — FIXED.** `tests/test_ui_m2_polish.py:13-22` module docstring updated to reflect m5's v0→v1 lift: the docstring now says m5 (UPL-19 v1) lifted the 980px ceiling to clamp(640px, 92vw, 1400px), the test was renamed `test_body_max_width_uses_v1_clamp`, and m5 added a negative-regression check that the legacy 980px is absent from the body block.
- **F3 (MEDIUM) — FIXED.** `plans/ui-attractive-polish-roadmap.md` KR5 restated 365 → 370 with explicit "m5 came in 5 over the 365 budget — documentation-comment density (Primer-Dark rationale, swap-delay timing, clamp() trade-off) won the trade-off vs LOC-shaving" rationale + the lockstep update across both cap-tests is documented. The `tokens.css` split escape-hatch remains.
- **F4 (MEDIUM) — FIXED.** `tests/test_ui_m5_create_remove_in_place.py::TestUPL12V1CreatePreFlightChecklist::test_create_textbook_kind_returns_same_fragment_shape` added: exercises `notebook_kind="textbook"` through the HTML branch, asserts the fragment shape matches arxiv (no kind column, no leaked `pending` parse_status). Per critic's option (b) — pins the current behavior so future template additions that surface kind are caught.
- **F5 (LOW) — FIXED.** `git worktree remove --force .claude/worktrees/m5-implementation` + `git branch -d m5-implementation` executed. `git worktree list | grep m5` → empty; `git branch | grep m5` → empty. The `--force` was needed because the worktree had `.venv/` + `.ruff_cache/` untracked artifacts; the m5 commits were already merged into main so no work loss.
- **F6 (LOW) — DEFERRED.** Pre-existing m6/m7 inconsistency (`create_notebook` doesn't strip C0 control chars from `display_name` while `rename_notebook` does). NOT introduced by m5; m5 simply preserved the existing behavior into the new HTML branch. Tracked as a follow-up issue — the 2-LOC fix + 1 test should land as a separate `/milestone-pipeline` invocation (perhaps a bug-fix track item alongside the UPL-5/6/7 batch). Loopback-only deployment means this is non-urgent (no XSS / log-injection in a single-user single-workstation context).

Rectification summary: 5/6 findings closed (F1-F5); 1/6 deferred (F6 LOW, pre-existing). Test count delta: 137 → 137 (F1 removed 1; F4 added 1). Ruff clean.
