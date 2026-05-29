# Critique — notebook-surface-expansion-m1

**Critic:** adversary
**Generated:** 2026-05-29T00:00:00Z
**Commit range:** e01dee737a3bb645ad63fcce2f5d42074c8b2dcd..934ecba898500a7d4ee1bf346b9e38fac32928db
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: a small, correct, read-only UI render (handler + template + 4 tests); the only material gap is a test-surface hole around the operator-facing parse-status badge, which the recorded deviation makes the *primary* AC artifact.
- Finding counts: 0 CRITICAL, 0 HIGH, 1 MEDIUM, 2 LOW.
- Security (the e1 `security-reviewer` lens) is clean: Jinja2 autoescape is explicit and ON (`server/routes/ui.py:85-92`), zero `| safe` / zero `{% autoescape false %}` across all templates, and every new rendered value (`parse_status`, `latest_run.status`, the timestamps) is server-written and autoescaped.
- The notebook-scoped deviation (badge from `notebooks.parse_status`, not per-paper) is sound and explicitly recorded; both researchers concurred and the per-paper premise is unbuildable without a schema change the AC prohibits. Not flagged.
- Cache byte-stability (Axis 1) and MCP spec (Axis 4) are clean by construction: the range touches no `server/tools.py`, `server/prompts.py`, `EXPECTED_TOOL_SCHEMA_SHA256`, or any `tools/list` surface — it is `/ui` HTML only (confirmed by `git diff --name-only`).
- The highest-leverage residual is F1: the known-enum non-`skipped` parse_status mappings (`pending`/`running`→warn, `complete`→ok, `failed`→down) and the `failed` ingest-run render are entirely untested; only `skipped`→ok and the `futurestate`→warn fallback are exercised.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Known-enum parse-status + failed-ingest renders untested

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_notebook_detail_status.py:103-173
- **What:** The 4 tests exercise only two CSS-class outcomes: `skipped`→`status-badge--ok` (`test_arxiv_notebook_shows_skipped_badge_and_never_indexed`) and the `futurestate`→`status-badge--warn` forward-compat fallback (`test_unknown_future_status_renders_literally_with_warn_fallback`). The known-enum mappings that matter most to an operator — `failed`→`down`, `complete`→`ok`, `pending`/`running`→`warn` (`server/routes/ui.py:101-107`) — never render through a test. The ingest-run `status` is tested for `success` and `running` but never `failed`.
- **Why it matters:** The recorded deviation makes the notebook-scoped badge the SOLE artifact satisfying AC1's "operator sees parse/ingest state." The single most operator-relevant signal — a red `failed` parse badge — is the one with zero coverage. A future typo in `_PARSE_STATUS_CSS` (e.g. `"failed": "warn"`) would ship green. Low likelihood (trivial dict), but the AC's whole point is unverified for its most important value.
- **Proposed fix:** Add one parametrized test in `tests/test_notebook_detail_status.py` driving `parse_status` ∈ {`pending`,`running`,`complete`,`failed`} via the same raw-sqlite3 `UPDATE notebooks SET parse_status=?` pattern already used at line 124-132, asserting the expected `status-badge--{warn,warn,ok,down}` class and that the literal status text renders. Add a `failed`-ingest-run case (`_insert_ingest_run(..., status="failed", finished_at=...)`) asserting `"ingest failed"` renders and `"Never indexed"` does not.
- **Regression guard:** The parametrized badge-class test above is itself the guard; it fails on any `_PARSE_STATUS_CSS` value drift.

### F2 — Handler CSS fallback and template text fallback diverge on empty parse_status

- **Severity:** LOW
- **Source:** adversary
- **File:** server/routes/ui.py:262-264
- **What:** The handler computes the CSS class with `_PARSE_STATUS_CSS.get(notebook.get("parse_status") or "", "warn")` (empty/None → `warn`), while the template renders the badge *text* with `notebook.parse_status | default('unknown', true)` (`frontend/templates/notebook_detail.html:23`). On an empty/None `parse_status` the badge would read "unknown" but carry the `warn` class — two different fallback tokens for the same condition.
- **Why it matters:** Purely cosmetic and on an unreachable path: `parse_status` is `TEXT NOT NULL DEFAULT 'skipped'` (`server/notebooks_store.py:240-242`), so neither fallback can fire in practice (confirmed: FM-c is dead). No correctness or security impact; noted only so the two belt-and-suspenders defaults don't silently disagree if the column constraint ever changes.
- **Proposed fix:** Optionally align the tokens — e.g. add `"unknown": "warn"` semantics by mapping the handler's empty-string default to the same `'unknown'` label, or drop one of the two redundant fallbacks. Cheap, but defer; the path is unreachable.
- **Regression guard:** n/a (deferred; unreachable path).

### F3 — arxiv badge always "skipped" reads as not-indexed despite a successful ingest

