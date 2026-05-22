# Deferred-work tracker (E14_S06)

**Status:** living document. Owned by the design-constitution agent;
reviewed quarterly aligned with the restic-restore drill cadence
(`docs/ops/daily-ops-cadence.md`). Last review: 2026-05-22.

This file is the single canonical home for work that is **explicitly
out of v1 scope** but that motivates current v1 design decisions.
Items move OUT of this tracker only when their stated un-park trigger
condition is met AND documented. Adding an item here is not a
commitment to build it — it's a commitment to **not lose track of
why we decided not to build it yet**.

The tracker consolidates the former E15 epic (quality-of-life and v2
deferred work) into a single file location per the E14_S06 roadmap
text. It also collects deferred items previously scattered across the
design constitution and individual roadmap files.

---

## Conventions

Every item has three fields:

1. **What it is** — one-paragraph description, including a name a
   future agent can grep for.
2. **Why it was deferred** — the v1 reasoning. Often "no evidence
   yet that the v1 path is the bottleneck."
3. **Un-park trigger** — a *concrete and falsifiable* condition that
   would move this item to active work. "When we have time" is NOT
   an un-park trigger.

Items with no un-park trigger graduate into **explicit non-goals**
(separate section at the end of this document).

---

## Tier 6 candidates (v1.5 / v2 features motivated by v1 design)

### ColBERT-v2 late interaction for theorem-level chunks

- **What it is.** ColBERT-v2 (v1.5 or newer) late-interaction
  retrieval, replacing or supplementing the BGE-M3 single-vector
  dense path on long technical chunks. Late interaction beats
  single-vector dense on long technical content at approximately
  10× storage cost. The LanceDB schema reserved `embedding_colbert`
  in E05_S01 specifically to absorb this without a schema migration.
- **Why deferred.** No evidence yet that the BGE-M3 single-vector
  ANN retrieval is actually the bottleneck. The 200K-paper Tier-5
  corpus + the Tier-1 eval gate (`make eval --ndcg-min=0.80`) are
  the prerequisites for that evidence; both must be in steady state
  before a 10× storage cost is justifiable.
- **Un-park trigger.** Documented evidence from the E11_S04
  retrieval-quality eval that the nDCG@5 gap between BGE-M3 and
  the theoretical ceiling (BM25 oracle re-ranked) is > 0.10.
- **Estimated complexity:** XL.

### TikZ-cd commutative diagram extraction (math.AG-specific)

