# Critique — ingest-robustness-m1 — milestone-infra-safety-critic

**Critic:** milestone-infra-safety-critic
**Commit range:** 23b8628..b2352c0
**Diff stats:** 18 files, 975 LOC (+953/−22); infra scope: Makefile (+7/−5)
**Critique format version:** 1.0

## Verdict

DO-NOT-SHIP. The new `make init` recipe embeds a literal `$(if $(strip ...))` inside an `@#` recipe-line comment; GNU make expands `$(...)` on recipe lines even in shell comments, and that expansion is a one-argument `if` call, which is a fatal make error. `make init` now aborts on EVERY invocation — the milestone's own AC3 feature (`make init MINERU_BIN=`) cannot run, and the previously-working `make init NOTEBOOK= EMAIL=` path is broken too. This is a hard regression against a shipped onboarding verb and must be fixed before merge.

## Executive summary

- [CRITICAL] `Makefile:479` — an `@#` comment containing `$(if $(strip ...))` makes `make init` fail with `*** insufficient number of arguments (1) to function 'if'` on every call; the target never runs.
- [CRITICAL] This is a regression: the pre-diff `init` target expanded and ran correctly; the base checkout was verified working.
- [MEDIUM] The milestone's new tests exercise `notebook_init.run(...)` in-process but never dry-run the `make init` recipe, so nothing guards the Make wrapper — that gap is exactly what let this CRITICAL through.
- [CLEAN] The functional recipe (line 481) is itself correct: quoting is intact, `.PHONY: init` is declared, the line is tab-indented, and `$(if $(strip ...))` emits each flag independently for NEITHER / EMAIL / MINERU_BIN / BOTH.
- [CLEAN] The new subprocess path (`tools/notebook_pdf_parse.py` → `run_mineru_sandboxed`) preserves sandbox discipline: `shell=False` fixed argv, scrubbed env, `start_new_session`, wall-timeout + `killpg`, no new privilege.

## Findings

**C1 — `make init` fatally broken: `$(if ...)` expanded inside a recipe comment** (CRITICAL)

**Where:** `Makefile:479`
**Anchor:** `@# $(if $(strip ...)) emits each flag onl`
**What:** The `@#` recipe-line comment contains a literal `$(if $(strip ...))`, and GNU make expands `$(...)` references on recipe lines (comments included) before handing them to the shell, so make parses it as an `if` function with a single argument and aborts with `makefile:479: *** insufficient number of arguments (1) to function 'if'. Stop.`
**Why it matters:** `make init` — a first-class onboarding verb — now fails at expand time on 100% of invocations (verified: NEITHER, EMAIL-only, MINERU_BIN-only, and BOTH all abort identically), so the milestone's headline AC3 feature is unrunnable and the previously-working `EMAIL=` path is a regression.
**Proposed fix:** Escape the dollar signs in the comment so make emits them literally instead of expanding: change line 479 to `@# $$(if $$(strip ...)) emits each flag only when its var is non-empty, so` (or reword the prose to drop the `$(...)` code-literal entirely, e.g. "make's conditional-flag idiom emits each flag only when its var is non-empty"). Verified: escaping to `$$(if $$(strip ...))` clears the error and the recipe then expands correctly in all four var combinations. The functional recipe on line 481 needs no change.
**Regression-guard:** Add a Make-level smoke test (extend `tests/tools/test_notebook_scripts.py`) that shells `make -n init NOTEBOOK=demo MINERU_BIN=/x PYTHON=python3`, asserts exit 0, and asserts the captured stdout contains `--mineru-bin`; it fails today and passes after the fix. A pure-Python `notebook_init.run()` test cannot catch a broken Make recipe.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Makefile / build script discipline

**M1 — New tests never dry-run the `make init` recipe (Make wrapper unguarded)** (MEDIUM)

**Where:** `tests/tools/test_notebook_scripts.py:226`
**Anchor:** `def test_init_persists_mineru_bin(notebooks`
**What:** The two added tests (`test_init_persists_mineru_bin`, `test_init_rejects_missing_mineru_bin`) call `notebook_init.run(...)` directly and assert the Python side effect, but no test invokes the `make init` target that AC3 actually ships, leaving the Make wrapper — where C1 lives — entirely uncovered.
**Why it matters:** The Make recipe is the documented operator entry point (`make init NOTEBOOK=<slug> MINERU_BIN=<path>`), so a break in the recipe layer ships green through the whole suite, as C1 demonstrates.
**Proposed fix:** Add one `make -n init ...` dry-run test (see C1 Regression-guard); gate it on `shutil.which("make")` so it skips cleanly on boxes without make rather than hard-failing CI.
**Regression-guard:** The dry-run test in C1 doubles as this guard.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Makefile / build script discipline

## What was done well

- The functional AC3 recipe (line 481) uses `$(if $(strip $(EMAIL)),...)` / `$(if $(strip $(MINERU_BIN)),...)` correctly: EMAIL and MINERU_BIN are independent optional flags, and behavior for NEITHER / EMAIL-only exactly matches the pre-diff if/else (no behavior regression in the recipe itself).
- Both interpolations stay shell-quoted (`--email "$(EMAIL)"`, `--mineru-bin "$(MINERU_BIN)"`), so values containing a space or comma pass through as a single argv token; the make-function comma-splitting happens before expansion, so a comma inside a value is safe.
- The `init` target is properly declared `.PHONY` (line 19) and the recipe lines are genuine tabs, so no "missing separator" or phony-collision hazard.
- The subprocess sandbox contract is preserved end-to-end: `tools/notebook_pdf_parse.py` delegates to `run_mineru_sandboxed`, which uses a fixed-argv `shell=False` Popen, a scrubbed env whitelist (proxies + AWS/GCP/Azure/HF creds stripped), per-invocation `TMPDIR` confinement, `start_new_session`, RLIMIT_AS on Linux, and a wall-timeout with `os.killpg` — no `shell=True`, no privilege escalation, no new egress.
- Timeout handling is sound: `--timeout-s` defaults to None (module-configured value), out-of-range values raise rather than silently clamp, and the CLI aggregates per-paper failures into a non-zero exit instead of aborting the batch mid-run.
- The binary-resolution extension (`explicit → env → operator_settings → which → raise`) validates each candidate is an existing file and degrades on any operator_settings read error via a local import, so `ingest/` gains no hard import dependency on `server/`.
- Documentation was kept honest: the Makefile `help` text, `docs/install.md`, and `docs/usage.md` were updated alongside the new `MINERU_BIN` var.

Severity counts: C1 H0 M1 L0

## Recommended rectification order

C1, M1

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed: <finding ids>
- Deferred: <finding ids>
- Invalidated: <finding ids with reasons>
- Regression tests added: <file paths>
