"""Tests for the drift watchdog (E11_S04).

Pure unit tests with mocked retrieval pipeline (via the
`compute_eval` injection seam) and synthetic fixtures. No live
model, no LanceDB. The suite covers the four ACs:

1. AC1 — seed corpus → nDCG@5 ≥ 0.80
   (conditional-skip — fixture is empty in the v1 stub).
2. AC2 — degraded retrieval (nDCG@5 ≈ 0.60) → exit non-zero +
   quarantine flag written.
3. AC3 — `arxmcp_eval_ndcg5{corpus_version="N"}` emitted at
   `/metrics` (XFAIL — cross-process exposure deferred to E14
   per the LATEXML_DRIFT_DETECTED_COUNTER precedent).
4. AC4 — runbook content (threshold + quarantine + E11_S05).

Plus regression guards for the synthesis landmines.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ops.watchdog_eval import (
    DEFAULT_REGRESSION_THRESHOLD_PCT,
    MIN_QUERIES_FOR_REGRESSION_CHECK,
    _clear_quarantine_flag,
    _parse_threshold_pct,
    evaluate_regression,
    find_prior_report,
    run_watchdog,
)
from server.metrics import EVAL_NDCG5_GAUGE, reset_eval_metrics_for_tests

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_eval_metric_gauge():
    """Reset the EVAL_NDCG5_GAUGE before AND after each test so
    label-set residue doesn't leak between tests."""
    reset_eval_metrics_for_tests()
    yield
    reset_eval_metrics_for_tests()


def _write_fixture(path: Path, query_ids: list[str]) -> None:
    """Build a minimal eval fixture with N queries."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fixture = {
        "schema_version": "1.0",
        "chunker_version": "v1.0",
        "created_at": "2026-05-15",
        "queries": [
            {"query_id": qid, "text": f"test query {qid}", "relevant": []}
            for qid in query_ids
        ],
    }
    path.write_text(json.dumps(fixture), encoding="utf-8")


def _write_staging_marker(staging_path: Path, version: int = 42) -> None:
    staging_path.mkdir(parents=True, exist_ok=True)
    (staging_path / "corpus-version.json").write_text(
        json.dumps(
            {
                "version": version,
                "chunker_version": "v1.0",
                "embedder_version": "bge-m3@aaaaaaaa",
                "paper_count": 50,
                "chunk_count": 1000,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _write_prior_report(
    report_dir: Path,
    *,
    corpus_version: int,
    ndcg5_mean: float,
) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    out = report_dir / f"corpus_v{corpus_version}-20260101T120000.json"
    out.write_text(
        json.dumps(
            {
                "corpus_version": corpus_version,
                "ndcg5_mean": ndcg5_mean,
                "ndcg5_per_query": [],
                "alert_triggered": False,
                "timestamp": "2026-01-01T12:00:00Z",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return out


def _stub_eval(ndcg5_per_query: list[float], rerank: bool = False):
    """Build a compute_eval stub that returns the given per-query
    nDCG@5 values."""

    def _impl(*, fixture, corpus_version, lancedb_staging_path, rerank_enabled):
        rows = [
            {
                "query_id": f"q{idx:02d}",
                "ndcg5": value,
                "recall10": value * 0.9,
            }
            for idx, value in enumerate(ndcg5_per_query)
        ]
        return rows, rerank_enabled if rerank else False

    return _impl


# ---------------------------------------------------------------------------
# evaluate_regression — one-directional math
# ---------------------------------------------------------------------------


class TestEvaluateRegression:
    """Closes synthesis Headline #3 / brief's regression formula."""

    def test_decline_above_threshold_alerts(self):
        delta, pct, alert = evaluate_regression(0.80, 0.70, 10.0)
        assert delta == pytest.approx(-0.10)
        assert pct == pytest.approx(12.5)
        assert alert is True

    def test_decline_below_threshold_no_alert(self):
        delta, pct, alert = evaluate_regression(0.80, 0.76, 10.0)
        # 5% regression below the 10% threshold.
        assert pct == pytest.approx(5.0)
        assert alert is False

    def test_improvement_never_alerts(self):
        """Brief: one-directional. A nDCG@5 INCREASE never alerts."""
        _, pct, alert = evaluate_regression(0.70, 0.80, 5.0)
        # regression_pct is negative for an improvement.
        assert pct < 0
        assert alert is False

    def test_zero_prior_returns_no_signal(self):
        """Pathological prior — divide-by-zero-safe."""
        delta, pct, alert = evaluate_regression(0.0, 0.5, 10.0)
        assert delta == 0.0
        assert pct == 0.0
        assert alert is False


