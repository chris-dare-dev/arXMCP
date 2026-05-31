# UI attractive polish — close the bare-bones gap — Roadmap

**Slug:** `ui-attractive-polish`
**Created:** 2026-05-31T01:55:30Z
**Status:** init

<!--
This roadmap is itself the state. Re-invoking the `roadmap` skill on
this file resumes from the first un-populated phase. Sections below
contain `{{TOKEN}}` placeholders until their phase runs.

Phases:
  1. REFINE     — How-Might-We, sharpening questions, assumptions, OKR, Won't list
  2. DECOMPOSE  — technique, epics, INVEST, specialist suggestions
  3. SEQUENCE   — MoSCoW, RICE, Now/Next/Later, spike lane, Now-lane milestones
  4. MATERIALIZE — validation results, optional GitHub bundle, next-step handoff
-->

---

## Phase 1 — Refine

<!-- populated by REFINE phase 2026-05-30; brief = head-350 of
.claude/notes/frontend-uplifts/2026-05-ui-polish/artifacts/final-report.md
(itself the output of a 4-scout / 1-challenger / 25-candidate discovery
pipeline). Sharpening was answered from the discovery artifacts in lieu
of a fresh Q&A pass with the user — the brief IS the polished output of
a discovery skill, so questions like "what does attractive mean?" are
already named at the UPL-N level. -->

### How Might We

How might we raise arXMCP's `/ui/` operator console from "shipped
correctness, bare on a11y and visual polish" to **2026-SOTA-parity for
a dense-info dev-tool surface**, **for a single loopback-only operator
(Chris)**, **without introducing a Node/npm build chain or widening the
deferred UI security audit** (`chris-dare-dev/arXMCP#9`)?

### Sharpening questions answered

1. **Is "attractive and less bare-bones" subjective enough to need
   re-scoping?** No — the uplift's discovery pipeline already named the
   gap concretely: zero `prefers-reduced-motion`, zero `:focus-visible`,
   zero `aria-live` on success swap targets, no skip-link, no dark mode,
   no `tabular-nums`, no htmx-in-flight feedback, mobile table overflow,
   `location.reload()` on every successful create. "Attractive" =
   closing these named gaps via pure-CSS / native-Web-API / vendored-
   single-file drops only. The 25 candidates in
   `.claude/notes/frontend-uplifts/2026-05-ui-polish/artifacts/synthesis.md`
   are the concretization.

2. **What's the operator workflow this UI serves?** The single operator
   (Chris) manages notebooks (corpora), adds papers via URL or upload,
   kicks off ingest runs, watches polling status, deletes / renames
   notebooks. The "live, scannable, quietly animated, keyboard-honest"
   tone is the right anchor — biased toward dense-info dev-tool patterns
   (Linear, Vercel Dashboard, Raycast, Zed) + scholarly platforms
   (arXiv abstract, ar5iv, Distill). NOT a SaaS marketing surface.

3. **What's the budget envelope across the program?** Five tracks per the
   final report's §5: Track A (foundational a11y, ≈S), Track B (visible
   polish, ≈S), Track C (dark + htmx feedback, ≈M), Track D (in-place
   swaps + View Transitions, ≈M+ + audit-coordination), Track E (bug-
   fixes — RUN AS PARALLEL milestones, NOT in this roadmap's Now lane
   per final-report §5 Track E). Single milestone (Track A) ships
   immediately; the rest sequence over several weeks.

4. **What's the UI-security-audit dependency?** Track D candidates (UPL-12
   in-place swaps, UPL-13 View Transitions) materially widen
   `chris-dare-dev/arXMCP#9`. Land Track A → Track B → Track C first;
   defer Track D until the audit is either greenlit OR descoped to
   not-blocking. The audit landing is therefore a soft dependency
   captured as a Spike-lane discovery item.

5. **Why are UPL-5/6/7 (the CRITICAL bug-fixes) NOT in this roadmap's
   Now lane?** Per the final report §5 Track E + the challenger's
   §6.3 diagnostic concern on UPL-5: those are regressions on shipped
   functionality (silent rename, raw-JSON empty-states, raw-JSON
   middleware rejection) — not "polish." They each get their own
   `/milestone-pipeline ui-rename-422-fix-bm1` etc., run in parallel
   with this roadmap, and the v0 for UPL-5 starts with a reproduce-
   first spike (capture the actual emitted PATCH body before coding
   any fix to the JSON-shim). Bundling them into the polish roadmap
   would obscure the "fix-anyway, RICE-independent" framing.

### Assumptions

- `[MUST]` **arXMCP's `/ui/` stack stays Jinja2 + vendored htmx + a
  single CSS file** — i.e. CLAUDE.md §4.7 (no-build-chain, no SPA,
  no Node, no npm) remains a project-level hard constraint for the
  whole program. (Validated by existing constitution; no spike needed.)
- `[MUST]` **A11y baselines (`prefers-reduced-motion`, `:focus-visible`,
  `aria-live`, skip-link) deliver real value to a single-operator
  loopback console** — not just compliance theater. (Chris uses
  keyboard nav, may use screen-reader testing; even self-use benefits.
  Validated by inspection of the visual-scout brief — destructive red
  buttons currently have NO visible keyboard focus on Safari.)
- `[MUST]` **The View Transitions API integration with htmx 2.0.10 works
  via the `htmx:beforeSwap` event + `document.startViewTransition()`
  pattern** documented in MDN and the library-scout brief. If `htmx.swap()`
  re-entry has the wrong signature, UPL-13 silently breaks every
  interaction. **Validated by Spike-1.**
- `[SHOULD]` **Browser baselines for `:has()`, View Transitions API,
  `color-mix()`, `popover` attribute are stable enough to ship as
  primary behavior** for Chris's actual browser (Chrome on macOS, per
  the visual scout's live-walk evidence). Library-scout cites Baseline
  Widely Available status for `color-mix()` (2025-11) and Newly→Widely
  Available for `:has()` (~2026-06); View Transitions same-document
  Baseline Widely Available in Chrome+Safari, no-op in Firefox.
- `[SHOULD]` **The dark-mode color choices anchored to GitHub Primer's
  dark scale meet WCAG AA contrast for the existing 8 tokens** without
  needing a parallel token system. Falls back to "ship v0 with 8 base
  tokens only; defer status-pill dark-mode remap to v1" per challenger
  finding on UPL-8.
