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

**Run via**: the ``arxmcp-server`` console script (issue #206), or
``python -m server.main``, or ``make up`` — all three are the same code
path and all honor ``ARXMCP_BIND_HOST`` / ``ARXMCP_BIND_PORT`` via
:class:`Config`. The startup sequence itself lives in
:func:`server.cli.main`; the ``__main__`` block at the bottom of this
module only delegates to it. The ``uvicorn server.main:app`` CLI form also
works but does NOT honor the env-var bind overrides — closes IS3+IS4 from
the E06_S01 critique.

Note the module-level ``app`` below is built as an import side effect, so
anything wanting to invoke the CLI must import :mod:`server.cli` (which
defers this module's import into the function body) rather than importing
this module — otherwise ``arxmcp-server --help`` would construct the whole
app before argparse ran.

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
import difflib
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

from server import session
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
    """Return True if ``path`` should bypass the body-size cap.

    notebook-surface-expansion-m6 (rect F2): the per-notebook export route
    ``GET /ui/api/notebooks/<slug>/export`` streams a deterministic tar
    (PDFs + ar5iv HTML + per-notebook LanceDB + a manifest) that routinely
    exceeds 256 KB. The exemption is **segment-exact** — ONLY
    ``/ui/api/notebooks/<slug>/export`` matches (5 segments after the leading
    ``/``); a hypothetical multi-segment future sub-route like
    ``/ui/api/notebooks/<slug>/papers/<pid>/export`` does NOT inherit the
    exemption (m6-rect F2 closure: a path-suffix check would over-exempt).
    Every other notebook API path stays under the 256 KB cap as
    defense-in-depth.
    """
    if path.startswith("/ui/api/notebooks/") and path.endswith("/export"):
        parts = path.split("/")
        # ["", "ui", "api", "notebooks", "<slug>", "export"] — exactly 6 parts.
        if len(parts) == 6 and parts[5] == "export":
            return True
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


#: Known-but-server-unsupported ``ARXMCP_*`` env vars that come from
#: CLI / ingest-pipeline tools, NOT from the server's :class:`Config`.
#: Setting one of these before ``make up`` is a predictable footgun
#: (the docs used to tell operators to do exactly that — closed by
#: ``onboarding-uplift-m1``); the scan still rejects them — they would
#: silently bypass the server's documented config — but with a tailored
#: carve-out message that names the tools that DO consume the var, so
#: the operator can unset it for the server and use it where it's
#: meaningful.
#:
#: Maps env-var name → human-readable hint. To add a new ingest-tool
#: var, append an entry here; ``_format_unknown_arxmcp_env_var``
#: prefers this lookup over the generic ``difflib`` suggestion. Keys
#: must be ``ARXMCP_*``-prefixed (the scan only inspects that
#: namespace).
_KNOWN_INGEST_ENV_VARS: dict[str, str] = {
    # m1 critique F1: the prior version named 3 of 5 actual consumers
    # and omitted ``tools/fetch_seed.py`` — the very tool the README
    # quick-start runs at line 51, which is the most likely path a
    # user follows before hitting this error. Now lists every direct
    # ``os.environ.get("ARXMCP_CONTACT_EMAIL")`` reader: the
    # ``tools/arxiv_fetch.py`` shared library (consumed transitively
    # by ``tools/fetch_seed.py``, ``tools/fetch_one_paper.py``,
    # ``tools/curate_seed.py``) + the two notebook-stage tools that
    # call it directly + the two ingest CLIs.
    "ARXMCP_CONTACT_EMAIL": (
        "is NOT a server config var; it is read by the arXiv-facing "
        "CLI tools (tools/arxiv_fetch.py library + "
        "tools/fetch_seed.py, tools/notebook_fetch.py, "
        "tools/recover_preambles.py; ingest/inspire_ingest.py and "
        "ingest/graph_ingest.py) for the arXiv polite-pool User-Agent. "
        "Unset it for the server."
    ),
    "ARXMCP_LATEXML_TIMEOUT_S": (
        "is NOT a server config var; it is read at import by the "
        "textbook-ingest CLI path (tools/arxiv_fetch.py "
        "parse_with_latexml + ingest/textbook_renderer.py "
        "render_mineru_to_html) to cap the LaTeXML render wall-clock "
        "for math-dense PDFs. The server never invokes LaTeXML. "
        "Unset it for the server."
    ),
    # ingest-robustness-m1 AC3: MinerU is a textbook/PDF ingest-side concern
    # (ingest/textbook_parser.py). The server never invokes MinerU. Prefer
    # persisting the binary path via `make init MINERU_BIN=…` (operator_settings)
    # over exporting the env var, so `make up` never trips the unknown-var scan.
    "ARXMCP_MINERU_BIN": (
        "is NOT a server config var; it is read at parse time by the "
        "textbook/PDF ingest path (ingest/textbook_parser.py "
        "_resolve_mineru_binary) to locate the mineru CLI. Prefer persisting "
        "it via `make init MINERU_BIN=<abs path>` (operator_settings) so no "
        "export is needed. Unset it for the server."
    ),
    "ARXMCP_MINERU_TIMEOUT_S": (
        "is NOT a server config var; it is read at import by the "
        "textbook/PDF ingest path (ingest/textbook_parser.py) to cap the "
        "MinerU parse wall-clock. The server never invokes MinerU. "
        "Unset it for the server."
    ),
}


def _format_unknown_arxmcp_env_var(
    env_name: str, declared: frozenset[str]
) -> str:
    """Build a one-/two-line human-readable hint for a single unknown
    ``ARXMCP_*`` env var.

    Branches in priority order (per ``onboarding-uplift-m1`` synthesis
    §3 D1 + D2):

    1. **Ingest-tool carve-out.** ``ARXMCP_CONTACT_EMAIL`` and any
       future ingest-pipeline var registered in
       ``_KNOWN_INGEST_ENV_VARS`` gets a tailored "this is a CLI-tool
       var; unset it for the server" message naming the modules that
       DO consume it.
    2. **Close-match suggestion.** ``difflib.get_close_matches`` with
       ``n=1, cutoff=0.7`` over the declared set. ``0.7`` is tighter
       than Python's ``0.6`` default — preferred per m1 synthesis D2:
       a wrong suggestion (e.g. ``ARXMCP_BIND_HOTS`` → ``ARXMCP_KUZU_PATH``)
       is worse UX than no suggestion at all. Genuine typos (transposed
       / dropped characters) still clear ``0.7``.
    3. **Short-form fallback.** No close match → list the top-3 nearest
       declared vars at ``cutoff=0.0`` so the operator can scan for a
       likely intent without the full 32-var dump.

    Output is intentionally compact: the scan fires before
    ``logging.basicConfig`` on the uvicorn-import path (FM-3), so the
    user sees one block via ``sys.stderr.write`` in
    ``_build_module_app``. Multi-paragraph prose would be lost.
    """
    carve_out_hint = _KNOWN_INGEST_ENV_VARS.get(env_name)
    if carve_out_hint is not None:
        return f"  - {env_name} {carve_out_hint}"

    # Close-match suggestion (D2: tighter cutoff than the default 0.6).
    suggestions = difflib.get_close_matches(
        env_name, sorted(declared), n=1, cutoff=0.7
    )
    if suggestions:
        return f"  - {env_name}: did you mean {suggestions[0]}?"

    # Short-form fallback — top 3 nearest at cutoff=0.0, NOT the full
    # 32-var dump. ``cutoff=0.0`` still applies SequenceMatcher ordering;
    # an empty result here is only possible when ``declared`` itself is
    # empty (impossible at runtime — Config has 32 declared fields).
    nearest = difflib.get_close_matches(
        env_name, sorted(declared), n=3, cutoff=0.0
    )
    if nearest:
        return (
            f"  - {env_name} is not a declared ARXMCP_* var; nearest: "
            f"{', '.join(nearest)}. Full list: server/config.py::Config."
        )
    return (  # pragma: no cover — declared is non-empty at runtime
        f"  - {env_name} is not a declared ARXMCP_* var. See "
        f"server/config.py::Config for the full list."
    )


def _scan_unknown_arxmcp_env_vars(config: Config) -> None:
    """Reject any ``ARXMCP_*`` env var not declared on :class:`Config`.

    Closes F4 from the E06_S01 critique. ``pydantic-settings``'s
    ``extra="forbid"`` only fires for direct ``__init__`` kwargs —
    NOT for env-var input. So a typo like ``ARXMCP_BIND_HOST_TYPO``
    is silently ignored at the Pydantic layer. This scan walks
    ``os.environ`` for every ``ARXMCP_*`` key and asserts it maps to
    a declared field. (The original docstring also cited
    ``ARXMCP_OTEL_ENDPOINT`` as an example of the "documented-but-
    unimplemented" class — m1 critique F2: ``ARXMCP_OTEL_ENDPOINT``
    is now declared on ``Config`` (E14 observability landed) and
    would be accepted, so the example was retired.)

    ``onboarding-uplift-m1`` replaces the prior 30-line declared-var
    dump with per-var hints: an ingest-tool carve-out for
    ``ARXMCP_CONTACT_EMAIL`` (the documented footgun the m1 doc sweep
    removed from CLAUDE.md / README.md / Makefile), a
    ``difflib.get_close_matches`` (``n=1, cutoff=0.7``) suggestion for
    typos like ``ARXMCP_BIND_HOTS``, and a short-form "nearest 3"
    fallback otherwise. The dynamic ``Config.model_fields`` source is
    preserved — adding a new ``Config`` field automatically extends
    ``declared`` (m1 synthesis FM-5 mitigation).
    """
    declared = frozenset(
        f"ARXMCP_{name.upper()}" for name in Config.model_fields
    )
    unknown = sorted(
        env_name
        for env_name in os.environ
        if env_name.startswith("ARXMCP_") and env_name not in declared
    )
    if not unknown:
        return
    hints = "\n".join(
        _format_unknown_arxmcp_env_var(name, declared) for name in unknown
    )
    raise ValueError(
        "unknown ARXMCP_* environment variables — each would silently "
        "bypass the documented config; fix or remove:\n" + hints
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
    # onboarding-uplift-m4 F1: skip metrics refresh in bootstrap mode.
    # corpus_info is None in bootstrap mode; refresh_metrics_from_singleton_state
    # now guards corpus_info reads internally, but the belt-and-suspenders
    # check here avoids the scrape overhead when there's nothing to report.
    if not getattr(resources, "bootstrap_mode_active", False):
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
        # onboarding-uplift-m4: closure binds the tracker to
        # resources.late_bind so a successful first ingest promotes
        # the server from bootstrap mode to normal operation without
        # a restart.
        async def _on_ingest_success(_slug: str) -> None:
            await resources.late_bind(config)

        app.state.ingest_tracker = IngestTaskTracker(
            on_success_callback=_on_ingest_success,
        )
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

    # agent-platform-m1: push the operator-configured per-tool session
    # caps into server.session's module globals BEFORE the middleware
    # stack is built — SessionCapMiddleware reads them per request, so
    # this must land before the first request, not before construction.
    session.configure_caps(cfg)

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
    # The body that used to live here — Config load, env-var scan, logging
    # setup, the Threat-5 / Threat-7 startup warnings, and uvicorn.run —
    # moved to ``server/cli.py`` when issue #206 added the ``arxmcp-server``
    # console script. It is NOT duplicated here: two entry points running
    # two copies of the startup sequence is exactly how a security warning
    # ends up firing on one path and not the other.
    #
    # ``python -m server.main`` therefore remains equivalent to
    # ``arxmcp-server``, and both honor ARXMCP_BIND_HOST / ARXMCP_BIND_PORT
    # via Config (IS3+IS4) rather than hardcoded uvicorn CLI flags.
    from server.cli import main as _cli_main

    raise SystemExit(_cli_main())


__all__ = [
    "BodySizeCapMiddleware",
    "_scan_unknown_arxmcp_env_vars",
    "app",
    "create_app",
    "lifespan",
]
