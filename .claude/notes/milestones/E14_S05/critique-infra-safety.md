# E14_S05 — infra-safety critique

**Scope:** `infra/prometheus/alerts.yml` (new) and `ops/cron/arxmcp-delta.sh`
(modified) within `6fca689..c03cfae`.

**Reviewer mandate:** cron-environment portability, Prometheus rule-file
shape, secret-discipline, threshold drift between code and alerts.

---

## What was done well

- **Threshold drift defensively pinned by a test.** `tests/test_alerts_yaml.py::test_disk_full_threshold_matches_implementation`
  (lines 100-119) imports `server.health.DISK_PAUSE_THRESHOLD_BYTES` and
  asserts the numeric literal appears in the `ArXMCPDiskFull` expression.
  This is exactly the cross-link the brief asked for — the magic number
  `10737418240` is not a magic number, it is the test-pinned image of
  `DISK_PAUSE_THRESHOLD_BYTES: int = 10 * 1024**3`
  (`server/health.py:545`). Drift here would fail CI.
- **All four metric families referenced by alerts are actually emitted.**
  `arxmcp_disk_free_bytes` (`server/observability/metrics.py:215`),
  `arxmcp_degraded_mode_active` (`server/observability/metrics.py:229`),
  `arxmcp_eval_quarantine_active` (`server/metrics.py:238`),
  `arxmcp_latexml_drift_fixtures` (`server/metrics.py:200`),
  `arxmcp_backup_last_success_timestamp_seconds` (`server/metrics.py:261`).
  No alert fires on a non-existent metric.
- **Prometheus rule shape is canonical.**
  `infra/prometheus/alerts.yml:18-21` lays out
  `groups → name → interval → rules`, and every rule carries
  `alert / expr / for / labels / annotations` per
  `tests/test_alerts_yaml.py::test_alert_rule_shape` (lines 73-97).
  Severity vocabulary (`critical`, `warning`) is the canonical subset.
- **Sentinel exit-0 semantics are correct.** `ops/cron/arxmcp-delta.sh:75`
  exits `0` when the pause sentinel is present so cron-mailer does not
  spam the operator during a deliberate pause. The block also emits a
  human-readable line to stderr with the clear-command (`python -m
  tools.ingest_sentinel clear`) so the operator does not need to grep
  source to recover.
- **`RESTIC_PASSWORD` discipline holds.** A grep of `git diff
  6fca689..c03cfae` shows zero new occurrences of `RESTIC_PASSWORD=`
  followed by a literal value; every appearance is documentation prose
  about the `RESTIC_PASSWORD_FILE` discipline shipped in E11_S05. AC
  satisfied.
- **`ARXMCP_VOYAGE_API_KEY` is not leaked through any health/metric/
  resource surface.** Grep `voyage_api_key` across `server/health.py`,
  `server/resources.py`, `server/observability/`, `server/main.py`
  returns zero hits. The field exists only in `server/config.py:207`
  as an in-memory `str | None`. The brief's "stored only in memory;
  never logged" comment (`server/config.py:204`) matches actual surface
  area.
- **No `0.0.0.0`-style escape; no CI changes; no container-escape
  surface.** The cron wrapper still runs as the operator under
  `flock(1)`; no new SUID, no `sudo`, no new privileged step.

---

## Findings

### IS1 — HIGH — `runbook_url` annotations point at the wrong GitHub repo slug

**File:** `infra/prometheus/alerts.yml:40,58,76,93,110`

All five `runbook_url` annotations use `github.com/chris-dare/arXMCP/...`.
The actual remote on this repository is
`https://github.com/chris-dare-dev/arXMCP.git` — note the `-dev` suffix.
Every runbook URL emitted by Alertmanager will 404. This is the exact
finding the E11_S05 adversary critique already raised
(`.claude/notes/milestones/E11_S05/critique-adversary.md:356`), repeated
here.

**Why HIGH:** when this alert fires at 02:00 the operator clicks the
runbook URL and is told the page does not exist. The recovery procedure
for the named failure mode is unreachable.

**Fix:** replace `chris-dare/arXMCP` with `chris-dare-dev/arXMCP` in all
five `runbook_url:` lines (40, 58, 76, 93, 110). Or — better for a
local-first project — point at a local file path or a deployment-time
template variable, since the project's design constitution (CLAUDE.md
§4.1) is "single-user, single-workstation" and the operator already has
`docs/ops/failure-modes.md` etc. on their workstation.

### IS2 — MEDIUM — `python3` is not guarded on PATH the way `uv` and `flock` are

**File:** `ops/cron/arxmcp-delta.sh:70-72`

The new sentinel-check block calls `python3 -c '...'` without first
asserting `python3` is on PATH. The cron environment's PATH is typically
`/usr/bin:/bin` only; on macOS Catalina+ and most Linux distros
`/usr/bin/python3` exists by default, but on a fresh Alpine container or
a minimal NixOS profile it does not.

The block does include a `2>/dev/null || echo "malformed_sentinel"`
fallback, so the cron does not crash — it skips with a degraded reason
string. That's why this is MEDIUM not HIGH: the sentinel still wins
(exit 0), the only loss is the diagnostic text.

