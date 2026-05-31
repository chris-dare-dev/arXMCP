# Synthesis — Capability Scout `2026q2-crawl4ai-paper-discovery`

**Date:** 2026-05-31
**Survey mode:** standard (5 scouts)
**Briefs synthesized:** comparative, research-frontier, oss-trends, multi-agent, adversary

---

## 1. Executive summary

This scout was commissioned to evaluate integrating **crawl4ai** into arXMCP so a
notebook (e.g. "Bridgeland stability conditions") can autonomously discover NEW arXiv
papers and pull them in as additional context — with the user's stated hope that
scraping would **sidestep arXiv's rate-limiting**. All 5 scouts independently reached
the same verdict: **crawl4ai is the wrong tool, and the rate-limiting premise is
false.** arXiv rate-limits by IP at the network layer (not by endpoint or
user-agent); `arxiv.org/robots.txt` mandates a **15-second** crawl-delay and
**disallows `/search`, `/api/`, `/oai2/`, `/e-print/`** — making scraping both a
ToS/robots violation **and slower** than the official API's 3-second limit, while
adding a mandatory Playwright/Chromium (~300–500 MB) browser dependency that
collides with arXMCP's local-first, no-browser, Windows-friendly constraints.

The genuinely valuable finding is that **the requested feature is real, wanted, and
~90% already built** — it is an *orchestration gap, not a capability gap*. arXMCP
already has the polite arXiv fetch (`tools/arxiv_fetch.py`), the arXiv Atom API call
shape (`tools/curate_seed.py`), the OAI-PMH delta loop (`ingest/oai_delta.py`), the
OpenAlex client (`ingest/graph_ingest.py`), the per-paper ingest pipeline, the Kùzu
citation graph (`cite_neighbors`), and BGE-M3 embeddings. What is missing is the
*wiring*: a notebook that declares its topic, a discovery driver that calls the
official APIs with that topic, and a propose→confirm surface that queues new
paper_ids into the existing pipeline.

**14 candidates** emerged, dominated by the **Ingestion / parsing** and **MCP tool
surface** categories. The top theme: *use the official discovery APIs (arXiv Atom,
Semantic Scholar Recommendations, OpenAlex Topics) that arXMCP already knows how to
call — three complementary channels — behind a deterministic, LLM-free ingest job.*
The top cross-cutting tension: **autonomous auto-ingest vs operator propose→confirm**
— the user asked for "autonomously go discover," but the adversary scout and the
design constitution (`01-mission-and-context.md` "power tool, not autopilot") push
toward a human-in-the-loop confirm step.

---

## 2. Triangulation strength

- **Strong signal (3+ briefs):** CAND-1 (5), CAND-2 (4), CAND-3 (4), CAND-4 (4),
  CAND-7 (3), CAND-10 (3) — **6 candidates**.
- **Moderate signal (2 briefs):** CAND-5 (2), CAND-8 (2), CAND-9 (2) — **3 candidates**.
- **Weak signal (1 brief — flag for challenger scrutiny):** CAND-6 (1), CAND-11 (1),
  CAND-12 (1), CAND-13 (1), CAND-14 (1) — **5 candidates**.

The crawl4ai rejection is itself a 5-brief unanimous finding (see Parking lot); it is
not a build candidate, so it is excluded from the catalog count.

---

## 3. Candidate catalog

### Ingestion / parsing

#### CAND-1 — Add an arXiv Atom API topic-discovery channel

**Category:** Ingestion / parsing
**Size:** S
**Evidence triangulation:** 5 briefs (comparative ✓, research-frontier ✓, oss-trends ✓, multi-agent ✓, adversary ✓)

**What it is:** A driver that queries `export.arxiv.org/api/query` with
`cat:<category> AND abs:<topic keywords>` + `submittedDate:[…]` + `sortBy=submittedDate`,
parses the returned Atom XML, dedups against the notebook's existing paper_ids, and
queues new IDs for the existing per-paper ingest pipeline. This is the recency/keyword
discovery axis.

