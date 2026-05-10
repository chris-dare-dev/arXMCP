# E04_S04 Research Brief 2 — BM25 Index over `body_tokens`

---

## 1. In-Codebase Context

### `ingest/tokenizer.py` — `tokenize_body` output

Module docstring (verbatim):

> "Math-aware regex pre-tokenizer for the BM25 ``body_tokens`` field (E02_S03).
> No custom Tantivy LaTeX analyzer is used; see H4 remediation."

`tokenize_body` docstring (verbatim):

> "Produce a whitespace-joined token string for BM25 indexing. The function is pure
> and deterministic: same input → same output on any Python version, on any host,
> every time. It applies NFC normalization, strips ``$...$`` math delimiters, runs
> one regex sweep over the result, and returns ``" ".join(tokens)``."

Output of `tokenize_body` is a **single space-joined string**. The BM25 layer
calls `.split()` on it to recover the token list. Example:
- `\mathrm{Spec}` → token `mathrm_Spec`
- `\mathbb{Z}` → token `mathbb_Z`
- `\partial` → token `partial`

The query string "Spec mathrm_Pic" therefore splits into `["Spec", "mathrm_Pic"]`,
which matches chunks whose `body_tokens` contains those whitespace-delimited tokens.

### `ingest/store.py` — stats discipline

`STORE_STATS_PATH` (line 114):
```python
STORE_STATS_PATH = REPO_ROOT / "var" / "arxmcp" / "ops" / "store-stats.jsonl"
```

`_append_store_stats` (lines 450–464):

```python
def _append_store_stats(stats: WriteStats) -> None:
    """Append one JSON line to ``var/arxmcp/ops/store-stats.jsonl``.

    Append mode is non-atomic but acceptable for an ops log — mirrors
    the ``embed-stats.jsonl`` discipline from E03_S01.
    """
    STORE_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = (
        json.dumps(stats.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
    )
    try:
        with STORE_STATS_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        logger.error("could not write to store-stats.jsonl: %s", STORE_STATS_PATH)
```

The BM25 stats writer (`_append_bm25_stats`) should mirror this exactly:
- Module-level path constant `BM25_STATS_PATH = REPO_ROOT / "var" / "arxmcp" / "ops" / "bm25-stats.jsonl"`
- `@dataclass BM25Stats` with `to_dict()` returning alphabetically-keyed fields
- `try/except OSError` wrapping the file append
- `sort_keys=True` in `json.dumps`
- Parent `mkdir` before open

### `server/corpus.py` — `open_chunks_table`

The BM25 indexer must call `open_chunks_table(lancedb_path, version=corpus_version)`
— not call `lancedb.connect(...)` directly. This is a hard constraint:

- `open_chunks_table` handles `FileNotFoundError` with a clear message
- It performs the `tbl.checkout(version)` pin for MVCC isolation
- It re-raises bad-version errors as `ValueError` with context

After getting the table handle:
```python
tbl = open_chunks_table(lancedb_path, version=corpus_version)
arrow = tbl.to_arrow()
# filter in Python — simpler than a WHERE clause at Tier-0 scale
mask = [row is not None for row in arrow.column("body_tokens").to_pylist()]
```

### `ingest/schema.py` — `body_tokens` field

Line 77: `pa.field("body_tokens", pa.utf8(), nullable=False)` — non-nullable.
The store raises `ValueError` on `body_tokens=None` at write time (line 309),
so by the time BM25 builds, every row has a non-null value. The indexer can
read all rows without a NULL filter; a defensive `IS NOT NULL` filter is
redundant but harmless.

### `pyproject.toml`

No BM25-related dependency is pinned. `rank-bm25` is not present. Adding
`"rank-bm25>=0.2"` to the `[project.dependencies]` list is the only
`pyproject.toml` change required. No entry in `[project.optional-dependencies]`
— BM25 is a first-class runtime dependency, not dev-only.

### `05-storage-and-indexing.md` — BM25 spec

Verbatim (lines 63–68):
> "BM25 over `body_tokens` using Python `rank_bm25` (BM25Okapi); index stored at
> `var/arxmcp/index/bm25/v<N>/`. `body_tokens` is a space-joined token stream
> produced at chunk-write time by a Python regex pre-tokenizer (E02_S03) that
> preserves backslash tokens like `\Spec`, `mathrm_Pic`, etc. Standard whitespace
> split is all that BM25 needs over pre-tokenized input. **No Tantivy LaTeX
> analyzer** — Tantivy ships no such analyzer; the approach was fictional."

### `08-security-observability-ops.md` — pickle / RCE

Threat 6 (line 76): "Use `safetensors` format only; refuse `.bin` / pickle weights."
This applies to **model weights** only, not to application data artifacts. The BM25
pickle (`bm25.pkl`) is written and read by the same trusted local process. The indexer
docstring must state: "Never load `bm25.pkl` from an untrusted source — pickle is
not safe for data from third parties." This is sufficient for Tier-0. The brief's
own language ("pickle is in-process; Tier-5 needs scalable replacement") confirms
acceptability.