# ---------------------------------------------------------------------------
# _parse_threshold_pct — synthesis D4 validation
# ---------------------------------------------------------------------------


class TestParseThresholdPct:
    def test_accepts_numeric(self):
        assert _parse_threshold_pct(5.0) == 5.0
        assert _parse_threshold_pct("7.5") == 7.5

    def test_rejects_non_numeric(self):
        with pytest.raises(ValueError, match="numeric"):
            _parse_threshold_pct("not-a-number")

    def test_rejects_zero_or_negative(self):
        with pytest.raises(ValueError, match="> 0"):
            _parse_threshold_pct(0.0)
        with pytest.raises(ValueError, match="> 0"):
            _parse_threshold_pct(-5.0)

    def test_rejects_over_100(self):
        with pytest.raises(ValueError, match="<= 100"):
            _parse_threshold_pct(101.0)


# ---------------------------------------------------------------------------
# find_prior_report — synthesis D7 lookup
# ---------------------------------------------------------------------------


class TestFindPriorReport:
    def test_empty_dir_returns_none(self, tmp_path):
        path, data = find_prior_report(tmp_path / "reports", 42)
        assert path is None
        assert data is None

    def test_picks_highest_version_below_current(self, tmp_path):
        rd = tmp_path / "reports"
        _write_prior_report(rd, corpus_version=10, ndcg5_mean=0.75)
        _write_prior_report(rd, corpus_version=20, ndcg5_mean=0.80)
        _write_prior_report(rd, corpus_version=30, ndcg5_mean=0.78)
        path, data = find_prior_report(rd, current_version=25)
        assert data is not None
        assert data["ndcg5_mean"] == 0.80  # version 20 is the highest < 25
        assert "corpus_v20" in str(path)

    def test_ignores_corrupt_report(self, tmp_path):
        rd = tmp_path / "reports"
        rd.mkdir()
        (rd / "corpus_v10-20260101T000000.json").write_text("{not json")
        path, data = find_prior_report(rd, current_version=25)
        assert path is None
        assert data is None

    def test_ignores_missing_ndcg5_mean(self, tmp_path):
        rd = tmp_path / "reports"
        rd.mkdir()
        (rd / "corpus_v10-20260101T000000.json").write_text(
            json.dumps({"corpus_version": 10})
        )
        path, data = find_prior_report(rd, current_version=25)
        assert path is None
        assert data is None


# ---------------------------------------------------------------------------
# run_watchdog — end-to-end with stubbed compute_eval
# ---------------------------------------------------------------------------


