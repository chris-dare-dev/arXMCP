# UI contrast table — ui-uplift-m6

Every rendered foreground/background pair in the operator console's
stylesheet, with its measured WCAG 2.1 contrast ratio. Since `ui-uplift-m7`
that is two files: the token values are parsed from
`server/frontend/static/tokens.css` and the rules that combine them live in
`server/frontend/static/app.css`. It was the canonical record `ui-uplift-m8`
was written against: that milestone's rule ladder depended on the light-mode
`--border` token clearing 3:1 on `--bg` (it did not before m6 — it was
1.342:1), and **m8 has since shipped**, deleting `.card` and re-grounding
roughly a third of the registry from `--card-bg` onto `--bg`. Read the
`--card-bg` rows as the CONTROL layer now, not as a panel.

**Status:** GENERATED from the checked-in stylesheet by
`tests/test_ui_contrast.py`. Counts and failures are in the generated
Headline below — they are no longer written here, because they were wrong
here. Regenerate with:

```sh
python -m tests.test_ui_contrast --update
```

Three regions of this document are machine-written between
`<!-- BEGIN/END GENERATED … -->` markers — the Headline, the `--accent`
roles table, and the pair table. Do not hand-edit them.
`tests/test_ui_contrast.py::test_published_region_is_current` fails if any
drifts from the stylesheet, and
`::test_no_ratio_is_typed_outside_a_generated_region` fails if a new ratio
is typed anywhere else.

## Headline

<!-- BEGIN GENERATED HEADLINE -->

| | |
|---|---|
| Pairs measured | **101** (52 light, 49 dark) |
| Of those, gated / exempt | **87** gated, **14** exempt (each with its reason in the Site column) |
| Failures | **0** |
| Tightest gated pair | light `--rule-section under thead, on the hovered first row` — **3.040:1** against a 3.0:1 floor |
| Tightest gated text pair | dark `.status-badge--down text` — **4.832:1** against 4.5:1 |

<!-- END GENERATED HEADLINE -->

Previously-shipped failures closed by this milestone: **1** AA
(`.skip-link:focus-visible`, was 2.526:1) and **2** SC 1.4.11 (light
`--border`, was 1.342:1; `.status-badge--ops-warn` border, was 2.414:1).
Their current values are in the generated table below — the before-values
are historical and cannot drift, the after-values are computed.

**The prior contrast table in `.claude/references/frontend-uplift/arxmcp-design-system.md`
§4 covered 12 cells (6 tokens × 2 grounds). That partial inventory is how
three AA failures reached shipped code.** This table covers every pair that
actually renders, including hardcoded literals, `color-mix()`-derived
grounds, and non-text UI boundaries.

## Method

Ratios are **computed, never typed.** `tests/_ui_color.py` implements WCAG
2.1 relative luminance (`0.2126 R + 0.7152 G + 0.0722 B` over linearised
sRGB) and the OKLab↔linear-sRGB matrices needed to evaluate `oklch()` token
values and `color-mix(in oklab, …)` results. It parses the token tables
straight out of `tokens.css` — `TOKENS_CSS_PATH`, not `APP_CSS_PATH`, since
`ui-uplift-m7` split them — so no test duplicates a token value as a Python
string.

The implementation reproduces all nine independently-published numbers it
was checked against — the five in `arxmcp-design-system.md` §4, the
`1.342:1` figure asserted in `plans/ui-uplift/roadmap.yaml`, the two ratios
the m6 research briefs measured (`2.526:1`, `4.974:1`), and black-on-white
at exactly `21.000:1`.

Every ratio is computed from the **8-bit hex a browser actually paints**,
not from exact linear intermediates. Every authored `oklch()` token is
asserted in-gamut first: OKLCH covers P3 and beyond, and a browser
gamut-maps an out-of-gamut colour through CSS Color 4's chroma-reduction
algorithm before painting, so a naive clamp would not match what renders.

### What is *not* automated

The **list of which pairs exist** is hand-maintained (`PAIRS` in
`tests/test_ui_contrast.py`). Deriving it automatically would require a
headless browser walking the real DOM + CSSOM for every element's computed
`color`/`background-color`, which this repo's no-Node/no-heavy-dependency
posture rules out. So this list can still go stale if a future milestone
adds a selector and no matching row.

The honest claim is therefore: the *arithmetic* is 100% generated (large,
error-prone, and exactly what produced the historical failures — including
a comment in `app.css` that stated a ratio ~20% off), while the *inventory*
is small, reviewable, and reviewed.

## Floors applied

| Floor | Success criterion | Applies to |
|---|---|---|
| 4.5:1 | SC 1.4.3 Contrast (Minimum) | **every** text pair in this stylesheet |
| 3:1 | SC 1.4.11 Non-text Contrast | borders, focus rings, pill outlines |

