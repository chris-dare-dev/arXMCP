# Research Synthesis — E14_Tier5plus

**Phase:** 1 (Research) → 2 (Implement)
**Briefs merged:** `research-brief-1.md`, `research-brief-2.md`
**Generated:** 2026-05-22

---

## Bundle in one paragraph

Five Tier-5/6+ observability/ops milestones (S09 Grafana dashboard,
S10 ops runbook index, S11 Langfuse caller-side docs, S12 API spend
metrics, S06 deferred-work tracker) shipped as one bundled run. The
deliverables are heterogeneous: a JSON dashboard, an index markdown,
a Python reference doc, a new metric family + cost constants, and a
consolidated notes file. Five logical commits in the order
**S09 → S10 → S11 → S12 → S06** (tracker last per brief).

---

## Cross-brief agreements (both researchers concur)

### A1. **Metric name drift** — brief is wrong; use the registered name

R-1 (§"S09 — Grafana dashboard") and R-2 (§"Cache metrics families")
both flag: the brief calls the per-tool latency metric
`arxmcp_tool_latency_seconds`, but the registered metric is
**`arxmcp_request_latency_seconds`** (`server/observability/metrics.py:67`).
The S09 dashboard PromQL must use the registered name.

Other registered names worth pinning (R-1):
- Cache: `arxmcp_cache_hits_total{tier=...}` / `arxmcp_cache_lookups_total{tier=...}`
  with **string-typed `tier`** label (values `"1"`, `"2"`, `"3"`).
- Rerank: `arxmcp_rerank_latency_seconds` is a Histogram with
  `labelnames=["model"]`. P95 PromQL:
  `histogram_quantile(0.95, rate(arxmcp_rerank_latency_seconds_bucket{model="bge-reranker-v2-m3"}[5m]))`.
- `arxmcp_embed_singleflight_dedup_total` lives in `server/health.py:125`
  (NOT `server/observability/metrics.py`), bare (no labels).
- During implementation, **grep before writing PromQL** for any metric
  whose exact name is questionable.

### A2. **Runbook file-path drift** — link to `backup-restore.md`, not `restore-runbook.md`

R-1 (§"S10") and R-2 (§"`docs/ops/`") both confirm: `docs/ops/restore-runbook.md`
does NOT exist; the actual file E14_S05 shipped is **`docs/ops/backup-restore.md`**.
S10 must link to `backup-restore.md`. (The brief's reference to
`restore-runbook.md` is a documentation bug.)

### A3. **`server/observability/` already exists** — brief wrongly says "NEW directory"

R-1 (§"S12") and R-2 (§"Critical contradiction") both confirm:
`server/observability/` was created by E14_S01 and already contains
`__init__.py`, `log_filter.py`, `logging_setup.py`, `metrics.py`,
`sanitize.py`, `tracing.py`. **Add `spend_constants.py` to the existing
directory; do NOT re-create `__init__.py`.**

### A4. **`Mcp-Session-Id` is NOT a response header** — caller passes the value they already sent

R-1 (§"S11") and R-2 (§"`Mcp-Session-Id`") both confirm: searching
`server/` for any response-side `Mcp-Session-Id` emission returns zero
hits. The header is only *consumed* by `TracingContextMiddleware`
(stored in `current_session_id` ContextVar). **The S11 snippet must
show the caller passing the value they already sent as the request
header — NOT extracting it from a response header.** Note that MCP
2025-06-18 spec DOES require the server to echo `Mcp-Session-Id` in
the initialize response, so the caller can verify the session is
established; but the snippet should use the value the caller sent in.

### A5. **E08_S07 (Haiku summarizer) does not exist** — Voyage path only

Both confirm: no Haiku summarizer code in `server/`. No `import
anthropic` anywhere (banned by CLAUDE.md §4.7). S12 ships:
- `spend_constants.py` (cost constants for Voyage + Anthropic, both
  for forward-compat)
