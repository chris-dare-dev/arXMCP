# Implementation Summary — corpus-integrity-completion-m3

**One-line summary:** Ship `tests/test_server_startup_integration.py` with the AC-required positive-path + mutation tests (plus a tolerance-floor sanity test); crosses the write→lifespan→/readyz seam end-to-end via real `write_chunks` + sync `TestClient`; closes KR-1 of the parent epic.

**Commit range:** `1a398f7..HEAD` (single feat commit).

**Implementation path:** inline (orchestrator main session). One new test file (`tests/test_server_startup_integration.py`, ~220 LOC). Zero source changes, zero new dependencies.

## Acceptance criteria status

- [x] **AC-1:** `tests/test_server_startup_integration.py` exists with `test_chunk_count_marker_equals_table_after_multi_paper_write` and `test_pre_m1_bug_shape_is_caught_by_integration`. **Met.** Both functions present; canonical names match the AC verbatim.

- [x] **AC-2:** Positive-path test exercises a real `write_chunks` call against `tmp_path`-rooted LanceDB; boots the FastAPI lifespan; asserts `GET /readyz` returns 200 with `body["chunk_count"] == body["marker_chunk_count"]`. **Met.** Per the m3 critique rect F1, the test uses the new multi-call helper `seed_corpus_multi_paper(lancedb_path, n_papers=3, chunks_per_paper=10)` from `tests/_corpus_helpers.py` — three `write_chunks` calls with 10 chunks per call, cumulative 30 rows. This matches the production bulk-ingest per-paper cadence AND reproduces the exact pre-m1 bug shape (last-batch-only `len(chunks)`). Boots `create_app(cfg)` under `with TestClient(app) as client:` (the canonical lifespan-trigger pattern per synthesis Mismatch B), and asserts `body["chunk_count"] is not None` (FM-5 guard) AND `body["chunk_count"] == body["marker_chunk_count"]`. The implementation adds a third sanity assertion `body["chunk_count"] == _CUMULATIVE_CHUNK_COUNT == 30` to pin the expected cumulative size — a regressed `chunk_count = len(chunks)` would publish 10 here (the per-call batch size) and fail the assertion with a diagnostic gap.

- [x] **AC-3:** Mutation test monkeypatches `ingest/store.py::write_corpus_version_marker` to write a deliberately-wrong `chunk_count`; asserts the positive-path detection fires. **Met.** The test wraps `store_mod.write_corpus_version_marker` with `bad_marker_writer` that uses `**kwargs` passthrough (rect F5: forward-compatible with future schema extensions) and forces `chunk_count = _CHUNKS_PER_PAPER = 10` — the EXACT value the pre-m1 bug shape would have written for a per-paper-batch of 10 chunks. (FM-9 guard: positive count, NOT a negative sentinel — the latter would route through "count unavailable, skip check" and silently bypass the detection.) Per synthesis §4 D4 the monkeypatch target is `ingest.store.write_corpus_version_marker` — the module's own namespace where `write_chunks` calls the function at bare name from `ingest/store.py:946`. The test asserts `/readyz` returns 503 with `body["status"] == "degraded"` and `body["reason"] == "chunk_count_diverged"`. **Coverage scope (rect F2):** this mutation intercepts ONLY the `ingest.store.write_corpus_version_marker` binding. Sibling marker writers at `server/routes/notebooks._rewrite_corpus_version_marker` and `tools/notebook_reconcile_marker.py` are NOT intercepted; a regression in either of those paths would not be caught by this test. Documented in the test file's module docstring; tracked in state.json `follow_ups` for a future epic.

- [x] **AC-4:** Both tests run under `make test` without the `requires_full_corpus` marker; ≤ 5s wall-clock per test. **Met.** Measured: 3 tests in 1.09s total (positive ~0.5s, mutation ~0.5s, sanity ~0.01s). The file's `pytestmark = []` line is an explicit "no opt-in markers" marker for future reviewers. The dual-module BGE-M3 patch via `_patch_model` (synthesis FM-1 top risk) keeps lifespan boot under 0.5s instead of the 5-30s real BGE-M3 cold-load.

