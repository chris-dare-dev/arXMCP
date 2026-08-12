# Critique — desktop-distribution-m15 — milestone-infra-safety-critic

**Critic:** milestone-infra-safety-critic
**Commit range:** 525de97..b8c0a1c
**Diff stats:** 17 files, 3308 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

The assembly pipeline is correct on its sharpest axis: signing is genuinely bottom-up per-file, `codesign --deep` is absent from every mutating path and AST-pinned as such, the seal now raises rather than shipping an unsealed artifact, and the m7/m8 guards are genuinely re-run over the PLACED tree rather than a stale pre-assembly copy. One HIGH defeats the gate's own contract: `make desktop-bundle-check` exports `DESKTOP_BUNDLE_GATE=1`, but that name was never added to `tests/conftest.py`'s `_DESKTOP_GATE_ENV`, so the zero-skip detector this milestone documents in four places is inert. The remaining findings are build-time supply-chain and cleanup foot-guns, none of which block the artifact.

## Executive summary

- [HIGH] `DESKTOP_BUNDLE_GATE` is missing from `tests/conftest.py:53`'s `_DESKTOP_GATE_ENV`, so the zero-skip guard that the Makefile, `pyproject.toml`, CLAUDE.md §4.5 and the test module all describe never arms for `make desktop-bundle-check`.
- [MEDIUM] `build_app_shell` hands `tauri build` the full inherited environment; `APPLE_SIGNING_IDENTITY`/`APPLE_CERTIFICATE` being set would make Tauri's own bundler sign the shell, outside this repo's never-`--deep` invariant and with a different identity than the assembler's.
- [MEDIUM] `tauri-cli` is version-pinned, not hash-pinned, while the comment above `desktop_package.py:760` asserts parity with the `--require-hashes` PyInstaller lock; the difference is not stated.
- [MEDIUM] No clean path reclaims the assembled `.app` (~0.75 GB) or the Rust release `target/`; `make desktop-package-clean` reaches only `var/desktop-package/`.
- [MEDIUM] `assembly-report.json` is never invalidated at the top of `assemble()`, so an interrupted run leaves a stale report beside a new partial `.app`, and six gate assertions read the report rather than the artifact.
- [MEDIUM] AC5's byte-identity baseline is taken AFTER pre-signing mutates `var/desktop-package/dist/` in place, so "byte-identical to the artifact `make desktop-package` emitted" is not the property measured.
- [LOW] `ensure_tauri_cli`'s reuse check is a substring match on `--version` output; two further claim-precision issues elsewhere.
- Clean: signing order, `--deep` absence, seal-raises-on-failure, guards over the assembled tree, `make test` unchanged, marker registered in both required places.

## Findings

**H1 — desktop-bundle-check's zero-skip guard is never armed** (HIGH)

