# Research-Frontier Brief — crawl4ai Paper-Discovery Scout

**Scout run ID:** 2026q2-crawl4ai-paper-discovery  
**Date:** 2026-05-31  
**Scope:** Crawl4ai feasibility, arXiv ToS reality, paper-discovery methods for topic-driven corpus expansion, arXMCP ingest pipeline fit.

---

## 1. TL;DR

The three highest-value methods for topic-driven paper discovery are: **(1) OpenAlex Topics-filtered Works API** (structured, free, already partially wired in arXMCP's graph-ingest path, rate-limit far above arXiv's), **(2) SPECTER2 proximity embedding + nearest-neighbor candidate scoring** (title+abstract embeddings of candidate papers ranked against existing notebook chunks), and **(3) Semantic Scholar Recommendations API** (single-call "more like this" per seed paper, free with API key, handles citation-graph signals internally). Crawl4ai is the **wrong tool** for this feature: arXiv's ToS prohibits web scraping for bulk retrieval, crawl4ai's "stealth mode" and bot-detection bypass are explicit ToS violations, and arXiv's official APIs already cover the discovery surface with correct rate limits. The main thematic shift in 2024–2026 literature is from keyword-based to *topic-topology-aware* discovery: graph-signal (citation) and dense-embedding signals are being combined at the candidate-scoring layer rather than treated as alternative retrieval tracks.

---

## 2. Method Candidates

### M1 — OpenAlex Topics-Filtered Works API (Topic-Driven Discovery)

