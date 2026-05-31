# Observability

arXMCP ships first-class metrics and tracing. Everything here is **opt-in**
and **loopback-friendly** — the server stays useful with none of it wired.

- [Prometheus metrics](#prometheus-metrics)
- [Daily ops report](#daily-ops-report)
- [OpenTelemetry tracing](#opentelemetry-tracing)
- [Phoenix](#phoenix)
- [Grafana dashboard](#grafana-dashboard)
- [Langfuse (orchestrator)](#langfuse)

## Prometheus metrics

The server exposes `/metrics` (Prometheus text format) with cache hit-ratio,
retrieval latency, and tool-call counters. Point a Prometheus scrape at
`http://127.0.0.1:7733/metrics`.

## Daily ops report

`make daily-report` scrapes `/metrics` and writes a markdown summary to
`var/arxmcp/ops/daily-reports/<date>.md`. Render against a saved fixture
without touching the network:

```sh
make daily-report ARGS="--dry-run --fixture tests/fixtures/metrics_sample.txt"
```

See the [daily-ops-cadence runbook](../ops/daily-ops-cadence.md) for the
cron/systemd schedule.

## OpenTelemetry tracing

One parent span per JSON-RPC tool call, with child spans for embed / rerank /
ANN. Set `ARXMCP_OTEL_ENDPOINT` to an OTLP/gRPC collector to enable it. When
unset, the SDK is never installed and every span takes the no-op fast path
with zero allocation — so leaving it off costs nothing.

## Phoenix

Arize Phoenix consumes the OTLP traces for local LLM/retrieval inspection.
Its SQLite trace store lives under `PHOENIX_WORKING_DIR` (bootstrap creates
`var/arxmcp/observability/phoenix/`); the compose file
`infra/observability/phoenix-compose.yml` bind-mounts it to `/mnt/data`.

## Grafana dashboard

A provisioned dashboard with cache hit-ratio and latency panels lives at
[`infra/observability/grafana-dashboard.json`](../../infra/observability/grafana-dashboard.json).
Provisioning config is split into two files so each mounts where Grafana
expects it:

- [`grafana-datasource.yml`](../../infra/observability/grafana-datasource.yml)
  — Prometheus datasource block.
- [`grafana-dashboard-provider.yml`](../../infra/observability/grafana-dashboard-provider.yml)
  — dashboards provider block.

### Option A — manual import (one-off)

1. Grafana → **Dashboards → New → Import**.
2. Upload `grafana-dashboard.json` (or paste it) and pick your Prometheus
   datasource.
3. It appears as **arXMCP — Cache and Latency**.

### Option B — provisioned auto-load (durable)

Mount the dashboard JSON and the two provisioning YAMLs into Grafana's
provisioning tree, then restart Grafana:

```
grafana-datasource.yml          → /etc/grafana/provisioning/datasources/arxmcp.yml
grafana-dashboard-provider.yml  → /etc/grafana/provisioning/dashboards/arxmcp.yml
grafana-dashboard.json          → /etc/grafana/provisioning/dashboards/arxmcp/arxmcp-cache-latency.json
```

```sh
docker restart grafana   # dashboard auto-loads
```

> **Container networking gotcha.** The datasource YAML hardcodes
> `url: http://localhost:9090`. When Grafana runs in a container, `localhost`
> is the *Grafana* container, not the host. Fix inline in the YAML:
> Docker Desktop (macOS/Windows) → `http://host.docker.internal:9090`;
> Linux shared compose stack → a service alias like `http://prometheus:9090`.

Tested against Grafana 10.x / 11.x (`schemaVersion: 39`). Requires a
Prometheus datasource scraping arXMCP's `/metrics`.

## Langfuse

Orchestrator-level LLM tracing (for the calling Claude pipeline, not the
server) is documented separately in
[`langfuse-orchestrator.md`](langfuse-orchestrator.md).
