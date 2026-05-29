# Research Brief — notebook-bm25-isolation-m1

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-29T17:15:00Z

## In-codebase context

### 1. BM25 root machinery (exact file:line)

`ingest/bm25_indexer.py`:
- Line 104: `BM25_INDEX_ROOT = REPO_ROOT / "var" / "arxmcp" / "index" / BM25_DIR_NAME`
- Lines 108–114:
  ```python
  def _bm25_version_dir(corpus_version: int) -> Path:
      return BM25_INDEX_ROOT / f"v{corpus_version}"
  ```
- Lines 245–248: `def build_bm25_index(lancedb_path: str | Path, corpus_version: int) -> None:`
  — resolves output dir via `_bm25_version_dir(corpus_version)` (line 306), which reads
  the module-level `BM25_INDEX_ROOT` directly. There is NO `bm25_index_root` parameter.
- Artifact names: `BM25_INDEX_NAME = "bm25.pkl"`, `BM25_CHUNK_IDS_NAME = "chunk_ids.json"` (lines 102–103).

**The collision mechanism verbatim (from docstring):**
> "`bm25.pkl` is produced locally from trusted LanceDB data by this module. … The path
> `var/arxmcp/index/bm25/` MUST be treated as trusted-local."

### 2. Callers of BM25_INDEX_ROOT / _bm25_version_dir / build_bm25_index

All confirmed via grep:

| File | Usage | Notes |
|---|---|---|
| `server/retrieval/bm25.py:84–85` | imports `_bm25_version_dir`, `build_bm25_index` | BM25Phase._sync_startup uses both |
| `server/retrieval/bm25.py:429` | `version_dir = _bm25_version_dir(corpus_version)` | THE collision site |
| `server/resources.py:517–521` | `BM25Phase.startup(lancedb_path=config.lancedb_path, corpus_version=…)` | no bm25 root passed |
| `tools/notebook_ingest.py:39` | `from ingest.bm25_indexer import BM25_INDEX_ROOT, build_bm25_index` | |
| `tools/notebook_ingest.py:138` | `bm25_v_dir = BM25_INDEX_ROOT / f"v{corpus_version}"` | sentinel check |
| `tools/notebook_ingest.py:152` | `build_bm25_index(str(lancedb_path), corpus_version=corpus_version)` | ingest driver |
| `tools/notebook_ingest.py:167` | `BM25_INDEX_ROOT.glob("v*")` | stale-dir warning |
| `tests/conftest.py:210–234` | autouse monkeypatch of `ingest.bm25_indexer.BM25_INDEX_ROOT` into `tmp_path` | |
| `tests/test_bm25.py` (many) | monkeypatches `BM25_INDEX_ROOT` per-test | |
| `tests/test_notebook_cutover.py:103` | monkeypatches `BM25_INDEX_ROOT` | |
| `tests/tools/test_notebook_scripts.py` (many) | monkeypatches `BM25_INDEX_ROOT` | |
| `tests/retrieval/test_bm25.py:175` | monkeypatches `bm25_mod.BM25_INDEX_ROOT` | |

**Key observation:** the existing test isolation pattern is `monkeypatch.setattr(bm25_mod, "BM25_INDEX_ROOT", ...)`. This module-level global is the single writeable point. The fix must keep this pattern working for all existing tests.

### 3. Fork-C isolation precedent: `server/config.py`

The model-validator `derive_notebook_lancedb_path` (lines 419–515) is the exact pattern to mirror:

```python
@model_validator(mode="after")
def derive_notebook_lancedb_path(self) -> Config:
    if self.notebook is None:
        return self
    # ... ambiguity guard + slug validation ...
    derived = notebook_lancedb_path(self.notebook)
    # ... corpus-version.json check ...
    self.lancedb_path = derived
    # F1 rectification: redirect cache_db_path
    if "cache_db_path" not in self.model_fields_set:
        self.cache_db_path = derived.parent / "cache" / "retrieval.db"
    return self
```
(Lines 454–515)

`cache_db_path` default: `Path("var/arxmcp/cache/retrieval.db")` (line 134).
It is rewritten to `var/arxmcp/notebooks/<slug>/cache/retrieval.db` when notebook is set
(line 514: `self.cache_db_path = derived.parent / "cache" / "retrieval.db"`).

