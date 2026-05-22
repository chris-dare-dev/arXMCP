"""Tests for the /ui/* SecFetchSite carve-out (m7 AC #4).

The default ``SecFetchSiteMiddleware`` 403s any ``Sec-Fetch-Site``
value other than ``none`` or absent — this is the Threat-5
DNS-rebinding defense for the MCP surface. m7 adds an
``exempt_prefixes=("/ui",)`` carve-out so the htmx UI (m8) can
make same-origin fetch() POSTs to ``/ui/api/notebooks`` without
the browser-injected ``Sec-Fetch-Site: same-origin`` header
triggering a 403.

These tests pin the carve-out invariants:

1. ``/mcp`` REJECTS ``Sec-Fetch-Site: same-origin`` (existing
   behavior preserved — the DNS-rebinding defense still applies on
   the MCP surface).
2. ``/ui/api/notebooks`` ACCEPTS ``Sec-Fetch-Site: same-origin``
   (the carve-out fires).
3. The carve-out uses PREFIX matching, not substring — a request
   to ``/uiOTHER`` or ``/evil-ui/path`` MUST still be rejected
   (FM-3 from m7 synthesis).
4. The carve-out is keyed on ``scope["path"]``; query strings,
   methods, and headers don't bypass it.

Pattern mirrors ``tests/security/test_origin_binding.py``: a
``_build_test_client`` helper builds a real ``create_app(cfg)``
TestClient against a tmp_path LanceDB so the lifespan fails
cleanly (we only need the middleware chain on rejected requests,
not the actual handler dispatch — the response status is what we
assert).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.config import Config
from server.main import create_app
from server.middleware import SecFetchSiteMiddleware


def _build_test_client(tmp_path: Path, monkeypatch) -> TestClient:
    """Construct a TestClient against a real ``create_app``.

    Mirrors ``tests/security/test_origin_binding.py::_build_test_client``
    — the lifespan tries to load LanceDB and may fail; we only
    assert on response status codes that short-circuit before the
    handler dispatch, so lifespan failure is acceptable.
    """
    lancedb_path = tmp_path / "lancedb-empty"
    monkeypatch.setenv("ARXMCP_LANCEDB_PATH", str(lancedb_path))
    monkeypatch.delenv("ARXMCP_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("ARXMCP_UNSAFE_NETWORK_BIND", raising=False)
    monkeypatch.delenv("ARXMCP_CONTACT_EMAIL", raising=False)
    cfg = Config()
    app = create_app(cfg)
    return TestClient(app)


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    return _build_test_client(tmp_path, monkeypatch)


class TestMcpStillRejectsSameOrigin:
    """The carve-out MUST NOT bleed onto /mcp — the DNS-rebinding
    defense still applies there (per .claude/notes/08-security-
    observability-ops.md Threat 5)."""

    def test_mcp_path_rejects_same_origin(self, client: TestClient) -> None:
        # Use /healthz as a stand-in — same middleware chain, no
        # session-management overhead. The MCP path itself requires
        # the session init handshake which is not relevant here.
        # The earlier TestSecFetchSiteRejection class in
        # test_origin_binding.py asserts this on /healthz directly.
        # Here we assert that the SAME header on the SAME middleware
        # is still rejected when the path is NOT under /ui.
        response = client.get(
            "/healthz", headers={"Sec-Fetch-Site": "same-origin"}
        )
        assert response.status_code == 403
        assert response.json()["error"] == "sec_fetch_site_forbidden"


class TestUiCarveoutAcceptsSameOrigin:
    """The /ui/* prefix is exempt — same-origin htmx posts pass."""

    def test_ui_api_path_accepts_same_origin(
        self, client: TestClient,
    ) -> None:
        """A same-origin POST to /ui/api/notebooks/<missing-slug>/papers
        must NOT be 403'd by SecFetchSiteMiddleware. The downstream
        handler may return 503 (lifespan failed) or 404 (notebook
        not found) — anything BUT 403 from sec_fetch_site_forbidden
        proves the carve-out fired."""
        response = client.post(
            "/ui/api/notebooks",
            headers={"Sec-Fetch-Site": "same-origin"},
            json={"slug": "demo-nb"},
        )
        # If the response is 403, the body MUST NOT name
        # sec_fetch_site_forbidden — otherwise the carve-out is broken.
        if response.status_code == 403:
            body = response.json()
            assert body.get("error") != "sec_fetch_site_forbidden", (
                "SecFetchSite carve-out for /ui/* did not fire — "
                "got 403 sec_fetch_site_forbidden on /ui/api/notebooks"
            )

    def test_ui_api_path_rejects_cross_site(
        self, client: TestClient,
    ) -> None:
        """m7 rect F1: the carve-out RELAXES the allow-set to
        ``{none, same-origin}`` — it is NOT a full bypass.
        ``cross-site`` POSTs (forged by another local app on a
        different port via a browser-mediated CSRF) MUST still be
        403'd on ``/ui/*``. Without this guard, any other localhost
        web service (a dev server, a Flask script on :5000, a
        JupyterLab on :8888) could create/delete notebooks on the
        operator's behalf."""
        response = client.post(
            "/ui/api/notebooks",
            headers={"Sec-Fetch-Site": "cross-site"},
            json={"slug": "csrf-victim"},
        )
        assert response.status_code == 403
        assert response.json()["error"] == "sec_fetch_site_forbidden"

    def test_ui_api_path_rejects_same_site(
        self, client: TestClient,
    ) -> None:
        """Same-site (same eTLD+1, different origin) is also
        rejected on /ui/* — the carve-out is for the in-page UI's
        same-origin htmx, not any browser-mediated traffic."""
        response = client.post(
            "/ui/api/notebooks",
            headers={"Sec-Fetch-Site": "same-site"},
            json={"slug": "demo-nb"},
        )
        assert response.status_code == 403
        assert response.json()["error"] == "sec_fetch_site_forbidden"


class TestPrefixVsSubstring:
    """FM-3: the carve-out must use prefix matching, not substring.
    A path like /evil-ui/foo or /uiOTHER must NOT bypass the check."""

    def test_uioother_path_not_exempt(self, client: TestClient) -> None:
        """A path that begins with 'ui' but isn't /ui or /ui/* must
        still hit the rejection."""
        # No such route exists, but the middleware fires BEFORE
        # routing. If the carve-out used substring matching, this
        # request would pass through. We assert that the
        # middleware's 403 either fires (proving the prefix check
        # is correct) OR a non-403 fires (meaning the route doesn't
        # exist, which is also fine — what matters is the
        # middleware doesn't grant exemption based on substring).
        #
        # The TestClient with a same-origin header on /uiOTHER:
        # - If carve-out is BUGGY substring: 404 (route not found,
        #   carve-out passed it through to the router)
        # - If carve-out is CORRECT prefix: 403 sec_fetch_site_forbidden
        response = client.get(
            "/uiOTHER",
            headers={"Sec-Fetch-Site": "same-origin"},
        )
        assert response.status_code == 403, (
            f"prefix-matching is broken — /uiOTHER got "
            f"{response.status_code}; expected 403 because /uiOTHER "
            f"is NOT under the /ui prefix"
        )
        assert response.json()["error"] == "sec_fetch_site_forbidden"

    def test_evil_ui_path_not_exempt(self, client: TestClient) -> None:
        """A path like /evil-ui/foo contains 'ui' as a substring but
        does NOT match /ui as a prefix — carve-out must NOT fire."""
        response = client.get(
            "/evil-ui/foo",
            headers={"Sec-Fetch-Site": "same-origin"},
        )
        assert response.status_code == 403
        assert response.json()["error"] == "sec_fetch_site_forbidden"


# ---------------------------------------------------------------------------
# Direct middleware unit tests (no TestClient)
# ---------------------------------------------------------------------------


class TestSecFetchSiteMiddlewareExemptPrefixesUnit:
    """Direct unit tests of the exempt_prefixes argument — verifies
    the constructor contract without the full app stack."""

    def test_default_no_exempt_prefixes(self) -> None:
        """The default constructor (no kwarg) preserves backward
        compat — existing call sites that pass only `app` still
        get the original behavior."""
        from unittest.mock import MagicMock
        mw = SecFetchSiteMiddleware(app=MagicMock())
        assert mw._exempt_prefixes == ()

    def test_exempt_prefixes_stored(self) -> None:
        from unittest.mock import MagicMock
        mw = SecFetchSiteMiddleware(
            app=MagicMock(), exempt_prefixes=("/ui", "/admin"),
        )
        assert mw._exempt_prefixes == ("/ui", "/admin")
