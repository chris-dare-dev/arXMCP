"""E14_S04 — tests for ``tools/quarterly_drill_reminder.sh``.

The shell script is intentionally simple (~80 LOC bash + an
embedded Python heredoc for date math) so the test surface is
also lean: invoke it as a subprocess with `--dry-run` and assert
exit-0 + the expected output shape. A pure-shell test gives us
real coverage of the heredoc + subshell composition.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "quarterly_drill_reminder.sh"


def test_script_present_and_executable():
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    # Executable bit is required for cron to invoke it.
    import os  # noqa: PLC0415

    assert os.access(SCRIPT, os.X_OK), (
        f"{SCRIPT} must be executable (chmod +x)"
    )


@pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash not on PATH"
)
def test_dry_run_exits_zero():
    """The brief AC explicitly names ``--dry-run`` as the
    test-able invocation path."""
    result = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, (
        f"dry-run failed: stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )


@pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash not on PATH"
)
def test_dry_run_does_not_write_reminder_file(tmp_path, monkeypatch):
    """--dry-run must NEVER write to disk. We can't easily redirect
    the script's REPO_ROOT, but we CAN run it from a clean tmp_path
    and assert no reminders/ subdir is created."""
    # The script resolves REPO_ROOT relative to its own location,
    # not the cwd. So we copy the script into a temp tree where
    # the parent (the new "REPO_ROOT") has no var/arxmcp/...
    # prior state, and assert nothing is created.
    new_repo = tmp_path / "fake-repo"
    (new_repo / "tools").mkdir(parents=True)
    new_script = new_repo / "tools" / SCRIPT.name
    new_script.write_bytes(SCRIPT.read_bytes())
    new_script.chmod(0o755)

    result = subprocess.run(
        ["bash", str(new_script), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0
    # The dry-run branch must NOT create any var/ subtree.
    assert not (new_repo / "var").exists(), (
        "dry-run wrote a var/ subtree — violates the AC"
    )


@pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash not on PATH"
)
def test_real_invocation_exits_zero(tmp_path):
    """Real invocation (no --dry-run, real calendar) must exit 0
    whether the operator is in-window or out-of-window.

    F5 rectification (E14_S04 adversary critique): the prior
    version ran the in-repo script directly, which would create
    `var/arxmcp/ops/reminders/quarterly-drill-...flag` inside
    the real repo tree on Mar 25–31 / Jun 24–30 / Sep 24–30 /
    Dec 25–31. Copy the script into a tmp_path fake repo so the
    test is calendar-independent.
    """
    new_repo = tmp_path / "fake-repo"
    (new_repo / "tools").mkdir(parents=True)
    new_script = new_repo / "tools" / SCRIPT.name
    new_script.write_bytes(SCRIPT.read_bytes())
    new_script.chmod(0o755)

    result = subprocess.run(
        ["bash", str(new_script)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, (
        f"failed: stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
    # Whether the test ran in or out of the 7-day window, the
    # fake repo's reminders/ (if it exists) must only contain
    # flag files for the upcoming quarter — never an empty-field
    # 'quarterly-drill--Q.flag' from a failed heredoc.
    reminders_dir = new_repo / "var" / "arxmcp" / "ops" / "reminders"
    if reminders_dir.is_dir():
        for f in reminders_dir.iterdir():
            assert "--Q" not in f.name, (
                f"empty-field flag file leaked: {f.name}"
            )


@pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash not on PATH"
)
def test_script_resolves_repo_root_via_bash_source():
    """Regression guard: the script must compute REPO_ROOT
    relative to its own location (BASH_SOURCE), not the cwd.
    Cron invokes the script via an absolute path; the operator's
    cwd at run-time is the user's home directory.
    """
    content = SCRIPT.read_text(encoding="utf-8")
    assert "BASH_SOURCE" in content, (
        "REPO_ROOT must be derived from BASH_SOURCE for cron "
        "compatibility — the script may be invoked from any cwd"
    )
    assert 'cd "${REPO_ROOT}"' in content, (
        "REPO_ROOT must be the working directory before any "
        "relative path resolution"
    )


@pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash not on PATH"
)
def test_aborts_when_python_heredoc_fails(tmp_path):
    """F1 rectification (E14_S04 adversary critique): if the
    embedded python3 heredoc fails (DAYS_UNTIL becomes empty),
    the script MUST exit non-zero with an actionable error
    message rather than silently writing a malformed flag.

    We inject a fake `python3` shim on PATH that always exits 1.
    The script's `if ! DRILL_TUPLE=...; then exit 1; fi` guard
    must catch this and propagate.
    """

    # Stage the script in a fresh tree so var/ stays clean.
    new_repo = tmp_path / "fake-repo"
    (new_repo / "tools").mkdir(parents=True)
    new_script = new_repo / "tools" / SCRIPT.name
    new_script.write_bytes(SCRIPT.read_bytes())
    new_script.chmod(0o755)

    # Fake python3 that exits 1 (simulates date-math failure).
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text("#!/bin/bash\nexit 1\n")
    fake_python.chmod(0o755)

    env = {
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "HOME": str(tmp_path),
    }
    result = subprocess.run(
        ["bash", str(new_script)],
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
        check=False,
    )
    # Must exit non-zero AND must not have created any reminder
    # files inside the fake-repo tree.
    assert result.returncode != 0, (
        f"expected non-zero exit when python heredoc fails; "
        f"got stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "ERROR: quarterly date math" in result.stderr, (
        f"expected actionable error message; got {result.stderr!r}"
    )
    # No quarterly-drill--Q.flag with empty fields written.
    reminders_dir = (
        new_repo / "var" / "arxmcp" / "ops" / "reminders"
    )
    if reminders_dir.exists():
        for f in reminders_dir.iterdir():
            assert "--Q" not in f.name, (
                f"empty-field flag file leaked: {f.name}"
            )


@pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash not on PATH"
)
def test_short_circuit_logic_short_circuits_for_out_of_window():
    """When out-of-window, the script writes nothing to disk.
    Real-calendar dependency: if pytest runs in the 7 days
    before a quarter mark this test SKIPS (the in-window branch
    DOES write to disk, which is correct behavior).
    """
    import datetime  # noqa: PLC0415

    now = datetime.datetime.now(datetime.UTC).date()
    year = now.year
    marks = [
        datetime.date(year, 1, 1),
        datetime.date(year, 4, 1),
        datetime.date(year, 7, 1),
        datetime.date(year, 10, 1),
        datetime.date(year + 1, 1, 1),
    ]
    next_mark = min(m for m in marks if m > now)
    days = (next_mark - now).days
    if days <= 7:
        pytest.skip(
            f"within 7 days of {next_mark} (T-{days}d) — "
            "real-calendar test cannot verify out-of-window behaviour"
        )
    # Out of window. Run, assert exit 0, and assert NO new
    # reminder file appeared for the upcoming quarter mark.
    qmap = {1: 1, 4: 2, 7: 3, 10: 4}
    quarter = qmap[next_mark.month]
    reminder_path = (
        REPO_ROOT / "var" / "arxmcp" / "ops" / "reminders"
        / f"quarterly-drill-{next_mark.year}-Q{quarter}.flag"
    )
    pre_exists = reminder_path.is_file()
    result = subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True,
        timeout=15, check=False,
    )
    assert result.returncode == 0
    post_exists = reminder_path.is_file()
    # If the file didn't exist before, it must not exist now.
    if not pre_exists:
        assert not post_exists, (
            f"out-of-window run created {reminder_path} (T-{days}d "
            "from quarter — should not have written)"
        )
