# Research Synthesis — E13_S04b

**Generated:** 2026-05-20 (orchestrator merge of brief-1 and brief-2)
**Mode:** standard (2× milestone-researcher, Haiku 4.5)

---

## Current state of the world (load-bearing)

**The helper exists and is shared.** `server/tools.py` defines:

```python
def enforce_byte_cap(
    structured_content: dict[str, Any],
    chunk_id: str | None = None,
    body_text_path: tuple[str, ...] = ("body_text",),
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
```

Signature:
- Returns `(structured_content, content_blocks)`.
- Happy path (under cap): returns `(payload, [])`.
- Over cap: returns `(truncated_payload_with_1024char_body, [{"type": "resource_link", "uri": "arxmcp://chunks/<chunk_id>", "name": chunk_id}])` and sets `body_truncated=True` at top level of the structured content.
- Measurement: `len(json.dumps(payload).encode("utf-8")) * _WIRE_OVERHEAD_FACTOR <= Config.result_byte_cap` where `result_byte_cap = 262144` and `_WIRE_OVERHEAD_FACTOR = 2` (per `server/tools.py:415,448`).
- `CHUNK_RESOURCE_URI_SCHEME = "arxmcp://chunks/"` defined once in `server/tools.py:100`.

**Current enforcement** (verified by both researchers):

| Tool | File | Enforces? | Pattern |
|---|---|---|---|
| `get_chunk` | `server/handlers/chunk.py:100-104` | ✅ | `enforce_byte_cap(payload, chunk_id=chunk_id, body_text_path=("chunk","body_text"))` |
| `get_definitions` | `server/handlers/definitions.py:182-205` | ✅ | `_cap()` helper wraps `enforce_byte_cap(payload)` |
| `search_papers` | `server/handlers/search.py:40-46` | ❌ | Handler comment explicitly: "search_papers does NOT call server.tools.enforce_byte_cap (only get_chunk does at v1)" |
| `find_equation` | `server/handlers/equation.py` | ❌ | No call |
| `find_lemma_by_name` | `server/handlers/lemma.py` | ❌ | No call |
| `get_paper` | `server/handlers/paper.py` | ❌ | No call |
| `cite_neighbors` | `server/handlers/citations.py` | ❌ | Handler is v1 stub returning `{neighbors: [], infrastructure_status: "deferred", ...}` |

---

## Threat 4 verbatim (`.claude/notes/08-security-observability-ops.md`)

> **Threat 4: Resource exhaustion via tool arguments**
>
> An LLM in a retry loop can pass `k=10000` and torch the rerank budget. A
> prompt-injection could request enormous result payloads.
>
> **Mitigations:**
> - JSON-Schema `maximum` on every numeric parameter (`k <= 50`).
> - Hard byte cap on tool result inline content (256 KB; spillover via `resource_link`).
> - Per-session rate limits keyed on `Mcp-Session-Id`: max 60 tool calls per
>   minute per session, max 1000 per hour. Configurable.
> - Embedder/reranker semaphores prevent runaway concurrent calls.

E13_S04b closes the "hard byte cap" mitigation across the 5 currently-unenforced tools.

---

## Snippet-contract layer separation (E06_S04)

From `.claude/docs/snippet-contract.md` § (a):

> Snippet is 150 characters max — no LLM rewriting. Every result row carries
> a single inline text field, `snippet`. The content is the first 150 characters
> of the chunk's canonical body text. The 150-char cap is small enough to fit
> ~50 results under the 256 KB inline-payload cap (E06_S01).

**Two distinct layers:**
1. **Per-row snippet:** 150 chars — applies to row content fields.
2. **Aggregate response payload:** 256 KB — applies to entire `structuredContent` JSON.

The 150-char per-row cap doesn't prevent aggregate overflow; the byte cap is the load-bearing aggregate guard. At v1 the 150-char + k≤50 floors mean the cap is largely defensive (forward-compat for reranker expansion, section-level dedup, future full-body inclusion).

---

## Where briefs disagreed — orchestrator decisions

