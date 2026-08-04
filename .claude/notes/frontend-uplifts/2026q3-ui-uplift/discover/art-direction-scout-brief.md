# Art-direction scout brief — 2026q3-ui-uplift

**Scout:** `frontend-uplift-art-direction-scout` · **Run:** `2026q3-ui-uplift` · **Surface:** `tool` (S-2 wholesale)
**Wave:** 2 (dispatched after visual-scout + current-state-critic; both briefs read in full before framing)
**Memory:** `.claude/agent-memory/frontend-uplift-art-direction-scout/lessons.md` was EMPTY at run start — this is
the first art-direction pass on this repo. No prior direction retrospectives to inherit.
**House-thesis overlay:** `.claude/references/frontend-uplift/arxmcp-design-system.md` §9 — **present, read BEFORE
this brief's thesis was written** (canon §9 mandate satisfied). This brief SHARPENS that thesis for this run's
scope; it does not replace it.

---

## Evidence-tier notice (read first — §14 discipline)

**There are ZERO PNG screenshots this run.** `{SCREENSHOT_DIR}` is empty; the Browser pane never
composited frames. Every judgment below therefore rests on two tiers:

| Tier | Source | What it can and cannot establish |
|---|---|---|
| `✓ live` | `discover/visual-manifest.md` — live computed styles, per-card y/height geometry at 1440×900 and 390px, tap-target measurements, htmx/motion inventory, all captured against a running `http://127.0.0.1:7733` | §14 lists "computed style, live DOM metric" as `✓ live`, so the manifest **is** live-tier evidence — it is not `~ inferred`. What is missing is the *pictorial* half. |
| `✓ code` | `server/frontend/static/app.css` (371 lines, read end-to-end), `templates/{base,index,notebook_detail}.html` (all three read in full), `server/routes/{ui,notebooks}.py` line cites carried from the current-state critic | Establishes what the CSS/markup *is*. |

**The one honest limit:** judgments that require *seeing* a composition rather than *measuring* it
(e.g. "does the page feel crowded", "does the badge read as a pill") are stated from geometry and
marked as such. Nothing in this brief is a visual impression I did not measure. Per §14, a section
with no `✓ live` **screenshot** does not carry a PASS on its own — the §10 score below is auditable
per-tell, but the DQS half must be re-scored against real screenshots before any ship gate.

**Injection attempts: 0.** Nine reference-site fetches (metalab, waabi, filter.im, new.studio,
newgenre.studio, ponder.ai, save.design, trionn/404) returned only marketing copy and nav labels. No
fetched page attempted to instruct me. Fetched copy is quoted as *trait evidence*, never as a claim.

---

## 1. TL;DR

The console scores **6/13** on the §10 cookie-cutter rubric (self-scored; independent range 5–6 — see
the arbitration note on tell 4), which lands it at the **6+ "generic AI dashboard" band edge** despite
having no Tailwind, no shadcn, no Node and no build chain anywhere — the user's *diagnosis* is wrong
and their *perception* is right: the generic feel traces to a **documented GitHub-Primer palette
clone** (`app.css:234-241` says so in its own comment), **one effective type step** (32px → 17.6px →
16px, so h2/body contrast is carried by weight alone), and **one container primitive** (`.card`) doing
every structural job across seven identically-weighted panels. The thesis this run should build to:
**arXMCP's console is the bench record of a one-person mathematics lab — each notebook is a named body
of literature with a stated question, a provenance trail, and a parse-and-index state readable as a
metered fact, with the corpus shown before the machinery that mutates it.** The recommended direction
is **D-1 "The Ledger Sheet"** — retire the card as a primitive and let graded hairline rules carry all
structure — because it removes five of the six scored tells with pure CSS plus a template reorder, adds
no font file, no JS, no CSP change and no widening of the open UI security audit, and it attacks the
"AI-generated" complaint at its actual root (the box) rather than decorating the box.

---

## 2. Cookie-cutter score — current state

**Derived total: 6 / 13** (counted from the 1-verdicts below; never asserted). Band per §14: **6+ →
"generic AI dashboard"**. Two tells (4 and 9) are judgment-qualifiers where a second scorer could
reasonably read 0, which would put the total at **5** ("template-leaning / MAJOR"). Both readings are
recorded per-tell so the arbitration can happen against evidence rather than memory. Per §10's
empirical calibration, ±1 with disagreement concentrated on judgment tells is the expected shape.

| # | Tell (BAN) | Verdict | Evidence | Tier |
|---|---|---|---|---|
| 1 | Navy shell + neon accent set (BAN-1) | **0** | Dark shell IS near-navy (`--bg #0d1117`, Primer canvas.default — blue-tinted near-black), but there is exactly ONE brand accent (`#58a6ff`) and every other colour (`--danger`, the 4 status-pill pairs) is reserved for live state. The ban needs 2+ neon accents. **Closest-to-1 of the zero verdicts** — any uplift that "enriches" the palette flips this. | `✓ code` app.css:242-291 · `✓ live` manifest §1 |
| 2 | 6+ equal rounded cards as primary layout (BAN-2) | **1** | Seven `<section class="card">` on `notebook_detail.html` (lines 8, 94, 147, 181, 221, 251, 300), all measured at identical 1293px width, identical `border-radius: 6px`, identical 1px border, identical `padding: 1rem 1.25rem`, identical `margin-bottom: 1rem`, `box-shadow: none` on every one. No sidebar/topbar (so the literal BAN-2 phrasing is partial), but §10's restatement — "6+ equal rounded cards as the primary layout" — is exactly the page. | `✓ live` manifest §3 · `✓ code` app.css:53-59 |
| 3 | Icon-tile decoration (BAN-3) | **0** | Zero `<svg>`, zero icon classes, zero icon font in any of the three templates. Only `favicon.svg`. A genuine strength — and the most likely place an uplift regresses. | `✓ code` all 3 templates |
| 4 | Default stack look untouched (BAN-4) | **1** *(judgment)* | Literal reading (Inter + Lucide + shadcn) → **0**: none present. Invariant reading → **1**: unmodified `-apple-system` system stack (`app.css:24-25`), **zero `letter-spacing` anywhere in 371 lines**, one effective type step (h1 32px → h2 17.6px is 1.82×; h2 → body 16px is 1.10×, carried by weight 700 vs 400), binary radius system (4px ×7 sites / 6px ×1), **zero `box-shadow` in the file**, **zero `transition` outside the reduced-motion clamp**. I score **1** and adopt the current-state critic's H5 argument: the tell transfers through a different stack. An independent scorer reading §10's literal wording should score 0 → total 5. | `✓ code` app.css:24-25,53-59,87-98 · `✓ live` manifest §2 |
| 5 | No focal element / equal panel weight (BAN-5) | **1** | Nothing on either route is weighted differently from anything else. On the detail page the papers table — the only corpus content — begins at **y=1823 of a 2343px document**, dead last after six consecutive input forms; only cards 1–3 sit above a 900px fold. The overlay's own §9 says this page should lead with a posture lede; it does not. | `✓ live` manifest §3 |
| 6 | Decorative unannotated charts (BAN-6) | **0** | There are no charts at all. **This is §10's stated blind spot** — zero charts scores clean here while also meaning the console has no decision instrument (DQS dim 3). Read it as an open surface, not a pass. | `✓ code` all 3 templates |
| 7 | Badge soup (BAN-7) | **0** | Two badges visible per detail-page view (parse-status at `notebook_detail.html:59`, footer operability at `base.html:88`); one on the index. Well under ~5. The overlay explicitly names this as the thing to protect. | `✓ code` |
| 8 | Glow/gradient/glass without reason (BAN-8) | **0** | `grep box-shadow` → 0 matches in 371 lines. No gradients, no blur, no glass. Only `color-mix(in oklab, …)` on button hover. | `✓ code` app.css (full read) |
| 9 | Multiple primary CTAs per viewport (BAN-9) | **1** *(judgment)* | The CSS has **one button style, full stop** — `button, .button { background: var(--accent); color: #fff }` with a single `.danger` fill variant. There is no secondary/ghost/tertiary tier anywhere. On the detail page's first 900px: Rename (accent fill), Delete notebook (danger fill), Save topic (accent fill) all read as equally primary. A scorer counting *intent* rather than *styling* could read 0; I score 1 because the absence of a button hierarchy is the durable, code-level fact. | `✓ code` app.css:87-108 · `✓ live` manifest §3 |
| 10 | Generic / cosplay copy (BAN-10) | **0** | The copy is a genuine strength and must be protected: "Loopback only · same-origin only · Destructive notebook wipe lives in `tools/notebook_purge.py`" (`base.html:71-73`), "PDF parse — arxiv notebooks skip this; see 'Last indexed' below for indexing" (`notebook_detail.html:64`), "Per-notebook arXiv corpora for the `/proof-verify` pipeline" (`base.html:55`). No "Welcome back", no "Quick Actions", no theatrics. | `✓ code` |
| 11 | Semantic colour used decoratively (BAN-11) | **0** | The four `.status-badge--*` pairs appear only on live-state surfaces. Watch-item, not a hit: `--danger` does double duty as destructive-*action* fill and error-*state* colour (`app.css:108` vs `:137-148`), which is consequence-coded and defensible today but is the dilution path. | `✓ code` app.css:152-168,286-289 |
| 12 | Uniform density, no authored modes (BAN-14) | **1** | Every card `padding: 1rem 1.25rem`; every table cell `0.5rem 0.5rem`; `body { padding: 1rem }` **identical at 1440px and at 390px** (measured). No density toggle, no compact table mode, no per-view density intent. One medium density for a 7-form workflow page and a 6-row data table alike. | `✓ code` app.css:29,57,115 · `✓ live` manifest §3 mobile |
| 13 | Same-silhouette syndrome (BAN-15) | **1** | The dark palette is an **explicitly documented clone of another product's published design system**: the in-file comment at `app.css:234-241` reads "re-declares the 8 base tokens with **GitHub-Primer-anchored values**", and the values are GitHub's exact ones (`#0d1117` canvas.default, `#161b22` canvas.subtle, `#58a6ff` accent.fg, `#f85149` danger.fg). The light palette comes from a *different*, unattributed source (`--accent #1e5b8a`). Two palettes stitched under one schema, with another company's material as this product's identity — that is BAN-15's shape, and it is the single most precise answer to "why does it look like something I've seen before." | `✓ code` app.css:242-255 |

