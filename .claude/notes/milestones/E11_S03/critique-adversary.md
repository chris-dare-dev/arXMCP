# Critique — E11_S03

**Critic:** adversary
**Generated:** 2026-05-15T00:00:00Z
**Commit range:** 7c2bdea..8b3ad32
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict: SHIP-WITH-FIXES. The driver's correctness contract (content-
  addressable copy + F1-class version guard + staging-path discipline)
  is sound, but `_load_old_rows` re-scans the entire active LanceDB
  per-paper — at 200K-paper scale this is the disk-time analogue of
  the GPU-day cost the brief was written to avoid.
- Finding counts: 0 CRITICAL, 2 HIGH, 4 MEDIUM, 3 LOW.
- Highest-risk file: `ingest/re_embed.py:259-305` (`_load_old_rows`
  full-table scan per paper).
- Synthesis decision D8 ("write `{status: in-progress}` sentinel to
  the STAGING `corpus-version.json`") was NOT implemented — the marker
  is overwritten on every per-paper `write_chunks` call with a normal
  doc; only the OPS state file gets the sentinel. AC4-adjacent: the
  runbook never advertised the sentinel either.
- Cross-axis pattern: the AC1 test (`TestCopyEfficacy::test_95_percent_copy`)
  is mock-heavy enough that it proves the orchestrator's accounting but
  not the no-recompute invariant. Same shape applies to AC2 — the test
  passes because the mocked `_staging_chunk_ids` returns a fixed set,
  not because the production code threads paths correctly.
- The `TestChunkerVersionFreeze` regression guard is performative: it
  only checks that three substrings (`unicodedata.normalize`, `NFC`,
  `sha256`, `preamble_text`) appear in `_compute_chunk_id`'s source.
  A deliberate rewrite that preserved those tokens but changed the
  algorithm would pass. The expected_sha placeholder is declared then
  immediately `del`'d — dead code that documents the intent without
  enforcing it.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC) |
| LOW | style, naming, micro-perf | defer to `deferred_findings` |

## Findings

### F1 — `_load_old_rows` full-table scan per paper is O(N²) at scale

- **Severity:** HIGH
- **Source:** adversary
- **File:** ingest/re_embed.py:259-305
- **What:** `_load_old_rows` calls `tbl.to_arrow(columns=[...])` —
  which materializes the ENTIRE chunks-table for the listed columns
  into memory — and is invoked once per paper from `_process_paper`
  (re_embed.py:436). At 200K papers × 5M rows × (chunk_id + 2×1024-
  float embedding vectors + version + kind) per scan, the I/O alone
  is multi-day for the very common-case scenarios the brief targeted
  (chunker fix at 5% drift, macro-normalizer fix at 1%).
- **Why it matters:** the brief's stated GPU-budget motivation —
  "5M chunks ≈ 5M GPU-day → partial path makes it 250K chunks ≈ 2h"
  — is undone by the per-paper full-scan I/O cost. Worse, the
  function reads the two 1024-d embedding columns (~8KB/row × 5M
  rows = 40GB / scan) into Python lists via `.to_pylist()`, so peak
  RSS during one call can exceed available RAM on a workstation.
- **Proposed fix:** hoist the old-rows scan out of the per-paper
  loop. One `to_arrow()` call at run start indexed by `chunk_id` →
  `(stmt_vec, proof_vec, version, kind)` dict (or arrow table sliced
  by paper_id once). Alternatively, accept LanceDB's `where=` SQL
  filter (e.g. `chunk_id IN (...)`) per-paper but verify it works on
  the pinned 0.30 version — the docstring's claim of "doesn't
  support `IN (...)` cleanly across versions" should be checked.
- **Regression guard:** add a unit test that counts the number of
  `_load_old_rows` calls during a 10-paper run and asserts it's
  ≤ 1, OR rewrite the function so its work is amortized at run
  start. Add a perf-budget assertion in the runbook that fails the
  smoke-run if per-paper wall-clock exceeds N seconds.

### F2 — Synthesis D8 staging-marker sentinel was promised but never written

- **Severity:** HIGH
- **Source:** adversary
- **File:** ingest/re_embed.py:548-700
- **What:** Synthesis D8 (research-synthesis.md:192-212) and §8
  ("staging corpus-version.json sentinel + final marker") commit to
  writing `{"status":"in-progress","target_version":N,...}` to the
  STAGING `corpus-version.json` at run start, with rewrite by
  `write_chunks`'s postcondition at run end. The implementation
  ONLY writes a sentinel to the OPS state file at
  `var/arxmcp/ops/re-embed-state.json`. The staging
  `var/arxmcp/index/lancedb-staging/corpus-version.json` is
  overwritten on every per-paper `write_chunks` call with a
  standard `{version, embedder_version, chunker_version,
  paper_count, chunk_count}` doc — there is no `status` field, no
  `in-progress` sentinel, and an operator/external tool examining
  the staging marker mid-run cannot tell the run is incomplete.
