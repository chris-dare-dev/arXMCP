# E09_S03 Implementation Summary

**Milestone:** `cite_neighbors(chunk_id, depth, direction)` graph
traversal + intra-paper `\ref{}` ingest pass.
**Path:** inline (orchestrator, main session).
**Date:** 2026-05-10.

## One-line summary

Added `server/graph_queries.py::cite_neighbors` (async) backed by
Kùzu's variable-length-path Cypher with Python-side dedup + filter +
LanceDB chunk-id lookup; added `ingest/intra_paper_refs.py` for the
`\ref{}` self-edge ingest pass; exported `paper_id_from_chunk_id`
from `ingest/identifiers.py`. 41 new tests, full suite green.

## Commit range

`e5ecbee..<head>` — single feat commit.

## Acceptance criteria status

| AC | Status | Evidence |
|---|---|---|
| #1 `depth=1, direction="cites"` returns direct citation neighbors | met | `tests/test_graph_queries.py::TestCiteNeighborsCites::test_depth_1_returns_direct_outgoing` (B and C from A's outgoing edges). |
| #2 `depth=2` returns hop-1 + hop-2 with correct `hop_distance` | met | `::test_depth_2_returns_hop1_and_hop2` (A→B→D and A→C→D both yield hop=2 D; B and C remain hop=1). |
| #3 `direction="cited_by"` returns incoming edges | met | `TestCiteNeighborsCitedBy::test_cited_by_returns_incoming_edges` (E→A; E appears with edge_kind="cited_by"). |
| #4 `direction="depends_on"` returns intra-paper `\ref{}` chain results | met | `TestCiteNeighborsDependsOn::test_depends_on_includes_intra_paper_self_loop` (A's intra-paper self-loop returns A with edge_kind="ref"; cross-paper fallback also reaches B and C). |
| #5 Results capped at `max_results=50` | met | `TestMaxResultsAndChunkIdNone::test_max_results_caps_returned_count` + `test_default_max_results_is_50`. Cap applied AFTER dedup + filter so distinct papers aren't silently dropped. |
| #6 Each result includes the full dataclass shape | met | `TestResultShape::test_each_result_includes_all_fields` exercises every field. |
| #7 Papers in graph but not in chunked corpus return `chunk_id=None` | met | `TestMaxResultsAndChunkIdNone::test_chunk_id_none_when_lancedb_path_none`. The dataclass field is `str \| None` (deviation from brief — see below). |
| #8 Unit test passes on a 5-paper fixture graph with known edges | met | The `kuzu_db` fixture builds a 5-paper graph (A,B,C,D,E) with 6 edges including the intra-paper self-loop; every test in `tests/test_graph_queries.py` runs against it. |

**Net AC status: 8/8 met.**

## New / changed files

| Path | Lines (rough) | What |
|---|---|---|
| [server/graph_types.py](server/graph_types.py) | ~50 | New module: `CitationNeighbor` frozen dataclass with `chunk_id: str \| None`, `paper_id`, `edge_kind`, `hop_distance`, `source`, `confidence`. Lifted out of `graph_queries.py` so a future MCP-tool wrapper can import the type without pulling the Kùzu read path. |
| [server/graph_queries.py](server/graph_queries.py) | ~290 | New async module. `cite_neighbors(chunk_id, depth, direction, max_results, kuzudb_path, lancedb_path)` async function. Helpers: `_build_query`, `_execute_traversal`, `_row_passes_direction_filter`, `_result_source`, `_edge_kind_for_result`, `_lookup_chunk_ids_for_papers`. Uses `relationships(p)` projection (verified live in Kùzu 0.11.3) for per-hop edge metadata. |
| [ingest/intra_paper_refs.py](ingest/intra_paper_refs.py) | ~430 | New ingest module: scans LaTeXML HTML for `<a class="ltx_ref" href="#<label>">`, validates labels against `theorem_label` in LanceDB chunks, emits one `(P)-[:cites {source: "intra-paper", confidence: 1.0}]->(P)` self-edge per paper with at least one resolved label. CLI with checkpoint discipline mirroring E09_S01/S02. |
| [ingest/identifiers.py](ingest/identifiers.py) | +30 | New `paper_id_from_chunk_id(chunk_id) -> str` helper. Single source of truth for the chunk_id-to-paper_id parse; raises `ValueError` on malformed input. |
| [tests/test_graph_queries.py](tests/test_graph_queries.py) | ~280 (29 tests) | Query builder, direction filter, all 4 directions × 2 depths happy path, dedup, ordering, max_results, chunk_id None fallback, input validation, identifier helper. |
| [tests/test_intra_paper_refs.py](tests/test_intra_paper_refs.py) | ~250 (12 tests) | Extractor, label resolution, full ingest happy path, idempotent re-run, missing-HTML failure tracking, atomic checkpoint, paper_id validation. |

