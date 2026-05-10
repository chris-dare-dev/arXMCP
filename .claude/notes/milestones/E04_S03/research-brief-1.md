# E04_S03 Research Brief 1 — `corpus_version` marker file and cache invalidation contract

**Researcher:** Sonnet-A (Research Brief 1)
**Written:** 2026-05-08

---

## 1. In-codebase context

### 1a. Where `write_corpus_version_marker` should live and how it relates to `write_chunks`

`ingest/store.py` ends with a deliberate comment: "if a future side-file needs atomic writes, copy the pattern from `ingest.preamble._write_preamble_json` (the canonical implementation) rather than re-introducing it here." That comment closes F11 from the E04_S01 critique and explicitly anticipates this milestone. The home for `write_corpus_version_marker` is `ingest/store.py`, exactly as the brief specifies.

The question is whether `write_chunks` should call it automatically. The current `write_chunks` already calls `_append_store_stats` after a successful write — a pattern of post-write bookkeeping inside the function body. The corpus-version marker is analogous: it is a post-write side-effect that callers should not have to remember to invoke. **Decision: `write_chunks` should call `write_corpus_version_marker` internally, before returning `dataset_version`.** Callers (the corpus driver, tests) get the marker for free; the alternative — requiring every caller to chain the two calls — creates a contract gap where a future caller writes chunks but forgets the marker, producing a stale `corpus-version.json` that will silently misdirect the MCP server.

However, `write_corpus_version_marker` must be a public function (in `__all__`) so that tests can call it independently and so that the brief's deliverables list is met verbatim.

The `paper_count` and `chunk_count` parameters: `write_chunks` already receives `chunks: list[ChunkRecord]`, so `chunk_count = len(chunks)` is trivially available. `paper_count` is **not** available in `write_chunks` — `ChunkRecord` carries `paper_id` but the full corpus may span many papers, and the caller may have assembled chunks from multiple papers before the single `write_chunks` call. Two options:

1. Pass `paper_count` as an explicit parameter to `write_corpus_version_marker` (and to the internal call from `write_chunks`, where `paper_count = len({c.paper_id for c in chunks})`).
2. Derive it from a LanceDB query after write.

Option 1 is simpler and avoids an extra round-trip to LanceDB. The `chunks` list is in scope inside `write_chunks`, so `len({c.paper_id for c in chunks})` is a one-liner. **Decision: `paper_count` is a parameter; the internal call in `write_chunks` computes it from the set of distinct `paper_id`s in `chunks`.**

### 1b. `server/corpus.py` — existing module shape and conventions

`server/corpus.py` (landed E04_S02) currently exports only `open_chunks_table`. The module docstring references `corpus-version.json` explicitly: "The server uses this on cold startup before reading the `corpus-version.json` marker file (E04_S03); after the marker is read, the server re-opens with the explicit integer." This is a direct hook for E04_S03's `read_corpus_version`.

The module follows these conventions:
- Lazy `import lancedb` inside the function body (same as `ingest/store.py`).
- `lancedb_path: str | Path | None = None` defaulting to `DEFAULT_LANCEDB_PATH` from `ingest.store` — the F3-from-E04_S02 fix. `read_corpus_version` must adopt the same default.
- `__all__` is explicitly declared.
- The caching contract comment location: the brief says "Cache contract comment in server/corpus.py." The natural home is the module-level docstring OR a comment adjacent to `read_corpus_version`'s return value. Given that the cache contract spans all caches (Tier 1–3 in 07-multi-agent-caching.md), the module docstring is the right place — it's where the reader sees the architectural context before diving into the function.

Conventions for the `CorpusVersionInfo` dataclass: the codebase uses `@dataclass` with explicit `to_dict` / `from_dict` methods (see `PreambleDoc` in `ingest/preamble_types.py`). `CorpusVersionInfo` should follow the same pattern, with `from_dict` accepting the raw JSON dict and `to_dict` emitting the same dict. The natural module to define it is `server/corpus.py` itself (not a separate `_types.py`) because it is read-only and the server-layer module is small.

### 1c. Atomic-write pattern — canonical form

The codebase has TWO canonical implementations:
- `ingest/preamble._write_preamble_json`: PID + UUID-suffixed tmp, `tmp.write_text(payload)`, `os.replace(tmp, out_path)`, `finally: contextlib.suppress(OSError): tmp.unlink(missing_ok=True)`.
- `ingest/embedder._write_embeddings_manifest`: identical pattern for the JSON sidecar.

The private `_write_corpus_version_marker_atomic` helper (or equivalently, inlining it in `write_corpus_version_marker`) should copy this pattern exactly:

