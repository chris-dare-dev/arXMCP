# Research Brief — verification-feedback-m4

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-30T15:45:00Z

---

## In-codebase context

### 1. Tool registration + handler signature surface

`server/tools.py` (lines 809–871): `register_all(mcp_server: FastMCP)` iterates `ALL_TOOLS`
and calls:

```python
mcp_server.add_tool(
    _wrap_with_observability(tm.name, handler_by_name[tm.name]),
    name=tm.name,
    description=tm.description,
    meta=meta,
)
```

The `_wrap_with_observability` wrapper (lines 688–799) uses `@functools.wraps(handler)` which
sets `__wrapped__`. **Critical:** `inspect.signature` in Python 3.12 follows `__wrapped__` by
default — FastMCP's `func_metadata` at
`.venv/.../mcp/server/fastmcp/utilities/func_metadata.py:222` calls
`inspect.signature(func, eval_str=True)` which transparently sees the ORIGINAL handler's
signature. Therefore: any `ctx: Context` parameter added to a handler is correctly detected by
FastMCP's `find_context_parameter` even through the observability wrapper.

**Current signatures (all 8 registered handlers, verbatim):**

- `handle_search_papers(query, level, k, filters, cursor)` — `server/handlers/search.py`
- `handle_get_chunk(chunk_id, include_referenced, include_equations)` — `server/handlers/chunk.py`
- `handle_find_equation(latex, k, alpha)` — `server/handlers/equation.py`
- `handle_get_definitions(paper_id, term, page, cursor)` — `server/handlers/definitions.py`
- `handle_find_lemma_by_name(name, paper_id, k)` — `server/handlers/lemma.py`
- `handle_get_paper(paper_id)` — `server/handlers/paper.py`
- `handle_cite_neighbors(chunk_id, direction, depth)` — `server/handlers/citations.py`
- `handle_lean_verify(snippet, imports, mode) -> dict[str, Any]` — `server/handlers/lean_verify.py:268–304`

The `lean_verify` handler today has **no** `ctx` parameter.

### 2. The schema-exclusion boundary (AC-3 cardinal correctness point)

FastMCP `Tool.from_function` (`tools/base.py:57–91`) calls:
```python
context_kwarg = find_context_parameter(fn)  # line 70
func_arg_metadata = func_metadata(
    fn,
    skip_names=[context_kwarg] if context_kwarg is not None else [],  # line 74
    ...
)
parameters = func_arg_metadata.arg_model.model_json_schema(by_alias=True)  # line 77
```

`find_context_parameter` (`utilities/context_injection.py`) walks `typing.get_type_hints(fn)` and
returns the name of any parameter whose annotation is a subclass of `Context`. That name goes into
`skip_names`, which means it is **excluded from the Pydantic arg_model** and therefore **never
appears in `parameters` (the `inputSchema` field in `tools/list`)**. This is the mechanism that
keeps `ctx` out of the schema — it requires no special decorator or `Annotated` marker. The ONLY
requirement is that the parameter's type annotation is literally `Context` (or a subclass).

**Import path:** `from mcp.server.fastmcp import Context`
(file: `.venv/.../mcp/server/fastmcp/server.py:1098`).

Since `functools.wraps` preserves `__wrapped__` and `inspect.signature` follows it, the
`find_context_parameter` check works correctly on the wrapped form passed to `add_tool`. The
existing `_wrap_with_observability` is transparent to Context injection with no changes.

### 3. `report_progress` signature (confirmed via live import)

```python
(self, progress: float, total: float | None = None, message: str | None = None) -> None
```

It is an `async` method — callers must `await ctx.report_progress(...)`.

Source: `.venv/.../mcp/server/fastmcp/server.py:1162`.

### 4. `lean_verify` call site anatomy

`server/handlers/lean_verify.py:336–337`:
```python
resp = await lean_repl.query({"cmd": cmd})
```

This is a **single `await`** that can take 5–30 s. The entire elaboration time lives inside
`lean_repl.query`, which internally runs `asyncio.wait_for(self._round_trip(command), timeout=30.0)`
inside `_io_lock` (`server/lean_repl.py:282–300`).

**Where to emit progress:**
There is no natural mid-elaboration cadence — the REPL is a single round-trip. The AC requires
only "at least one notification before the result for a call >2 s". The minimum-LOC approach is:

