# Critique — embedder-truncation-m1

**Critic:** adversary
**Generated:** 2026-05-27T22:35:00Z
**Commit range:** `68c77c82..4787a41d`
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES because the C-fix and B-bump core changes are correct, byte-stable, and well-tested — but bundling textbook-ingest-m2's schema additions without its corresponding `_migrate_chunks_schema_if_needed` migration function introduces a documentation lie and a real schema-evolution gap that bites on stale-staging resume paths.
- Finding counts: 0 CRITICAL, 2 HIGH, 4 MEDIUM, 3 LOW (9 total).
- Highest-risk file:line: `ingest/schema.py:13-15` (docstring references `ingest.store._migrate_chunks_schema_if_needed` which does not exist; m2's load-bearing migration function was orphaned during bundling).
- Operator UX gap: the 3-8 hour `make re-embed-all` run prints only 2 lines per dataset (start + end); no inline per-paper progress reaches stdout despite `re_embed.py` writing rich `re-embed-progress.json` checkpoints.
- Driver hardening gap: `tools/re_embed_all.py::discover_targets` does not honor the project-wide m6 F3 symlink-rejection contract codified in `tools/_notebook_common.py:97`; latent (no symlinks in production tree today) but inconsistent.
- Cosmetic but operator-visible defect: failure-path print formats `summary.papers_failed` (a `list[str]`) inline in an f-string, producing `(['paper1', 'paper2'] paper failures)` instead of a count — and the test mocks `papers_failed=1` (int) so the defect is uncaught.
- Documentation drift: `ingest/chunker_types.py:167` still references the OLD `512-token (stmt) or 448-token (proof window) BGE-M3 budget` in the live docstring — should reference the constants after the very bump this milestone landed.
- Cache-discipline axes 1, 3, 4, 5, 7 all clean. `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` verified green at HEAD; `EXPECTED_COMPUTE_CHUNK_ID_SHA256` correctly untouched.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Schema docstring references a non-existent migration function

- **Severity:** HIGH
- **Source:** adversary
- **File:** `ingest/schema.py:13-15` (and the parallel comment at `ingest/schema.py:135-136`)
- **What:** The updated schema docstring claims `Existing-row migrations land via ingest.store._migrate_chunks_schema_if_needed which calls tbl.add_columns for any column present in the canonical schema but absent from the on-disk table.` A repo-wide grep for `_migrate_chunks_schema_if_needed` returns zero matches outside the two docstring locations. The function does not exist. `ingest/store.py::write_chunks` (line 638-641) opens existing tables and immediately calls `merge_insert` against the raw 21-column arrow table — no migration check, no `add_columns` call.
- **Why it matters:** The implementer's Deviation #2 imported textbook-ingest-m2's schema additions without importing m2's corresponding migration function (which m2's `research-brief-2.md:152-199` explicitly documented as REQUIRED before `merge_insert` would work on old-schema tables). Empirically confirmed: LanceDB rejects mismatched columns with `ValueError: Field 'X' not found in target schema` (reproduced live). The CRITICAL impact path requires a stale 14-col staging dir from before the m2 schema additions; today's production `var/arxmcp/notebooks/*/lancedb/` are 14-col but the typical re-embed creates a FRESH staging dir at the new 21-col schema, so the most common path works. The HIGH-severity impact is (a) the docstring lies, misleading any future maintainer who tries to debug a schema-evolution failure by grepping for the named function, and (b) any operator who runs `make re-embed-all`, encounters a transient failure, and re-runs against the partial 21-col staging is fine — but an operator whose staging predates m2 will hit a hard fail with no remediation path.
- **Proposed fix:** Either (i) implement `_migrate_chunks_schema_if_needed(tbl)` in `ingest/store.py` that diffs `tbl.schema` against `CHUNKS_SCHEMA_V1` and calls `tbl.add_columns({field.name: _null_sql_for(field.type)})` for each missing field, invoked from `write_chunks` immediately after `db.open_table` (the existing-table branch only). The implementation pattern is documented verbatim in `.claude/notes/milestones/textbook-ingest-m2/research-brief-2.md:152-199` and `:285`. Add a regression test that creates a 14-col table, writes a 21-col ChunkRecord through `write_chunks`, and asserts the table gains 7 nullable columns. OR (ii) if the migration is intentionally deferred to a separate milestone, **remove the lying docstring** at `ingest/schema.py:13-15` and `:135-136` and add a `RuntimeError` in `write_chunks` for schema-mismatch with a clear "run `tools/migrate_chunks_schema.py` first" message.
- **Regression guard:** `tests/test_store.py::TestSchemaEvolution::test_open_14_col_then_write_21_col_adds_missing_columns` (or the negative variant if option (ii) is chosen).

