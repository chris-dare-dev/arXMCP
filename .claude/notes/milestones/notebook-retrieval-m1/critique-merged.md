# Critique — notebook-retrieval-m1 (merged)

**Critics:** adversary (only — no infra-scoped files changed, so infra-safety did not fire)
**Generated:** 2026-05-28
**Commit range:** `da9a800f..56397647`
**Merged verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES. Fork-C routing is correct, Threat-1-gated, and BP1/tool-schema byte-stable. One HIGH: the persisted Tier-1 cache is shared across notebook relaunches and keyed without a notebook slug (F1) — a latent cross-notebook wrong-results/leakage vector on the relaunch workflow.
- Counts: **0 CRITICAL, 1 HIGH, 3 MEDIUM, 1 LOW**.
- Single critic (adversary); no cross-critic agreement section (infra-safety didn't fire — no Makefile/infra/CI edits).

## Findings (preserved IDs)

### F1 — Tier-1 cache shared across notebooks; key lacks notebook slug (HIGH)
- **File:** `server/config.py` (validator rewrites `lancedb_path` not `cache_db_path`); `server/cache_sqlite.py:103-141` (key); `server/resources.py:505-506` (shared open).
- **What:** The notebook validator leaves `cache_db_path` at the shared default; `Resources.startup` opens Tier-1 at that shared path keyed on `(query, filters, k, corpus_version, level)` — no slug. corpus_version is per-dataset MVCC (not globally unique), so two notebooks sharing a version → relaunch from A to B within the TTL serves A's chunks for a B query.
- **Fix:** in `derive_notebook_lancedb_path`, also redirect `cache_db_path` to a per-notebook sibling (`derived.parent / "cache" / "retrieval.db"`) when not explicitly set — structural isolation mirroring the lancedb isolation; avoids the slug-in-key refactor deferred to m2.
- **Regression guard:** two `Config(notebook=...)` with colliding corpus_version derive DISTINCT cache_db_path; + a cache miss-across-notebooks assertion.

### F2 — No end-to-end test that Resources.startup boots a notebook path (MEDIUM)
- **File:** `tests/test_server_startup.py` (TestNotebookConfig stops at config-string assertions).
- **What:** No test drives `Resources.startup(cfg)` against an `ARXMCP_NOTEBOOK`-derived path; only the derived string is asserted. The `seeded_lancedb` + `mocked_bge_m3` fixtures already exist to do it without a model.
- **Fix:** add a test that seeds `notebooks_base/<slug>/lancedb`, sets the notebook, runs `Resources.startup`, asserts the notebook's corpus_version is pinned + the opened table is the notebook's.

### F3 — Config `is_dir()` vs Resources `corpus-version.json` is a TOCTOU + partial-ingest gap (MEDIUM)
- **File:** `server/config.py` (`if not derived.is_dir()`) vs `server/resources.py:306` (`read_corpus_version`).
- **What:** `is_dir()` proves the lancedb dir exists, not that `corpus-version.json` is inside. A dir-present/marker-absent partial-ingest passes the AC5 config check then hits `CorpusNotIngestedError` at startup — the exact "deeper error not clean config error" AC5 was meant to prevent.
- **Fix:** check `(derived / "corpus-version.json").is_file()` (or `read_corpus_version(derived) is not None`) instead of `is_dir()`; one contract.

### F4 — Ambiguity guard rejects ARXMCP_LANCEDB_PATH set to its own default (MEDIUM)
- **File:** `server/config.py` (`if "lancedb_path" in self.model_fields_set`).
- **What:** Setting `ARXMCP_LANCEDB_PATH` to the exact default + `ARXMCP_NOTEBOOK` is rejected as ambiguous even though the value matches the default (no real conflict). Foot-gun for operators with a baseline `ARXMCP_LANCEDB_PATH` in a shell profile.
- **Fix:** only reject when the explicit value DIFFERS from the field default; pin the chosen semantics in a test.

### F5 — AC5 message names `tools/notebook_ingest.py`; verify it exists (LOW)
- **File:** `server/config.py` (AC5 message) + `tools/_notebook_common.py` (docstring).
- **What:** The remediation command + docstring name `tools/notebook_ingest.py`; nothing pins that the script exists (drift class).
- **Fix:** the script exists (verified) — add a guard test asserting `Path("tools/notebook_ingest.py").is_file()` co-located with the AC5 message test.

## Recommended rectification order
1. F1 (HIGH) — per-notebook cache_db_path.
2. F3 (MEDIUM) — tighten AC5 check to corpus-version.json.
3. F2 (MEDIUM) — Resources.startup boot test.
4. F4 (MEDIUM) — relax ambiguity guard to value-differs.
5. F5 (LOW) — guard test for the ingest-script path.

## Rectification status

All 5 findings dispositioned in `server/config.py::derive_notebook_lancedb_path`
+ `tests/test_server_startup.py`. Generated: 2026-05-28.

- **F1 (HIGH) — FIXED.** `derive_notebook_lancedb_path` now redirects
  `cache_db_path` to `var/arxmcp/notebooks/<slug>/cache/retrieval.db` when
  `ARXMCP_CACHE_DB_PATH` is not set explicitly (after the `lancedb_path`
  rewrite). Structural per-notebook isolation mirroring the lancedb
  isolation; no slug-in-key refactor (that stays deferred to m2). Guards:
  `test_notebook_derives_per_notebook_cache_db_path`,
  `test_two_notebooks_derive_distinct_cache_db_paths`,
  `test_explicit_cache_db_path_overrides_notebook_derivation`, and the
  cross-notebook miss assertion `test_notebook_cache_files_are_isolated`
  (writes under notebook A's derived file, asserts a MISS through B's).
- **F3 (MEDIUM) — FIXED.** The un-ingested check changed from
  `derived.is_dir()` to `(derived / "corpus-version.json").is_file()` — the
  SAME marker `Resources.startup` reads (`server/resources.py:308`), so the
  config gate and startup gate share one contract. A dir-present /
  marker-absent partial ingest now fails at config-load with the AC5
  message. Guard: `test_notebook_dir_present_but_marker_absent_rejected`
  (+ the two existing happy-path tests updated to seed the marker via
  `_seed_notebook_marker`).
- **F2 (MEDIUM) — FIXED.** Added `test_resources_startup_boots_notebook_corpus`:
  seeds ONLY the notebook corpus, sets `ARXMCP_NOTEBOOK`, runs the full
  lifespan, asserts `/readyz` 200 + the notebook's `corpus_version` pinned +
  the notebook's table opened (2 rows). Hermetic — patches the
  resources-level `_get_model`/`_get_tokenizer` (the names `resources.py`
  imports directly; `mocked_bge_m3` only patches `query_encoder`), so the
  boot test needs no real BGE-M3 download / HF Hub network.
- **F4 (MEDIUM) — FIXED.** The ambiguity guard now fires only when the
  explicit `lancedb_path` DIFFERS from the field default. Setting
  `ARXMCP_LANCEDB_PATH` to its own default value alongside `ARXMCP_NOTEBOOK`
  is a no-op, not a conflict (shell-profile foot-gun). Guards: existing
  `test_notebook_and_explicit_lancedb_path_rejected` updated to a non-default
  path; new `test_notebook_with_lancedb_path_at_default_allowed`.
- **F5 (LOW) — FIXED.** Added `test_ac5_named_ingest_script_exists` asserting
  `tools/notebook_ingest.py` exists, co-located with the AC5 message test —
  pins the remediation command against a silent-rename drift.

**Net new/changed tests:** +8 in `TestNotebookConfig` (F1×4, F2×1, F3×1,
F4×1, F5×1); 2 existing happy-path tests updated for the F3 marker contract;
1 existing ambiguity test updated for F4.
