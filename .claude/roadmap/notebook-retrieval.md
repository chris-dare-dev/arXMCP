# notebook-retrieval — Make per-notebook chunks queryable through the MCP server

**Owner:** Chris Dare
**Created:** 2026-05-28
**Status:** scoped
**Source:** discovered while researching notebook-cutover-m1 — the MCP server never reads per-notebook lancedb

**Supersedes/absorbs:** `notebook-cutover-m1` (parked at research-complete).
That milestone's value ("advance the per-notebook active lancedb") only
matters once the server actually QUERIES per-notebook lancedb — which is
what THIS milestone delivers. Cutover becomes a natural sub-need here.

**The gap (verified by code-read during notebook-cutover-m1 research):**

- `server/config.py:97`: `lancedb_path = Path("var/arxmcp/index/lancedb")`
  — the retrieval substrate is the SHARED corpus only.
- `server/handlers/search.py:384`: `search_papers` calls `get_resources()`,
  which opens `config.lancedb_path`. No per-notebook path is consulted.
- The shared corpus `var/arxmcp/index/lancedb` is **empty** (no `chunks`
  table). The notebook papers (53 in bridgeland-stability, 12+ in
  shimura-varieties) live in `var/arxmcp/notebooks/<slug>/lancedb/`.
- `server/tools.py:174-177` documents notebook scoping via
  `filters={'paper_id': [...]}` — but that mechanism assumes every paper
  is in the ONE shared corpus. With the shared corpus empty and papers
  isolated per-notebook, **a `search_papers` call returns nothing for any
  notebook paper today.** All the ingest / embedding / preamble work is
  currently un-queryable through the MCP server.

**The core tension to resolve in research:** the design notes pull two ways.
`textbook-ingest-roadmap.md` mandates "textbook chunks live ONLY in
`var/arxmcp/notebooks/<slug>/lancedb/`" (per-notebook isolation), while the
shipped `search_papers` retrieval assumes a single shared corpus scoped by
`filters.paper_id`. Reconciling these is the heart of this milestone.

---

### notebook-retrieval-m1 — First vertical slice: one notebook queryable end-to-end

**Description.** Make a single notebook's chunks retrievable through the
MCP `search_papers` tool, opening the notebook's own
`var/arxmcp/notebooks/<slug>/lancedb/` as the retrieval substrate when a
notebook is selected. Deliver the full BM25 → ANN → RRF → rerank pipeline
against the notebook corpus, returning ranked chunk results with the same
envelope shape as a shared-corpus query. Demo target: a `search_papers`
call scoped to `bridgeland-stability` returns relevant chunks from the 53
ingested papers (e.g. the `bridge-q1` "Bridgeland's original definition"
query from `var/arxmcp/notebooks/bridgeland-stability/queries.json` surfaces
`0705.3794`).

**Design forks for the research phase to resolve (these are the
load-bearing decisions; pick with evidence, do not average):**

1. **Notebook selection mechanism.** Three candidates:
   - **(A) `filters.notebook=<slug>`** on `search_papers`. ATTRACTIVE IF
     `filters` is typed as a free-form `dict` (then adding a `notebook`
     key needs NO inputSchema change → **no `EXPECTED_TOOL_SCHEMA_SHA256`
     re-pin, no BP1 cache invalidation**). Research MUST verify the
     `filters` arg type in the `search_papers` handler signature. This is
     the recommended starting position IF the no-re-pin property holds.
   - **(B) Session-bound notebook** — `Mcp-Session-Id` → notebook mapping
     in `SessionState` (`server/session.py`), set via a header or a small
     new tool. More stateful; a new tool would re-pin BP1.
   - **(C) Server-launch-param** — one notebook per server instance
     (`ARXMCP_NOTEBOOK` env in `server/config.py`). Simplest; inflexible
     (can't query two notebooks from one server). Acceptable for a v1
     single-user slice.
   Research recommends ONE; the synthesis locks it.

2. **Retrieval routing.** `get_resources()` returns a startup-bound
   singleton (`.corpus`, `.bm25`, `.degraded`) pointing at the shared
   corpus. A notebook query needs a Resources-equivalent bound to the
   notebook's lancedb. Options: a per-notebook Resources cache (open +
   memoize per slug), or a request-scoped Corpus open. Research resolves
   the cleanest seam in `server/handlers/search.py` + the Resources
   abstraction (find via `grep -rn "def get_resources\|class Resources"`).

3. **BM25 per-notebook.** BM25 is global + version-keyed
   (`var/arxmcp/index/bm25/v<N>/`), built by `notebook_ingest.py` at the
   notebook's `corpus_version`. The notebook query's BM25 phase must use
   the NOTEBOOK's corpus_version, not the shared corpus's. Research
   confirms how `server/retrieval/bm25.py::BM25Phase` resolves its
   version and whether a notebook query can point it at the right one.

4. **Cache-key isolation.** The 3-tier retrieval cache keys on
   `corpus_version + query + filters + k + level`. Two notebooks could
   collide if their corpus_versions overlap (each notebook's LanceDB
   starts versioning independently). The cache key MUST include the
   notebook identity (slug) so notebook-A's results never serve a
   notebook-B query. Research confirms the current cache key construction
   in `server/cache.py`.

5. **Readiness / degraded-state.** `/readyz` currently gates on the
   shared corpus + BGE-M3 warm. A notebook query against a missing /
   empty notebook lancedb should return a clean empty result or a clear
   error, NOT a 500. Research confirms the degraded-state surface.

**Acceptance criteria (first vertical slice).**

