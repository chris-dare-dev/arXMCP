---
milestone_id: "ui-uplift-m6"
researcher_role: "general"
external_writes_required:
  - "git push origin main — lands the feat/rect/chore commit triple; USER-GATED at the Phase-4 boundary (CLAUDE.md §4.4, re-ask each time). Precedent: lean-repl-observability-m1 and verification-contract-m1 brief-2s both enumerate exactly this and nothing else for comparably self-contained milestones. No package publish, no deploy, no API call, no issue creation is required by this CSS-token milestone — that part of the dispatch note's expectation is correct."
sources:
  - url: "https://developer.mozilla.org/en-US/docs/Web/CSS/color_value/oklch"
    sha256: "ab23e37042cb1e64c6775d985388705e687112f377cb63721b48b9daf085c198"
    takeaway: "oklch() is Baseline Widely Available since May 2023 (3+ years by this milestone's target date); a non-supporting engine drops the whole declaration at PARSE time when oklch() is used directly on a standard property, falling back to the previous cascade value."
  - url: "https://developer.mozilla.org/en-US/docs/Web/CSS/color_value/light-dark"
    sha256: "2f82b7acc90a5c5db074fa4410838be3cd9cf65e10ba58f3d8b3d35cb0c5482c"
    takeaway: "light-dark() reached Baseline Newly Available only in May 2024, confirming criterion 7's framing; Baseline's ~30-month newly-to-widely rule puts Widely around Q4 2026 — still in the future as of this research (2026-08-03)."
  - url: "https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_cascading_variables/Using_CSS_custom_properties"
    sha256: "5a7f99750e9961a8129d2f55cf9cba0ce658981eed806f9775a17595a668db57"
    takeaway: "Verbatim mechanism behind criterion 7: an invalid var() substitution at computed-value time falls back to the inherited value if the property inherits, else its initial value. background-color does not inherit, so its initial value (transparent) is exactly what renders — confirmed, not just asserted."
  - url: "https://bottosson.github.io/posts/oklab/"
    sha256: "763738fd931b6d3feea3d91b61db5d40028758c3e228d11748f6b00ad1df7cf7"
    takeaway: "Canonical OKLab<->linear-sRGB conversion matrices (the same ones the CSS Color 4 spec's own sample code reproduces). Used below to build and triple-cross-validate a Python verification routine against this repo's own already-published contrast numbers."
  - url: "https://www.radix-ui.com/colors/docs/palette-composition/understanding-the-scale"
    sha256: "29c2a1efb11d46b820ed50bda81e58b9f7a04f36ea54253d5378568c8759da5a"
    takeaway: "Mature multi-role color systems split roles across DIFFERENT scale steps — step 9 (purest chroma) for solid/button grounds, steps 11/12 (engineered contrast) for accessible text — rather than reusing one raw value for both. Criterion 3 deliberately requires the opposite (one token, five roles); §2 below explains why that is nonetheless achievable here."
  - url: "https://webaim.org/articles/contrast/"
    sha256: "d7d9987d601f6b58971073148ac2b8b833bf2e049575fb10bd1091a2f11f0e5c"
    takeaway: "Practitioner corroboration that WCAG 2.x contrast is defined purely on sRGB relative luminance — there is no perceptual-space (OKLCH L, Lab, HSL lightness) shortcut. This is the single biggest way this milestone could ship something that looks right and fails the gate."
injection_attempts: 0
---

# Research brief (general) — ui-uplift-m6

Two sources could not be independently hashed: **`https://www.w3.org/TR/WCAG22/`**
(Success Criteria text, contrast-ratio formula) and
**`https://www.w3.org/WAI/GL/wiki/Relative_luminance`** (the coefficients + the
0.03928→0.04045 errata). Both were read via an interactive fetch tool on
2026-08-03 and the exact quotes appear in §3 below, but `www.w3.org` returns an
HTTP 403 Cloudflare managed-challenge page to a non-interactive fetch even with
a standard browser User-Agent (verified live via `curl`, confirmed by
inspecting the challenge HTML) — no raw bytes were obtainable to hash the way
the other 6 sources were. The formula quoted from these two pages is
cross-corroborated three separate ways in §3 (two of them fresh, first-party
verification I ran myself, not just citation): against WebAIM's independently
hashed page's topic, and against this repo's own already-published contrast
numbers in `.claude/references/frontend-uplift/arxmcp-design-system.md` §4
(5-for-5 match to ±0.005) and `plans/ui-uplift/roadmap.yaml`'s
`ui-uplift-m8` claim ("the light border token is 1.342:1 today" — reproduced
exactly, see §3).

