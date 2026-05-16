"""E14_S02 — OpenTelemetry tracing surface tests.

Coverage map (synthesis decisions → test class):

  D2  setup_tracing shape           TestSetupTracing
  D3  ContextVar plumbing           TestContextVarPlumbing
  D4  child spans                   TestChildSpans
  D6  cache-layer enum              TestContextVarPlumbing.test_cache_layer_*
  D8  acceptance criteria           TestParentSpan + others

Test strategy (Brief 2 §2.7): module-scoped ``InMemorySpanExporter``
fixture + ``exporter.clear()`` between tests. ``set_tracer_provider``
warns-and-no-ops on a second call in a process, so we install ONE
provider per test module and reset only the exporter between
individual tests.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from server.config import Config
from server.observability import tracing as tracing_mod
from server.observability.tracing import (
    current_agent_role,
    current_cache_layer,
    current_session_id,
    reset_tracing_for_tests,
    set_cache_layer,
    setup_tracing,
    span_ann,
    span_embed,
    span_rerank,
    span_tool_call,
)

# ===========================================================================
# Shared fixtures
# ===========================================================================


@pytest.fixture(scope="module")
def span_exporter() -> InMemorySpanExporter:
    """Module-scoped exporter. ``set_tracer_provider`` is a process-
    global write-once side-effect (the OTel SDK warns-and-no-ops on
    re-call); we install exactly ONE provider for this module and
    rely on ``exporter.clear()`` between tests for isolation.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    # Mark the module-level guard so setup_tracing knows a provider
    # is already installed (otherwise the disabled-path test below
    # would skip the no-op fast-path assertion).
    tracing_mod._provider_installed = True
    yield exporter
    # Best-effort: clear at end so a follow-on test module that
    # forgets the fixture doesn't see stale state.
    exporter.clear()


@pytest.fixture
def clear_spans(span_exporter: InMemorySpanExporter) -> InMemorySpanExporter:
    """Per-test exporter reset. Always pair with ``span_exporter``."""
    span_exporter.clear()
    # Reset ContextVars to their defaults so a prior test's
    # leftover session/role doesn't bleed in.
    current_session_id.set(None)
    current_agent_role.set(None)
    current_cache_layer.set("miss")
    yield span_exporter
    span_exporter.clear()


def _spans_by_name(exporter: InMemorySpanExporter, name: str) -> list[Any]:
    return [s for s in exporter.get_finished_spans() if s.name == name]


# ===========================================================================
# D2 — setup_tracing
# ===========================================================================


