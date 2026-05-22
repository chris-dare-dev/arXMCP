"""Tests for the Lean REPL subprocess harness (verification-feedback-m2).

Two test tiers:

1. **Always-run** — config defaults, the fail-loud contract
   (`LeanUnavailableError` on an unresolvable toolchain), and the
   error-type hierarchy. No Lean toolchain required.
2. **`@pytest.mark.requires_lean_repl`** — JSON round-trip tests
   against a REAL Lean 4 REPL. Skipped unless both ``ARXMCP_LAKE_PATH``
   and ``ARXMCP_LEAN_REPL_DIR`` are set (the opt-in pattern mirroring
   ``requires_model`` / ``ARXMCP_RUN_REAL_BGE_RERANKER``).
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from server.config import Config
from server.lean_repl import (
    LeanRepl,
    LeanReplError,
    LeanUnavailableError,
)
from server.resources import ResourceStartupError

# ---------------------------------------------------------------------------
# Lean-toolchain opt-in detection (mirrors ARXMCP_RUN_REAL_BGE_RERANKER)
# ---------------------------------------------------------------------------

_LAKE_PATH = os.environ.get("ARXMCP_LAKE_PATH")
_REPL_DIR = os.environ.get("ARXMCP_LEAN_REPL_DIR")
_LEAN_AVAILABLE = bool(_LAKE_PATH and _REPL_DIR)
_lean_skip = pytest.mark.skipif(
    not _LEAN_AVAILABLE,
    reason="set ARXMCP_LAKE_PATH + ARXMCP_LEAN_REPL_DIR to exercise the real Lean REPL",
)


def _run(coro):
    return asyncio.run(coro)


# ===========================================================================
# Tier 1 — always-run (no Lean toolchain needed)
# ===========================================================================


class TestConfigGate:
    def test_enable_lean_defaults_false(self):
        """AC1: ARXMCP_ENABLE_LEAN is a Config field defaulting false —
        the server starts cleanly on a workstation with no Lean."""
        assert Config.model_fields["enable_lean"].default is False
        assert Config.model_fields["lean_repl_dir"].default is None
        assert Config.model_fields["lake_path"].default is None

    def test_explicit_disabled_config_has_no_lean(self):
        cfg = Config(enable_lean=False, lake_path=None, lean_repl_dir=None)
        assert cfg.enable_lean is False


class TestFailLoudContract:
    """AC: ARXMCP_ENABLE_LEAN=true with an unresolvable toolchain must
    raise — the server refuses to start (the enable_rerank /
    RerankerUnavailableError precedent), it does NOT silently degrade."""

    def test_lean_unavailable_is_a_resource_startup_error(self):
        # The lifespan catches the broad Exception, but subclassing
        # ResourceStartupError documents intent + keeps the error in
        # the same family the lifespan FATAL-logs.
        assert issubclass(LeanUnavailableError, ResourceStartupError)

    def test_spawn_from_config_raises_when_paths_unset(self):
        cfg = Config(enable_lean=True, lake_path=None, lean_repl_dir=None)
        with pytest.raises(LeanUnavailableError, match="ARXMCP_LAKE_PATH"):
            _run(LeanRepl.spawn_from_config(cfg))

    def test_spawn_raises_when_lake_binary_missing(self, tmp_path: Path):
        with pytest.raises(LeanUnavailableError, match="lake binary not found"):
            _run(
                LeanRepl.spawn(
                    lake_path=tmp_path / "no_such_lake",
                    repl_dir=tmp_path,
                )
            )

    def test_spawn_raises_when_repl_dir_missing(self, tmp_path: Path):
        fake_lake = tmp_path / "lake"
        fake_lake.write_text("", encoding="utf-8")  # a real file
        with pytest.raises(
            LeanUnavailableError, match="REPL package directory not found"
        ):
            _run(
                LeanRepl.spawn(
                    lake_path=fake_lake,
                    repl_dir=tmp_path / "no_such_repl_dir",
                )
            )


# ===========================================================================
# Tier 1b — always-run query / round-trip / close coverage via a fake
# subprocess (m2 critique F2). No Lean toolchain required.
# ===========================================================================


class _FakeStdin:
    """Stand-in for ``proc.stdin``: captures bytes; ``drain`` is a no-op."""

    def __init__(self) -> None:
        self.buffer = b""

    def write(self, data: bytes) -> None:
        self.buffer += data

    async def drain(self) -> None:
        return None


class _FakeStdout:
    """Stand-in for ``proc.stdout``: yields canned lines then EOF (``b""``).

    With ``hang=True`` every ``readline`` blocks forever — used to drive
    the :meth:`LeanRepl.query` timeout path.
    """

    def __init__(self, lines: list[bytes], *, hang: bool = False) -> None:
        self._lines = list(lines)
        self._hang = hang

    async def readline(self) -> bytes:
        if self._hang:
            await asyncio.sleep(3600)
        return self._lines.pop(0) if self._lines else b""


class _FakeProc:
    """A stand-in for ``asyncio.subprocess.Process`` — exercises the
    ``LeanRepl`` query / ``_round_trip`` / ``close`` logic with no real
    Lean toolchain. ``wait_hangs=True`` simulates a wedged parent-side
    transport so the kill-escalation reap can be tested."""

    def __init__(
        self,
        *,
        stdout_lines: list[bytes] | None = None,
        stdout_hang: bool = False,
        returncode: int | None = None,
        wait_hangs: bool = False,
    ) -> None:
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout(stdout_lines or [], hang=stdout_hang)
        self.returncode = returncode
        self._wait_hangs = wait_hangs
        self.terminate_called = False
        self.kill_called = False

    def terminate(self) -> None:
        self.terminate_called = True
        if not self._wait_hangs:
            self.returncode = -15

    def kill(self) -> None:
        self.kill_called = True
        if not self._wait_hangs:
            self.returncode = -9

    async def wait(self) -> int | None:
        if self._wait_hangs:
            await asyncio.sleep(3600)
        return self.returncode


def _repl(proc: _FakeProc) -> LeanRepl:
    """Build a LeanRepl directly over a fake process (bypasses spawn)."""
    return LeanRepl(proc, Path("fake_lake"), Path("fake_repl_dir"))


class TestFakeProcRoundTrips:
    """Always-run coverage for query / _round_trip / close — the
    timeout, EOF, non-JSON, missing-terminator, and kill-escalation
    paths — driven by a fake subprocess (m2 critique F2)."""

    def test_query_returns_parsed_json(self):
        proc = _FakeProc(stdout_lines=[b'{"env": 0}\n', b"\n"])
        resp = _run(_repl(proc).query({"cmd": "x"}))
        assert resp == {"env": 0}
        # The command was framed as JSON + a double newline on stdin.
        assert proc.stdin.buffer == b'{"cmd": "x"}\n\n'

    def test_query_returns_without_trailing_blank_line(self):
        """F3 guard: a response with NO trailing blank line must return
        immediately on the successful parse, not hang to the timeout."""
        proc = _FakeProc(stdout_lines=[b'{"env": 0}\n'])  # no blank line
        resp = _run(_repl(proc).query({"cmd": "x"}, timeout=2.0))
        assert resp == {"env": 0}

    def test_query_parses_multi_line_json(self):
        proc = _FakeProc(
            stdout_lines=[b"{\n", b'  "env": 0\n', b"}\n", b"\n"]
        )
        resp = _run(_repl(proc).query({"cmd": "x"}))
        assert resp == {"env": 0}

    def test_query_timeout_raises_lean_repl_error(self):
        proc = _FakeProc(stdout_hang=True)
        with pytest.raises(LeanReplError, match="timeout"):
            _run(_repl(proc).query({"cmd": "x"}, timeout=0.1))

    def test_query_eof_before_response_raises(self):
        proc = _FakeProc(stdout_lines=[])  # readline -> b"" (EOF) at once
        with pytest.raises(LeanReplError, match="closed stdout"):
            _run(_repl(proc).query({"cmd": "x"}))

    def test_query_non_json_response_raises(self):
        proc = _FakeProc(stdout_lines=[b"not json at all\n", b"\n"])
        with pytest.raises(LeanReplError, match="non-JSON"):
            _run(_repl(proc).query({"cmd": "x"}))

    def test_query_after_exit_raises(self):
        proc = _FakeProc(returncode=0)
        with pytest.raises(LeanReplError, match="has exited"):
            _run(_repl(proc).query({"cmd": "x"}))

    def test_close_terminates_and_reaps(self):
        proc = _FakeProc(returncode=None)
        repl = _repl(proc)
        assert repl.is_running is True
        _run(repl.close())
        assert proc.terminate_called is True
        assert repl.is_running is False
        # close() is idempotent — a second call is a no-op.
        _run(repl.close())

    def test_close_escalates_to_kill_and_stays_bounded(self, monkeypatch):
        """F5 guard: when terminate()'s grace wait AND the post-kill()
        reap both stall, close() still returns within a bounded time
        rather than hanging the lifespan shutdown drain."""
        monkeypatch.setattr("server.lean_repl._CLOSE_GRACE_S", 0.1)
        proc = _FakeProc(returncode=None, wait_hangs=True)
        repl = _repl(proc)
        start = time.monotonic()
        _run(repl.close())
        elapsed = time.monotonic() - start
        assert proc.terminate_called is True
        assert proc.kill_called is True
        # Two bounded waits of ~0.1s each — generously under 5s.
        assert elapsed < 5.0


# ===========================================================================
# Tier 2 — real Lean REPL round-trips (requires the toolchain)
# ===========================================================================


@_lean_skip
@pytest.mark.requires_lean_repl
class TestRealLeanRepl:
    """JSON round-trips against a real Lean 4 REPL. Each test spawns and
    closes its own subprocess for isolation."""

    @staticmethod
    async def _with_repl(fn):
        repl = await LeanRepl.spawn(lake_path=_LAKE_PATH, repl_dir=_REPL_DIR)
        try:
            return await fn(repl)
        finally:
            await repl.close()

    def test_query_ok_case(self):
        """A valid theorem returns a response with no error-severity
        messages."""
        async def _fn(repl: LeanRepl):
            return await repl.query({"cmd": "theorem m2_ok : 1 + 1 = 2 := rfl"})

        resp = _run(self._with_repl(_fn))
        errors = [
            m for m in resp.get("messages", []) if m.get("severity") == "error"
        ]
        assert errors == [], f"valid theorem produced errors: {errors}"

    def test_query_error_case(self):
        """A type error returns an error message carrying a source
        position — the signal m3's lean_verify needs."""
        async def _fn(repl: LeanRepl):
            return await repl.query({"cmd": "theorem m2_bad : 1 + 1 = 3 := rfl"})

        resp = _run(self._with_repl(_fn))
        errors = [
            m for m in resp.get("messages", []) if m.get("severity") == "error"
        ]
        assert errors, "a type-mismatch theorem must produce an error message"
        assert "pos" in errors[0], "the error message must carry a source position"

    def test_query_sorry_case(self):
        """A `sorry` returns a `sorries` entry carrying the proof state."""
        async def _fn(repl: LeanRepl):
            return await repl.query(
                {"cmd": "theorem m2_sorry (n : Nat) : n = n := by sorry"}
            )

        resp = _run(self._with_repl(_fn))
        sorries = resp.get("sorries", [])
        assert sorries, "a `sorry` proof must produce a `sorries` entry"
        assert isinstance(sorries[0].get("goal"), str) and sorries[0]["goal"], (
            "the sorry entry must carry a non-empty goal (proof state)"
        )

    def test_close_reaps_the_process(self):
        """After close(), the subprocess is no longer running."""
        async def _fn():
            repl = await LeanRepl.spawn(lake_path=_LAKE_PATH, repl_dir=_REPL_DIR)
            assert repl.is_running is True
            await repl.close()
            assert repl.is_running is False
            # close() is idempotent — a second call is a no-op.
            await repl.close()

        _run(_fn())

    def test_query_after_close_raises(self):
        """Querying a closed REPL raises LeanReplError, not a hang."""
        async def _fn():
            repl = await LeanRepl.spawn(lake_path=_LAKE_PATH, repl_dir=_REPL_DIR)
            await repl.close()
            with pytest.raises(LeanReplError, match="has exited"):
                await repl.query({"cmd": "theorem t : True := trivial"})

        _run(_fn())
