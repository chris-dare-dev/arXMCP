# E14_S04 — Research synthesis (orchestrator-merged)

**Sources:** [research-brief-1.md](research-brief-1.md) (in-codebase,
157 LOC) + [research-brief-2.md](research-brief-2.md) (external +
patterns, 364 LOC). Both researchers converged on the same load-
bearing corrections to the brief.

---

## 1. Headline findings

1. **`infra/cron/` is wrong — use `ops/cron/` and `ops/systemd/`.**
   Both researchers independently confirmed: `infra/cron/` does
   not exist; the established convention from E11_S02 / E11_S04 /
   E11_S05 is `ops/cron/<name>.sh` for wrappers and
   `ops/systemd/<name>.{service,timer}` for unit pairs. Treat the
   brief's `infra/cron/` as a typo.
2. **`tools/parser_failures_report.py` does NOT exist.** The brief
   asserts it was "authored in E02_S06" but **E02 stops at S05**;
   no such milestone exists, and no such script exists. This is a
   phantom dependency. Resolution per D2 (below): author the
   script as part of this milestone.
3. **Note 08 cadence drifts from shipped reality.** Note 08 says
   "00:00 UTC delta, 04:10 backup, 05:00 metrics report"; the
   actual landed crons say 02:00 delta, 02:30 watchdog, 03:30
   backup. The new `docs/ops/daily-ops-cadence.md` documents
   shipped UTC times, not the aspirational ones from note 08.
4. **Cache label is `tier`, not `layer`.** `server/metrics.py`
   ships `arxmcp_cache_*_total{tier=...}`. Note 08's
   `{layer=...}` form is constitutional drift — out of scope here.
5. **Cron is 5-field, not 6-field.** The brief's "6-field format"
   wording is a slip; standard `crontab(5)` is 5 time fields +
   command. (Six-field cron is the Quartz / systemd-with-seconds
   variant.)
6. **`.timer` files alone are not executable.** The brief lists
   `.timer` files only; the systemd idiom is the `.timer` +
   `.service` pair. Ship both per the existing E11 precedent.
7. **The E11_S04 watchdog cron has a `.sh` wrapper but no
   `.service` / `.timer`.** Worth landing the systemd pair in
   this milestone while we're here.
8. **Ingestion-throughput metrics are not yet emitted.**
   `arxmcp_ingest_papers_processed_total` /
   `arxmcp_ingest_chunks_written_total` are named in note 08 but
   nothing emits them. The daily report falls back to reading
   `var/arxmcp/ops/delta-status.json` (if present) or shows "n/a
   — ingest metrics not yet wired".
9. **Doc placement: `docs/ops/`.** Grandfathered for E11 ops
   runbooks per CLAUDE.md §1. `docs/ops/daily-ops-cadence.md`
   and `docs/ops/parser-failure-review.md` fit the precedent
   directly.
10. **No new deps.** `prometheus-client>=0.20` (already in
    `pyproject.toml`) has `text_string_to_metric_families` for
    client-side scraping; stdlib `smtplib` + `email.message`
    handle the opt-in email path; stdlib `datetime` handles
    quarterly date math. No `tabulate`.

---

## 2. Decisions

### D1. File placement — `ops/cron/` and `ops/systemd/`

Reject the brief's `infra/cron/`. Deliverables land at:

- `ops/cron/arxmcp-daily-report.sh` (wrapper)
- `ops/cron/arxmcp-parser-failures-weekly.sh` (wrapper)
- `ops/cron/arxmcp-quarterly-drill.sh` (wrapper)
- `ops/cron/arxmcp-cron.cron` (single crontab fragment with all
  three lines + comment headers; matches existing convention)
- `ops/systemd/arxmcp-daily-report.{service,timer}`
- `ops/systemd/arxmcp-parser-failures-weekly.{service,timer}`
- `ops/systemd/arxmcp-quarterly-drill.{service,timer}`
- `ops/systemd/arxmcp-watchdog.{service,timer}` (E11_S04 parity
  fill — addresses finding 7)
- `tools/daily_metrics_report.py`
- `tools/parser_failures_report.py` (scope expansion per D2)
- `tools/quarterly_drill_reminder.sh` — recommends keeping the
  pure-shell version BESIDE the wrapper so `--dry-run` exists
  as the brief requires; the wrapper invokes it.

### D2. Author the missing `tools/parser_failures_report.py`

The brief assumes this script exists. It does not, and the
referenced "E02_S06" is fictional. Author it as part of this
milestone — ~150 LOC of Python:

