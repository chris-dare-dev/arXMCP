---
milestone_id: "ui-uplift-m8"
phase: "implement"
implementation_base: "590acd52577d295fead21b202769623eb75b5f4f"
branch: "worktree-agent-afb6414427acaf6c8"
external_writes_required:
  - "git push origin main"
scope: "EXCEEDED — see implement/scope-exceeded.md"
files_touched: 11
diff_total: "1068 insertions / 317 deletions"
diff_generated_share: "194 of those lines are the regenerated contrast table"
---

# Implement synthesis — ui-uplift-m8 (UPL-2)

`.card` is deleted from the product. Nine `<section class="card">` boxes, the
rule, its five descendant compounds and its three dark-mode remaps are gone;
structure is now the three-rung ladder the 2026q3 discovery authored by name,
over a doubled vertical rhythm.

## Built

### AC#1 — no `.card` primitive remains, and that is now falsifiable

- All **9** markup sites converted (2 in `index.html`, 7 in
  `notebook_detail.html`) — the roadmap said 10; `notebook_detail.html:315`
  was a comment, not a site.
- Deleted from `app.css`: the `.card` rule (including the file's **only**
  `border-radius: 6px` on structure) plus `.card h2` / `.hint` / `.note` /
  `.empty` / `.display-name`. The four surviving descendants re-homed as bare
  selectors; the three dark remaps de-prefixed.
- **`.card .note` deleted outright, not re-homed.** `class="note"` is emitted
  by zero templates and zero fragment builders, so the rule, its 2 registry
  rows and its pinned dark remap were all defending markup that never existed.
- **The guard AC#1 never had** ships as `tests/test_ui_m8_rule_ladder.py`
  (new). Four independent checks: no template `class="card"`, no fragment
  builder emitting it, no stylesheet rule declaring it, and no
  `border-radius` on a non-control. All read comment-stripped CSS and
  comment-stripped markup — the m10 rectify lesson, and it bites harder here
  because the m8 comments necessarily *contain* the string `.card`.
- Radius audit: `pre.error` **squared** (a structural feedback panel).
  `.status-badge` and the spinner are enumerated as the two documented
  exceptions in the guard, so a third cannot be added silently.

### AC#2 — `--card-bg`'s successor role, stated and enforced

Stated in `tokens.css` at the token: **control ground**, not panel ground —
`th` in both modes, `input`/`textarea` in dark, and the base of the
`tbody tr:hover` tint. The AC's "three dark-mode rules" is corrected in place:
**3 CSS rules of which only 1 is dark-only, plus 3 dark TOKEN derivations**
(`--border`, `--accent`, and — until this milestone — `--fg-muted`) that name
it as their solved ground.

`TestCardBgSuccessorRole` enforces it: any `var(--card-bg)` consumer outside
the three named roles fails, so the primitive cannot come back under another
name.

### AC#3 — the header separation migrates to a rule weight

`th, td { border-bottom: 1px solid var(--border) }` gave the header and every
data row the *same* weight, leaving the header boundary carried by a fill at
**1.1081:1** (light) / **1.0948:1** (dark). Split into `thead th` at
`--rule-section` and `tbody td` at `--rule-row`.

**AC#2 ∧ AC#3, not AC#3 alone.** The fill survives *and* the rule is added.
Light `th` moved off the hardcoded `#f0f0f0` onto `var(--card-bg)`, which let
the dark redeclaration be deleted as dead code — the two modes can no longer
disagree about this surface.

### AC#4 — treated as a regression guard

Already satisfied: light `--border` on `--bg` measures **3.3123:1**, not the
"1.342:1 today" the AC claims. `test_light_border_clears_three_to_one_on_bg`
already gated it. The live version of AC#4's concern is D1 below.

### AC#5 — verified, not re-done

m6/m7/m9/m10 all `phase: complete`; `tokens.css` carries both the OKLCH family
and the m7 type scale.

## Owner decision D1 — graded by lightness, and the exemption was MADE true

Three tokens, **authored names recovered from discovery**
(`art-direction-scout-brief.md:176-177`, `artifacts/synthesis.md:234`; the
roadmap has zero `--rule-` occurrences — the third milestone running with this
drop-shape).

