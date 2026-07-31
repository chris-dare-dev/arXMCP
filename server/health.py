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

from server.backup_status import (
    BACKUP_STATE_UNKNOWN,
    BACKUP_STATES,
    advances_freshness,
    classify_backup_state,
)

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
_INGEST_SUMMARY_NAME: str = "ingest-summary.json"
_EVAL_REPORTS_DIR: str = "eval-reports"

#: Backup label cells, sourced from the SHARED producer/consumer
#: vocabulary in :mod:`server.backup_status` — see that module for why
#: this must not be re-declared locally (``chris-dare-dev/arXMCP#202``:
#: the local literal drifted disjoint from what the wrapper emitted, so
#: every backup classified as ``unknown``). Used by
#: :func:`refresh_sentinel_metrics` to zero-out the inactive states so
#: exactly one cell is 1.0 at a time. ``"unknown"`` is the catch-all the
#: scrape hook lights up when the wrapper emits a state outside the
#: shared set — closes F4 from the E14_S01 adversary critique (silent
#: alert suppression on corrupted / future state strings).
_BACKUP_STATES: tuple[str, ...] = BACKUP_STATES


def _last_success_stamp(
    payload: dict[str, object], bucket: str | None
) -> str | None:
    """The ISO-8601 timestamp of the last SUCCESSFUL backup as recorded by
    ``backup-status.json``, or ``None`` when there has never been one.

    Shared by BOTH backup consumers — :func:`refresh_sentinel_metrics`
    (``arxmcp_backup_last_success_timestamp_seconds``) and
    :func:`compute_health_status` (the ``backup:time`` check) — so the two
    can never disagree about when the last good backup happened. That
    divergence is the shape ``chris-dare-dev/arXMCP#203`` took.

    Resolution order:

    1. ``last_success_at``, read **unconditionally**. The wrapper carries
       this field forward onto every sentinel it writes, including the
       failed / partial / running ones, so it names the last good run
       regardless of how the current one went. Reading it without gating on
       ``status`` is the whole point: it is what survives a server restart
       taken while the latest run was not ``ok``. Before this field existed
       the freshness gauge was pure process state that only an ``ok``
       sentinel could seed, so such a restart left it at 0.0 with nothing
       able to advance it — ``ArXMCPBackupStale`` fired instantly with an
       age measured from epoch 0.
    2. ``finished_at``, but only when ``bucket`` is a freshness-advancing
       state. This is the upgrade path for sentinels written before the
       wrapper carried the field, and the gate is #203 itself: the wrapper
       stamps ``finished_at`` on every run that reaches the end, success or
       not, so on its own it is not evidence of a backup having happened.

    A candidate that is not a parseable timestamp is skipped with a WARNING
    rather than raised on, so one corrupt field cannot cost the caller the
    other, usable one.
    """
    from datetime import datetime  # noqa: PLC0415

    gate_ok = bucket is not None and advances_freshness(bucket)
    for key, gated in (("last_success_at", False), ("finished_at", True)):
        if gated and not gate_ok:
            continue
        candidate = payload.get(key)
        if not isinstance(candidate, str) or not candidate:
            continue
        try:
            # ``fromisoformat`` handles RFC-3339 including the trailing-``Z``
            # form on Python 3.11+, which is the project floor.
            datetime.fromisoformat(candidate)
        except ValueError:
            logger.warning(
                "backup-status.json carries an unparseable %s=%r; ignoring it",
                key,
                candidate,
            )
            continue
        return candidate
    return None


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

