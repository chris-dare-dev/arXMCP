---
milestone_id: "ui-uplift-m8"
researcher_role: "general"
external_writes_required:
  - "git push origin main"
sources:
  - url: "https://api.webstatus.dev/v1/features/has"
    sha256: "9690e42a9414370eb9833d26da3e20ada9c490b71ae37cb4d0026139d81baeb4"
    takeaway: ":has() is Baseline WIDELY available — low 2023-12-19, high 2026-06-19 — so it crossed the 30-month bar seven weeks before this milestone and clears CLAUDE.md 4.7."
  - url: "https://api.webstatus.dev/v1/features/subgrid"
    sha256: "06165562e775e4b2b7d6ff8c4b83ab5df002625119ef01b5efbb1181bbb3e12e"
    takeaway: "subgrid is Baseline WIDELY available — low 2023-09-15, high 2026-03-15 — but Firefox-Android stable WPT is 0.63, the weakest engine score of any feature checked."
  - url: "https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html"
    sha256: "9d5323cbdc7c18ca307b6e3d93c42442f875295a9c33ded58a5ace868ca1ab15"
    takeaway: "SC 1.4.11's 3:1 bar binds only what is 'required to understand the content'; a purely aesthetic divider is exempt — which is precisely why deleting .card converts the rule ladder from exempt decoration into a gated graphical object."
  - url: "https://www.scottohara.me/blog/2021/07/16/section.html"
    sha256: "de5e306de92832d1d0786f10c12ae1398f6a915f7a729c513b0111c7e230da14"
    takeaway: "A <section> exposes its implicit region landmark ONLY with an accessible name; unnamed sections are semantically div-equivalent, and over-populating a page with regions 'will reduce their ability to help users find the most important parts'."
  - url: "https://practicaltypography.com/rules-and-borders.html"
    sha256: "d3de65796e77ff102d9281d2455d060a53d193ee36cafda0e154ad232adaf7d0"
    takeaway: "Butterick: rules and borders 'are best used sparingly', border thickness belongs between half a point and one point, and increasing the space above and below the text is the move to 'try first'."
  - url: "https://www.nngroup.com/articles/common-region/"
    sha256: "51fb73f4290559a7df143a26e1d4951b9b874b504d69f49a2f31f2c9aaa51052"
    takeaway: "Common region is 'a strong visual cue that can overpower other grouping principles such as proximity'; NN/g nonetheless holds that 'using whitespace alone to create clear groupings reduces the visual complexity of a design'."
injection_attempts: 0
---

# Research brief (general) — ui-uplift-m8

Role scope: external context + the external-writes list. Codebase mapping is
brief-1's (`explore`). Repo facts appear here only where they are load-bearing
for an external claim or where they contradict the milestone brief.

---

## 0. Read this first — two traps

### 0.1 The `UPL-2` decoy is REAL, and it depends on which grep you run

`UPL-2` names **two unrelated candidates** in this repo:

| | 2026q3 run (this milestone) | May-2026 run (the decoy) |
|---|---|---|
| Meaning | Retire `.card`; graded hairline rule ladder | `:focus-visible` outline ring |
| Home | `plans/ui-uplift/roadmap.yaml:331` | `.claude/roadmap/ui-attractive-polish-roadmap.md:466` |
| Status | planned (this milestone) | **SHIPPED** in `ui-attractive-polish-m1` |
| Guarded by | nothing yet | `tests/test_ui_a11y_baselines.py:8,90,119` |

Measured in this checkout on 2026-08-04:

- `grep -rn "UPL-2" .` (GNU/BSD grep, from repo root) returns
  `plans/ui-uplift/roadmap.yaml` **first**. The prompt's ordering warning does
  **not** reproduce under plain `grep`.
- `rg -n "UPL-2"` (ripgrep — i.e. what the **Grep tool** uses) returns
  `tests/test_ui_m4_in_place_add_paper.py` first, and the whole first page is
  May-2026 material. **Under ripgrep the decoy does outrank the real content.**

So: the warning stands for the tool the implementer will actually reach for.
The sharpest form of the trap is `tests/test_ui_a11y_baselines.py`, whose module
docstring reads ``**UPL-2** ``:focus-visible`` outline-ring rules`` — a *passing*
test that documents UPL-2 as something else entirely. Anchor on
`plans/ui-uplift/roadmap.yaml:331` and nothing else.

