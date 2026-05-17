# Daily ops cadence

The arXMCP server runs a fixed UTC ops schedule. Everything below
ships as a cron wrapper at `ops/cron/` and a systemd timer + service
pair at `ops/systemd/`. The systemd path is preferred on Linux; the
cron path is the macOS fallback and a no-systemd-environment
escape hatch.

## Schedule (UTC)

| UTC | What | Wrapper | Systemd unit | Runbook |
|---|---|---|---|---|
| 02:00 daily | OAI-PMH delta harvest | `ops/cron/arxmcp-delta.sh` | `arxmcp-delta.{timer,service}` | [delta-loop.md](delta-loop.md) |
| 02:30 daily | Drift watchdog (eval regression) | `ops/cron/arxmcp-watchdog.sh` | `arxmcp-watchdog.{timer,service}` | [drift-watchdog.md](drift-watchdog.md) |
| 03:30 daily | restic backup | `ops/cron/arxmcp-backup.sh` | `arxmcp-backup.{timer,service}` | [backup-restore.md](backup-restore.md) |
| **05:00 daily** | **Daily ops metrics report (E14_S04)** | `ops/cron/arxmcp-daily-report.sh` | `arxmcp-daily-report.{timer,service}` | this doc |
| **06:00 Sun** | **Weekly parser-failures review (E14_S04)** | `ops/cron/arxmcp-parser-failures-weekly.sh` | `arxmcp-parser-failures-weekly.{timer,service}` | [parser-failure-review.md](parser-failure-review.md) |
| **00:00 daily** | **Quarterly drill reminder (short-circuits unless within 7d of next quarter)** | `ops/cron/arxmcp-quarterly-drill.sh` | `arxmcp-quarterly-drill.{timer,service}` | [backup-restore.md](backup-restore.md) §Restore drill |

### Drift from `.claude/notes/08-security-observability-ops.md`

The note 08 cadence is aspirational:
`00:00 delta → 04:00 LanceDB write → 04:10 backup → 05:00 metrics report`.
The **shipped** times above were chosen during E11_S02 / E11_S04 /
E11_S05 implementation and are what production actually runs. The
note has documented drift; rewriting it is out of scope for E14_S04.

## Enabling the schedule

### systemd (Linux primary)

```bash
# After substituting /opt/arxmcp + arxmcp user/group inside the
# service units (see the comment block at the top of each .service):
sudo install -m 644 ops/systemd/arxmcp-*.timer   /etc/systemd/system/
sudo install -m 644 ops/systemd/arxmcp-*.service /etc/systemd/system/
sudo systemctl daemon-reload
for unit in delta watchdog backup daily-report \
            parser-failures-weekly quarterly-drill; do
    sudo systemctl enable --now arxmcp-${unit}.timer
done
sudo systemctl list-timers 'arxmcp-*'
```

`Persistent=true` is set on every timer so a missed firing (host
was down at the scheduled UTC slot) fires on next boot.

### cron (macOS / fallback)

```bash
# Inspect:
cat ops/cron/arxmcp-cron.cron

# Install (destructive — replaces the operator's crontab):
crontab ops/cron/arxmcp-cron.cron
crontab -l   # verify
```

The wrappers are pure-bash with `flock(1)` for reentrancy. On
macOS, install `flock` via `brew install flock` first.

## Daily metrics report (E14_S04)

`tools/daily_metrics_report.py` scrapes the running MCP server's
`/metrics` endpoint, parses the Prometheus exposition format, and
renders a markdown report at
`var/arxmcp/ops/daily-reports/<YYYY-MM-DD>.md`. Sections:

- Requests served (per-tool OK/error counts; overall error rate)
- Latency P50 / P95 / P99 per-tool (linear-interpolated histogram
  quantiles — bucket-walk would quantise P99 to 5.0s)
- Cache hit rates per tier (Tier 1 / 2 / 3)
- Embedder + reranker call counts
- Ingestion throughput (placeholder — the
  `arxmcp_ingest_papers_processed_total` family is named in note
  08 but no emitter exists yet)
- Sentinels (drift fixtures, eval quarantine, delta timeout, backup
  age)

### Email opt-in

Set ALL THREE of `MAIL_TO`, `MAIL_FROM`, `SMTP_HOST` in the
service environment (or `/etc/default/arxmcp`) to enable email
delivery. STARTTLS is opt-in via `SMTP_STARTTLS=1`; SMTP auth is
opt-in via `SMTP_USER` + `SMTP_PASS`. When any of the three
required vars is missing, the report writes to disk normally and
an INFO log records which var was missing.

