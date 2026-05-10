# Research Brief — E04_S04: BM25 Index over `body_tokens`

## 1. In-Codebase Context

### Stats logging pattern (`store-stats.jsonl`)

`ingest/store.py` defines:
```python
STORE_STATS_PATH = REPO_ROOT / "var" / "arxmcp" / "ops" / "store-stats.jsonl"
```

The `_append_store_stats` helper does:
```python
STORE_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
line = json.dumps(stats.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
with STORE_STATS_PATH.open("a", encoding="utf-8") as fh:
    fh.write(line)
```

`bm25-stats.jsonl` should mirror this exactly: `append` mode, `sort_keys=True`, `ensure_ascii=False`, `OSError` swallowed with a logger.error. The stats dict should include at minimum `chunk_count`, `elapsed_s`, `corpus_version`, and `index_path`. A `BM25Stats` dataclass following `WriteStats`'s shape is the right pattern. The ops path constant should be `BM25_STATS_PATH = REPO_ROOT / "var" / "arxmcp" / "ops" / "bm25-stats.jsonl"`.

### `open_chunks_table` iterator API

`server/corpus.py:open_chunks_table(path, version=N)` returns a `lancedb.table.Table` handle pinned to version N. From that handle, reading chunk_id + body_tokens is:

```python
tbl = open_chunks_table(lancedb_path, version=corpus_version)
arrow = tbl.to_arrow()  # returns pyarrow.Table
chunk_ids = arrow.column("chunk_id").to_pylist()
body_tokens_col = arrow.column("body_tokens").to_pylist()
```

Alternatively: `tbl.search().select(["chunk_id", "body_tokens"]).limit(None).to_arrow()` — but the full `to_arrow()` is simpler for a full-table scan during index build. The `body_tokens` column is declared `nullable=False` in schema, but the brief instructs `WHERE body_tokens IS NOT NULL` as a defensive filter. Use `[r for r in ... if r is not None]` at the Python layer.

### `tokenize_body` output format confirmed

`ingest/tokenizer.py` confirms: `tokenize_body(body_text: str) -> str` returns `" ".join(tokens)` — a whitespace-joined string. The docstring explicitly states: "The output is what E04_S04 will hand to `rank_bm25` after a single `split()` call." So `body_tokens.split()` is the exact tokenization contract for BM25 index build.

The tokenizer does NOT lowercase (math is case-sensitive). BM25 must also not lowercase. Query terms must be passed verbatim (no lowercasing at query time).

### `ChunkRecord.body_tokens` convention confirmed

`ingest/chunker_types.py` line 101 comment: "The annotation is `str | None` (NOT `list[str] | None`) to match the LanceDB schema's `string` column type — E04_S04's BM25 indexer does `body_tokens.split()`." Confirmed: whitespace-joined string, split for BM25.

### LanceDB column type

`ingest/schema.py`: `pa.field("body_tokens", pa.utf8(), nullable=False)`. The schema declares it non-nullable; but `ChunkRecord.body_tokens: str | None = None` allows None for legacy chunks. The store raises `ValueError` on None at write time (D8). At BM25 index build time, the defensive `IS NOT NULL` filter is still correct as belt-and-suspenders.

### `rank_bm25` in `pyproject.toml`

**Not pinned.** `pyproject.toml` lists: beautifulsoup4, transformers, torch, safetensors, numpy, lancedb, pyarrow. No BM25 library is present. `rank_bm25` is not installed in `.venv` (verified). **`rank-bm25` must be added to `dependencies` in `pyproject.toml`.**

### `05-storage-and-indexing.md` BM25 spec

Direct quote: "BM25 over `body_tokens` using Python `rank_bm25` (BM25Okapi); index stored at `var/arxmcp/index/bm25/v<N>/`. `body_tokens` is a space-joined token stream produced at chunk-write time by a Python regex pre-tokenizer (E02_S03) that preserves backslash tokens like `\Spec`, `mathrm_Pic`, etc. Standard whitespace split is all that BM25 needs over pre-tokenized input. **No Tantivy LaTeX analyzer**."

No k1/b knobs are specified — BM25Okapi defaults (k1=1.5, b=0.75) apply.

### `07-multi-agent-caching.md` — BM25 pickle as artifact

BP1 byte-stability applies to "tool result payloads" and "tool definitions," not to internal index files. The BM25 pickle (`bm25.pkl`) is a runtime index artifact, not a cached prompt artifact — it is loaded lazily (E07) into process memory and never enters the prompt cache or tool result payload. BP1 does not constrain its format. It must be idempotent (same corpus → same index behavior) but byte-stability of the pickle itself is not required.

### `08-security-observability-ops.md` — pickle security

