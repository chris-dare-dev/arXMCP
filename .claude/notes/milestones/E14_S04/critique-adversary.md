# Critique — E14_S04

**Critic:** adversary
**Generated:** 2026-05-16T00:00:00Z
**Commit range:** 028cd35..99e1949
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES: one HIGH bug in `tools/quarterly_drill_reminder.sh`
  silently produces a malformed flag write when the embedded Python heredoc
  fails — set -euo pipefail does NOT trap cmd-substitution failures inside
  `read`, the script then falls through both numeric guards and writes
  `quarterly-drill--Q.flag` with empty fields.
- Finding counts: 0 CRITICAL, 1 HIGH, 6 MEDIUM, 3 LOW.
- Highest-risk file: `tools/quarterly_drill_reminder.sh:48-69`.
- Cross-axis pattern: the milestone is operator-facing tooling and every
  finding flagged is in operator-foot-gun territory (silent SMTP errors,
  side-effecting test, missing backup state surface) rather than data /
  invariant territory — consistent with the "ops runbook" framing.
- Cache byte-stability: clean. No server source touched; TOOL_SCHEMA_VERSION
  pinned at 6.
- AC drift on "quarterly drill writes a file" is documented in synthesis
  D10 — the literal wording is unmet but the reinterpretation (`--dry-run`
  must not side-effect) is correct. Flagged LOW, not HIGH.
- The fixture has no regeneration script. Future metric-name drift (e.g.
  E10 emits `arxmcp_ingest_papers_processed_total`) will make the fixture
  stale without anyone noticing.
- E11_S04 watchdog systemd parity-fill scope expansion is defensible — the
  E11_S04 cron wrapper exists but has no systemd unit; landing it here
  closes a real production gap.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Quarterly drill silently writes malformed flag if python heredoc fails

- **Severity:** HIGH
- **Source:** adversary
- **File:** tools/quarterly_drill_reminder.sh:48-69
- **What:** The script computes `DAYS_UNTIL NEXT_YEAR NEXT_QUARTER` by
  `read -r ... <<<"$(python3 - <<'PY' ... PY)"`. Under `set -euo pipefail`,
  bash does NOT abort on a failure inside a command substitution that
  feeds `read` — verified empirically: `python3 -c "sys.exit(1)"` inside
  the heredoc produces an empty `DAYS_UNTIL`. The guard
  `[ "${DAYS_UNTIL}" -gt 7 ] || [ "${DAYS_UNTIL}" -lt 0 ]` writes
  "integer expression expected" to stderr but BOTH branches evaluate
  false, so the script falls through to the in-window path and writes
  `var/arxmcp/ops/reminders/quarterly-drill--Q.flag` (empty `${NEXT_YEAR}`,
  empty `${NEXT_QUARTER}`).
- **Why it matters:** The reminder system is the operator's only signal
  that DR is overdue. A silent malformed write — same filename every
  failed run — masks the "no reminder fired" condition AND poisons the
  reminders dir with junk that an operator might mistake for a real flag.
  The "INFO: wrote reminder to ..." log message even fires successfully
  with an empty path component, making the failure invisible to
  journalctl review.
- **Proposed fix:** Capture the python output to a variable, check its
  exit status, abort with a clear error if empty.
  ```bash
  DRILL_TUPLE="$(python3 - <<'PY'
  ...
  PY
  )" || {
    echo "ERROR: quarterly date math failed; aborting" >&2
    exit 1
  }
  read -r DAYS_UNTIL NEXT_YEAR NEXT_QUARTER <<<"${DRILL_TUPLE}"
  if [ -z "${DAYS_UNTIL}" ] || [ -z "${NEXT_YEAR}" ] || [ -z "${NEXT_QUARTER}" ]; then
    echo "ERROR: quarterly date math produced empty fields" >&2
    exit 1
  fi
  ```
- **Regression guard:** `tests/test_quarterly_drill_reminder.py` add
  a test that patches PATH to point at a `python3` shim that exits 1,
  invokes the script, asserts exit code != 0 AND no flag-file with empty
  name segments was written.

