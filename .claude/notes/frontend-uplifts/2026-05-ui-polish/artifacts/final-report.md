# Final report — `2026-05-ui-polish`

**Phase:** 4 — Prioritize (main session)
**Date:** 2026-05-30
**Inputs:** synthesis (25 candidates) + challenger (0 BLOCKER / 3 MAJOR / 8 MINOR / 14 NONE) + 4 Phase-1 briefs + 8 screenshots.
**Ranking method:** RICE-light — `RICE = R × I × C / E`, with challenger penalties (MAJOR −25%, MINOR/NONE no adjustment, BLOCKER drop OR halve if redesigned) and a +30% foundational bonus.

---

## 1. Executive summary

Three candidates tie for first place at **RICE 52.0** — **UPL-1
(`prefers-reduced-motion` gate), UPL-2 (`:focus-visible` baseline), and
UPL-3 (`aria-live` on htmx success swap targets)**. All three are
4-brief-triangulated, XS-effort, foundational a11y baselines that
unblock every motion / interaction candidate below them. The
recommended **first ship** is to bundle these three with UPL-4
(skip-to-main-content, RICE 26.0) into a **single "a11y baseline pass"
milestone** — total effort ≈ S, ships pure CSS + 6 attribute additions
+ 1 HTML line, no new vendor weight, no JS, no CSP widening.

The dominant thematic recommendation: **a11y baselines + visual polish
ship via RICE; the visual-scout CRITICAL bug-fixes (UPL-5/6/7) ship
through a parallel `/milestone-pipeline` bug-fix track regardless of
RICE rank.** The bug-fixes RICE-rank low because their Reach is bounded
(single route or single form), but they erode shipped functionality —
fix-anyway, not polish-rank. The challenger's diagnostic concern about
UPL-5 (the JSON-shim may NOT be the root cause of the silent rename
422) is a load-bearing pre-implementation step: **reproduce first,
capture the actual emitted PATCH body, THEN code the fix**.

Honest caveat: this is a 4-brief / 1-challenger discovery run with
~60 minutes of scout time per role; the RICE confidence numbers reflect
brief-triangulation, not field-test confirmation. The visual-scout
single-source CRITICAL findings get C=1.0 by special-case (live-walk
evidence is irrefutable) — note that the challenger's diagnostic
push-back on UPL-5 means the c=1.0 covers "the symptom is real" but
not "the proposed root cause is correct."

---

## 2. Quick-glance ranking table

