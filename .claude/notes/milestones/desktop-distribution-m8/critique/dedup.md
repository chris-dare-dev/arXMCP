# Critique (merged) — desktop-distribution-m8

**Critics:** milestone-adversary-critic, milestone-infra-safety-critic
**Commit range:** b3a04fe..954ae99
**Diff stats:** 13 files, 4289 LOC
**Critique format version:** 1.0

> **Merge note.** Each critic authored its ids from 1 within its own file, so
> they collided across files. `findings.py merge` renumbered them into one
> gapless per-severity sequence in critic dispatch order; bodies are verbatim.
> **Phase 4 dispositions attach to the MERGED ids below**, not to the ids in
> the per-critic files. Re-running merge after a critic file changes will shift
> these ids - see milestone-pipeline-critique-format.md.
>
> - `milestone-adversary-critic` (adversary.md): ids unchanged
> - `milestone-infra-safety-critic` (infra-safety.md): M1->M4, M2->M5, M3->M6, M4->M7, L1->L2, L2->L3, L3->L4

## Verdict

**SHIP-WITH-FIXES** — the most severe of the per-critic verdicts below.

### milestone-adversary-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES. The milestone's centrepiece — the AC2-B injection proving the
duplicate OpenMP copy is dangerous rather than merely redundant — holds up under
attack: the abort is pinned to `OMP: Error #15`, the exit status is read from an
unshelled child, and the shipped artifact is re-asserted untouched afterwards.
AC1's exclusion is verified live (no Mach-O in the bundle names `faiss/.dylibs`,
`@rpath/libomp.dylib` resolves through the `_internal` symlink to torch's copy,
and FAISS still does a real add+search). The fixes are one build-portability
break that contradicts a current marker doc, one evidence-vanishing platform
branch, and the mandatory diff-size finding.

### milestone-infra-safety-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES. The build machinery is unusually careful: the TOC exclusion is an exact
normalized-path match rather than a glob, it is backstopped by two independent fail-loud guards
(the spec's "dropped nothing" `SystemExit` and the driver's filesystem `_require_single_libomp`),
the new `server` data collection is derived rather than hand-listed, and the marker is registered
in BOTH `pyproject.toml` and `tests/conftest.py::_OPT_IN_MARKERS` — issue #206's exact bug avoided.
The four MEDIUMs are gate-coverage and latent-foot-gun issues, not correctness bugs in the shipped
artifact: the freeze-side data guard is scoped to `server` only, the AC2-B fault-injection arm
silently reports PASS on Linux, the frozen-child boot proof is reachable only behind the heaviest
prerequisite, and the spec now execs the build driver at spec-eval time.

## Executive summary — milestone-adversary-critic

- [HIGH] `make desktop-package` now hard-fails at spec evaluation on Linux: the
  guard raises when nothing named `faiss/.dylibs/libomp.dylib` was dropped, and
  that path is a macOS delocate convention — while the `requires_desktop_package`
  marker doc in `pyproject.toml` and CLAUDE.md §4.5 both still say "macOS/Linux
  only", unamended.
- [HIGH] Mandatory diff-size auto-finding: 4265 insertions with
  `allow_large_diff: false` in state.json.
- [MEDIUM] The sole AC2-B BEFORE-arm test returns bare off macOS, so it reports
  PASSED having asserted nothing — routing around the `DESKTOP_PACKAGE_GATE`
  zero-skip detector that exists to stop exactly this degradation.
- [MEDIUM] The golden gate never compares `torch_version`, though both the
  fixture's `_provenance` and the probe's output carry it and `pyproject.toml`
  pins torch only as `>=2.0,<3`; a toolchain bump would present as the
  weights-corruption alarm the module docstring instructs the reader to infer.
- [MEDIUM] `state.json`'s frozen `milestone_brief` is the PRE-revision AC set,
  so Phase-4 re-verification reading it judges against superseded criteria.
