# Critique (merged) — E01_S01-S03

**Critics:** adversary (Opus), infra-safety (Sonnet)
**Generated:** 2026-05-06
**Commit range:** `953709e..c486b26`
**Verdict:** SHIP-WITH-FIXES

## Executive summary (orchestrator's voice)

- **Verdict SHIP-WITH-FIXES.** Both critics independently arrive there. No CRITICAL findings — the offline scaffolding, math-fidelity stance (no PyPDF, MathML guard, `--javascript=mathjax` deliberately omitted), no-fork policy, tier sequencing, and SSRF posture (`export.arxiv.org`-pinned URLs + `paper_id` regex) are all sound.
- **Combined finding counts:** 0 CRITICAL, 4 HIGH, 7 MEDIUM, 7 LOW (18 total).
  - Adversary: 0 / 4 / 4 / 3 (F1–F11)
  - Infra-safety: 0 / 0 / 3 / 4 (IS1–IS7)
- **Highest-risk file across both critics:** `tools/fetch_seed.py`. Adversary flags `:107` (skips `find_main_tex` → silent math loss on multi-tex submissions) and `:117-128` (timeout/tarball exceptions escape the loop, killing the run mid-corpus). Infra-safety flags `:103` (no idempotency on crash → 30–90 min wasted on a re-run after any failure). All three converge on the same hot path.
- **Cross-axis pattern #1 — "no Python environment contract."** F4 (adversary, HIGH), IS1 (infra-safety, MEDIUM), and IS2 (infra-safety, MEDIUM) all stem from the same root: `make test`'s bare `pytest` plus `make bootstrap`'s ungated `pip install` plus loose dev pins (IS4) means the test suite's "green" verdict is not reproducible across the development environments the project will encounter.
- **Cross-axis pattern #2 — "loop resilience under partial failure."** F2 (adversary, HIGH — exceptions escape) and IS3 (infra-safety, MEDIUM — no idempotency / no incremental log) are two faces of the same defect class. Fixing them together is cheaper than fixing in isolation.
- **Cross-axis pattern #3 — "untested security-critical surfaces."** F5 (politeness contract loop), F6 (`_safe_extract`, `parse_with_latexml`), and the implementation summary's own admission that network-and-binary tests are deferred mean the four threat-model entries the synthesis quoted (Threat 1 path traversal, Threat 3 LaTeXML timeout, Threat 7 response size cap — F8, plus politeness contract) are scaffolded in code but unverified by tests.
- **E01_S03 acceptance is partially met.** F3 (HIGH) records that `tools/seed-papers.txt` ships with one ID rather than the brief's required 50. The implementation summary frames this as a deliberate Phase 4 gate (avoiding fabricated arXiv IDs); the orchestrator should escalate this to the user during Phase 4 rather than auto-populating.
- **What both critics independently affirmed:** no PyPDF/pymupdf/pdfplumber imports, no `--javascript=mathjax`, URLs pinned to `export.arxiv.org`, `_safe_extract` defense-in-depth, `ARXMCP_CONTACT_EMAIL` never hard-coded, `LATEXML_TIMEOUT_SECONDS=300` matching Threat 3, no Tier-1 over-reach, three logical commits in dependency order matching synthesis §8.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Cross-critic agreement

- **`tools/fetch_seed.py:103-107** — flagged by adversary, infra-safety (findings: IS3, F1; severities: HIGH, MEDIUM)
- **`Makefile:26-27** — flagged by adversary, infra-safety (findings: F4, IS2; severities: HIGH, MEDIUM)

<!-- end:cross-critic-agreement -->

## Findings

### F1 — process_paper bypasses find_main_tex; picks any .tex via rglob

