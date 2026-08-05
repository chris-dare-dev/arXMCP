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
    AXIOM_ALLOWLIST,
    MAX_IMPORT_LINE_LEN,
    _audit_from_messages,
    _build_command,
    _declaration_names,
    _decode_token,
    _encode_token,
    _normalize_position,
    _normalize_response,
    handle_lean_verify,
)
from server.lean_repl import LeanReplError, LeanReplTimeoutError
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
        generation: str = "fakegen",
    ) -> None:
        self._responses = list(responses or [])
        self._raise_with = raise_with
        self.commands: list[dict[str, Any]] = []
        self.closed = False
        # lean-verify-continuation-m1: the handler namespaces continuation
        # tokens with LeanRepl.generation. A distinct value per instance
        # lets the respawn tests exercise the expired-token path.
        self.generation = generation

    def _next_response(self) -> dict[str, Any]:
        """Pop the next queued response, or ``{}`` once the queue is empty.

        A full-mode call now costs TWO round-trips: the snippet, then a
        ``#print axioms`` audit over the declarations it introduced
        (lean-verify-axiom-audit). Tests that queue only the primary response
        are asserting about the primary axes, so the fake models "Lean told us
        nothing about the axioms" rather than raising ``IndexError``.

        ``{}`` is deliberately the *honest* exhausted-queue reply, not a
        convenient one: an audit that learns nothing scores ``outcome
        ="unknown"``. A fake that manufactured a clean ``#print axioms`` reply
        would make every one of those tests silently assert a passing axiom
        verdict that nothing measured — exactly the defect this milestone
        exists to remove.
        """
        return self._responses.pop(0) if self._responses else {}

    async def query(self, command: dict[str, Any]) -> dict[str, Any]:
        self.commands.append(command)
        if self._raise_with is not None:
            raise self._raise_with
        return self._next_response()

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
        """The lean_verify_result.json ``version`` integer must echo the
        global TOOL_SCHEMA_VERSION. History: 11->12 (verification-
        feedback-m3), 12->13 (textbook-ingest-m3), 13->14 (textbook-
        ingest-m9 / e4 — SEARCH_PAPERS source_kind filter description
        edit drifted the global version; lean_verify result shape
        unchanged), 14->15 (textbook-ingest-m9 / e4 rectification —
        critique-F3 filters-parameter inputSchema description fix
        drifted the global version; lean_verify result shape again
        unchanged), 15->16 (textbook-ingest-m11 / e5 — get_chunk
        truncated_for_license response flag drifted the global version;
        lean_verify result shape once more unchanged), 16->17
        (paper-metadata-m2 — GET_PAPER ToolMeta description rewritten
        for the hydrated per-notebook metadata store; lean_verify
        result shape yet again unchanged), 17->18 (source-truth-m5 --
        get_chunk grew 5 source-truth response fields; lean_verify result
        shape unchanged), 18->19 (license-serving-removal-m1 -- get_chunk
        DROPPED the truncated_for_license response flag as the 300-char
        license-truncation gate was removed; lean_verify result shape once
        more unchanged)."""
        # 20->21 (agent-platform-m3 / W1): batched schema re-pin
        # (get_chunk batch + arg cleanup, search/find_equation/cite
        # description edits, ToolAnnotations, search-row title/year);
        # lean_verify result shape unchanged, version tracks the global.
        # 21->22 (W2 batched re-pin): the second batched window, applying
        # the two deltas staged after W1 closed. This one DOES change the
        # lean_verify result shape -- the always-emitted axiom_audit
        # record (issues #205 / #281 / #332), whose behaviour had already
        # merged bump-free -- alongside search_papers' cache_match
        # (issue #204). The LEAN_VERIFY description edit landing in the
        # same window is what made it BP1-affecting.
        # 22->23 (verification-contract-m1): honest-vocabulary rename
        # only -- the status enum member "ok" becomes
        # "elaborated_no_errors" (trust-language-policy.md §2). No
        # behaviour change; compilation_success / axiom_audit /
        # continuation_status keep their existing semantics. The
        # LEAN_VERIFY description's two "ok" mentions are edited in
        # lockstep, which is what makes this window BP1-affecting.
        assert TOOL_SCHEMA_VERSION == 23

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
    def test_clean_compile_status_elaborated_no_errors(self):
        out = _normalize_response({"env": 0}, "full", repl_generation="g")
        assert out["status"] == "elaborated_no_errors"
        assert out["compilation_success"] is True
        assert out["messages"] == []
        assert out["sorry_goals"] == []
        assert out["goals_remaining"] == []
        assert out["proof_state"] is None
        assert out["lean_status"] == "available"
        assert out["mode"] == "full"

    def test_sorry_result_still_elaborated_cleanly(self):
        """The elaboration axis is NOT readable from `status` alone.

        Regression guard for verification-contract-m1 critique M5: the token
        `elaborated_no_errors` names policy §4 axis 5 (elaboration) but is
        additionally gated on axis 6 (proof closure). A snippet that
        elaborates without a single error-severity diagnostic still reports
        `status="sorry"` when a sorry remains — so a consumer reading the
        elaboration axis off `status` gets the wrong answer, and must use the
        absence of severity=="error" in `messages` instead.
        """
        out = _normalize_response(
            {
                "env": 0,
                "sorries": [
                    {"goal": "⊢ True", "pos": {"line": 1, "column": 0}},
                ],
            },
            "full",
            repl_generation="g",
        )
        assert out["status"] == "sorry"
        # ...yet nothing failed to elaborate:
        assert [m for m in out["messages"] if m["severity"] == "error"] == []

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
        out = _normalize_response(repl_resp, "full", repl_generation="g")
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
        out = _normalize_response(repl_resp, "full", repl_generation="g")
        assert out["status"] == "sorry"
        assert out["compilation_success"] is False
        assert out["goals_remaining"] == ["n : Nat\n⊢ n = n"]
        assert out["proof_state"] == "n : Nat\n⊢ n = n"
        assert out["sorry_goals"] == [
            {
                "goal": "n : Nat\n⊢ n = n",
                "position": {"line": 1, "column": 30},
                # lean-verify-continuation-m1: proofState surfaced as an
                # opaque token namespaced by the REPL generation ("g").
                "proof_state_id": "g:0",
            }
        ]
        # The first sorry's proof state is also mirrored at top level, and
        # the environment id is surfaced as a continuation token.
        assert out["proof_state_id"] == "g:0"
        assert out["env"] == "g:0"
        assert out["continuation_status"] == "not-applicable"

    def test_syntax_only_clean_returns_compilation_success_null(self):
        """syntax_only mode short-circuits before kernel verification,
        so a clean elaboration carries compilation_success=null (NOT
        True) — kernel acceptance is not defined."""
        out = _normalize_response({"env": 0}, "syntax_only", repl_generation="g")
        assert out["status"] == "elaborated_no_errors"
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
        out = _normalize_response(repl_resp, "full", repl_generation="g")
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
        out = _normalize_response(repl_resp, "full", repl_generation="g")
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
        assert result["status"] == "elaborated_no_errors"
        assert result["compilation_success"] is True
        assert result["lean_status"] == "available"
        assert result["mode"] == "full"
        assert result["corpus_version"] == 1
        # First command sent to the REPL is the bare snippet; the second is
        # the axiom-hygiene audit over the declaration it introduced, run
        # against the env that snippet produced (lean-verify-axiom-audit).
        assert repl.commands == [
            {"cmd": "theorem t : 1+1=2 := rfl"},
            {"cmd": "#print axioms t", "env": 0},
        ]

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


# ===========================================================================
# Tier 1e — Continuation tokens: env reuse + proof stepping
#           (lean-verify-continuation-m1)
# ===========================================================================


def _repl_with(responses, *, generation="fakegen"):
    """Attach fake resources with a fake REPL of the given generation."""
    repl = _FakeLeanRepl(responses=responses, generation=generation)
    _attach_fake_resources(repl)
    return repl


class TestContinuationTokenCodec:
    """Unit tests for the opaque generation-scoped token codec."""

    def test_encode_roundtrips_through_decode(self):
        tok = _encode_token("abc123", 7)
        assert tok == "abc123:7"
        assert _decode_token(tok, "abc123") == ("resumed", 7)

    def test_generation_mismatch_is_expired(self):
        # A token minted by a prior REPL instance must be rejected, never
        # reused against a colliding env id in the respawned process.
        assert _decode_token("oldgen:0", "newgen") == ("expired", None)

    def test_missing_colon_is_malformed(self):
        assert _decode_token("nocolon", "g") == ("malformed", None)

    def test_empty_generation_is_malformed(self):
        assert _decode_token(":5", "g") == ("malformed", None)

    def test_non_integer_index_is_malformed(self):
        assert _decode_token("g:notanint", "g") == ("malformed", None)

    def test_negative_index_is_malformed(self):
        assert _decode_token("g:-1", "g") == ("malformed", None)

    def test_non_string_token_is_malformed(self):
        assert _decode_token(123, "g") == ("malformed", None)
        assert _decode_token(None, "g") == ("malformed", None)


class TestEnvReuse:
    """mode=full/syntax_only env continuation."""

    def teardown_method(self):
        reset_resources_for_tests()

    def test_env_token_forwarded_and_new_token_returned(self):
        repl = _repl_with([{"env": 5}], generation="genA")
        result = _run(
            handle_lean_verify(
                snippet="theorem t : True := trivial", env="genA:0"
            )
        )
        # The decoded raw env id (0) is forwarded to the REPL...
        assert repl.commands[0] == {
            "cmd": "theorem t : True := trivial",
            "env": 0,
        }
        # ...and the axiom audit runs against the env the snippet PRODUCED
        # (5), not the one it continued from (0).
        assert repl.commands[1] == {"cmd": "#print axioms t", "env": 5}
        # ...and the produced env (5) comes back as a generation-scoped token.
        assert result["env"] == "genA:5"
        assert result["continuation_status"] == "resumed"
        assert result["status"] == "elaborated_no_errors"

    def test_no_env_is_not_applicable(self):
        repl = _repl_with([{"env": 0}], generation="genA")
        result = _run(handle_lean_verify(snippet="theorem t : True := trivial"))
        assert repl.commands == [
            {"cmd": "theorem t : True := trivial"},
            {"cmd": "#print axioms t", "env": 0},
        ]
        assert result["continuation_status"] == "not-applicable"
        assert result["env"] == "genA:0"

    def test_expired_env_fails_closed_without_querying(self):
        # Token generation != live REPL generation -> the REPL was respawned
        # since the token was minted. The call must NOT run.
        repl = _repl_with([{"env": 9}], generation="genNEW")
        result = _run(
            handle_lean_verify(
                snippet="theorem t : True := trivial", env="genOLD:0"
            )
        )
        assert repl.commands == []  # never queried
        assert result["status"] == "invalid-input"
        assert result["continuation_status"] == "expired"
        assert result["compilation_success"] is False

    def test_malformed_env_fails_closed_without_querying(self):
        repl = _repl_with([{"env": 9}], generation="genA")
        result = _run(
            handle_lean_verify(
                snippet="theorem t : True := trivial", env="not-a-token"
            )
        )
        assert repl.commands == []
        assert result["status"] == "invalid-input"
        assert result["continuation_status"] == "malformed"

    def test_unknown_id_message_shape_fails_closed(self):
        # THE fail-open regression guard. The REPL's {"message": ...} reply
        # for an unknown env carries NEITHER messages NOR sorries, so the
        # pre-m5 normalizer reported it as a CLEAN COMPILE (status "ok").
        # It must be invalid-input.
        repl = _repl_with(
            [{"message": "Unknown environment."}], generation="genA"
        )
        result = _run(
            handle_lean_verify(
                snippet="theorem t : True := trivial", env="genA:3"
            )
        )
        # It WAS forwarded (the generation matched)...
        assert repl.commands == [
            {"cmd": "theorem t : True := trivial", "env": 3}
        ]
        # ...but the unknown-id reply failed closed.
        assert result["status"] == "invalid-input"
        assert result["continuation_status"] == "unknown-id"
        assert result["compilation_success"] is False

    def test_imports_with_env_fails_closed(self):
        # m5 critique F3: imports cannot apply to a continued env (Lean
        # rejects a mid-session import). Reject up front, don't query.
        repl = _repl_with([{"env": 1}], generation="genA")
        result = _run(
            handle_lean_verify(
                snippet="theorem t : True := trivial",
                env="genA:0",
                imports=["Mathlib"],
            )
        )
        assert repl.commands == []
        assert result["status"] == "invalid-input"
        assert result["continuation_status"] == "malformed"


