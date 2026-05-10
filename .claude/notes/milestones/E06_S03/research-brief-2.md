# E06_S03 — Research Brief 2 (7 MCP tools)

Researcher: parallel-2 (independent of brief-1).

## 1. In-codebase context

**Server skeleton (E06_S01) is in place and load-bearing for this milestone.**
- `server/main.py` constructs `FastMCP("arxmcp", json_response=True)` and
  mounts via `mount_mcp(app, mcp_server)` at `/mcp/`. The instance is
  stashed on `app.state.mcp_server` and its session-manager lifespan is
  threaded into the parent lifespan. **Tool registration must happen
  during `create_app()` BEFORE `mount_mcp` is invoked** (or at least
  before the lifespan opens), because `streamable_http_app()` snapshots
  the registered tools when called. Today `create_app()` calls
  `FastMCP("arxmcp", json_response=True)` and immediately mounts — so
  E06_S03 needs to insert a `register_tools(mcp_server, app.state)` call
  between the construct and the mount, or have `register_tools` operate
  on the already-mounted server (FastMCP supports `add_tool` post-init,
  but the byte-stable tools/list response depends on registration order
  being deterministic).
- `server/resources.py` exposes `Resources` on `app.state.resources`:
  - `config: Config` — env vars
  - `corpus_info: CorpusVersionInfo` — `.version: int` is the
    `corpus_version` to embed in every result
  - `chunks_table` — pinned LanceDB Table handle (live
    `dataset.checkout(version=N)` view; supports `to_arrow`, `search`,
    `count_rows`, scalar predicate filtering)
  - `embed_semaphore` (8), `rerank_semaphore` (4), `rerank_singleflight`
  - `reranker_model` (None until E07 ships)
