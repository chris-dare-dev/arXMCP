# E14_S03 — Research Brief 2 (External Context)

**Scope.** External context for the Phoenix integration milestone. In-codebase
context is touched lightly only to confirm prerequisites.

---

## 1. In-codebase context (light pass)

- **No prior Phoenix references** in code/config. `grep -ril phoenix` returns
  only doc/roadmap files (`.claude/roadmap/E14-observability-ops.md`,
  `.claude/docs/observability-tracing.md`, E14_S02 milestone artifacts,
  HANDOFF, and references). Zero hits under `server/`, `ingest/`, `tools/`,
  `docker/`, `infra/`, `tests/` source trees.
- **No `docker-compose.yml` exists yet** at the repo root. `infra/` is a
  bare directory containing only `README.md` (a placeholder per CLAUDE.md
  §5). So E14_S03 introduces BOTH the compose file and the Phoenix profile
  on it — there is no pre-existing compose to extend. The brief's wording
  "Updated `docker-compose.yml`" is misleading; treat it as "create."
- **E14_S02 has shipped.** `server/observability/tracing.py` exists (lines
  31, 406, 413, 446 reference `gen_ai.request.model`). The tracer attaches
  `gen_ai.request.model` + `arxmcp.model.revision` on embed and rerank
  spans, and `arxmcp.k`, `mcp.tool_name`, `mcp.session_id`,
  `arxmcp.agent_role`, `arxmcp.corpus_version` on the parent
  `mcp.tool.search_papers` span. **No `openinference.span.kind` is being
  set today.** This matters — see §2.6.

---

## 2. External sources (pinned)

### 2.1 Image, version, license

- **Image:** `arizephoenix/phoenix` on Docker Hub. Latest tag as of
  2026-05-15 push: **`15.10.0`** (also aliased to `15.10`, `15`, `latest`).
  Compressed sizes: **amd64 = 208.8 MB, arm64 = 202.69 MB** — multi-arch
  manifest covers both, so Apple Silicon hosts work without Rosetta.
- **License:** **Elastic License 2.0 (ELv2)**, per the repo README:
  *"This software is licensed under the terms of the Elastic License 2.0
  (ELv2)."* Permissive enough for our local-first single-user usage (no
  hosting-as-a-service restriction matters here), but **not Apache-2.0**.
  Worth flagging in `docs/observability/phoenix.md` so a future contributor
  isn't surprised.
- **Pinning recommendation:** the Phoenix self-hosting Docker page advises
  *"Pin to a specific version (e.g., `arizephoenix/phoenix:version-8.0.0`)
  for production deployments."* Floating tags `15` or `15.10` give us
  patch-level updates without semver-major surprises. Use **`15.10`**
  (minor pin) for the milestone; document the upgrade procedure as "bump
  the tag, re-`docker compose pull`."

### 2.2 Environment variables (canonical list)

From Phoenix's *Self-Hosting → Configuration* page, the relevant vars and
their defaults are:

| Var | Default | Notes |
|---|---|---|
| `PHOENIX_PORT` | `6006` | HTTP UI + `/v1/traces` (OTLP/HTTP) |
| `PHOENIX_GRPC_PORT` | `4317` | OTLP/gRPC trace collector |
| `PHOENIX_HOST` | `0.0.0.0` | Bind inside the container; keep this — bind to loopback at the **host** via `ports:` mapping |
| `PHOENIX_WORKING_DIR` | `~/.phoenix` (host); `/mnt/data` is the recommended container path | Holds SQLite + working state |
| `PHOENIX_SQL_DATABASE_URL` | (unset → SQLite under WORKING_DIR) | Set to a Postgres DSN to swap backend |
| `PHOENIX_DEFAULT_RETENTION_POLICY_DAYS` | `0` (infinite) | Worth setting to `7` or `14` for E14_S03 to bound disk |
| `PHOENIX_ENABLE_PROMETHEUS` | unset | Opens optional **port 9090** |
| `PHOENIX_DEFAULT_ADMIN_INITIAL_PASSWORD` | `admin` | Auth is opt-in; defaults are open. Localhost-only binding is our defense |
| `PHOENIX_CSRF_TRUSTED_ORIGINS` | — | Only relevant if reverse-proxying |
| `PHOENIX_TELEMETRY_ENABLED` | — | Phoenix's own usage telemetry; set to `false` |

Auth posture: Phoenix ships **no required auth** by default. With the
host-side `127.0.0.1:` bind (see §2.7), that's acceptable for the
single-workstation threat model (CLAUDE.md §1). Do **not** mention this in
the README without the loopback caveat.

### 2.3 Data persistence

- Phoenix's default storage is **SQLite under `PHOENIX_WORKING_DIR`**, with
  Postgres as an opt-in via `PHOENIX_SQL_DATABASE_URL`. The Docker
  deployment guide recommends `phoenix_data:/mnt/data` with
  `PHOENIX_WORKING_DIR=/mnt/data`.
