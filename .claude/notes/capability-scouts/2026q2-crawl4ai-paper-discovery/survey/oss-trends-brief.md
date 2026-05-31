# OSS Trends Brief — crawl4ai / Paper Discovery

**Scout run:** `2026q2-crawl4ai-paper-discovery`
**Date:** 2026-05-31
**Phase:** Survey › OSS Trends

---

## 1. TL;DR

The top three projects worth borrowing ideas from are **arxiv.py** (Atom API
wrapper whose `cat:` + `SortCriterion.SubmittedDate` query pattern is the right
idiom for lightweight topic discovery), **pyalex** (OpenAlex API client for
"related-works" enrichment via topic + date compound queries), and **Sickle**
(OAI-PMH harvesting design pattern — superseded in arXMCP by the production
`ingest/oai_delta.py` that already does this). The main thematic gap: arXMCP
already has everything it needs for paper discovery without crawl4ai — the
`oai_delta.py` delta loop plus a thin "discover for notebook" adapter over the
arXiv Atom API is the correct, ToS-compliant, zero-new-dependency path. crawl4ai
is categorically the wrong tool for this job: it requires a full Playwright +
Chromium binary download (~300–500 MB), conflicts with arXMCP's no-browser
local-first constraints, and cannot sidestep arXiv's rate-limiting because
arXiv's `robots.txt` explicitly **Disallows** all crawlers from `/api/`,
`/oai2/`, and `/e-print/` — and the official API rate limit (3 s between
requests) is actually less restrictive than the robots.txt Crawl-delay (15 s).

---

## 2. Project Candidates

### Entry #1 — crawl4ai (PRIMARY — dependency-footprint verdict)

| Field | Value |
|---|---|
| **Project** | crawl4ai |
| **URL** | https://github.com/unclecode/crawl4ai |
| **License** | Apache License 2.0 |
| **Stars** | 67,400+ |
| **Last commit** | Active as of 2026 (1,468+ commits on main) |

**What it does.** An async web-crawling framework that turns rendered web pages
into LLM-friendly Markdown. Its core value is JavaScript execution (Playwright)
+ structured extraction + anti-bot evasion. It is fundamentally a browser
automation wrapper with an LLM-extraction layer on top. It does not provide a
lightweight HTTP-only mode — browser components are mandatory for core
functionality per its own documentation.

**Dependency footprint verdict — DISQUALIFYING for arXMCP.**

From the published `requirements.txt` and `pyproject.toml` (verified 2026-05-31):

