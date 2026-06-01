---
name: regression-guard-pins-names-not-shape
description: Test extensions that pin alert/rule NAMES into a required set leave EXPR/FOR/SEVERITY/RUNBOOK_URL fields unenforced; docstring claims of "forward regression protection" can be vacuous in this shape. Rule-shape tests with `assert key in keys()` check existence but not values.
metadata:
  type: feedback
---

When a milestone extends a "required entries are present" test (e.g.
`test_required_alerts_present` extending a `required = {<names...>}` set),
the regression guard ONLY pins NAMES — not the SHAPE (expr, for, severity,
runbook_url, threshold values, etc.) that the AC actually mandates.

**Why:** corpus-integrity-completion-m1 extended the required-names set and
the docstring claimed "future change cannot silently remove them" but a
future commit could keep the alert name and silently strip the runbook_url
annotation, retarget the expr, or change `for: 10m` to `for: 1d` (defeating
the tripwire) — and every existing test would still pass. The peer
`test_disk_full_threshold_matches_implementation` was the precedent for
pinning a numeric VALUE against a Python constant; no analogous shape-pin
exists for the new rules. Pattern: existence-of-key checks (`assert key in
keys()`) leave VALUES unenforced.

**How to apply:** On any milestone that adds entries to a "required set"
regression guard, walk every AC field (expr / for / severity / runbook_url
/ duration / threshold) and check whether the assertion list actually pins
that field. If only the entity NAME is pinned, flag MEDIUM (F1/F2 class).
Look specifically at `test_*_shape` tests — they typically assert `set <=
keys()` which proves existence but not value match. The high-leverage fix
is one additional test that iterates the required set and asserts each
field's value against the AC; ~15-25 LOC. Same pattern applies to MCP
tool-schema tests, BP1 byte-stability tests, and any "frozen contract" test
surface.

See also [[threading-pinned-by-reading-not-assertion]] (peer class: code
that READS a param but no test PINS the artifact location).
