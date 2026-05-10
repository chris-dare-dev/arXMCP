# E06_S04 — Research Brief 1 (sole researcher, single-pass)

## 1. In-codebase context

### `server/handlers/search.py` (E06_S03 state)

The handler already implements ~95% of the snippet contract. Verbatim from the file:

- `SNIPPET_MAX_CHARS = 150` (line 37) — pinned constant.
- `_snippet(body_text)` (lines 168–174) returns `body_text[:SNIPPET_MAX_CHARS]` verbatim, no LLM, no ellipsis. Empty string for null/empty input. **Matches the brief exactly.**
- Per-row dict shape (lines 148–157): `{chunk_id, label, paper_id, score, section_path, snippet}` — six fields, no `summary`, no `version` (E06_S03 already dropped `version` per F7). **No `summary` strip is needed — it never existed.**
- Source column is `body_text` (line 132) read from the LanceDB chunks table.

The handler returns a plain `dict` from `envelope({...})`. There is **no `content` array manipulation** — FastMCP wraps the dict via the auto-generated `_create_dict_model` and the lowlevel server falls into the `isinstance(results, dict)` branch (`server/lowlevel/server.py:548`), producing `content=[TextContent(text=json.dumps(results, indent=2))]` and `structuredContent=results`. So today, `content` carries exactly one block: a pretty-printed JSON repeat of `structuredContent`. **No `resource_link` blocks are emitted.**

### `server/tools.py`

- `CHUNK_RESOURCE_URI_SCHEME = "arxmcp://chunks/"` (line 69). Confirmed.
- `enforce_byte_cap()` (lines 288–337) already builds `resource_link` block dicts when payloads exceed cap, but they are **discarded** by `get_chunk` (line 100 punts: `structured["resource_link_uri"] = content_blocks[0]["uri"]`). The pattern of "build a `resource_link` dict and find a way to inject it into `content`" is exactly what E06_S04 needs to fix — and `get_chunk` will benefit downstream.

### FastMCP — how to inject `content` blocks alongside `structuredContent`

Two viable mechanisms in `mcp==current` (verified against vendored source):

1. **Return `mcp.types.CallToolResult` directly.** `FuncMetadata.convert_result` (`fastmcp/utilities/func_metadata.py:114-118`) explicitly handles this: `if isinstance(result, CallToolResult): ... return result`. The lowlevel server's call-tool dispatcher (`lowlevel/server.py:540`) then short-circuits to `return types.ServerResult(results)` — full handler control over both `content` and `structuredContent`. **Caveat:** when `output_schema` is non-None (which it is — FastMCP auto-builds a `_create_dict_model` for `dict[str, Any]` returns), `convert_result` calls `self.output_model.model_validate(result.structuredContent)`. The structured payload still has to validate against the auto-generated dict model. Easy: keep the same dict shape we've always returned.
2. **Return a `(content_list, structured_dict)` tuple.** `convert_result` returns this tuple when `output_schema is not None` (line 132); the lowlevel server then enters its `isinstance(results, tuple) and len(results) == 2` branch (line 545) and assembles a `CallToolResult` from the parts. Cleaner type-wise but requires reverse-engineering the contract; the `CallToolResult` route is more explicit.

**Recommended:** return `CallToolResult(content=[TextContent(...), ResourceLink(...) for each result], structuredContent=envelope({...}))`. The pretty-printed text block must be assembled manually (mirror what the dict-only path does) so the wire shape stays equivalent for clients that rely on `content[0].text` JSON. There is **no `Context`-based mechanism** — `Context` only carries request metadata, not output blocks.

### `tests/test_tools_all.py`

`test_search_papers_smoke` (lines 281–288) and `test_search_papers_level_paper` (290–295) currently assert: HTTP 200, `corpus_version` in `structuredContent`, `retrieval_mode == "dense_only"`, `results` is a list, and dedup-by-paper produces ≤ N unique paper_ids. **No assertion about `content` blocks, `snippet`, or `summary`.** The new `test_snippet_contract.py` will need its own warm_app fixture (or reuse the seeded corpus pattern from this file) and assert: (a) every result row has `snippet` and the string is ≤150 chars; (b) no row has a `summary` key; (c) `chunk_id` present and matches arxiv id format; (d) `content` array contains a `resource_link` block per row with `uri == "arxmcp://chunks/<chunk_id>"`.

### `docs/` directory

Three files exist: `chunker-fixtures.md`, `eval-curation.md`, `install.md`. All are short single-page notes — `snippet-contract.md` should match that style: ~40-80 lines, four sections (snippet rule, no-summary, no-Citations-API, get_chunk pattern).

## 2. Prior decisions and lessons

- **E06_S03 already dropped `summary` and `version`.** The brief reads as if `summary` still exists; it doesn't. The "strip summary" deliverable is a no-op verification. Treat it as an audit + lock-in via test, not a code change.
- **E06_S03 set `excluded_kinds: ["proof"]`** in the envelope. This is unrelated to the snippet contract and should not appear in `search_papers_result.json` per-row schema — it's an envelope-level field.
- **`SNIPPET_MAX_CHARS = 150`** is the established constant. Reuse, do not duplicate.
- **`body_canonical` vs `body_text`** — see Open question (a).
- **No real seed corpus exists.** `tests/test_tools_all.py` uses `_seed_corpus()` to write 5 synthetic chunks across 2 papers via `ingest.store.write_chunks`. Use the same pattern; do not invent a separate fixture.
- **JSON Schema Draft-07 is the lock-in convention** — `tests/test_tools_all.py:178-200` already enforces Draft-07 over input schemas (specifically forbids `$defs`). Output result schema must match.
- **BP1 byte-stability** is enforced by E06_S06 over `tools/list`. The `result` schema (per-tool output_schema) is also part of the `tools/list` rendering — once committed, any drift in field order, descriptions, or types cracks the cache. Sort the JSON Schema keys alphabetically before writing the file.
- **`CallToolResult` switch-over breaks `outputSchema`-driven serialization unchanged** as long as `structuredContent` validates against the auto-generated dict model. Verified by reading `convert_result`.
- **Content block ordering matters for byte-stability** if E06_S06 ever expands to hash full responses. Keep `content[0]` = the existing pretty-printed JSON text (preserves the wire-overhead-factor=2 measurement in `enforce_byte_cap`), then append `resource_link` blocks in `(score_desc, chunk_id_asc)` order — same sort as `results`.

