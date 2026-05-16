# Phoenix retrieval-quality view (E14_S03)

Phoenix (Arize Phoenix) is the v1 local sidecar for eyeballing
retrieval quality — it renders the OTel spans emitted by the MCP
server's E14_S02 tracer and surfaces a retrieval-evaluation table
showing the top-k chunks, their dense scores, and any reranker
output.

Phoenix is **opt-in**. The default `make up` workflow runs the
server bare-metal with tracing disabled; bringing Phoenix online
is a separate `docker compose` invocation.

---

## License callout

Phoenix is licensed under the **Elastic License 2.0 (ELv2)**, not
Apache-2.0. The license is permissive enough for the project's
local-first single-workstation use, but a future contributor who
assumes "open-source = Apache-2.0" may be surprised. The Phoenix
container ships unmodified upstream; no patches are vendored.

---

## Startup

### 1. First-time setup

```bash
# (one-time) make bootstrap creates var/arxmcp/observability/phoenix/
make bootstrap
```

### 2. Start Phoenix

```bash
docker compose -f infra/observability/phoenix-compose.yml \
  --profile phoenix up -d
```

This pulls `arizephoenix/phoenix:15.10` (~210 MB compressed, multi-
arch — Apple Silicon works without Rosetta) on first run, then
brings up the container with:

- HTTP UI at `http://127.0.0.1:6006`
- OTLP/gRPC trace intake at `127.0.0.1:4317`
- Trace SQLite persisted under
  `./var/arxmcp/observability/phoenix/`
- Trace retention capped at 14 days
- Phoenix's own usage telemetry **disabled** (no phone-home)

### 3. Point the MCP server at Phoenix

The server's tracing is gated on `ARXMCP_OTEL_ENDPOINT`; set it
**before** `make up`:

```bash
export ARXMCP_OTEL_ENDPOINT="http://127.0.0.1:4317"
make up
```

Without the env var the server starts normally with tracing
disabled (E14_S02 zero-allocation ProxyTracer path).

### 4. Verify

1. Open `http://127.0.0.1:6006` in a browser.
2. Issue a `search_papers` MCP call (via Claude Code or a test
   client).
3. Phoenix's "Traces" tab should show one `mcp.tool_call` parent
   span with children `arxmcp.embed`, `arxmcp.ann`, and (if
   reranking is enabled) `arxmcp.rerank`.
4. The "Retrieval Evaluation" view should populate because each
   span carries the OpenInference
   `openinference.span.kind` attribute
   (`CHAIN` / `EMBEDDING` / `RETRIEVER` / `RERANKER`).

---

## Tear-down

```bash
docker compose -f infra/observability/phoenix-compose.yml \
  --profile phoenix down
```

Add `-v` to also wipe the SQLite trace store. Without `-v`, the
bind-mount at `./var/arxmcp/observability/phoenix/` retains
traces across restarts.

---

## Upgrading Phoenix

The image is pinned to a minor version (`arizephoenix/phoenix:15.10`)
for reproducibility. To bump:

1. Edit `infra/observability/phoenix-compose.yml` — change the
   `image:` tag.
2. `docker compose -f infra/observability/phoenix-compose.yml pull`
3. `docker compose -f infra/observability/phoenix-compose.yml \
       --profile phoenix up -d`

A major-version bump (e.g. `15.x` → `16.x`) may involve a SQLite
schema migration on first start. The 14-day retention policy means
data loss from migration failures is bounded; back up
`./var/arxmcp/observability/phoenix/` first if you need to keep
the trace history.

---

## Security

**Spans carry `mcp.session_id`** (per
[`08-security-observability-ops.md`](../notes/08-security-observability-ops.md)
§Tracing). Both Phoenix host ports bind to `127.0.0.1` —
exposing them to the LAN would leak session IDs to anyone on the
network. The bindings are tested-regression-guarded at
`tests/test_compose_phoenix.py::test_loopback_only_port_bindings`.

If you need to forward traces to a remote collector for any reason
(SaaS Phoenix, OTel Collector pipeline, etc.), set
`ARXMCP_OTEL_ALLOW_REMOTE=1` AND audit your export path for
`mcp.session_id` redaction — Phoenix itself does NOT redact.

---

## What's NOT here

- **Prometheus scrape target.** Phoenix is not a Prometheus
  scraper; the `/metrics` endpoint surfaces only via the MCP
  server's own ASGI mount. Grafana + Prometheus ships in a
  future E14 milestone (see roadmap §E14_S09).
- **Base `docker-compose.yml`.** The two-service `server` +
  `ingest` stack from
  `.claude/notes/08-security-observability-ops.md` §Docker
  deployment is not yet shipped. Today, `make up` runs the
  server bare-metal as `python -m server.main` and Phoenix runs
  as an independent local sidecar.
- **Phoenix cloud / SaaS.** Out of scope. The local Docker
  container is the v1 surface.
- **Langfuse orchestrator-side traces.** Tracked as E14_S11. The
  E14_S02 spans cover the server-internal pipeline; the
  orchestrator agent's full prompt composition is a separate
  trace lane.

---

## Troubleshooting

### Phoenix UI says "no traces yet"

1. Confirm the server is actually emitting:
   ```bash
   curl http://127.0.0.1:7733/metrics | grep arxmcp_request_total
   ```
   If `arxmcp_request_total` is zero, no tool call has fired yet
   — issue a search.
2. Confirm `ARXMCP_OTEL_ENDPOINT` is set in the server's
   environment. The disabled-by-default path leaves the OTel SDK
   uninitialised; no spans flow.
3. Check the Phoenix container is healthy:
   ```bash
   docker compose -f infra/observability/phoenix-compose.yml ps
   ```
   The `STATUS` column should read `Up (healthy)`. If it's
   `unhealthy`, inspect logs:
   ```bash
   docker logs $(docker ps -qf name=phoenix)
   ```

### Retrieval-eval view doesn't render

The view depends on the `openinference.span.kind` attribute being
set on each span — verified by
`tests/test_tracing.py::TestOpenInferenceSpanKind`. If the view
is missing while raw spans appear, an upgrade may have removed
the OpenInference renderer; check the Phoenix release notes.

### Disk pressure

The 14-day retention default is enforced by Phoenix on a per-
trace basis. If `./var/arxmcp/observability/phoenix/` grows
unexpectedly, either lower
`PHOENIX_DEFAULT_RETENTION_POLICY_DAYS` in the compose file or
truncate manually after stopping the container.