- `[MIGHT]` **htmx 2.0.10's `hx-trigger="every 2s [condition]"`
  composes** (poll-backoff candidate UPL-21). Spike-2 verifies; if
  it doesn't, fallback is server-side `HX-Trigger` interval-swap OR
  inline Page-Visibility listener.
- `[MIGHT]` **Chris's monitor is wide enough that expanding `body {
  max-width: 980px }` to `clamp(640px, 92vw, 1400px)` improves the
  workflow** (UPL-19 v1). The v0 (just `.table-wrap` wrappers) ships
  the mobile fix without this assumption.

### Objective

**Raise arXMCP's `/ui/` operator console to 2026-SOTA-parity for a
dense-info dev-tool surface — closing the named a11y, dark-mode, and
htmx-feedback gaps via pure-CSS / native-Web-API / vendored-single-file
techniques only — while preserving the no-build-chain constitution and
not widening the open UI security audit until that audit lands.**

### Key Results

1. **By 2026-06-15:** the 4 foundational a11y baselines from UPL-1..4
   (`prefers-reduced-motion` universal gate, `:focus-visible` outline
   ring, `aria-live="polite"` on 4 htmx success swap targets +
   `aria-atomic` on the status-badge, skip-to-main-content link) are
   live in `frontend/static/app.css` + `frontend/templates/base.html`,
   confirmed by **manual keyboard-walk of all 3 routes + 1 fragment
   without losing focus** AND **macOS VoiceOver smoke-test announces
   at least the rename success and ingest-poll transitions**.
2. **By 2026-06-30:** `@media (prefers-color-scheme: dark)` is honored
   across all 3 HTML routes — light and dark token sets BOTH pass
   WCAG AA non-text contrast (3:1) for `--fg` on `--bg` and `--card-bg`,
   measured via a checker against the post-edit CSS.
3. **By 2026-06-30:** `htmx-request` styling produces visible in-flight
   feedback (opacity dim + spinner) on at least 5 of the 7 htmx-bound
   forms (Create / Rename / Add paper / Upload / Ingest / Remove
   notebook / Remove paper) within 100ms of click, measured by DevTools
   Performance recording of one happy-path interaction per form.
4. **By 2026-07-15:** at least one of the three legacy `location.reload()`
   flows (target: add-paper, per the challenger's v0-narrow recommendation
   for UPL-12) is converted to an in-place htmx swap, eliminating the
   full-page white flash on that flow — verified by recording a 60-fps
   capture showing no `unload`/`load` event sequence on a successful add.
5. **Across the program:** total `frontend/static/app.css` size stays
   under **300 lines** (currently 126; budget +174 lines of pure CSS)
   AND **zero new npm dependencies, package.json files, or build-chain
   artifacts** are introduced (re-validated by `make test` passing +
   ruff clean + the existing `tests/test_vendored_assets_integrity.py`
   continuing to pin only `htmx.min.js`).

### Won't (explicit out-of-scope)

- **No SPA migration** — Next.js / React / Vue / Svelte / Vite remain
  CLAUDE.md §4.7 BLOCKERs. Re-pinned across notebook-surface-expansion
  m3 and m5.
- **No npm-installable libraries** — Tailwind / shadcn / Radix / Framer
  Motion / GSAP-pro / Recharts / Zustand / TanStack / Alpine.js are all
  enumerated in the final-report §6 rejection set.
- **No custom web font** (Inter / IBM Plex / Source Serif) — would add
  CSP `font-src` widening + network fetch; system-ui stack at
  `app.css:18` is excellent on macOS / Linux / Windows.
- **No Cmd-K command palette** — final-report §6 parks this until
  notebook count grows past ~20 OR a search surface lands. The
  current 3-page surface doesn't justify a global-keyboard-handler
  modal trap.
- **No marketing surface or hero imagery** — arXMCP has no marketing
  surface; the README is the only public face.
- **No multi-user / auth / OAuth** — loopback-only design is the
  security model; the `SecFetchSiteMiddleware` + `OriginValidationMiddleware`
  triple defense is load-bearing.
- **No SVG illustrations for empty states** — UPL-17 ships the
  copy + CTA upgrade only; designer-asset budget is not in scope.
- **No UPL-5/6/7 bug-fix work inside THIS roadmap** — they run as
  parallel `/milestone-pipeline ui-rename-422-fix-bm1` /
  `ui-preview-empty-bm2` / `ui-secfetch-html-bm3` invocations per the
  final-report §5 Track E. Bundling them into the polish roadmap
  obscures the "fix-anyway, RICE-independent" framing.
- **No `idiomorph` vendoring** — final-report §6 parks; arXMCP's swap
  targets are small enough that morphdom-style diffing isn't load-
  bearing. Revisit if focus-loss / scroll-jump becomes a real
  observed problem.
- **No `:has()`-driven layout primitives** — library-scout flagged
  Baseline status as Newly→Widely-Available ~2026-06. Use only as
  progressive enhancement (e.g. inside UPL-15's table-row hover
  rules), never as a load-bearing layout.

---

## Phase 2 — Decompose

### Technique

**Vertical slicing + enabler stories.** Each epic delivers an
operator-visible behavior change (keyboard nav working / dark mode
honored / in-flight feedback / no full-page flash on create), not a
horizontal layer. Deviation from the default was unnecessary — the
4-track structure surfaced by the discovery pipeline IS a clean
vertical-slice decomposition.

### Epics

#### ui-attractive-polish-e1 — `/ui/` keyboard-walkable and screen-reader-honest

- **Type:** value
- **Specialist suggestion:** `—` (CSS + Jinja2 attribute additions only;
  no parser/cache/MCP/security path matches. The milestone-pipeline's
  default adversary critic suffices.)
- **Outcome:** the four foundational a11y baselines (UPL-1..4) are live;
  Chris can keyboard-walk all 3 routes + 1 fragment without losing focus;
  VoiceOver announces htmx success swaps; the universal `prefers-
  reduced-motion` gate is in place so no future motion candidate is a
  Phase-3 BLOCKER. Closes KR-1.
- **Estimated size:** S (4 × XS items bundled)
- **INVEST check:** I clean (zero deps on later epics; ships first),
  N clean (each UPL inside can be deferred individually), V clean
  (Chris-visible keyboard walk improvement), E clean (T-shirt S),
  S clean (1 week max), T clean (KR-1 has manual-walk + VoiceOver-
  smoke-test gates).
- **Dependencies:** none
- **Won't conflict check:** none
- **Inside:** UPL-1, UPL-2, UPL-3, UPL-4 — see
  `.claude/notes/frontend-uplifts/2026-05-ui-polish/artifacts/final-report.md`
  §4 ranks 1-4.

#### ui-attractive-polish-e2 — `/ui/` numerically calm and mobile-readable

- **Type:** value
- **Specialist suggestion:** `—` (CSS + template wrapper edits + 1
  static asset only)
- **Outcome:** the dense-info polish layer — `tabular-nums` removes
  digit-jitter on every htmx swap; `color-mix()` adoption replaces the
  imprecise `filter: brightness(1.08)` hover; `.table-wrap { overflow-x:
  auto }` fixes mobile table clipping; `aria-hidden` on footer separators
  silences SR noise; a tiny SVG favicon eliminates devtools 403 noise.
  Operator-visible improvement: numbers stop dancing, mobile is usable,
  hover states feel intentional. Also: lays the `color-mix()` foundation
  for e3's dark-mode status-pill derivation.
- **Estimated size:** S (5 × XS bundled)
- **INVEST check:** I clean (no dep on other epics for v0 ship; UPL-9
  inside is itself a forward-dep for e3 but ships first), N clean
  (each UPL drops individually), V clean (jitter-free typography +
  mobile fix are immediately visible), E clean, S clean (1 week),
  T clean (KR-3 sub-clause + measurable contrast checks).
- **Dependencies:** none (and unblocks e3 via UPL-9)
- **Won't conflict check:** none
- **Inside:** UPL-9, UPL-10, UPL-19 v0, UPL-23, UPL-25 — final-report
  §5 Track B.

#### ui-attractive-polish-e3 — `/ui/` dark-mode-honest and click-acknowledged

- **Type:** value
- **Specialist suggestion:** `—` (CSS + `hx-disabled-elt` attribute
  additions on htmx forms; no parser/cache/MCP/security path matches.
  However: the universal-selector `*` rule in UPL-1 + the new
  `.htmx-request` styling combine in subtle ways with macOS Safari's
  WebKit transition-event semantics — the adversary critic should
  manual-verify on Safari before close.)
- **Outcome:** `@media (prefers-color-scheme: dark)` is honored — the
  white-flash-on-dark-OS goes away. `.htmx-request` styling produces
  visible click-acknowledgement on every htmx-bound form within 100ms.
  Operator-visible improvement: dark-mode operators feel respected;
  every click feels acknowledged. Closes KR-2 + KR-3.
- **Estimated size:** M (UPL-8 v0 S + UPL-11 S + integration testing
  ≈ M total; cross-browser verification adds buffer)
- **INVEST check:** I borderline — depends on e1 (UPL-1 `prefers-reduced-
  motion` gate is prereq for UPL-11's spinner animation per challenger)
  and e2 (UPL-9 `color-mix()` is prereq for v0 dark-mode pill
  derivations, though v0 sidesteps the status-pill remap entirely);
  N clean, V clean, E clean, S clean (≤ 2 weeks), T clean (KR-2 +
  KR-3 are measurable).
- **Dependencies:** e1, e2 (hard sequencing edge)
- **Won't conflict check:** none — UPL-11 uses only htmx core CSS hooks
  (`htmx-request` auto-class), no new vendored asset.
- **Inside:** UPL-8 v0 (8 base tokens only — defer status-pill dark-mode
  remap to a v1 follow-on), UPL-11.

#### ui-attractive-polish-e4 — `/ui/` swap-fluent and flash-free on success

- **Type:** value
- **Specialist suggestion:** `security-reviewer` — see
  `.claude/skills/roadmap/references/specialist-contracts.md`. UPL-12
  introduces new server-side fragment-rendering endpoints in
  `server/routes/notebooks.py`; UPL-13 adds an htmx-event-bridge inline
  script in `base.html` (within the existing `'unsafe-inline'`
  allowance, but adds JS to the un-audited UI surface
  `chris-dare-dev/arXMCP#9`). UPL-22's `htmx-settling` flash relies on
  the `color-mix()` derivation from e2.