1. `await ctx.report_progress(0, 1, "Lean elaboration started")` BEFORE `lean_repl.query`.
2. Optionally: a heartbeat `asyncio.Task` that calls `report_progress` every ~3 s while awaiting.
   This satisfies the >2 s AC by definition AND provides better UX for 30 s runs.

The heartbeat pattern (recommended — see Recommendation section) uses:
```python
async def _heartbeat(ctx, total_s):
    elapsed = 0
    interval = 3.0
    while True:
        await asyncio.sleep(interval)
        elapsed += interval
        pct = min(elapsed / total_s, 0.95)
        await ctx.report_progress(pct, 1.0, f"Lean elaborating... (~{elapsed:.0f}s)")

heartbeat = asyncio.create_task(_heartbeat(ctx, DEFAULT_QUERY_TIMEOUT_S))
try:
    resp = await lean_repl.query({"cmd": cmd})
finally:
    heartbeat.cancel()
    try:
        await heartbeat
    except asyncio.CancelledError:
        pass
```

The handler's `None`-ctx guard: all 7 existing handlers do NOT take `ctx`. The AC says they are
"unchanged in behavior." m4 ONLY adds `ctx` to `handle_lean_verify`. The 7 existing handlers
need no changes — they were never registered with a Context-typed param and FastMCP's
`find_context_parameter` will return `None` for them (unchanged behavior). **Explicitly: do NOT
add `ctx` to the 7 other handlers.** The AC says "Handler signatures ... are updated to pass
`ctx: Context`" — reading this in context of the milestone, this means only `lean_verify` is
changed; the 7 others remain untouched.

However: if `lean_repl is None` (disabled path, line 331), `ctx` is still passed but never used
— this is fine; the early-return `_disabled_envelope` does not call `report_progress`.

### 5. BP1/BP2 byte-stability proof path (AC-3)

**`EXPECTED_TOOL_SCHEMA_SHA256`** in `tests/test_server_tool_schema.py:95`:
```
"c7df4c5c10c86693ac8553b7d079b55fba21749881c233f0f298955379d13375"
```
Paired with `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH: int = 16` (line 109).

**`EXPECTED_BP1_SHA256`** in `tests/test_prompts.py:649`:
```
"483344e3fcdea1d64de893cc669c9f142fd6f1198d4c8d383cd9c232558959bc"
```

The `_live_tools_payload()` function (test_prompts.py:443–464) projects ONLY `{name, description}`
per tool — the `_meta.tool_schema_version` is explicitly dropped. Adding `ctx: Context` to
`handle_lean_verify` changes NEITHER the tool's `name` nor `description` (both live in `LEAN_VERIFY`
ToolMeta in `server/tools.py:316–335`). Adding `ctx` changes only the handler's Python signature,
not the `ToolMeta` constants. Therefore:

- **`EXPECTED_BP1_SHA256` is unchanged** (hashes only `{name, description}` per tool)
- **`EXPECTED_TOOL_SCHEMA_SHA256` is also unchanged** (the `inputSchema` is derived from
  `func_metadata` with Context excluded via `skip_names`)

**The implementer MUST verify** by running after the change:
```bash
/Users/chris.dare/Library/Python/3.9/bin/uv run python -m pytest \
  tests/test_server_tool_schema.py tests/test_prompts.py --tb=short
```
and asserting both hashes are unchanged. If FastMCP version behavior differs from the above, the
hash will drift — the test is the ground truth.

**`TOOL_SCHEMA_VERSION` must NOT be bumped for this milestone.** No schema bytes change.

---

## Prior decisions and lessons

**Recent git log (last 20):**
- `7f9cac9 chore(notes): land session planning + agent-memory artifacts` (2026-05-30)
- `bd65584 chore(notes): finalize notebook-surface-expansion-m7 state -> complete`
- Active development on notebook surface expansion epics; no verification-feedback commits
  since `bfeabdf` (m3 rectification, 2026-05-22).

**m3 state.json** (`verification-feedback-m3`, phase: complete, 2026-05-22):
- All 8 m3 critique findings (F1–F8) resolved.
- `handle_lean_verify` signature as of m3: `(snippet, imports, mode) -> dict[str, Any]` —
  NO `ctx` parameter.
