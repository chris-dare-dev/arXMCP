# Source registry — /frontend-uplift

Curated sources each scout reaches for FIRST. Updates as new libraries / patterns / inspiration sources prove valuable across runs.

## §0 — Freshness & revalidation protocol (READ FIRST — critique C-2/C-4, 2026-07-09)

This registry is a **curated snapshot, not ground truth**. Library majors, licenses, exemplar
stacks, and tool aliases rot; before this protocol existed the corrections (GSAP-free-2025, the
anime.js addition) only happened when a human noticed by accident. The rules:

- **Every §1–§7 section carries a `**Last-verified:** YYYY-MM-DD` stamp** — the date of the last
  *documented* verification of that section's claims (initial stamps are honest authoring/verify
  dates, not today's date). The same stamp convention applies to the sibling claim-tables:
  `.claude/references/frontend-uplift-motion-vocabulary.md` §10, `.claude/references/frontend-uplift-experiential-motion.md` §5/§6,
  `.claude/references/frontend-design-language.md` §12. The machine-readable census of WHICH sections must carry a
  stamp is `REQUIRED_STAMPS` in `.claude/scripts/frontend-uplift-canon-lint.py` — that dict is authoritative;
  update it when adding a stamped section (this prose describes, the lint enforces).
- **Staleness window: 120 days.** A stale stamp fails nothing by itself — it *triggers* live
  re-verification (T3 below) of the entries a run actually relies on. Structural integrity
  (stamps present + parseable, token tables collision-free) is linted by
  `python3 .claude/scripts/frontend-uplift-canon-lint.py check` (CI-wired; staleness is a WARNING —
  CI must never go red because time passed).
- **Whoever verifies, stamps.** Any scout or skill that live-verifies a section's entries during
  a run updates that section's stamp (the end-of-run write path below already exists). Corrections
  carry a dated one-line note.

**Currency triggers (T1–T4) — when live research is MANDATORY, not discretionary** (single home;
`/frontend-design` Step 2.5 and every scout cite these instead of restating):

- **T1 — off-registry subject:** the brief names a framework / library / exemplar not in this
  registry (or not in REF-1..9) → live-verify (WebSearch/WebFetch) before proposing or styling
  against it.
- **T2 — new dependency:** a candidate/contract introduces a package not in the target
  `package.json` → live-verify current major, license, and React 19 + RSC posture (bundlephobia +
  official docs) — the §2/§10 tables are the starting point, not the verdict.
- **T3 — stale stamp:** the section relied on has `Last-verified` older than 120 days →
  re-verify the specific entries used and UPDATE the stamp in-run.
- **T4 — contradiction:** an entry contradicts observed reality (dead link, deprecated package,
  license change, renamed tool) → correct the entry in-run with a dated note. That correction IS
  this registry working as designed.

## §1 — Live system evidence (for `frontend-uplift-visual-scout`)

**Last-verified:** 2026-07-09 (tool-alias probe — see naming note).

**Tool naming across harness builds:** the preview MCP's server alias has changed between
harness generations — current builds expose **`mcp__Claude_Browser__preview_*`**, older builds
**`mcp__Claude_Preview__preview_*`**. The visual-scout is granted BOTH spellings (unknown names
drop harmlessly); use whichever resolves. If NEITHER resolves, screenshots are impossible — say
so in the brief TL;DR and return `screenshot_count: 0` (loud degradation), never silently skip.
Note the preview MCP **spawns dev servers from `.claude/launch.json`**; it does not reliably
attach to an externally-started server (observed 2026-06-07).

| Tool (`mcp__Claude_Browser__*` current · `mcp__Claude_Preview__*` legacy) | Use |
|---|---|
| `preview_start` | Boot a preview instance pointed at the dev-server URL |
| `preview_screenshot` | Capture PNG of current state to `screenshots/<page>-<state>.png` |
| `preview_click` / `preview_fill` | Drive interactions to capture state changes |
| `preview_inspect` | Read computed styles + DOM structure |
| `preview_resize` | Capture mobile / tablet / desktop responsive breakpoints |
| `preview_logs` / `preview_console_logs` | Surface errors / warnings |

**Required pages to capture (per page in scope):**
- Default state (loaded, no user input)
- Loading state (skeleton / spinner — if applicable)
- Empty state (no data — REQUIRED axis 2 of phase-3)
- Error state (network failure / 4xx / 5xx — REQUIRED axis 2)
- Hover state (cursor on primary CTA)
- Focus state (keyboard focus — a11y axis 7)
- Mobile breakpoint (375px wide)
- Tablet breakpoint (768px wide)
- Desktop breakpoint (1440px wide)
- Dark mode (if theme switcher exists — axis 6 of phase-3)