- **`playwright>=1.49.0`** — mandatory core dep. Playwright downloads Chromium,
  Firefox, and WebKit binaries via `playwright install` / `crawl4ai-setup`. On
  Windows this writes ~300 MB of browser binaries to `%USERPROFILE%\AppData\Local\ms-playwright\`.
  This is not a Node.js runtime, but is equivalent friction: a large out-of-band
  binary artifact required at install time.
- **`patchright>=1.49.0`** — a second Playwright fork for "undetected" mode; also
  a mandatory core dep, not optional.
- **`playwright-stealth>=2.0.0`** — mandatory.
- **`unclecode-litellm==1.81.13`** — a vendor-pinned fork of the upstream
  `litellm` package. Pulling a pinned third-party fork into a security-audited
  project's dep graph is a supply-chain concern under arXMCP's E13 threat model.
- **`pdf2image>=1.17.0`** — requires the Poppler system binary on Windows; not
  pip-only. Adds a system-level install step with no Python escape.
- **`alphashape>=1.3.1`**, **`shapely>=2.0.0`** — computational geometry; pulls
  in GEOS native extension. Not relevant to paper discovery; they exist because
  crawl4ai does visual/bounding-box extraction.
- **Total install footprint on Windows:** Python wheels (~50 MB) + Playwright
  binaries (~300 MB) + Poppler (~10 MB if installed) = ~360 MB minimum. The
  `crawl4ai[all]` variant adds torch + sentence-transformers, approaching 2 GB.

**The rate-limiting premise is false.** The user's stated hope that crawl4ai
"sidesteps" arXiv's rate-limiting is contradicted by two hard facts:

1. **`arxiv.org/robots.txt`** (verified 2026-05-31) sets a **Crawl-delay of 15
   seconds** for all user-agents and explicitly **Disallows `/api/`, `/oai2/`,
   `/e-print/`** — all the paths that carry structured paper metadata or source.
   The human-facing list pages (`/list/`) are in the Allow list, but HTML
   scraping those yields presentation markup, not structured metadata, and still
   at a 15-second per-request minimum.
2. The **arXiv Atom API rate limit** ("no more than one request every three
   seconds" per the ToS) is **five times less restrictive** than the robots.txt
   Crawl-delay. Official API access is faster, not slower, than scraping. The
   arXiv ToS explicitly prohibits "attempting to circumvent rate limits" and
   reserves the right to block access.

A Playwright-driven crawler hitting `arxiv.org/list/math.AG/recent` would: (a)
see the human-facing HTML with no structured metadata, (b) be subject to the
15-second Crawl-delay, (c) risk IP block for ToS violation, and (d) require
100–200 ms/page browser startup latency on top of network time. This is
strictly worse than calling the Atom API with `urllib.request`.

**Windows 11 specifically.** Playwright's Windows support is functional but:
`patchright` (anti-detection Playwright fork) has known Windows Defender false
positives; `pdf2image` requires manual Poppler installation with PATH editing;
`crawl4ai-setup` may require elevated PowerShell for browser binary installation.
These are meaningful friction points on a single-workstation setup.

**Specific capability worth borrowing.** The `AsyncMarkdownGenerator` extraction
pipeline (LLM-ready Markdown from rendered HTML) is crawl4ai's genuine
contribution — but arXMCP already does this via BeautifulSoup + LaTeXML for
ar5iv HTML, both already in `pyproject.toml`. No borrowing opportunity.

**arXMCP positioning.** No lift. Do not add as a dependency. Do not implement a
crawl4ai-inspired browser layer. The feature is better served by the official
arXiv Atom API path described in Entries #2 and #8.

**Risk flags.**
- Browser binary bloat (~300–500 MB on Windows).
- `pdf2image` requires Poppler system dep — friction on Windows 11.
- `patchright` (anti-detection fork) is a maintenance fragility; upstream
  Playwright API changes may silently break it.
- `unclecode-litellm` pin is a vendor fork, not PyPI upstream — supply-chain
  concern for E13-audited projects.
- **VERDICT: Do not use. Do not implement a crawl4ai-equivalent browser layer.**

---

### Entry #2 — arxiv.py (arXiv Atom API client)

| Field | Value |
|---|---|
| **Project** | arxiv.py |
| **URL** | https://github.com/lukasschwab/arxiv.py |
| **License** | MIT |
| **Stars** | ~1,500 |
| **Last commit** | Active (172+ commits on main) |

**What it does.** A thin Python wrapper around arXiv's official Atom API
(`http://export.arxiv.org/api/query`). Supports `Search` with query strings
including `cat:math.AG`, `SortCriterion.SubmittedDate` for chronological
ordering, `delay_seconds` for politeness, and pagination. The key compound
query for "new papers in category X since date Y" is:
`cat:math.AG AND submittedDate:[20260101* TO *]`. Max results per request: 2,000;
total traversable: 30,000 — more than sufficient for "last 30 days of math.AG."

**Specific capability worth borrowing.** The `cat:` + `submittedDate` query
pattern. arXMCP already has `tools/arxiv_fetch.py` with the correct User-Agent +
politeness contract for `export.arxiv.org`. Extending it with Atom API search is
a ~150-line addition: build the query URL, call `urllib.request`, parse the Atom
XML response with `xml.etree.ElementTree` (stdlib). arxiv.py itself is unnecessary
as a dependency — the value is the query pattern and the Atom result parsing shape.

**arXMCP positioning.** Design-pattern lift → native re-impl in a new
`ingest/arxiv_search.py` module. No new pip dependency. This module would expose
`search_recent(category, topic_keywords, since_date)` returning a list of paper
IDs ready to be handed to `ingest_one_paper()`.

**Risk flags.** None. The arXiv Atom API is stable, officially supported, and the
rate limit (3 s) matches arXMCP's existing contract in `tools/arxiv_fetch.py`.

---

### Entry #3 — Sickle (OAI-PMH client)

| Field | Value |
|---|---|
| **Project** | sickle (mloesch fork) |
| **URL** | https://github.com/mloesch/sickle |
| **License** | BSD-3-Clause (original Sickle; fork inherits) |
| **Stars** | 116 |
| **Last commit** | Maintained |

**What it does.** A Python OAI-PMH client supporting all six OAI verbs with
automatic resumption-token following and Python object wrappers for records,
headers, and sets. The key pattern:
`sickle.ListRecords(metadataPrefix='arXivRaw', set='math:math:AG', **{'from': '2026-05-01'})`.
Transparently pages through all results by following `ResumptionToken` elements.

