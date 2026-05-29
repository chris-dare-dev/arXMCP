# infra/

Docker Compose, Dockerfiles, and deployment glue.

## Current state

Two compose files ship today:

- [`docker-compose.yml`](docker-compose.yml) — the **base server-only v0
  stack** (notebook-ops-hardening-m3). Builds
  [`../docker/Dockerfile.server`](../docker/Dockerfile.server) and runs the MCP
  server as non-root UID 1000, published on loopback only
  (`127.0.0.1:7733`). Run with:
  ```bash
  make bootstrap                                          # create var/arxmcp/ first
  docker compose -f infra/docker-compose.yml up --wait    # blocks until /readyz 200
  ```
  See [`../docs/install.md`](../docs/install.md) § "Run via Docker Compose" for
  the full flow (incl. the Linux-only `chown` pre-step). **Corpus prerequisite:**
  the server warms its corpus eagerly at startup, so `var/arxmcp` must already
  hold an ingested corpus (or set `ARXMCP_NOTEBOOK=<slug>`) — an empty tree makes
  the container EXIT at startup, not serve a 503. The **ingest service + a
  Litestream sidecar are a deliberate v1 increment** — not yet shipped.

- [`observability/phoenix-compose.yml`](observability/phoenix-compose.yml) —
  opt-in Phoenix UI + OTLP collector (E14_S03). Run with:
  ```bash
  docker compose -f infra/observability/phoenix-compose.yml \
    --profile phoenix up -d
  ```
  See [`.claude/docs/observability-phoenix.md`](../.claude/docs/observability-phoenix.md) for the full operator runbook.

Both compose files bind only to `127.0.0.1` on the host per
[`.claude/notes/08-security-observability-ops.md`](../.claude/notes/08-security-observability-ops.md)
§ Docker deployment. `make up` still runs the server bare-metal as
`python -m server.main`; the compose stack is the containerized alternative.