- **Severity:** HIGH
- **Source:** adversary
- **File:** `tools/fetch_seed.py:107`
- **What:** `process_paper` does `main_tex = next(raw_paper.rglob("*.tex"), None)` and feeds whatever the OS yields first to LaTeXML. The `find_main_tex` heuristic in `tools/arxiv_fetch.py:166-193` (prefer `<paper_id>.tex`, unique-`.tex`, `\documentclass`-search, then alphabetical fallback) is unused on the 50-paper path even though `fetch_one_paper.py:39` already returns `fetch.main_tex` from `fetch_eprint`.
- **Why it matters:** multi-tex submissions are common (a main file + `appendix.tex`/`macros.tex`/`refs.tex`). On those, `rglob` order is not guaranteed to return the main file; LaTeXML on `appendix.tex` produces a tiny HTML with no `<math>`, which the parse-success detector then correctly classifies as failure. The acceptance gate (≥45/50) tilts toward false negatives precisely on the papers the heuristic was written to handle. Directly undermines "math fidelity over coverage."
- **Proposed fix:** call `fetch_eprint` once and use `fetch_outcome.main_tex` (the `FetchResult` already carries it). Refactor `fetch_with_backoff` to return the `FetchResult` so `process_paper` can read `.main_tex`.
- **Regression guard:** unit test that builds a fake raw_dir with `appendix.tex` (alphabetically first) and `<paper_id>.tex` (matching paper_id) and asserts `process_paper` picks the latter — mock `fetch_with_backoff` to succeed and assert on the path passed to a mocked `parse_with_latexml`.

### F2 — LaTeXML timeout + corrupt-tar exceptions kill the seed loop

- **Severity:** HIGH
- **Source:** adversary
- **File:** `tools/fetch_seed.py:117-128`, `tools/fetch_seed.py:95-97`
- **What:** `process_paper` wraps `parse_with_latexml` in `except (RuntimeError, OSError)`, but `subprocess.run(..., timeout=)` raises `subprocess.TimeoutExpired`, whose MRO is `(TimeoutExpired, SubprocessError, Exception)` — neither `RuntimeError` nor `OSError`. Same gap in `fetch_with_backoff`'s `except (OSError, RuntimeError, ValueError)`: `tarfile.ReadError`, `tarfile.CompressionError`, `tarfile.HeaderError` derive from `tarfile.TarError -> Exception`, not `OSError`.
- **Why it matters:** Threat 3 in `08-security-observability-ops.md` mandates a 5-minute timeout precisely so a hostile or malformed `.tex` cannot freeze ingestion. The timeout is set (`LATEXML_TIMEOUT_SECONDS = 300`) but when it fires, the unhandled exception escapes `process_paper`, escapes the `for` loop in `main()`, and the remaining papers are not fetched. The 50-paper loop's "fail open, log, continue" invariant is broken on exactly the failure modes the timeout exists to handle.
- **Proposed fix:** broaden both `except` tuples to `(RuntimeError, OSError, subprocess.TimeoutExpired, tarfile.TarError, gzip.BadGzipFile)`, or catch `Exception` at this single boundary. Log the offending paper to `seed.log` with status `fail` and a clear message and `continue`.
- **Regression guard:** unit test `process_paper` with `parse_with_latexml` monkeypatched to raise `subprocess.TimeoutExpired(cmd=[...], timeout=300)`; assert the Outcome is `success=False, message="timeout"` and the loop does not raise.

### F3 — seed-papers.txt has 1 ID, not the 50 the brief requires

- **Severity:** HIGH
- **Source:** adversary
- **File:** `tools/seed-papers.txt:1-15`
- **What:** the file contains a single arXiv ID (`2307.01156`, declared as the S02 smoke-test target). E01_S03 acceptance criterion #1 says "tools/seed-papers.txt lists 50 arXiv IDs from category math.AG"; that's not satisfied at HEAD.
- **Why it matters:** without 50 IDs, the entire S03 fetch loop cannot be exercised. The ≥45/50 parse-success gate, the 30–90 minute wall-clock figure, and the failure log all depend on the list being populated. The implementation summary frames this as a deliberate Phase-4 gate ("avoiding fabricated arXiv IDs"), which is a defensible safety stance — but the milestone ships incomplete against its own stated acceptance criterion.
- **Proposed fix:** Phase 4 runs `tools/curate_seed.py --max-results 200`, the implementer eyeballs the candidates, picks 50, and commits them. If the user declines, mark E01_S03 partially-met and surface the deviation in the milestone exit report.
- **Regression guard:** add a startup-time check in `fetch_seed.py` that errors out (not just warns) when `len(paper_ids) != EXPECTED_SEED_COUNT` with a `--allow-undersized` opt-out; the next time someone runs the script with a partial list it fails loud.

### F4 — `make test` returns non-zero on the dev machine's default Python

