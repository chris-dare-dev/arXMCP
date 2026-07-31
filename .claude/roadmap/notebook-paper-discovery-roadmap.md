---
project: arxmcp
type: roadmap
status: active
authorship: agent-generated
tags:
- project/arxmcp
- type/roadmap
- authorship/agent-generated
---

# Notebook topic-driven paper discovery — Roadmap

> [!done] ARCHIVED — track complete, retained for the record
> **Moved** from `plans/notebook-paper-discovery-roadmap.md` to `.claude/roadmap/` on 2026-07-29.
> `plans/` is reserved for live `roadmap/1` tracks (`plans/<slug>/roadmap.yaml`);
> `CLAUDE.md` § 1 allows no other Markdown outside `.claude/`. This directory is
> already the home of completed standalone briefs (`notebook-cutover.md`,
> `embedder-truncation.md`, …) and stays inside
> `milestone-pipeline-resolve-brief.py`'s legacy-prose glob, so `/milestone-pipeline`
> still resolves every id below.
>
> **Completed milestones (4)** — `state.json` phase `complete`: `notebook-paper-discovery-m1`, `notebook-paper-discovery-m2`, `notebook-paper-discovery-m3`, `notebook-paper-discovery-m4`
> **Last commit touching this track:** `e6c9d81 chore(notes): finalize notebook-paper-discovery-m4 state -> complete`


**Slug:** `notebook-paper-discovery`
**Created:** 2026-05-31T14:49:03Z
**Status:** init

<!--
This roadmap is itself the state. Re-invoking the `roadmap` skill on
this file resumes from the first un-populated phase. Sections below
contain `{{TOKEN}}` placeholders until their phase runs.

Phases:
  1. REFINE     — How-Might-We, sharpening questions, assumptions, OKR, Won't list
  2. DECOMPOSE  — technique, epics, INVEST, specialist suggestions
  3. SEQUENCE   — MoSCoW, RICE, Now/Next/Later, spike lane, Now-lane milestones
  4. MATERIALIZE — validation results, optional GitHub bundle, next-step handoff
-->

---

## Phase 1 — Refine

<!-- populated by REFINE phase -->

### How Might We

How might we let an operator discover and add new arXiv papers relevant to a
notebook's topic, for the sketcher → autoformalizer → tactician → fixer pipeline that
consumes the corpus, without scraping arXiv or breaking arXMCP's local-first,
deterministic, no-server-LLM constraints?

### Sharpening questions answered

1. **Auto-ingest or propose→confirm?** — Propose→confirm is the v1 default. The design
   constitution frames arXMCP as a "power tool, not autopilot"
   (`.claude/notes/01-mission-and-context.md`), and the scout's adversary brief (H1)
   argues the operator should confirm candidates before the expensive ar5iv/LaTeXML
   ingest. An opt-in auto-ingest threshold is a later enhancement.
2. **Which discovery channel ships first?** — The arXiv Atom API
   (`export.arxiv.org/api/query`, `cat:<category> AND abs:<topic>` + `submittedDate`).
   It is zero-auth, ToS-clean, the most-triangulated candidate (5/5 scout briefs,
   CAND-1), and reuses the existing `tools/curate_seed.py` call shape. Semantic
   Scholar and OpenAlex are fast-follows behind their own API-key decisions.
3. **Where does the "intelligence" live?** — In a deterministic, LLM-free ingest job;
   relevance is judged by the calling agent retrieving over the expanded corpus, never
   by the server. arXMCP runs no `anthropic` SDK at runtime (`CLAUDE.md §4.7`), so any
   server-side LLM relevance call is an architecture-lock violation.
4. **What identifies a notebook's topic?** — Today, nothing: `server/notebooks_store.py`
   is SCHEMA_VERSION=4 with slug/display_name/lancedb_path/notebook_kind/parse_status and
   no topic field (adversary M1). v1 must add operator-supplied topic metadata
   (a validated `discovery_category` + free-text `description`/keywords) via an additive
   v4→v5 migration.