**Method name:** OpenAlex `/works` filter by `primary_topic.id` or `topics.id` with date-range filter  
**Year + author:** OpenAlex team (OurResearch), continuously maintained; Topics system launched 2023, stable as of 2025  
**Primary citation:** https://developers.openalex.org/api-entities/works/filter-works (API docs; not a paper)  
**Summary:** OpenAlex assigns every work a `primary_topic` from a four-level hierarchy (domain > field > subfield > topic). Given a notebook topic like "Bridgeland stability conditions", an agent can (a) search the `/topics` endpoint by `display_name` to resolve the topic ID, then (b) issue a filtered `/works` query (`filter=primary_topic.id:<ID>,from_publication_date:<date>,is_oa:true`) with pagination to retrieve all recently published papers in that area. This is the *category-bulk-discovery path* that `ingest/graph_ingest.py` explicitly documents as deferred (`NotImplementedError` in the `--category` branch; `CLAUDE.md §8` gotcha #3 notes that the deprecated Concept IDs were wrong). Topics replace the deprecated Concept system and cover arXiv papers via ML classification of titles/abstracts. Rate limit: 10 rps polite pool (with `?mailto=`), 100 rps with free API key — both far above arXiv's 1 req/3 s. Returns title, abstract, authors, publication date, DOI, `referenced_works` — everything needed to score and decide on ingest without hitting arXiv's bandwidth budget first.  
**Compute footprint:** Zero ML inference at query time. Network-only (stdlib `urllib.request`). A topic-search + one-page Works fetch completes in < 2 s wall time.  
**Implementation complexity:** ~150 LOC over the existing `ingest/graph_ingest.py` infrastructure. The `_fetch_openalex_work`, `_build_works_url`, politeness-sleep, and checkpoint patterns are fully reusable. Add `_fetch_topic_id_by_name(query)` (GET `/topics?search=<query>`) and `_fetch_works_for_topic(topic_id, from_date, max_results)` (GET `/works?filter=...`). No new dependencies.  
**arXMCP fit:** `ingest/graph_ingest.py` — implements the existing `--category` stub. New entry point: `ingest/topic_discovery.py`. Results feed directly into the standard `ingest_one_paper` pipeline (E11_S01).  
**Maturity signal:** Production API, used by Elicit, Semantic Scholar, ResearchRabbit. OpenAlex has 250M+ works, math.AG / math.NT coverage is strong (mirrors arXiv for post-2010 math). Apache-2.0 data license on metadata.

---

### M2 — SPECTER2 Proximity Adapter (Relevance Scoring for Candidate Papers)

**Method name:** SPECTER2 `allenai/specter2` proximity adapter — dense retrieval over title+abstract  
**Year + author:** Cohan et al. (Allen AI), 2022/2023; benchmarked in SciRepEval and MDCR  
**Primary citation:** https://huggingface.co/allenai/specter2 (model card; the associated paper arXiv ID could not be positively confirmed in this scan — the HuggingFace model card is the verified source)  
**Summary:** SPECTER2 is a family of adapter-augmented scientific embedding models. The `proximity` adapter (for nearest-neighbor / link-prediction tasks) encodes paper title+abstract into a 768-dim vector. It outperforms original SPECTER on SciRepEval (71.1% vs 67.5% avg) and MDCR citation recommendation (MAP 38.4 vs 30.6). For arXMCP's paper-discovery use case: embed each *candidate* paper (from OpenAlex or arXiv API) using SPECTER2 proximity, embed the notebook's existing chunks using the same model (or project via cosine similarity from BGE-M3 space), and rank candidates by cosine similarity to the notebook centroid. This gives a relevance score without running the full ingest pipeline on every candidate. The 2024 Church et al. paper (arXiv:2407.05836, verified) identifies the SPECTER/graph hybrid as the strongest approach and SPECTER2 as the current generation of this content-based signal.  
**Compute footprint:** 110M parameters (BERT-base scale). CPU inference: ~50 ms/paper title+abstract on M-series Mac. A 500-candidate batch scores in ~25 s CPU. The `adapters` library (not `peft`) is required — distinct install from standard transformers.  
**Implementation complexity:** ~200 LOC. New `ingest/candidate_scorer.py` that (a) loads SPECTER2 once at module level, (b) exposes `score_candidates(notebook_chunk_ids, candidate_abstracts) -> list[float]`, (c) uses cosine similarity between candidate embedding and mean of notebook chunk embeddings. Runs before `ingest_one_paper` so only high-scoring candidates enter the parse/embed pipeline. OSS: Apache-2.0 (model weights), MIT (`adapters` library).  
**arXMCP fit:** New module `ingest/candidate_scorer.py`, called from `ingest/topic_discovery.py` before triggering per-paper ingest. Keeps BGE-M3 as the production retrieval embedder (unchanged); SPECTER2 is a pre-ingest filter only. Alternative: use BGE-M3 directly (already loaded) by computing cosine similarity between candidate abstract embeddings and the notebook's chunk centroid — avoids loading a second model entirely.  
**Maturity signal:** HuggingFace model, 500+ downloads/month, evaluated in two peer-reviewed benchmarks, used in production by Semantic Scholar. License: Apache-2.0.

---

### M3 — Semantic Scholar Recommendations API (Citation-Graph-Aware "More Like This")

**Method name:** Semantic Scholar Graph API `/recommendations/v1/papers/forpaper/{paper_id}` and multi-paper variant  
**Year + author:** Allen AI / Semantic Scholar team; stable since 2022, continuously updated  
**Primary citation:** https://api.semanticscholar.org/api-docs/ (official docs; not a paper)  
**Summary:** The S2 Recommendations API returns papers similar to a given seed paper (single-paper endpoint) or a positive/negative example set (multi-paper endpoint). Internally it combines citation-graph signals (co-citation, bibliographic coupling) with SPECTER2 embeddings — precisely the hybrid that Church et al. (arXiv:2407.05836) identifies as the strongest approach. For arXMCP: given a notebook's seed papers (already in the Kùzu graph via `ingest/graph_ingest.py`), iterate over seed paper IDs, call S2 recommendations, deduplicate results, score by recommendation frequency (how many seeds surfaced the same paper), and pass high-scoring candidates to the ingest pipeline. S2 paper ID → arXiv ID mapping is in the `externalIds.ArXiv` field of the response. PaperQA2 (Apache-2.0, `notes/10-references-and-prior-art.md`) uses the same S2 integration pattern.  
**Compute footprint:** Zero local ML. HTTP only. 10 seed papers at 1 req/s = 10 s sweep. Each call returns up to 500 candidate papers.  
**Implementation complexity:** ~120 LOC. New `ingest/s2_recommend.py`: GET `https://api.semanticscholar.org/recommendations/v1/papers/forpaper/{s2_id}`, parse JSON, deduplicate by arXiv ID, score by frequency, resolve arXiv IDs for candidates. Needs 1 s polite sleep between calls. No new dependencies beyond stdlib.  
**arXMCP fit:** `ingest/s2_recommend.py` feeds arXiv IDs into the standard ingest pipeline. Integrates with `ingest/graph_ingest.py`'s checkpoint pattern. S2 paper IDs can be obtained via the `/paper/arXiv:{arxiv_id}` lookup endpoint for each seed paper.  
**Maturity signal:** Production API used by Elicit, PaperQA2. Free tier generous (1 req/s without key, higher with free API key). CC-BY-4.0 on metadata. No data redistribution required for in-pipeline use.

---

### M4 — arXiv Search API with `cat:` + `submittedDate` Filter (Official Topic Discovery)

**Method name:** arXiv Atom API v1 — `cat:` category filter + keyword `abs:` search + `submittedDate` range  
**Year + author:** arXiv.org; API stable since 2009; OAI-PMH variant (E11_S02) already shipped in arXMCP  
**Primary citation:** https://info.arxiv.org/help/api/user-manual.html  
**Summary:** The arXiv Atom API supports `cat:math.AG`, `cat:math.NT`, `cat:hep-th`, `cat:math-ph` filters with `submittedDate` range queries and `sortBy=submittedDate&sortOrder=descending`, returning up to 2000 papers per call (30000 total per query). For topic-specific discovery: `search_query=abs:bridgeland+AND+cat:math.AG&sortBy=submittedDate&sortOrder=descending` returns recently submitted topic-targeted papers. Rate limit: 1 req/3 s (same as bulk harvest; arXiv ToS confirmed). Already understood in arXMCP: `ingest/oai_delta.py` uses OAI-PMH for bulk date-ordered harvest; the Atom API is the *search-interface* complement for keyword + category targeted pulls. The OAI-PMH path is for bulk harvest; the Atom API is for topic-specific discovery within arXiv's 30k-paper query window. Pagination via `start` + `max_results` (max 2000/call).  
**Compute footprint:** Zero ML. Network only. Parses Atom XML via stdlib `xml.etree`. A 100-paper topic-filtered search takes ~5 s at polite rate.  
**Implementation complexity:** ~100 LOC reusing `tools/arxiv_fetch.py` patterns (`build_user_agent`, `parse_retry_after`, 3 s politeness sleep). New `ingest/arxiv_search.py` exposing `search_papers(query, categories, from_date, max_results) -> list[ArxivPaper]`.  
**arXMCP fit:** Complementary to M1 (OpenAlex gives broader cross-venue coverage; arXiv Atom gives keyword precision within arXiv). Both feed into `ingest_one_paper`. No new dependencies.  
**Maturity signal:** Canonical official API, used by every arXiv MCP server reviewed in `notes/10-references-and-prior-art.md`. Strictly rate-limited but entirely sufficient for notebook-scale discovery (< 200 papers per session).

---

### M5 — Citation Graph Snowballing via Existing `cite_neighbors` (Forward/Backward Expansion)

**Method name:** Bidirectional citation snowballing on the existing Kùzu citation graph + OpenAlex referenced_works expansion  
**Year + author:** arXMCP internal capability (E09_S03); snowballing methodology is classical  
**Primary citation:** `server/graph_queries.py::cite_neighbors` — "the library is real; the MCP tool handler is a v1 stub" (`CLAUDE.md §7`)  
**Summary:** Citation snowballing expands a seed set by following reference chains. arXMCP already has the Kùzu graph and `cite_neighbors(direction="cited_by", depth=2)` for backward chaining. For topic-discovery: (1) identify the notebook's seed papers, (2) call `cite_neighbors(direction="cites", depth=1)` to get forward references, (3) call `cite_neighbors(direction="cited_by", depth=1)` to get papers that cite the seeds, (4) for out-of-corpus neighbors (which have `chunk_id=None`), resolve via OpenAlex to get abstracts, (5) score with M2 or M3 and ingest high-scoring ones. The Church et al. 2024 paper (arXiv:2407.05836) empirically confirms that combining content-based (SPECTER) and graph-based (citation) signals outperforms either alone. This is the "co-citation" signal without any new model or API beyond what arXMCP already has.  
**Compute footprint:** Zero ML for the graph traversal. Adds N OpenAlex HTTP calls for out-of-corpus neighbor resolution (reuses existing `_fetch_openalex_work`). At depth=1 with 20 seed papers and ~30 neighbors each, worst case ~600 OpenAlex calls = ~60 s at polite rate.  
**Implementation complexity:** ~80 LOC coordinating existing components. `await cite_neighbors(chunk_id, direction="cited_by", depth=1)` is already callable from any async context. New logic: filter `chunk_id=None` results, batch-resolve via `_fetch_openalex_work`, score, ingest. Reuses all existing infrastructure.  
**arXMCP fit:** This is a zero-new-dependency capability delta. Works against the live Kùzu graph without new ingest. Main gap: `cite_neighbors` as an MCP tool is a stub — but the library is callable directly from any ingest-side driver.  
**Maturity signal:** Method is classical; arXMCP graph infra is shipped and tested (2100 tests pass per `CLAUDE.md §3`). No external dependency risk.

---

### M6 — Hybrid Sparse+Dense Scoring for Candidate Ranking

**Method name:** BM25 over abstracts + dense cosine similarity (SPECTER2 or BGE-M3) fused via RRF  
**Year + author:** Mandikal & Mooney (UT Austin), SDU-AAAI 2024, arXiv:2401.04055 (verified)  
**Primary citation:** arXiv:2401.04055 — "Sparse Meets Dense: A Hybrid Approach to Enhance Scientific Document Retrieval"  
**Summary:** This peer-reviewed paper evaluates BM25 vs SPECTER2 for scientific document retrieval in a niche domain (cystic fibrosis), finding that a linear hybrid "yields significantly better results" than either alone, and that SPECTER2 dense vectors alone "do not significantly enhance performance" in low-resource specialized domains. For arXMCP's candidate-scoring step: candidates retrieved via M1/M3/M4 can be re-ranked using BM25 over their abstracts (against the notebook's existing chunk text) combined with cosine similarity to the notebook centroid, fused with RRF. This directly parallels arXMCP's existing BM25→ANN→RRF pipeline but operating at the *pre-ingest candidate* level. Compute overhead is minimal since BM25 on raw text requires no model. RRF is already implemented in `server/retrieval/`.  
**Compute footprint:** BM25 scoring: < 1 ms per candidate at notebook scale (rank 100-500 candidates). Combined with M2 SPECTER2 dense: see M2. RRF fusion: negligible.  
**Implementation complexity:** ~60 LOC. Reuse `ingest/bm25_indexer.py` patterns for scoring candidate abstracts against notebook chunk text. Combine BM25 rank with dense similarity rank via RRF using existing `server/retrieval/` patterns.  
**arXMCP fit:** `ingest/candidate_scorer.py` (same module as M2). BM25 pre-filter reduces the candidate set before any ML inference. No new dependencies.  
**Maturity signal:** Peer-reviewed AAAI workshop paper, 2024. Method is a straightforward combination of two well-established techniques. No new dependencies.