class TestTacticStep:
    """mode=tactic_step proof stepping."""

    def teardown_method(self):
        reset_resources_for_tests()

    def test_completed_step_is_ok_with_null_compilation_success(self):
        repl = _repl_with(
            [{"proofStatus": "Completed", "proofState": 1, "goals": []}],
            generation="genA",
        )
        result = _run(
            handle_lean_verify(
                snippet="simp", mode="tactic_step", proof_state="genA:0"
            )
        )
        assert repl.commands == [{"tactic": "simp", "proofState": 0}]
        assert result["status"] == "elaborated_no_errors"
        assert result["goals_remaining"] == []
        assert result["proof_state_id"] == "genA:1"
        # A single tactic step is NOT a full-declaration kernel check.
        assert result["compilation_success"] is None
        assert result["env"] is None
        assert result["continuation_status"] == "resumed"

    def test_remaining_goals_is_incomplete(self):
        _repl_with(
            [
                {
                    "proofStatus": "Incomplete",
                    "proofState": 2,
                    "goals": ["⊢ P", "⊢ Q"],
                }
            ],
            generation="genA",
        )
        result = _run(
            handle_lean_verify(
                snippet="constructor",
                mode="tactic_step",
                proof_state="genA:0",
            )
        )
        assert result["status"] == "incomplete"
        assert result["goals_remaining"] == ["⊢ P", "⊢ Q"]
        assert result["proof_state_id"] == "genA:2"
        assert result["proof_state"] == "⊢ P"
        assert result["compilation_success"] is None

    def test_tactic_error_is_error(self):
        _repl_with(
            [
                {
                    "messages": [
                        {
                            "severity": "error",
                            "pos": {"line": 0, "column": 0},
                            "data": "unknown tactic",
                        }
                    ]
                }
            ],
            generation="genA",
        )
        result = _run(
            handle_lean_verify(
                snippet="bogus_tac", mode="tactic_step", proof_state="genA:0"
            )
        )
        assert result["status"] == "error"

    def test_missing_proof_state_fails_closed(self):
        repl = _repl_with([{"proofStatus": "Completed", "goals": []}])
        result = _run(handle_lean_verify(snippet="simp", mode="tactic_step"))
        assert repl.commands == []
        assert result["status"] == "invalid-input"
        assert result["continuation_status"] == "malformed"

    def test_expired_proof_state_fails_closed(self):
        repl = _repl_with(
            [{"proofStatus": "Completed", "goals": []}], generation="genNEW"
        )
        result = _run(
            handle_lean_verify(
                snippet="simp", mode="tactic_step", proof_state="genOLD:0"
            )
        )
        assert repl.commands == []
        assert result["status"] == "invalid-input"
        assert result["continuation_status"] == "expired"

    def test_thrown_lean_error_is_error_not_invalid_input(self):
        # m5 critique F1: a FAILED tactic throws a bare
        # {"message": "Lean error:\n..."} — a real tactic error, NOT a
        # continuation-token problem. status=error, token still "resumed".
        _repl_with(
            [{"message": "Lean error:\nType mismatch\n  42\nhas type Nat"}],
            generation="genA",
        )
        result = _run(
            handle_lean_verify(
                snippet="exact (42 : Nat)",
                mode="tactic_step",
                proof_state="genA:0",
            )
        )
        assert result["status"] == "error"
        assert result["continuation_status"] == "resumed"  # token WAS valid
        assert result["compilation_success"] is False
        assert "Type mismatch" in result["messages"][0]["text"]

    def test_sorry_introducing_tactic_surfaces_frontier(self):
        # m5 critique F2: a `sorry` tactic returns goals:[] + sorries:[...];
        # the sorries frontier + its resumable proofState must surface.
        _repl_with(
            [
                {
                    "proofStatus": "Incomplete: contains sorry",
                    "proofState": 2,
                    "goals": [],
                    "sorries": [{"proofState": 1, "goal": "⊢ True"}],
                }
            ],
            generation="genA",
        )
        result = _run(
            handle_lean_verify(
                snippet="sorry", mode="tactic_step", proof_state="genA:0"
            )
        )
        assert result["status"] == "incomplete"
        assert result["sorry_goals"] == [
            {
                "goal": "⊢ True",
                "position": {"line": 0, "column": 0},
                "proof_state_id": "genA:1",
            }
        ]
        assert result["proof_state"] == "⊢ True"
        # top-level proof_state_id = the post-tactic state (2).
        assert result["proof_state_id"] == "genA:2"

    def test_env_in_tactic_step_fails_closed(self):
        # m5 critique F5: env does not apply to tactic_step; reject it
        # symmetric with proof_state rejection in full mode.
        repl = _repl_with(
            [{"proofStatus": "Completed", "goals": []}], generation="genA"
        )
        result = _run(
            handle_lean_verify(
                snippet="simp",
                mode="tactic_step",
                proof_state="genA:0",
                env="genA:1",
            )
        )
        assert repl.commands == []
        assert result["status"] == "invalid-input"
        assert result["continuation_status"] == "malformed"


class TestModeCrossWiring:
    """proof_state and env are mode-scoped; crossing them fails closed."""

    def teardown_method(self):
        reset_resources_for_tests()

    def test_proof_state_rejected_in_full_mode(self):
        # Even a well-formed, current-generation token is rejected when the
        # mode does not accept it — the modes must not silently cross wires.
        repl = _repl_with([{"env": 0}])
        result = _run(
            handle_lean_verify(
                snippet="theorem t : True := trivial",
                proof_state="fakegen:0",
            )
        )
        assert repl.commands == []
        assert result["status"] == "invalid-input"
        assert result["continuation_status"] == "malformed"


class TestContinuationSchemaConformance:
    """The new envelope shapes conform to lean_verify_result.json v20."""

    def teardown_method(self):
        reset_resources_for_tests()

    @staticmethod
    def _validate(result):
        from jsonschema import Draft7Validator

        schema_path = (
            Path(__file__).parent.parent
            / "server"
            / "schemas"
            / "lean_verify_result.json"
        )
        with open(schema_path, encoding="utf-8") as f:
            Draft7Validator(json.load(f)).validate(result)

    def test_env_reuse_with_sorry_envelope_conforms(self):
        _repl_with(
            [{"env": 5, "sorries": [{"goal": "g", "proofState": 0}]}],
            generation="genA",
        )
        result = _run(
            handle_lean_verify(
                snippet="theorem t : g := by sorry", env="genA:0"
            )
        )
        self._validate(result)

    def test_tactic_step_envelope_conforms(self):
        _repl_with(
            [{"proofStatus": "Completed", "proofState": 1, "goals": []}],
            generation="genA",
        )
        result = _run(
            handle_lean_verify(
                snippet="simp", mode="tactic_step", proof_state="genA:0"
            )
        )
        self._validate(result)

    def test_invalid_input_envelope_conforms(self):
        _repl_with([{"env": 0}], generation="genA")
        result = _run(
            handle_lean_verify(
                snippet="theorem t : True := trivial", env="badtoken"
            )
        )
        self._validate(result)


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
            repl_generation="g",
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
            repl_generation="g",
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
            repl_generation="g",
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
        assert result["status"] == "elaborated_no_errors", result
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

    def test_real_env_reuse_carries_declarations(self):
        """lean-verify-continuation-m1: a def elaborated in one call is
        visible in a later call that continues from the returned env token
        — the import-amortization primitive, on core Lean (no Mathlib)."""

        async def _go():
            repl = await self._setup_real_repl()
            try:
                first = await handle_lean_verify(
                    snippet="def contFoo : Nat := 41"
                )
                second = await handle_lean_verify(
                    snippet="theorem contUse : contFoo + 1 = 42 := rfl",
                    env=first["env"],
                )
                # Control: WITHOUT the env, contFoo is not in scope.
                third = await handle_lean_verify(
                    snippet="theorem contBad : contFoo + 1 = 42 := rfl"
                )
                return first, second, third
            finally:
                await self._teardown(repl)

        first, second, third = _run(_go())
        assert first["status"] == "elaborated_no_errors", first
        assert first["env"] is not None
        assert first["continuation_status"] == "not-applicable"
        # Reusing the env makes contFoo visible -> the theorem checks.
        assert second["status"] == "elaborated_no_errors", second
        assert second["continuation_status"] == "resumed"
        # Without the env, contFoo is out of scope -> not ok.
        assert third["status"] != "elaborated_no_errors", third

    def test_real_tactic_step_closes_sorry(self):
        """A sorry's proof_state_id is advanced to closure by a tactic in a
        follow-up tactic_step call."""

        async def _go():
            repl = await self._setup_real_repl()
            try:
                opened = await handle_lean_verify(
                    snippet="theorem contStep : True := by sorry"
                )
                ps = opened["sorry_goals"][0]["proof_state_id"]
                stepped = await handle_lean_verify(
                    snippet="trivial", mode="tactic_step", proof_state=ps
                )
                return opened, stepped
            finally:
                await self._teardown(repl)

        opened, stepped = _run(_go())
        assert opened["status"] == "sorry", opened
        assert opened["sorry_goals"][0]["proof_state_id"] is not None
        assert stepped["status"] == "elaborated_no_errors", stepped
        assert stepped["goals_remaining"] == []
        # A tactic step is never a full-declaration kernel verdict.
        assert stepped["compilation_success"] is None

    def test_real_expired_generation_fails_closed(self):
        """A token whose generation does not match the live REPL is rejected
        before any query (the cross-respawn guard)."""

        async def _go():
            repl = await self._setup_real_repl()
            try:
                return await handle_lean_verify(
                    snippet="theorem x : True := trivial",
                    env="deadbeefdeadbeef:0",
                )
            finally:
                await self._teardown(repl)

        result = _run(_go())
        assert result["status"] == "invalid-input", result
        assert result["continuation_status"] == "expired"

    def test_real_unknown_env_id_fails_closed(self):
        """A current-generation token pointing at a non-existent env id gets
        the REPL's {"message": "Unknown environment."} reply, which MUST
        fail closed (the fail-open regression guard, end to end)."""

        async def _go():
            repl = await self._setup_real_repl()
            try:
                bogus = f"{repl.generation}:999999"
                return await handle_lean_verify(
                    snippet="theorem x : True := trivial", env=bogus
                )
            finally:
                await self._teardown(repl)

        result = _run(_go())
        assert result["status"] == "invalid-input", result
        assert result["continuation_status"] == "unknown-id"
        assert result["compilation_success"] is False

    def test_real_failed_tactic_is_error_not_invalid_input(self):
        """m5 F1: a real failed tactic (thrown 'Lean error:\\n...') is
        status=error with the token still resumed — NOT mislabeled as a
        bad continuation token."""

        async def _go():
            repl = await self._setup_real_repl()
            try:
                opened = await handle_lean_verify(
                    snippet="theorem t : True := by sorry"
                )
                ps = opened["sorry_goals"][0]["proof_state_id"]
                # 42 : Nat cannot close the goal `⊢ True` (Prop) -> throws.
                return await handle_lean_verify(
                    snippet="exact (42 : Nat)",
                    mode="tactic_step",
                    proof_state=ps,
                )
            finally:
                await self._teardown(repl)

        result = _run(_go())
        assert result["status"] == "error", result
        assert result["continuation_status"] == "resumed", result
        assert result["compilation_success"] is False

    def test_real_sorry_tactic_surfaces_frontier(self):
        """m5 F2: stepping with `sorry` leaves a sorries frontier reachable
        via sorry_goals[*].proof_state_id."""

        async def _go():
            repl = await self._setup_real_repl()
            try:
                opened = await handle_lean_verify(
                    snippet="theorem t : True := by sorry"
                )
                ps = opened["sorry_goals"][0]["proof_state_id"]
                return await handle_lean_verify(
                    snippet="sorry", mode="tactic_step", proof_state=ps
                )
            finally:
                await self._teardown(repl)

        result = _run(_go())
        assert result["status"] == "incomplete", result
        assert result["sorry_goals"], result
        assert result["sorry_goals"][0]["proof_state_id"] is not None

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
        # status must NOT be "elaborated_no_errors": a clean compile
        # under a 32 MiB cap would mean the cap is silently a no-op
        # (i.e. the broken state F1 catches). Acceptable outcomes are
        # "error" (subprocess crashed during query) or "timeout"
        # (elaboration never returned because the kernel couldn't
        # allocate); the Lean REPL's exact failure mode under memory
        # pressure varies but never produces "elaborated_no_errors".
        assert result["status"] != "elaborated_no_errors", (
            f"RLIMIT_AS cap of 32 MiB did not constrain the subprocess "
            f"— Lean compiled cleanly anyway, meaning the cap silently "
            f"failed to apply. result={result!r}"
        )
        assert result["status"] in {"error", "timeout", "unavailable"}


