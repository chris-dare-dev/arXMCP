---
milestone_id: "ui-uplift-m6"
phase: "rectify"
rectification_commit: "150f28eaa2669a7e46d736130f6884a933c45e09"
critics_run:
  - milestone-adversary-critic
  - milestone-arxmcp-critic
finding_counts: { critical: 0, high: 3, medium: 9, low: 4 }
fixed: [H1, H2, H3, M1, M2, M3, M4, M5, M6, M7, M8, L1, L2, L3, L4]
deferred: [M9]
invalidated: []
external_writes_required:
  - "git push origin main"
---

# Rectify summary — ui-uplift-m6

## Re-verification

All 16 anchors re-verified against live code before any fix — **16/16 found,
0% invalidation**. The critics worked from current code.

## The theme both critics found

m6's headline discipline is *"no contrast number is typed by a human anywhere
in this milestone"*, over *"EVERY rendered pair"*. Both critics independently
falsified both halves inside the milestone's own artifact and its own
registry — and the register clustered three of their findings at the same two
lines. Neither claim was wrong by accident: each hole was in exactly the place
the claim's own guard structurally could not look.

## Fixed

### H1 + M8 — badge-flash replaced the pill's ground

`@keyframes badge-flash` animated `background`, which **replaces** a pill's
opaque fill rather than overlaying it. For the whole 400 ms, pill text sat on
accent@30% composited over the page ground: **3.095:1** (dark `--down`) to
4.542:1 — 6 of 8 pill texts under SC 1.4.3, inside a milestone whose AC#5
makes any sub-floor pair a ship blocker. The artifact justified skipping the
pair by describing it as a *transient 30%-opacity overlay*, which was wrong on
the facts, and AC#3's role 5 rested on that description.

It now animates `border-color` to `var(--accent)`. Every pill keeps its
designed opaque ground, so **no text pair moves at all**, and the role-5 pair
is a plain non-text boundary at 6.198–7.190:1.

**Two alternatives measured and rejected**, recorded because the second was a
critic's own proposal:

| Option | Worst pair | Verdict |
|---|---|---|
| Keep 30% fill tint, declare exempt | 3.095:1 | Carve-out from AC#5's own gate |
| Re-solve fill tint to 10% | 4.533:1 | Clears, but near-invisible |
| Inset `box-shadow` overlay (arxmcp-critic's proposal) | 3.044:1 | **Fails all 7 pills — worse than shipped** |
| **Flash `border-color`** | **6.198:1** | Chosen |

### H3 + M1 — the registry held no composited row at all

`opacity` composites **both** an element's text and its fill over what is
behind it, so it changes the ground a pair is read against. The registry had
zero composited rows, which is why an entire rendered state class — reached on
every form submit — sat outside "EVERY rendered pair".

Added `alpha_over` to `_ui_color.py` and a `fade()` spec kind to the resolver;
16 composited rows registered. `opacity` also composites the **focus ring**,
which at 0.6 measured 2.703–2.976:1 against SC 1.4.11. Raised to **0.7**, the
lowest step clearing 3:1 on every ground (binding case needs ≥ 0.66).

Deleted the `outline-width: 3px` compensation. The critic is right that it was
never valid: **SC 1.4.11 states a contrast threshold and has no width term** —
thickness is SC 2.4.13, a separate criterion — so the wider ring left the
failure exactly where it was while looking addressed.

The dimmed **label** cannot reach 4.5:1 at any opacity a person would call
dimmed. It is registered `EXEMPT` with its measured ratio and its
justification inline (`pointer-events: none` is what earns SC 1.4.3's
inactive-component exception). `test_rendered_pair_meets_wcag_floor` asserts
every EXEMPT row *carries* a justification, so an exemption cannot be added
silently — which was the finding's actual point: "an unstated exemption and an
oversight look identical from the artifact."

### H2 + M4 — the artifact hand-typed the numbers it forbade

The `--accent` roles table and the Headline block sat **outside** the single
`BEGIN/END GENERATED CONTRAST TABLE` marker pair, so
`test_published_contrast_table_is_current` structurally could not see them. 9
of 12 role cells were wrong (`6.583` vs `6.553`, `7.199` vs `7.190`, `5.037`
vs `4.981`, `6.584` vs `6.568` — several are digit transpositions, the
hand-typing tell) and the Headline's "68 (34 light, 34 dark)" split was 36/32.

Both are now generated regions rendered from the same code the gate uses, and
`test_no_ratio_is_typed_outside_a_generated_region` **enforces** the
document's central claim rather than asserting it in prose. Design targets
(the "solved for" column) and historical before-values are allow-listed
explicitly, each with a note saying why it cannot drift.

### The remaining MEDIUMs and LOWs

- **M2** — `--border`'s real binding grounds (`th`'s `#f0f0f0`, `tbody
  tr:hover`) registered for both modes. The light row-hover pair at 3.040:1 is
  now the tightest gated pair in the whole sweep — previously unguarded.
