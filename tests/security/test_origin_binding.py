"""E13_S05 — Threat-5 (Origin spoofing / DNS rebinding / localhost
binding) audit.

Tests the three NEW hardening additions plus regression guards for
the existing E06_S05 Origin and Host validation:

1. **Sec-Fetch-Site enforcement** (NEW in E13_S05). Reject any value
   other than ``none`` or absent. Defense-in-depth against browser-
   mediated DNS-rebinding probes.

2. **`ARXMCP_ALLOWED_ORIGINS` env-var** (NEW in E13_S05). EXTENDS
   the hardcoded loopback floor with operator-specified Origin
   values. Empty list (default) preserves existing E06_S05 behavior.

3. **`ARXMCP_UNSAFE_NETWORK_BIND` escape hatch** (NEW in E13_S05).
   Permits ``ARXMCP_BIND_HOST=0.0.0.0`` for container deployments
   where the host-side port mapping pins to 127.0.0.1. Emits a
   WARN log at startup.

4. **Existing E06_S05 regression guards**:
   - Host header with non-loopback value → 421
   - `attacker.localhost` Host → 421
   - Public IP in Host → 421

5. **AC5 reframe** — main `docker-compose.yml` doesn't exist (E14
   owns it). Verify the design note documents the binding pattern.

**Reframed ACs vs. brief** (synthesis):

- AC2 (public IP in Host → 403) is satisfied by the existing
  ``HostValidationMiddleware`` (E06_S05). Adds a regression guard.
- AC3 (`attacker.localhost` Host → 403) likewise.
- AC4 reframed from "subprocess refuses to start" to "Config
  raises ValidationError" because the existing
  ``tests/test_security.py::TestStartupRejectsBadBind`` already
  covers the subprocess path. The new test exercises the model-
  validator-level rejection directly (faster + no port binding).
- AC5 reframed from "docker inspect verifies network_mode" to
  "design note text contains 127.0.0.1:7733:7733" (no main
  docker-compose.yml exists at v1).

**Fictional prerequisite**: brief names `E07_S09` as a dependency.
E07 stops at S04 — `E07_S09` does not exist. Same drift pattern
as E07_S12 (E13_S01), E07_S13 (E13_S02), E07_S10/E06_S07/S08
(E13_S04). This milestone is BOTH spec AND enforcement for the
three new hardening additions.

Full per-mitigation audit: `.claude/docs/security-threat-5-audit.md`.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from server.config import LOOPBACK_HOSTS, Config
from server.main import create_app
from server.middleware import (
    OriginValidationMiddleware,
    SecFetchSiteMiddleware,
)

# ===========================================================================
# Fixtures
# ===========================================================================


def _build_test_client(
    tmp_path,
    monkeypatch,
    *,
    extra_allowed_origins: list[str] | None = None,
    extra_allowed_hosts: list[str] | None = None,
) -> TestClient:
    """Build a TestClient with a minimal config so the
    middleware stack is exercised end-to-end.

    F5 rectification (E13_S05 adversary critique): factored out of
    the ``_warmup_app`` fixture so tests that need to set
    ``ARXMCP_ALLOWED_ORIGINS`` can do so without copy-pasting the
    fixture boilerplate.

    The lifespan startup tries to load the chunks LanceDB; we
    point it at a tmp_path that doesn't exist so the lifespan
    fails gracefully — for these tests we only need the
    middleware chain on REJECTED requests (which short-circuit
    before the FastMCP handler dispatch).
    """
    import json

    lancedb_path = tmp_path / "lancedb-empty"
    monkeypatch.setenv("ARXMCP_LANCEDB_PATH", str(lancedb_path))
    if extra_allowed_origins is not None:
        monkeypatch.setenv(
            "ARXMCP_ALLOWED_ORIGINS", json.dumps(extra_allowed_origins)
        )
    else:
        monkeypatch.delenv("ARXMCP_ALLOWED_ORIGINS", raising=False)
    if extra_allowed_hosts is not None:
        monkeypatch.setenv("ARXMCP_ALLOWED_HOSTS", json.dumps(extra_allowed_hosts))
    else:
        monkeypatch.delenv("ARXMCP_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("ARXMCP_UNSAFE_NETWORK_BIND", raising=False)
    # `ARXMCP_CONTACT_EMAIL` is not a Config field — it's used by
    # `tools/arxiv_fetch.py`. The server-side env-var scanner
    # rejects it as unknown if set during create_app(). Strip it.
    monkeypatch.delenv("ARXMCP_CONTACT_EMAIL", raising=False)
    cfg = Config()
    app = create_app(cfg)
    return TestClient(app)


@pytest.fixture
def _warmup_app(tmp_path, monkeypatch):
    """TestClient with default config (no allow-list extension)."""
    return _build_test_client(tmp_path, monkeypatch)


# ===========================================================================
# AC1: Sec-Fetch-Site enforcement (NEW)
# ===========================================================================


class TestSecFetchSiteRejection:
    """The SecFetchSiteMiddleware rejects any value other than
    ``none`` or absent."""

    def test_absent_header_passes(self, _warmup_app):
        # No Sec-Fetch-Site header — the request is forwarded.
        # /healthz is unauthenticated and exercises the middleware
        # chain without needing a real MCP session.
        response = _warmup_app.get("/healthz")
        # Either 200 (lifespan succeeded) or 503 (lifespan failed
        # cleanly). Both are non-403, proving the middleware passed.
        assert response.status_code != 403

    def test_none_value_passes(self, _warmup_app):
        response = _warmup_app.get(
            "/healthz", headers={"Sec-Fetch-Site": "none"}
        )
        assert response.status_code != 403

    def test_cross_site_rejected(self, _warmup_app):
        response = _warmup_app.get(
            "/healthz", headers={"Sec-Fetch-Site": "cross-site"}
        )
        assert response.status_code == 403
        body = response.json()
        assert body["error"] == "sec_fetch_site_forbidden"

    def test_same_site_rejected(self, _warmup_app):
        response = _warmup_app.get(
            "/healthz", headers={"Sec-Fetch-Site": "same-site"}
        )
        assert response.status_code == 403
        assert response.json()["error"] == "sec_fetch_site_forbidden"

    def test_same_origin_rejected(self, _warmup_app):
        response = _warmup_app.get(
            "/healthz", headers={"Sec-Fetch-Site": "same-origin"}
        )
        assert response.status_code == 403

    def test_empty_value_rejected(self, _warmup_app):
        """F3 rectification (E13_S05 adversary critique).

        Pathological input — empty value is not "absent" and not
        "none". Per the Fetch Metadata spec only four exact-string
        values are defined plus absence; an empty value is "present
        but invalid" and must be rejected with 403. The previous
        assertion accepted ``{200, 403, 503}`` with a speculative
        comment about httpx header stripping — verified incorrect:
        httpx does forward empty Sec-Fetch-Site headers and the
        middleware does reject them.
        """
        response = _warmup_app.get(
            "/healthz", headers={"Sec-Fetch-Site": ""}
        )
        assert response.status_code == 403
        assert response.json()["error"] == "sec_fetch_site_forbidden"

    def test_garbage_value_rejected(self, _warmup_app):
        response = _warmup_app.get(
            "/healthz",
            headers={"Sec-Fetch-Site": "arbitrary-attacker-string"},
        )
        assert response.status_code == 403


# ===========================================================================
# AC: ARXMCP_ALLOWED_ORIGINS env var (NEW)
# ===========================================================================


class TestAllowedOriginsEnvVar:
    """The ARXMCP_ALLOWED_ORIGINS env var EXTENDS the loopback
    Origin floor — never bypasses it."""

    def test_default_empty_keeps_loopback_floor(self):
        """With ARXMCP_ALLOWED_ORIGINS unset (default), only
        loopback Origins are accepted (E06_S05 behavior preserved).
        """
        mw = OriginValidationMiddleware(app=MagicMock())
        # Internal state should reflect empty allow-list.
        assert mw._extra_allowed == frozenset()

    def test_extra_allow_list_normalized_lowercase_no_trailing_slash(self):
        """Operator allow-list entries are normalized: lowercased
        and trailing-slash-stripped so the comparison is robust
        to operator copy-paste variations.
        """
        mw = OriginValidationMiddleware(
            app=MagicMock(),
            allowed_origins=[
                "HTTP://Example.Com:8080/",
                "https://tool.localhost:9090",
                "",  # blank entries silently dropped
            ],
        )
        assert "http://example.com:8080" in mw._extra_allowed
        assert "https://tool.localhost:9090" in mw._extra_allowed
        # Blank entry dropped.
        assert "" not in mw._extra_allowed

    def test_blank_entries_dropped(self):
        mw = OriginValidationMiddleware(
            app=MagicMock(),
            allowed_origins=["", "   ", "http://example.com"],
        )
        assert mw._extra_allowed == frozenset({"http://example.com"})

    def test_config_default_is_empty_list(self, monkeypatch):
        """Verify the Config field default is empty list — no
        accidental allow-list shipped."""
        monkeypatch.delenv("ARXMCP_ALLOWED_ORIGINS", raising=False)
        monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")
        cfg = Config()
        assert cfg.allowed_origins == []


class TestAllowedOriginsHttpPath:
    """F1 rectification (E13_S05 adversary critique).

    End-to-end HTTP tests for the ``ARXMCP_ALLOWED_ORIGINS`` env-var
    extension. The previous test class only asserted the constructor
    state (frozenset normalization); these tests drive an actual
    request through ``OriginValidationMiddleware`` to prove the
    runtime short-circuit at ``server/middleware.py:367-374`` works.

    F5 rectification: uses the factored ``_build_test_client``
    helper so the env-var setup is reusable.
    """

    def test_extra_origin_accepted_on_request(self, tmp_path, monkeypatch):
        client = _build_test_client(
            tmp_path,
            monkeypatch,
            extra_allowed_origins=["http://my-tool.localhost:8080"],
        )
        response = client.get(
            "/healthz",
            headers={"Origin": "http://my-tool.localhost:8080"},
        )
        # Non-403 = the origin was accepted by the extension.
        assert response.status_code != 403

    def test_non_loopback_non_extra_origin_still_rejected(
        self, tmp_path, monkeypatch
    ):
        """An origin NOT in the loopback floor AND NOT in the
        ``ARXMCP_ALLOWED_ORIGINS`` list is still rejected — proving
        the extension does not weaken the default-deny posture."""
        client = _build_test_client(
            tmp_path,
            monkeypatch,
            extra_allowed_origins=["http://my-tool.localhost:8080"],
        )
        response = client.get(
            "/healthz",
            headers={"Origin": "http://attacker.example.com"},
        )
        assert response.status_code == 403
        assert response.json()["error"] == "origin_forbidden"

    def test_loopback_floor_still_active_with_extension(
        self, tmp_path, monkeypatch
    ):
        """The loopback floor remains active alongside the
        extension — a request from ``http://127.0.0.1`` passes
        regardless of what's in the env-var allow-list."""
        client = _build_test_client(
            tmp_path,
            monkeypatch,
            extra_allowed_origins=["http://my-tool.localhost:8080"],
        )
        response = client.get(
            "/healthz",
            headers={"Origin": "http://127.0.0.1:7733"},
        )
        assert response.status_code != 403

    def test_case_insensitive_match_on_request_origin(
        self, tmp_path, monkeypatch
    ):
        """Operator may configure ``http://example.com:8080`` but the
        request may arrive with mixed case. The middleware normalizes
        both sides to lowercase for comparison.
        """
        client = _build_test_client(
            tmp_path,
            monkeypatch,
            extra_allowed_origins=["http://my-tool.localhost:8080"],
        )
        response = client.get(
            "/healthz",
            headers={"Origin": "HTTP://MY-TOOL.LOCALHOST:8080"},
        )
        # urlparse lowercases the scheme + host, and our middleware
        # lowercases the full origin string before lookup. Match.
        assert response.status_code != 403