5. **Is crawl4ai in scope?** — No. All 5 scouts rejected it: arXiv rate-limits by IP at
   the network layer, `robots.txt` mandates a 15s crawl-delay and disallows `/search`,
   `/api/`, `/oai2/`, `/e-print/`, and crawl4ai adds a mandatory Playwright/Chromium
   (~300–500 MB) dependency for zero gain. It is on the Won't list.

### Assumptions

- `[MUST]` The arXiv Atom API supports `cat:<category> AND abs:<topic>` +
  `submittedDate:[…]` queries returning structured Atom XML usable for discovery, and the
  existing ≥3s politeness contract (`tools/arxiv_fetch.py`) keeps the operator's IP off
  arXiv's block list. (Scout live-verified 2,176 hits for `cat:math.AG AND abs:Bridgeland
  stability` — but re-confirm under the actual driver.)
- `[MUST]` A notebook's research interest can be captured as operator-supplied metadata
  (validated arXiv `discovery_category` + topic keywords) rich enough to drive a useful
  query, and the v4→v5 SQLite migration is additive and safe.
- `[SHOULD]` Operators prefer propose→confirm over auto-ingest; the candidate-queue can be
  ephemeral (re-run on demand) in v1 rather than persisted in a new table.
- `[SHOULD]` Simple dedup-against-corpus plus the calling agent reading abstracts is
  enough relevance filtering for v1 — no second embedding model (SPECTER2) and no
  pre-ingest scoring needed yet.
- `[MIGHT]` The semantic (Semantic Scholar) and taxonomy (OpenAlex) channels add enough
  precision on pure-math topics to justify their per-channel free-API-key setup burden.
- `[MIGHT]` The Kùzu citation graph is populated enough for the operator's notebooks that
  local citation-neighborhood expansion (CAND-4) returns useful results rather than an
  empty list.

### Objective

Turn arXMCP from a manually-curated paper store into a system-assisted research substrate:
give every notebook a first-class, ToS-clean path to grow its corpus from the operator's
stated topic, using only official arXiv APIs behind a deterministic, human-confirmed,
no-server-LLM flow.

### Key Results

1. From a notebook with a declared topic, an operator can trigger discovery and review
   ≥10 candidate papers (title + abstract) in a single operator-console action, with
   papers already in the notebook deduplicated out (0 duplicates surfaced).
2. Discovery issues requests only to official arXiv API endpoints (0 requests to
   robots.txt-disallowed paths), preserves the ≥3s politeness contract, and `make test`
   stays green (ruff clean, prior passing count preserved).
3. Adding a discovered paper routes through the existing `ingest_one_paper` pipeline into
   the notebook's LanceDB with **no new MCP tool in v1** — `EXPECTED_TOOL_SCHEMA_SHA256`
   and the BP1 prefix are byte-unchanged.
4. All discovery channels are unit-tested with the HTTP layer mocked (no live arXiv/S2/
   OpenAlex calls in CI), following the `graph_ingest.py` monkeypatch pattern.
5. Zero new heavy dependencies: `pyproject.toml` gains no Playwright/Chromium/crawl4ai and
   no browser binary; the v1 arXiv channel adds no pip dependency at all (stdlib HTTP +
   `xml.etree`).

### Won't (explicit out-of-scope)

- **crawl4ai / any browser- or Playwright-based scraping of arXiv** — rejected
  unanimously by the scout; ToS + robots violation, heavyweight dep, zero gain.
- **Server-side LLM relevance scoring** — no `anthropic` SDK at runtime (`CLAUDE.md §4.7`);
  relevance judgment stays with the calling agent.
- **Auto-ingest without operator confirmation** in v1 (propose→confirm only).
- **A full local 2.6M-paper embedding index** (Milvus / Citegeist literal approach) —
  violates the single-workstation constraint.
- **The agent-facing `discover_papers` MCP tool** (CAND-9) — deferred to v2; it forces an
  `EXPECTED_TOOL_SCHEMA_SHA256` re-pin + a permanent BP1 cold-start cache bust that must be
  batched with other tool additions.
- **New arXiv categories** beyond the four targets (`math.AG`, `math.NT`, `math-ph`,
  `hep-th`).
- **Mathlib4 / LeanSearch theorem discovery** (CAND-13) — a verification-tooling milestone,
  not paper discovery.
- **Daily arXiv RSS consumer** (CAND-14) — subsumed by the Atom API + the existing OAI-PMH
  delta loop.

---

## Phase 2 — Decompose

<!-- populated by DECOMPOSE phase -->

### Technique

**Vertical slicing + enabler stories.** The feature is a thin orchestration over existing
arXMCP machinery; one enabler epic establishes the shared substrate (topic metadata +
reusable arXiv-API library), then each value epic adds one discovery axis end-to-end
(operator action → candidates → confirmed ingest). This keeps every value epic demoable to
a non-engineer and lets the highest-confidence channel (arXiv Atom) ship before the
API-key-gated channels.

### Epics

#### notebook-paper-discovery-e1 — Notebooks carry a machine-readable topic, and arXiv search is a reusable library

- **Type:** enabler
- **Specialist suggestion:** `security-reviewer` — see `.claude/skills/roadmap/references/specialist-contracts.md` (the reusable arXiv-API module is network egress + the new `discovery_category` is tool/operator input that must be validated against the four allowed categories)
- **Outcome:** A notebook stores a validated `discovery_category` + free-text topic
  `description`/keywords (additive v4→v5 SQLite migration), and `tools/_arxiv_api.py`
  exposes `build_query_url(category, abs_keywords, ti_keywords, start, max_results)` +
  `fetch_candidates()` + `parse_atom_feed()` as a reusable, politeness-injected library
  (with pagination), with `curate_seed.py` rewired as a thin wrapper. Also ships a 1–2 page
  "notebook discovery model" note under `.claude/notes/` committing the field schema +
  propose→confirm model + channel-dedup boundary (CC-4).
- **Estimated size:** S
- **INVEST check:** I clean, N clean, V borderline (pure enabler — no operator-visible
  behavior alone; justified as the substrate for e2–e4), E clean, S clean, T clean
- **Dependencies:** none
- **Won't conflict check:** none

#### notebook-paper-discovery-e2 — An operator discovers and adds topic-relevant new arXiv papers from the console

- **Type:** value
- **Specialist suggestion:** `security-reviewer` — see `.claude/skills/roadmap/references/specialist-contracts.md` (arXiv API egress, dedup against the junction table, and the propose→confirm route are new loopback input/output paths)
- **Outcome:** From a notebook with a declared topic, the operator clicks "Discover" in the
  console and reviews ≥10 deduplicated candidate papers (title + abstract) returned by the
  arXiv Atom channel (`cat:<category> AND abs:<keywords>` + `submittedDate`); clicking "Add"
  routes the paper through the existing `ingest_one_paper` pipeline into the notebook's
  LanceDB. No new MCP tool; `EXPECTED_TOOL_SCHEMA_SHA256` unchanged.
- **Estimated size:** M
- **INVEST check:** I borderline (depends on e1's library + topic field), N clean, V clean
  (the demoable feature), E clean, S clean, T clean (KR-1/KR-2/KR-3 are the test)
- **Dependencies:** notebook-paper-discovery-e1
- **Won't conflict check:** none (deterministic, LLM-free, propose→confirm, official API only)

#### notebook-paper-discovery-e3 — Semantic and taxonomy discovery channels widen recall

- **Type:** value
- **Specialist suggestion:** `security-reviewer` — see `.claude/skills/roadmap/references/specialist-contracts.md` (two new external egress targets + free-API-key handling with graceful degradation when unset)
- **Outcome:** The Discover panel can additionally query Semantic Scholar Recommendations
  (positive-seed, SPECTER2 similarity; CAND-2) and OpenAlex Topics (taxonomy; CAND-3);
  results from all channels are merged and deduplicated **after** aggregation (CC-3) before
  the operator reviews them. Each channel degrades gracefully (log + skip) when its API key
  is absent, and the cumulative key setup is documented in `docs/install.md`.
- **Estimated size:** M
- **INVEST check:** I borderline (depends on e1 library pattern + e2 panel), N clean,
  V clean, E clean, S clean, T clean
- **Dependencies:** notebook-paper-discovery-e1, notebook-paper-discovery-e2
- **Won't conflict check:** none — note CAND-3 must NOT claim to close the
  `graph_ingest.py --category` stub (challenger MAJOR-2); it is a parallel module

#### notebook-paper-discovery-e4 — Citation-neighborhood expansion surfaces lineage papers with zero discovery-API egress

- **Type:** value
- **Specialist suggestion:** `determinism-reviewer` — see `.claude/skills/roadmap/references/specialist-contracts.md` (combines `cite_neighbors` graph traversal + BGE-M3 similarity scoring; ranking must be deterministic, and the `paper_id → chunk_id` bridge + empty-graph diagnostic must be explicit)
- **Outcome:** From a notebook's existing papers, the operator gets ranked un-ingested
  candidates discovered by walking the Kùzu citation graph and scoring neighbors by BGE-M3
  similarity to the notebook (CAND-4) — respecting the operator's existing curation, with
  no keyword/semantic discovery-API call for the traversal itself. Emits a clear "graph not
  populated — run `python -m ingest.graph_ingest`" diagnostic instead of a silent empty list.
- **Estimated size:** M
- **INVEST check:** I borderline (depends on e1; gated by a `[MIGHT]` graph-coverage
  assumption → spike in SEQUENCE), N clean, V clean, E borderline (out-of-corpus neighbor
  abstract resolution adds OpenAlex calls — CC-5), S clean, T clean
- **Dependencies:** notebook-paper-discovery-e1; SEQUENCE spike on Kùzu graph coverage
- **Won't conflict check:** none — calls the `cite_neighbors` **library** directly, not the
  stubbed MCP handler (`CLAUDE.md §7`)

---

## Phase 3 — Sequence

<!-- populated by SEQUENCE phase -->

### MoSCoW assignment

`score-moscow.py` → **OK: Must = 40.0% (≤ 60% cap)** (total 10pm; must 4 / should 3 / could 3).

- **Must** (≤ 60% of total effort): `notebook-paper-discovery-e1` (S), `notebook-paper-discovery-e2` (M) — the v1 discovery core (topic metadata + reusable arXiv library + arXiv Atom channel + propose→confirm console panel).
- **Should**: `notebook-paper-discovery-e3` (M) — Semantic Scholar + OpenAlex channels.
- **Could**: `notebook-paper-discovery-e4` (M) — local citation-neighborhood expansion (gated by the Kùzu-coverage spike).
- **Won't (this cycle):** pre-ingest relevance scoring (CAND-7), OAI-PMH topic-filter hook (CAND-8), agent-facing `discover_papers` MCP tool (CAND-9, forces a BP1 cache bust), Mathlib4 theorem discovery (CAND-13), RSS consumer (CAND-14), and crawl4ai (rejected outright).

### RICE ranking — Musts

| ID | Reach | Impact | Confidence | Effort | Score |
|---|---:|---:|---:|---:|---:|
| notebook-paper-discovery-e1 | 3 | 2.00 | 80% | 1.00 | 4.8 |
| notebook-paper-discovery-e2 | 3 | 3.00 | 90% | 3.00 | 2.7 |

_No `*`: both Musts are evidence-backed (scout live-verified the arXiv query; SCHEMA_VERSION=4 migration pattern is established). e1 outranks e2 and is its hard dependency — correct execution order._

### Now / Next / Later

- **Now** (fully spec'd): `notebook-paper-discovery-e1`, `notebook-paper-discovery-e2` → milestones m1–m4 below.
- **Next** (shaped): `notebook-paper-discovery-e3` (Semantic Scholar + OpenAlex channels; each behind a free-API-key + graceful-degradation decision).
- **Later** (outcome-only): `notebook-paper-discovery-e4` (citation-neighborhood expansion; promote only after `spike-3` confirms Kùzu graph coverage).

### Spike / discovery lane

- `notebook-paper-discovery-spike-1` — Run the real discovery driver against live arXiv: confirm `cat:<cat> AND abs:<kw>` + `submittedDate` returns usable Atom XML and that the ≥3s politeness contract keeps the workstation IP unblocked over a realistic discovery session (≤ 1 day, validates `[MUST]`: arXiv Atom API query shape + no IP-block risk).
- `notebook-paper-discovery-spike-2` — Dry-run the v4→v5 migration on a copy of a real `notebooks.db`: confirm it is additive (no DROP), back-compatible with existing rows, and that the `discovery_category` validation set = {math.AG, math.NT, math-ph, hep-th} is correct (≤ 1 day, validates `[MUST]`: notebook topic-metadata migration is additive/safe).
- `notebook-paper-discovery-spike-3` — Measure Kùzu citation-graph coverage for a representative populated notebook: do its papers have graph nodes, and does `cite_neighbors` return non-empty out-of-corpus neighbors? (≤ 2 days, validates `[MIGHT]` gating e4: graph is populated enough for local expansion to be useful.)

### Milestones — Now lane

<!--
Each Now-lane milestone is its own H3 below. Heading format is
`### <slug>-mN — Title` exactly — milestone-pipeline's init-state.sh
greps for this. Do not change it.
-->

