# E06_S03 Implementation Summary

**Branch:** `claude/gallant-blackburn-b89422`
**Files changed:** 11 (10 new, 1 modified)
**Commit (planned):** see Phase 4 footer once committed.

## Files

| Path | New / Modified | Purpose |
|---|---|---|
| `server/tools.py` | NEW | `ToolMeta` frozen-dataclass constants (one per tool), `TOOL_SCHEMA_VERSION`, `register_all(mcp_server)`, `set_resources` / `get_resources` lifespan hand-off, `envelope()` + `enforce_byte_cap()` shared helpers. |
| `server/handlers/__init__.py` | NEW | Empty pkg marker. |
| `server/handlers/search.py` | NEW | `search_papers` — dense-only ANN over `embedding_stmt`; level={paper,section,theorem} with dedup-keep-best aggregation; ≤150-char snippet from body_text. |
| `server/handlers/chunk.py` | NEW | `get_chunk` — direct LanceDB lookup; `_CHUNK_ID_RE` validation; `enforce_byte_cap` for >256KB bodies (resource_link mode). |
| `server/handlers/equation.py` | NEW | `find_equation` — dense-only fallback over `embedding_stmt` (embedding_eq always NULL pre-E10_S03). |
| `server/handlers/definitions.py` | NEW | `get_definitions` — reads per-paper `preamble.json`, parses `\newcommand{\X}{...}` lines, supports optional `term` filter. |
| `server/handlers/lemma.py` | NEW | `find_lemma_by_name` — in-memory case-insensitive substring scan; exact-match-first sort. |
| `server/handlers/paper.py` | NEW | `get_paper` — synthesizes per-paper metadata from chunks (chunk_count, section_count, versions); null-fields for authors/title/year (no metadata source today). |
| `server/handlers/citations.py` | NEW | `cite_neighbors` — empty stub with `infrastructure_status: "deferred"`. |
| `server/main.py` | modified | Insert `register_all_tools(mcp_server)` BEFORE `mount_mcp` (synthesis D11); call `set_resources(resources)` from the lifespan after `Resources.startup` returns. |
| `tests/test_tools_all.py` | NEW | 14 tests across 3 classes: schema-shape (3) + Draft-07 conformance (1) + per-tool smoke (10). |

## Decisions exercised from research-synthesis.md

| Decision | Where it landed |
|---|---|
| D1 — Cross-epic dependency strategy: best-effort where infrastructure exists | 6 of 7 tools use real data (search/chunk/equation/definitions/lemma/paper); cite_neighbors is the only stub |
| D2 — Schema definition: typed handler signatures + frozen description constants | `ToolMeta` constants in `server/tools.py`; FastMCP-derived inputSchemas via `Annotated[T, pydantic.Field(...)]` |
| D3 — `tool_schema_version` per-tool `_meta` | `mcp_server.add_tool(..., meta={"tool_schema_version": TOOL_SCHEMA_VERSION})` |
| D4 — `papers` table: synthesize from chunks | `handle_get_paper` aggregates the chunks_table; null-fields for absent metadata; `metadata_status: "synthesized_from_chunks"` |
| D5 — `find_lemma_by_name`: in-memory substring scan | `handle_find_lemma_by_name` over `chunks_table.to_arrow()` filtered by `theorem_name IS NOT NULL` |
| D6 — `cite_neighbors`: empty stub | `handle_cite_neighbors` returns `{neighbors: [], infrastructure_status: "deferred"}` |
| D7 — Test strategy: tmp_path LanceDB + mocked BGE-M3 | `_seed_corpus(lancedb_path)` helper mirrors E06_S01's pattern |
| D8 — Resources hand-off via module-level singleton | `set_resources(r)` from lifespan; `get_resources()` from handlers |
| D9 — Per-handler body-size cap | `enforce_byte_cap()` in `server/tools.py`; called by `get_chunk` |
| D10 — Sort order `(score_desc, chunk_id_asc)` | every list-returning handler sorts before truncating to k |
| D11 — Tool registration BEFORE `mount_mcp` | `create_app()` sequence: FastMCP() → register_all() → mount_mcp() |
| D12 — JSON Schema Draft-07 conformance | `TestSchemaConformance::test_all_input_schemas_are_draft7_compatible` uses `jsonschema.Draft7Validator.check_schema` + asserts no `$defs` (which would be 2020-12-only) |

## Test results

- **652 passed**, 3 skipped (pre-existing), ruff clean (was 638, +14 new tests)
- 14 new tests across `TestToolsList` (3), `TestSchemaConformance` (1), `TestToolsSmoke` (10)
- All tools invoke via the FastAPI TestClient against the mounted `/mcp/` endpoint; the MCP `initialize` handshake is performed first via `_initialize_session(client)` helper

