"""D-6 proving orchestrator v0 unit tests (stage2/arx-d3 — WS-D;
AC-D.8/AC-D.12/AC-D.13/AC-D.14/AC-D.15 offline half). Fake Lean
verifiers throughout.

Pins: **abstained is the structural default** (a task with no
evidence earns nothing); the D-5 skeptic lane runs FIRST and a hit
short-circuits with ``prover_cycles: 0`` in the bundle's own budget
accounting (AC-D.10); field-tiered lane defaults come from
``lane_config.json`` — configuration, not prose — in lockstep with the
proof-task schema's ``field_lane`` enum, and the selected plan is
inspectable in every bundle (AC-D.14); budget exhaustion maps to
``abstained`` with partial evidence, never the highest verdict reached
(AC-D.15); conflicting evidence forces ``abstained`` + ``escalated``
(AC-D.12, the seeded-misformalization case); the engine can never sign
the D-3 checkbox (source-scan tripwire + the publishable award path
refuses unsigned records); and every exit path emits a schema-valid
EvidenceBundle (AC-D.13).
"""

from __future__ import annotations

import asyncio
import json
import re
import textwrap

import pytest

from server.proving import orchestrator as orch
from server.proving.contracts import (
    PROOF_TASK_ARTIFACT,
    PROOF_TASK_VERSION,
    ContractValidationError,
    load_example,
    load_schema,
    validate_evidence_bundle,
    wrap_payload,
)
from server.proving.faithfulness import (
    BWD_NAME,
    FWD_NAME,
    BackTranslationRecord,
    FormalizationRecord,
    SkepticDiffRecord,
    normalize_lean,
    record_human_signoff,
)
from server.proving.orchestrator import (
    BudgetLedger,
    LaneConfigError,
    ProofAttempt,
    RoleOutputs,
    apply_lane_ceiling,
    context_pack_sha256,
    context_pack_violations,
    detect_evidence_conflict,
    lane_plan_for,
    load_lane_config,
    make_publishable_bundle,
    run_kat_controls,
    run_proving_pipeline,
)


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fixtures: fake hardened envelopes + tasks + role outputs
# ---------------------------------------------------------------------------

_PROP_A = "∀ m n : Nat, Even m → Even n → Even (m + n)"
_PROP_B = "∀ a b : Nat, a % 2 = 0 → b % 2 = 0 → (a + b) % 2 = 0"

_ATTEMPT_SNIPPET = (
    "theorem d6_main : ∀ m n : Nat, Even m → Even n → Even (m + n) := by\n"
    "  intro m n hm hn; exact Even.add hm hn"
)
# The kernel-reported type `#check @d6_main` would report for the winning
# attempt — equals formalization A, so the proof-side statement link holds.
_ATTEMPT_KERNEL_STMT = "∀ m n : Nat, Even m → Even n → Even (m + n)"
# Durable P1 named-declaration contract: a linkage-bearing witness MUST be
# a NAMED theorem so its kernel type is queryable (an anonymous `example`
# yields no `kernel_statements` entry -> linkage fails closed). Migrated
# from the former anonymous `example : ¬ Nat.Prime (40 ^ 2 + 40 + 41)`.
_WITNESS_SNIPPET = (
    "theorem n2n41_witness : ¬ Nat.Prime (40 ^ 2 + 40 + 41) := by norm_num"
)
_WITNESS_KERNEL_STMT = "¬ Nat.Prime (40 ^ 2 + 40 + 41)"
_SEARCH_SNIPPET = "example : ∀ n : Nat, Nat.Prime (n ^ 2 + n + 41) := by plausible"


def _award_env(
    decl: str = "d6_main",
    *,
    kernel_statement: str | None = _ATTEMPT_KERNEL_STMT,
) -> dict:
    """Fake D-2 hardened envelope that passes ``formal_award_ok``.

    Durable P1 soundness fix: carries ``kernel_statements`` mapping the
    audited decl to the KERNEL-reported proved type (default: the
    attempt's type, which equals formalization A so the proof-side
    statement link holds). Equivalence-obligation envelopes (FWD/BWD)
    pass their own decl and a benign type — they are not linkage-checked.
    """
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
        "kernel_statements": (
            {decl: kernel_statement} if kernel_statement is not None else {}
        ),
        "provenance": {
            "lean_toolchain": "leanprover/lean4:v4.30.0-rc2",
            "mathlib_rev": "5450b53e5ddc",
            "transcript_sha256": "ab" * 32,
        },
    }


def _witness_env(
    kernel_statements: dict[str, str] | None = None,
) -> dict:
    """Fake envelope that passes ``server.kat.witness_ok``.

    Durable P1 named-declaration contract: a linkage-bearing witness is a
    NAMED theorem, so the envelope carries a ``kernel_statements`` entry
    for it (default: the migrated ``n2n41_witness`` proving
    ``¬ Nat.Prime (40 ^ 2 + 40 + 41)``). Pass ``kernel_statements`` to
    model a different named witness; pass ``{}`` to model an anonymous
    ``example`` (no queryable name -> linkage fails closed). ``audit_status``
    stays ``ok`` with an empty ``audited_decls`` (the axiom audit and the
    statement audit are independent — witness_ok does not require audited
    decls, and the kernel type is additive linkage evidence)."""
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
            "audited_decls": [],
            "axiom_closure": [],
            "axiom_closure_ok": True,
        },
        "kernel_statements": (
            dict(kernel_statements)
            if kernel_statements is not None
            else {"n2n41_witness": _WITNESS_KERNEL_STMT}
        ),
        "provenance": {
            "lean_toolchain": "leanprover/lean4:v4.30.0-rc2",
            "mathlib_rev": "5450b53e5ddc",
            "transcript_sha256": "cd" * 32,
        },
    }


def _reject_env() -> dict:
    return {
        "status": "error",
        "mode": "full",
        "compilation_success": False,
        "messages": [{"severity": "error", "text": "unsolved goals"}],
        "soundness": {
            "guard": "passed",
            "flags": [],
            "audit_status": "rejected",
            "audited_decls": [],
            "axiom_closure": None,
            "axiom_closure_ok": False,
        },
        "provenance": {
            "lean_toolchain": None,
            "mathlib_rev": None,
            "transcript_sha256": "ef" * 32,
        },
    }


def _no_hit_search_env() -> dict:
    env = _witness_env()
    env["messages"] = [
        {"severity": "warning", "text": "Unable to find a counter-example"}
    ]
    return env


def _kernel_ok_env() -> dict:
    """A clean `status: ok` envelope for a kernel-check command
    (`example : <target> := @<decl>`) the KERNEL ACCEPTS — the fake's
    stand-in for "the proof/witness proves the target". `kernel_decides_
    linked` reads status+compilation_success, so only those matter here."""
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
            "audited_decls": [],
            "axiom_closure": ["propext", "Classical.choice", "Quot.sound"],
            "axiom_closure_ok": True,
        },
        "kernel_statements": {},
        "provenance": {
            "lean_toolchain": "leanprover/lean4:v4.30.0-rc2",
            "mathlib_rev": "5450b53e5ddc",
            "transcript_sha256": "1a" * 32,
        },
    }


def _kernel_mismatch_env() -> dict:
    """A `status: error` (Type mismatch) envelope for a kernel-check the
    KERNEL REJECTS — the target is not defeq to the decl's type (the ℝ/ℚ
    collision, an unrelated proof, a vacuous binder). `kernel_decides_
    linked` → False → linkage fails closed."""
    return {
        "status": "error",
        "mode": "full",
        "compilation_success": False,
        "messages": [
            {
                "severity": "error",
                "text": "Type mismatch: has type … but is expected to have type …",
            }
        ],
        "sorry_goals": [],
        "soundness": {
            "guard": "passed",
            "flags": [],
            "audit_status": "skipped",
            "audited_decls": [],
            "axiom_closure": None,
            "axiom_closure_ok": None,
        },
        "provenance": {
            "lean_toolchain": "leanprover/lean4:v4.30.0-rc2",
            "mathlib_rev": "5450b53e5ddc",
            "transcript_sha256": "2b" * 32,
        },
    }


#: Kernel-check command shape produced by
#: ``server.lean_soundness.kernel_check_snippet``: the target's ``example``
#: line is the LAST line. Parse ``(target, decl)`` from it.
_KERNEL_CHECK_RE = re.compile(r"example\s*:\s*(?P<target>.+?)\s*:=\s*@(?P<decl>\S+)\s*$")


def _parse_kernel_check(snippet: str) -> tuple[str, str] | None:
    """If ``snippet`` ends with a ``kernel_check_snippet`` line
    ``example : <target> := @<decl>``, return ``(target, decl)``; else
    ``None``. The combined snippet is ``<original>\\nexample : … := @…``,
    so the check line is the last non-empty line."""
    m = _KERNEL_CHECK_RE.search(snippet.rstrip())
    if m is None:
        return None
    return m.group("target"), m.group("decl")


#: Default kernel-modelled real types per decl name — the type the KERNEL
#: would report for each decl the tests declare. A kernel check
#: ``example : <target> := @<decl>`` is ACCEPTED iff ``normalize_lean(
#: target)`` equals this map's entry for ``decl`` (the fake's stand-in for
#: definitional equality; the LIVE gated tests exercise true defeq). Decls
#: absent here have no accepting target -> the check is a mismatch
#: (fail-closed), which is the right default for cheat/phantom decls.
_DEFAULT_DECL_TYPES: dict[str, str] = {
    "d6_main": _PROP_A,
    "d6_fixed": _PROP_A,
    "trailing_thm": _PROP_A,  # never selected (principal is first) but honest
    "n2n41_witness": _WITNESS_KERNEL_STMT,
}


