# R2 — claim-graph

Phase 1. Depends on: R1 (identity/spans), evidence-engine FIX (populated eval fixture),
R0 (abstention vocabulary). Blocks: R5 (targets link claims), R6 (proof DAGs), R7 (ablation).

## Brief (seed for /roadmap)

arXMCP has a paper graph, not a claim graph — and "Lemma 3.2 of [14]" is the atomic unit of
mathematical trust that every documented 2026 failure mode turns on (Erdős "solves" that were
literature finds; a solve demoted when prior literature surfaced; this project's own shipped
S²≅[4] error, which a citation-grounded check against LNSZ 1912.04332 Lemma 4.8 kills).
Verified at source: the intra-paper `\ref{}` pass resolves labels to chunks and then discards
the result, emitting one paper→paper self-edge (`ingest/intra_paper_refs.py` — the Kùzu
schema has only paper nodes); `theorem_label` is the TeX label key, not the printed number;
equations carry `parent_chunk_id = None` (`ingest/extract_equations.py`); and there is no
representation of a claim's standing assumptions or of which category/theory a symbol lives
in — the S_X-vs-S_Ku conflation that produced the article's error is invisible to a flat
hypothesis list, because no hypothesis was dropped: a symbol was silently retyped. This
initiative builds claim IR v1 and precision-first resolution: work/revision/block/claim/
citation-occurrence tables with dual identity (a stable Stacks-style claim tag that survives
edits + the immutable revision hash); printed-number extraction with cross-version alias
maps; bibliography→work resolution over the paper-metadata store + S2/OpenAlex; cross-paper
claim-edge resolution that preserves the literal citing text, method, confidence, and
candidates — with calibrated abstention as a first-class outcome; scoped explicit
assumptions (`effective_hypotheses` with provenance and review state, LemmaBench-style
candidate completion clearly flagged as inferred); typed symbol/theory context v1 (symbols
bound to their ambient category, with restriction/induction/transport edges — OMDoc/MMT as
design prior art at notebook scale, sized to catch exactly the ambient-vs-subcategory
functor trap); and equation→block attachment. Expose `resolve_reference`, `get_claim`,
`get_claim_context`, and `explain_edge`; batch schema changes into agent-platform's W1
window. TheoremGraph's hosted graph (68.1% combined precision, single-LLM-judged alignments,
CC-BY-NC-SA) is the adapter/baseline to compare against (R7), not a source of truth: arXMCP's
tier is precision-first, evidence-carrying, revision-pinned, abstaining. Extraction volume
routes through local-llm with Claude-gated acceptance sampling per the delegation policy;
resolution itself stays deterministic-first.

## HMW / Objective

- **HMW:** How might we make every load-bearing claim in the notebook a first-class,
  revision-pinned, context-carrying object — resolvable from citing text with evidence and
  calibrated abstention — so agents and audits stop working at paragraph grain?
- **Objective:** Ship claim IR v1 + deterministic-first resolution + scoped assumptions +
  typed context v1, measured against an expert-reviewed reference suite at ≥98% precision
  with honest abstention.

## Key results

1. New IR tables (LanceDB/SQLite per existing patterns; graph edges in Kùzu v3 schema):
   `blocks` (statement/proof/definition/example, with R1 spans), `claims` (stable tag +
   revision hash + printed number + label + kind), `citation_occurrences` (citing block,
   literal text span, target work candidate(s)), `claim_edges` (cites/invokes/defines/
   restates/specializes/corrects, each with method ∈ {deterministic, heuristic, llm},
   confidence, evidence span, review state).
2. `resolve_reference(citing_occurrence)` returns exactly one of: resolved claim (with
   evidence), ranked candidate set (with why-ambiguous), or abstention (with what's
   missing) — never a silent best guess. Explicit-reference precision ≥98% on the expert
   suite; known-negative fixtures (citations to papers not in corpus; ambiguous numbering;
   arXiv-vs-journal renumbering) return non-resolution outcomes 100% of the time.
3. `get_claim_context(claim)` returns: statement (with truncation status), scoped
   explicit assumptions (each with source span + `stated|inherited|inferred` provenance +
   review state), the macro environment (existing definitions lane, renamed honestly), and
   typed symbol bindings (symbol → theory/category node, with any restriction/transport
   edges).
4. The typed-context fixture: on the Enriques article + LNSZ pair, the system represents
   S_X and S_Ku as distinct typed entities with distinct domains, and a query for "S² = ?"
   returns both bindings with their theories — the machine-visible version of the
   conflation that produced the shipped error. This is an acceptance test, not a demo.
5. Intra-paper `\ref{}` edges land at claim grain (superseding the self-edge), and the
   evidence-engine auto-benchmark mines the new occurrence table instead of re-scanning
   HTML.
