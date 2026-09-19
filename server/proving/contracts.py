"""ProofTask / EvidenceBundle contract loading + validation
(stage2/arx-d3 — WS-D over the WS-C registry conventions; AC-D.13).

Every proving run consumes exactly one **ProofTask** and emits exactly
one **EvidenceBundle**; both are envelope-wrapped bridge artifacts
following the ``contracts/`` registry conventions established on
``stage2/arx-c1`` (URN ``$id``s, per-type MAJOR.MINOR, MINOR = additive
only, enums append-only within a MAJOR).

**Custody (IF-5) — move executed at Stage-2 integration.** The
WS-D-authored v0.2 schema content now lives in the repo-root
``contracts/`` registry (WS-C hosts and versions the types; WS-D
authors the payload content). The slice-custody copies under
``server/proving/schemas/`` — including the vendored envelope — were
moved/deleted per the move list in ``server/proving/README.md``;
this module loads directly from ``contracts/`` (the SHA-256 envelope
pin in ``tests/test_proving_contracts.py`` now guards the canonical
file itself).

Loader contract (mirrors ``contracts/README.md`` on arx-c1): schema
``$id``s are opaque, never-fetched URNs; a local
:class:`referencing.Registry` maps each ``$id`` to its contents.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

#: Directory holding the schema files: the repo-root ``contracts/``
#: registry (IF-5 custody move executed at Stage-2 integration; the
#: pre-integration value was the slice-custody
#: ``server/proving/schemas/``).
SCHEMAS_DIR: Path = Path(__file__).resolve().parents[2] / "contracts"

#: Directory holding the committed, test-validated example artifacts.
EXAMPLES_DIR: Path = SCHEMAS_DIR / "examples"

ENVELOPE_SCHEMA_ID = "urn:arxmcp:bridge:envelope:v1"
PROOF_TASK_SCHEMA_ID = "urn:arxmcp:bridge:proof-task:v0"
EVIDENCE_BUNDLE_SCHEMA_ID = "urn:arxmcp:bridge:evidence-bundle:v0"

PROOF_TASK_ARTIFACT = "arxmcp.bridge/proof-task"
EVIDENCE_BUNDLE_ARTIFACT = "arxmcp.bridge/evidence-bundle"

#: Authored versions (the arx-c1 registry carries the 0.1 stubs; the
#: integration step bumps its ``registry.json`` entries to these).
#: proof-task bumped 0.2 → 0.3 at stage3/proving-r3: an additive,
#: back-compatible 0.MINOR bump adding the OPTIONAL skeptic-check
#: ``discharges`` refutation-linkage declaration (CONTRACTS.md v0-stub
#: rule; a missing declaration fails CLOSED — the confident refuted is
#: capped/escalated, never opened).
PROOF_TASK_VERSION = "0.3"
EVIDENCE_BUNDLE_VERSION = "0.2"

_SCHEMA_FILES: dict[str, str] = {
    ENVELOPE_SCHEMA_ID: "envelope.v1.schema.json",
    PROOF_TASK_SCHEMA_ID: "proof-task.v0.schema.json",
    EVIDENCE_BUNDLE_SCHEMA_ID: "evidence-bundle.v0.schema.json",
}


class ContractValidationError(ValueError):
    """A document failed validation against its bridge schema. Carries
    a readable, path-annotated summary of every error (a proving run
    must never proceed on a malformed task or emit a malformed
    bundle)."""


def load_schema(schema_id: str) -> dict[str, Any]:
    """Load one schema by its URN ``$id`` from :data:`SCHEMAS_DIR`."""
    try:
        filename = _SCHEMA_FILES[schema_id]
    except KeyError:
        raise KeyError(
            f"unknown bridge schema id {schema_id!r}; known: "
            f"{sorted(_SCHEMA_FILES)}"
        ) from None
    return json.loads((SCHEMAS_DIR / filename).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def schema_registry() -> Registry:
    """The local ``$id`` → contents registry (URNs are never fetched)."""
    resources = [
        (schema_id, Resource.from_contents(load_schema(schema_id), default_specification=DRAFT7))
        for schema_id in _SCHEMA_FILES
    ]
    return Registry().with_resources(resources)


@lru_cache(maxsize=len(_SCHEMA_FILES))
def _validator_for(schema_id: str) -> Draft7Validator:
    schema = load_schema(schema_id)
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema, registry=schema_registry())


def _validate(doc: Mapping[str, Any], schema_id: str, kind: str) -> None:
    errors = sorted(
        _validator_for(schema_id).iter_errors(doc),
        key=lambda e: list(e.absolute_path),
    )
    if errors:
        detail = "; ".join(
            f"at {'/'.join(str(p) for p in err.absolute_path) or '<root>'}: "
            f"{err.message}"
            for err in errors[:10]
        )
        more = f" (+{len(errors) - 10} more)" if len(errors) > 10 else ""
        raise ContractValidationError(
            f"invalid {kind} artifact: {detail}{more}"
        )


def validate_proof_task(doc: Mapping[str, Any]) -> None:
    """Validate an envelope-wrapped ProofTask document.

    Raises :class:`ContractValidationError` with a path-annotated
    summary on failure; returns ``None`` on success.
    """
    _validate(doc, PROOF_TASK_SCHEMA_ID, "proof-task")


def validate_evidence_bundle(doc: Mapping[str, Any]) -> None:
    """Validate an envelope-wrapped EvidenceBundle document.

    Raises :class:`ContractValidationError` with a path-annotated
    summary on failure; returns ``None`` on success.
    """
    _validate(doc, EVIDENCE_BUNDLE_SCHEMA_ID, "evidence-bundle")


def load_example(name: str) -> dict[str, Any]:
    """Load a committed example artifact by filename."""
    return json.loads((EXAMPLES_DIR / name).read_text(encoding="utf-8"))


def wrap_payload(
    *,
    artifact: str,
    version: str,
    producer: str,
    produced_at: str,
    substrate: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Assemble an envelope-wrapped bridge document.

    Pure structural assembly for the D-6 orchestrator and tests — no
    validation happens here; call :func:`validate_proof_task` /
    :func:`validate_evidence_bundle` on the result. ``substrate`` must
    carry the envelope's six required pins (``server``,
    ``corpus_version``, ``notebook``, ``filter_echo``,
    ``retrieval_mode``, ``tool_schema_sha256``).
    """
    return {
        "bridge": {
            "artifact": artifact,
            "version": version,
            "producer": producer,
            "produced_at": produced_at,
            "substrate": dict(substrate),
        },
        "payload": dict(payload),
    }


__all__ = [
    "ENVELOPE_SCHEMA_ID",
    "EVIDENCE_BUNDLE_ARTIFACT",
    "EVIDENCE_BUNDLE_SCHEMA_ID",
    "EVIDENCE_BUNDLE_VERSION",
    "EXAMPLES_DIR",
    "PROOF_TASK_ARTIFACT",
    "PROOF_TASK_SCHEMA_ID",
    "PROOF_TASK_VERSION",
    "SCHEMAS_DIR",
    "ContractValidationError",
    "load_example",
    "load_schema",
    "schema_registry",
    "validate_evidence_bundle",
    "validate_proof_task",
    "wrap_payload",
]
