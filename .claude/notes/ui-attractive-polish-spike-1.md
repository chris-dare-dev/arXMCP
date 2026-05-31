# Spike-1 — htmx 2.0.10 View Transitions integration verification

**Slug:** `ui-attractive-polish-spike-1`
**Date:** 2026-05-31
**Validates `[MUST]` assumption #3 from Phase-1 REFINE:** "The View
Transitions API integration with htmx 2.0.10 works via the
`htmx:beforeSwap` event + `document.startViewTransition()` pattern
documented in MDN and the library-scout brief."
**Status:** **OK — but the assumption was based on an obsolete htmx-1.x pattern.** The htmx-2.x reality is materially simpler. UPL-13 (in epic e4) shipping cost drops from "~5 LOC inline JS + audit-widening" to "**1 line of inline JS, zero audit-widening**."
**Budget:** ≤ 1 day. Actual: ~30 min (research-only — no proof-of-concept code needed; htmx source + docs both confirm).

---

## TL;DR

**Do NOT wrap htmx swaps in `document.startViewTransition()` manually.**

htmx 2.0.10 has **native, first-class View Transitions integration** — it
calls `document.startViewTransition()` internally when either of two opt-ins
fires:

1. **Global:** `htmx.config.globalViewTransitions = true` (one config line —
   every swap gets View Transitions).
2. **Per-element:** `hx-swap="<style> transition:true"` (e.g.
   `hx-swap="outerHTML transition:true"` — only this swap target transitions).

