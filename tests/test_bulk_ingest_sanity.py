"""Operator-gated sanity tests for the bulk ingest (E11_S01).

These tests assert against a FULLY-INGESTED staging LanceDB. They
SKIP by default — running `make test` on a fresh checkout sees the
skipped tests and the suite stays green.

To run after a full operator ingest:

    pytest -m requires_full_corpus tests/test_bulk_ingest_sanity.py

The `requires_full_corpus` marker AND the
`ARXMCP_RUN_FULL_CORPUS_TESTS=1` env var must both be set so a
contributor cannot accidentally opt-in via a stray `-m` flag in CI.

Synthesis D9 frames these as "operator-gated ACs" — verifiable
only after the multi-day ingest run.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ingest.bulk_ingest import DEFAULT_LANCEDB_STAGING_PATH


def _opted_in() -> bool:
    """Both marker AND env var must indicate opt-in."""
    return os.environ.get("ARXMCP_RUN_FULL_CORPUS_TESTS") == "1"


@pytest.mark.requires_full_corpus
@pytest.mark.skipif(
    not _opted_in(),
    reason=(
        "Operator-gated. Set ARXMCP_RUN_FULL_CORPUS_TESTS=1 AND "
        "run `pytest -m requires_full_corpus` to enable."
    ),
)
class TestBulkIngestSanity:
    """Brief AC1 + AC5 — verifiable AFTER the operator runs
    `make ingest` end-to-end."""

    def test_chunks_table_has_at_least_100k_rows(self):
        """AC1: new LanceDB version contains ≥ 100,000 chunk entries."""
        import lancedb

        db = lancedb.connect(str(DEFAULT_LANCEDB_STAGING_PATH))
        tbl = db.open_table("chunks")
        row_count = tbl.to_arrow().num_rows
        assert row_count >= 100_000, (
            f"expected ≥ 100K chunks in staging LanceDB; got {row_count}"
        )

    def test_ar5iv_hit_rate_at_least_70pct(self):
        """AC5: ar5iv cache hit rate logged AND ≥ 70%.

        Reads `ops/ingestion.log` and parses the final progress
        line for the `ar5iv_rate=<float>` field.
        """
        log = (
            Path(__file__).resolve().parent.parent
            / "var" / "arxmcp" / "ops" / "ingestion.log"
        )
        assert log.is_file(), (
            f"ingestion.log not found at {log}; operator must run "
            "`make ingest` first"
        )
        last_line = log.read_text(encoding="utf-8").strip().splitlines()[-1]
        # Field format: ar5iv_rate=<float>
        rate_token = next(
            (t for t in last_line.split("\t") if t.startswith("ar5iv_rate=")),
            None,
        )
        assert rate_token is not None, (
            f"ar5iv_rate field missing from progress log: {last_line!r}"
        )
        rate = float(rate_token.split("=", 1)[1])
        assert rate >= 0.70, (
            f"ar5iv cache hit rate {rate:.3f} below 0.70 threshold"
        )

    def test_active_corpus_version_json_untouched(self):
        """AC2: the active `corpus-version.json` was NOT advanced by
        bulk ingest. The staging path holds the new marker; the
        active path is byte-identical to its pre-ingest state."""
        from ingest.store import DEFAULT_LANCEDB_PATH

        active = DEFAULT_LANCEDB_PATH / "corpus-version.json"
        staging = DEFAULT_LANCEDB_STAGING_PATH / "corpus-version.json"
        assert staging.is_file(), (
            f"staging corpus-version.json missing at {staging} — did "
            "the ingest complete?"
        )
        if not active.is_file():
            # Cold-start case: no active marker before ingest. AC2 is
            # vacuously satisfied (the active state hasn't advanced
            # because there's nothing to advance).
            return
        # The active marker's version integer should NOT match the
        # staging one (the staging one moved forward; the active stays
        # where it was).
        import json

        active_v = json.loads(active.read_text())["version"]
        staging_v = json.loads(staging.read_text())["version"]
        assert active_v < staging_v, (
            f"active corpus version {active_v} should be < staging "
            f"version {staging_v}; the bulk ingest must not have "
            "advanced the active marker"
        )
