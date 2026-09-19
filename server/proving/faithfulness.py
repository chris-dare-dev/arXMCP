"""D-3 statement-faithfulness gate — L1 (stage2/arx-d3 — WS-D;
AC-D.5/AC-D.6).

The gate answers ONE question: *does the Lean statement actually say
what the English claim says?* A kernel-checked proof of the wrong
statement is worse than no proof at all (the Erdős-misformalization
lesson, finding 05 §2.C) — so no ``proven-formal`` verdict is awardable
without a complete faithfulness record, and a run missing ANY element
caps at ``plausible-unverified`` (AC-D.5, enforced by
:func:`award_statement_verdict`, unit-tested LLM-free).

The four elements (AC-D.5)
--------------------------

1. **Dual independent formalization.** Two formalization passes over
   the same natural-language claim that must NOT share context
   (separate sessions; neither saw the other's output). The passes are
   produced upstream (D-6 orchestrator roles); the gate consumes their
   *records* and enforces the independence attestations structurally:
   distinct channels ``A``/``B``, distinct non-empty session ids,
   ``saw_original_statement`` true and ``saw_other_channel`` false on
   both. The gate is LLM-free and cannot verify an attestation's truth
   — it records everything for audit and fails closed on any missing
   or violated attestation.
2. **Lean equivalence check.** The two formalizations must be proved
   equivalent *by the kernel*: one obligation per direction
   (``theorem d3_gate_equiv_fwd : (A) → (B)`` and the reverse),
   executed through the injected ``lean_verify`` handler so every
   direction carries the full D-2 hardened envelope, and accepted only
   when :func:`server.lean_soundness.formal_award_ok` passes on BOTH
   directions (kernel-accepted, axiom closure within the trust base,
   no forbidden flags — an equivalence "proved" by ``sorry`` or a
   smuggled axiom is no equivalence). Definitionally-equal
   formalizations close instantly on the ``exact fun h => h`` rung of
   the default tactic portfolio, so identity needs no special path.
   Anything the portfolio cannot prove is NOT established — fail
   closed. Known limitation (recorded here deliberately): material
   equivalence of two *independently true* statements is always
   provable, so the equivalence check alone cannot distinguish "same
   meaning" from "both true" — that is exactly why the
   back-translation diff and the human sign-off exist as further
   layers, and why none of the four elements may substitute for
   another.
3. **Blind back-translation.** A translator that has NOT seen the
   original English renders the Lean statement back into English; a
   skeptic (which HAS seen the original) diffs the rendering against
   the original claim. The gate enforces the blindness structurally:
   ``translator_saw_original`` false, translator session distinct from
   both formalizer sessions, and the rendered Lean text byte-matching
   (modulo whitespace) the channel's recorded formalization — a
   translator handed a *different* statement proves nothing.
4. **Human sign-off.** A human checkbox recorded in the EvidenceBundle
   before ANY publishable ``proven-formal`` verdict. **No automation
   may set it**: :func:`run_faithfulness_gate` always emits
   ``signed: false``; the ONLY constructor of a signed record is
   :func:`record_human_signoff`, which is operator-invoked (console /
   CLI), requires the literal ``i_am_a_human_operator=True`` keyword
   (a grep-able tripwire, not a proof of humanity), and refuses to
   sign a record whose machine-checkable elements do not pass. The
   D-6 orchestrator MUST NOT call it — binding rule, asserted by the
   award-path tests and by this module never calling it itself.

Like ``server/kat.py`` and the D-5 skeptic lane, this module registers
nothing on the MCP surface (BP1-safe) and never talks to an LLM; the
Lean side goes through an injected async verifier (production callers
pass ``server.handlers.lean_verify.handle_lean_verify``; unit tests
inject fakes).

Design references: acceptance-criteria.md AC-D.5/AC-D.6, finding 05
§2.C/§4.3, HANDOFF.md §3 (arx-d3), the D-2 award predicate
(``server.lean_soundness.formal_award_ok``).
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from server.lean_soundness import formal_award_ok

logger = logging.getLogger(__name__)

#: Async verifier signature: ``(snippet, imports) -> lean_verify result``
#: (same injection grain as the D-5 skeptic lane).
LeanVerify = Callable[[str, list[str]], Awaitable[Mapping[str, Any]]]

GATE_VERSION = "1"

#: The two independent formalization channels. Exactly two, by design:
#: "dual" is the contract, not "n-way".
CHANNELS: tuple[str, str] = ("A", "B")

#: Equivalence-record methods. The v1 gate only ever emits ``lean-iff``
#: (established) or ``none`` (not established); ``syntactic-identity``
#: is reserved in the bundle schema for a future documented-defeq path
#: but is NOT award-eligible (see :func:`faithfulness_award_ok`).
EQUIV_METHODS: tuple[str, ...] = ("lean-iff", "syntactic-identity", "none")

DIFF_VERDICTS: tuple[str, str] = ("match", "mismatch")

#: Names of the per-direction equivalence obligations. Simple ASCII
#: identifiers at top level so the D-2 axiom audit name-extracts and
#: audits them (an unauditable equivalence proof denies the award —
#: fail closed).
FWD_NAME = "d3_gate_equiv_fwd"
BWD_NAME = "d3_gate_equiv_bwd"

#: Default equivalence tactic portfolio, live-probed on the D-1 mathlib
#: REPL (v4.30.0-rc2): ``exact fun h => h`` closes defeq/alpha-renamed
#: pairs instantly; ``tauto``/``aesop`` handle propositional
#: rephrasings; the ``solve_by_elim`` rungs close hypothesis-shuffled
#: and Even/Odd↔mod-2 rephrasings; every rung fails in well under a
#: second on non-equivalent mutant pairs (probed: quantifier swap,
#: strict-vs-non-strict, hypothesis-dropped). The ``norm_num`` rungs
#: carry a ``; done`` guard — probed live: bare ``norm_num`` can
#: simplify a sub-term WITHOUT closing the goal and still "succeed",
#: which would win the ``first`` race and end the block with unsolved
#: goals; ``done`` forces close-or-roll-back so later rungs stay
#: reachable. Callers (the D-6 tactician) may pass a stronger
#: per-direction tactic; soundness never depends on the portfolio — an
#: unprovable direction fails the gate no matter what tactic text is
#: supplied. ``plausible`` (which ADMITS goals via sorry) must never be
#: added here; if it ever is, the closure audit still catches the
#: resulting ``sorryAx``.
DEFAULT_EQUIV_TACTIC = (
    "first\n"
    "    | exact fun h => h\n"
    "    | tauto\n"
    "    | omega\n"
    "    | decide\n"
    "    | (norm_num; done)\n"
    "    | (intros; omega)\n"
    "    | (intros; norm_num; done)\n"
    "    | (intros; solve_by_elim)\n"
    "    | (intros; simp only [Nat.even_iff, Nat.odd_iff] at *; solve_by_elim)\n"
    "    | aesop"
)

_WS_RE = re.compile(r"\s+")


def normalize_lean(text: str) -> str:
    """Whitespace-collapsed form of a Lean fragment (comparison only —
    never fed back to Lean; deliberately NOT a lexer)."""
    return _WS_RE.sub(" ", text).strip()


def _require_nonempty(value: Any, field: str, owner: str) -> None:
    if not value or not isinstance(value, str):
        raise ValueError(f"{owner}.{field} must be a non-empty string")


@dataclass(frozen=True)
class FormalizationRecord:
    """One independent formalization pass (produced upstream; the gate
    consumes the record).

    Constructor errors are for *structurally malformed* records
    (harness misuse — loud, like the skeptic lane's specs). Attestation
    VIOLATIONS (e.g. ``saw_other_channel=True``) are representable on
    purpose: they are upstream facts the gate must record and then
    fail on, not values to silently reject at parse time.
    """

    channel: str
    statement_lean: str
    producer: str
    session_id: str
    imports: tuple[str, ...] = ()
    context_sha256: str | None = None
    saw_original_statement: bool = True
    saw_other_channel: bool = False

    def __post_init__(self) -> None:
        if self.channel not in CHANNELS:
            raise ValueError(
                f"FormalizationRecord.channel must be one of {CHANNELS}; got {self.channel!r}"
            )
        _require_nonempty(self.statement_lean, "statement_lean", "FormalizationRecord")
        _require_nonempty(self.producer, "producer", "FormalizationRecord")
        _require_nonempty(self.session_id, "session_id", "FormalizationRecord")
        object.__setattr__(self, "imports", tuple(self.imports))

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "statement_lean": self.statement_lean,
            "imports": list(self.imports),
            "producer": self.producer,
            "session_id": self.session_id,
            "context_sha256": self.context_sha256,
            "saw_original_statement": self.saw_original_statement,
            "saw_other_channel": self.saw_other_channel,
        }


@dataclass(frozen=True)
class BackTranslationRecord:
    """A blind Lean→English rendering (translator must not have seen
    the original claim)."""

    statement_en: str
    translator: str
    session_id: str
    source_channel: str
    rendered_statement_lean: str
    translator_saw_original: bool = False

    def __post_init__(self) -> None:
        if self.source_channel not in CHANNELS:
            raise ValueError(
                "BackTranslationRecord.source_channel must be one of "
                f"{CHANNELS}; got {self.source_channel!r}"
            )
        _require_nonempty(self.statement_en, "statement_en", "BackTranslationRecord")
        _require_nonempty(self.translator, "translator", "BackTranslationRecord")
        _require_nonempty(self.session_id, "session_id", "BackTranslationRecord")
        _require_nonempty(
            self.rendered_statement_lean, "rendered_statement_lean", "BackTranslationRecord"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "statement_en": self.statement_en,
            "translator": self.translator,
            "session_id": self.session_id,
            "source_channel": self.source_channel,
            "rendered_statement_lean": self.rendered_statement_lean,
            "translator_saw_original": self.translator_saw_original,
        }


@dataclass(frozen=True)
class SkepticDiffRecord:
    """The skeptic's diff of the blind back-translation against the
    original claim (the skeptic HAS seen the original — that is its
    job)."""

    skeptic: str
    verdict: str
    saw_original: bool = True
    discrepancies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_nonempty(self.skeptic, "skeptic", "SkepticDiffRecord")
        if self.verdict not in DIFF_VERDICTS:
            raise ValueError(
                f"SkepticDiffRecord.verdict must be one of {DIFF_VERDICTS}; got {self.verdict!r}"
            )
        if self.verdict == "mismatch" and not self.discrepancies:
            raise ValueError(
                "SkepticDiffRecord: a 'mismatch' verdict must list its discrepancies"
            )
        object.__setattr__(self, "discrepancies", tuple(self.discrepancies))

    def to_dict(self) -> dict[str, Any]:
        return {
            "skeptic": self.skeptic,
            "verdict": self.verdict,
            "saw_original": self.saw_original,
            "discrepancies": list(self.discrepancies),
        }


def equivalence_snippet(
    source_prop: str, target_prop: str, *, direction: str, tactic: str = DEFAULT_EQUIV_TACTIC
) -> str:
    """Build one direction's equivalence obligation.

    ``direction`` is ``"fwd"`` (A → B) or ``"bwd"`` (B → A); the props
    are parenthesized verbatim — the D-2 snippet guard (which the
    injected handler runs) rejects ``axiom``/``opaque`` smuggled inside
    either prop before the REPL ever sees it.
    """
    if direction == "fwd":
        name = FWD_NAME
    elif direction == "bwd":
        name = BWD_NAME
    else:
        raise ValueError(f"direction must be 'fwd' or 'bwd'; got {direction!r}")
    return f"theorem {name} : ({source_prop}) → ({target_prop}) := by\n  {tactic}"


# ---------------------------------------------------------------------------
# Pure structural checks (shared by the gate runner and the award rule
# — single source of truth, both operate on plain record dicts)
# ---------------------------------------------------------------------------


def _dual_reasons(dual: Mapping[str, Any] | None) -> list[str]:
    reasons: list[str] = []
    if not isinstance(dual, Mapping):
        return ["no dual-formalization record"]
    records = dual.get("records")
    if not isinstance(records, list) or len(records) != 2:
        return ["dual formalization requires exactly 2 records"]
    a, b = records
    if not (isinstance(a, Mapping) and isinstance(b, Mapping)):
        return ["dual formalization records must be objects"]
    if {a.get("channel"), b.get("channel")} != set(CHANNELS):
        reasons.append("dual channels must be exactly {A, B}")
    for rec in (a, b):
        ch = rec.get("channel")
        if not rec.get("statement_lean"):
            reasons.append(f"channel {ch}: empty statement_lean")
        if not rec.get("producer"):
            reasons.append(f"channel {ch}: no producer recorded")
        if not rec.get("session_id"):
            reasons.append(f"channel {ch}: no session_id recorded")
        if rec.get("saw_original_statement") is not True:
            reasons.append(
                f"channel {ch}: formalizer did not attest to seeing the original statement"
            )
        if rec.get("saw_other_channel") is not False:
            reasons.append(
                f"channel {ch}: independence violated (saw the other channel's output, "
                "or the attestation is missing)"
            )
    if a.get("session_id") and a.get("session_id") == b.get("session_id"):
        reasons.append("independence violated: both passes ran in the same session")
    # A==B trivial-equivalence guard (P0 #3; math-r1 nit 1). Two
    # byte-identical (whitespace-normalized) formalizations make the
    # kernel A⇔B check close instantly on the `exact fun h => h` rung —
    # the dual-formalization defense would contribute NOTHING while
    # reading as "established". Independence must be more than attested
    # (distinct sessions/channels): the two statements must actually
    # differ. Fail closed on identical A/B; over-rejection costs the
    # autoformalizer a genuinely-independent second phrasing, which is
    # the entire point of the dual channel.
    stmt_a = a.get("statement_lean")
    stmt_b = b.get("statement_lean")
    if (
        isinstance(stmt_a, str)
        and isinstance(stmt_b, str)
        and stmt_a
        and stmt_b
        and normalize_lean(stmt_a) == normalize_lean(stmt_b)
    ):
        reasons.append(
            "dual formalization is trivial: channels A and B are "
            "byte-identical (whitespace-normalized) — independence must be "
            "more than attested, and an A⇔B equivalence over identical "
            "statements closes instantly on `exact fun h => h`, providing no "
            "dual-formalization protection (P0 #3; math-r1 nit 1)"
        )
    return reasons


def _back_translation_reasons(
    bt: Mapping[str, Any] | None, dual: Mapping[str, Any] | None
) -> list[str]:
    reasons: list[str] = []
    if not isinstance(bt, Mapping):
        return ["no blind back-translation record"]
    if not bt.get("statement_en"):
        reasons.append("back-translation: empty statement_en")
    if not bt.get("translator"):
        reasons.append("back-translation: no translator recorded")
    if bt.get("translator_saw_original") is not False:
        reasons.append(
            "back-translation is not blind (translator saw the original claim, "
            "or the attestation is missing)"
        )
    session = bt.get("session_id")
    if not session:
        reasons.append("back-translation: no session_id recorded")
    records = (dual or {}).get("records") if isinstance(dual, Mapping) else None
    by_channel: dict[Any, Mapping[str, Any]] = {
        r.get("channel"): r for r in (records or []) if isinstance(r, Mapping)
    }
    if session and any(session == r.get("session_id") for r in by_channel.values()):
        reasons.append(
            "back-translation is not blind (translator session is a formalizer session)"
        )
    src = bt.get("source_channel")
    src_record = by_channel.get(src)
    if src_record is None:
        reasons.append(f"back-translation: source_channel {src!r} has no formalization record")
    elif normalize_lean(str(bt.get("rendered_statement_lean") or "")) != normalize_lean(
        str(src_record.get("statement_lean") or "")
    ):
        reasons.append(
            f"back-translation rendered a different Lean statement than channel {src} produced"
        )
    return reasons


def _skeptic_diff_reasons(sd: Mapping[str, Any] | None) -> list[str]:
    reasons: list[str] = []
    if not isinstance(sd, Mapping):
        return ["no skeptic diff record"]
    if not sd.get("skeptic"):
        reasons.append("skeptic diff: no skeptic recorded")
    if sd.get("saw_original") is not True:
        reasons.append("skeptic diff: the skeptic must diff against the ORIGINAL claim")
    verdict = sd.get("verdict")
    if verdict == "mismatch":
        discrepancies = [str(d) for d in sd.get("discrepancies") or []]
        listed = "; ".join(discrepancies) or "<none listed>"
        reasons.append(f"skeptic diff verdict is 'mismatch': {listed}")
    elif verdict != "match":
        reasons.append(f"skeptic diff verdict is {verdict!r}, not 'match'")
    return reasons


def _equivalence_reasons(equiv: Mapping[str, Any] | None) -> list[str]:
    """Award-side equivalence checks (fail-closed re-derivation — the
    recorded ``established`` flag alone is never trusted)."""
    if not isinstance(equiv, Mapping):
        return ["no equivalence record"]
    reasons: list[str] = []
    if equiv.get("established") is not True:
        reasons.append("Lean equivalence of the two formalizations was not established")
    if equiv.get("method") != "lean-iff":
        reasons.append(
            f"equivalence method {equiv.get('method')!r} is not award-eligible "
            "(only 'lean-iff' is)"
        )
    for direction in ("forward", "backward"):
        rec = equiv.get(direction)
        if not isinstance(rec, Mapping):
            reasons.append(f"equivalence: no {direction} direction record")
        elif rec.get("award_ok") is not True:
            reasons.append(
                f"equivalence: the {direction} direction did not pass the hardened "
                "formal award predicate"
            )
    return reasons


def _signoff_reasons(signoff: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(signoff, Mapping):
        return ["no human sign-off record"]
    if signoff.get("signed") is not True:
        return ["human sign-off checkbox is not set"]
    reasons: list[str] = []
    if not signoff.get("by"):
        reasons.append("human sign-off carries no signer identity")
    if not signoff.get("at"):
        reasons.append("human sign-off carries no timestamp")
    return reasons


# ---------------------------------------------------------------------------
# The gate runner
# ---------------------------------------------------------------------------


def _direction_record(
    *, snippet: str, imports: list[str], result: Mapping[str, Any] | None
) -> dict[str, Any]:
    if result is None:
        return {
            "award_ok": False,
            "reasons": ["direction not attempted"],
            "lean_status": None,
            "transcript_sha256": None,
            "snippet": snippet,
            "imports": imports,
        }
    ok, reasons = formal_award_ok(dict(result))
    provenance = result.get("provenance") or {}
    return {
        "award_ok": ok,
        "reasons": reasons,
        "lean_status": result.get("status"),
        "transcript_sha256": provenance.get("transcript_sha256"),
        "snippet": snippet,
        "imports": imports,
    }


@dataclass
class FaithfulnessGateResult:
    """The gate's structured outcome; ``to_faithfulness_block()`` is
    the EvidenceBundle ``payload["faithfulness"]`` content."""

    gate_ok: bool
    gate_reasons: list[str]
    block: dict[str, Any]

    def to_faithfulness_block(self) -> dict[str, Any]:
        return dict(self.block)


async def run_faithfulness_gate(
    *,
    statement_latex: str,
    formalization_a: FormalizationRecord,
    formalization_b: FormalizationRecord,
    back_translation: BackTranslationRecord | None,
    skeptic_diff: SkepticDiffRecord | None,
    lean_verify: LeanVerify | None,
    statement_nl: str | None = None,
    equiv_tactic_fwd: str = DEFAULT_EQUIV_TACTIC,
    equiv_tactic_bwd: str = DEFAULT_EQUIV_TACTIC,
) -> FaithfulnessGateResult:
    """Run the L1 gate over the four elements and assemble the
    EvidenceBundle faithfulness block.

    The emitted ``human_signoff`` is ALWAYS ``{"signed": false, ...}``
    — there is deliberately no parameter to pass a signature in.
    Re-running the gate re-opens the checkbox; the operator signs the
    emitted record via :func:`record_human_signoff` after review.

    Fail-fast on broken independence: when the dual-formalization
    attestations do not hold, the Lean equivalence check is NOT run
    (tainted inputs do not deserve REPL budget) and the record says so.
    """
    if not statement_latex or not isinstance(statement_latex, str):
        raise ValueError("statement_latex must be a non-empty string")
    started_at = datetime.now(UTC).isoformat()
    t0 = time.monotonic()
    lean_queries = 0

    dual: dict[str, Any] = {
        "records": [formalization_a.to_dict(), formalization_b.to_dict()],
    }
    dual_reasons = _dual_reasons(dual)
    dual["independent"] = not dual_reasons

    imports = sorted(set(formalization_a.imports) | set(formalization_b.imports))
    equivalence: dict[str, Any] = {
        "established": False,
        "method": "none",
        "tactic_fwd": equiv_tactic_fwd,
        "tactic_bwd": equiv_tactic_bwd,
        "imports": imports,
        "forward": None,
        "backward": None,
    }
    equiv_reasons: list[str] = []
    if dual_reasons:
        equiv_reasons.append(
            "equivalence not attempted: dual-formalization independence does not hold"
        )
    elif lean_verify is None:
        equiv_reasons.append("equivalence not attempted: no Lean verifier wired")
    else:
        prop_a = formalization_a.statement_lean
        prop_b = formalization_b.statement_lean
        fwd_snippet = equivalence_snippet(
            prop_a, prop_b, direction="fwd", tactic=equiv_tactic_fwd
        )
        bwd_snippet = equivalence_snippet(
            prop_b, prop_a, direction="bwd", tactic=equiv_tactic_bwd
        )
        fwd_result = await lean_verify(fwd_snippet, list(imports))
        lean_queries += 1
        equivalence["forward"] = _direction_record(
            snippet=fwd_snippet, imports=list(imports), result=fwd_result
        )
        bwd_result = await lean_verify(bwd_snippet, list(imports))
        lean_queries += 1
        equivalence["backward"] = _direction_record(
            snippet=bwd_snippet, imports=list(imports), result=bwd_result
        )
        fwd_ok = equivalence["forward"]["award_ok"]
        bwd_ok = equivalence["backward"]["award_ok"]
        if fwd_ok and bwd_ok:
            equivalence["established"] = True
            equivalence["method"] = "lean-iff"
        else:
            for direction, ok, rec in (
                ("forward", fwd_ok, equivalence["forward"]),
                ("backward", bwd_ok, equivalence["backward"]),
            ):
                if not ok:
                    detail = "; ".join(rec["reasons"][:3])
                    equiv_reasons.append(
                        f"equivalence {direction} direction not proved ({detail})"
                    )

    bt_dict = back_translation.to_dict() if back_translation else None
    sd_dict = skeptic_diff.to_dict() if skeptic_diff else None
    bt_reasons = _back_translation_reasons(bt_dict, dual)
    sd_reasons = _skeptic_diff_reasons(sd_dict)

    gate_reasons = [*dual_reasons, *equiv_reasons, *bt_reasons, *sd_reasons]
    gate_ok = not gate_reasons and equivalence["established"] is True

    block: dict[str, Any] = {
        "gate_version": GATE_VERSION,
        "gate_ok": gate_ok,
        "gate_reasons": gate_reasons,
        "statement": {"latex": statement_latex, "nl": statement_nl},
        "dual": dual,
        "equivalence": equivalence,
        "back_translation": bt_dict,
        "skeptic_diff": sd_dict,
        # No automation may set this — see record_human_signoff.
        "human_signoff": {"signed": False, "by": None, "at": None, "note": None},
        "budget": {
            "wall_clock_s": time.monotonic() - t0,
            "lean_queries": lean_queries,
        },
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    if not gate_ok:
        logger.info(
            "faithfulness gate: FAILED with %d reason%s: %s",
            len(gate_reasons),
            "" if len(gate_reasons) == 1 else "s",
            "; ".join(gate_reasons[:5]),
        )
    return FaithfulnessGateResult(gate_ok=gate_ok, gate_reasons=gate_reasons, block=block)


# ---------------------------------------------------------------------------
# Human sign-off (operator-only; automation is locked out by contract)
# ---------------------------------------------------------------------------


def record_human_signoff(
    block: Mapping[str, Any],
    *,
    by: str,
    at: str | None = None,
    note: str | None = None,
    i_am_a_human_operator: bool = False,
) -> dict[str, Any]:
    """Return a copy of a faithfulness block with the human sign-off
    checkbox set.

    **Operator-invoked ONLY** (console/CLI path). No pipeline
    component — including the D-6 orchestrator — may call this
    function; the ``i_am_a_human_operator=True`` literal keyword is a
    grep-able tripwire making any automated call visible in review,
    not a proof of humanity (no code can prove that; the audit trail
    is the enforcement).

    Refuses to sign a block whose machine-checkable elements do not
    pass (:func:`faithfulness_award_ok` with the sign-off requirement
    itself excluded): a human signature on a failed gate would launder
    the failure.
    """
    if i_am_a_human_operator is not True:
        raise PermissionError(
            "human sign-off is operator-only: pass i_am_a_human_operator=True "
            "from an operator-invoked surface, never from pipeline automation"
        )
    if not by or not isinstance(by, str):
        raise ValueError("human sign-off requires a non-empty signer identity")
    machine_ok, reasons = faithfulness_award_ok(block, publishable=False)
    if not machine_ok:
        raise ValueError(
            "refusing to sign a faithfulness record whose machine-checkable "
            f"elements do not pass: {'; '.join(reasons[:5])}"
        )
    signed = dict(block)
    signed["human_signoff"] = {
        "signed": True,
        "by": by,
        "at": at or datetime.now(UTC).isoformat(),
        "note": note,
    }
    return signed


# ---------------------------------------------------------------------------
# Award rules (pure functions over the block — AC-D.5, AC-D.13 grain)
# ---------------------------------------------------------------------------


def faithfulness_award_ok(
    block: Mapping[str, Any] | None, *, publishable: bool = True
) -> tuple[bool, list[str]]:
    """Decide whether a faithfulness block can support ``proven-formal``.

    Pure function over the recorded block — no LLM, no REPL
    (AC-D.13 discipline). Every element is re-derived from the record;
    the block's own ``gate_ok`` flag is never trusted. Fail-closed:
    a missing block, or any missing element, denies. With
    ``publishable=True`` (the default — publishable is the posture of
    the whole programme) the human sign-off checkbox is required; a
    ``publishable=False`` caller may run internal experiments without
    a signature but the resulting bundle must not be marked
    publishable (the bundle schema enforces the checkbox on
    ``publishable: true`` bundles independently).
    """
    if not isinstance(block, Mapping):
        return False, ["no faithfulness record (the L1 gate did not run)"]
    reasons = [
        *_dual_reasons(block.get("dual")),
        *_equivalence_reasons(block.get("equivalence")),
        *_back_translation_reasons(block.get("back_translation"), block.get("dual")),
        *_skeptic_diff_reasons(block.get("skeptic_diff")),
    ]
    if publishable:
        reasons.extend(_signoff_reasons(block.get("human_signoff")))
    return (not reasons, reasons)


def _has_dual_records(block: Mapping[str, Any] | None) -> bool:
    """True iff the faithfulness block carries at least one non-empty
    ``dual.records[*].statement_lean`` — the gate-checked formalizations
    the proof must be linked to. A structural sanity guard: a recorded
    ``proves_formalization`` boolean with NO formalizations on record is
    not trustworthy (nothing was there to prove), so linkage fails
    closed."""
    if not isinstance(block, Mapping):
        return False
    dual = block.get("dual")
    records = dual.get("records") if isinstance(dual, Mapping) else None
    for rec in records or []:
        if isinstance(rec, Mapping):
            stmt = rec.get("statement_lean")
            if isinstance(stmt, str) and stmt.strip():
                return True
    return False


def proof_statement_linked(
    proves_formalization: bool | None,
    faithfulness_block: Mapping[str, Any] | None,
) -> tuple[bool, list[str]]:
    """Machine-check the SECOND link of the proof chain: the winning
    proof's declaration proves one of the two gate-checked
    formalizations (findings #1/#2 — the ``formalization ⇔ proof`` link
    that neither :func:`formal_award_ok` nor :func:`faithfulness_award_ok`
    establishes).

    ``formal_award_ok`` proves *some* statement is kernel-clean;
    ``faithfulness_award_ok`` proves ``claim ⇔ formalization_A ⇔
    formalization_B``. Without this predicate a kernel-clean proof of an
    UNRELATED statement (e.g. ``1 + 1 = 2``) rides the faithful A/B pair
    to a ``proven-formal`` award — a proof of the wrong statement, which
    AC-D.5 calls worse than no proof.

    **KERNEL DECIDES (durable P1 soundness fix).** ``proves_formalization``
    is the BOOLEAN the orchestrator's award path recorded after asking THE
    KERNEL — ``example : <formalization_a/b.statement_lean> := @<decl>``,
    linked iff the kernel accepts it for at least one channel (see
    :func:`server.lean_soundness.kernel_check_snippet` /
    :func:`server.lean_soundness.kernel_decides_linked`). This replaces the
    pretty-print string equality that let ``∃ x : ℝ, x*x=2`` (proved,
    TRUE) match a gate-checked ``∃ x : ℚ, x*x=2`` (FALSE) because Lean's
    delaborator elides the ∃-binder type — a live CRITICAL false-accept.
    The kernel decides definitional equality, so the collision is denied
    AND a defeq-but-differently-phrased formalization (``Nat`` vs ``ℕ``)
    still links.

    Pure, LLM-free, REPL-free (AC-D.13 grain — the REPL round-trip
    happened in the orchestrator's verifier layer; this function only
    reads the recorded boolean), and fail-closed: ``proves_formalization``
    anything other than ``True`` (``None``/missing — the kernel check
    never ran or errored, or a prior-result award with no snippet in
    hand), OR a block with no dual records, DENIES. Over-rejection only
    costs a snippet rewrite; accepting an unlinked proof is the exact
    soundness hole D-6 exists to remove.
    """
    if proves_formalization is not True:
        return False, [
            "statement linkage: the kernel did not confirm the proof proves "
            "a gate-checked formalization (proves_formalization is not True — "
            "the per-award `example : <formalization> := @<decl>` kernel "
            "check did not accept, was not run, or errored). Fail-closed — a "
            "kernel-clean proof not kernel-linked to a gate-checked "
            "formalization must never earn proven-formal (AC-D.5, findings "
            "#1/#2; durable P1 kernel-decides fix)."
        ]
    if not _has_dual_records(faithfulness_block):
        return False, [
            "statement linkage: the faithfulness block carries no "
            "formalization statements to link the proof to (fail-closed)"
        ]
    return True, []


def award_statement_verdict(
    formal_result: Mapping[str, Any] | None,
    faithfulness_block: Mapping[str, Any] | None,
    *,
    publishable: bool = True,
    proves_formalization: bool | None = None,
) -> tuple[str, list[str]]:
    """The L1-gated verdict award for a formally-proved claim.

    ``proven-formal`` requires ALL THREE links of the proof chain:

    1. the D-2 hardened formal award
       (:func:`server.lean_soundness.formal_award_ok` on the claim's own
       verification result) — *some* statement is kernel-clean;
    2. the complete faithfulness record
       (:func:`faithfulness_award_ok`) — ``claim ⇔ formalization_A ⇔
       formalization_B``;
    3. **statement linkage** (:func:`proof_statement_linked`) — the
       kernel confirmed the proof proves one of those two formalizations
       (findings #1/#2: the ``formalization ⇔ proof`` link).

    A kernel-accepted proof whose faithfulness record is missing any
    element, OR whose declaration is not kernel-linked to a gate-checked
    formalization, caps at ``plausible-unverified`` (AC-D.5 — the proof
    may well be real, but nobody has established it proves the CLAIMED
    statement). No formal award at all → ``abstained``.

    ``proves_formalization`` is the BOOLEAN the orchestrator recorded from
    the per-award kernel check ``example : <formalization> := @<decl>``
    (durable P1 kernel-decides fix — the pipeline computes it in its
    verifier layer and records it; the publishable path re-derives it from
    the bundle). It is fail-closed **required** ``True`` for a
    ``proven-formal`` award: anything else (``None``/missing — check not
    run, errored, or a prior-result award with no snippet) leaves the link
    unestablished and the verdict caps.
    """
    formal_ok, formal_reasons = formal_award_ok(dict(formal_result or {}))
    if not formal_ok:
        return "abstained", [f"formal lane: {r}" for r in formal_reasons]
    faith_ok, faith_reasons = faithfulness_award_ok(faithfulness_block, publishable=publishable)
    link_ok, link_reasons = proof_statement_linked(
        proves_formalization, faithfulness_block
    )
    if not faith_ok or not link_ok:
        return (
            "plausible-unverified",
            [
                "kernel-accepted proof, but the statement-faithfulness gate (L1) "
                "is not satisfied — capped per AC-D.5",
                *[f"faithfulness: {r}" for r in faith_reasons],
                *link_reasons,
            ],
        )
    return "proven-formal", []


__all__ = [
    "BWD_NAME",
    "CHANNELS",
    "DEFAULT_EQUIV_TACTIC",
    "DIFF_VERDICTS",
    "EQUIV_METHODS",
    "FWD_NAME",
    "GATE_VERSION",
    "BackTranslationRecord",
    "FaithfulnessGateResult",
    "FormalizationRecord",
    "LeanVerify",
    "SkepticDiffRecord",
    "award_statement_verdict",
    "equivalence_snippet",
    "faithfulness_award_ok",
    "normalize_lean",
    "proof_statement_linked",
    "record_human_signoff",
    "run_faithfulness_gate",
]
