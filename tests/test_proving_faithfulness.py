"""D-3 statement-faithfulness gate unit tests (stage2/arx-d3 — WS-D;
AC-D.5/AC-D.6 offline half). Fake Lean verifiers throughout.

Pins: the four elements are individually load-bearing (a run missing
ANY caps at plausible-unverified — THE AC-D.5 award-rule test);
seeded misformalizations (quantifier swap, strict-vs-non-strict,
hypothesis-dropped) are caught by the equivalence check failing
fail-closed; the equivalence directions consume the D-2 hardened
award predicate (a native_decide- or sorry-tainted "proof" of a
direction is no equivalence); blindness and independence attestations
are enforced structurally; NO automation can set the human sign-off
(the gate always emits signed=false; the only signer is
operator-invoked and refuses failed gates); and the bundle schema
carries the two D-3 laws (proven-formal requires a faithfulness
record; publishable proven-formal requires the signed checkbox).
"""

from __future__ import annotations

import asyncio
import copy

import pytest

from server.proving.contracts import (
    EVIDENCE_BUNDLE_ARTIFACT,
    EVIDENCE_BUNDLE_VERSION,
    ContractValidationError,
    load_example,
    validate_evidence_bundle,
    wrap_payload,
)
from server.proving.faithfulness import (
    BWD_NAME,
    DEFAULT_EQUIV_TACTIC,
    FWD_NAME,
    BackTranslationRecord,
    FormalizationRecord,
    SkepticDiffRecord,
    award_statement_verdict,
    equivalence_snippet,
    faithfulness_award_ok,
    normalize_lean,
    proof_statement_linked,
    record_human_signoff,
    run_faithfulness_gate,
)

# ---------------------------------------------------------------------------
# Fixtures: fake hardened lean_verify envelopes + standard gate records
# ---------------------------------------------------------------------------

_PROP_A = "∀ n : Nat, n + 0 = n"
_PROP_B = "∀ k : Nat, k + 0 = k"


def _direction_env(kind: str, decl_name: str) -> dict:
    """A fake D-2 hardened lean_verify result for one equivalence
    direction. ``kind``: 'ok' (award-clean), 'error' (direction not
    proved), 'flagged' (kernel ok but native_decide — award must
    deny), 'dirty-closure' (kernel ok but sorryAx in the closure)."""
    base = {
        "status": "ok",
        "mode": "full",
        "compilation_success": True,
        "messages": [],
        "sorry_goals": [],
        "soundness": {
            "guard": "passed",
            "flags": [],
            "audit_status": "ok",
            "audited_decls": [decl_name],
            "axiom_closure": ["propext", "Classical.choice", "Quot.sound"],
            "axiom_closure_ok": True,
        },
        "provenance": {
            "lean_toolchain": "leanprover/lean4:v4.30.0-rc2",
            "mathlib_rev": "5450b53e5ddc",
            "transcript_sha256": f"{'ab' if decl_name == FWD_NAME else 'cd'}" * 32,
        },
    }
    if kind == "error":
        base["status"] = "error"
        base["compilation_success"] = False
        base["messages"] = [
            {
                "severity": "error",
                "position": {"line": 1, "column": 0},
                "text": "unsolved goals",
            }
        ]
    elif kind == "flagged":
        base["soundness"]["flags"] = ["native_decide"]
    elif kind == "dirty-closure":
        base["soundness"]["axiom_closure"] = ["propext", "sorryAx"]
        base["soundness"]["axiom_closure_ok"] = False
    elif kind != "ok":
        raise ValueError(kind)
    return base


def _make_verifier(fwd: str = "ok", bwd: str = "ok"):
    """Async fake dispatching on the obligation names; records calls."""
    calls: list[str] = []

    async def verify(snippet: str, imports: list[str]) -> dict:
        calls.append(snippet)
        if FWD_NAME in snippet:
            return _direction_env(fwd, FWD_NAME)
        if BWD_NAME in snippet:
            return _direction_env(bwd, BWD_NAME)
        raise AssertionError(f"unexpected snippet: {snippet!r}")

    verify.calls = calls
    return verify


def _form_a(**over) -> FormalizationRecord:
    kwargs = {
        "channel": "A",
        "statement_lean": _PROP_A,
        "producer": "autoformalizer-1",
        "session_id": "sess-a",
        "imports": ("Mathlib.Tactic",),
    }
    kwargs.update(over)
    return FormalizationRecord(**kwargs)