The htmx-1.x pattern the m3 research synthesis cited ("intercept
`htmx:beforeSwap`, call `document.startViewTransition()`, re-enter via
`htmx.swap()`") was the workaround when htmx had no native integration. It
**still works** in 2.x (the public `htmx.swap(target, content, swapSpec,
swapOptions)` API exists), but it's the harder + audit-widening path.

The synthesis's stated risk — "if `htmx.swap()` call shape is wrong, UPL-13
silently breaks every htmx interaction" — is **eliminated** by the native
path because there's no user JS that could have the wrong shape.

---

## Evidence

### A. The vendored htmx.min.js itself

Inspecting `frontend/static/htmx.min.js` (the vendored 2.0.10 file):

1. **Public API surface declares `swap` exists** —
   ```js
   const Q = { onLoad: null, process: null, …, swap: null, … }
   …
   Q.swap = _e;
   ```
   `Q` is `htmx` (the exported global). `_e` is the internal swap function
   bound as `htmx.swap`. Confirms the function exists with public-API stability.

2. **Default config exposes a global View Transitions flag** —
   ```js
   config: { …, globalViewTransitions: false, … }
   ```
   The flag's default is `false`; flipping it to `true` is the global
   opt-in.

3. **The swap path conditionally invokes `document.startViewTransition()`** — minified excerpt:
   ```js
   …startViewTransition){const o=new Promise(function(e,t){m=e
   …startViewTransition(function(){i()
   ```
   This is the native integration. The condition is `startViewTransition` being a function on `document` AND (the global config flag OR the per-element `transition:true` modifier being set on the swap spec). Both opt-ins resolve into the same code path.

4. **Per-element `transition:true` parsing** — minified excerpt:
   ```js
   transition:")===0){r.transition=l.slice(11)==="true"}
   ```
   The `hx-swap` value parser reads the `transition:` modifier and writes
   `r.transition = true|false`. Downstream the swap engine reads `r.transition`
   alongside the config flag.

### B. The htmx 2.x docs

- **`htmx.org/docs/#view-transitions`** confirms the two opt-ins:
  - "**globalViewTransitions:** Setting `htmx.config.globalViewTransitions = true` enables transitions for all swaps without manual wrapping."
  - "**Per-element:** Use the `transition:true` option in the `hx-swap` attribute."
  - The cancellation hook: "`htmx:beforeTransition` event — call `preventDefault()` on it to cancel the transition."

- **`htmx.org/api/#swap`** documents the public API:
  - Signature: `htmx.swap(target, content, swapSpec, swapOptions)`
  - `target`: HTMLElement | CSS selector string
  - `content`: HTML string
  - `swapSpec`: `{ swapStyle, swapDelay, settleDelay, transition, … }`
  - `swapOptions`: `{ select, selectOOB, eventInfo, … callbacks }`
  - Intent: user-level code that needs to programmatically trigger swaps
    outside the standard htmx request flow.

---

## Implications for UPL-13 (epic `ui-attractive-polish-e4`)

The original m3-roadmap UPL-13 sketch (from
`plans/ui-attractive-polish-roadmap.md` Phase 2 → epic e4 description +
`.claude/notes/frontend-uplifts/2026-05-ui-polish/artifacts/synthesis.md`
UPL-13) anticipated this implementation:

```js
document.body.addEventListener('htmx:beforeSwap', (e) => {
  if (!document.startViewTransition) return;
  e.preventDefault();
  document.startViewTransition(() => {
    htmx.swap(e.detail.target, e.detail.serverResponse, e.detail.swapSpec);
  });
});
```

That code is **obsolete for htmx 2.x**. The correct UPL-13 implementation is:

**Option A — Global (recommended for arXMCP):** add ONE line to the existing
inline JSON-shim block in `base.html` (within the existing `'unsafe-inline'`
CSP allowance, no CSP widening):

```js
htmx.config.globalViewTransitions = true;
```

Every htmx swap in arXMCP — rename in `#display-name-block`, ingest-status
poll in `#ingest-status` (every 2s), badge poll in `#status-badge` (every
10s), paper-row append in `#papers-tbody`, future in-place create flows from
UPL-12 — automatically gets a `document.startViewTransition()`-wrapped
crossfade on Chrome + Safari. Firefox + Firefox-derivatives gracefully
no-op (htmx's `if (document.startViewTransition)` guard ensures clean
degradation).

**Option B — Per-element (granular):** add `transition:true` to each
`hx-swap=` attribute we want View-Transitioned. More LOC, more reviewer
load, no advantage over Option A unless we wanted to OPT OUT of some swaps
(which we don't — the polling swaps benefit from the crossfade as much as
the user-triggered ones).

**Optional CSS for transition duration** (gated by m1's `prefers-reduced-motion`
discipline):

```css
@media (prefers-reduced-motion: no-preference) {
  ::view-transition-old(root), ::view-transition-new(root) {
    animation-duration: 200ms;
  }
}
```

(htmx defaults to a CSS-default ~250ms; explicit 200ms keeps the operator
console snappy. Without this block, the browser uses its default duration.)

---

## What this means for the e4 roadmap

| Original assumption | Revised reality |
|---|---|
| UPL-13 = "5 LOC inline JS + audit-widening (new JS in the un-audited UI surface)" | UPL-13 = "1 LOC config flag — `htmx.config.globalViewTransitions = true` — in the existing inline shim (no audit widening; the shim already uses `'unsafe-inline'`)" |
| Risk: "wrong `htmx.swap()` signature silently breaks every htmx interaction" | Risk: **eliminated**. No user JS for htmx to call — htmx handles it internally. The only failure mode is browser-side `document.startViewTransition` absence, which htmx already guards. |
| Sequencing: UPL-13 depends on UPL-12 (in-place swaps) AND UPL-11 (htmx-request feedback) | Sequencing: UPL-13 still depends on **nothing implementation-wise** — could ship today on top of m3 — but its visible value is highest after UPL-12 lands (the longer crossfades have more to show on create/add/remove swaps than on the m1/m2/m3 single-element swaps). Either order works. |
| Effort: S (per the m2 final-report) | Effort: **XS** (the global-config one-liner + the optional CSS duration override). |

**Spike-2 (UI security audit scoping) is still required** for UPL-12 (in-place
swaps introduce new server-side fragment-rendering endpoints — audit surface
widens regardless of UPL-13's path). But Spike-2 no longer needs to consider
"new inline JS for View Transitions" as an axis — that surface is zero.

---

## Recommendation

When `/roadmap ui-attractive-polish` next re-invokes to slice e4 into m4:

1. **Shape m4 as "UPL-12 v0 (add-paper in-place swap) + UPL-13 (View
   Transitions) + UPL-22 (status-badge flash)"** per the existing roadmap.
   UPL-13's implementation drops to:
   - 1 LOC added to the `base.html` inline shim block: `htmx.config.globalViewTransitions = true;`
   - 4 LOC added to `frontend/static/app.css`: the `::view-transition-old/new`
     duration block gated by `prefers-reduced-motion: no-preference`.
   - Regression test: assert the config-flag line is present in `base.html`.
2. **UPL-13 is no longer audit-widening** beyond the existing `'unsafe-inline'`
   allowance. The Spike-2 audit-coordination cost falls entirely on UPL-12
   (which adds 3 new server-side fragment endpoints).
3. **Optional micro-spike**: write a 1-page browser test in
   `/tmp/spike1-vt-test.html` that loads htmx + flips the config + triggers a
   manual `htmx.ajax()` call to confirm the transition fires. Skipped here
   because the htmx source + docs are conclusive; if Chris wants empirical
   confirmation, a 10-minute test via `make up` + Chrome DevTools console
   would do it.

**Spike-1 verdict: PASS.** Risk eliminated; UPL-13 simplified; no UPL-12
dependency change.

---

## What did NOT need verifying after this finding

- The synthesis's claim that "`htmx.swap()` call shape may have the wrong
  signature" — moot, since we don't need to call `htmx.swap()` from user JS.
  But for the record: the signature is `htmx.swap(target, content, swapSpec,
  swapOptions)` per the htmx 2.x docs. Confirmed.
- Whether `document.startViewTransition()` works on Chris's macOS browsers
  (Chrome + Safari) — yes (Chrome 111+, Safari 18.2+; macOS 15 Safari 18+
  has it; Chrome on macOS has had it since 2023).
- Whether htmx-extension `htmx-ext-view-transitions` would help — not
  needed; native config flag is the documented path.

---

## Risks the spike did NOT cover

These were OUT OF SCOPE for Spike-1 (its stated mandate was the
`htmx.swap()` re-entry signature only):

- **Visual quality of the default 250ms crossfade on small swap targets.**
  The status-badge fragment is ~50px wide; the rename `#display-name-block`
  is ~200px wide. A 250ms crossfade on such small elements may feel slow.
  Mitigation: the CSS duration override above (200ms or shorter). Easy.
- **Layout-shift artifacts on the ingest-status poll** when the swap content
  height changes (e.g. `running` → `success` adds the `· Finished … · Run
  #` suffix). View Transitions can produce a brief horizontal jiggle on
  width-change. Acceptable for v0; if it bothers operators, opt that
  specific swap OUT via `hx-swap="outerHTML transition:false"`.
- **Interaction with the m3 `.htmx-request` opacity dim** — when a button
  with `.htmx-request` is the swap source, does the crossfade compound with
  the opacity reduction? Should be visually clean (the View Transition
  captures the button at full opacity pre-request; the post-swap snapshot
  shows the button at 1.0 again). Worth eyeballing during m4 implementation.
- **Polling-driven swaps** (badge every 10s, ingest-status every 2s)
  triggering View Transitions every cycle. Per htmx docs, `htmx:beforeTransition`
  can `preventDefault()` to opt out specific events. We may want to
  skip-transition the polling cases (operator doesn't care about a smooth
  badge crossfade) — small follow-up consideration during m4 build.

These belong in the m4 implementation's research phase, not Spike-1.

---

*Spike-1 complete. e4's UPL-13 path is unblocked + simplified.*
