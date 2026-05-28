# Implementation Summary — textbook-ingest-m11 (e5 part 2 of 2 — CLOSES e5)

**Summary:** `get_chunk` now enforces the non-OA license-truncation policy — a chunk whose `license` is not in the open-access allowlist has its body truncated to 300 chars with a `truncated_for_license: true` flag; open-access chunks return full text. New `server/license_policy.py` holds the fail-closed allowlist. Closes e5 and the textbook-ingest epic.

**Commit range:** `a7da3f0..HEAD` (single feat commit + this summary).

## Acceptance criteria status

| AC | Status | Evidence |
|---|---|---|
| OA chunk → full body, flag false/absent | [x] | `tests/test_handlers_chunk.py::test_open_access_returns_full_body_no_flag`, `::test_gfdl_is_open_access_full_body` |
| non-OA chunk → ≤300 chars + `truncated_for_license=true` | [x] | `::test_non_oa_body_truncated_to_300_with_flag` |
| unknown/empty/None license → fail-closed (truncated) | [x] | `::test_unknown_license_fail_closed`, `::test_empty_license_fail_closed`, `::test_null_license_fail_closed` + `tests/test_license_policy.py` |
| composes with byte-cap; license trunc innermost (no >300 leak via resource_link) | [x] | `::test_non_oa_huge_body_never_emits_resource_link` (300 KB non-OA body → no resource_link, no body_truncated, inner ≤300) + `::test_oa_huge_body_still_byte_capped` (OA path unchanged) |
| `<retrieved_chunk>` delimiters preserved (truncate inner, not tags) | [x] | `::test_delimiter_wrap_intact_after_truncation` |
| `truncated_for_license` present-only-when-true (absent-not-null) | [x] | flag asserted absent on every OA/short-body test |
| get_chunk result schema gains the field; version bump + tool-schema re-pin; NO BP1 re-pin | [x] | no `get_chunk_result.json` exists (envelope-only); `TOOL_SCHEMA_VERSION` 15→16; `EXPECTED_TOOL_SCHEMA_SHA256` re-pinned; BP1 verified stable (GET_CHUNK description unchanged) |
| snippet-contract.md updated (policy + allowlist + flag + precedence) | [x] | new §(g) + §(f) past-tense fixes |
| `is_open_access`/allowlist unit tests | [x] | `tests/test_license_policy.py` (allowlist members, None/empty/unknown, case-sensitivity, frozen) |

## What changed
- **`server/license_policy.py`** (NEW): `OA_ALLOWLIST = frozenset({arxiv-license, CC-BY, CC-BY-SA, CC0, public-domain, GFDL})`, `LICENSE_TRUNCATION_CHARS = 300`, `is_open_access(license_token: str | None) -> bool` (fail-closed on None/"").
- **`server/handlers/chunk.py`**: read `row["license"]`; truncate `sanitized_body` to 300 chars for non-OA chunks BEFORE `enforce_byte_cap` + `wrap_retrieved_text` (the load-bearing FM-1/FM-2 ordering); add `license` to the chunk dict; set top-level `truncated_for_license=True` only when truncation fires.
- **`server/tools.py`**: `TOOL_SCHEMA_VERSION` 15→16 + v16 history note.
- **`server/schemas/search_papers_result.json`** + **`lean_verify_result.json`**: `version`/`$id` 15→16 (global echo; per-row shapes unchanged).
- **`tests/test_server_tool_schema.py`**: `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH=16` re-pinned via `--update-tool-schema-hash`.
- **`tests/test_handlers_lean_verify.py`**: version cross-check 15→16.
- **`.claude/docs/snippet-contract.md`**: new §(g) (full policy) + §(f) past-tense updates.
- **`tests/test_license_policy.py`** + **`tests/test_handlers_chunk.py`** (NEW).

## Design decisions (from synthesis)
- **get_chunk ONLY** (D2): it is the sole full-body surface (search snippet is 150<300; equation/definitions/lemma return no body_text). NOT added to search_papers rows (would be informational-only + churn the search schema).
- **Helper in `server/license_policy.py`** (D1): standalone, testable, no circular import.
- **Flag present-only-when-true** (D3); **`license` token surfaced** (D4).

## External writes required
None — purely local.

## Deviations from the brief
None material. The brief's "research should decide whether non-OA search rows carry the flag" was resolved NO (get_chunk-only) per the synthesis. No `get_chunk_result.json` schema file exists (get_chunk returns `envelope(structured)` directly), so the field lands in the response envelope + is documented in snippet-contract.md rather than in a schema JSON.
