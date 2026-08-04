# Synthesis — 2026q3-ui-uplift

**Run:** `2026q3-ui-uplift` · **Mode:** standard (5 scouts) · **Surface:** `tool` (S-2 wholesale)
**Briefs read end-to-end:** art-direction, visual-scout, current-state-critic, library-scout, inspiration-scout, plus the orchestrator's `discover/visual-manifest.md`.

**Evidence-tier notice (binding on everything below).** There are **ZERO PNG screenshots** this run —
the Browser pane was never displayed, so the page never composited frames. Every "Screenshot evidence"
field below reads `none — see visual-manifest.md §N`. The orchestrator captured live computed styles,
per-card y/height geometry at 1440×900 and 390px, the token set, the typography table, the htmx
inventory, the motion inventory and tap-target measurements against a running server, so the catalog
rests on `✓ live` (measured DOM) + `✓ code` (full 371-line `app.css` read) tiers. Per canon §14 the
**anti-pattern half of the cookie-cutter score is auditable from this evidence; the positive DQS half
is not** and must be re-scored against real PNGs before any ship gate. This is the single largest
limitation of the run and it is carried forward into the final report.

**User's brief (verbatim):** *"Uplift and improve the overall UI for the arXMCP application. Identify
what sections and aspects could be improved, which parts look AI-generated and unoriginal in terms of
the standard tailwind + shadcn UI feel, and propose new libraries which could give an interactive feel."*

**Premise correction, agreed independently by four of five briefs.** There is **no Tailwind and no
shadcn** in this codebase — no utility classes, no component directory, no `cn()`/CVA, no Node, no
build chain (CLAUDE.md §4.7 forbids them). `/ui/` is a hand-authored **371-line, 52-CSSOM-rule**
stylesheet, 3 Jinja2 templates, and one vendored `htmx.min.js`. The user's *perception* is correct;
the *diagnosis* is not. What actually produces the generic read is named in §0.2 and drives the frame.

---

## Section 0 — Design frame (ADOPTED from `art-direction-scout-brief.md`)

### 0.1 Visual thesis

> **arXMCP's console is the bench record of a one-person mathematics lab: every notebook is a named
> body of literature with a stated question, a provenance trail, and a parse-and-index state the
> operator can read as a metered fact — and the console shows the corpus before the machinery that
> mutates it.**

