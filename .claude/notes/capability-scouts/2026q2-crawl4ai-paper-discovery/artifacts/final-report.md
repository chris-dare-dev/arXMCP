# Final Report — Capability Scout `2026q2-crawl4ai-paper-discovery`

**Date:** 2026-05-31
**Pipeline:** Survey (5 scouts) → Synthesize (14 candidates) → Challenge (0 BLOCKER / 5 MAJOR / 4 MINOR) → Prioritize
**Question asked:** Should arXMCP integrate **crawl4ai** to autonomously discover new arXiv papers for a notebook's topic area, hoping to sidestep arXiv rate-limiting?

---

## 1. Executive summary

**The headline finding is a clean NO on the premise and a clear YES on the feature.** All
5 scouts independently rejected crawl4ai: arXiv rate-limits by **IP at the network layer**
(not by endpoint or user-agent), `arxiv.org/robots.txt` mandates a **15-second crawl-delay**
(5× *slower* than the official API's 3s) and **disallows `/search`, `/api/`, `/oai2/`,
`/e-print/`**, and crawl4ai drags in a mandatory **Playwright/Chromium (~300–500 MB)** browser
plus a vendor-forked `unclecode-litellm` — colliding with arXMCP's local-first, no-browser,
Windows, and E13-supply-chain constraints, for **zero capability gain** over the structured API.
The user's hope ("scraping sidesteps rate-limiting") is factually false. arXMCP's design
constitution already lists "live arXiv listings scraping" as a **non-goal**
(`03-ingestion-pipeline.md`).

**The feature itself is real, wanted, and ~90% already built** — it is an *orchestration gap,
not a capability gap.* arXMCP already has the polite arXiv fetch, the arXiv Atom API call shape
(`tools/curate_seed.py`), the OAI-PMH delta loop, the OpenAlex client, the per-paper ingest
pipeline, the Kùzu citation graph, and BGE-M3 embeddings. The top-3 by RICE are
**CAND-1 — arXiv Atom topic-discovery channel (9.0)**, **CAND-5 — notebook topic/description
field (6.0)**, and **CAND-4 — local citation+embedding expansion (4.5)**. The thematic
recommendation: ship a **single v1 milestone** that bundles the cheap, co-dependent core —
CAND-6 (refactor) + CAND-5 (topic field) + CAND-1 (arXiv Atom channel) + CAND-10 (propose→confirm
operator panel) — using **official APIs behind a deterministic, LLM-free, human-confirmed
ingest flow.** The Semantic-Scholar and OpenAlex channels (CAND-2/3) and the local citation
expansion (CAND-4) are fast-follows; the agent-facing MCP tool (CAND-9) and pre-ingest scoring
(CAND-7) are v2.

**Honest caveat:** this is a discovery scout (15-min scout budgets, t-shirt effort estimates).
The architectural verdict on crawl4ai is high-confidence (5/5 triangulation + verified
robots.txt/ToS). The effort estimates carry ±50%; the challenger already re-sized four "S"
candidates to S–M once dedup, notebook-LanceDB routing, API-ID resolution, and tests are
counted.

---

## 2. Quick-glance ranking table

| Rank | Cand | Title | Category | Size | R | I | C | E | Adj | RICE | Challenger |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | CAND-1 | arXiv Atom topic-discovery channel | Ingestion | S | 3 | 3 | 1.0 | 1 | — | **9.0** | MINOR |
| 2 | CAND-5 | Notebook topic/description field (v5) | MCP/notebook model | XS | 3 | 1 | 0.5 | 0.25 | — | **6.0** | MINOR |
| 3 | CAND-4 | Local citation+embedding expansion | Citation graph | S–M | 3 | 3 | 1.0 | 2 | — | **4.5** | MINOR |
| 4 | CAND-10 | Discovery orchestrator + console panel | Ops / infra | S–M | 3 | 3 | 0.8 | 2 | ×0.75 | **2.7** | MAJOR |
| 5 | CAND-8 | OAI-PMH topic-relevance filter hook | Ingestion | S | 3 | 1 | 0.5 | 1 | — | **1.5** | MINOR |
| 6 | CAND-6 | Refactor curate_seed → `_arxiv_api` lib | Ingestion | XS | 1 | 1 | 0.3 | 0.25 | — | **1.2** | NONE |
| 7 | CAND-2 | Semantic Scholar Recommendations channel | Ingestion | S–M | 3 | 1 | 1.0 | 2 | ×0.75 | **1.13** | MAJOR |
| 7 | CAND-3 | OpenAlex Topics channel | Ingestion | S–M | 3 | 1 | 1.0 | 2 | ×0.75 | **1.13** | MAJOR |
| 9 | CAND-11 | arXiv API pagination | Ingestion | XS | 1 | 0.5 | 0.3 | 0.25 | — | **0.6** | NONE (fold→CAND-6) |
| 9 | CAND-7 | Pre-ingest candidate relevance scoring | Retrieval quality | M | 3 | 1 | 0.8 | 3 | ×0.75 | **0.6** | MAJOR |
| 11 | CAND-9 | Agent-facing `discover_papers` MCP tool | MCP tool surface | M | 3 | 1 | 0.5 | 3 | ×0.75 | **0.38** | MAJOR (v2) |
| — | CAND-12 | "Discover" UI panel | MCP/UI | XS | — | — | — | — | fold | **→ CAND-10** | NONE |
| KILL | CAND-14 | Daily arXiv RSS consumer | Ingestion | XS | 1 | 0.5 | 0.3 | 0.25 | subsumed | 0.6 | KILL |
| KILL | CAND-13 | Mathlib4 theorem discovery | MCP tool surface | M | 1 | 1 | 0.3 | 3 | wrong-milestone | 0.1 | KILL |

**Note on enablers:** CAND-6 (RICE 1.2) and CAND-5 (RICE 6.0) score lower/oddly under raw RICE
because they have 1–2 sources and are infrastructure, but **both are hard dependencies of the
#1 candidate**. RICE ranks them in isolation; the recommended sequencing (below) bundles them.

---

## 3. Top candidates in detail

### Rank 1 — CAND-1 — arXiv Atom API topic-discovery channel · RICE 9.0 · MINOR

**Synthesis entry:** A driver that queries `export.arxiv.org/api/query` with
`cat:<category> AND abs:<topic keywords>` + `submittedDate:[…]` + `sortBy=submittedDate`, parses
Atom XML, dedups against the notebook's paper_ids, and queues new IDs for the existing per-paper
ingest pipeline. The recency/keyword discovery axis. **Most-triangulated candidate (5/5 briefs);
live-verified 2,176 hits for `cat:math.AG AND abs:Bridgeland stability`.** Closest analog:
`tools/curate_seed.py:68-110` (correct API call, but a one-shot TSV-printing CLI). Kills the
adversary scout's highest-severity gap (H1).

**Challenger (MINOR):** `build_query_url(category, start, max_results)` only builds
`f"cat:{category}"` — it has **no `abs:`/`ti:` topic-keyword support** today. The CAND-6 refactor
must generalize the query (add `abs_keywords`/`ti_keywords` params), else CAND-1 is described as
"reusing the existing function unchanged" when it isn't. **Hard dependency on CAND-6.**

**RICE:** R=3 (expanded corpus serves every downstream role) × I=3 (kills the flagged H1 gap —
the core requested feature) × C=1.0 (5 sources) / E=1 (S) = **9.0**. No adjustment (MINOR).

**Rationale:** Highest value-per-effort, zero-auth, zero ToS risk, most evidence. The engine of
the whole feature.

---

### Rank 2 — CAND-5 — Notebook topic/description metadata field (schema v5) · RICE 6.0 · MINOR

**Synthesis entry:** Add `description TEXT NOT NULL DEFAULT ''` (and/or `discovery_category` /
`topic_keywords`) via an additive v4→v5 SQLite migration, plus a "Research question / topic area"
field in the UI create form. Discovery tools default to this when no explicit query is given.
**Co-dependent enabler for every discovery channel.** Closest analog:
`server/notebooks_store.py` (SCHEMA_VERSION=4, verified) — no topic field today.

**Challenger (MINOR):** The field-shape open question (one free-text `description` vs structured
`(discovery_category, topic_keywords)`) **must be closed before** CAND-1/2/3 are built, because all
three default their query from it. Recommended: ship both — `description` (human context) +
`discovery_category` (validated arXiv category like `math.AG`, fed to CAND-1/3 `cat:` filter). Add
the new column to the restic backup scope.

**RICE:** R=3 (all channels consume it) × I=1 (enabler/parity) × C=0.5 (2 sources) / E=0.25 (XS)
= **6.0**. No adjustment.

**Rationale:** Cheapest unblock with the broadest downstream reach. Without it, every discovery run
needs a hand-typed query and autonomous/scheduled discovery is impossible.

---

### Rank 3 — CAND-4 — Local citation-graph + embedding neighborhood expansion · RICE 4.5 · MINOR

**Synthesis entry:** Given a notebook's paper_ids, walk Kùzu `cite_neighbors(cited_by/cites,
depth=1–2)`, score out-of-corpus neighbors by BGE-M3 cosine similarity to the notebook centroid,
return top-N un-ingested paper_ids. The **fully-local, curation-respecting** discovery axis
(Connected-Papers pattern). 4/5 briefs; research-frontier cites Church et al. 2024
(arXiv:2407.05836) confirming content+graph hybrid beats either alone.

**Challenger (MINOR):** Two real seams. (1) Kùzu graph **may be empty** on a fresh install
(`python -m ingest.graph_ingest` must have run) → must emit a clear "graph not populated"
diagnostic, not a silent empty list. (2) `cite_neighbors` takes a **`chunk_id`, not a `paper_id`**
(verified `server/graph_queries.py:52-54`) → needs a `paper_id → representative chunk_id` bridge.
The "zero-external-API" claim is true only for the *traversal*; out-of-corpus neighbor abstract
resolution adds N OpenAlex calls (CC-5).

**RICE:** R=3 × I=3 (decisive — external tools can't match a discovery scoped to the operator's
own curated corpus + citation lineage) × C=1.0 (4 sources) / E=2 (S–M) = **4.5**. No adjustment.

**Rationale:** The one candidate that needs no new outbound discovery API and respects existing
curation. **Carries an unvalidated prerequisite (graph coverage)** → route to the `/roadmap`
Spike lane before committing a milestone.

---

### Rank 4 — CAND-10 — Discovery orchestrator + operator-console "Discover" panel · RICE 2.7 · MAJOR

**Synthesis entry:** The glue: a `tools/discover_for_notebook.py` driver running one/more channels,
dedup, ranked candidates; a loopback `POST /ui/api/notebooks/{slug}/discover` htmx panel listing
candidates with title+abstract + per-row "Add" (propose→confirm); optional periodic refresh. The
v1 "Option A" deterministic path. Absorbs CAND-12 (UI panel). 3/5 briefs.

**Challenger (MAJOR):** (1) **Candidate-queue persistence is unspecified** — the propose UI can
only show what the API just returned; no local store for "discovered-but-not-confirmed" candidates,
so the list dies on server restart / navigation. Resolve: ephemeral (label "Refresh to re-run") or
add a `notebook_discovery_candidates` table. (2) The `papers` metadata table is absent
(`get_paper` returns NULL title/abstract; `_paper_row_html` at `notebooks.py:1097` shows only
slug+paper_id+added_at) — a permanent UX seam, though channels supply metadata at discovery time.
(3) **Windows cron** — the project is win32; `schtasks`/Task Scheduler note required, not Unix cron.
Re-size to S–M.

**RICE:** R=3 × I=3 (the user-facing surface where the feature actually ships) × C=0.8 (3 sources)
/ E=2 (S–M) = 3.6 × **0.75** (MAJOR) = **2.7**.

**Rationale:** The feature's face. Slightly penalized for the persistence/Windows-cron gaps, which
must be resolved in design. Pairs with CAND-1 as the v1 milestone.

---

### Rank 5 — CAND-8 — OAI-PMH topic-relevance filter hook · RICE 1.5 · MINOR

**Synthesis entry:** Optional `relevance_filter: Callable[[HarvestedRecord], bool]` on `run_delta()`
to drop category-wide records that don't match a topic before the expensive ar5iv/LaTeXML fetch;
adds `records_filtered` to `DeltaSummary`. 2 briefs.

**Challenger (MINOR):** A misconfigured filter could silently stop the production corpus from
growing → add a `filter_ratio_warn_threshold=0.8` warning. `DeltaSummary` has **no
`records_filtered`** today (verified `oai_delta.py:187-198`) — additive but a typed-surface change
tests snapshot. **Sequence as v2** — at v1, CAND-10 can cross-check arXiv-Atom results against
OAI-PMH post-hoc without touching production `run_delta()`.

**RICE:** R=3 × I=1 × C=0.5 / E=1 = **1.5**. v2 refinement.

---

### Rank 6 — CAND-6 — Refactor `curate_seed.py` → `tools/_arxiv_api.py` · RICE 1.2 · NONE

**Synthesis entry:** Extract `build_query_url`/`fetch_candidates`/`parse_atom_feed` into a shared
module with `sleep=` injection; `curate_seed.py` becomes a thin CLI wrapper. **Hard enabler for
CAND-1.** Challenger: clean (NONE) — but its scope MUST include the `abs:`/`ti:` query-param
generalization that CAND-1 needs (per MINOR-1). RICE understates it because it's a 1-source
infra refactor; treat as the **first task of the CAND-1 milestone**, not a standalone item.

---

### Rank 7 (tie) — CAND-2 — Semantic Scholar Recommendations channel · RICE 1.13 · MAJOR

**Synthesis entry:** Positive-seed similarity discovery (SPECTER2, past-60-day window) returning
`externalIds.ArXiv`; semantic axis complementary to CAND-1's keyword axis. 4 briefs.
**Challenger (MAJOR):** (1) S2 Recommendations takes **S2 internal IDs, not arXiv IDs** — needs an
arXiv→S2 resolution pass (one lookup/paper at 1 rps), doubling LOC → S–M. (2) Free **API key**
required → operator setup + graceful-degradation-when-absent. (3) **Pure-math (math.AG/NT)
coverage on S2 is genuinely thinner** than CS/biomed — precision risk for topics like Bridgeland
stability. **Gate as v2 fast-follow after CAND-1.** RICE: R=3 × I=1 × C=1.0 / E=2 × 0.75 = **1.13**.

### Rank 7 (tie) — CAND-3 — OpenAlex Topics channel · RICE 1.13 · MAJOR

**Synthesis entry:** Resolve topic → OpenAlex Topic ID, filter `/works` by `primary_topic.id` +
date; concept-taxonomy axis. 4 briefs. **Challenger (MAJOR):** (1) **arXiv-ID extraction is
fragile** — `host_organization_name:arxiv` is inconsistent; 10–30% of pure-math works may lack a
clean `ArXiv` external ID → partial-hit handling required. (2) OpenAlex **API key reportedly
required since Feb 2026** → setup + client migration. (3) The synthesis's claim that CAND-3
"closes the `--category` `NotImplementedError`" is **wrong** — verified: CAND-3 creates a *new*
module; the `graph_ingest.py` stub (lines 763-768) stays deferred. Drop that claim. **Gate as v2.**
RICE: R=3 × I=1 × C=1.0 / E=2 × 0.75 = **1.13**.

---

### Ranks 9–11 (v2 / fold-ins)

- **CAND-11 (pagination, 0.6, NONE)** — fold into CAND-6 (~10 LOC; net correctness for >2,000-result topics).
- **CAND-7 (pre-ingest scoring, 0.6, MAJOR)** — challenger: BGE-M3 is **not** "already loaded" in a
  CLI/ingest process (separate ~2.5 GB load), centroid computation couples to LanceDB, and the
  novelty-threshold stop has false-positive (thin notebooks) / false-negative (full-category
  corpora) risks. Re-size to M. **v2** — v1 dedup + agent-reads-abstracts is enough.
- **CAND-9 (agent-facing MCP tool, 0.38, MAJOR)** — explicitly v2 in both source briefs; forces an
  `EXPECTED_TOOL_SCHEMA_SHA256` re-pin + a **permanent BP1 cold-start cache bust** across the
  4-agent fan-out → must be **batched** with other tool additions (`notes/07 §Property 1`); must
  stay LLM-free (`§4.7`); snippet-bearing results honor the 150-char contract.

---

## 4. Recommended next steps

1. **Feed ONE bundled milestone to `/roadmap` first: the v1 discovery core.** Bundle **CAND-6 →
   CAND-5 → CAND-1 → CAND-10** into a single milestone "notebook topic-driven discovery (official
   arXiv Atom channel, propose→confirm)." This is the smallest coherent slice that ships the
   requested feature end-to-end, zero-auth, zero ToS risk, no new heavy deps. RICE-justified
   (top-2 candidates + the surface they need).

2. **Spike-lane CAND-4 before committing it.** Its value is high (RICE 4.5) but it carries an
   **unvalidated prerequisite** — the Kùzu citation graph must be populated for the operator's
   notebooks, and `cite_neighbors`' MCP handler is a stub (the library works). The `/roadmap`
   skill should place a `[MUST]` spike: "verify Kùzu graph coverage for a real notebook + confirm
   the `paper_id → chunk_id` bridge" before a milestone.

3. **Sequence CAND-2 + CAND-3 as v2 fast-follows**, each behind its own API-key/operator-setup
   decision and graceful-degradation requirement (CC-1). They add the semantic + taxonomy axes once
   the keyword core is proven. Do **not** put all three channels in v1 (CC-3: the orchestrator must
   dedup *after* channel aggregation, not inside each channel).

4. **Pre-write a 1–2 page "notebook discovery model" extension spec** under `.claude/notes/` or
   `.claude/docs/` BEFORE the milestone (CC-4). Commit the field schema (CAND-5 shape),
   the propose→confirm model + candidate-queue persistence choice (CAND-10 MAJOR-5), and channel
   priority/dedup boundary. This prevents CAND-5/8/10/9 from making incompatible choices across
   separate milestones — the notebook model has repeatedly outrun the design constitution.

5. **Park for a future scout/milestone:** CAND-7 (pre-ingest scoring), CAND-8 (OAI-PMH filter),
   CAND-9 (agent MCP tool). **Kill:** CAND-13 (Mathlib4 — wrong milestone, verification tooling)
   and CAND-14 (RSS — subsumed by Atom API + OAI-PMH).

6. **Record the crawl4ai verdict so it doesn't recur.** Add a one-line non-goal to
   `.claude/notes/03-ingestion-pipeline.md` (or its non-goals list) and/or a CLAUDE.md §8 gotcha:
   "crawl4ai / browser-scraping of arXiv was evaluated 2026-05 and rejected — robots.txt 15s
   crawl-delay, `/search` disallowed, Playwright dep; use the official arXiv Atom API."

---

## 5. Honest limitations

- **Scout budget:** each of the 5 scouts had ~15 wall-clock minutes; the math-specialized-search
  and commercial-RAG corners (zbMATH, Elicit, Consensus) were 403-blocked and under-explored.
- **Triangulation is strong but not infallible:** 5/5 agreement on the crawl4ai rejection is the
  highest-confidence result here (and is backed by verified robots.txt/ToS), but the *effort*
  estimates are t-shirts → person-weeks with ±50% realistic accuracy. The challenger already
  re-sized four "S" candidates to S–M.
- **API-terms drift:** the OpenAlex (Feb 2026) and S2 API-key requirements were reported by the
  oss-trends scout but not all independently re-verified at terms-of-service level — confirm before
  scoping CAND-2/CAND-3.
- **Architecture-lock snapshot:** the challenger judged against current `CLAUDE.md` locks (no
  runtime `anthropic` SDK, BP1/BP2 discipline, local-first). If those evolve, the v2 MCP-tool
  candidate (CAND-9) calculus changes.
- **One verified discrepancy:** the live tool count is **8** (incl. `LEAN_VERIFY`), not the 7 in
  CLAUDE.md §6 — minor doc drift, noted by the challenger.

---

## 6. Cross-reference index

| Cand | Comparative | Research-frontier | OSS-trends | Multi-agent | Adversary | # |
|---|---|---|---|---|---|---|
| CAND-1 (arXiv Atom) | C1 | M4 | #2 | C2 | H1 | **5** |
| CAND-2 (S2 Recommendations) | C2,C4 | M3 | #5 | C1,C7 | — | 4 |
| CAND-3 (OpenAlex Topics) | C5 | M1 | #4 | C8 | — | 4 |
| CAND-4 (citation+embedding) | C9 | M5 | — | C4 | M4 | 4 |
| CAND-5 (topic field) | C6 | — | — | — | M1 | 2 |
| CAND-6 (arxiv-api refactor) | — | — | — | — | M2 | 1 |
| CAND-7 (candidate scoring) | C4 | M2,M6 | — | C4,C5 | — | 3 |
| CAND-8 (OAI-PMH filter) | C3 | — | — | — | M3 | 2 |
| CAND-9 (discover MCP tool) | C6 | — | — | C6-B | — | 2 |
| CAND-10 (orchestrator+panel) | — | — | #7,#8 | C6-A | H1,L2 | 3 |
| CAND-11 (pagination) | — | — | — | — | L1 | 1 |
| CAND-12 (UI panel→CAND-10) | — | — | — | — | L2 | 1 |
| CAND-13 (Mathlib4) | C10 | — | — | — | — | 1 |
| CAND-14 (RSS) | C8 | — | — | — | — | 1 |
| **crawl4ai (REJECTED)** | C7 | parking | #1 | C3 | H2 | **5** |

---

## Handoff offer

The top candidates above (3 rank at RICE ≥ 3.0; the v1 bundle CAND-6+CAND-5+CAND-1+CAND-10 is the
recommended first cut) are ready to feed the `roadmap` skill as a source brief. To materialize as a
roadmap with milestones:

    /roadmap notebook-paper-discovery --brief "$(head -200 .claude/notes/capability-scouts/2026q2-crawl4ai-paper-discovery/artifacts/final-report.md)"

The roadmap skill will refine → decompose → sequence → materialize from this report; its milestones
(`notebook-paper-discovery-mN`) hand off to `/milestone-pipeline` for execution. Recommend it place
**CAND-4 (Kùzu graph coverage)** in its Spike lane as a `[MUST]` before that milestone.

*(capability-scout never auto-invokes `/roadmap` — this is offer-and-wait. Type the command if you
want to proceed.)*
