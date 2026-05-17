# E14_S04 Research Brief 2 — External Context + Patterns

**Scope:** external sources, cron/systemd conventions, Prometheus client-side
scraping, smtplib, and concrete file shapes. Researcher 1 covers the
in-codebase landscape; this brief stays light on internals and quotes
load-bearing details for the implementer.

---

## 1. In-codebase reality check (LIGHT)

Three corrections to the milestone brief that the implementer **must
not miss**:

- **Path drift.** The brief says `infra/cron/`. The actual project
  convention (E11_S02 / E11_S04) is **`ops/cron/` for wrappers and
  `ops/systemd/` for units.** Two unit pairs already exist:
  `ops/systemd/arxmcp-delta.{service,timer}`,
  `ops/systemd/arxmcp-backup.{service,timer}`. Following the existing
  layout is mandatory; treat `infra/cron/` in the brief as a typo.
- **Docs path drift.** Brief says `docs/ops/daily-ops-cadence.md`; this
  fits the existing `docs/ops/*.md` runbook directory (already has
  `delta-loop.md`, `drift-watchdog.md`, `backup-restore.md`, etc.). Land
  there.
- **`tabulate` is NOT a dependency.** `pyproject.toml` declares only
  `prometheus-client>=0.20` from the relevant set. F-string pipe tables
  are sufficient; don't add a dep.

No existing `daily_metrics_report.py` or `quarterly_drill_reminder.sh`;
no overlapping module. Greenfield within `tools/`.

The existing `ops/cron/arxmcp-delta.sh` is the canonical wrapper pattern
to copy: shebang, `set -euo pipefail`, `SCRIPT_DIR`/`REPO_ROOT` derived
from `BASH_SOURCE`, `flock -n` on a `var/arxmcp/ops/.<name>.lock` path,
explicit `flock(1)` availability check (macOS warning included), `uv run`
invocation, `exec`'d at the tail. Copy this skeleton verbatim.

---

## 2. Prometheus exposition parsing (client-side)

`prometheus-client>=0.20` ships
`prometheus_client.parser.text_string_to_metric_families`. Pattern:

```python
import urllib.request
from prometheus_client.parser import text_string_to_metric_families

raw = urllib.request.urlopen("http://127.0.0.1:7733/metrics",
                             timeout=5).read().decode("utf-8")
for fam in text_string_to_metric_families(raw):
    # fam.name, fam.type ∈ {"counter","gauge","histogram",…}
    for sample in fam.samples:
        # sample.name, sample.labels, sample.value
        ...
```

For histograms, `text_string_to_metric_families` synthesises three
sample names per family: `<name>_bucket` (with `le` label),
`<name>_count`, `<name>_sum`. So latency for `arxmcp_request_latency_seconds`
arrives as one family whose samples are the cumulative bucket counts per
`(tool, le)` plus per-tool `_count` and `_sum`.

### Client-side `histogram_quantile`

Prometheus's algorithm (linearly interpolated within the bucket containing
the quantile):

```python
def histogram_quantile(q: float, buckets: list[tuple[float, float]]) -> float:
    """buckets = sorted [(le, cumulative_count), …]; +Inf bucket required."""
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
                return prev_le  # cannot interpolate past +Inf
            if prev_count == count:
                return prev_le
            return prev_le + (le - prev_le) * (rank - prev_count) / (count - prev_count)
        prev_le, prev_count = le, count
    return buckets[-1][0]
```

This matches Prometheus's `histogram_quantile()` exactly per
`promql/quantile.go` (linear interpolation inside the matching bucket,
clamp at the highest finite `le` for the `+Inf` overflow case).
**Recommendation:** ship this — bucket-walk-only would be lazy and the
report's P99 would be quantised to bucket edges (e.g. 5.0s ceiling).

`server/observability/metrics.py` declares buckets
`(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)` so
sub-millisecond cache hits don't underflow. The report's per-tool
latency table iterates the seven registered tools
(`search_papers`, `get_chunk`, `find_equation`, `get_definitions`,
`find_lemma_by_name`, `get_paper`, `cite_neighbors`).

---

## 3. Cron syntax — 6 vs 5 fields

The brief says "6-field format (m h dom mon dow command)" — that's a
**slip**. Standard cron is **5 time fields + command** (`m h dom mon dow
command`). Six-field cron is the Quartz/systemd variant with seconds.
For `crontab(5)` on Linux/macOS, write 5 fields.

`crontab -l | crontab -` does light syntax validation (it rejects
malformed lines) but doesn't lint semantics. Pair the cron fragments
with a comment header explaining the UTC slot.

