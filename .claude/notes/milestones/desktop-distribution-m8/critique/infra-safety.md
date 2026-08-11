# Critique — desktop-distribution-m8 — milestone-infra-safety-critic

**Critic:** milestone-infra-safety-critic
**Commit range:** b3a04fe..954ae99
**Diff stats:** 13 files, 4289 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES. The build machinery is unusually careful: the TOC exclusion is an exact
normalized-path match rather than a glob, it is backstopped by two independent fail-loud guards
(the spec's "dropped nothing" `SystemExit` and the driver's filesystem `_require_single_libomp`),
the new `server` data collection is derived rather than hand-listed, and the marker is registered
in BOTH `pyproject.toml` and `tests/conftest.py::_OPT_IN_MARKERS` — issue #206's exact bug avoided.
The four MEDIUMs are gate-coverage and latent-foot-gun issues, not correctness bugs in the shipped
artifact: the freeze-side data guard is scoped to `server` only, the AC2-B fault-injection arm
silently reports PASS on Linux, the frozen-child boot proof is reachable only behind the heaviest
prerequisite, and the spec now execs the build driver at spec-eval time.

## Executive summary

- [MEDIUM] `hook-server.py` and its derived guard test cover the `server` package only; `ingest`,
  `ops` and `tools` also declare wheel package-data and have no freeze-side equivalent, so the
  next omission in one of those trees repeats the `11b93e1` class of bug undetected.
- [MEDIUM] `test_a_second_openmp_copy_aborts_the_frozen_process` uses a bare `return` on non-darwin,
  so on Linux the AC2-B "prove the duplicate is dangerous" arm reports `passed` having asserted
  nothing — indistinguishable in gate output from a real pass.
- [MEDIUM] The only test that BOOTS the frozen bundle is `requires_bundled_model`-marked, so
  `make desktop-package-check` still exits green without ever proving the artifact starts — the
  precise m7 gap that `11b93e1` exposed, now closed only in the heavier gate.
- [MEDIUM] `arxmcp_desktop.spec:129` exec's `desktop_package.py` — the build DRIVER, whose job is
  to run `uv`, `rmtree` build trees and invoke PyInstaller — inside the PyInstaller build process.
- [LOW] The two `FORBIDDEN_ENV` validators diverge on their loader-prefix set (`LD_` vs
  `LD_PRELOAD`/`LD_LIBRARY`) and the equality test pins only the regex and `FORBIDDEN_ENV[0]`.
- [LOW] `_stop_process` terminates the direct child only, with no process-group kill and no orphan
  assertion, on the first test that drives the FROZEN (spawn-re-exec) child.
- [LOW] The spec's "dropped nothing" guard sums across both analyses, so a per-analysis regression
  is invisible at the spec layer.
- [CLEAN] Cost and disk: `make test` is untouched (no new prerequisite, no unmarked expensive test);
  `desktop-model-check` adds one bundle (~0.75 GB, and `build_bundle` `rmtree`s the prior one before
  rebuilding, so bundles do not accumulate), the ~4.6 GB of weights stay in the operator's external
  HF cache, and the fault-injection clone is `os.link`-based so it costs one `.so`, not 0.75 GB.
  Peak under `var/desktop-package/` is unchanged from m7 (~1 GB venv + ~0.75 GB bundle);
  `make desktop-package-clean` remains the reclaim path.

## Findings

