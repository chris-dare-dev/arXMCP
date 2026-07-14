# Critique — source-truth-m3 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** 624fd94..d2d9fe6
**Diff stats:** 5 files, 1355 LOC
**Critique format version:** 1.0

## Verdict

SHIP. The primary axis (cache byte-stability) is verified clean on both hashes: `EXPECTED_TOOL_SCHEMA_SHA256` is untouched and green, and the manifest's own `content_hash`/`rollup_sha256` are deterministic with the `revisions` array explicitly sorted and the canonicalization reused verbatim from `_serialize_tools`. Allowlist-by-projection, the `<retrieved_manifest>` wrap, on-read read-only discipline, and the 24-test surface all hold under scrutiny. The single finding is a LOW defense-in-depth robustness note, not a live bug — the milestone is ready to ship.

## Executive summary

- [CLEAN] Axis 1a: `EXPECTED_TOOL_SCHEMA_SHA256` = `5189d7a6…ad394` UNCHANGED (not in the diff), `test_server_tool_schema.py` green; the wrap-tag edit lives in `wrap_retrieved_text`, not `ALL_TOOLS`/`TOOL_SCHEMA_VERSION` (still 18). Net-new guard test pins it with the resource registered.
- [CLEAN] Axis 1b: `compute_manifest_hash`/`rollup_sha256` use `sort_keys=True, separators=(",",":"), ensure_ascii=True` byte-identical to `_serialize_tools`; the `revisions` array + rollup input are both explicitly `sorted((work_id, arxiv_version))`; `generated_at` sits outside the hash boundary; read-stability test present.
- [CLEAN] Axis 3: allowlist-by-projection holds — `license_uri` and `display_name` are excluded; only closed-vocab enums / hex checksums / ints / ISO stamps cross; payload wrapped as `<retrieved_manifest>` (NOT the silent `<retrieved_chunk>` fallback) with payload-level escape-on-emit; delimiter-breakout test present.
- [CLEAN] Axis 4: resource registered in `register_resources()` AFTER tools / BEFORE mount (main.py:843→849→850), `mime_type="text/plain"` matches siblings, appears in `resources/list`, adds no tool (8-tool count pinned).
- [CLEAN] Axis 6: consumes m1's registry; `override` is read-only (no `set`/`set_setting` in the read path); zero m4 leakage (no coverage/serving/`is_open_access`/escalation path in the diff).
- [CLEAN] Axis 8: 24 tests cover content-hash determinism/stability, 3-paper on-disk re-hash, synthetic withdrawn+superseded invalidation, override absent+malformed, registry-absent degrade, corrupt-DB per-notebook isolation, and injection — including an end-to-end `mcp.read_resource` path.
- [CLEAN] Axis 5 (short-lived, file-existence-guarded per-notebook SQLite reads, no cloud dep) / Axis 2 (no math content flows) / Axis 7 (all original code) — verified clean.
- [LOW] The per-notebook failure-isolation invariant ("a corrupt notebook never fails the whole read") is enforced piece-wise, not by a blanket guard; it holds for all reachable exceptions today but is fragile to future edits.

## Findings

**L1 — Per-notebook failure isolation is piece-wise, not a blanket guard** (LOW)