#: The ``corpus_version`` currently being served. Set at startup and
#: refreshed whenever the process re-binds the corpus (issue #207).
CORPUS_VERSION_GAUGE = Gauge(
    "arxmcp_corpus_version",
    "The integer corpus_version the server is currently serving. "
    "Changes in-process when an ingest advances corpus-version.json "
    "and the server re-binds; a step in this gauge marks that rebind.",
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

#: corpus-integrity-observability-m3 (scout CAND-10) — total HNSW unindexed
#: rows across all ANN indexes, read ONCE at startup. -1 = could not determine
#: (index API raised, or no ANN index exists); 0 = checked & clean; >0 =
#: abnormal (rows committed without an index rebuild → ANN brute-forces them, a
#: silent perf degradation). Non-zero is ALWAYS abnormal in normal operation
#: (_create_indices runs synchronously in write_chunks). Alert on > 0.
CORPUS_UNINDEXED_ROWS = Gauge(
    "arxmcp_corpus_unindexed_rows",
    "Total HNSW unindexed rows across all ANN indexes, read once at startup. "
    "-1 = unavailable (index API raised, or no ANN index). 0 = fully indexed "
    "(normal). >0 = abnormal: ANN brute-forces those rows; re-run ingest to "
    "rebuild.",
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

    # onboarding-uplift-m4 F2: bootstrap mode → 200 with status "bootstrap".
    # Synthesis §3 D1: a 503 causes the shim to treat the server as down,
    # defeating the wizard flow. Return 200 so the shim forwards MCP calls
    # (which the orchestrator-level stub-check in tools.py handles).
    if resources is not None and getattr(resources, "bootstrap_mode_active", False):
        warm_map = {
            "embedder": False,
            "lancedb": False,
            "reranker": False,
        }
        return JSONResponse(
            status_code=200,
            content={
                "status": "bootstrap",
                "bootstrap_mode_active": True,
                "warm": warm_map,
            },
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
# /status — human-friendly operability endpoint (notebook-ops-hardening-m4)
# ---------------------------------------------------------------------------

#: Last-backup staleness threshold. The daily restic cron fires ~03:30; a
#: ``finished_at`` older than this (or an absent backup) flips the backup
#: check to ``warn``. 25h gives the daily run a full extra hour of grace.
_BACKUP_STALE_SECONDS: float = 25 * 3600


def _iso_now() -> str:
    from datetime import UTC, datetime  # noqa: PLC0415

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


async def compute_health_status(
    resources: Resources | None,
    store: object | None = None,
    *,
    now: float | None = None,
) -> dict[str, object]:
    """Compute the operability snapshot backing BOTH ``/status`` (health+json)
    and ``/ui/status-badge`` (HTML). notebook-ops-hardening-m4.

    Returns ``{"status", "http_code", "checks", "summary"}`` where ``status``
    is the IETF ``application/health+json`` top-level value:

    - **not warm / pre-startup → ``"fail"`` (503)** — matches ``/readyz``'s
      503-before-warm semantics. (AC4: ``/readyz`` itself is untouched.)
    - **warm + degraded / disk-low / backup-stale → ``"warn"`` (200)** — the
      server still serves; ``/readyz`` returns 503 for the degraded case but
      ``/status`` reports a serving-but-degraded 2xx.
    - **warm + healthy → ``"pass"`` (200)``.

    Every component probe degrades to ``warn`` rather than raising — a status
    endpoint must never 500. ``now`` is injectable for deterministic tests.
    """
    clock = time.time() if now is None else now
    t = _iso_now()
    checks: dict[str, list[dict[str, object]]] = {}

    # --- bootstrap mode → warn (server is serving stub responses) ---
    # onboarding-uplift-m4 F2: mirrors the /readyz bootstrap branch.
    # Returns "warn" (200) rather than "fail" (503) so operator dashboards
    # see "serving but degraded" — the server is up, just awaiting first ingest.
    if resources is not None and getattr(resources, "bootstrap_mode_active", False):
        uptime = max(0.0, clock - resources.process_start_time_seconds)
        checks["process:uptime"] = [
            {"componentType": "system", "observedValue": round(uptime, 1),
             "observedUnit": "s", "status": "pass", "time": t}
        ]
        return {
            "status": "warn",
            "http_code": 200,
            "checks": checks,
            "summary": "bootstrap | awaiting first ingest",
        }

    # --- not warm / pre-startup → fail (mirrors /readyz 503-before-warm) ---
    if resources is None or not resources.warm:
        for comp, ctype in (("embedder", "component"), ("lancedb", "datastore")):
            warm = bool(resources and resources.is_resource_warm(comp))
            checks[f"{comp}:status"] = [
                {"componentType": ctype, "status": "pass" if warm else "fail",
                 "time": t}
            ]
        uptime = max(
            0.0, clock - resources.process_start_time_seconds
        ) if resources is not None else 0.0
        checks["process:uptime"] = [
            {"componentType": "system", "observedValue": round(uptime, 1),
             "observedUnit": "s", "status": "pass", "time": t}
        ]
        return {
            "status": "fail",
            "http_code": 503,
            "checks": checks,
            "summary": "DOWN | server warming up",
        }

    # --- warm path --------------------------------------------------------
    degraded = resources.degraded is not None

    checks["embedder:status"] = [
        {"componentType": "component", "status": "pass", "time": t}
    ]
    lancedb_check: dict[str, object] = {
        "componentType": "datastore", "status": "pass", "time": t,
    }
    if degraded:
        lancedb_check["status"] = "warn"
        lancedb_check["output"] = (
            f"fallback_version={resources.degraded.fallback_version}"
        )
    checks["lancedb:status"] = [lancedb_check]

    checks["corpus:version"] = [
        {"componentType": "datastore",
         "observedValue": resources.corpus_info.version,
         "observedUnit": "version", "status": "pass", "time": t}
    ]

    # notebook count — degrade to warn (never 500) if the store is absent or
    # the query fails.
    nb_count: int | None = None
    nb_status = "pass"
    if store is not None:
        try:
            nb_count = len(await store.list_notebooks())
        except Exception:  # noqa: BLE001 — operability probe, must not 500
            # m4 rect F1: must NOT 500 here, but DO leave a breadcrumb — a
            # genuine store-layer regression would otherwise render as a
            # permanent silent warn/null-count with no way to debug. (A real
            # store failure is a standing condition, so the 10s poll
            # re-logging it is acceptable signal, not spam.)
            logger.warning(
                "/status notebook-store probe failed; reporting warn",
                exc_info=True,
            )
            nb_status = "warn"
    else:
        nb_status = "warn"
    checks["notebooks:count"] = [
        {"componentType": "datastore", "observedValue": nb_count,
         "observedUnit": "notebooks", "status": nb_status, "time": t}
    ]

    # disk utilization (warn when free < the ingest-pause threshold).
    disk_warn = False
    try:
        import shutil  # noqa: PLC0415

        usage = shutil.disk_usage(str(resources.config.data_dir))
        pct = round(100.0 * usage.used / usage.total, 1) if usage.total else 0.0
        disk_warn = usage.free < DISK_PAUSE_THRESHOLD_BYTES
        disk_check: dict[str, object] = {
            "componentType": "system", "observedValue": pct,
            "observedUnit": "percent",
            "status": "warn" if disk_warn else "pass", "time": t,
        }
        if disk_warn:
            disk_check["output"] = (
                f"free={usage.free // 1024**3}GB < "
                f"{DISK_PAUSE_THRESHOLD_BYTES // 1024**3}GB threshold"
            )
    except OSError:
        disk_warn = True
        disk_check = {"componentType": "system", "status": "warn",
                      "output": "disk_usage failed", "time": t}
    checks["disk:utilization"] = [disk_check]

    # last-backup recency. Read finished_at defensively; absent or >25h → warn.
    # backup-status.json carries both ``status`` (overall run outcome) and
    # ``backup_status`` (backup phase) keys.
    #
    # chris-dare-dev/arXMCP#203 — recency is gated on ``status`` FIRST. This
    # check used to trust ``finished_at`` on its own, and the wrapper stamps
    # that field on every run that reaches the end, success or not. So a run
    # of failing backups kept ``backup:time`` reporting pass, exactly like
    # the /metrics freshness gauge did. Both consumers now share one
    # verdict: only a state in FRESHNESS_ADVANCING_STATES counts as a
    # backup having happened.
    backup_warn = False
    backup_check: dict[str, object] = {
        "componentType": "system", "status": "pass", "time": t,
    }
    try:
        from datetime import datetime  # noqa: PLC0415

        backup_path = Path(resources.config.ops_dir) / _BACKUP_STATUS_NAME
        payload: object = None
        if backup_path.is_file():
            raw = _read_capped(backup_path)
            payload = json.loads(raw) if raw else None
        backup_state = None
        last_success = None
        if isinstance(payload, dict):
            backup_state = classify_backup_state(payload.get("status"))
            # The same resolver /metrics uses, so ``backup:time`` and
            # ``arxmcp_backup_last_success_timestamp_seconds`` cannot report
            # different last-good times. ``last_success_at`` is carried
            # forward by the wrapper, so this stays meaningful across a
            # restart taken while the latest run was failed / partial.
            last_success = _last_success_stamp(payload, backup_state)

        def _age_hours(stamp: str) -> int:
            return int(
                max(0.0, clock - datetime.fromisoformat(stamp).timestamp())
                // 3600
            )

        if backup_state is not None and not advances_freshness(backup_state):
            # chris-dare-dev/arXMCP#203 — the latest run did not succeed, so
            # warn no matter how fresh the last GOOD backup is. What changed
            # with the carried field is only what we can SAY about it: the
            # true last-good timestamp instead of nothing.
            backup_warn = True
            backup_check["status"] = "warn"
            detail = (
                "no successful backup on record"
                if last_success is None
                else f"last success {_age_hours(last_success)}h ago"
            )
            if last_success is not None:
                backup_check["observedValue"] = last_success
            backup_check["output"] = (
                f"last backup run did not succeed "
                f"(status={backup_state}); {detail}"
            )
        elif last_success is None:
            backup_warn = True
            backup_check["status"] = "warn"
            backup_check["output"] = "no backup recorded"
        else:
            backup_check["observedValue"] = last_success
            age = clock - datetime.fromisoformat(last_success).timestamp()
            if age > _BACKUP_STALE_SECONDS:
                backup_warn = True
                backup_check["status"] = "warn"
                backup_check["output"] = (
                    f"last backup {int(age // 3600)}h ago (> 25h)"
                )
    except (OSError, ValueError, json.JSONDecodeError):
        backup_warn = True
        backup_check["status"] = "warn"
        backup_check["output"] = "backup-status.json unreadable"
    checks["backup:time"] = [backup_check]

    uptime = max(0.0, clock - resources.process_start_time_seconds)
    checks["process:uptime"] = [
        {"componentType": "system", "observedValue": round(uptime, 1),
         "observedUnit": "s", "status": "pass", "time": t}
    ]

    any_warn = degraded or disk_warn or backup_warn or nb_status == "warn"
    status = "warn" if any_warn else "pass"
    label = {"pass": "READY", "warn": "DEGRADED"}[status]
    nb_text = "?" if nb_count is None else nb_count
    summary = (
        f"{label} | corpus v{resources.corpus_info.version} | "
        f"{nb_text} notebooks" + (" | degraded" if degraded else "")
    )
    return {
        "status": status,
        "http_code": 200,
        "checks": checks,
        "summary": summary,
    }


@router.get("/status")
async def status_endpoint(request: Request) -> Response:
    """Operability snapshot as IETF ``application/health+json``
    (notebook-ops-hardening-m4).

    A SUPERSET of ``/readyz``: ``status: pass|warn|fail`` + per-component
    ``checks`` (embedder, lancedb, corpus:version, notebooks:count,
    disk:utilization, backup:time, process:uptime). HTTP 200 for ``pass`` and
    ``warn`` (serving, possibly degraded), 503 for ``fail`` (not warm). Unlike
    ``/readyz`` (which 503s on the degraded case), ``/status`` reports the
    degraded state as ``warn`` with a 200 so an operator/badge sees
    "serving-but-degraded" distinctly from "down". ``/readyz`` is unchanged.

    NOT an MCP tool — no tool-schema / BP1 impact. Consumed by ``make status``
    + the ``/ui/status-badge`` poll.
    """
    resources: Resources | None = getattr(request.app.state, "resources", None)
    store = getattr(request.app.state, "notebooks_store", None)
    report = await compute_health_status(resources, store)
    body = {
        "status": report["status"],
        "description": "arXMCP MCP server",
        "checks": report["checks"],
    }
    return JSONResponse(
        status_code=int(report["http_code"]),  # type: ignore[call-overload]
        content=body,
        media_type="application/health+json",
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
    # onboarding-uplift-m4 F1: in bootstrap mode corpus_info is None.
    # Skip the corpus_info gauges — Prometheus reports them as absent,
    # which is correct for bootstrap mode. Mirror the getattr defense
    # at line 538 (startup_unindexed_rows) for the corpus_info reads.
    if resources.corpus_info is not None:
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
    # corpus-integrity-observability-m3: O(1) read of the startup-cached
    # unindexed-rows tripwire (NEVER re-queries index_stats here — the
    # "computed once at startup" contract). getattr-defended for a partial /
    # duck-typed Resources (mirrors the chunk-count reads above).
    CORPUS_UNINDEXED_ROWS.set(getattr(resources, "startup_unindexed_rows", -1))
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

    # lean-repl-observability-m1: refresh the Lean REPL telemetry gauges
    # (env-snapshot proxy + worker age). Cheap (two property reads); a
    # disabled/absent REPL (getattr -> None) explicitly zeroes both gauges.
    from server.metrics import refresh_lean_repl_metrics

    refresh_lean_repl_metrics(getattr(resources, "lean_repl", None))

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
    - ``backup-status.json`` — JSON ``{"status":
      "ok"|"partial"|"failed"|"running", "finished_at": <iso8601>,
      "last_success_at": <iso8601>|null}``. ``status`` drives exclusive
      1.0 on :data:`BACKUP_STATUS_GAUGE{state}`;
      :data:`BACKUP_LAST_SUCCESS_GAUGE` is set from whichever timestamp
      :func:`_last_success_stamp` resolves — ``last_success_at``, which
      the wrapper carries forward across runs, else ``finished_at`` on a
      run that actually succeeded.
    - ``eval-reports/corpus_v<N>-*.json`` — the watchdog's per-corpus-
      version nDCG@5 reports. The N most-recent reports drive
      :data:`EVAL_NDCG5_GAUGE`; older labels are evicted from the
      gauge to bound cardinality.

    Per-file errors are isolated: malformed JSON in one file does NOT
    prevent the others from being refreshed. "Malformed" includes JSON
    that parses cleanly but is not the shape the reader expects — a
    top-level array where an object is required, or an object whose
    count field is not a number. Both are unusable sentinels, and every
    unusable sentinel on this path takes the same route: log a WARNING
    and LEAVE the prior gauge values. It never zeroes them; a zero is a
    positive claim ("no backup has ever succeeded", "nothing was ever
    ingested") that an unreadable file is not evidence for. Only a
    genuinely ABSENT sentinel zeroes its gauges.
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
            # The guard is ``isinstance(payload, dict)``, NOT
            # ``payload is not None``. Every field read below goes through
            # ``.get``, which only a mapping has — a sentinel whose body is
            # valid JSON of the wrong SHAPE (a top-level array, string,
            # number or bool) raised ``AttributeError`` here, and that is
            # not in the ``except`` tuple below, so it escaped the reader
            # and 500'd the whole /metrics scrape. Every other gauge in
            # this function went dark with it. ``compute_health_status``
            # has always guarded this way for the /status consumer; the
            # two readers now agree on what an unusable sentinel is.
            if isinstance(payload, dict):
                # chris-dare-dev/arXMCP#203 — CLASSIFY THE RUN FIRST, then
                # decide whether it may touch the freshness clock. This
                # block used to set BACKUP_LAST_SUCCESS_GAUGE from
                # ``finished_at`` BEFORE inspecting ``status`` at all, so a
                # FAILED run advanced ``last_success`` and suppressed
                # ArXMCPBackupStale — the alerting surface read healthy
                # exactly while backups were broken. Order is load-bearing;
                # do not hoist the ``finished_at`` read back above this.
                raw_state = payload.get("status")
                # F4 rectification — unknown / corrupted / future state
                # strings light up the ``unknown`` cell instead of silently
                # zeroing every state. Operators wiring
                # ``arxmcp_backup_status{state="failed"}`` alerts would
                # otherwise miss a regression to an emit-mismatched-string
                # wrapper bug (which is precisely what #202 was).
                bucket = classify_backup_state(raw_state)
                if bucket == BACKUP_STATE_UNKNOWN:
                    logger.warning(
                        "backup-status.json at %s reports unknown state "
                        "%r; routing to arxmcp_backup_status{state=\"unknown\"}",
                        backup_status,
                        raw_state,
                    )
                for s in _BACKUP_STATES:
                    BACKUP_STATUS_GAUGE.labels(state=s).set(
                        1.0 if s == bucket else 0.0
                    )

                # Only a fully clean run advances the last-success clock.
                # A failed / partial / running / unknown run re-states the
                # timestamp the wrapper carried forward, so the age of the
                # last GOOD backup keeps growing and ArXMCPBackupStale can
                # fire — see :func:`_last_success_stamp` for why the carried
                # field is read WITHOUT gating on the current run's status,
                # and why ``finished_at`` still is gated.
                #
                # The gauge is never cleared here. A sentinel that names no
                # successful run at all leaves the prior value alone rather
                # than zeroing it: on this path a zero reads as "no backup
                # has ever succeeded", which is a stronger claim than the
                # sentinel supports.
                stamp = _last_success_stamp(payload, bucket)
                if stamp is not None:
                    from datetime import datetime  # noqa: PLC0415

                    BACKUP_LAST_SUCCESS_GAUGE.set(
                        datetime.fromisoformat(stamp).timestamp()
                    )
            elif raw is not None:
                # Parsed, but not an object. ``raw is None`` is excluded
                # because that is the oversized case, which _read_capped
                # has already logged — no duplicate line for it. Prior
                # gauge values are left alone, matching the malformed-JSON
                # path directly below: a zero here would assert "no backup
                # has ever succeeded", which an unreadable sentinel is not
                # evidence for.
                logger.warning(
                    "backup-status.json at %s is not a JSON object (got %s); "
                    "leaving prior gauge values",
                    backup_status,
                    type(payload).__name__,
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

    # --- ingest-summary.json → INGEST_LAST_RUN_* gauges ---------------
    # corpus-integrity-observability-e3: mirror the backup-status reader.
    from server.metrics import (  # noqa: PLC0415
        INGEST_LAST_RUN_CHUNKS,
        INGEST_LAST_RUN_PAPERS,
        INGEST_LAST_RUN_TIMESTAMP_SECONDS,
    )

    ingest_summary = ops_dir / _INGEST_SUMMARY_NAME
    if ingest_summary.is_file():
        try:
            raw = _read_capped(ingest_summary)
            payload = json.loads(raw) if raw is not None else None
            # Shape guard before any ``.get`` — see the identical note on
            # the backup-status reader above. This block mirrors that one,
            # so it inherited the same non-object-JSON crash.
            if isinstance(payload, dict):
                # FM-7: schema_version check FIRST — unknown version means
                # the reader cannot trust the field layout. Leave prior
                # gauges intact rather than zeroing (a zero reads as
                # "never ingested" which is worse than stale).
                if payload.get("schema_version") != 1:
                    logger.warning(
                        "ingest-summary.json at %s has unknown schema_version "
                        "%r; leaving prior gauge values",
                        ingest_summary,
                        payload.get("schema_version"),
                    )
                else:
                    # Coerce BOTH counts before setting EITHER gauge. Done
                    # inline, this reader set papers, then raised on a
                    # wrong-typed chunks value — leaving papers updated from
                    # a file it had just rejected, which is neither the new
                    # reading nor the prior one. "Leave the prior gauge
                    # values" has to mean all of them or it means nothing.
                    papers = float(payload.get("papers_processed", 0))
                    chunks = float(payload.get("chunks_written_this_run", 0))
                    INGEST_LAST_RUN_PAPERS.set(papers)
                    INGEST_LAST_RUN_CHUNKS.set(chunks)
                    finished_at = payload.get("finished_at")
                    if isinstance(finished_at, str) and finished_at:
                        from datetime import datetime  # noqa: PLC0415

                        INGEST_LAST_RUN_TIMESTAMP_SECONDS.set(
                            datetime.fromisoformat(finished_at).timestamp()
                        )
            elif raw is not None:
                logger.warning(
                    "ingest-summary.json at %s is not a JSON object (got %s); "
                    "leaving prior gauge values",
                    ingest_summary,
                    type(payload).__name__,
                )
        # ``TypeError`` covers a correctly-shaped object carrying a
        # wrong-TYPED count: ``float(None)`` and ``float([1, 2])`` raise it,
        # not ValueError, so ``{"schema_version": 1, "papers_processed":
        # null}`` escaped this handler the same way a top-level array
        # escaped the shape guard.
        except (json.JSONDecodeError, OSError, TypeError, ValueError, KeyError):
            logger.warning(
                "ingest-summary.json at %s is malformed; leaving prior gauge values",
                ingest_summary,
                exc_info=True,
            )
    else:
        INGEST_LAST_RUN_PAPERS.set(0.0)
        INGEST_LAST_RUN_CHUNKS.set(0.0)
        INGEST_LAST_RUN_TIMESTAMP_SECONDS.set(0.0)

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
    # The isinstance check above already made this reader safe against a
    # non-object body, but not against an object with a wrong-typed count:
    # ``float(None)`` and ``float([1, 2])`` raise TypeError, not ValueError,
    # so ``{"fixture_count": null}`` escaped instead of taking the
    # "non-numeric fixture_count -> 1.0 with a WARNING" row this function's
    # own docstring promises.
    except (json.JSONDecodeError, TypeError, ValueError):
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
            # Third instance of the non-object-JSON shape bug — the two
            # sentinel readers in refresh_sentinel_metrics guarded with
            # ``is not None``, this one had no guard at all. A report file
            # containing a top-level array reached ``.get`` and raised
            # ``AttributeError``, which this ``except`` does not name, so
            # it escaped _refresh_eval_ndcg5 AND its caller.
            if not isinstance(payload, dict):
                logger.warning(
                    "eval-report %s is not a JSON object (got %s); skipping",
                    report_path,
                    type(payload).__name__,
                )
                continue
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
    "CORPUS_UNINDEXED_ROWS",
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
