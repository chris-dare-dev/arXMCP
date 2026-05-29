"""Health and metrics endpoints (E06_S01).

Three operationally-distinct routes:

- ``GET /healthz`` — **liveness**. Returns 200 as long as the process
  responds. Intended for orchestrator restart loops (Docker
  ``HEALTHCHECK``, k8s livenessProbe). Does NOT depend on resource
  warm state — a process answering ``/healthz`` may still be loading
  models. The brief AC: *"GET /healthz returns 200 before
  readiness."*

- ``GET /readyz`` — **readiness**. Returns 200 only after the
  embedder, LanceDB handle, and (if enabled) reranker are warm.
  Returns 503 with a JSON body listing which resource is not yet
  warm. The brief AC: *"GET /readyz returns 503 until embedder +
  LanceDB are initialized, then 200."* k8s readinessProbe consumers
  use this to decide when to route traffic.

- ``GET /metrics`` — **Prometheus exposition**. Mounted as a
  sub-ASGI app via ``prometheus_client.make_asgi_app()`` from
  :mod:`server.main` rather than registered here as a route — this
  module just defines the canonical metric set so downstream tool
  modules (E06_S03+) reach into one registry, not several.

The metric set at this milestone (synthesis D11) is intentionally
small — per-tool counters land in E06_S03 when the tools materialize.
The names follow the project's naming convention from
:doc:`.claude/notes/08-security-observability-ops.md` so future
additions don't collide.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Gauge

if TYPE_CHECKING:
    from server.resources import Resources


logger = logging.getLogger(__name__)

#: Most-recent corpus_versions exposed via :data:`EVAL_NDCG5_GAUGE`.
#: E14_S01 synthesis D6 — cap label cardinality so the watchdog's
#: per-corpus-version histogram cannot drift unboundedly. Older
#: labels are evicted via ``Gauge.remove(...)`` at refresh time.
_EVAL_NDCG5_LABEL_CAP: int = 5

#: Sentinel-file basenames the scrape hook reads. Hoisted to module
#: scope so a future ops note can grep one place for the cron-vs-server
#: file contract.
_DRIFT_FLAG_NAME: str = "drift-detected.flag"
_QUARANTINE_FLAG_NAME: str = "eval-quarantine.flag"
_DELTA_TIMEOUT_FLAG_NAME: str = "delta-timeout.flag"
_BACKUP_STATUS_NAME: str = "backup-status.json"
_EVAL_REPORTS_DIR: str = "eval-reports"

#: Backup states that the wrapper may emit, in the order
#: ``backup-status.json`` documents (see
#: ``docs/ops/backup-restore.md``). Used by
#: :func:`refresh_sentinel_metrics` to zero-out the inactive
#: states so exactly one cell is 1.0 at a time. ``"unknown"`` is
#: the catch-all bucket the scrape hook lights up when the wrapper
#: emits a state outside the documented set — closes F4 from the
#: E14_S01 adversary critique (silent alert suppression on
#: corrupted / future state strings).
_BACKUP_STATES: tuple[str, ...] = ("ok", "failed", "running", "unknown")

#: Maximum bytes the scrape hook will ``read_text`` from any
#: cron-emitted sentinel file. Each ``/metrics`` scrape walks
#: every sentinel; an oversized file would materialize its full
#: byte string in process RSS per scrape (default Prometheus
#: scrape interval is 15s). Closes F1 from the E14_S01 adversary
#: critique. 64 KB is far above any legitimate sentinel
#: (drift-detected.flag is a touch-file or a tiny JSON;
#: backup-status.json is <1 KB; each eval-report is <10 KB).
_MAX_SENTINEL_BYTES: int = 64 * 1024

# ---------------------------------------------------------------------------
# Prometheus registry — one per process, populated by the lifespan.
# ---------------------------------------------------------------------------

#: Pinned ``corpus_version`` integer. Updated once at startup.
CORPUS_VERSION_GAUGE = Gauge(
    "arxmcp_corpus_version",
    "The integer corpus_version the server pinned at startup. "
    "Constant for the process lifetime; restart to pick up a new "
    "corpus version.",
)

#: corpus-integrity-observability-m2 — the marker's ``chunk_count`` read
#: once at startup. Compared against CORPUS_CHUNK_COUNT_ACTUAL; a
#: persistent gap means the corpus-version.json marker disagrees with the
#: live table (the silent ~100x drift the m1 bug class produced).
CORPUS_CHUNK_COUNT_MARKER = Gauge(
    "arxmcp_corpus_chunk_count_marker",
    "chunk_count from corpus-version.json, read once at startup. "
    "Compare with arxmcp_corpus_chunk_count_actual; a persistent gap "
    "means the marker disagrees with the live chunks table.",
)

#: corpus-integrity-observability-m2 — the live ``chunks_table.count_rows()``
#: captured ONCE at startup (cached on Resources.startup_chunk_count). NOT
#: recomputed per scrape. ``-1`` means count_rows() failed at startup
#: (Resources.startup FM-2). Equals the marker gauge on the happy path.
CORPUS_CHUNK_COUNT_ACTUAL = Gauge(
    "arxmcp_corpus_chunk_count_actual",
    "Live chunks-table row count read once at startup. -1 = count "
    "unavailable. Equals arxmcp_corpus_chunk_count_marker on the happy "
    "path; a gap indicates corpus/marker divergence.",
)

#: Per-resource warm state (0 = not loaded, 1 = warm). One time series
#: per resource label.
RESOURCE_WARM_GAUGE = Gauge(
    "arxmcp_resources_warm",
    "Whether a server resource is loaded and ready to serve "
    "requests. 1 = warm, 0 = not loaded. Three resources at this "
    "milestone: embedder, lancedb, reranker.",
    labelnames=["resource"],
)

#: UNIX timestamp at which the server process started. Set once at
#: startup; together with the Prometheus default ``process_*``
#: collectors this lets dashboards distinguish "server process up"
#: from "server process restarted recently".
PROCESS_START_TIME_GAUGE = Gauge(
    "arxmcp_process_start_time_seconds",
    "UNIX epoch (seconds) at which the arxmcp-server process "
    "started. Set once during the lifespan startup.",
)

#: Embedder singleflight dedup hits since process start. The wireable
#: counterpart of :func:`server.query_encoder.get_singleflight_dedup_count`.
#: F8 from the E03_S03 critique flagged that we should expose this; the
#: ``/metrics`` collector reads the source-of-truth integer at scrape
#: time and ``inc(delta)``s the counter to match — see
#: :func:`refresh_metrics_from_singleton_state`.
EMBED_SINGLEFLIGHT_DEDUP_COUNTER = Counter(
    "arxmcp_embed_singleflight_dedup_total",
    "Number of times an in-flight BGE-M3 query embedding was reused "
    "by another concurrent caller (singleflight cache hit). Higher "
    "values indicate more inter-request query overlap; near-zero "
    "values indicate fully-distinct query traffic.",
)

#: Track the last-observed dedup count so the counter only ever
#: monotonically increases (Counter contract). Module-level state is
#: fine here — single process, single registry.
_LAST_DEDUP_COUNT = 0


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe.

    Always 200 if the process can respond at all. Does NOT inspect
    resource warm state — a process loading the BGE-M3 model still
    returns 200 here (and 503 from ``/readyz``). The brief AC:
    *"returns 200 before readiness."*
    """
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> Response:
    """Readiness probe.

    Returns 200 only after :meth:`server.resources.Resources.startup`
    has completed and ``Resources.warm`` is True. Returns 503 with a
    JSON body naming the un-warm resources during the window between
    process start and readiness.

    The body shape is documented for ops dashboards:

        {"status": "ready" | "not_ready",
         "warm": {"embedder": bool, "lancedb": bool, "reranker": bool}}
    """
    resources: Resources | None = getattr(
        request.app.state, "resources", None
    )

    # Resources not yet attached → still in lifespan startup window.
    if resources is None or not resources.warm:
        # Probe the per-resource state if we have a partial Resources
        # object; otherwise return all-False.
        if resources is None:
            warm_map = {
                "embedder": False,
                "lancedb": False,
                "reranker": False,
            }
        else:
            warm_map = {
                "embedder": resources.is_resource_warm("embedder"),
                "lancedb": resources.is_resource_warm("lancedb"),
                "reranker": resources.is_resource_warm("reranker"),
            }
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "warm": warm_map},
        )

    # E14_S05 D2: degraded body. When the LanceDB N-1 fallback was
    # activated at startup, /readyz returns 503 with the degraded
    # body — load-balancers see "not healthy" and operators see the
    # exact reason. The server still serves requests because the
    # chunks_table is open at the fallback version.
    if resources.degraded is not None:
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "reason": resources.degraded.reason,
                "fallback_version": resources.degraded.fallback_version,
                "original_version": resources.degraded.original_version,
                "warm": {
                    "embedder": resources.is_resource_warm("embedder"),
                    "lancedb": resources.is_resource_warm("lancedb"),
                    "reranker": resources.is_resource_warm("reranker"),
                },
            },
        )

    # corpus-integrity-observability-e2 (scout CAND-6b — the BP1-free cut):
    # surface the m2 startup-cached corpus counts on the ready body so an
    # operator (or a probe) sees the marker-vs-table reconciliation without an
    # extra MCP tool (get_corpus_status stays on the Won't list; /readyz is NOT
    # MCP surface, so the tool-schema + BP1 hashes are unaffected). A -1
    # startup_chunk_count (count_rows() failed at startup — m2 FM-2) renders as
    # null, never a bogus negative count.
    startup_count = resources.startup_chunk_count
    return JSONResponse(
        status_code=200,
        content={
            "status": "ready",
            "chunk_count": None if startup_count < 0 else startup_count,
            "marker_chunk_count": resources.corpus_info.chunk_count,
            "warm": {
                "embedder": resources.is_resource_warm("embedder"),
                "lancedb": resources.is_resource_warm("lancedb"),
                "reranker": resources.is_resource_warm("reranker"),
            },
        },
    )


