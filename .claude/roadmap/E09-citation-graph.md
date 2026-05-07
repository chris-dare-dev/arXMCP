# E09 — Citation Graph (NEW)

**Epic dependencies:** E04 (LanceDB `chunks` table with stable `chunk_id`s and `paper_id`s), E06 (MCP server with `search_papers` and `get_chunk` tools, Sonnet B), E07 (hybrid retrieval, Sonnet B), E08 (caching + multi-agent orchestration, Sonnet B). This is a Tier-3 epic — it begins only after Tier-0 (E01–E05), Tier-1 (E06–E07), and Tier-2 (E08) have landed.

**Goal:** Build a Kùzu citation graph that connects arXiv papers to each other via `cites` edges (sourced from OpenAlex for math.AG/math.NT and INSPIRE-HEP for hep-th/math-ph), and expose a `cite_neighbors(chunk_id, depth, direction)` tool over the MCP server that enables the multi-agent math-proof pipeline to trace cross-paper proof chains. The 2-round agent pattern (round 1: `cite_neighbors(depth=2)`, round 2: bulk parallel `get_chunk`) fits within the 3-round cap defined in E08 and closes H7 fully.

**Effort:** ~3 weeks calendar (L+M+M+M across four milestones).

**References:** `05-storage-and-indexing.md` § Kùzu citation graph (schema, `cite_neighbors` API, OpenAlex bulk ingest notes), `06-mcp-server-design.md` § Tool surface (`cite_neighbors` tool spec), `07-multi-agent-caching.md` § Round-trip budgets (3-round cap for multi-agent workflows), `10-references-and-prior-art.md` § OpenAlex, INSPIRE-HEP.

---

### E09_S01 — Kùzu schema migrations and OpenAlex bulk ingest (math.AG/math.NT)

**Status:** NEW
**Tier:** 3
**Effort:** L
**Dependencies:** E04_S01 (stable paper_id set), E08 (Sonnet B — server layer must be stable before graph is added)

**Description.** Initialize the Kùzu graph database at `var/arxmcp/index/kuzudb/` and define the graph schema. Kùzu is a high-performance embedded graph database (MIT license) with a Cypher-like query language; it is used here rather than a general-purpose graph database because it can be embedded in the Python process alongside LanceDB, requires no separate server, and supports efficient graph traversal at Tier-3 corpus scales (tens of thousands of papers and hundreds of thousands of citation edges).

**Graph schema:**
```cypher
CREATE NODE TABLE papers (
  paper_id STRING,
  title STRING,
  abstract STRING,
  authors STRING,
  year INT32,
  categories STRING,
  oa_work_id STRING,   -- OpenAlex work ID
  PRIMARY KEY (paper_id)
);

CREATE REL TABLE cites (
  FROM papers TO papers,
  source STRING,       -- "openAlex" | "inspire" | "intra-paper"
  confidence FLOAT     -- 1.0 for confirmed, lower for inferred
);
```

OpenAlex bulk ingest reads from the OpenAlex API (`https://api.openalex.org/works`) using filtered queries for `primary_topic.field.id = "fields/mathematics"` and `concepts.id = "C66938386"` (algebraic geometry) or `C15736585` (number theory). The ingest script uses the OpenAlex "polite pool" by including `mailto:` in the `User-Agent` header (same pattern as arXiv TOS compliance in E01_S02). Rate limit: 10 requests/second in the polite pool.

For each paper in the seed corpus (the 50 arXiv IDs from E01_S03), the ingest script fetches the OpenAlex work record, extracts the `referenced_works` list (cited papers), and writes `cites` edges for each referenced work that is also in the corpus. In Tier 3, the corpus expands to all math.AG and math.NT papers in OpenAlex (not just the 50-paper seed), which may number in the tens of thousands; the ingest script must handle pagination and checkpointing.

The ingest script is `ingest/graph_ingest.py` with a CLI: `python -m ingest.graph_ingest --source openAlex --category math.AG math.NT --checkpoint var/arxmcp/ops/graph-ingest-checkpoint.json`. Checkpointing is essential at Tier-3 scale: if the ingest fails midway through tens of thousands of papers, it should resume from the last checkpoint rather than starting over.

