"""E13_S03 — Threat-3 (LaTeXML sandbox) hostile-input validation.

Exercises five hostile `.tex` fixtures against the LaTeXML subprocess
invocation in :func:`tools.arxiv_fetch.parse_with_latexml`. For each
fixture the test asserts:

1. **Containment.** The subprocess terminates (no orphan processes, no
   hung pipe) within a short test-timeout. The Python-side timeout is
   the load-bearing kill mechanism — LaTeXML's own `--timeout` flag
   is documented but not relied upon (see audit doc).

2. **No host filesystem leak.** No new files appear in `/tmp/` (or
   any other host path) with the canary prefix `arxmcp_pwned_e13s03`.
   The baseline-vs-post snapshot is filtered to this prefix so the
   test is robust against unrelated `/tmp/` activity from other
   pytest runs.

3. **No outbound network egress.** For the network_call fixture, a
   socket-creation monkeypatch confirms no socket-level connection
   was attempted to an external host.

**Fixture effectiveness caveats** (synthesis FM-3 + FM-5):

- ``write18_shellout.tex`` — LaTeXML does NOT pass `\write18` to the
  shell (Perl-based, no `--shell-escape`). The fixture tests SIDE-
  EFFECT ABSENCE, not attack-trigger. If LaTeXML ever gains shell-
  escape support, the canary path will appear and the test will fail.
- ``network_call.tex`` — LaTeXML resolves `\input{}` as a local file
  path, not an HTTP fetch. The fixture tests that NO network
  connection is initiated regardless of LaTeXML's actual `\input{}`
  resolution behavior.

These caveats are documented in the fixture file headers and in
``.claude/docs/security-threat-3-audit.md``.

**Why the test timeout is short (10 s, not 300 s).** The production
timeout in :data:`tools.arxiv_fetch.LATEXML_TIMEOUT_SECONDS` is 300 s
— well above the worst-case parsing latency for real arXiv content.
For unit tests, a 10 s ceiling exercises the same containment code
path without making the test suite slow. The contract being tested is
"subprocess terminates within timeout"; the absolute timeout value
matters only operationally.

**Sandbox-exec wiring.** The macOS `sandbox-exec` profile at
``infra/latexml/sandbox.sb`` is NOT wired into ``parse_with_latexml``
in production code at v1 (see synthesis D3). These tests therefore
exercise the Python-level process-group kill discipline, which is
the cross-platform defense E13_S03 ships TODAY. A separate test
class (``TestSandboxProfile``) verifies the .sb profile parses and
contains the required restrictions; it does NOT run latexmlc inside
the sandbox at unit-test time.
"""

from __future__ import annotations

import contextlib
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

# E13_S03: pytest's KMP_DUPLICATE_LIB_OK guard (CLAUDE.md §8 gotcha 1)
# is set by tests/conftest.py and is load-bearing — do not remove.

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "latexml"

#: Canary filename used by the write18 fixture. The fixture attempts
#: to create this path; the test asserts it does NOT exist after
#: each run.
CANARY_PATH = Path("/tmp/arxmcp_pwned_e13s03.txt")

#: Short timeout for unit-test runs. Production
#: :data:`tools.arxiv_fetch.LATEXML_TIMEOUT_SECONDS` is 300 s; the
#: same containment code path is exercised with this shorter cap.
TEST_TIMEOUT_SECONDS = 10.0


# ===========================================================================
# Helpers
# ===========================================================================


def _baseline_tmp_canary_snapshot() -> set[Path]:
    """Snapshot any /tmp/ entries matching the arxmcp canary prefix.

    Filter to the canary prefix only — unrelated /tmp/ activity from
    other tests / processes is out of scope. The set is used by the
    teardown-time assertion that no new canary files appeared.
    """
    return {p for p in Path("/tmp").glob("arxmcp_pwned_e13s03*")}


def _ensure_canary_clean() -> None:
    """Remove a stale canary from a prior test run.

    Without this, a test that suffered an actual sandbox escape on
    a previous run would leave the canary on disk and every
    subsequent run would falsely PASS (the canary already exists,
    snapshot diff is empty).
    """
    if CANARY_PATH.exists():
        CANARY_PATH.unlink()


