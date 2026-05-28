"""Tests for the sandboxed MinerU subprocess driver (textbook-ingest-m5).

Three tiers (mirrors the parser-fidelity-eval-m1 test layout):

1. **Pure-Python unit tests** (always run). Cover the helpers that
   don't invoke MinerU: env parsing, binary resolution, env scrubbing,
   tail truncation, output locator, and the run_mineru_sandboxed
   surface with subprocess.Popen mocked.

2. **Integration tests** (gated behind ``requires_mineru`` +
   ``ARXMCP_RUN_REAL_MINERU=1`` + ``ARXMCP_MINERU_BIN`` set).
   Drive a real MinerU 3.2.0 invocation against a synthetic 1-page
   PDF generated in the test.

3. **Sandbox-enforcement tests** (also gated). Validate the wall-clock
   timeout path against a controlled subprocess.
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ingest import textbook_parser
from ingest.textbook_parser import (
    _DEFAULT_TIMEOUT_S,
    _ENV_WHITELIST,
    _MINERU_RLIMIT_AS_BYTES,
    _OUTPUT_TAIL_BYTES,
    _RLIMIT_AS_PLATFORM,
    _TIMEOUT_MAX_S,
    _TIMEOUT_MIN_S,
    MinerUResult,
    _locate_outputs,
    _parse_timeout_from_env,
    _resolve_mineru_binary,
    _scrub_subprocess_env,
    _tail,
    run_mineru_sandboxed,
)

# ---------------------------------------------------------------------------
# Tier 1 — pure-Python unit tests
# ---------------------------------------------------------------------------


class TestParseTimeoutFromEnv:
    """Module-load timeout parsing rejects bad inputs explicitly."""

    def test_unset_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARXMCP_MINERU_TIMEOUT_S", raising=False)
        assert _parse_timeout_from_env() == _DEFAULT_TIMEOUT_S

    def test_empty_string_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARXMCP_MINERU_TIMEOUT_S", "")
        assert _parse_timeout_from_env() == _DEFAULT_TIMEOUT_S

    def test_whitespace_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARXMCP_MINERU_TIMEOUT_S", "   ")
        assert _parse_timeout_from_env() == _DEFAULT_TIMEOUT_S

    def test_valid_value_parsed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARXMCP_MINERU_TIMEOUT_S", "120")
        assert _parse_timeout_from_env() == 120

    def test_min_value_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARXMCP_MINERU_TIMEOUT_S", str(_TIMEOUT_MIN_S))
        assert _parse_timeout_from_env() == _TIMEOUT_MIN_S

    def test_max_value_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARXMCP_MINERU_TIMEOUT_S", str(_TIMEOUT_MAX_S))
        assert _parse_timeout_from_env() == _TIMEOUT_MAX_S

    def test_non_integer_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARXMCP_MINERU_TIMEOUT_S", "foo")
        with pytest.raises(RuntimeError, match="not a valid integer"):
            _parse_timeout_from_env()

    def test_below_min_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARXMCP_MINERU_TIMEOUT_S", str(_TIMEOUT_MIN_S - 1))
        with pytest.raises(RuntimeError, match="out of range"):
            _parse_timeout_from_env()

    def test_above_max_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARXMCP_MINERU_TIMEOUT_S", str(_TIMEOUT_MAX_S + 1))
        with pytest.raises(RuntimeError, match="out of range"):
            _parse_timeout_from_env()

    def test_negative_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARXMCP_MINERU_TIMEOUT_S", "-30")
        with pytest.raises(RuntimeError, match="out of range"):
            _parse_timeout_from_env()


class TestResolveMineruBinary:
    """Binary resolution chain: env var → which → RuntimeError."""

    def test_env_var_set_to_existing_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        fake_bin = tmp_path / "mineru"
        fake_bin.write_text("#!/bin/sh\nexit 0\n")
        fake_bin.chmod(0o755)
        monkeypatch.setenv("ARXMCP_MINERU_BIN", str(fake_bin))
        assert _resolve_mineru_binary() == str(fake_bin)

    def test_env_var_set_to_missing_path_raises(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ARXMCP_MINERU_BIN", "/nonexistent/path/mineru")
        with pytest.raises(RuntimeError, match="does not point to a file"):
            _resolve_mineru_binary()

    def test_unset_falls_back_to_which(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ARXMCP_MINERU_BIN", raising=False)
        with patch.object(shutil, "which", return_value="/usr/local/bin/mineru"):
            assert _resolve_mineru_binary() == "/usr/local/bin/mineru"

    def test_unset_and_which_empty_raises(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ARXMCP_MINERU_BIN", raising=False)
        with (
            patch.object(shutil, "which", return_value=None),
            pytest.raises(RuntimeError, match="mineru binary not found"),
        ):
            _resolve_mineru_binary()

    def test_empty_env_var_falls_through_to_which(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ARXMCP_MINERU_BIN", "")
        with patch.object(shutil, "which", return_value="/usr/bin/mineru"):
            assert _resolve_mineru_binary() == "/usr/bin/mineru"


class TestScrubSubprocessEnv:
    """Env scrubbing: whitelist + TMPDIR override."""

    def test_whitelist_passes_through(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        monkeypatch.setenv("HOME", "/home/test")
        monkeypatch.setenv("LANG", "en_US.UTF-8")
        env = _scrub_subprocess_env(tmp_path)
        assert env["PATH"] == "/usr/bin:/bin"
        assert env["HOME"] == "/home/test"
        assert env["LANG"] == "en_US.UTF-8"

    def test_tmpdir_overridden_to_output_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("TMPDIR", "/some/other/notebook/tmp")
        env = _scrub_subprocess_env(tmp_path)
        assert env["TMPDIR"] == str(tmp_path)

    def test_tmpdir_set_even_if_unset_in_parent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.delenv("TMPDIR", raising=False)
        env = _scrub_subprocess_env(tmp_path)
        assert env["TMPDIR"] == str(tmp_path)

    def test_non_whitelist_vars_stripped(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        # Inject everything we explicitly want to strip.
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "leak")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "leak")
        monkeypatch.setenv("HF_TOKEN", "leak")
        monkeypatch.setenv("HF_HOME", "/leaked/cache")
        monkeypatch.setenv("HTTP_PROXY", "http://proxy")
        monkeypatch.setenv("HTTPS_PROXY", "http://proxy")
        monkeypatch.setenv("NO_PROXY", "localhost")
        env = _scrub_subprocess_env(tmp_path)
        for k in (
            "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
            "HF_TOKEN", "HF_HOME",
            "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
        ):
            assert k not in env, f"{k} leaked into scrubbed env"

    def test_whitelist_set_unchanged(self) -> None:
        # Pinned exactly so a future PR widening the whitelist must
        # update both the constant and this test.
        assert frozenset({"PATH", "HOME", "LANG", "LC_ALL"}) == _ENV_WHITELIST

    def test_env_var_absent_from_parent_is_absent_from_child(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.delenv("LC_ALL", raising=False)
        env = _scrub_subprocess_env(tmp_path)
        assert "LC_ALL" not in env


class TestTail:
    """8 KB tail-truncation for stdout/stderr fields."""

    def test_short_input_passes_through(self) -> None:
        s = "hello"
        assert _tail(s) == s

    def test_empty_input(self) -> None:
        assert _tail("") == ""

    def test_at_boundary(self) -> None:
        s = "x" * _OUTPUT_TAIL_BYTES
        assert _tail(s) == s

    def test_one_over_boundary(self) -> None:
        s = "x" * (_OUTPUT_TAIL_BYTES + 1)
        result = _tail(s)
        # We get the LAST n bytes, so length is the budget exactly.
        assert len(result.encode("utf-8")) == _OUTPUT_TAIL_BYTES

    def test_truncation_keeps_tail(self) -> None:
        s = "a" * _OUTPUT_TAIL_BYTES + "TAIL_MARKER"
        result = _tail(s)
        assert result.endswith("TAIL_MARKER")

    def test_unicode_safe(self) -> None:
        # Multi-byte chars that might land on a truncation boundary.
        # Encode/decode with errors="replace" prevents UnicodeDecodeError.
        s = "α" * 5000 + "β" * 5000
        result = _tail(s)
        assert len(result.encode("utf-8")) <= _OUTPUT_TAIL_BYTES


class TestLocateOutputs:
    """MinerU output-tree resolution post-subprocess."""

    def _make_outputs(
        self, root: Path, stem: str, *, with_md: bool = True,
        with_cl: bool = True, parse_method: str = "auto",
    ) -> tuple[Path, Path]:
        auto_dir = root / stem / parse_method
        auto_dir.mkdir(parents=True, exist_ok=True)
        md = auto_dir / f"{stem}.md"
        cl = auto_dir / f"{stem}_content_list.json"
        if with_md:
            md.write_text("# Heading\n")
        if with_cl:
            cl.write_text("[]")
        return md, cl

    def test_direct_path_resolves(self, tmp_path: Path) -> None:
        md, cl = self._make_outputs(tmp_path, "doc")
        rmd, rcl = _locate_outputs(tmp_path, "doc")
        assert rmd == md
        assert rcl == cl

    def test_glob_fallback_finds_md(self, tmp_path: Path) -> None:
        # MinerU emitted under a non-"auto" parse method.
        md, cl = self._make_outputs(tmp_path, "doc", parse_method="txt")
        rmd, rcl = _locate_outputs(tmp_path, "doc")
        assert rmd == md
        assert rcl == cl

    def test_no_markdown_raises(self, tmp_path: Path) -> None:
        # content_list present, .md missing — output_tree partial.
        self._make_outputs(tmp_path, "doc", with_md=False)
        with pytest.raises(RuntimeError, match="no .md file found"):
            _locate_outputs(tmp_path, "doc")

    def test_no_content_list_raises(self, tmp_path: Path) -> None:
        # .md present, content_list missing.
        self._make_outputs(tmp_path, "doc", with_cl=False)
        # Glob fallback finds the .md but then complains about cl.
        with pytest.raises(RuntimeError, match="content_list"):
            _locate_outputs(tmp_path, "doc")

    def test_empty_dir_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match="no .md file found"):
            _locate_outputs(tmp_path, "doc")

    def test_glob_fallback_picks_paired_files(self, tmp_path: Path) -> None:
        """Regression for m5 F4: fallback must NEVER cross-pair files
        from different parse-method subdirs.
        """
        # Mismatched layout: dirA has .md only, dirB has .json only.
        dir_a = tmp_path / "dirA"
        dir_a.mkdir()
        (dir_a / "x.md").write_text("# A\n")
        dir_b = tmp_path / "dirB"
        dir_b.mkdir()
        (dir_b / "y_content_list.json").write_text("[]")
        with pytest.raises(RuntimeError, match="no paired"):
            _locate_outputs(tmp_path, "doc")

    def test_glob_fallback_finds_first_paired(self, tmp_path: Path) -> None:
        """When multiple md files exist, return the FIRST one whose
        sibling _content_list.json is present.
        """
        # First md (alphabetically) has no companion; second does.
        dir_a = tmp_path / "a-no-companion"
        dir_a.mkdir()
        (dir_a / "x.md").write_text("# A\n")
        dir_b = tmp_path / "b-with-companion"
        dir_b.mkdir()
        md_b = dir_b / "y.md"
        cl_b = dir_b / "y_content_list.json"
        md_b.write_text("# B\n")
        cl_b.write_text("[]")
        rmd, rcl = _locate_outputs(tmp_path, "doc")
        assert rmd == md_b
        assert rcl == cl_b


class TestPlatformSetup:
    """Module-level platform-specific RLIMIT setup."""

    def test_rlimit_platform_constant(self) -> None:
        # Sanity: the constant we gate on is "linux", not anything else.
        # If a future PR changes this, both _set_mineru_rlimits and the
        # security-pdf-sandbox.md doc must move in lockstep.
        assert _RLIMIT_AS_PLATFORM == "linux"

    def test_rlimit_4gb_constant(self) -> None:
        # If a future PR changes the cap, the security-pdf-sandbox.md
        # doc must update in the same commit (m4 F2 anti-pattern guard).
        assert _MINERU_RLIMIT_AS_BYTES == 4 * 1024 * 1024 * 1024

    def test_preexec_fn_matches_platform(self) -> None:
        if sys.platform == _RLIMIT_AS_PLATFORM:
            assert textbook_parser._set_mineru_rlimits is not None
            assert textbook_parser._resource is not None
        else:
            # macOS and Windows get None + WARN at import.
            assert textbook_parser._set_mineru_rlimits is None
            assert textbook_parser._resource is None

    def test_warn_fires_on_non_linux_import(self, tmp_path: Path) -> None:
        """Closes m5 F7: regression guard that the macOS/Windows WARN
        log fires at module import.

        The WARN is the only operator signal that the verified-live
        macOS RLIMIT_AS gap is in effect; silently dropping it would
        leave Darwin operators believing the 4 GB cap is active when
        only the wall timeout is.

        Spawns a subprocess that overrides ``sys.platform = "darwin"``
        BEFORE importing the module, captures stderr, and asserts the
        WARN appears. Subprocess isolation avoids the in-process
        ``importlib.reload`` pollution that would invalidate
        ``isinstance(x, MinerUResult)`` checks in downstream tests.
        """
        script = tmp_path / "darwin_import_check.py"
        script.write_text(
            "import sys\n"
            "sys.platform = 'darwin'\n"
            "import logging\n"
            "logging.basicConfig(level=logging.WARNING)\n"
            "from ingest import textbook_parser  # noqa: F401\n"
        )
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, check=False,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        assert result.returncode == 0, (
            f"subprocess exited {result.returncode}: stderr={result.stderr!r}"
        )
        assert "RLIMIT_AS cap not enforceable on platform" in result.stderr, (
            f"expected RLIMIT_AS WARN in subprocess stderr; got: "
            f"{result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# Tier 1 — run_mineru_sandboxed with Popen mocked
# ---------------------------------------------------------------------------


def _fake_proc(
    stdout: str = "", stderr: str = "", returncode: int = 0,
    pid: int = 12345, raise_timeout: bool = False,
) -> MagicMock:
    proc = MagicMock(spec=subprocess.Popen)
    proc.pid = pid
    proc.returncode = returncode
    if raise_timeout:
        proc.communicate.side_effect = subprocess.TimeoutExpired(
            cmd="mineru", timeout=1,
        )
    else:
        proc.communicate.return_value = (stdout, stderr)
    return proc


class TestRunMineruSandboxedSurface:
    """``run_mineru_sandboxed`` with subprocess.Popen mocked."""

    def _make_pdf_and_outputs(
        self, tmp_path: Path, stem: str = "test",
    ) -> tuple[Path, Path]:
        pdf = tmp_path / f"{stem}.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%fake\n")
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        # Pre-create the output tree the locator expects, so the
        # subprocess "success" path can resolve.
        auto = out_dir / stem / "auto"
        auto.mkdir(parents=True)
        (auto / f"{stem}.md").write_text("# Heading\n")
        (auto / f"{stem}_content_list.json").write_text("[]")
        return pdf, out_dir

    def test_happy_path_returns_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pdf, out_dir = self._make_pdf_and_outputs(tmp_path)
        monkeypatch.setenv("ARXMCP_MINERU_BIN", _create_fake_bin(tmp_path))
        with patch.object(
            subprocess, "Popen",
            return_value=_fake_proc(stdout="loaded", stderr=""),
        ) as mock_popen:
            result = run_mineru_sandboxed(pdf, out_dir, timeout_s=60)
        assert isinstance(result, MinerUResult)
        assert result.output_dir == out_dir
        assert result.markdown_path.is_file()
        assert result.content_list_path.is_file()
        assert result.stdout == "loaded"
        assert result.wall_clock_s >= 0
        # Verify the command shape.
        call_args, call_kwargs = mock_popen.call_args
        cmd = call_args[0]
        assert "-p" in cmd and str(pdf) in cmd
        assert "-o" in cmd and str(out_dir) in cmd
        assert cmd[-4:] == ["-b", "pipeline", "-m", "auto"]
        # Verify sandbox settings.
        assert call_kwargs["start_new_session"] is True
        assert call_kwargs["stdout"] == subprocess.PIPE
        assert call_kwargs["stderr"] == subprocess.PIPE
        assert call_kwargs["text"] is True
        assert call_kwargs["cwd"] == str(out_dir)
        # preexec_fn only on Linux.
        if sys.platform == _RLIMIT_AS_PLATFORM:
            assert call_kwargs.get("preexec_fn") is not None
        else:
            assert "preexec_fn" not in call_kwargs

    def test_env_scrubbed_in_popen_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pdf, out_dir = self._make_pdf_and_outputs(tmp_path)
        monkeypatch.setenv("ARXMCP_MINERU_BIN", _create_fake_bin(tmp_path))
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "leak")
        monkeypatch.setenv("HF_TOKEN", "leak")
        with patch.object(
            subprocess, "Popen", return_value=_fake_proc(),
        ) as mock_popen:
            run_mineru_sandboxed(pdf, out_dir, timeout_s=60)
        _, kwargs = mock_popen.call_args
        env = kwargs["env"]
        assert "AWS_SECRET_ACCESS_KEY" not in env
        assert "HF_TOKEN" not in env
        assert env["TMPDIR"] == str(out_dir)

    def test_subprocess_nonzero_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pdf, out_dir = self._make_pdf_and_outputs(tmp_path)
        monkeypatch.setenv("ARXMCP_MINERU_BIN", _create_fake_bin(tmp_path))
        with patch.object(
            subprocess, "Popen",
            return_value=_fake_proc(returncode=1, stderr="boom"),
        ), pytest.raises(RuntimeError, match="exited 1"):
            run_mineru_sandboxed(pdf, out_dir, timeout_s=60)

    def test_timeout_triggers_killpg(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        pdf, out_dir = self._make_pdf_and_outputs(tmp_path)
        monkeypatch.setenv("ARXMCP_MINERU_BIN", _create_fake_bin(tmp_path))
        # First communicate() raises TimeoutExpired; the second drain
        # call returns non-empty tail output. Closes m5 F5 — assert
        # the drained stderr surfaces in the WARN log.
        proc = MagicMock(spec=subprocess.Popen)
        proc.pid = 12345
        proc.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd="mineru", timeout=1),
            ("late stdout chunk", "[ERROR] killed mid-decode at offset 42"),
        ]
        import logging
        with (
            caplog.at_level(logging.WARNING, logger="ingest.textbook_parser"),
            patch.object(subprocess, "Popen", return_value=proc),
            patch.object(os, "killpg") as mock_killpg,
            patch.object(os, "getpgid", return_value=12345),
            pytest.raises(subprocess.TimeoutExpired),
        ):
            run_mineru_sandboxed(pdf, out_dir, timeout_s=60)
        mock_killpg.assert_called_once_with(12345, signal.SIGKILL)
        # The drain call MUST follow the killpg.
        assert proc.communicate.call_count == 2
        # F5 regression: drained stderr tail captured in WARN log.
        warn_msgs = [
            r.getMessage() for r in caplog.records
            if r.levelname == "WARNING"
        ]
        assert any(
            "killed mid-decode at offset 42" in m for m in warn_msgs
        ), f"drain stderr not captured in WARN log: {warn_msgs!r}"

    def test_invalid_pdf_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match="pdf_path is not a file"):
            run_mineru_sandboxed(
                tmp_path / "nonexistent.pdf", tmp_path, timeout_s=60,
            )

    def test_invalid_output_dir_raises(self, tmp_path: Path) -> None:
        pdf = tmp_path / "x.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        with pytest.raises(RuntimeError, match="output_dir is not a directory"):
            run_mineru_sandboxed(
                pdf, tmp_path / "nonexistent_dir", timeout_s=60,
            )

    def test_out_of_range_timeout_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pdf, out_dir = self._make_pdf_and_outputs(tmp_path)
        with pytest.raises(RuntimeError, match="out of range"):
            run_mineru_sandboxed(pdf, out_dir, timeout_s=5)
        with pytest.raises(RuntimeError, match="out of range"):
            run_mineru_sandboxed(pdf, out_dir, timeout_s=99999)

    def test_missing_binary_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pdf, out_dir = self._make_pdf_and_outputs(tmp_path)
        monkeypatch.delenv("ARXMCP_MINERU_BIN", raising=False)
        with (
            patch.object(shutil, "which", return_value=None),
            pytest.raises(RuntimeError, match="mineru binary not found"),
        ):
            run_mineru_sandboxed(pdf, out_dir, timeout_s=60)

    def test_default_timeout_used_when_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Closes m5 F6: prove `timeout_s=None` uses the module-load
        ``_CONFIGURED_TIMEOUT_S`` rather than a hard-coded literal.

        The pre-fix test asserted ``timeout == _CONFIGURED_TIMEOUT_S``,
        which was a tautology — both sides resolve to the same module-
        level constant. To actually detect a regression where the
        driver started ignoring _CONFIGURED_TIMEOUT_S, we patch the
        constant in-module to a sentinel value and verify the driver
        picks IT up.
        """
        pdf, out_dir = self._make_pdf_and_outputs(tmp_path)
        monkeypatch.setenv("ARXMCP_MINERU_BIN", _create_fake_bin(tmp_path))
        sentinel_timeout = 173  # a value that cannot coincide with the default
        monkeypatch.setattr(
            textbook_parser, "_CONFIGURED_TIMEOUT_S", sentinel_timeout,
        )
        with patch.object(
            subprocess, "Popen", return_value=_fake_proc(),
        ) as mock_popen:
            run_mineru_sandboxed(pdf, out_dir, timeout_s=None)
        proc = mock_popen.return_value
        proc.communicate.assert_called_once()
        _, comm_kwargs = proc.communicate.call_args
        # If the driver had hard-coded 1800, this would fail with 173 != 1800.
        assert comm_kwargs["timeout"] == sentinel_timeout


