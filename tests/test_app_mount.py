"""Tests for the /app SPA static mount + its stricter CSP (stage2/arx-b1).

Coverage matrix (acceptance-criteria.md AC-B.1 + AC-B.2 server half):

- TestSpaFilesMount      — index at /app/, history-API fallback for
                           extensionless client routes, honest 404 for
                           missing assets, real assets served.
- TestAppCsp             — /app responses carry
                           CONTENT_SECURITY_POLICY_APP; script-src is
                           'self' with NO unsafe-inline; strictly
                           stricter than the /ui/ policy; prefix
                           scoping (/appOTHER gets nothing).
- TestMountGuard         — missing dist/ skips the mount (warning, not
                           a crash); the committed real dist exists.

Harness: minimal FastAPI app + SecurityHeadersMiddleware + the real
mount code against a tmp_path fake dist (no lifespan, no model loads —
the tests/test_api_v1.py pattern).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.middleware import (
    CONTENT_SECURITY_POLICY_APP,
    CONTENT_SECURITY_POLICY_UI,
    SecurityHeadersMiddleware,
)
from server.spa import FRONTEND_APP_DIST, SPAFiles, mount_frontend_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_dist(tmp_path: Path) -> Path:
    """A minimal Vite-shaped dist tree."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><html><head><title>arXMCP console</title>"
        '<script type="module" src="/app/assets/index-abc.js"></script>'
        "</head><body><div id=\"root\"></div></body></html>",
        encoding="utf-8",
    )
    (dist / "assets" / "index-abc.js").write_text("console.log('m0');", encoding="utf-8")
    (dist / "assets" / "index-abc.css").write_text(":root{--radius:2px}", encoding="utf-8")
    return dist


@pytest.fixture()
def client(fake_dist: Path) -> TestClient:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ui/")
    async def ui_page() -> dict[str, str]:  # pragma: no cover — trivial
        return {"surface": "ui"}

    @app.get("/appendix")
    async def not_the_spa() -> dict[str, str]:  # pragma: no cover — trivial
        return {"surface": "other"}

    mounted = mount_frontend_app(app, dist_dir=fake_dist)
    if not mounted:  # fail loud — the fixture guarantees index.html
        raise RuntimeError("fixture dist failed to mount")
    return TestClient(app)


# ---------------------------------------------------------------------------
# TestSpaFilesMount
# ---------------------------------------------------------------------------


class TestSpaFilesMount:
    def test_index_served_at_app_root(self, client: TestClient) -> None:
        r = client.get("/app/")
        if r.status_code != 200:
            raise AssertionError(f"/app/ -> {r.status_code}")
        if "arXMCP console" not in r.text:
            raise AssertionError("index.html body not served at /app/")

    def test_history_fallback_serves_index_for_client_routes(self, client: TestClient) -> None:
        """A reload on a client-side route must get index.html (AC-B.1)."""
        r = client.get("/app/specimen")
        if r.status_code != 200 or "arXMCP console" not in r.text:
            raise AssertionError(f"client route fallback broken: {r.status_code}")
        # Nested client routes too (future notebook detail).
        r2 = client.get("/app/notebooks/bridgeland-stability")
        if r2.status_code != 200 or "arXMCP console" not in r2.text:
            raise AssertionError(f"nested client route fallback broken: {r2.status_code}")

    def test_missing_asset_is_honest_404(self, client: TestClient) -> None:
        """Paths WITH an extension are asset lookups — no index masquerade."""
        r = client.get("/app/assets/gone-def.js")
        if r.status_code != 404:
            raise AssertionError(f"missing asset should 404, got {r.status_code}")

    def test_real_asset_served(self, client: TestClient) -> None:
        r = client.get("/app/assets/index-abc.js")
        if r.status_code != 200 or "m0" not in r.text:
            raise AssertionError("bundled asset not served")

    def test_route_path_heuristic(self) -> None:
        if not SPAFiles._is_route_path("specimen"):
            raise AssertionError("extensionless path must be a route")
        if not SPAFiles._is_route_path("notebooks/some-slug"):
            raise AssertionError("nested extensionless path must be a route")
        if SPAFiles._is_route_path("assets/index-abc.js"):
            raise AssertionError("asset path must NOT be a route")


# ---------------------------------------------------------------------------
# TestAppCsp
# ---------------------------------------------------------------------------


