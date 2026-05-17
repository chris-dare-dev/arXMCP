# E14_S05 — Research synthesis (orchestrator-merged)

**Sources:** [research-brief-1.md](research-brief-1.md) (in-codebase,
106 LOC) + [research-brief-2.md](research-brief-2.md) (external +
patterns, 361 LOC). Both researchers converged on the load-bearing
decisions; the milestone has significant scope overlap with E11_S05
(restic backup) which is documented in detail below.

---

## 1. Headline findings

1. **E11_S05 already shipped the entire restic surface.** Both
   researchers independently confirmed: `ops/cron/arxmcp-backup.sh`,
   `ops/restic-env.sh.template`, `ops/systemd/arxmcp-backup.{service,
   timer}`, `ops/restore_drill.sh`, `ops/restore_drill_check.py`,
   `docs/ops/backup-restore.md` all exist and cover everything the
   E14_S05 brief asks `infra/restic/nightly.sh` to provide. The brief's
   `infra/restic/` references are out-of-date.
2. **The brief says 8 failure modes; the note has 9.** Note 08's
   table at §"Failure modes and graceful degradation" lists 9 rows:
   (1) hosted-embedder outage, (2) LanceDB corruption, (3) MCP OOM,
   (4) reranker cold start, (5) LaTeXML hang, (6) singleflight
   deadlock (defensive), (7) disk full, (8) OAI-PMH 503,
   (9) arxiv.org per-paper 503. The runbook covers all 9.
3. **E07_S07 was never shipped.** Brief asserts the reranker warm-up
   was "already shipped" in E07_S07; E07 stops at S04. The reranker
   model IS loaded at startup (`_load_reranker_or_raise`), but no
   *dummy inference* exists. Authoring it is in-scope here.
4. **`ARXMCP_QUERY_EMBED_PROVIDER` does NOT exist today.**
   `server/query_encoder.py` is BGE-M3-only; no hosted-embedder
   path anywhere. The brief asks for the fallback BEHAVIOR; the
   full Voyage HTTP implementation balloons scope. Resolution per
   D6: ship the protocol + a stub + the fallback wrapper, defer
   the real HTTP client.
5. **LanceDB corruption fallback is the load-bearing new code.**
   `server/corpus.py:185` raises today; no N-1 fallback;
   `/readyz` has no "degraded" body shape. ~25 LOC of changes
   across `server/corpus.py`, `server/resources.py`, `server/health.py`.
6. **`infra/prometheus/alerts.yml` is greenfield.**
   No existing equivalent. The directory itself is new.
7. **Disk-full detection: server-emit, not node_exporter.** Use
   `shutil.disk_usage()` + a Prometheus Gauge with
   `set_function(...)` so the value recomputes at every scrape. No
   second daemon to deploy; exporter-agnostic alert expression.
8. **`ingest-paused` sentinel needs both write side (in scrape
   hook) AND read side (cron wrappers + `ingest/oai_delta.py`
   entry).** Hysteresis: write at <10 GB, clear at >15 GB.
9. **`docs/ops/restore-runbook.md` would duplicate
   `docs/ops/backup-restore.md`.** Don't create a second file;
   add a small "LanceDB version-dir vs restic prune" paragraph
   to the existing runbook.
10. **No new dependencies.** `prometheus_client`, `lancedb`,
    `shutil` (stdlib) cover the whole milestone.

---

## 2. Decisions

### D1. File placement

| Path | Status | Reason |
|---|---|---|
| `ops/cron/arxmcp-backup.sh` | EXISTS (E11_S05) | no-op confirm |
| `ops/restic-env.sh.template` | EXISTS (E11_S05) | no-op confirm |
| `ops/systemd/arxmcp-backup.{service,timer}` | EXISTS (E11_S05) | no-op confirm |
| `ops/restore_drill.sh` / `ops/restore_drill_check.py` | EXISTS (E11_S05) | no-op confirm |
| `docs/ops/backup-restore.md` | EXISTS (E11_S05) | add small risk-note paragraph (D9) |
| `tools/quarterly_drill_reminder.sh` | EXISTS (E14_S04) | no-op confirm |
| `infra/prometheus/alerts.yml` (NEW) | greenfield | D7 |
| `docs/ops/failure-modes.md` (NEW) | greenfield | D9 |
| `tools/ingest_sentinel.py` (NEW) | greenfield | D5 |
| `server/corpus.py` (MODIFY) | add fallback | D2 |
| `server/resources.py` (MODIFY) | add reranker warm-up + degraded state | D2, D3 |
| `server/health.py` (MODIFY) | degraded readyz body | D2 |
| `server/observability/metrics.py` (MODIFY) | disk-free gauge + degraded-mode gauge + hosted-fallback counter | D4, D6 |
| `server/query_encoder.py` (MODIFY) | hosted-embedder fallback path | D6 |
| `server/config.py` (MODIFY) | new env vars (ARXMCP_DATA_DIR, ARXMCP_QUERY_EMBED_PROVIDER, ARXMCP_VOYAGE_API_KEY) | D4, D6 |
| `ops/cron/arxmcp-delta.sh` (MODIFY) | sentinel check before flock | D5 |
| `ingest/oai_delta.py` (MODIFY) | sentinel check in `__main__` | D5 |
| `tests/test_failure_modes.py` (NEW) | corruption + sentinel + fallback tests | D10 |
| `tests/test_alerts_yaml.py` (NEW) | YAML shape + optional promtool | D10 |