# ---------------------------------------------------------------------------
# Metric refresh helper
# ---------------------------------------------------------------------------


def refresh_metrics_from_singleton_state(resources: Resources) -> None:
    """Pull module-level singleton state into the Prometheus registry.

    Called from the ``/metrics`` ASGI app's request handler (hooked
    in :mod:`server.main` via a small middleware around the prometheus
    sub-app) so scrapes always observe fresh values for the gauges
    that track underlying-singleton state. Counter monotonicity is
    preserved by tracking the last-observed dedup count and
    incrementing by the delta only.
    """
    global _LAST_DEDUP_COUNT
    from server.query_encoder import get_singleflight_dedup_count

    # Gauges: instantaneous truth.
    CORPUS_VERSION_GAUGE.set(resources.corpus_info.version)
    # corpus-integrity-observability-m2: O(1) reads of the startup-cached
    # count + the marker count from a fully-constructed Resources. NEVER call
    # count_rows() here — the gauges read the cached ints
    # (startup_chunk_count = -1 only when count_rows() failed at startup). The
    # reconciliation/gauge path computes the count exactly once at startup; a
    # /metrics scrape never recomputes it. (Direct access, matching the
    # corpus_info.version read above — F4: no getattr sentinel that would mask
    # a genuine missing-field wiring bug as the FM-2 count-unavailable signal.)
    CORPUS_CHUNK_COUNT_MARKER.set(resources.corpus_info.chunk_count)
    CORPUS_CHUNK_COUNT_ACTUAL.set(resources.startup_chunk_count)
    PROCESS_START_TIME_GAUGE.set(resources.process_start_time_seconds)
    for res_name in ("embedder", "lancedb", "reranker"):
        RESOURCE_WARM_GAUGE.labels(resource=res_name).set(
            1.0 if resources.is_resource_warm(res_name) else 0.0
        )

    # Counter: monotonic delta from the source-of-truth integer.
    current = get_singleflight_dedup_count()
    delta = current - _LAST_DEDUP_COUNT
    if delta > 0:
        EMBED_SINGLEFLIGHT_DEDUP_COUNTER.inc(delta)
        _LAST_DEDUP_COUNT = current

    # E08_S03: refresh the cache byte-usage gauges. Cheap (three
    # integer sums); a missing cache singleton is a no-op.
    from server.metrics import refresh_cache_metrics

    refresh_cache_metrics(getattr(resources, "cache", None))

    # E14_S01: bridge cron-emitted sentinel files into Prometheus
    # gauges. Cron processes exit between runs so they can't keep a
    # gauge set in-process — the sentinel files ARE the cross-process
    # signal channel. Reading them at scrape time is cheap (a few
    # stat() + small JSON parses) and the failure mode is per-file
    # graceful: a missing file zeroes that gauge; a malformed file
    # logs a warning and leaves the prior value (operator gets a
    # stale-but-known signal rather than a misleading zero).
    config = getattr(resources, "config", None)
    ops_dir = getattr(config, "ops_dir", None) if config is not None else None
    if ops_dir is not None:
        refresh_sentinel_metrics(Path(ops_dir))

    # E14_S05: disk-free gauge + ingest-paused sentinel management.
    # Reads ``shutil.disk_usage(config.data_dir)`` and (a) sets
    # ``arxmcp_disk_free_bytes{path}``, (b) writes the
    # ``ingest-paused`` sentinel when free < 10 GB, (c) clears it
    # when free > 15 GB (hysteresis — don't toggle at the boundary).
    data_dir = getattr(config, "data_dir", None) if config is not None else None
    if data_dir is not None:
        refresh_disk_free_metric(Path(data_dir))

    # E14_S05: degraded-mode gauge. Surface the failure-mode
    # fallback state to Prometheus + Phoenix so the ArXMCPDegradedMode
    # alert fires when the server is running on a fallback corpus
    # version (or any other future degraded reason).
    refresh_degraded_mode_metric(resources)


