# Orchestrator rules

This document is the canonical reference for orchestrator
implementors building on top of the arXMCP server. The two rules
below are E08_S04's load-bearing decisions; future orchestrator
work (E08_S05+, multi-agent fan-out) MUST honor both.

The corresponding code lives at:
- `server/orchestrator/id_canon.py` — Rule 1 implementation
- `server/session.py` + `server/middleware.py::SessionCapMiddleware` —
  Rule 2 implementation

## Rule 1 — Tool-use ID canonicalization

### What

Every `tool_use_id` echoed back in `tool_result` blocks AND every
`id` on `tool_use` blocks MUST be replaced with a deterministic
canonical ID before the messages list is composed into another
agent's prompt context.

The canonical format is `toolu_{counter:08d}` where `counter` is a
per-call monotonically increasing integer reset to 0 at the start
of every `canonicalize_turn` invocation.

### Why

The Anthropic Messages API assigns server-side **non-deterministic**
IDs to `tool_use` and `tool_result` blocks. Two identical requests
get two different IDs. In the project's 4-agent fan-out, the
orchestrator composes one agent's tool-call history into another
agent's prompt context. If agent A's tool call carries a
non-deterministic ID and that exact byte sequence ends up in agent
B's prompt prefix, agent B's prompt cache misses.

The prompt cache key is the byte hash of the prefix. Even a single
non-deterministic byte invalidates it. So a 4-agent fan-out with
even one shared tool call drops cross-agent cache hit rate from
~95% to ~25% on the affected slot.

The cited design note (`.claude/notes/07-multi-agent-caching.md`
line 117) calls this *"the single most underrated optimization in
agentic pipelines."*

### How (the function)

```python
from server.orchestrator.id_canon import canonicalize_turn

# `messages` is the Anthropic Messages-API list[dict] form.
canonical_messages = canonicalize_turn(messages)

# `messages` is NOT mutated; a deep copy is returned.
# Idempotent: applying twice == applying once.
assert canonicalize_turn(canonical_messages) == canonical_messages
```

The reference pseudocode (canonical source):

```python
def canonicalize_turn(messages):
    counter = 0
    id_map = {}
    out = copy.deepcopy(messages)
    for msg in out:
        for block in msg.get("content", []):
            if block.get("type") in ("tool_use", "tool_result"):
                old_id = block.get("id") or block.get("tool_use_id")
                if old_id not in id_map:
                    id_map[old_id] = f"toolu_{counter:08d}"
                    counter += 1
                if "id" in block:
                    block["id"] = id_map[old_id]
                if "tool_use_id" in block:
                    block["tool_use_id"] = id_map[old_id]
    return out
```

### Worked 4-agent fan-out example

Setup: a 3-round retrieval session shared across 4 agents (Lookup,
Synthesis, Verification, Autoformalization). Round 1 is a
`search_papers`; Round 2 is two parallel `get_chunk` calls; Round 3
is another `search_papers`.

**Pre-canonicalization (raw Anthropic IDs):**

| Round | Block kind | Anthropic-issued id |
|---|---|---|
| 1 | `tool_use` (search_papers) | `toolu_01R1A...` |
| 1 | `tool_result` | `toolu_01R1A...` |
| 2 | `tool_use` (get_chunk) | `toolu_02R2A...` |
| 2 | `tool_use` (get_chunk) | `toolu_03R2B...` |
| 2 | `tool_result` | `toolu_02R2A...` |
| 2 | `tool_result` | `toolu_03R2B...` |
| 3 | `tool_use` (search_papers) | `toolu_04R3A...` |
| 3 | `tool_result` | `toolu_04R3A...` |

If we splice this verbatim into Agent 2's prompt context, Agent 2's
prompt cache key is the hash of all eight non-deterministic IDs.
Agent 3 gets a different set of IDs (different request to Anthropic
→ different `toolu_*` strings) and so on. None of the four agents
share a cacheable prefix.

**Post-canonicalization (after `canonicalize_turn`):**

| Round | Block kind | Canonical id |
|---|---|---|
| 1 | `tool_use` (search_papers) | `toolu_00000000` |
| 1 | `tool_result` | `toolu_00000000` |
| 2 | `tool_use` (get_chunk) | `toolu_00000001` |
| 2 | `tool_use` (get_chunk) | `toolu_00000002` |
| 2 | `tool_result` (paired with `00000001`) | `toolu_00000001` |
| 2 | `tool_result` (paired with `00000002`) | `toolu_00000002` |
| 3 | `tool_use` (search_papers) | `toolu_00000003` |
| 3 | `tool_result` | `toolu_00000003` |

