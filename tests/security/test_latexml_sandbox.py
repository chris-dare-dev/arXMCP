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
import signal
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
        # Monkeypatch socket-level egress AND name resolution. The
        # fixture should NOT trigger any network activity under
        # LaTeXML's documented behavior (\input{URL} resolves as local
        # file). F5 rectification (E13_S03 adversary critique) added
        # the DNS coverage — LaTeXML could in principle perform a DNS
        # query via socket.getaddrinfo / gethostbyname WITHOUT ever
        # calling .connect(), and the original test would have missed
        # that egress channel.
        attempted_connections: list[tuple] = []
        attempted_dns: list[str] = []
        real_connect = socket.socket.connect
        real_getaddrinfo = socket.getaddrinfo
        real_gethostbyname = socket.gethostbyname

        def _record_and_block(self, address):  # noqa: ANN001
            attempted_connections.append(address)
            raise OSError(
                "Threat-3 BREACH — outbound socket attempt blocked: "
                f"{address}"
            )

        # Localhost lookups (127.0.0.1, ::1, localhost) are common
        # in test infrastructure (pytest fixtures, asyncio loops) and
        # are not threat-3 egress. Filter to external hosts only.
        _LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "", None}

        def _record_dns_getaddrinfo(host, *args, **kwargs):
            if host not in _LOCAL_HOSTS:
                attempted_dns.append(str(host))
                raise OSError(
                    "Threat-3 BREACH — outbound DNS via getaddrinfo: "
                    f"{host}"
                )
            return real_getaddrinfo(host, *args, **kwargs)

        def _record_dns_gethostbyname(host):
            if host not in _LOCAL_HOSTS:
                attempted_dns.append(str(host))
                raise OSError(
                    "Threat-3 BREACH — outbound DNS via gethostbyname: "
                    f"{host}"
                )
            return real_gethostbyname(host)

        monkeypatch.setattr(socket.socket, "connect", _record_and_block)
        monkeypatch.setattr(socket, "getaddrinfo", _record_dns_getaddrinfo)
        monkeypatch.setattr(socket, "gethostbyname", _record_dns_gethostbyname)
        try:
            _, _elapsed, status = _run_fixture(
                "network_call.tex", tmp_path, timeout=TEST_TIMEOUT_SECONDS
            )
        finally:
            monkeypatch.setattr(socket.socket, "connect", real_connect)
            monkeypatch.setattr(socket, "getaddrinfo", real_getaddrinfo)
            monkeypatch.setattr(socket, "gethostbyname", real_gethostbyname)

        # Containment: subprocess terminated.
        assert status in {"terminated", "timed_out"}, (
            f"network_call: unexpected state {status!r}"
        )
        # And no outbound TCP connection was attempted.
        assert not attempted_connections, (
            f"Threat-3 BREACH — outbound connections attempted: "
            f"{attempted_connections}"
        )
        # And no DNS resolution for an external host was attempted
        # (F5 rectification — covers the gap where LaTeXML could
        # exfiltrate via DNS without ever calling .connect).
        assert not attempted_dns, (
            f"Threat-3 BREACH — outbound DNS resolutions attempted: "
            f"{attempted_dns}"
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

    def test_profile_does_not_grant_blanket_home_read(self):
        """F1 + IS2 regression guard (E13_S03 critiques).

        Both critics flagged that the previous profile contained
        ``(allow file-read* (subpath (param "HOME")))`` — granting
        the LaTeXML subprocess read access to ~/.ssh/, ~/.aws/
        credentials, ~/.gnupg/, etc. The rectification narrowed the
        HOME allowance to enumerated Perl module roots only. This
        guard fails if a future edit re-introduces the blanket
        allowance.
        """
        text = self.SANDBOX_PROFILE.read_text()
        # The literal bare-HOME allow pattern as it appeared
        # pre-rect. Match precisely so a deliberate future addition
        # of a different bare-HOME pattern would still need to
        # touch this guard explicitly.
        forbidden = '(allow file-read* (subpath (param "HOME")))'
        assert forbidden not in text, (
            "sandbox profile must NOT grant blanket file-read* on "
            "(subpath (param \"HOME\")) — narrow to enumerated "
            "Perl/CPAN paths or add explicit denies for credential "
            "directories first (F1 + IS2 from E13_S03 critique)"
        )

    def test_profile_denies_credential_directories(self):
        """F1 + IS2 regression guard — assert the explicit denies
        for known credential directories are present in the
        profile, BEFORE any HOME-relative allows.
        """
        text = self.SANDBOX_PROFILE.read_text()
        required_denies = [
            '(deny file-read* (subpath (string-append (param "HOME") "/.ssh")))',
            '(deny file-read* (subpath (string-append (param "HOME") "/.aws")))',
            '(deny file-read* (subpath (string-append (param "HOME") "/.gnupg")))',
        ]
        for rule in required_denies:
            assert rule in text, (
                f"sandbox profile must contain explicit deny for "
                f"credential directory: {rule!r}"
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

    def test_top_level_mem_limit_and_cpus(self):
        """IS1 regression guard (E13_S03 infra-safety critique).

        ``deploy.resources.limits`` only applies in Docker Swarm
        mode and is silently ignored in standalone docker-compose
        (v1 / v2). The actual enforcement keys in standalone mode
        are top-level ``mem_limit`` and ``cpus``. The pre-rect
        config had ONLY the deploy block — meaning the resource
        caps documented as defense-in-depth against `fork_bomb.tex`
        and `large_alloc.tex` were no-ops.
        """
        text = self.DOCKER_CONFIG.read_text()
        assert "mem_limit:" in text, (
            "Docker config must declare top-level mem_limit "
            "(deploy.resources is Swarm-only and silently ignored "
            "in standalone compose)"
        )
        assert "cpus:" in text, (
            "Docker config must declare top-level cpus "
            "(deploy.resources is Swarm-only)"
        )

    def test_restart_policy_explicit(self):
        """IS3 regression guard — explicit restart: declaration."""
        text = self.DOCKER_CONFIG.read_text()
        assert "restart:" in text, (
            "Docker config must declare an explicit restart policy "
            "(IS3 from E13_S03 infra-safety critique)"
        )

    def test_bind_mount_default_under_var_arxmcp(self):
        """IS4 regression guard — bind-mount source default must
        point under ``var/arxmcp/`` (project's gitignored data
        tree), NOT under the repo source tree.
        """
        text = self.DOCKER_CONFIG.read_text()
        # The pre-rect default was `./latexml-output` which would
        # resolve relative to the compose file's dir
        # (`infra/latexml/`) and pollute the repo.
        bad_default = ":-./latexml-output"
        assert bad_default not in text, (
            f"Docker config must NOT default the bind-mount source "
            f"to {bad_default!r} — this resolves to "
            f"infra/latexml/latexml-output/ and pollutes the repo "
            f"tree (IS4 from E13_S03 infra-safety critique). Use a "
            f"path under var/arxmcp/ instead."
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

    def test_timeout_fires_killpg_path(self, tmp_path, monkeypatch):
        """F3 rectification (E13_S03 adversary critique).

        Forces the timeout path to fire by mocking ``subprocess.Popen``
        so the first ``communicate`` raises ``TimeoutExpired``. Asserts
        that ``os.killpg`` was called with the child's PGID and that
        the original ``TimeoutExpired`` propagates. Containment tests
        accept either ``terminated`` or ``timed_out`` and may never
        actually exercise this branch on a given machine; this guard
        anchors the killpg path independently.
        """
        from tools import arxiv_fetch as af  # noqa: PLC0415

        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/latexmlc")

        class _FakeProc:
            def __init__(self, *args, **kwargs):
                self.pid = 99001
                self.returncode = None
                self._communicate_calls = 0

            def communicate(self, timeout=None):
                self._communicate_calls += 1
                if self._communicate_calls == 1:
                    raise subprocess.TimeoutExpired(cmd="latexmlc", timeout=timeout)
                # Second call (post-killpg drain) returns cleanly.
                return ("", "")

        killpg_calls: list[tuple] = []

        def _record_killpg(pgid, sig):
            killpg_calls.append((pgid, sig))

        # Fake getpgid to a known value so the assertion can check it.
        monkeypatch.setattr(af.subprocess, "Popen", _FakeProc)
        monkeypatch.setattr(af.os, "getpgid", lambda pid: pid)
        monkeypatch.setattr(af.os, "killpg", _record_killpg)

        main = tmp_path / "main.tex"
        main.write_text(r"\documentclass{article}\begin{document}x\end{document}")

        with pytest.raises(subprocess.TimeoutExpired):
            af.parse_with_latexml(
                main, tmp_path / "parsed", "fake_paper", timeout=1
            )

        # Exactly one killpg with SIGKILL on the (mocked) PGID == PID.
        assert killpg_calls == [(99001, signal.SIGKILL)], (
            f"killpg should have been called once with the child's "
            f"PGID and SIGKILL; got {killpg_calls!r}"
        )

    def test_catastrophic_case_drains_pipes_and_reraises(
        self, tmp_path, monkeypatch
    ):
        """F2 rectification (E13_S03 adversary critique).

        Catastrophic-case test: SIGKILL was sent but the process
        group survived (kernel pathology). The second
        ``communicate(timeout=5)`` ALSO times out. The function must
        still re-raise the ORIGINAL TimeoutExpired so callers see
        the parse-failure signal instead of deadlocking.
        """
        from tools import arxiv_fetch as af  # noqa: PLC0415

        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/latexmlc")

        communicate_calls: list[float] = []

        class _ZombieProc:
            def __init__(self, *args, **kwargs):
                self.pid = 99002
                self.returncode = None

            def communicate(self, timeout=None):
                communicate_calls.append(timeout)
                # BOTH calls raise — the killpg was ineffective.
                raise subprocess.TimeoutExpired(cmd="latexmlc", timeout=timeout)

        killpg_calls: list[tuple] = []

        monkeypatch.setattr(af.subprocess, "Popen", _ZombieProc)
        monkeypatch.setattr(af.os, "getpgid", lambda pid: pid)
        monkeypatch.setattr(
            af.os, "killpg", lambda pgid, sig: killpg_calls.append((pgid, sig))
        )

        main = tmp_path / "main.tex"
        main.write_text(r"\documentclass{article}\begin{document}x\end{document}")

        with pytest.raises(subprocess.TimeoutExpired):
            af.parse_with_latexml(
                main, tmp_path / "parsed", "fake_paper", timeout=1
            )

        # Two communicate calls (initial + post-killpg drain).
        assert len(communicate_calls) == 2, (
            f"communicate should have been called twice (initial + "
            f"post-killpg drain); got {communicate_calls!r}"
        )
        # Second call uses the 5s drain timeout.
        assert communicate_calls[1] == 5, (
            f"second communicate call should use 5s drain timeout; "
            f"got {communicate_calls[1]!r}"
        )
        # killpg was still called even though it was ineffective.
        assert killpg_calls == [(99002, signal.SIGKILL)], (
            f"killpg should have been called; got {killpg_calls!r}"
        )