class TestSetupTracing:
    def test_otel_endpoint_unset_disables_tracing_silently(
        self, caplog, tmp_path
    ):
        """AC: ``ARXMCP_OTEL_ENDPOINT`` unset → tracing disabled
        (no-op exporter); no error."""
        # Snapshot + reset the module-level installation guard so we
        # exercise the disabled path even though the fixture above
        # set _provider_installed = True for the other tests.
        prior = tracing_mod._provider_installed
        reset_tracing_for_tests()
        try:
            cfg = Config(lancedb_path=tmp_path, otel_endpoint=None)
            with caplog.at_level(logging.INFO, logger="server.observability.tracing"):
                setup_tracing(cfg)
            # Disabled path logs INFO, never WARN.
            info_msgs = [r.message for r in caplog.records if r.levelname == "INFO"]
            assert any(
                "tracing.disabled" in m for m in info_msgs
            ), f"expected disabled-log, got {info_msgs!r}"
            assert tracing_mod._provider_installed is False
        finally:
            tracing_mod._provider_installed = prior

    def test_setup_tracing_is_idempotent(self, tmp_path, caplog):
        """A second call with an endpoint set must NOT re-register and
        must log the already-installed signal — closes the test-
        isolation gotcha in Brief 2 §2.7."""
        # Pretend tracing has already been set up. Then call setup
        # again with a fresh endpoint and confirm we short-circuit.
        prior = tracing_mod._provider_installed
        tracing_mod._provider_installed = True
        try:
            cfg = Config(
                lancedb_path=tmp_path, otel_endpoint="http://127.0.0.1:4317"
            )
            with caplog.at_level(logging.INFO, logger="server.observability.tracing"):
                setup_tracing(cfg)
            assert any(
                "already_installed" in r.message for r in caplog.records
            )
        finally:
            tracing_mod._provider_installed = prior

    def test_unreachable_endpoint_logs_warn_does_not_crash(
        self, monkeypatch, tmp_path, caplog
    ):
        """AC: OTel endpoint unreachable → server continues operating;
        WARN logged once at startup. We force ``_probe_endpoint`` to
        return False; the call still registers the exporter (so
        traces flow when Phoenix wakes mid-process) and logs WARN.
        """
        # Reset the install guard AND the global OTel provider so a
        # fresh setup_tracing runs. We can't reset trace._TRACER_PROVIDER
        # (write-once), so just exercise the probe + warn-log path
        # and confirm the WARN fires without raising.
        prior = tracing_mod._provider_installed
        reset_tracing_for_tests()
        monkeypatch.setattr(tracing_mod, "_probe_endpoint", lambda *a, **kw: False)
        # Replace set_tracer_provider with a no-op to avoid touching
        # OTel's process-global state from this test.
        monkeypatch.setattr(trace, "set_tracer_provider", lambda *a, **kw: None)
        try:
            cfg = Config(
                lancedb_path=tmp_path, otel_endpoint="http://127.0.0.1:14317"
            )
            with caplog.at_level(logging.WARNING):
                setup_tracing(cfg)
            assert any(
                "endpoint_unreachable" in r.message for r in caplog.records
            )
        finally:
            tracing_mod._provider_installed = prior

    def test_probe_endpoint_returns_true_for_open_port(self):
        """Sanity: the probe DOES succeed against a real listening
        socket. Without this, the unreachable-endpoint test could
        be passing because the probe was always returning False."""
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen(1)
        port = server_sock.getsockname()[1]

        def _accept_once() -> None:
            try:
                conn, _ = server_sock.accept()
                conn.close()
            except OSError:
                pass

        t = threading.Thread(target=_accept_once, daemon=True)
        t.start()
        try:
            assert (
                tracing_mod._probe_endpoint(
                    f"http://127.0.0.1:{port}", timeout_s=0.5
                )
                is True
            )
        finally:
            server_sock.close()

    def test_probe_endpoint_returns_false_for_closed_port(self):
        # Port 1 is reserved and refuses TCP connect on every common
        # platform (privileged + tcpmux RFC-1078). 0.5s is far above
        # the connect-refuse RTT on loopback.
        assert (
            tracing_mod._probe_endpoint(
                "http://127.0.0.1:1", timeout_s=0.5
            )
            is False
        )


# ===========================================================================
# D8 — Parent span, attribute presence, error path
# ===========================================================================


class TestParentSpan:
    def test_span_tool_call_emits_one_parent_with_required_attributes(
        self, clear_spans: InMemorySpanExporter
    ):
        current_session_id.set("session-abc-123")
        current_agent_role.set("sketcher")
        current_cache_layer.set("miss")

        with span_tool_call(
            "search_papers", corpus_version=42, k=10
        ):
            pass

        spans = clear_spans.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.name == "mcp.tool_call"
        attrs = dict(span.attributes or {})
        assert attrs["mcp.tool_name"] == "search_papers"
        assert attrs["mcp.session_id"] == "session-abc-123"
        assert attrs["arxmcp.agent_role"] == "sketcher"
        assert attrs["arxmcp.corpus_version"] == 42
        assert attrs["arxmcp.k"] == 10
        # cache_layer_served defaults to "miss" — read just-in-time
        # in the span's finally block from the ContextVar.
        assert attrs["arxmcp.cache_layer_served"] == "miss"

    def test_span_tool_call_records_error_status_on_handler_raise(
        self, clear_spans: InMemorySpanExporter
    ):
        with pytest.raises(RuntimeError, match="boom"), span_tool_call("search_papers"):
            raise RuntimeError("boom")
        spans = clear_spans.get_finished_spans()
        assert len(spans) == 1
        # OTel records status_code=ERROR on uncaught exception via
        # the context-manager protocol.
        assert spans[0].status.status_code.name == "ERROR"

    def test_late_cache_layer_set_surfaces_on_parent(
        self, clear_spans: InMemorySpanExporter
    ):
        """Handlers call ``set_cache_layer("tier1")`` LATE — after
        the span has opened. The attribute must reflect the last
        value at span close, not the entry-time default."""
        with span_tool_call("search_papers"):
            # Simulate a handler detecting a Tier-2 hit mid-execution.
            set_cache_layer("tier2")
        spans = clear_spans.get_finished_spans()
        assert dict(spans[0].attributes or {})["arxmcp.cache_layer_served"] == "tier2"