| rung | value | light | dark | status |
|---|---|---|---|---|
| `--rule-section` | `1px solid var(--border)` | **3.3123** on `--bg`, **3.4054** on `--card-bg` | **3.6762** / **3.3580** | GATED, clears 3:1 everywhere |
| `--rule-row` | `1px solid` @ 80% toward `--bg` | **2.5332** on `--bg`, **2.3251** on hover | **2.6766** / **2.2428** | EXEMPT, decorative |
| `--rule-meta` | `1px dotted` @ 60% toward `--bg` | **1.9596** | **1.9591** | EXEMPT, decorative |

**Authoring choice: whole `border-*` shorthands, not colours.** The tints are
`color-mix(… var(--border) N%, var(--bg))`, and custom properties substitute
at *use* time, so **one declaration per rung serves both colour schemes** —
three declarations, not six. `--rule-` was added to
`NON_COLOUR_TOKEN_PREFIXES` (`test_ui_contrast.py`) deliberately, as an
allow-list entry; this is the m7 `--text-*` trap and it was hit and closed.

**The exemption audit — every tinted site has a second, non-visual cue:**

| site | rung | what else carries the grouping |
|---|---|---|
| between the 9 top-level blocks | **`--rule-section`** | *nothing else does* — hence full weight |
| under `<thead>` | **`--rule-section`** | *nothing else does* — a reader who cannot see it reads a label as data |
| `header` / `footer` edges | **`--rule-section`** | landmark elements, but the rule is the visible page frame |
| `tbody td` | `--rule-row` | `<tr>` announced by the AT; column alignment; the hover tint |
| `.discover-candidate` | `--rule-row` | `<li>` in a `<ul>`; a per-item `<h3>`; 1.5rem combined padding |
| `dl.meta` rows | `--rule-meta` | `<dl>` dt/dd semantics; a two-column grid |

Written per-token into `tokens.css` **with the measured ratios beside each
claim**, and registered in the contrast registry with the `EXEMPT` sentinel
plus an inline `[EXEMPT: …]` justification (6 new rows).
`test_ui_m8_rule_ladder.py` asserts both directions: the section rung *clears*
3:1 on every ground, and the tinted rungs are *genuinely under* it — a tint
that crept back over 3:1 would mean the ladder had collapsed onto one weight
while still claiming to be graded.

Rejected and recorded: grading by **thickness**. Butterick's usable range is
~0.67–1.33px — the whole budget for three rungs — and a sub-pixel border
rounds per device-pixel-ratio, so two rungs would be indistinguishable at DPR 1.

The discovery's ambiguous "row rule (60%)" is read as **the depth of the
ladder**, not as the row rung: row lands at 80%, meta takes the authored 60%
*and* the authored dotted texture, so the ladder is monotone in tone and its
last step is also a step in texture.

## Owner decision D2 — `<section>` vs `<div>`, decided per site

**The criterion.** An unnamed `<section>` exposes no `region` landmark — it is
semantically a `<div>` — so neither choice moves the accessibility tree today;
what it records is authorial intent. `<section>` survives where the block is a
self-contained **content region** a reader would want to reach; `<div>` where
the box only wrapped a **single job form**, which its own `<form>` already
delimits.

| # | site | element | why |
|---|---|---|---|
| 1 | `index.html` Create notebook | **div** | one create form |
| 2 | `index.html` Existing notebooks | **section** | the page's focal content — the notebook inventory |
| 3 | detail `<code>{slug}</code>` | **section** | the record itself: identity, name, metadata, delete |
| 4 | detail Topic & discovery | **div** | a form and its readback |
| 5 | detail Discover papers | **div** | a job form plus a transient result panel — the borderline case; the results are content, but they are job output |
| 6 | detail Add paper by URL | **div** | one add form |
| 7 | detail Upload ar5iv HTML | **div** | one upload form |
| 8 | detail Ingest | **div** | a job form plus its status target |
| 9 | detail Papers in this notebook | **section** | the page's focal content — the corpus |