# ===========================================================================
# Tier 1e — verification-feedback-m4 progress notifications
# ===========================================================================


class _FakeMeta:
    """The minimal ``request_context.meta`` chain the m4 handler walks
    via ``_has_progress_token`` (``ctx.request_context.meta.progressToken``).

    ``progressToken`` of ``None`` matches the FastMCP "client did not
    opt in" path; a non-None token mirrors a real client request.
    """

    def __init__(self, progress_token: str | int | None = "test-tok") -> None:
        self.progressToken = progress_token


class _FakeRequestContext:
    def __init__(self, meta: _FakeMeta) -> None:
        self.meta = meta


class _RecordingCtx:
    """Stand-in for FastMCP's ``Context`` that records every
    ``report_progress`` invocation.

    We do NOT use ``MagicMock(spec=Context)`` because the spec walks the
    Context class's full MRO (Pydantic + generic machinery) and is slow
    + brittle. A small recorder is sufficient — the m4 contract is just
    "an async ``report_progress(progress, total, message)`` method that
    captures every call" plus the ``request_context.meta.progressToken``
    introspection chain the handler walks (m4 critique F3 — without the
    chain, ``_has_progress_token`` returns False and the heartbeat task
    is never spawned, so emission tests would vacuously pass).

    ``raise_on_call`` (optional) makes ``report_progress`` raise — used
    for FM-2 (client disconnect mid-emission) to assert the exception
    does NOT propagate to the handler.

    ``progress_token`` (default ``"test-tok"``) controls the spawn gate.
    Pass ``None`` to model the FM-1 "client did not opt in" path —
    ``_has_progress_token`` returns False, no task spawned (m4 critique
    F4 coverage).
    """

    def __init__(
        self,
        raise_on_call: Exception | None = None,
        progress_token: str | int | None = "test-tok",
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._raise = raise_on_call
        self.request_context = _FakeRequestContext(
            _FakeMeta(progress_token=progress_token)
        )

    async def report_progress(
        self,
        progress: float,
        total: float | None = None,
        message: str | None = None,
    ) -> None:
        self.calls.append(
            {"progress": progress, "total": total, "message": message}
        )
        if self._raise is not None:
            raise self._raise


class _SlowFakeLeanRepl(_FakeLeanRepl):
    """``_FakeLeanRepl`` variant whose ``query`` sleeps ``delay_s``
    before returning. Lets the heartbeat task get >=1 tick in before
    ``query`` returns (AC-2 / AC-6) and exercises the FM-7 path when
    ``raise_with`` is set + ``delay_s`` > 0.
    """

    def __init__(
        self,
        responses: list[dict[str, Any]] | None = None,
        raise_with: Exception | None = None,
        delay_s: float = 0.0,
    ) -> None:
        super().__init__(responses=responses, raise_with=raise_with)
        self._delay_s = delay_s

    async def query(self, command: dict[str, Any]) -> dict[str, Any]:
        self.commands.append(command)
        if self._delay_s > 0:
            await asyncio.sleep(self._delay_s)
        if self._raise_with is not None:
            raise self._raise_with
        return self._next_response()


class TestProgressHeartbeat:
    """m4 acceptance criteria.

    AC-2: Given a ``lean_verify`` call that runs longer than the
    heartbeat interval, when it executes, then >= 1
    ``notifications/progress`` message is emitted before the result.

    AC-4: Given ``ctx is None`` (the existing direct-call test sites),
    when the handler runs, then no heartbeat task is spawned and the
    query still works.

    AC-5: Given ``query`` raises ``LeanReplTimeoutError`` or
    ``LeanReplError`` mid-await, when the handler runs, then the
    heartbeat task is cancelled (no leaked emissions after the
    exception) — explicit regression tests for both exception types.

    AC-6: Given ``query`` succeeds, when the handler returns the
    result, then the heartbeat task is cancelled BEFORE the result is
    returned — no post-completion emissions (spec MUST).

    AC-7: Progress ``message`` field contains ONLY duration/elapsed
    text — no ``snippet`` / ``cmd`` substring ever leaks (FM-9).
    """

    @pytest.fixture(autouse=True)
    def _fast_heartbeat(self, monkeypatch):
        """Crank the heartbeat down to 50 ms so tests don't sleep for
        seconds. We still verify the >=1-emission AC-2 with a query
        delay of 200 ms (>= 4 heartbeat intervals)."""
        from server.handlers import lean_verify as lv

        monkeypatch.setattr(lv, "_HEARTBEAT_INTERVAL_S", 0.05)
        # Total stays at 30.0 so the reported progress / total ratio
        # reflects the real units; the cap at 0.95 still holds.

    def test_ac4_no_emission_when_ctx_is_none(self, fake_resources_with_repl):
        """AC-4: no ``ctx`` → no heartbeat task → query runs normally.
        The existing test suite passes this transitively; the explicit
        assertion is that ``handle_lean_verify`` works without a ``ctx``
        kwarg at all."""
        _fake, repl = fake_resources_with_repl
        repl._responses.append({"env": 0})
        result = _run(
            handle_lean_verify(snippet="theorem t : 1+1=2 := rfl", imports=[])
        )
        assert result["status"] == "elaborated_no_errors"

    def test_ac2_emits_progress_before_result_for_slow_call(self):
        """AC-2: a >3-heartbeat-interval REPL call emits >=1 progress
        notification before the result returns."""
        slow_repl = _SlowFakeLeanRepl(responses=[{"env": 0}], delay_s=0.2)
        _attach_fake_resources(slow_repl)
        ctx = _RecordingCtx()
        try:
            result = _run(
                handle_lean_verify(
                    snippet="theorem t : True := trivial",
                    imports=[],
                    mode="full",
                    ctx=ctx,
                )
            )
            assert result["status"] == "elaborated_no_errors"
            assert len(ctx.calls) >= 1, (
                f"expected >=1 progress emission for a 200ms call at a "
                f"50ms heartbeat interval; got {len(ctx.calls)} calls"
            )
            # All emissions carry total=DEFAULT_QUERY_TIMEOUT_S (the
            # source of truth for the REPL wall-clock budget — m4
            # critique F2) and a STRICTLY-monotonic progress value (m4
            # critique F1 / F5 — the spec MUST is "MUST increase", and
            # the prior non-strict `sorted` check would silently pass
            # the plateau-at-0.95 bug).
            from server.lean_repl import DEFAULT_QUERY_TIMEOUT_S

            progresses = [c["progress"] for c in ctx.calls]
            assert all(0.0 < p < 1.0 for p in progresses), (
                f"progress must be in (0, 1) — the asymptotic taper "
                f"never reaches 1; got {progresses}"
            )
            # Strict increase per MCP spec MUST. `[0.95, 0.95, 0.95]`
            # passes the prior `sorted` check but fails this one.
            assert all(
                a < b for a, b in zip(progresses, progresses[1:], strict=False)
            ), (
                f"progress MUST STRICTLY increase per MCP spec "
                f"(monotonicity MUST, 2025-06-18); got {progresses}"
            )
            assert all(
                c["total"] == DEFAULT_QUERY_TIMEOUT_S for c in ctx.calls
            ), (
                f"total MUST track DEFAULT_QUERY_TIMEOUT_S so a future "
                f"timeout bump scales the heartbeat with it (m4 "
                f"critique F2); got totals "
                f"{[c['total'] for c in ctx.calls]}"
            )
        finally:
            reset_resources_for_tests()

    def test_ac7_message_contains_no_snippet_or_cmd_text(self):
        """AC-7 / FM-9: progress messages MUST contain only elapsed-time
        text, never the user-supplied Lean source. A leaked snippet is
        a security regression."""
        secret_snippet = (
            "theorem secret_internal_proof : 1+1=2 := SECRETSAUCE_token_xyz"
        )
        slow_repl = _SlowFakeLeanRepl(responses=[{"env": 0}], delay_s=0.15)
        _attach_fake_resources(slow_repl)
        ctx = _RecordingCtx()
        try:
            _run(
                handle_lean_verify(
                    snippet=secret_snippet,
                    imports=["Mathlib.SECRET_IMPORT"],
                    mode="full",
                    ctx=ctx,
                )
            )
            assert len(ctx.calls) >= 1
            for call in ctx.calls:
                msg = call["message"] or ""
                assert "SECRETSAUCE" not in msg, (
                    f"snippet text leaked into progress message: {msg!r}"
                )
                assert "SECRET_IMPORT" not in msg, (
                    f"imports leaked into progress message: {msg!r}"
                )
                assert "theorem" not in msg, (
                    f"snippet text leaked into progress message: {msg!r}"
                )
                # The message MUST be the elapsed-time format.
                assert "elapsed" in msg.lower(), (
                    f"expected 'elapsed' in progress message; got {msg!r}"
                )
        finally:
            reset_resources_for_tests()

    def test_ac6_no_emission_after_result_returns(self):
        """AC-6 / FM-3: the heartbeat task MUST be cancelled before the
        handler returns. Sleep briefly AFTER the handler returns and
        assert the emission count did not grow — i.e. the cancellation
        actually fired in ``finally``."""
        slow_repl = _SlowFakeLeanRepl(responses=[{"env": 0}], delay_s=0.15)
        _attach_fake_resources(slow_repl)
        ctx = _RecordingCtx()

        async def _go():
            result = await handle_lean_verify(
                snippet="theorem t : True := trivial",
                imports=[],
                mode="full",
                ctx=ctx,
            )
            count_at_return = len(ctx.calls)
            # Sleep WELL past the heartbeat interval; a leaked task would
            # add emissions during this sleep.
            await asyncio.sleep(0.25)
            assert len(ctx.calls) == count_at_return, (
                f"heartbeat task leaked: {count_at_return} emissions at "
                f"return, {len(ctx.calls)} after 250ms sleep"
            )
            return result

        try:
            result = _run(_go())
            assert result["status"] == "elaborated_no_errors"
        finally:
            reset_resources_for_tests()

    def test_ac5a_heartbeat_cancelled_on_lean_repl_timeout(self, monkeypatch):
        """AC-5 / FM-7: ``LeanReplTimeoutError`` mid-await must cancel
        the heartbeat task in ``finally`` — no emissions leak after the
        exception. Also asserts the m3 timeout-kill-respawn path runs
        unchanged (the heartbeat wrapping must NOT regress it)."""
        from server.lean_repl import LeanReplTimeoutError

        slow_timeout_repl = _SlowFakeLeanRepl(
            raise_with=LeanReplTimeoutError("simulated 30s timeout"),
            delay_s=0.15,
        )
        fake = _attach_fake_resources(slow_timeout_repl)

        respawned = _FakeLeanRepl()

        async def _fake_spawn_from_config(config):
            return respawned

        import server.lean_repl as lean_mod

        monkeypatch.setattr(
            lean_mod.LeanRepl, "spawn_from_config", _fake_spawn_from_config
        )

        ctx = _RecordingCtx()

        async def _go():
            result = await handle_lean_verify(
                snippet="theorem t : True := trivial",
                imports=[],
                mode="full",
                ctx=ctx,
            )
            count_at_return = len(ctx.calls)
            # Past the heartbeat interval — a leaked task would tick.
            await asyncio.sleep(0.25)
            assert len(ctx.calls) == count_at_return, (
                f"heartbeat leaked across LeanReplTimeoutError path: "
                f"{count_at_return} at return, {len(ctx.calls)} after "
                f"250ms sleep"
            )
            return result

        try:
            result = _run(_go())
            # m3 contract preserved: timeout envelope, respawn happened.
            assert result["status"] == "timeout"
            assert slow_timeout_repl.closed is True
            assert fake.lean_repl is respawned
        finally:
            reset_resources_for_tests()

    def test_ac5b_heartbeat_cancelled_on_lean_repl_error(self):
        """AC-5 / FM-7: non-timeout ``LeanReplError`` mid-await must
        also cancel the heartbeat. The handler returns an error envelope
        (m3 contract), not the timeout envelope."""
        from server.lean_repl import LeanReplError

        erroring_repl = _SlowFakeLeanRepl(
            raise_with=LeanReplError("REPL crashed: non-JSON response"),
            delay_s=0.15,
        )
        _attach_fake_resources(erroring_repl)

        ctx = _RecordingCtx()

        async def _go():
            result = await handle_lean_verify(
                snippet="theorem t : True := trivial",
                imports=[],
                mode="full",
                ctx=ctx,
            )
            count_at_return = len(ctx.calls)
            await asyncio.sleep(0.25)
            assert len(ctx.calls) == count_at_return, (
                f"heartbeat leaked across LeanReplError path: "
                f"{count_at_return} at return, {len(ctx.calls)} after "
                f"250ms sleep"
            )
            return result

        try:
            result = _run(_go())
            # m3 contract: status=error envelope (not "timeout").
            assert result["status"] == "error"
            assert result["lean_status"] == "available"
            assert "REPL crashed" in result["messages"][0]["text"]
        finally:
            reset_resources_for_tests()

    def test_fm2_disconnected_ctx_does_not_break_handler(self):
        """FM-2 (client disconnect mid-emission). ``ctx.report_progress``
        raises a transport-closed exception. The handler MUST still
        complete the REPL query normally — the disconnection is the
        SDK / session layer's problem, not the handler's."""
        slow_repl = _SlowFakeLeanRepl(responses=[{"env": 0}], delay_s=0.15)
        _attach_fake_resources(slow_repl)
        ctx = _RecordingCtx(raise_on_call=ConnectionError("SSE closed"))
        try:
            result = _run(
                handle_lean_verify(
                    snippet="theorem t : True := trivial",
                    imports=[],
                    mode="full",
                    ctx=ctx,
                )
            )
            # Query succeeded despite the ctx raising.
            assert result["status"] == "elaborated_no_errors"
            # At least one report_progress was attempted (and raised).
            assert len(ctx.calls) >= 1
        finally:
            reset_resources_for_tests()

    def test_fm8_ctx_excluded_from_input_schema(self):
        """FM-8 / AC-3 cardinal correctness: FastMCP's
        ``find_context_parameter`` returns ``"ctx"`` for the m4 handler,
        which causes ``Tool.from_function`` to add ``ctx`` to
        ``skip_names`` for ``func_metadata`` — therefore ``ctx`` does
        NOT appear in the tool's ``inputSchema``. The companion
        BP1-hash test in ``tests/test_server_tool_schema.py`` is the
        full byte-stability proof; this test guards the upstream
        mechanism FastMCP relies on."""
        from mcp.server.fastmcp.utilities.context_injection import (
            find_context_parameter,
        )

        assert find_context_parameter(handle_lean_verify) == "ctx", (
            "FastMCP must recognise ctx for injection — without this "
            "EXPECTED_TOOL_SCHEMA_SHA256 would drift and the BP1 cache "
            "would invalidate across every multi-agent session"
        )

    # ----- m4 rectification (critique F1 / F2 / F3 / F4 / F5) ----------

    def test_f4_no_emission_when_client_omits_progress_token(self):
        """m4 critique F4: when the client did NOT send
        ``_meta.progressToken``, ``_has_progress_token`` returns False,
        the heartbeat task is NEVER spawned, NO emissions occur, and the
        INFO-log spam is avoided. The handler still returns the result
        normally. This is the dominant prod path for non-progress-aware
        agents."""
        slow_repl = _SlowFakeLeanRepl(responses=[{"env": 0}], delay_s=0.2)
        _attach_fake_resources(slow_repl)
        # ``progress_token=None`` ⇒ _has_progress_token returns False.
        ctx = _RecordingCtx(progress_token=None)
        try:
            result = _run(
                handle_lean_verify(
                    snippet="theorem t : True := trivial",
                    imports=[],
                    mode="full",
                    ctx=ctx,
                )
            )
            assert result["status"] == "elaborated_no_errors"
            assert ctx.calls == [], (
                f"no emissions expected when client omits progressToken; "
                f"got {ctx.calls}"
            )
        finally:
            reset_resources_for_tests()

    def test_f2_total_tracks_default_query_timeout_s(self, monkeypatch):
        """m4 critique F2: ``total`` MUST track
        ``server.lean_repl.DEFAULT_QUERY_TIMEOUT_S`` — patching it
        scales the emitted ``total`` and the asymptotic taper. Without
        the import, the prior hardcoded ``_HEARTBEAT_TOTAL_S = 30.0``
        would emit ``total=30.0`` regardless and silently desynchronize
        from the real REPL budget."""
        import server.handlers.lean_verify as lv
        import server.lean_repl as lr

        # Patch the module-level binding the handler READS each tick
        # (the handler uses ``total=DEFAULT_QUERY_TIMEOUT_S`` — a bare
        # name resolved against ``server.handlers.lean_verify``'s
        # module globals at call time, so we patch it there).
        monkeypatch.setattr(lv, "DEFAULT_QUERY_TIMEOUT_S", 99.0)
        monkeypatch.setattr(lr, "DEFAULT_QUERY_TIMEOUT_S", 99.0)

        slow_repl = _SlowFakeLeanRepl(responses=[{"env": 0}], delay_s=0.2)
        _attach_fake_resources(slow_repl)
        ctx = _RecordingCtx()
        try:
            _run(
                handle_lean_verify(
                    snippet="theorem t : True := trivial",
                    imports=[],
                    mode="full",
                    ctx=ctx,
                )
            )
            assert len(ctx.calls) >= 1
            assert all(c["total"] == 99.0 for c in ctx.calls), (
                f"total MUST track the patched DEFAULT_QUERY_TIMEOUT_S "
                f"(=99.0); got {[c['total'] for c in ctx.calls]} — "
                f"hardcoded constant divergence from m4 critique F2"
            )
        finally:
            reset_resources_for_tests()

    def test_f1_progress_never_plateaus(self, monkeypatch):
        """m4 critique F1: the spec MUST is "progress MUST increase
        with each notification" — the prior ``min(elapsed / total,
        0.95)`` cap plateaued at 0.95. The asymptotic taper
        ``1 - exp(-elapsed / total)`` is strictly monotonic for all
        positive ``elapsed``. We force the cap region by shrinking
        ``DEFAULT_QUERY_TIMEOUT_S`` so the taper saturates rapidly
        within a tractable wall-clock — and confirm strict-monotonic
        emissions across many ticks."""
        import server.handlers.lean_verify as lv
        import server.lean_repl as lr

        # Tiny total + a longer-than-needed delay so MANY heartbeat
        # ticks fire while the (pre-fix) cap would have plateaued.
        monkeypatch.setattr(lv, "DEFAULT_QUERY_TIMEOUT_S", 0.1)
        monkeypatch.setattr(lr, "DEFAULT_QUERY_TIMEOUT_S", 0.1)

        slow_repl = _SlowFakeLeanRepl(responses=[{"env": 0}], delay_s=0.5)
        _attach_fake_resources(slow_repl)
        ctx = _RecordingCtx()
        try:
            _run(
                handle_lean_verify(
                    snippet="theorem t : True := trivial",
                    imports=[],
                    mode="full",
                    ctx=ctx,
                )
            )
            progresses = [c["progress"] for c in ctx.calls]
            # >=5 ticks at 50ms interval over 500ms call.
            assert len(progresses) >= 5, (
                f"expected >=5 emissions to exercise the cap region; "
                f"got {len(progresses)}"
            )
            # STRICT monotonic — the asymptotic taper has no plateau,
            # so every adjacent pair MUST satisfy a < b.
            assert all(
                a < b for a, b in zip(progresses, progresses[1:], strict=False)
            ), (
                f"progress plateaued — the cap-at-0.95 bug from m4 "
                f"critique F1 is back; got {progresses}"
            )
            # Strictly less than 1 by construction (asymptote).
            assert all(p < 1.0 for p in progresses), (
                f"progress reached 1.0; the asymptote should never "
                f"saturate; got {progresses}"
            )
        finally:
            reset_resources_for_tests()

    def test_f3_warn_log_on_emission_failure(self, caplog):
        """m4 critique F3: when ``report_progress`` raises (FM-2 client
        disconnect), the handler MUST log at WARN — silent swallow +
        unconditional INFO "heartbeat fired" was misleading. AND the
        INFO log MUST NOT fire on the failed-emission tick."""
        import logging as _logging

        slow_repl = _SlowFakeLeanRepl(responses=[{"env": 0}], delay_s=0.15)
        _attach_fake_resources(slow_repl)
        ctx = _RecordingCtx(raise_on_call=ConnectionError("SSE closed"))
        try:
            with caplog.at_level(
                _logging.WARNING, logger="server.handlers.lean_verify"
            ):
                result = _run(
                    handle_lean_verify(
                        snippet="theorem t : True := trivial",
                        imports=[],
                        mode="full",
                        ctx=ctx,
                    )
                )
            assert result["status"] == "elaborated_no_errors"
            warn_records = [
                r for r in caplog.records if r.levelno == _logging.WARNING
            ]
            assert any(
                "progress emission failed" in r.getMessage()
                for r in warn_records
            ), (
                f"expected a WARN log naming the emission failure; got "
                f"{[r.getMessage() for r in caplog.records]}"
            )
            # The INFO log for "heartbeat fired" MUST NOT appear on the
            # failed-emission tick (m4 critique F3 — the INFO was firing
            # unconditionally and overcounting emissions).
            info_records = [
                r for r in caplog.records if r.levelno == _logging.INFO
            ]
            heartbeat_info_records = [
                r
                for r in info_records
                if "progress heartbeat" in r.getMessage()
            ]
            assert heartbeat_info_records == [], (
                f"INFO 'heartbeat fired' MUST NOT log on a failed "
                f"emission; got {[r.getMessage() for r in heartbeat_info_records]}"
            )
        finally:
            reset_resources_for_tests()


# ===========================================================================
# Axiom-hygiene axis (issues #205 / #281 / #332)
# ===========================================================================


def _axioms_reply(**by_name: list[str]) -> dict[str, Any]:
    """Build a fake ``#print axioms`` REPL reply for the given declarations,
    in the exact wire form Lean emits (info-severity messages whose text is
    ``'<name>' depends on axioms: [...]`` / ``'<name>' does not depend on any
    axioms``)."""
    messages = []
    for name, axioms in by_name.items():
        text = (
            f"'{name}' depends on axioms: [{', '.join(axioms)}]"
            if axioms
            else f"'{name}' does not depend on any axioms"
        )
        messages.append(
            {"severity": "info", "pos": {"line": 0, "column": 0}, "data": text}
        )
    return {"env": 1, "messages": messages}


class TestDeclarationNameExtraction:
    """Unit tests for the name extractor that decides WHAT gets audited.

    Under-extraction is the dangerous direction — a declaration nobody asked
    ``#print axioms`` about would ride along inside a ``clean`` verdict — so
    the parser reports completeness separately and the scorer degrades to
    ``unknown`` whenever a declaration site could not be named.
    """

    def test_bare_axiom_is_extracted(self):
        assert _declaration_names("axiom h : False") == (["h"], True)

    def test_axiom_plus_dependent_theorem(self):
        names, complete = _declaration_names(
            "axiom cheat : False\ntheorem t : 1 = 2 := absurd rfl (cheat.elim)"
        )
        assert names == ["cheat", "t"]
        assert complete is True

    def test_namespace_qualifies_the_name(self):
        assert _declaration_names(
            "namespace N\ntheorem t : True := trivial\nend N"
        ) == (["N.t"], True)

    def test_bare_end_closes_a_section_not_the_namespace(self):
        """A ``section`` inside a ``namespace`` is closed by a bare ``end``.
        Popping the namespace there would silently de-qualify every later
        declaration, and a wrong name scores ``unknown`` — turning a clean
        proof into an unresolvable one."""
        names, complete = _declaration_names(
            "namespace N\n"
            "section\n"
            "theorem a : True := trivial\n"
            "end\n"
            "theorem b : True := trivial\n"
            "end N"
        )
        assert names == ["N.a", "N.b"]
        assert complete is True

    def test_attributes_and_modifiers_are_skipped(self):
        assert _declaration_names(
            "@[simp] private noncomputable def f (x : Nat) : Nat := x"
        ) == (["f"], True)

    def test_unnamed_instance_marks_the_extraction_incomplete(self):
        """An unnamed ``instance`` gets a compiler-generated name this parser
        cannot predict. It MUST surface as an unaudited declaration site, not
        be silently dropped."""
        assert _declaration_names("instance : Inhabited Nat := d") == ([], False)

    def test_named_instance_is_extracted(self):
        assert _declaration_names("instance nat0 : Inhabited Nat := d") == (
            ["nat0"],
            True,
        )

    def test_example_introduces_no_name(self):
        assert _declaration_names("example : True := trivial") == ([], True)


class TestPrefixedDeclarationSites:
    """arXMCP#382 — a declaration behind an unrecognised same-line prefix.

    ``_DECL_SITE_RE`` anchors the keyword at the start of the line, so ANY
    unrecognised token in front of it made the declaration invisible rather
    than merely unnamed: ``sites`` never incremented, the
    ``sites == len(names)`` fail-safe reported complete, and — whenever the
    snippet ALSO carried a recognised declaration — the prefixed one was
    silently dropped from a verdict that then read as ``clean``.

    Two distinct outcomes are correct here, and the tests below assert which
    one applies to each shape:

    - Shapes the parser can now READ (a same-line doc comment, ``alias``) are
      named and genuinely audited — strictly better than fail-safe.
    - Shapes it still cannot read (``set_option … in``, ``deriving instance``,
      ``meta …``) count as a site with no extractable name, the same fail-safe
      an unnamed ``instance`` already uses.

    Neither can move ``complete`` False -> True, so neither can admit an
    unaudited declaration.

    The first pass at #382 keyed on the ``in`` combinator and closed only five
    of the eight shapes; both Phase-3 critics caught it independently. The
    correct characterisation, from ``research/brief-2.md:155-158``, is that the
    line carries a declaration keyword with something unrecognised in front of
    it — "it is not really about ``in``".
    """

    # --- the reported shapes: MIXED snippet, where the drop was silent ---

    def test_set_option_in_theorem_is_not_silently_dropped(self):
        """AC#1 — the reported bug. `sneaky` is invisible to the name
        extractor, so the audit must refuse to call the sweep complete."""
        names, complete = _declaration_names(
            "set_option maxHeartbeats 400000 in theorem sneaky : False := sorry\n"
            "theorem harmless : True := trivial"
        )
        assert names == ["harmless"]
        assert complete is False

    def test_open_in_theorem_is_not_silently_dropped(self):
        """AC#2."""
        names, complete = _declaration_names(
            "open Classical in theorem sneaky : False := sorry\n"
            "theorem harmless : True := trivial"
        )
        assert names == ["harmless"]
        assert complete is False

    # --- the three siblings research found in the same class (AC#3) ---

    def test_variable_in_theorem_is_not_silently_dropped(self):
        names, complete = _declaration_names(
            "variable (n : Nat) in theorem sneaky : True := trivial\n"
            "theorem harmless : True := trivial"
        )
        assert names == ["harmless"]
        assert complete is False

    def test_universe_in_theorem_is_not_silently_dropped(self):
        names, complete = _declaration_names(
            "universe u in theorem sneaky : True := trivial\n"
            "theorem harmless : True := trivial"
        )
        assert names == ["harmless"]
        assert complete is False

    def test_attribute_in_theorem_is_not_silently_dropped(self):
        names, complete = _declaration_names(
            "attribute [simp] foo in theorem sneaky : True := trivial\n"
            "theorem harmless : True := trivial"
        )
        assert names == ["harmless"]
        assert complete is False

    def test_modifier_after_the_in_combinator_still_counts(self):
        """The prefix scan reuses the modifier/attribute grammar, so
        ``open X in noncomputable def f`` is a site too."""
        names, complete = _declaration_names(
            "open Classical in noncomputable def f : Nat := 0\n"
            "theorem harmless : True := trivial"
        )
        assert names == ["harmless"]
        assert complete is False

    # --- AC#4: the abstention path stays an abstention ---

    def test_prefixed_declaration_alone_yields_no_names(self):
        """A snippet whose ONLY declaration is prefixed still extracts no
        name, so ``_attach_axiom_audit`` still takes its ``if not names``
        branch and abstains. ``complete`` flips to False, which is strictly
        more accurate: there IS a declaration here, it just could not be
        named, and that is the reason string the caller now emits."""
        assert _declaration_names(
            "set_option maxHeartbeats 400000 in theorem sneaky : False := sorry"
        ) == ([], False)

    # --- AC#5: controls that must NOT regress ---

    def test_multiline_open_in_is_unaffected(self):
        """``open X in`` with the declaration on the NEXT line already worked
        — the next line matches ``_DECL_SITE_RE`` normally. Nothing follows
        ``in`` on the combinator line, so the prefix scan ignores it."""
        assert _declaration_names(
            "open Classical in\ntheorem fine : True := trivial"
        ) == (["fine"], True)

    def test_comment_mentioning_a_keyword_is_not_a_site(self):
        """The false-positive shape a loose keyword scan would have created.
        Lean prose uses these words constantly."""
        names, complete = _declaration_names(
            "-- prove this theorem using induction\n"
            "-- def foo does something\n"
            "theorem t : True := trivial"
        )
        assert names == ["t"]
        assert complete is True

    def test_mathlib_sum_binder_is_not_a_site(self):
        """``∑ i in Finset.range n`` is an ``in`` on a continuation line. No
        declaration keyword follows it, and ``instances`` / ``classical`` do
        not word-boundary-match ``instance`` / ``class``."""
        names, complete = _declaration_names(
            "theorem s :\n"
            "    ∑ i in Finset.range n, f i = g n := by\n"
            "  simp [instances, classical]"
        )
        assert names == ["s"]
        assert complete is True

    def test_bare_open_and_variable_lines_stay_invisible(self):
        """A bare ``open``/``variable``/``universe`` line introduces no
        kernel-checked declaration ``#print axioms`` could address, and must
        keep introducing no site."""
        names, complete = _declaration_names(
            "open Classical\n"
            "variable (n : Nat)\n"
            "universe u\n"
            "theorem t : True := trivial"
        )
        assert names == ["t"]
        assert complete is True

    # --- H1: same-line comment prefixes (Phase-3 critique) ---

    def test_same_line_doc_comment_declaration_is_audited(self):
        """The founding threat, one doc comment away. Before the rectify pass
        this returned ``(['harmless'], True)`` — `axiom evil : False` inside a
        verdict that read `clean`. Comment text is now stripped, so `evil` is
        a normally-named site and is genuinely sent to `#print axioms`."""
        names, complete = _declaration_names(
            "/-- Helper. -/ axiom evil : False\n"
            "theorem harmless : True := trivial"
        )
        assert names == ["evil", "harmless"]
        assert complete is True

    def test_same_line_block_comment_declaration_is_audited(self):
        names, complete = _declaration_names(
            "/- setup -/ axiom evil : False\n"
            "theorem harmless : True := trivial"
        )
        assert names == ["evil", "harmless"]
        assert complete is True

    # --- H2: prefixes with no `in` combinator (Phase-3 critique) ---

    def test_deriving_instance_is_not_silently_dropped(self):
        """Quoted verbatim from live mathlib4 via ``research/brief-2.md:141``.
        No `in` anywhere, so the first pass at #382 missed it entirely."""
        names, complete = _declaration_names(
            "deriving instance ToExpr for ULift\n"
            "theorem harmless : True := trivial"
        )
        assert names == ["harmless"]
        assert complete is False

    def test_meta_prefix_is_not_silently_dropped(self):
        names, complete = _declaration_names(
            "meta unsafe instance foo : Inhabited Nat := d\n"
            "theorem harmless : True := trivial"
        )
        assert names == ["harmless"]
        assert complete is False

    def test_alias_is_a_declaration_keyword(self):
        """`alias foo := bar` registers a real declaration. It was missing
        from ``_DECL_KEYWORDS`` outright, so — unlike the fail-safe shapes —
        the fix is to NAME it, not merely to count it."""
        names, complete = _declaration_names(
            "alias sneaky := Classical.choice\n"
            "theorem harmless : True := trivial"
        )
        assert names == ["sneaky", "harmless"]
        assert complete is True

    # --- M1/M2: the broadened scan must not fire on prose ---

    def test_comment_containing_in_theorem_is_not_a_site(self):
        """The pinning test the first pass lacked. Its predecessor,
        ``test_comment_mentioning_a_keyword_is_not_a_site``, uses comments with
        no ``in`` — so it passed identically with and without the regex and
        could never have caught this."""
        names, complete = _declaration_names(
            "-- as used in theorem 3.2\ntheorem t : True := trivial"
        )
        assert names == ["t"]
        assert complete is True

    def test_tactic_line_trailing_comment_is_not_a_site(self):
        names, complete = _declaration_names(
            "theorem t : True := by\n"
            "  simp [Finset.sum_comm] -- in def form\n"
            "  trivial"
        )
        assert names == ["t"]
        assert complete is True

    def test_multiline_block_comment_prose_is_not_a_site(self):
        """Block comments span lines and nest; prose inside one must not be
        scanned for declaration keywords."""
        names, complete = _declaration_names(
            "/-\n"
            "This is proved in theorem 2.1, see also /- nested -/ remarks.\n"
            "-/\n"
            "theorem harmless : True := trivial"
        )
        assert names == ["harmless"]
        assert complete is True

    def test_snippet_with_no_declaration_does_not_claim_one(self):
        """The false-evidence case: reporting ``complete=False`` here made the
        record assert a declaration existed that could not be named, for a
        snippet containing no declaration at all."""
        assert _declaration_names(
            "-- refer to the bound in lemma 2\n#check Nat"
        ) == ([], True)

    def test_projection_ending_in_a_keyword_is_not_a_site(self):
        """The keyword must be whitespace-preceded, so ``Set.def`` in a tactic
        argument is not a declaration site."""
        names, complete = _declaration_names(
            "theorem t : True := by\n  simp [Set.def]\n  trivial"
        )
        assert names == ["t"]
        assert complete is True

    # --- the comment scanner's own hazards ---

    def test_comment_opener_inside_a_string_does_not_open_a_comment(self):
        """Without string tracking, ``"/-"`` would open a block comment that
        never closes and every later declaration in the snippet would vanish —
        the exact silent drop this module exists to prevent."""
        names, complete = _declaration_names(
            'def s : String := "/-"\ntheorem harmless : True := trivial'
        )
        assert names == ["s", "harmless"]
        assert complete is True

    def test_line_comment_marker_inside_a_string_is_not_a_comment(self):
        names, complete = _declaration_names(
            'def s : String := "-- not a comment"\n'
            "theorem harmless : True := trivial"
        )
        assert names == ["s", "harmless"]
        assert complete is True

    def test_escaped_quote_does_not_end_the_string(self):
        names, complete = _declaration_names(
            'def s : String := "he said \\"/-\\" loudly"\n'
            "theorem harmless : True := trivial"
        )
        assert names == ["s", "harmless"]
        assert complete is True

    def test_apostrophe_identifiers_survive(self):
        """``'`` is a legal identifier character in Lean, so the scanner
        deliberately does NOT track char literals."""
        names, complete = _declaration_names(
            "theorem h' : True := trivial\ntheorem h'' : True := trivial"
        )
        assert names == ["h'", "h''"]
        assert complete is True

    def test_claude_md_table_matches_live_behavior(self):
        """CLAUDE.md §4.10 rule 3 carries a measured table of
        ``_declaration_names`` outputs. It is loaded at session start by every
        agent in this repo and it is the constitutional statement of what the
        axiom axis may promise a sibling formalization repo — so a stale row
        teaches every future agent a false mechanism.

        It went stale once already: the block described #382 as live, in the
        present tense, after the fix landed. This derives the table's claims
        from live code so the block cannot drift silently again in either
        direction — change the code without the doc, or the doc without the
        code, and this fails.
        """
        # One concrete snippet per table row, in the table's own order.
        rows = [
            ("theorem harmless : True := trivial", (["harmless"], True)),
            (
                "set_option maxHeartbeats 400000 in "
                "theorem sneaky : True := trivial",
                ([], False),
            ),
            (
                "instance : Inhabited Nat := d\n"
                "theorem harmless : True := trivial",
                (["harmless"], False),
            ),
            (
                "set_option maxHeartbeats 400000 in "
                "theorem sneaky : True := trivial\n"
                "theorem harmless : True := trivial",
                (["harmless"], False),
            ),
            (
                "deriving instance ToExpr for ULift\n"
                "theorem harmless : True := trivial",
                (["harmless"], False),
            ),
            (
                "/-- doc -/ axiom evil : False\n"
                "theorem harmless : True := trivial",
                (["evil", "harmless"], True),
            ),
            # #382 round 2 — one physical line, two Lean commands.
            (
                "def harmless : Nat := 1 axiom evil : False",
                (["harmless"], False),
            ),
            (
                "namespace N theorem t : True := trivial axiom evil : False",
                ([], False),
            ),
        ]

        claude_md = (Path(__file__).resolve().parents[1] / "CLAUDE.md").read_text()
        block = claude_md.split("issue #382")[1].split("Any axis whose")[0]
        table = [
            line for line in block.splitlines()
            if line.strip().startswith("|") and "`_declaration_names`" not in line
            and not set(line.strip()) <= set("|- ")
        ]

        assert len(table) == len(rows), (
            f"CLAUDE.md §4.10 rule 3's table has {len(table)} rows but this "
            f"test knows {len(rows)} snippets. Add the snippet for the new row "
            "here — an unpinned row is how the block went stale before."
        )

        for (snippet, expected), doc_row in zip(rows, table, strict=True):
            live = _declaration_names(snippet)
            assert live == expected, (
                f"live _declaration_names disagrees with this test: {live!r} "
                f"!= {expected!r} for {snippet!r}"
            )
            # The doc's own middle column must state the same tuple.
            names, complete = expected
            rendered = f"({names!r}, {complete})".replace("'", "'")
            assert rendered in doc_row.replace("`", ""), (
                f"CLAUDE.md §4.10 rule 3 row is stale.\n"
                f"  row:      {doc_row.strip()}\n"
                f"  measured: {rendered}"
            )

    def test_the_whole_chain_refuses_to_report_clean(self):
        """End-to-end over the two functions the caller composes: every name
        we DID ask about came back clean, but the dropped declaration must
        stop the record reading as a clean sweep."""
        names, complete = _declaration_names(
            "set_option maxHeartbeats 400000 in theorem sneaky : False := sorry\n"
            "theorem harmless : True := trivial"
        )
        rec = _audit_from_messages(
            [{"text": "'harmless' does not depend on any axioms"}], names, complete
        )
        assert rec["outcome"] == "unknown"
        assert "could not name" in rec["reason"]


class TestMultipleDeclarationsOnOnePhysicalLine:
    """arXMCP#382 round 2 — Lean reads COMMANDS, this parser reads LINES.

    Lean 4 is whitespace-insensitive at the command level: the term parser
    stops at a command keyword, so one physical line can carry any number of
    declarations. ``_DECL_SITE_RE`` anchors at the start of the line and
    ``.match()`` returns at most once, so a line was worth 0 or 1 sites no
    matter how many declarations Lean actually read off it — and
    ``sites == len(names)`` then reported a COMPLETE sweep over a snippet
    whose second declaration was never named, never audited, and therefore
    never able to move the record off ``clean``.

    Every shape below was executed against real ``leanprover/lean4:v4.29.0``
    before being pinned here. The reported one::

        def harmless : Nat := 1 axiom evil : False

        'harmless' does not depend on any axioms
        'evil' depends on axioms: [evil]

    Two declarations, one of them an axiom, and the pre-fix extractor returned
    ``(['harmless'], True)``.

    The scope commands are the same hole wearing a different hat: the
    ``namespace`` / ``section`` / ``end`` branches consumed their line and
    ``continue``d, so a declaration riding behind the scope command was not
    merely unnamed but never counted. All three were confirmed live —
    ``end N axiom evil : False`` and ``section axiom evil2 : False`` both
    register their axiom.

    As everywhere else in this module the correction is fail-safe, never
    feature: over-counting sites can only move ``complete`` True -> False.
    """

    # --- the reported shape, both orderings ---

    def test_axiom_hidden_behind_a_def_on_the_same_line(self):
        """The reported bug, verbatim. `evil` is invisible to the name
        extractor, so the sweep must refuse to call itself complete."""
        names, complete = _declaration_names(
            "def harmless : Nat := 1 axiom evil : False"
        )
        assert names == ["harmless"]
        assert complete is False

    def test_axiom_hidden_behind_a_theorem_on_the_same_line(self):
        names, complete = _declaration_names(
            "theorem harmless : True := trivial axiom evil : False"
        )
        assert names == ["harmless"]
        assert complete is False

    def test_leading_axiom_is_named_but_the_sweep_is_still_incomplete(self):
        """Reversing the order names `evil` instead — but `harmless` is now
        the dropped one, so the sweep is no more complete than before. The
        fail-safe must not depend on WHICH declaration got lucky."""
        names, complete = _declaration_names(
            "axiom evil : False def harmless : Nat := 1"
        )
        assert names == ["evil"]
        assert complete is False

    # --- the scope commands, which used to consume their whole line ---

    def test_namespace_cannot_swallow_a_declaration_sharing_its_line(self):
        """Lean registers `N.t` AND `N.evil` here. The namespace branch used
        to `continue` before anything on the line was counted."""
        names, complete = _declaration_names(
            "namespace N theorem t : True := trivial axiom evil : False"
        )
        assert names == []
        assert complete is False

    def test_end_cannot_swallow_a_declaration_sharing_its_line(self):
        names, complete = _declaration_names(
            "namespace N\ntheorem t : True := trivial\nend N axiom evil : False"
        )
        assert names == ["N.t"]
        assert complete is False

    def test_section_cannot_swallow_a_declaration_sharing_its_line(self):
        names, complete = _declaration_names(
            "section axiom evil : False\nend"
        )
        assert names == []
        assert complete is False

    # --- the counting scan must not over-fire on ordinary code ---

    def test_prose_inside_a_string_literal_is_not_a_declaration_site(self):
        """The scan reads the whole line, so `_strip_comments` must mask
        string INTERIORS or every string mentioning `theorem`/`def` would
        abstain a perfectly auditable snippet. Fail-safe is not free — an
        `unknown` this snippet does not deserve is still a wrong answer."""
        names, complete = _declaration_names(
            'def s : String := "a theorem about a def"\n'
            "theorem harmless : True := trivial"
        )
        assert names == ["s", "harmless"]
        assert complete is True

    def test_attribute_bracket_without_a_space_still_counts_once(self):
        """`@[simp]theorem t` is legal Lean and the name extractor reads it,
        so the scan must too — otherwise sites(0) < names(1) and a valid
        snippet abstains."""
        names, complete = _declaration_names("@[simp]theorem t : True := trivial")
        assert names == ["t"]
        assert complete is True

    def test_projection_named_like_a_keyword_is_not_a_site(self):
        """`Set.def` is dot-preceded, not whitespace-preceded."""
        names, complete = _declaration_names(
            "theorem t : True := by simp [Set.def]"
        )
        assert names == ["t"]
        assert complete is True

    # --- the round-trip, which is where the defect was observable ---

    def test_same_line_axiom_does_not_reach_the_wire_as_clean(self):
        """arXMCP#382 round 2, end-to-end. `#print axioms` is issued for
        `harmless` only and comes back clean; the envelope must still refuse
        to report a clean trust record, because `evil` was never asked about.
        """
        repl = _repl_with([{"env": 0}, _axioms_reply(harmless=[])])
        result = _run(
            handle_lean_verify(snippet="def harmless : Nat := 1 axiom evil : False")
        )

        # The kernel-acceptance axis is untouched — the snippet really did
        # elaborate. Only the axiom axis carries the bad news (CLAUDE.md §4.9:
        # no axis is inferred from another).
        assert result["status"] == "elaborated_no_errors"
        assert result["compilation_success"] is True

        audit = result["axiom_audit"]
        assert audit["outcome"] == "unknown"
        assert audit["reason"] is not None
        assert repl.commands[1] == {"cmd": "#print axioms harmless", "env": 0}


class TestAxiomAuditScoring:
    """Unit tests for scoring a ``#print axioms`` reply set."""

    def test_allowlisted_axioms_are_clean(self):
        rec = _audit_from_messages(
            [{"text": "'t' depends on axioms: [propext, Classical.choice]"}],
            ["t"],
            True,
        )
        assert rec["outcome"] == "clean"
        assert rec["disallowed_axioms"] == []

    def test_no_axiom_dependency_is_clean(self):
        rec = _audit_from_messages(
            [{"text": "'t' does not depend on any axioms"}], ["t"], True
        )
        assert rec["outcome"] == "clean"
        assert rec["declarations"][0]["axioms"] == []

    def test_user_axiom_is_flagged(self):
        rec = _audit_from_messages(
            [{"text": "'t' depends on axioms: [propext, h]"}], ["t"], True
        )
        assert rec["outcome"] == "flagged"
        assert rec["disallowed_axioms"] == ["h"]

    def test_sorry_ax_is_flagged(self):
        """``sorryAx`` is the axiom-side cross-check on the proof-closure
        axis: it needs no special-casing, it is simply not allowlisted."""
        rec = _audit_from_messages(
            [{"text": "'t' depends on axioms: [sorryAx]"}], ["t"], True
        )
        assert rec["outcome"] == "flagged"
        assert rec["disallowed_axioms"] == ["sorryAx"]

    def test_native_decide_trust_reduction_is_flagged(self):
        rec = _audit_from_messages(
            [{"text": "'t' depends on axioms: [Lean.ofReduceBool]"}], ["t"], True
        )
        assert rec["outcome"] == "flagged"
        assert rec["disallowed_axioms"] == ["Lean.ofReduceBool"]

    def test_unanswered_declaration_is_unknown_not_clean(self):
        rec = _audit_from_messages([], ["t"], True)
        assert rec["outcome"] == "unknown"
        assert rec["declarations"][0]["verdict"] == "unknown"

    def test_incomplete_extraction_downgrades_a_clean_sweep(self):
        """Every name we DID ask about came back clean, but a declaration
        site went unnamed — the record must not read as a clean sweep."""
        rec = _audit_from_messages(
            [{"text": "'t' does not depend on any axioms"}], ["t"], False
        )
        assert rec["outcome"] == "unknown"
        assert "could not name" in rec["reason"]

    def test_flagged_outranks_unknown(self):
        """Weakest-link meet WITHIN the axis: a real finding is strictly more
        informative and more severe than an unresolved name."""
        rec = _audit_from_messages(
            [{"text": "'a' depends on axioms: [h]"}], ["a", "b"], True
        )
        assert rec["outcome"] == "flagged"

    def test_replies_bind_by_name_not_by_order(self):
        rec = _audit_from_messages(
            [
                {"text": "'b' depends on axioms: [h]"},
                {"text": "'a' does not depend on any axioms"},
            ],
            ["a", "b"],
            True,
        )
        by_name = {d["name"]: d for d in rec["declarations"]}
        assert by_name["a"]["verdict"] == "clean"
        assert by_name["b"]["verdict"] == "flagged"

    def test_record_carries_its_evidence(self):
        """Policy §6 rule 3 — a trust-bearing field carries its evidence, not
        a bare token."""
        rec = _audit_from_messages(
            [{"text": "'t' depends on axioms: [propext]"}], ["t"], True
        )
        assert rec["allowlist"] == sorted(AXIOM_ALLOWLIST)
        assert rec["method"] == "#print axioms"
        assert rec["declarations"][0]["axioms"] == ["propext"]


class TestAxiomHygieneOnTheWire:
    """The end-to-end defect from issues #205 / #281 / #332."""

    def teardown_method(self):
        reset_resources_for_tests()

    def test_bare_axiom_false_does_not_report_a_clean_trust_record(self):
        """THE acceptance test for #205.

        ``axiom h : False`` elaborates with no error and no sorry, so the
        elaboration and kernel-acceptance axes legitimately pass — the kernel
        really did accept it. What must NOT happen is the result reading as a
        clean trust record overall.
        """
        repl = _repl_with([{"env": 0}, _axioms_reply(h=["h"])])
        result = _run(handle_lean_verify(snippet="axiom h : False"))

        audit = result["axiom_audit"]
        assert audit["outcome"] == "flagged"
        assert audit["disallowed_axioms"] == ["h"]
        assert audit["declarations"] == [
            {"name": "h", "axioms": ["h"], "verdict": "flagged"}
        ]
        # The audit really was driven by Lean, against the produced env.
        assert repl.commands[1] == {"cmd": "#print axioms h", "env": 0}

        # No field anywhere in the envelope reports a clean trust record.
        assert "clean" not in json.dumps(result)

    def test_status_and_compilation_success_are_not_inferred_from_the_audit(
        self,
    ):
        """Policy §4 / CLAUDE.md §4.9 rule 1: no axis is inferred from
        another. The axiom finding must not rewrite the elaboration or
        kernel-acceptance axes — that is the same conflation this milestone
        removes, merely pointing the other way. The kernel DID accept the
        snippet, and the record says so honestly while the axiom axis
        carries the bad news."""
        _repl_with([{"env": 0}, _axioms_reply(h=["h"])])
        result = _run(handle_lean_verify(snippet="axiom h : False"))
        assert result["status"] == "elaborated_no_errors"
        assert result["compilation_success"] is True
        assert result["axiom_audit"]["outcome"] == "flagged"

    def test_issue_332_failure_scenario(self):
        """``axiom cheat : False`` + a theorem that leans on it. Both
        declarations are audited and both are flagged."""
        _repl_with(
            [
                {"env": 0},
                _axioms_reply(cheat=["cheat"], t=["propext", "cheat"]),
            ]
        )
        result = _run(
            handle_lean_verify(
                snippet=(
                    "axiom cheat : False\n"
                    "theorem t : 1 = 2 := absurd rfl (cheat.elim)"
                )
            )
        )
        audit = result["axiom_audit"]
        assert audit["outcome"] == "flagged"
        assert audit["disallowed_axioms"] == ["cheat"]
        assert {d["name"] for d in audit["declarations"]} == {"cheat", "t"}

    def test_honest_clean_proof_reports_clean(self):
        """The axis is not a blanket refusal — a genuinely clean proof must
        still be reportable as clean, or the signal is worthless."""
        _repl_with(
            [{"env": 0}, _axioms_reply(t=["propext", "Classical.choice"])]
        )
        result = _run(handle_lean_verify(snippet="theorem t : 1+1=2 := rfl"))
        assert result["status"] == "elaborated_no_errors"
        assert result["axiom_audit"]["outcome"] == "clean"
        assert result["axiom_audit"]["reason"] is None

    def test_sorry_path_is_audited_and_flags_sorry_ax(self):
        """A sorry-carrying theorem still runs the audit; ``sorryAx`` shows
        up on the axiom axis independently of ``status='sorry'``."""
        _repl_with(
            [
                {"env": 0, "sorries": [{"goal": "n = n", "proofState": 0}]},
                _axioms_reply(t=["sorryAx"]),
            ]
        )
        result = _run(handle_lean_verify(snippet="theorem t : n = n := by sorry"))
        assert result["status"] == "sorry"
        assert result["axiom_audit"]["outcome"] == "flagged"
        assert result["axiom_audit"]["disallowed_axioms"] == ["sorryAx"]

    def test_prefixed_declaration_does_not_reach_the_wire_as_clean(self):
        """arXMCP#382 end-to-end. Every name the tool DID ask about comes back
        clean, but `deriving instance` was never asked about — the envelope
        must not report a clean trust record.

        The unit tests pin the tuple; this pins the whole round-trip, which is
        where the defect was actually observable: `#print axioms` is issued for
        `harmless` only, and the caller must still refuse to say `clean`.
        """
        repl = _repl_with([{"env": 0}, _axioms_reply(harmless=[])])
        result = _run(
            handle_lean_verify(
                snippet=(
                    "deriving instance ToExpr for ULift\n"
                    "theorem harmless : True := trivial"
                )
            )
        )

        # The kernel-acceptance axis is untouched — the snippet really did
        # elaborate. Only the axiom axis carries the bad news.
        assert result["status"] == "elaborated_no_errors"
        assert result["compilation_success"] is True

        audit = result["axiom_audit"]
        assert audit["outcome"] == "unknown"
        assert audit["reason"] is not None
        # Only `harmless` was ever asked about — that is the drop, made
        # visible. `harmless` itself is legitimately clean per-declaration;
        # what must not happen is the RECORD's outcome reading clean on the
        # strength of it.
        assert repl.commands[1] == {"cmd": "#print axioms harmless", "env": 0}
        assert [d["name"] for d in audit["declarations"]] == ["harmless"]
        assert json.loads(json.dumps(result))["axiom_audit"]["outcome"] != "clean"

    def test_incomplete_extraction_reason_names_the_prefix_cause(self):
        """The evidence attached to a trust-bearing field must name the actual
        cause (policy §6 rule 3). Before the rectify pass the reason offered
        only 'an unnamed instance or an unrecognized declaration form', which
        pointed a reader at the wrong mechanism entirely."""
        _repl_with([{"env": 0}, _axioms_reply(harmless=[])])
        result = _run(
            handle_lean_verify(
                snippet=(
                    "set_option maxHeartbeats 400000 in theorem sneaky : True := trivial\n"
                    "theorem harmless : True := trivial"
                )
            )
        )
        reason = result["axiom_audit"]["reason"]
        assert "same-line prefix" in reason
        assert "set_option" in reason


class TestAxiomAuditAbstentionPaths:
    """Every path that does NOT measure the axis must say so — never 'clean'
    (trust-language policy §6 rule 5: no axis defaults to passing)."""

    def teardown_method(self):
        reset_resources_for_tests()

    def test_syntax_only_is_not_applicable(self):
        _repl_with([{"env": 0}])
        result = _run(
            handle_lean_verify(
                snippet="theorem t : True := trivial", mode="syntax_only"
            )
        )
        assert result["axiom_audit"]["outcome"] == "not-applicable"
        assert result["compilation_success"] is None

    def test_syntax_only_issues_no_audit_round_trip(self):
        repl = _repl_with([{"env": 0}])
        _run(
            handle_lean_verify(
                snippet="theorem t : True := trivial", mode="syntax_only"
            )
        )
        assert len(repl.commands) == 1

    def test_tactic_step_is_not_applicable(self):
        _repl_with(
            [{"proofStatus": "Completed", "proofState": 1, "goals": []}],
            generation="genA",
        )
        result = _run(
            handle_lean_verify(
                snippet="simp", mode="tactic_step", proof_state="genA:0"
            )
        )
        assert result["axiom_audit"]["outcome"] == "not-applicable"

    def test_type_error_is_not_applicable(self):
        _repl_with(
            [
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
            ]
        )
        result = _run(handle_lean_verify(snippet="theorem t : 1+1=3 := rfl"))
        assert result["status"] == "error"
        assert result["axiom_audit"]["outcome"] == "not-applicable"

    def test_disabled_repl_is_not_applicable(self, fake_resources_disabled):
        result = _run(handle_lean_verify(snippet="theorem t : True := trivial"))
        assert result["status"] == "unavailable"
        assert result["axiom_audit"]["outcome"] == "not-applicable"

    def test_invalid_continuation_is_not_applicable(self):
        _repl_with([{"env": 0}], generation="genA")
        result = _run(
            handle_lean_verify(
                snippet="theorem t : True := trivial", env="badtoken"
            )
        )
        assert result["status"] == "invalid-input"
        assert result["axiom_audit"]["outcome"] == "not-applicable"

    def test_term_snippet_with_no_declaration_is_unknown_not_clean(self):
        """A snippet that names nothing carries no auditable axiom closure.
        That is an epistemic abstention, explicitly not a pass."""
        repl = _repl_with([{"env": 0}])
        result = _run(handle_lean_verify(snippet="(1 : Nat) + 1"))
        assert result["axiom_audit"]["outcome"] == "unknown"
        # No pointless round-trip when there is nothing to address.
        assert len(repl.commands) == 1

    def test_missing_env_id_is_unknown(self):
        """Without an env id there is no environment in which to resolve the
        declarations — unknown, and no round-trip attempted."""
        repl = _repl_with([{}])
        result = _run(handle_lean_verify(snippet="theorem t : True := trivial"))
        assert result["axiom_audit"]["outcome"] == "unknown"
        assert len(repl.commands) == 1

    def test_unanswered_audit_is_unknown(self):
        """Lean returned nothing usable for the declaration — unknown."""
        _repl_with([{"env": 0}, {"env": 1, "messages": []}])
        result = _run(handle_lean_verify(snippet="theorem t : True := trivial"))
        assert result["axiom_audit"]["outcome"] == "unknown"

    def test_no_envelope_ever_defaults_the_axis_to_clean(self):
        """Belt-and-braces over the whole sentinel family: a 'clean' outcome
        must be impossible without a measurement behind it."""
        from server.handlers.lean_verify import (
            _disabled_envelope,
            _invalid_continuation_envelope,
            _message_error_envelope,
            _timeout_envelope,
        )

        envelopes = [
            _disabled_envelope("full"),
            _timeout_envelope("full", 30.0),
            _invalid_continuation_envelope(
                "full", continuation_status="expired", message="x"
            ),
            _message_error_envelope(
                "full", "boom", continuation_status="not-applicable"
            ),
        ]
        for env in envelopes:
            assert env["axiom_audit"]["outcome"] == "not-applicable"
            assert env["axiom_audit"]["declarations"] == []
            assert env["axiom_audit"]["reason"]


class TestAxiomAuditFailureIsolation:
    """An audit that cannot run must degrade to 'unknown' and leave the
    primary verdict untouched — never crash the call, never fake a pass."""

    def teardown_method(self):
        reset_resources_for_tests()

    def test_repl_error_during_audit_degrades_to_unknown(self):
        class _FailOnAudit(_FakeLeanRepl):
            async def query(self, command):
                self.commands.append(command)
                if "#print axioms" in command.get("cmd", ""):
                    raise LeanReplError("boom")
                return self._next_response()

        repl = _FailOnAudit(responses=[{"env": 0}])
        _attach_fake_resources(repl)
        result = _run(handle_lean_verify(snippet="theorem t : True := trivial"))
        # Primary verdict survives intact...
        assert result["status"] == "elaborated_no_errors"
        assert result["compilation_success"] is True
        # ...and the axis honestly reports that it could not be measured.
        assert result["axiom_audit"]["outcome"] == "unknown"
        assert "boom" in result["axiom_audit"]["reason"]

    def test_audit_timeout_respawns_and_invalidates_dead_tokens(self):
        """A wedged audit round-trip carries the same stale-stdout hazard as
        the primary query, so it triggers the same kill+respawn. The
        continuation tokens the primary response minted address a process
        that no longer exists, so they must not be emitted as live."""
        import server.handlers.lean_verify as lv

        class _TimeoutOnAudit(_FakeLeanRepl):
            async def query(self, command):
                self.commands.append(command)
                if "#print axioms" in command.get("cmd", ""):
                    raise LeanReplTimeoutError("audit timed out")
                return self._next_response()

        repl = _TimeoutOnAudit(
            responses=[
                {"env": 7, "sorries": [{"goal": "g", "proofState": 3}]}
            ]
        )
        fake = _attach_fake_resources(repl)

        respawned = _FakeLeanRepl(generation="genB")

        async def _fake_spawn(_config):
            return respawned

        original = lv.LeanRepl.spawn_from_config
        lv.LeanRepl.spawn_from_config = staticmethod(_fake_spawn)
        try:
            result = _run(
                handle_lean_verify(snippet="theorem t : g := by sorry")
            )
        finally:
            lv.LeanRepl.spawn_from_config = original

        assert repl.closed is True
        assert fake.lean_repl is respawned
        # Primary axes intact.
        assert result["status"] == "sorry"
        # Axiom axis unknown, not clean.
        assert result["axiom_audit"]["outcome"] == "unknown"
        # Dead tokens are not advertised as resumable.
        assert result["env"] is None
        assert result["proof_state_id"] is None
        assert "proof_state_id" not in result["sorry_goals"][0]


class TestAxiomAuditSchemaConformance:
    """The new envelope shapes validate against lean_verify_result.json."""

    def teardown_method(self):
        reset_resources_for_tests()

    @staticmethod
    def _validate(result):
        from jsonschema import Draft7Validator

        schema_path = (
            Path(__file__).parent.parent
            / "server"
            / "schemas"
            / "lean_verify_result.json"
        )
        with open(schema_path, encoding="utf-8") as f:
            Draft7Validator(json.load(f)).validate(result)

    def test_flagged_envelope_conforms(self):
        _repl_with([{"env": 0}, _axioms_reply(h=["h"])])
        self._validate(_run(handle_lean_verify(snippet="axiom h : False")))

    def test_clean_envelope_conforms(self):
        _repl_with([{"env": 0}, _axioms_reply(t=["propext"])])
        self._validate(
            _run(handle_lean_verify(snippet="theorem t : 1+1=2 := rfl"))
        )

    def test_unknown_envelope_conforms(self):
        _repl_with([{"env": 0}, {"env": 1, "messages": []}])
        self._validate(
            _run(handle_lean_verify(snippet="theorem t : True := trivial"))
        )

    def test_not_applicable_envelope_conforms(self):
        _repl_with([{"env": 0}])
        self._validate(
            _run(
                handle_lean_verify(
                    snippet="theorem t : True := trivial", mode="syntax_only"
                )
            )
        )

    def test_axiom_audit_is_required_by_the_schema(self):
        """Until the staged TOOL_SCHEMA_VERSION bump lands, the version
        integer cannot distinguish this shape from the pre-audit one — so
        consumers key on the PRESENCE of axiom_audit, which means it must be
        required rather than optional."""
        schema_path = (
            Path(__file__).parent.parent
            / "server"
            / "schemas"
            / "lean_verify_result.json"
        )
        with open(schema_path, encoding="utf-8") as f:
            schema = json.load(f)
        assert "axiom_audit" in schema["required"]


@_lean_skip
@pytest.mark.requires_lean_repl
class TestAxiomHygieneAgainstRealLean:
    """Tier-3: the same acceptance case against a REAL Lean kernel.

    The fake-REPL tests pin the handler's scoring; this one pins the thing
    that actually has to be true — that Lean's own ``#print axioms`` output,
    in its real wire format, parses into a flagged verdict for a snippet the
    elaborator is perfectly happy with.
    """

    def teardown_method(self):
        reset_resources_for_tests()

    def test_axiom_false_is_flagged_by_the_real_kernel(self):
        from server.lean_repl import LeanRepl

        async def _go():
            repl = await LeanRepl.spawn(
                lake_path=_LAKE_PATH, repl_dir=_REPL_DIR
            )
            cfg = Config(
                result_byte_cap=256 * 1024,
                enable_lean=True,
                lake_path=_LAKE_PATH,
                lean_repl_dir=_REPL_DIR,
            )

            class _R:
                pass

            r = _R()
            r.config = cfg
            r.corpus_info = _FakeCorpusInfo()
            r.lean_repl = repl
            set_resources(r)
            try:
                return await handle_lean_verify(snippet="axiom h : False")
            finally:
                await repl.close()

        result = _run(_go())
        # Elaboration is genuinely clean — that is the whole point.
        assert result["status"] == "elaborated_no_errors"
        assert result["compilation_success"] is True
        # And the axiom axis catches what those fields never could.
        assert result["axiom_audit"]["outcome"] == "flagged"
        assert "h" in result["axiom_audit"]["disallowed_axioms"]
