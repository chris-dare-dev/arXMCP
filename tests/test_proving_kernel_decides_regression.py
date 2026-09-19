"""Durable P1 kernel-decides-equality regression suite (the reproduced
CRITICAL false-accept, closed).

THE BUG (reproduced live on the D-1 mathlib REPL, Lean v4.30.0-rc2). Both
linkage sites compared a WHITESPACE-NORMALIZED STRING of the kernel
pretty-print vs the author target. Lean's delaborator ELIDES the
∃-binder type, so::

    ∃ x : ℝ, x * x = 2   (TRUE)   -> renders  ∃ x, x * x = 2
    ∃ x : ℚ, x * x = 2   (FALSE)  -> renders  ∃ x, x * x = 2

A kernel-clean proof/witness of the ℝ statement string-MATCHED a
gate-checked / declared ℚ formalization, earning a mismatched
``proven-formal`` / a confident ``refuted`` for a FALSE claim. The
convergence repro scripts are ``scratchpad/exploit_e2e.py`` (both sides,
pure functions), ``scratchpad/exploit_live.py`` (refutation, live REPL),
``scratchpad/both_kernel.py`` + ``rat_false.py`` (the collision + the ℚ
falsity). These tests ADAPT those repros into the suite.

THE FIX. THE KERNEL, not a string, decides: the proof/witness proves the
target IFF the kernel accepts ``example : <target> := @<decl>``. The
ℝ-proof does NOT inhabit the ℚ existential (``Type mismatch``), so the
collision is DENIED; a defeq author phrasing (``Nat``↔``ℕ``, reordered
binders) still LINKS.

**Fail-before / pass-after.** On the string-match HEAD ``99d2d7f`` the
collision GRANTED (``exploit_e2e.py`` prints ``proven-formal`` /
``refuted``); after the fix these tests assert DENY. They drive the REAL
production functions (``run_proving_pipeline`` / ``run_skeptic_lane`` /
``award_linked_verdict``) with an OFFLINE fake kernel whose accept/reject
behaviour matches the live REPL probed in ``scratchpad/mechanism_probe.py``
and ``scratchpad/handler_e2e_probe.py`` (the collision denied, defeq
linked, Nat/Int distinguished — verbatim). The GATED real-kernel form is
in the ``*_lean.py`` batteries.
"""

from __future__ import annotations

import asyncio
import re

from server.lean_soundness import kernel_check_snippet, kernel_decides_linked
from server.proving.contracts import (
    PROOF_TASK_ARTIFACT,
    PROOF_TASK_VERSION,
    load_example,
    validate_evidence_bundle,
    wrap_payload,
)
from server.proving.faithfulness import (
    BackTranslationRecord,
    FormalizationRecord,
    SkepticDiffRecord,
    normalize_lean,
    proof_statement_linked,
)
from server.proving.orchestrator import (
    ProofAttempt,
    RoleOutputs,
    run_proving_pipeline,
)
from server.proving.skeptic import run_skeptic_lane
from server.proving.verdict_linkage import (
    award_linked_verdict,
    refutation_statement_linked,
)


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# An OFFLINE fake KERNEL that models defeq exactly as the live REPL did.
# It answers plain snippets from a route table and, for a kernel-check
# command `<snippet>\nexample : <target> := @<decl>`, ACCEPTS iff the
# target is definitionally equal to the decl's real type — modelled here
# by a per-decl "defeq set" of accepted surface forms (the live REPL's
# behaviour, probed verbatim in scratchpad/mechanism_probe.py).
# ---------------------------------------------------------------------------

_KERNEL_CHECK_RE = re.compile(r"example\s*:\s*(?P<target>.+?)\s*:=\s*@(?P<decl>\S+)\s*$")


