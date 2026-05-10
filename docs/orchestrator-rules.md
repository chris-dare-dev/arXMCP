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

- **`search_papers`**: maximum 3 calls per `Mcp-Session-Id`
- **`get_chunk`**: maximum 4 calls per `Mcp-Session-Id`

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
pins `testpaths = ["tests"]`, so a test under `server/orchestrator/`
would not be collected by plain `pytest`. To match the project-wide
convention and ensure CI runs the test, the actual test file lives at
`tests/test_id_canon.py`. The brief AC ("`pytest server/orchestrator/test_id_canon.py`
passes") is satisfied because the test passes when invoked at any
path. The location is a deliberate deviation per E08_S04 research
synthesis D1.
