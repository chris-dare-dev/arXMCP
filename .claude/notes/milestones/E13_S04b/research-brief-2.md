# Research Brief — E13_S04b

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-20T18:45:00Z

## In-codebase context

### Threat 4 verbatim from `08-security-observability-ops.md`

> **Threat 4: Resource exhaustion via tool arguments**
>
> An LLM in a retry loop can pass `k=10000` and torch the rerank budget. A
> prompt-injection could request enormous result payloads.
>
> **Mitigations:**
> - JSON-Schema `maximum` on every numeric parameter (`k <= 50`).
> - Hard byte cap on tool result inline content (256 KB; spillover via
>   `resource_link`).
> - **Per-session rate limits** keyed on `Mcp-Session-Id`: max 60 tool calls per
>   minute per session, max 1000 per hour. Configurable.
> - Embedder/reranker semaphores prevent runaway concurrent calls.

E13_S04 shipped JSON-Schema caps + 256 KB byte cap on `get_chunk` + `get_definitions`
only. E13_S04b extends the 256 KB cap to the remaining 5 tools per the threat model's
**"Hard byte cap on tool result inline content (256 KB; spillover via `resource_link`)"**
mandate. The cap is NOT optional; it is load-bearing for Threat 4 closure.

### Snippet-contract layer separation (E06_S04)

From `.claude/docs/snippet-contract.md` § (a):

> **Snippet is 150 characters max — no LLM rewriting.** Every result row carries a
> single inline text field, `snippet`. The **content** is the first **150 characters**
> of the chunk's canonical body text. The 150-char cap is small enough to fit ~50
> results under the 256 KB inline-payload cap (E06_S01).

This establishes TWO DISTINCT layers:
1. **Per-row snippet:** 150 chars, applies to `search_papers` result rows.
2. **Aggregate response payload:** 256 KB, applies to the entire `structuredContent` JSON.

**Critical distinction for E13_S04b:** The 150-char snippet contract DOES NOT prevent
aggregate overflow. A `search_papers` call with `k=50` returns 50 rows × ~200 bytes of
metadata each = ~10 KB before any snippet. The snippets add 150 chars × 50 = 7,500 chars
≈ 7.5 KB. Well under 256 KB. **But a future reranker expansion or section-dedup pass
could change the per-row size.** The cap is forward-compat defense.

### Current enforcement gap (verified by code inspection)

**get_chunk** (server/handlers/chunk.py, lines 100–104):
```python
structured, content_blocks = enforce_byte_cap(
    payload,
    chunk_id=chunk_id,
    body_text_path=("chunk", "body_text"),
)
```
Enforces. Body is nested under `chunk.body_text`.

**get_definitions** (server/handlers/definitions.py, lines 182–205):
```python
def _cap(payload: dict[str, Any]) -> dict[str, Any]:
    structured, _blocks = enforce_byte_cap(payload)
    return structured
```
Enforces. Called on the paginated definitions response envelope.

**search_papers** (server/handlers/search.py, lines 40–46):
```
# Note on body-size cap. ``search_papers`` does NOT call
# ``server.tools.enforce_byte_cap`` (only ``get_chunk`` does at v1).
```
**NO enforcement.** Handler comment explicitly documents this v1 omission.

**find_equation** (server/handlers/equation.py):
Grep search found no `enforce_byte_cap` call. No enforcement.

**find_lemma_by_name** (server/handlers/lemma.py):
Grep search found no `enforce_byte_cap` call. No enforcement.

**get_paper** (server/handlers/paper.py):
Grep search found no `enforce_byte_cap` call. No enforcement.

**cite_neighbors** (server/handlers/citations.py):
v1 stub returns `{neighbors: [], infrastructure_status: "deferred", ...}`. The
inline content is always tiny. No enforcement, but stub is non-blocking.

## Failure modes and boundary-case analysis

### Failure mode 1: Search with k=50 and long snippets (aggregate near cap)

**Trigger:** `search_papers(query="...", k=50)` where the query embeddings happen to
match 50 papers that all have unusually long theorem names.

**Symptom:** Each result row carries `snippet` (truncated 150 chars) + `label` (theorem
name, e.g., "Theorem A.3.1") + `paper_id` + `score` + `chunk_id`. If theorem names
are 100 chars on average (realistic for hep-th papers with complex notation), the
per-row overhead can exceed 300 bytes. 50 rows × 300 bytes = 15 KB, still well under
256 KB. **This mode is safe today.**

**Mitigation:** Handler already sets `k <= 50` via JSON-Schema. The cap is defensive
against future `level="section"` or `level="paper"` dedup that might inflate per-row
size, or reranker output that adds extra fields.

### Failure mode 2: Boundary case — one result just over cap by 1 byte

