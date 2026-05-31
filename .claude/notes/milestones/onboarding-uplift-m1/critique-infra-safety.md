# Critique — onboarding-uplift-m1

**Critic:** infra-safety
**Generated:** 2026-05-30T00:00:00Z
**Commit range:** be099b339859b3583e35ec1922a92a3b143d7aaf..e7c480adba88bf928efadbf0988a17badc813d2d
**Verdict:** SHIP

## Executive summary

- SHIP verdict: the two-region Makefile change is informational-only and introduces no infra regressions.
- 0 CRITICAL, 0 HIGH, 0 MEDIUM, 0 LOW
- All 4 Makefile axes clean; the factual claim "the server REJECTS the var" is verified correct against `server/main.py::_scan_unknown_arxmcp_env_vars` (lines 348-384).
- No new targets, no side-effect changes, no privilege escalation, no exit-code masking.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

No findings.

## What was done well

- **Factually accurate help text.** The claim "the server REJECTS the var" is grounded in `server/main.py:381` (`raise ValueError`) — not editorial speculation. The carve-out message at line 282 names exactly the three tools listed in the Makefile help.
- **Precise tool enumeration.** `tools/notebook_fetch.py`, `tools/recover_preambles.py`, `ingest/inspire_ingest.py` are listed consistently in both the `help` target (lines 37-40) and the bootstrap nag (lines 63-68), matching `_KNOWN_INGEST_ENV_VARS` in `main.py:280-286`.
- **Bootstrap idempotency preserved.** The nag block at lines 63-68 is pure `@echo`; `if [ -z ... ]; then ... fi` evaluates a shell condition and never mutates state. Running `make bootstrap` twice cannot fail due to this change.
- **Exit codes remain uncorrupted.** The `@if` block at lines 63-68 always exits 0 and is the LAST recipe line, so it cannot mask any failure from `pip install` (line 49) or `mkdir -p` (lines 50-57). The new echo lines do not introduce `; cmd` chaining.
- **No `sudo`, no destructive default.** The diff adds no privileged operations. The `make clean` target does not exist; destructive targets are scoped to `cutover`/`notebook-cutover` with warnings.
- **`make test` target unaffected.** Dry-run confirms `ruff check .` + `pytest` still fire in sequence; the diff does not touch lines 70-75.
- **`make ingest` stub preserved.** The ingest stub (line 138) is unchanged — `$(PYTHON) -m ingest.bulk_ingest $(ARGS)` is the real E11 driver, not a misplaced stub replacement.
- **No `sudo` anywhere in the Makefile.** Full scan of the current Makefile confirms zero occurrences.
- **Operator guidance is additive, not removing prior context.** Changing "WARNING:" to "NOTE:" is an appropriate severity downgrade — the original "WARNING" implied operator error; the correct posture is that leaving the var unset is the expected state for `make up`.
- **Multi-echo idiom is correct.** The four-line echo block in the nag uses separate `@echo` / `echo` statements rather than a single long concatenated string, consistent with the rest of the Makefile's help section.

## Recommended rectification order

No rectification required.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->

---

verdict: CLEAN; 0 findings (0/0/0/0)
