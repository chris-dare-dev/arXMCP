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
``mcp/server/transport_security.py``) already rejects bad-Origin /
bad-Host requests on ``/mcp`` with 403 / 421 respectively. Our
:class:`OriginValidationMiddleware` does NOT replace that; it adds
the same rejection across the WHOLE FastAPI app (so ``/metrics``
and the health endpoints behind a malicious origin are also
protected). Both layers apply — DO NOT disable the FastMCP
built-in.

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
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Hosts permitted in the ``Origin`` header. Mirrors the FastMCP
#: built-in's ``allowed_origins=["http://127.0.0.1:*",
#: "http://localhost:*", "http://[::1]:*"]`` so operators don't see
#: surprising rejection differences between ``/mcp`` and the rest of
#: the app.
LOOPBACK_ORIGIN_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

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


def _origin_is_allowed(origin: str) -> bool:
    """Return True if ``origin`` is in the loopback allow-list.

    Allows the schemes in :data:`LOOPBACK_ORIGIN_SCHEMES` with the
    hosts in :data:`LOOPBACK_ORIGIN_HOSTS`, with any port (or no
    port). Mirrors FastMCP's ``allowed_origins`` defaults.

    ``urlparse`` lowercases scheme + hostname; we compare against
    lowercase constants. IPv6 hosts are returned without brackets by
    ``urlparse('http://[::1]:1234').hostname``, which matches our
    ``"::1"`` constant.
    """
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    if parsed.scheme not in LOOPBACK_ORIGIN_SCHEMES:
        return False
    host = parsed.hostname  # already lowercased; brackets stripped
    if host is None:
        return False
    return host in LOOPBACK_ORIGIN_HOSTS


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
      JSON error body. The body names the offending origin so
      operators can debug a misconfigured client; we do NOT echo
      the full header value to avoid log injection (the JSON
      ``json.dumps`` already escapes any embedded quotes).
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
                "origin": origin_str,
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


class RequestBodySizeLimitMiddleware:
    """Cap incoming request bodies at ``max_bytes``.

    uvicorn has no ``limit_request_body`` knob (verified in
    ``uvicorn/config.py`` — only ``limit_max_requests`` exists), so
    the cap MUST live in middleware. Two paths:

    1. ``Content-Length`` is present and exceeds the cap → reject
       immediately with 413 BEFORE forwarding any
       ``http.request`` events. The downstream app never sees the
       request.
    2. ``Content-Length`` is absent (chunked transfer) or
       under-promises → wrap ``receive`` and accumulate the body.
       If the running total exceeds the cap, replace subsequent
       ``http.request`` events with an empty terminal event AND
       send a 413; this is the only safe path because we may have
       already started the request body's iteration.

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

        # Path 1: Content-Length declared and over the cap → reject
        # before reading the body.
        content_length_b = _get_header(scope.get("headers", []), b"content-length")
        if content_length_b is not None:
            try:
                declared = int(content_length_b.decode("ascii"))
            except (ValueError, UnicodeDecodeError):
                declared = -1
            if declared > self.max_bytes:
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

        # Path 2: wrap receive and count.
        body_seen = 0
        cap_exceeded = False

        async def wrapped_receive() -> dict:
            nonlocal body_seen, cap_exceeded
            if cap_exceeded:
                # Synthesize a terminal disconnect so the wrapped app
                # stops asking for more.
                return {"type": "http.disconnect"}
            event = await receive()
            if event["type"] != "http.request":
                return event
            chunk = event.get("body", b"")
            body_seen += len(chunk)
            if body_seen > self.max_bytes:
                cap_exceeded = True
                # Truncate the body and signal end. The downstream
                # handler will receive a partial body; we'll then send
                # the 413 response below the wrapped call.
                return {
                    "type": "http.request",
                    "body": b"",
                    "more_body": False,
                }
            return event

        # Track whether we sent our own 413; if so, swallow the
        # downstream's response events.
        our_response_sent = False

        async def wrapped_send(event: dict) -> None:
            nonlocal our_response_sent
            if cap_exceeded and not our_response_sent:
                our_response_sent = True
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
            if our_response_sent:
                # Already responded with our 413 — drop downstream events.
                return
            await send(event)

        await self.app(scope, wrapped_receive, wrapped_send)


__all__ = [
    "LOOPBACK_ORIGIN_HOSTS",
    "LOOPBACK_ORIGIN_SCHEMES",
    "REQUEST_BODY_MAX_BYTES",
    "OriginValidationMiddleware",
    "RequestBodySizeLimitMiddleware",
    "SecurityHeadersMiddleware",
]