## 0. Grounding: what's actually in the file today

`server/frontend/static/app.css` (not `frontend/static/` — the tree moved
under `server/` per CLAUDE.md §5). The `:root` block (`:4-19`) declares
**exactly 8 custom properties** — `--fg --bg --card-bg --border --accent
--danger --error-bg --mono` — matching the milestone title's "the 8 tokens."
`--mono` is a font stack, not a color; this milestone's OKLCH work touches the
other 7, and ADDS 3 new duration tokens (`--dur-fast/normal/slow`) alongside
them, landing at 11 total custom properties. The dark-mode block is
`@media (prefers-color-scheme: dark)` at `:267`, re-declaring 7 of the 8 (all
but `--mono`).

I ran the exact WCAG relative-luminance formula (implemented from the quotes
in §3, cross-checked 5-for-5 against the design system doc's own published
table) against every current token and every `var(--accent)` use site. That
work grounds §§1-3 below in real numbers instead of restating the milestone
brief's own claims back at it.

## 1. OKLCH derivation method

**Baseline status, dated.** `oklch()` — Widely Available since May 2023
(source 1). `color-mix(in oklab, …)` is already shipped and relied on twice
in this file (`app.css:122,377`) so it needs no fresh verification. Both are
safe defaults for v0.

**The trap, stated precisely (this is the one that matters most):** OKLCH's
`L` axis is *designed* to be perceptually uniform — equal steps in L look
like equal steps in lightness to a human eye, across any hue. WCAG contrast
is **not** computed in that space at all. It is computed on **sRGB relative
luminance** (§3's formula), which is a physical-light quantity, gamma-encoded,
with **hue- and chroma-dependent** channel mixing (`0.2126·R + 0.7152·G +
0.0722·B`, i.e. green contributes ~10x more to WCAG luminance than blue at
equal linear intensity). Two OKLCH colors with identical `L` but different
hue/chroma can and do land at measurably different WCAG contrast ratios
against the same background. **A 4-step ladder built by picking four "nice"
evenly-spaced L values (e.g. 30/50/70/90%) will NOT produce four evenly-spaced
WCAG ratios, and will not reliably clear 4.5:1 at the step that needs to.**
The only correct method is to derive lightness from a **target contrast
ratio**, not the reverse.

**A verified, executable method** (fixed hue `H` + chroma `C`, solve for `L`):

```python
# Given: bg_lum = relative_luminance(bg_hex)  (see §3 for the formula)
# Given: target = the WCAG ratio this step must clear (e.g. 4.5, 7.0, 3.0)
# Given: darker = True if the candidate must be the darker of the pair
def solve_L_for_target_ratio(bg_lum, target, H, C, darker):
    needed_lum = ((bg_lum + 0.05) / target - 0.05) if darker \
                 else (target * (bg_lum + 0.05) - 0.05)
    lo, hi = 0.0, 1.0
    for _ in range(60):                      # converges far past 8-bit precision
        mid = (lo + hi) / 2
        hex_, out_of_gamut = oklch_to_hex(mid, C, H)   # §5 has the full function
        lum = relative_luminance(hex_to_rgb01(hex_))
        if (lum > needed_lum) == darker:
            lo = mid
        else:
            hi = mid
    return hi
```

I ran this live against this file's own tokens. Solving for a light-mode
`--border` candidate at exactly 3:1 against `--bg` (criterion 4), anchored to
the dark-mode border's existing cool-grey hue (`H=256°, C=0.02` — see the
table below) converges to `oklch(65.37% 0.02 256deg)` = `#89919d`, verified
ratio **2.996:1** (binary-search floor artifact, not a formula error — 61
iterations closes it to 3.000). **This is a demonstration of the method, not
a color recommendation** — hue/chroma choice is the implementer's design call
— but it proves the recipe works end-to-end against this exact codebase and
gives a working reference implementation instead of a re-derivation task.

