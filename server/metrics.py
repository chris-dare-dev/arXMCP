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
    from server.lean_repl import LeanRepl

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
# Retrieval-cap metric (E08_S04)
# ---------------------------------------------------------------------------

#: F9 fix from the E08_S04 critique: count RETRIEVAL_CAP_REACHED
#: rejections per tool. The cap middleware short-circuits BEFORE
#: FastMCP, so FastMCP-side per-tool counters do NOT see cap
#: rejections. Without this counter, operators can't tell how often
#: the caps fire — a key signal for tuning the limits.
RETRIEVAL_CAP_REJECTIONS_COUNTER: Counter = Counter(
    "arxmcp_retrieval_cap_rejections_total",
    "Total number of `tools/call` requests rejected by the per-MCP-"
    "session retrieval cap. Labeled by tool name (`search_papers` or "
    "`get_chunk`). When this rises, the configured caps may be too "
    "tight or an upstream agent may be in a runaway-retrieval loop.",
    labelnames=["tool"],
)


# ---------------------------------------------------------------------------
# LaTeXML drift detection (E10_S04)
# ---------------------------------------------------------------------------

#: Counter incremented by ``ops.drift_check`` whenever the daily
#: drift check detects that a fixture's freshly-rendered MathML does
#: NOT match the checked-in expected MathML. Drift signals that the
#: LaTeXML version (or its dependencies) has changed in a way that
#: produces different output bytes — which silently corrupts the
#: equation TED index because stored MathML trees are no longer
#: byte-comparable to freshly-rendered queries.
#:
#: **Cron-side audit counter.** Increments inside the
#: ``ops/drift_check`` cron process per drifted fixture. The
#: cron process exits after each run, so this counter never
#: surfaces at the server's ``/metrics`` — it exists to support
#: E10_S04's in-process tests and would be replaced by a
#: structured-log emission in a future refactor.
#:
#: **For server-side /metrics exposure, see
#: :data:`LATEXML_DRIFT_DETECTED_GAUGE` below.** That gauge is
#: rehydrated at scrape time from the cron's sentinel file
#: (``var/arxmcp/ops/drift-detected.flag``), which is the
#: cross-process signal channel.
LATEXML_DRIFT_DETECTED_COUNTER: Counter = Counter(
    "arxmcp_latexml_drift_detected_total",
    "Total number of fixture diffs that detected LaTeXML output "
    "drift since the cron process started. Each increment is one "
    "fixture whose freshly-rendered MathML differed from the "
    "checked-in expected baseline. Operators should re-run the "
    "extractor + indexer (see docs/ops/latexml-drift-runbook.md) "
    "and regenerate fixtures via `python -m ops.drift_check "
    "--update-fixtures` after confirming the LaTeXML upgrade is "
    "intentional.",
    labelnames=["fixture"],
)

#: E14_S01 server-side gauge — number of fixtures currently in
#: drift state. Rehydrated at ``/metrics`` scrape time by
#: :func:`server.health.refresh_sentinel_metrics` reading the
#: cron's sentinel file at ``var/arxmcp/ops/drift-detected.flag``.
#: Closes the E10_S04 F8 deferral: the cron process exits before
#: Prometheus can scrape it; the gauge bridges the
#: server-vs-cron process boundary via the sentinel file.
#: NOTE on the metric name: prometheus_client strips the conventional
#: ``_total`` suffix when assigning the time-series name, so the
#: Counter above registers as ``arxmcp_latexml_drift_detected`` in the
#: registry. We use ``arxmcp_latexml_drift_fixtures`` here to avoid the
#: collision (the alternative — registering the Gauge with the same
#: bare name as the Counter — raises ``ValueError`` at import).
LATEXML_DRIFT_DETECTED_GAUGE: Gauge = Gauge(
    "arxmcp_latexml_drift_fixtures",
    "Number of LaTeXML fixtures currently in drift state, "
    "rehydrated from var/arxmcp/ops/drift-detected.flag at "
    "scrape time. 0 means no drift; >0 means the operator "
    "should run the recovery procedure documented in "
    "docs/ops/latexml-drift-runbook.md.",
)