# ===========================================================================
# D4 — child spans
# ===========================================================================


class TestChildSpans:
    def test_span_embed_records_model_revision(
        self, clear_spans: InMemorySpanExporter
    ):
        sha = "deadbeef" * 5  # 40-char hex shape
        with span_tool_call("search_papers"), span_embed(
            model_name="bge-m3", model_revision=sha
        ):
            pass

        embed_spans = _spans_by_name(clear_spans, "arxmcp.embed")
        assert len(embed_spans) == 1
        attrs = dict(embed_spans[0].attributes or {})
        assert attrs["gen_ai.request.model"] == "bge-m3"
        assert attrs["arxmcp.model.revision"] == sha

    def test_span_rerank_records_model_revision(
        self, clear_spans: InMemorySpanExporter
    ):
        sha = "cafebabe" * 5
        with span_tool_call("search_papers"), span_rerank(
            model_name="bge-reranker-v2-m3", model_revision=sha
        ):
            pass
        rerank_spans = _spans_by_name(clear_spans, "arxmcp.rerank")
        assert len(rerank_spans) == 1
        attrs = dict(rerank_spans[0].attributes or {})
        assert attrs["gen_ai.request.model"] == "bge-reranker-v2-m3"
        assert attrs["arxmcp.model.revision"] == sha

    def test_search_papers_full_hierarchy_embed_ann_then_parent(
        self, clear_spans: InMemorySpanExporter
    ):
        """AC: a search_papers call produces a parent span with child
        spans for embed + ANN + rerank. We simulate the call with the
        actual helpers; spans must close in LIFO order with the
        parent enclosing both children."""
        with span_tool_call("search_papers", k=5):
            with span_embed(
                model_name="bge-m3", model_revision="0" * 40
            ):
                pass
            with span_ann(k=5):
                pass
            with span_rerank(
                model_name="bge-reranker-v2-m3", model_revision="1" * 40
            ):
                pass
        names = sorted(s.name for s in clear_spans.get_finished_spans())
        assert names == sorted(
            ["arxmcp.embed", "arxmcp.ann", "arxmcp.rerank", "mcp.tool_call"]
        )
        # Parent span has both children — check via parent_span_id.
        parents = _spans_by_name(clear_spans, "mcp.tool_call")
        assert len(parents) == 1
        parent_id = parents[0].context.span_id
        for child_name in ("arxmcp.embed", "arxmcp.ann", "arxmcp.rerank"):
            child = _spans_by_name(clear_spans, child_name)[0]
            assert child.parent.span_id == parent_id


# ===========================================================================
# D3 — ContextVar plumbing
# ===========================================================================


class TestContextVarPlumbing:
    def test_session_id_contextvar_flows_through_to_parent_span(
        self, clear_spans: InMemorySpanExporter
    ):
        current_session_id.set("test-session-42")
        with span_tool_call("get_paper"):
            pass
        assert (
            dict(clear_spans.get_finished_spans()[0].attributes or {})[
                "mcp.session_id"
            ]
            == "test-session-42"
        )

    def test_agent_role_contextvar_flows_through(
        self, clear_spans: InMemorySpanExporter
    ):
        current_agent_role.set("tactician")
        with span_tool_call("get_chunk"):
            pass
        assert (
            dict(clear_spans.get_finished_spans()[0].attributes or {})[
                "arxmcp.agent_role"
            ]
            == "tactician"
        )

    def test_cache_layer_default_is_miss(
        self, clear_spans: InMemorySpanExporter
    ):
        with span_tool_call("search_papers"):
            pass  # no set_cache_layer call
        assert (
            dict(clear_spans.get_finished_spans()[0].attributes or {})[
                "arxmcp.cache_layer_served"
            ]
            == "miss"
        )

    @pytest.mark.parametrize("layer", ["tier1", "tier2", "tier3"])
    def test_cache_layer_set_to_each_tier(
        self, clear_spans: InMemorySpanExporter, layer: str
    ):
        with span_tool_call("search_papers"):
            set_cache_layer(layer)
        assert (
            dict(clear_spans.get_finished_spans()[0].attributes or {})[
                "arxmcp.cache_layer_served"
            ]
            == layer
        )

    def test_session_id_absent_does_not_set_attribute(
        self, clear_spans: InMemorySpanExporter
    ):
        # ContextVar default is None; the span helper should NOT set
        # the attribute in that case (so missing-session-id is
        # distinguishable from session-id="" in operator tooling).
        current_session_id.set(None)
        with span_tool_call("search_papers"):
            pass
        attrs = dict(clear_spans.get_finished_spans()[0].attributes or {})
        assert "mcp.session_id" not in attrs


