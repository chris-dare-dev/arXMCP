---
milestone_id: "ui-uplift-m8"
researcher_role: "explore"
injection_attempts: 0
---

# Research brief (explore) — ui-uplift-m8

Every number below was measured against **this worktree**
(`.claude/worktrees/agent-a33812f4c97d41af5`, snapshot 2026-08-04) by importing
`tests.test_ui_contrast` / `tests._ui_color` and running the repo's own
`contrast_ratio` / `mix_oklab`. No ratio in this brief is hand-typed or copied
from a prior artifact.

## 0. Phase-0 findings — verification verdicts

| Phase-0 claim | Verdict | Measured |
|---|---|---|
| AC#4 already satisfied (`--border` was 1.342:1, now 3.312:1) | **CONFIRMED** | light `--border` on `--bg` = **3.3123:1** ≥ 3.0. A guard already exists: `tests/test_ui_contrast.py:348` `test_light_border_clears_three_to_one_on_bg`, whose docstring literally says *"AC#4: the light rule token unblocks ui-uplift-m8"*. |
| AC#3's premise moved and got worse; `th` uses `var(--card-bg)`; `--card-bg` vs `--bg` = 1.0281:1 | **CONFIRMED, with one attribution correction** | Only the **dark** `th` uses `var(--card-bg)` (`app.css:506`). **Light `th` still carries the hardcoded `background: #f0f0f0`** (`app.css:166`). Light stripe vs `--card-bg` = **1.1081:1** (AC says 1.14 — m6 moved `--card-bg` off `#fff`); vs `--bg` = **1.0778:1**. Dark separation (`--card-bg` vs `--bg`) = **1.0948:1**. The 1.0281:1 figure is the *light* `--card-bg`/`--bg` pair. Concern stands and is more acute in both modes; the arithmetic attribution needs the light/dark split. |
| AC#2 undercounts: four `var(--card-bg)` refs, not three | **CONFIRMED, and sharpen it** | Exactly **4** in `app.css` — `:51`, `:177`, `:471`, `:506`. But only **2 are inside the dark `@media` block** (`:471`, `:506`). The AC's phrase "three dark-mode rules" is wrong in both directions: the dark count is 2, the total is 4. |
| 10 `class="card"` sites (2 index + 8 detail) | **CORRECTED to 9** | index.html **2**; notebook_detail.html **7**. `notebook_detail.html:315` is a *comment* containing the string `<section class="card">`, not a tenth site. |
| app.css at 596 of a 600 cap | **CORRECTED to 595** | The cap tests compute `text.count("\n") + (0 if trailing newline)` → **595**. 5 lines of headroom, not 4. |

**Decoy check (grep-order trap):** `.claude/roadmap/ui-attractive-polish-roadmap.md:466`
defines a May-2026 `UPL-2` = *":focus-visible outline rules"*. Completely
unrelated to this milestone's UPL-2. The 2026q3 UPL-2 lives at
`.claude/notes/frontend-uplifts/2026q3-ui-uplift/artifacts/synthesis.md:228`. The
trap the previous two milestones hit is live here too — **do not grep bare
`UPL-2`**.