- Glob `var/arxmcp/ops/parser-failures/*.{log,jsonl}`
- Read TSV files (`chunk.log`, `preamble.log`, `embed.log`,
  `seed.log`) with the 4-column `paper_id\tstatus\tduration_s\treason`
  shape
- Read JSONL files (`delta.jsonl`, `re-embed.jsonl`, `bulk.jsonl`)
- Filter to the ISO-week window via `date.isocalendar()`
- Group by `(stage, reason)` regex; produce top-N by count
- Markdown render to
  `var/arxmcp/ops/reports/parser-failures-<YYYY>-W<NN>.md`
- `--dry-run` flag prints to stdout instead

### D3. Histogram quantile — linear interpolation

Pure bucket-walk would quantise P99 to bucket edges (5.0s ceiling
on the existing `arxmcp_request_latency_seconds` family — useless
for any tool that lives in the 100ms-1s range). Implement
Prometheus's `promql/quantile.go` algorithm verbatim:

```python
def histogram_quantile(q: float, buckets: list[tuple[float, float]]) -> float:
    """buckets = sorted [(le, cumulative_count), ...]; +Inf bucket required."""
    if not buckets:
        return float("nan")
    total = buckets[-1][1]
    if total == 0:
        return float("nan")
    rank = q * total
    prev_le, prev_count = 0.0, 0.0
    for le, count in buckets:
        if count >= rank:
            if le == float("inf"):
                return prev_le
            if prev_count == count:
                return prev_le
            return prev_le + (le - prev_le) * (rank - prev_count) / (count - prev_count)
        prev_le, prev_count = le, count
    return buckets[-1][0]
```

Tests pin both bucket-edge and within-bucket interpolation cases.

### D4. Cache labels — `tier`, not `layer`

The daily report scrapes `arxmcp_cache_hits_total{tier="1"|"2"|"3"}`
and `arxmcp_cache_lookups_total{tier=...}`. Hit-rate per tier =
hits / lookups. Note 08's `{layer=...}` form is constitutional
drift; out of scope to fix here.

### D5. Cadence reconciliation — document shipped UTC times

The new `docs/ops/daily-ops-cadence.md` lists the actual landed
times:

| UTC | what | landed in |
|---|---|---|
| 02:00 | OAI-PMH delta harvest | E11_S02 (`ops/systemd/arxmcp-delta.timer`) |
| 02:30 | drift watchdog eval | E11_S04 (`ops/cron/arxmcp-watchdog.sh`) |
| 03:30 | restic backup | E11_S05 (`ops/systemd/arxmcp-backup.timer`) |
| 05:00 | daily metrics report | E14_S04 (NEW) |
| Sun 06:00 | parser-failures weekly review | E14_S04 (NEW) |
| Daily (short-circuit) | quarterly drill reminder | E14_S04 (NEW) |

The doc notes the divergence from note 08's aspirational table
in a sidebar.

### D6. systemd unit shapes — explicit UTC, Persistent=true

Timer template (mirrors `ops/systemd/arxmcp-delta.timer`):

```ini
[Unit]
Description=arXMCP daily ops metrics report — 05:00 UTC
Documentation=https://github.com/chris-dare/arXMCP/blob/main/docs/ops/daily-ops-cadence.md

[Timer]
OnCalendar=*-*-* 05:00:00 UTC
Persistent=true
Unit=arxmcp-daily-report.service
RandomizedDelaySec=120

[Install]
WantedBy=timers.target
```

`Persistent=true` is **load-bearing** — fires on next boot if the
host was down at the scheduled time. The `UTC` token on
`OnCalendar=` is essential (host-local-timezone is the default).

Service template includes the project's hardening trio: `ProtectSystem=strict`,
`ProtectHome=true`, `ReadWritePaths=/opt/arxmcp/var`,
`NoNewPrivileges=true`, `PrivateTmp=true`. Mirror
`ops/systemd/arxmcp-delta.service` verbatim.

### D7. Cron wrapper skeleton — copy from `ops/cron/arxmcp-delta.sh`

Every wrapper uses the same shape:

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

# flock(1) preflight (macOS warning).
command -v flock >/dev/null || {
  echo "ERROR: flock(1) not on PATH; install util-linux" >&2
  exit 1
}

LOCKFILE="${REPO_ROOT}/var/arxmcp/ops/.daily-report.lock"
mkdir -p "$(dirname "${LOCKFILE}")"

