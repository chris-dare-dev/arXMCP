# Phase 1 synthesis — source-truth-m3

**Mode:** standard (explore→brief-1, design→brief-2). Both `complete`, 0 injections, both
live-verified. **brief-2 is the decision-complete design** — the implementer follows it; this
synthesis captures the path + the decisions + the landmines.

## The change
Add `arxmcp://corpus-manifest` — a content-addressed, read-only MCP **resource** (generated
on-read from the m1 registry + `corpus-version.json` + `operator_settings`). No corpus mutation,
no backfill, **no go-live**. **Roadmap link is stale:** the target is `server/mcp_resources.py`
(NOT `server/resources.py`, the process-lifecycle dataclass).

## Manifest shape (brief-2 §1, decision-complete)
`{manifest_version, generated_at, content_hash, snapshot:{notebooks:{<slug>:{...}}}}`.
- **`content_hash` = `sha256(json.dumps(snapshot, sort_keys=True, separators=(",",":"), ensure_ascii=True))`**
  over `snapshot` ALONE (the tools/list-hash canonicalization, reused verbatim). `content_hash` /
  `generated_at` / `manifest_version` sit OUTSIDE the hash boundary (read-time/wire metadata).
- Per-notebook: `corpus_version` + chunker/embedder versions + counts (from `read_corpus_version`,
  all-or-null together), `license_summary` (3-way + total, §4.9), `id_shape`, `revisions_digest`
  (`rollup_sha256` all + `active_rollup_sha256` active-only), the full `revisions` list, `override`.
- Per-revision (allowlist-projection — NO `license_uri`, NO per-row chunker_version): `work_id`,
  `arxiv_version`, `raw_source_sha256`+`raw_source_status`, `parse_artifact_sha256`,
  `license_status`, `status`, `invalidated`, `invalidation_reason`. Sorted by `(work_id, arxiv_version)`.
- **Invalidation (AC2):** `invalidated=(status!="active")`, `invalidation_reason=status`
  (`withdrawn`/`superseded`); excluded from `active_rollup_sha256`, retained in the full list +
  `rollup_sha256`. JSON edge ONLY — no Kùzu, no delete. (0 live rows today → needs a synthetic fixture.)

## Recommended layout (brief-2 §7)
New **`server/corpus_manifest.py`** (pure logic: `async build_manifest(store)`, `compute_manifest_hash(snapshot)`,
`rollup_sha256(records)` — FastMCP-independent, unit-testable); `server/mcp_resources.py` gains the
`@mcp_server.resource("arxmcp://corpus-manifest")` registration.

## LANDMINES the implementer MUST handle
1. **`wrap_retrieved_text` silent fallback:** `server/tools.py:574-577` dispatches `kind` through a
   CLOSED dict `.get(kind, _WRAP_TAG_CHUNK)`. A naive `kind="manifest"` silently wraps as
   `<retrieved_chunk>`. **Add `_WRAP_TAG_MANIFEST = "retrieved_manifest"` + a `"manifest":` entry to
   that dict FIRST.** This edit is in the wrap helper, NOT `ALL_TOOLS`/`TOOL_SCHEMA_VERSION` — so
   verify `EXPECTED_TOOL_SCHEMA_SHA256` (`test_server_tool_schema.py`) stays UNCHANGED after it.
2. **Registry-absent degrade:** for a notebook with no `documents.db` (today: the 3 non-hydrated
   notebooks) set `registry_present:false` + OMIT `license_summary`/`revisions`/`revisions_digest`/
   `override`; **never call `DocumentsStore.open()` on a missing file** (it would create an empty db).
3. **Per-notebook failure isolation:** wrap each notebook block in `try/except (sqlite3.DatabaseError,
   OSError, ValueError)` → degrade that ONE notebook to `registry_present:false, registry_error:"..."`,
   never fail the whole `resources/read`. Needs its own test (a truncated non-SQLite `documents.db`).
4. **registry vs corpus counts are separate fields, never reconciled** (fourier-duality: registry 52
   vs corpus paper_count 51 — a legitimate one-off drift).

## Decisions taken (autonomy §12)
1. **Override-SET UX deferred to m4:** m3 READS `license_unknown_override_<slug>` from
   `operator_settings` (default-off; fail-safe-disabled on malformed JSON) and surfaces it. The
   existing `set_setting`/`OperatorSettingsStore.set` API IS the SET path — no new CLI in m3 (m4
   owns the operator UX + the serving/escalation wiring). This satisfies "the manifest RECORDS it".
2. **Full per-revision list** (not rollup-only) — forced by AC1 ("re-verify a specific paper's
   checksum"); +rollup digest for cheap drift-checks. Fine at 197 revisions; scale ceiling flagged.
3. **AC1 "re-fetch" = on-disk re-hash** via `tools/notebook_documents_backfill._hash_raw_source_tree`
   / `_parse_artifact_sha256` (no network — matches this track's idempotency norm).

## Path + acceptance
- **DELEGATED** (~400-500 LOC: new module + resource + wrap-tag + tests). No `allow_large_diff`.
- ACs: AC1 (content_hash recomputes from snapshot; 3-paper on-disk re-hash matches; stability across
  reads). AC2 (invalidated/invalidation_reason; active_rollup excludes; synthetic withdrawn fixture).
  Boundary (net-new TestByteStability for the manifest resource; `EXPECTED_TOOL_SCHEMA_SHA256`
  unchanged). §4.9 (3-way license_summary, `unknown` never folded, constants imported not re-typed).
  Override (default-false for absent AND malformed; read path never writes).
- **Security:** allowlist-projection (only `override.note` is operator-freeform → the
  `TestIndirectPromptInjection` delimiter test); `<retrieved_manifest>` wrap.

## external_writes_required
```yaml
external_writes_required: ["git push origin main"]
```
