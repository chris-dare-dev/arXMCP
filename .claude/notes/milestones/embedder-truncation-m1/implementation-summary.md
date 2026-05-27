# Implementation Summary — embedder-truncation-m1

**Path:** inline (orchestrator main session)
**Base SHA:** `68c77c826d9d790167451488399f9005a0b62911`
**Generated:** 2026-05-27

---

## One-line

C+B bundled: fixed embedder pre-pass `add_special_tokens=False` off-by-2; bumped `BGE_M3_MAX_TOKENS` 512→2048 (with stmt/proof headroom + `EMBED_BATCH_DEFAULT` 32→8); bumped `CHUNKER_VERSION` v1.0→v1.1; added `make re-embed-all` driver; regenerated 10 fixtures.

## Commit range

`68c77c82..<HEAD>` (filled in after the feat commit lands).

## Acceptance criteria status

- **[C-1] ✅** Chunker non-truncated chunk → embedder pre-pass `truncated_count == 0`. Regression test:
  `tests/test_embedder.py::TestTokenBudget::test_pre_pass_excludes_special_tokens`.
- **[C-2] ✅** `ingest/embedder.py` pre-pass call site passes `add_special_tokens=False`. Grep-style guard:
  `tests/test_embedder.py::TestTokenBudget::test_pre_pass_call_passes_add_special_tokens_false`.
  Invariant: exactly ONE `add_special_tokens=False,` kwarg in the file.
- **[B-1] ✅** Canary 1902.08184: **0.5% truncation rate (1/221) on stmt/lemma/def/prop chunks** at the
  post-bump 2048-token budget (chunker hand-measured pre-commit). Pre-bump baseline was ~30%+ per the
  chunk-truncation-and-skew-2026-05-27 scan brief. AC threshold ≤5% met by ~10× margin. Total truncated
  chunks for this paper dropped from 44/725 = 6% to 2/548 = 0.4%.
- **[B-2] ✅** CHUNKER_VERSION bump rotates chunk_ids of previously-truncated chunks; emitted records carry
  `chunker_version="v1.1"`. Test:
  `tests/test_chunker.py::TestB2BudgetBumpTakesEffect::test_long_stmt_now_fits_intact`. Verifies BOTH
  AC clauses: (a) record carries v1.1, (b) chunk_id matches `_compute_chunk_id(paper_id, "", full_body)`
  and differs from the hash of a 512-token-clipped prefix.
- **[B-3] DEFERRED — eval fixture is empty.** Per the research synthesis's reframe and the
  retrieval-quality-report.md `_PENDING_` baseline: `tests/eval/fixtures/queries.json` has `"queries": []`,
  so the AC as written cannot be measured pre/post in this milestone. The synthesis reframed to use
  `var/arxmcp/notebooks/bridgeland-stability/queries.json` (10 populated queries) — but that requires
  the operator's actual re-embed run to populate post-bump chunks against which to query. Recording the
  baseline measurement is **operator follow-up** after `make re-embed-all` lands. The vacuous-pass
  posture in r1's brief is honored here.
- **[B-4] ✅** Driver subprocess test verifies the discovery + invocation contract:
  `tests/test_re_embed_all.py::TestRunExitCodes` and `TestDiscovery`. The actual `corpus-version.json`
  +1 advance happens when the operator runs `make re-embed-all` post-milestone (3–8 hour run per
  synthesis estimate). The driver itself, given a synthetic 2-dataset fixture, discovers both and
  invokes `run_re_embed()` per dataset; failures propagate to a non-zero exit.
- **[B-5] ✅** Docs updated:
  - `.claude/notes/04-parsing-and-chunking.md` § "Token budget (embedder-truncation-m1, 2026-05-27)"
    with the constant-change table and the math-fidelity rationale.
  - `.claude/docs/chunker-fixtures.md` § Schema example (`chunker_version: "v1.1"`), regen runbook
    canonical-example update, and a note on 2307.00007's multi-window fixture (the proof now fits in
    one window at the new budget; multi-window code coverage lives in
    `TestProofWindowSplitting::test_proof_chunks_emitted_from_full_paper` which programmatically
    generates a >1856-token proof).
- **[B-6] ✅** `make re-embed-all` target exists (Makefile +18 lines: `.PHONY`, help line, target body).
  Discovers `var/arxmcp/notebooks/*/lancedb/` via glob + shared corpus, calls `run_re_embed()` per
  dataset, exits non-zero on any per-dataset failure. Driver at `tools/re_embed_all.py`. Tests at
  `tests/test_re_embed_all.py` cover discovery, dry-run, exit codes, and per-dataset failure
  propagation.
- **[B-7] ✅** `EMBED_BATCH_DEFAULT` lowered 32 → 8 in `ingest/embedder.py:133`. Documented in the
  constant's comment + in the commit body. CPU O(n²) attention at 2048-token inputs would otherwise
  OOM-risk a 32-batch.
