"""Regression: kernel_decides_linked must be self-sufficiently sound.

Stage-3 terminating probe found that a ``sorryAx`` TERM proof of a false
proposition (``:= @sorryAx P false``) emits only a ``declaration uses
'sorry'`` WARNING, so the handler derives ``status == "ok"`` /
``compilation_success is True`` while the axiom-closure audit on the SAME
envelope flags the taint (``axiom_closure_ok is False``). Before the
hardening ``kernel_decides_linked`` read only status/compile and GRANTED;
it must now also consult the closure and DENY. It was harmless end-to-end
only because ``formal_award_ok`` / ``witness_ok`` independently caught
``sorryAx`` — this test pins the predicate as sound on its own terms.
"""
from server.lean_soundness import kernel_decides_linked


def test_sorryax_taint_denies_even_when_status_ok():
    # The exact terminating-probe envelope shape: clean status/compile,
    # but the closure audit flagged sorryAx.
    tainted = {
        "status": "ok",
        "compilation_success": True,
        "soundness": {"axiom_closure": ["sorryAx"], "axiom_closure_ok": False},
    }
    assert kernel_decides_linked(tainted) is False


def test_clean_axiom_closure_still_links():
    # A legitimate proof using only allowed axioms → closure OK → links.
    clean = {
        "status": "ok",
        "compilation_success": True,
        "soundness": {
            "axiom_closure": ["propext", "Classical.choice", "Quot.sound"],
            "axiom_closure_ok": True,
        },
    }
    assert kernel_decides_linked(clean) is True


def test_no_soundness_block_falls_back_to_status_compile():
    # Absent soundness block: status/compile decide (unchanged behavior;
    # a sorryAx proof always DOES carry the block, per the live probe).
    assert kernel_decides_linked({"status": "ok", "compilation_success": True}) is True


def test_type_mismatch_and_sorry_tactic_still_denied():
    assert kernel_decides_linked({"status": "error", "compilation_success": False}) is False
    assert kernel_decides_linked({"status": "sorry", "compilation_success": False}) is False
    assert kernel_decides_linked(None) is False
    assert kernel_decides_linked({"status": "ok", "compilation_success": None}) is False
