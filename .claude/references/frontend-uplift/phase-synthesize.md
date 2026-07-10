# Phase 2 — SYNTHESIZE (main session)

**Purpose:** the main session reads every discover brief end-to-end + reviews the captured screenshots + writes a unified modernization-candidate catalog at `artifacts/synthesis.md`.

## Inputs

- `.claude/notes/frontend-uplifts/{ID}/discover/art-direction-scout-brief.md` (**the design FRAME — read FIRST**)
- `.claude/notes/frontend-uplifts/{ID}/discover/visual-scout-brief.md`
- `.claude/notes/frontend-uplifts/{ID}/discover/library-scout-brief.md` (standard mode)
- `.claude/notes/frontend-uplifts/{ID}/discover/inspiration-scout-brief.md` (standard mode)
- `.claude/notes/frontend-uplifts/{ID}/discover/current-state-critic-brief.md`
- `.claude/notes/frontend-uplifts/{ID}/screenshots/*.png` (visual evidence)

## Output

`.claude/notes/frontend-uplifts/{ID}/artifacts/synthesis.md`

## Synthesis protocol

0. **ADOPT THE FRAME FIRST (Step 2a.5 — the anti-cookie-cutter open).**  Read the
   `art-direction-scout-brief.md` before anything else and OPEN the synthesis with its design frame
   (visual thesis + chosen/recommended direction + active BAN-1..15 list + surface map) as Section 0.
   Then, as you build the catalog, tag every candidate against the frame: `[DIRECTION-DEFINING]`
   (it realizes the chosen direction), direction-compatible, or `[polish]` (cosmetic, frame-neutral).
   A synthesis that skips the frame and lists only polish is a Phase-3 Axis-11 BLOCKER.  If the
   art-direction-scout failed, build a PROVISIONAL frame from the overlay `arxmcp-design-system.md` §9
   + `frontend-design-language.md` §8, and say so explicitly.
1. **Read every brief end-to-end.**  Hold them all in working memory (the frame brief, the two evidence briefs, and — in standard/deep — the library + inspiration briefs).
2. **Look at the screenshots.**  The visual scout's screenshots are evidence; the synthesizer references them in candidate entries by path.
3. **Build a candidate inventory.**  Every distinct modernization opportunity proposed across the briefs becomes a candidate row (`UPL-1`, `UPL-2`, …) — including the art-direction-scout's direction-defining candidates.  **Do NOT re-catalog SHIPPED work as net-new** (reduced-motion, `:focus-visible`, dark-mode, skip-link, htmx loading states, tabular-nums, View Transitions all landed in `ui-attractive-polish-m1..m5`; verify against the live `app.css`).
4. **Deduplicate.**  Triangulation is the strongest signal.  When two briefs surface the same upgrade (e.g., library-scout cites the View Transitions API + visual-scout cites "fade-on-swap needed on notebook tiles"), merge into ONE candidate with both evidence sources.
5. **Cross-link motion vocabulary.**  Every candidate that involves animation cites a `[MOT-N]` primitive from `.claude/references/frontend-uplift-motion-vocabulary.md` (the flat SYNCED canon) AND names the motion JOB it serves (§0 motion-jobs test: orientation / causality / feedback / continuity — no job, no motion).  On arXMCP the primitive is realized in CSS transitions + htmx swap hooks, never a JS engine.  This is what makes the catalog comparable.
6. **Categorize** with this fixed taxonomy:
   - **Motion** — animation primitives (pure-CSS transitions, View Transitions, scroll-driven timelines, stagger-reveal via inline `--i` index)
   - **Scroll/parallax** — `animation-timeline: scroll()` / `view()` based reveals
   - **Typography** — font, scale, weight, `tabular-nums` for timestamps / counts
   - **Layout** — density, grid, spacing, container queries, responsive breakpoints
   - **Color/theme** — CSS-variable token application, `prefers-color-scheme` adoption, `color-mix()` derivation
   - **Interaction** — hover, `:focus-visible`, command palette, keyboard, native `<dialog>` / `popover`
   - **Data viz** — count display, status badges, skeleton choreography (arXMCP has no charts today)
   - **Vendor-able single-file drop** — adding a new vendored asset under `frontend/static/` (htmx extension, sortable.js, etc.) with license + weight cited
   - **Accessibility** — a11y improvements (`prefers-reduced-motion`, `:focus-visible`, `aria-live` on htmx swaps, `aria-label` on icon-only buttons, skip-link)
   - **Cross-cutting refactor** — design-system rationalization (extend the 8 CSS variables in `frontend/static/app.css`)
7. **T-shirt every candidate.**  XS (<1d), S (1–3d), M (4–10d), L (>10d).
8. **Don't propose solutions in detail.**  1-paragraph sketches; detailed design happens via `/milestone-pipeline` if/when pulled forward.

## Candidate entry shape (use verbatim)

