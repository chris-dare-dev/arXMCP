# Critique — E01_S01-S03

**Critic:** infra-safety
**Generated:** 2026-05-06T00:00:00Z
**Commit range:** 953709e..c486b26
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- **SHIP-WITH-FIXES.** No CRITICAL or HIGH findings; 3 MEDIUM foot-guns around Python environment hygiene and crash-safety in the 30–90-minute seed-fetch loop; 4 LOW housekeeping items. Core invariants are sound.
- 0 CRITICAL, 0 HIGH, 3 MEDIUM, 4 LOW.
- Highest-risk file: `tools/fetch_seed.py` — write-only-at-end log and no idempotency gate mean a mid-run crash wastes the full politeness budget again on retry.
- Container hygiene (Axis 1), docker-compose (Axis 2), and CI workflow safety (Axis 3) are all N/A — no Dockerfile, no compose file, no `.github/workflows/` were introduced; `infra/` correctly remains a README stub.
- A cross-axis pattern: the `make bootstrap` ambiguity (IS1) and the bare `pytest`/`ruff` invocations (IS2) trace to the same root — no Python environment contract is stated or enforced in the build tooling.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### IS1 — bootstrap silently installs into system Python if no venv active

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** `Makefile:16`
- **What:** `python3 -m pip install -e ".[dev]"` runs against whatever `python3` resolves to on PATH. On macOS with system Python 3.9 the install fails (requires-python ≥3.11 is a guard), but on a machine with system Python 3.11+ it silently pollutes global site-packages with dev dependencies — no warning, no venv check.
- **Why it matters:** A new contributor running `make bootstrap` outside a venv will have ruff and pytest installed at the system level; a later `python3.13 -m pytest` picks up the wrong pytest version, and `make test`'s bare `pytest` may invoke a stale binary from a different environment altogether.
- **Proposed fix:** Add a VIRTUAL_ENV guard before the pip call:
  ```makefile
  bootstrap:
  	@test -n "$$VIRTUAL_ENV" || (echo "ERROR: activate a venv first (python3.11+ -m venv .venv && source .venv/bin/activate)" && exit 1)
  	python3 -m pip install -e ".[dev]"
  	...
  ```
  Alternatively, replace the pip call with `python3 -m pip install --require-virtualenv -e ".[dev]"` (pip ≥22.0 flag).
- **Regression guard:** Add a `make test` step to CI that checks `python --version` is ≥3.11 and `which ruff` is inside `.venv` or a known-managed path.

### IS2 — `make test` uses bare `ruff`/`pytest`, not `python3 -m ruff`/`python3 -m pytest`

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** `Makefile:27-28`
- **What:** The `test` recipe calls `ruff check .` and `pytest` without a `python3 -m` prefix. If PATH contains a stale system-level `ruff` binary (e.g., from an earlier homebrew install), the test run silently uses the wrong tool version and may produce different lint results than the dev session described in the implementation summary (`python3.13 -m pytest`).
- **Why it matters:** The implementation summary explicitly documents that `python3.13 -m pytest` was the validated invocation. Using bare `pytest` in `make test` means the Makefile's "green" verdict is not guaranteed to match the documented validated command; on CI or a fresh machine they can diverge.
- **Proposed fix:**
  ```makefile
  test:
  	python3 -m ruff check .
  	python3 -m pytest
  ```
  This binds ruff and pytest to whichever `python3` is in the environment (consistent with the bootstrap target) and is unambiguous on any platform.
- **Regression guard:** Add a check in CI that `python3 -m ruff --version` matches the installed requirement.