- **[X-1] ✅** `EXPECTED_TOOL_SCHEMA_SHA256` UNCHANGED (no `server/tools.py::ALL_TOOLS` edit).
  Verified by `tests/test_server_tool_schema.py` green.
- **[X-2] ✅** `EXPECTED_BP1_SHA256` UNCHANGED (no `server/prompts.py` edit). Verified by
  `tests/test_prompts.py` green.
- **[X-3] ✅** `ruff check .` clean. `make test`: **2777 passed, 26 skipped, 1 xfailed, 6 pre-existing
  failures** (all 6 verified pre-existing at base SHA 68c77c82 via `git stash --include-untracked`):
  - `tests/test_drift_check.py::TestIntegrationRealLatexmlc::*` (2 — `latexmlc` binary issues)
  - `tests/test_tools_all.py::TestToolsSmoke::test_cite_neighbors_wired` (1 — Kùzu graph init)
  - `tests/eval/test_parser_fidelity.py::TestFixtureStructure::test_class_dir_exists[*]` (3 — fixture
    dirs absent)

## New / changed tests

- **New:** `tests/test_re_embed_all.py` — 11 tests covering `discover_targets()` and `run()`.
- **New:** `tests/test_embedder.py::TestTokenBudget::test_pre_pass_excludes_special_tokens` — C-1 regression.
- **New:** `tests/test_embedder.py::TestTokenBudget::test_pre_pass_call_passes_add_special_tokens_false` — C-2 source-stable guard.
- **New:** `tests/test_chunker.py::TestB2BudgetBumpTakesEffect::test_long_stmt_now_fits_intact` — B-2 budget-bump end-to-end (chunker → full hash).
- **Updated:** `tests/test_chunker.py::TestProofWindowSplitting::test_long_proof_produces_multiple_windows` — word_count 300 → 1500 (new PROOF_MAX_TOKENS=1856 needed).
- **Updated:** `tests/test_chunker.py::TestProofWindowSplitting::test_window_token_budget_respected` — same word_count bump.
- **Updated:** `tests/test_chunker.py::TestProofWindowSplitting::test_window_overlap_present` — same word_count bump.
- **Updated:** `tests/test_chunker.py::TestProofWindowSplitting::test_proof_chunks_emitted_from_full_paper` — word_count 400 → 1500.
- **Updated:** `tests/test_chunker.py::TestFixtureSuite::test_multi_window_proof_fixture_exists` — relaxed from "≥2 proof chunks" to "≥1 proof chunk" with a docstring pointing to the programmatic coverage in `TestProofWindowSplitting`.
- **Updated:** `tests/test_chunker.py` — 4 `"v1.0"` → `"v1.1"` literal assertions.
- **Updated:** `tests/test_chunker_ids.py::TestChunkerVersionConstant::test_constant_value` — `"v1.0"` → `"v1.1"`.
- **Updated:** `tests/test_chunker_ids.py::TestSingleVersionDefinition::test_v1_0_literal_count_in_ingest_package` →
  renamed `test_version_literals_only_in_canonical_assignments` and generalized to scan for both CHUNKER_VERSION and TOKENIZER_VERSION literals at runtime so future bumps don't require touching this test.
