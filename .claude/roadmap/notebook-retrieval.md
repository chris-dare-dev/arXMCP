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

---

### notebook-retrieval-m2 — Per-call notebook routing (fork A): one server, many notebooks

**Owner:** Chris Dare
**Created:** 2026-05-28
**Status:** scoped — QUEUED (run after m1 shipped 2026-05-28; m1 = fork C, complete)

**Description.** Generalize m1's fork C (one-notebook-per-process via
`ARXMCP_NOTEBOOK`) to fork A: a `filters.notebook=<slug>` argument on
`search_papers` routes a single call to THAT notebook's
`var/arxmcp/notebooks/<slug>/lancedb` — WITHOUT a server relaunch, so one
running server serves many notebooks across calls. m1 front-loaded the shared
seam `tools._notebook_common.notebook_lancedb_path(slug)` (m1 AC8) precisely
so this is additive, not a rewrite. Demo target: with the server running and
NO `ARXMCP_NOTEBOOK` set, `search_papers(query="Bridgeland's original
definition…", filters={"notebook": "bridgeland-stability"})` surfaces
`0705.3794`, and a second call with `filters={"notebook":
"shimura-varieties"}` serves shimura chunks from the SAME process.

**LOAD-BEARING CORRECTIONS to the m1 omnibus brief above (do NOT regress).**
The stale m1 brief (AC2, fork-1 prose) assumed the full
BM25 → ANN → RRF → rerank pipeline. THREE spikes
(`spike-accuracy-fork-analysis.md`, `spike-accuracy-by-difficulty-class.md`,
`spike-dual-column-fusion.md`) measured **dense-only over `embedding_stmt`
as the accuracy ceiling** on these notebooks — BM25/RRF/rerank AND dual-column
(`embedding_proof`) fusion are all net-negative on top-1 precision. **m2 routes
the SAME dense-only path m1 ships, just per-call.** Do not wire the hybrid
pipeline; do not query `embedding_proof`. The fork-1 decision is LOCKED to (A)
— `filters` is a free-form `dict[str, Any]` (m1 verified), so adding a
`notebook` key needs NO `inputSchema` change → no `EXPECTED_TOOL_SCHEMA_SHA256`
re-pin, no BP1 cache invalidation.

**The forks m1 deferred to m2 (this is the real m2 substance):**

1. **Slug-in-cache-key — THE central refactor.** m1's F1 fix used STRUCTURAL
   per-notebook isolation: one process = one notebook = one `cache_db_path`
   sibling (`var/arxmcp/notebooks/<slug>/cache/retrieval.db`). Fork A breaks
   that premise — one process now serves MANY notebooks per-request against ONE
   `cache_db_path`. The Tier-1 key
   (`server/cache_sqlite.py:107-180`: `query, filters, k, corpus_version,
   level`) carries NO notebook slug, and `corpus_version` is per-dataset MVCC
   (NOT globally unique → bridgeland v369 and a fresh notebook v369 collide).
   **m2 MUST add the notebook slug to the Tier-1 key** — the slug-in-key
   refactor m1 explicitly deferred. Reconcile cleanly with m1's F1: with fork A,
   the per-process notebook is unset, so the m1 per-notebook `cache_db_path`
   derivation becomes a no-op and m2 reverts to the shared `cache_db_path` +
   slug-in-key. Do NOT leave two competing isolation mechanisms.
2. **Per-notebook table registry.** `Resources.startup` opens ONE
   `chunks_table` at startup (`server/resources.py:332`). Fork A needs a
   slug → table cache (lazy open + memoize per slug, bounded). Resolve the
   cleanest seam — a `Resources.notebook_table(slug)` lazy registry vs a
   request-scoped open — in `server/handlers/search.py` + the Resources
   abstraction. Threat-1 slug validation BEFORE any open.
3. **Per-notebook `corpus_version` echo.** The result envelope echoes
   `corpus_version`. With per-call notebooks, the echoed value MUST be the
   NOTEBOOK's pinned version, not the (empty) shared corpus's. Confirm the
   envelope construction in `server/handlers/search.py`.
4. **Threat-1 at the filters boundary.** The slug arrives in agent-supplied
   `filters` JSON and flows to a filesystem path. It MUST be validated via
   `tools._notebook_common.validate_slug` (regex + symlink rejection +
   containment) at the handler boundary BEFORE any path use — the
   E09_S03-style "never source a path from agent JSON without validation"
   contract. This is the same guard m1 applied at config-load, now at the
   per-call boundary.

**Acceptance criteria (corrected, dense-only).**

