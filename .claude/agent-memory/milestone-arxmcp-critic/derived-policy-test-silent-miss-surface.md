---
name: derived-policy-test-silent-miss-surface
description: Auditing a derived policy/guard test (AST or regex extractor + allow-list) — probe the extractor's SILENT-miss surface with synthetic alternate syntaxes, and check allow-list staleness in BOTH directions and for name-global vs site-scoped suppression
metadata:
  type: feedback
---

When the diff is a **derived policy test** (`test_assert_ban.py`, `test_wheel_packaging.py`,
`test_ui_class_css_coverage.py` — this repo keeps growing them), the test IS the product.
Two probe routines find real findings almost every time.

**Why:** a guard test's whole value is its forward-binding claim ("a new X with no Y fails the
suite"). That claim is only as wide as the extractor, and the extractor's gaps are invisible
from reading — you have to execute it. On `ui-uplift-m9` both routines fired: the AST class-attr
extractor returned `[]` for `'<div class="' + c + '">'` and for `class='x'` (silent bypass of
AC3), while `.format()`, `%`, and joined-list forms all failed LOUDLY — a distinction only
visible by running it.

**How to apply:**

1. **Probe the extractor with synthetic alternate syntaxes and sort results into
   silent-pass vs fail-loud.** Import the test module's own helpers into a scratchpad script
   and feed it hand-written source. Fail-loud gaps are acceptable (they force a change);
   silent-pass gaps defeat the acceptance criterion. For a string-literal extractor the
   standard battery is: explicit `+` concatenation splitting the token, the other quote
   character, `.format()`, `%`-format, `"".join(...)`, variable indirection, and a literal
   nested inside an f-string `FormattedValue`. Propose a **structural** fix (a byte-level
   count tripwire vs the AST-derived count) over enumerating the syntaxes.
2. **For every allow-list / known-debt dict, check BOTH staleness directions and the
   suppression scope.** Repos ship a "self-cleaning" test for the direction they thought of
   (entry gained a rule → delete it) and none for the other (entry no longer emitted → rots
   forever). Then check the key: a bare-name key suppresses that name **anywhere** in the
   scanned tree, so re-emitting it from a brand-new file passes silently — demonstrate it
   with a synthetic module rather than asserting it. When the class/docstring claims it
   "cannot go stale in either direction", that is a claim to verify, not a fact
   (see [[claim-drift-verify-against-code]]).
3. **Verify every `file:line` citation in a parked-debt dict, and verify each deferral's
   named owner exists.** On m9 all nine citations were accurate (do not assume drift), but
   4 of 9 reasons said "unowned" and `grep` over the roadmap confirmed no milestone scopes
   them — deferral without tracking, see [[severity-calibration-and-edge-inputs]]. The
   5 entries that DID name `ui-uplift-m10` checked out against `plans/*/roadmap.yaml`.
4. **Also quantify the residual outside the declared scope.** m9 legitimately scoped to
   `server/routes/` per its AC; running the same check over `server/frontend/templates/*.html`
   found 8 more unstyled classes — same magnitude as the guarded gap. Scope-correct, so LOW,
   but worth recording. Note a prior-phase synthesis may pre-emptively say "Phase 3 does not
   flag this" — evaluate it on merits, do not let it suppress the record.
5. **Environment triage first.** A bare system python will fail collection on missing deps
   (`defusedxml`) — that is an env artifact, not a finding. Re-run with the MAIN checkout's
   venv (worktrees here have no `.venv`):
   `"…/arXMCP/.venv/Scripts/python.exe" -m pytest <file> -q`. It IS worth a LOW when a
   module-level app import couples an otherwise stdlib-only policy file to the whole
   FastAPI import graph, since one unrelated import break disables the entire guard.