#: E11_S04 drift watchdog gauge — the latest nDCG@5 mean per
#: staging corpus version. Set by ``ops/watchdog_eval.run_watchdog``
#: in the watchdog's own process (a one-shot cron). E14_S01 closed
#: the cross-process exposure gap: the watchdog writes per-corpus-
#: version JSON reports to ``var/arxmcp/ops/eval-reports/`` and
#: the server's scrape-time hook
#: (:func:`server.health.refresh_sentinel_metrics`) reads the
#: N most-recent reports on every ``/metrics`` scrape and calls
#: ``EVAL_NDCG5_GAUGE.labels(corpus_version=N).set(ndcg5_mean)``.
#:
#: The scrape-time hook caps exposed labels at the 5 most-recent
#: corpus_versions (E14_S01 synthesis D6) to avoid Prometheus
#: high-cardinality drift.
EVAL_NDCG5_GAUGE: Gauge = Gauge(
    "arxmcp_eval_ndcg5",
    "Latest watchdog nDCG@5 measurement per staging corpus "
    "version. Rehydrated at /metrics scrape time from "
    "var/arxmcp/ops/eval-reports/corpus_v<N>-*.json by the "
    "scrape hook in server.health.refresh_sentinel_metrics. "
    "Capped at the 5 most-recent corpus versions to bound "
    "label cardinality.",
    labelnames=["corpus_version"],
)

#: E11_S04 watchdog quarantine flag — 1.0 when
#: ``var/arxmcp/ops/eval-quarantine.flag`` is present, 0.0 when
#: absent. The flag is the watchdog's refuse-to-promote signal
#: for E11_S05's cutover; exposing it as a gauge lets alert
#: rules fire on ``arxmcp_eval_quarantine_active > 0``.
EVAL_QUARANTINE_ACTIVE_GAUGE: Gauge = Gauge(
    "arxmcp_eval_quarantine_active",
    "1.0 when var/arxmcp/ops/eval-quarantine.flag is present "
    "(watchdog has detected a regression and refuses cutover); "
    "0.0 when absent. Rehydrated at /metrics scrape time.",
)

#: E11_S02 delta-loop timeout flag — 1.0 when
#: ``var/arxmcp/ops/delta-timeout.flag`` is present, 0.0 when
#: absent. The flag is written when a delta run exceeds its
#: 90-minute budget.
DELTA_TIMEOUT_ACTIVE_GAUGE: Gauge = Gauge(
    "arxmcp_delta_timeout_active",
    "1.0 when var/arxmcp/ops/delta-timeout.flag is present "
    "(last delta run exceeded the 90-minute budget); 0.0 when "
    "absent. Rehydrated at /metrics scrape time.",
)

#: E11_S05 backup last-success timestamp. Reads
#: ``var/arxmcp/ops/backup-status.json::finished_at`` (ISO-8601)
#: and exposes the Unix epoch. An alert rule of
#: ``now() - arxmcp_backup_last_success_timestamp_seconds > 86400``
#: fires when the nightly backup is more than a day late.
BACKUP_LAST_SUCCESS_GAUGE: Gauge = Gauge(
    "arxmcp_backup_last_success_timestamp_seconds",
    "Unix epoch of the last successful restic backup, "
    "rehydrated from var/arxmcp/ops/backup-status.json at "
    "/metrics scrape time. 0.0 when the sentinel is absent "
    "(no backup has run yet).",
)

#: E11_S05 backup status. Exactly one label is 1.0 at any time
#: (or all are 0.0 when the sentinel is absent). States mirror
#: the backup wrapper's emitted ``status`` field.
BACKUP_STATUS_GAUGE: Gauge = Gauge(
    "arxmcp_backup_status",
    "Most recent restic backup outcome, rehydrated from "
    "var/arxmcp/ops/backup-status.json at /metrics scrape "
    "time. Exclusive — exactly one state is 1.0 at a time. "
    "All zero means no backup has run yet.",
    labelnames=["state"],
)

#: corpus-integrity-observability-e3 — ingest last-run snapshot gauges.
#: Rehydrated from var/arxmcp/ops/ingest-summary.json at /metrics scrape time.
#: Unlabeled scalars (no {driver} label — only the most-recent run is
#: reflected; a labelled series would leave non-recent drivers frozen at
#: stale values; see spike-3 decision.md Decision 2).
INGEST_LAST_RUN_PAPERS: Gauge = Gauge(
    "arxmcp_ingest_last_run_papers",
    "Number of papers processed in the last ingest run, "
    "rehydrated from var/arxmcp/ops/ingest-summary.json at "
    "/metrics scrape time. 0.0 when the sentinel is absent.",
)

INGEST_LAST_RUN_CHUNKS: Gauge = Gauge(
    "arxmcp_ingest_last_run_chunks",
    "Number of chunks written in the last ingest run, "
    "rehydrated from var/arxmcp/ops/ingest-summary.json at "
    "/metrics scrape time. 0.0 when the sentinel is absent.",
)