**No row claims WCAG's large-text exception. That is a deliberate choice to
hold every text pair to one floor — NOT, as an earlier revision of this
paragraph claimed, because the exemption stopped applying.**

Until `ui-uplift-m7`, `header h1 a` was held to 3:1: `header h1` carried no
`font-size` and rode the UA `h1 { font-size: 2em }` = a fixed 32px. m7 put the
title on `clamp(1.5rem, 4vw + 0.5rem, 2.25rem)` and the row moved to the 4.5:1
text floor.

The rationale first written for that move was wrong, and ui-uplift-m7's
critique (M2/M9) caught it. It claimed the clamp made the rendered size
"viewport-dependent, so no single floor claim holds everywhere". It does not:
the clamp's **minimum is exactly 24px**, which *is* WCAG's large-text
threshold for non-bold text, and `header h1` carries no author `font-weight`
so it keeps UA bold and clears the ≥18.66px-bold branch as well. **The
exemption holds at every viewport, on both branches.** Keeping `LARGE` would
have been defensible.

The move to `TEXT` stands on its own merits — one floor for all text is
simpler to reason about, and the pair passes at 16.0:1 / 13.9:1 with an order
of magnitude of headroom, so nothing was traded for it. But it is a
preference, not a requirement, and this document should not have said
otherwise. The `LARGE` constant was removed with it: it was numerically
identical to `NONTEXT`, so an alias for a different success criterion at the
same number invited the SC column to be inferred from a float.

Sizes under the m7 scale, for the record: meta 11px (`th`, `.status-badge`,
and the badge's nested `.status-badge__remediation`), small 13px (labels,
captions, table cells, `pre.error`, every identifier in `code`/`time`, and —
since `ui-uplift-m10` — the Discover panel's `.discover-meta` and the
`.topic-category` / `.topic-description` pair), body 16px, section
20px (`h2` — a bare element rule since `ui-uplift-m8` deleted `.card`, and
`.discover-title`, which m10's rectify made an `<h3>` at the section step
rather than body weight-600), meta 11px also covering `.discover-abstract`,
which m10's rectify dropped to `--text-meta` to restore the meta/abstract
step — both corrected here by m8's critique (M3/M12), which found this
paragraph false on two counts,
title fluid 24→36px. Form controls
(`input`, `select`, `textarea`) and `.display-name` are on
`var(--text-body)` = **16px**, not the 13px an earlier revision of this list
claimed (critique M4). `h2` at 20px inherits UA bold and so *would* qualify for
the ≥18.7px-bold branch; it is held to 4.5:1 anyway, on the same one-floor
reasoning as the title. `th` at `font-weight:600`/11px is nowhere near the
threshold and is likewise held to 4.5:1.

## The family

One brand hue (**250°**, neutrals + accent) and one danger hue (**28°**,
danger + its error surface), with the **same construction in both modes**.
This replaces a stylesheet whose light neutrals were hand-picked and
perfectly achromatic (C = 0.0000) while its dark neutrals were a
self-labelled GitHub Primer clone at C 0.014–0.020, H 256–258° — two
different methods by two authors, stitched at one `@media` boundary.

Surfaces are chosen anchors; **every contrast-bearing token is the
binary-search solution for a target ratio against a named ground**, because
OKLCH `L` is perceptually uniform while WCAG contrast is sRGB relative
luminance — equal `L` steps do not give equal ratios.

| Token | Light | Solved for | Dark | Solved for |
|---|---|---|---|---|
| `--bg` | `oklch(98% 0.004 250)` | anchor | `oklch(16% 0.014 250)` | anchor |
| `--card-bg` | `oklch(99% 0.004 250)` | anchor (control) | `oklch(21% 0.016 250)` | anchor (control) |
| `--error-bg` | `oklch(96% 0.015 28)` | anchor | `oklch(24% 0.04 28)` | anchor |
| `--fg` | `oklch(22.842% 0.014 250)` | 16.0:1 on `--bg` | `oklch(89.089% 0.008 250)` | 14.0:1 on `--bg` |
| `--fg-muted` | `oklch(45.170% 0.014 250)` | 7.00:1 on `--bg` | `oklch(71.512% 0.008 250)` | 7.00:1 on `--card-bg`, kept |
| `--border` | `oklch(62.984% 0.018 250)` | 3.30:1 on `--bg` | `oklch(52.923% 0.02 250)` | 3.35:1 on `--card-bg` |
| `--accent` | `oklch(47.863% 0.115 250)` | 6.20:1 on `--bg` | `oklch(69.761% 0.13 250)` | 6.60:1 on `--card-bg` |
| `--danger` | `oklch(52.018% 0.165 28)` | 5.30:1 on `--error-bg` | `oklch(69.137% 0.17 28)` | 5.60:1 on `--error-bg` |
| `--rule-section` | `1px solid var(--border)` | structural — see below | *(inherits)* | structural |
| `--rule-row` | `1px solid` @ 80% toward `--bg` | **decorative, exempt** | *(inherits)* | decorative |
| `--rule-meta` | `1px dotted` @ 60% toward `--bg` | **decorative, exempt** | *(inherits)* | decorative |

