"""``/api/v1/capabilities`` CRUD tests (stage2/arx-a23, WS-A A2).

Profile management over ``operator_settings`` with immediate cache
invalidation (AC-A.7's runtime mutability at the API layer) and the
AC-A.10 tripwire: a request carrying a raw ``token`` member is 422.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import capabilities as cap
from server.capabilities import hash_token, set_capability_settings_store
from server.routes.capabilities import router as capabilities_router


class _FakeSettingsStore:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value


def _client(store: _FakeSettingsStore | None = None) -> TestClient:
    if store is not None:
        set_capability_settings_store(store, cache_ttl_s=3600.0)
    app = FastAPI()
    app.include_router(capabilities_router, prefix="/api/v1")
    return TestClient(app)


class TestListProfiles:
    def test_synthesized_default_always_listed(self) -> None:
        client = _client(_FakeSettingsStore())
        body = client.get("/api/v1/capabilities/profiles").json()
        assert body["format_version"] == 1
        names = [p["name"] for p in body["items"]]
        assert "default" in names
        default = next(p for p in body["items"] if p["name"] == "default")
        assert default["enabled"] is True
        assert default["tools"] is None
        assert default["notebooks"] is None


class TestUpsertProfile:
    def test_upsert_and_readback(self) -> None:
        store = _FakeSettingsStore()
        client = _client(store)
        digest = hash_token("tok")
        r = client.put(
            "/api/v1/capabilities/profiles/website",
            json={
                "token_sha256": digest,
                "tools": ["search_papers"],
                "caps": {"search_papers": 5},
                "notebooks": ["bridgeland-stability"],
            },
        )
        assert r.status_code == 200, r.text
        body = client.get("/api/v1/capabilities/profiles").json()
        row = next(p for p in body["items"] if p["name"] == "website")
        assert row["token_sha256"] == digest
        assert row["tools"] == ["search_papers"]
        assert row["caps"] == {"search_papers": 5}
        assert row["notebooks"] == ["bridgeland-stability"]

    def test_write_invalidates_cache_immediately(self) -> None:
        """The TTL is 1 h in this fixture — only the CRUD surface's
        inline invalidation can make the write visible now (AC-A.7)."""
        store = _FakeSettingsStore()
        client = _client(store)
        # Warm the cache.
        asyncio.run(cap.get_profiles())
        client.put(
            "/api/v1/capabilities/profiles/hot",
            json={"caps": {"get_chunk": 9}},
        )
        profiles = asyncio.run(cap.get_profiles())
        assert "hot" in profiles
        assert profiles["hot"].tool_caps == {"get_chunk": 9}

    def test_raw_token_member_rejected_422(self) -> None:
        """AC-A.10 tripwire: the API refuses raw token values."""
        client = _client(_FakeSettingsStore())
        r = client.put(
            "/api/v1/capabilities/profiles/leaky",
            json={"token": "raw-secret-value"},
        )
        assert r.status_code == 422

    def test_malformed_token_hash_rejected(self) -> None:
        client = _client(_FakeSettingsStore())
        r = client.put(
            "/api/v1/capabilities/profiles/p",
            json={"token_sha256": "not-a-hash"},
        )
        assert r.status_code == 422
        assert "never the token value" in r.json()["detail"]

    def test_negative_cap_rejected(self) -> None:
        client = _client(_FakeSettingsStore())
        r = client.put(
            "/api/v1/capabilities/profiles/p",
            json={"caps": {"search_papers": -3}},
        )
        assert r.status_code == 422

    def test_bad_profile_name_rejected(self) -> None:
        client = _client(_FakeSettingsStore())
        r = client.put(
            "/api/v1/capabilities/profiles/Bad_Name!",
            json={},
        )
        assert r.status_code == 422

    def test_unbound_store_is_503(self) -> None:
        client = _client(None)  # reset fixture leaves the store unbound
        r = client.put("/api/v1/capabilities/profiles/p", json={})
        assert r.status_code == 503


class TestDeleteProfile:
    def test_delete_then_404(self) -> None:
        store = _FakeSettingsStore()
        client = _client(store)
        client.put("/api/v1/capabilities/profiles/gone", json={})
        assert client.delete("/api/v1/capabilities/profiles/gone").status_code == 204
        assert client.delete("/api/v1/capabilities/profiles/gone").status_code == 404
        stored = json.loads(store.data[cap.CAPABILITY_PROFILES_KEY])
        assert "gone" not in stored["profiles"]

    def test_deleting_operator_default_restores_synthesized(self) -> None:
        store = _FakeSettingsStore()
        client = _client(store)
        client.put(
            "/api/v1/capabilities/profiles/default",
            json={"tools": []},
        )
        row = next(
            p for p in client.get("/api/v1/capabilities/profiles").json()["items"]
            if p["name"] == "default"
        )
        assert row["tools"] == []  # locked down
        client.delete("/api/v1/capabilities/profiles/default")
        row = next(
            p for p in client.get("/api/v1/capabilities/profiles").json()["items"]
            if p["name"] == "default"
        )
        assert row["tools"] is None  # synthesized permissive default is back