6. Equations attach to blocks (`parent_block_id`), enabling R6's equation spine.
7. The 50-query retrieval fixture (merged with evidence-engine FIX) includes ≥10
   claim-resolution queries and ≥5 negatives; `make eval` produces its first numbers
   before any R2 tool ships (ordering gate).
8. Every response carries source evidence (R1 revision + span) — no bare answers.

## Scope — out (wont)

- **No semantic entailment/cite-checking verdicts.** The server composes evidence pairs
  (citing use + resolved statement + hypothesis/type diffs); judging support/conflict is
  the calling agent's job. (Hard limit: complete semantic cite-checking is impossible in
  general; the server must not pretend otherwise.)
- No cross-paper *semantic* similarity edges (that is retrieval, already served).
- No proof DAGs (R6), no formal alignment (R5), no external candidate-graph ingestion
  (R7 adapters).
- No full MMT/OMDoc stack — typed context v1 is: theory nodes, symbol bindings, four edge
  types (defines / restricts-to / induced-by / transported-along), scoped to the
  bridgeland-stability notebook.

## Assumptions (tiered)

- **must** — FIX lands (owner labeling) before R2's tools ship; the fixture is the
  precision gate's substrate. *Validation:* decomposition confirms the evidence-engine FIX
  milestone is scheduled; if it stalls, R2 m1–m2 (IR + extraction) may proceed but m4
  (tool exposure) blocks.
- **must** — Printed-number + author-set matching resolves ≥80% of explicit numbered
  citations in the notebook deterministically (before any LLM assist). *Validation:* the
  m2 spike measures on a 100-citation hand-audited sample; below 80%, add bibliography
  string-matching signals before considering LLM resolution, and re-measure.
- **should** — Standing-assumption extraction ("Throughout, X is …") yields usable
  candidates via local-llm at notebook scale with ≤10% false-attachment after Claude
  gating. *Validation:* 50-sample audit with owner adjudication; worse than 10% demotes
  assumptions to `inferred`-only display until improved.
- **should** — Kùzu 0.11.3 (pinned, archived upstream) tolerates the schema v3 node/edge
  additions the way the v2 migration did. *Validation:* dry-run against a snapshot copy;
  fallback is a rebuild, which the checkpointed ingest passes already support.
- **might** — S2 citation contexts (planned in retrieval-unlocks) arrive in time to serve
  as corroborating evidence on cross-paper edges. *Validation:* treat as enrichment, not
  dependency.

## Evidence (verified 2026-07-11)

- `ingest/intra_paper_refs.py` docstring items 3–4: label→chunk validation exists; result
  collapsed to ONE self-edge; "chunk-level dep info comes from inspecting the chunk HTML
  directly".
- `ingest/chunker.py:406-418`; `ingest/extract_equations.py` ("parent_chunk_id = None at
  v1"); `ingest/kuzudb_schema.py` (papers + cites only).
- TheoremGraph (arXiv:2606.25363; api.theoremsearch.com): resolution tractable at arXiv
  scale; 98.8% deterministic-parser precision vs 42.7% notation-derived — the census
  argument for deterministic-first + abstention.
- LemmaBench (arXiv:2602.24173): assumption-completion prior art; adopt as candidate
  generator only.
- The article's §8 aside + LNSZ 1912.04332: the acceptance fixture pair.
- Erdős #281 demotion; Gemini Erdős paper (arXiv:2601.22401) naming literature-ID +
  "subconscious plagiarism" as core gaps: the demand side.

## Milestone sketch

1. **m1 — claim IR schema + migration** (M): tables, dual identity, Kùzu v3, golden
   fixtures from 5 hand-annotated papers.
2. **m2 — deterministic resolution** (L): printed numbers, alias maps across versions,
   bibliography→work via metadata store + S2/OpenAlex, intra-paper upgrade to claim grain,
   the 100-citation audit, calibration of confidence + abstention.
3. **m3 — scoped assumptions + typed context v1** (L): extraction passes (local-llm +
   gate), theory/symbol tables, the four edge types, the S_X/S_Ku fixture.
4. **m4 — tool surface** (M): `resolve_reference` / `get_claim` / `get_claim_context` /
   `explain_edge`; W1 batch; docs; eval numbers published to the regression ledger.

## Gates

- **Entry:** R1 exit gate green; FIX populated.
- **Exit:** ≥98% precision on explicit references; 100% abstention on known negatives;
  calibration report (confidence vs accuracy) committed; the typed-context fixture passes;
  every response evidence-carrying. If precision cannot reach 98% on some citation class,
  that class ships as candidates-only, permanently labeled.
