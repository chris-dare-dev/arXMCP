# Critique — E11_S03

**Critic:** infra-safety
**Generated:** 2026-05-15T00:00:00Z
**Commit range:** 7c2bdea..8b3ad32
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: 0 CRITICAL, 0 HIGH, 2 MEDIUM, 3 LOW. The most
  important fix is IS2 (MEDIUM): the runbook is silent on concurrent
  `make re-embed` invocations even though `delta-loop.md` establishes
  an explicit flock precedent; an operator could start two parallel
  runs against the same staging LanceDB and corrupt it.
- IS5 (MEDIUM): the final `_write_state` call omits `chunks_skipped_resume`,
  so after a `--resume` run the state file is the only persistence artifact
  and it cannot tell the operator how many chunks were skipped.
- IS1 (LOW): the `re-embed` target in `Makefile:131` is missing the
  `NOTE on ARGS` word-split hazard comment that `ingest:` carries;
  `--paper-ids-file` is equally vulnerable to space-in-path splits.
- IS3 (LOW): the runbook has no explicit "human-initiated; no cron/systemd
  unit" statement, creating a risk that operators silently expect an automated
  re-embed run that will never happen.
- IS4 (LOW): `started_utc` in the per-paper checkpoint write uses
  `_utc_iso()` (live clock) instead of the boot timestamp captured at
  run start, so operators monitoring the state file mid-run see a drifting
  start time rather than the true wall-clock start.
- The Python version guard pattern is identical to `ingest:`, `delta:`,
  `up:`, and `eval:` — no regression there.
- `make help` correctly advertises the new target with the runbook link.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### IS2 — Runbook silent on concurrent re-embed reentrancy risk

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** docs/ops/re-embed-runbook.md:1
- **What:** The runbook has no text about concurrent invocation of
  `make re-embed`. Two operators (or two terminal sessions) issuing
  `make re-embed` simultaneously will both open the same
  `lancedb-staging/` path for write, which violates LanceDB's
  single-writer invariant and can corrupt the staging dataset.
- **Why it matters:** `delta-loop.md` establishes an explicit project
  precedent: the delta loop documents `flock -n` on line 77, warns
  "Do NOT run the delta loop from two hosts" on line 79, and explains
  the NFS-unsafety concern. The re-embed runbook is silent on all of
  these — an operator familiar with the delta pattern would not know
  whether the re-embed driver has equivalent protection or relies on
  a different mechanism.
- **Proposed fix:** Add a "Concurrent invocations" warning section to
  `docs/ops/re-embed-runbook.md` before the Procedure section:

  ```markdown
  ## Concurrent invocations

  `make re-embed` is **human-initiated** in v1; there is no cron or
  systemd unit (see also: no scheduled job exists — §). Only one
  instance should run against a given staging LanceDB at a time.
  LanceDB's single-writer invariant is not NFS-safe; running from two
  hosts against a shared `var/` will corrupt the staging dataset.

  Unlike the delta loop (which ships a `flock` shell wrapper), the
  re-embed driver does not include a lock guard because it is not
  expected to run unattended. If you need to protect against accidental
  double-invocation in a scripted context, wrap with:
  ```sh
  flock -n var/arxmcp/ops/.re-embed.lock make re-embed ARGS="..."
  ```
  ```

- **Regression guard:** Add a `TestRunbookContent::test_warns_concurrent`
  test to `tests/test_re_embed.py` asserting `"concurrent"` or
  `"single instance"` appears in the runbook text. Keeps it honest as
  the runbook evolves.

### IS5 — Final state file omits chunks_skipped_resume

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** ingest/re_embed.py:682
- **What:** The `_write_state` call that writes the terminal state
  (`"complete"` or `"complete_with_failures"`) does not include
  `chunks_skipped_resume` in the dict. The field is accumulated in
  `summary.chunks_skipped_resume` and appears on the CLI summary line
  (`skipped_resume=...`), but the persisted state file is the only
  durable record — the terminal state is what operators inspect with
  `cat var/arxmcp/ops/re-embed-state.json` after the run.
