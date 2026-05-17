# E14_S05 — Research Brief 2 (external context + patterns)

**Scope:** external prior art, alerting/PromQL idioms, restic, hosted-embedder
fallback recipes. Researcher 1 owns the in-codebase deep dive; this brief
only touches the codebase for delta — where existing scaffolding lives so we
avoid duplication.

---

## 1. In-codebase context (LIGHT — delta only)

Things already shipped that this milestone must extend (not replace):

- **`ops/` is already the home for ops** (cron wrappers, systemd units,
  restic env template, restore drill). E11_S05 landed there. **Do NOT
  create `infra/restic/`.** Continue using `ops/`.
- **Existing sentinel pattern** lives in `ingest/oai_delta.py`
  (`var/arxmcp/ops/delta-timeout.flag`) and `ingest/re_embed.py`
  (`_write_progress_sentinel`). The watchdog quarantine flag in
  `tools/daily_metrics_report.py` reads
  `arxmcp_eval_quarantine_active` as a metric. Pattern: cron writes
  a file under `var/arxmcp/ops/`; the dependent cron `[ -e flag ] &&
  exit 0` early-exits.
- **Existing backup wrapper** (`ops/cron/arxmcp-backup.sh`) ALREADY runs
  `restic forget --prune --keep-daily 7 --keep-weekly 4 --keep-monthly
  12` and emits a `backup-status.json`. E14_S05 does NOT re-author it;
  it adds the restore drill measurement (`ops/restore_drill.sh` exists
  too).
- **Metrics module:** `server/observability/metrics.py` is the right
  home for `arxmcp_disk_free_bytes`. `tools/daily_metrics_report.py`
  reads via `prometheus_client.parser.text_string_to_metric_families`
  — use the same idiom.
- **`/readyz`** already reports `warm` per resource; degraded-mode
  surfacing needs a new `degraded` block + `reason` field
  (`server/health.py`).
- **No `voyage` code exists yet.** `ARXMCP_QUERY_EMBED_PROVIDER` is
  referenced ONLY in the roadmap / notes. The "hosted embedder
  fallback" milestone must either (a) add the entire hosted path + the
  fallback, or (b) gate the fallback behind a feature flag and
  implement only the fall-through logic. **Recommend (b)** — see open
  question 2.

---

## 2. External context (the bulk)

### 2.1 `promtool check rules` — what it validates

`promtool` is the Go binary shipped with Prometheus. `check rules
<file>` parses the file and validates:

- Top-level must be `groups: [ <RuleGroup> ]`.
- Each `RuleGroup` has `name: <string>`, optional `interval:
  <duration>`, and `rules: [<Rule>]`.
- Each `Rule` is either an alerting rule (`alert: <name>`) or a
  recording rule (`record: <name>`). For alerts:
  - `alert: <UpperCamelCase string>` (convention; not enforced).
  - `expr: <PromQL>` — promtool runs the PromQL parser. Type
    must be `instant vector`.
  - `for: <duration>` — must be a Go duration (`5m`, `1h`).
  - `labels: {severity: page|warn|info, ...}` — string→string.
  - `annotations: {summary, description, runbook_url}` — go-template
    rendered against `$labels` / `$value`, but promtool only
    validates that the template parses, not that the labels exist.

**Exit codes:** 0 on valid; non-zero on syntax / PromQL parse / type
errors. Skipping promtool if not on PATH is the same pattern E14_S04
uses for `crontab -T` — test asserts file shape with PyYAML and only
shells out to promtool when present.

Citing the Prometheus docs (alerting rules page): *"alert: The name
of the alert. expr: The PromQL expression to evaluate. for: How long
before alert state transitions to firing."* Standard label is
`severity: critical | warning | info`.

### 2.2 PromQL for the disk-full alert

The canonical node-exporter expression is:

```promql
node_filesystem_avail_bytes{mountpoint="/var/lib/arxmcp"} < 10737418240
```

But **arXMCP does not deploy node_exporter** — only the server's
own `/metrics`. Three options:

(a) Ship the rule against node_exporter as a documented assumption
    ("requires node_exporter on the host").
