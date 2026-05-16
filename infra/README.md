# infra/

Docker Compose, Dockerfiles, and deployment glue.

## Current state

Only the **Phoenix observability profile** ships today (E14_S03):

- [`observability/phoenix-compose.yml`](observability/phoenix-compose.yml) — opt-in Phoenix UI + OTLP collector. Run with:
  ```bash
  docker compose -f infra/observability/phoenix-compose.yml \
    --profile phoenix up -d
  ```
  See [`.claude/docs/observability-phoenix.md`](../.claude/docs/observability-phoenix.md) for the full operator runbook.

The base `docker-compose.yml` (the two-service `server` + `ingest`
stack from [`.claude/notes/08-security-observability-ops.md`](../.claude/notes/08-security-observability-ops.md)
§ Docker deployment) is **not yet shipped** — tracked as future
work. Today, `make up` runs the server bare-metal as
`python -m server.main`; the Phoenix compose is an independent
local sidecar.