UV_BIN="${ARXMCP_UV:-/Users/chris.dare/Library/Python/3.9/bin/uv}"

exec flock -n "${LOCKFILE}" "${UV_BIN}" run python \
  tools/daily_metrics_report.py "$@"
```

### D8. Email opt-in — stdlib smtplib

Send only when ALL of `MAIL_TO`, `MAIL_FROM`, `SMTP_HOST` are
set. Log one INFO line either way (enabled or disabled with
missing-var list). STARTTLS opt-in via `SMTP_STARTTLS=1`, SMTP
auth opt-in via `SMTP_USER` + `SMTP_PASS`. No SSL-on-connect
(port 465 / smtps).

### D9. `--dry-run` + `--fixture` contract

The daily-report script accepts:

- `--metrics-url URL` (default `http://127.0.0.1:7733/metrics`)
- `--fixture PATH` — read from file instead of `--metrics-url`
- `--dry-run` — print markdown to stdout, do not write file, do
  not email
- `--out-dir PATH` — defaults to
  `var/arxmcp/ops/daily-reports/`

Ship `tests/fixtures/metrics_sample.txt` — a saved `/metrics`
response capturing all 7 tools + cache families + sentinels. The
`--dry-run` test path reads this fixture and asserts every tool
name appears in the rendered markdown.

### D10. Quarterly drill — daily cron + script short-circuit

The cron runs `tools/quarterly_drill_reminder.sh` daily at 00:00
UTC. The script short-circuits unless the operator is within 7
days of the next quarter mark (Jan 1, Apr 1, Jul 1, Oct 1). When
in-range, the script writes
`var/arxmcp/ops/reminders/quarterly-drill-<YYYY-QN>.flag`
containing the runbook reference + the exact
`ops/restore_drill.sh` invocation.

`--dry-run` flag adds early `set -x` and skips the file write.

### D11. Makefile parity targets

Add to the `Makefile`:

```makefile
daily-report:
	$(PYTHON) -m tools.daily_metrics_report $(ARGS)

parser-failures-report:
	$(PYTHON) -m tools.parser_failures_report $(ARGS)
```

Mirror the existing `watchdog` block style. Update `make help`.

### D12. `parser-failure-review.md` — human triage workflow

The brief asks for a `docs/ops/parser-failure-review.md`. Content:

- Where reports land (`var/arxmcp/ops/reports/parser-failures-<YYYY>-W<NN>.md`)
- What each row means (parser stage, reason regex)
- Triage decision tree: arxiv-tarball-broken → skip; latexml-crash
  → file upstream issue; chunker-bug → write a fixture-based
  regression test and fix in `ingest/chunker.py`
- The two "must-act" thresholds: >5% of week's papers fail =>
  pause delta cron; >10 same-reason failures => upstream
  investigation

### D13. Alert thresholds in the daily-ops-cadence doc

The brief's "alert thresholds" section pulls from prior shipped
runbooks (not from note 08, which has none):

- `regression_pct > 10%` → quarantine flag set (drift-watchdog.md)
- `now() - arxmcp_backup_last_success_timestamp_seconds > 86400` →
  backup overdue (backup-restore.md)
- `arxmcp_eval_quarantine_active > 0` → cutover blocked
- `arxmcp_delta_timeout_active > 0` → delta exceeded budget
- P99 latency > 2.5s sustained 5 min → tier-3 cache miss surge
  (proposed; defer concrete alerting to E14_S09)
- Error rate > 1% sustained 5 min → handler-level bug
  (proposed; defer to E14_S09)

---

## 3. Forced cross-file changes