- **Updated:** `tests/test_embedder.py::TestModuleContract::test_max_tokens_is_512` → renamed `test_max_tokens_is_2048` and updated.
- **Updated:** `tests/test_embedder.py::TestTokenBudget::test_overlong_input_warn_and_truncate` — 1000 → 3000 source words to overflow the new 2048-token cap.
- **Updated:** `tests/test_embedder.py` — `_fake_model_factory` tokenizer now respects `add_special_tokens=False` in the F3 pre-pass return path.
- **Updated:** `tests/test_store.py::TestSchemaContract::test_column_count_matches_brief` — 14 → 21 (incorporates the textbook-ingest-m2 schema additions present in the working tree, see "Deviations" below).
- **Updated:** `tests/test_store.py::TestSchemaContract::test_column_names_in_brief_order` — appended the 7 textbook columns.
- **Regenerated:** all 10 `tests/fixtures/chunker/<paper_id>.expected.json` files per the
  chunker-fixtures.md runbook. Most chunk_ids stable (synthetic fixtures don't hit 1920 tokens);
  2307.00007's proof_chunks dropped 3 → 1 because the long proof now fits in one window at the new
  budget (documented in chunker-fixtures.md as the canonical multi-window-fixture caveat).
- **Updated:** `tests/eval/fixtures/queries.json` — `chunker_version` `"v1.0"` → `"v1.1"`.

## Code edits

- `ingest/chunker.py` — `BGE_M3_MAX_TOKENS=2048`, `STMT_MAX_TOKENS=1920` (literal int, not derived; 128-token preamble headroom), `PROOF_MAX_TOKENS=1856` (literal int; 192-token headroom).
- `ingest/embedder.py` — `MAX_TOKENS=2048`, `EMBED_BATCH_DEFAULT=8`, added `add_special_tokens=False` kwarg to the F3 pre-pass tokenizer call (the only line of C).
- `ingest/chunker_types.py` — `CHUNKER_VERSION = "v1.1"`.

## Driver + Makefile

- `tools/re_embed_all.py` (NEW, ~150 LOC) — discovery + per-dataset invocation loop. Late-imports `ingest.re_embed.run_re_embed` so `--dry-run` and the discovery tests don't pay the BGE-M3 model-load cost.
- `Makefile` — added `re-embed-all` target with help text; appended to `.PHONY`.

## Docs

- `.claude/notes/04-parsing-and-chunking.md` — new "Token budget" subsection with constant-change table and post-bump canary number; updated `chunker_version` in JSON example to `"v1.1"`.
- `.claude/docs/chunker-fixtures.md` — schema example bumped to `"v1.1"`; multi-window scenario caveat added; regen runbook canonical example updated.

## External writes the orchestrator must authorize

**None.** This milestone is purely local:

- No `git push`
- No `gh issue create` / `gh pr create`
- No external API calls
- No infra mutations

The operator-driven re-embed run (`make re-embed-all`, est. 3–8 hours of CPU) is a local-CPU follow-up, not an external write.

## Deviations from the brief

1. **B-3 is deferred to operator post-milestone follow-up.** The brief's reframe pointed B-3 at
   `var/arxmcp/notebooks/bridgeland-stability/queries.json` (10 populated queries), but those queries can
   only be measured against re-embedded chunks — i.e., after `make re-embed-all` runs. The pipeline does
   not run the re-embed (3–8 hour wall-clock; synthesis decision). The operator records baseline and
   post-bump nDCG@5 post-milestone.

2. **The schema-contract test update incorporates textbook-ingest-m2 schema additions.** During this
   session, `ingest/schema.py`, `ingest/chunker_types.py`, and `ingest/store.py` received
   textbook-ingest-m2 changes (7 new columns: `source_kind`, `license`, `chapter`, `page_start`,
   `page_end`, `textbook_slug`, `parser_used`) per a system reminder marking them as intentional. Those
   edits broke `tests/test_store.py::TestSchemaContract::test_column_count_matches_brief` (which pinned
   14 columns). Per the system reminder's "take it into account as you proceed" directive, I updated
   the test contract to 21 columns rather than reverting the schema additions. This pulls
   textbook-ingest-m2's schema test into my commit; the textbook m2 milestone itself remains a separate
   piece of work, but its schema-test fallout is closed here. Surface this in adversary critique if
   the bundling feels wrong.

3. **2307.00007 fixture no longer exercises multi-window proof.** At the old PROOF_MAX_TOKENS=448, the
   fixture's proof body split into 3 windows; at the new 1856, it fits in one. The chunker's multi-
   window splitting code is still exercised by `TestProofWindowSplitting` (programmatic), so coverage
   is intact. Authoring a new long-body fixture for the new regime is a follow-up — not bundled here.

4. **`_compute_chunk_id` lives in `ingest/chunker`, not `ingest/chunker_types`.** R2's brief
   referenced `chunker_types` for the hash function; my B-2 test corrected the import. Minor.

## Implementation order

1. Constants in `chunker.py`, `embedder.py`, `chunker_types.py`. (C + B core)
2. Literal `"v1.0"` → `"v1.1"` updates in 4 test files.
3. Generalized `TestSingleVersionDefinition` scan to use runtime-imported constants.
4. Regenerated 10 chunker fixtures via the runbook procedure.
5. Updated `tests/eval/fixtures/queries.json`.
6. Added 3 new tests (C-1, C-2, B-2).
7. Wrote `tools/re_embed_all.py` driver + Makefile target.
8. Added `tests/test_re_embed_all.py` (11 tests).
9. Updated 2 docs (04-parsing-and-chunking.md, chunker-fixtures.md).
10. Ran ruff + pytest; fixed ruff E501 + F401; fixed test failures from updated constants.
11. Updated schema-contract test for the parallel textbook-m2 columns.
12. Final `make test`: green except 6 pre-existing failures.

## Risk surface for Phase 3 critique

- **Bundling concern:** schema-test update touches textbook-ingest-m2 surface (Deviation #2 above). Adversary may flag.
- **Multi-window fixture regression:** 2307.00007 no longer multi-windows; coverage moved to programmatic test (Deviation #3 above). Adversary may want a new fixture.
- **EMBED_BATCH_DEFAULT change:** dropping 32→8 will slow embedding on small chunks; documented but not measured.
- **B-3 deferral:** if the adversary considers nDCG@5 measurement load-bearing, the deferred-to-operator framing may be flagged.
- **Makefile change:** triggers `milestone-infra-safety` critic (new target, no other infra touched).