def _form_b(**over) -> FormalizationRecord:
    kwargs = {
        "channel": "B",
        "statement_lean": _PROP_B,
        "producer": "autoformalizer-2",
        "session_id": "sess-b",
        "imports": ("Mathlib.Tactic",),
    }
    kwargs.update(over)
    return FormalizationRecord(**kwargs)


def _bt(**over) -> BackTranslationRecord:
    kwargs = {
        "statement_en": "For every natural number n, n plus zero equals n.",
        "translator": "blind-translator",
        "session_id": "sess-bt",
        "source_channel": "A",
        "rendered_statement_lean": _PROP_A,
        "translator_saw_original": False,
    }
    kwargs.update(over)
    return BackTranslationRecord(**kwargs)


def _sd(**over) -> SkepticDiffRecord:
    kwargs = {
        "skeptic": "statement-skeptic",
        "verdict": "match",
        "saw_original": True,
    }
    kwargs.update(over)
    return SkepticDiffRecord(**kwargs)


def _run_gate(
    *,
    a=None,
    b=None,
    bt=...,
    sd=...,
    verifier=...,
    **kwargs,
):
    if verifier is ...:
        verifier = _make_verifier()
    return asyncio.run(
        run_faithfulness_gate(
            statement_latex="For every natural $n$, $n + 0 = n$.",
            formalization_a=a or _form_a(),
            formalization_b=b or _form_b(),
            back_translation=_bt() if bt is ... else bt,
            skeptic_diff=_sd() if sd is ... else sd,
            lean_verify=verifier,
            **kwargs,
        )
    )


_SUBSTRATE = {
    "server": "arxmcp",
    "corpus_version": 1690,
    "notebook": {
        "slug": "bridgeland-stability",
        "uri": "arxmcp://notebooks/bridgeland-stability",
    },
    "filter_echo": None,
    "retrieval_mode": "dense_only",
    "tool_schema_sha256": "8665de4d1d52c053dbb1dbdd30e2a8a219c0b1e39ff9083124b5a0fa76ca304d",
}


def _bundle_doc(**payload_overrides) -> dict:
    payload = {"task_id": "t-1", "verdict": "abstained", **payload_overrides}
    return wrap_payload(
        artifact=EVIDENCE_BUNDLE_ARTIFACT,
        version=EVIDENCE_BUNDLE_VERSION,
        producer="test",
        produced_at="2026-07-04T00:00:00Z",
        substrate=_SUBSTRATE,
        payload=payload,
    )


def _signed_ok_block() -> dict:
    """A complete, passing, operator-signed faithfulness block."""
    result = _run_gate()
    if not result.gate_ok:
        raise AssertionError(f"fixture gate unexpectedly failed: {result.gate_reasons}")
    return record_human_signoff(
        result.to_faithfulness_block(),
        by="chris.dare",
        note="unit-test fixture",
        i_am_a_human_operator=True,
    )


# ---------------------------------------------------------------------------
# Record constructors: harness misuse is loud
# ---------------------------------------------------------------------------


class TestRecordConstructors:
    def test_bad_channel_raises(self):
        with pytest.raises(ValueError, match="channel"):
            _form_a(channel="C")

    def test_empty_statement_raises(self):
        with pytest.raises(ValueError, match="statement_lean"):
            _form_a(statement_lean="")

    def test_empty_session_raises(self):
        with pytest.raises(ValueError, match="session_id"):
            _form_a(session_id="")

    def test_imports_normalized_to_tuple(self):
        rec = _form_a(imports=["Mathlib.Tactic"])
        assert rec.imports == ("Mathlib.Tactic",)

    def test_bt_bad_source_channel_raises(self):
        with pytest.raises(ValueError, match="source_channel"):
            _bt(source_channel="Z")

    def test_sd_bad_verdict_raises(self):
        with pytest.raises(ValueError, match="verdict"):
            _sd(verdict="looks-fine")

    def test_sd_mismatch_requires_discrepancies(self):
        with pytest.raises(ValueError, match="discrepancies"):
            _sd(verdict="mismatch")

    def test_attestation_violations_are_representable(self):
        # Upstream facts, not parse errors: the GATE fails them.
        rec = _form_b(saw_other_channel=True)
        assert rec.saw_other_channel is True


# ---------------------------------------------------------------------------
# Element 1 — dual independent formalization
# ---------------------------------------------------------------------------


