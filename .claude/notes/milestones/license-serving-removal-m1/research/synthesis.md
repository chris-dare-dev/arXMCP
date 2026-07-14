# Research synthesis — license-serving-removal-m1

Hand-driven pipeline (non-repo session; `/milestone-pipeline` + bespoke agents
unavailable). Owner directive: licensing drives NO serving decision; never
truncate/limit; treat all materials as owned. This milestone REMOVES the
existing 300-char license-truncation gate so that invariant holds in code.

## Affected files (deduped)

### Production
- `server/handlers/chunk.py` — drop the `license_policy` import + the truncation
  gate + the `truncated_for_license` emit; keep `chunk.license`/`license_ref` as
  informational metadata; fix stale comments.
- `server/license_policy.py` — DELETE (whole module is the truncation policy).
- `server/tools.py` — `TOOL_SCHEMA_VERSION` 18→19 + v19 changelog entry.
- `server/schemas/lean_verify_result.json` — `version` 17→19.
- `server/schemas/search_papers_result.json` — `version` 17→19.
- `tools/oai_license.py` — comments referencing the deleted module (advisory
  `decide_license_status` stays; no serving gate exists anymore).

### Tests
- `tests/test_license_policy.py` — DELETE.
- `tests/test_handlers_chunk.py` — remove `LICENSE_TRUNCATION_CHARS` import;
  replace `TestGetChunkLicenseTruncation` with full-body-regardless-of-license
  tests + the required regression (non-OA/unknown/null → full body, no flag);
  keep `TestGetChunkSourceTruthFields`.
- `tests/test_handlers_lean_verify.py` — assertion `== 17` → `== 19` + history
  entries (17→18 m5, 18→19 this milestone).
- `tests/test_server_tool_schema.py` — `EXPECTED_TOOL_SCHEMA_SHA256` +
  `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` re-pinned via `--update-tool-schema-hash`.

### Docs / comments
- `.claude/docs/snippet-contract.md` — §(g) rewrite: `get_chunk` no longer
  truncates on license.
- `ingest/chunker_types.py`, `ingest/schema.py` — stale `truncated_for_license`
  comments.

## Acceptance criteria (from brief, CORRECTED)

1. `get_chunk` returns full sanitized body for ANY license token (null/""/
   copyrighted/unknown) — no `truncated_for_license` field.
2. No license value gates body length/content in `server/`; size-based byte-cap
   + resource_link path unchanged.
3. `server.license_policy` removed; no importer relies on its truncation.
4. **CORRECTED**: `TOOL_SCHEMA_VERSION` bumps 18→19 (response-shape change, per
   the repo convention) and `EXPECTED_TOOL_SCHEMA_SHA256` re-pins — NOT
   "unchanged" as the brief first assumed. BP1 unchanged.
5. `make test` green (ruff + pytest) with a new full-body regression test and the
   obsolete truncation tests removed.
6. `snippet-contract.md` §(g) corrected.
7. **NEW (folded in per owner (a)):** the pre-existing source-truth-m5
   version-echo regression (both `*_result.json` + 3 tests stranded at 17) is
   fixed by the consistent-v19 end state.

## external_writes_required

`[]` — local code change only. No push/publish/deploy required to complete
(push remains a separate user-gated action; the pipeline never pushes).

## Open questions

None outstanding — owner ratified the consistent-v19 approach (option a).

## Path decision

Inline (deletions + version bumps + comment fixes; ~11-12 files, no novel
architecture, well under 300 net LOC).
