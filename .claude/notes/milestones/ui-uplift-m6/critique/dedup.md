# Critique (merged) — ui-uplift-m6

**Critics:** milestone-adversary-critic, milestone-arxmcp-critic
**Commit range:** f8e931e..7817d8f
**Diff stats:** 12 files, 1560 LOC (1439+ / 121-)
**Critique format version:** 1.0

> **Merge note.** Each critic authored its ids from 1 within its own file, so
> they collided across files. `findings.py merge` renumbered them into one
> gapless per-severity sequence in critic dispatch order; bodies are verbatim.
> **Phase 4 dispositions attach to the MERGED ids below**, not to the ids in
> the per-critic files. Re-running merge after a critic file changes will shift
> these ids - see milestone-pipeline-critique-format.md.
>
> - `milestone-adversary-critic` (adversary.md): ids unchanged
> - `milestone-arxmcp-critic` (arxmcp.md): H1->H2, H2->H3, M1->M7, M2->M8, M3->M9, L1->L2, L2->L3, L3->L4

## Verdict

**SHIP-WITH-FIXES** — the most severe of the per-critic verdicts below.

### milestone-adversary-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES. The colour arithmetic is correct — I reimplemented OKLCH→sRGB
by the independent CSS-Color-4 XYZ path and it agrees byte-for-byte with
`tests/_ui_color.py` on all 14 tokens, every token is comfortably in-gamut with
no clipping, and the 0.03928/0.04045 threshold difference provably cannot move
any 8-bit ratio. The two rewritten tests are strictly stronger than what they
replaced, not weaker. What is missing is inventory: acceptance criterion 3
enumerates **five** `--accent` roles and the fifth — badge-flash tint — is
neither registered in `PAIRS` nor checked by the five-roles test, and when
computed it falls under its floor for five of eight status pills.

### milestone-arxmcp-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES

The OKLCH colour math is correct — I reimplemented the OKLab matrices independently and reproduced every token hex and every generated ratio to four decimal places, plus the canonical `oklch(62.796% 0.25768 29.234)` -> `#ff0000` round-trip — and axes 1, 3, 4, 5 and 7 are genuinely clean. But the milestone's own headline discipline ("no contrast number is typed by a human anywhere in this milestone") is falsified inside its own published artifact: the hand-written `--accent` five-roles table sits outside the generated markers and nine of its twelve numbers are wrong. Separately, the "EVERY rendered pair" sweep silently excludes the entire `.htmx-request { opacity: 0.6 }` state class, which contains sub-floor pairs the stylesheet itself computes.

## Executive summary — milestone-adversary-critic

- [HIGH] AC#3's fifth named `--accent` role, "badge-flash tint", is unmeasured;
  `test_accent_satisfies_all_five_roles` checks four roles, and the composite
  (30% accent over the canvas) yields 3.48–4.13:1 for 5 of 8 pill texts and
  2.10/2.22:1 for the base badge border — under AC#5's hard gate.
- [MEDIUM] The `.htmx-request { opacity: 0.6 }` button composite is also absent
  from `PAIRS` (2.79–3.37:1); plausibly exempt as an inactive component, but the
  exemption is nowhere recorded.
- [MEDIUM] Light `--border` was solved against `--bg`, but its real binding
  grounds are `th { background:#f0f0f0 }` (3.073:1) and `tbody tr:hover`
  (3.040:1) — neither is in `PAIRS`, so ~2.5% of headroom is unguarded.
- [MEDIUM] `tests/_ui_color.py` — 231 lines of new arithmetic that the whole
  gate and the published artifact depend on — has no ground-truth anchor test;
  the doc's "reproduces all nine independently-published numbers" is prose only.
- [MEDIUM] `ui-contrast-table.md:24` hand-types "(34 light, 34 dark)"; the real
  split is 36/32, and that line sits OUTSIDE the generated markers so the
  staleness gate cannot see it.
- [MEDIUM] `tests/_ui_color.py:3` claims to be "the repo's single WCAG-contrast
  implementation" while the 0.03928 duplicate still lives and is still called at
  `tests/test_ui_m5_create_remove_in_place.py:535`.
- [MEDIUM] `test_favicon_tracks_light_accent` is satisfied by the hex inside the
  SVG's XML comment, so it would pass with the `fill` attribute wrong.
- [NOTE] Diff-size auto-finding NOT filed: 1560 LOC is over the 400-LOC cliff,
  but the orchestrator records a user-granted `--allow-large-diff` and a settled
  scope decision, so it is deliberately omitted rather than overlooked.