## §2 — Component libraries + frameworks (for `frontend-uplift-library-scout`)

**Last-verified:** 2026-06-17 (GSAP-free + anime.js verification pass).

| Library | Why | URL |
|---|---|---|
| Tailwind CSS v4 | New CSS engine, container queries, OKLCH, native v4 features | `https://tailwindcss.com/blog` |
| Radix UI Primitives | Unstyled accessible components (Dialog, Popover, Tooltip, Select) | `https://www.radix-ui.com/primitives` |
| shadcn/ui | Copy-paste components built on Radix; community variants | `https://ui.shadcn.com` |
| Tremor | React data-viz components | `https://github.com/tremorlabs/tremor` |
| Headless UI | Tailwind Labs' unstyled accessibility primitives | `https://headlessui.com` |
| Framer Motion | SOTA React animation library | `https://www.framer.com/motion` |
| GSAP | Advanced timeline animations (**now 100% FREE** for commercial — Webflow 2025) | `https://gsap.com` |
| Auto-Animate (FormKit) | Zero-config layout animation | `https://auto-animate.formkit.com` |
| **anime.js** (`animejs` 4.x) | **Dependency-free, tree-shakeable** engine — SVG draw/morph/motion-path, grid-stagger, scramble, spring-drag; the §0 diversification flagship (works on tool surfaces too) | `https://animejs.com` |
| Lucide Icons | Open-source icon set | `https://lucide.dev` |
| Phosphor Icons | Flexible weight icon set | `https://phosphoricons.com` |
| Sonner | Toast notifications (replaces react-hot-toast) | `https://sonner.emilkowal.ski` |
| Vaul | Drawer component | `https://vaul.emilkowal.ski` |
| cmdk | Command palette (Cmd-K pattern) | `https://cmdk.paco.me` |
| TanStack Table | Headless data-grid | `https://tanstack.com/table` |
| TanStack Query | Server-state management | `https://tanstack.com/query` |
| React Aria | a11y primitives from Adobe | `https://react-spectrum.adobe.com/react-aria` |

**Motion layer (motion-jobs test — motion-vocabulary §0; quota retired round 3):** Radix +
Tailwind + shadcn are the *structural* baseline, not the finish line — but the motion rule is
the jobs test, not a quota: every motion candidate names its job (orientation / causality /
feedback / continuity); no named job, no motion; a missing animation dependency with no
unserved jobs is not a finding. Default lightweight engine when a job needs one: **anime.js**
(MIT, 0-dep, tree-shakeable); alternatives Motion (ex-Framer), Motion One, GSAP (now free) —
surface-gated, never at the cost of the a11y / perf locks.

## §3 — Inspiration sources (for `frontend-uplift-inspiration-scout`)

**Last-verified:** 2026-06-07 (authoring pass).

| Source | Why | URL |
|---|---|---|
| Linear | Universally cited UX benchmark for engineering tools | `https://linear.app` |
| Vercel dashboard | Clean ops UX; great empty/error states | `https://vercel.com/dashboard` |
| Stripe Dashboard | Best-in-class data tables + filters | `https://dashboard.stripe.com` (auth required) |
| Notion | Document tools + database views | `https://www.notion.so` |
| Arc Browser | Novel browser UX (sidebar, spaces) | `https://arc.net` |
| Raycast | Command-palette + extensions UX | `https://www.raycast.com` |
| Mintlify | Documentation site UX | `https://mintlify.com` |
| Cal.com | Open-source scheduling app | `https://cal.com` (and GitHub) |
| Plausible Analytics | Privacy-first analytics with clean dashboards | `https://plausible.io` |
| Trail of Bits research | Security tool UX (advanced data viz) | `https://github.com/trailofbits` |
| Anthropic Claude.ai | Reference for AI-chat UX | `https://claude.ai` |
| OpenAI ChatGPT | Reference for AI-chat UX | `https://chat.openai.com` |
| Cursor IDE | Reference for AI-coding tool UX | `https://cursor.com` (download for analysis) |
| Vercel v0 | Reference for AI-generation UX | `https://v0.dev` |
| Awwwards SOTD | Visual / interaction inspiration | `https://www.awwwards.com/sites_of_the_day` |
| Dribbble (dashboard tag) | Dashboard inspiration | `https://dribbble.com/tags/dashboard` |
| Mobbin | Mobile + web pattern library | `https://mobbin.com` |
| Page Flows | User flow recordings | `https://pageflows.com` |

**Filter signal:** prefer sources where the app is actually USED (not just demoed). User-tested > marketing-screenshot.

## §4 — Internal codebase orientation (for `frontend-uplift-current-state-critic`)

