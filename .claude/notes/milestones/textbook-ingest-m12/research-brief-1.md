# Research Brief — textbook-ingest-m12

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-28T20:00:00Z

## In-codebase context

### Design notes that apply

- `03-ingestion-pipeline.md` — arXiv pipeline: fetch → parse → chunk → embed → store. The textbook path mirrors each step notebook-scoped.
- `05-storage-and-indexing.md` — LanceDB `chunks` table, MVCC corpus-version marker, dual-column embedding routing.
- `07-multi-agent-caching.md` — tool schema and BP1 byte-stability. **This milestone is ingest-only (no `server/` changes) → NO tool-schema re-pin, NO BP1 re-pin expected.**

### Load-bearing signatures

**`ingest/textbook_chunker.py` — `chunk_textbook`:**

```
def chunk_textbook(slug: str, paper_id: str) -> list[ChunkRecord]
```

Docstring line 43: "Writes chunk JSONs only — NOT LanceDB. Embedding/LanceDB-write is a downstream step..."

Output path: `var/arxmcp/notebooks/<slug>/chunks/<flat_paper_id>/<hash16>.json`
Manifest: `var/arxmcp/notebooks/<slug>/chunks/<flat_paper_id>/chunk_manifest.json`

Fields set: `source_kind="textbook"`, `textbook_slug=slug`, `parser_used="mineru+latexml"`, `chunker_version="tv0.1"`, `chapter=<str|None>`, `page_start=None`, `page_end=None`, `license=<token>`.
Chunk IDs: `textbook:<slug>:<sha256[:16]>` (from `_compute_textbook_chunk_id`, line 142).

**`ingest/embedder.py` — key insight:**

`embed_paper(paper_id: str, ...)` at line 889 reads from `CHUNKS_DIR = REPO_ROOT / "var" / "arxmcp" / "corpus" / "chunks"` hardcoded in `_load_chunks` (line 749) and `_read_manifest_chunk_ids` (line 826). There is NO public lower-level function that accepts a `list[ChunkRecord]` or a custom chunks directory. The lower-level primitives are:

- `_build_embed_input(preamble_text, body_text) -> str` (line 371) — NFC normalize + concat
- `_encode_batch(texts: list[str], ...) -> tuple[np.ndarray, int]` (line 396) — calls `_get_model()` + `_get_tokenizer()`
- Routing rule (line 1028): `"embedding_proof" if kind == "proof" else "embedding_stmt"`

There is NO `embed_chunk_records(chunks: list[ChunkRecord]) -> EmbedRecord` function. The driver must implement this inline using the above private primitives.

**`ingest/schema.py` — `EmbedRecord`:**

```python
@dataclass
class EmbedRecord:
    chunk_ids_stmt: list[str]
    embedding_stmt: np.ndarray   # shape (N_stmt, 1024), float32, L2-normed
    chunk_ids_proof: list[str]
    embedding_proof: np.ndarray  # shape (N_proof, 1024), float32, L2-normed
    embedder_version: str        # "bge-m3@<8-hex>"
```

`__post_init__` validates L2 norms (atol=1e-3), no duplicates within lists, no cross-list overlap, correct dtype.

**`ingest/store.py` — `write_chunks`:**

```python
def write_chunks(
    chunks: list[ChunkRecord],
    embeddings: EmbedRecord,
    lancedb_path: str | Path | None = None,
) -> int
```

The `lancedb_path` parameter routes writes to the per-notebook LanceDB directory. Returns the post-index LanceDB version integer.

**CRITICAL: `write_chunks` at line 904 passes `chunker_version=CHUNKER_VERSION` (the arXiv constant "v1.1") to `write_corpus_version_marker` regardless of the actual chunk content.** For a textbook-only LanceDB, this writes a misleading marker. The driver should call `write_corpus_version_marker` explicitly with `TEXTBOOK_CHUNKER_VERSION` after `write_chunks`.

**`ingest/store.py` — m9 write-time invariant (line 459-479):**

`_build_arrow_table` enforces: `chunk.chunk_id.startswith(f"{chunk.source_kind}:")`. For `source_kind="textbook"`, the prefix must be `"textbook:"`. `chunk_textbook` already emits this — do NOT alter the returned `ChunkRecord`s.

**`tools/notebook_ingest.py` — the arXiv template (212 LOC):**

Pattern: `validate_slug` → `notebook_dir` → `papers_txt` → `run_bulk_ingest(lancedb_staging_path=nb_dir/"lancedb")` → `_read_corpus_version(lancedb_path)` → `build_bm25_index(lancedb_path, corpus_version=corpus_version)`.

BM25 note: `notebook_ingest.py` builds BM25 after arXiv ingest. However, `search_papers` is **dense-only at v1** (notebook-retrieval-m2 AC2 confirmed). BM25 is required for the hybrid pipeline but the hybrid pipeline is locked off for notebooks. **The driver SHOULD skip BM25** for the initial e4-closing demo — same as `tests/test_store.py` model-free pattern.