| Rank | Cand id | Title | Category | Size | R | I | C | E | Penalty | Adj-RICE | Challenger |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 (tie) | UPL-1 | `prefers-reduced-motion` universal gate | A11y (FOUNDATIONAL) | XS | 10 | 1 | 1.0 | 0.25 | +30% | **52.0** | MINOR |
| 1 (tie) | UPL-2 | `:focus-visible` baseline ring | A11y (FOUNDATIONAL) | XS | 10 | 1 | 1.0 | 0.25 | +30% | **52.0** | MINOR |
| 1 (tie) | UPL-3 | `aria-live` on htmx success swap targets | A11y (FOUNDATIONAL) | XS | 10 | 1 | 1.0 | 0.25 | +30% | **52.0** | NONE |
| 4 | UPL-4 | Skip-to-main-content link | A11y (FOUNDATIONAL) | XS | 10 | 0.5 | 1.0 | 0.25 | +30% | **26.0** | NONE |
| 5 (tie) | UPL-10 | `tabular-nums` on timestamps + counts | Typography | XS | 10 | 0.5 | 1.0 | 0.25 | — | **20.0** | NONE |
| 5 (tie) | UPL-19 v0 | Mobile responsiveness — `.table-wrap` | Layout | XS | 10 | 1 | 0.5 | 0.25 | — | **20.0** | MINOR |
| 7 | UPL-8 v0 | `prefers-color-scheme: dark` (8 base tokens) | Color/theme | S | 10 | 1 | 1.0 | 1 | — | **10.0** | MINOR |
| 8 | UPL-11 | `htmx-request` styling on in-flight buttons | Interaction | S | 10 | 1 | 0.8 | 1 | — | **8.0** | MINOR |
| 9 (tie) | UPL-15 | Table-row hover + focus-within | Interaction | XS | 10 | 0.5 | 0.3 | 0.25 | — | **6.0** | NONE |
| 9 (tie) | UPL-22 | Footer badge fixed-width + flash | Layout / Motion | XS | 10 | 0.5 | 0.3 | 0.25 | — | **6.0** | MINOR |
| 9 (tie) | UPL-23 | Footer `·` `aria-hidden` cleanup | A11y | XS | 10 | 0.5 | 0.3 | 0.25 | — | **6.0** | NONE |
| 9 (tie) | UPL-25 | favicon + `/favicon.ico` 403 fix | Layout | XS | 10 | 0.5 | 0.3 | 0.25 | — | **6.0** | NONE |
| 13 | UPL-13 | View Transitions API on htmx swaps | Motion | S | 10 | 1 | 0.5 | 1 | — | **5.0** | MINOR |
| 14 | UPL-9 | `color-mix()` derived shades | Color/theme | XS | 3 | 0.5 | 0.5 | 0.25 | — | **3.0** | NONE |
| 15 | UPL-17 | Richer empty-state cards | Layout | S | 10 | 0.5 | 0.5 | 1 | — | **2.5** | NONE |
| 16 | UPL-7 v0 | HTML-render SecFetchSite rejection (exception handler) | Interaction (BUG) | S–M | 3 | 3 | 1.0 | 3 | −25% | **2.25** | MAJOR |
| 17 (tie) | UPL-18 | Per-route H1 specialization | Typography | XS | 3 | 0.5 | 0.3 | 0.25 | — | **1.8** | NONE |
| 17 (tie) | UPL-24 | Cosmetic CSS micro-polish bundle | Cross-cutting | XS | 3 | 0.5 | 0.3 | 0.25 | — | **1.8** | NONE |
| 19 | UPL-14 | Status-pill discipline extension | Layout | S | 10 | 0.5 | 0.3 | 1 | — | **1.5** | NONE |
| 20 | UPL-6 | HTML-render preview empty-state | Interaction (BUG) | S | 1 | 1 | 1.0 | 1 | — | **1.0** | NONE |
| 21 | UPL-5 v0 | Fix silent rename failure (error-unwrap + CSS revert) | Interaction (BUG) | S–M | 1 | 3 | 1.0 | 3 | −25% | **0.75** | MAJOR |
| 22 | UPL-20 | Disabled-Preview affordance | A11y | XS | 1 | 0.5 | 0.3 | 0.25 | — | **0.6** | NONE |
| 23 (tie) | UPL-16 | Scholarly metadata-strip typing | Typography | S | 3 | 0.5 | 0.3 | 1 | — | **0.45** | NONE |
| 23 (tie) | UPL-21 | Poll backoff + Page Visibility API | Interaction (perf) | S | 3 | 0.5 | 0.3 | 1 | — | **0.45** | MINOR |
| 25 | UPL-12 v0 | Convert `location.reload()` → in-place swap (add-paper only) | Interaction | M | 3 | 1 | 0.5 | 3 | −25% | **0.375** | MAJOR |

**Calibration notes.** Effort sizing applies challenger-recommended v0
splits (UPL-5/7/8/19/12). RICE Confidence uses the synthesis's
triangulation count (4 briefs = 1.0; 3 = 0.8; 2 = 0.5; 1 = 0.3) EXCEPT
UPL-5/6/7 where the visual-scout's live-walk evidence warrants C=1.0
despite single-source.

---

## 3. Foundational candidates (ship FIRST as one milestone)

These four candidates form the load-bearing prerequisite layer — every
motion / interaction candidate below depends on them. RICE bonus of
+30% reflects their unblocking-leverage.