---

## 3. Sources Reviewed

| Venue / Source | URL pattern | Pages/papers scanned | High signal |
|---|---|---|---|
| crawl4ai GitHub | github.com/unclecode/crawl4ai | 1 (README) | NO — wrong tool; ToS violation |
| arXiv ToS | info.arxiv.org/help/api/tou.html | 1 | YES — critical constraints confirmed |
| arXiv API user manual | info.arxiv.org/help/api/user-manual.html | 1 | YES — M4 directly |
| arXiv bulk data | info.arxiv.org/help/bulk_data.html | 1 | YES — S3 + OAI-PMH context |
| arXiv cs.IR recent | arxiv.org/list/cs.IR/recent | ~20 listings | PARTIAL — 3 high-signal hits |
| arXiv search (various queries) | arxiv.org/search/?query=... | ~8 searches | LOW — search surface is noisy |
| OpenAlex developer docs | developers.openalex.org | 3 pages | YES — M1 directly |
| Semantic Scholar API | semanticscholar.org/product/api, api-docs | 2 pages | YES — M3 directly |
| SPECTER2 HuggingFace | huggingface.co/allenai/specter2 | 1 | YES — M2 directly |
| PaperQA2 GitHub | github.com/Future-House/paper-qa | 1 (README) | YES — confirms S2 integration pattern |
| arXiv:2401.04055 (Sparse Meets Dense) | arxiv.org/abs/2401.04055 | 1 | YES — M6 |
| arXiv:2407.05836 (Church et al., CBF+GB) | arxiv.org/abs/2407.05836 | 1 | YES — confirms M5 hybrid rationale |
| arXiv:2604.17680 (MasterSet) | arxiv.org/abs/2604.17680 | 1 | MEDIUM — benchmark context for M6 |
| arXiv:2605.27610 (Eliot) | arxiv.org/abs/2605.27610 | 1 | MEDIUM — trend-visualization pattern |
| arXiv:2512.00986 (ADRA-Bank) | arxiv.org/abs/2512.00986 | 1 | LOW — framing only |
| arXiv:2404.16130 (GraphRAG) | arxiv.org/abs/2404.16130 | 1 | LOW — not paper-discovery |
| arXiv:2409.11136 (Promptriever) | arxiv.org/abs/2409.11136 | 1 | LOW — query-retrieval, not discovery |
| notes/10-references-and-prior-art.md | local | full read | YES — de-duplication baseline |
| CLAUDE.md §3–8 | local | full read | YES — arXMCP capability baseline |

