"""Known-Answer Test (KAT) suite harness for the proving lane
(stage2/arx-d2 — WS-D D-4; finding 05 §2.D2, §3-R4; AC-D.7..AC-D.9).

The KAT suite is the proving pipeline's calibration instrument: a
versioned fixture of statements with *established* truth values —
including FALSE statements the pipeline must refuse to "prove" — plus
the pure evaluation rules that score a run against it. The fixture
lives at ``tests/eval/fixtures/kat/kat_v1.json`` (versioned like the
retrieval eval fixtures); this module is the loader, sampler, and
scorer. LLM-free and REPL-free by design (the formal-lane bridge
helpers only *consume* ``lean_verify`` result envelopes).

Four statement classes (finding 05 §2.D2):

- ``TRUE-known-formal`` — mathlib/ProofNet-provable seeds. Expected
  ``proven-formal``. A miss here is a *capability* gap, never a
  soundness alarm.
- ``TRUE-known-informal`` — textbook/graduate statements beyond
  today's mathlib ceiling (Hartshorne-level AG, Huybrechts Bridgeland
  material). Expected ``proven-informal-checked`` or honest
  ``abstained`` — never ``proven-formal``.
- ``FALSE-must-reject`` — the critical class: mutations, historically
  false conjectures, small- and large-counterexample cases. Expected
  ``refuted`` (with a counterexample artifact) or ``abstained`` for
  the humility cases. **Any proven-* verdict here is a red alarm.**
- ``OPEN-must-abstain`` — genuinely open problems (Formal-Conjectures
  class seeds). Expected ``abstained`` / ``plausible-unverified``.
  Any proven-* triggers the Tao-grade skepticism protocol.

Escalation semantics (AC-D.9; RISKS.md cross-cutting rule 1): any
*soundness-failing* verdict on a control sets the run to
``escalated`` — a proven-* verdict on a FALSE-must-reject or
OPEN-must-abstain entry (a false *acceptance*), OR a ``refuted``
verdict on a TRUE-known-formal/TRUE-known-informal entry (a false
*refutation*: the mirror image — a counterexample witness sound in
isolation but not established relevant to a known-true claim).
:func:`evaluate_run` writes a loud JSON artifact and logs CRITICAL;
:func:`raise_if_escalated` converts the report into a hard halt for
pipeline callers. There is no auto-resume: a human clears the
artifact. (A mere ``abstained`` on a TRUE-known entry is a capability
gap, not an alarm — only asserting a *falsehood* about it is.)

Per-run controls (AC-D.8): :func:`sample_controls` deterministically
samples a control subset (≥ 1 FALSE, ≥ 1 OPEN, ≥ 1 TRUE-formal
positive control) for embedding in every production proving run; a
run whose controls fail is non-reportable.
"""

from __future__ import annotations

import json
import logging
import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from server.lean_soundness import formal_award_ok

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------

TRUE_KNOWN_FORMAL = "TRUE-known-formal"
TRUE_KNOWN_INFORMAL = "TRUE-known-informal"
FALSE_MUST_REJECT = "FALSE-must-reject"
OPEN_MUST_ABSTAIN = "OPEN-must-abstain"

KAT_CLASSES: tuple[str, ...] = (
    TRUE_KNOWN_FORMAL,
    TRUE_KNOWN_INFORMAL,
    FALSE_MUST_REJECT,
    OPEN_MUST_ABSTAIN,
)

#: The five-verdict output taxonomy (finding 05 §4.3, R1).
VERDICTS: frozenset[str] = frozenset(
    {
        "proven-formal",
        "proven-informal-checked",
        "plausible-unverified",
        "refuted",
        "abstained",
    }
)

#: Verdicts that claim the statement is *established true*. On a FALSE
#: or OPEN entry these are the red-alarm set.
PROVEN_VERDICTS: frozenset[str] = frozenset(
    {"proven-formal", "proven-informal-checked"}
)

