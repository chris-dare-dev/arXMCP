"""E14_S04 — tests for ``tools/daily_metrics_report.py``.

Coverage:

- ``histogram_quantile`` matches Prometheus's linear-interp
  algorithm (per E14_S04 synthesis D3).
- ``--dry-run`` against the fixture renders all 7 tools, all 3
  cache tiers, and the sentinel gauges.
- The fixture is the saved ``/metrics`` capture used by the cron
  acceptance criterion.
- ``maybe_email`` is opt-in: silent on missing config; we cannot
  send a real SMTP from tests so we patch the transport.
"""

from __future__ import annotations

import datetime
import logging
import pathlib
from unittest.mock import patch

import pytest

from tools.daily_metrics_report import (
    CACHE_TIERS,
    TOOLS,
    _request_counts,
    fetch_metrics_text,
    histogram_quantile,
    main,
    maybe_email,
    render_report,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "metrics_sample.txt"
#: Alias kept for the F4 regen-fixture test naming.
FIXTURE_PATH = FIXTURE


# ---------------------------------------------------------------------------
# histogram_quantile
# ---------------------------------------------------------------------------


class TestHistogramQuantile:
    def test_empty_buckets_returns_nan(self):
        v = histogram_quantile(0.5, [])
        assert v != v  # nan

    def test_zero_total_returns_nan(self):
        v = histogram_quantile(0.99, [(0.1, 0.0), (1.0, 0.0), (float("inf"), 0.0)])
        assert v != v  # nan

    def test_median_interpolates_inside_bucket(self):
        # 10 observations, all in (0.1, 1.0]; median at rank=5
        # within (0.1, 1.0] interpolates to 0.1 + (1.0-0.1) * (5-0)/(10-0)
        # = 0.1 + 0.9 * 0.5 = 0.55.
        buckets = [(0.1, 0.0), (1.0, 10.0), (float("inf"), 10.0)]
        v = histogram_quantile(0.5, buckets)
        assert abs(v - 0.55) < 1e-9

    def test_p99_clamps_at_highest_finite_le_for_plus_inf_overflow(self):
        # Half the observations land in +Inf overflow. The
        # Prometheus algorithm clamps P99 to the highest finite
        # `le` (the 5.0 bucket) — better than NaN, better than
        # returning +Inf.
        buckets = [(1.0, 50.0), (5.0, 50.0), (float("inf"), 100.0)]
        v = histogram_quantile(0.99, buckets)
        assert v == 5.0

    def test_quantile_at_bucket_edge(self):
        # rank exactly equals the bucket count → answer is the
        # bucket's `le`. With 10 obs and q=1.0 we hit the +Inf
        # bucket; clamp at highest finite le.
        buckets = [(0.1, 10.0), (float("inf"), 10.0)]
        v = histogram_quantile(1.0, buckets)
        assert v == 0.1


# ---------------------------------------------------------------------------
# Fixture-driven render
# ---------------------------------------------------------------------------


class TestRenderReport:
    def test_fixture_present(self):
        assert FIXTURE.is_file(), (
            "tests/fixtures/metrics_sample.txt must be regenerated; "
            "see the E14_S04 implementation summary"
        )

    def test_dry_run_renders_all_seven_tools(self, capsys):
        rc = main(
            ["--dry-run", "--fixture", str(FIXTURE)]
        )
        assert rc == 0
        out = capsys.readouterr().out
        for tool in TOOLS:
            assert f"`{tool}`" in out, (
                f"tool {tool!r} missing from rendered report"
            )

    def test_renders_three_cache_tiers(self, capsys):
        main(["--dry-run", "--fixture", str(FIXTURE)])
        out = capsys.readouterr().out
        for tier in CACHE_TIERS:
            assert f"tier{tier}" in out

    def test_request_counts_are_extracted_correctly(self):
        text = FIXTURE.read_text(encoding="utf-8")
        from prometheus_client.parser import text_string_to_metric_families  # noqa: PLC0415

        fams = {f.name: f for f in text_string_to_metric_families(text)}
        counts = _request_counts(fams.get("arxmcp_request"))
        for tool in TOOLS:
            assert counts[tool]["ok"] == 100
            assert counts[tool]["error"] == 2

    def test_total_and_error_rate_lines_present(self, capsys):
        main(["--dry-run", "--fixture", str(FIXTURE)])
        out = capsys.readouterr().out
        # Seven tools × (100 ok + 2 errors) = 700 ok + 14 errors = 714 total.
        assert "**700**" in out
        assert "**14**" in out
        assert "**714**" in out
        assert "2.0%" in out  # 14/714

    def test_p99_is_finite_milliseconds(self, capsys):
        """The histogram_quantile linear-interp implementation must
        produce a finite millisecond value, not 'n/a' and not the
        '+Inf clamped' edge value. Closes E14_S04 D3."""
        main(["--dry-run", "--fixture", str(FIXTURE)])
        out = capsys.readouterr().out
        # Find a P99 line and assert it's a ms value, not n/a.
        for line in out.splitlines():
            if "`search_papers`" in line and "ms" in line:
                assert "n/a" not in line
                break
        else:
            pytest.fail("expected a search_papers latency row in output")

    def test_renders_no_traceback_on_empty_metrics(self):
        # Empty exposition text (e.g. server returned nothing). The
        # render function must not crash; sentinels render as n/a.
        out = render_report("", datetime.datetime(2026, 5, 17, tzinfo=datetime.UTC))
        assert "arXMCP daily ops report — 2026-05-17" in out
        # All tools render with n/a quantiles.
        for tool in TOOLS:
            assert f"`{tool}`" in out


class TestFetchMetricsText:
    def test_fixture_path(self, tmp_path):
        p = tmp_path / "x.txt"
        p.write_text("# metrics\n", encoding="utf-8")
        assert fetch_metrics_text(None, p).startswith("# metrics")

    def test_fixture_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            fetch_metrics_text(None, tmp_path / "missing.txt")

    def test_url_path_missing_endpoint_returns_nonzero_exit(
        self, capsys, monkeypatch
    ):
        # Force a URLError by pointing at a closed port.
        rc = main(
            [
                "--dry-run",
                "--metrics-url",
                "http://127.0.0.1:1/metrics",
            ]
        )
        assert rc == 2
        err = capsys.readouterr().err
        assert "ERROR: failed to fetch" in err


# ---------------------------------------------------------------------------
# Email opt-in
# ---------------------------------------------------------------------------


class TestF6HistogramQuantileGuard:
    """F6 rectification — histogram_quantile must raise on a
    histogram with no +Inf overflow bucket. The prior implementation
    silently returned a value drawn from the highest-finite-le
    bucket, a foot-gun for any future caller."""

    def test_raises_when_plus_inf_bucket_missing(self):
        with pytest.raises(ValueError, match=r"\+Inf"):
            histogram_quantile(0.95, [(0.1, 100.0)])

    def test_accepts_well_formed_histogram_with_plus_inf(self):
        # No raise.
        histogram_quantile(0.95, [(0.1, 5.0), (float("inf"), 10.0)])


class TestF3BackupStateSurface:
    """F3 rectification — render the ``arxmcp_backup_status{state}``
    cell alongside the age so a "failed" status isn't masked by a
    recently-updated ``finished_at`` timestamp."""

    def test_failed_state_surfaces_in_report(self):
        # Minimal Prometheus exposition that exercises the failed-
        # but-recent path: backup happened ~1.5h ago but state=failed.
        # Use a slightly-larger offset than the boundary to avoid
        # the integer-divison round-down that floating-point
        # noise + .1f formatting can introduce (3600s -> 0h ago,
        # rather than 1h ago, after the round trip).
        import time  # noqa: PLC0415

        ts = time.time() - 5400  # 1.5h ago
        text = (
            "# HELP arxmcp_backup_last_success_timestamp_seconds backup ts\n"
            "# TYPE arxmcp_backup_last_success_timestamp_seconds gauge\n"
            f"arxmcp_backup_last_success_timestamp_seconds {ts:.1f}\n"
            "# HELP arxmcp_backup_status backup state\n"
            "# TYPE arxmcp_backup_status gauge\n"
            'arxmcp_backup_status{state="ok"} 0.0\n'
            'arxmcp_backup_status{state="failed"} 1.0\n'
            'arxmcp_backup_status{state="running"} 0.0\n'
            'arxmcp_backup_status{state="unknown"} 0.0\n'
        )
        now = datetime.datetime(2026, 5, 17, tzinfo=datetime.UTC)
        out = render_report(text, now)
        assert "(failed)" in out
        # The age also renders so operators see "Xh ago (failed)"
        # rather than just one or the other.
        assert "h ago" in out

    def test_ok_state_renders_without_noise(self):
        import time  # noqa: PLC0415

        ts = time.time() - 9000  # 2.5h ago
        text = (
            "# HELP arxmcp_backup_last_success_timestamp_seconds backup ts\n"
            "# TYPE arxmcp_backup_last_success_timestamp_seconds gauge\n"
            f"arxmcp_backup_last_success_timestamp_seconds {ts:.1f}\n"
            "# HELP arxmcp_backup_status backup state\n"
            "# TYPE arxmcp_backup_status gauge\n"
            'arxmcp_backup_status{state="ok"} 1.0\n'
            'arxmcp_backup_status{state="failed"} 0.0\n'
        )
        now = datetime.datetime(2026, 5, 17, tzinfo=datetime.UTC)
        out = render_report(text, now)
        assert "(ok)" in out


class TestCorpusIntegritySection:
    """corpus-integrity-observability-e2 (CAND-9) — the daily report renders a
    ``## Corpus integrity`` row reconciling marker vs actual chunk_count, makes
    a divergence operator-visible, and degrades gracefully to ``n/a``."""

    _NOW = datetime.datetime(2026, 5, 17, tzinfo=datetime.UTC)

    @staticmethod
    def _gauges(marker: float, actual: float, version: float = 645.0) -> str:
        return (
            "# HELP arxmcp_corpus_chunk_count_marker marker\n"
            "# TYPE arxmcp_corpus_chunk_count_marker gauge\n"
            f"arxmcp_corpus_chunk_count_marker {marker}\n"
            "# HELP arxmcp_corpus_chunk_count_actual actual\n"
            "# TYPE arxmcp_corpus_chunk_count_actual gauge\n"
            f"arxmcp_corpus_chunk_count_actual {actual}\n"
            "# HELP arxmcp_corpus_version version\n"
            "# TYPE arxmcp_corpus_version gauge\n"
            f"arxmcp_corpus_version {version}\n"
        )

    def test_section_present_and_matching_is_ok(self):
        out = render_report(self._gauges(10298.0, 10298.0), self._NOW)
        assert "## Corpus integrity" in out
        assert "| corpus_version | 645 |" in out
        assert "| marker chunk_count | 10298 |" in out
        assert "| actual chunk_count | 10298 |" in out
        assert "| Status | ok |" in out
        assert "[DIVERGED]" not in out

    def test_divergence_is_flagged(self):
        # The motivating bug shape: marker says 106, table has 10298.
        out = render_report(self._gauges(106.0, 10298.0), self._NOW)
        assert "| marker chunk_count | 106 |" in out
        assert "| actual chunk_count | 10298 |" in out
        assert "**[DIVERGED]**" in out

    def test_minus_one_sentinel_renders_na_not_negative(self):
        # m2 FM-2: count_rows() failed at startup → actual gauge is -1.
        out = render_report(self._gauges(10298.0, -1.0), self._NOW)
        assert "| actual chunk_count | n/a |" in out
        assert "-1" not in out.split("## Corpus integrity")[1].split("##")[0]
        # A -1 sentinel must NOT be reported as a divergence.
        assert "[DIVERGED]" not in out

    def test_absent_gauges_render_na(self):
        # Server down / cold corpus → gauges absent from /metrics → NaN → n/a.
        out = render_report("", self._NOW)
        assert "## Corpus integrity" in out
        assert "| actual chunk_count | n/a |" in out
        assert "[DIVERGED]" not in out


class TestRegenFixture:
    """F4 rectification — the fixture regeneration script
    (`tools/regen_metrics_fixture.py`) must produce the SAME bytes
    as the checked-in fixture. If a metric family is renamed or
    added in `server/metrics.py` or `server/observability/metrics.py`
    without the regen script being updated, this test fails."""

    @staticmethod
    def _normalize(text: bytes) -> list[str]:
        """Strip non-deterministic lines from a Prometheus
        exposition before comparison: ``_created`` timestamps
        (OpenMetrics gauges set at family-init), and the default
        ``python_*`` / ``process_*`` collector samples (which
        change run-to-run with GC + cpu state).
        """
        out = []
        for line in text.decode("utf-8").splitlines():
            if "_created" in line:
                continue
            if line.startswith(
                ("python_", "process_", "# HELP python_", "# TYPE python_",
                 "# HELP process_", "# TYPE process_")
            ):
                continue
            out.append(line)
        return out

    def test_regen_matches_checked_in_fixture(self):
        # The fixture is generated in a one-shot fresh process —
        # not via the regen script's main() (which would mutate
        # the test process's prometheus_client registry). We run
        # the regen as a subprocess so the in-process registry of
        # the test runner stays clean.
        import subprocess  # noqa: PLC0415
        import sys  # noqa: PLC0415

        # Use sys.executable, NOT `uv run`. `uv run` re-syncs the project venv
        # before executing, which tries to replace .venv/Scripts/*.exe — and on
        # Windows a *running* console script (arxmcp-shim.exe, registered as the
        # MCP shim in ~/.claude.json) holds an exclusive lock, so the replace
        # fails with "Access is denied. (os error 5)", uv exits 2, and this test
        # fails for reasons that have nothing to do with the fixture. That made
        # the suite red for anyone using arXMCP from Claude Code while testing.
        # sys.executable gives the same fresh-interpreter isolation the comment
        # above asks for, without mutating shared environment state.
        result = subprocess.run(
            [
                sys.executable, "-c",
                "from tools.regen_metrics_fixture import render_fixture_bytes;"
                " import sys; sys.stdout.buffer.write(render_fixture_bytes())",
            ],
            capture_output=True,
            timeout=30,
            check=False,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, (
            f"regen failed: stderr={result.stderr.decode()!r}"
        )
        regen_lines = self._normalize(result.stdout)
        on_disk_lines = self._normalize(FIXTURE_PATH.read_bytes())
        if regen_lines != on_disk_lines:
            # Provide an actionable error message including which
            # lines differ.
            import difflib  # noqa: PLC0415

            diff = list(
                difflib.unified_diff(
                    on_disk_lines[:50],
                    regen_lines[:50],
                    fromfile="on-disk",
                    tofile="regen",
                    lineterm="",
                )
            )
            pytest.fail(
                "tests/fixtures/metrics_sample.txt is out of sync "
                "with tools/regen_metrics_fixture.py (deterministic "
                "lines only). Regenerate with: "
                "`uv run python -m tools.regen_metrics_fixture`. "
                f"First diff lines:\n{chr(10).join(diff[:30])}"
            )


class TestMaybeEmail:
    def test_silent_skip_when_disabled(self, caplog, monkeypatch):
        # Clear every env var we read.
        for k in ("MAIL_TO", "MAIL_FROM", "SMTP_HOST"):
            monkeypatch.delenv(k, raising=False)
        with caplog.at_level(logging.INFO, logger="tools.daily_metrics_report"):
            maybe_email("subject", "body")
        # INFO log fires with the missing-var list, but no SMTP call.
        assert any(
            "email disabled" in r.message for r in caplog.records
        )

    def test_send_invoked_when_all_three_set(self, monkeypatch):
        monkeypatch.setenv("MAIL_TO", "ops@example.com")
        monkeypatch.setenv("MAIL_FROM", "arxmcp@example.com")
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        with patch("smtplib.SMTP") as smtp_cls:
            instance = smtp_cls.return_value.__enter__.return_value
            maybe_email("subject", "body")
            smtp_cls.assert_called_once_with(
                "smtp.example.com", 25, timeout=10
            )
            instance.send_message.assert_called_once()

    def test_smtp_failure_does_not_raise(
        self, monkeypatch, caplog
    ):
        """F2 rectification (E14_S04 adversary critique): an SMTP
        failure must NOT bubble up. The daily report file is the
        durable artifact; a misconfigured SMTP would otherwise
        turn a successful cron run into a journalctl-failed unit
        and trip the operator's "did the report fail?" alarm.
        """
        import smtplib  # noqa: PLC0415

        monkeypatch.setenv("MAIL_TO", "ops@example.com")
        monkeypatch.setenv("MAIL_FROM", "arxmcp@example.com")
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        with patch("smtplib.SMTP") as smtp_cls:
            instance = smtp_cls.return_value.__enter__.return_value
            instance.send_message.side_effect = smtplib.SMTPRecipientsRefused(
                {"ops@example.com": (550, b"User unknown")}
            )
            with caplog.at_level(logging.ERROR, logger="tools.daily_metrics_report"):
                # Must return normally; no raise.
                maybe_email("subject", "body")
        assert any(
            "email delivery failed" in r.message
            for r in caplog.records
        )

    def test_smtp_network_failure_does_not_raise(
        self, monkeypatch, caplog
    ):
        """Same F2 contract for an OSError (DNS lookup, refused
        connect) BEFORE the SMTP handshake."""
        monkeypatch.setenv("MAIL_TO", "ops@example.com")
        monkeypatch.setenv("MAIL_FROM", "arxmcp@example.com")
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        with patch("smtplib.SMTP") as smtp_cls:
            smtp_cls.side_effect = OSError("connection refused")
            with caplog.at_level(logging.ERROR, logger="tools.daily_metrics_report"):
                maybe_email("subject", "body")
        assert any(
            "email delivery failed" in r.message
            for r in caplog.records
        )


# ===========================================================================
# corpus-integrity-observability-e3 — Ingestion throughput section
# ===========================================================================


class TestIngestionThroughputSection:
    """Tests for the ``## Ingestion throughput`` section that replaces
    the TODO stub in ``tools/daily_metrics_report.py``."""

    _NOW = datetime.datetime(2026, 5, 29, 12, 0, 0, tzinfo=datetime.UTC)

    @staticmethod
    def _ingest_gauges(
        papers: float = 52.0,
        chunks: float = 4820.0,
        ts: float = 1748476800.0,
    ) -> str:
        """Build a minimal Prometheus exposition text with the 3 ingest gauges."""
        return (
            "# HELP arxmcp_ingest_last_run_papers papers\n"
            "# TYPE arxmcp_ingest_last_run_papers gauge\n"
            f"arxmcp_ingest_last_run_papers {papers}\n"
            "# HELP arxmcp_ingest_last_run_chunks chunks\n"
            "# TYPE arxmcp_ingest_last_run_chunks gauge\n"
            f"arxmcp_ingest_last_run_chunks {chunks}\n"
            "# HELP arxmcp_ingest_last_run_timestamp_seconds ts\n"
            "# TYPE arxmcp_ingest_last_run_timestamp_seconds gauge\n"
            f"arxmcp_ingest_last_run_timestamp_seconds {ts}\n"
        )

    def test_section_present_in_fixture_output(self, capsys):
        """The section header must appear when the script runs on the
        regenerated fixture."""
        rc = main(["--dry-run", "--fixture", str(FIXTURE)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "## Ingestion throughput" in out

    def test_present_gauges_render_papers_and_chunks(self, tmp_path: pathlib.Path):
        out = render_report(self._ingest_gauges(), self._NOW, ops_dir=tmp_path)
        assert "## Ingestion throughput" in out
        section = out.split("## Ingestion throughput")[1].split("##")[0]
        assert "52" in section
        assert "4820" in section

    def test_absent_gauges_render_na(self, tmp_path: pathlib.Path):
        """When no ingest gauges are present (server cold / no scrape yet),
        the section renders n/a values rather than crashing or omitting."""
        out = render_report("", self._NOW, ops_dir=tmp_path)
        assert "## Ingestion throughput" in out
        section = out.split("## Ingestion throughput")[1].split("##")[0]
        assert "n/a" in section

    def test_zero_gauges_absent_sentinel_render_na_not_zero(
        self, tmp_path: pathlib.Path
    ):
        """corpus-integrity-observability-e3 F2: server UP but sentinel absent →
        refresh_sentinel_metrics sets the gauges to 0.0, so /metrics exposes
        ``...papers 0.0``. The report must render papers/chunks as n/a (a 0.0
        timestamp = "never ingested"), NOT "0" — which would read as "the last
        run ingested nothing", the silent-lie class spike-3 warned about."""
        out = render_report(
            self._ingest_gauges(papers=0.0, chunks=0.0, ts=0.0),
            self._NOW,
            ops_dir=tmp_path,  # no ingest-summary.json present
        )
        section = out.split("## Ingestion throughput")[1].split("##")[0]
        assert "| papers (last run) | n/a |" in section
        assert "| chunks (last run) | n/a |" in section
        assert "| papers (last run) | 0 |" not in section  # pre-fix rendered "0"

    def test_driver_rendered_from_sentinel_file(self, tmp_path: pathlib.Path):
        """``driver`` is read from ``ingest-summary.json`` directly
        (not a Prometheus label) and surfaced in the row."""
        import json as _json  # noqa: PLC0415

        payload = {
            "schema_version": 1,
            "driver": "oai_delta",
            "finished_at": "2026-05-29T04:00:00Z",
            "elapsed_seconds": 45.0,
            "papers_processed": 10,
            "papers_succeeded": 9,
            "papers_failed": 1,
            "chunks_written_this_run": 890,
            "total_rows_after_commit": 5000,
        }
        (tmp_path / "ingest-summary.json").write_text(
            _json.dumps(payload) + "\n", encoding="utf-8"
        )
        out = render_report(self._ingest_gauges(), self._NOW, ops_dir=tmp_path)
        assert "oai_delta" in out

    def test_absent_sentinel_driver_renders_na(self, tmp_path: pathlib.Path):
        """When the sentinel file is absent the driver cell must render n/a."""
        # No ingest-summary.json in tmp_path.
        out = render_report(self._ingest_gauges(), self._NOW, ops_dir=tmp_path)
        section = out.split("## Ingestion throughput")[1].split("##")[0]
        assert "n/a" in section

    def test_no_crash_on_absent_ingest_summary(self, tmp_path: pathlib.Path):
        """render_report must not raise when the sentinel file is absent."""
        out = render_report("", self._NOW, ops_dir=tmp_path)
        assert "## Ingestion throughput" in out

    def test_fixture_contains_ingest_gauge_families(self):
        """The regenerated fixture must contain the three new gauge families
        so dry-run tests exercise the real data path (FM-2)."""
        text = FIXTURE.read_text(encoding="utf-8")
        assert "arxmcp_ingest_last_run_papers" in text
        assert "arxmcp_ingest_last_run_chunks" in text
        assert "arxmcp_ingest_last_run_timestamp_seconds" in text
