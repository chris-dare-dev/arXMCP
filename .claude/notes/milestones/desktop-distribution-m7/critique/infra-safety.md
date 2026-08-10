# Critique — desktop-distribution-m7 — milestone-infra-safety-critic

**Critic:** milestone-infra-safety-critic
**Commit range:** 81d04ec..2877e07
**Diff stats:** 16 files, 1507 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

The Makefile axis is clean: both new targets propagate exit codes, `make test` is untouched and the ~150 s builds genuinely stay out of it, and the `-m "X or not X"` tautology is a deliberate, compensated design rather than a repeat of m5's H3. The build-script axis has one real hole — AC5's temp-root needle is built from `os.path.realpath(gettempdir())` while the build is handed the raw `gettempdir()`, so on the macOS box this was measured on the two strings differ and the scan cannot match the string it exists to catch. The remaining findings are transient-disk and reproducibility foot-guns, not correctness breaks.

## Executive summary

- [HIGH] `default_needles()["tmp"]` realpaths the temp root (`/private/var/folders/…`) while `_tool_env()` passes the build the raw form (`/var/folders/…`); verified divergent on this box, so AC5's temp-root coverage is one-directional.
- [MEDIUM] The embedded-PYZ scan's coverage floors live only in `tests/test_desktop_package.py`; `build_once` asserts nothing, so `make desktop-package` — which `docs/releasing.md` step 3 says "fails on any build-machine path string" — passes vacuously if the archive reader yields zero entries.
- [MEDIUM] No `try`/`finally` around the work trees: a `BuildError` or interrupt strands `work` / `work-a` / `work-b` / `dist-verify` (~1.5 GB), and a later `build` run only cleans `work`, never the `verify` pair.
- [MEDIUM] `requirements-build.txt` is a macOS-resolved lock (`macholib` in, `pywin32-ctypes` absent) and `_tool_env()` hardcodes a POSIX `PATH`, so the packaging path is macOS/Linux-only despite `_venv_python`'s `os.name == "nt"` branch implying otherwise.
- [MEDIUM] First-run NETWORK dependence is named only in the pyproject marker prose; `make help` and `docs/releasing.md` say "one-time provisioning" without saying network, and `_tool_env()` strips proxy/TLS env so a proxied box fails with a truncated `uv` stderr.
- [MEDIUM] The needle set covers `$HOME`, username and temp root but not the build root / `--workpath` / `--distpath`, so a checkout outside `$HOME` leaves the build path itself unscanned.
- [LOW] `verify_determinism` returns scan hits without raising, asymmetric with `build_once`, relying on every caller to re-check.
- [LOW] `EXPECTED_EXCEPTION_COUNT` is defined in the driver but read only from the test module.

## Findings

