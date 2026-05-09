# E05_S03 Infra-Safety Critique — `make eval` target

**Scope.** Diff `b2c3b6a..4449a1d Makefile`. Adds a single new target
`eval`, updates `.PHONY`, adds a `help:` row. No Dockerfile / compose /
CI workflow changes in this commit.

**Axes evaluated.**

| Axis | Status |
|---|---|
| Container hygiene | N/A — no container changes in this commit. |
| docker-compose correctness | N/A — no compose file in repo. |
| CI workflow safety | N/A — no `.github/workflows/` changes in this commit. |
| Makefile / build script | **Reviewed below.** |

## What was done well

- **Python version guard reuses the canonical pattern.** The new
  `eval` target's preflight (`Makefile:51-53`) is a verbatim mirror of
  the `test` target's guard (`Makefile:42-44`) — same `MIN_PY_MINOR`
  variable, same `$(PYTHON) -c` inline assert, same recovery hint
  format (`Try: make eval PYTHON=python3.$(MIN_PY_MINOR)`). No
  hardcoded `python3` anywhere; the override surface is identical.
- **`.PHONY` updated.** Line 1 lists `eval` alongside the other phony
  targets — no risk of a future `eval/` directory shadowing the
  target.
- **`help:` updated in the same commit.** Line 12 adds the row, so
  `make help` discovery stays in sync with the actual target list.
  Mirrors the existing one-line-per-target convention.
- **Pytest invocation is a single shell command.** Line 55 is one
  line, no `&&` chain, so pytest's exit code is the recipe's exit
  code. A non-zero from pytest (threshold failure, collection error)
  propagates cleanly to `make`.
- **No `sudo`, no `rm`, no destructive defaults.** The recipe only
  invokes Python.
- **No cross-target dependencies.** `eval` declares no prerequisites,
  so `-jN` parallel invocations cannot deadlock or race against
  `bootstrap` / `test`. Each target stands alone.
- **The `@` prefix is on the version-guard line only.** Line 51 is
  silenced (preflight noise is not useful); line 55 echoes the pytest
  command (operator can copy-paste it). Same pattern as `test`.
- **Inline header comment documents the SKIP-is-not-a-pass
  invariant.** Lines 49-52 of the Makefile explicitly warn that `1
  skipped` is not the same as `1 passed` for promotion purposes —
  this is a defense-in-depth duplicate of the same warning in
  `TIER-GATES.md`, which is appropriate because the operator who runs
  `make eval` may never read `TIER-GATES.md`.

## Findings

### IS1 — `make eval` is a strict subset of `make test` (LOW)

**Where.** `Makefile:55` (`pytest tests/eval/test_retrieval_quality.py
--ndcg-min=0.70`) overlaps with `Makefile:46` (`pytest` — runs the
full suite, which includes `tests/eval/test_retrieval_quality.py`).

**Observation.** Running `make test` already executes
`test_retrieval_quality` (with the default `--ndcg-min=0.70` from
`tests/conftest.py:37`). `make eval` re-runs the same single test.
This is intentional per the brief — `make eval` is the named gate
even though `make test` covers it transitively — but it does mean a
CI matrix that fans out `make test` and `make eval` in parallel will
do the same retrieval pass twice.

**Severity.** LOW. Not wrong, just redundant. The target's purpose is
operator ergonomics (one named command for the Tier-0 gate), not
incremental test coverage. No fix recommended.

### IS2 — `make eval` does not depend on `bootstrap`, so cold-start writes can target a missing parent (LOW, no real impact)

**Where.** `Makefile:53` declares no prereqs, so `make eval` on a
fresh checkout will run before `bootstrap` has created
`var/arxmcp/ops/`.

**Observation.** I traced the test path: in the cold-start cell
(`tests/eval/test_retrieval_quality.py:159-174`), the test
short-circuits via `pytest.skip` before any output directory is
touched. In the RUN cell, `score_and_write` calls `output_dir.mkdir(
parents=True, exist_ok=True)` (`tests/eval/test_retrieval_quality.py:300`)
and the atomic-write helper repeats the `mkdir` for the parent
(`tests/eval/test_retrieval_quality.py:351`). So `var/arxmcp/ops/eval/`
is created on demand by the test, not by `bootstrap`. No
missing-directory failure mode exists.

**Severity.** LOW. Documented for completeness — this was an explicit
question in the critique brief and the answer is "the test handles
it." No Makefile change needed.

### IS3 — Side effects in working tree are real but reasonable for a Make target (LOW)

**Where.** `tests/eval/test_retrieval_quality.py:301-302` writes
`var/arxmcp/ops/eval/results-<v>.jsonl` and `aggregate-<v>.json` on
the RUN cell.

**Observation.** A `make`-level expectation is that targets either
build files in `var/` (acceptable) or are "check" targets with no
side effects (typical for `test`). `make eval` straddles the line: on
cold-start it has no side effects (test SKIPs), on a hot RUN it
writes two files under `var/arxmcp/ops/eval/`. The write path is
under the documented `var/` tree (created by `bootstrap`), is atomic
(PID + UUID-suffix tmp + `os.replace`,
`tests/eval/test_retrieval_quality.py:342-360`), and is not under
git. The file naming embeds `corpus_version` so re-runs at the same
version overwrite cleanly without orphan accumulation. This is the
documented drift-detection baseline for E11_S04 — the side effect IS
the point.

**Severity.** LOW. Acceptable. The Makefile recipe could mention the
side effect via an inline comment for discoverability, but the
existing comment already directs the reader to `TIER-GATES.md`, so
this is style.

### IS4 — `make eval` is not idempotent across corpus versions (LOW)

**Where.** `tests/eval/test_retrieval_quality.py:301-302` —
filename embeds `corpus_version`, so each new version creates a new
file pair without pruning the old.

**Observation.** Re-running `make eval` at the same `corpus_version`
overwrites the existing files (idempotent in the strict sense). But
running `make eval` after re-ingesting at a new `corpus_version`
leaves the old `results-<old-v>.jsonl` and `aggregate-<old-v>.json`
in place — the directory grows monotonically. This is intentional
per E11_S04's drift-detection plan (the historical aggregates are
the baseline), so it's not a bug. Worth flagging only because a
naive operator might expect `make eval` to clean stale files.

**Severity.** LOW. Documented behavior, not a defect. No Makefile
change recommended.

## Summary

The Makefile diff is small and disciplined. The new `eval` target is
a near-clone of the `test` target's structure (same Python guard,
same one-shot pytest invocation, same `@`-prefix discipline) and
introduces no new risk vectors. The four findings are all LOW —
documentation polish or "I checked this and it's fine" notes
prompted by the critique brief's explicit questions. No CRITICAL,
HIGH, or MEDIUM defects.

The cross-target safety surface (`-jN`, no prereqs, no shared
mutable state) is clean. The pytest exit code propagates correctly.
The Python version guard works the same way it does for `make test`.
The output side effects are bounded to the `var/` tree, atomic, and
correctly versioned for the downstream drift-detection consumer.

**Verdict.** Ship as-is.