**Current de-facto thesis, stated honestly:** *"Whatever ships correct, styled to whatever GitHub
already proved was accessible."* Not "none — template defaults" (this repo is far more disciplined than
that: computed contrast tables, a belt-and-suspenders reduced-motion gate, correctly-scoped
`tabular-nums`), but also not a thesis — it is a **borrowed** one, adopted for contrast safety and never
revisited.

### §10 is only half the gate — the DQS dimensions this state visibly fails

§10 measures the ABSENCE of clichés; a sparse page scores well while answering nothing. Scored
qualitatively from the same evidence (real screenshots required before this half can gate — §14):

| DQS dim | Read | Why |
|---|---|---|
| 1 task clarity | **~1** | The operator's most common question ("what's in this notebook?") is answered 1823px down, after six forms. |
| 2 priority fidelity | **~1** | Visual weight is uniform, so mutation controls outrank the content they mutate. |
| 3 decision integrity | **~2** | Raw ISO timestamps; `parse_status: skipped` needs a sentence of prose to be readable; no paper/chunk counts, no corpus delta, no "so what" anywhere. |
| 4 composition | **~1–2** | One column, seven identical blocks, no region answering a distinct question. |
| 5 typography | **~1** | One effective step, zero tracking, one face. |
| 6 semantic depth | **~1** | No layer model exists: zero shadows, one border weight, one radius pair. Nothing encodes nesting, selection, or ownership. |
| 7 interaction & state craft | **~2** | Genuinely strong where shipped (htmx `.htmx-request` states, `:focus-visible`, dark mode, reduced motion, live regions) — but zero `hx-indicator` on 9 htmx elements, four server-emitted class families with **no CSS rule at all**, and native `window.confirm()` on all three destructive paths. |
| 8 product signature | **~1** | Remove the `<h1>` and this is indistinguishable from any internal tool using GitHub's palette. Nothing says *research mathematics*. |

Mean ≈ **1.4** against a 3.0 ship bar, with dims 1/3/8 (the ones §14 requires ≥3) at the bottom. **The
DQS half, not the anti score, is where this run's value is.** A run that only removed the six scored
tells and left the page answering nothing would trade one failure for another.

---

## 3. THE FRAME — thesis + three directions

### 3.1 Visual thesis

> **arXMCP's console is the bench record of a one-person mathematics lab: every notebook is a named
> body of literature with a stated question, a provenance trail, and a parse-and-index state the
> operator can read as a metered fact — and the console shows the corpus before the machinery that
> mutates it.**

**Swap-test:** substitute "a generic notebook manager", "an internal admin dashboard", or "a Docker
registry UI" — the sentence collapses immediately: none of them has a *body of literature*, a *stated
research question*, a *parse-and-index state*, or a corpus-before-machinery priority. **Passes.**

**Relationship to the overlay (§9).** This is the overlay's thesis *sharpened for this run*, not a
replacement. The overlay's four invariants remain binding and are inherited verbatim; this run adds two
that the current UI does not express at all:

| # | Invariant | Source | What it forbids |
|---|---|---|---|
| I-1 | **Operational honesty** — a reading the operator can't trust is worse than none | overlay §9 | semantic colour as decoration; badges that report a token without the fact behind it |
| I-2 | **Provenance & freshness** — corpus version, ids, timestamps are metered facts, live not stale | overlay §9 | proportional numerals on data; a render that lies about daemon state |
| I-3 | **Calm at repeat use** | overlay §9 | motion without a named job; anything that moves on a poll tick |
| I-4 | **Sovereign minimalism** — 3 pages, zero build chain, zero egress | overlay §9 / CLAUDE.md §4.7 | npm, CDN, SPA, any non-vendored dependency |
| I-5 | **Corpus before machinery** *(new this run)* | this thesis; visual-scout CRITICAL-1 | mutation controls placed above the content they mutate |
| I-6 | **Domain legibility** *(new this run)* | this thesis; DQS dim 8 at ~1 | an identity that would fit equally well on a log-bucket console; identity from ornament rather than from corpus vocabulary + typographic discipline |

**Deliberately NOT in the thesis:** any silhouette. No card, no rail, no grid, no lede shape is
mandated — that would be BAN-15 authored at the top of the run. The three directions below satisfy the
same six invariants through compositions that could not be mistaken for one another.

---

### 3.2 The three directions

Divergence check first, because §8's binding rule is the divergence requirement, not the seeds:

