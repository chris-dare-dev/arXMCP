# Critique — source-truth-m2 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** 880fcfd..ac0ff62
**Diff stats:** 8 files, 1825 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES. No correctness defect survived scrutiny: the load-bearing AC2
embedding-preservation gate is sound (real `np.array_equal` test + independent
repro on lancedb 0.30.2), 0-re-embed is genuinely structural, `source_span` is
byte-stable, `truncated` is safe-direction, and the registry join abstains on
every ambiguous cardinality. The two actionable items are the mandated
large-diff review flag (H1, owner-approved `allow_large_diff`) and one
regression-guard gap (M1): every backfill test starts at the already-migrated
26-column schema, so the driver's own `add_columns`→hydrate composition — the
exact live go-live path — has no committed test (I verified it works, but a
future lancedb bump could silently regress AC2 with the in-memory report still
falsely reporting `resolved`).

## Executive summary

- [HIGH] Mandated review-quality flag: the diff is 1825 LOC (> 400). No code
  defect; `allow_large_diff` is owner-approved and 240 passing tests + a
  15,106-row scratch smoke substantially mitigate. Logged per the pipeline gate.
- [MEDIUM] No backfill test exercises the driver's `_ensure_v2_columns`
  migration path with `columns_added > 0`; the migrate-then-hydrate composition
  (the live 21→26-column go-live path) is only covered by the uncommitted
  scratch smoke. Verified correct on lancedb 0.30.2, but unguarded.
- [LOW] `_PRINTED_NUMBER_RE` captures a trailing word-letter fused to a digit
  ("Corollary3" → "y3"); not reachable in real LaTeXML (always a space in the
  tag), but cheap defensive hardening.
- [LOW] Idempotency skip-gate keys on `source_revision_id`, so the "re-run
  writes nothing" claim holds only for a fully-registry-resolved notebook;
  registry-missing papers re-chunk+re-write every run (embeddings preserved).
- [LOW] Commit 2572f2f subject is 51 chars after the `feat(ingest): ` prefix,
  1 over the §4.3 ≤50 convention.
- No CRITICAL. Embedding preservation, structural 0-re-embed, byte-stable
  `source_span`, safe-direction `truncated`, and the registry abstention
  cardinalities are all correct and tested.

## Findings

**H1 — Diff exceeds the 400-LOC review-quality threshold** (HIGH)

**Where:** no specific file
**Anchor:** `1825 LOC across 8 files`
**What:** The milestone diff is 1825 LOC (8 files), above the 400-LOC line the critique format flags as HIGH.
**Why it matters:** Large diffs lower per-line review density and raise the chance a defect ships unseen.
**Proposed fix:** No code change. Acknowledge the mandated flag: `allow_large_diff` is owner-approved for this milestone, and the volume is dominated by two new test files (531 + 159 LOC) and a self-contained 736-LOC driver with no cross-module coupling. Mitigation is real — 240 tests pass and the 15,106-row scratch smoke showed 0 embedding mismatches on live data. Record and proceed.
**Regression-guard:** N/A (process flag; the mitigating 240 tests + smoke are already present).
**Source critic:** milestone-adversary-critic
**Source axis:** Review quality / diff size

**M1 — Driver's own add_columns→hydrate composition has no regression guard** (MEDIUM)

**Where:** `tools/notebook_chunks_backfill.py:532`
**Anchor:** `report.columns_added = _ensure_v2_columns`
**What:** Every backfill test builds its table via `write_chunks` / `CHUNKS_SCHEMA_V1` (already 26 columns), so `_ensure_v2_columns` always returns `[]` and the driver's migrate-then-hydrate path (add 5 columns to a live pre-v2 table, then hydrate them in the same run) is never exercised by an automated test.
**Why it matters:** That composition IS the go-live scenario on the live 21-column notebook tables; if a future lancedb version or refactor left `table.schema`/`table.to_arrow()` stale after `add_columns`, `from_pylist(schema=table.schema)` would drop the 5 patched keys and `merge_insert` would silently no-op them — and because `_patch_notebook` increments `source_span_resolved`/`rev_resolved` from in-memory decisions (not a post-write read-back), the report would still print `resolved=N` while the columns persisted NULL, a silent AC2 violation with no in-driver detection.
**Proposed fix:** Add one backfill test that creates a genuine pre-v2 table (`pa.schema(list(CHUNKS_SCHEMA_V1)[:-5])`, as `TestSourceTruthM2SchemaMigration._make_pre_v2_table` already does), writes rows + synthetic embeddings, runs `backfill.run(...)`, then asserts (a) `columns_added == 5` via the report, (b) the five columns are hydrated non-null on a HIT paper by reading the table back, and (c) `embedding_stmt`/`embedding_proof` are `np.array_equal` pre/post. (I confirmed the mechanism itself is correct on lancedb 0.30.2 by isolated repro — this is a guard against future regression, not a live bug.)
**Regression-guard:** `tests/test_notebook_chunks_backfill.py::TestMigrateThenHydrate::test_pre_v2_table_migrated_and_hydrated_in_one_run`
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage (AC1∩AC2 composition)

**L1 — printed-number regex fuses a trailing word-letter to a digit** (LOW)

**Where:** `ingest/chunker.py:123`
**Anchor:** `_PRINTED_NUMBER_RE = re.compile(r"([A-Za`
**What:** On heading text with no space between the environment word and the number, the optional leading `[A-Za-z]?` captures the word's last letter — "Corollary3" → "y3", "Lemma5" → "a5".
**Why it matters:** A malformed `printed_number` would be persisted verbatim; harmless today because LaTeXML always renders a space in the `ltx_tag_theorem` tag ("Corollary 3"), so the input is not reachable in the corpus — but the extractor is new and the guard is one anchor.
**Proposed fix:** Require a word boundary or leading separator before the optional appendix letter, e.g. anchor the letter to a `(?:^|[\s(])` prefix inside the tag-span scan, or post-filter a captured group whose leading letter is immediately preceded by another letter. Add a `test_no_space_before_number_declines` case ("Corollary3" → None).
**Regression-guard:** `tests/test_chunker.py::TestPrintedNumberExtraction::test_no_space_before_number_declines`
**Source critic:** milestone-adversary-critic
**Source axis:** printed_number extraction

