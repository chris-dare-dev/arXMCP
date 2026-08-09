# Implement synthesis — desktop-distribution-m9

## Built

- **AC1 — tauri.conf.json declares 14.0:**
  `apps/desktop/crates/supervisor/tauri.conf.json:12-14` adds
  `bundle.macOS.minimumSystemVersion: "14.0"`. Key path verified against the
  crate source, not guessed: `tauri-utils 2.9.3` `src/config.rs:1680`
  (`#[serde(rename = "macOS")]` on `BundleConfig.macos`) and `:642-646`
  (`minimum_system_version`, camelCase, default `10.13` at `:691-693`). The
  config is parsed at compile time by `tauri::generate_context!`
  (`supervisor/src/main.rs:279`), so the supervisor build itself validates the
  key — a wrong path would have failed `cargo build` (MacConfig is
  `deny_unknown_fields`).
- **AC2 — binaries report minos 14.0 on the gate path:** new repo-root
  `.cargo/config.toml` sets `[env] MACOSX_DEPLOYMENT_TARGET = { value = "14.0",
  force = true }`. Mechanism chosen deliberately: cargo config discovery walks
  up from the invocation CWD, so a repo-root file covers `make
  desktop-conformance` (runs from `$(CURDIR)` = repo root), every manual
  command in `apps/desktop/README.md` (documented as run from the repo root),
  and any invocation from inside `apps/desktop/` — where a Makefile-only
  `export` would cover only the make path and a crate-local
  `apps/desktop/.cargo/` would cover only in-directory invocations (cargo
  discovers config from CWD, **not** from `--manifest-path`). `force = true`
  because a non-forced entry yields to an ambient
  `MACOSX_DEPLOYMENT_TARGET`, which would silently desync the built artifact
  from the declared floor — the exact disagreement this milestone exists to
  close. Evidence below.
- **AC2 hazard found and closed — warm-cache stale minos:** cargo does NOT
  fingerprint `[env]` for the linker. Observed live: after adding the pin, the
  first rebuild produced supervisor `minos 14.0` (rebuilt because its
  tauri.conf.json input changed) but fixture-sidecar **stale at `minos 11.0`**
  (considered fresh). Fixed by declaring the env var a tracked build input:
  `cargo:rerun-if-env-changed=MACOSX_DEPLOYMENT_TARGET` in a new
  `apps/desktop/crates/fixture-sidecar/build.rs` and prepended in
  `apps/desktop/crates/supervisor/build.rs`. A future floor bump now relinks
  both binaries from any cache state instead of shipping a mixed declaration.
- **AC3 — README:** `apps/desktop/README.md` "Supported boundary" gains two
  paragraphs: (1) the floor is INHERITED and HARD — the single
  `macosx_14_0_arm64` faiss_cpu 1.13.2 wheel with no lower-tagged arm64
  fallback, 132/200 Mach-O files at minOS 14.0, measured 2026-08-09 — and the
  three agreeing declaration sites; (2) the floor is UNVERIFIED — `minos` is a
  build-time declaration, not a runtime gate (the brief's `minos 30.0` dyld
  control cited), no component has ever executed on macOS 14, no macOS 14 SDK
  exists on the development machine (oldest 15.2), the M4 Max cannot boot
  macOS 14 even virtualized, and "nothing contradicts it" is stated as not
  being "it works" (the ObjC/WebKit runtime-resolution blind spot named).
  Tone matches the spike-3 non-claims block: DECLARED, not exercised.
- **AC4 — regression:** new `tests/test_desktop_support_floor.py` (11 tests,
  in the default `make test` run, no marker):
  - declaration agreement: tauri.conf.json == `.cargo/config.toml` (value AND
    `force = true`) == README quoted pin, all at the single `FLOOR = "14.0"`
    constant;
  - README honesty markers required verbatim: `macosx_14_0_arm64`,
    INHERITED/HARD, UNVERIFIED, "build-time declaration" + "not a runtime
    gate";
  - unearned-claim scan over the shipped doc set (root README, CHANGES.md,
    apps/desktop/README.md, docs/**/*.md — deliberately NOT `.claude/`, whose
    research briefs legitimately quote claim-shaped rows): claim-verb +
    "macOS 14" patterns with a same-sentence negation-cue exemption, so "No
    component has ever been executed on macOS 14" passes while "tested on
    macOS 14" fails;
  - scanner controls both ways (repo norm: a checker reporting zero because it
    is broken looks clean): three positive controls (bare test/works/supported
    claims flagged), two negative controls (negated statement, release-target
    phrasing), plus a laundering control (negation in an *earlier* sentence
    does not exempt the claim after it);
  - doc-set non-emptiness asserted ("empty output is not zero").
