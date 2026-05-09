# E06_S06 — Implementation summary

**One-line:** Pinned-hash byte-stability test for the `tools/list` response, with `--update-tool-schema-hash` flag for intentional schema bumps.

## Files

### NEW: `tests/test_server_tool_schema.py` (~390 LOC)

Three test classes plus the hash-computation helpers:

- **`TestPinnedHash`** (1 test): `test_live_tools_match_pinned_hash` computes `sha256(canonical_json(tools/list response))` and asserts it equals `EXPECTED_TOOL_SCHEMA_SHA256`. The pin lives as a module-level string literal in this file; when `--update-tool-schema-hash` is set, the test rewrites the literal in place via the `UPDATE-ANCHOR` sentinel pattern, then `pytest.skip`s with a "re-run without flag to verify" message.

- **`TestSchemaVersionMetaSurface`** (2 tests): per-tool `_meta` carries `tool_schema_version: 1`; closes brief AC #4 by asserting both the literal substring `"_meta":{"tool_schema_version":1}` in the canonical JSON AND that every tool's in-memory meta dict matches the module constant.

- **`TestUpdateProcedure`** (5 tests): bumping a tool description changes the hash (closes brief AC #2); the rewrite helper is idempotent when the hash is unchanged; the `UPDATE-ANCHOR` regex finds exactly one match in the file; `_serialize_tools` is byte-deterministic across runs; the live tool list contains all 7 tools.

Helpers exposed:
- `_serialize_tools(tools)` — canonical JSON form of `[t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in tools]` wrapped in `{"tools": [...]}`. `by_alias=True` is critical so `meta` aliases to the wire form `_meta`. `exclude_none=True` strips MCP-SDK-version-sensitive nullable noise (`outputSchema`, `annotations`, `icons`, `title`).
- `compute_tool_schema_hash(tools)` — `sha256` over UTF-8 of the canonical JSON.
- `_rewrite_pinned_hash(new_hash)` — anchored regex rewrite of `EXPECTED_TOOL_SCHEMA_SHA256`. Idempotent (returns False if value unchanged) and unambiguous (the `UPDATE-ANCHOR` sentinel guarantees the regex hits exactly one literal in the file).

### MODIFIED: `tests/conftest.py`

Added `--update-tool-schema-hash` flag via `pytest_addoption` — mirrors the existing `--ndcg-min` recipe (lines 33-43). Help text explains: CI never sets this flag; a hash drift in CI is a BP1 prompt-cache invalidation signal.

### NOT MODIFIED: `server/tools.py`

The brief listed `server/tools.py` as a deliverable ("updated with `tool_schema_version: int = 1` field in the `tools/list` response"). Verified during research (see `research-brief-1.md` § 1, "Tool surface (already shipped by E06_S03)"): `TOOL_SCHEMA_VERSION = 1` already exists at `server/tools.py:64` and `register_all` at `server/tools.py:359-398` already passes `meta={"tool_schema_version": TOOL_SCHEMA_VERSION}` into FastMCP's `add_tool`. The wire `_meta` field is on the `tools/list` response. Re-debating top-level vs per-tool `_meta` was explicitly resolved by E06_S03 research-brief-2 lines 235-245.

The `TestSchemaVersionMetaSurface` class makes that prior wiring visible by asserting the literal substring in the canonical JSON, so brief AC #4 has a dedicated test.

## Acceptance criteria

| AC | Status | Evidence |
|---|---|---|
| `pytest tests/test_server_tool_schema.py` passes | met | 8 passed (running without flag) |
| Changing a tool description fails the test | met | `TestUpdateProcedure::test_changing_tool_description_changes_hash` simulates the bump and asserts inequality with the pin |
| `pytest --update-tool-schema-hash` regenerates the constant | met | Verified in this session: started with 64-char zero literal; the flag rewrote it to `4623e8988f...18fd41`; subsequent runs without the flag pass |
| `tool_schema_version: 1` in `tools/list` response | met | `TestSchemaVersionMetaSurface` asserts the literal substring AND in-memory equality with `TOOL_SCHEMA_VERSION` |

## Deviation from the brief

The brief listed `server/tools.py` as a deliverable; we did not modify it because the wiring it asks for already exists (E06_S03 shipped `TOOL_SCHEMA_VERSION` + per-tool `_meta`). The synthesis brief documents this in § 2 ("Prior decisions and lessons"). Adding a top-level `tool_schema_version` field to `ListToolsResult` would require subclassing the FastMCP lowlevel server's `tools/list` handler for one int — gold-plating, vs. the spec-blessed per-tool `_meta` slot which is already on the wire.

The pinned hash at ship time: `4623e8988f8346da38eaa882303da7a4ef5a4c9a6c13211d867a04c50018fd41`.

## External writes the orchestrator must authorize

None. Purely-internal test milestone. The `--update-tool-schema-hash` flag rewrites a local file in place when invoked manually; CI never sets the flag.

## Project check command

`ruff check .` — clean.
`pytest -q` — **791 passed, 3 skipped** (was 783 pre-milestone — +8 from this milestone).