| Cand | Why foundational |
|---|---|
| **UPL-1** (52.0) | Per `motion-vocabulary.md` MOT-NO-5: any motion that lands without this is an automatic Phase-3 BLOCKER. Prerequisite for UPL-11, UPL-13, UPL-15, UPL-17, UPL-22. |
| **UPL-2** (52.0) | WCAG 2.1 AA non-text-contrast baseline. Destructive `<button class="danger">` rows have NO visible keyboard focus today on Safari. Prerequisite for UPL-15. |
| **UPL-3** (52.0) | htmx swap success-path parity with the existing 5 `pre.error[aria-live]` regions. Prerequisite for UPL-5's rendered error and UPL-12's swap-completion announcement. |
| **UPL-4** (26.0) | WCAG SC 2.4.1; cheapest a11y win; unblocks any future nav expansion. |

**Recommended bundle:** ship **UPL-1+2+3+4 as a single milestone** —
total effort ≈ S (XS+XS+XS+XS ≈ 4 worktree-day equivalents), pure CSS
+ 6 attribute additions + 1 HTML line, no new vendor weight, no JS,
no CSP widening, no UI-audit-surface-widening. Suggested milestone
slug: **`ui-a11y-baseline-m1`** (or similar).

---

## 4. Top-10 in detail

Each entry includes the synthesis catalog reference (for full sketch),
the challenger findings inline, RICE breakdown, and DAG dependency
notes.

### Rank 1 (tie) — UPL-1 — `prefers-reduced-motion` universal gate

**RICE:** R=10 × I=1 × C=1.0 / E=0.25 = 40.0; +30% foundational = **52.0**.
**Challenger verdict:** MINOR (add `animation-delay` + `transition-delay`
overrides to the sketch for completeness).
**Sketch:** ~6 lines at the bottom of `frontend/static/app.css` (universal
`*, *::before, *::after { animation-duration: 0.01ms !important; … }`
inside `@media (prefers-reduced-motion: reduce)`).
**Source:** current-state H1, library A1, inspiration CAND-3, visual G6
(all 4 briefs).
**Dependencies:** none. Ships FIRST.
**Rank rationale:** unblocks every motion candidate; XS effort; 4-brief
consensus; no axis risk.

### Rank 1 (tie) — UPL-2 — `:focus-visible` baseline ring

**RICE:** R=10 × I=1 × C=1.0 / E=0.25 = 40.0; +30% foundational = **52.0**.
**Challenger verdict:** MINOR (flip `button.danger:focus-visible` outline-
color to `--danger` instead of `--fg` for louder destructive focus).
**Sketch:** ~8 CSS lines using existing `--accent` token.
**Source:** all 4 briefs.
**Dependencies:** none.
**Rank rationale:** non-negotiable WCAG AA prerequisite; Safari drops
default focus on `<a class="button">`; trivial to ship.

### Rank 1 (tie) — UPL-3 — `aria-live="polite"` on htmx success swap targets

**RICE:** R=10 × I=1 × C=1.0 / E=0.25 = 40.0; +30% foundational = **52.0**.
**Challenger verdict:** NONE.
**Sketch:** 5 attribute additions across `base.html` + `notebook_detail.html`
+ `index.html` (after UPL-12).
**Source:** all 4 briefs.
**Dependencies:** none for the 4 already-shipped swap targets;
`#notebook-list` aria-live waits for UPL-12.
**Rank rationale:** SR parity with the 5 existing `pre.error[aria-live]`
regions; zero code, just attributes.

### Rank 4 — UPL-4 — Skip-to-main-content link

**RICE:** R=10 × I=0.5 × C=1.0 / E=0.25 = 20.0; +30% foundational = **26.0**.
**Challenger verdict:** NONE.
**Sketch:** 1 HTML line + 5 CSS lines.
**Source:** all 4 briefs.
**Dependencies:** none.
**Rank rationale:** cheapest a11y win; ships with the foundational bundle.

