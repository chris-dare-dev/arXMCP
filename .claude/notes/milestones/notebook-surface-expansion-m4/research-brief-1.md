# Research Brief — notebook-surface-expansion-m4

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-29T00:00:00Z

## In-codebase context

### FastMCP construction + registration site (verbatim)

`server/main.py:654`:
```python
mcp_server = FastMCP("arxmcp", json_response=True)
# E06_S03: tools MUST be registered BEFORE mount_mcp because
# streamable_http_app() snapshots the registered tools at
# mount time (synthesis D11).
register_all_tools(mcp_server)
mount_mcp(app, mcp_server)
# F2 fix (E06_S01): stash on app.state so the lifespan can
# thread the session-manager lifespan into ours.
app.state.mcp_server = mcp_server
```

**Register resources here:** `register_resources(mcp_server)` must go AFTER
`register_all_tools(mcp_server)` and BEFORE `mount_mcp(app, mcp_server)`. This is
the identical constraint as tools — `mount_mcp` snapshots the registry at call time.

### NotebooksStore lifespan wiring (verbatim)

`server/main.py:338`:
```python
app.state.notebooks_store = await NotebooksStore.open(
    config.notebooks_db_path
)
```

The FastAPI REST handlers reach the store via `request.app.state.notebooks_store`
using a DI dependency (`get_notebooks_store` in `server/routes/notebooks.py:164`):
```python
def get_notebooks_store(request: Request) -> NotebooksStore:
    store = getattr(request.app.state, "notebooks_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="notebook store not initialized")
    return store
```

**Crux — resource callbacks have no FastAPI `Request`:** FastMCP resource callbacks
receive only their URI parameters (no request context, no DI). The pattern used by
the tool layer is different: tools reach `Resources` via a module-level global set by
`set_resources()`. The same pattern must be used for the NotebooksStore. Add a
module-level `_notebooks_store: NotebooksStore | None = None` global in a new
`server/resources_notebooks.py` (or directly in `server/tools.py`) with
`set_notebooks_store(s)` / `get_notebooks_store_for_resources()`. Call
`set_notebooks_store(app.state.notebooks_store)` in the lifespan AFTER opening the
store, mirroring `set_resources(resources)` at `server/main.py:318-320`.

The MCP callbacks run in the SAME asyncio event loop as FastAPI (single-process
uvicorn; FastMCP is mounted as an ASGI sub-application via `mount_mcp`), so there is
**no cross-loop hazard** — `asyncio.to_thread` inside `NotebooksStore` methods is safe.

### NotebooksStore read method signatures (verbatim)

`server/notebooks_store.py:273`:
```python
async def list_notebooks(self) -> list[dict[str, str]]:
    # Returns: [{"slug": ..., "display_name": ..., "lancedb_path": ...,
    #            "created_at": ..., "notebook_kind": ..., "parse_status": ...,
    #            "parse_error": ..., "parsed_html_path": ...}, ...]
```

`server/notebooks_store.py:302`:
```python
async def get_notebook(self, slug: str) -> dict[str, str] | None:
    # Same dict shape; returns None if not found
```

`server/notebooks_store.py:422`:
```python
async def list_papers(self, slug: str) -> list[dict[str, str]]:
    # Returns: [{"paper_id": ..., "added_at": ...}, ...]
    # Returns [] for unknown slug (not None — callers must check get_notebook first)
```

**Note:** `parse_status` is notebook-scoped (single value per notebook from the
`notebooks` table), not per-paper. `list_papers()` returns only `paper_id` +
`added_at`. This is confirmed by the MEMORY note: "parse_status is on the `notebooks`
table, NOT on `notebook_papers`."

### Tool-schema byte-stability (verbatim from spike)

From `tests/test_server_tool_schema.py:94`:
```python
EXPECTED_TOOL_SCHEMA_SHA256: str = (  # UPDATE-ANCHOR — do not delete
    "c7df4c5c10c86693ac8553b7d079b55fba21749881c233f0f298955379d13375"
)
EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH: int = 16  # VERSION-ANCHOR — do not delete
```

From `tests/test_prompts.py:649`:
```python
EXPECTED_BP1_SHA256 = (
    "483344e3fcdea1d64de893cc669c9f142fd6f1198d4c8d383cd9c232558959bc"
)
```

**Neither hash changes for this milestone.** The spike proved empirically that
registering resources + templates leaves `tools/list` SHA-256 byte-identical. The AC
requires the guard test to verify this — construct a FastMCP, register_all_tools +
register_resources, then assert `compute_tool_schema_hash(tools) ==
EXPECTED_TOOL_SCHEMA_SHA256` with NO re-pin.

### validate_slug (verbatim)