- [LOW] Three near-copies of one launch contract now disagree on which loader
  overrides are forbidden, and the pinning test checks only element 0.
- Verified clean and NOT reported: the abort's cause (OMP #15 assertion), the
  child-vs-shell exit status, injection side effects on the shipped bundle,
  FAISS functional health after the exclusion, package-data completeness for
  `server`, marker registration in both required places, and that neither new
  gate lands in default `make test`.

## Executive summary — milestone-infra-safety-critic

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

**H1 — Linux desktop-package build breaks on the macOS-only TOC path** (HIGH)

**Where:** `apps/desktop/pyinstaller/arxmcp_desktop.spec:209`
**Anchor:** `if not _dropped_libomp:`
**What:** `DUPLICATE_LIBOMP_DEST` is `faiss/.dylibs/libomp.dylib` — the macOS
delocate layout — so on Linux (where faiss-cpu ships its OpenMP under
`faiss_cpu.libs/libgomp-*.so.N`) `_drop_duplicate_libomp` drops zero entries and
this guard raises `SystemExit`, failing the build before `COLLECT()`.
**Why it matters:** `make desktop-package` and `make desktop-package-check` become
impossible on Linux, while the `requires_desktop_package` marker text in
`pyproject.toml` and its CLAUDE.md §4.5 copy both still assert "macOS/Linux only"
and name only the Windows dependency as the reason — a current doc contradicted
with no update in this diff. `_require_single_libomp` and
`test_bundle_ships_exactly_one_openmp_runtime`'s `_internal/torch/lib/libomp.dylib`
literal carry the same macOS assumption one layer down.
**Proposed fix:** Either (a) make the predicate platform-aware — a
`(darwin -> faiss/.dylibs/libomp.dylib, linux -> faiss_cpu.libs/libgomp-*.so*)`
mapping with the canonical target likewise resolved per-platform — or (b) accept
macOS-only and say so: gate the drop+guard on `sys.platform == "darwin"`, and
amend the marker text in `pyproject.toml` and CLAUDE.md §4.5 plus
`apps/desktop/README.md` the way issue #423 already records `make
desktop-conformance` as macOS-only. (b) is the smaller, more honest change and
also resolves M1. **Uncertainty flagged:** this is read from the delocate/auditwheel
conventions and the bundle on this macOS host, not from an executed Linux build;
if a Linux `make desktop-package` is demonstrated green, invalidate this finding.
**Regression-guard:** a fast (unmarked) test asserting the exclusion predicate
resolves to a non-empty, platform-appropriate destination for both `darwin` and
`linux`, so the mapping cannot silently regress to a single-OS literal.
**Source critic:** milestone-adversary-critic
**Source axis:** correctness / doc drift

**H2 — Diff exceeds 400 LOC with allow_large_diff false** (HIGH)

**Where:** no specific file
**Anchor:** `b3a04fe..954ae99`
**What:** The range changes 4265 insertions / 24 deletions across 13 files;
`state.json:36` records `"allow_large_diff": false`, so the auto-finding applies.
**Why it matters:** Defect-detection rates fall off sharply past ~400 LOC per
review unit; the mandatory finding exists so the size is acknowledged rather
than absorbed.
**Proposed fix:** No code change. Record the arithmetic in the milestone
synthesis and either set `allow_large_diff` deliberately (as m6/m7/m9 did) or
accept the finding as informational. Arithmetic for the record: 3132 of the
insertions are the generated `tests/fixtures/desktop_model/golden_v1.json` and
206 are the `implement/synthesis.md` notes, leaving ~927 hand-written LOC —
still over the threshold.
**Regression-guard:** none; this is a review-quality signal, not a defect.
**Source critic:** milestone-adversary-critic
**Source axis:** diff size (auto-finding)

**M1 — AC2-B's BEFORE arm reports PASSED off macOS having asserted nothing** (MEDIUM)

**Where:** `tests/test_desktop_package.py:597`
**Anchor:** `    if sys.platform != "darwin":`
**What:** `test_a_second_openmp_copy_aborts_the_frozen_process` returns bare on
non-darwin, so the milestone's only proof that the duplicate is dangerous
degrades to a green no-op rather than a visible absence.
**Why it matters:** `DESKTOP_PACKAGE_GATE` exists precisely so evidence cannot
silently vanish from this suite — conftest fails the session on any skip. A bare
`return` routes around that detector and yields a pass. The docstring justifies
it as "the m7 codesign test's platform-branch precedent", but that precedent
(`:657`) is a PARTIAL guard: the test still asserts universally (both executables
exist and are executable) and only the `codesign --verify` step is darwin-scoped.
`:577` is the same partial shape. This is the first whole-body branch in the file.
**Proposed fix:** Convert to `pytest.skip("Mach-O injection; see issue #423")` so
the gate's skip detector sees it, and record the package gate as macOS-only in
`apps/desktop/README.md` beside the existing `desktop-conformance` entry — which
is the same rectification H1 option (b) needs. If a universal assertion is
preferred instead, keep the platform branch but assert the ELF-side invariant
that IS checkable everywhere (exactly one OpenMP regular file, canonical name
resolved per platform).
**Regression-guard:** the conftest gate itself, once the branch is a real skip:
`make desktop-package-check` then fails loudly off macOS instead of passing.
**Source critic:** milestone-adversary-critic
**Source axis:** test discipline

**M2 — Golden comparison ignores the torch version it was measured at** (MEDIUM)

**Where:** `tests/test_desktop_bundled_model.py:219`
**Anchor:** `    assert observed["embedder_revision"] == golde`
**What:** The gate compares both model revisions and the HF cache root but never
`torch_version`, although `tools/desktop_model_probe.py` returns it and the
fixture records `_provenance.torch_version = "2.11.0"`; `pyproject.toml:129`
pins torch only as `>=2.0,<3`.
**Why it matters:** The 1e-6 tolerance is justified against run-to-run variation
on ONE host at ONE torch build. A `uv lock --upgrade` that moves torch (or numpy,
`>=1.24`) can shift float32 CPU reduction order past that tolerance, and the
failure surfaces as `"…drifted by …"` under a module docstring that instructs the
reader that "a vector mismatch otherwise means the weights that loaded are not
the weights intended" — the wrong root cause, on a gate whose whole value is
diagnostic precision. Note the observed toolchain is currently pinned by
`uv.lock`, so this is a latent misdiagnosis rather than a live break, which is
why it is MEDIUM and not HIGH.
**Proposed fix:** Lift `torch_version` (and ideally `numpy.__version__`) to a
top-level fixture key and assert it, or — softer, and enough — include the
golden's and the observed toolchain versions in the drift assertion message so a
failing run names the upgrade as a candidate cause. Amend the module docstring's
"regenerate ONLY when a pinned model revision changes" to cover a toolchain bump.
**Regression-guard:** covered by the assertion/message itself; a fast test can
pin that the fixture carries a toolchain record at all.
**Source critic:** milestone-adversary-critic
**Source axis:** acceptance coverage

**M3 — state.json's frozen brief is the superseded pre-revision AC set** (MEDIUM)

**Where:** `.claude/notes/milestones/desktop-distribution-m8/state.json:32`
**Anchor:** `  "milestone_brief": "### desktop-distribu`
**What:** The stored brief still carries the original AC2 ("The regression MUST
reproduce the documented abort as its RED state before the fix") with no A/B
split and no AC4 greenfield note, while `plans/desktop-distribution-roadmap.md`
was corrected in `b3a04fe` ("docs(notes): correct m8 ACs after measurement") —
the range's own base commit.
**Why it matters:** `milestone-pipeline-resolve-brief.py` reads the roadmap live
and returns the revised text, but any consumer reading state.json directly —
including a Phase-4 re-verification or a later closure review — judges the
implementation against criteria the owner explicitly retired after measurement,
and would wrongly score AC2 as unmet.
**Proposed fix:** Refresh `milestone_brief` in state.json from the resolver
output before Phase 4, or record a one-line `brief_revised_at` pointer to
`b3a04fe` so the staleness is self-evident. Bookkeeping only; no code change.
**Regression-guard:** none required (state bookkeeping).
**Source critic:** milestone-adversary-critic
**Source axis:** acceptance coverage

**M4 — Freeze-side data guard covers `server` only, not the other packaged trees** (MEDIUM)

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

**M5 — AC2-B fault-injection arm reports PASS with zero evidence off macOS** (MEDIUM)

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

**M6 — The only boot-the-frozen-bundle proof sits behind the heaviest prerequisite** (MEDIUM)

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

**M7 — The spec exec's the build driver module at spec-eval time** (MEDIUM)

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

**L1 — Three copies of one launch contract disagree on loader overrides** (LOW)

**Where:** `apps/desktop/pyinstaller/probe_entry.py:63`
**Anchor:** `        if key in FORBIDDEN_ENV or key.startswith`
**What:** `probe_entry.py` rejects any `DYLD_*` or `LD_*` key,
`tools/desktop_model_probe.py:40` rejects `DYLD_*`, `LD_PRELOAD*`, `LD_LIBRARY*`,
and `tools/desktop_sidecar_spike.py:49` rejects only `DYLD_*` — three near-copies
of a contract all three docstrings describe as one.
**Why it matters:** The OpenMP filename regex was correctly recognised as
duplicated and pinned equal by
`test_probe_and_driver_agree_on_the_openmp_filename_pattern`, but that same test
checks only `probe.FORBIDDEN_ENV[0]`, so the env half is free to keep drifting.
`LD_PRELOAD` on the sidecar spike is the concrete gap.
**Proposed fix:** Extend the existing pinning test to assert the full
`FORBIDDEN_ENV` tuple AND the prefix set are identical across all three, or lift
the predicate into one importable helper the two non-frozen callers share (the
frozen probe must keep its copy — it cannot import the driver).
**Regression-guard:** the extended pinning test.
**Source critic:** milestone-adversary-critic
**Source axis:** dead code / leftovers

**L2 — The two FORBIDDEN_ENV validators diverge and the equality test does not pin them** (LOW)

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

**L3 — Frozen-child boot test has no process-group kill and no orphan assertion** (LOW)

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

**L4 — The "dropped nothing" guard sums across both analyses** (LOW)

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

### From milestone-adversary-critic

- The AC2-B injection reproduces the RIGHT failure. `subprocess.run` with no
  shell means `returncode` is the child's wait status (`-signal.SIGABRT`/134,
  both accepted), and `assert "OMP: Error #15" in proc.stderr` discriminates a
  duplicate-OpenMP abort from a corrupted binary, a bad rpath, or any other
  crash — the exact trap the brief warned about.
