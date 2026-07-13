# Critique — source-truth-m2 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** 880fcfd..ac0ff62
**Diff stats:** 8 files, +1825/-14 LOC
**Critique format version:** 1.0

## Verdict

SHIP. The three load-bearing invariants of the chunks-schema-v2 milestone are all clean: `_compute_chunk_id` is untouched and none of the five new fields feed it (chunk_id still hashes `preamble_text + NFC(body_text)` only); the 0-re-embed guarantee is structural (`ingest.store`/`ingest.embedder` kept out of the driver import graph) AND empirically pinned by a `np.array_equal` pre/post test on real synthetic embeddings; and the MCP tool surface (`server/tools.py`, `ALL_TOOLS`, `EXPECTED_TOOL_SCHEMA_SHA256`) is not touched by the range. The findings below are edge-path, coverage, and operational-sharp-edge refinements — none corrupt data (every failure mode degrades to a counted, reported NULL abstention), and go-live remains a separate owner-gated step.

## Executive summary

- [CLEAN] Axis 1 (PRIMARY, cache byte-stability): `source_span` JSON is emitted byte-stably via `json.dumps(sort_keys=True, separators=(",",":"))` and unit-pinned; `_compute_chunk_id` is byte-for-byte unchanged and the new `printed_number` is documented + wired as chunk_id-independent; the `tools/list` BP1 pin is untouched.
- [CLEAN] 0-re-embed is both structural (import-scan test) and empirical (`np.array_equal` on `embedding_stmt`/`embedding_proof` pre/post over a real write→read round-trip); the full-row `merge_insert("chunk_id")` mirrors the shipped `embed_equations.py`.
- [CLEAN] Axis 2 math fidelity: the printed-number extractor reads the rendered heading via the math-preserving `_element_text`, never mutates `body_text`/preamble, and cannot disturb any chunk_id or embedding.
- [MEDIUM] M1: the idempotency skip-gate keys on `source_revision_id`, so a registry-HIT + chunk-id-MISS row is permanently frozen at `source_span=null` on every future run with no `--force` to re-attempt.
- [MEDIUM] M2: no test exercises the REAL `extract_preamble`→chunk_id round-trip — every backfill test stubs preamble to `None` on both build and backfill, so a preamble-resolution divergence (the sole HIT-path dependency) would pass CI and surface only as a low `resolved=` count in the go-live report.
- [MEDIUM] M3: the `chunker_rerun_failed` abstention reason-code branch has no covering test (a `PER_PAPER_FAILURE_EXCEPTIONS` during re-chunk is never triggered).
- [LOW] L1: `_truncated_fallback`'s "airtight" claim is slightly overstated — boundary re-tokenization is not guaranteed monotonic, so a MISS on a truncated stmt can rarely mis-report complete.
- [LOW] L2: the backfill's `_V2_COLUMN_DEFAULTS` duplicates `ingest.store._TEXTBOOK_MIGRATION_DEFAULTS`' five m2 entries with no test pinning them equal.

## Findings

**M1 — Idempotency skip-gate freezes source_span abstentions after revision resolves** (MEDIUM)

**Where:** `tools/notebook_chunks_backfill.py:549`
**Anchor:** `if all(row.get("source_revision_id") is not None for r`
**What:** A paper is skipped on re-run when all its rows carry a non-null `source_revision_id`, but `source_revision_id` is set whenever the registry resolves — independent of whether `source_span`/`printed_number` resolved — so a registry-HIT + chunk-id-MISS row is skipped forever with `source_span=null` and can never be re-attempted.
**Why it matters:** After a future chunker fix that would now reproduce the chunk_id, an operator re-running the backfill cannot recover those abstained spans (there is no `--force`/`--reattempt`); they would have to hand-NULL `source_revision_id` first. On the static live corpus this is rare (chunk-id MISS is expected near-zero), but the docstring frames idempotency purely as a benefit and never states this terminal-abstention consequence.
**Proposed fix:** Add a `--reattempt-spans` flag that re-chunks papers even when the revision is already resolved but `source_span` is still null on some rows; OR key the skip-gate on "all five columns resolved OR the paper's abstention is provably terminal (unregistered/ambiguous)" rather than on `source_revision_id` alone. Minimal change (<30 LOC).
**Regression-guard:** A test that (1) runs the backfill with a fabricated-id table + resolvable registry → `source_revision_id` set, `source_span=null`; (2) fixes the ids to reproduce; (3) re-runs and asserts the spans now resolve under the flag (and remain skipped without it, documenting the current behavior).
**Source critic:** milestone-arxmcp-critic
**Source axis:** Axis 8 — test surface / Axis 1 — cache byte-stability

**M2 — HIT path's real preamble round-trip is never tested (all tests stub preamble to None)** (MEDIUM)

