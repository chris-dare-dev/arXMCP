"""Thin adapter for mounting the MCP library onto FastAPI (E06_S01).

The ``mcp`` Python SDK's FastAPI/Starlette mount API has shifted
across 1.x minors (for example, ``sse_app`` → ``streamable_http_app``).
Synthesis D9 calls for isolating the mount call in a single function
so a future API rename is a one-line change.

Verified against ``mcp==1.27.1``: ``FastMCP("name").streamable_http_app()``
returns a Starlette ASGI app suitable for ``FastAPI.mount(...)``.

This module deliberately exposes the SMALLEST possible surface — no
``mcp.types.*`` re-exports, no helper for tool registration. Tool
registration lands in :mod:`server.tools` (E06_S03), and that module
will import ``FastMCP`` directly. This module's job is exactly the
mount call.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


#: The conventional MCP endpoint path. The MCP 2025-06-18 spec says:
#: *"The server MUST provide a single HTTP endpoint path (hereafter
#: referred to as the MCP endpoint) that supports both POST and GET
#: methods."* ``/mcp`` is the de-facto convention.
DEFAULT_MCP_PATH = "/mcp"


def mount_mcp(
    app: FastAPI,
    mcp_server: FastMCP,
    *,
    path: str = DEFAULT_MCP_PATH,
) -> None:
    """Mount ``mcp_server``'s Streamable HTTP ASGI app on ``app`` so
    requests to ``path`` reach the MCP endpoint.

    Parameters
    ----------
    app
        The parent FastAPI application.
    mcp_server
        A ``FastMCP`` instance with handlers already registered.
        E06_S01 registers ZERO tools; E06_S03 will register the
        seven canonical tools.
    path
        The desired MCP endpoint path. Default ``/mcp``.

    Notes
    -----
    The ``mcp`` library's ``streamable_http_app()`` returns a
    Starlette app whose internal route is at the FastMCP setting
    ``streamable_http_path`` (default ``/mcp``). We configure
    ``mcp_server.settings.streamable_http_path = "/"`` so the
    sub-app's internal route is ``/``, then mount it at
    ``path`` on the parent FastAPI app. The Starlette mount-routing
    math is:

        ``"/mcp" (mount prefix) + "/" (sub-app route) → "/mcp/"``

    Operators who hit ``/mcp`` (no trailing slash) get a 307
    redirect to ``/mcp/`` from Starlette's standard trailing-slash
    handling — both forms reach the same handler.

    Why not mount at root ``""``: a root-prefix mount catches every
    path the parent app didn't explicitly register first, including
    ``/metrics``. Mounting at the dedicated ``path`` keeps the
    routing surface unambiguous.

    Verified against ``mcp==1.27.1``. The ``streamable_http_app()``
    call returns a fresh Starlette app each invocation; do not
    cache the return value across multiple mount calls.
    """
    # Configure FastMCP's internal path to "/" so the sub-app route
    # is at the root of its own ASGI app. This MUST happen BEFORE
    # ``streamable_http_app()`` is invoked.
    #
    # F11 fix: save and restore the prior ``streamable_http_path``
    # so a caller passing the same ``mcp_server`` to multiple
    # ``mount_mcp`` calls doesn't see the settings stuck at "/".
    # The ``streamable_http_app()`` call captures the current value
    # internally; restoring afterwards leaves the settings object
    # unchanged from the caller's perspective.
    prior_path = mcp_server.settings.streamable_http_path
    mcp_server.settings.streamable_http_path = "/"
    try:
        sub_app = mcp_server.streamable_http_app()
    finally:
        mcp_server.settings.streamable_http_path = prior_path
    app.mount(path, sub_app)
    logger.info(
        "MCP Streamable HTTP app mounted; endpoint path=%s "
        "(handler count: %d tools registered)",
        path,
        # FastMCP exposes a ``_tools`` registry; reading the count is
        # safe (read-only) but the underscore signals it's not a
        # stable API. Wrap in try/except so a future rename doesn't
        # break startup.
        _safe_tool_count(mcp_server),
    )


def _safe_tool_count(mcp_server: FastMCP) -> int:
    """Best-effort tool count for log line. Falls back to 0 on any
    attribute error so a future ``FastMCP`` API change doesn't break
    server startup."""
    try:
        # FastMCP 1.27 stores tools in a ``_tool_manager`` with a
        # ``_tools`` dict. Other 1.x minors may differ.
        return len(mcp_server._tool_manager._tools)  # type: ignore[attr-defined]
    except AttributeError:
        return 0


__all__ = [
    "DEFAULT_MCP_PATH",
    "mount_mcp",
]
