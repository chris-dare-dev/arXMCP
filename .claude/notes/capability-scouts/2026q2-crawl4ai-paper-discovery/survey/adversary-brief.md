# Adversary Brief — Capability Scout 2026q2-crawl4ai-paper-discovery

**Scout run:** 2026-05-31
**Scope:** crawl4ai integration · corpus expansion · topic-driven paper discovery · freshness · arXiv ToS
**Critic model:** claude-sonnet-4-6

---

## Grounding answers (critical verification tasks)

### What IS a "notebook" in arXMCP today?

A notebook is a **named collection of papers** tracked in SQLite
(`var/arxmcp/cache/notebooks.db`) with:

- `slug` (primary key, regex-validated, `^[a-z][a-z0-9-]{2,30}$`)
- `display_name` (free text, ≤256 chars)
- `lancedb_path` (auto-derived, `var/arxmcp/notebooks/<slug>/lancedb/`)
- `notebook_kind` (`arxiv` or `textbook`)
- `parse_status` (for textbook notebooks; `pending|running|done|failed|skipped`)
- A junction table `notebook_papers (slug, paper_id, added_at)`

Source: `server/notebooks_store.py:1-75`, `server/routes/notebooks.py:190-212`

**There is NO topic/subject-area metadata on the notebook.** The notebook has
no `topic`, `description`, `keywords`, `category`, or `intent` field. A
notebook named "bridgeland-stability" is indistinguishable from one named
"elliptic-curves" except by its slug string. The operator knows what the
notebook is about; the system does not.

Papers are added either:
1. By pasting an `arxiv.org/abs/<id>` or `ar5iv.labs.arxiv.org/html/<id>` URL
   into the UI (`POST /ui/api/notebooks/{slug}/papers`)
2. By uploading an ar5iv HTML file or PDF directly
3. By editing `var/arxmcp/notebooks/<slug>/papers.txt` and running
   `tools/notebook_fetch.py <slug>`

There is **no automated discovery path** — every paper in a notebook was put
there manually by the operator.

### Does arXMCP have ANY existing "find new papers" path?

**No**, not at the notebook level.

What EXISTS at the corpus level:
- `tools/curate_seed.py` — hits `export.arxiv.org/api/query?search_query=cat:<category>` to produce a TSV of candidates for human review. This is a **one-shot operator tool** that produces a list for human curation, not an automated discovery loop. Source: `tools/curate_seed.py:44-76`.
- `ingest/oai_delta.py` — nightly harvest of OAI-PMH for **four hardcoded category sets** (`math:math:AG`, `math:math:NT`, `physics:math-ph`, `physics:hep-th`). It discovers new papers by category, not by topic. There is no "find papers related to Bridgeland stability conditions" capability. Source: `ingest/oai_delta.py:109-114`.
- `ingest/graph_ingest.py:57-65` — explicitly notes that `--category math.AG math.NT` discovery path raises `NotImplementedError`; "Tier-3 category-bulk discovery will land in a future milestone using Topics."

**There is zero semantic/topic-driven discovery.** The system can pull all
papers from a category set; it cannot pull papers matching a concept like
"Bridgeland stability" or "etale cohomology" autonomously.

### What is the ACTUAL rate-limiting reality arXMCP already handles?

arXMCP already handles arXiv rate limits with disciplined politeness:

**tools/arxiv_fetch.py:**
- `POLITENESS_SLEEP_SECONDS = 3.0` — hard minimum 3-second sleep between ALL `/e-print/` requests (not just failures)
- `DEFAULT_503_BACKOFF_SECONDS = 30.0`, `MAX_503_BACKOFF_SECONDS = 300.0` — exponential backoff on 503s
- `build_user_agent()` — mandatory `arXMCP/0.1 (mailto:<email>)` User-Agent (enforced at runtime, raises if unset)
- Source: `tools/arxiv_fetch.py:33-38`

**ingest/oai_delta.py:**
- Same 3-second politeness contract between OAI-PMH page fetches
- Exponential backoff on 503: 30s initial → doubles → capped at 600s
- 1-hour wall-clock retry cap before giving up
- Explicit OAI-PMH TOS reference: "no more than one request every three seconds"
- Source: `ingest/oai_delta.py:87-95, 157-160`

