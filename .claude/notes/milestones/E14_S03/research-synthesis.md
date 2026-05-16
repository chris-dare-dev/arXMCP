# E14_S03 — Research synthesis (orchestrator-merged)

**Sources:** [research-brief-1.md](research-brief-1.md) (in-codebase, 270 LOC)
+ [research-brief-2.md](research-brief-2.md) (external + Phoenix API,
299 LOC).

The two researchers converged on every load-bearing decision and
surfaced one critical scoping issue the brief itself missed:
the project has **no `docker-compose.yml` at the repo root**, so the
brief's "Updated `docker-compose.yml` — Phoenix profile integrated"
deliverable cannot be satisfied as written. Resolution below (D1).

---

## 1. Headline findings

1. **No base `docker-compose.yml` exists.** Confirmed independently by
   both researchers. `infra/` holds only a placeholder README; the
   roadmap has no other milestone shipping the base compose stack.
   The brief's "Updated docker-compose.yml" deliverable references a
   file that doesn't exist.
2. **`make up` is bare-metal `python -m server.main`** — NOT a
   compose invocation. CLAUDE.md §7's "make ingest is a stub" wording
   is now stale post-E11_S01; both targets are real, neither uses
   compose.
3. **`server/config.py::otel_endpoint`** already accepts
   `http://127.0.0.1:4317` (validated against
   `LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}`). Zero
   server-side changes needed for the connectivity AC.
4. **Phoenix Docker image:** `arizephoenix/phoenix:15.10` —
   multi-arch (amd64 + arm64), Elastic License 2.0, ~210 MB
   compressed. Multi-arch means Apple Silicon works without Rosetta.
   The ELv2 license is permissive enough for our single-workstation
   local-first use case but is **not Apache-2.0** — worth flagging in
   the runbook.
5. **Phoenix consumes OTLP directly** — no separate
   `otel-collector` sidecar. Port 4317 = gRPC OTLP, port 6006 =
   HTTP UI + OTLP/HTTP at `/v1/traces`. The brief's "OTLP collector
   Phoenix ships with" phrasing refers to Phoenix's in-process
   collector.