No edits to existing modules beyond `ingest/identifiers.py` (additive
`paper_id_from_chunk_id`).

## Test count delta

- Before: 1253 passed, 4 skipped.
- After: **1294 passed, 4 skipped** (+41 new tests).
- `ruff check .`: clean.

## Deviations from the brief

The brief was followed with these documented exceptions:

1. **`kuzudb_path` default**. Brief signature uses
   `var/arxmcp/index/kuzudb/`. Implementation uses
   `var/arxmcp/index/kuzu/` (matches Makefile bootstrap, the two
   relevant design notes, AND E09_S01/S02 shipped code — same drift
   resolved the same way three times now). Documented in the
   module docstring.
2. **`CitationNeighbor.chunk_id` type**. Brief signature shows
   `chunk_id: str` but the AC explicitly says "Papers in the graph
   but not in the chunked corpus return `chunk_id=None`." The
   dataclass declares `chunk_id: str | None` (the typed truth). Both
   researchers flagged this as a brief inconsistency; pin in the
   dataclass docstring.
3. **`source` field is the LAST edge in the path** (not the first).
   The brief's `CitationNeighbor.source` field is annotated "from
   the cites rel table" but doesn't specify which hop's source for
   depth=2 paths. The implementation uses the LAST edge (closest to
   the result paper), which is symmetric across `cites`/`cited_by`
   directions. Documented in the module docstring.
4. **`max_results` cap applied in Python, not Cypher**. The
   synthesis recommended Cypher-side `LIMIT` but the cap MUST be
   applied AFTER dedup + direction filter — applying it earlier
   silently drops distinct papers. Python-side is the correct
   place; the perf cost is negligible at Tier-3 scale.
5. **`kind="stmt"` priority list fallback**. The brief says
   "first `kind="stmt"` chunk" but some math papers (especially
   expository) have only `kind="lemma"` / `"definition"` chunks.
   Implementation uses a priority list (`stmt > lemma >
   proposition > corollary > definition > remark`); falls back to
   `chunk_id=None` only when no theorem-kind chunk exists. R2's
   recommendation; documented in the helper docstring.
6. **Intra-paper edges are paper-level self-edges**, not
   chunk-level. The Kùzu schema only has `papers` nodes (no chunk
   nodes), so the intra-paper edge model is necessarily
   `(P)-[:cites {source: "intra-paper"}]->(P)`. The
   `cite_neighbors(direction="depends_on")` query surfaces this as
   "this paper has intra-paper deps"; chunk-level info is recovered
   by inspecting the chunk HTML. Documented in
   `ingest/intra_paper_refs.py`'s module docstring.

## Implementation choices for Phase 3 to scrutinize

These are choices I made where I expect the adversary to push back:

1. **`relationships(p)` projection** trusted to work in Kùzu 0.11.3.
   Verified live before commit, but a future Kùzu version (or fork
   migration) could break this. The two-query fallback (depth=1 +
   depth=2-only) mentioned in the synthesis is the documented
   alternative if this ever fails.
2. **`source` field for depth=2 path** is the LAST edge's source.
   Could equally be the FIRST. Pick is documented; a future caller
   wanting per-hop visibility would need to call back with depth=1
   from each intermediate paper.