### notebook-paper-discovery-m1 — Notebook topic metadata (schema v4→v5) + discovery-model note

**Description.** Give a notebook a machine-readable research interest. Add an additive
v4→v5 SQLite migration to `server/notebooks_store.py` introducing `discovery_category`
(validated against the four target arXiv categories) and free-text `description`, surface
both in the operator-console create + edit forms, and commit a 1–2 page "notebook discovery
model" note under `.claude/notes/` that fixes the field schema, the propose→confirm model,
and the post-aggregation channel-dedup boundary (CC-4) so later milestones share one model.

**Acceptance criteria.**
- [ ] v4→v5 migration adds `discovery_category TEXT NOT NULL DEFAULT ''` + `description TEXT NOT NULL DEFAULT ''`; existing rows migrate with defaults (no DROP, no data loss).
- [ ] `discovery_category` is validated against `{math.AG, math.NT, math-ph, hep-th}` (empty string allowed) via `if … raise`, not `assert` (`CLAUDE.md §4.7`).
- Given an operator on the notebook create/edit form, When they set a topic area + category, Then both persist and re-render on reload.
- [ ] The new columns are included in the restic backup scope.
- [ ] `.claude/notes/<name>.md` discovery-model note committed (field schema + propose→confirm + dedup boundary), placed per `CLAUDE.md §1`.
- [ ] `make test` green (ruff clean; prior passing count preserved).

