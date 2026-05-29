# Research Synthesis — notebook-surface-expansion-m4

**Milestone:** Notebooks become first-class MCP **resources** (`resources/list` +
`resources/read`), metadata-only, byte-stability-preserving. (Epic e2, piece 1/2.)
**Mode:** standard (2× Sonnet). Both `ok`, 0 external writes. Spike-1 (GO) de-risked
the byte-stability question; this builds on it.
**Implementation path:** INLINE (new `server/mcp_resources.py` + a `main.py` wiring
change + a 06-doc update + a new test file; ~4 files, < 300 LOC).

---

## Load-bearing decisions (orchestrator-resolved)

### D1 — Resource shape: a concrete index + a `{slug}` template (NOT per-notebook concrete registration)

The AC says "resources/list returns one `arxmcp://notebooks/{slug}` per notebook".
Both researchers flagged this is ambiguous/brittle taken literally: FastMCP registers
a `{slug}` URI as a **template** (shows in `resources/templates/list`, not
`resources/list`); enumerating each notebook as a *concrete* resource in
`resources/list` would require **dynamic per-slug registration at lifespan start +
re-registration on every notebook create** — which has no hook today and fights the
snapshot-at-mount model. **RESOLUTION (recorded deviation):** register
- `arxmcp://notebooks` — a **concrete** `FunctionResource` whose `resources/read`
  returns the full enumeration `{count, notebooks: [{slug, display_name, uri}, …]}`; and
- `arxmcp://notebooks/{slug}` — a **template** whose `resources/read` returns one
  notebook's metadata.

