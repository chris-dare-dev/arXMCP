# E09 — Citation Graph (Tier 3)

**Epic dependencies:** E04, E07.

**Goal:** stand up Kùzu citation graph; ingest from OpenAlex (math.AG / math.NT) and INSPIRE-HEP (hep-th / math-ph); add `cite_neighbors` and `dependency_graph` MCP tools. Exit criterion (`09-feature-priorities.md`): "papers cited by Theorem 3.4 of arXiv:2401.01234" returns a coherent dependency list including across-paper citations.

**Effort:** 1–2 weeks.

**References:** `05-storage-and-indexing.md` § Citation graph: Kùzu (schema, query patterns); `03-ingestion-pipeline.md` § Source 4 (INSPIRE), § Source 5 (OpenAlex); `06-mcp-server-design.md` § cite_neighbors, § dependency_graph.

---

### E09_S01 — Kùzu schema migrations

**Description.** Implement the Cypher DDL from `05-storage-and-indexing.md` § Schema (Cypher DDL): `Paper`, `Author`, `Theorem` node tables; `CITES`, `AUTHORED`, `PROVES`, `NAMED_AFTER` rel tables. Migrations are versioned and idempotent.

**Acceptance criteria.**
- [ ] `ingest/graph/schema_v1.cypher` contains the DDL exactly as specified in `05-storage-and-indexing.md`.
- [ ] `ingest/graph/migrate.py::migrate(kuzu_path)` applies missing migrations idempotently.
- [ ] After running on an empty graph: `MATCH (n) RETURN count(n)` returns 0; all 4 node tables and 4 rel tables exist.
- [ ] Test: a second migration call is a no-op.
- [ ] Schema version stored in a `_schema_version` node so future bumps are detectable.

**Dependencies.** none within E09.

**Complexity.** S.

**Labels.** `area:graph`, `kind:infra`.

---

### E09_S02 — OpenAlex monthly bulk-snapshot ingester

**Description.** Per `03-ingestion-pipeline.md` § Source 5 — download monthly OpenAlex bulk snapshots (newline-delimited JSON, gzipped, on a public CDN), filter to math-AG/math-NT works with arXiv IDs, populate `Paper` nodes and `CITES` edges.

**Acceptance criteria.**
- [ ] `ingest/graph/openalex_bulk.py` downloads the latest monthly snapshot (URL pattern from `https://docs.openalex.org/download-all-data`).
- [ ] Polite-pool `mailto=<configured>` parameter used.
- [ ] Filter: only works with `arxiv` external ID and arxiv categories starting with `math.AG` or `math.NT`.
- [ ] Streaming JSON parse — never load the full snapshot into memory.
- [ ] Edges inserted with `source = "openalex"`.
- [ ] Test: a 100-record fixture file produces N `Paper` nodes and M `CITES` edges with correct fields.
- [ ] Resume support: a checkpoint file records which snapshot date was last processed.

**Dependencies.** E09_S01.

**Complexity.** L.

**Labels.** `area:graph`, `area:ingestion`.

---

### E09_S03 — OpenAlex monthly diff and Kùzu rebuild orchestration

**Description.** Per `03-ingestion-pipeline.md` § Realistic timing — citation graph re-sync is monthly. Diff the new snapshot against the prior, apply add/remove edge changes incrementally rather than rebuilding the whole graph.

**Acceptance criteria.**
- [ ] `ingest/graph/openalex_diff.py` reads the last-applied snapshot ID from the checkpoint and computes added/removed/modified records.
- [ ] Adds new `Paper` nodes; updates titles/dates on modified ones; never deletes papers (only edges, on rare retraction events).
- [ ] Total monthly diff time on full corpus ≤ 1 hour per `03-ingestion-pipeline.md`.
- [ ] Test: synthetic snapshot N+1 with 5 new papers and 3 new edges applies correctly.

**Dependencies.** E09_S02.

**Complexity.** M.

**Labels.** `area:graph`, `area:ingestion`.

---

### E09_S04 — INSPIRE-HEP per-paper enrichment loop

