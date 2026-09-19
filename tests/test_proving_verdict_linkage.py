"""Unit tests for the verdict-award choke-point
(stage3/proving-r3 — WS-D round-3 statement-linkage class fix; durable
P1 kernel-decides-equality upgrade).

The choke-point (:mod:`server.proving.verdict_linkage`) is the single
seam every verdict-award path passes through, so no path can emit a
confident verdict without a recorded, checked evidence↔claim linkage.
LLM-free / REPL-free (AC-D.13 grain) — pure over recorded evidence
dicts.

**Durable P1 kernel-decides fix.** Both linkage models now key on a
BOOLEAN that the REPL-access layer (orchestrator / skeptic) recorded from
a KERNEL type-check ``example : <target> := @<decl>``, NOT a pretty-print
string comparison:

- proof side — ``proves_formalization`` (did the kernel accept the proof
  against a gate-checked formalization?);
- refutation side — ``counterexample["proves_declared_proposition"]`` (did
  the kernel accept the witness against the declared discharged
  proposition?).

The string compare is gone; these pure functions only read the recorded
boolean. The kernel's *decision* — the ℝ/ℚ collision denied, a defeq
phrasing linked — is exercised end-to-end in
``tests/test_proving_orchestrator.py`` (fake kernel) and the gated
``*_lean.py`` batteries (real kernel).
"""

from __future__ import annotations

from server.proving.verdict_linkage import (
    PROOF_LINKAGE_CAP,
    REFUTATION_LINKAGE_CAP,
    award_linked_verdict,
    proof_award_linkage,
    refutation_statement_linked,
)

# ---------------------------------------------------------------------------
# Fixtures: counterexample records (the skeptic lane's own shape)
# ---------------------------------------------------------------------------

_PROP_A = "∀ m n : Nat, Even m → Even n → Even (m + n)"
_PROP_B = "∀ a b : Nat, a % 2 = 0 → b % 2 = 0 → (a + b) % 2 = 0"


def _signed_ok_block() -> dict:
    """A complete faithfulness block whose dual records are _PROP_A/_PROP_B
    (the proof-linkage targets)."""
    return {
        "dual": {
            "records": [
                {
                    "channel": "A",
                    "statement_lean": _PROP_A,
                    "producer": "af-a",
                    "session_id": "sess-a",
                    "saw_original_statement": True,
                    "saw_other_channel": False,
                },
                {
                    "channel": "B",
                    "statement_lean": _PROP_B,
                    "producer": "af-b",
                    "session_id": "sess-b",
                    "saw_original_statement": True,
                    "saw_other_channel": False,
                },
            ]
        }
    }


def _kernel_witness_cx(
    *, proves_declared: bool | None, declared: str | None, refutes=True
) -> dict:
    """A lean-witness counterexample as the skeptic lane records it.

    ``proves_declared`` is the BOOLEAN the skeptic lane recorded from the
    kernel check ``example : <declared> := @<witness_decl>`` (durable P1
    kernel-decides fix); ``declared`` is the author's discharged
    proposition text (obligation-linkage only now — never string-compared
    against the kernel)."""
    cx: dict = {
        "source": "lean-witness",
        "check": "w1",
        "kernel_confirmed": True,
        "witness": {"snippet": "…", "imports": []},
        "description": "kernel witness",
        # Audit/display only now (the elaborated type); NOT the decider.
        "proved_statement_lean": "audit-only",
        "proves_declared_proposition": proves_declared,
    }
    if declared is not None:
        cx["discharges"] = {"proposition": declared, "refutes_claim": refutes}
    return cx


# ---------------------------------------------------------------------------
# refutation_statement_linked — the declared-and-KERNEL-checked model
# ---------------------------------------------------------------------------