NOT created (deliberate per D9):
- `docs/ops/restore-runbook.md` — `docs/ops/backup-restore.md` covers it.

### D2. LanceDB corruption fallback

In `server/corpus.py`, add a new `open_chunks_table_with_fallback(db,
corpus_info)` that:

1. Tries `db.open_table("chunks")` at the current version.
2. On `(lance.LanceError, OSError, RuntimeError, ValueError)` —
   broad on purpose because corruption surfaces unpredictably —
   logs WARN with the version and exception.
3. Retries with `checkout(version - 1)`, gated at `version >= 2`
   (CorpusVersionInfo's floor is 1; you can't checkout 0).
4. On success, returns `(table, DegradedState(active=True,
   reason="corpus_corruption", fallback_version=v-1))`.
5. On second failure, raises `RuntimeError("corpus_corruption_unrecoverable")`
   — the lifespan handler crashes the process.

In `server/resources.py::startup`, catch the second-tier raise
and propagate. Add `degraded: DegradedState | None` to the
Resources dataclass.

In `server/health.py::readyz`, return:

```python
{
    "status": "degraded",
    "reason": "corpus_corruption",
    "warm": {...},
    "fallback_version": <v-1>,
}
```

with status code 503 when `resources.degraded is not None`.

Tests (per D10):
- Synthetic-corruption test creates a tmpdir LanceDB v=2 + v=1,
  truncates `v=2`'s manifest, asserts the fallback opens v=1 and
  sets `degraded.active=True`.

### D3. Reranker warm-up dummy inference

In `server/resources.py::startup` (after `_load_reranker_or_raise`
when `config.enable_rerank=True`), sample 10 deterministic chunks
from `chunks_table.to_arrow().slice(0, 10)` (not random — keeps
`/readyz` timing stable across restarts), build dummy `(query,
chunk_text)` pairs with a fixed query (`"warmup query for the
BGE reranker"`), and run one forward pass via `RerankPhase.rerank`.
Block readiness until done.

Surface via a new gauge `arxmcp_resources_warm{resource="reranker_warmed"}`
that flips to 1.0 only after the dummy inference completes.

If the table has fewer than 10 chunks (early seed corpus), use
all available — never raise.

### D4. Disk-full detection — server-emit

In `server/observability/metrics.py`:

```python
DISK_FREE_BYTES = Gauge(
    "arxmcp_disk_free_bytes",
    "Free bytes on the arXMCP data filesystem",
    labelnames=["path"],
)
```

A scrape-time refresh hook in `server/health.py::refresh_metrics_from_singleton_state`
calls `shutil.disk_usage(config.data_dir)` and sets the gauge.
Same call writes the `ingest-paused` sentinel via
`tools.ingest_sentinel.write_pause("disk_low", free)` when
`free < 10 GB`, and clears via `clear_pause("disk_low")` when
`free > 15 GB` (hysteresis).

New `Config.data_dir: Path` field, env `ARXMCP_DATA_DIR`,
default `var/arxmcp/`.

### D5. `ingest-paused` sentinel + cron checks

New `tools/ingest_sentinel.py`:

```python
def write_pause(reason: str, free_bytes: int | None = None,
                threshold_bytes: int = 10 * 1024**3) -> None: ...
def clear_pause(reason: str | None = None) -> None: ...
def is_paused() -> dict | None: ...  # returns the JSON body or None

# CLI:
#   python -m tools.ingest_sentinel write --reason=disk_low --free=5000000
#   python -m tools.ingest_sentinel clear
#   python -m tools.ingest_sentinel status   # exit 0=running, 2=paused
```

`ops/cron/arxmcp-delta.sh` adds an early check:

```bash
PAUSE_FLAG="${REPO_ROOT}/var/arxmcp/ops/ingest-paused"
if [ -e "$PAUSE_FLAG" ]; then
    echo "ingest paused; reason=$(cat "$PAUSE_FLAG" | python3 -c \
        'import sys, json; print(json.load(sys.stdin).get(\"reason\", \"unknown\"))')" >&2
    exit 0
fi
```