- [x] **AC-5 (synthesis-derived):** Implementation summary documents that this test now protects against any future `len(chunks)`-flavored regression on the write path. **Met** in §"Regression-class coverage" below.

## Decisions made beyond / around the literal AC

The synthesis flagged TWO brief-vs-reality mismatches; the implementation honors both:

### Mismatch A — `tests/_graph_helpers.py` is NOT the right primary tool

The milestone brief said "use the synthetic-fixture pattern from `tests/_graph_helpers.py`" but both researchers verified end-to-end that `build_synthetic_lancedb` does NOT call `write_chunks`, does NOT write a `corpus-version.json` marker, and does NOT build HNSW indices — so `Resources.startup()` would raise `CorpusNotIngestedError` on its output. Per synthesis Mismatch A, the implementation imports `_seed_corpus` from `tests/test_corpus_count_reconciliation.py` (which does call real `write_chunks`). The synthesis also picked import-over-copy on maintenance grounds (one source of truth for the load-bearing `_patch_model` dual-module pattern).

### Mismatch B — `httpx.AsyncClient` is NOT the canonical pattern

The brief said "boot a real FastAPI lifespan via `httpx.AsyncClient` + the existing `tests/test_server_startup.py` TestClient bootstrap pattern" — a self-contradiction. The existing test exclusively uses sync `fastapi.testclient.TestClient`, the project has no `pytest-asyncio` dependency, no `asyncio_mode` in `pyproject.toml`, and the dual-mention in the brief is aspirational. Per synthesis Mismatch B, the implementation uses sync `TestClient(app)` with `with` block — the canonical FastAPI lifespan-trigger pattern.

### Sanity test added beyond AC-1

`test_synthetic_corpus_size_exceeds_divergence_tolerance_floor` is a third test the AC did NOT require. It calls `compute_chunk_count_divergence(1, 30, 0.05)` and asserts the result is `"rows_added"` — proving the math the mutation test depends on. If a future refactor changes `_SYNTHETIC_CORPUS_SIZE` without updating the mutation's injected count, this test fails loudly at collection time rather than silently letting the mutation test pass-vacuously. Cheap insurance (10 LOC) for the load-bearing tolerance-math contract.

## Regression-class coverage

This test surface now protects against the **entire `len(...)`-flavored chunk_count regression class**:

- **Direct re-regression:** any future commit that rewrites `chunk_count = tbl.count_rows()` back to `chunk_count = len(chunks)` (the pre-m1 bug shape) fails `test_chunk_count_marker_equals_table_after_multi_paper_write` AND `test_pre_m1_bug_shape_is_caught_by_integration` in CI.
- **Equivalent variants:** any flavor of "marker reflects the last per-paper batch only" — e.g. `chunk_count = stats.last_batch_size`, `chunk_count = paper_chunk_count`, `chunk_count = len(records_in_this_call)` — fails the same tests because the multi-paper seed exercises the cumulative path.
- **Marker-side corruption:** the mutation test's `bad_marker_writer` intercept generalizes to "any future code path that bypasses the table-count reconciliation" — including, e.g., a hypothetical optimization that caches a stale count.
- **Divergence-detection regression:** if `compute_chunk_count_divergence` or `Resources.startup`'s reconciliation contract regresses, the mutation test fails because the expected 503 + `chunk_count_diverged` doesn't fire.

The third test (`test_synthetic_corpus_size_exceeds_divergence_tolerance_floor`) protects against a future tolerance-math change that silently moves the divergence floor above 29 rows, which would silently disarm the mutation test.

## New / changed test paths

- **New:** `tests/test_server_startup_integration.py` (~220 LOC; 3 tests; 1.09s wall-clock total).
- **No changes** to existing tests, source modules, or configuration.

## Project check status