class TestRefutationLinkage:
    def test_kernel_confirmed_link_is_linked(self):
        """The FALSE-trio shape: the witness proves an auxiliary fact and
        DECLARES it discharges that proposition; THE KERNEL confirmed the
        witness proves the declared proposition (proves_declared=True),
        refutes_claim=true, so the refutation is linked."""
        cx = _kernel_witness_cx(
            proves_declared=True,
            declared="2 ^ 32 + 1 = 641 * 6700417",
        )
        linked, reasons = refutation_statement_linked(cx)
        assert linked is True
        assert reasons == []

    def test_no_declaration_fails_closed(self):
        """The exact hole: a kernel-clean witness with NO declared target
        cannot earn a confident refuted."""
        cx = _kernel_witness_cx(proves_declared=True, declared=None)
        linked, reasons = refutation_statement_linked(cx)
        assert linked is False
        assert any("declared no discharged proposition" in r for r in reasons)

    def test_declaration_not_marked_refutes_claim_fails_closed(self):
        cx = _kernel_witness_cx(
            proves_declared=True, declared="¬ Nat.Prime 4", refutes=False
        )
        linked, reasons = refutation_statement_linked(cx)
        assert linked is False
        assert any("refutes_claim" in r for r in reasons)

    def test_kernel_denied_declaration_fails_closed(self):
        """THE CRUCIAL check + the durable P1 fix: the author declared a
        claim-linked target but THE KERNEL did NOT accept
        ``example : <declared> := @<witness_decl>`` — the witness proves
        something else, or (the reproduced CRITICAL) the ℝ/ℚ pretty-print
        collision where a ℝ witness was declared to discharge a ℚ
        proposition. The declared string is never trusted over the
        kernel's verdict, so the refutation is denied."""
        cx = _kernel_witness_cx(
            proves_declared=False,  # kernel refused: not defeq
            declared="¬ (∀ n, Nat.Prime (n^2+n+41))",
        )
        linked, reasons = refutation_statement_linked(cx)
        assert linked is False
        assert any("KERNEL did not confirm" in r for r in reasons)

    def test_kernel_confirmed_but_missing_boolean_fails_closed(self):
        """kernel_confirmed=True but the kernel-check boolean is
        absent/None (the check never ran, errored, or the witness has no
        queryable decl name) — fail closed, never assumed linked."""
        cx = _kernel_witness_cx(proves_declared=None, declared="¬ Nat.Prime 4")
        linked, reasons = refutation_statement_linked(cx)
        assert linked is False
        assert any("KERNEL did not confirm" in r for r in reasons)

    def test_search_hit_is_not_linked_even_with_declaration(self):
        """ROUND-3 CLASS FIX (findings: search-kind unlinked refutation).
        A search hit is ``kernel_confirmed=False`` (the falsification
        tactic reports a hit, it kernel-proves nothing), so it FAILS the
        kernel-linkage half — even if the author bolts on a discharges
        declaration (which search never carried). Capped/escalated
        downstream."""
        cx = {
            "source": "lean-search",
            "check": "s1",
            "kernel_confirmed": False,
            "witness": {"bindings": {"n": "44"}},
            "description": "search hit",
        }
        linked, reasons = refutation_statement_linked(cx)
        assert linked is False
        # No declaration first (the real shape the lane records) —
        # fail-closed on the missing declaration.
        assert any("declared no discharged proposition" in r for r in reasons)

        # Even WITH a (bogus) declaration bolted on, search still fails —
        # kernel_confirmed=False has no declaration for the kernel to
        # inhabit.
        cx_declared = {
            **cx,
            "proves_declared_proposition": None,
            "discharges": {"proposition": "∀ n : Nat, n < 3", "refutes_claim": True},
        }
        linked2, reasons2 = refutation_statement_linked(cx_declared)
        assert linked2 is False
        assert any("not kernel-confirmed" in r for r in reasons2)

    def test_cas_hit_with_declaration_is_not_linked(self):
        """ROUND-3 CLASS FIX (findings: CAS-sympy unlinked refutation).
        CAS is evaluation-checked (``kernel_confirmed=False``) — the
        author supplies BOTH the code and the declaration and there is no
        declaration for the kernel to inhabit, so a CAS hit FAILS the
        kernel-linkage half. Capped/escalated downstream."""
        cx = {
            "source": "cas-sympy",
            "check": "c1",
            "kernel_confirmed": False,
            "witness": {"n": 40},
            "description": "cas hit",
            "proves_declared_proposition": False,
            "discharges": {
                "proposition": "∃ n, ¬ Nat.Prime (n^2+n+41)",
                "refutes_claim": True,
            },
        }
        linked, reasons = refutation_statement_linked(cx)
        assert linked is False
        assert any("not kernel-confirmed" in r for r in reasons)

    def test_cas_hit_without_declaration_fails_closed(self):
        cx = {
            "source": "cas-sympy",
            "check": "c1",
            "kernel_confirmed": False,
            "witness": {"n": 40},
            "description": "cas hit",
            "proves_declared_proposition": False,
        }
        assert refutation_statement_linked(cx)[0] is False

    def test_cas_or_search_backed_by_kernel_witness_clears(self):
        """The escape hatch the class fix leaves open (finding #3/major's
        recommended tie): a CAS/search refutation CAN stand if it is
        promoted to a kernel-confirmed record whose kernel check accepted
        the declared proposition — i.e. a companion kernel witness. This
        proves the fix caps *unlinked* refutations, not all non-witness
        sources categorically."""
        cx = {
            "source": "cas-sympy",
            "check": "c1",
            "kernel_confirmed": True,  # promoted by a companion kernel witness
            "witness": {"n": 40},
            "proved_statement_lean": "¬ Nat.Prime (40 ^ 2 + 40 + 41)",
            "proves_declared_proposition": True,
            "discharges": {
                "proposition": "¬ Nat.Prime (40 ^ 2 + 40 + 41)",
                "refutes_claim": True,
            },
        }
        assert refutation_statement_linked(cx) == (True, [])

    def test_unknown_source_fails_closed(self):
        cx = {"source": "vibes", "check": "x", "kernel_confirmed": True}
        linked, reasons = refutation_statement_linked(cx)
        assert linked is False
        assert any("unknown counterexample source" in r for r in reasons)

    def test_none_counterexample_fails_closed(self):
        assert refutation_statement_linked(None)[0] is False


