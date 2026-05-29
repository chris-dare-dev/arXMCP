# Research Synthesis — notebook-bm25-isolation-m1

**Merged from:** research-brief-1.md (seam map) + research-brief-2.md (failure modes).
**Generated:** 2026-05-29.
**Verdict:** INLINE-or-DELEGATED, ~5 source files + tests, no novel architecture. Purely
local. Closes the notebook-cutover-m1 F1 (HIGH) follow-up. Both briefs concur on the
design; the one divergence (Config-field default) is resolved in §3.

## 1. The locked design

Thread an OPTIONAL BM25 index root through the build + load + config chain, mirroring the
existing fork-C `lancedb_path` / `cache_db_path` isolation. The non-notebook (shared)
path is 100% unchanged; fork-C gets a per-notebook root.

- `ingest/bm25_indexer.py`: add `index_root: Path | None = None` to `build_bm25_index`
  AND to `_bm25_version_dir`. When `None`, resolve the module-level `BM25_INDEX_ROOT`
  **at call time** (preserves the ~40 tests + the conftest autouse monkeypatch). Keep
  `BM25_INDEX_ROOT` and `_bm25_version_dir` — do NOT rename/remove. The `vN` literal must
  stay constructed ONLY in `bm25_indexer.py` (a test at `tests/test_bm25.py:535-550`
  asserts this — `server/retrieval/bm25.py` must DELEGATE to `_bm25_version_dir(version,
  index_root=...)`, not build the `vN` path itself).
- `server/config.py`: add `bm25_index_root: Path | None = None` (see §3 for why `None`).
  In `derive_notebook_lancedb_path` (the fork-C validator, ~:454-515), after rewriting
  `lancedb_path`, add — mirroring the `cache_db_path` rewrite:
  ```python
  if "bm25_index_root" not in self.model_fields_set:
      self.bm25_index_root = derived.parent / "index" / "bm25"
  ```
  (`derived.parent` = `var/arxmcp/notebooks/<slug>/`.)
- `server/retrieval/bm25.py`: add `bm25_index_root: Path | None = None` to
  `BM25Phase.startup` + `BM25Phase._sync_startup`; pass it to `_bm25_version_dir` (the
  load path, :429) AND to `build_bm25_index` (the auto-build path, :441).
- `server/resources.py` (~:517): pass `bm25_index_root=config.bm25_index_root` to
  `BM25Phase.startup`.
- `tools/notebook_ingest.py`: build under the per-notebook root
  (`notebook_dir(slug) / "index" / "bm25"`, via `tools/_notebook_common.py`), passing
  `index_root=` explicitly to `build_bm25_index`; **REMOVE the `.notebook_slug` sentinel
  workaround** (lines ~132-157) + update the stale-`v*`-dir warning (~:167) to enumerate
  the per-notebook root; update the docstring (it documents the now-superseded global-path
  scoping decision from textbook-ingest-m6).

## 2. Load-bearing facts (quoted, both briefs concur)

- **Collision mechanism:** `BM25_INDEX_ROOT = var/arxmcp/index/bm25` (`bm25_indexer.py:104`);
  `_bm25_version_dir(v) -> BM25_INDEX_ROOT / f"v{v}"` (:114). Keyed ONLY by the per-dataset
  MVCC integer → a notebook (shimura v49) and the shared corpus (also v49) map to the SAME
  `bm25/v49/`. Confirmed live in `notebook_cutover.py:37-48`.
- **The detector is the E07_S01 F4 chunk_id cross-check** (`server/retrieval/bm25.py:500-513`):
  fork-C loads the global `bm25/vN/chunk_ids.json` (shared-corpus arxiv ids) and cross-checks
  vs the live notebook table (textbook ids) → massive mismatch → `BM25IndexUnavailableError`
  (unbootable). The fix makes the per-notebook index's ids match the notebook table → the
  check passes **for the right reason** (the fix does NOT touch/disable the cross-check).
- **Fork-C precedent (mirror it):** `derive_notebook_lancedb_path` (`config.py:454-515`)
  rewrites `lancedb_path` → `var/arxmcp/notebooks/<slug>/lancedb` and `cache_db_path` →
  `derived.parent / "cache" / "retrieval.db"` (only when not explicitly set). The BM25
  analog is `derived.parent / "index" / "bm25"`.
- **`build_bm25_index` callers (grep-confirmed) — all must route the root correctly:**
  (1) `server/retrieval/bm25.py:441` auto-build, (2) `tools/notebook_ingest.py:152`. No
  other production callers (`bulk_ingest`/`store`/`ops`/`eval` do NOT call it). Tests
  monkeypatch `BM25_INDEX_ROOT`.
- **Security posture preserved:** BM25 artifacts are 0o600 trusted-local
  (`bm25_indexer.py:194-237` chmod-before-rename; `_assert_dir_safe`). Moving the root
  under `var/arxmcp/notebooks/<slug>/` (same process-user-owned tree) keeps the same trust
  posture — no new write path (08-security-observability-ops.md).