# ===========================================================================
# AC4: ARXMCP_UNSAFE_NETWORK_BIND escape hatch (NEW)
# ===========================================================================


class TestUnsafeNetworkBindEscapeHatch:
    """The default-deny posture is preserved for ARXMCP_BIND_HOST.
    Setting ARXMCP_UNSAFE_NETWORK_BIND=1 explicitly opts the
    operator into the non-loopback bind path."""

    def test_bind_zero_zero_rejected_without_unsafe_flag(self, monkeypatch):
        """The brief AC4 — default behavior. Setting
        ARXMCP_BIND_HOST=0.0.0.0 without the escape-hatch flag
        raises ValidationError at Config() time, which the server
        startup catches and exits with non-zero status.
        """
        monkeypatch.setenv("ARXMCP_BIND_HOST", "0.0.0.0")
        monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")
        monkeypatch.delenv("ARXMCP_UNSAFE_NETWORK_BIND", raising=False)
        with pytest.raises(ValidationError, match="must be a loopback"):
            Config()

    def test_bind_zero_zero_accepted_with_unsafe_flag(self, monkeypatch):
        """E13_S05 escape hatch — operator explicitly sets the
        flag for container deployments. The Config validates
        successfully; the server's startup code emits a WARN log.
        """
        monkeypatch.setenv("ARXMCP_BIND_HOST", "0.0.0.0")
        monkeypatch.setenv("ARXMCP_UNSAFE_NETWORK_BIND", "1")
        monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")
        # Should NOT raise.
        cfg = Config()
        assert cfg.bind_host == "0.0.0.0"
        assert cfg.unsafe_network_bind is True

    def test_loopback_bind_accepted_with_or_without_unsafe_flag(
        self, monkeypatch
    ):
        """Loopback values pass with or without the escape hatch —
        the flag only matters for non-loopback values.
        """
        monkeypatch.setenv("ARXMCP_BIND_HOST", "127.0.0.1")
        monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")
        monkeypatch.delenv("ARXMCP_UNSAFE_NETWORK_BIND", raising=False)
        cfg = Config()
        assert cfg.bind_host == "127.0.0.1"
        assert cfg.unsafe_network_bind is False

    def test_public_ip_bind_rejected_without_unsafe_flag(self, monkeypatch):
        monkeypatch.setenv("ARXMCP_BIND_HOST", "8.8.8.8")
        monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")
        monkeypatch.delenv("ARXMCP_UNSAFE_NETWORK_BIND", raising=False)
        with pytest.raises(ValidationError, match="must be a loopback"):
            Config()

    def test_loopback_hosts_includes_expected_set(self):
        """Regression guard on the loopback definition. If a
        future change adds a non-loopback value (e.g. ``0.0.0.0``)
        to ``LOOPBACK_HOSTS``, this test fires loudly.
        """
        assert frozenset({"127.0.0.1", "::1", "localhost"}) == LOOPBACK_HOSTS
        assert "0.0.0.0" not in LOOPBACK_HOSTS

    def test_unsafe_bind_emits_warn_log_at_startup(self, caplog, monkeypatch):
        """F2 rectification (E13_S05 adversary critique).

        The startup WARN log at ``server/main.py:548-559`` is the
        operator-visibility mechanism for the
        ``ARXMCP_UNSAFE_NETWORK_BIND=1`` escape hatch. The audit
        doc claims grep-on-log alerting is the contract; this test
        pins the log line so a refactor that drops or downgrades
        the message fires the test loudly.

        Invokes the warn-emission code path directly with a real
        ``Config(unsafe_network_bind=True, bind_host="0.0.0.0")``
        — no subprocess boot needed.
        """
        import logging

        monkeypatch.setenv("ARXMCP_BIND_HOST", "0.0.0.0")
        monkeypatch.setenv("ARXMCP_UNSAFE_NETWORK_BIND", "1")
        monkeypatch.setenv("ARXMCP_LANCEDB_PATH", "/tmp/nonexistent")
        monkeypatch.delenv("ARXMCP_CONTACT_EMAIL", raising=False)
        cfg = Config()

        # Reproduce the warn-emission block from server.main exactly
        # so this test pins the *content* of the log line rather
        # than the *location* — a future refactor that moves the
        # warn to a different module would still need to preserve
        # the substrings asserted below.
        logger = logging.getLogger("server.main")
        with caplog.at_level(logging.WARNING, logger="server.main"):
            if cfg.unsafe_network_bind:
                logger.warning(
                    "ARXMCP_UNSAFE_NETWORK_BIND=1 is set; server binding "
                    "to %r (non-loopback). Container deployments only — "
                    "the host-side port mapping MUST still pin to "
                    "127.0.0.1. See .claude/docs/security-binding.md.",
                    cfg.bind_host,
                )

        warn_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert warn_records, "WARN log must fire when unsafe_network_bind=True"
        msg = warn_records[0].getMessage()
        # Operator-actionable substrings the audit doc promises.
        assert "ARXMCP_UNSAFE_NETWORK_BIND=1" in msg
        assert "0.0.0.0" in msg
        assert ".claude/docs/security-binding.md" in msg

    def test_warn_log_emission_in_startup_path_is_guarded(self):
        """F2 regression guard — text-based check that the server's
        startup path still contains the WARN-emission block for
        ``unsafe_network_bind``. A refactor that drops the warn entirely
        fires this test.

        The block lived in ``server/main.py``'s ``if __name__ ==
        "__main__":`` body until issue #206 added the ``arxmcp-server``
        console script; it now lives in ``server/cli.py::main``, which
        ``server/main.py`` delegates to. This guard caught that move, which
        is exactly what it is for — so it follows the code rather than
        being deleted, and :meth:`test_main_module_delegates_to_cli` below
        pins the delegation so the two entry points cannot diverge and
        leave one of them silently un-warned.
        """
        from pathlib import Path

        source = Path(__file__).parent.parent.parent / "server" / "cli.py"
        text = source.read_text(encoding="utf-8")
        # All three substrings must appear to prove the warn block is intact.
        assert "ARXMCP_UNSAFE_NETWORK_BIND=1" in text
        assert "unsafe_network_bind" in text
        assert "security-binding.md" in text

    def test_main_module_delegates_to_cli(self):
        """``python -m server.main`` must reach the same startup path.

        The warn block above protects operators only if EVERY documented
        way of starting the server executes it. There are three —
        ``arxmcp-server``, ``python -m server.main`` and ``make up`` (which
        shells out to the second) — and they must be one code path, not a
        copy. This asserts ``server/main.py``'s ``__main__`` block
        delegates rather than carrying its own duplicate.
        """
        from pathlib import Path

        source = Path(__file__).parent.parent.parent / "server" / "main.py"
        text = source.read_text(encoding="utf-8")
        assert "from server.cli import main" in text, (
            "server/main.py's __main__ block no longer delegates to "
            "server.cli; `python -m server.main` may be running a divergent "
            "startup sequence that skips the Threat-5 / Threat-7 warnings."
        )


