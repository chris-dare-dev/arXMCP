# Critique — notebook-ops-hardening-m4

**Critic:** adversary
**Generated:** 2026-05-29T14:58:54Z
**Commit range:** b248b6042a3095427514e2520ccc1d4c982bc88c..67864da063bd9f698885862dca366a5156bf0a17
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES — the design is correct on every load-bearing axis (Deviation #1
  `/ui/status-badge` genuinely passes SecFetchSite + keeps polling; pass/warn/fail →
  200/200/503 mapping is right; `/readyz` is untouched and the AC4 test asserts BOTH
  legs). The only fix worth doing is one cheap MEDIUM observability gap.
- Finding counts: 0 CRITICAL, 0 HIGH, 1 MEDIUM, 3 LOW.
- Highest-risk file:line: `server/health.py:357` — broad `except Exception` on the
  notebook-store probe with no log line; a future store bug surfaces as a permanent
  silent `warn` with zero debug breadcrumb.
- Cache/MCP byte-stability (Axis 1/4): CLEAN — diff touches no `server/tools.py`,
  `server/prompts.py`, `ALL_TOOLS`, `tools/list`, BP1, or `EXPECTED_TOOL_SCHEMA_SHA256`.
  `/status` and `/ui/status-badge` are plain HTTP routes; no re-pin needed.
- Security/info-leak (Axis 3): CLEAN — `output` fields carry only ints + fixed labels
  (`free=NGB < NGB threshold`, `last backup Nh ago`, `fallback_version=N`); no paths,
  no tracebacks. Badge `summary` is built from ints + fixed labels and `html.escape`d
  belt-and-braces. `compute_health_status` never raises in either path (warm-path
  attribute reads are all confirmed-present on the real `Resources`/`Config`).
- `make status` down-path is correct (captured-then-piped avoids double-output; 503
  falls to the `||` DOWN line) but its DOWN wording conflates "reachable-but-503" with
  "unreachable" (F3).
- Banned-pattern + tier-sequencing + local-first + no-fork + math-fidelity: all CLEAN.
- 17/17 m4 tests pass; `ruff check` clean on all changed files.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Notebook-store probe swallows all exceptions with no log

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/health.py:357
- **What:** The notebook-count probe wraps `len(await store.list_notebooks())` in a
  bare `except Exception:` that sets `nb_status = "warn"` and leaves `nb_count = None`,
  with no log call. The disk (`except OSError`, :384) and backup
  (`except (OSError, ValueError, json.JSONDecodeError)`, :421) probes are narrowly
  typed and self-describing via their `output` field; this one is not.
- **Why it matters:** "must not 500 on a status endpoint" is the right intent and the
  failure IS surfaced to the operator as `warn` + `observedValue: null` (not a silent
  `pass`), so this is not a correctness bug. But a genuine store-layer regression
  (e.g. a future LanceDB/SQLite query change that throws) would render as a permanent
  `warn`/null-count with NO log line — the operator sees "degraded" forever and has no
  breadcrumb to debug. Bare `except Exception` that discards the exception object is
  the open-scan anti-pattern (catch-all that silently swallows).
- **Proposed fix:** keep the must-not-500 behavior; add a single throttled/`exc_info`
  log so the cause is recoverable:
  ```python
  except Exception:  # noqa: BLE001 — operability probe, must not 500
      logger.warning("notebook-store probe failed in /status", exc_info=True)
      nb_status = "warn"
  ```
  (~2 LOC. The 10s poll could make this chatty, but a real store failure is a
  standing condition the operator wants to see; if poll-spam is a concern, gate it
  behind a module-level "last logged" guard — still ≤ 10 LOC.)
- **Regression guard:** add a test where `store.list_notebooks` raises (a fake store
  whose coroutine raises `RuntimeError`); assert `report["status"] == "warn"`,
  `checks["notebooks:count"][0]["observedValue"] is None`, AND that a warning was
  logged (`caplog`). The existing suite only covers `store is None`, never a
  throwing store — so the broad `except` body is currently UNEXERCISED.

### F2 — `now`-injection parameter is dead; docstring overclaims deterministic tests