The pattern: `derived.parent` is `var/arxmcp/notebooks/<slug>/lancedb`.parent = `var/arxmcp/notebooks/<slug>/`. So for BM25, the analog is `var/arxmcp/notebooks/<slug>/index/bm25/`.

### 4. `tools/_notebook_common.py`: the canonical `notebook_dir` helper

- Line 33: `NOTEBOOKS_BASE: Path = REPO_ROOT / "var" / "arxmcp" / "notebooks"`
- Lines 79–123: `def notebook_dir(slug: str, *, base: Path | None = None) -> Path` — validates slug + containment + symlink rejection. Returns `NOTEBOOKS_BASE / slug` (resolved).
- Lines 126–147: `def notebook_lancedb_path(slug: str, *, base: Path | None = None) -> Path` — returns `notebook_dir(slug) / "lancedb"`.

**There is NO existing `notebook_bm25_root(slug)` helper.** The fix will add a
`bm25_index_root` Config field and wire the fork-C validator to set it.

### 5. BM25Phase.startup consumer (server/resources.py:509–521)

```python
from server.retrieval import BM25Phase

live_chunk_ids = set(
    chunks_table.to_arrow().column("chunk_id").to_pylist()
)
bm25_phase = await BM25Phase.startup(
    lancedb_path=config.lancedb_path,
    corpus_version=corpus_info.version,
    live_chunk_ids=live_chunk_ids,
)
```

`BM25Phase.startup` delegates to `BM25Phase._sync_startup` (line 414):

```python
version_dir = _bm25_version_dir(corpus_version)   # line 429
```

`_bm25_version_dir` reads the module-level `BM25_INDEX_ROOT` directly — there is no
`bm25_index_root` parameter passed from the caller. The fix must thread the root from
config through this call chain.

### 6. EXPECTED_TOOL_SCHEMA_SHA256 / EXPECTED_BP1_SHA256 — confirmed unaffected

This milestone adds no MCP tool and changes no tool schema or system prompt. Both hashes
must remain unchanged. Confirmed: `BM25Phase.startup` is server-internal startup logic,
not part of any tool handler or tool definition in `server/tools.py::ALL_TOOLS`.

### 7. notebook_ingest.py: the EXISTING sentinel workaround (lines 132–157)

`tools/notebook_ingest.py` currently works around the global-namespace collision by
writing a `.notebook_slug` sentinel file into `bm25/v<N>/` and raising `NotebookError`
if a different slug already owns that vN. **This sentinel workaround becomes unnecessary
once the root is per-notebook.** The implementer should remove it (or explicitly keep it
with a comment) as part of this fix — do not leave dead sentinel logic after the root is
isolated.

**The docstring at notebook_ingest.py:14–21 explicitly documents the limitation:**
> "The synthesis 'Disagreement 2' resolves in favor of the global BM25 path …
> Modifying `build_bm25_index` to accept a per-notebook output dir is out of m6's scope."
>
> This milestone IS that deferred fix.

### 8. Conflict with existing design note

The notebook_ingest.py docstring (lines 14–21) documents the global-path approach as a
deliberate scoping decision from textbook-ingest-m6. **This milestone supersedes it.**
The implementer must update the notebook_ingest.py docstring to reflect the new
per-notebook root.

### 9. `tests/conftest.py` autouse fixture (lines 210–234)

The autouse `_patched_bm25_index_root` fixture patches `ingest.bm25_indexer.BM25_INDEX_ROOT`
at the module level. Post-fix, when `BM25Phase._sync_startup` uses a *parameter* for the
root (instead of reading the module global), the conftest patch may no longer intercept the
BM25Phase path in tests that call `BM25Phase._sync_startup` directly. **The fix must
ensure BM25Phase._sync_startup still uses a patchable root, OR the conftest must also
patch the new Config field.** Recommend: keep the module-level global as the non-notebook
default, and thread the root only when changed.

## Prior decisions and lessons

- **notebook-cutover-m1 F1 (HIGH)** filed this exact problem: "The proper fix —
  per-notebook BM25 root coordinated with fork-C startup — is the BM25 analog of
  m1's `cache_db_path` isolation and is filed as a FOLLOW-UP." This milestone is
  that follow-up. See `.claude/notes/milestones/notebook-cutover-m1/critique-merged.md`.

- **notebook-cutover-m1 F1 rectification** removed `build_bm25_index` from
  `tools/notebook_cutover.py` entirely (fork-C startup auto-builds via E04_S04 H1).
  The cutover no longer writes any global BM25. After this milestone, the cutover
  can optionally re-add a per-notebook BM25 build (but is NOT required to — fork-C
  startup auto-builds at server start).

