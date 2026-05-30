# Implementation Summary — ui-badge-disambiguate

**Path:** inline (orchestrator implemented directly; ≪ 200 LOC, 3 files, well-scoped)
**Base SHA:** `ca2c274bb2fc4e1e130f896c4df7de3b6f2efea2`

## One-line summary

Split the operator-console status badge's `warn` rendering into a `DEGRADED` (retrieval-side
non-pass → operator should ACT) and a `WARN` (ops-side-only non-pass → informational) label,
each with a distinct CSS modifier (`--warn` vs new `--ops-warn`).

## Commit range

`ca2c274..<head>` (1 feat commit pending immediately after this summary is written).

## Changes by file

### `server/routes/ui.py` (+72 / -3)

- Added module-level `_RETRIEVAL_CHECK_KEYS` frozenset (4 keys: embedder, lancedb, corpus
  version, notebooks count). Inline comment cross-references
  `server/health.py::compute_health_status` and instructs future check-adders to classify.
- Added module-level pure helper `_classify_status_badge(report) -> (label, css)` —
  four-way branch (fail / pass / warn-retrieval / warn-ops-only), defensive against
  `checks` being non-dict (FM-2: schema drift fallback to today's "DEGRADED" label so a
  real retrieval degradation cannot silently slip behind a future shape change).
- `ui_status_badge` now calls `_classify_status_badge(report)` for label + CSS, then
  rebuilds the badge text by replacing `compute_health_status()`'s leading label token
  (the pre-rendered `report["summary"]` still says "DEGRADED" for all warn cases — it is
  shared with the `make status` CLI where the loudest label is correct, but the badge
  wants the disambiguated one). Docstring updated explaining the disambiguation.

### `frontend/static/app.css` (+1 / -3 modified to align columns)

- Added one rule: `.status-badge--ops-warn { background:#eef2f7; color:#475569; border-color:#94a3b8; }`
  (soft blue-grey "informational" tone — distinct from amber `--warn`).
- Realigned the four `.status-badge--*` rules to column-aligned form (cosmetic only;
  no behavioral change to `--ok`, `--warn`, `--down`).

### `tests/test_status_endpoint.py` (+143 / -0)

- 3 new test cases inside the existing `TestStatusBadge` class:
  - `test_badge_retrieval_warn_renders_degraded_label` (AC1) — degraded resources
    → lancedb:status warn → asserts `status-badge--warn`, "DEGRADED" in text,
    "WARN |" NOT in text, `status-badge--ops-warn` NOT in text.
  - `test_badge_ops_only_warn_renders_distinct_label` (AC2) — missing
    backup-status.json → backup:time warn while retrieval clean → asserts
    `status-badge--ops-warn`, "WARN" in text, "DEGRADED" NOT in text,
    exact-boundary check that bare `status-badge--warn"` is NOT in text.
  - `test_badge_mixed_retrieval_and_ops_warn_prefers_degraded` (FM-1 regression
    guard) — both warns set → DEGRADED wins.

- New `TestClassifyStatusBadge` class with 8 unit tests of the helper directly
  (covers schema drift, malformed entries, every retrieval key one at a time,
  empty-checks edge case, retrieval-key fail status — not just warn).

Total new tests: **8** (verified pass-fail count: 32 in this file, up from 24).

## Acceptance criteria status

