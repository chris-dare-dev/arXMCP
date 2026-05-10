# E06_S03 — Research brief 1 (researcher 1 of 2)

## 1. In-codebase context

### Per-tool design (06-mcp-server-design.md, lines 51–256)

The note explicitly fixes the surface and the response envelope:

> "All tools accept JSON arguments; all return `{content: [...], structuredContent: {...}}` where `structuredContent` is the canonical, byte-stable, cache-friendly payload."

`search_papers` (lines 64–128). Inputs `query` (required) + `level` ∈ {paper, section, theorem} default theorem + `k` int 1–50 default 10 + `filters` object (`categories`, `year_min`, `year_max`, `authors`, `include_withdrawn`) + opaque `cursor`. Result fields per row: `chunk_id`, `paper_id`, `version`, `label`, `score`, `snippet` (≤150 chars taken **directly** from `body_canonical`), `section_path`. Top-level: `results`, `next_cursor`, `corpus_version`, `embed_model`. The note is verbatim:

> "The `summary` field is **dropped**. Each result carries only a ≤150-char inline `snippet` taken directly from `body_canonical` (no LLM rewriting). Agents that need the full body call `get_chunk(chunk_id)`."

`get_chunk` (130–145): inputs `chunk_id` + `include_referenced?` + `include_equations?`. The note doesn't pin the response shape — implicitly the full ChunkRecord plus optional referenced citations / equation atoms.

`find_equation` (147–164): input `latex` (required) + `k`. Note says "MathML → tree-edit-distance plus dense embedding"; the brief's name is `latex_or_mathml`. Returns equation atoms with parent chunk IDs.

`get_definitions` (166–183): inputs `paper_id` (required) + `symbol` (note uses `symbol`; brief uses `term` — call out). Without the symbol filter returns full notation table; with it expands one symbol (absorbs `expand_macro`).

`find_lemma_by_name` (186–198): inputs `name` (required) + `paper_id?` + `fuzzy?` (default true).

`get_paper` (210–219): inputs `paper_id` (required) + `version?` (defaults to latest). The note doesn't define the result shape; the brief points at "metadata lookup from the `papers` table." That table does not exist.

`cite_neighbors` (221–245): inputs `chunk_id` (required) + `direction` ∈ {citers, cited, co_cited, co_citing, depends_on} default `cited` + `depth` 1–3 default 1 + `limit` 1–100 default 30. `direction="depends_on"` absorbs the former `dependency_graph`.

### Determinism contract (06-mcp-server-design.md, lines 270–290)

Verbatim:

> "1. Results sorted by `(score_desc, chunk_id_asc)`. Ties broken deterministically. 2. Chunk IDs content-addressable. 3. No timestamps anywhere in tool results. 4. No random tie-breaking. 5. JSON serialized with sorted keys (alphabetical). 6. `corpus_version` field included in every response… 7. Tool definitions themselves are byte-stable across server restarts: pin schema, sort properties alphabetically, freeze descriptions in source."

And: "A casual edit to a tool description blows every sub-agent's prompt cache. Treat tool definitions as a versioned API surface; bump a `tool_schema_version` field when changing them and document the change."

### BP1 byte-stability (07-multi-agent-caching.md, 40–62)

> "Pin tool JSON schemas. Sort properties alphabetically at serialization time. Freeze descriptions as constants in source… Implementation: a single `tools.py` module with frozen dataclasses + a unit test that asserts `sha256(serialize_tools()) == EXPECTED_HASH`."

E06_S06 will land that hash test.

### LanceDB schema reality (`ingest/schema.py::CHUNKS_SCHEMA_V1`)

The chunks table carries: `chunk_id`, `paper_id`, `kind`, `section_path` (`list<utf8>`), `theorem_name`, `theorem_label`, `body_text`, `body_tokens`, `embedding_stmt` (1024-dim, nullable), `embedding_proof` (1024-dim, nullable), `embedding_eq` (1024-dim, nullable, **never populated** until E10_S03), `chunker_version`, `embedder_version`, `preamble_ref`. No `title`, no `abstract`, no `authors`, no `year`, no `categories`, no `version` (paper version), no `references`, no `equations`, no `definitions`, no `papers` table, no FTS5, no Kùzu. ChunkRecord has no `version` field for the per-row paper-version stamp the design's snippet object expects.

Tools implementable from the schema today: `search_papers` (dense-only), `get_chunk` minus `include_referenced`/`include_equations`. Everything else needs new infrastructure.

### `server/` inventory