class TestIndependenceEnforcement:
    def test_same_session_fails_and_skips_repl(self):
        verifier = _make_verifier()
        result = _run_gate(b=_form_b(session_id="sess-a"), verifier=verifier)
        assert result.gate_ok is False
        assert any("same session" in r for r in result.gate_reasons)
        # Fail-fast: tainted inputs do not get REPL budget.
        assert verifier.calls == []
        assert result.block["equivalence"]["method"] == "none"

    def test_saw_other_channel_fails(self):
        verifier = _make_verifier()
        result = _run_gate(b=_form_b(saw_other_channel=True), verifier=verifier)
        assert result.gate_ok is False
        assert any("independence violated" in r for r in result.gate_reasons)
        assert verifier.calls == []

    def test_missing_original_statement_attestation_fails(self):
        result = _run_gate(a=_form_a(saw_original_statement=False))
        assert result.gate_ok is False
        assert any("seeing the original statement" in r for r in result.gate_reasons)

    def test_duplicate_channel_fails(self):
        result = _run_gate(b=_form_b(channel="A", statement_lean=_PROP_A))
        assert result.gate_ok is False
        assert any("{A, B}" in r for r in result.gate_reasons)

    def test_independent_flag_recorded(self):
        good = _run_gate()
        assert good.block["dual"]["independent"] is True
        bad = _run_gate(b=_form_b(session_id="sess-a"))
        assert bad.block["dual"]["independent"] is False

    def test_byte_identical_a_b_is_rejected(self):
        """P0 #3 (math-r1 nit 1): two byte-identical formalizations make
        the A⇔B kernel check close instantly on `exact fun h => h`,
        contributing NO dual-formalization protection. Independence must
        be more than attested (distinct channels/sessions) — the
        statements must actually differ. The gate fails closed and does
        NOT spend REPL budget on the trivial equivalence."""
        verifier = _make_verifier()
        # Distinct channels A/B and distinct sessions (all attestations
        # otherwise clean) — only the statement text is identical.
        result = _run_gate(
            b=_form_b(statement_lean=_PROP_A), verifier=verifier
        )
        assert result.gate_ok is False
        assert any(
            "byte-identical" in r for r in result.gate_reasons
        ), result.gate_reasons
        # Fail-fast: the tainted (trivially-equivalent) pair gets no REPL.
        assert verifier.calls == []
        assert result.block["equivalence"]["method"] == "none"
        assert result.block["dual"]["independent"] is False

    def test_byte_identical_whitespace_only_diff_is_rejected(self):
        """Whitespace-only reformatting is still trivial — the A==B guard
        normalizes whitespace before comparing (a reformat is not
        independence)."""
        spaced = _PROP_A.replace(" ", "  ")
        result = _run_gate(b=_form_b(statement_lean=spaced))
        assert result.gate_ok is False
        assert any("byte-identical" in r for r in result.gate_reasons)

    def test_award_rule_also_rejects_identical_a_b(self):
        """The A==B guard lives in _dual_reasons, so faithfulness_award_ok
        (which re-derives every element from the block) denies an
        identical-A/B record too — not just the gate runner."""
        block = _run_gate(b=_form_b(statement_lean=_PROP_A)).to_faithfulness_block()
        ok, reasons = faithfulness_award_ok(block, publishable=False)
        assert ok is False
        assert any("byte-identical" in r for r in reasons)


# ---------------------------------------------------------------------------
# Element 2 — Lean equivalence over the D-2 hardened envelopes
# ---------------------------------------------------------------------------


