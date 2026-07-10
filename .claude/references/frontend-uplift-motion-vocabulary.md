# Motion vocabulary — /frontend-uplift

Shared vocabulary so scouts and the synthesizer can dedupe across briefs ("library-scout cites Framer Motion + visual-scout cites 'list needs animation' both point at `[MOT-3 stagger-reveal]`"). Every motion candidate in a scout brief MUST cite the `[MOT-N <name>]` token from this file.

If a scout proposes a NEW motion primitive not in this list, append it (next `[MOT-N+1]`) AND cite the source library. Memory accumulates this way across runs.

**Two motion languages.** This file (`MOT-*`) is the **tool/dashboard** motion language — restrained,
fast, functional. The **experiential / award-tier** motion language (`EXP-*` — parallax, smooth-scroll,
scroll-scrub/zoom, cursor-reactive frames, deterministic preloaders, WebGL galleries, image-masked type,
dynamic recoloring) lives in the companion `.claude/references/frontend-uplift-experiential-motion.md`. Read §0 below to
decide which language a surface speaks BEFORE proposing motion.

**Surface substrate (web vs non-web).** The library exemplars and code idioms in this file assume a
**web** surface (React / RSC / CSS / a JS bundler). The *doctrine* — the motion-jobs test (§0), the
surface budget (§0), the anti-patterns (§8), token discipline (§9) — is substrate-independent and
governs every frontend. But where a row names a web library (Framer Motion, Radix, Tailwind) or a
bundler concern, a reader on a **non-web** surface (a PySide6/Qt desktop app, a Jinja2+htmx
server-rendered console) should read the *job* the primitive serves and map it to that platform's own
animation facility (e.g. Qt `QPropertyAnimation`/`QVariantAnimation`, CSS transitions in the htmx
console), not import the library. The web specifics stay in the file; they simply do not apply off-web.

## §0 — Surface-type model (decide this FIRST — it gates §8 anti-patterns)

Every motion candidate carries a **surface tag**. The same primitive can be encouraged on one surface and
a BLOCKER on another.

| Surface | What it is | Examples | Motion budget |
|---|---|---|---|
| **S-1 experiential** | Marketing/brand/story; motion IS the product | landing, hero, brand, portfolio, launch pages | `EXP-*` encouraged (with perf + a11y gates); `MOT-*` too |
| **S-1m experiential moment** | An experiential surface inside a tool app | public login/signup, onboarding, marketing/pricing, empty-first-run, a success celebration | scoped `EXP-*` on that surface only — must not leak into the data UI |
| **S-2 tool / dashboard** | Data, controls, dense info, repeat use | admin dashboards, data grids, settings, monitoring (internal admin consoles, operator dashboards) | `MOT-*` only; `EXP-*` and §8 AP-1/2/3/5 are BLOCKERs |

Full model + the `EXP-*` token catalog + modern-code recipes: `.claude/references/frontend-uplift-experiential-motion.md` §1–§7.
**Unconditional on EVERY surface (S-1 included):** `prefers-reduced-motion` honored, no motion that
obscures (AP-6) or blocks-click (AP-7), WCAG 2.2 AA, no auto-playing audio.

**The motion-jobs test (round 3 — THE home of this rule; replaces the old per-run quota):**
every motion candidate names which of the four jobs it does — **orientation** (where am I /
what moved), **causality** (this happened because of that), **feedback** (your action
registered), **continuity** (the same object persists across a change). **No named job = no
motion.** Entry fades, initial-load number tweens, ambient glow, and stagger for its own sake
do not satisfy this test. The absence of an animation dependency is NOT itself a design gap —
it is a gap only when named jobs go unserved; then prefer native CSS / incumbent capability
first, and reach for a lib (default lightweight engine: **anime.js** — tree-shakeable, 0-dep)
only when a named job needs it. Static-monoculture remains a *named gap class* precisely so
frozen UIs with unserved jobs get caught — but there is no quota to fill, and heavy
experiential motion (parallax/WebGL) stays an S-2 BLOCKER regardless of job.

