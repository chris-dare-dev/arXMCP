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

**Run via uvicorn**: ``uvicorn server.main:app --host 127.0.0.1
--port 7733`` or, equivalently, ``make up``.

**Lifespan-style startup/shutdown**, NOT the deprecated
``@app.on_event("startup")`` decorator (FastAPI ≥0.93). The
async context manager wraps the entire app lifetime; pre-yield is
startup, post-yield is shutdown. The brief mandates a 30-second
shutdown drain — :meth:`Resources.shutdown` is wrapped in
``asyncio.wait_for(..., timeout=30)``.

**Body-size middleware (synthesis D13)**. A custom
``BaseHTTPMiddleware`` enforces the 256 KB inline-payload cap on
every response EXCEPT ``/metrics`` (Prometheus exposition can grow
large) and the health endpoints (negligible size). Tool implementations
in E06_S03 will rely on this universal cap rather than each tool
remembering its own size budget.

**Why eager startup is load-bearing**. ``/readyz`` returns 503 until
the embedder + LanceDB are warm. Lazy load would make the first
``tools/call`` hang for ~5–30s while a green ``/readyz`` lied. The
lifespan eager-loads BGE-M3 BEFORE ``yield``, so a green readiness
truly means "this process can serve a query in milliseconds, not
seconds."
"""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from fastapi import FastAPI, Request, Response
from prometheus_client import make_asgi_app
from starlette.middleware.base import BaseHTTPMiddleware

from server.config import Config
from server.health import (
    refresh_metrics_from_singleton_state,
)
from server.health import (
    router as health_router,
)
from server.resources import Resources, ResourceStartupError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Body-size middleware (256 KB cap on tool responses)
# ---------------------------------------------------------------------------


#: Paths exempt from the 256 KB cap. Prometheus exposition and the
#: health endpoints can exceed the cap legitimately (especially
#: ``/metrics`` with large registries).
_BYTE_CAP_EXEMPT_PATHS = frozenset({"/healthz", "/readyz", "/metrics"})


class BodySizeCapMiddleware(BaseHTTPMiddleware):
    """Universal cap on response body bytes (synthesis D13).

    Enforced as middleware so every tool response goes through a
    single check, rather than each tool remembering its own size
    budget. Per-tool caps are easier to forget; the universal cap
    makes the contract enforceable.

    The cap value comes from :attr:`Config.result_byte_cap` (default
    256 KB). Exempt paths (see :data:`_BYTE_CAP_EXEMPT_PATHS`) bypass
    the check entirely; on a non-exempt path that exceeds the cap,
    the response is rewritten to a 413 (Payload Too Large) with a
    JSON body explaining the failure.

    **Streaming responses are passed through.** The MCP spec's SSE
    streaming path returns ``text/event-stream`` and is inherently
    streaming — measuring its accumulated bytes would require
    buffering the entire stream, defeating the streaming benefit.
    The size cap applies to single-response (non-streaming) JSON
    payloads only. Tool implementations that need to return large
    payloads MUST use ``resource_link`` per the MCP spec.
    """

    def __init__(self, app, byte_cap: int) -> None:
        super().__init__(app)
        self.byte_cap = byte_cap

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        if request.url.path in _BYTE_CAP_EXEMPT_PATHS:
            return response

        # Streaming responses (SSE, file streams) don't expose a
        # finite ``body`` attribute; pass them through.
        body = getattr(response, "body", None)
        if body is None:
            return response

        if len(body) > self.byte_cap:
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=413,
                content={
                    "error": "payload_too_large",
                    "message": (
                        f"response body of {len(body)} bytes exceeds "
                        f"the configured cap of {self.byte_cap} "
                        f"bytes; tools returning large payloads must "
                        f"use resource_link per the MCP 2025-06-18 spec"
                    ),
                    "byte_cap": self.byte_cap,
                    "body_size": len(body),
                },
            )
        return response


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup → yield → shutdown.

    Startup: build :class:`Resources`, attach to ``app.state.resources``.
    Shutdown: 30-second drain via :meth:`Resources.shutdown`.

    A startup failure (missing corpus marker, reranker model
    unavailable, LanceDB open failure) raises
    :class:`ResourceStartupError`. The lifespan logs ``FATAL: ...``
    and re-raises so uvicorn exits non-zero — ``/readyz`` never
    opens.
    """
    config: Config = app.state.config
    try:
        resources = await Resources.startup(config)
    except ResourceStartupError as exc:
        logger.error("FATAL: %s", exc)
        raise

    app.state.resources = resources
    # Prime the Prometheus metrics with the freshly-warm state so the
    # first ``/metrics`` scrape sees the correct values.
    refresh_metrics_from_singleton_state(resources)

    try:
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

    # Universal body-size cap.
    app.add_middleware(BodySizeCapMiddleware, byte_cap=cfg.result_byte_cap)

    # Health + readiness routes.
    app.include_router(health_router)

    # Metrics ASGI sub-app. We wrap with a tiny middleware that
    # refreshes the gauges from the resources state at scrape time —
    # otherwise the gauges would only carry whatever the lifespan
    # primed at startup. The wrapper does NOT itself enforce the
    # body-size cap (the universal middleware exempts ``/metrics``).
    metrics_app = make_asgi_app()

    async def metrics_wrapper(scope, receive, send):
        # Refresh from the live resources, if attached.
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
        mcp_server = FastMCP("arxmcp")
        mount_mcp(app, mcp_server)
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
    import uvicorn

    cfg = Config()
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
    "app",
    "create_app",
    "lifespan",
]
