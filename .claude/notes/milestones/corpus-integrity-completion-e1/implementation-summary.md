# Implementation Summary — corpus-integrity-completion-e1

**One-line summary:** Shipped the WAP gate (marker-file readback verify) inside `ingest/store.py::write_chunks` per spike-1 binding decision; 6 new mutation/positive tests in `tests/test_write_chunks_wap_gate.py`; m3 integration test restructured to validate the read-side detection independently of the now-shipped write-side gate; runbook extended with S5/S6 sections + WAP-gate triage subsection.

**Commit range:** `688b25f..HEAD` (one feat commit; orchestrator inline path).

**Implementation path:** inline (orchestrator main session, no worktree). Total LOC well under 500 / 5 files.

## Acceptance criteria status

- [x] **Gate site:** WAP-gate block in `ingest/store.py::write_chunks` placed AFTER the existing `try/except` at lines 931-977 closes, before `_append_store_stats(stats)`. **MET** — verified by direct read; new lines 988-1042 fall between line 977 (`        )` closing the swallow's logger.error) and the (now-shifted) `_append_store_stats(stats)` call.
- [x] **`read_corpus_version` is imported** — **MET via function-local import.** A module-level `from server.corpus import read_corpus_version` causes a circular import (`server/corpus.py:101` already does `from ingest.store import CORPUS_VERSION_MARKER_NAME, DEFAULT_LANCEDB_PATH`). The spike's §5 rect F5 import-direction analysis cited `ingest/bm25_indexer.py:87` as precedent, but that module is loaded lazily; `ingest.store` is loaded at server startup. Surgical fix: function-local import inside `write_chunks`. Documented in code comment at the import block. Runtime semantics identical.
- [x] **Three error arms:**
  - [x] `except ValueError` (malformed JSON / failed `from_dict`) → `raise RuntimeError` citing truncated atomic rename hypothesis. **MET.**
  - [x] `re_read_marker is None` (cold-clone) → `raise RuntimeError` citing missing-marker case. **MET.**
  - [x] `re_read_marker.chunk_count != fresh_count` → `raise RuntimeError` citing pre-m1-style regression vs swallow-stale-marker enumeration. **MET.**
- [x] **Error messages cite** target_path, diagnostic counts, likely-cause enumeration, preceding swallow-warning log line discriminator, `make reconcile` remediation, `docs/ops/corpus-drift-runbook.md` runbook URL. **MET** — verbatim copies of spike-1 §3 code shape.
- [x] **Gate is unconditional** (no feature flag, no env var). **MET.**
- [x] **Existing best-effort try/except swallow at lines 931-977 PRESERVED unchanged.** **MET** — gate is strictly additive AFTER the swallow's scope closes.

### Test plan AC

- [x] `tests/test_write_chunks_wap_gate.py` exists with **6 tests** (1 positive A + 1 positive B FM-13 + 4 mutations). All pass; `1.15s wall-clock`.
  - [x] `test_positive_path_single_call` — multi-call (3×10) ingest passes gate.
  - [x] `test_positive_path_re_embed_two_call_shape` — TWO sequential `write_chunks` calls on the same path pass gate (FM-13 coverage from research-synthesis).
  - [x] `test_mutation_A_wrong_value_marker` — `chunk_count=1` injected; COUNT-MISMATCH arm raises.
  - [x] `test_mutation_B_missing_marker` — marker writer raises IOError; swallow logs warning AND gate raises MISSING-marker; `caplog` asserts the swallow-warning discriminator is present.
  - [x] `test_mutation_C_malformed_marker` — marker file written as `"not valid json"`; gate's `except ValueError → raise RuntimeError` arm catches.
  - [x] `test_mutation_D_stale_marker_swallow` — pre-seed 2 papers (marker=20); monkeypatch writer to raise IOError; third `seed_corpus_multi_paper(n_papers=3)` call hits the gate on paper 3 (new paper adds 10 rows; marker stays stale at 20; COUNT-MISMATCH arm raises). Asserts (a) error text mentions the swallow-warning discriminator AND (b) the swallow itself logged the discriminator.

### Runbook extension AC

- [x] `docs/ops/corpus-drift-runbook.md` gains a new "WAP gate RuntimeError at ingest time (e1)" subsection under `## Symptom`, a WAP-gate triage subsection under `## Quick triage`, S5 + S6 entries under `## Likely causes`, and Fix S5 + Fix S6 procedures under `## Remediation`. **MET** — same commit as the gate code per spike-1 §3 rect F6.

## Decisions surfaced during implementation

1. **Circular-import discovery (DEVIATION FROM SPIKE §5 rect F5):** the spike claimed `ingest/bm25_indexer.py:87`'s `from server.corpus import open_chunks_table` was sufficient precedent that a top-level import in `ingest/store.py` would work. Direct test on `import ingest.store` raised `ImportError: cannot import name 'CORPUS_VERSION_MARKER_NAME' from partially initialized module 'ingest.store'`. **Resolution:** function-local import inside `write_chunks`. Documented in the module's import block AND at the gate site. Runtime semantics identical; no test impact.

2. **m3 integration test contract update:** the pre-existing `tests/test_server_startup_integration.py::test_pre_m1_bug_shape_is_caught_by_integration` test mutated `write_corpus_version_marker` during the ingest to inject the pre-m1 bug shape, then expected `/readyz` to catch it. With e1 in place, the gate now raises `RuntimeError` on the SECOND `write_chunks` call (marker=10 vs cumulative=20), so the original test pattern can no longer reach `/readyz`. **Resolution:** restructured the test to (a) run a clean `seed_corpus_multi_paper` ingest (gate passes), (b) manually overwrite the marker on disk to inject the pre-m1 chunk_count=10 — simulating the bypass paths the e1 gate does NOT cover (sibling marker writers, externally-edited markers, stale-backup restores), and (c) hit `/readyz` and assert degraded. The two layers are now complementary defence-in-depth: e1 catches at write boundary (fail-fast); m3 catches at server boot (recovery path for non-ingest-write corruption). The test's spirit is preserved; its name and AC are unchanged.

3. **`mutation D` test design correction:** the spike's original test plan said "pre-seed via `seed_corpus_multi_paper(n_papers=2)` then make a third `write_chunks` call." The naïve implementation (two back-to-back `n_papers=1` calls then a third `n_papers=1`) does NOT work because `seed_corpus_multi_paper` starts `paper_idx` from 1 every call — repeated calls write the SAME paper_ids and `merge_insert` upserts (table never grows). **Resolution:** pre-seed with `n_papers=2` (papers 1+2 land; table=20; marker=20), then call `n_papers=3` (papers 1 and 2 upsert silently; paper 3 is new; table=30; marker stays stale at 20 → COUNT-MISMATCH on paper 3's gate). Documented in the test's docstring. Net effect: the test correctly exercises the stale-marker production-common path.