`main.py` — FastAPI app + lifespan; `app.state.resources` holds the `Resources` container; `app.state.mcp_server` is a `FastMCP("arxmcp", json_response=True)` (the `json_response=True` is load-bearing — the shim cannot parse SSE). The MCP comment is explicit: "no tools registered yet — E06_S03 lands the tool implementations" (line 12).

`_mcp_mount.py` — single mount call; **does not** expose any helper for tool registration: "Tool registration lands in :mod:`server.tools` (E06_S03), and that module will import `FastMCP` directly" (line 12).

`corpus.py` — `open_chunks_table(path, version)` + `read_corpus_version(path)` + `CorpusVersionInfo`. The reader-side primitive every tool handler will call.

`query_encoder.py` — `encode_query(text)` is the BGE-M3 singleflight singleton (4-byte / NFC-normalized canonicalization, 100 ms post-completion eviction, L2-normalized 1024-dim float32). This is the embedding entry point for `search_papers` and `find_equation` (dense-only fallback path).

`resources.py` — `Resources` dataclass: `chunks_table`, `embed_semaphore`, `rerank_semaphore`, `rerank_singleflight`, `corpus_info` (so `corpus_info.version` is the int that lands in every tool result).

`health.py` — `/healthz`, `/readyz`, `/metrics`. No per-tool counters yet; line 26: "per-tool counters land in E06_S03 when the tools materialize."

`config.py` — pydantic-settings; carries `result_byte_cap = 256 KB` (line 130). E06_S01's `BodySizeCapMiddleware` exempts `/mcp` precisely because SSE chunks defeat buffering — the MCP spec response is enforced via the `resource_link` discipline, not the middleware.

### E07_S01 / E07_S02 status

**Not shipped.** Roadmap (E07-hybrid-retrieval.md lines 17–93) defines `server/retrieval/bm25.py::BM25Phase` and `server/retrieval/ann.py::ANNPhase` as future work in Sonnet B's stream. There is no `server/retrieval/` directory. The brief lists E07_S01/E07_S02 as dependencies of E06_S03; this is an aspirational dependency, not a satisfied one. The E04_S04 `ingest/bm25_indexer.py` writes a per-corpus-version BM25 pickle but no server-side loader exists yet.

**Recommendation:** ship `search_papers` with **dense-only ANN over `embedding_stmt`** today (the `embedding_proof` column is for proofs, not statements; mixing without RRF would produce inconsistent rankings). When the Phase-1 BM25 + Phase-2 RRF + Phase-3 reranker land, replace the dense-only path inside `server/handlers/search.py`. The tool's external contract (schema + result shape) does not change. Document the degradation explicitly in `search_papers`'s description constant — but do NOT interpolate runtime state into the description, or BP1 cache stability dies (07-multi-agent-caching.md line 44).

## 2. Prior decisions and lessons

