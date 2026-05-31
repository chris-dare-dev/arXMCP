# Challenge — Capability Scout `2026q2-crawl4ai-paper-discovery`

**Challenger role:** Phase 3 adversary  
**Date:** 2026-05-31  
**Synthesis under review:** `.claude/notes/capability-scouts/2026q2-crawl4ai-paper-discovery/artifacts/synthesis.md`  
**Lessons applied:** `.claude/agent-memory/capability-scout-challenger/lessons.md` (prior run: verify [VERIFY] flags inline before assigning severity)

---

## 1. Executive Summary

Zero BLOCKERs. Five MAJORs, four MINORs, five candidates rated NONE or recommended-fold.
The catalog is architecturally sound: every candidate respects the no-fork policy, no `anthropic`
SDK invocation at runtime, and no `BaseHTTPMiddleware`. The dominant cost the synthesis
under-surfaces is **effort mis-sizing**: the synthesis calls CAND-1/2/3/7/10 all "S", but
once dedup-against-corpus, notebook-LanceDB routing, abstract-API call for the propose UI,
OpenAlex arXiv-ID extraction, and test coverage are counted, each is an S–M. The second
pattern is **a hidden dependency chain that risks building on sand**: CAND-9 (agent-facing
MCP tool) depends on CAND-10 (orchestrator), which depends on CAND-1/2/3 (channels), which
depend on CAND-6 (refactor); AND the propose UI (CAND-10/CAND-12) needs paper titles +
abstracts that the API returns during discovery but the current `get_paper` handler cannot
supply from local storage (no `papers` metadata table). The synthesis notes this as "parallel
concern, not a blocker" — the challenger agrees it is not a blocker, but it is a permanent UX
seam: the discover panel can only show what the external API just returned, not what is stored.
Two candidates are recommend-kill: CAND-13 (wrong milestone entirely) and CAND-14 (subsumed).

---

## 2. BLOCKER Findings

_None._

---

## 3. MAJOR Findings

### MAJOR-1 — CAND-2 (Semantic Scholar) effort, API-key burden, and pure-math coverage

**Candidate:** CAND-2 — Add a Semantic Scholar Recommendations discovery channel  
**Severity:** MAJOR  
**Axes violated:** 8 (effort honesty), 5 (local-first / operator setup), 9 (value density for pure math)

**Objections:**

- **Effort under-estimate (axis 8).** The synthesis sizes CAND-2 as S (~80–120 LOC). In
  practice: `ingest/s2_discovery.py` must (a) resolve arXiv IDs to S2 paper IDs (the S2
  Recommendations endpoint takes S2 internal IDs as `positivePaperIds`, NOT arXiv IDs
  natively — `externalIds.ArXiv` is a return field, not an input field; the caller must
  first resolve each paper_id via `GET /graph/v1/paper/arXiv:{id}?fields=paperId`), (b)
  batch those lookups (one request per paper at 1 rps = slow for notebooks of 50+ papers),
  (c) handle the cold-start case where a notebook has <3 seeds (the multi-seed endpoint
  returns thin results below ~3 seeds), (d) deduplicate against the notebook's LanceDB,
  (e) handle 429s and `Retry-After`, and (f) write tests against mocked responses. The
  resolution pass alone doubles the LOC estimate. Realistic size: S–M (same as CAND-4).

- **API key is a new setup step that dents local-first posture (axis 5).** S2 requires a
  free API key via an online registration form. The oss-trends scout correctly flags this.
  This key must be stored somewhere (environment variable, `.env` file), documented in
  `docs/install.md`, and validated at startup — a non-trivial operator-setup burden on top
  of the zero-config posture CAND-1 (arXiv Atom, no auth) provides. The synthesis lists
  this as an "open question" without flagging the implementation cost of key validation +
  graceful degradation when absent.