(b) **Emit `arxmcp_disk_free_bytes{path="<data-dir>"}` from the server
    itself** via `shutil.disk_usage()` refreshed at scrape time.
(c) Cron job that calls `df` and writes the sentinel directly, bypassing
    Prometheus.

**Recommend (b).** Reasons:

- Pure-Python stdlib (`shutil.disk_usage(path) → (total, used, free)`),
  ~10 LOC. Avoid `os.statvfs` (POSIX-only, breaks Windows dev).
- Server-owned metric, no second daemon to deploy.
- Already in the prometheus_client process registry — `promtool check
  metrics` already covers it indirectly via the smoke test.
- Daily report at `tools/daily_metrics_report.py` can read it via
  the same `_sentinel_gauge` helper.

Rule then becomes (clean and exporter-agnostic):

```promql
arxmcp_disk_free_bytes < 10737418240
```

Use a Prometheus **Gauge** (not Counter), refreshed via a
`prometheus_client.Gauge.set_function(...)` callback so the value
recomputes at every scrape without a background thread.

### 2.3 The disk-pause sentinel — pattern + wiring

File path: **`var/arxmcp/ops/ingest-paused`** (matches the brief and
the existing `delta-timeout.flag` neighbor). Body: JSON with `{reason,
free_bytes, threshold_bytes, written_at}` so the daily report can
surface the cause.

Cron-side check pattern (matches `ops/cron/arxmcp-delta.sh` style):

```bash
PAUSE_FLAG="${ARXMCP_DATA_DIR:-/var/lib/arxmcp}/ops/ingest-paused"
if [ -e "$PAUSE_FLAG" ]; then
    echo "ingest paused: $(cat $PAUSE_FLAG)" >&2
    exit 0
fi
```