## Executive summary — milestone-arxmcp-critic

- [HIGH] `.claude/docs/ui-contrast-table.md`'s five-roles table is hand-typed, outside the generated region, and 9 of 12 cells are wrong (6.583 vs 6.553, 7.199 vs 7.190, 5.037 vs 4.981, 6.584 vs 6.568) — the exact failure mode the milestone exists to close.
- [HIGH] The pair registry contains zero opacity-composited pairs, so AC#2's "EVERY rendered pair" and the "68 pairs, 0 failures" headline exclude in-flight button text at 2.79:1 and the danger focus ring at 2.77:1.
- [MEDIUM] `test_favicon_tracks_light_accent` passes on the XML comment, not the `fill` attribute — it cannot catch the drift it was written to catch.
- [MEDIUM] Role 5's exclusion rests on a false premise: `badge-flash` replaces the pill's opaque background for the full 400 ms, so 6 of 8 pill texts sit at 3.48–4.13:1 during the flash.
- [MEDIUM] `ui-uplift-m8`'s only code anchor (`app.css:53-59`, exactly the `.card` rule it retires) was invalidated by m6's +100-line shift and not moved.
- [LOW] "67 rendered pairs" in two places; the registry holds 68 and nothing pins the count.
- [LOW] The dark block's own comment claims "Nothing here is lifted from Primer any more" while four Primer Dark literals survive 60 lines below, one on the milestone's own blocklist.
- [CLEAN] Cache byte-stability, security/CSP, MCP spec, local-first, and no-fork all verified clean; the two deliberate v1-literal edits are both correct calls.

## Findings

**H1 — AC#3 role 5 (badge-flash tint) unmeasured and below floor** (HIGH)

**Where:** `tests/test_ui_contrast.py:211`
**Anchor:** `def test_accent_satisfies_all_five_roles`
**What:** `plans/ui-uplift/roadmap.yaml`'s AC#3 enumerates five `--accent` roles ending with "badge-flash tint", but this test checks only button ground, hover ground, focus ring (×2 grounds), link and skip-link — four distinct roles — and `PAIRS` registers no row for `app.css:437`'s `color-mix(in oklab, var(--accent) 30%, transparent)` background either, so the milestone's own "EVERY rendered pair" claim (AC#2, `test_ui_contrast.py:9`) is false for a state that renders every 10 seconds.
**Why it matters:** Computing that composite the way a browser does (accent at 30% alpha over the canvas in sRGB: `#b6cbde` light, `#213a54` dark) puts `.status-badge--ok` at 4.127:1, `--warn` at 3.552:1 and `--down` at 3.584:1 in light mode, `--ops-warn` at 3.797:1 and `--down` at 3.484:1 in dark, plus the base `.status-badge` border at 2.099:1 / 2.216:1 — five text pairs under SC 1.4.3's 4.5:1 and two borders under SC 1.4.11's 3:1, which AC#5 declares a hard ship gate.
**Proposed fix:** Add a `flash("--accent", 30, ground)` spec kind to `_resolve` that does *alpha-over-in-sRGB* compositing (not `mix_oklab` — `color-mix(…, transparent)` premultiplies and yields accent at α=0.3, which then composites in sRGB, not OKLab), register one row per pill per mode plus the base-badge border, and add role 5 to `test_accent_satisfies_all_five_roles`. Then either lower the tint percentage / re-solve until every flash pair clears its floor, or — if the team judges a 400 ms `ease-out` transient exempt — record that exemption explicitly in `ui-contrast-table.md` with the measured numbers rather than leaving the pairs unlisted. I am confident the pairs are unmeasured; I am moderately confident (not certain) that WCAG requires them to pass, since the flash is transient and reduced-motion-gated — but "unmeasured" alone defeats AC#2 and AC#3.
**Regression-guard:** `tests/test_ui_contrast.py::test_rendered_pair_meets_wcag_floor[light-.status-badge--warn text during badge-flash]` plus a role-5 assertion in `test_accent_satisfies_all_five_roles`.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**H2 — Artifact's five-roles table is hand-typed and 9/12 numbers wrong** (HIGH)

