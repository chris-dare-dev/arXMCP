# E13_S01 — implementation summary

## What landed

Closes Threat 1 (path traversal via `paper_id` / `chunk_id`)
from `.claude/notes/08-security-observability-ops.md`. The
audit confirmed:

- 4 of 7 handlers already validated in-body (E06_S03 F3 close).
- 1 handler (`cite_neighbors`) was an unguarded gap — now
  closed with an `is_valid_chunk_id` guard.
- 2 handlers take no scalar identifier and are out of Threat-1
  scope (`search_papers.filters` is a documented known gap,
  `find_equation` is Threat-3 scope).

Plus the audit doc + 23 regression tests.

## Files changed

| Path | Change | Synthesis ref |
|---|---|---|
| `server/handlers/citations.py` | NEW: `is_valid_chunk_id` guard at handler entry (3 lines); mirrors `get_chunk` precedent | D3 |
| `tests/security/__init__.py` | NEW (empty package marker) | D9 |
| `tests/security/test_path_traversal.py` | NEW — 23 tests: 9 paper_id × 3 inputs + 6 chunk_id × 3 inputs + 6 chunk_id-shaped attacks + 2 positive sanity cases | D9 |
| `.claude/docs/security-threat-1-audit.md` | NEW operator-internal audit doc: per-tool table, canonical regex, known gaps, deferred migration plan | D8, D11 |

## Drift from brief (deliberate)

1. **Tool surface corrected.** Brief named 7 tools including
   `paper_diff` + `dependency_graph` (don't exist) and silently
   omitted `get_definitions` + `find_lemma_by_name`. Adopted the
   real `server/tools.py::ALL_TOOLS` list.
2. **AC reframed from `-32602` to `ValueError` + isError wrap.**
   Brief 2 §4 reads the mcp Python SDK source and confirms it
   NEVER emits JSON-RPC -32602 for tool-arg validation — both
   jsonschema and Pydantic failures surface as
   `CallToolResult(isError=True)`. The security GOAL ("never
   reach the handler body") is met; the wire-level code is
   implementation choice. Migration to bespoke
   `McpError(INVALID_PARAMS)` is deferred to a future Tier-6+
   milestone (documented in the audit doc §"Migration plan").
3. **`E07_S12` is a fictional dependency.** The brief asserts
   it mandated regex at JSON-Schema; that milestone never
   shipped. The audit is BOTH a coverage milestone AND an
   enforcement milestone — added the `cite_neighbors` guard
   that was missing.
4. **15 → 21 → 23 test cases.** Brief said 21 (`7 × 3` based on
   the wrong tool list). Real matrix is 15 (5 identifier-
   accepting tools × 3 adversarial inputs) + 6
   chunk-id-shaped-attack cases + 2 positive sanity cases = 23.
5. **No Pydantic `pattern=` migration.** Adding `Field(pattern=...)`
   would re-trigger `EXPECTED_TOOL_SCHEMA_SHA256` and bump
   `TOOL_SCHEMA_VERSION` (invalidating BP1 prompt-cache per
   note 07). Deferred per D7.
6. **No `max_length` caps.** Same byte-stability re-pin cost as
   the `pattern=` migration; the current anchored regex
   rejects the 512-char overlong input without ReDoS. Deferred.
7. **Doc destination.** Brief said `docs/security/threat-1-audit.md`;
   per CLAUDE.md §1, `docs/` is operator-facing-only. Landed at
   `.claude/docs/security-threat-1-audit.md` (matches the
   E14_S02 precedent).
8. **CI hook reframed.** Brief mandated CI on every PR; project
   has no CI (`CLAUDE.md §4.1`). The new tests run as part of
   `make test`.

## Test count delta

* Pre-milestone: 1866 passed, 9 skipped, 1 xfailed (end of E14_S05).
* Post-milestone: 1889 passed, 9 skipped, 1 xfailed (+23):
  - 9 in `TestPaperIdPathTraversal` (3 tools × 3 inputs)
  - 6 in `TestChunkIdPathTraversal` (2 tools × 3 inputs)
  - 6 in `TestChunkIdShapedAttacks` (2 tools × 3 chunk-shaped
    attacks)
  - 2 in `TestPositiveCases` (sanity guards)
* `ruff check .` — clean.

## Acceptance criteria status

- [x] **All adversarial cases rejected before handler body.**
  Adopted AC: every adversarial input raises `ValueError` from
  the in-body validator BEFORE any resource lookup. 21 tests
  (15 brief-mandated + 6 chunk-shaped bonus) pass. The SDK
  wraps the ValueError into `CallToolResult(isError=True)` for
  callers — covered by the existing handler test suite.
- [x] **`docs/security/threat-1-audit.md` has one row per tool.**
  Reinterpreted as `.claude/docs/security-threat-1-audit.md`
  per CLAUDE.md §1. All 7 tools have rows; status column shows
  ✅ for 5 covered handlers, KNOWN GAP for `search_papers.filters`,
  OUT OF SCOPE for `find_equation`.
- [x] **Any failing tool gets a fix in the same PR.**
  `cite_neighbors` was the only gap; closed in this commit.
- [~] **CI runs the tests on every PR.** Reframed as
  `make test` participation — the project has no CI configured
  (CLAUDE.md §4.1).

## What this milestone does NOT cover

- **`search_papers.filters` paper_id validation.** Deferred
  pending E07_S04 (real filter execution). Documented as a
  known gap in the audit doc.
- **Pydantic JSON-Schema `pattern=` enforcement.** Deferred —
  re-pins `EXPECTED_TOOL_SCHEMA_SHA256` and bumps
  `TOOL_SCHEMA_VERSION`.
- **`max_length` Pydantic caps.** Same as above.
- **`McpError(INVALID_PARAMS)` migration for wire-level
  -32602.** Tier-6+ work.
- **Threats 2–9.** Each is its own milestone (E13_S02 through
  E13_S10).

## Threat-coverage matrix snapshot

After E13_S01:

| Threat | Status |
|---|---|
| 1. Path traversal via paper_id | ✅ E13_S01 |
| 2. Prompt-injection delimiter | ⏳ E13_S02 |
| 3. LaTeXML sandbox hostile input | ⏳ E13_S03 |
| 4. Resource exhaustion | ⏳ E13_S04 |
| 5. Origin spoofing / DNS rebinding | ⏳ E13_S05 (partial — Origin / Host already shipped in E06_S05) |
| 6. Model SHA pinning / safetensors | ⏳ E13_S06 (partial — BGE-M3 SHA already pinned) |
| 7. Source ingestion TLS | ⏳ E13_S07 |
| 8. Log redaction | ⏳ E13_S08 |
| 9. Localhost binding regression test | ⏳ E13_S09 |