def _make_verifier(
    routes: list[tuple[str, dict]],
    *,
    decl_types: dict[str, str] | None = None,
):
    """Async fake dispatching on snippet substrings; records calls.

    Durable P1 kernel-decides fix: when a call is a KERNEL-CHECK command
    (``example : <target> := @<decl>`` appended by
    ``server.lean_soundness.kernel_check_snippet``), the fake does NOT
    route on substring — it MODELS THE KERNEL: returns
    :func:`_kernel_ok_env` iff ``normalize_lean(target)`` equals the
    decl's registered real type (``decl_types`` overlaid on
    :data:`_DEFAULT_DECL_TYPES`), else :func:`_kernel_mismatch_env`. This
    is what decides the recorded ``proves_formalization`` /
    ``proves_declared_proposition`` booleans the pure linkage functions
    consume. Plain (non-check) snippets route on substring as before.
    """
    calls: list[str] = []
    types = {**_DEFAULT_DECL_TYPES, **(decl_types or {})}

    async def verify(snippet: str, imports: list[str]) -> dict:
        calls.append(snippet)
        check = _parse_kernel_check(snippet)
        if check is not None:
            target, decl = check
            real = types.get(decl)
            if real is not None and normalize_lean(target) == normalize_lean(real):
                return _kernel_ok_env()
            return _kernel_mismatch_env()
        for key, env in routes:
            if key in snippet:
                return env
        raise AssertionError(f"unexpected snippet: {snippet!r}")

    verify.calls = calls
    return verify


def _routes_all_green() -> list[tuple[str, dict]]:
    return [
        ("d6_main", _award_env("d6_main")),
        (FWD_NAME, _award_env(FWD_NAME)),
        (BWD_NAME, _award_env(BWD_NAME)),
        ("Nat.Prime (40", _reject_env()),  # witness of a TRUE claim fails
        ("plausible", _no_hit_search_env()),
    ]


def _task(**payload_over) -> dict:
    example = load_example("proof-task.v0.example.json")
    payload = {
        "task_id": "d6-test-task",
        "statement_latex": (
            "\\forall m, n \\in \\mathbb{N}: 2 \\mid m \\wedge 2 \\mid n "
            "\\Rightarrow 2 \\mid (m + n)"
        ),
        "statement_nl": "The sum of two even natural numbers is even.",
        "field_lane": "math.NT",
        "claim_type": "lemma",
    }
    payload.update(payload_over)
    return wrap_payload(
        artifact=PROOF_TASK_ARTIFACT,
        version=PROOF_TASK_VERSION,
        producer="test-harness",
        produced_at="2026-07-04T00:00:00Z",
        substrate=example["bridge"]["substrate"],
        payload=payload,
    )


def _full_role_outputs(**over) -> RoleOutputs:
    kwargs = {
        "sketch": "Even m and Even n give m = 2a, n = 2b; m + n = 2(a + b).",
        "formalization_a": FormalizationRecord(
            channel="A",
            statement_lean=_PROP_A,
            producer="autoformalizer-a",
            session_id="sess-a",
            imports=("Mathlib.Tactic",),
        ),
        "formalization_b": FormalizationRecord(
            channel="B",
            statement_lean=_PROP_B,
            producer="autoformalizer-b",
            session_id="sess-b",
            imports=("Mathlib.Tactic",),
        ),
        "back_translation": BackTranslationRecord(
            statement_en="If m and n are both even naturals, their sum is even.",
            translator="blind-translator",
            session_id="sess-bt",
            source_channel="A",
            rendered_statement_lean=_PROP_A,
            translator_saw_original=False,
        ),
        "skeptic_diff": SkepticDiffRecord(
            skeptic="statement-skeptic", verdict="match"
        ),
        "attempts": (
            ProofAttempt(
                name="tactician-1",
                snippet=_ATTEMPT_SNIPPET,
                imports=("Mathlib.Tactic",),
            ),
        ),
    }
    kwargs.update(over)
    return RoleOutputs(**kwargs)


_WITNESS_CHECKS = {
    "lean": [
        {
            "name": "n2n41-witness-40",
            "kind": "witness",
            "snippet": _WITNESS_SNIPPET,
            "imports": ["Mathlib.Tactic"],
            # Round-3 statement-linkage declaration: this witness proves
            # ¬Prime(40²+40+41), which is a direct counterexample to the
            # claim "n²+n+41 is prime for all n". The choke-point kernel-
            # checks the witness's proved statement against this
            # proposition before earning a confident `refuted`.
            "discharges": {
                "proposition": "¬ Nat.Prime (40 ^ 2 + 40 + 41)",
                "refutes_claim": True,
                "justification": (
                    "n = 40 is a counterexample: 40²+40+41 = 1681 = 41² is "
                    "composite, so the universal 'n²+n+41 is prime' is false."
                ),
            },
        }
    ]
}


# ---------------------------------------------------------------------------
# Lane config: AC-D.14 as configuration, not prose
# ---------------------------------------------------------------------------


class TestLaneConfig:
    def test_config_loads_and_validates(self):
        config = load_lane_config()
        assert config["config_version"] >= 1
        assert set(config["field_lanes"])

    def test_field_lanes_track_proof_task_schema_enum_lockstep(self):
        schema = load_schema("urn:arxmcp:bridge:proof-task:v0")
        enum = set(
            schema["allOf"][1]["properties"]["payload"]["properties"][
                "field_lane"
            ]["enum"]
        )
        assert set(load_lane_config()["field_lanes"]) == enum

    def test_mandated_field_tier_defaults_pinned(self):
        """The slice-mandated trio, as data: math.NT formal-first;
        math.AG informal-checked ceiling; math-ph CAS/numerics-first."""
        lanes = load_lane_config()["field_lanes"]
        nt = lanes["math.NT"]
        assert nt["lane_order"][1] == "formal", "math.NT must be formal-first"
        assert nt["verdict_ceiling"] == "proven-formal"
        ag = lanes["math.AG"]
        assert ag["verdict_ceiling"] == "proven-informal-checked"
        assert ag["lane_order"].index("informal") < ag["lane_order"].index("formal")
        ph = lanes["math-ph"]
        assert ph["lane_order"][1] == "cas", "math-ph must be CAS/numerics-first"

    def test_every_lane_order_starts_with_skeptic(self):
        """AC-D.10 is a hard contract, not a per-field choice."""
        for name, lane in load_lane_config()["field_lanes"].items():
            assert lane["lane_order"][0] == "skeptic", name

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda c: c["field_lanes"]["math.NT"].update(
                {"lane_order": ["formal", "skeptic"]}
            ),
            lambda c: c["field_lanes"]["math.NT"].update(
                {"verdict_ceiling": "certainly-true"}
            ),
            lambda c: c["field_lanes"]["math.NT"].update(
                {"lane_order": ["skeptic", "vibes"]}
            ),
            lambda c: c["field_lanes"].pop("math.AG"),
            lambda c: c.pop("default_budget"),
        ],
        ids=[
            "skeptic-not-first",
            "unknown-ceiling",
            "unknown-lane",
            "enum-drift",
            "no-default-budget",
        ],
    )
    def test_malformed_config_refuses(self, tmp_path, mutate):
        config = json.loads(
            orch.LANE_CONFIG_PATH.read_text(encoding="utf-8")
        )
        mutate(config)
        bad = tmp_path / "lane_config.json"
        bad.write_text(json.dumps(config), encoding="utf-8")
        with pytest.raises(LaneConfigError):
            load_lane_config(bad)

    def test_unknown_field_lane_falls_back_to_general(self):
        assert lane_plan_for(None)["field_lane"] == "general"
        assert lane_plan_for("math.NT")["field_lane"] == "math.NT"


class TestLaneCeiling:
    def test_ag_ceiling_caps_without_fabricating(self):
        verdict, reasons = apply_lane_ceiling(
            "proven-formal", "proven-informal-checked"
        )
        assert verdict == "plausible-unverified"
        assert any("ceiling" in r for r in reasons)

    def test_within_ceiling_passes_through(self):
        assert apply_lane_ceiling("proven-formal", "proven-formal") == (
            "proven-formal",
            [],
        )
        assert apply_lane_ceiling("abstained", "proven-informal-checked") == (
            "abstained",
            [],
        )

    def test_refuted_is_never_capped(self):
        assert apply_lane_ceiling("refuted", "proven-informal-checked") == (
            "refuted",
            [],
        )


# ---------------------------------------------------------------------------
# Role outputs
# ---------------------------------------------------------------------------


class TestRoleOutputs:
    def test_from_dict_roundtrip(self):
        ro = RoleOutputs.from_dict(
            {
                "sketch": "outline",
                "formalization_a": {
                    "channel": "A",
                    "statement_lean": _PROP_A,
                    "producer": "af-a",
                    "session_id": "s-a",
                    "imports": ["Mathlib.Tactic"],
                },
                "attempts": [
                    {"name": "t1", "snippet": "theorem x : True := trivial"}
                ],
            }
        )
        assert ro.formalization_a.channel == "A"
        assert ro.attempts[0].role == "tactician"

    def test_bad_attempt_role_refuses(self):
        with pytest.raises(ValueError, match="role"):
            ProofAttempt(name="x", snippet="y", role="oracle")

    def test_malformed_record_is_loud(self):
        with pytest.raises((KeyError, ValueError)):
            RoleOutputs.from_dict({"formalization_a": {"channel": "A"}})


# ---------------------------------------------------------------------------
# Context packs
# ---------------------------------------------------------------------------


