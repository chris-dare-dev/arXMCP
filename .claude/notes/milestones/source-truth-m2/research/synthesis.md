# Phase 1 synthesis — source-truth-m2

**Mode:** standard (explore→brief-1, design→brief-2). Both `complete`, 0 injections, both
live-verified against the on-disk corpus + m1 registry. brief-2 empirically resolved the two
open forks brief-1 left (write mechanism; license_ref shape) with isolated scratch-table tests.

## Live ground truth (queried this session)
- **19,581 chunk rows total:** `bridgeland-stability` 15,106 rows / 145 papers; `fourier-duality`
  4,475 rows / 51 papers. `chunker_version` uniformly `v1.1` (0 drift); `parser_used` 100% NULL.
- Registry join is **1:1 live-confirmed** (145/145; 51-of-52 — the 52nd registry row has no chunks
  yet, benign). Zero `work_id` collisions, zero non-empty `arxiv_version`.

## The 5 columns (all appended after `parser_used` in `CHUNKS_SCHEMA_V1`, all `nullable=True`)

| col | type | value | null/abstention |
|---|---|---|---|
| `source_revision_id` | utf8 | `f"{work_id}@{version}"` or bare `work_id` (reuse `_label()`); join by grouping `DocumentsStore.all_records()` by `work_id` | null if paper unregistered / multi-row registry (defensive) |
| `source_span` | utf8 (**JSON string**, not struct) | `{"rev":<16-hex parse_artifact_sha256>,"txt":<64-hex sha256(NFC(ws-collapsed body_text))>,"id":<element-id or "">}`, byte-stable `json.dumps(sort_keys,separators)` | null when `source_revision_id` unresolved OR chunk_id not reproduced by the re-run |
| `truncated` | bool | persist `ChunkRecord.truncated` (currently dropped at `_build_arrow_table`); backfill: exact on chunk-id HIT, else token-recount vs `STMT_MAX_TOKENS` (safe-direction), `proof`→False | **never null** (100% populated) |
| `printed_number` | utf8 | new `_extract_printed_number(tag)` — spike-2 regex `[A-Za-z]?\.?\d+(\.\d+)*` on the `ltx_tag_theorem` text; chunker-native | null when genuinely unnumbered (F1) or uncomputable (tied to source_span miss); not-attempted for proof/section |
| `license_ref` | utf8 | **denormalized `license_status`** (`eligible`/`not-allowlisted-open`/`unknown`) from the matched registry row — NOT a pointer; ADVISORY (serving untouched) | null iff `source_revision_id` null |

## Migration + backfill mechanism (the load-bearing resolution)
- **Migration:** all 5 ride `_migrate_chunks_schema_if_needed`'s existing single-loop SQL-dict
  `add_columns` (one `cast(NULL as ...)` each in `_TEXTBOOK_MIGRATION_DEFAULTS`) — **no struct, no
  new branch** (spike-4). Idempotent (2nd run = 0 add_columns). Note the `textbook-ingest-m2`
  name-collision (a *different* shipped milestone).
- **Backfill write = full-row read-modify-write via `merge_insert("chunk_id").when_matched_update_all()
  .when_not_matched_insert_all()`, mirroring the shipped `ingest/embed_equations.py:82-139`.**
  brief-2 empirically ruled out: `Table.update()` (values_sql rejects a CASE-keyed bulk expr →
  19,581 individual calls) and `write_chunks`/`_build_arrow_table` (embedding-shaped, hard-requires
  an embedding per row). Connect to LanceDB directly; **never import `ingest.embedder`** (structural
  0-re-embed; the chunker's tokenizer-only load is fine — no BGE-M3 forward pass).
- **Backfill compute:** per paper, re-run the chunker on `parsed/<paper_id>/index.html` → fresh
  `chunk_id→ChunkRecord` map; for each existing row, chunk_id HIT → patch the 5 cols exact; MISS →
  `source_span=null`, `printed_number=null`, `truncated` via fallback, still join revision/license.
  Idempotency skip-gate on rows already carrying `source_revision_id`.

## Decisions taken (autonomy per §12; documented, not checkpointed)
1. `license_ref` = denormalized value (brief-2) over pointer (brief-1) — per-chunk license filter
   without a join; matches the existing `license` token-column precedent.
2. `source_span` = JSON string (brief-2) — extensibility/escaping/debuggability; identical migration cost.
3. Migration + backfill in ONE milestone, two decoupled steps (schema auto-migrates on write; the
   hydration CLI is separately-invoked/resumable/idempotent).
4. **Forward-wiring fast-follow:** new-ingest drivers don't consult the registry, so a future paper
   would get `truncated`/`printed_number` but NULL `source_span`/`source_revision_id`/`license_ref`
   until re-backfill (brief-2 Risk 5). Wiring that shut is OUT of m2's 3 ACs → tracked fast-follow.

## Acceptance (roadmap AC1/AC2/AC3)
1. Migration adds the 5 cols, idempotent, existing cols byte-identical (embeddings `np.array_equal`).
2. Backfill hydrates all 5 on both notebooks, **0 re-embed** (structural; verify embeddings bit-identical).
3. Un-anchorable block → `source_span=null`, counted+listed in a per-notebook abstention report
   (by reason code) + the F2 per-paper sanity flag.

## Phase 2 path + SAFETY
- **DELEGATED**, `allow_large_diff` (schema + migration + extractor + backfill CLI + tests ≈ >800 LOC).
- **The implementer must NOT mutate the live corpus.** Build + unit-test + smoke the backfill
  against a **scratch COPY** of each `lancedb/` dir (spike-4's robocopy-then-verify method); hard-gate
  on row-count-unchanged + distinct-chunk_id-unchanged + `embedding_stmt`/`embedding_proof`
  bit-identical. The live-corpus hydration (19,581 rows) is the **go-live**, run post-rectify with
  owner OK + the same verification — NOT during implement.
- m2 does NOT touch `server/handlers/chunk.py` / `server/tools.py` / `ALL_TOOLS` /
  `EXPECTED_TOOL_SCHEMA_SHA256` (get_chunk surfacing is m5) and does NOT modify `_compute_chunk_id`.

## external_writes_required
```yaml
external_writes_required: ["git push origin main"]
```
m2 fetches nothing from arXiv; all inputs are the parsed corpus + m1's registry.
