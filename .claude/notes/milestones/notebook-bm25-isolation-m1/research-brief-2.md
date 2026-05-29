# Research Brief — notebook-bm25-isolation-m1

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-29T17:20:00Z

---

## In-codebase context

### The collision is already documented and its root cause confirmed

`tools/notebook_cutover.py:37-48` documents the live collision verbatim:
> "BM25 index root (`var/arxmcp/index/bm25/v<N>/`) is GLOBAL and keyed only on the per-dataset MVCC `corpus_version` — which is NOT globally unique across notebooks + the shared corpus (collision confirmed live: shared-corpus `v49` and shimura-varieties active are both v49)."

`notebook-cutover-m1` critique F1 (HIGH) identified the root cause and explicitly deferred it:
> "The proper fix — a per-notebook BM25 root coordinated with fork-C startup — is the BM25 analog of m1's `cache_db_path` isolation and is tracked as a separate follow-up."

### The three load-bearing seams

**Seam 1 — `ingest/bm25_indexer.py:104,114`:**
```
BM25_INDEX_ROOT = REPO_ROOT / "var" / "arxmcp" / "index" / BM25_DIR_NAME
def _bm25_version_dir(corpus_version: int) -> Path:
    return BM25_INDEX_ROOT / f"v{corpus_version}"
```
`_bm25_version_dir` hardcodes `BM25_INDEX_ROOT` as the sole root. `build_bm25_index` calls `_bm25_version_dir` internally — it accepts `lancedb_path` but NOT an explicit `bm25_root`. The root is not a parameter.

**Seam 2 — `server/retrieval/bm25.py:429`:**
```python
version_dir = _bm25_version_dir(corpus_version)
```
`BM25Phase._sync_startup` calls the same global `_bm25_version_dir` to locate the artifact before loading. This is the exact path that causes the unbootable-notebook failure.

**Seam 3 — `server/config.py:98-118`** (the precedent):
The `derive_notebook_lancedb_path` model-validator rewrites `lancedb_path` to `var/arxmcp/notebooks/<slug>/lancedb` when `ARXMCP_NOTEBOOK` is set, and also rewrites `cache_db_path` to `var/arxmcp/notebooks/<slug>/cache/retrieval.db`. A `bm25_index_root` field following this exact pattern is the correct analogous fix.

**Seam 4 — `server/resources.py:517-521`:**
```python
bm25_phase = await BM25Phase.startup(
    lancedb_path=config.lancedb_path,
    corpus_version=corpus_info.version,
    live_chunk_ids=live_chunk_ids,
)
```
`BM25Phase.startup` does not accept a `bm25_root` argument. It must be extended to accept one (or derive it from a module-level global that is monkey-patchable, matching the current test-patching pattern at `conftest.py:211-234`).

### The existing `notebook_ingest.py` sentinel approach is REPLACED by this fix

`tools/notebook_ingest.py:138-157` added a `.notebook_slug` sentinel as a workaround for the global-root collision. After this milestone ships, `notebook_ingest.py` must write to the PER-NOTEBOOK BM25 root (`var/arxmcp/notebooks/<slug>/index/bm25/v<N>/`) instead of `BM25_INDEX_ROOT`. The sentinel approach becomes unnecessary (the namespaces are isolated by directory), but may be kept as belt-and-suspenders.

### Cache isolation precedent (07-multi-agent-caching.md)

From `07-multi-agent-caching.md`: cache keys include `corpus_version` as a mandatory component. The BM25 `chunk_ids.json` plays a analogous role — it IS the corpus identity map for BM25. Any confusion between notebook and shared-corpus ids violates the deterministic-payload contract of note 07.

### Security note (08-security-observability-ops.md)

From `server/retrieval/bm25.py:19-31` (the pickle-loader hardening section):
> "when `var/arxmcp/index/bm25/` lives on a shared filesystem (NFS, Docker bind mount, multi-tenant container) an attacker who can write to that path achieves RCE in the server process via `pickle.load`."

