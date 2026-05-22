"""Tests for the ``lean_verify`` MCP handler (verification-feedback-m3).

Three tiers:

1. **Always-run** — handler-level tests over a fake LeanRepl. Cover the
   m3 acceptance criteria (type error → status=error; unresolved sorry
   → status=sorry + sorry_goals populated; mode=syntax_only short-
   circuits via #check) plus the FM mitigations from the m3 research
   synthesis (FM-2 timeout = kill+respawn; FM-4 schema-field
   normalization; FM-7 graceful unavailable when enable_lean=false).
2. **POSIX/Windows split** — the RLIMIT_AS preexec_fn check at the
   LeanRepl.spawn site. Implemented as a unit test that monkeypatches
   ``asyncio.create_subprocess_exec`` so the platform-specific
   behaviour is observable.
3. **``@pytest.mark.requires_lean_repl``** — opt-in integration test
   against a REAL Lean toolchain. Asserts a clean theorem returns
   status=ok and the RLIMIT_AS cap is in force (POSIX only).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from server.config import Config
from server.handlers.lean_verify import (
    MAX_IMPORT_LINE_LEN,
    _build_command,
    _normalize_position,
    _normalize_response,
    handle_lean_verify,
)
from server.tools import (
    LEAN_VERIFY,
    TOOL_SCHEMA_VERSION,
    reset_resources_for_tests,
    set_resources,
)

# ---------------------------------------------------------------------------
# Tier-3 opt-in detection (mirrors test_lean_repl.py)
# ---------------------------------------------------------------------------

_LAKE_PATH = os.environ.get("ARXMCP_LAKE_PATH")
_REPL_DIR = os.environ.get("ARXMCP_LEAN_REPL_DIR")
_LEAN_AVAILABLE = bool(_LAKE_PATH and _REPL_DIR)
_lean_skip = pytest.mark.skipif(
    not _LEAN_AVAILABLE,
    reason="set ARXMCP_LAKE_PATH + ARXMCP_LEAN_REPL_DIR for the real Lean REPL",
)


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fake LeanRepl harness
# ---------------------------------------------------------------------------


class _FakeLeanRepl:
    """Async stand-in for ``server.lean_repl.LeanRepl``.

    ``responses`` is a list of REPL JSON responses returned in order.
    ``raise_with`` (optional) is the LeanReplError to raise on the
    first ``query`` call instead — used for the timeout path.
    """

    def __init__(
        self,
        responses: list[dict[str, Any]] | None = None,
        raise_with: Exception | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self._raise_with = raise_with
        self.commands: list[dict[str, Any]] = []
        self.closed = False

    async def query(self, command: dict[str, Any]) -> dict[str, Any]:
        self.commands.append(command)
        if self._raise_with is not None:
            raise self._raise_with
        return self._responses.pop(0)

    async def close(self) -> None:
        self.closed = True


class _FakeCorpusInfo:
    version = 1


def _attach_fake_resources(lean_repl: Any = None, *, enable_lean: bool = True) -> Any:
    cfg = Config(
        result_byte_cap=256 * 1024,
        enable_lean=enable_lean,
        # Paths are only consulted if spawn_from_config fires; the
        # respawn-on-timeout test monkeypatches that path so paths can
        # stay None here.
        lake_path=None,
        lean_repl_dir=None,
    )

    class _FakeResources:
        pass

    fake = _FakeResources()
    fake.config = cfg
    fake.corpus_info = _FakeCorpusInfo()
    fake.lean_repl = lean_repl
    set_resources(fake)
    return fake


@pytest.fixture
def fake_resources_with_repl():
    repl = _FakeLeanRepl()
    fake = _attach_fake_resources(repl)
    try:
        yield fake, repl
    finally:
        reset_resources_for_tests()


@pytest.fixture
def fake_resources_disabled():
    fake = _attach_fake_resources(lean_repl=None, enable_lean=False)
    try:
        yield fake
    finally:
        reset_resources_for_tests()


# ===========================================================================
# Tier 1a — Tool registration + schema cross-check (always-run)
# ===========================================================================


class TestToolRegistration:
    def test_lean_verify_in_all_tools(self):
        from server.tools import ALL_TOOLS

        assert LEAN_VERIFY in ALL_TOOLS, "LEAN_VERIFY must appear in ALL_TOOLS"
        assert ALL_TOOLS[-1] is LEAN_VERIFY, (
            "LEAN_VERIFY must be appended at the END of ALL_TOOLS "
            "(insertion mid-tuple drifts every prior tool's hash)"
        )
        assert LEAN_VERIFY.name == "lean_verify"
        # Frozen-description discipline — no f-strings, no dynamic content.
        # If this assertion fires, somebody computed the description at
        # import time and broke BP1 cache stability.
        assert "{" not in LEAN_VERIFY.description, (
            "LEAN_VERIFY.description must be a fully-literal string "
            "(no f-string interpolation) to preserve BP1 byte-stability"
        )

    def test_schema_version_matches_tool_schema_version(self):
        """m3 bumps TOOL_SCHEMA_VERSION 11 -> 12; the new schema file
        must echo the same integer (cross-checked by
        test_snippet_contract.py::TestSchemaVersionPin)."""
        assert TOOL_SCHEMA_VERSION == 12

        schema_path = (
            Path(__file__).parent.parent
            / "server"
            / "schemas"
            / "lean_verify_result.json"
        )
        with open(schema_path, encoding="utf-8") as f:
            schema = json.load(f)
        assert schema["version"] == TOOL_SCHEMA_VERSION


# ===========================================================================
# Tier 1b — Command construction (always-run, pure functions)
# ===========================================================================


class TestBuildCommand:
    def test_full_mode_passes_snippet_verbatim(self):
        cmd = _build_command("theorem t : 1+1=2 := rfl", [], "full")
        assert cmd == "theorem t : 1+1=2 := rfl"

    def test_full_mode_prepends_imports(self):
        cmd = _build_command(
            "example : True := trivial",
            ["Mathlib.Tactic", "Mathlib.Data.Nat"],
            "full",
        )
        assert cmd == (
            "import Mathlib.Tactic\nimport Mathlib.Data.Nat\n"
            "example : True := trivial"
        )

    def test_syntax_only_wraps_bare_term_in_check(self):
        """A bare term (NOT a declaration) is wrapped in #check(...) so
        elaboration runs but kernel decide-instances is skipped."""
        cmd = _build_command("(1 + 1 : Nat)", [], "syntax_only")
        assert cmd == "#check ((1 + 1 : Nat))"

    def test_syntax_only_wraps_theorem_in_maxheartbeats(self):
        """A theorem/def declaration cannot be #check-wrapped — fall
        back to set_option maxHeartbeats 5000 in <decl>."""
        snippet = "theorem t : 1 = 1 := rfl"
        cmd = _build_command(snippet, [], "syntax_only")
        assert cmd.startswith("set_option maxHeartbeats 5000 in ")
        assert cmd.endswith(snippet)

    def test_syntax_only_wraps_def_in_maxheartbeats(self):
        cmd = _build_command("def x : Nat := 7", [], "syntax_only")
        assert cmd.startswith("set_option maxHeartbeats 5000 in ")


# ===========================================================================
# Tier 1c — Response normalization (always-run, pure function)
# ===========================================================================


class TestNormalizeResponse:
    def test_clean_compile_status_ok(self):
        out = _normalize_response({"env": 0}, "full")
        assert out["status"] == "ok"
        assert out["compilation_success"] is True
        assert out["messages"] == []
        assert out["sorry_goals"] == []
        assert out["goals_remaining"] == []
        assert out["proof_state"] is None
        assert out["lean_status"] == "available"
        assert out["mode"] == "full"

    def test_type_error_status_error(self):
        """AC: a snippet with a type error returns status=error with the
        message body + severity + source position."""
        repl_resp = {
            "env": 0,
            "messages": [
                {
                    "severity": "error",
                    "pos": {"line": 1, "column": 4},
                    "endPos": {"line": 1, "column": 10},
                    "data": "type mismatch: 1+1=3",
                }
            ],
        }
        out = _normalize_response(repl_resp, "full")
        assert out["status"] == "error"
        assert out["compilation_success"] is False
        assert out["messages"] == [
            {
                "severity": "error",
                "position": {"line": 1, "column": 4},
                "text": "type mismatch: 1+1=3",
            }
        ]

    def test_sorry_populates_goals(self):
        """AC: an unresolved sorry returns status=sorry,
        sorry_goals + goals_remaining populated, proof_state = first
        goal."""
        repl_resp = {
            "env": 0,
            "sorries": [
                {
                    "pos": {"line": 1, "column": 30},
                    "goal": "n : Nat\n⊢ n = n",
                    "proofState": 0,
                }
            ],
        }
        out = _normalize_response(repl_resp, "full")
        assert out["status"] == "sorry"
        assert out["compilation_success"] is False
        assert out["goals_remaining"] == ["n : Nat\n⊢ n = n"]
        assert out["proof_state"] == "n : Nat\n⊢ n = n"
        assert out["sorry_goals"] == [
            {
                "goal": "n : Nat\n⊢ n = n",
                "position": {"line": 1, "column": 30},
            }
        ]

    def test_syntax_only_clean_returns_compilation_success_null(self):
        """syntax_only mode short-circuits before kernel verification,
        so a clean elaboration carries compilation_success=null (NOT
        True) — kernel acceptance is not defined."""
        out = _normalize_response({"env": 0}, "syntax_only")
        assert out["status"] == "ok"
        assert out["compilation_success"] is None
        assert out["mode"] == "syntax_only"

    def test_normalize_missing_pos_defaults_to_zero(self):
        """FM-4: REPL omits/garbles pos — schema's
        ``position: {line: int, column: int}`` is non-nullable, so
        normalization defaults to {0, 0}."""
        repl_resp = {
            "messages": [{"severity": "error", "data": "bad"}],
            "sorries": [{"goal": "g"}],
        }
        out = _normalize_response(repl_resp, "full")
        assert out["messages"][0]["position"] == {"line": 0, "column": 0}
        assert out["sorry_goals"][0]["position"] == {"line": 0, "column": 0}

    def test_normalize_position_helper_handles_garbage(self):
        assert _normalize_position(None) == {"line": 0, "column": 0}
        assert _normalize_position({"line": "x"}) == {"line": 0, "column": 0}
        assert _normalize_position({"line": 3, "column": 7}) == {
            "line": 3,
            "column": 7,
        }

    def test_error_beats_sorry_in_status_precedence(self):
        """If a snippet has both an error and a sorry, status=error
        (the agent must see the error first)."""
        repl_resp = {
            "messages": [
                {"severity": "error", "pos": {"line": 0, "column": 0}, "data": "x"}
            ],
            "sorries": [{"pos": {"line": 0, "column": 0}, "goal": "g"}],
        }
        out = _normalize_response(repl_resp, "full")
        assert out["status"] == "error"


# ===========================================================================
# Tier 1d — Handler (always-run, fake REPL)
# ===========================================================================


class TestHandlerHappyPaths:
    def test_full_mode_clean_theorem(self, fake_resources_with_repl):
        _fake, repl = fake_resources_with_repl
        repl._responses.append({"env": 0})
        result = _run(
            handle_lean_verify(snippet="theorem t : 1+1=2 := rfl", imports=[])
        )
        assert result["status"] == "ok"
        assert result["compilation_success"] is True
        assert result["lean_status"] == "available"
        assert result["mode"] == "full"
        assert result["corpus_version"] == 1
        # Command sent to REPL is the bare snippet.
        assert repl.commands == [{"cmd": "theorem t : 1+1=2 := rfl"}]

    def test_full_mode_type_error(self, fake_resources_with_repl):
        _fake, repl = fake_resources_with_repl
        repl._responses.append(
            {
                "env": 0,
                "messages": [
                    {
                        "severity": "error",
                        "pos": {"line": 1, "column": 4},
                        "data": "type mismatch",
                    }
                ],
            }
        )
        result = _run(
            handle_lean_verify(snippet="theorem t : 1+1=3 := rfl", imports=[])
        )
        assert result["status"] == "error"
        assert result["compilation_success"] is False
        assert result["messages"][0]["severity"] == "error"
        assert result["messages"][0]["position"] == {"line": 1, "column": 4}

    def test_sorry_path(self, fake_resources_with_repl):
        _fake, repl = fake_resources_with_repl
        repl._responses.append(
            {
                "env": 0,
                "sorries": [
                    {
                        "pos": {"line": 1, "column": 30},
                        "goal": "⊢ n = n",
                    }
                ],
            }
        )
        result = _run(
            handle_lean_verify(snippet="theorem t (n : Nat) : n=n := by sorry")
        )
        assert result["status"] == "sorry"
        assert result["sorry_goals"][0]["goal"] == "⊢ n = n"
        assert result["goals_remaining"] == ["⊢ n = n"]
        assert result["proof_state"] == "⊢ n = n"

    def test_syntax_only_mode_wraps_in_check(self, fake_resources_with_repl):
        _fake, repl = fake_resources_with_repl
        repl._responses.append({"env": 0})
        result = _run(
            handle_lean_verify(snippet="(1 + 1 : Nat)", mode="syntax_only")
        )
        assert result["mode"] == "syntax_only"
        assert result["compilation_success"] is None
        assert repl.commands == [{"cmd": "#check ((1 + 1 : Nat))"}]

    def test_syntax_only_theorem_uses_max_heartbeats(
        self, fake_resources_with_repl
    ):
        _fake, repl = fake_resources_with_repl
        repl._responses.append({"env": 0})
        _run(
            handle_lean_verify(
                snippet="theorem t : 1=1 := rfl", mode="syntax_only"
            )
        )
        sent = repl.commands[0]["cmd"]
        assert sent.startswith("set_option maxHeartbeats 5000 in ")


class TestHandlerDisabled:
    def test_returns_unavailable_when_lean_repl_is_none(
        self, fake_resources_disabled
    ):
        """FM-7: enable_lean=False -> tool is still registered (BP1
        stability) but the REPL is None. Handler MUST return a
        graceful envelope, not 5xx."""
        result = _run(handle_lean_verify(snippet="theorem t : True := trivial"))
        assert result["status"] == "unavailable"
        assert result["lean_status"] == "disabled"
        assert result["compilation_success"] is None
        assert result["messages"] == []
        assert result["sorry_goals"] == []


class TestHandlerTimeout:
    def test_timeout_kills_and_respawns_repl(self, monkeypatch):
        """FM-2: a per-query wall-clock timeout raises
        LeanReplTimeoutError; the handler must close the wedged REPL
        and spawn a fresh one before returning. Otherwise the next
        call reads stale stdout."""
        from server.lean_repl import LeanReplTimeoutError

        timed_out = _FakeLeanRepl(
            raise_with=LeanReplTimeoutError(
                "Lean REPL query exceeded the 30s timeout."
            )
        )
        fake = _attach_fake_resources(timed_out)

        respawned = _FakeLeanRepl()

        async def _fake_spawn_from_config(config):
            return respawned

        # Patch the spawn_from_config classmethod the handler calls.
        import server.lean_repl as lean_mod

        monkeypatch.setattr(
            lean_mod.LeanRepl, "spawn_from_config", _fake_spawn_from_config
        )

        try:
            result = _run(
                handle_lean_verify(snippet="theorem t : True := trivial")
            )
            assert result["status"] == "timeout"
            assert result["lean_status"] == "timeout"
            assert result["compilation_success"] is False
            # The wedged REPL was closed.
            assert timed_out.closed is True
            # A fresh REPL replaced it on Resources.lean_repl so the
            # next call doesn't hit the disabled path.
            assert fake.lean_repl is respawned
        finally:
            reset_resources_for_tests()


class TestHandlerInputValidation:
    def test_oversize_import_line_rejected(self, fake_resources_with_repl):
        long = "x" * (MAX_IMPORT_LINE_LEN + 1)
        with pytest.raises(ValueError, match="import line too long"):
            _run(handle_lean_verify(snippet="theorem t : True := trivial",
                                    imports=[long]))


# ===========================================================================
# Tier 2 — LeanRepl.spawn RLIMIT_AS guard (POSIX/Windows split)
# ===========================================================================


class TestSpawnRlimitGuard:
    """The m3 acceptance criterion: RLIMIT_AS via preexec_fn lands on
    POSIX; Windows silently no-ops (preexec_fn is rejected by
    asyncio.create_subprocess_exec and would crash every
    enable_lean=true startup).

    Both branches are testable without a real Lean toolchain: we
    monkeypatch ``asyncio.create_subprocess_exec`` to capture the
    spawn kwargs, then assert preexec_fn presence/absence by platform.
    """

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="POSIX-only branch: setrlimit/preexec_fn required",
    )
    def test_posix_attaches_preexec_fn(self, tmp_path, monkeypatch):
        from server import lean_repl as lean_mod

        fake_lake = tmp_path / "lake"
        fake_lake.write_text("", encoding="utf-8")
        fake_dir = tmp_path / "repl"
        fake_dir.mkdir()

        captured: dict[str, Any] = {}

        class _FakeProcess:
            pid = 9999
            returncode = None

        async def _capturing_exec(*args, **kwargs):
            captured.update(kwargs)
            return _FakeProcess()

        monkeypatch.setattr(
            lean_mod.asyncio, "create_subprocess_exec", _capturing_exec
        )

        _run(
            lean_mod.LeanRepl.spawn(
                lake_path=fake_lake,
                repl_dir=fake_dir,
                rlimit_as_bytes=4 * 1024 * 1024 * 1024,
            )
        )
        assert "preexec_fn" in captured, (
            "POSIX path must attach preexec_fn for RLIMIT_AS"
        )
        preexec_fn = captured["preexec_fn"]
        assert callable(preexec_fn)
        # m3 critique F1 (companion to the integration test): assert the
        # cap INTEGER actually reaches the setrlimit closure — not just
        # that preexec_fn is callable. Without this, a future refactor
        # that builds the preexec_fn but passes the wrong value (e.g.
        # always 0, or a stale closure variable) would still pass the
        # callable-check above.
        import inspect

        closure_vars = inspect.getclosurevars(preexec_fn)
        assert closure_vars.nonlocals.get("cap") == 4 * 1024 * 1024 * 1024, (
            "preexec_fn closure must capture the requested cap "
            f"(got cap={closure_vars.nonlocals.get('cap')!r})"
        )

    def test_no_rlimit_means_no_preexec_fn(self, tmp_path, monkeypatch):
        """rlimit_as_bytes=0/None disables the cap on every platform."""
        from server import lean_repl as lean_mod

        fake_lake = tmp_path / "lake"
        fake_lake.write_text("", encoding="utf-8")
        fake_dir = tmp_path / "repl"
        fake_dir.mkdir()

        captured: dict[str, Any] = {}

        class _FakeProcess:
            pid = 9999
            returncode = None

        async def _capturing_exec(*args, **kwargs):
            captured.update(kwargs)
            return _FakeProcess()

        monkeypatch.setattr(
            lean_mod.asyncio, "create_subprocess_exec", _capturing_exec
        )

        _run(
            lean_mod.LeanRepl.spawn(
                lake_path=fake_lake, repl_dir=fake_dir, rlimit_as_bytes=0
            )
        )
        assert "preexec_fn" not in captured

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="Windows-only branch: preexec_fn must NOT be set",
    )
    def test_windows_skips_preexec_fn_and_warns(
        self, tmp_path, monkeypatch, caplog
    ):
        """Windows must silently skip the cap (the platform has no
        RLIMIT_AS and would crash on preexec_fn). The handler logs a
        WARN so the operator sees the unprotected path explicitly."""
        from server import lean_repl as lean_mod

        fake_lake = tmp_path / "lake"
        fake_lake.write_text("", encoding="utf-8")
        fake_dir = tmp_path / "repl"
        fake_dir.mkdir()

        captured: dict[str, Any] = {}

        class _FakeProcess:
            pid = 9999
            returncode = None

        async def _capturing_exec(*args, **kwargs):
            captured.update(kwargs)
            return _FakeProcess()

        monkeypatch.setattr(
            lean_mod.asyncio, "create_subprocess_exec", _capturing_exec
        )

        with caplog.at_level("WARNING"):
            _run(
                lean_mod.LeanRepl.spawn(
                    lake_path=fake_lake,
                    repl_dir=fake_dir,
                    rlimit_as_bytes=4 * 1024 * 1024 * 1024,
                )
            )
        # preexec_fn must NOT be set on Windows.
        assert "preexec_fn" not in captured
        # ... AND a WARNING must explain why.
        assert any(
            "RLIMIT_AS" in rec.getMessage() and "Windows" in rec.getMessage()
            for rec in caplog.records
        )


# ===========================================================================
# Tier 1e — Phase 4 rectification regression guards (always-run)
# ===========================================================================


class TestLeanVerifyResultSchema:
    """m3 critique F2 + F6: every handler envelope (success, disabled,
    timeout, generic-error) must validate against the frozen
    ``lean_verify_result.json`` schema. Without this, the schema is a
    comment, not a contract."""

    @pytest.fixture
    def schema_validator(self):
        from jsonschema import Draft7Validator

        schema_path = (
            Path(__file__).parent.parent
            / "server"
            / "schemas"
            / "lean_verify_result.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        return Draft7Validator(schema)

    def test_clean_compile_envelope_conforms(
        self, fake_resources_with_repl, schema_validator
    ):
        _fake, repl = fake_resources_with_repl
        repl._responses.append({"env": 0})
        out = _run(
            handle_lean_verify(snippet="theorem t : 1+1=2 := rfl")
        )
        schema_validator.validate(out)

    def test_type_error_envelope_conforms(
        self, fake_resources_with_repl, schema_validator
    ):
        _fake, repl = fake_resources_with_repl
        repl._responses.append(
            {
                "env": 0,
                "messages": [
                    {
                        "severity": "error",
                        "pos": {"line": 1, "column": 4},
                        "data": "type mismatch",
                    }
                ],
            }
        )
        out = _run(handle_lean_verify(snippet="theorem t : 1+1=3 := rfl"))
        schema_validator.validate(out)

    def test_sorry_envelope_conforms(
        self, fake_resources_with_repl, schema_validator
    ):
        _fake, repl = fake_resources_with_repl
        repl._responses.append(
            {
                "env": 0,
                "sorries": [
                    {"pos": {"line": 1, "column": 30}, "goal": "⊢ n = n"}
                ],
            }
        )
        out = _run(
            handle_lean_verify(snippet="theorem t (n : Nat) : n=n := by sorry")
        )
        schema_validator.validate(out)

    def test_syntax_only_envelope_conforms(
        self, fake_resources_with_repl, schema_validator
    ):
        _fake, repl = fake_resources_with_repl
        repl._responses.append({"env": 0})
        out = _run(
            handle_lean_verify(snippet="(1 + 1 : Nat)", mode="syntax_only")
        )
        schema_validator.validate(out)

    def test_disabled_envelope_conforms(
        self, fake_resources_disabled, schema_validator
    ):
        """m3 critique F6: the disabled-path envelope (the agent's
        most-fragile contract surface) must conform to the same
        schema as the success envelope."""
        out = _run(handle_lean_verify(snippet="theorem t : True := trivial"))
        schema_validator.validate(out)

    def test_timeout_envelope_conforms(self, monkeypatch, schema_validator):
        """m3 critique F6: the timeout envelope must conform."""
        from server.lean_repl import LeanReplTimeoutError

        timed_out = _FakeLeanRepl(
            raise_with=LeanReplTimeoutError(
                "Lean REPL query exceeded the 30s timeout."
            )
        )
        _attach_fake_resources(timed_out)

        async def _fake_spawn(config):
            return _FakeLeanRepl()

        import server.lean_repl as lean_mod

        monkeypatch.setattr(
            lean_mod.LeanRepl, "spawn_from_config", _fake_spawn
        )
        try:
            out = _run(handle_lean_verify(snippet="theorem t : True := trivial"))
            schema_validator.validate(out)
        finally:
            reset_resources_for_tests()

    def test_generic_error_envelope_conforms(
        self, fake_resources_with_repl, schema_validator
    ):
        """m3 critique F6: the non-timeout LeanReplError envelope
        (process exited, malformed response) must conform."""
        from server.lean_repl import LeanReplError

        _fake, repl = fake_resources_with_repl
        repl._raise_with = LeanReplError(
            "Lean REPL closed stdout before returning a response"
        )
        out = _run(handle_lean_verify(snippet="theorem t : True := trivial"))
        schema_validator.validate(out)


class TestTimeoutDiscriminatorIsTypeNotSubstring:
    """m3 critique F3: the handler must route to kill+respawn only on
    the TypedTimeoutError subclass — never on a substring match against
    the error message."""

    def test_non_timeout_error_with_word_timeout_in_message(
        self, fake_resources_with_repl
    ):
        """A non-timeout LeanReplError whose message happens to contain
        the word 'timeout' must NOT trigger the respawn path — it goes
        to the generic-error envelope. Without the F3 fix (substring
        match), this test fails: the handler erroneously kills + tries
        to respawn the REPL."""
        from server.lean_repl import LeanReplError

        _fake, repl = fake_resources_with_repl
        # The substring "timeout" appears, but the exception is NOT a
        # LeanReplTimeoutError — it's a generic LeanReplError. Without
        # F3, the handler would substring-match on "timeout" and kill
        # the wedged REPL needlessly.
        repl._raise_with = LeanReplError(
            "Lean REPL returned a non-JSON response after the 30s "
            "timeout window expired upstream"
        )
        result = _run(handle_lean_verify(snippet="theorem t : True := trivial"))
        assert result["status"] == "error", result
        # status="error" + lean_status="available" is the generic-error
        # branch; "timeout"/"timeout" would be the respawn branch.
        assert result["lean_status"] == "available"
        # CRITICAL — the REPL was NOT closed (the handler must not kill
        # a still-functional REPL just because its error message
        # happened to contain the string "timeout").
        assert repl.closed is False


class TestRespawnFailureNarrowExcept:
    """m3 critique F4: respawn-failure path must NOT swallow
    CancelledError or other non-IO exceptions."""

    def test_cancelled_error_during_respawn_propagates(self, monkeypatch):
        """asyncio.CancelledError must propagate, never be swallowed —
        cancellation is the task-cancellation primitive; swallowing it
        breaks every higher-level cancellation contract."""
        from server.lean_repl import LeanReplTimeoutError

        timed_out = _FakeLeanRepl(
            raise_with=LeanReplTimeoutError("Lean REPL query exceeded timeout.")
        )
        _attach_fake_resources(timed_out)

        async def _cancelled_respawn(config):
            raise asyncio.CancelledError("cancelled during respawn")

        import server.lean_repl as lean_mod

        monkeypatch.setattr(
            lean_mod.LeanRepl, "spawn_from_config", _cancelled_respawn
        )
        try:
            with pytest.raises(asyncio.CancelledError):
                _run(
                    handle_lean_verify(
                        snippet="theorem t : True := trivial"
                    )
                )
        finally:
            reset_resources_for_tests()


class TestPositionClampsNegatives:
    """m3 critique F5: schema declares ``position.line/column`` with
    ``minimum: 0``; normalize must clamp negatives."""

    def test_negative_position_clamps_to_zero(self):
        out = _normalize_position({"line": -1, "column": -2})
        assert out == {"line": 0, "column": 0}

    def test_negative_in_message_clamps_via_normalize_response(self):
        out = _normalize_response(
            {
                "messages": [
                    {
                        "severity": "error",
                        "pos": {"line": -5, "column": 0},
                        "data": "x",
                    }
                ]
            },
            "full",
        )
        assert out["messages"][0]["position"] == {"line": 0, "column": 0}


class TestNormalizeSeverityClamp:
    """m3 critique F2 (handler half): unknown REPL ``severity`` values
    are clamped to the schema enum. Default = "error" (safer than
    silently downgrading to "info")."""

    def test_unknown_severity_clamped_to_error(self):
        out = _normalize_response(
            {
                "messages": [
                    {
                        "severity": "trace",  # Lean internal category
                        "pos": {"line": 0, "column": 0},
                        "data": "noise",
                    }
                ]
            },
            "full",
        )
        assert out["messages"][0]["severity"] == "error"
        # ... AND status reflects the (clamped-to-error) severity.
        assert out["status"] == "error"

    def test_non_string_data_coerced_to_string(self):
        """A future REPL build emitting structured proof-state objects
        for ``data`` / ``goal`` must not crash the schema — coerce
        to ``str``."""
        out = _normalize_response(
            {
                "messages": [
                    {
                        "severity": "info",
                        "pos": {"line": 0, "column": 0},
                        "data": {"structured": "object", "n": 7},
                    }
                ],
                "sorries": [{"pos": {"line": 0, "column": 0}, "goal": 42}],
            },
            "full",
        )
        assert isinstance(out["messages"][0]["text"], str)
        assert "structured" in out["messages"][0]["text"]
        assert isinstance(out["sorry_goals"][0]["goal"], str)
        assert out["sorry_goals"][0]["goal"] == "42"


class TestImportsListLengthDefenseInDepth:
    """m3 critique F8: the per-line bound is the existing
    defense-in-depth; the LIST length bound must match (the docstring
    explicitly motivates the loop with 'catches a non-FastMCP caller
    path' — and direct callers can bypass Pydantic's max_length)."""

    def test_oversize_imports_list_rejected(self, fake_resources_with_repl):
        from server.handlers.lean_verify import MAX_IMPORTS

        with pytest.raises(ValueError, match="imports list too long"):
            _run(
                handle_lean_verify(
                    snippet="theorem t : True := trivial",
                    imports=["X"] * (MAX_IMPORTS + 1),
                )
            )


# ===========================================================================
# Tier 3 — real Lean REPL integration (requires the toolchain)
# ===========================================================================


@_lean_skip
@pytest.mark.requires_lean_repl
class TestRealLeanRepl:
    """End-to-end against a real Lean 4 REPL. Each test spawns its own
    LeanRepl, attaches it to Resources, and runs handle_lean_verify."""

    @staticmethod
    async def _setup_real_repl():
        from server.lean_repl import LeanRepl

        repl = await LeanRepl.spawn(
            lake_path=_LAKE_PATH,
            repl_dir=_REPL_DIR,
            rlimit_as_bytes=4 * 1024 * 1024 * 1024,
        )
        _attach_fake_resources(repl)
        return repl

    @staticmethod
    async def _teardown(repl):
        try:
            await repl.close()
        finally:
            reset_resources_for_tests()

    def test_real_clean_theorem(self):
        async def _go():
            repl = await self._setup_real_repl()
            try:
                return await handle_lean_verify(
                    snippet="theorem m3_ok : 1 + 1 = 2 := rfl"
                )
            finally:
                await self._teardown(repl)

        result = _run(_go())
        assert result["status"] == "ok", result
        assert result["compilation_success"] is True

    def test_real_type_error_carries_position(self):
        async def _go():
            repl = await self._setup_real_repl()
            try:
                return await handle_lean_verify(
                    snippet="theorem m3_bad : 1 + 1 = 3 := rfl"
                )
            finally:
                await self._teardown(repl)

        result = _run(_go())
        assert result["status"] == "error"
        assert any(
            m["severity"] == "error" for m in result["messages"]
        )
        # Every error message carries a position (the contract).
        for m in result["messages"]:
            if m["severity"] == "error":
                assert "line" in m["position"] and "column" in m["position"]

    def test_real_sorry_returns_goal(self):
        async def _go():
            repl = await self._setup_real_repl()
            try:
                return await handle_lean_verify(
                    snippet="theorem m3_sorry (n : Nat) : n = n := by sorry"
                )
            finally:
                await self._teardown(repl)

        result = _run(_go())
        assert result["status"] == "sorry"
        assert result["sorry_goals"], result
        assert result["proof_state"]

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="RLIMIT_AS is POSIX-only; Windows path tested via the unit "
        "test that monkeypatches create_subprocess_exec",
    )
    def test_real_rlimit_as_bounds_subprocess(self):
        """The m3 AC: RLIMIT_AS bounds the subprocess. m3 critique F1
        rewrite — the prior version (``List.range 1000`` at 4 GiB cap)
        asserted only ``status in {ok, error, sorry}`` and would pass
        even if ``preexec_fn`` were never attached.

        This version spawns a fresh REPL at a deliberately tight cap
        (32 MiB — below Lean's baseline RSS) and asserts that a trivial
        elaboration FAILS observably (subprocess crash, EOF, or
        timeout) — i.e. the cap is actually in force. If the parent
        survives + the call returns a usable envelope OR raises
        LeanReplError, RLIMIT_AS proved it can constrain the child;
        an ``ok`` status would mean the cap silently failed to apply.
        """
        from server.lean_repl import LeanRepl, LeanReplError

        async def _go():
            # 32 MiB — well below Lean's baseline; the kernel + oleans
            # can't even bootstrap. Spawn must still succeed (fork+exec
            # returns before Lean allocates), but the first query MUST
            # fail observably.
            tight_cap = 32 * 1024 * 1024
            repl = await LeanRepl.spawn(
                lake_path=_LAKE_PATH,
                repl_dir=_REPL_DIR,
                rlimit_as_bytes=tight_cap,
            )
            _attach_fake_resources(repl)
            try:
                try:
                    out = await handle_lean_verify(
                        snippet="theorem cap_ok : True := trivial"
                    )
                except LeanReplError:
                    # Subprocess crashed or stdout closed under the cap
                    # — exactly the bounded-failure mode RLIMIT_AS is
                    # meant to produce.
                    return "raised_lean_repl_error"
                return out
            finally:
                try:
                    await repl.close()
                finally:
                    reset_resources_for_tests()

        result = _run(_go())
        if isinstance(result, str):
            assert result == "raised_lean_repl_error"
            return
        # The parent process is alive — that's necessary. AND the
        # status must NOT be "ok": a clean compile under a 32 MiB cap
        # would mean the cap is silently a no-op (i.e. the broken
        # state F1 catches). Acceptable outcomes are "error"
        # (subprocess crashed during query) or "timeout" (elaboration
        # never returned because the kernel couldn't allocate); the
        # Lean REPL's exact failure mode under memory pressure varies
        # but never produces "ok".
        assert result["status"] != "ok", (
            f"RLIMIT_AS cap of 32 MiB did not constrain the subprocess "
            f"— Lean compiled cleanly anyway, meaning the cap silently "
            f"failed to apply. result={result!r}"
        )
        assert result["status"] in {"error", "timeout", "unavailable"}