### IS3 — `fetch_seed.py` has no idempotency gate; a crash requires re-fetching all 50 papers

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** `tools/fetch_seed.py:103` (`process_paper`)
- **What:** `process_paper` unconditionally fetches and parses regardless of whether `var/arxmcp/corpus/raw/<paper_id>/` already exists. `write_log` is called only after the full loop completes — a SIGINT, LaTeXML timeout, or disk-full error at paper 45 produces no log and no checkpoint; the only way to recover is a complete 50-paper re-run.
- **Why it matters:** A 50-paper re-run consumes another ~150+ arXiv requests (50 fetches × the politeness budget) and another 30–90 minutes of wall-clock. The politeness contract says "1 request per 3 seconds" — a needless re-run doubles the load on arXiv infrastructure unnecessarily. The acceptance criterion requires ≥45/50 parses; a partial run that left 45 successful parses cannot be verified without a full re-run.
- **Proposed fix:** Add a skip-if-already-parsed check at the top of `process_paper`:
  ```python
  # skip papers already successfully parsed (idempotency)
  out_html = PARSED_DIR / paper_id / "index.html"
  if out_html.exists() and out_html.stat().st_size > MIN_PARSED_HTML_BYTES:
      return Outcome(paper_id=paper_id, success=True, message="already parsed (skipped)", elapsed_s=0.0)
  ```
  Also move `write_log` inside the loop (append or rewrite after each paper) so a partial run leaves a recoverable log.
- **Regression guard:** Add a test in `tests/test_fetch_seed.py` that calls `process_paper` twice on a pre-populated parsed dir and asserts the second call returns `success=True, message~="skipped"` without touching the network.

### IS4 — `ruff>=0.5` and `pytest>=8.0` are lower-bound-only pins

- **Severity:** LOW
- **Source:** infra-safety
- **File:** `pyproject.toml:11-12`
- **What:** Dev dependencies declare only minimum versions (`ruff>=0.5`, `pytest>=8.0`). ruff's lint-rule set changes between minor versions (e.g. new B, UP rules enabled by default), meaning `ruff check .` can start failing after a `pip install --upgrade` without any code change.
- **Why it matters:** Reproducing a clean `make test` run on a different machine or at a later date may behave differently if the installed ruff version differs. This undermines the "53 tests all green" baseline documented in the implementation summary.
- **Proposed fix:** Pin to a compatible range: `ruff>=0.5,<1.0` and `pytest>=8.0,<9.0`. At this project stage that is sufficient. A `uv.lock` or `requirements-dev.txt` snapshot would be stronger; defer to a later milestone.
- **Regression guard:** None required beyond the range pin itself; CI will catch future resolution drift.

### IS5 — `extend-exclude = [".claude"]` hides pre-existing lint issues in skill code

- **Severity:** LOW
- **Source:** infra-safety
- **File:** `pyproject.toml:18`
- **What:** The ruff `extend-exclude` silently excludes the entire `.claude/` tree. The implementation summary documents this is intentional because `.claude/skills/` contains third-party Python that fails ruff (`datetime.UTC`, B007, F541 violations). However, the exclusion is project-wide and permanent — any future application code committed under `.claude/` (e.g., a hook script) would also be silently skipped.
- **Why it matters:** The `.claude/` exclusion is a correctness decision masquerading as a scope decision. If the convention breaks down and real code lands in `.claude/`, lint regressions would be invisible.
- **Proposed fix:** Narrow the exclusion to the specific sub-path that is known to be unclean: `.claude/skills` instead of `.claude`. Or add a comment `# third-party skill code; not application code` so the intention is explicit and auditable.
- **Regression guard:** No test required; the change is purely declarative.

### IS6 — No concurrent-run protection on `seed.log`; two simultaneous runs corrupt it

