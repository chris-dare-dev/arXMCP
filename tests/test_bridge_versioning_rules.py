"""Bridge contract versioning rules AS TESTS (stage2/arx-c1, WS-C).

Covers AC-C.3 from the Stage-1 acceptance criteria — the versioning
scheme is executable, not prose:

(i)   MINOR tolerance — an artifact carrying unknown *additive* fields
      still validates (consumers MUST ignore unknown fields), at the
      bridge, substrate, and payload levels. Documented exception: the
      retrieval-evidence payload is the verbatim strict triangulation
      contract (additions live inside its open ``result`` object), so
      its payload level is exercised via ``result`` instead.
(ii)  MAJOR refusal — an artifact declaring a higher MAJOR than the
      registry supports is refused with a precise diagnostic naming
      both versions; a higher MINOR within the supported MAJOR is
      accepted.
(iii) Enums are append-only within a MAJOR — every enum recorded in
      ``tests/fixtures/contracts/enum-baseline.json`` must still exist
      with at least its recorded values (codifies the m5 precedent
      that preserved the ``notebooklm`` enum value so 28 historical
      artifacts kept validating).

Plus the strict-version-string rule (exactly ``MAJOR.MINOR``) the
producers embed.
"""

from __future__ import annotations

import copy

import pytest

from tests._bridge_helpers import (
    CONTRACTS_DIR,
    FIXTURES_DIR,
    MajorVersionRefused,
    example_path_for,
    load_json,
    load_registry_manifest,
    parse_version,
    select_schema,
    validator_for,
)

MANIFEST = load_registry_manifest()
ARTIFACT_TYPES: list[str] = sorted(MANIFEST["artifact_types"])


def _example(artifact_type: str) -> dict:
    entry = MANIFEST["artifact_types"][artifact_type]
    return copy.deepcopy(load_json(example_path_for(entry["schema"])))


def _validator(artifact_type: str):
    return validator_for(MANIFEST["artifact_types"][artifact_type]["schema"])


# ---------------------------------------------------------------------------
# Rule (i): MINOR tolerance — unknown additive fields validate
# ---------------------------------------------------------------------------


class TestMinorAdditiveTolerance:
    @pytest.mark.parametrize("artifact_type", ARTIFACT_TYPES)
    def test_unknown_field_in_bridge_block_tolerated(
        self, artifact_type: str
    ) -> None:
        artifact = _example(artifact_type)
        artifact["bridge"]["x_future_minor_field"] = "ignored by v1 consumers"
        assert _validator(artifact_type).is_valid(artifact)

    @pytest.mark.parametrize("artifact_type", ARTIFACT_TYPES)
    def test_unknown_field_in_substrate_tolerated(self, artifact_type: str) -> None:
        artifact = _example(artifact_type)
        artifact["bridge"]["substrate"]["x_future_pin"] = {"anything": True}
        assert _validator(artifact_type).is_valid(artifact)

    @pytest.mark.parametrize(
        "artifact_type",
        [t for t in ARTIFACT_TYPES if t != "arxmcp.bridge/retrieval-evidence"],
    )
    def test_unknown_payload_field_tolerated(self, artifact_type: str) -> None:
        artifact = _example(artifact_type)
        artifact["payload"]["x_future_payload_field"] = 42
        assert _validator(artifact_type).is_valid(artifact)

    def test_retrieval_evidence_additions_live_inside_result(self) -> None:
        """Documented exception (CONTRACTS.md): the triangulation payload
        is strict at its top level by inherited design; its additive
        surface is the open ``result`` object — proven here."""
        artifact = _example("arxmcp.bridge/retrieval-evidence")
        artifact["payload"]["result"]["x_new_dual_signal_field"] = 0.5
        assert _validator("arxmcp.bridge/retrieval-evidence").is_valid(artifact)

    def test_top_level_document_tolerates_unknown_siblings(self) -> None:
        """A future MINOR may add envelope-level siblings to bridge/payload."""
        artifact = _example("arxmcp.bridge/notebook-ref")
        artifact["x_sidecar"] = {"annotations": []}
        assert _validator("arxmcp.bridge/notebook-ref").is_valid(artifact)


# ---------------------------------------------------------------------------
# Rule (ii): MAJOR refusal with a precise diagnostic; MINOR drift accepted
# ---------------------------------------------------------------------------


