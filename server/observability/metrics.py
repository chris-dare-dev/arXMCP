"""Per-tool request + embedder + reranker Prometheus metrics
(E14_S01).

These families fill the per-request observability gap that
`.claude/notes/08-security-observability-ops.md` § Metrics
documents. The cache + retrieval-cap + drift + eval gauges
already live in :mod:`server.metrics`; that placement is kept
for backwards compatibility with existing tests (E08_S03,
E10_S04, E11_S04 all import from there).

Wiring (per E14_S01 synthesis D3 + D4):

* Tool handlers — wrapped at registration time in
  :func:`server.tools.register_all` via a dispatcher-level
  closure that increments these counters around each call.
  No per-handler decorator scatter.
* Embedder (query path) — :mod:`server.query_encoder` imports
  :data:`EMBED_CALLS_COUNTER` + :data:`EMBED_LATENCY` and
  wraps the ``model(**encoded)`` forward pass.
* Reranker — :mod:`server.retrieval.rerank` imports
  :data:`RERANK_CALLS_COUNTER` + :data:`RERANK_LATENCY` and
  wraps the cross-encoder call.

**Histograms over Summaries.** Latency + result-bytes are
:class:`prometheus_client.Histogram` with explicit buckets
because histograms are aggregatable across replicas. Even on a
single-process deployment today, this matches future-proof
patterns and lets the operator compute quantiles in PromQL
without server-side state.

**Default registry.** All families are registered with the
process-wide ``prometheus_client.REGISTRY`` so they appear
automatically at ``GET /metrics`` (served via
``prometheus_client.make_asgi_app()`` mounted in
:mod:`server.main`).
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Per-tool request metrics
# ---------------------------------------------------------------------------

#: One increment per tool handler invocation. ``status`` is
#: ``"ok"`` when the handler returns normally and ``"error"``
#: when it raises. Closes design-note 08 §Metrics
#: ``arxmcp_request_total{tool, status}``.
REQUEST_COUNTER: Counter = Counter(
    "arxmcp_request_total",
    "Total tool handler invocations, partitioned by tool name "
    "and terminal status (ok / error). One increment per call; "
    "the wrapping logic in server.tools.register_all guarantees "
    "ok-or-error is always recorded via try/finally.",
    labelnames=["tool", "status"],
)

#: Per-call wall-clock latency in seconds. Histograms expose
#: ``_bucket{le=...}`` rollups; alerts use
#: ``histogram_quantile(0.99, ...)`` in PromQL.
#:
#: Buckets cover sub-millisecond cache hits up to multi-second
#: cold-start retrieval. The high-end bucket (5s) is the
#: ``ARXMCP_DEFAULT_TOOL_TIMEOUT_SECONDS`` ceiling — anything
#: slower than that is already a separate observability signal.
REQUEST_LATENCY: Histogram = Histogram(
    "arxmcp_request_latency_seconds",
    "Tool handler wall-clock latency in seconds, recorded for "
    "both ok and error outcomes. Latency timer starts before "
    "the handler runs and stops in the try/finally of "
    "server.tools._tracked_handler.",
    labelnames=["tool"],
    buckets=(
        0.001, 0.005, 0.01, 0.025, 0.05, 0.1,
        0.25, 0.5, 1.0, 2.5, 5.0,
    ),
)

#: In-flight gauge — incremented when a handler starts,
#: decremented when it returns. Lets operators see concurrent
#: tool calls per-handler. Backstop against runaway concurrency
#: on a single tool.
REQUEST_INFLIGHT: Gauge = Gauge(
    "arxmcp_request_inflight",
    "Number of concurrent in-flight tool handler invocations "
    "per tool. Incremented at handler entry, decremented in "
    "try/finally on return or raise.",
    labelnames=["tool"],
)

#: Result payload size in bytes, recorded post-handler from
#: ``len(json.dumps(result.structuredContent).encode())``. Only
#: recorded on the ``ok`` path; the error path is bypassed to
#: avoid serializing exception payloads.
#:
#: Buckets cover small structured results up to the
#: ``ARXMCP_RESULT_BYTE_CAP`` of 256 KB (E06_S04 D7). The cap
#: itself is a hard limit enforced by middleware; this metric
#: tracks the distribution below the cap.
RESULT_BYTES: Histogram = Histogram(
    "arxmcp_result_bytes",
    "Tool handler result payload size in bytes "
    "(structuredContent only, after JSON-serialization). "
    "Recorded only on the ok path. Buckets span small "
    "(1 KB) to result_byte_cap (256 KB by default).",
    labelnames=["tool"],
    buckets=(
        128, 256, 512, 1024, 2048, 4096, 8192,
        16384, 32768, 65536, 131072, 262144,
    ),
)


# ---------------------------------------------------------------------------
# Embedder (query-path) metrics
# ---------------------------------------------------------------------------

#: One increment per BGE-M3 query encode call.
#:
#: ``model`` is the embedder identity (currently ``"bge-m3"``;
#: future label values would surface a model upgrade).
#: ``outcome`` is ``"ok"`` or ``"error"`` — the singleflight
#: dedup path is tracked separately by
#: :data:`server.health.EMBED_SINGLEFLIGHT_DEDUP_COUNTER`, so
#: this counter records ACTUAL forward passes only.
EMBED_CALLS_COUNTER: Counter = Counter(
    "arxmcp_embed_calls_total",
    "Total query-encoding forward passes through the BGE-M3 "
    "model, labeled by model identity and ok/error outcome. "
    "Dedup'd singleflight hits are NOT counted here — see "
    "arxmcp_embed_singleflight_dedup_total for those.",
    labelnames=["model", "outcome"],
)

#: BGE-M3 forward-pass latency. Buckets target a CPU envelope
#: (5-500ms typical) with headroom for GPU (sub-10ms) and cold
#: model load (multi-second).
EMBED_LATENCY: Histogram = Histogram(
    "arxmcp_embed_latency_seconds",
    "Query-encoding BGE-M3 forward-pass latency in seconds. "
    "Excludes tokenization (negligible) and includes L2 "
    "normalization (negligible).",
    labelnames=["model"],
    buckets=(
        0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0,
    ),
)


# ---------------------------------------------------------------------------
# Reranker metrics
# ---------------------------------------------------------------------------

#: One increment per BGE-reranker-v2-m3 cross-encoder call.
#: ``outcome`` is ``"ok"`` or ``"error"``.
RERANK_CALLS_COUNTER: Counter = Counter(
    "arxmcp_rerank_calls_total",
    "Total cross-encoder rerank calls through "
    "BGE-reranker-v2-m3, labeled by model and ok/error "
    "outcome. Increment fires once per RerankPhase.rerank "
    "invocation (each invocation scores N candidates in a "
    "single batched forward pass).",
    labelnames=["model", "outcome"],
)

#: Reranker batch-forward-pass latency.
RERANK_LATENCY: Histogram = Histogram(
    "arxmcp_rerank_latency_seconds",
    "Reranker BGE-reranker-v2-m3 cross-encoder batch latency "
    "in seconds. Captures one batched forward pass per "
    "rerank invocation (N query-document pairs at once).",
    labelnames=["model"],
    buckets=(
        0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0,
    ),
)


# ---------------------------------------------------------------------------
# Test-only reset helpers (mirror server.metrics conventions)
# ---------------------------------------------------------------------------


def _reset_metric_child(child: object) -> None:
    """Reset a single Counter / Gauge / Histogram labelled child to
    its zero state. Prefers the public :meth:`Counter.reset` API
    (available on ``prometheus_client>=0.16``; the project pins
    ``0.25``) and falls back to the documented-private
    ``._value.set(0)`` accessor only for label spaces that the
    public API does not cover. Closes F6 from the E14_S01
    adversary critique (Counter-monotonicity violation in tests).
    """
    if hasattr(child, "reset"):
        child.reset()
        return
    # Histogram bucket fallback (older prometheus_client builds).
    for bucket in getattr(child, "_buckets", ()):
        bucket.set(0)
    if hasattr(child, "_sum"):
        child._sum.set(0)
    if hasattr(child, "_value"):
        child._value.set(0)


# ---------------------------------------------------------------------------
# E14_S05 — failure-mode + disk-full gauges + hosted-embed fallback counter
# ---------------------------------------------------------------------------

#: Free bytes on the arXMCP data filesystem. Refreshed at scrape
#: time by ``server.health.refresh_metrics_from_singleton_state``
#: via ``shutil.disk_usage(config.data_dir)``. Used by the
#: ``ArXMCPDiskFull`` Prometheus alert (E14_S05 D4 + D7) and as the
#: signal for writing the ``ingest-paused`` sentinel.
DISK_FREE_BYTES: Gauge = Gauge(
    "arxmcp_disk_free_bytes",
    "Free bytes on the arXMCP data filesystem. Refreshed at "
    "every /metrics scrape via shutil.disk_usage(); the "
    "ingest-paused sentinel is written at <10 GB free and "
    "cleared at >15 GB free (hysteresis).",
    labelnames=["path"],
)

#: 1.0 when the server is running in a degraded mode (failure-mode
#: fallback active); 0.0 otherwise. The ``reason`` label carries
#: the specific cause: ``corpus_corruption`` (LanceDB N-1
#: fallback), ``hosted_embedder_outage`` (Voyage stub fell back to
#: local BGE-M3), etc. E14_S05 D2 + D6.
DEGRADED_MODE_ACTIVE: Gauge = Gauge(
    "arxmcp_degraded_mode_active",
    "1.0 when the server is running in a degraded mode; 0.0 "
    "otherwise. The `reason` label carries the specific cause "
    "(corpus_corruption / hosted_embedder_outage / ...). Surfaces "
    "the failure-mode fallback state to Prometheus + Phoenix.",
    labelnames=["reason"],
)

#: Counter of hosted-embedder fallback events per provider. Fires
#: once per request that hit the fallback path (NOT once per call
#: site within the request). The metric is the operator-facing
#: signal that the hosted provider is having an outage. E14_S05 D6.
HOSTED_EMBED_FALLBACK_COUNTER: Counter = Counter(
    "arxmcp_hosted_embed_fallback_total",
    "Total number of query-embed requests that fell back from "
    "the configured hosted provider to the local BGE-M3 path. "
    "Labeled by provider (the one that failed); rising values "
    "indicate a hosted-provider outage.",
    labelnames=["provider"],
)


def reset_failure_mode_metrics_for_tests() -> None:
    """Reset the E14_S05 failure-mode metric families. Test-only;
    mirrors the other reset_*_for_tests helpers."""
    for child in list(DISK_FREE_BYTES._metrics.values()):
        child._value.set(0)
    for child in list(DEGRADED_MODE_ACTIVE._metrics.values()):
        child._value.set(0)
    for child in list(HOSTED_EMBED_FALLBACK_COUNTER._metrics.values()):
        if hasattr(child, "reset"):
            child.reset()


def reset_request_metrics_for_tests() -> None:
    """Reset every request-level Counter/Histogram/Gauge to zero.

    Test-only escape hatch — never call from production paths.
    Uses :func:`_reset_metric_child` which prefers the public
    :meth:`Counter.reset` API.
    """
    for family in (REQUEST_COUNTER, REQUEST_INFLIGHT, REQUEST_LATENCY, RESULT_BYTES):
        for child in list(family._metrics.values()):
            _reset_metric_child(child)


def reset_embed_metrics_for_tests() -> None:
    """Reset embedder query-path counters/histograms."""
    for family in (EMBED_CALLS_COUNTER, EMBED_LATENCY):
        for child in list(family._metrics.values()):
            _reset_metric_child(child)


def reset_rerank_metrics_for_tests() -> None:
    """Reset reranker counters/histograms."""
    for family in (RERANK_CALLS_COUNTER, RERANK_LATENCY):
        for child in list(family._metrics.values()):
            _reset_metric_child(child)


__all__ = [
    "DEGRADED_MODE_ACTIVE",
    "DISK_FREE_BYTES",
    "EMBED_CALLS_COUNTER",
    "EMBED_LATENCY",
    "HOSTED_EMBED_FALLBACK_COUNTER",
    "RERANK_CALLS_COUNTER",
    "RERANK_LATENCY",
    "REQUEST_COUNTER",
    "REQUEST_INFLIGHT",
    "REQUEST_LATENCY",
    "RESULT_BYTES",
    "reset_embed_metrics_for_tests",
    "reset_failure_mode_metrics_for_tests",
    "reset_rerank_metrics_for_tests",
    "reset_request_metrics_for_tests",
]
