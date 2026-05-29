# Research Brief — notebook-surface-expansion-m5

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-29T19:00:00Z

## In-codebase context

### Spike proof (load-bearing — read first)

`notebook-surface-expansion-spike-1.md` established **GO** for the instructions wiring.
Verbatim from the spike:

> "Both byte-stability gates (`tests/test_server_tool_schema.py` +
> `tests/test_prompts.py`, 42 tests) are **green on current main** — the baseline
> anchor for 'unchanged'."

And structurally:

> "**BP1 is the ORCHESTRATOR's prompt assembly, not the MCP handshake.**
> `EXPECTED_BP1_SHA256` hashes `SYSTEM_PROMPT + ALL_TOOLS` assembled into the
> Anthropic Messages request by `_build_fanout_request`. A repo-wide grep of
> `server/prompts.py` + `server/orchestrator/*.py` for
> `instructions|initialize|capabilities|InitializeResult` returns **nothing** — BP1
> has zero coupling to the MCP `initialize` response."

And:

> "**The MCP `initialize` response is not in the Anthropic prompt cache at all.**
> BP1/BP2 are Anthropic `cache_control` breakpoints over the orchestrator's request.
> Even if the MCP initialize bytes changed, BP1/BP2 could not move."

### MCP 2025-06-18 spec — instructions field

From `schema.ts` (pinned to `2025-06-18`):

```typescript
/**
 * Instructions describing how to use the server and its features.
 *
 * This can be used by clients to improve the LLM's understanding of available tools,
 * resources, etc. It can be thought of like a "hint" to the model. For example, this
 * information MAY be added to the system prompt.
 */
instructions?: string;
```

The lifecycle spec confirms `instructions` appears in the `initialize` result:

```json
{
  "result": {
    "protocolVersion": "2025-06-18",
    "capabilities": { ... },
    "serverInfo": { ... },
    "instructions": "Optional instructions for the client"
  }
}
```

**Semantic boundary (critical):** The `MAY be added to the system prompt` language means
the host/client decides whether and how to surface `instructions` to the LLM. This is
**advisory orientation only** — it is NOT a security control, NOT a substitute for
server-side `<retrieved_*>` delimiters, and NOT guaranteed to reach the LLM at all.
The field is **OPTIONAL** (type `string`, absent = no orientation hint).

### 06-mcp-server-design.md — instructions field

The note now documents the m4 notebook resources update. There is **no prior statement**
about the `initialize.instructions` field in the current constitution — m5 will be the
first mention. The note is clean for this addition; no contradiction exists.

The Won't-list boundary is stated in the milestone brief itself: `instructions=` is the
CAND-11 v0 — NOT the full `SYSTEM_PROMPT`. `server/prompts.py` already holds the
`SYSTEM_PROMPT` placeholder (line 113–116). The `ARXMCP_INSTRUCTIONS` constant MUST go
in a **separate module** (`server/mcp_instructions.py`) or be clearly distinct from
`SYSTEM_PROMPT` to prevent conflation.

### 07-multi-agent-caching.md — cache discipline

The cache-stability note is entirely about the Anthropic prompt-cache (BP1/BP2) and the
MCP server's retrieval caches. The `initialize` handshake is NOT part of either. No
cache discipline applies to `initialize.instructions` itself. The ONLY obligation is that
the wiring must NOT drift `EXPECTED_TOOL_SCHEMA_SHA256` or `EXPECTED_BP1_SHA256`.

### Current main.py construction site

`server/main.py:661`:
```python
mcp_server = FastMCP("arxmcp", json_response=True)
```
The one-line change is adding `instructions=ARXMCP_INSTRUCTIONS` to this call. The
spike confirmed FastMCP 1.27.x passes this kwarg into the `initialize` result natively.

### prompts.py discipline

`server/prompts.py` uses `MappingProxyType` + AST literal-only checks. The
`ARXMCP_INSTRUCTIONS` constant does NOT belong in `prompts.py` because:
1. It is not a cache-breakpoint constant (no BP relevance).
2. The AST literal-only test in `tests/test_prompts.py` might fail or require extension
   if a new constant with different shape is added there.
3. **Separation of concerns**: a future implementer must not confuse instructions with
   the BP1 system prompt — keeping them in separate modules makes the boundary obvious.