### Recent commit patterns (E04_S03 feat + rect)

From `6d12138` and `01adfce`:
- `try/except Exception` (widened from `OSError`) for best-effort post-success ops
  (marker write inside `write_chunks`). The BM25 stats append should use `OSError`
  narrowly (write failure), not the widened form.
- `.. warning:: TODO(E06) Threat-1` blocks in every function accepting a filesystem
  path from the caller.
- Single-source-of-truth filename constants (`CORPUS_VERSION_MARKER_NAME`).
- `@dataclass` stats objects with `to_dict()` + alphabetical `json.dumps(sort_keys=True)`.

---

## 2. Prior Decisions and Lessons

### Atomic-write discipline

`ingest/preamble._write_preamble_json` is the canonical pattern; `write_corpus_version_marker`
(lines 566–575 of `store.py`) replicates it verbatim:

```python
tmp = out_path.with_suffix(
    f"{out_path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
)
try:
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, out_path)
finally:
    with contextlib.suppress(OSError):
        tmp.unlink(missing_ok=True)
```

Both `bm25.pkl` and `chunk_ids.json` must use this pattern. They are written
sequentially; write `chunk_ids.json` first (pure JSON, no deps), then `bm25.pkl`.
If the process dies mid-write the `.tmp` file is left behind (cleaned by the
`finally`) and the destination is not corrupted.

### Threat 1 path-traversal deferral

`open_chunks_table` (lines 135–142) and `read_corpus_version` (lines 347–350) both
contain the identical `.. warning::` block. `build_bm25_index` must add the same:

```rst
.. warning::

   Path-traversal validation (Threat 1 from
   ``08-security-observability-ops.md``) is **deferred to E06's
   tool-input boundary** (TODO(E06)). This function trusts
   ``lancedb_path`` as config-derived.
```

### Single-source-of-truth naming

`CORPUS_VERSION_MARKER_NAME` is the exemplar. The BM25 module should define:

```python
BM25_DIR_NAME = "bm25"            # var/arxmcp/index/bm25/
BM25_INDEX_NAME = "bm25.pkl"
BM25_CHUNK_IDS_NAME = "chunk_ids.json"
```

The per-version subdir: a helper function is cleaner than an f-string literal
scattered across callers:

```python
def _bm25_version_dir(corpus_version: int) -> Path:
    return REPO_ROOT / "var" / "arxmcp" / "index" / BM25_DIR_NAME / f"v{corpus_version}"
```

The `f"v{N}"` literal lives only inside this helper. Every other reference uses
`_bm25_version_dir(corpus_version)`.

### Cross-checking `corpus_version` against the marker file

**Do not cross-check.** `build_bm25_index` should trust the caller. Reasons:
1. `open_chunks_table(lancedb_path, version=corpus_version)` already validates the
   version is a real LanceDB version (raises `ValueError` if not).
2. The marker file records the last-written version, but a caller may intentionally
   build a BM25 index for an older version (re-run / audit path).
3. Cross-checking couples BM25 build to ingest state, making tests harder to
   isolate — tests would need a valid marker file.
4. Trust the caller; document the contract.

### Idempotency and partial state

The brief says "no-op if files exist." But partial state (only `bm25.pkl` present,
`chunk_ids.json` missing, or vice versa) is a hazard — E03_S02's `_paper_is_up_to_date`
required verifying BOTH artifacts. Apply the same rule:

```python
pkl_path = version_dir / BM25_INDEX_NAME
ids_path = version_dir / BM25_CHUNK_IDS_NAME
if pkl_path.is_file() and ids_path.is_file():
    logger.info("BM25 index already exists at %s — skipping", version_dir)
    return
```

Both must be present **and** be regular files (`is_file()`, not `exists()`). If
only one is present, fall through and rebuild both from scratch (atomic writes
ensure no partial state is observable post-rebuild).

### Test fixture for "Spec mathrm_Pic"

Use curated synthetic chunks: hand-craft a list of `{"chunk_id": ..., "body_tokens": ...}`
dicts with known content. Do NOT depend on the full chunker + tokenizer pipeline.
Reasoning: the test query "Spec mathrm_Pic" tokenizes to `["Spec", "mathrm_Pic"]`;
create one chunk whose `body_tokens = "Spec mathrm_Pic foo bar"` and several
decoys with no overlap. This is deterministic, has zero dependency on E02_S01
fixture stability, and can run without a real LanceDB dataset.

For integration tests that require a real LanceDB table, use a tmp-dir LanceDB
fixture injected via `pytest` `tmp_path`. The test builds the table using
`write_chunks` with a minimal `EmbedRecord`.

---

## 3. External Sources

### `rank_bm25`

Install: `pip install rank-bm25` (PyPI package `rank-bm25`, module `rank_bm25`).

Key class: `BM25Okapi(corpus: list[list[str]], k1=1.5, b=0.75, epsilon=0.25)`.
- `corpus` is a list of token lists: `[doc.split() for doc in body_tokens_list]`.
- Method: `get_scores(query: list[str]) -> np.ndarray` — one float per document.
- `np.argsort(scores)[::-1]` gives descending rank order.

