# E07_S01 — Phase 1: BM25 over body_tokens — Research Brief 1

## 1. In-codebase context

### Design notes that bind this milestone

The brief cites `.claude/notes/05-retrieval-and-ranking.md` — **that file does not exist**. The relevant design constitution is `.claude/notes/05-storage-and-indexing.md`. The load-bearing rules:

- `05-storage-and-indexing.md:62-68` (BM25 index spec):
  > "BM25 over `body_tokens` using Python `rank_bm25` (BM25Okapi); index stored at `var/arxmcp/index/bm25/v<N>/`. `body_tokens` is a space-joined token stream produced at chunk-write time by a Python regex pre-tokenizer (E02_S03) … **No Tantivy LaTeX analyzer** — Tantivy ships no such analyzer; the approach was fictional."
- `05-storage-and-indexing.md:323-325` (Phase-1 contract):
  > "Phase 1 (cheap, broad): BM25 over `body_tokens` using Python `rank_bm25`. The `body_tokens` field is a pre-tokenized stream (E02_S03)… Take top-200."
- `07-multi-agent-caching.md:132-134, 149-151` (byte-faithful normalization rule):
  > "`canonical_form(query)` is `query.strip()` only — do **not** lowercase, do **not** strip punctuation. `\'etale` and `étale` produce different lexical matches."
  > "Two-key normalization rule (critical): the cache *lookup key* may use aggressive normalization; the *actual query passed to BM25 / embedder* must be unchanged. 'Hodge' and 'hodge' are different lexical tokens."

### `body_tokens` schema and tokenizer output

- `ingest/schema.py:69-117` declares `CHUNKS_SCHEMA_V1`; `body_tokens` is `pa.utf8(), nullable=False` (line 86). Sibling field is `body_text` (line 81) — **the chunks table has no `body_canonical` column**. The brief's risk note ("falls back to the prose `body_canonical` BM25 index") is a typo for `body_text`. There is no separate prose BM25 index in the codebase today; the fallback path the brief gestures at is undefined.
- `ingest/tokenizer.py:1-156` defines `tokenize_body(body_text) -> str`. Format examples (`tokenizer.py:20-22`): `\mathbb{Z}` → `mathbb_Z`; `\mathrm{Spec}` → `mathrm_Spec`; `\partial` → `partial`; `\Spec` → `Spec`. NFC-normalized; **case-preserving** (`tokenizer.py:38-39`); `H_{ij}` → `H_ij`; exotic notations (`H^{n+1}`, `H_{i,j}`) decompose to component tokens. `TOKENIZER_VERSION = "v1.0"` (`tokenizer.py:76`).

### What E04_S04 actually shipped (`ingest/bm25_indexer.py`)

This is the ground truth — the brief misrepresents the design. E04_S04 did **not** build a LanceDB-native FTS index. It built an out-of-band pickled `BM25Okapi`:

- `ingest/bm25_indexer.py:225-393` — `build_bm25_index(lancedb_path, corpus_version)`:
  - Reads every `(chunk_id, body_tokens, paper_id)` triple from the pinned LanceDB version via `server.corpus.open_chunks_table` (line 316).
  - Skips rows where `body_tokens is None` or whitespace-only (lines 334-347).
  - Calls `BM25Okapi(corpus)` where `corpus` is `list[list[str]]` from `body_tokens.split()` (line 365).
  - Writes `var/arxmcp/index/bm25/v<N>/bm25.pkl` and `chunk_ids.json` atomically (lines 371-375). Both files MUST exist for idempotent skip (line 293).
- `ingest/bm25_indexer.py:62-71` — flagged TODO(E07): "the loader (in :mod:`server` for query-time BM25) MUST verify file ownership matches process UID and refuse world-writable paths before calling `pickle.load`." **This milestone owns that loader.** It is a hard requirement, not an optional defense-in-depth.

### Server lifecycle wiring