Now all four agents see the SAME canonical IDs and their prompt
prefixes match byte-for-byte. The cross-agent prefix is cacheable
and the 4-agent fan-out approaches "near-free" cost (per
`07-multi-agent-caching.md` line 38).

The pairing invariant — `tool_use` and the `tool_result` that
references it MUST share the same id — is preserved because the
canonicalizer maps both occurrences of the same source ID through
the same `id_map[old_id]` entry.

This expected output is pinned in
`tests/test_id_canon.py::TestFourAgentFanoutExample::test_4_agent_3_round_canonicalization_pins_to_known_output`
so a future doc edit that drifts from the worked example fails at
test time.

### When to call

Call `canonicalize_turn` exactly once per agent transition — after
receiving a tool-result block from agent A, before appending it to
the shared context that agent B will see. Within a single agent's
run loop the canonicalization is unnecessary (one agent only sees
its own tool IDs).

> ⚠️ **MUST pass the FULL accumulated history every time** (F1 fix
> from the E08_S04 critique). The canonical-id counter is per-call,
> reset to 0 at the start of every `canonicalize_turn` invocation.
> The brief's "per-session monotonically increasing" wording is
> satisfied IF AND ONLY IF every call sees the full history, so
> the same accumulated list produces the same canonical IDs
> deterministically. The function's idempotency makes this safe:
> re-canonicalizing already-canonical IDs is a no-op.
>
> **❌ WRONG** (introduces ID collisions across transitions):
>
> ```python
> # Transition 1
> ctx = canonicalize_turn([turn_a])  # turn_a.id = "toolu_00000000"
> # Transition 2 — only the new turn:
> ctx_partial = canonicalize_turn([turn_b])  # turn_b.id = "toolu_00000000"
> # COLLISION: turn_b's id collides with turn_a's id.
> ```
>
> **✅ RIGHT** (passes full accumulated history each time):
>
> ```python
> # Transition 1
> ctx = canonicalize_turn(history + [turn_a])
> # Transition 2 — pass the FULL accumulated history:
> ctx = canonicalize_turn(ctx + [turn_b])
> # turn_a's ids are preserved; turn_b's ids are appended to the
> # same counter sequence (toolu_00000001, toolu_00000002, ...).
> ```

### Mutation discipline

The function returns a **deep copy**. The input list is not
mutated. This deviates from the design-note pseudocode (which
mutates in place) — we trade a deep-copy cost for footgun
avoidance per the E08_S04 research synthesis. Idempotency holds:
applying the function twice produces the same output as applying
it once.

## Rule 2 — Hard retrieval caps

### What

The MCP server enforces per-session hard caps on retrieval tools:

- **`search_papers`**: maximum 30 calls per `Mcp-Session-Id`
- **`get_chunk`**: maximum 100 calls per `Mcp-Session-Id`

Both are defaults as of agent-platform-m1 (raised from 3 and 4, which were
sized for a scripted 2-round fan-out and fired on interactive research).
Operators tune them with `ARXMCP_MAX_SEARCH_PAPERS_CALLS` /
`ARXMCP_MAX_GET_CHUNK_CALLS`, so an orchestrator must read the `limit`
field off the error rather than assume a number.

When a cap is reached, the server short-circuits the tool call
and returns a structured `RETRIEVAL_CAP_REACHED` error. The agent
sees the error as a regular tool result it can read and act on
(typically: proceed with the chunks already retrieved or open a
new MCP session).

### Why

Token-budget safety. A runaway retrieval loop in an agent could
trivially consume the entire context window with chunk bodies
before the model produces any output. The caps cap this exposure.

The caps are defensive ceilings, not security boundaries. Stateless
clients (no `Mcp-Session-Id` header) bypass cap enforcement — the
cap is about runaway-loop containment, not abuse prevention.

### Wire format

A cap-rejected `tools/call` returns a normal HTTP 200 with a
JSON-RPC envelope. The `result` is a `CallToolResult` with
`isError: true`:

```json
{
  "jsonrpc": "2.0",
  "id": <echoed from request>,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"code\":\"RETRIEVAL_CAP_REACHED\",...}"
      }
    ],
    "structuredContent": {
      "code": "RETRIEVAL_CAP_REACHED",
      "message": "search_papers cap of 3 call(s) per MCP session reached (attempt #4). Proceed with the chunks already retrieved or open a new session.",
      "tool": "search_papers",
      "limit": 3,
      "session_attempted_count": 4
    },
    "isError": true
  }
}
```

