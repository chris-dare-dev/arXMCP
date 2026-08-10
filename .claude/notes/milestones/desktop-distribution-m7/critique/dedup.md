# Critique (merged) — desktop-distribution-m7

**Critics:** milestone-adversary-critic, milestone-infra-safety-critic
**Commit range:** 81d04ec..2877e07
**Diff stats:** 16 files, 1489 LOC
**Critique format version:** 1.0

> **Merge note.** Each critic authored its ids from 1 within its own file, so
> they collided across files. `findings.py merge` renumbered them into one
> gapless per-severity sequence in critic dispatch order; bodies are verbatim.
> **Phase 4 dispositions attach to the MERGED ids below**, not to the ids in
> the per-critic files. Re-running merge after a critic file changes will shift
> these ids - see milestone-pipeline-critique-format.md.
>
> - `milestone-adversary-critic` (adversary.md): ids unchanged
> - `milestone-infra-safety-critic` (infra-safety.md): H1->H3, M1->M5, M2->M6, M3->M7, M4->M8, M5->M9, L1->L2, L2->L3

## Verdict

**SHIP-WITH-FIXES** — the most severe of the per-critic verdicts below.

### milestone-adversary-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES. The packaging work is substantially real — the scanner opens
Mach-O binaries, nested zips and decompressed embedded-PYZ `.pyc` bytes and
caught a genuine `_sysconfigdata` `$HOME` leak; the AC3 proof drives the actual
frozen executable with a real `--multiprocessing-fork` argv rather than
repeating the hollow monkeypatch precedent; and the manifest hashes content,
not a normalized view. Two gaps matter: the "second independent build" reuses a
shared PyInstaller bincache that memoizes all 176 native binaries, so the empty
exception set is partly a cache replay for exactly the highest-risk file class;
and `docs/releasing.md` now wires a sidecar known not to launch into the release
procedure without saying so. Neither is a correctness defect in the committed
code; both are evidence/honesty gaps that a small fix closes.

### milestone-infra-safety-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES

The Makefile axis is clean: both new targets propagate exit codes, `make test` is untouched and the ~150 s builds genuinely stay out of it, and the `-m "X or not X"` tautology is a deliberate, compensated design rather than a repeat of m5's H3. The build-script axis has one real hole — AC5's temp-root needle is built from `os.path.realpath(gettempdir())` while the build is handed the raw `gettempdir()`, so on the macOS box this was measured on the two strings differ and the scan cannot match the string it exists to catch. The remaining findings are transient-disk and reproducibility foot-guns, not correctness breaks.

## Executive summary — milestone-adversary-critic

- [HIGH] `verify_determinism`'s second build shares `~/Library/Application Support/pyinstaller/bincache00py31264bit/arm64` (180 cached files) with the first; the bundle's 176 native binaries are cache replays, not independent reproductions.
- [HIGH] `docs/releasing.md` step 3 promotes `make desktop-package` as a release step without recording that the frozen child dies in `executable_identity()` before it can complete a launch handshake.
- [MEDIUM] The `verify` CLI subcommand is reachable from no make target and exercised by no test — ~15 lines of unverified exit-code logic.
- [MEDIUM] `test_manifest_diff_catches_content_membership_and_mode` will fail on Windows (`chmod(0o755)` is a no-op there) with no `skipif`, against a repo whose recorded suite baseline is a Windows run.
- [MEDIUM] The AC3 control arm asserts on a traceback that only exists because of the deferred `executable_identity` bug; fixing that bug breaks the test.
- [MEDIUM] The marker text's "~1.5 GB transient disk" is wrong in both directions: measured 1.7 GB **persistent** (992 MB build-venv + 735 MB dist), ~2.5 GB at verify peak, and nothing cleans it up.
- [LOW] The needle set carries no build-root needle despite CLAUDE.md and the marker both calling it a "build-root string scan"; it works only because this checkout happens to sit under `$HOME`.
- [WAIVED] Diff size (1,489 LOC) exceeds the 400-LOC auto-finding threshold; owner-authorized via `--allow-large-diff` with `implement/scope-exceeded.md` — not filed per orchestrator instruction.

## Executive summary — milestone-infra-safety-critic