# ===========================================================================
# Middleware ContextVar propagation
# ===========================================================================


class TestTracingContextMiddleware:
    """Verify the pure-ASGI middleware populates the ContextVars
    from headers correctly and resets them on scope exit."""

    def test_middleware_sets_session_id_from_header(self):
        from server.middleware import TracingContextMiddleware  # noqa: PLC0415

        seen: dict[str, Any] = {}

        async def inner_app(scope, receive, send):
            seen["session_id"] = current_session_id.get()
            seen["agent_role"] = current_agent_role.get()
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [],
                }
            )
            await send({"type": "http.response.body", "body": b""})

        mw = TracingContextMiddleware(inner_app)
        scope = {
            "type": "http",
            "headers": [
                (b"mcp-session-id", b"middleware-test-sid"),
                (b"arxmcp-agent-role", b"fixer"),
            ],
        }

        async def receive():  # noqa: ANN202
            return {"type": "http.request", "body": b""}

        sent: list[dict] = []

        async def send(msg):  # noqa: ANN001
            sent.append(msg)

        asyncio.run(mw(scope, receive, send))
        assert seen["session_id"] == "middleware-test-sid"
        assert seen["agent_role"] == "fixer"
        # After scope exit, ContextVars revert to None.
        assert current_session_id.get() is None
        assert current_agent_role.get() is None


# ===========================================================================
# Wrapper integration — the _wrap_with_observability composition
# ===========================================================================


class TestWrapperIntegration:
    def test_wrap_with_observability_opens_parent_span(
        self, clear_spans: InMemorySpanExporter
    ):
        from server.tools import _wrap_with_observability  # noqa: PLC0415

        async def handler(query: str, k: int = 5):
            return SimpleNamespace(structuredContent={"results": []})

        wrapped = _wrap_with_observability("search_papers", handler)
        asyncio.run(wrapped(query="abc", k=7))

        parents = _spans_by_name(clear_spans, "mcp.tool_call")
        assert len(parents) == 1
        attrs = dict(parents[0].attributes or {})
        assert attrs["mcp.tool_name"] == "search_papers"
        assert attrs["arxmcp.k"] == 7

    def test_wrap_old_name_is_alias(self):
        """Backwards-compat: existing tests/test_server_metrics.py
        imports `_wrap_with_metrics`. The rename must keep the old
        name as an alias to the new function."""
        from server.tools import _wrap_with_metrics, _wrap_with_observability  # noqa: PLC0415

        assert _wrap_with_metrics is _wrap_with_observability


# ===========================================================================
# Disabled-path performance sanity
# ===========================================================================


class TestEnabledPathPerformance:
    """F10 rectification — the prior test was named
    `test_disabled_path_is_fast` but the module-scoped fixture had
    already installed a real provider, so the test was actually
    measuring the ENABLED path. Rename + tighten the budget so a
    real regression in span-creation cost surfaces.
    """

    def test_enabled_path_1000_spans_under_1s(self):
        from opentelemetry.trace import get_tracer  # noqa: PLC0415

        tracer = get_tracer("test_enabled_path_speed")
        t0 = time.perf_counter()
        for _ in range(1000):
            with tracer.start_as_current_span("noop"):
                pass
        elapsed = time.perf_counter() - t0
        assert elapsed < 1.0, (
            f"1000 spans took {elapsed:.3f}s with InMemorySpanExporter — "
            f"investigate BatchSpanProcessor cost regression"
        )


# ===========================================================================
# Rectification regression guards
# ===========================================================================