**L3 — Idempotency skip-gate keyed on source_revision_id overstates the no-op claim** (LOW)

**Where:** `tools/notebook_chunks_backfill.py:549`
**Anchor:** `if all(row.get("source_revision_id") is`
**What:** The docstring says "a re-run over a fully-hydrated notebook re-chunks nothing and writes nothing," but the skip-gate keys on `source_revision_id`; a paper that abstained as `registry_missing` (revision null) is re-chunked and re-written on every subsequent run, and a paper that resolved its revision but missed its chunk-id (`source_span` null) is treated as done and never re-attempts `source_span`.
**Why it matters:** Near-zero impact on the live notebooks (the source-truth-m1 smoke reported `source_revision_id` 100%, so registry_missing ≈ 0), and re-writing preserves embeddings, so it is not a correctness bug — but the "writes nothing" guarantee is weaker than documented, and the re-attempt semantics after a chunker upgrade are undefined (no `--force`).
**Proposed fix:** Tighten the docstring to "a re-run over a notebook whose papers ALL resolved a source_revision_id re-chunks nothing"; optionally add a `--force` flag (drop-and-re-add the 5 columns, or bypass the skip-gate) for post-chunker-upgrade re-hydration, tracked as a fast-follow.
**Regression-guard:** Optional (LOW) — a `test_registry_missing_paper_rewrites_on_rerun` asserting the abstained paper is re-processed and embeddings stay `np.array_equal`.
**Source critic:** milestone-adversary-critic
**Source axis:** Idempotency

**L2 — Commit 2572f2f subject is 1 char over the ≤50 convention** (LOW)

**Where:** no specific file
**Anchor:** `chunks schema v2 columns + printed-number extractor`
**What:** The `feat(ingest)` subject body "chunks schema v2 columns + printed-number extractor" is 51 characters, 1 over the CLAUDE.md §4.3 "≤50 after the type prefix" rule.
**Why it matters:** Purely cosmetic; the commit is already landed and signed, so this is a note for future subjects, not a rebase trigger.
**Proposed fix:** No action on the landed commit. For future subjects, trim (e.g. "chunks schema v2 cols + printed-number extractor" = 48).
**Regression-guard:** N/A (convention nit).
**Source critic:** milestone-adversary-critic
**Source axis:** Commit hygiene

## What was done well

- **Embedding preservation is proven, not asserted.** AC2's load-bearing gate has a real `test_embeddings_bit_identical_pre_post` using `np.array_equal`, and I independently reproduced the driver's exact `to_pylist` → `from_pylist(schema=table.schema)` → `merge_insert` path on lancedb 0.30.2: float32 `0.1` round-trips to its identical float32. The 15,106-row scratch smoke showed 0 mismatches on real data.
- **0-re-embed is genuinely STRUCTURAL.** The driver imports neither `ingest.store` nor `ingest.embedder`, and even literalizes `CHUNKS_TABLE_NAME` to avoid transitively pulling the embedder through `ingest.schema`'s module-load `EMBEDDING_DIM` import — with `test_driver_imports_no_embedder_or_store` enforcing it. No forward pass can run.
- **`source_span` is byte-stable and path-independent.** `json.dumps(sort_keys=True, separators=(",",":"))` and a `txt` key that is a pure function of the STORED `body_text` (NFC + whitespace-collapse), so a re-run cannot rot the column and the resolving key never depends on the extraction path.
- **The registry join abstains on every cardinality.** 0 → `registry_missing`, >1 → `ambiguous_multi_row_registry` (never a silent first-pick), 1 → use. `license_ref` is safe by construction: `DocumentRecord.license_status` is `NOT NULL DEFAULT 'unknown'` and coerced `row[10] or "unknown"`, so the "NULL exactly when `source_revision_id` NULL" invariant holds.
- **`truncated` has a provably safe-direction fallback.** Proofs are windowed (never `truncated=True` in the chunker), so unconditional `False` is correct-by-construction; the stmt branch (`>= STMT_MAX_TOKENS`) can only over-flag a complete max-length statement, never under-report real truncation.
- **The re-chunk mirror is faithful and read-only.** It replicates `_chunk_paper_impl`'s pass order, `_compute_chunk_id(paper_id, preamble_text, body_text)` inputs, and keep-first dedup, while deliberately omitting the per-chunk JSON write — empirically reproducing 14,947/15,106 chunk_ids.
- **Abstention is first-class (§4.9).** Every null is counted, reason-coded, and listed (capped at 500) in a machine-parseable per-notebook report, with the spike-2 F2 sanity flag surfacing likely total markup-path misses on old-style papers.
- **AC1 is thoroughly tested.** 5-column migration, idempotency, nullability, type-match, and existing-embedding byte-identity all have store-level tests, and the previously-silently-dropped `truncated` column now has a write→read round-trip guard.
- **Clean process hygiene.** Both commits are GPG-signed with the correct `Co-Authored-By: Claude Opus 4.8` trailer; no one-writer violation (no `roadmap.yaml`/`state.json` edits in range); no production `assert`-for-invariants; all 240 relevant tests pass locally.

Severity counts: C0 H1 M1 L3

## Recommended rectification order

H1, M1, L1, L3, L2