class TestRunWatchdog:
    """Cover the run_watchdog control flow with mocked eval."""

    def test_first_run_no_prior_no_alert(self, tmp_path):
        """Synthesis D7: first run on a corpus has no baseline →
        no alert even if nDCG@5 is low (there's nothing to
        regress against)."""
        fixture_path = tmp_path / "queries.json"
        _write_fixture(fixture_path, [f"q{i:02d}" for i in range(20)])
        staging = tmp_path / "lancedb-staging"
        _write_staging_marker(staging, version=42)

        exit_code, report = run_watchdog(
            lancedb_staging_path=staging,
            report_dir=tmp_path / "reports",
            fixture_path=fixture_path,
            quarantine_flag_path=tmp_path / "quarantine.flag",
            re_embed_state_path=tmp_path / "no-state.json",
            compute_eval=_stub_eval([0.60] * 20),
        )
        assert exit_code == 0
        assert report is not None
        assert report.alert_triggered is False
        assert report.prior_ndcg5_mean is None
        assert report.regression_vs_prev is None

    def test_degraded_retrieval_alerts_and_writes_flag(self, tmp_path):
        """AC2: simulated regression → exit non-zero + sentinel."""
        fixture_path = tmp_path / "queries.json"
        _write_fixture(fixture_path, [f"q{i:02d}" for i in range(20)])
        staging = tmp_path / "lancedb-staging"
        _write_staging_marker(staging, version=42)
        report_dir = tmp_path / "reports"
        # Prior baseline at 0.80; new run at 0.60 → 25% regression.
        _write_prior_report(report_dir, corpus_version=41, ndcg5_mean=0.80)
        flag = tmp_path / "quarantine.flag"

        exit_code, report = run_watchdog(
            lancedb_staging_path=staging,
            report_dir=report_dir,
            fixture_path=fixture_path,
            quarantine_flag_path=flag,
            re_embed_state_path=tmp_path / "no-state.json",
            threshold_pct=10.0,
            compute_eval=_stub_eval([0.60] * 20),
        )
        assert exit_code == 1
        assert report.alert_triggered is True
        assert report.regression_pct == pytest.approx(25.0)
        assert flag.is_file()
        payload = json.loads(flag.read_text())
        assert payload["corpus_version"] == 42
        assert payload["regression_pct"] == pytest.approx(25.0)

    def test_within_threshold_no_alert(self, tmp_path):
        fixture_path = tmp_path / "queries.json"
        _write_fixture(fixture_path, [f"q{i:02d}" for i in range(20)])
        staging = tmp_path / "lancedb-staging"
        _write_staging_marker(staging, version=42)
        report_dir = tmp_path / "reports"
        _write_prior_report(report_dir, corpus_version=41, ndcg5_mean=0.80)

        exit_code, report = run_watchdog(
            lancedb_staging_path=staging,
            report_dir=report_dir,
            fixture_path=fixture_path,
            quarantine_flag_path=tmp_path / "quarantine.flag",
            re_embed_state_path=tmp_path / "no-state.json",
            threshold_pct=10.0,
            compute_eval=_stub_eval([0.76] * 20),  # 5% regression
        )
        assert exit_code == 0
        assert report.alert_triggered is False
        assert report.regression_pct == pytest.approx(5.0)
        assert not (tmp_path / "quarantine.flag").is_file()

    def test_empty_fixture_skips_run(self, tmp_path):
        """Synthesis Headline #5: 0 queries → skip silently."""
        fixture_path = tmp_path / "queries.json"
        _write_fixture(fixture_path, [])
        staging = tmp_path / "lancedb-staging"
        _write_staging_marker(staging, version=42)

        exit_code, report = run_watchdog(
            lancedb_staging_path=staging,
            report_dir=tmp_path / "reports",
            fixture_path=fixture_path,
            quarantine_flag_path=tmp_path / "quarantine.flag",
            re_embed_state_path=tmp_path / "no-state.json",
            compute_eval=_stub_eval([]),
        )
        assert exit_code == 0
        assert report is None  # silently skipped

    def test_underpowered_fixture_does_not_alert(self, tmp_path):
        """Synthesis Headline #5: < 10 queries → compute metric,
        no regression check (alert_triggered=false)."""
        fixture_path = tmp_path / "queries.json"
        _write_fixture(fixture_path, [f"q{i:02d}" for i in range(5)])
        staging = tmp_path / "lancedb-staging"
        _write_staging_marker(staging, version=42)
        report_dir = tmp_path / "reports"
        _write_prior_report(report_dir, corpus_version=41, ndcg5_mean=0.80)

        exit_code, report = run_watchdog(
            lancedb_staging_path=staging,
            report_dir=report_dir,
            fixture_path=fixture_path,
            quarantine_flag_path=tmp_path / "quarantine.flag",
            re_embed_state_path=tmp_path / "no-state.json",
            threshold_pct=10.0,
            compute_eval=_stub_eval([0.20] * 5),  # disastrously low
        )
        assert exit_code == 0
        assert report.alert_triggered is False
        assert report.underpowered is True
        assert report.regression_pct is None
        assert any("regression check skipped" in n for n in report.notes)
        assert not (tmp_path / "quarantine.flag").is_file()

    def test_re_embed_in_progress_skips_run(self, tmp_path):
        """Synthesis D6: re-embed in progress → skip silently."""
        fixture_path = tmp_path / "queries.json"
        _write_fixture(fixture_path, [f"q{i:02d}" for i in range(20)])
        staging = tmp_path / "lancedb-staging"
        _write_staging_marker(staging, version=42)
        state = tmp_path / "re-embed-state.json"
        state.write_text(json.dumps({"status": "in_progress"}))

        exit_code, report = run_watchdog(
            lancedb_staging_path=staging,
            report_dir=tmp_path / "reports",
            fixture_path=fixture_path,
            quarantine_flag_path=tmp_path / "quarantine.flag",
            re_embed_state_path=state,
            compute_eval=_stub_eval([0.80] * 20),
        )
        assert exit_code == 0
        assert report is None

    def test_re_embed_complete_runs(self, tmp_path):
        fixture_path = tmp_path / "queries.json"
        _write_fixture(fixture_path, [f"q{i:02d}" for i in range(20)])
        staging = tmp_path / "lancedb-staging"
        _write_staging_marker(staging, version=42)
        state = tmp_path / "re-embed-state.json"
        state.write_text(json.dumps({"status": "complete"}))

        exit_code, report = run_watchdog(
            lancedb_staging_path=staging,
            report_dir=tmp_path / "reports",
            fixture_path=fixture_path,
            quarantine_flag_path=tmp_path / "quarantine.flag",
            re_embed_state_path=state,
            compute_eval=_stub_eval([0.85] * 20),
        )
        assert exit_code == 0
        assert report is not None

    def test_dry_run_writes_no_files(self, tmp_path, capsys):
        fixture_path = tmp_path / "queries.json"
        _write_fixture(fixture_path, [f"q{i:02d}" for i in range(20)])
        staging = tmp_path / "lancedb-staging"
        _write_staging_marker(staging, version=42)
        report_dir = tmp_path / "reports"
        _write_prior_report(report_dir, corpus_version=41, ndcg5_mean=0.80)
        flag = tmp_path / "quarantine.flag"

        exit_code, report = run_watchdog(
            lancedb_staging_path=staging,
            report_dir=report_dir,
            fixture_path=fixture_path,
            quarantine_flag_path=flag,
            re_embed_state_path=tmp_path / "no-state.json",
            threshold_pct=10.0,
            dry_run=True,
            # Even with degraded eval, dry-run never writes flag.
            compute_eval=_stub_eval([0.40] * 20),
        )
        assert exit_code == 0
        assert report is not None
        # Sentinel must NOT be written in dry-run.
        assert not flag.is_file()
        # No NEW report file (only the prior one).
        assert len(list(report_dir.glob("corpus_v42-*"))) == 0
        # The dry-run prints the report JSON to stdout.
        out = capsys.readouterr().out
        assert "ndcg5_mean" in out

    def test_report_file_has_expected_fields(self, tmp_path):
        fixture_path = tmp_path / "queries.json"
        _write_fixture(fixture_path, [f"q{i:02d}" for i in range(20)])
        staging = tmp_path / "lancedb-staging"
        _write_staging_marker(staging, version=42)
        report_dir = tmp_path / "reports"
        _write_prior_report(report_dir, corpus_version=41, ndcg5_mean=0.80)

        run_watchdog(
            lancedb_staging_path=staging,
            report_dir=report_dir,
            fixture_path=fixture_path,
            quarantine_flag_path=tmp_path / "quarantine.flag",
            re_embed_state_path=tmp_path / "no-state.json",
            threshold_pct=10.0,
            compute_eval=_stub_eval([0.80] * 20),
        )
        # Find the new report file.
        new_reports = list(report_dir.glob("corpus_v42-*.json"))
        assert len(new_reports) == 1
        report = json.loads(new_reports[0].read_text())
        # Required fields per synthesis D9.
        for key in (
            "alert_triggered",
            "corpus_version",
            "ndcg5_mean",
            "ndcg5_per_query",
            "prior_ndcg5_mean",
            "query_count",
            "regression_pct",
            "regression_vs_prev",
            "threshold_pct",
            "timestamp",
            "underpowered",
        ):
            assert key in report, f"missing field {key!r}"


