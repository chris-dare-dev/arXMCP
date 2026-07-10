# Experiential motion catalog — /frontend-uplift

The **award-tier / experiential** companion to `.claude/references/frontend-uplift-motion-vocabulary.md`. Where the
motion-vocabulary covers *tool/dashboard* motion (entry, state-change, microinteractions), THIS file
covers the **marketing/experiential** motion language that makes sites like Squarespace, zetta-joule,
vaulk, ref.digital, trucknroll and sondaven feel alive — parallax, smooth-scroll, scroll-driven
scrub/zoom, cursor-reactive frames, deterministic preloaders, WebGL galleries, image-masked type,
dynamic recoloring.

**These techniques are a different motion budget, not a free-for-all.** The challenger BLOCKS most of
them on tool/dashboard surfaces (motion-vocabulary §8 AP-1/AP-2/AP-3/AP-5). They belong on
**experiential surfaces** (see §1). The accessibility locks (`prefers-reduced-motion`, WCAG 2.2 AA,
keyboard) are **unconditional** — they apply on every surface, always.

Every experiential candidate in a scout brief MUST cite the `[EXP-N <name>]` token from §3 (and, where
it overlaps tool-motion, the `[MOT-N]` token too). If a scout discovers a new experiential primitive,
append it as `[EXP-N+1]` with the exemplar site + library source.

**Surface substrate (web vs non-web).** Every recipe below is written for a **web** surface (React /
RSC / CSS / WebGL / a JS bundler). The surface-class doctrine (§1), the anti-monoculture mandate (§0),
and the unconditional a11y locks (§7) apply to any frontend; the *implementations* (Lenis, GSAP, R3F,
`animation-timeline`, `'use client'`) are web-only. On a non-web surface — a PySide6/Qt desktop app or
a Jinja2 + htmx server-rendered console — most experiential techniques (parallax, WebGL galleries,
smooth-scroll) have no equivalent and should be treated as out-of-surface; port only the *intent* of
the lightweight ones (a deterministic preloader counter, a reduced-motion-gated reveal) to the
platform's native facility. Do not attempt to import the web libraries.

---

## §0 — Dynamic-content-by-default (the anti-monoculture mandate — READ FIRST, with §1)

**The convergence problem this pipeline now actively counters.** AI-generated and template-spun frontends
have collapsed onto one look — **static shadcn/ui + Tailwind, no motion layer.** It is clean, accessible,
and *everywhere*, which is exactly why it no longer reads as modern or distinctive. shadcn + Tailwind +
Radix stay the correct **structural** baseline (best React 19 + RSC story, a11y-by-default); the failure
is stopping there and shipping a frozen UI.

**Standing directive — every run, every mode (including `lean`), REVISED round 3 (quota
retired):** treat *"static shadcn+Tailwind with no dynamic-content layer"* as a **named gap
class, not a quota**. The old rule ("≥ 2 dynamic candidates + ≥ 1 new engine every run")
rewarded gratuitous motion — initial-load number tweens, stagger for its own sake, hover
glow — and bred an anime.js monoculture of its own. The binding rule is now the
**motion-jobs test** (motion-vocabulary §0, the one home): a motion candidate must name its
job — orientation / causality / feedback / continuity — and no named job means no motion.
- **library-scout** evaluates the motion/dynamic-content layer as its own axis: does the UI
  have *unserved motion jobs*? If yes, propose the lightest fix — native CSS or incumbent
  capability first; a new engine (default: **anime.js** — MIT, zero-dependency,
  tree-shakeable; siblings: Motion (ex-Framer), Motion One, GSAP-now-free) only when a named
  job needs one. A missing animation dependency with no unserved jobs is NOT a finding.
- **current-state-critic** flags `static-monoculture` ONLY as "these named jobs are unserved"
  (e.g. no feedback on destructive actions, no continuity across drill-downs) — never as
  "no animation lib in package.json" per se.

**This does NOT relax the surface gates (§1) or the a11y locks (§7).** "Add dynamic content" is
surface-appropriate by construction:
- **S-2 tool/dashboard** → tasteful **microinteractions**: staggered list reveals, number-tweens,
  icon-morphs, SVG success-draws, scramble-on-load. anime.js shines here precisely because it is
  tree-shakeable and needs **no heavy WebGL bundle**. Parallax/WebGL/scroll-zoom stay AP-1/2/3 BLOCKERs.
- **S-1 / S-1m experiential** → the full award-tier budget (§3), incl. the new anime.js-class EXP-20..25.

Diversify the *craft*, never the *guardrails*.

---

## §1 — Surface-type model (gates everything below — read with §0)

Before proposing ANY experiential technique, classify the surface. This is the single most important
decision; it determines whether a technique is *encouraged* or a *BLOCKER*.

| Surface class | What it is | Examples | Experiential motion budget |
|---|---|---|---|
| **S-1 experiential** | Marketing / brand / storytelling. The motion IS part of the product. | Landing pages, hero/brand pages, product launches, portfolios, brochure sites, the 7 exemplar sites | **Encouraged** — parallax, WebGL, scroll-zoom, preloaders, custom cursor all in-budget WITH perf + a11y gates |
| **S-1m experiential moment** | An experiential surface *inside* an otherwise-tool app. | An app's public login/signup, onboarding/welcome, marketing/pricing page, empty-first-run, a celebratory success moment | **Scoped-yes** — allowed on that surface only; must not leak into the data UI |
| **S-2 tool / dashboard** | Data, controls, dense information, frequent repeat use. | Admin dashboards, data grids, settings, monitoring, internal tool / operator working views | **Blocked** — AP-1/2/3/5 are challenger BLOCKERs here. Use motion-vocabulary tool motion only |

**Rules:**
- A technique acceptable on S-1 can be a BLOCKER on S-2. The surface tag is part of the candidate.
- "Apple does it" / "this award site does it" is NOT a justification on an S-2 surface.
- The boundary matters most in mixed apps: a tool with a marketing front. Tag each page, not the app.
- **Unconditional regardless of surface:** `prefers-reduced-motion` honored (AP-4), motion never
  obscures (AP-6) or blocks-click (AP-7) content, WCAG 2.2 AA contrast/focus/keyboard, no auto-playing
  audio. These never relax — not even on S-1.