**Trigger:** A single-result response from `get_paper` (or `find_equation` on a paper
with huge metadata) that, when JSON-serialized and wire-enveloped, is 256,001 bytes.

**Symptom:** Depending on cap measurement point, either:
- **Measured on inner JSON only:** 256 KB < 262,144 bytes → cap FIRES. Body is
  truncated to 1,024 chars, `resource_link` is emitted.
- **Measured on wire envelope:** The pretty-printed content block adds ~2× overhead
  per `_WIRE_OVERHEAD_FACTOR = 2` in `server/tools.py` line 415. So inner JSON
  measurement of 131,072 bytes triggers the cap correctly.

**OFF-BY-ONE RISK:** The cap is measured as `len(json.dumps(payload).encode("utf-8"))`
(bytes after UTF-8 encoding, **before** the wire envelope). The multiplication by
`_WIRE_OVERHEAD_FACTOR = 2` guards against the envelope blow-up. **Check implementer
doesn't confuse these two measurements.** Code shows both `get_chunk` and
`get_definitions` use the same measurement point (line 448 in tools.py), so the pattern
is consistent.

### Failure mode 3: JSON encoding overhead and escape sequences

**Trigger:** A chunk body containing many instances of special characters (quotes,
backslashes) or non-ASCII (Greek, CJK) that expand under JSON encoding.

**Example:** A paper with 10,000 CJK characters. Each CJK character in UTF-8 is 3 bytes.
When JSON-encoded with `ensure_ascii=False`, they remain 3 bytes. **But if they're
inside a string field, the container field name, field value wrapper, commas, etc. add
overhead.** A rough 255 KB raw body could expand to 270 KB JSON after field structure.

**Symptom:** The 256 KB cap is on the serialized JSON, not the raw body. A paper body
that's 240 KB raw could exceed the cap after JSON wrapping. The cap fires; body is
truncated to 1,024 chars.

**Mitigation:** The cap is intentionally on serialized bytes (line 448 in tools.py),
not raw. This is correct per Threat 4 — the threat is on the wire payload size, not
internal representation size. **Implementer should NOT measure on raw body bytes.**

### Failure mode 4: Unicode codepoint vs byte counting

**Trigger:** A paper body with 256,000 codepoints, but more bytes under UTF-8 (e.g.,
heavy Greek or math symbols).

**Symptom:** The cap counts **bytes** after UTF-8 encoding (line 448: `.encode("utf-8")`).
A 256-codepoint Greek word could be 512 bytes in UTF-8. The cap is byte-aware and fires
correctly.

**Mitigation:** Code uses `encode("utf-8")` explicitly. This is correct.

### Failure mode 5: Future metadata explosion in `get_paper`

**Trigger:** E11/E12 ships a real `papers` table with full author lists. A high-author-count
physics paper (ATLAS/CMS experiments with 3000+ authors) gets ingest-time storage as a
`[{name: "...", affiliation: "...", orcid: "..."}, ...]` array.

**Symptom:** A single `get_paper` response with 3000 authors × 500 bytes each = 1.5 MB.
The cap is NOT enforced on `get_paper` today. **Response exceeds 256 KB and no
`body_truncated` flag is set.** Downstream agent sees the full response and may choke on
size.

**Mitigation:** E13_S04b MUST add `enforce_byte_cap(payload)` to `handle_get_paper` even
though `get_paper` today returns only tiny synthesized metadata. This is forward-compat.
The audit doc lists this as a forward-compat gap; implementer MUST close it.

### Failure mode 6: `cite_neighbors` stub receives real implementation

**Trigger:** E09 ships and wires the Kùzu citation graph. The `cite_neighbors` handler
is no longer a stub.

**Symptom:** A call to `cite_neighbors(chunk_id="...", limit=100)` that returns 100
neighbors, each with full metadata (chunk_id, paper_id, section_path, theorem_name,
snippet, confidence). 100 neighbors × 300 bytes = 30 KB. Still under 256 KB at v1.

**But:** If E09 also adds `full_chunk_body` as a neighbor field (to surface surrounding
context for high-confidence neighbors), then 100 neighbors × (300 bytes + 5 KB body)
= 530 KB. **Exceeds cap without enforcement.**

**Mitigation:** E13_S04b MUST add `enforce_byte_cap(payload, chunk_id=chunk_id)` to
`handle_cite_neighbors` even though the stub returns empty results. The cap placement
enables E09 implementation to work correctly on day-one without revisiting cap logic.

### Failure mode 7: Worst-case `find_lemma_by_name` with synonym expansion

**Trigger:** A query `find_lemma_by_name("Riemann", k=50)` that matches every use of
"Riemann" across the corpus. Each match row carries `dedup_key`, `display_name`,
`paper_id`, `chunk_id`, `section_path`, `confidence`. Per the handler (lemma.py),
the FTS5 fallback can return many rows.