- `server/query_encoder.encode_query(text)` — async, singleflight-wrapped,
  returns L2-normalized `np.ndarray[float32]` of dim 1024. Already
  semaphore-aware via callers (handlers must `async with
  resources.embed_semaphore:` BEFORE awaiting `encode_query`, matching
  the two-tier discipline documented in `resources.py`'s docstring).
- The chunks table v1 schema (`ingest/schema.py CHUNKS_SCHEMA_V1`) has
  these columns useful for E06_S03: `chunk_id, paper_id, kind,
  section_path, theorem_name, theorem_label, body_text, body_tokens,
  embedding_stmt, embedding_proof, embedding_eq (always NULL pre-E10),
  chunker_version, embedder_version, preamble_ref`. **No `version`
  column on the chunk table** — the per-chunk `version: 3` shown in the
  notes example for `search_papers` results is paper-version, which is
  NOT in the schema. Either drop the field or default it to a constant
  (e.g., `1`) for v1. The notes example also shows a `label: "Theorem
  3.4"` field that combines `theorem_name` + `theorem_label`, and a
  `score` field — both must be synthesized in the handler.

**FastMCP `@tool()` decorator (mcp 1.27, verified in
`.venv/lib/.../mcp/server/fastmcp/tools/base.py`).** `Tool.from_function`
calls `func_metadata(fn)` which builds a Pydantic v2 arg model from the
function signature; `parameters = arg_model.model_json_schema(by_alias=True)`
becomes the wire `inputSchema`. `outputSchema` is auto-derived from the
return annotation when present (configurable via `structured_output=True/False/None`
on `add_tool`/`@tool()`). **There is NO `inputSchema=` kwarg on `@tool()` —
the decorator does NOT accept an explicit schema.** This is the central
constraint for the brief's "frozen Python dataclasses in `server/tools.py`"
requirement: dataclasses do NOT plug into FastMCP's schema derivation
path. To produce byte-stable schemas you have two options (see Open
Question (b)).

`tools/list` is implemented at `FastMCP.list_tools()` (server.py:315) and
returns `list[MCPTool]`. **There is no spec/library hook for a top-level
`tool_schema_version` integer in the `tools/list` response** — see Open
Question (c).

**Body-size cap.** `BodySizeCapMiddleware` exempts `/mcp` (because
Streamable-HTTP SSE chunks defeat measurement) — so the 256 KB cap is NOT
enforced on tool responses today. We must enforce it in-handler
(measure `len(json.dumps(structuredContent))` before returning, return a
`resource_link` if exceeded). This affects `get_chunk` most directly.

**`server/_mcp_mount.py`** is intentionally tiny and just configures
`streamable_http_path = "/"` then mounts. Tool registration is `server/tools.py`'s
job, NOT the mount module's.

**Test patterns from E06_S01.** `tests/test_server_startup.py` defines a
`_seed_corpus(lancedb_path)` helper that ingests a tiny 2-chunk corpus
via `ingest.store.write_chunks` against `tmp_path`, with random
embeddings. The `mocked_bge_m3` fixture monkeypatches `_get_model` and
`_get_tokenizer` so tests run without the BGE-M3 weights download. Smoke
tests for E06_S03 should use the same shape: tmp_path LanceDB seeded by
`write_chunks`, mocked BGE-M3, in-process FastAPI client via
`fastapi.testclient.TestClient`.

## 2. Prior decisions and lessons

- **E06_S01:** `Resources` container shipped; `chunks_table` is the canonical
  read-only handle. `enable_rerank=True` is FATAL until E07 — handlers
  must NOT call the reranker; they may dense-only.
- **E06_S02:** shim does byte-pass-through and the server is configured
  `json_response=True` so tool responses are single-shot
  `application/json`. **Crucial for handlers:** the `structuredContent`
  dict must be JSON-serializable AND keys at every level must be
  output-deterministic for the BP1 byte-stability guarantee. Use
  `dict()` ordering (Python 3.7+) but build dicts in alphabetical key
  order on the way out, or pass `sort_keys=True` to whatever serializer
  the framework uses. (FastMCP serializes via Pydantic; `model_dump_json`
  does NOT sort keys by default. Recommend assembling dicts with
  pre-sorted keys via `dict(sorted(items))`.)
- **E06_S04 (NEXT, depends on us):** locks `search_papers` result shape
  to `snippet ≤150 chars, NO summary, resource_link in content array`,
  and writes `server/schemas/search_papers_result.json`. We should ship
  the snippet truncation (≤150 chars from `body_text`) NOW so E06_S04
  can focus on the JSON Schema file, not the retrofit.
- **256 KB cap from E06_S01:** `/mcp` is exempt at the middleware
  layer. So `get_chunk` returning a 200 KB body_text is accepted by the
  middleware but would still violate the cap policy. Recommended:
  per-handler `_enforce_byte_cap(structured_content) -> structured_content_or_resource_link`
  helper. If `len(json.dumps(sc)) > config.result_byte_cap`, return a
  truncated `structuredContent` with a `resource_link` to
  `arxmcp://chunks/<chunk_id>` in `content` and a
  `body_truncated: True` flag in the structured payload.
- **Cross-epic dependency reality:** E07_S01 (BM25), E07_S02 (RRF), E10_S03
  (equation TED index), E09 (Kùzu citation graph), and the FTS5 lemma
  index do NOT exist. The `papers` table does NOT exist (only the
  `chunks` table is in v1 schema). The `definitions`/notation table
  does NOT exist (preamble macros are in `var/arxmcp/corpus/preamble/<paper_id>/preamble.json`
  via `PreambleDoc`, but no in-table representation).
- **The brief's "graceful fallback to dense-only" pattern for
  `find_equation`** is the model. Apply the same logic across the suite:
  every handler ships now, but the ones whose backing infrastructure is
  missing return a deterministic empty/best-effort result with a
  warning in `structuredContent`.

## 3. External sources

**MCP 2025-06-18 spec (`https://modelcontextprotocol.io/specification/2025-06-18`):**

- `tools/list` returns `{tools: [Tool], nextCursor?: string}`. The `Tool`
  object has: `name, description?, inputSchema (JSON Schema Draft-07),
  outputSchema?, annotations?, _meta?`. There is NO top-level
  `tool_schema_version` slot. The brief's `tool_schema_version` integer
  has to live somewhere — see Open Question (c).
- `inputSchema` MUST be a JSON Schema Draft-07 object. Pydantic v2's
  `model_json_schema()` produces 2020-12 by default; FastMCP's path
  through `model_json_schema(by_alias=True)` does the same. **This is a
  potential AC-failure risk:** "Each tool's JSON schema validates
  correctly against JSON Schema Draft-07" requires either (1) post-
  processing the Pydantic-generated schemas to strip 2020-12-only
  features, OR (2) writing JSON Schema Draft-07 dicts by hand and
  bypassing Pydantic's auto-derivation. Concrete remediation: replace
  `$defs` with `definitions`, replace `prefixItems` with `items` array
  form, drop `$dynamicRef`/`$dynamicAnchor`. For the simple tool
  schemas in this milestone (strings, integers, enums, nested objects)
  the differences are minor.
- `tools/call` response is `CallToolResult { content: ContentBlock[],
  structuredContent?: dict, isError?: bool, _meta? }`. `ContentBlock`
  union includes `TextContent | ImageContent | AudioContent |
  ResourceLink | EmbeddedResource`. `ResourceLink` has `type:
  "resource_link"` and `uri` (plus `name`, `description`, `mimeType`).
- Spec quote on tool errors: "If an error occurs while invoking the tool
  (e.g., invalid arguments, unknown tool name), the response MUST be a
  JSON-RPC error." Distinguish protocol-level errors (raise an exception
  → JSON-RPC error) from tool-execution errors (return
  `{isError: true, content: [TextContent(error message)]}`). Pydantic
  validation errors raised from the handler propagate as MCP errors.