- **No MCP surface change:** BM25 is a server-internal retrieval phase.
  `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` UNCHANGED; no `ALL_TOOLS`/`prompts.py`
  change (07-multi-agent-caching.md hash-freeze respected). No new dependency
  (`rank_bm25` is path-agnostic).

## 3. Divergence resolved (orchestrator synthesis note)

**Config-field default: `Path("var/arxmcp/index/bm25")` (R1 rec #2) vs `None` (R1 §9 + R2
FM-6).** **RESOLVED → `bm25_index_root: Path | None = None`.** A CONCRETE default would be
held verbatim in the `Config` object and passed by `resources.py` to `BM25Phase.startup`,
**bypassing the conftest autouse monkeypatch of `ingest.bm25_indexer.BM25_INDEX_ROOT`**
(`tests/conftest.py:210-234`) — so any test booting via `Resources.startup` would write
BM25 artifacts to the REAL global root instead of `tmp_path` (test pollution; ~40 tests
affected). With `None`: shared/test path → `None` flows to `_bm25_version_dir(v,
index_root=None)` → resolves the (patchable) module global at call time; fork-C →
validator sets the notebook root. This is the load-bearing correctness point — both the
function-param defaults AND the Config-field default are `None`, resolving `BM25_INDEX_ROOT`
lazily at call time. (R1 and R2's recommendation bodies both ultimately land on the `None`
sentinel; only R1's terse rec #2 line said a concrete path — superseded here.)

## 4. Failure modes (brief-2) → required handling

- **FM-1 first-boot auto-build:** after this ships, a fork-C notebook's BM25 doesn't exist
  under the new root → `BM25Phase._sync_startup` auto-builds (E04_S04 H1) once at startup
  (seconds at seed/notebook scale). ACCEPTED; note it in the `notebook_ingest.py` docstring.
  The stale global `bm25/vN/` artifacts are harmless (the shared server still finds its own).
- **FM-4 shared-corpus regression (the cardinal risk):** the validator MUST early-return
  `if self.notebook is None` so the shared default stays the global root. Test: shared
  config (no `ARXMCP_NOTEBOOK`) → `bm25_index_root is None`/global; fork-C → notebook root.
- **FM-5 callers bypassing config:** both `build_bm25_index` callers
  (`bm25.py:441`, `notebook_ingest.py:152`) must pass the right root. Verified no others.
- **FM-6 monkeypatch preservation:** the `None`-default + lazy `BM25_INDEX_ROOT` resolution
  (§3) preserves the conftest patch — load-bearing.
- **FM-7 sentinel removal:** the `.notebook_slug` sentinel in `notebook_ingest.py` was the
  partial workaround; post-fix it reads the WRONG (global) path and can raise a SPURIOUS
  `NotebookError`. REMOVE it (the per-notebook directory is the 1:1 isolation now).
- **FM-2/FM-3:** two notebooks at the same N fully separate; the F4 cross-check passes for
  the right reason. These ARE the regression-test cases.

## 5. Acceptance criteria

1. A fork-C server (`ARXMCP_NOTEBOOK=<slug>`) loads/builds its BM25 under
   `var/arxmcp/notebooks/<slug>/index/bm25/v<N>/`, NOT the global root.
2. The shared (non-notebook) server uses the global `var/arxmcp/index/bm25/v<N>/`,
   unchanged (FM-4 — config test asserts the default).
3. Regression test: two builds at the SAME version `N` with different `index_root` resolve
   to DIFFERENT, non-overlapping artifact paths (no collision) — MUST fail on the pre-fix
   global-root code.
4. The `notebook_ingest.py` `.notebook_slug` sentinel workaround is removed; the build
   targets the per-notebook root; docstring updated.
5. `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` UNCHANGED; no `CHUNKER_VERSION`
   bump; `make test` green (the ~40 `BM25_INDEX_ROOT`-monkeypatching tests still pass).

## 6. Implementation order

1. `ingest/bm25_indexer.py` (`index_root` param on `_bm25_version_dir` + `build_bm25_index`,
   `None`→global at call time). 2. `server/config.py` (`bm25_index_root: Path | None = None`
   + fork-C validator rewrite). 3. `server/retrieval/bm25.py` (thread through
   `startup`/`_sync_startup`, both load + auto-build). 4. `server/resources.py` (pass
   `config.bm25_index_root`). 5. `tools/notebook_ingest.py` (per-notebook root + remove
   sentinel + docstring). 6. Tests: bm25_indexer regression (same-N-different-root), config
   fork-C-rewrite + shared-default, a fork-C startup isolation test, and confirm the
   conftest monkeypatch path still holds.

## 7. Open questions

**None blocking.** OQ-1 (keep `notebook_ingest.py`'s explicit build — yes, under the new
root) and OQ-2 (`notebook_cutover.py` BM25 re-add — OPTIONAL, OUT OF SCOPE; fork-C
auto-build is the safety net) are resolved per both briefs.

## 8. External writes required

**None** — purely local (`ingest/`, `server/`, `tools/`, tests). The per-notebook BM25
root is a local file tree under `var/arxmcp/notebooks/<slug>/` (gitignored). Both concur.
