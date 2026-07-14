# Research brief-1 (explore / codebase surface) — license-serving-removal-m1

Role: explore. Driven inline by the orchestrator (hand-driven pipeline from a
non-repo session; bespoke `milestone-researcher` agent type unavailable here).

## The gate as it exists on `main` @ 8045da6

`get_chunk` is the ONLY served surface that returns a full chunk body, and it
truncates that body to 300 chars whenever the chunk's legacy `license` column
token is not in a hardcoded open-access allowlist:

- `server/license_policy.py` — the whole module: `OA_ALLOWLIST` = {arxiv-license,
  CC-BY, CC-BY-SA, CC0, public-domain, GFDL}, `LICENSE_TRUNCATION_CHARS = 300`,
  `is_open_access()` (fail-closed on None/""/unknown).
- `server/handlers/chunk.py:23` imports it; `:94-98` truncates; `:149-154` emits
  `truncated_for_license=True`. `license_token` (`row["license"]`) is also
  surfaced at `:107` as the `chunk.license` field (informational).
- The gate is near-inert on the live corpus today only because every row carries
  the allowlisted `arxiv-license` blanket token — so it fires for nothing now,
  but is latent for any non-allowlisted token (textbook `copyrighted`, etc.).

## Full symbol blast radius (grep-verified, `*.py`)

- Production: `server/handlers/chunk.py`, `server/license_policy.py` (delete).
- Tests: `tests/test_license_policy.py` (whole file = the policy; delete),
  `tests/test_handlers_chunk.py` (`TestGetChunkLicenseTruncation` + the
  `LICENSE_TRUNCATION_CHARS` import).
- No runtime CONSUMER reads `truncated_for_license` (only chunk.py writes it,
  tests assert it) — removal breaks no reader.
- Stale doc/comment references to update: `tools/oai_license.py:28,119,126`
  (points at the module being deleted), `ingest/chunker_types.py:129`,
  `ingest/schema.py:200`, `.claude/docs/snippet-contract.md` §(g).

## Tool-schema version machinery (the load-bearing part)

`get_chunk` response-shape changes bump `server/tools.py::TOOL_SCHEMA_VERSION`,
which is echoed into every tool's `tools/list` `_meta.tool_schema_version` and
therefore into `EXPECTED_TOOL_SCHEMA_SHA256`. Removing `truncated_for_license`
is such a change → bump 18→19 + re-pin hash via
`pytest tests/test_server_tool_schema.py --update-tool-schema-hash` (the flag
rewrites both the hash and `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`, and refuses
unless `TOOL_SCHEMA_VERSION` was bumped first).

Echo consumers that must equal `TOOL_SCHEMA_VERSION`:
- `server/schemas/lean_verify_result.json` `version`
- `server/schemas/search_papers_result.json` `version`
- asserted by `tests/test_handlers_lean_verify.py:179,189`,
  `tests/test_snippet_contract.py:553`, `tests/test_search_filter.py:916`.

BP1 (`EXPECTED_BP1_SHA256`, `tests/test_prompts.py`) hashes {name, description}
only — UNCHANGED (no tool name/description/inputSchema edit).

## PRE-EXISTING m5 REGRESSION (baseline is red)

`source-truth-m5` bumped `TOOL_SCHEMA_VERSION` to 18 and re-pinned the hash but
left every echo at 17: both `*_result.json` files and the three asserting tests
fail `== TOOL_SCHEMA_VERSION`. Confirmed: `test_schema_version_matches_tool_schema_version`
fails `assert 18 == 17`. The consistent-v19 change fixes all of them.
