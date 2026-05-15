# Critique — E11_S01

**Critic:** infra-safety
**Generated:** 2026-05-14T00:00:00Z
**Commit range:** e274edd..f0a19c6
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES. The scaffolding is structurally sound, staging-path
  isolation is correct, and the dry-run flag exists — but three findings
  must be rectified before Phase 4 closes.
- 0 CRITICAL, 2 HIGH, 2 MEDIUM, 1 LOW.
- Highest-risk issue: `Makefile:80` — the `ingest:` target omits the
  Python version guard present in every other target (`test`, `eval`,
  `up`). On the default system Python 3.9, `make ingest ARGS="..."` silently
  crashes with `TypeError: dataclass() got an unexpected keyword argument
  'slots'` before the CLI even parses `--paper-ids-file`, producing a
  confusing error that obscures the real problem.
- Secondary risk: `ingest/bulk_ingest.py:338` — `run_bulk_ingest`'s
  `resume` parameter is accepted by the CLI and documented in the runbook
  as a crash-recovery mechanism, but is silently dropped inside the loop
  body. `--resume` advertises behaviour it does not implement.
- Cross-axis pattern: the `$(ARGS)` unquoted expansion is a pre-existing
  Makefile convention (matches `make test` style) and carries only a minor
  word-splitting hazard on paths with spaces — MEDIUM, not HIGH.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### IS1 — `ingest:` target missing Python version guard

- **Severity:** HIGH
- **Source:** infra-safety
- **File:** `Makefile:80`
- **What:** Every other substantive target (`bootstrap:`, `test:`, `eval:`,
  `up:`) begins with a `@$(PYTHON) -c "import sys; assert
  sys.version_info >= (3, $(MIN_PY_MINOR)), ..."` guard that aborts with an
  actionable message if the wrong Python is on PATH. The new `ingest:` target
  omits this guard entirely. On macOS the default `PYTHON ?= python3`
  resolves to `/usr/bin/python3` (3.9.6), which fails with
  `TypeError: dataclass() got an unexpected keyword argument 'slots'` at
  import time — before argparse, before any CLI help is printed.
- **Why it matters:** An operator who follows the runbook's
  `make ingest ARGS="--paper-ids-file=tools/seed-papers.txt --limit=5"`
  smoke-test step will see a Python traceback with no indication that the
  fix is `PYTHON=$(uv run which python) make ingest ...` or
  `make ingest PYTHON=python3.12`. The error is especially confusing on
  macOS where the system Python is the obvious `python3`.
- **Proposed fix:** Add the guard as the first recipe line in `ingest:`,
  matching the pattern used in `up:`:
  ```makefile
  ingest:
  	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, $(MIN_PY_MINOR)), \
  		f'arXMCP requires Python >= 3.$(MIN_PY_MINOR); got {sys.version_info[:2]}. \
  Try: make ingest PYTHON=python3.$(MIN_PY_MINOR)'"
  	$(PYTHON) -m ingest.bulk_ingest $(ARGS)
  ```
- **Regression guard:** Add a shell-level test in `tests/test_makefile.py`
  (or extend the existing Makefile smoke test if one exists) that runs
  `make ingest PYTHON=python2.7 2>&1` (or a known-bad Python) and asserts
  the output contains "requires Python".

---

### IS2 — `--resume` silently no-ops; CLI lies to the operator

- **Severity:** HIGH
- **Source:** infra-safety
- **File:** `ingest/bulk_ingest.py:338` (signature), `365` (call site)
- **What:** `run_bulk_ingest` accepts `resume: bool = False` and the
  docstring states it "skips papers whose embeddings sidecar already
  exists". However, the loop body at lines 365–370 calls `ingest_one_paper`
  without passing `resume` or any sidecar-check logic; the parameter is
  consumed but never acted upon. `--resume` effectively does nothing.
- **Why it matters:** The runbook (`docs/ops/bulk-ingest-runbook.md:165`)
  explicitly tells the operator to use `--resume` to recover an interrupted
  multi-day ingest without re-processing already-embedded papers. In
  practice the flag is ignored, so a resumed run re-chunks and re-embeds
  every paper, wasting hours of GPU time and potentially overwriting
  staging-LanceDB rows that were already clean. This violates the brief's
  explicit "resume mode skips already-processed papers" requirement
  (research synthesis D8).