```markdown
### UPL-N — Short imperative title

**Category:** Motion | Scroll/parallax | Typography | Layout | Color/theme | Interaction | Data viz | Vendor-able single-file drop | Accessibility | Cross-cutting refactor
**Size:** XS | S | M | L
**Evidence triangulation:** N briefs (e.g. "visual ✓, library ✓, inspiration ✓" — count of briefs that surfaced this)
**Motion primitives:** [MOT-N name], [MOT-N name] (if applicable)

**What it is:** 2-3 sentence plain-English description of the upgrade.

**Why it matters:** 1-2 sentence value-pitch from the operator's perspective.

**Sources:**
- Visual scout: <bullet pointing to the gap row + screenshot path>
- Library scout: <bullet pointing to the library row>
- Inspiration scout: <bullet pointing to the pattern row + competitor URL>
- Current-state critic: <bullet pointing to the gap row + file:line>

**Closest arXMCP analog today:** `frontend/templates/<file>.html:NNN` or `frontend/static/app.css:NN-MM` — what's there now, why it's insufficient.  Or "no analog" when net-new.

**Screenshot evidence:** `screenshots/<route>-desktop.png` (visual-scout-captured)

**Sketch:** 1-paragraph design hint. Cite specific file:line attach points where credible. Cite the 8 CSS variables to be applied (`--fg`, `--bg`, `--card-bg`, `--border`, `--accent`, `--danger`, `--error-bg`, `--mono`); if a new variable is required, propose adding it to `frontend/static/app.css:4-13`. Cite [MOT-N] primitives composing the upgrade. State the `@media (prefers-reduced-motion: no-preference)` gate explicitly (arXMCP's CSS today has ZERO such blocks). Confirm pure-CSS / vanilla-JS / vendored-single-file only — no npm.

**Open questions:** bullet list, or "none" when well-specified.
```

## Synthesis sections

**Section 0 — Design frame (adopted).** OPEN the document with the art-direction-scout's frame: visual thesis + chosen/recommended direction + active BAN-1..15 list + surface map (all four arXMCP surfaces are S-2 — overlay §9). Note "PROVISIONAL frame (art-direction-scout unavailable)" if you had to build it from overlay §9 + canon §8. Everything below is placed against this frame.

1. **Executive summary** — 4–6 sentences: how many candidates, dominant categories, top theme, top tension across briefs, AND whether the top candidates are `[DIRECTION-DEFINING]` or `[polish]` (a top-5 that is all `[polish]` must say so plainly).
2. **Triangulation strength** — count candidates by evidence-source count: "N candidates have 3+ brief sources (strong); N have 2; N have 1 (weak — flag for challenger scrutiny)".
3. **Foundational candidates** — surface FIRST: candidates other candidates depend on (e.g., "add a `@media (prefers-reduced-motion: no-preference)` block to `frontend/static/app.css`" foundation enables every animation candidate; "add `:focus-visible` styling" foundation enables every interactive-affordance candidate). Synthesis MUST flag these as foundational so Phase 4 sequences them correctly.
4. **Candidate catalog** — every candidate, ordered by:  foundational candidates first; then high-triangulation within each category; then by t-shirt size ascending.
5. **Cross-cutting tensions** — places where briefs disagreed (e.g., "inspiration-scout proposed dense Distill-style margin annotations; current-state-critic flagged the operator console as a workflow surface that should stay scannable; resolution: defer dense-annotation pattern to a future help surface").
6. **Already considered + rejected** — bullet list of candidates from the briefs that don't survive synthesis (1-2 sentence rejection reason each).
7. **Motion-vocabulary index** — table mapping each `[MOT-N]` primitive cited across candidates to the candidate ids using it.

## After writing

```bash
.claude/scripts/frontend-uplift/checkpoint.py <ID> --set synthesis_path='".claude/notes/frontend-uplifts/<ID>/artifacts/synthesis.md"'
.claude/scripts/frontend-uplift/checkpoint.py <ID> --set candidate_count=<N>
.claude/scripts/frontend-uplift/checkpoint.py <ID> synthesize-complete
```

## Anti-patterns

| Tempting belief | Reality |
|---|---|
| "I can synthesize without looking at the screenshots." | Visual evidence anchors visual claims.  Screenshots are 30% of the brief's value. |
| "Let me invent new categories." | Fixed taxonomy keeps Phase 4 ranking comparable across runs. |
| "Candidates with 1 brief source are still strong if they sound good." | Single-source candidates ARE weaker signal.  Flag for challenger scrutiny — don't filter them out, but rank them with eyes open. |
| "I'll write detailed implementation plans for each candidate." | Phase 4's job, not Phase 2's.  Sketches only. |
| "Skip the foundational-candidates surface — Phase 4 will figure out dependencies." | NO.  Foundational candidates change the sequencing math; surface them prominently in Section 3 so Phase 4 can RICE-rank with the right DAG context. |
