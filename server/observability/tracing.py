"""OpenTelemetry tracing — one parent span per JSON-RPC tool call,
child spans for embed / ANN / rerank (E14_S02).

The span hierarchy gives end-to-end latency visibility across the
retrieval pipeline: the parent span scopes a ``tools/call``, and
child spans scope the BGE-M3 forward pass, the LanceDB ANN query,
and the BGE-reranker-v2-m3 cross-encoder call.

**Tracing disabled is the default.** When
:data:`server.config.Config.otel_endpoint` is ``None``,
:func:`setup_tracing` returns without registering a
:class:`opentelemetry.sdk.trace.TracerProvider`. Every
``tracer.start_as_current_span(...)`` then takes the
:class:`opentelemetry.trace.ProxyTracer` → ``NoOpTracer`` fast
path with zero allocation. This is strictly better than
registering a ``NoOpTracerProvider`` because it skips even the
provider-lookup machinery.

**ContextVar plumbing.** ``Mcp-Session-Id`` and
``Arxmcp-Agent-Role`` are HTTP request headers consumed by
:class:`server.middleware.TracingContextMiddleware` and surfaced
through :data:`current_session_id` / :data:`current_agent_role`
ContextVars. Handlers update :data:`current_cache_layer` when a
cache hit fires; the parent span reads the ContextVar
just-in-time in its ``finally`` block so the
``arxmcp.cache_layer_served`` attribute reflects the actual
served path.

**OTel semantic conventions vs project-private namespace.** OTel
GenAI semantic conventions are still "Development"-stability;
we adopt ``gen_ai.request.model`` (the model NAME on embed/rerank
child spans) where it exists in semconv, and use the
project-private ``arxmcp.*`` namespace for everything else,
including ``arxmcp.model.revision`` (commit SHA — no semconv
equivalent). The complete attribute catalog lives in
``.claude/docs/observability-tracing.md``.

**Cache-layer enum.** The OTel attribute uses
``tier1|tier2|tier3|miss`` — matches the Prometheus surface
:func:`server.metrics.CACHE_HITS_COUNTER` label space. The
``08-security-observability-ops.md`` constitution note's legacy
``exact|semantic|rerank|miss`` enumeration is updated in
lockstep with this milestone (E14_S02 synthesis D6).
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

if TYPE_CHECKING:
    from collections.abc import Iterator

    from opentelemetry.trace import Span

    from server.config import Config


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Service-name attribute on the ``Resource`` attached to every span.
#: Surfaces in Phoenix's service picker.
SERVICE_NAME: str = "arxmcp-server"

#: Service-version attribute. Bumped when the project versions; the
#: integer ``corpus_version`` is a SPAN attribute, not a Resource
#: attribute, because it can change at startup-time across deploys.
SERVICE_VERSION: str = "0.1.0"

#: Default OTLP/gRPC port. Phoenix's default OTLP intake also lives
#: here. The HTTP/protobuf variant (OTLP/HTTP) defaults to 4318; we
#: pin gRPC.
OTLP_DEFAULT_PORT: int = 4317

#: TCP-connect timeout for the startup endpoint probe. 1 second is
#: long enough to reach a localhost or sidecar Phoenix; short
#: enough that a misconfigured endpoint doesn't delay startup
#: meaningfully.
PROBE_TIMEOUT_S: float = 1.0

#: OpenInference span-kind attribute name. Phoenix's
#: retrieval-evaluation view (the "top-k chunks with scores +
#: reranker output" UI named in the E14_S03 brief AC) is gated by
#: this attribute being present. Without it, Phoenix renders the
#: span as a generic OTel span and the table-of-documents view
#: does not appear. Cite OpenInference *Semantic Conventions*:
#: *"openinference.span.kind … is required for all OpenInference
#: spans. It provides a hint to the tracing backend as to how the
#: trace should be assembled."* Supported values:
#: ``LLM``/``EMBEDDING``/``CHAIN``/``RETRIEVER``/``RERANKER``/
#: ``TOOL``/``AGENT``/``GUARDRAIL``/``EVALUATOR``/``PROMPT``.
OPENINFERENCE_SPAN_KIND: str = "openinference.span.kind"


# ---------------------------------------------------------------------------
# ContextVars — plumb session_id / agent_role / cache_layer
# ---------------------------------------------------------------------------

#: Current ``Mcp-Session-Id`` for the in-flight HTTP request. Set by
#: :class:`server.middleware.TracingContextMiddleware` at ASGI scope
#: entry; reset on scope exit. Read by :func:`span_tool_call` to
#: populate ``mcp.session_id`` on the parent span.
current_session_id: ContextVar[str | None] = ContextVar(
    "current_session_id", default=None
)

#: Allow-list for the ``Arxmcp-Agent-Role`` header. F2 rectification
#: from the E14_S02 adversary critique — without an allow-list, any
#: 64 KB string was admitted, blowing up span cardinality + opening a
#: log-injection / Phoenix-cardinality DoS vector. The canonical four
#: roles match the multi-agent pipeline documented in
#: :doc:`.claude/notes/01-mission-and-context.md` (Sketcher →
#: Autoformalizer → Tactician → Fixer). Header values outside this set
#: are dropped at the middleware layer with a DEBUG log.
VALID_AGENT_ROLES: frozenset[str] = frozenset(
    {"sketcher", "autoformalizer", "tactician", "fixer"}
)

#: Maximum byte length the middleware will read from any tracing-
#: related header (``Mcp-Session-Id``, ``Arxmcp-Agent-Role``). Real
#: values are at most a few dozen bytes; the cap is defense-in-depth
#: against an oversized-header memory-pressure vector.
MAX_HEADER_BYTES: int = 256

#: Allow-list for cache-layer enum values. F7 rectification — without
#: this, ``set_cache_layer("Tier1")`` silently leaked into Phoenix as a
#: distinct attribute value, polluting cardinality. The canonical set
#: matches :data:`server.metrics.ALL_TIERS` plus the ``"miss"`` zero-
#: hit terminal.
VALID_CACHE_LAYERS: frozenset[str] = frozenset(
    {"tier1", "tier2", "tier3", "miss"}
)

#: Sentinel for ``arxmcp.corpus_version`` when Resources have not yet
#: warmed at the time the parent span opens. F4 rectification — the
#: prior behaviour silently OMITTED the attribute, making the
#: startup-race failure mode invisible. Operators querying for
#: ``arxmcp.corpus_version="resources-not-ready"`` see the race
#: directly.
CORPUS_VERSION_RESOURCES_NOT_READY: str = "resources-not-ready"

#: Current ``Arxmcp-Agent-Role`` (e.g. ``sketcher``, ``tactician``,
#: ``fixer``, ``autoformalizer``) for the in-flight request. Set by
#: the same middleware; read by :func:`span_tool_call`.
#:
#: Why a header and NOT a JSON-Schema property: adding ``_agent_role``
#: as a first-class JSON-Schema property on every tool would bump
#: :data:`server.tools.TOOL_SCHEMA_VERSION` and invalidate the BP1
#: prompt-cache for every existing agent prefix
#: (``07-multi-agent-caching.md`` Property 1). The header keeps
#: TOOL_SCHEMA_VERSION pinned at 6. The brief's wording
#: "documented in the tool schema but not required" is interpreted
#: as "the attribute is documented" not "a JSON-Schema property
#: must exist" — see E14_S02 synthesis D7.
current_agent_role: ContextVar[str | None] = ContextVar(
    "current_agent_role", default=None
)

#: Current cache layer that served the in-flight request. Default
#: ``"miss"``; handlers call :func:`set_cache_layer` to update on a
#: hit. Read by the parent span just-in-time in its ``finally``
#: block so a late-detected hit still surfaces on the attribute.
current_cache_layer: ContextVar[str] = ContextVar(
    "current_cache_layer", default="miss"
)

#: stage2/arx-a23 (WS-A A3, gap R5): always-on lightweight phase
#: timings for the in-flight tool call, keyed by phase name
#: (``embed`` / ``ann`` / ``bm25`` / ``rerank``), values = cumulative
#: seconds. ``server.tools._wrap_with_observability`` sets a fresh
#: dict at call entry and folds the result into the request event at
#: exit; the child-span helpers below record into it via
#: :func:`_record_phase_seconds`. Independent of
#: ``ARXMCP_OTEL_ENDPOINT`` — the perf_counter capture runs whether
#: or not the OTel spans are no-ops, which is exactly the R5
#: requirement ("reuse the span seams, not the exporter").
current_phase_timings: ContextVar[dict[str, float] | None] = ContextVar(
    "current_phase_timings", default=None
)


def _record_phase_seconds(phase: str, seconds: float) -> None:
    """Accumulate ``seconds`` under ``phase`` on the in-flight timing
    dict. No-op when no tool call is in flight (the ContextVar is
    None — e.g. ingest-side embed calls)."""
    timings = current_phase_timings.get()
    if timings is not None:
        timings[phase] = timings.get(phase, 0.0) + seconds


def _validate_agent_role(raw: str | None) -> str | None:
    """Apply the ``Arxmcp-Agent-Role`` allow-list + length cap.

    Mirrors :class:`server.middleware.TracingContextMiddleware`'s
    validation byte-for-byte so the request-ring event and the
    session-cap roster agree on the role for the SAME call. Unknown or
    oversized values fall back to ``None`` (no role attribute)."""
    if raw is None:
        return None
    if len(raw.encode("utf-8")) > MAX_HEADER_BYTES or raw not in VALID_AGENT_ROLES:
        return None
    return raw


def resolve_request_identity() -> tuple[str | None, str | None]:
    """Return ``(session_id, agent_role)`` for the in-flight tool call.

    **Why not just read the ContextVars.** ``current_session_id`` /
    ``current_agent_role`` are set per-HTTP-request by
    :class:`server.middleware.TracingContextMiddleware`. But the MCP
    Streamable-HTTP session manager (``mcp.server.streamable_http_manager``)
    runs every ``tools/call`` on a long-lived per-session task that was
    started — and whose ``contextvars.Context`` was captured — at
    ``initialize`` time. At ``initialize`` the ``Arxmcp-Agent-Role``
    header exists but the ``Mcp-Session-Id`` has not been minted yet.
    Reading the ContextVars from inside the handler therefore yields
    ``session_id=None`` and the role frozen to the initialize-time
    value, no matter what the actual ``tools/call`` request carried.
    That is the stage3/cross-r1 bug the request-ring SESSION column and
    the Connections roster ``requests`` cross-link surfaced (row
    ``session_id=null``, dead-end empty state, role/lane contradiction).

    **The fix.** The MCP low-level server stamps a fresh
    :class:`mcp.shared.context.RequestContext` into its ``request_ctx``
    ContextVar for EACH JSON-RPC message, carrying the Starlette
    ``Request`` for THAT ``tools/call`` HTTP request (with its true
    per-call ``Mcp-Session-Id`` + ``Arxmcp-Agent-Role`` headers — see
    ``streamable_http.py`` ``ServerMessageMetadata(request_context=request)``
    and ``lowlevel/server.py`` ``request_ctx.set(...)``). We read the
    identity from those per-call headers first (applying the identical
    validation the middleware applies), and fall back to the ContextVars
    only when no MCP request context is present (direct handler calls in
    unit tests, or non-``/mcp`` code paths). This keeps the ring and the
    roster reading the SAME source of truth for a given call.

    Best-effort: any failure resolving the MCP context falls back to the
    ContextVars. Observability must never break the request path.
    """
    ctx_session = current_session_id.get()
    ctx_role = current_agent_role.get()
    try:
        # Lazy import — avoids a module-load cycle
        # (mcp.server.__init__ -> fastmcp -> server.tools -> tracing).
        from mcp.server.lowlevel.server import request_ctx  # noqa: PLC0415

        req_ctx = request_ctx.get()
    except (ImportError, LookupError):
        # LookupError: the ContextVar has no value in this context
        # (no MCP request in flight). ImportError: mcp not importable.
        return ctx_session, ctx_role

    request = getattr(req_ctx, "request", None)
    headers = getattr(request, "headers", None)
    if headers is None:
        return ctx_session, ctx_role

    # Starlette Headers.get is case-insensitive; the transport injects
    # the client-supplied values verbatim for this specific call.
    try:
        raw_sid = headers.get("mcp-session-id")
        raw_role = headers.get("arxmcp-agent-role")
    except Exception:  # noqa: BLE001 — never break the request path
        return ctx_session, ctx_role

    # Strict ASCII discipline mirrors the middleware's
    # ``_decode_header_strict`` (Starlette already str-decodes headers;
    # reject non-ASCII to match the middleware's None-on-garbage rule).
    session_id: str | None = ctx_session
    if raw_sid is not None:
        try:
            raw_sid.encode("ascii")
            session_id = raw_sid
        except UnicodeEncodeError:
            session_id = None
    role = ctx_role
    if raw_role is not None:
        try:
            raw_role.encode("ascii")
            role = _validate_agent_role(raw_role)
        except UnicodeEncodeError:
            role = None
    return session_id, role


# ---------------------------------------------------------------------------
# Setup / shutdown
# ---------------------------------------------------------------------------

#: Module-level guard that records whether :func:`setup_tracing`
#: has succeeded in this process. Used by :func:`shutdown_tracing`
#: to decide whether a force-flush is meaningful.
_provider_installed: bool = False
_setup_lock: threading.Lock = threading.Lock()


def setup_tracing(config: Config) -> None:
    """Install the OTel ``TracerProvider`` + ``BatchSpanProcessor``
    when :data:`server.config.Config.otel_endpoint` is set.

    When unset, returns immediately. Every subsequent
    ``tracer.start_as_current_span(...)`` takes the OTel SDK's
    no-op fast path; this is the documented "tracing disabled"
    idiom (synthesis D2 / D5).

    Idempotent across re-calls in the same process: a duplicate
    call logs INFO and returns. The OTel SDK itself warns-and-
    no-ops on a second ``trace.set_tracer_provider(...)`` call;
    we short-circuit before reaching that point so the test
    fixture pattern (process-shared provider, per-test exporter
    reset) works cleanly.
    """
    global _provider_installed

    endpoint = config.otel_endpoint
    if not endpoint:
        logger.info(
            "tracing.disabled.no_endpoint "
            "(ARXMCP_OTEL_ENDPOINT unset; spans no-op)"
        )
        return

    with _setup_lock:
        if _provider_installed:
            logger.info(
                "tracing.setup.already_installed; skipping re-registration"
            )
            return

        # Best-effort 1-second TCP probe. Failure logs a single
        # WARN but DOES NOT block registration — the exporter
        # keeps retrying so traces flow when Phoenix wakes
        # mid-process. Closes the brief AC "OTel endpoint
        # unreachable → server continues operating; WARN logged
        # once at startup".
        if not _probe_endpoint(endpoint):
            logger.warning(
                "tracing.endpoint_unreachable; will retry lazily on first export "
                "(endpoint=%s)",
                endpoint,
            )

        resource = Resource.create(
            {
                "service.name": SERVICE_NAME,
                "service.version": SERVICE_VERSION,
            }
        )
        provider = TracerProvider(resource=resource)
        # Lazy-import the OTLP exporter to keep import-time cost
        # off any module that imports server.observability.tracing
        # but doesn't actually need the SDK (the exporter pulls
        # grpcio which is ~5 MB).
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # noqa: PLC0415
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _provider_installed = True
        logger.info(
            "tracing.enabled (endpoint=%s service=%s)",
            endpoint,
            SERVICE_NAME,
        )


def shutdown_tracing() -> None:
    """Force-flush the ``BatchSpanProcessor`` so in-flight spans
    export before the process exits.

    Called from the lifespan shutdown AFTER ``resources.shutdown()``
    returns. No-op when :func:`setup_tracing` was never called (the
    default in tests + the no-endpoint production case).

    F5 rectification (E14_S02 adversary): dropped the unused
    ``timeout_s`` parameter. ``TracerProvider.shutdown`` does not
    expose a timeout argument; the flush time is bounded by the
    ``BatchSpanProcessor``'s ``schedule_delay_millis``. A real
    bounded-shutdown story (running the call in a thread with
    ``join(timeout=...)``) is a follow-up — pretending the parameter
    was honoured was misleading.
    """
    if not _provider_installed:
        return
    provider = trace.get_tracer_provider()
    if hasattr(provider, "shutdown"):
        # ``TracerProvider.shutdown`` flushes the BatchSpanProcessor
        # then closes the exporter. The OTel SDK does not document a
        # timeout argument on shutdown; flush timing is bounded by the
        # processor's own ``schedule_delay_millis``.
        try:
            provider.shutdown()
        except Exception:
            logger.warning(
                "tracing.shutdown_failed; some spans may not have exported",
                exc_info=True,
            )


def _probe_endpoint(endpoint: str, timeout_s: float = PROBE_TIMEOUT_S) -> bool:
    """Return True iff a TCP connect to ``endpoint`` succeeds within
    ``timeout_s`` seconds. Used by :func:`setup_tracing` to detect a
    down Phoenix at startup and log a single WARN.

    Failure modes returning False: ``ConnectionRefusedError``,
    ``socket.timeout``, ``socket.gaierror`` (DNS resolution), and
    other ``OSError`` subclasses (``EHOSTUNREACH`` / ``ENETUNREACH``).
    All of these inherit from ``OSError`` in Python 3.10+, so the
    single ``except OSError`` is intentional and complete (F6
    rectification from the E14_S02 adversary critique). ``ValueError``
    catches a malformed URL where ``parsed.port`` raises during
    parsing. The probe never raises — observability code must never
    crash the host process.
    """
    try:
        parsed = urlparse(endpoint)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or OTLP_DEFAULT_PORT
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except (OSError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Parent span — one per JSON-RPC tool call
# ---------------------------------------------------------------------------


@contextmanager
def span_tool_call(
    tool_name: str,
    *,
    corpus_version: int | str | None = None,
    k: int | None = None,
) -> Iterator[Span]:
    """Yield the parent OTel span for one JSON-RPC ``tools/call``.

    Reads the session id + agent role via
    :func:`resolve_request_identity` (the true per-``tools/call``
    headers from the MCP request context, falling back to the
    :class:`server.middleware.TracingContextMiddleware` ContextVars for
    non-MCP call paths). Reads
    :data:`current_cache_layer` in the ``finally`` block so a
    handler that detects a Tier-N cache hit late in its execution
    still surfaces on the parent span.

    When tracing is disabled (``setup_tracing`` was never called),
    the underlying ``tracer.start_as_current_span(...)`` returns a
    no-op span and the yielded object's ``set_attribute`` calls are
    cheap no-ops.

    Closes :doc:`.claude/notes/08-security-observability-ops.md`
    §Tracing requirements:

    - ``mcp.session_id``
    - ``mcp.tool_name``
    - ``arxmcp.cache_layer_served`` (set on exit from ContextVar)
    - ``arxmcp.corpus_version``
    - ``arxmcp.k``
    - ``arxmcp.agent_role``
    """
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("mcp.tool_call") as span:
        # E14_S03 D4: OpenInference span-kind gates Phoenix's
        # retrieval-evaluation view. The parent JSON-RPC tool call
        # is a CHAIN that orchestrates embed + retrieve + rerank
        # child spans.
        span.set_attribute(OPENINFERENCE_SPAN_KIND, "CHAIN")
        span.set_attribute("mcp.tool_name", tool_name)
        # stage3/cross-r1: resolve from the MCP per-request context (the
        # true per-``tools/call`` headers), not the ContextVars — the
        # session task's captured context freezes them at initialize
        # (session_id=None, initialize-time role). Keeps the parent span
        # in agreement with the request-ring event + the session roster.
        sid, role = resolve_request_identity()
        if sid is not None:
            span.set_attribute("mcp.session_id", sid)
        if role is not None:
            span.set_attribute("arxmcp.agent_role", role)
        if corpus_version is not None:
            span.set_attribute("arxmcp.corpus_version", corpus_version)
        if k is not None:
            span.set_attribute("arxmcp.k", k)
        try:
            yield span
        finally:
            # Late binding — the handler may have called
            # set_cache_layer("tier1") between span entry and now.
            span.set_attribute(
                "arxmcp.cache_layer_served", current_cache_layer.get()
            )


def set_cache_layer(layer: str) -> None:
    """Set :data:`current_cache_layer` to ``layer`` for the in-flight
    request. Accepts the values in :data:`VALID_CACHE_LAYERS`
    (``"tier1" | "tier2" | "tier3" | "miss"``) — matches the
    Prometheus :data:`server.metrics.CACHE_HITS_COUNTER` label space
    and the OTel attribute enum (synthesis D6).

    F7 rectification (E14_S02 adversary): unknown values are
    REJECTED — logged at DEBUG and ignored. The prior ``current_cache_layer``
    value is preserved. This closes the operator-typo cardinality
    leak that the prior "free-form" behaviour permitted.

    Called from cache handlers (typically inside
    ``server/handlers/search.py``) when a tier hit is detected.
    """
    if layer not in VALID_CACHE_LAYERS:
        logger.debug(
            "set_cache_layer: rejected unknown value %r "
            "(allowed: %s); leaving prior value %r intact.",
            layer,
            sorted(VALID_CACHE_LAYERS),
            current_cache_layer.get(),
        )
        return
    current_cache_layer.set(layer)


# ---------------------------------------------------------------------------
# Child spans
# ---------------------------------------------------------------------------


@contextmanager
def span_embed(model_name: str, model_revision: str) -> Iterator[Span]:
    """Child span for one BGE-M3 query encoding forward pass.

    ``gen_ai.request.model`` adopts the OTel GenAI semconv name
    (still "Development"-stability — see synthesis D5).
    ``arxmcp.model.revision`` carries the commit SHA — no semconv
    equivalent exists for that. ``openinference.span.kind=EMBEDDING``
    gates the Phoenix embedding-stats view (E14_S03 D4).

    stage2/arx-a23 (gap R5): also records wall-clock seconds into
    :data:`current_phase_timings` (key ``embed``), independent of the
    OTel exporter state.
    """
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("arxmcp.embed") as span:
        span.set_attribute(OPENINFERENCE_SPAN_KIND, "EMBEDDING")
        span.set_attribute("gen_ai.request.model", model_name)
        span.set_attribute("arxmcp.model.revision", model_revision)
        t0 = time.perf_counter()
        try:
            yield span
        finally:
            _record_phase_seconds("embed", time.perf_counter() - t0)


@contextmanager
def span_ann(k: int | None = None) -> Iterator[Span]:
    """Child span for the LanceDB ANN vector search.

    ``openinference.span.kind=RETRIEVER`` gates the Phoenix
    retrieval-evaluation view that lists top-k chunks with scores
    (E14_S03 D4). Phase timing recorded under key ``ann`` (gap R5).
    """
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("arxmcp.ann") as span:
        span.set_attribute(OPENINFERENCE_SPAN_KIND, "RETRIEVER")
        if k is not None:
            span.set_attribute("arxmcp.k", k)
        t0 = time.perf_counter()
        try:
            yield span
        finally:
            _record_phase_seconds("ann", time.perf_counter() - t0)


@contextmanager
def span_bm25(k: int | None = None) -> Iterator[Span]:
    """Child span for the BM25 sparse search (forward-compat for
    E07_S04+; v1 ``search_papers`` is dense-only and never enters
    this span). ``openinference.span.kind=RETRIEVER`` mirrors
    :func:`span_ann` — both are retrieval phases. Phase timing under
    key ``bm25`` (gap R5)."""
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("arxmcp.bm25") as span:
        span.set_attribute(OPENINFERENCE_SPAN_KIND, "RETRIEVER")
        if k is not None:
            span.set_attribute("arxmcp.k", k)
        t0 = time.perf_counter()
        try:
            yield span
        finally:
            _record_phase_seconds("bm25", time.perf_counter() - t0)


@contextmanager
def span_rerank(model_name: str, model_revision: str) -> Iterator[Span]:
    """Child span for one BGE-reranker-v2-m3 cross-encoder forward
    pass. ``openinference.span.kind=RERANKER`` gates the Phoenix
    rerank-quality view (E14_S03 D4). Phase timing under key
    ``rerank`` (gap R5)."""
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("arxmcp.rerank") as span:
        span.set_attribute(OPENINFERENCE_SPAN_KIND, "RERANKER")
        span.set_attribute("gen_ai.request.model", model_name)
        span.set_attribute("arxmcp.model.revision", model_revision)
        t0 = time.perf_counter()
        try:
            yield span
        finally:
            _record_phase_seconds("rerank", time.perf_counter() - t0)


@contextmanager
def span_summarize() -> Iterator[Span]:
    """Child span for the Haiku-API-backed summarizer. Reserved
    helper — note 07 lines 236-244 permanently dropped the
    in-server summarizer, so v1 never enters this span. Kept for
    forward-compat: a future tier may re-introduce a summarizer
    and the helper is then a one-line wrap point.
    ``openinference.span.kind=LLM`` for that future caller."""
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("arxmcp.summarize") as span:
        span.set_attribute(OPENINFERENCE_SPAN_KIND, "LLM")
        yield span


# ---------------------------------------------------------------------------
# Test-only reset helpers
# ---------------------------------------------------------------------------


def reset_tracing_for_tests() -> None:
    """Reset the module-level installation guard to ``False`` so a
    subsequent :func:`setup_tracing` call in the same process
    succeeds. Test-only; production paths must never call this.

    Note this does NOT reset OTel's own
    ``trace._TRACER_PROVIDER`` global — that variable is
    write-once per process. Tests that need a fresh provider must
    use the module-scoped fixture pattern (one provider per test
    process, ``InMemorySpanExporter.clear()`` between tests).
    """
    global _provider_installed
    _provider_installed = False


__all__ = [
    "OPENINFERENCE_SPAN_KIND",
    "OTLP_DEFAULT_PORT",
    "PROBE_TIMEOUT_S",
    "SERVICE_NAME",
    "SERVICE_VERSION",
    "current_agent_role",
    "current_cache_layer",
    "current_phase_timings",
    "current_session_id",
    "reset_tracing_for_tests",
    "resolve_request_identity",
    "set_cache_layer",
    "setup_tracing",
    "shutdown_tracing",
    "span_ann",
    "span_bm25",
    "span_embed",
    "span_rerank",
    "span_summarize",
    "span_tool_call",
]