**arXiv official API (`export.arxiv.org/api/query`) — used in curate_seed.py:**
- Standard HTTP, no auth required
- Rate limit: effectively the same 3s politeness contract (arXiv TOS §3)
- Max 2000 results per query (`--max-results`, source: `tools/curate_seed.py:139-143`)
- Supports `search_query=cat:math.AG AND ti:Bridgeland` style queries

---

## 1. Executive Summary

The highest-severity gap is the **total absence of topic-driven paper discovery
at the notebook level**: given a notebook named "bridgeland-stability", the
system cannot autonomously find and propose new arXiv papers relevant to that
topic. Everything above that gap flows from it — there is no semantic query
to arXiv, no suggestion surface, no "ingest related papers" button. Second:
**the user's premise that crawl4ai sidesteps arXiv rate-limiting is false and
architecturally risky**; arXMCP already has a TOS-compliant path (arXiv's
official API + OAI-PMH), and scraping with a headless browser would violate
`robots.txt`, consume excessive arXiv resources, and expose the operator to
IP bans. Third: **the notebook model has no topic/intent metadata**, making
any automated discovery blind without an explicit query from the operator.
Fourth: **`tools/curate_seed.py` has the right API call shape** but is
designed only for offline human curation, not as a building block for a
notebook-scoped discovery loop.

---

## 2. Critical Gaps

