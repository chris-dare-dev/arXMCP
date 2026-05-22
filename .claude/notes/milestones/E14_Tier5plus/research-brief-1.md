# Research Brief — E14_Tier5plus

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-22T00:00:00Z

## In-codebase context

### S09 — Grafana dashboard

**CRITICAL metric name drift between brief and codebase.** The brief calls the
per-tool latency panel `arxmcp_tool_latency_seconds` but the registered metric
is `arxmcp_request_latency_seconds` (see `server/observability/metrics.py:67`).
The dashboard JSON must use `arxmcp_request_latency_seconds`, not
`arxmcp_tool_latency_seconds`.

The tier label convention is important: cache metrics use the label `tier` (not
`layer`) with string values `"1"`, `"2"`, `"3"`. From `server/metrics.py`:
"Tier labels are the strings `"1"`, `"2"`, `"3"` (string-typed so the
Prometheus label space stays consistent regardless of label-renderer quirks)."
The brief's cache hit-ratio panels must use `tier` as the label name.

`arxmcp_embed_singleflight_dedup_total` is registered in `server/health.py:125`
(NOT `server/observability/metrics.py`). The Grafana PromQL must reference it
without a label (no `{model}` label exists on this counter).

`arxmcp_rerank_latency_seconds` is a Histogram with `labelnames=["model"]`
(not bare). PromQL for P95 reranker latency:
`histogram_quantile(0.95, rate(arxmcp_rerank_latency_seconds_bucket{model="bge-reranker-v2-m3"}[5m]))`.

`infra/observability/` exists (has `phoenix-compose.yml`). No grafana files
exist yet. `infra/prometheus/alerts.yml` exists. `docs/observability/` does
NOT exist — it must be created.

**No `grafana-provisioning.yml` or `grafana-compose.yml` exists.** The brief
requires these. The dashboard JSON must be byte-stable (sorted keys, no
timestamps per hard constraint 5).

### S10 — Ops runbook index

`docs/ops/README.md` does NOT exist. Root `README.md` already has an
Operations section (line 61) with a table of individual runbooks. It does NOT
link to `docs/ops/README.md` — it links individual files directly.

**Most runbooks already exist:**
- server-crash: partially covered by `docs/ops/failure-modes.md` (LanceDB
  corruption, OOM, reranker cold start)
- ingestion-pause + disk-full: `docs/ops/failure-modes.md`
- restore from backup: `docs/ops/backup-restore.md` (NOT `restore-runbook.md`)
  — **the brief references `docs/ops/restore-runbook.md` which does not exist**.
  The actual file is `docs/ops/backup-restore.md`.
- latexml-restart: `docs/ops/latexml-drift-runbook.md`
- drift-watchdog: `docs/ops/drift-watchdog.md`

**NEW runbooks needed (no existing file):** `model-swap` and `corpus-rollback`.
`docs/ops/server-crash.md` probably also needed as a dedicated file since
`failure-modes.md` covers 9 modes as a table, not named scenario runbooks.

**CONFLICT FLAGGED:** The brief says "link to `docs/ops/restore-runbook.md`
from E14_S05" — this file does NOT exist. The real backup runbook is
`docs/ops/backup-restore.md`. The implementer must link to
`docs/ops/backup-restore.md`, not `restore-runbook.md`.

The brief says `docs/ops/README.md` is OK per CLAUDE.md §1 because it is
operator-facing (links from root README) — this is correct.

### S11 — Langfuse documentation

`08-security-observability-ops.md:197` states verbatim: *"Default v1 stack:
Phoenix + Prometheus. Langfuse if/when the agent orchestrator becomes part of
this repo."* S11 ships doc today; the orchestrator does NOT live in this repo.

`server/observability/tracing.py` uses `Mcp-Session-Id` as a ContextVar. The
middleware at `server/main.py:472` copies `Mcp-Session-Id` into a ContextVar
for OTel spans. There is no evidence the server EMITS `Mcp-Session-Id` as a
response header. The brief says "the MCP session ID is available from the
`Mcp-Session-Id` response header" — this needs verification before writing
the snippet. The MCP spec sends `Mcp-Session-Id` in the server's first response
to initialize the session, so it should be present.

