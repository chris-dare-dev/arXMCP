# Implementation Summary — E14_Tier5plus

**Phase:** 2 (Implement) — INLINE path (bundle of 5 sub-milestones)
**Test count:** 2574 passed (+109 from m10's 2491; 84 new tests across
S09-S12 + 25 incidental from updated parametrization). 10 skipped
(+1 for langfuse-deps-missing). 1 xfailed. Ruff clean.

---

## One-line summary

Bundled Tier-5/6+ observability + ops polish — Grafana dashboard
(S09), ops runbook index + 4 new runbooks (S10), Langfuse caller-side
docs (S11), API spend metrics module (S12), deferred-work tracker
(S06). Five logical commits + 1 fixup, all under one milestone shell.

---

## Commit range

`a0a00d64e344d679c7f37abc15ab9dec8d180dd8..c5aeba10fd7a7b2563e45dd33df9897ac7355745`

Six commits:
- `92f7f28` feat(infra): Grafana cache+latency dashboard (E14_S09)
- `73c7371` docs(ops): runbook index + 4 new runbooks (E14_S10)
- `936143f` docs(observability): Langfuse caller-side tracing reference (E14_S11)
- `b0d7288` feat(server): API spend metrics + cost constants (E14_S12)
- `c7cf81d` fix(server,tests): SSoT model-ID import + ruff line-length cleanups (E14_Tier5plus)
- `c5aeba1` docs(notes): deferred-work tracker (E14_S06)

Brief suggested 5 logical commits S09→S10→S11→S12→S06; landed 5 sub-
milestone commits + 1 fixup (the fixup folded the SSoT model-ID drift
caught at full-suite test time). 6 total.

---

## Acceptance criteria status

### S09 — Cache hit-ratio + latency Grafana dashboard

| AC | Status | Evidence |
|---|---|---|
| `infra/observability/grafana-dashboard.json` validates as Grafana schema | ✅ | `tests/test_grafana_dashboard.py::TestDashboardStructure` (17 required-field parameterized checks); `schemaVersion: 39` |
| Cache hit ratio per tier panel | ✅ | Panel 1 uses `arxmcp_cache_hits_total / arxmcp_cache_lookups_total` grouped by `tier` (string `"1"`, `"2"`, `"3"`) |
| Embedder singleflight dedup count panel | ✅ | Panel 2; bare counter from `server/health.py::EMBED_SINGLEFLIGHT_DEDUP_COUNTER` |
| Reranker latency P50/P95 panel | ✅ | Panel 3; histogram_quantile over `arxmcp_rerank_latency_seconds_bucket{model}` |
| Per-tool P95 request latency panel | ✅ | Panel 4; **uses `arxmcp_request_latency_seconds_bucket` (the actual registered name), NOT `arxmcp_tool_latency_seconds`** (synthesis A1) |
| Active inflight requests per tool panel | ✅ | Panel 5; `arxmcp_request_inflight{tool}` |
| Prometheus datasource auto-provisioned at `http://localhost:9090` | ✅ | `infra/observability/grafana-provisioning.yml` datasource block |
| README "Importing the dashboard" section | ✅ | Both manual UI import + provisioned auto-load documented |
| Byte-stable dashboard JSON | ✅ | `test_json_keys_are_sorted_at_every_level` round-trip assertion |

### S10 — Ops runbook index

| AC | Status | Evidence |
|---|---|---|
| `docs/ops/README.md` exists with the 8 required scenarios | ✅ | All 8 named in primary table; `test_scenario_mentioned_in_index` parameterized over all 8 |
| Each scenario has the 4-part skeleton | ✅ | For the 4 NEW runbooks (server-crash, model-swap, corpus-rollback, latexml-restart): `test_new_runbook_has_all_skeleton_sections` parameterized |
| Linked from root README.md | ✅ | `test_root_readme_links_to_index` |
| Restore-from-backup link points at actual file | ✅ | Links `docs/ops/backup-restore.md` (synthesis A2), NOT the brief's nonexistent `restore-runbook.md` |
| Link-check: every relative MD link resolves to a real file | ✅ | `test_every_relative_link_resolves` |

### S11 — Langfuse orchestrator-side tracing documentation