- **Why it matters:** After a `--resume` run, an operator cannot
  determine from the state file alone how many chunks were skipped
  because they were already in staging. The CLI output scrolls away;
  the state file is the durable artifact. The runbook's state file
  schema example also omits this field, compounding the confusion.
- **Proposed fix:** Add `"chunks_skipped_resume": summary.chunks_skipped_resume`
  to the terminal `_write_state` dict in `ingest/re_embed.py` at the
  final `_write_state` block (around line 682). Also add the field
  to the runbook's state file schema example.
- **Regression guard:** Extend `TestStateFile::test_state_marks_complete_on_success`
  to assert `state["chunks_skipped_resume"]` is present (even if 0)
  in the final state dict.

### IS1 — re-embed target missing ARGS word-split hazard note

- **Severity:** LOW
- **Source:** infra-safety
- **File:** Makefile:131
- **What:** The `ingest:` target carries an explicit comment block
  "NOTE on ARGS: paths inside ARGS must not contain spaces — Make's
  shell expansion splits at whitespace before argparse sees the tokens"
  (lines 90-92). The new `re-embed:` target does not. The
  `--paper-ids-file` flag accepts a path and has the same word-split
  hazard.
- **Why it matters:** An operator who copies the `make re-embed
  ARGS="--paper-ids-file=/path/with spaces/seed.txt"` form will
  silently pass garbage to argparse rather than getting a clear error.
  The `ingest:` target documented this exactly because it was a live
  foot-gun in E11_S01; the re-embed target repeats the same interface
  without the same documentation.
- **Proposed fix:** Add the note to the `re-embed:` comment block in
  `Makefile`, parallel to the `ingest:` block:

  ```makefile
  @# NOTE on ARGS: paths inside ARGS must not contain spaces — Make's
  @# shell expansion splits at whitespace before argparse sees the
  @# tokens. Use an absolute, space-free path for --paper-ids-file.
  ```

- **Regression guard:** No test needed for a comment addition; the
  `TestMakefileReEmbedTarget` test in `tests/test_re_embed.py` can
  be extended to assert `"spaces" in text or "NOTE on ARGS" in text`
  in the `re-embed:` target block.

### IS3 — Runbook does not declare absence of automated scheduling

- **Severity:** LOW
- **Source:** infra-safety
- **File:** docs/ops/re-embed-runbook.md:1
- **What:** The runbook does not state that no cron job, systemd
  unit, or other automated scheduler exists for `re-embed`. The
  `delta-loop.md` runbook explicitly mentions the systemd unit
  (`ops/systemd/arxmcp-delta.{service,timer}`) and its cron
  alternative. An operator reading the re-embed runbook has no signal
  either way.
- **Why it matters:** If an operator assumes a nightly automated
  re-embed keeps the corpus fresh (by analogy with the delta loop),
  they may silently defer manual intervention after a chunker bump.
  Making the human-initiated, ad-hoc nature explicit prevents this
  assumption. The CLAUDE.md brief says "human-initiated in v1"; the
  runbook should mirror that.
- **Proposed fix:** Add one short callout box near the top of the
  runbook (under the staging-path discipline block):

  ```markdown
  > **No automated scheduling.** `make re-embed` is human-initiated in
  > v1. There is no cron job or systemd unit. An operator must run it
  > manually after every `CHUNKER_VERSION` or `EMBEDDER_VERSION` bump.
  ```

- **Regression guard:** Extend `TestRunbookContent` in
  `tests/test_re_embed.py` to assert the word "human-initiated" or
  "no cron" appears in the runbook text.

### IS4 — started_utc drifts in per-paper checkpoint writes