Construction is `O(N * avg_doc_len)`. At Tier-0 scale (thousands of chunks) this
is sub-second. The BM25Okapi object is the entire index state — pickling it and
the parallel `chunk_ids` list is sufficient for persistence.

### Pickle vs joblib

Use stdlib `pickle`. joblib is faster on numpy arrays but `BM25Okapi`'s internal
state is nested Python dicts and lists — joblib provides no speedup here and adds
a dependency. `pickle.dump(bm25_obj, fh, protocol=pickle.HIGHEST_PROTOCOL)` is
the right call.

### Pickle security

The project produces `bm25.pkl` locally from its own trusted pipeline. The indexer
docstring must state that loading a `bm25.pkl` produced by an untrusted third party
is a remote-code-execution risk. Never expose the load path to user-supplied file
paths (Threat 1 coverage). At Tier-0 this is a dev-only artifact.

### LanceDB query API

Simplest approach at Tier-0:
```python
tbl = open_chunks_table(lancedb_path, version=corpus_version)
arrow = tbl.to_arrow()
```
Then filter in Python: `arrow.column("body_tokens").to_pylist()` yields a list of
strings (all non-null per schema). Pair with `arrow.column("chunk_id").to_pylist()`
to build the parallel lists for `BM25Okapi`.

Do NOT use `.search().where(...)` — the `to_arrow()` + Python filter is simpler,
requires no SQL escaping, and is correct at any corpus size we target in Tiers 0–3.

---

## Open Questions

**1. `rank_bm25` vs custom 30-line BM25 — recommend:**
Use `rank_bm25`. The custom 30-line BM25 looks attractive but introduces a
maintenance surface (TF-IDF formula bugs, IDF edge cases on zero-document
corpora, no existing test coverage). `rank_bm25` is MIT-licensed, 400 lines,
well-tested, and the spec's own text names it. Add `"rank-bm25>=0.2"` to
`pyproject.toml` and be done.

**2. Should `build_bm25_index` validate `corpus_version` against the marker file?**
No. See §2 reasoning above. Trust the caller; `open_chunks_table` validates the
version is a real LanceDB version. Document the contract in the docstring.

**3. Test query "Spec mathrm_Pic" — curated vs real chunker output?**
Curated synthetic chunks. Create `body_tokens = "Spec mathrm_Pic foo bar"` in a
fixture dict. This is deterministic and has zero dependency on upstream pipeline
stability. Real chunker output is an integration test concern, not a unit test.

**4. Idempotency signal — file existence vs mtime vs content hash?**
File existence (`is_file()`) is sufficient and correct for the brief's stated
requirement. Mtime comparison adds complexity with no benefit (we don't have a
reference mtime to compare against). Content hash would require loading the pickle
to hash it, which defeats the no-op optimization. Both files must be present.

**5. Empty-corpus edge case:**
`BM25Okapi([])` — zero-document corpus. `rank_bm25` source shows `avgdl = 0` and
IDF calculations produce `nan` or division-by-zero for empty corpora. The
implementation should raise `ValueError("no non-null body_tokens rows; cannot
build BM25 index")` before calling `BM25Okapi`. Verify experimentally in unit
tests with `pytest.raises(ValueError)`.

---

## External Writes the Implementation Will Require

1. **`pyproject.toml`** — add `"rank-bm25>=0.2"` to `[project.dependencies]`.

2. **`ingest/bm25_index.py`** (new file) — the `build_bm25_index` module with:
   - Module docstring: `"Standard Python BM25 over pre-tokenized body_tokens. No Tantivy, no custom analyzer. See H4 remediation."`
   - Constants: `BM25_DIR_NAME`, `BM25_INDEX_NAME`, `BM25_CHUNK_IDS_NAME`, `BM25_STATS_PATH`
   - Helper: `_bm25_version_dir(corpus_version: int) -> Path`
   - Dataclass: `BM25Stats` with `to_dict()`
   - Private: `_append_bm25_stats`, `_load_corpus_rows`, `_write_index_atomic`
   - Public: `build_bm25_index(lancedb_path: str, corpus_version: int) -> None`

3. **`var/arxmcp/index/bm25/v<N>/bm25.pkl`** — atomically written BM25Okapi pickle.

4. **`var/arxmcp/index/bm25/v<N>/chunk_ids.json`** — atomically written JSON array
   of chunk_id strings, parallel to the BM25Okapi corpus list.

5. **`var/arxmcp/ops/bm25-stats.jsonl`** — append-only JSONL ops log, one line per
   `build_bm25_index` call, with fields: `chunk_count`, `corpus_version`,
   `elapsed_s`, `skipped` (bool), `timestamp_utc`.

6. **`tests/test_bm25_index.py`** (new file) — unit + integration tests covering
   idempotency, the "Spec mathrm_Pic" query AC, empty-corpus raise, and
   partial-state rebuild.