class TestEquivalenceCheck:
    def test_both_directions_sound_establishes(self):
        result = _run_gate()
        equiv = result.block["equivalence"]
        assert equiv["established"] is True
        assert equiv["method"] == "lean-iff"
        assert equiv["forward"]["award_ok"] is True
        assert equiv["backward"]["award_ok"] is True
        assert equiv["forward"]["transcript_sha256"]
        assert equiv["backward"]["transcript_sha256"]
        assert result.block["budget"]["lean_queries"] == 2
        assert result.gate_ok is True

    def test_quantifier_swap_mutant_is_caught(self):
        """NEGATIVE (mandated): a quantifier-swapped mis-formalization
        (∀n ∃m vs ∃m ∀n) leaves the forward implication unprovable —
        the gate MUST fail."""
        swap = _form_b(statement_lean="∃ m : Nat, ∀ n : Nat, n < m")
        result = _run_gate(
            a=_form_a(statement_lean="∀ n : Nat, ∃ m : Nat, n < m"),
            b=swap,
            verifier=_make_verifier(fwd="error", bwd="ok"),
        )
        assert result.gate_ok is False
        assert result.block["equivalence"]["established"] is False
        assert any("forward direction not proved" in r for r in result.gate_reasons)

    def test_strict_vs_nonstrict_mutant_is_caught(self):
        """NEGATIVE (mandated): a ≤/< strength mutation fails one
        direction — the gate MUST fail."""
        result = _run_gate(
            a=_form_a(statement_lean="∀ n : Nat, 1 ≤ n → n ≤ n ^ 2"),
            b=_form_b(statement_lean="∀ n : Nat, 1 ≤ n → n < n ^ 2"),
            verifier=_make_verifier(fwd="error", bwd="ok"),
        )
        assert result.gate_ok is False
        assert any("forward direction not proved" in r for r in result.gate_reasons)

    def test_backward_failure_named(self):
        result = _run_gate(verifier=_make_verifier(fwd="ok", bwd="error"))
        assert result.gate_ok is False
        assert any("backward direction not proved" in r for r in result.gate_reasons)

    def test_native_decide_direction_is_no_equivalence(self):
        """The D-2 wire-in: a direction 'proved' with native_decide is
        kernel-ok but NOT award-clean — the equivalence must not be
        established on it."""
        result = _run_gate(verifier=_make_verifier(fwd="flagged", bwd="ok"))
        assert result.block["equivalence"]["forward"]["award_ok"] is False
        assert result.block["equivalence"]["established"] is False
        assert result.gate_ok is False

    def test_dirty_closure_direction_is_no_equivalence(self):
        result = _run_gate(verifier=_make_verifier(fwd="ok", bwd="dirty-closure"))
        assert result.block["equivalence"]["established"] is False
        assert result.gate_ok is False

    def test_no_verifier_never_establishes(self):
        result = _run_gate(verifier=None)
        assert result.gate_ok is False
        assert result.block["equivalence"]["established"] is False
        assert any("no Lean verifier wired" in r for r in result.gate_reasons)

    def test_snippet_builder_shapes(self):
        fwd = equivalence_snippet("P", "Q", direction="fwd", tactic="tauto")
        bwd = equivalence_snippet("Q", "P", direction="bwd", tactic="tauto")
        assert fwd.startswith(f"theorem {FWD_NAME} : (P) → (Q) := by")
        assert bwd.startswith(f"theorem {BWD_NAME} : (Q) → (P) := by")
        assert "tauto" in fwd
        with pytest.raises(ValueError, match="direction"):
            equivalence_snippet("P", "Q", direction="sideways")

    def test_default_tactic_never_admits(self):
        """`plausible` ADMITS goals via sorry (the D-5 live pin) — it
        must never appear in the default equivalence portfolio."""
        assert "plausible" not in DEFAULT_EQUIV_TACTIC
        assert "sorry" not in DEFAULT_EQUIV_TACTIC

    def test_normalize_lean(self):
        assert normalize_lean("  ∀ n : Nat,\n   n + 0 = n ") == "∀ n : Nat, n + 0 = n"


# ---------------------------------------------------------------------------
# Element 3 — blind back-translation + skeptic diff
# ---------------------------------------------------------------------------


class TestBackTranslationAndSkepticDiff:
    def test_missing_back_translation_fails(self):
        result = _run_gate(bt=None)
        assert result.gate_ok is False
        assert any("no blind back-translation" in r for r in result.gate_reasons)

    def test_translator_saw_original_fails(self):
        result = _run_gate(bt=_bt(translator_saw_original=True))
        assert result.gate_ok is False
        assert any("not blind" in r for r in result.gate_reasons)

    def test_translator_in_formalizer_session_fails(self):
        result = _run_gate(bt=_bt(session_id="sess-a"))
        assert result.gate_ok is False
        assert any("formalizer session" in r for r in result.gate_reasons)

    def test_rendered_statement_must_match_channel(self):
        result = _run_gate(bt=_bt(rendered_statement_lean=_PROP_B))
        assert result.gate_ok is False
        assert any("different Lean statement" in r for r in result.gate_reasons)

    def test_rendered_statement_whitespace_insensitive(self):
        result = _run_gate(bt=_bt(rendered_statement_lean="∀ n : Nat,\n  n + 0   = n"))
        assert not any("different Lean statement" in r for r in result.gate_reasons)
        assert result.gate_ok is True

    def test_skeptic_mismatch_fails_with_discrepancies(self):
        result = _run_gate(
            sd=_sd(
                verdict="mismatch",
                discrepancies=("original says strict inequality; rendering says non-strict",),
            )
        )
        assert result.gate_ok is False
        assert any("strict inequality" in r for r in result.gate_reasons)

    def test_skeptic_must_see_original(self):
        result = _run_gate(sd=_sd(saw_original=False))
        assert result.gate_ok is False
        assert any("ORIGINAL claim" in r for r in result.gate_reasons)

    def test_missing_skeptic_diff_fails(self):
        result = _run_gate(sd=None)
        assert result.gate_ok is False
        assert any("no skeptic diff" in r for r in result.gate_reasons)