### F2 — `maybe_email` SMTP failure makes cron job exit non-zero after success

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tools/daily_metrics_report.py:489-494
- **What:** `with smtplib.SMTP(...) as s: ... s.send_message(msg)` has zero
  exception handling. `main()` only catches `FileNotFoundError` and
  `urllib.error.URLError` in `fetch_metrics_text`. An SMTP send failure
  (refused recipient, connection refused, malformed `MAIL_FROM`, auth
  failure, TLS-required-but-not-opted-in) propagates an uncaught
  exception. By call-order this happens AFTER `out_path.write_text(body)`
  has succeeded, so:
  - The daily report file IS on disk.
  - The cron job exits non-zero with a Python traceback.
  - On systemd, this turns into a journalctl entry that triggers the
    operator's "did the daily report fail?" alarm — when really it
    succeeded but email is misconfigured.
- **Why it matters:** False alarms degrade signal-to-noise on the very
  surface this milestone is supposed to make operators trust. Foot-gun
  named explicitly in the milestone brief as "operator-shooting-themselves-
  in-the-foot pattern" but at the SMTP layer it's actually misconfiguration,
  not user input.
- **Proposed fix:** Wrap the SMTP body in `try/except smtplib.SMTPException
  as exc: logger.error("email delivery failed: %s", exc)` and return
  normally. The daily report is the artifact; email is an opt-in
  notification channel — its failure should not poison the cron exit
  status.
- **Regression guard:** `tests/test_daily_metrics_report.py::TestMaybeEmail::
  test_smtp_failure_does_not_raise` — patch `smtplib.SMTP` so
  `send_message` raises `SMTPRecipientsRefused`, assert `maybe_email`
  returns normally and an ERROR log line is emitted.

### F3 — `daily_metrics_report` does not surface `arxmcp_backup_status` state

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tools/daily_metrics_report.py:398-427
- **What:** The Sentinels section reads `_backup_age_seconds` (derived
  from `arxmcp_backup_last_success_timestamp_seconds`) and renders "Xh
  ago" — but does NOT render `arxmcp_backup_status{state}` at all.
  `_BACKUP_STATES` from E14_S01 is `("ok", "failed", "running",
  "unknown")`. A backup that actually FAILED but whose `finished_at`
  field still got updated (the failure path can produce a non-zero
  timestamp on partial success — per `server/health.py:341`) appears as
  "2h ago" in the daily report, masking the failed status entirely. The
  alert-thresholds table in `docs/ops/daily-ops-cadence.md` mentions
  `arxmcp_backup_status{state="failed"} == 1` as a Grafana condition,
  but the daily report itself ignores it.
- **Why it matters:** The daily report is the operator's morning-after
  surface for overnight state. If backup status is silently misrendered
  the operator believes the backup succeeded when it failed.
- **Proposed fix:** Add a single line under the Backup sentinel that
  reads `arxmcp_backup_status{state=...}` and renders the active state
  alongside the age. The data is already in `_BACKUP_STATES`; the parser
  exposes it.
- **Regression guard:** `tests/test_daily_metrics_report.py` add a
  fixture variant that sets `arxmcp_backup_status{state="failed"} 1.0`
  and assert the word "failed" appears in the rendered report.

### F4 — Fixture has no regeneration script; will silently drift on metric rename

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/fixtures/metrics_sample.txt:1
- **What:** The 404-line fixture is hand-generated per the implementation
  summary "Generated by populating the prometheus_client registry with
  synthetic samples and calling `generate_latest()`." No script under
  `tools/` or `tests/` regenerates it. When E10/E11 lands a metric rename
  (e.g. `arxmcp_ingest_papers_processed_total` becoming a real emitter)
  the fixture stays valid as Prometheus exposition format BUT the daily
  report's `Ingestion throughput` placeholder section will continue to
  render the "not yet wired" copy forever — silently — because the
  rendering only checks for absence of the family name, not for changes.
- **Why it matters:** Latent foot-gun. Either the fixture turns into
  stale binary-ish blob nobody re-touches, or someone hand-edits it
  with typos and the test passes against the typo.