- **What it is.** TikZ-cd diagrams in math.AG papers carry
  significant semantic content (commutative diagrams are often the
  paper's central object). The chunker would emit `DiagramAtom`
  records with a normalized graph representation (nodes + edges) for
  graph-similarity retrieval, plus a new `find_diagram` MCP tool.
- **Why deferred.** v1 retrieval over the parsed-text path already
  finds diagram-heavy papers via their surrounding theorem text. No
  documented failure case yet where this is insufficient.
- **Un-park trigger.** A documented retrieval-failure case where a
  TikZ-cd-rich paper is the known correct answer for a test query,
  but BM25 + ANN retrieval both miss it (or rank it below k=20).
- **Estimated complexity:** XL.

### Proof-skeleton classifier

- **What it is.** A small fine-tuned classifier (DistilBERT-class)
  that tags theorem chunks with proof-skeleton labels (induction,
  contradiction, spectral sequence, generic functoriality, ...).
  Training data: Mathlib tagged proofs. Would add a
  `proof_skeleton` filter to `search_papers`.
- **Why deferred.** The tactician sub-agent in the v1 pipeline
  hasn't demonstrated a need for proof-pattern filtering — keyword
  + semantic search has been sufficient for the queries we've
  observed.
- **Un-park trigger.** A tactician sub-agent demonstrates
  documented need for "find me proofs that use induction on the
  dimension" (or similar pattern query) and the existing keyword +
  semantic search returns the wrong results.
- **Estimated complexity:** XL.

### Multi-paper deduplication

- **What it is.** Cross-listed papers, withdraw-and-resubmit
  cases, and near-duplicate works on different arXiv IDs create
  redundancy in retrieval results. Detection via pairwise
  chunk-similarity scan over papers with overlapping authors and
  close submission dates; output is a `near_duplicates` field on
  the `papers` table that the search handler can use to collapse
  results.
- **Why deferred.** No measurement yet of how often this actually
  affects top-10 results. The cost of running pairwise
  chunk-similarity over 200K papers is non-trivial.
- **Un-park trigger.** Retrieval evaluations show ≥ 5% of top-10
  result sets contain duplicates of the same work.
- **Estimated complexity:** L.

### ORCID author disambiguation

- **What it is.** ORCID data arrives via INSPIRE / OpenAlex
  enrichment in E09_S05 (when that ships). This item would expose
  `find_papers_by_author(orcid)` and disambiguate the `authors`
  filter in `search_papers`. Also surfaces `withdrawn=true` flags
  more visibly (a `warning: "withdrawn"` field at the top of
  `get_paper` and `search_papers` results).
- **Why deferred.** No documented agent failure caused by
  author-name collision yet. The current search by paper_id or by
  topic is sufficient for the v1 sketcher → autoformalizer
  pipeline.
- **Un-park trigger.** A documented agent failure caused by
  author-name collision where ORCID disambiguation would resolve
  it.
- **Estimated complexity:** M.

### `paper_diff` MCP tool

- **What it is.** A `paper_diff(paper_id_a, paper_id_b)` tool that
  surfaces the structural / semantic differences between two
  papers. Useful for comparing arXiv versions, or for retrieving
  the "minimal differences" between two related theorems.
- **Why deferred.** Per `06-mcp-server-design.md` line 340: deferred
  to Tier 4 explicitly. The v1 7-tool surface is intentionally
  rationalized to avoid tool-block bloat in the prompt (H6 from the
  Phase 3 critique).
- **Un-park trigger.** An agent workflow request that requires
  comparing two specific paper versions, where the
  `get_chunk`/`search_papers` round-trip is demonstrably too
  expensive in tokens.
- **Estimated complexity:** M.

### PDF figure extraction

- **What it is.** Extract image-format figures from PDFs and expose
  them via a `get_figure(paper_id, figure_index)` tool. Math.AG
  often has hand-drawn algebraic varieties; math-ph has data
  plots.
- **Why deferred.** Per `09-feature-priorities.md`: "Tier 6 if at
  all." LaTeX source path provides MathML and TikZ source which
  is far more useful than raster PDF figures. The math content is
  the contract — figures are typically illustration, not the
  thing being reasoned about.
- **Un-park trigger.** A sketcher/autoformalizer sub-agent
  demonstrably needs to see a figure (rather than the surrounding
  text) to make progress on a real query.
- **Estimated complexity:** L (PDF extraction is fiddly; pure
  Python tools are weak on figure-bbox detection).

---

## Tier 7 (v2 deferred — gateway features for the autoformalizer)

### Lean 4 toolchain integration

- **What it is.** LeanDojo bindings exposing Lean's proof state to
  arXMCP, enabling a `lean_kernel_query` pass-through tool. This
  is the gateway feature for the autoformalizer integration and
  the subgoal-decomposition orchestrator agent (DeepSeek-Prover-V2
  pattern).
- **Why deferred.** v2 design decision. The v1 design
  (deterministic chunk IDs, hierarchical retrieval, definitions
  table, `expand_macro` tool, `find_lemma_by_name` tool) was made
  with this in mind, but Lean kernel integration is a v2 scope
  decision, not a v1 add-on.
- **Un-park trigger.** A dedicated v2 design document exists AND
  the autoformalizer integration is the primary development goal.
- **HARD CONSTRAINT:** A `lean_kernel_query` tool is NOT to be
  added to the 7-tool v1 surface without a v2 scope decision.
- **Estimated complexity:** XL.

---

## Tier 5/6 security and operational hardening (deferred)

### mTLS between arXMCP and the orchestrator

- **What it is.** Mutual TLS between the arXMCP server and the
  orchestrator process, replacing the current
  `127.0.0.1`-loopback-only deployment posture.
- **Why deferred.** Single-workstation single-operator deployment
  per CLAUDE.md §4.1. Loopback + Origin pinning + Sec-Fetch-Site
  middleware is sufficient for that threat model.
- **Un-park trigger.** A documented multi-host deployment use case
  (e.g., a Kubernetes deployment where the orchestrator runs in a
  separate pod from arXMCP).
- **Estimated complexity:** M.

### Alertmanager routing for Prometheus alerts

- **What it is.** Wire the Prometheus alerts in
  `infra/prometheus/alerts.yml` to an Alertmanager instance that
  routes to operator email / PagerDuty / Slack. Today the alerts
  fire into a Prometheus UI that no one is watching outside of
  active operation hours.
- **Why deferred.** Single-operator deployment; the operator
  reviews `make ops` output daily and notices anomalies via the
  cadence runbook, not via paged alerts.
- **Un-park trigger.** A multi-operator deployment (i.e., the
  arXMCP server is being run by someone other than its primary
  maintainer) OR an incident where a Prometheus alert fired into
  the void and operator response was delayed > 24h as a result.
- **Estimated complexity:** S.

### API spend budget alerting

- **What it is.** Extend the `arxmcp_api_spend_usd_total` Counter
  (E14_S12) with a budget threshold (e.g., $100/month per provider)
  that triggers a Prometheus alert when exceeded. Tied into the
  Alertmanager routing above.
- **Why deferred.** Today only the Voyage embedder path even has a
  spend wire (and it's a stub), and the Haiku summarizer (E08_S07)
  hasn't shipped. No actual API spend to budget yet.
- **Un-park trigger.** E08_S07 ships AND real Voyage / Anthropic
  spend is occurring AND a single month's spend exceeds a
  user-defined threshold (typically $50).
- **Estimated complexity:** S.

### Server-side KaTeX pre-rendering for the m10 preview route

- **What it is.** During ingest, pre-render the `<math>` blocks in
  ar5iv HTML to KaTeX HTML so the m10 paper-preview route (which
  serves under a tight CSP that blocks MathJax) displays typeset
  math rather than raw LaTeX markup.
- **Why deferred.** Per the m10 research synthesis A6: accepted
  trade-off for v2 m10. Raw LaTeX display is readable enough for
  the preview use case; KaTeX pre-rendering touches the ingest
  pipeline.
- **Un-park trigger.** Operator feedback that the raw-LaTeX
  display is unreadable in practice (not just aesthetically
  unpleasant).
- **Estimated complexity:** M.

---

## Unmet deliverables from prior milestones (cleanup backlog)

### `docs/observability/tracing.md` from E14_S02

- **What it is.** E14_S02 listed `docs/observability/tracing.md`
  as a deliverable, but the file (and parent directory) were
  never created. The E14_S02 `state.json` claims `phase: complete`
  but the deliverable is missing.
- **Surfaced by:** the E14_Tier5plus bundle research — R-1 flagged
  it as a CONFLICT when implementing S11. The S11 commit
  (`docs/observability/langfuse-orchestrator.md`) created the
  directory but did not back-fill the tracing.md content.
- **Un-park trigger.** A specific operator question that the
  `tracing.md` content would have answered, OR a milestone that
  consolidates E14 observability docs.
- **Estimated complexity:** S (extract from existing
  `server/observability/tracing.py` docstrings).

---

## Explicit non-goals (NOT a Tier 6+ list — these will never ship)

These are hard design constraints, not deferrals. They appear here so
no future "Tier 6 backlog grooming" pass mistakes them for parked
work.

### LLM critic tool

- **What it is.** A tool that has another LLM call review/critique
  an LLM-generated answer.
- **Why it's a non-goal.** Per
  `.claude/notes/01-mission-and-context.md`: "the Lean kernel is
  the better critic." The valuable LLM roles in this project live
  UPSTREAM of verification (sketcher → autoformalizer →
  tactician → fixer); adversarial LLM critique of math content is
  structurally wrong here.
- **What would change this:** nothing. This is a project-level
  design decision, not a triage outcome.

### Comments / discussion / blog tracking around papers

- **What it is.** Extracting paper-adjacent commentary (blogs,
  MathOverflow threads, etc.) into the corpus.
- **Why it's a non-goal.** Per `09-feature-priorities.md` Tier 6
  Quality-of-life: "Out of scope." Signal-to-noise too low; the
  retrieval pipeline is optimized for primary-source content (the
  paper itself).
- **What would change this:** nothing.

### OCR of pre-2007 scanned arXiv papers

- **What it is.** Apply OCR to pre-2007 papers whose source isn't
  available as `.tex` (just scanned PDFs).
- **Why it's a non-goal.** Per `09-feature-priorities.md`
  explicitly: "not built." OCR quality on math content is too poor
  for the math-fidelity contract to survive.
- **What would change this:** a documented advance in math-content
  OCR that produces MathML output. None on the horizon as of
  2026-05-22.

### `anthropic` or LLM-provider SDK at runtime inside `server/`

- **What it is.** Importing `anthropic`, `openai`, or any other
  LLM-provider SDK inside `server/` source.
- **Why it's a non-goal.** Per CLAUDE.md §4.7: "No `anthropic` SDK
  at runtime. The server is a tool provider; the LLM lives in the
  calling agent." Architectural separation is load-bearing.
- **What would change this:** a major architectural decision to
  fold the orchestrator into arXMCP. There is no current path to
  that decision.

---

## How to add a new item

When you encounter design pressure for a feature that is genuinely
out of v1 scope:

1. **Add an entry here** with the 3 required fields (what, why
   deferred, un-park trigger). The un-park trigger MUST be
   concrete and falsifiable.
2. **Cross-link** from any code TODOs that motivated the entry
   (e.g., a `# TODO: see deferred-work-tracker.md § ColBERT-v2` in
   `server/retrieval/`).
3. **Don't add to active roadmap files** — those track work that
   has been scoped. This tracker is for work that has NOT been
   scoped.

If you encounter what you think is a deferred-work item but it
turns out to be an EXPLICIT non-goal (above), add it under that
section instead. Confusing the two and then "promoting" a non-goal
to active work is the named anti-pattern this file exists to
prevent.

## Review cadence

Quarterly. Aligned with the restic-restore drill cadence per
`docs/ops/daily-ops-cadence.md`. The reviewer:

1. Re-reads each item's un-park trigger.
2. Checks whether the trigger condition has been met (look at
   eval results, file new issues for triggered items).
3. Updates `LAST_REVIEW` below.

**LAST_REVIEW: 2026-05-22** (E14_Tier5plus initial population)