`ingest/oai_delta.py::main` adds the same check as defense-in-
depth for manual invocations.

### D6. Hosted-embedder fallback (fallback-only contract)

In-scope:

- New `Config.query_embed_provider: Literal["local", "voyage"] = "local"`.
- New `Config.voyage_api_key: str | None = None` (env
  `ARXMCP_VOYAGE_API_KEY`).
- New `server/query_encoder.py::_HOSTED_PROVIDERS` registry.
- `voyage` provider stub class that raises
  `NotImplementedError("voyage HTTP client not yet implemented "
  "— see E14_S05 D6")` on first encode.
- `encode_query` wrapper: try hosted provider; on ANY exception
  (subclass of `Exception`), fall back to local BGE-M3, set
  `_hosted_fallback_active = True` for the rest of the request,
  emit a one-shot WARN log per process.
- Tag result rows with `degraded=true` + `degraded_reason="hosted_embedder_outage"`
  in `server/handlers/search.py` when the request hit the
  fallback path.
- New metric `arxmcp_hosted_embed_fallback_total{provider}`
  Counter.

Out of scope: real Voyage HTTP client (separate ticket).

### D7. Prometheus alert rules — `infra/prometheus/alerts.yml`

Three alerts:

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
          runbook_url: ".../docs/ops/failure-modes.md#disk-full"
      - alert: ArXMCPDegradedMode
        expr: arxmcp_degraded_mode_active == 1
        for: 1m
        labels: {severity: warning, component: server}
        annotations:
          summary: "arXMCP running in degraded mode ({{ $labels.reason }})"
          runbook_url: ".../docs/ops/failure-modes.md#degraded-modes"
      - alert: ArXMCPBackupStale
        expr: (time() - arxmcp_backup_last_success_timestamp_seconds) > 172800
        for: 10m
        labels: {severity: warning, component: backup}
        annotations:
          summary: "no successful restic backup in > 48h"
          runbook_url: ".../docs/ops/backup-restore.md"
```

New gauge `arxmcp_degraded_mode_active{reason}` in
`server/observability/metrics.py`; set in
`refresh_metrics_from_singleton_state` from
`resources.degraded`.

### D8. `tools/ingest_sentinel.py` shape

~80 LOC: dataclass `PauseRecord(reason, free_bytes, threshold_bytes, written_at)`,
JSON serialisation, idempotent write (overwrite preserved if
same reason), CLI via argparse.

### D9. Documentation

`docs/ops/failure-modes.md` (NEW) — table covering all 9 failure
modes from note 08, columns: # / Failure / Detection / Recovery /
Surfaces as / Runbook anchor. Plus one section per failure with
the procedure. Anchored at `#disk-full`, `#degraded-modes`,
`#hosted-embedder-outage`, `#lancedb-corruption`, etc.

`docs/ops/backup-restore.md` (MODIFY) — add one paragraph in §
"Risks" clarifying that restic prunes ITS snapshots, NOT the
live `lancedb/<version>/` MVCC directories that the F1 fallback
depends on. Reassure the operator that the existing wrapper
does NOT call `dataset.cleanup_old_versions()`.

### D10. Tests

`tests/test_failure_modes.py`:

- `TestLanceDBCorruptionFallback`:
  - `test_v_minus_1_fallback_on_v_manifest_corruption` — create
    tmpdir LanceDB v=1 + v=2, truncate v=2 manifest, assert
    `open_chunks_table_with_fallback` returns v=1 table + degraded
    flag.
  - `test_unrecoverable_when_both_versions_corrupt` — truncate
    both, assert RuntimeError.
  - `test_v_minus_1_skipped_at_floor` — corpus at v=1, no
    fallback possible; raises immediately.
- `TestDegradedReadyz`:
  - `test_readyz_returns_degraded_body_when_corrupt` — fake
    Resources with `degraded.active=True`, assert 503 +
    `{"status": "degraded", "reason": "corpus_corruption", ...}`.
- `TestIngestSentinel`:
  - `test_write_pause_then_is_paused_reads_back` — write +
    read the JSON.
  - `test_clear_pause_removes_sentinel` — write + clear + assert
    `is_paused() is None`.
- `TestDiskFullSentinelLogic`:
  - `test_writes_pause_when_free_below_threshold` — mock
    `shutil.disk_usage` returning (free=5GB), call refresh,
    assert sentinel exists.
  - `test_clears_pause_when_free_above_hysteresis_band` — same
    setup but free=20GB, sentinel cleared.