def refresh_sentinel_metrics(ops_dir: Path) -> None:
    """Read cron-emitted sentinel files from ``ops_dir`` and update
    the corresponding Prometheus gauges (E14_S01 synthesis D5).

    Sentinel contract — for each file we recognise, the rule is:

    - ``drift-detected.flag`` — present means "≥1 fixture has drifted".
      Body may be JSON ``{"fixture_count": N}``; if so, the gauge is
      set to ``N``. Body may be a touch file (empty); the gauge is
      set to 1.0. Absence sets the gauge to 0.0.
    - ``eval-quarantine.flag`` / ``delta-timeout.flag`` — touch-file
      style; presence sets the gauge to 1.0, absence to 0.0.
    - ``backup-status.json`` — JSON ``{"status": "ok"|"failed"|"running",
      "finished_at": <iso8601>}``. ``finished_at`` is parsed to an
      epoch and set on :data:`BACKUP_LAST_SUCCESS_GAUGE`; ``status``
      drives exclusive 1.0 on :data:`BACKUP_STATUS_GAUGE{state}`.
    - ``eval-reports/corpus_v<N>-*.json`` — the watchdog's per-corpus-
      version nDCG@5 reports. The N most-recent reports drive
      :data:`EVAL_NDCG5_GAUGE`; older labels are evicted from the
      gauge to bound cardinality.

    Per-file errors are isolated: malformed JSON in one file does NOT
    prevent the others from being refreshed.
    """
    from server.metrics import (
        BACKUP_LAST_SUCCESS_GAUGE,
        BACKUP_STATUS_GAUGE,
        DELTA_TIMEOUT_ACTIVE_GAUGE,
        EVAL_QUARANTINE_ACTIVE_GAUGE,
        LATEXML_DRIFT_DETECTED_GAUGE,
    )

    # --- drift-detected.flag → LATEXML_DRIFT_DETECTED_GAUGE -----------
    drift_flag = ops_dir / _DRIFT_FLAG_NAME
    if drift_flag.is_file():
        value = _read_drift_flag(drift_flag)
        LATEXML_DRIFT_DETECTED_GAUGE.set(value)
    else:
        LATEXML_DRIFT_DETECTED_GAUGE.set(0.0)

    # --- eval-quarantine.flag / delta-timeout.flag → 0/1 gauges -------
    EVAL_QUARANTINE_ACTIVE_GAUGE.set(
        1.0 if (ops_dir / _QUARANTINE_FLAG_NAME).is_file() else 0.0
    )
    DELTA_TIMEOUT_ACTIVE_GAUGE.set(
        1.0 if (ops_dir / _DELTA_TIMEOUT_FLAG_NAME).is_file() else 0.0
    )

    # --- backup-status.json → BACKUP_LAST_SUCCESS + BACKUP_STATUS -----
    backup_status = ops_dir / _BACKUP_STATUS_NAME
    if backup_status.is_file():
        try:
            raw = _read_capped(backup_status)
            payload = json.loads(raw) if raw is not None else None
            if payload is not None:
                finished_at = payload.get("finished_at")
                if isinstance(finished_at, str) and finished_at:
                    # ``datetime.fromisoformat`` handles RFC-3339 (including
                    # the trailing-``Z`` form on Python 3.11+, which is the
                    # project floor).
                    from datetime import datetime  # noqa: PLC0415

                    BACKUP_LAST_SUCCESS_GAUGE.set(
                        datetime.fromisoformat(finished_at).timestamp()
                    )
                state = payload.get("status")
                if isinstance(state, str):
                    # F4 rectification — unknown / corrupted / future state
                    # strings light up the ``unknown`` cell instead of
                    # silently zeroing every state. Operators wiring
                    # ``arxmcp_backup_status{state="failed"}`` alerts
                    # would otherwise miss a regression to an emit-
                    # mismatched-string wrapper bug.
                    bucket = state if state in _BACKUP_STATES else "unknown"
                    if bucket == "unknown":
                        logger.warning(
                            "backup-status.json at %s reports unknown state "
                            "%r; routing to arxmcp_backup_status{state=\"unknown\"}",
                            backup_status,
                            state,
                        )
                    for s in _BACKUP_STATES:
                        BACKUP_STATUS_GAUGE.labels(state=s).set(
                            1.0 if s == bucket else 0.0
                        )
        except (json.JSONDecodeError, OSError, ValueError):
            logger.warning(
                "backup-status.json at %s is malformed; leaving prior gauge values",
                backup_status,
                exc_info=True,
            )
    else:
        BACKUP_LAST_SUCCESS_GAUGE.set(0.0)
        for s in _BACKUP_STATES:
            BACKUP_STATUS_GAUGE.labels(state=s).set(0.0)

    # --- eval-reports/corpus_v<N>-*.json → EVAL_NDCG5_GAUGE -----------
    reports_dir = ops_dir / _EVAL_REPORTS_DIR
    if reports_dir.is_dir():
        _refresh_eval_ndcg5(reports_dir)