| Axis | D-1 Ledger Sheet | D-2 Reading Room | D-3 Console Rail | Differs? |
|---|---|---|---|---|
| **navigation model** | row-drill; the ledger row IS the nav; no persistent chrome | breadcrumb + in-page section index (a paper's table of contents) | persistent left instrument rail + single work pane | ✓ 3-way |
| **page silhouette** | one full-bleed ruled sheet, no boxes at all | asymmetric ~65ch reading measure over a full-bleed bibliography | two-column split, rail + pane | ✓ 3-way |
| **typography posture** | sans body + mono data voice, micro-caps meta | **serif/editorial display voice** + sans body + mono data | **mono-forward UI**, sans demoted to prose hints only | ✓ 3-way |
| **geometry** | radius 0 on structure; rules only, no vertical edges | radius 0 rules + ONE soft 10px lede block | radius 2px, rail edge as a rule not a box | ✓ (D-1/D-2 partially share) |
| **material / depth** | warm paper, hairline-only, graded rule ladder | warm paper, one tinted background lift | cold ink, one raised layer (the command overlay) | ✓ |
| **colour temperature** | warm neutral | warm neutral | cold neutral, dark-first | partial (D-3 vs D-1/D-2) |
| **density** | compact, uniform-authored | **two densities** (spacious lede / compact bibliography) | compact + explicit comfortable toggle | ✓ 3-way |
| **interaction grammar** | keyboard row-nav + selection state | reading; hover-reveals provenance | **command line**; forms become the fallback | ✓ 3-way |

**Six axes differ three ways.** Requirement is ≥4. Grayscale plates of the same notebook would be
unmistakable: a ruled record · a reading measure with a bibliography · a rail beside a command line.

---

#### D-1 · The Ledger Sheet **[RECOMMENDED]**

> *"The console is one continuous record of account, not a stack of panels. Rules carry every
> structure; the box is deleted."*

**Concept.** The `.card` is retired as a primitive. Structure is carried entirely by a **graded
hairline rule ladder** — section rule (full weight), row rule (60%), meta rule (dotted) — the way a
laboratory notebook or a printed ledger is structured. Notebooks are rows; papers are rows; state
changes are dated lines. The five mutation forms collapse into a single native `<details>` "Manage"
region below the corpus.

**Applies to:** all four S-2 surfaces — index, detail, status fragment, and (as chrome-free document
view) the ar5iv preview. **Must NOT apply to:** nothing in-product; there is no surface this over-reaches
(there is no S-1/S-1m anywhere).

**5 concrete UI traits**
1. **Zero-radius structural containers.** Radius survives only on interactive controls (buttons,
   inputs, the one operability badge) — geometry itself encodes "structure vs. control".
2. **Graded rule ladder** replacing all borders: `--rule-section` / `--rule-row` / `--rule-meta`, three
   weights, horizontal only. No vertical edges anywhere.
3. **Mono as a true data voice** — every paper id, path, slug, timestamp, corpus version and state
   token in `--mono` with `tabular-nums` (extends what already ships at `app.css:133-135`).
4. **Tracked micro-caps column meta** — 11px, `letter-spacing: 0.06em`, uppercase, muted: the first
   authored tracking in the product's history.
5. **Row as the unit of interaction** — full-row hover, a persistent selected-row state, and `j`/`k`
   row traversal; the row, not a button, is what the operator addresses.

**5 banned traits:** no `.card` boxes · no `box-shadow` (hairline is the sole elevation method) · no
rounded pills beyond the single operability badge · no accent-filled secondary buttons · no icons.

**Risks.** *a11y:* the light-mode border token is `#d8d8d8` on `#f8f8f8` — I compute **1.34:1** (and
1.43:1 on `--card-bg #fff`). That is tolerable while borders are incidental; the moment rules become
the *sole* structural device, SC 1.4.11's 3:1 non-text bar applies and this **fails**. D-1 cannot ship
without darkening the light rule token and re-running overlay §4's contrast table (dark `#6e7681` at
4.12:1 already clears). *Density:* a compact record collides with the measured 32px buttons / 19px
`<select>` — needs the C6 coarse-pointer floor in the same change. *Taste:* a ruled sheet with timid
type contrast reads as a spreadsheet — D-1 is only as good as C3.
**Effort:** M. **Seeds:** REF-1 (confidence from what you leave out; the numbered 01–24 index), REF-5
(density is authored, not accidental), M-1 Sovereign Ledger.

---

#### D-2 · The Reading Room

> *"The notebook is a work of literature with a stated question. Type carries everything; the machinery
> is an appendix."*

**Concept.** The console adopts a scholarly-editorial register. A notebook opens the way a paper opens:
an eyebrow (category), a title, a stated question, then evidence. Papers are a **bibliography**, not a
CRUD table. The five forms become "Appendix — manage this notebook."

**Applies to:** the detail page and the index primarily. **Must NOT apply to:** the ar5iv preview
(where the ar5iv document's own typography must own the surface — an editorial chrome there would
compete with the mathematics) and the status fragment (which stays a compact instrument).

**5 concrete UI traits**
1. **A stated-question lede** in an editorial voice: eyebrow `math.AG` → title *Bridgeland stability
   conditions on K3 surfaces* → one honest posture sentence built from metered facts.
2. **A real type ladder with a serif/italic accent voice** for the notebook title and abstention/empty
   states — the one direction that requires a vendored font file.
3. **Bibliography-style paper list** — hanging indent, id in mono, added-date muted, preview as a
   text link, not a button column.
4. **Numbered section eyebrows** — `01 — Corpus`, `02 — Discovery`, `03 — Appendix: manage` — replacing
   seven undifferentiated `h2`s.
5. **Measure-limited prose** — every `.hint` capped at ~65ch instead of running the full 1293px column.

**5 banned traits:** no equal-weight card stack · no 100%-width inputs for short fields · no ALL-CAPS
SaaS section labels · no icon tiles · no display type above 40px (S-2 cap — display sizes belong to
S-1, and there is no S-1 here).

**Risks.** *Asset story:* this direction **needs a self-hosted `woff2`** (§12 kits: IBM Plex Serif or
Newsreader italic, both OFL and safe to bundle). The product currently ships **zero font files and no
reachable CDN under the UI CSP** — so this is a real change to the asset story, not a free choice. I
could not verify a subset byte weight from a citable source this run (`~ inferred`: a latin-subset
variable woff2 is typically tens of KB, but the actual figure must be **measured before D-2 is
chosen**, not assumed). *Density:* editorial scale eats vertical space on a workflow page — capped at
40px with the bibliography kept compact. *Rendering:* serif at 13px on Windows without good hinting is
the failure mode; test at the real size before committing.
**Effort:** L. **Seeds:** REF-3 (title-case editorial headlines, serif/italic contrast, whitespace as a
status signal — *"Transforming Brands, Building Futures" / "Ambition" / "Selected Work"*), REF-4
(eyebrow → headline → evidence rhythm — *"Our work, from petal to planet"*; its own type system is
Displaay Serrif + Saans, evidencing the two-voice serif/sans pairing), REF-2 (short declarative
sentence pairs — *"Built to think. Born to haul."* — as the model for an honest posture sentence).

---

#### D-3 · The Console Rail

> *"A daemon control surface: the live instrument is always visible, and the operator types rather than
> clicks."*

**Concept.** A persistent left rail carries the daemon's live state (operability badge, corpus version,
notebook list) beside a single work pane. A `/`-triggered command line runs the same verbs the forms
run (`add <url>`, `discover`, `ingest`, `rename <name>`); the forms remain as the no-JS fallback. The
register is terminal-adjacent: mono-forward, cold, exact.

