"""Cache-specific Prometheus metrics (E08_S03).

The 3-tier retrieval cache (``server/cache.py``) emits four metric
families per tier, exposed at ``/metrics`` via the same default
single-process registry that ``server/health.py`` uses. Tier labels
are the strings ``"1"``, ``"2"``, ``"3"`` (string-typed so the
Prometheus label space stays consistent regardless of label-renderer
quirks).

**Naming convention** matches the project-wide pattern from
``server/health.py``: ``arxmcp_<subsystem>_<metric>_total`` for
counters, ``arxmcp_<subsystem>_<metric>`` for gauges. The four
metrics:

- ``arxmcp_cache_lookups_total{tier}`` — every ``RetrievalCache.lookup``
  call increments the per-tier counter for whichever tier was
  consulted (incremented on the lookup attempt, NOT the result —
  hits are tracked separately).
- ``arxmcp_cache_hits_total{tier}`` — increments on a cache hit
  (Tier-1 SQLite hit, Tier-2 FAISS-cosine ≥0.97 hit, Tier-3 LRU
  hit on the rerank-set key).
- ``arxmcp_cache_evictions_total{tier}`` — increments when an entry
  is evicted from a tier (LRU overflow, TTL expiry detected at
  read time, Tier-2 ring-buffer slot reuse).
- ``arxmcp_cache_bytes{tier}`` — gauge of approximate byte usage
  per tier. Tier-1 is the sum of payload byte lengths; Tier-2 is
  the FAISS index size estimate (`ntotal * dim * 4` bytes for
  ``IndexFlatIP``); Tier-3 is the sum of cached candidate-list
  byte lengths.

**Single-process registry.** Per ``server/health.py``: *"Default
single-process registry; multiprocess mode is explicitly NOT used
(the server is single-process by design)."* The cache metrics live
in the same registry so a single ``/metrics`` scrape returns the
union.

**Refresh hook.** Counters are incremented from inside the cache
on the data path. The Gauge (``arxmcp_cache_bytes``) is refreshed
at scrape time via :func:`refresh_cache_metrics`, called from
:func:`server.health.refresh_metrics_from_singleton_state`. This
mirrors the pattern used for ``EMBED_SINGLEFLIGHT_DEDUP_COUNTER``.

**Failure-mode discipline.** Per
``.claude/notes/07-multi-agent-caching.md``: *"Cache layer crash /
OOM → Fall through to recompute; log; alert. Caching is
performance, not correctness."* Metric increments are wrapped in
try/except inside the cache module so a Prometheus library issue
never propagates to a request handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import Counter, Gauge

if TYPE_CHECKING:
    from server.cache import RetrievalCache

# ---------------------------------------------------------------------------
# Cache metric definitions
# ---------------------------------------------------------------------------

#: Per-tier lookup counter. Incremented on every call to
#: ``RetrievalCache.lookup`` for whichever tiers were consulted
#: BEFORE the lookup terminated (a Tier-1 hit increments tier=1
#: only; a Tier-1 miss + Tier-2 hit increments tier=1 and tier=2).
CACHE_LOOKUPS_COUNTER: Counter = Counter(
    "arxmcp_cache_lookups_total",
    "Total number of cache lookups attempted, per tier. A Tier-1 "
    "hit increments tier=1 only; a Tier-1 miss followed by a "
    "Tier-2 lookup increments tier=1 and tier=2.",
    labelnames=["tier"],
)

#: Per-tier hit counter. Incremented when a tier returned a usable
#: payload (Tier-1 SQLite hit, Tier-2 ≥0.97 cosine hit, Tier-3 LRU
#: hit). Hits are a strict subset of lookups: a tier's hit count
#: must be ≤ its lookup count.
CACHE_HITS_COUNTER: Counter = Counter(
    "arxmcp_cache_hits_total",
    "Total number of cache hits, per tier. A hit means the tier "
    "returned a usable payload; the request handler can skip the "
    "downstream pipeline. hits_total{tier} <= lookups_total{tier}.",
    labelnames=["tier"],
)

#: Per-tier eviction counter. Incremented when an entry leaves a
#: tier (LRU overflow on Tier-1 / Tier-3, TTL expiry detected at
#: read time on any tier, Tier-2 ring-buffer slot reuse).
CACHE_EVICTIONS_COUNTER: Counter = Counter(
    "arxmcp_cache_evictions_total",
    "Total number of cache evictions, per tier. Includes LRU "
    "overflow, TTL expiry detected at read time, and Tier-2 "
    "ring-buffer rotation.",
    labelnames=["tier"],
)

#: Per-tier byte-usage gauge. Refreshed at scrape time from
#: :func:`refresh_cache_metrics`. Approximation only — Tier-1 sums
#: payload byte lengths, Tier-2 estimates FAISS index size, Tier-3
#: sums cached candidate-list byte lengths.
CACHE_BYTES_GAUGE: Gauge = Gauge(
    "arxmcp_cache_bytes",
    "Approximate byte usage per cache tier. Refreshed at scrape "
    "time (NOT continuously). Operational telemetry, not a hard "
    "limit.",
    labelnames=["tier"],
)

#: F11 fix from the E08_S03 critique: count cache-write skips for
#: payloads that are not JSON-serializable (e.g. a future tool emits
#: a Pydantic model or ``datetime`` that lands in ``structuredContent``).
#: Without this counter, the cache silently goes cold for such tools
#: and operators have no telemetry to debug from. Labelnames:
#: ``reason`` (currently only ``"non_serializable"``; future skip
#: reasons can extend the label space without bumping the metric
#: family name).
CACHE_PAYLOAD_SKIPS_COUNTER: Counter = Counter(
    "arxmcp_cache_payload_skips_total",
    "Total number of cache writes skipped because the payload could "
    "not be canonicalized (typically: non-JSON-serializable). When "
    "this rises above zero, a tool's structuredContent is causing "
    "silent cache cold-out — debug by running the tool and "
    "inspecting the WARNING log line that precedes each increment.",
    labelnames=["reason"],
)


# ---------------------------------------------------------------------------
# Tier label constants — string-typed so label space stays canonical
# ---------------------------------------------------------------------------

#: Allowed tier label values. Use these constants instead of bare
#: string literals at increment sites so a typo (``"tier1"`` vs
#: ``"1"``) is caught by import-time grep rather than producing a
#: silent second time series.
TIER_1: str = "1"
TIER_2: str = "2"
TIER_3: str = "3"

#: Pre-validated set used by :func:`refresh_cache_metrics` and tests
#: to check that any tier label being recorded is one of the three
#: known tiers.
ALL_TIERS: frozenset[str] = frozenset({TIER_1, TIER_2, TIER_3})


# ---------------------------------------------------------------------------
# Scrape-time refresh hook
# ---------------------------------------------------------------------------


def refresh_cache_metrics(cache: RetrievalCache | None) -> None:
    """Pull the cache singleton's per-tier byte-usage estimates into
    the Prometheus registry.

    Called from :func:`server.health.refresh_metrics_from_singleton_state`
    at scrape time so the gauges reflect the latest state. A ``None``
    cache (server still in startup or tests that did not initialize
    the cache singleton) is a no-op — the gauges retain their last
    observed value, which is the documented Prometheus behavior for
    unset gauges.

    The function is intentionally cheap (three integer sums); any
    cost would be borne on every Prometheus scrape, which can be
    several times per second in active operations.
    """
    if cache is None:
        return
    # Each .bytes_used() call is O(1) — the cache tracks the running
    # sum on insert/evict.
    CACHE_BYTES_GAUGE.labels(tier=TIER_1).set(cache.tier1_bytes_used())
    CACHE_BYTES_GAUGE.labels(tier=TIER_2).set(cache.tier2_bytes_used())
    CACHE_BYTES_GAUGE.labels(tier=TIER_3).set(cache.tier3_bytes_used())


def reset_cache_metrics_for_tests() -> None:
    """Test hook — reset every cache counter and gauge to zero.

    The Prometheus library does not expose a ``Counter.reset()`` so
    we work around it by re-setting the underlying ``_value`` to 0
    via the documented ``.collect()`` reflection path. This is a
    test-only escape hatch — production code paths must NEVER call
    this (counter monotonicity is a Prometheus contract).

    Mirrors :func:`server.health.reset_metrics_for_tests` discipline.
    """
    for tier in ALL_TIERS:
        # Counters: reset by accessing the underlying _value attribute.
        # This is private API but stable across prometheus_client 0.16+.
        CACHE_LOOKUPS_COUNTER.labels(tier=tier)._value.set(0)
        CACHE_HITS_COUNTER.labels(tier=tier)._value.set(0)
        CACHE_EVICTIONS_COUNTER.labels(tier=tier)._value.set(0)
        CACHE_BYTES_GAUGE.labels(tier=tier).set(0)
    # Reset the payload-skip counter for every reason label seen so far.
    for reason in ("non_serializable",):
        CACHE_PAYLOAD_SKIPS_COUNTER.labels(reason=reason)._value.set(0)


__all__ = [
    "ALL_TIERS",
    "CACHE_BYTES_GAUGE",
    "CACHE_EVICTIONS_COUNTER",
    "CACHE_HITS_COUNTER",
    "CACHE_LOOKUPS_COUNTER",
    "CACHE_PAYLOAD_SKIPS_COUNTER",
    "TIER_1",
    "TIER_2",
    "TIER_3",
    "refresh_cache_metrics",
    "reset_cache_metrics_for_tests",
]