- **AC5 — gates:** all green, see below.

## Failure demonstration (AC4 "do not ship an assertion you have not seen fail")

Temporarily appended `The supervisor was tested on macOS 14 and works on
macOS 14.` to `apps/desktop/README.md`, ran the suite:

```
FAILED tests/test_desktop_support_floor.py::TestNoUnearnedClaimInShippedDocs::test_shipped_docs_carry_no_unearned_macos14_claim
AssertionError: macOS 14 compatibility claims with no recorded macOS 14 test run:
{'apps/desktop/README.md': ['tested on macOS 14', 'works on macOS 14']}. A claim
may land only together with the run evidence and a revision of this gate ...
1 failed, 10 passed in 0.14s
```

README then restored from a scratchpad copy; `git diff --stat` confirmed only
the intended 28-line addition remained.

## otool evidence (the gate-built artifacts, after `make desktop-conformance`)

```
== apps/desktop/target/debug/supervisor ==
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform 1
    minos 14.0
      sdk 26.5
== apps/desktop/target/debug/fixture-sidecar ==
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform 1
    minos 14.0
      sdk 26.5
```

(Pre-change baseline was `minos 11.0` on both, matching the brief.)

## Branching note

Committed directly on `main` per CLAUDE.md §4.1 (single-user project, all work
lands on `main`, no feature branches). Commit `0b11bbc`, parent `2f319af` — the
exact dispatched BASE_SHA; no concurrent commit interleaved. Staged explicit
paths only; `.gitignore` and `build/` (owned by the concurrent session)
untouched.

## Files touched

- `apps/desktop/crates/supervisor/tauri.conf.json` — `bundle.macOS.minimumSystemVersion: "14.0"`
- `.cargo/config.toml` — NEW; forced `MACOSX_DEPLOYMENT_TARGET=14.0` env pin
- `apps/desktop/crates/fixture-sidecar/build.rs` — NEW; rerun-if-env-changed relink guard
- `apps/desktop/crates/supervisor/build.rs` — same guard prepended before `tauri_build::build()`
- `apps/desktop/README.md` — INHERITED/HARD/UNVERIFIED floor paragraphs
- `tests/test_desktop_support_floor.py` — NEW; the AC4 regression (11 tests)

## Deferred

- No macOS 14 execution, SDK-level symbol check at 14.x, VM, hardware purchase,
  or hosted-runner setup — out of scope by milestone definition; the README and
  brief record what discharging UNVERIFIED requires (a macOS 14 Mac or hosted
  runner).
- Roadmap `[SHOULD]` rewording (brief §6.1–6.2) — roadmap file is outside this
  milestone's ACs; the regression + README carry the honesty guarantees.
- No macOS-14-run evidence sentinel path was invented; the gate's contract is
  that a claim lands only alongside the evidence and a same-commit revision of
  the gate (stated in the test docstring and failure message).

## external_writes_required

- []  (commit is local; push NOT performed — per-event authorization per
  CLAUDE.md §4.4 happens in the main session)

## Test deltas

- Added `tests/test_desktop_support_floor.py` (11 tests). No existing test
  modified. Suite total 5091 → 5102.

## Check gate results

- `cargo fmt --all -- --check`: PASS
- `cargo clippy --workspace --all-targets --all-features -- -D warnings`: PASS
- `make desktop-conformance PYTHON=.venv/bin/python`: PASS (exit 0; 42 passed +
  29 passed, zero skips)
- `make test PYTHON=.venv/bin/python`: PASS (5102 passed, 60 skipped,
  1 xfailed, exit 0 — baseline 5091/60/1, no regression)
- git status: clean except the untracked milestone notes dir and the concurrent
  session's `build/`
