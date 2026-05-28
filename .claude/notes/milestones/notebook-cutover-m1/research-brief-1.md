# Research Brief — notebook-cutover-m1

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-28T00:00:00Z

## In-codebase context

### Design notes that apply

**`05-storage-and-indexing.md`** — LanceDB MVCC section (verbatim):
> "Manual symlink swaps (`current -> v0007`) are **explicitly prohibited** under
> the new design. Use LanceDB's native MVCC mechanism instead."
> "Keep N=7 prior LanceDB dataset versions for rollback; a compaction job GCs
> older versions after readers have migrated (see E11)."

This applies to the SHARED corpus. The per-notebook `<slug>/lancedb` layout
(directory swap, not version checkout) is a different mechanism — it was
introduced by the notebook ingest path (`tools/notebook_ingest.py`) and was
never subjected to the MVCC constraint. The cutover milestone correctly uses
`os.rename` (directory swap), not LanceDB version manipulation.

**`07-multi-agent-caching.md`** — BP1 byte-stability: the `tools/list`
response must stay byte-stable. This milestone adds no MCP tool (X-1 confirmed
— no `EXPECTED_TOOL_SCHEMA_SHA256` re-pin needed).

**`08-security-observability-ops.md`** — Threat 1 (path traversal). The
`--notebook=<slug>` arg flows into `os.rename` on `<notebooks_base>/<slug>/lancedb`.
The existing `tools._notebook_common.validate_slug` + `notebook_dir` enforce
slug regex (`^[a-z][a-z0-9-]{2,30}$`) and symlink rejection before any path
construction. This contract MUST be reused, not re-implemented.

### E11_S05 cutover precedent — atomic swap sequence (verbatim from `ops/cutover.py`)

```
os.rename(active_path, rollback_path)   # step 1: lancedb → lancedb-prev
try:
    os.rename(staging_path, active_path)   # step 2: lancedb-staging → lancedb
except OSError as exc:
    os.rename(rollback_path, active_path)  # restore if step 2 fails
    raise CutoverError(...)
```

**Rollback (verbatim):**
```
os.rename(active_path, failed_cutover_dir)   # move promoted aside
os.rename(rollback_path, active_path)         # restore previous
```

The E11_S05 cutover also enforces cross-filesystem detection:
```python
active_dev = os.stat(active_path).st_dev
staging_dev = os.stat(staging_path).st_dev
rollback_parent_dev = os.stat(rollback_path.parent).st_dev
if not (active_dev == staging_dev == rollback_parent_dev):
    raise CutoverError(...)
```
This POSIX-atomicity guard MUST be replicated in the per-notebook version.

### Per-notebook path layout (confirmed from `tools/re_embed_all.py`, `tools/notebook_ingest.py`)

- `NOTEBOOKS_BASE = var/arxmcp/notebooks/`
- Per-notebook active: `<slug>/lancedb/`
- Per-notebook staging (produced by `re_embed`): `<slug>/lancedb-staging/`
- After cutover: `<slug>/lancedb-prev-<UTC-ts>/` (backup), `<slug>/lancedb/` (promoted)

### Critical: what the MCP server actually reads for notebook papers

**The MCP server does NOT read `<slug>/lancedb` at query time.** The server's
`Resources.startup` reads `config.lancedb_path` (= `var/arxmcp/index/lancedb`,
the SHARED arXiv corpus). For arXiv-kind notebooks, papers are in the shared
corpus and scoped by `filters["paper_id"]`. For textbook-kind notebooks,
`textbook-ingest-roadmap.md` mandates isolation: "textbook chunks live ONLY in
`var/arxmcp/notebooks/<slug>/lancedb/`" — but the query path for textbook
notebooks is NOT yet wired into the MCP retrieval pipeline (textbook-ingest-m2
through m6 wrote chunks into the per-notebook lancedb but the server's
`search_papers` handler uses `get_resources()` which reads only
`config.lancedb_path`).

**Implication for this milestone:** the cutover's primary purpose is to
advance the per-notebook active `lancedb` so that the NEXT `re_embed_all` run
uses the improved (2048-tok, preamble-populated) version as its re-embed
SOURCE. This is necessary AND valuable regardless of the query path question.
The brief's phrasing "MCP server reads `<notebook>/lancedb`" is an
oversimplification: it conflates ingest source (per-notebook) with query path
(shared). The implementer must not add a server-restart requirement based on
this incorrect framing.

