# Implementation synthesis — license-serving-removal-m1

Path: **inline**. Base `2698ac8` → feat `b6b77be`. 13 files, net **-231 LOC**
(removal-heavy).

## What changed
- **`server/handlers/chunk.py`** — removed the `license_policy` import + the
  non-OA 300-char truncation gate + the `truncated_for_license` emit. Full
  sanitized body is now returned for every license; `license`/`license_ref`
  kept as informational provenance. Only length safeguard left is the 256 KB
  byte-cap.
- **`server/license_policy.py`** + **`tests/test_license_policy.py`** — DELETED
  (whole module was the truncation policy; no other importer).
- **`server/tools.py`** — `TOOL_SCHEMA_VERSION` 18→19 + v19 changelog entry.
- **`server/schemas/{lean_verify,search_papers}_result.json`** — `version` +
  `$id` → 19, changelog entries added (also closing the m5 17→18 echo gap).
- **`tests/test_handlers_lean_verify.py`** — version-echo assertion 17→19 +
  history (17→18 m5, 18→19 this milestone).
- **`tests/test_server_tool_schema.py`** — `EXPECTED_TOOL_SCHEMA_SHA256` +
  `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` re-pinned to 19 via the guarded
  `--update-tool-schema-hash` flow.
- **`tests/test_handlers_chunk.py`** — truncation suite → full-body suite +
  parametrized regression (arxiv/GFDL/CC-BY/author-distributed/copyrighted/
  unknown/""/null all return full body, no flag).
- **`tools/oai_license.py`**, **`ingest/{chunker_types,schema}.py`** — de-staled
  comments that referenced the deleted module / removed flag.
- **`.claude/docs/snippet-contract.md`** — §(g) rewritten (truncation REMOVED),
  §(h) updated.

## Gate results
- `ruff check .`: **clean**.
- Focused affected tests (server_tool_schema, handlers_chunk, handlers_lean_verify,
  snippet_contract, search_filter, prompts, bootstrap_mode, equation_index): **green**.
- Full suite: **green EXCEPT 2 PRE-EXISTING failures** —
  `test_textbook_chunker.py::{TestGoldenFixture,TestTheoremRemarkProofPairingAudit}::test_matches_golden`.
  Stash-verified: they fail **identically on the base commit** (no chunker logic
  touched here), so they are pre-existing golden-fixture drift from an earlier
  milestone, orthogonal to this one. Flagged for a separate fix.

## No-leak verification
`get_chunk` was the ONLY full-body serving surface. `search_papers` snippet is a
150-char size-based preview (unrelated to license); `find_equation` /
`get_definitions` / `find_lemma_by_name` return no `body_text`. No runtime
consumer reads `truncated_for_license` (grep-verified across `*.py`).