- **Proposed fix:** Add `tools/regen_metrics_fixture.py` (~30 LOC) that
  populates the prometheus_client default registry exactly as the
  implementation summary says, calls `generate_latest()`, writes to
  `tests/fixtures/metrics_sample.txt`. Add a single test that imports
  the regen module and asserts its output equals the on-disk fixture
  (the `pytest --regen-fixture` pattern from chunker fixtures —
  `.claude/docs/chunker-fixtures.md`).
- **Regression guard:** `tests/test_daily_metrics_report.py::
  test_fixture_matches_regen_script` — if a metric family disappears
  from `server/metrics.py`, the regen test fails loudly.

### F5 — `test_real_invocation_exits_zero` is side-effecting close to quarter marks

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_quarterly_drill_reminder.py:85-104
- **What:** The test runs `bash tools/quarterly_drill_reminder.sh`
  WITHOUT `--dry-run`, against the real calendar. When within 7 days of
  a quarter mark (Mar 25-31, Jun 24-30, Sep 24-30, Dec 25-31), the
  in-window branch writes a real flag to
  `var/arxmcp/ops/reminders/quarterly-drill-<Y>-Q<N>.flag` inside the
  actual repo tree, not a tmp_path. Today (2026-05-16) is safe;
  2026-06-24 onward is not.
- **Why it matters:** Tests creating untracked files in the repo tree is
  an established anti-pattern in this project (per the `tests/conftest.py`
  autouse fixture pattern). It also produces flaky CI behavior if any
  cleanup happens between test runs.
- **Proposed fix:** Either invoke the script via tmp_path copy (the
  pattern `test_dry_run_does_not_write_reminder_file` already
  demonstrates — copy the script into `tmp_path/fake-repo/tools/` and
  run from there), OR add a `pytest.mark.skipif` that skips when within
  7 days of a quarter mark (mirror the explicit short-circuit logic in
  `test_short_circuit_logic_short_circuits_for_out_of_window`).
- **Regression guard:** The skipif/copy-to-tmp_path approach is itself
  the guard.

### F6 — `histogram_quantile` silently accepts malformed input (no +Inf bucket)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tools/daily_metrics_report.py:87-135
- **What:** Prometheus exposition contract REQUIRES a `le="+Inf"` bucket
  on every histogram. The current implementation:
  `histogram_quantile(0.95, [(0.1, 100.0)])` returns `0.095` —
  interpolates within the only bucket and produces a plausible-looking
  result. There's no validation that the last bucket boundary is `+Inf`.
  An operator handing the function a malformed histogram (or a future
  exporter that drops the +Inf bucket) gets a silently wrong number.
- **Why it matters:** The function is exported and reusable; any future
  caller that doesn't know this constraint gets a silent foot-gun. The
  daily report itself is safe today because prometheus_client always
  emits the +Inf bucket, but the contract should be enforced at the
  function boundary.
- **Proposed fix:** Add a guard at the top of the function:
  ```python
  if buckets and buckets[-1][0] != float("inf"):
      raise ValueError(
          "histogram missing +Inf bucket; expositions without "
          "le='+Inf' are malformed per Prometheus spec"
      )
  ```
  Add a test that the raise fires.
- **Regression guard:** `tests/test_daily_metrics_report.py::
  TestHistogramQuantile::test_missing_plus_inf_bucket_raises`.

### F7 — `tools/parser_failures_report.py` glob-by-allowlist mtime-fallback misorders weeks

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tools/parser_failures_report.py:219-258
- **What:** `filter_by_week` uses the source file's mtime when a TSV row
  has no timestamp. But the mtime reflects the LAST write to the log
  file (append-only). A `chunk.log` that was last appended-to yesterday
  has mtime = yesterday; ALL its TSV rows — including rows from 3 weeks
  ago — get filtered into this week's report. The comment "conservative:
  surface them rather than silently drop" is a defensible policy
  decision, but the consequence is duplicate triage of the same rows
  every week until the operator rotates the log.