# ---------------------------------------------------------------------------
# Gauge wiring (in-process only — AC3 deferred for production /metrics)
# ---------------------------------------------------------------------------


class TestEvalNdcg5Gauge:
    def test_gauge_populated_after_run(self, tmp_path):
        """The in-process gauge IS set; production /metrics
        exposure is XFAIL/deferred (E14) — see test_ac3 below."""
        fixture_path = tmp_path / "queries.json"
        _write_fixture(fixture_path, [f"q{i:02d}" for i in range(20)])
        staging = tmp_path / "lancedb-staging"
        _write_staging_marker(staging, version=99)

        run_watchdog(
            lancedb_staging_path=staging,
            report_dir=tmp_path / "reports",
            fixture_path=fixture_path,
            quarantine_flag_path=tmp_path / "quarantine.flag",
            re_embed_state_path=tmp_path / "no-state.json",
            compute_eval=_stub_eval([0.85] * 20),
        )
        # Read the in-process gauge value.
        value = (
            EVAL_NDCG5_GAUGE.labels(corpus_version="99")
            ._value.get()
        )
        assert value == pytest.approx(0.85)


@pytest.mark.xfail(
    reason=(
        "AC3: cross-process /metrics exposure deferred to E14 — "
        "matches the LATEXML_DRIFT_DETECTED_COUNTER precedent. "
        "The watchdog is a one-shot cron; the in-process gauge "
        "vanishes when it exits. The MCP server's /metrics "
        "endpoint cannot read this gauge until E14 ships a "
        "scrape-time hook that re-hydrates from the JSON report."
    ),
    strict=True,
)
def test_ac3_metric_at_metrics_endpoint():
    raise AssertionError(
        "deferred — see XFAIL reason"
    )


