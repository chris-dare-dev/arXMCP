---
name: vacuous-test-kept-as-documentation
description: v0→v1 milestones flip an assertion + leave a companion discriminator test where the mutate-then-check becomes a no-op against the new code; assertion holds vacuously → MEDIUM
metadata:
  type: feedback
---

On any v0→v1 milestone that FLIPS a regression-guard assertion (e.g. m2 v0
asserted `max-width: 980px` stays; m5 v1 asserts `clamp(640px, 92vw, 1400px)`
is present), the companion "discriminator" test that mutates the CSS string
via `str.replace(<v0-form>, <v1-form>)` typically becomes VACUOUS post-flip:
the v0 substring is no longer present, the `.replace()` is a no-op, the
follow-up regex search against the unchanged string returns None, and the
assertion `body_block is None` holds without testing anything.

**Why:** the discriminator was designed to PROVE the regex narrowly matches
the v0 form by mutating CSS that contains it. Once production CSS no longer
contains the v0 form, there's nothing to mutate, the test self-check is
no longer demonstrable, and the test passes regardless of input.

**How to apply:** on any milestone that "flips" an assertion that was paired
with a `*_guard_discriminates` companion (search `tests/` for `discrim` /
`mutate` / `synthetic_v[01]`), check whether the companion is still
discriminating. If the production CSS no longer contains the mutate-source
substring, the test is dead weight. The fix is either (a) DELETE the
companion (the new positive-form assertion + negative-regression check is
enough), or (b) REWRITE the discriminator to construct a synthetic CSS
string from scratch (`"body { max-width: 980px; }"` literal) so it actually
exercises the regex.

Implementers tend to KEEP these tests "as documentation of the v0→v1
transition" — that's the wrong artifact choice. Code is not documentation.
Flag MEDIUM per the dead-test-code class. The implementer's honest
disclosure ("considered removing but kept") makes this easier to flag
without false-positive risk.

See also: [[bp1-description-vs-handler-validator-drift]],
[[stale-docstring-anti-pattern]] — same "doc says X, code does Y" family.

First flagged in ui-attractive-polish-m5 F1
(tests/test_ui_m2_polish.py:181-199 — test_body_max_width_guard_discriminates
became no-op after UPL-19 v1 lifted 980px → clamp).