The three `--rule-*` rows are `ui-uplift-m8`'s ladder and are **not colours**
— each is a whole `border-*` shorthand, which is why one declaration serves
both modes (`var(--border)` / `var(--bg)` substitute at use time) and why
`--rule-` is on `test_ui_contrast.py`'s `NON_COLOUR_TOKEN_PREFIXES`
allow-list. Their measured ratios are in the generated table above, not here.

Chroma stays low at the lightness extremes because the sRGB gamut allows
almost none there — max chroma at L=99% on hue 250 is 0.0049.

**`--fg-muted` (ui-uplift-m10) is the family's first addition since m6**, and
it follows the same construction rather than extending it: brand hue 250°, at
its own mode's `--fg` chroma (0.014 light, 0.008 dark), solved against a named
ground. Two choices in it are deliberate and worth reading.

**Its ground moved, and the move is the worked example of why this document
exists.** m10 solved it against `--card-bg` because every consumer —
`.discover-meta`, `.topic-description`, `.status-badge__remediation` — then
rendered inside `<section class="card">` or inside a status pill, and it
recorded a written *refusal* to register a `--bg` pair on the principle that
a registered pair which does not render is the same class of error as a
rendered pair that is missing. m10's own critique (M6) then flagged the
forward risk: `ui-uplift-m8` deletes the card, two of the three consumers
land on the canvas, and the light token would have measured **under its own
stated AAA target while still clearing the 4.5 registry floor** — a miss that
nothing in the suite would have reported. m8 re-solved the light value
against `--bg`, inverted that refusal into the `--bg` rows the registry now
carries, and added
`test_fg_muted_meets_its_own_stated_target_on_its_real_ground` so the next
such move is loud. Dark was deliberately **not** re-solved: it already clears
the target on `--bg`, and pulling a passing token toward its floor for
symmetry would cost contrast here and on all three dark pill grounds.
`.status-badge__remediation` did not move at all — it still grounds on the
pills, so those six rows are untouched.

The target is 7.00:1 (SC 1.4.6, AAA) rather than the
4.5:1 minimum, because that is the band the eleven hand-typed greys it exists
to replace already occupied, and the extra headroom is what lets one token
also clear the three status-pill grounds the remediation caption sits on
without a per-pill override.

**Binding-ground note.** In dark mode `--card-bg` is *lighter* than `--bg`,
so for a light foreground it is the tighter ground; dark `--border` and
`--accent` are solved against `--card-bg`, not `--bg`. In light mode the
relation inverts and `--bg` binds. Assuming the `--bg` pair covers both is
the specific mistake this table exists to prevent.

## `--accent`'s five roles, one token

The reason one token can carry all five is that the **on-accent text colour
is a mode-conditional companion**, not a fixed literal: white in light mode,
`var(--bg)` in dark. That collapses five potentially-conflicting constraints
into two per mode that push the same direction.

<!-- BEGIN GENERATED ROLES TABLE -->

| Role | Site | Light | Dark |
|---|---|---|---|
| 1 · button ground | `button, .button` | 6.553:1 | 7.190:1 |
| 1b · hover ground | `button:hover` | 4.981:1 | 8.260:1 |
| 2 · focus ring vs `--bg` | `:focus-visible` | 6.198:1 | 7.190:1 |
| 2 · focus ring vs `--card-bg` | `:focus-visible` | 6.372:1 | 6.568:1 |
| 3 · link | `.breadcrumb a` | 6.198:1 | 7.190:1 |
| 4 · skip-link ground | `.skip-link:focus-visible` | 6.553:1 | 7.190:1 |
| 5 · badge-flash border vs `--bg` | `@keyframes badge-flash` | 6.198:1 | 7.190:1 |
| 5 · badge-flash border vs `--card-bg` | `@keyframes badge-flash` | 6.372:1 | 6.568:1 |

<!-- END GENERATED ROLES TABLE -->

The on-accent text colour in light mode is `#fff`; in dark it is
`var(--bg)`.