The `_BM25_ARTIFACT_MODE = 0o600` and `_assert_dir_safe` + `_open_safely_for_load` chain enforce trusted-local safety. Moving the notebook BM25 root to `var/arxmcp/notebooks/<slug>/index/bm25/` must preserve 0o600 artifact mode. The atomic-write helpers in `bm25_indexer.py:194-237` already set `chmod 0o600` before rename — this is inherently preserved by the fix (no new write path). `_assert_dir_safe` checks the VERSION directory; `var/arxmcp/notebooks/<slug>/` is owned by the server process user (same as all other notebook dirs), so the trust posture is unchanged.

---

## Failure-mode analysis (PRIMARY deliverable)

### FM-1 — Fork-C first boot after fix: BM25 auto-build latency (acceptable cost)
**Trigger:** fork-C server starts with `ARXMCP_NOTEBOOK=<slug>` after this milestone ships. The notebook's BM25 artifacts have never been built under the new per-notebook root (`var/arxmcp/notebooks/<slug>/index/bm25/v<N>/`). The old global-root artifacts (`var/arxmcp/index/bm25/v<N>/`) from pre-fix runs exist but are NOT checked by the new path.
**Observable symptom:** `BM25Phase._sync_startup` sees `pkl_path.is_file()` → False, triggers auto-build via `build_bm25_index`. This is E04_S04 H1 behavior — it was always the fallback for a missing artifact. At seed-corpus scale (~50 papers) auto-build takes <10 seconds. At notebook scale (hundreds of papers) it could take 30-60 seconds — within acceptable startup latency.
**Mitigation:** Document in the tool's help text that first-boot after migration rebuilds BM25. The `notebook_ingest.py` run will pre-build under the new root for any notebook re-ingested after the fix. No action needed in the server itself — auto-build is the correct graceful path.
**Stale global artifact:** the old `var/arxmcp/index/bm25/v<N>/` artifacts from notebook ingests are now "orphaned" — the shared-corpus server still finds its OWN artifacts there (because the shared path is `var/arxmcp/index/bm25/v<N>/` and the shared corpus produces those), but a notebook's old v<N> artifacts may pollute if shared corpus happened to be at the same N. **This is actually the bug being fixed** — after the fix, the fork-C server no longer looks at the global root at all, so no cleanup is needed for correctness. The orphaned artifacts are harmless to shared-corpus operation.

### FM-2 — Two notebooks at the same version N: full separation after fix
**Trigger:** Notebooks A (slug=`shimura`) and B (slug=`algebraic-geometry`) are ingested independently; both happen to reach version 1 (their respective LanceDB MVCC version integers start at 1 for every new dataset).
**Pre-fix:** both map to `var/arxmcp/index/bm25/v1/`. Whichever runs `notebook_ingest.py` second finds the files exist (idempotent skip at `bm25_indexer.py:313`) and loads A's chunk_ids for B. Fork-C startup's F4 cross-check then fails with "chunk_ids contains N ids not present in the live LanceDB table."
**Post-fix:** A maps to `var/arxmcp/notebooks/shimura/index/bm25/v1/`; B maps to `var/arxmcp/notebooks/algebraic-geometry/index/bm25/v1/`. No collision. This is the regression test the AC requires.
**Mitigation:** The per-notebook directory tree is the mitigation. The `.notebook_slug` sentinel in `notebook_ingest.py` becomes redundant (but harmless — can stay as belt-and-suspenders or be removed).

### FM-3 — The chunk_id cross-check (F4) is the collision detector; fix makes it PASS correctly
**Trigger:** Pre-fix, fork-C loads the global `bm25/vN/chunk_ids.json` which contains arxiv chunk_ids from the shared corpus (or a different notebook). The live LanceDB table for the fork-C notebook has ONLY the notebook's textbook chunk_ids (prefix `textbook:<slug>:...`). The cross-check at `bm25.py:500-513` finds massive "missing" set → raises `BM25IndexUnavailableError`.
**Post-fix:** the per-notebook BM25 is built from the SAME LanceDB table that fork-C startup opened (same `lancedb_path`, same `corpus_version`). The chunk_ids in `chunk_ids.json` are exactly the notebook's chunks → cross-check passes for the right reason (not by disabling it).
**Confirm:** the fix does NOT touch the F4 cross-check logic. It merely changes WHICH directory the artifact is found in. The cross-check remains in place.

