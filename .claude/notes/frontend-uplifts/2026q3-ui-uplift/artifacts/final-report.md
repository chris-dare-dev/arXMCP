# Final report — 2026q3-ui-uplift

**Run:** `2026q3-ui-uplift` · **Mode:** standard (5 scouts) · **Surface:** `tool` (S-2 wholesale)
**Candidates:** 26 catalogued · 20 ranked in 5 lanes · **6 killed / parked** · **1 added by the challenger**
**Challenge:** 0 BLOCKER · 9 MAJOR · 10 MINOR · 7 NONE (27% NONE, unpadded)
**Artifacts:** [`synthesis.md`](synthesis.md) · [`challenge.md`](challenge.md) · [`discover/`](../discover/) (5 briefs + visual manifest)

---

## 1. Executive summary

**The premise in the brief is wrong and the perception behind it is right.** There is no Tailwind and
no shadcn anywhere in this codebase — no utility classes, no component directory, no `cn()`/CVA, no
Node, no build chain (CLAUDE.md §4.7 forbids them). `/ui/` is **371 lines / 52 CSSOM rules** of
hand-authored CSS, three Jinja2 templates, and one vendored `htmx.min.js`. Four of five briefs reached
that correction independently. What actually makes it read as generic is measurable, and the run named
it: **the dark palette is a self-documented GitHub-Primer clone** (`app.css:234-241` says so in its own
comment, and the hexes are GitHub's exact values), **seven visually identical `.card`s** carry the
whole detail page, there is **one effective type step** (32px → 17.6px → 16px, so h2/body contrast is
weight alone), **zero `box-shadow`**, **zero `letter-spacing`**, and **zero `transition`** in the entire
file. Cookie-cutter score **6/13** — the "generic AI dashboard" band edge — reached without a single
line of shadcn.

**Top pick per lane:** a11y — **UPL-27** fix two already-shipped WCAG AA contrast failures ·
signature — **UPL-3** author a two-voice type scale · foundations — **UPL-7** every emitted class ships
its CSS rule · workflow — **UPL-8/UPL-10** finish the unstyled form controls and the ingest error ·
polish — **UPL-15a** row hover tint.

**Theme.** Nearly every finding traces to one root cause the current-state critic named exactly:
*feature milestones shipped complete, tested, secure behaviour and left CSS as an afterthought scoped
to "does it render," not "does it look finished" — because no milestone's acceptance criteria ever said
"style this."* Four separate server-emitted class families ship with **zero CSS rule anywhere**. The
security and correctness discipline in this repo is genuinely strong; finish-level visual polish has
simply never been a milestone's job description.

**Caveat, load-bearing.** **There are zero screenshots this run** — the Browser pane was never
displayed, so the page never composited frames. Everything rests on live-measured DOM geometry +
computed styles + a full source read. Per canon §14 that is enough to audit the **anti-pattern** half
of the score and not enough to gate the **positive** (design-quality) half. Second caveat: the
challenger's honest read is that **UPL-1 through UPL-7 is a full milestone stretch by itself** — this
is roughly three quarters of work, not one.

---

## 2. Design frame recap

> **arXMCP's console is the bench record of a one-person mathematics lab: every notebook is a named
> body of literature with a stated question, a provenance trail, and a parse-and-index state the
> operator can read as a metered fact — and the console shows the corpus before the machinery that
> mutates it.**

**Direction: D-1 "The Ledger Sheet"** — retire `.card` as a primitive; a graded hairline rule ladder
carries all structure; `--mono` becomes a true data voice on every id/path/slug/timestamp/version; the
row is the unit of interaction.

**Honesty correction the challenger insisted on, and it is right:** this run **confirms and sharpens
the overlay's already-declared house direction (D-A "Precision Instrument")** — it did not discover a
new one. Four of D-1's five traits (hairline elevation, mono data voice, tracked micro-caps, posture
lede) appear verbatim in the canon's own list of its emergent house look. Where D-1 is genuinely
arXMCP-specific — **the row as the unit of interaction**, `--mono` on every identifier *because those
are this product's primary data*, and **deleting the box on a page whose content is a bibliography** —
lead with those. "Hairlines and micro-caps" is not the differentiator.

**Six invariants:** I-1 operational honesty · I-2 provenance & freshness as metered facts · I-3 calm at
repeat use · I-4 sovereign minimalism · **I-5 corpus before machinery** · **I-6 domain legibility**.

**Must be removed:** BAN-2 (equal card stack) · BAN-4 (default-stack look) · BAN-5 (no focal element) ·
BAN-9 (multiple primary CTAs per viewport) · BAN-14 (uniform density) · BAN-15 (borrowed silhouette).
**Must not be introduced:** **BAN-3** (icon tiles — the product has zero icons and that is an asset;
the single most likely "make it prettier" regression) · BAN-1 (a second accent) · BAN-6 (unannotated
charts) · BAN-7 (badge soup — a *per-view* threshold of ~5, not per-row) · BAN-8 (glow/glass) ·
**BAN-10** (the current copy is a genuine strength — no "Welcome back", no "Command Center") · BAN-11
(semantic colour used decoratively) · BAN-13 (KPI stat tiles).
**Run-scoped:** **BAN-R1** form-first page order · **BAN-R2** unstyled-fragment debt · **BAN-R3**
instrument without a reading.