**3 sections, 6 divs.** Heading relationships checked and guarded: every one of
the 9 blocks still opens with its `<h2>` on the next line
(`test_every_block_still_opens_with_its_heading`), which is what actually
carries navigation — the HTML5 outline algorithm was never implemented in any
browser, so heading rank *is* the outline.

**Deliberately refused:** adding `aria-labelledby` to promote these to real
landmarks. That would mint 9 regions on one page; over-populating a page with
landmarks reduces their usefulness, and heading hierarchy is the recommended
answer. Guarded by `test_no_block_was_promoted_to_a_landmark`.

The mixed elements are why the ladder selector is
`main > :where(section, div) + :where(section, div)` — `:where()` holds it at
(0,0,0) so deleting `.card` cannot re-open the specificity of the five
compounds it dropped to (0,0,1), and `main >` keeps `<nav class="breadcrumb">`
out of the ladder.

## The two silent regressions — both handled deliberately

**1. `ROW_HOVER` stays on `var(--card-bg)`, and the argument is in the
stylesheet.** A hovered row is a control surface — the pointer's current
target, and the buttons in it are why the tint exists — so it classifies with
`th` and the dark inputs under the new role.

**Correction to the research on this point, recorded rather than repeated.**
Both briefs justified keeping it by the SC 1.4.11 cliff (re-basing on `--bg`
drops light `--border` on this ground from 3.0401 to **2.9533**). **That cliff
is retired by m8's own design**: the row rule dropped to `--rule-row`, so *no
full-weight rule is drawn against the hover ground at all*. The reason is now
the role classification, and the stylesheet says exactly that so a later reader
does not re-derive an argument that no longer holds.

**2. `--fg-muted` re-solved against its new ground.** Two of three consumers
(`.discover-meta`, `.topic-description`) moved to `--bg`; the third
(`.status-badge__remediation`) did not move — it grounds on the status pills,
so its 6 rows are untouched.

- **Light: re-solved.** `oklch(45.706%)` → **`oklch(45.170% 0.014 250)`**, the
  binary-search solution for 7.00:1 on `--bg` (**7.0176** measured; the old
  value measured **6.8230** there — under its own AAA target, over the 4.5
  gate, so nothing would have failed). It also *improves* all three light pill
  pairs.
- **Dark: deliberately NOT re-solved.** It measures **7.7040** on `--bg`,
  already over target; pulling a passing token toward its floor for symmetry
  would cost contrast here and on all three dark pill grounds. Stated in the
  token comment.
- m10's **written refusal** to register a `--bg` pair is *inverted*, not
  merely edited — the comment is the artifact a future reader trusts.
- New guard `test_fg_muted_meets_its_own_stated_target_on_its_real_ground`
  makes the next such move loud. This is the whole point: the registry gates
  at 4.5, so a token that stops meeting its *own* 7.00 derivation passes every
  row.

## Registry and artifact

**99 pairs before, 99 after** — deliberately, not coincidentally. 8 rows
retired, 8 added:

- **Retired:** 4 duplicate `--fg`-on-`--card-bg` rows consolidated into one
  per-mode "control ground" row; `.card .note` (light); `--border on th
  #f0f0f0` (the literal is gone); `--border on tbody tr:hover` ×2 (no
  full-weight rule renders there any more — m6's critique-M2 intent survives
  because `--border`'s two binding grounds are still both enumerated).
- **Added:** `--rule-row` on `--bg` and on the hover tint, `--rule-meta` on
  `--bg` (6 EXEMPT rows), plus `focus ring on tbody tr:hover` ×2 — a ground m6
  never registered, and now the tightest accent-ring pair in the sweep.
- **Re-grounded AND renamed:** the 7 `.card .*` grey rows, `td text`,
  `.discover-meta / .topic-description`. A row named for a selector that no
  longer exists is the registry rotting in place, and its site string ships
  into the published artifact.
- `button.danger focus ring on --card-bg` → `on tbody tr:hover`; the in-flight
  sweep's second ground moved from `--card-bg` to the hover tint (the Remove
  button is in-flight exactly there, and nothing registered it).

