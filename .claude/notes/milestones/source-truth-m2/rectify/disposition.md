# Rectification disposition — source-truth-m2

Rectifier protocol closure of the merged critique (`critique/dedup.md`,
severity counts C0 H1 M4 L4). H1 (diff-size flag) and L4 (commit subject nit)
need no code and were left per the task. M1–M4, L1–L3 are closed below. No
commit / git run (orchestrator commits). Gate green; ruff clean.

Files changed (stage by explicit pathspec):

- `ingest/chunker.py`
- `tools/notebook_chunks_backfill.py`
- `tests/test_chunker.py`
- `tests/test_notebook_chunks_backfill.py`

---

## M1 — HIT path's real (non-empty) preamble round-trip untested — FIXED (test-only)

Added `tests/test_notebook_chunks_backfill.py::TestRealPreambleRoundTrip::test_hit_path_with_real_preamble_roundtrip`
(class at :580). Builds the table AND runs `backfill.run(...)` through the SAME
non-empty-`preamble_text` resolver (a stable `PreambleDoc`), so the stored
chunk_ids are `hash(preamble_text + body_text)` and the driver's
`_rechunk_paper` `preamble_doc is not None` branch (chunker.py extraction seam,
`run()`'s `resolve_preamble = _resolve_preamble_doc` default) is exercised — the
branch every prior test bypassed with `preamble=None`. Asserts the backfill
reproduces the chunk_ids (HIT), `preamble_ref` matches the non-empty hash, and
`source_span` resolves non-null (with the authoritative `txt` hash) plus
`printed_number="1.1"` on the theorem rows (printed_number is set only on a HIT,
so it double-proves reproduction). Two shared test helpers added:
`_nonempty_preamble()` and an optional `resolve_preamble=` param on
`_build_table_from_html`.

## M2 — add_columns→hydrate composition (21→26 col) untested — FIXED (test-only)

Added `tests/test_notebook_chunks_backfill.py::TestMigrateThenHydrate::test_pre_v2_table_migrated_and_hydrated_in_one_run`
(class at :647). Materializes a genuine pre-v2 (21-col) table at
`pa.schema(list(CHUNKS_SCHEMA_V1)[:-5])` holding real HIT-reproducible rows +
embeddings (harvested from a throwaway `write_chunks` build, then re-created at
the notebook path — no `drop_table`), runs the backfill via `_patch_notebook`,
and asserts (a) `report.columns_added == 5` (the exact 5 names — this exercises
`_ensure_v2_columns`, backfill.py:532, which every other test made a no-op),
(b) the 5 columns hydrated non-null read BACK from disk on the HIT paper (all 5
on the theorem stmt row; the always-set four on every row — the section row's
`printed_number` is legitimately None/F1), (c) `embedding_stmt`/`embedding_proof`
`np.array_equal` pre/post. Schema is now 26 cols post-run.

## M3 — `chunker_rerun_failed` abstention branch uncovered — FIXED (test-only)

Added `tests/test_notebook_chunks_backfill.py::TestRerunFailedAbstention::test_rerun_failed_abstains`
(class at :768). Patches `backfill._extract_chunks_from_container` to raise a
`ValueError` (a `PER_PAPER_FAILURE_EXCEPTIONS` member), so `_rechunk_paper`'s
real try/except converts it to `status="rerun_failed"` — covering BOTH the
resilience envelope AND the previously-uncovered `_patch_notebook` branch
(`elif rr.status == "rerun_failed"`, backfill.py:615). Registers the paper so
the abstention is reason-coded `chunker_rerun_failed` (not `no_source_revision`).
Asserts `report.source_span_null_reasons["chunker_rerun_failed"] == total_rows`
(>= 1), `rev_resolved == total_rows`, and on the read-back rows: `source_span`
null, `printed_number` null, `truncated` still populated via the fallback.

## M4 — idempotency skip-gate froze source_span abstentions — FIXED (prod + test)

**Prod change** (`tools/notebook_chunks_backfill.py:557`, the skip-gate; +
module docstring :46; ~10 LOC logic): the gate now skips a paper only when every
row carries BOTH a non-null `source_revision_id` AND a non-null `source_span`
(fully hydrated), instead of `source_revision_id` alone. This lets a
registry-HIT + chunk-id-MISS row (revision resolved, span still null) be
RE-attempted on a re-run so a chunker upgrade that reproduces the id resolves
the span — it is no longer frozen.

**Anchor adapted (noted per task).** The critique's proposed "OR its abstention
is provably terminal (registry-missing / ambiguous) → skip" half is NOT
implementable as specified and was deliberately not taken, because live code
diverges from the finding's premise: `ingest/store.py::_build_arrow_table`
(:588–589) already writes `truncated` / `printed_number` at ingest (they are
chunker-native), and leaves ONLY the three registry-derived columns
(`source_revision_id` / `source_span` / `license_ref`) null. Consequences:
(1) a registry-missing/ambiguous paper is byte-identical before and after the
backfill (registry cols null, chunker-native cols already set), so a
"skip-terminal-abstention-on-re-run-only" cannot be distinguished from a
first-run skip by any stored column value; and (2) the existing
`TestAbstention::test_registry_missing_abstains` /
`test_ambiguous_multi_row_registry_abstains` require those papers to be
PROCESSED on the first run (they assert the abstention counts AND
`printed_number="1.1"` from the re-chunk). Skipping terminal abstentions would
break both existing tests and drop the report counts. The minimal, correct,
test-consistent fix is the `source_span` conjunct alone (which is exactly what
closes the frozen-span bug the finding centers on); terminal-registry papers
continue to re-chunk each run (a value-level write no-op, embeddings preserved),
matching pre-existing behavior. The module + inline docstrings were updated to
state this actual guarantee (not the overstated "writes nothing" claim).

**Test:** `tests/test_notebook_chunks_backfill.py::TestSpanReattempt::test_span_null_rerun_reattempts_when_ids_reproduce`
(class at :816). Run 1 re-chunks under a NON-matching preamble (all chunk-id
MISS → `source_span` null though `source_revision_id` resolved — asserted on the
`mid` read-back, the exact frozen precondition the old gate preserved); run 2
re-chunks under the matching preamble (HIT → `source_span` resolves). Asserts
`embedding_stmt`/`embedding_proof` `np.array_equal` across both runs. Under the
old `source_revision_id`-only gate, run 2 would skip and the span would stay
null, so the test is a real guard, not a tautology.

## L1 — printed-number regex fused a trailing word-letter to a digit — FIXED (prod + test)

**Prod change** (`ingest/chunker.py:130`): `_PRINTED_NUMBER_RE` gains a leading
`(?:^|[\s(\[])` (start-of-string or a whitespace/bracket boundary) before the
optional appendix letter, so `"Corollary3"` no longer captures `"y3"` (now
declines → None). Comment above the pattern updated. **Test:**
`tests/test_chunker.py::TestPrintedNumberExtraction::test_no_space_before_number_declines`
(:747) — `"Corollary3"` → None, plus regression guards that the real cases still
resolve (`Theorem A.2`→`A.2`, `Lemma 1.5.1`→`1.5.1`, `Theorem [Ku] 3.4`→`3.4`).
Empirically verified old vs new against all existing cases before editing.

## L2 — `_truncated_fallback` "airtight" docstring overstated — FIXED (docstring-only)

`tools/notebook_chunks_backfill.py:241` — replaced the "airtight" claim with
"Safe-direction in the common case … NOT an airtight invariant … a boundary
re-tokenization can rarely undercount by one token (a BPE merge at the cut
yielding `max_tokens - 1`) … one token, MISS-path-only, advisory column."
No behavior change.

## L3 — duplicated v2 default map had no drift guard — FIXED (test-only)

Added `tests/test_notebook_chunks_backfill.py::test_v2_defaults_match_store`
(:886). Imports both `ingest.store._TEXTBOOK_MIGRATION_DEFAULTS` and
`backfill._V2_COLUMN_DEFAULTS` (importing `ingest.store` in a TEST is fine — the
0-re-embed guarantee binds the driver's import graph, not the test's) and
asserts the 5 shared keys' cast SQL are byte-equal, so a future single-map edit
that diverges the driver's self-contained migration from the store's fails CI.

---

## Gate

- `pytest tests/test_notebook_chunks_backfill.py tests/test_chunker.py
  tests/test_store.py tests/test_server_tool_schema.py -q -p no:warnings`
  → **246 passed** (was 240 pre-rectify; +6 regression tests).
- `ruff check tools/notebook_chunks_backfill.py ingest/chunker.py` → clean
  (also clean on the two touched test files).
- Untouched per task: `server/handlers/chunk.py`, `server/tools.py`,
  `ALL_TOOLS`, `EXPECTED_TOOL_SCHEMA_SHA256`, `_compute_chunk_id`. No live
  `var/arxmcp/notebooks/*/lancedb/` run (tests use tmp tables). No git.
