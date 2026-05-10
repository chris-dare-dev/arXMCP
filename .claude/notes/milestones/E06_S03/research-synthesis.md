# E06_S03 — Research Synthesis

**Inputs:** `research-brief-1.md`, `research-brief-2.md` (both
Sonnet, parallel). Strong convergence on most decisions. The
disagreements are around AGGRESSIVENESS — R1 prefers stubs for
tools where backing infrastructure is incomplete; R2 prefers
best-effort implementations using whatever data is at hand. R2's
position wins on 4 of the 5 disputed tools; R1's wins on
`cite_neighbors` (no graph data anywhere).

---

## D1 — Cross-epic dependency strategy: best-effort where infrastructure exists

**Both briefs agree** that `find_equation`'s "graceful fallback"
pattern from the brief generalizes to other tools. They diverge on
how aggressively to apply it.

**Decision (per-tool):**

| Tool | Strategy | Backing data |
|---|---|---|
| `search_papers` | best-effort | dense-only ANN over `embedding_stmt` (E07 RRF deferred) |
| `get_chunk` | best-effort | direct LanceDB lookup by chunk_id |
| `find_equation` | best-effort | per the brief — dense over `embedding_stmt` (NOT `embedding_eq`, always NULL pre-E10) |
| `get_definitions` | best-effort | read `var/arxmcp/corpus/preamble/<paper_id>/preamble.json` (`PreambleDoc.macros` exists; verified) |
| `find_lemma_by_name` | best-effort | in-memory substring scan over `chunks_table` filtered by `theorem_name IS NOT NULL` (50-paper corpus is small enough) |
| `get_paper` | best-effort | synthesize from `chunks_table` group-by-paper; null-fields for `authors/title/year/categories` (no metadata source today) |
| `cite_neighbors` | stub | empty `neighbors: []` + `infrastructure_status: "deferred"` (no Kùzu graph anywhere) |

The "best-effort" tools include a status field in the
structuredContent (e.g. `retrieval_mode: "dense_only"`,
`metadata_status: "synthesized_from_chunks"`,
`infrastructure_status: "deferred"`) so the agent runtime knows
what it's getting. Tool descriptions in `server/tools.py` are
frozen at module load and do NOT interpolate runtime state (per
BP1 byte-stability).

## D2 — Schema definition: typed handler signatures + frozen description constants

**Disagreement, R1's position wins.**

R1: typed Python functions registered via `@mcp.tool()`; FastMCP
auto-derives the schema from `Annotated[T, pydantic.Field(...)]`
parameters. The frozen dataclasses live as
*description constants* (immutability for byte-stability), NOT
JSON Schema dicts.

R2: hand-author JSON Schema dicts in frozen dataclasses, bypass
FastMCP's schema derivation by writing to `_tool_manager._tools`
or subclassing `FastMCP` and overriding `list_tools`.

R1 wins because:
- Bypassing `_tool_manager` reaches into private API. Subclassing
  FastMCP fragments the integration.
- The brief's "frozen Python dataclasses" requirement is satisfied
  by frozen `name + description` constants — the byte-stability
  guarantee comes from the SERIALIZATION (sort_keys + pinned
  hash in E06_S06), not from the schema author identity.
- FastMCP's signature-derived schemas are deterministic across
  restarts as long as the function signatures are pinned.

**Decision:**
- `server/tools.py` exports a `@dataclass(frozen=True) class ToolMeta`
  with `name: str` + `description: str` constants for each tool.
- Each tool handler is a typed function in `server/handlers/<name>.py`.
- Registration: `mcp_server.add_tool(handler_fn, name=meta.name,
  description=meta.description)` in `server/tools.py::register_all`.
- E06_S06 will land the byte-stability test that hashes the
  rendered `tools/list` and pins the SHA-256.

## D3 — `tool_schema_version: int` lives in per-tool `_meta`

**Both briefs agree.** The MCP spec has no top-level
`tool_schema_version` slot. Per-tool `_meta: {"tool_schema_version":
TOOL_SCHEMA_VERSION}` is spec-compliant (clients ignoring `_meta`
just see the canonical schema).

