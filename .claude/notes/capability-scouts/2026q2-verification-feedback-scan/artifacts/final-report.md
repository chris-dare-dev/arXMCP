# Final Report — Capability Scout `2026q2-verification-feedback-scan`

**Phase 4 deliverable** — the user-facing artifact. Ready to feed `/roadmap`.
**Date:** 2026-05-22
**Pipeline:** Survey (5 scouts) → Synthesize (14 candidates) → Challenge (1 BLOCKER / 4 MAJOR / 5 MINOR / 4 NONE) → Prioritize.

---

## 1. Executive summary

The scout asked: *what should arXMCP build next to give its sketcher → autoformalizer → tactician → fixer pipeline execution-based verification feedback, and to close the citation-graph tool gap?* Five independent scouts converged with unusual force, and the RICE-light ranking gives a clear top three:

1. **CAND-2 — Wire the `cite_neighbors` MCP handler** (RICE **30.0**) — the single best move in the catalog. The library shipped and is tested; only a ~40-line MCP boundary is missing. Small effort, large unblock.
2. **CAND-1 — Add the `lean_verify` Lean-kernel verification-trace tool** (RICE **10.0**) — the flagship capability. All 5 scouts named it #1; it converts arXMCP from a retrieval substrate into a full agent-harness component.
3. **CAND-5 — Add a `search_mathlib` premise/declaration search tool** (RICE **10.0**) — gives the tactician formal-library grounding alongside informal arXiv retrieval.

The thematic recommendation: **ship CAND-2 first as a fast confidence-builder, then CAND-1 as the headline epic.** Both were the user's original seed ideas — the scout did not just confirm them, it quantified them and showed CAND-2 is the higher-RICE move precisely because the hard work is already done.

**Honest caveat:** this is a 15-minute-per-scout reconnaissance, not a design review. Effort estimates are t-shirts (±50%). The challenger found the catalog systematically under-specifies dependency edges and undercounts the `EXPECTED_TOOL_SCHEMA_SHA256` re-pin tax — both are corrected in §4. And one structural fact dominates sequencing: **CAND-14 (eval-fixture curation) gates measurable evaluation of five other candidates** despite a middling RICE — treat it as a prerequisite, not a peer.

---

## 2. Quick-glance ranking table

RICE = R × I × C / E. C by triangulation (1 src→0.3, 2→0.5, 3→0.8, 4+→1.0). E by t-shirt (XS=0.25, S=1, M=3, L=8). Adj: BLOCKER un-redesigned ×0.5; MAJOR ×0.75.

| Rank | Cand | Title | Category | Size | R | I | C | E | Adj | RICE | Challenger |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | CAND-2 | Wire `cite_neighbors` MCP handler | Citation graph | S | 10 | 3 | 1.0 | 1 | — | **30.0** | MINOR |
| 2 | CAND-1 | `lean_verify` kernel verification-trace tool | Verification/proof | M | 10 | 3 | 1.0 | 3 | — | **10.0** | MINOR |
| 3 | CAND-5 | `search_mathlib` premise/declaration tool | Retrieval quality | M | 10 | 3 | 1.0 | 3 | — | **10.0** | MINOR |
| 4 | CAND-8 | `get_paper` metadata table | Ingestion/parsing | M | 10 | 3 | 0.5 | 3 | — | **5.0** | MINOR |
| 5 | CAND-14 | Curate the 20-query eval fixture | Ops/infra | S | 10 | 1 | 0.5 | 1 | — | **5.0** | NONE |
| 6 | CAND-3 | Migrate Kùzu to maintained fork | Citation graph | XS | 3 | 1 | 0.5 | 0.25 | ×0.5 | **3.0** | BLOCKER |
| 7 | CAND-7 | Complete dual-column proof-chunk RRF | Retrieval quality | S | 10 | 1 | 0.3 | 1 | — | **3.0** | MINOR |
| 8 | CAND-6 | Proof-state-conditioned retrieval | Retrieval quality | M | 10 | 1 | 0.8 | 3 | ×0.75 | **2.0** | MAJOR |
| 9 | CAND-4 | Syntax-check + incremental `lean_verify` modes | Verification/proof | M | 10 | 1 | 0.5 | 3 | ×0.75 | **1.25** | MAJOR |
| 10 | CAND-12 | MCP progress notifications | MCP tool surface | S | 3 | 0.5 | 0.5 | 1 | — | **0.75** | NONE |
| 11 | CAND-13 | Paper version-awareness + version-diff | Ingestion/parsing | M | 3 | 1 | 0.5 | 3 | — | 0.50 | MINOR |
| 12 | CAND-11 | `retrieval_confidence` sufficiency signal | MCP tool surface | S | 3 | 0.5 | 0.3 | 1 | ×0.75 | 0.34 | MAJOR |
| 13 | CAND-9 | GNN re-ranking over Kùzu edges | Retrieval quality | L | 3 | 1 | 0.3 | 8 | — | 0.11 | NONE |
| 14 | CAND-10 | LanceDB native FTS tokenizer migration | Ingestion/parsing | M | 1 | 0.5 | 0.3 | 3 | — | 0.05 | NONE |