The agent can parse `structuredContent` and react accordingly. The
`text` block carries the same payload for clients that read only
`content[0].text`.

#### Why `result.isError=true` rather than a JSON-RPC error envelope

The MCP 2025-06-18 spec defines two error-signaling shapes for
`tools/call`:

1. **Tool execution error** — the tool ran but produced an error.
   Signaled via `CallToolResult.isError=true` with the error
   detail in the `content` / `structuredContent` payload. The
   agent's tool-handling loop receives this as a regular tool
   result it can read and react to.
2. **JSON-RPC protocol error** — the tool could not be invoked
   at all (e.g., malformed request, unknown method). Signaled via
   the JSON-RPC `{"error": {"code": ..., "message": ...}}`
   envelope. Most SDKs surface this as a thrown exception.

A cap rejection sits on the boundary between these two: the tool
was not invoked (server-level refusal), but the agent absolutely
needs to reason about the rejection (proceed with already-retrieved
chunks, NOT crash). We chose `result.isError=true` because:

- The agent's natural processing path is the tool-result handler,
  not the exception handler. Many agent SDKs surface JSON-RPC
  errors as exceptions that abort the run loop — exactly what we
  do NOT want for a recoverable cap rejection.
- The structured payload (with `code`, `tool`, `limit`,
  `session_attempted_count`) is richer than a JSON-RPC error
  string and easier for the agent to parse programmatically.
- The MCP spec permits `isError=true` for any tool-side error;
  while server-level refusals lean toward the JSON-RPC envelope,
  the spec doesn't strictly forbid the `isError=true` form.

This is a deliberate UX choice (F8 fix from the E08_S04 critique).
A future MCP spec revision that makes the boundary stricter would
warrant revisiting.

### Caps survive cache hits

The cap counts ALL calls to a capped tool — including calls that
hit the 3-tier retrieval cache (`server/cache.py`). The cap bounds
**token exposure**, not compute. A Tier-1 cache hit still emits a
result the agent can re-process, so it counts.

### Caps reset on server restart

The session registry is in-memory. A server restart drops every
session's counters (and every session). Long-running servers also
LRU-evict abandoned sessions at 10K entries.

### When the cap does NOT fire

- The request has no `mcp-session-id` header. The cap layer
  silently passes through. Stateless clients bypass cap
  enforcement; rationale above.
- The request is not a `tools/call` JSON-RPC method. Initialize,
  ping, tools/list, etc. all bypass.
- The tool name is not `search_papers` or `get_chunk`. Other
  tools (`get_definitions`, `find_lemma_by_name`,
  `find_equation`, `get_citations`) bypass.
- The body is malformed or unparseable. The middleware
  forward-compat-fails open; FastMCP will emit its own error.

### Telemetry

Future milestone (E08_S05 or later) will add Prometheus counters
for cap hits. v1 logs cap-rejection at INFO level
(`server.middleware.security` logger) with the truncated
session-id, the tool name, the attempted count, and the limit.

## Cross-references

- `.claude/notes/07-multi-agent-caching.md` — the canonicalization
  rule rationale (lines 87–117)
- `.claude/notes/08-security-observability-ops.md` — the
  per-session rate-limit framing (lines 60–61)
- `.claude/notes/06-mcp-server-design.md` — `Mcp-Session-Id`
  header semantics
- `server/orchestrator/id_canon.py` — Rule 1 implementation
- `server/session.py` — Rule 2 SessionState + registry
- `server/middleware.py::SessionCapMiddleware` — Rule 2 enforcement
- `tests/test_id_canon.py` — Rule 1 acceptance tests
- `tests/test_session_caps.py` — Rule 2 acceptance tests

## Note on test path

The E08_S04 brief specifies the canonicalize_turn test at
`server/orchestrator/test_id_canon.py`. The project's `pyproject.toml`
pins `testpaths = ["tests"]`, so a test file under
`server/orchestrator/` would not be collected by plain `pytest`.

**The full test suite lives at `tests/test_id_canon.py`** to match
project convention; CI's plain `pytest` picks it up there. A
**re-export stub at `server/orchestrator/test_id_canon.py`**
(F3 fix from the E08_S04 critique) re-imports the test classes so
the literal AC ("`pytest server/orchestrator/test_id_canon.py`
passes") is satisfied. Running either path collects and runs the
same tests.