**M1 — Freeze-side data guard covers `server` only, not the other packaged trees** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/hook-server.py:17`
**Anchor:** `datas = collect_data_files("server")`
**What:** The wheel declares package-data for `server`, `server.schemas`, `server.frontend.*`,
`ingest`, `tools`, `ops`, `ops.cron` and `ops.systemd` (`pyproject.toml:64-80`), but the freeze
boundary has a hook and a derived guard test (`tests/test_desktop_package.py`
`test_bundle_ships_every_server_data_file_the_wheel_ships`) for `server` alone.
**Why it matters:** `11b93e1` was exactly this bug one package over; the next data file added under
`ingest/` or `ops/` that the frozen child reads would be silently absent, and nothing in either new
gate would notice — which is the "does the new gate catch the analogous next omission" question
answered NO for every tree but one.
**Proposed fix:** Either add sibling hooks (`hook-ingest.py`, `hook-ops.py`, `hook-tools.py`) each a
one-line `collect_data_files(...)`, or better, derive both sides from one list: read the package
names out of `[tool.setuptools.package-data]` and loop, so a new packaged tree cannot be added to
the wheel without also being collected into the bundle. Widen
`test_bundle_ships_every_server_data_file_the_wheel_ships` to iterate that same list.
**Regression-guard:** Extend the existing derived test to loop over every top-level package named in
`[tool.setuptools.package-data]` rather than hard-coding `installed / "server"`.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline (build/packaging machinery)

**M2 — AC2-B fault-injection arm reports PASS with zero evidence off macOS** (MEDIUM)

**Where:** `tests/test_desktop_package.py:597`
**Anchor:** `    if sys.platform != "darwin":`
**What:** The "prove the duplicate copy is DANGEROUS, not merely redundant" arm returns early on
non-darwin, so on Linux it is collected, reported `passed`, and asserts nothing.
**Why it matters:** `DESKTOP_PACKAGE_GATE=1` deliberately converts a skip into a session failure so
missing evidence is loud — a bare `return` routes around exactly that mechanism, and a Linux
operator reading `26 passed` cannot tell that the only test proving the m8 exclusion is load-bearing
never ran.
**Why the skip route is the right one:** the conftest guard already exists and would fail the Linux
gate honestly, which is the correct outcome when the platform cannot produce the evidence.
**Proposed fix:** Replace the bare `return` with `pytest.skip("Mach-O only; the ELF equivalent is
not the shipped artifact's failure mode")` and let `_DESKTOP_GATE_SKIPS` fail a Linux gate run; if
a green Linux gate is genuinely wanted, record it explicitly (e.g. `request.node.add_report_section`
or a `record_property("evidence", "unavailable-on-linux")`) so the omission is visible in the report
rather than invisible in a pass.
**Regression-guard:** Optional (MEDIUM). A `record_property` assertion in the gate summary, or a
conftest check that no `requires_desktop_package` test body short-circuits before its first assert.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline (gate evidence integrity)

**M3 — The only boot-the-frozen-bundle proof sits behind the heaviest prerequisite** (MEDIUM)

**Where:** `Makefile:198`
**Anchor:** `desktop-model-check: desktop-package`
**What:** `test_frozen_child_warms_every_model_from_the_external_cache` — the sole test that
actually launches the frozen child and drives it to `/readyz` — is `requires_bundled_model`-marked
and therefore runs only under `make desktop-model-check`, which additionally demands ~4.6 GB of
pre-cached weights under `HF_HUB_OFFLINE=1`. `make desktop-package-check` still never constructs
the app.
**Why it matters:** `11b93e1` is the recorded proof that a packaging gate which never reaches
`create_app()` is a gate that passes on an unbootable bundle; that property is now fixed only in
the gate an operator without both pinned snapshots cached cannot run at all. The derived data-file
test covers the DATA class of that failure in `desktop-package-check`, but a missing hidden import
or a broken runtime hook is caught only in the model gate.
**Proposed fix:** Add a weights-free boot smoke test to `tests/test_desktop_package.py` under
`requires_desktop_package` — launch the frozen child with an env that disables eager model warm-up
(the m5/m6 lifecycle tests already have a non-model path) and assert it handshakes and answers
`/healthz`. The model-output comparison stays where it is; only the "does it start" half moves down
a tier.
**Regression-guard:** Optional (MEDIUM). The new smoke test IS the guard.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline (gate stratification)

**M4 — The spec exec's the build driver module at spec-eval time** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/arxmcp_desktop.spec:129`
**Anchor:** `_helpers = _load_driver_helpers(Path(SPECPATH))`
**What:** `_load_driver_helpers` runs `importlib`'s `exec_module` on `desktop_package.py` — the
driver that provisions the build venv with `uv`, `rmtree`s work/dist trees and shells out to
PyInstaller — from inside the PyInstaller process that driver launched.
**Why it matters:** It is pure today (the module body is constants plus one `len()` assertion), but
the intent "share ONE predicate between build and test" has been bought with a circular import
where any future module-level statement in the driver executes recursively inside its own build,
and the failure would present as an inexplicable nested build or an `rmtree` of the tree being
written.
**Proposed fix:** Move `CANONICAL_LIBOMP` / `DUPLICATE_LIBOMP` / `LIBOMP_PATTERN` /
`is_duplicate_libomp` / `is_canonical_libomp` into a tiny side-effect-free module (e.g.
`apps/desktop/pyinstaller/libomp_policy.py`) that both `desktop_package.py` and the spec import.
The single-source-of-truth property is preserved and the driver is no longer executed by its own
build. Failing that, add a module-level guard in the driver that raises if it is imported under a
name other than `__main__`/`arxmcp_desktop_package`.
**Regression-guard:** Optional (MEDIUM). A test asserting the shared-policy module's top level
contains only assignments and `def`/`class` statements (AST walk), as `tests/test_assert_ban.py`
already does for the `assert` ban.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Open scan (build/packaging machinery)

**L1 — The two FORBIDDEN_ENV validators diverge and the equality test does not pin them** (LOW)

**Where:** `tools/desktop_model_probe.py:40`
**Anchor:** `        if key in FORBIDDEN_ENV or key.startswith(`
**What:** This validator rejects `DYLD_`, `LD_PRELOAD`, `LD_LIBRARY`; `probe_entry.py:63` rejects
`DYLD_` and the broader `LD_`. `test_probe_and_driver_agree_on_the_openmp_filename_pattern` pins the
regex and `FORBIDDEN_ENV[0]` only, so the prefix sets can drift further unnoticed.
**Why it matters:** The two probes are the two halves of the same AC3 claim ("the compute ran with
no loader override"); a narrower set on one side means the golden vectors could be produced under a
loader override the frozen probe would have refused.
**Proposed fix:** Adopt one prefix tuple (the broader `("DYLD_", "LD_")`) in both, and extend the
existing equality test to assert `probe.FORBIDDEN_ENV == model_probe.FORBIDDEN_ENV` and that both
reject `LD_LIBRARY_PATH`.
**Regression-guard:** Optional (LOW).
**Source critic:** milestone-infra-safety-critic
**Source axis:** Open scan (build/packaging machinery)

**L2 — Frozen-child boot test has no process-group kill and no orphan assertion** (LOW)

**Where:** `tests/test_desktop_bundled_model.py:289`
**Anchor:** `        _stop_process(process)`
**What:** `_stop_process` (`tests/test_desktop_child.py:222`) sends `terminate()` then `kill()` to
the direct child only. This is the first test to drive the FROZEN child, whose `freeze_support()`
spawn guard exists precisely because that binary re-execs itself, and unlike m6's cleanup-evidence
probes there is no `lsof`/`ps` assertion afterwards.
**Why it matters:** A surviving re-exec'd worker would hold the runtime dir and, on a repeated gate
run, its loopback port — a class of leak m6 built explicit evidence for and this test does not
inherit.
**Proposed fix:** Launch with `start_new_session=True` and have `_stop_process`'s caller
`os.killpg(os.getpgid(process.pid), SIGTERM)`; or reuse m6's cleanup-evidence probe to assert no
descendant of the bundle path survives the `finally` block.
**Regression-guard:** Optional (LOW).
**Source critic:** milestone-infra-safety-critic
**Source axis:** Open scan (build/packaging machinery)

**L3 — The "dropped nothing" guard sums across both analyses** (LOW)

**Where:** `apps/desktop/pyinstaller/arxmcp_desktop.spec:205`
**Anchor:** `_dropped_libomp = sum(`
**What:** The guard fires only when the TOTAL across `child_analysis` and `probe_analysis` is zero,
so if a future PyInstaller stops collecting `faiss/.dylibs/libomp.dylib` in one analysis but not the
other, the exclusion silently becomes a no-op for that analysis and the `SystemExit` never fires.
**Why it matters:** Low impact only because `_require_single_libomp` inspects the merged bundle on
disk and catches the dangerous direction; the spec-layer guard is nonetheless weaker than its error
message claims.
**Proposed fix:** Assert per-analysis: `dropped = _drop_duplicate_libomp(analysis, _helpers)` inside
the loop and `raise SystemExit` naming the analysis when any one returns 0.
**Regression-guard:** Optional (LOW).
**Source critic:** milestone-infra-safety-critic
**Source axis:** Open scan (build/packaging machinery)

## What was done well

- **The TOC exclusion is exact, not a glob.** `is_duplicate_libomp` normalizes separators and
  compares against one literal destination, and
  `test_libomp_exclusion_predicate_targets_only_the_redundant_copy` explicitly spares
  `torch/lib/libomp.dylib`, bare `libomp.dylib` and `faiss/_swigfaiss.abi3.so`. The named failure
  mode ("a string-match bug drops the LIVE runtime") is the right one to have tested first.
- **The exclusion cannot silently no-op.** Three independent guards: `SystemExit` when nothing was
  dropped, `SystemExit` when dropping would leave no OpenMP in the TOC, and `_require_single_libomp`
  counting real files on disk in both `build_once` and `verify`. If PyInstaller changes its TOC
  shape the build fails loudly rather than passing a filesystem count that only holds until the file
  returns.
- **`LIBOMP_PATTERN` counts the family, not the literal name.** `libomp.5.dylib` / `libiomp5.dylib`
  / `libgomp.so.1` all match, with negative cases (`libompressed.dylib`) pinned; and the pattern is
  held byte-identical between the driver and the frozen probe by a test, because the frozen probe
  cannot import the driver.
- **The `server` data collection is derived, not enumerated.** `collect_data_files("server")` plus a
  guard test that diffs the bundle against the build venv's INSTALLED tree — so within `server`, a
  new data file cannot drop out the way it once dropped out of the wheel (§4.5b, one layer down).
- **Marker registration is complete in both places.** `requires_bundled_model` is in
  `pyproject.toml`'s `markers` AND `tests/conftest.py::_OPT_IN_MARKERS`, and
  `DESKTOP_BUNDLED_MODEL_GATE` was added to `_DESKTOP_GATE_ENV` — the issue-#206 half-registration
  bug and the m5/m7 zero-skip guard both honored without prompting.
- **Neither gate lands in `make test`.** The `test` target is byte-unchanged; the two new fast tests
  in `tests/test_desktop_bundled_model.py` are pure fixture checks, and the expensive work is
  marker-gated behind the m6 findings.json:240 precedent.
- **Recipe-line failure propagation is correct.** Every new recipe line is a single command with no
  `;` chaining or swallowed status, `desktop-model-check: desktop-package` is a real make
  prerequisite (a failed build stops the gate), and both targets are declared `.PHONY`. No `sudo`,
  no destructive default — `desktop-package-clean` remains the only `rm -rf` and it is opt-in.
- **The fault injection is genuinely safe.** It clones with `os.link`, then explicitly breaks the
  hardlink on `_swigfaiss.abi3.so` BEFORE `install_name_tool` touches it (with a comment saying
  exactly why), mutates only inside `tmp_path`, and then re-reads the SHIPPED artifact with `otool`
  to prove `@rpath/libomp.dylib` survived and `@loader_path/.dylibs/…` did not. A failed injection
  is distinguishable from a successful no-crash: the `install_name_tool`/`codesign` exit codes are
  asserted, the abort is asserted as `-SIGABRT`/134 via `subprocess.run` with no shell (so the wait
  status is the child's), AND `OMP: Error #15` must appear in stderr.
- **`subprocess.run(..., timeout=900)` is the right containment for the model probe.** `run` kills
  and reaps the child on both `TimeoutExpired` and any other exception including `KeyboardInterrupt`,
  so an interrupt cannot leave a 4.6 GB model-loading process behind; and the golden fixture is
  never written by the automated path (regeneration is a documented manual command), so no partial
  golden can be produced on interrupt.
- **The tolerance is measured, not chosen to make the assertion pass.** The docstring records four
  probe runs across `OMP_NUM_THREADS` 2/3/4 and both offline and online resolution differing by
  exactly 0.0, and states that loosening `1e-6` requires a re-measurement.

Severity counts: C0 H0 M4 L3

## Recommended rectification order

M1, M3, M2, M4, L3, L1, L2

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed: <finding ids>
- Deferred: <finding ids>
- Invalidated: <finding ids with reasons>
- Regression tests added: <file paths>