#: Verdicts that claim the statement is *established false*. On a
#: TRUE-known entry these are the red-alarm set — the mirror image of
#: PROVEN_VERDICTS on a FALSE/OPEN entry. A `refuted` on a known-TRUE
#: control is a false refutation: a soundness failure, categorically
#: unlike an `abstained` on the same control (a completeness/capability
#: gap that AC-D.7 explicitly does NOT alarm on).
REFUTING_VERDICTS: frozenset[str] = frozenset({"refuted"})

#: Per-class acceptable-verdict envelope (the fixture pins each entry's
#: ``expected_verdicts`` to a subset of these).
ACCEPTABLE_VERDICTS: dict[str, frozenset[str]] = {
    TRUE_KNOWN_FORMAL: frozenset({"proven-formal"}),
    TRUE_KNOWN_INFORMAL: frozenset({"proven-informal-checked", "abstained"}),
    FALSE_MUST_REJECT: frozenset({"refuted", "abstained"}),
    OPEN_MUST_ABSTAIN: frozenset({"abstained", "plausible-unverified"}),
}

#: known_truth value each class must carry (None = open).
_CLASS_TRUTH: dict[str, bool | None] = {
    TRUE_KNOWN_FORMAL: True,
    TRUE_KNOWN_INFORMAL: True,
    FALSE_MUST_REJECT: False,
    OPEN_MUST_ABSTAIN: None,
}

#: FALSE-must-reject subclass tags (finding 05 §2.D2 item 3). v1 must
#: cover at least the four concrete kinds; the humility kinds map to
#: large / no-explicit counterexamples.
FALSE_KINDS: frozenset[str] = frozenset(
    {
        "mutation",
        "historical",
        "small-counterexample",
        "large-counterexample",
        "no-explicit-counterexample",
    }
)
_REQUIRED_FALSE_KINDS: frozenset[str] = frozenset(
    {"mutation", "historical", "small-counterexample", "large-counterexample"}
)

#: AC-D.7: every class carries at least this many entries at v1.
MIN_ENTRIES_PER_CLASS = 10

#: Default fixture location (versioned eval fixture, house discipline).
DEFAULT_KAT_FIXTURE_PATH: Path = (
    Path(__file__).resolve().parent.parent
    / "tests"
    / "eval"
    / "fixtures"
    / "kat"
    / "kat_v1.json"
)

#: Default loud-artifact directory for escalations (gitignored data
#: tree; mirrors the ops-report layout). Overridable per call — tests
#: pass ``tmp_path``.
DEFAULT_ESCALATION_DIR: Path = (
    Path(__file__).resolve().parent.parent / "var" / "arxmcp" / "ops" / "kat"
)


class KatFixtureError(ValueError):
    """The KAT fixture is structurally invalid — refuse to run."""


class KatEscalation(RuntimeError):
    """Raised by :func:`raise_if_escalated` on a red-alarm run. The
    pipeline MUST halt: no retry, no auto-resume, human review only."""

    def __init__(self, report: KatRunReport) -> None:
        alarms = ", ".join(
            f"{o.entry_id}={o.verdict}" for o in report.red_alarms
        )
        super().__init__(
            f"KAT ESCALATION — soundness-failing verdict on "
            f"{len(report.red_alarms)} control(s) (proven-* on a FALSE/OPEN "
            f"control, or refuted on a TRUE-known control): "
            f"[{alarms}]. Pipeline trust is revoked "
            f"until a human reviews the artifact"
            + (f" at {report.artifact_path}" if report.artifact_path else "")
            + "."
        )
        self.report = report


# ---------------------------------------------------------------------------
# Fixture loading + validation
# ---------------------------------------------------------------------------


