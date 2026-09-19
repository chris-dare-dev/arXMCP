"""Bridge contract core suite (stage2/arx-c1, WS-C).

Covers AC-C.1 / AC-C.2 / AC-C.6 / AC-C.10 from the Stage-1 acceptance
criteria:

- ``contracts/registry.json`` is internally consistent (every listed
  schema exists; every schema is listed; versions parse MAJOR.MINOR).
- Every schema is itself a valid Draft-07 schema.
- Every committed example under ``contracts/examples/`` validates
  against its type schema, and its ``bridge.artifact`` /
  ``bridge.version`` agree with the registry.
- The envelope's substrate block is enforced: missing substrate,
  malformed ``tool_schema_sha256``, and any ``retrieval_mode`` other
  than ``dense_only`` (the D8 pin) are schema violations.
- ``retrieval-evidence`` wraps the proof-verify triangulation payload
  UNCHANGED: the vendored payload schema is byte-pinned by SHA-256,
  and two real historical triangulation artifacts (produced 2026-06-11
  and 2026-06-18, long before this contract existed) validate as v1.0
  payloads without modification.
- ``verdict-record`` vocabularies are domain-tagged and do NOT unify:
  a cross-domain enum leak (e.g. the proving domain claiming
  ``VERIFIED``) is a schema violation.
- The replay checker proves substrate-block sufficiency: from an
  artifact file alone, match/mismatch against a live substrate is
  decidable with a diagnostic naming both values.
"""

from __future__ import annotations

import copy
import re

import jsonschema
import pytest

from tests._bridge_helpers import (
    CONTRACTS_DIR,
    EXAMPLES_DIR,
    FIXTURES_DIR,
    all_schema_paths,
    example_path_for,
    load_json,
    load_registry_manifest,
    parse_version,
    substrate_matches,
    validator_for,
)

MANIFEST = load_registry_manifest()
ARTIFACT_TYPES: list[str] = sorted(MANIFEST["artifact_types"])
SCHEMA_FILES: list[str] = [MANIFEST["envelope"]["schema"]] + [
    MANIFEST["artifact_types"][t]["schema"] for t in ARTIFACT_TYPES
]


# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_expected_initial_types_present(self) -> None:
        """The Stage-1 initial registry (workstreams.md WS-C) is complete:
        six core types + two WS-D placement stubs + the WS-E skeleton."""
        expected = {
            "arxmcp.bridge/notebook-ref",
            "arxmcp.bridge/retrieval-evidence",
            "arxmcp.bridge/verdict-record",
            "arxmcp.bridge/ingest-receipt",
            "arxmcp.bridge/corpus-snapshot",
            "arxmcp.bridge/run-ledger-entry",
            "arxmcp.bridge/proof-task",
            "arxmcp.bridge/evidence-bundle",
            "arxmcp.bridge/proposed-notebook-manifest",
        }
        assert set(ARTIFACT_TYPES) == expected

    def test_every_listed_schema_file_exists(self) -> None:
        for schema_file in SCHEMA_FILES:
            assert (CONTRACTS_DIR / schema_file).is_file(), schema_file

    def test_every_schema_file_is_listed(self) -> None:
        """No orphan schemas: every contracts/*.schema.json is either the
        envelope or a registry entry.

        The ``payload_schema`` branch is kept though nothing uses it today:
        no payload schema is vendored here (they belong to the consumers that
        publish them), and if one ever is, it must be listed rather than
        silently tolerated as an orphan."""
        listed = set(SCHEMA_FILES)
        payload_listed = {
            entry["payload_schema"]
            for entry in MANIFEST["artifact_types"].values()
            if "payload_schema" in entry
        }
        for path in all_schema_paths():
            rel = path.relative_to(CONTRACTS_DIR).as_posix()
            assert rel in listed or rel in payload_listed, f"unlisted schema: {rel}"

    @pytest.mark.parametrize("artifact_type", ARTIFACT_TYPES)
    def test_versions_parse_major_minor(self, artifact_type: str) -> None:
        parse_version(MANIFEST["artifact_types"][artifact_type]["version"])

    @pytest.mark.parametrize("artifact_type", ARTIFACT_TYPES)
    def test_stub_status_matches_schema_marker(self, artifact_type: str) -> None:
        """registry.json status and the schema's x-bridge.status agree,
        and every stub declares its content owner (WS-D / WS-E)."""
        entry = MANIFEST["artifact_types"][artifact_type]
        schema = load_json(CONTRACTS_DIR / entry["schema"])
        assert schema["x-bridge"]["status"] == entry["status"]
        assert schema["x-bridge"]["version"] == entry["version"]
        assert schema["x-bridge"]["artifact"] == artifact_type
        if entry["status"] == "stub":
            assert entry["content_owner"] in {"WS-D", "WS-E"}
            assert schema["x-bridge"]["content_owner"] == entry["content_owner"]

    def test_stubs_are_exactly_the_declared_set(self) -> None:
        """Registry stub set pin. Initially three (c1); the two WS-D
        types were promoted stub -> draft at the Stage-2 integration
        custody move (IF-5: arx-d3's authored v0.2 content replaced
        the placement stubs — see CONTRACTS.md changelog), leaving the
        WS-E manifest as the only remaining stub."""
        stubs = {
            t for t in ARTIFACT_TYPES if MANIFEST["artifact_types"][t]["status"] == "stub"
        }
        assert stubs == {
            "arxmcp.bridge/proposed-notebook-manifest",
        }
        drafts = {
            t for t in ARTIFACT_TYPES if MANIFEST["artifact_types"][t]["status"] == "draft"
        }
        assert drafts == {
            "arxmcp.bridge/proof-task",
            "arxmcp.bridge/evidence-bundle",
        }


# ---------------------------------------------------------------------------
# Schema well-formedness + committed examples (AC-C.1)
# ---------------------------------------------------------------------------


class TestSchemasAndExamples:
    @pytest.mark.parametrize(
        "schema_path", all_schema_paths(), ids=lambda p: p.name
    )
    def test_schema_is_valid_draft7(self, schema_path) -> None:
        jsonschema.Draft7Validator.check_schema(load_json(schema_path))

    @pytest.mark.parametrize("artifact_type", ARTIFACT_TYPES)
    def test_committed_example_validates(self, artifact_type: str) -> None:
        entry = MANIFEST["artifact_types"][artifact_type]
        example = load_json(example_path_for(entry["schema"]))
        validator = validator_for(entry["schema"])
        errors = [e.message for e in validator.iter_errors(example)]
        assert errors == [], f"{artifact_type} example invalid: {errors}"

    @pytest.mark.parametrize("artifact_type", ARTIFACT_TYPES)
    def test_example_bridge_block_matches_registry(self, artifact_type: str) -> None:
        entry = MANIFEST["artifact_types"][artifact_type]
        example = load_json(example_path_for(entry["schema"]))
        assert example["bridge"]["artifact"] == artifact_type
        assert example["bridge"]["version"] == entry["version"]

    def test_every_example_file_belongs_to_a_registry_entry(self) -> None:
        """Every registry entry has its canonical example, and every
        extra example file is a named VARIANT of a registered type
        (``<schema-stem>.<variant>.example.json``) that validates
        against that type's schema. The variant allowance was added at
        the Stage-2 integration custody move (IF-5), which re-homed
        arx-d3's supplementary
        ``evidence-bundle.v0.proven-formal.example.json`` here."""
        stem_to_type = {
            example_path_for(MANIFEST["artifact_types"][t]["schema"]).name[
                : -len(".example.json")
            ]: t
            for t in ARTIFACT_TYPES
        }
        expected = {s + ".example.json" for s in stem_to_type}
        actual = {p.name for p in EXAMPLES_DIR.glob("*.example.json")}
        assert expected <= actual, (
            f"missing canonical examples: {sorted(expected - actual)}"
        )
        for name in sorted(actual - expected):
            base = name[: -len(".example.json")]
            owners = [
                t for s, t in stem_to_type.items() if base.startswith(s + ".")
            ]
            assert owners, f"orphan example (no registry entry): {name}"
            entry = MANIFEST["artifact_types"][owners[0]]
            example = load_json(EXAMPLES_DIR / name)
            errors = [
                e.message
                for e in validator_for(entry["schema"]).iter_errors(example)
            ]
            assert errors == [], f"variant example {name} invalid: {errors}"


