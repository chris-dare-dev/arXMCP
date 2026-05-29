# Critique — notebook-bm25-isolation-m1

**Critic:** adversary
**Generated:** 2026-05-29T17:35:00Z
**Commit range:** d073c0a2c63a863d1a951cae0f2d11e1f56392b3..f6138a5
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the load-bearing correctness (lazy `None`-resolution of
  `BM25_INDEX_ROOT` at call time, both build call-sites threaded, FM-4
  early-return, sentinel fully removed, security chain preserved) is all
  correct; the only findings are test-surface quality issues, none on a
  production code path.
- Finding counts: 0 CRITICAL, 0 HIGH, 3 MEDIUM, 1 LOW.
- The cardinal point (synthesis §3 / FM-6) is verified clean: `ingest/bm25_indexer.py:129`
  resolves the module global at call time (`root = index_root if index_root is not None else BM25_INDEX_ROOT`),
  NOT frozen as a def-time default. The conftest autouse monkeypatch
  (`tests/conftest.py:209-234`) is preserved; 135/135 tests in the three
  edited modules pass.
- Both `build_bm25_index` callers are threaded: load path delegates via
  `_bm25_version_dir(...)` (`server/retrieval/bm25.py:451`) AND auto-build
  passes `index_root=` (`server/retrieval/bm25.py:463`). No production caller
  hard-codes the global root anymore (grep-verified).
- Highest-risk gap: AC-1's end-to-end claim — that a fork-C server BUILDS its
  BM25 under the notebook root via the *startup* path — is only implicitly
  covered by an unrelated `/readyz` boot test; no test asserts the artifact
  landed under `<slug>/index/bm25` (F2, MEDIUM).
- Cache byte-stability (Axis 1), no-fork (Axis 7), local-first (Axis 5), MCP
  spec (Axis 4), math fidelity (Axis 2) all axis-verified clean: `server/tools.py`,
  `server/prompts.py`, `pyproject.toml`, `uv.lock` untouched in-range.
- Security (Axis 3) clean: the per-notebook root flows from validated
  `notebook_dir(slug)` (slug regex + symlink-reject + containment check at
  `tools/_notebook_common.py:79-123`); the `_assert_dir_safe` /
  `_open_safely_for_load` 0o600 pickle-hardening chain
  (`server/retrieval/bm25.py:486,492,501`) operates on the threaded root
  unchanged — not weakened.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — AC-3 regression test has a broken chained-comparison guard

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_bm25.py:638
- **What:** `if version_a != version_b != 1:` is a Python chained comparison
  meaning `(version_a != version_b) and (version_b != 1)`, not the intended
  "skip unless both are 1". Verified empirically: `(va=1,vb=2)→skip=True`
  (would skip a valid scenario), `(va=2,vb=1)→skip=False`, `(va=5,vb=5)→skip=False`.
  The guard is asymmetric and does not express its docstring intent.
- **Why it matters:** The guard is currently inert because both notebooks land
  at MVCC version 1 (`skip=False` → test runs), so the test passes today. But
  it is dead/misleading logic in the file that AC-3 designates as the
  collision regression: a future corpus-setup change that yields any other
  version pairing could silently `pytest.skip` the AC-3 guarantee, masking a
  regression.
- **Proposed fix:** Replace with the explicit intent, e.g.
  `if not (version_a == 1 and version_b == 1): pytest.skip(...)` — or, since
  both builds use distinct roots, drop the version-equality skip entirely and
  assert the roots/chunk_ids differ regardless of the integers.
- **Regression guard:** Keep the existing `ids_list_a != ids_list_b` +
  `"2301" in ...` / `"2302" in ...` assertions (they already exercise the real
  isolation); just make the skip condition match its docstring.

### F2 — No test asserts fork-C STARTUP builds BM25 under the notebook root

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_server_startup.py:625
- **What:** AC-1's strongest claim is "a fork-C server loads/builds its BM25
  under `var/arxmcp/notebooks/<slug>/index/bm25/v<N>/`". The new tests cover
  the config-derivation (`test_notebook_derives_per_notebook_bm25_index_root`)
  and the `notebook_ingest.py` build call, but the END-TO-END startup path
  (`Resources.startup → BM25Phase.startup → _sync_startup` actually writing
  artifacts under the notebook root) is only implicitly exercised by the
  pre-existing `test_resources_startup_boots_notebook_corpus`, which asserts
  only `/readyz == 200` and the LanceDB version — it never inspects where the
  BM25 artifacts landed.