class TestContextPack:
    def test_valid_pack_no_violations_and_stable_hash(self):
        pack = {
            "definitions": [{"name": "Even", "statement_latex": "2 \\mid n"}],
            "hypotheses": ["n \\in \\mathbb{N}"],
            "sources": [{"paper_id": "2008.12019", "chunk_id": "c-1"}],
        }
        assert context_pack_violations(pack) == []
        assert context_pack_sha256(pack) == context_pack_sha256(dict(pack))

    def test_violations_are_listed(self):
        pack = {"definitions": "not-a-list", "surprise": {}, "hypotheses": [""]}
        violations = context_pack_violations(pack)
        assert any("unknown" in v for v in violations)
        assert any("definitions" in v for v in violations)
        assert any("hypotheses" in v for v in violations)

    def test_none_pack_is_fine(self):
        assert context_pack_violations(None) == []
        assert context_pack_sha256(None) is None


# ---------------------------------------------------------------------------
# The pipeline: abstained-by-default, skeptic-first, award paths
# ---------------------------------------------------------------------------


class TestAbstainedByDefault:
    def test_no_evidence_earns_nothing(self):
        result = _run(
            run_proving_pipeline(
                task=_task(),
                role_outputs=RoleOutputs(),
                lean_verify=_make_verifier([]),
            )
        )
        assert result.verdict == "abstained"
        assert any("structural default" in r for r in result.verdict_reasons)
        assert result.escalated is False
        validate_evidence_bundle(result.bundle)
        payload = result.bundle["payload"]
        assert payload["publishable"] is False
        assert payload["cost"]["prover_cycles"] == 0

    def test_no_verifier_still_emits_valid_abstained_bundle(self):
        result = _run(
            run_proving_pipeline(
                task=_task(skeptic_checks=_WITNESS_CHECKS),
                role_outputs=_full_role_outputs(),
                lean_verify=None,
            )
        )
        assert result.verdict == "abstained"
        validate_evidence_bundle(result.bundle)
        # The unavailable checks are recorded, never counted as hits.
        checks = result.bundle["payload"]["skeptic"]["checks"]
        assert all(c["status"] == "unavailable" for c in checks)


class TestSkepticFirst:
    def test_refutation_short_circuits_before_any_prover_cycle(self):
        """AC-D.10: the hit terminates the run with prover_cycles: 0 in
        the bundle's own budget accounting; the attempts never run."""
        verifier = _make_verifier(
            [("Nat.Prime (40", _witness_env())]  # only the witness route
        )
        result = _run(
            run_proving_pipeline(
                task=_task(
                    skeptic_checks=_WITNESS_CHECKS,
                    known_truth=False,
                    kat_id="kat-fm-02",
                ),
                role_outputs=_full_role_outputs(),
                lean_verify=verifier,
            )
        )
        assert result.verdict == "refuted"
        payload = result.bundle["payload"]
        assert payload["counterexample"]["kernel_confirmed"] is True
        assert payload["counterexample"]["proves_declared_proposition"] is True
        assert payload["skeptic"]["budget"]["prover_cycles"] == 0
        assert payload["cost"]["prover_cycles"] == 0
        assert payload["verdict_confidence"] == "high"
        # The witness snippet + its kernel-check command reached the
        # verifier (durable P1: the extra `example : <declared> := @<decl>`
        # round-trip decides `proves_declared_proposition`); the prover
        # attempts still never ran (short-circuit).
        assert len(verifier.calls) == 2
        assert all("Nat.Prime (40" in c for c in verifier.calls)
        assert _parse_kernel_check(verifier.calls[1]) is not None
        validate_evidence_bundle(result.bundle)

    def test_declared_witness_on_real_task_earns_refuted_but_escalated(self):
        """The positive class-fix case: a FALSE claim on a REAL
        (known_truth=null) task whose witness proves ¬Prime(40²+40+41)
        AND declares it discharges exactly that proposition passes the
        verdict-linkage choke-point (kernel-vs-declaration match +
        refutes_claim=true) and earns a confident `refuted` — the linkage
        requirement does NOT block legitimate refutations, and the
        counterexample is preserved.

        Round-3 adv-2 (refutation semantic-entailment gap): because the
        declared-proposition ⇒ ¬claim entailment is an unverifiable
        attestation pre-formalization and a `refuted` carries NO human
        sign-off gate, a real-task (known_truth=None) `refuted` is now
        ESCALATED for human confirmation. The verdict stays `refuted` and
        the counterexample rides the bundle (signal preserved), but
        escalated=True with the new reason."""
        result = _run(
            run_proving_pipeline(
                task=_task(
                    statement_latex=(
                        "\\forall n \\in \\mathbb{N}: n^2 + n + 41 \\in \\mathbb{P}"
                    ),
                    statement_nl="n² + n + 41 is prime for every natural number n.",
                    known_truth=None,  # a REAL task
                    skeptic_checks=_WITNESS_CHECKS,
                ),
                role_outputs=_full_role_outputs(),
                lean_verify=_make_verifier([("Nat.Prime (40", _witness_env())]),
            )
        )
        assert result.verdict == "refuted", result.verdict_reasons
        assert result.escalated is True  # real-task refuted -> human gate
        assert any(
            "unverifiable attestation" in r for r in result.verdict_reasons
        )
        payload = result.bundle["payload"]
        assert payload["escalated"] is True
        # The counterexample is PRESERVED — escalation gates trust, it does
        # not drop the refutation signal.
        assert payload["counterexample"]["kernel_confirmed"] is True
        assert payload["verdict_confidence"] == "high"
        validate_evidence_bundle(result.bundle)

    def test_lane_selection_recorded_per_field(self):
        """AC-D.14 acceptance grain: one task per field; lane selection
        is inspectable in each bundle."""
        expected = {
            "math.NT": ["skeptic", "formal"],
            "math.AG": ["skeptic", "informal", "formal"],
            "math-ph": ["skeptic", "cas", "formal"],
        }
        for lane_name, order in expected.items():
            result = _run(
                run_proving_pipeline(
                    task=_task(field_lane=lane_name),
                    role_outputs=RoleOutputs(),
                    lean_verify=_make_verifier([]),
                )
            )
            plan = result.bundle["payload"]["provenance"]["lane_plan"]
            assert plan["field_lane"] == lane_name
            assert plan["lane_order"] == order, lane_name
            assert result.bundle["payload"]["provenance"]["lane_trace"][0][
                "lane"
            ] == "skeptic"
            validate_evidence_bundle(result.bundle)


class TestProvenFormalPath:
    def test_full_evidence_earns_proven_formal_unpublished(self):
        result = _run(
            run_proving_pipeline(
                task=_task(),
                role_outputs=_full_role_outputs(),
                lean_verify=_make_verifier(_routes_all_green()),
            )
        )
        assert result.verdict == "proven-formal", result.verdict_reasons
        payload = result.bundle["payload"]
        assert payload["publishable"] is False
        assert payload["faithfulness"]["human_signoff"]["signed"] is False
        assert payload["formal"]["best_attempt"] == "tactician-1"
        assert payload["cost"]["prover_cycles"] == 1
        validate_evidence_bundle(result.bundle)

    def test_missing_faithfulness_element_caps(self):
        """AC-D.5 wired through the pipeline: no back-translation ⇒
        the kernel proof caps at plausible-unverified."""
        result = _run(
            run_proving_pipeline(
                task=_task(),
                role_outputs=_full_role_outputs(back_translation=None),
                lean_verify=_make_verifier(_routes_all_green()),
            )
        )
        assert result.verdict == "plausible-unverified"
        assert any("AC-D.5" in r or "faithfulness" in r for r in result.verdict_reasons)
        validate_evidence_bundle(result.bundle)

    def test_kernel_proof_of_unrelated_statement_never_earns_proven_formal(self):
        """findings #1/#2: the pipeline must NOT award proven-formal when
        the sole attempt's kernel-clean proof is of a statement UNRELATED
        to either gate-checked formalization. Every other element is
        green (faithful A/B pair, back-translation, skeptic match) — only
        the formalization⇔proof link is broken. The publishable path must
        likewise refuse, so no signed publishable proven-formal bundle
        certifying the wrong statement is reachable.
        """
        cheat = ProofAttempt(
            name="cheat-attempt",
            snippet="theorem stage3_cheat : 1 + 1 = 2 := rfl",
            imports=("Mathlib.Tactic",),
        )
        routes = [
            # cheat proof is kernel-clean but proves 1+1=2 — the KERNEL-
            # reported type is "1 + 1 = 2", NEITHER formalization, so the
            # statement link must fail closed (durable P1: the kernel type
            # is authoritative — a cheat cannot claim formalization A's type
            # unless the kernel actually elaborated it).
            ("stage3_cheat", _award_env("stage3_cheat", kernel_statement="1 + 1 = 2")),
            (FWD_NAME, _award_env(FWD_NAME)),  # A⇔B genuinely established
            (BWD_NAME, _award_env(BWD_NAME)),
            ("Nat.Prime (40", _reject_env()),
            ("plausible", _no_hit_search_env()),
        ]
        result = _run(
            run_proving_pipeline(
                task=_task(),  # known_truth is null — a REAL task, not a KAT control
                role_outputs=_full_role_outputs(attempts=(cheat,)),
                lean_verify=_make_verifier(routes),
            )
        )
        # The kernel proof exists and passes formal_award_ok, and the A/B
        # faithfulness record is complete — yet the verdict caps because
        # the proved statement (1 + 1 = 2) is neither formalization.
        assert result.verdict == "plausible-unverified", result.verdict_reasons
        assert result.verdict != "proven-formal"
        assert any("statement linkage" in r for r in result.verdict_reasons)
        payload = result.bundle["payload"]
        assert payload["formal"]["best_statement_lean"] == "1 + 1 = 2"
        validate_evidence_bundle(result.bundle)

        # The publishable path re-derives linkage independently and must
        # refuse even with a (test-supplied) operator signature.
        signed = record_human_signoff(
            payload["faithfulness"],
            by="test-operator",
            i_am_a_human_operator=True,
        )
        with pytest.raises(ValueError, match="not 'proven-formal'"):
            make_publishable_bundle(result.bundle, signed)

    def test_fixer_attempt_runs_after_tactician_failure(self):
        # The winning (fixer) attempt must prove a gate-checked
        # formalization (_PROP_A) for the statement-linkage award to hold
        # (findings #1/#2) — a fixer that proves an unrelated placeholder
        # caps at plausible-unverified, which is a separate test below.
        routes = [
            ("d6_broken", _reject_env()),
            ("d6_fixed", _award_env("d6_fixed")),
            (FWD_NAME, _award_env(FWD_NAME)),
            (BWD_NAME, _award_env(BWD_NAME)),
        ]
        attempts = (
            ProofAttempt(
                name="t1",
                snippet=f"theorem d6_broken : {_PROP_A} := by sorry",
            ),
            ProofAttempt(
                name="f1",
                snippet=(
                    f"theorem d6_fixed : {_PROP_A} := by\n"
                    "  intro m n hm hn; exact Even.add hm hn"
                ),
                role="fixer",
            ),
        )
        result = _run(
            run_proving_pipeline(
                task=_task(),
                role_outputs=_full_role_outputs(attempts=attempts),
                lean_verify=_make_verifier(routes),
            )
        )
        assert result.verdict == "proven-formal", result.verdict_reasons
        payload = result.bundle["payload"]
        assert payload["formal"]["best_attempt"] == "f1"
        assert payload["cost"]["prover_cycles"] == 2
        attempts_out = payload["formal"]["attempts"]
        assert [a["award_ok"] for a in attempts_out] == [False, True]
        # The awarded statement is linked back to formalization A.
        assert payload["formal"]["best_statement_lean"] == _PROP_A

    def test_ag_ceiling_caps_formal_award_in_pipeline(self):
        """math.AG informal-checked ceiling: even a full formal award
        never surfaces as proven-formal (leakage/misformalization
        posture, lane_config.json)."""
        result = _run(
            run_proving_pipeline(
                task=_task(field_lane="math.AG"),
                role_outputs=_full_role_outputs(),
                lean_verify=_make_verifier(_routes_all_green()),
            )
        )
        assert result.verdict == "plausible-unverified"
        assert any("ceiling" in r for r in result.verdict_reasons)
        validate_evidence_bundle(result.bundle)