**Where:** `.claude/docs/ui-contrast-table.md:127`
**Anchor:** `| 1 · button ground | `button, .button``
**What:** The `--accent` five-roles table (lines 125–133) and the Headline table (line 28) sit OUTSIDE the `<!-- BEGIN/END GENERATED CONTRAST TABLE -->` markers, are hand-typed, and nine of their twelve ratio cells disagree with the values the milestone's own code computes: role 1/4 light `6.583` vs actual **6.5528**; role 1/2/3/4 dark `7.199` vs **7.1898**; role 1b light `5.037` vs **4.9809** (a 1.1% error); role 1b dark `8.264` vs **8.2596**; role 2 dark vs `--card-bg` `6.584` vs **6.5675**. The `7.199` figure is repeated in the Headline row and again as `7.20:1` at `app.css:331`.
**Why it matters:** The document states "Ratios are **computed, never typed**" and `tests/test_ui_contrast.py:13` states "No contrast number is typed by a human anywhere in this milestone." Both are false, and `test_published_contrast_table_is_current` structurally cannot catch it because it only compares the region between the markers. This is the same class of defect the artifact itself cites as its motivating incident ("a comment in `app.css` that stated a ratio ~20% off"), reintroduced in the artifact written to end it. Several errors are digit transpositions (6.583/6.553, 7.199/7.190), the classic hand-typing tell.
**Proposed fix:** Generate the five-roles table from the same six checks `test_accent_satisfies_all_five_roles` already computes, and emit it inside a second `BEGIN/END GENERATED ROLES TABLE` marker pair covered by an equality test; likewise derive the four Headline numbers (tightest pair, tightest text pair) from `_rows()` via `min(...)`. Fix `app.css:331`'s `7.20:1` to `7.19:1` in the same edit.
**Regression-guard:** Extend `test_published_contrast_table_is_current` (or add `test_roles_table_is_generated`) to assert the roles region equals a `render_roles_table()` output; then grep-assert that no `\d\.\d{3}:1` literal appears in `ui-contrast-table.md` outside a generated region.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

**H3 — Sweep omits the entire `.htmx-request` opacity-0.6 state class** (HIGH)

**Where:** `tests/test_ui_contrast.py:87`
**Anchor:** `PAIRS: list[tuple[str, str, object, object,`
**What:** `PAIRS` registers no opacity-composited pair. `app.css:390-396` applies `opacity: 0.6` to every in-flight submit button, which composites BOTH the element's text and its background over the parent, collapsing their mutual contrast. Measured: light in-flight button label `#fdfeff` on `#779ec3` = **2.787:1** (floor 4.5), dark = **3.368:1**; light `button.danger:focus-visible` ring at 0.6 = **2.766:1** and the accent ring = **2.736:1** (floor 3.0). `app.css:398-402` already knows about the ring case ("falls to ~2.57:1 ... fails SC 1.4.11") and "compensates" with `outline-width: 3px` — but SC 1.4.11 states a contrast threshold with no width trade; thickness is a WCAG 2.2 SC 2.4.13 *area* criterion, a different requirement.
**Why it matters:** AC#2 requires a table over EVERY rendered pair and AC#5 makes any sub-floor pair a ship blocker; the artifact's headline asserts "68 pairs, 0 failures". A whole rendered state class reached on the most common path in the console (every form submit) was excluded without being declared, which is precisely the "partial inventory" mechanism the module docstring says shipped three prior AA failures. Even under the SC 1.4.3/1.4.11 "inactive component" exemption (arguable for the label, weak for a `:focus-visible` ring), the correct outcome is an exempt-with-reason row, not silence.
**Proposed fix:** Add an `alpha` spec kind to `_resolve` (`("alpha", spec, 0.6, parent)` -> per-channel `round(a*fg + (1-a)*parent)`) and register the four in-flight pairs (light/dark x button label, danger ring) plus a note row. If a pair is judged exempt, register it with an explicit `EXEMPT` floor sentinel so it appears in the artifact with its ratio and its reason.
**Regression-guard:** `test_rendered_pair_meets_wcag_floor` parametrized over the new `light-in-flight button label` / `dark-in-flight danger ring` ids; plus a structural test asserting every `opacity:` declaration in `app.css` under 1.0 has at least one matching registry row.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M1 — `.htmx-request` 0.6-opacity button composite absent from PAIRS** (MEDIUM)

**Where:** `server/frontend/static/app.css:393`
**Anchor:** `  opacity: 0.6;`
**What:** In-flight buttons render at `opacity: 0.6`, compositing BOTH their text and their fill over the page ground, and no row in `PAIRS` covers that state.
**Why it matters:** Measured, the composite is 2.799:1 (light accent on `--bg`), 2.855:1 (light danger), 3.274:1 and 2.976:1 (dark) — all well under 4.5:1, so a reader of `ui-contrast-table.md` would conclude the console has no sub-floor text pair when it has eight.
**Proposed fix:** Either register the eight composites (a `fade(spec, 0.6, ground)` resolver reusing the same sRGB alpha-over helper H1 needs) or add a short "Exempt states" section to `ui-contrast-table.md` citing WCAG's inactive-user-interface-component exception and noting that `pointer-events: none` is what makes it apply. I lean toward the exemption being legitimate here — `app.css:398-403` already reasoned about this opacity for the focus ring — but an unstated exemption and an oversight look identical from the artifact.
**Regression-guard:** optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**M2 — Light `--border` solved against the wrong binding ground** (MEDIUM)

