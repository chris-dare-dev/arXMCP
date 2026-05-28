# Research Synthesis — textbook-ingest-m11 (e5 part 2 of 2 — CLOSES e5)

**Orchestrator merge of research-brief-1 + research-brief-2.** Strong independent agreement on every load-bearing point; two minor divergences resolved below.

## What m11 is

Enforce the non-OA license-truncation policy: `get_chunk` surfaces at most **300 chars** of a NON-open-access chunk's body, with a `truncated_for_license: true` flag; open-access chunks return full text. The `truncated_for_license` flag is documented as a future e5 flag (`ingest/schema.py:165`, `chunker_types.py:129`) — it is a **runtime response flag only, NOT a schema column**; no LanceDB migration.

## The load-bearing correctness invariant (both briefs agree — DO NOT get this wrong)

`server/handlers/chunk.py::handle_get_chunk` current order:
1. `raw_body = row["body_text"] or ""` (line 74)
2. `sanitized_body = sanitize_retrieved_text(raw_body)` (line 75)
3. build `chunk = {"body_text": sanitized_body, ...}` (lines 76-87)
4. `enforce_byte_cap(payload, ..., body_text_path=("chunk","body_text"))` (→ may set `body_truncated` + `resource_link`)
5. `wrap_retrieved_text(...)` — E13_S02 `<retrieved_chunk>` delimiter wrap, AFTER the byte-cap so tags aren't sliced

**m11 inserts license truncation between steps 2 and 3** — the INNERMOST truncation, on the raw sanitized string, BEFORE byte-cap and BEFORE wrap. New order: **sanitize → license-truncate → byte-cap → wrap.**

This ordering is the ONLY one that closes the two CRITICAL leak paths (brief-2 FM-1/FM-2):
- **FM-1**: truncating AFTER the wrap slices the `</retrieved_chunk>` delimiter tag (malformed defense + ~265 effective content chars).
- **FM-2 (headline risk)**: truncating AFTER the byte-cap lets a >256 KB non-OA chunk emit a `resource_link` to the FULL unrestricted body — the agent gets `truncated_for_license=true` but can follow the link to the complete text. Applying license truncation first means the body is always ≤300 chars, so the 256 KB byte-cap NEVER fires on a non-OA chunk and `resource_link` is never emitted. A non-OA chunk can never surface >300 chars via ANY path.

## Scope confirmation: get_chunk is the ONLY full-body surface

brief-2 grepped every `server/handlers/*.py` reader of `body_text`:
- `chunk.py` → full body (the target).
- `search.py` → `_snippet()` slices to `SNIPPET_MAX_CHARS=150` (< 300; never exposes >300).
- `definitions.py` → returns preamble `expansion`, not chunk `body_text`.
- `equation.py` → returns `chunk_id`/`paper_id`/`score` only.
- `lemma.py` → returns `display_name`/metadata only.
- `paper.py` → `abstract` (NULL until E11).

**Conclusion: `get_chunk` is the exclusive leakage surface. License truncation is handler-only, in `get_chunk`.**

## Resolved divergences (orchestrator decisions)

**D1 — helper module name.** brief-1: `server/licensing.py`; brief-2: `server/license_policy.py`. **DECISION: `server/license_policy.py`** — unambiguous (it is the OA-allowlist policy, not generic software licensing), standalone for testability, no circular import with `chunk.py`.

**D2 — add `truncated_for_license` to `search_papers` rows?** brief-1 says YES (informational transparency); brief-2 says NO (150<300 so no truncation ever occurs there; adding a per-row field churns `search_papers_result.json` shape unnecessarily on the final milestone; the agent discovers the restriction via `get_chunk`). **DECISION: NO — `get_chunk` only.** Rationale: the compliance goal is fully met at the only full-body surface; a search-row flag would be informational-only (the 150-char snippet is never further truncated); keeping scope tight on the last milestone avoids a second result-shape change. The `search_papers_result.json` `version` field still bumps to 16 (global echo of `TOOL_SCHEMA_VERSION`), but its per-row shape is unchanged.

**D3 — flag presence when not truncated (brief-2 OQ-2).** **DECISION: present + `true` only when truncation fires; ABSENT otherwise** — mirrors the existing `body_truncated` absent-when-false pattern + the m2 `filters_applied` absent-not-null convention. The agent infers "unrestricted" from the flag's absence + the surfaced `license` token (see D4).