When a candidate is S-1/S-1m, the challenger's axis-3 (motion anti-pattern) shifts from "is this an
anti-pattern?" to "is this *budgeted* — perf, reduced-motion poster, mobile fallback, contrast-holds?".

---

## §2 — Reverse-engineered exemplars (primary evidence, captured live 2026-06-07; **animejs.com** added 2026-06-17 via source + bundlephobia detection)

The sites the capability was built from, with the live-detected stack and signature technique.
Two technique *families* emerged: a **WebGL family** (three.js / R3F / OGL shaders, pointer/scroll
uniforms, preloader-gated, heavier) and a **DOM/CSS-transform family** (Lenis/Locomotive smooth-scroll
+ GSAP ScrollTrigger + a custom DOM cursor; lighter, more accessible, more transferable). **animejs.com**
(added 2026-06-17) anchors a third, *lightest* lane — **dependency-free DOM/SVG via anime.js** — proof
that distinctive, dynamic motion does NOT require a heavy WebGL bundle; it is the diversification exemplar.

| Site | Detected stack (live) | Signature technique | Family |
|---|---|---|---|
| **squarespace.com** /go/create-a-website | Custom framework + **WebGL2** (1 canvas) | Cursor-reactive **3D plane gallery** — group/camera rotation lerped toward normalized pointer each rAF | WebGL |
| **zetta-joule.com** | **Webflow** + GSAP (ScrollTrigger, Flip, **SplitText**, ScrollToPlugin) + **Lenis** + **Three.js r128** + Swiper (3 canvas) | Pinned hero + **scroll-scrub scale** + SplitText line reveals | both |
| **vaulk.com** | Bundled (module-scoped) GSAP/three + custom cursor (**7 canvas**) | **Deterministic asset preloader** (`LOADING 86/100` counter), heavy multi-canvas WebGL | WebGL |
| **ref.digital** /work | **Nuxt (Vue)** + custom DOM cursor (0 canvas) | DOM **cursor-morph** over work items + **parallax-column** reveal grid | DOM |
| **trucknroll.com** | **Locomotive Scroll v5** (28 `[data-scroll]`, 0 canvas) | `data-scroll-speed` parallax + **oversized editorial type** + image-nested-in-text | DOM |
| **sondaven.com** /en | GSAP 3.13 + **ScrollTrigger** + **SplitText** + **Lenis** + Swiper (**16 canvas**) | **Scroll-zoom** pinned hero (scale scrub) + WebGL image-displacement + image-masked text | both |
| **animejs.com** | **vanilla JS + anime.js v4.4.1** (self-dogfooded; single `scripts.js?v=4.4.1`, 0 framework, 0 deps, 0 canvas) | **grid/value-staggered reactive field** + SVG line-draw/morph logo + draggable spring physics | **DOM/SVG (light)** |

**How to detect a site's stack yourself** (the `frontend-uplift-experiential-scout` does this live):
run this in the page console / `javascript_tool`:

```js
({
  generator: document.querySelector('meta[name=generator]')?.content,        // "Webflow" etc.
  gsap: window.gsap?.version, ScrollTrigger: !!window.gsap?.core?.globals?.()?.ScrollTrigger,
  lenis: !!window.Lenis, locomotive: !!window.LocomotiveScroll || !!document.querySelector('[data-scroll]'),
  three: window.THREE?.REVISION, canvases: document.querySelectorAll('canvas').length,
  framework: window.__NUXT__ ? 'nuxt' : window.__NEXT_DATA__ ? 'next' : document.querySelector('#root,[data-reactroot]') ? 'react' : null,
  customCursor: !!document.querySelector('[class*=cursor]'),
  libFiles: [...document.querySelectorAll('script[src]')].map(s=>s.src.split('/').pop().split('?')[0])
    .filter(n=>/gsap|scroll|lenis|locomotive|three|ogl|swiper|split/i.test(n)),
})
```
Bundled (Vite/webpack) builds expose **no globals** — `libFiles:[]` + `canvases>0` + a `[class*=cursor]`
node means "heavy WebGL site, libs module-scoped". `generator:"Webflow"` exposes the full GSAP+Lenis
stack via CDN. Count canvases: many canvases (7, 16) = the per-image-WebGL pattern (see EXP-11 trap).

---

## §3 — Experiential motion tokens `[EXP-N]`

Each token: what it is · exemplar · **native/CSS-first** path · **library** path · cost · surface.
Full recipes in §4. Cite the token in every experiential candidate.

### Scroll-driven (DOM family)

| Token | Name | Exemplar | Native-first | Library | Surface |
|---|---|---|---|---|---|
| EXP-1 | smooth-inertia-scroll | zetta-joule, sondaven, trucknroll | — (no CSS equiv for wheel inertia) | **Lenis** ~3 KB | S-1 / S-1m |
| EXP-2 | scroll-scrub | zetta-joule, sondaven | `animation-timeline: scroll()` | GSAP ScrollTrigger `scrub` | S-1 / S-1m |
| EXP-3 | scroll-pin | sondaven, zetta-joule | **`position: sticky`** (0 JS) | ScrollTrigger `pin` | S-1 / S-1m / S-2* |
| EXP-4 | scroll-zoom (dolly hero) | sondaven, zetta-joule | sticky + `animation-timeline: view()` scale | ScrollTrigger pin+scrub | S-1 / S-1m |
| EXP-5 | reveal-on-scroll | all six | IntersectionObserver / `view()` | ScrollTrigger.batch | S-1 / S-1m / S-2* |
| EXP-6 | parallax-columns | trucknroll, ref.digital | `view-timeline` + `sibling-index()` | Locomotive `data-scroll-speed` / GSAP `y` scrub | S-1 / S-1m |

\* EXP-3 sticky and a *single, fast, reduced-motion-gated* EXP-5 reveal are acceptable on S-2 (a sticky
table header, a one-shot fade-in). The decorative variants are not.

### Loading / text