**Specific capability worth borrowing.** Sickle's automatic resumption-token
follow is the reference design for pagination in OAI-PMH harvesting. arXMCP's
`ingest/oai_delta.py` already implements this manually (state file persists the
token; D6 in the module docstring). Sickle confirms the design is correct and
adds no new ideas. The `from` parameter Python-keyword workaround (`**{'from': ...}`)
is documented in Sickle's tutorial and is the same pattern arXMCP uses internally.

**arXMCP positioning.** No new import needed. `ingest/oai_delta.py` is the
production OAI-PMH harvester and already does `ListRecords` with date and set
filters for the four target sets. Sickle is useful as a reference only.

**Risk flags.** Low star count. The value is the design pattern, not the library.
arXMCP's hand-rolled implementation is superior because it integrates directly
with the state file, budget watchdog, and staging-path discipline.

---

### Entry #4 — pyalex (OpenAlex API client)

| Field | Value |
|---|---|
| **Project** | pyalex |
| **URL** | https://github.com/J535D165/pyalex |
| **License** | MIT |
| **Stars** | 383 |
| **Last commit** | Active; updated for the Feb 2026 mandatory API key |

**What it does.** A lightweight Python client for the OpenAlex REST API. Supports
filtering `Works` by `topics.id`, `from_publication_date`, `from_created_date`,
and sorting by `publication_date`. The `Works().similar()` method provides
semantic similarity-based paper discovery from a text query. As of February 13,
2026 an API key is required (free; 100K credits/day with key vs 100/day without).
Rate limit: 100 req/s max with key.

**Specific capability worth borrowing.** The `from_publication_date` + `topics.id`
compound filter is the correct pattern for "find papers about Bridgeland stability
conditions published since 2026-04-01." OpenAlex Topics are more granular than
arXiv `cat:` codes and can map a free-text notebook topic to a specific subfield
ID. arXMCP already uses OpenAlex for citation graph ingest (`ingest/graph_ingest.py`);
the HTTP client pattern (polite-pool email in User-Agent) is established.

