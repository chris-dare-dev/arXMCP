"""``GET /bridge/contracts`` — the bridge-contract handshake (stage2/arx-a1).

The one endpoint that converts the historical day-long stale-daemon
probe cycles into a one-line preflight failure (finding 06 §2.5.2
item 4; target-architecture.md §5.4): a consumer (the website's
`/proof-verify` Phase-0 preflight, a future orchestrator) fetches the
artifact-type → version map plus per-schema SHA-256s and compares them
against its vendored pins. Mismatch → halt with a precise diagnostic
naming both versions; match → proceed.

**Registry source.** The producer-owned ``contracts/`` directory at the
repo root (decision D2 — WS-C authors its content). This endpoint is
deliberately tolerant of the directory not existing yet: WS-A ships the
handshake transport before WS-C lands the registry, so an absent (or
empty) ``contracts/`` serves an **empty-registry envelope** with
``registry_status: "absent"`` rather than a 404 — consumers can already
distinguish "server too old to have the endpoint" (HTTP 404) from
"server current, contracts not yet published" (200 + ``absent``).

**Registry layout contract** (tolerant by design, tightened when WS-C
lands):

1. If ``contracts/registry.json`` exists it is authoritative: a JSON
   object whose ``artifact_types`` maps ``<type-id>`` →
   ``{"version": "<MAJOR.MINOR>", "schema": "<relative filename>"}``.
   Each referenced schema file is hashed (SHA-256 of raw bytes).
2. Otherwise every ``*.json`` schema file directly under ``contracts/``
   (excluding ``registry.json`` itself and anything under
   ``examples/``) is listed by filename stem, with ``version`` read
   from the schema document's ``x-bridge-version`` (fallback:
   top-level ``version``) when present, else ``null``.

Security posture: read-only, loopback-bound (inherits every middleware
on the app), no host paths in the response (filenames are relative),
bounded reads (schemas are small JSON documents; a per-file byte cap
refuses pathological files). NOT an MCP surface — ``tools/list`` bytes
and the BP1 hashes are untouched (pinned by
``tests/test_bridge_route.py``).
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["bridge"])

#: Handshake response format version (independent of any artifact-type
#: version — this versions the ENVELOPE of the handshake itself).
BRIDGE_HANDSHAKE_FORMAT_VERSION: int = 1

#: Repo root — ``server/routes/bridge.py`` → three parents up.
_REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent

#: The producer-owned contracts directory (D2). WS-C authors content.
CONTRACTS_DIR: Path = _REPO_ROOT / "contracts"

#: Refuse to hash/parse any registry/schema file larger than this.
#: JSON Schemas here are a few KB; 1 MB is a generous ceiling that
#: keeps a corrupted/oversized file from ballooning the handshake.
_MAX_SCHEMA_BYTES: int = 1024 * 1024


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_schema_bytes(path: Path) -> bytes | None:
    """Read a schema file's raw bytes, or ``None`` when unreadable or
    oversized (logged; the entry then carries ``schema_sha256: null``
    so the consumer sees a positive "cannot verify" signal instead of
    a silently missing entry)."""
    try:
        if path.stat().st_size > _MAX_SCHEMA_BYTES:
            logger.warning(
                "/bridge/contracts: schema file %s exceeds %d bytes; "
                "refusing to hash",
                path.name, _MAX_SCHEMA_BYTES,
            )
            return None
        return path.read_bytes()
    except OSError:
        logger.warning(
            "/bridge/contracts: schema file %s unreadable", path.name,
            exc_info=True,
        )
        return None


def _entry_from_registry(
    contracts_dir: Path, type_id: str, meta: object
) -> dict[str, object]:
    """Build one artifact-type entry from an authoritative
    ``registry.json`` row. Tolerates malformed rows (non-dict meta,
    missing keys, unreadable schema files) by degrading fields to
    ``null`` — the handshake must serve whatever is verifiable."""
    version: object = None
    schema_name: object = None
    schema_sha256: object = None
    if isinstance(meta, dict):
        version = meta.get("version")
        schema_name = meta.get("schema")
        if isinstance(schema_name, str) and schema_name:
            # Containment: the schema reference must stay inside
            # contracts/ (a registry.json is repo-authored, but the
            # check is cheap defense-in-depth).
            candidate = (contracts_dir / schema_name).resolve()
            if candidate.is_relative_to(contracts_dir.resolve()) and candidate.is_file():
                raw = _read_schema_bytes(candidate)
                if raw is not None:
                    schema_sha256 = _sha256_hex(raw)
            else:
                logger.warning(
                    "/bridge/contracts: registry entry %r references "
                    "schema %r outside contracts/ or missing; serving "
                    "null sha", type_id, schema_name,
                )
    return {
        "version": version,
        "schema": schema_name,
        "schema_sha256": schema_sha256,
    }


def _scan_contracts_dir(
    contracts_dir: Path,
) -> tuple[str, dict[str, dict[str, object]], dict[str, object] | None]:
    """Return ``(registry_status, artifact_types, envelope)`` for the handshake.

    ``registry_status`` is one of:

    - ``"absent"`` — no ``contracts/`` directory (or it is empty of
      JSON files). The empty-registry envelope case.
    - ``"registry"`` — ``contracts/registry.json`` present and parsed;
      its ``artifact_types`` map is authoritative.
    - ``"scan"`` — no registry.json; entries derived from the schema
      files found directly under ``contracts/``.
    - ``"malformed_registry"`` — registry.json exists but is invalid
      JSON / wrong shape; falls back to the scan entries so the
      consumer still sees verifiable hashes, with the status naming
      the problem.

    ``envelope`` is the registry's top-level ``envelope`` block rendered
    as one verifiable entry (``{"version", "schema", "schema_sha256"}``)
    or ``None`` when there is no registry / no envelope block. The
    envelope is the six-field substrate wrapper (the anti-spike-1/2/3
    core) that every artifact-type schema references via an opaque URN
    ``$ref`` — so an envelope change moves ZERO bytes in any served
    artifact-type schema. stage3/cross-r1: it was previously never
    served, leaving the live preflight blind to envelope drift (the
    running-server-vs-disk divergence the handshake exists to catch).
    """
    if not contracts_dir.is_dir():
        return "absent", {}, None

    registry_path = contracts_dir / "registry.json"
    if registry_path.is_file():
        raw = _read_schema_bytes(registry_path)
        if raw is not None:
            try:
                doc = json.loads(raw)
            except json.JSONDecodeError:
                doc = None
            if isinstance(doc, dict) and isinstance(
                doc.get("artifact_types"), dict
            ):
                entries = {
                    str(type_id): _entry_from_registry(
                        contracts_dir, str(type_id), meta
                    )
                    for type_id, meta in sorted(doc["artifact_types"].items())
                }
                # stage3/cross-r1: also serve the top-level envelope
                # block so the consumer can verify the substrate wrapper.
                # Reuses the same tolerant hashing + containment path as
                # an artifact-type row (the envelope registry row has the
                # identical ``{version, schema}`` shape).
                envelope: dict[str, object] | None = None
                env_meta = doc.get("envelope")
                if isinstance(env_meta, dict):
                    envelope = _entry_from_registry(
                        contracts_dir, "envelope", env_meta
                    )
                return "registry", entries, envelope
        logger.warning(
            "/bridge/contracts: registry.json is malformed; falling "
            "back to directory scan"
        )
        status = "malformed_registry"
    else:
        status = "scan"

    entries = {}
    for path in sorted(contracts_dir.glob("*.json")):
        if path.name == "registry.json":
            continue
        raw = _read_schema_bytes(path)
        sha: object = _sha256_hex(raw) if raw is not None else None
        version: object = None
        if raw is not None:
            try:
                doc = json.loads(raw)
                if isinstance(doc, dict):
                    v = doc.get("x-bridge-version", doc.get("version"))
                    if isinstance(v, (str, int, float)):
                        version = v
            except json.JSONDecodeError:
                logger.warning(
                    "/bridge/contracts: schema %s is not valid JSON; "
                    "serving hash only", path.name,
                )
        # Type id = filename stem minus a conventional ``.schema``
        # suffix (``retrieval-evidence.schema.json`` and
        # ``retrieval-evidence.json`` both key as
        # ``retrieval-evidence``).
        stem = path.name[: -len(".json")]
        if stem.endswith(".schema"):
            stem = stem[: -len(".schema")]
        entries[stem] = {
            "version": version,
            "schema": path.name,
            "schema_sha256": sha,
        }
    if not entries and status == "scan":
        # Directory exists but holds no JSON — same consumer meaning
        # as no directory: nothing published yet.
        return "absent", {}, None
    # scan / malformed_registry paths cannot resolve an envelope block
    # (no authoritative registry to read it from); the envelope schema
    # file, if present, is already exposed as a scan entry.
    return status, entries, None


@router.get("/contracts")
async def bridge_contracts() -> dict[str, object]:
    """The contract-registry handshake (finding 06 §2.5.2 item 4).

    Response shape (all fields always present)::

        {
          "format_version": 1,
          "registry_status": "absent" | "registry" | "scan"
                             | "malformed_registry",
          "envelope": {"version": <str|null>,
                        "schema": <filename|null>,
                        "schema_sha256": <hex|null>} | null,
          "artifact_types": {
            "<type-id>": {"version": <str|null>,
                           "schema": <filename|null>,
                           "schema_sha256": <hex|null>},
            ...
          },
          "count": <int>
        }

    ``registry_status: "absent"`` with an empty map is the
    empty-registry envelope served until WS-C publishes ``contracts/``.

    ``envelope`` (stage3/cross-r1) is the top-level substrate-wrapper
    entry from ``registry.json`` (``null`` when there is no registry /
    no envelope block). It is served alongside the artifact types so the
    consumer's preflight can verify the six-field substrate block — the
    anti-spike-1/2/3 core — whose bytes never move in any artifact-type
    schema (they reference the envelope by opaque URN ``$ref``).
    ``format_version`` stays 1: the field is purely additive and
    older consumers ignore it.
    """
    status, entries, envelope = _scan_contracts_dir(CONTRACTS_DIR)
    return {
        "format_version": BRIDGE_HANDSHAKE_FORMAT_VERSION,
        "registry_status": status,
        "envelope": envelope,
        "artifact_types": entries,
        "count": len(entries),
    }


__all__ = [
    "BRIDGE_HANDSHAKE_FORMAT_VERSION",
    "CONTRACTS_DIR",
    "bridge_contracts",
    "router",
]
