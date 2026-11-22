"""Tests for the 200K cutover activation (E11_S05).

Pure unit tests with synthetic fixtures + mocked subprocess /
HTTP boundaries. No live server, no live restic.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from arxmcp.ops.cutover import (
    NDCG5_MIN,
    CriterionResult,
    CutoverError,
    check_criterion_1_seed_eval,
    check_criterion_2_watchdog,
    check_criterion_3_re_embed_state,
    check_criterion_4_restore_drill,
    perform_directory_swap,
    perform_rollback,
    poll_readyz,
    run_cutover,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_marker(path: Path, version: int, embedder: str = "bge-m3@aaaaaaaa") -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "corpus-version.json").write_text(
        json.dumps(
            {
                "version": version,
                "chunker_version": "v1.0",
                "embedder_version": embedder,
                "paper_count": 50,
                "chunk_count": 1000,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _write_aggregate(eval_dir: Path, version: int, ndcg5: float) -> None:
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / f"aggregate-{version}.json").write_text(
        json.dumps(
            {
                "corpus_version": version,
                "ndcg5_mean": ndcg5,
                "query_count": 20,
                "timestamp": "2026-05-15T00:00:00Z",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _write_watchdog_report(
    report_dir: Path,
    *,
    version: int,
    ndcg5: float,
    alert: bool = False,
) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    out = report_dir / f"corpus_v{version}-20260515T000000.json"
    out.write_text(
        json.dumps(
            {
                "corpus_version": version,
                "ndcg5_mean": ndcg5,
                "alert_triggered": alert,
                "timestamp": "2026-05-15T00:00:00Z",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return out


def _write_re_embed_state(path: Path, status: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"status": status}, sort_keys=True),
        encoding="utf-8",
    )


def _write_drill_flag(
    path: Path, smoke_check: str = "passed", *, days_ago: float = 3.0
) -> None:
    import datetime as _dt

    restored_at = _dt.datetime.now(_dt.UTC) - _dt.timedelta(days=days_ago)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "smoke_check": smoke_check,
                "snapshot_id": "abc12345",
                "restored_at": restored_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Activation criteria — individual checks
# ---------------------------------------------------------------------------


class TestCriterion3ReEmbedState:
    """Closes brief criterion 3 — re-embed status check."""

    def test_absent_state_passes(self, tmp_path):
        r = check_criterion_3_re_embed_state(tmp_path / "missing.json")
        assert r.ok is True
        assert "no re-embed-state.json" in r.reason or "no " in r.reason

    def test_complete_passes(self, tmp_path):
        state = tmp_path / "re-embed-state.json"
        _write_re_embed_state(state, "complete")
        r = check_criterion_3_re_embed_state(state)
        assert r.ok is True

    def test_complete_with_failures_passes(self, tmp_path):
        state = tmp_path / "re-embed-state.json"
        _write_re_embed_state(state, "complete_with_failures")
        r = check_criterion_3_re_embed_state(state)
        assert r.ok is True

    def test_in_progress_fails(self, tmp_path):
        state = tmp_path / "re-embed-state.json"
        _write_re_embed_state(state, "in_progress")
        r = check_criterion_3_re_embed_state(state)
        assert r.ok is False

    def test_malformed_fails(self, tmp_path):
        state = tmp_path / "re-embed-state.json"
        state.write_text("{not json")
        r = check_criterion_3_re_embed_state(state)
        assert r.ok is False
        assert "malformed" in r.reason


class TestCriterion4RestoreDrill:
    """Closes brief criterion 4 — restore-drill sentinel."""

    def test_missing_flag_fails(self, tmp_path):
        r = check_criterion_4_restore_drill(tmp_path / "missing.flag")
        assert r.ok is False
        assert "src/arxmcp/ops/restore_drill.sh" in r.reason

    def test_passed_flag_passes(self, tmp_path):
        flag = tmp_path / "drill.flag"
        _write_drill_flag(flag, "passed")
        r = check_criterion_4_restore_drill(flag)
        assert r.ok is True
        assert "abc12345" in r.reason

    def test_failed_smoke_check_fails(self, tmp_path):
        flag = tmp_path / "drill.flag"
        _write_drill_flag(flag, "failed")
        r = check_criterion_4_restore_drill(flag)
        assert r.ok is False
        assert "expected 'passed'" in r.reason


class TestCriterion1SeedEval:
    """Closes brief criterion 1 — seed nDCG@5 ≥ 0.80."""

    def test_passes_when_aggregate_present(self, tmp_path):
        active = tmp_path / "lancedb"
        _write_marker(active, version=7)
        eval_dir = tmp_path / "eval"
        _write_aggregate(eval_dir, version=7, ndcg5=0.83)
        r = check_criterion_1_seed_eval(
            active_marker_path=active / "corpus-version.json",
            aggregate_dir=eval_dir,
        )
        assert r.ok is True

    def test_fails_when_aggregate_missing(self, tmp_path):
        active = tmp_path / "lancedb"
        _write_marker(active, version=7)
        r = check_criterion_1_seed_eval(
            active_marker_path=active / "corpus-version.json",
            aggregate_dir=tmp_path / "no-eval",
        )
        assert r.ok is False
        assert "make eval" in r.reason

    def test_fails_when_ndcg_below_threshold(self, tmp_path):
        active = tmp_path / "lancedb"
        _write_marker(active, version=7)
        eval_dir = tmp_path / "eval"
        _write_aggregate(eval_dir, version=7, ndcg5=0.70)
        r = check_criterion_1_seed_eval(
            active_marker_path=active / "corpus-version.json",
            aggregate_dir=eval_dir,
        )
        assert r.ok is False
        assert f"< {NDCG5_MIN}" in r.reason


class TestCriterion2Watchdog:
    """Closes brief criterion 2 — staging watchdog + no quarantine."""

    def test_passes_when_report_clean(self, tmp_path):
        staging = tmp_path / "lancedb-staging"
        _write_marker(staging, version=42)
        reports = tmp_path / "eval-reports"
        _write_watchdog_report(reports, version=42, ndcg5=0.85, alert=False)
        r = check_criterion_2_watchdog(
            staging_marker_path=staging / "corpus-version.json",
            report_dir=reports,
            quarantine_flag_path=tmp_path / "no-quarantine.flag",
        )
        assert r.ok is True

    def test_fails_when_quarantine_flag_present(self, tmp_path):
        staging = tmp_path / "lancedb-staging"
        _write_marker(staging, version=42)
        reports = tmp_path / "eval-reports"
        _write_watchdog_report(reports, version=42, ndcg5=0.85, alert=False)
        flag = tmp_path / "quarantine.flag"
        flag.write_text(json.dumps({"corpus_version": 42}))
        r = check_criterion_2_watchdog(
            staging_marker_path=staging / "corpus-version.json",
            report_dir=reports,
            quarantine_flag_path=flag,
        )
        assert r.ok is False
        assert "quarantine flag present" in r.reason

    def test_fails_when_alert_triggered(self, tmp_path):
        staging = tmp_path / "lancedb-staging"
        _write_marker(staging, version=42)
        reports = tmp_path / "eval-reports"
        _write_watchdog_report(reports, version=42, ndcg5=0.85, alert=True)
        r = check_criterion_2_watchdog(
            staging_marker_path=staging / "corpus-version.json",
            report_dir=reports,
            quarantine_flag_path=tmp_path / "no-quarantine.flag",
        )
        assert r.ok is False
        assert "alert_triggered" in r.reason

    def test_fails_when_no_report_for_staging_version(self, tmp_path):
        staging = tmp_path / "lancedb-staging"
        _write_marker(staging, version=42)
        reports = tmp_path / "eval-reports"
        _write_watchdog_report(reports, version=41, ndcg5=0.85)  # wrong version
        r = check_criterion_2_watchdog(
            staging_marker_path=staging / "corpus-version.json",
            report_dir=reports,
            quarantine_flag_path=tmp_path / "no-quarantine.flag",
        )
        assert r.ok is False
        assert "no watchdog report" in r.reason

    def test_fails_when_ndcg_below_threshold(self, tmp_path):
        staging = tmp_path / "lancedb-staging"
        _write_marker(staging, version=42)
        reports = tmp_path / "eval-reports"
        _write_watchdog_report(reports, version=42, ndcg5=0.60, alert=False)
        r = check_criterion_2_watchdog(
            staging_marker_path=staging / "corpus-version.json",
            report_dir=reports,
            quarantine_flag_path=tmp_path / "no-quarantine.flag",
        )
        assert r.ok is False
        assert f"< {NDCG5_MIN}" in r.reason


# ---------------------------------------------------------------------------
# Directory swap + rollback
# ---------------------------------------------------------------------------


class TestDirectorySwap:
    def test_swap_renames_both_directories(self, tmp_path):
        active = tmp_path / "lancedb"
        staging = tmp_path / "lancedb-staging"
        rollback = tmp_path / "lancedb-prev"
        active.mkdir()
        (active / "marker-OLD").write_text("old")
        staging.mkdir()
        (staging / "marker-NEW").write_text("new")

        perform_directory_swap(
            active_path=active,
            staging_path=staging,
            rollback_path=rollback,
        )
        # active now has the staging marker.
        assert (active / "marker-NEW").is_file()
        # rollback has the old marker.
        assert (rollback / "marker-OLD").is_file()
        # staging path is gone.
        assert not staging.exists()

    def test_refuses_if_rollback_path_exists(self, tmp_path):
        active = tmp_path / "lancedb"
        staging = tmp_path / "lancedb-staging"
        rollback = tmp_path / "lancedb-prev"
        active.mkdir()
        staging.mkdir()
        rollback.mkdir()
        with pytest.raises(CutoverError, match="rollback path"):
            perform_directory_swap(
                active_path=active,
                staging_path=staging,
                rollback_path=rollback,
            )

    def test_refuses_if_active_missing(self, tmp_path):
        staging = tmp_path / "lancedb-staging"
        staging.mkdir()
        with pytest.raises(CutoverError, match="active path"):
            perform_directory_swap(
                active_path=tmp_path / "missing",
                staging_path=staging,
                rollback_path=tmp_path / "prev",
            )

    def test_refuses_if_staging_missing(self, tmp_path):
        active = tmp_path / "lancedb"
        active.mkdir()
        with pytest.raises(CutoverError, match="staging path"):
            perform_directory_swap(
                active_path=active,
                staging_path=tmp_path / "missing",
                rollback_path=tmp_path / "prev",
            )


class TestRollback:
    def test_rollback_reverses_swap(self, tmp_path):
        active = tmp_path / "lancedb"
        rollback = tmp_path / "lancedb-prev"
        active.mkdir()
        (active / "marker-CURRENT").write_text("current")
        rollback.mkdir()
        (rollback / "marker-PREV").write_text("prev")

        failed_dir = perform_rollback(
            active_path=active,
            rollback_path=rollback,
        )
        # active now has the prev marker.
        assert (active / "marker-PREV").is_file()
        # the failed cutover state was preserved.
        assert (failed_dir / "marker-CURRENT").is_file()
        # rollback path is gone (consumed by the rename).
        assert not rollback.exists()

    def test_rollback_refuses_if_no_prev(self, tmp_path):
        active = tmp_path / "lancedb"
        active.mkdir()
        with pytest.raises(CutoverError, match="rollback path"):
            perform_rollback(
                active_path=active,
                rollback_path=tmp_path / "missing-prev",
            )


# ---------------------------------------------------------------------------
# /readyz polling
# ---------------------------------------------------------------------------


class TestPollReadyz:
    def test_returns_true_on_200(self):
        class _FakeResp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        calls = {"n": 0}

        def _urlopen(_url, **_):
            calls["n"] += 1
            return _FakeResp()

        assert poll_readyz(
            url="http://x/readyz",
            total_timeout=10.0,
            interval=0.1,
            sleep=lambda _t: None,
            monotonic=lambda: 0.0,
            urlopen=_urlopen,
        ) is True
        assert calls["n"] == 1

    def test_returns_false_on_timeout(self):
        # The urlopen never returns 200; the deadline expires.
        clock = {"now": 0.0}

        def _monotonic():
            return clock["now"]

        def _sleep(t):
            clock["now"] += t

        import urllib.error as _ue

        def _urlopen(_url, **_):
            raise _ue.URLError("connection refused")

        assert poll_readyz(
            url="http://x/readyz",
            total_timeout=1.0,
            interval=0.2,
            sleep=_sleep,
            monotonic=_monotonic,
            urlopen=_urlopen,
        ) is False


# ---------------------------------------------------------------------------
# run_cutover end-to-end (with mocked criteria + swap)
# ---------------------------------------------------------------------------


class TestRunCutover:
    def test_dry_run_with_all_passing(self, tmp_path):
        active = tmp_path / "lancedb"
        _write_marker(active, version=7)
        staging = tmp_path / "lancedb-staging"
        _write_marker(staging, version=42)
        eval_dir = tmp_path / "eval"
        _write_aggregate(eval_dir, version=7, ndcg5=0.85)
        reports = tmp_path / "eval-reports"
        _write_watchdog_report(reports, version=42, ndcg5=0.83)
        state = tmp_path / "re-embed-state.json"
        _write_re_embed_state(state, "complete")
        drill = tmp_path / "restore-drill-passed.flag"
        _write_drill_flag(drill)

        with patch(
            "arxmcp.ops.cutover.verify_lancedb_integrity",
            return_value=CriterionResult(
                "LanceDB integrity (staging)", True, "synthetic stub"
            ),
        ):
            rc = run_cutover(
                active_path=active,
                staging_path=staging,
                rollback_path=tmp_path / "lancedb-prev",
                aggregate_dir=eval_dir,
                watchdog_report_dir=reports,
                quarantine_flag_path=tmp_path / "no-quarantine.flag",
                re_embed_state_path=state,
                restore_drill_flag_path=drill,
                dry_run=True,
            )
        assert rc == 0
        # active + staging are untouched on dry-run.
        assert (active / "corpus-version.json").is_file()
        assert (staging / "corpus-version.json").is_file()

    def test_refuses_when_any_criterion_fails(self, tmp_path):
        active = tmp_path / "lancedb"
        _write_marker(active, version=7)
        staging = tmp_path / "lancedb-staging"
        _write_marker(staging, version=42)
        # Aggregate is MISSING → C1 fails.

        with patch(
            "arxmcp.ops.cutover.verify_lancedb_integrity",
            return_value=CriterionResult(
                "LanceDB integrity (staging)", True, "stub"
            ),
        ):
            rc = run_cutover(
                active_path=active,
                staging_path=staging,
                rollback_path=tmp_path / "lancedb-prev",
                aggregate_dir=tmp_path / "no-eval",
                watchdog_report_dir=tmp_path / "no-reports",
                quarantine_flag_path=tmp_path / "no-quarantine.flag",
                re_embed_state_path=tmp_path / "no-state.json",
                restore_drill_flag_path=tmp_path / "no-drill.flag",
                dry_run=True,
            )
        assert rc == 1

    def test_full_swap_when_all_pass(self, tmp_path):
        active = tmp_path / "lancedb"
        _write_marker(active, version=7)
        (active / "OLD-data").write_text("old")
        staging = tmp_path / "lancedb-staging"
        _write_marker(staging, version=42)
        (staging / "NEW-data").write_text("new")
        eval_dir = tmp_path / "eval"
        _write_aggregate(eval_dir, version=7, ndcg5=0.85)
        reports = tmp_path / "eval-reports"
        _write_watchdog_report(reports, version=42, ndcg5=0.83)
        state = tmp_path / "re-embed-state.json"
        _write_re_embed_state(state, "complete")
        drill = tmp_path / "restore-drill-passed.flag"
        _write_drill_flag(drill)

        with (
            patch(
                "arxmcp.ops.cutover.verify_lancedb_integrity",
                return_value=CriterionResult(
                    "LanceDB integrity (staging)", True, "stub"
                ),
            ),
            patch(
                "arxmcp.ops.cutover.wait_for_promoted_server",
                return_value=(True, 42),
            ) as wait,
        ):
            rc = run_cutover(
                active_path=active,
                staging_path=staging,
                rollback_path=tmp_path / "lancedb-prev",
                aggregate_dir=eval_dir,
                watchdog_report_dir=reports,
                quarantine_flag_path=tmp_path / "no-quarantine.flag",
                re_embed_state_path=state,
                restore_drill_flag_path=drill,
                skip_post_activation=True,
            )
        assert rc == 0
        assert wait.call_args.kwargs["expected_version"] == 42
        # Swap completed: active now has the staging data + marker.
        assert (active / "NEW-data").is_file()
        marker = json.loads((active / "corpus-version.json").read_text())
        assert marker["version"] == 42
        # rollback path has the old data.
        rollback = tmp_path / "lancedb-prev"
        assert (rollback / "OLD-data").is_file()
        # staging path is gone.
        assert not staging.exists()


# ---------------------------------------------------------------------------
# Bash wrapper hygiene
# ---------------------------------------------------------------------------


class TestCutoverShellWrapper:
    wrapper = REPO_ROOT / "src" / "arxmcp" / "ops" / "cutover.sh"

    def test_wrapper_exists_and_executable(self):
        assert self.wrapper.is_file()
        assert os.access(self.wrapper, os.X_OK)

    def test_wrapper_no_hardcoded_user_path(self):
        text = self.wrapper.read_text(encoding="utf-8")
        # E11_S02 IS2 lesson — no /Users/ workstation-specific
        # paths. Ignore the substring inside the documentation
        # comment that explains the lesson.
        for line in text.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            assert "/Users/" not in line, (
                f"hardcoded /Users/ path in non-comment line: {line!r}"
            )
        assert "command -v uv" in text

    def test_wrapper_set_euo_pipefail(self):
        text = self.wrapper.read_text(encoding="utf-8")
        assert "set -euo pipefail" in text


# ---------------------------------------------------------------------------
# Makefile target
# ---------------------------------------------------------------------------


class TestMakefileCutoverTarget:
    def test_cutover_target_present(self):
        text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        assert "\ncutover:\n" in text
        assert "arxmcp.ops.cutover" in text

    def test_cutover_carries_args_note(self):
        text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        block_start = text.index("\ncutover:\n")
        block = "\n".join(text[block_start:].splitlines()[:30])
        assert "spaces" in block.lower() or "NOTE on ARGS" in block


# ---------------------------------------------------------------------------
# Rectification regression guards
# ---------------------------------------------------------------------------


class TestCutoverShellWrapperFlock:
    """Closes infra-safety IS1: cutover.sh must acquire a flock
    before invoking python — concurrent operator invocations can
    interleave the two os.rename calls and leave the active path
    missing."""

    def test_wrapper_acquires_flock(self):
        text = (REPO_ROOT / "src" / "arxmcp" / "ops" / "cutover.sh").read_text(
            encoding="utf-8"
        )
        assert "flock -n" in text
        assert ".cutover.lock" in text
        assert "command -v flock" in text


class TestCrossFilesystemSwapRefused:
    """Closes adversary F8: the atomic-swap contract requires
    all three paths on the same filesystem. Mocked `os.stat` to
    return different `st_dev` values."""

    def test_refuses_when_active_and_staging_span_filesystems(
        self, tmp_path
    ):
        active = tmp_path / "lancedb"
        staging = tmp_path / "lancedb-staging"
        rollback = tmp_path / "lancedb-prev"
        active.mkdir()
        staging.mkdir()

        real_stat = os.stat

        def _fake_stat(path, *args, **kwargs):
            real = real_stat(path, *args, **kwargs)
            # Return a different st_dev for the staging path.
            if str(path).endswith("lancedb-staging"):
                class _S:
                    st_dev = real.st_dev + 1
                return _S()
            return real

        from arxmcp.ops.cutover import perform_directory_swap

        with (
            patch("arxmcp.ops.cutover.os.stat", side_effect=_fake_stat),
            pytest.raises(CutoverError, match="cross-filesystem"),
        ):
            perform_directory_swap(
                active_path=active,
                staging_path=staging,
                rollback_path=rollback,
            )


class TestPostActivationAbsoluteFloor:
    """Closes adversary F2: AC5 must enforce the absolute
    nDCG@5 ≥ 0.80 floor, not just the watchdog's relative
    regression."""

    def test_subprocess_ok_but_low_ndcg_fails(self, tmp_path):
        from arxmcp.ops.cutover import run_post_activation_watchdog

        # Write a synthetic watchdog report with ndcg below the
        # floor but alert_triggered=false (regression within
        # threshold).
        report_dir = tmp_path / "eval-reports"
        report_dir.mkdir()

        class _FakeCompleted:
            returncode = 0
            stderr = ""

        def _runner(*_args, **_kw):
            # The watchdog subprocess writes its report during the run.
            (report_dir / "corpus_v42-20260515T000000.json").write_text(
                json.dumps(
                    {
                    "corpus_version": 42,
                    "ndcg5_mean": 0.75,
                    "alert_triggered": False,
                    "timestamp": "2026-05-15T00:00:00Z",
                }
                )
            )
            return _FakeCompleted()

        r = run_post_activation_watchdog(
            corpus_version=42,
            active_path=tmp_path / "lancedb",
            report_dir=report_dir,
            ndcg5_min=0.80,
            runner=_runner,
        )
        assert r.ok is False
        assert "0.7500" in r.reason or "< 0.8" in r.reason

    def test_subprocess_ok_and_high_ndcg_passes(self, tmp_path):
        from arxmcp.ops.cutover import run_post_activation_watchdog

        report_dir = tmp_path / "eval-reports"
        report_dir.mkdir()

        class _FakeCompleted:
            returncode = 0
            stderr = ""

        def _runner(*_args, **_kw):
            # The watchdog subprocess writes its report during the run.
            (report_dir / "corpus_v42-20260515T000000.json").write_text(
                json.dumps(
                    {
                    "corpus_version": 42,
                    "ndcg5_mean": 0.85,
                    "alert_triggered": False,
                    "timestamp": "2026-05-15T00:00:00Z",
                }
                )
            )
            return _FakeCompleted()

        r = run_post_activation_watchdog(
            corpus_version=42,
            active_path=tmp_path / "lancedb",
            report_dir=report_dir,
            ndcg5_min=0.80,
            runner=_runner,
        )
        assert r.ok is True

    def test_subprocess_nonzero_fails(self, tmp_path):
        from arxmcp.ops.cutover import run_post_activation_watchdog

        class _FakeCompleted:
            returncode = 1
            stderr = "synthetic failure"

        r = run_post_activation_watchdog(
            corpus_version=42,
            active_path=tmp_path / "lancedb",
            report_dir=tmp_path / "missing",
            ndcg5_min=0.80,
            runner=lambda *_args, **_kw: _FakeCompleted(),
        )
        assert r.ok is False
        assert "exited 1" in r.reason

    def test_underpowered_run_passes(self, tmp_path):
        """When the fixture is too small, the watchdog report has
        ndcg5_mean=null + underpowered=true. AC5 passes by skip
        (not a real measurement)."""
        from arxmcp.ops.cutover import run_post_activation_watchdog

        report_dir = tmp_path / "eval-reports"
        report_dir.mkdir()

        class _FakeCompleted:
            returncode = 0
            stderr = ""

        def _runner(*_args, **_kw):
            # The watchdog subprocess writes its report during the run.
            (report_dir / "corpus_v42-20260515T000000.json").write_text(
                json.dumps(
                    {
                    "corpus_version": 42,
                    "ndcg5_mean": None,
                    "alert_triggered": False,
                    "underpowered": True,
                    "query_count": 4,
                    "timestamp": "2026-05-15T00:00:00Z",
                }
                )
            )
            return _FakeCompleted()

        r = run_post_activation_watchdog(
            corpus_version=42,
            active_path=tmp_path / "lancedb",
            report_dir=report_dir,
            ndcg5_min=0.80,
            runner=_runner,
        )
        assert r.ok is True
        assert "underpowered" in r.reason


class TestBackupWrapperRectifications:
    """Closes F4+IS2, F5+IS3, IS4 patches to the backup wrapper."""

    wrapper = REPO_ROOT / "src" / "arxmcp" / "ops" / "cron" / "arxmcp-backup.sh"

    def test_two_phase_sentinel(self):
        text = self.wrapper.read_text(encoding="utf-8")
        # F4+IS2: an in-flight sentinel must be written after the
        # snapshot lands but BEFORE forget runs, so a forget failure
        # cannot leave the operator looking at yesterdays record.
        #
        # arXMCP#202 re-pointed this token: it used to be the ad-hoc
        # string "backup_complete_forget_pending", which no consumer
        # state matched. It is now the shared vocabulary's `running`
        # (src/arxmcp/ops/cron/backup-status-lib.sh + src/arxmcp/server/backup_status.py).
        assert '"status": "${ARXMCP_BACKUP_STATE_RUNNING}"' in text
        # The write must still precede the forget invocation.
        assert text.index('"${ARXMCP_BACKUP_STATE_RUNNING}"') < text.index(
            "restic forget --prune"
        )

    def test_connectivity_check_always_on(self):
        text = self.wrapper.read_text(encoding="utf-8")
        # F5+IS3: ARXMCP_RESTIC_CHECK is exported before sourcing.
        assert "export ARXMCP_RESTIC_CHECK=1" in text

    def test_restic_exit_3_handled_as_partial(self):
        text = self.wrapper.read_text(encoding="utf-8")
        # IS4: restic exit 3 = partial; treat differently from
        # total failure.
        assert "RESTIC_BACKUP_EXIT" in text
        assert "partial" in text
        # Restic exit 3 specifically called out.
        assert "-eq 3" in text


# ---------------------------------------------------------------------------
# The server answering after a swap must be serving the promoted corpus
# ---------------------------------------------------------------------------


class _FakeHttp:
    """Answers /readyz with 200 and /status with a scripted version."""

    def __init__(self, versions: list[int]) -> None:
        self._versions = versions

    def __call__(self, url, **_kw):  # noqa: ANN001
        outer = self

        class _Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                version = (
                    outer._versions.pop(0)
                    if len(outer._versions) > 1
                    else outer._versions[0]
                )
                return json.dumps(
                    {"checks": {"corpus:version": [{"observedValue": version}]}}
                ).encode()

        return _Resp()


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class TestWaitForPromotedServer:
    def test_a_server_still_on_the_old_corpus_does_not_pass(self):
        from arxmcp.ops.cutover import wait_for_promoted_server

        clock = _Clock()
        ok, seen = wait_for_promoted_server(
            expected_version=42,
            total_timeout=20.0,
            interval=5.0,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
            urlopen=_FakeHttp([7]),
        )
        assert (ok, seen) == (False, 7)

    def test_passes_once_the_restarted_server_reports_the_promoted_version(self):
        from arxmcp.ops.cutover import wait_for_promoted_server

        clock = _Clock()
        ok, seen = wait_for_promoted_server(
            expected_version=42,
            total_timeout=60.0,
            interval=5.0,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
            urlopen=_FakeHttp([7, 7, 42]),
        )
        assert (ok, seen) == (True, 42)

    def test_run_cutover_fails_when_the_old_server_keeps_answering(
        self, tmp_path, capsys
    ):
        active = tmp_path / "lancedb"
        _write_marker(active, version=7)
        staging = tmp_path / "lancedb-staging"
        _write_marker(staging, version=42)
        eval_dir = tmp_path / "eval"
        _write_aggregate(eval_dir, version=7, ndcg5=0.85)
        reports = tmp_path / "eval-reports"
        _write_watchdog_report(reports, version=42, ndcg5=0.83)
        state = tmp_path / "re-embed-state.json"
        _write_re_embed_state(state, "complete")
        drill = tmp_path / "restore-drill-passed.flag"
        _write_drill_flag(drill)

        with (
            patch(
                "arxmcp.ops.cutover.verify_lancedb_integrity",
                return_value=CriterionResult(
                    "LanceDB integrity (staging)", True, "stub"
                ),
            ),
            patch(
                "arxmcp.ops.cutover.wait_for_promoted_server",
                return_value=(False, 7),
            ),
            patch("arxmcp.ops.cutover.run_post_activation_watchdog") as post,
        ):
            rc = run_cutover(
                active_path=active,
                staging_path=staging,
                rollback_path=tmp_path / "lancedb-prev",
                aggregate_dir=eval_dir,
                watchdog_report_dir=reports,
                quarantine_flag_path=tmp_path / "no-quarantine.flag",
                re_embed_state_path=state,
                restore_drill_flag_path=drill,
            )
        assert rc == 1
        assert "serving corpus_v7, not the promoted corpus_v42" in capsys.readouterr().out
        post.assert_not_called()


class TestPostActivationReadsItsOwnReport:
    @staticmethod
    def _report(report_dir: Path, version: int, ndcg5: float) -> Path:
        path = report_dir / f"corpus_v{version}-20260515T000000.json"
        path.write_text(
            json.dumps(
                {"corpus_version": version, "ndcg5_mean": ndcg5,
                 "alert_triggered": False}
            )
        )
        return path

    class _Completed:
        returncode = 0
        stderr = ""

    def test_a_report_written_before_the_run_is_not_used(self, tmp_path):
        from arxmcp.ops.cutover import run_post_activation_watchdog

        report_dir = tmp_path / "eval-reports"
        report_dir.mkdir()
        stale = self._report(report_dir, 42, 0.95)
        os.utime(stale, (1000.0, 1000.0))

        r = run_post_activation_watchdog(
            corpus_version=42,
            active_path=tmp_path / "lancedb",
            report_dir=report_dir,
            runner=lambda *_a, **_k: self._Completed(),
            wall_clock=lambda: 2000.0,
        )
        assert r.ok is False
        assert "wrote no report for corpus_v42" in r.reason

    def test_a_report_for_another_version_is_not_used(self, tmp_path):
        from arxmcp.ops.cutover import run_post_activation_watchdog

        report_dir = tmp_path / "eval-reports"
        report_dir.mkdir()

        def _runner(*_a, **_k):
            # The nightly watchdog's report for some other tree.
            self._report(report_dir, 41, 0.95)
            return self._Completed()

        r = run_post_activation_watchdog(
            corpus_version=42,
            active_path=tmp_path / "lancedb",
            report_dir=report_dir,
            runner=_runner,
        )
        assert r.ok is False


class TestRestoreDrillFreshness:
    def test_a_drill_from_last_week_passes(self, tmp_path):
        from arxmcp.ops.cutover import check_criterion_4_restore_drill

        flag = tmp_path / "restore-drill-passed.flag"
        _write_drill_flag(flag, days_ago=7)
        assert check_criterion_4_restore_drill(flag).ok is True

    def test_a_drill_older_than_a_quarter_fails(self, tmp_path):
        from arxmcp.ops.cutover import check_criterion_4_restore_drill

        flag = tmp_path / "restore-drill-passed.flag"
        _write_drill_flag(flag, days_ago=400)
        r = check_criterion_4_restore_drill(flag)
        assert r.ok is False
        assert "400 days ago" in r.reason

    def test_a_flag_without_a_timestamp_fails(self, tmp_path):
        from arxmcp.ops.cutover import check_criterion_4_restore_drill

        flag = tmp_path / "restore-drill-passed.flag"
        flag.write_text(json.dumps({"smoke_check": "passed"}))
        r = check_criterion_4_restore_drill(flag)
        assert r.ok is False
        assert "restored_at" in r.reason


# ---------------------------------------------------------------------------
# Staging vector-index coverage
# ---------------------------------------------------------------------------


def _staging_chunks(paper_id: str, *, stmt: int, proof: int = 0):
    """``stmt`` stmt chunks then ``proof`` proof chunks for ``paper_id``."""
    from arxmcp.ingest.chunk import CHUNKER_VERSION, ChunkRecord

    kinds = ["stmt"] * stmt + ["proof"] * proof
    return [
        ChunkRecord(
            chunk_id=f"arxiv:{paper_id}:{i:016x}",
            paper_id=paper_id,
            kind=kind,
            section_path=[],
            theorem_name=None,
            theorem_label=None,
            body_text=f"{paper_id} {kind} {i}",
            body_tokens=f"{kind} {i}",
            preamble_ref=None,
            chunker_version=CHUNKER_VERSION,
        )
        for i, kind in enumerate(kinds)
    ]


def _write_staging(path: Path, chunks, *, build_indices: bool, seed: int = 0) -> None:
    """Write ``chunks`` into a real staging LanceDB (marker included)."""
    import numpy as np

    from arxmcp.ingest.embedder import EMBEDDER_VERSION, EMBEDDING_DIM
    from arxmcp.ingest.schema import EmbedRecord
    from arxmcp.ingest.store import write_chunks

    rng = np.random.default_rng(seed)

    def _vectors(n: int):
        if n == 0:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        v = rng.standard_normal((n, EMBEDDING_DIM)).astype(np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    stmt = [c for c in chunks if c.kind == "stmt"]
    proof = [c for c in chunks if c.kind == "proof"]
    record = EmbedRecord(
        chunk_ids_stmt=[c.chunk_id for c in stmt],
        embedding_stmt=_vectors(len(stmt)),
        chunk_ids_proof=[c.chunk_id for c in proof],
        embedding_proof=_vectors(len(proof)),
        embedder_version=EMBEDDER_VERSION,
    )
    write_chunks(chunks, record, lancedb_path=path, build_indices=build_indices)


def _index_names(path: Path) -> set[str]:
    from arxmcp.ingest.corpus import open_chunks_table, read_corpus_version

    info = read_corpus_version(lancedb_path=path)
    table = open_chunks_table(lancedb_path=path, version=info.version)
    return {cfg.name for cfg in table.list_indices()}


class TestStagingVectorIndexCoverage:
    """``arxmcp.ingest.re_embed`` writes staging with ``build_indices=False`` and
    builds the indexes once at the end; C3 accepts ``complete_with_failures``.
    The integrity probe is where cutover must refuse a staging table whose
    vector columns are not fully indexed, or search silently scans flat."""

    def test_unindexed_staging_is_refused(self, tmp_path):
        from arxmcp.ops.cutover import verify_lancedb_integrity

        staging = tmp_path / "lancedb-staging"
        _write_staging(
            staging, _staging_chunks("2301.00001", stmt=4, proof=2),
            build_indices=False,
        )
        assert _index_names(staging) == set()

        r = verify_lancedb_integrity(staging)

        assert r.ok is False
        assert "embedding_stmt holds 4 vectors but has no index" in r.reason
        assert "embedding_proof holds 2 vectors but has no index" in r.reason

    def test_fully_indexed_staging_passes(self, tmp_path):
        from arxmcp.ops.cutover import verify_lancedb_integrity

        staging = tmp_path / "lancedb-staging"
        _write_staging(
            staging, _staging_chunks("2301.00001", stmt=4, proof=2),
            build_indices=True,
        )
        assert {"embedding_stmt_idx", "embedding_proof_idx"} <= _index_names(staging)

        r = verify_lancedb_integrity(staging)

        assert r.ok is True, r.reason
        assert r.reason == "chunks=6; vector indexes cover every row"

    def test_all_null_proof_column_needs_no_index(self, tmp_path):
        from arxmcp.ops.cutover import verify_lancedb_integrity

        staging = tmp_path / "lancedb-staging"
        _write_staging(
            staging, _staging_chunks("2301.00001", stmt=4), build_indices=True,
        )
        # _create_indices skips a column with no vectors.
        names = _index_names(staging)
        assert "embedding_stmt_idx" in names
        assert "embedding_proof_idx" not in names

        r = verify_lancedb_integrity(staging)

        assert r.ok is True, r.reason

    def test_rows_outside_the_index_are_refused(self, tmp_path):
        from arxmcp.ops.cutover import verify_lancedb_integrity

        staging = tmp_path / "lancedb-staging"
        _write_staging(
            staging, _staging_chunks("2301.00001", stmt=4, proof=2),
            build_indices=True,
        )
        _write_staging(
            staging, _staging_chunks("2301.00002", stmt=3),
            build_indices=False, seed=1,
        )

        r = verify_lancedb_integrity(staging)

        assert r.ok is False
        assert "embedding_stmt_idx misses 3 rows" in r.reason
        # The appended rows carry no proof vector, but they sit outside the
        # proof index too, so a proof search scans them flat.
        assert "embedding_proof_idx misses 3 rows" in r.reason

    def test_index_without_stats_fails_closed(self):
        from types import SimpleNamespace

        from arxmcp.ops.cutover import vector_index_gaps

        table = SimpleNamespace(
            list_indices=lambda: [
                SimpleNamespace(name="embedding_stmt_idx", columns=["embedding_stmt"])
            ],
            index_stats=lambda _name: None,
            count_rows=lambda where: 5 if "embedding_stmt" in where else 0,
        )

        assert vector_index_gaps(table) == ["embedding_stmt_idx reports no stats"]

    def test_run_cutover_refuses_unindexed_complete_with_failures_staging(
        self, tmp_path
    ):
        """The reviewed scenario end to end: every other criterion passes,
        the re-embed ended ``complete_with_failures``, staging is unindexed."""
        from arxmcp.ingest.corpus import read_corpus_version
        from arxmcp.ingest.store import CORPUS_VERSION_MARKER_NAME

        active = tmp_path / "lancedb"
        _write_marker(active, version=7)
        staging = tmp_path / "lancedb-staging"
        _write_staging(
            staging, _staging_chunks("2301.00001", stmt=4, proof=2),
            build_indices=False,
        )
        staging_version = read_corpus_version(lancedb_path=staging).version
        eval_dir = tmp_path / "eval"
        _write_aggregate(eval_dir, version=7, ndcg5=0.85)
        reports = tmp_path / "eval-reports"
        _write_watchdog_report(reports, version=staging_version, ndcg5=0.83)
        state = tmp_path / "re-embed-state.json"
        _write_re_embed_state(state, "complete_with_failures")
        drill = tmp_path / "restore-drill-passed.flag"
        _write_drill_flag(drill)

        # The readiness wait is stubbed so a gate that wrongly passes fails
        # here on the swap, not after a 60 s wait for the server.
        with patch(
            "arxmcp.ops.cutover.wait_for_promoted_server",
            return_value=(True, staging_version),
        ):
            rc = run_cutover(
                active_path=active,
                staging_path=staging,
                rollback_path=tmp_path / "lancedb-prev",
                aggregate_dir=eval_dir,
                watchdog_report_dir=reports,
                quarantine_flag_path=tmp_path / "no-quarantine.flag",
                re_embed_state_path=state,
                restore_drill_flag_path=drill,
                skip_post_activation=True,
            )

        assert rc == 1
        assert (staging / CORPUS_VERSION_MARKER_NAME).is_file()
        assert not (tmp_path / "lancedb-prev").exists()