- **Why it matters:** The whole milestone exists because the STARTUP load/build
  path read the wrong (global) root. `resources.py:521` threading is verified
  by reading, but the threading is not pinned by an assertion — a future
  refactor of `resources.py` or `BM25Phase.startup` that drops the kwarg would
  pass every current test (the auto-build would just fall back to the global
  root and `/readyz` would still be 200). This is exactly the e3-class
  "summary claims correct, no test pins it" risk.
- **Proposed fix:** Extend `test_resources_startup_boots_notebook_corpus` (or
  add a sibling) to assert
  `(notebooks_base / "demo-nb" / "index" / "bm25" / f"v{nb_version}" / "bm25.pkl").is_file()`
  after boot, AND assert the global `_patched_bm25_index_root` (tmp_path) v-dir
  was NOT created. That pins the full `config → resources → BM25Phase` chain.
- **Regression guard:** The above two assertions in the notebook boot test.

### F3 — Idempotent-skip path of `build_bm25_index` is not exercised per-root

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/bm25_indexer.py:324
- **What:** The pre-fix `notebook_ingest.py` comment (now removed) flagged that
  `build_bm25_index`'s idempotent skip keys on the version dir existing. With
  the per-notebook root, the skip now keys on `<nb_root>/v<N>/`. No test
  verifies that a SECOND `build_bm25_index` call at the same version under the
  SAME notebook root idempotently skips (vs. the OLD collision where notebook
  B's v1 would no-op against notebook A's v1). The new tests use distinct
  roots, so the "same-root re-build skips correctly, different-root re-build
  rebuilds" boundary is untested.
- **Why it matters:** The collision the milestone fixes was rooted in the
  idempotent skip firing across notebooks. The fix relies on the skip now being
  scoped per-root. That scoping is correct by reading (`_bm25_version_dir`
  resolves the root first), but the regression that would re-introduce the bug
  (e.g. a future change that resolves the skip-check against the global root
  while building against the per-notebook root) would not be caught.
- **Proposed fix:** Add one test in `TestBM25IndexRootIsolation`: build under
  `root_a` twice at version 1, assert the second call hits the skip path
  (e.g. via `BM25Stats.skipped is True` or by asserting the pkl mtime is
  unchanged) AND that a build under `root_b` at version 1 does NOT skip.
- **Regression guard:** The test above.