- The injection is hygienic. `copytree(..., copy_function=os.link)` then an
  explicit unlink-and-rewrite of `_swigfaiss.abi3.so` BEFORE `install_name_tool`
  breaks the shared inode, and the test closes by re-running `otool -L` on the
  SHIPPED binary to prove `@rpath/libomp.dylib` survived and
  `@loader_path/.dylibs/…` did not.
- AC1's exclusion is verified not to have broken FAISS. Independently confirmed
  on the built bundle: no Mach-O names `faiss/.dylibs`, `_swigfaiss.abi3.so`
  carries `LC_RPATH @loader_path/..` resolving `@rpath/libomp.dylib` to the
  `_internal` symlink onto torch's copy, `faiss/.dylibs/` is gone entirely, and
  the AFTER arm asserts a real add+search result
  (`faiss_neighbours == list(range(8))`), not a bare import.
- The AFTER arm reads dyld's live image list rather than a directory listing,
  which is the correct distinction between "present but never mapped" (a
  packaging defect) and "mapped twice" (an abort), and the probe refuses to run
  with `KMP_DUPLICATE_LIB_OK` set so it cannot be a suppressed abort.
- The package-data fix is DERIVED, not enumerated:
  `test_bundle_ships_every_server_data_file_the_wheel_ships` computes the
  expected set from the build venv's installed `server` tree, so a future data
  file cannot drop out of the bundle the way it dropped out of the wheel. The
  bundle carries `router_patterns.yaml`, both `server/schemas/*.json`, and the
  full `frontend/{templates,static}` set; the wheel's remaining package-data
  globs (`ops`, `tools`, `ingest` shell/text assets) are operator-CLI surface
  the frozen child never resolves from its package.