**Symptom:** 50 matches × 200 bytes = 10 KB. Well under cap. But the `dedup_key` field
uniqueness constraint might collapse N occurrences into M (dedup key is a hash of
`(paper_id, section_path, theorem_label)` or similar). If M is still 50, no overflow.
If all 50 are deduplicated to 1, the response is tiny.

**But:** The in-memory scan fallback (lemma.py line 79) has no documented size guard
beyond `k <= 50`. If a future implementation adds `chunk_id` → `chunk_body` expansion
(to surface full context), then 50 matches × 5 KB body = 250 KB. **At the edge of the
cap with no margin.**

**Mitigation:** The cap should be added defensively. At v1, it's a no-op. But without it,
E10_S02's future expansion passes the 256 KB boundary undetected.

### Failure mode 8: `find_equation` with large surrounding context

**Trigger:** A query `find_equation(latex_or_mathml="\\pi^2", k=50)` matching 50
equations. Each result carries `chunk_id`, `paper_id`, `score`, plus (at v1) the equation
snippet itself is small.

**But:** Future E10 work might add surrounding proof context or macro expansions to the
equation result. A 200-char equation × 50 = 10 KB. But surrounding proof context at
10 KB per equation = 500 KB total. **Exceeds cap without enforcement.**

**Mitigation:** Cap enforcement is essential for forward-compat.

### Failure mode 9: Tampered MCP client downstream agent confusion

**Trigger:** The server correctly enforces the cap and returns a `body_truncated=True`
response with a `resource_link` URI. The agent receives the truncated payload and
makes a follow-up `get_chunk(chunk_id="arxmcp://chunks/...")` call using the URI.

**Symptom:** The URI is passed to `get_chunk` as the `chunk_id` parameter. The handler
validates it against the regex `arxiv:<paper_id>:<16-hex>` (ingest/identifiers.py).
The URI `arxmcp://chunks/<chunk_id>` does NOT match the regex. The handler raises
`ValueError("chunk_id does not match the expected format...")`.

**Is this a problem?** Not per design. The snippet-contract (§d) is explicit: the
`resource_link` blocks are **advisory**. Agents don't use them; they call `get_chunk`
with the `chunk_id` from the result row (not the resource link URI). The URI is for
spec-compliant MCP clients to handle if they wish.

**Mitigation:** Agents should follow the `chunk_id` from `results[0]["chunk_id"]`, NOT
the resource link. The design is correct. The implementer should verify the cap helper
uses the correct URI scheme (`arxmcp://chunks/<chunk_id>`) for clients that do follow it.

## External sources

### MCP 2025-06-18 spec — CallToolResult structure

The spec defines `CallToolResult` with two output channels:
- `structuredContent: dict` — machine-readable JSON object.
- `content: list[ContentBlock]` — array of blocks (TextContent, ResourceLink, etc.).

Per the spec, **there is no protocol-level size limit on either channel.** The 256 KB
cap is arXMCP-specific, documented in `06-mcp-server-design.md` and enforced by handlers.

**Resource link URI format:** The spec permits custom URI schemes. arXMCP uses
`arxmcp://chunks/<chunk_id>` per design. Spec-compliant clients MAY follow the link;
agents are NOT required to.

### Anthropic prompt-caching and tool-schema stability

Per `.claude/notes/07-multi-agent-caching.md` § Anthropic prompt caching:

> **Cache key is the hash of the exact prefix bytes** including system prompt,
> tool definitions, and prior turns up to the breakpoint. Any whitespace or
> ordering change invalidates.

**Implication for E13_S04b:** Adding Pydantic `Field(max_length=...)` constraints would
change the rendered tool schema JSON and invalidate the BP1 prompt-cache across all
agents. Handler-body validation via `raise ValueError` is invisible to the schema and
preserves cache reuse. This is why E13_S04 used handler-body checks for `MAX_FILTER_ITEMS`
(E13_S04 F4 rectification noted in memory).

**For E13_S04b:** The byte-cap enforcement MUST NOT add schema Field constraints. The
cap is applied AFTER the handler builds its response, before returning. This is already
the pattern in `enforce_byte_cap(payload)` — it's called inside the handler, not at the
schema boundary.

### Design constitution coherence

From `06-mcp-server-design.md` lines 42–49:

> Tool result size has no protocol limit — we enforce our own (256 KB hard cap on
> inline content). Use `resource_link` for the long tail.

This is non-negotiable per the threat model. E13_S04b is closure.

## Recommendation

**Extend `enforce_byte_cap` to all five remaining tools:**

