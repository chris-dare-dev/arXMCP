# Implementation plan — desktop-distribution-m9

- **What:** pin every macOS floor declaration to 14.0 (the measured hard inherited
  floor) and record UNVERIFIED status precisely; declarations + docs only, no
  macOS 14 verification claim anywhere.
- **Files:** `apps/desktop/crates/supervisor/tauri.conf.json` (add
  `bundle.macOS.minimumSystemVersion: "14.0"` — key path verified against
  `tauri-utils 2.9.3` `MacConfig`, serde `rename = "macOS"`, field
  `minimum_system_version` camelCase); NEW repo-root `.cargo/config.toml` with
  `[env] MACOSX_DEPLOYMENT_TARGET = { value = "14.0", force = true }` — chosen over
  Makefile-only export because cargo config discovery walks up from CWD, so it
  covers `make desktop-conformance` (runs from repo root), the README's manual
  commands, and any invocation from inside `apps/desktop/`; `force = true` so an
  ambient override cannot silently desync the artifact from the declaration;
  `apps/desktop/README.md` ("Supported boundary" gains INHERITED/HARD/UNVERIFIED
  paragraphs matching the spike-3 non-claims tone); NEW
  `tests/test_desktop_support_floor.py`.
- **Check commands:** the four gates (fmt, clippy, desktop-conformance, make test),
  plus `otool -l` on both rebuilt binaries proving `minos 14.0`, plus a
  demonstrated failure of the new regression against a temporarily added
  unearned claim.
- **Regression shape (AC4):** assert the three declarations agree at "14.0";
  assert the README carries the required honesty markers (`macosx_14_0_arm64`
  citation, UNVERIFIED, minos-is-not-a-runtime-gate); scan the shipped doc set
  (root README, apps/desktop/README, CHANGES.md, docs/**/*.md) for
  claim-verb + "macOS 14" patterns with a negation-cue exemption, with positive
  and negative scanner controls in the test itself (repo norm: a checker that
  reports zero because it is broken looks like a clean checker).
- **Delivery actions expected:** one local GPG-signed commit on `main`; NO push
  (per-event authorization, not requested). No external writes.
- **Deviations from brief:** none of substance. The brief's §6 roadmap-wording
  changes are out of scope here (roadmap lives outside this milestone's ACs);
  the README + declarations + regression are the milestone's surface.