def _create_fake_bin(tmp_path: Path) -> str:
    bin_path = tmp_path / "fake_mineru"
    bin_path.write_text("#!/bin/sh\nexit 0\n")
    bin_path.chmod(0o755)
    return str(bin_path)


class TestMinerUResultIsFrozen:
    """The result type is a frozen dataclass — mutations raise."""

    def test_cannot_reassign_field(self, tmp_path: Path) -> None:
        result = MinerUResult(
            output_dir=tmp_path,
            markdown_path=tmp_path / "x.md",
            content_list_path=tmp_path / "x.json",
            stdout="", stderr="", wall_clock_s=0.0,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.stdout = "tampered"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Tier 3 — Integration tests against a real MinerU binary
# ---------------------------------------------------------------------------


def _make_minimal_pdf(path: Path) -> None:
    """Write a minimal valid 1-page PDF containing the text "Hello".

    Pure-stdlib generator: produces ~700 bytes of PDF bytes with
    correct xref offsets. Used as the integration-test fixture so the
    test does not depend on an external file or another package.
    """
    obj1 = b"<< /Type /Catalog /Pages 2 0 R >>"
    obj2 = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
    obj3 = (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
    )
    stream = b"BT /F1 24 Tf 100 700 Td (Hello, World!) Tj ET"
    obj4 = (
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\n"
        b"stream\n" + stream + b"\nendstream"
    )
    obj5 = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    objs = [obj1, obj2, obj3, obj4, obj5]
    out = bytearray()
    out.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(out))
        out.extend(f"{i} 0 obj\n".encode("ascii"))
        out.extend(obj)
        out.extend(b"\nendobj\n")
    xref_offset = len(out)
    out.extend(b"xref\n0 6\n")
    out.extend(b"0000000000 65535 f \n")
    for off in offsets:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(b"trailer\n<< /Size 6 /Root 1 0 R >>\n")
    out.extend(b"startxref\n")
    out.extend(f"{xref_offset}\n".encode("ascii"))
    out.extend(b"%%EOF\n")
    path.write_bytes(bytes(out))


