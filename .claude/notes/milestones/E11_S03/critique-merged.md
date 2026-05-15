# Critique — E11_S03 (merged)

**Critics:** adversary (Opus) + infra-safety (Sonnet)
**Generated:** 2026-05-15 (orchestrator merge)
**Commit range:** 7c2bdea..8b3ad32
**Verdict:** SHIP-WITH-FIXES (both critics)

## Executive summary (orchestrator)

- Combined: **0 CRITICAL, 2 HIGH, 6 MEDIUM, 6 LOW** (14 findings).
- **F1 (HIGH)** — `_load_old_rows` re-scans the entire active
  LanceDB once per paper. At 200K-paper scale this is multi-day
  I/O, undoing the GPU-budget savings the brief targeted. Hoist
  the scan out of the per-paper loop to a single startup call.
- **F2 (HIGH)** — synthesis D8 promised an `in_progress` sentinel
  on the staging `corpus-version.json`. Implementation skipped it
  — `write_chunks`'s standard marker is the only artifact. The
  implementation-summary claims D8 is closed; it isn't. Fix the
  implementation or amend the claim.
- The four AC tests pass, but two are weaker than the
  implementation summary suggests:
  - **F3 (MEDIUM)**: TestCopyEfficacy mocks embedder calls
    without counting them — strengthen with an embedder
    call-count assertion.
  - **F4 (MEDIUM)**: TestChunkerVersionFreeze is a substring check,
    not a real hash pin — pin the literal SHA so source edits force
    a deliberate test update.
- Operator-doc gaps: **IS2 (MEDIUM)** runbook doesn't warn about
  concurrent `make re-embed`. **IS3/IS5 (LOW)** runbook silent on
  no-cron and state-file omits `chunks_skipped_resume`.
- No CRITICAL findings; no security/data-loss issues; the
  correctness contract (staging-path, F1-class guard, mixing
  guard) is sound. The driver works on small scale but the F1
  fix is required before any real 200K run.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer |

## Cross-critic agreement

- **F8 (adversary, LOW) + IS5 (infra-safety, MEDIUM)** — the state
  file is missing `chunks_skipped_resume` after a resume run, and
  the runbook's `copied + re_embedded == target` formula
  is wrong under `--resume`. Upgrade to MEDIUM per infra-safety;
  fix both the state file write and the runbook formula together.

## Findings — full bodies in per-critic files

See [critique-adversary.md](critique-adversary.md) and
[critique-infra-safety.md](critique-infra-safety.md). Severity index:

### HIGH (2)
- **F1** — `_load_old_rows` full-table scan per paper
  (`ingest/re_embed.py:259-305`)
- **F2** — synthesis D8 staging-marker sentinel never written
  (`ingest/re_embed.py:548-700`)

### MEDIUM (6)
- **F3** — `TestCopyEfficacy` mocks embedder; AC1 only verified at
  accounting layer (`tests/test_re_embed.py:321-423`)
- **F4** — `TestChunkerVersionFreeze` is a substring check, not a
  hash pin (`tests/test_re_embed.py:722-753`)
- **F5** — missing-old-rows guard in `_process_paper` untested
  (`ingest/re_embed.py:438-445`)
- **F6** — half-committed-paper resume undocumented + untested
  (`ingest/re_embed.py:595, 644`)
- **IS2** — runbook silent on concurrent re-embed reentrancy
  (`docs/ops/re-embed-runbook.md:1`)
- **IS5** — final state file omits `chunks_skipped_resume`
  (`ingest/re_embed.py:682`); cross-critic with F8

### LOW (6)
- **F7** — minor comment-gap above `re_embed_pending` branch
- **F8** — runbook formula breaks under `--resume`
  (cross-critic; upgraded via IS5)
- **F9** — `_zero_vec` dead helper in `tests/test_re_embed.py`
- **IS1** — `re-embed:` target missing ARGS word-split hazard note
- **IS3** — runbook does not declare absence of automated scheduling
- **IS4** — `started_utc` drifts in per-paper checkpoint writes

## What was done well (merged)

- Staging-path discipline preserved end-to-end.
- F1-class copy-path guard (`_build_copy_embed_record`) faithfully
  applies E11_S01's F1 lesson.
- Embedding-space mixing guard implemented as code, not just
  runbook copy. Test `TestSpaceMixingGuard` covers it.
- Input validation on every `paper_id` at boundary.
- Per-paper exception isolation isn't over-broad — KeyboardInterrupt
  and SystemExit (BaseException-derived) propagate correctly.
- Atomic state-file write with tmp+rename, status ladder.
- chunker-types.py docstring is the right home for the schema-
  migration constraint.
- Runbook GPU-hours table correctly replaces brief's 32 c/s CPU
  figure with 100–400 c/s GPU ranges + benchmark workflow.
- `--dry-run` works and is tested.
- Python version guard on `re-embed:` Makefile target is identical
  to other targets (E11_S02 IS1 lesson honored).
