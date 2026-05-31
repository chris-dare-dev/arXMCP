# Motion + visual-effect vocabulary

**Purpose:** a curated reference so every scout speaks the same language when
proposing motion / animation / interaction upgrades. Cite by name (e.g.
`[MOT-3 stagger-reveal]`) in briefs and synthesis catalogs.

This file is loaded by scouts and by the synthesizer at phase start. It is
NOT a tutorial — it's a vocabulary table.

**arXMCP framing:** every implementation hint below assumes the no-build-chain
lock (CLAUDE.md §4.7) — pure CSS, vanilla JS, or htmx swap behaviour. Anything
proposing a React/Framer/Tailwind/shadcn implementation is automatically a
Phase-3 BLOCKER. Examples are drawn from arXMCP's actual surface (notebooks,
papers, freshness signals, status badge, htmx swaps) — NOT from a finance /
SaaS / marketing context.

---

## 1. Entry / exit primitives

| ID | Name | Description | When to use | Reduced-motion gate |
|---|---|---|---|---|
| MOT-1 | `fade-in` | Opacity 0 → 1 over 200–400ms | Default for any element appearing in-place | Wrap the `@keyframes`/`transition` in `@media (prefers-reduced-motion: no-preference) { … }` |
| MOT-2 | `fade-up` | Opacity 0→1 + `translateY(8px → 0)` over 250–400ms | Below-the-fold sections appearing on scroll | Combine with native `animation-timeline: view()` or IntersectionObserver |
| MOT-3 | `stagger-reveal` | Sequence of `fade-up` with 50–80ms inter-item delay | Notebook list / paper list landing on the screen | CSS `animation-delay: calc(var(--i) * 60ms)` per row via custom property; OR htmx `:after-swap` + a small CSS class |
| MOT-4 | `scale-in` | Opacity 0→1 + `scale(0.96 → 1)` over 200–300ms | Modal / popover / drawer entry (the native `<dialog>` element pairs well) | Pair with backdrop fade |
| MOT-5 | `slide-from-edge` | `translateX(±100% → 0)` over 250–350ms | Side panel / sheet entry — pair with native `popover` attribute | Disable on `prefers-reduced-motion: reduce` |
| MOT-6 | `dissolve` | Cross-fade between two elements in the same slot | htmx swap of a fragment; replace `swap-mode` default with a CSS-transitioned class | Use View Transitions API where supported |

## 2. Continuous / ambient motion

| ID | Name | Description | When to use | Caveats |
|---|---|---|---|---|
| MOT-10 | `breathing-glow` | Box-shadow or opacity slow pulse, 2–4s loop | Live indicators (the `/ui/status-badge` `ok` state, an "ingest in progress" row) | Cap intensity; respect `prefers-reduced-motion`; pause when tab not visible (`Page Visibility API`) |
| MOT-11 | `gradient-shift` | Hue rotation or conic-gradient angle drift, 8–20s loop | Status badges for highlighted state, freshness-timestamp accent | GPU-friendly; pause off-screen via IntersectionObserver |
| MOT-12 | `cursor-tracking-spotlight` | Radial gradient that follows pointer | Card hover affordance — arXMCP's notebook tiles could use this; mouse-position tracked via `mousemove` + CSS custom properties | Disable on touch / reduced-motion |
| MOT-13 | `skeleton-shimmer` | Diagonal sheen across skeleton bg | Loading placeholders (htmx request-in-flight rows; pre-poll status-badge state) | Pair with `loading-states` htmx extension if vendored |
| MOT-14 | `data-tick-flash` | Brief color flash on numeric value change | Freshness timestamp updates; paper count after htmx swap | Use `@keyframes flash` triggered via JS adding/removing a class on swap |

## 3. Scroll-driven

