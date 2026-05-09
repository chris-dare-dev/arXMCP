"""FastAPI app + lifespan + Streamable HTTP mount (E06_S01).

The long-running ``arxmcp-server`` process. Wires:

- :func:`server.config.Config` (env-var loading + validation).
- :class:`server.resources.Resources` (lifecycle container — the
  embedder, LanceDB handle, reranker, semaphores, singleflights).
- :mod:`server.health` (``/healthz``, ``/readyz``).
- ``prometheus_client.make_asgi_app()`` (``/metrics``).
- The MCP ``FastMCP`` server mounted at ``/mcp`` via
  :func:`server.mcp_mount.mount_mcp` (no tools registered yet —
  E06_S03 lands the tool implementations).

**Run via uvicorn**: ``python -m server.main`` (preferred — honors
``ARXMCP_BIND_HOST`` / ``ARXMCP_BIND_PORT`` via :class:`Config`) or,
equivalently, ``make up``. The ``uvicorn server.main:app`` CLI form
also works but does NOT honor the env-var bind overrides — closes
IS3+IS4 from the E06_S01 critique.

**Lifespan-style startup/shutdown**, NOT the deprecated
``@app.on_event("startup")`` decorator (FastAPI ≥0.93). The
async context manager wraps the entire app lifetime; pre-yield is
startup, post-yield is shutdown. The brief mandates a 30-second
shutdown drain — :meth:`Resources.shutdown` is wrapped in
``asyncio.wait_for(..., timeout=30)``.

The lifespan ALSO threads the MCP library's session-manager
lifespan into the parent's lifespan (closes F2 from the E06_S01
critique). ``FastMCP.streamable_http_app()`` returns a Starlette
sub-app whose lifespan opens a task group used by every request;
mounting the sub-app via ``app.mount`` does NOT propagate that
lifespan to the parent FastAPI app, so without the explicit
threading the first request to ``/mcp`` raises ``RuntimeError:
Task group is not initialized``. We capture the FastMCP instance
on ``app.state.mcp_server`` and ``async with
mcp_server.session_manager.run()`` from inside the parent
lifespan.

**Body-size middleware (synthesis D13, F1 fix).** A pure-ASGI
middleware enforces the 256 KB inline-payload cap on every
response EXCEPT ``/metrics`` (Prometheus exposition can grow
large), the health endpoints (negligible size), and the ``/mcp``
endpoint (Streamable HTTP carries SSE streams that defeat
buffering). The original ``BaseHTTPMiddleware`` implementation was
a silent no-op because Starlette wraps every response in a
``_StreamingResponse`` whose body lives in ``body_iterator``, not
``body`` — see F1 in the E06_S01 critique. The new pure-ASGI
implementation observes ``http.response.body`` events and
short-circuits with a 413 if the cumulative bytes exceed the cap
on a non-exempt path.

**Why eager startup is load-bearing**. ``/readyz`` returns 503 until
the embedder + LanceDB are warm. Lazy load would make the first
``tools/call`` hang for ~5–30s while a green ``/readyz`` lied. The
lifespan eager-loads BGE-M3 BEFORE ``yield``, so a green readiness
truly means "this process can serve a query in milliseconds, not
seconds."
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from fastapi import FastAPI
from prometheus_client import make_asgi_app

from server.config import Config
from server.health import (
    refresh_metrics_from_singleton_state,
)
from server.health import (
    router as health_router,
)
from server.resources import Resources

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Body-size middleware (256 KB cap on tool responses) — pure ASGI
# ---------------------------------------------------------------------------


#: Path PREFIXES exempt from the 256 KB cap.
#:
#: - ``/metrics``: Prometheus exposition can legitimately exceed the
#:   cap on registries with many time series.
#: - ``/healthz`` + ``/readyz``: tiny response bodies.
#: - ``/mcp``: the Streamable HTTP transport carries SSE streams
#:   whose total size cannot be measured without buffering the
#:   entire stream (which defeats the streaming benefit). MCP-spec
#:   tools that need to return large payloads MUST use
#:   ``resource_link`` per the spec — that resource_link IS the
#:   "<256 KB pointer to the larger payload" pattern. The cap fires
#:   on the resource-resolved fetch, not on the SSE chunks.
_BYTE_CAP_EXEMPT_PREFIXES = ("/healthz", "/readyz", "/metrics", "/mcp")


def _is_exempt_path(path: str) -> bool:
    """Return True if ``path`` should bypass the body-size cap."""
    return any(path == p or path.startswith(p + "/") for p in _BYTE_CAP_EXEMPT_PREFIXES)


class BodySizeCapMiddleware:
    """Pure-ASGI middleware enforcing the 256 KB inline-result cap.

    Closes F1 from the E06_S01 critique. The previous
    ``BaseHTTPMiddleware`` implementation was a silent no-op because
    Starlette wraps every response in a ``_StreamingResponse`` whose
    payload lives in ``body_iterator``, NOT a ``body`` attribute —
    so ``getattr(response, "body", None)`` always returned ``None``
    and the size check never fired.

    The pure-ASGI form intercepts ``http.response.start`` and
    ``http.response.body`` events. We accumulate body bytes; if the
    total exceeds ``byte_cap`` on a non-exempt path, we abort the
    upstream response (drop further body events) and emit a 413 in
    its place.

    **Limitation.** A response that has already sent the
    ``http.response.start`` event downstream cannot have its status
    changed (HTTP semantics — once headers are sent, status is
    locked). So we BUFFER the start event until the first body
    chunk arrives, by which point we know the true content length
    (or at least an over-cap signal). If the body is delivered in
    one chunk and stays under the cap, we forward both events
    unchanged. If we exceed the cap mid-stream, we synthesize a 413
    response. This adds one event of latency for the small-payload
    path; acceptable for a 256 KB cap.
    """

    def __init__(self, app, byte_cap: int) -> None:
        self.app = app
        self.byte_cap = byte_cap

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            # Lifespan, websocket — pass through unchanged.
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if _is_exempt_path(path):
            await self.app(scope, receive, send)
            return

        # Stateful interceptor: buffer the start event, count body
        # bytes, abort with 413 if we exceed the cap.
        start_event: dict | None = None
        body_bytes = 0
        sent_start = False
        cap_exceeded = False

        async def wrapped_send(event):
            nonlocal start_event, body_bytes, sent_start, cap_exceeded
            if cap_exceeded:
                # We've already sent a 413; swallow any further events
                # from the upstream handler.
                return
            if event["type"] == "http.response.start":
                # Hold onto it until the first body event arrives so
                # we can rewrite to 413 if needed.
                start_event = event
                return
            if event["type"] != "http.response.body":
                # Trailers etc — pass through.
                await send(event)
                return

            chunk = event.get("body", b"")
            body_bytes += len(chunk)

            if body_bytes > self.byte_cap:
                # Over the cap. Emit a 413 response and stop.
                cap_exceeded = True
                payload = json.dumps(
                    {
                        "error": "payload_too_large",
                        "message": (
                            f"response body of >={body_bytes} bytes exceeds "
                            f"the configured cap of {self.byte_cap} bytes; "
                            f"tools returning large payloads must use "
                            f"resource_link per the MCP 2025-06-18 spec"
                        ),
                        "byte_cap": self.byte_cap,
                    }
                ).encode("utf-8")
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
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
                return

            # Under cap so far. Flush the held start event then this
            # body event.
            if not sent_start:
                assert start_event is not None
                await send(start_event)
                sent_start = True
            await send(event)

        await self.app(scope, receive, wrapped_send)


# ---------------------------------------------------------------------------
# ARXMCP_* env-var validator (closes F4)
# ---------------------------------------------------------------------------


def _scan_unknown_arxmcp_env_vars(config: Config) -> None:
    """Reject any ``ARXMCP_*`` env var not declared on :class:`Config`.

    Closes F4 from the E06_S01 critique. ``pydantic-settings``'s
    ``extra="forbid"`` only fires for direct ``__init__`` kwargs —
    NOT for env-var input. So a typo like ``ARXMCP_BIND_HOST_TYPO``
    or a documented-but-unimplemented var like ``ARXMCP_OTEL_ENDPOINT``
    is silently ignored. This scan walks ``os.environ`` for every
    ``ARXMCP_*`` key and asserts it maps to a declared field.
    """
    declared = {f"ARXMCP_{name.upper()}" for name in Config.model_fields}
    unknown = []
    for env_name in os.environ:
        if env_name.startswith("ARXMCP_") and env_name not in declared:
            unknown.append(env_name)
    if unknown:
        raise ValueError(
            f"unknown ARXMCP_* environment variables: {sorted(unknown)}. "
            f"Declared variables: {sorted(declared)}. A typo here would "
            f"silently bypass the documented config — fix or remove the "
            f"variable."
        )


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup → yield → shutdown.

    Startup: build :class:`Resources`, attach to ``app.state.resources``.
    Also threads the MCP session-manager lifespan into the parent
    lifespan (F2 fix); without that, MCP requests raise
    ``RuntimeError: Task group is not initialized`` on the first
    call.

    Shutdown: 30-second drain via :meth:`Resources.shutdown`. Any
    startup failure raises and uvicorn exits non-zero — ``/readyz``
    never opens. Closes F9 from the E06_S01 critique by catching
    not just :class:`ResourceStartupError` but the broader
    ``Exception`` (LanceDB raises ``FileNotFoundError`` /
    ``ValueError`` outside the ``ResourceStartupError`` hierarchy).
    """
    config: Config = app.state.config

    # F9 fix: catch the broad Exception so LanceDB errors get the
    # FATAL prefix too.
    try:
        resources = await Resources.startup(config)
    except Exception as exc:
        logger.error("FATAL: Resources.startup failed: %s", exc)
        raise

    app.state.resources = resources
    refresh_metrics_from_singleton_state(resources)

    # F2 fix: thread the MCP session-manager lifespan into ours. The
    # mcp_server is attached to app.state by ``mount_mcp``.
    mcp_server = getattr(app.state, "mcp_server", None)

    try:
        if mcp_server is not None:
            async with mcp_server.session_manager.run():
                yield
        else:
            yield
    finally:
        try:
            await asyncio.wait_for(resources.shutdown(), timeout=30.0)
        except TimeoutError:
            logger.error(
                "Resources.shutdown exceeded the 30s drain budget; "
                "tearing down regardless"
            )


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(config: Config | None = None) -> FastAPI:
    """Construct the FastAPI application.

    Factored as a function so tests can construct the app with a
    custom :class:`Config` (e.g. a ``tmp_path`` LanceDB) without
    re-running the module-level env parse. Production callers
    (``uvicorn server.main:app``) get the module-level singleton
    constructed in the bottom of this file.
    """
    cfg = config if config is not None else Config()

    # F4 fix: scan os.environ for unknown ARXMCP_* vars BEFORE we
    # build the app. Belt + suspenders for typos that pydantic-
    # settings silently ignores.
    _scan_unknown_arxmcp_env_vars(cfg)

    app = FastAPI(
        title="arxmcp-server",
        description=(
            "Local-first MCP server exposing a research-mathematics "
            "arXiv corpus to multi-agent Claude pipelines."
        ),
        version="0.1.0",
        lifespan=lifespan,
        # Disable the default ``/docs`` and ``/redoc`` UIs — Threat 4
        # surface reduction. Operators who want a tool list use the
        # MCP ``tools/list`` JSON-RPC method.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.config = cfg

    # Universal body-size cap (pure ASGI — closes F1).
    app.add_middleware(BodySizeCapMiddleware, byte_cap=cfg.result_byte_cap)

    # Health + readiness routes.
    app.include_router(health_router)

    # Metrics ASGI sub-app. We wrap with a tiny middleware that
    # refreshes the gauges from the resources state at scrape time.
    metrics_app = make_asgi_app()

    async def metrics_wrapper(scope, receive, send):
        resources: Resources | None = getattr(
            app.state, "resources", None
        )
        if resources is not None:
            refresh_metrics_from_singleton_state(resources)
        await metrics_app(scope, receive, send)

    app.mount("/metrics", metrics_wrapper)

    # MCP Streamable HTTP mount. Lazily import the mcp lib so a
    # missing dep produces a clear FATAL message at startup rather
    # than a confusing module-level import error.
    try:
        from mcp.server.fastmcp import FastMCP

        from server._mcp_mount import mount_mcp

        # Empty FastMCP server — tools land in E06_S03. The mount
        # has to exist now so the Streamable HTTP endpoint responds
        # to ``tools/list`` (with an empty list) and is ready for
        # tool registration in the next milestone.
        # ``json_response=True`` makes responses single-shot
        # ``application/json`` rather than ``text/event-stream`` (SSE).
        # Required by the E06_S02 stdio shim, which is a pure
        # single-frame request/response proxy and does NOT parse SSE.
        # The design constitution
        # (``.claude/notes/06-mcp-server-design.md`` line 46) is
        # explicit: "No protocol-level streaming of tool results.
        # notifications/progress is a heartbeat, not a partial-result
        # channel." We don't need the SSE pipe.
        mcp_server = FastMCP("arxmcp", json_response=True)
        mount_mcp(app, mcp_server)
        # F2 fix: stash on app.state so the lifespan can thread the
        # session-manager lifespan into ours.
        app.state.mcp_server = mcp_server
    except ImportError as exc:
        logger.error(
            "FATAL: mcp library not installed (%s); install via "
            "pip install -e '.' (the mcp dep is in pyproject.toml)",
            exc,
        )
        raise

    return app


# ---------------------------------------------------------------------------
# Module-level singleton — uvicorn's ASGI entry point
# ---------------------------------------------------------------------------


def _build_module_app() -> FastAPI:
    """Wrapper for the module-level ``app`` singleton. Catches
    :class:`pydantic.ValidationError` from :class:`Config` (e.g.
    ``ARXMCP_BIND_HOST=0.0.0.0``) and exits with a clear message
    rather than a multi-screen pydantic stack."""
    try:
        return create_app()
    except Exception as exc:
        logger.error("FATAL during app construction: %s", exc)
        sys.stderr.write(f"FATAL: {exc}\n")
        raise


app = _build_module_app() if __name__ != "__main__" else None


if __name__ == "__main__":
    # IS3+IS4 fix: the ``__main__`` path uses Config to source the
    # bind host/port, so ``ARXMCP_BIND_HOST`` / ``ARXMCP_BIND_PORT``
    # are honored. Use this entry point (``python -m server.main``)
    # rather than the bare ``uvicorn server.main:app`` form for
    # env-var-aware binding.
    import uvicorn

    cfg = Config()
    _scan_unknown_arxmcp_env_vars(cfg)
    logging.basicConfig(level=cfg.log_level)
    logger.info(
        "Starting arxmcp-server on %s:%d", cfg.bind_host, cfg.bind_port
    )
    uvicorn.run(
        "server.main:app",
        host=cfg.bind_host,
        port=cfg.bind_port,
        lifespan="on",
        log_config=None,
    )


__all__ = [
    "BodySizeCapMiddleware",
    "_scan_unknown_arxmcp_env_vars",
    "app",
    "create_app",
    "lifespan",
]