None. All gaps below are HIGH or MEDIUM. The discovery absence comes close to
CRITICAL given the mission statement ("every sub-agent shares one substrate of
grounded context"), but the notebook model is an opt-in operator convenience
layer on top of the corpus — the corpus itself continues to grow via OAI-PMH.
The gap hurts UX significantly but does not erase core retrieval value.

---

## 3. High Gaps

### H1 — No topic-driven paper discovery for notebooks

**Gap name:** Notebook-scoped topic-driven discovery absent

**Severity:** HIGH

**What comparable systems/SOTA expects:** NotebookLM, Elicit, Consensus, and
Semantic Scholar all expose "find related papers" or "discover more like these"
workflows. Elicit specifically discovers papers by topic query over a
research-area corpus. For a system explicitly targeting math-pipeline agents
(sketcher → autoformalizer → tactician), a "find papers about Bridgeland
stability conditions" primitive is the obvious next capability after the
retrieval surface exists. Comparable local-first tools (Zotero, Obsidian with
plugins, Papers) surface citation-expansion as a discovery mechanism; arXMCP's
citation graph (E09) exists but is not wired to a discovery flow.

**What arXMCP has today:** Zero topic-driven discovery. `tools/curate_seed.py`
(`curate_seed.py:44-76`) hits `export.arxiv.org/api/query?search_query=cat:<category>`
but is designed as a one-time human-curation tool (it prints a TSV, exits, and
requires the operator to hand-pick IDs). `ingest/oai_delta.py` discovers by
category set, not by semantic topic (`oai_delta.py:109-114` — four hardcoded
sets). The notebook model has no topic field at all (`notebooks_store.py:1-75`).
There is no MCP tool, no CLI subcommand, and no UI button that takes a topic
description and returns candidate paper IDs. `ingest/graph_ingest.py:57-65`
explicitly notes `--category` discovery raises `NotImplementedError`.

**What a credible v1 fill-in would look like:** Wire `tools/curate_seed.py`'s
existing `build_query_url()` + `fetch_candidates()` into a new
`tools/notebook_discover.py` that: (1) accepts `<slug>` + `<query>`, (2) calls
the arXiv API with `search_query=<query>` (the API already supports
`ti:Bridgeland AND cat:math.AG` style syntax), (3) filters against papers
already in the notebook, (4) returns the top-N as `paper_id + abstract_head`
candidates for the operator to review + optionally add via `POST
/ui/api/notebooks/{slug}/papers`. Optionally surface it as a UI panel:
"Discover papers matching [text input]". No headless browser, no scraping, no
new dependencies beyond what already exists.

**Architecture-lock interaction:** The arXiv API
(`export.arxiv.org/api/query`) is already in use in `tools/curate_seed.py` and
is TOS-compliant. The 3-second politeness contract (`tools/arxiv_fetch.py:35`)
already applies. The new tool would live in `tools/` (CLI) or
`server/routes/` (UI panel), following the local-first / loopback-only
convention. No `anthropic` SDK, no Node, no fork. The key design question is
whether discovery results should be "proposed" (operator confirms) vs
"auto-ingested" (no confirmation) — given `01-mission-and-context.md`'s "power
tool, not autopilot" framing, the proposed/confirm model is architecturally
correct.

**Why this hasn't been fixed yet:** The feature was never scoped into any
epic. The notebook model is relatively recent (post-E09), and the system's
ingestion design (`03-ingestion-pipeline.md`) focuses on category-level
freshness (OAI-PMH) rather than topic-level discovery. The building blocks
(`curate_seed.py`, arXiv API, OAI-PMH) are all present; connecting them into
a notebook-scoped flow is the missing piece.

---

### H2 — The "crawl4ai sidesteps rate-limiting" premise is false and risky

**Gap name:** crawl4ai does not sidestep arXiv rate limits; it bypasses ToS

**Severity:** HIGH (risk classification: ToS violation + heavyweight dependency for zero benefit)

**SPECIAL ADJUDICATION:** The user's stated hope is that "crawl4ai-based
scraping could sidestep arXiv's rate-limiting." This premise is **false on two
grounds and risky on a third**:

1. **arXMCP already respects the documented rate limits.** arXiv's rate limit
   for `/e-print/` fetches is 1 request per 3 seconds. arXMCP already enforces
   this (`tools/arxiv_fetch.py:35: POLITENESS_SLEEP_SECONDS = 3.0`). The delta
   loop already does the same for OAI-PMH (`oai_delta.py:90`). The "rate
   limiting problem" being solved by crawl4ai does not exist in arXMCP's
   current code — the system is already polite. The arXiv API for metadata
   queries has no per-paper rate limit at all (unlike `/e-print/`); a single
   well-formed `search_query` call returns 2000 results without any 3-second
   sleep requirement beyond courtesy.

2. **crawl4ai is a headless browser scraper; scraping arxiv.org violates
   `robots.txt`.** arxiv.org's `robots.txt` disallows automated scraping of the
   HTML listing pages. The official supported machine-access channels are:
   - **arXiv API** (`export.arxiv.org/api/query`) — what `curate_seed.py` already uses
   - **OAI-PMH** (`oaipmh.arxiv.org/oai`) — what `oai_delta.py` already uses
   - **`/e-print/<id>`** — what `arxiv_fetch.py` already uses (for source tarballs)
   Crawling `arxiv.org/search/?query=Bridgeland` with a headless browser (what
   crawl4ai does) bypasses these channels and is explicitly against the terms.
   Reference: `ingest/oai_delta.py:50` cites arXiv TOS; `notes/03-ingestion-pipeline.md`
   "Non-goals: Live arXiv listings scraping (use OAI-PMH)."

3. **crawl4ai would add a heavyweight, non-local-first dependency with no
   incremental benefit.** crawl4ai requires Playwright (Chromium + async
   browser), which is a ~200 MB binary dependency that is pure
   browser-automation overhead for a task the arXiv API already handles with
   plain HTTP. The local-first / no-Node constraint (`CLAUDE.md §4.7`) is not
   technically violated (crawl4ai is Python), but Playwright installs Chromium
   via `playwright install` which downloads Node packages during setup. More
   importantly: crawl4ai adds nothing over `urllib.request` + `xml.etree` for
   the arXiv use case because the arXiv API returns clean Atom XML — no
   JavaScript rendering is needed.

**What the correct path looks like:** Use the arXiv API
(`export.arxiv.org/api/query`) for topic-driven discovery. It is free, TOS-
compliant, returns structured metadata (title, authors, abstract, categories,
IDs), supports semantic queries (`ti:Bridgeland+AND+cat:math.AG`), and is
already wired in `tools/curate_seed.py`. arXMCP already has all the HTTP
primitives it needs. crawl4ai is the wrong tool for this job.

**Architecture-lock interaction:** Using crawl4ai to scrape arxiv.org HTML
listing pages would create: (a) a ToS-violation risk for the operator's IP;
(b) a fragile scraper against arxiv.org's HTML which changes without notice;
(c) a security surface — crawl4ai evaluates JavaScript in a real browser,
expanding the attack surface (a hostile arXiv page could attempt drive-by
exploits via JS; the arXiv API returns XML which has no script execution path).
The design constitution's first ingestion non-goal (`03-ingestion-pipeline.md`)
is "Live arXiv listings scraping (use OAI-PMH)." crawl4ai is exactly that.

**Why this hasn't been fixed yet:** This is a novel premise being evaluated
in this scout run; no prior epic proposed crawl4ai. The finding is that the
premise should be rejected before any milestone is scoped around it.

---

## 4. Medium Gaps

### M1 — Notebook has no topic/intent metadata (discovery is blind without operator query)

**Gap name:** Notebook lacks topic field; any discovery must be fully operator-supplied

**Severity:** MEDIUM

**What comparable systems/SOTA expects:** Zotero, Papers, and Obsidian all
support per-collection tags, descriptions, or topic metadata that enable
intelligent suggestions. Elicit ties "library" (its notebook analog) to a
research question. NotebookLM grounding happens against a stated research
context.

**What arXMCP has today:** The SQLite schema
(`notebooks_store.py:154-178`) has `slug + display_name + lancedb_path +
created_at + notebook_kind + parse_status`. There is no `topic`, `description`,
`keywords`, `category`, or `intent` field. The `display_name` is a free-text
label (e.g., "Bridgeland Stability") that is rendered in the UI header but is
not parsed, indexed, or used programmatically. Any "related papers" discovery
flow must fully rely on the operator providing a query string; there is no
system-derived starting point.

**What a credible v1 fill-in would look like:** Add a `description TEXT NOT
NULL DEFAULT ''` column (v5 ADDITIVE migration in `notebooks_store.py`, same
pattern as v1→v4) and surface a one-liner "Research question or topic area for
discovery" text field in the UI creation form. The existing `PATCH
/ui/api/notebooks/{slug}` (rename endpoint) pattern can be extended to a
`description` update. The discovery tool (`H1` above) would then default to
using `description` as the query if no explicit query is supplied. This is
small, additive, and requires no new dependencies.

**Architecture-lock interaction:** Pure SQLite ADDITIVE migration (no DROP);
follows the v1→v4 pattern already established. The description field is
operator-supplied data (loopback-only; no external fetch). The UI PATCH
extension is a minor htmx addition — no Node, no SPA. The description field
should be included in the restic backup scope per the notebook-storage gap
noted in the prior scout run (`2026q2-notebook-ux-storage-ops` H2).

**Why this hasn't been fixed yet:** The notebook model was designed for
manual curation, not for automated discovery. The feature was never on the
roadmap because there was no discovery capability to anchor it to. The two
gaps (H1: no discovery, M1: no topic metadata) are co-dependent — fixing H1
without M1 produces a discovery tool that always needs an explicit query;
fixing M1 without H1 stores metadata with no consumer.

---

### M2 — curate_seed.py is not reusable as a library primitive

**Gap name:** Existing arXiv-API query tool is designed as a one-shot CLI, not a reusable module

**Severity:** MEDIUM

**What comparable systems/SOTA expects:** Projects with multiple pipeline stages
factor their data-source clients into shared library modules, not standalone
CLI scripts. The arXiv API query capability should be a `fetch_candidates()`
function that any pipeline stage can call.

**What arXMCP has today:** `tools/curate_seed.py` has `build_query_url()`,
`fetch_candidates()`, `parse_atom_feed()`, and `filter_candidates()` as
top-level functions (`curate_seed.py:68-125`) that do exactly the right thing:
call the arXiv API, parse Atom XML, apply metadata filters. BUT: the module's
`main()` function prints a TSV to stdout and exits (`curate_seed.py:137-187`).
There is no `tools/_arxiv_search.py` or `ingest/arxiv_search.py` library
module that `tools/notebook_discover.py` (the H1 fill-in) could import. The
existing functions are accessible as Python but the module is designed as a
CLI, and `POLITENESS_SLEEP_SECONDS` is a module-level constant that blocks
in `time.sleep()` inside `main()`, not something a pipeline can control via
injection.

**What a credible v1 fill-in would look like:** Extract `build_query_url()`,
`fetch_candidates()`, and `parse_atom_feed()` into a new
`tools/_arxiv_api.py` (following the `tools/_notebook_common.py` pattern)
with the same politeness-sleep injection the delta loop uses
(`sleep=time.sleep` parameter with a default that tests can override). The
existing `tools/curate_seed.py` CLI becomes a thin wrapper around the shared
module. `tools/notebook_discover.py` and any future discovery surface import
from `_arxiv_api.py`. This is pure refactoring — no behavior change.

**Architecture-lock interaction:** Follows the established pattern
(`tools/_notebook_common.py`, `tools/arxiv_fetch.py`) of shared module +
CLI wrapper. No new dependencies. The politeness-sleep injection pattern is
already used in `ingest/oai_delta.py`'s `fetch_page` and `sleep_between_pages`
parameters.

**Why this hasn't been fixed yet:** `curate_seed.py` was written for E01_S03
as a one-shot seed-curation tool. The notebook model didn't exist then. The
refactoring need was never surfaced because there was no planned consumer for
a library form of the arXiv API query.

---

### M3 — OAI-PMH delta loop is category-granular, not topic-granular

**Gap name:** Freshness channel pulls entire categories; no topic-relevant subset filtering

**Severity:** MEDIUM

**What comparable systems/SOTA expects:** Semantic Scholar, Connected Papers, and
ResearchRabbit all offer topic-specific alerts ("new papers matching <query>")
rather than category-level flooding. A user working on Bridgeland stability
conditions does not want ALL of `math.AG` (hundreds of papers per day across
the entire category); they want papers about their specific topic.

**What arXMCP has today:** `ingest/oai_delta.py` harvests all papers from
four hardcoded OAI-PMH sets: `math:math:AG`, `math:math:NT`,
`physics:math-ph`, `physics:hep-th` (`oai_delta.py:109-114`). Every paper in
those categories goes into the corpus. The operator cannot configure "only
ingest papers about derived categories" or "only if the title/abstract mentions
Fourier-Mukai". The OAI-PMH `arXivRaw` metadata prefix returns full abstracts
(`oai_delta.py:119`), which would enable abstract-based relevance filtering
before the expensive ar5iv/LaTeXML fetch — but this filter is not implemented.
The `HarvestedRecord` datatype (`oai_delta.py:177-185`) carries `categories`
from the OAI-PMH record, so the filtering hook point already exists in the
data.

**What a credible v1 fill-in would look like:** Add an optional
`relevance_filter` parameter to `run_delta()` that accepts a callable
`(HarvestedRecord) -> bool`. The simplest implementation: filter on whether
the abstract contains any of a configurable keyword list. A more principled
implementation: after the OAI-PMH harvest (cheap: metadata XML), cross-check
against the arXiv API for a keyword query and intersect the two sets — only
papers that appear in BOTH (category AND topic query) get the expensive
ar5iv/LaTeXML treatment. This is additive to `DeltaSummary` (adds a
`records_filtered: int` field) and does not change the existing no-filter path.

**Architecture-lock interaction:** The existing staging-path discipline
(`oai_delta.py:18-24`) is unaffected; filtering happens before the per-paper
feed. The `dry_run=True` path in `run_delta()` can print filtered records
separately. No new dependencies. Not a blocker for the core corpus; purely
additive.

**Why this hasn't been fixed yet:** The delta loop was designed for "keep the
corpus current across all four categories." Per-notebook or per-topic filtering
was never in scope because there was no notebook-discovery concept on the
roadmap. The OAI-PMH design was correctly prioritized over scraping
(`03-ingestion-pipeline.md`); the next step (topic-aware filtering) is a
natural extension that was never planned.

---

### M4 — No "suggest papers from citation graph" discovery path for notebooks

**Gap name:** Citation graph exists but is not wired to notebook-expansion discovery

**Severity:** MEDIUM

**What comparable systems/SOTA expects:** Semantic Scholar, Connected Papers, and
Inciteful all surface citation-graph expansion as a primary discovery mechanism.
"Papers that cite papers already in my notebook" and "papers cited by papers
in my notebook" are the highest-precision discovery signals available — they
are pre-filtered by the intellectual lineage of exactly the papers the operator
already knows are relevant.

**What arXMCP has today:** The Kùzu citation graph (E09) with `cite_neighbors()`
library (`server/graph_queries.py`) can return papers 1-2 hops from any paper
in the graph. The MCP tool `cite_neighbors` is registered. But:
- The tool takes a `chunk_id`, not a notebook slug. There is no
  "expand notebook via citation graph" flow.
- The `cite_neighbors` MCP handler is still a v1 stub (`CLAUDE.md §7`); the
  library is real but the MCP boundary is not fully wired for production use.
- `cite_neighbors` returns `paper_id` + `representative chunk_id`; there is no
  "check if these papers are already in the notebook and filter them out"
  logic.
- The notebook junction table (`notebook_papers`) is not accessible to the
  server-side graph query — the graph query has no awareness of the notebook
  model.

**What a credible v1 fill-in would look like:** A `tools/notebook_expand.py`
that: (1) reads the notebook's `papers.txt` (or `notebook_papers` junction),
(2) calls `cite_neighbors(depth=1, direction="cited_by")` for each paper,
(3) deduplicates against papers already in the notebook, (4) returns the top-N
candidate paper IDs with their hop distance + confidence. This is a pure
read-path operation — it touches only the Kùzu graph and the notebook junction
table, both of which are available. The core `server/graph_queries.py`
`cite_neighbors()` function is real and callable today.

**Architecture-lock interaction:** The `cite_neighbors` MCP handler stub issue
(`CLAUDE.md §7`) is a separate concern; the underlying library is real. The
expansion tool would call the library directly (not the MCP tool). The
notebook junction table is SQLite — accessible synchronously from a CLI tool
without the server running. No new dependencies. The "propose then confirm"
UX model applies here too: the tool surfaces candidates, the operator decides
which to add.

**Why this hasn't been fixed yet:** The notebook model (post-E09) and the
citation graph (E09) developed in parallel milestones with no cross-wiring.
E09_S04 explicitly notes the `cite_neighbors` MCP handler stub is deferred
pending the path-validation contract formalization.

---

## 5. Low Gaps

### L1 — arXiv API query in curate_seed.py lacks pagination

**Gap name:** curate_seed.py makes a single API call with no result-set pagination

**Severity:** LOW

**What arXMCP has today:** `tools/curate_seed.py:128-133` makes a single
`fetch_candidates()` call with `start=0` and `max_results` (default 200, max
2000). For topics with thousands of papers (math.AG has tens of thousands),
a single page will miss recent papers if they land outside the top-2000.

**What a credible v1 fill-in would look like:** Add a simple pagination loop:
`while records_fetched < target_count: fetch page, sleep 3s, advance start`.
The arXiv API `start` parameter supports standard offset pagination. Minor
addition to `_arxiv_api.py` (the M2 refactoring creates the right home for it).

**Architecture-lock interaction:** The politeness sleep already applies.
The arXiv API max per-request is 2000 (`curate_seed.py:143: max 2000 per arXiv`).
Pagination is uncontroversial.

**Why this hasn't been fixed yet:** The seed-curation use case only needed 50
papers; 200 was more than enough. The function was never used for exhaustive
discovery.

---

### L2 — No UI affordance for "discover papers" on the notebook detail page

**Gap name:** Notebook UI has no discovery entry point (after H1 is fixed, the UI still needs wiring)

**Severity:** LOW

**What arXMCP has today:** The notebook detail page (`server/routes/ui.py`,
`frontend/templates/`) has: paper list, add-by-URL form, upload, ingest button,
rename. There is no "Find related papers" panel.

**What a credible v1 fill-in would look like:** A text input + button on the
notebook detail page: "Search arXiv for papers to add" → calls a new
`GET /ui/api/notebooks/{slug}/discover?q=<query>` route → returns an HTML table
of candidate paper IDs + titles + abstracts with "Add" buttons. The htmx
patterns are already present (`hx-post`, `hx-swap`). This is the UI skin over
the H1 fill-in; architecturally trivial once H1 exists.

**Architecture-lock interaction:** No Node, no SPA. Pure Jinja2+htmx server-
rendered fragment, same pattern as the existing rename and ingest-status
endpoints. The `_paper_row_html()` pattern in `server/routes/notebooks.py:1097-1131`
already shows how to return HTML table rows for htmx swap.

**Why this hasn't been fixed yet:** The discovery backend (H1) doesn't exist
yet, so the UI panel has no backend to call.

---

## 6. What arXMCP does well (calibration anchor)

- **TOS-compliant ingest infrastructure is already in place.** `tools/arxiv_fetch.py` and `ingest/oai_delta.py` correctly implement the 3-second politeness contract, User-Agent with contact email, 503 backoff with Retry-After, and content-length caps. The "rate limiting problem" crawl4ai was supposed to solve does not exist here.

- **OAI-PMH delta loop is production-grade.** `ingest/oai_delta.py` handles resumption tokens, cross-day crash recovery, daily state persistence, budget alerts, and multi-set harvest with correct token-set pairing (F3 rectification). The foundation for freshness is solid.

- **arXiv API is already wired in `curate_seed.py`.** `build_query_url()`, `fetch_candidates()`, and `parse_atom_feed()` are all present and correct at `tools/curate_seed.py:68-110`. The semantic building block for topic-driven discovery exists; it just needs to be refactored into a reusable module and called from a notebook-aware flow.

- **The notebook model has a clean, secure foundation.** The SQLite schema, path-traversal defense (`validate_slug`), upload preflight, htmx polling for ingest status, and metadata-only delete semantics are all implemented and tested. Adding a topic/description field is additive to a stable base.

- **Citation graph is available as a high-precision discovery signal.** `server/graph_queries.py`'s `cite_neighbors()` is real and callable. Papers in the same intellectual lineage as papers the operator already selected are the highest-precision expansion signal available — and they require no external API call after initial ingest.

- **The design constitution explicitly rejects live scraping.** `03-ingestion-pipeline.md` § "Non-goals" states: "Live arXiv listings scraping (use OAI-PMH)." The architectural constraint against crawl4ai-style scraping is already a first-class design principle, not something that needs to be invented here.

---

## 7. Themes

The dominant theme across all gaps is **operator-supplied vs system-assisted corpus composition**: arXMCP is currently 100% operator-driven in what goes into a notebook (the operator pastes URLs, uploads files, or edits `papers.txt`). The missing capability is a system-assisted path that takes the operator's stated research interest and proposes papers — but all the building blocks (arXiv API in `curate_seed.py`, OAI-PMH freshness in `oai_delta.py`, citation graph in `graph_queries.py`) are already present. The gap is in wiring them into a notebook-aware discovery flow, not in any fundamental infrastructure missing.

The secondary theme is **crawl4ai is the wrong tool for this job, and the premise behind proposing it is false**: the user's stated reason for considering it ("sidestep rate limiting") rests on a misread of what rate limits exist and how arXMCP already handles them. The arXiv API (`export.arxiv.org/api/query`) already does topic-driven paper discovery at high scale with no rate limit beyond the same 3-second courtesy rule arXMCP already enforces. Adopting crawl4ai would trade a lightweight, TOS-compliant, maintainable HTTP client for a heavyweight headless browser that violates `robots.txt` and is fragile against HTML changes. The correct recommendation is to extend the existing arXiv API path rather than introduce a new scraping dependency.

The third theme, connecting to the prior `2026q2-notebook-ux-storage-ops` scout run, is **the notebook model grows capabilities faster than the design constitution tracks them**: the notebook has no topic metadata because the design notes were written before the notebook feature existed. Each new capability (M1: topic field, H1: discovery, M4: citation-graph expansion) needs to be explicitly planned rather than assumed to follow from the existing model. This is a signal that a formal "notebook model extension spec" should precede any discovery milestone planning.
