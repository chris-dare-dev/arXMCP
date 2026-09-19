"""Offline OpenAPI dump — IF-1 (stage2/arx-a1; acceptance AC-A.2).

- TestDeterminism    — two consecutive renders are byte-identical.
- TestCommittedFile  — the committed openapi.json matches a fresh
                       render (fails with a "run make openapi" hint
                       when the surface drifted).
- TestScope          — /api/v1 + /bridge/contracts + probes are in;
                       the legacy /ui/api surface and /mcp are OUT.
- TestRouterParity   — every route registered on the /api/v1 router
                       appears in the dump (drift guard between
                       tools/dump_openapi.py's doc-app and the real
                       app factory's mounts).
- TestThreat4Runtime — the runtime app still refuses /openapi.json,
                       /docs, /redoc (the dump is the ONLY schema
                       channel).
"""

from __future__ import annotations

from pathlib import Path

from tools.dump_openapi import (
    OPENAPI_PATH,
    build_openapi_document,
    render_openapi_bytes,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestDeterminism:
    def test_two_renders_byte_identical(self) -> None:
        assert render_openapi_bytes() == render_openapi_bytes()

    def test_render_ends_with_newline_and_is_ascii(self) -> None:
        raw = render_openapi_bytes()
        assert raw.endswith(b"\n")
        raw.decode("ascii")  # raises on non-ASCII


class TestCommittedFile:
    def test_committed_dump_is_current(self) -> None:
        assert OPENAPI_PATH.is_file(), (
            "openapi.json missing — run `make openapi` (or `python -m "
            "tools.dump_openapi`) and commit the result"
        )
        assert OPENAPI_PATH.read_bytes() == render_openapi_bytes(), (
            "openapi.json is STALE — the /api/v1 surface changed; run "
            "`make openapi` and commit the regenerated file (IF-1 "
            "consumers generate typed clients from it)"
        )


class TestScope:
    def test_expected_surfaces_present(self) -> None:
        paths = set(build_openapi_document()["paths"])
        for expected in (
            "/healthz", "/readyz", "/status",
            "/bridge/contracts",
            "/api/v1/notebooks",
            "/api/v1/notebooks/{slug}",
            "/api/v1/notebooks/{slug}/papers",
            "/api/v1/notebooks/{slug}/papers/upload",
            "/api/v1/notebooks/{slug}/ingest",
            "/api/v1/notebooks/{slug}/ingest/latest",
            "/api/v1/notebooks/{slug}/export",
            "/api/v1/notebooks/{slug}/health",
            "/api/v1/notebooks/{slug}/reconcile-marker",
            "/api/v1/admin/repair-registry",
        ):
            assert expected in paths, expected

    def test_legacy_and_agent_surfaces_excluded(self) -> None:
        paths = build_openapi_document()["paths"]
        assert not any(p.startswith("/ui") for p in paths)
        assert not any(p.startswith("/mcp") for p in paths)

    def test_loopback_server_entry(self) -> None:
        doc = build_openapi_document()
        assert doc["servers"] == [{"url": "http://127.0.0.1:7733"}]


class TestRouterParity:
    def test_every_api_v1_route_is_in_the_dump(self) -> None:
        """Drift guard: tools/dump_openapi.py assembles its own app
        from the routers; if a route lands on the router it MUST show
        up in the dump."""
        import re

        from fastapi.routing import APIRoute

        from server.routes.api_v1 import router as api_v1_router

        dumped = set(build_openapi_document()["paths"])
        for route in api_v1_router.routes:
            if isinstance(route, APIRoute):
                # OpenAPI drops Starlette converter suffixes:
                # ``{paper_id:path}`` renders as ``{paper_id}``.
                openapi_path = re.sub(r"\{(\w+):\w+\}", r"{\1}", route.path)
                assert f"/api/v1{openapi_path}" in dumped, route.path


class TestThreat4Runtime:
    def test_runtime_schema_endpoints_stay_disabled(
        self, tmp_path, monkeypatch,
    ) -> None:
        """AC-A.2 runtime half: GET /openapi.json, /docs, /redoc all
        404 on the real app factory (openapi_url=None preserved)."""
        from fastapi.testclient import TestClient

        import server.query_encoder as qe_mod
        from server.config import Config
        from server.health import reset_metrics_for_tests
        from server.main import create_app
        from server.tools import reset_resources_for_tests

        monkeypatch.setattr(qe_mod, "_get_model", lambda: object())
        monkeypatch.setattr(qe_mod, "_get_tokenizer", lambda: object())
        reset_resources_for_tests()
        reset_metrics_for_tests()
        cfg = Config(lancedb_path=tmp_path / "no_lancedb_needed")
        app = create_app(cfg)
        # No lifespan entry (TestClient without context manager does
        # not run startup) — route-table checks only.
        client = TestClient(app)
        for path in ("/openapi.json", "/docs", "/redoc"):
            assert client.get(path).status_code == 404, path

    def test_app_factory_pins_openapi_url_none(self, tmp_path, monkeypatch) -> None:
        import server.query_encoder as qe_mod
        from server.config import Config
        from server.health import reset_metrics_for_tests
        from server.main import create_app
        from server.tools import reset_resources_for_tests

        monkeypatch.setattr(qe_mod, "_get_model", lambda: object())
        monkeypatch.setattr(qe_mod, "_get_tokenizer", lambda: object())
        reset_resources_for_tests()
        reset_metrics_for_tests()
        app = create_app(Config(lancedb_path=tmp_path / "nope"))
        assert app.openapi_url is None
        assert app.docs_url is None
        assert app.redoc_url is None
