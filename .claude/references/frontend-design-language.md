# Frontend design language — art direction before pixels

The canonical taste document for every frontend we build or restyle. It exists because
component-correct UIs kept shipping as **generic AI-generated dashboards** — dark navy shells, neon
accents, equal-weight card grids — that no amount of motion or library polish fixed. The failure was
never mechanics; it was the absence of an **art-direction decision**. This file makes that decision
mandatory, describable, and enforceable.

**Who consumes this file:**

| Consumer | When | How |
|---|---|---|
| `/frontend-design` skill | Any session building or restyling UI | Loads this file FIRST, runs the thesis-first workflow (§2) before writing code |
| `frontend-uplift-art-direction-scout` | Phase 1 of `/frontend-uplift` | Reads the repo house-thesis overlay (§9), reverse-engineers §4 references, produces thesis + 3 directions for the run |
| `frontend-uplift-challenger` | Phase 3 of `/frontend-uplift` | Axis 11 (distinctiveness) scores candidates against §5 bans + §10 rubric |
| `milestone-frontend-ux` critic | `/milestone-pipeline` Phase 3 on frontend diffs | Cites §5 BAN tokens + §10 score when the diff ships template-default UI |

Surface classes (S-1 / S-1m / S-2) are defined in `.claude/references/frontend-uplift-motion-vocabulary.md`
§0 and reused here unchanged. Motion recipes live in
`.claude/references/frontend-uplift-experiential-motion.md`; this file owns
**composition, typography, color/material, data-viz, chrome, and voice**.

---

## §1 — The anti-reference: "generic AI dashboard" (what we are stopping)

The named failure mode, observed over and over in shipped product screens — a stock
security/settings dashboard assembled from defaults, and "command center" concept comps that theme a
template rather than direct it. It is not bad because it is dark; it is bad because it is
**undirected** — assembled from defaults, with no thesis. Recognize it by these tells:

1. Dark **navy** shell (`#0B1220`-family) with 3+ neon accents (electric blue / green / purple / orange).
2. Sidebar + topbar + a grid of 6+ equal rounded cards as the entire identity.
3. Icon-in-rounded-square tiles used as decoration on every card.
4. Untouched default stack look: Inter everywhere, stock Lucide strokes, default shadcn radius/border/shadow on every element.
5. Everything the same visual weight — no lede, no focal point, nothing to read first.
6. Decorative charts: legend-donuts, unlabeled sparklines, bar charts with no threshold or annotation.
7. Badge/chip soup — colored status pills scattered across every row and card.
8. Glow borders, gradient blobs, glassmorphism with no layering rationale.
9. "Welcome back, Administrator" hero + 4 KPI stat cards + "Quick Actions" — the template page-opener.
10. Cosplay copy ("MISSION TIME", "Command Center") over specific, honest instrument labels.

A UI can be **clean, consistent, accessible — and still be this**. Correctness is not direction.

---

## §2 — The mandate: thesis before pixels

Before proposing components, libraries, or motion for ANY net-new surface or restyle, produce the
six deliverables. No exceptions for "small" restyles — a thesis can be one sentence; skipping it is
how template output happens.

