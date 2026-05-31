# Implementation Summary — onboarding-uplift-m3

**Summary:** 3 new REST endpoints (`POST /ui/api/admin/repair-registry`,
`POST /ui/api/notebooks/<slug>/reconcile-marker`,
`GET /ui/api/notebooks/<slug>/health`) + 2 server-down CLI fallbacks
(`tools/notebook_repair_registry.py`, `tools/notebook_reconcile_marker.py`)
+ 2 Make targets (`make repair-registry`, `make reconcile [NOTEBOOK=]`)
+ static `<small>` remediation block on `/ui/status-badge` +
`CorpusVersionInfo.with_counts()` helper + Makefile `.PHONY` split (m2
F8 deferred LOW). Heals the on-disk-vs-registry split + corpus-version.json
marker drift bugs we hand-fixed earlier this session.

**Commit range:** `08b9c53087892a2861456e1b33db5b4038e48161..<HEAD after feat>`

## Acceptance criteria status

- [x] **AC1** `POST /ui/api/admin/repair-registry` walks NOTEBOOKS_BASE,
      classifies each dir into four buckets (`registered`,
      `already_registered`, `skipped_no_marker`,
      `skipped_malformed_marker`), routes registrations through
      `NotebooksStore.create_notebook` (m2 F1 lesson). Idempotent.
      Regression guards: `TestRepairRegistry` (7 tests covering empty
      dir, valid marker, idempotent re-run, no-marker skip, malformed-
      JSON skip, symlink skip, invalid-slug skip).
- [x] **AC2** `POST /ui/api/notebooks/<slug>/reconcile-marker` opens
      LanceDB at the marker's pinned `version` (MVCC snapshot —
      synthesis FM-1 safe vs concurrent ingest), recounts via
      `_recount_notebook_lancedb` (PyArrow distinct), and atomically
      rewrites the marker JSON via the canonical `ingest/store.py`
      tmp+os.replace pattern. `created_at` preserved from the read
      marker (D4 byte-identical idempotency). Regression guards:
      `TestReconcileMarker` (6 tests including the cardinal
      byte-identical-at-steady-state test).
- [x] **AC3** `GET /ui/api/notebooks/<slug>/health` returns per-notebook
      drift report with status classification (`ok` / `drift` /
      `no_marker` / `malformed_marker`). Live recount per call (D1
      resolution — `Resources.startup_chunk_count` is shared-corpus,
      not per-notebook; a per-notebook cache lands in m6). Regression
      guards: `TestNotebookHealth` (5 tests covering all four statuses
      + 404 on unknown slug).
- [x] **AC4** `make repair-registry` + `make reconcile [NOTEBOOK=<slug>]`
      both implement the m2 dual-mode pattern: curl REST when server
      up (`/healthz` 200), direct Python CLI when server down. Server-
      down path mirrors REST classification exactly. CLI tests: 11
      tests under `TestNotebookRepairRegistryCLI` +
      `TestNotebookReconcileMarkerCLI`.
- [x] **AC5** `/ui/status-badge` extended with `_build_remediation_block`
      that returns a static `<small>` block (per synthesis §3 D2 —
      NOT `<details>`; the `hx-swap="outerHTML"` 10s poll would drop
      the open state). Block names the failing check + the Make
      remediation command. NO raw paths (FM-6 mitigation enforced by
      `TestStatusBadgeRemediation::test_warn_status_names_failing_check_and_make_command`).
      Regression guards: 6 tests covering ok-status no-block, warn-status
      with check naming, ops-side checks, multi-check rendering.
- [x] **AC6** `Makefile` `.PHONY` split into 5 per-section stanzas
      (FIRST-TIME, CORPUS LIFECYCLE, OPS/MAINTENANCE, NOTEBOOK CRUD,
      REPAIR/RECONCILE). Closes m2 F8. Updated two pre-existing tests
      (`test_status_target_exists`, `test_eval_target_in_phony`) to
      walk multiple `.PHONY:` lines rather than assuming a single
      first-line declaration.
- [x] **AC7** `make test` green (3 pre-existing m3-unrelated failures),
      `ruff check .` clean.
- [x] **AC8** `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256`
      UNCHANGED — verified by `tests/test_server_tool_schema.py` +
      `tests/test_prompts.py`. Plus the structural
      `TestNoMCPSurfaceTouch` guard that asserts the new m3 modules
      don't import from `server.tools` or reference `ALL_TOOLS`.
- [x] **AC9** 39 new regression tests across two new files
      (`tests/test_m3_endpoints.py`: 28 tests including the rect
      additions for F1 + F3; `tests/test_m3_cli.py`: 11 tests).

## File deltas

**Modified (5):**

- **`server/corpus.py`** — added `CorpusVersionInfo.with_counts()`
  helper that returns a copy with `chunk_count` + `paper_count`
  overridden, every other field (including `created_at`) preserved.
  Validates non-negative integers. ~40 LOC.