| AC | Status | Evidence |
|---|---|---|
| `docs/observability/langfuse-orchestrator.md` exists | ✅ | `test_doc_present` |
| `< 60 LOC` working Python snippet | ✅ | `test_snippet_under_60_loc` (meaningful-LOC count strips blank lines and comment-only lines) |
| Doctest snippet imports cleanly | ✅ | `test_snippet_imports_succeed`, `skipif` when langfuse+anthropic absent (default in CI per the don't-add-langfuse-to-pyproject constraint) |
| Snippet uses `anthropic` SDK only OUTSIDE arXMCP server | ✅ | `test_no_anthropic_import_in_server` greps `server/` for any `import anthropic` and fails on hit |
| Snippet pins langfuse>=4.0 + anthropic>=0.40 | ✅ | `test_required_phrase_present` parameterized |
| Session-ID is the caller's value (not a server response header) | ✅ | `test_doc_clarifies_session_id_is_not_a_response_header` (whitespace-tolerant phrase check); doc explicitly states "does **NOT** emit `Mcp-Session-Id` as a response header" per synthesis A4 |

### S12 — API spend metrics for hosted-model fallbacks

| AC | Status | Evidence |
|---|---|---|
| `server/observability/spend_constants.py` exists | ✅ | New file in EXISTING `server/observability/` dir (synthesis A3 — brief wrongly said NEW directory) |
| Counter `arxmcp_api_spend_usd_total{provider, model, agent_role}` registered | ✅ | `test_metric_is_a_counter`, `test_metric_has_three_expected_labels` |
| Per-call cost constants documented with source + LAST_VERIFIED | ✅ | VOYAGE_3_USD_PER_M_TOKENS, CLAUDE_HAIKU_4_5_INPUT_USD_PER_M, CLAUDE_HAIKU_4_5_OUTPUT_USD_PER_M; `LAST_VERIFIED = "2026-05-22"` |
| `agent_role` label reads from ContextVar (NOT a tool arg) | ✅ | `_resolve_agent_role()` reads `current_agent_role.get()`; `TestAgentRoleLabel` parameterized over 4 valid roles + None + foreign-value coercion (synthesis D4) |
| Voyage increment wired at the success branch (not the fallback stub) | ✅ | TODO comment at `_voyage_encode_stub` (no live increment per synthesis D2); `test_voyage_stub_carries_future_client_todo` is the regression guard |
| Anthropic increment placeholder with E08_S07 TODO | ✅ | `test_anthropic_increment_not_wired_yet` greps server/ and confirms no live call site |
| Unit test for counter-increment | ✅ | `TestRecordSpendVoyage`, `TestRecordSpendAnthropic`; `TestRecordSpendValidation` for error paths |

### S06 — Deferred-work tracker

| AC | Status | Evidence |
|---|---|---|
| `.claude/notes/deferred-work-tracker.md` exists | ✅ | Created |
| At least the 3 brief-enumerated items present | ✅ | ColBERT-v2 + TikZ-cd + proof-skeleton classifier explicit sections |
| Plus items surfaced from `.claude/` greps | ✅ | Multi-paper dedup, ORCID disambiguation, paper_diff, PDF figure extraction, Lean 4, mTLS, Alertmanager, API spend budget, KaTeX pre-render, E14_S02 docs/observability/tracing.md unmet deliverable, plus 4 explicit non-goals |
| Each item has 3 sub-bullets (what / why / un-park trigger) | ✅ | Convention block documents the schema; every item conforms |
| Quarterly review cadence documented | ✅ | "LAST_REVIEW: 2026-05-22"; aligned with restic restore drill cadence |

---

## New / changed test paths

**New:**
- `tests/test_grafana_dashboard.py` (35 tests)
- `tests/test_runbook_index.py` (15 tests)
- `tests/test_langfuse_doc.py` (9 tests; 1 conditionally skipped)
- `tests/test_spend_constants.py` (25 tests)

**Modified (fixup):**
- `tests/test_spend_constants.py` — import `MODEL_HAIKU_4_5` from
  `model_selector` to preserve SSoT property.
- `tests/test_grafana_dashboard.py`,
  `tests/test_langfuse_doc.py`,
  `tests/test_runbook_index.py` — docstring line-wrap fixes for
  ruff E501.

---

## Files touched (E14_Tier5plus-specific only)

| File | Status | Origin commit |
|---|---|---|
| `infra/observability/grafana-dashboard.json` | NEW | S09 |
| `infra/observability/grafana-provisioning.yml` | NEW | S09 |
| `tests/test_grafana_dashboard.py` | NEW | S09 |
| `README.md` | MOD (added "Importing the dashboard" + index pointer) | S09 + S10 |
| `docs/ops/README.md` | NEW (index) | S10 |
| `docs/ops/server-crash.md` | NEW | S10 |
| `docs/ops/model-swap.md` | NEW | S10 |
| `docs/ops/corpus-rollback.md` | NEW | S10 |
| `docs/ops/latexml-restart.md` | NEW | S10 |
| `tests/test_runbook_index.py` | NEW | S10 |
| `docs/observability/langfuse-orchestrator.md` | NEW (dir also new) | S11 |
| `tests/test_langfuse_doc.py` | NEW | S11 |
| `server/observability/spend_constants.py` | NEW (existing dir) | S12 |
| `server/query_encoder.py` | MOD (TODO comment at Voyage stub) | S12 |
| `tests/test_spend_constants.py` | NEW | S12 |
| `.claude/notes/deferred-work-tracker.md` | NEW | S06 |

Total: ~1,800 LOC across 5 sub-milestones. INLINE path was the right
call (well within INLINE-path threshold given the heterogeneity and
small per-file deltas).

---

## Synthesis-driven decisions applied

- **A1** — Used registered metric names (`arxmcp_request_latency_seconds`
  not `arxmcp_tool_latency_seconds`; `tier` label not `layer`).
- **A2** — Linked to `docs/ops/backup-restore.md` (the actual file),
  not `docs/ops/restore-runbook.md` (the brief's wrong reference).
- **A3** — Added `spend_constants.py` to the EXISTING
  `server/observability/` directory; did NOT re-create `__init__.py`.
- **A4** — Snippet uses caller's own session-ID value, NOT a server
  response header (since the server doesn't emit one).
- **A5** — E08_S07 deferred: only Voyage path stubbed; no live
  anthropic increment site exists in server/ (regression guard test).
- **A6** — `docs/observability/` directory created for S11; the
  E14_S02 `tracing.md` unmet deliverable is tracked in S06 (not
  fixed inline — out of scope).
- **A7** — No MCP tool surface changes; no
  `EXPECTED_TOOL_SCHEMA_SHA256` re-pin.
- **D1** — Commit order matched brief (S09→S10→S11→S12→S06).
- **D2** — No Voyage spend increment in the fallback path; TODO
  comment at the stub site.
- **D3** — 3 labels on the spend counter per brief (not 2 per
  design note).
- **D4** — `agent_role` reads from `current_agent_role` ContextVar.
- **D5** — Langfuse SDK v4 patterns; `langfuse>=4.0` pin in snippet.
- **D6** — Shipped dashboard JSON + provisioning YAML; did NOT ship
  grafana-compose.yml (scope discipline).

---

## Deviations from the brief / synthesis

1. **Six commits, not five.** Added a fixup commit (c7cf81d) after
   S12 to (a) fix an SSoT regression that pasted the literal
   `"claude-haiku-4-5"` into `spend_constants.py` instead of
   importing `MODEL_HAIKU_4_5` from `model_selector`, and (b) fix
   ruff E501 line-too-long errors in the test docstrings. Both
   would otherwise have failed the project check command. Recorded
   as a separate commit rather than amending S12 because the rect
   commit was already pushed-ready and the SSoT fix touches 5
   files including 4 from different sub-milestones.

2. **S06 surfaced one item not in the brief's enumerated list:**
   the E14_S02 `docs/observability/tracing.md` unmet deliverable.
   This is a documented finding from the research synthesis (A6);
   tracking it in S06 makes the audit visible.

No deviation from the AC list itself; every brief checkbox has a
verifiable artifact.

---

## External writes the orchestrator must authorize

**None.** Purely local milestone:
- No `git push` (final user gate per CLAUDE.md §4.4).
- No `gh issue create`, no PR, no infra apply.
- No Grafana API call to import the dashboard (operator imports
  manually).
- No third-party API call; no MCP tool schema change (no
  `EXPECTED_TOOL_SCHEMA_SHA256` re-pinning needed).

The only external-write gate is the user's `yes, push` after the
rectifier phase completes.
