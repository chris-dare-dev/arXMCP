# Implement synthesis (assembly half) — desktop-distribution-m15

Second half of the two-part m15 dispatch. The ADR half (AC1 + AC2's decision
text) landed at `dc89658`/`3f21248` and was Accepted; this dispatch implements
against it and owns AC2's regression, AC3–AC10, and the two stale prose sites.

**Base:** `3f21248`. **Commit:** `f581dd0` on `worktree-agent-acea46e67ef8a92bd`.

---

## Built

- **AC2 (guard)** — `tests/test_desktop_notarization_claims.py` (new, 226 LOC).
  Scans a DERIVED file set for notarization/Gatekeeper readiness claims, with
  must-flag and must-not-flag control corpora on the m9 pattern.
- **AC3 (partial, see "Not claimed")** — `make desktop-bundle` produces
  `arXMCP.app`. `tauri.conf.json` flips `bundle.active` to `true` and pins
  `targets: ["app"]`; `desktop_package.py assemble` does the rest.
- **AC4** — measured, not inherited. New supervisor diagnostic
  `--print-child-plan` (`main.rs`, `child_plan_probe` / `emit_child_plan_probe`)
  reports `current_exe()`, the payload root, whether that root is a symlink,
  and the resolved `child_argv[0]`. Proven by
  `TestAssembledArtifact::test_supervisor_resolves_the_child_inside_the_bundle`
  against the real bundle, with the negative arm in
  `test_a_symlinked_payload_root_is_still_refused` and the symlink half in
  `test_payload_root_is_not_a_symlink`.
- **AC5** — `assemble` compares `file_manifest()` of the pre-signed onedir with
  the placed copy and raises on any drift; re-derived independently in
  `test_placed_child_is_byte_identical_to_the_onedir`. Assembly deliberately
  does NOT rebuild the onedir, so the comparison is against the artifact
  `make desktop-package` produced rather than a fresh look-alike.
