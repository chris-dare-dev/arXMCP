"""End-to-end retrieval-quality test for the eval harness (E05_S02).

Reads the curated query fixture (E05_S01), pins to the current
LanceDB corpus version, runs each query through the BGE-M3 query
encoder + dual-column ANN search (stmt + proof), merges and dedups
by chunk_id (MIN-distance per chunk_id), computes nDCG@5 and
Recall@10 against the ground-truth grades, and writes both per-query
JSONL and an aggregate JSON to ``var/arxmcp/ops/eval/``.

Fails when ``ndcg5_mean < --ndcg-min`` (default 0.70 — Tier-0 ANN-only
gate). The threshold is the Tier-0 → Tier-1 exit criterion per
E05_S03's ``TIER-GATES.md``.

**Cold-start behavior matrix (D1 from research-synthesis).**

==========================  =====  ============================
``read_corpus_version()``   N      Behavior
==========================  =====  ============================
``None`` (no marker)        0      ``pytest.skip("both pending")``
``None``                    20     ``pytest.skip("corpus not ingested")``
``CorpusVersionInfo``       0      ``pytest.skip("queries not curated")``
``CorpusVersionInfo``       20     RUN
==========================  =====  ============================

The test SKIPs (does not fail) on every cold-start cell — `make
test` must stay green on a fresh checkout. The Tier-0 exit gate
(E05_S03) is the layer that asserts the prerequisites are present
before this test runs.

**Output files (only written in the RUN cell).**

- ``var/arxmcp/ops/eval/results-<corpus_version>.jsonl`` — one JSON
  line per query: ``{ndcg5, query_id, query_text, recall10,
  retrieved_chunk_ids}``.
- ``var/arxmcp/ops/eval/aggregate-<corpus_version>.json`` — single
  JSON object: ``{corpus_version, ndcg5_mean, query_count,
  recall10_mean, timestamp}``. Atomic write via PID + UUID-suffix
  tmp + ``os.replace``. Drift-detection baseline for E11_S04.

**Why the test is in tests/eval/, not under tests/integration/.** The
brief deliberately puts it next to ``test_metrics.py`` so the metric
+ harness pair lives together. `make test` runs the full suite; the
skip-on-cold-start protocol keeps cycle time fast.

**See also.**

- ``tests/eval/metrics.py`` — pure ``ndcg_at_k`` / ``recall_at_k`` /
  ``assert_threshold`` (unit-tested in ``tests/eval/test_metrics.py``).
- ``server/query_encoder.py`` — async ``encode_query`` (E03_S03).
- ``server/corpus.py`` — ``open_chunks_table`` + ``read_corpus_version``
  (E04_S02 + E04_S03).
- ``tools/validate_eval_fixtures.py`` — fixture validator (E05_S01).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ingest.schema import EMBEDDING_COLUMN_NAMES
from tests.eval.metrics import (
    _mean,
    assert_threshold,
    ndcg_at_k,
    recall_at_k,
)

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: The committed fixture path. Points at the same file the validator
#: reads (E05_S01); we do NOT re-validate here — the validator runs in
#: ``make test`` already.
FIXTURE_PATH = REPO_ROOT / "tests" / "eval" / "fixtures" / "queries.json"

#: Per-run output directory under ``var/``. Created on first write.
EVAL_OPS_DIR = REPO_ROOT / "var" / "arxmcp" / "ops" / "eval"

#: Per-column top-k for the dual ANN. Brief: "two ANN queries are
#: issued (one per column), top-k results are merged and sorted by
#: score, deduped by chunk_id, and the top 10 are taken."
PER_COLUMN_TOP_K = 10

#: Final cutoff (after dedup) used for both Recall@k and the
#: retrieved-chunk-ids written to the per-query JSONL.
FINAL_TOP_K = 10

#: Cutoff for nDCG.
NDCG_K = 5

#: The two embedding columns to search. Imported from
#: :data:`ingest.schema.EMBEDDING_COLUMN_NAMES` per F3 of the E05_S02
#: critique — the column-name strings live in exactly one place
#: (single-source-of-truth: a future schema rename touches one constant).
EMBEDDING_COLUMNS = EMBEDDING_COLUMN_NAMES


# ---------------------------------------------------------------------------
# The retrieval-quality test
# ---------------------------------------------------------------------------


#: AC #4 latency budget for the full pipeline at k=10. Brief verbatim:
#: "Latency p95 for the full pipeline (with rerank if enabled) is
#: ≤ 2 seconds at k=10 on the seed corpus." Asserted on top of the
#: nDCG threshold in the hybrid branch.
LATENCY_P95_MAX_SECONDS: float = 2.0


@pytest.mark.eval
def test_retrieval_quality(
    ndcg_min: float,
    hybrid: bool,
    rerank: bool,
) -> None:
    """Top-level eval harness — see module docstring for the behavior
    matrix.

    The body is split into helpers:
    - :func:`_run_queries_against_corpus` runs the dense-only ANN loop
      (the original E05_S02 path; default).
    - :func:`_run_hybrid_against_corpus` runs the FULL 3-phase
      pipeline (BM25 → ANN+RRF → optional Rerank) when ``--hybrid``
      is passed (E07_S04). Records per-phase latency for the
      ``LATENCY_P95_MAX_SECONDS`` AC.
    - :func:`score_and_write` consumes per-query rows and writes the
      result files.

    The split is per F4 of the E05_S02 critique: ``score_and_write``
    is unit-tested in :mod:`tests.eval.test_metrics` against
    synthetic per-query rows so the threshold-failure path has a
    real regression guard.

    **E07_S04: ``@pytest.mark.eval``** registered in ``pyproject.toml``.
    Allows ``pytest -m "not eval"`` opt-in exclusion. The default test
    run does NOT exclude — the cold-start matrix is the load-bearing
    skip mechanism (see synthesis D4).
    """
    # --- Cold-start gate -------------------------------------------------
    # Import deferred so a fully-cold dev box (no LanceDB installed)
    # does not import-error here. Skipping is the right signal.
    try:
        from server.corpus import open_chunks_table, read_corpus_version
        from server.query_encoder import encode_query
    except ImportError as exc:
        pytest.skip(
            f"server-side deps not importable ({exc}); "
            "the eval harness needs lancedb + transformers installed"
        )

    # Fixture must exist (E05_S01 ships an empty stub).
    if not FIXTURE_PATH.is_file():
        pytest.skip(
            f"fixture missing at {FIXTURE_PATH} (E05_S01 should have "
            "shipped a stub)"
        )
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    queries = fixture.get("queries", [])

    # Try to read the corpus marker; the matrix below uses (info, len)
    # to pick the correct skip / run branch.
    try:
        corpus_info = read_corpus_version()
    except ValueError as exc:
        # Corpus marker is present but malformed — do NOT skip; this
        # is an upstream bug the operator should see.
        pytest.fail(
            f"corpus-version.json is malformed: {exc}. Re-run the "
            f"ingestion driver to repair the marker."
        )

    if corpus_info is None and not queries:
        pytest.skip(
            "eval cold-start: no corpus marker AND queries.json is "
            "empty — both pending. See docs/eval-curation.md and run "
            "the ingestion driver."
        )
    if corpus_info is None:
        pytest.skip(
            f"corpus not ingested (no marker file); skipping the "
            f"{len(queries)}-query eval pass"
        )
    if not queries:
        pytest.skip(
            f"queries.json has zero entries — curation pending "
            f"(corpus is at version {corpus_info.version})"
        )

    # E07_S04 D5: --rerank requires the BGE-reranker model env-gate
    # (matches tests/retrieval/test_rerank.py:743-746). The 2.3 GB
    # model download is opt-in.
    if rerank and os.environ.get("ARXMCP_RUN_REAL_BGE_RERANKER") != "1":
        pytest.skip(
            "set ARXMCP_RUN_REAL_BGE_RERANKER=1 to exercise the "
            "BGE-reranker-v2-m3 model (~2.3 GB download) — same env-gate "
            "convention as tests/retrieval/test_rerank.py."
        )

    # --- RUN cell --------------------------------------------------------
    corpus_version = corpus_info.version
    tbl = open_chunks_table(version=corpus_version)

    if hybrid:
        # E07_S04: full BM25 → ANN+RRF → optional Rerank pipeline.
        per_query_rows = _run_hybrid_against_corpus(
            queries, tbl, encode_query,
            corpus_version=corpus_version,
            rerank_enabled=rerank,
        )
    else:
        # E05_S02 default: dense-only dual-column ANN.
        per_query_rows = _run_queries_against_corpus(
            queries, tbl, encode_query,
        )

    score_and_write(
        per_query_rows=per_query_rows,
        corpus_version=corpus_version,
        ndcg_min=ndcg_min,
        output_dir=EVAL_OPS_DIR,
        assert_latency_p95=hybrid,  # AC #4 only fires for hybrid paths
    )


# ---------------------------------------------------------------------------
# RUN-cell helpers (factored for unit-testability per F4)
# ---------------------------------------------------------------------------


def _run_queries_against_corpus(
    queries: list[dict],
    tbl,  # noqa: ANN001 — lancedb.table.Table; importing for typing pulls heavy deps
    encode_query,  # noqa: ANN001 — Awaitable[(str) -> np.ndarray]
) -> list[dict]:
    """Encode each query, run dual-column ANN, return per-query rows.

    Closes F2 from the E05_S02 critique: encode every query inside a
    SINGLE event loop rather than calling ``asyncio.run`` per query.
    The previous one-loop-per-query pattern leaked stale ``Future``
    objects into ``server.query_encoder._inflight`` (the singleflight
    cache) — when a second query had identical canonical text, the
    FAST PATH would await a Future bound to a closed loop and raise
    ``RuntimeError``. Single-loop-per-test eliminates the stale-Future
    surface entirely.

    Closes F7 from the E05_S02 critique: per-query KeyError now
    surfaces as a ``pytest.fail`` with a clear pointer to the
    fixture validator (E05_S01) rather than a naked traceback that
    leaves the operator guessing.
    """
    loop = asyncio.new_event_loop()
    try:
        per_query_rows: list[dict] = []
        for query_idx, query in enumerate(queries):
            try:
                query_id = query["query_id"]
                query_text = query["query_text"]
                ground_truth = {
                    entry["chunk_id"]: entry["relevance"]
                    for entry in query["relevant_chunks"]
                }
            except (KeyError, TypeError) as exc:
                pytest.fail(
                    f"queries[{query_idx}] is malformed ({exc!r}); run "
                    f"`python tools/validate_eval_fixtures.py` to "
                    f"diagnose. The eval harness trusts the fixture's "
                    f"shape and the validator is the safety net."
                )

            query_vec = loop.run_until_complete(encode_query(query_text))

            # Dual-column ANN: one search per embedding column.
            # MIN-distance per chunk_id (D3 of synthesis), sorted
            # ascending, top FINAL_TOP_K. In practice the schema
            # enforces exactly one of stmt/proof per row, so dedup is
            # rarely active — defense-in-depth.
            per_chunk_min_distance: dict[str, float] = {}
            for col in EMBEDDING_COLUMNS:
                arrow = (
                    tbl.search(query_vec, vector_column_name=col)
                    .limit(PER_COLUMN_TOP_K)
                    .to_arrow()
                )
                cids = arrow.column("chunk_id").to_pylist()
                distances = arrow.column("_distance").to_pylist()
                for cid, dist in zip(cids, distances, strict=True):
                    if cid is None or dist is None:
                        continue
                    prev = per_chunk_min_distance.get(cid)
                    if prev is None or dist < prev:
                        per_chunk_min_distance[cid] = dist

            ranked = sorted(
                per_chunk_min_distance.items(),
                key=lambda kv: kv[1],
            )
            retrieved_chunk_ids = [cid for cid, _ in ranked[:FINAL_TOP_K]]

            ndcg5 = ndcg_at_k(retrieved_chunk_ids, ground_truth, k=NDCG_K)
            recall10 = recall_at_k(
                retrieved_chunk_ids, ground_truth, k=FINAL_TOP_K
            )

            per_query_rows.append(
                {
                    "ndcg5": ndcg5,
                    "query_id": query_id,
                    "query_text": query_text,
                    "recall10": recall10,
                    "retrieved_chunk_ids": retrieved_chunk_ids,
                }
            )
        return per_query_rows
    finally:
        loop.close()


def _run_hybrid_against_corpus(
    queries: list[dict],
    tbl,  # noqa: ANN001
    encode_query,  # noqa: ANN001
    *,
    corpus_version: int,
    rerank_enabled: bool,
) -> list[dict]:
    """Run the full 3-phase hybrid pipeline (E07_S04).

    Per-query stages:
      1. BM25 (Phase 1, E07_S01) — top-200 candidates
      2. dual-ANN + RRF (Phase 2, E07_S02) — fuse with BM25 list,
         take top-50
      3. optional cross-encoder rerank (Phase 3, E07_S03) — top-K
         (here ``FINAL_TOP_K = 10``)

    Per the E07_S04 synthesis D1, this orchestrator lives in the
    eval test (NOT in `server/handlers/search.py`). The brief
    deliverables list omits handler modifications; E08 (agent
    runtime) will lift this into the handler when the live server
    serves hybrid retrieval.

    **Latency instrumentation (D6).** Records per-phase elapsed
    time per query: ``bm25_ms``, ``ann_ms``, ``rerank_ms``,
    ``total_ms``. Aggregated to p50 / p95 by :func:`score_and_write`.

    **Encode dedup (D8).** Calls ``encode_query`` once for the
    ``query_vec`` (passed to RerankPhase). ``ANNPhase.query`` ALSO
    calls ``encode_query`` internally — the singleflight in
    ``server.query_encoder`` collapses the duplicate to one forward
    pass.

    **Phantom-id contract.** Both ANN and Rerank tolerate phantom
    chunk_ids (E07_S02 F5, E07_S03 propagation). The eval doesn't
    inject phantoms but documents the tolerance for future
    maintainers.
    """
    import time as _time

    from server.config import Config
    from server.resources import Resources

    # Build a Resources instance once for the whole run. Per
    # synthesis D5 + D7, ``enable_rerank`` flag is passed to Config
    # so the on/off behavior is determined at construction. We
    # construct against the SAME corpus version the test pinned.
    # F5 fix from the E07_S04 critique: catch ``pydantic.ValidationError``
    # so an operator with stray ``ARXMCP_*`` env vars (e.g. an
    # ``ARXMCP_BIND_HOST=0.0.0.0`` in their ``.envrc``) sees a clear
    # diagnostic rather than a raw pydantic stack. The eval doesn't
    # need ``bind_host`` etc. — only ``enable_rerank`` matters — but
    # ``Config()`` reads ALL declared ARXMCP_* env vars at instantiation.
    try:
        cfg = Config(enable_rerank=rerank_enabled)
    except Exception as exc:
        pytest.fail(
            f"Eval harness Config() failed; an ARXMCP_* env var in your "
            f"shell may be invalid for the loopback / value-range "
            f"validators. Original error:\n  {exc}\n\n"
            f"To work around, unset the offending env var before running "
            f"the eval (only ARXMCP_RUN_REAL_BGE_RERANKER and "
            f"ARXMCP_LANCEDB_PATH are typically required)."
        )

    # F1 fix from the E07_S04 critique: explicit ``resources = None``
    # sentinel so the ``finally`` block can skip shutdown when startup
    # raised before binding the name. The previous broad
    # ``contextlib.suppress(NameError, Exception)`` masked
    # ``asyncio.TimeoutError`` and other shutdown failures.
    resources = None
    loop = asyncio.new_event_loop()
    try:
        # Resources.startup is async — drive on the same event loop
        # we use for query encoding.
        resources = loop.run_until_complete(Resources.startup(cfg))

        per_query_rows: list[dict] = []
        for query_idx, query in enumerate(queries):
            try:
                query_id = query["query_id"]
                query_text = query["query_text"]
                ground_truth = {
                    entry["chunk_id"]: entry["relevance"]
                    for entry in query["relevant_chunks"]
                }
            except (KeyError, TypeError) as exc:
                pytest.fail(
                    f"queries[{query_idx}] is malformed ({exc!r}); run "
                    f"`python tools/validate_eval_fixtures.py` to "
                    f"diagnose."
                )

            # ENCODE ONCE — used by RerankPhase. ANNPhase will encode
            # again internally; the query_encoder singleflight
            # collapses to one forward pass.
            t_total_start = _time.monotonic()
            query_vec = loop.run_until_complete(encode_query(query_text))

            # PHASE 1: BM25 (sync, fast).
            t_bm25_start = _time.monotonic()
            bm25_candidates, _filter_warnings = (
                resources.bm25_phase.query(query_text, top_n=200)
            )
            bm25_ms = (_time.monotonic() - t_bm25_start) * 1000.0

            # PHASE 2: dual-ANN + RRF.
            t_ann_start = _time.monotonic()
            fused = loop.run_until_complete(
                resources.ann_phase.query(
                    query_text, bm25_candidates, top_n=50,
                )
            )
            ann_ms = (_time.monotonic() - t_ann_start) * 1000.0

            # PHASE 3: optional cross-encoder rerank. The off-path is
            # a passthrough (synthesis D7); on-path scores all fused
            # candidates and re-orders by sigmoid(logit).
            t_rerank_start = _time.monotonic()
            ranked = loop.run_until_complete(
                resources.rerank_phase.rerank(
                    query_text, query_vec, fused, top_k=FINAL_TOP_K,
                )
            )
            rerank_ms = (_time.monotonic() - t_rerank_start) * 1000.0
            total_ms = (_time.monotonic() - t_total_start) * 1000.0

            retrieved_chunk_ids = [cid for cid, _score in ranked]
            ndcg5 = ndcg_at_k(retrieved_chunk_ids, ground_truth, k=NDCG_K)
            recall10 = recall_at_k(
                retrieved_chunk_ids, ground_truth, k=FINAL_TOP_K
            )

            per_query_rows.append(
                {
                    "ndcg5": ndcg5,
                    "query_id": query_id,
                    "query_text": query_text,
                    "recall10": recall10,
                    "retrieved_chunk_ids": retrieved_chunk_ids,
                    # Per-phase latency (E07_S04 D6). Floats; ms.
                    "bm25_ms": bm25_ms,
                    "ann_ms": ann_ms,
                    "rerank_ms": rerank_ms,
                    "total_ms": total_ms,
                    # Pipeline identity for the report.
                    "pipeline": (
                        "hybrid+rerank" if rerank_enabled else "hybrid"
                    ),
                }
            )
        return per_query_rows
    finally:
        # F1 fix: narrow the shutdown error path. Skip when
        # ``resources`` is unbound (startup raised); surface
        # ``TimeoutError`` as a warning (don't mask it as a silent
        # success). All other shutdown exceptions propagate so the
        # operator sees real cleanup failures. F9 fix: drop the
        # redundant ``NameError`` from the suppress list (handled
        # by the ``is not None`` guard above).
        if resources is not None:
            try:
                loop.run_until_complete(
                    asyncio.wait_for(resources.shutdown(), timeout=30.0)
                )
            except TimeoutError:
                # 30s drain budget exceeded — surface as a warning so
                # ops can investigate without failing the eval (the
                # query loop already finished).
                import warnings as _warnings  # noqa: PLC0415

                _warnings.warn(
                    "Resources.shutdown exceeded the 30s drain budget "
                    "during eval cleanup; the eval results are valid "
                    "but the next process may inherit half-released "
                    "handles.",
                    stacklevel=2,
                )
        # F6 fix: reset the query-encoder singleflight registry so a
        # downstream test in the same pytest session does not await a
        # stale future bound to this now-closed loop. Mirrors
        # tests/retrieval/test_ann.py:_reset_for_tests calls.
        try:
            from server import query_encoder as _qe  # noqa: PLC0415

            _qe._reset_for_tests()
        except ImportError:
            pass
        loop.close()


def score_and_write(
    per_query_rows: list[dict],
    corpus_version: int,
    ndcg_min: float,
    output_dir: Path,
    *,
    assert_latency_p95: bool = False,
) -> None:
    """Aggregate, write the result files, and assert the threshold.

    Factored out per F4 of the E05_S02 critique so the AC2 path is
    unit-testable without a live corpus.
    :func:`tests.eval.test_metrics.TestScoreAndWrite` exercises this
    function with synthetic ``per_query_rows`` to confirm: (a) the
    JSONL + aggregate files land at the expected paths with the
    expected schema, and (b) ``ndcg5_mean < ndcg_min`` raises
    :class:`tests.eval.metrics.ThresholdNotMetError`.

    The aggregate file is the drift-detection baseline that E11_S04's
    watchdog will compare against on a schedule.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / f"results-{corpus_version}.jsonl"
    aggregate_path = output_dir / f"aggregate-{corpus_version}.json"

    ndcg5_mean = _mean(row["ndcg5"] for row in per_query_rows)
    recall10_mean = _mean(row["recall10"] for row in per_query_rows)

    # JSONL: write-once per corpus_version (truncate-write); the filename
    # embeds the version so re-runs with the same version overwrite
    # cleanly. NOT append-mode — the store-stats / bm25-stats append
    # discipline is for monotonic ops logs, not per-corpus-version
    # baselines. (Closes F5 from the E05_S02 critique — the original
    # comment misnamed this as append-mode.)
    with results_path.open("w", encoding="utf-8") as fh:
        for row in per_query_rows:
            fh.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            )

    aggregate: dict = {
        "corpus_version": corpus_version,
        "ndcg5_mean": ndcg5_mean,
        "query_count": len(per_query_rows),
        "recall10_mean": recall10_mean,
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    # E07_S04 D6: latency aggregates (only present when the hybrid
    # path ran — dense-only rows have no per-phase keys). The
    # ``total_ms`` percentile is the AC #4 budget surface.
    has_latency = bool(per_query_rows) and "total_ms" in per_query_rows[0]
    if has_latency:
        latency_keys = ("bm25_ms", "ann_ms", "rerank_ms", "total_ms")
        latency_aggregate: dict = {}
        for key in latency_keys:
            values = [row[key] for row in per_query_rows if key in row]
            if not values:
                continue
            latency_aggregate[key] = {
                "p50": _percentile(values, 50),
                "p95": _percentile(values, 95),
                "max": max(values),
            }
        aggregate["latency_ms"] = latency_aggregate
        aggregate["pipeline"] = per_query_rows[0].get("pipeline", "unknown")

    _atomic_write_text(
        aggregate_path,
        json.dumps(aggregate, ensure_ascii=False, sort_keys=True) + "\n",
    )

    # F8 fix from the E07_S04 critique: check latency BEFORE the nDCG
    # threshold so an operator triaging a failed gate sees BOTH
    # signals when both ACs are violated. The aggregate JSON has
    # already been written, so neither assertion blocks the diagnostic
    # baseline.
    latency_violation_msg: str | None = None
    if assert_latency_p95 and has_latency:
        total_p95_s = aggregate["latency_ms"]["total_ms"]["p95"] / 1000.0
        if total_p95_s > LATENCY_P95_MAX_SECONDS:
            latency_violation_msg = (
                f"E07_S04 AC #4 violated: total p95 latency "
                f"{total_p95_s:.3f}s exceeds budget "
                f"{LATENCY_P95_MAX_SECONDS:.1f}s at k={FINAL_TOP_K}. "
                f"Per-phase p95 (ms): "
                f"{aggregate['latency_ms']}. Either optimize the "
                f"slow phase or revisit the budget in "
                f"docs/retrieval-quality-report.md."
            )

    # AC1 / AC2: nDCG threshold gate. Catch the ThresholdNotMetError
    # so we can chain it with the latency violation if both fired.
    ndcg_violation: BaseException | None = None
    try:
        assert_threshold(ndcg5_mean=ndcg5_mean, ndcg_min=ndcg_min)
    except AssertionError as exc:
        ndcg_violation = exc

    if latency_violation_msg and ndcg_violation:
        raise AssertionError(
            f"BOTH ACs violated:\n  - {ndcg_violation}\n  - "
            f"{latency_violation_msg}"
        )
    if latency_violation_msg:
        raise AssertionError(latency_violation_msg)
    if ndcg_violation:
        raise ndcg_violation


def _percentile(values: list[float], pct: float) -> float:
    """Return the ``pct``-th percentile of ``values`` (linear
    interpolation between adjacent ranks). Pure-Python — avoids a
    numpy dep at the eval-aggregate layer.

    Matches the standard "linear" interpolation method used by
    ``numpy.percentile`` with default args; for ≤ 20-query eval
    sets the result is dominated by interpolation between two
    adjacent values."""
    if not values:
        raise ValueError("cannot compute percentile of empty sequence")
    if not 0 <= pct <= 100:
        raise ValueError(f"pct must be in [0, 100]; got {pct}")
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = rank - lo
    return float(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac)


# ---------------------------------------------------------------------------
# Atomic-write helper (canonical pattern from preamble._write_preamble_json)
# ---------------------------------------------------------------------------


def _atomic_write_text(out_path: Path, payload: str) -> None:
    """Atomically write UTF-8 ``payload`` to ``out_path``.

    PID + UUID-suffix tmp + ``os.replace`` + ``try/finally`` cleanup.
    Mirrors ``ingest.preamble._write_preamble_json`` and
    ``ingest.bm25_indexer._atomic_write_text``. The aggregate file
    is one row per ``corpus_version``; a partial write breaks
    E11_S04's drift-detection baseline.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(
        f"{out_path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    )
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, out_path)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