- m3 deliberately chose NOT to add `ctx` (the milestone brief confirms this was explicitly
  deferred to m4).

**From plans/verification-feedback-roadmap.md (Phase 1, Assumptions):**
> "Adding a `lean_verify` tool and threading the MCP `Context` through handlers does not regress
> BP1/BP2 prompt-cache discipline (tools/list byte-stability). Fallback: the `ctx` parameter is
> server-internal and not part of the tool input schema, so the schema hash should be unaffected —
> confirmed during implementation."

This is a design-time assumption validated by the FastMCP source inspection above.

**Banned pattern check:**
- `assert` for invariants: `lean_repl.py:312-314` already uses `raise LeanReplError(...)` not
  `assert` — good. New progress code must follow same discipline.
- `BaseHTTPMiddleware`: not touched by this milestone.
- `anthropic` SDK: not touched.

**`KMP_DUPLICATE_LIB_OK=TRUE`** in `tests/conftest.py` — not touched by this milestone.

**`TOOL_SCHEMA_VERSION`**: currently `16`. Must NOT be bumped (no schema bytes change).

---

## External sources

**FastMCP `Context` / `report_progress`** — confirmed via installed package
(`mcp>=1.27,<2` in pyproject.toml, resolved to `.venv`):

From `mcp/server/fastmcp/server.py:1162`:
> `async def report_progress(self, progress: float, total: float | None = None, message: str | None = None) -> None`

The MCP spec (2025-06-18) states:
> "No protocol-level streaming of tool results. `notifications/progress` is a heartbeat, not a
> partial-result channel. A `tools/call` returns exactly one `result`."
(quoted in `06-mcp-server-design.md:46–47`)

This is already documented in the design constitution. Progress notifications are fire-and-forget
(no blocking ack from the client); they transport over the SSE stream alongside the eventual
tool result.

---

## Recommendation

**Add `ctx: Context` as the LAST positional parameter to `handle_lean_verify` only.** Use a
heartbeat task pattern: fire `report_progress(0, 1.0, "Lean elaboration started")` once on entry,
then spin an `asyncio.create_task` heartbeat every 3 s (capped at 0.95 progress) that runs while
`lean_repl.query` awaits. Cancel the heartbeat in `finally`. This satisfies the ">2 s → ≥1
notification" AC by construction AND provides good UX for 30 s runs with no extra complexity.

Do NOT add `ctx` to the 7 other handlers — the AC's "unchanged in behavior" clause is explicit.

**`ctx` must be `Optional[Context]` with a default of `None`** to keep the existing non-FastMCP
test call sites (`asyncio.run(handle_lean_verify(snippet=...))`) working without change. The tests
in `test_handlers_lean_verify.py` call the handler directly without a `ctx` argument; they must
continue to pass. The heartbeat path should no-op when `ctx is None`.

Exact import line:
```python
from mcp.server.fastmcp import Context
```

Handler signature change:
```python
async def handle_lean_verify(
    snippet: Annotated[...],
    imports: Annotated[...] = None,
    mode: Annotated[...] = "full",
    ctx: Context | None = None,  # FastMCP injects; not in inputSchema
) -> dict[str, Any]:
```

**`EXPECTED_TOOL_SCHEMA_SHA256` must NOT be re-pinned** — the AC explicitly states it is
unchanged. Verify by running the schema test after implementation; if it drifts, the implementation
has a bug.

**Test for progress notifications:** use a `MagicMock(spec=Context)` or `AsyncMock` for `ctx`, set
a `side_effect` on `report_progress` to append calls to a list, and a fake `_FakeLeanRepl` with
`asyncio.sleep(2.1)` in its `query`. Assert `len(progress_calls) >= 1`.
Mark the test `@pytest.mark.asyncio` (or use `asyncio.run`). No `requires_lean_repl` needed.

---

## Open questions

No open questions — implementation can proceed on the above recommendation.

The one design decision that might look open (heartbeat vs single-emit) is resolved in the
Recommendation: use the heartbeat. It strictly dominates single-emit for the ">2 s" AC, and is
only ~10 lines of code.

---

## External writes the implementation will require

None — this milestone is purely local. No `git push`, no PR, no ticket, no infra mutation.