**Projected end-state score (computed by the challenger, missing from my synthesis): 2/13** on the
recommended path — a PASS on the anti half — **rising to 4–5 ("template-leaning") if UPL-20 ships as a
coloured chip or UPL-24 ships.** Those two are the only candidates that push the program back out of
band. The DQS half stays UNVERIFIED until real screenshots exist.

---

## 3. Quick-glance ranking (grouped by lane; RICE computed WITHIN lane only)

### Lane 1 — a11y-safety-debt (mandatory; never ranked away)

| # | Candidate | Size | Verdict | RICE |
|---|---|---|---|---|
| 1 | **UPL-27** — Fix two already-shipped WCAG AA contrast failures | XS | *challenger-derived* | 20.0 |
| 2 | **UPL-22** — Fix the reduced-motion preference listener | XS | NONE | 20.0 |
| 3 | **UPL-6** — Authored density + `pointer: coarse` 44px touch floor | S | NONE | 3.0 |
| 4 | **UPL-13 v0** — Stop the 2s poll re-announcing; drop 6 empty live regions | S | MAJOR | 2.25 |

### Lane 2 — signature-direction

| # | Candidate | Size | Verdict | RICE |
|---|---|---|---|---|
| 1 | **UPL-3** — Author a two-voice type scale | S–M | NONE | 19.5 |
| 2 | **UPL-2** — Retire `.card`; adopt the graded hairline rule ladder | M | MINOR | 9.75 |
| 3 | **UPL-4** — De-Primer the material: one authored OKLCH family | M | MAJOR | 7.31 |
| 4 | **UPL-1 v0** — Reorder the detail page: corpus before machinery | M | MAJOR | 5.63 |
| 5 | **UPL-5 v0** — A posture lede for the notebook | M | MINOR | 5.25 |

### Lane 3 — foundations

| # | Candidate | Size | Verdict | RICE |
|---|---|---|---|---|
| 1 | **UPL-7** — Every server-emitted class ships with its CSS rule (+ a guard test) | S–M | NONE | 6.5 |
| 2 | **UPL-16** — Container-query the form layout | S | NONE | 2.1 |

### Lane 4 — workflow

| # | Candidate | Size | Verdict | RICE |
|---|---|---|---|---|
| 1 | **UPL-8 v0** — `select` / `textarea` sizing parity | XS | MINOR | 8.4 |
| 2 | **UPL-10 v0** — Ingest failure gets the house `pre.error` treatment | XS | MINOR | 8.4 |
| 3 | **UPL-9** — Style the Discover-results candidate list | S | MINOR | 6.3 |
| 4 | **UPL-26** — First-ever inline validation state (`:user-invalid`) | XS | MINOR | 3.6 |
| 5 | **UPL-20 v0** — Surface `notebook_kind` as micro-caps text (NOT a chip) | XS | MAJOR | 3.15 |
| 6 | **UPL-12 v0** — `:has()` region-level in-flight cue | S | MINOR | 3.0 |
| 7 | **UPL-11** — Replace `window.confirm()` with an in-language `<dialog>` | M | MINOR | 2.25 |
| 8 | **UPL-21** — Author the four empty states (cause + one action) | S | NONE | 2.1 |
| 9 | **UPL-17′** — De-duplicate the error handler with an in-repo helper | XS | MAJOR* | 0.45 |
| 10 | **UPL-23 v0** — `/` focuses the primary input on `index.html` | S | MINOR | 0.35 |

\* MAJOR applies to the *vendored* form, which is killed; the redesigned in-repo form is what is ranked.

### Lane 5 — polish

| # | Candidate | Size | Verdict | RICE |
|---|---|---|---|---|
| 1 | **UPL-15a** — Table row hover tint | XS | NONE | 4.2 |
| 2 | **UPL-14** — `#ingest-status` settle flash | XS | NONE | 1.8 |
| 3 | **UPL-19a** — `@view-transition { navigation: auto }` (at-rule only) | XS | MINOR | 1.8 |

**RICE-light:** Reach (1/3/10) × Visual-Impact (0.5/1/3) × Triangulation-Confidence (0.3–1.0) ÷
Effort (XS 0.25 · S 1 · S–M 2 · M 4 · L 8); −25% on MAJOR; +30% foundational bonus (UPL-2, UPL-3,
UPL-4, UPL-7).