---

## 3. Top 10 in detail

Full candidate entries (sources, sketches, open questions) are in `synthesis.md`; full objections in `challenge.md`. This section pairs each with its challenger verdict and RICE rationale.

### Rank 1 — CAND-2 — Wire the `cite_neighbors` MCP handler (RICE 30.0)
**What/why:** Replace the v1 stub in `server/handlers/citations.py` with a real call to the shipped, tested `server/graph_queries.py::cite_neighbors`. Unblocks the entire proof-chain workflow. The library passed `tests/test_proof_chain.py` in E09_S03; only the MCP boundary is missing.
**Challenger (MINOR):** (a) decide the direction-enum question *before* coding — recommended path is re-align the handler enum to the library's `cites/cited_by/depends_on` and re-pin the schema hash (a silent mapping layer is a documentation foot-gun); (b) `cite_neighbors` cache entries **must** include a `graph_version` key component or a graph re-ingest serves stale neighbors — this is a correctness requirement, not an optimization.
**RICE rationale:** R=10 (every consuming agent), I=3 (kills a CLAUDE.md §7 flagged gap, unblocks a whole workflow), C=1.0 (4 briefs), E=1 (S — library done). Highest RICE in the catalog by 3× — small effort against a large, certain payoff.

### Rank 2 — CAND-1 — `lean_verify` kernel verification-trace tool (RICE 10.0)
**What/why:** New MCP tool returning structured Lean 4 kernel output (errors+positions, proof state, remaining goals, `sorry` locations) via a managed local Lean REPL subprocess. Converts arXMCP from a retrieval substrate into a harness component. Honors — does not violate — the "Lean kernel is the better critic" philosophy: it is a thin kernel wrapper, not an LLM critic.
**Challenger (MINOR):** (a) start the subprocess inside the async `lifespan`, conditionally on `ARXMCP_ENABLE_LEAN`, to avoid a cold-start race; (b) produce a one-page Lean-sandbox security sub-design modeled on E13_S03's LaTeXML sandbox (timeout, filesystem isolation, memory cap) as research-phase pre-work.
**RICE rationale:** R=10, I=3 (the decisive capability gap), C=1.0 (5 briefs — maximum), E=3 (M). This is the natural "v2 design document" that un-parks E14_S06's Tier-7 deferral.