### F2 — Driver fails-to-display per-dataset failure count correctly

- **Severity:** HIGH
- **Source:** adversary
- **File:** `tools/re_embed_all.py:164-168`
- **What:** The per-dataset failure branch prints `f"({summary.papers_failed} paper failures)"`, but `ReEmbedSummary.papers_failed` is typed `list[str]` (`ingest/re_embed.py:103`) and gets appended-to with paper IDs (`ingest/re_embed.py:718, 750`). When 3 papers fail, stderr will read `(['2307.00100', '2307.00200', '2307.00300'] paper failures)` rather than `(3 paper failures)`. The test at `tests/test_re_embed_all.py:168` mocks `papers_failed=(1 if call_count["n"] == 2 else 0)` — an `int`, not a `list[str]` — so the test never exercises the real type and the bug is uncaught.
- **Why it matters:** This is the operator's only inline visibility into the dataset's failure mode after a multi-hour re-embed run. Garbled error output forces the operator to dig into `re-embed-progress.json` to count failures. Hard-to-spot in code review; certain to bite on first real failure.
- **Proposed fix:** Change to `f"({len(summary.papers_failed)} paper failure(s): {', '.join(summary.papers_failed[:5])}{'...' if len(summary.papers_failed) > 5 else ''})"`. Update the test to use a `SimpleNamespace(papers_failed=['2307.00100'])` (a real list) and assert the stderr contains `"1 paper failure"` not `"['2307"`.
- **Regression guard:** `tests/test_re_embed_all.py::TestRunExitCodes::test_per_dataset_failure_propagates_to_exit_code` — bump the mock to return a real `list[str]` and assert on the formatted stderr message.

