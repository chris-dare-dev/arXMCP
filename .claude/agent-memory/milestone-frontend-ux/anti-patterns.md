# milestone-frontend-ux — recurring anti-patterns

Append-only. Promote here when a pattern is seen more than once, or when it is
structural enough that the next run should check for it by default.

## Element-level type rules with absolute sizes

A rule like `code, time { font-size: var(--text-small) }` is attractive because it
applies a voice by element rather than by class. But an absolute `rem` value does not
compose: wherever that element nests inside a larger context (a heading, a lede, a
callout), it *shrinks* the text instead of marking it. Check every element-level
font-size rule against the set of contexts the element actually appears in — grep the
templates and the fragment builders for the tag, not just the stylesheet.
First seen: ui-uplift-m7 (`<h2><code>slug</code></h2>` rendered at 13px in a 20px heading).

## The scale's largest step landing on boilerplate

When a base template owns the only `<h1>` and it is a site wordmark, applying the page-
title token to it means no page ever gets a focal title — the brand outranks the content
on every screen. Check *what string* the largest step actually renders before accepting
that a scale delivers hierarchy.
First seen: ui-uplift-m7 (`base.html` `<h1>arXMCP notebooks</h1>` on every page).

## Un-declared sizes riding UA keywords

A milestone can truthfully claim "every font-size declaration is now a token" while
surfaces sized by `<small>`, or by no declaration at all, sit outside the scale entirely.
Nested `<small>` inside an already-small element compounds it. Audit for *absent*
declarations, not just literal ones.
First seen: ui-uplift-m7 (`.status-badge__remediation` at ~9px; `.card .empty`; `footer > small`).

## [CONFIRMED] Inventory sites enumerated in research and then skipped in implementation

When a research brief ships a numbered inventory, diff the implemented sites against it
explicitly. A partial sweep is worse than none: it leaves the same value class rendering
two different ways on one page, which reads as a bug rather than as unfinished work.
First seen: ui-uplift-m7 (brief-1 §2 site #10, `latest_run.status`, left in sans while
sites 28–31 — the same token — were fixed).
CONFIRMED: ui-uplift-m10 — the `--fg-muted` token comment enumerates ELEVEN hand-typed greys
by hex and migrates zero of them, so the token ships as a twelfth value beside the eleven it
names. The enumeration was in the diff itself, not just in a brief, and the sweep still did
not happen. When a comment lists what a change replaces, check that it replaced it.

## A design authored in discovery, honoured on the cheap rules and substituted on the costly one

Discovery findings that ship *fully-specified* CSS get graded as "honoured" on rule count, but
the rules that are pure declarations (list-style, padding, border, font-weight) are free and
the one carrying a UX decision is not. Diff every authored rule individually and ask which one
the implementation changed — that is where the design was actually re-decided.
First seen: ui-uplift-m10 (discovery H3's five rules: four verbatim, and the fifth — the
abstract — gained a `max-height` clamp with no reveal affordance that H3 never authored).

## A derived guard that reduces a selector list to one member

A CSS guard that parses `selector { … }` and then classifies only
`selector.split(",")[-1]` checks one of N selectors, so anything grouped in a
comma list anywhere but last is invisible to it — `section, button { border-radius: 8px }`
passes a "no radius on structure" check. Pair it with a literal-value assertion
(`"6px" not in values`) and the guard defends one exact string on one exact
position. When a milestone ships the guard that makes its own headline claim
falsifiable, read the guard's parser, not its docstring: this one opened with a
warning about "guards that pass vacuously" and then shipped a partial-coverage
classifier. Iterate every selector, and assert the guard REJECTS a synthetic
violation.
First seen: ui-uplift-m8 (`test_structure_carries_no_border_radius`, which also
admits `[tabindex]` as a "control" when the product's only `[tabindex]` is `<main>`).