# ---------------------------------------------------------------------------
# proof_award_linkage — the kernel-decided formalization⇔proof link
# ---------------------------------------------------------------------------


class TestProofLinkage:
    def test_kernel_confirmed_proof_is_linked(self):
        ok, reasons = proof_award_linkage(
            "proven-formal",
            proves_formalization=True,
            faithfulness_block=_signed_ok_block(),
        )
        assert ok is True and reasons == []

    def test_kernel_denied_proof_is_not_linked(self):
        """The kernel did NOT accept the proof against any gate-checked
        formalization (the ℝ/ℚ collision, an unrelated proof, a
        vacuous-binder proof) — proves_formalization False → not linked."""
        ok, reasons = proof_award_linkage(
            "proven-formal",
            proves_formalization=False,
            faithfulness_block=_signed_ok_block(),
        )
        assert ok is False
        assert any("kernel did not confirm" in r for r in reasons)

    def test_informal_checked_carries_no_machine_linkage_obligation(self):
        ok, _ = proof_award_linkage(
            "proven-informal-checked",
            proves_formalization=None,
            faithfulness_block=None,
        )
        assert ok is True


# ---------------------------------------------------------------------------
# award_linked_verdict — THE choke-point routing
# ---------------------------------------------------------------------------


class TestChokePointRouting:
    def test_refuted_with_valid_linkage_stands(self):
        cx = _kernel_witness_cx(
            proves_declared=True,
            declared="¬ Nat.Prime (40 ^ 2 + 40 + 41)",
        )
        out = award_linked_verdict("refuted", "high", counterexample=cx)
        assert out.verdict == "refuted"
        assert out.confidence == "high"
        assert out.linked is True

    def test_refuted_without_linkage_is_capped(self):
        cx = _kernel_witness_cx(proves_declared=None, declared=None)
        out = award_linked_verdict("refuted", "high", counterexample=cx)
        assert out.verdict == REFUTATION_LINKAGE_CAP == "abstained"
        assert out.confidence == "low"
        assert out.linked is False
        assert any("choke-point" in r for r in out.reasons)

    def test_proven_formal_with_linkage_stands(self):
        out = award_linked_verdict(
            "proven-formal",
            "high",
            proves_formalization=True,
            faithfulness_block=_signed_ok_block(),
        )
        assert out.verdict == "proven-formal"
        assert out.linked is True

    def test_proven_formal_without_linkage_is_capped(self):
        out = award_linked_verdict(
            "proven-formal",
            "high",
            proves_formalization=False,
            faithfulness_block=_signed_ok_block(),
        )
        assert out.verdict == PROOF_LINKAGE_CAP == "plausible-unverified"
        assert out.linked is False

    def test_abstained_passes_through_untouched(self):
        out = award_linked_verdict("abstained", "low")
        assert out.verdict == "abstained"
        assert out.linked is True

    def test_plausible_unverified_passes_through_untouched(self):
        out = award_linked_verdict("plausible-unverified", "low")
        assert out.verdict == "plausible-unverified"
        assert out.linked is True


