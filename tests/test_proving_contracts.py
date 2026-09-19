"""ProofTask / EvidenceBundle contract tests (stage2/arx-d3 — WS-D;
AC-D.13 schema half).

Covers: the vendored-envelope byte-pin, Draft-07 validity, committed
examples, the v0.1 stub pins preserved at v0.2 (task_id +
statement_latex; task_id + verdict + the D9 five-verdict enum), the
refuted-requires-counterexample rule (AC-D.7), the AC-D.11 CAS replay
floor, the AC-D.10 skeptic ``prover_cycles: 0`` pin, and the registry
conventions inherited from stage2/arx-c1 (MINOR additive tolerance;
enums as pinned vocabularies).
"""

from __future__ import annotations

import copy
import hashlib
import json

import pytest
from jsonschema import Draft7Validator

from server.kat import VERDICTS
from server.proving import contracts
from server.proving.contracts import (
    EVIDENCE_BUNDLE_ARTIFACT,
    EVIDENCE_BUNDLE_VERSION,
    PROOF_TASK_ARTIFACT,
    PROOF_TASK_VERSION,
    SCHEMAS_DIR,
    ContractValidationError,
    load_example,
    load_schema,
    validate_evidence_bundle,
    validate_proof_task,
    wrap_payload,
)

#: SHA-256 of the vendored envelope schema. MUST stay byte-identical to
#: ``contracts/envelope.v1.schema.json`` on stage2/arx-c1 (the producer
#: copy) so the Stage-2 integration merge is a pure file deletion here
#: — see server/proving/README.md. Recompute ONLY when deliberately
#: re-vendoring from contracts/.
ENVELOPE_SHA256 = "2b8303d0ab114d9f8a5c52958191357ba08c5363067b5e4479c80d20b2d016f2"

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


def _task_doc(**payload_overrides) -> dict:
    payload = {
        "task_id": "t-1",
        "statement_latex": "$1 + 1 = 2$",
        **payload_overrides,
    }
    return wrap_payload(
        artifact=PROOF_TASK_ARTIFACT,
        version=PROOF_TASK_VERSION,
        producer="test",
        produced_at="2026-07-04T00:00:00Z",
        substrate=_SUBSTRATE,
        payload=payload,
    )


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


_COUNTEREXAMPLE = {
    "source": "cas-sympy",
    "check": "n2n41-scan",
    "kernel_confirmed": False,
    "witness": {"n": 40},
    "description": "40^2 + 40 + 41 = 1681 = 41^2",
}


class TestVendoredEnvelope:
    def test_envelope_byte_pin_matches_arx_c1(self):
        """The vendored envelope is byte-identical to the arx-c1
        producer copy (integration deletes this file; drift would make
        the two branches validate different documents)."""
        raw = (SCHEMAS_DIR / "envelope.v1.schema.json").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == ENVELOPE_SHA256

    def test_missing_substrate_pin_rejected(self):
        doc = _task_doc()
        del doc["bridge"]["substrate"]["tool_schema_sha256"]
        with pytest.raises(ContractValidationError):
            validate_proof_task(doc)

    def test_retrieval_mode_d8_pin(self):
        doc = _task_doc()
        doc["bridge"]["substrate"]["retrieval_mode"] = "hybrid"
        with pytest.raises(ContractValidationError):
            validate_proof_task(doc)


class TestSchemaValidity:
    @pytest.mark.parametrize(
        "schema_id",
        sorted(contracts._SCHEMA_FILES),
    )
    def test_schemas_are_valid_draft7(self, schema_id):
        Draft7Validator.check_schema(load_schema(schema_id))

    def test_examples_validate(self):
        validate_proof_task(load_example("proof-task.v0.example.json"))
        validate_evidence_bundle(load_example("evidence-bundle.v0.example.json"))

    def test_examples_carry_authored_versions(self):
        task = load_example("proof-task.v0.example.json")
        bundle = load_example("evidence-bundle.v0.example.json")
        # proof-task bumped to 0.3 at stage3/proving-r3 (additive
        # `discharges` refutation-linkage field); evidence-bundle unchanged.
        assert task["bridge"]["version"] == PROOF_TASK_VERSION == "0.3"
        assert bundle["bridge"]["version"] == EVIDENCE_BUNDLE_VERSION == "0.2"


