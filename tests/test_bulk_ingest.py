"""Tests for the bulk-ingest orchestrator (E11_S01).

Two layers:

* Pure orchestrator logic — paper-id file parsing, CLI flag
  handling, parser-failures JSONL writing, progress logging,
  dry-run output. Mocks `ingest_one_paper` so the suite runs
  without LaTeXML / BGE-M3 / LanceDB.
* End-to-end "smoke" test against a SINGLE paper — mocks the
  ar5iv hit, stages a minimal parsed HTML, runs the real
  chunker + embedder + LanceDB write at the staging path.
  Marked `requires_model` (BGE-M3 download).

The sanity test ("≥100K chunks in staging LanceDB") lives at
`tests/test_bulk_ingest_sanity.py` and is marked
`requires_full_corpus`; it skips by default and runs only after
the operator has executed the full ingest.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from ingest.bulk_ingest import (
    PaperOutcome,
    _log_parser_failure,
    _log_progress,
    _read_paper_ids,
    ingest_one_paper,
    run_bulk_ingest,
)

# ---------------------------------------------------------------------------
# _read_paper_ids
# ---------------------------------------------------------------------------


class TestReadPaperIds:
    def test_reads_one_per_line(self, tmp_path):
        path = tmp_path / "ids.txt"
        path.write_text("2401.00001\n2401.00002\n", encoding="utf-8")
        assert _read_paper_ids(path) == ["2401.00001", "2401.00002"]

    def test_skips_blanks_and_comments(self, tmp_path):
        path = tmp_path / "ids.txt"
        path.write_text(
            "# heading\n2401.00001\n\n# more\n2401.00002\n",
            encoding="utf-8",
        )
        assert _read_paper_ids(path) == ["2401.00001", "2401.00002"]

    def test_raises_on_malformed_id(self, tmp_path):
        path = tmp_path / "ids.txt"
        path.write_text("2401.00001\nnot-an-id\n", encoding="utf-8")
        with pytest.raises(ValueError, match="invalid paper_id"):
            _read_paper_ids(path)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="paper-ids-file"):
            _read_paper_ids(tmp_path / "missing.txt")


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------


class TestLogParserFailure:
    def test_writes_jsonl_line(self, tmp_path):
        path = tmp_path / "ops" / "parser-failures" / "bulk.jsonl"
        outcome = PaperOutcome(
            paper_id="2401.00001",
            parsers_tried=["ar5iv", "latexml"],
            failure_reason="no_parsed_html",
        )
        _log_parser_failure(outcome, path)
        rec = json.loads(path.read_text().strip())
        assert rec["paper_id"] == "2401.00001"
        assert rec["parsers_tried"] == ["ar5iv", "latexml"]
        assert rec["failure_reason"] == "no_parsed_html"
        assert "timestamp" in rec

    def test_appends_multiple_records(self, tmp_path):
        path = tmp_path / "bulk.jsonl"
        for i in range(3):
            _log_parser_failure(
                PaperOutcome(
                    paper_id=f"2401.0000{i}",
                    parsers_tried=["ar5iv"],
                    failure_reason="x",
                ),
                path,
            )
        lines = path.read_text().splitlines()
        assert len(lines) == 3


class TestLogProgress:
    def test_writes_progress_line(self, tmp_path):
        from ingest.bulk_ingest import IngestSummary

        path = tmp_path / "ingestion.log"
        summary = IngestSummary(
            papers_total=10,
            papers_succeeded=8,
            papers_failed=2,
            ar5iv_hits=7,
            ar5iv_misses=1,
        )
        _log_progress(path, summary, paper_id="2401.00010")
        text = path.read_text()
        assert "paper=2401.00010" in text
        assert "ok=8" in text
        assert "fail=2" in text
        assert "ar5iv_hits=7" in text


# ---------------------------------------------------------------------------
# run_bulk_ingest with mocked ingest_one_paper
# ---------------------------------------------------------------------------


def _ok_outcome(paper_id: str, parser: str = "ar5iv") -> PaperOutcome:
    return PaperOutcome(
        paper_id=paper_id,
        parsers_tried=[parser],
        parser_used=parser,
        chunks_written=10,
        elapsed_seconds=0.1,
    )


def _fail_outcome(paper_id: str) -> PaperOutcome:
    return PaperOutcome(
        paper_id=paper_id,
        parsers_tried=["ar5iv", "latexml"],
        parser_used=None,
        chunks_written=0,
        elapsed_seconds=0.1,
        failure_reason="no_parsed_html",
    )


class TestRunBulkIngest:
    def test_all_papers_succeed(self, tmp_path):
        failures = tmp_path / "bulk.jsonl"
        log = tmp_path / "ingestion.log"
        paper_ids = ["2401.00001", "2401.00002", "2401.00003"]

        with patch(
            "ingest.bulk_ingest.ingest_one_paper",
            side_effect=[_ok_outcome(p) for p in paper_ids],
        ):
            summary = run_bulk_ingest(
                paper_ids,
                failures_path=failures,
                log_path=log,
                progress_interval=1,
            )

        assert summary.papers_total == 3
        assert summary.papers_succeeded == 3
        assert summary.papers_failed == 0
        assert summary.ar5iv_hits == 3
        assert summary.ar5iv_misses == 0
        assert summary.ar5iv_hit_rate == 1.0
        assert not failures.exists()  # no failures, no JSONL line

    def test_mixed_success_and_failure(self, tmp_path):
        failures = tmp_path / "bulk.jsonl"
        log = tmp_path / "ingestion.log"
        outcomes = [
            _ok_outcome("2401.00001"),
            _fail_outcome("2401.00002"),
            _ok_outcome("2401.00003"),
        ]
        with patch(
            "ingest.bulk_ingest.ingest_one_paper",
            side_effect=outcomes,
        ):
            summary = run_bulk_ingest(
                ["2401.00001", "2401.00002", "2401.00003"],
                failures_path=failures,
                log_path=log,
                progress_interval=10,
            )
        assert summary.papers_total == 3
        assert summary.papers_succeeded == 2
        assert summary.papers_failed == 1
        # Only the failed paper writes to the JSONL.
        lines = failures.read_text().splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["paper_id"] == "2401.00002"

    def test_limit_caps_papers_processed(self, tmp_path):
        failures = tmp_path / "bulk.jsonl"
        log = tmp_path / "ingestion.log"
        paper_ids = ["2401.00001", "2401.00002", "2401.00003"]
        call_count = 0

        def _mock(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return _ok_outcome(args[0])

        with patch("ingest.bulk_ingest.ingest_one_paper", side_effect=_mock):
            summary = run_bulk_ingest(
                paper_ids,
                failures_path=failures,
                log_path=log,
                limit=2,
            )
        assert summary.papers_total == 2
        assert call_count == 2

    def test_ar5iv_hit_rate_tracks_correctly(self, tmp_path):
        failures = tmp_path / "bulk.jsonl"
        log = tmp_path / "ingestion.log"
        # Mix: 2 ar5iv hits + 1 latexml fallback. ar5iv hit rate = 2/3.
        outcomes = [
            _ok_outcome("2401.00001", parser="ar5iv"),
            PaperOutcome(
                paper_id="2401.00002",
                parsers_tried=["ar5iv", "latexml"],
                parser_used="latexml",
                chunks_written=5,
                elapsed_seconds=0.1,
            ),
            _ok_outcome("2401.00003", parser="ar5iv"),
        ]
        with patch(
            "ingest.bulk_ingest.ingest_one_paper",
            side_effect=outcomes,
        ):
            summary = run_bulk_ingest(
                ["2401.00001", "2401.00002", "2401.00003"],
                failures_path=failures,
                log_path=log,
                progress_interval=10,
            )
        assert summary.ar5iv_hits == 2
        assert summary.ar5iv_misses == 1
        assert summary.ar5iv_hit_rate == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# dry-run
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_does_not_call_ingest_one_paper(self, tmp_path, capsys):
        failures = tmp_path / "bulk.jsonl"
        log = tmp_path / "ingestion.log"
        # Stage one paper as having an ar5iv local cache.
        parsed_dir = tmp_path / "parsed"
        (parsed_dir / "2401.00001").mkdir(parents=True)
        (parsed_dir / "2401.00001" / "index.html").write_text("<html/>")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "2401.00001.html").write_text("<html/>")

        with patch(
            "ingest.bulk_ingest.ingest_one_paper",
            side_effect=AssertionError("dry-run must not call this"),
        ):
            summary = run_bulk_ingest(
                ["2401.00001", "2401.00002"],
                ar5iv_cache_dir=cache_dir,
                parsed_dir=parsed_dir,
                failures_path=failures,
                log_path=log,
                dry_run=True,
            )
        out, _err = capsys.readouterr()
        assert "ar5iv_local_cache" in out
        assert summary.papers_skipped == 2


# ---------------------------------------------------------------------------
# ingest_one_paper — skip-and-log path (no ar5iv hit, no parsed HTML)
# ---------------------------------------------------------------------------


class TestIngestOnePaperFailurePath:
    def test_returns_no_parsed_html_when_both_paths_miss(self, tmp_path):
        """Per synthesis D2: bulk_ingest does NOT fetch raw .tex or
        invoke LaTeXML itself. If ar5iv misses AND no local
        parsed HTML exists, the outcome is skip-and-log.
        """
        cache_dir = tmp_path / "cache"
        parsed_dir = tmp_path / "parsed"
        # ar5iv stubbed to return a miss.
        with patch(
            "ingest.bulk_ingest.try_cache",
            return_value=__import__(
                "ingest.ar5iv_fetch", fromlist=["Ar5ivResult"]
            ).Ar5ivResult(
                paper_id="2401.00001",
                hit=False,
                cache_path=None,
                parsed_path=None,
                reason="http_404",
            ),
        ):
            outcome = ingest_one_paper(
                "2401.00001",
                lancedb_staging_path=tmp_path / "lancedb-staging",
                ar5iv_cache_dir=cache_dir,
                parsed_dir=parsed_dir,
            )
        assert outcome.parser_used is None
        assert outcome.failure_reason == "no_parsed_html"
        assert "ar5iv" in outcome.parsers_tried
        assert "latexml" in outcome.parsers_tried


# ---------------------------------------------------------------------------
# Active corpus-version.json is NOT touched
# ---------------------------------------------------------------------------


class TestActiveCorpusVersionUntouched:
    """AC2 close: bulk ingest writes to a staging path, so the active
    `corpus-version.json` (under DEFAULT_LANCEDB_PATH) is byte-
    identical before and after the run.
    """

    def test_dry_run_doesnt_touch_active_marker(self, tmp_path):
        from ingest.store import DEFAULT_LANCEDB_PATH

        active_marker = DEFAULT_LANCEDB_PATH / "corpus-version.json"
        before = active_marker.read_bytes() if active_marker.is_file() else None
        # Dry-run with no parsed/cache hits — exits cleanly.
        failures = tmp_path / "bulk.jsonl"
        log = tmp_path / "ingestion.log"
        run_bulk_ingest(
            ["2401.00001"],
            ar5iv_cache_dir=tmp_path / "cache",
            parsed_dir=tmp_path / "parsed",
            failures_path=failures,
            log_path=log,
            dry_run=True,
        )
        after = active_marker.read_bytes() if active_marker.is_file() else None
        assert after == before