- **Pure-math coverage is genuinely thinner on S2 (axis 9).** The synthesis mentions this
  as an "open question" but understates it. S2 SPECTER2 training is heavily weighted toward
  CS and biomedical. Pure algebraic geometry (math.AG) and number theory (math.NT) papers
  have partial coverage and lower-quality citation graphs on S2 vs OpenAlex. The comparative
  scout's "335 hits with arXiv IDs" is a weak signal — 335 recommendations for a math.AG
  notebook of 50 papers, from a recent-60-day window, may have significant precision loss
  on pure-math subfields like Bridgeland stability. The synthesis does not surface this risk.

**Suggested scope adjustment:** Gate CAND-2 as a v2 fast-follow after CAND-1 ships.
CAND-1 (arXiv Atom, keyword+category, zero-auth) is strictly more feasible for v1 and
covers the keyword-discovery axis. If S2 is v1 scope, require: (a) arXiv-ID→S2-ID
resolution pass in the size estimate, (b) graceful-degradation path when `S2_API_KEY`
is unset (log + skip, not crash), (c) math-coverage caveat in the UI "Discover" panel
("S2 coverage for pure math may be incomplete"), (d) re-size to S–M.

---

### MAJOR-2 — CAND-3 (OpenAlex Topics) arXiv-ID extraction is harder than sketched + key requirement unverified

**Candidate:** CAND-3 — Add an OpenAlex topic-filtered Works discovery channel  
**Severity:** MAJOR  
**Axes violated:** 8 (effort honesty), 5 (local-first / setup step), 3 (N/A but worth noting the claim needs verification)

**Objections:**

- **arXiv-ID extraction path is fragile (axis 8).** The synthesis sketch says "arXiv ID is
  not a native OpenAlex filter field — requires DOI crosswalk or the
  `host_organization_name:arxiv` location filter + ID extraction." This sentence buries a
  significant problem: the `host_organization_name:arxiv` filter is informal and
  inconsistently applied across OpenAlex records (preprint location data quality varies
  by year and category). The DOI crosswalk path requires `doi` → `arxiv_id` mapping via
  `externalIds` which is not always populated for math papers. In practice, roughly 10–30%
  of pure-math arXiv papers in OpenAlex may lack a clean `ArXiv` external ID or reliable
  location filter match. The implementation must handle partial-hit results gracefully and
  the synthesis does not flag this extraction fallibility.

- **OpenAlex API key requirement (axis 5).** The oss-trends scout flags that OpenAlex began
  requiring a free API key in February 2026. The synthesis acknowledges this as "confirm
  current terms" but does not commit to whether the key is required or merely recommended.
  If required, this is a second new operator-setup step alongside CAND-2's S2 key. The
  existing `ingest/graph_ingest.py` OpenAlex client (`OPENALEX_POLITE_SLEEP_SECONDS`,
  `?mailto=<email>`) was written before the Feb 2026 key requirement; it would need updating
  regardless, but CAND-3 inherits this migration cost without explicitly accounting for it.

- **`NotImplementedError` resolution is not as clean as advertised (axis 8).** The synthesis
  claims CAND-3 "closes" the `--category` `NotImplementedError` in
  `ingest/graph_ingest.py:57-65`. Verified at file: the `NotImplementedError` in
  `graph_ingest.py` is in the `--category` CLI path that does category-bulk discovery
  via OpenAlex Concepts/Topics. CAND-3's sketch creates a NEW `ingest/openalex_discovery.py`
  module rather than filling in the stub at `graph_ingest.py:763-768`. These are
  architecturally different: the stub is about seeding the Kùzu citation graph by category;
  CAND-3 is about discovering papers for a notebook by topic. The synthesis conflates them.
  Closing the actual `NotImplementedError` in `graph_ingest.py` is a separate (smaller)
  task; CAND-3 should not claim it as a deliverable without implementing it.