- **Proposed fix:** Add a sidecar check before the `ingest_one_paper` call:
  ```python
  from ingest.embedder import _sidecar_path  # or equivalent exported helper
  ...
  for n, paper_id in enumerate(work, start=1):
      if resume and _sidecar_path(paper_id).is_file():
          summary.papers_skipped += 1
          continue
      outcome = ingest_one_paper(...)
  ```
  Alternatively, move the sidecar guard inside `ingest_one_paper` (passing
  `skip_if_sidecar_exists=resume`) if the sidecar path helper is already
  accessible there.
- **Regression guard:** Add a unit test in `tests/test_bulk_ingest.py` that
  calls `run_bulk_ingest([paper_id], resume=True)` on a paper whose sidecar
  already exists and asserts `summary.papers_skipped == 1` and that
  `ingest_one_paper` is NOT called (via a mock / spy).

---

### IS3 — Unquoted `$(ARGS)` in Makefile; word-split hazard on paths with spaces

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** `Makefile:89`
- **What:** The recipe line `$(PYTHON) -m ingest.bulk_ingest $(ARGS)`
  leaves `$(ARGS)` unquoted. If the operator passes a path containing
  spaces — e.g.
  `make ingest ARGS="--paper-ids-file='my papers/seed.txt'"` — Make's
  shell expansion splits the argument at the space boundary before the
  shell sees it, causing argparse to receive `--paper-ids-file=my` and
  `papers/seed.txt` as separate tokens. The error message from argparse
  (`unrecognized argument: papers/seed.txt`) is non-obvious.
- **Why it matters:** The target categories (math.AG, hep-th) have enough
  operator diversity that a macOS operator with a space-bearing home
  directory or a file on a network share will encounter this silently.
  The `--paper-ids-file is required` guard at the Python level does NOT
  catch this variant.
- **Proposed fix:** Wrap the expansion: `$(PYTHON) -m ingest.bulk_ingest
  $(if $(ARGS),$(ARGS),)` — this does not solve the underlying word-split
  problem for paths with spaces, but the correct fix is documenting that
  operators should not use paths with spaces for the input file (the
  Makefile comment block at line 83 is a good place for this) OR switching
  to `$(value ARGS)` with single-quote wrapping. The lowest-risk tactical
  fix for v1 is a one-line comment in the Makefile: `# ARGS must not
  contain shell-metacharacter paths; use an absolute path without spaces.`
- **Regression guard:** Document in the runbook's "Failure modes" section.
  No automated test is practical here (Makefile shell expansion is
  environment-dependent).

---

### IS4 — `make help` still advertises `ingest` as "not yet implemented"

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** `Makefile:14`
- **What:** The `help:` target line at `Makefile:14` reads
  `"make ingest   Run the ingestion pipeline (E11; not yet implemented)"`.
  The target is now implemented and the comment is stale.
- **Why it matters:** An operator who runs `make help` before `make ingest`
  will read "not yet implemented" and either skip the target or question
  whether the diff they just applied actually landed. The stale help text
  is not a functional break but is a trust issue for the runbook workflow.
- **Proposed fix:** Update line 14 to:
  `"make ingest ARGS=\"...\"   Run the bulk-ingest orchestrator (E11; see docs/ops/bulk-ingest-runbook.md)"`
- **Regression guard:** None required; cosmetic.

---

### IS5 — `bulk_download.sh`: no destructive default, but `aria2c` check exits 1 without context on non-Linux

- **Severity:** LOW
- **Source:** infra-safety
- **File:** `ingest/bulk_download.sh:32`
- **What:** When `aria2c` is not found, the script exits 1 with an error
  block. The error block lists `macOS: brew install aria2` and
  `Debian/Ubuntu: apt install aria2`. This is appropriate. The file has the
  executable bit set (`-rwxr-xr-x`), uses `set -euo pipefail`, and does
  not expose sensitive paths, env vars, or system info. No destructive
  defaults exist. The only nit is that the exit-1 on missing `aria2c` fires
  before the operator reads the full workflow instructions — an operator who
  runs this on a machine where `aria2c` is intentionally absent (e.g. a
  read-only CI runner that just wants to check the script) will get a
  hard failure rather than a conditional warning. This is acceptable for an
  operator stub.
- **Why it matters:** No functional risk. The exit-1 on missing `aria2c`
  is a reasonable guard for its stated purpose.