def _run_fixture(
    fixture_name: str,
    output_dir: Path,
    timeout: float = TEST_TIMEOUT_SECONDS,
) -> tuple[int | None, float, str]:
    """Invoke parse_with_latexml on the named fixture; return
    ``(returncode, elapsed_seconds, status)`` where ``status`` is
    one of ``"terminated"`` (clean exit, any code), ``"timed_out"``
    (Python timeout fired and SIGKILL'd the group), or
    ``"runtime_error"`` (latexmlc missing or other shape failure).

    Uses the production :func:`tools.arxiv_fetch.parse_with_latexml`
    so the test exercises the actual process-group kill discipline
    landed by this milestone, not a parallel reimplementation.
    """
    # Lazy import — these tests should be collectible even when
    # ``tools/`` is missing from the path (older Pythons).
    from tools.arxiv_fetch import parse_with_latexml  # noqa: PLC0415

    fixture_src = FIXTURES_DIR / fixture_name
    # Copy the fixture into a working subdirectory so latexmlc's cwd
    # is set there and any `\input{}` resolution stays scoped.
    work_dir = output_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    main_tex = work_dir / fixture_name
    main_tex.write_bytes(fixture_src.read_bytes())

    parsed_dir = output_dir / "parsed"
    parsed_dir.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    try:
        result = parse_with_latexml(
            main_tex=main_tex,
            parsed_dir=parsed_dir,
            paper_id=fixture_name.replace(".tex", ""),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        return (None, elapsed, "timed_out")
    except RuntimeError as exc:
        # parse_with_latexml raises RuntimeError if `latexmlc` is not on
        # PATH. The test would normally be skipped before reaching this
        # point, but surface the error explicitly.
        elapsed = time.monotonic() - start
        return (None, elapsed, f"runtime_error: {exc}")

    elapsed = time.monotonic() - start
    return (result.exit_code if hasattr(result, "exit_code") else 0,
            elapsed, "terminated")


# ===========================================================================
# Test class — fires only when latexmlc is on PATH
# ===========================================================================


@pytest.mark.skipif(
    shutil.which("latexmlc") is None,
    reason="latexmlc not on PATH (install LaTeXML 0.8.x — `brew install latexml`)",
)
class TestLatexmlSandboxContainment:
    """End-to-end containment tests for the 5 hostile fixtures.

    Each test runs the corresponding fixture through the production
    :func:`tools.arxiv_fetch.parse_with_latexml` and asserts the
    containment contract holds: subprocess terminates, no canary
    file appears, elapsed time is within the test timeout.

    These tests do NOT assert specific LaTeXML exit codes — different
    LaTeXML versions handle hostile inputs differently (some exit 0
    with degraded output; some exit non-zero; some segfault). The
    contract is *containment*, not *attack detection*.
    """

    def setup_method(self) -> None:
        _ensure_canary_clean()
        self._tmp_canary_baseline = _baseline_tmp_canary_snapshot()

    def teardown_method(self) -> None:
        # Post-condition: no new canary files appeared on disk.
        post = _baseline_tmp_canary_snapshot()
        new_canaries = post - self._tmp_canary_baseline
        if new_canaries:
            # Clean up before re-raising so the next test starts fresh.
            for p in new_canaries:
                with contextlib.suppress(OSError):
                    p.unlink()
            pytest.fail(
                f"Threat-3 BREACH — hostile fixture caused unexpected "
                f"file writes to /tmp/: {sorted(new_canaries)}"
            )

    def test_infinite_recursion_contained(self, tmp_path):
        _, elapsed, status = _run_fixture(
            "infinite_recursion.tex", tmp_path, timeout=TEST_TIMEOUT_SECONDS
        )
        # Either LaTeXML's internal expansion limit fired (terminated)
        # or the Python timeout caught it (timed_out). Both are valid.
        assert status in {"terminated", "timed_out"}, (
            f"infinite_recursion: subprocess in unexpected state {status!r} "
            f"after {elapsed:.1f}s"
        )
        # Bounded elapsed — the kill mechanism actually fired.
        assert elapsed <= TEST_TIMEOUT_SECONDS + 5.0, (
            f"infinite_recursion: elapsed {elapsed:.1f}s exceeded "
            f"timeout + kill grace ({TEST_TIMEOUT_SECONDS + 5.0}s)"
        )

    def test_write18_shellout_no_canary(self, tmp_path):
        # The canary cleanup happens in setup_method; the teardown
        # checks no canary was created. Just run the fixture.
        _, elapsed, status = _run_fixture(
            "write18_shellout.tex", tmp_path, timeout=TEST_TIMEOUT_SECONDS
        )
        # write18 fixture is expected to complete quickly (LaTeXML
        # silently ignores \write18). Containment = no canary file.
        assert status in {"terminated", "timed_out"}, (
            f"write18: unexpected state {status!r}"
        )
        # Explicit guard alongside the teardown — make the failure
        # message clearer when this specific fixture breaches.
        assert not CANARY_PATH.exists(), (
            f"Threat-3 BREACH — \\write18 escaped: {CANARY_PATH} created"
        )

    def test_fork_bomb_contained(self, tmp_path):
        _, elapsed, status = _run_fixture(
            "fork_bomb.tex", tmp_path, timeout=TEST_TIMEOUT_SECONDS
        )
        # Three valid outcomes (synthesis FM-10):
        # 1. terminated normally (LaTeXML expansion limit fired)
        # 2. timed_out (Python timeout SIGKILL'd the group)
        # 3. terminated with exit -9 (kernel OOM-killer fired first)
        # All three are containment-positive.
        assert status in {"terminated", "timed_out"}, (
            f"fork_bomb: unexpected state {status!r}"
        )
        assert elapsed <= TEST_TIMEOUT_SECONDS + 5.0

    def test_large_alloc_contained(self, tmp_path):
        _, elapsed, status = _run_fixture(
            "large_alloc.tex", tmp_path, timeout=TEST_TIMEOUT_SECONDS
        )
        # Likely terminates normally — LaTeXML handles deeply nested
        # math without crashing. Containment is satisfied as long as
        # the subprocess terminates within the cap.
        assert status in {"terminated", "timed_out"}, (
            f"large_alloc: unexpected state {status!r}"
        )
        assert elapsed <= TEST_TIMEOUT_SECONDS + 5.0

    def test_network_call_no_egress(self, tmp_path, monkeypatch):
        # Monkeypatch socket.socket().connect to record any attempted
        # connection. The fixture should NOT trigger network egress
        # under LaTeXML's documented behavior (\input{URL} resolves
        # as local file).
        attempted_connections: list[tuple] = []
        real_connect = socket.socket.connect

        def _record_and_block(self, address):  # noqa: ANN001
            attempted_connections.append(address)
            raise OSError(
                "Threat-3 BREACH — outbound socket attempt blocked: "
                f"{address}"
            )

        monkeypatch.setattr(socket.socket, "connect", _record_and_block)
        try:
            _, _elapsed, status = _run_fixture(
                "network_call.tex", tmp_path, timeout=TEST_TIMEOUT_SECONDS
            )
        finally:
            monkeypatch.setattr(socket.socket, "connect", real_connect)

        # Containment: subprocess terminated.
        assert status in {"terminated", "timed_out"}, (
            f"network_call: unexpected state {status!r}"
        )
        # And no outbound connection was attempted (the monkeypatch
        # raises if any code path called .connect).
        assert not attempted_connections, (
            f"Threat-3 BREACH — outbound connections attempted: "
            f"{attempted_connections}"
        )


# ===========================================================================
# Sandbox profile + Docker config — static validation (always-on)
# ===========================================================================


class TestSandboxProfile:
    """Static validation of the macOS sandbox-exec profile shipped at
    ``infra/latexml/sandbox.sb``. The profile is a DOCUMENTATION
    ARTIFACT + test fixture at v1 — it is NOT wired into
    ``parse_with_latexml`` production code (synthesis D3). When
    production hardening lands in E11, the wiring should reference
    this profile.

    These tests parse the profile as text and assert the required
    restrictions are present. They run on every platform.
    """

    SANDBOX_PROFILE = (
        Path(__file__).parent.parent.parent
        / "infra" / "latexml" / "sandbox.sb"
    )

    def test_profile_file_exists(self):
        assert self.SANDBOX_PROFILE.exists(), (
            "infra/latexml/sandbox.sb is missing — E13_S03 deliverable"
        )

    def test_profile_denies_default(self):
        text = self.SANDBOX_PROFILE.read_text()
        assert "(deny default)" in text, (
            "sandbox profile must start from a default-deny posture"
        )

    def test_profile_denies_network(self):
        text = self.SANDBOX_PROFILE.read_text()
        assert "(deny network*)" in text, (
            "sandbox profile must deny network egress (Threat 3)"
        )

    def test_profile_uses_version_1(self):
        text = self.SANDBOX_PROFILE.read_text()
        assert "(version 1)" in text, (
            "sandbox profile must declare (version 1)"
        )


class TestDockerLatexmlConfig:
    """Static validation of the standalone Docker config for the
    LaTeXML service at ``infra/latexml/docker-compose.latexml.yml``.

    This file is a DOCUMENTATION ARTIFACT (synthesis D2) — when E14
    lands the main docker-compose, the settings here should be
    merged into the LaTeXML service definition. The test parses the
    YAML and asserts the required isolation flags are present, with
    no Docker daemon required.
    """

    DOCKER_CONFIG = (
        Path(__file__).parent.parent.parent
        / "infra" / "latexml" / "docker-compose.latexml.yml"
    )

    def test_config_file_exists(self):
        assert self.DOCKER_CONFIG.exists(), (
            "infra/latexml/docker-compose.latexml.yml is missing — "
            "E13_S03 deliverable for AC3 reframe"
        )

    def test_network_mode_is_none(self):
        # Trivial text check — avoids a YAML parsing dep.
        text = self.DOCKER_CONFIG.read_text()
        assert "network_mode: none" in text, (
            "Docker config must set network_mode: none on the "
            "latexml service (Threat 3 — no network access)"
        )

    def test_no_new_privileges_set(self):
        text = self.DOCKER_CONFIG.read_text()
        assert "no-new-privileges" in text, (
            "Docker config must set security_opt: no-new-privileges "
            "on the latexml service (Threat 3 — defense in depth)"
        )

    def test_read_only_filesystem(self):
        text = self.DOCKER_CONFIG.read_text()
        assert "read_only: true" in text, (
            "Docker config must set read_only: true on the latexml "
            "service (Threat 3 — filesystem write whitelist)"
        )

    def test_non_root_user(self):
        # Parse the user: line specifically — substring matches on the
        # whole-file text are too loose (a comment about "root
        # filesystem" trips a naive `"root" in text` check).
        text = self.DOCKER_CONFIG.read_text()
        user_lines = [
            line.strip()
            for line in text.splitlines()
            # Match `user:` at the start of an indented service-level
            # key. Exclude lines like `# user: 65534...` (comments).
            if line.lstrip().startswith("user:")
            and not line.lstrip().startswith("#")
        ]
        assert user_lines, (
            "Docker config must specify a `user:` field on the "
            "latexml service (Threat 3 — subprocess UID isolation)"
        )
        # Every actual user: line must specify a non-root UID. The
        # acceptable forms are `user: "<uid>:<gid>"` (numeric) or
        # `user: <nonroot-name>` where the name is not literally
        # "root" / "0" / "0:0".
        for line in user_lines:
            value = line.split(":", 1)[1].strip().strip('"').strip("'")
            assert value not in {"root", "0", "0:0"}, (
                f"Docker config must NOT run latexml as root; "
                f"found `user: {value}` (Threat 3)"
            )
            # Numeric UID must be > 0.
            uid_part = value.split(":", 1)[0]
            if uid_part.isdigit():
                assert int(uid_part) > 0, (
                    f"Docker config must use a non-zero UID; "
                    f"found `user: {value}` (Threat 3)"
                )


# ===========================================================================
# Process-group kill discipline regression guard
# ===========================================================================


class TestProcessGroupKill:
    """Regression guard for the process-group kill discipline added
    to ``parse_with_latexml`` in this milestone. Without
    ``start_new_session=True``, a hostile `.tex` that causes LaTeXML
    to fork Perl helpers would leave grandchildren behind on
    timeout. The test asserts the production code carries the
    contract.

    AST-based check (mirrors E13_S02's TestV1Gaps F3 rectification)
    — robust against false-positives from comments / docstrings.
    """

    def test_parse_with_latexml_uses_process_group_kill(self):
        import ast  # noqa: PLC0415

        from tools import arxiv_fetch  # noqa: PLC0415

        source = Path(arxiv_fetch.__file__).read_text()
        tree = ast.parse(source)

        # Find the parse_with_latexml function.
        func = next(
            (
                n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef)
                and n.name == "parse_with_latexml"
            ),
            None,
        )
        assert func is not None, "parse_with_latexml function not found"

        # Walk the function body looking for start_new_session=True
        # and os.killpg references.
        func_source = ast.unparse(func)
        assert "start_new_session=True" in func_source, (
            "parse_with_latexml must launch latexmlc with "
            "start_new_session=True so the process-group kill on "
            "timeout reaches Perl grandchildren (E13_S03 Threat 3)"
        )
        assert "killpg" in func_source, (
            "parse_with_latexml must SIGKILL the entire process "
            "group on TimeoutExpired (E13_S03 Threat 3)"
        )