### Rank 3 — CAND-5 — `search_mathlib` premise/declaration tool (RICE 10.0)
**What/why:** New MCP tool retrieving Lean 4 Mathlib declarations by NL query, backed by a pre-built offline index — gives the tactician/autoformalizer formal-library grounding (today `find_lemma_by_name` only searches the arXiv corpus).
**Challenger (MINOR):** (a) **v1 = semantic mode only** (NL→declaration via offline index); the Loogle-style type-directed mode needs a Lean elaborator — split it to a CAND-5b gated on CAND-1; (b) confirm a pre-built Mathlib declaration index is downloadable — if arXMCP must generate it from a 2–4 GB mathlib4 build, upsize M→L; (c) `search_mathlib` rows are declarations, not arXiv chunks — define a *new* frozen result-row schema; the 150-char snippet contract does not apply.
**RICE rationale:** R=10, I=3, C=1.0 (4 briefs), E=3 (M, contingent on a downloadable index). Scope-expansion decision required — see §4.

### Rank 4 — CAND-8 — `get_paper` metadata table (RICE 5.0)
**What/why:** Populate a Kùzu `papers` table at ingest so `get_paper` returns real authors/title/abstract/year/categories instead of `null`. Becomes acutely needed once CAND-2 lands (agents call `get_paper` on every citation neighbor).
**Challenger (MINOR):** v1 uses already-fetched OpenAlex/INSPIRE-HEP data — **no new outbound calls**; explicitly exclude the S2 TLDR field (local-first). Description change re-pins the shared `tools/list` hash.
**RICE rationale:** R=10, I=3 (flagged §7 gap), C=0.5 (2 briefs), E=3 (M).

### Rank 5 — CAND-14 — Curate the 20-query eval fixture (RICE 5.0)
**What/why:** Hand-label `tests/eval/fixtures/queries.json` so `make eval` and the nDCG@5 gate can actually fire. Pure execution against an existing runbook (`.claude/docs/eval-curation.md`).
**Challenger (NONE):** clean — requires math-domain judgement (owner-led or owner-reviewed).
**RICE rationale:** R=10, I=1, C=0.5, E=1. **Sequencing-critical regardless of RICE** — it is the quality gate for CAND-6, 7, 9, 10, 15. Schedule it first or in parallel; no retrieval-behavior candidate should reach implementation without it in flight.

### Rank 6 — CAND-3 — Migrate Kùzu to the Vela-Engineering fork (RICE 3.0, post-BLOCKER halve)
**What/why:** Re-pin from archived `kuzu==0.11.3` to a maintained MIT fork — de-risks the citation-graph foundation under CAND-2.
**Challenger (BLOCKER → redesign, not kill):** a `git+https://` pin is a live Threat-6 supply-chain surface contradicting E13's posture. **Redesign:** first confirm the fork is on PyPI with a pinnable semver tag — if yes, the pin becomes `kuzu==0.11.x`, the BLOCKER collapses to MINOR, and RICE roughly doubles to ~6.0. If PyPI cannot be confirmed, do **not** execute — document the migration path in `E14` and keep `0.11.3`.
**RICE rationale:** R=3 (enabler), I=1 (continuity, not advantage), C=0.5, E=0.25 (XS); ×0.5 BLOCKER adjustment. Conditional — see next steps.

### Rank 7 — CAND-7 — Complete the dual-column proof-chunk RRF (RICE 3.0)
**What/why:** Index `embedding_proof` in the ANN path and fuse via the existing `rrf.py` — completes the hybrid retrieval E07 was designed for. The column is already populated.
**Challenger (MINOR):** soft-depends on CAND-14 (no nDCG@5 before/after measurement without it); resolve the `E07_S04`-marked-SHIPPED vs tool-description-contradicts roadmap inconsistency as a `chore(notes)` pre-step.
**RICE rationale:** R=10, I=1 (completes intended feature), C=0.3 (1 brief — weak signal), E=1 (S).

### Rank 8 — CAND-6 — Proof-state-conditioned retrieval (RICE 2.0)
**What/why:** Retrieval keyed on a serialized Lean proof goal rather than an NL query (ReProver pattern). A precision improvement, not a new capability.
**Challenger (MAJOR):** **hard-depends on CAND-1** (near-zero standalone value — no proof state exists without `lean_verify`); add a Lean-goal BM25-tokenizer regression fixture as pre-work; the new `server/router.py` route tag needs a BP2 cache-discipline review.
**RICE rationale:** R=10, I=1, C=0.8 (3 briefs), E=3; ×0.75 MAJOR. Schedule strictly after CAND-1.