Canonical fragment for 05:00 UTC:

```cron
# arXMCP daily metrics report — runs at 05:00 UTC.
# After delta (00:00 UTC) and drift watchdog (04:30 UTC) so the
# report reflects the most recent overnight cycle.
0 5 * * * /opt/arxmcp/ops/cron/arxmcp-daily-report.sh >/dev/null 2>&1
```

`flock` wrapping must live **inside** the wrapper, not in the cron line,
to match the `arxmcp-delta.sh` precedent. The cron line itself stays
minimal — easier to audit by `crontab -l`.

---

## 4. systemd timer + service pair (canonical)

Timer files alone are not executable. The idiomatic split is
`name.timer` (scheduling) + `name.service` (the actual `ExecStart=`).
The brief's wording ("`.timer` systemd unit files") is shorthand;
**ship the pair.**

Timer template (mirrors `arxmcp-delta.timer`):

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

`Persistent=true` is **load-bearing** — if the host was down at 05:00,
the timer fires on next boot. `OnCalendar=*-*-* 05:00:00 UTC` is the
explicit-UTC form; `man systemd.time` confirms the trailing `UTC` token
overrides the host's local timezone. `RandomizedDelaySec=120` mirrors
the existing pattern.

Service template:

```ini
[Unit]
Description=arXMCP daily metrics report (generates daily-reports/<date>.md)
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/opt/arxmcp
User=arxmcp
Group=arxmcp
ExecStart=/opt/arxmcp/ops/cron/arxmcp-daily-report.sh
StandardOutput=journal
StandardError=journal
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/arxmcp/var
NoNewPrivileges=true
PrivateTmp=true
TimeoutStartSec=600

[Install]
WantedBy=multi-user.target
```

Include the same operator-substitution comment block (`/opt/arxmcp` +
`arxmcp` user) as `arxmcp-delta.service`.

Weekly parser-failures (Sunday 06:00 UTC) uses
`OnCalendar=Sun *-*-* 06:00:00 UTC`. Quarterly drill: `OnCalendar=*-01,04,07,10-* 00:00:00 UTC`
fires daily during the first week of each quarter — the
`quarterly_drill_reminder.sh` short-circuits unless we're within 7 days
of a quarter boundary.

---

## 5. stdlib `smtplib` for optional email