1. **For multi-result tools (`search_papers`, `find_equation`, `find_lemma_by_name`), should the over-cap `resource_link` point to the first row's `chunk_id` or omit the link?**

   Brief-1: extract first result's `chunk_id` where available.
   Brief-2: omit for `search_papers` (aggregate, not a single chunk); use first match for others.

   **Decision: pass `chunk_id=None` for all three multi-result tools.** When the cap fires on a multi-result response, the overflow is on the AGGREGATE response, not a single chunk. Pointing the `resource_link` at the first row's `chunk_id` would mislead the agent — `get_chunk(<first_chunk_id>)` won't recover the truncated other rows. Per the snippet-contract § (d), resource links are advisory; agents follow the per-row `chunk_id` field from the result to fetch the full body of specific rows they care about. Omitting the link is semantically correct ("here's a truncated multi-result payload; the per-row chunk_ids are still in the results array — pick what you want").

   For `cite_neighbors`, pass `chunk_id=chunk_id` (the INPUT parameter — the parent chunk being queried). This IS meaningful: the link points to the parent chunk whose neighborhood was being returned.

   For `get_paper`, pass `chunk_id=None` (the over-cap response is the paper metadata, not a chunk).

2. **Synthetic vs realistic test payload?** Both researchers converged. **Decision:** use `unittest.mock.patch` to temporarily lower `Config.result_byte_cap` to a small value (e.g. 256 bytes) and construct minimal-but-over-cap payloads. Mirrors the E13_S04 `test_resource_exhaustion.py` pattern. Fast, deterministic, no large fixtures.

3. **Docstring updates?** Both researchers said yes. **Decision:** one-line note in each handler's module docstring or function docstring: `E13_S04b — byte cap enforced via server.tools.enforce_byte_cap`. Matches the `get_chunk` precedent.

4. **Helper extraction?** Brief-1's research found the helper is ALREADY single-sourced in `server/tools.py`. **No extraction needed.** Just import + call.

---

## Brief/repo conflicts — researcher-1 had one factual error

**Researcher-1 wrote:** "Brief says 'close GitHub issue #1' — no `.github/` directory exists per CLAUDE.md §4.1, no actual GitHub issue exists; this is a deferred gap documented in E13_S10 coverage table."

**This is wrong.** The E13_S10 milestone (completed earlier in this session) filed six gap issues via `gh issue create`; G1 is now `chris-dare-dev/arXMCP#1` at `https://github.com/chris-dare-dev/arXMCP/issues/1`. CLAUDE.md §4.1 forbids CI gating, not GitHub issues. The audit doc `.claude/docs/security-threat-model-coverage.md` already cites the URL. **The `gh issue close #1` external write IS required** at Phase 4.

Researcher-2 correctly noted the issue as a Phase 4 external write.

---

## Failure modes (union of both briefs, deduped)

1. **Boundary off-by-one** — payload just over cap by 1 byte. Resolved by `_WIRE_OVERHEAD_FACTOR=2` and the strict `<=` check at the helper measurement site. No implementation change required, but tests should pin the boundary behavior.
2. **JSON encoding overhead** — chunk body with many escape sequences inflates serialized size 5-10%. The cap is on **serialized JSON bytes**, not raw content. Helper already measures correctly (`json.dumps(...).encode("utf-8")`). Implementer must not measure on raw body length.
3. **Unicode codepoint vs byte counting** — Greek/CJK papers have more UTF-8 bytes per codepoint. The helper uses `.encode("utf-8")` so the byte count is correct. No fix needed.
4. **Future metadata explosion in `get_paper`** — when the metadata table lands (E11/E12), high-author-count physics papers (ATLAS/CMS, 3000+ authors) could push a single `get_paper` response past 256 KB. v1 returns NULL for all metadata so the cap is a no-op today, but the call MUST be added now for forward-compat.
5. **`cite_neighbors` stub becomes real (E09 wire-up)** — once the citation graph is queried for real, neighbors with chunk-body context could push past the cap. Add the cap call now so the future implementation inherits it without revisiting.
6. **`find_lemma_by_name` with chunk-body expansion** — current in-memory substring scan returns small rows. If E10_S02 adds chunk-body context to matches, the aggregate could approach the cap. Defensive cap added.
7. **`find_equation` with surrounding context** — same forward-compat argument.
8. **Tool-schema cache invalidation** — adding `Field(max_length=...)` constraints would re-pin `EXPECTED_TOOL_SCHEMA_SHA256` and bust the BP1 prompt cache. The helper enforces in handler body, not schema. **Implementer must not add Field constraints.** Same pattern E13_S04 used for `MAX_FILTER_ITEMS`.
9. **Resource-link URI confusion** — agent receives a truncated response with `resource_link` to `arxmcp://chunks/<chunk_id>`. The agent then tries to pass that URI as a `chunk_id` arg to `get_chunk`, which validates the regex and rejects. **By design** — per snippet-contract § (d), the resource link is advisory for spec-compliant MCP clients; agents follow the per-row `chunk_id` field, not the URI scheme. No implementation change.
10. **Empty-result tools with the cap call** — `cite_neighbors` stub returns `[]`; `find_equation` with no matches returns empty. The cap call is a no-op on tiny payloads. **Let it run anyway** — consistency over branching.

