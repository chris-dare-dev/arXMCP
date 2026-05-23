# Phase 4 — PRIORITIZE (main session)

**Purpose:** the main session reads the synthesis + challenge end-to-end and writes a final ranked report at `artifacts/final-report.md` that's ready to feed `/roadmap` as a source brief.  Phase 4 runs in the main session (NOT a sub-agent) because the user reviews the final report directly and may iterate.

## Inputs

- `.claude/notes/capability-scouts/{ID}/artifacts/synthesis.md`
- `.claude/notes/capability-scouts/{ID}/artifacts/challenge.md`

## Output

`.claude/notes/capability-scouts/{ID}/artifacts/final-report.md`

## Ranking method — RICE-light

arXMCP's `roadmap` skill uses RICE for prioritization within a roadmap.  The capability-scout uses a lightweight RICE adapted for capability-discovery (where each variable carries more uncertainty than mid-roadmap):

| Variable | Scale | Source |
|---|---|---|
| **Reach** (R) | 1 / 3 / 10 | 1 = one sub-agent role in the downstream pipeline; 3 = every consuming agent; 10 = changes arXMCP's positioning as a substrate. |
| **Impact** (I) | 0.5 / 1 / 3 | 0.5 = QOL; 1 = parity with comparable retrieval/MCP systems; 3 = decisive advantage / kills a flagged gap. |
| **Confidence** (C) | 0.3 / 0.5 / 0.8 / 1.0 | Triangulation strength: 1 source → 0.3; 2 → 0.5; 3 → 0.8; 4+ → 1.0. |
| **Effort** (E) | 0.25 / 1 / 3 / 8 | T-shirt → person-weeks: XS=0.25, S=1, M=3, L=8. |

**RICE = R × I × C / E**

Drop the candidate's RICE BY HALF when the challenger emitted BLOCKER without a credible redesign.  Drop BY 25% when the challenger emitted MAJOR.  No adjustment for MINOR or NONE.

## Final report sections

1. **Executive summary** (4-6 sentences) — top 3 candidates by RICE; main thematic recommendation; honest caveat about the scout-run's confidence ceiling.

2. **Quick-glance ranking table** — markdown table:

   | Rank | Cand id | Title | Category | Size | R | I | C | E | Adj | RICE | Challenger |
   |---|---|---|---|---|---|---|---|---|---|---|---|
   | 1 | CAND-1 | Lean kernel verification-trace tool | Verification / proof tooling | M | 10 | 3 | 0.8 | 3 | 1.0 | 8.0 | NONE |
   | 2 | CAND-7 | cite_neighbors MCP tool wiring | Citation graph | S | 3 | 1 | 1.0 | 1 | 1.0 | 3.0 | MINOR |
   …

3. **Top 10 in detail** — for each, copy the synthesis catalog entry verbatim, append the challenger's findings inline, append the final RICE breakdown and rank rationale.  This is the section a downstream `/roadmap` invocation reads.

4. **Recommended next steps** — 3-5 specific actions:
   - Which 1-2 candidates should the user feed to `/roadmap` first?
   - Which 1-2 candidates carry an unvalidated assumption — flag them so the `roadmap` skill places them in its Spike lane (one spike per `[MUST]`) rather than going straight to a milestone.
   - Which candidates should the user park for the next scout run?

5. **Honest limitations** — bullet list:
   - Scouts had a 15-minute budget each; some categories may be under-explored.
   - Triangulation across 5 briefs is strong evidence but not infallible.
   - Effort estimates are t-shirts → person-weeks; ±50% accuracy is the realistic ceiling at this stage.
   - The challenger evaluated against current architecture locks; if `CLAUDE.md` conventions evolve, BLOCKERs may flip.

6. **Cross-reference index** — table of `CAND-id` → which survey briefs cited it.  Useful for the user when re-reading sources.

## Optional handoff: feeding to `/roadmap`

The final report includes this footer when ≥3 candidates rank above a threshold (RICE ≥ 3.0):

```text
## Handoff offer

The top-N candidates above are ready to feed the `roadmap` skill as a source brief.  To materialize as a roadmap with milestones:

    /roadmap <new-slug> --brief "$(head -200 .claude/notes/capability-scouts/<ID>/artifacts/final-report.md)"

The roadmap skill will refine → decompose → sequence → materialize from this report, and its milestones (`<slug>-mN`) hand off to `/milestone-pipeline` for execution.

(Note: capability-scout NEVER auto-invokes /roadmap.  Always offer-and-wait.)
```

## After writing

```bash
.claude/scripts/capability-scout/checkpoint.py <ID> --set final_report_path='".claude/notes/capability-scouts/<ID>/artifacts/final-report.md"'
.claude/scripts/capability-scout/checkpoint.py <ID> --set ranked_candidates='[{"id":"CAND-1","title":"Lean kernel verification-trace tool","rice":8.0,"rank":1}, ...]'
.claude/scripts/capability-scout/checkpoint.py <ID> complete
```

Print a 5-line final summary: scout id, total candidates, top-3 by RICE, BLOCKERs, recommended next step.

## Anti-patterns

| Tempting belief | Reality |
|---|---|
| "RICE Confidence is 1.0 for every candidate — we triangulated." | Triangulation is the C-dial.  Use the C-scale.  1.0 is reserved for 4+ brief sources. |
| "Auto-invoke /roadmap on the top candidate." | NO.  Offer-and-wait.  The user picks the cut. |
| "Drop the parking-lot section — it's noise." | Keep it.  Discarded candidates document why the project isn't pursuing X — invaluable when the question recurs in 6 months. |
| "I'll rank a candidate even if the challenger BLOCKERed it." | Allowed, but flag prominently in the executive summary that the top candidate has a BLOCKER objection.  The user needs to know. |
| "Effort estimates should be calendar-precise." | They're t-shirts.  Round to the nearest tier — XS / S / M / L.  Calendar-precision lives in `/roadmap` decomposition. |