- **Severity:** LOW
- **Source:** adversary
- **File:** server/health.py:284
- **What:** `compute_health_status(..., *, now: float | None = None)` and the derived
  `clock` are documented as "`now` is injectable for deterministic tests," but no test
  passes `now=` (grep `now=` in `tests/test_status_endpoint.py` → no hits). All tests
  drive time via real `time.time()` plus a real recent / 30h-old `backup-status.json`.
  Neither `status_endpoint` nor `ui_status_badge` ever pass `now` either.
- **Why it matters:** the injectable clock — the documented test affordance and the
  one piece of nondeterminism control in the file — has zero coverage, so a future
  refactor could break it undetected. The backup-staleness tests are mildly flaky-prone
  (they depend on wall-clock vs a string timestamp) precisely because they don't use
  the hook that exists for them.
- **Proposed fix:** either (a) add one test that pins `now` to a fixed epoch and
  asserts the `backup:time` warn boundary at exactly `_BACKUP_STALE_SECONDS` (uses the
  parameter as documented), or (b) drop the `now` param if it is not going to be used.
  Prefer (a) — the param is genuinely useful for the staleness math.
- **Regression guard:** the test in (a) IS the guard — assert that a `finished_at`
  exactly `_BACKUP_STALE_SECONDS - 1` before injected `now` is `pass` and exactly
  `+1` after is `warn`.

### F3 — `make status` conflates 503/fail with unreachable; `status_line` fail-label is dead

- **Severity:** LOW
- **Source:** adversary
- **File:** Makefile:103-112
- **What:** On a reachable-but-503 server (`fail` / not-warm), `curl -sf` exits
  non-zero, so the `&&` chain short-circuits to
  `|| echo "DOWN: arxmcp-server not reachable at 127.0.0.1:.../status"`. A server that
  IS reachable but warming up is reported with the word "not reachable." Relatedly,
  `tools/status_line.py:20` maps `"fail" → "DOWN"`, but `compute_health_status` only
  ever emits `fail` with `http_code 503` — never a parseable 200 `fail` body — so the
  `DOWN | corpus v? | ? notebooks` line that `status_line.py` would print for a `fail`
  payload is unreachable on the `make status` path (the `||` branch wins first).
- **Why it matters:** purely cosmetic operator-facing inaccuracy (both states mean
  "not usable"), and a small piece of dead code in the parser. No functional defect:
  the down path is single-output and crash-free as the summary claims.
- **Proposed fix:** (a) soften the message to e.g.
  `"DOWN: arxmcp-server at 127.0.0.1:$(ARXMCP_BIND_PORT)/status is down or warming up"`;
  (b) optionally drop the unreachable `"fail"` row from `_LABELS` or add a comment that
  the 200-fail path is structurally impossible from this server (the parser keeps it
  only for robustness against a hand-fed body).
- **Regression guard:** N/A (cosmetic) — the existing
  `TestStatusLineParser::test_fail_line_with_missing_checks` already pins the parser's
  fail-body output for the hand-fed case.

### F4 — m4 endpoint tests bypass the middleware stack; Deviation #1 unexercised here

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/test_status_endpoint.py:182-189
- **What:** `_app_with()` builds a bare `FastAPI()` with no middleware, then mounts the
  health + ui routers. So the m4 tests for `/status` and `/ui/status-badge` never pass
  through `SecFetchSiteMiddleware` / `SecurityHeadersMiddleware` — the load-bearing
  justification for Deviation #1 (a browser same-origin XHR to `/status` 403s; the
  exemption applies to `/ui/status-badge`) is not asserted by m4's own suite.
- **Why it matters:** the deviation is the single most important design decision in the
  milestone, yet its correctness rests on a pre-existing test
  (`tests/security/test_sec_fetch_site_carveout.py`) that proves a non-`/ui` health
  route (`/healthz`) 403s `Sec-Fetch-Site: same-origin` and that `/ui/*` is exempt by
  prefix. `/status` is on the same `health_router` (non-`/ui`) and `/ui/status-badge`
  is under `/ui`, so the behavior IS structurally guaranteed by that test — but nothing
  names these two paths, so a future router-prefix change to either could silently
  regress the deviation. (I verified the middleware logic by hand:
  `exempt_prefixes=("/ui",)` with `path == p or path.startswith(p + "/")` →
  `/ui/status-badge` exempt, `/status` not → correct.)