### Rank 9 — CAND-4 — Syntax-check + incremental `lean_verify` modes (RICE 1.25)
**What/why:** Cheaper sub-modes on the CAND-1 tool — `syntax_only` (sketch validation) and `incremental` (per-tactic checkpoints).
**Challenger (MAJOR):** **split it** — CAND-4a (`syntax_only`) folds into CAND-1's v1 schema at ~zero extra cost, ship it *with* CAND-1; CAND-4b (`incremental`) is genuinely M-sized (needs a session-scoped REPL subprocess pool) and depends on CAND-1 shipping first.
**RICE rationale:** R=10, I=1, C=0.5, E=3; ×0.75 MAJOR. The low RICE is an artifact of blending two sub-candidates — CAND-4a is effectively free value; CAND-4b is the costly part.

### Rank 10 — CAND-12 — MCP progress notifications (RICE 0.75)
**What/why:** Emit `report_progress()` during long calls (`lean_verify` 5–30 s). Pairs with CAND-1.
**Challenger (NONE):** clean — but a structural refactor (every handler signature gains `ctx`); benefit is zero if the client ignores notifications. Sequence it *with* CAND-1 rather than standalone.
**RICE rationale:** R=3, I=0.5 (QOL), C=0.5, E=1.

*(Ranks 11–14 — CAND-13 version-diff, CAND-11 `retrieval_confidence`, CAND-9 GNN re-ranking, CAND-10 LanceDB FTS — are v2-backlog: low RICE, and CAND-9/CAND-10 are correctly deferred by the synthesis itself. CAND-9 carries a "re-evaluate when corpus > 500 papers" trigger; the citation graph is too sparse for GNN training signal at the 50-paper seed scale.)*

---

## 4. Recommended next steps

**Feed to `/roadmap` first (the headline epic):**
- **CAND-2, then CAND-1.** Bundle them into one roadmap slug — e.g. `/roadmap verification-feedback`. CAND-2 is a fast S-sized win that delivers the proof-chain workflow and builds confidence; CAND-1 is the M-sized flagship. Pull **CAND-4a (`syntax_only` mode)** into CAND-1's v1 schema and **CAND-12 (progress notifications)** into CAND-1's milestone — both are cheapest done alongside it. CAND-1 should explicitly be written up as the "v2 design document" that un-parks `E14_S06`.

**Sequence early regardless of rank:**
- **CAND-14 (eval fixture).** Owner-led curation. It gates measurable evaluation of CAND-6/7/9/10. Start it in parallel with CAND-2 so it is ready before any retrieval-behavior candidate reaches implementation.

