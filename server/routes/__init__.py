"""HTTP routes that are NOT MCP tool surfaces (E08_S03).

The existing handler pattern at ``server/handlers/`` is for MCP tool
implementations (``search_papers``, ``get_chunk``, ...). This package
collects FastAPI HTTP routes that operate at the ASGI layer rather
than via the MCP JSON-RPC envelope:

- ``debug.py`` — ``GET /debug/cache-stats`` for the 3-tier cache.

Routes here are NOT exempt from ``BodySizeCapMiddleware`` — they are
expected to return small payloads. If a future debug surface needs
to return large payloads, attach a per-route exception in
``server/main.py`` and document why.
"""
