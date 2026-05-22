# Implementation Summary — verification-feedback-m1

**Summary.** The `cite_neighbors` MCP handler is wired to the live `server/graph_queries.py::cite_neighbors` library, replacing the v1 empty stub; the E09_S03 F2 path-validation contract is closed at the tool boundary.

**Commit range:** `ead7af9..2e30dcc` (feat commit `2e30dccc4b89bb2944ea95e3ac3b99a8f3be25fa`, GPG-signed).

**Implementation path:** INLINE (orchestrator, main session) — ~5 source/test files + 1 doc + a Config field; no novel architecture; no specialist agent registered.

## Acceptance criteria status

| AC | Status | Notes |
|---|---|---|
| AC1 — handler calls the library, stub removed | ✅ met | `server/handlers/citations.py` calls `cite_neighbors(...)`; `infrastructure_status: "deferred"` path removed. |
| AC2 — direction enum re-aligned, schema hash re-pinned | ✅ met | Handler `direction` → `Literal["cites","cited_by","depends_on"]`; `TOOL_SCHEMA_VERSION` 9→10; `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` re-pinned via `pytest --update-tool-schema-hash`. |
| AC3 — paths from Config, not agent JSON (F2) | ✅ met | New `Config.kuzu_path`; both Kùzu + LanceDB paths derived from `get_resources().config`. Verified by `TestHandlerEndToEnd`. |
| AC4 — cache entries include `graph_version`; re-ingest invalidates | ⚠️ met-by-exclusion | m1 does **not** cache `cite_neighbors` (the Phase-3 challenger's sanctioned option b, see `research-synthesis.md` §2). Every call reads the live Kùzu graph → a re-ingest can never serve stale neighbors; AC4's correctness intent holds by construction. The `graph_version`-keyed cache is an optimization explicitly deferred to a future caching milestone. |
| AC5 — handler-level test, 500 ms gate | ✅ met | `TestHandlerEndToEnd` in `tests/test_proof_chain.py` exercises `handle_cite_neighbors` end-to-end including a handler-level 500 ms perf-gate test. |
| AC6 — `make test` green, `ruff check .` clean | ✅ met (caveat) | `make` is unavailable on this Windows workstation → used the project-check fallback `ruff check . && uv run python -m pytest`. `ruff check .` clean repo-wide. Full suite: 34 failures, **all pre-existing** (Windows/env — `killpg`, symlinks, subprocess determinism, `latexmlc` binary, POSIX heredoc, Kùzu ingest; CLAUDE.md §3 documents ~29 Windows-platform failures + env-gated `TestIntegrationRealLatexmlc`/docker tests). Verified against the base commit: **zero new failures introduced**. The 262 tests covering the changed surface all pass. |

## New / changed test paths

- `tests/test_proof_chain.py` — **added** `TestHandlerEndToEnd` (5 handler-level tests: real-neighbors, `cited_by` direction, 500 ms perf gate, malformed-chunk_id rejection, graph-absent degradation) + the `handler_resources` fixture.
- `tests/test_tools_all.py` — `test_cite_neighbors_stub` → `test_cite_neighbors_wired` (asserts the wired behavior; the old stub assertion is gone).
- `tests/test_server_tool_schema.py` — `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` re-pinned (the schema-change regression guard).
- `tests/test_prompts.py` — `EXPECTED_BP1_SHA256` re-pinned (the tool-array change drifts the BP1 prompt-cache hash — same byte-stability discipline).

## Files changed

- `server/config.py` — added `kuzu_path: Path` field.
- `server/handlers/citations.py` — stub replaced with the live wiring.
- `server/tools.py` — `CITE_NEIGHBORS` description rewritten; `TOOL_SCHEMA_VERSION` 9→10.
- `server/schemas/search_papers_result.json` — `version` 9→10, `$id` v9→v10 (tracks the global `TOOL_SCHEMA_VERSION`).
- `.claude/docs/proof-chain-workflow.md` — stub paragraph updated to reflect the wired handler.

## Deviations from the synthesis design

- **D1 — `depth` kept at `Field(le=3)`** (synthesis proposed clamping to `le=2`). `tests/security/test_resource_exhaustion.py::test_cite_neighbors_depth_field_constraint_present` pins `le == 3` (E13_S04 Threat-4). `depth=3` is rejected by the library's explicit `ValueError("depth must be 1 or 2")` — an equally clean, fast error. Keeping `le=3` avoids editing a security test for no functional gain.
- **D2 — `.claude/notes/06-mcp-server-design.md` stale `direction` enum NOT corrected** (synthesis §3 proposed correcting it). Editing the design constitution is outside m1's scope; the drift is pre-existing. Flagged here for a future docs milestone. The shipped library remains the authority.
- **D3 — added a `graph_status` response field** (`"absent"` / `"present"`). Not named in the synthesis, but follows from the AC4 no-cache decision: the handler must handle a not-yet-ingested Kùzu graph gracefully (return empty neighbors, not a 5xx). `graph_status` makes that observable to the consuming agent.
- **D4 — `EXPECTED_BP1_SHA256` re-pinned** alongside `EXPECTED_TOOL_SCHEMA_SHA256`. The synthesis named the tool-schema hash re-pin but not BP1; BP1 = system prompt + tools array, so a tool-array change drifts it too. Caught by the full-suite run (`test_prompts.py::test_bp1_hash_pinned`), confirmed a regression-vs-base, and re-pinned — the established paired-update pattern.

## External writes required

**None.** Purely local: source + tests + a Config field + a doc update. No push, no PR, no ticket, no infra mutation, no external API call. `external_writes_required = []`.
