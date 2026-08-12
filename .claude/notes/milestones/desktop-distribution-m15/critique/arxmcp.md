# Critique — desktop-distribution-m15 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** 525de97..b8c0a1c
**Diff stats:** 17 files, 3308 LOC (3262 insertions / 46 deletions)
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

The assembly, the Decision 2a relocation and the dual-layout resolver are honest, well-measured work, and the two axes most likely to bite — §4.5 marker-table consistency and §4.9 trust language on the seal — are clean on inspection rather than on assertion. The defects are all in the evidence machinery around the artifact rather than in the artifact: the milestone's headline zero-skip guarantee is documented in three places and wired in none, the new notarization-claim scanner exempts ordinary claim sentences, and two evidence reads (a stale `assembly-report.json`, a control-free negative measurement) can report clean for the wrong reason. One ungated test also creates a symlink with no win32 guard, which regresses the 2026-07-12 portability push.

## Executive summary

- [HIGH] `DESKTOP_BUNDLE_GATE` is absent from `tests/conftest.py::_DESKTOP_GATE_ENV`, so `make desktop-bundle-check`'s advertised zero-skip contract is unimplemented — the exact m7 failure mode the conftest comment above it describes.
- [MEDIUM] The notarization-claim scanner's sentence-level cue set exempts a plain claim containing `no` / `may` / `if` / `must`; four unearned-claim sentences pass, demonstrated below.
- [MEDIUM] `assemble()` never invalidates a prior `assembly-report.json`, so a run that fails after sealing leaves last run's evidence beside this run's `.app` and the gated tests read the stale file.
- [MEDIUM] `TestPlacementDoesNotIntroduceASymlinkRoot` is ungated and calls `symlink_to`, which the repo elsewhere guards with `skipif(sys.platform == "win32")`.
- [MEDIUM] The quarantine negative measurement asserts an empty probe report with no same-run control, so a probe that launched and failed to write is indistinguishable from a blocked launch — the m6 doctrine this repo already wrote down.
- [MEDIUM] CLAUDE.md, `pyproject.toml` and the README all say assembly "raises rather than leaving an unsealed `.app`"; it raises AND leaves it at the canonical path.
- [LOW] `emit_child_plan_probe` discards the write result, so the probe exits 0 having produced nothing.
- [LOW] `_probe`'s stdout path breaks if `DESKTOP_CHILD_PLAN_OUT` is set in the ambient environment.

## Findings

**H1 — m15 gate's zero-skip guard is documented but not wired** (HIGH)

**Where:** `tests/conftest.py:53`
**Anchor:** `_DESKTOP_GATE_ENV: tuple[str, ...] = (`
**What:** The tuple lists `DESKTOP_SUPERVISOR_BIN`, `ARXMCP_FIXTURE_SIDECAR`, `DESKTOP_PACKAGE_GATE` and `DESKTOP_BUNDLED_MODEL_GATE` but not `DESKTOP_BUNDLE_GATE`, which `Makefile:229` exports; `git grep DESKTOP_BUNDLE_GATE` at the tip finds it only in the Makefile, CLAUDE.md, `pyproject.toml`, the m15 notes and `tests/test_desktop_bundle.py:74` — never in the guard.
**Why it matters:** CLAUDE.md §4.5, the `requires_desktop_bundle` registration in `pyproject.toml:376` and `Makefile:226` each state that `DESKTOP_BUNDLE_GATE=1` makes any skip fail the session. It does not. The Makefile's `-m "requires_desktop_bundle or not requires_desktop_bundle"` is a tautology for any token, so a drifted marker name or a `pytest.skip` inside a gated test degrades the gate to a green run with the evidence missing — verbatim the m7 degradation the comment at `tests/conftest.py:49` says `DESKTOP_PACKAGE_GATE` was added to prevent.
**Proposed fix:** Add `"DESKTOP_BUNDLE_GATE"` to `_DESKTOP_GATE_ENV` and extend the comment block above it with the m15 sentence, mirroring the m7/m8 lines.
**Regression-guard:** In `tests/test_desktop_bundle.py::TestGateWiring`, assert `"DESKTOP_BUNDLE_GATE" in tests.conftest._DESKTOP_GATE_ENV` — a source-derived check, so the doc claim and the mechanism cannot drift again.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