## Acceptance-criteria mapping

| AC | Status | Where verified |
|---|---|---|
| `tools/list` returns exactly 7 tools | **met** | `TestToolsList::test_seven_tools_registered` + `test_tool_names_match_canonical` |
| Each tool's JSON schema validates against Draft-07 | **met** | `TestSchemaConformance::test_all_input_schemas_are_draft7_compatible` |
| `search_papers(level="paper")` returns paper-level results | **met** | `TestToolsSmoke::test_search_papers_level_paper` (asserts dedup-by-paper) |
| `get_definitions(paper_id="...")` returns full notation table | **partial** | Logic shipped + tested for the `extraction_status: "no_preamble"` cold-start path; the full-table path requires a real preamble.json (E02_S02 produces one but the test corpus doesn't have one) |
| `get_definitions(paper_id="...", term="\\mathcal{A}")` returns the expansion for that symbol | **partial** | Same as above — the per-term filter logic ships; the smoke test exercises the no-preamble branch |
| `cite_neighbors(direction="depends_on")` returns intra-paper deps | **stubbed** | `handle_cite_neighbors` returns `infrastructure_status: "deferred"`; the schema accepts the direction arg |
| All 7 tool smoke tests pass against the 50-paper seed corpus | **partial** | All 7 pass against a synthetic 5-chunk corpus; the literal 50-paper run is gated behind operator ingestion (per synthesis "rephrase as smoke tests against synthetic-but-representative corpus" + the env-gated escape hatch precedent from E06_S01) |

## Notable design choices for the critic

- **Tool registration order is load-bearing.** `register_all_tools(mcp_server)` MUST run BEFORE `mount_mcp(app, mcp_server)` because `streamable_http_app()` snapshots the registered tools at mount time. Documented in `server/main.py:create_app` with an inline comment citing synthesis D11.
- **The `mocked_bge_m3` fixture monkeypatches at THREE locations:** `server.query_encoder._get_model` / `_get_tokenizer` (the singletons), AND `server.handlers.search.encode_query` / `server.handlers.equation.encode_query` (the import bindings). Otherwise the handlers' `from server.query_encoder import encode_query` captures the real function at module-load and the monkeypatch on `query_encoder.encode_query` doesn't affect them.
- **Test seed-corpus chunk_ids are consistent:** the embedded paper_id in each chunk_id matches the `ChunkRecord.paper_id` field. This is enforced by the `_CHUNK_ID_RE` validator in `chunk.py` which rejects malformed ids; if the seeder ever drifts, the get_chunk smoke test catches it.
- **`enforce_byte_cap` is a hand-rolled helper, not a pure-ASGI middleware.** The E06_S01 `BodySizeCapMiddleware` exempts `/mcp` (Streamable-HTTP carries SSE chunks that defeat buffering). So per-handler enforcement is the only path; `enforce_byte_cap(structured_content, chunk_id)` returns `(structured, content_blocks)` and surfaces a `resource_link` when over cap.
- **`get_chunk` sets `resource_link_uri` in structuredContent** when over cap; the `content_blocks` array from `enforce_byte_cap` would normally land in the MCP response's `content` array, but FastMCP's auto-derivation of `content` blocks from a return value is opaque. v1 surfaces the URI via structured payload; E06_S04 will pin the richer `content` array shape for `search_papers` results.
- **`_envelope(payload)` injects `corpus_version`** sourced from the live `Resources` singleton AND sorts the dict alphabetically. Serialized output is byte-stable across runs (a precondition for the E06_S06 hash test).
- **Cross-epic dependencies documented per-tool in the description constants** — agents reading `tools/list` see the v1 limitations explicitly. The descriptions are FROZEN at module load and do NOT interpolate runtime state (BP1 byte-stability).
- **`cite_neighbors` is a stub but the schema is stable.** When E09 (Kùzu citation graph) lands, the handler swap is internal — no schema change, no agent-side breakage.

## Out-of-scope (deferred per brief)

- `paper_diff` (Tier 4).
- LLM-generated summaries in tool results (E06_S04 explicitly drops these).
- Full equation TED index (E10_S03).
- Hybrid BM25+RRF retrieval (E07).
- Kùzu citation graph (E09).
- SQLite FTS5 lemma index (E10_S02).
- A real `papers` metadata table (E11/E12).

The cross-epic-dependency tools (`cite_neighbors`, partial `get_definitions`) ship with stable schemas and will swap to real data without API changes when the upstream epics ship.

## External writes

**None at commit time.** All deliverables are local commits.
- The `pip install -e .` re-runs locally for the new handlers
  package; that's a developer-machine action.
- No git push, no PR, no infra mutation, no third-party API call.
