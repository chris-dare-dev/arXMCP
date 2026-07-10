# Phase 4 — PRIORITIZE (main session)

**Purpose:** the main session reads synthesis + challenge and writes the ranked final report at `artifacts/final-report.md` ready to feed `/milestone-pipeline` (per-candidate) or `/roadmap` (multi-candidate program).  Runs in the main session so the user can review and iterate.

## Inputs

- `.claude/notes/frontend-uplifts/{ID}/artifacts/synthesis.md`
- `.claude/notes/frontend-uplifts/{ID}/artifacts/challenge.md`

## Output

`.claude/notes/frontend-uplifts/{ID}/artifacts/final-report.md`

## Step 1 — Assign portfolio lanes (BEFORE any RICE)

Cross-lane RICE ranking mathematically buries structural design under XS polish (a `+30%`-bonused
`prefers-reduced-motion` tweak out-scores a transformative direction move every time). So **assign every
candidate to exactly ONE lane first**, and compute RICE **only WITHIN a lane**:

| Lane | Order | What lands here |
|---|---|---|
| **`a11y-safety-debt`** | **1st — MANDATORY, never ranked away** | WCAG AA gaps, reduced-motion/focus/aria debt, CSP-surface risk, autoescape/security-audit items (`chris-dare-dev/arXMCP#9`). Listed first even when its RICE is low — safety debt is not out-competed by polish. |
| **`signature-direction`** | 2nd | the art-direction frame's `[DIRECTION-DEFINING]` moves — what makes the console recognizably arXMCP (overlay §9), not a template. |
| **`foundations`** | 3rd | token / CSS-architecture work other candidates depend on (extend `app.css:4-19` tokens, structural refactors). |
| **`workflow`** | 4th | operator-workflow improvements on the dense surfaces (index table, notebook_detail actions, ingest/preview flow). |
| **`polish`** | 5th | cosmetic paper-cuts with no structural or a11y stakes. |

A run whose only populated lanes are `foundations` + `polish` (nothing in `signature-direction`) is a
directionless run — say so in the executive summary.

## Step 2 — Ranking method — RICE-light, computed WITHIN each lane

Each candidate scored on (rank candidates only against others in the SAME lane):

| Variable | Scale | Source |
|---|---|---|
| **Reach** (R) | 1 / 3 / 10 | 1 = single route; 3 = handful of routes; 10 = platform-wide (every page benefits). |
| **Visual-Impact** (I) | 0.5 / 1 / 3 | 0.5 = polish; 1 = noticeably nicer; 3 = transformative (operator first-load reaction changes). |
| **Confidence** (C) | 0.3 / 0.5 / 0.8 / 1.0 | Triangulation: 1 brief source → 0.3; 2 → 0.5; 3 → 0.8; 4+ → 1.0 (standard mode now runs 5 scouts). |
| **Effort** (E) | 0.25 / 1 / 3 / 8 | T-shirt → person-days: XS=0.25, S=1, M=3, L=8. |

**RICE = R × I × C / E**

Challenger penalty:
- BLOCKER with no redesign → drop the candidate entirely (don't rank).
- BLOCKER with a credible redesign sketch → halve the RICE.
- MAJOR → -25% RICE.
- MINOR or NONE → no adjustment.

**Foundational-candidate bonus:** if synthesis Section 3 flagged a candidate as foundational (other candidates depend on it), add +30% to its RICE.  Reasoning: foundational candidates unlock downstream value; their effort is amortized across all dependents.

## Final report sections

1. **Executive summary** (4–6 sentences) — the TOP PICK PER LANE (not a single cross-lane top-3); main thematic recommendation; whether the run is directionless (no `signature-direction` candidates); honest caveat about scout-run confidence ceiling.

2. **Design frame recap** — carry the synthesis's adopted frame forward: visual thesis + chosen direction + active BAN-1..15 list + the surface map (all four arXMCP surfaces S-2, overlay §9). This anchors the whole report; a report without it is a frameless polish list.

3. **Quick-glance ranking table — GROUPED BY LANE**, `a11y-safety-debt` lane first, then `signature-direction`, `foundations`, `workflow`, `polish`. Rank only WITHIN each lane:

   | Lane | Rank | Cand id | Title | Frame tag | Size | R | I | C | E | Penalty | Adj-RICE | Challenger |
   |---|---|---|---|---|---|---|---|---|---|---|---|---|
   | a11y-safety-debt | 1 | UPL-3 | `aria-live` on the ingest-status htmx swap target | — | XS | 10 | 1 | 0.8 | 0.25 | — | 32.0 | NONE |
   | signature-direction | 1 | UPL-8 | Posture-lede recompose of `notebook_detail` top block | [DIRECTION-DEFINING] | M | 3 | 3 | 0.8 | 3 | — | 2.4 | MINOR |
   | polish | 1 | UPL-14 | Hover-color-shift on breadcrumb links | [polish] | XS | 3 | 0.5 | 0.5 | 0.25 | — | 3.0 | NONE |
   …

4. **Lane-by-lane detail** — walk the lanes in order (`a11y-safety-debt` FIRST). Within each lane, for each candidate: copy the synthesis catalog entry verbatim; append the challenger findings inline; append the within-lane RICE breakdown + adjusted score + rank rationale + DAG dependency note.

5. **Recommended next steps** — 3–5 specific actions, a11y-safety-debt FIRST:
   - Which `a11y-safety-debt` item ships first (that lane leads regardless of RICE)? Pick from what is genuinely still missing — reduced-motion / `:focus-visible` / dark-mode / skip-link ALREADY SHIPPED (m1..m5), so look for remaining gaps like `aria-live` on htmx swap targets or `aria-label` on icon-only controls.
   - Which 1 `signature-direction` candidate best realizes the frame, and is it `/milestone-pipeline`-ready or does it need a `/spike` first?
   - Which 1–2 `foundations`/`workflow` candidates are ready for `/milestone-pipeline`?
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
| "Skip the foundational-candidates section — RICE already accounts for it." | NO.  The foundational bonus pushes them up WITHIN their lane, but operators need to SEE the dependency DAG to plan sequencing. |
| "Rank all candidates in one cross-lane RICE table." | NO.  Portfolio lanes first (`a11y-safety-debt` mandatory + first), RICE only WITHIN a lane — else a `+30%`-bonused XS a11y tweak out-scores a transformative `signature-direction` move and structural design is buried. |
| "The run found no `signature-direction` candidate but that's fine — polish is still value." | Flag it.  A run with an empty `signature-direction` lane is directionless — the art-direction frame did not convert to moves; say so in the executive summary rather than presenting polish as the outcome. |
| "RICE Confidence is 1.0 for every candidate — they all came from every brief." | Triangulation is the C-dial.  4+ briefs = 1.0; 3 = 0.8; etc.  Reflect the actual triangulation, not aspiration. |
| "Effort estimates should be calendar-precise." | T-shirts (XS/S/M/L) only at this stage.  Calendar precision lives in `/roadmap` decomposition. |
| "Drop the parking-lot section — it's noise." | Keep it.  Discarded candidates document why arXMCP isn't pursuing X — invaluable when the question recurs. |
| "I'll rank a candidate even if the challenger BLOCKERed it with no redesign." | Don't.  Drop it entirely.  Half-considered BLOCKERs are noise; surface them in the parking lot with the BLOCKER rationale instead. |