---

**M1 — notarization scanner exempts ordinary claim sentences** (MEDIUM)

**Where:** `tests/test_desktop_notarization_claims.py:95`
**Anchor:** `_DISCLAIM_CUES = re.compile(`
**What:** The cue set includes `no`, `not`, `may`, `must`, `if`, `open`, `would`, `question`, and it is applied at SENTENCE granularity, so any claim sentence containing one of those very common words is skipped entirely. Executed against the module at this commit, `_find_unearned_claims` returns `[]` for all four of: "The assembled bundle is notarization-ready, so no further work is needed."; "The bundle has been notarized and may now be shipped."; "Code signing works, if you have the certificate."; "arXMCP.app is Gatekeeper-ready and must be shipped as-is."
**Why it matters:** This is the gate that enforces ADR Decision 3 and §4.9's rule against collapsing "sealed" into "notarizable" — the one axis this milestone must not get wrong. The module's docstring says "the controls below are what bound it", but every `_MUST_FLAG` sentence at `:143` is cue-free, so the controls prove nothing about the exemption's width.
**Proposed fix:** Keep the sentence window only for the meta-statement shape it exists for: require the cue to appear BEFORE the claim match within the sentence, and drop the generic modals (`may`, `must`, `if`, `would`) from the cue set. The ADR's real meta-statements retain `no` / `not` / `whether` and still pass.
**Regression-guard:** Add the four sentences above to `_MUST_FLAG` so `TestScannerControls::test_flags_a_claim` fails against the current cue set.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

---

**M2 — a stale `assembly-report.json` can be read as this run's evidence** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:1251`
**Anchor:** `    (root / "assembly-report.json").write_text(`
**What:** `assemble()` writes the report only at the very end, after `_require_scan_coverage`, `_require_single_libomp` and the `scan["hits"]` check (`:1232`–`:1249`) have already had their chance to raise, and it never removes a pre-existing report at entry. `build_app_shell` does `rmtree` the `.app`, so a run that seals and then fails the scan leaves this run's `.app` on disk next to the PREVIOUS run's report.
**Why it matters:** `tests/test_desktop_bundle.py::_report()` only checks that the file exists. `TestOuterSeal` and `test_placed_child_is_byte_identical_to_the_onedir` read `signing`, `seal`, `seal_location_control`, `signature_stability` and `scan` from it. `make desktop-bundle-check` is protected by make's dependency ordering, but the marker registration and CLAUDE.md §4.5 both advertise bare `pytest -m requires_desktop_bundle` as an equivalent entry point, and that path has no freshness check at all.
**Proposed fix:** `unlink(missing_ok=True)` the report as the first statement of `assemble()`, and record the `.app`'s resolved path plus its `Contents/_CodeSignature/CodeResources` digest in the report so a reader can bind report to artifact.
**Regression-guard:** A gated test asserting `Path(_report()["app"]).resolve() == _app().resolve()` and that the recorded `CodeResources` digest matches the artifact on disk.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

---

**M3 — ungated test creates a symlink with no win32 guard** (MEDIUM)

**Where:** `tests/test_desktop_bundle.py:386`
**Anchor:** `        (payload / "_internal" / "link").symlink_to("data")`
**What:** `TestPlacementDoesNotIntroduceASymlinkRoot::test_placed_root_is_a_real_directory` carries no marker and no `skipif`, so it runs on every `make test` on every platform and creates a symlink, which Windows refuses without Developer Mode or `SeCreateSymbolicLinkPrivilege`.
**Why it matters:** CLAUDE.md §3 records `make test` being measured on Windows 11, and the 2026-07-12 portability push explicitly GUARDED nine symlink-creation tests rather than letting them fail; `tests/test_desktop_data_root_spike.py:229` is the in-repo precedent (`skipif(sys.platform == "win32", reason="symlink privilege varies")`). The gate results for this milestone were measured on macOS only, so this regression is unmeasured rather than absent.
**Proposed fix:** Add `@pytest.mark.skipif(sys.platform == "win32", reason="symlink privilege varies")`, matching the precedent. Alternatively split the symlink-preservation assertion into its own guarded test and leave the `place_payload` destination/`is_symlink` assertions running everywhere.
**Regression-guard:** Optional (MEDIUM).
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

---