| File | Change | Decision |
|---|---|---|
| `tools/daily_metrics_report.py` (NEW) | ~150 LOC: Prometheus scrape, histogram_quantile, markdown render, optional email | D1, D3, D8, D9 |
| `tools/parser_failures_report.py` (NEW) | ~150 LOC: TSV + JSONL aggregation, ISO-week filter, top-N markdown | D2 |
| `tools/quarterly_drill_reminder.sh` (NEW) | ~50 LOC bash: date math, short-circuit, flag write, `--dry-run` | D10 |
| `ops/cron/arxmcp-daily-report.sh` (NEW) | wrapper per D7 | D1, D7 |
| `ops/cron/arxmcp-parser-failures-weekly.sh` (NEW) | wrapper per D7 | D1, D7 |
| `ops/cron/arxmcp-quarterly-drill.sh` (NEW) | wrapper invoking `tools/quarterly_drill_reminder.sh` | D1, D10 |
| `ops/cron/arxmcp-cron.cron` (NEW) | single crontab fragment with all three lines + UTC comments | D1 |
| `ops/systemd/arxmcp-daily-report.{service,timer}` (NEW) | 05:00 UTC | D6 |
| `ops/systemd/arxmcp-parser-failures-weekly.{service,timer}` (NEW) | Sun 06:00 UTC | D6 |
| `ops/systemd/arxmcp-quarterly-drill.{service,timer}` (NEW) | daily 00:00 UTC; script short-circuits | D6, D10 |
| `ops/systemd/arxmcp-watchdog.{service,timer}` (NEW) | E11_S04 parity fill, 02:30 UTC | finding 7 |
| `docs/ops/daily-ops-cadence.md` (NEW) | full schedule table, alert thresholds, escalation path | D5, D13 |
| `docs/ops/parser-failure-review.md` (NEW) | human triage workflow | D12 |
| `Makefile` | `daily-report` + `parser-failures-report` targets; update `make help` | D11 |
| `tests/fixtures/metrics_sample.txt` (NEW) | saved /metrics fixture for `--dry-run` | D9 |
| `tests/test_daily_metrics_report.py` (NEW) | dry-run + histogram_quantile + email-disabled tests | D9 |
| `tests/test_parser_failures_report.py` (NEW) | TSV + JSONL aggregation tests | D2 |
| `tests/test_quarterly_drill_reminder.py` (NEW) | bash --dry-run + date-math edge cases | D10 |
| `infra/README.md` (verify) | no changes needed; `ops/` is the convention | — |

---

## 4. Implementation order

1. `tests/fixtures/metrics_sample.txt` — saved `/metrics` capture
   from a local server run. Required by the test surface.
2. `tools/daily_metrics_report.py` + tests.
3. `tools/parser_failures_report.py` + tests.
4. `tools/quarterly_drill_reminder.sh` + tests.
5. `ops/cron/arxmcp-*.sh` wrappers (3 new).
6. `ops/cron/arxmcp-cron.cron` crontab fragment.
7. `ops/systemd/arxmcp-*.{service,timer}` unit pairs (4 new
   incl. watchdog parity fill).
8. `docs/ops/daily-ops-cadence.md` + `docs/ops/parser-failure-review.md`.
9. `Makefile` targets + `make help` update.
10. `make test`, `ruff check .`, manual `crontab -f
    ops/cron/arxmcp-cron.cron` syntax check.
11. Implementation-summary + feat commit.

---

## 5. Open questions resolved at synthesis time

All open questions from both briefs resolved. No user input
required. The implementer proceeds.

---

## 6. External writes required

**Zero beyond local `main` commits.**

- All file creates/edits per §3.
- 3 git commits (feat + rect + chore) per the project's pattern.
- `git push origin main` per user authorization (per-event).

No PyPI uploads, no GitHub-API calls, no infra mutation. The
cron + systemd files SHIP as artifacts; the operator enables
them per their host (the runbook documents both `crontab -l |
crontab -` and `systemctl enable --now arxmcp-daily-report.timer`).

---

## 7. Risk register (carry into Phase 3)

- **Brief drift documented in 3 places** — `infra/cron/` →
  `ops/cron/`, missing `parser_failures_report.py`, cadence
  reconciliation. Adversary may flag scope expansion; rationale
  in implementation-summary §"Drift from brief".
- **Note 08 cadence vs shipped reality.** The new runbook
  documents shipped times; out of scope to rewrite the note here
  but worth a follow-up.
- **Cache `tier` vs `layer` label drift.** Note 08 has it wrong;
  the runbook + script use `tier` to match reality.
- **Ingestion throughput metrics not yet emitted.** The daily
  report falls back to `delta-status.json` reads or "n/a"
  rendering.
- **`tools/parser_failures_report.py` author quality.** Net new
  script; tests must pin the TSV/JSONL parsing behavior tightly
  to avoid silent data loss.
- **Quarterly cron must run daily.** A "monthly first-week"
  pattern via `OnCalendar=*-01,04,07,10-* 00:00:00 UTC` would
  miss leap-quarter edge cases; daily run + Python date-math
  inside the script is the robust path.
- **systemd timer hardening trio** (`ProtectSystem=strict`,
  `ProtectHome=true`, `ReadWritePaths=...`) — copy verbatim from
  the existing units; do not deviate.