class TestAppCsp:
    def test_app_surface_carries_app_csp(self, client: TestClient) -> None:
        for path in ("/app/", "/app/specimen", "/app/assets/index-abc.js"):
            csp = client.get(path).headers.get("content-security-policy")
            if csp != CONTENT_SECURITY_POLICY_APP.decode():
                raise AssertionError(f"{path}: wrong CSP: {csp!r}")

    def test_app_csp_script_src_self_without_unsafe_inline(self) -> None:
        """AC-B.2: script-src 'self', NO unsafe-inline anywhere in it."""
        directives = {
            d.strip().split(" ")[0]: d.strip()
            for d in CONTENT_SECURITY_POLICY_APP.decode().split(";")
            if d.strip()
        }
        if directives.get("script-src") != "script-src 'self'":
            raise AssertionError(f"script-src drifted: {directives.get('script-src')!r}")

    def test_app_csp_strictly_stricter_than_ui(self) -> None:
        """The /ui/ policy carries script-src 'unsafe-inline'; /app must not."""
        ui = CONTENT_SECURITY_POLICY_UI.decode()
        app_csp = CONTENT_SECURITY_POLICY_APP.decode()
        if "script-src 'self' 'unsafe-inline'" not in ui:
            raise AssertionError("UI CSP baseline changed; re-evaluate this comparison")
        if "'unsafe-inline'" in app_csp.split("style-src")[0]:
            raise AssertionError("unsafe-inline leaked into /app script-src region")
        for directive in ("base-uri 'none'", "font-src 'self'", "connect-src 'self'"):
            if directive not in app_csp:
                raise AssertionError(f"/app CSP lost {directive!r}")

    def test_prefix_scoping(self, client: TestClient) -> None:
        """/appendix is NOT the SPA surface; /ui/ keeps the legacy CSP."""
        other = client.get("/appendix").headers.get("content-security-policy")
        if other is not None:
            raise AssertionError(f"/appendix must carry no CSP, got {other!r}")
        ui = client.get("/ui/").headers.get("content-security-policy")
        if ui != CONTENT_SECURITY_POLICY_UI.decode():
            raise AssertionError(f"/ui/ CSP regressed: {ui!r}")


# ---------------------------------------------------------------------------
# TestMountGuard
# ---------------------------------------------------------------------------


class TestMountGuard:
    def test_missing_dist_skips_mount(self, tmp_path: Path) -> None:
        app = FastAPI()
        mounted = mount_frontend_app(app, dist_dir=tmp_path / "nowhere")
        if mounted:
            raise AssertionError("mount must be skipped when dist is absent")
        # Server still functional.
        client = TestClient(app)
        if client.get("/app/").status_code != 404:
            raise AssertionError("absent SPA should 404, not crash")

    def test_committed_dist_exists(self) -> None:
        """The repo commits frontend-app/dist so the runtime needs no Node
        (D1 ADR) and the design gates always have compiled CSS to read."""
        if not (FRONTEND_APP_DIST / "index.html").is_file():
            raise AssertionError(
                "frontend-app/dist/index.html missing - rebuild and commit: "
                "cd frontend-app && npm ci && npm run build"
            )
        css = list((FRONTEND_APP_DIST / "assets").glob("*.css"))
        if not css:
            raise AssertionError("no compiled CSS in frontend-app/dist/assets")


# ---------------------------------------------------------------------------
# TestAppAssetsByteCapExemption (stage2/arx-b2 fix pass)
# ---------------------------------------------------------------------------


BYTE_CAP = 256 * 1024