- **notebook-retrieval-m1 cache isolation** (server/config.py:513–514) is the exact
  pattern: `derived.parent / "cache" / "retrieval.db"`. The BM25 analog is
  `derived.parent / "index" / "bm25"`.

- **git log:** no notebook-bm25-related commits since the cutover-m1 rectification.
  The sentinel workaround in notebook_ingest.py is the only existing mitigation and
  it is incomplete (only covers `notebook_ingest.py` callers; fork-C startup still
  collides).

- **BM25_INDEX_ROOT module-global patching** is load-bearing for ~40 existing tests.
  Do not change the module global's name or remove it — keep it as the default for
  the non-notebook path.

- **08-security-observability-ops.md** notes: "BM25 pickle is application data with
  the analogous-narrower attack surface (trust local, deny remote)." The per-notebook
  root inherits this — it lives under `var/arxmcp/notebooks/<slug>/` which is also
  local-only. No new security surface.

## External sources

No external vendor docs are relevant. MCP spec and Anthropic prompt-caching docs are
unaffected — this milestone touches no tool surface, no system prompt, no cache breakpoints.

The `_bm25_version_dir` "sole-owner" constraint is already codified in the existing test:
`tests/test_bm25.py:535–550` asserts that no file other than `ingest/bm25_indexer.py`
constructs the `f"v{...}"` literal. Post-fix, `server/retrieval/bm25.py` must either:
(a) still delegate the version-path construction to a function in `bm25_indexer.py`, or
(b) the test must be updated. Option (a) is simpler — keep the helper, add an `index_root`
parameter to it.

## Recommendation

**Use a Config field + a single helper function parameter, mirroring the `cache_db_path`
isolation exactly.**

Specific implementation (minimal, all changes are additive):

1. **`ingest/bm25_indexer.py`**: Add an `index_root: Path | None = None` parameter to
   `build_bm25_index` (default `None` → uses `BM25_INDEX_ROOT`). Rename
   `_bm25_version_dir` to accept an optional `index_root` parameter with the same
   default. Export the updated function. All existing callers that pass no `index_root`
   continue to use the global default with zero change.

2. **`server/config.py`**: Add a field:
   ```python
   bm25_index_root: Path = Path("var/arxmcp/index/bm25")
   ```
   In `derive_notebook_lancedb_path`, after rewriting `lancedb_path`, add:
   ```python
   if "bm25_index_root" not in self.model_fields_set:
       self.bm25_index_root = derived.parent / "index" / "bm25"
   ```
   (`derived.parent` = `var/arxmcp/notebooks/<slug>/`)

3. **`server/retrieval/bm25.py`**: Add `bm25_index_root: Path | None = None` parameter
   to `BM25Phase.startup` and `BM25Phase._sync_startup`. Use it instead of calling the
   module-level `_bm25_version_dir` directly.

4. **`server/resources.py`**: Pass `bm25_index_root=config.bm25_index_root` to
   `BM25Phase.startup` at line 517.

5. **`tools/notebook_ingest.py`**: Remove the sentinel workaround (lines 132–157);
   call `build_bm25_index` with `index_root=nb_dir / "index" / "bm25"`. Update docstring.

6. **Tests**: Add one regression test asserting that two calls with version=N but
   different `index_root` values produce artifacts in non-overlapping paths (this test
   must fail on the pre-fix code). The existing conftest autouse patch remains valid
   because the module-level `BM25_INDEX_ROOT` is still the non-notebook default.

This design:
- Keeps the non-notebook path 100% unchanged (backward-compatible).
- Does not add any new public symbol to `server/tools.py` (EXPECTED_TOOL_SCHEMA_SHA256 unchanged).
- Does not change any system prompt (EXPECTED_BP1_SHA256 unchanged).
- Removes the sentinel workaround rather than layering on it.

## Open questions

No open questions — implementation can proceed on the above recommendation.

The only borderline decision is whether `notebook_cutover.py` should re-add a
per-notebook BM25 pre-build now that the root is safe. This is OPTIONAL per the brief
("can be a separate follow-up") and the AC does not require it. The implementer should
skip it to keep scope minimal; it can ship as a follow-up if desired.

## External writes the implementation will require

None — this milestone is purely local.
