# Research Brief — E14_Tier5plus

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-22T00:00:00Z

---

## In-codebase context

### Critical contradiction: `server/observability/` already exists

**The brief says `server/observability/spend_constants.py` is in a "NEW directory; create it
with `__init__.py`."** The directory is NOT new. `server/observability/` was created by
E14_S01 and contains: `__init__.py`, `log_filter.py`, `logging_setup.py`, `metrics.py`,
`sanitize.py`, `tracing.py`. The implementer must add `spend_constants.py` to the
existing directory — NOT create the directory or re-add `__init__.py`.

### `arxmcp_api_spend_usd_total` label drift

The design note (`08-security-observability-ops.md` line 143) defines:
```
arxmcp_api_spend_usd_total{provider,agent_role}         counter
```
The BRIEF (and E14 roadmap) defines:
```
arxmcp_api_spend_usd_total{provider, model, agent_role}
```
The roadmap (`E14-observability-ops.md` line 347) adds a third `model` label. **The brief
is the authoritative spec for this milestone; use three labels: `{provider, model, agent_role}`.**
The design note is slightly stale. No existing test or metric family references the two-label
form — adding `model` is safe and does not require a schema migration.

### `_agent_role` tool arg vs `Arxmcp-Agent-Role` HTTP header

The brief mentions `agent_role` from the `_agent_role` tool arg (E14_S02). In the actual
implementation, `arxmcp.agent_role` is populated from the `Arxmcp-Agent-Role` **HTTP
request header**, NOT a JSON-Schema tool argument (see `08-security-observability-ops.md`
§Tracing: "read from `Arxmcp-Agent-Role` HTTP request header; NOT a JSON-Schema property —
keeps `TOOL_SCHEMA_VERSION` pinned at 6"). This header is captured into the ContextVar
`current_agent_role` by `TracingContextMiddleware` in `server/middleware.py`. The
`VALID_AGENT_ROLES` frozenset is `{"sketcher", "autoformalizer", "tactician", "fixer"}` in
`server/observability/tracing.py:130-132`. The spend counter's `agent_role` label should
read from `current_agent_role.get()` — bounded to 4 values, no cardinality risk.

### Voyage path is a STUB

`server/query_encoder.py::_voyage_encode_stub` raises `NotImplementedError` with
`"voyage HTTP client not yet implemented; see E14_S05 D6"`. The stub always fails and falls
back to local BGE-M3 (triggering `HOSTED_EMBED_FALLBACK_COUNTER`). The spend counter
increment for Voyage must gate on an actual Voyage HTTP call — which does not exist. The
brief's instruction "ship the `spend_constants.py` + Prometheus metric registration + Voyage
path increment ONLY" means: wire the increment into the real Voyage HTTP path **when it
lands**, or stub the counter increment inside `_voyage_encode_stub` as a TODO comment. Do
NOT increment the spend counter in the fallback path.

### E08_S07 (Haiku summarizer) does not exist

Confirmed: no Haiku summarizer code exists anywhere in `server/`. No `import anthropic` in
server source (banned by `CLAUDE.md §4.7`). The brief correctly handles this: ship the
Voyage increment path only; leave a `# TODO(E08_S07)` comment for the Anthropic increment.

### `Mcp-Session-Id` is NOT emitted as a response header

Searching `server/` for any response-side `Mcp-Session-Id` emission returns zero hits. The
header is only CONSUMED (read by `TracingContextMiddleware` and stored in
`current_session_id` ContextVar). The S11 Langfuse doc snippet must note that to attach
the MCP session ID as a Langfuse tag, the caller reads the **request header they sent** (the
same value they pass), not a response header from the server. The snippet should show the
caller passing the session ID they already have.

### `docs/ops/` already contains 11 runbook files

`docs/ops/` already has: `backup-restore.md`, `bulk-ingest-runbook.md`,
`cutover-runbook.md`, `daily-ops-cadence.md`, `delta-loop.md`, `drift-watchdog.md`,
`failure-modes.md`, `latexml-drift-runbook.md`, `notebook-modes.md`,
`parser-failure-review.md`, `re-embed-runbook.md`. A `README.md` index does NOT yet exist.
The S10 deliverable is primarily that index file; most substance is already written and
just needs cross-linking. The brief's required runbooks map as follows:
- server-crash recovery → needs new `docs/ops/server-crash.md` (not present)
- ingestion-pause recovery → `failure-modes.md` partially covers this
- disk-full handling → `failure-modes.md`
- restore from backup → `backup-restore.md` (EXISTS; brief says E14_S05's `restore-runbook.md`
  but the actual file is `backup-restore.md`)
- model swap → needs new `docs/ops/model-swap.md`
- corpus rollback → `cutover-runbook.md` partial coverage; needs `docs/ops/corpus-rollback.md`
- LaTeXML worker restart → `latexml-drift-runbook.md` covers part; needs `docs/ops/latexml-restart.md`
- drift watchdog → `drift-watchdog.md` (EXISTS)

**Note:** `docs/ops/restore-runbook.md` does NOT exist; the file is `backup-restore.md`.
The BRIEF's exit criterion references `docs/ops/restore-runbook.md` from E14_S05 — this is
a link-rot risk. The implementer should link to `backup-restore.md` and create an alias or
note the naming discrepancy.

### `docs/observability/` does NOT exist

`docs/observability/` is absent. S11 creates `docs/observability/langfuse-orchestrator.md`
— this requires creating the directory first. This is operator-facing content (the snippet
is for orchestrator authors), so `docs/` placement is correct per `CLAUDE.md §1`.

### `.claude/notes/deferred-work-tracker.md` does NOT exist

The deferred-work tracker file does not yet exist. The E14 roadmap at lines 220-242 contains
the authoritative list of all 6 deferred items + 1 non-goal. S06 should consolidate these
verbatim from the roadmap into the new file at `.claude/notes/deferred-work-tracker.md`.

### No Grafana dashboard JSON exists in `infra/observability/`

`infra/observability/` currently contains only `phoenix-compose.yml`. The S09 dashboard,
provisioning YAML, and grafana-compose.yml must all be created fresh.

### Cache metrics families exist in `server/metrics.py` (not `server/observability/metrics.py`)

From the `server/observability/metrics.py` docstring: "The cache + retrieval-cap + drift +
eval gauges already live in `server.metrics`; that placement is kept for backwards
compatibility." The PromQL queries in the dashboard must work against metric families as
actually registered:
- `arxmcp_cache_hits_total{layer}` and `arxmcp_cache_lookups_total{layer}` — in
  `server/metrics.py` (per E08_S03, E04_S04)
- `arxmcp_embed_singleflight_dedup_total` — this metric name needs verification;
  `server/observability/metrics.py` has `EMBED_CALLS_COUNTER` but singleflight dedup
  counter may be in `server/health.py` per the docstring comment
- `arxmcp_rerank_latency_seconds` — in `server/observability/metrics.py`
- `arxmcp_tool_latency_seconds` — confirmed in `server/observability/metrics.py` as
  `arxmcp_request_latency_seconds` (not `tool_latency_seconds` — the brief uses the
  wrong name; use `arxmcp_request_latency_seconds`)

---

## Prior decisions and lessons

From git log: the last 20 commits are all `proof-verify-handler-wiring-*` milestones (m7–m10)
and E01_S01-S03. No E14 milestone appears in recent history, confirming S09–S12 have not
been touched since E14 was initially shipped (S01–S05 only).

From `MEMORY.md`: the E13 milestone series established that doc placement corrections are
systematic — any brief mentioning `docs/` for internal docs should default to `.claude/docs/`.
S11 (`docs/observability/langfuse-orchestrator.md`) is correctly operator-facing; S10
(`docs/ops/README.md`) is correctly operator-facing. No placement correction needed.

The `VALID_AGENT_ROLES` frozenset (`{"sketcher", "autoformalizer", "tactician", "fixer"}`)
acts as a bounded enum for the `agent_role` Prometheus label — cardinality is safe at 4
values. The spend counter with `{provider, model, agent_role}` has bounded cardinality:
2 providers × ~3 model names × 4 roles = 24 maximum label combinations.

The project bans `assert` for invariants, `BaseHTTPMiddleware`, and `import anthropic` in
server source. The S12 `spend_constants.py` must use `if ... raise` patterns. The S11
snippet must include a prominent "this runs in the CALLER's codebase, not arXMCP server/"
disclaimer.

The `EXPECTED_TOOL_SCHEMA_SHA256` does NOT need re-pinning for this bundle — no MCP tool
schema changes are made. `server/tools.py::ALL_TOOLS` is untouched.

---

## External sources

### Grafana dashboard JSON schema

Current `schemaVersion` in production Grafana deployments is in the 39–42 range (Grafana
10.x–11.x). The classic model still exports `schemaVersion: 17` in documentation examples
but this is outdated. **Recommendation: use `schemaVersion: 39`** which is safely importable
by Grafana 10.x and 11.x. For portable dashboards, the `__inputs` block declares datasource
inputs so the dashboard can be imported without hard-coding the datasource UID:

```json
{
  "__inputs": [
    {
      "name": "DS_PROMETHEUS",
      "label": "Prometheus",
      "description": "",
      "type": "datasource",
      "pluginId": "prometheus",
      "pluginName": "Prometheus"
    }
  ],
  "__elements": {},
  "__requires": [
    {"type": "datasource", "id": "prometheus", "name": "Prometheus", "version": "1.0.0"},
    {"type": "grafana", "id": "grafana", "name": "Grafana", "version": "10.0.0"}
  ]
}
```

Panels then reference `"datasource": "${DS_PROMETHEUS}"`. A provisioned dashboard (via YAML)
can hard-code `"datasource": {"type": "prometheus", "uid": "prometheus"}` since the
provisioning file sets the UID deterministically. For this project (single operator, known
environment), **use provisioning-based import** with hard-coded `uid: prometheus` in the
YAML provisioning config. Skip `__inputs` to keep the JSON simpler.

**Grafana 10.x/11.x import risk:** a dashboard with `schemaVersion` ≥ 40 may reject import
on older Grafana 10.x versions. Use `schemaVersion: 39` to maximize compatibility.

### Langfuse Python SDK

Current version: **SDK v4** (`langfuse` package on PyPI). The SDK v4 API uses:
- `langfuse = Langfuse()` — main client
- `langfuse.trace(name=..., session_id=..., tags=[...], input=..., output=...)` — creates a
  trace (synchronous); `session_id` maps MCP session ID directly
- `trace.generation(name=..., model=..., input=..., output=..., usage=...)` — child span for
  LLM call
- Context manager: `with langfuse.start_as_current_observation(as_type="span") as span:` —
  preferred for nested instrumentation
- `propagate_attributes()` — propagates `user_id`, `session_id`, `metadata`, `version`,
  `tags` to all children

For the S11 snippet: use `langfuse.trace(session_id=mcp_session_id, ...)` where
`mcp_session_id` is the value the caller sends as the `Mcp-Session-Id` request header (NOT
a response header — the server does not echo it back). The snippet should be < 60 LOC and
must NOT use `import anthropic` inside arXMCP server source.

**Import note for S11 test:** `langfuse` is NOT in the project's `pyproject.toml` dev deps.
The S11 doctest must be written as `# doctest: +SKIP` or the langfuse package must be added
as an optional dev dependency. Recommend: write the snippet as runnable pseudocode with a
`# requires: langfuse` comment at the top; test with `doctest: +SKIP` to avoid a missing dep
failure. Do NOT add langfuse to pyproject.toml unless explicitly approved.

### prometheus_client — Counter.inc() with float

`Counter.labels(provider=..., model=..., agent_role=...).inc(amount)` accepts float values
(the `amount` must be non-negative). For sub-cent spend deltas like `$0.0001`, pass the raw
float: `.inc(0.0001)`. This is confirmed by prometheus_client documentation and source.
The Counter monotonicity constraint (cannot decrement) is satisfied because API spend is
always positive.

### Pricing constants (verified 2026-05-22)

For `spend_constants.py`:
- `claude-haiku-4-5`: input `$1.00/M tokens`, output `$5.00/M tokens`
  (source: Anthropic pricing page, May 2026)
- `voyage-3`: `$0.06/M tokens` (input only; embeddings have no output tokens)
  (source: Voyage AI pricing docs, May 2026)

Derive per-call cost: `tokens / 1_000_000 * PRICE_PER_MILLION`. Comments must include the
source URL and `last_verified` date per the roadmap acceptance criterion.

---

## Failure-mode analysis

**FM-1 (S09): Grafana schemaVersion mismatch.** Trigger: operator runs Grafana 9.x or ≤10.3
and imports a dashboard with `schemaVersion: 39`. Symptom: import silently partially works;
some panels show "unknown panel type" or variable syntax errors. Mitigation: document minimum
Grafana version in `docs/observability/grafana.md`; use `schemaVersion: 39` (not 40+) which
has widest compat.

**FM-2 (S11): Langfuse SDK API breaks between v3 and v4.** Trigger: operator has `langfuse<4`
installed. v3 uses `Langfuse.trace()` directly; v4 restructured to `get_client()`. Symptom:
`AttributeError` or missing method. Mitigation: pin the SDK version in the snippet comment
(`# requires: langfuse>=4.0`). The snippet must note the SDK version.

**FM-3 (S12): Cost constants go stale silently.** Trigger: Anthropic or Voyage changes
pricing. Symptom: spend dashboard shows systematically wrong values with no alert. Mitigation:
`spend_constants.py` must include `LAST_VERIFIED: str = "2026-05-22"` and a comment with the
pricing URL. The quarterly restore drill cadence (per `08-security-observability-ops.md`)
doubles as the manual pricing review cadence.

**FM-4 (S12): `agent_role` label unbounded if validation removed.** Trigger: if
`VALID_AGENT_ROLES` frozenset guard is bypassed and raw header value used. Symptom:
Prometheus cardinality explosion (one series per unique header value). Mitigation: ALWAYS
read from `current_agent_role.get()` which is already validated by `TracingContextMiddleware`
to be in `{"sketcher", "autoformalizer", "tactician", "fixer"}` or `None`.

**FM-5 (S12): Counter increments before API call succeeds (overcounting).** Trigger:
increment placed before the HTTP response is received. Symptom: failed Voyage calls counted
as spend. Mitigation: increment ONLY in the success path (after parsing the response), not
in `try:` before the call.

**FM-6 (S12): Counter in hot path adds latency.** Trigger: `Counter.inc()` in the
query-encoding fast path. Reality: prometheus_client Counter.inc() is ~100 ns (pure
in-process; no I/O). Not a measurable latency contributor. No mitigation needed.

**FM-7 (S06): Deferred-work tracker becomes a graveyard.** Trigger: items added but never
reviewed. Mitigation: document review cadence explicitly in the tracker (quarterly, aligned
with restore drill). The tracker is `.claude/notes/` — agent-internal, not operator-facing.
Each item must have a concrete, falsifiable un-park trigger.

**FM-8 (S10): Runbook links rot as files move.** Trigger: a future milestone renames a
file in `docs/ops/`. Symptom: broken links in `docs/ops/README.md`. Mitigation: the S10
link-check test must use absolute file path assertions (not HTTP fetches) — verify each
linked file exists at test time.

**FM-9 (S11): Doctest fails because langfuse not installed.** Trigger: `pytest` runs the
doctest on a clean install without langfuse. Mitigation: mark the doctest `# doctest: +SKIP`
or wrap in a try/import guard. Do NOT add langfuse to pyproject.toml without user approval.
The brief requires "doctest the Python snippet imports cleanly" — this is achievable with
a `try: import langfuse; HAS_LANGFUSE = True except ImportError: HAS_LANGFUSE = False`
preamble and `pytest.mark.skipif(not HAS_LANGFUSE, ...)`.

---

## Recommendation

**Implement in the order S06 → S09 → S10 → S11 → S12** (invert the brief's suggested
S09-first ordering because S06 is zero-effort and produces content that may surface
additional deferred items to reference in other sub-milestones).

For S12, do not attempt to wire the Voyage spend increment into `_voyage_encode_stub` — the
stub raises `NotImplementedError` immediately. Instead, add the increment to the success
branch of the future real Voyage client call site, with a `# TODO(E08_S07): add Anthropic
increment here` comment. Wire the counter **registration** and **unit test** now (using a
mock increment in the test), but leave the production increment gated on a real Voyage call.

For S09, use `schemaVersion: 39`, provisioning-based datasource (no `__inputs`), hard-coded
`uid: prometheus` in the provisioning YAML. Metric names must match what is actually
registered: `arxmcp_request_latency_seconds` (not `arxmcp_tool_latency_seconds`).

For S11, the Langfuse snippet must not `import anthropic` in any server file. The session ID
comes from the caller's own sent header value (not from a server response header — the server
does not emit `Mcp-Session-Id` in responses).

---

## Open questions

1. **`arxmcp_embed_singleflight_dedup_total` exact location.** The `server/observability/metrics.py`
   docstring says this counter is in `server.health` but the metric name suggests
   it may live elsewhere. The implementer must `grep -rn singleflight_dedup` and verify
   the exact registered metric name before writing the dashboard PromQL panel.

2. **S09 Grafana container version to pin.** The `infra/observability/grafana-compose.yml`
   must pin Grafana to a specific version tag (not `latest` — banned by `CLAUDE.md §4`).
   Recommend `grafana/grafana:10.4.3` (last stable 10.x before v11 breaking changes) but the
   implementer should verify current stable 10.x or 11.x tag.

---

## External writes the implementation will require

None — this milestone is purely local per the BRIEF's own "External writes expected: Zero"
declaration. No `git push`, no `gh issue create`, no infra apply, no third-party API call.
The Grafana dashboard JSON is checked into source; the operator imports it manually.
