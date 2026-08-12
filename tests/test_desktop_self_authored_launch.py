"""desktop-distribution-m10 — the supervisor authors its own launch plan.

Scope fence, stated once: this file proves the SELF-AUTHORED arm, the one
taken when ``ARXMCP_DESKTOP_LAUNCH_PLAN`` is absent. It deliberately lives
outside ``tests/test_desktop_child.py`` so that file — every m5 lifecycle and
m6 fault-matrix gate, and the only two writers of that variable in the tree —
stays byte-identical, which is m10's own third acceptance criterion.

Two things this file does NOT prove, recorded here rather than implied:

* The end-to-end arm runs against the **fixture sidecar** staged in m7's
  onedir SHAPE, not against the real ~0.75 GB PyInstaller bundle. No
  committed gate builds the Rust supervisor and the frozen child in the same
  session (``desktop-conformance`` builds the binaries; ``desktop-package-check``
  builds the bundle), so a test needing both would either skip — which the
  zero-skip guard turns into a failure — or fail outright. The frozen-artifact
  proof belongs with ``desktop-distribution-m15``, which assembles the ``.app``
  and re-points the containment check at the bundle root.
* ``std::env::current_exe()`` is the root of the containment check, and the
  Rust stdlib documents it as NOT a security primitive. The relocated- and
  tampered-sidecar cases are closed; the PATH-search and hardlink classes the
  stdlib names are accepted residual risk.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from server.application_paths import _platform_data_root
from server.desktop_child import COMPONENT as _DESKTOP_CHILD_COMPONENT


def _desktop_package_module():
    """Load the PyInstaller packaging driver by path.

    It lives outside any importable package (`apps/desktop/pyinstaller/`), so
    `tests/test_desktop_package.py` already loads it this way; reuse the shape
    rather than re-declaring its constants here.
    """
    import importlib.util

    path = (
        Path(__file__).resolve().parents[1]
        / "apps"
        / "desktop"
        / "pyinstaller"
        / "desktop_package.py"
    )
    spec = importlib.util.spec_from_file_location("_m10_desktop_package", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"could not load the packaging driver at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

if sys.platform == "win32":  # pragma: no cover - POSIX is the §4.1 authority
    pytest.skip(
        "the staged-executable harness needs POSIX exec bits and SIGKILL; the "
        "self-authoring arm itself is platform-neutral and its unit tests run "
        "everywhere `cargo test` does",
        allow_module_level=True,
    )

REPO_ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR_BIN_ENV = "DESKTOP_SUPERVISOR_BIN"
FIXTURE_BIN_ENV = "ARXMCP_FIXTURE_SIDECAR"
PLAN_ENV = "ARXMCP_DESKTOP_LAUNCH_PLAN"

#: `arxmcp_desktop.spec`'s `name=` for BOTH the EXE and the COLLECT, which is
#: what makes m7's onedir `<root>/arxmcp-desktop-child/arxmcp-desktop-child`.
#: DERIVED from the packaging driver, never re-declared: staging the harness
#: from a private literal made both sides of the proof move together, so a
#: rename broke the shipped double-click path with every gate still green
#: (m10 critique H4/M4/M5/M6).
CHILD_PAYLOAD_DIR = _desktop_package_module().BUNDLE_NAME
#: `server/desktop_child.py::COMPONENT` — what the frozen child calls itself,
#: and therefore what the self-authored plan must name. Imported for the same
#: reason.
CHILD_COMPONENT = _DESKTOP_CHILD_COMPONENT
#: The pre-m10 failure string at `main.rs`'s `load_plan()` None arm. Its
#: REMOVAL is the RED state these tests discriminate against.
PRE_M10_FAILURE = "ARXMCP_DESKTOP_LAUNCH_PLAN is required"
_SUPERVISOR_MAIN_RS = (
    REPO_ROOT / "apps" / "desktop" / "crates" / "supervisor" / "src" / "main.rs"
)
_HEX64 = re.compile(rb"(?<![0-9a-fA-F])[0-9a-f]{64}(?![0-9a-fA-F])")
_LAUNCH_TIMEOUT = 180.0


def test_the_pre_m10_required_plan_failure_no_longer_exists() -> None:
    """RED state, source half: before m10 an absent plan variable reached
    ``fail("ARXMCP_DESKTOP_LAUNCH_PLAN is required")`` -> ``exit(2)``.

    Unmarked on purpose — it runs on every ``make test``, so a revert of the
    self-authoring arm is caught without the desktop stack. The runtime half
    lives in ``test_red_state_missing_payload_still_exits_two`` below."""
    source = _SUPERVISOR_MAIN_RS.read_text(encoding="utf-8")
    live = [
        line
        for line in source.splitlines()
        if PRE_M10_FAILURE in line and not line.lstrip().startswith("//")
    ]
    assert not live, f"pre-m10 failure arm is still live: {live}"
    # ... and the comment that records it is retained, so the next reader
    # learns what the RED state was rather than rediscovering it.
    assert PRE_M10_FAILURE in source


def _supervisor_binary() -> Path:
    supervisor = os.environ.get(SUPERVISOR_BIN_ENV)
    if not supervisor or not Path(supervisor).is_file():
        pytest.fail(
            f"{SUPERVISOR_BIN_ENV} must point at the built supervisor binary "
            f"(run via `make desktop-conformance`)"
        )
    return Path(supervisor)


def _fixture_binary() -> Path:
    fixture = os.environ.get(FIXTURE_BIN_ENV)
    if not fixture or not Path(fixture).is_file():
        pytest.fail(
            f"{FIXTURE_BIN_ENV} must point at the built fixture sidecar "
            f"(run via `make desktop-conformance`)"
        )
    return Path(fixture)


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _stage(tmp_path: Path, *, with_child: bool) -> tuple[Path, Path]:
    """Reproduce the layout the self-authoring arm reads: a supervisor
    executable with (or deliberately without) m7's onedir directory as its
    SIBLING. Returns ``(staged supervisor, staged HOME)``."""
    base = tmp_path / "stage"
    base.mkdir(parents=True)
    supervisor = base / "supervisor"
    shutil.copy2(_supervisor_binary(), supervisor)
    _make_executable(supervisor)
    if with_child:
        payload = base / CHILD_PAYLOAD_DIR
        payload.mkdir()
        child = payload / CHILD_PAYLOAD_DIR
        shutil.copy2(_fixture_binary(), child)
        _make_executable(child)
    home = tmp_path / "home"
    home.mkdir()
    return supervisor, home


def _plan_free_env(home: Path, **extra: str) -> dict[str, str]:
    """The production shape: no launch-plan variable, no ambient ``ARXMCP_*``.

    The plan variable is *removed*, not overwritten — that absence is the
    entire input this milestone adds a behavior for."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("ARXMCP_")}
    env.pop(PLAN_ENV, None)
    # Every variable `_platform_data_root` consults is pinned, not inherited:
    # an ambient XDG_DATA_HOME on the runner would send the supervisor to a
    # data root the test then looks for in the wrong place.
    for key in ("XDG_DATA_HOME", "USERPROFILE", "LOCALAPPDATA"):
        env.pop(key, None)
    env["HOME"] = str(home)
    env.update(extra)
    return env