**Where:** `tests/conftest.py:53`
**Anchor:** `_DESKTOP_GATE_ENV: tuple[str, ...] = (`
**What:** `Makefile:228` runs the m15 gate with `DESKTOP_BUNDLE_GATE=1`, but the diff added `requires_desktop_bundle` only to `_OPT_IN_MARKERS` and never added `DESKTOP_BUNDLE_GATE` to `_DESKTOP_GATE_ENV`, whose members are `DESKTOP_SUPERVISOR_BIN`, `ARXMCP_FIXTURE_SIDECAR`, `DESKTOP_PACKAGE_GATE` and `DESKTOP_BUNDLED_MODEL_GATE` — none of which `desktop-bundle-check` sets.
**Why it matters:** `pytest_runtest_logreport` returns early when no member is present, so `_DESKTOP_GATE_SKIPS` stays empty and `pytest_sessionfinish` never fails the session; the `-m "requires_desktop_bundle or not requires_desktop_bundle"` expression is a tautology for any token, so a drifted marker name or a `pytest.skip` inside the gated half would let `make desktop-bundle-check` exit 0 with the artifact evidence silently absent. This is the same failure class the m5 critique's H3 already closed once for m6 and m7, and it makes the implementer-reported "62 passed zero skips" an unenforced human read rather than a mechanism.
**Proposed fix:** Add `"DESKTOP_BUNDLE_GATE",` to the `_DESKTOP_GATE_ENV` tuple at `tests/conftest.py:53-58` and extend the adjacent comment the way `DESKTOP_PACKAGE_GATE` and `DESKTOP_BUNDLED_MODEL_GATE` were.
**Regression-guard:** A test that derives the expected set from the Makefile rather than restating it: parse every `DESKTOP_[A-Z_]*_GATE=1` assignment out of the Makefile's recipe lines and assert each is a member of `conftest._DESKTOP_GATE_ENV`. That makes the next gate target unable to land with an inert guard.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M1 — tauri build inherits an environment that can silently activate Tauri's own signing** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:996`
**Anchor:** `        [str(cli), "build"],`
**What:** `build_app_shell` passes `env=dict(os.environ)` to `tauri build` with no guard, and Tauri's macOS bundler signs the produced `.app` at build time whenever `APPLE_SIGNING_IDENTITY` / `APPLE_CERTIFICATE` are present in the environment.
**Why it matters:** The never-`--deep` invariant is enforced only over this repo's own code — `test_deep_never_appears_in_a_signing_command` walks the AST of exactly `sign_file`, `presign_payload` and `seal_app`. Tauri's bundler is outside that scope and signs the app bundle with its own flags, so an operator who exports a signing identity gets a shell signed by a second actor with a second identity, invisibly to every assertion in the gate. This is not a theoretical shell: e4's notarization trial is the moment those exact variables get exported.
**Proposed fix:** Refuse loudly rather than inherit. In `build_app_shell`, raise `BuildError` when any of `APPLE_SIGNING_IDENTITY`, `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD` is set (pointing at `CODESIGN_IDENTITY_ENV` as the supported knob), or strip them from the child environment. Decision 1 step 3 says the bundler builds the shell only; this is the enforcement of it.
**Regression-guard:** Unit test that monkeypatches `APPLE_SIGNING_IDENTITY` into the environment and asserts `build_app_shell` raises before `_run` is reached, or that the env dict handed to `_run` does not contain it.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M2 — tauri-cli is version-pinned, not hash-pinned, and the difference is unstated** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:760`
**Anchor:** `TAURI_CLI_VERSION = "2.11.4"`
**What:** The comment above this line says the pin is "like every other link in this chain" and cites `requirements-build.txt`'s `--require-hashes` alongside it, but `cargo install --locked --version` records no digest anywhere in this repo; integrity rests entirely on whichever registry `cargo` resolves at build time, and `--locked` fixes only the CLI's own transitive resolution, not the top-level crate's bytes.
**Why it matters:** §4.9's rule against a claim that collapses distinct questions applies to build provenance too. A reader comparing the two mechanisms is told they are equivalent when one records a hash in-tree and the other does not; the gap is real for a registry-source replacement in `.cargo/config.toml` or a `CARGO_REGISTRIES_*` override, and `cargo install` additionally executes the build scripts of the whole tauri-cli dependency tree on this host.
**Proposed fix:** Restate the comment honestly — version-and-lock pinned, with integrity delegated to the registry index's checksums, NOT hash-pinned in-tree the way `requirements-build.txt` is — and record the observed `cargo-tauri --version` string plus the crate's `.crate` sha256 next to the pin so drift is detectable. Extend `TestToolchainPinning` to assert the comment names the distinction.
**Regression-guard:** Optional at MEDIUM; the `TestToolchainPinning` addition above doubles as one.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M3 — no clean path reclaims the assembled .app or the Rust release target** (MEDIUM)