**Applies to:** index + detail. **Must NOT apply to:** the ar5iv preview (the rail would fight the
document and the tight preview CSP forbids the JS anyway) and mobile ≤480px (the rail must collapse to
a header strip — a rail at 390px is a bug, not a direction).

**5 concrete UI traits**
1. **Persistent instrument rail** — the 10s badge poll already exists and currently renders in a
   footer nobody looks at; the rail gives it the one place where "is the daemon healthy" is always in
   the operator's field of view.
2. **`/` command line** with typed verbs and inline completion, mapped 1:1 to existing `/ui/api/*` calls.
3. **Mono-forward UI voice** — labels, ids, state strings and commands all in `--mono`; sans reserved
   for prose hints only. The exact inverse of D-1/D-2.
4. **Command-palette overlay as the ONLY elevated layer** — satisfying §14's semantic-depth clause
   honestly: one shadow exists in the product, and it means "transient overlay above the work surface."
5. **Fixed-width state line per notebook** — `math.AG · 6 papers · idx 2026-08-03 · v12` rendered as a
   monospaced instrument reading rather than a `<dl>`.

**5 banned traits:** no card stack · no accent-filled button as the primary action (commands replace
them) · no decorative pills · no 6px rounded containers · no light-mode-first authoring (this direction
is authored dark-first, then derived light).