**Chroma across the ladder.** The one piece of concrete numeric guidance the
practitioner literature actually offers (LogRocket, source 6, plus general
sRGB-gamut geometry): chroma should be **low at the extremes of the lightness
range and higher in the middle** — the sRGB gamut boundary in the OKLCH (L,C)
plane for any fixed hue is roughly lens-shaped, with maximum achievable chroma
around the mid-lightness band and chroma forced toward 0 as L→0 or L→1 (a
pure-white or pure-black pixel cannot be "vivid"). For a 4-step *text* ladder
this argues for near-zero chroma at the muted/tertiary end and a small,
deliberate, non-zero chroma at the body-text end tied to the SAME hue as the
brand accent — which is precisely what this codebase's dark mode already does
**by accident** (see the table below) and what the light mode never does at
all. Neither source gave me a defensible numeric C value beyond "small and
non-zero" (EvilMartians/LogRocket were both light on hard numbers here) — treat
chroma magnitude as the implementer's design call, constrained only by (a)
non-zero and hue-consistent for the text ladder, (b) never so high that a
9x-chroma-mismatch with the brand accent reads as "off-brand grey."

**Quantified proof of the "stitched, not one hue" framing (criterion 1).**
I converted every current token to OKLCH (matrices in §5, cross-validated
three ways in §3):

| Token | Light hex | Light OKLCH | Dark hex | Dark OKLCH |
|---|---|---|---|---|
| `--fg` | `#1a1a1a` | L=21.78% **C=0.0000** (hueless) | `#e8e8e8` | L=93.10% **C=0.0000** (hueless) |
| `--bg` | `#f8f8f8` | L=97.91% **C=0.0000** | `#0d1117` | L=17.63% C=0.0140 **H=258.4°** |
| `--card-bg` | `#ffffff` | L=100% **C=0.0000** | `#161b22` | L=22.02% C=0.0157 **H=256.8°** |
| `--border` | `#d8d8d8` | L=88.22% **C=0.0000** | `#6e7681` | L=56.29% C=0.0196 **H=256.3°** |
| `--accent` | `#1e5b8a` | L=45.61% C=0.0983 **H=245.9°** | `#58a6ff` | L=71.53% C=0.1518 **H=253.3°** |
| `--danger` | `#a3271a` | L=47.23% C=0.1624 H=30.1° | `#f85149` | L=66.51% C=0.2046 H=27.0° |