**Dependencies.** `notebook-paper-discovery-e1`; informed by `spike-2`.

**Complexity.** S

**Specialist suggestion.** `—` (additive SQLite migration; covered by milestone-pipeline's adversary critic)

### notebook-paper-discovery-m2 — Reusable arXiv Atom API library

**Description.** Extract the arXiv-API functions from `tools/curate_seed.py` into a shared
`tools/_arxiv_api.py` (mirroring `tools/_notebook_common.py`), generalize the query builder
to compose `cat:<category> AND abs:<keywords>` / `ti:<keywords>`, add offset pagination, and
inject the politeness sleep so callers/tests control it. Rewire `curate_seed.py` as a thin
wrapper with no behavior change.

**Acceptance criteria.**
- [ ] `tools/_arxiv_api.py` exposes `build_query_url(category, abs_keywords=None, ti_keywords=None, start=0, max_results=…)`, `fetch_candidates(…, sleep=time.sleep)`, `parse_atom_feed()`.
- [ ] Query builder composes category + `abs:`/`ti:` keyword clauses (the topic-keyword support `curate_seed.py` lacks today — challenger MINOR-1).
- [ ] Pagination loops via `start` + `max_results` (≤ 2000/page) with the ≥3s sleep between pages.
- [ ] `curate_seed.py` is rewired to import from `_arxiv_api.py`; its existing tests pass unchanged.
- [ ] New unit tests mock the HTTP layer (no live arXiv calls in CI), following the `graph_ingest.py` monkeypatch pattern.

**Dependencies.** `notebook-paper-discovery-e1`.

**Complexity.** S

**Specialist suggestion.** `security-reviewer` (network egress + Atom-XML parsing of untrusted input)

### notebook-paper-discovery-m3 — arXiv Atom discovery driver for a notebook

**Description.** Add `tools/discover_for_notebook.py` that, given a notebook slug, reads its
`discovery_category` + keywords, queries `_arxiv_api.py`, deduplicates candidates against the
notebook's `notebook_papers` junction, and returns a ranked candidate list (paper_id, title,
abstract head, submitted date). Deterministic and LLM-free; relevance is left to the operator
and the downstream agent.