# ---------------------------------------------------------------------------
# Element 4 — human sign-off (automation locked out)
# ---------------------------------------------------------------------------


class TestHumanSignoff:
    def test_gate_always_emits_unsigned(self):
        result = _run_gate()
        assert result.gate_ok is True
        assert result.block["human_signoff"] == {
            "signed": False,
            "by": None,
            "at": None,
            "note": None,
        }

    def test_signer_requires_operator_tripwire(self):
        block = _run_gate().to_faithfulness_block()
        with pytest.raises(PermissionError, match="operator-only"):
            record_human_signoff(block, by="chris.dare")

    def test_signer_requires_identity(self):
        block = _run_gate().to_faithfulness_block()
        with pytest.raises(ValueError, match="signer identity"):
            record_human_signoff(block, by="", i_am_a_human_operator=True)

    def test_signer_refuses_failed_gate(self):
        """A human signature must never launder a failed gate."""
        failed = _run_gate(verifier=_make_verifier(fwd="error")).to_faithfulness_block()
        with pytest.raises(ValueError, match="refusing to sign"):
            record_human_signoff(failed, by="chris.dare", i_am_a_human_operator=True)

    def test_signing_returns_copy_with_checkbox(self):
        block = _run_gate().to_faithfulness_block()
        signed = record_human_signoff(
            block, by="chris.dare", note="reviewed", i_am_a_human_operator=True
        )
        assert signed["human_signoff"]["signed"] is True
        assert signed["human_signoff"]["by"] == "chris.dare"
        assert signed["human_signoff"]["at"]
        # The gate's own block is not mutated.
        assert block["human_signoff"]["signed"] is False


# ---------------------------------------------------------------------------
# THE AC-D.5 award-rule tests (pure; no LLM, no REPL)
# ---------------------------------------------------------------------------


class TestAwardRule:
    def test_complete_record_awards_proven_formal(self):
        # A complete record awards proven-formal ONLY when the KERNEL
        # confirmed the proof proves a gate-checked formalization
        # (findings #1/#2; durable P1 kernel-decides fix). The orchestrator
        # records that decision as `proves_formalization` — here True.
        verdict, reasons = award_statement_verdict(
            _direction_env("ok", "even_add_even"),
            _signed_ok_block(),
            proves_formalization=True,
        )
        assert verdict == "proven-formal"
        assert reasons == []

    @pytest.mark.parametrize(
        "missing",
        ["dual", "equivalence", "back_translation", "skeptic_diff"],
    )
    def test_missing_any_element_caps_at_plausible_unverified(self, missing):
        """AC-D.5: a run missing ANY element caps at plausible-unverified
        — asserted here as an award-rule unit test, not convention."""
        block = _signed_ok_block()
        del block[missing]
        verdict, reasons = award_statement_verdict(
            _direction_env("ok", "even_add_even"), block
        )
        assert verdict == "plausible-unverified"
        assert any("AC-D.5" in r for r in reasons)

    def test_no_faithfulness_record_caps(self):
        verdict, reasons = award_statement_verdict(
            _direction_env("ok", "even_add_even"), None
        )
        assert verdict == "plausible-unverified"
        assert any("L1 gate did not run" in r for r in reasons)

    def test_unsigned_publishable_caps(self):
        unsigned = _run_gate().to_faithfulness_block()
        verdict, reasons = award_statement_verdict(
            _direction_env("ok", "even_add_even"), unsigned, publishable=True
        )
        assert verdict == "plausible-unverified"
        assert any("checkbox" in r for r in reasons)

    def test_unsigned_internal_run_may_award(self):
        unsigned = _run_gate().to_faithfulness_block()
        verdict, _ = award_statement_verdict(
            _direction_env("ok", "even_add_even"),
            unsigned,
            publishable=False,
            proves_formalization=True,
        )
        assert verdict == "proven-formal"

    def test_equivalence_not_established_caps(self):
        block = _run_gate(verifier=_make_verifier(fwd="error")).to_faithfulness_block()
        verdict, _ = award_statement_verdict(
            _direction_env("ok", "even_add_even"), block, publishable=False
        )
        assert verdict == "plausible-unverified"

    def test_syntactic_identity_method_is_not_award_eligible(self):
        block = _signed_ok_block()
        block["equivalence"]["method"] = "syntactic-identity"
        ok, reasons = faithfulness_award_ok(block)
        assert ok is False
        assert any("not award-eligible" in r for r in reasons)

    def test_gate_ok_flag_is_never_trusted(self):
        """Tampering with the recorded per-direction award while leaving
        gate_ok=true must still deny — the award rule re-derives."""
        block = _signed_ok_block()
        block["equivalence"]["forward"]["award_ok"] = False
        assert block["gate_ok"] is True  # the tamper leaves the flag
        ok, reasons = faithfulness_award_ok(block)
        assert ok is False
        assert any("forward direction" in r for r in reasons)

    def test_unsound_formal_result_abstains(self):
        verdict, reasons = award_statement_verdict(
            _direction_env("error", "even_add_even"), _signed_ok_block()
        )
        assert verdict == "abstained"
        assert any("formal lane" in r for r in reasons)

    def test_award_ok_fail_closed_on_empty(self):
        ok, reasons = faithfulness_award_ok({})
        assert ok is False
        assert reasons


