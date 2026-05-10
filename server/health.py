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

import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Gauge

if TYPE_CHECKING:
    from server.resources import Resources

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

    return JSONResponse(
        status_code=200,
        content={
            "status": "ready",
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
    "CORPUS_VERSION_GAUGE",
    "EMBED_SINGLEFLIGHT_DEDUP_COUNTER",
    "PROCESS_START_TIME_GAUGE",
    "RESOURCE_WARM_GAUGE",
    "healthz",
    "readyz",
    "refresh_metrics_from_singleton_state",
    "reset_metrics_for_tests",
    "router",
]


# Suppress unused-import warning — `time` is imported for future use
# (per-tool latency histograms in E06_S03 will need wall-clock).
_ = time