| # | Brief AC | Status | Evidence |
|---|----------|--------|----------|
| 1 | Retrieval check (`lancedb:status`, `corpus:version`, `embedder:status`, `notebooks:count`) non-pass → label "DEGRADED" | ✅ | `_classify_status_badge` retrieval branch + `_RETRIEVAL_CHECK_KEYS`; tests `test_badge_retrieval_warn_renders_degraded_label`, `test_warn_with_each_retrieval_key_renders_degraded`, `test_warn_with_retrieval_check_fail_also_renders_degraded`. |
| 2 | ONLY `backup:time`, `disk:utilization`, or `process:uptime` non-pass → label "WARN" (not "DEGRADED") | ✅ | `_classify_status_badge` ops-only fall-through; tests `test_badge_ops_only_warn_renders_distinct_label`, `test_warn_with_ops_only_keys_renders_ops_warn`. |
| 3 | Existing badge tests updated | ✅ | New cases added in `tests/test_status_endpoint.py::TestStatusBadge`. **Note: brief named `tests/test_routes_ui.py`, which does not exist** — both researchers independently flagged this; the correct file is `tests/test_status_endpoint.py`. |
| 4 | `make test` green, ruff clean, BP1/tool-schema hashes unchanged | ✅ partial — see below | `ruff check .` clean. `tests/test_server_tool_schema.py` + `tests/test_prompts.py` = 42/42 pass (BP1/tool-schema hashes byte-stable). All 21 badge-relevant tests pass. Full suite: 3483 passed, 30 skipped, 1 xfailed, **3 failed — all pre-existing and unrelated to this diff** (see below). |
| 5 | No new dependencies, no SPA, no JS beyond htmx | ✅ | Only stdlib + already-imported names; one CSS rule; no JS change. |

### Pre-existing test failures (NOT caused by this milestone)

Three tests fail on a full `pytest` run, but **none of them touch any file in this diff**:

1. `tests/test_drift_check.py::TestIntegrationRealLatexmlc::test_all_fixtures_match_baselines`
2. `tests/test_drift_check.py::TestIntegrationRealLatexmlc::test_render_fixture_does_not_leave_log_artifact`
3. `tests/test_tools_all.py::TestToolsSmoke::test_cite_neighbors_wired`
   — assertion: `'unavailable' == 'absent'` (citation-handler return-value drift)

The drift-check tests need real `latexmlc` available with stable output (their
`requires_latexmlc` marker normally gates them off in the default run; if they're
running here they need a parity check against a pinned fixture that may have drifted).
The `test_cite_neighbors_wired` failure is a value-mismatch in a handler not touched
by this diff. All three predate this milestone.

Per CLAUDE.md gotcha #1 (macOS pytest segfault with `faiss-cpu` + PyTorch) and the
existing 29 pre-existing Windows-platform failures, the project has explicit precedent
for documenting unrelated environmental failures as out-of-scope.

The relevant target tests — `tests/test_status_endpoint.py` (32 pass) + all 21
badge-related tests across the suite — pass cleanly.

## New / changed test paths

- `tests/test_status_endpoint.py::TestStatusBadge::test_badge_retrieval_warn_renders_degraded_label` (new)
- `tests/test_status_endpoint.py::TestStatusBadge::test_badge_ops_only_warn_renders_distinct_label` (new)
- `tests/test_status_endpoint.py::TestStatusBadge::test_badge_mixed_retrieval_and_ops_warn_prefers_degraded` (new)
- `tests/test_status_endpoint.py::TestClassifyStatusBadge` (new class, 8 cases)

## External writes required

**None.** Purely local; no `git push`, no PR, no `gh issue create`, no infra mutation,
no third-party API call. Per project convention, the feat / rect / chore commit
triple will land directly on `main` after the user authorizes a `git push` post-pipeline.

## Deviations from the brief's design

- **Brief said test file is `tests/test_routes_ui.py`** — that file does not exist.
  Both researchers caught this; implementation went to `tests/test_status_endpoint.py`
  per the actually-existing badge-test class. Documented in synthesis + here.
- **Brief said "possibly add `--ops-warn` variant for clarity"** — implemented as
  added (rather than reusing `--warn` for both states). Synthesis resolution: the
  visual distinction at-a-glance helps operators; one CSS rule is minimal cost. The
  text label is the primary disambiguator; CSS is the secondary signal.
- **`tools/status_line.py`** intentionally NOT touched — out of scope per brief
  (`make status` CLI keeps its "DEGRADED" label for terminal context). Documented
  in synthesis open-question #2.