- The `libomp` scan counts FILES, not names: symlinks are reported separately
  and excluded from the copy count, with sha256 identity per regular file, and
  the pattern deliberately covers `libomp.5`, `libiomp5`, `libgomp.so.N` so a
  renamed copy cannot slip a literal check. The negative cases
  (`libompressed.dylib`, `libcompression.dylib`) are tested.
- The spec's TOC-level exclusion is the right mechanism and says why: an
  `install_name_tool` rewrite would invalidate PyInstaller's ad-hoc signatures
  and force a re-sign between the rewrite and the signature gate. Both the
  "dropped nothing" and the "dropped the live copy" failure modes raise.
- Gate placement is correct and complete: `desktop-model-check` is a separate
  `.PHONY` target, `requires_bundled_model` is registered in BOTH
  `pyproject.toml` and `tests/conftest.py:_OPT_IN_MARKERS`,
  `DESKTOP_BUNDLED_MODEL_GATE` is added to `_DESKTOP_GATE_ENV`, and the marked
  tests RAISE rather than skip on a missing bundle or an uncached HF snapshot
  (`HF_HUB_OFFLINE=1` makes an absent pin a failure, not a download).
- The golden fixture is built to be able to FAIL:
  `test_golden_fixture_is_wellformed_and_discriminating` checks 1024-dim
  L2-normalized vectors (an independent property of BGE-M3 output, not a
  restatement of the probe) and a rerank separation of 0.987 vs ~1.6e-5, so a
  mis-loaded model cannot coincidentally match; and the fixture's revisions are
  pinned to the live constants so a bump with a stale golden fails loudly.