Artifact regenerated with `python -m tests.test_ui_contrast --update`. **The
hand-written prose outside the generated markers was audited and updated** —
it went stale in m6, m7, m7-rectify and m10. Five regions fixed: the header's
"consulted by ui-uplift-m8" framing, the m7 sizes paragraph (`.card h2`,
`.card .display-name`), the token-family table (new `--fg-muted` value + 3
`--rule-*` rows), the `--fg-muted` ground paragraph (refusal inverted), and
observations 2 and 4. New observation 6 records the sub-3:1 rungs.

New headline: 99 pairs (51 light / 48 dark), 85 gated / 14 exempt, **0
failures**, tightest gated pair light `in-flight accent focus ring on tbody
tr:hover` at 3.129:1.

## The line-budget decision — made first, as step one

| file | before | after | cap | action |
|---|---|---|---|---|
| `tokens.css` | 198 | **278** | 200 → **290** | **RAISED** (first raise since m7 set it) |
| `app.css` | 595 | **599** | 600 | **NOT raised** |

**`tokens.css` raised, with merits recorded at the assertion.** The three
`--rule-*` tokens plus this repo's mandatory derivation comments do not fit 2
lines of headroom, and the m7 split hatch is spent. The derivation is
unusually load-bearing here: two rungs ship *under* SC 1.4.11 and do so only
because they are declared decorative, and that declaration is conditional — so
the argument **is** the deliverable.

**`app.css` NOT raised — m10's precedent followed.** m10 refused a fourth
raise after the adversary asked whether the discipline is real, and trimmed
instead. Same here: the ladder's grading, exemption and rejected-alternative
prose lives **once** in `tokens.css` rather than being repeated at each of the
four rule sites, and the app.css comments point there.

**Honest caveat: that is 1 line of headroom, and the file did not shrink.** The
premise that deleting a primitive should shrink the sheet did not hold — ~29
lines of rules were deleted and ~5 added, but this repo mandates written
rationale for five decisions (deletion, ladder, re-role, `th`, radius) and that
prose is the net growth. Lowering the cap was therefore not available.
**The rectify pass has 1 line to work with**; if it needs more, the honest
options are trimming m8's own prose further or raising deliberately — not
compressing other milestones' rationale, which I did only in three places where
m8 made it factually stale.

## Files touched

| path | role |
|---|---|
| `server/frontend/static/tokens.css` | `--rule-*` family (3 tokens); `--fg-muted` light re-solved; `--card-bg` re-roled |
| `server/frontend/static/app.css` | primitive deleted; ladder installed; `th` migrated; radius squared |
| `server/frontend/templates/index.html` | 2 sites; D2 rationale |
| `server/frontend/templates/notebook_detail.html` | 7 sites; D2 rationale |
| `tests/test_ui_m8_rule_ladder.py` | **NEW** — AC#1's missing guard + the ladder / D2 / AC#2 guards |
| `tests/test_ui_contrast.py` | registry re-grounded; `--rule-` allow-listed; AAA guard |
| `tests/test_ui_m7_type_scale.py` | `.card h2` guard rewritten to its intent; tokens.css bound 200→290 |
| `tests/test_ui_m5_create_remove_in_place.py` | `th` guard rewritten to its intent |
| `tests/test_ui_m3_dark_and_htmx_feedback.py` | dark-remap selector pins de-prefixed |
| `tests/test_ui_class_css_coverage.py` | `M10_STYLED` + `hint`/`empty`/`display-name` (BAN-R2) |
| `.claude/docs/ui-contrast-table.md` | regenerated + 5 stale prose regions fixed |

**Every one of the four named guards was fixed by asserting its ORIGINAL
INTENT, never by deletion** — the m6/m7/m10 rectify pattern. One was renamed
because its mechanism changed
(`test_th_dark_background_redeclared` → `test_th_background_is_the_token_in_every_mode`);
`test_card_h2_is_edited_not_shadowed` kept its name and now checks both that
the size sits on the winning rule *and* that nothing outranks it, so dropping
to a bare-`h2` match cannot silently re-admit the shadowing bug.

## Deferred