def _expected_data_root(home: Path) -> Path:
    """The Python side of the pair, called with the SAME environment the
    supervisor will see."""
    return _platform_data_root({"HOME": str(home)}).resolve()


def _events(root: Path) -> list[dict]:
    path = root / "logs" / "supervisor-events.ndjson"
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _by_name(root: Path, name: str) -> list[dict]:
    return [event for event in _events(root) if event["event"] == name]


def _wait_for_event(
    root: Path, name: str, timeout: float, process: subprocess.Popen
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = _by_name(root, name)
        if found:
            return found[0]
        if process.poll() is not None:
            raise RuntimeError(
                f"supervisor exited {process.returncode} before {name!r}; "
                f"events: {_events(root)}"
            )
        time.sleep(0.05)
    raise TimeoutError(f"event {name!r} not seen in {timeout}s; events: {_events(root)}")


def _pid_is_gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OSError):
        return True
    return False


def _reap(process: subprocess.Popen, root: Path) -> None:
    """The self-authored plan is ``smoke: false`` by construction, so nothing
    ends this launch on its own — the supervisor AND the child it spawned are
    this test's to clean up, m6 critique H3/H6's rule."""
    spawned = {event["fields"]["child_pid"] for event in _by_name(root, "child-spawn")}
    orphans: list[int] = []
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=15)
        # m10 critique M16: this is the FIRST `smoke: false` launch any gate
        # runs — the first where the supervisor does not self-exit after one
        # cycle — so it is the first chance to observe the stdin-EOF
        # parent-lifetime lease and the grace->TERM->KILL ladder on the shape
        # that actually ships. Unconditionally SIGKILLing every recorded pid
        # made an orphan and a clean reap produce the same green result.
        # Record the verdict BEFORE the safety net runs, then still run it, so
        # a failing assertion never leaves a live child behind.
        settle = time.monotonic() + 5.0
        for pid in spawned:
            while not _pid_is_gone(pid) and time.monotonic() < settle:
                time.sleep(0.05)
            if not _pid_is_gone(pid):
                orphans.append(pid)
    for pid in spawned:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            continue
    deadline = time.monotonic() + 5.0
    for pid in spawned:
        while not _pid_is_gone(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert _pid_is_gone(pid), f"self-authored child {pid} survived teardown"
    assert not orphans, (
        f"children {orphans} outlived the supervisor's own shutdown on the "
        f"smoke:false arm — the parent-lifetime lease did not reap them, and "
        f"only this test's SIGKILL safety net did"
    )


@pytest.mark.requires_desktop_stack
def test_red_state_missing_payload_still_exits_two(tmp_path: Path) -> None:
    """RED state, runtime half.

    With the plan variable absent and NO sibling payload the supervisor still
    exits 2 — the ``exit(2)`` path is intact — but for a reason that names the
    self-authoring arm. A test asserting only the new arm's success would pass
    against a tree where the arm was never wired, which is what the criterion
    forbids; the two assertions below are what discriminate."""
    supervisor, home = _stage(tmp_path, with_child=False)
    completed = subprocess.run(  # noqa: S603 - staged copy of our own binary
        [str(supervisor)],
        env=_plan_free_env(home),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 2, completed
    assert "self-authored plan: child payload root missing" in completed.stderr
    assert PRE_M10_FAILURE not in completed.stderr, (
        "the supervisor still refuses an absent plan variable outright; the "
        "self-authoring arm did not run"
    )
    # No plan means no data root either: the arm refuses before creating one.
    assert not _expected_data_root(home).exists()


@pytest.mark.requires_desktop_stack
def test_bound_identity_still_refuses_a_component_mismatch(tmp_path: Path) -> None:
    """The GREEN arm tells the fixture to answer to the frozen child's
    component, and the fixture echoes back the identity it accepted — so on
    its own that arm would pass even if the supervisor compared nothing at
    all (m10 critique M14).

    Drive the override to a component the self-authored plan does NOT name
    and require the launch to never reach ``child-bound``. That is what makes
    the green arm's identity agreement evidence rather than tautology."""
    supervisor, home = _stage(tmp_path, with_child=True)
    env = _plan_free_env(
        home, DESKTOP_FIXTURE_COMPONENT=CHILD_COMPONENT + "-not-the-plan"
    )
    root = _expected_data_root(home)
    process = subprocess.Popen(  # noqa: S603 - staged copy of our own binary
        [str(supervisor)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        # It must get far enough to have derived and authored a plan...
        _wait_for_event(root, "supervisor-started", 60.0, process)
        # ...and then must NOT accept the mismatched child.
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            assert not _by_name(root, "child-bound"), (
                "the supervisor accepted a child whose component the plan "
                "does not name — the bound-identity comparison is dead"
            )
            if process.poll() is not None:
                break
            time.sleep(0.1)
    finally:
        _reap(process, root)


@pytest.mark.requires_desktop_stack
def test_self_authored_launch_reaches_ready_and_window(tmp_path: Path) -> None:
    """The GREEN arm: plan variable ABSENT, m7's onedir shape staged beside
    the supervisor, all the way to a ready server and an ordered-in window.

    The child here is the fixture sidecar wearing the frozen child's component
    name (``DESKTOP_FIXTURE_COMPONENT``) — see this module's docstring for why
    the real bundle is m15's proof and not this one's."""
    supervisor, home = _stage(tmp_path, with_child=True)
    env = _plan_free_env(home, DESKTOP_FIXTURE_COMPONENT=CHILD_COMPONENT)
    root = _expected_data_root(home)
    process = subprocess.Popen(  # noqa: S603 - staged copy of our own binary
        [str(supervisor)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        # `data_root` was DERIVED, not supplied: the event log only exists at
        # this path if the Rust derivation matched the Python one.
        started = _wait_for_event(root, "supervisor-started", 60.0, process)
        assert started["fields"]["plan_source"] == "self-authored", started
        _wait_for_event(root, "child-bound", _LAUNCH_TIMEOUT, process)
        _wait_for_event(root, "child-ready", _LAUNCH_TIMEOUT, process)
        _wait_for_event(root, "mcp-smoke-ok", _LAUNCH_TIMEOUT, process)
        window = _wait_for_event(root, "window-ready", _LAUNCH_TIMEOUT, process)
        assert window["fields"]["window_ordered_in"] is True, window
        # smoke: false — the launch is still LIVE, which is the production
        # behavior a `smoke: true` self-authored plan would have broken.
        assert process.poll() is None, "a self-authored launch must not self-exit"
        # Exactly one spawn cycle — no retry, no second child. This does NOT
        # prove provenance: `child-spawn` carries only `child_pid`, no path
        # (m10 critique M9). Containment is proven where it is actually
        # enforced — `main.rs::tests::child_executable_escaping_the_payload_
        # root_is_rejected` and `::symlinked_payload_root_is_rejected` — plus
        # `lifecycle.rs`'s digest comparison, which refuses any child whose
        # bytes differ from `identity_file`.
        spawned = _by_name(root, "child-spawn")
        assert len(spawned) == 1, _events(root)
    finally:
        _reap(process, root)

    # AC: the startup token is generated per launch, never persisted. The test
    # cannot know it, so the m6 technique applies: every 64-hex string in every
    # persisted artifact must be the staged child's identity digest.
    payload_child = supervisor.parent / CHILD_PAYLOAD_DIR / CHILD_PAYLOAD_DIR
    allowed = {hashlib.sha256(payload_child.read_bytes()).hexdigest().encode("ascii")}
    for artifact in root.rglob("*"):
        if artifact.is_file():
            for match in set(_HEX64.findall(artifact.read_bytes())):
                assert match in allowed, (artifact, match[:12])


#: Rows exercise every branch of `_platform_data_root` that this platform can
#: reach, plus the variables the OTHER platforms' branches read — a Rust port
#: that consulted the wrong variable would diverge on one of these.
_PARITY_MATRIX: tuple[dict[str, str], ...] = (
    {"HOME": "/parity/home"},
    {"HOME": "/parity/home", "XDG_DATA_HOME": "/parity/xdg"},
    {"HOME": "/parity/home", "XDG_DATA_HOME": ""},
    {"HOME": "/parity/home", "LOCALAPPDATA": "C:/parity/local"},
    {"HOME": "/parity/home", "USERPROFILE": "/parity/profile"},
    {"HOME": "/parity/home", "USERPROFILE": ""},
    {"USERPROFILE": "/parity/profile"},
    {"HOME": "/parity/home with spaces/数学"},
    {"HOME": "/parity/home", "XDG_DATA_HOME": "/parity/xdg with spaces/数学"},
    # --- added by the m10 critique, each row a measured divergence ---
    # M1: `Path()` collapses `//` and `.` at construction; PathBuf does not,
    # so these rows derived DIFFERENT data roots before pathlib_normalize.
    {"HOME": "/parity//home"},
    {"HOME": "/parity/./home"},
    {"HOME": "/parity/home/"},
    # POSIX keeps exactly two leading slashes and collapses three or more.
    {"HOME": "//parity/home"},
    {"HOME": "///parity/home"},
    {"HOME": "/parity/home", "XDG_DATA_HOME": "/parity//xdg/./deep"},
) + (
    # M7: the platform's own base variable with NO home set — Python never
    # reads home on these rows, so the port must not refuse early either.
    #
    # Platform-conditional because the row is only REACHABLE where the branch
    # has a base variable of its own. macOS derives
    # `home/Library/Application Support` unconditionally, so "base set, home
    # absent" cannot occur there; a HOME-less row on macOS lands on the
    # DOCUMENTED divergence instead (Python falls back to `Path.home()`'s
    # passwd read, Rust refuses), which
    # `test_data_root_parity_has_exactly_one_documented_divergence` owns.
    # The per-platform laziness itself is pinned in Rust by
    # `main.rs::tests::the_home_lookup_is_lazy_like_pythons`, which runs on
    # every platform `cargo test` does.
    ({"XDG_DATA_HOME": "/parity/xdg"},)
    if sys.platform.startswith("linux")
    else ({"LOCALAPPDATA": "C:/parity/local"},)
    if sys.platform == "win32"
    else ()
)


@pytest.mark.requires_desktop_stack
@pytest.mark.parametrize("row", _PARITY_MATRIX, ids=range(len(_PARITY_MATRIX)))
def test_data_root_parity_with_python(row: dict[str, str]) -> None:
    """The two implementations are pinned by RUNNING both, never by reading
    them side by side. `_platform_data_root` is Python and the supervisor is
    Rust with no FFI bridge; a hand-copied port with no executable pin is the
    silent-drift hazard both research briefs named."""
    env = {"PATH": os.environ.get("PATH", ""), **row}
    completed = subprocess.run(  # noqa: S603 - our own built binary
        [str(_supervisor_binary()), "--print-data-root"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed
    expected = _platform_data_root(row).as_posix()
    assert completed.stdout.strip() == expected, completed


@pytest.mark.requires_desktop_stack
def test_data_root_parity_has_exactly_one_documented_divergence() -> None:
    """Python falls back to ``Path.home()`` (a passwd read) when neither
    ``HOME`` nor ``USERPROFILE`` is set; Rust refuses instead of guessing a
    home for a process about to create a data root there. Asserted, so the
    divergence is a recorded decision rather than an unnoticed gap."""
    completed = subprocess.run(  # noqa: S603 - our own built binary
        [str(_supervisor_binary()), "--print-data-root"],
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 2, completed
    assert "no HOME or USERPROFILE" in completed.stderr
    # Python, on the same input, answers rather than refusing.
    assert _platform_data_root({}).name == "arXMCP"


@pytest.mark.requires_desktop_stack
def test_the_environment_arm_is_unchanged_by_the_new_one(tmp_path: Path) -> None:
    """AC3's guard from this side: a *supplied* plan still wins over the
    layout. The staged tree has a perfectly good payload the self-authoring
    arm would accept, so a supervisor that ignored the variable would launch
    successfully — the malformed-plan refusal is what proves it did not."""
    supervisor, home = _stage(tmp_path, with_child=True)
    plan_path = tmp_path / "launch-plan.json"
    plan_path.write_text("{not json", encoding="utf-8")
    env = _plan_free_env(home)
    env[PLAN_ENV] = str(plan_path)
    completed = subprocess.run(  # noqa: S603 - staged copy of our own binary
        [str(supervisor)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 2, completed
    assert "launch plan malformed" in completed.stderr, completed.stderr
    assert "self-authored" not in completed.stderr, completed.stderr


def _main_rs_const(name: str) -> str:
    """Read a `const <name>: &str = "..."` literal out of the supervisor."""
    source = _SUPERVISOR_MAIN_RS.read_text(encoding="utf-8")
    match = re.search(
        rf'^const {re.escape(name)}: &str = "([^"]*)";', source, re.MULTILINE
    )
    if match is None:
        raise AssertionError(f"{name} is no longer a plain const in main.rs")
    return match.group(1)


def test_rust_layout_constants_match_their_python_sources() -> None:
    """The two constants that decide WHICH BINARY the supervisor executes are
    pinned by running the comparison, not by inspection.

    m10 critique H4/M4/M5/M6: `CHILD_PAYLOAD_DIR` and `CHILD_COMPONENT` were
    literals in Rust, duplicated again in this module, with nothing tying
    them to `desktop_package.BUNDLE_NAME` or `server.desktop_child.COMPONENT`.
    Renaming either broke the shipped double-click path at spawn or at
    bound-identity while `make test`, `make desktop-conformance` and
    `make desktop-package-check` all stayed green, because the end-to-end arm
    staged its own directory from its own literal and told the fixture the
    same literal — both sides of the proof moved together.

    Unmarked (critique M8): a Python-side rename must fail on every
    `make test`, not only under the desktop stack."""
    package = _desktop_package_module()
    assert _main_rs_const("CHILD_PAYLOAD_DIR") == package.BUNDLE_NAME
    assert _main_rs_const("CHILD_COMPONENT") == _DESKTOP_CHILD_COMPONENT
    # The onedir's executable shares the directory name; that is what makes
    # the layout `<root>/<name>/<name>`, which `child_payload_root` assumes.
    assert package.CHILD_EXE == package.BUNDLE_NAME


def test_supervisor_crate_version_matches_the_python_package_version() -> None:
    """`compose_self_authored_plan` sends the Rust crate version as the
    CHILD's expected executable-identity version.

    m10 critique H1/H3: `lifecycle.rs` puts `plan.version` in the launch
    frame's `ExecutableIdentity`, and `server/desktop_child.py` refuses the
    launch when it differs from its own `importlib.metadata.version("arxmcp")`.
    Those are two unrelated version lines that happened to be equal. Equal by
    assertion now: bump one without the other and the suite goes red, instead
    of shipping a double-click that dies at bound-identity."""
    workspace = (REPO_ROOT / "apps" / "desktop" / "Cargo.toml").read_text(
        encoding="utf-8"
    )
    crate = re.search(r'^version = "([^"]+)"', workspace, re.MULTILINE)
    assert crate is not None, "workspace [package] version not found"
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    python = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
    assert python is not None, "pyproject [project] version not found"
    assert crate.group(1) == python.group(1), (
        "the supervisor crate version and the arxmcp package version are "
        "compared for equality at launch; keep them in lockstep or stop "
        "deriving the child's identity version from the crate"
    )


def test_windows_data_root_branch_is_pinned_on_both_sides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Neither gate can reach the Windows branch on this host: the parity
    matrix runs the real binary (macOS) and the Rust unit test compares a
    `cfg!`-selected expectation.

    m10 critique M15: a one-sided edit would bifurcate the operator's data
    root with no error — the app derives root A while the CLI and every ops
    tool derive root B, so the app looks empty and ingest lands where it is
    never read. Pin both sides by source instead of waiting for a Windows
    runner that does not exist."""
    monkeypatch.setattr(sys, "platform", "win32")
    assert _platform_data_root({"LOCALAPPDATA": "C:/base/local"}) == Path(
        "C:/base/local"
    ) / "arXMCP"
    assert _platform_data_root({"USERPROFILE": "C:/users/x"}) == (
        Path("C:/users/x") / "AppData" / "Local" / "arXMCP"
    )
    source = _SUPERVISOR_MAIN_RS.read_text(encoding="utf-8")
    windows_branch = re.search(
        r'if cfg!\(target_os = "windows"\) \{(.+?)\} else if', source, re.DOTALL
    )
    assert windows_branch is not None, "the Rust Windows branch moved"
    body = windows_branch.group(1)
    assert 'value("LOCALAPPDATA")' in body
    assert '"AppData"' in body and '"Local"' in body