**Where:** `server/frontend/static/app.css:36`
**Anchor:** `  --border: oklch(62.984% 0.018 250);  /*`
**What:** The token records "solved: 3.30:1 on `--bg`", and the dark block does the binding-ground analysis carefully (`app.css:314-317` picks the lighter of two grounds), but in light mode `--border` is also drawn against `th { background: #f0f0f0 }` (`app.css:164`) and `tbody tr:hover` (`app.css:171`), where it measures 3.073:1 and 3.040:1 — both darker grounds than `--bg` and therefore the actual binding ones.
**Why it matters:** The shipped value has 1.3% headroom over SC 1.4.11 on grounds that no `PAIRS` row covers, so a future re-derivation aimed at the documented 3.30:1 `--bg` target could drop the real thinnest pair under 3:1 with the gate still green.
**Proposed fix:** Add `_p("light", "--border on th #f0f0f0", "--border", "#f0f0f0", NONTEXT)` and `_p(_m, "--border on tbody tr:hover", "--border", ROW_HOVER, NONTEXT)` for both modes, and amend the light `--border` comment to name `#f0f0f0` as the binding ground (or re-solve against it with the same margin the dark token got).
**Regression-guard:** optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**M3 — `_ui_color.py` has no ground-truth anchor test** (MEDIUM)

**Where:** `tests/_ui_color.py:79`
**Anchor:** `def linear_srgb_to_oklab(r: float, g: floa`
**What:** The module is the arithmetic authority for the whole gate and the published table, yet no test asserts a single independently-known value — not black-on-white = 21.000:1, not a known `oklch()`→hex conversion, not that `in_srgb_gamut` rejects an out-of-gamut triple, not a `mix_oklab` reference result — while `.claude/docs/ui-contrast-table.md:46` asserts in prose that "the implementation reproduces all nine independently-published numbers it was checked against".
**Why it matters:** A transposed matrix row or a swapped OKLab coefficient would shift every ratio coherently: the gate would still pass, the table would regenerate to match itself, and the milestone's central claim ("the arithmetic is generated, not typed") would be quietly wrong. I verified the current code against an independent XYZ-path implementation and it is correct today; nothing in the repo keeps it correct tomorrow.
**Proposed fix:** Add `tests/test_ui_color_math.py` pinning the nine numbers the doc already claims were checked — `contrast_ratio("#000000", "#ffffff") == 21.000`, the `1.342`/`2.526`/`4.974` historical figures against their historical hexes, at least one `resolve_color("oklch(…)") == "#…"` reference conversion, and `pytest.raises(RuntimeError)` for a deliberately out-of-gamut triple such as `oklch(70% 0.4 250)` and for an unsupported value shape.
**Regression-guard:** optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Test discipline

**M4 — Hand-typed pair counts in the generated artifact are wrong** (MEDIUM)

**Where:** `.claude/docs/ui-contrast-table.md:24`
**Anchor:** `| Pairs measured | **68** (34 light, 34`
**What:** The headline splits 68 pairs as "34 light, 34 dark"; the registry actually holds 36 light and 32 dark, and this line lives outside the `BEGIN/END GENERATED CONTRAST TABLE` markers so `test_published_contrast_table_is_current` cannot catch it — the same off-by-one appears as "67 rendered pairs" at `tests/test_ui_contrast.py:19` and "All 67 rendered pairs" at `server/frontend/static/app.css:26`.
**Why it matters:** A document whose entire thesis is "hand-typed numbers are how three AA failures shipped" carries three wrong hand-typed numbers on its first page, which is exactly the credibility the artifact needs to keep.
**Proposed fix:** Move the headline row inside the generated region (or emit a second generated marker pair around it) so `render_table()` produces the counts and the split, and correct the two "67"s to "68" — better, phrase them as "every pair in `PAIRS`" so they cannot drift again.
**Regression-guard:** optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**M5 — "single WCAG-contrast implementation" is false; the duplicate survives** (MEDIUM)

