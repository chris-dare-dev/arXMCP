# Research Brief — E13_S04b

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-20T00:00:00Z

## In-codebase context

### Handler layout (7 tools, actual filenames)

The canonical 7-tool surface per `server/tools.py::ALL_TOOLS`:
1. `server/handlers/search.py` — `handle_search_papers`
2. `server/handlers/chunk.py` — `handle_get_chunk` ✓ **byte-cap enforced**
3. `server/handlers/equation.py` — `handle_find_equation`
4. `server/handlers/definitions.py` — `handle_get_definitions` ✓ **byte-cap enforced**
5. `server/handlers/lemma.py` — `handle_find_lemma_by_name`
6. `server/handlers/paper.py` — `handle_get_paper`
7. `server/handlers/citations.py` — `handle_cite_neighbors` (v1 stub)

### Byte-cap enforcement status (E13_S04 shipped)

**Current state (from memory E13_S04 known-gaps):**
- `get_chunk`: enforces via `enforce_byte_cap(payload, body_text_path=("chunk", "body_text"))`
- `get_definitions`: enforces via `_cap()` helper that calls `enforce_byte_cap(payload)` with no body_text_path arg (defaults to top-level)
- `search_papers`, `find_equation`, `find_lemma_by_name`, `get_paper`, `cite_neighbors`: **NO enforcement**

**The helper function** — `server/tools.py::enforce_byte_cap`:

```python
def enforce_byte_cap(
    structured_content: dict[str, Any],
    chunk_id: str | None = None,
    body_text_path: tuple[str, ...] = ("body_text",),
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
```

Returns `(structured_content, content_blocks)` where:
- On happy path (under 256 KB): returns `(payload, [])`
- Over cap: returns `(truncated_payload_with_1024char_body, [{"type": "resource_link", "uri": "arxmcp://chunks/<chunk_id>", "name": chunk_id}])`
- Sets `body_truncated=True` at top level when truncation fires
- Measures: `len(json.dumps(payload).encode("utf-8")) * _WIRE_OVERHEAD_FACTOR <= Config.result_byte_cap` (cap is 262,144 bytes default)

**Constant is defined once** (good): `CHUNK_RESOURCE_URI_SCHEME = "arxmcp://chunks/"` in `server/tools.py` line 100.

### Per-tool scope decision

1. **`search_papers`** — Returns list of 150-char snippets + metadata (≤50 rows). Current worst-case: 50 rows × (150 chars + ~200 bytes metadata) ≈ 17.5 KB. Well under cap by design per handler comments. CAP RELEVANT for forward-compat when `level="section"` or `level="paper"` dedup or reranker output expansion lands. **Recommend adding defensive cap now.**

2. **`find_equation`** — Returns equation atoms with context. Per handler: returns top-k equations with surrounding context. No explicit size bound in the code. **Cap relevant; should be added.**

3. **`find_lemma_by_name`** — Returns theorem-name matches. Per handler signature: takes `k: Field(ge=1, le=50)`. Per memory: no `enforce_byte_cap` call. Each row is small (name + chunk_id + metadata). **Cap relevant for consistency; low-risk but should be added.**

4. **`get_paper`** — Synthesizes metadata from chunks: chunk_count, section_count, chunker_version, embedder_version. Authors/title/abstract/year/categories are `null` at v1. Per handler: "v1 has no papers metadata table." **Cap is a no-op today** (all returned fields are tiny) **but should be added for forward-compat** — when the metadata table lands (E11/E12), the abstract field could exceed 256 KB for a single paper.

5. **`cite_neighbors`** — Handler is a v1 stub (per memory: "returns `{neighbors: [], infrastructure_status: "deferred", ...}` for every direction"). Returns empty results today. **Cap enforcement is harmless no-op now, but should be added for forward-compat** — when E09 wires the graph, results could be large.

### Existing test pattern (`tests/security/test_resource_exhaustion.py`)

E13_S04 test file (per read above, lines 1–80):
- Imports handlers directly (async pattern with `asyncio.run`)
- Uses `unittest.mock.patch` to mock resources / LanceDB
- Tests both Pydantic validation rejection (schema-level) AND handler-level validation
- Parametrizes over adversarial inputs (e.g., `ADVERSARIAL_K = 10000`)
- Checks exception type and that handler body doesn't execute