def _read_capped(path: Path) -> str | None:
    """Read ``path`` as UTF-8 text, refusing files larger than
    :data:`_MAX_SENTINEL_BYTES`. Closes F1 from the E14_S01 adversary
    critique — every scrape walks the sentinel directory, and an
    attacker (or a buggy cron) that can write a 100 GB sentinel
    would otherwise OOM the server at scrape time.

    Returns ``None`` when the file is oversized (after emitting a
    WARNING log line so operators have a positive signal). Returns
    the file contents on success. Raises :class:`OSError` on read
    failure — callers catch + log.
    """
    try:
        size = path.stat().st_size
    except OSError:
        raise
    if size > _MAX_SENTINEL_BYTES:
        logger.warning(
            "sentinel file %s is %d bytes (cap is %d); refusing to "
            "read body. Operator should inspect the file and either "
            "remove it or fix the producing cron.",
            path,
            size,
            _MAX_SENTINEL_BYTES,
        )
        return None
    return path.read_text(encoding="utf-8")


def _read_drift_flag(drift_flag: Path) -> float:
    """Return the drift-fixture-count value to set on
    :data:`server.metrics.LATEXML_DRIFT_DETECTED_GAUGE`.

    Behavior matrix (precedence top-down):

    * oversized file (size > :data:`_MAX_SENTINEL_BYTES`) → 1.0
      (treat as touch-file; the WARNING from :func:`_read_capped`
      is the operator's actionable signal).
    * empty body → 1.0 (touch-file convention).
    * JSON object with ``fixture_count`` integer → the integer.
    * malformed JSON / OSError / non-numeric ``fixture_count`` →
      1.0 with a WARNING log line.
    """
    try:
        raw = _read_capped(drift_flag)
    except OSError:
        logger.warning(
            "drift-detected.flag at %s could not be read; treating as "
            "touch-file=1.0",
            drift_flag,
            exc_info=True,
        )
        return 1.0
    if raw is None:
        # Oversized — _read_capped already logged.
        return 1.0
    raw = raw.strip()
    if not raw:
        return 1.0
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "fixture_count" in parsed:
            return float(parsed["fixture_count"])
    except (json.JSONDecodeError, ValueError):
        logger.warning(
            "drift-detected.flag at %s is malformed; treating as "
            "touch-file=1.0",
            drift_flag,
            exc_info=True,
        )
    return 1.0


