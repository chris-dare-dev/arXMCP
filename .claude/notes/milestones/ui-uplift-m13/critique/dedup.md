# ui-uplift-m13 — critique (inline, self-adversarial)

Phase 3 run inline rather than via the critic sub-agents. Every finding below
was reproduced against the working tree before being written down, and the
five guard mutations in §Verification were executed.

## H1 — `#status-badge` carries the IDENTICAL defect, on every page, forever

**Where:** `server/frontend/templates/base.html` (`id="status-badge"`),
`server/routes/ui.py::ui_status_badge`

**What:** the badge `<span>` carries `aria-live="polite" aria-atomic="true"`
AND is the `hx-swap="outerHTML"` target of `hx-trigger="load, every 10s"`. The
server fragment re-emits both attributes, on the same m1 reasoning m13 has just
inverted for the ingest region. Every 10 seconds the whole composite string
("READY · corpus v… · N notebooks") is announced again, changed or not.

**Why it matters:** this is not an adjacent surface — it is **one of the twelve
live regions the milestone's own census counts**, it lives in `base.html` so it
is on *every* page including the index, and unlike the ingest poll it has no
terminal state: it re-announces for as long as the tab is open. Shipping
"stop the 2s poll re-announcing" while leaving a 10s poll doing the same thing
would make the milestone's title true and its purpose false. The brief's AC set
does not name it, which is the gap — the ACs were written from the ingest
symptom, and the census sentence is what actually scopes the work.

**Fix:** the same wrapper shape, in phrasing content: a never-swapped
`<span id="status-live" aria-live="polite" aria-atomic="true">` around the
badge; drop both attributes from the badge and from the fragment.

## M1 — `index.html`'s `create-error` is now the odd one out, undocumented

Six error blocks migrated to `<output>`; `#create-error` on the index page did
not. That is defensible — m12 scoped v0 to the detail page and the index half
belongs to m11/m19 — but it leaves the only remaining `.error` carrying an
explicit `aria-live`, and nothing in the repo says why. An inconsistency
without a recorded reason reads as an oversight to the next agent.

**Fix:** record it at the site.

## M2 — the empty-state collapse is derived, not observed

`.error:empty` dropping `display: none` for a zero-footprint box is reasoned
from the CSS (`min-height: 0; padding: 0; margin: 0; background: none`, and
`:empty` outranks `.error` on specificity so ordering is not a risk). It is not
observed in a browser — this repo ships no browser harness and the preview pane
renders these as static snapshots. Six empty tinted boxes at first paint would
be an obvious visual regression, so the risk is low but non-zero.

**Fix:** none available in-repo. Recorded as a residual so the next operator
with a browser checks it deliberately rather than assuming it was verified.

## L1 — `<output>`'s implicit role is asserted by this milestone, not by a test

`test_every_error_block_is_an_output` pins the element; the claim that
`<output>` maps to `role="status"` is HTML-AAM, not something the repo can
check without an AT. Stated as the spec fact it is, and the census guard counts
implicit-role elements so a future swap back to `<div>` fails.

## Verification

Five mutations injected and confirmed to fail the new guards, control passing:

1. `aria-live` restored on the swap target → caught
2. the wrapper made a swap target → caught
3. one error block reverted to `<pre aria-live>` → caught
4. `display: none` restored on `.error:empty` → caught
5. a fragment branch re-declaring the region → caught

`tests/test_ui_a11y_baselines.py` (24) green after its UPL-3 class was inverted
rather than deleted; the full UI-adjacent selection (1114 tests) green.