class TestCasLane:
    _CAS_CHECKS = {
        "cas": [
            {
                "name": "no-cx-scan",
                "code": (
                    "def find_counterexample(start, stop):\n"
                    "    return None\n"
                ),
                "params": {"start": 0, "stop": 4},
                "timeout_s": 30,
            }
        ]
    }

    def test_math_ph_completed_scan_earns_numeric_support_only(self):
        """A completed no-hit CAS scan in a cas-lane plan earns
        plausible-unverified — numeric support, never a proof."""
        result = _run(
            run_proving_pipeline(
                task=_task(field_lane="math-ph", skeptic_checks=self._CAS_CHECKS),
                role_outputs=RoleOutputs(),
                lean_verify=_make_verifier([]),
                cas_on=True,
            )
        )
        assert result.verdict == "plausible-unverified"
        assert any("never a proof" in r for r in result.verdict_reasons)
        artifacts = result.bundle["payload"]["cas"]
        assert artifacts and artifacts[0]["status"] == "ok"
        assert artifacts[0]["found"] is False
        validate_evidence_bundle(result.bundle)

    def test_refused_cas_earns_nothing(self):
        """Flag off ⇒ the runner refuses; a refused check is recorded
        evidence of refusal, not numeric support."""
        result = _run(
            run_proving_pipeline(
                task=_task(field_lane="math-ph", skeptic_checks=self._CAS_CHECKS),
                role_outputs=RoleOutputs(),
                lean_verify=_make_verifier([]),
                cas_on=False,
            )
        )
        assert result.verdict == "abstained"
        assert result.bundle["payload"]["skeptic"]["cas_refused"] is True
        validate_evidence_bundle(result.bundle)


class TestBudgetExhaustion:
    def test_exhaustion_maps_to_abstained_never_highest_reached(self):
        """AC-D.15: the formal award was already earned when the gate
        ran out of budget — the verdict must be abstained with the
        partial evidence attached, NOT plausible-unverified or
        proven-formal."""
        result = _run(
            run_proving_pipeline(
                task=_task(budget={"lean_queries": 1, "wall_clock_s": 600}),
                role_outputs=_full_role_outputs(),
                lean_verify=_make_verifier(_routes_all_green()),
            )
        )
        assert result.verdict == "abstained"
        assert any("budget exhausted" in r for r in result.verdict_reasons)
        assert any("AC-D.15" in r for r in result.verdict_reasons)
        payload = result.bundle["payload"]
        # Best partial evidence attached: the award-ok attempt is there.
        assert payload["formal"]["best_result"] is not None
        assert payload["provenance"]["budget_exhausted"]
        validate_evidence_bundle(result.bundle)

    def test_prover_cycle_ceiling_stops_the_loop(self):
        routes = [("d6_broken", _reject_env())]
        attempts = tuple(
            ProofAttempt(name=f"t{i}", snippet=f"theorem d6_broken{i} : True := sorry")
            for i in range(3)
        )
        # Route on the shared prefix.
        result = _run(
            run_proving_pipeline(
                task=_task(budget={"prover_cycles": 1, "wall_clock_s": 600}),
                role_outputs=_full_role_outputs(attempts=attempts),
                lean_verify=_make_verifier(routes),
            )
        )
        assert result.verdict == "abstained"
        assert result.bundle["payload"]["cost"]["prover_cycles"] == 1
        validate_evidence_bundle(result.bundle)

    def test_wall_clock_exhaustion(self):
        result = _run(
            run_proving_pipeline(
                task=_task(budget={"wall_clock_s": 1e-9}),
                role_outputs=_full_role_outputs(),
                lean_verify=_make_verifier(_routes_all_green()),
            )
        )
        assert result.verdict == "abstained"
        assert any("budget exhausted" in r for r in result.verdict_reasons)
        validate_evidence_bundle(result.bundle)


class TestEvidenceConflict:
    def test_conflict_rule_is_pure_and_loud(self):
        assert detect_evidence_conflict(formal_ok=False, counterexample=None) == []
        assert (
            detect_evidence_conflict(
                formal_ok=True, counterexample=None
            )
            == []
        )
        reasons = detect_evidence_conflict(
            formal_ok=True,
            counterexample={"source": "cas-sympy", "check": "scan-1"},
        )
        assert reasons and "AC-D.12" in reasons[0]

    def test_seeded_misformalization_abstains_and_escalates(self):
        """AC-D.12: the formal statement diverges from the NL claim —
        a prior kernel-accepted proof stands while the skeptic lane
        finds a live counterexample to the claim. The run must abstain
        and escalate, never pick a side silently."""
        verifier = _make_verifier([("Nat.Prime (40", _witness_env())])
        result = _run(
            run_proving_pipeline(
                task=_task(skeptic_checks=_WITNESS_CHECKS),
                role_outputs=_full_role_outputs(),
                lean_verify=verifier,
                prior_formal_result=_award_env("d6_prior"),
            )
        )
        assert result.verdict == "abstained"
        assert result.escalated is True
        assert any("AC-D.12" in r for r in result.verdict_reasons)
        payload = result.bundle["payload"]
        assert payload["escalated"] is True
        assert "counterexample" not in payload  # neither side is endorsed
        # ...but the skeptic evidence trail remains auditable.
        assert payload["skeptic"]["refuted"] is True
        assert payload["formal"]["prior_award_ok"] is True
        validate_evidence_bundle(result.bundle)


