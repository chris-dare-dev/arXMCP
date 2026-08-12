# Critique — desktop-distribution-m15 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** 525de97..b8c0a1c
**Diff stats:** 17 files, 3308 LOC (3262 insertions, 46 deletions; ~1076 of the insertions are `.claude/` notes + the ADR)
**Critique format version:** 1.0

## Verdict

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

## Executive summary

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

## What was done well

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

Severity counts: C1 H1 M6 L2

## Recommended rectification order

C1, H1, M2, M3, M4, M1, M5, M6, L1, L2

Notes for Phase 4, so the omissions are auditable:

- The **>400 LOC auto-finding is deliberately NOT filed**: `state.json:33`
  carries `allow_large_diff: true` (the m6/m7/m8/m10/m12 precedent). The
  arithmetic is 3262 insertions + 46 deletions = 3308 LOC across 17 files, of
  which roughly 1076 insertions are `.claude/` notes and the ADR.
- **Not filed by dispatch instruction:** the absence of notarization (ADR
  Decision 3), the PyInstaller `minos` reconciliation, and the GUI-session
  `test_supervisor_owns_a_native_window_while_running` failure.
- **Attacked and cleared:** the seal cannot pass on a degenerate payload
  (`presign_payload` raises on zero Mach-O; the manifest-drift check precedes
  the seal); the outer seal genuinely does cover nested payload Mach-O bytes,
  including framework-shaped ones, on this macOS (measured, see M1);
  `codesign --verify` is never described as evidence about the notary anywhere
  in the diff; and `make desktop-bundle-check`'s 62-passed figure is
  implementer-reported only — no finding here relies on it.