**Decision:**
- `TOOL_SCHEMA_VERSION: int = 1` module-level constant in
  `server/tools.py`.
- Surfaced via FastMCP's `add_tool(..., annotations=...)` or by
  patching the `_tool_manager._tools[name].annotations` post-add
  (whichever the FastMCP 1.27 API supports cleanly — verified at
  implement time).
- Manual bump on any schema change; E06_S06 tests catch the gap.

## D4 — `papers` table for `get_paper`: synthesize from chunks today

**Both briefs agree** that no `papers` table exists in the v1
schema. R2's recommendation: synthesize from `chunks_table`
group-by-paper and return null for fields the schema doesn't
carry (`authors`, `title`, `year`, `categories`, `abstract`).
Add a `metadata_status: "synthesized_from_chunks"` flag.

**Decision:** synthesize. Stable API for when E11/E12 lands a real
papers table; the implementation swaps without an external
contract change.

## D5 — `find_lemma_by_name`: in-memory substring scan today

**Disagreement, R2's position wins.** R1 says defer (raise
ToolNotImplementedError). R2 says scan `chunks_table.to_arrow()`
filtered by `theorem_name IS NOT NULL`, in-memory case-insensitive
substring match.

R2 wins because:
- The 50-paper corpus has at most a few hundred theorems with
  names; in-memory scan is sub-millisecond.
- Returning `isError` violates the AC "All 7 tool smoke tests pass
  against the seed corpus."
- The handler's interface stays stable when E10_S02's FTS5 ships;
  swap is internal.

**Decision:** in-memory scan with a `retrieval_mode: "in_memory_scan"`
flag; document the FTS5 swap as future work.

## D6 — `cite_neighbors`: empty stub today

**Both briefs agree.** Kùzu citation graph (E09) doesn't exist;
intra-paper theorem dependency parser (for `direction=
"depends_on"`) doesn't exist. No best-effort path.

**Decision:** return `{neighbors: [], infrastructure_status:
"deferred", note: "citation graph (E09) not yet built"}`. Schema
validates; agent runtime sees a clean empty result.

## D7 — Test strategy: tmp_path LanceDB seeded by `write_chunks`

**Both briefs agree** with the E06_S01 precedent. The
literal "50-paper seed corpus" AC isn't satisfiable today (no
ingested artifact exists); rephrase as "smoke tests against a
synthetic 2-5-chunk corpus exercising every code path" + an
env-gated `ARXMCP_RUN_SEED_CORPUS_SMOKE=1` test for the future.

**Decision:**
- `tests/test_tools_all.py` uses the `_seed_corpus(lancedb_path)`
  helper from `tests/test_server_startup.py` (or a sibling that
  seeds 5 chunks across 2 papers with a theorem_name on at least
  one chunk).
- Mocks BGE-M3 via the existing `mocked_bge_m3` fixture.
- Calls each tool via the FastAPI TestClient against the mounted
  /mcp endpoint. The mcp library's session-manager lifespan must
  fire (per E06_S01 F2 fix).

## D8 — `corpus_version` field in every result

**Both briefs agree.** Source from
`app.state.resources.corpus_info.version`. Wire via a
module-level reference set during the lifespan startup.

**Decision:** `server/tools.py` exports a
`set_resources(r: Resources) -> None` hook called from the
lifespan AFTER `Resources.startup()`. Handlers read
`_resources.corpus_info.version` directly. A `_envelope(payload)`
helper injects `corpus_version` at the structuredContent root.

## D9 — Body-size cap enforcement per-handler

**Both briefs agree.** The E06_S01 `BodySizeCapMiddleware` exempts
`/mcp` (because Streamable-HTTP SSE chunks defeat buffering — and
even with `json_response=True`, the middleware still exempts the
prefix). So per-handler enforcement is the only path.

**Decision:**
- `server/tools.py` exports `_enforce_byte_cap(structuredContent)
  -> structuredContent_or_resource_link`.
