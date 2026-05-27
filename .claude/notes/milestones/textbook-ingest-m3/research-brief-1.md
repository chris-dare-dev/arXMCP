# Research Brief — textbook-ingest-m3

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-27T23:30:00Z

---

## In-codebase context

### EXPECTED_TOOL_SCHEMA_SHA256

File: `tests/test_server_tool_schema.py` lines 94–96.

Current pinned value:
```
EXPECTED_TOOL_SCHEMA_SHA256: str = (  # UPDATE-ANCHOR — do not delete
    "1d0abfe94a53230c3976bf16f418011884234662f7d4434256416782f0e00140"
)
EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH: int = 12  # VERSION-ANCHOR — do not delete
```

What bytes are hashed (lines 41–46):
```python
payload = {"tools": [t.model_dump(mode="json", by_alias=True,
                                   exclude_none=True)
                      for t in tools]}
canonical = json.dumps(payload, sort_keys=True,
                       separators=(",", ":"), ensure_ascii=True)
sha256(canonical.encode("utf-8")).hexdigest()
```

The `tools` list comes from `register_all()`-populated `ALL_TOOLS`. The
`inputSchema` is derived by FastMCP from handler typed signatures. The
`search_papers_result.json` schema file does NOT flow into the `tools/list`
hash — it is a separately versioned output-schema document that FastMCP does
not embed in `tools/list`. **The m1 edits to `search_papers_result.json`
(updated `chunk_id.pattern`) do NOT change the `tools/list` hash.**

Regeneration tooling:
```
pytest tests/test_server_tool_schema.py --update-tool-schema-hash
```
The flag rewrites the `EXPECTED_TOOL_SCHEMA_SHA256` literal in-place.
It REFUSES to proceed if `TOOL_SCHEMA_VERSION` was not bumped from
`EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` first (F2 guard from E06_S06).

Current `TOOL_SCHEMA_VERSION = 12` in `server/tools.py`.

### EXPECTED_BP1_SHA256

File: `tests/test_prompts.py` lines 632–634.

Current pinned value:
```
EXPECTED_BP1_SHA256 = (
    "1162e998fab9637a2ddbf4423ac8e84d439bff24ff26842cac3860cc460938ed"
)
```

What bytes are hashed (`_bp1_hash`, lines 506–513):
```python
bp1 = {"system": req["system"], "tools": req["tools"]}
return hashlib.sha256(_canonical_json(bp1)).hexdigest()
```

BP1 = `{"system": <SYSTEM_PROMPT as list-of-content-blocks>, "tools": <ALL_TOOLS
serialized via model_dump>}`. Any change to `SYSTEM_PROMPT` in
`server/prompts.py` OR any change to `ALL_TOOLS` in `server/tools.py` drifts
this hash. Regeneration: **manual** — edit the `EXPECTED_BP1_SHA256` literal
directly (no flag; test prints the observed value on failure).

### SYSTEM_PROMPT — current state

File: `server/prompts.py` lines 113–116:
```python
SYSTEM_PROMPT: str = (
    "<placeholder system prompt — E08_S04 will author the v1 body. "
    "This text is byte-stable but informationally a no-op for v1.>"
)
```

`SYSTEM_PROMPT` is still the E08_S04 placeholder. It carries zero
textbook-aware language. The module docstring says "BP1 (system + tool
definitions) is BYTE-IDENTICAL across all four roles." Any edit to
`SYSTEM_PROMPT` drifts BOTH `EXPECTED_BP1_SHA256` (directly) and,
indirectly, `EXPECTED_TOOL_SCHEMA_SHA256` does NOT drift (tool schema hash
only covers `ALL_TOOLS`, not the system prompt). They are SEPARATE hashes.

**The brief says "schema description edits, key-ordering, and BP1 prompt-prefix
edits all bundle into this one commit."** For BP1 to actually drift in m3, at
least one of these must change: `SYSTEM_PROMPT` or `ALL_TOOLS` descriptions.

### ALL_TOOLS — what m1 and m2 actually changed on the MCP surface

m1 (`feat(ingest): textbook chunk-id regex`) and m2 (`feat(ingest):
chunks-schema migration for textbook`) are both INGEST-side changes. Neither
touched `server/tools.py::ALL_TOOLS` nor any `ToolMeta` description.
`server/schemas/search_papers_result.json` was updated in m1 (chunk_id pattern
dual-prefix), but that file is NOT embedded in `tools/list` — it is a
separately-consulted output schema.

**Conclusion: at current HEAD, `tools/list` hash has NOT drifted from the m1
baseline. `EXPECTED_TOOL_SCHEMA_SHA256` currently PASSES without change.**

