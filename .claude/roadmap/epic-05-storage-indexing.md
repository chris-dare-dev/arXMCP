# E05 — Storage & Indexing (Tier 1d)

**Epic dependencies:** E04.

**Goal:** replace the v0 single-table LanceDB write from E01 with the full schema from `05-storage-and-indexing.md`. Five tables (`chunks`, `equations`, `definitions`, `theorem_names`, `papers`), dual-representation embeddings (`embedding_prose` and `embedding_latex`), HNSW + Tantivy BM25 indices with a LaTeX-aware analyzer, MVCC versioning with atomic symlink swap.

**Effort:** 1–2 weeks.

**References:** `05-storage-and-indexing.md` (entire file is authoritative); `02-architecture-overview.md` § Versioning; `04-parsing-and-chunking.md` § What gets stored per chunk.

---

### E05_S01 — Define the `chunks` LanceDB schema with dual embeddings

**Description.** Implement the full `chunks` table schema from `05-storage-and-indexing.md` § Table: chunks. Columns include `chunk_id`, `paper_id`, `version`, `level`, `kind`, `section_path`, `label`, `preamble`, `body_canonical`, `body_raw_latex`, `mathml`, `referenced_chunks`, `equation_atoms`, char offsets, `embedding_text`, `embedding_prose`, `embedding_latex`, `chunker_version`, `embed_model`, `created_at`. ColBERT column reserved but nullable for now.

**Acceptance criteria.**
- [ ] `ingest/store/schemas.py::CHUNKS_SCHEMA` returns a PyArrow schema matching the note exactly.
- [ ] Embedding dimension (`D`) is a single config constant; both prose and latex columns use it.
- [ ] `embedding_colbert` exists as `nullable fixed_size_list<float32, ?>` and is left null in v1 (filled in E15 if/when ColBERT lands).
- [ ] `chunker_version` and `embed_model` are NOT NULL string columns.
- [ ] Test: a sample row round-trips through write/read with all fields preserved.

**Dependencies.** none within E05.

**Complexity.** M.

**Labels.** `area:storage`, `kind:feature`.

---

### E05_S02 — `equations`, `definitions`, `theorem_names`, `papers` table schemas

**Description.** Implement the remaining four tables from `05-storage-and-indexing.md`. `equations` for the equation atoms emitted by E04_S03; `definitions` for the per-paper notation table from E03_S06; `theorem_names` for Mathlib-style exact-match lookup (filled by E10); `papers` for paper-level metadata.

**Acceptance criteria.**
- [ ] `ingest/store/schemas.py` exposes `EQUATIONS_SCHEMA`, `DEFINITIONS_SCHEMA`, `THEOREM_NAMES_SCHEMA`, `PAPERS_SCHEMA` matching the note.
- [ ] All five schemas live in one module, all share the same `D` (embedding dimension) constant.
- [ ] `papers.parse_status` enum: `{ok, degraded, failed}` per `05-storage-and-indexing.md`.
- [ ] `papers.parser_used` enum: `{ar5iv, latexml_local, nougat}`.
- [ ] Test: writing and reading one row per table preserves all fields; enum columns reject invalid values.

**Dependencies.** E05_S01.

**Complexity.** M.

**Labels.** `area:storage`, `kind:feature`.

---

### E05_S03 — Build HNSW indexes on prose and LaTeX embeddings

**Description.** Per `05-storage-and-indexing.md` § Indexes, build HNSW (M=16, efConstruction=200) on both `embedding_prose` and `embedding_latex` in the `chunks` table, plus `embedding_eq` in the `equations` table and `abstract_embedding` in `papers`.

**Acceptance criteria.**
- [ ] `ingest/store/build_indexes.py::build_hnsw(table, columns)` creates HNSW indexes with the documented parameters.
- [ ] Index build is idempotent (re-running with the same data is a no-op or fast skip).
- [ ] Index build time on the 50-paper seed is <60 s.
- [ ] `dataset.list_indices()` confirms three HNSW indexes on `chunks` (prose, latex), one on `equations`, one on `papers.abstract_embedding`.
- [ ] Index build emits `arxmcp_index_build_seconds` metric scaffold.

**Dependencies.** E05_S01, E05_S02.

**Complexity.** M.

