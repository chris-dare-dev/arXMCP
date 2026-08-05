---
milestone_id: "ui-uplift-m8"
phase: "research"
briefs_synthesized:
  - "research/brief-1.md (explore)"
  - "research/brief-2.md (general)"
external_writes_required:
  - "git push origin main"
estimated_loc: "250-400"
estimated_files: "8-12"
novel_architecture: false
phase2_path: "delegated"
---

# Research synthesis — ui-uplift-m8 (UPL-2, retire `.card` / rule ladder)

Fan-in of brief-1 (explore) and brief-2 (general). Both `complete`, zero
injection attempts. Every number below re-verified by the orchestrator against
the working tree.

## The milestone has one hard problem, and it is in the design, not the code

**A graded ladder cannot be graded by lightness.** Both briefs reached this
independently. `--border` was solved to exactly 3.30:1 — it *is* the SC 1.4.11
floor — so every tint toward the ground falls under it:

| weight | light | dark |
|---|---|---|
| 100% `--border` | 3.312:1 ✅ | 3.676:1 ✅ |
| 80% | 2.533:1 ❌ | 2.677:1 ❌ |
| 70% | 2.219:1 ❌ | 2.286:1 ❌ |
| 60% | 1.960:1 ❌ | 1.959:1 ❌ |

The discovery's own "60% row rule" is therefore illegal as written. **The ladder
must be graded by thickness or style — not lightness** — or the lighter weights
need an explicit decorative declaration (SC 1.4.11 exempts purely decorative
boundaries, but that exemption has to be *stated*, and this is the milestone
that makes rules the sole structural device, so claiming the structure is
decorative is self-defeating).

This is step one of Phase 2, not a detail. An implementer reading "graded
hairline rule ladder" and reaching for tints ships three of four weights under
the floor.

## Three ACs are stale, and one AC pair is contradictory

| AC | As written | Actually |
|---|---|---|
| #4 | rule token "is 1.342:1 today" | **3.312:1 — m6 already delivered it.** Read AC#4 as a regression guard |
| #2 | "three dark-mode rules depend on `--card-bg`" | **4+**, and only 2 are dark-mode; light `th` still uses a hardcoded `#f0f0f0` |
| #3 | `th` background "1.14:1 on white" | `th` now uses `var(--card-bg)`; separation is **1.0281:1** — the concern is *more* acute |

**AC#2 and AC#3 pull in opposite directions on `th`.** AC#2 keeps `--card-bg`
as the control ground *for table headers*; AC#3 migrates the header separation
to a rule weight. `test_ui_m5_create_remove_in_place.py:570` pins the dark fill.
The resolution is **keep the fill AND add the rule** — but an implementer
reading AC#3 alone will delete the fill and break that test.

## Two silent regressions m8 introduces if nothing is done

Neither fails loudly, which is what makes them worth naming up front.

1. **`ROW_HOVER` re-grounding breaks the gate.** Re-basing it from `--card-bg`
   to `--bg` puts the registry's *tightest* pair at **2.9533:1** — under the
   3:1 floor, and the failing pair is `--border` itself. Cheapest defensible
   answer: leave `app.css:177` on `var(--card-bg)` and argue a hovered row is a
   control surface — but that must be **written into the stylesheet**, because
   an unedited line looks like an oversight.
2. **`--fg-muted` misses its own target.** m10 derived it at 7.00:1 (AAA)
   against `--card-bg`. Re-grounded to `--bg` it measures **6.8230** light /
   7.7040 dark: it fails its stated AAA target while passing the 4.5 gate, so
   **nothing fails loudly**. This is exactly the forward risk m10's critique
   (M6) recorded and m8's roadmap `links.note` carries. m8 must re-solve the
   token and register the new pairs.

## The roadmap dropped the authored design — third milestone running

The discovery authored the three weights **by name**:
`--rule-section` / `--rule-row` / `--rule-meta` (`synthesis.md:70`, with
`--rule-section` used again at `final-report.md:211` and `challenge.md:515,524`),
plus the full/60%/dotted grading and a `.lede` treatment. **The roadmap contains
zero occurrences of `--rule-`.**