| ID | Name | Description | Implementation | When to use |
|---|---|---|---|---|
| MOT-20 | `parallax-bg` | Background layer moves slower than foreground | Native CSS `animation-timeline: scroll()` (Chrome / Safari 26, Baseline Widely-Available) | Avoid on data-dense routes (`/ui/notebooks/<slug>`); only acceptable on a future landing/marketing surface, which arXMCP does NOT currently have |
| MOT-21 | `progress-bar-by-scroll` | Sticky header gets a progress bar reflecting page-scroll position | `animation-timeline: scroll(root block)` + a fixed `<progress>` element | Long preview pages (the ar5iv `/ui/notebooks/<slug>/papers/<id>/preview` route) |
| MOT-22 | `pinned-section-reveal` | Section pins while inner content scrolls | CSS `position: sticky` + `animation-timeline: view()` | Multi-step explanatory content (currently arXMCP has none of this kind of surface) |
| MOT-23 | `image-stack-cycle` | Vertical scroll cycles through a layered image stack | Native scroll-driven CSS animation timeline | Niche — would only fit a future help/docs surface |
| MOT-24 | `scroll-triggered-counter` | Number counts up when an element enters viewport | `animation-timeline: view()` + CSS `@property` for animatable custom property — OR small vanilla-JS IntersectionObserver | Notebook counts / paper counts on landing (`index.html`) |

## 4. Pointer / hover / focus

| ID | Name | Description | When to use |
|---|---|---|---|
| MOT-30 | `lift-on-hover` | `translateY(-2px)` + shadow elevation | Interactive cards (notebook tiles on `index.html`, paper rows on `notebook_detail.html`) |
| MOT-31 | `magnetic-cursor` | Element nudges toward cursor within X px | Brand/landing CTAs only — NEVER on operator-console buttons (would feel like jank in a notebook-management workflow). arXMCP has no eligible surface today. |
| MOT-32 | `border-on-hover` | Border color shift or gradient-border reveal | Notebook tiles, primary-action buttons — uses `--accent` |
| MOT-33 | `icon-spin-on-action` | Refresh / loading icons rotate 360° once on action trigger | `/ui/status-badge` refresh affordance, the "ingest" button while htmx request is in-flight |
| MOT-34 | `focus-visible-glow` | Subtle accent border / outline glow on `:focus-visible` | Accessibility-required focus rings (arXMCP has NONE today; this is a baseline gap to close before any decorative motion lands) |

## 5. Drag / gesture

| ID | Name | Description | When to use | Caveat |
|---|---|---|---|---|
| MOT-40 | `drag-to-reorder` | List items dragged with rearranging visual feedback | Future: reordering papers within a notebook | Vendor a single-file vanilla-JS lib (e.g. `sortable.js`) — NOT a framework-tied solution |
| MOT-41 | `swipe-to-action` | Mobile gesture revealing actions per row | Mobile-only paper-row actions | Single-operator loopback may de-prioritize mobile entirely — flag explicitly |
| MOT-42 | `pinch-zoom-canvas` | Two-finger zoom on a canvas surface | arXMCP has no canvas surface today; out of scope |
| MOT-43 | `drag-time-scrubber` | Horizontal drag scrubs a timeline | arXMCP has no time-series surface today; out of scope |

## 6. Page-transition primitives

| ID | Name | Description | When to use |
|---|---|---|---|
| MOT-50 | `htmx-swap-fade` | Cross-fade an htmx-swapped fragment via CSS class transitions | Default for `hx-swap` targets (`/ui/status-badge`, in-page rename/delete) |
| MOT-51 | `shared-element-transition` | Element morphs from list position to detail-view position | Notebook tile → notebook detail; paper row → preview pane |
| MOT-52 | `view-transitions-api` | Native `document.startViewTransition()` for full-page swaps | Chrome / Safari (Baseline Widely-Available for same-document); pairs with htmx via `hx-on::after-swap` |

## 7. Decorative / brand-feel

