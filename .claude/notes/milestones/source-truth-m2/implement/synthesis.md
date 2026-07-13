# source-truth-m2 — implementation synthesis

Chunks schema v2: the five source-truth columns + migration + the printed-number
extractor + the 0-re-embed backfill CLI. Built decision-complete against
`research/synthesis.md` + `brief-2.md`; smoked against a scratch copy of the live
`bridgeland-stability` table (live tables untouched).

## Built

### AC1 — migration adds the 5 columns, idempotent, existing cols byte-identical
- **`ingest/schema.py` `CHUNKS_SCHEMA_V1`** (`ingest/schema.py:230-286`): appended
  `source_revision_id` utf8, `source_span` utf8 (**JSON string, not struct**),
  `truncated` `pa.bool_()`, `printed_number` utf8, `license_ref` utf8 — all
  `nullable=True`, after `parser_used`. Schema is now 26 columns.
- **`ingest/store.py` `_TEXTBOOK_MIGRATION_DEFAULTS`** (`ingest/store.py:329-343`):
  one `cast(NULL as string)`/`cast(NULL as boolean)` entry per new column. The
  existing `_migrate_chunks_schema_if_needed` single-loop `add_columns` then
  handles all five unmodified (no struct branch). Idempotent (2nd run = 0
  add_columns) — proven by `test_migration_is_idempotent_for_v2`.

### AC2 — 5-column hydration, 0 re-embed, truncated/printed_number chunker-native
- **`ChunkRecord.printed_number`** (`ingest/chunker_types.py:186-197`) + `to_dict`
  (sorted-position insert, keeps JSON keys sorted).
- **`_extract_printed_number(tag)`** (`ingest/chunker.py:488-551`): spike-2 regex
  `([A-Za-z]?\.?\d+(?:\.\d+)*)[\s.]*$` (`_PRINTED_NUMBER_RE`,
  `ingest/chunker.py:115-124`) over the `ltx_tag_theorem` heading text. Handles
  the real LaTeXML shape where the tag span is **nested inside** the `ltx_title`
  h6 (searches direct-child headings for the span, tries the clean span before
  the parenthetical-bearing full heading), scoped to direct children per the F9
  no-nested-theorems discipline. Reads rendered text only (never the id/class →
  spike-2 §3e).
- **Wiring** (`ingest/chunker.py:686-691, 727-737, 749-760`): called at the
  theorem-scan site; stmt + paired proof carry it (proof inherits, like
  `theorem_name`/`theorem_label`); orphan proof / section leave `None`.
- **`_build_arrow_table`** (`ingest/store.py:551-566`): persists `truncated`
  (previously dropped) + `printed_number`; the three registry-derived columns
  stay `NULL` on a new write (forward-wiring fast-follow, synthesis Decision 4).
- **Backfill compute** (`tools/notebook_chunks_backfill.py`
  `_rechunk_paper` :286-353, `_source_span_json` :225-241, `_truncated_fallback`
  :250-267): per paper re-runs the chunker extraction (mirrors `_chunk_paper_impl`
  up through chunk_id, **no JSON side effect**), registry join grouped by
  `work_id` (`_load_registry` :360-380), HIT → exact 5 cols; MISS → source_span/
  printed_number null + truncated fallback + still-joined revision/license.

### AC3 — un-anchorable → null, counted + listed by reason + F2 flag
- **`_patch_notebook`** (`tools/notebook_chunks_backfill.py:437-575`): source_span
  null reason codes `no_source_revision` / `html_missing` / `chunker_rerun_failed`
  / `chunk_id_not_reproduced`; printed_number `numbered`/`unnumbered_f1`/
  `uncomputable`/`not_attempted`; the F2 per-paper sanity flag (`_detect_f2` :270-283).
- **Report** (`_print_report` :406-470): loud machine-parseable per-notebook block +
  a capped `(chunk_id, reason)` listing on stderr.
- **Write mechanism**: ONE `merge_insert("chunk_id").when_matched_update_all()
  .when_not_matched_insert_all()` per notebook, batch built against the live
  `table.schema` (lossless float32 round-trip). **Never imports `ingest.store` or
  `ingest.embedder`** (structural 0-re-embed; `CHUNKS_TABLE_NAME` literalized to
  avoid the `ingest.schema`→embedder transitive import). Self-contained
  `_ensure_v2_columns` (:388-404) adds any missing v2 columns so the CLI works on
  an unmigrated copy. Idempotency skip-gate on non-null `source_revision_id`.

