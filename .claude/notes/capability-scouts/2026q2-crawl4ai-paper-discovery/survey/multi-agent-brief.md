# Multi-Agent Capability Scout Brief
# 2026q2 — crawl4ai Paper Discovery for arXMCP Notebooks
# Scout ID: 2026q2-crawl4ai-paper-discovery

**Date:** 2026-05-31
**Scope theme:** Autonomous literature discovery / corpus expansion for notebooks; crawl4ai fit analysis; arXiv ToS and rate-limit reality; architecture of "discover new papers for this notebook topic" feature
**arXMCP current state baseline:** 8-tool MCP surface (TOOL_SCHEMA_VERSION=16); OAI-PMH delta harvester (`ingest/oai_delta.py`); bulk ingest orchestrator (`ingest/bulk_ingest.py`); citation graph expansion via `cite_neighbors` (Kùzu); BM25+ANN+RRF+BGE-reranker hybrid retrieval; no forward-discovery of un-ingested papers by topic; no agent-facing "discover related papers" tool.

---

## 1. TL;DR

**Top-3 multi-agent capabilities most relevant to autonomous paper discovery for arXMCP notebooks:**

1. **Semantic Scholar Recommendations API with SPECTER2 seeds** — a production-grade, no-scraping, rate-limit-safe path to "given papers already in this notebook, find the 500 most related un-ingested recent papers" via positive-seed recommendations. Returns arXiv IDs directly; feeds straight into the existing `ingest/bulk_ingest.py` per-paper pipeline. This is the correct discovery channel.

2. **arXiv API keyword+category+date search (`export.arxiv.org/api/query`)** — the already-understood, already-integrated-in-spirit channel for topic-seeded discovery. Search `abs:"Bridgeland stability" AND cat:math.AG` with `submittedDate` filtering to pull new papers. Does not require browser automation. Respects TOS at 3-second cadence. arXMCP already honors this cadence in `tools/arxiv_fetch.py:POLITENESS_SLEEP_SECONDS=3.0`.

3. **Deterministic ingest job (not LLM-in-the-loop)** — the "discover papers for notebook" feature should be a **server-side background job** triggered by the operator or by the calling agent, NOT an LLM-driven crawl loop. The discovery phase (find arXiv IDs by topic/recommendation) is deterministic; the relevance judgment is deferred to the agent retrieving over the newly-ingested corpus. This matches arXMCP's design philosophy: "valuable LLM roles live upstream of verification; invest in retrieval/pre-loading, not adversarial-LLM critique" (`.claude/notes/01-mission-and-context.md`).

**Main architectural gap:** arXMCP has no "topic-seeded forward discovery of un-ingested papers" path. The OAI-PMH delta loop (`ingest/oai_delta.py`) pulls all new papers from 4 fixed categories; there is no per-notebook, per-topic, targeted discovery of papers by semantic similarity or keyword. crawl4ai is the wrong tool for this gap — the right tools are arXiv API keyword search and the Semantic Scholar Recommendations API, both of which arXMCP's existing ingest infrastructure can directly consume.

---

## 2. Multi-agent candidates

---

### Candidate 1 — Semantic Scholar Recommendations API (positive-seed discovery)

**Name + citation/URL:** Semantic Scholar Academic Graph API — Recommendations endpoint. `https://api.semanticscholar.org/recommendations/v1/papers`. Launched formally ~2023; documented at `https://www.semanticscholar.org/product/api`.
**Year + venue:** 2023 (v1); still active 2026. Allen Institute for AI (Ai2). Production REST API.

**What it does:** Takes a list of `positivePaperIds` (papers the user finds relevant) and optionally `negativePaperIds` (papers to exclude flavor), and returns up to 500 recommended papers "selected from papers published within the past 60 days." Papers can be referenced by arXiv ID (e.g., `arXiv:2301.00001`) as an external identifier alongside the Semantic Scholar internal ID. The single-seed variant (`/recommendations/v1/papers/forpaper/{PAPER_ID}`) works without a list. SPECTER2 embeddings (768-dim, citation-graph-trained) are the underlying similarity signal. The API is free; API key required (self-service via partner form). Response includes `title`, `url`, `venue`, and with field expansion: `abstract`, `externalIds` (which includes `ArXiv`), `year`, `tldr`.