```python
tmp = out_path.with_suffix(
    f"{out_path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
)
payload = json.dumps(doc.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
try:
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, out_path)
finally:
    import contextlib
    with contextlib.suppress(OSError):
        tmp.unlink(missing_ok=True)
```

Note: `store.py` already imports `json`, `os`, `uuid`, and `contextlib` is imported lazily in `preamble.py`'s `_write_preamble_json`. For `store.py`, add `import contextlib` and `import uuid` to the top-level imports. `os` is not currently imported in `store.py` — add it.

### 1d. Cache invariants from 07-multi-agent-caching.md

The note states: "Tier 1 — Exact-query (SQLite LRU, 10K entries): key includes `corpus_version: int` as a mandatory component; stale entries from old corpus versions are unreachable by construction after a restart with a new `corpus-version.json`."

The BP1 byte-stability discipline ("No timestamps, no random tie-breaks") applies to **tool-result payloads** and **chunk content** — artifacts that are themselves cached or that flow into the Anthropic prompt cache. The `corpus-version.json` marker file is the **source** of cache invalidation, not itself a cached artifact. It is written by the ingestion pipeline and read by the server; it never enters the prompt cache or the retrieval cache. Therefore, the `created_at` timestamp is not a BP1 violation — but it IS a source of byte divergence between two ingest runs that produce identical corpus content (same papers, same chunks, same embeddings) differing only in wall-clock time. This matters for tests that compare the written file byte-for-byte, and for ops reproducibility.

### 1e. Threat 6 — `embedder_version` field

`ingest/embedder.py` defines: `EMBEDDER_VERSION = f"bge-m3@{BGE_M3_COMMIT_SHA[:8]}"` — so `"bge-m3@5617a9f6"`. The brief's schema shows `"bge-m3@abc1234"` (8-char placeholder). The actual runtime value is the 8-char prefix form. Threat 6 says "Pin model commit SHAs" but it says SHA**s** in the plural, not "store the full 40-char SHA in the marker file." The full 40-char SHA lives in `BGE_M3_COMMIT_SHA` in `embedder.py`; the marker file's `embedder_version` field is the same 8-char-prefix form that already flows into every LanceDB row via the `embedder_version` column. The marker file and the LanceDB rows are consistent by construction if both read `EMBEDDER_VERSION`.

### 1f. Existing scan tests — regression risk

`tests/test_chunker_ids.py` and `tests/test_query_encoder.py` have single-source-of-truth scan tests. `tests/test_mvcc.py` asserts the literal string `"No symlink swaps. LanceDB version int IS the corpus_version."` appears in `ingest/store.py`'s module docstring. None of these reference `corpus-version.json` file-name literals, so a new file-name constant in `store.py` will not cause regressions. However: if `tests/test_mvcc.py::TestSingleSourceOfTruth` scans for `"chunks"` as a literal in `server/corpus.py`, adding `read_corpus_version` to the same module will not trigger that test (the new function does not use the string `"chunks"`). No regression risk.

---

## 2. Prior decisions and lessons

### D1. `created_at` — allow it but make it optional to suppress in tests

The marker file is NOT a cached artifact (no BP1 violation), but `created_at` creates byte-instability between identical-content ingest runs. The resolution: keep `created_at` in the schema (it is useful for ops and matches the brief exactly), but `CorpusVersionInfo.from_dict` should be lenient about its absence (use `data.get("created_at")` returning `None`, not `data["created_at"]`). Tests that want byte-stability can pass a fixed `created_at` string. Tests that want to assert `version` increments don't need to compare the file bytes at all.

### D2. `embedder_version` is the 8-char prefix form — `EMBEDDER_VERSION` is the single source of truth

The brief's schema shows `"bge-m3@abc1234"`. The actual constant is `EMBEDDER_VERSION = f"bge-m3@{BGE_M3_COMMIT_SHA[:8]}"` in `ingest/embedder.py`. `write_corpus_version_marker` receives `embedder_version: str` as a parameter (matching the brief's signature). The internal call from `write_chunks` passes `embeddings.embedder_version` — which is already the 8-char prefix form loaded from the sidecar manifest. Single source of truth is `ingest/embedder.py::EMBEDDER_VERSION`; the parameter just threads it through. This is consistent with how `chunker_version` flows: `ChunkRecord.chunker_version` defaults to `CHUNKER_VERSION` from `chunker_types`, and the column in LanceDB carries that value.

### D3. `lancedb_version` in `WriteStats` vs. `version` in the marker file

`WriteStats.lancedb_version` is the same integer as the marker file's `version` field — the post-index LanceDB dataset version returned by `write_chunks`. They MUST match. The internal call from `write_chunks` should pass `dataset_version` (already computed) to `write_corpus_version_marker`, ensuring consistency without a second version query.