@pytest.mark.requires_mineru
@pytest.mark.skipif(
    "os.environ.get('ARXMCP_RUN_REAL_MINERU') != '1'"
    " or not os.environ.get('ARXMCP_MINERU_BIN')",
    reason="needs ARXMCP_RUN_REAL_MINERU=1 + ARXMCP_MINERU_BIN set",
)
class TestRealMineru:
    """End-to-end against the installed MinerU binary.

    Opt-in only. The lazy string-condition skipif is the F7 pattern
    from parser-fidelity-eval-m1: it re-evaluates at test-run time so
    later CI overrides actually unstick the skip.
    """

    def test_minimal_pdf_parses(self, tmp_path: Path) -> None:
        pdf = tmp_path / "minimal.pdf"
        _make_minimal_pdf(pdf)
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        # Use a long-enough timeout to cover model load on a cold
        # cache; first invocation may take 5+ min for ONNX warm-up.
        result = run_mineru_sandboxed(pdf, out_dir, timeout_s=1800)
        assert isinstance(result, MinerUResult)
        assert result.markdown_path.is_file()
        assert result.content_list_path.is_file()
        assert result.markdown_path.stat().st_size > 0
        assert result.wall_clock_s > 0


@pytest.mark.requires_mineru
@pytest.mark.skipif(
    "os.environ.get('ARXMCP_RUN_REAL_MINERU') != '1'"
    " or not os.environ.get('ARXMCP_MINERU_BIN')",
    reason="needs ARXMCP_RUN_REAL_MINERU=1 + ARXMCP_MINERU_BIN set",
)
class TestSandboxEnforcement:
    """Sandbox-profile enforcement against real MinerU."""

    def test_wall_timeout_triggers_killpg(self, tmp_path: Path) -> None:
        """A 60s timeout against a fresh-cache MinerU invocation
        triggers the killpg path. Model load is well over 60s on a
        cold start; the goal is to verify the timeout PATH FIRES and
        TimeoutExpired propagates cleanly — not to measure perf.

        On a warm cache this test may be flaky (MinerU loads in <60s).
        Operator runs with a cold cache or after `rm -rf ~/.cache/mineru/lib`
        to actually exercise the path.
        """
        pdf = tmp_path / "minimal.pdf"
        _make_minimal_pdf(pdf)
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        with pytest.raises(subprocess.TimeoutExpired):
            run_mineru_sandboxed(pdf, out_dir, timeout_s=_TIMEOUT_MIN_S)
