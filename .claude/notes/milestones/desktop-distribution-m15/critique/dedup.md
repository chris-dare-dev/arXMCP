# Critique (merged) — desktop-distribution-m15

**Critics:** milestone-adversary-critic, milestone-arxmcp-critic, milestone-infra-safety-critic
**Commit range:** 525de97..b8c0a1c
**Diff stats:** 17 files, 3308 LOC (3262 insertions, 46 deletions; ~1076 of the insertions are `.claude/` notes + the ADR)
**Critique format version:** 1.0

> **Merge note.** Each critic authored its ids from 1 within its own file, so
> they collided across files. `findings.py merge` renumbered them into one
> gapless per-severity sequence in critic dispatch order; bodies are verbatim.
> **Phase 4 dispositions attach to the MERGED ids below**, not to the ids in
> the per-critic files. Re-running merge after a critic file changes will shift
> these ids - see milestone-pipeline-critique-format.md.
>
> - `milestone-adversary-critic` (adversary.md): ids unchanged
> - `milestone-arxmcp-critic` (arxmcp.md): H1->H2, M1->M7, M2->M8, M3->M9, M4->M10, M5->M11, L1->L3, L2->L4
> - `milestone-infra-safety-critic` (infra-safety.md): H1->H3, M1->M12, M2->M13, M3->M14, M4->M15, M5->M16, L1->L5, L2->L6, L3->L7

## Verdict

**SHIP-WITH-FIXES** — the most severe of the per-critic verdicts below.

### milestone-adversary-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES. The assembly, the two-layout disjunction, the byte-identity
check and the seal are real, measured, and honestly bounded — I attacked the
seal-coverage and dual-layout claims with live `codesign` experiments and both
survived. What does not survive is the gate's own safety mechanism: the
`DESKTOP_BUNDLE_GATE` zero-skip guard that four separate documents (CLAUDE.md,
`pyproject.toml`, the Makefile comment, the test module) assert exists is never
registered in `tests/conftest.py`, so `make desktop-bundle-check` can exit 0
with its evidence skipped — the exact failure mode this milestone was written
to retire. AC3's launch claim is also unproven at the artifact level and is
disclosed as such only in a synthesis note.

### milestone-arxmcp-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES

The assembly, the Decision 2a relocation and the dual-layout resolver are honest, well-measured work, and the two axes most likely to bite — §4.5 marker-table consistency and §4.9 trust language on the seal — are clean on inspection rather than on assertion. The defects are all in the evidence machinery around the artifact rather than in the artifact: the milestone's headline zero-skip guarantee is documented in three places and wired in none, the new notarization-claim scanner exempts ordinary claim sentences, and two evidence reads (a stale `assembly-report.json`, a control-free negative measurement) can report clean for the wrong reason. One ungated test also creates a symlink with no win32 guard, which regresses the 2026-07-12 portability push.

### milestone-infra-safety-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES

The assembly pipeline is correct on its sharpest axis: signing is genuinely bottom-up per-file, `codesign --deep` is absent from every mutating path and AST-pinned as such, the seal now raises rather than shipping an unsealed artifact, and the m7/m8 guards are genuinely re-run over the PLACED tree rather than a stale pre-assembly copy. One HIGH defeats the gate's own contract: `make desktop-bundle-check` exports `DESKTOP_BUNDLE_GATE=1`, but that name was never added to `tests/conftest.py`'s `_DESKTOP_GATE_ENV`, so the zero-skip detector this milestone documents in four places is inert. The remaining findings are build-time supply-chain and cleanup foot-guns, none of which block the artifact.

## Executive summary — milestone-adversary-critic

- [CRITICAL] `DESKTOP_BUNDLE_GATE` is absent from `tests/conftest.py`'s
  `_DESKTOP_GATE_ENV`, so the "any skip fails the session" contract asserted in
  CLAUDE.md:385, `pyproject.toml`, `Makefile:224` and the test module is not
  implemented for m15's gate. One-word fix.
