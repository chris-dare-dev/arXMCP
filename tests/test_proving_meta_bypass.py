"""Regression: the meta-programming kernel-check bypass (finding R2-AC-1).

An author-supplied Lean snippet can add a declaration to the elaboration
environment with kernel checking DISABLED::

    import Lean
    open Lean in
    run_cmd do
      let decl := Declaration.thmDecl {
        name := `fake_false, levelParams := [],
        type := .const ``False [], value := .const ``True.intro [] }
      let env <- getEnv
      match env.addDeclCore 0 decl none false with   -- doCheck := false
      | .ok env' => setEnv env'
      | .error _ => logError "addDeclCore failed"
    theorem attack_false : False := fake_false

``fake_false`` is asserted ``: False`` without the kernel ever checking its
value (``True.intro : True``), so ``theorem attack_false : False``
type-checks, ``#print axioms attack_false`` reports a CLEAN closure (it
only walks the stored proof term, which references no axiom), and the whole
snippet returned ``status:"ok"`` / ``axiom_closure_ok:true`` — defeating the
axiom-closure audit and making a false ``proven-formal`` (formal_award_ok)
AND a false ``refuted`` (witness_ok + kernel_decides_linked) reachable.

The fix is one structural guard at the pre-REPL choke-point
(``server.lean_soundness.scan_snippet``): reject the syntactic ENTRY POINTS
to elaboration-time code execution (``#eval`` / ``run_cmd`` / ``elab`` /
``macro`` / ``initialize`` / …) and the kernel-check-disabling options
(``debug.skip*``). Because the snippet is rejected BEFORE the REPL runs,
every downstream award predicate fails closed automatically.

The ``TestScanSnippetMetaGuard`` / ``TestHandlerRejectsMetaBypass`` classes
are pure (no Lean toolchain) and fail at 59f9d4d (the guard did not exist),
pass after the fix. ``TestMetaBypassLiveRepl`` is the gated end-to-end
mirror of ``_pipeline/.../repros/r2_meta_bypass_ATTACK.py`` and additionally
pins the negative control (a real true theorem still earns its award — the
guard does not over-reject and the oracle is live).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from server.config import Config
from server.handlers.lean_verify import handle_lean_verify
from server.kat import witness_ok
from server.lean_repl import LeanRepl
from server.lean_soundness import (
    _META_REJECT_KEYWORDS,
    formal_award_ok,
    kernel_decides_linked,
    scan_snippet,
)
from server.tools import reset_resources_for_tests, set_resources

# The canonical attack snippet (byte-identical to the finding's repro).
ATTACK_SNIPPET = (
    "import Lean\n"
    "open Lean in\n"
    "run_cmd do\n"
    "  let decl := Declaration.thmDecl {\n"
    "    name := `fake_false, levelParams := [],\n"
    "    type := .const ``False [],\n"
    "    value := .const ``True.intro [] }\n"
    "  let env <- getEnv\n"
    "  match env.addDeclCore 0 decl none false with\n"
    "  | .ok env' => setEnv env'\n"
    "  | .error _ => logError \"addDeclCore failed\"\n"
    "theorem attack_false : False := fake_false"
)


# ===========================================================================
# Pure guard tests — no Lean toolchain; run in the default suite.
# ===========================================================================


class TestScanSnippetMetaGuard:
    def test_canonical_attack_rejected(self):
        scan = scan_snippet(ATTACK_SNIPPET)
        assert scan.rejected
        # The run_cmd entry point is the load-bearing catch; addDeclCore is
        # the defense-in-depth belt.
        assert "run_cmd" in scan.rejected_keywords

    @pytest.mark.parametrize(
        ("label", "snippet"),
        [
            # The meta-execution entry points — each reachable at the
            # command or tactic level, each able to run un-kernel-checked
            # code that mutates the environment.
            ("run_cmd", "run_cmd do pure ()\ntheorem t : False := fake"),
            ("run_elab", "run_elab do pure ()\ntheorem t : False := fake"),
            ("run_tac", "theorem t : False := by run_tac (do pure ())"),
            ("#eval", "#eval (1 : Nat)\ntheorem t : False := fake"),
            ("elab", 'elab "foo" : command => pure ()'),
            ("elab_rules", "elab_rules : command | `(foo) => pure ()"),
            ("macro", 'macro "foo" : term => `(0)'),
            ("macro_rules", "macro_rules | `(foo) => `(0)"),
            ("syntax", 'syntax "foo" : command'),
            ("initialize", "initialize x : Nat <- pure 0"),
            ("builtin_initialize", "builtin_initialize x : Nat <- pure 0"),
            # Kernel-check-disabling options.
            (
                "debug.skipKernelTC",
                "set_option debug.skipKernelTC true\n"
                "theorem t : False := fun h => h",
            ),
            (
                "debug.skipProofs",
                "set_option debug.skipProofs true in\ntheorem t : True := trivial",
            ),
            # Defense-in-depth: the non-checking add primitives by name.
            (
                "addDeclCore-transitive",
                # No `import Lean`: Mathlib brings the whole Lean meta API
                # into scope, so blocking imports would NOT close the class —
                # the run_cmd entry point is what catches it.
                "run_cmd do\n  let env <- Lean.getEnv\n"
                "  match env.addDeclCore 0 d none false with\n"
                "  | _ => pure ()\n"
                "theorem t : False := fake",
            ),
            (
                "addDeclWithoutChecking",
                "run_elab Lean.addDeclWithoutChecking d",
            ),
        ],
    )
    def test_meta_construct_rejected(self, label, snippet):
        scan = scan_snippet(snippet)
        assert scan.rejected, f"{label!r} must be rejected by the meta guard"

    @pytest.mark.parametrize(
        "snippet",
        [
            "theorem t : 1 + 1 = 2 := rfl",
            "theorem t : 2 + 2 = 4 := by norm_num",
            "example (a b : Nat) : a * b = b * a := by simp [Nat.mul_comm]",
            "example : ¬ Nat.Prime 4 := by decide",
            # native_decide/unsafe/partial are FLAGGED, not rejected.
            "theorem t : 2 + 2 = 4 := by native_decide",
            # deriving with a built-in handler is safe (no meta execution).
            "structure P where\n  x : Nat\nderiving Repr",
            # word-boundary: 'axiomatic'/'opaquely' (substrings of the
            # banned words, not the words themselves) must not trip the guard.
            "-- axiomatic development, opaquely named\n"
            "theorem t : True := trivial",
            # the kernel_check_snippet linkage form is a clean proof + example.
            "theorem t : True := trivial\nexample : True := @t",
        ],
    )
    def test_legit_proof_not_rejected(self, snippet):
        scan = scan_snippet(snippet)
        assert not scan.rejected, (
            f"legitimate proof must NOT be rejected: {snippet!r} "
            f"(rejected={scan.rejected_keywords})"
        )

    def test_labels_are_schema_enum_pinned(self):
        """Every label the meta guard can emit must be in the
        lean_verify_result.json rejected_keywords enum (else the rejected
        envelope fails schema conformance)."""
        schema_path = (
            Path(__file__).resolve().parents[1]
            / "server"
            / "schemas"
            / "lean_verify_result.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        enum = set(
            schema["properties"]["soundness"]["properties"][
                "rejected_keywords"
            ]["items"]["enum"]
        )
        missing = set(_META_REJECT_KEYWORDS) - enum
        assert not missing, f"meta labels absent from schema enum: {missing}"


class TestHandlerRejectsMetaBypass:
    """The FULL handler rejection path — exercised with the REPL disabled
    (the guard fires pre-REPL, so no toolchain is needed). Fails at 59f9d4d
    (which returns the 'unavailable'/'ok' envelope), passes after the fix.
    """

    def _handle(self, snippet: str) -> dict:
        class _Res:
            pass

        res = _Res()
        res.config = Config()  # enable_lean defaults off; lean_repl_dir None
        res.corpus_info = type("_CI", (), {"version": 1})()
        res.lean_repl = None
        set_resources(res)
        try:
            return asyncio.run(handle_lean_verify(snippet=snippet, mode="full"))
        finally:
            reset_resources_for_tests()

    def test_attack_rejected_and_all_predicates_deny(self):
        r = self._handle(ATTACK_SNIPPET)
        s = r.get("soundness") or {}
        assert r["status"] == "error"
        assert s["guard"] == "rejected"
        assert s["audit_status"] == "rejected"
        assert s["axiom_closure_ok"] is False
        # Every award predicate must fail closed.
        assert formal_award_ok(dict(r))[0] is False
        assert witness_ok(r) is False
        assert kernel_decides_linked(r) is False

    def test_linkage_form_also_rejected(self):
        # The orchestrator's kernel-linkage form
        # `example : False := @attack_false` appended to the attack is
        # likewise rejected (both lanes fail closed at the choke-point).
        linked = ATTACK_SNIPPET + "\nexample : False := @attack_false"
        r = self._handle(linked)
        assert r["status"] == "error"
        assert kernel_decides_linked(r) is False

    def test_rejected_envelope_is_schema_conformant(self):
        pytest.importorskip("jsonschema")
        from jsonschema import Draft7Validator

        schema_path = (
            Path(__file__).resolve().parents[1]
            / "server"
            / "schemas"
            / "lean_verify_result.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        r = self._handle(ATTACK_SNIPPET)
        # The envelope wraps the result under structuredContent-style keys;
        # validate the soundness sub-block's rejected_keywords are enum-legal.
        Draft7Validator(schema).validate(r)


# ===========================================================================
# Gated end-to-end — the real Lean/mathlib REPL (mirrors the finding repro).
# ===========================================================================

_LAKE_PATH = os.environ.get("ARXMCP_LAKE_PATH")
_REPL_DIR = os.environ.get("ARXMCP_LEAN_REPL_DIR")
_LEAN_AVAILABLE = bool(_LAKE_PATH and _REPL_DIR)
_HAS_MATHLIB = os.environ.get("ARXMCP_LEAN_REPL_HAS_MATHLIB") == "1"

_mathlib_skip = pytest.mark.skipif(
    not (_LEAN_AVAILABLE and _HAS_MATHLIB),
    reason=(
        "set ARXMCP_LAKE_PATH + ARXMCP_LEAN_REPL_DIR + "
        "ARXMCP_LEAN_REPL_HAS_MATHLIB=1 for the mathlib meta-bypass test"
    ),
)

_PREWARM_IMPORTS = ("Mathlib.Tactic",)
_PREWARM_TIMEOUT_S = 300.0


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module", autouse=True)
def _prewarm_oleans():
    if not (_LEAN_AVAILABLE and _HAS_MATHLIB):
        yield
        return

    async def _go():
        repl = await LeanRepl.spawn(lake_path=_LAKE_PATH, repl_dir=_REPL_DIR)
        try:
            cmd = "\n".join(f"import {m}" for m in _PREWARM_IMPORTS)
            await repl.query(
                {"cmd": f"{cmd}\n#eval 1"}, timeout=_PREWARM_TIMEOUT_S
            )
        finally:
            await repl.close()

    _run(_go())
    yield


class _FakeCorpusInfo:
    version = 1


async def _with_real_repl(coro_fn):
    repl = await LeanRepl.spawn(lake_path=_LAKE_PATH, repl_dir=_REPL_DIR)
    cfg = Config(
        result_byte_cap=256 * 1024,
        enable_lean=True,
        lake_path=Path(_LAKE_PATH),
        lean_repl_dir=Path(_REPL_DIR),
    )

    class _FakeResources:
        pass

    fake = _FakeResources()
    fake.config = cfg
    fake.corpus_info = _FakeCorpusInfo()
    fake.lean_repl = repl
    set_resources(fake)
    try:
        return await coro_fn()
    finally:
        try:
            if fake.lean_repl is not None:
                await fake.lean_repl.close()
            if fake.lean_repl is not repl:
                await repl.close()
        finally:
            reset_resources_for_tests()


@_mathlib_skip
class TestMetaBypassLiveRepl:
    def test_attack_denied_end_to_end(self):
        async def _go():
            r = await handle_lean_verify(snippet=ATTACK_SNIPPET, mode="full")
            link = await handle_lean_verify(
                snippet=ATTACK_SNIPPET + "\nexample : False := @attack_false",
                mode="full",
            )
            return r, link

        r, link = _run(_with_real_repl(_go))
        s = r.get("soundness") or {}
        # The False-typed theorem must NOT verify clean any longer.
        assert r["status"] == "error"
        assert s["guard"] == "rejected"
        assert s["axiom_closure_ok"] is False
        assert formal_award_ok(dict(r))[0] is False  # no false proven-formal
        assert witness_ok(r) is False  # no false refuted (soundness half)
        assert kernel_decides_linked(r) is False
        assert kernel_decides_linked(link) is False  # no false refuted (link)

    def test_oracle_live_true_theorem_still_awards(self):
        """Negative control: the guard does not over-reject and the oracle
        is live — a genuinely true theorem still earns proven-formal."""

        async def _go():
            return await handle_lean_verify(
                snippet="theorem mb_true : 1 + 1 = 2 := by norm_num",
                imports=list(_PREWARM_IMPORTS),
                mode="full",
            )

        r = _run(_with_real_repl(_go))
        s = r.get("soundness") or {}
        assert r["status"] == "ok"
        assert s["guard"] == "passed"
        assert s["axiom_closure_ok"] is True
        assert formal_award_ok(dict(r))[0] is True

    def test_false_goal_still_errors(self):
        """The unrelated-false control (a plain false goal, no meta trick)
        errors at the elaborator — the oracle rejects false goals directly,
        not only via the meta guard."""

        async def _go():
            return await handle_lean_verify(
                snippet="example (a b : Nat) : a * b = b * a := by simp",
                imports=list(_PREWARM_IMPORTS),
                mode="full",
            )

        r = _run(_with_real_repl(_go))
        assert r["status"] == "error"
        assert formal_award_ok(dict(r))[0] is False
