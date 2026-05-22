"""Tests for the m8 ``RequestBodySizeLimitMiddleware.prefix_caps``
extension (AC #4).

The default cap is 1 MB; the m8 carve-out raises it to 10 MB only
for paths under ``/ui/api/notebooks`` so the ar5iv HTML upload
endpoint can accept files larger than 1 MB. Every OTHER path
keeps the default cap.

Coverage matrix:

- TestDefaultCap                  — default 1 MB cap still applies elsewhere
- TestPrefixCapsRaisesCapForUi    — 10 MB cap on /ui/api/notebooks/*
- TestPrefixMatchNotSubstring     — /uiOTHER and /evil-ui/x stay at the default cap
- TestExceedingTheRaisedCap       — even 10 MB+ uploads rejected with 413
- TestEffectiveMaxBytesHelper     — direct unit test of _effective_max_bytes

These tests use a minimal pure-ASGI app + the middleware directly
(no FastAPI lifespan / Resources needed)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.middleware import (
    REQUEST_BODY_MAX_BYTES,
    RequestBodySizeLimitMiddleware,
)


def _make_echo_app(prefix_caps: dict[str, int] | None = None) -> FastAPI:
    """Build a tiny app that echoes the request body length back."""
    app = FastAPI()

    @app.post("/{path:path}")
    async def echo(path: str, body: dict | None = None) -> dict:
        return {"ok": True, "path": path}

    app.add_middleware(
        RequestBodySizeLimitMiddleware,
        prefix_caps=prefix_caps,
    )
    return app


@pytest.fixture
def default_client() -> Iterator[TestClient]:
    """Client with NO prefix_caps — every path uses the 1 MB default."""
    app = _make_echo_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def carveout_client() -> Iterator[TestClient]:
    """Client with the m8 carve-out: 10 MB on /ui/api/notebooks."""
    app = _make_echo_app(prefix_caps={
        "/ui/api/notebooks": 10 * 1024 * 1024,
    })
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Default cap (1 MB) still applies on every path when no carve-out
# ---------------------------------------------------------------------------


class TestDefaultCap:
    def test_small_body_passes(self, default_client: TestClient) -> None:
        r = default_client.post("/foo", json={"small": "body"})
        assert r.status_code == 200

    def test_2mb_body_rejected_with_413(
        self, default_client: TestClient,
    ) -> None:
        payload = "x" * (2 * 1024 * 1024)  # 2 MB string
        r = default_client.post(
            "/foo", json={"data": payload},
        )
        assert r.status_code == 413
        body = r.json()
        assert body["error"] == "payload_too_large"
        assert body["max_bytes"] == REQUEST_BODY_MAX_BYTES


# ---------------------------------------------------------------------------
# Carve-out raises cap on /ui/api/notebooks
# ---------------------------------------------------------------------------


class TestPrefixCapsRaisesCapForUi:
    def test_3mb_body_to_ui_api_notebooks_passes(
        self, carveout_client: TestClient,
    ) -> None:
        """3 MB POST to /ui/api/notebooks/<...> passes (under 10 MB cap)."""
        payload = "x" * (3 * 1024 * 1024)
        r = carveout_client.post(
            "/ui/api/notebooks/foo/papers/upload",
            json={"data": payload},
        )
        # The echo handler accepts anything; the middleware passes through.
        assert r.status_code == 200

    def test_3mb_body_to_non_ui_path_still_rejected(
        self, carveout_client: TestClient,
    ) -> None:
        """A 3 MB POST to a path OUTSIDE the carve-out still hits
        the 1 MB default cap → 413."""
        payload = "x" * (3 * 1024 * 1024)
        r = carveout_client.post(
            "/some/other/path", json={"data": payload},
        )
        assert r.status_code == 413
        assert r.json()["max_bytes"] == REQUEST_BODY_MAX_BYTES


# ---------------------------------------------------------------------------
# Prefix match (NOT substring) — FM-3 parity with m7 carve-out
# ---------------------------------------------------------------------------


class TestPrefixMatchNotSubstring:
    """A request to ``/uiOTHER`` or ``/evil-ui/x`` must NOT inherit
    the /ui carve-out (would defeat the purpose). Prefix-match form
    is ``path == p or path.startswith(p + "/")``."""

    def test_uiother_path_uses_default_cap(self) -> None:
        """A path that begins with 'ui' as substring of a different
        path name must NOT match. We use the more-specific
        '/ui/api/notebooks' prefix to make this concrete."""
        app = _make_echo_app(prefix_caps={
            "/ui/api/notebooks": 10 * 1024 * 1024,
        })
        with TestClient(app) as client:
            payload = "x" * (3 * 1024 * 1024)
            # /ui/api/notebooksOTHER must NOT match — would only match
            # under broken substring/contains semantics.
            r = client.post(
                "/ui/api/notebooksOTHER",
                json={"data": payload},
            )
            assert r.status_code == 413, (
                "prefix matching is broken: /ui/api/notebooksOTHER "
                "should NOT inherit the /ui/api/notebooks carve-out"
            )
            assert r.json()["max_bytes"] == REQUEST_BODY_MAX_BYTES

    def test_exact_prefix_match_works(self) -> None:
        """``path == prefix`` (no trailing slash) must match too."""
        app = _make_echo_app(prefix_caps={
            "/ui/api/notebooks": 10 * 1024 * 1024,
        })
        with TestClient(app) as client:
            payload = "x" * (3 * 1024 * 1024)
            r = client.post(
                "/ui/api/notebooks",
                json={"data": payload},
            )
            assert r.status_code == 200, (
                "exact prefix match should hit the carve-out cap"
            )


# ---------------------------------------------------------------------------
# Exceeding the raised cap
# ---------------------------------------------------------------------------


class TestExceedingTheRaisedCap:
    def test_12mb_body_to_carveout_path_rejected(
        self, carveout_client: TestClient,
    ) -> None:
        """Even with the 10 MB carve-out, a 12 MB body is rejected."""
        payload = "x" * (12 * 1024 * 1024)
        r = carveout_client.post(
            "/ui/api/notebooks/foo/papers/upload",
            json={"data": payload},
        )
        assert r.status_code == 413
        assert r.json()["max_bytes"] == 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# Unit test of the helper
# ---------------------------------------------------------------------------


class TestEffectiveMaxBytesHelper:
    def test_no_prefix_caps_uses_default(self) -> None:
        from unittest.mock import MagicMock
        mw = RequestBodySizeLimitMiddleware(app=MagicMock())
        assert mw._effective_max_bytes("/anything") == REQUEST_BODY_MAX_BYTES

    def test_matching_prefix_uses_override(self) -> None:
        from unittest.mock import MagicMock
        mw = RequestBodySizeLimitMiddleware(
            app=MagicMock(),
            prefix_caps={"/ui": 5 * 1024 * 1024},
        )
        assert mw._effective_max_bytes("/ui") == 5 * 1024 * 1024
        assert mw._effective_max_bytes("/ui/api/notebooks") == 5 * 1024 * 1024
        assert mw._effective_max_bytes("/ui/static/htmx.min.js") == 5 * 1024 * 1024

    def test_non_matching_prefix_uses_default(self) -> None:
        from unittest.mock import MagicMock
        mw = RequestBodySizeLimitMiddleware(
            app=MagicMock(),
            prefix_caps={"/ui": 5 * 1024 * 1024},
        )
        assert mw._effective_max_bytes("/mcp") == REQUEST_BODY_MAX_BYTES
        assert mw._effective_max_bytes("/uiOTHER") == REQUEST_BODY_MAX_BYTES
        assert mw._effective_max_bytes("/evil-ui/x") == REQUEST_BODY_MAX_BYTES

    def test_multiple_prefix_caps(self) -> None:
        from unittest.mock import MagicMock
        mw = RequestBodySizeLimitMiddleware(
            app=MagicMock(),
            prefix_caps={
                "/admin": 100,
                "/ui": 5 * 1024 * 1024,
            },
        )
        assert mw._effective_max_bytes("/admin/foo") == 100
        assert mw._effective_max_bytes("/ui/bar") == 5 * 1024 * 1024
        assert mw._effective_max_bytes("/other") == REQUEST_BODY_MAX_BYTES