def load_kat_fixture(path: Path | str | None = None) -> dict[str, Any]:
    """Load and structurally validate the versioned KAT fixture.

    Raises :class:`KatFixtureError` on any structural violation — a
    malformed calibration instrument must never silently score a run.
    """
    fixture_path = Path(path) if path is not None else DEFAULT_KAT_FIXTURE_PATH
    try:
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise KatFixtureError(f"cannot read KAT fixture: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise KatFixtureError(f"KAT fixture is not valid JSON: {exc}") from exc

    version = fixture.get("kat_version")
    if not isinstance(version, int) or version < 1:
        raise KatFixtureError(f"kat_version must be an int >= 1; got {version!r}")
    entries = fixture.get("entries")
    if not isinstance(entries, list) or not entries:
        raise KatFixtureError("fixture has no entries list")

    seen_ids: set[str] = set()
    counts: dict[str, int] = dict.fromkeys(KAT_CLASSES, 0)
    false_kinds_seen: set[str] = set()
    for i, entry in enumerate(entries):
        ctx = f"entry #{i}"
        if not isinstance(entry, dict):
            raise KatFixtureError(f"{ctx} is not an object")
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            raise KatFixtureError(f"{ctx} has no id")
        ctx = f"entry {entry_id!r}"
        if entry_id in seen_ids:
            raise KatFixtureError(f"{ctx}: duplicate id")
        seen_ids.add(entry_id)
        cls = entry.get("class")
        if cls not in KAT_CLASSES:
            raise KatFixtureError(f"{ctx}: unknown class {cls!r}")
        counts[cls] += 1
        if not isinstance(entry.get("statement_nl"), str) or not entry["statement_nl"]:
            raise KatFixtureError(f"{ctx}: statement_nl missing/empty")
        if entry.get("known_truth") != _CLASS_TRUTH[cls]:
            raise KatFixtureError(
                f"{ctx}: known_truth {entry.get('known_truth')!r} "
                f"inconsistent with class {cls} "
                f"(expected {_CLASS_TRUTH[cls]!r})"
            )
        expected = entry.get("expected_verdicts")
        if (
            not isinstance(expected, list)
            or not expected
            or not set(expected) <= ACCEPTABLE_VERDICTS[cls]
        ):
            raise KatFixtureError(
                f"{ctx}: expected_verdicts {expected!r} must be a non-empty "
                f"subset of {sorted(ACCEPTABLE_VERDICTS[cls])}"
            )
        if cls == FALSE_MUST_REJECT:
            kind = entry.get("false_kind")
            if kind not in FALSE_KINDS:
                raise KatFixtureError(
                    f"{ctx}: false_kind {kind!r} not in {sorted(FALSE_KINDS)}"
                )
            false_kinds_seen.add(kind)
            cx = entry.get("counterexample")
            if not isinstance(cx, dict) or not cx.get("description"):
                raise KatFixtureError(
                    f"{ctx}: FALSE entries require a counterexample "
                    "object with a description"
                )
        formal = entry.get("formal")
        if formal is not None and (
            not isinstance(formal, dict) or not formal.get("statement_lean")
        ):
            raise KatFixtureError(f"{ctx}: formal block requires statement_lean")

    for cls, n in counts.items():
        if n < MIN_ENTRIES_PER_CLASS:
            raise KatFixtureError(
                f"class {cls} has {n} entries; v1 floor is "
                f"{MIN_ENTRIES_PER_CLASS} (AC-D.7)"
            )
    missing_kinds = _REQUIRED_FALSE_KINDS - false_kinds_seen
    if missing_kinds:
        raise KatFixtureError(
            f"FALSE-must-reject must cover kinds {sorted(_REQUIRED_FALSE_KINDS)}; "
            f"missing {sorted(missing_kinds)}"
        )
    return fixture


def entries_by_class(fixture: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {cls: [] for cls in KAT_CLASSES}
    for entry in fixture["entries"]:
        out[entry["class"]].append(entry)
    return out


def entry_index(fixture: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {e["id"]: e for e in fixture["entries"]}


# ---------------------------------------------------------------------------
# Per-run control sampling (AC-D.8)
# ---------------------------------------------------------------------------


def sample_controls(
    fixture: Mapping[str, Any],
    *,
    seed: int,
    n_false: int = 1,
    n_open: int = 1,
    n_true_formal: int = 1,
) -> list[dict[str, Any]]:
    """Deterministically sample the per-run control subset.

    ``n_false >= 1`` and ``n_open >= 1`` are hard floors (AC-D.8);
    ``n_true_formal >= 1`` gives the positive control. Sampling is
    restricted to ``control_eligible`` entries (cheap enough to embed
    in every production run) and is reproducible from ``seed`` — the
    run report records the seed, so control selection replays.
    """
    if n_false < 1 or n_open < 1 or n_true_formal < 1:
        raise ValueError(
            "per-run controls require n_false >= 1, n_open >= 1, "
            "n_true_formal >= 1 (AC-D.8)"
        )
    rng = random.Random(seed)
    by_class = entries_by_class(fixture)
    picked: list[dict[str, Any]] = []
    for cls, n in (
        (TRUE_KNOWN_FORMAL, n_true_formal),
        (FALSE_MUST_REJECT, n_false),
        (OPEN_MUST_ABSTAIN, n_open),
    ):
        eligible = [e for e in by_class[cls] if e.get("control_eligible")]
        if len(eligible) < n:
            raise KatFixtureError(
                f"class {cls} has only {len(eligible)} control-eligible "
                f"entries; {n} requested"
            )
        picked.extend(rng.sample(eligible, n))
    return picked


# ---------------------------------------------------------------------------
# Run evaluation + escalation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KatOutcome:
    entry_id: str
    kat_class: str
    verdict: str | None
    ok: bool
    red_alarm: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "kat_class": self.kat_class,
            "verdict": self.verdict,
            "ok": self.ok,
            "red_alarm": self.red_alarm,
        }


@dataclass
class KatRunReport:
    fixture_version: int
    run_id: str
    outcomes: list[KatOutcome]
    per_class: dict[str, dict[str, int]]
    abstention_rate: float
    red_alarms: list[KatOutcome] = field(default_factory=list)
    escalated: bool = False
    reportable: bool = True
    artifact_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_version": self.fixture_version,
            "run_id": self.run_id,
            "outcomes": [o.to_dict() for o in self.outcomes],
            "per_class": self.per_class,
            "abstention_rate": self.abstention_rate,
            "red_alarms": [o.to_dict() for o in self.red_alarms],
            "escalated": self.escalated,
            "reportable": self.reportable,
            "artifact_path": self.artifact_path,
        }


def evaluate_run(
    fixture: Mapping[str, Any],
    verdicts: Mapping[str, str | None],
    *,
    run_id: str | None = None,
    artifact_dir: Path | str | None = None,
) -> KatRunReport:
    """Score a set of ``{kat entry id: verdict}`` results.

    - A verdict outside the entry's ``expected_verdicts`` fails that
      entry. ``None`` (no verdict produced) always fails.
    - **Red alarm (soundness failures, both directions):** any proven-*
      verdict on a FALSE-must-reject or OPEN-must-abstain entry (a false
      *acceptance*), OR any ``refuted`` verdict on a TRUE-known-formal or
      TRUE-known-informal entry (a false *refutation*) ⇒
      ``escalated=True``, a loud JSON artifact is written to
      ``artifact_dir`` (default ``var/arxmcp/ops/kat/``), and CRITICAL is
      logged. Callers wrap the report in :func:`raise_if_escalated` to
      halt. (An ``abstained`` on a TRUE-known entry is NOT an alarm — it
      is a capability gap per AC-D.7; only asserting a *falsehood* is.)
    - ``reportable`` is False when the run escalated OR any control
      entry failed (AC-D.8: a run whose controls fail is
      non-reportable).
    - ``abstention_rate`` is always computed — a pipeline that never
      abstains is miscalibrated by construction (finding 05 §2.D4).

    Unknown entry ids raise :class:`KatFixtureError` (harness misuse
    must be loud, not silently scored).
    """
    index = entry_index(fixture)
    unknown = sorted(set(verdicts) - set(index))
    if unknown:
        raise KatFixtureError(f"verdicts reference unknown KAT ids: {unknown}")
    if not verdicts:
        raise KatFixtureError("no verdicts supplied to evaluate_run")

    if run_id is None:
        run_id = datetime.now(UTC).strftime("kat-%Y%m%dT%H%M%S%fZ")

    outcomes: list[KatOutcome] = []
    per_class: dict[str, dict[str, int]] = {
        cls: {"evaluated": 0, "passed": 0, "failed": 0} for cls in KAT_CLASSES
    }
    abstained = 0
    for entry_id in sorted(verdicts):
        entry = index[entry_id]
        cls = entry["class"]
        verdict = verdicts[entry_id]
        if verdict is not None and verdict not in VERDICTS:
            raise KatFixtureError(
                f"entry {entry_id!r}: verdict {verdict!r} is not in the "
                f"five-verdict taxonomy {sorted(VERDICTS)}"
            )
        ok = verdict in entry["expected_verdicts"]
        red = (
            cls in (FALSE_MUST_REJECT, OPEN_MUST_ABSTAIN)
            and verdict in PROVEN_VERDICTS
        ) or (
            # Symmetric alarm (findings: refuted-verdict-skips-statement-
            # linkage): a `refuted` on a known-TRUE control is a false
            # refutation of a true theorem. A skeptic-lane witness is
            # accepted for its own soundness but never checked for
            # relevance to the claim, so an unrelated-but-sound witness
            # can refute a true statement. This is a soundness failure —
            # unlike an `abstained` here (a capability gap AC-D.7 does
            # not alarm on) — so it halts the run like the FALSE-accept.
            cls in (TRUE_KNOWN_FORMAL, TRUE_KNOWN_INFORMAL)
            and verdict in REFUTING_VERDICTS
        )
        outcomes.append(
            KatOutcome(
                entry_id=entry_id,
                kat_class=cls,
                verdict=verdict,
                ok=ok,
                red_alarm=red,
            )
        )
        per_class[cls]["evaluated"] += 1
        per_class[cls]["passed" if ok else "failed"] += 1
        if verdict == "abstained":
            abstained += 1

    red_alarms = [o for o in outcomes if o.red_alarm]
    escalated = bool(red_alarms)
    report = KatRunReport(
        fixture_version=fixture["kat_version"],
        run_id=run_id,
        outcomes=outcomes,
        per_class=per_class,
        abstention_rate=abstained / len(outcomes),
        red_alarms=red_alarms,
        escalated=escalated,
        reportable=not escalated and all(o.ok for o in outcomes),
    )

    if escalated:
        report.artifact_path = str(
            _write_escalation_artifact(report, artifact_dir)
        )
        logger.critical(
            "KAT ESCALATION: soundness-failing verdict on %d control entr%s "
            "(proven-* on FALSE/OPEN, or refuted on TRUE-known) (%s). "
            "Pipeline trust revoked — halt for human review. Artifact: %s",
            len(red_alarms),
            "y" if len(red_alarms) == 1 else "ies",
            ", ".join(f"{o.entry_id}={o.verdict}" for o in red_alarms),
            report.artifact_path,
        )
    return report


def _write_escalation_artifact(
    report: KatRunReport, artifact_dir: Path | str | None
) -> Path:
    out_dir = (
        Path(artifact_dir) if artifact_dir is not None else DEFAULT_ESCALATION_DIR
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"KAT-ESCALATION-{report.run_id}.json"
    artifact = {
        "!!": (
            "RED ALARM — a soundness-failing verdict was scored on a "
            "control: either a proven-* verdict on a statement with "
            "established FALSE truth value or OPEN status (a false "
            "acceptance), or a `refuted` verdict on a statement with "
            "established TRUE truth value (a false refutation — a "
            "counterexample witness sound in isolation but not relevant to "
            "the claim). The proving pipeline is NOT trustworthy in this "
            "configuration. Do not resume runs; audit the verdicts below "
            "(assume misformalization or literature leakage until shown "
            "otherwise). Delete this file only after human review."
        ),
        "created_at": datetime.now(UTC).isoformat(),
        "report": report.to_dict(),
    }
    path.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def raise_if_escalated(report: KatRunReport) -> KatRunReport:
    """Convert an escalated report into a hard halt (AC-D.9)."""
    if report.escalated:
        raise KatEscalation(report)
    return report


# ---------------------------------------------------------------------------
# Formal-lane bridge (consumes hardened lean_verify envelopes)
# ---------------------------------------------------------------------------


def formal_verdict(lean_result: Mapping[str, Any]) -> str:
    """Map a hardened ``lean_verify`` result to a formal-lane verdict.

    ``proven-formal`` iff the full award predicate passes
    (:func:`server.lean_soundness.formal_award_ok` — kernel ok AND
    axiom closure within the trust base AND no forbidden flags AND
    audited declarations exist); otherwise ``abstained``. The formal
    lane never emits ``refuted`` from a *positive* verification — a
    refutation comes from a witness (below).
    """
    ok, _reasons = formal_award_ok(dict(lean_result))
    return "proven-formal" if ok else "abstained"


def witness_sorry_tainted(lean_result: Mapping[str, Any]) -> bool:
    """True when a result carries any sorry evidence — explicit
    ``sorry_goals``, the ``sorry`` status, or a ``declaration uses
    `sorry``` message.

    This is the ``plausible``-admission path (probed live, load-bearing):
    when ``plausible`` finds no counterexample it admits the goal via
    ``sorry`` and the REPL reports no error and no ``sorries`` row — only
    a ``declaration uses `sorry``` warning — so the normalized envelope
    is ``status: "ok"`` / ``compilation_success: true`` and, for an
    anonymous ``example`` (which the axiom audit cannot name-extract),
    the kernel/audit checks alone would accept it as a valid witness.
    :func:`witness_ok` therefore folds this scan in (single source of
    truth for witness SOUNDNESS — the skeptic lane delegates here rather
    than re-implementing it, so ``kat.witness_ok`` and
    ``skeptic._witness_sound`` cannot drift; pinned by an equivalence
    vector table in ``tests/test_proving_skeptic.py``)."""
    if lean_result.get("status") == "sorry" or lean_result.get("sorry_goals"):
        return True
    messages = lean_result.get("messages") or []
    return any(
        isinstance(m, Mapping) and "sorry" in str(m.get("text", ""))
        for m in messages
    )


def witness_ok(lean_result: Mapping[str, Any]) -> bool:
    """Whether a counterexample-witness snippet is kernel-accepted and
    soundness-clean — the SINGLE witness-soundness predicate.

    A witness (e.g. ``¬ Nat.Prime (40 ^ 2 + 40 + 41)``) supports a
    ``refuted`` verdict when the kernel accepted it in full mode with
    the snippet guard passed, no forbidden flags, an axiom audit that
    did not fail (anonymous ``example`` witnesses legitimately skip the
    per-declaration audit; a *failed* audit still denies), AND no
    sorry-taint (:func:`witness_sorry_tainted` — folded in at round 3 so
    the sorry-admission hole is closed in ONE place rather than being
    patched only in the skeptic lane; the skeptic lane's
    ``_witness_sound`` now delegates here, ending the P0 drift risk
    between the two witness-acceptance predicates).

    NOTE this predicate is about witness SOUNDNESS (kernel-clean +
    sorry-free), orthogonal to witness RELEVANCE (does it discharge a
    claim-linked proposition), which the verdict-linkage choke-point
    (:mod:`server.proving.verdict_linkage`) enforces separately.
    """
    soundness = lean_result.get("soundness") or {}
    return (
        lean_result.get("status") == "ok"
        and lean_result.get("mode") == "full"
        and lean_result.get("compilation_success") is True
        and soundness.get("guard") == "passed"
        and not (set(soundness.get("flags") or ()) & {"native_decide", "unsafe"})
        and soundness.get("axiom_closure_ok") is not False
        and not witness_sorry_tainted(lean_result)
    )


__all__ = [
    "ACCEPTABLE_VERDICTS",
    "DEFAULT_ESCALATION_DIR",
    "DEFAULT_KAT_FIXTURE_PATH",
    "FALSE_KINDS",
    "FALSE_MUST_REJECT",
    "KAT_CLASSES",
    "KatEscalation",
    "KatFixtureError",
    "KatOutcome",
    "KatRunReport",
    "MIN_ENTRIES_PER_CLASS",
    "OPEN_MUST_ABSTAIN",
    "PROVEN_VERDICTS",
    "REFUTING_VERDICTS",
    "TRUE_KNOWN_FORMAL",
    "TRUE_KNOWN_INFORMAL",
    "VERDICTS",
    "entries_by_class",
    "entry_index",
    "evaluate_run",
    "formal_verdict",
    "load_kat_fixture",
    "raise_if_escalated",
    "sample_controls",
    "witness_ok",
    "witness_sorry_tainted",
]
