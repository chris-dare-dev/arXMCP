# E03_S02 Research Brief 1 — Idempotent Re-embed

**Written:** 2026-05-07 | **Researcher:** Sonnet-A

---

## 1. In-codebase context

### What E03_S01 landed

`ingest/embedder.py` (commit 8ee41be + rect 490c850) currently **always re-encodes every chunk it finds** for a paper. There is no skip logic. From the module docstring:

> **Why NPZ-first, not direct LanceDB.** The roadmap lists E03_S01 ↔ E04_S01 as a mutual dependency, so neither can literally block on the other. The NPZ store breaks the deadlock: E03_S01 ships independent of E04_S01, and E04_S01's `ingest/store.py` reads the NPZ alongside the chunk manifests when building the LanceDB rows.

The NPZ store is at `var/arxmcp/corpus/embeddings/<paper_id>/embeddings.npz`. The embedder exposes:

- `embed_paper(paper_id, batch_size)` — per-paper entry point
- `embed_corpus(lancedb_path=None, corpus_path=None, batch_size=32)` — corpus-wide scan

The `embed_corpus` loop (`_embed_paper_impl`) currently has no pre-flight skip check at all; it always calls `_load_chunks(paper_id)` and proceeds straight to `_encode_batch`.

### Chunker version signal

`CHUNKER_VERSION = "v1.0"` is defined **in `ingest/chunker_types.py`** (not `chunker.py`, to avoid a circular import). From `chunker_types.py`:

> "The value flows into every ChunkRecord's `chunker_version` field via the dataclass default below, into the per-paper `chunk_manifest.json` (written by `ingest.chunker`), and is what E04_S02's MVCC writer uses to detect stale rows."

Each per-chunk JSON on disk already carries `"chunker_version": "v1.0"`. The per-paper `chunk_manifest.json` also carries a top-level `"chunker_version"` field (as shown in `tests/test_embedder.py:_stage_chunk_dir`).

### The brief's pre-flight LanceDB query — adaptation required

The milestone brief says:

> "The skip logic is implemented as a pre-flight query over the LanceDB table: `SELECT chunk_id, chunker_version FROM chunks WHERE embedding_stmt IS NOT NULL OR embedding_proof IS NOT NULL`."

**This is structurally impossible at E03_S02.** LanceDB (E04_S01) has not been built. The NPZ store is the only embedding artifact. The brief's LanceDB language must be adapted to the NPZ-first world, exactly as D1 of `research-synthesis.md` adapted E03_S01. The brief's _intent_ (skip already-embedded chunks if version matches) is sound; the _mechanism_ needs to change.

### NPZ schema (E03_S01 output)

The NPZ at `var/arxmcp/corpus/embeddings/<paper_id>/embeddings.npz` contains:
- `chunk_ids_proof`: 1-D string array
- `chunk_ids_stmt`: 1-D string array
- `embedding_proof`: float32 array, shape `(N_proof, 1024)`
- `embedding_stmt`: float32 array, shape `(N_stmt, 1024)`

There is **no `chunker_version` field** in the NPZ. The NPZ carries which chunk_ids were embedded, but not what chunker version they came from.

### `EmbedStats.chunks_skipped` already exists

From `embedder.py:EmbedStats`:

```python
chunks_skipped: int
```

The field is present in the dataclass but is always `0` in the current implementation. E03_S02 will populate it.

### Design notes that apply

- **`05-storage-and-indexing.md` § "Chunk embedding cache":** "Key by content hash, not chunk_id. Chunk IDs are content-addressable in our system, so they're equivalent — but explicitly tying the cache to content hash + model version makes invalidation safe across schema migrations."
- **`07-multi-agent-caching.md` § BP1:** "JSON keys serialized in alphabetical order." — any new sidecar file must follow this.
- **`08-security-observability-ops.md` Threat 6:** The model SHA is already pinned. The skip logic must not create a path where chunks embedded with a different `embedder_version` (BGE-M3 SHA) are silently reused. **Recommendation:** `EXPECTED_CHUNKER_VERSION` guards the chunk content version; the `embedder_version` baked into `EmbedStats` guards the model. If the embedder SHA changes, E04_S02 handles MVCC rotation — E03_S02 only handles the chunker-version handshake.

### Roadmap constraint (E03-embedder.md)