- **Without a volume**, restarting the container loses all traces. For
  E14_S03's "eyeball retrieval quality" use case, that's mostly fine — but
  long-running diagnostics across multi-day debugging sessions will hurt.
  **Mount a volume.**
- **Project convention** (CLAUDE.md §5): all state goes under
  `var/arxmcp/`. So **bind-mount `./var/arxmcp/observability/phoenix:/mnt/data`**
  rather than a named Docker volume. Matches the existing `corpus/`,
  `index/`, `cache/`, `ops/` layout and keeps `make clean` semantics
  predictable.

### 2.4 OTel collector — bundled, not separate

Phoenix's HTTP server **directly accepts OTLP** on its two ports:

- `6006` → HTTP OTLP at path `/v1/traces` (alongside the UI on the same
  port — the path discriminates).
- `4317` → gRPC OTLP.

There is **no separate `otel-collector` container** in the official
Phoenix deployment shape. The "OTLP collector Phoenix ships with" phrasing
in the brief refers to the in-process collector, not a sidecar. **Do not
add a separate collector service** to the compose file; that's wasted
complexity. The server (E14_S02 tracing) just points its OTLP exporter at
`http://127.0.0.1:6006/v1/traces` (HTTP) or `http://127.0.0.1:4317` (gRPC).

### 2.5 Healthcheck endpoint

- **`GET /healthz`** on `PHOENIX_PORT` (default `6006`) is the supported
  endpoint per the Arize community thread *"what is the health check
  endpoint for phoenix?"* and confirmed by issue #2120 follow-ups.
- Caveat: that endpoint returns 200 once the Python process is up; it
  does **not** verify DB or migration readiness. Good enough for compose
  `healthcheck:` gating but not for first-call ordering — the server
  should retry its OTLP exporter on first failure.
- The Phoenix container image **does not include `curl`** in some builds
  but does include `wget` (Alpine/Debian-slim lineage varies by version).
  Use `wget --spider` for portability:
  ```yaml
  healthcheck:
    test: ["CMD", "wget", "--spider", "-q", "http://127.0.0.1:6006/healthz"]
    interval: 10s
    timeout: 3s
    retries: 5
    start_period: 20s
  ```

### 2.6 Span attributes Phoenix expects (LOAD-BEARING)

This is the riskiest implementation gap. From OpenInference's *Semantic
Conventions* spec:

> *"`openinference.span.kind` … is **required for all OpenInference
> spans**. It provides a hint to the tracing backend as to how the trace
> should be assembled."*

Supported values are `LLM`, `EMBEDDING`, `CHAIN`, `RETRIEVER`, `RERANKER`,
`TOOL`, `AGENT`, `GUARDRAIL`, `EVALUATOR`, `PROMPT`. Retrieved documents
flatten under `retrieval.documents.<i>.document.content` /
`...document.score`.

**Our E14_S02 spans do not set `openinference.span.kind`.** They set OTel
GenAI conventions (`gen_ai.request.model`) plus project-internal
`arxmcp.*` keys. Phoenix has a translator (`@arizeai/openinference-genai`)
for OTel GenAI → OpenInference, but per the *Translating Conventions* page
that's a TypeScript helper, not a server-side auto-translation: spans
that arrive **without** `openinference.span.kind` will land in Phoenix as
generic spans and miss the retrieval-evaluation view (the table-of-docs UI
the brief calls out).

**Recommendation for the implementer:** E14_S03's acceptance criterion
*"Phoenix UI shows spans from a test `search_papers` call (top-k chunks,
scores, reranker output)"* requires a follow-on patch to
`server/observability/tracing.py` adding:

- On the parent `search_papers` span: `openinference.span.kind = "CHAIN"`.
- On the embed child span: `openinference.span.kind = "EMBEDDING"`.
- On the rerank child span: `openinference.span.kind = "RERANKER"`.
- On the BM25/ANN retrieval phase: `openinference.span.kind = "RETRIEVER"`
  plus `retrieval.documents.<i>.document.id` /
  `...document.score` for top-k.

This is small (10–20 lines in `tracing.py`) but it's the difference
between "Phoenix shows a flat trace" and "Phoenix shows the retrieval-eval
view." Call it out as a scope question for the implementer — strictly
speaking it belongs to E14_S02, but E14_S03 cannot meet its own AC
without it.

### 2.7 Network model — localhost binding

Phoenix listens on `0.0.0.0` inside the container (correct — required for
the Docker bridge to forward). Host exposure must be loopback-only. The
canonical compose syntax (v2+):

```yaml
ports:
  - "127.0.0.1:6006:6006"   # HTTP UI + OTLP/HTTP
  - "127.0.0.1:4317:4317"   # OTLP/gRPC
```