**Last-verified:** 2026-06-07 (authoring pass — paths are re-confirmed by each run's reads).

Always READ FIRST before forming critique:

- `<frontend-project>/src/` — main source
- `<frontend-project>/src/components/` — component inventory
- `<frontend-project>/src/styles/` OR `<frontend-project>/tailwind.config.js` — token system
- `<frontend-project>/package.json` — dependencies inventory (incumbent libraries)
- `<frontend-project>/.storybook/` if present — what's componentized

**Locate the frontend project(s) in the consuming repo** — there may be more than one, and they may be
different surface classes (a marketing/landing surface and a data-tool surface are different S-classes;
tag each). Web projects expose the files above. **Non-web frontends carry different orientation files:**
a PySide6/Qt desktop app has no `package.json` / Tailwind config — read its `*.py` widget modules, `.ui`
layouts, and `.qss` stylesheets (theme / QSS constants are its token system); a Jinja2 + htmx
server-rendered console has templates + a stylesheet rather than a React component tree. Read the
equivalent, not the literal path.

Patterns to detect:
- Hard-coded colors / spacing / durations that should be tokens
- One-off components that duplicate Radix/Shadcn primitives
- Missing empty/error states (axis 2 violation)
- Missing dark mode parity (axis 6 violation)
- Missing keyboard navigation / focus indicators (axis 7 violation)
- Inconsistent typography (heading hierarchy violations)
- Bundle size red flags (lottie, three.js, large icon imports as default)

## §5 — Accessibility resources (for `frontend-uplift-challenger` axis 7)

**Last-verified:** 2026-07-09 (WCAG 2.2 quickref URL corrected — the 2.1 quickref hid exactly
the 2.2-only SCs the sweep was for: focus-not-obscured, dragging alternatives, 24px targets).

- WCAG 2.2 AA reference: `https://www.w3.org/WAI/WCAG22/quickref/`
- axe DevTools: `https://www.deque.com/axe/devtools/`
- WebAIM contrast checker: `https://webaim.com/resources/contrastchecker/`
- React Aria a11y patterns: `https://react-spectrum.adobe.com/react-aria/patterns.html`

**Required checks per candidate (phase-3 axis 7):**
- 4.5:1 contrast ratio for normal text (3:1 for large text)
- All interactive elements have visible focus indicators (`MOT-23 focus-ring`)
- All interactive elements are keyboard-reachable (Tab/Shift-Tab/Enter/Space/Esc)
- All images have alt text OR are decorative (`role="presentation"`)
- All form inputs have associated labels
- ARIA roles only where semantic HTML insufficient (`<button>` > `<div role="button">`)
- `prefers-reduced-motion` honored for every motion candidate (`MOT-*`)

## §6 — Experiential exemplars + toolkit (for `frontend-uplift-experiential-scout`)

**Last-verified:** 2026-06-17 (anime.js addition; exemplar stacks captured live 2026-06-07).

Award-tier **experiential** sites (marketing / brand / portfolio) reverse-engineered for modern motion
craft — the source of the `EXP-*` tokens. Surface-gated: these apply to S-1 / S-1m surfaces (landing,
hero, onboarding, login, marketing), NOT S-2 data tools. See `.claude/references/frontend-uplift-experiential-motion.md`.

**Canonical exemplars (reverse-engineered 2026-06-07, stack detected live; `animejs.com` added 2026-06-17):**

| Site | Detected stack | Signature technique | EXP |
|---|---|---|---|
| `squarespace.com/go/create-a-website` | Custom + WebGL2 | cursor-reactive 3D plane gallery | EXP-13 |
| `zetta-joule.com` | Webflow + GSAP(ScrollTrigger/Flip/SplitText) + Lenis + Three.js r128 | pinned scroll-scrub scale + SplitText reveals | EXP-2/4/8 |
| `vaulk.com/en-GB` | bundled GSAP/three + custom cursor (7 canvas) | deterministic asset preloader (0→100) | EXP-7/9 |
| `ref.digital/work` | Nuxt/Vue + custom DOM cursor | cursor-morph + parallax-column grid | EXP-6/11 |
| `trucknroll.com` | Locomotive Scroll v5 | data-scroll-speed parallax + editorial type | EXP-1/6/16 |
| `sondaven.com/en` | GSAP + ScrollTrigger + SplitText + Lenis (16 canvas) | scroll-zoom hero + image-displacement + masked text | EXP-4/14/15 |
| `animejs.com` | **vanilla JS + anime.js v4.4.1** (self-dogfooded, 0 deps, 0 framework, 0 canvas) | grid-stagger ripple + SVG draw/morph + draggable spring physics | EXP-20..25 |

**Galleries / studios to mine for more (cite the technique, not the screenshot):**

| Source | Why | URL |
|---|---|---|
| Awwwards | Site-of-the-day experiential benchmark | `https://www.awwwards.com` |
| Godly | Curated high-craft web design | `https://godly.website` |
| FWA | Cutting-edge interactive sites | `https://thefwa.com` |
| Codrops (Tympanus) | The technical teardowns + source for these effects | `https://tympanus.net/codrops` |
| Lusion / Active Theory / Resn / Immersive Garden | Studios that set the WebGL/experiential bar | (studio sites) |
| Webflow Showcase | Webflow+GSAP+Lenis stack exemplars | `https://webflow.com/made-in-webflow` |
| **anime.js** docs + examples | Dependency-free SVG draw/morph/motion-path, grid-stagger, scramble, draggable patterns to lift (the lightweight, no-WebGL lane) | `https://animejs.com/documentation` |

**Experiential library toolkit:** Lenis (`lenis`, smooth scroll) · GSAP + ScrollTrigger + SplitText +
Flip (all FREE since 2025) · `@gsap/react` `useGSAP` · Locomotive Scroll v5 · Three.js · `@react-three/
fiber` + `@react-three/drei` · OGL (~8 KB) · Swiper · **anime.js** (`animejs` 4.x — MIT, 0-dep, tree-shakeable: SVG draw/morph/motion-path, grid-stagger, scramble, draggable; the light no-WebGL lane) · **native CSS** (`animation-timeline: scroll()/
view()`, `@property`, `background-clip:text`, OKLCH `color-mix`). Native-first; lib only when functional
+ Firefox-coverage needed, or for true WebGL per-pixel work. Recipes: experiential-motion §4.

**Live-recon toolkit (ORCHESTRATOR / main-session only — NOT the scout):** the main session can drive a
real browser via the **Claude-in-Chrome MCP** (`mcp__Claude_in_Chrome__*`) to capture loading/scroll/
cursor behavior + detect runtime stacks the way the original 6 exemplars were captured. Flow: `list_connected_
browsers` → user picks (mandatory handshake) → `select_browser` → `tabs_context_mcp(createIfEmpty)` →
`navigate` → `javascript_tool` (run the stack-detect snippet, experiential-motion §2) → `browser_batch`
of `computer` scroll/hover + `screenshot`. Drop findings into `.claude/notes/frontend-uplifts/<ID>/
discoveries/live-recon.md` for the experiential-scout to read (`{LIVE_RECON_PATH}`). The browser-
selection handshake requires `AskUserQuestion`, so this is **not** available to sub-agents — the scout
reverse-engineers from WebFetch + web teardowns instead.

## §7 — Art-direction references (for `frontend-uplift-art-direction-scout`)

**Last-verified:** 2026-07-06 (canon authoring — REF copy lines fetched live that day).

The canonical taste library lives in **`.claude/references/frontend-design-language.md` §4 (REF-1..9)** — metalab.com ·
waabi.ai · new.studio · newgenre.studio · filter.im · ponder.ai · sohub.digital · trionn.com ·
save.design — with the trait-extraction protocol, the BAN-1..15 anti-pattern list (§5), the
per-surface positive specs (§6/§7), the direction seeds + divergence axes (§8), the product house
thesis (§9), and the cookie-cutter rubric (§10). This registry section is deliberately an INDEX, not
a copy — one canon, no drift.

How this differs from the neighboring sections: §3 inspiration apps are mined for tool-UX *patterns*;
§6 experiential exemplars are mined for motion *technique/stack*; the §7 reference library is mined
for *identity* — typography posture, layout rhythm, color/material language, voice, and
recognizability. Same site may appear in two lists with different extraction lenses.

**Numbered REF entries are minted only by human promotion** (round-3 8f): scouts append
candidates to design-language §4's "Proposed references (unreviewed)" block; a reviewer
promotes to REF-N (and only then mirrors the index row here) or deletes.

Galleries to source NEW references from (add as REF-10+ via design-language §13): `minimal.gallery`,
`godly.website`, `siteinspire.com`, `www.awwwards.com`, `land-book.com`, `httpster.net`.

## How to evolve this registry

Append new sources / libraries / inspiration apps to the relevant section AT END OF RUN with a one-line rationale.
New art-direction references (REF-10+) go to `.claude/references/frontend-design-language.md` §4 (full trait protocol) with only the index row here in §7.
When you live-verify a section's entries (trigger T2/T3/T4), update that section's
`**Last-verified:**` stamp in the same edit — the stamp is part of the correction, and
`.claude/scripts/frontend-uplift-canon-lint.py check` verifies the stamps stay present and parseable.