> **Rank is not sequence.** The DAG overrides it: **UPL-4 → UPL-2**, **UPL-3 → UPL-2**,
> **UPL-2 → UPL-6/UPL-12/UPL-16**, **UPL-1 ↔ UPL-21** (hard pair), **UPL-1 → UPL-13**,
> **UPL-1 → UPL-23**, **UPL-13 → UPL-14**, **UPL-11 ⊗ UPL-15b** (mutually exclusive). See §5.

---

## 4. Lane-by-lane detail

### Lane 1 — a11y-safety-debt

**UPL-27 — Fix two already-shipped WCAG AA contrast failures** *(added by the challenger)*
The overlay asserts "every pair clears AA in both themes." True of the eight token pairs it lists;
**false of the stylesheet.** Recomputed from WCAG 2.1 relative luminance: `.card .note` / `.card
.empty` at `#777` on `--card-bg #fff` = **4.478:1** (`app.css:63-64`, 12.8px italic — not large text)
and `.status-badge--ok` at `#1a7f37` on `#e6f4ea` = **4.472:1** (`app.css:165`, 12px/600 — not large
text). Both fail SC 1.4.3. This matters beyond the fix: **UPL-4's stated gate ("a pair dropping below
4.5:1 is a BLOCKER") would otherwise fire on a baseline that was never clean.** Related, also from the
challenger: the true tightest *rendered* token pair is dark `--danger #f85149` on `--error-bg #2a1a18`
(the `pre.error` rendering) at **4.97:1 — 0.47 of headroom, not the 0.66 my synthesis claimed** — and
it appears in neither the overlay table nor my catalog. Fix these as *named defects*, and re-scope
UPL-4's gate from "the overlay §4 table" to **"every rendered foreground/background pair."**

**UPL-22 — Fix the reduced-motion preference listener** · *NONE — the cleanest item in the run*
`base.html:38-45` reads `matchMedia('(prefers-reduced-motion: reduce)')` **once** inside
`DOMContentLoaded` and never registers a `change` listener, so an operator who flips their OS setting
mid-session keeps view transitions until a full reload. The three CSS gates (`app.css:223`, `:317`,
`:344`) react live because `@media` re-evaluates continuously; only this one JS read is stuck. ~4
lines, existing block, existing CSP, no new file. **Sequence this first — it costs nothing and blocks
nothing.**

**UPL-6 — Authored density + `pointer: coarse` touch floor** · *NONE*
Measured: every `button` is **32px tall**, `<select>` **19px**, footer links **17px**. Keying the 44px
floor to `@media (pointer: coarse)` rather than a width breakpoint fixes the real problem (touch)
instead of the proxy (narrow window) — the challenger called this "the kind of choice that
distinguishes an authored solution from a copied one." Also kills BAN-14 (`body { padding: 1rem }` is
currently identical at 1440px and 390px). Sequence after UPL-2 so the vertical rhythm is re-tuned once.