- `TestHostedEmbedderFallback`:
  - `test_voyage_stub_falls_back_to_local` — set provider=voyage,
    monkeypatch to raise, assert returns local result + degraded flag.

`tests/test_alerts_yaml.py`:

- `test_yaml_parses` — PyYAML round-trip.
- `test_three_alerts_present` — names check.
- `test_promtool_check_rules` — `@pytest.mark.skipif(shutil.which("promtool") is None)`.

### D11. Cron-side sentinel check (D5 wiring)

The `ops/cron/arxmcp-delta.sh` wrapper grows an early check:

```bash
PAUSE_FLAG="${REPO_ROOT}/var/arxmcp/ops/ingest-paused"
if [ -e "$PAUSE_FLAG" ]; then
    cat "$PAUSE_FLAG" >&2
    exit 0
fi
```

Same check at module entry of `ingest/oai_delta.py::main` for
direct invocations.

### D12. No-op confirms

The following are documented as "shipped in E11_S05, no
changes":

- `ops/cron/arxmcp-backup.sh`
- `ops/restic-env.sh.template`
- `ops/systemd/arxmcp-backup.{service,timer}`
- `ops/restore_drill.sh`
- `ops/restore_drill_check.py`
- `tools/quarterly_drill_reminder.sh` (E14_S04)

The implementation summary §"Drift from brief" notes that these
were already in place and that the brief's `infra/restic/` paths
are out-of-date.

---

## 3. Implementation order

1. `tools/ingest_sentinel.py` — first because the disk-full
   refresh hook calls it.
2. `server/config.py` — add `data_dir`, `query_embed_provider`,
   `voyage_api_key` fields.
3. `server/observability/metrics.py` — `DISK_FREE_BYTES`,
   `DEGRADED_MODE_ACTIVE`, `HOSTED_EMBED_FALLBACK_COUNTER`.
4. `server/health.py::refresh_metrics_from_singleton_state` —
   wire the disk-free + degraded-mode gauge refresh; call
   `tools.ingest_sentinel.write_pause/clear_pause` on threshold
   crossing.
5. `server/corpus.py` — `open_chunks_table_with_fallback` +
   `DegradedState` dataclass.
6. `server/resources.py` — degraded-state field; reranker
   warm-up dummy inference.
7. `server/health.py::readyz` — degraded body shape.
8. `server/query_encoder.py` — hosted-fallback wrapper; voyage
   stub.
9. `server/handlers/search.py` — tag results when fallback
   active.
10. `ops/cron/arxmcp-delta.sh` — sentinel check.
11. `ingest/oai_delta.py::main` — sentinel check (defense-in-
    depth).
12. `infra/prometheus/alerts.yml`.
13. `docs/ops/failure-modes.md` (NEW).
14. `docs/ops/backup-restore.md` — risk paragraph addendum.
15. `tests/test_failure_modes.py`.
16. `tests/test_alerts_yaml.py`.
17. `make test`, `ruff check .`, impl-summary, feat commit.

---

## 4. External writes required

**Zero beyond local commits.** Same posture as the other E14
milestones. No PyPI uploads, no GitHub-API calls, no SaaS account
creation (Voyage is a stub; no real HTTP). `git push` per user
authorization per-event.

---

## 5. Risk register (carry into Phase 3)

- **D2 LanceDB corruption test reliability.** Truncating a
  manifest in a tmpdir LanceDB is the synthetic path. The lance
  library may surface different exception types across versions.
  We catch broadly; the test pins the broad catch shape.
- **D3 reranker warm-up adds startup latency.** ~0.5–2s on CPU
  for 10 query-chunk pairs. The brief's note 08 explicitly says
  "Pre-warm at server startup" — acceptable.
- **D6 hosted-embedder fallback scope inflation.** Adversary
  may flag the stub-only approach. Rationale: full Voyage
  integration is a separate milestone; the fallback
  *behaviour* is what the brief actually requires.
- **D7 alert expressions reference metrics not yet emitted.**
  `arxmcp_degraded_mode_active` is new in D4/D7; the alert
  rule's `expr:` only matters at Prometheus runtime, not at
  validation time. `promtool check rules` validates only
  syntax, not metric existence.
- **D9 doc drift.** `docs/ops/backup-restore.md` and the new
  `docs/ops/failure-modes.md` both document the disk-full
  failure mode. Keep one CANONICAL location per failure mode;
  the runbook cross-links to the other.
- **D11 cron-side check race.** The sentinel-write and cron-
  check are both filesystem operations on different processes.
  Worst case: the sentinel was just written and the cron started
  reading 100ms before — cron runs once, then the next fire
  honors the sentinel. Acceptable; not data-corrupting.