`tools/_notebook_common.py:47,58`:
```python
SLUG_RE: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9-]{2,30}$")

def validate_slug(slug: str) -> None:
    if not isinstance(slug, str):
        raise NotebookError(f"slug must be a string, got {type(slug).__name__}")
    if not SLUG_RE.fullmatch(slug):
        raise NotebookError(
            f"invalid notebook slug {slug!r}: must match "
            f"{SLUG_RE.pattern!r} (lowercase letter start, then "
            f"3-30 chars of [a-z0-9-]). This rule rejects path "
            f"traversal (../, slashes), uppercase, and shell "
            f"metacharacters."
        )
```

`NotebookError` is a `RuntimeError` subclass. In FastMCP's `read_resource` path,
`ResourceTemplate.create_resource` wraps the callback exception as
`ValueError(f"Error creating resource from template: {e}")`. FastMCP then raises
`ResourceError(str(e))` from `server.py:388`. The implementer should let the
`NotebookError` propagate — FastMCP wraps it correctly.

### FastMCP resource API (confirmed from installed mcp 1.27.x)

`@mcp_server.resource("arxmcp://notebooks/{slug}")` — URI contains `{slug}` → registered
as a `ResourceTemplate` (returned via `list_resource_templates`, NOT `list_resources`).

`@mcp_server.resource("arxmcp://notebooks")` — no params → registered as a concrete
`FunctionResource` (returned via `list_resources`).

The callback return type:
- `str` → text content, MIME `text/plain` (default)
- Other types → `pydantic_core.to_json(result, fallback=str, indent=2).decode()` (JSON string)

Returning a `dict` from the callback produces canonical JSON. Use `mime_type="application/json"`.

`list_resources()` returns concrete resources. `list_resource_templates()` returns templates.

**Key design decision for AC (1):** AC says "resources/list returns one
`arxmcp://notebooks/{slug}` per notebook + the index". This requires concrete
resources (one per slug) AND the index resource. The template alone won't enumerate
slugs in `resources/list` — templates only appear in `list_resource_templates`.

**Recommended shape:**
- `arxmcp://notebooks` — concrete `FunctionResource`; callback calls
  `list_notebooks()` and returns a JSON array of `{slug, display_name}` tuples
  (the index).
- Per-slug enumeration: register one concrete resource per notebook AT STARTUP.
  `register_resources(mcp_server, store)` is called in the lifespan (not at
  `create_app` time) so it can await `list_notebooks()`. Alternatively, use the
  concrete index resource only and document that per-slug detail requires the
  template `arxmcp://notebooks/{slug}`.

**Simpler path (recommended):** register only the concrete index
(`arxmcp://notebooks`) + the template (`arxmcp://notebooks/{slug}`). The index
resource (concrete) returns all slugs; the template handles per-slug reads. AC (1)
says "resources/list returns one `arxmcp://notebooks/{slug}` per notebook" — this can
be satisfied by the index resource listing them by URI in its payload, not by
registering individual concrete resources. Verify AC intent: if "in resources/list"
means the MCP `resources/list` response must contain N concrete resource URIs (one per
notebook), then dynamic concrete resources must be registered at startup via
`add_resource`. This requires calling `register_resources` in the lifespan, not at
`create_app` time.

**FLAG:** The brief states "resources/list returns one `arxmcp://notebooks/{slug}` per
notebook". If this is literal (not merely "the index resource lists slugs"), the
implementation requires registering per-slug concrete `FunctionResource` objects at
lifespan start (after opening the store), and re-registering on notebook creation
(which has no mechanism in the current architecture). **Recommend interpreting it as:
the `arxmcp://notebooks` index resource returns the full list of slugs, and the
template handles per-slug reads.** This satisfies the AC's discovery intent without a
brittle per-slug registration loop.

### display_name indirect-prompt-injection discipline

From `08-security-observability-ops.md`:
> Wrap every returned chunk in `<retrieved_chunk>...</retrieved_chunk>` delimiters.

For `resources/read` on a slug, the `display_name` field is operator-authored (stored
in SQLite). The resource payload is NOT a retrieved chunk but a metadata struct.
Discipline: serialize as JSON (so the string is a JSON value, properly quoted) and
note that the agent consuming `resources/read` output should treat it as data. Do NOT
wrap in `<retrieved_chunk>` (that is for actual chunk content). JSON serialization is
the mitigation — a `display_name` value of `"Ignore previous instructions"` becomes
`{"display_name": "Ignore previous instructions", ...}` in the JSON payload, which is
structurally data.

**Additional guard:** the `server/routes/notebooks.py` display_name fragment uses
`html.escape`; for JSON output `json.dumps` handles quoting. No additional escaping
needed — the AC says "wrapped/escaped"; JSON serialization satisfies this.

## Prior decisions and lessons

