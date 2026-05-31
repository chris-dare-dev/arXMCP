# Critique — onboarding-uplift-m3

**Critic:** infra-safety
**Generated:** 2026-05-31T00:00:00Z
**Commit range:** b66fa1e58fe2ee66f48ec4a73831624a9062bccf..72d5e183463dab323082bc08ad1438bda262ba18
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: one MEDIUM finding (`.PHONY` section labels vs `make help` categorization
  mismatch creates operator confusion), no CRITICAL or HIGH findings
- 0 CRITICAL, 0 HIGH, 1 MEDIUM, 0 LOW across 4 axes
- Container hygiene: N/A (no Dockerfile changes)
- docker-compose: N/A (no compose file changes)
- CI workflows: N/A (no workflow files changed)
- Makefile axis: 4 checks — idempotency clean, no sudo/destructive defaults, exit-code
  propagation clean, help accuracy 1 MEDIUM

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### IS1 — `.PHONY` group labels mismatch `make help` categorization

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** Makefile:21-23 (`.PHONY` stanza) vs Makefile:40-59 (`make help` "FIRST TIME?" block)
- **What:** The `.PHONY` comment at line 21 assigns `repair-registry` and `reconcile` to the
  "REPAIR / RECONCILE" functional group. However, both targets appear inside the "FIRST TIME?
  (onboarding-uplift-m2)" block in `make help` (lines 53–59), alongside `init`, `add`,
  `notebook-list`, and `ingest`. The same cross-labeling applies to `init`, `add`,
  `notebook-list` (`.PHONY` group: "NOTEBOOK CRUD") and `ingest` (`.PHONY` group:
  "CORPUS LIFECYCLE") — all appear under the "FIRST TIME?" heading in `make help`.
- **Why it matters:** An operator reading `.PHONY` to understand the target taxonomy sees
  "REPAIR / RECONCILE" as a distinct category from "FIRST TIME?", but `make help` (the
  operator's primary reference) places the repair/reconcile targets in the onboarding
  block. A new contributor adding a target to the "FIRST TIME?" help block would
  reasonably add its `.PHONY` declaration to the "REPAIR / RECONCILE" stanza — and vice
  versa — leading to divergence between the two taxonomies over time. The comment at
  Makefile:1-3 explicitly promises that "each `.PHONY:` stanza below pairs with the
  section it describes", which is violated here.
- **Proposed fix:** Either (a) move `repair-registry reconcile` from the "REPAIR /
  RECONCILE" `.PHONY` stanza into the existing "NOTEBOOK CRUD" or a new "NOTEBOOK HEAL"
  stanza (≤ 5 LOC), OR (b) add a `make help` section header "REPAIR / RECONCILE" that
  groups the two targets separately from the "FIRST TIME?" block so the two views
  agree. Option (b) better reflects operator intent: repair/reconcile are not first-time
  actions; they are corrective maintenance targets that a new operator is unlikely to
  need on a fresh clone.
- **Regression guard:** After the fix, `make -n help | grep -A2 "FIRST TIME"` must not
  list `repair-registry` or `reconcile`, and `make -n help | grep -A2 "REPAIR"` must.

## What was done well

- The `.PHONY` split (Makefile:1-23) correctly eliminates the 219-char single-line
  `.PHONY` anti-pattern from m2 F8 and provides a maintainable per-section structure
  with explanatory comments for each group.
- `repair-registry` server-up branch correctly guards the inner curl with
  `|| { echo ... >&2; exit 1; }` (Makefile:536), ensuring a REST failure after a
  successful healthcheck probe propagates as a non-zero exit to Make.
- `reconcile` server-up + NOTEBOOK= branch applies the identical `|| { exit 1; }`
  guard pattern (Makefile:564), consistent with the existing `add` and `notebook-list`
  recipes.
- Both new recipes use the established `if curl ... healthz ...; then ... else ... fi`
  server-up detection idiom (not the `cmd || echo DOWN` anti-pattern already caught and
  fixed in m4 IS1), correctly isolating the server-probe failure path from the inner
  command failure path.
- `SCOPE_SLUG` and `SCOPE_LABEL` shell variables in `reconcile` (Makefile:551-553) are
  set inside double-quoted assignments, keeping slug values intact across the
  two-phase `if/fi` chain without word-splitting.
- The `$(PYTHON) -m tools.notebook_reconcile_marker "$$SCOPE_SLUG"` invocation
  (Makefile:572) correctly double-quotes the shell variable, consistent with the
  IS1-LOW fix from m2.
- Neither new target introduces `sudo`, destructive defaults, or mutations to
  `var/arxmcp/` beyond the narrow paths (notebooks.db + corpus-version.json) they
  document in their comments.
- The `make test` target is untouched and confirmed to still invoke `ruff check .` then
  `pytest` (`make -n test` output verified).
- The `make ingest` stub (E11_S01 intentional stub that exits 1) is untouched at
  Makefile:171-187; the stub is correctly preserved.
- `repair-registry` server-down branch (Makefile:539-540) propagates the Python exit
  code as the last command in the `else` branch of the outer `if/fi`, which is
  the exit code Make checks.

## Recommended rectification order

1. IS1 (MEDIUM): add a distinct "REPAIR / RECONCILE" section to `make help` (or move
   the two targets out of the "FIRST TIME?" block) so `.PHONY` group labels match the
   help output taxonomy. Cheap: ~6 LOC change to the `help` target. Verify with
   `make -n help | grep -E "REPAIR|FIRST TIME"`.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->

---

verdict: SHIP-WITH-FIXES; 1 finding (0 CRITICAL, 0 HIGH, 1 MEDIUM, 0 LOW)