- **AC6** — `test_m7_and_m8_guards_hold_over_the_assembled_payload`: m7's
  build-root string scan (including embedded-PYZ `.pyc` bytes, via the build
  venv's PyInstaller readers), m8's single-`libomp` inventory, and
  `direct_url.json` absence, all re-run over the PLACED tree.
- **AC7** — `test_bundled_supervisor_declares_the_floor`: `minos 14.0` off the
  bundle's own copy of the binary plus `LSMinimumSystemVersion` from the
  generated `Info.plist`.
- **AC8** — `apps/desktop/README.md` § "Assembled artifact layout", written
  from the measured artifact (tree, executable name, file/Mach-O counts, both
  minos values, the build order, and the two recorded non-claims).
- **AC9** — `make desktop-bundle` / `make desktop-bundle-check`, marker
  `requires_desktop_bundle`. This is the first committed gate that builds both
  the Rust binaries (via `tauri build`) and the frozen child in one session,
  which is what retires m10's fixture-in-the-onedir-shape substitution.
- **AC10** — `test_frozen_executables_minos_is_measured_and_pinned`, plus
  `test_the_two_declared_floors_disagree_and_that_is_recorded`.
- **Stale prose** — `main.rs`'s `child_payload_root` doc comment and the
  README's "Child payload layout" section both corrected; the correction is
  pinned by `test_the_stale_replacement_prediction_is_gone`.

---

## The ADR's eight open items, and how each was resolved

1. **Assembly mechanism and ordering** — a post-`tauri build` Python step in
   `desktop_package.py` (`assemble`), not a `beforeBundleCommand` hook. The
   hook runs *before* bundling, which cannot satisfy Decision 1's ordering
   constraint (pre-sign → build shell → place → seal): placement must happen
   after the shell exists.
2. **Signing identity** — ad-hoc (`-`) by default, overridable via
   `DESKTOP_CODESIGN_IDENTITY`. No Developer ID exists; the only codesigning
   identity on this host is an *Apple Development* certificate, which is not a
   distribution identity either. Skipping was rejected because it would leave
   the pre-signing step itself unexercised until e4. Hardened runtime is OFF
   by default (`DESKTOP_CODESIGN_HARDENED=1` opts in) — it is a notarization
   prerequisite that needs entitlements this project has never authored for a
   CPython closure, and shipping untested entitlements would trade a measured
   artifact for an unmeasured one.
3. **Distribution container** — `.app` only (`bundle.targets: ["app"]`). No
   DMG. Only a notarization submission forces the container question.
4. **Assembled-level determinism** — resolved as: m7's two-build onedir
   identity (unchanged, upstream) + AC5's byte-identity between the signed
   onedir and the placed copy + a measured answer to "is the one added
   byte-changing step a function of its input". **Measured: yes**, ad-hoc
   `codesign` is byte-stable. That measurement was WRONG on its first run and
   the correction is recorded in the code: signing two copies named `probe-0`
   and `probe-1` differed because `codesign` derives the signing identifier
   from the filename when the Mach-O carries none. Same basename in different
   directories → identical bytes.
5. **PyInstaller executables' `minos`** — see "Measured" below.
6. **Gate name / marker / target** — `requires_desktop_bundle`,
   `make desktop-bundle` + `make desktop-bundle-check`, `DESKTOP_BUNDLE_GATE=1`
   arming the zero-skip detector.
7. **Notarization-guard scan scope** — m9's set PLUS `.claude/docs/**.md`,
   `plans/**.md`, this milestone's notes, and
   `apps/desktop/pyinstaller/**.py`. Rationale in the module docstring: the
   most likely place to write the claim is the ADR that decides the layout,
   which m9 deliberately does not scan. Widening m9's own scanner was
   rejected — its corpus and calibration are about a different claim.
8. **README artifact-layout section** — written from the artifact.

---

## What was measured

| Fact | Value |
|---|---|
| Assembled bundle | `apps/desktop/target/release/bundle/macos/arXMCP.app` |
| Bundle executable | `Contents/MacOS/supervisor` (cargo bin name, NOT `productName`) |
| Payload location | `Contents/MacOS/arxmcp-desktop-child/` |
| Payload size | ~5,300 files, 180 Mach-O, ~0.75 GB |
| `child_argv[0]` resolution | inside the bundle, `error: null`, root not a symlink |
| Placed-vs-onedir manifest drift | 0 paths |
| Build-root string scan over placed tree | 0 hits |
| Supervisor `minos` | 14.0 · `LSMinimumSystemVersion` 14.0 |
| Frozen executables' `minos` | **11.0** (both) |
| Payload `minos` census | 111 × 14.0, 36 × 12.0, 33 × 11.0 |
| Ad-hoc signature byte-stability | stable (same input + basename) |
| Outer bundle seal | **not applied** |
| Location control (`data.txt`) | `Contents/MacOS` refused · `Contents/Resources` sealed |
| Frozen probe run from the assembled bundle | exit 0, real FAISS+Torch path |

### AC10's finding, stated plainly

The artifact carries **two different declared floors**. The Rust half is 14.0
(pinned by `.cargo/config.toml`, read back by m9). The PyInstaller-produced
executables are 11.0, because this project does not compile the CPython
bootloader and inherits the upstream wheel's target. The frozen half therefore
UNDER-declares the real floor, which the `faiss_cpu macosx_14_0_arm64` wheel
fixes at 14.0. Nothing enforces `minos` at runtime (the README already records
dyld loading a `minos 30.0` image on this host), so this changes no behaviour —
it removes an inference that the artifact agreed with itself. Not reconciled
here: raising it would mean rebuilding the PyInstaller bootloader, which is a
separate decision with its own hash-pinning consequences.

---

## What could NOT be measured on this host

- **Gatekeeper path translocation — UNVERIFIED, and asserted as such.**
  Setting `com.apple.quarantine` on the bundle and launching through `open(1)`
  yields exit 0 and no process: LaunchServices refuses an ad-hoc-signed bundle
  whose outer seal is invalid, so translocation never gets a chance to occur.
  Reaching that path needs the Developer ID signature e4 is blocked on.
  `TestRelocation::test_quarantine_blocks_the_launch_so_translocation_is_unverified`
  asserts the *negative* so the gap is visible inside a green run instead of
  living only in prose; when that test starts failing, translocation has become
  measurable and must be measured.
  What IS measured (`test_relocated_bundle_launched_via_launchservices_still_resolves`):
  the bundle relocated whole to an arbitrary path and launched through
  LaunchServices — not by direct exec — still resolves the payload as a sibling.
  Translocation relocates the bundle as a unit too, so this is *evidence for*
  the expectation. It is not the expectation itself.
- **Whether the artifact survives Apple's notary.** Unchanged and unchangeable
  here (ADR Decision 3). Not claimed anywhere; guarded.

---

## The one finding that touches an Accepted decision

`codesign` **cannot seal** the assembled bundle at Decision 2's location. It
treats every file under `Contents/MacOS` as a nested code object and refuses
the whole bundle at the first non-Mach-O one:

    <app>: code object is not signed at all
    In subcomponent: .../Contents/MacOS/arxmcp-desktop-child/_internal/tools/sbom.sh

This is a property of the **location**, not of this payload. The A/B control in
`TestOuterSeal::test_the_location_control_separates_layout_from_payload` builds
two one-file `.app` trees differing only in where a six-byte `data.txt` sits:
`Contents/MacOS/` is refused, `Contents/Resources/` seals and reports "valid on
disk / satisfies its Designated Requirement". Nothing arXMCP-specific is
involved, and the control re-runs on every gate run rather than being quoted
from a log.

**Handling.** Decision 2 is Accepted and was NOT relitigated. `seal_app`
attempts the seal, records the outcome and the exact error, and `assemble`
continues; the gate pins `sealed is False` so a future OS or toolchain change
turns the gate red and forces a re-record rather than silently improving.
Every nested Mach-O IS signed (180 files, verified on both executables); what
is absent is the bundle-level seal.

This is precisely the condition the ADR's rejected alternative **R3** names as
the trigger for revisiting the `frameworks` route — "if and only if a notary
trial rejects the hybrid on grounds of unsigned or improperly-sealed nested
code" — reached without a notary submission. **Escalated to the owner and the
critic as a decision-level input, not resolved by me.**

---

## Incidental finding: the committed icon was corrupt

`apps/desktop/crates/supervisor/icons/icon.png` was a 1×1 PNG whose IDAT chunk
CRC did not match its data. Nothing had ever decoded it, because `bundle.active`
was `false` for the whole life of the file; the first `tauri build` failed
outright on it. Replaced with a deterministic 512×512 RGBA placeholder and
guarded by `TestIconIsDecodable`, which walks every chunk's CRC.

---

## Scope report (mid-flight rule)

`git diff --stat 3f21248..HEAD` → **11 files changed, 1728 insertions(+),
24 deletions(-)**. The 350-LOC / 6-file threshold was crossed and is reported
rather than absorbed; `allow_large_diff` was set for this dispatch and the
estimate was ~900 LOC / ~10 files. The overrun is concentrated in the two new
test modules (693 + 226 = 919 LOC of the 1728), which carry the AC evidence and
the two recorded-non-claim controls. Authored-vs-generated split: all authored
except the 3,632-byte binary icon.

I did not abort at 350: the milestone has no partial-but-coherent stopping
point — flipping `bundle.active` without the assembly step produces an `.app`
with no payload, and the payload placement without the gate produces an
unmeasured artifact, which is the exact failure mode the owner's acceptance
record warns against.

---

## Files touched

- `apps/desktop/crates/supervisor/tauri.conf.json` — `active: true`,
  `targets: ["app"]`; no `resources`/`externalBin`/`frameworks`.
- `apps/desktop/crates/supervisor/src/main.rs` — `--print-child-plan`
  diagnostic; corrected `child_payload_root` doc comment.
- `apps/desktop/crates/supervisor/icons/icon.png` — regenerated (was corrupt).
- `apps/desktop/pyinstaller/desktop_package.py` — the assembly layer
  (`ensure_tauri_cli`, `presign_payload`, `build_app_shell`, `place_payload`,
  `seal_app`, `measure_macos_seal_location_control`,
  `measure_adhoc_signature_stability`, `assemble`) + the `assemble` subcommand.
- `apps/desktop/README.md` — new "Assembled artifact layout"; corrected
  "Child payload layout"; corrected intro.
- `Makefile` — `desktop-bundle`, `desktop-bundle-check`, help lines.
- `pyproject.toml` + `tests/conftest.py` — `requires_desktop_bundle` marker.
- `CLAUDE.md` §4.5 — twelve → thirteen markers, with the new one's entry
  (`tests/test_marker_doc_consistency.py` re-derives this and would have failed).
- `tests/test_desktop_bundle.py` — new (693 LOC).
- `tests/test_desktop_notarization_claims.py` — new (226 LOC).

---

## Deliberately not done

- **The full AC3 claim** — "reaches a ready server and a rendered window" from
  a genuine double-click is NOT proven. That needs the ~4.6 GB external model
  cache, which is m8's `requires_bundled_model` surface, and a GUI session. The
  strongest launch evidence here is the frozen **probe** executed out of the
  assembled bundle (real FAISS add+search plus Torch compute, exit 0), which
  proves the placed, signed payload runs. Stated as what it is.
- **Raising the frozen executables' `minos` to 14.0.** Needs a rebuilt
  PyInstaller bootloader; separate decision, separate hash pins.
- **Enabling hardened runtime.** Needs entitlements nobody has authored.
- **Moving the payload to `Contents/Resources` or `Contents/Frameworks`.**
  That is Decision 2 / R3 territory and belongs to the owner.
- **Widening m9's compatibility scanner.** Left byte-identical.
- **Any notarization work.** e4's.

## external_writes_required

- `git push origin main` (from the research briefs; not performed)
- `cargo install tauri-cli` fetches from crates.io on first provision — a new
  external dependency fetch in the build path, pinned by `--locked --version`.
- An Apple notary submission would be required to settle Decision 3. Out of
  scope for m15.

## Test deltas

- `tests/test_desktop_bundle.py` — NEW. 40 fast + 16 gated tests.
- `tests/test_desktop_notarization_claims.py` — NEW. 16 tests.
- No existing test file was modified. `tests/conftest.py` gained one marker
  name; `tests/test_desktop_support_floor.py` is byte-identical.

## Check gate results

- `make test PYTHON=.venv/bin/python` — **PASS, exit 0**.
  `5187 passed, 118 skipped, 1 xfailed` in 214.59s. (`ruff check .` clean,
  run inside the target.)
- `make desktop-conformance PYTHON=.venv/bin/python` — **PASS, exit 0**.
  `cargo fmt --check`, `cargo test --locked --workspace`,
  `cargo clippy -D warnings` all clean; 42 + 30 + 33 + 24 = 129 tests passed,
  zero skips.
- `make desktop-bundle-check` equivalent (`DESKTOP_BUNDLE_GATE=1` over both new
  modules with the tautology `-m`) — **PASS, exit 0**, `56 passed`, zero skips.
  Run against a real assembled bundle.
- Exit codes captured with `echo $?` on their own line, never through a pipe
  (the m6 lesson).
- `git status --porcelain`: clean after commit.

## Branching note

Repo policy is main-only (CLAUDE.md §4.1). `git checkout main` is mechanically
unavailable from this worktree because the shared checkout holds `main`, so the
commit landed on `worktree-agent-acea46e67ef8a92bd` off the dispatched base
`3f21248`. The orchestrator fast-forwards.
