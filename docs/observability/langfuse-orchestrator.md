# Langfuse orchestrator-side tracing

> **This code runs OUTSIDE the arXMCP server process.** It belongs
> in the orchestrator / agent runner that calls into arXMCP via
> Claude tool-use. Per `CLAUDE.md` §4.7 and
> `.claude/notes/08-security-observability-ops.md` § "Recommended
> export targets" — *"Langfuse if/when the agent orchestrator
> becomes part of this repo."* Today the orchestrator lives in the
> caller's codebase; arXMCP `server/` source MUST NOT import
> `anthropic` or `langfuse`.

## What this enables

End-to-end tracing from the orchestrator's Claude API call through
the MCP tool result, with both sides joined on a single MCP
session ID. The arXMCP server-side OpenTelemetry spans (E14_S02)
carry `mcp.session_id`; the Langfuse trace carries the same value
in `session_id` so a single Langfuse view shows the full request
flow.

## Session ID handling

The arXMCP server does **NOT** emit `Mcp-Session-Id` as a response
header — it only *consumes* the header from the client request
(see `server/middleware.py::TracingContextMiddleware`). The
session ID lives on the orchestrator side:

- The caller generates it (typically a UUIDv4 per agent session).
- The caller sends it as the `Mcp-Session-Id` request header on
  every `tools/call`.
- The caller uses the same value as the Langfuse `session_id` so
  Langfuse and OTel join on it.

Per the MCP 2025-06-18 spec, the server echoes the session ID in
its initialize response — the orchestrator can verify the session
was established but should not need to re-read it.

## Reference snippet (< 60 LOC, runs in the caller's codebase)

```python
# requires: langfuse>=4.0, anthropic>=0.40, mcp-client>=0.5
# Runs OUTSIDE the arXMCP server. The session_id is the orchestrator's
# own value, sent to arXMCP as the Mcp-Session-Id request header.
from __future__ import annotations

import uuid
from typing import Any

import anthropic
from langfuse import Langfuse  # type: ignore[import-not-found]
from mcp import ClientSession  # type: ignore[import-not-found]


async def call_claude_with_arxmcp_tracing(
    user_prompt: str,
    arxmcp_session: ClientSession,
    langfuse: Langfuse,
    *,
    mcp_session_id: str | None = None,
    model: str = "claude-sonnet-4-5",
) -> Any:
    """Run one Claude turn with MCP tool-use, traced into Langfuse.

    Both the Anthropic call and the MCP tool result land in the same
    Langfuse trace; the trace is keyed by ``mcp_session_id`` so the
    arXMCP server-side OTel spans (E14_S02) join cleanly.
    """
    mcp_session_id = mcp_session_id or str(uuid.uuid4())
    trace = langfuse.trace(
        name="arxmcp-call",
        session_id=mcp_session_id,
        tags=[f"mcp_session_id:{mcp_session_id}"],
        input={"user_prompt": user_prompt, "model": model},
    )

    tools = await arxmcp_session.list_tools()
    claude = anthropic.AsyncAnthropic()
    msg = await claude.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": user_prompt}],
        tools=[t.to_anthropic_schema() for t in tools.tools],
        extra_headers={"Mcp-Session-Id": mcp_session_id},
    )
    trace.update(output={"stop_reason": msg.stop_reason})

    for block in msg.content:
        if block.type == "tool_use":
            with langfuse.start_as_current_observation(
                name=f"mcp.{block.name}", as_type="span",
            ) as span:
                span.update(input=block.input)
                result = await arxmcp_session.call_tool(
                    block.name, block.input,
                )
                span.update(output={"result": str(result)[:512]})
    return msg
```

## Cadence and gotchas

- **Langfuse SDK pin.** The snippet uses Langfuse Python SDK v4
  (`langfuse>=4.0`). The v3 → v4 migration restructured the
  client; pinning the major version protects against silent
  breakage.
- **Anthropic SDK.** Pin `anthropic>=0.40` for stable tool-use
  block typing. The snippet uses `block.type == "tool_use"`
  which is stable across recent versions.
- **Trace cardinality.** A new Langfuse trace per Claude turn is
  reasonable for low-volume agents; if your orchestrator does
  hundreds of turns per session, batch into one trace per session
  with one span per turn.
- **MCP session lifecycle.** The session ID is sticky for the
  agent's lifetime; do not regenerate per tool call. The arXMCP
  server uses the session ID to scope the per-session retrieval
  cap (E08_S04) — switching IDs mid-session resets the cap.

## Cross-references

- arXMCP server-side OTel spans: `server/observability/tracing.py`
  (E14_S02).
- Threat model + observability targets:
  `.claude/notes/08-security-observability-ops.md`.
- Orchestrator rules (model selection, tool-use ID
  canonicalization): `.claude/docs/orchestrator-rules.md`.
- Prompt-cache discipline (BP1/BP2 breakpoints):
  `.claude/notes/prompts-bp-discipline.md`.