# ---------------------------------------------------------------------------
# THE statement-linkage award gate (findings #1/#2): the second link of
# the proof chain — the kernel-proved statement must BE one of the two
# gate-checked formalizations. formal_award_ok proves *some* statement
# is kernel-clean; faithfulness_award_ok proves claim⇔A⇔B; only this
# predicate establishes formalization⇔proof. A kernel-clean proof of an
# UNRELATED statement (e.g. 1+1=2) must never earn proven-formal.
# ---------------------------------------------------------------------------


class TestStatementLinkage:
    """The proof-side link (findings #1/#2), now decided by THE KERNEL
    (durable P1 kernel-decides fix). :func:`proof_statement_linked` is
    pure over the BOOLEAN the orchestrator recorded from the per-award
    kernel check ``example : <formalization> := @<decl>`` — the string
    comparison (which could not tell ``∃ x:ℝ,…`` from ``∃ x:ℚ,…``) is
    gone. The kernel's decision (collision denied, unrelated proof
    denied, vacuous binder denied, defeq phrasing linked) is exercised
    end-to-end in ``tests/test_proving_orchestrator.py`` (fake kernel) and
    the gated ``*_lean.py`` batteries (real kernel)."""

    def test_kernel_confirmed_link_is_linked(self):
        ok, reasons = proof_statement_linked(True, _signed_ok_block())
        assert ok is True
        assert reasons == []

    def test_kernel_denied_link_is_not_linked(self):
        """The kernel did NOT accept the proof against any gate-checked
        formalization (proves_formalization False) — e.g. the ℝ/ℚ
        collision, an unrelated proof, or a vacuous-binder proof. Denied."""
        ok, reasons = proof_statement_linked(False, _signed_ok_block())
        assert ok is False
        assert any("kernel did not confirm" in r for r in reasons)

    def test_missing_boolean_fails_closed(self):
        """``None``/absent (kernel check not run, errored, or a
        prior-result award with no snippet) — fail closed, never assumed
        linked."""
        for missing in (None, "true", 1):
            ok, reasons = proof_statement_linked(missing, _signed_ok_block())
            assert ok is False
            assert reasons

    def test_block_without_formalizations_fails_closed(self):
        """Even a True boolean fails closed when the block carries no
        formalizations to have been proved (structural sanity guard)."""
        ok, reasons = proof_statement_linked(True, {"dual": {"records": []}})
        assert ok is False
        assert any("no formalization statements" in r for r in reasons)

    def test_award_refuses_unlinked_proof_even_when_signed(self):
        """The full-chain regression: a complete, signed faithfulness
        record whose proof the KERNEL did not confirm proves a
        gate-checked formalization caps at plausible-unverified — the
        exact hole findings #1/#2 describe (a signed publishable
        proven-formal for an unlinked proof), now the ℝ/ℚ collision too."""
        verdict, reasons = award_statement_verdict(
            _direction_env("ok", "cheat"),
            _signed_ok_block(),
            publishable=True,
            proves_formalization=False,
        )
        assert verdict == "plausible-unverified"
        assert any("statement linkage" in r for r in reasons)

    def test_award_refuses_when_no_boolean_supplied(self):
        """Absent the kernel-decision boolean (e.g. a prior-result award
        with no snippet to kernel-check) the linkage is unestablished —
        fail closed."""
        verdict, reasons = award_statement_verdict(
            _direction_env("ok", "even_add_even"),
            _signed_ok_block(),
            publishable=False,
        )
        assert verdict == "plausible-unverified"
        assert any("statement linkage" in r for r in reasons)