**What's NEW vs arXMCP today:** arXMCP has `cite_neighbors` for backward/forward citation expansion within the *already-ingested* Kùzu graph (`server/handlers/citations.py`; `server/graph_queries.py`). But `cite_neighbors` only traverses papers already in the corpus. There is no mechanism to discover semantically similar *un-ingested* papers by topic seed. The S2 Recommendations API closes this exact gap: given a notebook's existing paper set as positive seeds, it returns the most similar recent papers that arXMCP has not yet ingested. These arXiv IDs feed directly into `ingest/bulk_ingest.py::ingest_one_paper()` — the same pipeline that the OAI-PMH delta loop uses.

**Architectural fit:**
- Net-new: `ingest/s2_discovery.py` — async function `discover_by_seeds(paper_ids: list[str], k: int = 100) -> list[str]` that calls the Recommendations API with the notebook's ingested `paper_id` set as positive seeds and returns new arXiv IDs not yet in LanceDB
- Net-new: CLI entrypoint (or extend `Makefile`) — `make discover NOTEBOOK=<slug> [K=100]` triggers discovery + ingest
- Extend: `server/routes/notebooks.py` — add `POST /ui/api/notebooks/{slug}/discover` operator-console action that (a) enumerates the notebook's paper IDs from LanceDB, (b) calls S2 discovery, (c) queues results into the existing `IngestTaskTracker` pipeline
- No new MCP tool required at v1 — the operator triggers discovery from the console; the agent retrieves over the expanded corpus

**Cache interaction:** No new MCP tools → no `EXPECTED_TOOL_SCHEMA_SHA256` re-pin. BP1 is unaffected. The `corpus_version` in `server/corpus.py` increments after the expanded ingest commits to LanceDB, which is the correct invalidation signal for all 3 retrieval cache tiers (notes/07 §"Tier 1: exact-query memo" — cache keys include `corpus_version`). No BP1/BP2 impact.

**Maturity signal:** Production REST API, Ai2, free tier. SPECTER2 embeddings are published (huggingface.co/allenai/specter2, Apache-2.0). The Python `semanticscholar` library (PyPI, MIT) wraps the API. Code available; production citations: Connected Papers is built on S2 APIs. High-signal.

**Architecture-lock check:** The S2 API is called at ingest time (a background job), not at query time and not by the MCP server itself. No LLM call by the server. Clean.

---

### Candidate 2 — arXiv API keyword+category+date search (`export.arxiv.org/api/query`)

**Name + citation/URL:** arXiv API, `https://export.arxiv.org/api/query`. Documented at `https://info.arxiv.org/help/api/user-manual.html`. TOS: `https://info.arxiv.org/help/api/tou.html`.
**Year + venue:** 2008 (launched); continuously maintained. arXiv / Cornell. Production REST API.

**What it does:** Boolean keyword search over title (`ti:`), abstract (`abs:`), and category (`cat:`), with date-range filtering (`submittedDate:[YYYYMMDDTTTT+TO+YYYYMMDDTTTT]`). Returns Atom XML with full metadata per paper: title, abstract, authors, categories, submission date, arXiv ID, DOI. Max 2,000 results per call, up to 30,000 total paginated. Rate limit: "no more than one request every three seconds" (same as the arXiv /e-print/ fetch politeness contract already implemented at `tools/arxiv_fetch.py:POLITENESS_SLEEP_SECONDS=3.0`). No authentication required. Search is keyword-only (no embedding/semantic search). The query `cat:math.AG AND abs:"Bridgeland stability"` returns papers in the right category mentioning the topic in the abstract.

**What's NEW vs arXMCP today:** The OAI-PMH delta loop (`ingest/oai_delta.py`) already harvests all new papers from 4 fixed category sets daily. What does not exist is a **per-topic query** inside those categories for targeted discovery: "find new papers in math.AG that specifically mention Bridgeland stability conditions." The arXiv API `abs:` search fills this gap. The delta loop is category-wide (everything in math.AG); the API search is topic-targeted.

**Architectural fit:**
- Net-new: `ingest/arxiv_search.py` — `async def search_new_papers(query: str, category: str, since: datetime, max_results: int = 200) -> list[str]` that hits the arXiv API, parses Atom XML, deduplicates against already-ingested paper IDs from LanceDB, returns new arXiv IDs
- Extend: `server/routes/notebooks.py` — `POST /ui/api/notebooks/{slug}/discover-by-topic` operator-console form that takes a keyword query and routes through the above
- Rate-limit discipline: the existing `tools/arxiv_fetch.py::politeness_sleep()` is the correct primitive to reuse

**Cache interaction:** Same as Candidate 1 — no new tools, no BP1 impact. The `corpus_version` bump after ingest serves as the cache invalidation signal.

