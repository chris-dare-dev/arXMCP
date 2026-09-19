"""Skeptic-lane unit tests (stage2/arx-d3 — WS-D D-5; AC-D.10 offline
half). Fake Lean verifiers; real CAS subprocesses.

Pins: witness hits are fail-closed (soundness gate + sorry-taint scan),
search hits parse the live-probed Plausible message shape, a CAS hit on
a known-false statement terminates the lane `refuted`, the flag-off CAS
refusal never fabricates evidence, the lane can never emit a proven-*
verdict, and a lane refutation composes into a schema-valid
EvidenceBundle whose budget proves zero prover cycles.
"""

from __future__ import annotations

import asyncio
import textwrap

import pytest

from server.kat import witness_ok, witness_sorry_tainted
from server.proving.contracts import (
    EVIDENCE_BUNDLE_ARTIFACT,
    EVIDENCE_BUNDLE_VERSION,
    load_example,
    validate_evidence_bundle,
    wrap_payload,
)
from server.proving.skeptic import (
    LeanCheckSpec,
    _witness_sound,
    checks_from_proof_task,
    parse_search_counterexample,
    run_skeptic_lane,
)
from server.proving.sympy_runner import CAS_ENABLE_ENV_VAR, CasCheckSpec

# ---------------------------------------------------------------------------
# Fake lean_verify envelopes (shape = the hardened D-2 result contract)
# ---------------------------------------------------------------------------


def _sound_ok(**overrides) -> dict:
    base = {
        "status": "ok",
        "mode": "full",
        "compilation_success": True,
        "messages": [],
        "sorry_goals": [],
        "goals_remaining": [],
        "soundness": {
            "guard": "passed",
            "flags": [],
            "audit_status": "skipped",
            "audit_detail": "no auditable theorem/lemma declarations found in snippet",
            "axiom_closure": None,
            "axiom_closure_ok": None,
        },
        "provenance": {
            "lean_toolchain": "leanprover/lean4:v4.30.0-rc2",
            "mathlib_rev": "5450b53e5ddc",
            "transcript_sha256": "ab" * 32,
        },
    }
    base.update(overrides)
    return base


def _error_with(text: str) -> dict:
    return _sound_ok(
        status="error",
        compilation_success=False,
        messages=[
            {"severity": "error", "position": {"line": 1, "column": 0}, "text": text}
        ],
    )


#: The live-probed Plausible hit message (mathlib v4.30.0-rc2 REPL).
_PLAUSIBLE_HIT = (
    "===================\n"
    "Found a counter-example!\n"
    "n := 44\n"
    "issue: ⋯ does not hold\n"
    "(0 shrinks)\n"
    "-------------------"
)

#: The live-probed Plausible no-hit shape: NO error, NO sorries row —
#: only an info + a `declaration uses `sorry`` warning, so the
#: normalized envelope is status "ok" / compilation_success true.
def _plausible_admission() -> dict:
    return _sound_ok(
        messages=[
            {
                "severity": "info",
                "position": {"line": 1, "column": 37},
                "text": "Unable to find a counter-example",
            },
            {
                "severity": "warning",
                "position": {"line": 1, "column": 0},
                "text": "declaration uses `sorry`",
            },
        ]
    )


class _FakeVerifier:
    """Returns queued envelopes; records every call."""

    def __init__(self, *envelopes: dict) -> None:
        self.envelopes = list(envelopes)
        self.calls: list[tuple[str, list[str]]] = []

    async def __call__(self, snippet: str, imports: list[str]) -> dict:
        self.calls.append((snippet, imports))
        return self.envelopes.pop(0)


def _witness(name="w1", snippet="example : ¬ P := by norm_num") -> LeanCheckSpec:
    return LeanCheckSpec(name=name, kind="witness", snippet=snippet)


def _search(name="s1", snippet="example : P := by plausible") -> LeanCheckSpec:
    return LeanCheckSpec(name=name, kind="search", snippet=snippet)


def _run(coro):
    return asyncio.run(coro)