# ---------------------------------------------------------------------------
# Bundle wiring: the two D-3 schema laws + recordable failures
# ---------------------------------------------------------------------------


class TestBundleWiring:
    def test_proven_formal_requires_faithfulness_record(self):
        with pytest.raises(ContractValidationError) as exc:
            validate_evidence_bundle(_bundle_doc(verdict="proven-formal"))
        assert "faithfulness" in str(exc.value)

    def test_proven_formal_with_signed_block_validates(self):
        validate_evidence_bundle(
            _bundle_doc(verdict="proven-formal", faithfulness=_signed_ok_block())
        )

    def test_publishable_proven_formal_requires_signed_checkbox(self):
        unsigned = _run_gate().to_faithfulness_block()
        with pytest.raises(ContractValidationError):
            validate_evidence_bundle(
                _bundle_doc(
                    verdict="proven-formal", publishable=True, faithfulness=unsigned
                )
            )
        validate_evidence_bundle(
            _bundle_doc(
                verdict="proven-formal",
                publishable=True,
                faithfulness=_signed_ok_block(),
            )
        )

    def test_signed_without_identity_rejected_by_schema(self):
        block = _signed_ok_block()
        block["human_signoff"]["by"] = None
        with pytest.raises(ContractValidationError):
            validate_evidence_bundle(
                _bundle_doc(verdict="proven-formal", faithfulness=block)
            )

    def test_failed_gate_is_recordable_in_lower_verdicts(self):
        """Honest reporting: a failed faithfulness block rides along in
        a plausible-unverified bundle without schema complaint."""
        failed = _run_gate(verifier=_make_verifier(fwd="error")).to_faithfulness_block()
        assert failed["gate_ok"] is False
        validate_evidence_bundle(
            _bundle_doc(verdict="plausible-unverified", faithfulness=failed)
        )

    def test_dual_requires_exactly_two_records(self):
        block = _signed_ok_block()
        block["dual"]["records"] = block["dual"]["records"][:1]
        with pytest.raises(ContractValidationError):
            validate_evidence_bundle(
                _bundle_doc(verdict="proven-formal", faithfulness=block)
            )

    def test_non_formal_verdicts_need_no_faithfulness(self):
        validate_evidence_bundle(_bundle_doc(verdict="abstained"))
        validate_evidence_bundle(_bundle_doc(verdict="plausible-unverified"))

    def test_refuted_law_unchanged(self):
        """The AC-D.7 law from the schema's first conditional still
        holds after the allOf restructure."""
        with pytest.raises(ContractValidationError) as exc:
            validate_evidence_bundle(_bundle_doc(verdict="refuted"))
        assert "counterexample" in str(exc.value)

    def test_proven_formal_example_validates(self):
        doc = load_example("evidence-bundle.v0.proven-formal.example.json")
        validate_evidence_bundle(doc)
        payload = doc["payload"]
        assert payload["verdict"] == "proven-formal"
        assert payload["publishable"] is True
        faith = payload["faithfulness"]
        assert faith["human_signoff"]["signed"] is True
        assert faith["equivalence"]["method"] == "lean-iff"
        # The example's recorded evidence passes the pure award rule.
        ok, reasons = faithfulness_award_ok(faith)
        assert ok, reasons

    def test_example_mutation_is_caught(self):
        doc = copy.deepcopy(load_example("evidence-bundle.v0.proven-formal.example.json"))
        doc["payload"]["faithfulness"]["human_signoff"]["signed"] = False
        with pytest.raises(ContractValidationError):
            validate_evidence_bundle(doc)