**UPL-13 v0 — Stop the 2s poll re-announcing** · *MAJOR — my proposed mechanism was wrong*
Twelve `aria-live` regions on one rendered page (count verified independently and it is **better than
the overlay's own figure of 24**, which counts documentation comments); six are empty `<pre
class="error">` at first paint; the 2s ingest poll re-announces **every tick**, so a screen-reader
operator gets an announcement roughly every two seconds for a whole ingest run. My "server-side delta
check, zero JS" is **not achievable** — `_ingest_status_fragment` is a pure function of the current DB
row and has no memory of what the client already rendered. **The correct zero-cost fix is different:
stop swapping the live region.** Move `aria-live` onto a stable, never-swapped wrapper — a live region
only announces *changed* text, so an identical re-render is silent by spec. Also drop `#ingest-status`
from the `<output>` migration: its failed branch emits `<pre>` (flow content) inside what would be a
phrasing-content element.

### Lane 2 — signature-direction

**UPL-3 — Author a two-voice type scale** · *NONE — the highest-value, lowest-cost move in the catalog*
Meta 11px uppercase tracked +0.06em · small 13px · body 16px · section 20px · title `clamp(1.5rem, 4vw
+ .5rem, 2.25rem)`; sans for prose, **`--mono` for every id, path, slug, timestamp, corpus version and
state token**. The 1.10× h2→body step is the literal measured form of the "untouched default stack"
tell. **Both voices are system stacks — zero font files, zero bytes, zero CSP impact.** Closes the
responsive-ramp gap in the same change via the `clamp()` idiom already at `app.css:37`. One honesty
note the challenger logged: this authors scale and tracking but **the faces do not change**, so BAN-4
scores 1 rather than 0 on the projected state.

**UPL-2 — Retire `.card`; adopt the graded hairline rule ladder** · *MINOR*
Three rule weights, horizontal only, radius → 0 on structure and 4px surviving only on interactive
controls, so geometry itself encodes structure-vs-control. **The rounded bordered Card IS shadcn's
identity; deleting it is the most direct answer to the complaint and the one move a default assembly
never makes.** My blocking a11y prerequisite is **verified correct**: light `--border #d8d8d8` on
`--bg #f8f8f8` recomputes to **1.342:1** — tolerable while borders are incidental, **failing SC
1.4.11's 3:1 non-text bar the moment rules are the sole structural device.** Three additions the
challenger requires: (a) state `--card-bg`'s successor role — it is still the dark-mode input
background and the dark `th` ground, so re-scope it to **control ground**, not panel ground; (b)
`th { background: #f0f0f0 }` is **1.14:1** on white today and effectively vanishes once the card goes
— migrate the header separation to a `--rule-section` weight under `<thead>`, or the papers table
loses its only column cue exactly when it becomes the focal content; (c) cite `#6e7681`-on-`--bg`
(4.12:1) as the dark rule pair, not on `--card-bg` (3.77:1).

**UPL-4 — De-Primer the material** · *MAJOR — gate mis-scoped, `light-dark()` fallback is hostile*
One authored OKLCH family from a single hue decision, both modes from the same source; a 4-step text
ladder; one brand accent; semantic colour reserved for live state. `#0d1117 / #161b22 / #58a6ff` is
*recognizably GitHub*, and that recognition **is** the complaint. Four corrections: **(1)** the gate
must cover **every rendered pair**, not the overlay's token×ground subset (see UPL-27). **(2)**
`light-dark()` inside a custom property fails at *substitution* in an unsupporting engine, so
`background: var(--accent)` resolves to `transparent` and `button { color: #fff }` leaves **invisible
primary buttons** — not graceful degradation. It needs `@supports` or deferral to v2 (it is Newly
Available; Widely Available lands 2026-11-13, *after* this run). **(3)** `--accent` is load-bearing in
five roles simultaneously — button ground (≥4.5:1 vs its own text), focus ring (≥3:1 vs **both**
grounds, SC 1.4.11), link colour, `.skip-link` ground, `badge-flash` tint — and the dark block already
carries a hand-patched compensation (`button { color: #0d1117 }`) whose reasoning must be *reproduced*,
not inherited. **(4)** Fold `--dur-fast: 100ms / --dur-normal: 200ms / --dur-slow: 300ms` into the same
`:root` rewrite: the motion canon requires token-referenced durations and `app.css` hard-codes `0.6s`,
`400ms`, `200ms` today with no duration tokens at all. **Split v0 (8 tokens + duration tokens + full
contrast table artifact) from v1 (fold in the ~12 grey and 8 pill literals + fix the two AA failures).**

**UPL-1 v0 — Reorder the detail page: corpus before machinery** · *MAJOR — three real corrections*
The papers table — the only corpus content — starts at **y=1823 of a 2343px document**, after six
consecutive input forms. Only cards 1–3 (all controls) sit above a 900px fold. This is the run's single
CRITICAL visual finding and its Q4 answer is the strongest in the catalog: a default assembly emits one
card per feature in authorship order, which is literally how this page was built (the milestone
comments read as a changelog). Corrections: **(a)** `[MOT-15 accordion-expand]` on native `<details>`
is **not implementable in Baseline CSS** — it needs `interpolate-size`/`calc-size()` or
`::details-content`, both Chromium-only, and my own rejected list parked `interpolate-size` as too new.
Ship with **no expand animation**; `<details>` snaps, which is fine on S-2. **(b)** My stated risk was
aimed at the wrong target: both `beforeend` swaps target `#papers-tbody`, which moves *above* the
disclosure and is never collapsed. The real failure is **invisible success** — `#ingest-status` carries
`hx-trigger="every 2s"` and would poll for a whole run inside a closed `<details>`, showing nothing.
Render the disclosure **open** whenever ingest is non-terminal, with a `<summary>` state cue.
**(c)** The `index.html` half ships a **copy regression**: `index.html:86` says "No notebooks yet.
Create one **above**," and after the reorder the form is neither above nor visible. **Hard-pair the
index half with UPL-21.** Detail page only in v0.

**UPL-5 v0 — A posture lede** · *MINOR*
One authored sentence of metered facts at 2–3× weight — kind · category · N papers · parse state **with
its meaning, not its token** · last indexed · corpus version — with **visible abstention** where the
daemon has no fact ("Never indexed"). It is the deliberate opposite of the template opener: one honest
sentence, **not four manufactured stat tiles** (BAN-13). Two corrections: **keep `<dl class="meta">` as
the machine-readable substrate in v0** and add the sentence above it — replacing `<dt>`/`<dd>` term↔value
associations with prose is an unnamed a11y trade. And answer the open question first: `/ui/api` counts
**junction rows**, which is why the `bridgeland-stability*` notebooks show 0 against large LanceDB
corpora — I-1 forbids showing a number the operator cannot trust.

### Lane 3 — foundations

**UPL-7 — Every server-emitted class ships with its CSS rule (BAN-R2)** · *NONE — "the cleanest DIRECTION-DEFINING candidate in the catalog"*
Four-brief triangulation, zero JS, zero CSP impact, zero bytes, and it names the root cause behind
nearly every HIGH finding in the run. The open question answers itself: **a test is the only version
that cannot rot**, and it is writable here because the fragments are f-strings in
`server/routes/notebooks.py` — a regex over emitted `class="…"` literals checked against `app.css`
selectors, with an allow-list for the dynamic `.status-badge--{ok,warn,ops-warn,down}` family.

**UPL-16 — Container-query the form layout** · *NONE*
A slug field expecting ~20 characters renders at **1251px**. `container-type: inline-size` +
`@container` is technically exact here: `body { max-width: clamp(640px, 92vw, 1400px) }` means a
viewport breakpoint **literally cannot see** the section's rendered width. 0 bytes, Widely Available,
and the **only** candidate that proactively named its own UPL-2 collision.

### Lane 4 — workflow

**UPL-8 v0 — `select`/`textarea` sizing parity** · *MINOR* — `select` renders **19px** against a
33px `input` in the same form row. But "one selector-list extension" will not produce visual parity:
`<select>`'s UA appearance largely ignores border/radius/background, and forcing it needs `appearance:
none`, which throws away exactly the UA internals that `color-scheme: light dark` (`app.css:10`,
documented load-bearing) exists to theme — **and then requires a dropdown indicator, i.e. the
product's first icon (BAN-3)**. v0 = the properties that work without `appearance: none`:
`font-family: inherit`, `font-size`, `padding`, `display: block`, `min-height` matching the input. That
closes the 14px mismatch, which is the actual finding.

**UPL-10 v0 — Ingest failure gets `pre.error`** · *MINOR — "the highest value-per-character item in the catalog"*
`server/routes/notebooks.py:2379-2381` is literally `f"<pre>{stderr_tail}</pre>"` while every sibling
error surface uses `pre.error`. The **failed corpus ingest — the most operationally important error an
operator will ever read here** — gets none of the tinted `--error-bg` / `--danger` alarm treatment.
`stderr_tail` is already `html.escape`'d. **One line.** Standalone this rates NONE; the MINOR is
entirely for the bundled status icon, which walks into BAN-3 unremarked — **defer any icon to v2**,
behind the same explicit decision UPL-21 forces.

**UPL-9 — Style the Discover-results list** · *MINOR* — Five server-emitted classes
(`.discover-list/-candidate/-title/-meta/-abstract`) with **zero CSS rules**. This is the only surface
in the console presenting external content for operator judgment, and it is the least-styled thing in
the product — a bare bulleted `<ul>`. The purest BAN-R2 closure available. **Drop the `[MOT-1 fade-in]`
I proposed** — `globalViewTransitions` already crossfades that exact swap at 200ms, so a fade keyframe
would double-animate.

**UPL-26 — `:user-invalid`** · *MINOR* — `app.css` has **zero validation-state styling**, not even an
`:invalid` rule, while seven forms carry native constraints (`pattern="[a-z][a-z0-9-]{2,30}"` on the
slug). Must pair the colour cue with a **non-colour** channel (border width, `::after` text, or
`aria-invalid` + `aria-describedby`) or it is an SC 1.4.1 Use-of-Color problem, and must use `--danger`,
not a literal.

**UPL-20 v0 — `notebook_kind` as micro-caps text, NOT a chip** · *MAJOR — the vehicle was wrong*
The need is real: `notebook_kind` appears **0 times** in `index.html`, so an operator must open every
notebook to learn whether it is `arxiv` or `textbook`. But my proposed guard ("one chip per row")
**measures the wrong unit** — BAN-7 is a *per-view* threshold of ~5, and one chip per row at six
notebooks plus the footer badge is **7 visible chips**. Worse, painting a two-value *taxonomy* in the
four-state *semantic live-state* palette is the textbook BAN-11 case, which my own frame listed as
must-not-introduce. **v0: plain `--mono` tracked micro-caps text in its own column (`ARXIV` /
`TEXTBOOK`) — no background, no border, no semantic colour.** Zero BAN-7/BAN-11 exposure, and strictly
more D-1-coherent, since a chip is a box and D-1 deletes boxes.

**UPL-12 v0 — `:has()` region-level in-flight cue** · *MINOR* — `hx-indicator` is set on **zero** of
the 9 htmx elements. Discover (live arXiv round-trip) and Ingest (background subprocess) get exactly
the same feedback as an instant local PATCH: one 80×32px button at 60% opacity. `:has()` also
disambiguates **which** of six visually identical Remove buttons is in flight — a job the per-element
cue genuinely cannot serve. Two corrections: my "0 bytes, pure CSS" covers only the `:has()` half (the
skeleton needs a template change and is its own S), and `.card:has(...)` keys off a class **UPL-2
deletes** — re-target to the ledger section.

**UPL-11 — In-language `<dialog>` confirm** · *MINOR — the cost declaration is the model the rest of the catalog should follow*
The three destructive actions are **the only three moments the console's visual language does not apply
at all**; in dark mode it is the one place a bright OS dialog flashes against the console. It also
rescues genuinely good copy currently trapped in unstyled chrome. Three additions: **(1)** guard on
`event.detail.question` — `htmx:confirm` fires on **every** htmx request, so an unconditional
`preventDefault()` halts all twelve htmx elements including both polls; this is the single most common
way this exact refactor breaks. **(2)** Don't rely on `::backdrop` inheriting `var(--fg)` — historically
it inherits from nothing, so the declaration can drop and leave an invisible backdrop on a destructive
confirm. **(3)** Cite the `@starting-style` / `transition-behavior: allow-discrete` baselines (both
Newly Available; both degrade to no-animation). **This is the one item worth its JS cost** — a CSS-only
fake loses the focus-trap semantics `<dialog>` gives for free.

**UPL-21 — Author the four empty states** · *NONE* — Cause + one action, at S-2 register (not a
cinematic 404). Correctly **escalates the BAN-3 icon question to an explicit decision** instead of
drifting into it. **Hard-paired with UPL-1** — see the copy regression above.

**UPL-17′ — De-duplicate the error handler in-repo** · *the vendored form is killed; this replaces it*
The same inline `JSON.parse(t).detail||t` handler is duplicated **seven times** (not six — I missed the
upload form at `notebook_detail.html:235`, and four of five line numbers were off by one). But
`response-targets` is **not** a drop-in: `hx-target-4xx` swaps the **raw body**, so the operator would
see `{"detail":"slug already exists"}` inside `pre.error` — making it work means changing the 4xx/5xx
response contract on seven `/ui/api` endpoints, and moving from `textContent` to `innerHTML` semantics.
It also contradicts the repo's own recorded decision (`VENDORED.md`: `json-enc.js` was authored in-repo
*specifically* to avoid pinning an unverifiable `htmx-extensions` version). **Redesign:** one exported
helper in the existing in-repo lane — `window.arxmcpShowError(id, xhr)` — reducing seven inline
attributes to one call each. Zero vendored bytes, zero provenance questions, keeps `textContent`, no
server change.

**UPL-23 v0 — `/` focuses the primary input on `index.html`** · *MINOR* — Zero `keydown`/`accesskey`
handlers exist anywhere. Scope to `index.html` where "the primary input" is unambiguous (the detail
page has six candidates, and after UPL-1 five are inside a collapsed `<details>` where focus cannot go).
The exclusion set must include **an open `<dialog>`** — otherwise typing `/` inside a destructive
confirm yanks focus out of the modal. The visible `<kbd>/</kbd>` hint is a **requirement, not an open
question**.

### Lane 5 — polish

**UPL-15a — Row hover tint** · *NONE standalone* — The only `:hover` rule in 371 lines is
`button:hover`. ~4 lines using the `color-mix` idiom already at `app.css:106`. Composes with D-1's "row
as the unit of interaction."
**UPL-14 — `#ingest-status` settle flash** · *NONE — "what a correctly-scoped XS candidate looks like"*
One selector added to an already-shipped, already-gated rule. Hard-paired with UPL-13, or it becomes a
light flashing every 2 seconds — a direct I-3 violation.
**UPL-19a — `@view-transition { navigation: auto }`** · *MINOR* — One line, 0 bytes, genuine no-op in
Firefox so no `@supports` needed, reuses the 200ms cap already declared. Must live **inside** the
existing `no-preference` block. Requires the opt-in on both documents, which holds because both come
from `base.html`.

---

## 5. Recommended next steps

**Do first (this week, ~1 day total):** the four a11y-lane items plus the two XS workflow wins. All are
XS/S, none blocks anything, and three are one-liners.

1. **UPL-27** — fix the two AA failures (`#777` → ≥4.5:1; darken `.status-badge--ok` text).
2. **UPL-22** — add the `matchMedia` `change` listener. 4 lines.
3. **UPL-10 v0** — add `class="error"` to the ingest-failure `<pre>`. One line.
4. **UPL-8 v0** + **UPL-15a** — form-control sizing parity + row hover tint.

**Then, `/milestone-pipeline`-ready (one milestone each, in this order — the DAG, not the RICE rank):**

- **`token-material-v0`** — UPL-4 v0 + the `--dur-*` tokens, shipping a **full rendered-pair contrast
  table** as an artifact. *Everything colour-touching waits on this.*
- **`type-scale`** — UPL-3. Independent of the above; can run in parallel.
- **`ledger-sheet-v0`** — UPL-2, only after both. Include the `--card-bg` re-scope and the `<thead>`
  rule migration.
- **`fragment-finish`** — UPL-7 + UPL-9 + UPL-13 v0 + UPL-21 (the whole BAN-R2 backlog + the live-region
  fix). Mostly XS/S; high finish-per-hour.
- **`corpus-before-machinery`** — UPL-1 v0 (detail page only, no expand animation, disclosure opens on
  non-terminal ingest), then UPL-1 v1 + UPL-21 as a hard pair.

**Spike first (don't schedule as a milestone yet):**
- **UPL-5's "N papers" question** — junction rows vs LanceDB chunks. One query; I-1 blocks the lede until it is answered.
- **UPL-11's `htmx:confirm` guard** — verify the `event.detail.question` early-return across all twelve htmx elements before committing to the `<dialog>` refactor.

**Parking lot / killed (challenger-recommended, adopted):**

| Item | Disposition | Why |
|---|---|---|
| **UPL-17** (vendored `response-targets`) | **Killed; redesigned as UPL-17′** | Needs a 7-endpoint response-contract change, not a code deletion; contradicts the repo's own `json-enc.js` precedent |
| **UPL-18** (idiomorph) | **Parked** | No named unserved continuity job; risks two shipped tested behaviours; a 0-byte `view-transition-name` alternative is unexamined |
| **UPL-19b** (`preload` extension) | **Deleted** | ~4.5 KB gz + a third vendored file + a third audit surface, to hide latency on a `127.0.0.1` binding |
| **UPL-24** (state-history strip) | **Killed from the frontend catalog** | Server keeps ingest history but exposes only `LIMIT 1`; the operability half has no history at all; BAN-15 borrowed fleet-monitoring instrument at single-operator cadence |
| **UPL-25** (ar5iv identity strip) | **Deferred wholesale** | UNSCORABLE (route 404s — never rendered); a strip inside a document permitted `style-src 'unsafe-inline'` can be **hidden or spoofed by that document**; contradicts the surface map's own "chrome recedes" |
| **UPL-15b** (action-reveal) | **Deferred; likely closed** | Probably superseded by UPL-11; `display`/`visibility` hiding makes the control keyboard-unreachable, defeating the `:focus-within` guard entirely |
| Timestamp humanization | **Parked** | I-2 wants metered facts; keep the exact value, add relative context only as a `title` |
| Every npm/CDN library | **Rejected** | See §8 |

**Aggregate JS budget — adopt the challenger's recommendation: one new vendored file across the whole
program, or zero.** Five candidates admitted JS surface; after the kills, only **UPL-11** genuinely
earns it (focus-trap semantics), and it needs **no new file**.

---

## 6. Visual evidence index

**No screenshots exist.** `screenshots/` is empty — the Browser pane was never displayed, so the page
never composited frames. Evidence substitute, captured live against `http://127.0.0.1:7733`:

| Evidence | Covers | Candidates |
|---|---|---|
| [`discover/visual-manifest.md`](../discover/visual-manifest.md) §1 token table | the 8 tokens + every hardcoded literal | UPL-4, UPL-27 |
| §2 typography table (measured sizes/weights/tracking) | the 1.10× step, zero letter-spacing | UPL-3 |
| §3 per-card y/height geometry at 1440×900 | 7 identical cards; papers table at y=1823/2343 | UPL-1, UPL-2, UPL-5 |
| §3 mobile tap-target table at 390px | button 32px · select 19px · footer links 17px | UPL-6, UPL-8 |
| §4 htmx attribute inventory | 9 hx-* elements, 0 `hx-indicator`, 12 live regions, 2s/10s polls | UPL-12, UPL-13, UPL-14 |
| §5 motion inventory | 3 keyframes + 1 view transition, all correctly gated; **zero `transition` properties** | UPL-19a, UPL-15a |
| Full read of `server/frontend/static/app.css` (371 lines) | every claim above at `✓ code` tier | all |

**To close this gap:** open the Browser pane and re-run the visual walk. The projected-state DQS score
cannot gate without it.

---

## 7. Honest limitations

1. **No pictorial evidence.** The anti-pattern half of the cookie-cutter score is auditable from
   measured geometry; **the positive design-quality half is not**, and no ship gate should treat the
   projected 2/13 as sufficient. Two of my own candidates (UPL-5, UPL-7) were ranked partly on DQS
   claims this run cannot score — treat those as **projected, not measured**.
2. **The ar5iv preview route was never audited.** No paper in the deployment has stored ar5iv HTML, so
   it correctly 404s. UPL-25 rests on zero evidence at any tier and is deferred for that reason.
3. **Three errors in my synthesis were caught by the challenger and are corrected in this report:** the
   contrast gate named the wrong tightest pair (4.97:1, not 5.16:1) and missed two *already-failing*
   shipped pairs; UPL-13's "zero-JS server-side delta" is not implementable as described; UPL-17's
   "safest kind of dependency" required a 7-endpoint response-contract change. The error-handler
   duplication count was 7, not 6, with four line numbers off by one.
4. **This is roughly three quarters of work, not one.** UPL-1 through UPL-7 alone is a full milestone
   stretch against this repo's own frontend grain.
5. **D-1 is a confirmation, not a discovery** — it is the overlay's pre-declared house default. Said
   plainly in §2 so the report does not sell novelty it does not have.
6. **`uplift-demo`** — a fixture notebook with 6 papers was created by the orchestrator to render a
   populated papers table (every pre-existing notebook returned `[]` via `/ui/api`). It has been
   deleted; the metadata-only DELETE leaves `var/arxmcp/notebooks/uplift-demo/` on disk.

---

## 8. Cross-reference index — the direct answer to "propose new libraries"

**Every library you would reach for is blocked, and the reason is architectural, not aesthetic.**
CLAUDE.md §4.7 forbids npm/Node/bundler/SPA, and `CONTENT_SECURITY_POLICY_UI`
(`server/middleware.py:170-177`) is `script-src 'self' 'unsafe-inline'` — **no external origin is
allow-listed**, so a CDN `<script src>` is blocked at the browser, not just by policy.

| Library | Why it cannot ship here |
|---|---|
| **Tailwind / PostCSS** | Requires a compile step; `app.css` is shipped as-authored with no build in the deploy path |
| **shadcn/ui** | Is React + Tailwind + Radix underneath — inherits every blocker below and above |
| **React / Vue / Svelte** | Require an SPA architecture; the server is Jinja2 with no client-side routing |
| **Radix UI** | npm-installable React components; no React runtime exists |
| **Framer Motion** | npm, React-only import path, ~40 KB min+gz |
| **GSAP / anime.js / Motion One** | npm or CDN; a vendored copy is theoretically CSP-legal but **no motion job exists** that CSS transitions + htmx swap hooks can't serve — the house thesis says "never a JS animation engine" |
| **cmdk** (command palette) | npm + React, and the wrong solve: the real gap is a one-element focus jump (UPL-23) |
| **Sonner / toasts** | npm, plus a thesis mismatch — inline `aria-live` + `pre.error` already answer "did my action work" next to the control |
| **Lucide / Phosphor** | No icon gap exists; text-label-only buttons are an asset (BAN-3) |
| **TanStack Table/Query** | npm; htmx fragment swaps already ARE the state-sync mechanism |

**What you get instead — and it is genuinely most of what those libraries provide, at zero bytes:**

| Native platform API | Replaces | Baseline | Candidate |
|---|---|---|---|
| **`<dialog>` + `::backdrop`** | Radix Dialog, modal libs | Widely Available ~Sept 2024 | **UPL-11** |
| **`@container` queries** | Tailwind responsive utilities | Widely Available ~Aug 2025 | **UPL-16** |
| **`:has()`** | JS state-class toggling | Widely Available ~June 2026 | **UPL-12** |
| **`:user-invalid`** | form-validation libs | Widely Available ~May 2026 | **UPL-26** |
| **`@view-transition`** | route-transition libs | Chromium + Safari (safe no-op in Firefox) | **UPL-19a** |
| **`color-mix()` / OKLCH** | color-manipulation libs | already used at `app.css:106` | **UPL-4** |
| **`text-wrap: balance`** | headline-balancing JS | Newly Available → Widely 2026-11-13 | **UPL-3** |
| **`field-sizing: content`** | auto-resize-textarea libs | Newly Available 2026-06-16 (`@supports`-gate) | **UPL-8 v1** |
| **`popover` + anchor positioning** | Popper.js / Floating UI | Newly Available (`@supports`-gate) | parked |
| **`<output>`** (implicit `role="status"`) | manual `aria-live` bookkeeping | universal | **UPL-13 v1** |

**Vendorable single-file drops (the proven `htmx.min.js` lane, all 0BSD):** `response-targets` (3,740 B
— **rejected**, see UPL-17′), `loading-states` (5,551 B — unnecessary, `:has()` covers the job),
`preload` (14,099 B — **deleted**, solves loopback latency), `idiomorph` (10,153 B min — **parked**, no
named job). **Net recommendation: zero new vendored files.**

**Design references cited:** [Linear 2026 refresh](https://linear.app/now/behind-the-latest-design-refresh) ·
[Vercel deployments redesign](https://vercel.com/changelog/redesigned-deployments-list) ·
[Primer Blankslate](https://primer.style/components/blankslate/) · [Primer ActionList](https://primer.style/components/action-list/) ·
[Primer State label](https://primer.style/components/state-label/) ·
[NotebookLM Discover sources](https://blog.google/technology/google-labs/notebooklm-discover-sources/) ·
[Grafana state timeline](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/state-timeline/) ·
[Zed diagnostics](https://zed.dev/docs/diagnostics) · [arXiv HTML rollout](https://blog.arxiv.org/2023/12/21/accessibility-update-arxiv-now-offers-papers-in-html-format/) ·
art-direction reference library REF-1…9 (metalab, waabi, new.studio, newgenre, filter.im, ponder.ai, sohub, trionn, save.design).

---

**Offer, not an auto-invoke.** Two handoff paths are available when you want them:

- Single candidate → `/milestone-pipeline` (e.g. `token-material-v0` or `type-scale`).
- Multi-candidate program → `/roadmap`, which would turn the five lanes into an epic tree.

Neither has been invoked. Type the command if you want to proceed.