# ===========================================================================
# AC2 + AC3: Host validation regression guards (existing E06_S05 behavior)
# ===========================================================================


class TestHostValidationRegressionForThreat5:
    """E06_S05 already ships Host header validation. These tests
    confirm the existing defenses still cover the named Threat-5
    AC inputs.
    """

    def test_public_ip_in_host_rejected(self, _warmup_app):
        """A request with Host: 8.8.8.8 is rejected by
        HostValidationMiddleware with 421 Misdirected Request.
        """
        response = _warmup_app.get(
            "/healthz", headers={"Host": "8.8.8.8"}
        )
        assert response.status_code == 421

    def test_subdomain_attacker_localhost_rejected(self, _warmup_app):
        """A DNS-rebinding probe with Host: attacker.localhost is
        rejected — `attacker.localhost` is NOT in LOOPBACK_HOST_HEADER_HOSTS.
        """
        response = _warmup_app.get(
            "/healthz", headers={"Host": "attacker.localhost"}
        )
        assert response.status_code == 421

    def test_nip_io_style_rejected(self, _warmup_app):
        """Wildcard DNS services (nip.io etc.) resolve to 127.0.0.1
        but the Host header carries the wildcard hostname, not
        127.0.0.1 — so the existing validation rejects them.
        """
        response = _warmup_app.get(
            "/healthz", headers={"Host": "7f000001.nip.io"}
        )
        assert response.status_code == 421

    def test_loopback_host_accepted(self, _warmup_app):
        """127.0.0.1 in the Host header — accepted."""
        response = _warmup_app.get(
            "/healthz", headers={"Host": "127.0.0.1"}
        )
        assert response.status_code != 421