# ---------------------------------------------------------------------------
# Envelope substrate enforcement (incl. the D8 retrieval_mode pin, AC-C.6)
# ---------------------------------------------------------------------------


def _valid_notebook_ref() -> dict:
    return load_json(example_path_for("notebook-ref.v1.schema.json"))


class TestEnvelopeSubstrate:
    def test_missing_substrate_rejected(self) -> None:
        artifact = _valid_notebook_ref()
        del artifact["bridge"]["substrate"]
        assert not validator_for("notebook-ref.v1.schema.json").is_valid(artifact)

    @pytest.mark.parametrize(
        "field",
        [
            "server",
            "corpus_version",
            "notebook",
            "filter_echo",
            "retrieval_mode",
            "tool_schema_sha256",
        ],
    )
    def test_missing_substrate_field_rejected(self, field: str) -> None:
        artifact = _valid_notebook_ref()
        del artifact["bridge"]["substrate"][field]
        assert not validator_for("notebook-ref.v1.schema.json").is_valid(artifact)

    def test_malformed_tool_schema_sha256_rejected(self) -> None:
        artifact = _valid_notebook_ref()
        artifact["bridge"]["substrate"]["tool_schema_sha256"] = "not-a-sha"
        assert not validator_for("notebook-ref.v1.schema.json").is_valid(artifact)

    def test_retrieval_mode_dense_only_is_sole_value(self) -> None:
        """D8: the envelope enum's SOLE value is dense_only. If this test
        fails because someone added a mode, that change must be a
        deliberate, versioned contract event (CONTRACTS.md rule 5) —
        hybrid re-opens only on a new measured verdict at materially
        larger corpus scale (finding 211 R-B), never as a side effect."""
        envelope = load_json(CONTRACTS_DIR / "envelope.v1.schema.json")
        substrate = envelope["properties"]["bridge"]["properties"]["substrate"]
        mode = substrate["properties"]["retrieval_mode"]
        assert mode["enum"] == ["dense_only"]

    @pytest.mark.parametrize("bad_mode", ["hybrid", "bm25", "dense", ""])
    def test_non_dense_only_retrieval_mode_rejected(self, bad_mode: str) -> None:
        artifact = _valid_notebook_ref()
        artifact["bridge"]["substrate"]["retrieval_mode"] = bad_mode
        assert not validator_for("notebook-ref.v1.schema.json").is_valid(artifact)

    def test_server_scoped_null_branch_accepted_for_corpus_snapshot(self) -> None:
        """corpus-snapshot legitimately carries null notebook/corpus_version
        (server scope); the committed example exercises that branch."""
        example = load_json(example_path_for("corpus-snapshot.v1.schema.json"))
        sub = example["bridge"]["substrate"]
        assert sub["notebook"] is None
        assert sub["corpus_version"] is None

    @pytest.mark.parametrize(
        "schema_file",
        ["notebook-ref.v1.schema.json", "retrieval-evidence.v1.schema.json"],
    )
    def test_notebook_scoped_types_reject_null_notebook(self, schema_file: str) -> None:
        artifact = load_json(example_path_for(schema_file))
        artifact["bridge"]["substrate"]["notebook"] = None
        assert not validator_for(schema_file).is_valid(artifact)

    def test_retrieval_evidence_requires_filter_echo(self) -> None:
        """The load-bearing anti-drift field: retrieval evidence without an
        affirmed notebook filter echo is not valid evidence (the spike-5
        failure — filter_echo null on all 38 queries — becomes a schema
        violation instead of a silent pass)."""
        artifact = load_json(example_path_for("retrieval-evidence.v1.schema.json"))
        artifact["bridge"]["substrate"]["filter_echo"] = None
        assert not validator_for("retrieval-evidence.v1.schema.json").is_valid(artifact)


