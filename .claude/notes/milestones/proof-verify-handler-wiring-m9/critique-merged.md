# Critique — proof-verify-handler-wiring-m9 (merged)

**Critics fired:** adversary (1; infra-safety / oss-scout / frontend-UX
did not fire — no infra paths in diff, no OSS-scout opt-in, no frontend
critic in arXMCP).

**Verdict:** SHIP-WITH-FIXES (adversary).

## Findings summary

| ID | Sev | Source | Title | Phase-4 status |
|---|---|---|---|---|
| F1 | HIGH | adversary | `CancelledError` leaks past `except Exception` — task pins DB row to `running` and orphans the subprocess on cancel | CLOSED — added explicit `except asyncio.CancelledError` branch in `_run_ingest_subprocess` that terminates the subprocess (SIGTERM + 2s grace + SIGKILL) AND writes a `failed` row with `exit_code=-2` + `"cancelled at daemon shutdown"` before re-raising. Regression test: `TestCancelPathWritesFailedRow` |
| F2 | HIGH | adversary | 1-hour orphan-recovery cutoff blocks operators for up to 55 minutes after clean restart-during-ingest | CLOSED — lowered the lifespan cutoff from `hours=1` to `minutes=5`. With F1 writing the failed row inline on clean shutdown, the orphan-recovery is purely defense-in-depth for hard-kill paths (SIGKILL, OOM-killer, host crash). The 5-min window bounds operator-visible "permanent 409" to a single restart-loop cycle |
| F3 | MEDIUM | adversary | `mark_orphaned_runs_failed` stores `message` arg into `stderr_tail` without HTML escape — contract drift waiting to bite | CLOSED — added `html.escape(message)` in `_update` closure; updated method docstring to name the new "storage is the single source of truth for safe-to-render HTML" contract. Regression test: `TestOrphanRecoveryEscapesMessage` |
| F4 | MEDIUM | adversary | Path-redaction regex skips paths with spaces (macOS `/Users/Joe Smith/...`) | CLOSED — added literal space to the character class: `rb"[/\\][\w /\\.\-]*?var[/\\]arxmcp[/\\]"`. Regression: 2 new parametrized cases in `TestPathRedaction::test_redact_paths` (single-space + double-space macOS usernames) |
| F5 | MEDIUM | adversary | `INGEST_STATUS_*` constants live on `NotebooksStore` (a persistence class); domain-vs-storage coupling | **DEFERRED** — pure refactor; no behavior change. Tests pin the string values either way. Would touch 3 files. Defer to a future cleanup pass; not load-bearing |
| F6 | MEDIUM | adversary | `latest_ingest` doesn't consult the in-memory tracker — design choice, but inconsistency with `trigger_ingest` warrants a comment | CLOSED — added a 6-line docstring block to `latest_ingest` explaining that DB is authoritative for polling because both the cancel-path and happy-path UPDATE the row inline; tracker is consulted ONLY by the trigger's 409 check |
| F7 | LOW | adversary | `_get_ingest_tracker(request)` carries `# noqa: ARG001` but `request` IS used | CLOSED — removed the bogus noqa |
| F8 | LOW | adversary | Test polling loop runs up to 20 times to catch task completion; masks ordering | **DEFERRED** — test polish; the loops work today and the bound is large enough to absorb scheduler jitter. Tightening would either require exposing tracker internals or risk flakey tests |
| F9 | LOW | adversary | `_tasks` dict isn't cleared at `shutdown()` end | **DEFERRED** — lifespan-end leak bounded by process exit. Not load-bearing |

## Rectification artifacts

- `server/ingest_tracker.py`:
  - Added `except asyncio.CancelledError` branch in
    `_run_ingest_subprocess` — subprocess termination + terminal
    DB write + re-raise. ~30 LOC. **F1 closure.**
  - Added literal space to `_ABS_PATH_PREFIX_RE` character class
    + docstring note about macOS usernames. **F4 closure.**
- `server/main.py` — lowered orphan-recovery cutoff from
  `timedelta(hours=1)` to `timedelta(minutes=5)`; expanded the
  comment to document the new "defense-in-depth for hard-kill
  paths only" rationale (relying on F1's cancel-path for clean
  shutdown). **F2 closure.**
- `server/notebooks_store.py`:
  - Added module-scope `import html`.
  - `mark_orphaned_runs_failed._update` now stores
    `html.escape(message)` instead of raw `message`. Docstring
    extended to name the contract. **F3 closure.**
- `server/routes/notebooks.py`:
  - Removed `# noqa: ARG001` from `_get_ingest_tracker`. **F7 closure.**
  - Added a 6-line docstring block to `latest_ingest` explaining
    the DB-is-authoritative-for-polling rationale. **F6 closure.**
- `tests/test_ingest_endpoint.py`:
  - 2 new parametrized cases in `TestPathRedaction::test_redact_paths`
    for macOS-spaces. **F4 regression guard.**
  - `TestCancelPathWritesFailedRow` (1 test) — spawns a hung
    subprocess via fake-spawn, calls `tracker.shutdown(timeout=1.0)`,
    asserts the row was updated to `failed` with `exit_code=-2`
    AND `proc.terminate()` was called. **F1 regression guard.**
  - `TestOrphanRecoveryEscapesMessage` (1 test) — passes
    `"<script>alert(1)</script>"` as the message; asserts the raw
    tag is absent + the escaped form is present in storage.
    **F3 regression guard.**

## Final test count

`make test`: **2465 passed** (+4 from rect: 2 path-redaction macOS
cases + 1 F1 cancel-path + 1 F3 escape; total +27 across m9 feat +
rect), 9 skipped, 1 xfailed. Ruff clean.

## Deferred findings

- **F5 (MEDIUM)** — `INGEST_STATUS_*` constants live on the
  persistence class. Pure refactor; no behavior change; tests
  agree on the string values. Defer to a future cleanup pass.
- **F8 (LOW)** — test polling loop bound of 20. Works today;
  tightening risks flakey tests without exposing tracker internals.
- **F9 (LOW)** — `_tasks` dict not cleared at `shutdown()`-end.
  Lifespan-end leak bounded by process exit.

## Re-verify gate notes

All CRITICAL + HIGH findings re-verified before fixing:

- **F1** (HIGH): confirmed at `server/ingest_tracker.py:205-245`
  that the only catch is `except Exception` — Python 3.8+
  `CancelledError` inherits from `BaseException`, not
  `Exception`, so the await raise on `task.cancel()` propagates
  past the catch without updating the DB row. Verified by reading
  Python's `asyncio.CancelledError` source.
- **F2** (HIGH): confirmed at `server/main.py:344` the cutoff was
  `timedelta(hours=1)`. With F1 unfixed, a clean shutdown 5 min
  into an ingest leaves the row pinned for 55 minutes.

Zero findings invalidated. Adversary invalidation rate: **0 / 2
(0%)** for HIGH+CRITICAL; well under the 40% threshold.

## Cross-critic agreement

N/A — only one critic fired (adversary).