#### Recommended secret-handling pattern (IS2 from E14_S04)

`SMTP_PASS` in a systemd unit file ends up world-readable at
`/etc/systemd/system/arxmcp-daily-report.service` (visible to
`systemctl cat` for any local user). Use a **mode-0640
drop-in** instead:

```ini
# /etc/systemd/system/arxmcp-daily-report.service.d/10-mail.conf
[Service]
EnvironmentFile=/etc/arxmcp/mail.env
```

```bash
# /etc/arxmcp/mail.env  (owner root:arxmcp, mode 0640)
MAIL_TO=ops@example.com
MAIL_FROM=arxmcp@example.com
SMTP_HOST=smtp.example.com
SMTP_USER=arxmcp-relay
SMTP_PASS=<secret>
SMTP_STARTTLS=1
```

```bash
sudo install -d -o root -g arxmcp -m 0750 /etc/arxmcp
sudo install -o root -g arxmcp -m 0640 /tmp/mail.env /etc/arxmcp/mail.env
sudo systemctl daemon-reload
sudo systemctl restart arxmcp-daily-report.timer
```

Loadability: `systemctl show arxmcp-daily-report.service
--property=Environment` will NOT echo the secrets back (systemd
masks `EnvironmentFile`-sourced vars in `systemctl show`
output), and `journalctl -u arxmcp-daily-report` only ever logs
"email enabled: sending to <MAIL_TO> via <SMTP_HOST>:..." — not
the password.

SMTP failures (refused recipient, auth refused, OSError before
handshake) are caught + logged at ERROR level by the
report tool; they do NOT propagate and turn the cron run into a
journalctl-failed unit. The on-disk report under
`var/arxmcp/ops/daily-reports/<date>.md` is the durable artifact
regardless of email outcome.

### Dry-run

```bash
uv run python -m tools.daily_metrics_report \
  --dry-run --fixture tests/fixtures/metrics_sample.txt
```

The fixture (`tests/fixtures/metrics_sample.txt`) is a saved
exposition response from a local server. The dry-run never hits
the network and never writes to disk.

## Alert thresholds

These thresholds are sourced from prior shipped runbooks
(drift-watchdog.md, backup-restore.md, E11_S04 watchdog config).
Grafana alerting rules implementing them ship in E14_S09.

| Threshold | Source | Action |
|---|---|---|
| `regression_pct > 10%` | drift-watchdog.md §4 | Quarantine flag set; cutover blocked |
| `now() - arxmcp_backup_last_success_timestamp_seconds > 86400` | backup-restore.md | Backup overdue — investigate cron failure |
| `arxmcp_eval_quarantine_active > 0` | E11_S04 watchdog | Cutover blocked; review eval report |
| `arxmcp_delta_timeout_active > 0` | E11_S02 delta loop | Delta exceeded 90-min budget |
| `arxmcp_latexml_drift_fixtures > 0` | E10_S04 | LaTeXML version drifted; re-render corpus |
| P99 latency > 2.5s sustained 5 min | proposed (E14_S04) | Tier-3 cache miss surge or BGE-M3 worker stall |
| Error rate > 1% sustained 5 min | proposed (E14_S04) | Handler-level bug; check journalctl |

## Escalation path

The project is single-operator (Chris Dare; see [OWNERS.md](../../OWNERS.md))
so there is no on-call rotation. The escalation path is:

1. Daily report + parser-failures report land in
   `var/arxmcp/ops/daily-reports/` and
   `var/arxmcp/ops/reports/` respectively. Operator reviews on
   the next business day.
2. Sentinel-set thresholds (quarantine, delta timeout, drift)
   fire as Prometheus gauges visible via `/metrics`. Grafana
   alerting (E14_S09) will turn these into email/Slack alerts;
   today they require the operator to inspect Phoenix / Grafana
   manually.
3. Restore drill (quarterly) is the disaster-recovery exercise;
   the reminder lands in `var/arxmcp/ops/reminders/` 7 days
   before the next quarter mark.

## See also

- [delta-loop.md](delta-loop.md) — E11_S02 cron + 90-min budget
- [drift-watchdog.md](drift-watchdog.md) — E11_S04 quarantine
- [backup-restore.md](backup-restore.md) — E11_S05 restic +
  restore drill
- [parser-failure-review.md](parser-failure-review.md) — weekly
  triage workflow
- [`.claude/notes/08-security-observability-ops.md`](../../.claude/notes/08-security-observability-ops.md)
  §Daily ops cadence — design rationale (with documented drift
  from shipped times)