---

## 4. Themes

The 2024–2026 literature confirms that **citation-graph + dense-embedding hybrid signals** consistently outperform either alone for academic paper recommendation, empirically validated by Church et al. (2024) and supported by MasterSet (2026). The trend is toward *pre-ranking candidate sets* using lightweight signals (BM25, SPECTER2 on abstract) before committing to expensive per-paper ingest — directly aligned with what arXMCP needs for notebook-scale discovery. A second theme is **API-first discovery displacing scraping**: OpenAlex Topics, Semantic Scholar Recommendations, and the arXiv Atom API collectively cover the topic-discovery surface that crawl4ai was proposed for, with better rate limits, structured metadata, and zero ToS risk — web scraping of arXiv is both unnecessary and prohibited. A third theme is **agentic iterative discovery** (ADRA-Bank, Eliot, deep-research agents), where retrieval is multi-turn and topic-adaptive, but these require per-session LLM calls and are higher complexity than the notebook-expansion use case arXMCP targets; they belong in a future milestone rather than the initial feature.

---

## 5. Already in arXMCP / Already Considered

- **BGE-M3 dual-column embedding + BM25 + RRF hybrid retrieval** — `server/retrieval/`, `ingest/embedder.py`, `ingest/bm25_indexer.py` (E07). Covers chunk-level retrieval; the gap is using these for *candidate scoring before ingest*.
- **Citation graph traversal (`cite_neighbors`)** — `server/graph_queries.py` (E09_S03). Library is real; M5 proposes wiring it as a discovery driver.
- **OpenAlex Works API** — `ingest/graph_ingest.py` (E09_S01). Fully wired for per-paper resolution; the `--category` / topic-search path is explicitly `NotImplementedError`. M1 closes this gap.
- **OAI-PMH delta harvesting** — `ingest/oai_delta.py` (E11_S02). Covers bulk date-ordered harvest of new papers; not keyword/topic-targeted. M4 is the complementary search-API path.
- **SPECTER2** — `notes/10-references-and-prior-art.md §Embedding models`. Listed as a citation-aware baseline; not yet used in arXMCP. M2 proposes using it as a pre-ingest candidate filter.
- **Semantic Scholar** — `notes/10-references-and-prior-art.md §Citation graph data sources`. Listed as a backup data source; Recommendations API not yet used.
- **arXiv politeness contract (3 s sleep, User-Agent)** — `tools/arxiv_fetch.py::POLITENESS_SLEEP_SECONDS`, `build_user_agent`. Fully implemented; M4 reuses this for Atom API calls.
- **ColBERTv2** — `notes/10-references-and-prior-art.md §Inspirational systems`. Already noted as Tier-6 / v1.5 candidate; not re-surfaced.
- **SPECTER1 (original)** — `notes/10-references-and-prior-art.md §Embedding models`. Already noted; SPECTER2 (M2) is the current generation.