**Deliverables.**
- `ingest/graph_ingest.py` — OpenAlex bulk ingest with checkpoint support
- `ingest/kuzudb_schema.py` — schema migration script; idempotent (safe to run multiple times)
- `var/arxmcp/index/kuzudb/` — initialized Kùzu database
- `pytest tests/test_graph_ingest.py` — test: ingest 5 fixture papers with mocked OpenAlex responses, assert node and edge counts

**Acceptance criteria.**
- [ ] Kùzu schema created at `var/arxmcp/index/kuzudb/` with `papers` node table and `cites` rel table.
- [ ] Schema migration is idempotent (running twice does not create duplicate tables or raise errors).
- [ ] For each of the 50 seed papers, a `papers` node exists in the graph.
- [ ] `cites` edges are written for all OpenAlex-confirmed citation pairs within the corpus.
- [ ] Checkpoint file written after each batch of 100 papers processed.
- [ ] Ingest resumes from checkpoint correctly: if interrupted after K papers, re-running skips the first K papers.
- [ ] `User-Agent` header includes `arXMCP/0.1 (mailto:...)` for OpenAlex polite pool compliance.
- [ ] Integration test passes with mocked OpenAlex API (no live network calls in CI).

**Out of scope.** INSPIRE-HEP ingest (E09_S02). `cite_neighbors` query API (E09_S03). Intra-paper `\ref{}` chain tracing (E09_S03). Cross-paper proof chain workflow documentation (E09_S04).

**Risk notes.**
- Kùzu is a relatively young project (first stable release 2023). Pin the Kùzu version in `pyproject.toml` and include a note that the Cypher dialect may differ from Neo4j Cypher. Test against the pinned version only.
- OpenAlex coverage for math.AG papers is strong for post-2000 arXiv papers but sparser for older literature. Papers not found in OpenAlex are still added as `papers` nodes (from the arXiv metadata) but may have no `cites` edges. This is acceptable at Tier 3; INSPIRE-HEP enrichment (E09_S02) fills some gaps for physics-adjacent papers.

**Labels.** `area:graph`, `kind:feature`, `tier:3`.

---

### E09_S02 — INSPIRE-HEP per-paper enrichment (hep-th/math-ph)

**Status:** NEW
**Tier:** 3
**Effort:** M
**Dependencies:** E09_S01

**Description.** OpenAlex citation coverage for `hep-th` and `math-ph` papers is significantly weaker than INSPIRE-HEP, which is the community standard for high-energy physics literature. This milestone enriches the citation graph with INSPIRE-HEP data for papers in the `hep-th` and `math-ph` arXiv categories.

INSPIRE-HEP exposes a REST API (`https://inspirehep.net/api/literature`) that accepts arXiv IDs as identifiers and returns structured citation records including both `references` (papers the target cites) and `citations` (papers that cite the target). The API is public and requires no authentication; the rate limit is approximately 5 requests/second.

The enrichment script `ingest/inspire_ingest.py` iterates over all `papers` nodes in the Kùzu graph with `categories LIKE "%hep-th%" OR categories LIKE "%math-ph%"`, queries INSPIRE-HEP for each, and adds any new `cites` edges discovered (marked with `source="inspire"`). Existing edges from OpenAlex are not overwritten — this is additive enrichment. The `confidence` field is set to 1.0 for INSPIRE-HEP confirmed citations (INSPIRE-HEP curates citation data manually for high-energy physics).

The script also enriches paper metadata: INSPIRE-HEP returns DOIs, journal references, and collaboration affiliations that OpenAlex may not have. This metadata is written to supplementary columns in the `papers` node table (nullable columns added via schema migration).

INSPIRE-HEP enrichment is run after OpenAlex ingest (E09_S01) completes. It is not a blocking dependency for `cite_neighbors` functionality (E09_S03); `cite_neighbors` works with whatever edges are in the graph, regardless of source. Enrichment just improves graph completeness for physics-category papers.

