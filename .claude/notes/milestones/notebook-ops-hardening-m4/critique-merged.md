# Merged Critique — notebook-ops-hardening-m4

**Critics:** adversary (`critique-adversary.md`) + infra-safety
(`critique-infra-safety.md`)
**Commit range:** b248b6042a3095427514e2520ccc1d4c982bc88c..67864da063bd9f698885862dca366a5156bf0a17

## Orchestrator executive summary

- **adversary: SHIP-WITH-FIXES** (0 CRITICAL, 0 HIGH, 1 MEDIUM, 3 LOW) — the
  design is correct on every load-bearing axis (Deviation #1 `/ui/status-badge`
  genuinely passes SecFetchSite + keeps polling; pass/warn/fail → 200/200/503;
  `/readyz` untouched and AC4 pins both legs; spec-faithful health+json;
  never-500 discipline; info-leak clean).
- **infra-safety: SHIP-WITH-FIXES** (0/0/1/0) — the Makefile `status` target is
  read-only, `.PHONY` + help correct; one MEDIUM on the `&&/||` chain.
- No HIGH/CRITICAL. All findings cheap; fixing all 5.

## Findings (IDs preserved)

- **F1 (MEDIUM, adversary, server/health.py:357)** — notebook-store probe
  `except Exception` swallows with no log → a real store regression renders as a
  permanent silent warn/null with no breadcrumb. Fix: add `logger.warning(...,
  exc_info=True)` + a throwing-store regression test (the broad except was
  unexercised).
- **IS1 (MEDIUM, infra-safety, Makefile)** — the `out=$(curl) && ... | py || echo
  DOWN` chain fires the `||` on ANY pipeline non-zero, including a
  `status_line.py` crash on a HEALTHY server → false "DOWN" + exit 0. Fix: an
  `if/else` so a parser crash propagates its own non-zero + traceback while a
  curl failure still prints DOWN.
- **F2 (LOW, adversary, server/health.py:284)** — the documented `now` clock has
  zero coverage; the backup-staleness tests use wall-clock. Fix: a test pinning
  the `_BACKUP_STALE_SECONDS` boundary with injected `now`.
- **F3 (LOW, adversary, Makefile)** — DOWN wording conflates reachable-but-503
  with unreachable. Fix: soften to "is down or warming up" (folds into IS1 edit).
- **F4 (LOW, adversary, tests)** — the m4 endpoint tests bypass the middleware
  stack, so Deviation #1's two premises (`/status` 403s same-origin;
  `/ui/status-badge` exempt) aren't pinned to the real paths. Fix: a `create_app`
  TestClient test asserting both.

## Cross-critic agreement

The two MEDIUMs (F1 + IS1) are independent (server probe vs Makefile recipe); no
overlap. F3 is the Makefile cosmetic counterpart to IS1 (same target). No finding
flagged by both critics.

## Combined "What was done well"

- Deviation #1 hand-verified correct: `/ui/status-badge` is SecFetchSite-exempt
  and the fragment re-emits its poll attributes (keeps polling after swap).
- AC4 genuinely pinned (one test asserts /status warn 200 AND /readyz 503).
- Spec-faithful health+json; never-500 discipline; info-leak clean (ints + fixed
  labels, html.escaped badge).
- `make status` down-path single-output + crash-free; `--max-time 5`; read-only;
  `.PHONY` + help + `ARXMCP_BIND_PORT ?= 7733` mirroring DEFAULT_BIND_PORT.
- No banned patterns, no tier/fork/math/BP1 impact; defensive `status_line.py`.

## Recommended rectification order

1. F1 (MED) — log + throwing-store test.
2. IS1 (MED) — Makefile if/else.
3. F4 (LOW) — SecFetchSite deviation test (protects the central design).
4. F2 (LOW) — now-clock boundary test.
5. F3 (LOW) — soften DOWN wording (folds into IS1).

## Rectification status

All 5 findings fixed (re-verify gate: F1's broad-except + IS1's `||`-conflation
both confirmed against the cited lines before fixing). 2 MEDIUM + 3 LOW; 0
deferred; 0 invalidated.

- **F1 (MEDIUM) — FIXED.** `server/health.py` store-probe `except` now logs
  `logger.warning("/status notebook-store probe failed; reporting warn",
  exc_info=True)` before degrading to warn. Guard:
  `test_throwing_store_warns_and_logs` (a store whose coroutine raises → warn +
  null count + a captured WARNING).
- **IS1 (MEDIUM) — FIXED.** `make status` rewritten as an `if out=$(curl ...);
  then ... | status_line.py; else echo DOWN; fi` — a parser crash on a healthy
  server now propagates its own non-zero exit + traceback instead of a false
  "DOWN". `make -n status` parses.
- **F4 (LOW) — FIXED.** `TestStatusSecFetchSiteDeviation` (create_app TestClient):
  `GET /status` + `Sec-Fetch-Site: same-origin` → 403 `sec_fetch_site_forbidden`
  (why the badge can't hit /status), and `GET /ui/status-badge` + same header →
  NOT 403 (the deviation works). Pins the design to the real paths.
- **F2 (LOW) — FIXED.** `test_now_injection_pins_backup_staleness_boundary`
  injects a fixed `now` and asserts the backup check is `pass` at
  `_BACKUP_STALE_SECONDS - 1` and `warn` at `+60` — exercises the documented
  clock + makes the staleness test deterministic.
- **F3 (LOW) — FIXED.** DOWN wording softened to "is down or warming up" (folded
  into the IS1 Makefile edit) — no longer claims "not reachable" for a
  reachable-but-503 server.

Net: m4 status test count 17 → 21. ruff clean.
