"""D-6 proving orchestrator v0 (stage2/arx-d3 — WS-D;
AC-D.8/AC-D.12/AC-D.13/AC-D.14/AC-D.15/AC-D.16).

The deterministic, LLM-free engine of the ``.claude/proving/`` pipeline
(the repo's arx-e1 pattern: the *pipeline* — role protocol, command,
prompts — lives under ``.claude/``; the Python that pytest must import
lives in a real package). The LLM roles (sketcher → autoformalizer →
tactician → fixer) run upstream as Claude agents and hand this engine
their **role outputs**; the engine owns everything a language model
must never own: lane sequencing, budget accounting, gate execution,
verdict award, and EvidenceBundle emission.

Contract (AC-D.13): every run consumes exactly one envelope-wrapped
``ProofTask`` and emits exactly one schema-valid ``EvidenceBundle``.
The verdict is **abstained by default** — a verdict must be earned by
evidence the pure award rules accept, never assumed:

- ``refuted``       — the D-5 skeptic lane found a counterexample
  (kernel-confirmed witness, falsification search, or CAS hit).
- ``proven-formal`` — the D-2 hardened formal award
  (``server.lean_soundness.formal_award_ok``) AND the complete D-3
  faithfulness record (``award_statement_verdict``), subject to the
  field lane's verdict ceiling.
- ``proven-informal-checked`` — NOT awardable at v0 (the informal
  panel lane is not automated; the ceiling logic knows this).
- ``plausible-unverified`` — a kernel-accepted proof capped by an
  incomplete faithfulness record (AC-D.5), a ceiling cap, or (in
  CAS-lane plans) a completed no-hit counterexample scan.
- ``abstained``     — everything else, including **budget exhaustion**
  (AC-D.15: exhaustion maps to ``abstained`` with best partial
  evidence attached — never to the highest verdict reached so far).

Hard sequencing contract (AC-D.10): the D-5 skeptic lane runs BEFORE
any prover cycle — enforced structurally (every ``lane_order`` in
``lane_config.json`` must start with ``"skeptic"``; the config loader
refuses otherwise) and evidenced in every bundle's budget accounting.

Field-tiered defaults (AC-D.14) are **configuration, not prose**:
``lane_config.json`` maps each ``field_lane`` to a lane order and a
verdict ceiling (math.NT formal-first; math.AG informal-checked
ceiling; math-ph CAS/numerics-first). The chosen plan is recorded in
every bundle (``provenance.lane_plan`` + ``provenance.lane_trace``) so
lane selection is inspectable per AC-D.14's acceptance test.

Cross-check rule (AC-D.12): conflicting evidence — a formal proof
passing the hardened award while a counterexample stands against the
claim (or vice versa) — is never resolved silently: the verdict is
forced to ``abstained`` and ``escalated: true`` (the seeded-
misformalization case: the formal statement diverges from the NL
claim).

KAT controls (AC-D.8/AC-D.9): production runs embed a sampled control
subset via :func:`run_kat_controls` (≥ 1 TRUE-formal positive control,
≥ 1 FALSE, ≥ 1 OPEN); the scored report rides the bundle's
``controls`` block, a failed control marks the run non-reportable, and
any proven-* on a FALSE/OPEN control raises
:class:`server.kat.KatEscalation` (hard halt) before the bundle is
emitted.

**The human sign-off is out of this module's reach — deliberately.**
The pipeline always emits ``publishable: false`` bundles;
``faithfulness.record_human_signoff`` is never imported here (binding
rule in ``server/proving/README.md``, pinned by a source-scan test).
The operator surface is ``tools/sign_bundle.py``, which signs and then
calls :func:`make_publishable_bundle` to re-derive the publishable
award — the D-3 gate, including the checkbox, stands between any
pipeline output and a publishable ``proven-formal``.

Like the rest of ``server/proving/``, nothing here registers on the
MCP surface (BP1-safe) and nothing talks to an LLM; Lean goes through
the injected async verifier (production: ``tools/prove_task.py`` wires
``server.handlers.lean_verify.handle_lean_verify``; tests inject
fakes).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from server.kat import (
    FALSE_MUST_REJECT,
    OPEN_MUST_ABSTAIN,
    TRUE_KNOWN_FORMAL,
    KatRunReport,
    evaluate_run,
    formal_verdict,
    load_kat_fixture,
    raise_if_escalated,
    sample_controls,
    witness_ok,
)
from server.lean_soundness import (
    extract_decl_names,
    formal_award_ok,
    kernel_check_snippet,
    kernel_decides_linked,
    kernel_statement_for_snippet,
)
from server.proving.contracts import (
    EVIDENCE_BUNDLE_ARTIFACT,
    EVIDENCE_BUNDLE_VERSION,
    load_schema,
    validate_evidence_bundle,
    validate_proof_task,
    wrap_payload,
)
from server.proving.faithfulness import (
    BackTranslationRecord,
    FormalizationRecord,
    LeanVerify,
    SkepticDiffRecord,
    award_statement_verdict,
    run_faithfulness_gate,
)
from server.proving.skeptic import (
    SkepticLaneResult,
    checks_from_proof_task,
    run_skeptic_lane,
)
from server.proving.verdict_linkage import award_linked_verdict

logger = logging.getLogger(__name__)

ORCHESTRATOR_VERSION = "v0"

LANE_CONFIG_PATH: Path = Path(__file__).resolve().parent / "lane_config.json"

#: Executable lane names known to this engine version.
KNOWN_LANES: frozenset[str] = frozenset({"skeptic", "formal", "informal", "cas"})

#: Verdict rank for the ceiling rule. ``refuted`` is deliberately
#: absent — a refutation is orthogonal evidence, never capped.
_VERDICT_RANK: dict[str, int] = {
    "abstained": 0,
    "plausible-unverified": 1,
    "proven-informal-checked": 2,
    "proven-formal": 3,
}

PROVEN_VERDICTS: frozenset[str] = frozenset(
    {"proven-formal", "proven-informal-checked"}
)

#: Verdicts that claim the statement is *established false*. On a task
#: with established-TRUE truth these are the red-alarm set — the mirror
#: image of ``PROVEN_VERDICTS`` on a FALSE task (AC-D.9 symmetry). A
#: confident refutation of a known-true theorem is a soundness failure,
#: not a capability gap: unlike an ``abstained`` on a TRUE control (a
#: completeness miss, per AC-D.7), it asserts a falsehood.
REFUTING_VERDICTS: frozenset[str] = frozenset({"refuted"})

ATTEMPT_ROLES: tuple[str, ...] = ("tactician", "fixer")


class LaneConfigError(ValueError):
    """``lane_config.json`` is structurally invalid — refuse to run
    (a proving run on a malformed lane policy is worse than no run)."""


class BudgetExceeded(RuntimeError):
    """Raised internally when the task budget runs out mid-pipeline;
    the pipeline converts it to the AC-D.15 ``abstained`` exit."""


# ---------------------------------------------------------------------------
# Lane configuration (AC-D.14 — data, not prose)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_lane_config(path: Path | str | None = None) -> dict[str, Any]:
    """Load and structurally validate the field-tier lane config.

    Raises :class:`LaneConfigError` on any violation: unknown lanes, a
    lane order that does not start with ``skeptic`` (AC-D.10 is a hard
    contract, not a per-field choice), a ceiling outside the earnable
    taxonomy, or a field set that drifts from the proof-task schema's
    ``field_lane`` enum (lockstep rule).
    """
    config_path = Path(path) if path is not None else LANE_CONFIG_PATH
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LaneConfigError(f"cannot read lane config: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LaneConfigError(f"lane config is not valid JSON: {exc}") from exc

    version = config.get("config_version")
    if not isinstance(version, int) or version < 1:
        raise LaneConfigError(f"config_version must be an int >= 1; got {version!r}")

    field_lanes = config.get("field_lanes")
    if not isinstance(field_lanes, Mapping) or not field_lanes:
        raise LaneConfigError("lane config has no field_lanes mapping")

    schema_enum = _proof_task_field_lane_enum()
    if set(field_lanes) != schema_enum:
        raise LaneConfigError(
            "field_lanes keys must track the proof-task schema field_lane "
            f"enum in lockstep; config has {sorted(field_lanes)}, schema has "
            f"{sorted(schema_enum)}"
        )

    for name, lane in field_lanes.items():
        ctx = f"field_lanes[{name!r}]"
        if not isinstance(lane, Mapping):
            raise LaneConfigError(f"{ctx} is not an object")
        order = lane.get("lane_order")
        if not isinstance(order, list) or not order:
            raise LaneConfigError(f"{ctx}: lane_order must be a non-empty list")
        unknown = [x for x in order if x not in KNOWN_LANES]
        if unknown:
            raise LaneConfigError(f"{ctx}: unknown lanes {unknown}")
        if len(set(order)) != len(order):
            raise LaneConfigError(f"{ctx}: lane_order has duplicates")
        if order[0] != "skeptic":
            raise LaneConfigError(
                f"{ctx}: lane_order must start with 'skeptic' — the "
                "counterexample-first pass is a hard contract (AC-D.10)"
            )
        ceiling = lane.get("verdict_ceiling")
        if ceiling not in _VERDICT_RANK:
            raise LaneConfigError(
                f"{ctx}: verdict_ceiling {ceiling!r} not in {sorted(_VERDICT_RANK)}"
            )

    budget = config.get("default_budget")
    if not isinstance(budget, Mapping):
        raise LaneConfigError("lane config has no default_budget object")
    for key in ("wall_clock_s", "lean_queries", "cas_runs", "prover_cycles"):
        if not isinstance(budget.get(key), (int, float)) or budget[key] <= 0:
            raise LaneConfigError(f"default_budget.{key} must be a positive number")

    return config


def _proof_task_field_lane_enum() -> set[str]:
    schema = load_schema("urn:arxmcp:bridge:proof-task:v0")
    payload_props = schema["allOf"][1]["properties"]["payload"]["properties"]
    return set(payload_props["field_lane"]["enum"])


def lane_plan_for(
    field_lane: str | None, *, config: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """The lane plan a task's ``field_lane`` selects (``general`` is
    the no-metadata fallback, mirroring the schema)."""
    cfg = config if config is not None else load_lane_config()
    lanes = cfg["field_lanes"]
    name = field_lane if field_lane in lanes else "general"
    plan = lanes[name]
    return {
        "field_lane": name,
        "lane_order": list(plan["lane_order"]),
        "verdict_ceiling": plan["verdict_ceiling"],
        "config_version": cfg["config_version"],
    }


def apply_lane_ceiling(verdict: str, ceiling: str) -> tuple[str, list[str]]:
    """Pure ceiling rule (AC-D.14). ``refuted`` and ``abstained`` pass
    through; a verdict ranking above the ceiling is capped — and when
    the ceiling tier itself requires evidence v0 cannot supply
    (``proven-informal-checked`` needs a panel record), the cap falls
    through to ``plausible-unverified`` rather than fabricating the
    ceiling verdict."""
    if verdict not in _VERDICT_RANK:
        return verdict, []
    if _VERDICT_RANK[verdict] <= _VERDICT_RANK[ceiling]:
        return verdict, []
    reasons = [
        f"field-lane ceiling: {verdict!r} exceeds the lane ceiling {ceiling!r} "
        "(lane_config.json); capped"
    ]
    if ceiling == "proven-informal-checked":
        reasons.append(
            "ceiling tier 'proven-informal-checked' requires informal-panel "
            "evidence the v0 pipeline cannot supply; capped to "
            "'plausible-unverified' instead of fabricating the ceiling verdict"
        )
        return "plausible-unverified", reasons
    return ceiling, reasons


# ---------------------------------------------------------------------------
# Role outputs (what the .claude/ role loop hands the engine)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProofAttempt:
    """One prover-cycle candidate: a full Lean snippet proving the
    claim's formalization. ``tactician`` attempts are the first-pass
    candidates; ``fixer`` attempts are repair iterations on prover
    feedback. The engine runs them in role order and charges one
    prover cycle each."""

    name: str
    snippet: str
    imports: tuple[str, ...] = ()
    role: str = "tactician"
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise ValueError("ProofAttempt.name must be a non-empty string")
        if not self.snippet or not isinstance(self.snippet, str):
            raise ValueError(f"attempt {self.name!r}: snippet must be a non-empty string")
        if self.role not in ATTEMPT_ROLES:
            raise ValueError(
                f"attempt {self.name!r}: role must be one of {ATTEMPT_ROLES}; "
                f"got {self.role!r}"
            )
        object.__setattr__(self, "imports", tuple(self.imports))


@dataclass(frozen=True)
class RoleOutputs:
    """The per-claim products of the sketcher → autoformalizer →
    tactician → fixer role loop. All optional — the engine treats a
    missing element as evidence that cannot be earned (fail-closed),
    never as a reason to crash."""

    sketch: str | None = None
    formalization_a: FormalizationRecord | None = None
    formalization_b: FormalizationRecord | None = None
    back_translation: BackTranslationRecord | None = None
    skeptic_diff: SkepticDiffRecord | None = None
    attempts: tuple[ProofAttempt, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempts", tuple(self.attempts))

    @classmethod
    def from_dict(cls, doc: Mapping[str, Any]) -> RoleOutputs:
        """Parse a role-outputs JSON document (the CLI grain).
        Malformed records raise ``ValueError`` loudly via the record
        constructors — harness misuse must never be silently scored."""
        if not isinstance(doc, Mapping):
            raise ValueError("role outputs must be an object")

        def _form(key: str) -> FormalizationRecord | None:
            rec = doc.get(key)
            if rec is None:
                return None
            return FormalizationRecord(
                channel=rec["channel"],
                statement_lean=rec["statement_lean"],
                producer=rec["producer"],
                session_id=rec["session_id"],
                imports=tuple(rec.get("imports") or ()),
                context_sha256=rec.get("context_sha256"),
                saw_original_statement=rec.get("saw_original_statement", True),
                saw_other_channel=rec.get("saw_other_channel", False),
            )

        bt = doc.get("back_translation")
        sd = doc.get("skeptic_diff")
        return cls(
            sketch=doc.get("sketch"),
            formalization_a=_form("formalization_a"),
            formalization_b=_form("formalization_b"),
            back_translation=(
                BackTranslationRecord(
                    statement_en=bt["statement_en"],
                    translator=bt["translator"],
                    session_id=bt["session_id"],
                    source_channel=bt["source_channel"],
                    rendered_statement_lean=bt["rendered_statement_lean"],
                    translator_saw_original=bt.get("translator_saw_original", False),
                )
                if bt is not None
                else None
            ),
            skeptic_diff=(
                SkepticDiffRecord(
                    skeptic=sd["skeptic"],
                    verdict=sd["verdict"],
                    saw_original=sd.get("saw_original", True),
                    discrepancies=tuple(sd.get("discrepancies") or ()),
                )
                if sd is not None
                else None
            ),
            attempts=tuple(
                ProofAttempt(
                    name=a["name"],
                    snippet=a["snippet"],
                    imports=tuple(a.get("imports") or ()),
                    role=a.get("role", "tactician"),
                    description=a.get("description"),
                )
                for a in doc.get("attempts") or ()
            ),
        )


# ---------------------------------------------------------------------------
# Context packs (the closed v0 shape the proof-task schema leaves open)
# ---------------------------------------------------------------------------

#: The D-6-authored context-pack shape for ``payload.statement_context``
#: (the proof-task schema deliberately leaves the block open at v0 and
#: names this module as the shape author). All keys optional; typed
#: when present.
CONTEXT_PACK_KEYS: frozenset[str] = frozenset(
    {"definitions", "hypotheses", "sources", "retrieval"}
)


def context_pack_violations(context: Mapping[str, Any] | None) -> list[str]:
    """Structural check of a per-claim context pack. Violations are
    recorded in the bundle provenance (loud, auditable) — the engine
    does not consume pack *content* (the LLM roles upstream do), so a
    bad pack degrades provenance rather than crashing the run."""
    if context is None:
        return []
    if not isinstance(context, Mapping):
        return ["statement_context must be an object"]
    violations: list[str] = []
    unknown = sorted(set(context) - CONTEXT_PACK_KEYS)
    if unknown:
        violations.append(f"unknown context-pack keys: {unknown}")
    for key in ("definitions", "sources"):
        items = context.get(key)
        if items is None:
            continue
        if not isinstance(items, list):
            violations.append(f"{key} must be a list")
            continue
        for i, item in enumerate(items):
            if not isinstance(item, Mapping):
                violations.append(f"{key}[{i}] must be an object")
    hypotheses = context.get("hypotheses")
    if hypotheses is not None and (
        not isinstance(hypotheses, list)
        or any(not isinstance(h, str) or not h for h in hypotheses)
    ):
        violations.append("hypotheses must be a list of non-empty strings")
    retrieval = context.get("retrieval")
    if retrieval is not None and not isinstance(retrieval, Mapping):
        violations.append("retrieval must be an object")
    return violations


def context_pack_sha256(context: Mapping[str, Any] | None) -> str | None:
    """Canonical-JSON SHA-256 of the pack — pins what context the
    roles saw into the bundle provenance (replay grain)."""
    if context is None:
        return None
    canonical = json.dumps(
        context, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Budget ledger (AC-D.15)
# ---------------------------------------------------------------------------


@dataclass
class BudgetLedger:
    """Whole-run resource accounting against the task's declared
    ceilings. ``charge_*`` raise :class:`BudgetExceeded` when a charge
    would cross a ceiling; the pipeline converts that to the AC-D.15
    ``abstained``-with-partial-evidence exit."""

    limits: dict[str, float]
    # perf_counter, not monotonic: on Windows this Python's monotonic
    # ticks at ~15.6 ms granularity, which makes small wall-clock
    # budgets unenforceable within a tick (probed live in this slice).
    t0: float = field(default_factory=time.perf_counter)
    lean_queries: int = 0
    cas_runs: int = 0
    prover_cycles: int = 0

    @classmethod
    def from_task(cls, payload: Mapping[str, Any]) -> BudgetLedger:
        defaults = load_lane_config()["default_budget"]
        declared = payload.get("budget") or {}
        limits = {
            key: float(declared.get(key, defaults[key]))
            for key in ("wall_clock_s", "lean_queries", "cas_runs", "prover_cycles")
        }
        return cls(limits=limits)

    def wall_clock_s(self) -> float:
        return time.perf_counter() - self.t0

    def check_wall_clock(self) -> None:
        if self.wall_clock_s() > self.limits["wall_clock_s"]:
            raise BudgetExceeded(
                f"wall clock exceeded {self.limits['wall_clock_s']}s"
            )

    def charge_lean_query(self) -> None:
        self.check_wall_clock()
        if self.lean_queries + 1 > self.limits["lean_queries"]:
            raise BudgetExceeded(
                f"lean query budget exhausted ({int(self.limits['lean_queries'])})"
            )
        self.lean_queries += 1

    def charge_prover_cycle(self) -> None:
        self.check_wall_clock()
        if self.prover_cycles + 1 > self.limits["prover_cycles"]:
            raise BudgetExceeded(
                f"prover cycle budget exhausted ({int(self.limits['prover_cycles'])})"
            )
        self.prover_cycles += 1

    def account_cas_runs(self, n: int) -> None:
        """CAS runs happen inside the skeptic lane's own loop; they are
        accounted after the fact (the lane's per-check timeouts bound
        the spend)."""
        self.cas_runs += n

    def totals(self) -> dict[str, Any]:
        return {
            "wall_clock_s": self.wall_clock_s(),
            "lean_queries": self.lean_queries,
            "cas_runs": self.cas_runs,
            "prover_cycles": self.prover_cycles,
        }


def _counting_verifier(lean_verify: LeanVerify, ledger: BudgetLedger) -> LeanVerify:
    async def wrapped(snippet: str, imports: list[str]) -> Mapping[str, Any]:
        ledger.charge_lean_query()
        return await lean_verify(snippet, imports)

    return wrapped


# ---------------------------------------------------------------------------
# Cross-check rule (AC-D.12)
# ---------------------------------------------------------------------------


def detect_evidence_conflict(
    *,
    formal_ok: bool,
    counterexample: Mapping[str, Any] | None,
) -> list[str]:
    """Pure conflict detector: a formal proof passing the hardened
    award while a counterexample stands against the claim (or vice
    versa — same pair) is the seeded-misformalization signature: the
    formal statement almost certainly diverges from the NL claim.
    Returns loud reasons when both evidences coexist; empty otherwise.
    """
    if not formal_ok or counterexample is None:
        return []
    return [
        "evidence conflict (AC-D.12): a formal proof passed the hardened award "
        "while a counterexample stands against the claim "
        f"({counterexample.get('source')} {counterexample.get('check')}) — "
        "the formal statement likely diverges from the NL claim "
        "(misformalization); verdict forced to abstained and the run escalated "
        "for human review",
    ]


# ---------------------------------------------------------------------------
# KAT controls (AC-D.8 / AC-D.9)
# ---------------------------------------------------------------------------


async def run_kat_controls(
    *,
    lean_verify: LeanVerify | None,
    seed: int,
    fixture: Mapping[str, Any] | None = None,
    artifact_dir: Path | str | None = None,
) -> tuple[KatRunReport, dict[str, Any]]:
    """Run the sampled per-run control subset and score it.

    Resolution is honest, not oracular (the d2
    ``test_per_run_controls_end_to_end`` grain): a TRUE-formal control
    resolves through the real verifier via
    :func:`server.kat.formal_verdict`; a FALSE control resolves
    ``refuted`` only when its fixture witness is kernel-accepted and
    soundness-clean (:func:`server.kat.witness_ok`); an OPEN control —
    for which no evidence exists by definition — resolves ``abstained``.
    With no verifier wired, every formal resolution degrades to
    ``abstained`` (which fails the TRUE-formal control and correctly
    marks the run non-reportable — controls cannot be met on faith).

    Any proven-* on a FALSE/OPEN control raises
    :class:`server.kat.KatEscalation` (AC-D.9 hard halt). Returns the
    report plus the bundle's ``controls`` block.

    Control spend is calibration overhead, deliberately outside the
    task's budget ledger (a task budget must not be exhaustible by its
    own controls).
    """
    fx = fixture if fixture is not None else load_kat_fixture()
    controls = sample_controls(fx, seed=seed)
    verdicts: dict[str, str] = {}
    for entry in controls:
        cls = entry["class"]
        if cls == TRUE_KNOWN_FORMAL:
            formal = entry.get("formal") or {}
            if formal.get("snippet") and lean_verify is not None:
                result = await lean_verify(
                    formal["snippet"], list(formal.get("imports") or ())
                )
                verdicts[entry["id"]] = formal_verdict(result)
            else:
                verdicts[entry["id"]] = "abstained"
        elif cls == FALSE_MUST_REJECT:
            witness = (entry.get("counterexample") or {}).get("witness_lean")
            if witness and lean_verify is not None:
                result = await lean_verify(
                    witness["snippet"], list(witness.get("imports") or ())
                )
                verdicts[entry["id"]] = (
                    "refuted" if witness_ok(result) else "abstained"
                )
            else:
                verdicts[entry["id"]] = "abstained"
        elif cls == OPEN_MUST_ABSTAIN:
            verdicts[entry["id"]] = "abstained"
    report = raise_if_escalated(
        evaluate_run(fx, verdicts, artifact_dir=artifact_dir)
    )
    return report, controls_block(report)


def controls_block(report: KatRunReport) -> dict[str, Any]:
    """The EvidenceBundle ``payload["controls"]`` block for a scored
    control run (AC-D.8)."""
    return {
        "kat_run_id": report.run_id,
        "kat_ids_run": [o.entry_id for o in report.outcomes],
        "abstention_rate": report.abstention_rate,
        "reportable": report.reportable,
    }


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------


@dataclass
class OrchestratorResult:
    """One run's outcome: the validated EvidenceBundle document plus
    the engine's own trace (for logs/tests; everything load-bearing is
    IN the bundle — the bundle is the artifact of record)."""

    bundle: dict[str, Any]
    verdict: str
    verdict_reasons: list[str]
    escalated: bool
    lane_trace: list[dict[str, Any]]
    skeptic_result: SkepticLaneResult | None
    budget: dict[str, Any]


async def run_proving_pipeline(
    *,
    task: Mapping[str, Any],
    role_outputs: RoleOutputs,
    lean_verify: LeanVerify | None,
    cas_on: bool | None = None,
    controls: Mapping[str, Any] | None = None,
    prior_formal_result: Mapping[str, Any] | None = None,
    producer: str = f"proving-orchestrator-{ORCHESTRATOR_VERSION}",
    substrate: Mapping[str, Any] | None = None,
) -> OrchestratorResult:
    """Drive one ProofTask through the lanes and emit its
    EvidenceBundle (see the module docstring for the full contract).

    ``controls`` is the pre-scored AC-D.8 block from
    :func:`run_kat_controls` (production callers run controls first —
    escalation halts before this pipeline starts). ``prior_formal_result``
    is a hardened ``lean_verify`` envelope from a previous cycle of the
    same task (fixer re-entry); the skeptic lane still runs first, and
    a lane counterexample against a prior formal award triggers the
    AC-D.12 conflict exit. ``substrate`` overrides the envelope pins
    (default: the task's own substrate — same corpus, same run).
    """
    validate_proof_task(task)
    payload: Mapping[str, Any] = task["payload"]
    task_id: str = payload["task_id"]
    plan = lane_plan_for(payload.get("field_lane"))
    ledger = BudgetLedger.from_task(payload)
    started_at = datetime.now(UTC).isoformat()

    lane_trace: list[dict[str, Any]] = []
    verdict = "abstained"
    reasons: list[str] = ["no verdict earned (abstained is the structural default)"]
    confidence = "low"
    escalated = False
    counterexample: dict[str, Any] | None = None
    faithfulness_block: dict[str, Any] | None = None
    formal_evidence: dict[str, Any] = {"attempts": [], "best_result": None}
    best_result: Mapping[str, Any] | None = None
    budget_exhausted: str | None = None
    lean_provenance: dict[str, Any] = {}

    if prior_formal_result is not None:
        prior_ok, _ = formal_award_ok(dict(prior_formal_result))
        formal_evidence["prior_result"] = dict(prior_formal_result)
        formal_evidence["prior_award_ok"] = prior_ok
        if prior_ok:
            best_result = prior_formal_result

    counting = (
        _counting_verifier(lean_verify, ledger) if lean_verify is not None else None
    )

    # --- Lane 1, always: the D-5 counterexample-first skeptic pass ---
    lean_specs, cas_specs = checks_from_proof_task(payload)
    skeptic_result: SkepticLaneResult | None = None
    try:
        skeptic_result = await run_skeptic_lane(
            lean_checks=lean_specs,
            cas_checks=cas_specs,
            lean_verify=counting,
            cas_on=cas_on,
        )
        ledger.account_cas_runs(skeptic_result.budget.get("cas_runs", 0))
        _note_lean_provenance(lean_provenance, skeptic_result.checks)
        if skeptic_result.verdict == "refuted":
            counterexample = skeptic_result.counterexample
            lane_trace.append(
                {"lane": "skeptic", "status": "refuted", "hit": counterexample["check"]}
            )
        else:
            lane_trace.append({"lane": "skeptic", "status": "passed"})
    except BudgetExceeded as exc:
        budget_exhausted = str(exc)
        lane_trace.append({"lane": "skeptic", "status": "budget-exhausted"})

    # --- Conflict check against prior formal evidence (AC-D.12) ---
    conflict_reasons = detect_evidence_conflict(
        formal_ok=best_result is not None, counterexample=counterexample
    )
    if conflict_reasons:
        verdict, reasons, confidence = "abstained", conflict_reasons, "low"
        escalated = True
        counterexample = None  # the conflict invalidates the refutation too
    elif counterexample is not None:
        # Lane refutation: short-circuit — no prover cycle runs
        # (AC-D.10; the bundle's budget accounting is the proof).
        verdict = "refuted"
        confidence = "high" if counterexample.get("kernel_confirmed") else "medium"
        reasons = [
            "skeptic lane: counterexample hit "
            f"({counterexample['source']} {counterexample['check']})"
        ]
    elif budget_exhausted is None:
        # --- Prover lanes, in the field-tier plan's order ---
        for lane in plan["lane_order"][1:]:
            if lane == "informal":
                lane_trace.append({"lane": "informal", "status": "not-automated-v0"})
                continue
            if lane == "cas":
                completed = [
                    c
                    for c in (skeptic_result.checks if skeptic_result else [])
                    if c.get("lane") == "cas"
                    and c.get("status") == "ok"
                    and c.get("found") is False
                ]
                lane_trace.append(
                    {
                        "lane": "cas",
                        "status": "numeric-support" if completed else "no-evidence",
                        "completed_scans": [c.get("check") for c in completed],
                    }
                )
                continue
            if lane == "formal":
                try:
                    best_result = await _run_formal_lane(
                        role_outputs=role_outputs,
                        counting=counting,
                        ledger=ledger,
                        formal_evidence=formal_evidence,
                        lane_trace=lane_trace,
                        best_result=best_result,
                        lean_provenance=lean_provenance,
                    )
                except BudgetExceeded as exc:
                    budget_exhausted = str(exc)
                    lane_trace.append({"lane": "formal", "status": "budget-exhausted"})
                    break

        # --- Faithfulness gate (only in reach of proven-formal) ---
        if budget_exhausted is None and best_result is not None:
            faithfulness_block, budget_exhausted = await _run_faithfulness(
                payload=payload,
                role_outputs=role_outputs,
                counting=counting,
                lane_trace=lane_trace,
            )

        # --- Verdict resolution (pure award rules; abstained default) ---
        if budget_exhausted is None:
            verdict, reasons, confidence = _resolve_verdict(
                plan=plan,
                best_result=best_result,
                faithfulness_block=faithfulness_block,
                lane_trace=lane_trace,
                proves_formalization=formal_evidence.get("best_proves_formalization"),
            )

    # --- THE verdict-award choke-point (stage3/proving-r3 class fix) ---
    # EVERY verdict-award path above (conflict exit, lane refutation,
    # prover award) converges here, so no path can emit a confident
    # verdict without a recorded, checked evidence↔claim linkage. The
    # refutation side is checked via the author-declared, kernel-verified
    # discharged proposition; the proof side re-checks the round-1
    # formalization⇔proof invariant (belt AND suspenders over
    # `_resolve_verdict`). Budget exhaustion below still overrides to
    # `abstained` (which the choke-point passes through), so this runs
    # before that override only for the non-exhausted paths.
    if budget_exhausted is None:
        linkage = award_linked_verdict(
            verdict,
            confidence,
            counterexample=counterexample,
            proves_formalization=formal_evidence.get("best_proves_formalization"),
            faithfulness_block=faithfulness_block,
        )
        if not linkage.linked:
            # A confident verdict lost its linkage — cap it, and drop the
            # now-unsupported counterexample from the bundle (a capped
            # refutation is not a refutation). The capped `refuted`
            # becomes `abstained`; the escalation net below still fires on
            # the residual paths (a KAT control that genuinely refutes).
            verdict = linkage.verdict
            confidence = linkage.confidence
            reasons = [*linkage.reasons, *reasons]
            if counterexample is not None and verdict != "refuted":
                counterexample = None

    if budget_exhausted is not None:
        # AC-D.15: exhaustion maps to abstained with best partial
        # evidence attached — NEVER the highest verdict reached so far.
        verdict = "abstained"
        confidence = "low"
        reasons = [
            f"budget exhausted ({budget_exhausted}); best partial evidence "
            "attached — exhaustion never awards the highest verdict reached "
            "(AC-D.15)"
        ]

    # Defense-in-depth mirror of the KAT harness rule (AC-D.9): a
    # proven-* on a control task with established-FALSE truth is
    # flagged in the bundle itself.
    #
    # CONTROL-PROVENANCE GATE (findings: known-truth-escalation-bypass).
    # ``known_truth`` is UNTRUSTED task payload — the same author-controlled
    # payload that carries ``skeptic_checks[].snippet``, the input the whole
    # ``verdict_linkage`` choke-point exists to distrust. The schema only
    # ADVISES real tasks to leave it null ("ONLY set for KAT/control tasks");
    # NOTHING upstream rejects a real task that stamps ``known_truth=false``
    # (validate_proof_task does not, and genuine controls never even reach
    # this pipeline — ``run_kat_controls`` scores them directly). So a bare
    # ``known_truth=false`` MUST NOT, on its own, be able to SUPPRESS the
    # mandatory real-task refutation escalation below — the sole backstop for
    # the acknowledged ``declared-proposition ⇒ ¬claim`` entailment residual
    # (verdict_linkage.py:104-114). Suppressing it with one schema-valid field
    # re-opens the exact round-2 threat model (a kernel-sound witness of an
    # unrelated true fact "refuting" a true theorem). A non-null
    # ``known_truth`` is therefore HONORED only when the task ALSO carries
    # control provenance — a non-empty ``kat_id`` self-labelling it a
    # KAT/control task (auditable in the bundle; in a KAT-aware pipeline this
    # is the id whose statement/verdict the harness scores against the fixture,
    # red-alarming a mismatch). Without that marker the task is treated as a
    # REAL task (``known_truth`` None) for escalation, so its ``refuted``
    # escalates like any other real-task refutation. FAIL CLOSED: the only
    # escalation ``known_truth`` can SUPPRESS (a genuine FALSE control's
    # expected ``refuted``) now requires provenance; a non-null ``known_truth``
    # can otherwise only ever ADD an escalation, never remove one. (Residual,
    # stated honestly: ``kat_id`` is itself author-supplied, so this closes the
    # bare-``known_truth`` masquerade — the reported exploit — not a determined
    # author who ALSO forges a ``kat_id``; the design already trusts ``kat_id``
    # as the control marker, and the existing escalation tests pin synthetic
    # ids like ``kat-fm-99``. See the fix note.)
    kat_id = payload.get("kat_id")
    has_control_provenance = isinstance(kat_id, str) and bool(kat_id.strip())
    effective_known_truth = payload.get("known_truth") if has_control_provenance else None
    if effective_known_truth is False and verdict in PROVEN_VERDICTS:
        escalated = True
        reasons = [
            "RED ALARM: proven-* verdict on a task with known_truth=false — "
            "escalated for human review (AC-D.9)",
            *reasons,
        ]
    # OPEN-must-abstain controls (convergence R-OPEN-1): the KAT harness
    # (server/kat.py::evaluate_run) red-alarms a proven-* verdict on BOTH a
    # FALSE-must-reject AND an OPEN-must-abstain control. The FALSE arm is the
    # branch above; this is the OPEN arm the in-bundle mirror was missing. An
    # OPEN control carries known_truth=None, so it is distinguished from a
    # genuine real-task proven-formal (the golden path, which MUST NOT
    # escalate) ONLY by control provenance: a proven-* here escalates iff the
    # task self-labels as a control (non-empty kat_id) AND declared no
    # established truth. Genuine real tasks have no kat_id → this never fires
    # on them; TRUE/FALSE controls are handled by their own branches; so this
    # can only ADD an escalation on exactly the OPEN-control proven-* case the
    # KAT rule flags. FAIL CLOSED.
    elif (
        has_control_provenance
        and effective_known_truth is None
        and verdict in PROVEN_VERDICTS
    ):
        escalated = True
        reasons = [
            "RED ALARM: proven-* verdict on an OPEN-must-abstain control "
            "(known_truth=null with control provenance) — the KAT harness "
            "rule flags this as a false acceptance; escalated for human "
            "review (AC-D.9, OPEN arm)",
            *reasons,
        ]
    # The symmetric net (findings: refuted-verdict-skips-statement-linkage):
    # a `refuted` on a control task with established-TRUE truth is a
    # confident false refutation of a true theorem. The skeptic lane
    # accepts a kernel-clean witness for its own SOUNDNESS but never
    # checks its RELEVANCE to the claim, so a witness that proves an
    # unrelated true proposition (e.g. ¬Prime(4) against "infinitely many
    # primes") lands here. Unlike an `abstained` TRUE control (a
    # completeness miss per AC-D.7), a `refuted` asserts a falsehood, so
    # it is a soundness alarm — flagged in the bundle itself.
    elif effective_known_truth is True and verdict in REFUTING_VERDICTS:
        escalated = True
        reasons = [
            "RED ALARM: refuted verdict on a task with known_truth=true — a "
            "counterexample witness sound in isolation but not established "
            "relevant to the claim refuted a known-true statement; escalated "
            "for human review (AC-D.9 symmetry)",
            *reasons,
        ]
    # Round-3 adversarial round 2 (findings: refutation semantic-entailment
    # gap on real tasks): a `refuted` on a REAL task (known_truth is None)
    # MUST be escalated. The choke-point machine-checks witness -> declared-
    # proposition (kernel) but NEVER declared-proposition -> ¬claim; that
    # entailment is the UNVERIFIABLE author attestation `discharges.
    # refutes_claim=true`, uncheckable pre-formalization (AC-D.10). The
    # `known_truth is True` branch above is INERT on real tasks — NOT
    # because the schema "pins" known_truth=null (it only ADVISES it;
    # relying on that pin was the known-truth-escalation-bypass hole), but
    # because the CONTROL-PROVENANCE GATE above normalizes any non-null
    # known_truth WITHOUT a kat_id to None, so a real task lands here
    # regardless of what the author stamped. Unlike the proof side, where a
    # proven-formal needs a mandatory human sign-off before it is
    # consumable, a `refuted` ships with NO human gate. So a kernel-valid
    # witness of ANY true auxiliary fact + an honest `refutes_claim:true`
    # would otherwise emit `refuted`/high, unescalated, for an ARBITRARY true
    # claim. Escalation is the required human gate here, mirroring the proof
    # side. The verdict STAYS `refuted` and the counterexample is preserved
    # (a genuine real-task refutation is still a refutation, just escalated
    # for human confirmation) — signal preserved, trust gated. Keys on
    # effective_known_truth is None, so provenance-established KAT controls +
    # the golden-path FALSE control (known_truth True/False WITH a kat_id)
    # are UNCHANGED.
    elif effective_known_truth is None and verdict in REFUTING_VERDICTS:
        escalated = True
        reasons = [
            "refutation entailment (declared proposition ⇒ ¬claim) is an "
            "unverifiable attestation pre-formalization and refutations carry "
            "no sign-off gate — escalated for human confirmation",
            *reasons,
        ]

    bundle_payload = _assemble_payload(
        task_id=task_id,
        verdict=verdict,
        confidence=confidence,
        reasons=reasons,
        escalated=escalated,
        counterexample=counterexample,
        skeptic_result=skeptic_result,
        formal_evidence=formal_evidence,
        faithfulness_block=faithfulness_block,
        controls=controls,
        plan=plan,
        lane_trace=lane_trace,
        payload_in=payload,
        role_outputs=role_outputs,
        ledger=ledger,
        started_at=started_at,
        budget_exhausted=budget_exhausted,
        lean_provenance=lean_provenance,
    )

    bundle = wrap_payload(
        artifact=EVIDENCE_BUNDLE_ARTIFACT,
        version=EVIDENCE_BUNDLE_VERSION,
        producer=producer,
        produced_at=datetime.now(UTC).isoformat(),
        substrate=dict(substrate if substrate is not None else task["bridge"]["substrate"]),
        payload=bundle_payload,
    )
    # A malformed bundle must never leave the engine — validation is
    # the exit gate on EVERY path (raises ContractValidationError).
    validate_evidence_bundle(bundle)

    logger.info(
        "proving pipeline: task=%s verdict=%s escalated=%s lanes=%s cost=%s",
        task_id,
        verdict,
        escalated,
        "→".join(t["lane"] + ":" + t["status"] for t in lane_trace),
        ledger.totals(),
    )
    return OrchestratorResult(
        bundle=bundle,
        verdict=verdict,
        verdict_reasons=reasons,
        escalated=escalated,
        lane_trace=lane_trace,
        skeptic_result=skeptic_result,
        budget=ledger.totals(),
    )


async def _run_formal_lane(
    *,
    role_outputs: RoleOutputs,
    counting: LeanVerify | None,
    ledger: BudgetLedger,
    formal_evidence: dict[str, Any],
    lane_trace: list[dict[str, Any]],
    best_result: Mapping[str, Any] | None,
    lean_provenance: dict[str, Any],
) -> Mapping[str, Any] | None:
    """Run prover cycles over the role loop's attempts (tactician
    first, then fixer), first hardened award wins. Raises
    :class:`BudgetExceeded` when a cycle cannot be afforded."""
    ordered = [a for a in role_outputs.attempts if a.role == "tactician"] + [
        a for a in role_outputs.attempts if a.role == "fixer"
    ]
    if not ordered:
        lane_trace.append({"lane": "formal", "status": "no-attempts"})
        return best_result
    if counting is None:
        lane_trace.append({"lane": "formal", "status": "no-verifier"})
        formal_evidence["attempts"] = [
            {
                "name": a.name,
                "role": a.role,
                "status": "unavailable",
                "detail": "no Lean verifier wired; attempt not run",
            }
            for a in ordered
        ]
        return best_result

    attempts_out: list[dict[str, Any]] = formal_evidence["attempts"]
    for attempt in ordered:
        if best_result is not None:
            break
        ledger.charge_prover_cycle()
        result = await counting(attempt.snippet, list(attempt.imports))
        ok, award_reasons = formal_award_ok(dict(result))
        provenance = result.get("provenance") or {}
        attempts_out.append(
            {
                "name": attempt.name,
                "role": attempt.role,
                "snippet": attempt.snippet,
                "imports": list(attempt.imports),
                "lean_status": result.get("status"),
                "award_ok": ok,
                "award_reasons": award_reasons,
                "transcript_sha256": provenance.get("transcript_sha256"),
            }
        )
        _note_lean_provenance(
            lean_provenance, [{"lean": True, "provenance": provenance}]
        )
        if ok:
            best_result = result
            formal_evidence["best_result"] = dict(result)
            formal_evidence["best_attempt"] = attempt.name
            # KERNEL-reported statement this proof proves — retained for
            # AUDIT/DISPLAY only (the elaborated type `#check @<name>`
            # reported). It is NO LONGER the linkage decider (durable P1
            # kernel-decides fix): a pretty-printed string cannot
            # distinguish `∃ x:ℝ, …` from `∃ x:ℚ, …` (Lean elides the
            # binder type), which was a live CRITICAL false-accept.
            formal_evidence["best_statement_lean"] = kernel_statement_for_snippet(
                attempt.snippet, result.get("kernel_statements")
            )
            # THE KERNEL decides the formalization⇔proof link (findings
            # #1/#2; durable P1 soundness fix). For each gate-checked
            # formalization the faithfulness gate consumes, ask the kernel
            # `example : <formalization> := @<decl>` in a fresh env; the
            # proof is linked iff the kernel accepts ONE of them. This
            # decides DEFINITIONAL EQUALITY — the ℝ/ℚ pretty-print
            # collision is denied, and a defeq-but-differently-phrased
            # formalization (`Nat` vs `ℕ`) still links (string-match
            # brittleness gone). Recorded as a boolean the pure award rule
            # (`proof_statement_linked`) consumes; the raw check envelopes
            # are recorded for audit. Fail-closed: no decl name, no
            # formalizations, a type-check error, or a verifier miss all
            # leave `proves_formalization` False -> caps to
            # plausible-unverified. The checks run through `counting`, so
            # their REPL round-trips are charged to the lean-query budget.
            proves, channel, checks = await _kernel_check_proves_formalization(
                attempt=attempt,
                role_outputs=role_outputs,
                counting=counting,
                lean_provenance=lean_provenance,
            )
            formal_evidence["best_proves_formalization"] = proves
            formal_evidence["best_proves_formalization_channel"] = channel
            formal_evidence["best_result"]["proves_formalization"] = proves
            formal_evidence["best_result"]["proves_formalization_channel"] = channel
            formal_evidence["proves_formalization_checks"] = checks
    lane_trace.append(
        {
            "lane": "formal",
            "status": "award-ok" if best_result is not None else "no-award",
            "cycles": ledger.prover_cycles,
        }
    )
    return best_result


async def _kernel_check_proves_formalization(
    *,
    attempt: ProofAttempt,
    role_outputs: RoleOutputs,
    counting: LeanVerify,
    lean_provenance: dict[str, Any],
) -> tuple[bool, str | None, list[dict[str, Any]]]:
    """Ask THE KERNEL whether the winning ``attempt`` proves one of the
    gate-checked formalizations (durable P1 kernel-decides fix).

    For each present formalization channel (A, then B) runs
    ``example : <formalization.statement_lean> := @<decl>`` — the combined
    snippet from :func:`server.lean_soundness.kernel_check_snippet`,
    elaborated in a FRESH env by the injected verifier — and treats it as
    linked iff :func:`server.lean_soundness.kernel_decides_linked` accepts
    the result. Short-circuits on the FIRST channel that links.

    Returns ``(proves, channel, checks)``:

    - ``proves`` — ``True`` iff some channel's kernel check accepted;
    - ``channel`` — the linking channel (``"A"`` / ``"B"``) or ``None``;
    - ``checks`` — a per-channel audit record list (channel, formalization,
      the check snippet, lean status, linked bool).

    Fail-closed on every edge: the winning attempt has no
    name-extractable declaration (anonymous ``example`` / unicode name),
    no formalization channels are present, or every kernel check errors /
    misses — ``proves`` is ``False``, so the pure award rule caps the
    verdict to ``plausible-unverified``. The imports passed to each check
    are the union of the attempt's imports and the formalization's own
    (the formalization may reference lemmas the bare proof did not import).
    ``BudgetExceeded`` from ``counting`` propagates to the caller (the
    formal lane), which converts it to the AC-D.15 abstained exit — an
    unaffordable linkage check is fail-closed, never an assumed link.
    """
    checks: list[dict[str, Any]] = []
    decls = extract_decl_names(attempt.snippet)
    if not decls:
        checks.append(
            {
                "channel": None,
                "linked": False,
                "detail": (
                    "winning attempt has no name-extractable theorem/lemma "
                    "declaration (anonymous example / unicode name) — cannot "
                    "build `example : <formalization> := @<decl>`; fail-closed"
                ),
            }
        )
        return False, None, checks
    decl = decls[0]
    channels: list[tuple[str, FormalizationRecord]] = [
        (ch, rec)
        for ch, rec in (
            ("A", role_outputs.formalization_a),
            ("B", role_outputs.formalization_b),
        )
        if rec is not None
    ]
    if not channels:
        checks.append(
            {
                "channel": None,
                "linked": False,
                "detail": "no formalization channels present to link against",
            }
        )
        return False, None, checks
    for ch, rec in channels:
        check_snippet = kernel_check_snippet(attempt.snippet, rec.statement_lean, decl)
        imports = sorted(set(attempt.imports) | set(rec.imports))
        result = await counting(check_snippet, imports)
        _note_lean_provenance(
            lean_provenance,
            [{"lean": True, "provenance": result.get("provenance") or {}}],
        )
        linked = kernel_decides_linked(result)
        checks.append(
            {
                "channel": ch,
                "formalization": rec.statement_lean,
                "check_snippet": check_snippet,
                "imports": imports,
                "lean_status": result.get("status"),
                "linked": linked,
            }
        )
        if linked:
            return True, ch, checks
    return False, None, checks


async def _run_faithfulness(
    *,
    payload: Mapping[str, Any],
    role_outputs: RoleOutputs,
    counting: LeanVerify | None,
    lane_trace: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None]:
    """Run the D-3 gate when the role loop produced both channels.
    Returns ``(block, budget_exhausted_reason)``."""
    if role_outputs.formalization_a is None or role_outputs.formalization_b is None:
        lane_trace.append(
            {"lane": "formal", "status": "faithfulness-gate-missing-channels"}
        )
        return None, None
    try:
        gate = await run_faithfulness_gate(
            statement_latex=payload["statement_latex"],
            formalization_a=role_outputs.formalization_a,
            formalization_b=role_outputs.formalization_b,
            back_translation=role_outputs.back_translation,
            skeptic_diff=role_outputs.skeptic_diff,
            lean_verify=counting,
            statement_nl=payload.get("statement_nl"),
        )
    except BudgetExceeded as exc:
        lane_trace.append({"lane": "formal", "status": "faithfulness-gate-budget-exhausted"})
        return None, str(exc)
    lane_trace.append(
        {
            "lane": "formal",
            "status": "faithfulness-gate-ok" if gate.gate_ok else "faithfulness-gate-failed",
        }
    )
    return gate.to_faithfulness_block(), None


def _resolve_verdict(
    *,
    plan: Mapping[str, Any],
    best_result: Mapping[str, Any] | None,
    faithfulness_block: Mapping[str, Any] | None,
    lane_trace: Sequence[Mapping[str, Any]],
    proves_formalization: bool | None = None,
) -> tuple[str, list[str], str]:
    """Pure verdict resolution over the assembled evidence (AC-D.13
    grain — no LLM, no REPL). Abstained by default; every upgrade is
    earned through the award rules; the lane ceiling caps last.

    ``proves_formalization`` is the BOOLEAN the formal lane recorded from
    the per-award kernel check ``example : <formalization> := @<decl>``
    (findings #1/#2; durable P1 kernel-decides fix). It is ``None`` for a
    prior-result award (no snippet in hand to kernel-check) — which
    correctly fails the linkage closed and caps below ``proven-formal``."""
    if best_result is not None:
        verdict, award_reasons = award_statement_verdict(
            best_result,
            faithfulness_block,
            publishable=False,
            proves_formalization=proves_formalization,
        )
        reasons = award_reasons or [
            "formal award + complete faithfulness record (pre-sign-off)"
        ]
        confidence = "high" if verdict == "proven-formal" else "low"
    else:
        cas_support = any(
            t.get("lane") == "cas" and t.get("status") == "numeric-support"
            for t in lane_trace
        )
        if cas_support:
            verdict = "plausible-unverified"
            reasons = [
                "CAS lane: completed counterexample scans found no witness — "
                "numeric support only, never a proof"
            ]
            confidence = "low"
        else:
            return (
                "abstained",
                ["no verdict earned (abstained is the structural default)"],
                "low",
            )

    capped, cap_reasons = apply_lane_ceiling(verdict, plan["verdict_ceiling"])
    if cap_reasons:
        verdict = capped
        reasons = [*cap_reasons, *reasons]
        confidence = "low"
    return verdict, reasons, confidence


def _note_lean_provenance(
    lean_provenance: dict[str, Any], checks: Sequence[Mapping[str, Any]]
) -> None:
    """Record the last-seen Lean toolchain pins for the bundle
    provenance block (every hardened envelope carries them)."""
    for check in checks:
        prov = check.get("provenance")
        if isinstance(prov, Mapping):
            for key in ("lean_toolchain", "mathlib_rev"):
                if prov.get(key):
                    lean_provenance[key] = prov[key]


def _assemble_payload(
    *,
    task_id: str,
    verdict: str,
    confidence: str,
    reasons: list[str],
    escalated: bool,
    counterexample: Mapping[str, Any] | None,
    skeptic_result: SkepticLaneResult | None,
    formal_evidence: Mapping[str, Any],
    faithfulness_block: Mapping[str, Any] | None,
    controls: Mapping[str, Any] | None,
    plan: Mapping[str, Any],
    lane_trace: list[dict[str, Any]],
    payload_in: Mapping[str, Any],
    role_outputs: RoleOutputs,
    ledger: BudgetLedger,
    started_at: str,
    budget_exhausted: str | None,
    lean_provenance: Mapping[str, Any],
) -> dict[str, Any]:
    context = payload_in.get("statement_context")
    provenance: dict[str, Any] = {
        "orchestrator_version": ORCHESTRATOR_VERSION,
        "lane_plan": dict(plan),
        "lane_trace": lane_trace,
        "context_pack_sha256": context_pack_sha256(context),
        "context_pack_violations": context_pack_violations(context),
        "sketch_present": role_outputs.sketch is not None,
        "started_at": started_at,
        "created_at": datetime.now(UTC).isoformat(),
        **dict(lean_provenance),
    }
    if budget_exhausted is not None:
        provenance["budget_exhausted"] = budget_exhausted

    payload: dict[str, Any] = {
        "task_id": task_id,
        "verdict": verdict,
        "verdict_confidence": confidence,
        "verdict_reasons": reasons,
        "escalated": escalated,
        # The pipeline NEVER emits a publishable bundle: publication
        # requires the operator sign-off surface (tools/sign_bundle.py)
        # and the D-3 gate's checkbox — make_publishable_bundle below.
        "publishable": False,
        "provenance": provenance,
        "cost": ledger.totals(),
    }
    if counterexample is not None:
        payload["counterexample"] = dict(counterexample)
    if skeptic_result is not None:
        payload["skeptic"] = skeptic_result.to_skeptic_block()
        payload["cas"] = skeptic_result.cas_artifacts()
    if (
        formal_evidence.get("attempts")
        or formal_evidence.get("best_result") is not None
        or formal_evidence.get("prior_result") is not None
    ):
        payload["formal"] = dict(formal_evidence)
    if faithfulness_block is not None:
        payload["faithfulness"] = dict(faithfulness_block)
    if controls is not None:
        payload["controls"] = dict(controls)
    return payload


# ---------------------------------------------------------------------------
# Publishable award (operator surface — the pipeline never calls this)
# ---------------------------------------------------------------------------


def _rederive_proves_formalization(formal: Mapping[str, Any]) -> bool:
    """Recover the formalization⇔proof kernel-decision for the
    publishable-path linkage check from the bundle's OWN evidence.

    Durable P1 kernel-decides fix: the decision is the boolean the formal
    lane recorded from the per-award kernel check
    ``example : <formalization> := @<decl>`` (see
    :func:`_kernel_check_proves_formalization`), persisted on the winning
    envelope as ``formal.best_result.proves_formalization``. This reads
    the value the KERNEL produced at prove time — it is not re-scanned
    author text, and (unlike the old string re-derivation) the publishable
    path does NOT re-run the REPL.

    Returns ``True`` only when that persisted boolean is exactly ``True``;
    anything else (``None``/absent — a prior-result award that carries no
    per-attempt kernel check, or an older envelope) is ``False``, so the
    linkage fails closed. A prior kernel result was never run through the
    per-award formalization check, so it cannot be published through this
    path without an attempt whose declaration the kernel confirmed proves
    a gate-checked formalization.
    """
    best_result = formal.get("best_result")
    if isinstance(best_result, Mapping):
        return best_result.get("proves_formalization") is True
    return False


def make_publishable_bundle(
    bundle: Mapping[str, Any],
    signed_faithfulness_block: Mapping[str, Any],
) -> dict[str, Any]:
    """Assemble the publishable form of a pipeline bundle from an
    operator-SIGNED faithfulness block.

    This function does not sign anything: the block must already carry
    ``human_signoff.signed=true`` from
    ``server.proving.faithfulness.record_human_signoff`` — which only
    the operator surface (``tools/sign_bundle.py``) may call. The
    publishable verdict is re-derived fail-closed from the bundle's
    own formal evidence plus the signed block via the pure award rule
    (``award_statement_verdict(..., publishable=True)``); anything
    short of ``proven-formal`` refuses (a publishable bundle that is
    not a full award has no reason to exist — lower-verdict bundles
    are published as-is only through human editorial channels, not
    this path). The result is re-validated against the bundle schema,
    whose own law requires the checkbox on every
    ``publishable: true`` + ``proven-formal`` bundle.

    The statement-linkage check (findings #1/#2) is re-derived here from
    the bundle's OWN kernel evidence: the boolean the formal lane recorded
    from the per-award kernel check ``example : <formalization> := @<decl>``,
    persisted on ``formal.best_result.proves_formalization`` (durable P1
    kernel-decides fix). A prior-result award carries no per-attempt kernel
    check, so ``proves_formalization`` is absent and the linkage fails
    closed — a prior kernel result can never be published through this
    path without an attempt whose declaration the kernel confirmed proves
    a gate-checked formalization.
    """
    payload = bundle.get("payload") or {}
    formal = payload.get("formal") or {}
    best_result = formal.get("best_result") or formal.get("prior_result")
    if best_result is None:
        raise ValueError(
            "bundle carries no hardened formal result; nothing to publish"
        )
    proves_formalization = _rederive_proves_formalization(formal)
    verdict, award_reasons = award_statement_verdict(
        best_result,
        signed_faithfulness_block,
        publishable=True,
        proves_formalization=proves_formalization,
    )
    if verdict != "proven-formal":
        raise ValueError(
            "publishable award refused: the re-derived verdict is "
            f"{verdict!r}, not 'proven-formal' — {'; '.join(award_reasons[:5])}"
        )
    published = json.loads(json.dumps(bundle))  # deep copy, JSON grain
    published["payload"]["verdict"] = "proven-formal"
    published["payload"]["verdict_confidence"] = "high"
    published["payload"]["verdict_reasons"] = [
        "formal award + complete faithfulness record + human sign-off "
        f"(signed by {signed_faithfulness_block['human_signoff']['by']!r})"
    ]
    published["payload"]["faithfulness"] = dict(signed_faithfulness_block)
    published["payload"]["publishable"] = True
    validate_evidence_bundle(published)
    return published


__all__ = [
    "ATTEMPT_ROLES",
    "KNOWN_LANES",
    "LANE_CONFIG_PATH",
    "ORCHESTRATOR_VERSION",
    "PROVEN_VERDICTS",
    "REFUTING_VERDICTS",
    "BudgetExceeded",
    "BudgetLedger",
    "LaneConfigError",
    "OrchestratorResult",
    "ProofAttempt",
    "RoleOutputs",
    "apply_lane_ceiling",
    "context_pack_sha256",
    "context_pack_violations",
    "controls_block",
    "detect_evidence_conflict",
    "lane_plan_for",
    "load_lane_config",
    "make_publishable_bundle",
    "run_kat_controls",
    "run_proving_pipeline",
]