### Rank 5 (tie) — UPL-10 — `tabular-nums` on timestamps + counts

**RICE:** R=10 × I=0.5 × C=1.0 / E=0.25 = **20.0**.
**Challenger verdict:** NONE.
**Sketch:** one CSS rule (`time, .status-badge, dl.meta dd, td code { font-variant-numeric: tabular-nums; }`).
**Source:** all 4 briefs.
**Dependencies:** none.
**Rank rationale:** removes visible horizontal jitter on every htmx
poll; one CSS rule.

### Rank 5 (tie) — UPL-19 v0 — Mobile responsiveness baseline (`.table-wrap`)

**RICE:** R=10 × I=1 × C=0.5 / E=0.25 = **20.0**.
**Challenger verdict:** MINOR (descope `body { max-width: min(95vw,
1400px) }` to v1 — keep the 980px ceiling for now, just wrap tables in
`<div class="table-wrap">` with `overflow-x: auto`).
**Sketch (v0):** 1 CSS line + 2 template wrap edits.
**Source:** visual G3 (screenshots) + current-state M5.
**Dependencies:** none.
**Rank rationale:** real mobile-clipping bug; XS effort for v0; visual-
scout's mobile screenshots are evidence.

### Rank 7 — UPL-8 v0 — `prefers-color-scheme: dark` (8 base tokens only)

**RICE:** R=10 × I=1 × C=1.0 / E=1 = **10.0**.
**Challenger verdict:** MINOR (skip the status-pill dark-mode remap for
v0; defer the table-header + freshness color to v1; promote dark-mode
hex literals to named tokens before v1 ships).
**Sketch (v0):** ~12 CSS lines re-declaring the 8 base tokens inside
`@media (prefers-color-scheme: dark) { :root { … } }`. Skip the
status-pill `color-mix()` remap until UPL-9 has landed.
**Source:** all 4 briefs (severity disagreement resolved as MEDIUM-HIGH
per synthesis §5).
**Dependencies:** UPL-9 (`color-mix()`) for v1 status-pill derivations.
v0 ships independently.
**Rank rationale:** white-flash on dark-OS is the most visible
"untouched" signal; v0 ships cheaply.

### Rank 8 — UPL-11 — `htmx-request` styling on in-flight buttons

**RICE:** R=10 × I=1 × C=0.8 / E=1 = **8.0**.
**Challenger verdict:** MINOR (move `opacity / pointer-events /
cursor: wait` OUTSIDE the `prefers-reduced-motion: no-preference`
block — those are signal, not motion; keep `animation: spin` inside
the gate. Add `hx-disabled-elt="this"` to forms for keyboard a11y
parity.).
**Sketch:** ~10 CSS lines (the `htmx-request` opacity-dim + the gated
spinner `::after`).
**Source:** current-state M2 + inspiration CAND-4 + visual G8 (3 briefs).
**Dependencies:** UPL-1 (the spinner animation MUST be reduced-motion-gated).
**Rank rationale:** every htmx-bound button currently has zero in-flight
feedback; UPL-12 actively depends on this landing first per the
challenger's sequencing analysis.

### Rank 9 (tie) — UPL-15 — Table-row hover + focus-within

**RICE:** R=10 × I=0.5 × C=0.3 / E=0.25 = **6.0**.
**Challenger verdict:** NONE.
**Sketch:** 4 CSS lines using `color-mix()` (depends on UPL-9 for
clean derivation).
**Source:** inspiration CAND-10 (1 brief).
**Dependencies:** UPL-1, UPL-2 (focus-within outline pairs with focus-
visible discipline), UPL-9 (color-mix).
**Rank rationale:** cheap scannability win; low triangulation (single-
source) so confidence discount applies.

### Rank 9 (tie) — UPL-22 — Footer badge fixed-width + flash