**`tools/_notebook_common.py` — path helpers:**

- `notebook_dir(slug) -> Path` — validate_slug + symlink rejection + containment check (Threat 1).
- `notebook_lancedb_path(slug) -> Path` — returns `notebook_dir(slug) / "lancedb"`.

**`tests/test_store.py` — `_make_synthetic_embeddings` (line 69-110):**

```python
def _make_synthetic_embeddings(chunks: list[ChunkRecord], *, seed: int = 0) -> EmbedRecord:
    """Build an EmbedRecord with random L2-normalized vectors for chunks.
    Routes by kind == "proof" like the production embedder."""
```

This pattern is the template for model-free testing. The integration test for m12 must use the same approach: build synthetic EmbedRecord, call `write_chunks(..., lancedb_path=tmp_nb_lancedb)`, then query `search_papers`.

### Conflict flags

**CONFLICT — `write_chunks` hardcodes arXiv `CHUNKER_VERSION` in corpus-version marker:** `ingest/store.py:904` passes `chunker_version=CHUNKER_VERSION` ("v1.1") to `write_corpus_version_marker`. When writing textbook chunks to a notebook LanceDB, this marker will claim `chunker_version="v1.1"` even though the actual chunks carry `chunker_version="tv0.1"`. **The marker is read by `_read_corpus_version` in `notebook_ingest.py` (for BM25 version gating) and by the server at startup.** This is an observability inaccuracy, not a functional failure. The driver can tolerate it by calling `write_chunks` (which does the LanceDB upsert + corpus-version.json write) and not adding a second marker write. FLAG: the implementer should note this in a code comment but not try to fix `write_chunks` itself in this milestone — that would be a store.py change requiring additional test scope.

## Prior decisions and lessons

**Recent git log:**
- `58c6989` notebook-cutover-m1 (complete) — per-notebook staging→active cutover
- `c16aac7` textbook-ingest-m11 (complete) — non-OA license truncation in `get_chunk`
- `a7da3f0` textbook-ingest-m10 (complete) — PDF sandbox doc + upload tests
- `12c8664` textbook-ingest-m9 (complete) — `search_papers` `source_kind` filter

**From MEMORY.md (injected context):**

- `textbook-ingest-m9 — no-textbook-embed-write-path-exists`: "`chunk_textbook` writes chunk JSONs to `var/arxmcp/notebooks/<slug>/chunks/` ONLY. No driver calls `chunk_textbook` externally; no embed→write-notebook-LanceDB path exists for textbook chunks. `bulk_ingest.py` handles arXiv only. Tests must seed synthetic notebook LanceDB directly via `write_chunks(chunks, embed_record, lancedb_path=tmp_path)`." This exactly describes the pre-m12 state and confirms the driver is ABSENT — we are building it from scratch.

**From m7 implementation-summary:** TEXTBOOK_CHUNKER_VERSION = "tv0.1" is separate from CHUNKER_VERSION ("v1.1"). Any test that checks `chunker_version` in the corpus-version.json will see "v1.1" (arXiv constant from store.py:904) not "tv0.1".

**From notebook-retrieval-m2:** Per-notebook LanceDB served via `ARXMCP_NOTEBOOK=<slug>` or `filters.notebook=<slug>`. The m2 integration test uses a `Resources.startup` hermetic fixture without real BGE-M3. The m12 integration test should use the same pattern: monkeypatch `write_chunks` against a `tmp_path` LanceDB + `filters.notebook` routing.

