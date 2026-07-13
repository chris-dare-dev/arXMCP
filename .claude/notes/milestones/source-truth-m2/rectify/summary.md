# Rectify summary — source-truth-m2

**Rect commit:** `2345b08` (GPG-signed; `Reviewed-by:` both critics; `Co-Authored-By: Claude Opus 4.8`).
4 files (2 production + 2 test). **Critique:** C0 H1 M4 L4. **Invalidation rate:** 1/9 = 11%. **Gate:** OK.

## Fixed (7)

| id | sev | fix |
|----|-----|-----|
| M1 | MED | `test_hit_path_with_real_preamble_roundtrip` — exercises the real `extract_preamble`→chunk_id round-trip (every prior test stubbed `preamble=None`, so a HIT-path regression would pass CI). |
| M2 | MED | `TestMigrateThenHydrate::test_pre_v2_table_migrated_and_hydrated_in_one_run` — a genuine pre-v2 (21-col) table migrated AND hydrated in one run; asserts `columns_added==5`, read-back hydration, `np.array_equal` embeddings (the exact live go-live path). |
| M3 | MED | `test_rerun_failed_abstains` — forces the `chunker_rerun_failed` abstention branch + asserts its reason code + null `source_span` + `truncated` fallback. |
| M4 | MED | Idempotency skip-gate now requires `source_span` resolved (not just `source_revision_id`), so a chunk-id-MISS row re-attempts on re-run instead of freezing at null; docstring corrected. **Adapted:** the critique's "also skip terminal abstentions" half is unimplementable (ingest pre-populates `truncated`/`printed_number`, so terminal-registry papers are byte-identical pre/post + existing abstention tests require first-run processing) — took the minimal `source_span`-conjunct fix that closes the frozen-span bug, empirically re-verified the old gate fails the new test. |
| L1 | LOW | `_PRINTED_NUMBER_RE` no longer fuses a trailing word-letter to a digit (`"Corollary3"`→None, not `"y3"`) + `test_no_space_before_number_declines`; real cases (`A.2`, `1.5.1`, `[Ku] 3.4`) preserved. |
| L2 | LOW | Softened the `_truncated_fallback` "airtight" docstring → "safe-direction in the common case; a boundary re-tokenization can rarely undercount by one token." |
| L3 | LOW | `test_v2_defaults_match_store` pins `_V2_COLUMN_DEFAULTS` == the store's 5 m2 entries (guards silent divergence). |

## Invalidated (1)
- **H1** (HIGH, 1825-LOC diff-size auto-flag): `allow_large_diff` owner-approved (one coherent milestone); 246 tests + the 15,106-row scratch smoke (0 embedding mismatches) mitigate. Not a code defect.

## Deferred (1)
- **L4** (LOW): commit `2572f2f` subject is 51 chars (1 over §4.3). It's landed + GPG-signed; a rebase for 1 char would break history. Noted for future subjects.

## Regression tests
`tests/test_notebook_chunks_backfill.py` (M1/M2/M3/M4/L3), `tests/test_chunker.py` (L1). Gate: the m2 suites + the `tools/list` schema-hash pin green; ruff clean; `_compute_chunk_id` untouched (0 diff lines).

## Go-live (NOT yet run — offered to the owner)
The migration + backfill are built, critiqued, rectified, and **scratch-smoke-validated on the real
15,106-row bridgeland table** (0 embedding mismatches, 14,947 spans resolved, 4 F2 papers flagged).
The live-corpus hydration of both notebooks (19,581 rows — mutates the `chunks` tables in place,
additive + embedding-preserving) is the go-live, run with owner OK + the same bit-identical-embedding
+ resolved-rate verification.

## External write
- `git push origin main` — the m2 code + rect + notes. Owner-authorized per-event.
