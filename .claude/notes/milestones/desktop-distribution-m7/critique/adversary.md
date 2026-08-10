# Critique — desktop-distribution-m7 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** 81d04ec..2877e07
**Diff stats:** 16 files, 1489 LOC
**Critique format version:** 1.0

## Verdict

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

## Executive summary

- [HIGH] `verify_determinism`'s second build shares `~/Library/Application Support/pyinstaller/bincache00py31264bit/arm64` (180 cached files) with the first; the bundle's 176 native binaries are cache replays, not independent reproductions.
- [HIGH] `docs/releasing.md` step 3 promotes `make desktop-package` as a release step without recording that the frozen child dies in `executable_identity()` before it can complete a launch handshake.
- [MEDIUM] The `verify` CLI subcommand is reachable from no make target and exercised by no test — ~15 lines of unverified exit-code logic.
- [MEDIUM] `test_manifest_diff_catches_content_membership_and_mode` will fail on Windows (`chmod(0o755)` is a no-op there) with no `skipif`, against a repo whose recorded suite baseline is a Windows run.
- [MEDIUM] The AC3 control arm asserts on a traceback that only exists because of the deferred `executable_identity` bug; fixing that bug breaks the test.
- [MEDIUM] The marker text's "~1.5 GB transient disk" is wrong in both directions: measured 1.7 GB **persistent** (992 MB build-venv + 735 MB dist), ~2.5 GB at verify peak, and nothing cleans it up.
- [LOW] The needle set carries no build-root needle despite CLAUDE.md and the marker both calling it a "build-root string scan"; it works only because this checkout happens to sit under `$HOME`.
- [WAIVED] Diff size (1,489 LOC) exceeds the 400-LOC auto-finding threshold; owner-authorized via `--allow-large-diff` with `implement/scope-exceeded.md` — not filed per orchestrator instruction.

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

**L1 — "build-root string scan" has no build-root needle** (LOW)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:286`
**Anchor:** `def default_needles() -> dict[str, bytes`
**What:** `default_needles()` returns exactly `home`, `user` and `tmp`; CLAUDE.md's new marker bullet and the `pyproject.toml` marker both describe AC5 as a "build-root string scan", which the needle set only covers incidentally because this checkout sits under `$HOME`.
**Why it matters:** On a checkout outside `$HOME` (a CI workspace at `/build/arxmcp`), the `--workpath`/`--distpath` strings PyInstaller can embed would pass the scan while the docs claim they are checked.
**Proposed fix:** Either add `str(REPO_ROOT)` as a fourth needle — cheap, and strictly widens the tripwire — or reword both doc strings to say "host temp root, `$HOME` prefix and username", matching the brief's AC5 wording and the code.
**Regression-guard:** Optional.
**Source critic:** milestone-adversary-critic
**Source axis:** doc drift

## What was done well

- The manifest hashes real content (`mode:size:sha256`, symlinks by target) rather than a normalized view, and excludes only mtimes with that exclusion stated in the docstring — the determinism claim is not a definitional artifact.
- The two ordering drifts were **fixed in the spec** (sorted `base_library.zip` members, sorted PYZ TOC) rather than excused into the exception set, which is what keeps the set closed and the AC honest.
- AC3 is proven on the real frozen executable with a genuine `--multiprocessing-fork` argv and an inherited pipe, and the docstring explicitly names `test_desktop_sidecar_spike.py`'s monkeypatched precedent as the thing it must not repeat.
- The scanner reads every regular file irrespective of extension, decompresses nested zip members and the executables' embedded PYZ entries, and carries a `bytes_scanned == lstat_bytes` tripwire plus coverage floors — a genuine defense against an early-return or a glob that skips files.
- AC4 asserts the leak was **observed** pre-sanitize (`leak_observed is True`), not merely that the file is absent afterward — a check that would otherwise pass vacuously.
- The `_sysconfigdata` fix is the milestone's best catch: it required understanding that repointing the TOC `src` is insufficient because `PYZ.assemble` reads a pre-compiled object out of `CONF['code_cache']`, and it fails loudly if no `_sysconfigdata` module is ever collected.
- AC2 converts the fixtures in the source venv **within the same test invocation** and hash-compares the bundled symbol table, so it can never degrade into a golden the bundle generated for itself.
- Gate wiring is correct: `requires_desktop_package` is registered in both `pyproject.toml` and `conftest._OPT_IN_MARKERS`, `DESKTOP_PACKAGE_GATE` joins `_DESKTOP_GATE_ENV` so any skip flips the exit status, the `-m` tautology is the established backstopped pattern rather than m5's H3 defect, and the ~150 s of builds stay out of `make test`.
- The commit is GPG-signed, conventional, uses the established `feat(desktop)` scope, and its body volunteers the deferred `executable_identity` limitation instead of hiding it.

Severity counts: C0 H2 M4 L1

## Recommended rectification order

H2, H1, M3, M2, M1, M4, L1