- `server/resources.py:209-326` — `Resources` dataclass + `Resources.startup`. Long-lived singletons attach here. The dataclass currently holds `chunks_table` (LanceDB handle), `embed_semaphore`, `rerank_semaphore`, `rerank_singleflight`, `reranker_model`. **Adding `bm25_phase: BM25Phase` to this dataclass is the wiring seam.** Load order (lines 259-313): corpus marker → LanceDB handle → embedder → reranker → semaphores. BM25 fits between LanceDB-handle open and embedder load (it depends only on `corpus_info.version` + `lancedb_path`; load via `loop.run_in_executor` for the same reason E06_S01 deferred LanceDB open — synchronous file I/O).
- `server/corpus.py:109-199` — `open_chunks_table(lancedb_path, version)` is the canonical pinning primitive; the BM25 phase MUST NOT call this on every query. Cache the handle on the dataclass; the brief is explicit ("must not re-read `corpus-version.json` on every query").

### Integration seam with E07_S02

- `server/handlers/search.py:78-158` — `handle_search_papers`. Today: dense-only ANN over `embedding_stmt` (line 113). The handler's docstring (`search.py:1-7`) flags E07 as the integration venue. E07_S01 adds the BM25 candidate list; E07_S02 consumes it via `ANNPhase.query(query_text, bm25_candidates, top_n=50)`. **E07_S01 itself does NOT modify `search.py`** — that's E07_S02's responsibility.

### Library and test infrastructure

- `pyproject.toml:65-71` pins `rank-bm25>=0.2`. `BM25Okapi.get_scores(tokenized_query: list[str]) -> np.ndarray` of length `corpus_size`.
- `tests/test_bm25.py:1-586` covers the indexer (E04_S04). The new test file `tests/retrieval/test_bm25.py` lives alongside; `tests/retrieval/` does not yet exist (verified). Pattern from `tests/test_bm25.py:188-237` (build-then-load) shows the curated-chunks fixture pattern this milestone should reuse.

## 2. Prior decisions and lessons