**Risks.** *Security/audit — the decisive one:* a command line is **real new JS**. It is CSP-legal today
(`script-src 'self' 'unsafe-inline'`, per the current-state critic's §6 constraint record) and needs no
CSP edit, but **any new JS widens the still-open UI security audit `chris-dare-dev/arXMCP#9`** and must
be declared, not slipped in. *Progressive enhancement:* every command must degrade to the existing form
with JS disabled, or the console becomes unusable under the preview CSP posture. *a11y:* keyboard-only
affordances need a visible discoverability hint and full ARIA combobox semantics — a hidden command line
is an accessibility regression, not a feature. *Legibility:* mono everywhere is fatiguing; cap it at
labels/data. *Contrast:* re-authoring the ink hue invalidates every pair in overlay §4.
**Effort:** L. **Seeds:** REF-9 / Savee (interaction quality IS the brand — its 20 documented shortcuts
exist to "navigate, search and organize without breaking focus"; ✓ verified), REF-6 (dark works when it
is product-specific and single-accent — *"Let your ideas flow. Ponder it."*), REF-1 (one sharp idea,
executed fully).

---

### 3.3 Recommendation — D-1, with D-2 as the declared runner-up

**Choose D-1 "The Ledger Sheet."** Four reasons, in order of weight:

1. **It removes the most scored tells at the lowest risk.** D-1 kills tells 2, 4, 5, 9 and 12 outright
   and contributes to 13, using pure CSS plus a template reorder — **no font file, no new JS, no CSP
   change, no widening of `arXMCP#9`.** D-2 costs an asset-story change; D-3 costs security-audit
   surface. On a repo whose §4.7 locks are the strongest constraint in the room, the direction that
   needs nothing new is the direction that can actually ship.
2. **It attacks the complaint at its root.** The "AI-generated" feel here is the *box* — seven
   identical rounded bordered panels. D-2 and D-3 both leave a container system in place and re-dress
   it; D-1 deletes it. Deleting the shadcn-shaped primitive is the most direct possible answer to
   "looks like standard shadcn," and it is the one move a default assembly will never make, because the
   Card *is* the default assembly's identity.
3. **It is the strongest fit for I-4 (sovereign minimalism) and the operator.** One research
   mathematician on one workstation reading a record of what is in the corpus. A ledger is what that
   person already keeps.
4. **It composes forward.** D-1 and D-2 share a material (warm paper, hairline-only), so a D-1 core
   with a D-2 posture lede on the detail page is a coherent v2 — which is exactly the "D-A workbench
   with a D-B posture lede" the overlay §9 surface map already anticipates. Choosing D-1 does not
   foreclose D-2; choosing D-3 forecloses both (cold ink, mono-forward, dark-first inverts the whole
   token authoring).

**What choosing D-1 costs:** it is the least *distinctive* of the three on first glance. D-3 would be
the most recognizable product; D-2 the most beautiful. D-1's distinctiveness is entirely load-bearing
on C3 (type scale) and C4 (material) — **if those two are descoped, D-1 degrades into "the same page
with the borders removed," which is a worse outcome than shipping nothing.** State that dependency in
Phase 2 and hold it in Phase 3.

---

## 4. Negative-reference list (active BAN tokens)

### Present in the current state — must be REMOVED

| Token | Evidence | Tier |
|---|---|---|
| **BAN-2** | 7 identical `.card`s, measured identical width/radius/border/padding | `✓ live` manifest §3 |
| **BAN-4** *(invariant reading)* | system stack unmodified; zero `letter-spacing` in 371 lines; 1.10× h2→body step; zero `box-shadow`; zero `transition` | `✓ code` app.css |
| **BAN-5** | papers table at y=1823/2343; nothing weighted differently anywhere | `✓ live` manifest §3 |
| **BAN-9** | one button style + one danger variant, no hierarchy tier exists | `✓ code` app.css:87-108 |
| **BAN-14** | identical padding across all cards/cells; `body` padding identical at 1440px and 390px | `✓ live` manifest §3 |
| **BAN-15** | dark palette is a self-documented GitHub-Primer clone (`app.css:234-241` comment + exact Primer values); light palette from a different, unattributed source | `✓ code` app.css:242-255 |

### Absent today — must NOT be INTRODUCED by the uplift (the real risk set)

`BAN-1` (any second accent added to the palette flips tell 1 immediately — the shell is already
near-navy) · `BAN-3` (icon-in-rounded-square tiles are the single most likely "make it prettier" move;
the product currently has zero icons and that is an asset) · `BAN-6` (an "ingest activity" sparkline is
tempting and must not ship without a threshold/annotation/"so what") · `BAN-7` (the M6 `notebook_kind`
chip is legitimate at *one chip per row* and becomes badge soup at two) · `BAN-8` (no glass/glow —
hairline is the sole elevation method in D-1/D-2, one overlay shadow in D-3) · `BAN-10` (the current
copy is a strength — protect it; no "Welcome back", no "Command Center") · `BAN-11` (do not let
`--danger` drift further between "destructive action" and "error state") · `BAN-12` (**wholesale** — see
§5) · `BAN-13` (a KPI stat-card row on the detail page would manufacture metrics the daemon does not
have — the overlay names this by name).

### Run-scoped anti-references (arXMCP-specific; **run-local tokens, NOT canon §5 entries**)

| Token | Pattern | Evidence |
|---|---|---|
| **BAN-R1 · Form-first page order** | Mutation controls rendered above the content they mutate. This is arXMCP's own signature tell and it is not in the canon. | `notebook_detail.html` section order; papers table at y=1823 after six forms |
| **BAN-R2 · Unstyled-fragment debt** | Server-emitted classes shipped with no CSS rule: `.status-badge__remediation`, `.discover-list/-candidate/-title/-meta/-abstract`, `select`, `textarea`, the ingest-failure bare `<pre>`, the inert `[data-status]` hook. **Any new fragment must land with its rule in the same change.** | `server/routes/ui.py:297-337`; `server/routes/notebooks.py:705-753`, `:2376-2389`; app.css grep = 0 matches |
| **BAN-R3 · Instrument without a reading** | A status surface reporting a token but not the fact behind it — `parse_status: skipped` needing a sentence of prose to be interpretable; "Last indexed" with no corpus delta; no paper/chunk counts anywhere. Violates I-1 and DQS dim 3. | `notebook_detail.html:57-75` |

**Standing negative baseline** (inherited, unchanged): the canon §1 anti-reference — a fully-templated
"command center" comp scoring 11–12. arXMCP has no bad screen of its own; its risk is **drift toward**
the template as candidates accrete. Add to that, from this run: **the GitHub console itself** — because
the palette is literally GitHub's, "looks like GitHub" is now a measurable, cite-able failure state
rather than a vague worry.

---

## 5. Surface map

Every route is **S-2 tool**. The overlay §9 already establishes *why*: arXMCP is loopback-only with no
public, login, marketing, or onboarding surface — the Origin + Host + SecFetchSite triple defense
replaces browser auth, so **there is no threshold for an experiential moment to live on**. Re-verified
against source this run; unchanged.

| # | Surface | Route / file | Class | Direction application (D-1 recommended) | Motion budget |
|---|---|---|---|---|---|
| 1 | Notebook index + create | `GET /ui/` · `index.html` | **S-2** | Ledger index: notebooks as ruled rows; create collapses into a `<details>` below the list (corpus before machinery) | `MOT-24` row hover ≤100ms · `MOT-15` details expand · shipped `row-fade-out` |
| 2 | Notebook detail (the dense page) | `GET /ui/notebooks/{slug}` · `notebook_detail.html` | **S-2** | The run's centre of gravity: ruled masthead (state as metered facts) → papers ledger → one `<details>` "Manage" carrying all five forms | `MOT-15`, `MOT-24`, shipped `badge-flash` on settle, shipped view transitions ≤200ms |
| 3 | ar5iv paper preview | `GET /ui/notebooks/{slug}/papers/{id}/preview` | **S-2** (document view) | Chrome recedes — the ar5iv HTML owns the surface. Tight `CONTENT_SECURITY_POLICY_PREVIEW` is a **constraint to honour, not a bug**. Note the critic's correction: `target="_blank" rel="noopener"` means closing the tab IS the way back; the residual gap is brand discontinuity only. **Un-audited this run** (no paper in the deployment has stored HTML) | none |
| 4 | Operability badge fragment | `GET /ui/status-badge` (10s poll) | **S-2** | The instrument. Semantic colour = live state ONLY. Stable width preserved (`min-width: 14ch`). **`.status-badge__remediation` must get its rule** | shipped `badge-flash` (feedback job) only |
| 5 | htmx fragments | `_display_name_fragment`, `_topic_fragment`, `_discover_results_fragment`, `_paper_row_html`, `_ingest_status_fragment` | **S-2** | Inherit the parent surface's language; each must ship with its CSS (BAN-R2) | swap-state only; **no motion on a poll tick** (I-3) |
| 6 | Empty / error / abstention states | `.empty`, `pre.error`, preview 404, "Never indexed", "No discovery run yet" | **S-2** | Authored per REF-8's doctrine — *at S-2 register*: cause + one action, explanatory and next-step-bearing. Not a cinematic 404 | none |

**Gate consequences (binding downstream).** Because every surface is S-2:
`EXP-*` tokens are **BLOCKED wholesale**. AP-1/2/3/5 (parallax, smooth-scroll hijack, scroll-scrub/zoom,
WebGL) are **BLOCKED**. BAN-12 applies everywhere. Motion is `MOT-*` only, and every candidate must name
one of the four motion jobs — orientation / causality / feedback / continuity — or it does not ship. Two
specific rejections follow from this and should be pre-empted: **initial-load number tweens (`MOT-18`) do
not pass the jobs test** (no job is served by animating a count that just arrived), and **`MOT-3`
stagger-reveal on the papers table is decoration**, not orientation. Additionally, per I-3: **nothing may
animate on a poll tick** — the 2s ingest poll and 10s badge poll may flash only on a genuine state
*change*, never on every refresh.

---

## 6. Reference traits extracted

Fetched live 2026-08-03. These are JS-heavy marketing sites: **copy and nav evidence is `✓`** (literally
present in the served markup); **visual traits are characterized at posture level, marked `~`** — I did
not fabricate hexes, fonts, or measurements I could not evidence. No live-recon notes existed for this
run (`{LIVE_RECON_PATH}` absent — the browser handshake is main-session-only and did not happen).
Depth is spent on REF-1/3/4/5/9 (closest to this domain: restraint, editorial hierarchy, authored
density, tool-craft); REF-2/6/7/8 are summarized.

| # | Site | Visual thesis | Trait extracted | Adaptable trait for arXMCP | Surface | Evidence |
|---|---|---|---|---|---|---|
| REF-1 | metalab.com | Extreme restraint; one sharp concept | Hero is a single declarative statement — *"We make interfaces"* — plus a numbered drag gallery whose markup carries the bare index sequence `1…24`. Confidence from omission. | **The numbered index as wayfinding, not decoration.** Adapt as D-2's `01 — Corpus / 02 — Discovery / 03 — Appendix` eyebrows and, in D-1, as the ledger's numbered row gutter. Also licenses D-1's core move: deleting the box is a legitimate identity, not an absence of one. | S-2 | ✓ copy + ✓ numbered index in markup |
| REF-2 | waabi.ai | Deep tech as calm conviction | Short declarative pairs: *"Built to think. Born to haul."*, *"We built our own road."*; capability blocks as one-word label + one honest sentence (*"Safe" / "The combination of advanced AI and neural simulation…"*, *"Scalable" / …*, *"Practical" / …*). Serious technology reads calm, never neon. | **The label + one-honest-sentence pair** is exactly the shape a posture lede needs: `Parse status` → *"skipped — arxiv notebooks have no PDF to parse; indexing state is below."* The product already writes in this register (`notebook_detail.html:64`); C5 promotes it from a hint to the page's focal element. | S-2 | ✓ copy |
| REF-3 | new.studio | Serif confidence; whitespace as status | Title-case editorial headlines (*"Transforming Brands, Building Futures"*), single-word section headings carrying full weight (*"Ambition"*, *"Selected Work"*), minimal nav (Case Studies / Approach / Insights / Contact). | **Whitespace and type weight as the hierarchy mechanism** — the D-2 seed. A notebook titled and spaced like a work rather than labelled like a record. | S-2 (D-2) | ✓ copy + nav |
| REF-4 | newgenre.studio | Editorial pacing, poetic precision | Eyebrow → headline → evidence rhythm; domain eyebrows (*Artificial Intelligence, Venture Capital, Cleantech…*) preceding case-study labels (*Brand Identity, Website, Motion*). **Type system named in the markup: Displaay Type's Serrif + Saans** — a two-voice serif/sans pairing, evidenced not assumed. | **The eyebrow → headline → evidence rhythm mapped to domain vocabulary**: `math.AG` → *Bridgeland stability conditions on K3 surfaces* → `6 papers · indexed 2026-08-03 · corpus v12`. This is the single highest-value trait in the table for I-6 (domain legibility) — it is how the console starts reading as mathematics. | S-2 (D-2 lede; D-1 masthead) | ✓ copy + ✓ font names in markup |
| REF-5 | filter.im | High-contrast editorial density | Dense but strictly hierarchical; three-item nav (**Index / Studio / Connect**); section headings that state an outcome, not a category (*"Websites that perform on day one."*, *"High stakes, high speed. That's Filter."*). | **Density is authored, not accidental** — the direct rebuttal to BAN-14. A ledger sheet is allowed to be dense *because* the rule ladder and type scale make the density legible. Also: three-item nav validates that a tiny navigation is a statement, not a limitation. | S-2 (D-1) | ✓ copy + nav |
| REF-6 | ponder.ai | Dark cinematic product UI done right | *"Video Editing, Reinvented" / "Your Fastest Cut, Powered by AI"*; product-specific, media-rich, single-accent dark. | **Dark is legitimate only when the material is the product's own.** The sharpest indictment of the Primer clone: arXMCP's dark mode is *someone else's* dark mode. Feeds C4 and D-3. | S-2 | ✓ copy |
| REF-7 | sohub.digital | 3D/media-led hero | Hero media carries the brand; chrome disappears. | **Not adaptable here** — media-led identity requires an S-1 surface and arXMCP has none. Recorded as deliberately unused. | — | ~ |
| REF-8 | trionn.com/404 | Every state is designable | **`GET /404` returns a genuine HTTP 404** (verified live this run — the status is real, the page is authored). | **Error and empty states are design surfaces.** Adapted at S-2 register, not cinematic: the preview 404, `pre.error`, "Never indexed", and "No discovery run yet" each carry cause + one action. Feeds C7. | S-2 | ✓ HTTP status |
| REF-9 | save.design | Product polish in a focused tool | *"Organize your design inspiration"* — "one clean space to browse, save, organize, and revisit." Its sibling surface (Savee) documents **20 keyboard shortcuts** built to "navigate, search and organize without breaking focus." | **Polish concentrated on the core loop, and keyboard as the operator's real interface.** For arXMCP the core loop is *add → discover → ingest → read the papers list*; that loop deserves the polish budget, and the overlay §7 already names the missing `/`-to-focus affordance. Feeds D-3 and C7. | S-2 | ✓ copy + ✓ shortcut inventory |

**Not appended to canon §4.** No `{TARGETS}` were supplied and I extracted no genuinely new site, so the
"Proposed references (unreviewed)" block is left untouched — correctly, since minting canon from a
scout's own run is what round-3 8f exists to prevent.

---

## 7. Direction-defining candidates

Eight candidates. Each answers all four §11 questions, carries a surface tag, names its cookie-cutter
delta, and cross-references existing code. **All are S-2. None proposes spectacle. None requires npm,
Node, a bundler, a CDN, or an SPA framework** — where a candidate touches JS at all it says so
explicitly and names the security-audit consequence.

---

### C1 · `corpus-before-machinery-reorder` **[DIRECTION-DEFINING]**
**Direction:** all three (it is invariant I-5 made structural) · **Surface:** S-2 · **Size:** M

Reorder `notebook_detail.html` so the notebook's identity + state + papers lead, and the five mutation
forms (Topic, Discover, Add-by-URL, Upload, Ingest) collapse into ONE native `<details>` "Manage this
notebook" region below the corpus. Index gets the same treatment: the notebooks list leads, the create
form collapses beneath it.

- **Q1 BAN removed:** BAN-5 (creates a real focal region), BAN-2 (7 cards → 3 regions), **BAN-R1** (the
  form-first order is arXMCP's own signature tell).
- **Q2 REF adapted:** REF-1's restraint and REF-5's authored density — *translated*, not copied: the
  studios use omission to make one statement land; here omission means the six things you rarely do stop
  competing with the one thing you always do. No editorial styling is imported.
- **Q3 Surface fit:** S-2, and it is the highest-value S-2 move available — it converts a measured
  1823px scroll to the operator's most common task into roughly one viewport.
- **Q4 Not-default:** a default assembly emits one Card per feature in authorship order — which is
  literally how this page was built (the milestone comments read as a changelog: m1, m2,
  discovery-m1/m4, m4, m9). A page ordered by *operator priority* rather than *shipping history* is a
  design decision no scaffold makes.
- **Motion:** `[MOT-15 accordion-expand]` via native `<details>`, reduced-motion gated. Job: **feedback**.
  No JS.
- **Cookie-cutter delta:** kills tells 2 and 5; softens 9. DQS dims 1, 2, 4 move the most of any single
  candidate in this brief.
- **Code:** `server/frontend/templates/notebook_detail.html:8-361` (section reorder only — the papers
  `<section>` is currently last in source order at :300-361); `index.html:6-121`. **Zero new CSS
  required for the reorder itself.**
- **Caution:** the five forms carry live htmx swap targets (`#topic-block`, `#discover-results`,
  `#papers-tbody`, `#ingest-status`); moving them inside `<details>` must not break `hx-target`
  resolution, and a `beforeend` swap into a collapsed `<details>` needs the region opened (or an
  explicit state cue) or the operator will believe the add failed.

---

### C2 · `retire-the-card-adopt-the-rule` **[DIRECTION-DEFINING]**
**Direction:** D-1 (primary); D-2-compatible · **Surface:** S-2 · **Size:** M

Delete `.card` as the universal container. Replace with a **graded hairline rule ladder** —
`--rule-section` (full), `--rule-row` (~60%), `--rule-meta` (dotted) — horizontal only, no vertical
edges. Radius → 0 on all structural containers; 4px survives only on interactive controls. One `.lede`
treatment marks the single focal region per view.

- **Q1 BAN removed:** BAN-2 (there is no card left to repeat), BAN-4 (radius/border/shadow defaults are
  replaced by an authored system), BAN-5 (the rule ladder *is* the hierarchy), contributes to BAN-15.
- **Q2 REF adapted:** REF-1 — *"confidence comes from what you leave out"* — translated from a
  marketing hero into a structural decision: the box is what's left out. REF-5 supplies the permission
  to be dense while staying hierarchical.
- **Q3 Surface fit:** S-2 §6 mandates ONE elevation method — "hairline OR soft shadow, never both plus
  glow." The product already has zero shadows; this makes hairline a *deliberate system* rather than an
  absence.
- **Q4 Not-default:** the rounded bordered Card **is** shadcn's identity. A console whose entire
  structure is carried by three weights of horizontal rule with zero boxes cannot be mistaken for one.
- **BLOCKING PREREQUISITE (a11y):** light-mode `--border #d8d8d8` on `--bg #f8f8f8` computes to
  **1.34:1** (and 1.43:1 on `--card-bg #fff`) by WCAG relative luminance — fine while borders are
  incidental, **failing SC 1.4.11's 3:1** the moment rules become the sole structural device. This
  candidate MUST darken the light rule token and re-run overlay §4's full contrast table. Dark
  `#6e7681` already clears at 4.12:1 (overlay §4).
- **Cookie-cutter delta:** kills tells 2, 4, 5.
- **Code:** `app.css:53-59` (`.card`), `:114-116` (table borders), `:42,47` (header/footer rules); every
  `<section class="card">` in both templates. New tokens extend the `:root` block at `app.css:11-18` —
  **never a parallel token set** (overlay §10).

---

### C3 · `two-voice-type-scale` **[DIRECTION-DEFINING]**
**Direction:** all three (expressed differently in each) · **Surface:** S-2 · **Size:** S–M

Author an actual type scale as tokens and formalize the two voices. Meta 11px uppercase tracked
+0.06em · small 13px · body 16px · section 20px · page title `clamp(1.5rem, 4vw + .5rem, 2.25rem)`.
Sans for prose; **`--mono` for every id, path, slug, timestamp, corpus version and state token** —
extending the `tabular-nums` scope already shipped at `app.css:133-135`. This introduces the **first
`letter-spacing` declaration in the product's history**.

- **Q1 BAN removed:** BAN-4 — the 1.10× h2→body step is the literal, measurable form the "untouched
  default stack" tell takes here — and it enables BAN-5's removal (a lede needs a scale to be built on).
- **Q2 REF adapted:** REF-3/REF-4's editorial scale contrast, **translated down to S-2 discipline**:
  their display sizes are 56px+ and belong to S-1; here the title caps at ~36px and the contrast is
  bought with tracking and voice rather than size. REF-4's markup evidences a two-voice system (Serrif +
  Saans); arXMCP's second voice is `--mono`, which it already owns.
- **Q3 Surface fit:** S-2 §6 names typography "the #1 lever," and it is the only lever that costs
  nothing here — **both voices are system stacks; zero font files, zero bytes, zero CSP impact.**
- **Q4 Not-default:** default assemblies ship one face at three sizes and never author tracking. A
  tracked micro-caps meta voice plus a strict mono data voice is a decision a scaffold cannot make for
  you.
- **Cookie-cutter delta:** kills tell 4; prerequisite for killing 5.
- **Code:** `app.css:23-25` (body stack), `:43` (h1), `:61` (card h2), `:62-65` (hint/note/empty/
  display-name), `:115` (th/td), `:133-135` (tabular-nums scope). Closes visual-scout LOW-3 and critic
  M4 (responsive ramp) in the same change via the `clamp()` idiom already used at `app.css:37`.
- **Dependency note:** **D-1's distinctiveness is load-bearing on this candidate.** Descoping C3 while
  shipping C2 yields "the same page with the borders removed" — a worse result than shipping neither.

---

### C4 · `de-primer-the-material` **[DIRECTION-DEFINING]**
**Direction:** all three (D-1/D-2 warm paper; D-3 cold ink — the candidate authors a material, the
direction picks which) · **Surface:** S-2 · **Size:** M

Replace the stitched two-source palette — a GitHub-Primer-cloned dark block plus an unattributed
bespoke light block — with **one authored material family derived in OKLCH from a single hue decision**,
both modes authored from the same source: a 4-step text ladder (≈100/70/50/35%), hairline borders at
authored alpha, ONE brand accent, semantic colours reserved exclusively for live state.

- **Q1 BAN removed:** **BAN-15** — this is the specific, evidenced form same-silhouette syndrome takes
  in this repo — plus BAN-1 (moves the shell off near-navy) and part of BAN-4.
- **Q2 REF adapted:** REF-6 — dark works when it is *product-specific* and single-accent. arXMCP's dark
  mode is currently product-specific to *GitHub*. REF-2 supplies the posture: serious technology reads
  as calm conviction, not as a borrowed accent.
- **Q3 Surface fit:** S-2 §6 — "pick a material, not a palette." The console has a palette; it has never
  had a material.
- **Q4 Not-default:** `#0d1117 / #161b22 / #58a6ff` is *recognizably GitHub* — that recognition is the
  whole complaint. An OKLCH-derived family with one accent and a real text ladder is recognizably
  nobody else.
- **HARD GATE:** every pair in overlay §4's contrast table must be recomputed; **a pair dropping below
  4.5:1 is a Phase-3 BLOCKER** (overlay §4, stated there, restated here because this candidate is the
  one that triggers it). The tightest pair today is dark `--danger` on `--card-bg` at 5.16:1 — there is
  only 0.66 of headroom. Also fold the ~12 hardcoded greys (`app.css:45,47,48,62-65,111,116,271-273`)
  and the 8 status-pill literals (`:165-168`, `:286-289`) into the token system in the same change; the
  in-file comment at `:268-269` already documents this as known-accepted debt.
- **Cookie-cutter delta:** kills tell 13; contributes to 4.
- **Code:** `app.css:11-18` (`:root`), `:242-291` (dark block). Keep `color-scheme: light dark`
  (`app.css:10`) — it is load-bearing for UA-styled control internals and is **not** a token (overlay §4).

---

### C5 · `posture-lede-for-the-notebook` **[DIRECTION-DEFINING]**
**Direction:** D-2 primary (editorial lede); D-1 renders it as a ruled masthead; D-3 as a fixed-width
state line · **Surface:** S-2 · **Size:** M

One focal module at the top of the detail page answering *"is this notebook usable, and what is in
it?"* in a single authored sentence composed of metered facts — kind · discovery category · N papers ·
parse state (with its meaning, not just its token) · last indexed · corpus version — at 2–3× the visual
weight of everything below it. Replaces the current `<dl class="meta">` + badge + hint assembly.

- **Q1 BAN removed:** BAN-5 (this *is* the focal element), BAN-13 (it is the deliberate opposite of the
  template opener: **one honest sentence of real facts, not four manufactured stat tiles** — and the
  overlay names KPI-card openers as arXMCP's own anti-reference), **BAN-R3**.
- **Q2 REF adapted:** REF-2's label + one-honest-sentence pairing (*"Safe" / "The combination of…"*)
  and REF-4's eyebrow → headline → evidence rhythm, translated from brand copy into **state copy**. The
  product already writes this way at `notebook_detail.html:64`; this promotes the register from a
  footnote to the page's opening statement.
- **Q3 Surface fit:** S-2 §6's lede module, sized for a working view (no display type; the S-1 hero
  register stays out).
- **Q4 Not-default:** the scaffold answer to "show notebook status" is a row of stat cards or a badge
  grid. A single typographically-weighted sentence built only from facts the daemon actually has —
  and which **abstains visibly** where it has none ("Never indexed") — is the anti-move, and it is what
  invariant I-1 requires.
- **Motion:** reuse the shipped `badge-flash` on genuine state change only. Job: **feedback**.
  **Explicitly rejected: `[MOT-18 number-tween]` on load** — no motion job is served by animating a
  count that just arrived.
- **Cookie-cutter delta:** kills tell 5; pre-empts 13. Largest single DQS gain on dims 1, 3, 8.
- **Code:** `notebook_detail.html:8-92` (`<dl class="meta">` at :48-76, parse-status badge at :59,
  freshness at :67-75); count/version data comes from the same handlers that already feed
  `server/routes/ui.py::ui_status_badge`.

---

### C6 · `authored-density-and-touch-floor` **[DIRECTION-DEFINING]**
**Direction:** all three (D-1 compact-uniform; D-2 dual-density; D-3 compact + toggle) · **Surface:**
S-2 · **Size:** S

Replace the single `padding: 1rem 1.25rem` / `0.5rem` rhythm with an **authored** density: a compact
data rhythm for tables and ledger rows, a comfortable rhythm for the lede and forms — plus a
`@media (pointer: coarse)` floor raising every interactive control to ≥44px **without touching desktop
density**.

- **Q1 BAN removed:** BAN-14 outright. Closes visual-scout HIGH-4 and critic M3 (measured: every button
  32px, `<select>` **19px**, inputs 33px, footer links 17px tall).
- **Q2 REF adapted:** REF-5 — density is authored, not accidental. The studio's dense image
  choreography works because hierarchy is explicit; the same logic licenses a tight papers ledger.
- **Q3 Surface fit:** S-2 §6 — "density is authored per view: analytic tables go compact; overview
  surfaces go spacious. Never uniform-medium everywhere."
- **Q4 Not-default:** a scaffold ships one padding scale and one width breakpoint. **Keying the touch
  floor to `pointer: coarse` rather than to a width breakpoint** is a deliberate authored decision — it
  fixes the actual problem (touch) instead of the proxy (narrow window).
- **Cookie-cutter delta:** kills tell 12.
- **Code:** `app.css:57` (card padding), `:87-98` (button padding `0.4rem 0.85rem`), `:115` (th/td),
  `:29` (body padding, identical desktop/mobile per manifest §3). **`select` has no base rule anywhere
  in the file** — which is exactly why it measures 19px; C7 gives it one, C6 gives it a floor.

---

### C7 · `state-fragments-ship-with-their-styles` **[DIRECTION-DEFINING]**
**Direction:** all three (it is a policy plus its four concrete fills) · **Surface:** S-2 · **Size:** S–M

Every server-emitted class gets a rule, and the policy binds going forward (**BAN-R2**). Concretely:
(a) `.status-badge__remediation` becomes a block caption below the pill instead of a 491px run-on line;
(b) the five `.discover-*` classes get a bibliography-row treatment — the Discover result is the only
surface in the console presenting external content for operator judgment and it is currently the
*least* styled; (c) `select` and `textarea` join the `input` family (same border/radius/padding,
`font-family: inherit`, `resize: vertical`, and **no `--mono`** on the prose textarea); (d) the
ingest-failure `<pre>` becomes `<pre class="error">` so the highest-stakes error in the product gets the
same alarm treatment every other error already has; (e) `[data-status]` becomes a real styling hook
instead of an inert attribute.

- **Q1 BAN removed:** BAN-R2, BAN-4 (finish is the invariant BAN-4 is really about), and it protects
  BAN-11 by keeping semantic colour attached to state.
- **Q2 REF adapted:** REF-9 — polish concentrated on the core loop, not spread thin. arXMCP's core loop
  is *add → discover → ingest → read the list*, and three of those four steps currently render
  unstyled. REF-8's doctrine extends it to error and empty states.
- **Q3 Surface fit:** S-2 §6 state craft; DQS dim 7, the dimension with the most latent value here
  because the behaviour is already correct and only the finish is missing.
- **Q4 Not-default:** the tell here is not shadcn — it is *unfinished*. A console where every emitted
  class is styled, including the failure paths, reads as authored by someone who used it.
- **Cookie-cutter delta:** contributes to tell 4; the single largest DQS dim-7 gain.
- **Code:** `server/routes/ui.py:297-337` (`_build_remediation_block`); `server/routes/notebooks.py:705-753`
  (`_discover_results_fragment`), `:2376-2389` (ingest-failure `<pre>`); `app.css:74-85` (input family to
  extend), `:137-148` (`pre.error` to reuse), `:152-168` (badge). **Pure CSS plus one one-line server
  string change. Zero JS, zero CSP impact.**

---

### C8 · `in-language-destructive-confirm` **[DIRECTION-DEFINING]**
**Direction:** D-1/D-2 as a two-stage inline confirm; D-3 as a typed command confirm · **Surface:** S-2
· **Size:** M

Replace the three `hx-confirm` → `window.confirm()` calls with a confirmation rendered in the console's
own language. Preferred minimum-JS path: a native `<dialog>` driven by `hx-on::htmx:confirm`, styled
from existing tokens. Lower-JS alternative: a two-stage `.danger` button whose first click swaps the
label to name the consequence.

- **Q1 BAN removed:** BAN-15-adjacent (an OS dialog is another product's chrome intruding at the
  highest-consequence moment — in dark mode it is the one place a bright system dialog flashes against
  the console) and it rescues BAN-10-grade copy currently trapped in unstyled chrome: the existing
  confirm strings are *good* ("On-disk data at `var/arxmcp/notebooks/{slug}/` is NOT deleted — run
  `tools/notebook_purge.py` to wipe the disk") and deserve to be readable.
- **Q2 REF adapted:** REF-8 — every state, errors and confirmations included, is a design surface;
  adapted at S-2 register (an authored, explanatory dialog, not a cinematic moment).
- **Q3 Surface fit:** S-2 — the three highest-consequence interactions in the product are currently the
  only three where the product's visual language does not apply at all.
- **Q4 Not-default:** scaffolds ship either the browser dialog or a stock modal. A confirm that names
  the exact on-disk consequence in the console's own type and colour, with the destructive verb as the
  affirmative label ("Delete notebook", never "OK"), is specific to this product's trust posture.
- **Motion:** ≤150ms open, reduced-motion gated. Job: **feedback**. Never a scale-bounce.
- **DECLARED COST:** this is the one candidate that **adds JS surface**. It is CSP-legal today with no
  CSP edit (`script-src 'self' 'unsafe-inline'`), but **any new JS widens the still-open UI security
  audit `chris-dare-dev/arXMCP#9`** and must be flagged in Phase 2 rather than passing silently. If the
  audit cost is judged too high this run, park it — do not shrink it to a CSS-only fake that loses the
  keyboard/focus-trap semantics `<dialog>` provides for free.
- **Cookie-cutter delta:** no §10 tell directly; DQS dims 7 and 8.
- **Code:** `index.html:111`, `notebook_detail.html:86` and `:350` (the three `hx-confirm` sites);
  `app.css:108` (`button.danger`), `:213` (its focus ring), `:315` (the in-flight ring compensation).

---

## 8. Out of scope / parking lot

- **D-3's `/` command line.** The defining move of the third direction; deliberately not surfaced as a
  candidate because D-3 is not recommended and it would push past the 8-candidate cap. If D-3 is chosen
  in Phase 2, it becomes candidate C9 with its `arXMCP#9` audit cost and its no-JS fallback stated up
  front. The overlay §7 already names the narrower version (`/` or Cmd-K to focus the URL-paste input)
  as an open gap — that narrower form is a legitimate D-1/D-2 candidate too, and is the cheapest way to
  get REF-9's keyboard-first trait without a full command surface.
- **`notebook_kind` chip on the index** (critic M6). Real gap, but it is a *feature* affordance rather
  than a direction-defining move, and it carries BAN-7 risk. If it ships: one chip per row, reusing the
  existing `.status-badge` vocabulary, never a second chip.
- **Timestamp humanization** (critic M5). Correctly parked by the critic with its own caveat: invariant
  I-2 wants *metered* facts, and "3 days ago" hides exactly the precision the thesis is built on. My
  read for Phase 2: keep the exact value visible, add relative context only as a `title`/secondary —
  never replace the metered fact with a fuzzy one. GitHub's `<relative-time>` custom element is the
  known pattern but is a vendored web component and must be weighed against I-4 before anyone reaches
  for it.
- **`aria-live` consolidation** (critic M1, 12 live regions on one page, 6 empty at first paint; the 2s
  ingest poll re-announcing on every tick). Genuinely important and genuinely not art direction — it is
  a correctness scope-reduction. Flagged here only so it does not fall between the briefs. Note the
  interaction: C1 moving forms into `<details>` changes which live regions are in the accessibility tree
  at all, so these two should be sequenced together.
- **ar5iv preview surface.** Un-audited this run — no paper in the deployment has stored HTML, so the
  route correctly 404s. Its house direction ("chrome recedes") is unchanged and its tight CSP is a
  constraint to honour. Needs a follow-up pass with an uploaded fixture before anyone restyles it.
- **Charts / an ingest-activity visualization.** No chart exists and none is proposed. If one is ever
  wanted, BAN-6 binds: threshold, annotation, and a stated "so what," or it does not ship.
- **The `uplift-demo` fixture notebook** seeded by the orchestrator should be deleted at run end
  (`DELETE /ui/api/notebooks/uplift-demo`) — recorded here so it is not forgotten.
- **Screenshots.** The §14 DQS half cannot gate without `✓ live` pictorial evidence. Before Phase 3
  scores a projected state, someone must capture real PNGs — the geometry substitute was sufficient for
  the anti-pattern half and is explicitly not sufficient for the positive half.