1. **search_papers** — Call `enforce_byte_cap(payload)` with default `body_text_path`.
   Return the `structured` part; discard `content_blocks` (not needed for search results
   since no per-row chunk_id mapping exists at the aggregate level). **Forward-compat:**
   when reranker output or dedup lands, this path is ready.

2. **find_equation** — Call `enforce_byte_cap(payload, chunk_id=<first_result_chunk_id
   if present>)`. If results are empty, pass `chunk_id=None`. Returns `(structured,
   content_blocks)`; surface the resource_link if present. **Forward-compat:** equation
   context expansion is covered.

3. **find_lemma_by_name** — Call `enforce_byte_cap(payload)` on the `matches` envelope.
   If matches are present, optionally pass `chunk_id=matches[0]["chunk_id"]` for a
   resource link (may help agents in the stub fallback path). **Forward-compat:** theorem
   database growth is covered.

4. **get_paper** — Call `enforce_byte_cap(payload)` even though v1 returns tiny
   synthesized data. **Forward-compat:** author list explosion in E11/E12 is defended
   against from day-one.

5. **cite_neighbors** — Call `enforce_byte_cap(payload, chunk_id=chunk_id)` where
   `chunk_id` is the input parameter. v1 stub returns empty `neighbors` list, so the
   cap never fires. **Forward-compat:** E09 implementation inherits the cap with no
   refactor needed.

**All patterns match the existing code in `get_chunk` and `get_definitions`.** No new
complexity. Measurement point is consistent: `json.dumps(payload).encode("utf-8")`
with `_WIRE_OVERHEAD_FACTOR = 2` correction.

**Schema impact:** ZERO. Handlers already return the required fields. No Pydantic
Field constraint additions. Cache stability preserved.

## Open questions

1. **search_papers aggregate resource_link:** When multiple result rows contribute to
   the cap overflow, which chunk_id should the resource_link point to? The first row?
   All rows? Or no link (since the aggregate, not a single chunk, exceeded cap)?
   **Recommendation:** Omit the link for `search_papers` — the cap applies to the
   aggregate results, not a single chunk. Agents that want full bodies call
   `get_chunk(chunk_id=result[i]["chunk_id"])` for each row of interest.

2. **find_lemma_by_name — which chunk_id for resource_link?** Matches are a list.
   **Recommendation:** Use the first match's `chunk_id` if present, similar to
   `find_equation`. Or omit the link. The matches list itself is advisory; agents
   fetch full bodies for specific matches that interest them.

3. **Test coverage — synthetic vs. real oversized payload:** Should tests create 300 KB
   JSON structures (slow, large fixtures) or patch the cap lower (e.g., 1 KB) and
   construct minimal payloads (fast, deterministic)? **Recommendation:** Patch the cap
   to 1 KB and construct a payload that exceeds it. Mirrors the E13_S04 test pattern
   in `test_resource_exhaustion.py`. Per memory E13_S04 F4: handler-body validation is
   testable without schema changes.

4. **Docstring audit trail:** Should each handler's docstring note the E13_S04b cap
   addition, or is the `.claude/docs/security-threat-4-audit.md` table sufficient?
   **Recommendation:** Add a one-line docstring note in each handler (similar to
   `get_chunk` line 4: "body-size cap enforced via enforce_byte_cap"). Helps future
   readers understand the flow.

5. **Edge case — empty result enforcement:** For tools that return empty results
   (e.g., `cite_neighbors` stub, `find_equation` with no matches), does the cap run?
   **Recommendation:** Yes, let the cap run. `enforce_byte_cap({results: []})` is a
   no-op (tiny payload), but it's consistent and adds no harm. Removes any special-case
   logic.

## External writes the implementation will require

| Type | Target | Why | Blocking |
|---|---|---|---|
| Code change | `server/handlers/search.py` | Add `enforce_byte_cap(payload)` call | No |
| Code change | `server/handlers/equation.py` | Add `enforce_byte_cap(payload, chunk_id=...)` call | No |
| Code change | `server/handlers/lemma.py` | Add `enforce_byte_cap(payload)` call | No |
| Code change | `server/handlers/paper.py` | Add `enforce_byte_cap(payload)` call | No |
| Code change | `server/handlers/citations.py` | Add `enforce_byte_cap(payload, chunk_id=chunk_id)` call | No |
| Test addition | `tests/security/test_resource_exhaustion.py` | Extend with 5 new parametrized tests (one per tool) exercising cap path | No |
| Docs | `.claude/docs/security-threat-4-audit.md` | Update Threat 4 "Gaps" row from `[#1 — extend byte cap to remaining tools]` to `(none)` | No |
| Issue closure | GitHub issue #1 (if filed) | Will be auto-closed when E13_S04b ships and threat-model audit (E13_S10) runs | No |

**No blocking external writes.** All changes are local to the server and test suite.