3. **Self-loop filtering for `cites`/`cited_by`** is post-Cypher
   in Python (`if neighbor_paper_id == source_paper_id: skip`). A
   pure-Cypher `WHERE n.paper_id <> $paper_id` would be cleaner but
   fails to handle the depth=2 case where A→A→B should NOT be
   excluded (B is a real neighbor reachable via the self-loop). The
   current implementation correctly handles this because the
   self-loop excluding only fires when the RESULT paper equals the
   source paper.
4. **Confidence=1.0 for intra-paper edges**. Synthesis recommended
   1.0 (curated content); a future critic might argue 0.5 (static
   analysis lower confidence). Documented in
   `ingest/intra_paper_refs.py`'s module docstring.
5. **Single self-edge per paper, regardless of how many intra-paper
   refs exist**. The graph stores "paper P has intra-paper deps"
   as a binary signal; downstream agents recover chunk-level info
   from the chunk content. A schema with chunk nodes would be
   richer but is out of scope (would require schema v3).
6. **`async def cite_neighbors` with `asyncio.to_thread`** wrapping
   the sync Kùzu calls. Matches the `server/handlers/*` async
   convention; the sync Kùzu call is short enough that the
   thread-pool hop is acceptable overhead. A pure-sync function
   would also be defensible.
7. **No new conftest autouse fixture**. The two new modules accept
   their paths as arguments rather than relying on module-level
   path constants, so the autouse-redirect pattern doesn't apply.
   Tests pass `tmp_path`-derived paths directly.

## External writes the orchestrator must authorize (Phase 4 gate)

| type | target | why | blocking? |
|---|---|---|---|
| Code edits | `server/graph_queries.py`, `server/graph_types.py`, `ingest/intra_paper_refs.py`, `ingest/identifiers.py`, `tests/test_graph_queries.py`, `tests/test_intra_paper_refs.py` | landed in this commit | no |
| Filesystem write (operator-only) | `var/arxmcp/index/kuzu/` (intra-paper edges) | gitignored; tests use `tmp_path` | no |
| Filesystem write (operator-only) | `var/arxmcp/ops/intra-paper-refs-checkpoint.json` | gitignored | no |
| `git push` | remote | not required by milestone; per-event authorization | no |

**No HTTP calls.** No new runtime dependencies (BeautifulSoup is
already a dep from E02).

## F-finding inheritance from E09_S01/S02 (not re-introduced)

| ref | applied here? |
|---|---|
| F1 (CLI casing) | N/A — `intra_paper_refs` CLI has no `--source` flag (single source, no need for the validator). |
| F2 (response cap) | N/A — no HTTP. Local file size cap (`MAX_HTML_BYTES = 50 MiB`) for parsed HTML. |
| F3 (fetch failure tracking) | applied to parse failures — `state["parse_failures"]` list, non-zero CLI exit, atomic checkpoint. |
| F4 (multi-source-write) | not applicable — intra-paper writes ONLY to `cites` rel, never to `papers` columns. |
| F5 (seed reader) | CLI's `--seed-file` path uses `tools.fetch_seed.read_seed_list`. |
| F6 (schema version) | NO schema mutation — intra-paper edges fit the v2 schema. `KUZU_SCHEMA_VERSION` stays at 2. |
| F7 (atomic fs) | reuses `graph_ingest.save_checkpoint`. |
| F8 (collision detection) | N/A — no external IDs to collide on. |
| F10 (non-vacuous tests) | every assertion is non-vacuous. |

## Open follow-ups (not in this milestone)

- The MCP-tool wrapper exposing `cite_neighbors` on `tools/list`
  lands in E06_S04 / E09_S04. The dataclass shape and the function
  signature are stable; the wrapper just needs to wire pydantic
  validation + the Resources / Config plumbing.
- The path-name drift (brief `kuzudb/` vs constitution `kuzu/`) is
  documented for the third milestone in a row. A docs PR could
  edit the brief; not required.
- The intra-paper edge model could be extended to chunk-level nodes
  in a future schema v3. Out of scope.
- The `confidence` for intra-paper edges (1.0) could be reconsidered
  if a downstream consumer wants source-rank ordering.
