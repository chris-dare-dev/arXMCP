# Critique — notebook-ops-hardening-m4

**Critic:** infra-safety
**Generated:** 2026-05-29T00:00:00Z
**Commit range:** b248b6042a3095427514e2520ccc1d4c982bc88c..67864da063bd9f698885862dca366a5156bf0a17
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: one MEDIUM finding (IS1) — `||` operator conflates curl
  failure with status_line.py failure; both branches print "DOWN" and exit 0
- 0 CRITICAL, 0 HIGH, 1 MEDIUM, 0 LOW
- Axes 1–3 (container hygiene, compose correctness, CI workflow) are N/A —
  only Makefile changed in range
- Axis 4 (Makefile discipline) is the sole axis in scope; `make test` is
  confirmed intact; `status` is correctly added to `.PHONY` and `make help`
- `ARXMCP_BIND_PORT ?= 7733` is a non-secret numeric default; no injection
  surface; URL is double-quoted at shell level
- No `sudo`, no destructive defaults, no state mutation — target is read-only

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### IS1 — `||` conflates curl failure with status_line.py failure

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** Makefile:109–111
- **What:** The recipe is a single `@out=$(…) && printf … | $(PYTHON) … || echo "DOWN: …"`.
  The `||` branch fires on ANY non-zero exit in the pipeline — including a
  successful curl that returns valid JSON but a `tools/status_line.py` crash
  (import error, parse error, etc.). In that case, the server IS reachable but
  `make status` prints "DOWN: arxmcp-server not reachable at …" and exits 0,
  giving a false negative.
- **Why it matters:** An operator running `make status` after a breaking change
  to `tools/status_line.py` sees "DOWN" and may restart a healthy server,
  or file a false incident. The misdiagnosis is silent (exit 0, no Python
  traceback visible because `2>/dev/null` is on the curl step only, not the
  `status_line.py` step).
- **Proposed fix:** Split the error paths so curl failure and status_line.py
  failure are distinguishable. Simplest safe form (≤10 LOC delta):

  ```make
  status:
  	@if out=$$(curl -sf --max-time 5 \
  		"http://127.0.0.1:$(ARXMCP_BIND_PORT)/status" 2>/dev/null); then \
  		printf '%s' "$$out" | $(PYTHON) tools/status_line.py; \
  	else \
  		echo "DOWN: arxmcp-server not reachable at 127.0.0.1:$(ARXMCP_BIND_PORT)/status"; \
  	fi
  ```

  With this form, a `status_line.py` failure propagates its own non-zero exit
  to the shell (and the operator sees the Python traceback), while a curl
  failure still prints the "DOWN" line.

- **Regression guard:** Run `make status` with the server stopped; confirm
  "DOWN" line appears and exit code is 0 (operator-facing, not CI gate). Run
  `make status` with a deliberately broken `tools/status_line.py` (e.g.
  `raise RuntimeError("broken")`); confirm the traceback is visible and exit
  is non-zero, rather than a silent "DOWN" line.

## What was done well

- `status` is correctly added to `.PHONY` on Makefile:1 — no stale file
  collision risk.
- `make status` is documented in the `make help` output (Makefile:17), satisfying
  the `makefile-operator-warning-help-visibility` pattern from agent memory.
- `ARXMCP_BIND_PORT ?= 7733` uses the conditional assignment form (`?=`),
  meaning an operator-set env var is honored without any Makefile surgery.
- The comment block (Makefile:6–7) names the source of truth
  (`server/config.py DEFAULT_BIND_PORT`) so the value stays in sync.
- `--max-time 5` on curl prevents indefinite hangs; appropriate for an
  interactive operator status check.
- `printf '%s' "$$out"` correctly double-quotes the captured output so that
  JSON values containing spaces, newlines, or shell-special characters are
  passed to `status_line.py` without word-splitting.
- The `2>/dev/null` on the curl step suppresses noisy "Connection refused"
  stderr while still routing the failure through the `||` branch — correct
  for the operator UX goal.
- The target is strictly read-only (curl + print); it mutates no state,
  writes no files, and has no side effects on `var/arxmcp/`.
- `make test` is confirmed intact (`make -n test` emits `ruff check .` and
  `pytest`); this diff does not regress the test target.
- The `ARXMCP_BIND_PORT` variable scope is limited to the Makefile (not
  exported by default), preventing accidental environment leakage into child
  processes that do not expect it.

## Recommended rectification order

1. **IS1 (MEDIUM)** — replace the `&&` / `||` chain with an `if/else` block
   to distinguish curl failure from `status_line.py` failure; ~8 LOC change,
   cheap and safe.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