# ---------------------------------------------------------------------------
# The ℝ/ℚ pretty-print collision (the reproduced CRITICAL false-accept),
# at the pure choke-point. Under the retired string-match model these two
# GRANTED (the ℝ witness/proof pretty-prints identically to the ℚ target);
# under kernel-decides the KERNEL denies the collision, so the recorded
# boolean is False and the choke-point caps. The end-to-end (real-function
# + fake-kernel) form lives in test_proving_orchestrator.py; the live
# real-kernel form in the gated *_lean.py batteries.
# ---------------------------------------------------------------------------


class TestRealRatCollisionAtChokePoint:
    def test_refutation_collision_denies(self):
        """A witness of the TRUE ``∃ x : ℝ, x*x=2`` declared to discharge
        the FALSE ``∃ x : ℚ, x*x=2``. Both delaborate to ``∃ x, x*x=2`` so
        the string compare matched (GRANT on the string-match HEAD); the
        kernel denies the ℝ⊄ℚ collision (proves_declared_proposition
        False), so the choke-point caps `refuted` → abstained."""
        cx = {
            "source": "lean-witness",
            "check": "sqrt2-real-vs-rat",
            "kernel_confirmed": True,
            "witness": {"snippet": "theorem wit : ∃ x : Real, x*x = 2 := …", "imports": []},
            # audit/display: the ℝ witness's kernel type pretty-prints to
            # the SAME string as the ℚ declaration — the collision.
            "proved_statement_lean": "∃ x, x * x = 2",
            # THE KERNEL refused `example : (∃ x:ℚ,…) := @wit`.
            "proves_declared_proposition": False,
            "discharges": {"proposition": "∃ x, x * x = 2", "refutes_claim": True},
        }
        linked, _ = refutation_statement_linked(cx)
        assert linked is False
        out = award_linked_verdict("refuted", "high", counterexample=cx)
        assert out.verdict == REFUTATION_LINKAGE_CAP == "abstained"
        assert out.linked is False

    def test_proof_collision_denies(self):
        """A proof of the TRUE ℝ statement against a gate-checked ℚ
        formalization (both pretty-print to ``∃ x, x*x=2``). The kernel
        denies the collision (proves_formalization False), so the
        choke-point caps `proven-formal` → plausible-unverified."""
        block = {
            "dual": {
                "records": [
                    {
                        "channel": "A",
                        "statement_lean": "∃ x, x * x = 2",  # author intent: ℚ
                        "producer": "af-a",
                        "session_id": "s-a",
                        "saw_original_statement": True,
                        "saw_other_channel": False,
                    },
                    {
                        "channel": "B",
                        "statement_lean": "∃ x, x * x = 2 ∧ True",
                        "producer": "af-b",
                        "session_id": "s-b",
                        "saw_original_statement": True,
                        "saw_other_channel": False,
                    },
                ]
            }
        }
        out = award_linked_verdict(
            "proven-formal",
            "high",
            proves_formalization=False,  # kernel refused ℝ-proof vs ℚ-formalization
            faithfulness_block=block,
        )
        assert out.verdict == PROOF_LINKAGE_CAP == "plausible-unverified"
        assert out.linked is False