The roadmap `E03_S02` explicit out-of-scope:

> "MVCC version management (E04_S02). BM25 index re-build on version bump (E04_S04). GPU acceleration (E11)."

The note under E11 (risk):

> "The idempotency guarantee is load-bearing for E11's scale-out: at 200K papers, re-embedding from scratch on every ingestion run would be prohibitively slow."

---

## 2. Prior decisions and lessons

### E03_S01 critique findings directly relevant here

**F2 (fixed):** The run-summary `event="run_summary"` JSONL line now fires after `embed_corpus`. E03_S02 must preserve this and extend the summary with `chunks_skipped` aggregate for the skip-all-up-to-date case to be observable.

**F1 (fixed):** Every paper attempt writes to `embed-stats.jsonl` regardless of outcome. E03_S02's skip path must also write a stats row (with `chunks_skipped == N`, `chunks_processed == 0`) so the audit trail stays complete.

**F5 (fixed):** NPZ kwargs are now alphabetical (`chunk_ids_proof, chunk_ids_stmt, embedding_proof, embedding_stmt`). Any new sidecar JSON must also use `sort_keys=True` at write time.

**F9 (fixed, documented):** Zero-row NPZ arrays use `(0, EMBEDDING_DIM)` shape — consumers MUST check `len(chunk_ids_*) > 0`, not key presence. E03_S02's skip logic must not misread a zero-row `embedding_proof` as "proof chunks were embedded."

### Naming precedent

`CHUNKER_VERSION` lives in `chunker_types.py` (not `chunker.py`) to avoid circular import. The brief's `EXPECTED_CHUNKER_VERSION` constant must live in `ingest/embedder.py` — it is an embedder-layer contract, not a chunker-layer constant. The embedder imports `CHUNKER_VERSION` from `chunker_types` to validate against; the `EXPECTED_CHUNKER_VERSION` constant in `embedder.py` should equal the current `CHUNKER_VERSION` value and be documented as the embedder's pinned input expectation.

**FLAG — potential single-source-of-truth violation:** The brief defines `EXPECTED_CHUNKER_VERSION = "v1.0"` as a new constant in `embedder.py`. If `CHUNKER_VERSION` in `chunker_types.py` is bumped to `"v1.1"` and `EXPECTED_CHUNKER_VERSION` in `embedder.py` is not updated, the skip logic silently re-embeds everything (correct behavior — but the code has two places to change). Better: define `EXPECTED_CHUNKER_VERSION = CHUNKER_VERSION` imported from `chunker_types`, not a string literal. This makes a version bump automatically trigger re-embed without a separate `embedder.py` edit. The brief's wording ("defined as a constant in exactly one place") is satisfied by this approach: the literal `"v1.0"` still lives only in `chunker_types.py`, and `embedder.py` references it by name.

### Concurrency note (brief acceptance criterion)

Brief: "if two embedder processes run concurrently on the same corpus, neither corrupts the other's rows (LanceDB's MVCC writer serializes writes; document this in the module docstring)."

**FLAG — inapplicable mechanism cited.** LanceDB is not in scope. The actual concurrency safety comes from `os.replace` atomicity in `_write_embeddings_npz`. Two concurrent processes writing to the same NPZ will produce a last-writer-wins outcome (atomic, no partial write visible). The module docstring should document this NPZ-level atomicity instead. A pre-flight read of the NPZ + skip decision + conditional write is **not** transactional: if P1 reads "NPZ exists, skip" and P2 reads "NPZ exists, re-embed and overwrite" for different paper subsets, the interleaving is safe because each paper's NPZ is independent. The concurrent-write risk only exists if two processes embed the SAME paper concurrently (last `os.replace` wins — both produce correct NPZ, not corruption).

---

## 3. External sources

### LanceDB MVCC (05-storage-and-indexing.md)

The design note documents LanceDB's MVCC as the future home of the concurrency contract (E04_S02). At E03_S02, the NPZ-first layer is the actual runtime artifact. The `os.replace` atomic rename is POSIX-guaranteed (see Python docs `os.replace`): "Rename the file or directory src to dst. If dst is a non-empty directory, OSError will be raised. If dst exists and is a file, it will be replaced silently if the user has permission."

### NumPy NPZ format