**Where:** `tools/notebook_chunks_backfill.py:691`
**Anchor:** `resolve_preamble = _resolve_preamble_doc`
**What:** Every `tests/test_notebook_chunks_backfill.py` case builds the table with `_resolve_preamble_doc` patched to `lambda _pid: None` AND runs the backfill with `resolve_preamble=lambda _pid: None`, so chunk_ids match by construction; the production default (`_resolve_preamble_doc` → `extract_preamble`) — the SOLE HIT-path dependency for `source_span`/`printed_number` reproduction — is exercised by no test.
**Why it matters:** If backfill-time preamble resolution ever diverges from ingest-time (raw `.tex` gone/changed, cache inconsistency), `_compute_chunk_id` differs, every chunk MISSes, and `source_span` goes uniformly null. This is NOT silent (the report prints `source_span: resolved=0 null=N` and the go-live SAFETY checklist would catch it), but a regression in `extract_preamble` reproducibility would pass the entire CI suite. The empirical 0-re-embed smoke does not cover this: embeddings are preserved on a MISS too, so "0 embedding mismatches on 15,106 rows" says nothing about the resolved-rate.
**Proposed fix:** Add one test that builds a fixture with a NON-empty preamble via the real `extract_preamble` seam (or a preamble doc with a stable `preamble_text`/`preamble_hash`) and asserts the backfill reproduces the chunk_ids and resolves `source_span` for the theorem rows. Separately, make the post-rectify go-live gate assert `resolved/rows >= <threshold observed in the scratch smoke>`, not just embeddings-preserved.
**Regression-guard:** `tests/test_notebook_chunks_backfill.py::test_hit_path_with_real_preamble_roundtrip` (non-None preamble, asserts `source_span` resolved).
**Source critic:** milestone-arxmcp-critic
**Source axis:** Axis 8 — test surface

**M3 — `chunker_rerun_failed` abstention branch is uncovered** (MEDIUM)

**Where:** `tools/notebook_chunks_backfill.py:615`
**Anchor:** `elif rr.status == "rerun_failed":`
**What:** The abstention reason cascade has four codes (`no_source_revision`, `html_missing`, `chunker_rerun_failed`, `chunk_id_not_reproduced`); tests exercise all except `chunker_rerun_failed` — no test forces `_rechunk_paper` to raise a `PER_PAPER_FAILURE_EXCEPTIONS` so `rr.status == "rerun_failed"`.
**Why it matters:** A malformed parsed HTML on the live run would hit this branch untested; a regression that mis-labels or crashes on the rerun-failed path (e.g. `rr.records` access when status is not "ok") would not be caught. The path itself reads correct (`hit` is gated on `rr.status == "ok"`), but the milestone's own AC3 is "un-anchorable block → counted + reason-coded," and one reason code is unverified.
**Proposed fix:** Add a test that patches `_rechunk_paper` (or feeds HTML that raises inside `_extract_chunks_from_container`) to return `status="rerun_failed"`, then asserts `chunker_rerun_failed=N` in the report and `source_span=null`, `truncated` still via fallback.
**Regression-guard:** `tests/test_notebook_chunks_backfill.py::test_rerun_failed_abstains`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** Axis 8 — test surface

**L1 — `_truncated_fallback` "airtight" claim overstates boundary monotonicity** (LOW)

**Where:** `tools/notebook_chunks_backfill.py:241`
**Anchor:** `return count_tokens(body_text) >= STMT_MAX_TOKENS`
**What:** The docstring asserts truncation "always leaves >= max_tokens tokens, so the `< budget` definitely-complete branch is airtight," but `_truncate_to_token_budget` slices at `offsets[max_tokens-1][1]` and re-tokenizing that boundary substring is not guaranteed to yield ≥ `max_tokens` (BPE merges at the cut can produce `max_tokens-1`), so the fallback could report a genuinely-truncated stmt as complete.
**Why it matters:** Only on the MISS path, only for a stmt whose stored (already-truncated) body sits exactly at the boundary, and only for the advisory `truncated` column (no serving behavior until m4+) — so impact is negligible, but the "airtight" wording invites a future reader to over-trust the invariant.
**Proposed fix:** Soften the docstring to "safe-direction in the common case; a boundary re-tokenization can rarely undercount by one token," or make the fallback `>= max_tokens - 1` if the conservative direction is desired. Docstring-only is sufficient.
**Regression-guard:** (optional) none required for a LOW docstring fix.
**Source critic:** milestone-arxmcp-critic
**Source axis:** Axis 8 — test surface

**L2 — Duplicated v2 default map has no drift guard** (LOW)