- **Why it matters:** the staging marker is documented as
  "authoritative server startup config" (ingest/store.py:486). An
  E11_S05 cutover script that promotes a half-finished staging
  dataset by swinging `corpus-version.json` will boot the server
  on partial data with no detection. The synthesis explicitly
  named this risk and the implementation summary's AC list claims
  D8 is closed (item 8) — it isn't.
- **Proposed fix:** at run start in `run_re_embed`, write the
  staging-side `corpus-version.json` with `{"status":
  "in_progress", "target_embedder_version": ..., ...}` BEFORE the
  first `write_chunks` call. On successful completion, overwrite
  with a clean `{"status": "complete", "version": <int>, ...}`
  doc. Either patch `write_chunks` to skip the marker write when
  it sees an in-progress sentinel already present, or rewrite the
  sentinel after every paper to keep `status` durable through
  per-paper writes.
- **Regression guard:** add `TestStagingMarkerSentinel` asserting
  the staging `corpus-version.json` carries `status="in_progress"`
  between paper-1 and paper-N writes, and `status="complete"`
  only after `run_re_embed` returns.

### F3 — `TestCopyEfficacy::test_95_percent_copy` mocks the embedder; AC1 is unverified

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_re_embed.py:321-423
- **What:** The 95%-copy test patches `chunk_paper`, `embed_paper`,
  `load_embed_record`, `_load_old_rows`, `_index_old_chunk_ids_by_paper`,
  `_check_staging_embedder_versions`, AND `write_chunks` — every
  external call is a mock. The embedder mock returns `EmbedStats(
  status="ok")` without performing any GPU work, so the test
  proves only the orchestrator's accounting counters
  (`chunks_copied == 95`, `chunks_re_embedded == 5`). It does NOT
  prove "95% copied without re-compute" because no compute path
  is exercised at all.
- **Why it matters:** AC1 says "verifiable via log". The current
  test's claim of AC1 closure is over-stated — a regression in
  `_process_paper` that called `embed_paper` redundantly for the
  copy ids (e.g. routing the copy chunks through the re-embed
  path) would still pass this test because `_embed_paper_stub`
  succeeds either way. Implementation-summary line 47 says
  "Embedder mocked to record calls" but the spy doesn't actually
  assert on call count vs. expected re-embed-pending size.
- **Proposed fix:** add an `embed_call_count` counter to the
  `_embed_paper_stub` and assert it equals the count of papers
  with re-embed-pending chunks (in the synthetic fixture, exactly
  1: paper 9). Currently the assertion is only `any(len(c[1]
  .chunk_ids_stmt) == 5 for c in write_spy.calls)` — strengthen
  to `embed_call_count == 1` AND `re_embed_pending_paper_count ==
  1`. Also assert `write_chunks` was called with a `chunks` list
  matching the copy-pending IDs for each of the 9 copy-only papers.
- **Regression guard:** the strengthened assertions above are the
  guard.

### F4 — `TestChunkerVersionFreeze` is a substring check, not a hash pin

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_re_embed.py:722-753
- **What:** The test computes `sha = hashlib.sha256(src.encode())
  .hexdigest()` then `del expected_sha, sha  # placeholder values
  for the doc`. The actual assertions check only that the strings
  `unicodedata.normalize`, `NFC`, `sha256`, and `preamble_text`
  appear in `_compute_chunk_id`'s source. The implementation
  summary calls this "the regression guard" closing Landmine A
  (synthesis §6.1); chunker_types.py:43 references it by name.
- **Why it matters:** a deliberate-or-accidental rewrite that
  kept those four tokens but changed the algorithm — e.g.
  `digest = hashlib.sha256((preamble_text + body_text).encode("utf-8"))
  .hexdigest()[:16]` (removes NFC on body) — passes this guard.
  The bytestring `NFC` is in the docstring; `unicodedata.normalize`
  could be moved to dead code. The synthesis decision was that
  any change to `_compute_chunk_id` is a schema migration; the
  test does not enforce this.