- **[AC1]** Given a `search_papers` call selecting notebook
  `bridgeland-stability` (mechanism per the research-locked fork 1), When
  the query is `"Bridgeland's original definition of a stability condition
  on a triangulated category"`, Then the result rows are drawn from the
  notebook's `lancedb` (not the empty shared corpus) and `0705.3794`
  appears in the top-k. Verified by an integration test against the live
  notebook OR a synthetic notebook fixture (research decides which is
  testable without a real BGE-M3 download).
- **[AC2]** Given a notebook selection, When retrieval runs, Then the full
  BM25 → ANN → RRF → rerank pipeline executes against the notebook corpus
  and the result envelope is byte-shape-identical to a shared-corpus query
  (same fields, snippet contract honored).
- **[AC3]** Given two notebooks with overlapping corpus_versions, When each
  is queried with the same query string, Then the 3-tier cache does NOT
  serve notebook-A's cached payload for a notebook-B query (cache key
  includes notebook identity). Regression test with a synthetic 2-notebook
  cache scenario.
- **[AC4]** Given a `search_papers` call with NO notebook selection, When
  the query runs, Then behavior is byte-identical to today (shared corpus;
  no regression). Snapshot test.
- **[AC5]** Given a notebook selection for a non-existent / empty notebook,
  When queried, Then a clean empty result (or a typed error) is returned,
  NOT a 500 / unhandled exception.
- **[AC6]** BM25 for the notebook query uses the NOTEBOOK's corpus_version
  (verified — a notebook query does not silently use the shared corpus's
  BM25 index).
- **[AC7]** Documentation: update `.claude/notes/06-mcp-server-design.md`
  (or the relevant note) with the notebook-retrieval routing, and the
  `docs/install.md` / operator surface if the selection mechanism is
  operator-visible.
- **[X-1]** `EXPECTED_TOOL_SCHEMA_SHA256` — UNCHANGED if fork-1 resolves
  to (A) `filters.notebook` over a free-form dict; otherwise a SINGLE
  coordinated re-pin documented in the implementation summary. The
  research synthesis MUST state which.
- **[X-2]** `EXPECTED_BP1_SHA256` — UNCHANGED unless the system prompt /
  tool surface changes; if it changes, re-pin once.
- **[X-3]** `ruff check .` clean; `make test` green; 2900+ tests.

**Out of scope (Won't list — these are follow-up milestones).**

- Multi-notebook concurrent querying from a single tool call (cross-notebook
  federation). v1 selects ONE notebook per call.
- The per-notebook cutover tooling (`notebook-cutover-m1`) — only needed once
  re-embeds must compound; absorb later if fork-2 makes per-notebook lancedb
  the live substrate.
- Notebook-scoped variants of the other tools (`get_definitions`,
  `find_lemma_by_name`, `find_equation`, `cite_neighbors`) — v1 wires only
  `search_papers`. The others follow the same pattern in a v2.
- A new MCP tool for notebook selection if fork-1 resolves to (A) or (C)
  (no new tool → no BP1 re-pin).
- Per-notebook `/readyz` gating (warming every notebook's BGE columns at
  startup). v1 opens the notebook lancedb lazily on first query.
- Migrating the existing shared-corpus query semantics. The shared corpus
  stays the default (AC4).

**Dependencies.** The notebook lancedb datasets exist and are populated
(bridgeland-stability, shimura-varieties). The preamble back-fill landed in
those notebooks' STAGING (not active) — for THIS milestone's testing, the
active `lancedb` (v369 / v49) is sufficient (it has chunks, just no
preambles). Preamble freshness is orthogonal to wiring up retrieval.

**Complexity.** M-L. If the research synthesis concludes the surface is
too large for one milestone (e.g. fork-1 forces a BP1 re-pin AND the cache
isolation AND the Resources refactor are each non-trivial), it should
recommend decomposing into a family via the `/roadmap` skill rather than
forcing a thin pipeline. FLAG THIS in the synthesis if so.

**Specialist suggestions.** `cache-stability-reviewer` (BP1 byte-stability
on the tool surface + the 3-tier cache-key isolation) + `mcp-protocol-reviewer`
(if the tool schema changes) + `determinism-reviewer` (cache key correctness
across notebooks).

**External writes the implementation will require.** None expected — all
changes are local server code + tests. No git push / PR / infra / API.

**Notes for the researcher agents (phase 1).**

1. **Resolve fork 1 FIRST and decisively** — read the `search_papers`
   handler signature in `server/handlers/search.py`: is `filters` typed as
   a free-form `dict[str, Any]` (→ adding `notebook` needs no schema change
   → no BP1 re-pin, the cleanest path)? Or is it a typed Pydantic model
   (→ adding a field re-pins)? This single fact determines whether (A) is
   viable. Quote the signature verbatim.
2. Read `server/handlers/search.py` end-to-end, `get_resources()` /
   `Resources` (grep for the definition), `server/corpus.py`,
   `server/cache.py` (cache-key construction), `server/retrieval/bm25.py`
   (BM25 version resolution), `server/config.py`, `server/session.py`
   (for fork 1B). Quote the cache-key construction + the Resources
   startup binding verbatim.
3. Confirm the shared corpus is actually empty (`var/arxmcp/index/lancedb`
   has no `chunks` table) so the "papers un-queryable today" claim is
   precise.
4. Read `.claude/notes/06-mcp-server-design.md` + `07-multi-agent-caching.md`
   (cache discipline) + `02-architecture-overview.md` + the
   `textbook-ingest-roadmap.md` isolation requirement. Surface any
   constraint that forces a particular fork.
5. Enumerate failure modes around: notebook lancedb missing/empty,
   corpus_version collision in the cache, BM25 version mismatch, a notebook
   query falling through to the (empty) shared corpus silently, and the
   BGE-M3 cold-start cost of opening a second corpus.
6. Be explicit in the synthesis about whether this is ONE shippable
   milestone or needs `/roadmap` decomposition.
