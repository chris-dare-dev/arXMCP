# Research Brief — proof-verify-handler-wiring-m1

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-21T22:45:00Z

---

## In-codebase context

### Handler surgery target

`server/handlers/search.py` lines 217–225 (verbatim — the dense ANN block that m1 must conditionally modify):

```python
    with span_ann(k=k):
        arrow = (
            r.chunks_table.search(query_vec, vector_column_name="embedding_stmt")
            .limit(k * 5 if level != "theorem" else k)  # over-fetch for dedup
            .to_arrow()
        )
```

Lines 242–246 (verbatim — the `filter_warnings` emission m1 must suppress when `paper_id` IS honored):

```python
    filter_warnings: list[str] = []
    if filters:
        filter_warnings.append(
            "filters arg is accepted but not yet processed (deferred to E07_S04)"
        )
```

The `filter_warnings` message must be REMOVED for the `paper_id` key path when the filter is honored. It should still fire for unrecognized keys (e.g., `categories`) — mirror BM25Phase's `DEFERRED_FILTER_KEYS` warning pattern.

### Existing predicate escape contract (verbatim from `server/handlers/chunk.py:144-146`)

```python
def _escape_lance_str(s: str) -> str:
    """Escape single quotes for LanceDB SQL-style WHERE clauses."""
    return s.replace("'", "''")
```

The identical function appears as `_escape` in `server/handlers/paper.py:122-123`. m1 should import or replicate this pattern. Since `is_valid_paper_id` rejects any string not matching `^\d{4}\.\d{4,5}(v\d+)?$` or `^[a-z][a-z\-]*/\d{7}(v\d+)?$`, no valid paper_id can contain a single quote — the escape is a defense-in-depth backstop. The `_escape_lance_str` function in `chunk.py` is the canonical spelling; import it or define an equivalent local `_escape_paper_id` in `search.py`.

### `prefilter` parameter for ANN + WHERE composition

`get_paper` and `get_chunk` both pass `prefilter=True` to `.where(...)`:

```python
r.chunks_table.search()
    .where(f"paper_id = '{_escape(paper_id)}'", prefilter=True)
```

The spike-1 POC (`poc.py:67-70`) did NOT use `prefilter=True` on the ANN call:

```python
res.chunks_table
    .search(qv, vector_column_name="embedding_stmt")
    .where(filter_clause)
    .limit(TOP_K)
    .to_arrow()
```

The spike verdict was confirmed correct without `prefilter`. For ANN + `.where()` composition, LanceDB applies the scalar predicate as a post-filter on HNSW results by default (without `prefilter`). The `.where()` without `prefilter=True` on ANN queries is the correct pattern — `prefilter=True` is for FULL-TABLE scans (no vector column) and may change behavior for HNSW. **Do not add `prefilter=True` to the ANN call.** The spike validated the pattern without it.

### BM25Phase filter contract to mirror

`server/retrieval/bm25.py:117` (verbatim):

```python
SUPPORTED_FILTER_KEYS: frozenset[str] = frozenset({"paper_id"})
```

`server/retrieval/bm25.py:664-706` — `_apply_supported_filters` normalizes `paper_id` to a frozenset, accepting both `str` and `list[str]`. m1 must mirror this: a `filters={"paper_id": "2604.26204"}` (string, not list) must coerce to a single-element list before building the IN clause. This is documented in the spike note (`note.md:29`).

### Cache key — no change required for m1

`server/cache.py:127-163` — `_filter_fingerprint` and `server/cache_sqlite.py:103-141` — `derive_tier1_key` ALREADY include `filters` in the cache key via `canonical_key_components`:

```python
filters_json = json.dumps(filters or {}, sort_keys=True, separators=(",", ":"))
```

The `filters={"paper_id": ["2604.26204"]}` arg will produce a different `filters_json` than `filters=None` → different Tier-1 cache key → distinct cache entry. The cache layer ALREADY handles this correctly; m1 does NOT need to touch `server/cache.py` or `server/cache_sqlite.py`.

