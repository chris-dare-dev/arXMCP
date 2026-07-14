# Critique — source-truth-m3 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** 624fd94..d2d9fe6
**Diff stats:** 5 files, +1355/-4 LOC (code +561, tests +697, notes +97)
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES. The core content-addressing, invalidation (AC2), 3-way license census, registry-degrade, and tools/list byte-stability properties are correctly implemented and genuinely (not vacuously) tested — 97 passed / 1 win32 skip locally, EXPECTED_TOOL_SCHEMA_SHA256 unchanged. The one substantive defect is a read-purity violation: a `resources/read` of the manifest empirically WRITES to `notebooks.db` (creates the `operator_settings` table + a schema-sentinel row when that table is absent), directly contradicting the module's own "a read NEVER writes / no `set_setting` anywhere in this path" claim, and the sole read-purity test only covers the absent-FILE case. Fix the write-on-read (or correct the false claim and add the covering test), consciously accept the >400-LOC single-module diff, and this ships.

## Executive summary

- [MEDIUM] A manifest `resources/read` WRITES to `notebooks.db`: `OperatorSettingsStore.open()` runs `CREATE TABLE IF NOT EXISTS operator_settings` + a sentinel INSERT when the table is absent — empirically confirmed by a probe — contradicting `corpus_manifest.py`'s "read NEVER writes / no `set_setting`/`.set()` anywhere in this path" docstring and brief-2 §5.
- [MEDIUM] `test_read_path_creates_no_settings_file` asserts read-purity only for the absent-FILE case; the reachable file-present/table-absent write path (a server whose operator never persisted a setting via `make init EMAIL=`) has no covering test — false assurance.
- [MEDIUM] Code diff is +561 LOC (412 logic LOC in one new module), over the 400-LOC review-burden auto-flag; it is a single cohesive, heavily-docstringed, well-tested module — flag for conscious acceptance, not a defect.
- [LOW] Per-notebook failure isolation is asymmetric: `_read_override` runs OUTSIDE `_build_notebook_block`'s isolation `try/except`, so a settings-store error outside its internal `(DatabaseError, OSError)` catch would fail the WHOLE `resources/read`, not just one notebook.
- [LOW] The injection-surface claim ("`override.note` is the only operator-freeform field") understates it — `set_by`/`set_at`/`note` are all operator-authored and uncoerced; the global escape-on-emit does protect all three, so there is no functional gap, only an inaccurate narrowing.
- [CONTEXT] 0 CRITICAL / 0 HIGH is the calibrated outcome for this well-tested read-only resource: content-hash determinism, AC2 synthetic withdrawn+superseded fixtures, and the boundary pin were all steelmanned and held.

## Findings

**M1 — Manifest `resources/read` creates the `operator_settings` table (a write) despite the read-only claim** (MEDIUM)

**Where:** `server/corpus_manifest.py:354`
**Anchor:** `store = await OperatorSettingsStore.open`
**What:** `_read_override` guards only on `settings_db_path.is_file()`, then calls `OperatorSettingsStore.open()`, whose `_open_sync` -> `_apply_migrations` unconditionally runs `CREATE TABLE IF NOT EXISTS operator_settings` and (when the table was absent) an `INSERT OR REPLACE` sentinel row — so a `resources/read` writes to `notebooks.db`.
**Why it matters:** It contradicts this module's own binding claim (`corpus_manifest.py:33-39` "Read-only (CLAUDE.md §4.8) ... No ... `set_setting`/`.set()` ... anywhere in this path"; `:346-348`; brief-2 §5 "No write call appears anywhere in this path"), and downstream R4/R5 receipts are meant to cite this resource as provably read-only; the write is reachable on any server whose operator never persisted a setting (the lifespan in `server/main.py` never opens the settings store — grep confirms only comment references), confirmed empirically: a build_manifest against a freshly-created `notebooks.db` turned `operator_settings` from absent to present.
**Why it is MEDIUM not HIGH:** §4.8's binding scope is *corpus* state, and it explicitly carves out "server-internal operational writes (retrieval-cache SQLite ...) [as] implementation detail, not corpus writes" — this is a benign, idempotent, self-healing bookkeeping write to an operational table, not a corpus mutation and not a security exposure. The defect is the false absolute claim + a test gap, not an incident.
**Proposed fix:** Make the override read genuinely pure — open a read-only sqlite3 connection (`sqlite3.connect(f"file:{path}?mode=ro", uri=True)`) or first check `SELECT name FROM sqlite_master WHERE type='table' AND name='operator_settings'` and return `_OVERRIDE_DISABLED` if absent, bypassing `OperatorSettingsStore.open`'s migration entirely. If the benign table-creation is instead deemed acceptable, correct the three docstrings + brief-2 §5 to state "creates the operational `operator_settings` table if absent (a server-internal, non-corpus write)" and add the covering test below.
**Regression-guard:** A test that opens a `NotebooksStore` on a fresh `notebooks.db` (operator_settings table absent), snapshots `sqlite_master` table names, runs `build_manifest(..., settings_db_path=<that notebooks.db>)`, and asserts the table set is unchanged (currently it gains `operator_settings`).
**Source critic:** milestone-adversary-critic
**Source axis:** Data-plane boundary (read-only, §4.8)