**Where:** `server/corpus_manifest.py:486`
**Anchor:** `        notebooks[slug] = await _build_notebook_block(`
**What:** `build_manifest`'s per-notebook loop and the `_read_override` call at `:455` sit OUTSIDE any try/except; only `_load_records` (`:436`), `_safe_read_corpus_version` (self-guarding), and the `notebook_dir` guard (`:416`) catch failures, so the "degrade one notebook, never fail the whole `resources/read`" invariant (brief-2 §1.3/§5, risk 4) is guaranteed only for the specific exception types those narrow catches enumerate.
**Why it matters:** It holds today (every reachable exception from the three data sources — `sqlite3.DatabaseError`, `OSError`, `ValueError`, `NotebookError` — is handled, and `_check_key` cannot throw for a creation-validated slug), but a future data source added inside `_build_notebook_block` outside the existing try/excepts, or an unexpected exception type surfacing from the override read, would fail the entire manifest read instead of degrading one notebook — silently regressing the milestone's named resilience invariant.
**Proposed fix:** Wrap the `_build_notebook_block(...)` call in the loop in a blanket `except Exception` that degrades that one notebook to `{registry_present: False, registry_error: type(exc).__name__}` (reusing the existing degrade shape and the log-server-side/no-path-leak discipline), so the invariant holds unconditionally and survives future edits rather than resting on exhaustive enumeration of today's throwers.
**Regression-guard:** A test that seeds two notebooks where one raises a non-`(DatabaseError|OSError|ValueError)` exception during block assembly (e.g. monkeypatch `_read_override` to raise `RuntimeError`) and asserts the sibling notebook still resolves and the manifest still hashes cleanly.
**Source critic:** milestone-arxmcp-critic
**Source axis:** Axis 3 — security threat-model (per-notebook failure isolation / degrade-not-crash)

## What was done well

- **Byte-stability landmine defused correctly.** The `kind="manifest"` wrap was added to `wrap_retrieved_text`'s dispatch dict AND `_WRAP_TAG_MANIFEST` first (tools.py:534,590) — avoiding the silent `<retrieved_chunk>` fallback the research brief flagged — while leaving `ALL_TOOLS`/`TOOL_SCHEMA_VERSION` untouched, so `EXPECTED_TOOL_SCHEMA_SHA256` is provably unchanged.
- **Canonicalization reused, not re-invented.** `compute_manifest_hash` and `rollup_sha256` use the exact `sort_keys=True, separators=(",",":"), ensure_ascii=True` convention as `test_server_tool_schema.py::_serialize_tools`, inheriting its already-adjudicated cross-platform determinism.
- **Array-order determinism handled explicitly.** Both `_revisions_list` (:276) and `rollup_sha256` (:164) `sorted(..., key=lambda r: (r.work_id, r.arxiv_version))` rather than trusting incidental DB `ORDER BY` — the one thing `sort_keys` cannot do — with an in-code comment naming why it is load-bearing.
- **Hash boundary is structural, not convention-based.** `content_hash` is computed over `snapshot` alone with the three wire/read-time fields (`manifest_version`/`generated_at`/`content_hash`) deliberately outside it, so a client re-verifies by `compute_manifest_hash(payload["snapshot"])` with no "exclude these keys" convention to get wrong — proven end-to-end through `mcp.read_resource`.
- **Allowlist-by-projection is real, not aspirational.** `_revision_entry` ships only closed-vocab enums, hex checksums, and ISO stamps; `license_uri` and `display_name` are structurally absent, shrinking the injection surface — and the escape-on-emit is applied at the whole-payload level, so it also covers the `set_by`/`set_at` operator passthrough, not just `note`.
- **Fail-safe-disabled override read.** Absent key, missing store file, malformed JSON, missing/non-bool `enabled`, and an unreadable store all degrade to `_OVERRIDE_DISABLED` (WARNING-logged, never a silent permissive grant) — matching the track's any-doubt-falls-to-safe posture, with all six branches tested.
- **Read-only discipline is airtight.** Every store access is a guarded open-read-close; the `db_path.is_file()` / `settings_db_path.is_file()` guards prevent `DocumentsStore.open`/`OperatorSettingsStore.open` from creating an empty DB as a read side effect (regression-tested by `test_absent_registry_creates_no_db` + `test_read_path_creates_no_settings_file`).
- **Call-time resolution honors the test harness.** `settings_db_path` is resolved via attribute access at call time (`:479-480`), which is precisely what lets conftest's autouse `_patched_operator_settings_db` redirect keep the injection test hermetic — a subtle correctness detail the docstring calls out.
- **Test surface matches the ACs one-to-one**, including the necessarily-synthetic withdrawn/superseded fixtures (zero live rows exercise this) and the corrupt-`documents.db` isolation case that risk 4 specifically demanded.

Severity counts: C0 H0 M0 L1

## Recommended rectification order

L1

(L1 is LOW — deferred by default per the severity calibration; listed for completeness.)

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