**Pattern for extending:** The implementer should:
1. Add test cases for each new tool following the existing parametrization style
2. Mock resource state (corpus version, config) as needed
3. Exercise the byte-cap path by constructing a synthetic payload that exceeds 256 KB (or patching the cap lower for testing)

### Snippet contract (E06_S04, per `.claude/docs/snippet-contract.md`)

- `snippet` is 150 characters max, no LLM rewriting
- Wrapped in `<retrieved_chunk>...</retrieved_chunk>` delimiters (E13_S02 Threat 2 defense)
- Escape-on-emit: literal `<retrieved_chunk>` or `</retrieved_chunk>` in the body is HTML-escaped before wrapping
- Over-cap response carries `resource_link` in `content` array (MCP 2025-06-18 spec)
- Full quote from snippet-contract.md §(d): "The `resource_link` blocks are **advisory**. The agent runtime (E08) does NOT depend on the client following them — it relies on the agent explicitly calling `get_chunk(chunk_id)`."

### MCP 2025-06-18 spec compliance

Per `06-mcp-server-design.md` lines 42–49:
- "Tool result size has no protocol limit — we enforce our own (256 KB hard cap on inline content)"
- "Use `resource_link` for the long tail"
- "No protocol-level streaming of tool results"

The brief's spillover envelope shape (resource_link in content array) is **spec-compliant**.

### Brief vs reality flags

**Fictional dependencies in the brief:**
- E07_S10 cited as dependency — **E07 stops at S04** (confirmed in memory)
- E06_S07, E06_S08 cited as dependencies — **E06 stops at S06** (confirmed in memory)
- Reframes: E13_S04 is BOTH spec AND enforcement for this coverage gap (same pattern as E13_S01–S03 per memory)

**Tool names in brief vs code:**
- Brief says "dependency_graph" — actual tool is `cite_neighbors` (per memory E13_S02 tool-list-drift)
- Handlers exist at expected paths ✓

**External writes required:**
- Brief says "close GitHub issue #1" — no `.github/` dir exists (per CLAUDE.md §4.1, no CI/PRs)
- Reframe: No actual GitHub issue exists; this is a deferred gap documented in E13_S10 coverage table

---

## Prior decisions and lessons

### E13_S04 state (already shipped, phase=complete)

From `.claude/notes/milestones/E13_S04/state.json`:
- Shipped 2026-05-18, one implementation commit + one rect commit
- Closed 7 findings (F1–F7), deferred 1 (F8)
- **Key F4 from E13_S04 rect:** Pydantic Field constraint vs handler-body validation tradeoff — handler-body `raise ValueError` is invisible to tool schema (no TOOL_SCHEMA_VERSION bump), same security outcome as a Pydantic `Field(max_items=...)`

This informs E13_S04b approach: **don't add schema constraints that would re-pin `EXPECTED_TOOL_SCHEMA_SHA256`**. Add enforcement inside handlers if needed.

### Known patterns from prior E13 milestones

1. **Doc placement**: `.claude/docs/security-threat-4-audit.md` not `docs/security/threat-4-audit.md` (per memory E13_S01)
2. **Byte-cap pattern**: Quote from `get_chunk` is the canonical precedent — nested body path support via `body_text_path` parameter (F1 from E06_S03 critique)
3. **No schema re-pins**: Search_papers already uses handler-body validation for `MAX_FILTER_ITEMS` to avoid schema bump (per memory E13_S04)

### Git log recent commits

E13_S04 shipped via commit `002ed477c35c68a75b5d45134676c5ebf4987496` (per state.json). Prior: E13_S03 through E13_S01 all completed.

---

## External sources

### MCP spec (2025-06-18)

https://modelcontextprotocol.io/specification/2025-06-18

Relevant quote from spec: CallToolResult carries two output channels:
- `structuredContent`: machine-readable JSON object
- `content`: array of content blocks (TextContent, ResourceLink, etc.)

Resource links are **advisory** per the spec; clients are not required to follow them.

### Anthropic prompt-caching

https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching

Relevant: tool definitions are part of the BP1 cacheable prefix. Changing tool schema (adding Field constraints that would change the JSON-Schema shape) invalidates the prompt cache across all agents. This is why handler-body validation is preferred when the security goal is the same.

### Design constitution notes

