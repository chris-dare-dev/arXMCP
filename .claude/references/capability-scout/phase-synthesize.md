# Phase 2 — SYNTHESIZE (main session)

**Purpose:** the main session reads every survey brief end-to-end and writes a unified opportunity catalog at `artifacts/synthesis.md`.  Sub-agents do NOT synthesize — the main session does, because synthesis requires holding all 5 briefs in working memory simultaneously and judging cross-brief signal.

## Inputs

- `.claude/notes/capability-scouts/{ID}/survey/comparative-brief.md`
- `.claude/notes/capability-scouts/{ID}/survey/research-frontier-brief.md`
- `.claude/notes/capability-scouts/{ID}/survey/oss-trends-brief.md`
- `.claude/notes/capability-scouts/{ID}/survey/multi-agent-brief.md`
- `.claude/notes/capability-scouts/{ID}/survey/adversary-brief.md`

(Subset for `survey_mode=lean`.)

## Output

`.claude/notes/capability-scouts/{ID}/artifacts/synthesis.md`

## Synthesis protocol (read this BEFORE writing)

1. **Read every brief end-to-end first.**  Do NOT start writing synthesis after reading one brief — the value is in cross-referencing.

2. **Build a candidate inventory.**  Every distinct capability proposed across the 5 briefs becomes a candidate row.  Each candidate gets a stable id (`CAND-1`, `CAND-2`, …) ordered by appearance.

3. **Deduplicate.**  When two scouts surface the same capability (e.g. the research-frontier scout flags "execution-feedback retrieval" and the adversary scout flags "no Lean verification surface"), merge them into ONE candidate with BOTH evidence sources cited.

4. **Cross-link evidence.**  Each candidate cites EVERY brief that contributed evidence — that triangulation is the strongest signal for prioritization.

5. **Categorize.**  Use this taxonomy (do not invent new categories):
   - **Retrieval quality** — ranking, reranking, hybrid retrieval, eval-harness changes
   - **Ingestion / parsing** — LaTeXML, theorem-aware chunker, embedder, corpus pipeline
   - **MCP tool surface** — new or changed MCP tools, tool-result envelope, snippet contract
   - **Agent harness** — multi-agent caching, role prefixes, context engineering, orchestrator policy
   - **Citation graph** — Kùzu schema, proof-chains, `cite_neighbors`, intra-paper refs
   - **Verification / proof tooling** — Lean integration, execution-feedback surfaces, autoformalization support
   - **Ops / infra** — observability, security, scale, backup, deployment

6. **Rough-size every candidate.**  T-shirt: XS (<1wk), S (1-2wk), M (3-6wk), L (>6wk).  Don't go finer than t-shirts at this stage; the challenger and Phase 4 prioritization refine.

7. **Don't propose solutions in detail.**  Each candidate gets a 1-paragraph "what it would look like" sketch.  Detailed design happens in `/roadmap` if/when the user pulls it forward.

## Candidate entry shape (use verbatim)

```markdown
### CAND-N — Short imperative title

**Category:** Retrieval quality | Ingestion / parsing | MCP tool surface | Agent harness | Citation graph | Verification / proof tooling | Ops / infra
**Size:** XS | S | M | L
**Evidence triangulation:** N briefs (e.g. "research-frontier ✓, adversary ✓" — count of briefs that surfaced this)

**What it is:** 2-3 sentence plain-English description.

**Why it matters:** 1-2 sentence value-pitch from the perspective of the downstream sketcher → autoformalizer → tactician → fixer pipeline (arXMCP's consumer).

**Sources:**
- Research-frontier scout: <bullet pointing to the capability row in research-frontier-brief.md>
- Adversary scout: <bullet pointing to the gap in adversary-brief.md>
- (or any subset of the 5 briefs)

**Closest arXMCP analog (today):** `server/path/to/file.py:NNN` — what's there now, why it's insufficient.  Or "no analog" when net-new.  Known stubs are documented in `CLAUDE.md §7`.

**Sketch:** 1-paragraph design hint.  Cite specific file:line attach points where credible.  This is enough for the challenger to evaluate feasibility; it is NOT a full implementation plan.

**Open questions:** bullet list, or "none" when the candidate is well-specified.
```

## Synthesis sections (use this order)

1. **Executive summary** — 4-6 sentences: how many candidates, what categories dominate, top theme, top tension across briefs.
2. **Triangulation strength** — count candidates by evidence-source count: "N candidates have 3+ brief sources (strong signal); N have 2; N have 1 (weak — flag for challenger scrutiny)".
3. **Candidate catalog** — every candidate, ordered as: high-triangulation first within each category, then by t-shirt size ascending.
4. **Cross-cutting tensions** — places where briefs disagreed (e.g. "the research-frontier scout favored a heavier reranker; the adversary scout flagged latency budget as a hard MCP-server constraint").  Surface these explicitly — they're the most interesting findings.
5. **What's already in flight** — bullet list of candidates that overlap active epics in `.claude/roadmap/` or in-flight milestones under `.claude/notes/milestones/`.  These are NOT killed — they're flagged so the challenger doesn't re-litigate.
6. **Parking lot** — proposals from the briefs that don't survive synthesis (1-2 sentence rejection reason each).

## After writing

```bash
.claude/scripts/capability-scout/checkpoint.py <ID> --set synthesis_path='".claude/notes/capability-scouts/<ID>/artifacts/synthesis.md"'
.claude/scripts/capability-scout/checkpoint.py <ID> --set candidate_count=<N>
.claude/scripts/capability-scout/checkpoint.py <ID> synthesize-complete
```

## Anti-patterns

| Tempting belief | Reality |
|---|---|
| "I can synthesize without reading every brief — the executive summaries are enough." | The triangulation signal lives in matching specific claims across briefs.  Executive summaries don't carry that signal. |
| "Let me invent new categories." | The taxonomy is fixed for a reason — it makes Phase 4 ranking comparable across scout runs. |
| "Candidates should be ranked here, not in Phase 4." | Synthesis is inventory; ranking is Phase 4.  Don't conflate them — the challenger needs to see all candidates equally weighted. |
| "I'll skip the cross-cutting tensions section." | This is the HIGHEST-VALUE section.  Disagreements between briefs are where novel insights live. |
| "I'll write detailed implementation plans for each candidate." | Phase 4's job, not Phase 2's.  Sketches only.  Detailed plans land in `/roadmap` then `/milestone-pipeline` after the user picks winners. |
