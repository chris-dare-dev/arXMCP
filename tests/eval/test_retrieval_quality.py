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


def test_retrieval_quality(ndcg_min: float) -> None:
    """Top-level eval harness — see module docstring for the behavior
    matrix.

    The body is split into two helpers: :func:`_run_queries_against_corpus`
    runs the ANN loop (the data-blocked path that needs the live
    encoder + LanceDB), and :func:`score_and_write` consumes the
    per-query rows and writes the result files. The split is mainly
    for F4 of the E05_S02 critique: ``score_and_write`` is unit-tested
    in :mod:`tests.eval.test_metrics` against synthetic per-query rows
    so the AC2 threshold-failure path has a real regression guard
    that exercises the same code path the live test takes.
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

    # --- RUN cell --------------------------------------------------------
    corpus_version = corpus_info.version
    tbl = open_chunks_table(version=corpus_version)
    per_query_rows = _run_queries_against_corpus(queries, tbl, encode_query)
    score_and_write(
        per_query_rows=per_query_rows,
        corpus_version=corpus_version,
        ndcg_min=ndcg_min,
        output_dir=EVAL_OPS_DIR,
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


def score_and_write(
    per_query_rows: list[dict],
    corpus_version: int,
    ndcg_min: float,
    output_dir: Path,
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

    aggregate = {
        "corpus_version": corpus_version,
        "ndcg5_mean": ndcg5_mean,
        "query_count": len(per_query_rows),
        "recall10_mean": recall10_mean,
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _atomic_write_text(
        aggregate_path,
        json.dumps(aggregate, ensure_ascii=False, sort_keys=True) + "\n",
    )

    # AC1 / AC2: threshold gate. Raises ThresholdNotMetError on
    # failure (subclass of AssertionError, so pytest treats it as a
    # standard test failure with rich diff).
    assert_threshold(ndcg5_mean=ndcg5_mean, ndcg_min=ndcg_min)


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
