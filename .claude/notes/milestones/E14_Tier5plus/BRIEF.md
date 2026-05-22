# Milestone Brief — E14_Tier5plus (BUNDLED)

**Bundle rationale:** 5 sub-milestones from `.claude/roadmap/E14-observability-ops.md`
run through one combined Research/Implement/Critique/Rectify pass. Each
sub-milestone lands as a discrete logical commit; Research and Critique
reason over the operability theme as a whole. Precedent: `E01_S01-S03`.

---

## Sub-issue 1 — E14_S06 (Tier 6, PARKED): Deferred-work tracker

Living tracker doc for items explicitly out of v1 scope but that motivate
v1 design decisions. **NO engineering budgeted** — this is a single notes
file consolidating ColBERT-v2 late interaction, TikZ-cd diagram
extraction, proof-skeleton classifier, and any other v2+ deferred items
currently scattered across `.claude/notes/` and
`.claude/roadmap/E14-observability-ops.md`. Each item lists:
1. what it is,
2. why it was deferred,
3. what un-park trigger would activate it.

**Location:** `.claude/notes/deferred-work-tracker.md`.

---

## Sub-issue 2 — E14_S09 (Tier 5, S): Cache hit-ratio + latency Grafana dashboard

Provisioned JSON dashboard at `infra/observability/grafana-dashboard.json`.

**Panels:**
- cache hit ratio per tier (`arxmcp_cache_hits_total / arxmcp_cache_lookups_total` grouped by tier label)
- embedder singleflight dedup count (`arxmcp_embed_singleflight_dedup_total`)
- reranker latency P50/P95 (`arxmcp_rerank_latency_seconds` histogram)
- per-tool P95 request latency (`arxmcp_tool_latency_seconds` histogram)
- active inflight requests per tool

Prometheus datasource auto-provisioned at `http://localhost:9090`.
README addition: "Importing the dashboard" section.

---

## Sub-issue 3 — E14_S10 (Tier 5, M): Ops runbook index

Consolidate operational runbooks at `docs/ops/README.md`, linked from
root `README.md`. Each runbook covers one named failure or maintenance
scenario from `.claude/notes/08-security-observability-ops.md`.

**Required runbooks** (each with symptoms / detection / steps / verification sections):
- server-crash recovery
- ingestion-pause recovery (disk-full sentinel)
- disk-full handling
- restore from backup (link to existing `docs/ops/restore-runbook.md` from E14_S05)
- model swap (embedder or reranker version upgrade — link to E13_S06 SHA-pinning)
- corpus-version rollback (MVCC atomic revert per E04_S02 + E11_S05)
- LaTeXML worker restart
- drift watchdog alert response

**Validation:** the linked `docs/ops/restore-runbook.md` actually exists
(created by E14_S05); if not, write a thin stub linking the substance
into the index.

---

## Sub-issue 4 — E14_S11 (Tier 5, S): Langfuse orchestrator-side tracing documentation

Doc at `docs/observability/langfuse-orchestrator.md`.

Per `.claude/notes/08-security-observability-ops.md` § Recommended
export targets — *"Langfuse if/when the agent orchestrator becomes part
of this repo."* Today the orchestrator lives in the caller's codebase.

Provide a **< 60 LOC** Python reference snippet using the Langfuse
Python SDK:
- wrap the Claude API call in a Langfuse `trace`
- add the arXMCP MCP session ID (`Mcp-Session-Id` response header) as a
  tag so traces join with the OTel spans from E14_S02
- log tool inputs and outputs

**CRITICAL constraint per CLAUDE.md:** the snippet uses the `anthropic`
SDK in the CALLER'S codebase, NOT inside `arXMCP server/`. The doc
explicitly notes "this code runs outside the arXMCP server process."

---

## Sub-issue 5 — E14_S12 (Tier 5, S): API spend metrics for hosted-model fallbacks

**Metric family:** `arxmcp_api_spend_usd_total{provider, model, agent_role}`
- `provider` ∈ {`voyage`, `anthropic`}
- `model` is specific name (`voyage-3`, `claude-haiku-4-5`, etc.)
- `agent_role` from `_agent_role` tool arg (same as E14_S02)

**Per-call cost constants** in `server/observability/spend_constants.py`
(NEW directory; create it with `__init__.py`); updated when pricing
changes (no automated pricing API).

**Daily metrics report** (E14_S04) surfaces top spend categories by
summing `arxmcp_api_spend_usd_total` grouped by provider+model.

**Counter increments** live where the corresponding API call lives:
- Voyage embedder path
- Haiku summarizer path **if E08_S07 has shipped** — verify before
  adding the increment; if E08_S07 is not yet shipped, ship the
  `spend_constants.py` + Prometheus metric registration + Voyage path
  increment ONLY and leave a TODO referencing E08_S07 for the Haiku
  increment.

---

## Combined hard constraints (apply to all 5)

1. Per `CLAUDE.md` §4.7: `assert` is BANNED for invariants (use
   `if … raise RuntimeError(…)` instead); pure-ASGI middleware only
   (`BaseHTTPMiddleware` project-banned); no `anthropic` SDK at runtime
   inside `server/` (the LLM lives in the calling agent); no-fork
   policy (no code lifted from existing OSS observability tools — ideas
   only); `server/` source NEVER references `claude-opus`.
2. New code → new tests:
   - S09 dashboard: JSON-schema validation test
   - S10: link-check test for each runbook section
   - S11: doctest the Python snippet imports cleanly
   - S12: counter-increment unit test + `spend_constants.py`
     value-sanity tests
3. Conventional commits, GPG signed, never `--no-verify`,
   Co-Authored-By trailer mandatory.
4. Stop at the external-write boundary: no `git push`, no `gh issue
   create`, no Grafana API call to import the dashboard (the JSON is
   checked in; operator imports manually).
5. The S09 dashboard JSON must be **byte-stable** so a future diff is
   meaningful — use sorted keys, deterministic UID, no timestamps in
   the body.
6. The S10 runbook index doc-placement rule per `CLAUDE.md` §1:
   `docs/ops/README.md` is OK because it's operator-facing (links from
   root README); the linked detail runbooks may live under `docs/ops/`
   OR `.claude/docs/` as appropriate (operator-facing → `docs/ops/`;
   agent-internal → `.claude/docs/`).

---

## Combined exit criteria

- `.claude/notes/deferred-work-tracker.md` exists with at least the 3
  enumerated items (ColBERT-v2, TikZ-cd, proof-skeleton classifier)
  plus any others surfaced by Research from grepping `.claude/` for
  `DEFERRED` / `PARKED` / `Tier 6` markers.
- `infra/observability/grafana-dashboard.json` validates as Grafana
  dashboard schema; README has "Importing the dashboard" section.
- `docs/ops/README.md` exists with the 8 required runbook sections
  (each with the 4-part skeleton); linked from root `README.md`.
- `docs/observability/langfuse-orchestrator.md` exists with a < 60 LOC
  working Python snippet (doctested for clean imports).
- `server/observability/spend_constants.py` + Prometheus metric
  registration exist; counter-increment unit test passes.
- 5 logical commits in dependency order (S09 → S10 → S11 → S12 → S06;
  tracker last because Research may add un-park items surfaced during
  the other four).
- `make test` green; ruff clean.

## External writes expected

**Zero — purely local milestone.**
- No `git push`, no `gh issue create`, no infra apply, no third-party API.
- Single pre-push gate per `CLAUDE.md` §4.4 stays with the user.