- **Severity:** HIGH
- **Source:** adversary
- **File:** `Makefile:26-28`, `tools/curate_seed.py:37`
- **What:** `make test` invokes plain `pytest`, which on the current dev machine resolves to `/usr/bin/python3` (3.9.6). `tools/curate_seed.py` does `from datetime import UTC, datetime` (3.11+) and the test collection fails with `ImportError: cannot import name 'UTC' from 'datetime'`. The implementation summary documents the workaround as "use `python3.13`" — but the brief's E01_S01 criterion says `make help` must list `bootstrap`, `test`, `up`, `ingest`, and the test target needs to actually work.
- **Why it matters:** any dev who clones the repo and runs `make bootstrap && make test` on a machine where `python3` < 3.11 hits an opaque ImportError instead of green tests.
- **Proposed fix:** declare `PYTHON ?= python3` in the Makefile and use `$(PYTHON) -m pytest` / `$(PYTHON) -m ruff check .` so a user can override with `make test PYTHON=python3.13`. Pair with a Python-version assert at the top of the test target. (See also IS1 + IS2 below — same root cause.)
- **Regression guard:** the bootstrap target's `pip install -e ".[dev]"` should already fail on Python <3.11 due to `requires-python`; assert that explicitly in a smoke check inside `bootstrap`, not just `test`.

### IS1 — bootstrap silently installs into system Python if no venv active

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** `Makefile:16`
- **What:** `python3 -m pip install -e ".[dev]"` runs against whatever `python3` resolves to on PATH. On a machine with system Python 3.11+ it silently pollutes global site-packages with dev dependencies — no warning, no venv check.
- **Why it matters:** A new contributor running `make bootstrap` outside a venv will have ruff and pytest installed at the system level; a later `python3.13 -m pytest` picks up the wrong pytest version, and `make test`'s bare `pytest` may invoke a stale binary from a different environment altogether.
- **Proposed fix:** Add a VIRTUAL_ENV guard before the pip call, or replace the pip call with `python3 -m pip install --require-virtualenv -e ".[dev]"` (pip ≥22.0 flag).
- **Regression guard:** none required beyond the guard itself; the guard refuses to proceed without a venv.

### IS2 — `make test` uses bare `ruff`/`pytest`, not `python3 -m ruff`/`python3 -m pytest`

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** `Makefile:27-28`
- **What:** The `test` recipe calls `ruff check .` and `pytest` without a `python3 -m` prefix. If PATH contains a stale system-level `ruff` binary (e.g., from an earlier homebrew install), the test run silently uses the wrong tool version.
- **Why it matters:** The implementation summary explicitly documents that `python3.13 -m pytest` was the validated invocation. Using bare `pytest` in `make test` means the Makefile's "green" verdict is not guaranteed to match the documented validated command; on CI or a fresh machine they can diverge.
- **Proposed fix:** `python3 -m ruff check .` and `python3 -m pytest`, ideally via the `$(PYTHON)` variable from F4's fix.
- **Regression guard:** none required beyond the change itself.

### IS3 — `fetch_seed.py` has no idempotency gate; a crash requires re-fetching all 50 papers

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** `tools/fetch_seed.py:103` (`process_paper`)
- **What:** `process_paper` unconditionally fetches and parses regardless of whether `var/arxmcp/corpus/raw/<paper_id>/` already exists. `write_log` is called only after the full loop completes — a SIGINT, LaTeXML timeout (see F2), or disk-full error at paper 45 produces no log and no checkpoint; the only way to recover is a complete 50-paper re-run.
- **Why it matters:** A 50-paper re-run consumes another ~150+ arXiv requests and another 30–90 minutes of wall-clock. Doubles load on arXiv infrastructure unnecessarily. The acceptance criterion requires ≥45/50 parses; a partial run that left 45 successful parses cannot be verified without a full re-run.
- **Proposed fix:** Add a skip-if-already-parsed check at the top of `process_paper`. Move `write_log` inside the loop (append after each paper, or rewrite incrementally) so a partial run leaves a recoverable log. Pair with F2's exception broadening for full crash-safety.
- **Regression guard:** test `process_paper` twice on a pre-populated parsed dir; assert the second call returns `success=True, message~="skipped"` without touching the network.