def _refresh_eval_ndcg5(reports_dir: Path) -> None:
    """Drive :data:`server.metrics.EVAL_NDCG5_GAUGE` from the watchdog's
    per-corpus-version JSON reports.

    Each file is named ``corpus_v<N>-<timestamp>.json`` and contains a
    JSON object with at least an ``ndcg5_mean`` numeric field. For each
    corpus_version with one or more reports, we use the MOST RECENT
    report (highest mtime). After computing the per-version map, only
    the :data:`_EVAL_NDCG5_LABEL_CAP` highest corpus_versions are kept
    on the gauge; older labels are evicted via ``Gauge.remove(...)``
    so the registry doesn't accumulate labels indefinitely.
    """
    from server.metrics import EVAL_NDCG5_GAUGE

    by_version: dict[int, tuple[float, float]] = {}
    for report_path in reports_dir.glob("corpus_v*.json"):
        try:
            # Filename shape: ``corpus_v<N>-<rest>.json``. Parse N from
            # the prefix; skip files whose name doesn't match.
            stem = report_path.stem
            if not stem.startswith("corpus_v"):
                continue
            version_part = stem[len("corpus_v"):].split("-", 1)[0]
            corpus_version = int(version_part)
            mtime = report_path.stat().st_mtime
            prior = by_version.get(corpus_version)
            if prior is not None and prior[0] >= mtime:
                continue
            # F1 rectification — per-file size cap so a 100 GB report
            # under eval-reports/ can't OOM the server at scrape time.
            raw = _read_capped(report_path)
            if raw is None:
                continue
            payload = json.loads(raw)
            ndcg5 = payload.get("ndcg5_mean")
            if not isinstance(ndcg5, (int, float)):
                continue
            by_version[corpus_version] = (mtime, float(ndcg5))
        except (json.JSONDecodeError, OSError, ValueError):
            logger.warning(
                "eval-report %s is malformed; skipping",
                report_path,
                exc_info=True,
            )
            continue

    # Cap label cardinality at the N most-recent corpus_versions.
    if not by_version:
        return
    sorted_versions = sorted(by_version.keys(), reverse=True)
    kept = set(sorted_versions[:_EVAL_NDCG5_LABEL_CAP])
    # Evict labels for versions outside the cap so the gauge doesn't
    # accumulate stale time series across restarts that pick up older
    # report files in the directory.
    existing = {
        labelvalues[0]
        for labelvalues in list(EVAL_NDCG5_GAUGE._metrics.keys())
    }
    for stale in existing - {str(v) for v in kept}:
        # Removed concurrently or never present → ignore.
        with contextlib.suppress(KeyError):
            EVAL_NDCG5_GAUGE.remove(stale)
    # Set kept versions to their latest measurement.
    for v in kept:
        _, ndcg5 = by_version[v]
        EVAL_NDCG5_GAUGE.labels(corpus_version=str(v)).set(ndcg5)