- **[AC1]** `search_papers(query=…, filters={"notebook":"bridgeland-stability"})`
  returns rows from that notebook's lancedb (not the empty shared corpus);
  `0705.3794` in top-k. Integration test against a synthetic 2-notebook fixture
  (no real BGE-M3 — mirror m1's hermetic `Resources.startup` pattern).
- **[AC2]** Retrieval is the SAME dense-only path (single ANN over
  `embedding_stmt`, proof chunks excluded, `retrieval_mode="dense_only"`);
  envelope byte-shape-identical to a shared-corpus query.
- **[AC3]** Two notebooks, same query string, overlapping `corpus_version` →
  the Tier-1 cache does NOT cross-serve (slug now in the key). Regression test
  with a synthetic 2-notebook cache scenario (cf. m1's
  `test_notebook_cache_files_are_isolated`, now at the key level).
- **[AC4]** No `filters.notebook` → byte-identical to today (shared corpus, or
  the fork-C `ARXMCP_NOTEBOOK` path if that env is set). No regression. Both
  fork-C (env) and fork-A (per-call) must coexist; define precedence if both
  are present (recommend: explicit per-call `filters.notebook` wins, documented).
- **[AC5]** A non-existent / empty notebook slug in `filters` → clean typed
  error or empty result, NOT a 500. A path-traversal slug is rejected by
  `validate_slug` at the boundary.
- **[AC6]** The envelope's `corpus_version` is the NOTEBOOK's pinned version.
- **[AC7]** Reconcile m1's F1 per-notebook `cache_db_path` with the new
  slug-in-key — one isolation mechanism, not two. Document the reconciliation.
- **[AC8]** Docs: update `.claude/notes/06-mcp-server-design.md` (fork A
  routing) + `07-multi-agent-caching.md` (slug-in-key) + `docs/install.md` if
  operator-visible.
- **[X-1]** `EXPECTED_TOOL_SCHEMA_SHA256` UNCHANGED (free-form `filters` dict —
  verify, do not assume).
- **[X-2]** `EXPECTED_BP1_SHA256` UNCHANGED.
- **[X-3]** `ruff check .` clean; `make test` green.

**Out of scope.** Multi-notebook federation in ONE call (still one notebook per
call). Notebook-scoped variants of the other 6 tools (`get_definitions`,
`find_lemma_by_name`, `find_equation`, `get_chunk`, `get_paper`,
`cite_neighbors`) — same pattern, later milestones. Per-notebook `/readyz`
warming. Any retrieval-MODE change (dual-column / hybrid / rerank — all closed
by the spikes; this milestone is routing only).

**Dependencies.** m1 shipped (fork C + the `notebook_lancedb_path` helper + the
per-notebook `cache_db_path` derivation to reconcile). Notebook lancedbs
populated (bridgeland-stability, shimura-varieties).

**Complexity.** M. The substance is the slug-in-key refactor + the table
registry + the F1 reconciliation; the routing itself is a thin handler change
on top of the m1 helper.

**Specialist suggestions.** `cache-stability-reviewer` (slug-in-key correctness
+ BP1 byte-stability) + `determinism-reviewer` (cross-notebook cache-key
isolation).

**External writes the implementation will require.** None — local server code +
tests + docs.

**Notes for the researcher agents (phase 1).**

1. Quote the `search_papers` handler signature in `server/handlers/search.py`
   verbatim — confirm `filters` is `dict[str, Any] | None` (m1's claim) so (A)
   needs no schema re-pin. If it is a typed model, FLAG IT (changes X-1).
2. Quote the Tier-1 key construction (`server/cache_sqlite.py:107-180`) +
   `server/cache.py` cache-key path verbatim; design the minimal slug-injection
   that keeps the key byte-stable for the no-notebook case (AC4 — unset slug
   must produce a key byte-identical to today).
3. Read m1's `server/config.py::derive_notebook_lancedb_path` + the m1 critique
   `critique-merged.md` (F1) — the F1 reconciliation (AC7) is load-bearing.
4. Resolve the table-registry seam: `grep -rn "def get_resources\|class Resources\|chunks_table"` —
   decide lazy per-slug memoization vs request-scoped open; bound the cache.
5. Enumerate failure modes: notebook missing/empty, corpus_version collision
   (now slug-keyed), traversal slug in filters, fork-C + fork-A both set,
   second-corpus cold-open cost, a slug that exists on disk but is un-ingested.
6. Confirm whether this is ONE shippable milestone or needs `/roadmap`
   decomposition (the slug-in-key refactor is the risk axis).