class TestKnownTruthDefense:
    def test_proven_on_known_false_task_escalates_in_bundle(self):
        """Defense-in-depth mirror of AC-D.9: if evidence 'proves' a
        control task with established-FALSE truth, the bundle itself
        carries the red flag (the KAT harness escalates the run)."""
        result = _run(
            run_proving_pipeline(
                task=_task(known_truth=False, kat_id="kat-fm-99"),
                role_outputs=_full_role_outputs(),
                lean_verify=_make_verifier(_routes_all_green()),
            )
        )
        assert result.verdict == "proven-formal"
        assert result.escalated is True
        assert any("RED ALARM" in r for r in result.verdict_reasons)
        validate_evidence_bundle(result.bundle)

    def test_proven_on_open_control_escalates_in_bundle(self):
        """Convergence R-OPEN-1: the in-bundle escalation mirror must match
        the KAT harness rule (server/kat.py::evaluate_run), which red-alarms
        a proven-* verdict on BOTH a FALSE-must-reject AND an OPEN-must-abstain
        control. The FALSE arm was covered; this pins the OPEN arm. An OPEN
        control carries known_truth=None WITH control provenance (a kat_id), so
        a proven-* here is a false acceptance the harness flags — the bundle
        must self-escalate. Pre-fix this came out escalated=False."""
        result = _run(
            run_proving_pipeline(
                task=_task(known_truth=None, kat_id="kat-open-99"),
                role_outputs=_full_role_outputs(),
                lean_verify=_make_verifier(_routes_all_green()),
            )
        )
        assert result.verdict == "proven-formal"
        assert result.escalated is True
        assert any(
            "OPEN-must-abstain control" in r for r in result.verdict_reasons
        )
        validate_evidence_bundle(result.bundle)

    def test_proven_on_real_open_task_without_provenance_not_escalated(self):
        """The OPEN-arm escalation must NOT fire on a genuine real task: a
        real proven-formal (known_truth=None, NO kat_id) is the golden path
        and carries its own mandatory human sign-off gate downstream, not an
        escalation. Guards the fix against over-firing on the golden path."""
        result = _run(
            run_proving_pipeline(
                task=_task(known_truth=None),  # no kat_id → not a control
                role_outputs=_full_role_outputs(),
                lean_verify=_make_verifier(_routes_all_green()),
            )
        )
        assert result.verdict == "proven-formal"
        assert result.escalated is False
        assert not any(
            "OPEN-must-abstain control" in r for r in result.verdict_reasons
        )
        validate_evidence_bundle(result.bundle)

    def test_bogus_unrelated_witness_no_declaration_caps_at_choke_point(self):
        """findings: refutation-witness-skips-statement-linkage (the R3
        CLASS fix, stronger than the R2 escalation net). A skeptic-lane
        witness is accepted for its own SOUNDNESS but its RELEVANCE to
        the claim was never checked, so a kernel-clean witness proving an
        UNRELATED true proposition (¬Prime(4)) could confidently refute
        the true 'there are infinitely many primes'. With NO declared
        discharged proposition, the verdict-award choke-point now caps
        the refutation to `abstained` BEFORE it can be emitted as
        `refuted` — the counterexample is dropped, and this holds on a
        REAL (known_truth=null) task where the R2 escalation net was
        inert. This is the primary class-fix behavior."""
        bogus = {
            "lean": [
                {
                    "name": "bogus-unrelated-witness",
                    "kind": "witness",
                    "snippet": "example : ¬ Nat.Prime 4 := by decide",
                    "imports": ["Mathlib.Tactic"],
                    # NO `discharges` declaration — the author never tied
                    # this witness to a refutation obligation for the claim.
                }
            ]
        }
        result = _run(
            run_proving_pipeline(
                task=_task(
                    statement_latex="\\forall N, \\exists p > N: p \\text{ prime}",
                    statement_nl="There are infinitely many primes.",
                    claim_type="theorem",
                    known_truth=None,  # a REAL task — the R2 net does not fire here
                    skeptic_checks=bogus,
                ),
                role_outputs=RoleOutputs(),  # skeptic short-circuits; no attempts
                lean_verify=_make_verifier([("Nat.Prime 4", _witness_env())]),
            )
        )
        assert result.verdict == "abstained", result.verdict_reasons
        assert result.verdict != "refuted"
        assert any("choke-point" in r for r in result.verdict_reasons)
        assert any(
            "declared no discharged proposition" in r
            for r in result.verdict_reasons
        )
        payload = result.bundle["payload"]
        # The capped refutation is dropped — no counterexample rides the
        # bundle for a verdict that is no longer `refuted`.
        assert "counterexample" not in payload
        validate_evidence_bundle(result.bundle)

    def test_refuted_on_known_true_task_escalates_in_bundle(self):
        """R2 escalation net, defense-in-depth BEHIND the R3 choke-point.
        When a witness DOES carry a valid declared+kernel-linked
        discharged proposition (so the choke-point lets the `refuted`
        stand) but the task is a known_truth=True control, the bundle
        still carries the RED ALARM — the mirror of the FALSE-red-alarm
        above. Here the witness legitimately proves ¬Prime(4) AND
        declares it discharges exactly that proposition, so the machine
        linkage passes; the *semantic* lie (that ¬Prime(4) refutes
        'infinitely many primes') is precisely what the escalation net +
        human review backstop — the honest residual the choke-point's
        kernel link cannot catch."""
        declared_but_irrelevant = {
            "lean": [
                {
                    "name": "declared-but-semantically-irrelevant",
                    "kind": "witness",
                    "snippet": "theorem w : ¬ Nat.Prime 4 := by decide",
                    "imports": ["Mathlib.Tactic"],
                    # Machine-valid declaration: the witness DOES prove this
                    # proposition (kernel link passes). The claim that it
                    # refutes 'infinitely many primes' is a recorded,
                    # auditable LIE — caught by the escalation net, not the
                    # kernel link (the documented residual).
                    "discharges": {
                        "proposition": "¬ Nat.Prime 4",
                        "refutes_claim": True,
                        "justification": "(mislabeled — does not entail ¬claim)",
                    },
                }
            ]
        }
        result = _run(
            run_proving_pipeline(
                task=_task(
                    statement_latex="\\forall N, \\exists p > N: p \\text{ prime}",
                    statement_nl="There are infinitely many primes.",
                    claim_type="theorem",
                    known_truth=True,
                    kat_id="kat-tf-99",
                    skeptic_checks=declared_but_irrelevant,
                ),
                role_outputs=RoleOutputs(),  # skeptic short-circuits; no attempts
                lean_verify=_make_verifier(
                    [("Nat.Prime 4", _witness_env({"w": "¬ Nat.Prime 4"}))],
                    # The witness `theorem w : ¬ Nat.Prime 4` genuinely
                    # proves its declared proposition, so the KERNEL check
                    # `example : ¬ Nat.Prime 4 := @w` ACCEPTS (kernel
                    # linkage passes). The LIE is the entailment to ¬claim
                    # — caught by the known_truth=true escalation net, not
                    # the kernel link (the documented residual).
                    decl_types={"w": "¬ Nat.Prime 4"},
                ),
            )
        )
        assert result.verdict == "refuted", result.verdict_reasons
        assert result.escalated is True
        assert any("RED ALARM" in r for r in result.verdict_reasons)
        assert any("known_truth=true" in r for r in result.verdict_reasons)
        payload = result.bundle["payload"]
        assert payload["escalated"] is True
        validate_evidence_bundle(result.bundle)