- **Proposed fix:** compute the SHA at test-collection time, pin
  the literal hash, and remove the `del` line. When the function's
  source bytes change (whitespace, docstring edit, anything), the
  test fails with a message telling the maintainer to either
  revert OR bump `CHUNKER_VERSION` and re-pin. The cost is one
  test-update per intentional change to `_compute_chunk_id` —
  the exact friction the regression guard is supposed to introduce.
- **Regression guard:** the pinned literal hash IS the guard.

### F5 — Missing-ids guard in `_process_paper` is uncovered by tests

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/re_embed.py:438-445; tests/test_re_embed.py
- **What:** When `_load_old_rows` returns fewer rows than
  requested (`missing = copy_pending - old_rows.keys()`),
  `_process_paper` raises `RuntimeError("chunk-id set may have
  drifted out of sync...")`. No test exercises this branch — it's
  triggered only if the active LanceDB is mutated concurrently
  with the re-embed run (a race) OR if a chunk_id collision
  occurs across papers, both of which are documented as
  impossible by construction but worth guarding.
- **Why it matters:** the per-paper isolation in `run_re_embed`
  wraps `_process_paper` in `except Exception` and demotes the
  failure to `papers_failed`. A drifted-source-of-truth condition
  would be silently demoted to a per-paper failure log entry
  instead of halting the run. For a long-running operator-driven
  job, this is the difference between "1 paper failed, retry it"
  and "the entire run is built on a stale view of the source".
- **Proposed fix:** add `TestMissingOldRowsRaises` that mocks
  `_load_old_rows` to return a short dict, runs a single paper,
  and asserts that the resulting failure is appended to
  `failures_path` with `reason="process_failed"` AND that the
  `papers_failed` summary contains the paper_id. Optionally,
  promote `missing` to a CRITICAL-class failure that aborts the
  entire run rather than per-paper isolation.
- **Regression guard:** the test above.

### F6 — Resume-window snapshot is taken once; staging writes invalidate it

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/re_embed.py:595, 644
- **What:** `already_in_staging = _staging_chunk_ids(staging_lancedb_path)
  if resume else set()` runs ONCE at run start. The set is then
  passed by reference to every `_process_paper` call. After paper
  K writes its chunks to staging, the staging table grows but
  `already_in_staging` does NOT — so paper K+1's `_process_paper`
  call sees the same pre-run snapshot. By the chunk_id
  construction (paper_id is in the hash input) this is correct on
  paper boundaries: a chunk_id from paper K cannot appear in
  paper K+1's plan. But on resume-after-crash mid-paper-K, the
  resume snapshot will already include any of paper K's chunks
  that committed before the crash, so the math works out — except
  the failure case where `write_chunks` committed copy chunks but
  the re-embed path then crashed (line 458-487). On the next
  resume run, the copy chunks are seen-in-staging but the re-embed
  chunks are not; both paths fall back to the work-queue
  difference cleanly. This case is undocumented and untested.
- **Why it matters:** the runbook (re-embed-runbook.md:170-180)
  asserts resume is "uniform across the copy AND re-embed paths"
  but does not address the half-committed-paper case explicitly.
  An operator who observes a crash mid-paper-K and resumes might
  reasonably expect paper K to be retried in full; the actual
  behavior is "retry only the half that didn't commit", which is
  fine but should be documented.
- **Proposed fix:** add a test
  `TestResumeMidPaper::test_half_committed_paper_resumes_other_half`
  that seeds the staging table with HALF a paper's chunks, runs
  with resume=True, and asserts the other half gets written. Also
  add a paragraph to the runbook clarifying the half-committed
  semantics.
- **Regression guard:** the test above.

### F7 — `embed_paper` is called even when `re_embed_pending` is empty-after-resume

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/re_embed.py:458-487
- **What:** `_process_paper` computes `re_embed_pending =
  plan.re_embed_ids - already_in_staging`. If `re_embed_pending`
  is non-empty BEFORE the resume subtraction but EMPTY after, the
  re-embed branch is skipped. Good. But the comment block doesn't
  state this; a future refactor that moved the resume filter
  could inadvertently re-introduce wasted GPU work on resume.
- **Why it matters:** minor — the code is correct today. The
  invariant is implicit.
- **Proposed fix:** add a one-line comment above the `if
  re_embed_pending` branch noting that the resume filter has
  already been applied.

### F8 — Runbook formula `copied + re_embedded == target` breaks under --resume

- **Severity:** LOW
- **Source:** adversary
- **File:** docs/ops/re-embed-runbook.md:105
- **What:** "Inspect ... should show `status: "complete"` and
  `chunks_copied + chunks_re_embedded == chunks_target`." Under
  `--resume`, this is FALSE — the second-run summary's
  `chunks_copied` and `chunks_re_embedded` reflect only the work
  done in THIS run, while `chunks_target` reflects the full
  re-chunk count. The state file's cumulative semantics aren't
  defined in the docs.