## New / changed test paths

- `tests/test_write_chunks_wap_gate.py` (NEW) — 6 tests, ~290 LOC.
- `tests/test_server_startup_integration.py::test_pre_m1_bug_shape_is_caught_by_integration` (MODIFIED) — restructured to validate m3 read-side detection independently of e1 write-side gate. Removed `import ingest.store as store_mod` (now unused). Net delta: +60 LOC docstring/setup, -25 LOC monkeypatch boilerplate.

## Project check status

- `ruff check .` — clean.
- `make test` (3818 collected) — **3815 passed, 30 skipped, 1 xfailed, 3 failed**.
- The 3 failures are PRE-EXISTING and unrelated to e1:
  - `tests/test_drift_check.py::TestIntegrationRealLatexmlc::test_all_fixtures_match_baselines` — `latexmlc exited -6` (SIGABRT) — environmental (latexmlc binary version mismatch on macOS).
  - `tests/test_drift_check.py::TestIntegrationRealLatexmlc::test_render_fixture_does_not_leave_log_artifact` — same `latexmlc -6`.
  - `tests/test_tools_all.py::TestToolsSmoke::test_cite_neighbors_wired` — `httpx.RemoteProtocolError: Server disconnected without sending a response` — environmental TestClient lifespan flake.
- Verified pre-existing by `git stash` of e1 changes; the same 3 fail on `main` at `688b25f`. Not caused by e1; not in e1's blast radius.

## External writes the orchestrator must authorize

| type | target | why | blocking |
|---|---|---|---|
| `git_push` | `origin/main` | Land the feat + rect + chore commit triple after Phase 4 rectification | yes |

## Deviations from the brief's design

1. **Function-local import** of `read_corpus_version` (vs. spike's module-level import). Necessitated by circular import; documented above; runtime semantics identical.
2. **m3 integration test restructuring.** Not anticipated in the spike; necessary because the e1 gate now catches the bug shape at the write boundary, so the m3 test pattern of "ingest with bad marker then check /readyz" cannot run. Restructured to test the read-side detection independently (via post-ingest marker mutation). Strengthens — does NOT weaken — the test surface.
3. **Mutation D fixture pattern** (pre-seed n_papers=2 + call n_papers=3) vs. the spike's exact wording (pre-seed n_papers=2 + manual third write). The functional outcome is the same — the test exercises the COUNT-MISMATCH-on-stale-marker path on a genuinely-new third paper. The chosen pattern reuses `seed_corpus_multi_paper` (no new helper); the alternative would have required hand-rolling a `write_chunks` call with a custom paper_id.

None of these deviations change the gate's contract or its acceptance criteria. They are implementation-level adjustments to honor the spike's intent.