- **Outcome:** the legacy `location.reload()` add-paper flow is
  converted to an in-place htmx swap — the full-page white flash on
  successful "Add paper by URL" is gone. View Transitions API wraps
  the m2 rename swap + the new add-paper swap with a ~200ms crossfade
  on Chrome/Safari (no-op on Firefox). The footer status-badge gets a
  fixed-width slot + a flash on every 10s swap so operators see "the
  badge just refreshed." Operator-visible improvement: the UI starts
  feeling like a real SPA without ever becoming one. Closes KR-4.
- **Estimated size:** M (UPL-12 v0 M + UPL-13 S + UPL-22 XS +
  audit-coordination overhead ≈ M+; soft-capped at M by descoping to
  add-paper-only per challenger.)
- **INVEST check:** I borderline — depends on e1 (UPL-3 `aria-live` on
  swap targets is prereq for UPL-12 swap UX) AND e3 (UPL-11 `htmx-request`
  in-flight feedback is prereq for UPL-12 per challenger's §6.1 — without
  in-flight signal, the no-reload flow has LESS affordance than the
  reload flow it replaces); also has a soft dependency on the UI
  security audit landing (`chris-dare-dev/arXMCP#9` — see §6.2 of the
  challenge). N clean (the v0 add-paper-only narrowing is the
  negotiation), V clean, E clean (M with v0 scope), S clean (3 weeks
  max if audit-coord is sequenced post-Track-C, not parallel), T clean
  (KR-4 is the 60-fps capture gate).
- **Dependencies:** e1, e2, e3, AND the UI security audit
  (`chris-dare-dev/arXMCP#9`) must be at least scoped before kickoff —
  represented in SEQUENCE as a Spike-lane "audit-coordination" item.
- **Won't conflict check:** none — UPL-12's content-negotiation pattern
  (HX-Request → fragment, else JSON) is server-side; no SPA migration.
  UPL-13's inline JS uses the existing `'unsafe-inline'` allowance,
  no CSP widening.
- **Inside:** UPL-12 v0 (add-paper only), UPL-13, UPL-22.

---

## Phase 3 — Sequence

### MoSCoW assignment

- **Must** (≤ 60% of total effort): `ui-attractive-polish-e1`, `ui-attractive-polish-e2`
- **Should**: `ui-attractive-polish-e3`
- **Could**: `ui-attractive-polish-e4`
- **Won't (this cycle)**: (none — the Won't list in Phase 1 captures the architectural/scope rejections; no epic was demoted here)

