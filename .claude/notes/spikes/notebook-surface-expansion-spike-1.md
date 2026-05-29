# Spike — notebook-surface-expansion-spike-1

**Question (confidence → evidence):** Can notebooks be exposed as MCP **resources**
(`resources/list` + `resources/read`) and can a static `initialize.instructions`
string be set — WITHOUT drifting `EXPECTED_TOOL_SCHEMA_SHA256` (the `tools/list`
wire bytes) or `EXPECTED_BP1_SHA256` (the BP1 prompt-cache breakpoint)?

**Gates:** epic **e2** (agent/MCP discovery surface).
**Date:** 2026-05-29. **Method:** throwaway prototype against the pinned
`mcp` SDK (FastMCP, `mcp>=1.27,<2`; live `1.27.x`). No code committed to the
server.

## Verdict: **GO** (for the `resources/list` + `resources/read` + `instructions` MVP)

Byte-stability holds — proven empirically AND structurally. The
`resources/subscribe` capability is **not** available in FastMCP 1.27.x
(`subscribe=False`), so the subscribe-driven "live notebook list" remains
soft-gated; the list+read MVP is buildable today.

---

## Evidence (empirical)

A throwaway script built TWO `FastMCP` servers and compared the canonical
`ListToolsResult` SHA-256 (the exact computation `tests/test_server_tool_schema.py`
pins):

| server | construction | tools | tool-schema SHA-256 |
|---|---|---|---|
| **baseline** | `FastMCP("arxmcp", json_response=True)` + `register_all` | 8 | `c7df4c5c…d13375` |
| **treatment** | baseline **+ `instructions="…"`** **+ a concrete `arxmcp://notebooks/demo` resource** **+ a `arxmcp://notebooks/{slug}` template** | 8 | `c7df4c5c…d13375` |

- `treatment_hash == baseline_hash == EXPECTED_TOOL_SCHEMA_SHA256` — **byte-identical.**
- `resources/list` → `['arxmcp://notebooks/demo']`; `list_resource_templates` →
  `['arxmcp://notebooks/{slug}']` — resources work.
- `initialize.instructions` is present when the constructor arg is set.
- `initialize.capabilities.resources` = `subscribe=False listChanged=False` in
  **both** baseline and treatment — FastMCP advertises the resources capability
  **unconditionally**, so registering a resource does NOT change the advertised
  capability shape either.
- Both byte-stability gates (`tests/test_server_tool_schema.py` +
  `tests/test_prompts.py`, 42 tests) are **green on current main** — the baseline
  anchor for "unchanged".

## Why it holds (structural — not just empirical)

1. **Tool-schema hash covers ONLY `tools/list`.** `_serialize_tools` hashes
   `ListToolsResult(tools=mcp_server.list_tools())` and nothing else
   (`tests/test_server_tool_schema.py:158-190`). Resources are a SEPARATE JSON-RPC
   method (`resources/list` / `resources/read`); they never enter `ListToolsResult`.
   FastMCP keeps tools, resources, and templates in distinct registries — confirmed
   by the byte-identical hash with two resources registered.
2. **BP1 is the ORCHESTRATOR's prompt assembly, not the MCP handshake.**
   `EXPECTED_BP1_SHA256` hashes `SYSTEM_PROMPT + ALL_TOOLS` assembled into the
   Anthropic Messages request by `_build_fanout_request` (`tests/test_prompts.py`).
   A repo-wide grep of `server/prompts.py` + `server/orchestrator/*.py` for
   `instructions|initialize|capabilities|InitializeResult` returns **nothing** — BP1
   has zero coupling to the MCP `initialize` response. `initialize.instructions` is
   a server→client handshake field that the calling harness MAY surface to the
   operator; it is NOT part of the cached system+tools prefix. So it is
   *structurally impossible* for `initialize.instructions` to drift BP1.