- **Severity:** LOW
- **Source:** infra-safety
- **File:** `tools/fetch_seed.py:152` (`write_log`)
- **What:** `write_log` uses `Path.write_text()` which is a full overwrite with no advisory lock. Two concurrent `python tools/fetch_seed.py` invocations would race on the same `seed.log` file and produce a truncated or interleaved result.
- **Why it matters:** Unlikely in practice for a dev script, but if a user accidentally launches two terminal windows both running the seed loop (plausible given the 30–90 min duration), the resulting log is silently corrupt and the ≥45/50 gate cannot be evaluated.
- **Proposed fix:** Write log to `seed.log.<pid>` and rename to `seed.log` after the run completes (atomic from the OS's perspective on POSIX). This also fixes the IS3 partial-run problem for the log.
- **Regression guard:** None required for a dev-only script; document the limitation in the script docstring if fix is deferred.

### IS7 — `var/arxmcp/` dirs created with default umask; E02 UID isolation will require permission adjustment

- **Severity:** LOW
- **Source:** infra-safety
- **File:** `Makefile:17-21`
- **What:** `mkdir -p` creates directories with permissions governed by the running user's `umask` (typically 755 or 750). The research synthesis mandates that E02_S02 will run LaTeXML as a separate UID inside a rootless container; that process must write to `var/arxmcp/corpus/parsed/<paper_id>/`. Under default 755 permissions, a different UID cannot write.
- **Why it matters:** E02 will inherit a `var/arxmcp/` tree that silently blocks the subprocess parser unless permissions are explicitly widened. The current commit does not pre-commit to a permissions model, but it also does not leave a comment noting the constraint for E02.
- **Proposed fix:** Add a comment in the Makefile bootstrap target: `# NOTE: E02_S02 LaTeXML container will need write access to corpus/; see 08-security-observability-ops.md § Threat 3`. No chmod required at this milestone.
- **Regression guard:** None required at this milestone; the comment is a forward-reference only.

## What was done well

- **All non-file targets are `.PHONY`-declared.** `help`, `bootstrap`, `test`, `up`, and `ingest` are all listed; no stale-target false-skips are possible.
- **`make bootstrap` is correctly idempotent.** Both `pip install -e` and `mkdir -p` are safe to re-run; repeated bootstraps on the same machine leave the environment in the same state.
- **`make up` and `make ingest` fail with exit 1, not exit 0.** The "not yet implemented" stubs produce a non-zero exit code, so CI or a developer piping `make ingest && something` will not silently proceed past an unimplemented gate. The multi-echo + exit 1 pattern is verified to work correctly in GNU Make (each recipe line is its own sub-shell; exit 1 propagates).
- **`make help` output is stable and informative.** The help text lists all four targets, references the milestone that each will land in (E01_S08 for `up`, E11 for `ingest`), and reminds the user about the `ARXMCP_CONTACT_EMAIL` requirement.
- **`pyproject.toml` `requires-python = ">=3.11"` acts as a safety net.** Even without a venv guard in the Makefile, `python3.9 -m pip install` fails at install time — the project's version floor prevents the worst misconfiguration silently succeeding.
- **No CI workflow files, Dockerfile, or docker-compose were introduced.** The commit correctly defers all container / CI infrastructure to E14; nothing in this diff pre-commits those decisions in a way that will need unwinding.
- **The `infra/README.md` correctly states the intent** (two-service compose target, both binding only to 127.0.0.1) without implementing it; the comment trail for E14 starts here cleanly.
- **`write_log` creates its parent directory via `mkdir(parents=True, exist_ok=True)`** rather than assuming `make bootstrap` has already run. This makes the script more portable.
- **Path-traversal guard in `_safe_extract`** is present and uses `Path.relative_to()` to reject any member that would write outside the extraction target — defense-in-depth for a trusted source, correctly noted as cheap protection against supply-chain swap.
- **`ARXMCP_CONTACT_EMAIL` is never hard-coded.** The bootstrap target warns if the env var is unset; `build_user_agent` raises at runtime if it is missing; no email leaks into committed code.

## Recommended rectification order

1. **IS2** — Change `make test` to `python3 -m ruff check .` and `python3 -m pytest`. One-line change; highest-leverage because it makes the Makefile's green verdict unambiguous and reproducible across Python environments.
2. **IS1** — Add `--require-virtualenv` flag or a VIRTUAL_ENV guard to `make bootstrap`. Prevents polluting system Python on contributor machines; ~3 lines of Makefile.
3. **IS3** — Add skip-if-already-parsed check to `process_paper` and move `write_log` to run after each paper (or at least on KeyboardInterrupt via try/finally). Prevents a 30–90 minute retry cost on crash. ~15 LOC.
4. **IS4** — Narrow `ruff>=0.5` to `ruff>=0.5,<1.0` and `pytest>=8.0` to `pytest>=8.0,<9.0`. One-line change per dependency; low risk.
5. **IS5** — Narrow `extend-exclude = [".claude"]` to `extend-exclude = [".claude/skills"]`. One-line change; tightens lint scope without affecting current behavior.
6. **IS6** — Add a docstring note about the concurrent-run limitation in `fetch_seed.py`. No code change required at this milestone; IS6 is a known acceptable risk for a dev script.
7. **IS7** — Add a comment in the Makefile bootstrap target noting the E02 UID/permissions requirement. One line; forward-reference only.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate. -->