**`score-moscow.py` result:** `OK: Must = 25.0% (≤ 60% cap)` —
2.00pm / 8.00pm total. The Must cap is comfortably under the 60%
ceiling; this gives Phase 4's MATERIALIZE room to push e3 to Must if a
discovery-time finding bumps its priority.

### RICE ranking — Musts

| ID | Reach | Impact | Confidence | Effort | Score |
|---|---:|---:|---:|---:|---:|
| `ui-attractive-polish-e1` | 10 | 1.00 | 100% | 1.00 | 10.0 |
| `ui-attractive-polish-e2` | 10 | 1.00 | 95% | 1.00 | 9.5 |

_No `*` markers — both Musts have evidenced confidence (e1 = 4-brief unanimous + Baseline-Widely-Available CSS APIs; e2 = 4-brief on UPL-10, 2-brief on UPL-19, 1-brief but cheap on UPL-23/25). RICE ranks e1 ahead of e2 by a thin margin reflecting UPL-19's lower triangulation; ship m1 first._

### Now / Next / Later

- **Shipped** (commits on `origin/main`):
  - `ui-attractive-polish-m1` (epic e1; commits `924d5ad..40f3552` — feat `c5adff3` + rect `dc30b93` + chore `40f3552`). Foundational a11y baselines UPL-1..4. RICE 10.0. Status: terminal.
  - `ui-attractive-polish-m2` (epic e2; commits `40f3552..fdd28d4` — feat `672ad81` + rect `4f1f664` + chore `fdd28d4`). Visible polish layer UPL-9/10/19v0/23/25. RICE 9.5. Status: terminal.
  - `ui-attractive-polish-m3` (epic e3; commits `e69de9c..b66fa1e` — chore-plans `e69de9c` + feat `58bfb41` + rect `08b9c53` + chore `b66fa1e`). Dark mode + htmx-request feedback UPL-8 v0 + UPL-11. **Critique surfaced 1 HIGH (text-input dark-mode invisibility) + 2 MED + 1 LOW; all fixed in rect.** Status: terminal.
- **Now** (fully spec'd, in-flight or next-up):
  - `ui-attractive-polish-e4` (promoted from Next after m3 shipped + BOTH spikes returned PASS). 1 milestone `m4` below (UPL-12 v0 add-paper in-place swap + UPL-13 View Transitions + UPL-22 status-badge flash).
- **Next** (shaped, awaiting capacity):
  - (empty — m4 v1 follow-ons (UPL-12 v1 for create/remove flows, UPL-8 v1 dark-mode status-pill remap, UPL-19 v1 wider clamp) can shape into m5 after m4 ships)
- **Later** (outcome-only, low-confidence horizon):
  - (empty — no further epics planned at this layer; future polish would start a new roadmap)

### Spike / discovery lane

- `ui-attractive-polish-spike-1` — **STATUS: PASS** (decision memo:
  `.claude/notes/ui-attractive-polish-spike-1.md`, ~30 min actual vs
  ≤ 1 day budget). Key finding: htmx 2.0.10 has **native first-class
  View Transitions integration** (the `htmx:beforeSwap` + manual
  `document.startViewTransition()` re-entry pattern the original brief
  cited was an htmx-1.x workaround, obsolete in 2.x). Two native opt-ins
  documented at `htmx.org/docs/#view-transitions`:
  - **Global:** `htmx.config.globalViewTransitions = true` (1 LOC).
  - **Per-element:** `hx-swap="<style> transition:true"`.
  Confirmed by inspecting the vendored `frontend/static/htmx.min.js`
  (`Q.swap = _e`; `globalViewTransitions: false` in default config;
  internal `document.startViewTransition(function(){i()...})` call site).
  **Implication for UPL-13**: drops from S effort + audit-widening
  (~5 LOC inline JS) to **XS (1 LOC config flag, zero audit-widening)** —
  uses the existing `'unsafe-inline'` CSP allowance for the inline
  JSON-shim block in `base.html`. Risk eliminated: no user JS for htmx
  to call with the wrong signature; htmx handles it internally with a
  `if (document.startViewTransition)` graceful-degradation guard.

- `ui-attractive-polish-spike-2` — **STATUS: PASS (hybrid (a))** (decision
  memo: `.claude/notes/ui-attractive-polish-spike-2.md`, ~45 min actual
  vs ≤ 2 day budget). Key finding: the framing as a binary fork ((a) full
  audit, (b) descope UPL-12) was wrong — issue #9 ALREADY exists as the
  tracking issue, and UPL-12 v0's incremental surface doesn't widen any
  of issue #9's 5 open questions (CSRF posture, upload polyglot,
  path-traversal on preview, CSP `unsafe-inline` scope, render-path
  divergence). The marginal axis (render-path divergence on the new
  add-paper fragment) is bounded by an **e4 pre-flight checklist** that
  the m4 milestone-pipeline adversary critic verifies — 13 mechanically
  checkable items across 4 axes (server-fragment correctness, middleware
  integrity, input validation, test surface). The fragment-rendering
  precedent (`_paper_row_html`, `_display_name_fragment`,
  `ui_status_badge`, `_ingest_status_fragment`) is already audited-by-
  pattern via `html.escape()` per value. **Implication for e4**: ship
  UPL-12 v0 (add-paper only) as planned in m4 with the pre-flight
  checklist as load-bearing AC; issue #9 stays open as a separate
  effort (the full audit is NOT a m4 dependency).

### Milestones — Now lane

<!--
Each Now-lane milestone is its own H3 below. Heading format is
`### <slug>-mN — Title` exactly — milestone-pipeline's init-state.sh
greps for this. Do not change it.
-->

### ui-attractive-polish-m1 — Foundational a11y baselines (UPL-1..4)

**Description.** Bundle the four foundational a11y baselines from the
uplift's RICE-rank-1 candidates into one CSS + template edit pass.
Establishes the `prefers-reduced-motion` gate, the `:focus-visible`
outline-ring, the `aria-live` parity on htmx success swap targets, and
the skip-to-main-content link. Implementation = pure CSS additions to
`frontend/static/app.css` + 5 attribute additions across 3 templates +
1 HTML line in `base.html`. No new vendored asset. No JS. No CSP impact.