**Role 5 was corrected during m6's rectify pass.** It previously animated
`background`, and the paragraph here described that as a *transient,
30%-opacity overlay animated over a status pill that is already
independently legible*. That was wrong on the facts: `@keyframes
badge-flash` animated the `background` property itself, so for the whole
400 ms the pill's opaque fill was **replaced**, not overlaid, and its text
sat on accent@30% composited over the page ground — 3.095:1 for dark
`--down`, with 6 of 8 pill texts under 4.5:1.

The flash now animates `border-color` to `--accent` instead. No text pair
moves at all, because every pill keeps its designed opaque ground, and the
role-5 pair is a plain non-text boundary that measures well over its floor
(rows above). Two alternatives were measured and rejected: dropping the
fill tint to 10% clears 4.5:1 but is close to invisible, and an inset
`box-shadow` overlay measures 3.044:1–3.902:1 and fails **all seven**
pills — worse than the behaviour it would have replaced.

## Known non-blocking observations

1. **The 8 status-pill literals are v1 scope and were left alone**, so they
   no longer track `--danger`/`--error-bg`. The dark `--down` pill in
   particular keeps the old Primer red `#f85149` while `--danger` has moved.
   This is a *pre-existing* divergence (its background `#3d1216` already
   differed from `--error-bg`) that m6 widens rather than introduces. All 8
   are measured below and all 8 pass.
2. **`.card .note` is GONE**, and with it the pair that was for two
   milestones the sweep's second-tightest gated text row (a historical
   5.025:1 that had lost headroom when light `--card-bg` stopped being pure
   white). `ui-uplift-m8` deleted the selector rather than re-homing it:
   `class="note"` is emitted by no template and no fragment builder in
   `server/`, so the rule, its two registry rows and its pinned dark-mode
   remap were all defending markup that does not exist.
4. **Light `--bg` → `--card-bg` separation halved** (critique L4), from a
   historical 1.062:1 to a value now pinned by
   `test_surface_separation_is_pinned_in_both_modes`. That guard survives
   `ui-uplift-m8` for a changed reason: the two surfaces no longer separate a
   *card* from the canvas — `--card-bg`'s successor role is the **control
   ground** (`th` in both modes, dark `input`/`textarea`, and the base of the
   `tbody tr:hover` tint) — but collapsing them to two identical hexes would
   still erase a distinction the sheet relies on.
6. **Two of the rule ladder's three rungs ship UNDER SC 1.4.11's 3:1 bar,
   deliberately** (`ui-uplift-m8`). `--border` was solved to exactly the
   floor, so no tint of it toward the ground can clear 3:1 — the ladder is
   graded by tone and the lower two rungs are declared **decorative**, which
   SC 1.4.11 exempts. That exemption is conditional, not a label: it holds
   only while something else carries each grouping, so `--rule-section` (full
   weight, clears the bar on every ground) carries every boundary a reader
   must perceive, and the tinted rungs draw only `<tr>`, `<li>` and `dl.meta`
   boundaries that element semantics and layout already establish. All six
   rows are registered EXEMPT with that justification inline.
5. **Two rendered state classes are composited, not flat** (critique
   H1/H3). `opacity` on an in-flight button and the badge flash both change
   the ground text is read against. Both are now in the registry: the
   in-flight focus ring is gated at 3:1 (which is why `opacity` is 0.7, not
   0.6), and the in-flight *label* is registered EXEMPT — `pointer-events:
   none` makes it an inactive user interface component, which SC 1.4.3
   exempts. The exemption is declared with its measured ratio in the table
   rather than left as an unlisted pair.
3. **`favicon.svg` cannot be tokenised.** SVG favicons render in browser-tab
   chrome and do not inherit page CSS custom properties, so its `fill` is
   kept in sync with light `--accent` by hand and asserted by
   `test_favicon_tracks_light_accent`.

<!-- BEGIN GENERATED CONTRAST TABLE -->