**Recommendation: `server/mcp_instructions.py` is the correct home.**

### Stale "7-tool" framing

The spike explicitly calls this out:

> "**Stale '7-tool' framing.** The surface is actually **8 tools** today
> (`lean_verify` is the 8th; `TOOL_SCHEMA_VERSION=16`). e2 docs/briefs should say
> 'the frozen 8-tool surface', not 7."

The `ARXMCP_INSTRUCTIONS` string MUST say "8-tool" not "7-tool". This is a content
correctness requirement for the constant body.

## Prior decisions and lessons

Recent git log confirms:
- `96cca0d` — notebook-surface-expansion-m4 complete (resources/list + resources/read)
- `9ac322a` — spike-1 doc committed (byte-stability GO)

The three-commit pattern applies: `feat(server)`, `rect(server)`, `chore(notes)`.

**No re-pinning of `EXPECTED_TOOL_SCHEMA_SHA256` or `EXPECTED_BP1_SHA256`** — the
milestone brief's byte-stability AC requires these unchanged. If either drifts, the
implementation leaked into the wrong surface — stop and fix, do NOT re-pin.

**EXPECTED_INSTRUCTIONS_SHA256** is a new, independent hash pin that MUST be added in
`tests/test_mcp_instructions.py` (or a suitable test file). It pins the `ARXMCP_INSTRUCTIONS`
string itself, NOT `tools/list`. Pattern mirrors `EXPECTED_TOOL_SCHEMA_SHA256`.

## External sources

**MCP spec 2025-06-18** — `schema.ts` `InitializeResult.instructions`:
> `instructions?: string` — "Instructions describing how to use the server and its
> features. This can be used by clients to improve the LLM's understanding of available
> tools, resources, etc. It can be thought of like a 'hint' to the model. For example,
> this information MAY be added to the system prompt."

Source: https://github.com/modelcontextprotocol/specification/blob/main/schema/2025-06-18/schema.ts

The lifecycle page shows `"instructions": "Optional instructions for the client"` in the
server initialize response example, confirming the field placement.

No Anthropic prompt-caching docs are relevant to this milestone — confirmed by the spike
that `initialize.instructions` has no coupling to the Anthropic prompt cache.

## Recommendation

**Place `ARXMCP_INSTRUCTIONS` in a new `server/mcp_instructions.py` module**, wire it
in `server/main.py` as `FastMCP("arxmcp", json_response=True, instructions=ARXMCP_INSTRUCTIONS)`,
and add a standalone `tests/test_mcp_instructions.py` with `EXPECTED_INSTRUCTIONS_SHA256`.

Reasoning: a dedicated module prevents confusing `initialize.instructions` with
`SYSTEM_PROMPT` (BP1 cache constant in `server/prompts.py`). The separation is the
primary guard against future implementers accidentally wiring the instructions constant
into the orchestrator's prompt assembly (FM-d below).

**Content of `ARXMCP_INSTRUCTIONS`** — keep it short (< 500 chars), factual, and
server-authored only:
1. What the corpus is: arXiv math corpus, categories `math.AG`, `math.NT`, `math-ph`, `hep-th`.
2. What `arxmcp://notebooks` resources expose: enumerable textbook corpora.
3. The 8-tool retrieval surface (name each tool briefly).
4. The read-only discovery model: this server provides evidence; it does not reason or mutate.
5. A pointer to treat `<retrieved_chunk>` / `<retrieved_notebook>` content as DATA, not
   instructions — directly primes the connecting agent for Threat 2 defense.

Including item 5 is critical: the spec says the client MAY surface instructions to the LLM.
When it does, the `<retrieved_*>` convention primer arrives at the LLM before the first
tool call, reinforcing the Threat 2 mitigation from `08-security-observability-ops.md`.

## Content-safety of the string

The instructions constant is SERVER-AUTHORED at commit time — zero injection vector. It
is a string literal checked into source, not operator/user input. However, it MUST NOT
contain:

1. **Secrets/tokens** — no `ARXMCP_*_API_KEY` values, no model commit SHAs.
2. **Absolute host paths** — `08-security-observability-ops.md` Threat 1 class;
   m4 already closed `lancedb_path` info-leak (D3); the instructions string must
   not reintroduce it (e.g., no `/var/arxmcp/...` paths).