**Validate before scheduling (Spike-lane candidates — flag these for the roadmap skill's Spike lane, one spike per unproven assumption):**
- **CAND-3** — spike: *is `Vela-Engineering/kuzu` on PyPI with a pinnable semver tag?* If yes → MINOR, schedule it; if no → document-and-defer, keep `0.11.3`. Do not schedule the migration until this spike resolves.
- **CAND-5** — spike: *is a pre-built Mathlib4 declaration index downloadable, or must arXMCP generate it from a full mathlib4 build?* The answer swings the effort M↔L. Also a genuine scope decision: does arXMCP host a second (formal) corpus? Resolve before roadmap decomposition.
- **CAND-1** — spike (lightweight): *raw `leanprover-community/repl` JSON vs the LeanDojo Python API as the subprocess backend* — affects handler LOC and dependency weight.

**Park for the next scout run / v2 backlog:**
- CAND-13, CAND-11, CAND-9, CAND-10 — low RICE; revisit CAND-9 when the corpus exceeds ~500 papers, CAND-15 (Matryoshka, not in the top 10) when cache-lookup latency becomes measurable at scale.
- The `server/prompts.py` SYSTEM_PROMPT placeholder (adversary L1) — a latent dependency for any candidate that adds an agent-facing signal (CAND-6, CAND-11). Track it as a doc/orchestrator task.

**Cross-cutting build discipline (from the challenger):**
- Schedule no more than one open milestone touching `server/tools.py` at a time — every tool add/modify re-pins the shared `EXPECTED_TOOL_SCHEMA_SHA256` and parallel work risks hash conflicts.
- Apply the E13 Threat-6 supply-chain checklist to every new dependency (CAND-3's fork, CAND-1's Lean toolchain, CAND-5's Mathlib index).

---

## 5. Honest limitations

- Each scout had a ~15-minute budget; some source classes (zbMATH, Elicit, several journals) were access-blocked and under-explored.
- Triangulation across 5 briefs is strong evidence but not infallible — CAND-7, CAND-9, CAND-10, CAND-11 rest on a single brief each (C=0.3) and warrant extra scrutiny in roadmap refinement.
- Effort estimates are t-shirts → person-weeks; ±50% is the realistic accuracy ceiling. CAND-5's size in particular hinges on an unresolved spike (M vs L).
- The challenger evaluated against current architecture locks (`CLAUDE.md §4.7/§8`); if those conventions evolve, the CAND-3 BLOCKER and other findings may shift.
- RICE-light systematically under-ranks enablers — CAND-14's RICE (5.0) understates its true sequencing importance. Read the ranking together with §4, not alone.
- arXiv IDs cited in the briefs were used as-is from the scouts; a few (e.g. `2605.*`, `2602.*`) carry future-dated YYMM prefixes — treat specific IDs as needing verification at roadmap time.

---

## 6. Cross-reference index

| Candidate | comparative | research-frontier | oss-trends | multi-agent | adversary |
|---|---|---|---|---|---|
| CAND-1 `lean_verify` | C1, C9 | 2.1, 2.4 | 2.1 | C1, C5 | H1 |
| CAND-2 `cite_neighbors` wiring | C3 | — | 2.2/theme | C8 | H2 |
| CAND-3 Kùzu fork | — | — | 2.2 | — | L3 |
| CAND-4 verify sub-modes | — | 2.7 | — | C2 | — |
| CAND-5 `search_mathlib` | C4 | 2.2 | — | C3, C6 | M2 |
| CAND-6 proof-state retrieval | C5 | 2.8/theme | — | C6 | — |
| CAND-7 dual-column RRF | — | — | — | — | M3 |
| CAND-8 `get_paper` metadata | C6 | — | — | — | H3 |
| CAND-9 GNN re-ranking | — | 2.3 | — | — | — |
| CAND-10 LanceDB FTS | — | — | 2.4 | — | — |
| CAND-11 `retrieval_confidence` | — | — | — | C7 | — |
| CAND-12 progress notifications | C8 | — | 2.5 | — | — |
| CAND-13 version-diff | C7 | — | — | — | M4 |
| CAND-14 eval fixture | — | 2.9 | — | — | M1 |

---

## Handoff offer

The top candidates above are ready to feed the `roadmap` skill as a source brief. To materialize as a sequenced roadmap with milestones:

```
/roadmap verification-feedback --brief "$(head -200 .claude/notes/capability-scouts/2026q2-verification-feedback-scan/artifacts/final-report.md)"
```

The roadmap skill will refine → decompose → sequence → materialize from this report; its milestones (`verification-feedback-mN`) then hand off to `/milestone-pipeline` for execution. Recommended roadmap scope: CAND-2 + CAND-1 (with CAND-4a and CAND-12 folded in) as the core, CAND-14 sequenced first, and CAND-3 / CAND-5 placed in the Spike lane pending their validation spikes.

*(capability-scout never auto-invokes `/roadmap` — this is an offer; invoke it when you're ready.)*