**Suggested scope adjustment:** (a) Replace the "closes NotImplementedError" claim with
"adds a parallel topic-discovery path; the `--category` stub in `graph_ingest.py` remains
deferred." (b) Mandate a `OPENALEX_API_KEY` env-var validation (similar to
`ARXMCP_CONTACT_EMAIL` enforcement pattern) with graceful degradation. (c) Add an
explicit partial-hit handling requirement: "if `externalIds.ArXiv` is absent, skip the
work record and count it in `DeltaSummary.records_skipped`." (d) Re-size to S–M.

---

### MAJOR-3 — CAND-7 effort and BGE-M3 centroid computation cost at pre-ingest time

**Candidate:** CAND-7 — Pre-ingest candidate relevance scoring  
**Severity:** MAJOR  
**Axes violated:** 8 (effort honesty), 7 (retrieval-quality regression risk if scoring gate is wrong)

**Objections:**

- **BGE-M3 is not "already loaded" at pre-ingest time (axis 8).** The synthesis sketch says
  "prefer BGE-M3 (already loaded) over a second SPECTER2 model download." BGE-M3 is loaded
  inside the MCP server's lifespan (`Resources.startup`). Pre-ingest scoring
  (`ingest/candidate_scorer.py`) runs as a CLI tool or background job — OUTSIDE the server
  process. It would need to load BGE-M3 independently, paying the model-load time (~10–30s
  on cold start) and ~2.5 GB RAM. On a workstation that is also running the server, this
  creates memory pressure. The synthesis does not model this cost.

- **Notebook centroid computation is non-trivial (axis 8).** Computing the BGE-M3 centroid
  for a notebook requires embedding ALL chunks in the notebook's LanceDB table
  (or fetching pre-computed embeddings via a LanceDB scan and averaging). For a 50-paper
  notebook with ~1,000 chunks, this is a 1,000-row LanceDB read + vector average — not
  a large operation, but it couples `ingest/candidate_scorer.py` to the LanceDB reader
  (`server/corpus.py` or `ingest/store.py`). The synthesis describes this as "~S–M" without
  modeling the cross-module coupling or the LanceDB read.

- **Scoring gate risks becoming a relevance bottleneck (axis 7).** A novelty-threshold
  stopping heuristic that halts discovery when "<10% of papers are new" could prematurely
  stop expansion for notebooks whose corpus is thin (e.g., a new notebook with 5 papers
  would have 100% novelty on any random batch, and a full-corpus notebook might halt after
  one batch even though 90% of "not new" papers are category matches, not topic matches).
  The synthesis does not flag the false-positive termination risk for thin notebooks or the
  false-negative (miss real novelty) risk for full-category-corpus notebooks.

**Suggested scope adjustment:** (a) Require a design note clarifying that BGE-M3 is loaded
fresh in the ingest process (not shared with the server). (b) Make novelty-threshold stopping
configurable with a sensible default, and document the thin-notebook edge case. (c) Re-size
to M. (d) Gate CAND-7 as a v2 enhancement; CAND-10 at v1 can do simple dedup-against-corpus
without scoring, and let the calling agent evaluate relevance from the abstract text returned.

---

### MAJOR-4 — CAND-9 adds an MCP tool that triggers a mandatory BP1 cold-start cache bust

**Candidate:** CAND-9 — Agent-facing `discover_papers_for_notebook` MCP tool  
**Severity:** MAJOR  
**Axes violated:** 3 (prompt-cache BP1 discipline), 4 (MCP tool-surface contract), 8 (effort honesty for v2 scope)

**Objections:**