- [HIGH] `default_needles()["tmp"]` realpaths the temp root (`/private/var/folders/…`) while `_tool_env()` passes the build the raw form (`/var/folders/…`); verified divergent on this box, so AC5's temp-root coverage is one-directional.
- [MEDIUM] The embedded-PYZ scan's coverage floors live only in `tests/test_desktop_package.py`; `build_once` asserts nothing, so `make desktop-package` — which `docs/releasing.md` step 3 says "fails on any build-machine path string" — passes vacuously if the archive reader yields zero entries.
- [MEDIUM] No `try`/`finally` around the work trees: a `BuildError` or interrupt strands `work` / `work-a` / `work-b` / `dist-verify` (~1.5 GB), and a later `build` run only cleans `work`, never the `verify` pair.
- [MEDIUM] `requirements-build.txt` is a macOS-resolved lock (`macholib` in, `pywin32-ctypes` absent) and `_tool_env()` hardcodes a POSIX `PATH`, so the packaging path is macOS/Linux-only despite `_venv_python`'s `os.name == "nt"` branch implying otherwise.
- [MEDIUM] First-run NETWORK dependence is named only in the pyproject marker prose; `make help` and `docs/releasing.md` say "one-time provisioning" without saying network, and `_tool_env()` strips proxy/TLS env so a proxied box fails with a truncated `uv` stderr.
- [MEDIUM] The needle set covers `$HOME`, username and temp root but not the build root / `--workpath` / `--distpath`, so a checkout outside `$HOME` leaves the build path itself unscanned.
- [LOW] `verify_determinism` returns scan hits without raising, asymmetric with `build_once`, relying on every caller to re-check.
- [LOW] `EXPECTED_EXCEPTION_COUNT` is defined in the driver but read only from the test module.

## Findings