Swap-test passes (substitute "generic notebook manager" / "internal admin dashboard" / "Docker
registry UI" and the sentence collapses). This SHARPENS the house-thesis overlay §9; it does not
replace it. Six binding invariants: **I-1** operational honesty · **I-2** provenance & freshness as
metered facts · **I-3** calm at repeat use · **I-4** sovereign minimalism (3 pages, zero build chain,
zero egress) · **I-5 corpus before machinery** *(new)* · **I-6 domain legibility** *(new)*.

### 0.2 Why it reads as generic — the measured causes

Cookie-cutter score **6/13** (independent range 5–6), landing at the "generic AI dashboard" band edge:

| Tell | Measured evidence |
|---|---|
| BAN-2 — 6+ equal rounded cards as primary layout | 7 `<section class="card">` on the detail page, all measured at **identical** 1293px width / `6px` radius / 1px border / `1rem 1.25rem` padding / `margin-bottom: 1rem` / `box-shadow: none` |
| BAN-4 — untouched default-stack look | unmodified `-apple-system` stack; **zero `letter-spacing` in 371 lines**; h2→body step is **1.10×** (hierarchy carried by weight alone); **zero `box-shadow`**; **zero `transition`** outside the reduced-motion clamp |
| BAN-5 — no focal element | papers table (the only corpus content) begins at **y=1823 of a 2343px** document, after six consecutive input forms |
| BAN-9 — no button hierarchy | one button style + one `.danger` variant; no secondary/ghost tier exists |
| BAN-14 — uniform density | identical card padding everywhere; `body { padding: 1rem }` **identical at 1440px and 390px** |
| BAN-15 — same-silhouette syndrome | the dark palette is a **self-documented GitHub-Primer clone** — `app.css:234-241` says so in its own comment, and the values are GitHub's exact `#0d1117` / `#161b22` / `#58a6ff` / `#f85149`; the light palette comes from a different, unattributed source |

**The DQS half is worse than the anti half** and is where this run's value sits: mean ≈ **1.4** against
a 3.0 ship bar, with dims 1 (task clarity), 3 (decision integrity) and 8 (product signature) at the
bottom. A run that only deleted the six tells and left the page answering nothing trades one failure
for another.

**Current de-facto thesis, stated honestly:** *"whatever ships correct, styled to whatever GitHub
already proved was accessible."* Borrowed, adopted for contrast safety, never revisited.

### 0.3 Chosen direction — **D-1 · The Ledger Sheet** (runner-up D-2 · The Reading Room)

> *"The console is one continuous record of account, not a stack of panels. Rules carry every
> structure; the box is deleted."*

Zero-radius structural containers (radius survives only on interactive controls) · a **graded hairline
rule ladder** (`--rule-section` / `--rule-row` / `--rule-meta`, horizontal only, no vertical edges)
replacing all borders · **`--mono` as a true data voice** on every id/path/slug/timestamp/version ·
**tracked micro-caps** column meta (the first authored `letter-spacing` in the product's history) ·
the **row as the unit of interaction**.

Chosen over D-2 ("Reading Room", editorial/serif — costs a vendored `woff2`, an asset-story change the
product has never made) and D-3 ("Console Rail", mono-forward + `/` command line — costs real new JS
and widens the still-open UI security audit `chris-dare-dev/arXMCP#9`) because **D-1 removes the most
scored tells at the lowest risk: pure CSS plus a template reorder, no font file, no new JS, no CSP
change.** It also attacks the complaint at its root — the "AI-generated" feel here IS the box, and
deleting the rounded-bordered card primitive is the one move a default assembly never makes, because
the Card *is* the default assembly's identity. D-1 and D-2 share a material, so a D-1 core with a D-2
posture lede is a coherent v2; choosing D-3 would forecloses both.

**Load-bearing dependency, stated up front:** D-1's distinctiveness rests entirely on **UPL-3 (type
scale)** and **UPL-4 (material)**. Ship UPL-2 without them and the result is "the same page with the
borders removed" — a worse outcome than shipping nothing. Phase 3 must hold this.

### 0.4 Active BAN list

**Present today — must be REMOVED:** BAN-2, BAN-4 (invariant reading), BAN-5, BAN-9, BAN-14, BAN-15.

**Absent today — must NOT be INTRODUCED (the real risk set):** BAN-1 (the shell is already near-navy;
*any* second accent flips this) · **BAN-3** (icon-in-rounded-square tiles — the single most likely
"make it prettier" move; the product has zero icons today and that is an asset) · BAN-6 (an "ingest
activity" sparkline without threshold + annotation + a stated "so what") · BAN-7 (badge soup — the
`notebook_kind` chip is legitimate at *one chip per row* and becomes soup at two) · BAN-8 (no
glass/glow — hairline is the sole elevation method) · **BAN-10** (the current copy is a genuine
strength — no "Welcome back", no "Command Center") · BAN-11 (don't let `--danger` drift further
between destructive-action and error-state) · BAN-12 (wholesale) · BAN-13 (a KPI stat-tile row would
manufacture metrics the daemon does not have).

**Run-scoped anti-references (arXMCP-specific, NOT canon §5 entries):**
- **BAN-R1 · Form-first page order** — mutation controls rendered above the content they mutate. arXMCP's own signature tell.
- **BAN-R2 · Unstyled-fragment debt** — server-emitted classes shipped with no CSS rule. **Any new fragment must land with its rule in the same change.**
- **BAN-R3 · Instrument without a reading** — a status surface reporting a token but not the fact behind it (`parse_status: skipped` needing a sentence of prose to be interpretable).

**New standing negative baseline:** because the palette is literally GitHub's, **"looks like GitHub"
is now a measurable, citeable failure state**, not a vague worry.

### 0.5 Surface map — every route is S-2 tool class

| # | Surface | Route / file | Class | Motion budget |
|---|---|---|---|---|
| 1 | Notebook index + create | `GET /ui/` · `index.html` | S-2 | `MOT-24` row hover ≤100ms · `MOT-15` details expand · shipped `row-fade-out` |
| 2 | Notebook detail (the dense page) | `GET /ui/notebooks/{slug}` · `notebook_detail.html` | S-2 | `MOT-15`, `MOT-24`, shipped `badge-flash`, shipped view transitions ≤200ms |
| 3 | ar5iv paper preview | `.../papers/{id}/preview` | S-2 (document view) | none — chrome recedes; tight CSP is a constraint to honour. **Un-audited this run** |
| 4 | Operability badge fragment | `GET /ui/status-badge` (10s poll) | S-2 | shipped `badge-flash` (feedback job) only |
| 5 | htmx fragments | 5 fragment builders in `routes/notebooks.py` + `routes/ui.py` | S-2 | swap-state only; **no motion on a poll tick** (I-3) |
| 6 | Empty / error / abstention states | `.empty`, `pre.error`, preview 404 | S-2 | none |

**Binding gate consequences.** `EXP-*` tokens are **BLOCKED wholesale**. AP-1/2/3/5 (parallax,
smooth-scroll hijack, scroll-scrub/zoom, WebGL) are **BLOCKED**. Motion is `MOT-*` only and every
candidate names one of the four jobs — orientation / causality / feedback / continuity — or it does
not ship. Two pre-emptive rejections: **`MOT-18` number-tween on load fails the jobs test** (no job is
served by animating a count that just arrived) and **`MOT-3` stagger-reveal on the papers table is
decoration**. Per I-3, **nothing may animate on a poll tick** — the 2s ingest poll and 10s badge poll
may flash only on a genuine state *change*.

---

## 1. Executive summary

**26 candidates**, dominated by **Cross-cutting refactor**, **Layout**, and **Interaction**. The top
theme is not "add polish" — it is that **seven independently-correct feature milestones each added one
`.card` and nothing has ever owned the page as a whole**; four of the five HIGH findings in the
current-state critique are server-emitted classes that shipped with no CSS rule at all
(`.status-badge__remediation`, the five `.discover-*` classes, `select`/`textarea`, the ingest-failure
`<pre>`). The top-5 is **not** all `[polish]`: four of five are `[DIRECTION-DEFINING]` (UPL-1 reorder,
UPL-2 retire-the-card, UPL-3 type scale, UPL-4 de-Primer the material) and the fifth (UPL-7) is the
finish-debt policy that makes the others hold.

**Top tension across briefs:** the library scout and the inspiration scout both answer the user's
"propose new libraries" ask with **"zero new libraries"** — and they are right about the constraint
(npm/CDN/SPA are automatic BLOCKERs under CLAUDE.md §4.7 + `CONTENT_SECURITY_POLICY_UI`'s
`script-src 'self' 'unsafe-inline'`) — but the honest answer to the user is not "no": it is that the
**2022–2026 CSS platform now ships, at zero bytes, most of what Framer Motion / shadcn / Radix exist to
paper over**, plus three 0BSD single-file htmx-family drops that fit arXMCP's proven vendoring lane.
That is UPL-11/12/16/17/18/19/26 and it is a real answer, not a refusal.

**Second tension:** the visual scout proposes a `box-shadow` hover-lift on cards (VS HIGH-1) while the
art-direction frame **bans shadow outright** (hairline is D-1's sole elevation method) and deletes the
card entirely. Resolution: the frame wins; the underlying job (differentiate primary from secondary
surfaces) is served by UPL-2's rule ladder + UPL-5's lede, not by elevation.

## 2. Triangulation strength

| Sources | Count | Candidates |
|---|---|---|
| **4 briefs (very strong)** | 3 | UPL-1, UPL-3, UPL-7 |
| **3 briefs (strong)** | 5 | UPL-2, UPL-4, UPL-6, UPL-11, UPL-12 |
| **2 briefs** | 7 | UPL-5, UPL-8, UPL-9, UPL-10, UPL-13, UPL-15, UPL-16 |
| **1 brief (weak — flag for challenger scrutiny)** | 11 | UPL-14, UPL-17, UPL-18, UPL-19, UPL-20, UPL-21, UPL-22, UPL-23, UPL-24, UPL-25, UPL-26 |

## 3. Foundational candidates (sequence these FIRST)

1. **UPL-4 — token/material system.** Every colour-touching candidate depends on it, and it carries
   the run's one HARD GATE: overlay §4's full contrast table must be recomputed, and **a pair dropping
   below 4.5:1 is a Phase-3 BLOCKER** (tightest pair today, dark `--danger` on `--card-bg`, has only
   **0.66 of headroom**).
2. **UPL-3 — type scale.** Prerequisite for UPL-2 and UPL-5; without it UPL-2 degrades to "borders removed."
3. **UPL-2 — rule ladder.** Carries a **BLOCKING a11y prerequisite**: light `--border #d8d8d8` on
   `--bg #f8f8f8` computes to **1.34:1**. Tolerable while borders are incidental; **fails SC 1.4.11's
   3:1 non-text bar the moment rules become the sole structural device.** UPL-2 cannot ship without
   darkening the light rule token inside UPL-4.
4. **UPL-7 — "fragments ship with their styles" policy (BAN-R2).** Not just four fixes — the standing
   rule that stops the debt regenerating.

**Already SHIPPED — do NOT re-catalog as net-new** (verified against the live `app.css` this run):
`prefers-reduced-motion` universal clamp · `:focus-visible` rings incl. the `button.danger` variant and
the `:focus:not(:focus-visible)` reset · `.skip-link` + `<main tabindex="-1">` · full
`prefers-color-scheme: dark` token remap · `color-scheme: light dark` · `.table-wrap { overflow-x:
auto }` · `font-variant-numeric: tabular-nums` · `aria-live`/`aria-atomic` on the badge · viewport meta
· `.htmx-request` loading state + gated `::after` spinner · `badge-flash` · `row-fade-out` ·
same-document View Transitions at 200ms.

---

## 4. Candidate catalog

### UPL-1 — Reorder the detail page: corpus before machinery **[DIRECTION-DEFINING]**

**Category:** Layout · **Size:** M · **Evidence triangulation:** 4 briefs (art-direction ✓, visual ✓, current-state ✓, inspiration ✓)
**Motion primitives:** `[MOT-15 accordion-expand]` — job: **feedback** (native `<details>`, reduced-motion gated, zero JS)

**What it is:** Reorder `notebook_detail.html` so the notebook's identity + state + papers table lead,
and the five mutation forms (Topic, Discover, Add-by-URL, Upload, Ingest) collapse into ONE native
`<details>` "Manage this notebook" region below the corpus. `index.html` gets the same treatment: the
notebooks list leads, the create form collapses beneath it.

**Why it matters:** Opening a notebook to see what is in it — almost certainly the single most common
reason to open the page — currently costs **1823px of scrolling past six input forms**. This converts
that to roughly one viewport.

**Sources:**
- Art-direction: C1 `corpus-before-machinery-reorder`; invariant **I-5** made structural; kills BAN-5, BAN-2, **BAN-R1**
- Visual scout: **CRITICAL-1** — the only CRITICAL in the run; papers table at y=1823 of 2343px
- Current-state critic: **H4** — "no milestone owned 'the page as a whole'"; 7 cards from 7 separate milestones
- Inspiration scout: **P1** — Linear's 2026 refresh, "don't compete for attention you haven't earned" (https://linear.app/now/behind-the-latest-design-refresh)

**Closest arXMCP analog today:** `server/frontend/templates/notebook_detail.html:8-361` — the papers
`<section class="card">` is literally last in source order (`:300-361`), and the source order mirrors
shipping history (the milestone comments read m1, m2, discovery-m1/m4, m4, m9), not operator priority.

**Screenshot evidence:** none — `visual-manifest.md` §3 card-geometry table.

**Sketch:** Pure template reorder; **zero new CSS required for the reorder itself**. Wrap the five
mutation sections in one `<details class="manage">` with a `<summary>`. Gate any expand animation on
`@media (prefers-reduced-motion: no-preference)`.

**Open questions:** The five forms carry live htmx swap targets (`#topic-block`, `#discover-results`,
`#papers-tbody`, `#ingest-status`). Moving them inside `<details>` must not break `hx-target`
resolution, and a `beforeend` swap into a **collapsed** `<details>` needs the region force-opened (or
an explicit state cue) or the operator will believe the add silently failed. This is the one real
implementation risk in the candidate.

---

### UPL-2 — Retire `.card`; adopt a graded hairline rule ladder **[DIRECTION-DEFINING]**

**Category:** Cross-cutting refactor · **Size:** M · **Evidence triangulation:** 3 briefs (art-direction ✓, visual ✓, current-state ✓)
**Motion primitives:** none (structure, not motion)

**What it is:** Delete `.card` as the universal container. Replace with three weights of horizontal
rule (`--rule-section` full / `--rule-row` ~60% / `--rule-meta` dotted), no vertical edges. Radius → 0
on structural containers; 4px survives only on interactive controls, so geometry itself encodes
"structure vs control." One `.lede` treatment marks the single focal region per view.

**Why it matters:** The rounded bordered Card **is** shadcn's identity. Seven identical ones is the
literal, measured form of the user's complaint. Deleting the primitive is the most direct possible
answer, and it is the move a default assembly will never make.

**Sources:**
- Art-direction: C2 `retire-the-card-adopt-the-rule`; kills tells 2, 4, 5; **[RECOMMENDED direction D-1's defining move]**
- Visual scout: HIGH-1 card sameness — `grep box-shadow` → 0 matches in 371 lines; `.card` applied identically to all 9 sections across both templates
- Current-state critic: H5(c)(d) — binary 4px/6px radius system (7 sites / 1 site), zero elevation language

**Closest arXMCP analog today:** `app.css:53-59` (`.card`), `:114-116` (table borders), `:42,47`
(header/footer rules).

**Screenshot evidence:** none — `visual-manifest.md` §3.

**Sketch:** New rule tokens **extend the `:root` block at `app.css:11-18`** — never a parallel token
set. Pure CSS + a class swap in both templates.

**Open questions:** **BLOCKING a11y prerequisite** — light `--border #d8d8d8` on `--bg #f8f8f8` is
**1.34:1** (1.43:1 on `--card-bg`). Fine while borders are incidental; **fails SC 1.4.11 (3:1
non-text) the moment rules are the sole structural device.** Must darken the light rule token and
re-run overlay §4's contrast table — i.e. UPL-2 **cannot ship before UPL-4**. Dark `#6e7681` already
clears at 4.12:1. Second: the visual scout's competing `box-shadow` hover-lift proposal is **rejected**
by the frame (BAN-8, hairline-only).

---

### UPL-3 — Author a two-voice type scale **[DIRECTION-DEFINING]** **[FOUNDATIONAL]**

**Category:** Typography · **Size:** S–M · **Evidence triangulation:** 4 briefs (art-direction ✓, visual ✓, current-state ✓, library ✓)
**Motion primitives:** none

**What it is:** Author an actual type scale as tokens — meta 11px uppercase tracked +0.06em · small
13px · body 16px · section 20px · page title `clamp(1.5rem, 4vw + .5rem, 2.25rem)` — and formalize the
two voices: sans for prose, **`--mono` for every id, path, slug, timestamp, corpus version and state
token**, extending the `tabular-nums` scope already shipped at `app.css:133-135`. Introduces the
**first `letter-spacing` declaration in the product's history**.

**Why it matters:** The 1.10× h2→body step is the literal, measurable form the "untouched default
stack" tell takes here. Both voices are **system stacks — zero font files, zero bytes, zero CSP
impact** — so this is the highest-leverage/lowest-cost move in the catalog.

**Sources:**
- Art-direction: C3 `two-voice-type-scale`; canon §6 names typography "the #1 lever"; closes VS LOW-3 + CS M4 in the same change via the `clamp()` idiom already at `app.css:37`
- Visual scout: XR-3 + LOW-3 — one effective step; `h1` stays 32px at 390px, no responsive ramp
- Current-state critic: H5(e)(f) + M4 — zero `letter-spacing`; canon §6 asks for meta 11-12 / body 14-16 / section 20-24 / title 28-40
- Library scout: CAND-7 `text-wrap: balance` on `h1, .card h2` (0 bytes, Newly Available → Widely 2026-11-13, harmless fallback)

**Closest arXMCP analog today:** `app.css:23-25` (body stack), `:43` (h1), `:61` (card h2), `:62-65`
(hint/note/empty/display-name), `:115` (th/td), `:133-135` (tabular-nums scope).

**Screenshot evidence:** none — `visual-manifest.md` §2 typography table.

**Sketch:** Add type tokens to the `:root` block at `app.css:11-18`. Apply `--mono` to the ids/paths/
timestamps already in the templates. `text-wrap: balance` needs no `@supports` gate.

**Open questions:** **D-1's entire distinctiveness is load-bearing on this candidate** — descoping it
while shipping UPL-2 yields a worse result than shipping neither. Phase 3 must hold that pairing.

---

### UPL-4 — De-Primer the material: one authored OKLCH family **[DIRECTION-DEFINING]** **[FOUNDATIONAL]**

**Category:** Color/theme · **Size:** M · **Evidence triangulation:** 3 briefs (art-direction ✓, current-state ✓, library ✓)
**Motion primitives:** none

**What it is:** Replace the stitched two-source palette — a GitHub-Primer-cloned dark block plus an
unattributed bespoke light block — with **one authored material family derived in OKLCH from a single
hue decision**, both modes from the same source: a 4-step text ladder (~100/70/50/35%), hairline
borders at authored alpha, ONE brand accent, semantic colours reserved exclusively for live state.
Folds the ~12 hardcoded greys and 8 status-pill literals into the token system in the same change.

**Why it matters:** `#0d1117 / #161b22 / #58a6ff` is *recognizably GitHub* — and that recognition **is**
the user's complaint, stated precisely. This is the single most specific answer to "why does it look
like something I've seen before."

**Sources:**
- Art-direction: C4 `de-primer-the-material`; kills BAN-15 + BAN-1; canon §6 "pick a material, not a palette"
- Current-state critic: H5(a)(b) + the token-bypass row — `app.css:234-241`'s own comment says "GitHub-Primer-anchored values"; hardcoded greys at `:45,47,48,62-65,111,116,271-273`; 8 pill literals at `:165-168` / `:286-289`
- Library scout: CAND-9 `light-dark()` (0 bytes, Widely Available 2026-11-13) collapses the ~50-line duplicated light/dark block into one declaration per token — **but the scout ranks it as a refactor-only candidate precisely because of the contrast gate below**

**Closest arXMCP analog today:** `app.css:11-18` (`:root`), `:242-291` (the dark block).

**Screenshot evidence:** none — `visual-manifest.md` §1 token table.

**Sketch:** Keep `color-scheme: light dark` (`app.css:10`) — load-bearing for UA-styled control
internals, and **not** a token. Extend the existing `:root`; never parallel-define.

**Open questions:** **HARD GATE** — every pair in overlay §4's contrast table must be recomputed and
**a pair dropping below 4.5:1 is a Phase-3 BLOCKER**; the tightest pair (dark `--danger` on
`--card-bg`, 5.16:1) has only **0.66 of headroom**. Also: UPL-2's 3:1 non-text rule requirement must
be satisfied *inside* this candidate. Is the OKLCH re-derivation one milestone or two (v0 tokens,
v1 pill/grey fold-in)?

---

### UPL-5 — A posture lede for the notebook **[DIRECTION-DEFINING]**

**Category:** Layout · **Size:** M · **Evidence triangulation:** 2 briefs (art-direction ✓, current-state ✓)
**Motion primitives:** shipped `badge-flash` on genuine state change only — job: **feedback**. **`[MOT-18 number-tween]` explicitly REJECTED** (no job served by animating a count that just arrived).

**What it is:** One focal module at the top of the detail page answering *"is this notebook usable, and
what is in it?"* in a single authored sentence composed of metered facts — kind · discovery category ·
N papers · parse state **with its meaning, not just its token** · last indexed · corpus version — at
2–3× the visual weight of everything below. Replaces the current `<dl class="meta">` + badge + hint
assembly.

**Why it matters:** Largest single DQS gain in the catalog (dims 1, 3, 8 — the three canon §14 requires
at ≥3, all currently at ~1). It is also the deliberate **opposite** of the template opener: one honest
sentence of real facts, **not four manufactured stat tiles** (BAN-13), and it **abstains visibly**
where the daemon has no fact ("Never indexed") per invariant I-1.

**Sources:**
- Art-direction: C5 `posture-lede-for-the-notebook`; kills BAN-5, pre-empts BAN-13, kills **BAN-R3**; REF-2 label+one-honest-sentence, REF-4 eyebrow→headline→evidence
- Current-state critic: H4 — the house thesis says the page should lead with "parse-status + freshness answer 'is this notebook usable?'"; the live page does not deliver that ordering

**Closest arXMCP analog today:** `notebook_detail.html:8-92` — `<dl class="meta">` at `:48-76`,
parse-status badge at `:59`, freshness at `:67-75`. The product already writes in the right register at
`:64` ("PDF parse — arxiv notebooks skip this; see 'Last indexed' below for indexing"); this promotes
that voice from a footnote to the page's opening statement.

**Screenshot evidence:** none — `visual-manifest.md` §3.

**Sketch:** Count/version data comes from the same handlers already feeding
`server/routes/ui.py::ui_status_badge`. Depends on UPL-3 for the weight step to exist.

**Open questions:** Does "N papers" mean rows in the papers junction table or chunks in LanceDB? The
two diverge (the `bridgeland-stability*` notebooks have large LanceDB corpora but **0** rows via
`/ui/api`), and I-1 forbids reporting a number the operator cannot trust.

---

### UPL-6 — Authored density + a coarse-pointer touch floor **[DIRECTION-DEFINING]**

**Category:** Layout · **Size:** S · **Evidence triangulation:** 3 briefs (art-direction ✓, visual ✓, current-state ✓)
**Motion primitives:** none

**What it is:** Replace the single `padding: 1rem 1.25rem` / `0.5rem` rhythm with an **authored**
density — compact for tables and ledger rows, comfortable for the lede and forms — plus a
`@media (pointer: coarse)` floor raising every interactive control to ≥44px **without touching desktop
density**.

**Why it matters:** Kills BAN-14 outright, and closes the one machine-checkable accessibility bar the
console misses: every `button` measures **32px tall**, `<select>` **19px**, footer links **17px**.

**Sources:**
- Art-direction: C6 `authored-density-and-touch-floor`; canon §6 "density is authored per view... never uniform-medium everywhere"
- Visual scout: HIGH-4 (six 77×32 Remove buttons adjacent in a table column — a slightly-off tap risks an adjacent row's destructive control) + LOW-2 (footer links 48×17 / 44×17)
- Current-state critic: M3 — "the layout was made mobile-*capable* without being made mobile-*comfortable*"

**Closest arXMCP analog today:** `app.css:57` (card padding), `:87-98` (button `0.4rem 0.85rem`),
`:115` (th/td), `:29` (body padding — identical desktop and mobile).

**Screenshot evidence:** none — `visual-manifest.md` §3 mobile tap-target table.

**Sketch:** Keying the floor to `pointer: coarse` rather than a width breakpoint fixes the actual
problem (touch) instead of the proxy (narrow window). `select` has **no base rule anywhere** in
`app.css`, which is exactly why it measures 19px — UPL-8 gives it one, UPL-6 gives it a floor.

**Open questions:** A taller button changes the vertical rhythm of every card — sequence after UPL-2 so
the rhythm is only re-tuned once.

---

### UPL-7 — Policy: every server-emitted class ships with its CSS rule (BAN-R2) **[DIRECTION-DEFINING]** **[FOUNDATIONAL]**

**Category:** Cross-cutting refactor · **Size:** S–M · **Evidence triangulation:** 4 briefs (art-direction ✓, visual ✓, current-state ✓, inspiration ✓)
**Motion primitives:** none

**What it is:** The standing rule — plus its concrete backlog, which is UPL-8/9/10 below. Nothing new
may ship a class the stylesheet does not style.

**Why it matters:** This is the **single largest DQS dim-7 gain** available and the root cause the
current-state critic traced nearly every HIGH finding to: *"feature milestones shipped complete,
tested, secure behavior and left CSS as an afterthought scoped to 'does it render,' not 'does it look
finished' — because no milestone's acceptance criteria named 'style this.'"* The tell here is not
shadcn; it is **unfinished**.

**Sources:** art-direction C7 · current-state H1/H2/H3/M2 + §6 conflict list · visual MEDIUM-1 ·
inspiration P5/P6 (the discover + ingest surfaces are exactly the unstyled ones).

**Closest arXMCP analog today:** the four unstyled surfaces enumerated in UPL-8/9/10, plus the inert
`[data-status]` attribute at `routes/notebooks.py:2310-2389` and four unused hook classes
(`notebook_detail.html:31,82,109,119`).

**Sketch:** Pure CSS plus one one-line server string change (UPL-10). **Zero JS, zero CSP impact.**

**Open questions:** Where does the policy live so it actually binds — a line in CLAUDE.md §4.7, a
milestone-pipeline acceptance-criteria template, or a test that greps emitted classes against
`app.css`? A test is the only version that cannot rot.

---

### UPL-8 — Give `select` / `textarea` the input family's styling

**Category:** Cross-cutting refactor · **Size:** XS · **Evidence triangulation:** 2 briefs (current-state ✓, library ✓)
**Motion primitives:** none

**What it is:** Extend `input[type="text"], input[type="url"], input[type="file"]` (`app.css:74-84`) to
also match `select, textarea` — same border, radius, padding, background, `font-family: inherit`. Add
`resize: vertical` to `textarea`; **do NOT** extend `--mono` to it (topic/keyword text is prose, not a
slug).

**Why it matters:** `select` and `textarea` appear in exactly ONE place in all 371 lines — the shared
`:focus-visible` selector list at `:207`. Four controls across the create and topic forms render as
raw OS widgets beside hand-styled siblings. This is the most common "someone started a design pass and
didn't finish it" tell in existence, independent of any framework.

**Sources:**
- Current-state critic: **H2** — `select` 19px vs `input` 33px inside the same form row
- Library scout: CAND-4 `field-sizing: content` (0 bytes, Newly Available 2026-06-16) auto-grows the one `<textarea>` in the product, with the existing `rows="2"` as the built-in fallback behind `@supports (field-sizing: content)`

**Closest arXMCP analog today:** `app.css:74-85`; `index.html:47-58`, `notebook_detail.html:129-140`.

**Sketch:** One selector-list extension. `field-sizing` MUST be `@supports`-gated (Firefox/Safari not
confirmed).

**Open questions:** none.

---

### UPL-9 — Style the Discover-results candidate list

**Category:** Layout · **Size:** S · **Evidence triangulation:** 2 briefs (current-state ✓, inspiration ✓)
**Motion primitives:** `[MOT-1 fade-in]` on the results group as a whole — job: **causality**. **`[MOT-3 stagger-reveal]` explicitly REJECTED** (AP-3 blocks it above 8 items on S-2; the candidate count can reach 10).

**What it is:** Five small rules for `.discover-list` / `.discover-candidate` / `.discover-title` /
`.discover-meta` / `.discover-abstract`, giving the discovered-paper rows a bibliography-style
title/meta/abstract hierarchy. Optionally add the "why this matches your topic" line NotebookLM ships.

**Why it matters:** This is **the only surface in the console that presents external content for
operator judgment**, and it is the *least* styled thing in the product — currently a bare bulleted
`<ul>` with default browser margins.

**Sources:**
- Current-state critic: **H3** — `routes/notebooks.py:705-753` emits five classes; `grep` finds **zero** rules for any of them
- Inspiration scout: **P5** — NotebookLM "Discover sources": topic → up to 10 candidates each with *an annotated summary explaining its relevance* → one-click import (https://blog.google/technology/google-labs/notebooklm-discover-sources/). The closest domain analogue found — a scholarly-research tool solving the identical workflow.

**Closest arXMCP analog today:** `#discover-results` at `notebook_detail.html:176`, currently
`<p class="hint">No discovery run yet…</p>`.

**Sketch:** Reuse existing tokens; `.discover-meta` in `--mono` picks up `tabular-nums` for free if
`<time>` stays as the element.

**Open questions:** Does the arXiv Atom driver return enough to generate a genuine relevance line, or
would that be manufactured? I-1 forbids the latter.

---

### UPL-10 — Make the ingest-failure `<pre>` use the house error treatment

**Category:** Data viz · **Size:** XS · **Evidence triangulation:** 2 briefs (current-state ✓, inspiration ✓)
**Motion primitives:** `[MOT-28 spinner]` — reuse of the shipped `@keyframes spin` for a run-status icon. Job: **feedback**.

**What it is:** Change `f"<pre>{stderr_pre}</pre>"` to `f'<pre class="error">{stderr_pre}</pre>'` at
`routes/notebooks.py:2380`, and make the inert `data-status` attribute a real styling hook (status
icon + `--mono` log rendering).

**Why it matters:** Every other error surface in the console (`create-error`, `rename-error`,
`topic-error`, `discover-error`, `paste-error`, `upload-error`, `ingest-error`) uses `pre.error` with
its tinted `--error-bg` + `--danger` treatment. **The failed corpus ingest — arguably the single most
operationally important error an operator will ever read here — gets none of it.**

**Sources:**
- Current-state critic: **M2** + §6 conflict list — the fragment predates `pre.error` becoming the house convention
- Inspiration scout: **P6** — GitHub Actions' closed `queued → in_progress → completed`+conclusion enum maps almost 1:1 onto arXMCP's own documented `queued → running → complete/failed` lifecycle, but the rendered surface is plain text with no icon

**Closest arXMCP analog today:** `routes/notebooks.py:2310-2389`; `app.css:137-148` (`pre.error`, to reuse).

**Sketch:** One-line server change reusing existing CSS; the icon reuses `.status-badge--{ok,warn,down}`
colours and the already-shipped `spin` keyframe. **Zero new keyframes.**

**Open questions:** none.

---

### UPL-11 — Replace `window.confirm()` with an in-language `<dialog>` **[DIRECTION-DEFINING]**

**Category:** Interaction · **Size:** M · **Evidence triangulation:** 3 briefs (art-direction ✓, visual ✓, library ✓; current-state ✓ as M1's destructive half — effectively 4)
**Motion primitives:** `[MOT-4 scale-in]` ≤150ms via `@starting-style`, reduced-motion gated — job: **feedback**. Never a scale-bounce.

**What it is:** Replace the three `hx-confirm` → `window.confirm()` sites with a native `<dialog>`
driven by an `htmx:confirm` listener calling `event.detail.issueRequest()`, styled from existing
tokens with `::backdrop { background: color-mix(in oklab, var(--fg) 40%, transparent) }`.

**Why it matters:** These are the three highest-consequence interactions in the product and **the only
three moments the console's own visual language does not apply at all**. In dark mode it is the one
place a bright light-themed OS dialog flashes against the console. It also rescues genuinely good copy
currently trapped in unstyled chrome: *"On-disk data at `var/arxmcp/notebooks/{slug}/` is NOT deleted —
run `tools/notebook_purge.py` to wipe the disk."*

**Sources:**
- Art-direction: C8 `in-language-destructive-confirm`
- Visual scout: **HIGH-3**
- Library scout: **CAND-5** — `<dialog>` is the oldest/safest candidate in its brief (Baseline Widely Available ~Sept 2024), 0 bytes CSS + ~10-15 lines inline JS already covered by `script-src 'self' 'unsafe-inline'`; **top pick of that brief**
- Current-state critic: M1 (destructive half) + §6 CSP constraint record

**Closest arXMCP analog today:** `index.html:111`, `notebook_detail.html:86` and `:350`;
`app.css:108` (`button.danger`), `:213` (its focus ring), `:315` (the in-flight ring compensation).

**Sketch:** Affirmative label is the destructive verb ("Delete notebook"), never "OK". `<dialog>`
provides keyboard + focus-trap semantics for free.

**Open questions:** **DECLARED COST — this is the one candidate in the top tier that adds JS surface.**
CSP-legal today with no CSP edit, but **any new JS widens the still-open UI security audit
`chris-dare-dev/arXMCP#9`** and must be flagged, not slipped in. If that cost is judged too high this
run, **park it — do not shrink it to a CSS-only fake** that loses the focus-trap semantics.

---

### UPL-12 — In-flight feedback that targets the region, not just the button

**Category:** Interaction · **Size:** S · **Evidence triangulation:** 3 briefs (visual ✓, current-state ✓, library ✓)
**Motion primitives:** `[MOT-8 shimmer-skeleton]` on `#discover-results` — job: **causality**; reduced-motion gated following the existing `spin`/`badge-flash` pattern verbatim.

**What it is:** `hx-indicator` is set on **ZERO** of the 9 htmx elements. Add region-targeted in-flight
state: a `.card:has(form.htmx-request)` / `tr:has(button.htmx-request)` treatment (0 bytes, pure CSS)
plus a placeholder row or a "Discover started…" line rendered into `#discover-results` the moment the
request fires.

**Why it matters:** **Discover** (live arXiv Atom round-trip) and **Ingest** (spawns a background
subprocess) are the two operations with real latency, and both get exactly the same feedback as an
instant local PATCH: one 80×32px button dimming to 60% opacity. An operator on a slow network cannot
distinguish "still searching" from "my click didn't register."

**Sources:**
- Visual scout: **HIGH-2**
- Current-state critic: M1 — `grep hx-indicator` → zero matches repo-wide
- Library scout: **CAND-2** `:has()` (0 bytes, Widely Available ~June 2026) — the row-level cue also disambiguates *which* of six identical 77×32 Remove buttons is in flight; **CAND-10** `loading-states` htmx extension (0BSD, 5,551 B src) is the fallback **only if a job appears that `:has()` genuinely cannot express** (path-scoped states across different targets in one request)

**Closest arXMCP analog today:** `app.css:293-333` (`.htmx-request` opacity + `::after` spinner) —
correct, just scoped to the requesting element only.

**Sketch:** Prefer `:has()` first (0 bytes, no new audit surface). Only reach for the extension if
`:has()` provably can't do the job.

**Open questions:** `:has()` crossed Widely-Available only ~2 months before this run — worth a
staleness re-check, though it degrades to "no extra highlight."

---

### UPL-13 — Consolidate the 12 `aria-live` regions and stop the 2s poll re-announcing

**Category:** Accessibility · **Size:** S · **Evidence triangulation:** 2 briefs (visual ✓, current-state ✓; library ✓ for the mechanism — effectively 3)
**Motion primitives:** none

**What it is:** Twelve `aria-live="polite"` regions on one rendered page (11 in `notebook_detail.html`
+ 1 inherited from `base.html`), **six of them empty `<pre class="error">` at first paint**. The 2s
ingest poll re-announces its region on **every tick regardless of whether the status text changed**.
Fix: only emit announcement-worthy content on a genuine `data-status` delta (pure server-side logic,
zero new JS), and migrate the 2–3 single-value status swaps to `<output>` (implicit `role="status"` +
implicit `aria-live="polite"`, 0 bytes).

**Why it matters:** A screen-reader operator mid-ingest currently gets an announcement roughly **every
2 seconds for the entire run's duration**. `ui-attractive-polish-m1` shipped live-region *presence* as
its acceptance criterion; throttling was never named as a follow-up.

**Sources:**
- Visual scout: MEDIUM-2 (count independently re-derived by grep, matching the manifest exactly)
- Current-state critic: M1 (polling half) + §6 conflict list, with per-line citations
- Library scout: CAND-14 `<output>` — removes the manual attribute and with it the exact drift failure mode `notebook_detail.html:16-19`'s own comment warns about ("the swap REPLACES this element, so the returned fragment MUST also carry the attribute")

**Closest arXMCP analog today:** `notebook_detail.html:20,46,109,143,174,176,217,247,271,290,322` + `base.html:89`.

**Sketch:** Server-side delta check is **audit-neutral** — zero new JS. Scope `<output>` to
`#display-name-block` / `#topic-block` / `#ingest-status` only; **not** the papers `<tbody>` (a list)
and **not** `pre.error` (an alert region).

**Open questions:** **Sequencing interaction with UPL-1** — moving forms inside `<details>` changes
which live regions are in the accessibility tree at all. These two must be sequenced together.

---

### UPL-14 — Give `#ingest-status` a settle signal

**Category:** Motion · **Size:** XS · **Evidence triangulation:** 1 brief (visual ✓)
**Motion primitives:** shipped `badge-flash` extended by ONE selector — job: **feedback**, on genuine state change only (I-3: never on a bare poll tick).

**What it is:** Add `#ingest-status.htmx-settling` to the already-shipped, already-gated `badge-flash`
rule so an ingest status update reads as a refresh in peripheral vision, the way the footer badge
already does.

**Sources:** Visual scout MEDIUM-4 — `badge-flash` is scoped to `.status-badge.htmx-settling` only.

**Closest arXMCP analog today:** `app.css:344-351`.

**Sketch:** One-selector addition to an existing correct pattern. **No new motion infrastructure.**

**Open questions:** Must fire only on a real status change — pairs with UPL-13's delta check, or it
becomes a light flashing every 2 seconds, which violates I-3 directly.

---

### UPL-15 — Row hover state + focus-revealed trailing actions

**Category:** Interaction · **Size:** S · **Evidence triangulation:** 2 briefs (visual ✓, inspiration ✓)
**Motion primitives:** `[MOT-24 hover-color-shift]` ≤100ms — job: **orientation**. Plus a **proposed new token `[MOT-52 hover-reveal-actions]`** (inspiration scout; **not** written into the hash-tracked shared canon — flagged for human promotion).

**What it is:** `tr:hover { background: color-mix(in oklab, var(--card-bg) 95%, var(--fg)) }` on both
tables (the `color-mix` idiom already at `app.css:106`), plus optionally revealing the destructive
Remove action on `tr:hover, tr:focus-within`.

**Why it matters:** The only `:hover` rule in all 371 lines is `button:hover`. Moving down either table
gives zero positional feedback before clicking a destructive control. Six always-visible red Remove
buttons also fight the "calm at repeat use" invariant.

**Sources:** Visual scout LOW-1 · Inspiration scout **P10** (Primer ActionList trailing-action anatomy,
https://primer.style/components/action-list/, + Linear's row-hover disclosure).

**Sketch:** `tr` in D-1 becomes the unit of interaction, so this composes with UPL-2 rather than
duplicating it.

**Open questions:** **HARD a11y REQUIREMENT, non-negotiable:** `:focus-within` MUST accompany `:hover`.
A hover-only reveal makes Remove invisible to keyboard-only and switch-device operators — **a
regression relative to today's always-visible buttons, and a Phase-3 BLOCKER condition** if proposed
without the focus-within twin.

---

### UPL-16 — Container-query the form layout; stop 1251px inputs for 12-char values

**Category:** Layout · **Size:** S · **Evidence triangulation:** 2 briefs (visual ✓, library ✓)
**Motion primitives:** none

**What it is:** `container-type: inline-size` on the card/section, plus a
`@container (min-width: 480px)` two-column form grid and a `max-width` on short-content fields (slug,
paper ID), leaving genuinely long fields (arXiv URL, topic) full-width.

**Why it matters:** A slug field expecting ~20 characters renders at **1251px** — roughly 60× its
expected content. Part of why the page reads as un-tuned form-generator output.

**Sources:** Visual scout MEDIUM-3 · Library scout **CAND-1** `@container` (0 bytes, Widely Available
~Aug 2025) — the viewport is already `clamp(640px, 92vw, 1400px)`, so a `@media` breakpoint literally
**cannot** see the card's rendered width the way `@container` can.

**Closest arXMCP analog today:** `app.css:74-84` (`width:100%` on every text input), `:37` (body clamp).

**Open questions:** Interacts with UPL-2 (there may be no card left to be the container) — sequence
after, and re-target the container to the ledger section.

---

### UPL-17 — Vendor `response-targets`; delete 6 copies of hand-duplicated inline JS

**Category:** Vendor-able single-file drop · **Size:** S · **Evidence triangulation:** 1 brief (library ✓)
**Motion primitives:** none

**What it is:** The identical inline one-liner
`hx-on::htmx:response-error="…JSON.parse(t).detail||t…"` is hand-duplicated **six times**
(`notebook_detail.html:37,124,170,208,267` + `index.html:27`). The htmx `response-targets` extension
replaces every one with declarative `hx-target-4xx` / `hx-target-5xx` attributes.

**Why it matters:** **This is the safest kind of dependency — one that DELETES existing code rather
than adding an affordance.** Six copies of a hand-rolled `JSON.parse(...).detail||t` fallback chain is
six chances to drift.

**Sources:** Library scout **CAND-11** — 0BSD (`src/response-targets/LICENSE`, verified live
2026-08-03), 3,740 B source / ~1.3 KB gz estimated. **Top htmx-extension pick of that brief.**

**Sketch:** Same vendoring lane as `htmx.min.js` + `json-enc.js`; `script-src 'self'` already covers a
same-origin file — **no CSP change**. Error text still flows through `textContent`, not `innerHTML`,
so no new XSS surface.

**Open questions:** License provenance must cite `src/<ext>/LICENSE`, **not** the repo root or
`package.json` — the htmx-extensions repo has no root LICENSE and npm reports `license: null`
(verified live). New JS file = new UI security-audit surface for `arXMCP#9`.

---

### UPL-18 — Vendor idiomorph for continuity-preserving swaps

**Category:** Vendor-able single-file drop · **Size:** M · **Evidence triangulation:** 1 brief (library ✓)
**Motion primitives:** unlocks a genuinely new primitive — **continuity-preserving attribute transitions across an htmx swap** — job: **continuity**.

**What it is:** `hx-swap="morph"` diffs incoming HTML against the live DOM and patches only what
changed, so the DOM node persists across a swap. A freshly-inserted node has no "before" state to
transition FROM; a morphed node does.

**Why it matters:** It explains *why* `app.css:344-370` needs hand-authored keyframes at all — they
exist to make a full node replacement feel like a transition. Morph makes real CSS transitions possible
on in-place updates (rename, topic).

**Sources:** Library scout **CAND-13** — 0BSD (same license and author as the already-trusted
`htmx.min.js`), 10,153 B minified / ~3.5 KB gz estimated. **Top vendor-JS pick of that brief.**

**Open questions:** Morph may not apply `.htmx-swapping`/`.htmx-settling` the same way `outerHTML` does
— migrating existing targets requires re-verifying `row-fade-out` and `badge-flash` still fire. Flag as
a Phase-2 regression-test item. New JS = `arXMCP#9` surface. **Lower priority than UPL-17** (adds a
capability rather than deleting code).

---

### UPL-19 — Cross-document View Transitions + link preload

**Category:** Motion · **Size:** S · **Evidence triangulation:** 1 brief (library ✓)
**Motion primitives:** `[MOT-36 route-fade]` / `[MOT-14 shared-element-transition]` — job: **continuity**.

**What it is:** A one-line `@view-transition { navigation: auto; }` opts every same-origin navigation
into the browser's crossfade, reusing the SAME 200ms `::view-transition-*` cap already declared at
`app.css:352-355`. Optionally pair with the `preload` htmx extension on the index's "Open" link.

**Why it matters:** `globalViewTransitions` covers htmx fragment swaps only; clicking "Open"
(`index.html:94`, a bare `<a>`) gets an instant unstyled document swap. A preloaded, transitioned
navigation is the closest arXMCP gets to SPA-smooth without an SPA.

**Sources:** Library scout **CAND-8** (0 bytes; **NOT Baseline** — Chromium + Safari only, Firefox has
not shipped it; the at-rule is a genuine no-op in unsupported browsers, so **no `@supports` gate is
even needed**) + **CAND-12** `preload` (0BSD, 14,099 B src / ~4.5 KB gz est. — nearly 3× heavier than
`response-targets`; rank below it).

**Open questions:** The rule MUST live inside the existing `prefers-reduced-motion: no-preference`
block or it becomes a second sticky reduced-motion gap. `preload="mousedown"` fires a real GET before
the user commits — negligible on a loopback idempotent GET, but **document it for the audit rather than
let it be discovered**.

---

### UPL-20 — Surface `notebook_kind` on the index; densify the notebooks list

**Category:** Data viz · **Size:** S · **Evidence triangulation:** 1 brief (current-state ✓; inspiration ✓ for the pattern — effectively 2)
**Motion primitives:** none

**What it is:** `index.html` references `notebook_kind` **zero** times, so an operator must open every
notebook to learn whether it is `arxiv` or `textbook` — two kinds with different available actions.
Add ONE chip per row reusing the existing `.status-badge` vocabulary, and surface `parse_status` /
last-indexed inline so the list alone answers "is this notebook usable."

**Sources:** Current-state critic **M6** (with a correction to the overlay's stale count: the live
detail page has exactly 1 reference, not 3) · Inspiration scout **P2** (Vercel's redesigned deployments
list: "a denser layout… environments grouped with statuses" — https://vercel.com/changelog/redesigned-deployments-list) and **P4** (Primer State label's closed colour enum — https://primer.style/components/state-label/).

**Open questions:** **BAN-7 risk.** One chip per row, reusing the existing four-state vocabulary, never
a second chip. The art-direction brief parks this as a *feature* affordance rather than a
direction-defining move.

---

### UPL-21 — Author the four empty states (cause + one action)

**Category:** Layout · **Size:** S · **Evidence triangulation:** 1 brief (inspiration ✓; art-direction ✓ via surface-map row 6 — effectively 2)
**Motion primitives:** none — canon: keep static per the calm-at-repeat-use invariant.

**What it is:** The four `.empty` states are italic centred grey text with zero action affordance.
Each already carries a *cause* in its copy ("No papers yet. Add one above."); the missing half is
turning the implied action into an actual control so it is one click, not a scroll-and-find.

**Sources:** Inspiration scout **P3** — Primer Blankslate's anatomy: visual, heading, description,
`PrimaryAction` (https://primer.style/components/blankslate/). Art-direction surface map row 6: authored
**at S-2 register** — cause + one action, not a cinematic 404.

**Closest arXMCP analog today:** `app.css:64` (`.card .empty`); call sites `index.html:86`,
`notebook_detail.html:177,296,303`.

**Open questions:** Primer's Blankslate leads with an **icon**. arXMCP has **zero icons** and the
frame calls that an asset (BAN-3 is the most likely "make it prettier" regression). Adopt the anatomy
**without** the icon, or accept the first icon in the product deliberately — this needs an explicit
decision, not a drift.

---

### UPL-22 — Fix the reduced-motion preference listener

**Category:** Accessibility · **Size:** XS · **Evidence triangulation:** 1 brief (library ✓)
**Motion primitives:** none — makes existing shipped motion correctly responsive.

**What it is:** `base.html:38-45` reads `matchMedia('(prefers-reduced-motion: reduce)')` **once** inside
`DOMContentLoaded` and never registers a `change` listener, so an operator who flips their OS
reduced-motion setting mid-session keeps view transitions until a full page reload. The CSS gates
(`app.css:223`, `:317`, `:344`) react live because `@media` re-evaluates continuously; only this one JS
read is stuck.

**Sources:** Library scout **CAND-15** — ~4 lines of inline JS, delta to an existing block, no new file,
already covered by the CSP clause in use.

**Open questions:** none. This is a strict bug fix and the cheapest genuine a11y win in the catalog.

---

### UPL-23 — `/` to focus the primary input (NOT a command palette)

**Category:** Interaction · **Size:** S · **Evidence triangulation:** 1 brief (inspiration ✓; library ✓ scoping it down — effectively 2)
**Motion primitives:** none in the narrow form.

**What it is:** A ~10-line vanilla `keydown` listener: `/` (when focus is not already in a text input)
jumps focus to the page's primary input. **Explicitly not** a searchable multi-command palette.

**Why it matters:** There are **zero** `keydown`/`accesskey` handlers anywhere in the product, and the
single operator is exactly Raycast's target user — someone in this console repeatedly, every day.

**Sources:** Inspiration scout **P8** (Raycast/Linear/Vercel/GitHub ubiquity) · Library scout §6
scoping it correctly: *"a full command-palette library would be scope creep against the quiet-instrument
thesis; the named gap is a ONE-element focus jump"* · Art-direction parking lot: the narrow form is a
legitimate D-1/D-2 candidate and the cheapest way to get REF-9's keyboard-first trait.

**Open questions:** New JS = `arXMCP#9` surface. Needs a visible discoverability hint — a hidden
keyboard affordance is an a11y regression, not a feature. The **full** `/` command line is D-3's
defining move and is **out of scope** unless the direction changes.

---

### UPL-24 — Ingest/operability state history strip

**Category:** Data viz · **Size:** M · **Evidence triangulation:** 1 brief (inspiration ✓)
**Motion primitives:** `[MOT-26 tooltip-fade]` on per-tick hover — job: **orientation**, reduced-motion gated.

**What it is:** A horizontal strip of small coloured ticks (reusing the four `.status-badge--*` colours
verbatim, no new tokens) showing the last N ingest runs, additive to — not replacing — the current
single-state badge.

**Why it matters:** Both status surfaces throw away everything but the latest poll result. Grafana's
state-timeline and Datadog's monitor history both treat *recent state over time* as the primary
investigative signal.

**Sources:** Inspiration scout **P7** (https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/state-timeline/ · https://www.datadoghq.com/blog/monitor-alert-status/).

**Open questions:** **BAN-6 risk** — this is the closest thing in the catalog to a chart, and the frame
binds: threshold, annotation, and a stated "so what," or it does not ship. Also: **does the server even
retain run history?** If not, this is a backend feature wearing a frontend candidate's clothes and
belongs in a different pipeline. Requires verification before ranking.

---

### UPL-25 — Identity strip on the ar5iv preview surface

**Category:** Layout · **Size:** S · **Evidence triangulation:** 1 brief (inspiration ✓; current-state ✓ *narrowing* it — effectively 2)
**Motion primitives:** none — `position: sticky` is layout, not animation.

**What it is:** Inject a minimal top strip carrying "← {slug}" + the `paper_id` in `--mono` above the
served ar5iv HTML.

**Sources:** Inspiration scout **P9** (arXiv's HTML rollout keeps identity context adjacent to the bare
reading surface) · Current-state critic **L1**, which **corrects the overlay**: the Preview link opens
with `target="_blank" rel="noopener"`, so closing the tab IS the way back — **the gap is brand
discontinuity only, not a navigational dead-end.**

**Open questions:** **This surface was NOT audited this run** — no paper in the deployment has stored
ar5iv HTML, so the route correctly 404s. Needs a follow-up pass with an uploaded fixture before anyone
restyles it. Any injection must respect `CONTENT_SECURITY_POLICY_PREVIEW`, a deliberate security
decision that stays as-is. Also verify whether the same-origin favicon already supplies the identity
cue, in which case this may be a non-finding.

---

### UPL-26 — First-ever inline validation state (`:user-invalid`)

**Category:** Interaction · **Size:** XS · **Evidence triangulation:** 1 brief (library ✓)
**Motion primitives:** none recommended — the house thesis favours static colour-as-signal over motion-as-signal where either serves. (`[MOT-45 validation-shake]` is available but **not** recommended.)

**What it is:** `app.css` has **zero validation-state styling** — not even an `:invalid` rule — while
seven forms carry native constraint attributes (`required`, `pattern="[a-z][a-z0-9-]{2,30}"` on the
slug at `index.html:31-32`, `type="url"` on the paste field). `:user-invalid` fires only **after** the
user has interacted (unlike `:invalid`, which fires on page load for an empty required field and is
famously the wrong default).

**Why it matters:** The slug-pattern field gets its first inline cue instead of relying entirely on a
server 422 round-tripped through `hx-on::htmx:response-error` into a `<pre>`.

**Sources:** Library scout **CAND-3** — 0 bytes, Widely Available ~May 2026.

**Open questions:** Genuinely fresh baseline (~3 months at time of writing) — worth a staleness note.

---

## 5. Cross-cutting tensions

1. **"Propose new libraries" vs. §4.7.** Library + inspiration scouts both land on "zero new
   libraries." **Resolution:** answer the user's question directly rather than refusing it — the
   2022–2026 CSS platform (`@container`, `:has()`, `:user-invalid`, `<dialog>`, `popover` + anchor
   positioning, `field-sizing`, cross-doc View Transitions, `light-dark()`, `text-wrap: balance`)
   delivers at **0 bytes** most of what the named libraries exist to provide, and three 0BSD
   single-file htmx-family drops (`response-targets`, `idiomorph`, `preload`) fit the proven vendoring
   lane. The final report must carry the explicit "why not Framer Motion / shadcn / Tailwind / GSAP /
   cmdk / Sonner" table so the user gets an answer, not a rule.
2. **Elevation: hover-lift vs. hairline-only.** Visual scout HIGH-1 proposes the product's first
   `box-shadow`; the frame bans it (BAN-8; hairline is D-1's sole elevation method) and deletes the
   card entirely. **Resolution: frame wins.** The job — differentiate primary from secondary — is
   served by UPL-2 + UPL-5.
3. **Timestamps: humanize or keep metered.** Current-state M5 flags raw ISO timestamps but attaches its
   own calibration caveat; invariant **I-2** wants *metered* facts and "3 days ago" hides exactly the
   precision the thesis is built on. **Resolution: keep the exact value visible; add relative context
   only as a `title`/secondary. Never replace a metered fact with a fuzzy one.** GitHub's
   `<relative-time>` is the known pattern but is a vendored web component and must be weighed against
   I-4 first. → parking lot.
4. **Icons: Blankslate anatomy vs. BAN-3.** UPL-21's source pattern leads with an icon; the product has
   zero icons and the frame calls that an asset. **Resolution: adopt the anatomy without the icon
   unless the first icon is a deliberate, recorded decision.**
5. **Where the cookie-cutter score can and cannot gate.** The anti-pattern half is auditable from
   measured geometry; **the positive DQS half cannot gate without real screenshots.** Any Phase-3
   scoring of a *projected* state must say so.

## 6. Already considered + rejected

- **Framer Motion / GSAP / anime.js / Motion One** — npm-installable or CDN-requiring; `script-src 'self' 'unsafe-inline'` allow-lists no external origin. Also **no motion gap exists** that native CSS transitions + htmx swap hooks can't serve on an S-2 surface; the house thesis explicitly says "never a JS animation engine."
- **Tailwind / shadcn / Radix / React / Vue / Svelte / TanStack** — require a build chain that does not exist in the deploy path. The server ships as a single Python wheel with `server/frontend/` source-served.
- **`cmdk` / a full command palette** — npm + React, and the wrong solve: the named gap is a one-element focus jump (UPL-23), not a searchable command surface.
- **Sonner / toast libraries** — npm, plus a thesis mismatch: existing inline `aria-live` + `pre.error` already serve "did my action work" next to the control that triggered it; a floating toast stack is a new UI region BAN-7's reasoning warns against.
- **Lucide / Phosphor icon sets** — no icon gap was identified; text-label-only buttons fit the thesis. See tension 4.
- **`morphdom`** — rejected in favour of idiomorph: `morphdom-swap.js` is a 596-byte wrapper requiring a *second* vendored core file; idiomorph is one self-contained 0BSD file for the same job.
- **`animation-timeline: scroll()` / `view()`** — Firefox-blocked, and BAN-12 bans scroll-driven spectacle on S-2 wholesale. One narrow legitimate fit (a reading-progress indicator on the ar5iv preview) is parked behind the Firefox gap.
- **`@property`, `interpolate-size`** — parked; too new or too marginal to cite a stable baseline.
- **Self-hosted `--mono` webfont (JetBrains Mono)** — full charset measures **92,380 B**; no subsetted artifact was produced, so no honest weight can be cited. The only motivating gap (`tabular-nums` consistency) is already served by `font-variant-numeric`, which every system mono in the stack honours. **Rejected.**
- **D-2's vendored serif `woff2`** — real, but changes the product's asset story (zero font files today). Deferred with D-2 itself; **the byte weight must be measured, not assumed, before D-2 is ever chosen.**
- **D-3's `/` command line, `MOT-18` number-tween, `MOT-3` stagger-reveal on the papers table** — rejected by the frame (direction not chosen; motion-jobs test failed; AP-3).
- **Stripe's 3-column API-reference layout, Observable's reactive-cell model, any multi-user/account pattern, Semantic Scholar's citation-graph viz** — no analogous surface exists; the last is flagged for a future `cite_neighbors` UI brief, not speculative UI for a route that doesn't exist.
- **htmx upgrade** — 2.0.10 IS the current latest published version (verified live). Do not propose one.

## 7. Motion-vocabulary index

| Primitive | Job | Candidates |
|---|---|---|
| `[MOT-15 accordion-expand]` | feedback | UPL-1 |
| `[MOT-4 scale-in]` | feedback | UPL-11 |
| `[MOT-8 shimmer-skeleton]` | causality | UPL-12 |
| `[MOT-1 fade-in]` | causality | UPL-9 |
| `badge-flash` (shipped) | feedback | UPL-5, UPL-14 |
| `[MOT-24 hover-color-shift]` | orientation | UPL-15 |
| `[MOT-52 hover-reveal-actions]` **(proposed, not canon)** | orientation | UPL-15 |
| `[MOT-26 tooltip-fade]` | orientation | UPL-24 |
| `[MOT-36 route-fade]` / `[MOT-14 shared-element-transition]` | continuity | UPL-19 |
| `[MOT-28 spinner]` (shipped keyframe reused) | feedback | UPL-10 |
| continuity-preserving swap transitions **(new, unlocked by idiomorph)** | continuity | UPL-18 |
| **REJECTED:** `[MOT-18 number-tween]`, `[MOT-3 stagger-reveal]`, `[MOT-45 validation-shake]`, all `EXP-*`, AP-1/2/3/5 | — | — |