- `.claude/notes/06-mcp-server-design.md` § Tool surface (lines 42–49) — cap specification
- `.claude/notes/08-security-observability-ops.md` § Threat 4 (lines 51–62) — resource exhaustion threat model
- `.claude/docs/snippet-contract.md` § (d) — resource_link semantics and advisory nature

---

## Recommendation

**Extend `enforce_byte_cap` enforcement to all remaining 5 tools** using the existing helper, following the pattern established in `get_chunk` and `get_definitions`. This closes the E13_S04 enforcement gap and fulfills the brief's intent: "Cap behavior must be identical to the existing pattern (256 KB inline budget; oversize content spills via `resource_link`)."

**Specific approach:**

1. **search_papers**: Call `enforce_byte_cap(payload)` (default body_text_path) on the structured result before returning. Worst-case is bounded by k (≤50) + per-row snippet (≤150 chars), so it's a no-op today, but adds forward-compat when reranker output or section-level aggregation lands.

2. **find_equation**: Call `enforce_byte_cap(payload, chunk_id=<extracted_from_first_result>)` if results are non-empty (to surface the resource_link correctly). The cap is defensive against future expansion of equation context.

3. **find_lemma_by_name**: Call `enforce_byte_cap(payload)`. Similarly bounded today (k ≤ 50, small rows), but forward-compat when theorem-name database grows.

4. **get_paper**: Call `enforce_byte_cap(payload)`. No-op at v1 (metadata is null), but essential for forward-compat when the papers table lands with abstract/author/title fields.

5. **cite_neighbors**: Call `enforce_byte_cap(payload, chunk_id=chunk_id)` even though it returns empty results today. v1 stub is non-blocking; E09 wiring will benefit from the cap already in place.

**No schema changes required.** All 5 tools already accept the arguments needed; the cap is purely an internal handler-body change.

**Testing:** Extend `tests/security/test_resource_exhaustion.py` with:
- One parametrized test per tool verifying `enforce_byte_cap` is called
- A synthetic payload fixture (e.g., a 300 KB JSON structure) to exercise the cap path
- Assertion that `body_truncated=True` is set when cap fires
- Assertion that `resource_link` appears in the result envelope

---

## Open questions

1. **Synthetic payload construction for tests:** Should the test create a realistic oversized chunk body (e.g., a 300 KB theorem proof), or mock the JSON serialization to exceed the cap artificially? The former is more realistic but slower; the latter is deterministic and fast. **Recommendation: use `unittest.mock.patch` to temporarily lower the cap (e.g., to 1 KB) during the test, then construct a payload that exceeds it. This avoids needing large fixture files.**

2. **Resource link URI construction for multi-result tools:** `search_papers` and `find_lemma_by_name` return multiple rows. When the cap fires, should the `resource_link` point to the first oversized row, or should the handler not surface a link (since the aggregate result, not a single chunk, exceeded the cap)? **Recommendation: for `search_papers`, extract the first `chunk_id` from results if present. For `find_lemma_by_name`, extract the first `chunk_id` from the matched set. For `find_equation`, use the first matched equation's `chunk_id`. For `get_paper`, use the `paper_id` itself as a fallback URI (or surface no link if the brief intent is chunk-level only). For `cite_neighbors`, use the input `chunk_id` (already available).**

3. **Docstring updates vs audit doc:** Should each handler's docstring be updated to note the enforce_byte_cap call, or is it sufficient to document in `.claude/docs/security-threat-4-audit.md` that all 7 tools now enforce the cap? **Recommendation: add a one-line docstring note in each handler (e.g., "E13_S04b — byte cap enforced via enforce_byte_cap") to match the pattern in `get_chunk` and `get_definitions`.**

---

## External writes the implementation will require

E13_S04b closes a documented gap from E13_S10's audit. Per the brief, it specifies "close GitHub issue #1" — but no `.github/` directory exists per CLAUDE.md §4.1 (no CI blocking merges). **This is not an external write in the usual sense.** The gap will be documented in E13_S10's threat-model-coverage table (which does file GitHub issues if any gaps remain). At the time E13_S10 runs, if the gap still exists, a GitHub issue will be filed then. For E13_S04b purposes, **no external writes are required** — this is a purely local code change.

If the user wants to file a GitHub issue when this milestone completes, that can be done during the Phase 4 rectify step, but it is not a blocking requirement for implementation.