def _ok_env(decl: str = "d", kernel_stmt: str | None = None) -> dict:
    return {
        "status": "ok",
        "mode": "full",
        "compilation_success": True,
        "messages": [],
        "sorry_goals": [],
        "soundness": {
            "guard": "passed",
            "flags": [],
            "audit_status": "ok",
            "audited_decls": [decl],
            "axiom_closure": ["propext", "Classical.choice", "Quot.sound"],
            "axiom_closure_ok": True,
        },
        "kernel_statements": {decl: kernel_stmt} if kernel_stmt is not None else {},
        "provenance": {
            "lean_toolchain": "leanprover/lean4:v4.30.0-rc2",
            "mathlib_rev": "5450b53e5ddc",
            "transcript_sha256": "ab" * 32,
        },
    }


def _mismatch_env() -> dict:
    return {
        "status": "error",
        "mode": "full",
        "compilation_success": False,
        "messages": [
            {
                "severity": "error",
                "text": (
                    "Type mismatch\n  <decl>\nhas type\n  ∃ (x : ℝ), x * x = 2\n"
                    "but is expected to have type\n  ∃ (x : ℚ), x * x = 2"
                ),
            }
        ],
        "sorry_goals": [],
        "soundness": {
            "guard": "passed",
            "flags": [],
            "audit_status": "skipped",
            "axiom_closure": None,
            "axiom_closure_ok": None,
        },
        "provenance": {
            "lean_toolchain": "leanprover/lean4:v4.30.0-rc2",
            "mathlib_rev": "5450b53e5ddc",
            "transcript_sha256": "cd" * 32,
        },
    }


def _defeq_kernel(
    routes: list[tuple[str, dict]],
    defeq: dict[str, set[str]],
):
    """Fake verifier modelling the live kernel. ``defeq[decl]`` is the set
    of normalized target forms the kernel ACCEPTS for ``@decl`` (i.e. the
    forms defeq to the decl's real type). A kernel-check whose target is
    NOT in that set returns a Type-mismatch env (the collision denial)."""
    calls: list[str] = []
    norm_defeq = {d: {normalize_lean(t) for t in ts} for d, ts in defeq.items()}

    async def verify(snippet: str, imports: list[str]) -> dict:
        calls.append(snippet)
        m = _KERNEL_CHECK_RE.search(snippet.rstrip())
        if m is not None:
            target = normalize_lean(m.group("target"))
            decl = m.group("decl")
            if target in norm_defeq.get(decl, set()):
                return _ok_env(decl)
            return _mismatch_env()
        for key, env in routes:
            if key in snippet:
                return env
        raise AssertionError(f"unexpected snippet: {snippet!r}")

    verify.calls = calls
    return verify


def _task(**over) -> dict:
    example = load_example("proof-task.v0.example.json")
    payload = {
        "task_id": "kernel-decides-regression",
        "statement_latex": "\\exists x \\in \\mathbb{Q}: x^2 = 2",
        "statement_nl": "There is a rational whose square is two.",
        "field_lane": "math.NT",
        "claim_type": "lemma",
    }
    payload.update(over)
    return wrap_payload(
        artifact=PROOF_TASK_ARTIFACT,
        version=PROOF_TASK_VERSION,
        producer="regression-harness",
        produced_at="2026-07-05T00:00:00Z",
        substrate=example["bridge"]["substrate"],
        payload=payload,
    )


# ===========================================================================
# 1. THE ℝ/ℚ COLLISION (the reproduced CRITICAL) — must DENY both sides.
# ===========================================================================

# The author's two independent ℚ formalizations of the FALSE claim. Both
# denote ∃ x:ℚ, x*x=2; they pretty-print to `∃ x, x * x = 2` (binder type
# elided) — byte-identical to the ℝ proof's kernel render (the collision).
# The two channels differ (trivial-equivalence guard) but the winning ℝ
# proof is defeq to NEITHER (both are ℚ existentials).
_RAT_A = "∃ x : ℚ, x * x = 2"
_RAT_B = "∃ x : ℚ, x * x = 2 ∧ True"
# The pretty-print string BOTH the ℝ proof and the ℚ author formalization
# collapse to under normalize_lean (this is what the string-match HEAD
# compared, and matched).
_COLLISION_PP = "∃ x, x * x = 2"