**Deliverables.**
- `ingest/inspire_ingest.py` — INSPIRE-HEP enrichment script with checkpoint
- Schema migration: add nullable `doi`, `journal_ref`, `inspire_id` columns to `papers` table
- `pytest tests/test_inspire_ingest.py` — integration test with mocked INSPIRE-HEP API

**Acceptance criteria.**
- [ ] For all seed corpus papers with `hep-th` or `math-ph` in their categories, INSPIRE-HEP is queried.
- [ ] New `cites` edges from INSPIRE-HEP data are added with `source="inspire"`.
- [ ] Existing `source="openAlex"` edges are not duplicated or overwritten.
- [ ] `doi` and `inspire_id` columns are populated where INSPIRE-HEP returns them.
- [ ] Integration test passes with mocked API.
- [ ] Rate limiting: INSPIRE-HEP requests are throttled to ≤5/second.

**Out of scope.** OpenAlex re-ingest or update (E09_S01). Intra-paper reference chain tracing (E09_S03). Citation graph GC or freshness updates (E11).

**Risk notes.**
- INSPIRE-HEP API stability: the REST API has been stable since 2021, but the field names in the response schema can change. Pin the response parsing to a documented API version and add regression tests against a snapshot of the response format.
- For math-ph papers, INSPIRE-HEP and OpenAlex may both have good coverage; in that case, INSPIRE-HEP adds citation confidence (curated vs. inferred) rather than coverage.

**Labels.** `area:graph`, `kind:feature`, `tier:3`.

---

### E09_S03 — `cite_neighbors(chunk_id, depth=2, direction)` graph traversal

**Status:** NEW
**Tier:** 3
**Effort:** M
**Dependencies:** E09_S01, E09_S02, E06 (Sonnet B — `get_chunk` tool must be available for round 2 of the agent pattern)

**Description.** The `cite_neighbors` function is the primary graph query API. Given a `chunk_id` (which is mapped to a `paper_id` via a simple lookup), it performs a breadth-first graph traversal in the Kùzu database up to `depth` hops, returning a structured result list. This function is exposed as an MCP tool in E06 (Sonnet B adds it to the server tool surface); this milestone implements the underlying graph query.

**Function signature:**
```python
def cite_neighbors(
    chunk_id: str,
    depth: int = 2,
    direction: Literal["cites", "cited_by", "depends_on"] = "cites",
    max_results: int = 50,
    kuzudb_path: str = "var/arxmcp/index/kuzudb/"
) -> list[CitationNeighbor]
```

**`CitationNeighbor` dataclass:**
```python
@dataclass
class CitationNeighbor:
    chunk_id: str       # representative chunk_id for this paper (the first stmt chunk)
    paper_id: str       # arXiv ID
    edge_kind: str      # "cites", "cited_by", or "ref" (intra-paper)
    hop_distance: int   # 1 = direct neighbor, 2 = neighbor's neighbor
    source: str         # "openAlex", "inspire", or "intra-paper"
    confidence: float   # from the cites rel table
```

**Direction semantics:**
- `direction="cites"`: returns papers that the source paper cites (outgoing edges), up to `depth` hops.
- `direction="cited_by"`: returns papers that cite the source paper (incoming edges), up to `depth` hops.
- `direction="depends_on"`: traces intra-paper `\ref{}` chains from the chunk's `theorem_label` to other chunks in the same paper (the `cites` edges with `source="intra-paper"` created by a separate intra-paper ref-chain pass — see below). When `direction="depends_on"` and a result chunk is in a different paper, it falls back to `direction="cites"` for cross-paper hops.

**Intra-paper ref chain:** the milestone also includes a one-time pass at ingest time that reads each chunk's `theorem_label` and scans the paper's LaTeXML HTML for `\ref{<theorem_label>}` occurrences in other chunks. A `cites` edge with `source="intra-paper"` is added between the citing chunk's paper node and the cited theorem's paper node (the same paper, since `\ref{}` is typically intra-paper). This is a lightweight static analysis pass, not a proof-checker.

The Kùzu query for `direction="cites"` at `depth=2` is:
```cypher
MATCH (p:papers {paper_id: $paper_id})-[:cites*1..2]->(n:papers)
RETURN n.paper_id, length(path) AS hop
```

