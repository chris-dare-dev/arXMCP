# E08_S04 — Adversary critique

Commit range under review: `a08a7c0..12423ad` (the single E08_S04 implementation commit).

## Executive summary

- **Verdict: REWORK.** Two correctness/spec issues require attention before this merges; the rest is clean-up.
- **Per-call vs per-session counter (F1, HIGH).** Both the brief AND the project's design note (`07-multi-agent-caching.md` line 99–113) describe a counter "reset to 0 at session start" / "per-session monotonically increasing." The code resets the counter on EVERY `canonicalize_turn(...)` call. If the orchestrator calls `canonicalize_turn` once per agent transition (the documented "When to call" pattern), two transitions on the SAME multi-agent session emit IDs starting from `00000000` each time — the cross-agent prefix that Rule 1 was designed to protect still diverges if rounds-of-tool-calls grow between transitions, because the longest-common-prefix is no longer all canonicalized.
- **Trivial cap bypass via spoofed session-id (F2, HIGH).** `SessionCapMiddleware` calls `get_or_create_session(any-string)` for whatever `mcp-session-id` header the request supplies. There is NO validation that the session-id corresponds to one the server actually issued (FastMCP's `StreamableHTTPSessionManager` issues 32+hex via `uuid4().hex`). A client that rotates a fresh fake session-id on each request defeats both caps unconditionally. Reproduced live: 5 spoofed session-ids → 5 fresh `SessionState` entries.
- **Test path AC literally unsatisfied (F3, MEDIUM).** Brief AC reads `pytest server/orchestrator/test_id_canon.py passes`. The implementation places the file at `tests/test_id_canon.py`. The doc rationalizes the deviation, but the literal AC is false; future re-validation against the brief will flag it.
- **Block with both `id` and `tool_use_id` silently loses one mapping (F4, MEDIUM).** `block.get("id") or block.get("tool_use_id")` short-circuits — when both are present (atypical but not impossible in malformed input), only `id` is mapped and the unrelated `tool_use_id` is rewritten to that same canonical ID, destroying the original pairing without warning.
- **The local import in `SessionCapMiddleware.__call__` claims "cyclic-safe" but no cycle exists (F5, LOW).** `server/session.py` imports nothing from `server/middleware.py`. The local import is dead-weight latency on every cap-relevant request.
- **Untested LRU eviction path (F6, MEDIUM).** `MAX_REGISTRY_SIZE = 10_000` is asserted by code only; no test exercises the 10K-eviction path. Combined with F2 (spoofable session-ids), an attacker can churn 10K+ entries to evict legitimate sessions' counters — a slow cap-bypass.
- **Empty rectification footer placeholder for the rectifier.**

## Severity calibration

| Severity | Definition | Count |
|---|---|---|
| CRITICAL | Data loss / security breach / broken invariant on critical path | 0 |
| HIGH | Wrong behavior on common path; primary defense bypassable; spec MUST violated | 2 |
| MEDIUM | Subtle correctness gap, missing test surface, deviation from brief that is documented but not closed | 5 |
| LOW | Style / minor cleanup / inert dead code | 4 |

## Findings

### F1 — `canonicalize_turn` counter is per-call, brief says per-session

**Severity:** HIGH

**File:line:** `server/orchestrator/id_canon.py:161` (`counter = 0` reset inside the function body)

**What:** The brief states the counter is "a per-session monotonically increasing integer, reset to 0 at session start." The implementation resets on EVERY function invocation:

```python
def canonicalize_turn(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    canonicalized = copy.deepcopy(messages)
    counter = 0           # ← per-call, NOT per-session
    id_map: dict[str, str] = {}
    ...
```

The doc at `docs/orchestrator-rules.md:23` even acknowledges: *"per-call monotonically increasing integer reset to 0 at the start of every `canonicalize_turn` invocation"* — explicitly contradicting the brief.

**Why:** The "When to call" guidance (`docs/orchestrator-rules.md:135`) tells the orchestrator to call `canonicalize_turn` "exactly once per agent transition — after receiving a tool-result block from agent A, before appending it to the shared context that agent B will see." If transition #1 normalizes `[turn_A_tool_use_1]` to `toolu_00000000`, and transition #2 normalizes the same single new tool call from agent B to `toolu_00000000` again, fine — but if transition #2 is called over the WHOLE accumulated turn list (which is the safe pattern, since the function is documented as idempotent), it works. If, however, the orchestrator calls `canonicalize_turn` over JUST the new turn each time (a reasonable interpretation of "per agent transition"), the IDs collide across transitions and the pairing invariant breaks for every cross-transition reference.

The brief's wording avoids that footgun by mandating session-scoped counter state. The current API has no way to thread session state through `canonicalize_turn`; callers must always pass the entire history. That's an implicit precondition the docstring does NOT call out.

**Fix:** Either (a) accept an optional `session_state` argument carrying the `id_map` and `counter` so the orchestrator can normalize incrementally and IDs are stable across transitions, OR (b) add a prominent "MUST be called over the WHOLE accumulated message history each time" note to the docstring AND `docs/orchestrator-rules.md::When to call`, AND add a regression test that simulates two-transition orchestration and asserts ID stability across them.

### F2 — Trivial cap bypass via spoofed `mcp-session-id`

**Severity:** HIGH

**File:line:** `server/middleware.py:774-784` (header read), `server/session.py:121-149` (`get_or_create_session` accepts any string)

**What:** The brief asserts: *"The caps are enforced server-side — the client cannot override them."* The implementation:

```python
session_id_b = _get_header(headers, b"mcp-session-id")
if session_id_b is None:
    await self.app(scope, receive, send)
    return
try:
    session_id = session_id_b.decode("ascii")
except UnicodeDecodeError:
    ...
state = await get_or_create_session(session_id)
```

There is NO validation that the session-id is one the server has actually issued. Any string the client sends becomes a fresh `SessionState`. A client that rotates a new random session-id on each request bypasses BOTH caps unconditionally.

Live reproducer:

```python
# 5 requests, 5 spoofed session-ids
for i in range(5):
    sid = f"attacker-spoof-{i}"
    # ... POST /mcp with mcp-session-id: <sid>, search_papers
# Result: get_session_count() == 5; every request passed through.
```

**Why:** This contradicts the brief explicitly. It also contradicts `docs/orchestrator-rules.md:171-173`: *"Stateless clients ... bypass cap enforcement — the cap is about runaway-loop containment, not abuse prevention."* This is incorrect framing — a stateful client that rotates session-ids is NOT a stateless client. The genuine stateless client (no header at all) bypasses too.

The MCP `StreamableHTTPSessionManager` issues `uuid4().hex` (32 hex chars) and tracks issued ids. The SessionCapMiddleware should consult that registry (or at minimum require the session-id match the spec's required format AND have been seen on a previous `initialize`).

**Fix:** Either (a) verify the session-id has been issued by the FastMCP `StreamableHTTPSessionManager` (preferred — single source of truth), OR (b) reject session-ids that don't match the MCP spec's `^[0-9a-f]{32,}$` format AND track first-seen-via-initialize set so re-using a header without prior init fails. Without this, the brief's "client cannot override" statement is false.

### F3 — Test path AC literally unsatisfied

**Severity:** MEDIUM

**File:line:** `tests/test_id_canon.py` (file lives here), brief AC says `server/orchestrator/test_id_canon.py`

**What:** The brief lists as AC: *"`pytest server/orchestrator/test_id_canon.py` passes"*. Running that command literally:

```
$ pytest server/orchestrator/test_id_canon.py
ERROR: file or directory not found
```

The doc note in `docs/orchestrator-rules.md:255-265` documents the deviation, claiming the AC is satisfied because "the test passes when invoked at any path — the location is incidental." But the AC text is unambiguous about path.

**Why:** A future re-audit against the brief will flag this. The pyproject `testpaths = ["tests"]` constraint is real — but a one-line stub at `server/orchestrator/test_id_canon.py` that re-exports the test classes (e.g. `from tests.test_id_canon import *`) would satisfy the literal AC without breaking the project convention.

**Fix:** Add `server/orchestrator/test_id_canon.py` containing `from tests.test_id_canon import *  # noqa: F401, F403` so `pytest server/orchestrator/test_id_canon.py` collects and runs the same test classes. Update `docs/orchestrator-rules.md:255-265` to note the stub.

### F4 — Block with both `id` and `tool_use_id` silently loses a mapping

**Severity:** MEDIUM

**File:line:** `server/orchestrator/id_canon.py:180-197`

**What:** The block ID extraction is `old_id = block.get("id") or block.get("tool_use_id")`. If a block carries BOTH fields (atypical malformed input), only `id`'s value is mapped. Then both `id` AND `tool_use_id` are rewritten to the SAME canonical ID corresponding to `id`'s original value. The original `tool_use_id`'s mapping is never created — if a later `tool_result` references that `tool_use_id` value, it gets a NEW canonical ID, breaking the pairing.

Live reproducer:

```python
messages = [
    {'role': 'assistant', 'content': [
        {'type': 'tool_use', 'id': 'toolu_id_A', 'tool_use_id': 'toolu_tu_B', 'name': 'x', 'input': {}}
    ]},
]
out = canonicalize_turn(messages)
# out[0]['content'][0] == {'type': 'tool_use', 'id': 'toolu_00000000',
#                          'tool_use_id': 'toolu_00000000', ...}
# 'toolu_tu_B' is silently lost — no id_map['toolu_tu_B'] entry.
```

**Why:** The docstring claims "a block won't have both" — that's optimistic. Defensive code should handle the case explicitly OR raise. Silent corruption of the pairing invariant is the worst failure mode.

**Fix:** Either (a) iterate over both fields and map each independently; OR (b) raise `ValueError` if both fields are present AND differ; OR (c) add an explicit assertion + log warning when both are present. At minimum, document the resolution discipline in the docstring.

### F5 — Local import claim "cyclic-safe" is incorrect; cycle does not exist

**Severity:** LOW

**File:line:** `server/middleware.py:820`

**What:** The middleware does `from server.session import (...)` inside `__call__` with the comment `# local import: cyclic-safe`. But `server/session.py` imports only stdlib modules (`asyncio`, `logging`, `time`, `collections`, `dataclasses`, `typing`). There is no cycle to break.

**Why:** Local imports cost a dict lookup per call. On the cap-relevant fast-path, this is invoked once per `tools/call`. Trivial perf cost; more importantly, the comment is misleading and a future reader will be confused.

**Fix:** Hoist the import to the top of `server/middleware.py` and remove the misleading comment.

### F6 — LRU eviction path is asserted by code only, not tested

**Severity:** MEDIUM

**File:line:** `server/session.py:139-145`

**What:** `MAX_REGISTRY_SIZE = 10_000` triggers `popitem(last=False)` once the registry is full. There is no test that exercises this path — `tests/test_session_caps.py` allocates at most ~10 sessions across all tests. A regression that breaks the eviction (e.g. swapping to a regular `dict` so `popitem(last=False)` raises) would NOT be caught.

Combined with F2 (spoofable session-ids), an attacker can churn 10K+ session-ids to evict the legitimate session's counter, producing a slow cap-bypass even if F2's primary bypass were closed.

**Why:** The cap is a defensive ceiling. A defensive ceiling that hasn't been tested isn't a ceiling.

**Fix:** Add a test that monkeypatches `MAX_REGISTRY_SIZE` to a small value (e.g. 4), creates 5 sessions, and verifies the LRU-oldest entry is evicted. Use `monkeypatch.setattr(server.session, "MAX_REGISTRY_SIZE", 4)`.

### F7 — `RETRIEVAL_CAP_REACHED` envelope is short-circuited before `OriginValidation` for `/mcp` paths — actually, it isn't, but worth asserting

**Severity:** MEDIUM

**File:line:** `server/main.py:378-398`

**What:** The middleware mount order in `create_app` adds in LIFO request order. After the dust settles, the request flow is:

```
SecurityHeaders → OriginValidation → HostValidation → RequestBodySizeLimit → SessionCap → BodySizeCap → handler
```

This is correct: `SessionCap` is INSIDE `RequestBodySizeLimit`, so a 100MB malicious request is 413-rejected BEFORE `SessionCap` buffers it. But the only test that asserts the order is implicit (`tests/test_security.py` exercises the security middlewares, but not the new `SessionCap` integration). A future refactor that reorders `add_middleware` calls (e.g. moving `RequestBodySizeLimit` after `SessionCap`) would silently turn `SessionCap` into a memory-DoS surface.

**Why:** The mount-order brittleness is a recurring failure mode in this project (see E06_S05 F1 from earlier critique). Defensive testing of the order is cheap.

**Fix:** Add a test in `tests/test_main.py` (or a new `tests/test_middleware_order.py`) that constructs `create_app()`, walks `app.user_middleware`, and asserts the expected order. Bonus: assert `SessionCapMiddleware` is INSIDE `RequestBodySizeLimitMiddleware`.

### F8 — `RETRIEVAL_CAP_REACHED` message wire shape is not reviewed against MCP spec

**Severity:** MEDIUM

**File:line:** `server/middleware.py:861-892`

**What:** The cap-rejection wire shape is:

```json
{
  "jsonrpc": "2.0",
  "id": <echoed>,
  "result": {
    "content": [{"type": "text", "text": "<json blob>"}],
    "structuredContent": {...},
    "isError": true
  }
}
```

This uses the `result.isError=true` shape (not a JSON-RPC `error` envelope). Per MCP 2025-06-18 `tools/call`, `CallToolResult.isError=true` is the documented way to signal a TOOL execution error to the agent — but it's intended for errors produced by the tool implementation (e.g. "paper not found"). For a SERVER-LEVEL refusal to invoke the tool (cap reached), the spec arguably calls for a JSON-RPC `error` envelope (e.g. `{"error": {"code": -32000, "message": "..."}}`), not a successful `result` with `isError=true`.

The `mcp` Python SDK on the client side parses both shapes, so the choice is wire-correct in practice. But the brief framing (*"the agent receives the error as a structured tool result it can read and act on"*) suggests the team intentionally chose the `isError=true` path so the agent's tool-handling loop receives a parseable result, not an exception. Document this trade-off explicitly.

**Why:** Operationally the `isError=true` choice is sensible — it lets the agent see the structured content and decide to proceed with already-retrieved chunks. But MCP spec compliance is a topic this project takes seriously (see `06-mcp-server-design.md`); a deliberate choice deserves a paragraph in `docs/orchestrator-rules.md` explaining WHY `isError=true` over JSON-RPC error.

**Fix:** Add a paragraph to `docs/orchestrator-rules.md` "Wire format" section explaining the `isError=true` choice vs JSON-RPC error envelope and the reasoning (agent ergonomics: the tool-result handler is the natural processing path; the error envelope would surface as an exception in many SDKs).

### F9 — Cap rejection bypasses FastMCP request-counting / metrics

**Severity:** MEDIUM

**File:line:** `server/middleware.py:861-892`

**What:** The cap rejection synthesizes the entire HTTP response in middleware and never invokes the inner FastMCP app. This means:

- The `tools_call_total{tool="search_papers"}` Prometheus counter (if any) won't increment.
- FastMCP's per-tool latency histograms won't observe the cap-rejection.
- Any FastMCP-level audit logging for `tools/call` won't see the rejection.

`docs/orchestrator-rules.md:236-239` even promises *"Future milestone (E08_S05 or later) will add Prometheus counters for cap hits."* — but the metric is not yet wired AND the FastMCP-side metric (which would have shown the cap-rejection naturally) is bypassed.

**Why:** Operators reading `arxmcp_tool_calls_total` to track tool usage will see a misleadingly low count for `search_papers` / `get_chunk` if many cap-rejections occur. There's no observability today for "how often is the cap firing?"

**Fix:** Add a `prometheus_client.Counter` named `arxmcp_retrieval_cap_rejections_total{tool}` in `server/health.py` (or a new `server/cap_metrics.py`) and increment it in `SessionCapMiddleware` on the cap-rejection path. Add a test that scrapes `/metrics` after a cap rejection and verifies the counter incremented.

### F10 — `canonicalize_turn` does NOT handle non-list (e.g. tuple) input gracefully

**Severity:** LOW

**File:line:** `server/orchestrator/id_canon.py:159` (`copy.deepcopy(messages)` preserves type)

**What:** `copy.deepcopy(tuple_input)` returns a tuple. The function then iterates and rewrites in place via `block["id"] = new_id`, which works for dict blocks but the function's return type annotation (`list[dict[str, Any]]`) is now a lie if the caller passes a tuple.

```python
>>> canonicalize_turn(({"role": "assistant", "content": [{"type": "tool_use", "id": "x"}]},))
({'role': 'assistant', 'content': [{'type': 'tool_use', 'id': 'toolu_00000000'}]},)
# ← tuple, not list
```

**Why:** Type annotation mismatch. Not a bug in practice (callers pass lists), but a documented contract violation.

**Fix:** Either coerce `canonicalized = list(canonicalized)` at the top, or add an `assert isinstance(messages, list)` at function entry. The latter is more defensible.

### F11 — `SessionCapMiddleware` always buffers the body for ANY POST /mcp, not just `tools/call`

**Severity:** LOW

**File:line:** `server/middleware.py:786-803`

**What:** The middleware buffers the entire request body (up to 1MB) BEFORE checking whether the body is a `tools/call`. For `initialize`, `ping`, `tools/list`, `notifications/initialized` etc., the body is buffered, then parsed, then determined to not be `tools/call`, then replayed via the synthetic receive. This is wasted work on every non-tools-call request to /mcp.

**Why:** Modest perf cost; not a correctness issue. But on a busy server, every initialize and every notifications/initialized roundtrip pays a 1MB-bytearray allocation + JSON parse cost.

**Fix:** Could be defer-buffered: check the JSON-RPC method by partial-read first (the method field is typically in the first 64 bytes), and only buffer-fully if it's a tools/call. Optimization, not a defect.

### F12 — `_retrieval_cap_payload` exposes internal session attempt count

**Severity:** LOW

**File:line:** `server/middleware.py:914-927`

**What:** The cap-rejection payload includes `session_attempted_count` — the number of attempted calls (cap + N for the Nth rejection past the cap). This is only a leak of the requesting client's own state to the requesting client, so not a cross-client information leak. But it does enable a malicious agent to probe how aggressively to retry (knowing the exact attempt number lets the agent build a precise retry-backoff).

**Why:** Marginal observability surface. Not a real defect.

**Fix:** Acceptable as-is for v1, OR drop `session_attempted_count` from the response and keep it logged only.

### F13 — `docs/orchestrator-rules.md` worked example doesn't exercise tool-result `content` as a list of blocks

**Severity:** LOW

**File:line:** `docs/orchestrator-rules.md:79-131` (the worked example uses opaque `tool_result` rows)

**What:** The Anthropic Messages API allows `tool_result.content` to be a list of content blocks (text, image, etc.) rather than a string. The worked example in the doc uses opaque single-row tables; the test file (`tests/test_id_canon.py`) uses the helper `_tool_result(...)` which produces `content=[{"type":"text","text":"result"}]` — a list-of-blocks form. The implementation correctly leaves nested non-id-carrying blocks untouched (verified live: a `tool_result` with `content=[{"type":"text","text":"result"}]` round-trips with `tool_use_id` rewritten and the inner text block unchanged), but the doc never says so.

**Why:** A reader implementing canonicalization in another language would benefit from a worked-example row showing the nested-content shape.

**Fix:** Add a worked-example row in `docs/orchestrator-rules.md` showing a `tool_result` with nested `content` blocks, and confirm that nested blocks (which lack `id`/`tool_use_id`) are left unchanged.

## What was done well

- **Clean separation of pure logic (`id_canon.py`) and stateful registry (`session.py`)** — both modules have minimal external deps and clear single-responsibility shapes; this matches the project's standing pattern (cf. `server/cache.py`).
- **Deep-copy mutation discipline on `canonicalize_turn`** — the design-note pseudocode mutates in place; the implementation deviates with rationale, deep-copies, and pins the discipline with explicit tests in `TestDeepCopyDiscipline`. Caller invariants are stronger than the brief required.
- **Per-session `asyncio.Lock` for the counter increment** — the race-safety test (`test_concurrent_increments_under_per_session_lock_serialize`) drives 5 concurrent attempts and asserts exactly 3 succeed. This is the right pattern.
- **`reset_session_state_for_tests` autouse fixture in `conftest.py`** — mirrors the cache-isolation discipline from E08_S03; prevents per-test counter leaks AND documents the reasoning in the fixture docstring.
- **Worked 4-agent fan-out example pinned by a test** (`TestFourAgentFanoutExample`) — a future doc edit that drifts from the canonical IDs would fail at test time, not just at review time.
- **Failure-mode discipline in `SessionCapMiddleware`** — any internal error (failed body decode, registry exception) logs at INFO and forwards through. Explicitly documented in the docstring as "fail open is right because the cap is a defensive ceiling, not a security boundary."
- **`is_canonical_id` helper** — small, well-tested, makes downstream invariant assertions concise without re-encoding the regex.
- **Doc cross-references at the bottom of `orchestrator-rules.md`** — the canonical-reference doc points back to the implementation files AND the design notes (`07-multi-agent-caching.md`, `08-security-observability-ops.md`). Future maintainers can navigate to the rationale.
- **All 42 new tests pass** (`pytest tests/test_id_canon.py tests/test_session_caps.py` runs clean in <0.5s).

## Recommended rectification order

1. **F1** (HIGH) — fix the per-call vs per-session counter semantics. Either thread session state through the API or document/test the "always pass full history" precondition prominently. This is the load-bearing correctness gap.
2. **F2** (HIGH) — close the spoofed-session-id bypass. Validate against the FastMCP `StreamableHTTPSessionManager` issued-id set, OR enforce the `^[0-9a-f]{32,}$` format AND require prior `initialize`. Without this, the brief's "client cannot override" statement is false.
3. **F3** (MEDIUM) — add the `server/orchestrator/test_id_canon.py` re-export stub so the literal AC is satisfied.
4. **F4** (MEDIUM) — handle `id` AND `tool_use_id` co-occurrence explicitly (raise OR map both).
5. **F6** (MEDIUM) — add the LRU eviction test.
6. **F7** (MEDIUM) — add the middleware-order assertion test.
7. **F8** (MEDIUM) — document the `isError=true` vs JSON-RPC error trade-off in `orchestrator-rules.md`.
8. **F9** (MEDIUM) — wire the Prometheus counter for cap rejections.
9. **F5, F10, F11, F12, F13** (LOW) — clean-up; can land in any order.

## Rectification status

(empty — for the rectifier to fill in)