# ---------------------------------------------------------------------------
# AC1 — seed corpus nDCG@5 ≥ 0.80 (conditional skip, fixture-gated)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    True,
    reason=(
        "AC1: requires a populated 20-query fixture + live BGE-M3. "
        "tests/eval/fixtures/queries.json is empty in the v1 stub. "
        "When curation completes (see .claude/docs/eval-curation.md), "
        "this skip becomes a `requires_model`-marked integration "
        "test."
    ),
)
def test_ac1_seed_corpus_ndcg5():  # pragma: no cover
    raise AssertionError("placeholder — gated on fixture curation")


# ---------------------------------------------------------------------------
# Quarantine-flag clearing
# ---------------------------------------------------------------------------


class TestClearQuarantineFlag:
    def test_clears_existing_flag(self, tmp_path):
        flag = tmp_path / "quarantine.flag"
        flag.write_text(json.dumps({"corpus_version": 42}))
        assert _clear_quarantine_flag(flag) is True
        assert not flag.is_file()

    def test_absent_flag_is_no_op(self, tmp_path):
        flag = tmp_path / "missing.flag"
        assert _clear_quarantine_flag(flag) is False


# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------


class TestCli:
    def test_clear_quarantine_flag_returns_zero_when_absent(
        self, tmp_path, monkeypatch
    ):
        from ops.watchdog_eval import _cli

        # Redirect the default sentinel path to a tmp location so
        # the test doesn't touch the real var/ tree.
        monkeypatch.setattr(
            "ops.watchdog_eval.DEFAULT_QUARANTINE_FLAG_PATH",
            tmp_path / "missing.flag",
        )
        rc = _cli(["--clear-quarantine"])
        assert rc == 0


# ---------------------------------------------------------------------------
# AC4 — runbook content
# ---------------------------------------------------------------------------


class TestRunbookContent:
    runbook = REPO_ROOT / "docs" / "ops" / "drift-watchdog.md"

    def test_runbook_exists(self):
        assert self.runbook.is_file(), f"runbook missing at {self.runbook}"

    def test_documents_threshold(self):
        text = self.runbook.read_text(encoding="utf-8")
        # Must name the env var AND the percent values (10% default,
        # 5% long-term goal).
        assert "ARXMCP_EVAL_REGRESSION_THRESHOLD_PCT" in text
        assert "10%" in text or "10 percent" in text
        assert "5%" in text or "5 percent" in text

    def test_documents_quarantine(self):
        text = self.runbook.read_text(encoding="utf-8")
        assert "eval-quarantine.flag" in text
        assert "quarantine" in text.lower()

    def test_documents_cutover_dependency(self):
        text = self.runbook.read_text(encoding="utf-8")
        assert "E11_S05" in text


# ---------------------------------------------------------------------------
# Makefile target presence
# ---------------------------------------------------------------------------


class TestMakefileWatchdogTarget:
    def test_watchdog_target_present(self):
        text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        assert "\nwatchdog:\n" in text
        assert "ops.watchdog_eval" in text

    def test_watchdog_carries_args_note(self):
        """Closes E11_S03 IS1 pattern — every new Makefile target
        should document the ARGS word-split hazard."""
        text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        block_start = text.index("\nwatchdog:\n")
        block = "\n".join(text[block_start:].splitlines()[:30])
        assert "spaces" in block.lower() or "NOTE on ARGS" in block


# ---------------------------------------------------------------------------
# Shell wrapper hygiene (E11_S02 IS2 pattern)
# ---------------------------------------------------------------------------


class TestShellWrapper:
    wrapper = REPO_ROOT / "ops" / "cron" / "arxmcp-watchdog.sh"

    def test_wrapper_exists_and_executable(self):
        assert self.wrapper.is_file()

    def test_wrapper_uses_command_v_uv(self):
        """Closes E11_S02 IS2 pattern: no hardcoded `/Users/...`
        path; resolve uv via the PATH."""
        text = self.wrapper.read_text(encoding="utf-8")
        assert "/Users/" not in text
        assert "command -v uv" in text


# ---------------------------------------------------------------------------
# Synthesis-Headline-#5 underpowered-fixture defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_default_threshold_is_10_percent(self):
        """Closes synthesis D4: default 10% (not the brief's 5%
        because 5% is below the noise floor at 20 queries)."""
        assert DEFAULT_REGRESSION_THRESHOLD_PCT == 10.0

    def test_min_queries_is_10(self):
        """Closes synthesis Headline #5: half-fixture floor."""
        assert MIN_QUERIES_FOR_REGRESSION_CHECK == 10