class TestProofTaskPins:
    def test_valid_minimal_task(self):
        validate_proof_task(_task_doc())

    @pytest.mark.parametrize("missing", ["task_id", "statement_latex"])
    def test_v01_stub_identity_core_preserved(self, missing):
        """The arx-c1 v0.1 stub pins survive the v0.2 authoring."""
        doc = _task_doc()
        del doc["payload"][missing]
        with pytest.raises(ContractValidationError):
            validate_proof_task(doc)

    def test_wrong_artifact_const_rejected(self):
        doc = _task_doc()
        doc["bridge"]["artifact"] = "arxmcp.bridge/evidence-bundle"
        with pytest.raises(ContractValidationError):
            validate_proof_task(doc)

    def test_field_lane_enum_pinned(self):
        validate_proof_task(_task_doc(field_lane="math.NT"))
        with pytest.raises(ContractValidationError):
            validate_proof_task(_task_doc(field_lane="math.QA"))

    def test_target_verdict_floor_is_five_verdict_taxonomy(self):
        validate_proof_task(_task_doc(target_verdict_floor="refuted"))
        with pytest.raises(ContractValidationError):
            validate_proof_task(_task_doc(target_verdict_floor="proved"))

    def test_skeptic_lean_kind_enum(self):
        good = {
            "lean": [
                {"name": "w", "kind": "witness", "snippet": "example : True := trivial"}
            ]
        }
        validate_proof_task(_task_doc(skeptic_checks=good))
        bad = copy.deepcopy(good)
        bad["lean"][0]["kind"] = "decide"
        with pytest.raises(ContractValidationError):
            validate_proof_task(_task_doc(skeptic_checks=bad))

    def test_skeptic_cas_requires_name_and_code(self):
        with pytest.raises(ContractValidationError):
            validate_proof_task(
                _task_doc(skeptic_checks={"cas": [{"name": "scan"}]})
            )

    def test_minor_additive_tolerance(self):
        """Registry convention (arx-c1 rule 1): consumers ignore unknown
        additive fields — no additionalProperties:false anywhere."""
        doc = _task_doc(some_future_v03_field={"x": 1})
        doc["bridge"]["some_future_bridge_field"] = True
        validate_proof_task(doc)