Results are mapped to `CitationNeighbor` records by looking up the first `kind="stmt"` chunk for each `paper_id` in the LanceDB table. If no stmt chunk exists (the paper is in the graph but not in the chunked corpus), `chunk_id` is returned as `None` and the agent must call `get_chunk` with just `paper_id` instead.

**Deliverables.**
- `server/graph_queries.py` — `cite_neighbors()` implementation
- `server/graph_types.py` — `CitationNeighbor` dataclass
- `ingest/intra_paper_refs.py` — intra-paper `\ref{}` chain ingest pass
- `pytest tests/test_graph_queries.py` — unit test: 5-paper fixture graph, assert `cite_neighbors` returns correct neighbors at depth=1 and depth=2

**Acceptance criteria.**
- [ ] `cite_neighbors(chunk_id, depth=1, direction="cites")` returns all direct citation neighbors.
- [ ] `cite_neighbors(chunk_id, depth=2, direction="cites")` returns hop-1 and hop-2 neighbors with correct `hop_distance` values.
- [ ] `direction="cited_by"` returns incoming edges (papers that cite the source).
- [ ] `direction="depends_on"` returns intra-paper `\ref{}` chain results.
- [ ] Results are capped at `max_results=50` to prevent unbounded returns on highly-cited papers.
- [ ] Each result includes `chunk_id`, `paper_id`, `edge_kind`, `hop_distance`, `source`, `confidence`.
- [ ] Papers in the graph but not in the chunked corpus return `chunk_id=None`.
- [ ] Unit test passes on a 5-paper fixture graph with known edges.

**Out of scope.** MCP tool registration (`cite_neighbors` as an MCP tool — that is E06_S04, Sonnet B). Cross-paper proof chain agent workflow documentation (E09_S04). Equation-level dependency graphs (E10).

