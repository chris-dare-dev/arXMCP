# Critique — desktop-distribution-m8 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** b3a04fe..954ae99
**Diff stats:** 13 files, 4289 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES. The milestone's centrepiece — the AC2-B injection proving the
duplicate OpenMP copy is dangerous rather than merely redundant — holds up under
attack: the abort is pinned to `OMP: Error #15`, the exit status is read from an
unshelled child, and the shipped artifact is re-asserted untouched afterwards.
AC1's exclusion is verified live (no Mach-O in the bundle names `faiss/.dylibs`,
`@rpath/libomp.dylib` resolves through the `_internal` symlink to torch's copy,
and FAISS still does a real add+search). The fixes are one build-portability
break that contradicts a current marker doc, one evidence-vanishing platform
branch, and the mandatory diff-size finding.

## Executive summary

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

## What was done well

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

Severity counts: C0 H2 M3 L1

## Recommended rectification order

H1, M1, M2, M3, L1, H2