## §1 — Entry motions

| Token | Name | Use for | Library exemplar |
|---|---|---|---|
| MOT-1 | fade-in | reveal-on-mount; simplest entry | Framer Motion `<motion.div initial={opacity:0} animate={opacity:1}>` |
| MOT-2 | slide-up | new content appearing below a fold | Framer / Tailwind transition |
| MOT-3 | stagger-reveal | list items reveal sequentially | Framer Motion `staggerChildren` |
| MOT-4 | scale-in | modal / dialog mount | Radix Dialog default |
| MOT-5 | blur-fade | hero image / glamour content | Custom Framer keyframes |
| MOT-6 | typewriter | text reveal char-by-char | `react-type-animation` |
| MOT-7 | reveal-on-scroll | content appears as it enters viewport | Framer Motion `useInView` |
| MOT-8 | shimmer-skeleton | loading placeholder before content arrives | Tailwind animate-pulse + custom gradient |

## §2 — Exit motions

| Token | Name | Use for |
|---|---|---|
| MOT-9 | fade-out | dismissed content |
| MOT-10 | slide-out | drawer close, sidebar collapse |
| MOT-11 | scale-out | modal dismiss |
| MOT-12 | crossfade | route transition |

## §3 — State change motions

| Token | Name | Use for |
|---|---|---|
| MOT-13 | layout-shift | element moves on layout change | Framer Motion `layout` prop |
| MOT-14 | shared-element-transition | element persists across routes | `viewTransition` API or Framer `layoutId` |
| MOT-15 | accordion-expand | disclosure widget | Radix Accordion |
| MOT-16 | tab-content-swap | tab panel changes | Framer Motion `AnimatePresence` |
| MOT-17 | toggle-switch | binary state | Tailwind transition + transform |
| MOT-18 | number-tween | counter / metric change | `framer-motion` `animate` with value driver |
| MOT-19 | chart-redraw | data viz update | Recharts / D3 `transition.duration` |
| MOT-20 | progress-fill | bar / ring progress | Framer `motion.path` |

## §4 — Hover / focus motions

| Token | Name | Use for |
|---|---|---|
| MOT-21 | hover-lift | card hover (translate-y + shadow) |
| MOT-22 | hover-glow | CTA emphasis |
| MOT-23 | focus-ring | a11y focus indicator (REQUIRED for all interactive elements) |
| MOT-24 | hover-color-shift | link / icon hover |
| MOT-25 | hover-scale | button press affordance |
| MOT-26 | tooltip-fade | hover tooltip reveal |
| MOT-27 | magnetic-cursor | cursor proximity attraction (use sparingly) |

## §5 — Continuous / ambient motions

| Token | Name | Use for | Anti-pattern note |
|---|---|---|---|
| MOT-28 | spinner | indeterminate loading | OK |
| MOT-29 | pulse | CTA attention, notification dot | OK |
| MOT-30 | bouncing-arrow | "scroll for more" affordance | OK in marketing, NOT in tools |
| MOT-31 | floating-orbs | ambient background | Marketing-only — avoid in data dashboards |
| MOT-32 | gradient-shift | hero background animation | Marketing-only |
| MOT-33 | particle-system | hero / loading | Marketing-only; bundle-size hit |
| MOT-34 | typing-cursor | "AI thinking" indicator | OK in chat UIs |
| MOT-35 | breathing | subtle scale loop on focused content | Use sparingly |

## §6 — Page / navigation motions

| Token | Name | Use for |
|---|---|---|
| MOT-36 | route-fade | inter-page transition (Next.js / SvelteKit / Astro) |
| MOT-37 | route-slide | mobile-app-like horizontal nav |
| MOT-38 | scroll-snap | section-by-section scroll |
| MOT-39 | parallax | depth on scroll | Marketing-only — avoid in tools |
| MOT-40 | sticky-header-shrink | header collapses on scroll |
| MOT-41 | sticky-element-reveal | TOC / sidebar appears on scroll |

