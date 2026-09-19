"""The single statement-linkage choke-point every verdict-award path
passes through (stage3/proving-r3 — WS-D round-3 soundness class fix).

Motivation (the class bug, not the instance)
---------------------------------------------

Statement linkage — *is the evidence actually tied to THIS claim?* — was
bolted onto the pipeline one path at a time, and every review round found
the next unlinked path:

- Round 1 gave the **proof** side an exact linkage invariant
  (:func:`server.proving.faithfulness.proof_statement_linked`): a
  ``proven-formal`` requires the kernel-proved statement to match a
  gate-checked formalization. A kernel proof of ``1 + 1 = 2`` could no
  longer ride a faithful Goldbach A/B pair to ``proven-formal``.
- Round 2 found the **refutation** mirror (a kernel-clean witness of an
  UNRELATED true fact, e.g. ``¬ Prime 4`` against "infinitely many
  primes", confidently ``refuted`` a true theorem) but fixed it only
  with an *escalation net* keyed on ``known_truth is True`` — which fires
  on KAT controls but is inert on real ``known_truth = null`` tasks.

The pattern ("each round finds the sibling of the last fix") is the
signature of a missing invariant, not of two isolated bugs. This module
is that invariant, made structural: **no verdict-award path may emit a
confident verdict without a recorded, checked linkage between its
evidence and the claim.** :func:`award_linked_verdict` is the one
function through which ``run_proving_pipeline`` routes EVERY verdict
(proven-formal, refuted-via-lean-witness, refuted-via-CAS,
refuted-via-search, and the informal verdicts). A path that forgets to
establish linkage is capped here, not shipped.

Two linkage models — because the two sides are not symmetric
------------------------------------------------------------

**Proof side — the kernel decides equality.** "The proof proves the
claim's formalization" is decided by THE KERNEL, not a string: the
orchestrator's award path runs ``example : <formalization> := @<decl>``
for each gate-checked formalization and records whether the kernel
accepts one (durable P1 soundness fix — pretty-print string equality let
``∃ x : ℝ, x*x=2`` match ``∃ x : ℚ, x*x=2`` because Lean elides the
∃-binder type, a live CRITICAL false-accept). Folded into the choke-point
via :func:`proof_award_linkage`, which re-checks
:func:`proof_statement_linked` over the recorded boolean so an unlinked
``proven-formal`` is capped even if the upstream award rule is ever
bypassed.

**Refutation side — NO clean syntactic invariant** (the caveat math-r2
got right). A sound witness legitimately proves an *auxiliary* arithmetic
fact that only *implies* ``¬claim`` through math the kernel never sees in
the snippet — e.g. ``kat-fm-03``'s witness proves ``2^32 + 1 = 641 *
6700417``, NOT ``¬(all Fermat numbers are prime)``. A naive "witness
statement must equal ``¬claim``" compare would DENY the acceptance
suite's own FALSE trio. So the refutation model is the one math-r2
recommends: the ProofTask author **declares**, per skeptic check, which
claim-derived proposition that counterexample discharges (the
``discharges`` field on ``skeptic_checks.lean[]`` / ``.cas[]``), and the
gate verifies

  1. **kernel linkage** — THE KERNEL decides that the witness's
     declaration proves the declared target. Durable P1 soundness fix:
     the orchestrator/skeptic layer runs
     ``example : <discharges.proposition> := @<witness_decl>`` in the
     witness's env (see :func:`server.lean_soundness.kernel_check_snippet`
     / :func:`server.lean_soundness.kernel_decides_linked`) and records
     the boolean ``proves_declared_proposition``; this predicate requires
     it ``True``. The kernel decides DEFINITIONAL EQUALITY, so a witness
     of the TRUE ``∃ x : ℝ, x*x=2`` can no longer pass as a declared FALSE
     ``∃ x : ℚ, x*x=2`` — the two delaborate to the identical string but
     are not defeq (a live CRITICAL false-accept the old pretty-print
     compare admitted); conversely a defeq author phrasing still links.
     Because ``@decl`` must inhabit the WHOLE type, a vacuous-hypothesis
     witness (full ``∀`` type) cannot pass as its bare conclusion; a
     phantom in a comment/string or an unrelated trailing decl has no
     queryable name so the check cannot be built and fails closed. The
     untrusted author cannot satisfy it without the kernel actually
     proving that proposition, so it cannot reincarnate the hole; and
  2. **obligation linkage** — the declared target is a recorded,
     claim-linked refutation obligation (a structured, auditable
     attestation on the same check), mirroring how the faithfulness gate
     ties a formalization to the claim through recorded attestations
     rather than a machine proof it cannot perform pre-formalization.

A refutation with no valid declared-and-kernel-checked linkage does NOT
earn a confident ``refuted`` — it is capped (to ``abstained`` by default;
the orchestrator routes the capped case to the escalation net), exactly
as an unlinked proof caps at ``plausible-unverified``.

**ONE rule for every source (round-3 class fix).** Round 3 removed the
per-kind carve-outs that were the surviving siblings of the round-1/2
holes: a confident ``refuted`` requires kernel linkage from ANY source.
``search`` hits are ``kernel_confirmed=False`` (the falsification tactic
reports a hit, it kernel-proves nothing) — the earlier "linked BY
CONSTRUCTION, the snippet asserts the ORIGINAL claim" assumption was
never verified (the snippet is author-supplied with no schema tie to
``statement_latex``), so it is gone. ``cas`` hits are likewise
``kernel_confirmed=False`` (evaluation-checked) — the earlier "the
recorded declaration is the only linkage" acceptance is gone, because the
author supplies both the code and the declaration. Both now fail the
kernel-linkage half and are capped/escalated. Only a ``kernel_confirmed``
witness whose kernel-proved statement matches the declared proposition
clears the choke-point; a search/CAS refutation that must stand needs a
companion kernel witness that does.

Honest residual (stated, not hidden): the *semantic* half of obligation
linkage — that the declared target genuinely entails ``¬claim`` — is an
attestation, not a machine proof, because the skeptic lane runs before
any formalization exists (AC-D.10) and receives no formalization to
kernel-check against. That is the SAME trust grain the faithfulness gate
uses for claim↔formalization (recorded attestations + human sign-off),
and it is backstopped by the KAT red-alarm + the orchestrator's
``known_truth`` escalation. What round 3 closes is the *machine* half —
the kernel link counterexample↔declared-target, required now of EVERY
source — which the search/CAS carve-outs skipped, and the structural
guarantee that no path skips the check.

Like the rest of ``server/proving/``, this module registers nothing on
the MCP surface (BP1-safe) and never talks to an LLM or a REPL: it is a
pure function over recorded evidence dicts (AC-D.13 discipline).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from server.proving.faithfulness import proof_statement_linked

#: Verdicts that assert the claim is established TRUE — the proof side of
#: the choke-point (linked via a gate-checked formalization).
_PROVEN_VERDICTS: frozenset[str] = frozenset(
    {"proven-formal", "proven-informal-checked"}
)

#: The verdict that asserts the claim is established FALSE — the
#: refutation side of the choke-point (linked via a declared-and-checked
#: discharged proposition).
_REFUTING_VERDICTS: frozenset[str] = frozenset({"refuted"})

#: Every counterexample source the skeptic lane can emit. ALL of them
#: carry an AUTHOR-SUPPLIED snippet/code with no schema-level tie to the
#: claim (proof-task.v0.3: ``skeptic_checks.lean[].snippet`` /
#: ``.cas[].code`` are ``minLength: 1`` only), so NONE is linked to the
#: claim "by construction" — the round-3 class fix (findings: search /
#: CAS unlinked refutation) removed the ``lean-search`` carve-out that
#: assumed, without ever verifying, that a search snippet asserts the
#: ORIGINAL claim. A confident ``refuted`` from ANY source now requires
#: the machine linkage below; a source that cannot supply it is
#: capped/escalated, exactly like an unlinked witness.
_KNOWN_COUNTEREXAMPLE_SOURCES: frozenset[str] = frozenset(
    {"lean-witness", "lean-search", "cas-sympy"}
)

#: The cap a confident verdict falls to when its linkage is not
#: established. Mirrors the proof side's ``plausible-unverified`` cap:
#: over-rejection costs a re-run, accepting an unlinked verdict is the
#: soundness hole this module exists to remove.
REFUTATION_LINKAGE_CAP = "abstained"
PROOF_LINKAGE_CAP = "plausible-unverified"


@dataclass(frozen=True)
class LinkageOutcome:
    """The choke-point's decision for one verdict.

    ``verdict`` is the linkage-checked verdict (possibly capped down from
    the proposed one); ``linked`` is whether the evidence↔claim linkage
    was established; ``reasons`` explains a cap (empty when linked or when
    the verdict carries no linkage obligation, e.g. ``abstained``).
    """

    verdict: str
    confidence: str
    linked: bool
    reasons: list[str]


def _declared_target(check: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """The ``discharges`` declaration recorded on a skeptic check, or
    ``None`` when absent/malformed (fail-closed — a missing declaration
    denies the confident refuted, never opens it)."""
    if not isinstance(check, Mapping):
        return None
    declared = check.get("discharges")
    return declared if isinstance(declared, Mapping) else None


def refutation_statement_linked(
    counterexample: Mapping[str, Any] | None,
) -> tuple[bool, list[str]]:
    """Machine-check the refutation analogue of
    :func:`proof_statement_linked`: is the counterexample's evidence
    tied, through a recorded-and-kernel-checked declaration, to a
    refutation obligation for THIS claim?

    Pure, LLM-free, REPL-free (AC-D.13 grain), fail-closed. The
    ``counterexample`` dict is the skeptic lane's own record (see
    :meth:`server.proving.skeptic.SkepticLaneResult` construction),
    augmented by the lane with:

    - ``source`` — ``lean-witness`` / ``lean-search`` / ``cas-sympy``;
    - ``proves_declared_proposition`` — the BOOLEAN the orchestrator/
      skeptic layer recorded from the kernel check
      ``example : <discharges.proposition> := @<witness_decl>`` (the
      durable P1 kernel-decides result; ``None``/absent for search/CAS,
      which have no queryable declaration), and
    - ``discharges`` — the author's structured declaration lifted from
      the originating ``skeptic_checks`` entry:
      ``{"proposition": <lean text>, "refutes_claim": true,
      "justification": <why it entails ¬claim>}``.
    - ``proved_statement_lean`` — the KERNEL-reported elaborated type of
      the witness's declaration (audit/display only now; the linkage
      DECISION is the boolean above, not a string compare).

    Linkage rules (round-3 class fix — ONE rule for every source; no
    per-kind carve-out):

    A confident ``refuted`` requires BOTH halves, whatever the source —

    1. **obligation linkage** — a ``discharges`` declaration exists,
       marks ``refutes_claim: true``, and names a non-empty
       ``proposition`` (recorded, auditable, mirrors the faithfulness
       gate's attestation grain); AND
    2. **kernel linkage** — the counterexample is ``kernel_confirmed`` and
       THE KERNEL accepted ``example : <proposition> := @<witness_decl>``
       (``proves_declared_proposition is True``), never the author's word
       nor a pretty-print string compare. An untrusted author cannot
       satisfy this without the kernel actually proving the declared
       proposition, and the ℝ-vs-ℚ pretty-print collision is now denied
       because the kernel decides definitional equality.

    The two non-kernel sources therefore cannot earn a confident
    ``refuted``:

    - **search** (``kernel_confirmed=False`` by construction — the
      falsification tactic reports a hit, it does not kernel-prove
      anything, ``skeptic.py``) FAILS the kernel-linkage half. The
      earlier "linked by construction — the snippet asserted the
      ORIGINAL claim" carve-out is GONE: that premise (search snippet ⇒
      the claim) was NEVER verified (the snippet is author-supplied with
      no schema tie to ``statement_latex``), so an author-supplied search
      snippet asserting an UNRELATED proposition confidently "refuted" a
      claim it never touched (findings: search-kind unlinked refutation,
      the 1+1=2→Goldbach / ¬Prime-4→infinitude threat model on the
      refusal axis).
    - **CAS** (``kernel_confirmed=False`` — evaluation-checked, not
      kernel-checked) likewise FAILS the kernel-linkage half. The earlier
      "the recorded declaration is the only linkage → accept" path is
      GONE: the author supplies BOTH the code and the declaration, so a
      self-consistent-but-claim-irrelevant CAS declaration confidently
      "refuted" a true claim (findings: CAS-sympy declaration-only
      linkage).

    Both are capped to :data:`REFUTATION_LINKAGE_CAP` (``abstained``) by
    :func:`award_linked_verdict` and routed to the escalation net —
    exactly as an unlinked witness is. A CAS/search *no-hit* scan is
    unaffected (it never produces ``refuted``; a completed no-hit CAS
    scan earns ``plausible-unverified`` numeric support upstream). A
    CAS/search refutation that a caller nonetheless wants to stand needs
    a machine-checkable tie — e.g. a companion kernel witness whose
    proved statement matches the declared proposition — which routes
    through the kernel-confirmed path below.

    Returns ``(linked, reasons)`` — ``reasons`` non-empty explains why
    linkage failed (drives the cap).
    """
    if not isinstance(counterexample, Mapping):
        return False, [
            "refutation linkage: no counterexample record to link to the "
            "claim (fail-closed)"
        ]
    source = counterexample.get("source")
    if source not in _KNOWN_COUNTEREXAMPLE_SOURCES:
        return False, [
            f"refutation linkage: unknown counterexample source {source!r} — "
            "fail-closed (a source with no established linkage model cannot "
            "earn a confident refuted)"
        ]

    declared = _declared_target(counterexample)
    if declared is None:
        return False, [
            "refutation linkage: the skeptic check declared no discharged "
            "proposition (skeptic_checks[].discharges) — an author-supplied "
            f"{source} counterexample must declare which claim-derived "
            "proposition it discharges, and the gate must kernel-check it, "
            "before a confident refuted is earned (findings: "
            "refutation-witness-skips-statement-linkage). Fail-closed."
        ]
    if declared.get("refutes_claim") is not True:
        return False, [
            "refutation linkage: the discharged-proposition declaration does "
            "not attest refutes_claim=true — the recorded obligation does not "
            "tie the proposition to a refutation of THIS claim (fail-closed)"
        ]
    declared_prop = declared.get("proposition")
    if not declared_prop or not isinstance(declared_prop, str):
        return False, [
            "refutation linkage: the discharged-proposition declaration names "
            "no proposition text to kernel-check the counterexample against "
            "(fail-closed)"
        ]

    # Kernel linkage — the ONE machine invariant, required of every
    # source. THE KERNEL must decide that the witness's declaration proves
    # the declared target: the orchestrator/skeptic layer ran
    # ``example : <discharges.proposition> := @<witness_decl>`` in the
    # witness's env and recorded the boolean ``proves_declared_proposition``
    # (durable P1 kernel-decides fix — see
    # ``server.lean_soundness.kernel_check_snippet`` /
    # ``kernel_decides_linked``). This REPLACES the pretty-print string
    # equality that let a witness of the TRUE ``∃ x : ℝ, x*x=2`` match a
    # declared FALSE ``∃ x : ℚ, x*x=2`` (Lean elides the ∃-binder type so
    # both render identically) — a live CRITICAL false-accept. The kernel
    # decides definitional equality, so that collision is denied while a
    # defeq author phrasing still links. A source that is not
    # kernel-confirmed (search, CAS) has no declaration for the kernel to
    # inhabit and so cannot earn a confident refuted — the round-3 class
    # fix that removed the search/CAS carve-outs (findings: search-kind +
    # CAS-sympy unlinked refutation) stands unchanged.
    if counterexample.get("kernel_confirmed") is not True:
        return False, [
            f"refutation linkage: the {source} counterexample is not "
            "kernel-confirmed, so its declared discharged proposition cannot "
            "be checked against a kernel result — an author-supplied "
            "refutation with no kernel-proved statement (search hit or CAS "
            "evaluation) cannot earn a confident refuted (findings: "
            "search-kind + CAS-sympy unlinked refutation). Fail-closed; the "
            "orchestrator routes it to abstained/escalation."
        ]
    if counterexample.get("proves_declared_proposition") is not True:
        return False, [
            "refutation linkage: THE KERNEL did not confirm the witness "
            "proves the declared discharged proposition "
            "(proves_declared_proposition is not True — the "
            "`example : <declared proposition> := @<witness decl>` kernel "
            "check did not accept, was not run, or errored; the declared "
            "string is never trusted over the kernel's verdict). The witness "
            "proves something other than what the author declared it "
            "discharges, or the witness has no queryable declaration name "
            "(anonymous example / unparseable). Fail-closed — the durable P1 "
            "kernel-decides fix (the pretty-print collision that let a ℝ "
            "witness pass as a ℚ discharge is now denied by the kernel)."
        ]
    return True, []


def proof_award_linkage(
    verdict: str,
    *,
    proves_formalization: bool | None,
    faithfulness_block: Mapping[str, Any] | None,
) -> tuple[bool, list[str]]:
    """Re-check the proof-side linkage at the choke-point (belt AND
    suspenders over :func:`award_statement_verdict`, which already caps
    internally). A ``proven-formal`` whose declaration the kernel did not
    confirm proves a gate-checked formalization (``proves_formalization``
    not ``True``) is not linked — even if some future caller reaches the
    choke-point with a ``proven-formal`` it computed without the round-1
    gate."""
    if verdict == "proven-informal-checked":
        # Not awardable at v0; the ceiling rule already prevents it. It
        # under-claims rather than asserting the wrong thing, so it
        # carries no machine linkage obligation here.
        return True, []
    return proof_statement_linked(proves_formalization, faithfulness_block)


def award_linked_verdict(
    proposed_verdict: str,
    proposed_confidence: str,
    *,
    counterexample: Mapping[str, Any] | None = None,
    proves_formalization: bool | None = None,
    faithfulness_block: Mapping[str, Any] | None = None,
) -> LinkageOutcome:
    """THE verdict-award choke-point: every verdict the pipeline emits
    passes through here, and any confident verdict whose evidence↔claim
    linkage is not established is capped.

    - ``refuted`` → :func:`refutation_statement_linked`. Unlinked ⇒ capped
      to :data:`REFUTATION_LINKAGE_CAP` (``abstained``); the orchestrator
      routes the capped case to escalation.
    - ``proven-formal`` → :func:`proof_award_linkage`. Unlinked ⇒ capped
      to :data:`PROOF_LINKAGE_CAP` (``plausible-unverified``).
    - ``proven-informal-checked`` → passes through (under-claims; not
      awardable at v0 anyway).
    - ``plausible-unverified`` / ``abstained`` → assert nothing to link;
      pass through.

    Returns the linkage-checked :class:`LinkageOutcome`. ``reasons``
    (when a cap fired) are prepended to the bundle's ``verdict_reasons``
    by the caller so the cap is auditable.
    """
    if proposed_verdict in _REFUTING_VERDICTS:
        linked, reasons = refutation_statement_linked(counterexample)
        if linked:
            return LinkageOutcome(
                verdict=proposed_verdict,
                confidence=proposed_confidence,
                linked=True,
                reasons=[],
            )
        return LinkageOutcome(
            verdict=REFUTATION_LINKAGE_CAP,
            confidence="low",
            linked=False,
            reasons=[
                "verdict-linkage choke-point: refuted capped to "
                f"{REFUTATION_LINKAGE_CAP!r} — a refutation with no valid "
                "declared-and-kernel-checked linkage to the claim must not "
                "earn a confident refuted (findings: "
                "refutation-witness-skips-statement-linkage)",
                *reasons,
            ],
        )

    if proposed_verdict in _PROVEN_VERDICTS:
        linked, reasons = proof_award_linkage(
            proposed_verdict,
            proves_formalization=proves_formalization,
            faithfulness_block=faithfulness_block,
        )
        if linked:
            return LinkageOutcome(
                verdict=proposed_verdict,
                confidence=proposed_confidence,
                linked=True,
                reasons=[],
            )
        return LinkageOutcome(
            verdict=PROOF_LINKAGE_CAP,
            confidence="low",
            linked=False,
            reasons=[
                "verdict-linkage choke-point: proven-formal capped to "
                f"{PROOF_LINKAGE_CAP!r} — the proved statement is not linked "
                "to a gate-checked formalization (findings #1/#2)",
                *reasons,
            ],
        )

    # abstained / plausible-unverified assert nothing that needs linking.
    return LinkageOutcome(
        verdict=proposed_verdict,
        confidence=proposed_confidence,
        linked=True,
        reasons=[],
    )


__all__ = [
    "PROOF_LINKAGE_CAP",
    "REFUTATION_LINKAGE_CAP",
    "LinkageOutcome",
    "award_linked_verdict",
    "proof_award_linkage",
    "refutation_statement_linked",
]