6. **CRITICAL — retrieval-evaluation view needs
   `openinference.span.kind`.** Brief 2 §2.6: Phoenix's
   retrieval-eval table (the "top-k chunks, scores, reranker output"
   UI the brief's AC names) is gated by the OpenInference semantic
   convention `openinference.span.kind`. The E14_S02 spans set
   `gen_ai.request.model` + `arxmcp.*` but DO NOT set
   `openinference.span.kind`. Without it, Phoenix renders flat
   generic spans, NOT the retrieval-eval view. **The brief's AC
   #2 ("Phoenix UI shows spans from a test search_papers call
   — top-k chunks, scores, reranker output") cannot be met without
   a small patch to `server/observability/tracing.py`.**
7. **Phoenix is NOT a Prometheus scraper.** The brief's "compose
   profile also starts a Prometheus scrape target ... making E14_S01
   metrics visible in Phoenix's metrics pane" is factually wrong.
   Phoenix's metrics pane displays span-derived metrics, not
   Prometheus-scraped metrics. The Prometheus scrape work is
   E14_S09 (Grafana). Drop the line from this milestone's scope.
8. **Loopback-only port binding.** Compose v2 syntax
   `"127.0.0.1:6006:6006"` and `"127.0.0.1:4317:4317"` satisfies the
   brief's Risk note ("Phoenix container must be localhost-only").
   Plain `"6006:6006"` would bind to `0.0.0.0` on the host and leak
   `mcp.session_id`-bearing spans to anyone on the LAN.
9. **No yamllint / compose-config test pattern exists.** This is the
   first compose file the project ships. We add a minimal
   `docker compose -f <path> config --quiet` smoke test gated on
   `shutil.which("docker")` (skipped when Docker is absent — same
   pattern as `requires_model`).
10. **Doc location: `.claude/docs/observability-phoenix.md`.**
    Matches the E14_S02 precedent
    (`.claude/docs/observability-tracing.md`). The brief's literal
    path (`docs/observability/phoenix.md`) would create a brand-new
    `docs/` subtree with no other operator-facing rationale. The
    E11 `docs/ops/` runbooks are grandfathered but new observability
    docs land under `.claude/docs/`.
11. **`otel_endpoint` default stays `None`.** Flipping to
    `http://127.0.0.1:4317` would break the E14_S02 zero-allocation
    contract for the disabled-by-default path (tested by
    `tests/test_tracing.py::test_otel_endpoint_unset_disables_tracing_silently`).
    The runbook documents the `export
    ARXMCP_OTEL_ENDPOINT=http://127.0.0.1:4317` step.
12. **Note 08 docker-compose snippet drift.** Lines 269-315 of
    `.claude/notes/08-security-observability-ops.md` contain an
    aspirational compose snippet whose `ARXMCP_BIND_HOST=0.0.0.0`
    would fail the `Config.reject_non_loopback` validator at
    instantiation. The drift is already documented in
    `server/config.py:19-27`. Out of scope for this milestone to
    rewrite the snippet; recommend a touch-up in a follow-up.

---

## 2. Decisions

### D1. Scope — ship Phoenix as a STANDALONE compose file

Reject the brief's "Updated docker-compose.yml — Phoenix profile
integrated" wording. Deliver:

- `infra/observability/phoenix-compose.yml` — a single-service
  compose file with `profiles: ["phoenix"]`. Invoked with:
  ```bash
  docker compose -f infra/observability/phoenix-compose.yml \
    --profile phoenix up -d
  ```
- NO base `docker-compose.yml`. The base compose stack is a separate
  piece of work; track as **E14_S07 — "Base docker-compose stack"**
  (orchestrator to file once this milestone completes).

The `--profile phoenix` flag is retained even though the compose file
has only one service so the invocation pattern stays consistent with
the future base-compose milestone (which WILL have profiles).

### D2. Phoenix image — `arizephoenix/phoenix:15.10`

Minor pin (not `:latest`, not floating `:15`). Multi-arch
(amd64+arm64). The runbook documents the bump procedure (`docker
compose pull` after editing the tag).

### D3. Service shape

```yaml
services:
  phoenix:
    image: arizephoenix/phoenix:15.10
    profiles: ["phoenix"]
    environment:
      PHOENIX_PORT: "6006"
      PHOENIX_GRPC_PORT: "4317"
      PHOENIX_HOST: "0.0.0.0"  # inside-container only; loopback at host
      PHOENIX_WORKING_DIR: "/mnt/data"
      PHOENIX_DEFAULT_RETENTION_POLICY_DAYS: "14"  # bound disk
      PHOENIX_TELEMETRY_ENABLED: "false"           # no Phoenix usage stats
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

Rationale:

- `PHOENIX_DEFAULT_RETENTION_POLICY_DAYS=14` caps SQLite growth;
  the default (`0` = infinite) is unsuitable for a long-running dev
  loop.
- `PHOENIX_TELEMETRY_ENABLED=false` — Phoenix's own usage telemetry
  goes to Arize. We disable it so the only outbound network call is
  the one-time image pull.
- Bind-mount `./var/arxmcp/observability/phoenix:/mnt/data` per
  CLAUDE.md §5 (all state under `var/arxmcp/`). Named volumes
  bypass `make clean` discipline.
- `wget --spider` is the portable healthcheck (Phoenix 15.x images
  bundle wget; not all bundle curl).
- `restart: unless-stopped` matches the "long-running dev tool"
  posture; the operator stops it with `docker compose down`.

### D4. OpenInference span-kind attributes — patch `server/observability/tracing.py`

Without `openinference.span.kind`, Phoenix renders flat spans, not
the retrieval-eval view. Add ~6 LOC:

| Span helper | Attribute |
|---|---|
| `span_tool_call` (parent) | `openinference.span.kind = "CHAIN"` |
| `span_embed` | `openinference.span.kind = "EMBEDDING"` |
| `span_ann` | `openinference.span.kind = "RETRIEVER"` |
| `span_bm25` | `openinference.span.kind = "RETRIEVER"` (forward-compat) |
| `span_rerank` | `openinference.span.kind = "RERANKER"` |
| `span_summarize` | `openinference.span.kind = "LLM"` (forward-compat) |

This is **STRICTLY** an attribute add; no test breakage expected.
The existing tests assert presence of specific attributes; they will
keep passing.

Stretch goal (skip if scope inflates): plumb the top-k chunk IDs +
scores onto the parent span as
`retrieval.documents.<i>.document.id` and
`retrieval.documents.<i>.document.score`. This is more invasive
(touches `server/handlers/search.py`) and the retrieval view will
still render usefully without per-document attributes — they enrich
the table but aren't required for it to appear. **DEFER per-document
attributes to a follow-up; ship span-kind only in E14_S03.**

### D5. Operator runbook — `.claude/docs/observability-phoenix.md`

NOT `docs/observability/phoenix.md` (CLAUDE.md §1). Content:

- Phoenix license callout (ELv2, not Apache-2.0)
- Startup recipe (`docker compose -f ... up -d`)
- Setting `ARXMCP_OTEL_ENDPOINT`
- UI walkthrough (manual smoke — list what to look for in the
  retrieval-eval view)
- Persistence path (`./var/arxmcp/observability/phoenix/`)
- Tear-down recipe
- Image-tag bump procedure
- Security note: loopback-only binding; spans carry `mcp.session_id`

### D6. Smoke-test surface

Single new test file `tests/test_compose_phoenix.py` with two tests:

1. `test_compose_file_parses` — runs
   `docker compose -f infra/observability/phoenix-compose.yml config
   --quiet`; skipped when `shutil.which("docker")` is `None` (CI without
   Docker, or developer machines without it installed). Asserts exit
   code 0.
2. `test_compose_binds_to_loopback_only` — parses the YAML directly
   with `yaml.safe_load` (no Docker dependency) and asserts every
   entry under `services.phoenix.ports` starts with `127.0.0.1:`.
   Closes the brief Risk note as a regression guard.

No live-container test (Docker-in-CI is a future concern; the manual
UI smoke is the contract).

### D7. Drop Prometheus-scrape from scope

The brief's "compose profile also starts a Prometheus scrape target
for the `/metrics` endpoint" is factually wrong: Phoenix is not a
Prometheus scraper. Defer to E14_S09 (Grafana, which DOES ship a
Prometheus container). Document the deviation in the
implementation-summary §"Drift from brief".

### D8. Keep `otel_endpoint` default at `None`

Flipping the default would break the E14_S02 zero-allocation
guarantee. The runbook documents the export step:

```bash
export ARXMCP_OTEL_ENDPOINT="http://127.0.0.1:4317"
make up
```

### D9. Bootstrap directory creation

`./var/arxmcp/observability/phoenix/` must exist with write permission
before the bind-mount. Two options:

- Add an `mkdir -p` to `make bootstrap`.
- Let compose create it on first run (uses host umask).

Recommend (a) — explicit, predictable, matches the existing pattern
in the Makefile for other `var/arxmcp/` subtrees.

### D10. Note 08 touch-up — deferred

The aspirational compose snippet at
`.claude/notes/08-security-observability-ops.md:269-315` already has
documented drift. Rewriting it to match shipped reality is out of
scope for E14_S03 (touches a constitution note, separate concern).
Track as a follow-up note-grooming task.

### D11. No CLAUDE.md status-table update

The status table in CLAUDE.md §3 is stale; updates happen
opportunistically. Not load-bearing for this milestone.

### D12. Acceptance-criteria reinterpretation

| Brief AC | Status | How met |
|---|---|---|
| `docker compose --profile phoenix up -d` starts Phoenix without error | Adapted to standalone form: `docker compose -f infra/observability/phoenix-compose.yml --profile phoenix up -d`. Smoke-tested via `compose config --quiet`. |
| Phoenix UI at `http://localhost:6006` shows spans from a test `search_papers` call (top-k chunks, scores, reranker output) | Met via D4 (OpenInference span.kind attributes). Manual UI smoke documented in the runbook. |
| Without the `phoenix` profile, server starts normally | Already true today — the E14_S02 tracer probes the endpoint, logs WARN on failure, and registers the exporter anyway. Server lifespan is unaffected. |
| `docs/observability/phoenix.md` is self-contained and tested | Adapted to `.claude/docs/observability-phoenix.md` per D5. |

---

## 3. Forced cross-file changes

| File | Change | Decision |
|---|---|---|
| `infra/observability/phoenix-compose.yml` (NEW) | Phoenix service definition per D3 | D1, D2, D3 |
| `infra/observability/README.md` (NEW or update existing) | Pointer to the compose file + runbook | D1 |
| `server/observability/tracing.py` (MODIFY) | Add `openinference.span.kind` to 6 span helpers | D4 |
| `tests/test_tracing.py` (MODIFY) | Update 1-2 span-attribute assertions to acknowledge the new key | D4 |
| `tests/test_compose_phoenix.py` (NEW) | 2 smoke tests per D6 | D6 |
| `.claude/docs/observability-phoenix.md` (NEW) | Operator runbook | D5 |
| `Makefile` (MODIFY) | `make bootstrap` creates `./var/arxmcp/observability/phoenix/` | D9 |
| `.gitignore` (verify) | `var/arxmcp/` is already gitignored; the new subdir inherits — no change needed |
| `infra/README.md` (MODIFY) | Replace "Empty until E14" placeholder with a one-line pointer | D1 |

---

## 4. Implementation order

1. `server/observability/tracing.py` — add `openinference.span.kind`
   attributes. Smallest change, lowest blast radius.
2. `tests/test_tracing.py` — verify no regressions; update any
   assertion that pins span-attribute counts.
3. `infra/observability/phoenix-compose.yml` — write the compose file.
4. `tests/test_compose_phoenix.py` — write the two smoke tests.
5. `Makefile` — bootstrap directory.
6. `infra/README.md` + `.claude/docs/observability-phoenix.md` —
   docs.
7. Validate: `make test`, `ruff check .`, `docker compose config`
   smoke (if Docker on PATH).
8. Implementation-summary write-up.

---

## 5. Open questions resolved at synthesis time

All open questions from Brief 1 + Brief 2 are resolved by the
decisions above:

| Q | Resolution |
|---|---|
| Base compose vs Phoenix-only? | Phoenix-only standalone (D1). |
| Doc location? | `.claude/docs/observability-phoenix.md` (D5). |
| Prometheus scrape in scope? | No, defer to E14_S09 (D7). |
| `docker compose config` smoke or live test? | `config --quiet` only; live UI is manual (D6). |
| Phoenix image pin? | `arizephoenix/phoenix:15.10` (D2). |
| Persistence: named volume vs bind-mount? | Bind-mount per CLAUDE.md §5 (D3). |
| Healthcheck command? | `wget --spider` on `/healthz` (D3). |
| OpenInference span.kind in scope? | Yes — load-bearing for AC #2 (D4). |

---

## 6. External writes required

**Zero beyond local `main` commits + one-time Docker Hub pull.**

Specifically:

- Local file creates/edits per §3.
- 3 git commits (feat + rect + chore) per the project's 3-commit-
  per-milestone pattern.
- `docker compose pull` (or `up -d` on first run) fetches
  `arizephoenix/phoenix:15.10` from Docker Hub. One-time outbound
  network call. No Phoenix-SaaS account, no GitHub/PyPI writes.
- `git push origin main` per user authorization (per-event).

---

## 7. Risk register (carry into Phase 3)

- **D4 brief drift** — adding `openinference.span.kind` is
  technically OUTSIDE E14_S02's surface but is required to meet
  E14_S03 AC #2. Document the rationale in the implementation
  summary §"Drift from brief"; adversary may flag scope leak.
- **D1 deviation** — the brief specifies "Updated
  `docker-compose.yml`" but no base file exists. The standalone
  form is the only workable interpretation; document the
  E14_S07-tracking gap.
- **Manual UI smoke** — the "Phoenix UI shows spans" AC is
  inherently visual and can't be fully automated short of pulling
  Phoenix in CI. The compose-config smoke test verifies the
  configuration is well-formed; the runbook documents the manual
  step.
- **ELv2 license** — flag it in the runbook so a future contributor
  doesn't assume Apache-2.0.
- **Phoenix tag drift** — pin to `:15.10` (minor pin); a future
  `:16.x` schema migration could surprise an operator running
  `docker compose pull`. Document the bump procedure.
- **OpenInference semconv evolution** — the attribute spec is at
  "stable" but rebalances may still occur. We track `openinference`
  via OTel attribute names only; no Python dep added.
- **Docker absent in test env** — `tests/test_compose_phoenix.py`
  uses `shutil.which("docker")` as the skip gate. If a future CI
  pipeline DOES have Docker, the smoke runs automatically.