---

## Implementation plan (concrete deliverables)

1. **`server/handlers/search.py`** — import `enforce_byte_cap` from `server.tools`. After building the search-results payload but before returning, call `structured, content_blocks = enforce_byte_cap(payload)`. Return both. Update the existing comment ("search_papers does NOT call enforce_byte_cap") to reflect the new state. Module docstring gets a one-line note.

2. **`server/handlers/equation.py`** — same pattern. `chunk_id=None` (multi-result; aggregate overflow).

3. **`server/handlers/lemma.py`** — same pattern. `chunk_id=None`.

4. **`server/handlers/paper.py`** — same pattern. `chunk_id=None`. The call is a no-op at v1 (metadata is NULL) but forward-compat for E11/E12.

5. **`server/handlers/citations.py`** — pass `chunk_id=chunk_id` (the input parameter to `cite_neighbors`). v1 stub returns empty so the cap never fires, but the pattern is in place for E09 wire-up.

6. **No new shared helper.** The existing `server.tools.enforce_byte_cap` is already single-sourced.

7. **No Pydantic Field changes.** No tool-schema hash bump. `EXPECTED_TOOL_SCHEMA_SHA256` stays stable.

8. **`tests/security/test_resource_exhaustion.py`** — extend with one parametrized test class covering the 5 newly-covered tools:
   - `monkeypatch.setattr(Config, "result_byte_cap", 256)` (or similar — find the actual patching pattern in the existing tests).
   - Construct a minimal handler input that, when the handler runs, produces a payload > 256 bytes serialized.
   - Assert: `body_truncated=True` in the structured response.
   - Assert: `resource_link` content block is present (with input chunk_id for `cite_neighbors`; with `null`-name link or absent for the others).
   - Existing `get_chunk` + `get_definitions` cap tests remain as regression guards.

9. **`.claude/docs/security-threat-4-audit.md`** — update the per-tool compliance matrix to mark all 7 tools as cap-enforced. Add a note that E13_S04b closed the 5-tool gap.

10. **`.claude/docs/security-threat-model-coverage.md`** — update:
    - Summary-table Threat 4 row "Gaps" cell: replace `[#1 — extend 256 KB byte cap to remaining tool handlers](https://github.com/chris-dare-dev/arXMCP/issues/1)` with `(none)`.
    - Per-threat Threat 4 section "Gaps:" line: replace the `[#1 ...]` link + paragraph with `(none) — closed by E13_S04b`.
    - Gap-issue triage table G1 row: add a column note marking it closed, OR remove the row and add a "Closed gaps" sub-section below the open-gap table.

11. **`tests/security/test_threat_model_coverage.py` (E13_S10 staleness gate)** must continue to pass after the doc edit. The doc structure must keep all 7 numbered-threat sections + the observability addendum.

12. **GitHub issue closure** — `gh issue close 1 --reason completed --comment "Closed by E13_S04b: <commit-sha>"`. Phase-4 gated external write.

---