**Risk notes.**
- **Closes H7 partial.** This milestone implements the `cite_neighbors` function. H7 is fully closed when E09_S04 documents and validates the 2-round agent pattern that uses `cite_neighbors` + bulk `get_chunk`.
- `depth=2` can return up to O(D²) neighbors for a paper with D direct citations. Highly-cited papers (e.g. Grothendieck's Tôhoku paper) may have thousands of direct citations; the `max_results` cap prevents memory issues but means the traversal is incomplete. Document this limitation explicitly.

**Labels.** `area:graph`, `kind:feature`, `tier:3`.

---

### E09_S04 — Cross-paper proof chain workflow (2-round agent pattern)

**Status:** NEW
**Tier:** 3
**Effort:** M
**Dependencies:** E09_S03, E06 (Sonnet B — `get_chunk` MCP tool), E08 (Sonnet B — 3-round cap enforced)

**Description.** This milestone documents and validates the specific agent interaction pattern that `cite_neighbors` enables for the multi-agent math-proof pipeline. The pattern uses exactly 2 MCP rounds, fitting within the 3-round cap enforced by E08 (Sonnet B).

**The 2-round cross-paper proof chain pattern:**

```
Round 1: cite_neighbors(chunk_id=<entry_theorem>, depth=2, direction="cites")
  → Returns: list of CitationNeighbor records (up to 50, with chunk_ids)

Round 2 (parallel): get_chunk(chunk_id) × N
  → Returns: chunk bodies for all N returned neighbors
  (Each get_chunk call is independent; the agent issues them in parallel)

Total rounds: 2
```

The agent (typically the "autoformalizer" or "tactician" sub-agent in the math-proof pipeline) uses the proof-chain context assembled in these 2 rounds to identify which cited results it needs to assume as lemmas, and in which order they were proved. This context is assembled into the sub-agent's context window before it attempts to formalize or prove the target theorem.

The 2-round structure is critical for the 3-round budget. The math-proof pipeline's orchestrator allocates 3 MCP rounds per sub-agent invocation: 1 round for initial retrieval (`search_papers`), 1 round for proof-chain expansion (`cite_neighbors`), and 1 round for specific chunk retrieval (`get_chunk` bulk). Within E09_S04's pattern, rounds 2+3 are merged: `cite_neighbors` returns chunk_ids, and `get_chunk` calls are issued in parallel in a single round. This keeps the total at 2 rounds for the proof-chain workflow, leaving 1 round for the initial `search_papers` call in the full orchestration flow.

This milestone ships a worked example in the epic body (below) and a runnable integration test that simulates the 2-round pattern against the 50-paper seed corpus. The integration test uses a known entry theorem chunk_id from the eval fixture (E05_S01) and asserts that the returned neighbors contain at least one expected citation.

**Worked example** (included verbatim in `docs/proof-chain-workflow.md`):
```
Query: "What results does the proof of the Grothendieck-Riemann-Roch theorem cite?"

Round 1:
  cite_neighbors(
    chunk_id="arxiv:1803.01010:stmt-thm-grr",
    depth=2,
    direction="cites"
  )
  → [
      CitationNeighbor(chunk_id="arxiv:0901.0101:stmt-thm-rr", paper_id="0901.0101", hop_distance=1, ...),
      CitationNeighbor(chunk_id="arxiv:1205.4344:stmt-def-chern", paper_id="1205.4344", hop_distance=2, ...),
      ...
    ]

Round 2 (parallel, 1 MCP round):
  get_chunk("arxiv:0901.0101:stmt-thm-rr")   → {body_text: "Theorem (Riemann-Roch). ..."}
  get_chunk("arxiv:1205.4344:stmt-def-chern") → {body_text: "Definition (Chern character). ..."}

Total: 2 rounds. Context assembled: entry theorem + cited lemmas + their statements.
```

**Deliverables.**
- `docs/proof-chain-workflow.md` — the 2-round pattern documentation with worked example
- `pytest tests/test_proof_chain.py` — integration test simulating 2-round pattern against seed corpus
- Update to `server/graph_queries.py` — verify `cite_neighbors` returns results fast enough for 2-round budget (target: ≤500ms for `depth=2` on the 50-paper corpus)

**Acceptance criteria.**
- [ ] `docs/proof-chain-workflow.md` documents the 2-round pattern with the worked example above.
- [ ] `pytest tests/test_proof_chain.py` passes: round 1 returns ≥1 neighbor for a known entry chunk; round 2 (simulated parallel get_chunk) returns non-null body_text for all returned chunk_ids.
- [ ] `cite_neighbors(depth=2)` completes in ≤500ms on the 50-paper seed corpus.
- [ ] Documentation states: "Total round count = 2. This fits the 3-round cap from E08. Round 1 (`cite_neighbors`) + Round 2 (bulk parallel `get_chunk`) = 2 rounds."
- [ ] Documentation explicitly notes: if a `CitationNeighbor` has `chunk_id=None` (paper in graph but not chunked), the agent must use `search_papers(paper_id=<paper_id>)` instead of `get_chunk` — that counts as a third round and exhausts the budget.

**Out of scope.** Proof verification (Lean 4 kernel integration is a separate epic). Equation-level citation chains (E10). Graph freshness updates (E11). Expanding to math.NT, hep-th, math-ph in the proof-chain workflow (requires multi-category ingest from E09_S01 and E09_S02 to be complete).

**Risk notes.**
- **Closes H7 fully.** H7 ("cross-paper proof chains unaddressed") is closed by the combination of E09_S03 (`cite_neighbors` implementation) and this milestone (the 2-round agent pattern). The closure is confirmed when `tests/test_proof_chain.py` passes.
- The worked example must use real `chunk_id`s from the seed corpus to be testable. The integration test must use the same IDs. If `chunk_id`s change (e.g. due to a `chunker_version` bump), the worked example and test must be updated in lockstep with E02_S05's fixture update procedure.
- The 500ms latency target for `cite_neighbors(depth=2)` is achievable on the 50-paper corpus but must be verified on the full Tier-3 corpus (tens of thousands of papers). If Kùzu graph traversal is too slow at scale, BFS can be replaced with a pre-computed adjacency list (cached at server startup) without changing the API.

**Labels.** `area:graph`, `kind:feature`, `tier:3`.