**RICE:** R=10 × I=0.5 × C=0.3 / E=0.25 = **6.0**.
**Challenger verdict:** MINOR (drop the optional `[MOT-10 breathing-
glow]` for v1 — ambient operator motion is MOT-NO-2 by analogy; force
the dependency edge UPL-9 → UPL-22 since the flash keyframe uses
`color-mix()`).
**Sketch:** ~6 CSS lines (`.status-badge { min-width: 14ch; }` plus
`.htmx-settling` flash keyframe).
**Source:** visual G7 + current-state M4 (1 brief explicit).
**Dependencies:** UPL-1, UPL-9.
**Rank rationale:** stabilizes the footer's most-watched element; small.

### Rank 9 (tie) — UPL-23 — Footer `·` `aria-hidden` cleanup

**RICE:** R=10 × I=0.5 × C=0.3 / E=0.25 = **6.0**.
**Challenger verdict:** NONE.
**Sketch:** 5 spans, `aria-hidden="true"`.
**Source:** current-state L4 (1 brief).
**Dependencies:** none.
**Rank rationale:** SR noise removal; trivial.

### Rank 9 (tie) — UPL-25 — favicon + `/favicon.ico` 403 fix

**RICE:** R=10 × I=0.5 × C=0.3 / E=0.25 = **6.0**.
**Challenger verdict:** NONE.
**Sketch:** add `<link rel="icon" href="/ui/static/favicon.svg">` in
`base.html` + a trivial SVG.
**Source:** visual G14 (1 brief).
**Dependencies:** none.
**Rank rationale:** silences devtools noise; ships with the UI security
audit's "Continue" landing page (UPL-7's sibling) since both eliminate
SecFetchSite log noise.

---

## 5. Recommended next steps

The Phase-4 recommendation organizes the 25 candidates into **4
sequential milestone tracks** plus **one parallel bug-fix track** plus
**two spike candidates**:

### Track A — Foundational a11y pass (NEXT — ship first)

**Milestone slug suggestion:** `ui-a11y-baseline-m1`
**Candidates:** UPL-1 + UPL-2 + UPL-3 + UPL-4 (bundled)
**Effort:** ~S (XS×4 bundled).
**RICE total:** 52+52+52+26 = 182.
**Risk:** very low. Pure CSS, 1 HTML line, 5 attribute additions, no
JS, no CSP impact, no UI-audit-surface-widening.
**Why first:** every other motion / interaction candidate depends on
these. Ships the most-leverage-per-LOC in the catalog.

```
/milestone-pipeline ui-a11y-baseline-m1 --brief "Adopt the 4 foundational
a11y baselines from frontend-uplift 2026-05-ui-polish UPL-1..4:
prefers-reduced-motion universal gate, :focus-visible baseline ring on
button/.button/a/input/select/textarea/[tabindex], aria-live=polite on
the htmx success swap targets (#display-name-block, #ingest-status,
#papers-tbody, #status-badge with aria-atomic=true), and skip-to-main-
content link. All in frontend/static/app.css + base.html + minor
attribute additions on notebook_detail.html. Pure CSS; no new vendored
asset; no UI-audit-surface widening. See
.claude/notes/frontend-uplifts/2026-05-ui-polish/artifacts/final-report.md
§4 for the per-candidate details and § Top-10 for the sketches."
```

### Track B — Visible polish pass (after Track A)

**Milestone slug suggestion:** `ui-visible-polish-m2`
**Candidates:** UPL-10 (tabular-nums) + UPL-19 v0 (`.table-wrap`) +
UPL-9 (`color-mix()`) + UPL-25 (favicon) + UPL-23 (footer `·`
aria-hidden).
**Effort:** ~S (5 × XS bundled).
**RICE total:** 20+20+3+6+6 = 55.
**Risk:** very low. All pure CSS / 1 static asset.
**Why second:** delivers immediately-visible quality-of-life wins
(no horizontal jitter, no mobile overflow, no favicon 403). UPL-9
preconditions Track C.

