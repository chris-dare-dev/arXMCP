---
name: generated-artifact-hand-typed-outside-markers
description: A milestone that ships a GENERATED artifact + a staleness gate almost always hand-types the prose/summary numbers OUTSIDE the BEGIN/END markers — recompute every one of them
metadata:
  type: feedback
---

When a milestone's headline deliverable is a **generated** artifact guarded by a
staleness test, check the region the gate does NOT cover. The gate compares only
what sits between `<!-- BEGIN GENERATED … -->` / `<!-- END … -->`; headline
tables, "method" prose, and per-role summary tables above them are hand-typed
and structurally unguarded — while the document simultaneously claims "computed,
never typed."

**Why:** `ui-uplift-m6` (2026-08-04) shipped
`.claude/docs/ui-contrast-table.md` with a generated 68-row table AND a
hand-written `--accent` five-roles table above it. **9 of 12 cells were wrong**
(6.583 vs 6.553; 7.199 vs 7.190; 5.037 vs 4.981; 6.584 vs 6.568). Several are
digit transpositions — the classic hand-typing tell. `test_ui_contrast.py`'s
docstring asserted "No contrast number is typed by a human anywhere in this
milestone." Both the artifact and the test module were wrong about themselves.
This is the same document that cites "a comment in app.css that stated a ratio
~20% off" as its motivating incident.

**How to apply:** For any milestone shipping a generated doc: (1) locate the
marker pair, (2) recompute EVERY number outside it using the milestone's own
helper module, (3) grep the doc for numeric literals outside generated regions.
The fix is cheap and always the same — emit the summary table from the same
function the assertions already call.

## Sibling shape from the same run: "EVERY X" sweeps skip composited states

`PAIRS` registries built by hand for an "every rendered pair" gate reliably omit
pairs that only exist after **compositing**: `opacity: <1` on an ancestor,
`@keyframes` that animate `background`, and `color-mix(…, transparent)`.

- `opacity: 0.6` on a button composites BOTH its text and its background over
  the parent, collapsing their mutual ratio (measured 2.787:1 vs a 4.5 floor).
  The stylesheet's own comment already knew the focus ring fell to ~2.57:1 and
  "compensated" with `outline-width` — SC 1.4.11 is a contrast threshold with
  no width trade (thickness is WCAG 2.2 SC 2.4.13 *area*, a different rule).
- `@keyframes f { from { background: color-mix(in oklab, X 30%, transparent) } }`
  **replaces** the element's opaque background for the animation's whole
  duration — it is not an overlay. Any justification phrased as "a translucent
  tint over an already-legible surface" is factually wrong; the text lands on
  the tint over the *parent's* ground.

Related: [[claim-drift-verify-against-code]], [[vacuous-test-kept-as-documentation]],
[[test-wiring-and-coverage-gaps]].