## 3. External sources

- **MCP spec 2025-06-18 — `CallToolResult`.** `content: ContentBlock[]` where `ContentBlock = TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource` (verified in vendored `mcp/types.py:1206`). `ResourceLink` extends `Resource`: `{type: "resource_link", uri, name, title?, description?, mimeType?, size?, _meta?}`. `name` is required (`Resource` extends `BaseMetadata` which requires `name`). `uri` is `Annotated[AnyUrl, UrlConstraints(host_required=False)]` — custom schemes like `arxmcp://` validate fine (smoke-tested locally: `ResourceLink(type='resource_link', uri='arxmcp://chunks/...', name='...').model_dump()` succeeds).
- **MCP spec on `resource_link` semantics.** "A resource that the server is capable of reading, included in a prompt or tool call result. Note: resource links returned by tools are not guaranteed to appear in the results of `resources/list` requests." — perfect fit for our `arxmcp://chunks/<id>` URIs which are dynamic, not enumerable.
- **JSON Schema Draft-07.** Use `definitions`, not `$defs`; declare `$schema: "http://json-schema.org/draft-07/schema#"`; required fields listed in `required: [...]`. The `additionalProperties: false` flag on the per-row object is appropriate (the contract is closed — extra fields would silently slip in).

## Open questions (opinionated)

(a) **`body_canonical` vs `body_text`.** The brief uses `body_canonical`, the chunks-table column is `body_text`, the implementation reads `body_text`. The design notes (`04-parsing-and-chunking.md`, `05-storage-and-indexing.md`) consistently use `body_canonical` as the conceptual name for "the macro-expanded prose body." The schema chose `body_text` as a pragmatic short name. **Decision: keep the implementation reading `body_text`; in `docs/snippet-contract.md` and `search_papers_result.json` description, write "snippet is the first 150 chars of the chunk's canonical body text (column `body_text` in the LanceDB chunks table; conceptually `body_canonical` per design note 04)."** Brief is not buggy — it uses the conceptual name. No code change.

(b) **FastMCP `content` array injection — recommended pattern: return `mcp.types.CallToolResult` directly from the handler.** Verified against vendored source: `FuncMetadata.convert_result` line 114, lowlevel server line 540. Cleanest of the three options; preserves all envelope/structured-content semantics; keeps the `output_schema` validation intact. The handler signature can stay `-> dict[str, Any]` for FastMCP's input-side type inspection (which only inspects parameters); the actual return value just has to satisfy `isinstance(result, CallToolResult)`. If type-checkers complain, change the annotation to `dict[str, Any] | CallToolResult` — but verify this doesn't break `_try_create_model_and_schema`'s output-schema generation (Union types fall to `_create_wrapped_model`, which would change the wire shape and break BP1). **Safer:** keep return type as `dict[str, Any]`, return `CallToolResult` at runtime, and rely on duck-typing.

(c) **JSON Schema file location.** `server/schemas/` does not exist yet (the only thing named "schema" in `server/` is `server/config.py`). **Mkdir `server/schemas/`, write `search_papers_result.json` there with `__init__.py`-style sentinel optional**. The roadmap reserves the path; honor it.

(d) **Test strategy.** Reuse the synthetic 5-chunk corpus pattern from `tests/test_tools_all.py::_seed_corpus`. Same `mocked_bge_m3` fixture, same `warm_app` fixture, same `_call_tool` helper. The "seed corpus" language in the brief is aspirational; the established convention is synthetic. Write `tests/test_snippet_contract.py` with its own copy of the seed-corpus fixture (or refactor `_seed_corpus` into `tests/conftest.py` — but that's out of scope for E06_S04 and risks E06_S03's smoke tests).

(e) **`resource_link` per row vs shared `content` array.** Per the MCP spec (`CallToolResult.content: list[ContentBlock]`), the array is shared across the whole result, NOT per-row. **Recommended shape:** `content = [TextContent(json-pretty-print of structuredContent), *[ResourceLink for each result row]]`. The `TextContent` block is FastMCP's existing default for dict returns and preserves the wire-overhead-factor=2 measurement that `enforce_byte_cap` depends on (`server/tools.py:285`). The N `ResourceLink` blocks follow, each with `uri = "arxmcp://chunks/<chunk_id>"` and `name = chunk_id`. Order matches the `results` array's `(score_desc, chunk_id_asc)` sort for byte-stability.

(f) **Use the JSON Schema for runtime validation or just doc?** **Recommend: documentation-only at v1, with E06_S06 hash-pinning the file's bytes.** Wiring runtime validation through `jsonschema.validate(structured_content["results"][i], schema)` adds latency on every search call (50 results × Draft-07 validation = non-trivial); the dataclass shape in `search.py` already constrains the fields. The schema file's job is (1) BP1 byte-stability of the contract surface, (2) consumer-side validation by external clients. If we ever flip on runtime validation it's a one-liner addition; ship without first.

## External writes the implementation will require

None. All work is local: code edits in `server/handlers/search.py`, new file `server/schemas/search_papers_result.json`, new file `docs/snippet-contract.md`, new file `tests/test_snippet_contract.py`.