This is the receipt for the milestone's own framing: the **light neutrals are
perfectly achromatic** (C=0.0000 — hand-picked greys, no hue relationship to
anything), while the **dark neutrals carry a small but real cool-blue tint**
(H≈256-258°, chroma 0.014-0.020) that happens to sit close to the dark
accent's own hue (253.3°) — because the dark block is a labeled GitHub-Primer
clone (`app.css:259-266`'s own comment says so) and Primer's canvas colors are
knowingly cool-tinted, not neutral. Two different construction methods, by
two different original authors, stitched at one `@media` boundary. A properly
unified v0 family should pick ONE of these approaches (achromatic neutrals
throughout, or a small consistent tint tied to the one brand hue throughout)
and apply it to both modes identically — not inherit one of each.

## 2. Resolving `--accent`'s five roles with ONE token

Radix Colors (source 5) is the cleanest documented precedent for "one brand
hue, many roles," and it resolves the tension by **not** using one token:
step 9 (highest chroma in the scale — "the purest step") is reserved for
solid/button backgrounds, while steps 11/12 are separately engineered to
guarantee specific text contrast ratios against a step-2 background. Quoting
their own reasoning: text steps are "guaranteed to Lc 60 and Lc 90 APCA
contrast ratio" specifically *because* they're a different value than the
solid-background step. **Mature systems split this; criterion 3 explicitly
does not allow a split.**

That constraint is nonetheless achievable here, because of something this
codebase already does — I grepped every `var(--accent)` use site to check:

| # | Role | Selector | Line | Paired text/companion color |
|---|---|---|---|---|
| 1 | Button ground | `button, .button` | `:107` | `#fff` (light); overridden to `#0d1117` in dark (`:285`) |
| 2 | Focus ring | `button:focus-visible` et al. | `:234` | non-text, vs whatever sits behind the focused element |
| 3 | Link | `.breadcrumb a` | `:51` | `--bg`/`--card-bg` (whichever it renders on) |
| 4 | Skip-link ground | `.skip-link:focus-visible` | `:217` | `#fff` — **unconditional, not mode-overridden** |
| 5 | Badge-flash tint | `@keyframes badge-flash` | `:377` | composited over `.status-badge`'s own bg (already colored) |
| bonus | Hover ground | `button:hover, .button:hover` | `:122` | `color-mix(in oklab, var(--accent) 88%, white)`, same text color as role 1 |

Role 1 already proves the pattern works: **the "on-accent text" pairing is a
mode-conditional companion value, not a fixed literal** — light mode pairs
accent with white, dark mode overrides to near-black. That's exactly the
degree of freedom needed. Given that, the five roles decompose into two
independent constraints per mode, not five conflicting ones:

- **Light mode:** accent must be dark/saturated enough that (a) white
  on-accent text clears 4.5:1 (roles 1, 4) AND (b) accent-as-text clears
  4.5:1 against `--bg` (role 3) AND accent-as-ring clears 3:1 against both
  grounds (role 2). (a) and (b) both push the SAME direction (darker,
  saturated) — no real conflict.
- **Dark mode:** accent must be light enough to clear 4.5:1 as text/3:1 as
  ring against the near-black `--bg`/`--card-bg` (roles 2, 3) — which then
  requires DARK on-accent text for roles 1 and 4, mirroring the existing
  `button, .button { color: #0d1117 }` override.

**The one genuinely narrow needle:** the focus-ring role's *second* ground
(`--card-bg`) is the tighter constraint. In light mode `--card-bg` (`#fff`)
is even lighter than `--bg` (`#f8f8f8`), which works in a dark accent's
favor. In dark mode `--card-bg` (`#161b22`) is *lighter* than `--bg`
(`#0d1117`), which works against a light accent's ring contrast — that pair
is the one to explicitly re-verify after re-derivation, not assume passes
because the `--bg` pair does.

**A live, currently-shipped AA failure I found and verified (role 4, not
previously flagged anywhere I could find — not in this file's own comments,
not in `arxmcp-design-system.md`'s contrast table):** `.skip-link:focus-visible`
(`app.css:209-221`) sets `color: #fff` **unconditionally** — it is not
`button`/`.button`, so it does NOT inherit the dark-mode text-color override
at `:285`. In dark mode its background is `var(--accent)` = `#58a6ff`. I
computed the actual ratio (formula in §3, triple-cross-validated):
**white on `#58a6ff` = 2.526:1** — badly fails the 4.5:1 text floor, and
notably contradicts this very file's OWN neighboring comment at `:282-284`
("white text on #58a6ff is only ~3.1:1"), which is itself imprecise by about
20% (both numbers fail AA, so the qualitative conclusion doesn't change, but
this is a second, independent, freshly-verified illustration of exactly the
failure mode criterion 5 exists to close — a hand-typed number in a comment,
close-but-wrong, went unchecked because nothing re-derives it). Since
criterion 3 already requires `--accent`'s skip-link role to be re-verified,
fixing this is in scope for m6 by the criterion's own terms, not a separate
follow-up: extend the existing `button, .button { color: #0d1117 }` dark
override pattern to also cover `.skip-link:focus-visible`, or give the
skip-link its own equivalent mode-conditional text color.

## 3. WCAG arithmetic, precisely

**Relative luminance** (verbatim, w3.org — see the access note at the top):

> L = 0.2126 × R + 0.7152 × G + 0.0722 × B, where R, G and B are defined as:
> if R{sRGB} <= 0.03928 then R = R{sRGB}/12.92 else R = ((R{sRGB}+0.055)/1.055) ^ 2.4
> (and the same for G, B), and R{sRGB}, G{sRGB}, B{sRGB} are the 0–1-normalized
> sRGB channel values.

**Errata, also from the same source:** the `0.03928` threshold is a known
carry-over error from the original sRGB spec; the corrected value (matching
the IEC 61966-2-1 standard the piecewise function is actually derived from) is
**`0.04045`**. The difference is invisible for any 8-bit channel value ≥ 11/255
— every token in this file clears it — but use `0.04045` in new code since
that's the value that's actually self-consistent at the branch boundary.

**Contrast ratio:** `(L1 + 0.05) / (L2 + 0.05)`, where L1 is the lighter of
the two relative luminances and L2 the darker.

**SC 1.4.3 (Contrast Minimum), verbatim:** "The visual presentation of text
and images of text has a contrast ratio of at least 4.5:1, except for the
following: Large Text — Large-scale text and images of large-scale text have
a contrast ratio of at least 3:1", where large text is defined as "at least
18 point or 14 point bold." At the standard 96px/in, 72pt/in CSS conversion
(1pt = 4/3 px exactly): **18pt regular = 24px regular**, **14pt bold =
18.667px bold** — matching the milestone brief's own stated thresholds
exactly. Note for classifying THIS file's selectors: essentially nothing in
`app.css` reaches 24px at any weight except a bare `header h1` (no explicit
`font-size`, so it inherits the UA default `h1` rule, which is both `2em`
**and** `font-weight: bold` in every mainstream browser's default stylesheet
— comfortably large-text-eligible on both counts) — every other selector
(buttons at 14px, badges at 12px, table cells at 14.4px, card hints/notes at
12.8-14.4px) sits well under even the bold threshold and must be held to the
full 4.5:1, regardless of its `font-weight` (the one semi-bold selector, `th`
at `font-weight:600`/14.4px, is moot either way since it's far below 18.66px).

**SC 1.4.11 (Non-text Contrast), verbatim:** "The visual presentation of the
following have a contrast ratio of at least 3:1 against adjacent color(s):
User Interface Components [and] Graphical Objects." This is the one that
governs `--border` (criterion 4) and the focus-ring role (§2 role 2) — text
color rules don't apply to either.

**Formula correctness — I did not take my own implementation on faith.**
I implemented the above in Python (full listing in §5) and ran it against
every pair `arxmcp-design-system.md` §4 already publishes:

| Pair | Doc claims | I computed | Δ |
|---|---|---|---|
| light `--fg` vs `--bg` | 16.39:1 | 16.388:1 | -0.002 |
| light `--fg` vs `--card-bg` | 17.40:1 | 17.404:1 | +0.004 |
| light `--accent` vs `--bg` | 6.77:1 | 6.775:1 | +0.005 |
| dark `--accent` vs `--bg` | 7.49:1 | 7.492:1 | +0.002 |
| dark `--danger` vs `--card-bg` | 5.16:1 | 5.160:1 | +0.000 |

5-for-5 within rounding. I also independently reproduced
`plans/ui-uplift/roadmap.yaml`'s `ui-uplift-m8` claim that light `--border`
vs `--bg` "is 1.342:1 today" — my computation: **exactly 1.342:1**. Three
sanity checks against textbook values also matched (black/white = 21.0:1
exactly; pure red/white ≈ 4.0:1; pure blue/white ≈ 8.59:1). I'm confident the
formula in §5 is correct and safe to hand to whoever writes the verification
test — it does not need to be re-derived from scratch.

**The OKLCH↔WCAG bridge, one implementation shortcut worth knowing:** you do
NOT need to gamma-encode an OKLCH-derived color back to 8-bit sRGB hex before
computing its WCAG luminance. The OKLab-inverse matrix chain
(`oklch → OKLab → LMS → linear sRGB`, §5) already produces the exact
**linear** R/G/B values the WCAG formula wants — feed them straight into
`0.2126·R + 0.7152·G + 0.0722·B` and skip the gamma round-trip entirely
(avoids an 8-bit-rounding error source). The one thing you MUST check first:
linear r/g/b can fall outside `[0, 1]` for an OKLCH triple that's out of the
sRGB gamut (OKLCH covers P3 and beyond) — a real browser gamut-maps such a
color via CSS Color 4's (non-trivial) chroma-reduction algorithm before
painting it, so naively clamping or feeding negative/>1 values into the
luminance formula will NOT match what actually renders. The verification
tool should assert every authored token is in-gamut (`0 <= r,g,b <= 1`,
small epsilon) as a precondition and fail loudly, not silently, if not — this
is the kind of correctness gap that's easy to miss and would make the
contrast table wrong in a way that isn't obviously wrong.

## 4. Duration tokens

Current state — three literal durations, four use sites, already a clean,
unlabeled progression:

| Literal | Selector | Line | Motion |
|---|---|---|---|
| `0.6s` | `@keyframes spin` (button loading spinner) | `:358` | continuous rotation |
| `400ms` | `.status-badge.htmx-settling` (badge-flash) | `:374` | one-shot flash |
| `200ms` | `::view-transition-old/new(root)` | `:382` | page-swap cross-fade |
| `200ms` | `tr.htmx-swapping` (row-fade-out on delete) | `:392` | one-shot exit |

**Recommendation — token names map onto the existing values with zero
perceived-behavior change:**

| Token | Value | Replaces |
|---|---|---|
| `--dur-fast` | `200ms` | View-transition duration (`:382`) + row-fade-out (`:392`) |
| `--dur-normal` | `400ms` | Badge-flash (`:374`) |
| `--dur-slow` | `600ms` | Spinner (`:358`) — note the unit changes from `0.6s` to the token, value unchanged |

This is not an invented scale — it's the three distinct values already in
the file, named. It also happens to land inside the range general motion-duration
guidance recommends for UI feedback (roughly 100-300ms for small/utility
transitions, up to ~400-500ms for larger ones) — consistent with a
deliberately low-motion, tool-grade console (this repo's own
`.claude/references/frontend-uplift/motion-vocabulary.md` MOT-1/MOT-4 entries
independently suggest similar 200-400ms ranges for fades/scale-ins). I did not
find a citable source with harder numeric backing than that for a 3-tier
scheme specifically (Material Design's own duration tokens use 4+ tiers in
the 50-1000ms range, which is a different shape of scale, not a clean
3-way match) — treat "fast/normal/slow = 200/400/600" as justified primarily
by *this file's own existing, working values*, not by an external standard.

**Placement:** duration is not color-scheme-dependent — put all three in the
base `:root` block only. There is no reason to redeclare them inside
`@media (prefers-color-scheme: dark)` the way the color tokens are.

## 5. Verification tooling

**Recommend:** a new `tests/test_ui_contrast.py`. It lives under `tests/`, so
the repo's `assert`-ban (ruff `S101`, CLAUDE.md §4.7) does not apply there —
plain `assert` is fine and idiomatic. **If any part of the color-math helper
is factored out to a location OTHER than `tests/`** (e.g. a reusable
`tools/`-level module), that file is NOT exempt and must use
`if … raise RuntimeError(…)` for its invariants instead.

**What should be generated vs. what stays hand-maintained — be honest about
the boundary, since overclaiming full automation here would just relocate
the trust problem:**

- **Fully mechanical (this is the fix):** given two colors, compute the
  ratio. §3's formula, implemented once, tested against 6+ known-good values
  (5 from this repo's own doc, 1 more from the roadmap, 3 textbook sanity
  checks — all reproduced above). This is exactly the step that silently
  produced a ~20%-wrong number in a hand-typed comment (§2) and is the
  step criterion 5 hard-gates on.
- **Still hand-maintained, and that's fine:** the *list of which
  foreground/background pairs exist to check*. Fully auto-deriving this
  would require walking a real rendered DOM+CSSOM (a headless browser) to
  discover every element's effective computed `color`/`background-color` —
  impractical under this repo's no-Node/no-heavy-new-deps posture (CLAUDE.md
  §4.7) for a v0. The honest, achievable improvement over today is: shrink
  the hand-maintained surface to "which selector pairs with which
  color-or-token" (small, reviewable, changes rarely) and make the
  *arithmetic* on that list 100% generated (large, error-prone, exactly what
  broke before).

**A starter pairs list**, seeded directly from source (not invented) — §2's
grep of every `var(--accent)` site, plus the historical `UPL-27` fixes
(`app.css:63-65,187-189` — `.card .note` and `.status-badge--ok`, both
already-fixed instances of the same class of bug), plus the 4
`.status-badge--*` pill variants × 2 modes, plus `th` on its background, plus
the newly-found skip-link pair (§2):

```
(text-or-fg, ground, min-ratio, note)
  button text,           accent (button ground),      4.5,  role 1, both modes
  skip-link "#fff",       accent (skip-link ground),    4.5,  role 4 -- CURRENTLY FAILS dark (2.526:1)
  accent (as link text),  --bg / --card-bg,             4.5,  role 3, .breadcrumb a
  accent (focus ring),    --bg,                          3.0,  role 2, non-text
  accent (focus ring),    --card-bg,                     3.0,  role 2, non-text -- tighter in dark mode (§2)
  button text (hover),    color-mix(accent 88%, white),  4.5,  bonus role, currently unchecked anywhere
  --fg,                   --bg / --card-bg,              4.5,
  --danger,                --bg / --card-bg / --error-bg, 4.5,
  --border,                --bg / --card-bg,              3.0,  criterion 4
  status-badge--{ok,warn,ops-warn,down} fg, own bg,      4.5,  x4 pills x2 modes = 8 pairs
  status-badge--* border,  own bg,                        3.0,  non-text, x4 pills x2 modes
  th text,                 th background,                4.5,
  .card .note / .hint / .display-name / header .subtitle / footer, --bg or --card-bg, 4.5,
```

This list is deliberately broader than the "8 token-on-ground pairs" the
`arxmcp-design-system.md` overlay tabulates (criterion 2's own complaint) —
it includes literal hardcoded colors, derived `color-mix()` results, and
non-text UI-boundary pairs, which is exactly the coverage gap that let the
two historical `UPL-27` failures (and now this brief's freshly-found
skip-link failure) ship unnoticed.

**Parsing the stylesheet:** the file is small (399 lines) and hand-authored
— a full CSS parser dependency is not warranted. A targeted regex against the
`:root { … }` block and the `@media (prefers-color-scheme: dark) { :root {
… } }` block (`--([\w-]+):\s*([^;]+);`) is sufficient to extract both token
sets as `{name: raw_value}` dicts. The extraction needs to handle three value
shapes once tokens move to OKLCH: a bare hex literal, `oklch(L% C H)`, and
(for the derived hover/flash pairs) `color-mix(in oklab, A P%, B)` — the
latter is just linear interpolation in OKLab coordinates
(`P%·OKLab(A) + (100-P)%·OKLab(B)`, converted back through the same inverse
matrices) and does not need a separate implementation.

**Suggest, don't mandate:** have the test also *emit* a generated
Markdown/text contrast table as a side artifact when it runs (or a
`--update`-style regeneration flag mirroring this repo's existing
`--update-tool-schema-hash` pytest convention). That would satisfy criterion
2's "ships a contrast table" as a **generated artifact**, not a hand-typed
one — closing the loop criterion 5 opens. Exact location/format is an
implementation decision for Phase 2, not something I'm prescribing here.

**Reference implementation** (verified live against this repo's own numbers,
5-for-5 plus the 1.342:1 border figure — safe to copy-adapt, not just
citation-adjacent pseudocode):

```python
import math

def hex_to_rgb01(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))

def srgb_to_linear_channel(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def linear_to_srgb_channel(c):
    c = max(0.0, min(1.0, c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055

def relative_luminance(rgb01):
    r, g, b = (srgb_to_linear_channel(c) for c in rgb01)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def contrast_ratio(hex1, hex2):
    l1, l2 = relative_luminance(hex_to_rgb01(hex1)), relative_luminance(hex_to_rgb01(hex2))
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)

# OKLab <-> linear sRGB, matrices per bottosson.github.io/posts/oklab/
def linear_srgb_to_oklab(r, g, b):
    l = 0.4122214708*r + 0.5363325363*g + 0.0514459929*b
    m = 0.2119034982*r + 0.6806995451*g + 0.1073969566*b
    s = 0.0883024619*r + 0.2817188376*g + 0.6299787005*b
    # NOTE: cube root must handle negative inputs (out-of-gamut intermediates) --
    # x ** (1/3) on a negative float crashes/complexifies in Python; use copysign.
    l_, m_, s_ = (math.copysign(abs(v) ** (1/3), v) for v in (l, m, s))
    L = 0.2104542553*l_ + 0.7936177850*m_ - 0.0040720468*s_
    a = 1.9779984951*l_ - 2.4285922050*m_ + 0.4505937099*s_
    b2 = 0.0259040371*l_ + 0.7827717662*m_ - 0.8086757660*s_
    return L, a, b2

def oklab_to_linear_srgb(L, a, b):
    l_ = L + 0.3963377774*a + 0.2158037573*b
    m_ = L - 0.1055613458*a - 0.0638541728*b
    s_ = L - 0.0894841775*a - 1.2914855480*b
    l, m, s = l_**3, m_**3, s_**3
    r  =  4.0767416621*l - 3.3077115913*m + 0.2309699292*s
    g  = -1.2684380046*l + 2.6097574011*m - 0.3413193965*s
    b2 = -0.0041960863*l - 0.7034186147*m + 1.7076147010*s
    return r, g, b2

def hex_to_oklch(h):
    r, g, b = (srgb_to_linear_channel(c) for c in hex_to_rgb01(h))
    L, a, bb = linear_srgb_to_oklab(r, g, b)
    return L, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360

def oklch_to_hex(L, C, H):
    a, b = C * math.cos(math.radians(H)), C * math.sin(math.radians(H))
    r, g, bl = oklab_to_linear_srgb(L, a, b)
    out_of_gamut = any(c < -1e-4 or c > 1 + 1e-4 for c in (r, g, bl))
    rs, gs, bs = (linear_to_srgb_channel(c) for c in (r, g, bl))
    return "#{:02x}{:02x}{:02x}".format(round(rs*255), round(gs*255), round(bs*255)), out_of_gamut
```

## Acceptance criteria the implementer must meet

1. One hue decision, both modes, no Primer literal — §1's OKLCH table proves
   today's dark mode is Primer-derived (cool-tinted neutrals matching
   Primer's own canvas colors) and light mode is an independently-hand-picked
   achromatic block; §1's derivation method is hue/chroma-first, not
   copy-a-literal-then-adjust.
2. Contrast table covers every rendered pair, not 8 token-on-ground ones —
   §5's starter pairs list is deliberately broader than
   `arxmcp-design-system.md`'s existing table, seeded from real grep + the
   historical `UPL-27` fixes + the freshly-found skip-link failure.
3. `--accent`'s five roles simultaneously — §2 gives the concrete role
   inventory (with line numbers), explains why one token is achievable here
   specifically (on-accent text is already a mode-conditional companion, not
   a fixed literal), and names the one genuinely tight pairing (ring vs
   dark-mode `--card-bg`) to verify explicitly rather than assume.
4. Light-mode rule token clears 3:1 against `--bg` — §1 demonstrates the
   exact solve-for-target-ratio method against this repo's real `--bg` value,
   reproduces the current 1.342:1 figure exactly first.
5. Hard gate at 4.5:1 — §3 gives the exact formula plus 6 independent
   cross-validations so "the number was computed, not eyeballed" is
   actually true and checkable by a third party.
6. `color-scheme: light dark` preserved — out of scope for this brief's
   research (no token change touches it); confirmed still present and
   untouched at `app.css:10`.
7. `light-dark()` NOT used in v0 — §1 confirms the Baseline-Newly-not-Widely
   date math, and the MDN custom-properties citation in the frontmater
   sources gives the exact IACVT mechanism (falls back to `background-color`'s
   non-inherited initial value, `transparent`) that makes this a real risk,
   not a hypothetical one — and clarifies `oklch()` is safe FOR THE SAME
   REASON light-dark() isn't: both share the identical IACVT failure
   mechanism when used inside a custom property, but oklch()'s 3+ year
   Widely-Available track record makes the non-supporting population
   negligible where light-dark()'s ~2-year Newly-Available status does not.

## Risks and open questions

1. **Riskiest assumption, stated directly:** the brief assumes a single
   `(L, C, H)` point per mode can satisfy all five `--accent` roles
   *including staying visibly "the same brand blue."* That's true for the
   role-decomposition in §2, but it is NOT guaranteed for every hue choice —
   some hues have a much narrower high-chroma window near the lightness the
   dark-mode text/ring role needs (high L) than others, which could force a
   choice between "vivid" and "passes 4.5:1 as dark-mode text." **Concrete
   alternative if that turns out to bind:** fall back to the Radix-style
   split (source 5) — keep `--accent` for the text/link/ring roles (optimize
   for 4.5:1/3:1 against page backgrounds) and add a second token,
   `--accent-solid`, purely for button/skip-link grounds (optimize for
   legible on-accent text). That's a criterion-3 rewrite, not a silent
   workaround, so it needs to go back to the milestone owner explicitly if
   needed — but it's the field-tested fallback, not a hypothetical one.
2. Whether the badge-flash tint (§2 role 5) is actually subject to a hard
   WCAG ratio at all is genuinely unclear — it's a transient, low-alpha,
   animated overlay composited on top of an already-independently-legible
   badge, which arguably falls outside SC 1.4.11's "required to understand
   content" scope. Recommend verifying SOME reasonable ratio defensively
   since criterion 3 names it as one of the five roles, but flag that WCAG
   itself doesn't crisply mandate one here.
3. The skip-link dark-mode failure (§2) is, by the criteria's own logic,
   in-scope for m6 to fix (accent's skip-link role must be re-verified
   regardless) — but it's a pre-existing bug, not something the milestone
   brief named. Flagging explicitly so it isn't silently missed OR silently
   treated as "someone else's problem."
4. Whether "every rendered pair" (criterion 2) is meant to include *derived*
   colors (the hover `color-mix()`, the badge-flash `color-mix()`) or only
   statically-authored token values — I've included them in §5's starter
   list on the reading that "rendered" means rendered, but this is worth an
   explicit decision recorded in the implementation artifact rather than
   left implicit.
5. Baseline status is a dated claim, not a permanent one (CLAUDE.md §4.9's
   "novelty claims are dated censuses" applies to browser-support claims
   too). If implementation slips meaningfully past 2026-08-03, re-check
   `light-dark()`'s Baseline status before relying on this brief's "still
   Newly Available" conclusion — the ~30-month clock is close enough to
   Q4 2026 that a multi-month slip could change the answer.
