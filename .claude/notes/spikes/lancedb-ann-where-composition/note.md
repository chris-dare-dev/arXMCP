# Spike-1: LanceDB ANN + scalar-predicate composition — note

**Date:** 2026-05-21
**Question:** Does `chunks_table.search(qv, vector_column_name="embedding_stmt").where("paper_id IN (...)").limit(N).to_arrow()` return results that are (a) all within the filter set, (b) ranked sensibly within that set?

This is the [MUST] assumption from REFINE that m1's surgery depends on. The pattern is shipped for BM25 (`server/retrieval/bm25.py:670-687`) but never exercised on the ANN call path used by `search_papers`.

## Verdict

**YES** — LanceDB's ANN search composes correctly with `.where("paper_id IN (...)")`. m1 can proceed with this API shape; no fallback to a post-hoc filter pattern is needed.

## Evidence

Against the bridgeland-stability notebook (39 papers), with `filter = {0705.3794, 0712.1083, 1106.3430, 1607.08199, 2412.08531}` and query "Bridgeland's original definition of a stability condition on a triangulated category":

| check | result |
|---|---|
| 10/10 returned chunks have `paper_id` in the filter set | ✓ |
| Top-1 paper matches the unfiltered top-1 (`0705.3794`, the foundational paper) | ✓ |
| Top-2..7 dominated by `0712.1083` (Bayer polynomial stability — most relevant non-foundational paper in filter) | ✓ |
| Latency per filtered query | **~1.5 ms** (30× faster than unfiltered ~50ms — filter shrinks ANN search space) |
| Predicate syntax accepted | `paper_id IN ('a', 'b', 'c')` works as-is via LanceDB's SQL-ish predicate language |

## Implications for m1

- **API shape for the handler change is:** `chunks_table.search(qv, vector_column_name="embedding_stmt").where(predicate).limit(k*5).to_arrow()`. Append `.where(...)` between `.search(...)` and `.limit(...)`.
- **Predicate format:** `"paper_id IN ('id1', 'id2', ...)"` with single-quoted string literals. Need a small predicate builder that escapes single quotes (paper IDs don't naturally contain them, but defensive validation is required — security-reviewer's concern).
- **Empty-list edge case:** `filters={"paper_id": []}` should error or be coerced to `filters=None`, NOT passed as `paper_id IN ()` (LanceDB likely errors on empty IN; need defensive handling).
- **Single-id edge case:** `filters={"paper_id": "2604.26204"}` (string, not list) is supported by BM25Phase per its `_apply_supported_filters` impl — m1 should mirror that (coerce string to single-element list).
- **Latency win is a bonus:** because the filter narrows the ANN search space, filtered queries are FASTER than unfiltered. m1 has no latency-regression risk on the filter path.

## What this does NOT prove

- Behavior under malicious predicates (SQL-injection-style). Defensive validation at the handler boundary is m1's responsibility, not the spike's.
- Behavior with filter sets of 100+ paper_ids (notebook scale). The 5-paper filter is the spike fixture; 100-paper filter performance should be similar but isn't measured here.
- Composition with cursor pagination (`server/handlers/search.py:113-116` reserves `cursor` arg). Deferred — `cursor` is also unwired today.

## Reproducibility

```
ARXMCP_LANCEDB_PATH=var/arxmcp/notebooks/bridgeland-stability/lancedb \
  uv run python .claude/notes/spikes/lancedb-ann-where-composition/poc.py
```