**Maturity signal:** Production, used by millions of clients, 15-year track record. The Python `arxiv` library (PyPI, MIT) wraps it. arXMCP already uses the sibling `/e-print/` endpoint with the same rate-limit discipline. High-signal, zero new infrastructure risk.

**Architecture-lock check:** Clean. API called at ingest time by a background job. No server-side LLM call.

---

### Candidate 3 — crawl4ai (the user's proposed tool) — NEGATIVE FINDING

**Name + citation/URL:** crawl4ai, `https://github.com/unclecode/crawl4ai`. PyPI: `crawl4ai`. Current stable: v0.8.6 (2026). Apache-2.0.
**Year + venue:** 2024 (first release); active 2026. Open-source.

**What it does:** An LLM-friendly async web crawler and scraper built on Playwright (Chromium). Supports JavaScript rendering, CSS/XPath/LLM-driven structured extraction, stealth mode for bot detection, and an agentic crawler sub-library for multi-step crawls. Requires a full browser process (Playwright/Chromium mandatory — no lightweight headless-without-browser mode). Rate-limiting config is available (`enable_rate_limiting`, `rate_limit_config`) but is NOT pre-configured for arXiv. Optional `check_robots_txt=True` exists but is not the default.

**Why it is the WRONG tool for this use case:**

1. **arXiv TOS violation risk.** arXiv's ToS (`info.arxiv.org/help/api/tou.html`) explicitly warns: "Continued rapid-fire requests from any site after access has been denied will be interpreted as an attack." arXiv provides OAI-PMH, the REST API, and RSS as the sanctioned programmatic paths. Browser-based scraping of `arxiv.org/abs/` pages circumvents the official API surface. arXiv's robots page explicitly directs users to "authorized machine access methods including OAI-PMH, the arXiv API, RSS feeds" — framing all other access as requiring advance administrator approval.

2. **robots.txt.** arXiv has maintained a robots.txt since 1994. crawl4ai's `check_robots_txt` defaults to False. Even when enabled, crawl4ai does not guarantee per-domain throttling at the 3-second arXiv politeness cadence.

3. **Playwright dependency weight.** crawl4ai's mandatory Playwright runtime (Chromium ~300 MB) is incompatible with arXMCP's local-first, no-heavy-dependency philosophy. arXMCP already avoids heavy binaries on the server path (see no-fork policy, CLAUDE.md §4.7). Adding a browser process to an ingest job violates that spirit.

4. **The user's hope is incorrect.** crawl4ai does NOT sidestep arXiv's rate limiting. It hits the same arXiv.org infrastructure as the official API, just without the politeness contract, explicit TOS coverage, or structured metadata. arXiv has been aggressively blocking scrapers since early 2026 (429 responses noted in API community discussions as of Feb 2026). A crawler hitting arxiv.org HTML pages risks IP block, not rate-limit bypass.

5. **arXiv abstract pages contain the same metadata as the API.** The abstract page for paper `2401.01234` displays the same title/abstract/authors the API returns — but the API returns it as structured XML, machine-parseable, at a documented rate limit, with metadata arXiv wants you to use.

6. **No math-fidelity benefit.** arXMCP's value over commodity arXiv scrapers is LaTeX→LaTeXML→MathML processing. crawl4ai extracts rendered HTML text. Scraping `arxiv.org/html/XXXXXXX` via crawl4ai would get the ar5iv HTML, but arXMCP already has `ingest/ar5iv_fetch.py` for this. crawl4ai adds nothing to the LaTeX processing pipeline.

**What's NEW vs arXMCP today:** Nothing useful for this specific use case. crawl4ai adds: Playwright-based JS rendering (arXiv abstract pages are static HTML — JS rendering adds nothing), LLM-driven extraction (contradicts no-server-side-LLM constraint), stealth/anti-bot techniques (irrelevant for arXiv's official API path).

**Architectural fit:** Not recommended for any component of arXMCP.
**Cache interaction:** N/A — not recommended.
**Maturity signal:** Active project, Apache-2.0, but fundamentally the wrong fit for this use case.

---

### Candidate 4 — Citegeist pattern: embedding-seeded diversity-weighted corpus expansion

**Name + citation/URL:** Citegeist: Automated Generation of Related Work Analysis on the arXiv Corpus. arXiv:2503.23229 (March 2025). Code: github.com/webis-de/citegeist.
**Year + venue:** March 2025, arXiv cs.IR/cs.CL.

