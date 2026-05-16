"""Observability subpackage.

Two modules:

- :mod:`server.observability.metrics` (E14_S01) — request-level
  + embedder + reranker Prometheus metric families. Cache +
  retrieval-cap + drift + eval metrics remain in
  :mod:`server.metrics` for backwards-compat with existing tests.
- :mod:`server.observability.tracing` (E14_S02) — OpenTelemetry
  distributed tracing: one parent span per JSON-RPC ``tools/call``
  with child spans for embed / ANN / rerank. Disabled by default;
  set ``ARXMCP_OTEL_ENDPOINT`` to enable export to a Phoenix
  sidecar.
"""