**FastMCP behavior (mcp==1.27.x, verified in venv):**
`@FastMCP.tool()` synthesizes `inputSchema` from the function signature
via `pydantic.TypeAdapter` on each parameter (constructed in
`func_metadata.func_metadata()`). Descriptions come from `__doc__` (the
docstring). To get byte-stable schemas across server restarts, the
docstring + parameter annotations + parameter defaults + parameter ORDER
in the signature ALL contribute to the hash. **Recommendation:** define
each tool function with annotations only; put the human-readable
description in the `description=` kwarg of `@tool()` (a string constant
imported from `server/tools.py`); avoid Pydantic `Field(...)`
descriptions inline because future ruff autoformat passes can rewrite
them.

## Open questions (opinionated)

**(a) Cross-epic dependency strategy.** Pick option (iii) for tools
where infrastructure exists, option (ii) for tools where it does not,
matching the brief's `find_equation` precedent:
- `search_papers`: option (iii). Phase-1 BM25 not shipped → use
  dense-only via `chunks_table.search(query_vec).limit(k)` over both
  `embedding_stmt` and `embedding_proof`, naive max-score fusion. When
  `level="paper"`, group by `paper_id` and emit one row per paper
  (dedupe-by-paper, take max chunk score). When `level="section"`,
  group by `(paper_id, section_path)`. Apply filters as scalar
  predicates where the column exists; ignore unknown filter keys (with
  a `filter_warnings: [...]` array in the response).
- `get_chunk`: option (iii) — direct LanceDB lookup
  `chunks_table.search().where(f"chunk_id = '{chunk_id}'").limit(1)`.
  `include_referenced` and `include_equations` return empty arrays
  pre-E10 (no equation atoms exist).
- `find_equation`: option (iii) per brief — embed the LaTeX as if it
  were a query, search `embedding_stmt` (NOT `embedding_eq` — the
  column is always NULL pre-E10).
- `get_definitions`: option (iii) — read
  `var/arxmcp/corpus/preamble/<paper_id>/preamble.json` (the
  `PreambleDoc.macros` list) and parse each `\newcommand{\X}{...}` line
  into `(symbol, expansion)` pairs. When `term` is given, filter to
  matching symbol. Sort alphabetically by symbol.
- `find_lemma_by_name`: option (ii) — no FTS5 index exists. Initial
  cut: scan `chunks_table.to_arrow()` for non-NULL `theorem_name` and
  do an in-memory case-insensitive substring match. Fast enough for
  50-paper corpus; document that production needs FTS5 (E10).
- `get_paper`: option (iii) — synthesize from the chunks table:
  `SELECT paper_id, MAX(chunker_version), MAX(embedder_version),
  COUNT(*), array_agg(DISTINCT section_path[0])` grouped by paper_id.
  No `authors`/`year`/`categories` columns exist; return `null` for
  those (or empty arrays). When E11 ships a `papers` metadata table,
  swap the source.
- `cite_neighbors`: option (ii) — Kùzu graph not shipped. Return empty
  `neighbors: []` for all directions, with
  `infrastructure_status: "deferred"` in `structuredContent` so callers
  can branch.

**(b) Schema definition: dataclass vs Pydantic vs FastMCP auto-derive.**
The brief says "frozen Python dataclasses in `server/tools.py`". My read:
the brief is specifying the WIRE-FORMAT schema (the dataclass owns the
canonical JSON Schema bytes that go on the wire), NOT the
implementation language for argument validation. Concrete proposal:
- `server/tools.py` declares for each tool: a frozen `@dataclass(frozen=True)`
  `ToolSchema(name: str, description: str, input_schema: dict,
  output_schema: dict | None)`. `input_schema` is a hand-authored JSON
  Schema Draft-07 dict, alphabetically sorted at construction time.
- Each tool handler is a plain async function that takes
  `arguments: dict[str, Any]` and validates internally (Pydantic
  TypeAdapter, or plain `if "k" not in arguments`).
- Registration uses `mcp_server._tool_manager._tools[name] = MCPTool(name=ts.name,
  description=ts.description, parameters=ts.input_schema, ...)` — i.e.
  bypass `@tool()` and write directly to the tool manager's dict (or
  use `add_tool` with `description=` and a shim function whose
  signature matches the schema). The latter is brittle (FastMCP will
  re-derive a schema and ignore ours). The former requires reaching
  into the `_tool_manager` private surface, which the codebase has
  precedent for (see `_safe_tool_count` in `_mcp_mount.py`).