**What it does:** Uses abstract-level embeddings (Sentence-Transformers `all-mpnet-base-v2`) over the full 2.6M-paper arXiv corpus to find related papers via cosine similarity, then applies a diversity-weighted selection formula `score = (1-w)*similarity + w*(1 - max_similarity_to_selected)` to pick a `breadth`-sized candidate pool that is both relevant AND diverse. Uses a Milvus vector DB backend for ANN search over the full arXiv corpus. The key insight: paper discovery is framed as a **diversified nearest-neighbor search** over paper embeddings — not as a web crawl and not as a keyword search.

**What's NEW vs arXMCP today:** arXMCP's `search_papers` tool retrieves chunks from the *already-ingested* corpus. There is no diversified-nearest-neighbor search over the FULL arXiv embedding space to surface un-ingested papers. Citegeist's pattern applied to arXMCP would look like: embed the notebook's topic description (or the centroid of the notebook's ingested paper embeddings), query an external index of ALL arXiv paper embeddings, retrieve the top-N un-ingested paper IDs, feed into `ingest_one_paper`. The S2 Recommendations API (Candidate 1) implements essentially this same pattern as a production service without requiring a local 2.6M-paper embedding index.

**Architectural fit:**
- The full Citegeist pattern requires a local Milvus ANN index over 2.6M paper embeddings — not aligned with arXMCP's local-first, single-workstation constraints (CLAUDE.md §4.1)
- The conceptual pattern IS aligned and is better served by S2 Recommendations API (Candidate 1), which does the diversified similarity search server-side over the full arXiv corpus and returns arXiv IDs
- Valuable as a design pattern reference: the diversity parameter (not just top-k by similarity) is the right heuristic for corpus expansion — you want papers that are relevant AND cover different sub-aspects of the topic

**Cache interaction:** Background ingest job — no BP1 impact.

**Maturity signal:** Paper + code (github.com/webis-de/citegeist, license unverified from available sources). Active 2025. Medium-signal for the pattern; low-signal for the specific implementation (Milvus overhead too large for arXMCP's constraints).

---

### Candidate 5 — Stop-RAG: value-function stopping criterion for iterative retrieval loops

**Name + citation/URL:** Stop-RAG: Value-Based Retrieval Control for Iterative RAG. arXiv:2510.14337 (October 2025). No code repo confirmed.
**Year + venue:** October 2025, arXiv cs.IR.

**What it does:** Casts iterative retrieval as a finite-horizon Markov Decision Process and trains a Q(λ) value function to decide when to stop fetching additional context. Outperforms both fixed-iteration baselines and LLM-based confidence self-assessment on multi-hop QA benchmarks. Key insight: LLMs are poor at judging "do I have enough context?" — a learned value function is better.

**What's NEW vs arXMCP today:** arXMCP's multi-agent pipeline has no explicit stopping criterion for "when has this notebook accumulated enough papers on this topic?" The paper's insight applies to corpus expansion: the decision of when to stop adding papers to a notebook should be a learned or heuristic function of "coverage sufficiency," not an LLM's self-assessment. Concretely: a discovery job that has run N iterations over the arXiv API and S2 Recommendations should stop when the marginal novelty of each new batch falls below a threshold — i.e., when newly-discovered papers are mostly already-ingested (high overlap ratio).

**Architectural fit:**
- Not immediately implementable in its full RL form: Stop-RAG requires a trained value function; arXMCP has no RL training loop
- The high-overlap-ratio stopping heuristic IS implementable deterministically: `stop_if: (new_arxiv_ids NOT IN existing_ids) / total_discovered < 0.1` — i.e., stop when 90%+ of newly-discovered papers are already in the corpus
- This is the right stopping criterion for `ingest/s2_discovery.py` (Candidate 1) — codified as a configurable `novelty_threshold` parameter
- No new MCP tools, no BP1 impact

**Cache interaction:** Internal to the ingest job. No BP1/tool surface impact.

**Maturity signal:** Paper only, no code. Conceptually sound; the deterministic heuristic analog is the actionable derivative.

---

### Candidate 6 — ReAct / planner-executor agent pattern: where should the intelligence live?

**Name + citation/URL:** ReAct (Yao et al., 2023, arXiv:2210.03629, ICLR 2023). Planner-executor synthesis: Reason-Plan-ReAct (arXiv:2512.03560, Dec 2025).
**Year + venue:** ReAct: ICLR 2023; RP-ReAct: December 2025.

**What it does:** ReAct interleaves LLM reasoning ("Thought") with tool invocations ("Action") and observations in a loop. The planner-executor variant separates a high-level planner (decides WHAT to do next) from an executor (implements each step via tool calls). For literature discovery this would mean: the calling Claude agent (Sketcher role) decides the search strategy (which topics, which depth), calls an MCP tool to execute each discovery step, and receives structured results to decide the next step.

**What's NEW vs arXMCP today:** arXMCP's current pipeline is a FIXED ingest job — the agent cannot steer corpus expansion during a session. A ReAct-style loop would let the Sketcher agent say "I searched for `Bridgeland stability`; the results cover moduli spaces but not K3 surfaces; let me search for `K3 surfaces stability` next." Two design options:

**Option A (recommended for v1):** The discovery feature is a **deterministic server-side job** triggered by the operator (via `/ui/api/notebooks/{slug}/discover`) or by the agent calling a new MCP tool. The agent is NOT in the discovery loop; it retrieves over the expanded corpus post-ingest. This matches arXMCP's no-server-side-LLM philosophy and the "valuable LLM roles live upstream of verification" principle — the agent is the CONSUMER of discovered papers, not the DIRECTOR of the crawl.

**Option B (future v2):** A `discover_papers_for_notebook` MCP tool that the agent calls iteratively in a ReAct loop. The tool executes one round of arXiv API or S2 Recommendations discovery per call, returns discovered-paper summaries, and the agent decides whether to call again with refined queries. The calling agent provides all LLM judgment; the server remains LLM-free. Requires BP1 re-pin.

**Architectural fit:**
- Option A: zero new tools, no BP1 impact — strongly preferred for v1
- Option B: one new `discover_papers_for_notebook` MCP tool → mandatory `EXPECTED_TOOL_SCHEMA_SHA256` re-pin via `pytest --update-tool-schema-hash`; must be batched with other tool additions per notes/07 BP1 discipline

**Cache interaction (Option B only):** New tool in `ALL_TOOLS` → `EXPECTED_TOOL_SCHEMA_SHA256` re-pin. BP1 cache invalidated on next cold start for all agents. The tool result (list of discovered `paper_id` strings + ingest status) is deterministic and can participate in Tier-1 exact-query caching. See notes/07 §"Property 1."

**Maturity signal:** ReAct has code (github.com/ysymyth/ReAct, MIT). High-signal as a design pattern.

---

### Candidate 7 — SPECTER2 centroid-query via S2 API for notebook-aware discovery

**Name + citation/URL:** SPECTER2 (Mysore et al., 2023). Hugging Face: `allenai/specter2` (Apache-2.0). Semantic Scholar embedding field: `embedding.specterv2`.
**Year + venue:** 2023, EMNLP. Production embeddings available via S2 API.

**What it does:** SPECTER2 is a 768-dimensional scientific-document embedding model trained on citation graphs (papers that cite each other are close in embedding space). S2 makes SPECTER2 embeddings available for free per paper via the `embedding.specterv2` field in the Academic Graph API. For corpus expansion: compute the centroid of a notebook's already-ingested papers' SPECTER2 embeddings → use as the query vector → return nearest papers in S2's index not yet ingested.

**What's NEW vs arXMCP today:** arXMCP uses BGE-M3 embeddings for its own corpus (math-fidelity, LaTeX-aware). BGE-M3 embeddings only cover papers already in arXMCP's LanceDB. SPECTER2 covers the entire S2 corpus (~200M papers). The delta: arXMCP can use SPECTER2 centroid search as a discovery channel (querying S2's ANN index) while continuing to use BGE-M3 for in-corpus retrieval. These are separate purposes and separate embedding spaces; they do not conflict.

**Architectural fit:**
- Use SPECTER2 via the S2 API (not locally hosted) — avoid the model download in the discovery path
- The centroid-query pattern augments Candidate 1: the S2 Recommendations API already uses SPECTER2-derived similarity under the hood; calling it with positive seeds implicitly does the centroid query
- The 60-day window of S2 Recommendations is correct for the notebook-expansion use case: target RECENT papers (new to the user) that are semantically similar
- Net-new implementation cost folds into Candidate 1 (`ingest/s2_discovery.py`)

**Cache interaction:** Discovery is an ingest-time operation. No BP1/tool surface impact.

**Maturity signal:** SPECTER2 weights: HuggingFace, Apache-2.0. S2 API integration: production. The `semanticscholar` Python library exposes `embedding.specterv2` as a requestable field. High-signal.

---

### Candidate 8 — OpenAlex topic-filter discovery (third channel, resolves existing bug)

**Name + citation/URL:** OpenAlex API, `https://api.openalex.org`. Maintained by OurResearch. License: CC0 data, MIT client (`pyalex`). arXMCP already uses OpenAlex in `ingest/graph_ingest.py`.
**Year + venue:** 2022 (launch); production 2026.

**What it does:** OpenAlex indexes 200M+ scholarly works. The `works` endpoint supports filtering by `topics.id` (concept-level topic tags), `publication_date` (date range), and `locations.source.host_organization_name:arxiv` to restrict to arXiv papers. A filter like `filter=topics.id:<TOPIC_ID>,locations.source.host_organization_name:arxiv,publication_date:>2025-01-01` returns recent arXiv papers in a topic area. Rate limit: 1,000 requests/second unauthenticated (polite pool with user-agent) — far more generous than arXiv's own API.

**What's NEW vs arXMCP today:** `ingest/graph_ingest.py` already calls OpenAlex to build citation edges. The `--category` flag raises `NotImplementedError` (CLAUDE.md §8 gotcha 3). A topic-seeded query using OpenAlex's `topics` taxonomy resolves this existing gap. Three-channel composition: arXiv API (keyword freshness) + S2 Recommendations (citation-graph semantic similarity) + OpenAlex (topic-taxonomy coverage) — deduplicated against existing LanceDB corpus, queued into `ingest_one_paper`.

**Architectural fit:**
- Net-new: `ingest/openalex_discovery.py` — `async def discover_by_topic(topic_id: str, since: datetime) -> list[str]` (returns arXiv IDs)
- Reuse OpenAlex client pattern from `ingest/graph_ingest.py`
- Resolves the `NotImplementedError` for the `--category` flag in `ingest/graph_ingest.py`
- No new tools, no BP1 impact

**Cache interaction:** Background ingest job. No BP1/tool surface impact.

**Maturity signal:** Production API, CC0 data, generous rate limits, `pyalex` Python library (MIT). arXMCP already imports and uses OpenAlex — zero new infrastructure risk. High-signal.

---

## 3. Sources reviewed

| Paper / framework / spec | URL | Year | Code available | High-signal? |
|---|---|---|---|---|
| Semantic Scholar Recommendations API | api.semanticscholar.org/recommendations/v1/papers | 2023/2026 | Python SDK (MIT, `semanticscholar`) | YES |
| SPECTER2 embeddings (Mysore et al.) | huggingface.co/allenai/specter2 | 2023 | YES (Apache-2.0) | YES |
| arXiv API User's Manual | info.arxiv.org/help/api/user-manual.html | 2008/2026 | N/A (API) | YES |
| arXiv API Terms of Use | info.arxiv.org/help/api/tou.html | 2026 | N/A | YES (binding constraint) |
| arXiv Bulk Data Access | info.arxiv.org/help/bulk_data.html | 2026 | N/A | YES (binding constraint) |
| arXiv robots.txt / scraping policy | info.arxiv.org/help/robots.html | 2026 | N/A | YES (binding constraint) |
| crawl4ai (unclecode/crawl4ai) | github.com/unclecode/crawl4ai | 2024/2026 | YES (Apache-2.0) | NO (wrong tool) |
| crawl4ai SDK reference | docs.crawl4ai.com/complete-sdk-reference/ | 2026 | YES | NO (wrong tool) |
| OpenAlex API | api.openalex.org | 2022/2026 | Data: CC0; client: pyalex MIT | YES |
| Citegeist (arXiv:2503.23229) | arxiv.org/abs/2503.23229 | March 2025 | YES (github.com/webis-de/citegeist) | MEDIUM (pattern ref) |
| Stop-RAG (arXiv:2510.14337) | arxiv.org/abs/2510.14337 | October 2025 | NO | MEDIUM (stopping heuristic) |
| Agentic RAG Survey (arXiv:2501.09136) | arxiv.org/abs/2501.09136 | January 2025 | NO | MEDIUM (gap validator) |
| AutoResearchBench (arXiv:2604.25256) | arxiv.org/abs/2604.25256 | April 2026 | Unverified | MEDIUM (gap validator) |
| ReAct (Yao et al., arXiv:2210.03629) | arxiv.org/abs/2210.03629 | ICLR 2023 | YES (MIT) | MEDIUM (design pattern) |
| Reason-Plan-ReAct (arXiv:2512.03560) | arxiv.org/abs/2512.03560 | December 2025 | Unverified | LOW (future pattern) |
| The AI Scientist-v2 (arXiv:2504.08066) | arxiv.org/abs/2504.08066 | April 2025 | YES (Sakana AI) | LOW (uses web search; not arXiv API) |
| Semantic Scholar Open Data Platform (arXiv:2301.10140) | arxiv.org/abs/2301.10140 | 2023 | N/A (infrastructure paper) | MEDIUM (S2 design ref) |
| arXiv API 429-response community thread | groups.google.com/a/arxiv.org/g/api/ | 2026 | N/A | YES (rate-limit reality signal) |

---

## 4. Architectural alignment

| Candidate | arXMCP file:line / net-new | Type |
|---|---|---|
| C1: S2 Recommendations API (positive-seed discovery) | Net-new `ingest/s2_discovery.py`; extend `server/routes/notebooks.py` (`POST /ui/api/notebooks/{slug}/discover`); reuse `ingest/bulk_ingest.py::ingest_one_paper` pipeline | New ingest channel (no tool surface change) |
| C2: arXiv API keyword+date search | Net-new `ingest/arxiv_search.py`; reuse `tools/arxiv_fetch.py::politeness_sleep` + `build_user_agent`; extend Makefile with `make discover-topic` target | New ingest channel (no tool surface change) |
| C3: crawl4ai | NOT recommended — wrong tool, TOS risk, Playwright overhead, zero benefit over C1+C2 | REJECT |
| C4: Citegeist diversity-weighted expansion pattern | Informs C1 design: add `novelty_threshold` + `diversity_weight` parameters to `ingest/s2_discovery.py` so discovery selects for both similarity AND sub-topic diversity | Design pattern reference |
| C5: Stop-RAG stopping criterion | Informs `ingest/s2_discovery.py`: stop discovery rounds when `len(new_ids) / len(total_discovered) < novelty_threshold` (default 0.1) — LLM-free deterministic stopping | Design pattern derivative |
| C6: ReAct planner-executor (Option A — v1) | Operator-trigger path: no new MCP tools at v1; calling agent retrieves over expanded corpus post-ingest | Design pattern (Option A preferred for v1) |
| C6: ReAct planner-executor (Option B — v2) | Net-new `server/handlers/discover.py` + `DISCOVER_PAPERS` `ToolMeta` in `server/tools.py::ALL_TOOLS` → MANDATORY `EXPECTED_TOOL_SCHEMA_SHA256` re-pin + BP1 cache bust | Future option (deferred to v2; batch with other tool additions) |
| C7: SPECTER2 centroid-query | Used implicitly via C1 (S2 Recommendations API internally uses SPECTER2); explicit centroid query extends `ingest/s2_discovery.py` | Embedded in C1 |
| C8: OpenAlex topic-filter discovery | Net-new `ingest/openalex_discovery.py`; resolves `ingest/graph_ingest.py::NotImplementedError` for `--category` flag (CLAUDE.md §8 gotcha 3); reuse OpenAlex client pattern from `ingest/graph_ingest.py` | New ingest channel (resolves existing bug) |

**Priority ranking by effort vs delta value for the core user ask:**

1. **C2 (arXiv API keyword search)** — lowest risk, zero new infrastructure, 1–2 day implementation, immediate topic-seeded discovery capability, already within the rate-limit + politeness framework arXMCP enforces. Ship first.
2. **C1 (S2 Recommendations API)** — 2–3 day implementation, higher-quality semantic discovery (citation-graph similarity vs keyword), requires S2 API key (free, self-service). Ship as complement to C2.
3. **C8 (OpenAlex topic-filter)** — 1–2 day implementation (reuses existing OpenAlex client code in `ingest/graph_ingest.py`), also resolves the pre-existing `NotImplementedError`. Ship as third discovery channel.
4. **C4+C5 design patterns** — inform C1 implementation: add `novelty_threshold` and `diversity_weight` to the discovery loop. Zero extra implementation cost; fold into C1's sprint.
5. **C6 Option B (`discover_papers` MCP tool)** — defer to v2 until the operator-console trigger (Option A) has shipped and proven the discovery pipeline end-to-end.

---

## 5. Themes

**Theme 1: The user's hypothesis about crawl4ai sidestepping arXiv rate-limiting is incorrect.** crawl4ai's browser-based crawling hits the same arXiv.org servers as the official API, but without structured-metadata responses, without TOS coverage, and with a mandatory Playwright dependency that is incompatible with arXMCP's local-first philosophy. arXiv has been actively blocking scrapers (429 responses reported in community forums as of Feb 2026) and explicitly directs programmatic users to OAI-PMH, the REST API, and bulk S3 downloads. The correct discovery architecture uses the official API channels arXMCP already knows how to call.

**Theme 2: Discovery is a deterministic ingest job, not an LLM-in-the-loop crawl.** Every production autonomous-research system surveyed (Citegeist, AutoResearchBench benchmarks, S2 Recommendations) frames paper discovery as a SEARCH or ANN-lookup operation, not as a web-crawl. The LLM's role is DOWNSTREAM of discovery: it reads the newly-ingested papers and reasons about them. arXMCP's "valuable LLM roles live upstream of verification" philosophy is confirmed — the LLM sketcher is upstream of the INGEST STEP (reading papers to understand the field), and the discovery job is upstream of the sketcher (filling in the corpus the sketcher will read). No LLM should be in the discovery loop itself.

**Theme 3: Three discovery channels compose naturally.** arXiv API keyword search (C2), S2 Recommendations with positive seeds (C1), and OpenAlex topic filter (C8) are complementary, not competing. arXiv API = keyword freshness (topic-exact papers submitted recently); S2 Recommendations = semantic similarity (citation-graph neighbors from the past 60 days); OpenAlex = concept taxonomy coverage (all arXiv papers in a topic, any date). A production "discover papers for notebook" feature pipelines all three channels, deduplicates against the existing LanceDB corpus, and queues the union into `ingest_one_paper`.

**Theme 4: The stopping criterion is a deterministic coverage heuristic, not an LLM call.** Stop-RAG's core lesson — that LLMs are poor at self-assessing "do I have enough context?" — reinforces that the discovery job should stop deterministically when marginal novelty drops below a threshold. A `novelty_threshold=0.1` parameter on the discovery loop gives the operator a tunable knob without requiring the server to make an LLM call. This is directly aligned with arXMCP's "determinism over cleverness" design philosophy (notes/01 §"Design philosophy" point 2).

---

## 6. Out of scope / parking lot

| Concept | Rejection reason |
|---|---|
| crawl4ai | Wrong tool: Playwright overhead, arXiv TOS risk, zero benefit over official API; detailed negative finding in Candidate 3 |
| Scraping `arxiv.org/html/` pages via browser automation | arXiv explicitly discourages all non-API programmatic access; `ingest/ar5iv_fetch.py` already handles the LaTeXML HTML path for papers explicitly added by the operator |
| Local SPECTER2 embedding inference (host the model for centroid queries) | Requires downloading a 768M-param model in addition to BGE-M3; use the S2 API instead; no local hosting needed for the discovery channel |
| Full 2.6M-paper local embedding index (Citegeist's Milvus approach) | Single-workstation constraint (CLAUDE.md §4.1); S2 API provides ANN search over the full S2 corpus at no infrastructure cost |
| LLM-in-the-loop relevance filtering at ingest time (server-side LLM scores each discovered paper) | arXMCP runs NO `anthropic` SDK at runtime (CLAUDE.md §4.7); relevance judgment is the calling agent's job, not the server's |
| arXiv bulk S3 download for corpus expansion | Correct for the 200K-paper scale corpus; arXMCP already has `ingest/bulk_ingest.py` for this (E11); the requested feature is TARGETED per-notebook discovery, not bulk corpus rebuild |
| RSS feed polling for new papers | arXiv RSS is category-wide (same as OAI-PMH already running); `ingest/oai_delta.py` already covers this use case; RSS adds nothing for per-notebook topic-seeded discovery |
| Deep research agents (Perplexity-style web-search synthesis) | arXMCP is a retrieval tool provider; synthesis is the calling agent's role; adding synthesis capability to the server contradicts the no-server-LLM constraint |
| Scholar Inbox personalized recommendations (arXiv:2504.08385) | Cloud service requiring persistent user profiles; incompatible with local-first constraint; S2 Recommendations API provides the same capability per-session without persistence |
| crawl4ai MCP server (github.com/sadiuysal/crawl4ai-mcp-server) | Wraps crawl4ai as an MCP tool; inherits all of crawl4ai's Playwright overhead and TOS issues; not appropriate for arXMCP |
| MCP `sampling` capability (server-initiated LLM calls for relevance scoring) | arXMCP runs NO `anthropic` SDK at runtime (CLAUDE.md §4.7); `sampling` requires the server to call an LLM — direct architecture-lock conflict |
