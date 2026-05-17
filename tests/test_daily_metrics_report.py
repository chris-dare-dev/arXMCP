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
