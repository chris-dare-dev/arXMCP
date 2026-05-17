# E13_S01 — Research Brief 2 (External / Spec)

**Scope:** MCP 2025-06-18 spec, JSON-RPC 2.0 error code semantics, mcp Python SDK
empirical behavior on validation failure, arXiv canonical identifier docs, and the
test-shape recommendations that follow. Researcher 1 owns the in-codebase audit;
this brief is opinionated about the spec layer that the brief got wrong.

---

## 1. Light in-codebase confirmation (Pydantic→Schema bridge)

`server/tools.py::register_all` (lines 536-580) calls
`mcp_server.add_tool(handler, name=..., description=..., meta=...)`. There is **no
explicit `inputSchema` argument** — FastMCP derives the JSON-Schema from each
handler's typed signature via `func_metadata` (`mcp/server/fastmcp/tools/base.py`
lines 70-77: `parameters = func_arg_metadata.arg_model.model_json_schema(by_alias=True)`).

**Consequence:** every Pydantic `Annotated[str, Field(pattern=...)]` constraint
appears in the published `tools/list` schema bytes. Today, **no handler uses
`pattern=` on `paper_id` or `chunk_id`** (researcher 1 confirms — only `min_length=1`
is set on paper_id args; `chunk_id` arg in `chunk.py` has no Field constraints at
all). The JSON-Schema published to clients is silent on Threat-1 format.

When a Pydantic field fails validation, the wire response is **not** -32602 (see §3).

## 2. MCP 2025-06-18 spec — verbatim on tool error handling

From `https://modelcontextprotocol.io/specification/2025-06-18/server/tools`:

> ## Error Handling
>
> Tools use two error reporting mechanisms:
>
> 1. **Protocol Errors**: Standard JSON-RPC errors for issues like:
>    * Unknown tools
>    * Invalid arguments
>    * Server errors
>
> 2. **Tool Execution Errors**: Reported in tool results with `isError: true`:
>    * API failures
>    * Invalid input data
>    * Business logic errors
>
> Example protocol error:
> ```json
> {"jsonrpc":"2.0","id":3,"error":{"code":-32602,"message":"Unknown tool: invalid_tool_name"}}
> ```
> Example tool execution error:
> ```json
> {"jsonrpc":"2.0","id":4,"result":{"content":[{"type":"text","text":"Failed to fetch weather data: API rate limit exceeded"}],"isError":true}}
> ```

And from `## Security Considerations`:

> 1. Servers **MUST**:
>    * Validate all tool inputs
>    * Implement proper access controls
>    * Rate limit tool invocations
>    * Sanitize tool outputs

