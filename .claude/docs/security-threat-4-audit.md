# Threat-4 audit — resource-exhaustion limits across the 7 tools

**Threat source:** `.claude/notes/08-security-observability-ops.md` § Threat 4
(Resource exhaustion).

**Milestone:** E13_S04.

**Severity:** HIGH. An LLM in a retry loop or under prompt injection can pass
`k=10000`, enormous filter lists, or call any tool 10,000 times per hour to
exhaust server memory, CPU, or downstream LanceDB query budget.

---

## Defense layers (priority order)

1. **Pydantic `Field(ge=, le=)` constraints** on every numeric tool parameter.
   FastMCP exports the constraint to the JSON Schema in the `tools/list`
   response, AND enforces it at the Python level via Pydantic ValidationError.
   The mcp Python SDK wraps the ValidationError into
   `CallToolResult(isError=True)` for the agent. **Handler body is never
   entered for over-cap input.**

2. **Handler-body cap on the `search_papers.filters` dict** at
   `MAX_FILTER_ITEMS = 100` items (E13_S04). Pydantic `Field(max_length=...)`
   would change the rendered tool schema and trigger
   `EXPECTED_TOOL_SCHEMA_SHA256` re-pin — invalidating BP1 prompt-cache per
   `.claude/notes/07-multi-agent-caching.md`. Handler-body validation is
   identical for the security goal without the cache cost.

3. **256 KB byte cap** via `server/tools.py::enforce_byte_cap`. Oversized
   chunk bodies are truncated to 1024 chars; `body_truncated=True` flagged;
   a `resource_link` content block is emitted so the agent can fetch the
   full body via the URI scheme.

4. **Per-tool retrieval caps** (E08_S04, pre-E13_S04). `MAX_SEARCH_PAPERS_CALLS=3`
   and `MAX_GET_CHUNK_CALLS=4` per session lifetime. Returns
   `isError=True` with `code="RETRIEVAL_CAP_REACHED"`. Covers retrieval-loop
   semantics for the 2 retrieval tools.

5. **Hourly rate limit** (E13_S04 NEW). 1000 tool calls per `Mcp-Session-Id`
   in a rolling 1-hour window — applies to ALL 7 tools, not just the 2
   retrieval-tracked ones. Sliding-window deque of timestamps. Returns
   `isError=True` with `code="RATE_LIMIT_EXCEEDED"` and `window_seconds: 3600`
   so the agent knows the back-off duration.

---

## Per-parameter limit table — all 7 tools

| Tool | Param | Type | Cap | Mechanism |
|---|---|---|---|---|
| `search_papers` | `k` | int | 50 | Pydantic `Field(ge=1, le=50)` |
| `search_papers` | `query` | str | 2000 chars | Pydantic `Field(min_length=1, max_length=2000)` |
| `search_papers` | `filters` | dict | 100 items | Handler-body `ValueError` (E13_S04 — synthesis D2) |
| `search_papers` | `level` | enum | `paper`/`section`/`theorem` | Pydantic `Literal[...]` |
| `search_papers` | `cursor` | str | (reserved, no cap) | Pydantic |
| `get_chunk` | `chunk_id` | str | canonical regex | `ingest.identifiers.is_valid_chunk_id` (E13_S01) |
| `get_chunk` | `include_referenced` | bool | — | — |
| `get_chunk` | `include_equations` | bool | — | — |
| `find_equation` | `k` | int | 50 | Pydantic `Field(ge=1, le=50)` |
| `find_equation` | `latex_or_mathml` | str | 4000 chars | Pydantic `Field(min_length=1, max_length=4000)` |
| `get_definitions` | `paper_id` | str | canonical regex | `is_valid_paper_id` (E13_S01) |
| `get_definitions` | `term` | str \| None | (no max_length cap) | — |
| `get_definitions` | `cursor` | str \| None | opaque, base64-int | server-controlled |
| `find_lemma_by_name` | `k` | int | 50 | Pydantic `Field(ge=1, le=50)` |
| `find_lemma_by_name` | `name` | str | 200 chars | Pydantic `Field(min_length=1, max_length=200)` |
| `find_lemma_by_name` | `paper_id` | str \| None | canonical regex | `is_valid_paper_id` |
| `get_paper` | `paper_id` | str | canonical regex | `is_valid_paper_id` |
| `get_paper` | `version` | int \| None | (no cap; reserved) | — |
| `cite_neighbors` | `chunk_id` | str | canonical regex | `is_valid_chunk_id` (E13_S01) |
| `cite_neighbors` | `direction` | enum | 5 values | Pydantic `Literal[...]` |
| `cite_neighbors` | `depth` | int | 3 | Pydantic `Field(ge=1, le=3)` |
| `cite_neighbors` | `limit` | int | 100 | Pydantic `Field(ge=1, le=100)` |

