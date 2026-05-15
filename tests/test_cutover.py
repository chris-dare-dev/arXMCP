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

from ops.cutover import (
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


def _write_drill_flag(path: Path, smoke_check: str = "passed") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "smoke_check": smoke_check,
                "snapshot_id": "abc12345",
                "restored_at": "2026-05-15T00:00:00Z",
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
        assert "ops/restore_drill.sh" in r.reason

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
            "ops.cutover.verify_lancedb_integrity",
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
            "ops.cutover.verify_lancedb_integrity",
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
                "ops.cutover.verify_lancedb_integrity",
                return_value=CriterionResult(
                    "LanceDB integrity (staging)", True, "stub"
                ),
            ),
            patch("ops.cutover.poll_readyz", return_value=True),
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
    wrapper = REPO_ROOT / "ops" / "cutover.sh"

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
        assert "ops.cutover" in text

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
        text = (REPO_ROOT / "ops" / "cutover.sh").read_text(
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

        from ops.cutover import perform_directory_swap

        with (
            patch("ops.cutover.os.stat", side_effect=_fake_stat),
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
        from ops.cutover import run_post_activation_watchdog

        # Write a synthetic watchdog report with ndcg below the
        # floor but alert_triggered=false (regression within
        # threshold).
        report_dir = tmp_path / "eval-reports"
        report_dir.mkdir()
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

        class _FakeCompleted:
            returncode = 0
            stderr = ""

        r = run_post_activation_watchdog(
            active_path=tmp_path / "lancedb",
            report_dir=report_dir,
            ndcg5_min=0.80,
            runner=lambda *_args, **_kw: _FakeCompleted(),
        )
        assert r.ok is False
        assert "0.7500" in r.reason or "< 0.8" in r.reason

    def test_subprocess_ok_and_high_ndcg_passes(self, tmp_path):
        from ops.cutover import run_post_activation_watchdog

        report_dir = tmp_path / "eval-reports"
        report_dir.mkdir()
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

        class _FakeCompleted:
            returncode = 0
            stderr = ""

        r = run_post_activation_watchdog(
            active_path=tmp_path / "lancedb",
            report_dir=report_dir,
            ndcg5_min=0.80,
            runner=lambda *_args, **_kw: _FakeCompleted(),
        )
        assert r.ok is True

    def test_subprocess_nonzero_fails(self, tmp_path):
        from ops.cutover import run_post_activation_watchdog

        class _FakeCompleted:
            returncode = 1
            stderr = "synthetic failure"

        r = run_post_activation_watchdog(
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
        from ops.cutover import run_post_activation_watchdog

        report_dir = tmp_path / "eval-reports"
        report_dir.mkdir()
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

        class _FakeCompleted:
            returncode = 0
            stderr = ""

        r = run_post_activation_watchdog(
            active_path=tmp_path / "lancedb",
            report_dir=report_dir,
            ndcg5_min=0.80,
            runner=lambda *_args, **_kw: _FakeCompleted(),
        )
        assert r.ok is True
        assert "underpowered" in r.reason


class TestBackupWrapperRectifications:
    """Closes F4+IS2, F5+IS3, IS4 patches to the backup wrapper."""

    wrapper = REPO_ROOT / "ops" / "cron" / "arxmcp-backup.sh"

    def test_two_phase_sentinel(self):
        text = self.wrapper.read_text(encoding="utf-8")
        # F4+IS2: a partial sentinel with status
        # backup_complete_forget_pending must appear.
        assert "backup_complete_forget_pending" in text

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


class TestPasswordFilePermsDocumentation:
    """Closes adversary F3: install instructions must NOT tell
    the operator to use mode 0400 owned by root, because the
    systemd unit runs as User=arxmcp."""

    def test_template_documents_service_user_install(self):
        text = (
            REPO_ROOT / "ops" / "restic-env.sh.template"
        ).read_text(encoding="utf-8")
        # The fix instruction must include -o <service-user>
        # rather than -o root.
        assert "service-user" in text or "-o arxmcp" in text
        # And the F3 callout must be present.
        assert "F3" in text or "service user" in text.lower()

    def test_runbook_documents_service_user_install(self):
        text = (
            REPO_ROOT / "docs" / "ops" / "backup-restore.md"
        ).read_text(encoding="utf-8")
        # The runbook must NOT use -o root for the install line
        # (the line that was broken).
        # Look for the install line that's the actual operator
        # instruction (under "Create the password file").
        lower = text.lower()
        assert "service user" in lower or "-o arxmcp" in text


# ---------------------------------------------------------------------------
# README runbook link (cutover + backup)
# ---------------------------------------------------------------------------


class TestReadmeRunbookLinks:
    def test_cutover_runbook_linked(self):
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "docs/ops/cutover-runbook.md" in text

    def test_backup_runbook_linked(self):
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "docs/ops/backup-restore.md" in text


# ---------------------------------------------------------------------------
# Runbook content (AC3)
# ---------------------------------------------------------------------------


class TestCutoverRunbookContent:
    runbook = REPO_ROOT / "docs" / "ops" / "cutover-runbook.md"

    def test_runbook_exists(self):
        assert self.runbook.is_file()

    def test_states_all_four_criteria(self):
        text = self.runbook.read_text(encoding="utf-8")
        # The runbook must enumerate all 4 activation criteria.
        assert "C1" in text or "Criterion 1" in text
        assert "C2" in text or "Criterion 2" in text
        assert "C3" in text or "Criterion 3" in text
        assert "C4" in text or "Criterion 4" in text

    def test_states_rollback_time(self):
        text = self.runbook.read_text(encoding="utf-8")
        # AC3 requires the rollback time estimate.
        assert "30 second" in text.lower() or "< 30s" in text or "30s" in text

    def test_documents_directory_swap_not_marker_rewrite(self):
        text = self.runbook.read_text(encoding="utf-8")
        # Synthesis Headline #1 must be load-bearing in the runbook.
        assert "directory swap" in text.lower() or "atomic rename" in text.lower()