**Labels.** `area:storage`, `area:retrieval`.

---

### E05_S04 — Tantivy BM25 with separate analyzers for raw LaTeX vs canonical prose

**Description.** Per `05-storage-and-indexing.md` § Indexes — BM25/Tantivy on `body_canonical` (English analyzer) AND `body_raw_latex` (LaTeX analyzer that preserves backslash tokens like `\Spec`, `\mathrm{Pic}`). Two separate FTS indexes; queries fan out across both.

**Acceptance criteria.**
- [ ] LaTeX analyzer preserves `\Spec`, `\mathrm{Pic}`, `\mathcal{F}` etc. as single tokens (validated by a tokenizer test).
- [ ] English analyzer applies standard stemming on `body_canonical`.
- [ ] Both indexes registered against the `chunks` table.
- [ ] BM25 queries against `body_raw_latex` for `\Spec` return non-empty results from the seed corpus.
- [ ] BM25 queries against `body_canonical` for "spectrum" return semantically related results.
- [ ] Documented analyzer config in `docs/storage/analyzers.md`.

**Dependencies.** E05_S01.

**Complexity.** L.

**Labels.** `area:storage`, `area:retrieval`, `risk:high`.

---

### E05_S05 — B-tree scalar indexes on filter columns

**Description.** Per `05-storage-and-indexing.md` § Indexes, B-tree scalar indexes on `paper_id`, `version`, `level`, `kind` in `chunks`; on `paper_id` in `equations`; on `(paper_id, symbol)` and `symbol_raw` in `definitions`. Required for the filter clauses in `search_papers` to be performant.

**Acceptance criteria.**
- [ ] All scalar indexes listed in the note are created.
- [ ] Filter query `paper_id = $X AND level = "theorem"` uses index scan, not full scan (verified via LanceDB query plan).
- [ ] Index build is part of the same `build_indexes` invocation as HNSW.
- [ ] Test: querying with a missing index path on a 100K-row table is markedly slower than with an index (smoke test, not a hard threshold).

**Dependencies.** E05_S01, E05_S02.

**Complexity.** S.

**Labels.** `area:storage`, `area:retrieval`.

---

### E05_S06 — Dual-embedding emitter for the chunker output

**Description.** Per `05-storage-and-indexing.md` § Dual-representation indexing — each chunk gets two embeddings: prose-only (math stripped to `[MATH]` or unicode-math) and raw-LaTeX-with-expanded-macros. Both come from the same self-hosted embedder (bge-m3); only the input differs.

**Acceptance criteria.**
- [ ] `ingest/embed/dual.py::embed_pair(chunk) -> (prose_vec, latex_vec)`.
- [ ] Prose representation: macros expanded; display equations replaced with `[MATH:<presentation_latex>]` token.
- [ ] LaTeX representation: macros expanded; equations preserved verbatim.
- [ ] Both embeddings share the same embedder model and the same dimension.
- [ ] Test: the prose representation of a chunk contains no raw `\mathcal`, `\mathbb`, etc. tokens.
- [ ] Test: the LaTeX representation preserves backslash tokens.
- [ ] Embedding model commit SHA is part of the `embed_model` field per `08-security-observability-ops.md` Threat 6.

**Dependencies.** E05_S01.

**Complexity.** M.

**Labels.** `area:embedder`, `area:storage`, `kind:feature`.

---

### E05_S07 — MVCC versioned write path and `current` symlink

**Description.** Per `02-architecture-overview.md` § Versioning and `05-storage-and-indexing.md` § Versioning and atomic swaps — ingestion writes to a new versioned directory `index/lancedb/v0008/`, then atomically swaps the `current` symlink. The MCP server resolves `current` once at session start and pins the resolved version.

**Acceptance criteria.**
- [ ] `ingest/store/version_swap.py::publish(new_version_dir)` writes the new directory, then `os.symlink + os.rename` to swap `current`.
- [ ] Old version directories are not touched.
- [ ] Test: while a reader has `dataset.checkout(v0007)`, writer publishes v0008; reader continues to see v0007 data.
- [ ] Documented retention policy: keep N=7 prior versions; older are GC'd.
- [ ] GC script `tools/gc_old_versions.py` deletes directories older than the 7th-latest.
- [ ] GC is gated behind a confirmation flag and logs every deletion.