**M2 — Code diff exceeds the 400-LOC review-burden threshold** (MEDIUM)

**Where:** `server/corpus_manifest.py:1`
**Anchor:** `"""Content-addressed corpus manifest buil`
**What:** The diff adds 561 code LOC (506 in the new `corpus_manifest.py`, of which 412 are non-blank/non-comment logic LOC; +40 `mcp_resources.py`, +15 `tools.py`), over the rubric's 400-LOC code auto-flag.
**Why it matters:** The rubric maps ">400 LOC" to a HIGH review-risk flag; large diffs are where regressions hide. Here the excess is a single cohesive, single-concern new module (pure builder + hash + rollup + guarded I/O helpers), ~40% docstrings, fully covered by 697 test LOC and 24 passing tests, with no cross-cutting edits to existing tool logic — so the risk profile is materially below the rubric's worst case, demoting it to MEDIUM per the "demote when it maps to no clear analog" guidance.
**Why it is MEDIUM not HIGH:** No incident-likely defect, no cross-module blast radius; it is a size-governance flag for a human to consciously accept, not split.
**Proposed fix:** Accept the diff size as-is (splitting a self-contained provenance module would add churn without reducing risk); record the conscious acceptance in the Phase-4 disposition.
**Regression-guard:** N/A (governance flag, not a behavioral defect).
**Source critic:** milestone-adversary-critic
**Source axis:** Diff size / review burden

**L1 — Override read sits outside the per-notebook failure-isolation boundary** (LOW)

**Where:** `server/corpus_manifest.py:455`
**Anchor:** `block["override"] = await _read_override(`
**What:** `_build_notebook_block` belt-and-braces isolates the corpus-version read (`_safe_read_corpus_version`, never raises) and the registry read (`_load_records`, wrapped in `try/except (sqlite3.DatabaseError, OSError, ValueError)`), but the final `_read_override` call is NOT inside any block-level `try/except` — it relies solely on `_read_override`'s narrower internal `(sqlite3.DatabaseError, OSError)` catch.
**Why it matters:** The milestone's headline property (brief-2 §1.3/§5/risk-4) is that a single unhealthy notebook degrades to `registry_present:false` and never fails the whole `resources/read`. A settings-store exception outside `(DatabaseError, OSError)` — e.g. `sqlite3.InterfaceError` (a sibling of `DatabaseError`, not a subclass) — would escape and fail the entire read. Low probability: `notebooks.db` is the central store and its realistic corruption surfaces as `DatabaseError`/`OperationalError`, both caught.
**Proposed fix:** Wrap the `_read_override` call in `_build_notebook_block` in the same isolation `try/except` used for the registry read (degrade to `override: _OVERRIDE_DISABLED` on any unexpected exception), so all three sub-reads share one isolation posture.
**Regression-guard:** (optional for LOW) A test injecting a raising fake `OperatorSettingsStore.open` and asserting the sibling notebook's block still resolves.
**Source critic:** milestone-adversary-critic
**Source axis:** Per-notebook failure isolation

