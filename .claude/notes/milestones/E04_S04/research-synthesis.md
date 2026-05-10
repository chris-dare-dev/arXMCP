# E04_S04 Research Synthesis — BM25 index over `body_tokens`

**Sources:** `research-brief-1.md` (Sonnet-A), `research-brief-2.md` (Sonnet-B)
**Status:** convergent on every load-bearing decision.
**Written:** 2026-05-08

---

## Resolved decisions

### D1. Use `rank_bm25` (not a custom implementation)

`rank-bm25>=0.2` (PyPI package; module name `rank_bm25`). Add to
`pyproject.toml` `[project.dependencies]`. Pure Python, MIT-licensed,
no compiled deps, ~400 LOC, well-tested. The brief explicitly names
it. A 30-line custom implementation introduces fresh correctness risk
(IDF edge cases, zero-document corpora) for no benefit at Tier-0.

```python
from rank_bm25 import BM25Okapi

corpus = [body_tokens.split() for body_tokens in body_tokens_list]
bm25 = BM25Okapi(corpus, k1=1.5, b=0.75)  # defaults
scores = bm25.get_scores(query_tokens)  # numpy array, aligned with corpus
top_idx = int(scores.argmax())
top_chunk_id = chunk_ids[top_idx]
```

### D2. Module name: `ingest/bm25_indexer.py` (matches brief verbatim)

The brief's deliverables list specifies `ingest/bm25_indexer.py`. Use
that name (not `bm25_index.py`, which Researcher B sketched). The
naming aligns with `ingest/embedder.py` (the action: encode/index).

### D3. Constants live in `bm25_indexer.py`, not `store.py`

`store.py` is the LanceDB writer; it has no BM25 concern (mirrors
`EMBEDDINGS_DIR` living in `embedder.py`, not `store.py`). The new
module owns:

```python
BM25_DIR_NAME = "bm25"                # var/arxmcp/index/bm25/
BM25_INDEX_NAME = "bm25.pkl"
BM25_CHUNK_IDS_NAME = "chunk_ids.json"
BM25_INDEX_ROOT = REPO_ROOT / "var" / "arxmcp" / "index" / BM25_DIR_NAME
BM25_STATS_PATH = REPO_ROOT / "var" / "arxmcp" / "ops" / "bm25-stats.jsonl"
```

A helper `_bm25_version_dir(corpus_version: int) -> Path` confines
the `f"v{N}"` literal to one place — every other reference goes
through the helper.

### D4. Read LanceDB via `server.corpus.open_chunks_table` — not direct `lancedb.connect`

The reader-side wrapper from E04_S02 is the canonical entry point.
It validates the path, performs `tbl.checkout(version)` for MVCC
isolation, and re-raises bad-version errors as `ValueError`. The
indexer must use it to inherit those guarantees.

```python
from server.corpus import open_chunks_table

tbl = open_chunks_table(lancedb_path, version=corpus_version)
arrow = tbl.to_arrow()
chunk_ids = arrow.column("chunk_id").to_pylist()
body_tokens_list = arrow.column("body_tokens").to_pylist()
```

This creates a `server` ↔ `ingest` import — but `server.corpus`
already imports from `ingest.store` (E04_S02 D7), so the dependency
direction is consistent: `ingest.bm25_indexer` reads via
`server.corpus`, which reads via `ingest.store`. No cycle.

### D5. Trust the caller's `corpus_version` parameter

Do NOT cross-check against `corpus-version.json` inside
`build_bm25_index`. Reasons:

1. `open_chunks_table` already validates that `corpus_version` is a
   real LanceDB version (raises `ValueError` on bad version).
2. A caller may intentionally build a BM25 index for an older
   version (re-build / audit path).
3. Cross-checking couples BM25 build to ingest state, making tests
   harder to isolate.

The function trusts the caller. Document this contract in the
docstring.

### D6. Atomic writes for both `bm25.pkl` and `chunk_ids.json`

Both files must use the canonical pattern (`preamble._write_preamble_json`):
PID + UUID-suffixed tmp + `os.replace` + `try/finally` cleanup with
`contextlib.suppress(OSError)`.

`pickle` for `bm25.pkl` (`pickle.dump(bm25_obj, fh,
protocol=pickle.HIGHEST_PROTOCOL)` then `tmp.write_bytes(...)` is
unnecessary — write directly through the file handle, then
`os.replace`).

```python
# bm25.pkl
tmp_pkl = pkl_path.with_suffix(
    f".pkl.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
)
try:
    with tmp_pkl.open("wb") as fh:
        pickle.dump(bm25, fh, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp_pkl, pkl_path)
finally:
    with contextlib.suppress(OSError):
        tmp_pkl.unlink(missing_ok=True)
```

JSON file is plain text via `tmp.write_text(payload, encoding="utf-8")`.

### D7. Idempotency: BOTH files must exist (not just one)

Mirror E03_S02's verify-the-artifact discipline. The brief's "no-op
if files exist" requires checking BOTH. If only one exists (partial
write from a prior crash), fall through and rebuild.

```python
pkl_path = version_dir / BM25_INDEX_NAME
ids_path = version_dir / BM25_CHUNK_IDS_NAME
if pkl_path.is_file() and ids_path.is_file():
    logger.info("BM25 index already exists at %s — skipping rebuild", version_dir)
    return
```

`is_file()` (not `exists()`) so a directory at the marker location
returns False, matching the E04_S03 M5 fix discipline.

### D8. Empty-corpus edge: raise `ValueError`