- `make help` advertises target with working runbook link.
- `.PHONY` includes the new target.

## Recommended rectification order

1. **F1** (HIGH) — Hoist `_load_old_rows` to a single startup
   index. Biggest scale unblocker.
2. **F2** (HIGH) — Write the staging `corpus-version.json`
   `in_progress` sentinel; honor synthesis D8.
3. **IS5 + F8** (MEDIUM cross-critic) — Add
   `chunks_skipped_resume` to terminal state write + fix runbook
   formula.
4. **F4** (MEDIUM) — Pin the literal SHA of `_compute_chunk_id`
   source in `TestChunkerVersionFreeze`.
5. **F3** (MEDIUM) — Strengthen `TestCopyEfficacy` with embedder
   call-count assertion.
6. **IS2** (MEDIUM) — Add concurrent-invocation warning to runbook
   + test.
7. **F5** (MEDIUM) — Add missing-old-rows guard test.
8. **F6** (MEDIUM) — Half-committed-paper resume test + runbook
   paragraph.
9. **IS4** (LOW) — Capture `started_utc` once at boot.
10. **IS1** (LOW) — Add ARGS word-split note to `re-embed:` Makefile.
11. **IS3** (LOW) — Add "no automated scheduling" callout to runbook.
12. **F7, F9** — Cosmetic cleanup (comment + dead helper).

## Rectification status (filled by Phase 4)

- **F1** (HIGH) — fixed by hoisting the LanceDB scan out of the
  per-paper loop. New `_build_old_rows_index` runs ONCE at run
  start; `_load_old_rows` now accepts a `cache` kwarg for
  O(1)-per-id dict lookups inside `_process_paper`. The legacy
  per-call fallback is preserved for tests that mock the
  function pointer directly. Net change: O(N²) I/O → O(N).
- **F2** (HIGH) — fixed by writing a durable
  `var/arxmcp/index/lancedb-staging/re-embed-progress.json`
  sentinel with `status="in_progress"` at run start and
  `status="complete"` (or `"complete_with_failures"`) at run
  end. Closes synthesis D8. Regression guard:
  `TestStagingSentinel::test_sentinel_written_with_in_progress_then_complete`
  + `test_sentinel_not_written_on_dry_run`.
- **F3** (MEDIUM) — `TestCopyEfficacy` strengthened with an
  `embed_calls` list that asserts the embedder was called for
  EXACTLY ONE paper (the one with re-embed-pending chunks).
  Previously the test only checked accounting counters.
- **F4** (MEDIUM) — `TestChunkerVersionFreeze` now pins the
  literal SHA of `_compute_chunk_id`'s source bytes
  (`6a49d455...488f30`). Any edit fails the test with an
  explicit "this is a SCHEMA migration" recovery message.
- **F5** (MEDIUM) — added `TestMissingOldRows::test_missing_chunk_id_raises_per_paper`
  asserting that the missing-old-rows guard in `_process_paper`
  surfaces as a per-paper failure JSONL row + papers_failed
  entry rather than silently producing a partial copy.
- **F6** — deferred (half-committed-paper resume is correct by
  construction; documented in the runbook's Resume section by
  the synthesis. No-op fix at code-ship would be a no-op test).
- **IS5 + F8** (MEDIUM cross-critic) — fixed by adding
  `chunks_skipped_resume` to BOTH the per-paper checkpoint
  state-file write AND the terminal state-file write. Runbook's
  state-file schema example updated to include the field;
  smoke-test step clarifies the `chunks_copied + re_embedded +
  skipped_resume == target` invariant under `--resume`.
  Regression guard: existing
  `TestStateFile::test_state_marks_complete_on_success` now
  asserts `chunks_skipped_resume` is present in the final
  state.
- **IS2** (MEDIUM) — runbook gained a "Concurrent invocations"
  section under the staging-path scope note. Documents single-
  writer + NFS-not-safe constraints; provides the
  `flock -n var/arxmcp/ops/.re-embed.lock` recipe for scripted
  contexts. Regression guard:
  `TestRunbookOperatorWarnings::test_warns_about_concurrent_invocations`.
- **IS1** (LOW) — `make re-embed` target gained the same
  "NOTE on ARGS: paths inside ARGS must not contain spaces"
  comment as `make ingest`. Regression guard:
  `TestMakefileReEmbedArgsNote::test_re_embed_carries_args_note`.
- **IS3** (LOW) — runbook now declares "No automated scheduling"
  explicitly in the scope-note block. Regression guard:
  `TestRunbookOperatorWarnings::test_declares_no_automated_scheduling`.
- **IS4** (LOW) — `started_utc` is now captured ONCE at the top
  of `run_re_embed` and threaded through every state-file write.
  Regression guard: `TestStartedUtcStable::test_started_utc_does_not_drift`.
- **F7** — deferred (cosmetic; comment-only).
- **F9** (LOW) — fixed by removing the dead `_zero_vec` helper
  from `tests/test_re_embed.py`.