**Where:** `tools/notebook_chunks_backfill.py:143`
**Anchor:** `_V2_COLUMN_DEFAULTS: dict[str, str] = {`
**What:** `_V2_COLUMN_DEFAULTS` deliberately re-mirrors the five source-truth-m2 entries of `ingest.store._TEXTBOOK_MIGRATION_DEFAULTS` (to keep `ingest.store`/`ingest.embedder` out of the 0-re-embed import graph), but nothing asserts the two stay equal.
**Why it matters:** The duplication is correctly justified, but if a later milestone edits one column's cast SQL (e.g. a type change) in only one map, the backfill's self-contained migration would silently diverge from the store's. Low likelihood; cheap guard.
**Proposed fix:** A test that imports both and asserts `backfill._V2_COLUMN_DEFAULTS == {k: _TEXTBOOK_MIGRATION_DEFAULTS[k] for k in backfill._V2_COLUMN_DEFAULTS}` — importing `ingest.store` in a TEST is fine (the structural guarantee is about the driver's runtime import graph, not the test's).
**Regression-guard:** `tests/test_notebook_chunks_backfill.py::test_v2_defaults_match_store`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** Axis 7 — no-fork / internal reuse

## What was done well

- **Axis 1 (PRIMARY) fully satisfied.** `_compute_chunk_id` is untouched in the range; `ChunkRecord.printed_number` is documented as independent of both `theorem_label` and the chunk_id hash; and `source_span` is byte-stable via `json.dumps(sort_keys=True, separators=(",",":"))`, pinned by `test_source_span_json_shape_and_byte_stability` (asserts no `", "` and no `'": "'`).
- **0-re-embed is defended twice.** Structurally (the driver never imports `ingest.store`/`ingest.embedder`, asserted by an import-scan test and the `write_chunks`-absence check) AND empirically (`test_embeddings_bit_identical_pre_post` does a real write→backfill→read and asserts `np.array_equal` on both embedding columns), plus the idempotency test re-checks embedding equality after a second run.
- **Correct write mechanism.** The full-row read-modify-write via one `merge_insert("chunk_id").when_matched_update_all().when_not_matched_insert_all()` per notebook faithfully mirrors the shipped `ingest/embed_equations.py`; because every batch row already exists by `chunk_id`, `when_not_matched_insert_all` never fires and row-count/chunk_id-set are preserved (asserted).
- **Re-chunk fidelity.** `_rechunk_paper` mirrors `_chunk_paper_impl` container-for-container (`_extract_chunks_from_container(root)` + `_extract_section_chunks(soup)` + the section-less `_extract_body_fallback_chunks` guard + `_resolve_preamble_doc` + `tokenize_body` + `_compute_chunk_id` + keep-first dedup) and correctly OMITS the per-chunk JSON write, so a backfill re-chunk never mutates `var/arxmcp/corpus/chunks`. `CORPUS_PARSED_DIR` byte-matches the chunker's `PARSED_DIR`, so the re-chunk reads the exact parsed HTML the original ingest used.
- **Abstention is genuinely first-class (CLAUDE.md §4.9).** Every miss shape (`no_source_revision`, `html_missing`, `chunker_rerun_failed`, `chunk_id_not_reproduced`, `registry_missing`, `ambiguous_multi_row_registry`) is a counted, reason-coded, loudly-reported NULL — never a best-guess anchor — and `truncated` is the one guaranteed-non-null column with a documented safe-direction fallback.
- **Defensive registry join.** A `>1`-row-per-work registry deliberately abstains (`ambiguous_multi_row_registry`) rather than silently picking a revision; an absent `documents.db` returns an empty registry WITHOUT creating the store (no empty-DB write side effect). Both covered by tests.
- **Math fidelity preserved (Axis 2).** `_extract_printed_number` reuses the same `heading_candidates` gather + math-preserving `_element_text` as `_extract_theorem_name`, confines nested-span search to direct-child headings (F9 discipline), reads only rendered text (never the element id — spike-2 §3e), and never touches `body_text`; the paired proof inherits the number exactly like `theorem_name`/`theorem_label`.
- **Tier sequencing respected (Axis 4/6).** No MCP tool or `get_chunk` field is added (m5 owns surfacing), `EXPECTED_TOOL_SCHEMA_SHA256` is untouched, and m2 consumes only m1's shipped `documents_store` registry — no un-shipped tier.
- **Migration correctness (AC1).** The five columns ride the existing single-loop `add_columns` mechanism (one `cast(NULL as ...)` each, `truncated` as `cast(NULL as boolean)`), idempotent on re-run, nullable, with existing rows byte-identical — pinned by `TestSourceTruthM2SchemaMigration` (types, nullability, idempotency, `embedding_stmt`/`source_kind`/`license` preservation) and the store's unhandled-column guard updated to `13`.
- **Real bug fixed with a round-trip test (AC2).** `truncated` was previously computed at ingest but dropped at `_build_arrow_table`; it is now persisted, and `TestTruncatedPersistsRoundtrip` is the first store-level test to assert both `truncated` and `printed_number` survive the LanceDB write→read.

Severity counts: C0 H0 M3 L2

## Recommended rectification order

M2, M1, M3, L1, L2

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
