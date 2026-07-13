# source-truth-m3 implementation synthesis — `arxmcp://corpus-manifest`

The content-addressed, read-only corpus-provenance MCP resource, generated on-read
from the m1 registry + `corpus-version.json` + `operator_settings`. No corpus
mutation, no backfill, no persisted `manifest.json`, no go-live.

## Built

- **[AC1] content_hash over `snapshot` alone.** `compute_manifest_hash(snapshot)`
  (`server/corpus_manifest.py:117`) uses the exact `sort_keys=True,
  separators=(",",":"), ensure_ascii=True` convention as
  `tests/test_server_tool_schema.py::_serialize_tools`. `build_manifest`
  (`server/corpus_manifest.py:459`) returns `{manifest_version, generated_at,
  content_hash, snapshot:{notebooks:{…}}}` with the hash computed over `snapshot`
  ALONE — the three wire/read-time fields sit outside the boundary. Verified by
  `TestContentHash::test_content_hash_recomputes_from_snapshot` +
  `test_content_hash_excludes_wire_metadata`.
- **[AC1] on-disk re-hash, no network.** `TestOnDiskRehash` recomputes
  `_parse_artifact_sha256` (always) + `_hash_raw_source_tree` (when
  `raw_source_status="present"`) from `tools/notebook_documents_backfill.py`
  against 3 real `bridgeland-stability` papers and asserts equality with the
  manifest's reported checksums (data-precondition skip if unhydrated).
- **[AC1] stability.** `TestContentHash::test_reading_twice_is_stable` — two reads
  of unchanged data reproduce identical `content_hash` +
  `rollup_sha256`/`active_rollup_sha256`.
- **[AC2] invalidation edges.** `rollup_sha256` (`server/corpus_manifest.py:154`,
  brief-2 §1.6 positional key incl. `license_status`+`status`), `_revision_entry`
  (`:246`) sets `invalidated = status != active` + `invalidation_reason`,
  `_revisions_digest` (`:280`) excludes non-active from `active_rollup_sha256`
  while retaining them in the full list + `rollup_sha256`. Synthetic
  `upsert_records` withdrawn/superseded fixtures in
  `TestInvalidation`; the free `0-invalidated → rollup==active_rollup` invariant
  asserted too.
- **[§4.9] 3-way license census.** `_license_summary`
  (`server/corpus_manifest.py:204`) imports `LICENSE_STATUS_*` from
  `tools.oai_license` (never re-typed); `unknown` never folded into
  `not-allowlisted-open`; explicit `total`. `TestLicenseSummary`.
- **[override] read-only, fail-safe-disabled.** `_read_override`
  (`server/corpus_manifest.py:340`) reads `license_unknown_override_<slug>` via a
  short-lived `OperatorSettingsStore` (file-existence-guarded so it never creates
  a DB), defaults OFF for absent key AND for malformed JSON / missing-or-non-bool
  `enabled` (WARNING-logged, never raised). Never calls `set`/`set_setting`.
  `TestOverride` (6 cases incl. `test_read_path_creates_no_settings_file`).
- **[degrade + isolation]** registry-absent → `registry_present:false`, registry
  sub-blocks omitted, `documents.db` never opened/created
  (`_build_notebook_block` `:397`); per-notebook `try/except (sqlite3.DatabaseError,
  OSError, ValueError)` (+ `NotebookError` on the dir guard) degrades ONE notebook
  to `registry_present:false` + `registry_error` (exception class name only — full
  detail logged server-side, no host-path leak). `TestRegistryDegrade` incl. a
  truncated non-SQLite `documents.db` isolating to one notebook.
- **wrap-tag landmine fixed.** `server/tools.py:534` adds
  `_WRAP_TAG_MANIFEST = "retrieved_manifest"` and `:590` the
  `"manifest": _WRAP_TAG_MANIFEST` dispatch entry — in `wrap_retrieved_text`, NOT
  `ALL_TOOLS`. `TestIndirectPromptInjection` proves the payload wraps as
  `<retrieved_manifest>` (not `<retrieved_chunk>`) and that an `override.note`
  delimiter-breakout is escape-on-emit neutralized.
- **resource registration.** `server/mcp_resources.py:60`
  `CORPUS_MANIFEST_URI = "arxmcp://corpus-manifest"`; a third
  `@mcp_server.resource(...)` fn `_corpus_manifest` (`:215`) calling
  `corpus_manifest.build_manifest(_require_store())` + `_wrap_json(…, kind="manifest")`
  (`_wrap_json` generalized to take `kind`, default `"notebook"`, `:91`).

## Files touched

- `server/corpus_manifest.py` — NEW (pure builder + hash + rollup + I/O helpers).
- `server/tools.py` — `_WRAP_TAG_MANIFEST` + dispatch entry + docstring `kind` note.
- `server/mcp_resources.py` — URI const, `_wrap_json(kind=…)`, third resource, import, `__all__`.
- `tests/test_corpus_manifest.py` — NEW (24 tests).

## Schema-hash unchanged (confirmed)

`tests/test_server_tool_schema.py` passes untouched: `EXPECTED_TOOL_SCHEMA_SHA256`
= `5189d7a6…ad394`, `TOOL_SCHEMA_VERSION=18` — NOT re-pinned. The wrap-tag edit is
in the helper, not the tool surface. The net-new
`TestManifestByteStability::test_tools_list_hash_unchanged_with_manifest_resource`
pins the invariant with the manifest resource registered; `…_adds_no_tools`
asserts the 8-tool count.

## Test deltas

+24 tests (`tests/test_corpus_manifest.py`), 0 removed, 0 re-pinned. All prior
resource/schema/delimiter tests still pass.

## Check gate

- `pytest tests/test_mcp_resources.py tests/test_server_tool_schema.py
  tests/test_corpus_manifest.py -q -p no:warnings` → 50 passed, 1 skipped
  (win32 symlink test in test_mcp_resources.py).
- `tests/security/test_delimiters.py` → 48 passed (no wrap-helper regression).
- `ruff check server/corpus_manifest.py server/mcp_resources.py server/tools.py`
  → clean.

## Commit

`feat(server): arxmcp://corpus-manifest resource` — explicit pathspecs
(concurrently-dirty tree), GPG-signed, `Co-Authored-By: Claude Opus 4.8`. Sha
recorded in the returned JSON.