## §7 — Microinteractions

| Token | Name | Use for |
|---|---|---|
| MOT-42 | button-press | tactile press feedback |
| MOT-43 | icon-morph | icon changes shape (e.g. play→pause) |
| MOT-44 | input-focus-grow | input expands on focus |
| MOT-45 | validation-shake | error feedback on form submit |
| MOT-46 | success-checkmark | form submit success |
| MOT-47 | drag-handle-feedback | drag-and-drop affordance |
| MOT-48 | swipe-action-reveal | mobile swipe-to-reveal |
| MOT-49 | long-press-radial | mobile long-press menu |
| MOT-50 | undo-toast | dismissible action confirmation |
| MOT-51 | scroll-carousel-rotate | card gallery: DOM rotateY+translateZ per card on scroll, depth stagger, no WebGL; anime.js 4.x `createScrollObserver` or IntersectionObserver + CSS `transform` on S-2-restrained surfaces with grid fallback for `prefers-reduced-motion` |

## §8 — Anti-patterns (CHALLENGER USES THESE AS BLOCKER TRIGGERS)

Motion primitives the challenger flags. **AP-1/2/3/5 are SURFACE-CONDITIONAL** (see §0): a BLOCKER on
S-2 tool/dashboard surfaces, but *in-budget* on S-1/S-1m experiential surfaces WHEN the experiential
gates are met (perf budget, reduced-motion poster, mobile fallback, contrast holds). **AP-4/6/7 are
UNCONDITIONAL** — they never relax, not even on S-1.

| Anti-pattern | Gating | Why it fails (S-2) | On S-1/S-1m |
|---|---|---|---|
| **AP-1** Parallax / scroll-driven scrub | conditional | Distracts from data; motion-sickness risk | OK as `[EXP-2/4/6]` with reduced-motion + perf gate |
| **AP-2** Auto-playing video | conditional | Bandwidth + a11y cost on data pages | OK muted+playsinline+poster on a hero; never auto-audio |
| **AP-3** Stagger-reveal > 8 items | conditional | Annoying after 3-4; first interaction shouldn't take 2s | OK as a one-shot S-1 entrance; never on a working list |
| **AP-4** `prefers-reduced-motion: ignore` | **UNCONDITIONAL** | Hard a11y violation; seizures / motion-sickness | Always honor on EVERY surface — disable or `MOT-1` fallback; WebGL → static poster |
| **AP-5** Animation > 500ms on interactions | conditional | Feels sluggish; tools respond instantly | OK for a branded S-1 entrance / scroll-scrub; NOT for click feedback anywhere |
| **AP-6** Motion that obscures content | **UNCONDITIONAL** | Spinner over text being read | Use skeleton (MOT-8); never obscure on any surface |
| **AP-7** Motion that prevents click during animation | **UNCONDITIONAL** | Element animating in but unclickable | ms-fast (≤ 150ms) AND clickable from frame 1, every surface |

**Challenger rule:** before scoring axis 3, read the candidate's surface tag. On S-2, AP-1/2/3/5 are
BLOCKERs. On S-1/S-1m, re-frame axis 3 as "is this *budgeted*?" (perf / reduced-motion / mobile /
contrast) — see experiential-motion §1 + §7. A missing reduced-motion fallback is a BLOCKER on ALL surfaces.

## §9 — Token discipline (CHALLENGER USES THIS)

All motion durations MUST reference design-system tokens, not hard-coded ms values. Acceptable:

```
duration-fast    (100ms)  — microinteractions
duration-normal  (200ms)  — most state changes
duration-slow    (300ms)  — page transitions
duration-brand   (500ms)  — hero / branded entrance
```

Hard-coded `transition-duration: 367ms` is a MAJOR finding (token discipline violation). Custom durations must be added to the token system FIRST.

## §10 — Library compatibility matrix