# ---------------------------------------------------------------------------
# retrieval-evidence: triangulation payload wrapped UNCHANGED
# ---------------------------------------------------------------------------


class TestRetrievalEvidenceWrapsTriangulationUnchanged:
    """The payload schema is not vendored here (it belongs to the consumer
    that publishes it), so "wraps UNCHANGED" is proved the only way that
    survives that: real historical artifacts still validate, byte-for-byte
    unmodified, inside a v1.0 envelope."""

    @pytest.mark.parametrize(
        "fixture_name",
        [
            "fourier-duality-C-001-arxmcp.json",
            "algebraic-geometry-C-001-arxmcp.json",
        ],
    )
    def test_historical_artifact_validates_as_v1_payload(
        self, fixture_name: str
    ) -> None:
        """Backward-compat proof: real triangulation artifacts produced
        BEFORE this contract existed (2026-06-11 / 2026-06-18 runs)
        wrap into a v1.0 retrieval-evidence envelope with zero payload
        modification."""
        payload = load_json(FIXTURES_DIR / "historical" / fixture_name)
        slug = payload["result"]["notebook_slug"]
        wrapped = {
            "bridge": {
                "artifact": "arxmcp.bridge/retrieval-evidence",
                "version": "1.0",
                "producer": payload["agent"],
                "produced_at": payload["queried_at"],
                "substrate": {
                    "server": "arxmcp",
                    "corpus_version": payload["result"]["corpus_version"],
                    "notebook": {
                        "slug": slug,
                        "uri": f"arxmcp://notebooks/{slug}",
                    },
                    "filter_echo": {"notebook": slug},
                    "retrieval_mode": "dense_only",
                    "tool_schema_sha256": "c7df4c5c10c86693ac8553b7d079b55f"
                    "ba21749881c233f0f298955379d13375",
                },
            },
            "payload": payload,
        }
        validator = validator_for("retrieval-evidence.v1.schema.json")
        errors = [e.message for e in validator.iter_errors(wrapped)]
        assert errors == [], errors

    def test_payload_interior_is_not_this_contract_to_police(self) -> None:
        """This envelope does NOT reject an unknown top-level payload field,
        and that is deliberate rather than an oversight: the payload's schema
        belongs to the consumer that publishes it and is not vendored here, so
        this contract cannot speak for it. The strictness still exists -- on
        the consumer's side. A future reader tempted to "fix" this by adding
        additionalProperties:false would be asserting a constraint this
        repository has no copy of and no right to define.
        """
        artifact = load_json(example_path_for("retrieval-evidence.v1.schema.json"))
        artifact["payload"]["surprise_field"] = True
        assert validator_for("retrieval-evidence.v1.schema.json").is_valid(artifact)


# ---------------------------------------------------------------------------
# verdict-record: domain-tagged vocabularies, no unification (AC-C.10)
# ---------------------------------------------------------------------------


def _verdict_artifact(domain: str, verdict: str) -> dict:
    artifact = load_json(example_path_for("verdict-record.v1.schema.json"))
    artifact = copy.deepcopy(artifact)
    artifact["payload"]["domain"] = domain
    artifact["payload"]["verdict"] = verdict
    return artifact


