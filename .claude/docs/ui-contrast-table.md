# UI contrast table — ui-uplift-m6

Every rendered foreground/background pair in the operator console's
stylesheet (`server/frontend/static/app.css`), with its measured WCAG 2.1
contrast ratio. This document is the canonical record consulted by
`ui-uplift-m8`, whose rule-ladder depends on the light-mode `--border`
token clearing 3:1 against `--bg` (it did not before m6 — it was 1.342:1).

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
| Pairs measured | **91** (48 light, 43 dark) |
| Of those, gated / exempt | **83** gated, **8** exempt (each with its reason in the Site column) |
| Failures | **0** |
| Tightest gated pair | light `--border on tbody tr:hover` — **3.040:1** against a 3.0:1 floor |
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
straight out of `app.css`, so no test duplicates a token value as a Python
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
| 4.5:1 | SC 1.4.3 Contrast (Minimum) | all text below 24px, or below 18.7px bold |
| 3:1 | SC 1.4.11 Non-text Contrast | borders, focus rings, pill outlines |
| 3:1 | SC 1.4.3 large-text exception | `header h1 a` only — it inherits the UA `h1` rule (2em **and** bold) |

Nothing else in this stylesheet reaches the large-text threshold: buttons
are 14px, badges 12px, table cells 14.4px, card hints/notes 12.8–14.4px.
`th` at `font-weight:600`/14.4px is far below the 18.7px bold threshold and
is held to the full 4.5:1.

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
| `--card-bg` | `oklch(99% 0.004 250)` | anchor | `oklch(21% 0.016 250)` | anchor |
| `--error-bg` | `oklch(96% 0.015 28)` | anchor | `oklch(24% 0.04 28)` | anchor |
| `--fg` | `oklch(22.842% 0.014 250)` | 16.0:1 on `--bg` | `oklch(89.089% 0.008 250)` | 14.0:1 on `--bg` |
| `--border` | `oklch(62.984% 0.018 250)` | 3.30:1 on `--bg` | `oklch(52.923% 0.02 250)` | 3.35:1 on `--card-bg` |
| `--accent` | `oklch(47.863% 0.115 250)` | 6.20:1 on `--bg` | `oklch(69.761% 0.13 250)` | 6.60:1 on `--card-bg` |
| `--danger` | `oklch(52.018% 0.165 28)` | 5.30:1 on `--error-bg` | `oklch(69.137% 0.17 28)` | 5.60:1 on `--error-bg` |

Chroma stays low at the lightness extremes because the sRGB gamut allows
almost none there — max chroma at L=99% on hue 250 is 0.0049.

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
2. **`.card .note` lost headroom** from a historical 5.025:1, because light
   `--card-bg` is no longer pure white. It is an untouched v1 literal
   (`#6f6f6f`) and still clears 4.5:1 — it is the second-tightest gated
   text pair in the sweep, and its current value is the `.card .note`
   row in the generated table rather than a number typed here.
