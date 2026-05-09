# E06_S06 Research Brief — Tool schema byte-stability test

## 1. In-codebase context

### The BP1 stability rule (literal quote)

`.claude/notes/07-multi-agent-caching.md` lines 40–49:

> ### Property 1: Tool definitions are byte-stable
>
> Pin tool JSON schemas. Sort properties alphabetically at serialization time.
> Freeze descriptions as constants in source. A casual edit to a tool description
> blows every sub-agent's cache.
>
> Implementation: a single `tools.py` module with frozen dataclasses + a unit test
> that asserts `sha256(serialize_tools()) == EXPECTED_HASH`. Bump the hash
> deliberately when intentionally changing schema; treat as an API version bump.

`.claude/notes/06-mcp-server-design.md` line 286–290 makes the same point and adds: "bump a `tool_schema_version` field when changing them and document the change."

### Tool surface (already shipped by E06_S03)

`server/tools.py` already implements the durable structure:

- Lines 64: `TOOL_SCHEMA_VERSION: int = 1` module constant.
- Lines 89–199: 7 frozen `ToolMeta` dataclass instances (`SEARCH_PAPERS`, `GET_CHUNK`, `FIND_EQUATION`, `GET_DEFINITIONS`, `FIND_LEMMA_BY_NAME`, `GET_PAPER`, `CITE_NEIGHBORS`) + `ALL_TOOLS` tuple in registration order.
- Lines 359–398: `register_all(mcp_server)` calls `mcp_server.add_tool(handler, name=..., description=..., meta={"tool_schema_version": TOOL_SCHEMA_VERSION})`.