class TestEvidenceBundlePins:
    def test_valid_minimal_bundle(self):
        validate_evidence_bundle(_bundle_doc())

    @pytest.mark.parametrize("missing", ["task_id", "verdict"])
    def test_v01_stub_identity_core_preserved(self, missing):
        doc = _bundle_doc()
        del doc["payload"][missing]
        with pytest.raises(ContractValidationError):
            validate_evidence_bundle(doc)

    def test_verdict_enum_matches_kat_taxonomy(self):
        """Single-source cross-check: the schema's five-verdict enum is
        exactly ``server.kat.VERDICTS`` (D9; append-only within the
        MAJOR)."""
        schema = load_schema(contracts.EVIDENCE_BUNDLE_SCHEMA_ID)
        enum = schema["allOf"][1]["properties"]["payload"]["properties"]["verdict"]["enum"]
        assert set(enum) == set(VERDICTS)
        assert len(enum) == len(VERDICTS)

    def test_off_taxonomy_verdict_rejected(self):
        with pytest.raises(ContractValidationError):
            validate_evidence_bundle(_bundle_doc(verdict="proved"))

    def test_refuted_requires_counterexample(self):
        """AC-D.7: `refuted` ships with a counterexample artifact."""
        with pytest.raises(ContractValidationError) as exc:
            validate_evidence_bundle(_bundle_doc(verdict="refuted"))
        assert "counterexample" in str(exc.value)
        validate_evidence_bundle(
            _bundle_doc(verdict="refuted", counterexample=_COUNTEREXAMPLE)
        )

    def test_counterexample_source_enum(self):
        bad = {**_COUNTEREXAMPLE, "source": "vibes"}
        with pytest.raises(ContractValidationError):
            validate_evidence_bundle(
                _bundle_doc(verdict="refuted", counterexample=bad)
            )

    def test_cas_artifact_replay_floor(self):
        """AC-D.11: every CAS artifact records code + params + timeout."""
        full = {
            "engine": "sympy-subprocess",
            "check": "scan",
            "status": "ok",
            "code": "def find_counterexample():\n    return None",
            "params": {"start": 0, "stop": 100},
            "timeout_s": 10.0,
            "found": False,
        }
        validate_evidence_bundle(_bundle_doc(cas=[full]))
        for replay_key in ("code", "params", "timeout_s"):
            broken = {k: v for k, v in full.items() if k != replay_key}
            with pytest.raises(ContractValidationError):
                validate_evidence_bundle(_bundle_doc(cas=[broken]))

    def test_skeptic_budget_pins_prover_cycles_zero(self):
        """AC-D.10 as schema: the skeptic lane runs BEFORE any prover
        cycle, so its budget's prover_cycles is the const 0."""
        skeptic = {
            "ran": True,
            "refuted": False,
            "checks": [],
            "budget": {
                "wall_clock_s": 0.1,
                "lean_queries": 0,
                "cas_runs": 0,
                "prover_cycles": 0,
            },
        }
        validate_evidence_bundle(_bundle_doc(skeptic=skeptic))
        cheat = copy.deepcopy(skeptic)
        cheat["budget"]["prover_cycles"] = 1
        with pytest.raises(ContractValidationError):
            validate_evidence_bundle(_bundle_doc(skeptic=cheat))

    def test_minor_additive_tolerance(self):
        validate_evidence_bundle(_bundle_doc(some_future_evidence_block={"x": 1}))

    def test_validation_error_names_the_path(self):
        doc = _bundle_doc(verdict="proved")
        with pytest.raises(ContractValidationError) as exc:
            validate_evidence_bundle(doc)
        assert "payload/verdict" in str(exc.value)


class TestExampleSubstrateHonesty:
    def test_example_substrate_pin_is_hex64(self):
        """The examples pin this branch's (arx-d2-era v17) tools/list
        hash. Schema-wise any 64-hex value validates; integration may
        refresh the value after its own re-pin (README note) — so this
        test pins the SHAPE, not the value, on purpose."""
        for name in (
            "proof-task.v0.example.json",
            "evidence-bundle.v0.example.json",
        ):
            pin = load_example(name)["bridge"]["substrate"]["tool_schema_sha256"]
            assert len(pin) == 64
            int(pin, 16)  # raises if not hex

    def test_refuted_example_proves_counterexample_first_budget(self):
        """The committed refuted example is the AC-D.10 shape: the
        skeptic lane refuted and the whole run spent zero prover
        cycles."""
        bundle = load_example("evidence-bundle.v0.example.json")
        payload = bundle["payload"]
        assert payload["verdict"] == "refuted"
        assert payload["skeptic"]["budget"]["prover_cycles"] == 0
        assert payload["cost"]["prover_cycles"] == 0
        assert payload["counterexample"]["kernel_confirmed"] is True


class TestSchemaFilesAreCanonicalJson:
    @pytest.mark.parametrize(
        "path",
        sorted(SCHEMAS_DIR.glob("*.schema.json"))
        + sorted((SCHEMAS_DIR / "examples").glob("*.json")),
        ids=lambda p: p.name,
    )
    def test_parseable_utf8_json(self, path):
        json.loads(path.read_text(encoding="utf-8"))