**Acceptance criteria.**
- Given a notebook with `discovery_category=math.AG` and keywords "Bridgeland stability", When the driver runs, Then it returns ≥1 candidate and 0 papers already present in `notebook_papers`.
- [ ] Requests hit only official arXiv API endpoints (0 requests to robots.txt-disallowed paths); the ≥3s politeness contract is preserved.
- [ ] Output is deterministic given a fixed mocked API response (stable ordering).
- [ ] Unit tests mock the HTTP layer; no live network calls in CI.

**Dependencies.** `notebook-paper-discovery-m1`, `notebook-paper-discovery-m2`; informed by `spike-1`.

**Complexity.** M

**Specialist suggestion.** `security-reviewer` (egress + dedup against operator data)

### notebook-paper-discovery-m4 — Operator-console "Discover" panel (propose→confirm)

**Description.** Add a loopback `POST /ui/api/notebooks/{slug}/discover` route + a notebook-
detail-page htmx panel that lists discovered candidates (title + abstract) with a per-row
"Add" button (reusing the `_paper_row_html` pattern), wiring "Add" through the existing
`ingest_one_paper` pipeline into the notebook's LanceDB. The candidate queue is ephemeral
(panel labeled "Refresh to re-run discovery") — no new persistence table in v1.

**Acceptance criteria.**
- Given the operator opens a topic'd notebook and clicks "Discover", When the panel loads, Then it shows ≥10 deduplicated candidates with title + abstract, server-rendered.
- Given the operator clicks "Add" on a candidate, When the request completes, Then the paper is ingested into the notebook's LanceDB and recorded in `notebook_papers`.
- [ ] No new MCP tool is added; `EXPECTED_TOOL_SCHEMA_SHA256` and the BP1 prefix are byte-unchanged.
- [ ] The panel is loopback-only, server-rendered Jinja2+htmx, no Node/SPA; ephemeral-queue behavior is documented in the panel and the discovery-model note.
- [ ] `make test` green.