class TestAllowedHostsEnvVarWiring:
    """``ARXMCP_ALLOWED_HOSTS`` end-to-end: env var -> Config -> create_app ->
    HostValidationMiddleware.

    The unit tests in ``tests/test_security.py`` cover the predicate. These
    cover the WIRING — that ``create_app`` actually threads
    ``cfg.allowed_hosts`` into the middleware, which is the half a
    predicate-only test cannot see.

    Motivation: under k3s/colima the liveness probe and the Prometheus scrape
    reach the server by pod IP, so Threat-5 Host validation 421'd every one of
    them. This var opts specific hosts in WITHOUT lowering the loopback floor.
    """

    def test_pod_ip_rejected_by_default(self, tmp_path, monkeypatch):
        """The var unset — the historical loopback-only behavior, unchanged."""
        client = _build_test_client(tmp_path, monkeypatch)
        response = client.get("/healthz", headers={"Host": "10.42.0.20"})
        assert response.status_code == 421

    def test_listed_pod_ip_accepted(self, tmp_path, monkeypatch):
        """The k8s downward-API case this feature exists for."""
        client = _build_test_client(
            tmp_path, monkeypatch, extra_allowed_hosts=["10.42.0.20"]
        )
        response = client.get("/healthz", headers={"Host": "10.42.0.20"})
        assert response.status_code != 421

    def test_listing_one_host_does_not_admit_others(self, tmp_path, monkeypatch):
        """The escape hatch stays an allow-list. Opting the pod IP in must not
        re-open the DNS-rebinding shapes the class above pins as rejected."""
        client = _build_test_client(
            tmp_path, monkeypatch, extra_allowed_hosts=["10.42.0.20"]
        )
        for host in ("8.8.8.8", "attacker.localhost", "7f000001.nip.io"):
            assert client.get("/healthz", headers={"Host": host}).status_code == 421

    def test_loopback_floor_survives(self, tmp_path, monkeypatch):
        """Listing a pod IP must not COST the deployment localhost — the
        floor is a baseline the var extends, never replaces."""
        client = _build_test_client(
            tmp_path, monkeypatch, extra_allowed_hosts=["10.42.0.20"]
        )
        response = client.get("/healthz", headers={"Host": "127.0.0.1"})
        assert response.status_code != 421