**Why this is still worth flagging:** the surrounding code (lines 39-48
for `uv`, lines 54-60 for `flock`) sets a precedent of an explicit
`command -v <tool> ... || ERROR + exit 1` block. The new block silently
falls back, which is a different policy. Either the policy is "fail
loud" (then `python3` should get the same guard) or "fail soft" (then
the comment in lines 62-67 should mention the soft-fallback explicitly).

**Fix:** add a one-liner before line 70:

```bash
if ! command -v python3 >/dev/null 2>&1; then
    echo "INFO: ingest paused (reason=unknown; python3 not on PATH); " \
         "skipping delta run." >&2
    exit 0
fi
```

…or document in the block comment that the `python3 -c` failure path is
deliberate.

### IS3 — LOW — `runbook_url` form is a remote URL, not a local path, despite the local-first deployment posture

**File:** `infra/prometheus/alerts.yml:40,58,76,93,110`

The project is a single-user, single-workstation local-first MCP server
(CLAUDE.md §4.1). The operator has the runbook on disk at
`docs/ops/failure-modes.md`, `docs/ops/backup-restore.md`,
`docs/ops/drift-watchdog.md`, `docs/ops/latexml-drift-runbook.md`. Alert
notifications would be more reliable pointing at the on-workstation
file (or omitting `runbook_url` and surfacing the path in
`annotations.description`). A GitHub URL adds a network dependency to
incident response.

**Why LOW:** the GitHub URL is still a valid pointer in principle; the
question of remote-vs-local is an editorial choice with reasonable
trade-offs both ways. Surface this only if the operator wants the
runbook to work when the workstation is offline (which is the failure
mode that often co-occurs with these alerts).

### IS4 — LOW — sentinel-check runs OUTSIDE the flock; theoretical TOCTOU race

**File:** `ops/cron/arxmcp-delta.sh:68-76` vs `:84-85`

The pause-sentinel check happens before `flock -n` acquires the lock. A
concurrent invocation could write the sentinel between line 69 (test)
and line 84 (exec). Result: cron A passes the check and runs the delta;
cron B sees the sentinel and skips. Or: cron A reads a half-written
sentinel JSON during the disk-low scrape's `write_pause()` call (which
is non-atomic from outside the writer).

**Why LOW:** the delta is idempotent (E11_S02 ships
`merge_insert`-driven staging writes), so a single race-driven extra
run is harmless. The `tools.ingest_sentinel` writer uses
`write_text(...)` which is *not* atomic, but a half-written sentinel
yields `json.load(...)` raising and falling back to
`reason="malformed_sentinel"` — the cron then skips, which is the safe
direction.

**Fix (optional):** move the sentinel check inside the flock'd command,
or have `tools.ingest_sentinel.write_pause` write to a `.tmp` and
`os.replace(...)` it for atomic visibility. Neither is required for
correctness; both raise the noise floor.

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 0 |
| HIGH | 1 (IS1 — runbook URLs point at wrong repo slug) |
| MEDIUM | 1 (IS2 — `python3` not PATH-guarded) |
| LOW | 2 (IS3, IS4) |
| **Total** | **4** |

The only blocker for a clean ship is **IS1**: every `runbook_url:` line
in `alerts.yml` resolves to a 404 because the repo slug is
`chris-dare-dev/arXMCP`, not `chris-dare/arXMCP`. Five string
replacements close it. IS2 is a discipline-consistency nudge; IS3/IS4
are editorial.

Outside scope: no `.github/workflows/` changes were in the diff; no
container/dockerfile changes; no new SUID surface; no secrets
introduced. The infra-safety surface for this milestone is otherwise
clean.

---

## Rectification status

- **IS1** (HIGH — runbook URL slug): fixed via sed-replace
  ``s|chris-dare/arXMCP|chris-dare-dev/arXMCP|g`` across all 5
  ``runbook_url:`` lines in ``infra/prometheus/alerts.yml``. The
  alerts now resolve to the correct GitHub paths.
- **IS2** (MEDIUM — python3 PATH guard): fixed. Added
  ``command -v python3 >/dev/null 2>&1`` guard in
  ``ops/cron/arxmcp-delta.sh`` so the cron either invokes
  python3 cleanly or falls back to ``reason=unknown_python3_missing``
  (the soft-fail policy is now explicitly documented inline).
- **IS3** (LOW — remote vs local runbook URL): DEFERRED. Editorial
  choice; the GitHub URL works on a workstation with internet
  and the local file path works offline. The implementation
  summary documents the choice; a future hardening pass may
  switch to local-file URLs when an offline-mode operator
  workflow is documented.
- **IS4** (LOW — TOCTOU race between sentinel check and flock):
  DEFERRED. The cron is idempotent (delta uses ``merge_insert``)
  and the sentinel writer uses ``tmp + replace`` atomic write
  (verified at ``tools/ingest_sentinel.py:142-144``), so a
  half-written sentinel surfaces as ``reason="malformed_sentinel"``
  via ``json.JSONDecodeError`` — the cron skips (safe direction).
  Real harm window is microseconds; not load-bearing for v1.