Opt-in contract: send only when **all three** of `MAIL_TO`, `MAIL_FROM`,
`SMTP_HOST` are set. If any is missing, log one `INFO` line ("email
delivery disabled: $missing unset") and continue. Quiet absence is
correct here — the report file on disk is the durable artifact.

```python
import os, smtplib
from email.message import EmailMessage

def maybe_email(subject: str, body: str) -> None:
    cfg = {k: os.environ.get(k) for k in ("MAIL_TO","MAIL_FROM","SMTP_HOST")}
    if not all(cfg.values()):
        log.info("email disabled: missing %s",
                 ",".join(k for k,v in cfg.items() if not v))
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = cfg["MAIL_FROM"], cfg["MAIL_TO"], subject
    msg.set_content(body)
    with smtplib.SMTP(cfg["SMTP_HOST"], int(os.environ.get("SMTP_PORT","25")),
                       timeout=10) as s:
        if os.environ.get("SMTP_STARTTLS") == "1":
            s.starttls()
        if os.environ.get("SMTP_USER"):
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        s.send_message(msg)
```

Default cleartext on port 25 for trusted LAN relays; `SMTP_STARTTLS=1`
opt-in. No SSL-on-connect (port 465) — STARTTLS is the modern path.

---

## 6. Recommended file shapes

### `tools/daily_metrics_report.py` (~60–80 LOC)

```python
#!/usr/bin/env python3
"""Daily ops metrics report. Reads /metrics, writes markdown."""
import argparse, datetime, logging, pathlib, sys, urllib.request
from prometheus_client.parser import text_string_to_metric_families

TOOLS = ("search_papers","get_chunk","find_equation","get_definitions",
         "find_lemma_by_name","get_paper","cite_neighbors")
CACHE_TIERS = (1, 2, 3)
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

def fetch_metrics(url, fixture=None) -> str:
    if fixture: return pathlib.Path(fixture).read_text()
    return urllib.request.urlopen(url, timeout=5).read().decode()

def histogram_quantile(q, buckets): ...  # §2

def render(metrics_text, now) -> str:
    fams = {f.name: f for f in text_string_to_metric_families(metrics_text)}
    # request totals, latency P50/P95/P99 per tool, cache hits per tier, …
    return "\n".join(["# arXMCP daily ops report", f"_Generated {now.isoformat()}Z_", …])

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--metrics-url", default="http://127.0.0.1:7733/metrics")
    p.add_argument("--fixture")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--out-dir",
                   default=str(REPO_ROOT / "var/arxmcp/ops/daily-reports"))
    args = p.parse_args()
    now = datetime.datetime.now(datetime.UTC)
    md = render(fetch_metrics(args.metrics_url, args.fixture), now)
    if args.dry_run:
        sys.stdout.write(md); return
    out = pathlib.Path(args.out_dir) / f"{now.date().isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)
    maybe_email(f"arXMCP {now.date()} report", md)
```

Acceptance: `--dry-run` reads from `--fixture` (a saved `/metrics`
response under `tests/fixtures/metrics_sample.txt`), prints to stdout,
never hits the network, never writes a file. Tests pin the fixture and
assert all seven tool names appear under the latency section.

### `ops/cron/arxmcp-daily-report.cron`

```cron
0 5 * * * /opt/arxmcp/ops/cron/arxmcp-daily-report.sh
0 6 * * 0 /opt/arxmcp/ops/cron/arxmcp-parser-failures-weekly.sh
0 0 * * * /opt/arxmcp/ops/cron/arxmcp-quarterly-drill.sh
```

### `ops/cron/arxmcp-daily-report.sh` (~40 LOC)

Identical skeleton to `arxmcp-delta.sh`: `SCRIPT_DIR` → `REPO_ROOT` →
`flock(1)` check → `flock -n var/arxmcp/ops/.daily-report.lock` →
`exec uv run python tools/daily_metrics_report.py`.

### `ops/cron/arxmcp-quarterly-drill.sh` (~30 LOC)

Quarterly maths via stdlib:

```bash
#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

today_epoch=$(date -u +%s)
year=$(date -u +%Y); month=$(date -u +%m)
case "${month}" in
  01|02|03) next_q="${year}-04-01" ;;
  04|05|06) next_q="${year}-07-01" ;;
  07|08|09) next_q="${year}-10-01" ;;
  10|11|12) next_q="$((year+1))-01-01" ;;
esac
# GNU date vs BSD date: prefer python for portability
days_to_next=$(python3 -c "from datetime import date,datetime,UTC; \
  d=date.fromisoformat('${next_q}'); \
  print((d - datetime.now(UTC).date()).days)")

if [ "${days_to_next}" -le 7 ] && [ "${days_to_next}" -ge 0 ]; then
    REMINDER="${REPO_ROOT}/var/arxmcp/ops/restore-drill-reminder-${next_q}.flag"
    mkdir -p "$(dirname "${REMINDER}")"
    [ -f "${REMINDER}" ] || cat > "${REMINDER}" <<EOF
Restore drill due by ${next_q} (T-${days_to_next}d).
Runbook: docs/ops/backup-restore.md §Restore drill.
EOF
fi
```

`--dry-run` flag adds an early `set -x` and skips the file write to
satisfy the acceptance criterion.

---

## 7. Open questions

1. **`.service` files alongside `.timer` files?** Yes — required for the
   pair to function. The brief lists only `.timer` which is shorthand;
   the implementer should ship both files per the existing
   `arxmcp-delta` / `arxmcp-backup` precedent. **Recommendation: ship the
   pair, document explicitly in the milestone summary.**
2. **`tabulate` dep?** No. F-string pipe tables are sufficient; adding
   a dep for one report is not worth the supply-chain delta. **Stick
   to stdlib.**
3. **Histogram-quantile algorithm?** Linear interpolation per
   Prometheus's `promql/quantile.go`. Pure bucket-walk would quantise
   P99 to bucket edges (5.0s ceiling = useless). **Linear interp.**
4. **Email opt-in logging?** Log one `INFO` listing the missing env
   vars when disabled; one `INFO` ("sending report to MAIL_TO") when
   enabled. Quiet absence is wrong — operators need to see why their
   email never arrives.

---

## 8. External writes the implementation requires

- `pyproject.toml`: **no edits.** All deps available
  (`prometheus-client`, stdlib `smtplib`/`email.message`/`datetime`/
  `urllib.request`/`argparse`/`pathlib`).
- File creation only — no edits to `server/` or `ingest/`.
- One-time creation of `var/arxmcp/ops/daily-reports/` (gitignored;
  parent `var/arxmcp/ops/` already exists from E11_S04).
- Outbound network: only when `--metrics-url` actually fetches; `--dry-run`
  with `--fixture` is fully offline (test path).