The `127.0.0.1:` prefix is the long form — Docker honors it on both Linux
and Docker Desktop (mac/Windows). The risk-note in the brief ("Phoenix
container must be localhost-only") is satisfied by this binding plus the
default of no exposed firewall ports.

### 2.8 docker-compose syntax (v2 / Compose Specification)

- The `version:` top-level key is **deprecated** in Compose v2 and ignored
  by current `docker compose` binaries — *"the top-level `version` field
  is obsolete"*. Omit it.
- **Profiles:** the `profiles:` key on a service marks it as opt-in.
  Phoenix should set `profiles: ["phoenix"]` so the default
  `docker compose up -d` brings up only the server, and
  `docker compose --profile phoenix up -d` adds Phoenix. (The AC verbatim.)
- File split: brief calls for **`infra/observability/phoenix-compose.yml`**.
  In Compose-v2 idiom this is a **`include:`** target from the root
  `docker-compose.yml`:
  ```yaml
  include:
    - path: infra/observability/phoenix-compose.yml
  ```
  rather than a `-f` flag chain. Cleaner UX.

---

## 3. Recommendations — concrete compose shape

### `infra/observability/phoenix-compose.yml`

```yaml
# Phoenix UI for retrieval-quality eyeballing. Opt-in via:
#   docker compose --profile phoenix up -d
# Receives OTLP from the MCP server's E14_S02 tracer.
services:
  phoenix:
    image: arizephoenix/phoenix:15.10   # multi-arch (amd64+arm64), ELv2
    profiles: ["phoenix"]
    environment:
      PHOENIX_PORT: "6006"
      PHOENIX_GRPC_PORT: "4317"
      PHOENIX_HOST: "0.0.0.0"
      PHOENIX_WORKING_DIR: "/mnt/data"
      PHOENIX_DEFAULT_RETENTION_POLICY_DAYS: "14"
      PHOENIX_TELEMETRY_ENABLED: "false"
    ports:
      - "127.0.0.1:6006:6006"
      - "127.0.0.1:4317:4317"
    volumes:
      - ./var/arxmcp/observability/phoenix:/mnt/data
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://127.0.0.1:6006/healthz"]
      interval: 10s
      timeout: 3s
      retries: 5
      start_period: 20s
    restart: unless-stopped
```

### Root `docker-compose.yml` (new file, minimum scaffold)

```yaml
# arXMCP local-first compose. v2+; no `version:` field.
include:
  - path: infra/observability/phoenix-compose.yml
services:
  arxmcp:
    build:
      context: .
      dockerfile: docker/Dockerfile.server
    environment:
      ARXMCP_CONTACT_EMAIL: "${ARXMCP_CONTACT_EMAIL:?required}"
      # OTLP target: localhost on the HOST (compose host net), via the
      # phoenix profile's port mapping.
      OTEL_EXPORTER_OTLP_ENDPOINT: "http://host.docker.internal:4317"
      OTEL_EXPORTER_OTLP_PROTOCOL: "grpc"
    ports:
      - "127.0.0.1:7733:7733"
    volumes:
      - ./var/arxmcp:/var/arxmcp
    restart: unless-stopped
```

Without `--profile phoenix`, `arxmcp` starts standalone; its OTLP exporter
fails fast and the server keeps running (E14_S02 tracer must already be
non-fatal on collector unavailability — verify in implementation).

---

## 4. Open questions

1. **Healthcheck command if `wget` is absent in a future image build.**
   The Phoenix base appears to rotate between Debian-slim and
   distroless-ish flavors across major versions. Fallback is
   `CMD-SHELL` with `python -c "import urllib.request,sys;
   urllib.request.urlopen('http://127.0.0.1:6006/healthz').read()"` — but
   we shouldn't need it on 15.10.
2. **Minor pin vs `:latest`.** Recommend **`arizephoenix/phoenix:15.10`**
   (minor pin) for reproducibility. Phoenix's release cadence is fast
   (15.10.0 was published ~6h before this brief); pinning to `15` alone
   risks a 15.11 schema migration we didn't ask for.
3. **Persistence path.** Per CLAUDE.md §5 the project's discipline is
   `var/arxmcp/<subsystem>/`. Recommend **bind-mount
   `./var/arxmcp/observability/phoenix/:/mnt/data`**. A named volume
   (`phoenix_data:`) is the Phoenix-docs default but bypasses `make clean`
   conventions and forces the user to `docker volume rm` to reset.

---

## 5. External writes the implementation will require

- **First-run `docker compose pull` (or `up -d`) hits Docker Hub** and
  fetches `arizephoenix/phoenix:15.10` (~210 MB compressed). One-time
  network call. No Phoenix-SaaS account exists or is required.
- **No outbound traces leave the host.** Phoenix runs entirely locally;
  the optional `PHOENIX_TELEMETRY_ENABLED=true` would phone home its own
  usage stats — we **explicitly disable it** above.
- **Volume directory is created on first run.**
  `./var/arxmcp/observability/phoenix/` must exist with write permission;
  recommend `make bootstrap` create it (or compose creates it on first
  start, depending on host umask).
