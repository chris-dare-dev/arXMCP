# Anti-patterns seen while implementing milestones

## Piping a check gate through `tail`/`grep`

`pytest ... | tail -30` reports **`tail`'s** exit status, not pytest's, and
truncates the summary line. Both halves of "the gate is green" are then
unverifiable, and the run *looks* successful. Redirect to a file and record
`$?` on its own line. Seen: ui-uplift-m6 (2026-08-04) — a suite reported
"exit code 0" purely because `tail` succeeded.

## Pinning a literal when the test's intent is a property

Tests that assert `"#6e7681" in block` or `color: #0d1117` turn any
legitimate re-derivation into a false regression, and they say nothing about
what actually mattered (WCAG >= 3:1; an override exists). When updating such
a test, re-express the ORIGINAL intent as the property and keep the negative
half (e.g. "and still not the Primer canonical value"). Seen: ui-uplift-m6.

## A constant duplicated as a literal fails silently, not loudly

`canvas = "#0d1117"` in a test, `th { background: #161b22 }` in CSS, and
`fill="#1e5b8a"` in an SVG were all byte-copies of tokens. When the token
moves, none of them errors — the test keeps validating the wrong ground and
the assets keep painting the old colour. Only the *pinned* tests fail, which
gives a false sense that the blast radius has been found. Grep the repo for
the OLD value of anything you move. Seen: ui-uplift-m6.

## Trusting a published solver without checking its direction

A research brief shipped a `solve_L_for_target_ratio` binary search whose
`darker=True` branch moved the interval the wrong way, silently returning
L=0 or L=1 (pure black/white) instead of the solution. It looked plausible
and had a worked example attached. Re-derive or unit-check any solver a
brief hands you against a known-good value before building on it. Seen:
ui-uplift-m6.

## `re.sub` with no match writes the file back unchanged

A generator that does `re.sub(pattern, new, doc)` and then writes `doc` will
happily produce a byte-identical file when the pattern misses, and print its
success message anyway — leaving a stale artifact that looks freshly
generated. Use `subn` and raise unless the count is exactly what you expect.
Seen: ui-uplift-m6.