### Track C — Dark mode + htmx-request pass (after Track B)

**Milestone slug suggestion:** `ui-dark-and-htmx-feedback-m3`
**Candidates:** UPL-8 v0 (dark-mode 8 base tokens) + UPL-11 (htmx-
request styling).
**Effort:** S+S ≈ M total.
**RICE total:** 10+8 = 18.
**Risk:** low. Both pure CSS; UPL-11 needs `hx-disabled-elt` attribute
additions on htmx forms.
**Why third:** dark mode is the most visible "this is a 2026 tool"
upgrade; htmx-request styling is the prerequisite for UPL-12 (in-place
swaps) which is more substantial. Both depend on UPL-1.

### Track D — In-place swaps + View Transitions (after Track C)

**Milestone slug suggestion:** `ui-htmx-in-place-swaps-m4`
**Candidates:** UPL-12 (location.reload() → in-place swaps, v0 = add-
paper flow only) + UPL-13 (View Transitions API) + UPL-22 (footer
badge flash).
**Effort:** M+S+XS ≈ M+ total.
**RICE total:** 0.375+5.0+6.0 = 11.4 (UPL-12 RICE undersells the
operator-felt impact — the full-page flash on every successful create
is the single most-noticed UX defect).
**Risk:** MAJOR per challenger — widens the open UI security audit
(`chris-dare-dev/arXMCP#9`) by introducing 3 new server-side fragment
endpoints. v0 narrows to add-paper-only to minimize this.
**Spike first:** UPL-13's `htmx.swap()` re-entry signature against
vendored htmx 2.0.10 — wrong call shape silently breaks every htmx
interaction.

### Track E — Bug-fix parallel track (any time; not RICE-blocked)

**Milestone slug suggestions:** `ui-rename-422-fix-bm1`, `ui-preview-empty-bm2`, `ui-secfetch-html-bm3`
**Candidates:** UPL-5 + UPL-6 + UPL-7. Each its own `/milestone-pipeline`.
**Effort:** M each (post-challenger redesign).
**Risk:** UPL-5 / UPL-7 widen the UI security audit; the challenger
suggests UPL-7 use a FastAPI exception handler instead of middleware
content-negotiation to minimize audit coordination.
**Why parallel:** these are bugs on shipped UI, not polish. RICE ranks
them low only because the routes touched are bounded — the trust-
erosion impact is high. The challenger noted UPL-5's diagnostic may be
wrong; **reproduce-first** before coding.

**For UPL-5 specifically — the challenger's diagnostic objection is
load-bearing.** Do this before any code change:
```
# In a worktree with the server up:
1. open /ui/notebooks/bridgeland-stability in Chrome
2. open DevTools → Network → "Preserve log"
3. type a new display_name + click Rename
4. capture the exact JSON body in the PATCH request payload
5. compare to NotebookRename's Pydantic model
6. if shapes match — the 422 origin is elsewhere; investigate the
   validator chain. if shapes differ — fix the JSON-shim.
```

### Operator-surface polish (opportunistic; bundle 2-3 at a time)

UPL-14, UPL-15, UPL-16, UPL-17, UPL-18, UPL-20, UPL-21, UPL-24 — all
NONE or MINOR severity, mostly XS effort, none load-bearing. Ship as
fill-in milestones when a Track A–E milestone has slack.

### Spike candidates

- **Spike-1:** verify htmx 2.0.10's `htmx.swap()` re-entry signature for
  UPL-13's View Transitions integration. Without this, UPL-13 silently
  breaks every interaction. Effort: ≤ 1 day in a worktree against the
  real vendored htmx.
- **Spike-2:** verify htmx 2.0.10's `hx-trigger="every <interval>
  [condition]"` composition for UPL-21 (conditional polling). If the
  conditional-interval feature doesn't compose, document the fallback
  (server-side `HX-Trigger` interval-swap OR inline Page-Visibility
  listener). Effort: ≤ 0.5 day.