- The tolerance is justified rather than fitted: `run_to_run_max_abs_delta: 0.0`
  over 4 runs is recorded in the fixture's `_provenance`, and 1e-6 is stated as
  headroom against the largest observed element (0.252) rather than a margin
  sized to make a drifting assertion pass.
- m7's determinism contract is left intact: `NONDETERMINISTIC_EXCEPTIONS` and
  `EXPECTED_EXCEPTION_COUNT` are untouched, `test_verify_cli_exit_codes` gained a
  fourth case so a second OpenMP copy exits non-zero on the verify path too, and
  the new `probe_analysis` gets the same `_sanitize_sysconfigdata` treatment the
  child already had.

### From milestone-infra-safety-critic

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

Severity counts: C0 H2 M7 L4


## Cross-critic agreement

The following findings cluster within 5 lines of each other in the same file. Multiple critics flagged the same area - these are the strongest signals to fix first.

- **L4, H1** at `apps/desktop/pyinstaller/arxmcp_desktop.spec:205-209` (HIGH): The "dropped nothing" guard sums across both analyses; Linux desktop-package build breaks on the macOS-only TOC path
- **M1, M5** at `tests/test_desktop_package.py:597-597` (MEDIUM): AC2-B's BEFORE arm reports PASSED off macOS having asserted nothing; AC2-B fault-injection arm reports PASS with zero evidence off macOS

## Recommended rectification order

H1, H2, M1, M2, M3, M4, M6, M5, M7, L1, L4, L2, L3

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