**Why it matters:** It is the single most-triangulated, lowest-risk way to give the
sketcher a fresh, topic-relevant corpus — "what appeared in math.AG mentioning
Bridgeland stability in the last 30 days" — with zero ToS risk and zero new deps.

**Sources:**
- Comparative scout: Candidate 1 (live-verified: 2,176 hits for `cat:math.AG AND abs:Bridgeland stability`)
- Research-frontier scout: M4 (arXiv Atom `cat:`+`submittedDate`, ~100 LOC)
- OSS-trends scout: Entry #2 (arxiv.py query idiom; native re-impl ~150 LOC, no dep)
- Multi-agent scout: C2 (keyword+category+date; reuse `politeness_sleep`)
- Adversary scout: H1 (the highest-severity gap; `curate_seed.py` already has the call shape)

**Closest arXMCP analog (today):** `tools/curate_seed.py:44-110` (`build_query_url`,
`fetch_candidates`, `parse_atom_feed`) — correct API call, but a one-shot human-curation
CLI that prints a TSV and exits; not notebook-aware, not a reusable library. Depends on CAND-6.

**Sketch:** New `tools/notebook_discover.py` (or `ingest/arxiv_search.py`) exposing
`search_recent(category, topic_keywords, since_date, max_results) -> list[paper_id]`,
reusing `tools/arxiv_fetch.py`'s 3s politeness + User-Agent. Feeds
`ingest_one_paper(paper_id, lancedb_path=notebook_dir(slug))` and records IDs in the
`notebook_papers` junction. Pagination via `start`+`max_results` (CAND-11).

**Open questions:** arXiv Atom searches only title/abstract/metadata (not full LaTeX
body) — narrow topics that appear only in body text are missed; does semantic
re-ranking (CAND-7) close that gap acceptably?

---

#### CAND-2 — Add a Semantic Scholar Recommendations discovery channel

**Category:** Ingestion / parsing
**Size:** S
**Evidence triangulation:** 4 briefs (comparative ✓, research-frontier ✓, oss-trends ✓, multi-agent ✓)