- Prometheus metric registration
- Voyage path increment **placement** (but see D2 below for *where*)
- Unit test using a mock increment
- `# TODO(E08_S07)` comment for the Anthropic increment

### A6. **`docs/observability/` does NOT exist** — create it for S11

R-1 (§"S11") flags as a CONFLICT: E14_S02 specified
`docs/observability/tracing.md` as a deliverable but the directory
doesn't exist. R-2 (§"`docs/observability/`") confirms the absence.
S11 creates `docs/observability/` plus the langfuse-orchestrator.md
file inside it. If a `tracing.md` stub is appropriate (per E14_S02's
unmet deliverable), defer that to a future cleanup — S11 only ships
the langfuse doc.

### A7. **No MCP tool-schema change** — no `EXPECTED_TOOL_SCHEMA_SHA256` re-pin

S09-S12 don't touch the MCP tool surface. `server/tools.py::ALL_TOOLS`
is untouched. R-2 explicit; R-1 implicit. No re-pinning needed.

### A8. **No `git push` / external writes** — purely local milestone

Both briefs confirm: 0 external writes. Single pre-push gate per
CLAUDE.md §4.4 stays with user post-rect.

---

## Resolved divergences

### D1. **Commit order — go with brief (S09 → S10 → S11 → S12 → S06)**

- **R-1 position:** S09 → S10 → S11 → S12 → S06 (matches brief).
- **R-2 position:** S06 → S09 → S10 → S11 → S12 — argues that S06 is
  zero-effort and produces content that may surface additional
  deferred items to reference in other sub-milestones.