`BM25Okapi([])` produces NaN IDFs / division-by-zero (verified by
both researchers). A zero non-null `body_tokens` corpus is a real
upstream bug at Tier-0 (E02_S03 ensures non-null body_tokens via
`tokenize_body`). Raise `ValueError("no rows with body_tokens at
corpus_version=N; cannot build BM25 index")` before instantiating
`BM25Okapi`.

### D9. Threat 1 path-traversal deferral block

`build_bm25_index` accepts `lancedb_path: str | Path` from the
caller. Add the same `.. warning::` + `TODO(E06)` block that
`read_corpus_version` and `write_corpus_version_marker` carry:

```rst
.. warning::

   Path-traversal validation (Threat 1 from
   ``08-security-observability-ops.md``) is **deferred to E06's
   tool-input boundary** (TODO(E06)). This function trusts
   ``lancedb_path`` as config-derived. Callers passing user-supplied
   paths MUST validate against an allowlisted corpus root first.
```

### D10. Pickle security: documented threat surface

The module docstring must include a pickle-trust paragraph. The BM25
pickle is produced locally from trusted LanceDB data; loading it
from an untrusted source would be RCE (pickle is unsafe with
adversarial inputs). The brief's own "pickle is in-process; Tier-5
needs scalable replacement" already commits to this scope.

```text
**Pickle security.** ``bm25.pkl`` is produced locally from trusted
LanceDB data by this module. ``pickle.load`` on an untrusted file is
remote-code-execution; the path
``var/arxmcp/index/bm25/`` MUST be treated as trusted-local. Threat
6 (08-security-observability-ops.md) covers model-weight pickles
(deny); the BM25 pickle is application data with the analogous-
narrower attack surface (trust local, deny remote).
```

### D11. Stats logging: `bm25-stats.jsonl` mirroring `store-stats.jsonl`

```python
@dataclass
class BM25Stats:
    chunk_count: int = 0
    corpus_version: int = 0
    elapsed_s: float = 0.0
    skipped: bool = False  # True when idempotent re-run

    def to_dict(self) -> dict:
        return {
            "chunk_count": self.chunk_count,
            "corpus_version": self.corpus_version,
            "elapsed_s": round(self.elapsed_s, 3),
            "skipped": self.skipped,
        }
```

Sorted keys, ensure_ascii=False, append-mode write with try/except
OSError. Mirrors `_append_store_stats`.

### D12. Module docstring carries the AC sentence verbatim

Brief AC: 'Module docstring states: "Standard Python BM25 over
pre-tokenized body_tokens. No Tantivy, no custom analyzer. See H4
remediation."'

This sentence appears verbatim in the module docstring. A regression
test (`TestModuleContract.test_docstring_h4_remediation_sentence`)
locks it via whitespace-collapsed substring match.

### D13. Test fixture: curated `body_tokens` strings

The brief's test query "Spec mathrm_Pic" requires that some chunk
have `body_tokens` containing those exact tokens after `.split()`.
But `tokenize_body("\mathrm{Spec}\, \mathrm{Pic}")` actually
produces `"mathrm_Spec mathrm_Pic"` — NOT `"Spec mathrm_Pic"`. The
test must construct chunks with curated `body_tokens` strings rather
than relying on the tokenizer's output for this specific query.

Test approach:
- 20 synthetic chunks with hand-crafted `body_tokens` strings.
- One chunk has `body_tokens = "Spec mathrm_Pic algebraic curve foo"`
  (the target).
- 19 decoys with disjoint vocabulary (e.g. `"theorem proof lemma"`,
  `"differential geometry manifold"`, etc.).
- Use `write_chunks` against a real LanceDB on `tmp_path` to exercise
  the production read path through `open_chunks_table`.
- Call `build_bm25_index(tmp_path / "lancedb", corpus_version=v)`
  where `v` is the integer returned by `write_chunks`.
- Load `bm25.pkl` and `chunk_ids.json`, query
  `bm25.get_scores(["Spec", "mathrm_Pic"])`, assert
  `chunk_ids[scores.argmax()]` is the target.

### D14. `_patched_bm25_stats_path` autouse fixture

Add to `tests/conftest.py` to redirect `BM25_STATS_PATH` into
`tmp_path` per test, mirroring the existing `_patched_store_stats_path`.
Closes the F8-from-E04_S01 / L4-from-E04_S03 pollution-prevention
pattern.

---

## Open questions resolved

- rank_bm25 vs custom: rank_bm25 (D1).
- File name: `bm25_indexer.py` per brief (D2).
- corpus_version cross-check: trust caller (D5).
- Empty corpus: raise ValueError (D8).
- Test query fixture: curated `body_tokens` (D13).
- Idempotency signal: both files exist + `is_file()` (D7).
- Stats log path: `var/arxmcp/ops/bm25-stats.jsonl` (D11).

---

## External writes the implementation will require

| Path | Event | Notes |
|---|---|---|
| `pyproject.toml` | source edit | adds `rank-bm25>=0.2` |
| `ingest/bm25_indexer.py` | new file | `build_bm25_index`, `BM25Stats`, helpers, constants |
| `tests/test_bm25.py` | new file | curated 20-chunk corpus, idempotency, "Spec mathrm_Pic" query AC, empty-corpus raise, partial-state rebuild |
| `tests/conftest.py` | source edit | new `_patched_bm25_stats_path` autouse fixture |
| `var/arxmcp/index/bm25/v<N>/bm25.pkl` | runtime | atomic write |
| `var/arxmcp/index/bm25/v<N>/chunk_ids.json` | runtime | atomic write |
| `var/arxmcp/ops/bm25-stats.jsonl` | runtime | append-mode JSONL |

No `git push`, no PR creation, no infra mutation. The first `pip
install` after the milestone lands pulls `rank-bm25` (~150 KB pure
Python).