- **Why it matters:** operator confusion. The smoke-run check
  in step 2 instructs operators to verify the sum equality. After
  any resume run this check fails cosmetically.
- **Proposed fix:** add a note: "On a resume run, also account
  for `chunks_skipped_resume`: `chunks_copied + chunks_re_embedded
  + chunks_skipped_resume == chunks_target`." Or, more cleanly,
  make `chunks_copied`/`chunks_re_embedded`/`chunks_skipped_resume`
  accumulate across resume runs (today the state file is
  truncated/rewritten on resume start, losing prior numbers).

### F9 — `_zero_vec` in test file is dead code

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/test_re_embed.py:45-46
- **What:** `_zero_vec()` is defined at module top but never
  called. `ruff check .` does not catch unused module-level
  helpers; `_normalized()` is used.
- **Why it matters:** style hygiene. The implementation summary
  lists "ruff clean" as a green; this is below the threshold.
- **Proposed fix:** remove `_zero_vec` from tests/test_re_embed.py.

## What was done well

- The staging-path discipline is correctly preserved: every
  `write_chunks` call routes through `staging_lancedb_path`, the
  active marker is never touched, and the architecture documents
  this explicitly (re_embed.py:28-30, runbook line 12-14). Cache
  validity per note 07 is intact.
- The F1-class copy-path guard (`_build_copy_embed_record`) is a
  faithful and well-documented application of the lesson from
  E11_S01's F1 silent-stale-embed rectification — old rows whose
  `embedder_version` doesn't match the recorded
  OLD_EMBEDDER_VERSION are refused with a clear error citing the
  embedding-space-mixing risk.
- The embedding-space-mixing guard (`_check_staging_embedder_versions`)
  is implemented as code, not just runbook copy, and the
  refusal-on-mismatch test (`TestSpaceMixingGuard`) covers it.
  The synthesis decision to REJECT the `--force-mixed-space`
  escape hatch is upheld.
- Input validation on every `paper_id` (re_embed.py:590-592)
  closes the threat-model concern about path-traversal-in-input;
  the test `TestPaperIdValidation::test_invalid_paper_id_in_list_raises`
  pins it.
- Per-paper exception isolation (`except Exception` at
  re_embed.py:618, 646) is correct: `BaseException`-derived
  signals (KeyboardInterrupt, SystemExit) propagate; only
  Exception-class faults are demoted to per-paper failure rows
  in `re-embed.jsonl`. The adversary's hunch that
  KeyboardInterrupt would be swallowed is wrong in Py3.
- The atomic state-file write (`_write_state` with `tmp + replace`)
  matches the precedent established in E11_S02 and the
  preamble-writer pattern. Status ladder (`in_progress` →
  `complete` / `complete_with_failures`) is sensible.
- The chunker-types docstring addition (chunker_types.py:30-44)
  is the right home for the "schema-migration constraint" — it
  documents the contract at the same file where `CHUNKER_VERSION`
  lives, so a future contributor editing the version constant
  reads it in context.
- Runbook GPU-hours table corrects the brief's wrong 32 c/s (CPU)
  figure to 100-400 c/s (GPU) ranges across three scenarios, and
  includes a benchmark-on-your-hardware command (`make re-embed
  ARGS="... --dry-run"`).
- `--dry-run` exists, prints `<paper_id> copy=N reembed=N drop=N`
  per line (re_embed.py:629-635), and is exercised by
  `TestDryRun::test_dry_run_skips_writes`.

## Recommended rectification order

1. **F1** — hoist `_load_old_rows` out of the per-paper loop. This
   is the single biggest blocker to actually using the driver at
   scale; the test fixtures don't catch it because they cap at 10
   papers. Pre-index the active LanceDB once at run start.
2. **F2** — write the staging `corpus-version.json` sentinel. The
   synthesis promised it; the implementation summary claims it's
   shipped; it isn't. Either implement or amend the
   synthesis/implementation-summary to match reality.
3. **F4** — pin the literal SHA in `TestChunkerVersionFreeze`. One-
   line change after re-running the test; closes the substring-
   check gap.
4. **F3** — strengthen `TestCopyEfficacy` to count embedder calls.
5. **F5** — add the missing-old-rows guard test.
6. **F6** — half-committed-paper-resume test + runbook paragraph.
7. **F8** — runbook formula clarification.
8. **F7, F9** — cosmetic; bundle into any rectification commit.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate. -->