For the brief's intent to be realized, m3 must ADD something to the MCP
surface. The brief explicitly calls for "schema description edits" — the only
meaningful addition is a textbook-aware update to one or more `ToolMeta`
descriptions in `server/tools.py`. The `SEARCH_PAPERS` description currently
documents `arxiv` format paper_ids in the filters arg but says nothing about
textbook paper_ids (`textbook:<slug>`). That is the natural edit.

### `server/routes/notebooks.py` — notebook schema

`NotebookCreate` (lines 185–198):
```python
class NotebookCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=256)
```

No `notebook_kind` field exists. The SQLite schema in `server/notebooks_store.py`
(the `notebooks` table) has columns: `slug, display_name, lancedb_path,
created_at`. Current `SCHEMA_VERSION = 2`. The v1→v2 migration (m9) added
`notebook_ingest_runs` as a CREATE TABLE IF NOT EXISTS additive migration.

The migration pattern is documented (lines 57–68):
> When adding a new version: append a new `if current_version < N:` block in
> `_open_sync` using `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE` and bump
> SCHEMA_VERSION; do NOT drop existing tables.

**`notebook_kind` requires SCHEMA_VERSION bump to 3 and an `ALTER TABLE
notebooks ADD COLUMN notebook_kind TEXT NOT NULL DEFAULT 'arxiv'` migration.**
This is the additive-migration path — no data loss, existing rows get
`notebook_kind='arxiv'` via SQLite DEFAULT.

The route response (e.g., `list_notebooks` at line 207–213) returns:
```python
{"slug": r[0], "display_name": r[1], "lancedb_path": r[2], "created_at": r[3]}
```
This will need to include `notebook_kind` after the migration.

### 07-multi-agent-caching.md — load-bearing BP1 rule

From lines 40–48:
> **Property 1: Tool definitions are byte-stable**
>
> Pin tool JSON schemas. Sort properties alphabetically at serialization time.
> Freeze descriptions as constants in source. A casual edit to a tool description
> blows every sub-agent's cache.
>
> Implementation: a single `tools.py` module with frozen dataclasses + a unit
> test that asserts `sha256(serialize_tools()) == EXPECTED_HASH`. Bump the hash
> deliberately when intentionally changing schema; treat as an API version bump.

From lines 74–76:
> **Breakpoint 1 (BP1, 1-hour TTL):** end of system prompt + tool definitions
> block. Byte-identical across every agent role because roles are encoded as a
> ≤50-token prefix in the first *user* turn (not as per-role system prompts).

The constraint is clear: any description edit to `ALL_TOOLS` or any edit to
`SYSTEM_PROMPT` must be paired with `TOOL_SCHEMA_VERSION` bump + re-pin.

### prompts-bp-discipline.md — where to document the textbook-family bump

The doc has no existing "version history" or "re-pin episodes" section. The
closest anchor is the "Cross-references" section at the bottom. A new section
"## Textbook-family BP1 bump (textbook-ingest-m3)" appended before
cross-references documents the bump episode, what changed, and why it was
intentional. That is the natural insertion point.

---

## Prior decisions and lessons

Last `EXPECTED_TOOL_SCHEMA_SHA256` re-pin: `853011e feat(server): lean_verify
MCP tool (verification-feedback-m3)` — bumped TOOL_SCHEMA_VERSION 11→12 because
the 8th tool (`lean_verify`) was added to `ALL_TOOLS`. The paired BP1 re-pin
happened in the SAME commit (both test files changed together, confirming the
"bundle into one commit" precedent the brief calls for).

Last `EXPECTED_BP1_SHA256` re-pin: same `853011e` commit — the comment in
`test_prompts.py` lines 627–631 records:
> "v12: verification-feedback-m3 — added the `lean_verify` tool (8th in
> ALL_TOOLS). Adding a tool drifts the tools-array bytes, which drifts BP1
> (system + tools). Re-pinned in lockstep with EXPECTED_TOOL_SCHEMA_SHA256."

**Precedent for re-pinning BOTH in the same commit: YES, confirmed.**
`853011e` changed both `tests/test_server_tool_schema.py` and `tests/test_prompts.py`
in one commit.

`SYSTEM_PROMPT` has NEVER been populated beyond the placeholder. The E08_S04
TODO has not landed as of the current HEAD.

---

## External sources

No vendor docs relevant. The `search_papers_result.json` schema (updated in m1)
is local. The `CHUNK_ID_PATTERN` and `PAPER_ID_PATTERN` regexes are internal.
The BP1/tool-schema pin mechanism is fully documented locally in
`07-multi-agent-caching.md` and `prompts-bp-discipline.md`. No external fetches
required for this milestone.

---

## Recommendation

**Perform three coordinated edits in one `rect`-style commit:**

