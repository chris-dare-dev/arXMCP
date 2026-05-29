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
from pathlib import Path
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
_BYTE_CAP_EXEMPT_PREFIXES = (
    # notebook-ops-hardening-m4: /status is a tiny health+json body, exempt
    # for parity with the other health probes (no buffering delay on a probe).
    "/healthz", "/readyz", "/status", "/metrics", "/mcp",
    # m8: the vendored htmx.min.js (~51 KB) and CSS are small but
    # served via /ui/static/. Exempting only /ui/static (not the
    # whole /ui subtree) keeps the 256 KB response cap on the
    # /ui/api/* JSON routes — a future handler that accidentally
    # returns a large JSON body must still trip the cap. m8 rect F4
    # narrowed this from "/ui" to "/ui/static". The HTML page routes
    # at /ui/ and /ui/notebooks/{slug} serve modest pages (the
    # notebook list + paper table HTML); if they ever approach
    # 256 KB the right fix is per-page pagination, not exemption.
    "/ui/static",
)


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

    # E14_S02 D2: install the OTel TracerProvider BEFORE Resources.startup
    # so embedder + LanceDB warm-up spans are themselves traced. Disabled
    # path (ARXMCP_OTEL_ENDPOINT unset) returns without registering — every
    # subsequent ``tracer.start_as_current_span(...)`` then takes the
    # ProxyTracer → NoOpTracer fast path with zero allocation.
    from server.observability.tracing import setup_tracing  # noqa: PLC0415

    setup_tracing(config)

    # F9 fix: catch the broad Exception so LanceDB errors get the
    # FATAL prefix too.
    try:
        resources = await Resources.startup(config)
    except Exception as exc:
        logger.error("FATAL: Resources.startup failed: %s", exc)
        raise

    app.state.resources = resources
    refresh_metrics_from_singleton_state(resources)

    # E06_S03: tool handlers reach the live Resources via a
    # module-level reference set here. Synthesis D8 — handlers
    # raise ResourcesNotReadyError if invoked before this fires.
    from server.tools import set_resources

    set_resources(resources)

    # F2 fix: thread the MCP session-manager lifespan into ours. The
    # mcp_server is attached to app.state by ``mount_mcp``.
    mcp_server = getattr(app.state, "mcp_server", None)

    # m7 rect F2: open the NotebooksStore INSIDE the try/finally so
    # an open-failure (permission denied on var/arxmcp/cache/, disk
    # full, sqlite3 library mismatch) still invokes
    # ``resources.shutdown`` in the finally block. Without this,
    # the m7-era code path leaked BGE-M3 weights + LanceDB
    # connections + semaphores on startup retry loops (systemd /
    # docker `restart: on-failure`).
    from server.ingest_tracker import IngestTaskTracker  # noqa: PLC0415
    from server.notebooks_store import NotebooksStore  # noqa: PLC0415
    from server.parse_tracker import ParseTaskTracker  # noqa: PLC0415

    try:
        app.state.notebooks_store = await NotebooksStore.open(
            config.notebooks_db_path
        )
        # notebook-surface-expansion-m4: wire the live store for the MCP
        # resource callbacks (they have no FastAPI request/DI), mirroring
        # set_resources above. Same event loop as FastMCP → store awaits safe.
        from server.mcp_resources import set_notebooks_store  # noqa: PLC0415

        set_notebooks_store(app.state.notebooks_store)
        # m9 FM-5 + m9 rect F2: orphan-recovery — mark any
        # ``status='running'`` row older than 5 minutes as ``failed``
        # BEFORE accepting new ingest triggers. Covers daemon-crash-
        # mid-ingest where the previous task's done_callback never
        # fired.
        #
        # The 5-minute cutoff (m9 rect F2) replaces the original
        # 1-hour value. Rationale: with the F1 cancel-path fix
        # writing a terminal-state row inline on clean shutdown,
        # the orphan-recovery is purely defense-in-depth — it
        # covers ONLY the hard-kill path (SIGKILL, OOM-killer,
        # host crash) where the cancel-path never ran. A
        # 5-minute cutoff bounds the operator-visible
        # "permanent 409" window to a single restart-loop cycle.
        # The earlier 1-hour value was designed to NOT clobber a
        # still-running ingest, but with F1 in place the
        # cancel-path handles that case correctly.
        import datetime as _dt  # noqa: PLC0415
        cutoff = (
            _dt.datetime.now(_dt.UTC) - _dt.timedelta(minutes=5)
        ).isoformat(timespec="seconds")
        recovered = await app.state.notebooks_store.mark_orphaned_runs_failed(
            cutoff_iso=cutoff,
            message="server restarted mid-ingest (m9 FM-5 recovery)",
        )
        if recovered:
            logger.info(
                "IngestTracker startup recovery: marked %d orphaned "
                "running row(s) as failed", recovered,
            )
        # textbook-ingest-m6 FM-4: orphan-recovery for parse rows.
        # Any ``parse_status='running'`` row at startup is by
        # definition orphaned because the new daemon has not yet
        # accepted any uploads. Mark all such rows as ``failed``.
        recovered_parses = await app.state.notebooks_store.mark_orphaned_parses_failed(
            message="server restarted mid-parse (m6 FM-4 recovery)",
        )
        if recovered_parses:
            logger.info(
                "ParseTracker startup recovery: marked %d orphaned "
                "parse row(s) as failed", recovered_parses,
            )
        # m9: ingest task tracker — fire-and-forget subprocess
        # registry for the UI ingest trigger.
        app.state.ingest_tracker = IngestTaskTracker()
        # textbook-ingest-m6: parse task tracker — fire-and-forget
        # registry for the textbook PDF parse pipeline (MinerU +
        # LaTeXML). Mirrors IngestTaskTracker; runs in-process via
        # asyncio.to_thread (the heavy lifting subprocess-isolates
        # via the m5 + LaTeXML helpers).
        app.state.parse_tracker = ParseTaskTracker()
        if mcp_server is not None:
            async with mcp_server.session_manager.run():
                yield
        else:
            yield
    finally:
        # m9: cancel any in-flight ingest tasks first (best-effort;
        # subprocesses continue running until reaped, but the
        # async wrapper is torn down cleanly). Done BEFORE
        # NotebooksStore.close so the tracker's done_callbacks can
        # still write final-state rows.
        ingest_tracker = getattr(app.state, "ingest_tracker", None)
        if ingest_tracker is not None:
            await ingest_tracker.shutdown()
        # textbook-ingest-m6: same shutdown discipline as the ingest
        # tracker — cancel in-flight parse tasks before the store
        # closes so the cancel-path can write terminal-state rows.
        parse_tracker = getattr(app.state, "parse_tracker", None)
        if parse_tracker is not None:
            await parse_tracker.shutdown()
        # m7: close the NotebooksStore connection BEFORE Resources
        # shutdown so its async lock can drain cleanly. The store is
        # cheap to close (just a sqlite3.Connection.close); failures
        # are logged and swallowed inside NotebooksStore.close.
        notebooks_store = getattr(app.state, "notebooks_store", None)
        if notebooks_store is not None:
            await notebooks_store.close()
        try:
            await asyncio.wait_for(resources.shutdown(), timeout=30.0)
        except TimeoutError:
            logger.error(
                "Resources.shutdown exceeded the 30s drain budget; "
                "tearing down regardless"
            )
        # E14_S02 D2: flush in-flight spans AFTER resources have drained,
        # so any shutdown-time span (e.g. final cache eviction) gets
        # exported before the process exits.
        from server.observability.tracing import shutdown_tracing  # noqa: PLC0415

        shutdown_tracing()


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

    # E06_S05 + E13_S05: security-hardening middleware stack.
    #
    # ``add_middleware`` adds in LIFO request order — the LAST call
    # wraps the request FIRST. So mount innermost-first here:
    #
    #   request flow: SecurityHeaders -> SecFetchSite -> OriginValidation
    #                 -> HostValidation -> RequestBodySizeLimit
    #                 -> SessionCap -> BodySizeCap -> handler
    #
    # SecurityHeaders is OUTERMOST so even error responses from inner
    # middlewares (e.g. OriginValidation's 403, BodySizeCap's 413)
    # carry the X-Content-Type-Options + X-Frame-Options headers.
    # SecFetchSite is added next (one in from outer) so the cheap
    # byte-comparison fires before Origin parsing on attacker-shaped
    # browser traffic (E13_S05 Threat 5 defense-in-depth).
    # OriginValidation is BEFORE the request-body limit so an
    # evil-origin POST is rejected without buffering its body.
    from server.middleware import (
        HostValidationMiddleware,
        OriginValidationMiddleware,
        RequestBodySizeLimitMiddleware,
        SecFetchSiteMiddleware,
        SecurityHeadersMiddleware,
        SessionCapMiddleware,
        TracingContextMiddleware,
    )

    # E14_S02: copy ``Mcp-Session-Id`` + ``Arxmcp-Agent-Role`` headers
    # into ContextVars for the OTel parent span. Added FIRST so it
    # becomes the innermost middleware — runs LAST on the request path,
    # right before FastMCP dispatches to the handler. This guarantees
    # the ContextVars are populated when ``_wrap_with_observability``
    # opens the parent span. Pure-ASGI; the project bans
    # ``BaseHTTPMiddleware`` (E06_S01 F1).
    app.add_middleware(TracingContextMiddleware)
    # Universal response body-size cap (pure ASGI — closes F1).
    app.add_middleware(BodySizeCapMiddleware, byte_cap=cfg.result_byte_cap)
    # E08_S04: per-session retrieval-cap enforcement. Mounted INSIDE
    # the body-size cap so a RETRIEVAL_CAP_REACHED response is itself
    # capped, but OUTSIDE the FastMCP /mcp ASGI sub-app so the
    # middleware sees the inbound JSON-RPC body before FastMCP
    # dispatches. A request that fails the cap is short-circuited
    # before any handler runs.
    app.add_middleware(SessionCapMiddleware)
    # 1 MB default cap on incoming request bodies (E06_S05). m8:
    # /ui/api/notebooks/*/papers/upload accepts ar5iv HTML files
    # which routinely exceed 1 MB (~100KB-5MB observed); the
    # prefix_caps carve-out raises the cap for the whole
    # /ui/api/notebooks subtree. Other /ui/api/notebooks routes
    # accept small JSON bodies well under any cap, so the widening
    # is harmless for them. Prefix-match form (NOT substring) for
    # FM-3 parity with the m7 SecFetchSite carve-out.
    #
    # textbook-ingest-m4: cap raised from 10 MB to 200 MB to allow
    # textbook PDF uploads on notebook_kind="textbook" notebooks
    # (Bourbaki / Hartshorne / Griffiths-Harris all fit comfortably
    # under 200 MB). The 10 MB enforcement for arxiv-kind notebooks
    # is preserved at the ROUTE HANDLER level — the upload handler
    # in server/routes/notebooks.py reads notebook_kind from the
    # SQLite store (m3) and rejects 413 if the body exceeds 10 MB on
    # an arxiv-kind notebook. The middleware cap is the upper
    # envelope; the per-kind rule is enforced downstream.
    #
    # **Memory-pressure caveat (m4 rect F1).** The route handler
    # reads the full body via ``await file.read()`` BEFORE the per-
    # kind cap fires — see `server/routes/notebooks.py` upload-paper
    # flow. So a 200 MB body uploaded to an arxiv-kind notebook IS
    # buffered fully in memory before the handler returns 413. This
    # is acceptable under the loopback-only deployment model (CLAUDE.md
    # "Must run locally in Docker"; server binds to 127.0.0.1 per
    # ``server/config.py::reject_non_loopback``) but is a memory-
    # pressure regression vs the pre-m4 10 MB middleware envelope.
    # If arXMCP ever runs in a networked deployment, the per-kind cap
    # should be moved into ``RequestBodySizeLimitMiddleware`` (e.g.
    # via a callable in ``prefix_caps`` that resolves the cap from
    # request scope) so rejection fires before the body is buffered.
    app.add_middleware(
        RequestBodySizeLimitMiddleware,
        prefix_caps={
            "/ui/api/notebooks": 200 * 1024 * 1024,  # 200 MB envelope; per-kind enforced in handler
        },
    )
    # Host header validation: Threat 5 / DNS rebinding defense
    # (closes F3 from E06_S05 critique). FastMCP validates Host on
    # /mcp; this middleware extends the same protection across the
    # whole FastAPI app. ``allowed_port=None`` accepts any port so
    # tests work; production binds to cfg.bind_port and the FastMCP
    # built-in pins the port on /mcp specifically.
    app.add_middleware(HostValidationMiddleware, allowed_port=None)
    # Origin validation: MCP 2025-06-18 spec MUST. E13_S05 wires
    # the ARXMCP_ALLOWED_ORIGINS env-var allow-list (extends the
    # hardcoded loopback floor; default empty = floor only).
    app.add_middleware(
        OriginValidationMiddleware,
        allowed_origins=cfg.allowed_origins,
    )
    # E13_S05 Threat 5 defense-in-depth: reject any Sec-Fetch-Site
    # value except `none` or absent. Mounted JUST INSIDE the
    # outermost SecurityHeaders so the cheap header check fires
    # first on browser-mediated probes.
    #
    # m7: the `/ui/*` REST + (future) HTML surface is exempt from
    # this check. The htmx UI running at `http://127.0.0.1:7733/ui/`
    # making a fetch() to `/ui/api/notebooks` is a same-origin
    # subresource — the browser sets `Sec-Fetch-Site: same-origin`,
    # which the default check 403s. The carve-out preserves the
    # DNS-rebinding defense on `/mcp` (still 403s same-origin) while
    # letting the in-page UI talk to the daemon. OriginValidation +
    # HostValidation still fire on `/ui/*` (Option A from synthesis).
    app.add_middleware(SecFetchSiteMiddleware, exempt_prefixes=("/ui",))
    # X-Content-Type-Options + X-Frame-Options on every response.
    app.add_middleware(SecurityHeadersMiddleware)

    # Health + readiness routes.
    app.include_router(health_router)

    # E08_S03: debug routes (currently just /debug/cache-stats). The
    # router is mounted under the /debug prefix so future debug
    # endpoints land under one operational path. NOT exempt from the
    # body-size cap — debug payloads must stay small.
    from server.routes.debug import router as debug_router

    app.include_router(debug_router, prefix="/debug")

    # proof-verify-handler-wiring-m7: per-notebook REST surface for
    # the htmx UI (m8 ships the templates). All routes are JSON-only
    # (and one HTML-fragment upload endpoint added in m8) and exempt
    # from SecFetchSiteMiddleware via the /ui carve-out above.
    # OriginValidation + HostValidation still apply.
    from server.routes.notebooks import router as notebooks_router

    app.include_router(notebooks_router, prefix="/ui/api")

    # proof-verify-handler-wiring-m8: HTML page routes for the htmx
    # UI shell. Templates live at frontend/templates/; static assets
    # (vendored htmx + CSS) at frontend/static/ mounted below.
    from server.routes.ui import router as ui_router

    app.include_router(ui_router, prefix="/ui")

    # m8: vendored htmx + CSS at /ui/static/. Mount inside the /ui
    # subtree so the SecFetchSite carve-out covers it without a
    # separate exemption. StaticFiles uses Starlette's built-in
    # path-traversal protection (`os.path.commonpath` check after
    # `realpath` resolution — see starlette/staticfiles.py:163).
    from fastapi.staticfiles import StaticFiles

    _FRONTEND_STATIC = Path(__file__).resolve().parent.parent / "frontend" / "static"
    app.mount(
        "/ui/static",
        StaticFiles(directory=str(_FRONTEND_STATIC)),
        name="ui-static",
    )

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
        from server.mcp_instructions import ARXMCP_INSTRUCTIONS
        from server.mcp_resources import register_resources
        from server.tools import register_all as register_all_tools

        # ``json_response=True`` makes responses single-shot
        # ``application/json`` rather than ``text/event-stream`` (SSE).
        # Required by the E06_S02 stdio shim. Design constitution
        # (``.claude/notes/06-mcp-server-design.md`` line 46): "No
        # protocol-level streaming of tool results."
        # notebook-surface-expansion-m5: ``instructions=`` sets the MCP
        # initialize.instructions hint orienting a connecting agent. This is
        # the server->client handshake field, NOT SYSTEM_PROMPT/BP1 — setting
        # it leaves tools/list + BP1 byte-identical (spike-1; pinned by
        # tests/test_mcp_instructions.py).
        mcp_server = FastMCP(
            "arxmcp", json_response=True, instructions=ARXMCP_INSTRUCTIONS
        )
        # E06_S03: tools MUST be registered BEFORE mount_mcp because
        # streamable_http_app() snapshots the registered tools at
        # mount time (synthesis D11).
        register_all_tools(mcp_server)
        # notebook-surface-expansion-m4: register notebooks as MCP
        # resources (resources/list + read). MUST be after tools and
        # BEFORE mount_mcp — same snapshot-at-mount constraint. Adds NO
        # tools, so the tools/list + BP1 hashes stay byte-identical
        # (spike-1 GO; pinned by tests/test_mcp_resources.py).
        register_resources(mcp_server)
        mount_mcp(app, mcp_server)
        # F2 fix (E06_S01): stash on app.state so the lifespan can
        # thread the session-manager lifespan into ours.
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
    #
    # E06_S05: wrap Config() + the env-var scan so a bad bind host
    # (or any other config validation failure) emits a FATAL log
    # AND exits with code 1, not a multi-screen pydantic stack. This
    # mirrors :func:`_build_module_app`'s wrapping for the uvicorn-
    # CLI path so both entry points fail identically. Closes the
    # brief AC: "Starting server with ARXMCP_BIND_HOST=0.0.0.0
    # exits with code 1 and a log message."
    import uvicorn

    # Configure logging BEFORE Config() so the FATAL log lands on
    # stderr even when the failure is in Config() itself.
    logging.basicConfig(level=os.environ.get("ARXMCP_LOG_LEVEL", "INFO"))
    try:
        cfg = Config()
        _scan_unknown_arxmcp_env_vars(cfg)
    except Exception as exc:
        logger.error("FATAL during config load: %s", exc)
        sys.stderr.write(f"FATAL: {exc}\n")
        sys.exit(1)

    # E13_S08 Threat 8 — install the RedactionFilter on the root
    # logger AND re-apply the level from Config (which may differ
    # from the env-var fallback used before Config() loaded). The
    # filter strips REDACTED_FIELDS (query, body_canonical,
    # body_raw_latex, mathml) from every log record at INFO+ level so
    # accidental leakage of paper content into the operational log is
    # blocked at the source. See
    # ``.claude/docs/security-observability-logging.md``.
    from server.observability.logging_setup import configure as _configure_logging
    # corpus-integrity-observability-e2: cfg.log_format ("json" default,
    # 12-factor) selects the JsonFormatter, installed on the same
    # redaction-filtered handler inside configure().
    _configure_logging(cfg.log_level, cfg.log_format)
    # E13_S05 Threat 5 — emit a WARN log at startup if the operator
    # has enabled the unsafe-network-bind escape hatch. This makes
    # the security trade-off VISIBLE in the operational log so an
    # operator can spot the misconfiguration in retrospect even if
    # they forgot they set the env var.
    if cfg.unsafe_network_bind:
        logger.warning(
            "ARXMCP_UNSAFE_NETWORK_BIND=1 is set; server binding to %r "
            "(non-loopback). Container deployments only — the host-side "
            "port mapping MUST still pin to 127.0.0.1. See "
            ".claude/docs/security-binding.md.",
            cfg.bind_host,
        )
    # E13_S07c Threat 7 — INFO log when CA pinning is on so the
    # operator sees the opt-in at startup. The bundle path was
    # already validated by ``Config.validate_arxiv_ca_bundle``
    # (fail-closed); this log line just makes the active pin
    # visible in the operational log.
    if cfg.pin_arxiv_ca:
        from server.ssl_pin import resolve_arxiv_ca_bundle
        logger.info(
            "ARXMCP_PIN_ARXIV_CA=1 set; using pinned CA bundle at %s "
            "for arxiv.org / ar5iv.labs.arxiv.org / export.arxiv.org "
            "fetches (Threat 7 mitigation #2). Refresh via "
            "`make refresh-arxiv-ca`.",
            resolve_arxiv_ca_bundle(cfg),
        )
        # E13_S07c v1 caller-side coverage caveat: the API surface
        # is wired (try_cache + fetch_eprint accept ssl_context) but
        # the existing production callers (bulk_ingest, fetch_seed,
        # fetch_one_paper, notebook_fetch) do NOT auto-thread the
        # context. Surface this WARN so an operator who sets the
        # flag sees the gap explicitly rather than assuming bulk
        # ingest is pinned. Full caller-side wiring is tracked as a
        # follow-up; see .claude/docs/security-threat-7-audit.md.
        logger.warning(
            "ARXMCP_PIN_ARXIV_CA=1 set, BUT existing production "
            "callers (ingest/bulk_ingest.py, tools/fetch_seed.py, "
            "tools/fetch_one_paper.py, tools/notebook_fetch.py) do "
            "NOT auto-thread the SSLContext. Bulk-ingest paths will "
            "still use the system trust store. See "
            ".claude/docs/security-threat-7-audit.md \"Caller-side "
            "coverage\" for the workaround. Tracked as follow-up."
        )
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