3. **The MCP `initialize` response is not in the Anthropic prompt cache at all.**
   BP1/BP2 are Anthropic `cache_control` breakpoints over the orchestrator's
   request. Even if the MCP initialize bytes changed, BP1/BP2 could not move. (And
   they don't change: capabilities.resources is identical baseline-vs-treatment.)

## The `resources/subscribe` soft-gate (confirmed)

FastMCP 1.27.x advertises `capabilities.resources.subscribe = False` and does not
implement a `resources/subscribe` handler. So:
- **Buildable now:** `resources/list` + `resources/read` (a static/poll model — the
  agent enumerates corpora on demand).
- **Deferred:** `resources/subscribe` (push notification on notebook-list change).
  This matches the roadmap's "soft-gated on the harness's resources/subscribe
  maturing" note. e2's MVP must NOT depend on subscribe.

## Implementation guidance for the e2 milestone(s)

- **`initialize.instructions`** is a one-line change at `server/main.py:654`:
  `FastMCP("arxmcp", json_response=True, instructions=ARXMCP_INSTRUCTIONS)`. Keep
  the string a module-level constant (e.g. in `server/prompts.py` or a new
  `server/mcp_instructions.py`) so it is reviewable and testable. It does NOT touch
  BP1 — but a guard test should pin it independently (its own hash) so a future
  edit is intentional.
- **Resources** register via `@mcp_server.resource("arxmcp://notebooks/{slug}")`
  (template → `read_resource`) and/or `add_resource(...)` for a concrete index
  resource (e.g. `arxmcp://notebooks` listing all slugs). Register them in
  `register_all` (or a sibling `register_resources`) AFTER `register_all_tools`,
  BEFORE `mount_mcp` (same snapshot-at-mount constraint as tools — `main.py:655`).
- **`resources/read` payload:** return notebook METADATA only (slug, display_name,
  created_at, parse_status, paper count, lancedb_path) — NOT chunk content. This
  is read-only discovery; mutation stays in the `/ui/api` REST surface (the brief's
  "resources/read-only only" scope-out). Source it from `NotebooksStore`
  (`list_notebooks` / `get_notebook` / `list_papers`) — zero new query cost beyond
  what the UI already does.
- **Byte-stability regression guard:** the e2 milestone MUST keep
  `tests/test_server_tool_schema.py` + `tests/test_prompts.py` green WITHOUT
  re-pinning either hash. If either drifts, the resource/instructions wiring leaked
  into the tool registry or the orchestrator prefix — STOP and fix the leak; do NOT
  re-pin. Add a NEW test asserting `tools/list` bytes are unchanged after resources
  are registered (mirror this spike's two-server comparison).

## Residual risks for the e2 adversary to check

- **Resource URI = path-traversal surface.** `arxmcp://notebooks/{slug}` must run
  the same `validate_slug` guard as the REST routes before any `NotebooksStore` /
  filesystem access. A resource read is an UNAUTHENTICATED MCP call — treat `slug`
  as hostile (same as the UI).
- **Indirect-prompt-injection in `resources/read` output.** Notebook
  `display_name` is operator-authored; if `resources/read` returns it to an agent,
  wrap/escape per the `<retrieved_chunk>` discipline in
  `08-security-observability-ops.md` (the agent may feed it to an LLM).
- **`initialize.instructions` content drift.** Pin it with its own hash so it
  doesn't silently change; keep it short and factual (no secrets, no host paths).
- **Stale "7-tool" framing.** The surface is actually **8 tools** today
  (`lean_verify` is the 8th; `TOOL_SCHEMA_VERSION=16`). e2 docs/briefs should say
  "the frozen 8-tool surface", not 7.

## Decision

**GO.** Decompose e2 into milestones (suggest: `e2-m1` resources/list+read +
byte-stability guard test; `e2-m2` `initialize.instructions` + its pin test). Defer
any `resources/subscribe` work until the SDK/harness advertises `subscribe=True`.
Re-invoke `/roadmap notebook-surface-expansion` (or a fresh slug) to materialize the
e2 milestones, then `/milestone-pipeline notebook-surface-expansion-e2-m1`.