**Last-verified:** 2026-06-17 (GSAP-free + anime.js bundle re-measure) — claims here feed
challenger axes 5/10; re-verify per source-registry §0 triggers (T2/T3) when stale or relied on.

| Library | React 19 ready (2026) | RSC compatible | Bundle size (min+gzip) | License | Motion tokens covered |
|---|---|---|---|---|---|
| Framer Motion | yes (`motion/react`) | partial (Server Components require shim) | ~40 KB | MIT | MOT-1..50 |
| GSAP (core + plugins) | yes (`@gsap/react` `useGSAP`) | no (client-only) | ~25 KB core / ~70 KB +ScrollTrigger | **FREE — all commercial (Webflow 2025; SplitText/ScrollTrigger/etc. now free)** | MOT-1..50 + EXP-2..6,8,10 |
| auto-animate (FormKit) | yes | yes | ~2 KB | MIT | MOT-3, MOT-13 |
| Motion One | yes | yes | ~4 KB | MIT | MOT-1..30 |
| Tailwind CSS animate-* | n/a | yes | ~0 KB (utility classes) | MIT | MOT-1, MOT-2, MOT-28, MOT-29 |
| react-spring | yes | partial | ~15 KB | MIT | MOT-1..50 |
| Lenis | yes (`lenis/react`) | no (client-only) | ~3 KB | MIT | EXP-1 (smooth scroll) |
| Three.js / R3F / OGL | yes | no (`'use client'` + `dynamic ssr:false`) | ~150 / ~60 / ~8 KB | MIT | EXP-13, EXP-14 (WebGL) |
| **anime.js** (`animejs` 4.x) | yes (`createScope`) | no (client-only, `'use client'`) | **~14 KB gz** typical hook, ~26 KB full · tree-shakeable, 0 deps | **MIT** | MOT-3, 13, 18, 43, 46; EXP-20..25 |
| **Native CSS** (`animation-timeline`, `@property`, `background-clip:text`) | n/a | **yes (RSC-safe, 0 KB)** | 0 KB | — | EXP-2..6, 12, 15..18 |

Note 1 — **GSAP is now 100% free** (Webflow acquired GreenSock; the old "paid for commercial" belief is
obsolete). Do NOT flag GSAP as a license blocker. Note 2 — **native scroll-driven animations are NOT
Baseline** (Chrome/Edge 115+, Safari 26, **no Firefox**) → they need an `@supports` gate + IO fallback;
see experiential-motion §5. The challenger uses this matrix to flag MAJOR findings for "candidate
proposes GSAP/WebGL on a tool page" (client-only + bundle cost on an S-2 surface). Note 3 — **anime.js**
is the sanctioned lightweight tool-surface engine: tree-shakeable (`sideEffects:false`), 0-dependency, MIT
— a real `{animate,stagger,createScope}` hook is **~14 KB gz** (animate carries the engine), not a few KB — still light vs Framer ~40 KB / GSAP ~70 KB. It covers S-2 microinteractions (MOT-3/13/18/43/46) AND
experiential EXP-20..25; do NOT flag it as a bundle/license blocker (it is the §0 anti-monoculture default).

## §11 — Experiential cross-reference

The `EXP-*` tokens (experiential motion — parallax, smooth-scroll, scroll-scrub/zoom, preloaders, custom
cursor, WebGL galleries, image-masked type, dynamic recoloring) live in
`.claude/references/frontend-uplift-experiential-motion.md`. When a candidate is experiential, cite its `[EXP-N]` token (and
`[MOT-N]` if it overlaps tool-motion). The `frontend-uplift-experiential-scout` reverse-engineers
award-tier sites into these tokens; the challenger surface-gates them per §0 + §8.

## How to evolve this vocabulary

When a scout discovers a new motion primitive not in §1-§7, append it AT END OF RUN with the next `[MOT-N]` token + library source. New anti-patterns from challenger findings get appended to §8. This file IS the motion-pattern institutional memory across runs.