| Token | Name | Exemplar | Native-first | Library | Surface |
|---|---|---|---|---|---|
| EXP-7 | deterministic-preloader | vaulk | `Promise.all` over `img.decode()` + counter | THREE.LoadingManager / drei `useProgress` | S-1 / S-1m |
| EXP-8 | split-text-reveal | zetta-joule, sondaven | manual span-split + `view()` | **GSAP SplitText** (now free) | S-1 / S-1m |
| EXP-15 | image-masked-text | trucknroll, sondaven | **`background-clip: text`** | — | S-1 / S-1m |
| EXP-16 | editorial-oversized-type | trucknroll, sondaven | `clamp()` + `cqi` + `text-wrap: balance` | — | S-1 / S-1m / S-2 (restrained) |

### Cursor / pointer

| Token | Name | Exemplar | Native-first | Library | Surface |
|---|---|---|---|---|---|
| EXP-9 | custom-cursor-follow | vaulk, ref.digital | rAF lerp + `translate3d` | Motion `Cursor` | S-1 / S-1m |
| EXP-10 | cursor-magnetic | Squarespace-class CTAs | pointermove lerp | GSAP `quickTo` | S-1 / S-1m |
| EXP-11 | cursor-morph-on-hover | ref.digital | `data-cursor` attr + class | — | S-1 / S-1m |
| EXP-12 | dom-mouse-parallax-tilt | (CSS cousin of Squarespace) | **`@property` `--mx/--my`** + `rotateX/Y` | — | S-1 / S-1m |

### WebGL / color

| Token | Name | Exemplar | Native-first | Library | Surface |
|---|---|---|---|---|---|
| EXP-13 | webgl-mouse-parallax-gallery | **Squarespace** | CSS `preserve-3d` tilt (cheaper fake) | **R3F** `useFrame`+`state.pointer` / three.js / OGL | S-1 only |
| EXP-14 | webgl-image-displacement | sondaven, vaulk | — (genuinely per-pixel) | **OGL** ~8 KB / R3F `shaderMaterial` | S-1 only |
| EXP-17 | dynamic-recolor-on-scroll | all six | IO `--bg`/`--fg` swap / `scroll()` keyframes / OKLCH `color-mix` | — | S-1 / S-1m |
| EXP-18 | animated-color-pattern | hero backdrops | `@property <angle>` conic / mesh radial-gradients (OKLCH) | — | S-1 only |

### SVG + orchestration (anime.js-class — lightweight, dependency-free; diversifies the heavy WebGL stack)

These are the tokens the **anime.js** addition brings — the dynamic-content layer most AI-generated
shadcn+Tailwind UIs lack (§0). Several have a native path; anime.js earns its place where native is
brittle or absent (morph, grid-distance stagger, scramble, spring-drag) and for timeline orchestration.

| Token | Name | Exemplar | Native-first | Library | Surface |
|---|---|---|---|---|---|
| EXP-20 | svg-line-draw | animejs.com, sondaven | `stroke-dasharray`/`dashoffset` + `view()` | **anime.js** `svg.createDrawable` | S-1 / S-1m / S-2 (restrained) |
| EXP-21 | svg-shape-morph | animejs.com | — (native `d` interp brittle) | **anime.js** `svg.morphTo` | S-1 / S-1m |
| EXP-22 | motion-path-follow | animejs.com | **`offset-path`/`offset-distance`** (Baseline) | **anime.js** `svg.createMotionPath` | S-1 / S-1m / S-2* |
| EXP-23 | grid-stagger-ripple | **animejs.com** (signature) | `animation-delay: calc(var(--i)…)` (1-D only) | **anime.js** `stagger(v,{grid,from})` | S-1 / S-1m |
| EXP-24 | text-scramble-decode | trendy "decode" hero | — | **anime.js** `scrambleText` | S-1 / S-1m |
| EXP-25 | draggable-throw-physics | animejs.com, vaulk | — (manual pointer + spring) | **anime.js** `createDraggable` | S-1 / S-1m / S-2* |

\* EXP-22 native `offset-path` and a *restrained, keyboard-alternative-backed* EXP-25 drag (reorderable
lists / kanban) are acceptable on S-2. The decorative variants are not. All six honor reduced-motion (§7).

---

## §4 — Condensed modern-code recipes

**2026 default posture: native CSS first → `<video>` for baked art → JS lib → WebGL only for per-pixel
interactivity.** Every recipe ships a `prefers-reduced-motion` branch. Animate only `transform`/`opacity`
/ registered custom props (compositor-friendly).

### EXP-1 smooth-inertia-scroll — Lenis (the substrate under almost every exemplar)

```js
import Lenis from 'lenis';                 // bare `lenis` pkg (the @studio-freight/* names are RETIRED)
const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
const lenis = reduce ? null : new Lenis({ lerp: 0.1, smoothWheel: true, anchors: true });
// With GSAP ScrollTrigger present, use ONE clock — drive Lenis from gsap.ticker, not a 2nd rAF:
lenis?.on('scroll', ScrollTrigger.update);
gsap.ticker.add((t) => lenis?.raf(t * 1000));  gsap.ticker.lagSmoothing(0);
```
React: `'use client'` + `<ReactLenis root options={{lerp:0.1, anchors:true}}>{children}</ReactLenis>` from
`lenis/react`. **No CSS equivalent for wheel inertia** — `scroll-behavior: smooth` (Baseline, 0 KB) only
smooths anchor/programmatic jumps; escalate to Lenis only when the brief wants weighted wheel scroll.
Locomotive Scroll v5 is now built ON Lenis and delegates pinning to native sticky.

### EXP-2 scroll-scrub / EXP-4 scroll-zoom — native first, ScrollTrigger when Firefox-critical

```css
/* Native scroll-zoom dolly hero — 0 JS, off-main-thread, RSC-safe */
@media (prefers-reduced-motion: no-preference) {
  @supports ((animation-timeline: view()) and (animation-range: entry)) {
    .hero { position: sticky; top: 0; height: 100vh; overflow: clip; }   /* EXP-3 native pin */
    @keyframes dolly { from { scale: 1; } to { scale: 1.6; } }
    .hero-media { animation: dolly linear both; animation-timeline: view();
                  animation-range: cover 0% cover 100%; }
  }
}
```
```js
// Library path (use when Firefox/pre-2025-Safari coverage is required — see §5 support gate)
gsap.fromTo('.hero-media', {scale:1}, {scale:1.6, ease:'none',
  scrollTrigger:{ trigger:'.hero', start:'top top', end:'+=1200', pin:true, scrub:true }});
```
React lib path: `useGSAP(() => {...}, {scope: ref})` from `@gsap/react` (StrictMode-safe auto-cleanup).
Watch GPU/VRAM, not CPU, when scaling full-bleed 4K media.