class TestF1LoopbackValidator:
    """F1 — Config.otel_endpoint must reject non-loopback URLs at
    parse time unless ARXMCP_OTEL_ALLOW_REMOTE is set."""

    def test_loopback_127_0_0_1_accepted(self, tmp_path):
        cfg = Config(
            lancedb_path=tmp_path,
            otel_endpoint="http://127.0.0.1:4317",
        )
        assert cfg.otel_endpoint == "http://127.0.0.1:4317"

    def test_loopback_localhost_accepted(self, tmp_path):
        cfg = Config(
            lancedb_path=tmp_path, otel_endpoint="http://localhost:4317"
        )
        assert cfg.otel_endpoint == "http://localhost:4317"

    def test_none_accepted_disabled_default(self, tmp_path):
        cfg = Config(lancedb_path=tmp_path, otel_endpoint=None)
        assert cfg.otel_endpoint is None

    def test_public_ip_rejected(self, tmp_path):
        from pydantic import ValidationError  # noqa: PLC0415

        with pytest.raises(ValidationError, match="loopback"):
            Config(
                lancedb_path=tmp_path,
                otel_endpoint="https://otel.attacker.example:4317",
            )

    def test_private_rfc1918_rejected(self, tmp_path):
        from pydantic import ValidationError  # noqa: PLC0415

        with pytest.raises(ValidationError, match="loopback"):
            Config(
                lancedb_path=tmp_path,
                otel_endpoint="http://192.168.1.5:4317",
            )

    def test_link_local_metadata_ip_rejected(self, tmp_path):
        from pydantic import ValidationError  # noqa: PLC0415

        with pytest.raises(ValidationError, match="loopback"):
            Config(
                lancedb_path=tmp_path,
                otel_endpoint="http://169.254.169.254:80",
            )

    def test_userinfo_rejected(self, tmp_path):
        from pydantic import ValidationError  # noqa: PLC0415

        with pytest.raises(ValidationError, match="userinfo"):
            Config(
                lancedb_path=tmp_path,
                otel_endpoint="http://user:pass@127.0.0.1:4317",
            )

    def test_non_http_scheme_rejected(self, tmp_path):
        from pydantic import ValidationError  # noqa: PLC0415

        with pytest.raises(ValidationError, match="http"):
            Config(
                lancedb_path=tmp_path,
                otel_endpoint="grpc://127.0.0.1:4317",
            )

    def test_allow_remote_escape_hatch(self, tmp_path):
        # With ARXMCP_OTEL_ALLOW_REMOTE=1 the operator opt-in
        # disables the loopback check.
        cfg = Config(
            lancedb_path=tmp_path,
            otel_endpoint="https://otel-collector.example:4317",
            otel_allow_remote=True,
        )
        assert cfg.otel_endpoint == "https://otel-collector.example:4317"


class TestF2AgentRoleValidation:
    """F2 — TracingContextMiddleware must drop unknown / oversized
    Arxmcp-Agent-Role values rather than echoing them onto a span."""

    def test_known_role_accepted(self):
        from server.middleware import TracingContextMiddleware  # noqa: PLC0415

        seen: dict[str, Any] = {}

        async def inner_app(scope, receive, send):
            seen["agent_role"] = current_agent_role.get()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        mw = TracingContextMiddleware(inner_app)
        scope = {
            "type": "http",
            "headers": [(b"arxmcp-agent-role", b"tactician")],
        }

        async def receive():  # noqa: ANN202
            return {"type": "http.request", "body": b""}

        async def send(msg):  # noqa: ANN001
            pass

        asyncio.run(mw(scope, receive, send))
        assert seen["agent_role"] == "tactician"

    def test_unknown_role_dropped(self):
        from server.middleware import TracingContextMiddleware  # noqa: PLC0415

        seen: dict[str, Any] = {}

        async def inner_app(scope, receive, send):
            seen["agent_role"] = current_agent_role.get()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        mw = TracingContextMiddleware(inner_app)
        scope = {
            "type": "http",
            "headers": [(b"arxmcp-agent-role", b"superuser-injection")],
        }

        async def receive():  # noqa: ANN202
            return {"type": "http.request", "body": b""}

        async def send(msg):  # noqa: ANN001
            pass

        asyncio.run(mw(scope, receive, send))
        assert seen["agent_role"] is None

    def test_oversized_role_dropped(self):
        from server.middleware import TracingContextMiddleware  # noqa: PLC0415
        from server.observability.tracing import MAX_HEADER_BYTES  # noqa: PLC0415

        seen: dict[str, Any] = {}

        async def inner_app(scope, receive, send):
            seen["agent_role"] = current_agent_role.get()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        mw = TracingContextMiddleware(inner_app)
        scope = {
            "type": "http",
            "headers": [
                (b"arxmcp-agent-role", b"x" * (MAX_HEADER_BYTES + 1))
            ],
        }

        async def receive():  # noqa: ANN202
            return {"type": "http.request", "body": b""}

        async def send(msg):  # noqa: ANN001
            pass

        asyncio.run(mw(scope, receive, send))
        assert seen["agent_role"] is None