**CRITICAL constraint from CLAUDE.md §4.7:** "No `anthropic` SDK at runtime
inside `server/`." The S11 snippet uses `anthropic` SDK — but ONLY because it
runs in the caller's codebase (documented constraint). The doc must explicitly
state "this code runs outside the arXMCP server process."

`docs/observability/` does NOT exist and must be created. Per CLAUDE.md §1,
`docs/` is for operator-facing content linked from root README — a langfuse
integration doc qualifies if linked from root README (currently not linked).

### S12 — API spend metrics

`server/observability/spend_constants.py` does NOT exist. `server/observability/`
exists and has `__init__.py` — the new file can be added directly.

`arxmcp_api_spend_usd_total` is NOT registered anywhere in the codebase (grep
confirmed zero hits). It must be created in `server/observability/spend_constants.py`
or a new `server/observability/spend_metrics.py`.

**E08_S07 does NOT exist as a milestone.** The milestone list under `.claude/notes/milestones/` goes E08_S01 through E08_S05. No E08_S07 milestone exists. The Haiku summarizer is referenced in `server/observability/tracing.py:482` via `span_summarize()` as "Reserved for an in-server summarizer" that "v1 NEVER enters." The `server/query_encoder.py` Voyage path is a stub that always raises (`"voyage HTTP client not yet implemented; see E14_S05 D6"`).

**CONCLUSION on E08_S07:** Not shipped. Implementer must ship `spend_constants.py` + Prometheus metric registration + Voyage path ONLY, leaving a TODO for the Haiku increment. The Voyage path is a stub that raises immediately, so the counter increment should fire on the fallback path (already tracked by `HOSTED_EMBED_FALLBACK_COUNTER`). The new `arxmcp_api_spend_usd_total` tracks dollar cost, not just fallback events.

**The brief's S12 deliverable mentions `server/embedder/` and `server/summarizer/` directories.** Neither directory exists. The voyage embedding stub lives in `server/query_encoder.py::_voyage_encode_stub`. The counter increment must go in `server/query_encoder.py`, not a non-existent `server/embedder/` directory.

### S06 — Deferred work tracker

Exhaustive grep of `.claude/` and `plans/` confirms deferred items from design
notes and roadmap. Items already captured in E14_S06 roadmap text (ColBERT-v2,
TikZ-cd, proof-skeleton classifier, multi-paper dedup, ORCID disambiguation,
Lean 4 toolchain, Mathlib lookup). From `09-feature-priorities.md`: PDF figure
extraction ("Tier 6 if at all") and OCR of pre-2007 scanned papers (explicitly
not built). From `06-mcp-server-design.md`: `paper_diff` is "DEFERRED to
Tier 4". From `10-references-and-prior-art.md`: ColBERT-v2 referenced as
"v1.5 candidate." From security docs: mTLS, budget alerting, Alertmanager
routing — all Tier-6+ hardening. Non-goal: LLM critic tool (hardcoded
non-goal, must be in tracker as explicit non-goal).

`plans/proof-verify-handler-wiring-roadmap.md` exists — the proof-verify
handler wiring is part of the notebook integration series (pv-m1 through
pv-m10); not a deferred item but an active workstream. Not relevant to S06.

## Prior decisions and lessons

**Git log:** Recent 20 commits are entirely `proof-verify-handler-wiring-mN`
series (notebook UI/ingest milestones m1–m10), plus `E01_S01-S03` finalize.
The E14_Tier5plus milestone has no prior commits. E14_S01–E14_S05 all have
`state.json` with `phase: complete` — these are the dependency milestones.

**Adjacent milestone (E14_S05) delivered:**
- `docs/ops/backup-restore.md` (NOT `restore-runbook.md`)
- `docs/ops/failure-modes.md` (covers all 9 failure modes)
- `infra/prometheus/alerts.yml`
- `server/observability/metrics.py` — DISK_FREE_BYTES, DEGRADED_MODE_ACTIVE,
  HOSTED_EMBED_FALLBACK_COUNTER added here (failure-mode metrics)

