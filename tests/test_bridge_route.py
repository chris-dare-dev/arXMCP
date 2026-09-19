"""Tests for GET /bridge/contracts — the handshake endpoint (stage2/arx-a1).

Coverage (acceptance-criteria.md AC-A.4):

- TestEmptyRegistry     — absent / empty contracts dir serves the
                          empty-registry envelope (WS-C hasn't landed
                          yet; the transport ships first).
- TestScanMode          — schema files without a registry.json are
                          listed with SHA-256s + best-effort versions.
- TestRegistryMode      — registry.json is authoritative; schema refs
                          are hashed; malformed registry degrades to
                          the scan with a naming status.
- TestByteStabilityGuard— AC-A.4's BP1 guard: importing + exercising
                          the bridge route leaves the canonical
                          ``tools/list`` bytes at the pinned hash.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.routes import bridge as bridge_module
from server.routes.bridge import (
    BRIDGE_HANDSHAKE_FORMAT_VERSION,
)
from server.routes.bridge import (
    router as bridge_router,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """App with only the bridge router; CONTRACTS_DIR redirected to
    tmp_path/contracts (which tests create or leave absent)."""
    monkeypatch.setattr(
        bridge_module, "CONTRACTS_DIR", tmp_path / "contracts"
    )
    app = FastAPI()
    app.include_router(bridge_router, prefix="/bridge")
    return TestClient(app)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Empty-registry envelope
# ---------------------------------------------------------------------------


class TestEmptyRegistry:
    def test_absent_dir_serves_empty_envelope(self, client: TestClient) -> None:
        r = client.get("/bridge/contracts")
        assert r.status_code == 200
        # stage3/cross-r1: the response now always carries an ``envelope``
        # key (null when there is no registry / envelope block).
        assert r.json() == {
            "format_version": BRIDGE_HANDSHAKE_FORMAT_VERSION,
            "registry_status": "absent",
            "envelope": None,
            "artifact_types": {},
            "count": 0,
        }

    def test_empty_dir_serves_empty_envelope(
        self, client: TestClient, tmp_path: Path,
    ) -> None:
        (tmp_path / "contracts").mkdir()
        body = client.get("/bridge/contracts").json()
        assert body["registry_status"] == "absent"
        assert body["artifact_types"] == {}


# ---------------------------------------------------------------------------
# Scan mode (no registry.json)
# ---------------------------------------------------------------------------


class TestScanMode:
    def test_schema_files_hashed_and_versioned(
        self, client: TestClient, tmp_path: Path,
    ) -> None:
        cdir = tmp_path / "contracts"
        cdir.mkdir()
        ev = json.dumps(
            {"x-bridge-version": "1.0", "type": "object"}
        ).encode()
        (cdir / "retrieval-evidence.schema.json").write_bytes(ev)
        raw2 = json.dumps({"type": "object"}).encode()
        (cdir / "notebook-ref.json").write_bytes(raw2)

        body = client.get("/bridge/contracts").json()
        assert body["registry_status"] == "scan"
        assert body["count"] == 2
        types = body["artifact_types"]
        # ``.schema.json`` suffix collapses into the type id.
        assert types["retrieval-evidence"]["version"] == "1.0"
        assert types["retrieval-evidence"]["schema_sha256"] == _sha(ev)
        assert types["retrieval-evidence"]["schema"] == (
            "retrieval-evidence.schema.json"
        )
        # No version marker → null version, hash still served.
        assert types["notebook-ref"]["version"] is None
        assert types["notebook-ref"]["schema_sha256"] == _sha(raw2)

    def test_invalid_json_schema_still_hashed(
        self, client: TestClient, tmp_path: Path,
    ) -> None:
        cdir = tmp_path / "contracts"
        cdir.mkdir()
        raw = b"{not json"
        (cdir / "broken.json").write_bytes(raw)
        types = client.get("/bridge/contracts").json()["artifact_types"]
        assert types["broken"]["version"] is None
        assert types["broken"]["schema_sha256"] == _sha(raw)


# ---------------------------------------------------------------------------
# Registry mode
# ---------------------------------------------------------------------------


class TestRegistryMode:
    def test_registry_json_is_authoritative(
        self, client: TestClient, tmp_path: Path,
    ) -> None:
        cdir = tmp_path / "contracts"
        cdir.mkdir()
        schema_bytes = json.dumps({"type": "object"}).encode()
        (cdir / "corpus-snapshot.schema.json").write_bytes(schema_bytes)
        (cdir / "registry.json").write_text(json.dumps({
            "artifact_types": {
                "arxmcp.bridge/corpus-snapshot": {
                    "version": "1.0",
                    "schema": "corpus-snapshot.schema.json",
                },
            },
        }), encoding="utf-8")

        body = client.get("/bridge/contracts").json()
        assert body["registry_status"] == "registry"
        assert body["count"] == 1
        entry = body["artifact_types"]["arxmcp.bridge/corpus-snapshot"]
        assert entry["version"] == "1.0"
        assert entry["schema_sha256"] == _sha(schema_bytes)

    def test_registry_entry_with_missing_schema_serves_null_sha(
        self, client: TestClient, tmp_path: Path,
    ) -> None:
        cdir = tmp_path / "contracts"
        cdir.mkdir()
        (cdir / "registry.json").write_text(json.dumps({
            "artifact_types": {
                "verdict-record": {"version": "2.1", "schema": "missing.json"},
            },
        }), encoding="utf-8")
        entry = client.get("/bridge/contracts").json()["artifact_types"][
            "verdict-record"
        ]
        assert entry["version"] == "2.1"
        assert entry["schema_sha256"] is None

    def test_malformed_registry_falls_back_to_scan(
        self, client: TestClient, tmp_path: Path,
    ) -> None:
        cdir = tmp_path / "contracts"
        cdir.mkdir()
        (cdir / "registry.json").write_text("{broken", encoding="utf-8")
        raw = json.dumps({"type": "object"}).encode()
        (cdir / "ingest-receipt.json").write_bytes(raw)

        body = client.get("/bridge/contracts").json()
        assert body["registry_status"] == "malformed_registry"
        assert body["artifact_types"]["ingest-receipt"]["schema_sha256"] == _sha(raw)


# ---------------------------------------------------------------------------
# stage3/cross-r1 — the handshake serves the top-level envelope block
# ---------------------------------------------------------------------------


class TestEnvelopeInHandshake:
    """The registry's top-level ``envelope`` block (the substrate wrapper --
    the anti-spike-1/2/3 core) MUST be served alongside the artifact types.

    Before the fix the handshake served only ``registry['artifact_types']``,
    so the envelope was never exposed. Since every artifact-type schema
    references the envelope via an opaque URN ``$ref``, an envelope change
    moved ZERO bytes in any served schema -- the consumer's live preflight
    was blind to envelope drift (the running-server-vs-disk divergence the
    handshake exists to catch)."""

    def test_registry_envelope_block_is_served_with_sha(
        self, client: TestClient, tmp_path: Path,
    ) -> None:
        cdir = tmp_path / "contracts"
        cdir.mkdir()
        env_bytes = json.dumps(
            {"type": "object", "required": ["substrate"]}
        ).encode()
        (cdir / "envelope.v1.schema.json").write_bytes(env_bytes)
        art_bytes = json.dumps({"type": "object"}).encode()
        (cdir / "corpus-snapshot.schema.json").write_bytes(art_bytes)
        (cdir / "registry.json").write_text(json.dumps({
            "envelope": {"version": "1.0", "schema": "envelope.v1.schema.json"},
            "artifact_types": {
                "arxmcp.bridge/corpus-snapshot": {
                    "version": "1.0",
                    "schema": "corpus-snapshot.schema.json",
                },
            },
        }), encoding="utf-8")

        body = client.get("/bridge/contracts").json()
        assert body["registry_status"] == "registry"
        # The envelope block is present, versioned, and hash-verifiable.
        env = body["envelope"]
        assert env is not None, (
            "the handshake must serve the registry envelope block -- without "
            "it the consumer preflight cannot verify the substrate wrapper"
        )
        assert env["version"] == "1.0"
        assert env["schema"] == "envelope.v1.schema.json"
        assert env["schema_sha256"] == _sha(env_bytes)

    def test_envelope_sha_tracks_schema_bytes(
        self, client: TestClient, tmp_path: Path,
    ) -> None:
        """The served envelope sha is the sha of the envelope schema file --
        so a byte change to the envelope schema changes the served sha (the
        drift signal the consumer keys on)."""
        cdir = tmp_path / "contracts"
        cdir.mkdir()
        (cdir / "registry.json").write_text(json.dumps({
            "envelope": {"version": "1.0", "schema": "envelope.v1.schema.json"},
            "artifact_types": {},
        }), encoding="utf-8")
        v1 = json.dumps({"type": "object"}).encode()
        (cdir / "envelope.v1.schema.json").write_bytes(v1)
        sha_before = client.get("/bridge/contracts").json()["envelope"][
            "schema_sha256"
        ]
        assert sha_before == _sha(v1)

        # Mutate the envelope schema (add a required substrate field).
        v2 = json.dumps(
            {"type": "object", "required": ["new_substrate_field"]}
        ).encode()
        (cdir / "envelope.v1.schema.json").write_bytes(v2)
        sha_after = client.get("/bridge/contracts").json()["envelope"][
            "schema_sha256"
        ]
        assert sha_after == _sha(v2)
        assert sha_after != sha_before, (
            "an envelope schema byte change must change the served sha -- "
            "this is the drift signal the consumer preflight compares"
        )

    def test_registry_without_envelope_serves_null(
        self, client: TestClient, tmp_path: Path,
    ) -> None:
        """A registry with no envelope block serves ``envelope: null`` (not a
        crash) -- the consumer treats that as a substrate it cannot verify."""
        cdir = tmp_path / "contracts"
        cdir.mkdir()
        (cdir / "registry.json").write_text(json.dumps({
            "artifact_types": {},
        }), encoding="utf-8")
        body = client.get("/bridge/contracts").json()
        assert body["registry_status"] == "registry"
        assert body["envelope"] is None

    def test_scan_mode_serves_null_envelope(
        self, client: TestClient, tmp_path: Path,
    ) -> None:
        """Scan mode (no registry.json) has no authoritative envelope block to
        resolve, so ``envelope`` is null even though the envelope schema file
        is still exposed as a scan artifact-type entry."""
        cdir = tmp_path / "contracts"
        cdir.mkdir()
        (cdir / "envelope.v1.schema.json").write_bytes(
            json.dumps({"type": "object"}).encode()
        )
        body = client.get("/bridge/contracts").json()
        assert body["registry_status"] == "scan"
        assert body["envelope"] is None
        # ...but the schema file is still hashed as a scan entry.
        assert "envelope.v1" in body["artifact_types"]


# ---------------------------------------------------------------------------
# AC-A.4 BP1 guard — adding the endpoint leaves tools/list bytes unchanged
# ---------------------------------------------------------------------------


class TestByteStabilityGuard:
    def test_tools_list_hash_unchanged_after_bridge_route_exercised(
        self, client: TestClient, tmp_path: Path, monkeypatch,
    ) -> None:
        """Spike-S3 shape (RISKS.md §9.2): plain HTTP endpoints must be
        a no-op for the MCP tool schema. Exercise the route, then
        recompute the canonical tools/list hash and compare to the
        pinned constant — the same constant
        tests/test_server_tool_schema.py enforces."""
        assert client.get("/bridge/contracts").status_code == 200

        import server.query_encoder as qe_mod
        from tests.test_server_tool_schema import (
            _build_app_and_list_tools,
            _read_current_pin,
            compute_tool_schema_hash,
        )

        monkeypatch.setattr(qe_mod, "_get_model", lambda: object())
        monkeypatch.setattr(qe_mod, "_get_tokenizer", lambda: object())
        tools = _build_app_and_list_tools(tmp_path)
        pinned_hash, _pinned_version = _read_current_pin()
        assert compute_tool_schema_hash(tools) == pinned_hash, (
            "tools/list bytes drifted — a plain HTTP route addition "
            "must NEVER touch the MCP tool schema (BP1)"
        )