- **Severity:** LOW
- **Source:** infra-safety
- **File:** ingest/re_embed.py:674
- **What:** The per-paper checkpoint `_write_state` call on line 674
  uses `_utc_iso()` (live clock) for `started_utc`, with the comment
  "close-enough; written at boot". As a result, an operator tailing
  `re-embed-state.json` mid-run sees a `started_utc` that advances
  after every paper, making it impossible to compute wall-clock elapsed
  time from the state file.
- **Why it matters:** The `last_checkpoint_utc - started_utc` delta
  is the natural way to estimate remaining time. A drifting
  `started_utc` makes this calculation meaningless. The boot-start
  timestamp is computed in `run_re_embed` (`started = time.monotonic()`)
  but is not converted to an ISO timestamp at that point.
- **Proposed fix:** Capture the UTC start time once at the top of
  `run_re_embed` and pass it through to every `_write_state` call:

  ```python
  started = time.monotonic()
  started_utc = _utc_iso()
  ```

  Then replace `"started_utc": _utc_iso()` in the checkpoint write
  with `"started_utc": started_utc`.

- **Regression guard:** `TestStateFile` — extend one test to verify
  that the `started_utc` value in the state file after a multi-paper
  run equals the initial write's `started_utc` (same string, not
  drifted).

## What was done well

- The Python version guard is byte-for-byte identical to the guard in
  `ingest:`, `delta:`, `eval:`, and `up:` — format, error message,
  and override hint all match. E11_S02 IS1 is properly closed here.
- `make help` advertises `re-embed` with a runbook pointer
  (`docs/ops/re-embed-runbook.md`) that matches the actual file path
  exactly — no dead link.
- `$(ARGS)` pass-through is present at the same position in the recipe
  as in `ingest:` and `delta:`, allowing the operator to specify
  `--paper-ids-file`, `--dry-run`, `--resume`, and
  `--target-embedder-version` without Makefile changes.
- The `re-embed:` target is added to `.PHONY` — no file named
  `re-embed` can shadow the target.
- The Makefile comment block correctly explains the staging-path
  discipline (never touches the active `corpus-version.json`) and
  cross-references the E11_S05 cutover milestone explicitly.
- The runbook's GPU-hours table covers all four bump scenarios with
  three throughput columns (conservative / mid / optimistic); the
  `--dry-run` benchmark workflow gives operators a way to validate
  their specific hardware before committing to a full run.
- The embedding-space mixing guard is documented at two levels —
  in the runbook warning AND as a named code guard — matching the
  F1-class guard pattern from E11_S01.
- The `--resume` semantics are precisely documented in both the code
  docstring and the runbook, including the explicit warning against
  using `--resume` when the staging dataset has a stale
  `embedder_version`.
- The state file is written atomically (`tmp.replace(path)`) with
  per-paper checkpoints, which satisfies the crash-recovery pattern
  from the E11_S01 and E11_S02 runbooks.
- Four test classes (AC1–AC4) are structurally complete with mocked
  LanceDB boundaries; test count meets milestone acceptance criteria.

## Recommended rectification order

1. **IS2** — add concurrent-invocation warning to runbook. Cheap (≤ 10
   lines of documentation + 3-line regression test). Addresses the only
   operator-safety gap with a clear precedent from `delta-loop.md`.
2. **IS5** — add `chunks_skipped_resume` to the terminal `_write_state`
   call. One-line code change; extend one existing test. Ensures the
   state file is a complete, durable record for `--resume` runs.
3. **IS4** — capture `started_utc` at boot and thread it through to
   checkpoint writes. ~5-line code change; makes elapsed-time estimation
   correct for operators monitoring long runs.
4. **IS1** — add the `NOTE on ARGS` comment to the `re-embed:` target.
   A two-line Makefile comment; no code change needed.
5. **IS3** — add "no automated scheduling" callout to the runbook. One
   line of documentation; optionally extend `TestRunbookContent`.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate. -->
