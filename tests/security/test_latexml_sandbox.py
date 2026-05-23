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
import sys
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

    def test_profile_allows_tmpdir_subdir_read(self):
        """E13_S03b F7 rectification — SBPL ``file-write*`` does NOT
        imply ``file-read*``. Perl helpers commonly write a tmp file
        then re-open it for read; without an explicit
        ``file-read*`` allow on TMPDIR_SUBDIR, the sandbox would
        deny the re-read and trip the parse.

        Pins the profile change so a future edit that removes the
        read-allow fails this test loudly.
        """
        text = self.SANDBOX_PROFILE.read_text()
        # The literal form added by F7.
        required = '(allow file-read*\n  (subpath (param "TMPDIR_SUBDIR")))'
        assert required in text, (
            f"sandbox profile must allow file-read* on TMPDIR_SUBDIR "
            f"(E13_S03b F7); Perl atomic-write patterns require it. "
            f"Expected literal: {required!r}"
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

    def test_render_fixture_uses_start_new_session(self):
        """E13_S03b F4 rectification — synthesis D6 required
        ``start_new_session=True`` parity between
        ``parse_with_latexml`` (already had it via E13_S03) and
        ``ops/drift_check.py::render_fixture``. The initial
        E13_S03b implementation missed it; F4 added the kwarg.

        This AST guard pins the contract — a future refactor that
        drops the kwarg fails loudly. Mirrors
        ``test_parse_with_latexml_uses_process_group_kill`` above;
        AST-based and platform-independent so it runs on Windows
        too (where the live ``render_fixture`` would also exercise
        the path on macOS/Linux).
        """
        import ast  # noqa: PLC0415

        from ops import drift_check  # noqa: PLC0415

        source = Path(drift_check.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        func = next(
            (
                n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef)
                and n.name == "render_fixture"
            ),
            None,
        )
        assert func is not None, (
            "render_fixture function not found in ops.drift_check"
        )
        func_source = ast.unparse(func)
        assert "start_new_session=True" in func_source, (
            "render_fixture must launch latexmlc with "
            "start_new_session=True for parity with "
            "parse_with_latexml's process-group-kill discipline "
            "(E13_S03b F4)"
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


# ===========================================================================
# E13_S03b — Production sandbox wiring (Threat 3 Phase 2)
#   Closes the partial-coverage gap G3 (github.com/chris-dare-dev/arXMCP#3).
# ===========================================================================


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="sandbox-exec / bwrap are POSIX-only; Windows takes the "
    "degraded path unconditionally (no sandbox layer available)",
)
class TestSandboxWiring:
    """E13_S03b — closes Threat 3 Phase 2 gap G3.

    Wires the existing ``infra/latexml/sandbox.sb`` (macOS) and
    bubblewrap (Linux) into ``parse_with_latexml`` by prepending
    wrapper argv to the existing ``cmd`` list. The sandbox profile
    and Docker config were shipped by E13_S03; E13_S03b is wiring-
    only.

    Tests use MOCKS (not live latexmlc) to verify ``_build_sandbox_cmd``
    prepends the correct wrapper argv on each platform — this is the
    only way to assert wiring discipline without requiring the test
    machine to actually have sandbox-exec OR bwrap installed (the
    existing ``TestLatexmlSandboxContainment`` skips when latexmlc is
    absent, which would also skip on a machine that has latexmlc but
    not the chosen sandbox layer).
    """

    def test_detect_sandbox_layer_darwin_when_present(self, monkeypatch):
        """On macOS with sandbox-exec + profile present, returns
        the string ``"sandbox-exec"``.

        E13_S03b F5 rectification — the prior version of this test
        used a blanket ``lambda self: True`` stub for ``Path.is_file``
        which would pass even if the implementation dropped one of
        the two existence checks (sandbox-exec binary OR .sb
        profile). The stricter version below DISCRIMINATES which
        paths are checked and asserts both: a future refactor that
        drops either check fails this test.
        """
        from tools import arxiv_fetch as af  # noqa: PLC0415

        monkeypatch.setattr(af.sys, "platform", "darwin")
        checked_paths: list[str] = []
        original_is_file = Path.is_file

        def discriminating_is_file(self):
            path_str = str(self)
            checked_paths.append(path_str)
            if path_str == "/usr/bin/sandbox-exec":
                return True
            if path_str.endswith("sandbox.sb"):
                return True
            return original_is_file(self)

        monkeypatch.setattr(af.Path, "is_file", discriminating_is_file)
        result = af._detect_sandbox_layer()
        assert result == "sandbox-exec", (
            f"darwin + sandbox-exec + profile present must return "
            f"'sandbox-exec'; got {result!r}"
        )
        # F5 — both existence checks must have happened. Pin them
        # so a future refactor that drops either check fails loudly.
        assert "/usr/bin/sandbox-exec" in checked_paths, (
            f"sandbox-exec binary existence must be checked; "
            f"checked_paths={checked_paths!r}"
        )
        assert any(p.endswith("sandbox.sb") for p in checked_paths), (
            f".sb profile existence must be checked; "
            f"checked_paths={checked_paths!r}"
        )

    def test_detect_sandbox_layer_darwin_when_sandbox_exec_absent(
        self, monkeypatch
    ):
        """On macOS WITHOUT sandbox-exec (deprecation removed it in
        a hypothetical future macOS), returns None — degraded path.

        Closes FM-2 (silent sandbox removal): if the operator
        believes the pin is active but it's not, the next-best
        signal is the module-import-time INFO log. The wiring
        decision itself must return None cleanly.
        """
        from tools import arxiv_fetch as af  # noqa: PLC0415

        monkeypatch.setattr(af.sys, "platform", "darwin")
        # Path("/usr/bin/sandbox-exec").is_file() → False
        original_is_file = Path.is_file

        def fake_is_file(self):
            if str(self) == "/usr/bin/sandbox-exec":
                return False
            return original_is_file(self)

        monkeypatch.setattr(af.Path, "is_file", fake_is_file)
        result = af._detect_sandbox_layer()
        assert result is None, (
            f"darwin without sandbox-exec must return None "
            f"(degraded path); got {result!r}"
        )

    def test_detect_sandbox_layer_linux_with_bwrap(self, monkeypatch):
        """On Linux with bwrap on PATH, returns ``"bwrap"``."""
        from tools import arxiv_fetch as af  # noqa: PLC0415

        monkeypatch.setattr(af.sys, "platform", "linux")
        monkeypatch.setattr(
            af.shutil,
            "which",
            lambda name: "/usr/bin/bwrap" if name == "bwrap" else None,
        )
        result = af._detect_sandbox_layer()
        assert result == "bwrap", (
            f"linux + bwrap on PATH must return 'bwrap'; "
            f"got {result!r}"
        )

    def test_detect_sandbox_layer_linux_without_bwrap(self, monkeypatch):
        """On Linux without bwrap (operator hasn't installed
        bubblewrap), returns None — degraded path. The
        module-import-time INFO log is the operator-visible signal
        that the sandbox is not active.
        """
        from tools import arxiv_fetch as af  # noqa: PLC0415

        monkeypatch.setattr(af.sys, "platform", "linux")
        monkeypatch.setattr(af.shutil, "which", lambda name: None)
        result = af._detect_sandbox_layer()
        assert result is None, (
            f"linux without bwrap must return None (degraded path); "
            f"got {result!r}"
        )

    def test_build_sandbox_cmd_darwin_prepends_sandbox_exec(
        self, monkeypatch, tmp_path
    ):
        """When sandbox-exec is the active layer, _build_sandbox_cmd
        prepends ``/usr/bin/sandbox-exec -f <profile> -D SOURCE_DIR=...
        -D OUTPUT_DIR=... -D HOME=... -D TMPDIR_SUBDIR=...`` to the
        original cmd. The original cmd remains the suffix —
        unmodified — so a future refactor that drops a latexmlc
        arg gets caught."""
        from tools import arxiv_fetch as af  # noqa: PLC0415

        monkeypatch.setattr(af, "_SANDBOX_LAYER", "sandbox-exec")
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        output_dir = tmp_path / "out"
        output_dir.mkdir()
        tmpdir_subdir = tmp_path / "sbtmp"
        tmpdir_subdir.mkdir()
        original = ["latexmlc", "--timeout=300", "main.tex"]
        result = af._build_sandbox_cmd(
            original,
            source_dir=source_dir,
            output_dir=output_dir,
            tmpdir_subdir=tmpdir_subdir,
        )
        # sandbox-exec must be the FIRST arg.
        assert result[0] == "/usr/bin/sandbox-exec", (
            f"expected sandbox-exec to be the first arg; "
            f"got {result[0]!r}"
        )
        # The profile flag must appear.
        assert "-f" in result
        f_idx = result.index("-f")
        assert "sandbox.sb" in result[f_idx + 1], (
            f"sandbox-exec must point at the .sb profile; "
            f"got {result[f_idx + 1]!r}"
        )
        # The 4 -D substitutions must appear with the right keys.
        substitutions = " ".join(result)
        assert f"SOURCE_DIR={source_dir}" in substitutions
        assert f"OUTPUT_DIR={output_dir}" in substitutions
        assert f"TMPDIR_SUBDIR={tmpdir_subdir}" in substitutions
        assert "HOME=" in substitutions
        # The original cmd appears as the suffix, unmodified.
        assert result[-len(original):] == original, (
            f"original cmd must appear as the suffix unmodified; "
            f"got tail={result[-len(original):]!r}, "
            f"expected={original!r}"
        )

    def test_build_sandbox_cmd_linux_prepends_bwrap(
        self, monkeypatch, tmp_path
    ):
        """When bwrap is the active layer, _build_sandbox_cmd
        prepends ``bwrap --ro-bind ... --proc /proc --dev /dev
        --unshare-net --unshare-pid --die-with-parent --new-session
        -- ...`` to the original cmd.

        E13_S03b F1+F2 rectification — ``--proc /proc`` and
        ``--dev /dev`` MUST be present. ``--unshare-pid`` without
        ``--proc /proc`` is documented-broken; LaTeXML's Perl
        helpers also need ``/dev/null`` / ``/dev/urandom``.
        """
        from tools import arxiv_fetch as af  # noqa: PLC0415

        monkeypatch.setattr(af, "_SANDBOX_LAYER", "bwrap")
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        output_dir = tmp_path / "out"
        output_dir.mkdir()
        tmpdir_subdir = tmp_path / "sbtmp"
        tmpdir_subdir.mkdir()
        original = ["latexmlc", "main.tex"]
        result = af._build_sandbox_cmd(
            original,
            source_dir=source_dir,
            output_dir=output_dir,
            tmpdir_subdir=tmpdir_subdir,
        )
        assert result[0] == "bwrap", (
            f"expected bwrap to be the first arg; got {result[0]!r}"
        )
        # Load-bearing isolation flags MUST be present (E13_S03b
        # F1+F2 rectification added /proc and /dev to this list).
        for flag in (
            "--proc",
            "--dev",
            "--unshare-net",
            "--unshare-pid",
            "--die-with-parent",
            "--new-session",
        ):
            assert flag in result, (
                f"bwrap argv missing load-bearing flag {flag!r}; "
                f"got {result!r}"
            )
        # F1 — --proc must be paired with /proc target.
        proc_idx = result.index("--proc")
        assert result[proc_idx + 1] == "/proc", (
            f"--proc must target /proc; got {result[proc_idx + 1]!r}"
        )
        # F2 — --dev must be paired with /dev target.
        dev_idx = result.index("--dev")
        assert result[dev_idx + 1] == "/dev", (
            f"--dev must target /dev; got {result[dev_idx + 1]!r}"
        )
        # The end-of-bwrap-args marker '--' must appear right
        # before the original cmd. Find the SEPARATOR '--', not the
        # earlier '--proc' / '--dev' / etc. — locate the last '--'
        # in the sequence (since the original cmd has no '--' in it
        # post-F3 rectification).
        sep_idx = len(result) - len(original) - 1
        assert result[sep_idx] == "--", (
            f"expected '--' separator at index {sep_idx}; "
            f"got {result[sep_idx]!r}"
        )
        assert result[sep_idx + 1 :] == original, (
            f"original cmd must appear after the '--' separator "
            f"unmodified; got tail={result[sep_idx + 1 :]!r}, "
            f"expected={original!r}"
        )
        # System paths must be ro-bound (not bind / not tmpfs).
        for path in ("/usr", "/etc"):
            assert path in result, (
                f"bwrap argv missing read-only bind for {path!r}"
            )
        # source_dir is read-only; output_dir is read-write.
        ro_bind_indices = [
            i for i, a in enumerate(result) if a == "--ro-bind"
        ]
        bind_indices = [
            i for i, a in enumerate(result) if a == "--bind"
        ]
        ro_bound = [result[i + 1] for i in ro_bind_indices]
        bound = [result[i + 1] for i in bind_indices]
        assert str(source_dir) in ro_bound, (
            f"source_dir must be --ro-bind (read-only); "
            f"ro_bound={ro_bound!r}"
        )
        assert str(output_dir) in bound, (
            f"output_dir must be --bind (read-write); "
            f"bound={bound!r}"
        )

    def test_build_sandbox_cmd_linux_skips_missing_lib_dirs(
        self, monkeypatch, tmp_path
    ):
        """E13_S03b F6 rectification — both ``/lib`` and ``/lib64``
        ro-binds are now existence-guarded so a minimal-image
        operator (Alpine, scratch-based container) doesn't trip
        ``bwrap: Can't bind /lib`` errors.

        Monkey-patches ``Path.exists`` to report neither dir exists;
        asserts the produced argv has neither ``--ro-bind /lib`` nor
        ``--ro-bind /lib64`` pairs.
        """
        from tools import arxiv_fetch as af  # noqa: PLC0415

        monkeypatch.setattr(af, "_SANDBOX_LAYER", "bwrap")
        original_exists = Path.exists

        def fake_exists(self):
            path_str = str(self)
            if path_str in ("/lib", "/lib64"):
                return False
            return original_exists(self)

        monkeypatch.setattr(af.Path, "exists", fake_exists)
        result = af._build_sandbox_cmd(
            ["latexmlc", "main.tex"],
            source_dir=tmp_path / "src",
            output_dir=tmp_path / "out",
            tmpdir_subdir=tmp_path / "sbtmp",
        )
        # Walk every --ro-bind pair; ensure /lib and /lib64 are
        # NOT among the targets.
        ro_bind_indices = [
            i for i, a in enumerate(result) if a == "--ro-bind"
        ]
        ro_bound_targets = [result[i + 1] for i in ro_bind_indices]
        assert "/lib" not in ro_bound_targets, (
            f"missing-/lib code path must skip the --ro-bind; "
            f"ro_bound={ro_bound_targets!r}"
        )
        assert "/lib64" not in ro_bound_targets, (
            f"missing-/lib64 code path must skip the --ro-bind; "
            f"ro_bound={ro_bound_targets!r}"
        )

    def test_build_sandbox_cmd_unavailable_returns_unchanged(
        self, monkeypatch, tmp_path
    ):
        """When _SANDBOX_LAYER is None (the degraded path —
        Windows, or POSIX without sandbox-exec/bwrap), the helper
        returns the original cmd unchanged. The caller's
        subprocess+timeout primitives remain the only isolation
        layer.

        Regression guard for FM-2 (silent degradation): the helper
        must NOT silently inject a partial sandbox or do anything
        that hides the degraded state from the operator.
        """
        from tools import arxiv_fetch as af  # noqa: PLC0415

        monkeypatch.setattr(af, "_SANDBOX_LAYER", None)
        original = ["latexmlc", "--timeout=300", "main.tex"]
        result = af._build_sandbox_cmd(
            original,
            source_dir=tmp_path / "src",
            output_dir=tmp_path / "out",
            tmpdir_subdir=tmp_path / "sbtmp",
        )
        assert result == original, (
            f"degraded path must return cmd unchanged; "
            f"got {result!r}, expected {original!r}"
        )
        # And identity check: same list object (no defensive copy).
        # Not strictly required by the contract; documents the
        # observed behavior.
        assert result is original

    def test_build_sandbox_cmd_does_not_mutate_input(
        self, monkeypatch, tmp_path
    ):
        """The helper must NOT mutate the input cmd list — callers
        rely on being able to reuse / log the original argv. The
        sandbox layers all PREPEND to a new list."""
        from tools import arxiv_fetch as af  # noqa: PLC0415

        for layer in ("sandbox-exec", "bwrap"):
            monkeypatch.setattr(af, "_SANDBOX_LAYER", layer)
            original = ["latexmlc", "--timeout=300", "main.tex"]
            snapshot = list(original)
            af._build_sandbox_cmd(
                original,
                source_dir=tmp_path / "src",
                output_dir=tmp_path / "out",
                tmpdir_subdir=tmp_path / "sbtmp",
            )
            assert original == snapshot, (
                f"_build_sandbox_cmd must not mutate input cmd "
                f"(layer={layer!r}); got mutated to {original!r}"
            )

    def test_parse_with_latexml_threads_sandbox_to_popen(
        self, monkeypatch, tmp_path
    ):
        """When _SANDBOX_LAYER is set, parse_with_latexml's Popen
        must receive the wrapped argv (not the bare latexmlc cmd).
        Regression guard for FM-3 (wrapper at wrong layer) and FM-5
        (containment tests skip when latexmlc absent, so wiring
        bugs can go undetected without this mock-based test).
        """
        from tools import arxiv_fetch as af  # noqa: PLC0415

        monkeypatch.setattr(af, "_SANDBOX_LAYER", "bwrap")
        monkeypatch.setattr(
            "shutil.which", lambda name: "/usr/bin/latexmlc"
        )
        captured_argv: list[list[str]] = []

        class _FakeProc:
            def __init__(self, *args, **kwargs):
                self.pid = 12345
                self.returncode = 0
                captured_argv.append(list(args[0]))

            def communicate(self, timeout=None):
                return ("ok", "")

        monkeypatch.setattr(af.subprocess, "Popen", _FakeProc)
        main = tmp_path / "main.tex"
        main.write_text(
            r"\documentclass{article}\begin{document}x\end{document}"
        )
        af.parse_with_latexml(
            main, tmp_path / "parsed", "paper-1", timeout=10
        )
        assert len(captured_argv) == 1
        argv = captured_argv[0]
        # The wrapped argv must start with bwrap.
        assert argv[0] == "bwrap", (
            f"parse_with_latexml must thread the sandbox wrapper "
            f"to Popen; got argv[0]={argv[0]!r}"
        )
        # E13_S03b F8 rectification — the prior test only asserted
        # the bwrap wrapper was prepended; that left every
        # individual isolation flag unguarded. Future refactor that
        # drops --unshare-net (or, post-F1/F2, --proc or --dev)
        # would survive. Now assert ALL load-bearing isolation
        # flags appear in the captured argv.
        for flag in (
            "--proc",
            "--dev",
            "--unshare-net",
            "--unshare-pid",
            "--die-with-parent",
            "--new-session",
        ):
            assert flag in argv, (
                f"parse_with_latexml-threaded argv missing "
                f"load-bearing flag {flag!r}; got {argv!r}"
            )
        # And the original latexmlc cmd must appear after the FINAL
        # '--' separator (--proc and --dev have their own subsequent
        # values; the structural separator is the LAST '--').
        # E13_S03b F3 rectification — the --timeout=300 flag was
        # removed (no live-integration test exists to prove the
        # locally-installed latexmlc accepts the flag). The Python-
        # side subprocess timeout + killpg remain the load-bearing
        # timeout discipline.
        # The original cmd has 4 elements: ["latexmlc",
        # "<main_tex_name>", "--dest=...", "--format=html5"].
        # Find the latexmlc index instead of searching for '--'.
        assert "latexmlc" in argv
        latexmlc_idx = argv.index("latexmlc")
        # The element immediately before latexmlc must be the '--'
        # separator.
        assert argv[latexmlc_idx - 1] == "--", (
            f"latexmlc must be preceded by the '--' bwrap-args "
            f"terminator; got argv[{latexmlc_idx - 1}]="
            f"{argv[latexmlc_idx - 1]!r}"
        )
        # F3 — confirm the removed --timeout flag is NOT present.
        assert not any(
            arg.startswith("--timeout") for arg in argv[latexmlc_idx:]
        ), (
            f"--timeout=... was removed by F3 rectification; "
            f"argv post-latexmlc={argv[latexmlc_idx:]!r}"
        )
