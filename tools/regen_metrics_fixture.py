#!/usr/bin/env python3
"""Regenerate the ``tests/fixtures/metrics_sample.txt`` fixture.

F4 rectification (E14_S04 adversary critique): the original
fixture was hand-generated and had no regeneration path.
Future drift in metric family names (e.g. E10/E11 lands an
``arxmcp_ingest_papers_processed_total`` emitter) would leave
the fixture stale without any test failure.

Usage::

    uv run python -m tools.regen_metrics_fixture

The script populates the process-wide prometheus_client default
registry with synthetic samples matching the shape that
``tools/daily_metrics_report.py`` parses (all 7 tools, 3 cache
tiers, embed + rerank counters), calls ``generate_latest()``,
and writes the bytes to ``tests/fixtures/metrics_sample.txt``.

The companion test
``tests/test_daily_metrics_report.py::TestRegenFixture`` asserts
that running this script produces the same bytes as the
checked-in fixture. A metric family rename / addition that
breaks the synthetic-sample setup here will fail loudly in CI.

Run this script and re-commit the fixture whenever:

- A new metric family is added to ``server/observability/metrics.py``
  or ``server/metrics.py`` and the daily report should surface it.
- An existing metric family is renamed.
- A label name changes.
"""

from __future__ import annotations

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "metrics_sample.txt"

TOOLS = (
    "search_papers",
    "get_chunk",
    "find_equation",
    "get_definitions",
    "find_lemma_by_name",
    "get_paper",
    "cite_neighbors",
)
TIERS = ("1", "2", "3")
TIER_HITS = {"1": 820, "2": 75, "3": 40}
TIER_EVICT = {"1": 110, "2": 25, "3": 8}
TIER_BYTES = {"1": 2_400_000, "2": 4_200_000, "3": 1_100_000}
LATENCY_SAMPLES = (0.002, 0.008, 0.04, 0.09, 0.2, 0.45, 0.9, 1.8, 4.2)
RESULT_BYTES_SAMPLES = (512, 4096, 32768, 131072)


def populate_registry() -> None:
    """Mutate the prometheus_client default registry to match the
    fixture's contents. Idempotent on repeat calls (the counter +
    histogram increments stack on subsequent runs, so the function
    should be called from a fresh process)."""
    # Imports inside the function so a user reading this file
    # doesn't pay the prometheus_client import cost just to read
    # the docstring.
    from prometheus_client import generate_latest  # noqa: PLC0415

    # Touch the server modules so their metric families register.
    # Side-effect imports — intentional.
    import server.health  # noqa: F401, PLC0415
    import server.metrics  # noqa: F401, PLC0415
    import server.observability.metrics  # noqa: F401, PLC0415
    import server.observability.tracing  # noqa: F401, PLC0415
    from server.metrics import (  # noqa: PLC0415
        CACHE_BYTES_GAUGE,
        CACHE_EVICTIONS_COUNTER,
        CACHE_HITS_COUNTER,
        CACHE_LOOKUPS_COUNTER,
    )
    from server.observability.metrics import (  # noqa: PLC0415
        EMBED_CALLS_COUNTER,
        EMBED_LATENCY,
        REQUEST_COUNTER,
        REQUEST_INFLIGHT,
        REQUEST_LATENCY,
        RERANK_CALLS_COUNTER,
        RERANK_LATENCY,
        RESULT_BYTES,
    )

    for tool in TOOLS:
        for _ in range(100):
            REQUEST_COUNTER.labels(tool=tool, status="ok").inc()
        for _ in range(2):
            REQUEST_COUNTER.labels(tool=tool, status="error").inc()
        for sample in LATENCY_SAMPLES:
            REQUEST_LATENCY.labels(tool=tool).observe(sample)
        REQUEST_INFLIGHT.labels(tool=tool).set(0)
        for sz in RESULT_BYTES_SAMPLES:
            RESULT_BYTES.labels(tool=tool).observe(sz)

    for t in TIERS:
        CACHE_LOOKUPS_COUNTER.labels(tier=t).inc(1000)
        CACHE_HITS_COUNTER.labels(tier=t).inc(TIER_HITS[t])
        CACHE_EVICTIONS_COUNTER.labels(tier=t).inc(TIER_EVICT[t])
        CACHE_BYTES_GAUGE.labels(tier=t).set(TIER_BYTES[t])

    EMBED_CALLS_COUNTER.labels(model="bge-m3", outcome="ok").inc(420)
    EMBED_CALLS_COUNTER.labels(model="bge-m3", outcome="error").inc(1)
    for v in (0.012, 0.025, 0.06, 0.14, 0.32):
        EMBED_LATENCY.labels(model="bge-m3").observe(v)
    RERANK_CALLS_COUNTER.labels(model="bge-reranker-v2-m3", outcome="ok").inc(60)
    for v in (0.04, 0.09, 0.21):
        RERANK_LATENCY.labels(model="bge-reranker-v2-m3").observe(v)

    # No imports of `generate_latest` until we've staged the
    # registry; the caller invokes it.
    _ = generate_latest


def render_fixture_bytes() -> bytes:
    """Populate the registry and return the rendered exposition
    bytes. Side-effect: mutates the module-level prometheus_client
    default registry; call from a one-shot script process."""
    populate_registry()
    from prometheus_client import generate_latest  # noqa: PLC0415

    return generate_latest()


def main(argv: list[str] | None = None) -> int:
    body = render_fixture_bytes()
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_bytes(body)
    print(f"wrote {FIXTURE_PATH} ({len(body)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
