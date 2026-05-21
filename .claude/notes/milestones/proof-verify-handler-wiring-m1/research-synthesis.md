# Research Synthesis — proof-verify-handler-wiring-m1

**Generated:** 2026-05-21
**Mode:** standard (2 researchers)
**Briefs merged:** `research-brief-1.md`, `research-brief-2.md`

---

## What's getting built (single-sentence)

Replace the dropped-filter behavior in `server/handlers/search.py:217-225` with a `chunks_table.search(query_vec, ...).where(predicate, prefilter=True).limit(...)` call when `filters` contains a non-empty `paper_id` list. Add input validation (per-element `is_valid_paper_id`, list-length cap, single-quote escape as defense-in-depth) + tests. No cache changes, no tool input-schema changes, no Pydantic constraint changes.

## Load-bearing constraints (verbatim)

From `server/handlers/search.py:217-225` (the surgery target):
```python
with span_ann(k=k):
    arrow = (
        r.chunks_table.search(query_vec, vector_column_name="embedding_stmt")
        .limit(k * 5 if level != "theorem" else k)  # over-fetch for dedup
        .to_arrow()
    )
```

From `server/handlers/search.py:243-246` (the warning that must be REMOVED only when paper_id IS honored):
```python
if filters:
    filter_warnings.append(
        "filters arg is accepted but not yet processed (deferred to E07_S04)"
    )
```

From `server/retrieval/bm25.py:117` (the established `paper_id` filter contract m1 mirrors):
```python
SUPPORTED_FILTER_KEYS: frozenset[str] = frozenset({"paper_id"})
```

From `ingest/identifiers.py:57-64` (the validator for each element):
```python
def is_valid_paper_id(value: str) -> bool:
    """Return True if ``value`` is a well-formed arXiv paper_id."""
    return isinstance(value, str) and PAPER_ID_RE.match(value) is not None
```

From `ingest/index_definitions.py:404-405` (why string concatenation + escape is the only option):
> "LanceDB does not accept bound parameters for predicates today."

From `CLAUDE.md §4.7`:
> "`assert` is BANNED for invariants — Python `-O` strips them. Use `if … raise RuntimeError(…)` instead."

From `server/handlers/search.py:88-97` (the existing handler-body cap pattern — m1 mirrors this for `MAX_PAPER_ID_FILTER_ITEMS`):
> "Hard upper bound on the number of items in the `filters` dict (E13_S04 Threat 4 resource-exhaustion defense). Enforced via handler-body validation rather than Pydantic `Field(max_length=...)` so the constraint does NOT bump the rendered tool schema and trigger `EXPECTED_TOOL_SCHEMA_SHA256` re-pin per `.claude/notes/07-multi-agent-caching.md` BP1 byte-stability discipline."

## Resolved disagreements

### Disagreement 1: `prefilter=True` vs default for ANN + `.where()` — **PREFILTER=TRUE wins**

- **R-1 position:** Do NOT add `prefilter=True`. The spike-1 POC validated without it; 10/10 results in the filter set. Adding `prefilter=True` may change behavior.
- **R-2 position:** USE `prefilter=True`. Consistent with `get_paper`, `get_chunk`, `ingest/index_theorem_names.py:132`, `ingest/intra_paper_refs.py:226`. Without it, ANN may retrieve k corpus-wide candidates first and then discard those not in the filter set, returning fewer than k results from the filtered sub-corpus.

**Resolution: R-2 wins. Use `prefilter=True`.** Three reasons:
1. **Semantics safety:** with default behavior on a small filter set (e.g. 2 paper_ids), postfilter could return 0-2 results when k=10 and the filter set has many more relevant chunks. `prefilter=True` guarantees the ANN runs over the filtered sub-corpus first.
2. **Codebase convention:** every other production callsite using ANN + scalar predicate uses `prefilter=True`. Drifting from convention is a smell.
3. **Spike-1 didn't disprove `prefilter=True`:** the spike's filter (5 papers / 39 corpus) was large enough that postfilter behavior wasn't a discriminating test. The fact that 10/10 results were in the filter set is consistent with EITHER prefilter or postfilter-with-over-fetch — doesn't pin which one ran.

The spike's documented 1.5ms latency is preserved either way; `prefilter=True` doesn't slow down a filtered ANN call (in fact, it can speed it up by narrowing the search space).

### Disagreement 2: Cache key change — **AGREED: no change needed**

Both briefs independently verified that `server/cache.py:127-163` (`_filter_fingerprint`) and `server/cache_sqlite.py:103-141` (`derive_tier1_key`) ALREADY include `filters` in the cache key via `canonical_key_components`:

```python
filters_json = json.dumps(filters or {}, sort_keys=True, separators=(",", ":"))
```