### F5 — Politeness contract (3-s sleep, 503 backoff) is untested

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_arxiv_fetch.py`, `tests/test_fetch_seed.py`
- **What:** the brief's politeness contract has three load-bearing pieces — (a) 3 s sleep between requests, (b) 503 backoff with Retry-After, (c) `arXMCP/0.1 (mailto:...)` UA on every request. The test suite covers `parse_retry_after` and `build_user_agent` (pure functions) but NOT the loop. The retry path of `fetch_with_backoff` is uncovered, and the inter-request sleep at `tools/fetch_seed.py:174-175` is uncovered.
- **Why it matters:** the politeness contract is the only thing standing between this milestone and an arXiv IP ban. Untested contract, untested retry, untested header-on-every-request.
- **Proposed fix:** (i) fake-clock test for `fetch_with_backoff` mocking `urlopen` to raise `HTTPError(code=503, headers={"Retry-After": "60"})` once then succeed; assert `time.sleep` called with 60 (and not less than the floor); (ii) test `main` against a 3-paper seed file with mocked `process_paper` and assert `time.sleep(POLITENESS_SLEEP_SECONDS)` was called exactly twice (between, not before/after); (iii) assert every mocked `urlopen` request carried `User-Agent` starting with `arXMCP/0.1 (mailto:`.
- **Regression guard:** the tests above ARE the regression guard.

### F6 — `_safe_extract` (Threat 1) and `parse_with_latexml` are untested

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/arxiv_fetch.py:250-266`, `tools/arxiv_fetch.py:269-305`
- **What:** the path-traversal guard (Threat 1 mitigation per `08-security-observability-ops.md`) and the LaTeXML invocation (Threat 3) have no tests. Someone removes `filter="data"` from `tar.extractall`, or replaces `.resolve()` with `.absolute()` (which doesn't follow `..`), and the suite stays green.
- **Why it matters:** Threats 1 and 3 are the named threat-model entries the synthesis quoted. Once they're untested, the only signal that they still work comes from the next critic round.
- **Proposed fix:** test that builds an in-memory tar with member `../etc/passwd`; asserts `_safe_extract` raises `RuntimeError` AND no file was created outside `dest`. Test that monkeypatches `shutil.which` to return `None` and asserts `parse_with_latexml` raises a clear `RuntimeError` mentioning `latexml`. Test that monkeypatches `subprocess.run` to return `returncode=1` and asserts `parse_with_latexml` returns a non-success `ParseResult`.
- **Regression guard:** the tests above.

### F7 — politeness_sleep helper is dead code

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/arxiv_fetch.py:308-312`
- **What:** `politeness_sleep` is exported but never called by any caller (`fetch_one_paper.py`, `fetch_seed.py`, `curate_seed.py` all sleep inline). Confirmed by `grep -rn politeness_sleep tools/` — only the definition matches.
- **Why it matters:** dead helper invites future confusion ("was the loop supposed to call this?"). It also implies a politeness abstraction the codebase doesn't actually use.
- **Proposed fix:** either delete or refactor `fetch_seed.py:174-175` to call it (gives F5's testable seam). Prefer the refactor — one canonical home for inter-request spacing.
- **Regression guard:** F5's politeness loop test exercises this path post-refactor.

### F8 — fetch_eprint does not bound response size; Threat 7 latent

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/arxiv_fetch.py:218-220`
- **What:** `body = resp.read()` reads the entire response into memory with no upper bound. `08-security-observability-ops.md` Threat 7 explicitly calls out "Content-length sanity checks (a single paper > 100 MB source is suspicious)" as documented mitigation. Not implemented.
- **Why it matters:** a malicious or compromised arxiv mirror could serve a multi-GB response and OOM the dev machine — exactly the local-first threat model.
- **Proposed fix:** read in chunks with a hard cap (e.g. 200 MB); raise `RuntimeError("response too large")` past the cap. Or check `Content-Length` header and refuse before `read()`.
- **Regression guard:** test mocking `urlopen` to return a response whose `.read()` raises after N bytes / whose `Content-Length` exceeds the cap; assert `fetch_eprint` raises a clear error.

### F9 — re-running fetch_eprint mixes stale and new files in raw_dir

- **Severity:** LOW
- **Source:** adversary
- **File:** `tools/arxiv_fetch.py:209-247`
- **What:** `raw_dir.mkdir(parents=True, exist_ok=True)` and a subsequent `tar.extractall` / gzip write into the same per-paper directory without first clearing it. If a prior run extracted `appendix.tex` + `main.tex` and the next run downloads a single-file gzip variant that only ships `<paper_id>.tex`, the stale `appendix.tex` lingers and `find_main_tex` may pick it via the `\documentclass` heuristic.
- **Why it matters:** edge case in dev, but makes the seed corpus non-idempotent in a way that could confuse a re-run during E02 experiments.
- **Proposed fix:** at the top of `fetch_eprint`, after validation but before `mkdir`, do `if raw_dir.exists(): shutil.rmtree(raw_dir)`. Or extract into a tempdir and rename atomically.
- **Regression guard:** fixture-based test that pre-populates `raw_dir` with a stub file and asserts it's gone after a successful fetch.

### F10 — `*.log` blanket-ignore in .gitignore is broader than needed

- **Severity:** LOW
- **Source:** adversary
- **File:** `.gitignore:27`
- **What:** the gitignore line `*.log` matches every `*.log` file anywhere in the repo, not just under `var/arxmcp/`.
- **Why it matters:** if E14's docker-compose ever ships a sample `*.log` fixture, it would be silently un-trackable.
- **Proposed fix:** delete `*.log` (the `/var/arxmcp/` rule above already covers `seed.log`), or scope to `/var/arxmcp/**/*.log`.
- **Regression guard:** none; pure config.

### F11 — `urllib.error` imported but unused in arxiv_fetch.py

- **Severity:** LOW
- **Source:** adversary
- **File:** `tools/arxiv_fetch.py:19`
- **What:** `import urllib.error` is at the top of `arxiv_fetch.py` but the symbol is never referenced.
- **Why it matters:** dead import; tiny cognitive cost.
- **Proposed fix:** drop the line.
- **Regression guard:** none.

### IS4 — `ruff>=0.5` and `pytest>=8.0` are lower-bound-only pins

- **Severity:** LOW
- **Source:** infra-safety
- **File:** `pyproject.toml:11-12`
- **What:** Dev dependencies declare only minimum versions. ruff's lint-rule set changes between minor versions; `ruff check .` can start failing after a `pip install --upgrade` without any code change.
- **Why it matters:** Reproducing a clean `make test` run on a different machine or at a later date may behave differently if the installed ruff version differs.
- **Proposed fix:** Pin to a compatible range: `ruff>=0.5,<1.0` and `pytest>=8.0,<9.0`. A `uv.lock` or `requirements-dev.txt` snapshot would be stronger; defer to a later milestone.
- **Regression guard:** None required beyond the range pin itself.

### IS5 — `extend-exclude = [".claude"]` hides pre-existing lint issues in skill code

- **Severity:** LOW
- **Source:** infra-safety
- **File:** `pyproject.toml:18`
- **What:** The ruff `extend-exclude` silently excludes the entire `.claude/` tree. The implementation summary documents this is intentional, but the exclusion is project-wide and permanent — any future application code under `.claude/` would also be silently skipped.
- **Why it matters:** A correctness decision masquerading as a scope decision. If real code lands under `.claude/`, lint regressions would be invisible.
- **Proposed fix:** Narrow the exclusion to `.claude/skills`, or add a comment `# third-party skill code; not application code`.
- **Regression guard:** none required.

### IS6 — No concurrent-run protection on `seed.log`

- **Severity:** LOW
- **Source:** infra-safety
- **File:** `tools/fetch_seed.py:152` (`write_log`)
- **What:** `write_log` uses `Path.write_text()` — full overwrite with no advisory lock. Two concurrent runs would race on the same `seed.log` and produce a truncated or interleaved result.
- **Why it matters:** Unlikely in practice for a dev script; if a user accidentally launches two terminal windows both running the seed loop, log is silently corrupt.
- **Proposed fix:** Write to `seed.log.<pid>` and rename to `seed.log` after the run completes (atomic on POSIX). Also fixes IS3's partial-run problem for the log.
- **Regression guard:** none required for a dev-only script; document in the script docstring if fix is deferred.

### IS7 — `var/arxmcp/` dirs created with default umask; E02 UID isolation will need adjustment

- **Severity:** LOW
- **Source:** infra-safety
- **File:** `Makefile:17-21`
- **What:** `mkdir -p` creates directories with permissions governed by the running user's `umask` (typically 755 or 750). E02_S02 will run LaTeXML as a separate UID; under default 755 a different UID cannot write to `corpus/parsed/`.
- **Why it matters:** E02 will inherit a `var/arxmcp/` tree that silently blocks the subprocess parser unless permissions are explicitly widened. Current commit doesn't pre-commit to a permissions model, but also doesn't leave a comment noting the constraint.
- **Proposed fix:** Add a comment in the Makefile bootstrap target: `# NOTE: E02_S02 LaTeXML container will need write access to corpus/; see 08-security-observability-ops.md § Threat 3`.
- **Regression guard:** none required; the comment is a forward-reference only.

## What was done well

(Verbatim union from both critics.)

- The four-part parse-success rule with the explicit silent-math-loss guard at `tools/arxiv_fetch.py:113-163` is exactly what the synthesis (D4) called for; `test_silent_math_loss_caught` correctly anchors the failure mode.
- `--javascript=mathjax` is deliberately NOT passed to `latexmlc` — math fidelity stays on static MathML, no CDN dependency.
- No PyPDF / pymupdf / pdfplumber imports anywhere; the parser-chain ban from `04-parsing-and-chunking.md` is honored.
- URLs are pinned to `export.arxiv.org` (synthesis D2) at module scope, so SSRF via `paper_id` is blocked before formatting via `validate_paper_id`.
- `_safe_extract` uses `.resolve()` + `.relative_to()` AND `tar.extractall(filter="data")` — defense in depth catches absolute-path / `..` traversals.
- `LATEXML_TIMEOUT_SECONDS = 300` matches Threat 3's stated 5-minute hard cap.
- `build_user_agent` raises if `ARXMCP_CONTACT_EMAIL` is unset (no anonymous traffic).
- The seed-list reader correctly handles blanks, leading-whitespace comments, and trailing whitespace — tests exercise all four edge cases.
- No tier-1 over-reach: no ar5iv lookup, no theorem+proof pairing, no hierarchical chunker.
- Commit shape matches synthesis §8: three logical commits, one per sub-issue, in dependency order.
- All non-file Makefile targets are `.PHONY`-declared.
- `make bootstrap` is correctly idempotent (both `pip install -e` and `mkdir -p` safe to re-run).
- `make up` and `make ingest` fail with exit 1 (not 0) — CI / piped commands won't silently proceed past unimplemented gates.
- `pyproject.toml` `requires-python = ">=3.11"` acts as a safety net at install time.
- No CI workflows, Dockerfile, or compose files were introduced — correctly defers to E14.
- `infra/README.md` states intent (two-service compose target, `127.0.0.1`-only) without implementing.
- `write_log` creates its parent directory rather than assuming `make bootstrap` ran.

## Recommended rectification order (orchestrator's voice)

Cross-critic agreement bundles drive the ordering: F4+IS1+IS2 (Python contract) and F2+IS3 (loop resilience) are the same defects from two angles. Fixing each bundle as one PR-shaped change is cheaper than splitting.

1. **F2 + IS3** (loop resilience) — broaden the exception tuples, move `write_log` inside the loop, and add the skip-if-already-parsed gate. Together they are the difference between a one-shot run and a re-runnable script. ~30 LOC + 2 tests.
2. **F1** (process_paper bypasses find_main_tex) — refactor `fetch_with_backoff` to return `FetchResult` so `process_paper` reads `.main_tex`. ~10 LOC + 1 test.
3. **F4 + IS1 + IS2** (Python environment contract) — declare `PYTHON ?= python3` in Makefile, gate `bootstrap` on `VIRTUAL_ENV` (or `--require-virtualenv`), use `$(PYTHON) -m ...` in `test`, add a Python-version assertion. ~10 LOC of Makefile.
4. **F3** (50 IDs missing) — escalate to user. Phase 4 should NOT auto-populate the file from training knowledge. Either run `curate_seed.py` after user authorization (network external write) and commit the human-reviewed 50, OR explicitly mark E01_S03 partially-met in the Phase 4 commit. Add the loud-fail `--allow-undersized` gate either way.
5. **F5 + F6** (politeness + threat-model tests) — paired since they share infra (mocked `urlopen`, monkeypatched `time.sleep`). ~80 LOC of new tests, no production code change.
6. **F7** (delete or wire up `politeness_sleep`) — pair with F5's refactor.
7. **F8** (response size cap) — defense in depth; one place to enforce, ~10 LOC.
8. **IS4** (loose pins) — narrow to `<1.0` / `<9.0` upper bounds.
9. **IS5** (narrow ruff exclude) — `.claude/skills` instead of `.claude`.
10. **IS7** (E02 UID comment in Makefile) — one comment line.
11. **F9** (raw_dir not cleared on rerun) — opportunistic.
12. **F10** (`*.log` gitignore) — opportunistic.
13. **F11** (unused import) — opportunistic.
14. **IS6** (concurrent-run lock) — defer with docstring note (LOW, dev-only script).

## Rectification status (filled by Phase 4)

Re-verify gate: 0 of 4 HIGH findings invalidated (0% invalidation rate; well below the 40% heuristic). Both critic prompts performed cleanly on this run.

**Fixed in the rect commit:**

- F1 — fixed: `tools/fetch_seed.py::process_paper` now reads `FetchResult.main_tex` (with `find_main_tex` fallback). Regression: `tests/test_rectifications.py::TestF1MainTexSelection` (2 tests).
- F2 — fixed: `PER_PAPER_FAILURE_EXCEPTIONS` tuple in `tools/fetch_seed.py` now catches `subprocess.TimeoutExpired`, `tarfile.TarError`, `gzip.BadGzipFile`. Regression: `tests/test_rectifications.py::TestF2ExceptionEscape` (2 tests).
- F4 — fixed: `Makefile` declares `PYTHON ?= python3`, asserts Python ≥3.11, uses `$(PYTHON) -m ruff/pytest`. `make test PYTHON=python3.13` verified green.
- F5 — fixed: politeness contract loop now tested. Regression: `tests/test_rectifications.py::TestF5PolitenessContract` (2 tests — Retry-After honored, User-Agent on every request).
- F6 — fixed: `_safe_extract` and `parse_with_latexml` now tested. Regression: `tests/test_rectifications.py::TestF6SafeExtract` (2 tests) + `TestF6ParseWithLatexml` (2 tests).
- F7 — fixed: `tools/fetch_seed.py` now calls `politeness_sleep()` instead of inline `time.sleep`; helper is no longer dead code.
- F8 — fixed: `tools/arxiv_fetch.py::fetch_eprint` enforces `MAX_RESPONSE_BYTES=200MB` cap (Content-Length check + read cap). Regression: `tests/test_rectifications.py::TestF8ResponseSizeCap` (2 tests).
- IS1 — fixed: `make bootstrap` requires `VIRTUAL_ENV` and uses `pip install --require-virtualenv`.
- IS2 — fixed: `make test` invokes `$(PYTHON) -m ruff` / `$(PYTHON) -m pytest` (paired with F4).
- IS3 — fixed: `process_paper` honors `already_parsed()` idempotency gate; `write_log` runs after each paper (incremental persistence + KeyboardInterrupt handling). Regression: `tests/test_rectifications.py::TestIS3IdempotencyGate` (2 tests).
- IS7 — fixed: forward-reference comment added to `Makefile` bootstrap target citing `08-security-observability-ops.md` § Threat 3.

**Escalated to user (Phase 4 external-write boundary):**

- F3 — partially addressed in code: `tools/fetch_seed.py` now exits 2 on undersized seed lists with a `--allow-undersized` opt-out (regression: `TestF3UndersizedSeedList`, 2 tests). The actual 50-ID population requires running `tools/curate_seed.py` (an arXiv API external write) followed by human review of candidates. The orchestrator surfaces this to the user in Phase 4 rather than auto-populating fabricated IDs.

**Deferred (LOW — recorded for future):**

- F9 — `raw_dir` not cleared between fetches. Edge case; defer.
- F10 — `*.log` gitignore is broader than needed. Pure config; defer.
- F11 — `urllib.error` unused import in `arxiv_fetch.py`. Cosmetic; defer.
- IS4 — `ruff>=0.5` / `pytest>=8.0` are lower-bound-only pins. Defer until a uv.lock-style snapshot lands.
- IS5 — `extend-exclude = [".claude"]` could be narrowed to `.claude/skills`. Defer.
- IS6 — no concurrent-run lock on `seed.log`. Documented as known limitation in script docstring; defer.