class TestMajorRefusal:
    @pytest.mark.parametrize("artifact_type", ARTIFACT_TYPES)
    def test_supported_version_selects_schema(self, artifact_type: str) -> None:
        entry = MANIFEST["artifact_types"][artifact_type]
        assert select_schema(artifact_type, entry["version"]) == entry["schema"]

    @pytest.mark.parametrize("artifact_type", ARTIFACT_TYPES)
    def test_higher_minor_same_major_accepted(self, artifact_type: str) -> None:
        """The additive-only guarantee makes higher-MINOR artifacts safe
        to read: consumers ignore the unknown fields."""
        entry = MANIFEST["artifact_types"][artifact_type]
        major, minor = parse_version(entry["version"])
        assert (
            select_schema(artifact_type, f"{major}.{minor + 7}") == entry["schema"]
        )

    def test_unknown_major_refused_naming_both_versions(self) -> None:
        """AC-C.3(ii): the refusal diagnostic names the artifact's version
        AND the supported version — a one-line preflight failure
        instead of a day-long stale-daemon probe cycle."""
        with pytest.raises(MajorVersionRefused) as excinfo:
            select_schema("arxmcp.bridge/retrieval-evidence", "2.0")
        message = str(excinfo.value)
        assert "2.0" in message
        assert "1.0" in message
        assert "arxmcp.bridge/retrieval-evidence" in message

    def test_unknown_artifact_type_refused(self) -> None:
        with pytest.raises(MajorVersionRefused):
            select_schema("arxmcp.bridge/does-not-exist", "1.0")

    @pytest.mark.parametrize("bad", ["1", "1.0.0", "v1.0", "01.0", "1.", ".1", ""])
    def test_non_major_minor_version_strings_refused(self, bad: str) -> None:
        with pytest.raises(ValueError):
            parse_version(bad)

    @pytest.mark.parametrize("good", [("1.0", (1, 0)), ("0.1", (0, 1)), ("12.34", (12, 34))])
    def test_major_minor_version_strings_parse(self, good) -> None:
        text, expected = good
        assert parse_version(text) == expected

    def test_schema_rejects_three_component_version_at_validation(self) -> None:
        artifact = _example("arxmcp.bridge/notebook-ref")
        artifact["bridge"]["version"] = "1.0.0"
        assert not _validator("arxmcp.bridge/notebook-ref").is_valid(artifact)


# ---------------------------------------------------------------------------
# Rule (iii): enums are append-only within a MAJOR
# ---------------------------------------------------------------------------


def _resolve_pointer(document: dict, pointer: str):
    """Minimal RFC 6901 resolver (no escapes needed for our paths)."""
    node = document
    for token in pointer.lstrip("/").split("/"):
        node = node[int(token)] if isinstance(node, list) else node[token]
    return node


BASELINE = {
    schema_file: pointers
    for schema_file, pointers in load_json(
        FIXTURES_DIR / "enum-baseline.json"
    ).items()
    if not schema_file.startswith("_")
}

BASELINE_CASES = [
    (schema_file, pointer, values)
    for schema_file, pointers in BASELINE.items()
    for pointer, values in pointers.items()
]


class TestEnumAppendOnly:
    @pytest.mark.parametrize(
        ("schema_file", "pointer", "recorded"),
        BASELINE_CASES,
        ids=[f"{s}:{p}" for s, p, _ in BASELINE_CASES],
    )
    def test_recorded_enum_values_still_present(
        self, schema_file: str, pointer: str, recorded: list
    ) -> None:
        """Removing or renaming an enum value recorded in the baseline is
        a breaking change and fails here; APPENDING a value passes
        (extend the baseline in the same change). This is the executable
        form of 'enums are append-only within a MAJOR'."""
        schema = load_json(CONTRACTS_DIR / schema_file)
        try:
            current = _resolve_pointer(schema, pointer)
        except (KeyError, IndexError, TypeError):
            pytest.fail(
                f"{schema_file}: baseline enum path {pointer} no longer exists - "
                "moving/removing an enum within a MAJOR is a breaking change"
            )
        missing = [v for v in recorded if v not in current]
        assert missing == [], (
            f"{schema_file}{pointer}: baseline enum values removed: {missing} "
            "(enums are append-only within a MAJOR; see CONTRACTS.md rule 2)"
        )

    def test_baseline_covers_the_load_bearing_enums(self) -> None:
        """The baseline must never silently lose its load-bearing rows:
        the D8 retrieval_mode pin, the verdict-record domain split, the
        run outcome states, and the D9 five-verdict taxonomy."""
        assert "envelope.v1.schema.json" in BASELINE
        assert any(
            "retrieval_mode" in pointer
            for pointer in BASELINE["envelope.v1.schema.json"]
        )
        assert "verdict-record.v1.schema.json" in BASELINE
        assert "run-ledger-entry.v1.schema.json" in BASELINE
        assert "evidence-bundle.v0.schema.json" in BASELINE

    # The m5 precedent that motivated rule 2 -- the retired `notebooklm`
    # backend must stay in the triangulation `source` enum so the historical
    # artifacts keep validating -- is NO LONGER GUARDED HERE, and the guard was
    # removed rather than weakened. That enum lives in the payload schema,
    # which the consumer owns and this repository does not vendor; a baseline
    # row for a file we do not have would assert something we cannot read.
    # The precedent binds on the consumer's side. What survives here is the
    # rule itself (enums are append-only within a MAJOR) over the schemas this
    # repository actually owns.