**E14_S01 delivered:**
- `server/observability/metrics.py` with REQUEST_COUNTER, REQUEST_LATENCY,
  REQUEST_INFLIGHT, RESULT_BYTES, EMBED_CALLS_COUNTER, EMBED_LATENCY,
  RERANK_CALLS_COUNTER, RERANK_LATENCY
- `server/metrics.py` retains cache + retrieval-cap + drift + eval metrics

**E14_S02 delivered:**
- `server/observability/tracing.py` with setup_tracing(), span_tool_call(),
  span_embed(), span_rerank(), span_summarize() (stub, never entered in v1)
- `docs/observability/tracing.md` — this means `docs/observability/` directory
  SHOULD exist per E14_S02 deliverable. It does NOT currently (contradicts).
  **CONFLICT FLAGGED:** E14_S02 specified `docs/observability/tracing.md` as a
  deliverable but `docs/observability/` does not exist. Either it was never
  created or was deleted. Implementer must create `docs/observability/` for S11.

**Memory patterns from prior E13/E14 milestones:**
- E13 milestones systematically used `.claude/docs/` for audit docs. S06 deferred
  tracker goes to `.claude/notes/deferred-work-tracker.md` per brief — correct.
- Tool-schema re-pinning needed only if MCP tool surface changes. S09/S10/S11/S12
  do NOT add tools, so no re-pinning needed.
- `assert` ban, `BaseHTTPMiddleware` ban, pure-ASGI middleware rule all apply.

## External sources

**Grafana dashboard JSON schema.** Grafana 11.x uses `schemaVersion: 39` for
dashboard JSON (as of 2025). The provisioned dashboard format requires:
`"annotations"`, `"editable"`, `"fiscalYearStartMonth"`, `"graphTooltip"`,
`"id"` (null for new), `"links"`, `"panels"`, `"schemaVersion"`, `"tags"`,
`"time"`, `"timepicker"`, `"timezone"`, `"title"`, `"uid"`, `"version"`.
The `uid` must be deterministic (not randomly generated). For byte-stability
(hard constraint 5), use sorted JSON keys and a fixed `uid` string like
`"arxmcp-cache-latency"`. Grafana provisioning uses a YAML file specifying
`datasources:` (Prometheus at `http://localhost:9090`) and `dashboards:` (path
to the JSON directory).

**Langfuse Python SDK.** As of 2025, Langfuse Python SDK v2 uses
`langfuse.trace()` as a context manager. The key pattern is:
```python
from langfuse import Langfuse
lf = Langfuse()
trace = lf.trace(name="arxmcp-call", tags=["mcp_session_id:abc123"])
```
The `update_trace(tags=[...])` API is available on the returned trace object.
For the snippet, use the `langfuse.decorators.observe` decorator pattern (v2
SDK) to wrap the Claude API call, then call `langfuse_context.update_current_trace`
to add the session ID tag. The snippet must use <60 LOC.

**Prometheus `Counter.labels()` API.** `prometheus_client` Python (pinned 0.25
per `server/observability/metrics.py` comment) supports
`Counter(..., labelnames=[...]).labels(provider="voyage").inc()`. No API
instability concern.

**Voyage AI pricing (2026):** voyage-3 embedding is approximately $0.000006
per token (input). Verify against `https://docs.voyageai.com/pricing` before
hardcoding; the constant must have a comment citing the URL and date verified.

**Anthropic Haiku 4.5 pricing:** E08_S07 is not shipped, so Haiku spend
constants are not needed in v1. Ship only the Voyage constant.

## Recommendation

**S06 (shallow):** Write `.claude/notes/deferred-work-tracker.md` aggregating
all items from E14_S06 roadmap + `09-feature-priorities.md` Tier 6/7 section +
`paper_diff` deferral from `06-mcp-server-design.md`. Include the LLM critic
non-goal explicitly (it is a hard design constraint, not a deferral). This is
~80 lines of Markdown, zero engineering. No tests required.

