# ui-uplift-m13 — research synthesis (UPL-13 v0)

Measured against the working tree at `0457784`, not taken from the brief.

## The twelve live regions, enumerated

`notebook_detail.html` renders **eleven**; `base.html` adds `#status-badge`
(polled every 10s, outside `<main>`) for **twelve**.

| # | region | kind | how it updates |
|---|---|---|---|
| 1 | `#display-name-block` | `<p>` | outerHTML swap |
| 2 | `#papers-tbody` | `<tbody>` | `beforeend` swap |
| 3 | `#topic-block` | `<div>` | outerHTML swap |
| 4 | `#discover-results` | `<div>` +atomic | outerHTML swap |
| 5 | `#ingest-status` | `<div>` +atomic | **outerHTML swap every 2s** |
| 6–11 | `#rename-error`, `#topic-error`, `#discover-error`, `#paste-error`, `#upload-error`, `#ingest-error` | `<pre class="error">` | `textContent` via `hx-on::htmx:response-error` |
| 12 | `#status-badge` | `<span>` +atomic | outerHTML swap every 10s |

Six error blocks, exactly as the brief states. Both counts verify.

## AC#1 — why the 2s poll re-announces

`#ingest-status` carries `aria-live` **and is the swap target** with
`hx-swap="outerHTML"`. Every poll REPLACES the element. Inserting a node that
carries `aria-live` causes its content to be announced — the AT has no prior
version of that node to diff against, so "unchanged status" is not a thing it
can observe. `aria-atomic="true"` makes it re-read the whole composite string
each time.

The brief's proposed fix is right and its stated reason is the operative one:
*a live region only announces CHANGED text, so an identical re-render is silent
by spec* — but only if the live region ELEMENT persists across the update.

**Chosen shape: a stable wrapper AROUND the swap target**, not moving the poll
to `innerHTML`. Both make the live region persist. The wrapper is preferred
because `hx-swap="innerHTML"` would leave `hx-trigger="every 2s"` on the
surviving element forever, discarding the *defence-in-depth* half of the
existing stop mechanism (terminal fragments OMIT the trigger; HTTP 286 also
stops polling). Keeping the outerHTML swap keeps both halves.

## AC#2 — the six error blocks' `aria-live` is CARGO, not merely surplus

This is the finding the brief does not state, and it changes what "fix" means.

`app.css` carries `pre.error:empty { display: none; }`. An element with
`display: none` is **not in the accessibility tree**, so at first paint those
six live regions do not exist as far as an AT is concerned. The error path then
sets `.textContent`, which simultaneously (a) gives the element content and
(b) makes `:empty` stop matching, so the element is inserted into the a11y tree
*already carrying its text*. A live region must be present and rendered BEFORE
content arrives for the change to be announced; registering it and filling it
in the same frame is the canonical way to get silence.

So removing the attribute (AC#2) does not remove a working announcement — it
removes an attribute that was already not announcing. Deleting it outright
would still be a regression in intent, which is why AC#3's wording matters:
it speaks of "any `<output>` migration", i.e. the six move to `<output>`, whose
implicit `role="status"` IS a polite atomic live region. The attribute goes;
the semantics stay and become real.

**`display: none` must go with it.** Migrating to `<output>` while keeping
`:empty { display: none }` reproduces the exact defect one element later. The
empty state becomes zero-footprint instead of unrendered.

## AC#3 — why `#ingest-status` is excluded

`<output>` is **phrasing content**. `_ingest_status_fragment`'s failed branch
emits `<pre class="error">…</pre>`, which is **flow content**. `<pre>` inside
`<output>` is invalid. The exclusion is correct and the wrapper approach above
is what serves that region instead.

## AC#4 — the m12 interaction, and the constraint that binds this milestone

`notebook_detail.html` records a HARD CONSTRAINT naming m13 by name: **no swap
may target the `<details>` or any ancestor of it**, or the server-rendered
`open` state snaps back every 2s (the `onboarding-uplift-m3` D2 failure m12
escaped). m13's roadmap summary — "move `aria-live` onto a stable
never-swapped wrapper" — is the shape that violates it if the wrapper is placed
*around the disclosure* and polled.

The wrapper chosen here sits **inside** the ingest block, wrapping only
`#ingest-status`. It is a descendant of the `<details>`, never a swap target,
and carries no `hx-*`. `TestStructuralInvariantsHoldInTheRenderedTree`
(added by m12's rectify) enforces this and will fail loudly on the wrong shape.

## Guard that must change, and why it is not deletion

`tests/test_ui_a11y_baselines.py::…` asserts every `_ingest_status_fragment`
branch emits `aria-live` AND `aria-atomic`. Its stated premise — "the outerHTML
swap replaces this element entirely, so the SERVER-RENDERED FRAGMENT must also
carry aria-live" — is precisely what m13 makes false. The guard is rewritten to
assert the inverse (the fragment must NOT carry them, because a nested live
region inside the stable wrapper would re-announce on every poll and reinstate
the defect). Same property, opposite polarity.