The `_meta` per-tool slot is **already on the wire** (FastMCP `Tool` model in `mcp/types.py:1331`: `meta: dict[str, Any] | None = Field(alias="_meta", default=None)`; FastMCP's `list_tools` at `mcp/server/fastmcp/server.py:315–330` passes `_meta=info.meta` into `MCPTool(...)`). E06_S03's `tests/test_tools_all.py:165–175` already asserts `t.meta.get("tool_schema_version") == TOOL_SCHEMA_VERSION` against every registered tool.

**Verification:** `tool_schema_version: 1` is currently surfaced as **per-tool `_meta`**, not as a top-level `tools/list` field. The brief AC #4 (`tool_schema_version: 1` appears in the `tools/list` response) is therefore **already satisfied** at the per-tool granularity. See "Open question O1" below.

### Handler signatures → schema autoderivation

`server/handlers/search.py:78–94` is the canonical example: `handle_search_papers` is a typed async function with `Annotated[..., Field(description=..., ge=..., le=...)]` parameters. FastMCP's `_tool_manager` introspects the signature into a JSON Schema that becomes `inputSchema`. Identical pattern in `server/handlers/{chunk,equation,definitions,lemma,paper,citations}.py`. **Implication:** the byte-stability hash is sensitive to (i) `Field(description=...)` strings, (ii) parameter names/order, (iii) defaults, (iv) type annotations, (v) the dataclass `description` constants in `server/tools.py:102–185`.

### Cross-checked schema version

`server/schemas/search_papers_result.json:5–6` has `"version": 1` plus the comment: "MUST equal `server.tools.TOOL_SCHEMA_VERSION` (cross-checked by `tests/test_snippet_contract.py`)". `tests/test_snippet_contract.py:440–464` (`TestSchemaVersionPin`) enforces this. Pattern to follow: a new test class `TestPinnedHash` in `tests/test_server_tool_schema.py` cross-checks the pinned hex to `sha256(canonical_json(tools_list_response))`.

### Existing pytest plugin pattern

`tests/conftest.py:21–43` already shows the right `pytest_addoption` recipe (the `--ndcg-min` flag). Mirror it: add `parser.addoption("--update-tool-schema-hash", action="store_true", default=False, help="...")`. **No need for a separate plugin or external script.**

### Helpers to reuse

`tests/test_tools_all.py:53–92` (`_seed_corpus`), 95–119 (`mocked_bge_m3`), 122–131 (`warm_app`) — exactly the fixtures the new test needs to bring up an in-process server. The test does NOT need to call `tools/call` over the wire; calling `app.state.mcp_server.list_tools()` (already pattern at `tests/test_tools_all.py:142–175`) returns `list[mcp.types.Tool]` directly.

### pyproject pytest hooks

`pyproject.toml:115–117`: `[tool.pytest.ini_options] testpaths = ["tests"], addopts = "-q"`. **No** dedicated plugin is registered; the `conftest.py` `pytest_addoption` is auto-picked-up. No edit needed here.

---

## 2. Prior decisions and lessons

- **`TOOL_SCHEMA_VERSION` is live** (E06_S03 shipped it; commit `205c8ad`). The E06_S03 research-brief-2 lines 235–245 explicitly chose option (i) "per-tool `_meta`" over a top-level envelope field. This brief should NOT re-debate that decision.
- **The MCP spec's `ListToolsResult` is `PaginatedResult` + `tools: list[Tool]` + inherited `_meta` from `Result`** (see `mcp/types.py:133–145`, `1342–1346`). So a top-level `_meta: {"tool_schema_version": 1}` IS spec-legal on the `tools/list` response, but it's **redundant** given the per-tool `_meta`.
- **FastMCP does not let you inject arbitrary top-level keys** into `tools/list` without subclassing — the response is built by the lowlevel server's `handler` at `mcp/server/lowlevel/server.py:443–460`, which wraps the FastMCP-returned `list[Tool]` into `ListToolsResult(tools=result)` with no per-call hook. To add a top-level field you would have to override the handler. Per-tool `_meta` is the cheapest path and is already wired.

### Critical decisions for the implementer

**O1 — what counts as the "`tool_schema_version: 1` in the `tools/list` response" AC?** Recommend: **already satisfied via per-tool `_meta`**. Document this explicitly in the test file's docstring + add one explicit assertion in `tests/test_server_tool_schema.py` that the wire `tools/list` JSON contains the literal substring `"_meta":{"tool_schema_version":1}` for each tool. Do NOT add a separate top-level field — that would require subclassing FastMCP for one int and is gold-plating.

**O2 — canonical input to the hash.** The brief says `sha256(canonical_json(tools_list_response))`. Recommend hashing the wire-equivalent dict built from `await app.state.mcp_server.list_tools()` then `[t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in tools]` wrapped in `{"tools": [...]}` (matches the JSON-RPC `result` body). `by_alias=True` is critical so `meta` serializes as `_meta` (the wire form). `exclude_none=True` strips fields like `outputSchema=None`, `annotations=None`, `icons=None`, `title=None` that FastMCP currently leaves unset — without it the hash includes nullable noise that is sensitive to MCP SDK version bumps unrelated to our schema.

**O3 — pinned-hash file location.** Recommend: **module-level string literal in the test file itself** (`tests/test_server_tool_schema.py`), per the brief verbatim. Sibling-file alternatives (e.g. `tests/fixtures/tool_schema_hash.txt`) add I/O and an extra path constant for no benefit on a 64-char hex string. Keep it as `EXPECTED_TOOL_SCHEMA_SHA256: str = "<64-hex>"` with a docstring above explaining the update procedure.

**O4 — `--update-tool-schema-hash` mechanism.** Recommend: **conftest hook pattern** identical to `tests/conftest.py:21–43`. Implementation: when the flag is set, the test computes the hash and uses `Path(__file__).read_text() / .write_text()` to in-place rewrite the literal (anchor on a sentinel comment like `# UPDATE-ANCHOR — do not delete`). Tests pass trivially when the flag is set (since the freshly written hash now matches). Cheapest implementation; no separate script, no import-time side effects.

**O5 — testing the update procedure.** AC requires "bumping a tool description must produce a new hash that differs from the old one" tested. Recommend: a separate test that monkeypatches `server.tools.SEARCH_PAPERS` to a frozen dataclass with a different description (frozen=True forbids field mutation, so build a new instance and patch the module attribute), recomputes the hash, asserts inequality with the pinned constant. Do NOT shell out to `pytest --update-tool-schema-hash` from inside a test (that's a recursion / cwd hazard); test the hash function in isolation.

---

## 3. External sources

- **MCP 2025-06-18 spec — `tools/list`:** https://modelcontextprotocol.io/specification/2025-06-18/server/tools — defines `ListToolsResult` as `{tools: Tool[], nextCursor?: string}`. Each `Tool` has `name`, `title?`, `description?`, `inputSchema`, `outputSchema?`, `annotations?`, `_meta?`. Spec text on `_meta` (general fields): "This property is reserved by the protocol to allow clients and servers to attach additional metadata." — i.e. injecting `tool_schema_version` into per-tool `_meta` is explicitly spec-blessed. There is no spec MUST forbidding extra top-level fields on `ListToolsResult`, but the spec does not define one for schema versioning either; per-tool `_meta` is the canonical home.
- **Anthropic prompt caching cache key boundaries:** https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching — the cache prefix is composed of `tools` array → `system` blocks → `messages` in that order. Any byte change to the `tools` JSON invalidates BP1 (and therefore every BP2/BP3 downstream). This **verifies the brief's premise.**
- **`pytest_addoption`:** https://docs.pytest.org/en/stable/reference/reference.html#pytest.hookspec.pytest_addoption — `parser.addoption(name, action="store_true", default=False, help=...)` is the canonical signature. Lives in `conftest.py`. No plugin entry-point registration needed.
- **`hashlib.sha256` cross-version stability:** https://docs.python.org/3/library/hashlib.html — SHA-256 output is FIPS-180-4 deterministic; no Python version dependency. `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)` is also Python-version stable across 3.11–3.13 (which are the supported targets per `pyproject.toml:29`). Use `ensure_ascii=True` (the default) — `ensure_ascii=False` emits raw UTF-8 which is identical bytes for ASCII-only payloads but fragile to a future tool description that includes a non-ASCII char.

---

## Open questions

- **None blocking.** O1–O5 above are recommended decisions, not open questions; the implementer should adopt them as written.

## External writes the implementation will require

- **None.** This is a purely-internal test milestone. No git push, PR, ticket, infra change, or third-party API call. The `--update-tool-schema-hash` flag rewrites a local file in-place when invoked manually by a developer; CI never sets the flag.