def _build_real_app_client(tmp_path: Path, monkeypatch) -> TestClient:
    """A TestClient over the REAL ``create_app(cfg)`` middleware stack.

    Mirrors ``tests/security/test_sec_fetch_site_carveout.py::
    _build_test_client``. The lifespan is NOT entered (plain
    ``TestClient(app)``, no context manager), so no model/LanceDB
    loads happen — the StaticFiles mount and the full middleware
    chain (SecurityHeaders → SecFetchSite → Origin → Host →
    RequestBodySizeLimit → SessionCap → BodySizeCap) are what these
    tests exercise.
    """
    from server.config import Config
    from server.main import create_app

    monkeypatch.setenv("ARXMCP_LANCEDB_PATH", str(tmp_path / "lancedb-empty"))
    monkeypatch.delenv("ARXMCP_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("ARXMCP_UNSAFE_NETWORK_BIND", raising=False)
    monkeypatch.delenv("ARXMCP_CONTACT_EMAIL", raising=False)
    cfg = Config()
    return TestClient(create_app(cfg))


class TestAppAssetsByteCapExemption:
    """arx-b2 fix pass (verification finding 1, MAJOR): /app assets
    larger than the 256 KiB ``BodySizeCapMiddleware`` cap were
    truncated mid-stream on the real server — the brief-mandated
    self-hosted STIX Two Math fonts (403,344 / 418,048 B) never
    loaded, every math-bearing surface logged 2 console errors
    (``ERR_CONTENT_LENGTH_MISMATCH``) + 2 server-side ASGI
    protocol-violation exceptions, and AC-B.24's zero-console-errors
    gate failed live while the hermetic harness (which mounts only
    SecurityHeadersMiddleware) stayed green. ``/app/assets`` now
    joins ``_BYTE_CAP_EXEMPT_PREFIXES`` with the same narrowing
    discipline as the m8-rect-F4 ``/ui/static`` exemption.
    """

    def test_over_cap_dist_assets_exist(self) -> None:
        """The committed dist MUST contain over-cap assets (the STIX
        Two Math fonts) — otherwise the delivery test below proves
        nothing. If a future font subset drops them all under the
        cap, this test flags the delivery test for re-evaluation
        rather than letting it rot into a vacuous pass."""
        over_cap = [
            p
            for p in (FRONTEND_APP_DIST / "assets").glob("*")
            if p.is_file() and p.stat().st_size > BYTE_CAP
        ]
        if not over_cap:
            raise AssertionError(
                "no committed /app asset exceeds the 256 KiB cap; "
                "TestAppAssetsByteCapExemption::test_over_cap_asset_"
                "delivered_in_full is now vacuous — re-point it at a "
                "real over-cap asset or retire the pair together"
            )

    def test_over_cap_asset_delivered_in_full(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """EVERY over-cap committed asset is delivered byte-complete
        through the real middleware stack: status 200, body length
        == content-length header == on-disk size. Before the fix the
        middleware flushed the buffered start event (first 64 KiB
        chunk under the cap), then aborted mid-stream — an ASGI
        protocol violation surfacing as a truncated body."""
        client = _build_real_app_client(tmp_path, monkeypatch)
        over_cap = [
            p
            for p in (FRONTEND_APP_DIST / "assets").glob("*")
            if p.is_file() and p.stat().st_size > BYTE_CAP
        ]
        for asset in over_cap:
            r = client.get(f"/app/assets/{asset.name}")
            if r.status_code != 200:
                raise AssertionError(
                    f"/app/assets/{asset.name} -> {r.status_code} "
                    f"(expected 200 through the real create_app stack)"
                )
            declared = int(r.headers["content-length"])
            on_disk = asset.stat().st_size
            if declared != on_disk:
                raise AssertionError(
                    f"{asset.name}: content-length {declared} != "
                    f"on-disk size {on_disk}"
                )
            if len(r.content) != declared:
                raise AssertionError(
                    f"{asset.name}: delivered {len(r.content)} of "
                    f"{declared} bytes — truncated by the byte cap"
                )
            if len(r.content) <= BYTE_CAP:
                raise AssertionError(
                    f"{asset.name}: {len(r.content)} bytes does not "
                    f"exceed the cap — vacuous delivery check"
                )

    def test_exemption_is_narrow(self) -> None:
        """Prefix discipline (FM-3 parity): ONLY /app/assets is
        exempt. The /app HTML shell, the history-API fallback, sibling
        prefixes, and every JSON surface stay under the cap as
        defense-in-depth."""
        from server.main import _is_exempt_path

        if not _is_exempt_path("/app/assets/stix.woff2"):
            raise AssertionError("/app/assets/* must be exempt")
        if not _is_exempt_path("/app/assets"):
            raise AssertionError("/app/assets (exact) must be exempt")
        for capped in (
            "/app/",
            "/app/specimen/math",
            "/app/index.html",
            "/app/assetsX/evil.bin",
            "/appOTHER/assets/x.js",
            "/api/v1/notebooks",
            "/ui/api/notebooks",
        ):
            if _is_exempt_path(capped):
                raise AssertionError(f"{capped} must NOT be exempt")