1. **Visual thesis** — one sentence tying the product's domain to a visual idea.
   (Test: swap in a competitor's product name. If the sentence still works, it is not a thesis.)
2. **Three divergent directions** — per §8 shape: concept, where it applies, where it must NOT
   apply, 5 concrete traits, 5 banned traits, a11y/perf risk notes. Divergent means a viewer could
   not mistake mockups of one for another.
3. **Negative-reference list** — which §5 BAN tokens this work specifically avoids, plus any
   project-specific anti-references (link screenshots when they exist).
4. **Surface map** — every route/view in scope tagged S-1 / S-1m / S-2 (motion-vocabulary §0).
5. **Design-language contract** — the chosen direction resolved into tokens BEFORE code:
   type faces + scale, spacing rhythm, color/material tokens, border/elevation method, iconography
   treatment, data-viz rules, motion budget per surface, voice rules.
6. **Cookie-cutter risk score** — §10 rubric on the current state AND the proposed end state.

**In interactive sessions**: present the thesis + 3 directions and let the user pick (AskUserQuestion
with a recommended default). **In autonomous runs**: pick the strongest defensible direction, state
the choice and why, and proceed — never silently default to the template look.

---

## §3 — Surface classes gate the language

| Class | Surfaces | Design language budget |
|---|---|---|
| **S-1** experiential | marketing, landing, brand, docs-home, 404 | Full editorial + cinematic craft: display type, full-bleed media, scroll choreography, WebGL — with the unconditional a11y locks (reduced-motion, contrast, no obscuring) |
| **S-1m** experiential moment | login, signup, onboarding, getting-started, empty-first-run, success/celebration | Scoped cinematic moments with a fast path through; must not leak into the working UI |
| **S-2** tool | dashboards, tables, settings, ops consoles — every repeat-use view | §6 premium-instrument language. NO spectacle: borrow award-site **discipline** (hierarchy, type, whitespace, authored transitions), never their scroll theater (AP-1/2/3/5 are challenger BLOCKERs here) |

The most common taste failure is applying one language everywhere: brochure motion inside dashboards,
or dashboard austerity on the login. Split the surfaces first (§2 deliverable 4), then style each in
its own language — one brand, two dialects.

---

## §4 — Reference library (what "good" looks like, and the one lesson each teaches)

Canonical inspiration set (Chris-curated, 2026-07-06). Copy lines marked ✓ were fetched from the live
sites on 2026-07-06; visual traits are characterized from the sites' known design language — re-verify
with live-recon (Claude-in-Chrome) when a run leans hard on one. **Adapt the trait, never clone the
site**: these are mostly S-1 studio/marketing sites; §6 translates their discipline to S-2.

| # | Site | Visual thesis | The transferable lesson |
|---|---|---|---|
| REF-1 | `metalab.com` | Extreme restraint, sharp concept | ✓ "We make interfaces" — one massive declarative statement + numbered drag gallery ("HoverDrag", items 01–24). Memorable via ONE sharp idea, not density. Confidence comes from what you leave out. |
| REF-2 | `waabi.ai` | Technology as cinematic story | ✓ "Built to think. Born to haul." / "We built our own road." Full-bleed imagery, short declarative sentence pairs, generous section pacing. Serious deep-tech ≠ neon; it reads as calm conviction. |
| REF-3 | `new.studio` | Refined brand system, serif confidence | ✓ "Transforming Brands, Building Futures" / "We exist to make the new possible." Title-case editorial headlines, serif/italic contrast, whitespace as a status signal. |
| REF-4 | `newgenre.studio` | Editorial pacing, poetic precision | ✓ "Our work, from petal to planet" / "accelerating tomorrow's ideas." Case-study rhythm: eyebrow → headline → evidence. Quiet premium restraint with personality in the copy. |
| REF-5 | `filter.im` | High-contrast editorial density | ✓ "The studio behind the world's leading companies." / "High stakes, high speed. That's Filter." Dense image choreography WITH strong hierarchy — density is authored, not accidental. Minimal nav (Index / Studio / Connect). |
| REF-6 | `ponder.ai` | Dark cinematic product UI done right | ✓ "Video Editing, Reinvented" / "Let your ideas flow. Ponder it." Dark works when it is product-specific, media-rich, and single-accent — not when it is navy + rainbow neon. |
| REF-7 | `sohub.digital` | 3D/media-led hero, cinematic visuals | ✓ "Your story builds our history." / "Don't be shy." Hero media carries the brand; UI chrome nearly disappears. For our S-1 surfaces only. |
| REF-8 | `trionn.com` (incl. `/404`) | Playful bespoke identity | Even the 404 is an authored brand moment (served as a real 404 — error pages as craft). Every state — errors included — is designable. Feeds the branded-error-screen doctrine. |
| REF-9 | `save.design` | Product polish in a focused tool | ✓ "Organize your design inspiration." Small-surface tool where interaction quality IS the brand. Polish concentrated on the core loop, not spread thin. |

**Proposed references (unreviewed)** — agents append candidate sites HERE (full trait
protocol + evidence marks + run id); a human promotes to a numbered REF entry or deletes.
*(none pending)*

**Trait extraction protocol** (art-direction-scout, and anyone adding REF-10+): for each site record
(a) visual thesis in one sentence, (b) typography posture (faces, scale contrast, casing), (c) layout
rhythm (grid, asymmetry, pacing), (d) color/material language, (e) imagery/media strategy, (f)
interaction grammar (what motion means), (g) what makes it recognizable at a glance, (h) the ONE trait
worth adapting here — tagged to a surface class.

---

## §5 — The ban list (anti-cookie-cutter blockers)

Cited as `BAN-N` in briefs, syntheses, critiques, and reviews. On S-2 proposals these are hard
challenger findings (Axis 11): a proposal that INTRODUCES or PRESERVES-AS-IDENTITY any of these
without a named, product-specific reason is flagged.

| Token | Banned pattern |
|---|---|
| BAN-1 | Dark-navy shell + 2 or more neon accents (the "AI dashboard" cliché) |
| BAN-2 | Sidebar + topbar + grid of 6+ equal rounded cards as the page's primary identity |
| BAN-3 | Icon-in-rounded-square tiles as decoration (icon + heading + paragraph, repeated) |
| BAN-4 | Untouched default stack look — Inter + stock Lucide + default shadcn radius/border/shadow with no modification |
| BAN-5 | Equal visual weight across all panels — no lede, no focal element |
| BAN-6 | Charts as decoration — legend-donuts, unlabeled sparklines, no threshold/annotation/"so what" |
| BAN-7 | Badge soup — more than ~5 colored status chips visible per view |
| BAN-8 | Glow borders, gradient blobs, glassmorphism without a product-specific layering reason |
| BAN-9 | More than one primary CTA per viewport |
| BAN-10 | Generic-SaaS or cosplay copy — "Welcome back", "Quick Actions", "MISSION TIME" theatrics |
| BAN-11 | Semantic colors (ok/warn/crit) used decoratively, diluting their state meaning |
| BAN-12 | Marketing spectacle on an S-2 surface (parallax/WebGL/scroll-zoom in the working UI — also AP-1/2/3) |
| BAN-13 | The template page-opener: avatar + "Welcome, <name>" + row of KPI stat cards + Quick Actions |
| BAN-14 | Uniform medium density everywhere — no authored compact/comfortable intent per view |
| BAN-15 | **Same-silhouette syndrome** — another surface's (or a prior run's) shell, composition, and style recipe reused as this surface's identity without a product-specific reason. This explicitly includes this canon's own emergent house look (ink + violet wash + Space Grotesk/mono + numbered eyebrows + posture lede + hairlines + generous gaps + small motion flourishes): §6/§8 patterns are worked EXAMPLES of the invariants, and repeating their silhouette across unrelated surfaces is this tell (round-3 critique — the anti-cliché linter must not mint a new cliché) |

