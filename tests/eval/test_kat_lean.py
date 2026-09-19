"""KAT formal-lane integration against the REAL Lean/mathlib REPL
(stage2/arx-d2 — WS-D D-4 over D-2; AC-D.1/AC-D.2/AC-D.3/AC-D.8).

Opt-in via the house ``requires_lean_repl`` discipline:
``ARXMCP_LAKE_PATH`` + ``ARXMCP_LEAN_REPL_DIR`` for the kernel-only
tier; additionally ``ARXMCP_LEAN_REPL_HAS_MATHLIB=1`` for the tests
that import mathlib (the D-1 toolchain at
``_toolchains/mathlib-repl/project`` provides both).

Cold-cache discipline (D-1 lesson): the first heavy mathlib import of
a session can exceed the handler's 30 s budget, so an autouse
module fixture pre-warms the olean closure through a raw
``LeanRepl.query`` with a generous timeout before any handler-level
test runs.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from server.config import Config
from server.handlers.lean_verify import handle_lean_verify
from server.kat import (
    FALSE_MUST_REJECT,
    OPEN_MUST_ABSTAIN,
    TRUE_KNOWN_FORMAL,
    KatEscalation,
    entry_index,
    evaluate_run,
    formal_verdict,
    load_kat_fixture,
    raise_if_escalated,
    sample_controls,
    witness_ok,
)
from server.lean_repl import LeanRepl
from server.lean_soundness import (
    ALLOWED_AXIOMS,
    formal_award_ok,
    kernel_check_snippet,
    kernel_decides_linked,
    kernel_statement_for_snippet,
)
from server.lean_soundness import (
    extract_decl_names as _extract_decl_names,
)
from server.proving.verdict_linkage import award_linked_verdict
from server.tools import reset_resources_for_tests, set_resources

_LAKE_PATH = os.environ.get("ARXMCP_LAKE_PATH")
_REPL_DIR = os.environ.get("ARXMCP_LEAN_REPL_DIR")
_LEAN_AVAILABLE = bool(_LAKE_PATH and _REPL_DIR)
_HAS_MATHLIB = os.environ.get("ARXMCP_LEAN_REPL_HAS_MATHLIB") == "1"

_lean_skip = pytest.mark.skipif(
    not _LEAN_AVAILABLE,
    reason="set ARXMCP_LAKE_PATH + ARXMCP_LEAN_REPL_DIR for the real Lean REPL",
)
_mathlib_skip = pytest.mark.skipif(
    not (_LEAN_AVAILABLE and _HAS_MATHLIB),
    reason=(
        "set ARXMCP_LEAN_REPL_HAS_MATHLIB=1 (plus the REPL env vars) to run "
        "the mathlib-lane KAT tests"
    ),
)

#: Union of the mathlib modules used by the fixture snippets exercised
#: here — pre-warmed once per module (cold Analysis-tower imports can
#: exceed the 30 s handler budget; measured in the D-1 spike).
_PREWARM_IMPORTS = (
    "Mathlib.NumberTheory.Real.Irrational",
    "Mathlib.Tactic",
    "Mathlib.GroupTheory.Perm.Basic",
    "Mathlib.Data.Nat.Prime.Infinite",
    "Mathlib.Data.Nat.Prime.Basic",
)
_PREWARM_TIMEOUT_S = 300.0


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module", autouse=True)
def _prewarm_oleans():
    """Warm the olean closure once so per-test handler calls stay
    inside the 30 s budget. Raw REPL query — the handler timeout does
    not apply here."""
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
    """Spawn a real REPL, attach Resources, run ``coro_fn()``, clean up.

    Per-test spawn (not module-scoped): asyncio primitives inside
    LeanRepl bind to the running loop, and each test runs its own
    ``asyncio.run`` loop.
    """
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
            # The handler may have respawned the REPL; close whichever
            # instance Resources currently holds, then the original.
            current = fake.lean_repl
            if current is not None:
                await current.close()
            if current is not repl:
                await repl.close()
        finally:
            reset_resources_for_tests()


def _verify(snippet: str, imports: list[str]) -> dict:
    async def _go():
        return await handle_lean_verify(snippet=snippet, imports=imports)

    return _run(_with_real_repl(_go))


@pytest.fixture(scope="module")
def fixture():
    return load_kat_fixture()


# ===========================================================================
# Kernel-only tier (no mathlib required)
# ===========================================================================


@_lean_skip
@pytest.mark.requires_lean_repl
class TestKernelOnlyTier:
    def test_positive_control_kernel_only(self, fixture):
        """kat-tf-05 (1+1=2) must award proven-formal against the base
        Lean kernel — the mission's no-mathlib fallback case. The
        audit reports an empty closure ⊆ the allowed set."""
        entry = entry_index(fixture)["kat-tf-05"]
        result = _verify(
            entry["formal"]["snippet"], entry["formal"]["imports"]
        )
        assert result["status"] == "ok", result
        s = result["soundness"]
        assert s["audit_status"] == "ok"
        assert s["axiom_closure"] == []
        assert s["axiom_closure_ok"] is True
        assert formal_verdict(result) == "proven-formal"

    def test_ac_d1_axiom_canary_never_awards(self):
        """AC-D.1 (permanent regression vector): `axiom cheat : <goal>`
        + closing the theorem with it. The hardened handler rejects it
        before elaboration; the award is denied; ALSO covers the
        AC-D.2 negative-control shape (custom axiom mixed with
        Classical.choice reasoning)."""
        result = _verify(
            "axiom cheat : (1 : Nat) + 1 = 3\n"
            "theorem kat_canary : (1 : Nat) + 1 = 3 := cheat",
            [],
        )
        assert result["status"] == "error"
        assert result["soundness"]["guard"] == "rejected"
        ok, reasons = formal_award_ok(result)
        assert not ok and reasons
        assert formal_verdict(result) == "abstained"

    def test_ac_d3_transcript_replayability(self, fixture):
        """AC-D.3: two runs of the same snippet produce identical
        transcript hashes, and every result records the toolchain."""
        entry = entry_index(fixture)["kat-tf-05"]
        r1 = _verify(entry["formal"]["snippet"], entry["formal"]["imports"])
        r2 = _verify(entry["formal"]["snippet"], entry["formal"]["imports"])
        assert (
            r1["provenance"]["transcript_sha256"]
            == r2["provenance"]["transcript_sha256"]
        )
        toolchain_file = Path(_REPL_DIR) / "lean-toolchain"
        if toolchain_file.is_file():
            assert r1["provenance"]["lean_toolchain"] == (
                toolchain_file.read_text(encoding="utf-8").strip()
            )


# ===========================================================================
# Mathlib tier
# ===========================================================================


@_mathlib_skip
@pytest.mark.requires_lean_repl
class TestMathlibFormalLane:
    def test_ac_d2_positive_control_sqrt2(self, fixture):
        """AC-D.2 positive control: a clean mathlib proof
        (irrational_sqrt_two) passes the axiom audit and awards
        proven-formal; AC-D.3: the result records toolchain AND the
        pinned mathlib revision."""
        entry = entry_index(fixture)["kat-tf-01"]
        result = _verify(
            entry["formal"]["snippet"], entry["formal"]["imports"]
        )
        assert result["status"] == "ok", result
        s = result["soundness"]
        assert s["audit_status"] == "ok"
        assert set(s["axiom_closure"]) <= ALLOWED_AXIOMS
        assert s["axiom_closure_ok"] is True
        assert formal_verdict(result) == "proven-formal"
        assert result["provenance"]["lean_toolchain"] is not None
        assert result["provenance"]["mathlib_rev"] is not None

    def test_native_decide_denied_by_real_closure(self):
        """The audit backstop against a smuggle that evades no textual
        guard: `native_decide` verifies clean at kernel level but its
        compiler axiom enters the real closure — award denied on BOTH
        the flag and the closure."""
        result = _verify(
            "theorem kat_nd : 2 + 2 = 4 := by native_decide", []
        )
        assert result["status"] == "ok"
        s = result["soundness"]
        assert "native_decide" in s["flags"]
        assert s["axiom_closure_ok"] is False
        assert s["axiom_closure"], "closure should name the compiler axiom"
        assert formal_verdict(result) == "abstained"

    def test_false_witness_trio_refutes(self, fixture, tmp_path):
        """The acceptance test-plan's first FALSE trio (order-6 group,
        n²+n+41, Fermat F₅): each counterexample witness is kernel-
        accepted and soundness-clean ⇒ verdict `refuted`; the scored
        run is reportable with zero red alarms."""
        index = entry_index(fixture)
        verdicts: dict[str, str] = {}
        for kat_id in ("kat-fm-01", "kat-fm-02", "kat-fm-03"):
            witness = index[kat_id]["counterexample"]["witness_lean"]
            result = _verify(witness["snippet"], witness["imports"])
            assert result["status"] == "ok", (kat_id, result)
            assert witness_ok(result), (kat_id, result["soundness"])
            verdicts[kat_id] = "refuted"
        report = evaluate_run(fixture, verdicts, artifact_dir=tmp_path)
        assert report.reportable is True
        assert report.red_alarms == []

    def test_false_trio_still_refutes_under_verdict_linkage_chokepoint(
        self, fixture
    ):
        """Durable P1 KERNEL-DECIDES fix on the REAL kernel: each FALSE-trio
        witness is kernel-verified, and THE KERNEL decides the refutation
        linkage — the skeptic-lane check
        ``example : <discharges.proposition> := @<witness_decl>`` is run on
        the real REPL, and its boolean result (``kernel_decides_linked``) is
        recorded as ``proves_declared_proposition``. The choke-point requires
        that True (PLUS refutes_claim=true), so the confident `refuted`
        STANDS. This proves (a) the kernel-decides model does not break the
        acceptance suite's FALSE trio — kat-fm-03 proves the auxiliary
        ``2^32+1 = 641*6700417``, and its `discharges.proposition` is exactly
        that auxiliary fact, which the kernel accepts; and (b) the fixture's
        declared propositions, now written in NATURAL author syntax again
        (the brittleness reversion — `∃ a b : Equiv.Perm (Fin 3), …` for
        kat-fm-01, `¬ Nat.Prime …` with a space for kat-fm-02), LINK because
        THE KERNEL decides definitional equality, not a pretty-print string
        compare."""
        index = entry_index(fixture)
        for kat_id in ("kat-fm-01", "kat-fm-02", "kat-fm-03"):
            witness = index[kat_id]["counterexample"]["witness_lean"]
            snippet, imports = witness["snippet"], witness["imports"]
            result = _verify(snippet, imports)
            assert witness_ok(result), (kat_id, result["soundness"])
            # KERNEL-reported proved statement — audit/display only now.
            proved = kernel_statement_for_snippet(
                snippet, result.get("kernel_statements")
            )
            # THE KERNEL decides linkage: run `example : <declared> := @<decl>`
            # on the real REPL and read kernel_decides_linked (the exact
            # mechanism skeptic.run_skeptic_lane uses).
            declared = witness["discharges"]["proposition"]
            decl = _extract_decl_names(snippet)[0]
            check_result = _verify(kernel_check_snippet(snippet, declared, decl), imports)
            proves_declared = kernel_decides_linked(check_result)
            assert proves_declared is True, (
                kat_id,
                "the NATURAL-syntax declared proposition must be defeq to the "
                "witness's kernel type (brittleness-gone)",
                check_result.get("status"),
                [m for m in check_result.get("messages", []) if m.get("severity") == "error"],
            )
            cx = {
                "source": "lean-witness",
                "check": f"{kat_id}-witness",
                "kernel_confirmed": True,
                "proved_statement_lean": proved,
                "proves_declared_proposition": proves_declared,
                "discharges": witness["discharges"],
            }
            out = award_linked_verdict("refuted", "high", counterexample=cx)
            assert out.verdict == "refuted", (kat_id, proved, out.reasons)
            assert out.linked is True, (kat_id, proved, out.reasons)

    def test_bogus_unrelated_witness_capped_under_chokepoint(self, fixture):
        """The adversarial mirror on the REAL kernel: a kernel-clean
        witness proving an UNRELATED true fact (¬Prime 4) against a TRUE
        claim, carried with NO declared discharged proposition, is CAPPED
        to abstained by the choke-point — it does NOT earn a confident
        refuted (the exact hole round 2's escalation-only net left open
        for real known_truth=null tasks)."""
        bogus_snippet = "theorem bogus : ¬ Nat.Prime 4 := by decide"
        result = _verify(bogus_snippet, ["Mathlib.Tactic"])
        assert witness_ok(result), result.get("soundness")
        cx = {
            "source": "lean-witness",
            "check": "bogus-not-prime-4",
            "kernel_confirmed": True,
            # KERNEL-reported statement (durable P1) — present, but there is
            # NO `discharges`, so the choke-point caps regardless.
            "proved_statement_lean": kernel_statement_for_snippet(
                bogus_snippet, result.get("kernel_statements")
            ),
            # NO `discharges` — never tied to a claim refutation obligation.
        }
        out = award_linked_verdict("refuted", "high", counterexample=cx)
        assert out.verdict == "abstained"
        assert out.linked is False
        assert any("declared no discharged proposition" in r for r in out.reasons)

    def test_per_run_controls_end_to_end(self, fixture, tmp_path):
        """AC-D.8 shape, driven with real formal evidence: sample the
        control subset, resolve the TRUE-formal control through the
        real REPL, resolve FALSE/OPEN controls honestly (witness ⇒
        refuted; none ⇒ abstained), and score. The run must be
        reportable; the halt primitive must pass it through."""
        controls = sample_controls(fixture, seed=20260704)
        verdicts: dict[str, str] = {}
        for entry in controls:
            cls = entry["class"]
            if cls == TRUE_KNOWN_FORMAL:
                formal = entry.get("formal") or {}
                if formal.get("snippet"):
                    result = _verify(formal["snippet"], formal["imports"])
                    verdicts[entry["id"]] = formal_verdict(result)
                else:
                    verdicts[entry["id"]] = "abstained"
            elif cls == FALSE_MUST_REJECT:
                witness = (entry.get("counterexample") or {}).get(
                    "witness_lean"
                )
                if witness:
                    result = _verify(witness["snippet"], witness["imports"])
                    verdicts[entry["id"]] = (
                        "refuted" if witness_ok(result) else "abstained"
                    )
                else:
                    verdicts[entry["id"]] = "abstained"
            elif cls == OPEN_MUST_ABSTAIN:
                verdicts[entry["id"]] = "abstained"
        report = raise_if_escalated(
            evaluate_run(fixture, verdicts, artifact_dir=tmp_path)
        )
        assert report.reportable is True, report.to_dict()
        # Control-run report prints the abstention rate (AC-D.8).
        assert 0.0 <= report.abstention_rate <= 1.0

    def test_red_alarm_halt_on_forced_false_accept(self, fixture, tmp_path):
        """Simulated worst case: the orchestrator (wrongly) awards
        proven-formal on the n²+n+41 control. The harness must halt
        with the loud artifact — this is the wire between D-4 and any
        future D-6 orchestrator, pinned here so it cannot regress."""
        report = evaluate_run(
            fixture,
            {"kat-fm-02": "proven-formal"},
            artifact_dir=tmp_path,
            run_id="forced-false-accept",
        )
        assert report.escalated
        artifact = tmp_path / "KAT-ESCALATION-forced-false-accept.json"
        assert artifact.is_file()
        with pytest.raises(KatEscalation):
            raise_if_escalated(report)
