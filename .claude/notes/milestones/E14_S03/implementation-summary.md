# E14_S03 — implementation summary

## What landed

Phoenix retrieval-quality view as an opt-in local sidecar. The
project's first compose file ships at
`infra/observability/phoenix-compose.yml`, gated on
`--profile phoenix`. A small companion patch to
`server/observability/tracing.py` adds the
`openinference.span.kind` attribute to every span helper so
Phoenix's retrieval-evaluation view actually renders the
"top-k chunks, scores, reranker output" table the brief AC names.

## Files changed

| Path | Change | Synthesis ref |
|---|---|---|
| `infra/observability/phoenix-compose.yml` | NEW — single-service compose, `--profile phoenix`, loopback ports, 14-day retention, telemetry off, healthcheck, bind-mount to `var/arxmcp/observability/phoenix/` | D1, D2, D3 |
| `infra/README.md` | rewrite the placeholder to point at the new compose file + the runbook; note the base `docker-compose.yml` is still not shipped | D1 |
| `server/observability/tracing.py` | NEW `OPENINFERENCE_SPAN_KIND` constant; every span helper sets the attribute (`CHAIN`/`EMBEDDING`/`RETRIEVER`/`RERANKER`/`LLM` per OpenInference semconv) | D4 |
| `tests/test_tracing.py` | NEW `TestOpenInferenceSpanKind` class — 4 tests asserting the span-kind attribute on parent + embed + ANN + rerank spans | D4 |
| `tests/test_compose_phoenix.py` | NEW — 5 tests: file-exists, loopback-only ports, telemetry-disabled, bounded retention, full `docker compose config --quiet` validation (skipped without Docker on PATH) | D6 |
| `Makefile` | `bootstrap` target now creates `var/arxmcp/observability/phoenix/` | D9 |
| `.claude/docs/observability-phoenix.md` | NEW operator runbook: license callout (ELv2), startup recipe, UI verification steps, upgrade procedure, troubleshooting, security note, "what's NOT here" list | D5 |

## Drift from brief (deliberate)

1. **Phoenix ships as a standalone compose file, NOT a profile on
   a base `docker-compose.yml`.** The brief said "Updated
   `docker-compose.yml`" but no base file exists at the repo
   root, and no other roadmap milestone ships one. Two
   researchers independently surfaced this. Resolution per D1:
   ship `infra/observability/phoenix-compose.yml` invoked with
   `docker compose -f infra/observability/phoenix-compose.yml
   --profile phoenix up -d`. Defer the base compose stack to a
   future E14_S07 (orchestrator to file separately).