### 0.2 The roadmap summary DID drop authored values — failure shape (a) recurs

The discovery authored the ladder as **three named tokens with a stated
grading**. `plans/ui-uplift/roadmap.yaml`'s m8 summary and its five acceptance
criteria carry **neither the names nor the grading**. Verbatim source, three
files in agreement:

- `discover/art-direction-scout-brief.md:163-164` — *"a **graded hairline rule
  ladder** — section rule (full weight), row rule (60%), meta rule (dotted)"*
- `discover/art-direction-scout-brief.md:176-177` — *"`--rule-section` /
  `--rule-row` / `--rule-meta`, three weights, horizontal only. No vertical
  edges anywhere."*
- `artifacts/synthesis.md:234` — *"three weights of horizontal rule
  (`--rule-section` full / `--rule-row` ~60% / `--rule-meta` dotted)"*
- `artifacts/synthesis.md:236` — *"One `.lede` treatment marks the single focal
  region per view."*

Four things exist in discovery and are absent from the roadmap item:

1. the three token **names** `--rule-section` / `--rule-row` / `--rule-meta`;
2. the **grading** full / ~60% / dotted — i.e. the word *graded* in the title
   has no referent left in the brief;
3. the `.lede` single-focal-region treatment (synthesis.md:236);
4. the sketch constraint *"New rule tokens **extend the `:root` block** … never
   a parallel token set"* (synthesis.md:252-253) — which, post-m7, means
   `tokens.css`, not `app.css`.

This is the same drop-shape as m7's `clamp()` values and m10's finding-H3 rules.
**Treat the four items above as authored requirements, not suggestions.**

### 0.3 What the source does NOT author

No px value, no alpha, no colour is authored for any of the three rungs
anywhere in the 5,478 lines of discovery. `60%` is stated once, unqualified, in
two files. **It is ambiguous between weight (thickness) and tone
(lightness/alpha), and the two readings have opposite consequences:**

- **Thickness reading** — `0.6px` against a `1px` section rule. Sub-pixel
  borders round unpredictably per device-pixel-ratio; at DPR 1 a 0.6px border
  commonly renders as 1px (indistinguishable from the section rule) or drops
  out entirely. Butterick's own floor is "half a point to one point" and he
  warns that finer weights are *"too fine to reproduce well on … a computer
  screen"* (source 5). A thickness ladder of 1px / 0.6px / dotted therefore has
  **two rungs the operator may not be able to tell apart**.
- **Tone reading** — a lighter colour at the same 1px. This is the readable
  option, and it is the one that collides with SC 1.4.11 (§3 below).

The implementer must **decide and record which**, because the discovery did not.
Recommended: tone, with thickness held at 1px throughout.

---

## External sources

Six sources, all sha256-pinned in the frontmatter. Findings, in the order the
task's questions were asked.

### 1. What replaces a card, as a discipline

The design literature is unusually direct here and it does **not** say "nothing
replaces it."

**Common region is the strongest grouping cue there is, and deleting it is a
real loss that something must absorb.** NN/g: common region is *"a strong visual
cue that can overpower other grouping principles such as proximity or
similarity"* — their demonstration shows a boundary re-grouping two circles
*"regardless of their proximity"* (source 6). A `.card` is a common region. Nine
of them are what the operator currently uses to know where one job ends and the
next begins.

**The named replacement is whitespace, not a thinner border.** Same source:
*"using whitespace alone to create clear groupings reduces the visual complexity
of a design"*, and in many cases *"proximity is enough to signal grouping."*
Butterick reaches the same conclusion from the typographic side: rules and
borders *"are best used sparingly. Ask yourself: do you really need a rule or
border to make a visual distinction?"*, and you can *"usually get equally good
results by increasing the space above and below the text. Try that first"*
(source 5).