**Dependencies.** `notebook-paper-discovery-m3`.

**Complexity.** M

**Specialist suggestion.** `security-reviewer` (new loopback request/response surface; operator-supplied query reaches an external API)

---

## Phase 4 — Materialize

<!-- populated by MATERIALIZE phase -->

### Validation

- `validate-roadmap.py`: pass
- Must-cap: 40.0% (≤ 60%)
- All Now-lane milestones have AC: yes (m1–m4)
- Slug format valid: yes

### GitHub tickets

Not requested (run the skill with `--github` to bundle epic + story bodies under
`plans/notebook-paper-discovery-tickets/` plus a copy-paste `create-tickets.sh`).

### Next step

First Now-lane milestone: `notebook-paper-discovery-m1`. To execute it end-to-end, run:

    /milestone-pipeline notebook-paper-discovery-m1

This skill will not invoke milestone-pipeline. Cache stays warmer if you start the
milestone-pipeline session within 5 minutes.

Recommended execution order: **m1 → m2 → m3 → m4** (m3 depends on both m1 and m2; m4 depends
on m3). Run `spike-1` and `spike-2` (each ≤ 1 day) alongside or before m2/m1 to discharge the
two `[MUST]` assumptions; run `spike-3` before promoting e4 (citation expansion) out of Later.

---

<!-- end:roadmap -->