**What it is:** Given the notebook's existing paper_ids as positive seeds, call S2's
`/recommendations/v1/papers` (multi-seed) or `/forpaper/{id}` (single-seed) endpoint,
which returns up to 500 papers from the **past 60 days** ranked by SPECTER2
citation-graph similarity, each carrying `externalIds.ArXiv`. Dedup, score by
recommendation frequency, queue new arXiv IDs. This is the semantic-similarity
discovery axis (complementary to CAND-1's keyword axis). Folds in S2 bulk keyword
search (comparative C4) for the cold-start case where a notebook has no seeds yet.

**Why it matters:** Keyword search misses conceptually-adjacent papers that use
different terminology; SPECTER2 similarity surfaces the citation-neighborhood of what
the operator already curated — higher precision than any keyword query for an
established notebook.

**Sources:**
- Comparative scout: Candidate 2 + Candidate 4 (S2 recommendations + bulk search; live-verified 335 hits with arXiv IDs)
- Research-frontier scout: M3 (citation-graph + SPECTER2 hybrid, ~120 LOC)
- OSS-trends scout: Entry #5 (`/recommendations/v1/papers/forpaper/{id}`, ~80 LOC, urllib only)
- Multi-agent scout: C1 + C7 (positive-seed; SPECTER2 centroid via API, no local model)

**Closest arXMCP analog (today):** `ingest/graph_ingest.py` (E09_S01) already calls an
external scholarly API (OpenAlex) over the same paper_id set; S2 is a parallel channel
with the same HTTP-call pattern. No MCP analog. `server/graph_queries.py::cite_neighbors`
is the *local* analog but only traverses already-ingested papers.

**Sketch:** New `ingest/s2_discovery.py` — `discover_by_seeds(paper_ids, k) -> list[paper_id]`,
bare `urllib.request` JSON GET, 1s polite sleep, dedup against LanceDB, resolve
`externalIds.ArXiv` → arXiv ID → existing `ingest_one_paper`. Needs a free S2 API key
(self-service; 1 req/s authenticated).

**Open questions:** S2 TLDR/coverage for pure-math (math.AG/NT) may be thinner than CS;
S2 API key is a new operator-setup step — acceptable for local-first?

---

#### CAND-3 — Add an OpenAlex topic-filtered Works discovery channel (closes the `--category` stub)

**Category:** Ingestion / parsing
**Size:** S
**Evidence triangulation:** 4 briefs (comparative ✓, research-frontier ✓, oss-trends ✓, multi-agent ✓)

**What it is:** Resolve a notebook's free-text topic to an OpenAlex Topic ID
(`/topics?search=…`), then filter `/works?filter=primary_topic.id:<ID>,from_publication_date:<date>`
(optionally `locations.source.host_organization_name:arxiv`) to enumerate recent arXiv
papers in that topic. This is the concept-taxonomy discovery axis, and it **resolves
the long-standing `NotImplementedError`** in `ingest/graph_ingest.py:57-65` (the
deferred "Tier-3 category-bulk discovery using Topics").

**Why it matters:** OpenAlex Topics give a stable, granular subfield classification
that survives across runs (a notebook resolves "Bridgeland stability" → Topic ID once),
plus generous rate limits (10–100 rps vs arXiv's 1/3s), and it clears a documented
debt in the codebase.

**Sources:**
- Comparative scout: Candidate 5 (Topic filters; closes the NotImplementedError)
- Research-frontier scout: M1 (top method; ~150 LOC over existing graph-ingest infra)
- OSS-trends scout: Entry #4 (pyalex `from_publication_date`+`topics.id` pattern)
- Multi-agent scout: C8 (third channel; resolves CLAUDE.md §8 gotcha 3)

**Closest arXMCP analog (today):** `ingest/graph_ingest.py:57-65` — the `--category`
branch raises `NotImplementedError`; this candidate is its intended resolution. Existing
OpenAlex politeness (`OPENALEX_POLITE_SLEEP_SECONDS`) and client pattern are reusable.

**Sketch:** New `ingest/openalex_discovery.py` — `discover_by_topic(topic_id, since) -> list[paper_id]`
reusing the `_fetch_openalex_work`/polite-pool pattern. arXiv ID is not a native
OpenAlex filter field — requires DOI crosswalk or the `host_organization_name:arxiv`
location filter + ID extraction.

**Open questions:** OpenAlex began **requiring a free API key (Feb 2026)** per the
oss-trends scout — confirm current terms; arXiv-ID extraction path (DOI crosswalk vs
location filter) needs verification on math papers.

---

#### CAND-6 — Refactor `curate_seed.py`'s arXiv-API functions into a reusable library

**Category:** Ingestion / parsing
**Size:** XS
**Evidence triangulation:** 1 brief (adversary ✓)

**What it is:** Extract `build_query_url()`, `fetch_candidates()`, `parse_atom_feed()`
from `tools/curate_seed.py` into a shared `tools/_arxiv_api.py` (mirroring
`tools/_notebook_common.py`), with a `sleep=` injection parameter so tests/callers
control politeness. `curate_seed.py` becomes a thin CLI wrapper. Pure refactor, no
behavior change. **Enabler for CAND-1.**

**Why it matters:** Without it, CAND-1 either duplicates the arXiv API code or imports
from a CLI module designed to print-and-exit. This is the cheapest possible unblock.

**Sources:**
- Adversary scout: M2 (functions are correct but locked inside a one-shot CLI)

**Closest arXMCP analog (today):** `tools/curate_seed.py:68-187` — right functions,
wrong packaging. `tools/_notebook_common.py` is the precedent for a shared helper module.

**Sketch:** Move three functions + module-level constants into `tools/_arxiv_api.py`;
add `sleep` param defaulting to `time.sleep`; update `curate_seed.py` imports; re-point
existing tests. ~1 day.

**Open questions:** none.

---

#### CAND-8 — Add a topic-relevance filter hook to the OAI-PMH delta loop

**Category:** Ingestion / parsing
**Size:** S
**Evidence triangulation:** 2 briefs (adversary ✓, comparative ✓)

**What it is:** Add an optional `relevance_filter: Callable[[HarvestedRecord], bool]`
to `run_delta()` so the nightly OAI-PMH harvest can drop category-wide records that
don't match a notebook's topic (e.g. abstract-keyword match, or intersect with an
arXiv-API topic query) *before* the expensive ar5iv/LaTeXML fetch. The harvested
record already carries `categories` + abstract.

**Why it matters:** Today the delta loop floods the corpus with the entire category
(math.AG = hundreds/day); a topic-scoped notebook wants only its slice. This routes
freshness to relevance and saves ingest compute.

**Sources:**
- Adversary scout: M3 (category-granular not topic-granular; filter hook point exists in `HarvestedRecord`)
- Comparative scout: Candidate 3 + Theme 4 (OAI-PMH under-leveraged for topic-scoped notebooks)

**Closest arXMCP analog (today):** `ingest/oai_delta.py:109-114,177-185` — four
hardcoded sets, no per-topic filter; `HarvestedRecord` already carries `categories`.

**Sketch:** Add `relevance_filter` param (default `None` = current behavior),
`records_filtered: int` on `DeltaSummary`, apply before the per-paper feed. Additive,
no new deps, doesn't change the no-filter path.

**Open questions:** Does notebook→category subscription binding belong here or in the
discovery orchestrator (CAND-10)? Sequencing overlap with CAND-1/CAND-5.

---

### Citation graph

#### CAND-4 — Notebook expansion via local citation-graph + embedding neighborhood

**Category:** Citation graph
**Size:** S–M
**Evidence triangulation:** 4 briefs (comparative ✓, research-frontier ✓, multi-agent ✓, adversary ✓)

**What it is:** Given a notebook's existing paper_ids, walk the Kùzu graph
`cite_neighbors(direction=cited_by/cites, depth=1–2)`, score each out-of-corpus
neighbor by BGE-M3 cosine similarity to the notebook's topic/centroid, and return the
top-N un-ingested paper_ids. This is the **fully local, zero-external-API** discovery
axis — it respects the operator's existing curatorial choices (Connected-Papers pattern).

**Why it matters:** Highest-precision expansion signal available: papers in the
intellectual lineage of exactly what the operator already picked, computed offline from
data arXMCP already holds. No ToS surface at all.

**Sources:**
- Comparative scout: Candidate 9 (citation+embedding hybrid; both components exist)
- Research-frontier scout: M5 (bidirectional snowballing; ~80 LOC coordinating existing parts) + Church et al. 2024 (arXiv:2407.05836) confirming content+graph hybrid wins
- Multi-agent scout: C4 (Citegeist diversity-weighted selection pattern, arXiv:2503.23229)
- Adversary scout: M4 (graph exists but not wired to notebook expansion)

**Closest arXMCP analog (today):** `server/graph_queries.py::cite_neighbors` (E09_S03,
real library) + `server/retrieval/ann.py` (BGE-M3 ANN). Neither is combined into an
outward discovery query; `cite_neighbors` takes a `chunk_id`, not a notebook slug, and
its MCP handler is a v1 stub (`CLAUDE.md §7`).

**Sketch:** New `tools/notebook_expand.py` reading `notebook_papers`, calling the
`cite_neighbors` *library* directly (not the stubbed MCP tool), resolving out-of-corpus
neighbors' abstracts via OpenAlex, scoring with BGE-M3 (already loaded), applying a
diversity weight (Citegeist), returning ranked candidates. Out-of-corpus neighbor
resolution adds N OpenAlex calls.

**Open questions:** Depends on graph coverage — neighbors only exist for papers already
in the Kùzu graph (citation ingest must have run). Does the diversity weight matter at
notebook scale or is top-k by similarity enough?

---

### MCP tool surface

#### CAND-5 — Add a notebook topic/description metadata field (schema v5)

**Category:** MCP tool surface (notebook model)
**Size:** XS
**Evidence triangulation:** 2 briefs (adversary ✓, comparative ✓)

**What it is:** Add a `description TEXT NOT NULL DEFAULT ''` (and/or
`discovery_category`/`topic_keywords`) column to the notebooks SQLite schema (additive
v4→v5 migration) and a one-line "Research question / topic area" field in the UI create
form. Discovery tools default to this when no explicit query is given. **Co-dependent
enabler** for every discovery candidate.

**Why it matters:** Today a notebook named "bridgeland-stability" carries no
machine-readable topic — discovery is blind without an operator query every time.
Storing the topic once makes autonomous/scheduled discovery (and CAND-8 routing) possible.

**Sources:**
- Adversary scout: M1 (no topic/intent metadata; additive v5 migration, v1→v4 pattern)
- Comparative scout: Candidate 6 (notebook needs `topic_keywords`+`discovery_category` columns; arxiv-mcp-server `research_alerts` shape)

**Closest arXMCP analog (today):** `server/notebooks_store.py` (SCHEMA_VERSION=4) —
slug/display_name/lancedb_path/notebook_kind/parse_status; no topic field. The PATCH
rename endpoint is the precedent for an additive update route.

**Sketch:** Additive migration (no DROP); extend create + PATCH endpoints; surface a
text field in `frontend/templates/`. Include in restic backup scope.

**Open questions:** One free-text `description`, or structured
`(discovery_category, topic_keywords)`? The latter feeds the arXiv `cat:` filter directly.

---

#### CAND-9 — Agent-facing `discover_papers_for_notebook` MCP tool (ReAct Option B)

**Category:** MCP tool surface
**Size:** M
**Evidence triangulation:** 2 briefs (multi-agent ✓, comparative ✓)

**What it is:** A new MCP tool that lets the *calling* Claude agent steer discovery
iteratively (ReAct-style): each call runs one round of arXiv/S2/OpenAlex discovery for
the notebook, returns candidate summaries, and the agent decides whether to refine and
call again. The server stays LLM-free; all judgment lives in the calling agent. Both
scouts flag this as a **v2** that should follow the operator-trigger v1 (CAND-10).

**Why it matters:** Lets the sketcher adaptively fill corpus gaps mid-session ("results
cover moduli spaces but not K3 surfaces — search K3 next") instead of a fixed batch job.

**Sources:**
- Multi-agent scout: C6 Option B (new tool → mandatory `EXPECTED_TOOL_SCHEMA_SHA256` re-pin)
- Comparative scout: Candidate 6 (arxiv-mcp-server `research_alerts` register→poll shape)

**Closest arXMCP analog (today):** `server/tools.py::ALL_TOOLS` (8 tools, no discover
tool); `server/handlers/`. No analog.

**Sketch:** New `server/handlers/discover.py` + `ToolMeta` in `ALL_TOOLS`; **forces an
`EXPECTED_TOOL_SCHEMA_SHA256` re-pin** (`pytest --update-tool-schema-hash`) and a BP1
cold-start cache bust — must be batched with other tool additions per
`notes/07-multi-agent-caching.md`. Result = deterministic `paper_id` list + ingest
status; Tier-1 cacheable.

**Open questions:** Does an agent-facing discovery tool blur arXMCP's "tool provider, not
director" line? Should it only *propose* (never auto-ingest) to keep the boundary clean?

---

### Ops / infra

#### CAND-10 — Notebook discovery orchestrator + operator-console "Discover" panel (propose→confirm)

**Category:** Ops / infra
**Size:** S
**Evidence triangulation:** 3 briefs (adversary ✓, multi-agent ✓, oss-trends ✓)

**What it is:** The glue that turns the discovery channels into a usable feature: a
`tools/discover_for_notebook.py` driver that runs one or more channels (CAND-1/2/3/4),
dedups, and surfaces ranked candidates; a loopback `POST /ui/api/notebooks/{slug}/discover`
operator-console panel that lists candidates with title+abstract and per-row "Add"
buttons (propose→confirm); and an optional system-cron entry for periodic refresh. This
is the v1 "Option A" deterministic path: the operator/agent triggers it, the agent
consumes the expanded corpus post-ingest.

**Why it matters:** Without orchestration the channels are libraries with no entry
point. This is where the "autonomously discover" user story actually ships — as a
human-confirmed propose flow consistent with "power tool, not autopilot."

**Sources:**
- Adversary scout: H1 (propose/confirm model) + L2 (UI discovery panel; htmx `_paper_row_html` pattern exists)
- Multi-agent scout: C6 Option A (deterministic operator-trigger job; recommended for v1)
- OSS-trends scout: Entry #7 (prefer system cron over APScheduler) + Entry #8 (~200-line thin adapter, zero new deps)

**Closest arXMCP analog (today):** `server/routes/notebooks.py` (existing create/ingest/
rename htmx routes + `IngestTaskTracker`); `frontend/templates/` notebook detail page.
No discovery route or panel.

**Sketch:** Driver composes channel calls → dedup vs `notebook_papers` → return
candidates; htmx panel renders rows reusing `_paper_row_html()`; "Add" routes through
the existing ingest pipeline. Cron invokes the driver per E11's established system-cron
operational model.

**Open questions:** The central tension — auto-ingest top-N vs operator confirms each?
Recommended default: propose→confirm, with an opt-in auto-ingest threshold.

---

### Retrieval quality

#### CAND-7 — Pre-ingest candidate relevance scoring (diversity + novelty-threshold stopping)

**Category:** Retrieval quality
**Size:** S–M
**Evidence triangulation:** 3 briefs (research-frontier ✓, multi-agent ✓, comparative ✓)

**What it is:** A scoring stage that ranks raw discovery candidates *before* committing
them to the expensive parse/embed pipeline: BM25 over abstracts + dense cosine
(BGE-M3 already loaded, or SPECTER2) fused via the existing RRF, with a diversity weight
(Citegeist) so the selected set covers sub-aspects, and a deterministic **novelty-threshold
stopping heuristic** (Stop-RAG analog: stop when <10% of newly-discovered papers are
not already in the corpus). Keeps relevance judgment LLM-free and on the calling
agent's terms.

**Why it matters:** Discovery channels return noisy, oversized candidate sets; scoring
+ stopping bounds ingest cost and surfaces the most relevant N — directly improving what
the sketcher reads, without any server-side LLM call.

**Sources:**
- Research-frontier scout: M2 (SPECTER2 proximity, or reuse BGE-M3 centroid) + M6 (BM25+dense RRF hybrid, arXiv:2401.04055)
- Multi-agent scout: C4 (Citegeist diversity weighting) + C5 (Stop-RAG → deterministic novelty threshold)
- Comparative scout: Candidate 4 (agent-side SPECTER2 pre-screening before ingest)

**Closest arXMCP analog (today):** `server/retrieval/` (BM25→ANN→RRF already
implemented at chunk level) + `ingest/bm25_indexer.py`. No analog at the *pre-ingest
candidate* level; the existing RRF operates on already-ingested chunks.

**Sketch:** New `ingest/candidate_scorer.py` — `score_candidates(notebook_centroid,
candidate_abstracts) -> ranked list`; reuse RRF patterns; prefer BGE-M3 (already loaded)
over a second SPECTER2 model download; expose `novelty_threshold` + `diversity_weight`
knobs. Folds into CAND-10's driver.

**Open questions:** Is a second embedding model (SPECTER2) worth the download vs reusing
BGE-M3? (Research-frontier scout's own M2 says BGE-M3 centroid avoids the second model.)

---

### Weak-signal candidates (1 brief — flagged for challenger scrutiny)

#### CAND-11 — Add result-set pagination to the arXiv API query

**Category:** Ingestion / parsing
**Size:** XS
**Evidence triangulation:** 1 brief (adversary ✓)

**What it is:** Add `start`+`max_results` offset pagination to the arXiv API helper so
discovery can page past the first 2,000 results. Trivial once CAND-6 creates the shared
module.

**Sources:** Adversary scout L1 (`curate_seed.py:128-133` single-call, no pagination).
**Closest arXMCP analog:** `tools/curate_seed.py:128-143`.
**Sketch:** `while fetched < target: fetch page; sleep 3s; advance start`. Lives in
`_arxiv_api.py` (CAND-6).
**Open questions:** Needed at notebook scale (<200 papers/session) or premature?

---

#### CAND-12 — Notebook "Discover papers" UI panel (standalone)

**Category:** MCP tool surface (UI)
**Size:** XS
**Evidence triangulation:** 1 brief (adversary ✓)

**What it is:** The htmx panel on the notebook detail page. Folded into CAND-10 as its
UI skin — listed separately only because the adversary scored it as a distinct (L2) gap.
Not an independent build item if CAND-10 ships.
**Sources:** Adversary scout L2.
**Closest arXMCP analog:** `server/routes/notebooks.py:1097-1131` (`_paper_row_html`).
**Open questions:** Merge into CAND-10 (recommended) or track separately?

---

#### CAND-13 — Mathlib4 theorem discovery (LeanSearch/Moogle) for the autoformalizer

**Category:** MCP tool surface
**Size:** M
**Evidence triangulation:** 1 brief (comparative ✓)

**What it is:** A "does this lemma already exist in Mathlib4?" lookup (LeanSearch/Moogle
pattern) so the autoformalizer can reference an existing formal theorem instead of
guessing. **Orthogonal to paper discovery** — flagged for awareness, not for this feature.
**Sources:** Comparative scout Candidate 10.
**Closest arXMCP analog:** `server/handlers/lemma.py` (arXiv theorem-name index; different
corpus — Mathlib4 formal vs arXiv informal). No public API for LeanSearch.
**Open questions:** Different milestone entirely; belongs to verification tooling, not discovery.

---

#### CAND-14 — Daily arXiv RSS new-submission feed consumer

**Category:** Ingestion / parsing
**Size:** XS
**Evidence triangulation:** 1 brief (comparative ✓)

**What it is:** Poll `export.arxiv.org/rss/<category>` daily for new IDs, filter by topic
keywords client-side, queue matches. Lightweight notification channel.
**Sources:** Comparative scout Candidate 8.
**Closest arXMCP analog:** none (no RSS consumer). Largely **subsumed by CAND-1
(Atom API, more controllable) and the existing OAI-PMH loop** — the multi-agent scout
explicitly parks it as redundant.
**Open questions:** Does RSS add anything over Atom-API + OAI-PMH? (Multi-agent scout: no.)

---

## 4. Cross-cutting tensions

1. **Autonomous auto-ingest vs operator propose→confirm (THE central tension).** The
   user's brief says "autonomously go discover … and add." The adversary scout and
   `01-mission-and-context.md` ("power tool, not autopilot") argue for human
   confirmation before ingest. Resolution likely: propose→confirm as the default
   (CAND-10), with an opt-in auto-ingest threshold for trusted topics. The challenger
   should rule on whether any auto-ingest path is acceptable at v1.

2. **Where the intelligence lives: deterministic ingest job vs agent-driven ReAct loop.**
   The multi-agent scout strongly favors a deterministic, LLM-free job (Option A /
   CAND-10) for v1, deferring the agent-facing tool (Option B / CAND-9) to v2. The
   no-server-LLM lock (`CLAUDE.md §4.7`) makes any server-side relevance LLM a BLOCKER,
   which pushes relevance to deterministic embedding scoring (CAND-7) or to the calling
   agent. Tension: the user said "autonomously," which sounds agentic, but the cheapest
   correct v1 is deterministic.

3. **One channel vs three.** arXiv Atom (CAND-1), S2 Recommendations (CAND-2), and
   OpenAlex Topics (CAND-3) are complementary (keyword / semantic / taxonomy), and the
   multi-agent scout proposes composing all three. But each is its own integration +
   API-key/setup surface. Tension: comprehensiveness vs v1 scope. Likely v1 = CAND-1
   alone (zero-auth, most-triangulated); CAND-2/3 as fast-follows.

4. **API-key / setup friction vs local-first.** arXiv Atom needs no auth; S2 needs a
   free key (1 req/s); OpenAlex now reportedly requires a free key (Feb 2026). Each key
   is an operator-setup step that mildly dents the local-first, zero-config posture.
   Tension surfaced by oss-trends vs the convenience of richer channels.

5. **Second embedding model vs reuse BGE-M3.** Research-frontier M2 proposes SPECTER2
   for candidate scoring, then concedes BGE-M3 (already loaded) can do the centroid
   query without a second ~110M-param download. Tension: marginal ranking quality vs
   dependency/footprint discipline. Default: reuse BGE-M3.

6. **Notebook model outruns the design constitution.** The adversary scout (Theme 3,
   echoing the prior `2026q2-notebook-ux-storage-ops` run) notes the notebook keeps
   gaining capabilities the design notes don't track — a "notebook model extension spec"
   should arguably precede a discovery milestone so CAND-5/CAND-8/CAND-10 share one model.

---

## 5. What's already in flight / pre-existing debt these touch

- **`ingest/graph_ingest.py` `--category` `NotImplementedError`** (CLAUDE.md §8 gotcha 3)
  — CAND-3 is its intended resolution. Not in flight, but a documented deferral.
- **`cite_neighbors` MCP handler v1 stub** (CLAUDE.md §7; E09_S04 deferred pending the
  path-validation contract) — CAND-4 and CAND-9 interact with it. CAND-4 sidesteps the
  stub by calling the *library* directly; CAND-9 would need the boundary contract.
- **OAI-PMH delta loop** (`ingest/oai_delta.py`, E11_S02, shipped) — CAND-8 extends it
  additively. Production code; don't re-litigate the harvest design.
- **`papers` metadata table absent** (`get_paper` returns NULL for title/abstract/etc.,
  CLAUDE.md §7) — discovery candidates need title/abstract for the propose UI; the
  channels return that metadata from the API directly, so this is a parallel concern,
  not a blocker, but worth flagging.
- **Prior scout `2026q2-notebook-ux-storage-ops`** — the adversary scout cross-references
  its H2 (notebook storage/backup scope); CAND-5's new column must join the restic scope.

---

## 6. Parking lot (did not survive synthesis)

- **crawl4ai itself — REJECTED (unanimous, 5/5 briefs).** Wrong tool: (a) the
  rate-limiting premise is false — arXiv limits by IP at the network layer, and
  `robots.txt` mandates a 15s crawl-delay (5× *slower* than the API's 3s) and disallows
  `/search`, `/api/`, `/oai2/`, `/e-print/`; (b) ToS + robots violation exposing the
  operator's IP to bans; (c) mandatory Playwright/Chromium (~300–500 MB) + vendor-forked
  `unclecode-litellm` + Poppler — collides with local-first/no-browser/Windows
  constraints and the E13 supply-chain posture; (d) zero capability gain — the arXiv API
  returns the identical metadata as structured XML; (e) `03-ingestion-pipeline.md`
  already lists "live arXiv listings scraping" as a **non-goal**. Do not adopt; do not
  build a crawl4ai-equivalent browser layer.
- **Local full-corpus Milvus embedding index (Citegeist's literal approach)** — a 2.6M-paper
  local ANN index violates the single-workstation constraint; the S2 Recommendations API
  (CAND-2) provides the same diversified-similarity search server-side. Pattern kept
  (CAND-7), implementation parked.
- **Server-side LLM relevance scoring / MCP `sampling`** — requires the server to call an
  LLM; direct architecture-lock conflict (`CLAUDE.md §4.7`, no `anthropic` SDK at
  runtime). Relevance stays deterministic (CAND-7) or on the calling agent.
- **Local SPECTER2 hosting for centroid queries** — second model download; use BGE-M3
  (already loaded) or the S2 API instead.
- **Scholar Inbox personalized recommendations (arXiv:2504.08385)** — cloud service with
  persistent user profiles; incompatible with local-first.
- **crawl4ai-mcp-server wrapper** — inherits all of crawl4ai's Playwright + ToS issues.
- **zbMATH / Elicit / Consensus / Connected Papers / ResearchRabbit APIs** — variously
  403-blocked or no public API; ideas-only under no-fork; their discovery value is
  covered by arXiv/S2/OpenAlex.
- **CAND-13 (Mathlib4 theorem discovery) and CAND-14 (RSS)** are retained in the catalog
  as weak-signal/orthogonal but are de-prioritization candidates: CAND-13 belongs to
  verification tooling, not paper discovery; CAND-14 is subsumed by CAND-1 + OAI-PMH.