**The load-bearing consequence for this milestone:** a graded rule ladder is
*not* the substitute for common region — **vertical rhythm is**, and the ladder
is the secondary cue that disambiguates rank. If m8 deletes
`.card { padding: 1rem 1.25rem; margin-bottom: 1rem }` and replaces it with
three hairlines while leaving the spacing at 1rem, the result is the
"spreadsheet" failure the art-direction scout itself predicts
(`art-direction-scout-brief.md:193-194`: *"a ruled sheet with timid type
contrast reads as a spreadsheet"*). **The spacing scale is in scope even though
no acceptance criterion mentions it.** Expect the section gap to roughly double
(≈1rem → ≈2–2.5rem) where a rule replaces a box edge.

**Rule weight, concretely.** Butterick's usable range is half a point to one
point ≈ 0.67px–1.33px. That is the entire budget for a three-rung *thickness*
ladder, which is the second independent reason to grade by tone instead.

**The ledger/sheet idiom is legitimate for this surface.** The console is a
loopback single-operator tool over a dense record (a notebook detail page is a
table of up to hundreds of papers plus six job forms), not a marketing page.
Ruled records — ledgers, lab notebooks, bibliographies — are the historical
information-design answer to exactly that shape, and the art direction's own
seed cites density-as-authored (`art-direction-scout-brief.md:405`, REF-5). No
external source contradicts the idiom choice; the sources constrain *how much
rule* it needs, not *whether*.

### 2. Radius 0 on structure, 4px on controls — recognised, or bespoke?

**Split verdict. Half is a recognised convention; the semantic claim is
bespoke.**

- **Square structural containers in dense enterprise tooling is an established
  convention.** IBM Carbon is the canonical example — corner radius at or near
  0 across the system, with IBM's design language advising squared corners
  where they *"reflect the real form of the metaphor"* rather than forcing
  roundness. Nothing about zero-radius panels will read as a bug.
- **"Radius *means* interactive" is a bespoke thesis.** I found no design system
  that states radius as a semantic encoding of interactivity. Material 3's shape
  guidance points the other way: shape is treated as an expressive scale (0dp →
  full) that can differentiate components — e.g. a pill primary against a
  rectangular secondary — while explicitly cautioning against assigning a
  single fixed meaning to a given shape. (M3's shape pages are
  client-rendered; WebFetch returned no body text, so this is characterised
  from search-surfaced summaries rather than quoted, and is **not** in the
  pinned source list. Do not cite it as verbatim M3 text.)

**What it costs — and this is the concrete finding.** "4px surviving *only* on
interactive controls" is falsified by the shipped stylesheet today. Every
`border-radius` in `server/frontend/static/app.css`:

| line | selector | interactive? |
|---|---|---|
| 53 | `.card` — 6px | structure — deleted by m8 |
| 88 | `input[type=text\|url\|file]` — 4px | yes |
| 111 | `textarea` — 4px | yes |
| 120 | `button, .button` — 4px | yes |
| 313 | `pre.error` — 4px | **no — a feedback surface** |
| 347 | `.status-badge` — 4px | **no — a readout** |
| 402 | `.skip-link` — 4px | yes |
| 419 | `[tabindex]:focus-visible` — 4px | yes (ring geometry) |
| 546 | spinner — 50% | **no — motion decoration** |

Three of eight are not controls. Worse, **the authored direction itself grants
one of them an exemption**: D-1's banned-traits list is *"no rounded pills
beyond the single operability badge"* (`art-direction-scout-brief.md:186`) —
i.e. `.status-badge` keeps its radius **by design**. A rule with a named
exception is not a semantic encoding; it is a convention with an exception, and
it must be written down as one. The honest framing to ship: *radius marks the
control layer; the operability badge and the spinner are documented
exceptions.* `pre.error` is the one genuinely undecided case — it is a
structural feedback panel and squaring it is the consistent choice.

Read alongside §1: because the geometry claim survives only with exceptions,
**it cannot be the primary structure-vs-control signal.** Rhythm and the rule
ladder carry that; geometry reinforces it.

### 3. Accessibility — SC 1.4.11, and the exemption that cuts both ways

**The discovery's a11y argument is correct, and the primary source states the
exact mechanism.** SC 1.4.11 requires 3:1 for *User Interface Components* and
*Graphical Objects*, and its Understanding document carves out anything
*"for aesthetic purposes that does not require the user to see or understand it
to understand the content"* (source 3). That is why a card border at 1.34:1 was
survivable and a *structural* rule at the same value is not: deleting the
container moves the rule from the exempt column into the gated one.

**But AC #4 is stale as written, and this matters for scoping.** AC #4 says
*"the rule token clears SC 1.4.11's 3:1 non-text bar (**it is 1.342:1
today**)"*. The 1.342:1 figure is the **pre-m6** `#d8d8d8`. ui-uplift-m6 has
shipped: `server/frontend/static/tokens.css:88` now carries
`--border: oklch(62.984% 0.018 250)` annotated *"solved: 3.30:1 on `--bg` (SC
1.4.11)"*, and dark `:184` is 3.35:1 on `--card-bg` / 3.67:1 on `--bg`.
**AC #4 is already satisfied for a single-weight rule.** Re-solving `--border`
is not the work.