**Resolution: adopt R-1's order (matches brief).** The brief's
reasoning ("Research may add un-park items surfaced during the other
four") is sound — implementing S09-S12 first may expose new deferred
items (e.g., "S09 dashboard could one day import Loki for logs" → add
to tracker). R-2's argument inverts the dependency direction; the
brief's direction is the canonical one.

### D2. **Where to wire the Voyage spend counter increment**

- **R-1 position:** "Wire the increment in `server/query_encoder.py`
  on the Voyage fallback path (after the existing
  `HOSTED_EMBED_FALLBACK_COUNTER.inc()` call)."
- **R-2 position:** "Do NOT increment the spend counter in the
  fallback path." The Voyage stub raises `NotImplementedError`
  immediately — no actual Voyage HTTP call ever happens, so no spend
  has occurred. R-2: register the metric + unit test (with a mock
  increment) + leave a `# TODO` at the stub.

**Resolution: adopt R-2's position.** The spend counter measures
*dollars spent*, not *call attempts*. Counting fallback events as
spend would systematically report nonzero spend with zero actual API
calls. The metric registration + unit test (mock-based) + a `# TODO`
comment at `_voyage_encode_stub` is the correct shape for v1. The
increment moves to the success branch when a real Voyage HTTP client
lands.

### D3. **Spend counter label set — 3 labels (brief is authoritative)**

- **R-2 flag:** design note (`08-security-observability-ops.md:143`)
  defines `arxmcp_api_spend_usd_total{provider, agent_role}` (2 labels).
- **Brief / roadmap:** `arxmcp_api_spend_usd_total{provider, model, agent_role}` (3 labels).

**Resolution: 3 labels.** The brief is authoritative for this
milestone; the design note is stale. Cardinality remains bounded:
2 providers × ~3 models × 4 roles = 24 max combinations. R-2 verified
this calculation; safe under Prometheus best practices.

### D4. **`agent_role` source — ContextVar, NOT a tool arg**

- **Brief language:** "agent_role from `_agent_role` tool arg (same as E14_S02)"
- **R-2 correction:** `arxmcp.agent_role` is populated from the
  `Arxmcp-Agent-Role` HTTP request header (read into ContextVar
  `current_agent_role` by `TracingContextMiddleware` in
  `server/middleware.py`). Per `08-security-observability-ops.md`
  §Tracing: "read from `Arxmcp-Agent-Role` HTTP request header; NOT
  a JSON-Schema property — keeps `TOOL_SCHEMA_VERSION` pinned at 6."
  Valid values bounded to `{"sketcher", "autoformalizer", "tactician",
  "fixer"}` per `VALID_AGENT_ROLES` frozenset.

**Resolution: read from `current_agent_role.get()`.** The brief is
wrong to call it a "tool arg." Wire the spend counter to read the
ContextVar.

### D5. **Langfuse SDK version — v4 (current stable)**

- **R-1:** Langfuse SDK v2 (`langfuse.trace()` as context manager)
- **R-2:** Langfuse SDK v4 (`langfuse.trace(session_id=...)` +
  `start_as_current_observation`)

**Resolution: use SDK v4 patterns.** R-2's research is more current.
The S11 snippet preamble: `# requires: langfuse>=4.0`. Use
`langfuse.trace(session_id=<mcp_session_id>, name=..., tags=[...])`.

### D6. **Grafana dashboard scope — JSON + provisioning YAML; NO compose file**

Both researchers want provisioning YAML. R-2 also recommends pinning
a Grafana container version (10.4.3) via `grafana-compose.yml`.

**Resolution: ship dashboard JSON + provisioning YAML; do NOT ship
grafana-compose.yml.** Justification:
1. The brief's S09 acceptance criterion is "`infra/observability/grafana-dashboard.json`
   validates as Grafana dashboard schema; README has 'Importing the
   dashboard' section." It does NOT require a compose file.
2. The operator runs Grafana however they want (often as part of an
   already-running observability stack). Shipping a compose file
   prescribes architecture we shouldn't.
3. Scope discipline: 5 bundled milestones already. Don't grow them.
4. The README "Importing the dashboard" section explains both manual
   UI import AND provisioning-based import (mount the JSON +
   provisioning YAML into a Grafana the operator already runs).

---

## Deferred concerns (not blocking implementation)

### Open questions to resolve at implementation time

1. **`arxmcp_embed_singleflight_dedup_total` exact location** (R-1 OQ1,
   R-2 OQ1). The metric is registered in `server/health.py:125` per
   R-1's read, but R-2 wants the implementer to confirm with
   `grep -rn singleflight_dedup` before writing the PromQL panel.
   **Action: grep at implement time; do not block.**

2. **Grafana `schemaVersion`** — both agree on 39 for max
   compatibility (Grafana 10.x–11.x). R-2 explicit; R-1 implicit.
   **Action: use 39.**

3. **`docs/observability/tracing.md` from E14_S02 was never created.**
   R-1 flags as conflict. Out of scope for this milestone — the
   E14_S02 unmet deliverable is a separate cleanup task. **Action:
   note in the deferred-work tracker (S06) so it's tracked.**

---

## Implementation plan (Phase 2 — INLINE path)

Estimated total: ~400 LOC (incl. dashboard JSON which dominates) +
~80 LOC tests. Single contiguous file boundary (mostly under
`infra/observability/`, `docs/ops/`, `docs/observability/`,
`server/observability/`, `tests/`, `.claude/notes/`). **INLINE.** No
worktree delegation.

### Commit 1 — S09 Grafana dashboard

- `infra/observability/grafana-dashboard.json` — sorted keys,
  deterministic UID `"arxmcp-cache-latency"`, `schemaVersion: 39`,
  panels: (a) cache hit ratio per tier — uses `{tier="1"}` etc.;
  (b) embedder singleflight dedup count — bare counter; (c) reranker
  P95 latency by model; (d) per-tool P95 request latency — uses
  `arxmcp_request_latency_seconds` (NOT `arxmcp_tool_latency_seconds`);
  (e) active inflight requests per tool.
- `infra/observability/grafana-provisioning.yml` — datasource (Prometheus
  at `http://localhost:9090`, hardcoded `uid: prometheus`) + dashboards
  (path `/etc/grafana/provisioning/dashboards/`).
- README.md "Importing the dashboard" section — operator-facing:
  manual UI import flow + provisioning import flow with copy-paste
  paths.
- Test: `tests/test_grafana_dashboard.py` — JSON-schema validation
  (minimal jsonschema check: `schemaVersion`, `uid`, `title`,
  `panels` required; each panel has `datasource`, `targets`); byte-
  stability (re-serialize sorted, assert equal to disk bytes); each
  panel's PromQL references a metric that actually exists in
  `server/observability/metrics.py` or `server/metrics.py` or
  `server/health.py` (grep-based).

### Commit 2 — S10 Ops runbook index

- `docs/ops/README.md` — index with 8 entries linking to existing
  files (`backup-restore.md`, `failure-modes.md`, `drift-watchdog.md`,
  `latexml-drift-runbook.md`) and 4 new files (`server-crash.md`,
  `model-swap.md`, `corpus-rollback.md`, `latexml-restart.md`).
- Each new file has the 4-part skeleton: **Symptoms / Detection /
  Steps / Verification**. Where existing files cover the substance
  (e.g., `failure-modes.md` covers disk-full), the new file is a thin
  redirect with a one-paragraph summary.
- Root `README.md` Operations section updated to link
  `docs/ops/README.md` as the single index entry-point.
- Test: `tests/test_runbook_index.py` — link-check (every relative
  `*.md` reference in `docs/ops/README.md` resolves to an existing
  file via absolute path assertion); each linked file contains the
  4-part skeleton headers (or, for the existing files, at least one
  of the 4 sections).

### Commit 3 — S11 Langfuse caller-side docs

- `docs/observability/` directory created.
- `docs/observability/langfuse-orchestrator.md` — explanation +
  Python reference snippet (< 60 LOC).
  - **Explicit disclaimer at top:** "This code runs OUTSIDE the
    arXMCP server process, in the orchestrator/caller codebase."
  - **SDK version pin:** `# requires: langfuse>=4.0, anthropic>=0.40`
  - **Session ID handling:** caller passes the value they already
    sent in the `Mcp-Session-Id` request header (the server does NOT
    echo it in responses — per A4 above); the snippet stores it in
    a variable and uses `langfuse.trace(session_id=...)`.
  - Wraps the `anthropic.Anthropic().messages.create(...)` call in a
    Langfuse trace; logs tool inputs and outputs.
- Test: `tests/test_langfuse_doc.py` — extract the snippet from the
  markdown file, doctest-style import smoke; gated with
  `pytest.mark.skipif(not has_langfuse, reason="langfuse not installed")`.
  Do NOT add `langfuse` to `pyproject.toml`.

### Commit 4 — S12 API spend metrics

- `server/observability/spend_constants.py` (NEW file, existing
  directory):
  ```python
  # Pricing source URLs + LAST_VERIFIED date in docstring
  VOYAGE_3_USD_PER_M_TOKENS = 0.06        # input only
  CLAUDE_HAIKU_4_5_INPUT_USD_PER_M  = 1.00
  CLAUDE_HAIKU_4_5_OUTPUT_USD_PER_M = 5.00
  LAST_VERIFIED = "2026-05-22"
  ```
- Prometheus metric registration in `spend_constants.py`:
  ```python
  API_SPEND_USD_TOTAL = Counter(
      "arxmcp_api_spend_usd_total",
      "Cumulative API spend in USD.",
      labelnames=["provider", "model", "agent_role"],
  )
  ```
- Helper function `record_spend(provider, model, tokens_in,
  tokens_out=0)` that reads `current_agent_role.get()` (D4) and
  calls `.inc()` with the correct USD amount.
- At `server/query_encoder.py::_voyage_encode_stub`: a
  `# TODO(future-voyage-client): call record_spend(...) here when the
  real Voyage HTTP path lands` comment. **No increment in the stub
  per D2.**
- `# TODO(E08_S07): wire record_spend for Haiku once summarizer lands` comment.
- Test: `tests/test_spend_constants.py` — value-sanity (constants are
  positive floats, < $100/M tokens upper bound); counter-increment
  unit test using `prometheus_client.REGISTRY` snapshot before/after
  a `record_spend` call; label-cardinality test (4 valid agent_roles
  × 2 providers × known models all `.labels()` cleanly).

### Commit 5 — S06 Deferred-work tracker

- `.claude/notes/deferred-work-tracker.md` aggregating:
  - 3 items from E14_S06 roadmap text: ColBERT-v2 late interaction,
    TikZ-cd diagram extraction, proof-skeleton classifier.
  - From `.claude/notes/09-feature-priorities.md`: PDF figure
    extraction (Tier 6+), OCR of pre-2007 scanned papers (explicit
    non-build).
  - From `.claude/notes/06-mcp-server-design.md`: `paper_diff` tool
    (deferred to Tier 4).
  - From `.claude/notes/08-security-observability-ops.md`: mTLS,
    Alertmanager routing, budget alerting (Tier-6+ hardening).
  - From `.claude/notes/10-references-and-prior-art.md`: any items
    marked "v1.5 candidate" or "v2 candidate."
  - **NEW item surfaced by this milestone's research:**
    `docs/observability/tracing.md` from E14_S02 was never created;
    the E14_S02 state.json claims complete but the file is missing.
    Track as "E14_S02 unmet deliverable; cleanup task."
  - **Explicit non-goal:** "LLM-critic tool" — flagged in design
    notes as a hard non-goal, included for visibility.
- Each item has 3 sub-bullets: (1) what it is, (2) why it was
  deferred, (3) un-park trigger (concrete and falsifiable).
- Review cadence: documented in the tracker — quarterly, aligned
  with restore drill.
- Test: none required (notes file).

### Run `make test` after each commit. Ruff clean throughout.

---

## Orchestrator synthesis notes

- **Heavy alignment between researchers on the 4 brief-vs-codebase
  drifts** (A1 metric name, A2 runbook path, A3 directory existence,
  A4 session header). These are the highest-leverage findings — fixing
  the brief would have prevented all four.
- **One substantive disagreement on Voyage increment placement
  (D2)** — R-2's "no spend incurred = no increment" framing is
  correct; the metric measures dollars, not call attempts.
- **One scope grow-attempt rejected (D6 grafana-compose.yml)** — keep
  scope tight; ship JSON + provisioning YAML only.
- **The E14_S02 `docs/observability/tracing.md` unmet deliverable
  surfaces as an unexpected discovery** — recorded as a S06 tracker
  item for follow-up rather than handled inline.

---

## Open questions for the implementer

1. **`arxmcp_embed_singleflight_dedup_total` exact registration
   location.** Confirmed by R-1 as `server/health.py:125`; verify
   with `grep -rn singleflight_dedup server/` at impl time.
2. **Whether the link-check test (S10) should also follow links to
   anchors inside files** (e.g., `failure-modes.md#disk-full`).
   Recommendation: just file existence for v1; anchor-level checking
   is a future enhancement.

---

## External writes the implementation will require

**Zero — purely local.**
- No `git push`, no `gh issue create`, no Grafana API call, no
  infra apply, no third-party API.
- The Grafana dashboard JSON is checked into source; the operator
  imports it manually (UI) or via volume-mounted provisioning YAML.
- All file edits within `$REPO_ROOT`: `infra/observability/`,
  `docs/ops/`, `docs/observability/`, `server/observability/`,
  `tests/`, `.claude/notes/`, root `README.md`.
- Single pre-push authorization remains the only external-write gate;
  rectifier phase does not introduce external writes either.