- **Proposed fix:** No change required; acceptable as-is. Optionally
  demote the `aria2c` check to a warning (`exit 0`) so the operator
  instruction block always prints, making the script safe to inspect on any
  machine:
  ```bash
  if ! command -v aria2c >/dev/null 2>&1; then
      echo "WARNING: aria2c not found. Install before running the download." >&2
  fi
  ```
- **Regression guard:** None required; LOW severity.

---

## What was done well

- **Staging-path isolation is architecturally correct.** `DEFAULT_LANCEDB_STAGING_PATH`
  (`var/arxmcp/index/lancedb-staging/`) is entirely separate from the live
  `DEFAULT_LANCEDB_PATH`. The module's docstring explicitly explains why
  — the corpus-version.json invariant (AC2) is preserved at the design level,
  not just at runtime.
- **`--dry-run` is a first-class flag.** `_run_dry` prints the per-paper
  action plan without any network or disk writes. This is exactly the right
  safety valve for a multi-day job, and it exists out of the box.
- **`bulk_download.sh` is intentionally NOT automated.** The 300 GB
  BitTorrent download is a deliberate operator action. The script
  communicates this constraint clearly, exits 0 when `aria2c` is present
  (no accidental download), and the executable bit is set correctly
  (`-rwxr-xr-x`).
- **`_read_paper_ids` validates every id before the loop starts.** Malformed
  entries raise `ValueError` with `{path}:{lineno}` context. An operator
  cannot accidentally kick off a multi-day run against a typo'd corpus list.
- **Non-zero exit on any failures is wired.** `_cli` returns `1` when
  `summary.papers_failed > 0`, so cron mailers and systemd-timer `OnFailure=`
  units catch the signal. The comment at line 507 makes the intent explicit.
- **Parser-failure JSONL is append-only and path-safe.** `_log_parser_failure`
  calls `failures_path.parent.mkdir(parents=True, exist_ok=True)` before
  opening for append. The ingest log does the same. No write will fail
  due to a missing directory.
- **`requires_full_corpus` gating is correctly dual-keyed.** Both the
  pytest marker (`-m requires_full_corpus`) AND the env var
  (`ARXMCP_RUN_FULL_CORPUS_TESTS=1`) must be set. `test_bulk_ingest_sanity.py`
  uses `@pytest.mark.skipif(not _opted_in(), ...)` which enforces this
  correctly — a naive `pytest` run does not trigger the 200K-paper sanity tests.
- **Operator runbook is thorough and covers the entire pipeline.**
  `docs/ops/bulk-ingest-runbook.md` covers all seven steps end-to-end, gives
  expected disk budgets (500 GB total), wall-clock estimates, and recovery
  procedures for disk-full, network drops, ar5iv 503, and LaTeXML hangs.
- **Single-writer constraint is documented and enforced.** The docstring
  at line 44 names the constraint and the architectural rationale. The loop
  is sequential at the write boundary by construction.
- **No sensitive paths or system info leaked in `bulk_download.sh`.**
  The script prints only static instruction text; no `$HOME`, `$USER`,
  `hostname`, or `env` expansions appear anywhere in the output path.

---

## Recommended rectification order

1. **IS1** (HIGH) — Add Python version guard to `ingest:` Makefile target.
   One-liner addition; 5-minute fix. Unblocks every operator on macOS default Python.
2. **IS2** (HIGH) — Wire `resume` parameter in `run_bulk_ingest` loop body.
   Requires identifying the sidecar path helper and adding a ~3-line guard.
   Add unit test to `tests/test_bulk_ingest.py`.
3. **IS4** (MEDIUM) — Update `make help` description for `ingest:` target.
   One-line cosmetic change; zero risk.
4. **IS3** (MEDIUM) — Add word-split hazard comment to Makefile `ingest:` block.
   Documentation-only mitigation for v1; deferred if the rectifier is time-constrained.
5. **IS5** (LOW) — Optionally demote `aria2c` check to a warning.
   Defer unless the operator stub is expected to run in non-interactive contexts.

---

## Rectification status

<!-- Populated by the Phase 4 rectifier after applying fixes. -->

| ID | Status | Fix commit |
|---|---|---|
| IS1 | open | — |
| IS2 | open | — |
| IS3 | open | — |
| IS4 | open | — |
| IS5 | deferred | — |