**Description.** Per `03-ingestion-pipeline.md` § Source 4 — INSPIRE has structured records with references already resolved to arXiv IDs and DOIs for hep-th + math-ph. Per-paper API calls at ~15 rps with backoff. This is the citation graph backbone for the physics half of the corpus.

**Acceptance criteria.**
- [ ] `ingest/graph/inspire_enrich.py` issues GET requests to `https://inspirehep.net/api/literature?q=arxiv:<id>` at 15 rps with exponential backoff on 5xx.
- [ ] Parses INSPIRE's `references` field to populate `CITES` edges with `source = "inspire"`.
- [ ] Per-paper rate limit shared across the process (single rate-limiter instance).
- [ ] Test: a recorded fixture response for one paper produces the expected `CITES` edges.
- [ ] Resume support: per-paper enrichment status stored alongside the paper row.

**Dependencies.** E09_S01.

**Complexity.** M.

**Labels.** `area:graph`, `area:ingestion`.

---

### E09_S05 — Author disambiguation and `AUTHORED` edges

**Description.** Both OpenAlex and INSPIRE expose author disambiguation (ORCID where available, else fingerprint). Populate `Author` nodes and `AUTHORED` edges. ORCID is preferred; fall back to disambiguated key.

**Acceptance criteria.**
- [ ] `ingest/graph/authors.py` extracts authors from each paper's enrichment record.
- [ ] `Author.author_id` is the ORCID URL when available, else a stable disambiguation hash from OpenAlex/INSPIRE.
- [ ] `Author.affiliations` populated as a list (deduplicated).
- [ ] `AUTHORED.position` records author order.
- [ ] Test: a paper with 3 authors produces 3 `Author` nodes (deduped against existing ORCIDs) and 3 `AUTHORED` edges.

**Dependencies.** E09_S02, E09_S04.

**Complexity.** M.

**Labels.** `area:graph`, `area:ingestion`.

---

### E09_S06 — Intra-paper `\ref{}` extraction for `PROVES` edges

**Description.** Per `05-storage-and-indexing.md` § Seeded from — local extraction of `\ref{}` for intra-paper `PROVES` edges. When Theorem 3.4's proof references Lemma 2.1, that's a `PROVES` edge from the lemma to the theorem ("this theorem's proof depends on that theorem"). Already extracted as cross-references in E04_S07 — this issue lifts that data into the graph.

**Acceptance criteria.**
- [ ] `ingest/graph/proves_edges.py` reads chunks' `referenced_chunks` field (populated in E04_S07).
- [ ] For each theorem chunk that references another theorem chunk in the same paper, emit a `PROVES` edge.
- [ ] `Theorem.theorem_id` matches the chunk_id of the theorem chunk.
- [ ] Test: fixture paper with Theorem 1 referenced by Theorem 3 produces the expected `PROVES` edge.
- [ ] No edges for cross-paper `\cite{}` references — those go through INSPIRE/OpenAlex per the design.

**Dependencies.** E04_S07, E09_S01.

**Complexity.** M.

**Labels.** `area:graph`, `area:parser`.

---

### E09_S07 — `cite_neighbors` MCP tool

**Description.** Per `06-mcp-server-design.md` § cite_neighbors — accepts `paper_id`, `direction` (citers / cited / co_cited / co_citing), `depth`, `limit`. Issues the corresponding Cypher query against Kùzu. Result canonicalized and cache-friendly per the determinism contract.

**Acceptance criteria.**
- [ ] Tool schema matches the note exactly (alphabetically sorted, byte-stable).
- [ ] Each direction maps to a documented Cypher query (per `05-storage-and-indexing.md` § Query patterns we serve).
- [ ] Results sorted by `(citation_count_desc, paper_id_asc)` for determinism.
- [ ] Per-result fields: `paper_id`, `title`, `n_citations`, `relation` (e.g. "cited", "co_cited").
- [ ] Test: `cite_neighbors({paper_id, direction: "cited", depth: 1})` returns expected list on a fixture graph.
- [ ] Test: same call twice ⇒ byte-identical bytes.
- [ ] `corpus_version` reflects the citation graph version (separate from LanceDB version).