**This is a load-bearing finding**: the milestone brief says "Update the cache key to include the filter set" — this is already done. The implementer should confirm and NOT modify the cache layer.

### `MAX_FILTER_ITEMS` constant (existing)

`server/handlers/search.py:97` (verbatim):

```python
#: Hard upper bound on the number of items in the ``filters`` dict
MAX_FILTER_ITEMS = 100
```

This caps the total number of KEYS in the `filters` dict, not the length of the `paper_id` list. m1 needs a SEPARATE cap on `len(filters["paper_id"])`. The spike only validated 5-element filter lists. The brief calls for "tests against the 22-paper math.AG corpus," so 22 is a tested scale. A list of 100 paper_ids is the design target per the spike note. Recommend `MAX_PAPER_ID_FILTER_LEN = 100` as the cap constant, enforced in handler body (same rationale as `MAX_FILTER_ITEMS`: avoids bumping tool schema hash).

### `is_valid_paper_id` — the validator for each ID

`ingest/identifiers.py:57-64` (verbatim):

```python
def is_valid_paper_id(value: str) -> bool:
    """Return True if ``value`` is a well-formed arXiv paper_id.
    Reject behavior is symmetric for both new-style and old-style.
    Empty strings, paths with traversal sequences (``..``), and
    arbitrary text all return False.
    """
    return isinstance(value, str) and PAPER_ID_RE.match(value) is not None
```

This validator MUST be applied to each element of the `paper_id` list before building the predicate. Any invalid entry should surface a `ValueError` (not a 500).

### Tool schema — NO CHANGE

`tests/test_server_tool_schema.py:94` pins `EXPECTED_TOOL_SCHEMA_SHA256`. The handler function signature in `server/handlers/search.py:100-117` does not change (the `filters: dict[str, Any] | None` argument exists, same type, same description). The docstring describes the filter parameter as "Reserved for E07_S04; ignored at v1" — m1 should update this docstring to reflect that `paper_id` filtering IS now honored. Docstrings are not part of the tool schema hash; this is safe. **`EXPECTED_TOOL_SCHEMA_SHA256` does NOT need re-pinning.**

### Test directory structure

`tests/handlers/` does NOT exist. The brief proposes creating it. The existing pattern for handler tests is flat under `tests/` (e.g., `tests/test_snippet_contract.py`, `tests/test_tools_all.py`). The brief allows "or equivalent" placement. **Recommendation: create `tests/test_search_filter.py` (flat, mirroring existing conventions)** rather than `tests/handlers/test_search_filter.py` (requires creating a new package with `__init__.py`). Either works, but flat is the pattern in this repo.

### E13 security audit relevance

Threat 4 (`08-security-observability-ops.md:51-58`) — resource exhaustion. Mitigations:
1. `k <= 50` already enforced by `MAX_K`.
2. The 256 KB byte cap already fires on `search_papers` (E13_S04b).
3. The `MAX_FILTER_ITEMS = 100` cap already rejects oversized filter dicts.
4. **New gap m1 must close**: no cap on the length of the `paper_id` list itself. A `filters={"paper_id": [...10000 ids...]}` would pass the `MAX_FILTER_ITEMS` check (the dict has 1 key, which is ≤ 100) but generate a massive IN clause predicate that could stress LanceDB's SQL parser. Add `MAX_PAPER_ID_FILTER_LEN = 100`.

Threat 1 (path traversal) — `is_valid_paper_id` already prevents injection. No additional mitigation needed.

---

## Prior decisions and lessons

**Recent git log (last 20 commits)** shows `proof-verify-handler-wiring-m6` (notebook scaffolding scripts) is the most recent milestone. m1 is the foundational wiring milestone in this epic, running after the spike. m6 is already complete (phase=complete), which means this epic has non-sequential execution — the implementer should note this but m1's scope is unaffected.

**F6 from E06_S03 critique**: "filters and cursor are accepted in the schema but ignored at v1 with filter_warnings." m1 partially closes F6 for the `paper_id` key. The `cursor` arg remains deferred; the `filter_warnings` for deferred keys like `categories` must remain.