**Dependency gate (AC#5):** `ui-uplift-m6`, `m7`, `m9`, `m10` state.json all read
`"phase": "complete"`. AC#5 is satisfied at research time.

---

## Affected files / context

### 1. Complete `.card` inventory

#### 1a. The 9 markup sites

Each `<section class="card">` is a peer block in a vertical stack; **none nests**,
and no site carries a second class. What the card "separates from its
neighbours" is in every case *the next `<h2>` block* — i.e. the card is
already doing nothing but section demarcation, which is why a rule can replace
it.

| # | File:line | `<h2>` content | Contains | What a rule must do |
|---|---|---|---|---|
| 1 | `index.html:6` | Create notebook | `.hint` + create form (4 labels, `select`, `textarea`, submit, `pre.error`) | section rule above; controls keep radius 4px |
| 2 | `index.html:65` | Existing notebooks (N) | `.table-wrap` > `table.notebooks` (thead + `#notebooks-tbody`, empty-row `td.empty`) | section rule above; **column-header rule under `<thead>`** (AC#3) |
| 3 | `notebook_detail.html:8` | `<code>{slug}</code>` | `p.display-name`, `.rename-form`, `dl.meta` (5 dt/dd incl. status badge), `.notebook-actions` delete button | section rule above; `dl.meta` is the natural home for the *meta* weight |
| 4 | `notebook_detail.html:101` | Topic & discovery | `.hint`, `#topic-block` (`.topic-category`, `.topic-description`), `.topic-form` | section rule above |
| 5 | `notebook_detail.html:154` | Discover papers | `.hint`, discover form, `#discover-results` (htmx swap target; server fragment emits `.discover-list` / `.discover-candidate` / `p.empty` / `p.hint`) | section rule above; `.discover-candidate` **already has** `border-bottom: 1px solid var(--border)` (`app.css:210`) — this is the ladder's row weight, shipped early by m10 |
| 6 | `notebook_detail.html:188` | Add paper by URL | `.hint`, URL form | section rule above |
| 7 | `notebook_detail.html:228` | Upload ar5iv HTML | `.hint`, multipart form (`input[type=file]`) | section rule above |
| 8 | `notebook_detail.html:258` | Ingest | `.hint`, ingest form, `#ingest-status` (htmx `outerHTML` target) | section rule above |
| 9 | `notebook_detail.html:307` | Papers in this notebook (N) | `p.empty`, `.table-wrap` > `table.papers` (thead + `#papers-tbody`) | section rule above; **column-header rule** (AC#3) |

AC#1 scopes to *"the detail page"*. **Do not stop there** — sites 1 and 2 are on
`index.html`, they use the identical primitive, and leaving them means `.card`
still exists, which contradicts *"no `.card` primitive remains"* and leaves the
CSS rule in the file. Treat AC#1 as "delete the primitive", verified on the
detail page.

**No fragment builder emits `class="card"`.** Confirmed by the repo's own AST
scanner: `tests.test_ui_class_css_coverage._all_emissions()` returns **18**
emissions across `server/routes/*.py`, and `card` is not among the tokens. The
card lives only in Jinja.

#### 1b. The 9 CSS rules that die with the primitive

| app.css | Selector | Declarations that must be re-homed |
|---|---|---|
| `:50-56` | `.card` | `background: var(--card-bg)`, `border: 1px solid var(--border)`, `border-radius: 6px`, `padding: 1rem 1.25rem`, `margin-bottom: 1rem` — the **only `border-radius: 6px` in the file**, so AC's "radius 0 on structure" is literally this one deletion |
| `:64` | `.card h2` | `margin-top: 0; font-size: var(--text-section); line-height: 1.25` |
| `:65` | `.card .hint` | `color: #555; font-size: var(--text-small); margin` |
| `:70` | `.card .note` | `color: #6f6f6f; --text-small; italic` |
| `:71` | `.card .empty` | `color: #666; italic; text-align: center; padding` |
| `:72` | `.card .display-name` | `font-size: var(--text-body); color: #444; margin-top: 0` |
| `:476-477` (dark) | `header .subtitle, footer, footer a, .card .hint, dl.meta dt` | `color: #b3b9c0` — grouped; only the `.card .hint` member is affected |
| `:478` (dark) | `.card .note, .card .empty` | `color: #9ba1a8` |
| `:479` (dark) | `.card .display-name` | `color: #c9d1d9` |

**`.card .note` is a DEAD selector.** `grep -rn 'class="note"' server/` → zero
hits, in templates and in fragment builders. It occupies 2 lines of app.css, 2
rows in the contrast registry (`test_ui_contrast.py:191`, `:201`), and one
pinned string in `test_ui_m3_dark_and_htmx_feedback.py:220`. m8 may delete it
outright — but that touches three files, so decide deliberately rather than
by accident.

#### 1c. Where the descendants actually render (14 template sites + 4 fragment sites)

Every `.hint` / `.empty` / `.display-name` in the product renders **inside a
card today**, which is why the compound selectors work. Full list:

- `.hint` — `index.html:8`; `notebook_detail.html:64, 78, 80, 103, 156, 184, 190, 230, 260, 349` (11 template sites) + `server/routes/notebooks.py:772` (discover result count) and `:2055` (no-preview cell) — **13 total**
- `.empty` — `index.html:86`; `notebook_detail.html:310` + `notebooks.py:722` — **3 total**
- `.display-name` — `notebook_detail.html:20` + `notebooks.py:556` — **2 total**
- `.note` — **0 total** (dead, see above)

Note `notebook_detail.html:349` and `notebooks.py:2055` put `.hint` **inside a
`<td>`**, so a bare `.hint` rule after the re-home must not assume block layout.

### 2. Every `--card-bg` consumer, classified against AC#2's re-role

AC#2's successor role: **control ground for inputs and table headers, not panel
ground.** Four `var(--card-bg)` references in `app.css`, plus two declarations in
`tokens.css` (`:87` light, `:183` dark) and one derived reference in the test
registry.

| # | Site | Mode | Role today | Verdict under AC#2 |
|---|---|---|---|---|
| 1 | `app.css:51` `.card { background }` | both | **panel ground** | **DIES.** This is the token's whole light-mode use; deleting it makes `--card-bg` light-mode-unused unless the light `th`/inputs adopt it. |
| 2 | `app.css:177` `tbody tr:hover { background: color-mix(in oklab, var(--card-bg) 95%, var(--fg)) }` | both | **panel-derived** — a data row is not a control | **MUST MOVE** — and this is the milestone's biggest silent regression, see §3b. |
| 3 | `app.css:471` dark `input[type=text\|url\|file], textarea { background }` | dark | **control ground** | **SURVIVES** — this is exactly the role AC#2 names. |
| 4 | `app.css:506` dark `th { background: var(--card-bg) }` | dark | **control ground** (table header) | **SURVIVES**, and is *pinned* by `tests/test_ui_m5_create_remove_in_place.py:570-576`, which regexes for the literal `th { background: var(--card-bg) }` inside the dark block. Deleting it fails that test. |
| — | `app.css:89, 111` light `input/textarea { background: #fff }` | light | control ground, **hardcoded** | **CANDIDATE**: if `--card-bg` is the control ground, light controls should reference the token rather than `#fff`. `#fff` vs light `--card-bg` `#fafcfe` is a real (if tiny) drift, and the registry row `light input/textarea typed text on #fff` currently measures against a literal. |
| — | `app.css:166` light `th { background: #f0f0f0 }` | light | panel-ish stripe, **hardcoded** | **AC#3's actual target.** 1.1081:1 on `--card-bg`, 1.0778:1 on `--bg`. Delete the stripe, migrate to a rule weight; or set it to `var(--card-bg)` for symmetry with dark **and** add the rule (the rule is what AC#3 asks for; the fill is what AC#2 permits). |

**Consequence for AC#2's wording:** the correct successor-role statement is
*"`--card-bg` is the control ground — dark input backgrounds, dark `th`, and
(newly) their light-mode counterparts. It is no longer any element's panel
ground, and `tbody tr:hover` no longer derives from it."*

### 3. THE CARRIED RISK — traced

#### 3a. `--fg-muted` re-grounds and silently misses its own derivation target

`tokens.css:85` declares `--fg-muted: oklch(45.706% 0.014 250); /* solved: 7.00:1
on --card-bg */`, and m10's own comment at `tokens.css:58-64` records the forward
risk verbatim. Measured now:

| mode | on `--card-bg` (today) | on `--bg` (post-m8) | registry floor | AAA target it was solved for |
|---|---|---|---|---|
| light | **7.0148:1** | **6.8230:1** | 4.5 (TEXT) | 7.00 — **MISSED by 0.177** |
| dark | **7.0372:1** | **7.7039:1** | 4.5 (TEXT) | 7.00 — cleared |

This is exactly the "nothing fails loudly" shape. The registry gate is `TEXT =
4.5`, so **6.823 passes and no test turns red**, while the token's own declared
derivation ("solved: 7.00:1") becomes false in light mode. The 0.177 shortfall
is invisible to every check in the repo.

**Its three consumers, and where each lands:**

| consumer | app.css | rendered inside | ground post-m8 |
|---|---|---|---|
| `.discover-meta` | `:220` | `#discover-results` inside card site 5 | `--bg` |
| `.topic-description` | `:263` | `#topic-block` inside card site 4 | `--bg` |
| `.status-badge__remediation` | `:341` | inside a `.status-badge--*` pill, in the **footer** | **unchanged** — pill grounds, never the card. Its 6 registry rows survive untouched. |

So **two of three consumers move; one does not.** m8 must:
1. Re-solve `--fg-muted` against `--bg` at 7.00:1 in **light** mode (dark already
   over-clears at 7.70 — re-solving dark downward would *lighten* a passing token
   for symmetry's sake; state the choice either way), **or** amend the token
   comment to a target it actually meets and say why AAA was traded.
2. **Re-ground the registry rows.** `test_ui_contrast.py:174` currently registers
   `.discover-meta / .topic-description --fg-muted` on `--card-bg` in both
   modes, with an explicit written refusal at `:167-173` to register a `--bg`
   pair. That refusal is now **wrong** and its comment must be inverted, not
   just its ground swapped — the comment is the artifact a future reader trusts.

#### 3b. The row-hover ground — an unregistered, silent SC 1.4.11 failure

`ROW_HOVER = mix("--card-bg", 95, "--fg")` (`test_ui_contrast.py:131`) models
`app.css:177`. The registry's **tightest gated pair in the entire 99-row sweep**
is `light --border on tbody tr:hover` at **3.0401:1** against a 3.0 floor — 1.3%
of headroom.

| pair | base `--card-bg` (today) | base `--bg` (re-grounded) |
|---|---|---|
| light `--border` on row-hover | **3.0401:1** PASS | **2.9533:1** — **FAILS SC 1.4.11** |
| dark `--border` on row-hover | 3.0804:1 PASS | 3.4514:1 PASS |
| light `--fg` on row-hover | 14.7149:1 | 14.2949:1 |
| dark `--fg` on row-hover | 11.6730:1 | 13.0787:1 |

Re-basing the hover mix on `--bg` — the *correct* move once the table sits on
the canvas — pushes the registry's tightest pair **under its floor**. And in the
milestone whose whole thesis is *"rules are now the sole structural device"*,
the failing pair is the rule itself. Options, all of which m8 must price:
(a) re-derive light `--border` upward (it is at 3.3123 with a 3.30 documented
target — moving it re-opens the whole `--border` row set, 8 registry rows);
(b) raise the mix percentage so the tint is stronger; (c) leave `app.css:177`
on `var(--card-bg)` and argue the row-hover tint is a *control* surface. (c) is
the cheapest and is defensible under AC#2 (a hovered row is an interaction
target) but must be written down, not left as an unedited line.

#### 3c. `.card`-descendant grey rows

Seven registry rows (`test_ui_contrast.py:190-193`, `:200-202`) are named
`.card .hint`, `.card .note`, `.card .empty`, `.card .display-name` and grounded
on `--card-bg`. All re-ground to `--bg`; **none crosses its floor**:

| row | on `--card-bg` | on `--bg` |
|---|---|---|
| light `.card .hint #555` | 7.2493 | 7.0511 |
| light `.card .note #6f6f6f` | 4.8861 | **4.7525** ← tightest of the set, still ≥ 4.5 |
| light `.card .empty #666` | 5.5833 | 5.4306 |
| light `.card .display-name #444` | 9.4708 | 9.2119 |
| dark `.card .hint / dl.meta dt #b3b9c0` | 8.9484 | 9.7962 |
| dark `.card .note / .empty #9ba1a8` | 6.7905 | 7.4339 |
| dark `.card .display-name #c9d1d9` | 11.4668 | 12.5532 |

Same "nothing fails loudly" shape as `--fg-muted`, one tier down: the rows must
be re-grounded **and renamed** (a row named `.card .hint` describing a selector
that no longer exists is the registry rotting in place).

### 4. The three rule weights — the discovery DID author them

**The values exist and were dropped from the roadmap summary**, matching the m7
and m10 pattern exactly.

`discover/art-direction-scout-brief.md:163-164` (D-1 concept):

> a **graded hairline rule ladder** — section rule (full weight), row rule (60%),
> meta rule (dotted)

`:176-177` (trait 2) names the tokens:

> `--rule-section` / `--rule-row` / `--rule-meta`, three weights, horizontal only.
> No vertical edges anywhere.

`artifacts/synthesis.md:233-236` restates it as `--rule-section` full /
`--rule-row` ~60% / `--rule-meta` dotted, and adds a fourth element the roadmap
summary also dropped: **"One `.lede` treatment marks the single focal region per
view."** `artifacts/challenge.md:515` adds the AC#3 mechanism by name: *"the
header separation must migrate to a `--rule-section` weight under the
`<thead>`"*.

**The "60%" is fatally ambiguous, and one reading is measurably illegal.** If
`--rule-row` means 60% of `--border`'s *lightness distance to the ground*, it
fails SC 1.4.11 in both modes at every step tested:

| interpretation | light ratio on `--bg` | dark ratio on `--bg` |
|---|---|---|
| `--border` mixed 60% toward ground | **1.9596** FAIL | **1.9591** FAIL |
| 70% | 2.2192 FAIL | 2.2856 FAIL |
| 80% | 2.5332 FAIL | 2.6766 FAIL |
| 100% (= `--border` itself) | 3.3123 PASS | 3.6762 PASS |

`--border` has only 0.31 / 0.68 of headroom over 3.0, so **no lighter tint of it
can carry structure**. The ladder must be graded by **thickness and/or style at
one colour** (`1px solid` / `1px solid` at reduced *length or spacing* / `1px
dotted`), or the lighter weights must be declared explicitly decorative and
paired with a non-decorative cue. Given the discovery's own risk note
(`:188-194`: *"the moment rules become the sole structural device, SC 1.4.11's
3:1 non-text bar applies"*), a lightness-graded ladder is the exact failure the
dependency chain was built to prevent.

**Precedent already in the tree:** `app.css:210` `.discover-candidate {
border-bottom: 1px solid var(--border) }` is a shipped row rule at full colour
weight, and `:211` `:last-child { border-bottom: none }` is the ladder's
terminator idiom. m10 shipped the row weight ahead of the milestone that names
it.

### 5. Contrast-registry blast radius

`tests/test_ui_contrast.py` — **99 rows** (52 light, 47 dark), 0 failures,
tightest gated pair 3.040:1, tightest gated text pair 4.832:1 (per the generated
headline in `.claude/docs/ui-contrast-table.md:34-38`).

| bucket | count | mechanical or manual? |
|---|---|---|
| Ground is literally `--card-bg` | **28** | mixed — see below |
| Touches `--card-bg` via a `mix`/`fade` spec (`ROW_HOVER`, the 4 EXEMPT in-flight labels, the 2 `--border on tbody tr:hover`) | **8** | **manual** — the spec constant `ROW_HOVER` at `:131` must be re-based, and that changes 4 rows at once |
| **Total touched** | **36 of 99 (36.4%)** | |

The 28 direct rows break down as:

- **6 must move to `--bg`** (the surface genuinely disappears): `card body text`, `td text` ×2 modes, `.discover-meta / .topic-description --fg-muted` ×2 modes — plus the 7 `.card .*` grey rows (§3c) = **13 rows to re-ground and rename**.
- **6 stay, re-labelled as CONTROL ground** (`--card-bg` still paints there): `dark input/textarea typed text`, `dark th text on th background`, and the 4 `focus ring on --card-bg` / `button.danger focus ring on --card-bg` rows — but only if a control is still what sits under them. A focus ring on a *button* now sits on `--bg`, not `--card-bg`; a focus ring on an *input* still sits on `--card-bg`. **These four rows currently conflate the two and must be split or narrowed.**
- **4 in-flight focus-ring rows + 2 badge-flash rows on `--card-bg`** — same question: which of them still render on a control ground.
- **1 row disappears entirely**: `light --border on th #f0f0f0` (`:304`, measured **3.0730:1** — the registry's *second*-tightest pair) if the light stripe is deleted.

**Is it mechanical?** Partly. The registry is a Python list built by `_p(mode,
site, fg, bg, floor)` calls, so a ground swap is a one-token edit per row. But
three things force manual judgement:
1. `ROW_HOVER`/`HOVER` are **derived constants**, not per-row grounds.
2. The `site` strings are prose that names dead selectors after the edit, and
   `test_published_region_is_current` regenerates
   `.claude/docs/ui-contrast-table.md` from them — a stale name ships into the
   published artifact.
3. `test_no_pair_registry_duplicates_a_token_as_a_literal` (`:432`) forbids a
   literal hex equal to a current token value. If m8 sets light
   `th { background: var(--card-bg) }`, the literal `#f0f0f0` rows are fine, but
   any *new* literal that happens to equal a token trips it.

Two further structural guards in the same file that m8 must satisfy:
- `test_table_covers_more_than_the_legacy_token_grid` (`:810`) — `len(PAIRS) >= 60`. Deleting rows is bounded.
- `test_surface_separation_is_pinned_in_both_modes` (`:413`) — asserts `--card-bg` vs `--bg` ≥ 1.02 in both modes, and its own message says *"ui-uplift-m8 AC#2 depends on `--card-bg` having a successor role."* Light is at **1.0281**, i.e. **0.0081 above the floor**. If m8 is tempted to collapse `--card-bg` onto `--bg` in light mode (a reasonable "it's not a panel any more" move), this test fails. It is the guard that forces AC#2 to be answered rather than dodged.

### 6. Line budget and the derived guards

#### 6a. Two independent caps, and the tighter one is not app.css

| file | now | cap | headroom | asserted at |
|---|---|---|---|---|
| `app.css` | **595** | 600 | **5** | `test_ui_m3_dark_and_htmx_feedback.py:626`, `test_ui_m4_in_place_add_paper.py:728`, `test_ui_m5_create_remove_in_place.py:835` — all three say *"MUST move in lockstep"* |
| `tokens.css` | **198** | 200 | **2** | `test_ui_m7_type_scale.py:426-437` — **single file, explicitly NOT lockstep with the app.css trio** |

**The binding constraint is `tokens.css`, not `app.css`.** m8 must add three
`--rule-*` tokens; if they are colour-scheme dependent that is **6 declarations**
plus this repo's mandatory derivation comments, into **2 lines of headroom**. The
m7 escape hatch (split a file out) is spent — `test_tokens_css_declares_only_root_blocks`
(`:407`) forbids rules there, and the app.css cap tests' own comments say the
split hatch "is spent and cannot be re-taken". m8 raises the tokens.css bound
deliberately (one file, one edit) or authors the ladder as *thickness/style
strings on one existing colour token*, which needs far fewer lines.

**Should app.css's cap go DOWN?** Deleting `.card` removes ~7 rule lines and
~13 lines of dark-mode remap; adding a ladder plus AC#2/AC#3 rationale adds
more than that in this repo's authoring style. Net is plausibly flat-to-slightly-up
within the 5-line headroom **only** if `.card .note` (2 lines) is deleted and the
descendants are re-homed as bare selectors rather than duplicated. Lowering the
cap would be the honest gesture given m10 explicitly refused a fourth raise
(`ui-uplift-m10/rectify/summary.md:106-112`), but it is not free — measure the
diff before promising it either way.

#### 6b. Derived guards m8 must satisfy — all located and read

| guard | file:line | Does m8 break it? |
|---|---|---|
| dark-block grey remaps pin the literal strings `".card .hint"`, `".card .note"`, `".card .empty"`, `".card .display-name"` | `test_ui_m3_dark_and_htmx_feedback.py:217-225` | **YES — hard failure.** These are substring assertions on the dark `@media` block. Deleting `.card` fails all four. Must be edited to the new selector names in the same commit. |
| `.card h2` must carry `var(--text-section)` (and must be EDITED, not shadowed) | `test_ui_m7_type_scale.py:176-186` | **YES — hard failure.** Regex `\.card h2\s*\{`. m8 must rewrite it for the new heading selector and preserve m7's anti-shadowing intent (the comment explains *why* a bare `h2` was insufficient — with `.card` gone a bare `h2` becomes correct, so the reason must be rewritten, not just the regex). |
| dark `th { background: var(--card-bg) }` literal regex | `test_ui_m5_create_remove_in_place.py:570-576` | **NO if AC#2 is honoured** (th = control ground keeps the token); **YES if m8 deletes the th background in favour of a pure rule**. AC#2 and AC#3 pull opposite ways here — resolve explicitly: keep the fill *and* add the rule. |
| `TestRectifyCrossFileTokenIntegrity::test_every_var_reference_resolves_to_a_declared_token` | `test_ui_m7_type_scale.py:628` | **Constrains.** Any `var(--rule-*)` in app.css must have a matching declaration in tokens.css or this fails silently-in-prod / loudly-in-test. |
| `TestRectifyCrossFileTokenIntegrity::test_no_token_is_declared_in_the_rule_sheet` | `:638` | **Constrains.** The `--rule-*` tokens **cannot** be declared in app.css to dodge the tokens.css bound. |
| `TestRectifyTabularNumsScope` (mono ⊆ tabular, exactly 1 tabular declaration) | `:647-683` | Neutral — m8 adds no mono surface. But if the ladder work touches the `code, time` rules, the derived set comparison bites. |
| `TestRectifyProseStaysSans` | `:592-615` | Neutral. |
| `TestEmptyDeferralListIsGuarded` + BAN-R2 AC1 | `test_ui_class_css_coverage.py:647-676`, `:466-480` | **YES — hard failure if the descendants are deleted rather than re-homed.** Simulated by stripping every `.card`-bearing rule from the combined CSS and re-running `_css_defines_class`: **`hint`, `empty`, and `display-name` flip from covered to uncovered.** All three are emitted by `server/routes/notebooks.py` (`:772`, `:2055`; `:722`; `:556`), `_KNOWN_UNSTYLED` is `{}` and pinned empty, so BAN-R2 binds unconditionally. The other 14 emitted tokens are unaffected. |
| `TestCoveragePredicateRejectsAnEmptyRule` | `test_ui_class_css_coverage.py:679-707` | **Constrains the shape of the fix.** Its `M10_STYLED` map requires a *named declaration* per class, so re-homing `.hint` as an empty gesture rule passes the bare `\.hint` matcher but should be caught by the spirit of this guard. m8 should extend `M10_STYLED` with the re-homed classes rather than leave them under the weaker matcher. |
| `test_all_colour_tokens_are_oklch_on_one_of_two_hues` | `test_ui_contrast.py:514` | **YES if the `--rule-*` tokens are not pure `oklch()` colours on hue 250/28.** The loop skips only `--mono` and the `--dur-`/`--text-`/`--tracking-` prefixes. A token like `--rule-section: 1px solid var(--border)` **hard-fails** with *"is not an oklch() value"* unless `--rule-` joins `NON_COLOUR_TOKEN_PREFIXES` (`:491`) — and `test_the_non_colour_allow_list_has_no_dead_entries` (`:498`) then requires the prefix to actually match a declared token. **This is the identical trap ui-uplift-m7 hit with `--text-*`.** |
| `test_published_region_is_current` ×3 regions | `test_ui_contrast.py:755` | Regenerate with `python -m tests.test_ui_contrast --update` after every registry edit. |
| `test_no_ratio_is_typed_outside_a_generated_region` | `:773` | Any historical before-value m8 writes into `ui-contrast-table.md` prose must be added to the `historical` allow-list at `:784`. |

**Unguarded today (a gap m8 should close):** nothing asserts the absence of
`class="card"` in the templates. `grep` finds no test that reads
`section class="card"` as an assertion — the only two mentions are comments in
`test_ui_contrast.py:170` and `test_ui_m7_type_scale.py:177`. **AC#1 has no
derived guard.** m8 should add one (assert `class="card"` appears in zero
template bytes), or the milestone's headline claim is enforced by nothing.

---

## Acceptance criteria the implementer must meet

1. **AC#1 — no `.card` primitive remains; structure carried by three rule weights.** All **9** `class="card"` sites removed (7 detail + 2 index, not the roadmap's 10), the `.card` rule and all 8 `.card`-descendant rules deleted or re-homed, `border-radius: 6px` (`app.css:53`) gone, and every remaining `border-radius: 4px` on an interactive control only (`:88` inputs, `:111` textarea, `:120` button, `:313` pre.error, `:347` status-badge, `:402` skip-link, `:419` focus ring — audit `:313` and `:347`, which are *not* controls). **Add the missing derived guard** asserting zero `class="card"` in the templates.
2. **AC#2 — `--card-bg`'s successor role stated explicitly.** State it as *control ground*: dark inputs (`:471`) and dark `th` (`:506`) survive; `.card`'s use (`:51`) dies; `tbody tr:hover` (`:177`) is decided in writing (§3b). Correct the AC's own count in the same edit — **4 references, 2 of them in the dark block**, not "three dark-mode rules". Consider adopting the token for the two hardcoded light control grounds (`#fff` at `:89`/`:111`).
3. **AC#3 — the papers-table column-header separation migrates to a rule weight.** A `--rule-section`-weight border under `<thead>` on **both** `table.papers` and `table.notebooks`. The premise measured now: light stripe `#f0f0f0` is **1.1081:1** on `--card-bg` / **1.0778:1** on `--bg`; dark `th` uses `var(--card-bg)` at **1.0948:1** separation. Both modes need the rule; the fill is optional and, per AC#2, permitted.
4. **AC#4 — read as a REGRESSION GUARD, not a task.** Light `--border` on `--bg` is **3.3123:1** today; `test_ui_contrast.py:348` already gates it and names m8 in its docstring. The AC's "1.342:1 today" is stale — record the correction. The *live* version of AC#4's concern is §4's finding that **no lighter tint of `--border` clears 3:1**, so the ladder cannot be graded by lightness.
5. **AC#5 — m7's type scale has shipped.** Confirmed: `ui-uplift-m6/m7/m9/m10` state.json all `"phase": "complete"`. No action beyond citing it.
6. **[Derived from the m10 carried risk, not in the roadmap ACs] Re-solve and re-register `--fg-muted`.** Light drops from 7.0148 (on `--card-bg`) to **6.8230** (on `--bg`), missing its own declared 7.00:1 AAA target while passing the 4.5 gate — the textbook silent regression. Two of its three consumers move; `.status-badge__remediation` does not. Invert the written refusal at `test_ui_contrast.py:167-173`.
7. **[Derived] Re-ground the registry and keep it honest.** 36 of 99 rows touch `--card-bg`; re-ground and **rename** the 13 that move, split the 6+6 control-ground rows by what actually sits under them, drop `light --border on th #f0f0f0` if the stripe goes, and re-base or defend `ROW_HOVER`. Regenerate `.claude/docs/ui-contrast-table.md`.

## Risks and open questions

1. **The row-hover re-ground fails SC 1.4.11 in light mode — 2.9533:1.** Re-basing `ROW_HOVER` from `--card-bg` to `--bg` pushes the registry's *tightest* pair under its floor, and the failing pair is the rule token in the milestone that makes rules load-bearing. Cheapest defensible answer: leave `app.css:177` on `var(--card-bg)` and argue a hovered row is a control surface — but that must be **written into the stylesheet**, not left as an unedited line that looks like an oversight.
2. **`tokens.css` has 2 lines of headroom and the split hatch is spent.** Three (or six) new `--rule-*` declarations plus this repo's mandatory derivation comments do not fit. Either raise the 200-line bound deliberately at `test_ui_m7_type_scale.py:431` (a single-file edit, unlike the app.css trio) or author the ladder as thickness/style over one existing colour token. Decide this **first** — it is step one, not cleanup, exactly as it was in m7.
3. **`--rule-*` tokens will hard-fail the oklch guard if they are not pure colours.** `test_ui_contrast.py:514` iterates every raw token and skips only `--mono` / `--dur-*` / `--text-*` / `--tracking-*`. This is the m7 `--text-*` trap repeating verbatim. Adding `--rule-` to `NON_COLOUR_TOKEN_PREFIXES` is the mechanism, and `:498` then requires the prefix to match a real token.
4. **AC#2 and AC#3 pull in opposite directions on `th`.** AC#2 says `--card-bg` is the control ground *for table headers*; AC#3 says the header separation migrates to a rule weight. `test_ui_m5_create_remove_in_place.py:570` pins the dark fill. The resolution is "keep the fill **and** add the rule" — but an implementer reading AC#3 alone will delete the fill and break a test. Say this in the plan.
5. **The discovery's "60% row rule" is ambiguous and one reading is illegal.** Measured: 60/70/80% tints of `--border` toward the ground land at 1.96/2.22/2.53:1 — all under SC 1.4.11 in both modes. The graded ladder must be graded by thickness or style, not lightness, or the lighter weights need an explicit decorative declaration. The roadmap summary dropped the discovery's authored token names and the "one `.lede` treatment" element as well — recover both from `art-direction-scout-brief.md:163-184` and `synthesis.md:233-236` rather than re-inventing them.