- [HIGH] AC3 ("launches by double-click … reaches a ready server and a rendered
  window") is unproven and untested for the `.app`; the strongest evidence is a
  frozen *probe* subprocess. The gap is disclosed only in
  `implement/synthesis.md`, not in the README or CLAUDE.md.
- [MEDIUM] The README states the outer seal covers "everything below" and the
  code calls the payload tamper-evident; I verified that IS true on this host
  (a one-byte flip in a nested payload Mach-O, including a framework-shaped
  one, makes `codesign --verify --strict` fail) — but nothing in the repo
  measures it. The A/B location control is one arm short of proving it.
- [MEDIUM] `assembly-report.json` is never invalidated: `assemble` raises on
  drift / scan / libomp failures BEFORE writing it, and `_report()` binds the
  file to nothing on disk, so a stale report can be read as current evidence.
- [MEDIUM] The notarization-claim scanner is launderable in its own known
  shapes: appending "and needs no layout change" to a `_MUST_FLAG` sentence
  makes it MISS (measured). Six other realistic claim phrasings also MISS.
- [MEDIUM] AC6 names four guards to re-run over the assembled artifact; m8's
  weights-free assertion is the one not re-run, and the synthesis's AC6 bullet
  drops it without saying so.
- [MEDIUM] `PAYLOAD_MINOS_FLOOR` and the "180 Mach-O: 111/36/33" census are
  hand-recorded and never re-derived; the only assertion touching them compares
  two module constants and is tautological.
- [MEDIUM] The quarantine negative asserts `report == {}` with no
  same-invocation positive control and attributes the refusal to the ad-hoc
  identity without measuring it (`spctl --assess` was never run).

## Executive summary — milestone-arxmcp-critic

- [HIGH] `DESKTOP_BUNDLE_GATE` is absent from `tests/conftest.py::_DESKTOP_GATE_ENV`, so `make desktop-bundle-check`'s advertised zero-skip contract is unimplemented — the exact m7 failure mode the conftest comment above it describes.
- [MEDIUM] The notarization-claim scanner's sentence-level cue set exempts a plain claim containing `no` / `may` / `if` / `must`; four unearned-claim sentences pass, demonstrated below.
- [MEDIUM] `assemble()` never invalidates a prior `assembly-report.json`, so a run that fails after sealing leaves last run's evidence beside this run's `.app` and the gated tests read the stale file.
- [MEDIUM] `TestPlacementDoesNotIntroduceASymlinkRoot` is ungated and calls `symlink_to`, which the repo elsewhere guards with `skipif(sys.platform == "win32")`.
- [MEDIUM] The quarantine negative measurement asserts an empty probe report with no same-run control, so a probe that launched and failed to write is indistinguishable from a blocked launch — the m6 doctrine this repo already wrote down.
- [MEDIUM] CLAUDE.md, `pyproject.toml` and the README all say assembly "raises rather than leaving an unsealed `.app`"; it raises AND leaves it at the canonical path.
- [LOW] `emit_child_plan_probe` discards the write result, so the probe exits 0 having produced nothing.
- [LOW] `_probe`'s stdout path breaks if `DESKTOP_CHILD_PLAN_OUT` is set in the ambient environment.

## Executive summary — milestone-infra-safety-critic

- [HIGH] `DESKTOP_BUNDLE_GATE` is missing from `tests/conftest.py:53`'s `_DESKTOP_GATE_ENV`, so the zero-skip guard that the Makefile, `pyproject.toml`, CLAUDE.md §4.5 and the test module all describe never arms for `make desktop-bundle-check`.
- [MEDIUM] `build_app_shell` hands `tauri build` the full inherited environment; `APPLE_SIGNING_IDENTITY`/`APPLE_CERTIFICATE` being set would make Tauri's own bundler sign the shell, outside this repo's never-`--deep` invariant and with a different identity than the assembler's.
- [MEDIUM] `tauri-cli` is version-pinned, not hash-pinned, while the comment above `desktop_package.py:760` asserts parity with the `--require-hashes` PyInstaller lock; the difference is not stated.
- [MEDIUM] No clean path reclaims the assembled `.app` (~0.75 GB) or the Rust release `target/`; `make desktop-package-clean` reaches only `var/desktop-package/`.
- [MEDIUM] `assembly-report.json` is never invalidated at the top of `assemble()`, so an interrupted run leaves a stale report beside a new partial `.app`, and six gate assertions read the report rather than the artifact.
- [MEDIUM] AC5's byte-identity baseline is taken AFTER pre-signing mutates `var/desktop-package/dist/` in place, so "byte-identical to the artifact `make desktop-package` emitted" is not the property measured.
- [LOW] `ensure_tauri_cli`'s reuse check is a substring match on `--version` output; two further claim-precision issues elsewhere.
- Clean: signing order, `--deep` absence, seal-raises-on-failure, guards over the assembled tree, `make test` unchanged, marker registered in both required places.

## Findings

**C1 — m15's zero-skip gate env var is never registered** (CRITICAL)

**Where:** `tests/conftest.py:53`
**Anchor:** `_DESKTOP_GATE_ENV: tuple[str, ...] = (`
**What:** `_DESKTOP_GATE_ENV` lists `DESKTOP_SUPERVISOR_BIN`, `ARXMCP_FIXTURE_SIDECAR`, `DESKTOP_PACKAGE_GATE` and `DESKTOP_BUNDLED_MODEL_GATE` but NOT `DESKTOP_BUNDLE_GATE`, so `pytest_runtest_logreport` returns early during `make desktop-bundle-check` and no skip is ever recorded or failed on.
**Why it matters:** CLAUDE.md:385, the `requires_desktop_bundle` marker description in `pyproject.toml`, `Makefile:224` ("Same zero-skip mechanism … as desktop-package-check") and `tests/test_desktop_bundle.py:62-63` all assert that any skip fails the session; it does not, and the Makefile's `-m "requires_desktop_bundle or not requires_desktop_bundle"` tautology means a drifted marker name deselects every gated test into a skip while the target still exits 0 — the m6 H3 finding recurring verbatim, in the milestone whose AC9 is "a single committed gate … exercises the assembled artifact".
**Proposed fix:** Add `"DESKTOP_BUNDLE_GATE",` to `_DESKTOP_GATE_ENV` and extend the comment block above it the way m7 and m8 did. Nothing else changes; the reporting hook and `pytest_sessionfinish` already handle it.
**Regression-guard:** A test asserting `"DESKTOP_BUNDLE_GATE" in tests.conftest._DESKTOP_GATE_ENV`, alongside the existing `TestGateWiring` class — better, a derived assertion that every `DESKTOP_*_GATE` env var named in a Makefile recipe appears in `_DESKTOP_GATE_ENV`, which would have caught this and would cover m11–m14's gates too.
**Source critic:** milestone-adversary-critic
**Source axis:** Repo-gate compliance / doc drift

---

**H1 — AC3's launch claim is unproven at the artifact level** (HIGH)

**Where:** `tests/test_desktop_bundle.py:594`
**Anchor:** `    def test_the_placed_payload_still_executes_a`
**What:** The brief's AC3 requires the artifact to "launch by double-click … and reach a ready server and a rendered window with `ARXMCP_DESKTOP_LAUNCH_PLAN` unset"; the strongest evidence in the diff is the frozen *probe* run as a plain subprocess out of the payload, plus a `--print-child-plan` diagnostic that authors no plan and spawns nothing.
**Why it matters:** This is the milestone's headline claim ("makes the double-clickable artifact real") and the prerequisite the roadmap hangs m11–m14 on; leaving it unmeasured means the first genuine double-click is e4's problem, and the failure would surface at exactly the point where nothing else is under test. The two ingredients the synthesis names as blockers are both present on this host — the pinned model revisions are cached (m8's `requires_bundled_model` gate depends on it) and LaunchServices launches are already driven by `TestRelocation` via `open(1)`.
**Proposed fix:** Add one gated test that `open`s the assembled `.app` with no `--args`, polls `http://127.0.0.1:7733/readyz` until ready (or times out), asserts the supervisor owns a native window using the m5/m6 window probe, then quits it; mark it so it can be routed to the model-bearing gate if the weights make it too heavy for `desktop-bundle-check`. If it genuinely cannot run here, record AC3 as PARTIAL in `apps/desktop/README.md` and CLAUDE.md §4.5, not only in `implement/synthesis.md` — a residual that lives in a note the operator never reads is not recorded.
**Regression-guard:** `tests/test_desktop_bundle.py::TestAssembledArtifact::test_double_clicked_app_reaches_a_ready_server`, or an explicit PARTIAL record asserted by the same doc-consistency style test the repo already uses for markers.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

---

**H2 — m15 gate's zero-skip guard is documented but not wired** (HIGH)

**Where:** `tests/conftest.py:53`
**Anchor:** `_DESKTOP_GATE_ENV: tuple[str, ...] = (`
**What:** The tuple lists `DESKTOP_SUPERVISOR_BIN`, `ARXMCP_FIXTURE_SIDECAR`, `DESKTOP_PACKAGE_GATE` and `DESKTOP_BUNDLED_MODEL_GATE` but not `DESKTOP_BUNDLE_GATE`, which `Makefile:229` exports; `git grep DESKTOP_BUNDLE_GATE` at the tip finds it only in the Makefile, CLAUDE.md, `pyproject.toml`, the m15 notes and `tests/test_desktop_bundle.py:74` — never in the guard.
**Why it matters:** CLAUDE.md §4.5, the `requires_desktop_bundle` registration in `pyproject.toml:376` and `Makefile:226` each state that `DESKTOP_BUNDLE_GATE=1` makes any skip fail the session. It does not. The Makefile's `-m "requires_desktop_bundle or not requires_desktop_bundle"` is a tautology for any token, so a drifted marker name or a `pytest.skip` inside a gated test degrades the gate to a green run with the evidence missing — verbatim the m7 degradation the comment at `tests/conftest.py:49` says `DESKTOP_PACKAGE_GATE` was added to prevent.
**Proposed fix:** Add `"DESKTOP_BUNDLE_GATE"` to `_DESKTOP_GATE_ENV` and extend the comment block above it with the m15 sentence, mirroring the m7/m8 lines.
**Regression-guard:** In `tests/test_desktop_bundle.py::TestGateWiring`, assert `"DESKTOP_BUNDLE_GATE" in tests.conftest._DESKTOP_GATE_ENV` — a source-derived check, so the doc claim and the mechanism cannot drift again.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

---

**H3 — desktop-bundle-check's zero-skip guard is never armed** (HIGH)

**Where:** `tests/conftest.py:53`
**Anchor:** `_DESKTOP_GATE_ENV: tuple[str, ...] = (`
**What:** `Makefile:228` runs the m15 gate with `DESKTOP_BUNDLE_GATE=1`, but the diff added `requires_desktop_bundle` only to `_OPT_IN_MARKERS` and never added `DESKTOP_BUNDLE_GATE` to `_DESKTOP_GATE_ENV`, whose members are `DESKTOP_SUPERVISOR_BIN`, `ARXMCP_FIXTURE_SIDECAR`, `DESKTOP_PACKAGE_GATE` and `DESKTOP_BUNDLED_MODEL_GATE` — none of which `desktop-bundle-check` sets.
**Why it matters:** `pytest_runtest_logreport` returns early when no member is present, so `_DESKTOP_GATE_SKIPS` stays empty and `pytest_sessionfinish` never fails the session; the `-m "requires_desktop_bundle or not requires_desktop_bundle"` expression is a tautology for any token, so a drifted marker name or a `pytest.skip` inside the gated half would let `make desktop-bundle-check` exit 0 with the artifact evidence silently absent. This is the same failure class the m5 critique's H3 already closed once for m6 and m7, and it makes the implementer-reported "62 passed zero skips" an unenforced human read rather than a mechanism.
**Proposed fix:** Add `"DESKTOP_BUNDLE_GATE",` to the `_DESKTOP_GATE_ENV` tuple at `tests/conftest.py:53-58` and extend the adjacent comment the way `DESKTOP_PACKAGE_GATE` and `DESKTOP_BUNDLED_MODEL_GATE` were.
**Regression-guard:** A test that derives the expected set from the Makefile rather than restating it: parse every `DESKTOP_[A-Z_]*_GATE=1` assignment out of the Makefile's recipe lines and assert each is a member of `conftest._DESKTOP_GATE_ENV`. That makes the next gate target unable to land with an inert guard.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M1 — the seal's coverage of the payload is claimed but never measured** (MEDIUM)

**Where:** `apps/desktop/README.md:84`
**Anchor:** `        _CodeSignature/                  the ou`
**What:** The README says the outer seal is "over everything below", `seal_app`'s docstring justifies the whole pre-sign→place→seal ordering with "the shell's seal covers the payload's final bytes", and the intro calls every signature "tamper-evident locally" — but the only assertions are that `codesign` exited 0 and reports "valid on disk", which is a property of the signature, not of its coverage.
**Why it matters:** e4 inherits these sentences as the layout's evidence, and coverage is a property of `codesign`'s default resource rules rather than of anything this repo controls — a future `--resource-rules`/entitlement change, or a payload path that lands under an omitted rule, would leave the same three sentences reading true while the seal covered nothing. I built the counterexample and it did NOT reproduce: on macOS 26 a one-byte flip in a pre-signed nested Mach-O under `Contents/Resources/payload/`, and the same flip inside a framework-shaped `Python.framework/Versions/A/Python`, both make `codesign --verify --strict` on the bundle fail with "file modified" — so the claim is TRUE today and this is a missing-measurement finding, not a wrong-claim one.
**Proposed fix:** Extend `measure_macos_seal_location_control` with a third arm (or add `measure_seal_covers_resources`) that seals the throwaway control app, flips one byte in its `Contents/Resources/payload/` Mach-O, and records that `codesign --verify --strict` then fails — same synthetic, host-re-derivable shape as the existing A/B, no 0.75 GB copy needed. Assert both arms in `TestOuterSeal`.
**Regression-guard:** `TestOuterSeal::test_the_seal_detects_payload_tampering` over the synthetic control app.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness / evidence discipline

---

**M2 — a failed assembly leaves the previous run's report readable as current** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:1251`
**Anchor:** `    (root / "assembly-report.json").write_text(`
**What:** `assemble` never removes `assembly-report.json` on entry, and three failure paths — the manifest-drift raise, `_require_scan_coverage`, `_require_single_libomp` — raise BEFORE the write, so the file left on disk describes an earlier, different artifact; `tests/test_desktop_bundle.py:435`'s `_report()` reads it with no check that `report["app"]` is the artifact under test or that it is newer than the bundle.
**Why it matters:** Every `TestOuterSeal` and `TestAssembledArtifact` assertion about signing counts, seal status, byte-identity, the string scan and the libomp inventory is read out of that file, so a stale report makes all of them pass against evidence for a bundle that no longer exists — the "evidence must describe the artifact on disk" discipline this milestone is built on. The comment at `:1262` ("The report is on disk BEFORE this raises") is true only for the seal path.
**Proposed fix:** `(root / "assembly-report.json").unlink(missing_ok=True)` as the first statement after the platform/onedir preconditions, and in `_report()` assert `report["app"] == str(_app())` plus `report_path.stat().st_mtime >= (app / "Contents" / "Info.plist").stat().st_mtime`.
**Regression-guard:** A test that writes a bogus `assembly-report.json`, runs `assemble` far enough to hit a raise, and asserts the file is gone.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

---

**M3 — one stray cue word disables the notarization-claim scanner** (MEDIUM)

**Where:** `tests/test_desktop_notarization_claims.py:95`
**Anchor:** `_DISCLAIM_CUES = re.compile(`
**What:** The cue is matched anywhere in the sentence, and the cue set includes `no`, `not`, `must`, `may`, `open`, `if`, `would`, `whether` — so appending an unrelated clause launders a claim the module's own `_MUST_FLAG` corpus says must fire.
**Why it matters:** AC2 requires "a regression fails on such a claim"; I imported the module and ran it — `"The artifact is ready for notarization and needs no layout change."` returns MISS while the same sentence without the trailing clause is `_MUST_FLAG` entry 4. Six more realistic phrasings also MISS: "ready to ship to Apple's notary", "will notarize as-is", "should notarize without further work", "signed and ready for distribution", "Assembly produces a notarizable .app", "satisfies Apple's notarization requirements". The docstring's honest hedge ("no claim in the known shapes") does not cover a bypass of the known shapes. This is the m9 lesson recurring (a guard calibrated to the phrasings it was demoed against).
**Proposed fix:** Require the cue to occur BEFORE the match position within the sentence (`_DISCLAIM_CUES.search(sentence[:match.start()])`). I checked this against the committed corpus: it preserves all nine `_MUST_NOT_FLAG` entries (every one carries its cue ahead of the claim) and kills the counterexample. Then add the laundered sentence and 2–3 of the missed phrasings to `_MUST_FLAG`.
**Regression-guard:** `_MUST_FLAG` gains `"The artifact is ready for notarization and needs no layout change."` and `"The app bundle will notarize as-is."`
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage / test discipline

---

**M4 — AC6's weights-free assertion is the one guard not re-run** (MEDIUM)

**Where:** `tests/test_desktop_bundle.py:540`
**Anchor:** `    def test_m7_and_m8_guards_hold_over_the_asse`
**What:** AC6 names four things to re-run over the assembled artifact — m7's determinism/`direct_url.json`/string scan, and "m8's single-`libomp` guard and weights-free assertion"; the test re-runs the first three and the libomp inventory, and never checks for weight files, while `implement/synthesis.md`'s AC6 bullet lists only three and does not disclose the omission.
**Why it matters:** m8's weights-free check (`tests/test_desktop_bundled_model.py:182`, `WEIGHT_SUFFIXES` + `models--`/`blobs` cache trees) runs only under `requires_bundled_model`, which `make desktop-bundle-check` never invokes, so no run of the m15 gate would notice a 4.6 GB HF cache tree landing inside `Contents/Resources/`. The byte-identity assertion (AC5) is a genuine partial steelman — the placed payload equals the onedir — but it says nothing about the rest of the `.app`, and it makes m15's coverage depend on a gate with a 4.6 GB external prerequisite.
**Proposed fix:** Add ~10 lines to the same test: `rglob` the whole `_app()` (not just the payload) for `WEIGHT_SUFFIXES`/`pytorch_model*` and for `models--*`/`blobs` directories, assert empty, and keep m8's `files_walked` tripwire so a broken walk cannot read as clean. Import the suffix tuple from `test_desktop_bundled_model` rather than re-typing it.
**Regression-guard:** the assertion above, inside `test_m7_and_m8_guards_hold_over_the_assembled_payload`.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

---

**M5 — the payload-wide minos census is asserted only against itself** (MEDIUM)

**Where:** `tests/test_desktop_bundle.py:592`
**Anchor:** `        assert PAYLOAD_MINOS_FLOOR < FLOOR`
**What:** `PAYLOAD_MINOS_FLOOR = "11.0"` and its documented census ("180 Mach-O files: 111 at 14.0, 36 at 12.0, 33 at 11.0", repeated at `apps/desktop/README.md:148`) are hand-recorded constants; the single use is a comparison of two module-level string literals, which is true at import time regardless of the artifact.
**Why it matters:** The milestone's own standard is measured-not-inferred, and the two-declared-floors record is the thing m9's discipline is being applied to here; a census nothing re-derives goes stale exactly the way this repo's cap comments and pair inventories have (m6/m8/m10/m12). The comparison is also lexicographic, so it would silently keep passing if the floor ever moved to a single-digit major.
**Proposed fix:** In the gated class, derive the census from the artifact — `dp.macho_inventory(_payload())` is already available — build a `Counter` of `min(_declared_minos(p))`, assert the total Mach-O count and that the minimum equals `PAYLOAD_MINOS_FLOOR`, and compare versions as tuples (`tuple(map(int, v.split(".")))`) rather than as strings. Note in the failure message that a change means re-recording the README census in the same commit.
**Regression-guard:** `TestAssembledArtifact::test_payload_minos_census_is_re_derived`.
**Source critic:** milestone-adversary-critic
**Source axis:** Test discipline

---

**M6 — the quarantine negative has no in-invocation control and its attribution is inferred** (MEDIUM)

**Where:** `tests/test_desktop_bundle.py:788`
**Anchor:** `    def test_quarantine_blocks_the_launch_so_tra`
**What:** The test asserts `report == {}`, and `_probe(use_open=True)` returns `{}` for ANY reason the output file fails to appear within its 40 s poll — a slow host, a LaunchServices hiccup, a bad `open` argument — while the docstring and `apps/desktop/README.md` conclude, without measuring it, that the remaining refusal is the ad-hoc identity.
**Why it matters:** Asserting a negative with a probe that cannot distinguish "Gatekeeper refused" from "the probe did not run" is the same class as m6's `lsof` finding: it entrenches an assumption inside a green run. The attribution is cheap to measure and was not — `spctl --assess --type execute -vv <app>` reports the rejection source directly, and `log show --predicate 'subsystem == "com.apple.syspolicy"'` narrows it further.
**Proposed fix:** Give the test a same-invocation positive control: `ditto` the bundle, probe it un-quarantined (must return a report), then `xattr -w` quarantine on the SAME staged copy and probe again (must return `{}`). Add an `spctl --assess` call and assert on its recorded verdict string so the "it is the ad-hoc identity" sentence in the README and the docstring is a measurement rather than an elimination argument.
**Regression-guard:** the positive-control half of the same test.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness / evidence discipline

---

**M7 — notarization scanner exempts ordinary claim sentences** (MEDIUM)

**Where:** `tests/test_desktop_notarization_claims.py:95`
**Anchor:** `_DISCLAIM_CUES = re.compile(`
**What:** The cue set includes `no`, `not`, `may`, `must`, `if`, `open`, `would`, `question`, and it is applied at SENTENCE granularity, so any claim sentence containing one of those very common words is skipped entirely. Executed against the module at this commit, `_find_unearned_claims` returns `[]` for all four of: "The assembled bundle is notarization-ready, so no further work is needed."; "The bundle has been notarized and may now be shipped."; "Code signing works, if you have the certificate."; "arXMCP.app is Gatekeeper-ready and must be shipped as-is."
**Why it matters:** This is the gate that enforces ADR Decision 3 and §4.9's rule against collapsing "sealed" into "notarizable" — the one axis this milestone must not get wrong. The module's docstring says "the controls below are what bound it", but every `_MUST_FLAG` sentence at `:143` is cue-free, so the controls prove nothing about the exemption's width.
**Proposed fix:** Keep the sentence window only for the meta-statement shape it exists for: require the cue to appear BEFORE the claim match within the sentence, and drop the generic modals (`may`, `must`, `if`, `would`) from the cue set. The ADR's real meta-statements retain `no` / `not` / `whether` and still pass.
**Regression-guard:** Add the four sentences above to `_MUST_FLAG` so `TestScannerControls::test_flags_a_claim` fails against the current cue set.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

---

**M8 — a stale `assembly-report.json` can be read as this run's evidence** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:1251`
**Anchor:** `    (root / "assembly-report.json").write_text(`
**What:** `assemble()` writes the report only at the very end, after `_require_scan_coverage`, `_require_single_libomp` and the `scan["hits"]` check (`:1232`–`:1249`) have already had their chance to raise, and it never removes a pre-existing report at entry. `build_app_shell` does `rmtree` the `.app`, so a run that seals and then fails the scan leaves this run's `.app` on disk next to the PREVIOUS run's report.
**Why it matters:** `tests/test_desktop_bundle.py::_report()` only checks that the file exists. `TestOuterSeal` and `test_placed_child_is_byte_identical_to_the_onedir` read `signing`, `seal`, `seal_location_control`, `signature_stability` and `scan` from it. `make desktop-bundle-check` is protected by make's dependency ordering, but the marker registration and CLAUDE.md §4.5 both advertise bare `pytest -m requires_desktop_bundle` as an equivalent entry point, and that path has no freshness check at all.
**Proposed fix:** `unlink(missing_ok=True)` the report as the first statement of `assemble()`, and record the `.app`'s resolved path plus its `Contents/_CodeSignature/CodeResources` digest in the report so a reader can bind report to artifact.
**Regression-guard:** A gated test asserting `Path(_report()["app"]).resolve() == _app().resolve()` and that the recorded `CodeResources` digest matches the artifact on disk.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

---

**M9 — ungated test creates a symlink with no win32 guard** (MEDIUM)

**Where:** `tests/test_desktop_bundle.py:386`
**Anchor:** `        (payload / "_internal" / "link").symlink_to("data")`
**What:** `TestPlacementDoesNotIntroduceASymlinkRoot::test_placed_root_is_a_real_directory` carries no marker and no `skipif`, so it runs on every `make test` on every platform and creates a symlink, which Windows refuses without Developer Mode or `SeCreateSymbolicLinkPrivilege`.
**Why it matters:** CLAUDE.md §3 records `make test` being measured on Windows 11, and the 2026-07-12 portability push explicitly GUARDED nine symlink-creation tests rather than letting them fail; `tests/test_desktop_data_root_spike.py:229` is the in-repo precedent (`skipif(sys.platform == "win32", reason="symlink privilege varies")`). The gate results for this milestone were measured on macOS only, so this regression is unmeasured rather than absent.
**Proposed fix:** Add `@pytest.mark.skipif(sys.platform == "win32", reason="symlink privilege varies")`, matching the precedent. Alternatively split the symlink-preservation assertion into its own guarded test and leave the `place_payload` destination/`is_symlink` assertions running everywhere.
**Regression-guard:** Optional (MEDIUM).
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

---

**M10 — the quarantine negative measurement has no same-run control** (MEDIUM)

**Where:** `tests/test_desktop_bundle.py:813`
**Anchor:** `        assert report == {}, (`
**What:** `test_quarantine_blocks_the_launch_so_translocation_is_unverified` concludes "the quarantined bundle did not launch" from `_probe(..., use_open=True)` returning `{}`, which `_probe` returns whenever the output file is simply absent after its 40 s poll. A supervisor that DID launch but whose `fs::write` failed (`apps/desktop/crates/supervisor/src/main.rs:498` discards the result) produces exactly the same `{}`.
**Why it matters:** This is the single test that keeps the translocation gap visible in a green run, and `apps/desktop/README.md`'s "Gatekeeper path translocation is UNVERIFIED" claim rests on it. The repo's own m6 doctrine, restated in `apps/desktop/README.md`, is that "a failed or partial probe is an evidence failure and never clean absence" and that every absence query must ride a same-run control. This one does not — the positive arm lives in a different test with a different `tmp_path`.
**Proposed fix:** Inside the same test, first run the UN-quarantined staged copy through `_probe(..., use_open=True)` and require a non-empty report, then apply `com.apple.quarantine` to that same copy and require `{}`. That makes the write mechanism a same-run control for the absence.
**Regression-guard:** The added positive arm IS the guard; it fails if the `open(1)`/argv[2] write path breaks.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

---

**M11 — "raises rather than leaving an unsealed `.app`" is not what the code does** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:1261`
**Anchor:** `        raise BuildError(`
**What:** On a failed outer seal `assemble()` raises, but the unsealed `.app` stays at `app_bundle_path()`; nothing removes or marks it. CLAUDE.md §4.5 ("assembly raises rather than leaving an unsealed `.app`"), `pyproject.toml:376` (same words) and `apps/desktop/README.md` ("assembly RAISES rather than leaving an unsealed `.app` on disk") all state the stronger property.
**Why it matters:** `tests/test_desktop_bundle.py::_app()` accepts any directory at that path, so combined with M2 the residue is reachable by the documented bare-`pytest` entry point. More narrowly it is a §4.9-shaped inaccuracy: three documents assert an artifact does not exist when it does.
**Proposed fix:** Either `shutil.rmtree(app)` before the raise and say so in the message, or reword all three documents to the true claim — "assembly raises and leaves the unsealed `.app` in place for inspection; it is never a shippable artifact."
**Regression-guard:** Optional (MEDIUM). If the rmtree route is taken, a unit test that monkeypatches `seal_app` to report `sealed=False` and asserts the `.app` is gone after the raise.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

---

**M12 — tauri build inherits an environment that can silently activate Tauri's own signing** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:996`
**Anchor:** `        [str(cli), "build"],`
**What:** `build_app_shell` passes `env=dict(os.environ)` to `tauri build` with no guard, and Tauri's macOS bundler signs the produced `.app` at build time whenever `APPLE_SIGNING_IDENTITY` / `APPLE_CERTIFICATE` are present in the environment.
**Why it matters:** The never-`--deep` invariant is enforced only over this repo's own code — `test_deep_never_appears_in_a_signing_command` walks the AST of exactly `sign_file`, `presign_payload` and `seal_app`. Tauri's bundler is outside that scope and signs the app bundle with its own flags, so an operator who exports a signing identity gets a shell signed by a second actor with a second identity, invisibly to every assertion in the gate. This is not a theoretical shell: e4's notarization trial is the moment those exact variables get exported.
**Proposed fix:** Refuse loudly rather than inherit. In `build_app_shell`, raise `BuildError` when any of `APPLE_SIGNING_IDENTITY`, `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD` is set (pointing at `CODESIGN_IDENTITY_ENV` as the supported knob), or strip them from the child environment. Decision 1 step 3 says the bundler builds the shell only; this is the enforcement of it.
**Regression-guard:** Unit test that monkeypatches `APPLE_SIGNING_IDENTITY` into the environment and asserts `build_app_shell` raises before `_run` is reached, or that the env dict handed to `_run` does not contain it.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M13 — tauri-cli is version-pinned, not hash-pinned, and the difference is unstated** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:760`
**Anchor:** `TAURI_CLI_VERSION = "2.11.4"`
**What:** The comment above this line says the pin is "like every other link in this chain" and cites `requirements-build.txt`'s `--require-hashes` alongside it, but `cargo install --locked --version` records no digest anywhere in this repo; integrity rests entirely on whichever registry `cargo` resolves at build time, and `--locked` fixes only the CLI's own transitive resolution, not the top-level crate's bytes.
**Why it matters:** §4.9's rule against a claim that collapses distinct questions applies to build provenance too. A reader comparing the two mechanisms is told they are equivalent when one records a hash in-tree and the other does not; the gap is real for a registry-source replacement in `.cargo/config.toml` or a `CARGO_REGISTRIES_*` override, and `cargo install` additionally executes the build scripts of the whole tauri-cli dependency tree on this host.
**Proposed fix:** Restate the comment honestly — version-and-lock pinned, with integrity delegated to the registry index's checksums, NOT hash-pinned in-tree the way `requirements-build.txt` is — and record the observed `cargo-tauri --version` string plus the crate's `.crate` sha256 next to the pin so drift is detectable. Extend `TestToolchainPinning` to assert the comment names the distinction.
**Regression-guard:** Optional at MEDIUM; the `TestToolchainPinning` addition above doubles as one.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M14 — no clean path reclaims the assembled .app or the Rust release target** (MEDIUM)

**Where:** `Makefile:234`
**Anchor:** `desktop-package-clean:`
**What:** `desktop-package-clean` is `rm -rf var/desktop-package`, but m15's ~0.75 GB `.app` is written to `apps/desktop/target/release/bundle/macos/`, alongside a full Rust release `target/` tree that the first `tauri build` also creates. Nothing in the diff adds a `desktop-bundle-clean` target and `Makefile:106`'s help text still describes only the `var/desktop-package/` footprint.
**Why it matters:** The single documented reclaim verb now under-reports the milestone's disk cost by roughly a second copy of the payload plus the Rust build tree, on a machine where the `requires_desktop_package` marker text already advertises ~2.5 GB at the m7 peak. An operator following the documented cleanup path recovers less than they were told they would.
**Proposed fix:** Add a `desktop-bundle-clean` target (`rm -rf apps/desktop/target/release/bundle var/desktop-package/assembly-report.json`), list it in `help`, and amend `Makefile:106` plus the `requires_desktop_bundle` marker text to name where the assembled bundle actually lands. Note in the `desktop-package-clean` comment that it now also discards `tauri-cli`, forcing a several-minute network recompile on the next `make desktop-bundle`.
**Regression-guard:** Optional at MEDIUM.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M15 — a stale assembly-report.json can outlive the artifact it describes** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:1251`
**Anchor:** `    (root / "assembly-report.json").write_text(`
**What:** `assemble()` writes the report only at the very end and never removes a previous one at the top, while `build_app_shell` rmtrees and rebuilds the `.app` early in the same run. An interrupt or a `tauri build` failure between those two points leaves the previous run's report on disk next to a missing or partial bundle.
**Why it matters:** Six of the gated assertions read `_report()` rather than the artifact — `test_every_nested_macho_was_signed`, `test_the_outer_seal_succeeded_and_verifies`, `test_placed_child_is_byte_identical_to_the_onedir`, `test_m7_and_m8_guards_hold_over_the_assembled_payload`, `test_the_location_control_separates_layout_from_payload` and `test_ad_hoc_signing_is_byte_stable` — so a direct `DESKTOP_BUNDLE_GATE=1 pytest` run (the path H1 leaves unguarded) can grade a new partial artifact against an old run's evidence. `test_the_seal_is_verified_against_the_artifact_not_the_report` exists precisely because the author saw this class; it currently covers one assertion of the set.
**Proposed fix:** Unlink `root / "assembly-report.json"` as the first statement of `assemble()`, and stamp the report with the app's own identity (its path plus the sha256 of `Contents/MacOS/<CFBundleExecutable>`) so `_report()` can assert the report describes the bundle on disk before any assertion is built on it.
**Regression-guard:** Optional at MEDIUM.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M16 — AC5's byte-identity baseline is the post-signing onedir, not m7's artifact** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:1211`
**Anchor:** `    signed_manifest = file_manifest(payload_root)`
**What:** `presign_payload` at `:1209` signs the ~180 nested Mach-O files in place inside `var/desktop-package/dist/`, and the manifest baseline is taken on the line after. `Makefile:217` and CLAUDE.md §4.5 both describe the result as byte identity with "the artifact `make desktop-package` emitted"; the artifact that gate emitted no longer exists on disk by the time the comparison happens.
**Why it matters:** What is measured is copy fidelity from signed-onedir to placed-payload — real and worth keeping, since it catches a substituted or rebuilt child — but it is strictly weaker than the stated claim, and it also means m7's `report.json` and its determinism manifest no longer describe the tree sitting at `dist/` after any `make desktop-bundle`. Under §4.9's discipline the prose should not carry more than the measurement does.
**Proposed fix:** Capture `file_manifest(payload_root)` BEFORE `presign_payload` as well, record both in `assembly-report.json` as `onedir_manifest_presign` / `onedir_manifest_postsign`, and assert the pre-sign manifest's path set matches m7's. Then correct `Makefile:217` and the CLAUDE.md §4.5 sentence to say identity with the pre-signed onedir plus a signing-only delta, rather than identity with the m7 artifact.
**Regression-guard:** Optional at MEDIUM.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**L1 — CLAUDE.md is pinned OUT of the notarization-claim scan** (LOW)

**Where:** `tests/test_desktop_notarization_claims.py:207`
**Anchor:** `        assert REPO_ROOT / "CLAUDE.md" not in fi`
**What:** The scan set excludes `CLAUDE.md`/`AGENTS.md` and asserts the exclusion, so the file every agent in this repo reads at session start — and which this diff gave a 45-line description of the bundle, its seal and its translocation status — can never trip the AC2 guard.
**Why it matters:** AC2's wording is "no document, string, or acceptance claim"; the m9 precedent for excluding agent docs is real, but here the excluded file is the largest single prose description of the artifact the diff produced, and the exclusion is pinned by an assertion rather than left as a default.
**Proposed fix:** Either include `CLAUDE.md` in `scanned_files()` (it is already clean today — I read the added §4.5 block) or downgrade the assertion to a comment explaining the m9 inheritance so a later widening is not blocked by a test.
**Regression-guard:** optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

---

**L2 — inside a bundle the resolver still falls back to Decision 2's abandoned location** (LOW)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:383`
**Anchor:** `    candidates.push((LAYOUT_SUPERVISOR_SIBLING`
**What:** The sibling candidate is pushed unconditionally, so a supervisor at `Contents/MacOS/` whose `Contents/Resources/arxmcp-desktop-child/` is absent selects `Contents/MacOS/arxmcp-desktop-child/` — precisely the location Decision 2a abandoned — and that arm has no test in either language.
**Why it matters:** Precedence when BOTH roots exist IS tested and correct (`the_bundle_arm_wins_when_both_roots_exist`, and `test_the_bundle_arm_wins_over_a_stray_macos_payload` against the real binary), which is the dangerous direction; this is the residual one. It is genuinely small — a payload at that location makes the bundle unsealable, so no sealed artifact can carry one, and anyone who can create it already has write access to the payload directory (residual risk 1). Recording it rather than closing it is defensible; leaving it unstated is what makes it a finding.
**Proposed fix:** Either skip the sibling candidate when `in_bundle_macos` is true (one `if`), or add a Rust unit test naming the behaviour (`a_bundle_with_no_resources_payload_falls_back_to_the_macos_sibling`) plus a sentence in `child_payload_candidates`' doc comment, so the fallback is a recorded decision rather than an artifact of the push order.
**Regression-guard:** optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**L3 — the probe's file write cannot fail loudly** (LOW)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:498`
**Anchor:** `            let _ = fs::write(PathBuf::from(path), t`
**What:** The write result is discarded and `main` then exits 0, so a probe invocation that could not write its destination is indistinguishable from one that never ran.
**Why it matters:** It is the mechanism behind M4 and it makes every `use_open=True` measurement one-sided. Non-fatal is right for a diagnostic; exit 0 is the wrong signal.
**Proposed fix:** On `Err`, print the report to stderr and `std::process::exit(3)`; keep exit 0 for a successful write or the stdout path.
**Regression-guard:** Optional (LOW).
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

---

**L4 — `_probe`'s stdout path is sensitive to an ambient env var** (LOW)

**Where:** `tests/test_desktop_bundle.py:459`
**Anchor:** `    proc = subprocess.run(`
**What:** The non-`open` branch passes no argv[2], so `emit_child_plan_probe` falls back to `DESKTOP_CHILD_PLAN_OUT`. If that variable is set in the operator's shell the probe writes a file, stdout is empty and `json.loads(proc.stdout)` raises with an opaque error.
**Why it matters:** Small, but the whole family of `DESKTOP_*` non-`ARXMCP_`-prefixed vars exists precisely because operators do set them in this project.
**Proposed fix:** Pass an explicit `env=` with `DESKTOP_CHILD_PLAN_OUT` removed, or always pass an explicit argv[2] and read the file in both branches.
**Regression-guard:** Optional (LOW).
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**L5 — the tauri-cli reuse check is a substring match** (LOW)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:851`
**Anchor:** `        if proc.returncode == 0 and TAURI_CLI_VER`
**What:** `TAURI_CLI_VERSION in proc.stdout` accepts any output containing `2.11.4` as a substring, including `2.11.40` or `12.11.4`.
**Why it matters:** A cached binary at a neighbouring version would be silently reused as "the pin", defeating the point of the `--root`-isolated install.
**Proposed fix:** Match the version as a whole token — `re.search(rf"\b{re.escape(TAURI_CLI_VERSION)}\b", proc.stdout)` — or compare the parsed trailing field of `cargo-tauri <version>` exactly.
**Regression-guard:** Optional at LOW.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**L6 — the shipped supervisor writes JSON to an argv-supplied path** (LOW)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:494`
**Anchor:** `        .nth(2)`
**What:** `emit_child_plan_probe` writes its report to whatever path `argv[2]` names, with no containment check, in the binary that ships inside the `.app`.
**Why it matters:** Any local process that can call `open -a arXMCP.app --args --print-child-plan <path>` overwrites that file with JSON under the user's identity. It confers no privilege the caller does not already have, which is why this is LOW — but it is an unbounded write in a shipped diagnostic, and the containment discipline `resolve_inside()` applies two functions away is not applied here.
**Proposed fix:** Restrict the destination to an existing directory the caller already owns, or drop the `argv[2]` form in favour of `DESKTOP_CHILD_PLAN_OUT` alone once the translocation measurement no longer needs argv.
**Regression-guard:** Optional at LOW.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**L7 — macho_inventory's docstring overclaims what path-depth ordering guarantees** (LOW)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:895`
**Anchor:** `def macho_inventory(root: Path) -> list[Path]:`
**What:** The docstring says deepest-first "guarantees every dependency is sealed before anything that embeds or loads it". Path depth orders containment; it says nothing about link-time dependency, and two dylibs at equal depth are ordered alphabetically.
**Why it matters:** The claim is harmless in effect — a Mach-O's signature covers only its own bytes, so load order is irrelevant to seal validity, and containment is what actually matters — but `test_inventory_is_ordered_deepest_first` pins depth ordering with an assertion message that repeats the stronger reading, which is the kind of over-claim §4.9 asks this repo to avoid.
**Proposed fix:** Narrow both the docstring and the test's assertion message to containment: a container (`.framework`, a nested `.app`) must be signed after the code it contains, which is exactly what path depth gives.
**Regression-guard:** Optional at LOW.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

## What was done well

### From milestone-adversary-critic

- **The seal-location decision is a measurement, not an argument.** The A/B
  control on a six-byte `data.txt` separates "this payload is unusual" from
  "this location cannot hold data", stays in the build so any future failure is
  attributable, and is asserted in both directions
  (`test_the_location_control_separates_layout_from_payload`).
- **The failed-seal pin was INVERTED rather than deleted.** The previous
  dispatch pinned `sealed is False` so the finding could not evaporate; 2a
  flips it to `sealed is True` plus `verified is True` plus the literal "valid
  on disk" string, and `assemble` raises rather than shipping an unsealed
  `.app`. That is the right shape for a claim that changed.
- **`resolve_inside()` really is byte-unchanged.** I diffed the full range:
  the only deletions in `main.rs` are doc-comment lines and the old
  `child_payload_root` body. m10's symlinked-root refusal is preserved by
  construction, and the selection layer deliberately treats a symlinked root as
  *present* so it is refused rather than traded for the other layout — the
  subtle direction, and it is tested
  (`symlinked_bundle_payload_root_does_not_fall_through`).
- **AC4 is re-measured against the artifact, not inherited.** The
  `--print-child-plan` probe reports the selected ARM, so "it resolved inside
  the bundle" is read off the shipped binary instead of inferred from a path
  string, and the negative arm runs against the real bundle `Resources` root.
- **AC5's byte-identity is doubly derived** — `assemble` raises on manifest
  drift, and the test recomputes the manifests itself rather than trusting the
  build's own `payload_identical_to_onedir` flag.
- **The `--deep` ban is enforced over AST string constants minus docstrings**,
  which is the only way to let `presign_payload`'s prose name the flag in order
  to forbid it without the guard tripping on its own explanation.
- **The `minos` disagreement is recorded with its reasoning, not smoothed
  over** — the constant, the comment above it, the README paragraph and CLAUDE.md
  all say 11.0 vs 14.0 and say which half under-declares. I found no string or
  document implying the two agree.
- **`bundle_executable()` reads `CFBundleExecutable` from the built plist** and
  `product_name()` reads `productName` from `tauri.conf.json`, so neither the
  `arXMCP` / `supervisor` split nor a rename can desync the assembler from the
  bundler.
- **The corrupt committed `icon.png` was found and given a CRC regression** — a
  defect invisible to every other gate in the repo because `bundle.active` had
  been `false` for the file's whole life.
- **Commit hygiene is clean:** all six commits `%G? = G`, all carry a
  `Co-Authored-By` naming the authoring model, conventional subjects within the
  50-char budget, no `plans/` or roadmap edit, and no push performed.

### From milestone-arxmcp-critic

- **§4.5 marker-table consistency is fully closed, not partially.** `pyproject.toml` registers 13 markers, CLAUDE.md §4.5 says "Thirteen", all 13 names appear in the enumeration, and `tests/conftest.py:134`'s `_OPT_IN_MARKERS` gained `requires_desktop_bundle` — I re-derived all four independently rather than trusting `test_marker_doc_consistency.py`.
- **§4.9 is respected on the axis that mattered.** `sealed`, `verified`/`verify_output`, `signing` (nested Mach-O count plus the ad-hoc flag), `signature_stability` and `seal_location_control` are five separate recorded axes; no field, marker string or test name collapses "sealed" into "notarizable", and the notary question is ABSENT from the record rather than defaulted to passing — the same shape as `lean_verify`'s unmeasured axes.
- **The Decision 2 → 2a inversion was handled as a measurement, not a retreat.** The A/B control (`measure_macos_seal_location_control`) stays live in the build, so the reason for the location survives as re-derivable evidence, and `TestOuterSeal::test_the_location_control_separates_layout_from_payload` fails loudly if `Contents/MacOS` ever starts sealing a plain data file.
- **Doc drift from the two rewrites is fully resolved at the tip.** `CLAUDE.md`, `apps/desktop/README.md` and the ADR all describe `Contents/Resources/` and Decision 2a at `b8c0a1c`; no residue of `Contents/MacOS/` or m10's sibling-only convention survives outside the deliberately retained "Decision 2 as originally accepted" block.
- **The dual-layout resolver is a real disjunction, not a speculative probe.** The bundle candidate is offered only from `…/Contents/MacOS`, so outside a bundle there is exactly one root and nothing to fall through to; precedence, the refusal, and the symlinked-root non-fallthrough are each tested twice — as Rust unit tests and again against the real bundled binary.
- **`resolve_inside()` was left untouched and that is asserted.** m10's M13 symlinked-root refusal is preserved by construction (a symlinked root counts as PRESENT, is selected, and is then refused), which is the one design choice that keeps the new selection layer from silently weakening the old containment gate.
- **`file_manifest` uses `lstat`, hashes symlink targets separately and excludes mtimes** — the exact discipline this critic's lessons file records from the m7 spike, applied without prompting.
- **`--deep` is banned by an AST check over string constants minus docstrings**, so the prose that names the flag in order to forbid it cannot be mistaken for a use of it. That is the right resolution of a check a substring grep would have gotten wrong.
- **The two disagreeing `minos` floors were measured and pinned rather than reconciled or hidden** (11.0 frozen vs 14.0 Rust, with the 180-file distribution recorded), and the test says in as many words that agreement would itself be the thing to re-record.
- **The corrupt-icon regression is a genuine find with a genuine test.** A 1x1 PNG with a bad IDAT CRC had been invisible for the whole life of `bundle.active: false`; `TestIconIsDecodable` now checks every chunk CRC and the minimum dimension.

### From milestone-infra-safety-critic

- **Signing ordering is right and is pinned as a property, not a comment.** `macho_inventory` sorts deepest-first with a deterministic path tiebreak, and `test_inventory_is_ordered_deepest_first` builds a synthetic four-level tree and asserts the depths are monotonically decreasing rather than asserting a fixed list.
- **`codesign --deep` is genuinely absent from every mutating path, and the guard against it is not a substring grep.** `test_deep_never_appears_in_a_signing_command` walks the AST of `sign_file` / `presign_payload` / `seal_app`, excludes each docstring so the prose that forbids `--deep` cannot trip its own check, and asserts all three functions were actually found. The only `--deep` in the module is in the read-only `codesign_verify` helper.
- **Ad-hoc is described honestly rather than dressed up.** The `CODESIGN_IDENTITY_ENV` comment, the README, the ADR and the pyproject marker text all say the same thing: a real seal, locally tamper-evident, carrying no identity, saying nothing about the notary or Gatekeeper. Nothing in the diff implies more.
- **The m7/m8 guards measure the ASSEMBLED tree, not a stale copy.** `assemble()` calls `scan_tree(placed, …)` and `libomp_inventory(placed)` against the payload inside `Contents/Resources/`, with `_require_scan_coverage` and the bytes-read-vs-lstat tripwire intact, and the gate additionally asserts `files_scanned > 1000` and `embedded.pyc_entries > 0` so a vacuous scan cannot read as clean.
- **The seal now raises and leaves the evidence on disk first.** `assembly-report.json` is written before the `BuildError`, and the error text carries the location-control result so a future failure is attributable to the layout versus the host rather than guessed at.
- **The A/B location control was kept live rather than quoted from a log.** `measure_macos_seal_location_control` re-derives the `Contents/MacOS` versus `Contents/Resources` result on every run from a six-byte `data.txt`, and the gate asserts BOTH arms — including that `MacOS` still fails, with an assertion message telling a future reader to re-record the ADR if it ever seals.
- **The two-layout disjunction is explicit and its hardening is preserved by construction.** The bundle candidate is offered only from `…/Contents/MacOS`, presence is `symlink_metadata` so a symlinked root is selected and then refused by `resolve_inside()` rather than falling through to the sibling arm, and `symlinked_bundle_payload_root_does_not_fall_through` pins exactly that.
- **m10's trust assumption was updated for the new location, not left describing the old one.** Both `main.rs`'s residual-risk block and `apps/desktop/README.md` § "Child payload layout and its trust assumption" now say "the payload directory — whichever layout is in force", and the README's stale "m15 replaces this convention" paragraph is gone.
- **The `minos` disagreement is measured, pinned and left unreconciled rather than papered over.** 11.0 for the frozen executables against a declared 14.0 floor, with the 111/36/33 distribution recorded and `_declared_minos` raising on an empty `otool` parse instead of returning a clean-looking empty list.
- **Makefile hygiene is otherwise intact:** the `test` target is untouched and still runs the version gate, `ruff check .` and `pytest`; both new targets are `.PHONY`; `desktop-bundle` is idempotent (the onedir is rebuilt, `place_payload` rmtrees its destination, `--force` re-signs); no `sudo`, no destructive default; and the new marker was added to BOTH `pyproject.toml` and `conftest._OPT_IN_MARKERS`, which §4.5 names as the pairing a previous bug was created by missing.

Severity counts: C1 H3 M16 L7


## Cross-critic agreement

The following findings cluster within 5 lines of each other in the same file. Multiple critics flagged the same area - these are the strongest signals to fix first.

- **C1, H2, H3** at `tests/conftest.py:53-53` (CRITICAL): m15's zero-skip gate env var is never registered; m15 gate's zero-skip guard is documented but not wired; desktop-bundle-check's zero-skip guard is never armed
- **M5, H1** at `tests/test_desktop_bundle.py:592-594` (HIGH): the payload-wide minos census is asserted only against itself; AC3's launch claim is unproven at the artifact level
- **M2, M8, M15** at `apps/desktop/pyinstaller/desktop_package.py:1251-1251` (MEDIUM): a failed assembly leaves the previous run's report readable as current; a stale `assembly-report.json` can be read as this run's evidence; a stale assembly-report.json can outlive the artifact it describes
- **M3, M7** at `tests/test_desktop_notarization_claims.py:95-95` (MEDIUM): one stray cue word disables the notarization-claim scanner; notarization scanner exempts ordinary claim sentences
- **L6, L3** at `apps/desktop/crates/supervisor/src/main.rs:494-498` (LOW): the shipped supervisor writes JSON to an argv-supplied path; the probe's file write cannot fail loudly

## Recommended rectification order

C1, H1, H2, H3, M2, M3, M4, M1, M5, M6, M8, M7, M10, M9, M11, M15, M12, M16, M14, M13, L1, L2, L3, L4, L5, L7, L6

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