class TestRealTaskRefutationEscalation:
    """Round-3 adv-2 (findings: refutation semantic-entailment gap on real
    known_truth=null tasks). The choke-point machine-checks witness ->
    declared-proposition (kernel) but NEVER declared-proposition -> ¬claim;
    that entailment is the UNVERIFIABLE author attestation
    `discharges.refutes_claim=true`, uncheckable pre-formalization
    (AC-D.10). The only prior backstop — the `known_truth is True`
    escalation — is INERT on real tasks (the schema pins known_truth=null),
    and a `refuted` ships with NO human sign-off gate (unlike a proven-
    formal). So a real-task `refuted` is now ESCALATED for human
    confirmation, mirroring the proof-side gate. The verdict stays
    `refuted` and the counterexample is preserved (signal preserved, trust
    gated). This keys on known_truth is None — KAT controls and the
    golden-path FALSE control (known_truth True/False) are UNCHANGED."""

    def test_real_task_kernel_linked_refuted_is_escalated(self):
        """(a) A real task (known_truth=None) reaching `refuted` via a
        kernel-linked witness comes out escalated=True with the new
        reason, verdict still `refuted`, counterexample preserved."""
        result = _run(
            run_proving_pipeline(
                task=_task(
                    statement_latex=(
                        "\\forall n \\in \\mathbb{N}: n^2 + n + 41 \\in \\mathbb{P}"
                    ),
                    statement_nl="n² + n + 41 is prime for every natural number n.",
                    known_truth=None,  # a REAL task
                    skeptic_checks=_WITNESS_CHECKS,
                ),
                role_outputs=RoleOutputs(),
                lean_verify=_make_verifier([("Nat.Prime (40", _witness_env())]),
            )
        )
        assert result.verdict == "refuted", result.verdict_reasons
        assert result.escalated is True
        assert any(
            "unverifiable attestation" in r for r in result.verdict_reasons
        )
        assert any(
            "no sign-off gate" in r for r in result.verdict_reasons
        )
        payload = result.bundle["payload"]
        assert payload["escalated"] is True
        assert payload["counterexample"]["kernel_confirmed"] is True
        validate_evidence_bundle(result.bundle)

    def test_kat_false_control_refute_retains_prefix_escalation_behavior(self):
        """(b) A KAT FALSE control (known_truth=False) that refutes retains
        its EXISTING (pre-fix) escalation behavior — asserted explicitly so
        a future change to the escalation net cannot silently alter the
        controls. A FALSE control that refutes is the EXPECTED outcome
        (not a soundness alarm), so it is NOT escalated: the round-3 adv-2
        real-task escalation keys on known_truth is None and MUST NOT fire
        on a known_truth=False control. (The `2+2=4` witness here proves
        exactly its declared proposition — kernel linkage passes — so the
        refutation stands; the FALSE truth means no red alarm.)"""
        bogus_aux = {
            "lean": [
                {
                    "name": "aux-2plus2",
                    "kind": "witness",
                    "snippet": "theorem t : 2 + 2 = 4 := by norm_num",
                    "imports": ["Mathlib.Tactic"],
                    "discharges": {
                        "proposition": "2 + 2 = 4",
                        "refutes_claim": True,
                        "justification": "(control fixture)",
                    },
                }
            ]
        }
        result = _run(
            run_proving_pipeline(
                task=_task(
                    task_id="kat-false-control-refute",
                    statement_latex="A false control claim.",
                    statement_nl="A false control claim.",
                    known_truth=False,  # a FALSE control, NOT a real task
                    kat_id="kat-fc-99",
                    skeptic_checks=bogus_aux,
                ),
                role_outputs=RoleOutputs(),
                lean_verify=_make_verifier(
                    [("2 + 2 = 4", _witness_env({"t": "2 + 2 = 4"}))],
                    # `theorem t : 2 + 2 = 4` genuinely proves its declared
                    # proposition -> the KERNEL check accepts (kernel
                    # linkage passes); the FALSE control means no red alarm.
                    decl_types={"t": "2 + 2 = 4"},
                ),
            )
        )
        assert result.verdict == "refuted", result.verdict_reasons
        # UNCHANGED pre-fix behavior: a FALSE control refute is the
        # expected outcome — not escalated, no real-task reason.
        assert result.escalated is False
        assert not any(
            "unverifiable attestation" in r for r in result.verdict_reasons
        )
        payload = result.bundle["payload"]
        assert payload["escalated"] is False
        validate_evidence_bundle(result.bundle)

    def test_bogus_aux_fact_on_real_task_is_escalated_not_silent(self):
        """(c) THE live false-refute: a kernel-valid witness of a TRUE
        auxiliary fact (`theorem t : 2+2=4 := by norm_num`) with
        discharges.proposition="2 + 2 = 4" + refutes_claim=true on a REAL
        (known_truth=None) task. Kernel linkage passes (the kernel really
        proves 2+2=4, which matches the declaration), so before adv-2 this
        emitted a silent, confident `refuted`/high for an ARBITRARY claim.
        Now it comes out ESCALATED — the required human gate over the
        unverifiable declared⇒¬claim entailment. The verdict stays
        `refuted` (signal preserved) but is no longer silent."""
        bogus_aux = {
            "lean": [
                {
                    "name": "aux-2plus2",
                    "kind": "witness",
                    "snippet": "theorem t : 2 + 2 = 4 := by norm_num",
                    "imports": ["Mathlib.Tactic"],
                    # An HONEST refutes_claim=true on a witness that proves a
                    # true auxiliary fact — the kernel link passes; only the
                    # (unverifiable) entailment to ¬claim is the gap, so the
                    # escalation gate is the backstop.
                    "discharges": {
                        "proposition": "2 + 2 = 4",
                        "refutes_claim": True,
                        "justification": "(does not actually entail ¬claim)",
                    },
                }
            ]
        }
        result = _run(
            run_proving_pipeline(
                task=_task(
                    task_id="adv-bogus-aux-real",
                    statement_latex="Some arbitrary true claim on a real task.",
                    statement_nl="Some arbitrary true claim on a real task.",
                    known_truth=None,  # a REAL task — R2 net inert
                    skeptic_checks=bogus_aux,
                ),
                role_outputs=RoleOutputs(),
                lean_verify=_make_verifier(
                    [("2 + 2 = 4", _witness_env({"t": "2 + 2 = 4"}))],
                    # `theorem t : 2 + 2 = 4` genuinely proves its declared
                    # proposition -> the KERNEL check accepts (kernel
                    # linkage passes); only the (unverifiable) entailment to
                    # ¬claim is the gap, so the real-task escalation gate is
                    # the backstop.
                    decl_types={"t": "2 + 2 = 4"},
                ),
            )
        )
        assert result.verdict == "refuted", result.verdict_reasons
        assert result.escalated is True  # no longer a silent confident refuted
        assert any(
            "unverifiable attestation" in r for r in result.verdict_reasons
        )
        payload = result.bundle["payload"]
        assert payload["escalated"] is True
        assert payload["counterexample"]["kernel_confirmed"] is True
        validate_evidence_bundle(result.bundle)

    def test_known_truth_false_without_kat_id_cannot_suppress_escalation(self):
        """(d) THE known-truth-escalation-bypass regression (CRITICAL).

        The round-2 escalation net keyed the "a refuted needs no human
        gate" carve-out on ``known_truth is False`` — but ``known_truth``
        is UNTRUSTED task payload and the schema only ADVISES real tasks to
        leave it null. So an author who cannot actually refute a TRUE claim
        earned a CONFIDENT (verdict_confidence high), UN-escalated
        ``refuted`` by adding one schema-valid field, ``known_truth: false``,
        masquerading their real task as a FALSE control — silently disabling
        the sole backstop for the acknowledged declared⇒¬claim entailment
        residual. This is the exact round-2 threat model (a kernel-sound
        witness of an unrelated true fact "refuting" a true theorem)
        re-opened.

        Identical bogus-aux witness and TRUE claim as case (c), but the
        task sets ``known_truth=False`` with NO ``kat_id``. The
        control-provenance gate treats a non-null ``known_truth`` WITHOUT a
        ``kat_id`` marker as a real task, so the mandatory real-task
        refutation escalation still fires. Pre-fix this asserted
        escalated=False (the bypass); post-fix it MUST be escalated=True.
        Verdict stays ``refuted`` (signal preserved, trust gated)."""
        bogus_aux = {
            "lean": [
                {
                    "name": "aux-2plus2",
                    "kind": "witness",
                    "snippet": "theorem t : 2 + 2 = 4 := by norm_num",
                    "imports": ["Mathlib.Tactic"],
                    # Kernel-sound witness of a TRUE but claim-IRRELEVANT
                    # fact; refutes_claim=true is a bare (never-machine-
                    # checked) attestation — the entailment gap the
                    # escalation gate exists to backstop.
                    "discharges": {
                        "proposition": "2 + 2 = 4",
                        "refutes_claim": True,
                        "justification": "(does not actually entail ¬claim)",
                    },
                }
            ]
        }
        result = _run(
            run_proving_pipeline(
                task=_task(
                    task_id="adv-known-truth-false-masquerade",
                    # A TRUE claim the author cannot actually refute.
                    statement_latex="There are infinitely many prime numbers.",
                    statement_nl="There are infinitely many prime numbers.",
                    known_truth=False,  # author masquerade — but NO kat_id
                    skeptic_checks=bogus_aux,
                ),
                role_outputs=RoleOutputs(),
                lean_verify=_make_verifier(
                    [("2 + 2 = 4", _witness_env({"t": "2 + 2 = 4"}))],
                    decl_types={"t": "2 + 2 = 4"},
                ),
            )
        )
        assert result.verdict == "refuted", result.verdict_reasons
        # THE FIX: a non-null known_truth with NO control provenance
        # (kat_id) cannot suppress the real-task refutation escalation.
        assert result.escalated is True, result.verdict_reasons
        assert any(
            "unverifiable attestation" in r for r in result.verdict_reasons
        )
        assert any("no sign-off gate" in r for r in result.verdict_reasons)
        payload = result.bundle["payload"]
        assert payload["escalated"] is True
        # Signal preserved — the counterexample still rides the bundle.
        assert payload["counterexample"]["kernel_confirmed"] is True
        validate_evidence_bundle(result.bundle)


# Trial-division CAS code producing the n=40 counterexample to
# "n²+n+41 is prime for all n" — used to drive a REAL CAS hit end-to-end
# (the sandboxed SymPy subprocess runs offline; it needs no Lean).
_CAS_TRIAL_DIVISION = textwrap.dedent(
    """\
    def _is_prime(k):
        if k < 2:
            return False
        d = 2
        while d * d <= k:
            if k % d == 0:
                return False
            d += 1
        return True

    def find_counterexample(start, stop):
        for n in range(start, stop):
            if not _is_prime(n * n + n + 41):
                return {"n": n}
        return None
    """
)