### Parking lot (not in any milestone)

- UPL-16, UPL-21, UPL-12 v1 (post-add-paper expansion to create-notebook /
  remove-notebook), UPL-22's optional `[MOT-10 breathing-glow]`, UPL-14's
  optional `[MOT-10 breathing-glow]` on running ingest pill, UPL-17's
  optional SVG illustration.
- All the synthesis §6 rejected candidates (Cmd-K palette, Distill
  margin asides, NotebookLM sidebar, all npm-installable libs, etc.).
- Meta-tooling: `ensure-preview-up.sh` should also probe
  `var/arxmcp/index/lancedb/corpus-version.json` (visual scout coverage
  note §9).

---

## 6. Visual evidence index

Screenshots × candidates that cite them:

| Screenshot | Candidates |
|---|---|
| `home-desktop.png` | UPL-10 (timestamp jitter), UPL-19 (mobile reference baseline), UPL-15 (table-row affordance) |
| `home-mobile.png` | UPL-19 (mobile table overflow) |
| `notebooks-bridgeland-stability-desktop.png` | UPL-10, UPL-11 (button in-flight state), UPL-16 (dl.meta strip), UPL-5 (rename evidence) |
| `notebooks-bridgeland-stability-mobile.png` | UPL-19 (mobile overflow on detail table) |
| `notebooks-bridgeland-stability-papers-preview-desktop.png` | UPL-6 (raw-JSON empty state — CRITICAL) |
| `notebooks-bridgeland-stability-papers-preview-mobile.png` | UPL-6 (mobile) |
| `status-badge-desktop.png` | UPL-22 (footer badge), UPL-10 (corpus-version digits) |
| `status-badge-mobile.png` | UPL-22 (footer badge mobile) |

8 captures total at
`/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/notes/frontend-uplifts/2026-05-ui-polish/screenshots/`.

---

## 7. Honest limitations

1. **Scout time budget was ~15 minutes per role** (4-brief standard
   mode). Some `/ui/` surfaces may be under-explored; the visual
   scout did a thorough live walk but the rename-422 reproduce was
   evidence-only-from-the-walk and didn't capture the emitted PATCH
   body — the challenger flagged this as a v0 prerequisite.
2. **Triangulation across 4 briefs is strong but not infallible.**
   The 6 candidates with 4-brief triangulation (UPL-1, -2, -3, -4,
   -8, -10) are the highest-confidence anchors. Single-source
   candidates (14 of 25) deserve implementer scrutiny before
   committing.
3. **RICE estimates are rough; ±50% accuracy is the realistic ceiling.**
   Effort sizing applies challenger v0/v1 splits to keep MILESTONE
   sizes honest. Calendar precision lives in `/milestone-pipeline`.
4. **The challenger evaluated against current arXMCP architectural
   locks** (CLAUDE.md §4.7 no-build-chain, 8-CSS-variable token system,
   pure-ASGI middleware, CSP `script-src 'self' 'unsafe-inline'`) +
   WCAG AA. If conventions evolve, BLOCKERs may flip. Today the only
   BLOCKER trapdoor was npm-installable libs — and the synthesis
   never proposed one.
5. **The UI security audit (`chris-dare-dev/arXMCP#9`) is OPEN.**
   Track D (in-place swaps + View Transitions) and Track E (bug-fixes
   that touch the JSON-shim or middleware) widen this surface — the
   audit landing is itself a soft dependency for those tracks.
6. **No empirical user-testing.** Every "operator-felt impact" claim
   reflects scout judgment, not field tests. The recommendation to
   ship Track A first is the highest-confidence call because the a11y
   baselines are objectively measurable; deeper rankings (Track B+)
   are credible but more subjective.

---

## 8. Cross-reference index