- **Severity:** LOW
- **Source:** adversary
- **File:** frontend/templates/notebook_detail.html:22-32
- **What:** For arxiv-kind notebooks `parse_status` is permanently `skipped` (no PDF parse), so the "Parse status" badge always shows a green "skipped". Directly below, the freshness line can read "Last indexed <ts> (ingest success)". The two adjacent rows describe different subsystems (PDF parse vs index ingest) using similar vocabulary, which an operator may misread as contradictory ("skipped" yet "indexed").
- **Why it matters:** UX clarity only — both values are individually correct and the handler comment (`server/routes/ui.py:97-99`) documents that `skipped` is the normal arxiv state. No functional defect. Raised because the deviation elevates this badge to the AC's main signal, so its legibility is worth a note.
- **Proposed fix:** Optionally relabel the row "Parse status (PDF)" or add a one-line `<span class="hint">` clarifying that arxiv notebooks skip PDF parsing and rely on the ingest line below. Defer; cosmetic.
- **Regression guard:** n/a (deferred; presentation only).

## What was done well

- Security is genuinely tight for the audited surface: autoescape is explicit (not relying on Starlette's implicit default), the new template block carries an inline comment forbidding `| safe`, and a repo-wide grep confirms zero `| safe` / zero `{% autoescape false %}` — every new value (`parse_status`, `latest_run.status`, timestamps) is server-written and autoescaped.
- The deviation (notebook-scoped badge, not per-paper) is correctly grounded in the schema (`parse_status` is on `notebooks`, not `notebook_papers`), faithful to AC intent, and recorded in three places (synthesis, implementation-summary, template comment) — exactly the discipline a contested re-interpretation needs.
- Enum values were corrected against the actual `PARSE_STATUS_*` constants (`skipped/pending/running/complete/failed`) rather than the roadmap's wrong `pending/parsing/parsed` list.
- The `_PARSE_STATUS_CSS.get(..., "warn")` forward-compat fallback is the right shape (amber "attention" rather than a crashing match), and the reachable FM-d case (unknown future status) is explicitly tested to render literally without crashing.
- N+1 was correctly avoided: one O(1) `get_latest_ingest_run(slug)` call outside the papers loop, reusing the already-fetched `notebook` dict for `parse_status` (zero extra query) — matching the synthesis claim.
- The freshness logic correctly handles the running-with-NULL-`finished_at` case via `finished_at or started_at`, and the test asserts the `started_at` fallback — a real edge case, not a vacuous assertion.
- Tests are real: each asserts specific rendered substrings (`status-badge--ok`, `2026-05-28T03:30:00Z`, `ingest success`, `Never indexed` present/absent), not just HTTP 200. All 4 pass.
- The test seeding strategy (REST create + raw-sqlite3 INSERT under WAL) is a sound, documented way to avoid cross-event-loop `asyncio.Lock` acquisition while still exercising the lock-acquiring read paths.
- Correct scope hygiene: no MCP tool / `tools/list` / BP1 / `EXPECTED_TOOL_SCHEMA_SHA256` touched; no schema migration; no new route; no `| safe`; no dead imports (every new symbol in `server/routes/ui.py` is wired).
- The CSS classes the map emits (`ok`/`warn`/`down`) all exist in `frontend/static/app.css:123-125` — the badge will render styled, not bare.

## Recommended rectification order

1. **F1** (MEDIUM) — add the parametrized known-enum badge-class test plus a `failed`-ingest-run render case; closes the only material coverage gap and is ≤30 LOC in the existing test file.
2. **F2** (LOW) — defer unless trivially bundled; align the two empty-`parse_status` fallback tokens (unreachable path).
3. **F3** (LOW) — defer; optional label clarification for the arxiv "skipped" badge.

## Rectification status

Adversary SHIP-WITH-FIXES (0C/0H/1M/2L). F1 fixed; F3 fixed (cheap UX win on the
AC's headline signal); F2 deferred (unreachable + role-appropriate). m1 detail
test count 4 → 10. ruff clean.

- **F1 (MEDIUM) — FIXED.** Added a parametrized
  `test_known_enum_maps_to_expected_badge_class` (complete/skipped→`ok`,
  pending/running→`warn`, failed→`down`) + a
  `test_failed_run_renders_finished_at_and_failed_status` (a FAILED ingest run
  renders `finished_at` + "ingest failed", not "Never indexed"). Closes the only
  material coverage gap; ~30 LOC in the existing test file.
- **F3 (LOW) — FIXED.** The template now renders a one-line `<span class="hint">`
  next to the parse-status badge ONLY for arxiv-kind notebooks, clarifying that
  "skipped" is normal (no PDF to parse) and that "Last indexed" below is the
  indexing signal — removing the "skipped yet indexed" adjacency confusion the
  finding flagged. Cheap; improves the deviation-elevated headline signal.
- **F2 (LOW) — DEFERRED.** The handler's empty-`parse_status` CSS fallback
  (`"warn"`) vs the template label fallback (`"unknown"`) is on an UNREACHABLE
  path (`parse_status` is `TEXT NOT NULL DEFAULT 'skipped'`), and a CSS class
  ("warn" = amber) and a human label ("unknown") are appropriately different
  tokens for the same role-split — aligning them would arguably worsen the label.
  No code change.