**Where:** `tests/_ui_color.py:3`
**Anchor:** `This is the repo's single WCAG-contrast im`
**What:** The module docstring (and the `8ee611e` commit body) state that this is the repo's single WCAG implementation, but `tests/test_ui_m5_create_remove_in_place.py:525-540` still defines `_relative_luminance`/`_contrast_ratio` on the `0.03928` threshold and still calls it at `:596` and `:617` — the m5 test now parses the canvas from the stylesheet but computes the ratio with the old calculator.
**Why it matters:** Two calculators on two different branch thresholds is the precise hazard the module was created to end; the numbers cannot currently diverge (no 8-bit channel falls between 0.03928 and 0.04045, so the two are provably identical for any hex input), which means the divergence would only appear once someone feeds them non-8-bit input — silently.
**Proposed fix:** Delete `_hex_to_rgb`/`_relative_luminance`/`_contrast_ratio` from `tests/test_ui_m5_create_remove_in_place.py` and import `contrast_ratio` from `tests._ui_color` at the two call sites, or, if the duplicate is deliberately retained as an independent cross-check, say so in both docstrings and add a test asserting the two agree on the token set.
**Regression-guard:** optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**M6 — Favicon sync test is satisfied by the SVG's own comment** (MEDIUM)

**Where:** `tests/test_ui_contrast.py:382`
**Anchor:** `    assert LIGHT["--accent"] in svg.lower`
**What:** The assertion is a substring test over the whole file, and `favicon.svg:3` embeds the literal `#1f609b` inside the explanatory XML comment as well as in `fill="#1f609b"` at `:8`, so the test passes on the comment alone.
**Why it matters:** The one guard standing between a re-derived `--accent` and a stale brand colour in browser-tab chrome can be satisfied without the rendered attribute being correct at all — delete the `<rect>` and the test still goes green.
**Proposed fix:** Strip comments before the check, or better, assert the attribute: `m = re.search(r'<rect[^>]*fill="(#[0-9a-f]{6})"', svg, re.I); assert m and m.group(1).lower() == LIGHT["--accent"]`.
**Regression-guard:** optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Test discipline

**M7 — `test_favicon_tracks_light_accent` is satisfied by the XML comment** (MEDIUM)

**Where:** `tests/test_ui_contrast.py:382`
**Anchor:** `    assert LIGHT["--accent"] in svg.lower(),`
**What:** The assertion is a substring test over the whole file, and `favicon.svg:2-3` contains the literal `#1f609b` inside the XML comment the same milestone added ("now oklch(47.863% 0.115 250) = #1f609b"). A future edit that changes `fill="#1f609b"` to any other value while leaving the comment intact still passes.
**Why it matters:** This is the milestone's sole guard against the one value it identified as untokenisable and therefore hand-synced; a guard that its own explanatory comment satisfies gives false coverage. Same shape as the previously-recorded `vacuous-test-kept-as-documentation` family.
**Proposed fix:** Assert on the attribute: `m = re.search(r'<rect[^>]*fill="(#[0-9a-fA-F]{6})"', svg)` then `assert m and m.group(1).lower() == LIGHT["--accent"]`.
**Regression-guard:** The rewritten assertion itself; falsify by temporarily setting `fill="#1e5b8a"` and confirming the test fails.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M8 — Role 5's exclusion rests on a false claim about `background`** (MEDIUM)

**Where:** `.claude/docs/ui-contrast-table.md:135`
**Anchor:** `**Role 5 is deliberately not assigned a r`
**What:** The artifact justifies excluding the badge-flash tint as "a transient, 30%-opacity `color-mix(…, transparent)` overlay animated over a status pill that is already independently legible" (echoed at `implement/synthesis.md:37-40`). It is not an overlay. `app.css:436-439` animates the `background` property itself, so for the whole 400 ms window the modifier class's opaque background (`#e6f4ea` / `#3d1216` / …) is **replaced** — first by accent at 30% alpha, then by `transparent`. The pill text therefore sits on accent@30% composited over the footer's `--bg`, not on its designed ground. Measured: light ok **4.127:1**, warn **3.552:1**, down **3.584:1**; dark ops-warn **3.797:1**, down **3.484:1** — 6 of 8 under 4.5:1.
**Why it matters:** The one pair the sweep deliberately skipped is the one where the reasoning is wrong, and the reasoning is what AC#3 rests on for role 5. It is a pre-existing m4 (UPL-22) behaviour, but m6 re-derived `--accent` and so changed the composited ground while re-affirming the wrong model of it.
**Proposed fix:** Correct the paragraph to state that `background` is replaced, not overlaid, and register the eight flash pairs with the measured ratios (declared as transient/`prefers-reduced-motion`-gated, floor deliberately unasserted) so the numbers are in the artifact. Cheapest behavioural fix if wanted later: animate `box-shadow: inset 0 0 0 100vmax color-mix(...)` instead of `background`, which is a true overlay and preserves the pill ground.
**Regression-guard:** Registry rows `light-.status-badge--warn text during badge-flash` etc. with an `EXEMPT`/transient floor, so the numbers regenerate into the table and any future `--accent` move re-measures them.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

