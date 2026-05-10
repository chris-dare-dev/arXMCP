# E03_S02 Research Brief 2 — Idempotent Re-embed

**Researcher:** Sonnet-B (parallel independent brief)
**Written:** 2026-05-07
**Branch:** `claude/gallant-blackburn-b89422`

---

## 1. In-codebase context

### Storage reality: NPZ-first, no LanceDB table

The milestone brief describes skip logic as "a pre-flight query over the
LanceDB table: `SELECT chunk_id, chunker_version FROM chunks WHERE
embedding_stmt IS NOT NULL OR embedding_proof IS NOT NULL`." This is
**structurally impossible in the current codebase.** E03_S01 (commit
`8ee41be` + rect `490c850`) wrote a pure NPZ-first embedder with no
LanceDB dependency. E04_S01 has not landed. The `ingest/embedder.py`
module docstring states:

> "Why NPZ-first, not direct LanceDB. The roadmap lists E03_S01 ↔ E04_S01
> as a mutual dependency, so neither can literally block on the other. The
> NPZ store breaks the deadlock: E03_S01 ships independent of E04_S01, and
> E04_S01's `ingest/store.py` reads the NPZ alongside the chunk manifests
> when building the LanceDB rows."

The NPZ at `var/arxmcp/corpus/embeddings/<paper_id>/embeddings.npz` contains
four arrays in alphabetical order (F5 close, required for BP1 byte-stability):
`chunk_ids_proof`, `chunk_ids_stmt`, `embedding_proof`, `embedding_stmt`.
It does **not** store `chunker_version` — only the chunk IDs (as Python
object-dtype string arrays) and the float32 vectors.

### chunk_manifest.json structure (E02_S04)

Written by `ingest/chunker._write_chunk_manifest`. Current schema (from
`chunker.py` line 1009–1026):

```json
{
  "chunker_version": "v1.0",
  "chunks": [
    {"chunk_id": "arxiv:2307.01156:a1b2c3d4e5f60718", "kind": "stmt"},
    ...
  ],
  "paper_id": "2307.01156"
}
```

`CHUNKER_VERSION = "v1.0"` is defined as a constant in
`ingest/chunker_types.py` (single source of truth). The docstring there
states: "bumping it signals the LanceDB MVCC writer (E04_S02) and the
re-embedder (E03_S02) that existing rows are stale."

Per-chunk JSON files at `var/arxmcp/corpus/chunks/<paper_id>/<hash16>.json`
also carry `"chunker_version": "v1.0"` in their `ChunkRecord.to_dict()`
output (sorted key order, load-bearing for BP1).

### Relevant design notes

- **04-parsing-and-chunking.md §"Chunker versioning":** "Every chunk carries
  `chunker_version`. When we change chunking strategy: 1. Bump version
  (`v1.0` → `v1.1`). 2. Re-chunk affected papers in a new corpus version.
  3. Re-embed chunks with the same embedding model (no need to re-train
  embedder)." This is the authoritative semantic definition of what a
  version bump means.

- **07-multi-agent-caching.md §"Property 2: Tool result payloads are
  canonicalized":** "JSON keys serialized in alphabetical order." The skip
  set is an internal structure not sent to agents, but any sidecar manifest
  written to disk should follow the same discipline to stay cache-friendly.

- **07-multi-agent-caching.md §"Chunk embedding cache (build-time,
  persistent)":** "Key by content hash, not chunk_id." The skip logic should
  treat chunk_id + chunker_version as a composite staleness key — chunk_ids
  are already content-addressable, so the combination is equivalent to
  `(content_hash, model_version)`.

- **08-security-observability-ops.md Threat 6:** The pinned
  `BGE_M3_COMMIT_SHA` is the "model identity" side of the skip key. Bumping
  `BGE_M3_COMMIT_SHA` must also force re-embed (different model = different
  embedding space). This is **not** addressed by `EXPECTED_CHUNKER_VERSION`
  alone; it needs separate handling. The NPZ sidecar should record
  `embedder_version` as well.

### Current `embed_paper` structure (load-bearing)

`_embed_paper_impl` in `ingest/embedder.py` currently:
1. Calls `_load_chunks(paper_id)` → loads all chunks from chunk JSON files
2. Calls `load_preamble(paper_id)` for the preamble prefix
3. Encodes ALL chunks unconditionally in batches
4. Writes `embeddings.npz` atomically via tmp + `os.replace`

`EmbedStats` tracks `chunks_skipped: int` (already present as a field,
initialized to 0 in every path). The `run_summary` JSONL line includes
`chunk_count` derived from `chunks_processed`. Skip logic must add to
`chunks_skipped` and subtract from `chunks_processed`.

