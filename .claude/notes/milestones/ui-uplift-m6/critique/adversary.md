# Critique — ui-uplift-m6 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** f8e931e..7817d8f
**Diff stats:** 12 files, 1560 LOC (1439+ / 121-)
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES. The colour arithmetic is correct — I reimplemented OKLCH→sRGB
by the independent CSS-Color-4 XYZ path and it agrees byte-for-byte with
`tests/_ui_color.py` on all 14 tokens, every token is comfortably in-gamut with
no clipping, and the 0.03928/0.04045 threshold difference provably cannot move
any 8-bit ratio. The two rewritten tests are strictly stronger than what they
replaced, not weaker. What is missing is inventory: acceptance criterion 3
enumerates **five** `--accent` roles and the fifth — badge-flash tint — is
neither registered in `PAIRS` nor checked by the five-roles test, and when
computed it falls under its floor for five of eight status pills.

## Executive summary

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

**L1 — UPL-27 comment ratios are stated against a ground that moved** (LOW)

**Where:** `server/frontend/static/app.css:95`
**Anchor:** `/* UPL-27: #777 on #fff is 4.478:1 — unde`
**What:** The comment reasons about `.card .note` against `#fff` and quotes "5.02:1", but light `--card-bg` is now `#fafcfe`, where `#6f6f6f` measures 4.886:1.
**Why it matters:** It is the second-tightest pair in the whole sweep (1.086× its floor) and the adjacent comment overstates its headroom by ~3%, which is the same class of stale hand-computed number this milestone exists to retire.
**Proposed fix:** Restate as "`#6f6f6f` on `--card-bg` — see `.claude/docs/ui-contrast-table.md`" and drop the literal, so the number lives only where it is generated.
**Regression-guard:** optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Dead code / leftovers

## What was done well

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

Severity counts: C0 H1 M6 L1

## Recommended rectification order

H1, M2, M3, M4, M6, M5, M1, L1

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