INGEST_LAST_RUN_TIMESTAMP_SECONDS: Gauge = Gauge(
    "arxmcp_ingest_last_run_timestamp_seconds",
    "Unix epoch of the last ingest run's finished_at, "
    "rehydrated from var/arxmcp/ops/ingest-summary.json at "
    "/metrics scrape time. 0.0 when the sentinel is absent "
    "(no ingest has run yet). Use now()-this > 86400 to alert "
    "on a stale ingest.",
)


# ---------------------------------------------------------------------------
# Lean REPL telemetry (lean-repl-observability-m1)
# ---------------------------------------------------------------------------

#: Proxy for the size of the running Lean REPL's append-only
#: environment-snapshot tree: the count of successful ``LeanRepl.query``
#: round-trips served by the CURRENT REPL instance. leanprover-community/repl
#: records one immutable snapshot per command and frees none until a
#: kill+respawn or an operator restart (F7 — see
#: ``.claude/docs/lean-sandbox-design.md`` § "Environment-snapshot
#: accumulation"). Refreshed at scrape time from
#: :func:`refresh_lean_repl_metrics`; reads 0 when the REPL is
#: disabled/absent and drops back toward 0 after a respawn mints a fresh
#: instance. Operational telemetry (watch the growth; restart between heavy
#: Mathlib-resident sessions) — NOT a hard limit.
LEAN_REPL_ENV_SNAPSHOTS_GAUGE: Gauge = Gauge(
    "arxmcp_lean_repl_env_snapshots",
    "Successful Lean REPL query round-trips served by the current REPL "
    "instance — a proxy for the size of the REPL's append-only "
    "environment-snapshot tree (one immutable snapshot per command; freed "
    "only by a respawn/restart). 0 when ARXMCP_ENABLE_LEAN is off/absent. "
    "Refreshed at scrape time, not continuously.",
)