**M9 — m6 invalidated ui-uplift-m8's only code anchor without moving it** (MEDIUM)

**Where:** `server/frontend/static/app.css:85`
**Anchor:** `.card {`
**What:** `plans/ui-uplift/roadmap.yaml:350` gives m8 `links.code: ["server/frontend/static/app.css:53-59", "server/frontend/static/app.css:114-116"]`. At `f8e931e`, lines 53–59 were *exactly* the `.card { background; border; border-radius; padding; margin-bottom }` rule — the primitive m8 exists to delete. m6 added 100 lines above it, so `.card` now begins at line 85 and `app.css:53-59` resolves to `* { box-sizing }` plus the `body` font stack. `114-116` likewise now lands inside the `input[type=…]` rule.
**Why it matters:** Axis 6 — m8 is `depends_on: [ui-uplift-m6]` and this is the FOUNDATIONAL milestone in that chain. AC#4 is genuinely delivered (light `--border` 1.342:1 -> **3.312:1**, verified independently), so m8 is functionally unblocked, but its researcher's single starting pointer now lands on unrelated code. The artifact placement in `.claude/docs/` is correct, but nothing in m8's roadmap entry points at it either — discovery depends on the researcher scanning `.claude/docs/`.
**Proposed fix:** Update `plans/ui-uplift/roadmap.yaml` m8 `links.code` to `["server/frontend/static/app.css:85-91", "server/frontend/static/app.css:108-133"]` and append `docs: [".claude/docs/ui-contrast-table.md"]`. Sweep the same file for any other `app.css:<n>` anchor above line 51.
**Regression-guard:** Optional (MEDIUM). A cheap derived check: a test that every `app.css:<start>-<end>` anchor in `plans/ui-uplift/roadmap.yaml` for a not-yet-complete milestone still spans a line matching a CSS selector or `{`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing

**L1 — UPL-27 comment ratios are stated against a ground that moved** (LOW)

**Where:** `server/frontend/static/app.css:95`
**Anchor:** `/* UPL-27: #777 on #fff is 4.478:1 — unde`
**What:** The comment reasons about `.card .note` against `#fff` and quotes "5.02:1", but light `--card-bg` is now `#fafcfe`, where `#6f6f6f` measures 4.886:1.
**Why it matters:** It is the second-tightest pair in the whole sweep (1.086× its floor) and the adjacent comment overstates its headroom by ~3%, which is the same class of stale hand-computed number this milestone exists to retire.
**Proposed fix:** Restate as "`#6f6f6f` on `--card-bg` — see `.claude/docs/ui-contrast-table.md`" and drop the literal, so the number lives only where it is generated.
**Regression-guard:** optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Dead code / leftovers

**L2 — "67 rendered pairs" in two places; the registry holds 68** (LOW)

**Where:** `server/frontend/static/app.css:26`
**Anchor:** `     All 67 rendered pairs, their target`
**What:** `app.css:26` ("All 67 rendered pairs"), `app.css:225` ("the ONLY pair the full 67-pair sweep found") and `tests/test_ui_contrast.py:19` ("this one covers 67 rendered pairs") all say 67. `len(PAIRS)` is 68 and the artifact's own headline says "**68 pairs, 0 failures**" and numbers its last row `68`. No test pins the count — `test_table_covers_more_than_the_legacy_token_grid` only asserts `>= 60`.
**Why it matters:** Doc drift on the milestone's headline number, in the stylesheet a future author reads first; `>= 60` also lets a future edit silently drop eight pairs.
**Proposed fix:** Change all three occurrences to 68, and tighten the guard to `assert len(PAIRS) == 68` (or `>= 68`) so the count and the prose move together.
**Source critic:** milestone-arxmcp-critic
**Source axis:** cache byte-stability

**L3 — Dark block claims "Nothing here is lifted from Primer" while four Primer literals survive in it** (LOW)