### BM25 consistency (AC7) — resolved

`tools/notebook_ingest.py` calls `build_bm25_index(str(lancedb_path), corpus_version)` where `lancedb_path = nb_dir / "lancedb"` (the per-notebook dir). The BM25 output goes to the GLOBAL path `var/arxmcp/index/bm25/v<N>/`. After cutover, `<slug>/lancedb/corpus-version.json` will carry the new version (e.g. v645 for bridgeland). If a subsequent `re_embed_all` or `notebook_ingest` runs against the now-active lancedb, it will call `build_bm25_index` with the new version — which either already exists (idempotent-skip) or gets auto-built. Since the MCP server's BM25 is pinned at startup to `config.lancedb_path`'s `corpus_version` (the shared corpus), NOT the per-notebook corpus_version, the per-notebook BM25 is used only during INGEST (by `notebook_ingest.py`), not at query time.

**Resolution:** AC7 ("BM25 consistency after cutover") is satisfied by calling `build_bm25_index(new_active_lancedb_path, new_corpus_version)` AFTER the directory swap, within the cutover tool itself. This is a no-op if the index already exists (the `re_embed` pipeline already built it for the staging version), but ensures correctness without requiring operator awareness.

### Backup retention (AC6)

Live measurements (`du -sh`):
- bridgeland active: 505 MB; staging: 923 MB
- shimura active: 57 MB; staging: 143 MB

N=2 means keeping 2 × (505 + 57) MB ≈ 1.1 GB across two notebooks for
rollback. With N=2 `lancedb-prev-*` dirs, total per-notebook overhead is
bounded at 2× active size. This is reasonable. N=2 is correct and should be
hardcoded (not configurable) for v1.

### `corpus-version.json` after cutover