### FM-4 — Shared-corpus regression: config default must stay global
**Trigger:** `ARXMCP_NOTEBOOK` is unset (the common case). The `derive_notebook_lancedb_path` validator returns early (`if self.notebook is None: return self`). The new `bm25_index_root` field must have its default set to the global root (`var/arxmcp/index/bm25/`), NOT derived from anything, and the validator must only rewrite it when `notebook` is set.
**Observable symptom if regressed:** a shared-corpus server looks for its index under a nonexistent path, triggers auto-build from scratch (wasting minutes of compute), or fails entirely if the notebook-root path doesn't exist.
**Mitigation:** The model-validator pattern from `config.py:455` is the template — gate the rewrite on `if self.notebook is None: return self`. The default for `bm25_index_root` is `Path("var/arxmcp/index/bm25")`. Tests must assert this default is unchanged in the non-notebook case.

### FM-5 — `build_bm25_index` callers that bypass config: wrong root written
**Trigger:** Any caller that invokes `build_bm25_index` while still using the old `BM25_INDEX_ROOT` global will land the index under the global root — which fork-C will no longer find.
**Callers enumerated (via grep):**
1. `tools/notebook_ingest.py:152` — calls `build_bm25_index(str(lancedb_path), corpus_version=corpus_version)` AND hardcodes `BM25_INDEX_ROOT / f"v{corpus_version}"` for the sentinel check at line 138. **Must be updated** to use the per-notebook root.
2. `server/retrieval/bm25.py:441` (via `BM25Phase._sync_startup`) — calls `build_bm25_index(lancedb_path, corpus_version=corpus_version)`. This is the auto-build path. **Must be updated** to pass the per-notebook root.
3. No other callers of `build_bm25_index` exist in the codebase outside tests (confirmed: `ingest/bulk_ingest.py` does NOT call `build_bm25_index`; `ingest/store.py` does not; `ops/` scripts do not; `tests/eval/` does not call it directly).
**Mitigation:** `build_bm25_index` must accept an optional `bm25_root: Path | None = None` parameter that overrides `BM25_INDEX_ROOT` when set. `_bm25_version_dir` must be refactored to accept a `root` argument (or a new helper `_bm25_version_dir_for_root(corpus_version, root)` is added). The module-level `BM25_INDEX_ROOT` constant STAYS — it is the global default and must remain for shared-corpus and test-monkeypatching continuity.