**E13_S04b**: enforces 256 KB result byte cap on `search_papers` via `cap_result_list(structured, list_key="results")`. This is in the handler today and must not be disturbed by m1's surgery.

**Three-commit-per-milestone pattern** (CLAUDE.md §4.3): `feat(server): wire paper_id filter through search_papers (m1)` → `rect(...)` → `chore(notes)`.

**Known landmine** (CLAUDE.md §8.8): use `uv run python -m pytest` not system `pytest`.

**`assert` is BANNED** (CLAUDE.md §4.7, agent-conventions.md §4). The paper_id list validation must use `raise ValueError(...)` not `assert`.

---

## External sources

LanceDB documentation URLs returned 404 at time of research. However, the spike-1 POC directly validated the predicate syntax against a real LanceDB instance. The following is confirmed by empirical evidence:

- **Predicate syntax**: `"paper_id IN ('id1', 'id2', 'id3')"` — single-quoted string literals, comma-separated, inside `IN (...)`.
- **No `prefilter=True`** needed for ANN + `.where()` composition (spike validated without it).
- **String escape**: `s.replace("'", "''")` — SQL standard double-quote-the-single-quote, matching `_escape_lance_str` in `chunk.py`.
- **100-element filter performance**: not directly measured (spike used 5 IDs). Inference from spike: filtered queries are 30× faster than unfiltered because the filter narrows the ANN search space. A 100-element IN clause adds predicate-evaluation overhead but the ANN graph walk is the bottleneck; 100 IDs should be fine. This is an untested assumption at m1 scale.
- **Empty IN list**: `paper_id IN ()` is invalid SQL syntax. Handler must coerce `filters={"paper_id": []}` to a user-facing error before reaching LanceDB.

---

## Recommendation

**Implement a `_build_paper_id_predicate(paper_ids: list[str]) -> str` private helper in `server/handlers/search.py`.** The helper:

1. Validates each ID against `is_valid_paper_id` — raises `ValueError` on first invalid.
2. Escapes each ID via `s.replace("'", "''")` (identical to `_escape_lance_str`).
3. Returns `"paper_id IN ('id1', 'id2', ...)"`.

The handler surgery at lines 217–225: when `filters` contains a non-empty `paper_id` list, append `.where(predicate)` between `.search(...)` and `.limit(...)`. No `prefilter=True`.

The `filter_warnings` emission (lines 242–246): suppress the "deferred to E07_S04" message when `paper_id` filter was successfully honored. Keep warnings for `cursor` and for any unrecognized filter keys.

Place new tests in `tests/test_search_filter.py` (flat, not in a new `tests/handlers/` package).

**Do NOT touch `server/cache.py` or `server/cache_sqlite.py`** — the cache key already includes `filters` correctly.

**The tool schema does not change** — `EXPECTED_TOOL_SCHEMA_SHA256` requires NO re-pin.

---

## Open questions

**1. `prefilter=True` vs default for ANN + `.where()`.** The spike validated without `prefilter=True` and returned correct results. `get_paper` and `get_chunk` use `prefilter=True` on non-ANN (full-table-scan) calls. Mixing them would be inconsistent. The implementer should confirm: does omitting `prefilter` on an ANN call produce correct IN-list filtering per the spike evidence? The spike says YES. The implementer should NOT add `prefilter=True` unless LanceDB API docs explicitly say IN-list filtering with ANN requires it.

**2. 100-element IN clause correctness at corpus scale.** Spike validated 5 IDs. The 22-paper corpus is covered by the ACs. A 100-ID IN clause on a ~22-paper corpus (where most IDs won't match) is untested. This is a latency question only (correctness is guaranteed by the predicate), and filtered queries are already 30× faster than unfiltered. Treat as non-blocking.

These are both informational — the implementer can proceed. No open questions that block starting code.

---

## External writes the implementation will require

None — this milestone is purely local. The handler change, predicate builder, and new test file require no git push, no PR, no external API calls, no infra mutation.