**L2 — Injection-surface described as one field when three are operator-freeform** (LOW)

**Where:** `server/corpus_manifest.py:391`
**Anchor:** `"set_by": parsed.get("set_by"),`
**What:** `_read_override` surfaces `set_by`, `set_at`, and `note` verbatim from the operator-authored JSON blob (via `parsed.get`, uncoerced), but brief-2 §5 and `mcp_resources.py:219`/`corpus_manifest.py:252-253` describe `override.note` as "exactly one field" / "the only operator-freeform field".
**Why it matters:** All three carry operator-authored strings into the hashed, wrapped payload. There is NO functional gap today — `wrap_retrieved_text` escapes the delimiter over the whole serialized payload, so `set_by`/`set_at`/`note` (and any nested/non-string value) are equally protected — but the inaccurate "one field" framing is a latent trap: a future refactor to per-field escaping would silently miss `set_by`/`set_at`.
**Proposed fix:** Reword the claim to "three operator-authored fields (`set_by`/`set_at`/`note`), all neutralized by the payload-wide escape-on-emit"; optionally coerce the three to `str` (or drop unexpected types) in `_read_override`.
**Regression-guard:** (optional for LOW) Extend `test_override_note_delimiter_breakout_is_escaped` to place the `</retrieved_manifest>` payload in `set_by` as well as `note`.
**Source critic:** milestone-adversary-critic
**Source axis:** Injection surface / §4.9 trust language

## What was done well

- Content-hash determinism is handled correctly and defensibly: `compute_manifest_hash` hashes `snapshot` ALONE with the exact `test_server_tool_schema._serialize_tools` canonicalization, the three wire fields sit structurally outside the boundary, and the array-order landmine is closed by explicitly sorting both `revisions` and the `rollup` input by `(work_id, arxiv_version)` — read-stability verified across two reads.
- AC2 is proven with SYNTHETIC `withdrawn` AND `superseded` `upsert_records` fixtures (not a vacuous live-only pass), plus the free `0-invalidated -> rollup == active_rollup` invariant; invalidated rows are excluded from `active_rollup_sha256` yet retained in the full list, `rollup_sha256`, and `count_total`.
- The tools/list byte-stability boundary is pinned with a net-new manifest-specific test (`test_tools_list_hash_unchanged_with_manifest_resource`) that recomputes and compares to `EXPECTED_TOOL_SCHEMA_SHA256` rather than re-pinning it — and it passes; the wrap-tag lives in `wrap_retrieved_text`, never `ALL_TOOLS`.
- The brief-2 §5 wrap-tag landmine is correctly fixed: `_WRAP_TAG_MANIFEST` + a `"manifest"` dispatch entry, with the payload verifiably wrapping as `<retrieved_manifest>` (not `<retrieved_chunk>`) and an `override.note` delimiter-breakout escaped end-to-end through the resource.
- Registry-absent degrade never opens a missing `documents.db` (the open-creates-the-file side effect is `is_file()`-guarded and asserted by `test_absent_registry_creates_no_db`); a corrupt/truncated DB is isolated to one notebook and the whole manifest still hashes cleanly.
- Override fail-safe logic is genuinely thorough: absent key, missing file, malformed JSON, missing `enabled`, and non-bool `enabled` each degrade to disabled (WARNING-logged, never raised) — five distinct cases, each tested.
- §4.9 discipline honored: the 3-way census imports the `LICENSE_STATUS_*` constants (never re-typed literals), `unknown` is never folded, `total` is explicit, and registry vs corpus counts are kept as independent fields (no false reconcile-to-equal).
- `assert` is correctly avoided for invariants in production (`_require_store` raises `NotebookError`); the commit is GPG-signed (good signature) with the correct `Co-Authored-By: Claude Opus 4.8` trailer, a conventional `feat(server):` subject under 50 chars, and touches no `roadmap.yaml`/`state.json` (one-writer respected).

Severity counts: C0 H0 M2 L2

## Recommended rectification order

M1, M2, L1, L2

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