### FM-6 — Test monkeypatching breaks if `_bm25_version_dir` closes over `BM25_INDEX_ROOT`
**Trigger:** `tests/conftest.py:229-233` monkeypatches `ingest.bm25_indexer.BM25_INDEX_ROOT`. This works today because `_bm25_version_dir` reads `BM25_INDEX_ROOT` at call time (it's a module global reference, not captured at function definition). `server/retrieval/bm25.py` imports `_bm25_version_dir` from `ingest.bm25_indexer` — if the fix adds a `root` parameter defaulting to `BM25_INDEX_ROOT`, the monkeypatch of `BM25_INDEX_ROOT` will NOT affect the imported `_bm25_version_dir` default unless the parameter default is re-evaluated dynamically.
**Observable symptom:** tests that monkeypatch `BM25_INDEX_ROOT` and then call `BM25Phase.startup` or `build_bm25_index` without the new `bm25_root` kwarg would land artifacts in the real global root, not the tmp_path, causing test pollution.
**Mitigation:** The fix should keep the default as `None` (sentinel) rather than `BM25_INDEX_ROOT`, with `_bm25_version_dir` resolving `BM25_INDEX_ROOT` at call time when `None` is passed. This preserves the monkeypatch semantics. Alternatively, the per-notebook-root path is threaded all the way through as an explicit argument (never relying on the global default), and tests pass it explicitly.

### FM-7 — `notebook_ingest.py` F2 sentinel becomes misleading after fix
**Trigger:** `notebook_ingest.py:139-157` writes a `.notebook_slug` sentinel to `BM25_INDEX_ROOT / f"v{corpus_version}"` AFTER the build to detect cross-notebook collisions. After the fix, the sentinel is written to the PER-NOTEBOOK root where there can be no cross-notebook collision (by construction). The sentinel logic silently becomes a no-op guard.
**Observable symptom:** The sentinel-check code at lines 140-151 reads the sentinel at the OLD (global) path. After the fix this directory is not where the notebook's BM25 lives. If left unchanged, the sentinel check looks at the GLOBAL root (which may or may not have a `.notebook_slug` from a pre-fix ingest run), potentially raising a spurious `NotebookError` even though there is no actual collision.
**Mitigation:** Remove the sentinel logic from `notebook_ingest.py` entirely, or update it to look at the per-notebook root. Since the per-notebook root has a 1:1 mapping by construction (only one notebook writes to `var/arxmcp/notebooks/<slug>/index/bm25/`), the sentinel is redundant and should be removed. The F7 "multiple v<N>/ dirs" warning in `notebook_ingest.py:167-175` also references `BM25_INDEX_ROOT` and must be updated to enumerate the per-notebook root instead.

---

## External sources

**rank_bm25 (version pinned in pyproject.toml):** `BM25Okapi` is a pure in-memory index. It has no concept of "roots" or paths — paths are entirely managed by `bm25_indexer.py`. No spec impact.

**MCP spec:** BM25 is a retrieval phase internal to the server; no MCP tool surface changes. `EXPECTED_TOOL_SCHEMA_SHA256` is unchanged — confirmed: this milestone adds a config field and changes internal artifact paths only. No `ALL_TOOLS` mutation.

**Anthropic prompt-caching docs:** `07-multi-agent-caching.md` is satisfied by this fix (it restores the correctness invariant that retrieval results are deterministic per corpus-version). No BP1/BP2 hash impact.

---

## Recommendation

**Thread `bm25_index_root: Path` through `build_bm25_index`, `BM25Phase.startup`, and `Config`; default to the current global root; rewrite in `derive_notebook_lancedb_path` when `notebook` is set.**

Concretely:
1. Add `bm25_index_root: Path | None = None` parameter to `build_bm25_index` and `BM25Phase.startup/_sync_startup`. When `None`, resolve to `BM25_INDEX_ROOT` at call time (preserves monkeypatch semantics in tests).
2. Add `bm25_index_root: Path = Path("var/arxmcp/index/bm25")` field to `Config`. In `derive_notebook_lancedb_path`, after deriving `lancedb_path`, also rewrite `bm25_index_root` to `var/arxmcp/notebooks/<slug>/index/bm25` (same pattern as `cache_db_path`).
3. In `Resources.startup`, pass `bm25_root=config.bm25_index_root` to `BM25Phase.startup`.
4. In `tools/notebook_ingest.py`, derive the per-notebook BM25 root from `notebook_dir(slug) / "index" / "bm25"` and pass it explicitly to `build_bm25_index`. Remove the `.notebook_slug` sentinel logic (redundant after isolation).
5. The `_bm25_version_dir` helper must accept an optional `root: Path | None = None` parameter; when `None`, fall back to reading `BM25_INDEX_ROOT` from the module global (so monkeypatching still works in tests).

This approach: (a) mirrors `derive_notebook_lancedb_path` exactly, (b) preserves all existing tests (the autouse `_patched_bm25_index_root` fixture in `conftest.py:209-234` continues to work because the default None falls through to `BM25_INDEX_ROOT` which is monkeypatched), (c) is the minimum seam change.

---

## Open questions

**OQ-1:** Should `notebook_ingest.py` still call `build_bm25_index` directly, or should it rely on fork-C auto-build at server startup? Recommendation: keep the explicit build in `notebook_ingest.py` (it runs once, pre-server, gives the operator a deterministic "ingest complete" signal; auto-build at startup is a fallback, not the primary path). The milestone brief marks the re-add of notebook-cutover BM25 build as OPTIONAL — leave it out.

**OQ-2:** Does `tools/notebook_cutover.py` need to re-add a BM25 build now that the namespace is isolated? The cutover swaps `lancedb-staging → lancedb`. The new version's BM25 will NOT exist under the notebook root until the next `notebook_ingest.py` run OR fork-C auto-build at next server startup. This is acceptable — auto-build at startup is the safety net. The milestone brief explicitly marks this re-add as optional/follow-up.

These are implementation-time decisions, not blockers. Proceed on the above recommendation.

---

## External writes the implementation will require

None — this milestone is purely local. No git push, no PR, no ticket, no infra mutation.