- Cleaner alternative: subclass `FastMCP` and override `list_tools` to
  return our hand-authored schemas. This keeps `call_tool` dispatch
  (which still needs an entry in `_tool_manager`) but lets us own the
  `tools/list` payload byte-for-byte. Recommend this route.

**(c) `tool_schema_version: int` in `tools/list`.** The MCP spec has no
top-level slot for this. Two options:
- (i) Embed in each tool's `_meta`: `{"_meta": {"tool_schema_version":
  1}}`. Spec-compliant; clients that don't read `_meta` ignore it; our
  byte-stability test computes the hash AFTER serialization so it
  picks up the change.
- (ii) Add a custom top-level field on the `ListToolsResult`. The
  Pydantic `Result` class has `model_config = ConfigDict(extra="allow")`,
  so extra fields ARE preserved — but a strict client may reject the
  response. Less safe.
- **Recommendation: (i).** Define `TOOL_SCHEMA_VERSION = 1` as a module
  constant in `server/tools.py`; emit it in each tool's `_meta`. The
  E06_S06 byte-stability hash will protect every bump.

**(d) `get_paper` and the `papers` table.** The papers table doesn't
exist. Options:
- Synthesize on the fly from `chunks_table` (group-by-paper). Cheap and
  correct for the v1 fields available (`paper_id`, `chunker_version`,
  `embedder_version`, chunk count). Returns `null` for `authors`,
  `title`, `year`, `categories`, `abstract` — none of those are in any
  ingest output today.
- Read from `chunk_manifest.json` (per-paper sidecar produced by the
  chunker at `var/arxmcp/corpus/chunks/<paper_id>/chunk_manifest.json`).
  Same poverty of metadata fields.
- **Recommendation:** synthesize from `chunks_table`. Add a
  `metadata_status: "synthesized_from_chunks"` flag in the result so
  callers know fields are partial. When a real `papers` table lands
  (E11 / E12), swap the implementation; the API stays stable.

**(e) `find_lemma_by_name`.** No FTS5 sidecar exists; building one as
part of E06_S03 means new ingest-side code (out of brief). Initial
implementation: in-memory substring scan over `chunks_table` filtered
by `theorem_name IS NOT NULL`. For the 50-paper seed corpus this is
~hundreds of rows — single-millisecond scan. Document the
"deferred-to-E10 for FTS5" path and add a smoke test that asserts a
known fixture lemma name returns its chunk.

**(f) Tests.** The cold-start dilemma is real (same as E05_S02). Three
tiers:
- **Unit tests for schema shape** — no corpus needed; just assert
  `tools/list` shape, JSON Schema Draft-07 conformance via
  `jsonschema.Draft7Validator.check_schema(...)`, deterministic
  serialization. Always-on.
- **Smoke tests against tmp_path LanceDB** — reuse the
  `_seed_corpus(lancedb_path)` helper from `test_server_startup.py`,
  expand to ~5 chunks across 2 papers with deterministic body_text,
  theorem_name set on at least one chunk. Mock BGE-M3. Always-on.
- **The "50-paper seed corpus" path mentioned in the brief AC** —
  doesn't exist on disk yet (E05_S02 has the curated fixtures but they
  are not ingested). My read: skip this AC literally; instead add a
  pytest mark `@pytest.mark.ingested_corpus` that runs only when
  `ARXMCP_TEST_INGESTED_LANCEDB_PATH` env var points to a real corpus.
  Document in `tests/README.md` that operators run the 50-paper seed
  ingest first, then `pytest -m ingested_corpus`. **Recommendation:**
  satisfy the AC via the tmp_path-seeded approach and call out the
  literal-50-paper variant as an env-gated extension, mirroring the
  pattern E06_S01 used for `ARXMCP_RUN_REAL_BGE_M3=1`.

**(g) `corpus_version` field.** Confirmed: source from
`app.state.resources.corpus_info.version` (an `int`), embed in every
tool's `structuredContent.corpus_version`. The handler reaches it via
the FastMCP `Context` parameter (Context exposes
`fastmcp.get_context().request_context.lifespan_context` if we wire it
through the lifespan, OR more directly via the FastAPI `app.state`
which is reachable from the request scope). Cleanest: stash a module-
level reference at startup (`server/tools.py` imports a `set_resources(r)`
hook called from the lifespan) — handlers reach it via that
module-level closure rather than spelunking through `Context`.

## External writes the implementation will require

| type | target | why |
|---|---|---|
| none | n/a | E06_S03 is local code + tests; no remote writes. The 50-paper seed corpus ingestion is an operator action, not part of this milestone. No git push, no PR creation, no infra mutation, no third-party API call. The `pip install -e .` re-run is a developer-machine action, same precedent as E06_S01/E06_S02. |