The staging dir already contains `corpus-version.json` with the new version
(written by `write_chunks`). After `os.rename(staging_path, active_path)`, the
active dir's `corpus-version.json` already has the correct new version. No
marker rewrite needed (same as E11_S05 docstring: "The staging
`corpus-version.json` already carries the correct version integer for the
now-active dataset. **No marker rewrite needed.**").

### Milestones that produced the gap

The gap is confirmed: `tools/re_embed_all.py` doc comment (verbatim):
> "Out of scope (intentional — keep this driver minimal): The atomic cutover from
> `<dataset>/lancedb-staging` → `<dataset>/lancedb`. Re-embed writes to a staging
> dir; the operator promotes it via the existing E11_S05 cutover tooling."

The E11_S05 cutover (`ops/cutover.py`) hardcodes the SHARED corpus path and
its 4-gate activation criteria. It does NOT apply to per-notebook datasets.

## Prior decisions and lessons

### Recent git log (last 20 commits — relevant)
- `2797349` — finalize notebook-preamble-recovery-m1 state → complete
- `14d0b10` — rect: close F1–F7, IS1 from notebook-preamble-recovery-m1
- `be1a3ff` — feat: fetch raw .tex on ar5iv path; back-fill preambles
- `b489048` — chore: quiet structural noise in re-embed logs
- `fcf728e` — fix(ingest): re_embed `_build_old_rows_index` also missed `to_arrow columns=` fix

The `fcf728e` fix is significant: a bug in `re_embed._build_old_rows_index`
affected the re-embed's ability to copy unchanged chunks. The current live
staging data was produced AFTER this fix.

### notebook-preamble-recovery-m1 deviations relevant here
The implementation summary states deferred operator deliverables:
- AC6: `get_definitions` canary measurement post-promote
- The `operator-followup.md` cross-references notebook-cutover-m1 as the
  promotion mechanism for the live staging data

**No conflict between the brief and codebase** on the cutover mechanism itself.

### Known landmines
1. `KMP_DUPLICATE_LIB_OK=TRUE` in `tests/conftest.py` — must not be removed
2. `assert` banned — use `if … raise RuntimeError` (CLAUDE.md §4.7)
3. `BaseHTTPMiddleware` banned — not relevant here (no server changes)
4. `notebook_dir(slug)` ALREADY enforces symlink rejection (m6 F3 contract)
   — DO NOT re-implement slug validation

## External sources

No external API surfaces are involved. This milestone is purely local
filesystem renames within `var/arxmcp/notebooks/`. POSIX `os.rename` is
atomic within a filesystem; the two notebooks and their staging dirs are
co-located under `var/arxmcp/` and are on the same filesystem (confirmed
by the same-st_dev check pattern already in `ops/cutover.py`). No MCP spec
implications (no tool surface change). No Anthropic prompt-caching doc
consultation needed (X-1, X-2 unchanged).

## Recommendation

**Implement `tools/notebook_cutover.py` as a new standalone file** (not a
`--cutover` flag on `re_embed_all.py`). Rationale: the cutover is a distinct
operation with its own safety gates, rollback semantics, and backup retention
logic. Mixing it into `re_embed_all.py` would violate the deliberate separation
documented in the re_embed_all.py docstring ("Out of scope — intentional"),
complicate testing (the re-embed tests mock out the model; cutover tests need
only filesystem fixtures), and blur the operator mental model.

**Structure:** adapt `ops/cutover.py`'s `perform_directory_swap` + `perform_rollback`
functions for per-notebook paths. The key differences from E11_S05:
1. No 4-gate activation criteria (seed eval, watchdog, ingest-complete,
   restore-drill) — these don't apply to notebook datasets
2. Use timestamped backup names: `lancedb-prev-<UTC-ts>` not `lancedb-prev`
3. N=2 retention with pruning of older `lancedb-prev-*` dirs
4. Per-notebook failure isolation in `--all-notebooks` mode
5. After the swap, call `build_bm25_index(new_active_path, new_version)` to
   guarantee BM25 consistency (idempotent-skip if already built)

**Default behavior:** `--all-notebooks` should be the default (promoting all
promotable notebooks atomically), with `--notebook=<slug>` for targeted
promotion. This mirrors E11_S05's bulk-first design philosophy.

**Server warning:** probe `127.0.0.1:7733/healthz` and WARN if server is
running, but allow (the per-notebook lancedb is NOT the server's live query
path, so hot-swap risk is lower than the brief implies — however warn anyway
for the textbook-kind future where the server may read per-notebook paths).

## Open questions

**AC7 BM25 consistency:** RESOLVED. The per-notebook BM25 index is built by
`notebook_ingest.py` after initial ingest and is stored globally at
`var/arxmcp/index/bm25/v<N>/`. At query time, the MCP server uses the SHARED
corpus BM25 (version from `config.lancedb_path`'s `corpus-version.json`), not
the per-notebook BM25. The cutover must call `build_bm25_index(new_active_path,
new_version)` post-swap to ensure the per-notebook ingest pipeline has a
correct BM25 for the newly-active version. This is idempotent if `re_embed`
already built it during staging.

**Backup disk cost:** QUANTIFIED. Bridgeland active: 505 MB, staging: 923 MB.
Shimura active: 57 MB, staging: 143 MB. N=2 adds at most 2 × 505 MB ≈ 1 GB
overhead for bridgeland. Acceptable. N=2 is right.

**New file vs `--cutover` flag:** RESOLVED. New file `tools/notebook_cutover.py`.

**`--all-notebooks` default:** RESOLVED. Make `--all-notebooks` the default;
require `--notebook=<slug>` to restrict. Per-notebook failures isolated.
Operator must pass either `--notebook` or `--all-notebooks` is implicit; a
bare invocation with no args promotes all promotable notebooks.

**No remaining open questions — implementation can proceed on the above recommendation.**

## External writes the implementation will require

The cutover is local filesystem renames within `var/arxmcp/notebooks/`.

| Type | Target | Why |
|---|---|---|
| Filesystem rename | `<slug>/lancedb` → `<slug>/lancedb-prev-<ts>` | Backup active |
| Filesystem rename | `<slug>/lancedb-staging` → `<slug>/lancedb` | Promote staging |
| Filesystem delete | old `lancedb-prev-*` beyond N=2 | Retention pruning |
| File create | `var/arxmcp/index/bm25/v<N>/bm25.pkl` + `chunk_ids.json` | BM25 consistency |

**None of these are external writes in the Phase-4 gate sense** (no git push,
no PR, no infra mutation, no API). They are local data movement operations.

**Nuance for auto-mode awareness:** a prior session blocked on a cutover-like
local data mutation (the operator-followup for embedder-truncation-m1 and
notebook-preamble-recovery-m1 was explicitly deferred to operator). The pattern
here is: the TOOL runs locally without authorization gates; but the OPERATOR
INVOCATION of `make notebook-cutover` (AC9) is explicitly deferred to the
operator post-milestone. The pipeline tests use synthetic fixtures, not the
live staging data. No Phase-4 authorization block expected.
