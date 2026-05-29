# Research Synthesis — notebook-surface-expansion-m5

**Milestone:** A static MCP `initialize.instructions` string orients a connecting
agent (CAND-11 v0). (Epic e2, piece 2/2 — completes e2.)
**Mode:** standard (2× Sonnet). Both `ok`, 0 open questions, 0 external writes — the
briefs are unanimous (spike-1 + m4 did the groundwork).
**Implementation path:** INLINE (new `server/mcp_instructions.py` + a one-line
`main.py` wiring + a new test file + a 06-doc note; tiny, < 150 LOC).

---

## Load-bearing decisions (both briefs agree)

### D1 — `ARXMCP_INSTRUCTIONS` lives in a NEW `server/mcp_instructions.py`, NOT `prompts.py`

Both researchers strongly recommend a dedicated module. `server/prompts.py` is the BP1
source (`SYSTEM_PROMPT + ROLE_PREFIXES`); putting the instructions constant there is a
maintenance hazard (a future contributor maintaining BP1 discipline would wonder if it
participates in the cache hash — it would not, but the confusion invites FM-c: someone
wires it into the orchestrator's `SYSTEM_PROMPT + instructions` concat and drifts
`EXPECTED_BP1_SHA256`). A separate module makes the boundary unambiguous: **the MCP
`initialize.instructions` field (client orientation) is DISTINCT from `SYSTEM_PROMPT`
(the orchestrator's Anthropic-API prefix)** — different surfaces, proven orthogonal by
spike-1.

### D2 — One-line wiring at the FastMCP construction site (`server/main.py:661`)

`FastMCP("arxmcp", json_response=True)` → `FastMCP("arxmcp", json_response=True,
instructions=ARXMCP_INSTRUCTIONS)`. `instructions` is a native FastMCP 1.27.x `__init__`
kwarg (verified live in spike-1 + brief-1). No other wiring; `instructions` flows into
the `initialize` result natively.

### D3 — MCP spec: `instructions` is an OPTIONAL advisory hint (NOT a security control)

MCP 2025-06-18 `schema.ts` `InitializeResult.instructions?: string` — *"Instructions
describing how to use the server and its features … can be used by clients to improve
the LLM's understanding … thought of like a 'hint' to the model. For example, this
information MAY be added to the system prompt."* So the host MAY surface it to the LLM —
it is advisory orientation, NOT a substitute for the server-side `<retrieved_*>`
delimiters. Because the string MAY reach the LLM, it SHOULD prime the agent on the
`<retrieved_*>`-is-DATA convention (reinforces Threat 2).

### D4 — The constant content (server-authored, content-safe, ASCII)

Factual orientation only: corpus + categories (math.AG/math.NT/math-ph/hep-th); the
`arxmcp://notebooks` + `arxmcp://notebooks/<slug>` resources for discovery; the **eight**
retrieval tools by name (search_papers, get_chunk, find_equation, get_definitions,
find_lemma_by_name, get_paper, cite_neighbors, lean_verify — "8-tool", NOT the stale "7");
read-only/evidence-only model; the `<retrieved_*>`-is-DATA primer. **MUST NOT contain**
(content-safety, brief-2 + `08-security-observability-ops.md`): secrets/tokens, absolute
host paths (the m4 D3 info-leak class), non-loopback IPs, or env fingerprints — the
`initialize` handshake is unauthenticated, so treat the string as public. NOT the full
`SYSTEM_PROMPT` (Won't list).

### D5 — Tests (`tests/test_mcp_instructions.py`, new) — hash-pin + 3 guards

1. **Hash-pin:** `EXPECTED_INSTRUCTIONS_SHA256` (UPDATE-ANCHOR comment) ==
   `sha256(ARXMCP_INSTRUCTIONS.encode("utf-8")).hexdigest()`; intentional-drift discipline
   (mirrors `EXPECTED_TOOL_SCHEMA_SHA256`; on failure, edit the literal to the printed
   value). No auto-update flag (KISS — a single hash, unlike the regenerated tool schema).
2. **Wiring:** a live `FastMCP("arxmcp", json_response=True, instructions=ARXMCP_INSTRUCTIONS)`
   has `.instructions == ARXMCP_INSTRUCTIONS` (proves the kwarg threads through).
3. **Byte-stability guard:** two-server `tools/list` hash comparison (base vs
   instructions-set) both == `EXPECTED_TOOL_SCHEMA_SHA256` (reuse the m4 helper). NO re-pin.
4. **Drift guards (brief-2 FM-e/FM-f):** assert all 8 tool names appear in the string
   (catches tool-surface drift); assert `len(ARXMCP_INSTRUCTIONS) <= 800` (anti-bloat).

### D6 — Document in `06-mcp-server-design.md` (additive, consistent with m3/m4)

Add a short note (near the Resource surface / spec-compliance area) that the server sets
a static `initialize.instructions` orienting connecting agents (the CAND-11 v0; not the
SYSTEM_PROMPT). Keeps the constitution accurate per the m3-established discipline.

---

## Implementation checklist

1. **`server/mcp_instructions.py`** (new) — `ARXMCP_INSTRUCTIONS: str` constant (D4),
   module docstring noting it is the MCP `initialize.instructions` hint, DISTINCT from
   `SYSTEM_PROMPT`, and must stay content-safe.
2. **`server/main.py`** — add `instructions=ARXMCP_INSTRUCTIONS` to the `FastMCP(...)`
   call + the import.
3. **`tests/test_mcp_instructions.py`** (new) — the 4 tests in D5.
4. **`.claude/notes/06-mcp-server-design.md`** — the additive note (D6).

## Byte-stability / scope (the load-bearing AC)

No `server/tools.py`, `ALL_TOOLS`, `EXPECTED_TOOL_SCHEMA_SHA256`, `server/prompts.py`,
`SYSTEM_PROMPT`, or `EXPECTED_BP1_SHA256` change. No `TOOL_SCHEMA_VERSION` bump.
`instructions` is orthogonal to both pinned hashes (spike-1, structural + empirical). If
either drifts, the constant leaked into the wrong surface — STOP and fix, never re-pin.

## Open questions

None. (The only "fill-in" is the EXPECTED_INSTRUCTIONS_SHA256 value, computed
mechanically after writing the constant.)

## External writes required

**None.** Purely local. (Push at milestone end is per-event authorized.)