### EXP-3 scroll-pin — prefer native `position: sticky` (0 JS, Baseline, jank-free)

```css
.panel { position: sticky; top: 0; height: 100vh; }
.panel-wrapper { height: 250vh; }   /* parent height controls pin duration */
```
Reach for ScrollTrigger `pin` only for pin-driven inner-timeline scrub or dynamic re-pin.

### EXP-5 reveal-on-scroll — IntersectionObserver (reveal-once) or `view()` (decorative)

```js
const io = new IntersectionObserver((es)=>es.forEach(e=>{ if(e.isIntersecting){
  e.target.classList.add('is-in'); io.unobserve(e.target);   // reveal once, then stop
}}), { threshold: 0.15, rootMargin: '0px 0px -10% 0px' });
document.querySelectorAll('.reveal').forEach(el=>io.observe(el));
```
```css
.reveal { opacity:0; transform: translateY(24px); transition: opacity .6s, transform .6s; }
.reveal.is-in { opacity:1; transform:none; }
@media (prefers-reduced-motion: reduce){ .reveal{ opacity:1!important; transform:none!important; } }
```
**Choose deliberately:** native `view()` re-hides on scroll-up (it's scroll-bound); IO `unobserve`
reveals once and stays. For "reveal once permanent" UX, IO is *better*, not just a Firefox fallback.

### EXP-7 deterministic-preloader — framework-agnostic counter (vaulk pattern)

```js
const counter = { value: 0 }, el = document.querySelector('.loader-count');
const tasks = ASSET_URLS.map(src => { const img = new Image(); img.src = src;
  return img.decode().catch(()=>{}).finally(()=>{ done++;
    gsap.to(counter, { value: Math.round(done/ASSET_URLS.length*100), duration:.6, overwrite:true,
      onUpdate:()=>{ el.textContent = String(Math.round(counter.value)).padStart(3,'0'); }}); }); });
Promise.all(tasks).then(revealSite);   // tween smooths the discrete loaded/total jumps → monotonic 0→100
```
`img.decode()` guarantees paint-ready (not just downloaded). R3F path: drei `useProgress()` +
`<Loader/>` or a custom `<Html>` counter. **Gate the blocking counter on first-view assets only** — a
100-asset blocking bar on 3G is a bounce machine. Reduced-motion: show final state, skip the count-up.

### EXP-8 split-text-reveal — GSAP SplitText (NOW FREE) or manual spans

```js
import { SplitText } from 'gsap/SplitText';   // FREE since 2025 (see §5) — no Club GreenSock token
const split = new SplitText('.headline', { type:'lines,words,chars', mask:'lines' });  // mask = auto line clip
gsap.from(split.chars, { yPercent:120, opacity:0, duration:.8, ease:'expo.out', stagger:{each:.012} });
// reduced-motion: early-return BEFORE animating (never leave text at opacity:0); split.revert() on unmount
```
Native/0-lib: split into `<span class="char" aria-hidden style="--i:N">` inside `aria-label`'d heading,
animate with `animation-timeline: view()` + `animation-delay: calc(var(--i)*12ms)`. **Only split
headlines** — splitting body copy bloats DOM + hurts INP. `aria-label` on wrapper so SR reads the word.

### EXP-9 custom-cursor-follow — gated lerp (the a11y gating is the whole point)

```css
.cursor { display: none; }                    /* default: native cursor visible */
@media (hover: hover) and (pointer: fine) {   /* fine-pointer ONLY — never on touch */
  @media (prefers-reduced-motion: no-preference) {
    html { cursor: none; }                     /* hide native cursor ONLY inside both gates */
    .cursor { display:block; position:fixed; pointer-events:none; z-index:9999; }
    .cursor__dot,.cursor__ring{ position:absolute; border-radius:50%; translate:-50% -50%; will-change:transform; }
  }
}
```
```js
if (matchMedia('(hover:hover) and (pointer:fine)').matches && !matchMedia('(prefers-reduced-motion:reduce)').matches) {
  let mx=0,my=0,rx=0,ry=0; addEventListener('pointermove',e=>{mx=e.clientX;my=e.clientY;},{passive:true});
  (function f(){ rx+=(mx-rx)*0.14; ry+=(my-ry)*0.14;                    // 0.14 lerp = the lag signature
    dot.style.transform=`translate3d(${mx}px,${my}px,0)`; ring.style.transform=`translate3d(${rx}px,${ry}px,0)`;
    requestAnimationFrame(f); })();
}
```
Cursor node is `aria-hidden`, `pointer-events:none`, never focusable. **Never encode meaning in the
cursor alone.** React: keep coords in `useRef` (not state — no per-frame re-render), portal at body root.

### EXP-10 cursor-magnetic / EXP-11 morph — GSAP `quickTo` (cheap reusable tween)

```js
const xTo = gsap.quickTo(btn,'x',{duration:.4,ease:'power3'}), yTo = gsap.quickTo(btn,'y',{duration:.4,ease:'power3'});
btn.addEventListener('pointermove', e=>{ const r=btn.getBoundingClientRect();
  xTo((e.clientX-(r.left+r.width/2))*0.3); yTo((e.clientY-(r.top+r.height/2))*0.3); });  // STRENGTH ≤ 0.35
btn.addEventListener('pointerleave', ()=>{ xTo(0); yTo(0); });
```
Magnetic displacement is decorative — the real button keeps full hit area + focus ring. Morph: hovered
`[data-cursor="view"]` toggles a `.is-view` class that grows the ring + reveals an `aria-hidden` label.

### EXP-12 dom-mouse-parallax-tilt — `@property` interpolation (CSS-only Squarespace cousin)

```css
@property --mx { syntax:"<number>"; inherits:false; initial-value:0; }
@property --my { syntax:"<number>"; inherits:false; initial-value:0; }
.tilt { transform: perspective(800px) rotateX(calc(var(--my)*-10deg)) rotateY(calc(var(--mx)*10deg));
        transition: --mx .2s ease-out, --my .2s ease-out; transform-style: preserve-3d; }
@media (prefers-reduced-motion: reduce),(hover:none),(pointer:coarse){ .tilt{ transition:none; transform:none; } }
```
`pointermove` writes `--mx/--my` in -0.5..0.5; registered props interpolate so sparse events still glide.

### EXP-13 webgl-mouse-parallax-gallery — R3F (the Squarespace "Made with Squarespace")

```jsx
'use client';                                  // + dynamic(()=>import('./Gallery'),{ssr:false})
function Grid(){ const group=useRef(); useFrame((state,delta)=>{      // state.pointer is normalized -1..1
  group.current.rotation.x = THREE.MathUtils.damp(group.current.rotation.x, state.pointer.y*0.15, 4, delta);
  group.current.rotation.y = THREE.MathUtils.damp(group.current.rotation.y, state.pointer.x*0.15, 4, delta);
}); return <group ref={group}>{URLS.map(u=> <Image key={u} url={u} position={[...]} />)}</group>; }
// reduced-motion / touch / no-WebGL → return <PosterFallback/> (static <img>), never mount <Canvas>
```
`THREE.MathUtils.damp` is frame-rate-independent (preferred over fixed-alpha lerp). One canvas, one
group. Cap `dpr={[1,2]}`. On touch there's no hover → ship the static poster. **A CSS `preserve-3d`
tilt (EXP-12) fakes this far cheaper** — only go WebGL if you need real depth/many textured planes.

### EXP-14 webgl-image-displacement — OGL ~8 KB, ONE canvas many meshes

Displacement/RGB-shift fragment shader; `uMouse`/`uHover`/`uVelocity` uniforms fed by pointer + scroll
velocity. **The 16-canvas trap (sondaven/vaulk naive pattern): browsers cap ~16 live WebGL contexts —
the oldest is dropped → images blank.** Use **one canvas + one scene with many meshes**, each mesh
positioned over its DOM image via a synced scroll offset (OGL, or R3F drei `<View>`/`<ScrollControls>`).
curtains.js is purpose-built for DOM↔WebGL sync but lightly maintained — prefer OGL/R3F for new builds.
Client-only; reduced-motion/mobile → plain decoded `<img>`, skip the WebGL layer entirely.

### EXP-15 image-masked-text — `background-clip:text` (MUST ship a solid fallback)

```css
.masked-text { color: #fff; }                  /* visible fallback — text must NEVER vanish */
@supports (background-clip: text) or (-webkit-background-clip: text) {
  .masked-text { background: url('/grain.jpg') center/cover; background-clip:text; -webkit-background-clip:text;
                 color: transparent; -webkit-text-fill-color: transparent; }
}
.masked-text::selection { color:#000; background:#fff; -webkit-text-fill-color:#000; }  /* selection stays visible */
```
Keep it real selectable text (searchable/translatable/zoomable). Verify image luminance gives AA behind glyphs.

### EXP-16 editorial-oversized-type — fluid `clamp()` + container query units

```css
.hero { container-type: inline-size; }
.hero__title { font-size: clamp(2.5rem, 18cqi, 12rem);  /* max ≤ 2.5× min for a11y zoom */
               line-height:.9; letter-spacing:-.02em; text-wrap: balance; }
```

### EXP-17 dynamic-recolor-on-scroll — swap VETTED PAIRS (the #1 recolor a11y trap)

```css
:root { --bg:#0b0b0f; --fg:#f5f5f5; background:var(--bg); color:var(--fg);
        transition: background-color .6s, color .6s; }
[data-theme="cream"]{ --bg:#f4efe6; --fg:#16130d; }    /* both swap together → AA preserved */
@media (prefers-reduced-motion: reduce){ :root{ transition:none; } }   /* instant cut, still themed */
```
IO adopts the most-visible section's palette. **Every pair is contrast-checked AS A PAIR (4.5:1 / 3:1)
so no intermediate state drops legibility.** Derive focus-ring color from `--fg`. OKLCH `color-mix(in
oklch, …)` gives perceptually-even hue travel via a registered `--t` progress prop.

### EXP-18 animated-color-pattern — `@property <angle>` conic / mesh gradients (S-1 only)

```css
@property --angle { syntax:"<angle>"; inherits:false; initial-value:0deg; }
.aurora { background: conic-gradient(from var(--angle) in oklch longer hue, oklch(.7 .2 20), oklch(.7 .2 200), oklch(.7 .2 20));
          animation: spin 12s linear infinite; }
@keyframes spin { to { --angle: 360deg; } }
@media (prefers-reduced-motion: reduce){ .aurora{ animation:none; } }
```
**Never place body text directly on a live gradient** — contrast drifts as it animates; use a scrim
panel. Marketing-surface only; pause offscreen via IntersectionObserver to save battery.

---

### anime.js family — EXP-20..25 (lightweight, dependency-free; native-first where it exists)

```js
import { animate, stagger, svg, createTimeline, createDraggable, scrambleText } from 'animejs';
// v4 has NO global `anime` object — named ESM imports only; tree-shakes to what you actually use.
// React: wrap in createScope so every instance auto-cleans on unmount:
//   useEffect(() => { const scope = createScope({ root }).add(() => { /* animate(...) */ });
//                     return () => scope.revert(); }, []);
```

**EXP-20 svg-line-draw** — native first (0 KB, RSC-safe); anime.js for multi-path orchestration:
```css
.stroke { stroke-dasharray: var(--len); stroke-dashoffset: var(--len); }
@supports (animation-timeline: view()) { @media (prefers-reduced-motion: no-preference) {
  .stroke { animation: draw linear both; animation-timeline: view(); animation-range: entry 10% cover 40%; }}}
@keyframes draw { to { stroke-dashoffset: 0; } }
```
```js
const drawables = svg.createDrawable('.stroke');                       // auto-measures every path
animate(drawables, { draw: '0 1', ease: 'inOutQuad', duration: 1200 });// reduced-motion → set draw '0 1' instantly
```

**EXP-21 svg-shape-morph** — no robust native path; `morphTo` handles differing point counts:
```js
animate('#blob', { points: svg.morphTo('#target-blob'), ease: 'inOutCirc', duration: 800 });
// reduced-motion: snap to the target `points`, duration 0. Keep both paths in the same viewBox.
```

**EXP-22 motion-path-follow** — native `offset-path` is Baseline (prefer it); anime.js to timeline-sync:
```css
.mover { offset-path: path('M0,0 C40,80 120,80 160,0'); animation: move 4s linear infinite; }
@keyframes move { to { offset-distance: 100%; } }
@media (prefers-reduced-motion: reduce){ .mover{ animation: none; offset-distance: 100%; } }
```
```js
const { translateX, translateY, rotate } = svg.createMotionPath('#path');
animate('.mover', { translateX, translateY, rotate, ease: 'linear', duration: 4000, loop: true });
```

**EXP-23 grid-stagger-ripple** (the animejs.com hero) — grid-distance stagger is anime.js's signature; native only does 1-D delay:
```js
animate('.cell', { scale: [1, 0.2, 1], delay: stagger(80, { grid: [COLS, ROWS], from: 'center' }),
  ease: 'inOutSine', loop: true });           // ripples outward from center; from:'first'|index also work
// reduced-motion: drop loop + delay, or skip entirely (decorative).
```

**EXP-24 text-scramble-decode** — `scrambleText` (no native equivalent):
```js
animate('.headline', { scrambleText: { chars: 'A-Z0-9' }, duration: 1400, ease: 'out(3)' });
// Keep the resolved text as real DOM text (aria-label the element) so SR reads the word, not the scramble.
// reduced-motion: render final text immediately, skip the scramble.
```

**EXP-25 draggable-throw-physics** — `createDraggable` (spring/flick/snap; manual otherwise):
```js
createDraggable('.card', { releaseEase: 'spring(1, 80, 12, 0)', snap: 24,    // snap grid in px
  container: '.bounds', releaseContainerFriction: 0.9 });
// S-2: reorderable lists / kanban only, and a keyboard-operable alternative is REQUIRED (never drag-only).
// S-1: throw-and-settle gallery cards. Never the SOLE way to perform an action (a11y).
```

---

## §5 — Critical 2026 facts (override training-weight beliefs)

**Last-verified:** 2026-06-17 — time-sensitive claims (licensing, Baseline coverage, bundle
measurements); re-verify per source-registry §0 triggers (T2/T3) when stale or relied on.

1. **GSAP is 100% FREE for all commercial use** — Webflow acquired GreenSock (Oct 2024); as of 30 Apr
   2025 the *entire* toolkit is free, including the formerly-paid **SplitText, MorphSVG, DrawSVG,
   ScrollTrigger, ScrollSmoother, Inertia**. SplitText was rewritten ~50% smaller with native `mask:'lines'`.
   **Do NOT flag GSAP as a license blocker** (the old motion-vocabulary §10 "freemium/paid" note is obsolete).
2. **Native scroll-driven animations are NOT Baseline.** `animation-timeline: scroll()/view()` ship in
   **Chrome/Edge 115+ and Safari 26 (Sep 2025) but NOT Firefox.** Every native scroll-driven recipe
   MUST carry the feature gate + a JS fallback for functional (non-decorative) motion:
   ```css
   @supports ((animation-timeline: view()) and (animation-range: entry)) { /* native */ }
   ```
   **Do NOT use `scroll-timeline-polyfill`** (Chrome guidance: "not feature complete, lots of known
   issues"). Hand-roll an IntersectionObserver fallback, or accept graceful degradation for decoration.
3. **`scroll-behavior: smooth` IS Baseline** (~95%, Safari 15.4+) — the 0-JS answer for anchor smoothing.
   It does NOT smooth wheel scroll; wheel inertia is inherently JS (Lenis).
4. **The 16-canvas WebGL-context cap** — many `<canvas>` (sondaven 16, vaulk 7) is the naive per-image
   pattern; it hits the browser's ~16 live-context limit → images blank. Always one canvas + many meshes.
5. **anime.js v4 is MIT, zero-dependency, ESM-first, and aggressively tree-shakeable** (`sideEffects:false`,
   verified via bundlephobia). The *full* bundle is ~75.6 KB min / **~26 KB gzip**. Tree-shaking helps but does
   NOT reach a few KB: `animate` carries the core engine (~11.8 KB gz), so a real `{animate, stagger, createScope}`
   hook measures **~13.9 KB gz** (Bun.build-measured on a representative app) — **budget ~14 KB, not ~4–6 KB**; a
   namespace `* as` import balloons to ~41 KB (a default import is a v4 build error), so ALWAYS use named imports.
   It is NOT a WebGL lib — it animates DOM / CSS / SVG / plain
   JS objects through one unified API, and it dogfoods animejs.com itself (single `scripts.js`, no
   framework). v4 **removed the global `anime` object** — named ESM imports only: `import { animate, stagger,
   svg, createTimeline, createScope, createDraggable, scrambleText } from 'animejs'` (v3's `anime({targets})`
   → v4's `animate(target, opts)`; `anime.path()` → `svg.createMotionPath()`; `setDashoffset` →
   `svg.createDrawable()`). React integration is `createScope()` + `useEffect`. It is the **default
   dependency-free engine for dynamic SVG, grid-staggered choreography, scramble text, and spring-drag** —
   on BOTH experiential (EXP-20..25) and restrained tool surfaces (microinteractions). This is the flagship
   answer to the §0 anti-monoculture mandate: do NOT flag it as a license or bundle blocker.

---

## §6 — Library matrix (experiential)

**Last-verified:** 2026-06-17 — re-verify per source-registry §0 triggers (T2/T3) when stale or relied on.

| Library | React 19 | RSC | Bundle (min+gzip) | License | Covers |
|---|---|---|---|---|---|
| **Lenis** (`lenis` 1.3.x) | yes (`lenis/react`) | client-only (`'use client'`) | ~3 KB | MIT | EXP-1 |
| **GSAP** core + ScrollTrigger | yes (`@gsap/react` `useGSAP`) | client-only | ~70 KB combined | **FREE (all commercial)** | EXP-2..6, EXP-8, EXP-10 |
| GSAP SplitText | yes | client-only | small plugin | **FREE** | EXP-8 |
| Locomotive Scroll v5 | yes | client-only | ~9.4 KB | MIT | EXP-1, EXP-6 |
| **Three.js** | yes | client-only (`dynamic ssr:false`) | ~150 KB | MIT | EXP-13, EXP-14 |
| **@react-three/fiber** | yes | client-only | ~60 KB | MIT | EXP-13, EXP-14 |
| @react-three/drei | yes | client-only | named imports only | MIT | EXP-7, EXP-13, EXP-14 |
| **OGL** | yes (manual) | client-only | ~8 KB core | MIT | EXP-14 |
| **anime.js** (`animejs` 4.x) | yes (`createScope`+`useEffect`) | client-only (`'use client'`) | **~14 KB gz** typical hook (animate+stagger+createScope), ~26 KB full · tree-shakeable, 0 deps | **MIT** | EXP-8 (alt), EXP-20..25; tool microinteractions too |
| Native CSS SDA / `@property` / `background-clip` | n/a | **RSC-safe (0 JS)** | 0 KB | — | EXP-2..6, EXP-12, EXP-15..18 |

**Rule:** native CSS scroll-driven animation is more performant (off-main-thread), 0 KB, AND RSC-safe —
use it by default; add a JS lib only when the effect is functional and Firefox/old-Safari coverage is
required, or when you need true WebGL per-pixel interactivity.

---

## §7 — Unconditional accessibility locks (apply on EVERY surface, S-1 included)

The challenger flags these as BLOCKERs regardless of surface type:

- **`prefers-reduced-motion: reduce`** honored for every EXP technique — disable lag/lerp/scrub/scale/
  drift; WebGL → static poster; never leave split text at `opacity:0`; recolor cuts instantly.
- **Touch / coarse pointer** — custom cursors (EXP-9/10/11) gated behind `(hover:hover) and
  (pointer:fine)`; native cursor NEVER hidden on touch or for keyboard users.
- **Keyboard / focus** — custom cursor is pointer-only (`pointer-events:none`, not focusable, never
  traps focus). Real focus rings survive every recolor.
- **Contrast across recolor (EXP-17)** — swap vetted *pairs*; AA (4.5:1 / 3:1) holds at every state.
- **Masked text (EXP-15)** ships a solid-color fallback so headings never vanish; stays real text.
- **No motion that obscures (AP-6) or blocks-click (AP-7)** content; no auto-playing audio.
- **Mobile/perf budget** — WebGL drains battery/GPU; default to a static fallback on mobile unless the
  WebGL effect IS the core product. One Lenis instance, one canvas, capped `dpr`.

---

---

## §3 addendum — [EXP-19 depth-keyed-parallax-influence] (added 2026-06-07)

**Run:** dashboard-homepage-2026-q2

**What it is:** Within a 3D plane group OR a CSS `preserve-3d` tilt grid, each element receives a `--depth`
(or Z-position) that **scales its response to the pointer/scroll input**. Front elements barely move; deep
elements move proportionally more (amplified multiplier). The viewer perceives layered depth purely from
differential movement, without needing true Z-axis separation in 3D space. This is the perceptual
mechanism underlying both [EXP-13] (real Z in WebGL, Squarespace) and the CSS cousin [EXP-12] (simulated
Z via `--depth * multiplier`). It is an *enhancement* to EXP-12 or EXP-13, not a standalone primitive —
cite alongside the host token.

**Exemplar:** Codrops "Building a Scroll-Reactive 3D Gallery" (2026-03-09, three.js, plain JS/Vite):
`plane.position.x += pointerX * parallaxAmount * parallaxInfluence` where `parallaxInfluence` scales
with Z-depth. Also applies to any CSS `preserve-3d` grid where `--depth: 0|1|2` is assigned per card.

**Native-first (CSS, 0 KB):**
```css
/* Assign --depth: 0 | 1 | 2 on each .panel-card via JSX style attribute */
.panel-card {
  --tilt-amp: calc(1 + var(--depth, 0) * 0.4);
  transform:
    rotateX(calc(var(--my) * -8deg * var(--tilt-amp)))
    rotateY(calc(var(--mx) *  8deg * var(--tilt-amp)));
}
@media (prefers-reduced-motion: reduce),(hover:none),(pointer:coarse){
  .panel-card { transform: none; }
}
```

**Library path (R3F/three.js):**
```js
// in useFrame — depth is a per-mesh data attribute (0..2)
meshes.forEach(m => {
  const amp = 1 + m.userData.depth * 0.4;
  m.position.x = THREE.MathUtils.damp(m.position.x, state.pointer.x * 0.15 * amp, 4, delta);
  m.position.y = THREE.MathUtils.damp(m.position.y, state.pointer.y * 0.15 * amp, 4, delta);
});
```

**Bundle:** 0 KB (CSS path); three.js ~150 KB if using WebGL path.
**License:** n/a (CSS); MIT (three.js/R3F).
**RSC:** RSC-safe for CSS path; `'use client'` + `dynamic ssr:false` for R3F.
**Reduced-motion:** same as host EXP-12 / EXP-13 — kill all transforms on `prefers-reduced-motion: reduce`; touch/coarse → flat.
**Surface:** S-1 / S-1m. Never S-2.

---

## §3 addendum — [EXP-26 liquid-glass-nav] (added 2026-06-17)

**Run:** web-console-glassbar

**What it is:** A sticky top navigation bar or toolbar styled with `backdrop-filter: blur()` + semi-transparent
background + hairline border, creating a frosted-glass "liquid glass" material that blurs the content beneath
it. Optionally enhanced with `@container scroll-state(stuck: top)` to deepen the blur/opacity once the bar is
actually stuck. The "expand on interaction" variant opens a Radix Popover / DropdownMenu from a trigger in the
bar, styled with the same glass material at higher opacity. This is a **chrome upgrade**, not a data-surface
motion effect — it applies to the structural navigation layer of a tool app, not its data grids or lists.

**Exemplar:** new.studio navigation (Next.js; pure CSS; 0 canvas, 0 animation library); Josh W. Comeau
"Next-level frosted glass with backdrop-filter" (`https://www.joshwcomeau.com/css/backdrop-filter/`, 2025);
ICS Media "Using CSS @container scroll-state() for sticky headers" (`https://ics.media/en/entry/250602/`, 2025).

**Native-first (0 KB, RSC-safe):**
```css
.glass-toolbar {
  backdrop-filter: blur(14px) saturate(180%);
  -webkit-backdrop-filter: blur(14px) saturate(180%);
  background: rgba(var(--color-toolbar-from-rgb), 0.65);
  border-bottom: 1px solid rgba(255, 255, 255, 0.07);
  box-shadow: 0 1px 20px rgba(0, 0, 0, 0.3);
}
/* Progressive-enhancement: deepen glass when sticky bar is actually stuck (Chrome 133+) */
@supports (container-type: scroll-state) {
  .glass-toolbar-wrapper { container-type: scroll-state; }
  @container scroll-state(stuck: top) {
    .glass-toolbar { backdrop-filter: blur(18px) saturate(200%); background: rgba(var(--color-toolbar-from-rgb), 0.80); }
  }
}
/* Solid fallback for non-supporting browsers */
@supports not (backdrop-filter: blur(1px)) {
  .glass-toolbar { background: var(--color-toolbar-from); }
}
@media (prefers-reduced-motion: reduce) { .glass-toolbar { transition: none; } }
```

**Library:** None required. Add Radix Popover for the expand drawer (keyboard a11y: trap, Escape to close).
**Bundle:** 0 KB CSS; ~5 KB gzip Radix Popover (optional).
**License:** n/a (CSS); MIT (Radix).
**RSC:** RSC-safe for the CSS; `'use client'` for the Popover trigger state (standard for interactive nav).
**Reduced-motion:** `backdrop-filter` is a material, not a motion effect. `transition: none` on reduce — instant change, still glassy.
**Surface:** **S-2-OK (chrome/nav element only)** — this is the rare EXP technique acceptable on a tool surface because it applies to structural chrome, not data content. Confirmed: Linear, Vercel, and Notion all ship `backdrop-filter` headers in production tool apps. NEVER apply to data grids, list views, or table surfaces.

---

## §3 addendum — [EXP-27 dom-3d-carousel] (added 2026-06-17)

**Run:** web-console-glassbar

**What it is:** An interactive 3D browsing carousel for a collection of cards. Cards are absolutely positioned
in a `perspective: 1800px` / `transform-style: preserve-3d` stage. Each card's position is computed per rAF
frame from a normalized distance from the center item: `translate3d(norm*spread, 0, invNorm*depth)` +
`rotateY(-norm*angle)` + `scale(base + invNorm*scaleRange)`. Pointer/wheel/drag events write to a velocity
variable that decays each frame via friction (0.85–0.90), creating inertial throw physics with no library. An
infinite loop is achieved via modulo on the item-index offset. **Not WebGL. Not scroll-driven at the page
level.** This is a self-contained interactive widget — the rest of the page scrolls normally.

**Exemplar:** detroit.paris media-slider (Webflow-hosted, DOM-only, 0 canvas); Codrops "Building a 3D Infinite
Carousel with Reactive Background Gradients" (2025-11-11, `https://tympanus.net/codrops/2025/11/11/building-a-3d-infinite-carousel-with-reactive-background-gradients/`).

**Native-first (0 KB, vanilla JS + CSS):**
```css
.carousel-stage { perspective: 1800px; perspective-origin: 50% 50%; position: relative; height: 320px; }
.carousel-card  { position: absolute; left: 50%; top: 50%; will-change: transform; backface-visibility: hidden; }
@media (prefers-reduced-motion: reduce) { .carousel-stage { display: none; } /* grid fallback renders */ }
```
```js
// 'use client' — useEffect + cleanup
let vX = 0, offset = 0, rafId;
const FRICTION = 0.88;
function frame() {
  vX *= FRICTION;
  offset += vX;
  const N = cards.length;
  cards.forEach((card, i) => {
    const raw = ((i - offset % N) + N) % N;
    const norm = raw < N/2 ? raw/(N/2) : (raw - N)/(N/2); // -1..1
    const inv = 1 - Math.abs(norm);
    card.style.transform = [
      `translate3d(calc(-50% + ${norm * 240}px), -50%, ${(inv-1)*100}px)`,
      `rotateY(${-norm * 28}deg)`, `scale(${0.78 + inv * 0.22})`
    ].join(' ');
    card.style.opacity = String(0.4 + inv * 0.6);
    card.style.zIndex  = String(Math.round(inv * 100));
  });
  rafId = requestAnimationFrame(frame);
}
// Start on mount; cancel on unmount: return () => cancelAnimationFrame(rafId)
```

**Library path:** anime.js `createDraggable` for throw/snap-to-grid physics; `animate` for active-card settle.
**Bundle:** 0 KB (vanilla); ~14 KB gz if anime.js is added (animate+stagger+createScope hook; amortizes across tool microinteractions).
**License:** n/a (vanilla); MIT (anime.js).
**RSC:** `'use client'` + `useEffect` (pointer/wheel events, rAF). Standard Next.js client component.
**Reduced-motion:** Entire `.carousel-stage` is `display: none`; a static CSS grid replaces it. No carousel renders.
**Surface:** S-1 encouraged; **S-1m / S-2-restrained** — on a tool surface (S-2), the carousel MUST be an opt-in toggle (not the default), a static grid MUST be the always-rendered fallback, keyboard arrow-key navigation of the active card is required, and the carousel collapses to grid on mobile (max-width: 600px). Never apply as the sole content-browsing surface.

---

## How to evolve this catalog

When the `frontend-uplift-experiential-scout` reverse-engineers a NEW experiential primitive not in §3,
append it as `[EXP-N+1]` with: exemplar site + detected stack, native-first path, library path, bundle/
license, RSC note, reduced-motion fallback, and surface tag. New critical facts (browser-support shifts,
license changes) go in §5. This file + `.claude/references/frontend-uplift-motion-vocabulary.md` together are the motion
institutional memory across runs.