_REAL_PROOF = ProofAttempt(
    name="sqrt2_real",
    snippet=(
        "theorem sqrt2_real : ∃ x : Real, x * x = 2 := "
        "⟨Real.sqrt 2, Real.mul_self_sqrt (by norm_num)⟩"
    ),
    imports=("Mathlib",),
)


def _rat_role_outputs(attempts) -> RoleOutputs:
    return RoleOutputs(
        formalization_a=FormalizationRecord(
            channel="A", statement_lean=_RAT_A, producer="af-a",
            session_id="s-a", imports=("Mathlib",),
        ),
        formalization_b=FormalizationRecord(
            channel="B", statement_lean=_RAT_B, producer="af-b",
            session_id="s-b", imports=("Mathlib",),
        ),
        back_translation=BackTranslationRecord(
            statement_en="there is a rational whose square is two",
            translator="bt", session_id="s-bt",
            source_channel="A", rendered_statement_lean=_RAT_A,
            translator_saw_original=False,
        ),
        skeptic_diff=SkepticDiffRecord(skeptic="sk", verdict="match"),
        attempts=attempts,
    )


class TestRatCollisionProofSide:
    """PROOF side: a kernel-clean proof of the TRUE ℝ statement must NOT
    earn `proven-formal` against a gate-checked formalization of the FALSE
    ℚ statement — even though the two pretty-print identically (the
    string-match HEAD granted this)."""

    def test_string_match_would_have_collided(self):
        """Sanity: the two DO collapse to the same normalized string — so
        the retired string comparison WOULD have matched (this is why the
        HEAD granted). The kernel-decides path below denies it anyway."""
        assert normalize_lean(_COLLISION_PP) == normalize_lean("∃ x, x * x = 2")
        # The ℝ proof's kernel render and the ℚ author form both = _COLLISION_PP.

    def test_real_proof_does_not_earn_proven_formal_for_rat_claim(self):
        # The kernel accepts sqrt2_real ONLY against ℝ existentials, NEVER
        # the ℚ formalizations A/B (the live REPL Type-mismatch).
        verifier = _defeq_kernel(
            routes=[
                ("sqrt2_real", _ok_env("sqrt2_real", kernel_stmt=_COLLISION_PP)),
                ("d3_gate_equiv_fwd", _ok_env("d3_gate_equiv_fwd")),
                ("d3_gate_equiv_bwd", _ok_env("d3_gate_equiv_bwd")),
            ],
            defeq={
                "sqrt2_real": {"∃ x : Real, x * x = 2", "∃ x : ℝ, x * x = 2"},
            },
        )
        result = _run(
            run_proving_pipeline(
                task=_task(),  # a REAL task (known_truth null) — only linkage can stop it
                role_outputs=_rat_role_outputs((_REAL_PROOF,)),
                lean_verify=verifier,
            )
        )
        # DENY: the kernel refused sqrt2_real against both ℚ formalizations.
        assert result.verdict == "plausible-unverified", result.verdict_reasons
        assert result.verdict != "proven-formal"
        assert any("statement linkage" in r for r in result.verdict_reasons)
        payload = result.bundle["payload"]
        assert payload["formal"]["best_proves_formalization"] is False
        # The audit scalar still shows the collided pretty-print (proof that
        # a string compare WOULD have matched — the kernel denied anyway).
        assert payload["formal"]["best_statement_lean"] == _COLLISION_PP
        validate_evidence_bundle(result.bundle)

    def test_pure_award_denies_the_collision(self):
        """The pure award rule directly: proves_formalization=False (the
        kernel's verdict on the ℝ-vs-ℚ check) caps, regardless of the
        (colliding) pretty-print string."""
        block = {
            "dual": {
                "records": [
                    {"channel": "A", "statement_lean": _RAT_A, "producer": "a",
                     "session_id": "sa", "saw_original_statement": True,
                     "saw_other_channel": False},
                    {"channel": "B", "statement_lean": _RAT_B, "producer": "b",
                     "session_id": "sb", "saw_original_statement": True,
                     "saw_other_channel": False},
                ]
            }
        }
        ok, reasons = proof_statement_linked(False, block)
        assert ok is False
        assert any("kernel did not confirm" in r for r in reasons)