- **Why it matters:** The weekly report becomes monotonically larger as
  the year goes on. Operators triaging it will see "this same latexml
  crash failed last week and the week before" — because it did, and
  because the report can't distinguish "happened this week" from
  "appeared in the file this week." The TSV producers (chunker /
  preamble / embedder / seed-fetcher) should be emitting timestamps; the
  reporter is papering over an upstream gap.
- **Proposed fix:** Either (a) document the limitation prominently in
  `docs/ops/parser-failure-review.md` § Manual run, OR (b) require TSV
  rows to include a 5th column timestamp and reject pre-timestamp rows
  with a single-WARNING-per-file log line. Option (a) is the cheaper
  fix.
- **Regression guard:** Already covered by
  `test_untimestamped_rows_pass_through_without_mtime`, but expand the
  test to assert the mtime branch returns the row when mtime matches
  AND the test isn't a tautology of the implementation.

### F8 — `crontab` syntax test is awk-shallow, doesn't exercise the real binary

- **Severity:** LOW
- **Source:** adversary
- **File:** ops/cron/arxmcp-cron.cron:1
- **What:** Brief AC: "All cron entries pass `crontab -l | crontab -`
  syntax validation." The shipped test surface verifies only that lines
  have ≥6 fields (via `awk 'NF < 6'`). Real `crontab` syntax checks
  reject things like `60 0 * * *` (minute > 59), `0 24 * * *` (hour
  > 23), and so on; the awk check would silently accept these.
- **Why it matters:** The AC's literal "passes crontab validation" isn't
  exercised. Today's 6 entries are all valid; future drift wouldn't be
  caught.
- **Proposed fix:** Add a test that invokes `crontab -T ops/cron/arxmcp-
  cron.cron` (the `-T` flag does dry-run validation on the cron(5)
  syntax on Linux), skipping under `shutil.which("crontab") is None`.
  Note: BSD crontab on macOS does not support `-T`; the test must skip
  on Darwin or use a different validator. A pure-Python parser of the
  5-field syntax is also acceptable (and platform-independent).
- **Regression guard:** The new test itself.

### F9 — AC drift on quarterly drill `--dry-run` "writes a reminder file"

- **Severity:** LOW
- **Source:** adversary
- **File:** tools/quarterly_drill_reminder.sh:85-89
- **What:** Brief AC: "`tools/quarterly_drill_reminder.sh --dry-run`
  writes a reminder file without error." The shipped behavior (D10
  decision) is: `--dry-run` PRINTS what it would do, EXITS 0, but
  does NOT write the file. The synthesis reinterpretation
  ("dry-runs shouldn't side-effect") is defensible engineering practice,
  but the literal AC is unmet. The implementation-summary §"Acceptance
  criteria status" claims the AC is met, citing
  `test_dry_run_exits_zero` — which doesn't test for the file write.
- **Why it matters:** AC drift is documented in the synthesis as a
  conscious decision but the implementation-summary marks it as
  "[x] verified." The audit trail is inconsistent. A future reader
  comparing brief vs implementation will read this as scope drift not
  yet justified.
- **Proposed fix:** Edit the implementation-summary AC line to say
  "deliberate AC reinterpretation per D10: dry-run prints intent
  without disk side effects; flagged by F9 of E14_S04 critique." OR
  rewrite the brief AC in the milestone state.json to reflect the
  shipped behavior.
- **Regression guard:** N/A (documentation update).

### F10 — Systemd unit `/opt/arxmcp` placeholder lacks loud failure on substitution miss

- **Severity:** LOW
- **Source:** adversary
- **File:** ops/systemd/arxmcp-daily-report.service:15-23
- **What:** Comment block says "Operator MUST substitute these
  placeholders before enabling." If the operator forgets,
  `systemctl enable --now arxmcp-daily-report.timer` succeeds, the timer
  fires at 05:00 UTC, the service unit tries `cd /opt/arxmcp` which
  doesn't exist on the operator's host, the unit fails, journalctl
  records the failure. The operator sees nothing until they manually
  inspect `systemctl status arxmcp-daily-report`. This is the documented
  Linux ops pattern in this project (matches `arxmcp-delta.service` /
  `arxmcp-backup.service`) so consistency wins, but it's worth
  documenting the substitution step more prominently than a comment
  block inside the service file.