| # | Mode | Site / selector | Foreground | Background | Ratio | Floor | SC | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | light | body text | `#181d23` | `#f6f9fb` | **16.032:1** | 4.5:1 | 1.4.3 | PASS |
| 2 | light | th / input / textarea text on --card-bg [control ground] | `#181d23` | `#fafcfe` | **16.483:1** | 4.5:1 | 1.4.3 | PASS |
| 3 | light | header h1 a | `#181d23` | `#f6f9fb` | **16.032:1** | 4.5:1 | 1.4.3 | PASS |
| 4 | light | td text | `#181d23` | `#f6f9fb` | **16.032:1** | 4.5:1 | 1.4.3 | PASS |
| 5 | light | tbody tr:hover text | `#181d23` | `#edeff2` | **14.715:1** | 4.5:1 | 1.4.3 | PASS |
| 6 | light | .breadcrumb a link [accent role 3] | `#1f609b` | `#f6f9fb` | **6.198:1** | 4.5:1 | 1.4.3 | PASS |
| 7 | light | focus ring on --bg [accent role 2] | `#1f609b` | `#f6f9fb` | **6.198:1** | 3.0:1 | 1.4.11 | PASS |
| 8 | light | input/textarea focus ring on --card-bg [accent role 2, control ground] | `#1f609b` | `#fafcfe` | **6.372:1** | 3.0:1 | 1.4.11 | PASS |
| 9 | light | focus ring on tbody tr:hover [accent role 2] | `#1f609b` | `#edeff2` | **5.688:1** | 3.0:1 | 1.4.11 | PASS |
| 10 | light | pre.error text | `#b5352d` | `#fceeec` | **5.291:1** | 4.5:1 | 1.4.3 | PASS |
| 11 | light | button.danger focus ring on --bg | `#b5352d` | `#f6f9fb` | **5.656:1** | 3.0:1 | 1.4.11 | PASS |
| 12 | light | button.danger focus ring on tbody tr:hover | `#b5352d` | `#edeff2` | **5.191:1** | 3.0:1 | 1.4.11 | PASS |
| 13 | light | --rule-section on --bg — blocks, header, footer [AC#4 in light] | `#818a94` | `#f6f9fb` | **3.312:1** | 3.0:1 | 1.4.11 | PASS |
| 14 | light | --rule-section under thead, on --card-bg | `#818a94` | `#fafcfe` | **3.405:1** | 3.0:1 | 1.4.11 | PASS |
| 15 | light | --rule-row on --bg — tbody td, .discover-candidate [EXEMPT: decorative row rule, SC 1.4.11 aesthetic-purposes — its sites are <tr> and <li> boundaries an AT announces from the element, also carried by column alignment / 1.5rem padding under a per-item <h3>] | `#979fa8` | `#f6f9fb` | **2.533:1** | — | exempt | EXEMPT |
| 16 | light | --rule-row over the tbody tr:hover tint [EXEMPT: decorative row rule, SC 1.4.11 aesthetic-purposes — its sites are <tr> and <li> boundaries an AT announces from the element, also carried by column alignment / 1.5rem padding under a per-item <h3>] | `#979fa8` | `#edeff2` | **2.325:1** | — | exempt | EXEMPT |
| 17 | light | --rule-meta on --bg — dl.meta [EXEMPT: decorative dl.meta rule, SC 1.4.11 aesthetic-purposes — <dl> semantics and a two-column grid carry the dt/dd pairing, so deleting the rule changes no grouping] | `#aeb5bc` | `#f6f9fb` | **1.960:1** | — | exempt | EXEMPT |
| 18 | light | .discover-meta / .topic-description --fg-muted | `#50565d` | `#f6f9fb` | **7.018:1** | 4.5:1 | 1.4.3 | PASS |
| 19 | dark | body text | `#d7dbe0` | `#090e13` | **13.931:1** | 4.5:1 | 1.4.3 | PASS |
| 20 | dark | th / input / textarea text on --card-bg [control ground] | `#d7dbe0` | `#13191f` | **12.725:1** | 4.5:1 | 1.4.3 | PASS |
| 21 | dark | header h1 a | `#d7dbe0` | `#090e13` | **13.931:1** | 4.5:1 | 1.4.3 | PASS |
| 22 | dark | td text | `#d7dbe0` | `#090e13` | **13.931:1** | 4.5:1 | 1.4.3 | PASS |
| 23 | dark | tbody tr:hover text | `#d7dbe0` | `#1b2127` | **11.673:1** | 4.5:1 | 1.4.3 | PASS |
| 24 | dark | .breadcrumb a link [accent role 3] | `#59a2eb` | `#090e13` | **7.190:1** | 4.5:1 | 1.4.3 | PASS |
| 25 | dark | focus ring on --bg [accent role 2] | `#59a2eb` | `#090e13` | **7.190:1** | 3.0:1 | 1.4.11 | PASS |
| 26 | dark | input/textarea focus ring on --card-bg [accent role 2, control ground] | `#59a2eb` | `#13191f` | **6.568:1** | 3.0:1 | 1.4.11 | PASS |
| 27 | dark | focus ring on tbody tr:hover [accent role 2] | `#59a2eb` | `#1b2127` | **6.025:1** | 3.0:1 | 1.4.11 | PASS |
| 28 | dark | pre.error text | `#f36b5d` | `#301714` | **5.620:1** | 4.5:1 | 1.4.3 | PASS |
| 29 | dark | button.danger focus ring on --bg | `#f36b5d` | `#090e13` | **6.525:1** | 3.0:1 | 1.4.11 | PASS |
| 30 | dark | button.danger focus ring on tbody tr:hover | `#f36b5d` | `#1b2127` | **5.468:1** | 3.0:1 | 1.4.11 | PASS |
| 31 | dark | --rule-section on --bg — blocks, header, footer [AC#4 in light] | `#636d77` | `#090e13` | **3.676:1** | 3.0:1 | 1.4.11 | PASS |
| 32 | dark | --rule-section under thead, on --card-bg | `#636d77` | `#13191f` | **3.358:1** | 3.0:1 | 1.4.11 | PASS |
| 33 | dark | --rule-row on --bg — tbody td, .discover-candidate [EXEMPT: decorative row rule, SC 1.4.11 aesthetic-purposes — its sites are <tr> and <li> boundaries an AT announces from the element, also carried by column alignment / 1.5rem padding under a per-item <h3>] | `#4f5861` | `#090e13` | **2.677:1** | — | exempt | EXEMPT |
| 34 | dark | --rule-row over the tbody tr:hover tint [EXEMPT: decorative row rule, SC 1.4.11 aesthetic-purposes — its sites are <tr> and <li> boundaries an AT announces from the element, also carried by column alignment / 1.5rem padding under a per-item <h3>] | `#4f5861` | `#1b2127` | **2.243:1** | — | exempt | EXEMPT |
| 35 | dark | --rule-meta on --bg — dl.meta [EXEMPT: decorative dl.meta rule, SC 1.4.11 aesthetic-purposes — <dl> semantics and a two-column grid carry the dt/dd pairing, so deleting the rule changes no grouping] | `#3c444c` | `#090e13` | **1.959:1** | — | exempt | EXEMPT |
| 36 | dark | .discover-meta / .topic-description --fg-muted | `#9fa4a8` | `#090e13` | **7.704:1** | 4.5:1 | 1.4.3 | PASS |
| 37 | light | button/.button text [accent role 1] | `#ffffff` | `#1f609b` | **6.553:1** | 4.5:1 | 1.4.3 | PASS |
| 38 | light | button:hover text | `#ffffff` | `#3d73a8` | **4.981:1** | 4.5:1 | 1.4.3 | PASS |
| 39 | light | button.danger text | `#ffffff` | `#b5352d` | **5.980:1** | 4.5:1 | 1.4.3 | PASS |
| 40 | light | .skip-link:focus-visible text [accent role 4] | `#ffffff` | `#1f609b` | **6.553:1** | 4.5:1 | 1.4.3 | PASS |
| 41 | dark | button/.button text [accent role 1] | `#090e13` | `#59a2eb` | **7.190:1** | 4.5:1 | 1.4.3 | PASS |
| 42 | dark | button:hover text | `#090e13` | `#6eaeee` | **8.260:1** | 4.5:1 | 1.4.3 | PASS |
| 43 | dark | button.danger text | `#090e13` | `#f36b5d` | **6.525:1** | 4.5:1 | 1.4.3 | PASS |
| 44 | dark | .skip-link:focus-visible text [accent role 4] | `#090e13` | `#59a2eb` | **7.190:1** | 4.5:1 | 1.4.3 | PASS |
| 45 | light | header .subtitle #555 | `#555555` | `#f6f9fb` | **7.051:1** | 4.5:1 | 1.4.3 | PASS |
| 46 | light | footer #666 | `#666666` | `#f6f9fb` | **5.431:1** | 4.5:1 | 1.4.3 | PASS |
| 47 | light | footer a #666 | `#666666` | `#f6f9fb` | **5.431:1** | 4.5:1 | 1.4.3 | PASS |
| 48 | light | .hint #555 | `#555555` | `#f6f9fb` | **7.051:1** | 4.5:1 | 1.4.3 | PASS |
| 49 | light | .empty #666 | `#666666` | `#f6f9fb` | **5.431:1** | 4.5:1 | 1.4.3 | PASS |
| 50 | light | .display-name #444 | `#444444` | `#f6f9fb` | **9.212:1** | 4.5:1 | 1.4.3 | PASS |
| 51 | light | dl.meta dt #555 | `#555555` | `#f6f9fb` | **7.051:1** | 4.5:1 | 1.4.3 | PASS |
| 52 | dark | header .subtitle / footer / footer a #b3b9c0 | `#b3b9c0` | `#090e13` | **9.796:1** | 4.5:1 | 1.4.3 | PASS |
| 53 | dark | .hint / dl.meta dt #b3b9c0 | `#b3b9c0` | `#090e13` | **9.796:1** | 4.5:1 | 1.4.3 | PASS |
| 54 | dark | .empty #9ba1a8 | `#9ba1a8` | `#090e13` | **7.434:1** | 4.5:1 | 1.4.3 | PASS |
| 55 | dark | .display-name #c9d1d9 | `#c9d1d9` | `#090e13` | **12.553:1** | 4.5:1 | 1.4.3 | PASS |
| 56 | light | .status-badge--ok text | `#15682d` | `#e6f4ea` | **6.063:1** | 4.5:1 | 1.4.3 | PASS |
| 57 | light | .status-badge--ok border on --bg | `#15682d` | `#f6f9fb` | **6.512:1** | 3.0:1 | 1.4.11 | PASS |
| 58 | light | .status-badge--warn text | `#8a5a00` | `#fdf3e2` | **5.389:1** | 4.5:1 | 1.4.3 | PASS |
| 59 | light | .status-badge--warn border on --bg | `#8a5a00` | `#f6f9fb` | **5.606:1** | 3.0:1 | 1.4.11 | PASS |
| 60 | light | .status-badge__remediation on --warn | `#50565d` | `#fdf3e2` | **6.747:1** | 4.5:1 | 1.4.3 | PASS |
| 61 | light | .status-badge--ops-warn text | `#475569` | `#eef2f7` | **6.740:1** | 4.5:1 | 1.4.3 | PASS |
| 62 | light | .status-badge--ops-warn border on --bg | `#475569` | `#f6f9fb` | **7.167:1** | 3.0:1 | 1.4.11 | PASS |
| 63 | light | .status-badge__remediation on --ops-warn | `#50565d` | `#eef2f7` | **6.600:1** | 4.5:1 | 1.4.3 | PASS |
| 64 | light | .status-badge--down text (tokens) | `#b5352d` | `#fceeec` | **5.291:1** | 4.5:1 | 1.4.3 | PASS |
| 65 | light | .status-badge--down border on --bg (token) | `#b5352d` | `#f6f9fb` | **5.656:1** | 3.0:1 | 1.4.11 | PASS |
| 66 | light | .status-badge__remediation on --down | `#50565d` | `#fceeec` | **6.565:1** | 4.5:1 | 1.4.3 | PASS |
| 67 | dark | .status-badge--ok text | `#3fb950` | `#0d2818` | **6.198:1** | 4.5:1 | 1.4.3 | PASS |
| 68 | dark | .status-badge--ok border on --bg | `#3fb950` | `#090e13` | **7.627:1** | 3.0:1 | 1.4.11 | PASS |
| 69 | dark | .status-badge--warn text | `#d29922` | `#3d2a07` | **5.428:1** | 4.5:1 | 1.4.3 | PASS |
| 70 | dark | .status-badge--warn border on --bg | `#d29922` | `#090e13` | **7.676:1** | 3.0:1 | 1.4.11 | PASS |
| 71 | dark | .status-badge__remediation on --warn | `#9fa4a8` | `#3d2a07` | **5.448:1** | 4.5:1 | 1.4.3 | PASS |
| 72 | dark | .status-badge--ops-warn text | `#8b949e` | `#1c2230` | **5.169:1** | 4.5:1 | 1.4.3 | PASS |
| 73 | dark | .status-badge--ops-warn border on --bg | `#8b949e` | `#090e13` | **6.299:1** | 3.0:1 | 1.4.11 | PASS |
| 74 | dark | .status-badge__remediation on --ops-warn | `#9fa4a8` | `#1c2230` | **6.321:1** | 4.5:1 | 1.4.3 | PASS |
| 75 | dark | .status-badge--down text | `#f85149` | `#3d1216` | **4.832:1** | 4.5:1 | 1.4.3 | PASS |
| 76 | dark | .status-badge--down border on --bg | `#f85149` | `#090e13` | **5.780:1** | 3.0:1 | 1.4.11 | PASS |
| 77 | dark | .status-badge__remediation on --down | `#9fa4a8` | `#3d1216` | **6.440:1** | 4.5:1 | 1.4.3 | PASS |
| 78 | light | .status-badge base border on --bg | `#818a94` | `#f6f9fb` | **3.312:1** | 3.0:1 | 1.4.11 | PASS |
| 79 | dark | .status-badge base border on --bg | `#636d77` | `#090e13` | **3.676:1** | 3.0:1 | 1.4.11 | PASS |
| 80 | light | in-flight accent button label on --bg [EXEMPT: inactive component, SC 1.4.3 — pointer-events:none] | `#fcfdfe` | `#608eb8` | **3.403:1** | — | exempt | EXEMPT |
| 81 | light | in-flight accent focus ring on --bg | `#608eb8` | `#f6f9fb` | **3.278:1** | 3.0:1 | 1.4.11 | PASS |
| 82 | light | in-flight danger button label on --bg [EXEMPT: inactive component, SC 1.4.3 — pointer-events:none] | `#fcfdfe` | `#c8706b` | **3.445:1** | — | exempt | EXEMPT |
| 83 | light | in-flight danger focus ring on --bg | `#c8706b` | `#f6f9fb` | **3.318:1** | 3.0:1 | 1.4.11 | PASS |
| 84 | light | in-flight accent button label on tbody tr:hover [EXEMPT: inactive component, SC 1.4.3 — pointer-events:none] | `#fafafb` | `#5d8bb5` | **3.456:1** | — | exempt | EXEMPT |
| 85 | light | in-flight accent focus ring on tbody tr:hover | `#5d8bb5` | `#edeff2` | **3.129:1** | 3.0:1 | 1.4.11 | PASS |
| 86 | light | in-flight danger button label on tbody tr:hover [EXEMPT: inactive component, SC 1.4.3 — pointer-events:none] | `#fafafb` | `#c66d68` | **3.478:1** | — | exempt | EXEMPT |
| 87 | light | in-flight danger focus ring on tbody tr:hover | `#c66d68` | `#edeff2` | **3.149:1** | 3.0:1 | 1.4.11 | PASS |
| 88 | dark | in-flight accent button label on --bg [EXEMPT: inactive component, SC 1.4.3 — pointer-events:none] | `#090e13` | `#4176aa` | **4.057:1** | — | exempt | EXEMPT |
| 89 | dark | in-flight accent focus ring on --bg | `#4176aa` | `#090e13` | **4.057:1** | 3.0:1 | 1.4.11 | PASS |
| 90 | dark | in-flight danger button label on --bg [EXEMPT: inactive component, SC 1.4.3 — pointer-events:none] | `#090e13` | `#ad4f47` | **3.678:1** | — | exempt | EXEMPT |
| 91 | dark | in-flight danger focus ring on --bg | `#ad4f47` | `#090e13` | **3.678:1** | 3.0:1 | 1.4.11 | PASS |
| 92 | dark | in-flight accent button label on tbody tr:hover [EXEMPT: inactive component, SC 1.4.3 — pointer-events:none] | `#0e1419` | `#467bb0` | **4.167:1** | — | exempt | EXEMPT |
| 93 | dark | in-flight accent focus ring on tbody tr:hover | `#467bb0` | `#1b2127` | **3.650:1** | 3.0:1 | 1.4.11 | PASS |
| 94 | dark | in-flight danger button label on tbody tr:hover [EXEMPT: inactive component, SC 1.4.3 — pointer-events:none] | `#0e1419` | `#b2554d` | **3.796:1** | — | exempt | EXEMPT |
| 95 | dark | in-flight danger focus ring on tbody tr:hover | `#b2554d` | `#1b2127` | **3.324:1** | 3.0:1 | 1.4.11 | PASS |
| 96 | light | .status-badge.htmx-settling flash border on --bg [accent role 5] | `#1f609b` | `#f6f9fb` | **6.198:1** | 3.0:1 | 1.4.11 | PASS |
| 97 | light | .status-badge.htmx-settling flash border on --card-bg [accent role 5] | `#1f609b` | `#fafcfe` | **6.372:1** | 3.0:1 | 1.4.11 | PASS |
| 98 | dark | .status-badge.htmx-settling flash border on --bg [accent role 5] | `#59a2eb` | `#090e13` | **7.190:1** | 3.0:1 | 1.4.11 | PASS |
| 99 | dark | .status-badge.htmx-settling flash border on --card-bg [accent role 5] | `#59a2eb` | `#13191f` | **6.568:1** | 3.0:1 | 1.4.11 | PASS |
| 100 | light | --rule-section under thead, on the hovered first row | `#818a94` | `#edeff2` | **3.040:1** | 3.0:1 | 1.4.11 | PASS |
| 101 | dark | --rule-section under thead, on the hovered first row | `#636d77` | `#1b2127` | **3.080:1** | 3.0:1 | 1.4.11 | PASS |

<!-- END GENERATED CONTRAST TABLE -->

## Cross-references

- `server/frontend/static/tokens.css` — the token blocks and their per-token
  derivation rationale (both `:root` blocks moved here in `ui-uplift-m7`)
- `server/frontend/static/app.css` — the rules that consume those tokens
- `tests/_ui_color.py` — the colour math and stylesheet parser
- `tests/test_ui_contrast.py` — the gate, the pair registry, and this file's generator
- `.claude/references/frontend-uplift/arxmcp-design-system.md` §4 — the superseded 12-cell table
