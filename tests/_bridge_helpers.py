"""Shared helpers for the bridge-contract test suites (stage2/arx-c1).

Mirrors the ``tests/_graph_helpers.py`` precedent: pure helper module,
no fixtures, imported by ``tests/test_bridge_contracts.py`` and
``tests/test_bridge_versioning_rules.py``.

Also hosts the two *reference consumer implementations* the versioning
rules are tested through:

- :func:`select_schema` — the consumer-side version gate. MINOR-tolerant
  (an artifact at a higher MINOR of a supported MAJOR is accepted),
  MAJOR-refusing (an unknown MAJOR raises :class:`MajorVersionRefused`
  with a diagnostic naming both versions — the one-line preflight
  failure that replaces the historical day-long stale-daemon probe
  cycles).
- :func:`substrate_matches` — the replay checker: given only an
  artifact (its envelope substrate block) and a description of the live
  substrate, decide whether they match, reporting every mismatch with
  both values named (AC-C.2).

The website's Phase-0 preflight and the WS-A ``GET /bridge/contracts``
handshake are expected to mirror these semantics; they are deliberately
small enough to re-implement from this file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
CONTRACTS_DIR: Path = REPO_ROOT / "contracts"
EXAMPLES_DIR: Path = CONTRACTS_DIR / "examples"
FIXTURES_DIR: Path = Path(__file__).resolve().parent / "fixtures" / "contracts"

def load_json(path: Path) -> Any:
    """Load a JSON document from ``path`` (UTF-8)."""
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_registry_manifest() -> dict[str, Any]:
    """Load contracts/registry.json (the artifact-type → version map)."""
    return load_json(CONTRACTS_DIR / "registry.json")


def all_schema_paths() -> list[Path]:
    """Every schema file in contracts/ (top level).

    No payload schemas are vendored here: a payload's schema belongs to the
    consumer that publishes it, so this repository pins the envelope and
    passes the interior through.
    """
    return sorted(CONTRACTS_DIR.glob("*.schema.json"))


def build_ref_registry() -> Registry:
    """Build the referencing.Registry for cross-schema ``$ref`` resolution.

    Registers every schema under its ``$id`` (reference loader for
    consumers — see contracts/README.md).
    """
    resources: list[tuple[str, Resource]] = []
    for path in all_schema_paths():
        schema = load_json(path)
        resource = Resource.from_contents(schema, default_specification=DRAFT7)
        resources.append((schema["$id"], resource))
    return Registry().with_resources(resources)


def validator_for(schema_file: str) -> jsonschema.Draft7Validator:
    """Return a Draft-07 validator for ``contracts/<schema_file>``."""
    schema = load_json(CONTRACTS_DIR / schema_file)
    return jsonschema.Draft7Validator(schema, registry=build_ref_registry())


def example_path_for(schema_file: str) -> Path:
    """Map ``<type>.v<N>.schema.json`` → ``examples/<type>.v<N>.example.json``."""
    return EXAMPLES_DIR / schema_file.replace(".schema.json", ".example.json")


class MajorVersionRefused(Exception):
    """A consumer refused an artifact whose MAJOR it does not support."""


def parse_version(version: str) -> tuple[int, int]:
    """Parse a strict ``MAJOR.MINOR`` version string.

    Raises ``ValueError`` on anything else (``"1"``, ``"1.0.0"``,
    ``"v1.0"``, ``"01.0"`` are all refused — producers embed exactly
    two numeric components).
    """
    parts = version.split(".")
    if len(parts) != 2:
        raise ValueError(f"not a MAJOR.MINOR version: {version!r}")
    major_s, minor_s = parts
    for part in (major_s, minor_s):
        if not part.isdigit() or (part != "0" and part.startswith("0")):
            raise ValueError(f"not a MAJOR.MINOR version: {version!r}")
    return int(major_s), int(minor_s)


def select_schema(artifact_type: str, artifact_version: str) -> str:
    """Consumer-side version gate (versioning rule 1, refusal half).

    Returns the schema filename for ``artifact_type`` when the
    artifact's MAJOR matches the registry's supported MAJOR. A higher
    MINOR within the same MAJOR is accepted (additive-only guarantee;
    unknown fields are ignored on read). An unknown MAJOR raises
    :class:`MajorVersionRefused` with a diagnostic naming the artifact
    type, the artifact's version, and the supported version.
    """
    manifest = load_registry_manifest()
    entry = manifest["artifact_types"].get(artifact_type)
    if entry is None:
        raise MajorVersionRefused(
            f"unknown artifact type {artifact_type!r}; "
            f"known: {sorted(manifest['artifact_types'])}"
        )
    supported = entry["version"]
    supported_major, _ = parse_version(supported)
    artifact_major, _ = parse_version(artifact_version)
    if artifact_major != supported_major:
        raise MajorVersionRefused(
            f"{artifact_type}: artifact declares version {artifact_version} "
            f"(MAJOR {artifact_major}) but this consumer supports "
            f"{supported} (MAJOR {supported_major}); refusing to read. "
            f"Update the vendored contract pin or the producer."
        )
    return entry["schema"]


def substrate_matches(
    artifact: dict[str, Any], live: dict[str, Any]
) -> tuple[bool, list[str]]:
    """Replay checker (AC-C.2): does the live substrate match the artifact's?

    ``live`` is a plain description of the current substrate, e.g.::

        {"server": "arxmcp", "corpus_version": 1690,
         "notebook_slug": "bridgeland-stability",
         "retrieval_mode": "dense_only", "tool_schema_sha256": "..."}

    Returns ``(ok, mismatches)`` where every mismatch names the field
    and BOTH values — the precise diagnostic that turns the historical
    stale-substrate probe cycles into a one-line failure.
    """
    sub = artifact["bridge"]["substrate"]
    mismatches: list[str] = []

    def _check(field: str, artifact_value: Any, live_value: Any) -> None:
        if artifact_value is not None and artifact_value != live_value:
            mismatches.append(
                f"{field}: artifact was produced against {artifact_value!r} "
                f"but the live substrate reports {live_value!r}"
            )

    _check("server", sub.get("server"), live.get("server"))
    _check("corpus_version", sub.get("corpus_version"), live.get("corpus_version"))
    notebook = sub.get("notebook")
    if notebook is not None:
        _check("notebook", notebook.get("slug"), live.get("notebook_slug"))
    _check("retrieval_mode", sub.get("retrieval_mode"), live.get("retrieval_mode"))
    _check(
        "tool_schema_sha256",
        sub.get("tool_schema_sha256"),
        live.get("tool_schema_sha256"),
    )
    return (not mismatches, mismatches)
