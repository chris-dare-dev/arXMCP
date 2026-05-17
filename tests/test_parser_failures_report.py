"""E14_S04 — tests for ``tools/parser_failures_report.py``."""

from __future__ import annotations

import datetime
import json

import pytest

from tools.parser_failures_report import (
    FailureRecord,
    collect_records,
    filter_by_week,
    main,
    parse_week,
    render_report,
)

# ---------------------------------------------------------------------------
# parse_week
# ---------------------------------------------------------------------------


class TestParseWeek:
    def test_valid(self):
        assert parse_week("2026-W19") == (2026, 19)

    def test_invalid_no_w(self):
        import argparse  # noqa: PLC0415

        with pytest.raises(argparse.ArgumentTypeError):
            parse_week("2026-19")

    def test_invalid_non_int(self):
        import argparse  # noqa: PLC0415

        with pytest.raises(argparse.ArgumentTypeError):
            parse_week("yyyy-Www")


# ---------------------------------------------------------------------------
# collect_records — TSV + JSONL
# ---------------------------------------------------------------------------


class TestCollectRecords:
    def test_empty_dir_returns_empty(self, tmp_path):
        assert collect_records(tmp_path) == []

    def test_tsv_parsed_fail_status_only(self, tmp_path):
        (tmp_path / "chunk.log").write_text(
            "arxiv:2307.00001\tfail\t3.2\tLaTeXML crash\n"
            "arxiv:2307.00002\tok\t1.1\tparsed cleanly\n"
            "arxiv:2307.00003\tfail\t5.0\tnested-env nesting too deep\n",
            encoding="utf-8",
        )
        records = collect_records(tmp_path)
        assert len(records) == 2  # only fail rows
        ids = {r.paper_id for r in records}
        assert ids == {"arxiv:2307.00001", "arxiv:2307.00003"}
        for r in records:
            assert r.stage == "chunker"

    def test_tsv_malformed_rows_skipped(self, tmp_path):
        # Fewer than 4 columns → row ignored.
        (tmp_path / "embed.log").write_text(
            "arxiv:2307.00001\tfail\n"
            "arxiv:2307.00002\tfail\t1.0\treason\n",
            encoding="utf-8",
        )
        records = collect_records(tmp_path)
        assert len(records) == 1
        assert records[0].stage == "embedder"

    def test_jsonl_parsed_with_timestamp(self, tmp_path):
        (tmp_path / "delta.jsonl").write_text(
            json.dumps(
                {
                    "paper_id": "arxiv:2307.00010",
                    "failure_reason": "fetch 503",
                    "timestamp": "2026-05-12T03:00:00Z",
                }
            )
            + "\n"
            + json.dumps(
                {
                    "paper_id": "arxiv:2307.00011",
                    "reason": "ar5iv miss",
                    "ts": "2026-05-12T04:00:00Z",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        records = collect_records(tmp_path)
        assert len(records) == 2
        assert {r.stage for r in records} == {"oai-delta"}
        # First row has explicit timestamp parsed.
        for r in records:
            assert r.timestamp is not None
            assert r.timestamp.year == 2026

    def test_jsonl_malformed_lines_skipped(self, tmp_path):
        (tmp_path / "bulk.jsonl").write_text(
            "not json\n"
            + json.dumps({"paper_id": "x", "reason": "y"})
            + "\n",
            encoding="utf-8",
        )
        records = collect_records(tmp_path)
        assert len(records) == 1
        assert records[0].paper_id == "x"

    def test_unknown_filenames_ignored(self, tmp_path):
        # An unrelated file under parser-failures/ must not be parsed.
        (tmp_path / "stray.log").write_text("garbage", encoding="utf-8")
        assert collect_records(tmp_path) == []


# ---------------------------------------------------------------------------
# filter_by_week
# ---------------------------------------------------------------------------


class TestFilterByWeek:
    def test_timestamped_rows_filter_strictly(self):
        # ISO calendar: 2026-W19 covers May 4–10, 2026.
        in_week = FailureRecord(
            stage="oai-delta",
            paper_id="p1",
            reason="r",
            timestamp=datetime.datetime(2026, 5, 5, tzinfo=datetime.UTC),
        )
        out_of_week = FailureRecord(
            stage="oai-delta",
            paper_id="p2",
            reason="r",
            timestamp=datetime.datetime(2026, 4, 27, tzinfo=datetime.UTC),
        )
        filtered = filter_by_week([in_week, out_of_week], 2026, 19)
        assert filtered == [in_week]

    def test_untimestamped_rows_pass_through_without_mtime(self):
        r = FailureRecord(
            stage="chunker", paper_id="p", reason="r", timestamp=None
        )
        # No mtime → conservative pass-through.
        assert filter_by_week([r], 2026, 1) == [r]


# ---------------------------------------------------------------------------
# render_report
# ---------------------------------------------------------------------------


class TestRenderReport:
    def test_empty_records_says_healthy(self):
        out = render_report([], 2026, 19, datetime.datetime(2026, 5, 11, tzinfo=datetime.UTC))
        assert "2026-W19" in out
        assert "0" in out
        assert "healthy" in out.lower()

    def test_per_stage_breakdown(self):
        records = [
            FailureRecord("chunker", "a", "latexml-crash", None),
            FailureRecord("chunker", "b", "latexml-crash", None),
            FailureRecord("chunker", "c", "nested-env", None),
            FailureRecord("embedder", "d", "OOM", None),
        ]
        out = render_report(
            records, 2026, 19,
            datetime.datetime(2026, 5, 11, tzinfo=datetime.UTC),
        )
        assert "Total failures: **4**" in out
        assert "Distinct papers affected: **4**" in out
        # Stages appear with their counts.
        assert "| chunker | 3 |" in out
        assert "| embedder | 1 |" in out
        # Top-reason table shows the most-frequent reason.
        assert "latexml-crash" in out


# ---------------------------------------------------------------------------
# main entry point — dry-run on a fixture dir
# ---------------------------------------------------------------------------


class TestMainDryRun:
    def test_dry_run_prints_markdown_no_file(self, tmp_path, capsys):
        # Synthesize a fixture parser-failures directory.
        parser_dir = tmp_path / "parser-failures"
        parser_dir.mkdir()
        (parser_dir / "chunk.log").write_text(
            "arxiv:2307.00001\tfail\t2.1\tlatexml crashed on \\newcommand\n"
            "arxiv:2307.00002\tfail\t1.0\tlatexml crashed on \\newcommand\n",
            encoding="utf-8",
        )
        # JSONL row with a timestamp falling outside the target week
        # — using --week to pin the target. ISO 2026-W19 = May 4-10.
        outside = (tmp_path / "parser-failures" / "delta.jsonl")
        outside.write_text(
            json.dumps(
                {
                    "paper_id": "arxiv:2307.00099",
                    "reason": "old failure",
                    "timestamp": "2025-01-01T00:00:00Z",
                }
            ) + "\n",
            encoding="utf-8",
        )

        rc = main(
            [
                "--dry-run",
                "--parser-dir", str(parser_dir),
                "--out-dir", str(tmp_path / "reports"),
                "--week", "2026-W19",
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        # The TSV (untimestamped) entries fall through the mtime-
        # filter (file was just written, so its mtime is "now").
        # We can't pin the mtime week without monkey-patching; the
        # robustness test is that the report renders and lists
        # the chunker stage.
        assert "2026-W19" in out
        # The outside-window JSONL entry must NOT appear.
        assert "arxiv:2307.00099" not in out

    def test_real_write_creates_file(self, tmp_path):
        parser_dir = tmp_path / "parser-failures"
        parser_dir.mkdir()
        out_dir = tmp_path / "reports"
        rc = main(
            [
                "--parser-dir", str(parser_dir),
                "--out-dir", str(out_dir),
                "--week", "2026-W19",
            ]
        )
        assert rc == 0
        out_path = out_dir / "parser-failures-2026-W19.md"
        assert out_path.is_file()
        body = out_path.read_text(encoding="utf-8")
        assert "2026-W19" in body

    def test_missing_parser_dir_writes_healthy_report(self, tmp_path):
        rc = main(
            [
                "--parser-dir", str(tmp_path / "doesnotexist"),
                "--out-dir", str(tmp_path / "reports"),
                "--week", "2026-W19",
            ]
        )
        assert rc == 0
        report = (tmp_path / "reports" / "parser-failures-2026-W19.md").read_text(
            encoding="utf-8"
        )
        assert "healthy" in report.lower()