class TestRatCollisionRefutationSide:
    """REFUTATION side: a witness of the TRUE ℝ statement must NOT earn a
    confident `refuted` for a claim whose declared discharged proposition
    is the FALSE ℚ statement — the mirror hole. Adapts exploit_live.py."""

    _WITNESS_CHECKS = {
        "lean": [
            {
                "name": "rat-collision-witness",
                "kind": "witness",
                # A NAMED theorem kernel-proving the TRUE ℝ existential.
                "snippet": (
                    "theorem wit : ∃ x : Real, x * x = 2 := "
                    "⟨Real.sqrt 2, Real.mul_self_sqrt (by norm_num)⟩"
                ),
                "imports": ["Mathlib"],
                # The author DECLARES it discharges the ℚ proposition — which
                # renders to the SAME string as the ℝ witness's type. Under
                # the string-match HEAD this MATCHED -> confident `refuted`.
                "discharges": {
                    "proposition": "∃ x : ℚ, x * x = 2",
                    "refutes_claim": True,
                    "justification": "(claims to discharge the rational existence)",
                },
            }
        ]
    }

    def test_real_witness_does_not_earn_confident_refuted_for_rat_claim(self):
        verifier = _defeq_kernel(
            routes=[("∃ x : Real", _ok_env("wit", kernel_stmt=_COLLISION_PP))],
            defeq={
                # The kernel accepts wit ONLY against ℝ existentials, NEVER
                # the declared ℚ proposition -> proves_declared_proposition
                # False -> the choke-point caps `refuted` -> abstained.
                "wit": {"∃ x : Real, x * x = 2", "∃ x : ℝ, x * x = 2"},
            },
        )
        lane = _run(
            run_skeptic_lane(
                lean_checks=_specs(self._WITNESS_CHECKS),
                lean_verify=verifier,
            )
        )
        # The lane still records the raw witness hit...
        assert lane.verdict == "refuted"
        cx = lane.counterexample
        assert cx["kernel_confirmed"] is True
        # ...but the KERNEL denied the declared-ℚ check:
        assert cx["proves_declared_proposition"] is False

        # The pure linkage function DENIES:
        linked, reasons = refutation_statement_linked(cx)
        assert linked is False
        assert any("KERNEL did not confirm" in r for r in reasons)

        # The choke-point caps the confident refuted -> abstained:
        out = award_linked_verdict("refuted", "high", counterexample=cx)
        assert out.verdict == "abstained"
        assert out.linked is False

    def test_full_pipeline_rat_claim_does_not_refute(self):
        """End-to-end through run_proving_pipeline on a REAL task: the
        collision witness caps to abstained, and the counterexample is
        dropped from the bundle (a capped refutation is not a refutation)."""
        verifier = _defeq_kernel(
            routes=[("∃ x : Real", _ok_env("wit", kernel_stmt=_COLLISION_PP))],
            defeq={"wit": {"∃ x : Real, x * x = 2"}},
        )
        result = _run(
            run_proving_pipeline(
                task=_task(known_truth=None, skeptic_checks=self._WITNESS_CHECKS),
                role_outputs=RoleOutputs(),
                lean_verify=verifier,
            )
        )
        assert result.verdict == "abstained", result.verdict_reasons
        assert result.verdict != "refuted"
        assert "counterexample" not in result.bundle["payload"]
        assert any("choke-point" in r for r in result.verdict_reasons)
        validate_evidence_bundle(result.bundle)


def _specs(checks):
    from server.proving.skeptic import checks_from_proof_task

    lean_specs, _ = checks_from_proof_task({"skeptic_checks": checks})
    return lean_specs