**M4 — the quarantine negative measurement has no same-run control** (MEDIUM)

**Where:** `tests/test_desktop_bundle.py:813`
**Anchor:** `        assert report == {}, (`
**What:** `test_quarantine_blocks_the_launch_so_translocation_is_unverified` concludes "the quarantined bundle did not launch" from `_probe(..., use_open=True)` returning `{}`, which `_probe` returns whenever the output file is simply absent after its 40 s poll. A supervisor that DID launch but whose `fs::write` failed (`apps/desktop/crates/supervisor/src/main.rs:498` discards the result) produces exactly the same `{}`.
**Why it matters:** This is the single test that keeps the translocation gap visible in a green run, and `apps/desktop/README.md`'s "Gatekeeper path translocation is UNVERIFIED" claim rests on it. The repo's own m6 doctrine, restated in `apps/desktop/README.md`, is that "a failed or partial probe is an evidence failure and never clean absence" and that every absence query must ride a same-run control. This one does not — the positive arm lives in a different test with a different `tmp_path`.
**Proposed fix:** Inside the same test, first run the UN-quarantined staged copy through `_probe(..., use_open=True)` and require a non-empty report, then apply `com.apple.quarantine` to that same copy and require `{}`. That makes the write mechanism a same-run control for the absence.
**Regression-guard:** The added positive arm IS the guard; it fails if the `open(1)`/argv[2] write path breaks.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

---

**M5 — "raises rather than leaving an unsealed `.app`" is not what the code does** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:1261`
**Anchor:** `        raise BuildError(`
**What:** On a failed outer seal `assemble()` raises, but the unsealed `.app` stays at `app_bundle_path()`; nothing removes or marks it. CLAUDE.md §4.5 ("assembly raises rather than leaving an unsealed `.app`"), `pyproject.toml:376` (same words) and `apps/desktop/README.md` ("assembly RAISES rather than leaving an unsealed `.app` on disk") all state the stronger property.
**Why it matters:** `tests/test_desktop_bundle.py::_app()` accepts any directory at that path, so combined with M2 the residue is reachable by the documented bare-`pytest` entry point. More narrowly it is a §4.9-shaped inaccuracy: three documents assert an artifact does not exist when it does.
**Proposed fix:** Either `shutil.rmtree(app)` before the raise and say so in the message, or reword all three documents to the true claim — "assembly raises and leaves the unsealed `.app` in place for inspection; it is never a shippable artifact."
**Regression-guard:** Optional (MEDIUM). If the rmtree route is taken, a unit test that monkeypatches `seal_app` to report `sealed=False` and asserts the `.app` is gone after the raise.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

---

**L1 — the probe's file write cannot fail loudly** (LOW)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:498`
**Anchor:** `            let _ = fs::write(PathBuf::from(path), t`
**What:** The write result is discarded and `main` then exits 0, so a probe invocation that could not write its destination is indistinguishable from one that never ran.
**Why it matters:** It is the mechanism behind M4 and it makes every `use_open=True` measurement one-sided. Non-fatal is right for a diagnostic; exit 0 is the wrong signal.
**Proposed fix:** On `Err`, print the report to stderr and `std::process::exit(3)`; keep exit 0 for a successful write or the stdout path.
**Regression-guard:** Optional (LOW).
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

---

**L2 — `_probe`'s stdout path is sensitive to an ambient env var** (LOW)

**Where:** `tests/test_desktop_bundle.py:459`
**Anchor:** `    proc = subprocess.run(`
**What:** The non-`open` branch passes no argv[2], so `emit_child_plan_probe` falls back to `DESKTOP_CHILD_PLAN_OUT`. If that variable is set in the operator's shell the probe writes a file, stdout is empty and `json.loads(proc.stdout)` raises with an opaque error.
**Why it matters:** Small, but the whole family of `DESKTOP_*` non-`ARXMCP_`-prefixed vars exists precisely because operators do set them in this project.
**Proposed fix:** Pass an explicit `env=` with `DESKTOP_CHILD_PLAN_OUT` removed, or always pass an explicit argv[2] and read the file in both branches.
**Regression-guard:** Optional (LOW).
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

## What was done well

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

Severity counts: C0 H1 M5 L2

## Recommended rectification order

H1, M2, M1, M4, M3, M5, L1, L2

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