**H1 — Second build replays a shared PyInstaller bincache** (HIGH)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:424`
**Anchor:** `bundle_b = build_bundle(python, root / "w`
**What:** The two builds get fresh `--workpath`/`--distpath` but `_tool_env()` pins `HOME` to the real user home, so both resolve the same PyInstaller `CONF_DIR` bincache — confirmed present on this box with 180 cached files under `bincache00py31264bit/arm64`, against a bundle reporting `native_files: 176` — and on macOS `checkCache` is on the path for every binary because of load-path rewriting and ad-hoc signing.
**Why it matters:** AC1 exists as a tripwire against new nondeterminism, and the file class most likely to carry it (processed, ad-hoc-signed Mach-O binaries) is precisely the class build B copies out of build A's cache, so an "EMPTY exception set" is unproven for ~176 of 6,326 manifest entries.
**Proposed fix:** Give the second build its own config dir — thread an override into `_tool_env()` and pass a per-build value from `build_bundle` (`env["PYINSTALLER_CONFIG_DIR"] = str(workpath / "pyi-conf")`, which PyInstaller reads in `compat.CONF_DIR`). Re-measure the exception set with build B cold; if entries appear, they are real AC1 exceptions and belong in `NONDETERMINISTIC_EXCEPTIONS` with a per-entry rationale plus the mirrored count bump. If the set stays empty, the claim is then earned.
**Regression-guard:** Extend `test_two_builds_are_byte_identical_within_pinned_exceptions` to assert the two builds used distinct config dirs (e.g. the report records both paths and they differ, and build B's `bincache*` directory did not exist before build B started).
**Source critic:** milestone-adversary-critic
**Source axis:** acceptance coverage

**H2 — Release procedure ships a sidecar that cannot launch** (HIGH)

**Where:** `docs/releasing.md:41`
**Anchor:** `3. **Desktop bundle (if the release ships`
**What:** The new operator-facing release step describes the bundle as the shippable desktop sidecar and lists its hygiene proofs, but never states that `server/desktop_child.py:106`'s `hashlib.sha256(Path(__file__).read_bytes())` has no on-disk source once frozen, so `main()` raises at `executable_identity()` (line 345) before it ever reads the launch frame — the frozen child cannot complete a handshake at all.
**Why it matters:** The only written record of this is a test docstring at `tests/test_desktop_package.py:257` and the commit body; a release engineer following `docs/releasing.md` would attach a sidecar binary that exits with a traceback on first launch, and the ADR-grade doc surfaces (CLAUDE.md, releasing.md) say nothing.
**Proposed fix:** Add a bounded, dated limitation note to the `docs/releasing.md` step — one sentence naming `executable_identity()`, the frozen `__file__` cause, and the owning follow-up (m8) — and state that the artifact is currently consumable only by signing/packaging work, not as a runnable sidecar. Mirror one line into CLAUDE.md's `requires_desktop_package` bullet so an agent reading the marker inventory learns it too.
**Regression-guard:** A doc test in the spirit of `tests/test_marker_doc_consistency.py`: assert `docs/releasing.md` mentions `executable_identity` for as long as `server/desktop_child.py` still calls `Path(__file__).read_bytes()` in that function — so the caveat cannot outlive or predecease the bug.
**Source critic:** milestone-adversary-critic
**Source axis:** doc drift

**H3 — AC5 temp-root needle is realpath'd but the build gets the raw path** (HIGH)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:292`
**Anchor:** `        "tmp": os.path.realpath(tempfile.g`
**What:** The `tmp` needle is `os.path.realpath(tempfile.gettempdir())` while `_tool_env()` hands the build `TMPDIR = tempfile.gettempdir()` unresolved, and on macOS those differ (`/private/var/folders/dd/…/T` vs `/var/folders/dd/…/T` — measured on this box), so the needle is not a substring of the string the toolchain actually embeds.
**Why it matters:** AC5's third coverage axis silently matches nothing on the platform the milestone was measured on; a `co_filename` or build-path leak carrying the raw temp root ships and the gate still reports a clean scan.
**Proposed fix:** Emit both forms as separate needles, e.g. `raw = tempfile.gettempdir()` and `real = os.path.realpath(raw)`, keyed `"tmp"` and `"tmp_real"`, and drop the second only when the two strings are equal. Same treatment is cheap insurance for `Path.home()` on hosts where the home path is itself a symlink.
**Regression-guard:** Extend `tests/test_desktop_package.py::test_scanner_finds_needle_in_binary_and_extensionless_files` with a case asserting `set(dp.default_needles()) >= {"tmp", "tmp_real"}` whenever `tempfile.gettempdir() != os.path.realpath(tempfile.gettempdir())`, plus a fixture file containing only the raw form that the scan must flag.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M1 — `verify` subcommand is unreachable and untested** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:457`
**Anchor:** `report = verify_determinism(args.root)`
**What:** `main()`'s `verify` branch — the exception-set subtraction, the scan-hit check and both exit codes — is invoked by no make target (`desktop-package` runs `build`; `desktop-package-check` calls `verify_determinism()` directly through pytest) and by no test.
**Why it matters:** It duplicates the gate's assertions in code that no gate executes, so it can rot into a false-green CLI that a future operator or CI hook trusts.
**Proposed fix:** Either drop the `verify` choice and let `make desktop-package-check` be the single entry point, or add a fast unit test that monkeypatches `verify_determinism` to return a synthetic report with one unexpected differing path and one with a scan hit, asserting `main(["verify"])` returns 1 in both cases and 0 on a clean report.
**Regression-guard:** Optional — the unit test above is itself the guard.
**Source critic:** milestone-adversary-critic
**Source axis:** dead code / leftovers

**M2 — New manifest test hard-fails on Windows with no guard** (MEDIUM)

**Where:** `tests/test_desktop_package.py:178`
**Anchor:** `(b / "mode.sh").chmod(0o755)`
**What:** The test's third expected diff entry depends on a POSIX mode bit; on Windows `os.chmod` only toggles read-only, so `a/mode.sh` and `b/mode.sh` produce identical `mode:size:sha256` values and the exact-equality assertion on `["mode.sh", "only-in-b", "sub/content.bin"]` fails.
**Why it matters:** This is a fast test that runs in every `make test`, and CLAUDE.md § 3's recorded suite baseline is a Windows run with zero failures — the repo's convention from the 2026-07-12 portability push is a `sys.platform == "win32"` guard for a genuinely absent OS capability, not an unguarded failure.
**Proposed fix:** Split the mode leg into its own `@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")` test and leave the content/membership assertions unguarded, preserving the § 4.1 POSIX authority while keeping the Windows run green.
**Regression-guard:** Optional.
**Source critic:** milestone-adversary-critic
**Source axis:** test discipline

**M3 — AC3 control arm is coupled to the deferred frozen bug** (MEDIUM)

**Where:** `tests/test_desktop_package.py:273`
**Anchor:** `assert b", in main" in control.stderr, (`
**What:** The control arm proves "what entering `main()` looks like" only because the frozen child currently raises inside `executable_identity()` and prints a traceback containing `, in main`; once that is fixed, `main()` reaches `read_frame` on a `DEVNULL` stdin, hits the `DesktopContractError` path and returns 2 via `logger.error` with no traceback, so the assertion fails.
**Why it matters:** The milestone's strongest AC3 evidence is wired to a bug the same commit defers, so the m8 fix will look like an m7 regression — and a rushed repair is more likely to weaken the control arm than to re-establish an equivalent one.
**Proposed fix:** Assert on a marker that survives the fix instead of a traceback frame: have the control arm assert the child produced the launch-contract rejection (`returncode == 2` or the `desktop child rejected launch` log line) *or* the current traceback, and keep the fork-flagged arm's `EOFError` + absence-of-`main` assertions unchanged. Record in the docstring that the discriminator must be a signal `main()` emits on *any* entry path.
**Regression-guard:** Optional — the reworked control arm is the guard.
**Source critic:** milestone-adversary-critic
**Source axis:** test discipline

**M4 — Disk-footprint claim is understated and mislabelled transient** (MEDIUM)

**Where:** `pyproject.toml:375`
**Anchor:** `"requires_desktop_package: desktop-distr`
**What:** The marker text (echoed by CLAUDE.md) says "~1.5 GB transient disk"; measured on this box after the gate ran, `var/desktop-package/` holds 992 MB of build-venv plus 735 MB of `dist` — 1.7 GB **persistent**, roughly 2.5 GB at the moment `dist-verify` also exists — and no `clean` target or driver path removes any of it.
**Why it matters:** An operator budgeting for a transient 1.5 GB gets a permanent 1.7 GB with no documented way to reclaim it, and the persistence is load-bearing (the build venv is intentionally reused), so calling it transient hides a real design decision rather than a rounding error.
**Proposed fix:** Correct both strings to name the split — "~1 GB persistent build venv plus ~0.75 GB per bundle (~2.5 GB peak during the two-build verify)" — and add a `desktop-package-clean` make target that removes `var/desktop-package/`, referenced from the `help` line so reclaiming it is discoverable.
**Regression-guard:** Optional.
**Source critic:** milestone-adversary-critic
**Source axis:** doc drift

**M5 — Embedded-PYZ scan has no coverage floor in the build path** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:399`
**Anchor:** `    scan = scan_tree(bundle, default_needl`
**What:** `build_once` checks only `scan["hits"]`; the `embedded` sub-report's `entries_scanned` / `pyc_entries` counters are written to `report.json` but never asserted, so an archive reader that returns an empty TOC produces an indistinguishable "clean" result — the `read != meta.st_size` tripwire covers only the raw-file scope, not the embedded one.
**Why it matters:** The compressed PYZ is the sole coverage for the measured `_sysconfigdata` leak (21 `build_time_vars` values), and `docs/releasing.md` step 3 advertises `make desktop-package` as failing on any build-machine path string — a guarantee only `make desktop-package-check` actually enforces.
**Proposed fix:** Move the floors out of the test and into the driver: in `build_once` (and `verify_determinism`) raise `BuildError` when `scan["embedded"]["pyc_entries"] == 0` or `scan["files_scanned"] == 0`, keeping the test's higher numeric floors as the tighter gate assertion.
**Regression-guard:** A unit test that monkeypatches `scan_embedded_archives` to return `{"hits": {}, "entries_scanned": 0, "pyc_entries": 0}` and asserts `build_once` raises.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M6 — Transient work trees are not cleaned on failure or interrupt** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:398`
**Anchor:** `    shutil.rmtree(root / "work", ignore_er`
**What:** The `rmtree` calls sit on the success path only — a `BuildError` from `build_bundle`, a `subprocess` timeout, or a `KeyboardInterrupt` strands `root/work`, and in `verify_determinism` strands `work-a`, `work-b` and `dist-verify`, with no `try`/`finally`.
**Why it matters:** Each work tree is a large fraction of the ~1.5 GB transient budget, and the self-healing is partial: `build_bundle` rmtrees only the workpath it is about to use, so a failed `verify` leaves `work-a`/`work-b` that no subsequent `make desktop-package` ever reclaims.
**Proposed fix:** Wrap each build in `try: … finally: shutil.rmtree(path, ignore_errors=True)`, and add a startup sweep that removes any stale `work*` / `dist-verify` under `root` before the first build.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M7 — Build stack is macOS/Linux-only while the code advertises Windows support** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/requirements-build.txt:2`
**Anchor:** `#    uv pip compile --generate-hashes --p`
**What:** The lock was compiled with `--python-version 3.12` on macOS and carries no environment markers — `macholib` (darwin-only) is pinned and `pywin32-ctypes` (PyInstaller's win32 requirement) is absent — while `_tool_env()` hardcodes `PATH=/usr/bin:/bin:/usr/sbin:/sbin`, yet `_venv_python` carries an `os.name == "nt"` branch implying the driver runs on Windows.
**Why it matters:** `--require-hashes` forbids resolving the missing Windows dependency at install time, so on the Windows box CLAUDE.md §3 records as the primary test host the packaging path fails in two unrelated ways with nothing in the docs saying it is unsupported.
**Proposed fix:** Either state the macOS/Linux-only scope explicitly in `requirements-build.in`, `make help` and `docs/releasing.md` step 3, or regenerate with `--universal` and add the `sys_platform` markers, and derive `_tool_env()["PATH"]` per-platform instead of hardcoding the POSIX list.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M8 — First-run network dependence is not named where an operator reads** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:94`
**Anchor:** `        "PATH": "/usr/bin:/bin:/usr/sbin:/`
**What:** `_tool_env()` replaces the ambient environment wholesale, dropping `HTTPS_PROXY` / `SSL_CERT_FILE` / `UV_*` alongside `PYTHONPATH`, and there is no preflight for reachability — the network requirement appears only in the `pyproject.toml` marker prose, while `make help` and `docs/releasing.md` step 3 say only "one-time build-venv provisioning".
**Why it matters:** On an offline or proxied machine the first `make desktop-package` fails inside `uv sync` and surfaces as a `BuildError` carrying a 4000-char stderr tail, which reads as a build bug rather than "this step needs network".
**Proposed fix:** Add "requires network on first run" to the two `make help` lines and to `docs/releasing.md` step 3, and pass through `HTTPS_PROXY`/`HTTP_PROXY`/`NO_PROXY`/`SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` when set — none of them perturb build determinism the way `PYTHONPATH` would.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M9 — Needle set omits the build root, workpath and distpath** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:288`
**Anchor:** `    home = str(Path.home())`
**What:** The scan looks for `$HOME`, the username and the temp root, but not `REPO_ROOT`, the `--workpath` or the `--distpath` that PyInstaller is actually handed; those are covered today only incidentally, because this checkout happens to live under `$HOME`.
**Why it matters:** A CI or release box building from a checkout outside `$HOME` (`/opt/build/arXMCP`, `/builds/…`) leaves the single most likely leaked prefix — the build directory itself — entirely unscanned, and the gate reports clean.
**Proposed fix:** Add `str(REPO_ROOT)`, `str(workpath)` and `str(distpath)` as needles (threading the two paths into `scan_tree`'s caller), de-duplicating any that are already a prefix of an existing needle.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**L1 — "build-root string scan" has no build-root needle** (LOW)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:286`
**Anchor:** `def default_needles() -> dict[str, bytes`
**What:** `default_needles()` returns exactly `home`, `user` and `tmp`; CLAUDE.md's new marker bullet and the `pyproject.toml` marker both describe AC5 as a "build-root string scan", which the needle set only covers incidentally because this checkout sits under `$HOME`.
**Why it matters:** On a checkout outside `$HOME` (a CI workspace at `/build/arxmcp`), the `--workpath`/`--distpath` strings PyInstaller can embed would pass the scan while the docs claim they are checked.
**Proposed fix:** Either add `str(REPO_ROOT)` as a fourth needle — cheap, and strictly widens the tripwire — or reword both doc strings to say "host temp root, `$HOME` prefix and username", matching the brief's AC5 wording and the code.
**Regression-guard:** Optional.
**Source critic:** milestone-adversary-critic
**Source axis:** doc drift

**L2 — `verify_determinism` reports scan hits without raising** (LOW)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:429`
**Anchor:** `    scan = scan_tree(bundle_a, default_nee`
**What:** `build_once` raises `BuildError` on any scan hit, but `verify_determinism` returns the hits in its report and leaves the check to each caller.
**Why it matters:** Both current callers do check, so nothing is broken today; a third caller that forgets inherits a silently permissive path from a function whose whole purpose is evidence.
**Proposed fix:** Raise from `verify_determinism` too, and have the CLI/test catch it, so the fail-closed behavior is a property of the function rather than of its callers.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**L3 — `EXPECTED_EXCEPTION_COUNT` is unused inside the driver** (LOW)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:54`
**Anchor:** `EXPECTED_EXCEPTION_COUNT = 0`
**What:** The constant is read only by `tests/test_desktop_package.py::test_exception_set_is_closed_and_size_pinned`; the driver never compares it against `len(NONDETERMINISTIC_EXCEPTIONS)`.
**Why it matters:** It reads as a driver-enforced invariant while enforcing nothing there, so widening the frozenset without touching the count is caught by the test but not by `make desktop-package`.
**Proposed fix:** Add a module-level `if len(NONDETERMINISTIC_EXCEPTIONS) != EXPECTED_EXCEPTION_COUNT: raise RuntimeError(...)` — matching CLAUDE.md §4.7's `raise`-not-`assert` rule — so the two stay bound wherever the module is imported.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

## What was done well

### From milestone-adversary-critic

- The manifest hashes real content (`mode:size:sha256`, symlinks by target) rather than a normalized view, and excludes only mtimes with that exclusion stated in the docstring — the determinism claim is not a definitional artifact.
- The two ordering drifts were **fixed in the spec** (sorted `base_library.zip` members, sorted PYZ TOC) rather than excused into the exception set, which is what keeps the set closed and the AC honest.
- AC3 is proven on the real frozen executable with a genuine `--multiprocessing-fork` argv and an inherited pipe, and the docstring explicitly names `test_desktop_sidecar_spike.py`'s monkeypatched precedent as the thing it must not repeat.
- The scanner reads every regular file irrespective of extension, decompresses nested zip members and the executables' embedded PYZ entries, and carries a `bytes_scanned == lstat_bytes` tripwire plus coverage floors — a genuine defense against an early-return or a glob that skips files.
- AC4 asserts the leak was **observed** pre-sanitize (`leak_observed is True`), not merely that the file is absent afterward — a check that would otherwise pass vacuously.
- The `_sysconfigdata` fix is the milestone's best catch: it required understanding that repointing the TOC `src` is insufficient because `PYZ.assemble` reads a pre-compiled object out of `CONF['code_cache']`, and it fails loudly if no `_sysconfigdata` module is ever collected.
- AC2 converts the fixtures in the source venv **within the same test invocation** and hash-compares the bundled symbol table, so it can never degrade into a golden the bundle generated for itself.
- Gate wiring is correct: `requires_desktop_package` is registered in both `pyproject.toml` and `conftest._OPT_IN_MARKERS`, `DESKTOP_PACKAGE_GATE` joins `_DESKTOP_GATE_ENV` so any skip flips the exit status, the `-m` tautology is the established backstopped pattern rather than m5's H3 defect, and the ~150 s of builds stay out of `make test`.
- The commit is GPG-signed, conventional, uses the established `feat(desktop)` scope, and its body volunteers the deferred `executable_identity` limitation instead of hiding it.

### From milestone-infra-safety-critic

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

Severity counts: C0 H3 M9 L3


## Cross-critic agreement

The following findings cluster within 5 lines of each other in the same file. Multiple critics flagged the same area - these are the strongest signals to fix first.

- **L1, M9, H3** at `apps/desktop/pyinstaller/desktop_package.py:286-292` (HIGH): "build-root string scan" has no build-root needle; Needle set omits the build root, workpath and distpath; AC5 temp-root needle is realpath'd but the build gets the raw path
- **M6, M5** at `apps/desktop/pyinstaller/desktop_package.py:398-399` (MEDIUM): Transient work trees are not cleaned on failure or interrupt; Embedded-PYZ scan has no coverage floor in the build path
- **H1, L2** at `apps/desktop/pyinstaller/desktop_package.py:424-429` (HIGH): Second build replays a shared PyInstaller bincache; `verify_determinism` reports scan hits without raising

## Recommended rectification order

H2, H1, H3, M3, M2, M1, M4, M5, M9, M6, M8, M7, L1, L2, L3

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