- **BP1 cache bust has cross-agent cost beyond just re-pinning the hash (axis 3).** The
  synthesis correctly notes that adding a new MCP tool "forces an `EXPECTED_TOOL_SCHEMA_SHA256`
  re-pin" and "a BP1 cold-start cache bust." What it understates is that this bust is
  **permanent for all existing Claude agents** that have cached the old BP1 prefix. Every
  downstream agent (sketcher, autoformalizer, tactician, fixer) that has cached the
  `tools/list` response sees a cache miss on the next call — a one-time cost that compounds
  across a 4-agent fan-out. Per `07-multi-agent-caching.md §Property 1`, this must be
  batched with other tool additions to amortize the bust. The synthesis flags this but does
  not state the sequencing constraint explicitly: CAND-9 MUST be batched with any other
  tool additions in flight, not added in isolation.

- **CAND-9 is explicitly v2 in both source briefs (axis 8).** Both the multi-agent scout
  (C6: "Option B, after v1 ships") and the comparative scout list this as a follow-on.
  The synthesis correctly characterizes it as v2 but retains it as a catalog candidate.
  The challenger endorses retaining it in the catalog but flags that any v1 milestone that
  includes CAND-9 is scope-creeping past what the source evidence supports.

- **"Server stays LLM-free" constraint needs explicit enforcement (axis 1).** The proposed
  handler (`server/handlers/discover.py`) would call discovery channel functions that make
  outbound HTTP calls to arXiv, S2, and/or OpenAlex. This is fine — the server already
  calls OpenAlex in `ingest/graph_ingest.py` (at ingest time). But the handler must not
  use any LLM for relevance scoring (architecture lock: `CLAUDE.md §4.7`, no `anthropic`
  SDK at runtime). The synthesis states "the server stays LLM-free" but the implementation
  will need explicit enforcement — the handler must return a deterministic candidate list
  without sampling or calling a model, even if the calling agent uses that list to reason.

- **Snippet contract (axis 4).** If the tool returns paper summaries, they must honor the
  150-char snippet contract (`.claude/docs/snippet-contract.md`). The synthesis does not
  mention this.

**Suggested scope adjustment:** (a) Gate CAND-9 as v2, building only after CAND-10 (v1
operator-trigger path) is shipped and validated. (b) When it ships, batch the
`EXPECTED_TOOL_SCHEMA_SHA256` re-pin with any other pending tool additions. (c) Add
snippet-contract enforcement to the handler spec. (d) Document explicitly that the handler
must not call any LLM (assert replaced with `if ... raise` per §4.7 convention).

---

### MAJOR-5 — CAND-10 propose UI needs paper metadata (titles + abstracts) that local storage cannot supply

**Candidate:** CAND-10 — Notebook discovery orchestrator + operator-console "Discover" panel  
**Severity:** MAJOR  
**Axes violated:** 8 (hidden implementation cost from missing `papers` metadata table), 10 (sequencing dependency on external API response caching)

**Objections:**

- **The propose→confirm UI requires titles + abstracts; the `papers` metadata table does
  not exist (axis 8, axis 10).** The synthesis flags "papers metadata table absent" as "a
  parallel concern, not a blocker." This is partially correct for the discovery flow itself
  (the channels return metadata at discovery time from the API), but it is a permanent
  architectural seam: the "Discover" panel can only show paper metadata that the discovery
  API just returned. If the operator navigates away and returns, or if the server restarts
  between discovery and confirmation, the candidate list is gone — there is no local store
  for "discovered-but-not-yet-confirmed" candidates. The synthesis sketch does not propose
  a persistence layer for the candidate queue, which means the propose→confirm model is
  session-local and does not survive restarts.

- **Candidate queue persistence requires a new SQLite table or ephemeral in-memory state
  (axis 8).** For propose→confirm to work robustly, the orchestrator must either (a) store
  candidates in a new `notebook_discovery_candidates` table (additive SQLite migration,
  v5→v6 if CAND-5 lands first, or v5 if CAND-5 is folded in), or (b) accept that
  candidates are ephemeral and the UI is a single-session flow. Option (b) is simpler but
  must be explicitly documented as a constraint. The synthesis does not resolve this choice.