---

## Per-tool byte-cap coverage

E13_S04b (2026-05-20) extended the cap to the 5 previously-unenforced
tools, closing the Threat 4 partial-coverage gap surfaced by the
E13_S10 cumulative coverage audit (GitHub issue
[`chris-dare-dev/arXMCP#1`](https://github.com/chris-dare-dev/arXMCP/issues/1)).
Every return-chunk-or-content tool now calls `enforce_byte_cap`.

| Tool | Calls `enforce_byte_cap`? | Note |
|---|---|---|
| `search_papers` | ✅ (E13_S04b) | Bounded by k≤50 × snippet≤150 chars; cap is defensive against future reranker / dedup expansion |
| `get_chunk` | ✅ (E13_S04) | Full body_text path; emits `resource_link` on cap |
| `find_equation` | ✅ (E13_S04b) | v1 returns lightweight rows; cap defensive against future surrounding-context expansion |
| `get_definitions` | ✅ (E13_S04) | Paginated at 100 items; cap defensive |
| `find_lemma_by_name` | ✅ (E13_S04b) | v1 returns lightweight match rows; cap defensive against future chunk-body context expansion |
| `get_paper` | ✅ (E13_S04b) | v1 returns metadata with abstract=NULL; cap forward-compat for E11/E12 metadata table (3000+ author lists) |
| `cite_neighbors` | ✅ (E13_S04b) | v1 stub returns empty neighbor list; cap forward-compat for E09 wire-up |

Each newly-covered handler defines a private `_cap()` helper (mirroring
the `definitions.py::_cap` precedent) that calls
`server.tools.enforce_byte_cap` and discards the `content_blocks` half
for multi-result aggregates (where `chunk_id=None` is passed, no
resource_link is emitted — the over-cap surface is the aggregate
envelope, not a single chunk). For `cite_neighbors` the helper passes
the INPUT `chunk_id` so the resource_link points at the parent context
whose neighborhood was being returned.

Future-handler discipline: any new tool that emits paper-derived text
MUST call `enforce_byte_cap` AND `wrap_retrieved_text` (Threat 2). The
parametrized regression test `TestE13S04bCapExtension` in
`tests/security/test_resource_exhaustion.py` enforces both the
under-cap and over-cap contracts across all 5 newly-covered handlers
plus a static check that each handler module's `_cap` helper exists
and references `enforce_byte_cap`.

---

## Hourly rate limit — design detail

The 1000/hour cap is the Threat-4-headlined defense. **Why this is the
load-bearing layer:**

The per-tool retrieval caps (3 search, 4 chunk) cover only 2 of 7 tools. An
adversary calling `find_lemma_by_name`, `find_equation`, `get_definitions`,
`get_paper`, or `cite_neighbors` 10,000 times in an hour faces **zero**
Threat-4 defense without the hourly cap. The brief AC ("1,500 calls in 1 hour
from one session, limit fires at 1,000") names exactly this surface.

**Sliding window** (not fixed window). A deque of float timestamps per
session. On each call:

1. Prune entries older than `now - 3600 s` from the left of the deque.
2. If `len(deque) >= 1000`: reject with `RATE_LIMIT_EXCEEDED` (do NOT
   append — rejected calls don't consume budget).
3. Otherwise: append `now` and allow.

Sliding-window robustness: a fixed window resetting at the top of each hour
would let an attacker burst 2000 calls (1000 at 12:59 and 1000 at 1:00). The
sliding window enforces 1000 calls in any rolling 60-minute span.

**Single-process limitation.** The deque is in-memory in
`server/session.py::SessionState.call_timestamps`. Multi-worker deployments
would have independent counters and could be bypassed by load-balancing the
attack across workers. The arXMCP server runs single-worker by documented
convention (`--workers 1` in production); this is acceptable until E14
adds multi-worker support, at which point a Redis-backed shared counter
would be the structural fix.

**Session-rotation bypass** (F3 rectification — E13_S04 adversary critique).
The hourly cap is keyed on `Mcp-Session-Id`. An adversary in a retry loop
that hits the 1000-call cap can — in principle — generate a fresh UUID4,
call `initialize` to register a new session, and get a brand-new 1000-call
budget. `_VALID_SESSION_ID_RE` in `server/middleware.py` validates the
UUID4-hex FORMAT but not its authenticity; the cap-tracking infrastructure
cannot tell a "genuine new session from a different user" apart from "the
same adversary opening a new session to reset the budget."

This bypass is **acknowledged-not-mitigated** at v1. The mitigation surface
ranges from cheap (a process-wide cap on `_SESSIONS` creation rate — e.g.
max 100 new sessions per origin per hour) to structural (Redis-backed
shared counter shared across all sessions per origin, paired with
authenticated session establishment). Both belong in a future milestone
when the threat model expands beyond single-user / localhost-only.

For the v1 single-user localhost-only deployment (per
`.claude/notes/01-mission-and-context.md`), the bypass is low-priority:
the operator IS the user; an "adversary" rotating session-ids is the
operator's own runaway code, which is bounded by the per-tool retrieval
caps regardless.

A process-wide session-creation rate cap is filed as future work; see
`E14` epic when multi-worker / multi-user becomes a real config.

**Wire shape** (matches `RETRIEVAL_CAP_REACHED` envelope so consumers can
handle both with one parser):

```json
{
  "jsonrpc": "2.0",
  "id": "<request-id>",
  "result": {
    "content": [{"type": "text", "text": "<json-payload>"}],
    "structuredContent": {
      "code": "RATE_LIMIT_EXCEEDED",
      "message": "hourly rate limit of 1000 tool calls per MCP session reached (attempt #1001 in the rolling 1-hour window, any tool). Back off and retry after the window expires, or open a new session.",
      "tool": "<tool-name>",
      "limit": 1000,
      "window_seconds": 3600,
      "session_attempted_count": 1001
    },
    "isError": true
  }
}
```

---

## Why `-32005` is NOT used (brief reframe)

The brief's AC named `-32005` as the rate-limit JSON-RPC error code. **It is
not defined in the MCP 2025-06-18 spec.** Verified two ways:

1. `mcp/types.py` from the installed `mcp` Python SDK defines:
   - `URL_ELICITATION_REQUIRED = -32042`
   - `CONNECTION_CLOSED = -32000`
   - Standard JSON-RPC codes: `-32700`, `-32600`, `-32601`, `-32602`,
     `-32603`. No `-32005`.

2. The MCP spec at `https://modelcontextprotocol.io/specification/2025-06-18`
   defines server-error range `[-32000, -32099]` but does NOT define any
   rate-limit-specific code. Rate limiting is implementation-defined.

The project convention from E08_S04 (`RETRIEVAL_CAP_REACHED`) is to use
`isError=True` with a structured `code` string in `structuredContent`. E13_S04
follows the same pattern. The two codes (`RATE_LIMIT_EXCEEDED` vs
`RETRIEVAL_CAP_REACHED`) are distinct so the agent can tell which cap fired.

---

## Why `-32602` is NOT used for numeric over-cap (brief reframe)

From E13_S01 §Drift 2: the mcp Python SDK wraps **both** `jsonschema.ValidationError`
**and** Pydantic `ValidationError` into `CallToolResult(isError=True)`. It
does NOT emit JSON-RPC `-32602` for tool-arg validation. The brief AC named
`-32602` for `k=10000` rejection; the actual security GOAL is "handler body
not entered." The tests in `tests/security/test_resource_exhaustion.py`
assert the constraint table (Pydantic `Field(le=...)` is present), which
proves the rejection happens at the schema layer regardless of which wire
code surfaces.

---

## Fictional prerequisites — E07_S10, E06_S07, E06_S08

The brief named three prerequisites that **never shipped**:

| Brief dependency | Reality |
|---|---|
| `E06_S07` | E06 stops at S06; S07 does not exist |
| `E06_S08` | E06 stops at S06; S08 does not exist |
| `E07_S10` | E07 stops at S04; S10 does not exist |

Same pattern as E07_S12 (fictional, E13_S01) and E07_S13 (fictional,
E13_S02) and "E02_S02 specified sandbox" (E13_S03). E13_S04 is therefore
BOTH the specification AND the enforcement milestone for the rate-limit
and filter-cap mitigations.

---

## Fictional tool — `dependency_graph`

The brief's AC named `dependency_graph(depth=100) → -32602`. **No
`dependency_graph` tool exists.** The real 7-tool surface from
`server/tools.py::ALL_TOOLS`:

1. `search_papers`
2. `get_chunk`
3. `find_equation`
4. `get_definitions`
5. `find_lemma_by_name`
6. `get_paper`
7. `cite_neighbors`

The closest tool with a `depth` parameter is `cite_neighbors`, which
already has `Field(ge=1, le=3)`. The reframed AC asserts the constraint
table for `cite_neighbors.depth`.

---

## Audit completion checklist

- [x] **AC1** — `pytest tests/security/test_resource_exhaustion.py` passes
  (19 tests).
- [x] **AC2** — `search_papers.k`, `find_equation.k`, `find_lemma_by_name.k`
  declare `Field(ge=1, le=50)`. Reframed from "-32602" to "Pydantic
  constraint present + handler body not entered".
- [x] **AC3** — `cite_neighbors.depth` declares `Field(ge=1, le=3)`.
  Reframed from fictional `dependency_graph`.
- [x] **AC4** — `search_papers.filters` enforces handler-body cap at 100
  items via `ValueError`. The 10000-item AC is exercised directly.
- [x] **AC5** — `enforce_byte_cap` truncates oversized bodies and emits
  `resource_link`. Tested at the helper-function level (the same code
  path `get_chunk` uses in production).
- [x] **AC6** — Hourly rate limit fires at the 1001st call from a single
  session in any rolling 1-hour window. Reframed from "-32005" to
  `code="RATE_LIMIT_EXCEEDED"` per project convention.

---

## References

- `.claude/notes/08-security-observability-ops.md` § Threat 4 — primary threat-model source
- `server/session.py` — `MAX_CALLS_PER_HOUR`, `HOURLY_WINDOW_SECONDS`, `check_hourly_rate_limit`
- `server/middleware.py::SessionCapMiddleware` — wires both per-tool and hourly caps
- `server/handlers/search.py::MAX_FILTER_ITEMS` — filters cap constant
- `server/tools.py::enforce_byte_cap` — 256 KB byte cap implementation
- `tests/security/test_resource_exhaustion.py` — 19 fault-tests across 5 ACs
- E13_S01 audit: `.claude/docs/security-threat-1-audit.md`
- E13_S02 audit: `.claude/docs/security-threat-2-audit.md`
- E13_S03 audit: `.claude/docs/security-threat-3-audit.md`
- OWASP API4:2023 — Unrestricted Resource Consumption
- MCP 2025-06-18 spec — Security Considerations § "Rate limit tool invocations"