**Self-clearing vs operator-clearing**: recommend **self-clearing**.
The same scrape-time hook that writes the flag at <10 GB should
delete it once free space exceeds a hysteresis band (e.g. 15 GB —
don't toggle at the exact threshold). This is the same pattern
`ingest/oai_delta.py` uses: "Clear any stale budget-breach sentinel
BEFORE early-returning."

### 2.4 LanceDB corruption recovery

LanceDB's Python SDK does **not** expose a documented "corruption
detected" exception. Empirically:

- `lancedb.connect(uri)` is cheap (no metadata read). It does NOT fail
  on a corrupt dataset.
- `db.open_table("chunks")` reads the manifest. A corrupt manifest
  raises `lance.LanceError` (or `OSError` on a truncated fragment).
- A specific version checkout (`tbl.checkout(v)`) reads that
  manifest snapshot; if `v` is intact but `latest` is corrupt,
  checkout works. The corpus-version-1 fallback exploits exactly
  this.

**Recommended detection contract:** wrap the existing `open_chunks_table`
call in `server/corpus.py` with a try/except around
`(lance.LanceError, OSError, RuntimeError, ValueError)` — broad on
purpose, because corruption surfaces unpredictably. On exception:

1. Read `corpus_version_marker` for current `v`.
2. Attempt `checkout(v - 1)`.
3. If that succeeds, set a process-level
   `degraded = True; reason = "corpus_corruption"; fallback_version
   = v - 1` and log WARN.
4. If THAT also fails, the lifespan handler keeps `/readyz` at 503
   with `reason="corpus_corruption_unrecoverable"`.

**Synthetic corruption test** (acceptance criterion): truncate
`_versions/<v>.manifest` to zero bytes in a tmpdir LanceDB and assert
that `open_chunks_table(...)` returns the `v-1` table + the `degraded`
flag is set. The chunks table writes its manifest as
`<base>/_transactions/<txn>.txn` — truncating a single recent
manifest reliably triggers the failure path.

### 2.5 Restic retention syntax — confirm

From the restic docs (`restic forget` page):

> `--keep-daily n` — for the last n days which have one or more
> snapshots, keep only the most recent one for each day.
> `--keep-weekly n` — for the last n weeks (ISO weeks)...
> `--keep-monthly n` — for the last n months (calendar months)...
> Use `--prune` to actually delete data referenced by no remaining
> snapshot. Without `--prune`, forget only un-tags.

The existing wrapper at `ops/cron/arxmcp-backup.sh:133-136` already
uses the recommended `--keep-daily 7 --keep-weekly 4 --keep-monthly 12`
(7 days + 4 weeks + 12 months ≈ 12 months of recovery points, ~23
snapshots active). **No change needed.**

For E14_S05's restore-drill measurement: `restic restore latest
--target /tmp/restore-drill-<date>` followed by `restic check` (which
verifies pack files + tree integrity) + a file-count assertion. The
drill should measure (a) wall-clock restore time, (b) verify exit
code, (c) sample-file SHA match against a reference list. Existing
`ops/restore_drill.sh` is the scaffold.

### 2.6 Hosted-embedder fallback recipes (Voyage AI)

Voyage AI API observed failure modes:

- `429 Too Many Requests` — rate-limit. `Retry-After` header.
- `401 Unauthorized` — bad/missing key.
- `5xx` — transient. Voyage status page documents occasional
  multi-minute incidents.
- `httpx.TimeoutException` — slow connection, common on the API gateway.

**Fallback policy (opinionated):**

- One retry with jittered backoff (250 ms ± 100 ms) on
  `(429, 5xx, TimeoutException)`. Skip retry on `401/403` — these
  won't fix themselves.
- If the retry also fails, **fall back to local BGE-M3** and tag the
  result with `degraded=true` + `reason="hosted_embedder_outage"`.
- Emit ONE WARN log per process (use a module-level
  `_FALLBACK_LOGGED = False` flag) — avoid log spam on sustained
  outages. The metric `arxmcp_hosted_embed_fallback_total{provider}`
  Counter is the operator-facing observable.

---

## 3. Concrete shapes (recommendations)

### `server/corpus.py` corruption fallback (~25 LOC)

```python
def open_chunks_table_with_fallback(db, marker_path):
    v = read_corpus_version(marker_path).corpus_version
    for attempt_v in (v, v - 1):
        if attempt_v < 1:
            break
        try:
            tbl = db.open_table("chunks")
            if attempt_v != v:
                tbl = tbl.checkout(attempt_v)
            return tbl, _Degraded(active=(attempt_v != v),
                                   reason="corpus_corruption" if attempt_v != v else None,
                                   fallback_version=attempt_v)
        except (lance.LanceError, OSError, RuntimeError, ValueError) as e:
            logger.warning("corpus_open_failed v=%d: %s", attempt_v, e)
    raise RuntimeError("corpus_corruption_unrecoverable")
```

### `infra/prometheus/alerts.yml` (~35 LOC YAML)

```yaml
groups:
  - name: arxmcp
    interval: 30s
    rules:
      - alert: ArXMCPDiskFull
        expr: arxmcp_disk_free_bytes < 10737418240
        for: 5m
        labels: {severity: critical, component: storage}
        annotations:
          summary: "arXMCP free disk space < 10 GB"
          description: "free={{ $value }} bytes on {{ $labels.path }}"
          runbook_url: "docs/ops/failure-modes.md#disk-full"
      - alert: ArXMCPDegradedMode
        expr: arxmcp_degraded_mode_active == 1
        for: 1m
        labels: {severity: warning, component: server}
        annotations:
          summary: "arXMCP running degraded ({{ $labels.reason }})"
          runbook_url: "docs/ops/failure-modes.md#degraded-modes"
      - alert: ArXMCPBackupStale
        expr: (time() - arxmcp_backup_last_success_timestamp_seconds) > 172800
        for: 10m
        labels: {severity: warning, component: backup}
        annotations:
          summary: "no successful restic backup in > 48h"
          runbook_url: "docs/ops/backup-restore.md"
```

### `tools/ingest_sentinel.py` (~50 LOC)

CLI: `write_pause(reason, free_bytes)`, `clear_pause()`, `is_paused()
-> dict | None`. Same shape as `_write_progress_sentinel` in
`ingest/re_embed.py`. Importable from `server/observability/metrics.py`'s
disk-free scrape hook AND from cron-side `arxmcp-delta.sh`.

### Disk-free metric (~15 LOC in `server/observability/metrics.py`)

```python
DISK_FREE_BYTES = Gauge("arxmcp_disk_free_bytes",
                        "Free bytes on the arXMCP data filesystem",
                        labelnames=["path"])

def _refresh_disk_free():
    path = os.environ.get("ARXMCP_DATA_DIR", "/var/lib/arxmcp")
    try:
        usage = shutil.disk_usage(path)
        DISK_FREE_BYTES.labels(path=path).set(usage.free)
        if usage.free < 10 * 1024**3:
            ingest_sentinel.write_pause("disk_low", usage.free)
        elif usage.free > 15 * 1024**3:
            ingest_sentinel.clear_pause()
    except OSError as e:
        logger.warning("disk_free_refresh_failed: %s", e)
```

Wire via `Gauge.set_function(...)` from `server/main.py` lifespan so
it ticks at every Prometheus scrape (~15 s default).

### `docs/ops/failure-modes.md` table layout

| # | Failure mode | Detection | Recovery | Surfaces as |
|---|---|---|---|---|
| 1 | LanceDB manifest corruption | `LanceError` on open | Checkout `v-1` | `/readyz` 503 → 200 degraded |
| 2 | Reranker cold start | First-call latency >10 s | Dummy inference in lifespan | `/readyz` blocked until warm |
| 3 | Disk-full | `arxmcp_disk_free_bytes < 10 GB` | `ingest-paused` sentinel | `ArXMCPDiskFull` alert |
| 4 | Hosted embedder outage | HTTP 4xx/5xx, timeout | Fall back to BGE-M3 | `degraded=true` in result |
| 5 | Restic backup failure | Non-zero exit / stale ts | Operator restart | `ArXMCPBackupStale` alert |
| 6 | Restore-drill failure | Quarterly drill | Rotate to alt repo | Drill log |
| 7 | OAI-PMH outage | Delta cron error rate | Skip day; resume next | Delta metrics |
| 8 | BGE model load fail | Lifespan exception | Process exit, restart | `/readyz` never opens |

---

## 4. Open questions

1. **node_exporter vs server-emitted disk metric?** Recommend
   **server-emitted** (`arxmcp_disk_free_bytes`). Avoids a second
   daemon, reuses the existing `/metrics` endpoint, and keeps the
   alert expression exporter-agnostic.

2. **Voyage path scope — full add or fallback-only?** The roadmap
   describes `ARXMCP_QUERY_EMBED_PROVIDER=voyage` as if it exists,
   but no code does. Recommend **fallback-only contract** for
   E14_S05: ship a `HostedEmbedder` protocol + a stub
   `VoyageEmbedder` raising `NotImplementedError`, plus the
   fall-through wrapper that catches any exception and routes to
   BGE-M3 with `degraded=true`. Full Voyage integration becomes a
   separate ticket (E14_S05b or fold into E08). API key handling:
   `ARXMCP_VOYAGE_API_KEY` env var, read once at lifespan, masked in
   `/healthz`.

3. **`infra/restic/` vs `ops/restic/` — duplicate or stay put?**
   E11_S05 already shipped restic under `ops/`. **Recommend: do NOT
   duplicate.** The brief's `infra/prometheus/alerts.yml` is a new
   path (no existing equivalent), but restic stays at `ops/`.
   `infra/` becomes the "non-runtime declarative config" dir
   (Prometheus rules, future docker-compose); `ops/` stays the
   "imperative wrappers + systemd units" dir.

---

## 5. External writes the implementation will require

- **`pyproject.toml` deps:** none new. `prometheus_client` and
  `lancedb` already pinned. `shutil` is stdlib.
- **`promtool` binary** is OPTIONAL — tests assert YAML shape with
  PyYAML and gracefully skip the `promtool check rules` shell-out
  when not on PATH (same defer pattern as `crontab -T` in E14_S04).
  Doc the install path (`brew install prometheus` on macOS) in
  `docs/ops/failure-modes.md`.
- **`restic`** is OPTIONAL for tests — `tests/test_backup_wrapper.py`
  is already file-content-only (no live restic). The restore drill
  needs restic on the test runner; mark it `@pytest.mark.requires_restic`
  and skip by default.
- **No external file mutations** beyond writing the new files: the
  metric module change, the corpus fallback, the alert YAML, the
  sentinel CLI, the docs page.