class TestRefutationLinkageChokePointEndToEnd:
    """ROUND-3 CLASS FIX, end-to-end through ``run_proving_pipeline`` (the
    production CLI path). The refutation-side choke-point now requires a
    kernel-confirmed, declared-and-kernel-checked linkage from EVERY
    source; the ``lean-search`` "linked by construction" carve-out and
    the ``cas-sympy`` "declaration is the only linkage" carve-out — the
    surviving siblings of the round-1/2 witness holes — are closed. All
    of these run on REAL tasks (``known_truth=None``), where the round-2
    escalation net is inert, so the choke-point is the ONLY thing that
    can stop the false refutation.
    """

    def test_search_unrelated_snippet_caps_at_choke_point(self):
        """findings: search-kind unlinked refutation (CRITICAL). An
        author-supplied ``search`` snippet asserting an UNRELATED
        proposition (∀ n, n < 3) that ``plausible`` refutes used to yield
        a confident, unescalated ``refuted`` for the TRUE claim "there are
        infinitely many primes" — the choke-point passed it through as
        linked-by-construction. Now: a search hit is
        ``kernel_confirmed=False`` and carries no kernel-proved statement,
        so it fails the kernel-linkage half and is capped to ``abstained``
        BEFORE it can be emitted as ``refuted``; the unsupported
        counterexample is dropped from the bundle."""
        plausible_hit = {
            "status": "error",
            "mode": "full",
            "compilation_success": False,
            "messages": [
                {
                    "severity": "error",
                    "text": "Found a counter-example!\nn := 5\nissue: n < 3\n",
                }
            ],
            "provenance": {"transcript_sha256": "cd" * 32},
        }
        bogus_search = {
            "lean": [
                {
                    "name": "bogus-search-unrelated",
                    "kind": "search",
                    # NOT the claim — an unrelated proposition plausible
                    # trivially refutes. search kind ignored `discharges`
                    # anyway (was linked-by-construction).
                    "snippet": "example : ∀ n : Nat, n < 3 := by plausible",
                    "imports": ["Mathlib.Tactic"],
                }
            ]
        }
        result = _run(
            run_proving_pipeline(
                task=_task(
                    task_id="adv-infinitude-primes",
                    statement_latex="There are infinitely many prime numbers.",
                    statement_nl="There are infinitely many prime numbers.",
                    known_truth=None,  # a REAL task — the R2 net is inert
                    skeptic_checks=bogus_search,
                ),
                role_outputs=RoleOutputs(),  # skeptic short-circuits
                lean_verify=_make_verifier([("plausible", plausible_hit)]),
            )
        )
        assert result.verdict == "abstained", result.verdict_reasons
        assert result.verdict != "refuted"
        assert any("choke-point" in r for r in result.verdict_reasons)
        payload = result.bundle["payload"]
        # The capped refutation is dropped — no counterexample rides a
        # bundle whose verdict is no longer `refuted`.
        assert "counterexample" not in payload
        # The skeptic trail remains auditable (the raw hit is still there).
        assert payload["skeptic"]["refuted"] is True
        validate_evidence_bundle(result.bundle)

    def test_cas_unrelated_declaration_caps_at_choke_point(self):
        """findings: CAS-sympy unlinked refutation (MAJOR). A real CAS hit
        (n=40 to "n²+n+41 prime ∀n") carrying a self-consistent
        ``discharges`` declaration used to earn a confident, unescalated
        ``refuted`` on the strength of the author's declaration alone —
        the author supplies BOTH the code and the declaration. Here the
        CAS hit is planted against an UNRELATED true claim, so the
        declaration is claim-irrelevant. Now: a CAS hit is
        ``kernel_confirmed=False`` (evaluation-checked, no kernel
        statement), so it fails the kernel-linkage half and is capped to
        ``abstained`` regardless of the declaration."""
        bogus_cas = {
            "cas": [
                {
                    "name": "bogus-unrelated-cas",
                    "code": _CAS_TRIAL_DIVISION,
                    "params": {"start": 0, "stop": 200},
                    "timeout_s": 30,
                    # A self-consistent declaration that has NOTHING to do
                    # with the claim under test — the author's word, which
                    # the choke-point no longer trusts without a kernel tie.
                    "discharges": {
                        "proposition": "∃ n, ¬ Nat.Prime (n ^ 2 + n + 41)",
                        "refutes_claim": True,
                        "justification": "(irrelevant to the claim below)",
                    },
                }
            ]
        }
        result = _run(
            run_proving_pipeline(
                task=_task(
                    task_id="adv-cas-unrelated",
                    statement_latex="There are infinitely many prime numbers.",
                    statement_nl="There are infinitely many prime numbers.",
                    field_lane="math-ph",
                    known_truth=None,  # a REAL task — the R2 net is inert
                    skeptic_checks=bogus_cas,
                ),
                role_outputs=RoleOutputs(),
                lean_verify=_make_verifier([]),
                cas_on=True,  # run the real sandboxed SymPy subprocess
            )
        )
        assert result.verdict == "abstained", result.verdict_reasons
        assert result.verdict != "refuted"
        assert any("choke-point" in r for r in result.verdict_reasons)
        assert any("not kernel-confirmed" in r for r in result.verdict_reasons)
        payload = result.bundle["payload"]
        assert "counterexample" not in payload
        # The CAS artifact (the raw hit) is still recorded for audit.
        assert payload["skeptic"]["refuted"] is True
        assert any(c.get("hit") for c in payload.get("cas", []))
        validate_evidence_bundle(result.bundle)

    def test_kernel_witness_refutation_still_stands(self):
        """No-regression twin: the LEGITIMATE refutation path is not
        over-capped by the linkage class fix. A kernel-confirmed witness
        that proves ¬Prime(40²+40+41) AND declares it discharges exactly
        that proposition still earns a confident ``refuted`` (kernel
        linkage passes) with the counterexample preserved — the class fix
        does NOT drop real refutations.

        Round-3 adv-2: on a REAL task (known_truth=None) that `refuted` is
        additionally ESCALATED (the unverifiable declared⇒¬claim
        entailment + no sign-off gate). The verdict stays `refuted`; only
        the human gate is added. (The gated FALSE-refute golden path is
        known_truth=False, a control — it stays UNCHANGED / unescalated.)"""
        result = _run(
            run_proving_pipeline(
                task=_task(
                    statement_latex=(
                        "\\forall n \\in \\mathbb{N}: n^2 + n + 41 \\in \\mathbb{P}"
                    ),
                    statement_nl="n² + n + 41 is prime for every natural number n.",
                    known_truth=None,  # a REAL task
                    skeptic_checks=_WITNESS_CHECKS,
                ),
                role_outputs=RoleOutputs(),
                lean_verify=_make_verifier([("Nat.Prime (40", _witness_env())]),
            )
        )
        assert result.verdict == "refuted", result.verdict_reasons
        assert result.escalated is True  # real-task refuted -> human gate
        assert any(
            "unverifiable attestation" in r for r in result.verdict_reasons
        )
        payload = result.bundle["payload"]
        assert payload["counterexample"]["kernel_confirmed"] is True
        assert payload["counterexample"]["source"] == "lean-witness"
        validate_evidence_bundle(result.bundle)


class TestKernelReportedLinkageAdversarial:
    """Durable P1 soundness fix — the NEW adversarial vectors the retired
    text-scanner could not handle but the KERNEL-reported linkage does.
    Each runs end-to-end through ``run_proving_pipeline``; the envelope's
    ``kernel_statements`` reflects the KERNEL's honest view (a phantom in
    a comment/string is OMITTED because ``#check @<it>`` errors; a
    multi-decl map reports each decl's OWN type), and the pipeline must
    NOT grant a mismatched linkage. All on REAL tasks (known_truth=None)
    so only the linkage — not the escalation net — can stop the grant.
    """

    def _refutation_task(self, checks):
        return _task(
            task_id="adv-p1-kernel-linkage",
            statement_latex="Some arbitrary TRUE claim on a real task.",
            statement_nl="Some arbitrary TRUE claim on a real task.",
            known_truth=None,
            skeptic_checks=checks,
        )

    # (a) unicode-identifier decl — no ASCII name to key the kernel map.
    def test_unicode_identifier_witness_caps_at_choke_point(self):
        """A witness declared with a UNICODE name (`theorem αβ : …`) is
        not name-extractable (ASCII-only regex), so no kernel statement is
        selectable -> the refutation linkage fails closed -> capped. The
        text-scanner would have parsed the unicode decl's source type."""
        checks = {
            "lean": [
                {
                    "name": "unicode-witness",
                    "kind": "witness",
                    "snippet": "theorem αβ : ¬ Nat.Prime 4 := by decide",
                    "imports": ["Mathlib.Tactic"],
                    "discharges": {
                        "proposition": "¬Nat.Prime 4",
                        "refutes_claim": True,
                        "justification": "(unrelated to the claim anyway)",
                    },
                }
            ]
        }
        # The kernel DID accept the theorem and could report αβ's type, but
        # the selector cannot extract the unicode name from the snippet, so
        # proved_statement_lean is None -> kernel link fails closed.
        env = _witness_env({"αβ": "¬Nat.Prime 4"})
        result = _run(
            run_proving_pipeline(
                task=self._refutation_task(checks),
                role_outputs=RoleOutputs(),
                lean_verify=_make_verifier([("Nat.Prime 4", env)]),
            )
        )
        assert result.verdict == "abstained", result.verdict_reasons
        assert result.verdict != "refuted"
        assert any("choke-point" in r for r in result.verdict_reasons)
        assert "counterexample" not in result.bundle["payload"]
        validate_evidence_bundle(result.bundle)

    # (b) `theorem` inside a STRING literal — phantom invisible to kernel.
    def test_string_literal_phantom_proof_caps_below_proven_formal(self):
        """A proof attempt whose snippet hides a phantom
        `theorem <phantom> : <formalization_A>` inside a STRING literal on
        a real decl proving 1+1=2. The kernel elaborates only the real
        decl; `#check @<phantom>` errors, so it is OMITTED from
        kernel_statements. The selector keys on the real decl's name and
        gets its true kernel type (1 + 1 = 2), NEITHER formalization ->
        the proof caps at plausible-unverified. The text-scanner would
        have matched the phantom `theorem` text inside the string and
        linked the wrong (formalization-A) statement."""
        phantom = _PROP_A.replace('"', "")  # keep it string-safe
        cheat = ProofAttempt(
            name="stringlit-cheat",
            snippet=(
                f'def blurb : String := "theorem ph : {phantom} := by sorry"\n'
                "theorem stringlit_cheat : 1 + 1 = 2 := rfl"
            ),
            imports=("Mathlib.Tactic",),
        )
        # The kernel map (as the real handler builds it) carries ONLY the
        # real theorem's type; `ph` (in the string) never elaborates, so it
        # is absent. Even if an attacker forged a `ph` entry equal to
        # formalization A, the selector keys on the FIRST theorem/lemma name
        # in the snippet — `stringlit_cheat` — not `ph`.
        routes = [
            (
                "stringlit_cheat",
                _award_env("stringlit_cheat", kernel_statement="1 + 1 = 2"),
            ),
            (FWD_NAME, _award_env(FWD_NAME)),
            (BWD_NAME, _award_env(BWD_NAME)),
            ("Nat.Prime (40", _reject_env()),
            ("plausible", _no_hit_search_env()),
        ]
        result = _run(
            run_proving_pipeline(
                task=_task(),  # real task; formalizations A/B faithful
                role_outputs=_full_role_outputs(attempts=(cheat,)),
                lean_verify=_make_verifier(routes),
            )
        )
        assert result.verdict == "plausible-unverified", result.verdict_reasons
        assert result.verdict != "proven-formal"
        assert any("statement linkage" in r for r in result.verdict_reasons)
        # The recorded proved statement is the REAL decl's kernel type.
        assert result.bundle["payload"]["formal"]["best_statement_lean"] == "1 + 1 = 2"
        validate_evidence_bundle(result.bundle)

    # (c) multi-declaration — trailing decl differs from the principal.
    def test_multi_decl_trailing_statement_not_substitutable(self):
        """A proof whose snippet has the principal decl proving 1+1=2 and a
        TRAILING decl proving formalization A. The kernel reports each
        decl's OWN type; the selector keys on the FIRST decl, so the
        trailing decl's (matching) statement cannot be substituted to earn
        the grant -> caps at plausible-unverified. The text-scanner also
        took the first decl, but the kernel report additionally guarantees
        the reported type is what the kernel ACTUALLY elaborated for that
        name (no source-vs-kernel divergence)."""
        cheat = ProofAttempt(
            name="multidecl-cheat",
            snippet=(
                "theorem principal_thm : 1 + 1 = 2 := rfl\n"
                f"theorem trailing_thm : {_PROP_A} := by\n"
                "  intro m n hm hn; exact Even.add hm hn"
            ),
            imports=("Mathlib.Tactic",),
        )
        # Honest per-decl kernel map: principal proves 1+1=2 (unrelated),
        # trailing proves formalization A. The selector picks the FIRST.
        env = _award_env("principal_thm", kernel_statement="1 + 1 = 2")
        env["kernel_statements"] = {
            "principal_thm": "1 + 1 = 2",
            "trailing_thm": _PROP_A,
        }
        env["soundness"]["audited_decls"] = ["principal_thm", "trailing_thm"]
        routes = [
            ("principal_thm", env),
            (FWD_NAME, _award_env(FWD_NAME)),
            (BWD_NAME, _award_env(BWD_NAME)),
            ("Nat.Prime (40", _reject_env()),
            ("plausible", _no_hit_search_env()),
        ]
        result = _run(
            run_proving_pipeline(
                task=_task(),
                role_outputs=_full_role_outputs(attempts=(cheat,)),
                lean_verify=_make_verifier(routes),
            )
        )
        assert result.verdict == "plausible-unverified", result.verdict_reasons
        assert result.verdict != "proven-formal"
        assert any("statement linkage" in r for r in result.verdict_reasons)
        assert result.bundle["payload"]["formal"]["best_statement_lean"] == "1 + 1 = 2"
        validate_evidence_bundle(result.bundle)


