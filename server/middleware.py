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
:func:`server.config.Config.reject_non_loopback` already pins the
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
:func:`server.config.Config.reject_non_loopback` validator
(escalated from SHOULD to MUST for our deployment per the brief).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

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
    - ``Origin`` present and NOT in the allow-list → 403 with a
      JSON error body. F6: a WARN log line records the rejection
      (origin value + remote client) so ops can alert on
      DNS-rebinding probes. F13: the echoed origin in the error
      body is truncated to :data:`MAX_ECHOED_ORIGIN_LEN` chars to
      prevent amplification-style probes.
    """

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

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
        Body-size cap in bytes. Defaults to
        :data:`REQUEST_BODY_MAX_BYTES` (1 MB).
    """

    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        max_bytes: int = REQUEST_BODY_MAX_BYTES,
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

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
            if declared > self.max_bytes:
                logger.warning(
                    "request rejected: content-length %d exceeds cap %d",
                    declared, self.max_bytes,
                )
                await _send_json_error(
                    send,
                    status=413,
                    body={
                        "error": "payload_too_large",
                        "message": (
                            f"request body declares {declared} bytes; the "
                            f"server caps inbound bodies at {self.max_bytes} "
                            f"bytes per request"
                        ),
                        "max_bytes": self.max_bytes,
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
            if body_seen > self.max_bytes:
                logger.warning(
                    "request rejected: body bytes exceeded cap %d (saw %d+)",
                    self.max_bytes, body_seen,
                )
                await _send_json_error(
                    send,
                    status=413,
                    body={
                        "error": "payload_too_large",
                        "message": (
                            f"request body exceeds the {self.max_bytes}-byte "
                            f"cap; the server caps inbound bodies to defend "
                            f"against memory-exhaustion requests"
                        ),
                        "max_bytes": self.max_bytes,
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


__all__ = [
    "LOOPBACK_HOST_HEADER_HOSTS",
    "LOOPBACK_ORIGIN_HOSTS",
    "LOOPBACK_ORIGIN_SCHEMES",
    "MAX_ECHOED_ORIGIN_LEN",
    "REQUEST_BODY_MAX_BYTES",
    "HostValidationMiddleware",
    "OriginValidationMiddleware",
    "RequestBodySizeLimitMiddleware",
    "SecurityHeadersMiddleware",
]