Threat 6 covers supply-chain: "Use `safetensors` format only; refuse `.bin` / pickle weights." This applies to **model weights**, not to index artifacts. The BM25 pickle is produced entirely by our own code from our own LanceDB data — no attacker-supplied bytes enter the pickle. Risk surface: if an attacker can write to `var/arxmcp/index/bm25/`, they can inject a malicious pickle that gets loaded by the server. Mitigation: (1) document that `bm25.pkl` is trusted-only, produced locally; (2) verify `lancedb_path` is an allowlisted path (deferred to E06, same discipline as other path args). The module docstring should note: "bm25.pkl is produced locally from trusted LanceDB data; loading it from untrusted sources would be RCE (pickle)."

### Existing test scan guards

`conftest.py` has a single autouse fixture `_patched_store_stats_path` that redirects `STORE_STATS_PATH`. It does NOT redirect any BM25 paths. A parallel `_patched_bm25_stats_path` fixture should be added to `conftest.py`, OR the test can use `monkeypatch` inline. The existing test files (`test_store.py`, `test_mvcc.py`, `test_corpus_version.py`) all use real LanceDB on `tmp_path` — `test_bm25.py` should follow the same pattern.

---

## 2. Prior Decisions and Lessons

### Atomic-write pattern

The canonical pattern (from `ingest/preamble.py`, replicated in `store.py:write_corpus_version_marker`) is:
```python
tmp = out_path.with_suffix(f"{out_path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
try:
    tmp.write_bytes(...)  # or write_text
    os.replace(tmp, out_path)
finally:
    with contextlib.suppress(OSError):
        tmp.unlink(missing_ok=True)
```

Both `bm25.pkl` (binary) and `chunk_ids.json` (text) should use this pattern. The tmp file must be co-located with the destination (same filesystem) for `os.replace` to be POSIX-atomic. Use `pickle.dumps(bm25_obj)` → `tmp.write_bytes(data)` for the pickle, and `json.dumps(chunk_ids, ...) + "\n"` → `tmp.write_text(...)` for the JSON.

### `corpus_version` parameter discipline

The brief signature is `build_bm25_index(lancedb_path: str, corpus_version: int) -> None`. Following `write_corpus_version_marker`'s pattern: the function accepts `lancedb_path` (trusted, config-derived) with a `# TODO(E06)` path-traversal comment mirroring the existing deferral notes. `corpus_version` is an `int` — no path construction from it other than f-string into the directory name `f"v{corpus_version}"`.

### `read_corpus_version` vs. accepting `corpus_version` directly

The brief signature accepts `corpus_version: int` explicitly. **Do not call `read_corpus_version` inside `build_bm25_index`.** The function trusts the caller-supplied integer. This is correct: it matches the brief AC ("BM25 index built from non-null body_tokens in pinned corpus version") and avoids a hidden I/O dependency. The production driver reads the marker file once and passes the integer down.

### Idempotency: file-existence check

Brief: "re-run is a no-op if files exist." Check both:
```python
pkl_path = bm25_dir / "bm25.pkl"
ids_path = bm25_dir / "chunk_ids.json"
if pkl_path.is_file() and ids_path.is_file():
    logger.info("BM25 index already exists at %s — skipping rebuild", bm25_dir)
    return
```

If only one file exists (half-write from a previous crash), the check fails and a full rebuild runs — this is the correct behavior, since a half-written index is corrupt. No mtime comparison needed for Tier-0 (mtime-based staleness is an E11/ops concern).

### Constant placement

`BM25_DIR_NAME = "bm25"` should live in `ingest/bm25_indexer.py` (the new module owns its own constants). It does NOT belong in `ingest/store.py` because `store.py` is the LanceDB writer and has no BM25 concern. Mirror: `EMBEDDINGS_DIR` is defined in `ingest/embedder.py`, not in `store.py`. For cross-module sharing (if E07 needs to locate the BM25 index), export `BM25_INDEX_DIR` as a computed constant from `bm25_indexer.py`.

### Test fixture strategy

Real LanceDB on `tmp_path` is the established pattern (all existing integration tests). `test_bm25.py` should:
1. Build a real LanceDB table in `tmp_path` using `_make_chunk` + `_make_synthetic_embeddings` + `write_chunks` (imported from `test_store.py`).
2. Include at least one chunk whose `body_tokens` contains `"Spec mathrm_Pic"` explicitly — use `body_tokens` directly in the `ChunkRecord` constructor (bypassing `tokenize_body`) to control the exact token stream.
3. Call `build_bm25_index(str(tmp_path / "lancedb"), corpus_version=N)`.
4. Assert `bm25.pkl` and `chunk_ids.json` exist.
5. Load the index, query `["Spec", "mathrm_Pic"]`, assert the matching chunk has the highest score.

The query test is the key AC. Since `tokenize_body("$\\mathrm{Spec}\\, \\mathrm{Pic}$")` produces `"mathrm_Spec mathrm_Pic"` (the `\mathrm{Spec}` branch emits `mathrm_Spec`, not `mathrm_Pic`), the query `"Spec mathrm_Pic"` — with `Spec` as a bare word — matches chunks containing those tokens. Set up a fixture chunk with `body_tokens = "Spec mathrm_Pic algebraic geometry"` to guarantee the AC passes deterministically. Do not rely on what `tokenize_body` produces from real LaTeX for this specific query.

