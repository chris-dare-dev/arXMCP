# Critique — embedder-truncation-m1 (merged)

**Critics:** adversary, infra-safety
**Generated:** 2026-05-27 (post-Phase 3 merge)
**Commit range:** `68c77c826d9d790167451488399f9005a0b62911..4787a41d4da412f3be6ae2de485143c1841d9300`
**Merged verdict:** SHIP-WITH-FIXES

## Executive summary (orchestrator voice)

- SHIP-WITH-FIXES. The C+B core changes (off-by-2 fix + token-budget bump) are correct, well-tested, and byte-stable against cache invariants (X-1 / X-2 / chunk-id-hash pin all green at HEAD). Verdict bumps to SHIP-WITH-FIXES on two HIGH findings: a documentation lie about a non-existent migration function in the bundled-from-textbook-m2 schema additions (F1), and a `list[str]`-formatted-as-int operator-visible defect in the new `re_embed_all` driver's failure path (F2).
- Finding counts: **0 CRITICAL, 2 HIGH, 5 MEDIUM, 4 LOW (11 total)**.
- Adversary delivered 9 findings (1 HIGH, 4 MEDIUM, 1 HIGH = F1+F2, then F3-F9). Infra-safety delivered 2 (1 MEDIUM, 1 LOW). Cross-critic agreement: none — clean orthogonal coverage of (code surface) vs (Makefile surface).
- Highest-risk single defect: `ingest/schema.py:13-15` docstring references `ingest.store._migrate_chunks_schema_if_needed` which does NOT exist in the repo. Inherited via the textbook-ingest-m2 schema bundling (Deviation #2 in the implementation summary). Either implement the named function with a regression test, or remove the lying docstring and gate `write_chunks` with a hard error.
- Operator-experience gaps cluster in `tools/re_embed_all.py`: F2 (garbled failure output), F3 (symlink-rejection contract gap), F5 (no per-paper progress visibility during 3-8 hour run), F8 (overbroad exception swallow). All cheap to fix together.
- Bundling concerns the implementer self-disclosed (Deviation #2 — schema-test absorption of textbook-m2 changes) drew the adversary's HIGH finding (F1) and a LOW (F9, enum-without-enforcement). The disclosure was valuable; the bundling itself partially leaked m2 surface.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Cross-critic agreement

No finding was raised by both critics. Coverage was orthogonal:
- adversary handled code surface (chunker, embedder, schema, driver, docs)
- infra-safety handled Makefile surface

This is the expected outcome for a milestone whose only infra-scoped file is one Makefile target addition.

## Cross-critic agreement

_None — no file:line region was flagged by ≥ 2 critics._

<!-- end:cross-critic-agreement -->

## Findings (preserved IDs, by severity)

### F1 — Schema docstring references a non-existent migration function
- **Severity:** HIGH
- **Source:** adversary
- **File:** `ingest/schema.py:13-15` (and `:135-136`)
- **What:** Docstring claims `Existing-row migrations land via ingest.store._migrate_chunks_schema_if_needed`. Repo grep returns zero matches outside the two docstring locations. `ingest.store.write_chunks` opens existing tables and calls `merge_insert` directly with no migration step. The function does not exist.
- **Why it matters:** Bundling Deviation #2 imported textbook-m2's schema additions without its corresponding migration function. Operator hitting an old-schema staging dir gets a hard fail with no remediation. Misleading docstring would mislead any maintainer grepping for the named function.
- **Proposed fix:** (i) implement `_migrate_chunks_schema_if_needed(tbl)` per the pattern in `.claude/notes/milestones/textbook-ingest-m2/research-brief-2.md:152-199`, OR (ii) remove the lying docstring AND surface schema-mismatch as a `RuntimeError` in `write_chunks` with a clear remediation message.
- **Regression guard:** `tests/test_store.py::TestSchemaEvolution::test_open_14_col_then_write_21_col_adds_missing_columns` (option i) or the negative variant (option ii).

### F2 — Driver fails-to-display per-dataset failure count correctly
- **Severity:** HIGH
- **Source:** adversary
- **File:** `tools/re_embed_all.py:164-168`
- **What:** Prints `f"({summary.papers_failed} paper failures)"`, but `papers_failed` is `list[str]` per `ingest/re_embed.py:103`. Real failures will render as `(['2307.00100', '...'] paper failures)`. Test mock at `tests/test_re_embed_all.py:168` uses an int, so the bug is uncaught.
- **Why it matters:** Operator's only inline failure visibility after a multi-hour run is garbled. Hard to spot in review; certain to bite on first real failure.
- **Proposed fix:** Use `len(summary.papers_failed)` and surface up to 5 IDs in the message. Update the test mock to a real `list[str]` and assert the formatted stderr.
- **Regression guard:** Update `tests/test_re_embed_all.py::TestRunExitCodes::test_per_dataset_failure_propagates_to_exit_code`.

### F3 — `discover_targets` ignores the project-wide m6 F3 symlink-rejection contract
- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/re_embed_all.py:101-109`
- **What:** `discover_targets` iterates `notebooks_base.iterdir()` and does not refuse symlinked notebook dirs (per the contract codified at `tools/_notebook_common.py:97`).
- **Why it matters:** Latent today (no symlinks in production tree). Inconsistent with the rest of the codebase; a future operator's symlinked notebook would silently become a re-embed target.
- **Proposed fix:** Add `if nb_dir.is_symlink(): logger.warning(...); continue` OR delegate to `notebook_dir()`. Regression test creating a symlink in `tmp_path`.
- **Regression guard:** `tests/test_re_embed_all.py::TestDiscovery::test_skips_symlinked_notebook_dir`.

### F4 — Stale comment after token-budget bump
- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `ingest/chunker_types.py:166-167` (inline comment in the `truncated` field doc)
- **What:** Says `512-token (stmt) or 448-token (proof window)` — the OLD values, in the very commit that bumps them. The higher-level docstring at `:106-110` was correctly updated; the in-line comment was missed.
- **Proposed fix:** Replace with `STMT_MAX_TOKENS / PROOF_MAX_TOKENS; see ingest/chunker.py`.

### F5 — Multi-hour re-embed run has no inline per-paper progress
- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/re_embed_all.py:146-176`
- **What:** Driver prints two lines per dataset (start + summary). `ingest.re_embed` writes per-paper checkpoints to `re-embed-progress.json` but driver does not surface them. 3-8 hour wall-clock means the operator sees silence.
- **Proposed fix:** Configure `logging.basicConfig` to also include the `ingest.re_embed` logger so its per-paper INFO output reaches stderr.
- **Regression guard:** `tests/test_re_embed_all.py::TestRunExitCodes::test_per_paper_progress_lines_emitted`.

### F6 — `2099.99999` synthetic paper_id documentation
- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_chunker.py:898-900`
- **What:** Comment claims "conventionally used by the chunker tests as a synthetic id" but repo grep shows zero prior usage. Self-fulfilling-prophecy doc is misleading.
- **Proposed fix:** Make the comment honest: "this test is the first to use this convention; future synthetic-id tests should use distinct ids to avoid `tmp_path` collisions on `parsed/<id>`."

### F7 — B-3 deferral lacks a tracking artifact
- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `.claude/notes/milestones/embedder-truncation-m1/implementation-summary.md:33-39`
- **What:** B-3 was correctly deferred to operator post-`make re-embed-all`, but no `state.json::deferred_findings` entry, no follow-up file, no issue. "Deferred to operator" with no tracker is indistinguishable from forgotten.
- **Proposed fix:** Either add `state.json::deferred_findings` entry OR create `.claude/notes/milestones/embedder-truncation-m1/operator-followup.md` with the eval procedure.

### F8 — `noqa: BLE001` swallows all `run_re_embed` exceptions
- **Severity:** LOW
- **Source:** adversary
- **File:** `tools/re_embed_all.py:153`
- **What:** Bare `except Exception` masks `ImportError`/`TypeError`/`AttributeError` (programmer bugs) as "re-embed failed."
- **Proposed fix:** Narrow to `except (RuntimeError, ValueError, OSError, MemoryError) as exc:` matching the project's per-paper-isolation pattern.
- **Deferred:** LOW severity; defer per Phase 4 protocol.

### F9 — `_ALLOWED_SOURCE_KINDS` enum without enforcement test
- **Severity:** LOW
- **Source:** adversary
- **File:** `ingest/store.py:155-161` (bundled from textbook-ingest-m2)
- **What:** The enum is declared but no test exercises rejection of `"arxv"` etc. Bundling leaked m2's enum without m2's behavioral guard.
- **Proposed fix:** Either revert from this milestone's scope, OR add `tests/test_store.py::test_source_kind_enum_rejects_invalid`.
- **Deferred:** LOW; tracked for textbook-ingest-m2 proper.

### IS1 — `re-embed-all` missing ARGS spaces-footgun warning
- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** `Makefile:149` (the `re-embed-all` target body)
- **What:** Other path-bearing-CLI targets (`ingest`, `re-embed`, `watchdog`, `cutover`) carry a `@# NOTE on ARGS: paths inside ARGS must not contain spaces` comment. `re-embed-all` does not, though it forwards `$(ARGS)`. Latent today (`--dry-run` is the only accepted arg with no path payload).
- **Proposed fix:** Add the standard 3-line ARGS warning block.

### IS2 — help line for `re-embed-all` misaligned
- **Severity:** LOW
- **Source:** infra-safety
- **File:** `Makefile:17`
- **What:** Description column off by one character vs sibling short-named targets.
- **Proposed fix:** Add one extra space before the description.
- **Deferred:** LOW; cosmetic.

## Recommended rectification order

1. **F1** (HIGH, schema doc lies + migration function missing) — implement OR remove + gate. Highest priority.
2. **F2** (HIGH, garbled driver failure output) — 5-line fix + test mock update.
3. **F3** (MEDIUM, symlink-rejection gap) — 3-line driver change + test.
4. **IS1** (MEDIUM, ARGS warning) — 3-line Makefile comment addition.
5. **F4** (MEDIUM, stale comment) — one-line docstring fix.
6. **F5** (MEDIUM, no progress visibility) — minimal logging-config change.
7. **F7** (MEDIUM, B-3 tracking artifact) — one state.json edit or one followup file.
8. **F6** (MEDIUM, synthetic id doc) — one-line comment fix.
9. **F8, F9, IS2** (LOW) — defer per protocol.

## Rectification status

Re-verify gate: 2/2 HIGH findings (F1, F2) re-verified at the cited file:line ± 30 lines; neither invalidated.

- F1 — fixed in `ingest/schema.py` (lying docstring removed; replaced with explicit "migration NOT implemented here; textbook-ingest-m2 proper" note); no regression test added (the fix is documentation-only, not behavioral — no `_migrate_chunks_schema_if_needed` was ever called).
- F2 — fixed in `tools/re_embed_all.py:162-175` (failure-line format now uses `len(papers_failed)` + truncated head of paper_ids); regression: `tests/test_re_embed_all.py::TestRunExitCodes::test_per_dataset_failure_propagates_to_exit_code` (test mock updated to a real `list[str]`; asserts the formatted stderr).
- F3 — fixed in `tools/re_embed_all.py::discover_targets` (added `is_symlink()` check + WARNING log); regression: `tests/test_re_embed_all.py::TestDiscovery::test_skips_symlinked_notebook_dir`.
- F4 — fixed in `ingest/chunker_types.py:166-168` (inline comment now references the constants and the bump).
- F5 — fixed in `tools/re_embed_all.py::_cli` (basicConfig retains default no-logger-filter so `ingest.re_embed`'s per-paper INFO output reaches stderr).
- F6 — fixed in `tests/test_chunker.py::TestB2BudgetBumpTakesEffect` (comment now honest about "first to use this convention").
- F7 — fixed by creating `.claude/notes/milestones/embedder-truncation-m1/operator-followup.md` (B-3 procedure now tracked).
- F8 — deferred (LOW; broad `except Exception` documented + logged; programmer-bug isolation is a Phase 4 enhancement, not a regression).
- F9 — deferred (LOW; `_ALLOWED_SOURCE_KINDS` enforcement is textbook-ingest-m2's surface, not this milestone's).
- IS1 — fixed in `Makefile:re-embed-all` target (added the standard 3-line ARGS spaces-footgun comment block).
- IS2 — deferred (LOW; help-line column alignment is cosmetic).

All findings dispositioned. Invalidation rate: 0/2 HIGH = 0%; adversary critic prompt healthy.