m7 lost its authored `clamp()` values the same way; m10 lost five
fully-specified rules from discovery H3. Recover the names and the anatomy from
`art-direction-scout-brief.md:163-184` and `synthesis.md:233-236` rather than
inventing them — but note the grading itself is the illegal part above, so
adopt the *names* and re-derive the *grading*.

**The decoy is tool-dependent, which is worse than a plain decoy.** Under `rg`
(what the Grep tool uses) the first `UPL-2` hit is
`.claude/notes/frontend-uplifts/2026-05-ui-polish/state.json` — the **May-2026**
run. Under plain `grep` it is not. An implementer using the Grep tool lands on
the wrong milestone first; one using bash `grep` does not. Same shape as the
`UPL-9` decoy in m10, but it hides from the verification method that caught it
last time.

## Constraints that bind before a line is written

- **The binding budget is `tokens.css` at 198/200, not `app.css` at 595/600.**
  Three (or six) new `--rule-*` declarations plus this repo's mandatory
  derivation comments do not fit, and the split escape-hatch m7 used is spent.
  Either raise the 200-line bound at `test_ui_m7_type_scale.py:431` (a
  single-file edit, unlike the app.css trio) or author the ladder as
  thickness/style over one existing colour token. **Decide this first.**
- **`--rule-*` tokens hard-fail the oklch guard unless registered as
  non-colour.** `test_ui_contrast.py:514` iterates every raw token and skips
  only `--mono` / `--dur-*` / `--text-*` / `--tracking-*`. This is the m7
  `--text-*` trap verbatim; `NON_COLOUR_TOKEN_PREFIXES` is the mechanism.
- **Four named guards hard-fail on `.card` deletion**, plus BAN-R2 breaks on
  `hint` / `empty` / `display-name` — those selectors die with the primitive
  and their declarations must land somewhere that still exists.
- **AC#1 has no derived guard today.** "No `.card` primitive remains" is
  currently unfalsifiable; m8 should ship the check that makes it true.
- **Baseline: all 9 candidates ship** — `:has()` and CSS Nesting both crossed
  Widely within the last 8 weeks. Verified with dates; nothing here is barred.
- **`.card` is a `<section>`.** "Delete the primitive" is a CSS instruction.
  Deleting the *element* changes the document outline and landmark navigation
  and is a larger change — decide explicitly which one is meant.

## Acceptance criteria for Phase 2

1. No `.card` primitive; structure carried by three rule weights **named
   `--rule-section` / `--rule-row` / `--rule-meta`** per the discovery.
2. The ladder is graded by **thickness or style, not lightness** — every weight
   that carries structure clears 3:1, or is explicitly declared decorative.
3. `--card-bg`'s successor role stated in the stylesheet; all 4+ consumers
   classified control-ground or panel-ground.
4. `th` keeps its fill **and** gains the rule (AC#2 ∧ AC#3, not AC#3 alone).
5. `ROW_HOVER` and `--fg-muted` handled deliberately, with the reasoning
   written into the stylesheet — not left as unedited lines.
6. A derived guard for AC#1.
7. Registry re-grounded; artifact regenerated; ruff clean; suite green against
   the known 8.

## Open questions for Phase 2

1. **How is the ladder graded** — thickness (1px/2px/3px), style (solid/dashed/
   dotted), or one weight plus spacing? This is the design decision.
2. **Raise the `tokens.css` bound, or avoid new tokens entirely?**
3. **Does the `<section>` element survive?**

## Phase 2 path decision

**Path: `delegated`.** 250–400 LOC across 8–12 files (`app.css`, `tokens.css`,
both templates, the three cap tests, the contrast registry, the coverage test,
the artifact). Above the ≤5-file inline threshold on file count alone, and the
registry re-grounding touches a large fraction of 99 pairs.

## External writes required

```
external_writes_required: ["git push origin main"]
```