**Where:** `server/frontend/static/app.css:308`
**Anchor:** `     (dark canvas + a raised card 5pp li`
**What:** The comment opening the dark `@media` block asserts "Nothing here is lifted from Primer any more; the old block was a labelled Primer clone." Sixty lines below, still inside that block, `app.css:370-373` keeps `#3fb950`, `#d29922`, `#8b949e` and `#f85149` — GitHub Primer Dark `success.fg` / `attention.fg` / `fg.muted` / `danger.fg` — plus `#c9d1d9` at `:351`. `#f85149` is on the milestone's own `PRIMER_LITERALS` blocklist (`tests/test_ui_contrast.py:267`); the blocklist test only scans `:root` tokens, so it does not fire. The file contradicts itself at `:363-369`, which correctly admits the pill literals stay.
**Why it matters:** AC#1's wording ("no value is a GitHub Primer literal") is satisfied for the eight `:root` tokens — which I verified is a genuine re-derivation, not Primer re-expressed in `oklch()` — but the comment overstates the scope in the one place a reader checking the no-fork claim would look.
**Proposed fix:** Scope the sentence: "Nothing in **this `:root` block** is lifted from Primer any more; the four `.status-badge--*` literals below are v1 scope and are still Primer Dark values (see :363)."
**Source critic:** milestone-arxmcp-critic
**Source axis:** no-fork policy

**L4 — Light card/canvas separation halved, unrecorded and unpinned** (LOW)

**Where:** `server/frontend/static/app.css:35`
**Anchor:** `  --card-bg: oklch(99% 0.004 250);     /`
**What:** Light `--bg` -> `--card-bg` separation fell from `#f8f8f8` vs `#ffffff` = **1.0620:1** to `#f6f9fb` vs `#fafcfe` = **1.0281:1**, a ~55% reduction in an already sub-perceptual delta. Dark is unchanged (1.0940 -> 1.0948). The artifact's "Known non-blocking observations" records the `.card .note` headroom loss caused by the same anchor move but not this one, and no test pins any minimum: `test_focus_ring_verified_against_card_bg_not_only_bg:237` asserts only `DARK["--card-bg"] != DARK["--bg"]` — a bare inequality — and nothing at all for light.
**Why it matters:** Net card visibility improves (the 1 px `--border` went 1.342 -> 3.312:1), so this is not a defect today; but the surface pair is unmeasured and unguarded, and a future re-derivation could collapse it to identical hexes and pass every test in this milestone. It is also directly relevant to m8 AC#2, which requires `--card-bg`'s successor role to be stated because three dark rules depend on it.
**Proposed fix:** Add both surface pairs to the artifact's observations with their measured ratios, and replace the bare `!=` with `assert contrast_ratio(T["--card-bg"], T["--bg"]) >= 1.02` for both modes.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

## What was done well

### From milestone-adversary-critic

