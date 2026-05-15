# arXMCP cron jobs (internal registry)

Single-source list of automated jobs the project runs. Agent-internal
— operators see `docs/ops/` for procedure runbooks; this file is the
**registry of WHICH jobs exist + their cadence + entry points**.

## Active jobs

### `latexml-drift-check` (E10_S04)

| Field | Value |
|---|---|
| **Entry point** | `ops/cron/latexml-drift-check.sh` |
| **Python module** | `ops/drift_check.py` |
| **Suggested cadence** | Daily, 02:30 UTC |
| **Runtime** | ~5s wall time (5 fixtures × < 1s `latexmlc` each, plus BS4 parse) |
| **Counter** | `arxmcp_latexml_drift_detected_total` (in `server/metrics.py`) |
| **Sentinel** | `var/arxmcp/ops/drift-detected.flag` |
| **Runbook** | `docs/ops/latexml-drift-runbook.md` |
| **Fixtures** | `tests/fixtures/latexml-drift/*.{tex,expected.mathml}` |

**Purpose.** Detect when the operator's LaTeXML version produces
different MathML byte-for-byte vs the checked-in baselines —
silently corrupting the equation TED index built by E10_S03.

**Operator signal on drift.** Cron mailer / systemd-timer logs
catch the non-zero exit; sentinel file pings any external monitor
watching the directory. The Prometheus counter increment is
**in-process to the cron's lifetime** at v1; production
``/metrics`` exposure of the counter is deferred to E14.

**Crontab fragment:**

```
30 2 * * *  /path/to/arxmcp/ops/cron/latexml-drift-check.sh
```

**systemd-timer fragment** (alternative):

```ini
# /etc/systemd/system/arxmcp-latexml-drift.timer
[Unit]
Description=Daily LaTeXML drift check (arXMCP E10_S04)

[Timer]
OnCalendar=*-*-* 02:30:00
Persistent=true

[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/arxmcp-latexml-drift.service
[Unit]
Description=arXMCP LaTeXML drift check

[Service]
Type=oneshot
ExecStart=/path/to/arxmcp/ops/cron/latexml-drift-check.sh
User=arxmcp
```

## Future jobs

E14 (observability/ops) will add additional scheduled tasks:

* corpus-version drift watchdog (Tier-1 → Tier-2 transition gate)
* nDCG@5 regression alert
* daily `restic` backup of `var/arxmcp/`
* `OAI-PMH` delta poll for incremental ingest

Each gets a row in this table when it lands.

## Conventions

* All cron jobs are bash entry points under `ops/cron/`.
* All logic lives in a Python module under `ops/`.
* Counters live in `server/metrics.py` with the
  `arxmcp_<subsystem>_<action>_total` naming convention; production
  exposure via `/metrics` deferred to E14 in most cases.
* Sentinel files live under `var/arxmcp/ops/`.
* Runbooks for operator-facing procedures live under `docs/ops/`
  and are linked from the root README's Operations section.