- **Proposed fix:** add one test against a real `create_app(cfg)` TestClient (mirror
  `test_sec_fetch_site_carveout.py::_build_test_client`) asserting:
  `GET /status` with `Sec-Fetch-Site: same-origin` → 403 `sec_fetch_site_forbidden`,
  and `GET /ui/status-badge` with the same header → NOT 403 (200 fragment). Pins the
  deviation's two premises to the actual route paths.
- **Regression guard:** the test in the fix IS the guard.

## What was done well

- **Deviation #1 is correct, not just plausible.** Hand-verified: `/ui/status-badge`
  (prefix `/ui`) is SecFetchSite-exempt and the fragment re-emits `hx-get` +
  `hx-trigger="every 10s"` + `hx-swap="outerHTML"` (server/routes/ui.py:174-176), so
  the swapped element keeps polling — the badge does not go stale after the first swap.
- **AC4 is genuinely pinned.** `test_status_degraded_warn_200_AND_readyz_still_503`
  (tests/test_status_endpoint.py:207) asserts BOTH `/status` warn 200 AND `/readyz`
  503 `degraded` in one test; the `/readyz` handler is byte-for-byte untouched in the
  diff.
- **Spec-faithful health+json.** No ad-hoc top-level fields; `corpus_version` /
  `notebook_count` / `uptime` all live inside `checks` keyed `<component>:<measurement>`
  (server/health.py:344-431). `description` is a spec-defined optional top-level field,
  so it is not a violation.
- **Never-500 discipline.** Every probe degrades to `warn` rather than raising; the
  not-warm branch returns fail/503 mirroring `/readyz`; warm-path attribute reads
  (`corpus_info.version`, `config.data_dir`, `config.ops_dir`,
  `process_start_time_seconds`, `degraded`) are all confirmed present on the real
  `Resources`/`Config` dataclasses.
- **Info-leak hygiene.** `output` fields carry only integers + fixed labels; no
  filesystem paths or tracebacks reach the JSON body or the badge. The badge `summary`
  is `html.escape`d (server/routes/ui.py:172) even though it is built from ints + fixed
  labels — correct belt-and-braces.
- **`make status` down-path is single-output and crash-free** — the
  captured-then-piped `out=$$(curl -sf ...) && ... | python || echo DOWN` form avoids
  the classic double-output bug on the unreachable path.
- **Byte-cap parity done right** — `/status` added to `_BYTE_CAP_EXEMPT_PREFIXES`
  (server/main.py:109) alongside the other probes, matched by the same
  prefix-not-substring rule.
- **No banned patterns, no tier-sequencing violation, no fork, no math touched,**
  `ARXMCP_BIND_PORT ?= 7733` correctly mirrors `DEFAULT_BIND_PORT`, and the backup
  staleness math is correct against the real script's `date -u ...Z` UTC output (no
  naive-timezone bug).
- **Defensive parser** — `tools/status_line.py` degrades every missing/`None`/
  malformed field to `?` and never raises on a `warn`/`fail` body.

## Recommended rectification order

1. **F1** (MEDIUM, ~2 LOC + 1 test) — add the missing log line to the notebook-store
   `except` and a throwing-store regression test. Highest leverage: closes the one
   silent-swallow path and the only unexercised branch in `compute_health_status`.
2. **F4** (LOW, 1 test) — pin Deviation #1's two premises to the real `/status` and
   `/ui/status-badge` paths via a `create_app` TestClient. Cheap, protects the
   milestone's central design decision from future router changes.
3. **F2** (LOW, 1 test) — exercise the `now` clock at the `_BACKUP_STALE_SECONDS`
   boundary (or drop the unused param).
4. **F3** (LOW, cosmetic) — soften the `make status` DOWN wording. Defer if Phase 4 is
   tight; record under deferred_findings.

## Rectification status (filled by Phase 4)