2. **OpenInference span-kind attributes added in this milestone,
   not E14_S02.** Brief 2 §2.6 surfaced the load-bearing
   dependency: Phoenix's retrieval-eval view is gated on the
   `openinference.span.kind` attribute (per OpenInference semconv
   "openinference.span.kind … is required for all OpenInference
   spans"). The E14_S02 spans set `gen_ai.request.model` +
   `arxmcp.*` but DID NOT set `openinference.span.kind`. Without
   the patch, Phoenix renders flat generic spans, NOT the
   retrieval-evaluation view the brief's AC #2 names. Strictly
   the attribute belongs to E14_S02's surface — landing it in
   E14_S03 is justified because it's load-bearing for E14_S03's
   AC, not because the original E14_S02 milestone was wrong to
   ship without it.

3. **Prometheus scrape target dropped from scope.** The brief
   said the Phoenix profile "also starts a Prometheus scrape
   target for the `/metrics` endpoint, making E14_S01 metrics
   visible in Phoenix's metrics pane." This is factually wrong:
   Phoenix is not a Prometheus scraper. The Phoenix metrics pane
   surfaces span-derived metrics from OTel data. The proper
   Prometheus container ships in E14_S09 (Grafana + Prometheus
   profile). Per D7.

4. **Operator runbook at `.claude/docs/observability-phoenix.md`,
   NOT `docs/observability/phoenix.md`.** Per CLAUDE.md §1 only
   operator-facing docs linked from the root README live under
   `docs/`. Phoenix is an opt-in dev/eyeball tool. Matches the
   E14_S02 precedent (`.claude/docs/observability-tracing.md`).
   Per D5.

## Test count delta

* Pre-milestone: 1778 passed, 8 skipped, 1 xfailed (end of
  E14_S02).
* Post-feat: 1787 passed (+9):
  - 4 new in `TestOpenInferenceSpanKind`
  - 5 new in `tests/test_compose_phoenix.py`
* Post-rect: 1791 passed (+4 regression guards for F1/F3/F8/IS5/IS8;
  the F2 rectification replaced the old `config --quiet` test
  with a stricter parsed-config check rather than adding a new
  one). 8 skipped, 1 xfailed.
* `ruff check .` — clean.
* The `docker compose config --quiet` smoke test runs locally
  (Docker on this machine's PATH); it skips automatically when
  Docker is absent.

## Acceptance criteria status

- [x] `docker compose --profile phoenix up -d` starts Phoenix —
  reinterpreted as `docker compose -f
  infra/observability/phoenix-compose.yml --profile phoenix up -d`
  per D1. Validated via `compose config --quiet` smoke test;
  manual UI smoke documented in the runbook.
- [x] Phoenix UI shows spans from a test `search_papers` call
  (top-k chunks, scores, reranker output) — met via the
  OpenInference span-kind patch (D4). The retrieval-eval view
  is gated by `openinference.span.kind=RETRIEVER`; with the
  attribute present, Phoenix renders the documents table.
  Per-document attributes (`retrieval.documents.<i>.document.id`
  / `...document.score`) are a separate, more invasive piece
  of work deferred to a follow-up.
- [x] Without the `phoenix` profile, the server starts normally;
  no connection errors in the log — already true via the
  E14_S02 disabled-by-default path (`ARXMCP_OTEL_ENDPOINT` unset
  → no TracerProvider registered → ProxyTracer fast-path).
- [x] `.claude/docs/observability-phoenix.md` is self-contained
  and tested (was: `docs/observability/phoenix.md`; relocated
  per CLAUDE.md §1).

## What this milestone does NOT cover

- **Base `docker-compose.yml` stack.** The two-service
  `server` + `ingest` stack from
  `.claude/notes/08-security-observability-ops.md` §Docker
  deployment is still not shipped. `make up` continues to run
  bare-metal.
- **`retrieval.documents.<i>.document.id` / `...document.score`
  attributes on the retrieval span.** These enrich Phoenix's
  table but the view renders without them. Deferred to a
  follow-up that touches `server/handlers/search.py`.
- **Grafana + Prometheus.** E14_S09.
- **Langfuse orchestrator-side traces.** E14_S11.
- **Phoenix in CI.** Docker-in-CI is out of scope; the local
  smoke + manual UI verification is the contract.

## Span attribute inventory after E14_S03

Parent `mcp.tool_call`:

- `mcp.tool_name`
- `mcp.session_id` (when header present)
- `arxmcp.agent_role` (when header present)
- `arxmcp.corpus_version` (or sentinel `"resources-not-ready"`)
- `arxmcp.k` (when handler takes `k`)
- `arxmcp.cache_layer_served`
- **NEW `openinference.span.kind = "CHAIN"`**

Children:

| span | kind | other attrs |
|---|---|---|
| `arxmcp.embed` | `EMBEDDING` | `gen_ai.request.model`, `arxmcp.model.revision` |
| `arxmcp.ann` | `RETRIEVER` | `arxmcp.k` |
| `arxmcp.bm25` | `RETRIEVER` (forward-compat) | `arxmcp.k` |
| `arxmcp.rerank` | `RERANKER` | `gen_ai.request.model`, `arxmcp.model.revision` |
| `arxmcp.summarize` | `LLM` (forward-compat, no caller in v1) | — |