**Where:** `Makefile:234`
**Anchor:** `desktop-package-clean:`
**What:** `desktop-package-clean` is `rm -rf var/desktop-package`, but m15's ~0.75 GB `.app` is written to `apps/desktop/target/release/bundle/macos/`, alongside a full Rust release `target/` tree that the first `tauri build` also creates. Nothing in the diff adds a `desktop-bundle-clean` target and `Makefile:106`'s help text still describes only the `var/desktop-package/` footprint.
**Why it matters:** The single documented reclaim verb now under-reports the milestone's disk cost by roughly a second copy of the payload plus the Rust build tree, on a machine where the `requires_desktop_package` marker text already advertises ~2.5 GB at the m7 peak. An operator following the documented cleanup path recovers less than they were told they would.
**Proposed fix:** Add a `desktop-bundle-clean` target (`rm -rf apps/desktop/target/release/bundle var/desktop-package/assembly-report.json`), list it in `help`, and amend `Makefile:106` plus the `requires_desktop_bundle` marker text to name where the assembled bundle actually lands. Note in the `desktop-package-clean` comment that it now also discards `tauri-cli`, forcing a several-minute network recompile on the next `make desktop-bundle`.
**Regression-guard:** Optional at MEDIUM.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M4 — a stale assembly-report.json can outlive the artifact it describes** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:1251`
**Anchor:** `    (root / "assembly-report.json").write_text(`
**What:** `assemble()` writes the report only at the very end and never removes a previous one at the top, while `build_app_shell` rmtrees and rebuilds the `.app` early in the same run. An interrupt or a `tauri build` failure between those two points leaves the previous run's report on disk next to a missing or partial bundle.
**Why it matters:** Six of the gated assertions read `_report()` rather than the artifact — `test_every_nested_macho_was_signed`, `test_the_outer_seal_succeeded_and_verifies`, `test_placed_child_is_byte_identical_to_the_onedir`, `test_m7_and_m8_guards_hold_over_the_assembled_payload`, `test_the_location_control_separates_layout_from_payload` and `test_ad_hoc_signing_is_byte_stable` — so a direct `DESKTOP_BUNDLE_GATE=1 pytest` run (the path H1 leaves unguarded) can grade a new partial artifact against an old run's evidence. `test_the_seal_is_verified_against_the_artifact_not_the_report` exists precisely because the author saw this class; it currently covers one assertion of the set.
**Proposed fix:** Unlink `root / "assembly-report.json"` as the first statement of `assemble()`, and stamp the report with the app's own identity (its path plus the sha256 of `Contents/MacOS/<CFBundleExecutable>`) so `_report()` can assert the report describes the bundle on disk before any assertion is built on it.
**Regression-guard:** Optional at MEDIUM.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M5 — AC5's byte-identity baseline is the post-signing onedir, not m7's artifact** (MEDIUM)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:1211`
**Anchor:** `    signed_manifest = file_manifest(payload_root)`
**What:** `presign_payload` at `:1209` signs the ~180 nested Mach-O files in place inside `var/desktop-package/dist/`, and the manifest baseline is taken on the line after. `Makefile:217` and CLAUDE.md §4.5 both describe the result as byte identity with "the artifact `make desktop-package` emitted"; the artifact that gate emitted no longer exists on disk by the time the comparison happens.
**Why it matters:** What is measured is copy fidelity from signed-onedir to placed-payload — real and worth keeping, since it catches a substituted or rebuilt child — but it is strictly weaker than the stated claim, and it also means m7's `report.json` and its determinism manifest no longer describe the tree sitting at `dist/` after any `make desktop-bundle`. Under §4.9's discipline the prose should not carry more than the measurement does.
**Proposed fix:** Capture `file_manifest(payload_root)` BEFORE `presign_payload` as well, record both in `assembly-report.json` as `onedir_manifest_presign` / `onedir_manifest_postsign`, and assert the pre-sign manifest's path set matches m7's. Then correct `Makefile:217` and the CLAUDE.md §4.5 sentence to say identity with the pre-signed onedir plus a signing-only delta, rather than identity with the m7 artifact.
**Regression-guard:** Optional at MEDIUM.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**L1 — the tauri-cli reuse check is a substring match** (LOW)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:851`
**Anchor:** `        if proc.returncode == 0 and TAURI_CLI_VER`
**What:** `TAURI_CLI_VERSION in proc.stdout` accepts any output containing `2.11.4` as a substring, including `2.11.40` or `12.11.4`.
**Why it matters:** A cached binary at a neighbouring version would be silently reused as "the pin", defeating the point of the `--root`-isolated install.
**Proposed fix:** Match the version as a whole token — `re.search(rf"\b{re.escape(TAURI_CLI_VERSION)}\b", proc.stdout)` — or compare the parsed trailing field of `cargo-tauri <version>` exactly.
**Regression-guard:** Optional at LOW.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**L2 — the shipped supervisor writes JSON to an argv-supplied path** (LOW)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:494`
**Anchor:** `        .nth(2)`
**What:** `emit_child_plan_probe` writes its report to whatever path `argv[2]` names, with no containment check, in the binary that ships inside the `.app`.
**Why it matters:** Any local process that can call `open -a arXMCP.app --args --print-child-plan <path>` overwrites that file with JSON under the user's identity. It confers no privilege the caller does not already have, which is why this is LOW — but it is an unbounded write in a shipped diagnostic, and the containment discipline `resolve_inside()` applies two functions away is not applied here.
**Proposed fix:** Restrict the destination to an existing directory the caller already owns, or drop the `argv[2]` form in favour of `DESKTOP_CHILD_PLAN_OUT` alone once the translocation measurement no longer needs argv.
**Regression-guard:** Optional at LOW.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**L3 — macho_inventory's docstring overclaims what path-depth ordering guarantees** (LOW)

**Where:** `apps/desktop/pyinstaller/desktop_package.py:895`
**Anchor:** `def macho_inventory(root: Path) -> list[Path]:`
**What:** The docstring says deepest-first "guarantees every dependency is sealed before anything that embeds or loads it". Path depth orders containment; it says nothing about link-time dependency, and two dylibs at equal depth are ordered alphabetically.
**Why it matters:** The claim is harmless in effect — a Mach-O's signature covers only its own bytes, so load order is irrelevant to seal validity, and containment is what actually matters — but `test_inventory_is_ordered_deepest_first` pins depth ordering with an assertion message that repeats the stronger reading, which is the kind of over-claim §4.9 asks this repo to avoid.
**Proposed fix:** Narrow both the docstring and the test's assertion message to containment: a container (`.framework`, a nested `.app`) must be signed after the code it contains, which is exactly what path depth gives.
**Regression-guard:** Optional at LOW.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

## What was done well

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

Severity counts: C0 H1 M5 L3

## Recommended rectification order

H1, M4, M1, M5, M3, M2, L1, L3, L2

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed: <finding ids>
- Deferred: <finding ids>
- Invalidated: <finding ids with reasons>
- Regression tests added: <file paths>