| UPL id | Discover briefs citing it | Screenshots supporting it |
|---|---|---|
| UPL-1 | current-state H1, library A1, inspiration CAND-3, visual G6 | (none — preventive a11y) |
| UPL-2 | current-state H2, library A2, inspiration CAND-2, visual G4 | live tab walk (visual brief §3) |
| UPL-3 | current-state H4, library A3, inspiration CAND-5, visual G11 | (semantic; no screenshot) |
| UPL-4 | current-state M7, library A4, inspiration CAND-8, visual G5 | (preventive) |
| UPL-5 | visual G1 (live PATCH 422 walk) | live captures ss_9969f6djd, ss_1595ueybh + notebooks-bridgeland-stability-desktop.png |
| UPL-6 | visual G2 | notebooks-bridgeland-stability-papers-preview-{desktop,mobile}.png |
| UPL-7 | visual G3 (live SecFetchSite walk) | ss_4286hwuko, ss_6343wkdjz, ss_7100o6f9d |
| UPL-8 | current-state H3, library A5, inspiration CAND-6, visual G13 | (parametric; no screenshot) |
| UPL-9 | library A6, inspiration CAND-6 implicit | (none) |
| UPL-10 | current-state M1, library A7, inspiration CAND-7, visual G12 | home-desktop.png, notebooks-bridgeland-stability-desktop.png |
| UPL-11 | current-state M2, inspiration CAND-4, visual G8 | live ss_9969f6djd / ss_1595ueybh (pixel-identical) |
| UPL-12 | current-state H5 | (preventive — flash on success) |
| UPL-13 | library A8, inspiration CAND-9 | (none) |
| UPL-14 | inspiration CAND-11 + visual G15 (doc-drift) | (none) |
| UPL-15 | inspiration CAND-10 | home-desktop.png (table-row inert state) |
| UPL-16 | inspiration CAND-1 | notebooks-bridgeland-stability-desktop.png (dl.meta strip) |
| UPL-17 | inspiration CAND-12 + current-state M3 partial | (preventive) |
| UPL-18 | current-state M6 | (semantic) |
| UPL-19 | visual G3 + current-state M5 | home-mobile.png, notebooks-bridgeland-stability-mobile.png |
| UPL-20 | current-state M3 | notebooks-bridgeland-stability-desktop.png (Preview column) |
| UPL-21 | visual G10 (live network log) | (network log — 30 reqs/min) |
| UPL-22 | visual G7 + current-state M4 | status-badge-desktop.png |
| UPL-23 | current-state L4 | (semantic) |
| UPL-24 | current-state L1+L2+L3 | (semantic) |
| UPL-25 | visual G14 (network 403) | (network log) |

---

## Handoff offers

### Single-candidate handoff (RICE ≥ 5 candidates)

**Six candidates clear the RICE-5 threshold (UPL-1..4, UPL-8 v0, UPL-10,
UPL-11, UPL-13, UPL-15, UPL-19 v0, UPL-22, UPL-23, UPL-25).** Any can be
shipped via `/milestone-pipeline` directly. The recommended first ship
is the foundational bundle (UPL-1..4):

```
/milestone-pipeline ui-a11y-baseline-m1 --brief "Adopt the 4 foundational
a11y baselines from frontend-uplift 2026-05-ui-polish UPL-1..4 …"
```

(See Track A above for the full brief text.)

### Multi-candidate program handoff (≥ 3 candidates above RICE 3.0)

**16 candidates clear RICE 3.0.** To convert this report into a roadmap
with sequenced milestones:

```
/roadmap ui-attractive-polish --brief "$(head -350 .claude/notes/frontend-uplifts/2026-05-ui-polish/artifacts/final-report.md)"
```

The roadmap skill will refine → decompose → sequence → materialize from
the 4-track plan in §5 above (Track A foundational → Track B visible
polish → Track C dark + htmx-feedback → Track D in-place swaps + View
Transitions → Track E bug-fixes parallel).

(Note: frontend-uplift NEVER auto-invokes `/milestone-pipeline` or
`/roadmap` — offer-and-wait.)

---

*End of final report.*