## Files touched
- `ingest/schema.py` (M) — 5 columns + docstring.
- `ingest/store.py` (M) — migration defaults + `_build_arrow_table` row dict + docstring.
- `ingest/chunker.py` (M) — `_PRINTED_NUMBER_RE`, `_extract_printed_number`, wiring.
- `ingest/chunker_types.py` (M) — `printed_number` field + `to_dict`.
- `tools/notebook_chunks_backfill.py` (NEW, 736 lines) — the backfill CLI.
- `tests/test_store.py` (M) — v2 migration + truncated round-trip; 21→26 count updates.
- `tests/test_chunker.py` (M) — `_extract_printed_number` unit + wiring tests.
- `tests/test_notebook_chunks_backfill.py` (NEW, 531 lines) — backfill suite.

## Scratch-copy smoke results
Copy of live `var/arxmcp/notebooks/bridgeland-stability/{lancedb,documents.db}` →
scratch; backfill run against the COPY (live parsed HTML + preamble cache read-only).
- **row_count**: 15,106 → 15,106 (unchanged); **distinct chunk_id** unchanged.
- **cols**: 21 → 26 (added the 5); **embedding_mismatch_count = 0** over all 15,106
  rows (`embedding_stmt` + `embedding_proof` bit-identical via `np.array_equal`).
- **truncated** populated 15,106/15,106 (true=182, false=14,924).
- **source_revision_id / license_ref** resolved 15,106/15,106 (registry join 145/145 papers).
- **source_span** resolved 14,947 / null 159 (all `chunk_id_not_reproduced`, listed;
  ~99.0% — misses concentrate on a very-new paper `2510.22432`, correct abstention).
- **printed_number** numbered 10,547 / unnumbered_f1 447 / uncomputable 86 /
  not_attempted 4,026.
- **F2 flagged 4 papers**: `alg-geom/9606006` (known spike-2 F2), `hep-th/0002037`,
  `hep-th/0212218`, `2411.18554`.
- backfill exit 0, 248.6s.

## Test deltas
- `tests/test_store.py`: +`TestSourceTruthM2SchemaMigration` (5 tests: adds-5 /
  types / nullability / idempotent) + `TestTruncatedPersistsRoundtrip` (NEW —
  truncated + printed_number survive round-trip); updated `==21`→`==26` and
  `len(added)==8`→`==13`.
- `tests/test_chunker.py`: +`TestPrintedNumberExtraction` (9) +
  `TestPrintedNumberWiredIntoChunks` (1).
- `tests/test_notebook_chunks_backfill.py`: NEW 17 tests (helpers, 0-re-embed
  import-scan + embedding bit-identity, HIT all-5, report tokens, 4 abstention
  reason codes + F2, idempotent re-run, hard errors).

## Check gate
- `pytest tests/test_store.py tests/test_chunker.py tests/test_notebook_chunks_backfill.py`
  → **231 passed** (`.venv/Scripts/python.exe`, `-p no:warnings`).
- `ruff check` clean on all 8 files.
- `tests/test_server_tool_schema.py` still passes (no tool-surface drift — adding
  LanceDB columns is invisible to `handle_get_chunk`'s field projection). Related
  read-path suites green: `test_chunker_ids`, `test_re_embed`, `test_theorem_names`,
  `test_equation_index`, `test_notebook_documents_backfill`, `test_handlers_chunk`,
  `test_search_filter`.
- Did NOT touch `server/handlers/chunk.py`, `server/tools.py`, `ALL_TOOLS`,
  `EXPECTED_TOOL_SCHEMA_SHA256`, or `_compute_chunk_id`.

## Live tables untouched (confirmed)
The backfill ran ONLY against the scratch copy. Post-smoke: live
`bridgeland-stability` chunks table = 15,106 rows / 21 cols (unmigrated), and
`documents.db` mtime + size unchanged. The re-chunk read the live parsed HTML +
preamble cache read-only (`extract_preamble` short-circuits to the existing cache
for the already-ingested corpus). No live `var/arxmcp/notebooks/*/lancedb/` was
written. Live-corpus hydration (both notebooks) is the go-live, deferred to the
orchestrator with owner OK.

## Commits
- `2572f2f` feat(ingest): chunks schema v2 columns + printed-number extractor
  (6 files; GPG-signed; Co-Authored-By: Claude Opus 4.8).
- `ac0ff62` feat(tools): chunks schema v2 backfill CLI + abstention report
  (2 files; GPG-signed; Co-Authored-By: Claude Opus 4.8).
Explicit pathspecs only (tree concurrently dirty); both signatures verified `G`.