**H1 — AC5 temp-root needle is realpath'd but the build gets the raw path** (HIGH)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:292`
**Anchor:** `        "tmp": os.path.realpath(tempfile.g`
**What:** The `tmp` needle is `os.path.realpath(tempfile.gettempdir())` while `_tool_env()` hands the build `TMPDIR = tempfile.gettempdir()` unresolved, and on macOS those differ (`/private/var/folders/dd/…/T` vs `/var/folders/dd/…/T` — measured on this box), so the needle is not a substring of the string the toolchain actually embeds.
**Why it matters:** AC5's third coverage axis silently matches nothing on the platform the milestone was measured on; a `co_filename` or build-path leak carrying the raw temp root ships and the gate still reports a clean scan.
**Proposed fix:** Emit both forms as separate needles, e.g. `raw = tempfile.gettempdir()` and `real = os.path.realpath(raw)`, keyed `"tmp"` and `"tmp_real"`, and drop the second only when the two strings are equal. Same treatment is cheap insurance for `Path.home()` on hosts where the home path is itself a symlink.
**Regression-guard:** Extend `tests/test_desktop_package.py::test_scanner_finds_needle_in_binary_and_extensionless_files` with a case asserting `set(dp.default_needles()) >= {"tmp", "tmp_real"}` whenever `tempfile.gettempdir() != os.path.realpath(tempfile.gettempdir())`, plus a fixture file containing only the raw form that the scan must flag.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M1 — Embedded-PYZ scan has no coverage floor in the build path** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:399`
**Anchor:** `    scan = scan_tree(bundle, default_needl`
**What:** `build_once` checks only `scan["hits"]`; the `embedded` sub-report's `entries_scanned` / `pyc_entries` counters are written to `report.json` but never asserted, so an archive reader that returns an empty TOC produces an indistinguishable "clean" result — the `read != meta.st_size` tripwire covers only the raw-file scope, not the embedded one.
**Why it matters:** The compressed PYZ is the sole coverage for the measured `_sysconfigdata` leak (21 `build_time_vars` values), and `docs/releasing.md` step 3 advertises `make desktop-package` as failing on any build-machine path string — a guarantee only `make desktop-package-check` actually enforces.
**Proposed fix:** Move the floors out of the test and into the driver: in `build_once` (and `verify_determinism`) raise `BuildError` when `scan["embedded"]["pyc_entries"] == 0` or `scan["files_scanned"] == 0`, keeping the test's higher numeric floors as the tighter gate assertion.
**Regression-guard:** A unit test that monkeypatches `scan_embedded_archives` to return `{"hits": {}, "entries_scanned": 0, "pyc_entries": 0}` and asserts `build_once` raises.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M2 — Transient work trees are not cleaned on failure or interrupt** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:398`
**Anchor:** `    shutil.rmtree(root / "work", ignore_er`
**What:** The `rmtree` calls sit on the success path only — a `BuildError` from `build_bundle`, a `subprocess` timeout, or a `KeyboardInterrupt` strands `root/work`, and in `verify_determinism` strands `work-a`, `work-b` and `dist-verify`, with no `try`/`finally`.
**Why it matters:** Each work tree is a large fraction of the ~1.5 GB transient budget, and the self-healing is partial: `build_bundle` rmtrees only the workpath it is about to use, so a failed `verify` leaves `work-a`/`work-b` that no subsequent `make desktop-package` ever reclaims.
**Proposed fix:** Wrap each build in `try: … finally: shutil.rmtree(path, ignore_errors=True)`, and add a startup sweep that removes any stale `work*` / `dist-verify` under `root` before the first build.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M3 — Build stack is macOS/Linux-only while the code advertises Windows support** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/requirements-build.txt:2`
**Anchor:** `#    uv pip compile --generate-hashes --p`
**What:** The lock was compiled with `--python-version 3.12` on macOS and carries no environment markers — `macholib` (darwin-only) is pinned and `pywin32-ctypes` (PyInstaller's win32 requirement) is absent — while `_tool_env()` hardcodes `PATH=/usr/bin:/bin:/usr/sbin:/sbin`, yet `_venv_python` carries an `os.name == "nt"` branch implying the driver runs on Windows.
**Why it matters:** `--require-hashes` forbids resolving the missing Windows dependency at install time, so on the Windows box CLAUDE.md §3 records as the primary test host the packaging path fails in two unrelated ways with nothing in the docs saying it is unsupported.
**Proposed fix:** Either state the macOS/Linux-only scope explicitly in `requirements-build.in`, `make help` and `docs/releasing.md` step 3, or regenerate with `--universal` and add the `sys_platform` markers, and derive `_tool_env()["PATH"]` per-platform instead of hardcoding the POSIX list.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M4 — First-run network dependence is not named where an operator reads** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:94`
**Anchor:** `        "PATH": "/usr/bin:/bin:/usr/sbin:/`
**What:** `_tool_env()` replaces the ambient environment wholesale, dropping `HTTPS_PROXY` / `SSL_CERT_FILE` / `UV_*` alongside `PYTHONPATH`, and there is no preflight for reachability — the network requirement appears only in the `pyproject.toml` marker prose, while `make help` and `docs/releasing.md` step 3 say only "one-time build-venv provisioning".
**Why it matters:** On an offline or proxied machine the first `make desktop-package` fails inside `uv sync` and surfaces as a `BuildError` carrying a 4000-char stderr tail, which reads as a build bug rather than "this step needs network".
**Proposed fix:** Add "requires network on first run" to the two `make help` lines and to `docs/releasing.md` step 3, and pass through `HTTPS_PROXY`/`HTTP_PROXY`/`NO_PROXY`/`SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` when set — none of them perturb build determinism the way `PYTHONPATH` would.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M5 — Needle set omits the build root, workpath and distpath** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:288`
**Anchor:** `    home = str(Path.home())`
**What:** The scan looks for `$HOME`, the username and the temp root, but not `REPO_ROOT`, the `--workpath` or the `--distpath` that PyInstaller is actually handed; those are covered today only incidentally, because this checkout happens to live under `$HOME`.
**Why it matters:** A CI or release box building from a checkout outside `$HOME` (`/opt/build/arXMCP`, `/builds/…`) leaves the single most likely leaked prefix — the build directory itself — entirely unscanned, and the gate reports clean.
**Proposed fix:** Add `str(REPO_ROOT)`, `str(workpath)` and `str(distpath)` as needles (threading the two paths into `scan_tree`'s caller), de-duplicating any that are already a prefix of an existing needle.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**L1 — `verify_determinism` reports scan hits without raising** (LOW)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:429`
**Anchor:** `    scan = scan_tree(bundle_a, default_nee`
**What:** `build_once` raises `BuildError` on any scan hit, but `verify_determinism` returns the hits in its report and leaves the check to each caller.
**Why it matters:** Both current callers do check, so nothing is broken today; a third caller that forgets inherits a silently permissive path from a function whose whole purpose is evidence.
**Proposed fix:** Raise from `verify_determinism` too, and have the CLI/test catch it, so the fail-closed behavior is a property of the function rather than of its callers.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**L2 — `EXPECTED_EXCEPTION_COUNT` is unused inside the driver** (LOW)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:54`
**Anchor:** `EXPECTED_EXCEPTION_COUNT = 0`
**What:** The constant is read only by `tests/test_desktop_package.py::test_exception_set_is_closed_and_size_pinned`; the driver never compares it against `len(NONDETERMINISTIC_EXCEPTIONS)`.
**Why it matters:** It reads as a driver-enforced invariant while enforcing nothing there, so widening the frozenset without touching the count is caught by the test but not by `make desktop-package`.
**Proposed fix:** Add a module-level `if len(NONDETERMINISTIC_EXCEPTIONS) != EXPECTED_EXCEPTION_COUNT: raise RuntimeError(...)` — matching CLAUDE.md §4.7's `raise`-not-`assert` rule — so the two stay bound wherever the module is imported.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

## What was done well

- The `requires_desktop_package` marker is registered in **both** `pyproject.toml` and `tests/conftest.py::_OPT_IN_MARKERS` — the issue-#206 bug (registering only one) is not repeated.
- `make test` is untouched (`ruff check .` then bare `pytest`), and the marker deselection keeps the ~150 s of builds out of the default gate; the module-scoped `packaged` fixture is referenced only by marked tests, so no fast test can trigger a build. The m6 default-gate regression is not repeated.
- The `-m "requires_desktop_package or not requires_desktop_package"` tautology is deliberate and compensated, not m5's H3 returning: because pytest's own filter deselects nothing, every would-be skip produces a report, and `pytest_runtest_logreport` + `pytest_sessionfinish` turn any skip under `DESKTOP_PACKAGE_GATE=1` into a nonzero exit. A drifted marker name fails loudly instead of exiting 0 with no evidence.
- Explicit `--workpath` / `--distpath` under gitignored `var/desktop-package/`, deliberately away from PyInstaller's repo-root `build/` default. `git check-ignore` confirms no m7 source file is swallowed by the concurrently-added `/build/` and `/dist/` rules, and those rules are root-anchored so `var/desktop-package/dist` is unaffected.
- `build_wheel` records whether a repo-root `build/` scratch tree pre-existed and removes it only if it created it — no blind destructive `rmtree` of an operator's tree.
- Every new recipe line is a single command, so exit codes propagate per line; no `cmd1; cmd2` swallowing, no `sudo`, no destructive default, and both targets are declared `.PHONY`.
- The determinism harness is genuinely two independent PyInstaller invocations into freshly-rmtree'd work and dist paths, compared by a mode/size/sha256 per-file manifest that deliberately excludes mtimes — not one build re-hashed — and the second bundle is reclaimed by default.
- `requirements-build.txt` hash-pins **every** entry, transitive ones included, and is installed with `--require-hashes`, so a missing hash fails the install rather than silently weakening the guarantee; the `.in` header records the exact regeneration command and the spike-pinned wheel hash to re-verify against.
- Every subprocess carries a bounded `timeout` (1800 s default) and `_run` raises with truncated stdout/stderr on nonzero exit — no unbounded wait and no swallowed subprocess failure.
- The raw-file scanner opens **every** regular file as bytes (Mach-O included, not just archives and text), carries a chunk-boundary overlap so a needle spanning a 4 MiB read is still found, and cross-checks `read` against `st_size` per file — so a scan that failed to read is distinguishable from a scan that found nothing, at least in that scope.

Severity counts: C0 H1 M5 L2

## Recommended rectification order

H1, M1, M5, M2, M4, M3, L1, L2

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