Legitimate exceptions exist (a sidebar is fine; a donut can be right) — the rule is that the choice
must be **argued from the thesis**, not inherited from the template. "The library default looks like
this" is never the reason.

---

## §6 — Premium instrument language (the positive spec for S-2 tool surfaces)

What replaces the banned patterns on dashboards and consoles. Borrow the reference sites' discipline —
hierarchy, typographic confidence, authored pacing — with zero spectacle.

**This section is ONE worked dialect, not the admissible set** (round 3). The invariants are
binding — hierarchy, honest data-viz, authored density, semantic color discipline, state-borne
motion; the *specific patterns* below (numbered eyebrows, posture lede, two-voice type,
hairline elevation) are examples of those invariants, not a page recipe. Reusing this
silhouette verbatim across unrelated surfaces is BAN-15. A direction that satisfies the
invariants through a different composition is not a deviation — it is the point.

**Typography (the #1 lever)**
- Two-voice system: a **display/UI face** with character + a **data voice** (mono or tabular).
  Inter-everywhere is the template tell; if Inter stays, it is body-only, with display moments carried
  by a distinct face and real scale contrast.
- Real scale contrast: meta 11–12px caps (tracked +4–8%), body 14–16px, section 20–24px, page title
  28–40px. Display sizes (56px+) belong to S-1/S-1m. Tight leading + slight negative tracking on
  large sizes.
- ALL numerals in data contexts are tabular (`font-variant-numeric: tabular-nums`) or mono.
- Editorial wayfinding: numbered section eyebrows (`01 — Runtime posture`) instead of icon tiles.

**Layout & hierarchy**
- ONE focal element per view — a lede module (2–3× the visual weight) answering the view's core
  question in 5 seconds; supporting modules are visibly subordinate. Max 2 card sizes per view.
- Asymmetric, grid-true composition (12-col, generous gutters) over uniform card grids; whitespace
  is structure, not absence (section breaks 48–96px).
- Chrome is designed, not defaulted: if a sidebar earns its place, style it as a brand surface
  (width, type, active states, wordmark treatment) — not the shadcn default rail.
- Density is authored per view: analytic tables go compact (with a density toggle); overview surfaces
  go spacious. Never uniform-medium everywhere.

**Color & material**
- Pick a material, not a palette: **ink** (hue-tinted near-black, e.g. `oklch(0.16 0.01 <brand-hue>)`
  — never saturated navy) or **paper** (warm off-white, near-black text). Both modes designed, not
  auto-inverted.
- ONE brand accent. Semantic colors (ok / warn / crit / info) are reserved exclusively for state.
  Everything else is achromatic steps — a 4-step text ladder (≈100/70/50/35% alpha) and hairline
  borders (8–12% alpha). One elevation method: hairline OR soft shadow, never both plus glow.
- Define tokens in OKLCH; contrast per WCAG 2.2 AA is non-negotiable in both modes.

**Iconography** — fewer, smaller, monochrome-muted, aligned to the type grid. Icons annotate;
they do not decorate. No filled accent-colored icon chips.

**Data-viz as decision instrument**
- Every chart states its "so what" — caption or annotation (threshold band, delta label, anomaly
  marker). If no decision depends on it, it does not ship.
- Direct labeling over legends (≤5 series); no donut for ≤4 categories (use a stacked bar or big
  number + delta); sparklines carry min/max/current markers; axis type is 11px data-voice.
- Chart palette = achromatic + brand accent + semantic-when-state; never the rainbow default.

**Motion (MOT-\* only)** — state-change feedback, not decoration: micro 120–200ms, panel/overlay
200–300ms, stagger ≤8 items × 20–30ms, number tweens on value change (MOT-18), chart draw-in once on
mount, crossfade route transitions ≤300ms. Instant (<100ms) hover/focus. `prefers-reduced-motion`
honored everywhere.

**Voice** — declarative, specific, honest: "Last sync 14:32 UTC", not "MISSION TIME"; "3 clusters
degraded — oldest 25m", not "All Systems Operational ▾" theater. Empty states carry cause + one
action. Errors are branded, explanatory, next-step-bearing (never raw `RBAC: access denied` — see the
branded-error-screen program). Buttons name the outcome ("Rotate token"), not the gesture ("Click here").

---

## §7 — Experiential language (S-1 / S-1m)

Where the richer reference traits legitimately land: editorial hero composition (oversized display
type, full-bleed or masked media), scroll choreography, deterministic preloaders, cursor-reactive
moments, WebGL — recipes and `EXP-*` tokens in `.claude/references/frontend-uplift-experiential-motion.md`
§3–§4 (native-CSS-first). Design rules beyond motion:

- The hero states a **thesis in words** (REF-1/2 voice: short, declarative, product-true) — not
  feature bullets.
- One cinematic idea per surface, executed fully, beats three half-effects.
- S-1m surfaces need a fast path through: a returning user must never wait on choreography (skippable,
  and snappy after first visit).
- Unconditional locks apply on every surface: reduced-motion fallback (WebGL → static poster), contrast
  holds across recolors, no obscuring/click-blocking motion, mobile/touch fallbacks.

---

## §8 — Direction seeds (worked examples — divergence axes are the requirement)

**The binding rule is the divergence requirement, not any seed below** (round 3 — the seeds had
hardened into a rotation, which is BAN-15 by another name): the three directions presented per
§2 must differ on **at least four of these axes** — navigation model · page silhouette ·
typography posture · geometry · material/depth model · color temperature · density ·
interaction grammar. Retyping or recoloring one shell is one direction, not three. For
program-scope work, each direction is proven divergent by a same-content grayscale composition
plate (real data, no color) — if the plates could be mistaken for each other, they are not
divergent.

**Style-language seeds** (D-A/B/C — worked examples, historically over-used; reach past them):

**D-A · Precision Instrument** — *"A calm, exact tool that feels machined."*
Quiet ink or paper material, hairline structure, mono data voice, editorial-numbered sections,
near-zero decoration; recognizability comes from typographic discipline and spatial calm.
Traits: 2-voice type, 4-step text ladder, hairline-only elevation, annotated charts, instant motion.
Bans: BAN-1/2/3/8; any gradient; any icon decoration. Risk: sterile if type contrast is timid.
Applies: all S-2; S-1m in restrained form.

**D-B · Editorial Cockpit** — *"An operations magazine: the day's posture, laid out like a front page."*
Strong display type (grotesk or serif accent), asymmetric lede-plus-supporting composition, numbered
eyebrows, charts as annotated figures with captions, generous section pacing (REF-3/4/5 energy on a
tool). Traits: lede module, display headlines, editorial captions, byline-style metadata, section
rhythm. Bans: BAN-2/5/6/13; uniform grids. Risk: headline scale eating vertical space in dense
workflows — cap display sizes on working views. Applies: overview/report/posture S-2 surfaces + S-1m.

**D-C · Cinematic Threshold** — *"Cinematic at the doors, machined inside."*
Full experiential craft on S-1/S-1m thresholds (login, onboarding, first-run: WebGL field, masked
type, deterministic preloader — REF-2/6/7), wrapping a strict D-A instrument core for every working
view. Traits: authored thresholds, poster-quality login, celebration moments, calm interior. Bans:
BAN-12 (leakage inward), BAN-1 neon. Risk: two dialects must still be one brand — shared type +
accent + material. Applies: products with real public/first-run surfaces.

**Product mental-model seeds** (round 3 — directions organized around what the product IS, not
how it is styled; pick ONE dominant model per product area, never blend all three into another
purple cockpit):

**M-1 · Sovereign Ledger** — *"Every claim feels signed, attributable, and audit-ready."*
Provenance rails, evidence drawers, timestamps + confidence on every figure, institutional
typography. The surface reads as a record of account, not a dashboard.

**M-2 · Operational Cartography** — *"Infrastructure as territory."* Tenant boundaries, trust
zones, and controlled routes as nested planes; a persistent inspector supplies depth and
detail — depth comes from nesting and selection, never from glow. Topology earns its pixels by
carrying edge meaning (direction, rate, health, ownership) or it doesn't ship.

**M-3 · Causal Flight Recorder** — *"What changed, what it affected, what happened next."*
The product organized around time-aligned events: deploys, policy changes, cost movements, and
health traces on one causal axis. Every view answers "what happened and what do I do".

---

## §9 — House thesis contract (each repo declares its own)

**This registry copy of the canon is product-neutral by design.** It carries no house thesis of its
own — a thesis names one product, and this file is shared, unchanged, across every repo on the fleet.
The standing visual direction for a given product is therefore declared **in that repo**, not here.

Each consuming repo declares its house thesis in a repo-local design-system reference under
`.claude/references/frontend-uplift/` — `<repo>-design-system.md`, or `design-system.md` when the repo
ships a single product. **That overlay is the only place** a product-specific thesis, its named
anti-reference list, and its route/surface map may live. Nothing in this registry file may name a
product, a route, or a "never again" screenshot; when you feel the pull to, you are writing the
overlay, not this canon.

**The `frontend-uplift-art-direction-scout` MUST read the repo overlay before proposing a thesis or
directions.** A run with no overlay present is a run with no house thesis: the scout says so, proposes
directions from §8 against the neutral canon, and authoring the overlay is the run's first
deliverable — it is never silently defaulted to a prior surface's or a prior run's look (BAN-15).

**What a house-thesis overlay MUST contain** (the structure this section used to fill in directly — a
repo fills it in now):

1. **One-sentence visual thesis** tying the product's domain to a visual idea — and it MUST pass the
   swap-test: substitute a competitor's product name into the sentence; if it still reads true, it is a
   category description, not a thesis. State the **invariants** the thesis protects (trust, precision,
   honest data, calm at repeat-use, …), NOT a page silhouette or style recipe — a silhouette mandate is
   BAN-15 waiting to happen, because §6/§8 patterns are worked examples of the invariants, never a
   required shell. A run may satisfy the invariants through a §8 style seed (D-A/B/C), a §8 product
   mental model (M-1/M-2/M-3), or a genuinely new direction; what it may not do is clone a prior
   surface's shell.
2. **Named anti-references** — the specific prior screens, comps, or competitors this product is
   steering away from, each mapped to the §5 BAN tokens it exemplifies, kept as the concrete "never
   again" baseline (link screenshots when they exist).
3. **Surface map** — every route/view in scope tagged S-1 / S-1m / S-2
   (`.claude/references/frontend-uplift-motion-vocabulary.md` §0), with the direction chosen per surface.

**Worked example (illustrative — a fictional product, NOT this registry's house thesis).**
For a fictional grid-operations console, *"Voltline"*:

> **A calm high-voltage control room: every reading feels metered, sourced, and safe to act on.**
> Editorial hierarchy and high-trust instrumentation — not neon SOC theater. Cinematic moments live
> only at thresholds (login, onboarding, first-run); repeat-use dashboards stay calm, exact, and fast.

(Swap-test: substitute a generic competitor and the sentence collapses — it is anchored to grid
operations and its metered/sourced/safe invariants, so it passes.) One worked default, not a mandate:
a D-A instrument core, D-B overview surfaces, D-C thresholds — shown in the surface map below.

| Surface | Class | Application (example) |
|---|---|---|
| Login / first-run / 404 | S-1m | D-C threshold: one cinematic idea (spatial grid field / masked type), skippable, poster fallback |
| Getting Started / onboarding | S-1m | Guided editorial launchpad — journey map, progressive steps, restrained motion |
| Grid Overview / Posture | S-2 | D-B: posture lede ("what tripped, what needs me"), annotated severity figures — no persona-card grid |
| Load tables / analytic views | S-2 | D-A workbench: compact density, threshold-annotated charts, severity as semantic color ONLY |
| Assets / telemetry / costs | S-2 | D-A instrument panels: annotated trends, status timelines, command actions |
| Marketing / docs home | S-1 | Full editorial: REF-2-style declarative narrative, full-bleed media |

*Voltline's* anti-references (example): a prior "ops command center" comp scoring 11–12 on §10
(BAN-1/2/3/5/6/13), kept as its never-again baseline. **Your repo's overlay names its own** — this
example is here to show the shape, not to be inherited.

---

## §10 — Cookie-cutter risk score (measure it, don't debate it)

Score 1 point per tell that is present. Score the CURRENT state and every PROPOSED end state
(§2 deliverable 6; challenger Axis 11 uses the proposed-state score).

1. Navy/near-navy dark shell with neon accent set (BAN-1)
2. 6+ equal rounded cards as the primary layout (BAN-2)
3. Icon-tile decoration pattern (BAN-3)
4. Default Inter + Lucide + shadcn look untouched (BAN-4)
5. No focal element / equal panel weight (BAN-5)
6. Decorative, unannotated charts (BAN-6)
7. Badge soup (BAN-7)
8. Glow/gradient/glass without reason (BAN-8)
9. Multiple primary CTAs per viewport (BAN-9)
10. Generic or cosplay copy (BAN-10)
11. Semantic color used decoratively (BAN-11)
12. Uniform density, no authored modes (BAN-14)
13. Same-silhouette syndrome — a shell/recipe cloned from another surface or run, incl. the
    canon's own house look, as this surface's identity (BAN-15)

**0–2 not-cliché** (necessary, NOT sufficient — see the §14 Directed Quality Score) ·
**3–5 template-leaning** (MAJOR — needs direction work) ·
**6+ generic AI dashboard** (BLOCKER — do not ship; return to §2).

**§10 measures only the ABSENCE of named clichés** (round 3): a sparse, ornamental,
operationally-empty page can score 0–1 here — a blank page scores 0. Shipping requires BOTH
halves — this anti-pattern score AND the §14 DQS. Never present a low §10 score alone as
evidence of good design.

Calibration (round-3 corrected — anchors must be REPRODUCIBLE): an early "~9 screenshots" anchor
pointed at unpersisted images and could not be re-derived (an independent scorer read the successor
screens at ~5). Standing anchors: the §1 anti-reference — a fully-templated "command center" concept
comp — scores 11–12 (persisted description: §1); a two-scorer experiment on a real dashboard homepage
scored 4 vs 3 with 11/12 per-tell agreement. A self-scored "achieved N/13" with no independent column
is calibration data for nothing — one surface's self-claimed 0/12 vs an external ~5 on the same
program's screens is the standing example of why the independent column exists.

**Scoring protocol (binding — evidence tiers, band-edge rule, and per-consumer outcomes live in
§14, the one home):** every scored tell carries a verdict (`1` present / `0` absent /
`UNSCORABLE`) and ONE evidence artifact with its §14 tier (`✓ live` screenshot/computed-style ·
`✓ code` file:line · `~ inferred`). UNSCORABLE never counts toward a total. Totals are DERIVED
by counting 1-verdicts — never asserted from memory. Empirical calibration (2026-07-09, two
independent code-only scorers on the same surface): totals agree to ±1 with the residual
disagreement on the judgment-qualifier tells — which is exactly why the per-tell evidence row,
not the bare total, is the auditable unit.

---

## §11 — The four questions (every design proposal answers these)

- **Q1** Which anti-reference pattern does this remove or avoid? (cite BAN-N)
- **Q2** Which reference trait does this adapt — and how is it *translated* for this surface, not copied? (cite REF-N)
- **Q3** Why is this appropriate for this surface class? (cite S-1/S-1m/S-2)
- **Q4** What makes the result recognizably NOT a default shadcn/Tailwind assembly?

A proposal that cannot answer Q4 is polish, not design — acceptable only when the run is explicitly
scoped to mechanical fixes (a11y, tokens, states).

---

## §12 — Typography starter kits (self-hostable; sovereign/air-gap-clean)

**Last-verified:** 2026-07-06 (authoring date — licence/availability claims re-verify live when
stale or relied on; protocol: `.claude/references/frontend-uplift-source-registry.md` §0).

Runtime font CDNs (Google Fonts et al.) are an egress — **self-host** subset woff2 via `@font-face`
(`font-display: swap`; variable fonts preferred). Licenses noted; OFL is always safe to bundle.

| Kit | Display / UI | Data voice | Editorial accent | Character |
|---|---|---|---|---|
| Instrument (house default) | Geist Sans (OFL) | Geist Mono (OFL) | — | Sleek, machined, modern |
| Sovereign institutional | IBM Plex Sans (OFL) | IBM Plex Mono (OFL) | IBM Plex Serif (OFL) | Full family system; gravitas |
| Editorial cockpit | Space Grotesk (OFL) | JetBrains Mono (OFL) | Fraunces italic (OFL, variable soft/wonk) | Distinctive display + warm serif moments |
| Quiet contemporary | Instrument Sans (OFL) | Fira Code (OFL) | Newsreader italic (OFL) | Understated with an editorial voice |

Fontshare faces (General Sans, Cabinet Grotesk, Clash Display…) are free but under the proprietary
ITF FFL — review before bundling into air-gapped/IL5 artifacts. Commercial faces (Söhne, ABC
Diatype…) need purchase — flag as `$$` in briefs. Whatever the kit: establish the scale contrast and
tabular numerals of §6, or the face change reads as no change.

---

## §13 — How to evolve this file

- New inspiration sites → the §4 **"Proposed references (unreviewed)"** block, full
  trait-extraction protocol (fetched-copy evidence where possible, confidence marked; prefer
  live-recon verification). **Numbered REF entries are minted only by human promotion** —
  agents propose, a reviewer promotes or deletes (round-3 8f: §4 is curated taste; scouts
  minting canon made taste self-reinforcing). MOT/EXP token appends elsewhere remain direct
  (mechanical, collision-linted).
- New template tells observed in shipped AI-generated UI → §5 as BAN-15+ (and mirror into §10 when
  measurable).
- Direction retrospectives (a thesis that worked/failed in production) → one-line note under the
  relevant §8 direction.
- §9 is a product-neutral CONTRACT — it must never name a product. A product's house thesis is a
  human taste decision that lives in that repo's `.claude/references/frontend-uplift/` overlay and is
  revised there, never here. This file acquiring a product name, route, or "never again" screenshot is
  the drift to catch.
- Band→outcome mappings and evidence tiers change ONLY in §14 — consumers cite §14 and never
  restate the numbers locally (restated numbers are how the three ship bars drifted apart).

---

## §14 — Evidence tiers & band→outcome map (canonical — consumers cite, never restate)

The ONE home for how §10 scores and BAN/REF judgments are evidenced, and what each band means
per consumer. Added 2026-07-09 (frontend-pipeline critique round 1, findings X-1/X-2) after the
same rubric was found carrying three different ship bars across its three consumers.

**Evidence tiers** (extends the §4 ✓/~ notation to every scored judgment):

| Tier | Meaning | Examples |
|---|---|---|
| `✓ live` | observed on the running UI | screenshot path, computed style, live DOM metric |
| `✓ code` | established from source | `file:line`, class string, token definition |
| `~ inferred` | characterized without a direct artifact | posture-level description, unverified trait |
| `UNSCORABLE` | not establishable from available evidence | **never counts toward any total or gate** |

Prefer `✓ live` when a dev server exists; `✓ code` is acceptable; a gate-relevant judgment
resting only on `~ inferred` must be said out loud, not buried. Totals are DERIVED from per-tell
verdicts, never asserted (the one completed uplift run shipped three mutually inconsistent
counts of itself).

**Band → outcome map** (§10 anti-pattern score of the state being judged; 13 tells as of round 3):

| Band | Canonical meaning | `/frontend-design` skill (ships now) | `/frontend-uplift` challenger axis 11 (projected state) | `milestone-frontend-ux` axis 14 (diff critique) |
|---|---|---|---|---|
| 0–2 | not-cliché (necessary, NOT sufficient — see DQS below) | anti half of the gate PASSes | NONE / PASS on the anti half | pass on the anti half |
| 3–5 | template-leaning | **not done** — return to the contract (gate exit 3) | MAJOR | **F-H** when the milestone's stated intent is a restyle/design pass · F-M when the surface is incidental to the diff |
| 6+ | generic AI dashboard | not done | BLOCKER (run-level when projected) | **F-C** on restyle-intent (blocks via the findings gate) · F-H otherwise (still gates) |

**Directed Quality Score (DQS — the positive half, round 3).** The anti score proves only the
absence of named clichés; a blank page scores 0. Eight dimensions, each 0–4, scored with the
same per-row evidence + tier discipline: **1 task clarity** (operator states posture + next
action in 5s) · **2 priority fidelity** (visual weight ↔ risk/cost/urgency) · **3 decision
integrity** (labels/units/scope/freshness/thresholds/"so what" without hover) · **4
composition** (regions answer distinct questions; no dead-space theater or crowding) · **5
typography** (roles encode hierarchy; legible at operating density) · **6 semantic depth**
(layers mean nesting/selection/ownership/state — never decoration) · **7 interaction & state
craft** (focus/selection/drill/loading/empty/error/stale/partial coherent) · **8 product
signature** (logo removed: still recognizably THIS product, coherent with adjacent routes).

**v2 ship rule** (enforced for the skill by `.claude/scripts/frontend-design-check.py`; the uplift
challenger and milestone critic apply the same dimensions qualitatively when judging
proposed/changed surfaces): anti ≤ 2 **AND** DQS mean ≥ 3.0 **AND** no dimension < 2 **AND**
dimensions 1/3/8 each ≥ 3 — on BOTH the self and independent scores. A section with no `✓ live`
artifact is **UNVERIFIED** and does not gate without an audited waiver — code-only or inferred
evidence may produce UNVERIFIED, never PASS.

**Semantic-depth clause** (feeds DQS dim 6 and BAN-8): define the surface's layers — canvas,
work surface, selected/raised, transient overlay — and let every shadow, blur, boundary, or
glow name the product structure or interaction state it communicates. Hairlines around every
module and glow around every node are not depth.

The deliberate asymmetry, stated so it stops looking like drift: the milestone critic judges a
DIFF — hard-failing an unrelated diff because a pre-existing surface scores 4 would block
unrelated work, so *incidental* surfaces get one severity notch of grace. When the milestone
exists to restyle, the skill's bar applies unreduced. **Band-edge rule:** the skill's gate
(`.claude/scripts/frontend-design-check.py`) is deliberately CONSERVATIVE — BOTH the self and the
independent totals must land in the ship band (a 3 from either scorer blocks; a Δ>1 forces
per-tell arbitration from the evidence rows before any gating). The gate can produce a false
"not done", never a false ship.
