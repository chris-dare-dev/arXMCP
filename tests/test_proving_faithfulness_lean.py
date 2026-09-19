"""D-3 faithfulness gate against the REAL Lean/mathlib REPL
(stage2/arx-d3 — WS-D; AC-D.5/AC-D.6 live half).

Opt-in via the house ``requires_lean_repl`` discipline (the
``tests/test_proving_skeptic_lean.py`` Resources/prewarm pattern):
``ARXMCP_LAKE_PATH`` + ``ARXMCP_LEAN_REPL_DIR``, plus
``ARXMCP_LEAN_REPL_HAS_MATHLIB=1`` for the mathlib tier.

The AC-D.6 misformalization-detection drill lives here: ≥ 3 seeded
mutation pairs (quantifier swap, strict-vs-non-strict, hypothesis
dropped) where one channel formalizes the claim correctly and the
other channel's output is a mutant. In every case the mutant changes
the truth conditions, so the broken implication direction is
UNPROVABLE — the gate fails no matter how strong the tactic portfolio
is (fail-closed by the Lean kernel itself, not by tactic luck).

The positive path is the even+even ↔ mod-2 pair: two genuinely
different formalizations of the same claim, proved equivalent by the
kernel through the default portfolio (live-probed on the D-1
toolchain), then carried end-to-end: real formal proof of the claim,
operator sign-off, ``proven-formal`` award, schema-valid publishable
EvidenceBundle.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from server.config import Config
from server.handlers.lean_verify import handle_lean_verify
from server.lean_repl import LeanRepl
from server.lean_soundness import (
    extract_decl_names,
    kernel_check_snippet,
    kernel_decides_linked,
)
from server.proving.contracts import (
    EVIDENCE_BUNDLE_ARTIFACT,
    EVIDENCE_BUNDLE_VERSION,
    ContractValidationError,
    load_example,
    validate_evidence_bundle,
    wrap_payload,
)
from server.proving.faithfulness import (
    BackTranslationRecord,
    FormalizationRecord,
    SkepticDiffRecord,
    award_statement_verdict,
    record_human_signoff,
    run_faithfulness_gate,
)
from server.tools import reset_resources_for_tests, set_resources

_LAKE_PATH = os.environ.get("ARXMCP_LAKE_PATH")
_REPL_DIR = os.environ.get("ARXMCP_LEAN_REPL_DIR")
_LEAN_AVAILABLE = bool(_LAKE_PATH and _REPL_DIR)
_HAS_MATHLIB = os.environ.get("ARXMCP_LEAN_REPL_HAS_MATHLIB") == "1"

_mathlib_skip = pytest.mark.skipif(
    not (_LEAN_AVAILABLE and _HAS_MATHLIB),
    reason=(
        "set ARXMCP_LAKE_PATH + ARXMCP_LEAN_REPL_DIR + "
        "ARXMCP_LEAN_REPL_HAS_MATHLIB=1 for the mathlib faithfulness-gate tests"
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
            await repl.query({"cmd": f"{cmd}\n#eval 1"}, timeout=_PREWARM_TIMEOUT_S)
        finally:
            await repl.close()

    _run(_go())
    yield


class _FakeCorpusInfo:
    version = 1


async def _with_real_repl(coro_fn):
    """Spawn a real REPL, attach Resources, run ``coro_fn()``, clean up
    (the ``tests/test_proving_skeptic_lean.py`` pattern)."""
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
            current = fake.lean_repl
            if current is not None:
                await current.close()
            if current is not repl:
                await repl.close()
        finally:
            reset_resources_for_tests()


async def _verifier(snippet: str, imports: list[str]) -> dict:
    return await handle_lean_verify(snippet=snippet, imports=imports)


async def _kernel_proves_formalization(
    proof_snippet: str, formalizations: list[str], imports: list[str]
) -> bool:
    """Ask THE KERNEL (on the real REPL) whether ``proof_snippet``'s
    principal declaration proves any of ``formalizations`` — the exact
    per-award check ``orchestrator._kernel_check_proves_formalization``
    runs (durable P1 kernel-decides fix). Returns the boolean the pure
    award rule consumes; False (fail-closed) when the snippet has no
    name-extractable decl or no formalization type-checks."""
    decls = extract_decl_names(proof_snippet)
    if not decls:
        return False
    decl = decls[0]
    for target in formalizations:
        result = await handle_lean_verify(
            snippet=kernel_check_snippet(proof_snippet, target, decl),
            imports=imports,
        )
        if kernel_decides_linked(result):
            return True
    return False


_IMPORTS = ("Mathlib.Tactic",)

#: The positive pair: two genuinely different formalizations of "the
#: sum of two even naturals is even".
_PROP_EVEN = "∀ m n : Nat, Even m → Even n → Even (m + n)"
_PROP_MOD2 = "∀ a b : Nat, a % 2 = 0 → b % 2 = 0 → (a + b) % 2 = 0"


def _form(channel: str, statement: str, session: str) -> FormalizationRecord:
    return FormalizationRecord(
        channel=channel,
        statement_lean=statement,
        producer=f"autoformalizer-{channel.lower()}",
        session_id=session,
        imports=_IMPORTS,
    )


def _bt_for(statement_lean: str, channel: str, statement_en: str) -> BackTranslationRecord:
    return BackTranslationRecord(
        statement_en=statement_en,
        translator="blind-translator",
        session_id="sess-bt",
        source_channel=channel,
        rendered_statement_lean=statement_lean,
        translator_saw_original=False,
    )


def _run_gate_live(a: str, b: str, *, bt=None, sd=None):
    async def _go():
        return await run_faithfulness_gate(
            statement_latex="live-gate test claim",
            formalization_a=_form("A", a, "sess-a"),
            formalization_b=_form("B", b, "sess-b"),
            back_translation=bt or _bt_for(a, "A", "blind rendering of channel A"),
            skeptic_diff=sd or SkepticDiffRecord(skeptic="statement-skeptic", verdict="match"),
            lean_verify=_verifier,
        )

    return _run(_with_real_repl(_go))


@_mathlib_skip
@pytest.mark.requires_lean_repl
class TestRealEquivalencePositive:
    def test_alpha_renamed_pair_establishes(self):
        result = _run_gate_live("∀ n : Nat, n + 0 = n", "∀ k : Nat, k + 0 = k")
        assert result.gate_ok is True, result.gate_reasons
        equiv = result.block["equivalence"]
        assert equiv["method"] == "lean-iff"
        assert equiv["forward"]["transcript_sha256"]
        assert equiv["backward"]["transcript_sha256"]

    def test_even_vs_mod2_pair_establishes(self):
        """Two genuinely different formalizations of the same claim,
        proved equivalent by the kernel via the default portfolio."""
        result = _run_gate_live(_PROP_EVEN, _PROP_MOD2)
        assert result.gate_ok is True, result.gate_reasons
        assert result.block["equivalence"]["established"] is True
        assert result.block["budget"]["lean_queries"] == 2


@_mathlib_skip
@pytest.mark.requires_lean_repl
class TestMisformalizationDrill:
    """AC-D.6: ≥ 3 seeded mutation pairs; the gate must flag each. The
    kernel guarantees the catch — the mutated implication direction is
    mathematically unprovable."""

    @pytest.mark.parametrize(
        ("name", "correct", "mutant"),
        [
            (
                "quantifier-swap",
                "∀ n : Nat, ∃ m : Nat, n < m",
                "∃ m : Nat, ∀ n : Nat, n < m",
            ),
            (
                "strict-vs-non-strict",
                "∀ n : Nat, 1 ≤ n → n ≤ n ^ 2",
                "∀ n : Nat, 1 ≤ n → n < n ^ 2",
            ),
            (
                "hypothesis-dropped",
                "∀ n : Nat, 2 ≤ n → 2 ≤ n ^ 2",
                "∀ n : Nat, 2 ≤ n ^ 2",
            ),
        ],
    )
    def test_seeded_mutant_is_flagged(self, name, correct, mutant):
        result = _run_gate_live(correct, mutant)
        assert result.gate_ok is False, f"{name}: mutant slipped through the gate"
        assert result.block["equivalence"]["established"] is False
        assert any("direction not proved" in r for r in result.gate_reasons), (
            name,
            result.gate_reasons,
        )
        # The award rule caps a kernel-proved claim carried by this
        # failed record (AC-D.5).
        block = result.to_faithfulness_block()
        verdict, _ = award_statement_verdict(
            _SOUND_FORMAL_STUB, block, publishable=False
        )
        assert verdict == "plausible-unverified"


#: A minimal award-clean formal-lane stub for drill award checks (the
#: real formal result is exercised in the end-to-end test below).
_SOUND_FORMAL_STUB = {
    "status": "ok",
    "mode": "full",
    "compilation_success": True,
    "soundness": {
        "guard": "passed",
        "flags": [],
        "audit_status": "ok",
        "audited_decls": ["stub"],
        "axiom_closure": [],
        "axiom_closure_ok": True,
    },
    "provenance": {"transcript_sha256": "ee" * 32},
}


@_mathlib_skip
@pytest.mark.requires_lean_repl
class TestEndToEndProvenFormal:
    def test_gate_plus_real_proof_awards_and_bundles(self):
        """The L1 gate's own golden path: live equivalence + a REAL
        kernel-checked proof of the claim + operator sign-off →
        proven-formal → schema-valid publishable EvidenceBundle."""

        proof_snippet = (
            "theorem even_add_even : "
            f"{_PROP_EVEN} := by\n"
            "  intro m n hm hn\n"
            "  exact hm.add hn"
        )

        async def _go():
            gate = await run_faithfulness_gate(
                statement_latex="The sum of two even natural numbers is even.",
                statement_nl="The sum of two even natural numbers is even.",
                formalization_a=_form("A", _PROP_EVEN, "sess-a"),
                formalization_b=_form("B", _PROP_MOD2, "sess-b"),
                back_translation=_bt_for(
                    _PROP_EVEN,
                    "A",
                    "For all natural numbers m and n, if m is even and n is "
                    "even then m + n is even.",
                ),
                skeptic_diff=SkepticDiffRecord(
                    skeptic="statement-skeptic", verdict="match"
                ),
                lean_verify=_verifier,
            )
            proof = await handle_lean_verify(
                snippet=proof_snippet,
                imports=list(_IMPORTS),
            )
            # THE KERNEL decides the formalization⇔proof link (durable P1):
            # `example : <_PROP_EVEN> := @even_add_even` type-checks (the
            # proof proves formalization A).
            proves = await _kernel_proves_formalization(
                proof_snippet, [_PROP_EVEN, _PROP_MOD2], list(_IMPORTS)
            )
            return gate, proof, proves

        gate, proof, proves = _run(_with_real_repl(_go))
        assert gate.gate_ok is True, gate.gate_reasons
        assert proves is True  # kernel confirmed the proof proves formalization A

        # The gate itself emitted an unsigned checkbox; the operator
        # signs the reviewed record.
        assert gate.block["human_signoff"]["signed"] is False
        signed = record_human_signoff(
            gate.to_faithfulness_block(),
            by="chris.dare",
            note="live end-to-end test sign-off",
            i_am_a_human_operator=True,
        )

        # The kernel confirmed the proof proves formalization A; the
        # statement linkage (findings #1/#2) is satisfied.
        verdict, reasons = award_statement_verdict(
            proof, signed, publishable=True, proves_formalization=proves
        )
        assert verdict == "proven-formal", reasons

        substrate = load_example("evidence-bundle.v0.example.json")["bridge"]["substrate"]
        doc = wrap_payload(
            artifact=EVIDENCE_BUNDLE_ARTIFACT,
            version=EVIDENCE_BUNDLE_VERSION,
            producer="proving-orchestrator-v0",
            produced_at="2026-07-04T04:00:00Z",
            substrate=substrate,
            payload={
                "task_id": "even-add-even-live",
                "verdict": verdict,
                "publishable": True,
                "verdict_reasons": reasons,
                "formal": {
                    "status": proof.get("status"),
                    "mode": proof.get("mode"),
                    "compilation_success": proof.get("compilation_success"),
                    "soundness": proof.get("soundness"),
                    "provenance": proof.get("provenance"),
                },
                "faithfulness": signed,
                "cost": {
                    "wall_clock_s": gate.block["budget"]["wall_clock_s"],
                    "lean_queries": gate.block["budget"]["lean_queries"] + 1,
                    "cas_runs": 0,
                    "prover_cycles": 1,
                },
            },
        )
        validate_evidence_bundle(doc)

    def test_real_kernel_proof_of_unrelated_statement_caps(self):
        """findings #1/#2 on the REAL toolchain: a genuine kernel-clean
        proof of `1 + 1 = 2` — which passes formal_award_ok — carried by
        a complete, signed even-add faithfulness record must NOT award
        proven-formal. The proof is real; it just proves the wrong
        statement. This is the exact scenario the reviewer reproduced on
        lean4 v4.30.0-rc2/mathlib."""

        cheat_snippet = "theorem stage3_cheat : 1 + 1 = 2 := rfl"

        async def _go():
            gate = await run_faithfulness_gate(
                statement_latex="The sum of two even natural numbers is even.",
                statement_nl="The sum of two even natural numbers is even.",
                formalization_a=_form("A", _PROP_EVEN, "sess-a"),
                formalization_b=_form("B", _PROP_MOD2, "sess-b"),
                back_translation=_bt_for(
                    _PROP_EVEN, "A", "blind rendering of channel A"
                ),
                skeptic_diff=SkepticDiffRecord(
                    skeptic="statement-skeptic", verdict="match"
                ),
                lean_verify=_verifier,
            )
            # A REAL kernel-clean proof — of a DIFFERENT statement.
            cheat = await handle_lean_verify(
                snippet=cheat_snippet,
                imports=list(_IMPORTS),
            )
            # THE KERNEL denies the link: `example : <_PROP_EVEN> :=
            # @stage3_cheat` fails to type-check (1+1=2 is not defeq to
            # the even-add formalization), and likewise for B.
            proves = await _kernel_proves_formalization(
                cheat_snippet, [_PROP_EVEN, _PROP_MOD2], list(_IMPORTS)
            )
            return gate, cheat, proves

        gate, cheat, proves = _run(_with_real_repl(_go))
        assert gate.gate_ok is True, gate.gate_reasons
        assert proves is False  # kernel refused the unrelated proof
        # The cheat proof really is kernel-clean and award-ok on its own.
        from server.lean_soundness import formal_award_ok

        assert formal_award_ok(cheat)[0] is True, cheat.get("soundness")

        signed = record_human_signoff(
            gate.to_faithfulness_block(),
            by="chris.dare",
            i_am_a_human_operator=True,
        )
        # Award with the KERNEL's verdict on the formalization⇔proof link.
        verdict, reasons = award_statement_verdict(
            cheat, signed, publishable=True, proves_formalization=proves
        )
        assert verdict == "plausible-unverified", reasons
        assert any("statement linkage" in r for r in reasons)

    def test_real_kernel_vacuous_binder_proof_caps(self):
        """ROUND-3 proof-side class fix on the REAL toolchain (finding:
        vacuous-hypothesis binder). ``theorem attack (h : False) : <A> :=
        h.elim`` is genuinely kernel-clean and passes formal_award_ok —
        the kernel really proved the vacuously-true ``∀ (h : False), <A>``
        for ANY <A>. The OLD extractor returned the bare conclusion <A>,
        which matched the gate-checked formalization <A> and PASSED
        statement linkage → a confident, publishable proven-formal for a
        statement the kernel established NOTHING about (the reviewer
        reproduced this end-to-end with A = a FALSE claim). With binders
        reflected, the extraction carries ``∀ (h : False),`` and matches
        NEITHER formalization, so the award caps to plausible-unverified.
        Here A = the genuine even-add formalization; the point is the
        BINDER, not A's truth — the attack templates over any target."""

        attack_snippet = f"theorem attack (h : False) : {_PROP_EVEN} := h.elim"

        async def _go():
            gate = await run_faithfulness_gate(
                statement_latex="The sum of two even natural numbers is even.",
                statement_nl="The sum of two even natural numbers is even.",
                formalization_a=_form("A", _PROP_EVEN, "sess-a"),
                formalization_b=_form("B", _PROP_MOD2, "sess-b"),
                back_translation=_bt_for(
                    _PROP_EVEN, "A", "blind rendering of channel A"
                ),
                skeptic_diff=SkepticDiffRecord(
                    skeptic="statement-skeptic", verdict="match"
                ),
                lean_verify=_verifier,
            )
            # The vacuous-binder proof — REAL kernel-clean typecheck.
            attack = await handle_lean_verify(
                snippet=attack_snippet,
                imports=list(_IMPORTS),
            )
            # THE KERNEL decides: does `@attack` inhabit the bare <A>?
            proves = await _kernel_proves_formalization(
                attack_snippet, [_PROP_EVEN, _PROP_MOD2], list(_IMPORTS)
            )
            return gate, attack, proves

        gate, attack, proves = _run(_with_real_repl(_go))
        assert gate.gate_ok is True, gate.gate_reasons
        assert proves is False  # kernel refused the vacuous-binder proof
        from server.lean_soundness import formal_award_ok

        # The attack proof really is kernel-clean and award-ok on its own
        # (the vacuous `(h : False)` hypothesis is discharged by `h.elim`).
        assert formal_award_ok(attack)[0] is True, attack.get("soundness")

        signed = record_human_signoff(
            gate.to_faithfulness_block(),
            by="chris.dare",
            i_am_a_human_operator=True,
        )
        # THE KERNEL denies the link: `@attack` has type `False → <A>`
        # (the whole Π-telescope), which does NOT inhabit the bare `<A>` —
        # so `example : <A> := @attack` fails to type-check. A vacuous
        # generalization cannot pass as its conclusion (findings: vacuous-
        # hypothesis binder), decided by the kernel, not a string scan.
        verdict, reasons = award_statement_verdict(
            attack, signed, publishable=True, proves_formalization=proves
        )
        assert verdict == "plausible-unverified", reasons
        assert any("statement linkage" in r for r in reasons)

    def test_unsigned_gate_output_cannot_publish(self):
        """Automation stops here: the gate's own (unsigned) output can
        never ride a publishable proven-formal bundle — schema law."""
        result = _run_gate_live(_PROP_EVEN, _PROP_MOD2)
        assert result.gate_ok is True, result.gate_reasons
        unsigned = result.to_faithfulness_block()

        verdict, reasons = award_statement_verdict(
            _SOUND_FORMAL_STUB, unsigned, publishable=True
        )
        assert verdict == "plausible-unverified"
        assert any("checkbox" in r for r in reasons)

        substrate = load_example("evidence-bundle.v0.example.json")["bridge"]["substrate"]
        doc = wrap_payload(
            artifact=EVIDENCE_BUNDLE_ARTIFACT,
            version=EVIDENCE_BUNDLE_VERSION,
            producer="proving-orchestrator-v0",
            produced_at="2026-07-04T04:00:00Z",
            substrate=substrate,
            payload={
                "task_id": "even-add-even-live",
                "verdict": "proven-formal",
                "publishable": True,
                "faithfulness": unsigned,
            },
        )
        with pytest.raises(ContractValidationError):
            validate_evidence_bundle(doc)