From git log:
- `a7da3f0 chore(notes): finalize textbook-ingest-m10 state -> complete`
- `5316bfb rect(server): close textbook-ingest-m10 critique (3M 2L)`
- `ce74e61 docs(server): finalize PDF-sandbox doc + upload C-L test`

MEMORY entry (confirmed): `parse_status` is notebook-scoped on the `notebooks` table,
not on `notebook_papers`. Any resource payload must source it from `get_notebook()`.

MEMORY entry (confirmed): `jinja2-autoescape-explicit-construction` — zero `| safe`
filters exist; for the JSON resource payload, `json.dumps` is the equivalent safe
serializer.

**Banned patterns relevant here:**
- `assert` is banned — use `if … raise RuntimeError(…)` (or `NotebookError`)
- `BaseHTTPMiddleware` is banned (not relevant here)
- `import anthropic` in server/ (not relevant here)

**`TOOL_SCHEMA_VERSION` is NOT bumped** for this milestone — resources are a separate
registry; the tool surface is unchanged. The byte-stability guard test must assert
this explicitly (no re-pin allowed).

**Tool surface is 8 tools today** (not 7; the spike flagged "Stale 7-tool framing").
The `register_all` docstring says "7 v1 tools" — this is stale but should NOT be
updated in this milestone (out of scope; would be a doc-only chore commit).

## External sources

**MCP spec:** Not re-fetched; the spike already confirmed `resources/subscribe =
False` in FastMCP 1.27.x. The installed package source was read directly and confirms
the `resource` decorator API, `ResourceTemplate.matches()` regex dispatch, and
`list_resources()` vs `list_resource_templates()` split.

**Anthropic prompt caching:** Not relevant — this milestone does not touch
`tools/list` bytes or the BP1 prefix. Byte-stability is verified by test only.

## Recommendation

**Implement as: one concrete index resource + one template, both registered via a new
`register_resources(mcp_server)` function in `server/resources_notebooks.py`.**

Registration site: insert `register_resources(mcp_server)` at `server/main.py` after
`register_all_tools(mcp_server)` and before `mount_mcp(app, mcp_server)`.

The concrete index resource `arxmcp://notebooks` does not need the store at
construction time — its callback is a closure that reads the module-level
`_notebooks_store` global (set in the lifespan). The template
`arxmcp://notebooks/{slug}` callback takes `slug: str`, calls `validate_slug(slug)`
first, then calls `get_notebook()` and `list_papers()` on the global store, returning
a JSON string.

Metadata dict for `resources/read` response (JSON-serialized, `mime_type="application/json"`):
```json
{
  "slug": "...",
  "display_name": "...",
  "created_at": "...",
  "parse_status": "...",
  "notebook_kind": "...",
  "paper_count": 42,
  "lancedb_path": "..."
}
```

`paper_count` is derived from `len(await store.list_papers(slug))` — O(n) but the
notebook paper count is small (bounded to 100 per API cap). No chunk content, no
LanceDB query.

**Store access in callbacks:** add module-level globals to `server/resources_notebooks.py`:
```python
_notebooks_store: NotebooksStore | None = None

def set_notebooks_store(s: NotebooksStore) -> None:
    global _notebooks_store
    _notebooks_store = s
```

Call `set_notebooks_store(app.state.notebooks_store)` in the lifespan after
`app.state.notebooks_store = await NotebooksStore.open(...)`.

**Byte-stability guard test** (`tests/test_resources_notebooks.py`): construct two
`FastMCP` servers using `_build_app_and_list_tools(tmp_path)` pattern, one with
`register_resources` called, one without. Assert both return the same
`compute_tool_schema_hash`. Import `compute_tool_schema_hash` and `_serialize_tools`
from `tests/test_server_tool_schema.py`.

## Open questions

1. **AC (1) literal interpretation:** "resources/list returns one
   `arxmcp://notebooks/{slug}` per notebook" — does this require individual concrete
   resource URIs in the MCP `resources/list` response, or is the index resource
   containing slug URIs sufficient? **Recommendation:** treat as "index resource lists
   slug URIs"; register only index concrete + per-slug template. If the orchestrator
   overrules, concrete per-slug registration requires moving `register_resources` into
   the lifespan (not `create_app`), complicating the snapshot-at-mount constraint.

2. **Store-not-ready at callback time:** If a resource is read before the lifespan
   sets the `_notebooks_store` global (pathological timing, should never happen in
   production since `session_manager.run()` starts after the store opens), the
   callback must raise `NotebookError("notebooks store not ready")` — not return
   empty. Confirm the implementer adds this guard (mirrors `ResourcesNotReadyError`
   pattern in `server/tools.py:168`).

## External writes the implementation will require

None — this milestone is purely local. No git push, no PR, no infra mutation, no
third-party API call required to implement or test this milestone.