- **Why it matters:** Cron entries (`/opt/arxmcp/ops/cron/*.sh`) and
  systemd unit (`WorkingDirectory=/opt/arxmcp`, `ExecStart=`,
  `ReadWritePaths=`) all bake the path in. Operators on macOS or with
  a different checkout root must hand-substitute 3-4 lines per file
  across 8 files. Easy to miss one.
- **Proposed fix:** Add a top-level shell script
  `ops/systemd/render-units.sh` (~30 LOC) that takes `ARXMCP_ROOT=` and
  `ARXMCP_USER=`, sed-substitutes them across all `*.{service,timer}`
  files, and emits the rendered output to a chosen directory. Reference
  it from `docs/ops/daily-ops-cadence.md` § Enabling the schedule
  before the install command.
- **Regression guard:** N/A (operator-tooling change).

## What was done well

- The `histogram_quantile` implementation correctly mirrors Prometheus's
  promql/quantile.go algorithm with both clamping behaviors (empty-bucket
  clamp, +Inf overflow clamp). Test coverage at
  `tests/test_daily_metrics_report.py:44-76` is solid.
- The `_request_counts` filter handles the prometheus_client family-name
  vs sample-name distinction correctly. The adversary's concern about
  `_total` stripping is invalidated — `fam.samples[i].name` retains the
  full name with `_total`, so `s.name == "arxmcp_request_total"` is
  the right check.
- The cron wrappers correctly resolve `REPO_ROOT` via `BASH_SOURCE`
  rather than `$PWD`, so cron's "user's home as cwd" default doesn't
  break path resolution. Test
  `test_script_resolves_repo_root_via_bash_source` pins this.
- `flock -n` reentrancy on the daily-report and parser-failures wrappers
  prevents two concurrent runs from racing on the same `var/arxmcp/
  ops/daily-reports/<date>.md` write.
- The `--dry-run` + `--fixture` contract on
  `tools/daily_metrics_report.py` is a clean separation: tests never
  hit the network, never write to disk, and run in <100ms each.
- E11_S04 watchdog systemd parity-fill is the right scope expansion —
  the cron wrapper was orphaned and landing the unit pair here closes a
  real production gap with zero coupling cost.
- The `arxmcp-cron.cron` consolidated fragment with UTC comments + 5-field
  shape + flock-based reentrancy demonstrates the macOS-fallback
  discipline the project's CLAUDE.md asks for.
- `docs/ops/daily-ops-cadence.md` documents the drift from note 08's
  aspirational schedule rather than hiding it — flagging the divergence
  in a sidebar is the right transparency choice and matches the project's
  "documented drift > silent drift" pattern.
- The 7-day quarterly-lookahead via daily-cron + Python date math is
  more robust than a `OnCalendar=*-01,04,07,10-*` systemd pattern would
  be: leap years, DST quirks, and BSD-vs-GNU `date` differences don't
  break the date math.
- The parser-failures report's `(stage, reason)` Counter rollup with
  display-string truncation at 160 chars produces a readable triage
  table even with arbitrarily long error strings — operator-friendly by
  default.

## Recommended rectification order

1. **F1 (HIGH)** — fix the quarterly-drill silent-failure first. Touches
   one file, ~10 LOC, isolatable.
2. **F2 (MEDIUM)** — wrap SMTP send in try/except. ~5 LOC + 1 test.
3. **F3 (MEDIUM)** — surface `arxmcp_backup_status{state}` in daily
   report. ~10 LOC + fixture-variant test.
4. **F6 (MEDIUM)** — guard `histogram_quantile` against missing +Inf
   bucket. ~3 LOC + 1 test.
5. **F4 (MEDIUM)** — fixture regeneration script. ~30 LOC. Best done
   after F3 since F3 modifies the fixture-dependent code.
6. **F5 (MEDIUM)** — make `test_real_invocation_exits_zero` non-side-
   effecting. Copy-to-tmp_path pattern, ~10 LOC test change.