**Dense-only confirmed:** notebook-retrieval-m2 AC2 locks retrieval to "dense-only over `embedding_stmt`, proof chunks excluded, `retrieval_mode='dense_only'"`. BM25 is net-negative for notebook retrieval. The driver must NOT build BM25 for the e4-closing demo.

## External sources

This milestone is internal glue. No vendor docs required.

**BGE-M3 dual-column embedding contract (from `ingest/embedder.py` source, confirmed):**
- `kind == "proof"` → `embedding_proof` column; all other kinds → `embedding_stmt` column.
- Vectors are 1024-dim float32, L2-normalized.
- `EMBEDDER_VERSION = f"bge-m3@{BGE_M3_COMMIT_SHA[:8]}"` where `BGE_M3_COMMIT_SHA = "5617a9f61b028005a4858fdac845db406aefb181"`.

This contract is directly mirrored in `_make_synthetic_embeddings` in `tests/test_store.py` — the test helper is the authoritative reference for model-free encoding.

No MCP spec or prompt-caching docs are relevant — this is an ingest-only CLI tool.

## Recommendation

**Choose fork (b): embed `ChunkRecord`s returned by `chunk_textbook` directly, without the global-store NPZ round-trip.**

Reasoning: `embed_paper` hardcodes `CHUNKS_DIR` and `EMBEDDINGS_DIR` (arXiv global corpus paths). Teaching it a notebook-scoped chunk-source would require refactoring both `_load_chunks` and `_paper_is_up_to_date` to accept a custom base path, plus threading an NPZ output path through `_write_embeddings_npz`. That is a larger, riskier change to a core module. The direct approach instead calls the same lower-level primitives `embed_paper` uses (`_build_embed_input`, `_encode_batch`) from within a new `_embed_chunk_records` helper in `tools/notebook_textbook_ingest.py`, then constructs an `EmbedRecord` in-memory and passes it directly to `write_chunks`. This:

- Reuses BGE-M3 encoding logic without duplicating it
- Skips the NPZ round-trip (not needed for a notebook-scoped, single-use write)
- Is testable model-free by injecting a synthetic `EmbedRecord` (same pattern as `_make_synthetic_embeddings`)
- Does not touch `ingest/embedder.py` or `ingest/store.py`

**Recommended `tools/notebook_textbook_ingest.py` shape:**

```
CLI: uv run python tools/notebook_textbook_ingest.py <slug> [--paper-id PAPER_ID ...]
```

- `slug` required positional arg (validate via `validate_slug`)
- optional `--paper-id` repeatable arg; if omitted, discover all paper_ids from `var/arxmcp/notebooks/<slug>/chunks/` subdirs (scan for `chunk_manifest.json`)
- optional `--batch-size` (default 8, matches `EMBED_BATCH_DEFAULT`)
- `--dry-run` (list chunks but skip encode/write) useful for debugging

**The chunk → embed → write flow:**

```python
def _embed_chunk_records(chunks: list[ChunkRecord], batch_size: int) -> EmbedRecord:
    """Encode chunks using BGE-M3 dual-column routing. Requires model."""
    from ingest.embedder import _build_embed_input, _encode_batch, EMBEDDER_VERSION
    # Build embed inputs (preamble_text="" for textbook, per m8 OQ-1 decision)
    # Route by kind: proof -> proof col, else stmt col
    # Return EmbedRecord with aligned arrays
```

For model-free testing, `_embed_chunk_records` is replaced by `_make_synthetic_embeddings`-style injection.

**Notebook LanceDB path:** `tools._notebook_common.notebook_lancedb_path(slug)` → `var/arxmcp/notebooks/<slug>/lancedb`

**Per-paper loop:**
1. `nb_dir = notebook_dir(slug)` (validates slug + symlink)
2. For each `paper_id`: `chunks = chunk_textbook(slug, paper_id)` (calls chunker, writes JSONs, returns ChunkRecords)
3. `embed_record = _embed_chunk_records(chunks, batch_size)` (model-required; `@pytest.mark.requires_model` gate)
4. `version = write_chunks(chunks, embed_record, lancedb_path=nb_lancedb_path)` (MVCC upsert + corpus-version.json)
5. Print summary: `chunks written, lancedb_version`

**Do NOT call `build_bm25_index`** — search is dense-only at v1 for notebooks. Add a comment explaining this with a cite to notebook-retrieval-m2 AC2.

**corpus_version:** `write_chunks` writes `corpus-version.json` with the post-index LanceDB version integer. The per-notebook serving path reads this via `_read_corpus_version` at startup. This is handled by the existing `write_chunks` postcondition — no additional marker write needed. (The `chunker_version` field in the marker will show the arXiv constant "v1.1" due to the `store.py:904` hardcode — acceptable in this milestone; note it in a comment.)

**Idempotency:** `write_chunks` uses `merge_insert("chunk_id")` — re-running the driver is safe (same chunk_ids produce no-op upserts).

**Integration test structure (model-free, the e4-demo guard):**
1. Build synthetic `ChunkRecord`s (source_kind="textbook", textbook: chunk_ids, license="author-distributed")
2. Build `EmbedRecord` via `_make_synthetic_embeddings`-style helper
3. Call `write_chunks(chunks, embed_record, lancedb_path=tmp_nb_lancedb)`
4. Write `corpus-version.json` to `tmp_nb_lancedb`
5. Spin up `Resources.startup(arxmcp_notebook=slug)` or use `filters.notebook=slug`
6. Call `search_papers(query="...", filters={"source_kind": "textbook"})` against the test client
7. Assert at least one result with `source_kind="textbook"` and a `textbook:` chunk_id

**Real-model path:** the `_embed_chunk_records` call is `@pytest.mark.requires_model`-gated. The write+retrieve integration test runs model-free via synthetic embeddings.

## Open questions

No open questions — implementation can proceed on the above recommendation.

The one acknowledged inaccuracy (the `chunker_version="v1.1"` in the corpus-version marker for a textbook-only LanceDB) is documented as a known limitation and does not block the e4 demo. It can be addressed in a future store.py refactor if needed.

## External writes the implementation will require

| type | target | why |
|---|---|---|
| git push | `origin main` | ship the feat commit + rect commit + chore commit triple |
| gh issue close | `chris-dare-dev/arXMCP#8` | milestone closes the tracked follow-up from m9 completion |

Both are Phase-4 main-thread operations, gated on per-event user authorization. The driver itself is purely local.