#: Disk-free hysteresis: write the ingest-paused sentinel when free
#: bytes drop below this threshold (10 GB). Closes E14_S05 D4.
DISK_PAUSE_THRESHOLD_BYTES: int = 10 * 1024**3

#: Clear the ingest-paused sentinel only after free climbs back
#: above this threshold (15 GB). Prevents the cron from oscillating
#: at the exact pause threshold.
DISK_CLEAR_THRESHOLD_BYTES: int = 15 * 1024**3

#: Slug written into the sentinel JSON when disk-low is the
#: trigger. The sentinel CLI accepts arbitrary slugs; this is the
#: one the scrape hook uses so the operator can ``cat`` the file
#: and immediately understand why ingest paused.
DISK_PAUSE_REASON: str = "disk_low"


def refresh_disk_free_metric(data_dir: Path) -> None:
    """Refresh :data:`server.observability.metrics.DISK_FREE_BYTES`
    from ``shutil.disk_usage(data_dir)`` and update the
    ``ingest-paused`` sentinel state with hysteresis. E14_S05 D4.

    Failure mode 7 (Disk full) from
    :doc:`.claude/notes/08-security-observability-ops.md`:
    "Block ingestion, allow reads to continue, page operator."

    Idempotent — calling repeatedly with stable disk state is
    cheap (one ``statvfs`` syscall) and does not toggle the
    sentinel.
    """
    import shutil  # noqa: PLC0415

    from server.observability.metrics import DISK_FREE_BYTES  # noqa: PLC0415

    try:
        usage = shutil.disk_usage(str(data_dir))
    except OSError as exc:
        logger.warning(
            "disk_free refresh failed for %s: %s; gauge not "
            "updated this scrape",
            data_dir,
            exc,
        )
        return

    DISK_FREE_BYTES.labels(path=str(data_dir)).set(usage.free)

    # Sentinel management. Importing lazily so a test fixture can
    # monkey-patch tools.ingest_sentinel cleanly.
    from tools import ingest_sentinel  # noqa: PLC0415

    sentinel_path = Path(data_dir) / "ops" / "ingest-paused"
    if usage.free < DISK_PAUSE_THRESHOLD_BYTES:
        if not sentinel_path.is_file():
            logger.warning(
                "disk_free below threshold (%d < %d bytes); "
                "writing ingest-paused sentinel at %s",
                usage.free,
                DISK_PAUSE_THRESHOLD_BYTES,
                sentinel_path,
            )
        ingest_sentinel.write_pause(
            reason=DISK_PAUSE_REASON,
            free_bytes=usage.free,
            threshold_bytes=DISK_PAUSE_THRESHOLD_BYTES,
            path=sentinel_path,
        )
    elif usage.free > DISK_CLEAR_THRESHOLD_BYTES and sentinel_path.is_file():
        # Only auto-clear sentinels we wrote (reason=disk_low). An
        # operator-written maintenance sentinel must survive auto-
        # recovery — the operator clears it manually.
        record = ingest_sentinel.is_paused(path=sentinel_path)
        if record is not None and record.get("reason") == DISK_PAUSE_REASON:
            logger.info(
                "disk_free recovered (%d > %d bytes); clearing "
                "ingest-paused sentinel at %s",
                usage.free,
                DISK_CLEAR_THRESHOLD_BYTES,
                sentinel_path,
            )
            ingest_sentinel.clear_pause(path=sentinel_path)


