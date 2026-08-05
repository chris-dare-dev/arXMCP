# ui-uplift-m13 — implementation synthesis (UPL-13 v0)

## The one idea

A live region announces **changed** text. That comparison only exists if the
element carrying `aria-live` **survives** the update. Every defect this
milestone closes is the same mistake: the region was put on the element being
replaced, so each update inserted a brand-new region with nothing to compare
against, and the AT read the whole thing out again.

`ui-attractive-polish-m1` established the opposite rule — *the swap result must
re-declare the region, or it goes silent after the first swap* — and that rule
is CORRECT for a swap triggered by a user action. It is wrong for a timer. m13
splits the rule on that axis rather than reversing it.

| target | replaced by | treatment |
|---|---|---|
| `#display-name-block`, `#papers-tbody` | a user action | unchanged — fragment re-declares the region |
| `#ingest-status` | a 2s poll | region moved to `#ingest-live`, never swapped |
| `#status-badge` | a 10s poll | region moved to `#status-live`, never swapped |

## AC#1 — the 2s poll

`<div id="ingest-live" aria-live="polite" aria-atomic="true">` now wraps
`#ingest-status`, which is still the `hx-swap="outerHTML"` target. All four
`_ingest_status_fragment` branches stopped emitting the attributes; nesting a
region inside the wrapper would put the per-tick announcement back on the inner
node.

**A wrapper, not `hx-swap="innerHTML"`.** Both make the region persist.
`innerHTML` would leave `hx-trigger="every 2s"` on the surviving element
permanently, discarding the defence-in-depth half of the stop mechanism —
terminal fragments OMIT the trigger *and* the endpoint returns HTTP 286.
Keeping `outerHTML` keeps both halves.

## AC#2 — the six error blocks, and the finding the brief did not carry

The six became `<output>` (implicit `role="status"`), so the explicit attribute
is gone and the announcement is not.

The brief treats those six as surplus regions. They were **cargo**:
`app.css` carried `pre.error:empty { display: none; }`, and a `display: none`
element is not in the accessibility tree. All six are empty at first paint, so
the regions did not exist when an AT would register them; the error path then
set `.textContent`, which in one frame both filled the element and made
`:empty` stop matching — inserting an already-populated live region, which is
the canonical way to announce nothing. Migrating to `<output>` while keeping
`display: none` would have reproduced the defect one element later, so the
empty state is now zero-footprint instead of unrendered.

`.error` replaced `pre.error` throughout (including the tabular-nums scope list,
whose set-equality guard would otherwise fail) because two element types now
share the treatment.

## AC#3 — the exclusion, and why it is not arbitrary

`<output>` is phrasing content; `_ingest_status_fragment`'s failed branch emits
`<pre class="error">`, which is flow content. `<pre>` inside `<output>` is
invalid, so the ingest region keeps its `<div>` and gets the wrapper instead.
Pinned from both sides: the region must not be an `<output>`, and the failed
branch must still emit the `<pre>` that is the reason.

## AC#4 — sequencing with m12

m12's HARD CONSTRAINT names m13 as the near-miss: **no swap may target the
`<details>` or any ancestor of it**. m13's roadmap summary ("move `aria-live`
onto a stable never-swapped wrapper") is that violating shape if the wrapper
goes *around the disclosure* and is polled. `#ingest-live` sits **inside** the
ingest block, wraps only `#ingest-status`, is never a swap target and carries no
`hx-*`. m12's `TestStructuralInvariantsHoldInTheRenderedTree` enforces this and
stayed green throughout.

## What changed in the guards, and why none were deleted

`tests/test_ui_a11y_baselines.py`'s UPL-3 class asserted the m1 rule for the
polled targets. Its premise is what m13 makes false, so it was **inverted, not
removed** — same property, opposite polarity — and its module docstring now
states the user-action-vs-timer split as the rule rather than the old blanket
one. Deleting it would have left the strongest version of the defect untested.

## Verification

- `tests/test_ui_m13_live_region_hygiene.py` — 18 tests. **6 mutations injected
  and confirmed to fail** (region back on the swap target ×2, wrapper made a
  swap target, an error block reverted to `<pre aria-live>`, `display: none`
  restored, a fragment branch re-declaring the region), control green.
- Full suite: the documented 8 environment-bound failures, no new ones.
  `ruff check .` clean.
- **Not observed in a browser** — see finding M2, deferred for that reason.