**Acceptance criteria.**
- [ ] **UPL-1** — `@media (prefers-reduced-motion: reduce)` universal block at the bottom of `frontend/static/app.css` clamps `animation-duration`, `animation-iteration-count`, `transition-duration`, `animation-delay`, `transition-delay`, and `scroll-behavior` (per challenger MINOR finding adding delay coverage).
- [ ] **UPL-2** — `:focus-visible` outline rules for `button, .button, a, input, select, textarea, [tabindex]` using `var(--accent)` at 2px solid with `outline-offset: 2px`. `button.danger:focus-visible` uses `outline-color: var(--danger)` (per challenger finding — destructive controls deserve the LOUDEST focus ring, not the quietest). `:focus:not(:focus-visible)` resets outline.
- [ ] **UPL-3** — `aria-live="polite"` added to `#display-name-block` (`frontend/templates/notebook_detail.html:15`), `#ingest-status` (`:161`), `#papers-tbody` (`:180`); `#status-badge` (`frontend/templates/base.html:65`) gets `aria-live="polite" aria-atomic="true"`. The 5 existing `pre.error[aria-live="polite"]` regions are left unchanged.
- [ ] **UPL-4** — `<a class="skip-link" href="#main">Skip to main content</a>` added as the FIRST child of `<body>` in `frontend/templates/base.html`. The existing `<main>` gets `id="main" tabindex="-1"`. CSS rule for `.skip-link` visually-hides off-screen until `:focus-visible`, then reveals at `left: 1rem; top: 1rem` with `background: var(--accent); color: #fff`.
- [ ] **Verification — keyboard walk:** start with focus on URL bar, Tab forward through `/ui/`; skip-link is the first focus stop (visible); subsequent Tabs reach the Create form's display-name input, then the Create button, then each notebook row's Open link and Remove button. Every focused element shows the `--accent` ring (or the `--danger` ring for `button.danger`). Repeat on `/ui/notebooks/bridgeland-stability` — Tab reaches the Rename input, then Rename submit, then Add-paper URL input, etc. No element shows the browser-default focus ring.
- [ ] **Verification — VoiceOver smoke-test:** on `/ui/notebooks/bridgeland-stability`, trigger a successful rename via the Rename form. VoiceOver announces the new display name (`#display-name-block` swap reaches an `aria-live` region). Wait 10s for the next status-badge poll; VoiceOver announces the badge content as one atomic string (e.g. "READY · corpus v645 · 2 notebooks"). The status badge poll fires `aria-live` because of `aria-atomic="true"`.
- [ ] `make test` exits 0 (ruff + pytest, ≤2129 tests passing on macOS / Linux).
- [ ] Final `frontend/static/app.css` line count ≤ 165 (current 126 + budget 30 for UPL-1+UPL-2+UPL-4; UPL-3 adds zero CSS).

**Dependencies.** epic `ui-attractive-polish-e1`. No prior milestone deps. Independent of UPL-5/6/7 bug-fix track.

**Complexity.** S (≤ 1 day execution including the 4-phase milestone-pipeline; total CSS+HTML changes ≈ 40-50 lines; manual keyboard + VoiceOver verification is the largest time slice).