### `EMBEDDER_VERSION` already defined

`ingest/embedder.py` line 77: `EMBEDDER_VERSION = f"bge-m3@{BGE_M3_COMMIT_SHA[:8]}"`.
This is the model-identity string already written to `EmbedStats`.

---

## 2. Prior decisions and lessons

### From commits 8ee41be + 490c850 (E03_S01)

The F4 fix introduced three specific exception subclasses
(`_ChunkFileMissingError`, `_ManifestCorruptError`, `_ChunkJsonCorruptError`)
and an `error_class` enum on `EmbedStats`. The same discipline should be
applied to skip logic: a skip due to "NPZ already populated + version match"
and a skip due to "manifest absent" are distinct states. The existing
`status="ok"` path with `chunks_processed=0` covers the manifest-absent case
already; the new "all chunks up to date" case needs a distinct log message
and must not inflate `chunks_processed`.

### BP1 discipline (07-multi-agent-caching.md)

The skip-set data structure (a dict mapping `chunk_id → chunker_version`) is
internal and not serialized into any cache-keyed structure. But any sidecar
file written to disk must use `sort_keys=True` in `json.dumps` and
`ensure_ascii=False`, matching `embed-stats.jsonl` and `chunk_manifest.json`.

### NPZ atomic write pattern (E03_S01, D10)

`_write_embeddings_npz` uses PID + UUID-suffixed tmp + `os.replace`. The
skip logic must NOT break this atomicity: if a paper's NPZ is found on disk
and all chunks pass the version check, the function must return without
touching the NPZ file (zero writes). If any chunk fails the version check
(or is new), the function must re-encode ALL chunks for that paper and
atomically replace the entire NPZ. Partial-update of an NPZ (appending
new arrays) is not supported by `np.savez`; partial writes would corrupt the
file. The correct semantics for a mixed paper (some chunks up-to-date, some
new) is: skip encoding old chunks, encode only new/stale chunks, then write
a new NPZ containing all chunk embeddings (re-using cached vectors for the
unchanged ones).

### Model-identity as a skip dimension

`04-parsing-and-chunking.md §"Chunker versioning"` step 3: "Re-embed chunks
with the same embedding model." But a `BGE_M3_COMMIT_SHA` bump means a new
embedding model — the existing vectors are invalid against the new index.
The sidecar must record `embedder_version` (= `EMBEDDER_VERSION` constant)
alongside `chunker_version` so a model upgrade triggers re-embed even when
`chunker_version` is unchanged.

---

## 3. External sources

### NumPy NPZ — cheap header reads without loading vectors

`np.load(path, mmap_mode='r')` returns an `NpzFile` object that memory-maps
the underlying ZIP. Accessing `npz.files` (the list of array names) and
`npz['chunk_ids_stmt']` (a 1-D object array of strings) does NOT load the
float32 embedding matrices into RAM — only the requested sub-array is
paged in. For the skip pre-flight, the implementation should:

```python
with np.load(npz_path, allow_pickle=False, mmap_mode='r') as npz:
    known_stmt  = set(npz['chunk_ids_stmt'].tolist())
    known_proof = set(npz['chunk_ids_proof'].tolist())
```