**D4 — surface `license` in the chunk dict (brief-2 OQ-1).** **DECISION: YES** — add `row["license"]` to the `chunk` dict (alongside existing fields) for transparency, so an agent sees the license token directly. Low cost, available via the same Arrow row.

## Policy (confirmed safe to ship as documented default)

`server/license_policy.py`:
- `OA_ALLOWLIST = frozenset({"arxiv-license", "CC-BY", "CC-BY-SA", "CC0", "public-domain", "GFDL"})` — exact-string, case-sensitive.
- `LICENSE_TRUNCATION_CHARS = 300`.
- `is_open_access(license: str | None) -> bool`: `if not license: return False  # FAIL CLOSED (None and "")` then `return license in OA_ALLOWLIST`.

Both briefs + the roadmap `[SHOULD]` (`plans/textbook-ingest-roadmap.md:43` "acceptable to operator") agree the fail-closed allowlist is the safe, legally-defensible default. CC family / GFDL / public-domain are redistributable; `arxiv-license` is the dominant corpus license (classifying it OA preserves no-regression for the existing 100%-arXiv corpus); `author-distributed`/`no explicit license`/empty/unknown → truncate. **No operator sign-off required beyond the roadmap.** Use `str[:300]` slicing (codepoint-safe; FM-3) — NOT bytes.

## Re-pin scope (firm — the m9 lesson applied)

- `TOOL_SCHEMA_VERSION`: 15 → 16 (the get_chunk response envelope grows `truncated_for_license`; bump by convention).
- `EXPECTED_TOOL_SCHEMA_SHA256`: **re-pin** (the `_meta.tool_schema_version` in the wire `tools/list` changes). Regenerate via `pytest tests/test_server_tool_schema.py --update-tool-schema-hash` (it hard-refuses without a version bump — confirmed in m9).
- `EXPECTED_BP1_SHA256`: **NO re-pin.** BP1 hashes only `{name, description}` per tool (`test_prompts.py:464`). m11 does NOT change the GET_CHUNK ToolMeta `description` or any `inputSchema` Field — DO NOT mention the flag in the GET_CHUNK description (that would drift BP1). Verified empirically in m9.
- `search_papers_result.json["version"]` + `["$id"]`: 15 → 16 (global echo; cross-checked by `test_snippet_contract.py` / `test_search_filter.py`). Per-row shape UNCHANGED (D2).
- `lean_verify_result.json["version"]` + `["$id"]`: 15 → 16 (global echo; cross-checked by `test_handlers_lean_verify.py`).
- There is **NO `get_chunk_result.json`** schema file (brief-1 confirmed) — get_chunk returns `envelope(structured)` directly. So no get_chunk schema file to add the field to; the field lands in the response envelope + is documented in `snippet-contract.md`.

## Cache correctness (brief-2)
`get_chunk` does NOT use the 3-tier retrieval cache (it reads LanceDB directly via `chunks_table.search().where(...)`). No cache-key change needed; no stale pre-truncation `get_chunk` response can exist.

## Acceptance criteria → plan
- OA chunk (`arxiv-license`) → full body, no `truncated_for_license`. ✔ get_chunk
- non-OA chunk (`author-distributed`) → body ≤300 chars + `truncated_for_license=true`. ✔
- unknown/empty/None license → fail-closed → truncated. ✔ `is_open_access`
- composes with byte-cap: a >256 KB non-OA body is license-truncated to 300 first, so byte-cap never fires + no resource_link leak. ✔ ordering
- `<retrieved_chunk>` delimiters preserved (truncate inner body, not tags). ✔ ordering
- `snippet-contract.md` documents the policy + allowlist + flag + precedence. ✔
- version bump + tool-schema-hash re-pin (NOT BP1). ✔

## Orchestrator synthesis note
Divergences resolved: D1 (module name → `license_policy.py`), D2 (search_papers flag → NO, get_chunk-only), D3 (absent-when-not-truncated), D4 (surface `license` token). All other points were in unanimous agreement. The FM-1/FM-2 ordering invariant is the single most important implementation constraint and is non-negotiable.

## Open questions
None blocking. D1-D4 above resolve the only design choices both briefs raised.

## External writes the implementation will require
None — purely local. All commits land on `main`.