### F4 — Test substring assertions assume POSIX path separator

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/tools/test_notebook_scripts.py:660
- **What:** `assert "index/bm25" in str(index_root)` and the FM-7 sentinel
  check use a hard-coded forward slash. On Windows `str(Path(...))` uses `\`,
  so `"index/bm25"` substring would be absent and the assertion would fail.
- **Why it matters:** The repo already carries ~29 known Windows-platform test
  failures (CLAUDE.md §3), so this is consistent with existing posture and
  non-blocking on the macOS/Linux authority. It is a latent foot-gun only.
- **Proposed fix:** Assert against the Path object structurally, e.g.
  `assert index_root.parts[-2:] == ("index", "bm25")` and
  `assert "myslug" in index_root.parts`, which is separator-agnostic.
- **Regression guard:** N/A (LOW — defer).

## What was done well

- The cardinal lazy-resolution semantic is implemented exactly per synthesis §3:
  `root = index_root if index_root is not None else BM25_INDEX_ROOT` inside the
  function body (`ingest/bm25_indexer.py:129`), NOT captured as a def-time
  default — the conftest autouse monkeypatch is preserved and explicitly
  re-pinned by `test_none_index_root_uses_monkeypatched_global`.
- Both `build_bm25_index` call sites are threaded — the load path delegates to
  `_bm25_version_dir(corpus_version, index_root=bm25_index_root)`
  (`server/retrieval/bm25.py:451`) and the auto-build passes `index_root=`
  (`:463`). The auto-build path (the one most likely to be missed and the one
  that would silently re-introduce the collision on first boot) was NOT missed.
- FM-4 shared-default-stays-global is correct: the validator early-returns at
  `server/config.py:468-469` when `notebook is None`, leaving `bm25_index_root`
  as `None`, and `test_shared_config_has_none_bm25_index_root` pins it.
- The `f"v{N}"` literal stays confined to `_bm25_version_dir`;
  `server/retrieval/bm25.py` delegates rather than rebuilding the path, so the
  existing single-source-of-truth test invariant is respected.
- FM-7 sentinel removal is complete, not partial: the `.notebook_slug` write,
  the collision-detection read, the defensive `mkdir`, and the now-stale
  `BM25_INDEX_ROOT` import are ALL gone from `tools/notebook_ingest.py`; no dead
  remnants remain, and `test_ingest_builds_bm25_under_per_notebook_root`
  asserts no sentinel is written.
- Security posture preserved: the per-notebook root derives from the validated
  `notebook_dir(slug)` (regex + symlink-reject + containment), and the 0o600
  chmod-before-rename + `_assert_dir_safe` + `_open_safely_for_load` pickle-load
  chain operates on the threaded root with no weakening.
- `config.py` and `notebook_ingest.py` derive the same path two ways
  (`derived.parent / "index" / "bm25"` vs `nb_dir / "index" / "bm25"`) and they
  reconcile to the identical location — no divergence between the build-time and
  startup-time roots.
- Clean axis hygiene: no MCP-surface change, no `EXPECTED_TOOL_SCHEMA_SHA256` /
  `EXPECTED_BP1_SHA256` touch, no new dependency, no `assert`-for-invariants in
  source, no `BaseHTTPMiddleware`, no vendored/forked code — exactly the 8
  files the contract scoped.
- Docstrings and comments were updated in lockstep with the behavior change
  (`notebook_ingest.py` module docstring documents the new isolation + FM-1
  auto-build safety net; the superseded textbook-ingest-m6 global-path rationale
  was retracted) — avoiding the stale-docstring anti-pattern.

## Recommended rectification order

1. F2 — add the startup-path artifact-location assertion (highest leverage:
   pins the exact regression the milestone exists to prevent; ~6 LOC in an
   existing test).
2. F3 — add the per-root idempotent-skip boundary test (pins the collision
   mechanism's fix; ~15 LOC).
3. F1 — fix the chained-comparison guard in the AC-3 test (~2 LOC; same file as
   F3, batch them).
4. F4 — (defer) separator-agnostic path assertions, only if touching that file.

## Rectification status (filled by Phase 4)

- **F1 (MEDIUM) — FIXED.** Removed the broken `if version_a != version_b != 1:
  pytest.skip(...)` chained-comparison guard in
  `tests/test_bm25.py::test_build_bm25_index_per_root_no_overlap`. The
  root/chunk_id isolation assertions hold for ANY version integers, so the skip
  was dead/misleading logic that could mask the AC-3 regression; dropped it.
- **F2 (MEDIUM) — FIXED.** Extended
  `tests/test_server_startup.py::test_resources_startup_boots_notebook_corpus` to
  assert the fork-C STARTUP path built `bm25.pkl` under
  `notebooks_base/demo-nb/index/bm25/v<N>/` AND that the global (conftest-patched)
  `BM25_INDEX_ROOT` has NO such version dir. This pins the full
  config→resources→BM25Phase.startup threading — a future refactor dropping the
  `bm25_index_root` kwarg (auto-build into the global root, /readyz still 200)
  would now fail. Closes the e3-class "verified by reading, not pinned" gap.
- **F3 (MEDIUM) — FIXED.** Added
  `tests/test_bm25.py::test_idempotent_skip_is_scoped_per_root`: spies on
  `open_chunks_table` (called only on a real build) to assert a second build at
  the same version under the SAME root skips (no re-read), while a build under a
  DIFFERENT root rebuilds — pinning the per-root scoping of the idempotent skip
  (the exact collision mechanism the milestone fixes).
- **F4 (LOW) — FIXED.** Replaced the POSIX-separator substring assertions in
  `tests/tools/test_notebook_scripts.py` (`"index/bm25" in str(index_root)`) with
  separator-agnostic `Path(index_root).parts[-2:] == ("index", "bm25")` +
  `"myslug" in parts`. Removes the latent Windows foot-gun.

**Invalidation summary:** 4 findings (0 CRITICAL, 0 HIGH, 3 MEDIUM, 1 LOW). All 4
FIXED — all test-surface quality (the production correctness was verified clean by
the critic, by reading + the full green suite). 0 invalidated. Adversary
invalidation rate: 0%. Sub-agent-implemented; the fresh-eyes critique tightened the
test surface (esp. F2 — the startup-path artifact-location pin).