7. **F7 (MEDIUM)** — document the parser-failures mtime-fallback
   limitation in `docs/ops/parser-failure-review.md`. ~5 lines of
   markdown.
8. **F8 (LOW)** — defer. Real `crontab -T` test is platform-coupled;
   pure-Python parser is overkill for 6 entries.
9. **F9 (LOW)** — defer or fix as a 1-line implementation-summary edit.
10. **F10 (LOW)** — defer. Operator-tooling improvement, not a bug.

## Rectification status (filled by Phase 4)

- **F1** (HIGH — quarterly-drill silent malformed flag): fixed.
  Added `if ! DRILL_TUPLE="$(python3 - <<'PY' ... PY)"; then
  exit 1; fi` plus an empty-field guard around `read -r`. Both
  failure paths now exit non-zero with actionable error messages.
  Regression test
  `tests/test_quarterly_drill_reminder.py::test_aborts_when_python_heredoc_fails`
  injects a fake python3 that exits 1 and asserts non-zero exit
  + the error string in stderr + no malformed flag-file write.
- **F2** (MEDIUM — SMTP failure crashes cron): fixed. Wrapped
  the SMTP body in `try/except (smtplib.SMTPException, OSError)`
  with an ERROR log. Tests
  `test_smtp_failure_does_not_raise` (SMTP-protocol failure) and
  `test_smtp_network_failure_does_not_raise` (pre-handshake
  OSError) pin the contract.
- **F3** (MEDIUM — backup state not surfaced): fixed. New
  `_backup_status_active_state` helper reads
  `arxmcp_backup_status{state}` and renders alongside the age
  (e.g. "1h ago (failed)"). Regression guards
  `test_failed_state_surfaces_in_report` and
  `test_ok_state_renders_without_noise`.
- **F4** (MEDIUM — fixture has no regen script): fixed. New
  `tools/regen_metrics_fixture.py` populates the prometheus_client
  default registry with the same synthetic samples and calls
  `generate_latest()`. Regression test
  `TestRegenFixture::test_regen_matches_checked_in_fixture` runs
  the regen as a subprocess and diff-compares against the checked-in
  fixture, after stripping non-deterministic `_created` /
  `python_*` / `process_*` lines.
- **F5** (MEDIUM — test_real_invocation side-effecting): fixed.
  Copy the script into a `tmp_path/fake-repo/` tree before
  invoking; the real repo's `var/` stays untouched regardless of
  calendar position relative to quarter marks.
- **F6** (MEDIUM — histogram_quantile silently accepts malformed
  input): fixed. Added a guard at function entry that raises
  `ValueError` if the highest bucket boundary is not `+Inf`.
  Regression guards
  `test_raises_when_plus_inf_bucket_missing` and
  `test_accepts_well_formed_histogram_with_plus_inf`.
- **F7** (MEDIUM — TSV mtime-fallback misorders weeks): doc-only
  fix. Added a "Known limitation" §"TSV rows without
  timestamps" to `docs/ops/parser-failure-review.md` documenting
  the mtime-fallback behavior, the consequence (TSV rows can
  re-surface week-over-week until log rotation), and two
  workarounds (manual log rotate, future 5th-column timestamp).
- **F8** (LOW — crontab syntax test shallow): DEFERRED.
  Platform-coupled (`crontab -T` is GNU-only; BSD/macOS lacks
  it). The 5-field shape check + the consolidated fragment's
  inline UTC-time comments are sufficient defense for v1.
  Pure-Python parser deferred to a future ops-tooling milestone.
- **F9** (LOW — AC drift documented inconsistently): fixed.
  Annotated the AC checkbox for the quarterly-drill `--dry-run`
  in `implementation-summary.md` with the synthesis-D10
  reinterpretation rationale.
- **F10** (LOW — `/opt/arxmcp` substitution placeholder): partly
  addressed by IS1 (crontab fragment now has a substitution
  warning in its header). A `render-units.sh` script is
  DEFERRED — adds operator-tooling complexity that the existing
  comment-block approach already covers via the project's
  precedent in `arxmcp-delta.service` / `arxmcp-backup.service`.