**The roadmap brief's instruction "Update the cache key to include the filter set" is misleading — that work is already done.** m1 must NOT touch `server/cache.py` or `server/cache_sqlite.py`. Add a regression test asserting two same-`(query, k, level)` calls with different `filters` produce distinct cache entries.

### Disagreement 3: Test file location — **AGREED: flat `tests/test_search_filter.py`**

R-1 explicitly recommends flat; R-2 doesn't specify but the existing handler-test pattern is flat (`tests/test_snippet_contract.py`, `tests/test_tools_all.py`, etc.). The brief's `tests/handlers/test_search_filter.py` is "or equivalent" — flat is the established convention. **Use `tests/test_search_filter.py`.** Avoids creating a new `tests/handlers/` package + `__init__.py`.

### Disagreement 4: `_escape_sql` import vs local — **LOCAL helper in search.py**

The single-quote escape (`s.replace("'", "''")`) is defined three times in the codebase:
- `server/handlers/chunk.py:144-146` as `_escape_lance_str`
- `server/handlers/paper.py:122-123` as `_escape`
- `ingest/intra_paper_refs.py:253-255` as `_escape_sql`
- `server/graph_queries.py:292-295` as `_escape_sql`

m1 defines `_escape_paper_id_literal` locally in `server/handlers/search.py`. Promoting to a shared utility (e.g. `ingest/identifiers.py`) is OUT OF SCOPE — that's its own milestone. The local helper avoids cross-module import smells (handler depending on `graph_queries` or `chunk`).

## Failure modes the implementation must cover (R-2's 9, condensed)

The implementation MUST defend against each. Tests MUST cover at least items 1, 2, 3, 4, 5, 6, 7, 9.

1. **Predicate injection via malformed paper_id** — `is_valid_paper_id` regex (validate FIRST) + `replace("'", "''")` (escape ALWAYS). Defense-in-depth; layered.
2. **Empty paper_id list** — `filters={"paper_id": []}` MUST raise `ValueError`. Do NOT silently coerce to `filters=None`. AC #3 says "clear error via the result envelope, not a 500."
3. **String instead of list** — `filters={"paper_id": "2604.26204"}` MUST coerce to `["2604.26204"]` per BM25Phase's pattern at `server/retrieval/bm25.py:683-687`.
4. **Oversized list** — introduce `MAX_PAPER_ID_FILTER_ITEMS = 100` constant in `search.py`. Reject `len > 100` with `ValueError` in handler body (NOT as Pydantic constraint — would re-pin BP1 hash).
5. **All paper_ids invalid** — if ANY element fails `is_valid_paper_id`, raise `ValueError` naming the first bad element. Do NOT silently drop bad elements and proceed with a partial filter (hides LLM bugs).
6. **Cache key collision** — already handled by `canonical_key_components`. Regression test required: two same-`(query, k, level)` calls with different filter sets produce distinct cache entries.
7. **paper_ids not in corpus** — `paper_id IN ('aaaa.bbbb')` returns empty Arrow table; handler returns `{"results": [], ...}`. No error. Test that this works.
8. **`prefilter=True` semantics** — resolved above; use it.
9. **`filter_warnings` removal scoped to honored keys only** — remove the "deferred to E07_S04" message ONLY for `paper_id` when honored. Keep it (or equivalent) for `cursor` and any other unrecognized key in the filter dict.

## Test surface (acceptance criteria + failure modes)

New file: `tests/test_search_filter.py`. All tests use `tmp_path` fixtures + a synthetic LanceDB or mock the `chunks_table.search().where()` chain. The Tier-1 / Tier-2 cache tests can use the cache modules directly.

Required test cases:
- `test_filter_paper_id_list_scopes_results` — AC #1; filter `[a, b]` → every result's paper_id ∈ `{a, b}`.
- `test_no_filter_byte_identical_to_pre_m1` — AC #2; `filters=None` produces same Arrow shape as the pre-m1 dense-only path.
- `test_filter_string_coerced_to_list` — FM-3; `filters={"paper_id": "x"}` works same as `filters={"paper_id": ["x"]}`.
- `test_filter_empty_list_raises_value_error` — FM-2 / AC #3.
- `test_filter_malformed_paper_id_raises_value_error` — FM-5 / AC #3.
- `test_filter_oversized_list_raises_value_error` — FM-4; > `MAX_PAPER_ID_FILTER_ITEMS` items.
- `test_filter_injection_via_quote_escaped_at_two_layers` — FM-1; even bypassing the regex, the escape neutralizes.
- `test_filter_unknown_keys_still_warned` — FM-9; `filters={"paper_id": ["x"], "year": 2024}` keeps a warning for `year` while honoring `paper_id`.
- `test_filter_cache_key_distinct_per_filter_set` — FM-6; same query, different filter sets → distinct Tier-1 keys.
- `test_filter_nonexistent_paper_id_returns_empty` — FM-7; valid-format paper_id not in corpus → empty results, no error.
- `test_tool_schema_hash_unchanged` — AC #4; `EXPECTED_TOOL_SCHEMA_SHA256` from `tests/test_server_tool_schema.py` still passes (cross-import or duplicate the assertion).