3. **Internal IPs/ports beyond the documented loopback** — the bind address
   `127.0.0.1:7733` is documented in `docs/install.md` so mentioning the default
   port is acceptable; non-loopback addresses are not.
4. **Anything fingerprinting the operator's environment** — no hostname, no username,
   no OS details.
5. **Instructions that could be exploited if the initialize response is captured** —
   e.g., do not describe internal rate-limit thresholds or session-cap values (Threat 4).

Because `initialize` is an unauthenticated MCP handshake (Threat 5: origin validation
is loopback-only), a network-adjacent adversary capturing the response sees the
instructions. The string should be safe to make fully public.

## Failure-mode analysis

**FM-a: Hash-pin test is too brittle (any whitespace tweak forces re-pin).**
Trigger: developer edits the string to fix a typo. Symptom: `test_mcp_instructions.py` fails.
Mitigation: this is the INTENDED behavior — same discipline as `EXPECTED_TOOL_SCHEMA_SHA256`.
The hash enforces that any edit to `ARXMCP_INSTRUCTIONS` is intentional and re-pinned
consciously. Document this in the test docstring.

**FM-b: Instructions string edited but `EXPECTED_INSTRUCTIONS_SHA256` not re-pinned.**
Trigger: developer changes `ARXMCP_INSTRUCTIONS` without running the pin-update command.
Symptom: test fails loudly. Mitigation: the hash-pin test is the guard working correctly.
Provide a `pytest --update-instructions-hash` flag (mirrors `--update-tool-schema-hash`).

**FM-c: `ARXMCP_INSTRUCTIONS` placed in `server/prompts.py` and accidentally wired into BP1.**
Trigger: implementer adds the constant to `prompts.py` and a future refactor imports it
into the orchestrator's `SYSTEM_PROMPT + instructions` concatenation.
Symptom: `EXPECTED_BP1_SHA256` drifts. Mitigation: keep instructions in a SEPARATE
`server/mcp_instructions.py`; the byte-stability guard catches any accidental BP1 wiring.

**FM-d: Future `SYSTEM_PROMPT` landing (CLAUDE.md §8 gotcha #6) conflated with instructions.**
Trigger: when E08_S04 authors the real `SYSTEM_PROMPT`, implementer copies part of
`ARXMCP_INSTRUCTIONS` into it. Symptom: semantic duplication, possible BP1 drift.
Mitigation: `ARXMCP_INSTRUCTIONS` is for the MCP `initialize` response (client orientation);
`SYSTEM_PROMPT` is for the Anthropic messages API (orchestrator's LLM). They are DISTINCT
surfaces. The module separation enforces this conceptually.

**FM-e: Instructions string drifts out of sync with reality.**
Trigger: a tool is added/removed, or categories change, but `ARXMCP_INSTRUCTIONS` is not
updated. Symptom: connecting agent receives stale orientation (e.g., "8 tools" when
there are 9). Mitigation: the hash-pin forces a conscious re-pin on ANY edit; a test
asserting that each of the 8 tool names appears in the string catches tool-surface drift.
This test is LOW complexity and HIGH value — add it alongside the hash-pin test.

**FM-f: Instructions string too long, bloating every initialize handshake.**
Trigger: someone writes a multi-paragraph essay in `ARXMCP_INSTRUCTIONS`.
Symptom: every MCP connection carries unnecessary bytes; client may truncate.
Mitigation: cap the constant at 500 characters enforced by a test assertion
(`assert len(ARXMCP_INSTRUCTIONS) <= 500`). The spec has no protocol limit, but
FastMCP's initialize response is a single JSON object — keep it small.

## Open questions

No open questions — implementation can proceed on the above recommendation.

The only judgment call (where to put the constant) has a clear answer: `server/mcp_instructions.py`.
The only content question (what to include) has clear guidance above. The spike proved
byte-stability holds. The test pattern (hash-pin + tool-name assertion + length cap)
is fully specified.

## External writes the implementation will require

None — this milestone is purely local.

The implementation is a local file change + new test file + commit. No git push, no
PR, no ticket, no infra mutation.