**Specialist suggestion.** `—` (CSS + Jinja2 attribute additions only; milestone-pipeline's default adversary critic covers it).

### ui-attractive-polish-m2 — Visible polish layer (UPL-9, UPL-10, UPL-19 v0, UPL-23, UPL-25)

**Description.** The dense-info polish layer. `tabular-nums` ends digit
jitter on every htmx poll. `color-mix()` adoption replaces the imprecise
`filter: brightness(1.08)` button hover with a token-derivable shade,
and lays the foundation for e3's dark-mode status-pill derivation.
`.table-wrap` `<div>`s fix the mobile table-overflow bug visible in the
visual scout's mobile screenshots. `aria-hidden` on footer `·`
interpuncts removes SR noise. A trivial SVG favicon kills the
`/favicon.ico → 403` devtools noise. All pure CSS / template wrap edits /
one static asset.

**Acceptance criteria.**
- [ ] **UPL-10** — `time, .status-badge, dl.meta dd, td code { font-variant-numeric: tabular-nums; }` added to `frontend/static/app.css`. Verify on `/ui/`: the Created column in `table.notebooks` no longer reflows horizontally across page reloads with different ISO timestamps.
- [ ] **UPL-19 v0** — `<div class="table-wrap">` wrappers around both `<table class="notebooks">` (`frontend/templates/index.html:37` line approximately) and `<table class="papers">` (`frontend/templates/notebook_detail.html:176` line approximately). CSS rule `.table-wrap { overflow-x: auto; }` added to `app.css`. **Do NOT** ship the `body { max-width: min(95vw, 1400px) }` expansion in this milestone (per challenger finding — descope to v1; keep the 980px ceiling for now).
- [ ] **UPL-9** — replace `filter: brightness(1.08)` at `frontend/static/app.css:87` (or wherever the button-hover rule lives) with `background: color-mix(in oklab, var(--accent) 88%, white);` and `border-color: color-mix(in oklab, var(--accent) 80%, var(--fg));` (or similar — the exact derivation chosen by the implementer; verify hover state still meets WCAG AA contrast on light-mode `--bg`). Establishes the `color-mix()` pattern for e3 to extend.
- [ ] **UPL-23** — wrap each `·` interpunct in `frontend/templates/base.html:57-67` (the 5 footer separators) in `<span aria-hidden="true">·</span>`. Verify via VoiceOver on `/ui/` — footer reads only the link labels, no "middle dot" / "interpunct" announcements between them.
- [ ] **UPL-25** — create `frontend/static/favicon.svg` (a trivial 32×32 SVG — e.g. a small `<rect>` filled with `var(--accent)` color OR a stylized "arX" monogram; implementer's choice). Add `<link rel="icon" href="/ui/static/favicon.svg" type="image/svg+xml">` to `<head>` in `frontend/templates/base.html`. Verify DevTools network log on `/ui/` no longer shows `GET /favicon.ico → 403`; instead, the SVG is fetched once and cached.
- [ ] **Verification — mobile screenshot:** at 390×844 viewport (iPhone 12 dimensions), navigate to `/ui/notebooks/bridgeland-stability` — the papers table is scrollable WITHIN the card boundary (horizontal scroll fits inside the `.card` container), NOT clipped off the right edge of the viewport with no recovery affordance. Capture and save to `.claude/notes/milestones/ui-attractive-polish-m2/mobile-after.png`.
- [ ] `make test` exits 0.
- [ ] `frontend/static/VENDORED.md` updated if the SVG favicon counts as a vendored asset (likely no — it's hand-authored, not vendored). If updated, the `tests/test_vendored_assets_integrity.py` test continues to pass.
- [ ] Final `frontend/static/app.css` line count ≤ 175 (m1's 165 + m2's ≈ 10 new lines for tabular-nums + table-wrap + color-mix).

**Dependencies.** epic `ui-attractive-polish-e2`. Soft sequencing edge: SHIPS AFTER m1 (so the foundational a11y baselines land first), but m2's content has no hard dep on m1's content — could ship in either order if budget required.

**Complexity.** S (~ 0.5-1 day execution; the mobile verification + favicon design are the largest time slices).

**Specialist suggestion.** `—`.

### ui-attractive-polish-m3 — Dark mode + htmx-request feedback (UPL-8 v0 + UPL-11)

**Description.** Bundle the two e3 polish items into one CSS pass that
ships dark-mode parity and per-click visual feedback together. Both
depend on m1 + m2 (which are shipped on `origin/main`), so this is
foundation-clean. **UPL-8 v0** adds a `@media (prefers-color-scheme:
dark) { :root { … } }` block re-declaring the 8 base tokens with
GitHub-Primer-anchored dark values; per the challenger v0/v1 split,
the `.status-badge--*` modifier remap + table-header dark surface +
freshness color stay descoped to a v1 follow-on (so dark-mode
operators see consistent body chrome but the colored status pills
keep their light-mode contrast until v1 — visually inconsistent but
a11y-safe). **UPL-11** adds CSS targeting htmx's auto-applied
`htmx-request` class so every in-flight button dims + becomes
non-clickable + shows a tiny CSS-only spinner (the spin animation
itself is gated by `prefers-reduced-motion: no-preference`, which
m1 already established). Also adds `hx-disabled-elt="this"` to the
htmx-bound forms for keyboard a11y parity (so a focused-but-disabled
button doesn't accept Tab-triggered Enter activation mid-request).

**Acceptance criteria.**
- [ ] **UPL-8 v0** — `@media (prefers-color-scheme: dark) { :root { … } }` block added to `frontend/static/app.css`. Re-declares all 8 vars (`--fg`, `--bg`, `--card-bg`, `--border`, `--accent`, `--danger`, `--error-bg`, `--mono`) with GitHub-Primer-anchored dark values (e.g. `--fg: #e8e8e8`, `--bg: #0d1117`, `--card-bg: #161b22`, `--border: #30363d`, `--accent: #58a6ff`, `--danger: #f85149`, `--error-bg: #2a1a18`, `--mono` unchanged). Status-pill modifier remap + table-header dark surface + freshness color all stay light-mode (descoped to v1).
- [ ] **UPL-8 v0 verification** — both light and dark token sets pass WCAG AA non-text contrast (≥ 3:1) for `--fg` on `--bg` AND `--fg` on `--card-bg`. Verify via an offline checker or by inspection of the chosen hex pairs; record the contrast ratios in the milestone's implementation-summary.
- [ ] **UPL-11** — CSS rules for the auto-applied htmx classes added to `app.css`:
    - `button.htmx-request, .button.htmx-request { opacity: 0.6; pointer-events: none; cursor: wait; }` (unconditional — these are SIGNAL, not motion).
    - `.htmx-request::after { content: ""; display: inline-block; width: 0.8em; height: 0.8em; margin-left: 0.5em; border: 2px solid currentColor; border-right-color: transparent; border-radius: 50%; vertical-align: middle; }` (the spinner shape).
    - `@media (prefers-reduced-motion: no-preference) { .htmx-request::after { animation: spin 0.6s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } } }` (the spin animation gated by m1's foundational gate).
- [ ] **UPL-11 form attribute parity** — add `hx-disabled-elt="this"` to the 7 htmx-bound forms (Create notebook in `index.html`; Rename / Add-paper / Upload / Ingest now in `notebook_detail.html`; Remove notebook + Remove paper as button-only deletes). Ensures keyboard users can't double-fire a request via Enter-while-disabled.
- [ ] **Verification — `make test` exits 0** (via the canonical `/Users/chris.dare/Library/Python/3.9/bin/uv run python -m ruff check . && uv run python -m pytest`). All 41 existing m1+m2 tests still pass; new m3 tests added.
- [ ] **Verification — manual cross-browser walk** — Chris loads `/ui/` on Chrome + Safari on macOS with the OS theme toggled (Settings → Appearance → Dark vs Light). Both routes (`/ui/` + `/ui/notebooks/<slug>`) render coherently in both modes — no light-mode flash on dark-OS, no broken contrast on light-OS. Also: click "Ingest now" with a cold subprocess pool; the button visibly dims + shows a spinner within 100ms; double-click attempt rejected.
- [ ] **Verification — manual VoiceOver smoke-test** — VoiceOver on the focused-then-disabled button announces "dim" / "disabled" state via the `hx-disabled-elt` attribute's `aria-disabled` injection (htmx auto-applies); the spinner is invisible to AT (no `aria-label` on the `::after` content).
- [ ] **Regression test** at `tests/test_ui_m3_dark_and_htmx_feedback.py` (new file) — asserts the `@media (prefers-color-scheme: dark)` block exists + redeclares all 8 vars + the `.htmx-request` CSS rules exist with the correct selectors + the spin keyframe is inside the `prefers-reduced-motion: no-preference` block + every htmx-bound `<form>` in the templates carries `hx-disabled-elt="this"`.
- [ ] Final `frontend/static/app.css` line count ≤ 270 (current 216 + budget ~50 for dark-mode block + htmx-request styling).

**Dependencies.** epic `ui-attractive-polish-e3`. **Hard prereqs (now shipped):** m1's `prefers-reduced-motion` gate (anchors the spinner animation guard); m2's `color-mix()` adoption (not strictly required for v0 since the status-pill remap is descoped, but the pattern lives now). **No new spike** — both pure-CSS APIs are Baseline Widely Available; the implementation can proceed without measurement.

**Complexity.** M (~ 1–2 days execution including the 4-phase milestone-pipeline; ~50 LOC CSS + 7 attribute additions on htmx forms + the new test file; manual cross-browser theme verification + VoiceOver smoke-test are the largest time slices). Per the milestone-pipeline complexity scale: M is the right grade (1–3 days). Could split into m3 (dark mode) + m4 (htmx-request) but the m1+m2 precedent is to bundle multiple UPLs into one milestone; bundling here saves one full pipeline overhead.

**Specialist suggestion.** `—` (CSS + Jinja2 attribute additions only; milestone-pipeline's default adversary critic covers the surface — token-discipline, prefers-reduced-motion gate compliance, htmx-attribute correctness).

### ui-attractive-polish-m4 — In-place add-paper swap + View Transitions + footer-badge flash (UPL-12 v0 + UPL-13 + UPL-22)

**Description.** Ship the three e4 polish items now that both spikes have
returned PASS. The roadmap-AC scope is **narrowed by both spikes** vs the
original e4 sketch:
- **UPL-12 v0 narrowed to add-paper only** (per m2 final-report
  challenger MAJOR finding) — convert ONE legacy `location.reload()`
  flow (`POST /ui/api/notebooks/{slug}/papers` URL-paste in
  `notebook_detail.html:~97`) to an in-place htmx swap that returns a
  `<tr>` fragment appended to `#papers-tbody`. The other two legacy
  flows (create-notebook, remove-notebook) stay on `location.reload()`
  in m4 v0; converting them is a future m5 (each new fragment endpoint
  gets its own Spike-2 pre-flight check pass).
- **UPL-13 simplified to a 1-LOC config flag** (per Spike-1) — add
  `htmx.config.globalViewTransitions = true;` to the existing inline
  JSON-shim block in `base.html`. htmx 2.0.10 calls
  `document.startViewTransition()` internally; no user-JS wrapper, no
  audit-widening, no new `htmx.swap()` re-entry call site.
- **UPL-22 unchanged** — CSS-only `.status-badge` `min-width: 14ch`
  for footer reflow stability + a brief `.htmx-settling` flash keyframe
  on swap-in (gated by m1's `prefers-reduced-motion: no-preference`).

**Pre-flight checklist (Spike-2 — load-bearing AC the adversary critic verifies).**

*Server-fragment correctness (issue #9 open Q5):*
- [ ] The new add-paper HTML fragment branch uses `html.escape()` for every interpolated value (pattern-match `_paper_row_html` at `server/routes/notebooks.py:1575-1604`).
- [ ] Zero `| safe` filters or `Markup(...)` calls anywhere in the new code OR existing templates. Verify by grep.
- [ ] Content-negotiation on `HX-Request: true` header routes browser-htmx requests to the fragment branch; curl / non-htmx clients still get the existing JSON body.
- [ ] The fragment renderer interpolates ONLY validated, escaped, server-controlled values — never raw request body or header values.

*Middleware integrity (issue #9 open Q1):*
- [ ] `SecFetchSiteMiddleware` carve-out at `("/ui",)` unchanged (`git diff server/middleware.py` should have zero hunks in the m4 implementation commit).
- [ ] Origin + Host loopback validation unchanged.
- [ ] `CONTENT_SECURITY_POLICY_UI` unchanged (no `'unsafe-eval'`, no new `connect-src`, `frame-ancestors 'none'` preserved).

*Input validation invariants (issue #9 open Q3):*
- [ ] `validate_slug` called at every new mutation entry-point before the renderer constructs the fragment.
- [ ] `is_valid_arxiv_paper_id` rejects unparseable URLs before any server-side state mutation.
- [ ] Pydantic `Field(max_length=...)` bounds on the URL-paste payload model unchanged.

*Test surface:*
- [ ] **XSS payload injection test** at `tests/test_ui_m4_fragment_xss.py` (or sibling): send `display_name = '<img src=x onerror=alert(1)>'` through the new HX-Request branch; assert the rendered HTML contains `&lt;img` not `<img`.
- [ ] **Content-negotiation test**: send the same request with and without `HX-Request: true`; assert JSON response vs `text/html` `<tr>` fragment.
- [ ] **Slug-validation gate test**: send a path-traversal slug (e.g. `../../../etc/passwd`); assert 422 BEFORE the renderer is reached.

**Acceptance criteria.**

- [ ] **UPL-12 v0** — `POST /ui/api/notebooks/{slug}/papers` URL-paste handler in `server/routes/notebooks.py` returns an HTML `<tr>` fragment when `HX-Request: true` header is present (content-negotiation); existing JSON branch preserved for curl/non-htmx clients. The form in `frontend/templates/notebook_detail.html:~97` switches `hx-on::htmx:after-request="location.reload()"` to `hx-target="#papers-tbody" hx-swap="beforeend"` (with `aria-live="polite"` on the tbody — m1 already adopted that). Reuse `_paper_row_html` or extend it; per Spike-2 the existing helper is the correct precedent.
- [ ] **UPL-13** — add `htmx.config.globalViewTransitions = true;` to the existing inline `<script defer>` block in `frontend/templates/base.html` (within the existing `'unsafe-inline'` CSP allowance — zero CSP change). Per Spike-1, this enables `document.startViewTransition()` automatically on every htmx swap; htmx's internal `if (document.startViewTransition)` guards graceful Firefox no-op. NO `htmx:beforeSwap`-wrapper code (that was an obsolete htmx-1.x pattern).
- [ ] **UPL-13 — optional CSS duration override** (recommended): add
    ```css
    @media (prefers-reduced-motion: no-preference) {
      ::view-transition-old(root), ::view-transition-new(root) {
        animation-duration: 200ms;
      }
    }
    ```
    to `frontend/static/app.css`. Default crossfade is ~250ms; 200ms keeps the operator console snappy. Gated by m1's `prefers-reduced-motion` discipline.
- [ ] **UPL-22** — extend `.status-badge` rule in `app.css` with `min-width: 14ch` so the footer doesn't reflow across DEGRADED/WARN/OK/DOWN/ops-warn state changes. Add a `.htmx-settling` flash keyframe on `#status-badge` (~400ms ease-out, gated by `prefers-reduced-motion: no-preference`).
- [ ] **The Spike-2 pre-flight checklist above** (13 items) is satisfied. The m3-pattern regression-test file `tests/test_ui_m4_*.py` covers them mechanically.
- [ ] **All 61 m1+m2+m3 tests still pass.** Specifically: `tests/test_ui_a11y_baselines.py` (23) + `tests/test_ui_m2_polish.py` (18) + `tests/test_ui_m3_dark_and_htmx_feedback.py` (20). m4 adds new test file(s) but modifies zero existing assertions.
- [ ] **Verification — manual cross-browser walk** (Chris pre-KR-4): click "Add by URL" with a real arXiv URL on Chrome + Safari on macOS; observe (a) no full-page flash (UPL-12 working), (b) a smooth ~200ms crossfade of the new `<tr>` (UPL-13 working on Chrome+Safari; Firefox no-ops cleanly). Click "Remove notebook" in a different session; the OLD `location.reload()` flow STILL fires (m4 v0 didn't convert that — flag for m5).
- [ ] **Verification — VoiceOver smoke-test** (Chris pre-KR-4): the new paper-row append should announce via the `#papers-tbody` `aria-live="polite"` region (m1's UPL-3 swap-target a11y).
- [ ] **Verification — issue #9 hygiene**: m4 does NOT close issue #9 (the full audit remains open as a separate effort). m4's implementation-summary should note that the pre-flight checklist was satisfied INSIDE m4's scope (not the full audit).
- [ ] Final `frontend/static/app.css` line count ≤ 330 (current 306 + budget ~20 for the View-Transitions duration override + UPL-22's `min-width` + flash keyframe). The m3-rect-revised cap of 330 has just enough room.

**Dependencies.** epic `ui-attractive-polish-e4`. **Hard prereqs (now shipped):** m1's `prefers-reduced-motion` gate (anchors the spin keyframe + the UPL-22 flash gate); m2's `color-mix()` adoption (UPL-22's flash keyframe uses `color-mix(in oklab, var(--accent) 30%, transparent)` per the original synthesis); m3's `.htmx-request` styling (the new add-paper button gets m3's in-flight feedback automatically — confirms the m3 + m4 stack composes cleanly). **Both spikes PASS** (Spike-1: htmx native View Transitions; Spike-2: e4 pre-flight checklist defined). **Issue #9** stays open as a separate effort; NOT a m4 dependency.

**Complexity.** M (~ 1–2 days execution including the 4-phase milestone-pipeline). Largest time slices: (a) the new add-paper fragment handler + content-negotiation branch + 3 new tests for the pre-flight checklist, (b) the manual cross-browser View Transitions verification.

**Specialist suggestion.** `security-reviewer` — see `.claude/skills/roadmap/references/specialist-contracts.md`. UPL-12 introduces a new server-side fragment-rendering branch and the Spike-2 pre-flight checklist explicitly invokes security-correctness axes (XSS, content-negotiation, input-validation gates). The adversary critic should run with the `security-reviewer` lens engaged for the m4 critique. UPL-13 + UPL-22 do not need specialist attention (Spike-1 confirmed zero audit-widening; UPL-22 is CSS-only).

---

## Phase 4 — Materialize

### Validation

- `validate-roadmap.py`: **pass** (`OK: ui-attractive-polish-roadmap.md valid (phases populated: Refine, Decompose, Sequence)`)
- Must-cap: **25.0%** (≤ 60% — comfortable headroom; e3 could promote to Must if a discovery finding warranted it)
- All Now-lane milestones have AC: **yes** (m1: 7 AC items including 2 verification gates; m2: 8 AC items including mobile-screenshot evidence)
- Slug format valid: **yes** (`ui-attractive-polish` matches `^[a-z][a-z0-9-]{2,30}$` and does not match `^e\d+$`)

### GitHub tickets

Not requested (no `--github` flag). To bundle epic + story bodies for
`gh issue create`, re-invoke as
`roadmap ui-attractive-polish --github`. Per project policy, the skill
will write the bundle but never invoke `gh` itself.

### Next step

**m1, m2, m3 are all shipped + both spikes returned PASS** (see the
"Shipped" section and the marked-complete Spike-lane entries under
Phase 3 — Now / Next / Later above). The current Now-lane milestone
is **`ui-attractive-polish-m4`** (In-place add-paper swap + View
Transitions + footer-badge flash, bundling UPL-12 v0 + UPL-13 +
UPL-22). To execute it end-to-end via the 4-phase milestone-pipeline
(research → implement → critique → rectify), run:

    /milestone-pipeline ui-attractive-polish-m4

This skill will not invoke milestone-pipeline. Cache stays warmer if
you start the milestone-pipeline session within 5 minutes of this
roadmap completing.

**The m4 brief is materially simpler than the original e4 sketch.**
Both spikes returned PASS and narrowed the work:

- **Spike-1**: UPL-13 dropped from S effort + audit-widening to **XS
  (1 LOC config flag)** — htmx 2.0.10 has native View Transitions
  integration. No `htmx:beforeSwap` wrapper, no `htmx.swap()`
  re-entry, no new inline-JS audit surface. Just
  `htmx.config.globalViewTransitions = true;`.
- **Spike-2**: UPL-12 ships in m4 v0 (add-paper only) with the
  **e4 pre-flight checklist** as load-bearing AC — 13 mechanically
  verifiable items the milestone-pipeline adversary critic checks
  during Phase 3 (server-fragment correctness, middleware integrity,
  input validation, test surface). Issue #9 (the full UI audit) stays
  open as a separate effort; it is NOT a m4 dependency.

After `m4` ships, the next decision point is **m5** — a future
follow-on bundling the v1 deferred items:

- **UPL-12 v1**: convert create-notebook + remove-notebook flows
  (each new fragment endpoint gets its own Spike-2 pre-flight check
  pass).
- **UPL-8 v1**: dark-mode `.status-badge--*` modifier remap +
  `th { background }` dark surface + freshness color (descoped from
  m3 per the challenger v0/v1 split).
- **UPL-19 v1**: `body { max-width: clamp(640px, 92vw, 1400px) }`
  wider-monitor expansion (descoped from m2).

Re-invoke `/roadmap ui-attractive-polish` after m4 ships to slice
e4 v1 into m5 (or to wind down the roadmap if the m5 polish doesn't
justify another milestone).

### Parallel bug-fix track (not in this roadmap)

Per the Won't list and the final-report §5 Track E, the three CRITICAL
bugs from the visual scout (UPL-5 silent rename failure, UPL-6 raw-JSON
preview empty-state, UPL-7 raw-JSON SecFetchSiteMiddleware rejection)
ship as **independent `/milestone-pipeline` invocations**, NOT as part
of this roadmap. Suggested kickoffs (run any time, no roadmap-dep):

    /milestone-pipeline ui-rename-422-fix-bm1     # UPL-5 (reproduce-first per challenger)
    /milestone-pipeline ui-preview-empty-bm2      # UPL-6
    /milestone-pipeline ui-secfetch-html-bm3      # UPL-7 (consider the FastAPI-exception-handler v0 split per challenger)

These are fix-anyway items: their RICE scores are low (R bounded to
specific routes) but they erode shipped behavior. Bundle them with this
roadmap's polish milestones only if/when the operator chooses to.

---

<!-- end:roadmap -->