This reads only the two string arrays (cheap — each is a short list of
~N × 40-byte strings), leaving the `(N, 1024)` float32 matrices unmapped.
`allow_pickle=False` is required; the chunk_id arrays use `dtype=object`
(unicode strings via numpy's object array mechanism), which `np.savez` stores
as pickled objects by default. The existing `_write_embeddings_npz` passes
`np.asarray(chunk_ids_stmt, dtype=object)` — so `allow_pickle=True` IS
required to read them back. This is a known limitation: object-dtype arrays
in NPZ require pickle. Since the NPZ is written by our own trusted code path,
`allow_pickle=True` is safe here (Threat 6 applies to model weights, not
our own artifact files).

NumPy documentation on `mmap_mode`: "Memory mapping is especially useful for
accessing small fragments of large files without reading the entire file into
memory." The `chunk_ids_*` arrays are small fragments of an otherwise-large
NPZ; mmap lets the OS page-fault in only those arrays.

---

## Open questions

### The central question: LanceDB table → NPZ-first adaptation

The brief assumes a LanceDB pre-flight query. The actual storage is NPZ files.
Three options for implementing the skip set:

**(a) NPZ presence check + read chunk_ids arrays.** Load
`embeddings/<paper_id>/embeddings.npz` if it exists. Read `chunk_ids_stmt`
and `chunk_ids_proof` to build the set of already-embedded chunk IDs. Cross
with `chunk_manifest.json` to find new chunks. Check `chunker_version` via a
sidecar manifest (since the NPZ itself doesn't store version info).

**(b) Sidecar `embeddings_manifest.json` per paper.** Write a companion file
alongside `embeddings.npz` with schema:
```json
{
  "chunker_version": "v1.0",
  "embedder_version": "bge-m3@5617a9f6",
  "embedded_chunks": [
    {"chunk_id": "arxiv:...:hash16", "kind": "stmt"},
    ...
  ],
  "paper_id": "2307.01156"
}
```
Written atomically (same tmp + `os.replace` pattern) immediately after the
NPZ write. Skip pre-flight reads only this file (no NPZ open needed).

**(c) Hash `chunker_version` into the NPZ filename.** E.g.
`embeddings_v1.0.npz`. A version bump makes the new filename not exist →
automatic re-embed. No sidecar needed. Downside: filename proliferation,
GC complexity, breaks E04_S01's hardcoded path reference.

**Recommendation: option (b), sidecar `embeddings_manifest.json`.**

Rationale:
- The NPZ chunk_id arrays use `dtype=object` → `allow_pickle=True` is required
  to read them. A JSON sidecar sidesteps the pickle surface entirely.
- The sidecar records `chunker_version` AND `embedder_version` as first-class
  fields, enabling both skip dimensions without a second data structure.
- The sidecar mirrors `chunk_manifest.json` naming discipline (both are
  `*_manifest.json` files written atomically alongside their companion data).
- Skip pre-flight is a single `json.loads(sidecar.read_text())` — O(1) JSON
  parse, no NPZ open at all for papers that are fully up-to-date.
- Writing the sidecar atomically in the same tmp + `os.replace` pattern as the
  NPZ means both files are consistent: if the NPZ write succeeded, the sidecar
  describes it exactly.
- Option (a) requires opening the NPZ (with pickle) for every paper. Option
  (c) leaks version state into filenames, complicating E04_S01's path lookup.

The sidecar schema should be written with `sort_keys=True` (BP1 discipline).
The set of `embedded_chunks` in the sidecar must exactly match what's in the
NPZ — written from the same in-memory lists, not reconstructed separately.

### EXPECTED_CHUNKER_VERSION constant placement

The brief says define `EXPECTED_CHUNKER_VERSION = "v1.0"` in `embedder.py`.
However, `CHUNKER_VERSION = "v1.0"` already exists as the single source of
truth in `ingest/chunker_types.py`. Defining a second constant with the same
value in `embedder.py` violates the "single source of truth" principle and
will diverge on the next chunker version bump. Recommendation: import
`CHUNKER_VERSION` from `ingest.chunker_types` and alias it:
```python
from ingest.chunker_types import CHUNKER_VERSION as EXPECTED_CHUNKER_VERSION
```
This satisfies the brief's requirement that `EXPECTED_CHUNKER_VERSION` be
defined "in exactly one place" while preserving the actual single source of
truth in `chunker_types.py`.

### MVCC race condition documentation

The brief acceptance criterion states: "No race condition: if two embedder
processes run concurrently on the same corpus, neither corrupts the other's
rows (LanceDB's MVCC writer serializes writes; document this in the module
docstring)." Since there is no LanceDB yet, the concurrency guarantee must be
restated in terms of NPZ writes: `os.replace` is atomic at the POSIX level on
the same filesystem — a concurrent writer that wins the race simply overwrites
with its own complete NPZ + sidecar pair. The loser's `os.replace` call is
also atomic, so no reader ever sees a partial file. Both writers produce
identical output given the same input (BP1 byte-stability), so the "last
writer wins" outcome is semantically idempotent. Document this in the module
docstring, not in terms of LanceDB MVCC (which doesn't exist yet).

---

## External writes the implementation will require

| Path | Event | Notes |
|---|---|---|
| `ingest/embedder.py` | source edit | add skip logic to `_embed_paper_impl`, add `EXPECTED_CHUNKER_VERSION`, add `_write_embeddings_manifest`, update module docstring for POSIX-atomic concurrency |
| `var/arxmcp/corpus/embeddings/<paper_id>/embeddings_manifest.json` | per paper (first embed + any re-embed) | sidecar written atomically via tmp + `os.replace` |
| `var/arxmcp/ops/embed-stats.jsonl` | per `embed_corpus` call | existing; `run_summary` line gains `chunks_skipped` aggregate |
| `tests/test_embedder_idempotent.py` | new test file | run embed twice, assert second run writes 0 rows; version-mismatch fixture; new-chunk fixture |

No push, PR, infra mutation, or third-party API call is required by this
milestone. The HuggingFace model cache is already populated from E03_S01;
no new network access is needed.