class TestVerdictRecordDomains:
    VALIDATOR_FILE = "verdict-record.v1.schema.json"

    @pytest.mark.parametrize(
        ("domain", "verdict"),
        [
            ("lean", "ok"),
            ("lean", "sorry"),
            ("lean", "timeout"),
            ("proof-verify", "VERIFIED"),
            ("proof-verify", "OUT-OF-CORPUS"),
            ("proving", "proven-formal"),
            ("proving", "abstained"),
            ("proving", "refuted"),
            # cite-audit vocabulary is deliberately unpinned at v1.0
            # (no code-verified ground truth; see CONTRACTS.md Known gap).
            ("cite-audit", "VERIFIED"),
        ],
    )
    def test_in_domain_verdicts_accepted(self, domain: str, verdict: str) -> None:
        assert validator_for(self.VALIDATOR_FILE).is_valid(
            _verdict_artifact(domain, verdict)
        )

    @pytest.mark.parametrize(
        ("domain", "verdict"),
        [
            # SP2 measured that vocabularies do NOT unify: leaks between
            # domains must be schema violations, not silent passes.
            ("proving", "VERIFIED"),
            ("proving", "ok"),
            ("proof-verify", "proven-formal"),
            ("proof-verify", "abstained"),
            ("lean", "VERIFIED"),
            ("lean", "refuted"),
        ],
    )
    def test_cross_domain_enum_leak_rejected(self, domain: str, verdict: str) -> None:
        assert not validator_for(self.VALIDATOR_FILE).is_valid(
            _verdict_artifact(domain, verdict)
        )

    def test_unknown_domain_rejected(self) -> None:
        assert not validator_for(self.VALIDATOR_FILE).is_valid(
            _verdict_artifact("astrology", "VERIFIED")
        )

    def test_statement_hash_required(self) -> None:
        artifact = load_json(example_path_for(self.VALIDATOR_FILE))
        del artifact["payload"]["statement_sha256"]
        assert not validator_for(self.VALIDATOR_FILE).is_valid(artifact)


# ---------------------------------------------------------------------------
# Placement stubs (WS-D) + WS-E skeleton
# ---------------------------------------------------------------------------


class TestStubs:
    def test_proof_task_pins_only_the_identity_core(self) -> None:
        schema = load_json(CONTRACTS_DIR / "proof-task.v0.schema.json")
        payload = schema["allOf"][1]["properties"]["payload"]
        assert payload["required"] == ["task_id", "statement_latex"]

    def test_evidence_bundle_pins_five_verdict_taxonomy(self) -> None:
        """D9 soundness core: the five-verdict enum is pinned even at the
        v0 stub, abstained included (the structural default)."""
        schema = load_json(CONTRACTS_DIR / "evidence-bundle.v0.schema.json")
        payload = schema["allOf"][1]["properties"]["payload"]
        assert payload["properties"]["verdict"]["enum"] == [
            "proven-formal",
            "proven-informal-checked",
            "plausible-unverified",
            "refuted",
            "abstained",
        ]
        assert payload["required"] == ["task_id", "verdict"]

    def test_evidence_bundle_rejects_free_text_verdict(self) -> None:
        artifact = load_json(example_path_for("evidence-bundle.v0.schema.json"))
        artifact["payload"]["verdict"] = "proved!"
        assert not validator_for("evidence-bundle.v0.schema.json").is_valid(artifact)

    def test_manifest_requires_provenance_capable_paper_entries(self) -> None:
        """WS-E skeleton: a paper entry with neither arxiv_id nor url is
        rejected (every proposal must be identifiable; AC-E.4 provenance
        fields ride alongside)."""
        artifact = load_json(
            example_path_for("proposed-notebook-manifest.v0.schema.json")
        )
        artifact["payload"]["papers"].append({"title": "mystery paper, no id"})
        validator = validator_for("proposed-notebook-manifest.v0.schema.json")
        assert not validator.is_valid(artifact)

    def test_manifest_requires_topic_window_papers_textbooks(self) -> None:
        schema = load_json(
            CONTRACTS_DIR / "proposed-notebook-manifest.v0.schema.json"
        )
        payload = schema["allOf"][1]["properties"]["payload"]
        assert payload["required"] == ["topic", "window", "papers", "textbooks"]