class TestF4ResourcesNotReady:
    """F4 — when the wrapper runs before Resources have warmed, the
    parent span must carry the sentinel string AND the WARN must
    fire once per process."""

    def test_sentinel_string_on_corpus_version_attribute(
        self, clear_spans: InMemorySpanExporter, caplog
    ):
        # Force the resources singleton into the "not ready" state.
        from server.observability.tracing import (  # noqa: PLC0415
            CORPUS_VERSION_RESOURCES_NOT_READY,
        )
        from server.tools import (  # noqa: PLC0415
            _reset_resources_not_ready_warned_for_tests,
            _wrap_with_observability,
            reset_resources_for_tests,
        )

        reset_resources_for_tests()
        _reset_resources_not_ready_warned_for_tests()

        async def handler() -> SimpleNamespace:
            return SimpleNamespace(structuredContent={"ok": True})

        wrapped = _wrap_with_observability("search_papers", handler)
        with caplog.at_level(logging.WARNING, logger="server.tools"):
            asyncio.run(wrapped())

        spans = _spans_by_name(clear_spans, "mcp.tool_call")
        assert len(spans) == 1
        attrs = dict(spans[0].attributes or {})
        assert (
            attrs["arxmcp.corpus_version"]
            == CORPUS_VERSION_RESOURCES_NOT_READY
        )
        # WARN fires once.
        warns = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("resources-not-ready" in r.message for r in warns)
        # Second call must NOT log again (rate-limited).
        caplog.clear()
        asyncio.run(wrapped())
        warns_after = [r for r in caplog.records if r.levelname == "WARNING"]
        assert not any(
            "resources-not-ready" in r.message for r in warns_after
        )
        # Cleanup so subsequent tests in the module see resources.
        _reset_resources_not_ready_warned_for_tests()


class TestF7CacheLayerEnum:
    """F7 — set_cache_layer must reject values outside the
    canonical four; the prior ``current_cache_layer`` value
    must be preserved."""

    def test_typo_is_ignored(self, clear_spans: InMemorySpanExporter, caplog):
        set_cache_layer("tier1")
        with caplog.at_level(logging.DEBUG, logger="server.observability.tracing"):
            set_cache_layer("Tier1")  # capital T — typo
        # Original "tier1" preserved.
        assert current_cache_layer.get() == "tier1"
        assert any(
            "rejected unknown value" in r.message for r in caplog.records
        )

    def test_unknown_string_is_ignored(self):
        set_cache_layer("miss")
        set_cache_layer("disk")  # not a tier
        assert current_cache_layer.get() == "miss"


class TestF11AsyncContextPropagation:
    """F11 — OTel context propagation across ``await`` boundaries.
    Synthesis flagged this as a stdlib guarantee but the test
    surface didn't pin it. A handler that awaits between span
    operations must still see child spans attach to the parent."""

    def test_parent_context_propagates_across_await(
        self, clear_spans: InMemorySpanExporter
    ):
        async def _run():
            with span_tool_call("search_papers", k=10) as parent:
                await asyncio.sleep(0)  # release control to event loop
                with span_ann(k=10):
                    await asyncio.sleep(0)
                return parent.context.span_id

        parent_id = asyncio.run(_run())
        ann = _spans_by_name(clear_spans, "arxmcp.ann")
        assert len(ann) == 1
        assert ann[0].parent.span_id == parent_id


class TestF14StrictHeaderDecode:
    """F14 — non-ASCII bytes in tracing headers must be DROPPED
    (None), not silently rendered as U+FFFD."""

    def test_non_ascii_session_id_becomes_none(self):
        from server.middleware import TracingContextMiddleware  # noqa: PLC0415

        seen: dict[str, Any] = {}

        async def inner_app(scope, receive, send):
            seen["session_id"] = current_session_id.get()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        mw = TracingContextMiddleware(inner_app)
        scope = {
            "type": "http",
            "headers": [
                # b"\xff" is invalid ASCII; the strict decode must
                # return None instead of u"�".
                (b"mcp-session-id", b"valid-prefix-\xff"),
            ],
        }

        async def receive():  # noqa: ANN202
            return {"type": "http.request", "body": b""}

        async def send(msg):  # noqa: ANN001
            pass

        asyncio.run(mw(scope, receive, send))
        assert seen["session_id"] is None