- **BM25 is in-memory pickle, not LanceDB FTS.** Verified by reading `ingest/bm25_indexer.py:365, 374` (`BM25Okapi` + `pickle.dumps`). LanceDB *does* offer Tantivy-backed FTS (`tbl.create_fts_index(...)` + `tbl.search(query).type("fts")`) but **E04_S04 explicitly rejected it** — H4 critique remediation. The BM25 phase therefore loads `bm25.pkl` + `chunk_ids.json` on startup (or lazily on first query) and runs `bm25.get_scores(tokens)` per call. **Filters via combined LanceDB scalar+FTS predicate (the brief's promise) is not achievable** with this architecture; filters must be applied as a post-pass against a `chunk_id → row metadata` lookup, OR by filtering the candidate set before scoring (more on this below).
- **Filter columns do not exist on `chunks`.** The brief lists `categories, year_min, year_max, authors, include_withdrawn` — none of these are columns on the `chunks` table (verified in `ingest/schema.py:69-117`). The design note (`05-storage-and-indexing.md:120-142`) plans them on a `papers` metadata table that has not been built. **For Tier-1 v1, the only filter that can be honored is one keyed on a column that actually exists** (`paper_id`, `kind`, `chunker_version`, `embedder_version`, `preamble_ref`). Recommendation: implement a stub filter pipeline that accepts the documented kwargs but emits `filter_warnings: ["categories ignored: papers metadata table not yet built (E0X)"]` for unimplemented filters — same pattern as `server/handlers/search.py:131-141`. The AC `filters={"categories": ["math.AG"]}` cannot pass without a stand-in: ship a curated test corpus where chunks carry a synthetic categorical attribute, OR mark that AC as deferred and document the gap.
- **Thread safety.** `rank_bm25.BM25Okapi.get_scores` is read-only after construction — pure NumPy operations on the indexed `idf`/`doc_freqs`/`doc_len` arrays. Safe under the GIL for concurrent readers; safe under threads released for I/O. No locks needed. `LanceDB` table handles: per `server/corpus.py:26-35`, `checkout` mutates in place, so the cached handle MUST NOT be re-checked-out concurrently — which is fine because the brief mandates no version re-pinning at query time.
- **`BM25Phase` is a long-lived heavy object.** `bm25.pkl` for the seed corpus is small (≤ a few MB), but for the 200K-paper target it's hundreds of MB. Load once into the `Resources` singleton at startup. Do NOT re-instantiate per query.
- **Query tokenization parity is non-negotiable.** The query MUST go through `ingest.tokenizer.tokenize_body` before `bm25.get_scores`, otherwise `\Spec` (raw) will not match `Spec` (indexed). The brief says "byte-faithful passthrough" — but BM25 needs *tokens*, not bytes. Resolution: pass the query bytes verbatim to `tokenize_body`, then `.split()`. The byte-faithfulness applies to the cache key (Tier-1 cache uses `query.strip()` only); the BM25 phase's tokenization is downstream of caching and must mirror index-time tokenization to retrieve anything.

## 3. External sources

- `rank-bm25` 0.2.x: `BM25Okapi(corpus: list[list[str]], k1=1.5, b=0.75)`; `get_scores(query: list[str]) -> np.ndarray`; `get_top_n(query, documents, n)`. Source: `https://github.com/dorianbrown/rank_bm25/blob/master/rank_bm25.py`. The library has no thread-safety claims — but as confirmed above, the runtime path is read-only.
- LanceDB FTS docs (`https://lancedb.github.io/lancedb/fts/`): describe `create_fts_index` + `search(query).type("fts")` with combined scalar predicates via `.where(...)`. **Not used by this milestone** per E04_S04's rejection of LanceDB-native BM25.
- BM25 paper reference: not cited in `10-references-and-prior-art.md`; the closest entry is Tantivy (line 140-141) which the design rejects. No upstream paper to honor.

## Recommended single-path implementation

```python
class BM25Phase:
    def __init__(self, lancedb_path, corpus_version):
        # Load + sanity-check pkl + chunk_ids.json from
        # ingest.bm25_indexer.{_bm25_version_dir, BM25_INDEX_NAME, BM25_CHUNK_IDS_NAME}
        # MUST: stat() the file, refuse world-writable, refuse non-owner per E04_S04 TODO(E07).
        # MUST: pickle.load only after stat-check passes.
        ...
    def query(self, text: str, filters: dict | None = None,
              top_n: int = 200) -> list[tuple[str, float]]:
        tokens = ingest.tokenizer.tokenize_body(text).split()
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)        # np.ndarray
        # argpartition for O(n) top-N, then sort the top-N descending
        idx = np.argpartition(scores, -top_n)[-top_n:]
        idx = idx[np.argsort(-scores[idx])]
        out = [(self._chunk_ids[i], float(scores[i])) for i in idx if scores[i] > 0]
        # Apply filters POST-hoc against a metadata side-table loaded at init
        # (since chunks lacks the relevant columns). Stub for v1; emit warning.
        return out  # materialized list, not iterator
```

## Open questions

1. **`body_canonical` fallback path.** The brief promises a fallback to a "prose `body_canonical` BM25 index" if E04_S04's index is absent. That index does not exist anywhere in the codebase, and the column is `body_text`, not `body_canonical`. **Decision needed:** drop the fallback (recommended — the indexer is shipped and validated; absence is a fatal startup error) OR build a runtime fallback that calls `tokenize_body(body_text)` over the live LanceDB scan.
2. **Filter columns.** As detailed above, none of `categories, year_min, year_max, authors, include_withdrawn` exist on the `chunks` table. **Decision needed:** scope down to the columns that exist, OR add the metadata join from a future `papers` table (out of scope for E07_S01). Recommendation: implement filter handling as a post-pass against `(chunk_id → paper_id)` only; emit `filter_warnings` for the rest. Adjust the AC `BM25Phase.query("\\Spec", filters={"categories": ["math.AG"]})` to use a fixture-injected categorical attribute, or mark that specific AC deferred.
3. **Pickle loader hardening (TODO(E07) from `bm25_indexer.py:62-71`).** Hard requirement: the loader stat-checks file ownership and rejects world-writable paths before `pickle.load`. Confirm this lands in this milestone (recommended) rather than being deferred again.
4. **Lazy vs. eager load.** Brief says "instantiated once at server startup". Confirm eager — load `bm25.pkl` synchronously inside `Resources.startup` (off-load via `run_in_executor` like the LanceDB handle), so `/readyz` is honest about readiness. Failure to load = `ResourceStartupError` subclass (analogue of `CorpusNotIngestedError` in `server/resources.py:98-105`).

## External writes the implementation will require

None. Purely-internal retrieval milestone: no pushes, no PR creation, no ticket mutations, no third-party API calls, no infra changes. All artifacts are local files under `var/arxmcp/index/bm25/v<N>/` (already produced by E04_S04) and Python source under `server/retrieval/` + `tests/retrieval/`.
