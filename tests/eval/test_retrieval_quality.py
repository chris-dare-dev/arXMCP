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

#: The two embedding columns to search (E04_S01 schema).
EMBEDDING_COLUMNS = ("embedding_stmt", "embedding_proof")


# ---------------------------------------------------------------------------
# The retrieval-quality test
# ---------------------------------------------------------------------------


def test_retrieval_quality(ndcg_min: float) -> None:  # noqa: PLR0915
    """Top-level eval harness — see module docstring for the full
    behavior matrix.

    The function is one large body rather than per-step helpers
    because (a) the matrix is short, (b) splitting hurts traceability
    when the test fails (one stack frame is easier to read than five),
    and (c) every step has a unit-test counterpart in
    ``test_metrics.py`` already locking the math.
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

    per_query_rows: list[dict] = []
    ndcg_scores: list[float] = []
    recall_scores: list[float] = []

    for query in queries:
        query_id = query["query_id"]
        query_text = query["query_text"]
        ground_truth = {
            entry["chunk_id"]: entry["relevance"]
            for entry in query["relevant_chunks"]
        }

        query_vec = asyncio.run(encode_query(query_text))

        # Dual-column ANN: one search per embedding column. MIN
        # distance per chunk_id, sorted ascending, top FINAL_TOP_K.
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
                # MIN-distance dedup (D3): a chunk's best-channel
                # match wins. In practice, schema enforces exactly
                # one of stmt/proof per row, so collisions are rare;
                # this is defense-in-depth against future schema
                # changes (also locked by ``min(...)`` semantics).
                prev = per_chunk_min_distance.get(cid)
                if prev is None or dist < prev:
                    per_chunk_min_distance[cid] = dist

        ranked = sorted(
            per_chunk_min_distance.items(),
            key=lambda kv: kv[1],  # ascending distance == descending similarity
        )
        retrieved_chunk_ids = [cid for cid, _ in ranked[:FINAL_TOP_K]]

        ndcg5 = ndcg_at_k(retrieved_chunk_ids, ground_truth, k=NDCG_K)
        recall10 = recall_at_k(retrieved_chunk_ids, ground_truth, k=FINAL_TOP_K)
        ndcg_scores.append(ndcg5)
        recall_scores.append(recall10)

        per_query_rows.append(
            {
                "ndcg5": ndcg5,
                "query_id": query_id,
                "query_text": query_text,
                "recall10": recall10,
                "retrieved_chunk_ids": retrieved_chunk_ids,
            }
        )

    ndcg5_mean = _mean(ndcg_scores)
    recall10_mean = _mean(recall_scores)

    # --- Write the result files (only on the RUN cell) -------------------
    EVAL_OPS_DIR.mkdir(parents=True, exist_ok=True)
    results_path = EVAL_OPS_DIR / f"results-{corpus_version}.jsonl"
    aggregate_path = EVAL_OPS_DIR / f"aggregate-{corpus_version}.json"

    # JSONL: append-mode (mirrors store-stats / bm25-stats discipline);
    # one line per query, sort_keys for deterministic byte output.
    with results_path.open("w", encoding="utf-8") as fh:
        for row in per_query_rows:
            fh.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            )

    aggregate = {
        "corpus_version": corpus_version,
        "ndcg5_mean": ndcg5_mean,
        "query_count": len(queries),
        "recall10_mean": recall10_mean,
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _atomic_write_text(
        aggregate_path,
        json.dumps(aggregate, ensure_ascii=False, sort_keys=True) + "\n",
    )

    # --- AC1 / AC2: threshold gate ---------------------------------------
    # Raises ThresholdNotMetError on failure; pytest treats that as a
    # standard test failure (subclass of AssertionError).
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
