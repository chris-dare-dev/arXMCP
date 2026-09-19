"""D-5 counterexample-first skeptic lane (stage2/arx-d3 — WS-D;
AC-D.10/AC-D.11/AC-D.7).

The lane runs **before any prover cycle**: for a claim with a small
counterexample, ``decide``/``norm_num`` witnesses, a falsification
search tactic (``plausible``; ``slim_check`` on older mathlib), or a
sandboxed SymPy scan should find the witness and terminate the run
``refuted`` **without spending proof-search budget**. The lane's own
budget record pins ``prover_cycles: 0`` — the EvidenceBundle carries
that accounting as the AC-D.10 proof.

Check kinds
-----------

- **Lean "witness"** — a snippet that *proves* a refutation witness
  (e.g. ``example : ¬ Nat.Prime (40 ^ 2 + 40 + 41) := by norm_num``).
  A hit requires the hardened ``lean_verify`` envelope to be
  kernel-accepted AND soundness-clean (:func:`server.kat.witness_ok`)
  AND free of sorry-taint (see below) — the refutation side is as
  fail-closed as the award side. ``kernel_confirmed=True``.
- **Lean "search"** — a snippet asserting the ORIGINAL claim under a
  falsification-search tactic. On the D-1 toolchain
  (mathlib v4.30.0-rc2) the tactic is ``plausible`` (``slim_check`` was
  removed upstream — probed live on this REPL); a hit surfaces as an
  error message ``Found a counter-example!`` with ``var := value``
  binding lines, which the lane parses into a structured witness.
  ``kernel_confirmed=False`` — evaluation-checked, not kernel-checked.
- **CAS (SymPy)** — :mod:`server.proving.sympy_runner` specs. A hit is
  ``status == "ok" and found`` with the returned witness.
  ``kernel_confirmed=False``. Flag off ⇒ the runner refuses (recorded
  as ``cas_refused``); the lane NEVER fabricates a pass or a hit from
  a refused check.

**Sorry-taint (probed live, load-bearing).** When ``plausible`` finds
no counterexample it admits the goal via ``sorry``: the REPL reports
no error and no ``sorries`` row — only a ``declaration uses `sorry```
warning — so the normalized envelope is ``status: "ok"`` with
``compilation_success: true``, and (for an anonymous ``example``,
which the axiom audit cannot name-extract) ``witness_ok`` alone would
accept it as a valid witness. The lane therefore additionally rejects
any result whose messages mention ``sorry`` before counting a witness
hit. Pinned by a unit test and a gated real-REPL test.

The lane is a **library** consumed by the D-6 orchestrator and the
test suites; it registers nothing on the MCP surface. The Lean checks
go through an injected async verifier — production callers pass
``server.handlers.lean_verify.handle_lean_verify`` (with Resources
wired); unit tests inject fakes.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from server.kat import witness_ok, witness_sorry_tainted
from server.lean_soundness import (
    extract_decl_names,
    kernel_check_snippet,
    kernel_decides_linked,
    kernel_statement_for_snippet,
)
from server.proving.sympy_runner import CasCheckSpec, run_cas_check

logger = logging.getLogger(__name__)

#: Async verifier signature: ``(snippet, imports) -> lean_verify result``.
LeanVerify = Callable[[str, list[str]], Awaitable[Mapping[str, Any]]]

LEAN_CHECK_KINDS: tuple[str, ...] = ("witness", "search")

#: Counterexample-search hit/no-hit message patterns (probed live on
#: the D-1 mathlib REPL; Plausible prints "Found a counter-example!" /
#: "Unable to find a counter-example". Both spellings tolerated.)
_HIT_RE = re.compile(r"found a counter-?example", re.IGNORECASE)
_NO_HIT_RE = re.compile(r"unable to find a counter-?example", re.IGNORECASE)

#: ``var := value`` binding lines inside a Plausible counterexample
#: message (e.g. ``n := 44``).
_BINDING_RE = re.compile(r"^\s*([^\s:=]+)\s*:=\s*(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class LeanCheckSpec:
    """One Lean-lane skeptic check (see module docstring for kinds).

    ``discharges`` is the author's structured declaration of which
    claim-derived proposition a ``witness`` snippet discharges — the
    round-3 refutation statement-linkage input (proof-task.v0.3
    ``skeptic_checks.lean[].discharges``). Shape:
    ``{"proposition": <Lean text>, "refutes_claim": true,
    "justification": <why it entails ¬claim>}``. The verdict-linkage
    choke-point kernel-checks the witness's proved statement against
    ``proposition`` and requires ``refutes_claim: true`` before a
    confident ``refuted`` is earned. Optional and back-compatible: a
    ``witness`` check without it is capped/escalated (fail-closed),
    never opened; ``search`` checks are linked by construction and
    ignore it.
    """

    name: str
    kind: str
    snippet: str
    imports: tuple[str, ...] = ()
    description: str | None = None
    discharges: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise ValueError("LeanCheckSpec.name must be a non-empty string")
        if self.kind not in LEAN_CHECK_KINDS:
            raise ValueError(
                f"check {self.name!r}: kind must be one of "
                f"{LEAN_CHECK_KINDS}; got {self.kind!r}"
            )
        if not self.snippet or not isinstance(self.snippet, str):
            raise ValueError(f"check {self.name!r}: snippet must be a non-empty string")
        if self.discharges is not None and not isinstance(self.discharges, Mapping):
            raise ValueError(
                f"check {self.name!r}: discharges must be an object when present"
            )
        # Normalize list inputs (JSON-sourced specs) to the frozen tuple.
        object.__setattr__(self, "imports", tuple(self.imports))


@dataclass
class SkepticLaneResult:
    """The lane's structured outcome.

    ``verdict`` is ``"refuted"`` (a counterexample hit — terminate the
    run, do NOT start prover cycles) or ``"passed"`` (no counterexample
    found — the prover lanes may proceed). The lane can never emit a
    proven-* verdict by construction.
    """

    verdict: str
    counterexample: dict[str, Any] | None
    checks: list[dict[str, Any]]
    cas_refused: bool
    budget: dict[str, Any]
    started_at: str
    finished_at: str

    def to_skeptic_block(self) -> dict[str, Any]:
        """The EvidenceBundle ``payload["skeptic"]`` block."""
        return {
            "ran": True,
            "refuted": self.verdict == "refuted",
            "cas_refused": self.cas_refused,
            "checks": list(self.checks),
            "budget": dict(self.budget),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    def cas_artifacts(self) -> list[dict[str, Any]]:
        """The EvidenceBundle ``payload["cas"]`` artifact list (every
        CAS envelope, including refused/disabled ones — the refusal is
        itself evidence)."""
        return [c for c in self.checks if c.get("lane") == "cas"]

    def to_evidence_payload(self, task_id: str) -> dict[str, Any]:
        """Build the EvidenceBundle *payload* for a lane refutation.

        Only valid when the lane refuted: the final verdict of a
        non-refuted run belongs to the downstream prover lanes and the
        award rules, never to the skeptic lane.
        """
        if self.verdict != "refuted" or self.counterexample is None:
            raise ValueError(
                "to_evidence_payload is only valid for a lane refutation; "
                f"this lane result is {self.verdict!r}"
            )
        return {
            "task_id": task_id,
            "verdict": "refuted",
            "verdict_confidence": (
                "high" if self.counterexample.get("kernel_confirmed") else "medium"
            ),
            "verdict_reasons": [
                "skeptic lane: counterexample hit "
                f"({self.counterexample['source']} {self.counterexample['check']})"
            ],
            "escalated": False,
            "counterexample": dict(self.counterexample),
            "skeptic": self.to_skeptic_block(),
            "cas": self.cas_artifacts(),
            "cost": dict(self.budget),
        }


def _messages(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [m for m in (result.get("messages") or []) if isinstance(m, dict)]


#: The Plausible-admission sorry-taint scan is defined once in
#: ``server.kat`` (:func:`server.kat.witness_sorry_tainted`) and folded
#: into :func:`server.kat.witness_ok` at round 3. This alias preserves
#: the lane-local name (and the module docstring's "the lane
#: additionally rejects any result whose messages mention `sorry`"
#: framing) while removing the duplicate implementation.
_sorry_tainted = witness_sorry_tainted


def _witness_sound(result: Mapping[str, Any]) -> bool:
    """Fail-closed witness acceptance. Delegates ENTIRELY to
    :func:`server.kat.witness_ok`, which now folds in the sorry-taint
    scan itself — so ``kat.witness_ok`` and ``skeptic._witness_sound``
    are the SAME predicate by construction and cannot drift (the P0 #2
    witness soundness-predicate drift risk). Kept as a named lane-local
    seam for readability and for the equivalence-vector regression
    test."""
    return witness_ok(result)


def parse_search_counterexample(result: Mapping[str, Any]) -> dict[str, Any] | None:
    """Extract a structured counterexample from a falsification-search
    result, or ``None`` when no hit message is present.

    Returns ``{"bindings": {var: value, ...}, "raw": <message text>}``.
    """
    for m in _messages(result):
        text = str(m.get("text", ""))
        if _HIT_RE.search(text) and not _NO_HIT_RE.search(text):
            bindings = {
                var: value
                for var, value in _BINDING_RE.findall(text)
                if var.lower() != "issue"
            }
            return {"bindings": bindings, "raw": text[:2000]}
    return None


def checks_from_proof_task(
    payload: Mapping[str, Any],
) -> tuple[list[LeanCheckSpec], list[CasCheckSpec]]:
    """Parse a ProofTask payload's ``skeptic_checks`` block into specs.

    Malformed blocks raise ``ValueError`` (harness misuse must be loud
    — the same discipline as ``server.kat.load_kat_fixture``).
    """
    block = payload.get("skeptic_checks") or {}
    if not isinstance(block, Mapping):
        raise ValueError("skeptic_checks must be an object")
    lean_specs = [
        LeanCheckSpec(
            name=c["name"],
            kind=c["kind"],
            snippet=c["snippet"],
            imports=tuple(c.get("imports") or ()),
            description=c.get("description"),
            discharges=c.get("discharges"),
        )
        for c in block.get("lean") or []
    ]
    cas_specs = [
        CasCheckSpec(
            name=c["name"],
            code=c["code"],
            params=dict(c.get("params") or {}),
            timeout_s=float(c.get("timeout_s", 10.0)),
            description=c.get("description"),
            engine=c.get("engine", "sympy"),
            discharges=c.get("discharges"),
        )
        for c in block.get("cas") or []
    ]
    return lean_specs, cas_specs


def _lean_check_record(
    spec: LeanCheckSpec,
    *,
    status: str,
    hit: bool,
    detail: str | None,
    result: Mapping[str, Any] | None,
) -> dict[str, Any]:
    provenance = (result or {}).get("provenance") or {}
    return {
        "lane": "lean",
        "check": spec.name,
        "kind": spec.kind,
        "status": status,
        "hit": hit,
        "detail": detail,
        "snippet": spec.snippet,
        "imports": list(spec.imports),
        "lean_status": (result or {}).get("status"),
        "transcript_sha256": provenance.get("transcript_sha256"),
    }


async def run_skeptic_lane(
    *,
    lean_checks: Sequence[LeanCheckSpec] = (),
    cas_checks: Sequence[CasCheckSpec] = (),
    lean_verify: LeanVerify | None = None,
    cas_on: bool | None = None,
    python_executable: str | None = None,
) -> SkepticLaneResult:
    """Run the counterexample-first pass. Returns on the FIRST hit
    (short-circuit — the whole point is not spending further budget).

    Order: Lean witness checks (kernel-confirmable, soundest), then
    Lean search checks, then CAS checks. ``lean_verify`` is the
    injected async verifier; when ``None`` and Lean checks exist, each
    is recorded ``status: "unavailable"`` and never counted as a hit
    (the lane refuses to guess, mirroring the CAS flag-off refusal).
    ``cas_on`` overrides the ``ARXMCP_ENABLE_SKEPTIC_CAS`` gate
    (callers with a live Config pass ``config.enable_skeptic_cas``).

    ``budget.prover_cycles`` is the literal ``0`` — this lane never
    runs a prover, and the emitted record is the AC-D.10 accounting
    that the refutation cost no proof-search budget.
    """
    started_at = datetime.now(UTC).isoformat()
    t0 = time.monotonic()
    checks: list[dict[str, Any]] = []
    counterexample: dict[str, Any] | None = None
    lean_queries = 0
    cas_runs = 0
    cas_refused = False

    ordered_lean = [c for c in lean_checks if c.kind == "witness"] + [
        c for c in lean_checks if c.kind == "search"
    ]

    for spec in ordered_lean:
        if lean_verify is None:
            checks.append(
                _lean_check_record(
                    spec,
                    status="unavailable",
                    hit=False,
                    detail="no Lean verifier wired; check not run",
                    result=None,
                )
            )
            continue
        result = await lean_verify(spec.snippet, list(spec.imports))
        lean_queries += 1
        if spec.kind == "witness":
            if _witness_sound(result):
                # THE KERNEL decides refutation linkage (durable P1
                # kernel-decides fix). When the author declared a
                # discharged proposition, ask the kernel — in a fresh env —
                # whether the witness's declaration proves it:
                # `example : <discharges.proposition> := @<witness_decl>`.
                # The recorded boolean `proves_declared_proposition` is
                # what the choke-point (`refutation_statement_linked`)
                # requires True; it REPLACES the pretty-print string
                # compare that let a witness of the TRUE `∃ x : ℝ, x*x=2`
                # pass as a declared FALSE `∃ x : ℚ, x*x=2` (Lean elides
                # the ∃-binder type so both render identically) — a live
                # CRITICAL false-accept. Fail-closed: no declaration, no
                # queryable decl name (anonymous example / unicode), a
                # type-check error, or a verifier miss all leave it False.
                # The extra REPL round-trip is counted in the lane budget.
                proved_stmt = kernel_statement_for_snippet(
                    spec.snippet, result.get("kernel_statements")
                )
                proves_declared = False
                if spec.discharges is not None and lean_verify is not None:
                    declared_prop = spec.discharges.get("proposition")
                    decls = extract_decl_names(spec.snippet)
                    if (
                        isinstance(declared_prop, str)
                        and declared_prop.strip()
                        and decls
                    ):
                        check_snippet = kernel_check_snippet(
                            spec.snippet, declared_prop, decls[0]
                        )
                        check_result = await lean_verify(
                            check_snippet, list(spec.imports)
                        )
                        lean_queries += 1
                        proves_declared = kernel_decides_linked(check_result)
                counterexample = {
                    "source": "lean-witness",
                    "check": spec.name,
                    "kernel_confirmed": True,
                    "witness": {"snippet": spec.snippet, "imports": list(spec.imports)},
                    "description": spec.description
                    or f"kernel-accepted refutation witness ({spec.name})",
                    # KERNEL-reported proved proposition — AUDIT/DISPLAY
                    # only now (the elaborated type `#check @<name>`).
                    "proved_statement_lean": proved_stmt,
                    # THE linkage DECISION: did the kernel accept
                    # `example : <declared proposition> := @<witness_decl>`?
                    # (`refutation_statement_linked` requires this True.)
                    "proves_declared_proposition": proves_declared,
                    "discharges": (
                        dict(spec.discharges) if spec.discharges is not None else None
                    ),
                }
                checks.append(
                    _lean_check_record(
                        spec, status="witness-accepted", hit=True, detail=None, result=result
                    )
                )
                break
            if result.get("status") == "ok":
                # Kernel said ok but the soundness gate denied (flags,
                # failed audit, sorry-taint): fail-closed — a refutation
                # must never rest on an unsound witness.
                checks.append(
                    _lean_check_record(
                        spec,
                        status="witness-unsound",
                        hit=False,
                        detail=(
                            "kernel accepted but the witness failed the "
                            "soundness gate (flags/audit/sorry-taint); not "
                            "counted as a refutation"
                        ),
                        result=result,
                    )
                )
            else:
                checks.append(
                    _lean_check_record(
                        spec,
                        status="witness-rejected",
                        hit=False,
                        detail=f"witness snippet did not verify (status={result.get('status')!r})",
                        result=result,
                    )
                )
        else:  # search
            hit = parse_search_counterexample(result)
            if hit is not None:
                counterexample = {
                    "source": "lean-search",
                    "check": spec.name,
                    "kernel_confirmed": False,
                    "witness": hit,
                    "description": spec.description
                    or f"falsification search found a counterexample ({spec.name})",
                }
                checks.append(
                    _lean_check_record(
                        spec, status="counterexample-found", hit=True, detail=None, result=result
                    )
                )
                break
            if result.get("status") in ("timeout", "unavailable", "error") and not any(
                _NO_HIT_RE.search(str(m.get("text", ""))) for m in _messages(result)
            ):
                checks.append(
                    _lean_check_record(
                        spec,
                        status="inconclusive",
                        hit=False,
                        detail=f"search did not complete (status={result.get('status')!r})",
                        result=result,
                    )
                )
            else:
                checks.append(
                    _lean_check_record(
                        spec,
                        status="no-counterexample",
                        hit=False,
                        detail=None,
                        result=result,
                    )
                )

    if counterexample is None:
        for spec in cas_checks:
            env = run_cas_check(
                spec, enabled=cas_on, python_executable=python_executable
            )
            record = {"lane": "cas", "hit": False, **env}
            if env["status"] == "disabled":
                cas_refused = True
                checks.append(record)
                continue
            cas_runs += 1
            if env["status"] == "ok" and env["found"]:
                record["hit"] = True
                counterexample = {
                    "source": "cas-sympy",
                    "check": spec.name,
                    "kernel_confirmed": False,
                    "witness": env["witness"],
                    "description": spec.description
                    or f"CAS scan found a counterexample ({spec.name})",
                    # CAS is evaluation-checked (NOT kernel-checked): no
                    # declaration for the kernel to inhabit, so the
                    # kernel-linkage half fails closed (kernel_confirmed
                    # False AND proves_declared_proposition False). The
                    # choke-point caps/escalates the refuted (findings:
                    # search-kind + CAS-sympy unlinked refutation).
                    "proved_statement_lean": None,
                    "proves_declared_proposition": False,
                    "discharges": (
                        dict(spec.discharges) if spec.discharges is not None else None
                    ),
                }
                checks.append(record)
                break
            checks.append(record)

    verdict = "refuted" if counterexample is not None else "passed"
    lane_result = SkepticLaneResult(
        verdict=verdict,
        counterexample=counterexample,
        checks=checks,
        cas_refused=cas_refused,
        budget={
            "wall_clock_s": time.monotonic() - t0,
            "lean_queries": lean_queries,
            "cas_runs": cas_runs,
            # The counterexample-first contract, as data (AC-D.10).
            "prover_cycles": 0,
        },
        started_at=started_at,
        finished_at=datetime.now(UTC).isoformat(),
    )
    if verdict == "refuted":
        logger.info(
            "skeptic lane: REFUTED by %s (%s) after %d lean quer%s + %d CAS run%s",
            counterexample["source"],
            counterexample["check"],
            lean_queries,
            "y" if lean_queries == 1 else "ies",
            cas_runs,
            "" if cas_runs == 1 else "s",
        )
    return lane_result


__all__ = [
    "LEAN_CHECK_KINDS",
    "LeanCheckSpec",
    "LeanVerify",
    "SkepticLaneResult",
    "checks_from_proof_task",
    "parse_search_counterexample",
    "run_skeptic_lane",
]