`np.load` with `allow_pickle=False` (or default) loads NPZ lazily; accessing `npz.files` lists keys without loading the array data. This makes a pre-flight NPZ key-existence check cheap. The `chunk_ids_stmt` and `chunk_ids_proof` arrays are `dtype=object` (strings), small relative to the float32 embedding arrays.

---

## Open questions

### The central problem: how to implement skip logic without LanceDB

The brief says pre-flight query: `SELECT chunk_id, chunker_version FROM chunks WHERE embedding_stmt IS NOT NULL OR embedding_proof IS NOT NULL`.

In the NPZ-first world, three options:

**(a) Check NPZ existence + manifest-derived chunker_version.**
- Per paper: if `var/arxmcp/corpus/embeddings/<paper_id>/embeddings.npz` exists AND the manifest's top-level `chunker_version` matches `EXPECTED_CHUNKER_VERSION`, read `chunk_ids_stmt` and `chunk_ids_proof` from the NPZ to get the set of already-embedded chunk_ids. Skip those chunk_ids that appear in the set. New chunks (not in NPZ) are embedded; existing chunks with matching version are skipped.
- Problem: the NPZ does not store which `chunker_version` was current when it was written. If the embedder ran with chunker_version `"v1.0"` and the manifest still says `"v1.0"`, we cannot tell whether the NPZ is stale due to a model SHA change.
- However, E03_S02 only gates on `chunker_version` (not `embedder_version`); model SHA changes are an E04_S02 concern.

**(b) Read NPZ files and inspect chunk_ids / embedded version.**
- Same as (a) but also requires a sidecar for the version. The NPZ has no version field.

**(c) Maintain a parallel sidecar metadata file.**
- Write `var/arxmcp/corpus/embeddings/<paper_id>/embed-meta.json` alongside `embeddings.npz` at embed time containing `{"chunker_version": "v1.0", "embedder_version": "bge-m3@5617a9f6", "chunk_ids": [...]}`.
- Pre-flight: read `embed-meta.json`, compare `chunker_version` to `EXPECTED_CHUNKER_VERSION`. If match, load embedded chunk_ids from sidecar without opening the NPZ at all. Fast scalar read.

**Recommendation: option (a), with the manifest as the version oracle.**

Rationale:
1. The `chunk_manifest.json` already carries a top-level `"chunker_version"` field (confirmed in `test_embedder.py:_stage_chunk_dir`). This is the authoritative version for the paper's chunks.
2. The NPZ `chunk_ids_stmt` and `chunk_ids_proof` arrays encode exactly which chunk_ids were embedded. Loading them is cheap (dtype=object, string arrays) because `np.load` lazy-reads and the string arrays are small relative to the float32 blocks.
3. No new file format introduced; no new atomicity contract needed.
4. The per-paper skip decision algorithm: (1) check NPZ exists, (2) check manifest `chunker_version == EXPECTED_CHUNKER_VERSION`, (3) load `chunk_ids_stmt + chunk_ids_proof` from NPZ to get embedded set, (4) for each chunk in manifest, skip if chunk_id in embedded set AND manifest chunker_version matches.
5. New chunks (chunk_id not in NPZ) get embedded; the NPZ is rewritten with the merged result (all already-embedded vectors + newly-embedded vectors). This is atomic via the existing `_write_embeddings_npz` temp-then-rename pattern.

Option (c) (sidecar) is the cleaner long-term design but adds a new file format, new atomicity surface, and couples two writes. It becomes compelling if E04_S01 replaces the NPZ entirely — at that point the sidecar disappears too. Defer to E04_S02.

**The "Skipped N/N chunks — all up to date" log line** should fire from `embed_corpus` run-summary when `chunks_skipped == total_chunks` across all papers, not from per-paper paths. The per-paper `EmbedStats` carries `chunks_skipped`; the run-summary aggregates it.

---

## External writes the implementation will require

| type | target | why |
|---|---|---|
| filesystem write | `ingest/embedder.py` | add `EXPECTED_CHUNKER_VERSION`, skip logic in `embed_corpus` / `_embed_paper_impl` |
| filesystem write | `tests/test_embedder_idempotent.py` (new) | acceptance test: second run writes 0 rows |
| no new file format | — | NPZ + manifest are sufficient; no sidecar introduced |
| no git push | — | local commit only per project convention |
| no PR | — | milestone-pipeline handles PR at epic close |
| no third-party API call | — | no new network dependency |