**Dependencies.** E09_S05, E07_S02.

**Complexity.** M.

**Labels.** `area:graph`, `area:server`, `kind:feature`.

---

### E09_S08 — `dependency_graph` MCP tool

**Description.** Per `06-mcp-server-design.md` § dependency_graph — given a theorem chunk, return the lemmas its proof depends on, recursively up to `depth` levels. Uses the `PROVES` edges populated in E09_S06. Default depth 2, max 5.

**Acceptance criteria.**
- [ ] Tool schema matches the note exactly.
- [ ] Cypher query: `MATCH (t:Theorem {theorem_id: $id})-[:PROVES*1..$depth]->(dep:Theorem) RETURN dep`.
- [ ] Result is a DAG (cycles are pruned at the `depth` boundary).
- [ ] Per-result fields: `theorem_id`, `paper_id`, `name` (if present), `depth_from_root`.
- [ ] Test: a 3-level dependency chain returns the expected nodes at depth 2.
- [ ] Test: cyclic dependency (degenerate fixture) does not infinite-loop.

**Dependencies.** E09_S06, E09_S07.

**Complexity.** M.

**Labels.** `area:graph`, `area:server`, `kind:feature`.

---

### E09_S09 — Co-citation cluster query

**Description.** Per `05-storage-and-indexing.md` § Query patterns — co-citation clusters around a topic ("papers commonly cited together with X"). Surfaced via `cite_neighbors` with `direction = "co_cited"`. Implementation backs the query patterns in E09_S07.

**Acceptance criteria.**
- [ ] Cypher query implementation matches the note's example: `MATCH (x:Paper {paper_id: $id})<-[:CITES]-(p:Paper)-[:CITES]->(co:Paper) WHERE co.paper_id <> $id RETURN co.paper_id, count(*) AS strength ORDER BY strength DESC LIMIT 30`.
- [ ] Returns `[{paper_id, title, strength}]`.
- [ ] Test on a fixture graph: co-citation strength is computed correctly.

**Dependencies.** E09_S07.

**Complexity.** S.

**Labels.** `area:graph`, `area:retrieval`.

---

### E09_S10 — Citation-graph version pinning

**Description.** Like LanceDB, the citation graph is versioned. Daily INSPIRE enrichment writes incrementally to the graph but the MCP server reads a snapshot file pinned at session start. Monthly OpenAlex bulk diffs are atomic-swapped via a symlink.

**Acceptance criteria.**
- [ ] Kùzu graph file lives at `var/arxmcp/index/kuzu/citations-vYYYYMM.kuzu` with a `current` symlink.
- [ ] On startup, the MCP server resolves `current` and pins the path for the process lifetime.
- [ ] Test: writer publishes a new graph file; running server continues using the old one.
- [ ] `corpus_version` includes the citation graph version (e.g. `{lancedb: 7, kuzu: 202602}`).

**Dependencies.** E09_S03.

**Complexity.** S.

**Labels.** `area:graph`, `area:storage`, `kind:infra`.

---

### E09_S11 — Citation-graph smoke test on seed corpus

**Description.** Run citation enrichment over the 50-paper seed corpus from E01–E04 and validate that for at least 30 papers we have outbound `CITES` edges and for at least 5 papers we have inbound `CITES` edges from non-corpus papers.

**Acceptance criteria.**
- [ ] `tools/eval_citation_graph_seed.py` queries the graph and emits stats.
- [ ] At least 30 of 50 seed papers have ≥5 outbound `CITES` edges.
- [ ] At least 5 seed papers have ≥1 inbound `CITES` edge from a paper not in the seed.
- [ ] One sample paper's full neighborhood (1-hop in/out) is rendered in `docs/tier-3-citation-sample.md`.
- [ ] `cite_neighbors` and `dependency_graph` tools both return non-empty for at least one seed paper each.

**Dependencies.** E09_S07, E09_S08.

**Complexity.** S.

**Labels.** `area:graph`, `kind:research`.

---