1. **Edit `server/tools.py` SEARCH_PAPERS description** to document the
   textbook paper_id format in the `filters` argument: replace
   `"each validated against the arXiv format"` with `"each validated against
   the arXiv or textbook:<slug> format"`. This is the minimum semantically
   meaningful change that reflects the m1 identifier expansion and gives the
   description edit a real reason to exist.  Bump `TOOL_SCHEMA_VERSION` 12→13.

2. **Run `pytest tests/test_server_tool_schema.py --update-tool-schema-hash`**
   to re-pin `EXPECTED_TOOL_SCHEMA_SHA256`. Update `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`
   to 13. Then manually update `EXPECTED_BP1_SHA256` in `tests/test_prompts.py`
   to the value the test prints (BP1 drifts because `ALL_TOOLS` changed).

3. **Add `notebook_kind` to `server/routes/notebooks.py` and
   `server/notebooks_store.py`:**
   - `NotebookCreate`: add `notebook_kind: str = Field(default="arxiv",
     pattern="^(arxiv|textbook)$")` — Pydantic pattern validation prevents
     `notebook_kind="invalid_value"` (closes failure mode 3).
   - `NotebooksStore`: bump `SCHEMA_VERSION` 2→3, add
     `ALTER TABLE notebooks ADD COLUMN notebook_kind TEXT NOT NULL DEFAULT 'arxiv'`
     in a `if current_version < 3` block.
   - `create_notebook`, `list_notebooks`, `get_notebook`: thread `notebook_kind`
     through SELECT/INSERT and return dict.
   - `NotebookCreate.notebook_kind` is a **write-path default** (`"arxiv"` if
     not supplied). The read-path migration (ALTER TABLE DEFAULT 'arxiv') is the
     **read-path migration** for existing rows on disk. Both behaviors are needed.

4. **Update `prompts-bp-discipline.md`**: add a new section documenting the
   textbook-family bump (what changed, why intentional, the new SHA values).

Do NOT touch `SYSTEM_PROMPT`. Adding textbook language there would be
aspirational and risk breaking the 50-token-per-role prefix invariants. The
SEARCH_PAPERS description edit is the right minimal surface.

---

## Open questions

No open questions — implementation can proceed on the above recommendation.

The only ambiguity ("does the tool-schema hash actually need to change?") is
resolved: it does, because the SEARCH_PAPERS description edit is semantically
correct (the `filters` arg now accepts `textbook:<slug>` IDs from m1) and
provides the justification for the TOOL_SCHEMA_VERSION bump.

---

## Failure modes

1. **EXPECTED_TOOL_SCHEMA_SHA256 re-pinned without bumping TOOL_SCHEMA_VERSION
   first.** Trigger: running `--update-tool-schema-hash` before editing
   `TOOL_SCHEMA_VERSION`. Symptom: the flag REFUSES with "version not bumped"
   error (F2 guard, lines 380–382 in test_server_tool_schema.py). Mitigation:
   bump `TOOL_SCHEMA_VERSION` 12→13 first, then run the flag.

2. **BP1 hash drifts on Linux due to dict ordering in `_canonical_json`.** The
   hash function uses `json.dumps(..., sort_keys=True)` and `ensure_ascii=True`
   (lines 45–60 of test_server_tool_schema.py). These two flags make the output
   deterministic across platforms. No platform-specific hash risk.

3. **`notebook_kind` field added but not validated.** Trigger: adding it as a
   bare `str` without a Pydantic `pattern` constraint. Symptom: operator can
   persist `notebook_kind="freeform-garbage"`. Mitigation: use
   `Field(default="arxiv", pattern="^(arxiv|textbook)$")`.

4. **Existing `notebooks.db` files lack `notebook_kind` column; read path raises
   `sqlite3.OperationalError` ("no such column: notebook_kind").** Trigger: server
   restarts against an existing DB before the migration runs. Mitigation: the
   `if current_version < 3: ALTER TABLE ...` block in `_open_sync` runs on every
   connection open before any queries execute — this is the correct ordering.

5. **`prompts-bp-discipline.md` doc updated but `EXPECTED_BP1_SHA256` test
   literal missed.** Trigger: implementer documents the bump but forgets to
   re-pin the literal in `test_prompts.py`. Symptom: `test_bp1_hash_pinned`
   fails in CI (or on `make test`). Mitigation: pin the literal LAST in the
   sequence after all code edits are staged, run `make test` before committing.

6. **`KMP_DUPLICATE_LIB_OK=TRUE` removed from `tests/conftest.py`.** Not a
   risk from m3's changes specifically, but any test-file addition that imports
   torch/faiss must not omit the autouse fixture. Confirmed: `tests/conftest.py`
   sets this via an autouse session fixture; m3 adds no new conftest.

---

## External writes the implementation will require

None — this milestone is purely local.