**arXMCP positioning.** Design-pattern lift — extend `ingest/graph_ingest.py`'s
existing OpenAlex HTTP client with a `find_recent_by_topic(topic_id, since_date)`
function. The pyalex query URL pattern informs the construction; the actual HTTP
call uses `urllib.request`. This is complementary to the Atom API path (Entry #2):
OpenAlex gives richer topic matching for free-text topics but requires an API key;
Atom API is zero-auth but limited to arXiv category codes.

**Risk flags.** API key now required (Feb 2026) — operator must register at
`openalex.org/. Rate limit (100 req/s) is ample. OpenAlex Topics partially
supersede Concepts (deprecated); the query syntax for topic IDs may drift. The
`Works().similar()` semantic search feature requires knowing a seed paper's
OpenAlex ID, not just an arXiv ID — a join step is needed.

---

### Entry #5 — semanticscholar Python client (danielnsilva)

| Field | Value |
|---|---|
| **Project** | semanticscholar |
| **URL** | https://github.com/danielnsilva/semanticscholar |
| **License** | MIT |
| **Stars** | 460 |
| **Last commit** | Active (427+ commits on master) |

**What it does.** Python wrapper for Semantic Scholar's Academic Graph,
Recommendations, and Datasets APIs. The Recommendations API returns papers
similar to a given seed paper. Without a key: shared 1,000 req/s pool (throttled).
With an authenticated key: 1 req/s limit on all endpoints — an oddly restrictive
cap for a signed-in user.

**Specific capability worth borrowing.** The per-paper Recommendations endpoint
(`/recommendations/v1/papers/forpaper/{paper_id}`): given a notebook's seed paper
IDs (already in `notebook_papers` junction table), discover semantically similar
papers not yet in the notebook. This is a different discovery axis from the
category+date approach (Entries #2, #4) — it is similarity-driven, not
recency-driven. The two are complementary.

**arXMCP positioning.** Design-pattern lift → `ingest/s2_discovery.py`, ~80 lines,
zero new pip deps (bare `urllib.request` GET returning JSON). Gated by the 1 req/s
authenticated limit; suitable for a "discover 5–10 related papers for this seed"
call, not bulk harvesting.

**Risk flags.** 1 req/s authenticated rate limit restricts bulk use. The
`allenai/s2-folks` community repo was archived Jan 2025 — S2 API is maintained
but community engagement has dropped. S2 has no "new papers in category X since
date Y" endpoint — recommendations are per-paper-similarity only.

---

### Entry #6 — feedparser

| Field | Value |
|---|---|
| **Project** | feedparser |
| **URL** | https://pypi.org/project/feedparser/ |
| **License** | BSD-2-Clause |
| **Stars** | N/A (PyPI) |
| **Last release** | 6.0.12 — September 10, 2025 |

**What it does.** Parses RSS 0.9x, RSS 1.0, RSS 2.0, Atom 0.3, and Atom 1.0 feeds
in Python. The arXiv Atom API returns standard Atom 1.0, which feedparser handles
natively. Compared to `xml.etree.ElementTree`, feedparser adds namespace handling,
encoding normalization, and a uniform dict-like result model for Atom entries
(`entry.id`, `entry.updated`, `entry.tags`).

**Specific capability worth borrowing.** feedparser's result model for arXiv Atom
1.0 is the reference parse-result shape for the "discover new papers" feature.
However, the arXiv Atom response is simple enough that `xml.etree.ElementTree`
handles it in ~30 lines without a new dependency.

**arXMCP positioning.** Optional convenience — document the feedparser approach as
an alternative but implement natively via stdlib. arXMCP's "no implicit deps"
discipline (`pyproject.toml` per-line comment discipline) makes adding a new dep
for ~30 lines of XML parsing hard to justify.

**Risk flags.** None. BSD-2-Clause, pure Python, Windows-friendly, actively
maintained.

---

### Entry #7 — APScheduler

| Field | Value |
|---|---|
| **Project** | APScheduler |
| **URL** | https://github.com/agronholm/apscheduler |
| **License** | MIT |
| **Stars** | 7,500 |
| **Last commit** | Active; v3.11.2 released December 22, 2025 |

**What it does.** In-process Python task scheduler supporting cron, interval, and
one-shot triggers without a separate daemon. Relevant to "periodically discover new
papers for a notebook."

**Specific capability worth borrowing.** The in-process cron-trigger with jitter
pattern. However, arXMCP's existing operational model uses system cron to invoke
`oai_delta.py` externally — the simpler and more consistent path for notebook
discovery is a `tools/discover_for_notebook.py` CLI entrypoint invoked by system
cron, not in-process scheduling. In-process scheduling adds FastAPI lifespan
complexity and risks resource contention with the embedding pipeline.

**arXMCP positioning.** Design-pattern reference only. Prefer system cron over
APScheduler for consistency with E11's established operational model.

**Risk flags.** APScheduler v4 (async rewrite) is a breaking API change from v3;
the project is on v3.11.x (stable v3 line). Pin the major version carefully if
adopted.

---

### Entry #8 — arXMCP incumbent: `ingest/oai_delta.py` + `tools/arxiv_fetch.py`

This is not a third-party project but is the load-bearing framing for the feature
request.

**What they do.** `ingest/oai_delta.py` (E11_S02) implements OAI-PMH `ListRecords`
with date-range and set-filter parameters for the four arXMCP target sets
(`math:math:AG`, `math:math:NT`, `physics:math-ph`, `physics:hep-th`), feeds each
discovered paper ID to `ingest_one_paper()`, and persists resumption tokens.
`tools/arxiv_fetch.py` implements the politeness contract for `export.arxiv.org`
(User-Agent, 3-second sleep, 503 backoff, 100 MB cap, path-traversal-safe
extraction) used by both seed and delta flows.

**Gap for notebook-scoped discovery.** The current flow writes to the global staging
LanceDB. A notebook-scoped feature needs: (a) topic filtering narrower than arXiv
OAI sets (e.g., "Bridgeland stability conditions" within `math.AG`), (b) writing
to the notebook's per-slug LanceDB, (c) recording discovered paper IDs in the
`notebook_papers` junction table. None of these require new external libraries.

**Recommended thin adapter.** A `tools/discover_for_notebook.py` (~200 lines,
zero new deps) that: (1) queries the arXiv Atom API with
`cat:math.AG AND <topic_keywords> AND submittedDate:[<since>* TO *]` using the
existing `arxiv_fetch.py` politeness contract; (2) calls
`ingest_one_paper(paper_id, lancedb_path=notebook_dir(slug))` for each result;
(3) records paper IDs in `notebook_papers`. An optional second pass calls the
S2 Recommendations endpoint for similarity-driven discovery (Entry #5). This is
the feature in its entirety — no crawl4ai, no Playwright, no new pip deps.

---

## 3. Sources Reviewed

| Project / Source | URL | Stars | Last commit / release | High-signal |
|---|---|---|---|---|
| crawl4ai | https://github.com/unclecode/crawl4ai | 67,400 | 2026 (active) | YES — primary subject |
| crawl4ai requirements.txt | https://github.com/unclecode/crawl4ai/blob/main/requirements.txt | — | — | YES — dep verdict |
| crawl4ai installation docs | https://docs.crawl4ai.com/core/installation/ | — | — | YES — dep verdict |
| arxiv.py | https://github.com/lukasschwab/arxiv.py | 1,500 | Active | YES |
| Sickle (mloesch) | https://github.com/mloesch/sickle | 116 | Active | YES |
| pyalex | https://github.com/J535D165/pyalex | 383 | Active (Feb 2026 key update) | YES |
| semanticscholar (danielnsilva) | https://github.com/danielnsilva/semanticscholar | 460 | Active | YES |
| feedparser | https://pypi.org/project/feedparser/ | N/A | Sep 2025 (v6.0.12) | PARTIAL |
| APScheduler | https://github.com/agronholm/apscheduler | 7,500 | Dec 2025 (v3.11.2) | PARTIAL |
| arXiv ToS | https://info.arxiv.org/help/api/tou.html | — | — | YES — critical |
| arXiv robots.txt | https://arxiv.org/robots.txt | — | — | YES — critical |
| arXiv Atom API manual | https://info.arxiv.org/help/api/user-manual.html | — | — | YES |
| OpenAlex Works API | https://developers.openalex.org/api-entities/works/get-lists-of-works | — | — | YES |
| Semantic Scholar API | https://www.semanticscholar.org/product/api | — | — | YES |
| s2-folks (allenai) | https://github.com/allenai/s2-folks | 272 | Archived Jan 2025 | NO — archived |
| metha (Internet Archive) | https://github.com/internetarchive/metha | — | 404 | NO — Go binary |
| oaipmh-scythe | https://github.com/ddelange/oaipmh-scythe | — | 404 | NO — URL not found |

---

## 4. Themes

The dominant theme is **the official API path is strictly superior to scraping for
arXiv paper discovery**: arXiv's `robots.txt` (verified 2026-05-31) disallows
automated crawlers from all relevant structured-data endpoints, the official Atom
API rate limit (3 s between requests) is five times less restrictive than the
robots.txt Crawl-delay (15 s), and the Atom API returns structured Atom XML while
HTML scraping returns presentation markup requiring fragile parsing. crawl4ai's
dependency footprint (Playwright + Chromium binary + vendor-forked litellm +
pdf2image/Poppler) is categorically incompatible with arXMCP's single-workstation,
Windows-11, no-browser-binary operational profile and would violate the spirit of
the no-Node constraint in `CLAUDE.md §4.7`.

A second theme is **arXMCP already has 90% of what it needs**: `ingest/oai_delta.py`
is a production-grade OAI-PMH harvester; `tools/arxiv_fetch.py` has the correct
politeness contract and 503-backoff discipline; `ingest/graph_ingest.py` has an
established OpenAlex HTTP client pattern. The "discover new papers for a notebook"
feature is a ~200-line thin adapter over these existing modules, not a new
architectural layer requiring external libraries.

A third theme is **two complementary discovery axes are available natively**:
recency-driven (arXiv Atom API: `cat:` + `submittedDate` → new papers in the last
N days, zero-auth, 3 s rate limit, stdlib-only parse) and similarity-driven
(Semantic Scholar Recommendations API: seed paper ID → semantically similar papers,
JSON endpoint, ~80-line implementation). Combining both in a single
`discover_for_notebook` tool covers the full "discover new papers about X for
notebook Y" user story without crawl4ai.

---

## 5. Out of Scope / Parking Lot

- **metha** (Internet Archive Go binary) — Go binary, not pip-installable; no path
  forward in arXMCP's pure-Python dep graph; cross-platform friction on Windows.
- **oaipmh-scythe** (ddelange fork) — GitHub URL returned 404; dead link; original
  Sickle covers the same design pattern.
- **habanero** (Crossref API client, fabiobatalha) — Crossref has no arXiv category
  index; the `cat:` query surface is arXiv-specific; habanero is for DOI resolution,
  not paper discovery by category.
- **Connected Papers / ResearchRabbit** — commercial products with no public API
  for local-first integration.
- **trafilatura** — HTML extraction library (lighter than crawl4ai, no browser
  required); would be relevant if arXMCP needed to scrape HTML, but the official
  API path makes HTML scraping unnecessary for arXiv.
- **scrapy** — BSD-3-Clause but heavyweight for a single-site use case; the
  `urllib.request` path is sufficient and already established in arXMCP.
- **requests-html** — abandoned (last commit 2020); do not surface.
- **httpx** — already a transitive dep via MCP SDK; no new capability over stdlib
  `urllib.request` for this use case; arXMCP uses the sync stdlib HTTP path
  consistently in all ingest tools.
