# Phase 4 — PRIORITIZE (main session)

**Purpose:** the main session reads synthesis + challenge and writes the ranked final report at `artifacts/final-report.md` ready to feed `/milestone-pipeline` (per-candidate) or `/roadmap` (multi-candidate program).  Runs in the main session so the user can review and iterate.

## Inputs

- `.claude/notes/frontend-uplifts/{ID}/artifacts/synthesis.md`
- `.claude/notes/frontend-uplifts/{ID}/artifacts/challenge.md`

## Output

`.claude/notes/frontend-uplifts/{ID}/artifacts/final-report.md`

## Ranking method — RICE-light (adapted for visual / UX)

Each candidate scored on:

| Variable | Scale | Source |
|---|---|---|
| **Reach** (R) | 1 / 3 / 10 | 1 = single route; 3 = handful of routes; 10 = platform-wide (every page benefits). |
| **Visual-Impact** (I) | 0.5 / 1 / 3 | 0.5 = polish; 1 = noticeably nicer; 3 = transformative (operator first-load reaction changes). |
| **Confidence** (C) | 0.3 / 0.5 / 0.8 / 1.0 | Triangulation: 1 brief source → 0.3; 2 → 0.5; 3 → 0.8; 4 → 1.0. |
| **Effort** (E) | 0.25 / 1 / 3 / 8 | T-shirt → person-days: XS=0.25, S=1, M=3, L=8. |

**RICE = R × I × C / E**

Challenger penalty:
- BLOCKER with no redesign → drop the candidate entirely (don't rank).
- BLOCKER with a credible redesign sketch → halve the RICE.
- MAJOR → -25% RICE.
- MINOR or NONE → no adjustment.

**Foundational-candidate bonus:** if synthesis Section 3 flagged a candidate as foundational (other candidates depend on it), add +30% to its RICE.  Reasoning: foundational candidates unlock downstream value; their effort is amortized across all dependents.

## Final report sections

1. **Executive summary** (4–6 sentences) — top-3 candidates by adjusted RICE; main thematic recommendation; honest caveat about scout-run confidence ceiling.

2. **Quick-glance ranking table:**

   | Rank | Cand id | Title | Category | Size | R | I | C | E | Penalty | Adj-RICE | Challenger |
   |---|---|---|---|---|---|---|---|---|---|---|---|
   | 1 | UPL-1 | Add `prefers-reduced-motion` block to `frontend/static/app.css` | Accessibility | XS | 10 | 1 | 1.0 | 0.25 | +30% (foundational) | 52.0 | NONE |
   | 2 | UPL-7 | Stagger-reveal on paper rows in `notebook_detail.html` | Motion | S | 3 | 1 | 0.8 | 1 | (dep on UPL-1) | 2.4 | NONE |
   …

3. **Foundational candidates** (FIRST in detailed section) — these unblock the rest; surface them prominently so the user sees the sequencing implications.

4. **Top-10 in detail** — copy the synthesis catalog entry verbatim; append the challenger findings inline; append the RICE breakdown + adjusted score + rank rationale + DAG dependency note.

5. **Recommended next steps** — 3–5 specific actions:
   - Which 1 foundational candidate should ship first (often `prefers-reduced-motion` adoption or `:focus-visible` adoption, which unblock downstream motion / interaction candidates)?
   - Which 1–2 candidates are ready for `/milestone-pipeline` after the foundation lands?
   - Which 1 candidate should be a `/spike` first (e.g., View Transitions adoption on htmx swaps — needs measured a11y + cross-browser validation)?
   - Which candidates to park for the next uplift run?

6. **Visual evidence index** — table of screenshot paths × candidate ids that use them.  Lets the user click through to see what's being proposed.

7. **Honest limitations** — bullet list:
   - Scouts had a 15-minute budget; some surfaces may be under-explored.
   - Triangulation across 4 briefs is strong but not infallible.
   - Bundle-size + RICE estimates are rough; ±50% accuracy is the realistic ceiling.
   - The challenger evaluated against current arXMCP architectural locks (CLAUDE.md §4.7 no-build-chain, 8-CSS-variable token system, pure-ASGI middleware, CSP `script-src 'self' 'unsafe-inline'`) + WCAG AA; if conventions evolve, BLOCKERs may flip.

8. **Cross-reference index** — table of `UPL-id` → which discover briefs cited it + which screenshots support it.

## Optional handoff offers

The final report includes these footer offers when the top candidates clear sensible thresholds:

```text
## Handoff offers

### Single-candidate handoff (RICE ≥ 5 candidates)

To ship UPL-1 directly via the milestone pipeline:

    /milestone-pipeline frontend-uplift-foundation --brief "$(head -200 .claude/notes/frontend-uplifts/<ID>/artifacts/final-report.md | head -section UPL-1)"

### Multi-candidate program handoff (≥ 3 candidates above RICE 3.0)

To convert this report into a roadmap with milestones:

    /roadmap frontend-uplift-<ID> --brief "$(head -300 .claude/notes/frontend-uplifts/<ID>/artifacts/final-report.md)"

The roadmap skill will refine → decompose → sequence → materialize from this report.

(Note: frontend-uplift NEVER auto-invokes /milestone-pipeline or /roadmap.  Always offer-and-wait.)
```

## After writing

```bash
.claude/scripts/frontend-uplift/checkpoint.py <ID> --set final_report_path='".claude/notes/frontend-uplifts/<ID>/artifacts/final-report.md"'
.claude/scripts/frontend-uplift/checkpoint.py <ID> --set ranked_candidates='[{"id":"UPL-1","title":"Add prefers-reduced-motion block to app.css","rice":52.0,"rank":1}, ...]'
.claude/scripts/frontend-uplift/checkpoint.py <ID> complete
```

Print a 5-line final summary: uplift id, total candidates, top-3 by RICE, BLOCKER count, recommended next step.

## Anti-patterns

| Tempting belief | Reality |
|---|---|
| "Auto-invoke /milestone-pipeline on the top candidate." | NEVER.  Offer-and-wait.  External-write gates are non-negotiable. |
| "Skip the foundational-candidates section — RICE already accounts for it." | NO.  The foundational bonus pushes them to the top, but operators need to SEE the dependency DAG to plan sequencing. |
| "RICE Confidence is 1.0 for every candidate — they all came from 4 briefs." | Triangulation is the C-dial.  4 briefs = 1.0; 3 = 0.8; etc.  Reflect the actual triangulation, not aspiration. |
| "Effort estimates should be calendar-precise." | T-shirts (XS/S/M/L) only at this stage.  Calendar precision lives in `/roadmap` decomposition. |
| "Drop the parking-lot section — it's noise." | Keep it.  Discarded candidates document why arXMCP isn't pursuing X — invaluable when the question recurs. |
| "I'll rank a candidate even if the challenger BLOCKERed it with no redesign." | Don't.  Drop it entirely.  Half-considered BLOCKERs are noise; surface them in the parking lot with the BLOCKER rationale instead. |