- The OKLCH→sRGB conversion is correct. I reimplemented it by the independent
  CSS Color 4 path (OKLab → LMS → XYZ D65 → linear sRGB, entirely different
  matrices from Bottosson's direct form used at `tests/_ui_color.py:93-102`) and
  got byte-identical hexes for all 14 tokens.
- Gamut handling is right and deliberately fail-loud. `in_srgb_gamut`
  (`_ui_color.py:119`) rejects rather than clamps, with a comment naming the
  actual reason (browsers chroma-reduce, so a clamp would not match the render);
  every shipped token's linear triple sits inside `[0.0027, 0.9946]`, nowhere
  near the boundary.
- The `0.03928` → `0.04045` decision is documented *and* its blast radius
  correctly bounded (`_ui_color.py:52-56`) — no 8-bit channel falls between the
  two thresholds, so the choice provably moves no ratio.
- Neither rewritten test was softened. `test_dark_border_is_not_a_primer_literal_and_clears_sc_1411`
  keeps the original `#30363d` negative, *adds* `#6e7681`, and *adds* a computed
  3:1 check against both grounds; the on-accent test now resolves `var(--bg)` and
  asserts the ratio instead of regex-matching a hex. Both are strictly stronger.
- `test_no_pair_registry_duplicates_a_token_as_a_literal` is a genuinely clever
  meta-guard: it makes the m5 "stale hardcoded canvas" failure mode structurally
  unrepeatable rather than just fixing the one instance.
- The generated/hand-maintained boundary is stated honestly in three places
  (module docstring, table doc "What is *not* automated", commit body) instead of
  the diff claiming full automation it does not have.
- The `--dur-fast` ↔ `index.html` `swap:200ms` coupling was converted from a
  comment asking for it into `test_dur_fast_stays_coupled_to_the_hx_swap_modifier`,
  which parses the template — the right response to a numeric coupling.
- The two out-of-scope literal edits are both defensible and both loudly
  disclosed: `th { background }` was a byte-copy of a token being moved, and the
  `ops-warn` border was a live 2.414:1 SC 1.4.11 failure that AC#5 obliges the
  milestone to close once the sweep surfaced it.
- Clean on the boundary axes: no `plans/*/roadmap.yaml` or checkbox edit, no
  push/publish/deploy, no new dependency, no `assert` outside `tests/`, no
  Node/npm/CDN, `color-scheme: light dark` preserved and `light-dark()` absent
  (AC#6/AC#7 both tested). Both commits are GPG-signed (`%G? = G`), conventional,
  ≤50-char subjects, and carry the mandated `Co-Authored-By` trailer.

### From milestone-arxmcp-critic

- **The colour math is correct.** I reimplemented Ottosson's OKLab<->linear-sRGB matrices independently and reproduced all fourteen token hexes and every generated ratio to four decimal places, plus the canonical references `oklch(62.796% 0.25768 29.234)` -> `#ff0000` and `oklch(100% 0 0)` -> `#ffffff`. The `math.copysign(abs(v) ** (1/3), v)` guard for negative LMS intermediates is the correct handling of the complex-number trap.
- **Out-of-gamut triples raise instead of clamping** (`tests/_ui_color.py:119-124`). This is the one choice that matches what a browser paints: CSS Color 4 gamut-maps by chroma reduction, so a naive clamp would put a number in the table that no screen shows. Exactly the axis-2 failure mode the dispatch asked about, and it was anticipated.
- **The two hex-pinned tests were strengthened, not softened.** `test_dark_border_is_not_a_primer_literal_and_clears_sc_1411` now blocks two Primer literals instead of one AND checks 3:1 against **both** grounds — the old test checked neither ground, only a hex. `test_dark_block_corrects_on_accent_text_color` now resolves the declared colour and asserts the real 4.5:1 rather than regex-matching a byte string.
- **The `canvas = "#0d1117"` duplicate is gone** (`test_ui_m5_create_remove_in_place.py:611-614`). That literal was silently validating against a ground the product would no longer paint; it now parses from the stylesheet, and `test_no_pair_registry_duplicates_a_token_as_a_literal` generalises the lesson into a standing rule.
- **The three cap tests moved 400 -> 480 in lockstep**, each carrying a cross-reference naming the other two files. Verified: all three at 480, file at 460 lines.
- **`_update()` fails loudly on `count != 1`** rather than writing the file back unchanged, and pins `newline="\n"` so regenerating on Windows does not churn every line of a checked-in artifact — both are non-obvious, both were reasoned about in comments.
- **`test_dur_fast_stays_coupled_to_the_hx_swap_modifier`** converts a load-bearing "MUST match" comment into an enforced cross-file coupling by parsing `index.html`'s `hx-swap` modifier. That is the right shape for a numeric coupling that spans two file types.
- **No-fork holds under real scrutiny.** The new values are not Primer re-expressed: dark `--bg` is `#090e13` (Primer `#0d1117`), dark `--accent` `#59a2eb` (Primer `#58a6ff`), hue 250 against Primer's 256–258, and the light family is now chromatic (C=0.004) where it was perfectly achromatic. Genuinely re-derived.
- **Both deliberate v1-literal edits are the right calls.** `th { background: var(--card-bg) }` was mandatory, not optional — the literal was a byte-copy of the token being moved and leaving it would have shipped a visibly mismatched dark table header; I would have raised its absence as a finding. `.status-badge--ops-warn`'s border fix closes a live SC 1.4.11 failure at zero line cost and matches the file's own m5 single-colour precedent.
- **The synthesis surfaced its own weak points** — the scope overrun with a concrete m6a/m6b split proposal, the two v1 literals, and the `tail`-ate-pytest's-exit-code near-miss — rather than burying them. That is the behaviour that makes a Phase-3 review cheap.

Severity counts: C0 H3 M9 L4


## Cross-critic agreement

The following findings cluster within 5 lines of each other in the same file. Multiple critics flagged the same area - these are the strongest signals to fix first.

- **M6, M7** at `tests/test_ui_contrast.py:382-382` (MEDIUM): Favicon sync test is satisfied by the SVG's own comment; `test_favicon_tracks_light_accent` is satisfied by the XML comment
- **L4, M2** at `server/frontend/static/app.css:35-36` (MEDIUM): Light card/canvas separation halved, unrecorded and unpinned; Light `--border` solved against the wrong binding ground

## Recommended rectification order

H1, H2, H3, M2, M3, M4, M6, M5, M1, M7, M8, M9, L1, L2, L3, L4

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