### D4. Function signature — parameters vs. auto-import

The brief specifies: `write_corpus_version_marker(lancedb_path, version, chunker_version, embedder_version, paper_count, chunk_count)`. Taking these as explicit parameters (rather than auto-importing constants) is correct: it makes the function unit-testable with arbitrary values and avoids a tight coupling between `store.py` and the constants. The internal call from `write_chunks` is where `CHUNKER_VERSION` and `EMBEDDER_VERSION` are threaded in. This mirrors how `_append_store_stats` receives a `WriteStats` object fully assembled by the caller.

### D5. `read_corpus_version` should default to `DEFAULT_LANCEDB_PATH`

The E04_S02 F3 fix established that both reader and writer default to the same path. `read_corpus_version(lancedb_path: str | Path | None = None)` should follow the identical convention, importing `DEFAULT_LANCEDB_PATH` from `ingest.store` (already imported in `server/corpus.py`).

---

## 3. External sources

- **JSON serialization:** `json.dumps(..., sort_keys=True, ensure_ascii=False)` — already used in `_append_store_stats` in `store.py`. Use exactly this call.
- **Python dataclasses with `from_dict`/`to_dict`:** `PreambleDoc` in `preamble_types.py` is the canonical pattern. `CorpusVersionInfo` should mirror it: keys in sorted order in `to_dict`, `from_dict` using `data.get(...)` for optional fields (`created_at`).
- **ISO-8601 timestamp:** use `datetime.now(timezone.utc).isoformat()` (timezone-aware, Python 3.11+ best practice) rather than the deprecated `datetime.utcnow().isoformat() + "Z"`. The `+00:00` suffix produced by the former is valid ISO-8601; the trailing `Z` form requires `.replace("+00:00", "Z")` to match the brief's example exactly. Pick `datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")` for exact schema conformance.
- **Atomic rename:** `os.replace(tmp, dst)` is POSIX-atomic. Already canonical in the codebase.

---

## Open questions

1. **Should `write_corpus_version_marker` be called BY `write_chunks` automatically, or by a separate corpus driver?** Opinionated answer: call it inside `write_chunks`, following the `_append_store_stats` precedent. The alternative (requiring every caller to chain two calls) creates a contract gap. If E04_S04's `build_bm25_index` also needs to read the marker, it can call `read_corpus_version` — it doesn't need to write it.

2. **Is `created_at` really necessary?** It breaks byte-stability for two otherwise-identical ingest runs. Retain it (it matches the brief exactly and the marker file is not a cached artifact), but make `from_dict` lenient (`data.get("created_at")`). If the team later drops it, `from_dict` won't break.

3. **Should `read_corpus_version` raise `FileNotFoundError` or return `None` when the marker is absent?** The MCP server comment in E04_S02's `open_chunks_table` says: "The server uses this on cold startup before reading the `corpus-version.json` marker file (E04_S03); after the marker is read, the server re-opens with the explicit integer." This implies the server handles a missing marker (first run before any ingest). `read_corpus_version` should raise `FileNotFoundError` with a clear message (mirrors `open_chunks_table`), letting the caller decide the fallback. `None` return is too implicit.

4. **Where does `paper_count` come from?** Derive from `{c.paper_id for c in chunks}` inside `write_chunks`. Do NOT query LanceDB after the write — that adds latency and could return a stale count if the merge updated rows rather than inserting.

5. **Should the marker file include the full 40-char `BGE_M3_COMMIT_SHA`?** Threat 6 calls for pinning SHAs, but the marker file's `embedder_version` field already carries the same 8-char prefix that the LanceDB rows carry. Adding a full-SHA field (`"embedder_commit_sha": BGE_M3_COMMIT_SHA`) would align with Threat 6's "pin the SHA" language and would make the marker file useful as a security manifest. However, the brief does not include this field. Defer — the brief schema is the contract; deviations are breaking changes.

---

## External writes the implementation will require

| Path | Action | Notes |
|---|---|---|
| `ingest/store.py` | edit | Add `write_corpus_version_marker(...)`, call it from `write_chunks` after `_append_store_stats`; add `import os`, `import uuid`, `import contextlib` to top-level imports; update `__all__` |
| `server/corpus.py` | edit | Add `CorpusVersionInfo` dataclass, `read_corpus_version(lancedb_path)` function, cache-contract comment in module docstring; update `__all__` |
| `tests/test_corpus_version.py` | new file | Write marker → read back → assert fields match; two successive writes → assert version increments |
| `var/arxmcp/index/lancedb/corpus-version.json` | runtime artifact | Written by `write_chunks` on every successful ingest run; not tracked in git |