### F3 — `discover_targets` ignores the project-wide m6 F3 symlink-rejection contract

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/re_embed_all.py:101-109` (the `for nb_dir in sorted(notebooks_base.iterdir())` loop)
- **What:** The driver iterates `notebooks_base.iterdir()` and treats every directory as a candidate notebook. The project has a load-bearing contract at `tools/_notebook_common.py:97` (closing m6 F3, HIGH) that refuses to operate on any notebook path that is a symlink. `discover_targets` does not invoke `notebook_dir()` (the canonical resolver that enforces the contract) and does not check `nb_dir.is_symlink()` itself.
- **Why it matters:** A symlinked notebook dir at `var/arxmcp/notebooks/evil -> /etc` would silently be treated as a re-embed target. Today there are no symlinks in the production tree (verified live), so the impact is latent — but a future operator/attacker who can write under `notebooks/` (e.g. via the m6 init script's slug bypass) gets path-confusion. The driver is the only notebook-iterating tool added in this milestone, and inconsistency with the rest of the codebase is the kind of drift that bites in 6 months.
- **Proposed fix:** Either delegate notebook discovery through `tools._notebook_common.notebook_dir(slug)` (which already enforces F3), OR add a `if nb_dir.is_symlink(): logger.warning("skipping symlinked notebook %s", nb_dir.name); continue` at the top of the loop. Add a regression test `test_discover_skips_symlinked_notebook` using `tmp_path` to create a symlink notebook dir and assert it is not in the returned targets.
- **Regression guard:** `tests/test_re_embed_all.py::TestDiscovery::test_skips_symlinked_notebook_dir`.

### F4 — Stale comment after token-budget bump

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `ingest/chunker_types.py:166-167`
- **What:** The docstring for `ChunkRecord.truncated` reads: `True when the chunker had to truncate body_text to fit the 512-token (stmt) or 448-token (proof window) BGE-M3 budget.` These constants were JUST bumped to 1920 / 1856 in this same commit at `ingest/chunker.py:88-91`. The new docstring text added by this milestone at the higher-level field documentation (`ingest/chunker_types.py:106-110`) correctly omits a specific number, but the in-line comment at line 166-167 still cites the OLD numbers.
- **Why it matters:** Reading the chunker_types module is the canonical way a new agent (or a researcher in a future milestone) learns the chunk-record contract. A stale `512`/`448` literal in a milestone whose entire purpose was to bump those numbers is a self-inflicted documentation defect. Also catchable by `tests/test_chunker_ids.py::TestSingleVersionDefinition`-style scanning if generalized.
- **Proposed fix:** Replace the in-line comment with `True when the chunker had to truncate body_text to fit the BGE-M3 token budget (currently STMT_MAX_TOKENS=1920 for stmt and PROOF_MAX_TOKENS=1856 for proof windows; see ingest/chunker.py).`
- **Regression guard:** Optional — extend `TestSingleVersionDefinition` style scanning to forbid the literals `"512-token"`, `"448-token"` in `ingest/` outside the chunker.py change-history comment. Cheap; ≤10 LOC.

### F5 — Multi-hour re-embed run has no inline per-paper progress visibility

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/re_embed_all.py:146-176`
- **What:** The driver prints `=== re-embedding {label} ===` at the start of each dataset and a one-line summary at the end. For a 3-8 hour single-dataset run, the operator sees only two log lines (`===` then `ok (...)`). `ingest.re_embed.run_re_embed` writes per-paper checkpoint to `re-embed-progress.json` (the implementation summary states the file exists), but does NOT log per-paper progress to stdout/stderr at INFO level visible to the driver. The driver does not wire `re_embed`'s per-paper progress to its own stdout.
- **Why it matters:** Synthesis estimated 3-8 hours wall-clock. The operator running `make re-embed-all` on a laptop has zero visibility into liveness without separately tailing `re-embed-progress.json`. A hung process and an in-progress-but-slow process are indistinguishable. The roadmap brief gates B-6 as "fails-loudly" — silence-for-hours is the inverse of loud.
- **Proposed fix:** Either (i) configure `logging.basicConfig` in `_cli` to also include the `re_embed` logger (currently only `re_embed_all` is named — check `ingest.re_embed`'s logger emits per-paper INFO), OR (ii) add a periodic stderr print every N papers based on reading `re-embed-progress.json` (more work than warranted). The minimal fix is propagating `ingest.re_embed`'s existing per-paper logger output by removing the named-logger filter in `_cli`.
- **Regression guard:** `tests/test_re_embed_all.py::TestRunExitCodes::test_per_paper_progress_lines_emitted` — patch `run_re_embed` to invoke a logger.info, assert caplog captures it through the driver's logging config.

### F6 — `2099.99999` synthetic paper_id is in a year that is far future and may collide if other tests adopt the same convention

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_chunker.py:898-900`
- **What:** The new `TestB2BudgetBumpTakesEffect` test uses `PAPER_ID = "2099.99999"` and the comment claims this is "conventionally used by the chunker tests as a synthetic id." Repo-wide grep confirms zero other usages today. However, the comment is forward-looking — it advertises a convention that does not exist (no other test uses this paper_id). The arXiv ID format allows YYMM up to 99 (no upper bound), but the month digit 99 is invalid in real arXiv submissions (`MM` is 01-12). The regex `^\d{4}\.\d{4,5}$` is permissive and accepts it.
- **Why it matters:** Tests that share a synthetic paper_id collide on `tmp_path / "parsed" / paper_id`. Currently isolated. The MEDIUM concern is: a future test author following the comment's stated convention will produce collisions — particularly painful if both tests patch `ingest.chunker.PARSED_DIR`.
- **Proposed fix:** Either (i) make the comment honest: `"2099.99999 is a synthetic id chosen to never match a real arXiv paper; this test is the first to use this convention"`, OR (ii) namespace the synthetic id to the test class: `"9999.99999"` (clearly synthetic) and document the prefix convention in `.claude/docs/chunker-fixtures.md`.
- **Regression guard:** N/A (cosmetic test-hygiene improvement).

### F7 — B-3 deferral to operator is consistent with the synthesis, but no follow-up artifact tracks it

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `.claude/notes/milestones/embedder-truncation-m1/implementation-summary.md:33-39`
- **What:** The implementer correctly deferred B-3 (nDCG@5 measurement) per the synthesis's reframe — the canonical `tests/eval/fixtures/queries.json` is empty, and the alternative `var/arxmcp/notebooks/bridgeland-stability/queries.json` (10 populated queries) can only be measured against re-embedded chunks. The implementation summary marks this as "operator follow-up." However, no tracking artifact exists: no issue, no `.claude/notes/` follow-up file, no `state.json` `deferred_findings` entry to ensure the operator actually records baseline + post-bump nDCG.
- **Why it matters:** A "deferred to operator" item with no tracking artifact is indistinguishable from a forgotten item. The synthesis's reframe is defensible; the absence of a tracking pointer is not. If the operator forgets, the regression-guard contract of B-3 (no nDCG degradation) is silently unmet.
- **Proposed fix:** Add an explicit entry in `.claude/notes/milestones/embedder-truncation-m1/state.json::deferred_findings` referencing B-3, OR create `.claude/notes/milestones/embedder-truncation-m1/operator-followup.md` with the procedure: `make re-embed-all`, run the eval against `bridgeland-stability/queries.json` pre-bump and post-bump, record both nDCG@5 values, assert ≤0.05 regression. Either is fine; the tracking artifact is the deliverable.
- **Regression guard:** N/A (process artifact, not a test).

### F8 — `noqa: BLE001` swallows all `run_re_embed` exceptions, masking type/import errors

- **Severity:** LOW
- **Source:** adversary
- **File:** `tools/re_embed_all.py:153`
- **What:** `except Exception as exc: # noqa: BLE001` followed by `logger.exception(...)` and `failures.append(t.label)`. The bare exception catch is documented (noqa comment) and the exception is logged, so the swallow is intentional. However, this masks programmer errors (e.g. `ImportError` on the late `from ingest.re_embed import run_re_embed`, or `TypeError` on the kwarg-call) as "re-embed failed" rather than "the driver is broken." A `BaseException`-leak path is correct, but a `TypeError`/`ImportError` should propagate.
- **Why it matters:** Operator-visible failure mode is wrong. An `ImportError` (typo in the late import) and a real OOM during embedding look identical from stderr. The cost of distinguishing is one `if isinstance(exc, (TypeError, ImportError, AttributeError)): raise`.
- **Proposed fix:** Narrow the catch to `except (RuntimeError, ValueError, OSError, MemoryError) as exc:` (the exceptions `run_re_embed` documents) and let everything else propagate — matching the per-paper-isolation pattern in `ingest/re_embed.py:714` and the project-wide "per-task isolation, programmer bugs propagate" pattern.
- **Regression guard:** N/A or `tests/test_re_embed_all.py::TestRunExitCodes::test_import_error_propagates`.

### F9 — `ingest/schema.py` docstring claims the schema is now textbook-aware but the schema-tests gate is the only test for the additions

- **Severity:** LOW
- **Source:** adversary
- **File:** `tests/test_store.py:144-176` (the only test exercising the 7 new columns)
- **What:** The schema-contract test bump (`14 → 21` columns) and the column-names list update are correct, but they're the ONLY two tests touching the m2 column additions. There is no test for `_ALLOWED_SOURCE_KINDS` enforcement (`ingest/store.py:158-161` declares the enum but no test in this commit exercises rejection of `"arxv"`). The implementer's Deviation #2 calls out that the textbook-m2 milestone is "a separate piece of work" — but if the m2 schema additions ship here without their corresponding behavioral guards (enum rejection, migration function), the m2 milestone's own surface area is partially-but-silently consumed by this commit.
- **Why it matters:** A future m2 implementer expecting to add `_ALLOWED_SOURCE_KINDS` enforcement to a clean baseline will find the enum already declared with no rejection guard, and a schema doc claiming migrations work that has no migration code. The bundling created an inconsistent partial state that's harder to reason about than either "all of m2" or "none of m2."
- **Proposed fix:** Either (i) revert `_ALLOWED_SOURCE_KINDS` from `ingest/store.py:155-161` (defer to m2 proper), OR (ii) add the enforcement check at the existing `_build_arrow_table` call site and a `tests/test_store.py::test_source_kind_enum_rejects_invalid` test. Option (i) is the smaller blast radius.
- **Regression guard:** `tests/test_store.py::test_source_kind_enum_rejects_invalid` (if (ii) chosen).

## What was done well

- The C-fix is exactly the one-line surgical change the brief specified: `add_special_tokens=False` added to the pre-pass tokenizer call at `ingest/embedder.py:419` (now `:421`) with a clear in-line comment explaining the +2 off-by-2 mechanic and the invariant that the downstream encode MUST keep the default.
- Both C-1 and C-2 regression tests are well-designed: C-1 (`test_pre_pass_excludes_special_tokens`) exercises the real `_patched_embed` path with a chunk at EXACTLY MAX_TOKENS, while C-2 (`test_pre_pass_call_passes_add_special_tokens_false`) does a source-stable grep with the trailing-comma form and asserts `count == 1` to prevent regression by accidental duplication.
- The B-2 test (`TestB2BudgetBumpTakesEffect::test_long_stmt_now_fits_intact`) is the strongest regression guard in the milestone: it builds a 600-word stmt that would have clipped to 512 tokens pre-bump, runs the full `chunk_paper` pipeline with `_resolve_preamble_doc` patched to None, computes the chunk_id with `_compute_chunk_id` directly, and asserts BOTH clauses of the reframed AC (chunker_version + chunk_id hash matches the full body, differs from a 512-clipped prefix).
- The CHUNKER_VERSION-literal scan test was thoughtfully generalized: `test_v1_0_literal_count_in_ingest_package` → `test_version_literals_only_in_canonical_assignments` now imports `CHUNKER_VERSION` and `TOKENIZER_VERSION` at runtime, so future bumps don't require touching the test. Independent of this milestone's outcome, that's a durable improvement.
- The 2307.00007 multi-window fixture relaxation was handled honestly: implementer flagged it as Deviation #3, added a docstring at the fixture-test pointing to the programmatic backstop, and verified the backstop (`TestProofWindowSplitting::test_proof_chunks_emitted_from_full_paper`) actually exercises the end-to-end `chunk_paper` call with a `word_count=1500` body (>1856 tokens, so windowing must engage).
- `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` verified untouched and green at HEAD — perfect cache-discipline outcome from the brief's X-1 / X-2 ACs.
- `EXPECTED_COMPUTE_CHUNK_ID_SHA256` pin at `tests/test_re_embed.py:773` correctly left alone — the hash function itself wasn't touched, only the version string and the budgets, so the pin must stay.
- B-7 (EMBED_BATCH_DEFAULT 32 → 8) was implemented unconditionally per the synthesis decision and documented in the constant's comment with the O(n²) attention rationale.
- `make re-embed-all` driver follows the existing Makefile pattern (`re-embed`, `eval`, `ingest`) with a help line, a Python-version preflight, and `ARGS=...` passthrough — operator-consistent with the rest of the toolchain.
- The implementation summary explicitly enumerates all THREE deviations from the brief upfront (B-3 deferral, schema-test bundling, multi-window-fixture relaxation) and invites adversary scrutiny on each. Disciplined disclosure is rare and valued.

## Recommended rectification order

1. **F1** (HIGH, schema doc lies) — either implement the missing `_migrate_chunks_schema_if_needed` function and add a regression test, OR remove the lying docstring and surface schema-mismatch as a hard error with a remediation path. Highest priority because it interacts with operator workflow and m2 hygiene.
2. **F2** (HIGH, garbled failure output) — 5-line fix to the f-string + update the test mock to use a real `list[str]`. Cheap, operator-visible.
3. **F3** (MEDIUM, symlink-rejection gap) — either delegate to `_notebook_common.notebook_dir()` or add a 3-line `is_symlink()` skip with a test. Cheap; closes a defense-in-depth gap consistent with the project's m6 F3 contract.
4. **F4** (MEDIUM, stale comment) — one-line docstring fix. Trivial.
5. **F5** (MEDIUM, no progress visibility) — minimal fix is removing the named-logger filter in `_cli`'s basicConfig so `ingest.re_embed`'s existing per-paper logger output reaches stderr. Skip if 4-6 weeks is acceptable; otherwise close before the operator runs the multi-hour job.
6. **F7** (MEDIUM, B-3 tracking artifact) — add a `deferred_findings` entry in state.json or create `operator-followup.md`. One file or one JSON edit. Closes the process gap.
7. **F9** (LOW, m2 enum without enforcement) — either revert `_ALLOWED_SOURCE_KINDS` (preferred) or add the enforcement + test. Belongs to m2 proper; defer if rectifier is rushed.
8. **F8** (LOW, broad exception swallow) — narrow the catch. Defer.
9. **F6** (LOW, synthetic id documentation) — comment tweak. Defer.

## Rectification status

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