#: Seconds since the running Lean REPL instance spawned. Refreshed at scrape
#: time; reads 0 when the REPL is disabled/absent and resets on a
#: kill+respawn. Pairs with the env-snapshots gauge: a long-lived REPL with a
#: high snapshot count is the F7 growth signal an operator acts on.
LEAN_REPL_AGE_SECONDS_GAUGE: Gauge = Gauge(
    "arxmcp_lean_repl_age_seconds",
    "Seconds since the current Lean REPL subprocess was spawned. 0 when "
    "ARXMCP_ENABLE_LEAN is off/absent; resets on a kill+respawn. Refreshed "
    "at scrape time.",
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


def refresh_lean_repl_metrics(lean_repl: LeanRepl | None) -> None:
    """Pull the Lean REPL harness's read-only telemetry into the Prometheus
    registry (lean-repl-observability-m1).

    Called from :func:`server.health.refresh_metrics_from_singleton_state`
    at scrape time. Unlike :func:`refresh_cache_metrics`, a ``None`` REPL
    (the ``ARXMCP_ENABLE_LEAN`` default-off / disabled path) EXPLICITLY sets
    both gauges to ``0.0`` rather than no-op'ing: the gauges are module-level
    and persist for the whole process, so a bare return would leave a stale
    nonzero value from a prior REPL generation (or a prior test). The
    disabled path must read a clean 0 — a present-and-zero series, never a
    stale "last observed" one.

    Cheap (two attribute reads); borne on every ``/metrics`` scrape.
    """
    if lean_repl is None:
        LEAN_REPL_ENV_SNAPSHOTS_GAUGE.set(0.0)
        LEAN_REPL_AGE_SECONDS_GAUGE.set(0.0)
        return
    LEAN_REPL_ENV_SNAPSHOTS_GAUGE.set(lean_repl.env_snapshot_count)
    LEAN_REPL_AGE_SECONDS_GAUGE.set(lean_repl.age_seconds)


def _reset_child(child: object) -> None:
    """Reset a Counter / Gauge / Histogram labelled child using the
    public :meth:`Counter.reset` API when available (prometheus_client
    ≥ 0.16; the project pins 0.25), falling back to the documented-
    private ``._value`` accessor only when the public hook is absent.
    F6 rectification from the E14_S01 adversary critique."""
    if hasattr(child, "reset"):
        child.reset()
        return
    if hasattr(child, "_value"):
        child._value.set(0)


def reset_cache_metrics_for_tests() -> None:
    """Test hook — reset every cache counter and gauge to zero.
    F6 rectification: prefer the public ``Counter.reset()``."""
    for tier in ALL_TIERS:
        _reset_child(CACHE_LOOKUPS_COUNTER.labels(tier=tier))
        _reset_child(CACHE_HITS_COUNTER.labels(tier=tier))
        _reset_child(CACHE_EVICTIONS_COUNTER.labels(tier=tier))
        CACHE_BYTES_GAUGE.labels(tier=tier).set(0)
    # Reset the payload-skip counter for every reason label seen so far.
    for reason in ("non_serializable",):
        _reset_child(CACHE_PAYLOAD_SKIPS_COUNTER.labels(reason=reason))
    # Reset the retrieval-cap rejections counter (E08_S04).
    for tool in ("search_papers", "get_chunk"):
        _reset_child(RETRIEVAL_CAP_REJECTIONS_COUNTER.labels(tool=tool))


def reset_drift_metrics_for_tests() -> None:
    """Reset the LaTeXML drift counter (per-fixture labels) and the
    E14_S01 cross-process gauge to zero.

    Both metrics coexist after E14_S01:

    - :data:`LATEXML_DRIFT_DETECTED_COUNTER` is the cron-side
      audit counter (E10_S04) — still imported and used by
      :mod:`ops.drift_check` and exercised by
      ``tests/test_drift_check.py``.
    - :data:`LATEXML_DRIFT_DETECTED_GAUGE` is the server-side
      scrape-time gauge that bridges the cron-vs-server process
      boundary via the sentinel file.
    """
    for child in list(LATEXML_DRIFT_DETECTED_COUNTER._metrics.values()):
        _reset_child(child)
    LATEXML_DRIFT_DETECTED_GAUGE.set(0)


def reset_eval_metrics_for_tests() -> None:
    """Reset the E11_S04 watchdog nDCG gauge for every
    corpus_version label seen so far. Test-only — same discipline
    as :func:`reset_drift_metrics_for_tests`."""
    for child in list(EVAL_NDCG5_GAUGE._metrics.values()):
        _reset_child(child)


def reset_sentinel_metrics_for_tests() -> None:
    """Reset the E14_S01 sentinel-source gauges (eval-quarantine,
    delta-timeout, backup-last-success, backup-status) and the
    corpus-integrity-observability-e3 ingest gauges. Mirrors
    the other reset_*_for_tests helpers; test-only."""
    EVAL_QUARANTINE_ACTIVE_GAUGE.set(0)
    DELTA_TIMEOUT_ACTIVE_GAUGE.set(0)
    BACKUP_LAST_SUCCESS_GAUGE.set(0)
    for child in list(BACKUP_STATUS_GAUGE._metrics.values()):
        _reset_child(child)
    INGEST_LAST_RUN_PAPERS.set(0)
    INGEST_LAST_RUN_CHUNKS.set(0)
    INGEST_LAST_RUN_TIMESTAMP_SECONDS.set(0)


def reset_lean_repl_metrics_for_tests() -> None:
    """Reset the lean-repl-observability-m1 gauges to zero. Test-only;
    the gauges are unlabeled, so a plain ``.set(0)`` each suffices."""
    LEAN_REPL_ENV_SNAPSHOTS_GAUGE.set(0)
    LEAN_REPL_AGE_SECONDS_GAUGE.set(0)


__all__ = [
    "ALL_TIERS",
    "BACKUP_LAST_SUCCESS_GAUGE",
    "BACKUP_STATUS_GAUGE",
    "CACHE_BYTES_GAUGE",
    "CACHE_EVICTIONS_COUNTER",
    "CACHE_HITS_COUNTER",
    "CACHE_LOOKUPS_COUNTER",
    "CACHE_PAYLOAD_SKIPS_COUNTER",
    "DELTA_TIMEOUT_ACTIVE_GAUGE",
    "EVAL_NDCG5_GAUGE",
    "EVAL_QUARANTINE_ACTIVE_GAUGE",
    "INGEST_LAST_RUN_CHUNKS",
    "INGEST_LAST_RUN_PAPERS",
    "INGEST_LAST_RUN_TIMESTAMP_SECONDS",
    "LATEXML_DRIFT_DETECTED_COUNTER",
    "LATEXML_DRIFT_DETECTED_GAUGE",
    "LEAN_REPL_AGE_SECONDS_GAUGE",
    "LEAN_REPL_ENV_SNAPSHOTS_GAUGE",
    "RETRIEVAL_CAP_REJECTIONS_COUNTER",
    "TIER_1",
    "TIER_2",
    "TIER_3",
    "refresh_cache_metrics",
    "refresh_lean_repl_metrics",
    "reset_cache_metrics_for_tests",
    "reset_drift_metrics_for_tests",
    "reset_eval_metrics_for_tests",
    "reset_lean_repl_metrics_for_tests",
    "reset_sentinel_metrics_for_tests",
]