This satisfies the epic INTENT ("a pipeline agent can enumerate available corpora at
ZERO BP1 cost") — the agent sees `arxmcp://notebooks` in `resources/list`, reads it
once to get every slug, then reads `arxmcp://notebooks/{slug}` for detail — without
dynamic registration. Per-notebook concrete enumeration in `resources/list` is a
future enhancement once a registry-refresh hook exists. Registered statically at
`create_app` time (in the snapshot), so no lifespan-ordering complication.

### D2 — Wrap the read payload in `<retrieved_notebook>…</retrieved_notebook>` (brief-2 over brief-1)

The briefs disagreed: brief-1 argued JSON serialization alone makes `display_name`
structurally data (no wrap); brief-2 argued the threat model mandates wrapping
operator-authored text that flows to an agent. **RESOLUTION: WRAP** — security-reviewer
is a specialist lens on this milestone, `display_name` is operator-authored free text
reaching a pipeline agent, and `08-security-observability-ops.md §Threat 2` +
`server/tools.py::wrap_retrieved_text(text, kind=…)` are the established discipline.
Reuse `wrap_retrieved_text(json_text, kind="notebook")` →
`<retrieved_notebook>{json}</retrieved_notebook>`. Set the read content `mimeType` to
`text/plain` (the body is a delimited block, not pure JSON — honest mimeType). JSON
quoting (`json.dumps`) is defense-in-depth inside the wrap. (brief-1's pure-JSON
alternative is noted; the wrap is the safer, threat-aligned choice and forestalls the
adversary's Threat-2 finding.)

### D3 — OMIT `lancedb_path`; expose `is_ingested: bool` instead (brief-2)

The AC's metadata list included `lancedb_path`, but that is an absolute host path
(`/Users/chris.dare/.../var/arxmcp/notebooks/<slug>/lancedb`) leaking the host
username + project layout to an agent (possibly in an injected session). **RESOLUTION
(recorded deviation): OMIT `lancedb_path`.** Replace with `is_ingested: bool` derived
from whether the notebook's `lancedb` dir exists on disk (one `notebook_dir(slug) /
"lancedb"` stat — cheap, loopback) — a useful discovery signal with no path leak.

**Final `resources/read` metadata (per-slug):**
```json
{"slug","display_name","notebook_kind","created_at","parse_status","paper_count","is_ingested"}
```
`paper_count = len(await store.list_papers(slug))` (bounded ≤100; no LanceDB query, no
chunk content). `parse_status` sourced from the notebook row (it is notebook-scoped,
NOT per-paper — MEMORY).

### D4 — Store access via a dedicated module-global set in the lifespan

Resource callbacks get NO FastAPI `Request`/DI. Mirror the `set_resources()` pattern:
add `set_notebooks_store(store)` / a `_notebooks_store` module-global in the new
`server/mcp_resources.py`; call it in the lifespan right after
`app.state.notebooks_store = await NotebooksStore.open(...)`. FastMCP is mounted as an
ASGI sub-app in the SAME uvicorn event loop, so the store's `asyncio.to_thread`
methods are safe (no cross-loop hazard — brief-1). Guard: if the global is `None` at
callback time (pathological — session_manager starts after store open), raise
`NotebookError("notebooks store not ready")` (FastMCP surfaces it as a resource error).

### D5 — validate_slug FIRST; error convention

The `{slug}` template callback calls `validate_slug(slug)` as its FIRST statement
(before any store/FS access) — `tools/_notebook_common.validate_slug`, regex
`^[a-z][a-z0-9-]{2,30}$` rejects `../`, slashes (decoded or `%2F`), uppercase, shell
metachars. On failure `NotebookError` propagates; FastMCP wraps it (→ MCP error). On
unknown-but-valid slug (`get_notebook` → None) raise `NotebookError` too (resource not
found). The MCP `/mcp` transport is NOT in `SecFetchSiteMiddleware.exempt_prefixes`
(only `/ui` is), so resources inherit the strict `Sec-Fetch-Site: none` + Origin +
Host loopback triple-layer — same protection as tool calls (brief-2 FM-5).

### D6 — Separate module + the STOP-don't-re-pin byte-stability rule

New `server/mcp_resources.py` (NOT inline in `tools.py`/`main.py`) keeps the resource
surface decoupled so a resource can never accidentally land in `ALL_TOOLS`. Register
`register_resources(mcp_server)` AFTER `register_all_tools`, BEFORE `mount_mcp`
(`server/main.py:658-659`). **The new guard test mirrors spike-1's two-server
comparison:** build a FastMCP, `register_all_tools` + `register_resources`, assert
`compute_tool_schema_hash(list_tools()) == EXPECTED_TOOL_SCHEMA_SHA256` (import the
helper from `tests/test_server_tool_schema.py`) AND the `test_prompts.py` BP1 gate
stays green — with **NO re-pin of either hash, NO `TOOL_SCHEMA_VERSION` bump**. If
either drifts, the wiring LEAKED — fix the leak, never re-pin.

### D7 — Update `06-mcp-server-design.md` Resource-surface section (additive)

brief-2 found the note's Resource-surface section (lines ~257-270) lists
`arxmcp://chunks/`, `arxmcp://papers/…` but NOT `arxmcp://notebooks/` (and none are
actually registered yet — m4 is the FIRST live resource registration). Add the
`arxmcp://notebooks` + `arxmcp://notebooks/{slug}` entries + a note that they are the
first live resources. Keeps the constitution accurate (the discipline m3 just
established).

---

## Implementation checklist

1. **`server/mcp_resources.py`** (new) — `_notebooks_store` global + `set_notebooks_store`;
   `register_resources(mcp_server)` registering the concrete `arxmcp://notebooks` index
   + the `arxmcp://notebooks/{slug}` template; a `_notebook_metadata(slug) -> dict`
   builder (validate_slug-first, get_notebook→None→raise, list_papers count, is_ingested
   stat, OMIT lancedb_path); JSON-serialize + `wrap_retrieved_text(..., kind="notebook")`;
   `mimeType="text/plain"`. `if … raise` (no `assert`).
2. **`server/main.py`** — `register_resources(mcp_server)` between `register_all_tools`
   and `mount_mcp`; `set_notebooks_store(app.state.notebooks_store)` in the lifespan
   after the store opens. Confirm `wrap_retrieved_text` accepts `kind="notebook"` (else
   extend it minimally).
3. **`.claude/notes/06-mcp-server-design.md`** — add the notebooks resources to the
   Resource-surface section (additive; D7).
4. **`tests/test_mcp_resources.py`** (new) — (a) byte-stability guard (two-server hash
   comparison == `EXPECTED_TOOL_SCHEMA_SHA256`); (b) `resources/list` includes
   `arxmcp://notebooks`; (c) `resources/templates/list` includes the `{slug}` template;
   (d) `resources/read` index → enumerates seeded slugs; (e) `resources/read` slug →
   metadata shape (no `lancedb_path`; has `is_ingested`); (f) malformed/traversal slug →
   error before store access; (g) unknown slug → not-found error; (h) `display_name`
   with injection text → wrapped in `<retrieved_notebook>` + structurally inert; (i)
   empty-notebooks case. Seed via the established new-event-loop store + REST pattern.
   Also assert the `test_prompts.py` BP1 gate is unaffected (run it / import the hash).

## Open questions

None blocking — D1 (AC interpretation), D2 (wrap), D3 (lancedb_path omit), and the
store-not-ready guard are all resolved above.

## External writes required

**None.** Purely local: a new server module + a main.py wiring change + a constitution
doc edit + a new test file. No push/PR/issue/infra in the implementation (push at
milestone end is per-event authorized).