- **Cron invocation model needs care on Windows (axis 5).** The synthesis references
  E11's "system-cron operational model" for periodic refresh. The project runs on Windows
  (`env: win32`) and Windows Task Scheduler has a different interface from system cron.
  `CLAUDE.md §4.5` notes 29 pre-existing Windows-platform failures; any cron-dependent
  feature must document a Windows alternative (Task Scheduler or `schtasks`).

**Suggested scope adjustment:** (a) Explicitly resolve candidate queue persistence in the
v1 design: choose ephemeral (acceptable if UI state is clearly labeled "Refresh to re-run
discovery") or add a `notebook_discovery_candidates` table. (b) Document cron as a
Linux/macOS feature with a Windows Task Scheduler note. (c) The synthesis already sizes
CAND-10 as S — re-size to S–M to account for queue persistence decision.

---

## 4. MINOR Findings

### MINOR-1 — CAND-1 topic-keyword synthesis skips the `abs:` query syntax needed for real use

**Candidate:** CAND-1 — Add an arXiv Atom API topic-discovery channel  
**Severity:** MINOR  
**Axes violated:** 8 (light effort gap), 10 (depends on CAND-6)

**Objections:**

- **`build_query_url` in `curate_seed.py:68-76` only supports `cat:<category>`, not
  `cat:<category> AND abs:<topic>` queries (axis 8, verified at file).** The existing
  function signature is `build_query_url(category: str, start: int, max_results: int) -> str`
  with the hard-coded query `f"cat:{category}"`. For notebook-scoped topic discovery, the
  caller needs `f"cat:{category} AND abs:{topic_keywords}"` or
  `f"cat:{category} AND ti:{topic_keywords}"`. The refactoring into `tools/_arxiv_api.py`
  (CAND-6) is the right moment to generalize the query parameter — but neither CAND-6 nor
  CAND-1 explicitly lists "add `search_query` parameter" as a deliverable. This is a
  one-liner, but the synthesis should not describe CAND-1 as reusing the existing function
  unchanged.

- **CAND-1 explicitly depends on CAND-6 (axis 10).** The synthesis correctly flags this
  dependency. The challenger reinforces: CAND-1 cannot be shipped without CAND-6.
  Any milestone that includes CAND-1 must scope CAND-6 first.

**Suggested scope adjustment:** Add "generalize `search_query` to accept optional
`abs_keywords: str | None` and `ti_keywords: str | None` parameters" to the CAND-6
refactor deliverable. This keeps CAND-1 an S and avoids a second refactor pass.

---

### MINOR-2 — CAND-4 graph-coverage prerequisite not surfaced (Kùzu graph may be empty)

**Candidate:** CAND-4 — Notebook expansion via local citation-graph + embedding neighborhood  
**Severity:** MINOR  
**Axes violated:** 10 (sequencing dependency on graph ingest having run)

**Objections:**

- **Kùzu citation graph coverage is a prerequisite that the synthesis mentions but doesn't
  quantify (axis 10).** The synthesis notes "depends on graph coverage — neighbors only
  exist for papers already in the Kùzu graph." On a fresh installation, the Kùzu graph
  may be completely empty (graph ingest must have run via `python -m ingest.graph_ingest`).
  For a notebook with 10 papers where none have been resolved through OpenAlex, `cite_neighbors`
  returns zero results — making CAND-4 silently no-op with no user feedback. The implementation
  must detect empty-graph and emit a clear "citation graph not populated — run
  `python -m ingest.graph_ingest` first" message, not a silent empty list.

- **`cite_neighbors` takes a `chunk_id`, not a `paper_id` (verified at `server/graph_queries.py:52-54`).** 
  The synthesis sketch calls `cite_neighbors(direction=cited_by/cites, depth=1–2)` but the
  function signature requires a `chunk_id`. The implementation must map `paper_id` → a
  representative `chunk_id` (via `ingest/identifiers.py::paper_id_from_chunk_id` or a
  LanceDB lookup) before calling the graph function. This is a one-line bridge but must be
  explicitly included in the design.

**Suggested scope adjustment:** Add "emit a clear diagnostic when the Kùzu graph is empty
or when none of the notebook's papers have Kùzu nodes" to the CAND-4 spec. Add the
`paper_id → chunk_id` bridge to the implementation sketch.

---

### MINOR-3 — CAND-5 schema migration needs to commit to one field shape before channels are built

**Candidate:** CAND-5 — Add notebook topic/description metadata field  
**Severity:** MINOR  
**Axes violated:** 10 (shape ambiguity blocks every channel that depends on it)

**Objections:**

- **The "open question" (one free-text `description` vs structured
  `(discovery_category, topic_keywords)`) must be resolved before CAND-1/2/3 are built
  (axis 10).** All three discovery channels use the stored topic to default their query.
  CAND-1 uses `cat:<discovery_category> AND abs:<topic_keywords>`; CAND-3 uses
  `discovery_category` to call the arXiv `cat:` filter; CAND-2 doesn't use the stored
  topic at all (seeds from paper_ids). If v4→v5 migration stores only one `description`
  field, CAND-3 must parse it or require a separate `discovery_category` input every run.
  This is an API design decision that affects three dependent candidates. The synthesis
  surfaces this as an open question; the challenger says it must be closed before CAND-5
  is considered "ready to ship."

- **SCHEMA_VERSION=4 confirmed at `server/notebooks_store.py:75` (verified inline).**
  The v4→v5 migration pattern is established; the mechanic is fine. The gap is only
  in the field-shape choice.

**Suggested scope adjustment:** Resolve the field shape before CAND-5 is milestone-scoped.
Recommended: `description TEXT NOT NULL DEFAULT ''` (free text, displayed in UI) +
`discovery_category TEXT NOT NULL DEFAULT ''` (validated arXiv category, e.g. `math.AG`).
The two fields serve different consumers: `description` is human-readable context;
`discovery_category` is the machine-readable arXiv category filter used by CAND-1/CAND-3.

---

### MINOR-4 — CAND-8 introduces a `run_delta()` parameter that may conflict with existing tests

**Candidate:** CAND-8 — Add a topic-relevance filter hook to the OAI-PMH delta loop  
**Severity:** MINOR  
**Axes violated:** 7 (retrieval-quality risk from accidental filtering of the baseline corpus)

**Objections:**

- **The `relevance_filter` callable parameter could silently drop papers from the baseline
  corpus if misconfigured (axis 7).** `run_delta()` is the production nightly harvest.
  Adding an optional `relevance_filter: Callable[[HarvestedRecord], bool] | None = None`
  is additive; the no-filter path (`None`) is unchanged. But if a misconfigured filter
  (e.g., one that rejects 95% of records) is passed to a scheduled `run_delta()` call,
  the corpus silently stops growing. The DeltaSummary already tracks `records_total` and
  `records_ingested`; the synthesized `records_filtered: int` field is the right regression
  guard, but the caller needs a warning when the filter ratio exceeds some threshold (e.g.,
  >80% filtered is suspicious).

- **`DeltaSummary` does NOT currently have `records_filtered` (verified at
  `ingest/oai_delta.py:187-198`).** The existing fields are: `sets_harvested`,
  `records_total`, `records_deleted`, `records_ingested`, `records_failed`,
  `pages_fetched`, `elapsed_seconds`, `budget_breached`. Adding `records_filtered` is
  additive and correct, but it is an API-surface change that existing tests may type-check
  or snapshot against. Mention this explicitly in the implementation spec.

- **Sequencing: where does the filter live — in the OAI-PMH harvest or in the discovery
  orchestrator (CAND-10)?** The synthesis flags this as an open question. The challenger's
  view: CAND-8 belongs as a v2 refinement after CAND-10 ships. At v1, CAND-10's orchestrator
  can run an arXiv Atom query (CAND-1) and cross-check against the OAI-PMH results post-hoc,
  without modifying the production `run_delta()` signature. CAND-8 is an optimization, not
  a blocker for v1 topic discovery.

**Suggested scope adjustment:** (a) Add a `filter_ratio_warn_threshold=0.8` parameter
to log a warning when `records_filtered / records_total > threshold`. (b) Sequence CAND-8
as a v2 refinement. (c) Update the DeltaSummary type stub in tests explicitly.

---

## 5. Clean Candidates (NONE)

- **CAND-6** — Pure refactor with a clear precedent (`tools/_notebook_common.py`); no
  architecture locks touched; XS size estimate is accurate; no sequencing ambiguity. Survives
  the gauntlet cleanly.

- **CAND-11** — Trivial pagination addition that lives naturally inside the CAND-6 refactor;
  all synthesis claims verified (single-call `fetch_candidates` at `curate_seed.py:128-134`).
  The "needed at notebook scale?" question is real but doesn't block shipping it as part of
  CAND-6; adding `start` + pagination loop costs ~10 LOC and is a net correctness improvement
  for any topic with >2,000 papers. NONE.

- **CAND-12** — Correctly identified as a fold-in of CAND-10, not an independent item. The
  synthesis recommendation (merge into CAND-10) is correct. No separate analysis needed.

---

## 6. Cross-Cutting Concerns

### CC-1 — Four candidates add outbound API egress; each requires a free key or a polite-pool email

CAND-1 (arXiv, no key but polite email), CAND-2 (S2, free key required), CAND-3 (OpenAlex,
key reportedly required since Feb 2026), and CAND-4 (OpenAlex for abstract resolution of
out-of-corpus neighbors). Each new channel is a new operator-setup step. The pattern is
acceptable (arXMCP already calls OpenAlex and arXiv in `ingest/graph_ingest.py` with
`ARXMCP_CONTACT_EMAIL`) but the cumulative setup burden across all channels must be
documented clearly in `docs/install.md`. Any channel whose key is absent must degrade
gracefully (log + skip, never crash the server or the ingest job).

### CC-2 — No candidate explicitly specifies a per-channel test-isolation strategy

All five discovery channels make outbound HTTP calls. All five must be testable without
hitting the live API. The existing pattern (`monkeypatch.setattr` on `_fetch_openalex_work`
in `graph_ingest.py`'s tests) is the right model. No candidate explicitly lists "mock the
HTTP layer in tests" as a deliverable. This is a consistent omission — add it to every
channel's acceptance criteria.

### CC-3 — The propose→confirm UX model is correct but the synthesis does not resolve who owns "paper already ingested" state across channels

When CAND-1, CAND-2, and CAND-3 are all running (via CAND-10's orchestrator), each channel
does its own dedup against the notebook's `notebook_papers` table. Dedup is read-only
(SELECT from junction table) and idempotent, so running three channels in sequence is safe.
But if the orchestrator runs them in parallel (natural temptation for speed), concurrent
reads against SQLite in WAL mode are safe; concurrent proposes of the same paper_id from
two channels are not (one would attempt to INSERT a duplicate). The orchestrator must merge
channel results before proposing — dedup AFTER channel aggregation, not inside each channel.
The synthesis implies this ("dedups") but does not specify where the dedup boundary lives.

### CC-4 — The notebook model is growing capabilities faster than the design constitution tracks

The adversary scout's Theme 3 and the synthesis's Cross-cutting tension #6 both flag this.
The challenger reinforces: CAND-5 (topic field) + CAND-8 (filter hook) + CAND-10
(orchestrator) + future CAND-9 (MCP tool) collectively constitute a "notebook discovery
model" that has no design note. A lightweight "notebook model extension spec" (1–2 pages
under `.claude/notes/` or `.claude/docs/`) that commits the field schema, the discovery
model (propose→confirm), and the channel-priority ordering would prevent three separate
milestones from making incompatible choices. This is a low-cost pre-work for any discovery
milestone.

### CC-5 — CAND-4 is the only zero-API-egress channel but has the highest infrastructure dependency

CAND-4 (citation graph expansion) requires: (1) the Kùzu graph to be populated, (2) the
BGE-M3 model to be loaded (at pre-ingest scoring time if combined with CAND-7), and (3) an
OpenAlex lookup for the abstract of out-of-corpus neighbor papers (new API egress). The
"fully local, zero-external-API" characterization in the synthesis is accurate for the
graph traversal itself but misleading overall: the synthesis sketch adds N OpenAlex calls
for neighbor abstract resolution. CAND-4's zero-API claim should be scoped to the graph
traversal only; abstract resolution is a separate, API-dependent step.

---

## 7. Recommended Kill List

### Kill — CAND-13 (Mathlib4 theorem discovery)

**Recommendation: DROP from this catalog; scope to a verification-tooling milestone.**

The synthesis correctly identifies CAND-13 as "orthogonal to paper discovery" and notes
it "belongs to verification tooling, not discovery." There is no public API for LeanSearch
(confirmed in synthesis). The only brief that surfaced it (comparative) explicitly tagged
it as "different milestone entirely." Retaining it in the catalog adds noise to Phase 4
prioritization. Drop it; track it under a future verification milestone.

### Kill — CAND-14 (Daily arXiv RSS feed consumer)

**Recommendation: DROP from this catalog; subsumed.**

The multi-agent scout explicitly parks it as redundant; the synthesis's own analysis says
"does RSS add anything over Atom-API + OAI-PMH? (Multi-agent scout: no.)" The synthesis
retains it as a "weak-signal/de-prioritization candidate" — but retaining it without a
concrete capability it adds over CAND-1 + OAI-PMH wastes Phase 4 attention. Drop it.

---

## Appendix — Inline file verification results

| Synthesis claim | Verified | Result |
|---|---|---|
| `curate_seed.py:44-110` has `build_query_url`, `fetch_candidates`, `parse_atom_feed` | Yes | Functions at lines 68–110; `build_query_url` only takes `category, start, max_results` (no `abs:` support). Synthesis correctly identifies these but omits the missing topic-keyword parameter. |
| `server/notebooks_store.py` `SCHEMA_VERSION=4` | Yes | Confirmed at line 75. CAND-5's v4→v5 migration is the right mechanic. |
| `ingest/graph_ingest.py:57-65` raises `NotImplementedError` for `--category` | Yes (sort of) | The stub raises via `sys.stderr.write` + implicit `sys.exit`, not a Python `NotImplementedError`. Lines 763-768 confirm the behavior. CAND-3 does NOT close this stub; it creates a parallel module. |
| `server/tools.py::ALL_TOOLS` has 8 tools | Yes | Lines 341-350: SEARCH_PAPERS, GET_CHUNK, FIND_EQUATION, GET_DEFINITIONS, FIND_LEMMA_BY_NAME, GET_PAPER, CITE_NEIGHBORS, LEAN_VERIFY = 8. |
| `server/graph_queries.py::cite_neighbors` is real (not stub) | Yes | Full implementation at `server/graph_queries.py`; async, Kùzu-backed, takes `chunk_id` (not `paper_id`). |
| `ingest/oai_delta.py::DeltaSummary` has no `records_filtered` field | Yes | Confirmed at lines 187-198. Seven fields; `records_filtered` absent. |
| `server/routes/notebooks.py::_paper_row_html` exists | Yes | Line 1097. Returns `<tr>` fragment; slug + paper_id + added_at only (no title/abstract — confirms MAJOR-5 concern). |
| `tools/_notebook_common.py` exists as precedent for shared module pattern | Yes | File exists at project root's tools directory. |