---

## 6. Out of Scope / Parking Lot

- **crawl4ai (arXiv scraping path):** Explicit ToS violation. arXiv's ToS prohibits scraping and crawl4ai's "stealth mode" / bot-detection bypass makes the violation worse. The tool is valuable for sites without official APIs; arXiv has excellent official APIs. Rejected on ToS grounds, not just technical grounds.
- **crawl4ai rate-limit sidestep claim:** False premise. arXiv's rate limit (1 req/3 s) applies to all automated access regardless of whether you use the API or scrape the HTML. The ToS explicitly prohibits circumventing limits via any mechanism. Scraping HTML would also lose structured metadata (categories, arXiv IDs in canonical form, submit date) that the API returns directly.
- **GraphRAG (arXiv:2404.16130, ms-research/graphrag, MIT):** Addresses global Q&A over an existing corpus, not external paper discovery. Out of scope for this feature.
- **Promptriever (arXiv:2409.11136):** Instruction-tuned retrieval within a fixed local corpus, not discovery of new external papers. Out of scope for this feature.
- **OmniThink / SFR-RAG-9B / SafeRAG:** Long-form generation, small RAG LLMs, RAG security — none relevant to paper discovery.
- **ADRA-Bank (arXiv:2512.00986):** Evaluation benchmark for deep research agents; useful framing but no adoptable method.
- **Eliot clustering for operator UX (arXiv:2605.27610):** Interesting visualization enhancement but not required for the core discovery feature. Parking lot for a future UI milestone. Dependencies (`sentence-transformers`, `umap-learn`) would add weight without improving discovery quality.
- **MasterSet (arXiv:2604.17680):** Citation recommendation benchmark confirming no single technique (sparse/dense/graph) dominates must-cite retrieval. Supports M6 hybrid rationale; the benchmark itself is not adoptable.
- **Amazon S3 full-corpus arXiv download:** Wildly out of scope for notebook-scale topic discovery. Relevant only for a future full-corpus ingest milestone (beyond E12 which was scoped out).
- **LLM-generated keyword queries (PaperQA2 pattern for external search):** PaperQA2 uses LLM-generated keywords to search *within a local corpus*. Extending to external discovery requires a Claude API call per session, adding latency and cost. Deferred to a future agentic-search milestone.

---

*Scout: Research-Frontier / 2026q2-crawl4ai-paper-discovery*  
*Model: claude-sonnet-4-6*