**Reading the spec precisely.** The spec lists **"Invalid arguments"** under
**Protocol Errors** (the -32602 bucket) — this is the textual hook the milestone
brief is leaning on. But the example is for an *unknown tool*, not for argument-
shape validation. The spec is ambiguous: it nominates two mechanisms ("Protocol
Errors" vs "Tool Execution Errors") and does NOT pin which one a tool's
inputSchema-validation failure must use. There is no `MUST` text on either side.
"Invalid input data" appears under the `isError:true` bucket, not the -32602
bucket. A reasonable read is: the spec leaves the choice to the implementation.

The strongest spec rule is **"Servers MUST validate all tool inputs"** — which we
already do via in-body `is_valid_paper_id`. The wire encoding is implementation
choice.

## 3. JSON-RPC 2.0 error code table — verbatim

From `https://www.jsonrpc.org/specification`:

| code | message | meaning |
|------|---------|---------|
| -32700 | Parse error | Invalid JSON was received by the server. |
| -32600 | Invalid Request | The JSON sent is not a valid Request object. |
| -32601 | Method not found | The method does not exist / is not available. |
| -32602 | Invalid params | Invalid method parameter(s). |
| -32603 | Internal error | Internal JSON-RPC error. |

`-32602` is the JSON-RPC-correct code for "method exists, params are wrong-shape".
`-32600` is for malformed Request envelopes. A path-traversal `paper_id` is a
-32602 case, not -32600.

## 4. mcp Python SDK — what it actually emits (verbatim source)

I read three load-bearing files. The full chain on validation failure today:

**a. JSON-Schema validation in `mcp/server/lowlevel/server.py:521-532`:**

```python
async def handler(req: types.CallToolRequest):
    try:
        tool_name = req.params.name
        arguments = req.params.arguments or {}
        tool = await self._get_cached_tool_definition(tool_name)
        if validate_input and tool:
            try:
                jsonschema.validate(instance=arguments, schema=tool.inputSchema)
            except jsonschema.ValidationError as e:
                return self._make_error_result(f"Input validation error: {e.message}")
```

**b. `_make_error_result` (lines 467-474):**

```python
def _make_error_result(self, error_message: str) -> types.ServerResult:
    return types.ServerResult(
        types.CallToolResult(
            content=[types.TextContent(type="text", text=error_message)],
            isError=True,
        )
    )
```

**c. Pydantic validation in `mcp/server/fastmcp/tools/base.py:93-117`:**

```python
async def run(self, arguments, context=None, convert_result=False):
    try:
        result = await self.fn_metadata.call_fn_with_arg_validation(...)
        ...
    except Exception as e:
        raise ToolError(f"Error executing tool {self.name}: {e}") from e
```

The `ToolError` then propagates to `lowlevel/server.py:583-584`:

```python
except Exception as e:
    return self._make_error_result(str(e))
```

**The verdict: `mcp` Python SDK NEVER emits JSON-RPC -32602 for tool argument
validation.** Both jsonschema validation AND Pydantic ValidationError surface as
`CallToolResult(isError=True, content=[TextContent(text=...)])`. The only -32602
path in the codebase is for *unknown-tool* requests (`mcp/types.py:189`
`INVALID_PARAMS = -32602` is defined; grep `mcp/server/` shows it is referenced
only in the higher-level request-routing logic, not the tool argument path).

**This is the headline finding for the synthesist:** the milestone brief's
acceptance criterion "produce JSON-RPC -32602 Invalid Params" **cannot be met by
the mcp Python SDK today without bespoke handling**. Two paths forward:

- **(α) Reframe AC to match SDK:** "every adversarial input produces a
  `CallToolResult` with `isError=True` and a message identifying the input as a
  malformed identifier; the handler body never reaches LanceDB/Kùzu." This is
  testable with the existing surface. **Recommended.**
- **(β) Bespoke -32602:** raise `McpError(ErrorData(code=INVALID_PARAMS, ...))`
  from a pre-handler wrapper. `mcp.shared.exceptions.McpError` exists; the
  low-level server's `_handle_request` catches `McpError` and emits a proper
  JSON-RPC error response. This requires wrapping every handler — non-trivial
  blast radius, and the design note 08 does NOT specifically demand -32602 (it
  says "Reject at the JSON-Schema level so it never reaches handlers"). Skip
  for Tier-5.

## 5. arXiv canonical identifier format — verbatim

From `https://info.arxiv.org/help/arxiv_identifier.html`:

> The canonical form of identifiers from January 2015 (1501) is arXiv:YYMM.NNNNN,
> with 5-digits for the sequence number within the month.

Pre-2015 (0704–1412) used 4 digits. Pre-April 2007: `archive[.subjectclass]/YYMMNNNN`,
seven digits. Version suffix `vN` is OPTIONAL: "Without the version number ...
the identifier refers to the most recent version of the article."

**The canonical regex `^\d{4}\.\d{4,5}(v\d+)?$` (new) + `^[a-z][a-z\-]*/\d{7}(v\d+)?$`
(old) from `ingest/identifiers.py` matches the docs.** Researcher 1's note that
the design-note prose and milestone-brief prose carry a slightly drifted variant
(`^[a-z\-]+/\d{7}` instead of `^[a-z][a-z\-]*/\d{7}`) is correct and load-bearing —
quote the canonical one.

## 6. Length-cap defense + ReDoS

The 512-character overlong string is a **denial-of-service vector** distinct
from path-traversal: even when the regex rejects, evaluating
`^\d{4}\.\d{4,5}(v\d+)?$` on 512 characters of garbage is cheap (anchored, no
unbounded backtracking) — Python `re` engine is not vulnerable to catastrophic
ReDoS on this pattern. **But:** any future loosening of the regex (e.g. to
`(v\d+)*` with a `*` instead of `?`) would open it. Belt-and-suspenders:
**add `max_length=30` on every paper_id/chunk_id Pydantic Field** (chunk_id is at
most `arxiv:` + `<old-paper-id>` + `:` + 16 hex = 6 + ~20 + 1 + 16 ≈ 43; use 64
to be safe). 30 is too tight for chunk_id; use 30 for paper_id, 64 for chunk_id.

The length cap rejects the 512-char attack **before** regex evaluation, AND
publishes a `maxLength` constraint into the JSON-Schema seen by clients.

**Caveat: byte-stability pin.** Adding `max_length` to handler Fields will
change `tools/list` bytes and trip `EXPECTED_TOOL_SCHEMA_SHA256` (CLAUDE.md §9
step 4). Plan for re-pinning via `pytest --update-tool-schema-hash`.

## 7. Defense-in-depth — keep in-body validators

Even if we add `pattern=` to every Field (which would push validation into
FastMCP/jsonschema), the existing in-body `is_valid_paper_id` / `is_valid_chunk_id`
guards should **stay**. Reasons:

1. **Single source of truth.** `ingest/identifiers.py::PAPER_ID_RE` is the lock
   (F11 close from E06_S03). The Pydantic `pattern=` would duplicate the regex
   into the handler signature; drift between the two is exactly the failure
   mode F11 was created to prevent. Better: keep `pattern=PAPER_ID_PATTERN`
   importing from `ingest.identifiers` so there's one regex string in flight.
2. **Belt-and-suspenders.** A future contributor turning off `validate_input` in
   the low-level server, or a refactor that drops the FastMCP Pydantic guard,
   shouldn't silently unguard the handler.
3. **Cost is negligible.** One regex match per request.

## 8. Test-shape recommendations

**Parametrise pattern (researcher-1-confirmed real tool surface):**

```python
import pytest
from mcp.types import CallToolRequest, CallToolRequestParams

ADVERSARIAL = [
    pytest.param("../../../etc/passwd", id="path_traversal"),
    pytest.param("; cat /etc/shadow #", id="shell_injection"),
    pytest.param("a" * 512, id="overlong_512"),
]

# Tools that accept a paper_id scalar
PAPER_ID_TOOLS = [
    ("get_paper", "paper_id"),
    ("get_definitions", "paper_id"),
    ("find_lemma_by_name", "paper_id"),  # optional arg
]

# Tools that accept a chunk_id scalar
CHUNK_ID_TOOLS = [
    ("get_chunk", "chunk_id"),
    ("cite_neighbors", "chunk_id"),
]

@pytest.mark.parametrize("tool_name,arg_name", PAPER_ID_TOOLS)
@pytest.mark.parametrize("bad_input", ADVERSARIAL)
async def test_paper_id_path_traversal(tool_name, arg_name, bad_input, mcp_app, monkeypatch):
    # Spy on the handler body — assert it was NOT invoked
    handler_called = {"flag": False}
    monkeypatch.setattr(
        f"server.handlers.{_module_for(tool_name)}.handle_{tool_name}",
        lambda *a, **kw: handler_called.__setitem__("flag", True) or None,
    )
    args = {arg_name: bad_input}
    # add required-other-args defaults if needed (term, name, etc.)
    result = await mcp_app.call_tool(tool_name, arguments=args)
    assert result.isError is True
    assert handler_called["flag"] is False
```

For `find_lemma_by_name` the `paper_id` is optional, so pair it with a
non-empty `name="x"` to bypass the `name` validator and isolate the paper_id
regex.

**How to invoke the tool surface from tests.** Three options, in order of
preference for *this* milestone:

1. **Direct `Tool.run(arguments)` on the FastMCP Tool object.** Cheapest.
   `mcp_server._tool_manager.list_tools()` enumerates Tool objects; each has
   `.run({...args})` that exercises the Pydantic guard but bypasses the JSON-RPC
   transport. **Best signal-to-noise for the 21 cases.** Asserts `ToolError`
   is raised OR `CallToolResult(isError=True)` is returned, depending on
   convert_result path.
2. **`mcp_server.handle_request(CallToolRequest(...))`.** Goes through the
   full handler path including `jsonschema.validate` against the published
   inputSchema. Useful if we DO add `pattern=` to Fields and want to confirm
   the JSON-Schema rejection.
3. **HTTP fetch against `streamable_http_app`.** Most expensive. Skip for unit-
   level audit; consider one smoke test only.

**Handler-spy via monkeypatch.** Don't try to swap `register_all`; instead
monkeypatch the underlying function (e.g. `server.handlers.paper.handle_get_paper`)
and assert it was NOT called. Pydantic/JSON-Schema validation happens BEFORE
the wrapped handler invocation, so a working guard means the spy stays clean.

**Assertion shape (matching the SDK reality, not the brief):**

```python
assert result.isError is True
err_text = result.content[0].text
assert ("does not match" in err_text or "id format" in err_text
        or "Input validation error" in err_text or "ValueError" in err_text)
assert handler_called["flag"] is False
```

## 9. Open questions (for synthesis)

1. **-32602 vs `isError=True`:** the MCP spec is ambiguous; the mcp Python SDK
   emits `isError=True` for both JSON-Schema and Pydantic validation failures.
   **Recommend reframing AC to `isError=True` + handler-not-called.** Migrating
   to true -32602 requires custom `McpError` wrapping — out of Tier-5 budget.
2. **Length cap:** add `max_length=30` (paper_id) / `max_length=64` (chunk_id) on
   every relevant Field. Belt-and-suspenders against future regex changes and
   publishes the constraint to clients via the `tools/list` schema. Accept the
   byte-stability re-pin as the cost.
3. **Tool surface drift:** the brief names 7 tools but lists `paper_diff` and
   `dependency_graph` which DO NOT EXIST; the real seven are `search_papers`,
   `get_chunk`, `find_equation`, `get_definitions`, `find_lemma_by_name`,
   `get_paper`, `cite_neighbors` (per `server/tools.py::ALL_TOOLS`). Researcher 1
   has the per-handler input map; synthesis should adopt that list.
4. **Doc destination:** per CLAUDE.md §1, the audit checklist goes to
   `.claude/docs/security-threat-1-audit.md`, NOT `docs/security/`.

## 10. External writes required

**Zero.** All work is local: new `tests/security/test_path_traversal.py`,
new `.claude/docs/security-threat-1-audit.md`, in-body `is_valid_chunk_id` patch
to `server/handlers/citations.py`, and optionally `max_length` Field additions
across all paper_id/chunk_id args (with `EXPECTED_TOOL_SCHEMA_SHA256` re-pin).

---

**Word count:** ~1480.