# ===========================================================================
# 3. Brittleness gone: a defeq-but-different-syntax formalization LINKS.
#    (Denied under string-match; granted under kernel-decides.)
# ===========================================================================


class TestDefeqFormalizationLinks:
    """The kernel-form brittleness (the convergence pass's major robustness
    finding) is gone: a formalization written in NATURAL author syntax that
    is DEFINITIONALLY EQUAL to the proof's type LINKS, even though its
    pretty-print string differs from the proof's kernel render."""

    def test_natural_syntax_formalization_links_proof_side(self):
        # Proof's kernel type: `∀ (m n : ℕ), m + n = n + m`.
        # Formalization A written naturally: `∀ m n : Nat, ...` (Nat spelled,
        # implicit binder) — a DIFFERENT string, but defeq. Under string-match
        # this DENIED; the kernel accepts it, so it LINKS.
        attempt = ProofAttempt(
            name="nc",
            snippet="theorem nc : ∀ (m n : Nat), m + n = n + m := fun m n => Nat.add_comm m n",
            imports=("Mathlib",),
        )
        nat_a = "∀ m n : Nat, m + n = n + m"          # natural author syntax
        nat_b = "∀ (a b : ℕ), a + b = b + a ∧ True"    # different channel
        role_outputs = RoleOutputs(
            formalization_a=FormalizationRecord(
                channel="A", statement_lean=nat_a, producer="a",
                session_id="sa", imports=("Mathlib",),
            ),
            formalization_b=FormalizationRecord(
                channel="B", statement_lean=nat_b, producer="b",
                session_id="sb", imports=("Mathlib",),
            ),
            back_translation=BackTranslationRecord(
                statement_en="addition on the naturals commutes",
                translator="bt", session_id="sbt",
                source_channel="A", rendered_statement_lean=nat_a,
                translator_saw_original=False,
            ),
            skeptic_diff=SkepticDiffRecord(skeptic="sk", verdict="match"),
            attempts=(attempt,),
        )
        verifier = _defeq_kernel(
            routes=[
                ("theorem nc", _ok_env("nc", kernel_stmt="∀ (m n : ℕ), m + n = n + m")),
                ("d3_gate_equiv_fwd", _ok_env("d3_gate_equiv_fwd")),
                ("d3_gate_equiv_bwd", _ok_env("d3_gate_equiv_bwd")),
            ],
            defeq={
                # The kernel accepts nc against the natural-syntax A (defeq),
                # NOT against B (a strengthened, non-defeq statement).
                "nc": {nat_a, "∀ (m n : ℕ), m + n = n + m"},
            },
        )
        result = _run(
            run_proving_pipeline(
                task=_task(
                    statement_latex="\\forall m, n: m + n = n + m",
                    statement_nl="Addition on the naturals commutes.",
                ),
                role_outputs=role_outputs,
                lean_verify=verifier,
            )
        )
        # LINKS via kernel-decides even though A's string != the proof's
        # kernel render: proven-formal (was denied under string-match).
        assert result.verdict == "proven-formal", result.verdict_reasons
        payload = result.bundle["payload"]
        assert payload["formal"]["best_proves_formalization"] is True
        assert payload["formal"]["best_proves_formalization_channel"] == "A"
        validate_evidence_bundle(result.bundle)

    def test_pure_award_links_when_kernel_confirms_defeq(self):
        block = {
            "dual": {"records": [
                {"channel": "A", "statement_lean": "∀ m n : Nat, m + n = n + m",
                 "producer": "a", "session_id": "sa",
                 "saw_original_statement": True, "saw_other_channel": False},
                {"channel": "B", "statement_lean": "∀ (a b : ℕ), a + b = b + a ∧ True",
                 "producer": "b", "session_id": "sb",
                 "saw_original_statement": True, "saw_other_channel": False},
            ]}
        }
        # The kernel confirmed the proof proves a gate-checked formalization
        # (defeq to A) -> proves_formalization True -> linked, regardless of
        # the differing pretty-print strings.
        ok, reasons = proof_statement_linked(True, block)
        assert ok is True and reasons == []