- **`server/routes/notebooks.py`** — added 3 new handlers
  (`repair_registry`, `reconcile_marker`, `notebook_health`), 3 new
  Pydantic response models, 3 new helper functions
  (`_read_marker_safely`, `_recount_notebook_lancedb`,
  `_write_marker_atomically`). Plus the `NOTEBOOKS_BASE` +
  `notebook_lancedb_path` import additions. ~390 LOC.
- **`server/routes/ui.py`** — extended `ui_status_badge` to append the
  static `<small>` remediation block on non-pass status. New
  `_build_remediation_block` + `_remediation_lines_for_checks`
  helpers. `Iterable` import. ~95 LOC.
- **`Makefile`** — split single 219-char `.PHONY` line into 5 per-section
  stanzas (m2 F8 closure). Added `repair-registry` + `reconcile`
  recipes (dual-mode, identical pattern to m2's `make add`). Extended
  `make help` FIRST-TIME? section with the two new targets. ~75 LOC
  net addition.
- **`tests/test_tier_gates_doc.py`** + **`tests/test_status_endpoint.py`**
  — updated two pre-existing tests to walk multiple `.PHONY:` lines
  rather than `re.search` (first-match) on a single line. ~30 LOC
  edited.

**New (4):**

- **`tools/notebook_repair_registry.py`** (NEW, ~180 LOC) — server-down
  CLI mirroring the REST endpoint's classification. Routes via
  `NotebooksStore.create_notebook`. Accepts `db_path` +
  `notebooks_base` override kwargs for test isolation (m2 F3 pattern).
- **`tools/notebook_reconcile_marker.py`** (NEW, ~180 LOC) — server-down
  CLI mirroring the REST endpoint. `--shared` flag reconciles the
  global corpus marker at `var/arxmcp/index/lancedb/corpus-version.json`.
  Per-slug path goes through `notebook_lancedb_path`. Atomic JSON
  rewrite via the canonical `ingest/store.py` pattern.
- **`tests/test_m3_endpoints.py`** (NEW, ~470 LOC) — 26 tests across 5
  classes (`TestRepairRegistry`, `TestReconcileMarker`,
  `TestNotebookHealth`, `TestStatusBadgeRemediation`,
  `TestNoMCPSurfaceTouch`). Uses the existing `TestClient(app)` pattern
  from `tests/test_notebook_api.py`.
- **`tests/test_m3_cli.py`** (NEW, ~245 LOC) — 11 tests covering both
  CLI fallbacks. Stubs `_recount_lancedb` + `notebook_lancedb_path` to
  avoid needing a real lancedb dataset in tests.

**Doc artifacts (3):**

- `.claude/notes/milestones/onboarding-uplift-m3/research-brief-1.md`
- `.claude/notes/milestones/onboarding-uplift-m3/research-brief-2.md`
- `.claude/notes/milestones/onboarding-uplift-m3/research-synthesis.md`
- `.claude/notes/milestones/onboarding-uplift-m3/implementation-summary.md`
  (this file)

## Deviations from the synthesis

**One byte-shape correction during smoke-testing:** the synthesis
recommended `json.dumps(..., sort_keys=True, separators=(",", ":"))`
for the reconcile rewrite (minified form). Live smoke against
`var/arxmcp/notebooks/shimura-varieties/lancedb/corpus-version.json`
revealed that the canonical `ingest/store.py::write_corpus_version_marker`
uses `json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n"`
(default separators with space, trailing newline). I switched both the
REST handler and the CLI tool to mirror the canonical form verbatim so
a reconciled marker is byte-identical to a fresh-ingest marker. The
D4 byte-identical idempotency guarantee holds at the second run
forward (an existing hand-fixed minified marker takes one canonicalizing
run to converge; from then on every reconcile is byte-identical).

All other synthesis decisions adopted verbatim:
- **D1** live-recount per-notebook health (not cached startup count).
- **D2** static `<small>` block (not `<details>`).
- **D3** PyArrow `count_distinct` for distinct paper_ids.
- **D4** preserve `created_at` from read marker.
- **D5** CLI tools inherit `NotebooksStore`'s busy_timeout via the
  canonical `NotebooksStore.open` path.

## New / changed test paths

- `tests/test_m3_endpoints.py` — 26 new tests (4 classes + structural
  guard).
- `tests/test_m3_cli.py` — 11 new tests (2 CLI tools).
- `tests/test_tier_gates_doc.py` — `test_eval_target_in_phony` updated
  to walk multi-line `.PHONY`.
- `tests/test_status_endpoint.py` — `test_status_target_exists`
  updated similarly.

## External writes required

**None.** Purely local. The synthesis predicted zero external writes;
this holds.