- For `get_chunk` specifically: if `len(json.dumps(sc)) >
  result_byte_cap`, replace body with a truncated `body_text` +
  `body_truncated: True` flag, and add a `resource_link` to the
  `content` array pointing at `arxmcp://chunks/<chunk_id>`.
- Other tools' results are bounded by their own logic (top-k for
  search, single row for paper); the cap is enforced
  defensively.

## D10 — Sort order: `(score_desc, chunk_id_asc)`

**Both briefs agree** per the design constitution. Ties broken
deterministically.

**Decision:** every list-returning handler sorts by
`(-score, chunk_id)` before truncating to `k` and serializing.

## D11 — Tool registration order

**R2 flagged this; R1 confirmed.** Tool registration MUST happen
in `create_app()` BEFORE `mount_mcp(app, mcp_server)`, because
`streamable_http_app()` snapshots the registered tools when called.

**Decision:** modify `server/main.py::create_app` to call
`server.tools.register_all(mcp_server)` between `FastMCP("arxmcp",
json_response=True)` and `mount_mcp(app, mcp_server)`.

## D12 — JSON Schema Draft-07 conformance

**R2 flagged a real risk.** Pydantic v2's `model_json_schema()`
defaults to JSON Schema 2020-12, NOT Draft-07. The AC requires
Draft-07 conformance. Differences for our tool schemas:
- `$defs` (2020-12) vs `definitions` (Draft-07)
- `prefixItems` (2020-12) vs `items` array form (Draft-07)
- `$dynamicRef` / `$dynamicAnchor` (2020-12 only)

For the simple inputSchemas in this milestone (strings, integers,
enums, nested objects with primitive fields), most differences
won't appear in practice. But the test must validate explicitly.

**Decision:**
- Add a unit test in `tests/test_tools_all.py` that uses
  `jsonschema.Draft7Validator.check_schema(...)` on each tool's
  inputSchema.
- If FastMCP-generated schemas use Draft-2020-12-only constructs,
  post-process via a small shim (`_draft7_compatible(schema)`)
  in `server/tools.py` that rewrites `$defs` → `definitions` etc.
  Apply the shim at registration time.
- Verify post-process is necessary or skip if FastMCP's output is
  already Draft-07-compatible for our parameter types.

## File layout

```
server/tools.py               # NEW: ToolMeta dataclasses, TOOL_SCHEMA_VERSION,
                              #   register_all(mcp_server), set_resources(r),
                              #   _envelope(payload), _enforce_byte_cap(...)
server/handlers/__init__.py   # NEW: empty pkg marker
server/handlers/search.py     # NEW: search_papers handler (dense-only)
server/handlers/chunk.py      # NEW: get_chunk handler
server/handlers/equation.py   # NEW: find_equation handler (dense-only)
server/handlers/definitions.py # NEW: get_definitions handler (preamble.json)
server/handlers/lemma.py      # NEW: find_lemma_by_name handler (in-memory scan)
server/handlers/paper.py      # NEW: get_paper handler (synthesized)
server/handlers/citations.py  # NEW: cite_neighbors handler (empty stub)
server/main.py                # MODIFIED: insert register_all + set_resources calls
tests/test_tools_all.py       # NEW: schema-shape unit tests + tools/call smoke tests
```

## Open questions (residual)

**None blocking implementation.** The synthesis above locks every
disputed decision.

**Cross-cutting concern noted in both briefs:** the brief's AC
"All 7 tool smoke tests pass against the 50-paper seed corpus" is
literally unsatisfiable today (no ingested seed corpus). The
synthesis interprets this as "smoke tests pass against a
synthetic-but-representative corpus" + an env-gated escape hatch
for the literal-50-paper case. Document in implementation summary;
the literal AC closes when the operator runs the ingest pipeline
against `tools/seed-papers.txt` per E05_S01's
`docs/eval-curation.md`.

## External writes the implementation will require

**None.** All deliverables are local commits. The `pip install -e .`
re-run is a developer-machine action. No git push, no PR, no
infra mutation, no third-party API call.
