"""Live-server integration tests for the stage2/arx-a1 surfaces.

Opt-in (spawns a real ``python -m server.main`` subprocess in bootstrap
mode and talks to it over loopback HTTP)::

    ARXMCP_RUN_LIVE_SERVER_TESTS=1 pytest tests/test_api_v1_live.py

Skipped by default — the in-process TestClient suites
(tests/test_api_v1.py etc.) are the fast gate; this file is the
"against a running server instance" evidence pass: real uvicorn, real
middleware stack (SecFetchSite / Origin / Host / body caps), real
lifespan (bootstrap mode — no corpus needed), real HTTP.

The server runs with an ISOLATED data tree (``ARXMCP_DATA_DIR`` +
``ARXMCP_NOTEBOOKS_DB_PATH`` under the pytest tmp dir) and a
non-default port so a concurrently-running dev server on 7733 is never
touched.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ARXMCP_RUN_LIVE_SERVER_TESTS") != "1",
    reason=(
        "live-server integration is opt-in: set "
        "ARXMCP_RUN_LIVE_SERVER_TESTS=1 (spawns a real server "
        "subprocess in bootstrap mode)"
    ),
)

_PORT = 7799
_BASE = f"http://127.0.0.1:{_PORT}"
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _http(
    method: str, path: str, body: dict | None = None,
    headers: dict | None = None,
) -> tuple[int, dict | bytes, dict]:
    """Tiny urllib helper returning (status, parsed-or-raw body, headers)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(_BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            status = resp.status
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code
        resp_headers = {k.lower(): v for k, v in e.headers.items()}
    try:
        return status, json.loads(raw), resp_headers
    except (json.JSONDecodeError, UnicodeDecodeError):
        return status, raw, resp_headers


@pytest.fixture(scope="module")
def live_server(tmp_path_factory) -> None:
    """Spawn ``python -m server.main`` in bootstrap mode on _PORT with
    an isolated data tree; kill it (and verify port release) on
    teardown."""
    tmp = tmp_path_factory.mktemp("live-server")
    env = dict(os.environ)
    # The pytest gate var is NOT a server config var — the server's
    # unknown-ARXMCP_* scan (server/main.py F4) would fatally reject
    # the inherited copy. Strip it (and any other test-runner gates)
    # from the subprocess env.
    env.pop("ARXMCP_RUN_LIVE_SERVER_TESTS", None)
    env.update({
        "ARXMCP_BOOTSTRAP_MODE": "1",
        "ARXMCP_BIND_PORT": str(_PORT),
        "ARXMCP_DATA_DIR": str(tmp / "arxmcp"),
        "ARXMCP_NOTEBOOKS_DB_PATH": str(tmp / "arxmcp" / "cache" / "notebooks.db"),
    })
    # Log to a FILE, not a PIPE: nobody drains a pipe during the test
    # run, so the OS pipe buffer fills with uvicorn access-log lines
    # after ~a dozen requests and the server blocks mid-write — which
    # presents as a client-side socket timeout on an arbitrary later
    # request.
    log_path = tmp / "server.log"
    log_file = log_path.open("wb")
    proc = subprocess.Popen(
        [sys.executable, "-m", "server.main"],
        cwd=str(_REPO_ROOT),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 60
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                out = log_path.read_text(encoding="utf-8", errors="replace")
                raise RuntimeError(
                    f"server exited early (rc={proc.returncode}):\n{out[-4000:]}"
                )
            try:
                status, _, _ = _http("GET", "/healthz")
                if status == 200:
                    break
            except OSError as exc:  # noqa: PERF203 — startup poll
                last_err = exc
            time.sleep(0.5)
        else:
            raise RuntimeError(f"server never became healthy: {last_err}")
        yield
    finally:
        proc.kill()
        proc.wait(timeout=15)
        log_file.close()


class TestLiveProbeSurfaces:
    def test_readyz_bootstrap_carries_corpus_version_null(self, live_server) -> None:
        status, body, _ = _http("GET", "/readyz")
        assert status == 200
        assert body["status"] == "bootstrap"
        assert "corpus_version" in body
        assert body["corpus_version"] is None

    def test_status_carries_notebook_versions_check(self, live_server) -> None:
        status, body, _ = _http("GET", "/status")
        assert status == 200
        assert "notebooks:corpus_versions" in body["checks"]

    def test_threat4_schema_endpoints_404(self, live_server) -> None:
        for path in ("/openapi.json", "/docs", "/redoc"):
            status, _, _ = _http("GET", path)
            assert status == 404, path


class TestLiveBridgeContracts:
    def test_handshake_serves_registry_envelope(self, live_server) -> None:
        status, body, _ = _http("GET", "/bridge/contracts")
        assert status == 200
        assert body["format_version"] == 1
        assert body["registry_status"] in (
            "absent", "registry", "scan", "malformed_registry",
        )
        assert isinstance(body["artifact_types"], dict)
        assert body["count"] == len(body["artifact_types"])


class TestLiveApiV1:
    def test_full_notebook_lifecycle_json_only(self, live_server) -> None:
        # Create — WITH the HX-Request header: must still be JSON.
        status, body, headers = _http(
            "POST", "/api/v1/notebooks",
            body={"slug": "live-a1", "display_name": "Live A1"},
            headers={"HX-Request": "true"},
        )
        assert status == 201, body
        assert headers.get("content-type", "").startswith("application/json")
        assert body["format_version"] == 1
        assert body["slug"] == "live-a1"

        # List — paginated envelope.
        status, body, _ = _http("GET", "/api/v1/notebooks?limit=10")
        assert status == 200
        assert body["total"] >= 1
        assert any(r["slug"] == "live-a1" for r in body["items"])

        # Add paper + list.
        status, body, _ = _http(
            "POST", "/api/v1/notebooks/live-a1/papers",
            body={"arxiv_url": "https://arxiv.org/abs/0705.3794"},
        )
        assert status == 201
        status, body, _ = _http("GET", "/api/v1/notebooks/live-a1/papers")
        assert status == 200
        assert body["total"] == 1

        # Health + parse-status.
        status, body, _ = _http("GET", "/api/v1/notebooks/live-a1/health")
        assert status == 200
        assert body["status"] == "no_marker"
        status, body, _ = _http("GET", "/api/v1/notebooks/live-a1/parse-status")
        assert status == 200
        assert body["parse_status"] == "skipped"

        # Ingest poll (none yet) — plain 200 JSON, no htmx 286.
        status, body, _ = _http("GET", "/api/v1/notebooks/live-a1/ingest/latest")
        assert status == 200
        assert body["status"] == "none"

        # Export — binary tar with the header-form version stamp.
        status, raw, headers = _http("GET", "/api/v1/notebooks/live-a1/export")
        assert status == 200
        assert headers.get("content-type") == "application/x-tar"
        assert headers.get("x-arxmcp-format-version") == "1"
        assert isinstance(raw, bytes)

        # Delete (cleanup) — always 204.
        status, _, _ = _http("DELETE", "/api/v1/notebooks/live-a1")
        assert status == 204
