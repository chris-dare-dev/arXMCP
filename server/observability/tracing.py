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


def shutdown_tracing(timeout_s: float = 30.0) -> None:
    """Force-flush the ``BatchSpanProcessor`` so in-flight spans
    export before the process exits.

    Called from the lifespan shutdown AFTER ``resources.shutdown()``
    returns. No-op when :func:`setup_tracing` was never called (the
    default in tests + the no-endpoint production case).
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
    ``socket.timeout``, ``OSError`` (including ``EHOSTUNREACH`` /
    ``ENETUNREACH``). The probe never raises — observability code
    must never crash the host process.
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
    corpus_version: int | None = None,
    k: int | None = None,
) -> Iterator[Span]:
    """Yield the parent OTel span for one JSON-RPC ``tools/call``.

    Reads :data:`current_session_id` and :data:`current_agent_role`
    from the request's ContextVars (populated by
    :class:`server.middleware.TracingContextMiddleware`). Reads
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
        span.set_attribute("mcp.tool_name", tool_name)
        sid = current_session_id.get()
        if sid is not None:
            span.set_attribute("mcp.session_id", sid)
        role = current_agent_role.get()
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
    request. Accepts the values ``"tier1" | "tier2" | "tier3" | "miss"``
    matching the Prometheus
    :data:`server.metrics.CACHE_HITS_COUNTER` label space and the
    OTel attribute enum (synthesis D6).

    Called from cache handlers (typically inside
    ``server/handlers/search.py``) when a tier hit is detected.
    Invalid values are accepted as-is — the OTel attribute is a
    free-form string and an invalid value surfaces as a query-time
    indicator that the handler emitted something unexpected. We do
    NOT validate here; the test surface pins the canonical set.
    """
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
    equivalent exists for that.
    """
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("arxmcp.embed") as span:
        span.set_attribute("gen_ai.request.model", model_name)
        span.set_attribute("arxmcp.model.revision", model_revision)
        yield span


@contextmanager
def span_ann(k: int | None = None) -> Iterator[Span]:
    """Child span for the LanceDB ANN vector search."""
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("arxmcp.ann") as span:
        if k is not None:
            span.set_attribute("arxmcp.k", k)
        yield span


@contextmanager
def span_bm25(k: int | None = None) -> Iterator[Span]:
    """Child span for the BM25 sparse search (forward-compat for
    E07_S04+; v1 ``search_papers`` is dense-only and never enters
    this span)."""
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("arxmcp.bm25") as span:
        if k is not None:
            span.set_attribute("arxmcp.k", k)
        yield span


@contextmanager
def span_rerank(model_name: str, model_revision: str) -> Iterator[Span]:
    """Child span for one BGE-reranker-v2-m3 cross-encoder forward
    pass."""
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("arxmcp.rerank") as span:
        span.set_attribute("gen_ai.request.model", model_name)
        span.set_attribute("arxmcp.model.revision", model_revision)
        yield span


@contextmanager
def span_summarize() -> Iterator[Span]:
    """Child span for the Haiku-API-backed summarizer. Reserved
    helper — note 07 lines 236-244 permanently dropped the
    in-server summarizer, so v1 never enters this span. Kept for
    forward-compat: a future tier may re-introduce a summarizer
    and the helper is then a one-line wrap point."""
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("arxmcp.summarize") as span:
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
    "OTLP_DEFAULT_PORT",
    "PROBE_TIMEOUT_S",
    "SERVICE_NAME",
    "SERVICE_VERSION",
    "current_agent_role",
    "current_cache_layer",
    "current_session_id",
    "reset_tracing_for_tests",
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