**S09 (medium effort — deepest research needed):** Build the Grafana dashboard
JSON with the corrected metric names (`arxmcp_request_latency_seconds` not
`arxmcp_tool_latency_seconds`; `tier` label not `layer`). Use schemaVersion 39,
deterministic uid `"arxmcp-cache-latency"`, sorted keys. Build grafana-compose.yml
binding Grafana to `127.0.0.1:3000` and Prometheus to `127.0.0.1:9090`. The
JSON-schema validation test should parse the file against Grafana's published
schema (or use `jsonschema` with a minimal inline schema checking required fields).

**S10 (medium effort):** Create `docs/ops/README.md` as an index with 8 entries.
Link `docs/ops/backup-restore.md` for the restore scenario (not `restore-runbook.md`).
Create new files for `model-swap` (covers E13_S06 SHA-pinning procedure) and
`corpus-rollback` (MVCC revert: update `corpus-version.json`; restart server;
note Kùzu graph is NOT rolled back). For server-crash, ingestion-pause, and
disk-full, write short dedicated files that redirect to the relevant sections of
`failure-modes.md`. Update root `README.md` to add/update the link to
`docs/ops/README.md` rather than individual files (reorganize the Operations
table to point at the index). The link-check test should verify all hrefs in
`docs/ops/README.md` resolve to files that exist on disk.

**S11 (shallow — <60 LOC doc):** Create `docs/observability/langfuse-orchestrator.md`
using Langfuse SDK v2 `observe` decorator pattern. The snippet reads
`Mcp-Session-Id` from the response headers and passes it as a trace tag. State
explicitly: "This code runs outside the arXMCP server process." The doctest
imports cleanly if `langfuse` is installed; it should be guarded with a
`try/except ImportError` comment. Do NOT add `langfuse` to `pyproject.toml`.
Create `docs/observability/` directory at this point (if not already created
from E14_S02 tracing.md).

**S12 (medium — new metric registration):** Create `server/observability/spend_constants.py`
with Voyage per-token cost (float, with source URL and date comment). Register
`arxmcp_api_spend_usd_total{provider, model, agent_role}` as a Counter in this
file. Wire the increment in `server/query_encoder.py` on the Voyage fallback
path (after the existing `HOSTED_EMBED_FALLBACK_COUNTER.inc()` call). Leave a
`# TODO(E08_S07): add anthropic/haiku increment when summarizer ships` comment.
The test should mock the metric and verify the counter increments with the
correct labels when the hosted embed path is triggered.

**Commit order:** S09 → S10 → S11 → S12 → S06 (tracker last, per brief).

## Open questions

1. **`Mcp-Session-Id` as response header:** Verify the MCP server emits
   `Mcp-Session-Id` as a response header on the initial session setup. The
   MCP 2025-06-18 spec requires this for session management. If the shim
   (`shim/arxmcp_shim.py`) strips response headers, the Langfuse snippet
   cannot retrieve it that way. Check `server/main.py` for where the session
   is established and whether the header is echoed back.

2. **`docs/observability/tracing.md` existence:** E14_S02 specified this as a
   deliverable but the directory doesn't exist. The implementer should check
   whether the file was created but the directory removed, or simply never
   created. If creating `docs/observability/` for S11, also check whether a
   `tracing.md` stub should be moved there.

3. **Grafana provisioning directory path:** The `grafana-provisioning.yml`
   structure requires knowing where Grafana looks for provisioned dashboards
   inside the container. Standard path is `/etc/grafana/provisioning/`. The
   compose file must volume-mount `infra/observability/grafana-provisioning.yml`
   to the correct path inside the container. Verify against Grafana 11.x docs.

## External writes the implementation will require

None — this milestone is purely local.

No `git push`, no `gh issue create`, no Grafana API call, no infra apply,
no third-party API calls. Single pre-push gate per CLAUDE.md §4.4 stays with
the user.