- `ruff check .` — clean ("All checks passed!").
- `tests/test_server_startup_integration.py` — 3 passed in 1.09s.
- Full suite (excluding opt-in markers + `tests/eval/`): the only failure is the same pre-existing `tests/test_tools_all.py::TestToolsSmoke::test_cite_neighbors_wired` local-env artifact that has been ignored throughout the corpus-integrity-completion pipeline. Unrelated to m3.
- No new dependencies. No changes to `pyproject.toml`. No re-pin of `EXPECTED_TOOL_SCHEMA_SHA256` / `EXPECTED_BP1_SHA256` (no MCP tool surface change).

## External writes the orchestrator must authorize

**None.** All file changes are local (one new test file). The eventual `git push origin main` after Phase 4 is a separate per-event authorization per CLAUDE.md §4.4 — not pre-authorized here. Synthesis §7 recorded `external_writes_required = []`.

## Deviations from the brief's design

Two deliberate deviations grounded in research synthesis:

1. **Tooling source — `_seed_corpus` over `build_synthetic_lancedb`** (synthesis Mismatch A). The brief's pointer would have produced a fixture that fails `Resources.startup` (no marker file). The correct tool was identified by both researchers and locked in synthesis §4 D2.
2. **Test client mode — sync `TestClient` over async `httpx.AsyncClient`** (synthesis Mismatch B). The brief's `httpx.AsyncClient` mention contradicts the project's actual dependency tree (no pytest-asyncio). Sync is the canonical and only-viable choice today.

One scope addition beyond the literal AC:

3. **Sanity test for the mutation's divergence math** (`test_synthetic_corpus_size_exceeds_divergence_tolerance_floor`). 10 LOC. Not required by AC but the tolerance-math contract is a pre-condition for the mutation test's effectiveness, and exposing it as a discrete test prevents a silent disarmament of the mutation test in a future refactor.

## Adversary critic preparation

The adversary critic will fire (always-on per pipeline rules). The infra-safety critic will NOT fire — no infra/, .github/workflows/, Dockerfile, docker-compose*, or Makefile changes. Likely critique axes:

- **Cache byte-stability:** N/A — no MCP surface, no `EXPECTED_TOOL_SCHEMA_SHA256` re-pin, no role-prefix change.
- **Math fidelity:** N/A — no LaTeX/MathML touched.
- **Security:** N/A — no tool input, no LaTeXML subprocess, no `paper_id` validation surface, no `<retrieved_chunk>` delimiter change.
- **MCP spec:** N/A — no tool surface change.
- **Local-first:** the test boots a sync `TestClient` (in-process ASGI; no HTTP server, no port bind). Trivially local-first.
- **Tier sequencing:** the test depends on m1 (the `chunk_count = tbl.count_rows()` fix), m2's gauge work, and Resources.startup divergence detection — all shipped. No tier-gap.
- **No-fork:** N/A.
- **Test surface:** the test IS the AC; uses the established `_seed_corpus` + `_patch_model` pattern; runs in default `make test`; ≤ 5s wall-clock per AC.

Likely deeper critique angles:

- The cross-test import (`from tests.test_corpus_count_reconciliation import _patch_model, _seed_corpus`) creates a load-bearing dependency on a sibling test file. If `test_corpus_count_reconciliation.py` is ever renamed or its helpers are moved, this test breaks. An alternative is copy-over-import (R1's preference); the synthesis pick was import-over-copy on maintenance grounds. The adversary critic may flag this — the implementation summary documents the deliberation.
- The synthesis explicitly resolved that the divergence path (503 / `chunk_count_diverged`) is the correct detection vector for the mutation test — NOT a plain assertion-failure on equal-counts. A critic might suggest BOTH paths should be exercised. Synthesizer judgment: testing both is redundant; the divergence path is the load-bearing observable (operators see it; tests cite it). Open for adversary review.
- The hardcoded `_SYNTHETIC_CORPUS_SIZE = 30` is documented but the test would still pass if the constant were silently changed (the sanity test catches the tolerance-math math, but not e.g. `_SYNTHETIC_CORPUS_SIZE = 2` which would still satisfy the math). A scope-shrinking refactor could weaken the test without failure. Defensible — the AC doesn't pin the exact count — but worth flagging.