| ID | Name | Description | When to use | Caveat |
|---|---|---|---|---|
| MOT-60 | `mesh-gradient-bg` | SVG mesh gradient | Hero / landing only — arXMCP has no landing surface today | Heavy on first paint; precompose as a static SVG |
| MOT-61 | `noise-overlay` | Subtle SVG-noise texture over gradient | Background warmth | 2-4% opacity max |
| MOT-62 | `aurora-effect` | Multi-layer radial gradients animating opacity | "Help / about" surface if added | Off by default with reduced-motion |
| MOT-63 | `border-beam` | Animated gradient sweeping along a card border | Highlighted card / "what's new" badge | Cap to 1–2 instances per viewport |
| MOT-64 | `dot-grid-bg` | Subtle dot grid background | Background pattern for a future landing surface | Pair with cursor-tracking spotlight |
| MOT-65 | `floating-orbs` | Blurred gradient orbs drifting behind content | Hero background warmth (landing-only) | Pause off-screen; GPU-cheap |

## 8. Anti-patterns (do NOT propose)

| ID | Name | Why it's an anti-pattern |
|---|---|---|
| MOT-NO-1 | `bouncy easing on status / numeric data` | Bouncy/elastic curves on freshness timestamps, paper counts, or status badges look unstable — undermines operator trust |
| MOT-NO-2 | `parallax on the operator console` | Operators want stillness; parallax on `/ui/` or `/ui/notebooks/<slug>` causes motion sickness reports and adds zero information |
| MOT-NO-3 | `auto-rotating carousel for notebook content` | Operators must control what they see; auto-advance loses information |
| MOT-NO-4 | `magnetic-cursor on operational buttons` | Ingest / Delete / Rename / Upload buttons must NOT move toward the cursor — accidental-click risk on destructive actions |
| MOT-NO-5 | `continuous animation without prefers-reduced-motion fallback` | Categorical a11y regression. arXMCP's CSS today has ZERO `prefers-reduced-motion` blocks — adding the gate is a baseline prerequisite for any other motion candidate |
| MOT-NO-6 | `npm-installable animation library (Framer Motion / GSAP-pro / react-spring / motion / auto-animate)` | Violates CLAUDE.md §4.7 (no-build-chain). Use pure-CSS / native scroll-driven / View Transitions API / vendored single-file vanilla-JS instead — automatic Phase-3 BLOCKER otherwise |
| MOT-NO-7 | `confetti / celebration animations on operator actions` | Misaligned with research-tool tone; an operator finishing an ingest is not a gamification event |
| MOT-NO-8 | `decorative motion on destructive flows` | Delete-confirm, error states, recovery flows must remain visually quiet — motion here erodes the seriousness of the action |

---

## How to cite in a brief or candidate

In a scout brief, when proposing an upgrade that uses one of these primitives,
cite it by ID + name:

> "On `index.html`'s notebook tiles, apply `[MOT-30 lift-on-hover]` paired
> with `[MOT-32 border-on-hover]` using `--accent`. Both gated by
> `@media (prefers-reduced-motion: no-preference)` since arXMCP's CSS
> currently has NO reduced-motion block — adopting one is itself a prerequisite
> candidate."

In the Phase 2 synthesis catalog, each candidate's "Sketch" section calls out
the motion primitives it composes and the vendor-free implementation:

> **Sketch:** Apply `[MOT-3 stagger-reveal]` to the paper-list rows on
> `notebook_detail.html` with 60ms inter-row delay, implemented via CSS
> `animation-delay: calc(var(--i) * 60ms)` where `--i` is set inline per
> row in the Jinja2 loop. Pair with `[MOT-50 htmx-swap-fade]` on the htmx
> rename/delete swap targets. Zero new JS.

This shared vocabulary is the load-bearing thing that lets the synthesizer
dedupe across scout briefs ("library-scout cites the View Transitions API;
visual-scout cites *fade-on-swap of notebook tiles*; both are pointing at
`[MOT-50 htmx-swap-fade]` + `[MOT-52 view-transitions-api]`").
