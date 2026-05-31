# Comparative Landscape Brief — 2026q2-crawl4ai-paper-discovery

**Scout run:** 2026-05-31  
**Scope:** Whether crawl4ai-based scraping is the right tool for a "discover new arXiv papers by topic area and add to notebook" feature; official-API alternatives; how the feature fits arXMCP's ingest pipeline and MCP tool surface.

---

## 1. TL;DR

The arXiv API already provides category+keyword+date-range search sufficient to discover new papers in a topic area (`cat:math.AG AND abs:Bridgeland stability`, `sortBy=submittedDate`) — confirmed live with 2,176 matches. The Semantic Scholar Recommendations API (`/graph/v1/paper/{id}/recommendations`) provides seed-based "papers like this" discovery over 200M+ papers including TLDR machine summaries. **crawl4ai is the wrong tool for this job**: arXiv's `robots.txt` mandates a 15-second crawl-delay for generic bots (arXiv API TOS states one request per 3 seconds), crawl4ai's robots.txt support was a PR that was closed/abandoned (PR #1707, Mar 2026), and Playwright-based browser automation triggers arXiv's bot-detection. The main thematic gap is that arXMCP has no discovery outbox: it can retrieve from a fixed corpus, but no MCP tool or ingest entrypoint exists for the agent to say "go find more papers on X and queue them for ingest."

---

## 2. Top capability candidates

### Candidate 1: arXiv API category+topic search with date-range filtering

**Capability name:** Targeted new-paper discovery by category + keyword + submission date

**Source system:** arXiv public API (`export.arxiv.org/api/query`)

**Public evidence:** https://info.arxiv.org/help/api/user-manual.html — confirmed live:
- `search_query=cat:math.AG+AND+ti:Bridgeland+AND+ti:stability&sortBy=submittedDate` → 55 papers, newest first
- `search_query=cat:math.AG+AND+abs:Bridgeland+stability&sortBy=submittedDate` → 2,176 papers
- `submittedDate:[YYYYMMDDTTTT+TO+YYYYMMDDTTTT]` filter narrows to a time window
- `max_results` up to 2,000 per call, up to 30,000 total per query

**Capability angle:** An LLM agent (or the ingest driver) can receive a notebook's topic keywords and category, issue a single API call to discover papers submitted in the past week/month, get back Atom entries with title/abstract/authors/arXiv ID, and queue new IDs for the existing ingest pipeline. This is exactly the "discover new papers" feature requested. No scraping. No rate-limit risk. TOS-clean.

**Technical angle:** The API searches only fields arXiv indexes (title, abstract, author, categories, comment, journal-ref, report-num). It cannot search full-text or LaTeX bodies. "Bridgeland stability conditions" as an abstract keyword misses papers that use the term only in body text. Relevance ranking is coarse for highly technical sub-subfields; the agent may need to filter results semantically. The API returns metadata only — the ingest pipeline then handles the source fetch via the existing `/e-print/` path.

**Cross-reference to arXMCP:** `ingest/oai_delta.py` (OAI-PMH delta loop, E11); `tools/arxiv_fetch.py:POLITENESS_SLEEP_SECONDS=3.0` (the existing 3-second politeness contract). The arXiv API is an existing ingest source — this capability is a new entry point that calls the same API with different query parameters (topic + date-range rather than OAI-PMH incremental harvesting). No analog in the current MCP tool surface.

---

### Candidate 2: Semantic Scholar paper recommendations endpoint

**Capability name:** Seed-paper-based recommendation ("papers like this")

**Source system:** Semantic Scholar Academic Graph API (`api.semanticscholar.org/graph/v1/paper/{paperId}/recommendations`)

**Public evidence:** https://www.semanticscholar.org/product/api — confirmed working bulk search endpoint at `api.semanticscholar.org/graph/v1/paper/search/bulk` (335 results for "Bridgeland stability conditions" with arXiv IDs, DOIs, year); Recommendations API listed as a dedicated service. Unauthenticated pool: 1,000 req/s shared across all users; API key (free) provides 1 RPS dedicated. `s2-folks` repository archived 2025-01-27.

**Capability angle:** Given one or more arXiv IDs already in a notebook, an agent can ask S2 "what papers are similar to these?" and receive a ranked list with arXiv IDs. This is a **semantic neighborhood expansion** — a different axis from keyword search. S2 uses SPECTER2 embeddings (trained on citation graph + abstract). Also provides TLDR machine summaries (2-sentence abstracts) useful for agent pre-screening before committing to a full ingest.

**Technical angle:** S2's coverage of math.AG/math.NT is good but not complete — some preprints appear in S2 within days of arXiv submission via their daily ingest. The `recommendations` endpoint requires at least one `positivePaperIds` seed; for a fresh notebook with no ingested papers, the agent must first discover seeds via the bulk search path. The 1 RPS unauthenticated limit is acceptable for discovery (not bulk harvest). License: S2 API is a proprietary service with a free tier; data usage governed by S2 Terms; no code dependency introduced.

**Cross-reference to arXMCP:** `ingest/graph_ingest.py` (E09_S01) — already calls OpenAlex for citation data over the same seed paper IDs. S2 recommendations would be a parallel discovery channel using the same paper_id set. `server/graph_queries.py::cite_neighbors` is the closest retrieval analog (citation-graph neighbors), but cite_neighbors is a query over the local Kùzu graph, not an external discovery call. No MCP tool analog.

---

### Candidate 3: arXiv OAI-PMH incremental harvest (already in arXMCP, under-leveraged)

**Capability name:** Date-windowed category-filtered new-submission harvesting

**Source system:** arXiv OAI-PMH (`oaipmh.arxiv.org/oai`)

**Public evidence:** https://info.arxiv.org/help/oa/index.html — supports `set=math` (or `set=math:math.AG` for sub-category), date-range `from`/`until` windowing with resumption tokens. Formats: `oai_dc`, `arXiv` (metadata including categories/abstract), `arXivRaw` (version history).

**Capability angle:** The canonical arXiv-blessed mechanism for "what new papers appeared in category X since date Y." Supports incremental daily harvest. The OAI-PMH set hierarchy lets a notebook driver subscribe to `math:math.AG` and receive all new submissions automatically. This is the existing delta mechanism (E11) — the discovery feature is a matter of connecting the notebook's category to this existing channel.

**Technical angle:** OAI-PMH does NOT support keyword/topic filtering — only category sets and date ranges. A notebook with topic "Bridgeland stability" cannot use OAI-PMH alone to get only Bridgeland papers; it gets all math.AG papers and must post-filter. For narrow topics in broad categories (math.AG has ~500-1400 new papers/month), the agent must do semantic relevance filtering on the returned abstracts. OAI-PMH integration already exists in `ingest/oai_delta.py`.

**Cross-reference to arXMCP:** `ingest/oai_delta.py` (E11, fully shipped). This is not a net-new capability; it is an existing capability not yet connected to the notebook model. The gap is at the routing layer: nothing associates a notebook's topic area with the OAI-PMH category feed.

---

### Candidate 4: Semantic Scholar bulk search for topic discovery (no seed paper required)

**Capability name:** Keyword-based paper discovery with TLDR + SPECTER2 embeddings

**Source system:** Semantic Scholar Academic Graph API (`/graph/v1/paper/search/bulk`)

**Public evidence:** Live-verified: `GET https://api.semanticscholar.org/graph/v1/paper/search/bulk?query=Bridgeland+stability+conditions&fields=title,year,externalIds&limit=3` → 335 papers, each with `paperId`, `externalIds.ArXiv`, `externalIds.DOI`, year. Free tier, no authentication for basic search.

**Capability angle:** Richer semantic search than arXiv API alone. S2 searches full text of indexed papers (not just title/abstract), uses ML-based relevance ranking, and returns TLDR summaries and SPECTER2 embedding vectors for downstream semantic filtering. This allows agent-side pre-screening: fetch 50 candidates, embed the topic description, rank by SPECTER2 cosine similarity, queue top-10 for ingest. The `externalIds.ArXiv` field directly provides the arXiv ID needed by the existing `/e-print/` fetch path.

**Technical angle:** S2 bulk search is free but rate-limited (shared pool). TLDR and embedding fields require specifying `fields=tldr,embedding` — whether math papers have TLDR coverage is not confirmed (TLDR model was primarily trained on CS/biomedical). Coverage of pure math may be thinner than for CS. The `s2-folks` community repo was archived Jan 2025, indicating reduced S2 community engagement. Dependency: HTTP calls to `api.semanticscholar.org`; no SDK import needed.

**Cross-reference to arXMCP:** `ingest/graph_ingest.py:_fetch_openalex_work` — same pattern (external API call returning paper metadata). No analog on the MCP tool surface. The `externalIds.ArXiv` → arXiv ID bridge connects directly to `tools/arxiv_fetch.py:fetch_eprint`.

---

### Candidate 5: OpenAlex topic-filtered work search

**Capability name:** Topic-hierarchy-based paper discovery with referenced_works graph

**Source system:** OpenAlex API (`api.openalex.org/works`)

**Public evidence:** https://developers.openalex.org/api-entities/works/filter-works — filters: `primary_topic.id`, `primary_topic.field.id`, `topics.id`, `from_publication_date`, `to_publication_date`, `is_oa`, `has_doi`. Rate: $1/day free usage with key (approximately 10,000 list queries/day free).

**Capability angle:** OpenAlex Topics (the replacement for deprecated Concepts) provides a stable hierarchical classification of math sub-areas. A notebook's topic can be mapped to an OpenAlex Topic ID once (e.g., "Bridgeland stability conditions" → a stable Topic ID) and then used as a permanent subscription filter. The `referenced_works` field enables citation-graph walking to surface older foundational papers the agent might not have in the corpus.

**Technical angle:** OpenAlex does not expose a dedicated "similar papers" or "recommendations" endpoint (confirmed via developer docs). The `related_to` filter exists in the schema but is not a recommendation service. arXiv ID is not natively exposed as a filterable field (only DOI, PMID, PMCID, MAG, OpenAlex IDs listed in the schema — requires DOI-based crosswalk for arXiv papers). The cost model changed in late 2025 — previously free with politeness, now metered at $0.0001/list-query with $1/day free credit.

**Cross-reference to arXMCP:** `ingest/graph_ingest.py` (already uses OpenAlex for citation edges — `OPENALEX_POLITE_SLEEP_SECONDS=0.1`, `mailto=` polite-pool). The existing code fetches by arXiv-URL-as-identifier; the Topic-filter path is a different query shape. The `NotImplementedError` at `ingest/graph_ingest.py:58-66` was explicitly placed for the category-bulk-discovery path — this candidate is the correct resolution for that deferral.

---

### Candidate 6: arxiv-mcp-server community `research_alerts` tool

**Capability name:** Topic-watch registration with new-paper polling

**Source system:** blazickjp/arxiv-mcp-server (Apache-2.0 license, GitHub)

**Public evidence:** https://github.com/blazickjp/arxiv-mcp-server — tool: `research_alerts` — "Register topic watches and poll for newly published papers matching saved searches." Also exposes `citation_graph` (via Semantic Scholar — "Fetch references and citing papers via Semantic Scholar; works on any arXiv ID without requiring local download").

**Capability angle:** This community MCP server has already designed the exact UX: a tool that takes a topic description, stores it, and returns newly published matches on each poll. The shape confirms that the feature is implementable as a single MCP tool. The citation_graph tool's S2 delegation pattern is also directly relevant — it is a lightweight wrapper around S2's API, not a standalone computation.

**Technical angle:** This server uses pypdf / plain-text extraction — equations are destroyed (the exact failure mode documented in `.claude/notes/01-mission-and-context.md`). It is study-only per the no-fork policy. The `research_alerts` polling shape (register → poll) maps onto arXMCP's architecture as: a new column in `server/notebooks_store.py` (topic_keywords, discovery_category) plus a new MCP tool (`discover_papers`). License: Apache-2.0.

**Cross-reference to arXMCP:** `server/notebooks_store.py::SCHEMA_VERSION=4` — the notebook model has slugs, display names, and paper junction rows, but no `topic_keywords` or `discovery_category` columns. `server/tools.py::ALL_TOOLS` — 8 tools, no discover tool. This is net-new requiring both a schema migration and a new MCP tool registration.

---

### Candidate 7: crawl4ai for arXiv.org scraping (the user's stated approach) — NEGATIVE ASSESSMENT

**Capability name:** Browser-automation scraping of arXiv listing pages

**Source system:** unclecode/crawl4ai (Apache-2.0 license, GitHub; Python 3.10+; Playwright-based)

**Public evidence:**
- https://github.com/unclecode/crawl4ai — `AsyncPlaywrightCrawlerStrategy` is the default; robots.txt checking is opt-in via `config.check_robots_txt`.
- PR #1707 "Add Crawl-delay Directive Support from robots.txt" — closed/abandoned Mar 2026.
- Issue #1927 "MemoryAdaptiveDispatcher ignores max_session_permit" — open Apr 2026 (rate limiter bugs).
- `arxiv.org/robots.txt` — confirmed: generic bots → `Crawl-delay: 15`; `/search` path disallowed.
- arXiv API TOS: max 1 request per 3 seconds; multi-machine circumvention prohibited.

**Assessment of the crawl4ai approach — this is the core finding:**

crawl4ai is the wrong tool for four independent reasons:

1. **Redundancy.** arXiv API (Candidate 1) returns structured Atom/JSON for the identical data that scraping would extract from HTML. There is no information accessible via browser automation that is not available via the API.

2. **ToS non-compliance.** arXiv API TOS restricts automated access to 1 req/3s. Using Playwright instead of the API does NOT sidestep this limit — arXiv tracks by IP at the TCP layer. The robots.txt crawl-delay of 15s for generic bots (which Playwright appears as) is actually more restrictive than the API's 3s limit.

3. **robots.txt violation.** arXiv's `/search` path is explicitly disallowed for all bots. A keyword-search scraper must access `/search` to find papers by topic — the core use case falls on a disallowed path.

4. **Fragility.** arXiv's HTML markup for listings (`/list`, `/abs`) changes with UI redesigns. The API is versioned and stable. A Playwright-based scraper built on DOM selectors will break silently.

The user's stated hope that "scraping could sidestep arXiv's rate-limiting" is incorrect: arXiv rate-limits by IP at the network level, regardless of user-agent or endpoint used.

**Cross-reference to arXMCP:** No existing Playwright usage in arXMCP. The project's local-first, build-chain-free constraint (CLAUDE.md §2) is compatible with crawl4ai's Python API (no Node.js required), but the Playwright browser download (~300MB) conflicts with the minimal-dependency posture. The politeness contract (`tools/arxiv_fetch.py:POLITENESS_SLEEP_SECONDS=3.0`) is the baseline arXMCP already meets with the official API — crawl4ai would not improve on this.

---

### Candidate 8: arXiv RSS feeds for per-category new-paper notification

**Capability name:** Daily new-submission RSS feed per arXiv category

**Source system:** arXiv RSS (`export.arxiv.org/rss/{category}`)

**Public evidence:** `export.arxiv.org/rss/math.AG` — confirmed working endpoint (Atom feed for new math.AG submissions). Updated daily. No authentication required.

**Capability angle:** The simplest possible "what's new in math.AG today" signal. An ingest driver can poll the RSS feed daily, extract new arXiv IDs, optionally filter abstracts by topic keywords, and queue matching IDs for the full ingest pipeline. TOS-clean, no authentication, trivially parseable with Python's built-in `xml.etree` or `feedparser`.

**Technical angle:** RSS feeds are category-level only — no keyword sub-filtering at the feed level. For narrow topics the agent must pull the entire category feed and filter on the client side. math.AG typically has 15-30 new papers/day, making full-category pull feasible. The arXiv API with date-range filter is more controllable for batched backfill; RSS is better for lightweight daily notification.

**Cross-reference to arXMCP:** No existing RSS consumer in the codebase. Would be a new lightweight driver in `ingest/` (simpler than `ingest/oai_delta.py`), compatible with the existing `tools/arxiv_fetch.py` politeness contract.

---

### Candidate 9: Local citation + embedding neighborhood (Connected Papers pattern)

**Capability name:** Citation-graph + embedding hybrid neighborhood expansion

**Source system:** Connected Papers (`connectedpapers.com`) — closed, no API. ResearchRabbit (`researchrabbit.ai`) — closed, no API. Both are IDEA sources only (no-fork policy).

**Public evidence:** Both are web applications with no documented public HTTP API. Assessment based on published descriptions of their algorithmic approach (citation graph + semantic similarity hybrid).

**Capability angle:** The combination of citation-graph walking and embedding similarity is the correct algorithm for "given a notebook's current papers, surface conceptually related papers not yet in the corpus." arXMCP already has both components: `server/graph_queries.py::cite_neighbors` (Kùzu citation graph, E09_S03) for the graph dimension, and `server/retrieval/ann.py` (BGE-M3 ANN search, E03) for the embedding dimension. The capability gap is that nothing combines them into an outward-facing discovery query.

**Technical angle:** Both external systems are closed products; nothing to call. The local implementation would: (1) take the set of paper_ids in a notebook, (2) walk 2-hop cite_neighbors, (3) score each neighbor by BGE-M3 cosine similarity to the notebook's topic description, (4) return the top-N paper_ids not already in the notebook. This is entirely local and does not require any external API call.

**Cross-reference to arXMCP:** `server/graph_queries.py::cite_neighbors` + `server/retrieval/ann.py` — the building blocks exist. No tool combines them. The gap is a new handler in `server/handlers/` that takes `{notebook_slug, topic_description, k}` and emits ranked paper_ids not yet in the notebook.

---

### Candidate 10: LeanSearch / Moogle for Mathlib theorem-level discovery (orthogonal scope)

**Capability name:** Natural-language → Mathlib4 formalized theorem retrieval

**Source system:** LeanSearch (`leansearch.net`, AI4M Team at BICMR@PKU; no public API), Moogle (`loogle.lean-lang.org`; type-directed Mathlib search)

**Public evidence:** https://leansearch.net/ — "Find theorems in Mathlib4 using natural language query." Query Augmentation feature. No documented HTTP API.

**Capability angle:** Relevant for the autoformalizer/tactician pipeline roles (not paper discovery): "does this claimed lemma already exist in Mathlib as a formalized theorem?" A positive hit means the agent can reference the Mathlib theorem directly in its Lean proof instead of asking arXMCP to surface the underlying paper. Closes an agent-workflow gap that currently forces the autoformalizer to guess.

**Technical angle:** No public API; Moogle is web-only. Any arXMCP integration would require maintaining a local Mathlib4 name index (similar to `server/theorem_names_store.py` but over Mathlib4 declarations). This is a separate effort from paper discovery and belongs in a different milestone.

**Cross-reference to arXMCP:** `server/handlers/lemma.py::handle_find_lemma_by_name` + `server/theorem_names_store.py` (E10_S02) — arXiv theorem-name lookup is the analog; LeanSearch covers the orthogonal corpus (Mathlib4 formal proofs vs arXiv informal papers). Net-new capability, out of scope for the paper-discovery feature but worth flagging.

---

## 3. Sources reviewed

| System | URL reviewed | What was actually read | High signal? |
|---|---|---|---|
| crawl4ai | github.com/unclecode/crawl4ai (README + async_webcrawler.py source + GitHub issues) | License (Apache-2.0), Python 3.10+ req, Playwright backend, robots.txt opt-in, PR #1707 closed, rate-limiter bug #1927 | Yes |
| arXiv API manual | info.arxiv.org/help/api/user-manual.html | Query parameters, date-range filter (`submittedDate`), category filter (`cat:`), max_results cap (30K), rate limit (1 req/3s) | Yes |
| arXiv API ToS | info.arxiv.org/help/api/tou.html | Rate limits, prohibited activities, redistribution constraints | Yes |
| arXiv robots.txt | arxiv.org/robots.txt | Generic bots: Crawl-delay 15s; `/search` disallowed; `/list` `/abs` allowed | Yes |
| arXiv OAI-PMH | info.arxiv.org/help/oa/index.html | Category sets, date-window harvesting, no keyword filtering | Yes |
| arXiv API live test #1 | export.arxiv.org/api/query (cat+ti query) | 55 results for Bridgeland+stability in math.AG title | Yes |
| arXiv API live test #2 | export.arxiv.org/api/query (cat+abs query) | 2,176 results for Bridgeland stability in math.AG abstract | Yes |
| Semantic Scholar overview | semanticscholar.org/product/api | Rate limits (1000 rps shared / 1 rps API key), Recommendations API listed, SPECTER2 embeddings, s2-folks archived Jan 2025 | Partial |
| S2 bulk search (live) | api.semanticscholar.org/graph/v1/paper/search/bulk | 335 results, each with paperId + externalIds.ArXiv + year | Yes |
| arxiv-mcp-server | github.com/blazickjp/arxiv-mcp-server | 5 tools: search_papers, download_paper, list_papers, read_paper, semantic_search (pro), citation_graph (experimental via S2), research_alerts (topic watch) | Yes |
| OpenAlex works filters | developers.openalex.org/api-entities/works/filter-works | Topic filters (primary_topic.id, topics.id), date filters, no arXiv ID filter | Partial |
| OpenAlex llms.txt | developers.openalex.org/llms.txt | Rate: $1/day free with key; no recommendations endpoint confirmed | Yes |
| ingest/graph_ingest.py | arXMCP worktree | OpenAlex politeness, NotImplementedError at lines 58-66 for category-discovery | Yes |
| ingest/oai_delta.py | CLAUDE.md §3 reference | E11 shipped; OAI-PMH delta loop in codebase | Partial (via CLAUDE.md) |
| tools/arxiv_fetch.py | arXMCP worktree | Politeness contract: 3s sleep, User-Agent, 503 backoff | Yes |
| server/notebooks_store.py | arXMCP worktree | Schema v4: notebooks + notebook_papers; no topic/category columns | Yes |
| server/tools.py | arXMCP worktree | 8 tools in ALL_TOOLS; no discover/recommend tool | Yes |
| Context7 | github.com/upstash/context7 | 2 tools (resolve-library-id, query-docs); live-doc injection model | Partial |
| Connected Papers | connectedpapers.com | No public API; site only showed tagline | No (blocked) |
| ResearchRabbit | researchrabbit.ai | Redirects to app; no API docs visible | No (blocked) |
| LeanSearch | leansearch.net | Natural-language Mathlib4 search; Query Augmentation; no public API | Partial |
| arXiv S3 bulk | info.arxiv.org/help/bulk_data_s3.html | Requester-pays; 2.7TB PDF + 2.9TB source; not free | Yes |
| zbMATH | zbmath.org/static/zbmath-open-api.html | HTTP 403 | No (blocked) |
| Elicit | elicit.com | HTTP 403 | No (blocked) |
| arXiv RSS (live) | export.arxiv.org/rss/math.AG | Feed confirmed working; structure: title, link, description channel | Partial |

---

## 4. Cross-references to arXMCP

- **Candidate 1 (arXiv API topic search):** New entry point into the existing `tools/arxiv_fetch.py` + `/e-print/` fetch pipeline. Closest existing code: `ingest/oai_delta.py` (which harvests by date, not by keyword). No analog on MCP tool surface (`server/tools.py::ALL_TOOLS`). Net-new ingest driver + optional MCP tool.

- **Candidate 2 (S2 recommendations):** Parallel to `ingest/graph_ingest.py`'s OpenAlex pattern (external HTTP call → arXiv ID list → existing ingest). `server/graph_queries.py::cite_neighbors` is the closest local analog but operates over the already-ingested Kùzu graph rather than the external S2 graph. No MCP analog.

- **Candidate 3 (OAI-PMH):** `ingest/oai_delta.py` (E11, shipped). Gap: no notebook → category subscription binding. The feature is a routing change, not a new capability.

- **Candidate 4 (S2 bulk search):** Same HTTP-call pattern as `ingest/graph_ingest.py:_fetch_openalex_work`. `externalIds.ArXiv` → `tools/arxiv_fetch.py:fetch_eprint` is the complete bridge. No MCP analog.

- **Candidate 5 (OpenAlex topic filter):** `ingest/graph_ingest.py:58-66` — the `NotImplementedError` for category-bulk-discovery is the exact placeholder this candidate fills. Existing `OPENALEX_POLITE_SLEEP_SECONDS=0.1` politeness applies.

- **Candidate 6 (arxiv-mcp-server research_alerts):** Study-only (Apache-2.0; no-fork). Confirms the tool shape: `discover_papers(notebook_slug, topic_keywords, category, since_date)` → list of new paper_ids. Requires schema migration in `server/notebooks_store.py` (add `topic_keywords TEXT`, `discovery_category TEXT`) and a new tool in `server/tools.py`.

- **Candidate 7 (crawl4ai):** No existing analog in arXMCP; explicitly assessed as wrong approach. robots.txt violation + ToS risk + redundancy with arXiv API make this a non-starter.

- **Candidate 8 (arXiv RSS):** No existing RSS consumer. Would be a new driver in `ingest/` simpler than `oai_delta.py`. Category-granularity only — requires client-side topic filtering.

- **Candidate 9 (local citation+embedding neighborhood):** `server/graph_queries.py::cite_neighbors` (Kùzu, E09_S03) + `server/retrieval/ann.py` (BGE-M3 ANN, E03) — both components exist. The gap is a new handler combining them: given notebook paper_ids, walk Kùzu citation graph, score neighbors by BGE-M3 embedding similarity to topic description, return ranked candidate paper_ids not yet in the notebook.

- **Candidate 10 (LeanSearch / Moogle):** `server/handlers/lemma.py::handle_find_lemma_by_name` + `server/theorem_names_store.py` (E10_S02) — arXiv theorem-name index is the analog but covers a different corpus (arXiv informal vs Mathlib4 formal). Net-new, orthogonal to paper-discovery scope.

---

## 5. Themes

**Official APIs make scraping unnecessary.** The arXiv API (confirmed live) handles keyword+category+date-range discovery cleanly. The Semantic Scholar bulk search (confirmed live) handles semantic/ML-ranked discovery with arXiv ID passthrough. Both are TOS-compliant, structured, and already match arXMCP's existing HTTP-call patterns. crawl4ai adds zero capability over these APIs while introducing ToS risk, robots.txt violations, and a Playwright dependency.

**The feature is an orchestration gap, not a capability gap.** arXMCP already has all the ingest machinery (arXiv API polite fetch, `/e-print/` download, LaTeXML parse, BGE-M3 embed, LanceDB write). What is missing is the binding: (1) a notebook declaring its topic keywords and target categories, and (2) a driver that periodically calls the arXiv API / S2 / OAI-PMH with those parameters and queues the resulting new paper_ids for the existing ingest pipeline.

**Local corpus enables an enrichment capability external tools cannot match.** Once papers are ingested, the Kùzu citation graph + BGE-M3 embeddings support a "discover papers in my citation neighborhood that score high on my topic embedding" query that is scoped to the already-curated corpus. This is more precise than global API results because it respects the human's existing curatorial choices. External recommendation APIs (S2, OpenAlex) return global results; the local-citation-neighborhood approach returns results that are already epistemically connected to the notebook's existing papers.

**The OAI-PMH channel (E11) is under-leveraged for topic-scoped notebooks.** The existing `ingest/oai_delta.py` delta loop harvests for a global category set. If each notebook could register a preferred `(category, topic_keywords)` pair, the delta loop could route newly harvested papers to the relevant notebook's ingest queue. This would make the discovery feature a lightweight routing addition to an already-shipped subsystem rather than a new subsystem.

---

## 6. Out of scope / parking lot

- **zbMATH Open API (MSC classification, formula search):** API page returned HTTP 403 during this scout run. Parked — zbMATH covers published literature with MSC codes; arXiv OAI-PMH + the arXiv API are stronger for preprint discovery in the target categories.

- **CrossRef API (DOI-based paper lookup):** CrossRef covers journal DOI resolution. For arXiv preprint discovery, arXiv's own API + S2 + OpenAlex are stronger. Parked.

- **arXiv S3 bulk data (Academic Torrents path):** Already documented in `.claude/notes/03-ingestion-pipeline.md` as the seed channel. Out of scope for incremental notebook-scoped discovery.

- **Elicit / Consensus (claim-extraction research assistants):** Both returned HTTP 403; no public API found. Even if accessible, their value is claim extraction and evidence synthesis (LLM-over-literature), not structured paper-ID discovery. The paper-discovery step must happen before Elicit-style analysis. Parked.

- **INSPIRE-HEP for discovery:** Already used in arXMCP (`ingest/inspire_ingest.py`, E09_S02) for citation enrichment on hep-th/math-ph papers. Its search API could theoretically support topic discovery for physics papers, but the arXiv API covers this more uniformly across all four target categories.

- **nLab concept graph:** Dense math concept wiki with heavy cross-linking. No machine-readable API for new-entry subscriptions. Useful as a concept-resolution resource for the autoformalizer but not a paper-discovery feed. Parked.

- **Academic Torrents:** Addressed in `.claude/notes/03-ingestion-pipeline.md`. Provides stale bulk dumps, not incremental new-paper discovery.

- **Nomic Atlas / embedding-based commercial neighborhood:** Commercial closed product. Not relevant given arXMCP's local-first BGE-M3 setup (Candidate 9 covers the local equivalent).
