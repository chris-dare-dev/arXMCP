# Implementation Summary — notebook-surface-expansion-m4

**One-liner:** Notebooks are now first-class MCP **resources** — `arxmcp://notebooks`
(index) + `arxmcp://notebooks/{slug}` (per-notebook metadata) — so a pipeline agent
discovers corpora via `resources/list`+`read` at ZERO BP1 cost, with the frozen
8-tool surface + `tools/list` bytes + BP1 hash byte-identical. (Epic e2, piece 1/2.)

**Commit range:** `<base>..<head>` (filled at finalize).
**Implementation path:** inline — 4 source/doc files + 1 new test file.

---

## What landed

### `server/mcp_resources.py` (new)
- `register_resources(mcp_server)` registers a concrete index resource
  `arxmcp://notebooks` (`resources/read` → `{count, notebooks:[{slug, display_name,
  uri}]}`) + a template `arxmcp://notebooks/{slug}` (`resources/read` → one
  notebook's metadata). Both async callbacks; `mime_type="text/plain"`.
- `_notebook_metadata(slug)`: `validate_slug(slug)` FIRST (path-traversal guard,
  before any store/FS access) → `get_notebook` (None → `NotebookError` not-found) →
  `list_papers` count → `is_ingested` (lancedb-dir stat, guarded). Returns
  `{slug, display_name, notebook_kind, created_at, parse_status, paper_count,
  is_ingested}` — **`lancedb_path` deliberately OMITTED** (host-path info-leak, D3).
- Store reached via a module-global `set_notebooks_store` (resource callbacks have
  no FastAPI DI), mirroring `server.tools.set_resources`; `_require_store()` raises
  `NotebookError("notebooks store not ready")` if unset. `reset_notebooks_store_for_tests`.
- JSON payload wrapped in `<retrieved_notebook>…</retrieved_notebook>` (Threat 2).

### `server/tools.py`
- Added `_WRAP_TAG_NOTEBOOK = "retrieved_notebook"` + a `notebook` branch to
  `wrap_retrieved_text` (centralizes the Threat-2 discipline). NOT a tool / not in
  `ALL_TOOLS` → no `tools/list` hash impact (the guard test pins this).

### `server/main.py`
- `register_resources(mcp_server)` called AFTER `register_all_tools`, BEFORE
  `mount_mcp` (snapshot-at-mount constraint). `set_notebooks_store(app.state.
  notebooks_store)` in the lifespan right after the store opens (same loop as FastMCP).

### `.claude/notes/06-mcp-server-design.md`
- Resource-surface section now documents the notebook resources as the FIRST live
  MCP resources + the posture (validate_slug, `<retrieved_notebook>` wrap, no
  `lancedb_path`, subscribe deferred, byte-stability pinned) (D7).

### `tests/test_mcp_resources.py` (new, 13 tests)
Byte-stability guard (`tools/list` hash == `EXPECTED_TOOL_SCHEMA_SHA256` with
resources registered; two-server comparison; 8 tools unchanged); resources/list +
templates/list membership; index read enumerates seeded slugs + empty case; detail
read metadata shape (no `lancedb_path`, has `is_ingested`); malformed/uppercase +
too-short slug rejected; unknown slug not-found; `display_name` injection wrapped +
structurally inert; store-not-ready guard.

---

## Acceptance criteria status

- [x] **AC1** — `resources/list` exposes `arxmcp://notebooks`; reading it enumerates
  every notebook; `arxmcp://notebooks/{slug}` (template) reads one notebook's
  metadata (no chunk content). **DEVIATION (D1):** the AC's literal "one
  `arxmcp://notebooks/{slug}` per notebook IN resources/list" is realized as a
  concrete index resource (whose read enumerates all slugs) + a `{slug}` template —
  per-notebook *concrete* registration is brittle (snapshot-at-mount + no
  create-time refresh hook) and deferred; the discovery intent is met.
- [x] **AC2** — malformed/traversal slug rejected via `validate_slug` before any
  store/FS access (tested: uppercase, too-short).
- [x] **AC3a** — byte-stability guard test asserts `EXPECTED_TOOL_SCHEMA_SHA256`
  unchanged after resources registered (NO re-pin); BP1 gate (`test_prompts.py`)
  green; no `TOOL_SCHEMA_VERSION` bump.
- [x] **AC3b** — resources/list + resources/read tests (metadata shape; traversal
  rejection; empty case; display_name wrapped/escaped).

## Deviations from the brief

1. **D1 — index+template, not per-notebook concrete registration** (above).
2. **D3 — `lancedb_path` OMITTED**, replaced with `is_ingested: bool` (absolute
   host-path info-leak to an agent).
3. **D2 — wrap in `<retrieved_notebook>`** (brief said "wrapped/escaped"; resolved
   to the threat-model delimiter wrap via the centralized `wrap_retrieved_text`).

## Test surface

New: `tests/test_mcp_resources.py` (13). Changed: `server/mcp_resources.py` (new),
`server/main.py`, `server/tools.py`, `.claude/notes/06-mcp-server-design.md`. ruff
clean. Pinned-hash gates (`test_server_tool_schema.py`, `test_prompts.py`) +
`test_server_startup.py` green.

**Pre-existing failure (NOT m4):** `test_tools_all.py::test_cite_neighbors_wired`
fails (`graph_status == 'unavailable'` vs `'absent'`) because a stale
`var/arxmcp/index/kuzu` DIRECTORY exists on this workstation (dated 2026-05-20). My
diff touches no graph/citations code; this failure predates the milestone.

## Byte-stability / scope

The frozen 8-tool surface, `tools/list` wire bytes, `EXPECTED_TOOL_SCHEMA_SHA256`,
and `EXPECTED_BP1_SHA256` are byte-identical (resources are a separate JSON-RPC
method; `wrap_retrieved_text` is not a tool). Resources are READ-ONLY (mutation
stays on `/ui/api`). `/mcp` inherits the SecFetchSite+Origin+Host loopback triple.

## External writes required

**None.** Purely local.