_TRIAL_DIVISION_CODE = textwrap.dedent(
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


@pytest.fixture(autouse=True)
def _flag_unset(monkeypatch):
    monkeypatch.delenv(CAS_ENABLE_ENV_VAR, raising=False)


# ---------------------------------------------------------------------------
# Lean witness kind
# ---------------------------------------------------------------------------


class TestWitnessKind:
    def test_sound_witness_refutes_and_short_circuits(self):
        verifier = _FakeVerifier(_sound_ok())
        lane = _run(
            run_skeptic_lane(
                lean_checks=[_witness(), _witness(name="w2-never-runs")],
                lean_verify=verifier,
            )
        )
        assert lane.verdict == "refuted"
        assert lane.counterexample["source"] == "lean-witness"
        assert lane.counterexample["kernel_confirmed"] is True
        assert len(verifier.calls) == 1, "short-circuit: w2 must not run"
        assert lane.budget == {
            "wall_clock_s": pytest.approx(lane.budget["wall_clock_s"]),
            "lean_queries": 1,
            "cas_runs": 0,
            "prover_cycles": 0,
        }
        assert lane.checks[0]["status"] == "witness-accepted"
        assert lane.checks[0]["transcript_sha256"] == "ab" * 32

    def test_rejected_witness_does_not_refute(self):
        verifier = _FakeVerifier(_error_with("unsolved goals"))
        lane = _run(
            run_skeptic_lane(lean_checks=[_witness()], lean_verify=verifier)
        )
        assert lane.verdict == "passed"
        assert lane.checks[0]["status"] == "witness-rejected"

    def test_unsound_flag_denies_witness(self):
        """native_decide-flagged kernel 'ok' is NOT a refutation
        witness — fail-closed on the refutation side too."""
        env = _sound_ok()
        env["soundness"]["flags"] = ["native_decide"]
        verifier = _FakeVerifier(env)
        lane = _run(
            run_skeptic_lane(lean_checks=[_witness()], lean_verify=verifier)
        )
        assert lane.verdict == "passed"
        assert lane.checks[0]["status"] == "witness-unsound"

    def test_failed_audit_denies_witness(self):
        env = _sound_ok()
        env["soundness"]["axiom_closure_ok"] = False
        verifier = _FakeVerifier(env)
        lane = _run(
            run_skeptic_lane(lean_checks=[_witness()], lean_verify=verifier)
        )
        assert lane.verdict == "passed"
        assert lane.checks[0]["status"] == "witness-unsound"

    def test_sorry_tainted_ok_denies_witness(self):
        """THE load-bearing hole (probed live): a plausible-admitted
        anonymous example normalizes to status 'ok' with only a
        `declaration uses \\`sorry\\`` warning, and the anonymous decl
        evades the axiom audit — witness_ok alone would accept it. The
        lane's sorry-taint scan must deny."""
        verifier = _FakeVerifier(_plausible_admission())
        lane = _run(
            run_skeptic_lane(
                lean_checks=[_witness(snippet="example : P := by plausible")],
                lean_verify=verifier,
            )
        )
        assert lane.verdict == "passed"
        assert lane.checks[0]["status"] == "witness-unsound"
        assert "sorry" in lane.checks[0]["detail"]

    def test_no_verifier_means_unavailable_never_hit(self):
        lane = _run(run_skeptic_lane(lean_checks=[_witness()], lean_verify=None))
        assert lane.verdict == "passed"
        assert lane.checks[0]["status"] == "unavailable"
        assert lane.budget["lean_queries"] == 0


# ---------------------------------------------------------------------------
# Lean search kind (plausible / slim_check)
# ---------------------------------------------------------------------------


class TestSearchKind:
    def test_hit_message_refutes_not_kernel_confirmed(self):
        verifier = _FakeVerifier(_error_with(_PLAUSIBLE_HIT))
        lane = _run(
            run_skeptic_lane(lean_checks=[_search()], lean_verify=verifier)
        )
        assert lane.verdict == "refuted"
        cx = lane.counterexample
        assert cx["source"] == "lean-search"
        assert cx["kernel_confirmed"] is False
        assert cx["witness"]["bindings"] == {"n": "44"}
        assert "counter-example" in cx["witness"]["raw"].lower()

    def test_no_hit_passes(self):
        verifier = _FakeVerifier(_plausible_admission())
        lane = _run(
            run_skeptic_lane(lean_checks=[_search()], lean_verify=verifier)
        )
        assert lane.verdict == "passed"
        assert lane.checks[0]["status"] == "no-counterexample"

    def test_timeout_is_inconclusive_not_refuted(self):
        env = _sound_ok(status="timeout", compilation_success=False)
        verifier = _FakeVerifier(env)
        lane = _run(
            run_skeptic_lane(lean_checks=[_search()], lean_verify=verifier)
        )
        assert lane.verdict == "passed"
        assert lane.checks[0]["status"] == "inconclusive"

    def test_parse_ignores_issue_line_and_no_hit_text(self):
        assert parse_search_counterexample(_plausible_admission()) is None
        hit = parse_search_counterexample(_error_with(_PLAUSIBLE_HIT))
        assert hit["bindings"] == {"n": "44"}

    def test_witness_checks_run_before_search_checks(self):
        """Order pin: kernel-confirmable witnesses first, regardless of
        the caller's list order."""
        verifier = _FakeVerifier(_error_with("no"), _error_with(_PLAUSIBLE_HIT))
        lane = _run(
            run_skeptic_lane(
                lean_checks=[_search(name="search-1"), _witness(name="witness-1")],
                lean_verify=verifier,
            )
        )
        assert [c["check"] for c in lane.checks] == ["witness-1", "search-1"]
        assert lane.verdict == "refuted"


# ---------------------------------------------------------------------------
# CAS sub-lane
# ---------------------------------------------------------------------------


class TestCasLane:
    def test_known_false_statement_produces_refuted(self):
        """The mandated end-to-end unit: a known-false statement
        (n² + n + 41 prime ∀n) run through the enabled CAS lane yields
        verdict `refuted` with the witness n = 40."""
        spec = CasCheckSpec(
            name="n2n41",
            code=_TRIAL_DIVISION_CODE,
            params={"start": 0, "stop": 200},
            timeout_s=30.0,
        )
        lane = _run(run_skeptic_lane(cas_checks=[spec], cas_on=True))
        assert lane.verdict == "refuted"
        assert lane.counterexample == {
            "source": "cas-sympy",
            "check": "n2n41",
            "kernel_confirmed": False,
            "witness": {"n": 40},
            "description": lane.counterexample["description"],
            # Round-3 linkage fields the lane records: a CAS hit is
            # evaluation-checked (no kernel declaration to inhabit), so the
            # kernel-linkage half fails closed — kernel_confirmed False AND
            # proves_declared_proposition False — and this spec declared no
            # `discharges`. The orchestrator choke-point caps such a
            # refutation; the lane itself still reports the raw hit.
            "proved_statement_lean": None,
            "proves_declared_proposition": False,
            "discharges": None,
        }
        assert lane.budget["cas_runs"] == 1
        assert lane.budget["prover_cycles"] == 0
        assert lane.cas_refused is False

    def test_flag_off_lane_refuses_no_fabrication(self):
        """The mandated refusal test at lane level: CAS checks present
        but the gate is off ⇒ recorded refusal, verdict `passed` (never
        a fabricated hit), zero cas_runs."""
        spec = CasCheckSpec(name="n2n41", code=_TRIAL_DIVISION_CODE)
        lane = _run(run_skeptic_lane(cas_checks=[spec]))
        assert lane.verdict == "passed"
        assert lane.cas_refused is True
        assert lane.budget["cas_runs"] == 0
        assert lane.checks[0]["status"] == "disabled"
        assert lane.checks[0]["hit"] is False
        block = lane.to_skeptic_block()
        assert block["cas_refused"] is True
        assert block["refuted"] is False

    def test_cas_runs_after_lean_and_only_if_no_lean_hit(self):
        verifier = _FakeVerifier(_sound_ok())
        spec = CasCheckSpec(name="never-runs", code=_TRIAL_DIVISION_CODE)
        lane = _run(
            run_skeptic_lane(
                lean_checks=[_witness()],
                cas_checks=[spec],
                lean_verify=verifier,
                cas_on=True,
            )
        )
        assert lane.verdict == "refuted"
        assert lane.budget["cas_runs"] == 0
        assert [c["lane"] for c in lane.checks] == ["lean"]

    def test_cas_error_does_not_refute(self):
        spec = CasCheckSpec(
            name="boom",
            code="def find_counterexample():\n    raise RuntimeError('x')\n",
        )
        lane = _run(run_skeptic_lane(cas_checks=[spec], cas_on=True))
        assert lane.verdict == "passed"
        assert lane.checks[0]["status"] == "error"


# ---------------------------------------------------------------------------
# Lane result → EvidenceBundle composition
# ---------------------------------------------------------------------------


class TestEvidenceComposition:
    def _refuted_lane(self):
        spec = CasCheckSpec(
            name="n2n41",
            code=_TRIAL_DIVISION_CODE,
            params={"start": 0, "stop": 200},
            timeout_s=30.0,
        )
        return _run(run_skeptic_lane(cas_checks=[spec], cas_on=True))

    def test_refuted_lane_composes_valid_bundle(self):
        lane = self._refuted_lane()
        example = load_example("evidence-bundle.v0.example.json")
        doc = wrap_payload(
            artifact=EVIDENCE_BUNDLE_ARTIFACT,
            version=EVIDENCE_BUNDLE_VERSION,
            producer="proving-orchestrator-v0",
            produced_at="2026-07-04T02:00:00Z",
            substrate=example["bridge"]["substrate"],
            payload=lane.to_evidence_payload("kat-fm-02-task"),
        )
        validate_evidence_bundle(doc)
        assert doc["payload"]["verdict"] == "refuted"
        assert doc["payload"]["skeptic"]["budget"]["prover_cycles"] == 0
        assert doc["payload"]["cost"]["prover_cycles"] == 0
        # The CAS artifact carries the AC-D.11 replay floor.
        (artifact,) = doc["payload"]["cas"]
        assert artifact["code"] == _TRIAL_DIVISION_CODE
        assert artifact["params"] == {"start": 0, "stop": 200}

    def test_passed_lane_refuses_to_compose_a_verdict(self):
        lane = _run(run_skeptic_lane())
        assert lane.verdict == "passed"
        with pytest.raises(ValueError, match="only valid for a lane refutation"):
            lane.to_evidence_payload("t-1")

    def test_lane_never_emits_proven_verdicts(self):
        refuted = self._refuted_lane()
        passed = _run(run_skeptic_lane())
        for lane in (refuted, passed):
            assert lane.verdict in ("refuted", "passed")


# ---------------------------------------------------------------------------
# ProofTask parsing
# ---------------------------------------------------------------------------


class TestChecksFromProofTask:
    def test_parses_the_committed_example(self):
        payload = load_example("proof-task.v0.example.json")["payload"]
        lean_specs, cas_specs = checks_from_proof_task(payload)
        assert [s.kind for s in lean_specs] == ["witness", "search"]
        assert lean_specs[0].imports == ("Mathlib.Tactic",)
        assert len(cas_specs) == 1
        assert cas_specs[0].params == {"start": 0, "stop": 200}

    def test_missing_block_is_empty(self):
        assert checks_from_proof_task({"task_id": "t"}) == ([], [])

    def test_bad_kind_is_loud(self):
        with pytest.raises(ValueError, match="kind"):
            checks_from_proof_task(
                {
                    "skeptic_checks": {
                        "lean": [{"name": "x", "kind": "decide", "snippet": "s"}]
                    }
                }
            )

    def test_bad_spec_kind_rejected_at_construction(self):
        with pytest.raises(ValueError):
            LeanCheckSpec(name="x", kind="vibes", snippet="s")

    def test_parses_discharges_declaration(self):
        """v0.3 refutation statement-linkage: the witness's `discharges`
        declaration flows through into the LeanCheckSpec."""
        lean_specs, _ = checks_from_proof_task(
            {
                "skeptic_checks": {
                    "lean": [
                        {
                            "name": "w",
                            "kind": "witness",
                            "snippet": "example : ¬ P := by decide",
                            "discharges": {
                                "proposition": "¬ P",
                                "refutes_claim": True,
                            },
                        }
                    ]
                }
            }
        )
        assert lean_specs[0].discharges == {
            "proposition": "¬ P",
            "refutes_claim": True,
        }

    def test_missing_discharges_is_none(self):
        lean_specs, _ = checks_from_proof_task(
            {
                "skeptic_checks": {
                    "lean": [
                        {"name": "w", "kind": "witness", "snippet": "example : X := by z"}
                    ]
                }
            }
        )
        assert lean_specs[0].discharges is None


# ---------------------------------------------------------------------------
# P0 #2: witness soundness-predicate drift — the two predicates are ONE
# ---------------------------------------------------------------------------


class TestWitnessSoundnessPredicateUnified:
    """kat.witness_ok and skeptic._witness_sound must not diverge (P0 #2).
    Round 3 folds the sorry-taint scan into witness_ok and makes
    _witness_sound delegate to it, so they are the SAME predicate by
    construction. This vector table asserts equivalence over the exact
    envelope shapes both predicates classify — a belt-and-suspenders
    regression guard against a future edit re-forking them."""

    @staticmethod
    def _sound_full() -> dict:
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
                "audited_decls": ["t"],
                "axiom_closure": ["propext"],
                "axiom_closure_ok": True,
            },
        }

    def _vectors(self) -> list[dict]:
        base = self._sound_full
        vs: list[dict] = [base()]
        # status / mode / compilation mutations
        vs.append({**base(), "status": "error", "compilation_success": False})
        vs.append({**base(), "mode": "syntax_only"})
        vs.append({**base(), "compilation_success": None})
        # soundness mutations
        for key, val in (
            ("guard", "rejected"),
            ("flags", ["native_decide"]),
            ("flags", ["unsafe"]),
            ("axiom_closure_ok", False),
        ):
            v = base()
            v["soundness"] = {**v["soundness"], key: val}
            vs.append(v)
        # anonymous-example acceptable (audit skipped, not failed)
        v = base()
        v["soundness"] = {
            **v["soundness"],
            "audit_status": "skipped",
            "audited_decls": [],
            "axiom_closure": None,
            "axiom_closure_ok": None,
        }
        vs.append(v)
        # sorry-taint via each of the three signals
        vs.append({**base(), "status": "sorry"})
        vs.append({**base(), "sorry_goals": [{"goal": "P"}]})
        vs.append(
            {
                **base(),
                "messages": [
                    {"severity": "warning", "text": "declaration uses `sorry`"}
                ],
            }
        )
        # empty / malformed
        vs.append({})
        vs.append({"status": "ok"})
        return vs

    def test_witness_ok_and_witness_sound_agree_on_every_vector(self):
        for i, v in enumerate(self._vectors()):
            assert witness_ok(v) == _witness_sound(v), (
                f"vector #{i} diverged: witness_ok={witness_ok(v)} "
                f"_witness_sound={_witness_sound(v)} for {v}"
            )

    def test_sorry_taint_folded_into_witness_ok(self):
        """A kernel-clean-but-sorry-tainted envelope is denied by
        witness_ok itself (round 3 fold), not only by the lane wrapper."""
        tainted = {
            **self._sound_full(),
            "messages": [{"severity": "warning", "text": "declaration uses `sorry`"}],
        }
        assert witness_sorry_tainted(tainted) is True
        assert witness_ok(tainted) is False
        assert _witness_sound(tainted) is False