---

## 3. External Sources

### `rank_bm25` library

`pip install rank-bm25`. Class: `BM25Okapi(corpus, k1=1.5, b=0.75)` where `corpus` is `list[list[str]]`. Query: `bm25.get_scores(query_tokens)` returns a `numpy.ndarray` of float scores aligned with the corpus. The `BM25Okapi` object pickles cleanly (numpy arrays, dict, list — all natively picklable). The pickle contains: `corpus_size`, `avgdl`, `doc_freqs`, `idf`, `doc_len`, `epsilon`. No external dependencies in the pickle. **Recommend `rank_bm25` over a custom 30-line implementation**: it is a pure-Python library with no compiled extensions, is well-tested, and the brief explicitly names it. A custom implementation introduces fresh correctness risk for no benefit at Tier-0.

### Pickle security documentation

The module docstring must state: "bm25.pkl is produced locally from trusted LanceDB data by this module. Loading bm25.pkl from an untrusted filesystem path would be RCE (pickle). The path `var/arxmcp/index/bm25/` must be treated as a trusted-local directory. Threat 6 in `08-security-observability-ops.md` applies to model weights; the BM25 pickle has an analogous but narrower attack surface because it is never downloaded from the network."

### BM25 query mechanics

`bm25.get_scores(["Spec", "mathrm_Pic"])` returns a numpy array of shape `(N,)` where `N` is the corpus size. `chunk_ids[np.argmax(scores)]` gives the top-ranked chunk_id. The `chunk_ids` list from `chunk_ids.json` is index-aligned with the BM25 corpus.

---

## Open Questions

1. **`rank_bm25` vs custom 30-line BM25?** Recommend `rank_bm25`. The brief allows either; `rank_bm25` is explicitly named first, has no compiled deps, is correctly implemented, and the 30-line alternative introduces fresh regression risk. Use `BM25Okapi` with default hyperparameters (k1=1.5, b=0.75) — no tuning at Tier-0.

2. **How does `build_bm25_index` resolve the LanceDB version?** Accept `corpus_version: int` as a parameter per the brief signature, and trust the caller. Do NOT call `read_corpus_version` internally. Pass `version=corpus_version` to `open_chunks_table`.

3. **Zero-row corpus edge case.** If `SELECT chunk_id, body_tokens FROM chunks WHERE body_tokens IS NOT NULL` returns zero rows: build an empty BM25 corpus (`BM25Okapi([[]])`? No — `BM25Okapi` requires a non-empty corpus). Recommended: log a WARNING, write an empty `chunk_ids.json = []`, and skip writing `bm25.pkl` (mark the index as unbuilt). The E07 loader should check for this state. Alternatively, raise `ValueError("empty corpus — cannot build BM25 index")`. Given the brief's "no-op if files exist" AC implies both files must be written for the index to be valid, the cleaner option is to raise: a zero-row corpus is a real upstream bug at Tier-0.

4. **Query "Spec mathrm_Pic" — fixture control.** The test must use a fixture chunk with `body_tokens` set explicitly to include `"Spec"` and `"mathrm_Pic"` as tokens. Do NOT rely on `tokenize_body` producing these from real LaTeX (the tokenizer emits `"mathrm_Spec"` for `\mathrm{Spec}`, not `"Spec mathrm_Pic"`). The test should construct a `ChunkRecord` with `body_tokens = "Spec mathrm_Pic algebraic curve"` directly, bypassing the tokenizer.

5. **Idempotency signal.** File-existence check (`pkl.is_file() and ids.is_file()`) is sufficient for Tier-0. Mtime-based staleness detection (compare bm25.pkl mtime vs corpus-version.json mtime) is an E11 concern. The brief explicitly says "re-run is a no-op if files exist" — implement exactly that.

---

## External Writes the Implementation Will Require

- **`pyproject.toml`**: add `"rank-bm25>=0.2"` to `dependencies`.
- **`ingest/bm25_indexer.py`**: new file — `build_bm25_index` function, `BM25Stats` dataclass, `BM25_INDEX_ROOT`, `BM25_STATS_PATH` constants, module docstring with H4 remediation note and pickle security warning.
- **`tests/test_bm25.py`**: new file — 20-fixture corpus built on real LanceDB in `tmp_path`, idempotency test, query AC for "Spec mathrm_Pic".
- **`tests/conftest.py`**: add `_patched_bm25_stats_path` autouse fixture mirroring `_patched_store_stats_path`.
- **Runtime files** (created by `build_bm25_index` at ingest time): `var/arxmcp/index/bm25/v<N>/bm25.pkl` and `var/arxmcp/index/bm25/v<N>/chunk_ids.json`.
