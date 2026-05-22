"""Observability subpackage.

Modules:

- :mod:`server.observability.metrics` (E14_S01) — request-level
  + embedder + reranker Prometheus metric families. Cache +
  retrieval-cap + drift + eval metrics remain in
  :mod:`server.metrics` for backwards-compat with existing tests.
- :mod:`server.observability.tracing` (E14_S02) — OpenTelemetry
  distributed tracing: one parent span per JSON-RPC ``tools/call``
  with child spans for embed / ANN / rerank. Disabled by default;
  set ``ARXMCP_OTEL_ENDPOINT`` to enable export to a Phoenix
  sidecar.
- :mod:`server.observability.spend_constants` (E14_S12) — hosted-
  model API spend Counter + cost constants + ``record_spend()``
  helper. Imported below as a side-effect so the
  ``arxmcp_api_spend_usd_total`` Counter registers with
  ``prometheus_client.REGISTRY`` at server startup, even before
  any caller actually invokes ``record_spend()``. Without this
  side-effect import, the metric would never appear in
  ``/metrics`` until a future call site references the module —
  which today only happens in the test files and a TODO comment.
  Closes F2 from the E14_Tier5plus adversary critique.
"""

# F2 closure: side-effect import so API_SPEND_USD_TOTAL registers
# with the default Prometheus REGISTRY at process startup. Without
# this, the Counter is defined in a module nobody live-imports, and
# /metrics scrapes never include the metric series.
from server.observability import spend_constants as _spend_constants  # noqa: F401