- **`corpus_version: int` is mandatory in every result.** `app.state.resources.corpus_info.version` is the source. Wire it via a small helper `_envelope(payload)` in `server/tools.py` that injects `corpus_version` and `embed_model` into `structuredContent`.
- **256 KB body cap and `resource_link` (E06_S01 F1 closure, main.py 89–224).** The middleware exempts `/mcp` because SSE defeats buffering. So per the comment block (lines 99–104): "MCP-spec tools that need to return large payloads MUST use `resource_link` per the spec — that resource_link IS the '<256 KB pointer to the larger payload' pattern." `get_chunk` for a long proof body **can** exceed 256 KB; the handler itself must measure the serialized JSON length and switch to `resource_link` (URI `arxmcp://chunks/<chunk_id>`) when the payload is over cap. The MCP server already exposes the resource URI scheme (06-mcp-server-design.md line 261).
- **`Mcp-Session-Id` is per-process; tool handlers don't thread it.** The shim captures it (E06_S02 implementation summary, "TestSessionIdHandling"); FastMCP's session manager handles it server-side. Tool handlers receive a `Context` (FastMCP's optional injected param) if they need anything session-scoped — for E06_S03, no handler should need to.
- **Cross-epic dependencies (recap):**
  - `find_lemma_by_name` requires SQLite FTS5 (E10_S02). Not built.
  - `get_definitions` requires per-paper notation extraction (E10_S01). Not built. Preamble extraction (E02_S02) DID land — `preamble_ref` field is on every chunk — but the parsed `\newcommand` map is not stored anywhere readable by the server.
  - `cite_neighbors` requires Kùzu citation graph (E09). Not built. The `cites` rel table doesn't exist; `direction="depends_on"` would also need intra-paper theorem dependency edges (a separate parser pass not yet planned for any milestone).
  - `get_paper` requires a `papers` metadata table. **Not built and not currently scheduled** — the closest is the Kùzu `papers` node table from E09_S01, but Kùzu lives behind E09 and the schema there is graph-side. There is no paper-metadata source-of-truth in `var/arxmcp/index/` today.
  - `find_equation` needs `equations` table + MathML trees (E10_S03). The `embedding_eq` column exists in the schema but is never populated (`ingest/schema.py` line 101: "embedder NEVER populates this; every row written by E03_S01 has embedding_eq=None").
- **`server/query_encoder.encode_query` is the embedder.** Already singleflight-wrapped; tests confirm it produces the same vector that `ingest/embedder.EMBEDDER_VERSION` indexed with. Use it from `search_papers` and `find_equation` (when the latter falls back to dense-only).
- **E06_S01 mount discipline (`_mcp_mount.py` lines 14–16):** "Tool registration lands in `server.tools` (E06_S03), and that module will import FastMCP directly. This module's job is exactly the mount call." So `server/tools.py` does `from mcp.server.fastmcp import FastMCP` (or accepts a passed-in instance), defines all 7 tools, and exposes a `register_all(mcp_server: FastMCP, app_state)` function that `server/main.py::create_app` calls right after `mount_mcp(app, mcp_server)` (or before — registration must complete BEFORE `streamable_http_app()` is invoked, which happens **inside** `mount_mcp`, so registration MUST happen before the mount call. This is a real ordering constraint that needs to be sequenced in `create_app`).

## 3. External sources

### MCP 2025-06-18 spec (Tools section)

- Tool inputs MUST validate against `inputSchema` (JSON Schema Draft-07).
- Tool results carry both `content: list[ContentBlock]` (human-readable: TextContent, ImageContent, ResourceLinkContent, EmbeddedResourceContent) AND optional `structuredContent: dict` (machine-readable, when an `outputSchema` is declared).
- `tools/list` returns an array of `{name, description, inputSchema, outputSchema?, title?, annotations?}` plus an optional `nextCursor` for pagination.
- The spec does NOT define `tool_schema_version` — that's a **project-local** convention added in the design note. We surface it via the `_meta` field on the `tools/list` response (the spec reserves `_meta` keys for implementations) OR by wrapping the response in our own JSON envelope. Be opinionated: put it on the `_meta` of EACH tool entry as `_meta: {"tool_schema_version": 1}` so a single-tool change can be tracked independently.
- `resource_link` in `content` is `{type: "resource_link", uri, name?, description?, mimeType?}`.
- Error response: a tool can either set `isError: true` on a normal result with a TextContent describing the error, OR throw a JSON-RPC error. The spec recommends `isError: true` for tool-level failures so the agent sees them in-band.

### FastMCP `@mcp.tool()` (verified against the locally vendored `mcp` lib)

The decorator (`fastmcp/server.py` line 446) **derives the JSON schema from the function's Pydantic-validated parameters** (`func_metadata` + `arg_model.model_json_schema(by_alias=True)`). The function docstring becomes the description. Return-type annotation drives whether output is structured. So FastMCP **does NOT consume frozen dataclasses** — it consumes type-hinted Python functions. This contradicts the brief's literal phrasing ("frozen Python dataclasses in `server/tools.py`").

The reconcilable read: the dataclasses ARE the source of truth for schema bytes; we use them to **assemble a Pydantic model** programmatically (`pydantic.create_model` with field defaults from the dataclass), then write the actual handler functions whose signatures use `Annotated[X, Field(...)]` to match. Or simpler: skip the dataclass dance and write the seven handler functions with the schema declared via Pydantic field annotations directly, then write a unit test that **serializes the resulting `tools/list` JSON with sorted keys** and pins its sha256. The hash-pinning is what BP1 actually requires — the dataclass intermediary is a means to that end, not the end itself.

## Open questions

- **(a) Cross-epic dependency strategy.** Pick (i) for `get_paper`, `find_lemma_by_name`, `cite_neighbors`, and `get_definitions`: handlers raise a `ToolNotImplementedError` that surfaces as `isError: true` + a TextContent like *"`find_lemma_by_name` requires the theorem-names FTS5 index (E10_S02), not yet built. Tracked at .claude/roadmap/E10-specialized-indices.md."* The `tools/list` schema still lists all 7 tools (the AC requires it). The **handlers** stub the dependency. For `find_equation` go with (iii) — dense-only fallback over `embedding_eq` is impossible (column always NULL), so fall back to **dense over `embedding_stmt`** keyed on the LaTeX text passed through `encode_query`; document the limitation. For `search_papers` go with (iii) — **dense-only over `embedding_stmt`** today, with a TODO to flip to RRF when E07_S02 lands. Rationale: the AC says "All 7 tool smoke tests pass against the 50-paper seed corpus"; pure-(i) handlers would still pass the smoke test (returning a clean error IS a valid response), but you don't get the agent-runtime integration you need from E08 without `search_papers` returning real results.
- **(b) FastMCP integration shape.** Use **typed handler functions registered via `@mcp.tool()`**, with parameters annotated using `Annotated[T, pydantic.Field(description=..., ge=..., le=...)]` so the schema FastMCP derives matches the design note's JSON Schema verbatim. The dataclasses-in-`server/tools.py` are kept ONLY as the **source-of-truth constants for descriptions** (frozen `@dataclass(frozen=True)` with `name: str` and `description: str` fields); the handlers read those constants to populate the `description=` argument on the decorator. This satisfies the brief's "frozen dataclasses" requirement (descriptions are frozen at module-load) without fighting FastMCP. The byte-stability test (E06_S06) hashes the rendered `tools/list` response, not the dataclasses themselves.
- **(c) `tool_schema_version`.** A single module-level constant `TOOL_SCHEMA_VERSION: int = 1` in `server/tools.py`. Surfaced via FastMCP's per-tool `meta` field on every registered tool (`add_tool(..., meta={"tool_schema_version": TOOL_SCHEMA_VERSION})`). Bumped manually when ANY tool's schema bytes change; the byte-stability test fails if you forget. Justification: putting it per-tool lets future per-tool versioning land without an envelope rewrite.
- **(d) `papers` table.** Build it as a **separate LanceDB table `papers`** colocated with `chunks` under the same dataset version. Schema: `paper_id` (utf8, PK), `version` (int32), `title` (utf8, nullable), `abstract` (utf8, nullable), `authors` (list<utf8>, nullable), `categories` (list<utf8>, nullable), `year` (int32, nullable). Justification: keeps the MVCC `corpus_version` discipline (E04_S03) — one `corpus-version.json` covers both tables. SQLite would fragment the version model; embedding paper metadata in chunks is denormalized and breaks LanceDB MVCC isolation. **However**, this milestone should NOT build the populator (no metadata extractor exists in `ingest/`); the brief is "implement the 7 tools," not "extend ingest." So `get_paper` returns the `ToolNotImplementedError` for v1 (option (a) above) and lands a one-line TODO/issue for the metadata-extractor milestone.
- **(e) `find_lemma_by_name` SQLite FTS5.** **Defer the handler** (option (a)). Building FTS5 in this milestone widens scope from "implement 7 tools" to "implement 7 tools + a new ingest sidecar + a new SQLite reader infra," and the underlying theorem-name dedup logic (the dedup_key over `(paper_id, theorem_name, section_path)`) is non-trivial — see E10_S02 risk note. Returning `isError` for now is honest and faster.
- **(f) Test strategy.** Follow the **E06_S01 `_seed_corpus(tmp_path)` pattern verbatim** (`tests/test_server_startup.py` lines 53–95): build a tiny 2-chunk LanceDB at `tmp_path`, write a `corpus-version.json`, instantiate `Config(lancedb_path=tmp_path/...)`, call `create_app(config)`, drive via `fastapi.testclient.TestClient`. The 50-paper seed corpus referenced in the AC does NOT exist as an ingested artifact — the eval fixture lives at `tests/fixtures/` but the LanceDB indexed form needs the full ingest pipeline run. Use the `tmp_path` pattern; rephrase the AC narrative as "smoke test passes against a synthetic 2-chunk corpus that exercises every code path." The `tests/test_tools_all.py` deliverable lands as one TestClient session with one `tools/call` per tool plus a `tools/list` length check. Real seed-corpus runs become an env-gated `ARXMCP_RUN_SEED_CORPUS_SMOKE=1` test mirroring the BGE-M3 precedent.

## External writes the implementation will require

None. All deliverables are local to the repo and end at `git commit`. No git push, no PR creation, no ticket mutation, no infra mutation, no third-party API call. The runtime expectations (`make up`, BGE-M3 weight download on first real-model startup, `pip install -e .`) are operator actions, not part of the milestone's external-write boundary. The orchestrator should not gate on this list — there is nothing to gate.