## Implementation sketch (the actual surgery)

1. **Add constants near `MAX_FILTER_ITEMS` at `server/handlers/search.py:97`:**
   ```python
   MAX_PAPER_ID_FILTER_ITEMS = 100
   ```

2. **Add private helpers (after `SNIPPET_MAX_CHARS` at line 86):**
   ```python
   def _escape_paper_id_literal(s: str) -> str:
       return s.replace("'", "''")

   def _build_paper_id_predicate(paper_id_value):
       # Coerce str → [str]; validate; cap; escape; build IN clause.
       if isinstance(paper_id_value, str):
           paper_ids = [paper_id_value]
       elif isinstance(paper_id_value, list):
           paper_ids = paper_id_value
       else:
           raise ValueError(f"filters['paper_id'] must be str or list, got {type(paper_id_value).__name__}")
       if not paper_ids:
           raise ValueError("filters['paper_id'] must not be empty; use filters=None for no filter")
       if len(paper_ids) > MAX_PAPER_ID_FILTER_ITEMS:
           raise ValueError(f"filters['paper_id'] has {len(paper_ids)} items; max allowed is {MAX_PAPER_ID_FILTER_ITEMS}")
       invalid = [pid for pid in paper_ids if not is_valid_paper_id(pid)]
       if invalid:
           raise ValueError(f"filters['paper_id'] contains {len(invalid)} invalid arXiv IDs; first: {invalid[0]!r}")
       ids_csv = ",".join(f"'{_escape_paper_id_literal(pid)}'" for pid in sorted(paper_ids))
       return f"paper_id IN ({ids_csv})"
   ```

3. **In `handle_search_papers`, before the ANN call at line 217:**
   ```python
   paper_id_predicate = None
   if filters and "paper_id" in filters:
       paper_id_predicate = _build_paper_id_predicate(filters["paper_id"])
   ```

4. **Modify the ANN call at lines 217-225 to conditionally chain `.where()`:**
   ```python
   with span_ann(k=k):
       search_q = r.chunks_table.search(query_vec, vector_column_name="embedding_stmt")
       if paper_id_predicate is not None:
           search_q = search_q.where(paper_id_predicate, prefilter=True)
       arrow = search_q.limit(k * 5 if level != "theorem" else k).to_arrow()
   ```

5. **Update the `filter_warnings` block at lines 242-246:**
   - Remove the blanket "deferred to E07_S04" message.
   - Instead, surface warnings for unrecognized keys (mirror BM25Phase's `DEFERRED_FILTER_KEYS` pattern at `server/retrieval/bm25.py:119-125`).
   - If `paper_id` was the only filter key and it was honored, `filter_warnings` is empty.

6. **Update the handler docstring** to reflect that `paper_id` filtering is now honored (the brief argued for the deferred-message removal). Docstrings are not part of `EXPECTED_TOOL_SCHEMA_SHA256`.

## Implementation order (recommended)

1. Add helpers (`_escape_paper_id_literal`, `_build_paper_id_predicate`) + `MAX_PAPER_ID_FILTER_ITEMS` constant + module-level imports for `is_valid_paper_id`.
2. Wire the helper into the ANN call path with `.where(predicate, prefilter=True)`.
3. Update `filter_warnings` block (remove blanket message, surface unknown-key warnings).
4. Update handler docstring.
5. Write tests in `tests/test_search_filter.py` co-developed with each piece, NOT batched at the end.

Estimated LOC: ~80 in `search.py` + ~300 in `tests/test_search_filter.py` = ~380 LOC. Under the INLINE-path threshold (< 500 LOC + < 5 files). One handler file modified, one new test file. Recommended path: **INLINE** (no worktree implementer).

## Orchestrator synthesis note

Both researchers independently caught:
- The cache layer ALREADY handles filters correctly; the brief's "Update the cache key" instruction is misleading.
- `EXPECTED_TOOL_SCHEMA_SHA256` does NOT need re-pinning (handler-body validation, not Pydantic).
- `MAX_FILTER_ITEMS = 100` is a dict-key cap, not a list-length cap; m1 needs a separate `MAX_PAPER_ID_FILTER_ITEMS`.

The single meaningful divergence (`prefilter=True` or not) is resolved in favor of `prefilter=True` for semantics safety + codebase convention. The implementer should NOT trust the spike's empirical evidence to override the safer default.

## Open questions (orchestrator-resolved)

All open questions from both briefs are resolved in the disagreements section above. No blockers for implementation.

## External writes the implementation will require

None — purely local. Handler change + tests; no git push, no PR, no infra mutation, no third-party API calls. Phase 4 has no external-write authorizations to gate.