**Dependencies.** E05_S01, E05_S02, E05_S03, E05_S04.

**Complexity.** L.

**Labels.** `area:storage`, `kind:infra`, `risk:high`.

---

### E05_S08 — Chunk embedding cache (build-time, persistent)

**Description.** Per `07-multi-agent-caching.md` § Chunk embedding cache — keyed by `sha256(content_sha256 + embed_model_id)`, stored in SQLite under `var/arxmcp/cache/embeddings/`. Built at ingestion time, persistent forever (manually GC'd when a model retires). Saves re-embedding cost on chunker version bumps that leave content unchanged.

**Acceptance criteria.**
- [ ] `ingest/embed/cache.py::EmbedCache` SQLite-backed; key column is `(content_sha256, embed_model_id)`.
- [ ] Cache hit returns the stored vector; miss invokes the embedder and stores the result.
- [ ] Test: re-embedding the same chunk content with the same model is a cache hit and skips the embedder call.
- [ ] Test: same content + different model = miss.
- [ ] `arxmcp_embed_cache_hits_total` counter exposed.
- [ ] Documented in `docs/storage/embedding-cache.md` per the rule "key by content hash, not chunk_id."

**Dependencies.** E05_S06.

**Complexity.** M.

**Labels.** `area:embedder`, `area:cache`, `kind:feature`.

---

### E05_S09 — `papers` table population from parser metadata

**Description.** When a paper is parsed and chunked, populate one row in the `papers` table with title, authors, abstract, categories, dates, withdrawal status, license, parse_status, parser_used, and chunk/equation/definition counts.

**Acceptance criteria.**
- [ ] `ingest/store/papers_writer.py::upsert_paper(paper_id, parsed, normalized, chunks, equations)`.
- [ ] All fields from `05-storage-and-indexing.md` § Table: papers populated correctly.
- [ ] `abstract_embedding` computed from the abstract via the same embedder as chunks (single-vector, not dual).
- [ ] Test: a paper with parser_used=ar5iv and 30 chunks ends up in `papers` with `n_chunks=30`, `parser_used="ar5iv"`.
- [ ] On re-ingestion, the row is upserted (overwrite), not duplicated.

**Dependencies.** E05_S02, E05_S06.

**Complexity.** S.

**Labels.** `area:storage`.

---

### E05_S10 — Drive seed corpus through the new schema

**Description.** Re-ingest the 50-paper seed corpus into the new schema with all five tables populated, dual embeddings built, all indexes built. End state is the v1 storage layer fully exercised on the seed.

**Acceptance criteria.**
- [ ] `chunks` table has all seed chunks with both `embedding_prose` and `embedding_latex` populated.
- [ ] `equations` table populated.
- [ ] `definitions` table populated from E03_S06 outputs.
- [ ] `papers` table has 50 rows with parse_status=ok for ≥45 of them.
- [ ] `theorem_names` is left empty (filled by E10).
- [ ] All indexes built and queryable via `dataset.search(...)`.
- [ ] Stats summary written to `var/arxmcp/ops/seed-storage-stats.json`.

**Dependencies.** E05_S03, E05_S04, E05_S05, E05_S06, E05_S07, E05_S09, E03_S06.

**Complexity.** M.

**Labels.** `area:storage`, `kind:research`.

---

### E05_S11 — Disk budget sanity check

**Description.** Per `05-storage-and-indexing.md` § Disk and memory budget at v1 scale, the seed corpus's storage size is a leading indicator. Project from 50 papers to 200K papers and confirm we're within the ~100 GB budget.

**Acceptance criteria.**
- [ ] Measure on-disk size of `var/arxmcp/index/lancedb/current/` after E05_S10.
- [ ] Project: `(seed_size / 50) * 200_000` and confirm ≤120 GB (allowing 20% headroom on the budget).
- [ ] If projection exceeds budget, file a follow-up issue investigating the dominant column (likely `body_raw_latex` or `mathml`).
- [ ] Document the projection in `docs/storage/disk-budget.md`.
- [ ] Plot per-table size in the report.

**Dependencies.** E05_S10.

**Complexity.** S.

**Labels.** `area:storage`, `kind:research`.

---