- **`.lede` / the single focal region** (`artifacts/synthesis.md:236`). Named
  inside UPL-2's description but catalogued separately as UPL-5, and BAN-5
  ("no focal element") is already recorded as open in `tokens.css` against
  `ui-uplift-m12`. Not shipped; the ladder ranks groups by rule weight, not by
  type. **This is the open question the research flagged and it is answered
  "m12", explicitly rather than by omission.**
- **Light `input`/`textarea` stay on `#fff`** rather than adopting
  `var(--card-bg)`. AC#2 lists this as a candidate, not a requirement; moving
  it would make the dark override pinned at
  `test_ui_m3_dark_and_htmx_feedback.py:185` dead code while that guard still
  asserts it. Recorded rather than silently done.
- **Two pre-existing over-registrations left alone**, both predating m8: the
  badge-flash rows on `--card-bg`, and `_accent_role_checks`' "role 5 vs
  `--card-bg`". The badge renders in the footer only and never sat on a card,
  so these were wrong *before* this milestone; touching them cascades into the
  generated roles table.
- **`--fg-muted` is still a twelfth grey**, not a consolidation (m10's
  recorded debt). The eleven hand-typed greys moved *ground* with the card,
  not *value*.

## Test deltas

- **Added:** `tests/test_ui_m8_rule_ladder.py` — 5 classes, 20 tests.
- **Added:** `test_ui_contrast.py::test_fg_muted_meets_its_own_stated_target_on_its_real_ground`.
- **Rewritten to intent:** `test_card_h2_is_edited_not_shadowed`,
  `test_th_dark_background_redeclared` → `test_th_background_is_the_token_in_every_mode`,
  the m3 dark-remap selector list, `M10_STYLED`.
- **Bounds moved:** `tokens.css` 200 → 290 (single file, merits recorded).
  `app.css` 600 unchanged in all three lockstep files.

## Check gate results

- `ruff check .`: **PASS** (clean)
- `pytest`: **PASS relative to baseline — zero new failures**
- `git status --porcelain`: clean after commit

**Baseline correction.** The dispatch brief states 8 pre-existing failures.
**In this worktree the baseline is 7**, measured at `590acd5` before any edit:
6 × `test_latexml_sandbox.py` (macOS `sandbox-exec`) and 1 ×
`test_arxiv_fetch.py::TestParseWithLatexml::test_win32_bat_invoked_via_perl`.
`test_tools_all.py::…::test_cite_neighbors_wired` **passes here** — a git
worktree has no `var/` tree at all, so `graph_status` reports `absent`, which
is exactly what the test expects. The 8th failure is a property of the main
checkout's bootstrapped-but-empty `var/arxmcp/index/kuzu`, not of the code —
which corroborates m10's correction that it is local state, not a network
flake. Post-change run: the same 7, byte-identical list.

## Not verified in a browser

`create_app()` will not boot without an ingested corpus, so every check here is
source-level. **That matters more than usual for this milestone**: the
deliverable is a *visual* re-composition — nine boxes replaced by rhythm and
three rule weights — and nothing in this pass looked at a rendered page. The
rhythm values (2rem above / 2rem below the rule, replacing `1rem` padding +
`1rem` margin) are reasoned from the sources, not measured on screen, and the
"does it read as a spreadsheet?" question the art direction raises is exactly
the one source-level checks cannot answer.

## external_writes_required

- `git push origin main` — **NOT performed.** Declared only; push is
  per-event authorization (CLAUDE.md 4.4).

## Branching note

CLAUDE.md 4.1 says all work lands on `main`. **That is mechanically
unavailable from this worktree**: `git checkout main` fails with
`fatal: 'main' is already used by worktree at /Users/chris.dare/Personal/SourceCode/arXMCP`.
Commits are on **`worktree-agent-afb6414427acaf6c8`** for the orchestrator to
rebase and fast-forward. Nothing was forced. `main` may have moved (the
orchestrator commits research notes), so a rebase rather than a fast-forward
may be required.

Note also: this milestone's `research/` notes are untracked in the main
checkout and therefore absent from this worktree — they were read from the
main tree directly. This synthesis is committed on the worktree branch so it
travels with the code.