## Acceptance-criteria mapping

| AC (verbatim) | Status / how met |
|---|---|
| All 7 return-chunk-or-content tools enforce 256 KB cap with identical semantics | ✓ — 5 handler-body changes calling the existing `enforce_byte_cap` helper |
| `tests/security/test_resource_exhaustion.py` includes parametrized cap-rejection tests for all five newly-covered tools | ✓ — new test class extending existing patching pattern |
| `pytest tests/security/test_resource_exhaustion.py` passes all cases | ✓ — verified at Phase 2 exit |
| `.claude/docs/security-threat-model-coverage.md` Threat 4 row no longer cites #1; Gap-issue triage table updated | ✓ — doc edit replaces `(TODO file issue)` → `(none) — closed by E13_S04b` and adds a note to the G1 row |
| `tests/security/test_threat_model_coverage.py` (E13_S10 staleness gate) still passes | ✓ — doc edit preserves all 7 threat sections + addendum; staleness gate continues to pass |
| GitHub issue #1 closed with a commit reference | ⚠️ **Phase-4 gated** — `gh issue close 1` requires user authorization at the external-write boundary |

---

## Open questions (deferred to implementer judgment)

1. **`search_papers` over-cap envelope shape.** The handler returns a `results` list. When the cap fires:
   - The helper truncates the structured content (replaces `body_text` with a 1024-char excerpt + sets `body_truncated=True`).
   - But `search_papers` has no top-level `body_text` — its data shape is `{"results": [...], "filter_warnings": [...]}`.
   - **What happens** when `body_text_path=("body_text",)` (the default) doesn't match the structure?

   Researcher-1's read of `enforce_byte_cap` suggests it gracefully handles missing paths (the truncation is "best-effort"). The implementer should verify by running the test against a contrived oversize payload and confirming the envelope is shaped sensibly. If the helper doesn't degrade gracefully, the call should pass an empty `body_text_path=()` or similar.

2. **Cap value patching in tests.** Brief-1 suggests `patch.object(Config, "result_byte_cap", 1024)`. The implementer should locate the actual patching site in the existing E13_S04 tests and mirror it exactly.

3. **Audit-doc edit shape.** Two options for the Gap-issue triage table:
   - Add a "Status" or "Closed by" column inline.
   - Move closed rows to a "Closed gaps" sub-section under the open table.

   Recommend the inline column approach — keeps the audit trail visible and the table editable.

---

## External writes the implementation will require

| Type | Target | Why | Blocking |
|---|---|---|---|
| Git commit (feat) | local main | Implementation commit | No (local) |
| Git commit (rect) | local main | Rectifier commit closing critic findings | No (local) |
| Git commit (chore) | local main | Finalize state.json | No (local) |
| `gh issue close 1` | `chris-dare-dev/arXMCP` issue #1 | Close the issue with a reference to the closing commit | **YES — Phase-4 gated** |

---

## Orchestrator synthesis note

Both briefs converged on the same implementation shape: import the existing `server.tools.enforce_byte_cap` helper into each of the 5 missing handlers, add the call before the return, no schema changes, extend the test file with patched-cap parametrized tests. The only orchestrator-level merge concerns:

1. Researcher-1's factual error claiming "no actual GitHub issue exists" — corrected by the synthesis. Issue #1 IS real; `gh issue close` IS the Phase-4 external write.
2. Resource-link `chunk_id` argument for multi-result tools — the synthesis picks `None` for all three (search/equation/lemma) on semantic grounds (aggregate overflow ≠ single-chunk overflow). `cite_neighbors` gets the input `chunk_id` because that IS the parent context the link belongs to. `get_paper` gets `None`.
3. The CLAUDE.md §7 "Known stubs" note about `cite_neighbors` being a stub remains accurate — cap enforcement is forward-compat plumbing, identical to E13_S07's `ARXMCP_PIN_ARXIV_CA` stub pattern.

This is the smallest possible scope that closes G1: 5 handler patches + 1 test class + 2 doc edits + 1 GitHub issue close. ~150 LOC, well within the inline implementation path's 500-LOC budget.