# ===========================================================================
# 4. The 2-5=0 Nat/Int lossy-pp case: a Nat proof must NOT link an Int
#    formalization — kernel-decides distinguishes them (string-match would
#    have collided the pretty-prints).
# ===========================================================================


class TestNatIntLossyPrettyPrint:
    def test_nat_proof_does_not_link_int_formalization(self):
        """`(2-5 : Nat) = 0` is TRUE (truncated subtraction); the Int
        reading `(2-5 : Int) = 0` is FALSE. A proof of the Nat fact must
        NOT link a formalization INTENDING the Int equation — the kernel
        Type-mismatch distinguishes ℕ subtraction from ℤ subtraction."""
        attempt = ProofAttempt(
            name="natsub",
            snippet="theorem natsub : (2 - 5 : Nat) = 0 := by norm_num",
            imports=("Mathlib",),
        )
        int_form = "(2 - 5 : Int) = 0"   # author INTENDS the Int equation (FALSE)
        int_form_b = "(2 - 5 : Int) = 0 ∧ True"
        role_outputs = RoleOutputs(
            formalization_a=FormalizationRecord(
                channel="A", statement_lean=int_form, producer="a",
                session_id="sa", imports=("Mathlib",),
            ),
            formalization_b=FormalizationRecord(
                channel="B", statement_lean=int_form_b, producer="b",
                session_id="sb", imports=("Mathlib",),
            ),
            back_translation=BackTranslationRecord(
                statement_en="two minus five is zero over the integers",
                translator="bt", session_id="sbt",
                source_channel="A", rendered_statement_lean=int_form,
                translator_saw_original=False,
            ),
            skeptic_diff=SkepticDiffRecord(skeptic="sk", verdict="match"),
            attempts=(attempt,),
        )
        verifier = _defeq_kernel(
            routes=[
                ("theorem natsub", _ok_env("natsub", kernel_stmt="(2 - 5 : Nat) = 0")),
                ("d3_gate_equiv_fwd", _ok_env("d3_gate_equiv_fwd")),
                ("d3_gate_equiv_bwd", _ok_env("d3_gate_equiv_bwd")),
            ],
            defeq={
                # The kernel accepts natsub ONLY against the Nat equation,
                # NEVER the Int formalizations (ℤ subtraction ≠ ℕ truncated
                # subtraction) — the live REPL Type-mismatch.
                "natsub": {"(2 - 5 : Nat) = 0", "(2 : ℕ) - 5 = 0"},
            },
        )
        result = _run(
            run_proving_pipeline(
                task=_task(
                    statement_latex="2 - 5 = 0 \\text{ over } \\mathbb{Z}",
                    statement_nl="Two minus five is zero over the integers.",
                ),
                role_outputs=role_outputs,
                lean_verify=verifier,
            )
        )
        # DENY: the Nat proof does not inhabit the Int formalization.
        assert result.verdict == "plausible-unverified", result.verdict_reasons
        assert result.verdict != "proven-formal"
        assert any("statement linkage" in r for r in result.verdict_reasons)
        assert result.bundle["payload"]["formal"]["best_proves_formalization"] is False
        validate_evidence_bundle(result.bundle)


# ===========================================================================
# The mechanism helpers, exercised directly (the shapes the live probe used).
# ===========================================================================


class TestMechanismShapes:
    def test_kernel_check_snippet_shape(self):
        snip = "theorem sqrt2_real : ∃ x : Real, x * x = 2 := pf"
        out = kernel_check_snippet(snip, "∃ x : ℚ, x * x = 2", "sqrt2_real")
        assert out == f"{snip}\nexample : ∃ x : ℚ, x * x = 2 := @sqrt2_real"

    def test_kernel_decides_linked_reads_status(self):
        assert kernel_decides_linked({"status": "ok", "compilation_success": True})
        assert not kernel_decides_linked({"status": "error", "compilation_success": False})
        assert not kernel_decides_linked(None)
