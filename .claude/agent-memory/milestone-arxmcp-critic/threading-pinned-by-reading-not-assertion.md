---
name: threading-pinned-by-reading-not-assertion
description: On a "thread an optional param config→resources→phase" milestone, the end-to-end wiring is usually verified by reading but NOT pinned by an assertion — the e3-class regression risk
metadata:
  type: feedback
---

When a milestone threads an optional override (here `bm25_index_root`)
through a `config → resources → phase.startup → _sync` chain, the
implementer typically adds: (a) a config-derivation test, (b) a
unit test on the leaf function. But the END-TO-END path — does the
SERVER STARTUP actually use the override to write artifacts at the new
location? — is usually only IMPLICITLY covered by a pre-existing boot
test that asserts `/readyz == 200` and nothing about WHERE the artifact
landed.

**Why:** The threading at `resources.py` (one-line kwarg pass) is correct
by reading, but nothing pins it. A future refactor dropping the kwarg
passes every current test because the leaf falls back to the global
default and `/readyz` is still 200. This is the e3-class "summary claims
correct, no test pins it" risk — the milestone exists BECAUSE the
startup path read the wrong root, so the startup path is exactly what
needs an artifact-location assertion.

**How to apply:** On any thread-a-param-through-startup milestone, grep
the boot/startup test for an assertion on the artifact's on-disk LOCATION
(e.g. `(<derived_root>/v<N>/bm25.pkl).is_file()`) AND a negative
assertion that the OLD/global location was NOT written. If both are
absent, flag MEDIUM (test surface) — not HIGH, since the wiring is
correct by reading; the gap is the missing regression pin, not a live
bug. notebook-bm25-isolation-m1 F2 is the exemplar:
`test_resources_startup_boots_notebook_corpus` asserts version + readyz
but never the BM25 artifact path.

Companion check on the same milestone class: the idempotent-skip /
collision mechanism the fix targets is often untested per-scope (the
new tests use distinct inputs so the "same-scope re-run skips,
different-scope re-run rebuilds" boundary — the exact thing the bug
hinged on — goes uncovered). See F3 of the same critique.