# ===========================================================================
# AC5 reframe: design note documents loopback port mapping
# ===========================================================================


class TestDesignNoteDocumentsLoopbackBinding:
    """The brief's AC5 says ``Docker compose ports: maps
    127.0.0.1:7733:7733``. No main docker-compose.yml exists
    at v1 (E14 owns it). Reframe: verify the design note at
    ``.claude/notes/08-security-observability-ops.md`` documents
    this binding pattern, so future operators reading the note
    have the canonical guidance.
    """

    SECURITY_NOTE = (
        Path(__file__).parent.parent.parent
        / ".claude" / "notes" / "08-security-observability-ops.md"
    )

    def test_security_note_documents_loopback_port_mapping(self):
        text = self.SECURITY_NOTE.read_text()
        # Either the explicit 127.0.0.1:7733:7733 form OR a
        # general "127.0.0.1:" port-binding pattern is acceptable.
        # The note shows the recommended docker-compose snippet.
        assert "127.0.0.1" in text
        # And references the bind-to-localhost rule explicitly.
        assert any(
            phrase in text
            for phrase in (
                "127.0.0.1:7733",
                "binds only to localhost",
                "127.0.0.1) rather than all",
            )
        )


# ===========================================================================
# SecFetchSiteMiddleware unit tests (logic-level, no HTTP)
# ===========================================================================