# ---------------------------------------------------------------------------
# CONTRACTS.md changelog coverage
# ---------------------------------------------------------------------------


class TestChangelog:
    def test_contracts_md_exists(self) -> None:
        assert (CONTRACTS_DIR / "CONTRACTS.md").is_file()

    @pytest.mark.parametrize("artifact_type", ARTIFACT_TYPES)
    def test_every_type_and_version_is_recorded(self, artifact_type: str) -> None:
        """Every registry entry appears in the changelog with its current
        version (rule 5: every bump lands in CONTRACTS.md)."""
        text = (CONTRACTS_DIR / "CONTRACTS.md").read_text(encoding="utf-8")
        entry = MANIFEST["artifact_types"][artifact_type]
        assert artifact_type in text
        pattern = re.escape(artifact_type) + r"[^\n]*" + re.escape(entry["version"])
        assert re.search(pattern, text), (
            f"CONTRACTS.md does not record {artifact_type} at {entry['version']}"
        )


# ---------------------------------------------------------------------------
# Replay sufficiency (AC-C.2): substrate match is decidable from the file
# ---------------------------------------------------------------------------


LIVE_FOURIER = {
    "server": "arxmcp",
    "corpus_version": 205,
    "notebook_slug": "fourier-duality",
    "retrieval_mode": "dense_only",
    "tool_schema_sha256": (
        "c7df4c5c10c86693ac8553b7d079b55fba21749881c233f0f298955379d13375"
    ),
}


class TestReplaySufficiency:
    def test_matching_substrate_passes(self) -> None:
        artifact = load_json(example_path_for("retrieval-evidence.v1.schema.json"))
        ok, mismatches = substrate_matches(artifact, LIVE_FOURIER)
        assert ok, mismatches

    def test_stale_corpus_version_detected_with_both_values_named(self) -> None:
        """The spike-1/2/3 killer: a corpus_version drift is detected from
        the artifact alone, and the diagnostic names BOTH versions."""
        artifact = load_json(example_path_for("retrieval-evidence.v1.schema.json"))
        live = dict(LIVE_FOURIER, corpus_version=999)
        ok, mismatches = substrate_matches(artifact, live)
        assert not ok
        assert any("205" in m and "999" in m for m in mismatches)

    def test_wrong_notebook_detected(self) -> None:
        artifact = load_json(example_path_for("retrieval-evidence.v1.schema.json"))
        live = dict(LIVE_FOURIER, notebook_slug="bridgeland-stability")
        ok, mismatches = substrate_matches(artifact, live)
        assert not ok
        assert any(
            "fourier-duality" in m and "bridgeland-stability" in m for m in mismatches
        )

    def test_tool_schema_drift_detected(self) -> None:
        artifact = load_json(example_path_for("retrieval-evidence.v1.schema.json"))
        live = dict(LIVE_FOURIER, tool_schema_sha256="f" * 64)
        ok, mismatches = substrate_matches(artifact, live)
        assert not ok
        assert any("tool_schema_sha256" in m for m in mismatches)

    def test_every_committed_example_is_checkable(self) -> None:
        """Sufficiency over the whole registry: the checker runs on every
        example artifact without needing any information beyond the
        file itself (server-scoped null fields are treated as
        non-binding by design)."""
        for artifact_type in ARTIFACT_TYPES:
            entry = MANIFEST["artifact_types"][artifact_type]
            artifact = load_json(example_path_for(entry["schema"]))
            ok, mismatches = substrate_matches(artifact, LIVE_FOURIER)
            assert isinstance(ok, bool)
            assert isinstance(mismatches, list)