class TestMalformedInputs:
    def test_malformed_task_refuses_before_any_lane(self):
        verifier = _make_verifier([])
        task = _task()
        del task["payload"]["statement_latex"]
        with pytest.raises(ContractValidationError):
            _run(
                run_proving_pipeline(
                    task=task, role_outputs=RoleOutputs(), lean_verify=verifier
                )
            )
        assert verifier.calls == []


# ---------------------------------------------------------------------------
# KAT controls (AC-D.8 / AC-D.9)
# ---------------------------------------------------------------------------


class TestKatControls:
    def test_controls_resolve_honestly_with_fakes(self, tmp_path):
        async def verify(snippet: str, imports: list[str]) -> dict:
            if "¬" in snippet or "plausible" in snippet:
                return _witness_env()
            return _award_env("kat_ctrl")

        report, block = _run(
            run_kat_controls(
                lean_verify=verify, seed=20260704, artifact_dir=tmp_path
            )
        )
        assert report.reportable is True
        assert len(block["kat_ids_run"]) == 3
        assert 0.0 <= block["abstention_rate"] <= 1.0
        assert block["reportable"] is True
        assert block["kat_run_id"] == report.run_id

    def test_no_verifier_makes_controls_non_reportable(self, tmp_path):
        """Controls cannot be met on faith: with no verifier the
        TRUE-formal positive control fails and the run is
        non-reportable (AC-D.8)."""
        report, block = _run(
            run_kat_controls(
                lean_verify=None, seed=20260704, artifact_dir=tmp_path
            )
        )
        assert report.reportable is False
        assert block["reportable"] is False

    def test_controls_block_rides_the_bundle(self):
        controls = {
            "kat_run_id": "kat-test",
            "kat_ids_run": ["kat-tf-05", "kat-fm-02", "kat-op-01"],
            "abstention_rate": 1 / 3,
            "reportable": True,
        }
        result = _run(
            run_proving_pipeline(
                task=_task(),
                role_outputs=RoleOutputs(),
                lean_verify=_make_verifier([]),
                controls=controls,
            )
        )
        assert result.bundle["payload"]["controls"] == controls
        validate_evidence_bundle(result.bundle)


# ---------------------------------------------------------------------------
# The sign-off lockout + the publishable award path
# ---------------------------------------------------------------------------


class TestSignoffLockout:
    def test_engine_sources_never_touch_the_signer(self):
        """Grep-able tripwire (binding rule in server/proving/README.md):
        neither the engine nor the pipeline driver may reference
        record_human_signoff — only the operator surface does."""
        from pathlib import Path

        import tools.prove_task as prove_task_mod

        for mod in (orch, prove_task_mod):
            source = Path(mod.__file__).read_text(encoding="utf-8")
            # The one permitted mention is inside docstrings/comments;
            # a *call or import* would appear as the bare token —
            # assert the strict absence of both forms.
            assert "from server.proving.faithfulness import record_human_signoff" not in source
            assert "record_human_signoff(" not in source

    def _proven_bundle(self):
        return _run(
            run_proving_pipeline(
                task=_task(),
                role_outputs=_full_role_outputs(),
                lean_verify=_make_verifier(_routes_all_green()),
            )
        ).bundle

    def test_unsigned_block_cannot_publish(self):
        bundle = self._proven_bundle()
        with pytest.raises(ValueError, match="not 'proven-formal'"):
            make_publishable_bundle(bundle, bundle["payload"]["faithfulness"])

    def test_operator_signoff_roundtrip(self):
        bundle = self._proven_bundle()
        signed = record_human_signoff(
            bundle["payload"]["faithfulness"],
            by="Chris Dare",
            note="reviewed statement, closure, and back-translation",
            i_am_a_human_operator=True,
        )
        published = make_publishable_bundle(bundle, signed)
        payload = published["payload"]
        assert payload["publishable"] is True
        assert payload["verdict"] == "proven-formal"
        assert payload["faithfulness"]["human_signoff"]["signed"] is True
        validate_evidence_bundle(published)
        # The original pipeline bundle is untouched (pure assembly).
        assert bundle["payload"]["publishable"] is False

    def test_sign_bundle_cli_roundtrip(self, tmp_path):
        """The operator surface end-to-end: pipeline bundle on disk →
        tools.sign_bundle → schema-valid publishable bundle."""
        import tools.sign_bundle as sign_bundle_mod

        bundle_path = tmp_path / "bundle.json"
        bundle_path.write_text(
            json.dumps(self._proven_bundle(), ensure_ascii=False),
            encoding="utf-8",
        )
        out_path = tmp_path / "bundle.published.json"
        rc = sign_bundle_mod.main(
            [
                "--bundle",
                str(bundle_path),
                "--by",
                "Chris Dare",
                "--out",
                str(out_path),
                "--i-am-a-human-operator",
            ]
        )
        assert rc == 0
        published = json.loads(out_path.read_text(encoding="utf-8"))
        assert published["payload"]["publishable"] is True
        validate_evidence_bundle(published)

    def test_sign_bundle_cli_refuses_without_attestation_flag(self, tmp_path):
        import tools.sign_bundle as sign_bundle_mod

        bundle_path = tmp_path / "bundle.json"
        bundle_path.write_text(
            json.dumps(self._proven_bundle(), ensure_ascii=False),
            encoding="utf-8",
        )
        rc = sign_bundle_mod.main(
            [
                "--bundle",
                str(bundle_path),
                "--by",
                "automation",
                "--out",
                str(tmp_path / "nope.json"),
            ]
        )
        assert rc == 2
        assert not (tmp_path / "nope.json").exists()


# ---------------------------------------------------------------------------
# The pipeline driver CLI (offline, no Lean env)
# ---------------------------------------------------------------------------


class TestProveTaskCli:
    def test_offline_run_emits_valid_abstained_bundle(self, tmp_path, monkeypatch):
        import tools.prove_task as prove_task_mod

        monkeypatch.delenv("ARXMCP_LAKE_PATH", raising=False)
        monkeypatch.delenv("ARXMCP_LEAN_REPL_DIR", raising=False)
        task_path = tmp_path / "task.json"
        task_path.write_text(json.dumps(_task(), ensure_ascii=False), encoding="utf-8")
        out_path = tmp_path / "bundle.json"
        rc = prove_task_mod.main(
            [
                "--task",
                str(task_path),
                "--out",
                str(out_path),
                "--skip-controls",
            ]
        )
        assert rc == 0
        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        assert bundle["payload"]["verdict"] == "abstained"
        assert bundle["payload"]["publishable"] is False
        validate_evidence_bundle(bundle)

    def test_controls_seed_required_without_skip(self, tmp_path):
        import tools.prove_task as prove_task_mod

        with pytest.raises(SystemExit):
            prove_task_mod.main(
                ["--task", "x.json", "--out", "y.json"]
            )


# ---------------------------------------------------------------------------
# Ledger grain
# ---------------------------------------------------------------------------


class TestBudgetLedger:
    def test_defaults_come_from_lane_config(self):
        ledger = BudgetLedger.from_task({})
        defaults = load_lane_config()["default_budget"]
        assert ledger.limits["lean_queries"] == defaults["lean_queries"]

    def test_declared_budget_overrides(self):
        ledger = BudgetLedger.from_task({"budget": {"lean_queries": 2}})
        ledger.charge_lean_query()
        ledger.charge_lean_query()
        with pytest.raises(orch.BudgetExceeded):
            ledger.charge_lean_query()
        assert ledger.totals()["lean_queries"] == 2