def refresh_degraded_mode_metric(resources: Resources) -> None:
    """Set :data:`server.observability.metrics.DEGRADED_MODE_ACTIVE`
    from ``resources.degraded``. E14_S05 D7.

    The gauge has a ``reason`` label so the alert rule can
    surface which degradation is active (e.g.
    ``arxmcp_degraded_mode_active{reason="corpus_corruption"} 1``).
    """
    from server.observability.metrics import DEGRADED_MODE_ACTIVE  # noqa: PLC0415

    degraded = getattr(resources, "degraded", None)
    if degraded is None:
        # Reset known labels to 0. The label space is bounded by
        # the DegradedState.reason enum — small enough to enumerate.
        # "chunk_count_diverged" added by corpus-integrity-observability-m2.
        for reason in (
            "corpus_corruption",
            "hosted_embedder_outage",
            "chunk_count_diverged",
        ):
            DEGRADED_MODE_ACTIVE.labels(reason=reason).set(0.0)
        return
    DEGRADED_MODE_ACTIVE.labels(reason=degraded.reason).set(1.0)


def reset_metrics_for_tests() -> None:
    """Test hook — reset the module-level dedup tracker.

    Used by ``tests/test_server_startup.py`` to restore a clean
    counter state between independent test cases (the Prometheus
    ``Counter`` itself is also reset via ``REGISTRY.unregister``
    if needed; for E06_S01 the tests just verify scrape-time values
    rather than absolute counts).
    """
    global _LAST_DEDUP_COUNT
    _LAST_DEDUP_COUNT = 0


__all__ = [
    "CORPUS_CHUNK_COUNT_ACTUAL",
    "CORPUS_CHUNK_COUNT_MARKER",
    "CORPUS_VERSION_GAUGE",
    "EMBED_SINGLEFLIGHT_DEDUP_COUNTER",
    "PROCESS_START_TIME_GAUGE",
    "RESOURCE_WARM_GAUGE",
    "healthz",
    "readyz",
    "refresh_degraded_mode_metric",
    "refresh_disk_free_metric",
    "refresh_metrics_from_singleton_state",
    "refresh_sentinel_metrics",
    "reset_metrics_for_tests",
    "router",
]


# Suppress unused-import warning — `time` is imported for future use
# (per-tool latency histograms in E06_S03 will need wall-clock).
_ = time