4. **Light `--bg` → `--card-bg` separation halved** (critique L4), from a
   historical 1.062:1 to a value now pinned by
   `test_surface_separation_is_pinned_in_both_modes`. Net card visibility
   still improved, because the 1 px `--border` around it went from 1.342:1
   to over 3:1 — but the surface pair itself was previously unmeasured and
   unguarded, so nothing stopped a future re-derivation collapsing it to
   two identical hexes.
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
| 2 | light | card body text | `#181d23` | `#fafcfe` | **16.483:1** | 4.5:1 | 1.4.3 | PASS |
| 3 | light | header h1 a (large text) | `#181d23` | `#f6f9fb` | **16.032:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 4 | light | td text | `#181d23` | `#fafcfe` | **16.483:1** | 4.5:1 | 1.4.3 | PASS |
| 5 | light | tbody tr:hover text | `#181d23` | `#edeff2` | **14.715:1** | 4.5:1 | 1.4.3 | PASS |
| 6 | light | .breadcrumb a link [accent role 3] | `#1f609b` | `#f6f9fb` | **6.198:1** | 4.5:1 | 1.4.3 | PASS |
| 7 | light | focus ring on --bg [accent role 2] | `#1f609b` | `#f6f9fb` | **6.198:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 8 | light | focus ring on --card-bg [accent role 2] | `#1f609b` | `#fafcfe` | **6.372:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 9 | light | pre.error text | `#b5352d` | `#fceeec` | **5.291:1** | 4.5:1 | 1.4.3 | PASS |
| 10 | light | button.danger focus ring on --bg | `#b5352d` | `#f6f9fb` | **5.656:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 11 | light | button.danger focus ring on --card-bg | `#b5352d` | `#fafcfe` | **5.815:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 12 | light | --border on --bg [AC#4 in light] | `#818a94` | `#f6f9fb` | **3.312:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 13 | light | --border on --card-bg | `#818a94` | `#fafcfe` | **3.405:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 14 | dark | body text | `#d7dbe0` | `#090e13` | **13.931:1** | 4.5:1 | 1.4.3 | PASS |
| 15 | dark | card body text | `#d7dbe0` | `#13191f` | **12.725:1** | 4.5:1 | 1.4.3 | PASS |
| 16 | dark | header h1 a (large text) | `#d7dbe0` | `#090e13` | **13.931:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 17 | dark | td text | `#d7dbe0` | `#13191f` | **12.725:1** | 4.5:1 | 1.4.3 | PASS |
| 18 | dark | tbody tr:hover text | `#d7dbe0` | `#1b2127` | **11.673:1** | 4.5:1 | 1.4.3 | PASS |
| 19 | dark | .breadcrumb a link [accent role 3] | `#59a2eb` | `#090e13` | **7.190:1** | 4.5:1 | 1.4.3 | PASS |
| 20 | dark | focus ring on --bg [accent role 2] | `#59a2eb` | `#090e13` | **7.190:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 21 | dark | focus ring on --card-bg [accent role 2] | `#59a2eb` | `#13191f` | **6.568:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 22 | dark | pre.error text | `#f36b5d` | `#301714` | **5.620:1** | 4.5:1 | 1.4.3 | PASS |
| 23 | dark | button.danger focus ring on --bg | `#f36b5d` | `#090e13` | **6.525:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 24 | dark | button.danger focus ring on --card-bg | `#f36b5d` | `#13191f` | **5.960:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 25 | dark | --border on --bg [AC#4 in light] | `#636d77` | `#090e13` | **3.676:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 26 | dark | --border on --card-bg | `#636d77` | `#13191f` | **3.358:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 27 | light | button/.button text [accent role 1] | `#ffffff` | `#1f609b` | **6.553:1** | 4.5:1 | 1.4.3 | PASS |
| 28 | light | button:hover text | `#ffffff` | `#3d73a8` | **4.981:1** | 4.5:1 | 1.4.3 | PASS |
| 29 | light | button.danger text | `#ffffff` | `#b5352d` | **5.980:1** | 4.5:1 | 1.4.3 | PASS |
| 30 | light | .skip-link:focus-visible text [accent role 4] | `#ffffff` | `#1f609b` | **6.553:1** | 4.5:1 | 1.4.3 | PASS |
| 31 | dark | button/.button text [accent role 1] | `#090e13` | `#59a2eb` | **7.190:1** | 4.5:1 | 1.4.3 | PASS |
| 32 | dark | button:hover text | `#090e13` | `#6eaeee` | **8.260:1** | 4.5:1 | 1.4.3 | PASS |
| 33 | dark | button.danger text | `#090e13` | `#f36b5d` | **6.525:1** | 4.5:1 | 1.4.3 | PASS |
| 34 | dark | .skip-link:focus-visible text [accent role 4] | `#090e13` | `#59a2eb` | **7.190:1** | 4.5:1 | 1.4.3 | PASS |
| 35 | light | header .subtitle #555 | `#555555` | `#f6f9fb` | **7.051:1** | 4.5:1 | 1.4.3 | PASS |
| 36 | light | footer #666 | `#666666` | `#f6f9fb` | **5.431:1** | 4.5:1 | 1.4.3 | PASS |
| 37 | light | footer a #666 | `#666666` | `#f6f9fb` | **5.431:1** | 4.5:1 | 1.4.3 | PASS |
| 38 | light | .card .hint #555 | `#555555` | `#fafcfe` | **7.249:1** | 4.5:1 | 1.4.3 | PASS |
| 39 | light | .card .note #6f6f6f | `#6f6f6f` | `#fafcfe` | **4.886:1** | 4.5:1 | 1.4.3 | PASS |
| 40 | light | .card .empty #666 | `#666666` | `#fafcfe` | **5.583:1** | 4.5:1 | 1.4.3 | PASS |
| 41 | light | .card .display-name #444 | `#444444` | `#fafcfe` | **9.471:1** | 4.5:1 | 1.4.3 | PASS |
| 42 | light | dl.meta dt #555 | `#555555` | `#fafcfe` | **7.249:1** | 4.5:1 | 1.4.3 | PASS |
| 43 | light | input/textarea typed text on #fff | `#181d23` | `#ffffff` | **16.951:1** | 4.5:1 | 1.4.3 | PASS |
| 44 | light | th text on #f0f0f0 | `#181d23` | `#f0f0f0` | **14.875:1** | 4.5:1 | 1.4.3 | PASS |
| 45 | dark | header .subtitle / footer / footer a #b3b9c0 | `#b3b9c0` | `#090e13` | **9.796:1** | 4.5:1 | 1.4.3 | PASS |
| 46 | dark | .card .hint / dl.meta dt #b3b9c0 | `#b3b9c0` | `#13191f` | **8.948:1** | 4.5:1 | 1.4.3 | PASS |
| 47 | dark | .card .note / .card .empty #9ba1a8 | `#9ba1a8` | `#13191f` | **6.790:1** | 4.5:1 | 1.4.3 | PASS |
| 48 | dark | .card .display-name #c9d1d9 | `#c9d1d9` | `#13191f` | **11.467:1** | 4.5:1 | 1.4.3 | PASS |
| 49 | dark | input/textarea typed text | `#d7dbe0` | `#13191f` | **12.725:1** | 4.5:1 | 1.4.3 | PASS |
| 50 | dark | th text on th background | `#d7dbe0` | `#13191f` | **12.725:1** | 4.5:1 | 1.4.3 | PASS |
| 51 | light | .status-badge--ok text | `#15682d` | `#e6f4ea` | **6.063:1** | 4.5:1 | 1.4.3 | PASS |
| 52 | light | .status-badge--ok border on --bg | `#15682d` | `#f6f9fb` | **6.512:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 53 | light | .status-badge--warn text | `#8a5a00` | `#fdf3e2` | **5.389:1** | 4.5:1 | 1.4.3 | PASS |
| 54 | light | .status-badge--warn border on --bg | `#8a5a00` | `#f6f9fb` | **5.606:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 55 | light | .status-badge--ops-warn text | `#475569` | `#eef2f7` | **6.740:1** | 4.5:1 | 1.4.3 | PASS |
| 56 | light | .status-badge--ops-warn border on --bg | `#475569` | `#f6f9fb` | **7.167:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 57 | light | .status-badge--down text (tokens) | `#b5352d` | `#fceeec` | **5.291:1** | 4.5:1 | 1.4.3 | PASS |
| 58 | light | .status-badge--down border on --bg (token) | `#b5352d` | `#f6f9fb` | **5.656:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 59 | dark | .status-badge--ok text | `#3fb950` | `#0d2818` | **6.198:1** | 4.5:1 | 1.4.3 | PASS |
| 60 | dark | .status-badge--ok border on --bg | `#3fb950` | `#090e13` | **7.627:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 61 | dark | .status-badge--warn text | `#d29922` | `#3d2a07` | **5.428:1** | 4.5:1 | 1.4.3 | PASS |
| 62 | dark | .status-badge--warn border on --bg | `#d29922` | `#090e13` | **7.676:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 63 | dark | .status-badge--ops-warn text | `#8b949e` | `#1c2230` | **5.169:1** | 4.5:1 | 1.4.3 | PASS |
| 64 | dark | .status-badge--ops-warn border on --bg | `#8b949e` | `#090e13` | **6.299:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 65 | dark | .status-badge--down text | `#f85149` | `#3d1216` | **4.832:1** | 4.5:1 | 1.4.3 | PASS |
| 66 | dark | .status-badge--down border on --bg | `#f85149` | `#090e13` | **5.780:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 67 | light | .status-badge base border on --bg | `#818a94` | `#f6f9fb` | **3.312:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 68 | dark | .status-badge base border on --bg | `#636d77` | `#090e13` | **3.676:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 69 | light | in-flight accent button label on --bg [EXEMPT: inactive component, SC 1.4.3 — pointer-events:none] | `#fcfdfe` | `#608eb8` | **3.403:1** | — | exempt | EXEMPT |
| 70 | light | in-flight accent focus ring on --bg | `#608eb8` | `#f6f9fb` | **3.278:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 71 | light | in-flight danger button label on --bg [EXEMPT: inactive component, SC 1.4.3 — pointer-events:none] | `#fcfdfe` | `#c8706b` | **3.445:1** | — | exempt | EXEMPT |
| 72 | light | in-flight danger focus ring on --bg | `#c8706b` | `#f6f9fb` | **3.318:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 73 | light | in-flight accent button label on --card-bg [EXEMPT: inactive component, SC 1.4.3 — pointer-events:none] | `#fefeff` | `#618fb9` | **3.395:1** | — | exempt | EXEMPT |
| 74 | light | in-flight accent focus ring on --card-bg | `#618fb9` | `#fafcfe` | **3.327:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 75 | light | in-flight danger button label on --card-bg [EXEMPT: inactive component, SC 1.4.3 — pointer-events:none] | `#fefeff` | `#ca716c` | **3.421:1** | — | exempt | EXEMPT |
| 76 | light | in-flight danger focus ring on --card-bg | `#ca716c` | `#fafcfe` | **3.353:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 77 | dark | in-flight accent button label on --bg [EXEMPT: inactive component, SC 1.4.3 — pointer-events:none] | `#090e13` | `#4176aa` | **4.057:1** | — | exempt | EXEMPT |
| 78 | dark | in-flight accent focus ring on --bg | `#4176aa` | `#090e13` | **4.057:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 79 | dark | in-flight danger button label on --bg [EXEMPT: inactive component, SC 1.4.3 — pointer-events:none] | `#090e13` | `#ad4f47` | **3.678:1** | — | exempt | EXEMPT |
| 80 | dark | in-flight danger focus ring on --bg | `#ad4f47` | `#090e13` | **3.678:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 81 | dark | in-flight accent button label on --card-bg [EXEMPT: inactive component, SC 1.4.3 — pointer-events:none] | `#0c1117` | `#4479ae` | **4.144:1** | — | exempt | EXEMPT |
| 82 | dark | in-flight accent focus ring on --card-bg | `#4479ae` | `#13191f` | **3.870:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 83 | dark | in-flight danger button label on --card-bg [EXEMPT: inactive component, SC 1.4.3 — pointer-events:none] | `#0c1117` | `#b0524a` | **3.747:1** | — | exempt | EXEMPT |
| 84 | dark | in-flight danger focus ring on --card-bg | `#b0524a` | `#13191f` | **3.499:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 85 | light | .status-badge.htmx-settling flash border on --bg [accent role 5] | `#1f609b` | `#f6f9fb` | **6.198:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 86 | light | .status-badge.htmx-settling flash border on --card-bg [accent role 5] | `#1f609b` | `#fafcfe` | **6.372:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 87 | dark | .status-badge.htmx-settling flash border on --bg [accent role 5] | `#59a2eb` | `#090e13` | **7.190:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 88 | dark | .status-badge.htmx-settling flash border on --card-bg [accent role 5] | `#59a2eb` | `#13191f` | **6.568:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 89 | light | --border on th #f0f0f0 | `#818a94` | `#f0f0f0` | **3.073:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 90 | light | --border on tbody tr:hover | `#818a94` | `#edeff2` | **3.040:1** | 3.0:1 | 1.4.11 / large text | PASS |
| 91 | dark | --border on tbody tr:hover | `#636d77` | `#1b2127` | **3.080:1** | 3.0:1 | 1.4.11 / large text | PASS |

<!-- END GENERATED CONTRAST TABLE -->

## Cross-references

- `server/frontend/static/app.css` — the token block and its rationale comments
- `tests/_ui_color.py` — the colour math and stylesheet parser
- `tests/test_ui_contrast.py` — the gate, the pair registry, and this file's generator
- `.claude/references/frontend-uplift/arxmcp-design-system.md` §4 — the superseded 12-cell table