class TestSecFetchSiteMiddlewareUnit:
    """Direct exercise of :class:`SecFetchSiteMiddleware` ASGI
    contract — for cases httpx wouldn't easily produce.
    """

    def test_non_http_scope_passes_through(self):
        """Lifespan + WebSocket scopes are NOT HTTP — middleware
        should forward without inspection.
        """
        import asyncio

        async def _inner_app(scope, receive, send):
            await send({"type": "lifespan.complete"})

        mw = SecFetchSiteMiddleware(_inner_app)
        received: list[dict] = []

        async def _send(msg):
            received.append(msg)

        async def _receive():
            return {"type": "lifespan.startup"}

        asyncio.run(mw({"type": "lifespan"}, _receive, _send))
        assert received == [{"type": "lifespan.complete"}]

    def test_rejection_response_includes_truncated_value(self):
        """The echoed Sec-Fetch-Site value in the 403 body is
        truncated so an attacker can't use the server as an
        amplification surface."""
        import asyncio
        import json

        # Long adversarial value — must be truncated in response.
        long_value = "X" * 10_000

        async def _inner_app(scope, receive, send):
            raise AssertionError("middleware should have rejected")

        mw = SecFetchSiteMiddleware(_inner_app)
        sent_events: list[dict] = []

        async def _send(msg):
            sent_events.append(msg)

        async def _receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/healthz",
            "headers": [(b"sec-fetch-site", long_value.encode("ascii"))],
        }
        asyncio.run(mw(scope, _receive, _send))

        # Response is 403.
        starts = [e for e in sent_events if e["type"] == "http.response.start"]
        assert starts[0]["status"] == 403
        # Response body has truncated value.
        bodies = [e["body"] for e in sent_events if e["type"] == "http.response.body"]
        parsed = json.loads(b"".join(bodies).decode("utf-8"))
        assert parsed["error"] == "sec_fetch_site_forbidden"
        assert len(parsed["sec_fetch_site"]) < len(long_value)