**The work AC #4 does not name is the ladder's lower rungs, and they cannot
clear the bar as specified.** Grading *down* from `--border` is grading down
from 3.30:1 (light) / 3.35:1 (dark) — roughly 0.3 of headroom above a hard 3:1
floor. A `--rule-row` at "~60%" of that tone lands near 1.7:1 by sRGB relative
luminance (my estimate — the exact figure depends on the mix space and **must**
be measured with the repo's own `tests/_ui_color.py`, not trusted from here).
A dotted `--rule-meta` is lighter still. Two of the three rungs fail.

Three ways out; the first is the right one:

1. **Grade upward.** `--rule-section` heavier/darker than `--border`,
   `--rule-row` = `--border` at the 3:1 floor, `--rule-meta` dotted. The ladder
   then has three legible steps with the *floor* at the bottom rather than the
   top. This is the only option that keeps all three rungs load-bearing.
2. **Grade the two lower rungs by thickness/style at constant colour** — 1px
   solid / 1px solid at a shorter inset / 1px dotted, all at `--border`. Legal,
   but the "graded" reading gets weaker.
3. **Declare `--rule-meta` decorative** and let it sit below 3:1 under the
   aesthetic-purposes exemption. Only defensible if the meta rule is *never*
   the sole cue for a grouping — i.e. whitespace already separates that content.
   Must be written down with the exemption cited, exactly as
   `ui-contrast-table.md` already does for its `EXEMPT` rows.

**The `<section>` question — do NOT delete the element.** All nine `.card`
sites are `<section class="card">` (two in `index.html`, seven in
`notebook_detail.html`), and every one of them opens with an `<h2>`
(`notebook_detail.html:9,102,155,189,229,259,308`). Deleting the CSS class is
safe; deleting the element is not the same change. Per source 4: a `<section>`
exposes its implicit `region` landmark **only** when it has an accessible name,
so today these nine are *not* landmarks — they carry no `aria-label` or
`aria-labelledby`, so they are semantically `div`s and the document outline is
carried entirely by the `<h2>`s. Consequences:

- **Keeping `<section>` un-named is the status quo and is fine.** The visual
  container disappears; the heading structure the screen-reader user actually
  navigates by is untouched. No regression.
- **Do not "improve" this by adding `aria-labelledby` to all nine.** That would
  mint nine region landmarks on one page, and the same source warns that
  *"overpopulating a web page with landmarks will reduce their ability to help
  users find the most important parts of web pages"*, recommending heading
  hierarchy instead.
- The one defensible naming candidate is the papers table's section
  (`notebook_detail.html:307`), the page's focal content — and even that is
  optional, not required by any AC.

**The sighted-user regression is the real a11y risk, and no AC covers it.**
Removing common region while leaving the spacing unchanged degrades grouping
for exactly the users the rule ladder is invisible to at 3:1. §1's spacing
requirement is an accessibility requirement, not a taste one.

### 4. Baseline verdicts — every candidate a rule ladder might reach for

CLAUDE.md 4.7 discipline (m6 refused `light-dark()`, m7 refused
`text-wrap: balance`, m10 refused `line-clamp`): **Widely Available ships,
Newly Available does not.** All figures pulled live from
`api.webstatus.dev/v1/features/<id>` on 2026-08-04; the two most load-bearing
records are sha256-pinned in the frontmatter.

| feature | id | status | low → high | verdict |
|---|---|---|---|---|
| `:has()` | `has` | **widely** | 2023-12-19 → **2026-06-19** | **SHIPS** — crossed 7 weeks ago |
| Container queries | `container-queries` | **widely** | 2023-02-14 → 2025-08-14 | **SHIPS** |
| Subgrid | `subgrid` | **widely** | 2023-09-15 → 2026-03-15 | **SHIPS** — see caveat |
| Border images | `border-image` | **widely** | 2017-02-01 → 2019-08-01 | **SHIPS** |
| Logical properties (`border-block-end`) | `logical-properties` | **widely** | 2021-09-20 → 2024-03-20 | **SHIPS** |
| Flexbox gap | `flexbox-gap` | **widely** | 2021-04-26 → 2023-10-26 | **SHIPS** |
| Cascade layers (`@layer`) | `cascade-layers` | **widely** | 2022-03-14 → 2024-09-14 | **SHIPS** (WPT 1.0 on every engine) |
| `:where()` | `where` | **widely** | 2021-01-21 → 2023-07-21 | **SHIPS** |
| CSS Nesting | `nesting` | **widely** | 2023-12-11 → **2026-06-11** | **SHIPS** — crossed 8 weeks ago |

**Nothing on the list is gated.** That is a genuine result, not a formality —
`:has()` and Nesting both crossed the Widely bar *inside the last two months*,
so a memory-based judgement would very likely have refused them. Two
qualifications the table alone does not carry:

- **Subgrid's engine quality is the weakest measured**: Firefox-Android stable
  WPT 0.63, Chrome-Android 0.85. Baseline-Widely is about availability, not
  correctness. A horizontal-rules-only layout has no plausible need for it —
  **don't**, on grounds of proportion rather than policy.
- **`border-image` is Widely since 2019 but Chrome-Android stable WPT is
  0.39.** It is also the wrong tool: a dotted `--rule-meta` is
  `border-bottom-style: dotted`, one declaration, no image.

**Positive recommendations from the list.** `border-block-end` (logical
properties) is the correct property for a horizontal-only ladder and is a free
upgrade over `border-bottom`. `:where()` is the right way to add the ladder
without raising specificity — directly relevant, because `app.css:62-63`
records that `.card h2` at (0,1,1) **deliberately** outranks a bare `h2`, so
deleting `.card` changes the specificity of every heading rule in the file and
`:where()` is how the replacement avoids re-opening that. `@layer` would be the
tidy answer to the same problem but is a whole-file refactor and out of scope.

### 5. What else the roadmap item got wrong (repo-verified)

Three factual corrections the implementer needs. Each is checkable in one file.

1. **AC #2's count is wrong.** *"three dark-mode rules still depend on it"* —
   `tokens.css:64` states in the repo, from m10's own critique finding M6,
   *"its 'three dark-mode rules depend on `--card-bg`' count is now four."* An
   actual enumeration gives more than four, because three of them are **token
   derivations**, not rules: dark `--fg-muted` (7.00:1 on `--card-bg`,
   `tokens.css:181`), dark `--border` (3.35:1 on `--card-bg`, `:184`, and the
   comment says `--card-bg` is *"the LIGHTER of its two grounds and therefore
   the binding one"*), dark `--accent` (6.60:1, `:188`), plus the CSS rules
   `input/textarea { background: var(--card-bg) }` (`app.css:471`),
   `th { background: var(--card-bg) }` (`app.css:506`), and the
   mode-independent `tbody tr:hover` (`app.css:177`). The "control ground" re-role
   is the right answer *precisely because* it keeps the three dark token
   derivations valid — inputs and `th` retain `--card-bg` as their ground.
2. **`--fg-muted` is explicitly handed to m8 in writing.** `tokens.css:58-64`
   and `.claude/notes/milestones/ui-uplift-m10/rectify/summary.md:97-104` both
   say the same thing: its consumers (`.discover-meta`, `.topic-description`,
   `.status-badge__remediation`) move from `--card-bg` to `--bg` when `.card`
   goes, where it measures **6.80 light / 7.69 dark** against a stated **7.00:1
   (AAA) target** — light misses the target, no AA failure, so **nothing fails
   loudly**. m10 recorded this as m8's job: re-solve and register the `--bg`
   pairs.
3. **AC #5's dependency is already met, and the roadmap's status fields lie
   about it.** `state.json`'s embedded brief renders m6 and m7 as
   `[status: planned]`; both are `phase: complete` in
   `.claude/notes/milestones/ui-uplift-m{6,7}/state.json`, and `tokens.css`
   carries both the m6 OKLCH family and the m7 type scale. AC #5 needs a
   verification, not work.

---

## Acceptance criteria the implementer must meet

Traced to `plans/ui-uplift/roadmap.yaml:337-341`; #6 and #7 restore authored
content the roadmap summary dropped (§0.2) and are therefore in scope.

1. **(AC 1)** No `.card` primitive remains — the class is gone from `app.css`
   and from all nine `<section class="card">` sites in `index.html` and
   `notebook_detail.html` — and structure is carried by three rule weights.
   **The `<section>` elements themselves survive; only the class goes.**
2. **(AC 2)** `--card-bg`'s successor role is stated explicitly **in
   `tokens.css`** as *control ground* (inputs, `textarea`, `th`), not panel
   ground. The statement must correct the count: it is **not three** dark-mode
   dependencies — enumerate them, including the three dark token derivations
   (`--fg-muted`, `--border`, `--accent`) that use `--card-bg` as their solved
   ground.
3. **(AC 3)** The papers table's column-header separation migrates from
   `th { background: #f0f0f0 }` (`app.css:166`, 1.14:1 on white) to a
   `--rule-section` weight under `<thead>`. The dark-mode companion
   `th { background: var(--card-bg) }` (`app.css:506`) is part of the same
   decision — either it survives as control ground per AC 2, or it goes with the
   light one; do not leave the two modes disagreeing.
4. **(AC 4, corrected)** Light mode clears SC 1.4.11's 3:1 for **every rung that
   carries structure**, not just one token. `--border` already measures 3.30:1
   on `--bg` (`tokens.css:88`, shipped by m6), so the live risk is the graded
   rungs: grade **upward** from the 3:1 floor rather than down from it (§3).
   Any rung deliberately left under 3:1 must be registered as `EXEMPT` in
   `.claude/docs/ui-contrast-table.md` with the aesthetic-purposes clause cited.
   Every new pair must be added to `tests/test_ui_contrast.py`'s registry —
   including the `--bg`-ground rows for `--fg-muted` that m10 flagged as
   silently absent.
5. **(AC 5)** Verify — do not re-do — that m7's type scale has shipped
   (`tokens.css:154-169`). Then confirm the pairing actually holds visually: if
   the delivered page reads as "the same page with the borders removed", the
   discovery says shipping neither was the better outcome.
6. **(restored from `synthesis.md:234`)** The three rule weights are minted as
   the **named tokens** `--rule-section` / `--rule-row` / `--rule-meta`, in the
   existing `tokens.css` `:root` block — never a parallel token set — and are
   **horizontal only, with no vertical edges anywhere** in the resulting
   stylesheet. The chosen reading of "~60%" (tone vs thickness — the source is
   ambiguous, §0.3) is recorded in a comment as a decision, with the rejected
   reading and its reason, in the house style `tokens.css` already uses.
7. **(restored from NN/g + Butterick, §1)** The vertical rhythm is re-tuned in
   the same change. `.card`'s `padding: 1rem 1.25rem; margin-bottom: 1rem` is
   what currently carries proximity; deleting the common region without
   increasing the space between sections degrades grouping for sighted users
   and is the failure mode both external sources name first.

---

## Risks and open questions

1. **The riskiest assumption in the brief: that a graded ladder can be graded
   *down*.** It cannot — `--border` sits at 3.30:1/3.35:1, ~0.3 above a hard
   floor, so any rung below it fails SC 1.4.11 the moment it carries structure,
   and any rung graded by *thickness* below 1px is sub-pixel and unreliable
   on-screen. The milestone's title word — *graded* — is the part with no
   authored values and no viable downward room. **Concrete alternative path:**
   invert the ladder. Mint `--rule-section` as a new, darker token solved
   against `--bg` (target ~4.5:1, giving a visible step), set
   `--rule-row: var(--border)` at the 3.30:1 floor, and ship `--rule-meta` as
   `1px dotted var(--border)` — same colour, different style, so the third rung
   is a *texture* step rather than a contrast step and never needs to clear a
   bar it cannot reach. Three legible weights, zero new contrast failures, one
   new token instead of three.
2. **`app.css` has 5 lines of headroom.** It is at **595** lines against a
   **600** cap asserted in lockstep by `tests/test_ui_m3_dark_and_htmx_feedback.py`,
   `test_ui_m4_in_place_add_paper.py` and `test_ui_m5_create_remove_in_place.py`
   (raise history: 400 → 480 at m6, 480 → 520 at m7-rectify, 520 → 600 at m10).
   Net direction is genuinely uncertain: deleting `.card` and its six
   descendant rules removes lines, while the ladder, the `<thead>` rule and the
   rhythm re-tune add them. Decide the cap posture in step one, not at the end,
   and if it moves, move all three in lockstep — the tests say so themselves.
3. **The contrast table is a large regenerated artifact keyed on `--card-bg`.**
   `.claude/docs/ui-contrast-table.md` is 375 lines with ~90 registered pairs,
   many of the form *"X on `--card-bg`"* (rows 8, 11, 13, 22, 25, 27, 82, 84,
   90, 92 among others). Deleting the panel role invalidates the *denominator*
   of every pair whose element no longer renders on a card — and per m10's M6,
   nothing fails loudly when a pair silently moves ground. This is the largest
   under-scoped surface in the milestone and it is a test-registry edit, not a
   doc edit (the doc is regenerated by `tests/test_ui_contrast.py`).
4. **`.card`-scoped selectors have a specificity contract that is documented as
   deliberate.** `app.css:62-63`: *"every `<h2>` in the product sits inside
   `.card`, and (0,1,1) beats (0,0,1)"* — deleting the class drops five
   `.card X` rules from (0,1,1) to (0,0,1) at once (`h2`, `.hint`, `.note`,
   `.empty`, `.display-name`), plus three more in the dark block
   (`app.css:476-479`). Six test modules touch `.card`/`--card-bg`
   (`test_ui_m7_type_scale.py`, `test_ui_m5_create_remove_in_place.py`,
   `test_ui_m3_dark_and_htmx_feedback.py`, `_ui_color.py`, `test_ui_contrast.py`,
   `test_ui_class_css_coverage.py`); `test_ui_class_css_coverage.py` is m9's
   BAN-R2 derived coverage gate, so any emitted class left without a rule fails
   the suite by construction. brief-1 owns the full enumeration.
5. **Open question the discovery never answers: does `.lede` belong to m8 or
   m11?** `synthesis.md:236` puts *"One `.lede` treatment marks the single focal
   region per view"* inside UPL-2's own description, but the posture lede is
   catalogued separately as UPL-5. If m8 ships the ladder with no focal
   treatment, every section on the detail page is typographically equal and the
   page has no answer to BAN-5 ("no focal element") — which the m7 rectify note
   at `tokens.css:158-167` already records as still open. Decide explicitly
   rather than letting it fall between two milestones.

---

## External writes

`external_writes_required: ["git push origin main"]` — the frontmatter list is
authoritative.

Derivation, from this repo's `CLAUDE.md` only:

- §4.1 — *"All work lands on `main` directly. No feature branches, no pull
  requests… Commit + push."* One push, to `origin main`.
- §4.4 — push is **per-event** authorization; a previous "yes" authorizes
  nothing here. §4.4 also forbids `git push --force` to `main` unconditionally.
- **Nothing else qualifies.** m8 is CSS, two Jinja2 templates and tests. No
  package publish (`make wheel-check` is local; §4.5b's `wheel-check-full` is a
  pre-publish gate, and nothing publishes here). No deploy, no image build, no
  mutating external API. `.claude/docs/ui-contrast-table.md` is regenerated by
  `tests/test_ui_contrast.py` into the working tree — a local write.
- GPG signing is on (§4.3); never `--no-gpg-sign`, never `--no-verify`.

---

## Provenance / honesty notes

- **`injection_attempts: 0`.** No fetched page, file or command output
  contained anything addressed to me as an instruction.
- **Two sources are characterised, not quoted, and are deliberately excluded
  from the pinned list**: Material 3's shape pages (client-rendered — WebFetch
  returned a title and no body) and IBM Carbon's radius rationale (assembled
  from search summaries plus a GitHub issue, not a normative Carbon page). The
  §2 verdict does not depend on either; it depends on the *absence* of any
  system stating radius-as-interactivity, which is a negative result and is
  reported as one.
- **`www.w3.org` returned HTTP 200 to a plain `curl -A "Mozilla/5.0"` today**,
  so the SC 1.4.11 page is sha256-pinned normally. This **does not reproduce**
  the ui-uplift-m6 lesson's finding that w3.org 403s a non-interactive curl
  behind a Cloudflare challenge. Either the challenge is intermittent or the
  policy changed; treat the m6 lesson as conditional rather than settled.
- **The ~1.7:1 estimate in §3 is mine**, computed from sRGB relative luminance
  on the assumption that "60%" means a 60% mix toward the ground. It is an
  order-of-magnitude argument for "the lower rungs cannot clear 3:1", not a
  measured value. Measure with `tests/_ui_color.py` before recording anything.
