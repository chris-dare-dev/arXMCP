# Implementation Summary — notebook-surface-expansion-m5

**One-liner:** The MCP server now sets a static `initialize.instructions` hint
(`ARXMCP_INSTRUCTIONS`) orienting a connecting pipeline agent — the corpus, the
`arxmcp://notebooks` discovery resources, the 8 read-only tools, and the
`<retrieved_*>`-is-DATA primer — with the frozen tool-schema/BP1 hashes byte-identical.
(Epic e2, piece 2/2 — **completes e2**.)

**Commit range:** `<base>..<head>` (filled at finalize).
**Implementation path:** inline — 1 new constant module + a one-line `main.py` wiring +
a new test file + a 06-doc note (~4 files, < 150 LOC).

---

## What landed

### `server/mcp_instructions.py` (new)
- `ARXMCP_INSTRUCTIONS: str` — a 720-char, ASCII, content-safe orientation hint:
  research-math corpus + categories (math.AG/math.NT/math-ph/hep-th); the
  `arxmcp://notebooks` + `arxmcp://notebooks/<slug>` discovery resources; the eight
  retrieval tools by name; read-only/evidence-only model; the `<retrieved_*>`-is-DATA
  Threat-2 primer. Module docstring states it is the MCP `initialize.instructions` hint,
  DISTINCT from `SYSTEM_PROMPT`/BP1, and lays out the content-safety contract (no
  secrets / host paths / non-loopback addrs — the handshake is unauthenticated).

### `server/main.py`
- One-line wiring: `FastMCP("arxmcp", json_response=True, instructions=ARXMCP_INSTRUCTIONS)`
  (+ the import). No other change.

### `tests/test_mcp_instructions.py` (new, 8 tests)
- Hash-pin (`EXPECTED_INSTRUCTIONS_SHA256` + UPDATE-ANCHOR, intentional-drift discipline);
  all-8-tool-names-present (catches tool-surface drift); length ≤ 800 (anti-bloat);
  content-safety (no host paths / `0.0.0.0` / secret markers); `!= SYSTEM_PROMPT`;
  wiring (live `FastMCP(...).instructions == ARXMCP_INSTRUCTIONS`); and the byte-stability
  guard (two-server `tools/list` hash == `EXPECTED_TOOL_SCHEMA_SHA256`, no re-pin).

### `.claude/notes/06-mcp-server-design.md`
- Additive note documenting the `initialize.instructions` hint + its distinction from
  `SYSTEM_PROMPT` + the byte-stability/content-safety posture (consistent with m3/m4).

---

## Acceptance criteria status

- [x] **AC1** — the MCP `initialize` response's `instructions` field is the static
  `ARXMCP_INSTRUCTIONS` string (the kwarg threads natively to `mcp_server.instructions`;
  proven by `test_instructions_threaded_into_fastmcp`).
- [x] **AC2** — the constant + one-line wiring + a hash-pin test
  (`EXPECTED_INSTRUCTIONS_SHA256`, intentional-drift discipline mirroring
  `EXPECTED_TOOL_SCHEMA_SHA256`).
- [x] **AC3** — byte-stability guard: `EXPECTED_TOOL_SCHEMA_SHA256` unchanged (two-server
  comparison) and `EXPECTED_BP1_SHA256` green (`test_prompts.py`), no re-pin, no
  `TOOL_SCHEMA_VERSION` bump.

## Deviations from the brief

None material. The constant lives in a NEW `server/mcp_instructions.py` (the brief
offered "`server/prompts.py` or a new module"); both researchers + the synthesis chose
the dedicated module to keep it far from the BP1 surface (avoids the FM-c BP1-drift
hazard). Added two value tests beyond the AC (tool-name coverage + length cap) per
research FM-e/FM-f.

## Test surface

New: `tests/test_mcp_instructions.py` (8). Changed: `server/mcp_instructions.py` (new),
`server/main.py`, `.claude/notes/06-mcp-server-design.md`. ruff clean. Pinned-hash gates
(`test_server_tool_schema.py`, `test_prompts.py`) + `test_server_startup.py` +
`test_mcp_resources.py` all green.

**Pre-existing failure (NOT m5):** `test_tools_all.py::test_cite_neighbors_wired` fails on
a stale `var/arxmcp/index/kuzu` directory (2026-05-20); the m5 diff touches no
graph/citations code.

## Byte-stability / scope

No `server/tools.py`, `ALL_TOOLS`, `EXPECTED_TOOL_SCHEMA_SHA256`, `server/prompts.py`,
`SYSTEM_PROMPT`, or `EXPECTED_BP1_SHA256` change. `instructions` is the server→client
handshake field, orthogonal to both pinned hashes (spike-1).

## External writes required

**None.** Purely local.