- **M3** — `tests/test_ui_color_math.py`, 20 ground-truth anchors for the
  module the entire gate and artifact depend on and which had none. Includes
  the canonical `oklch(62.796% 0.25768 29.234)` → `#ff0000` round-trip, the
  three historical published ratios at their own historical hexes, gamut
  rejection, and an assertion that `alpha_over` and `mix_oklab` **disagree**
  (if they ever agree, one is wrong). The hazard was specific: a transposed
  matrix row shifts every ratio coherently, so the gate passes and the
  artifact regenerates to match itself.
- **M5** — deleted the `0.03928` duplicate calculator, making
  `_ui_color.py`'s "single WCAG-contrast implementation" docstring true.
- **M6 + M7** — the favicon guard was a substring search over the whole file
  and `favicon.svg` embeds that hex in its own XML comment, so deleting the
  `<rect>` outright still passed. Now regex-matches the `fill` attribute.
- **L1, L2, L3** — stale UPL-27 ratio literals removed, pair counts rephrased
  so they cannot drift, the "nothing here is lifted from Primer" claim scoped
  to the `:root` block it is actually true of.
- **L4** — surface separation pinned at ≥ 1.02 in both modes, replacing a bare
  `!=` that two identical hexes would have passed.

## Three earlier-milestone tests were rewritten, not deleted

m3 and m4 pinned the exact behaviour this rectify changes. Each encoded a real
intent that survives the change, so each was rewritten to assert the intent:

- `test_htmx_request_dim_properties_are_unconditional` hardcoded `opacity:
  0.6` while actually testing *where the declaration sits*. It now finds the
  rule by pattern — hardcoding the value made an unrelated test fail on a
  contrast fix while telling us nothing about the nesting it guards.
- `test_danger_focus_ring_widened_under_htmx_request` became
  `test_in_flight_focus_ring_clears_the_non_text_floor` — m3 identified the
  right problem and reached for an invalid mechanism, so the successor asserts
  the contrast property m3 actually wanted. Plus
  `test_no_outline_width_compensation_remains` so the invalid trade cannot
  return.
- `test_flash_uses_color_mix_not_hardcoded_hex` asserted one *spelling*;
  UPL-22's real requirement is that the flash colour **derives from
  `--accent`** rather than being a stale hex. `border-color: var(--accent)`
  satisfies that more directly than the `color-mix()` it replaced.

Falsification checked on the load-bearing one: with `opacity` reverted to 0.6,
`test_in_flight_focus_ring_clears_the_non_text_floor` fails at 2.756:1.

## Deferred

- **M9** — m8's `links.code` anchors (`app.css:53-59`) were invalidated by
  m6's +100-line shift and now resolve to unrelated code. Real problem, but
  the fix is an edit to `plans/ui-uplift/roadmap.yaml`, which the pipeline's
  one-writer rule reserves for the roadmap agents. **Correct spans computed
  for the follow-up: `app.css:85-91` (the `.card` rule m8 retires) and
  `app.css:110-120` (the input rule).** Needs a `/roadmap` pass.

## Registry growth

68 → **91 pairs** (83 gated, 8 exempt). The 23 new rows are the composited
state classes, the flash role, and `--border`'s real binding grounds — every
one of them a pair that renders today and was previously unmeasured.

## Check gate results

- `ruff check .`: **PASS**
- `pytest` (full suite): **PASS relative to baseline** — the same 8
  environment-bound failures measured before any work this session (6 × macOS
  `sandbox-exec` latexml, 1 × `WindowsPath` on darwin, 1 × HuggingFace
  download). Zero new.
- `python -m tests.test_ui_contrast --update`: artifact regenerated, all three
  generated regions current.
- Findings register gate: **OK — no open findings.**
- `git status --porcelain`: clean after the commits.

## Out of scope, fixed in passing

`.claude/launch.json` hardcoded `.venv\Scripts\python.exe`, a Windows path
from the sibling PC, so the preview server could not start on macOS at all.
Changed to `uv run python`, which works on both. Not a critique finding —
found while trying to verify the CSS change in a browser.

## external_writes_required

- `git push origin main` — NOT performed. Awaiting per-event authorization
  (CLAUDE.md 4.4).
