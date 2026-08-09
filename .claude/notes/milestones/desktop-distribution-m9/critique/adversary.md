# Critique — desktop-distribution-m9 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** 2f319af..0b11bbc
**Diff stats:** 6 files, 207 LOC (+207 / -1)
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES. The declarations are now truthful, the mechanism is the right
one, the honesty prose is unusually well-evidenced, and the commit is signed,
trailered, conventional, and touches no roadmap or plans file. Two gaps are
real: nothing asserts that a BUILT binary declares 14.0 — the one drift this
milestone actually observed — and the unearned-claim regression, measured
against the shipped module, misses 8 of 10 realistic claim phrasings including
"macOS 14 support is verified." Neither breaks anything today; both leave the
gate weaker than the README says it is.

## Executive summary

- [HIGH] The suite pins three *declarations* and never inspects an *artifact*; the warm-cache `minos 11.0` fixture-sidecar the implementer hit by hand has no regression guard, and `make desktop-conformance` would exit 0 with it.
- [HIGH] Measured against the shipped scanner, "macOS 14 support is verified.", "tested successfully on macOS 14", "runs fine on macOS 14", "macOS 14 compatibility confirmed", "ran the full suite on macOS 14.4", and a table cell `| macOS 14 | tested |` all pass; so does a real claim laundered by an unrelated "no" earlier in the same sentence.
- [MEDIUM] AC4 says "no document **or event**"; the scanner reads documents only, and its doc set is hand-listed rather than derived from the tree — the odd one out among this repo's honesty gates.
- [MEDIUM] The README states the M4-Max-cannot-boot-14 fact flatly; the spike marks that exact claim **(inferred)** and says it cannot be measured here.
- [MEDIUM] "every imported dynamic symbol exists in the macOS 15.2 SDK stubs" is stated categorically; the spike's own method note calls the check lenient by construction (it can under-report a missing symbol).
- [LOW] "Run these commands from the repository root" is now correctness-bearing — cargo finds `.cargo/config.toml` by CWD, not by `--manifest-path` — but still reads as a convenience.
- No CRITICALs. External-write boundary, one-writer rule, commit hygiene, dependency hygiene, and blast radius all clean; the `[env] force = true` pin is correctly scoped and inert off macOS.
- Diff is 207 LOC, under the 400-LOC review-quality threshold; no auto-finding.

## Findings

**H1 — No test asserts a built binary declares minos 14.0** (HIGH)

**Where:** `tests/test_desktop_support_floor.py:108`
**Anchor:** `class TestDeclaredFloorAgreement:`
**What:** The suite pins `tauri.conf.json`, `.cargo/config.toml`, and the README to 14.0, but nothing reads `LC_BUILD_VERSION` off a built `supervisor` or `fixture-sidecar`, so the declaration↔artifact agreement that this milestone exists to establish is verified once by hand in the commit message and never again.
**Why it matters:** This is not hypothetical — the implementer observed exactly this drift (a warm-cache `fixture-sidecar` at `minos 11.0` while every declaration read 14.0), and the `rerun-if-env-changed` guards mitigate only the cache arm; cargo discovers `.cargo/config.toml` by walking up from the **CWD**, not from `--manifest-path`, so any invocation whose CWD is outside the repo root silently rebuilds at rustc's 11.0 default while the whole suite stays green.
**Proposed fix:** Add a darwin-only, `requires_desktop_stack`-marked test that reads the binaries named by `DESKTOP_SUPERVISOR_BIN` and `ARXMCP_FIXTURE_SIDECAR` — both already exported by `Makefile:160-161`, so the gate arms it for free — parses `minos` from `otool -l` (or the Mach-O load commands directly) and asserts `== FLOOR`. Per the m6 `lsof` precedent, RAISE rather than skip when the tool or the env var is absent inside the gate, so the check cannot degrade to a silent skip.
**Regression-guard:** `tests/test_desktop_support_floor.py::TestBuiltArtifactDeclaresTheFloor::test_binaries_report_the_declared_minos`
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**H2 — The unearned-claim scanner misses the most natural claim phrasings** (HIGH)

**Where:** `tests/test_desktop_support_floor.py:37`
**Anchor:** `_CLAIM_PATTERNS = tuple(`
**What:** Executed against the shipped module, `_find_unearned_claims` returns empty for 8 of 10 realistic claim sentences: "macOS 14 support is verified.", "The supervisor was tested successfully on macOS 14.", "The app runs fine on macOS 14.", "macOS 14 compatibility confirmed on the release runner.", "We ran the full suite on macOS 14.4 and it was green.", "The bundle installs cleanly on macOS 14.", the table cell `| macOS 14 | tested |`, and "There is no CI yet, and the app runs on macOS 14." — the last because `_NEGATION_CUES` exempts a match whenever ANY cue appears earlier in the same sentence, regardless of whether it governs the claim.
**Why it matters:** AC4 requires the regression to fail when a compatibility claim appears without a macOS 14 run; as shipped it fails only on phrasings adjacent to the two the implementer demonstrated against, so the calibration is to its own demo — and both the README ("fails … if a macOS 14 compatibility claim lands in the shipped docs") and the module docstring ("an unearned claim anywhere in the shipped doc set fails the suite") state the guarantee unconditionally.
**Proposed fix:** Three cheap changes. (a) Permit up to ~3 intervening tokens between the evidence verb and the `on|against|under` preposition (`\b(?:test|verif|…)\w*(?:\s+\w+){0,3}\s+(?:on|against|under)\s+{_MACOS_14}`), and add noun-form adjacency in both directions (`macOS 14 (support|compatibility) … (is|was)? (verified|confirmed|tested)`). (b) Narrow the negation exemption so the cue must govern the match — require it within a few tokens before the matched verb, or cut the window at the nearest preceding comma/clause boundary — otherwise an unrelated "no" laundering a real claim is the default failure. (c) If a regex is accepted as best-effort, say so in the module docstring and soften the README sentence to match, rather than letting the doc over-promise the gate.
**Regression-guard:** Extend `TestScannerControls` with each of the seven measured bypasses above as positive-control cases.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**M1 — AC4's "or event" half is unscanned and the doc set is hand-listed** (MEDIUM)

**Where:** `tests/test_desktop_support_floor.py:76`
**Anchor:** `def _shipped_docs() -> list[Path]:`
**What:** The scan surface is an enumerated list (root `README.md`, `CHANGES.md`, the desktop README, `docs/**`), so it covers no source or event vocabulary — while AC4 reads "No document **or event** claims macOS 14 compatibility" — and misses the other root-allowlisted shipped files (`SECURITY.md`, `CONTRIBUTING.md`, `OWNERS.md`, `CONTRIBUTORS.md`).
**Why it matters:** The event half is satisfied only vacuously (no source string mentions macOS 14 today, verified by grep across `apps/desktop/crates/**`), so a user-facing supervisor string or a new shipped root doc lands outside the gate by construction — and every other honesty gate in this repo (`test_wheel_packaging`, `test_assert_ban`, `test_marker_doc_consistency`) derives its surface from the on-disk tree precisely so this cannot happen.
**Proposed fix:** Derive the doc set — root `*.md` minus the agent-facing `CLAUDE.md`/`AGENTS.md`, plus `docs/**/*.md` and `apps/**/README.md` — and add the event/user-string surface (`apps/desktop/crates/**/*.rs`, `server/desktop_child.py`) to the same scan. `test_doc_set_is_nonempty_and_covers_the_desktop_readme` already guards the empty-set arm; extend it to assert the derived set contains the root README and at least one source file.
**Regression-guard:** Optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**M2 — An inferred hardware fact is restated as measured** (MEDIUM)

**Where:** `apps/desktop/README.md:38`
**Anchor:** `(Apple M4 Max) cannot boot macOS 14 at al`
**What:** The README asserts flatly that the machine "cannot boot macOS 14 at all, including in a VM, because no macOS 14 build supports its SoC"; the spike states the same conclusion but marks it **(inferred)** and adds "it was not, and cannot be, measured by attempting an install here" (`.claude/notes/spikes/desktop-distribution-macos-floor.md:344-346`).
**Why it matters:** The whole product of this milestone is the distinction between measured and inferred; dropping the marker on the single load-bearing inference — the one that justifies never discharging the verification here — reintroduces in miniature the failure mode the milestone closes.
**Proposed fix:** One clause: "…because, per Apple's documented platform policy, no macOS 14 build supports its SoC (inferred — corroborated by the hardware ID and by this host's SDK inventory bottoming out at 15.2, not measured by attempting an install)."
**Regression-guard:** Optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**M3 — The symbol-analysis result is stated more strongly than the method supports** (MEDIUM)

**Where:** `apps/desktop/README.md:39`
**Anchor:** `macOS 14 build supports its SoC. Static a`
**What:** "every imported dynamic symbol exists in the macOS 15.2 SDK stubs" is a categorical claim, but the spike's own method note records that the check tokenizes whole `.tbd` files rather than parsing them, which "makes the check **lenient**, not strict — it can under-report a missing symbol, never over-report one" (`.claude/notes/spikes/desktop-distribution-macos-floor.md:440-444`).
**Why it matters:** The sentence is the README's only positive evidence, and it is the one most likely to be quoted forward; as written it reads as an exhaustive proof of absence rather than a lenient scan with bounded but non-zero leniency.
**Proposed fix:** "…a deliberately lenient symbol scan (whole-`.tbd` tokenization, with negative and sensitivity controls) found no imported dynamic symbol absent from the macOS 15.2 SDK stubs — and 15.2 is one major above the floor." The existing "but 'nothing contradicts it' is not 'it works'" clause then carries the right weight.
**Regression-guard:** Optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**L1 — A build instruction is now correctness-bearing but reads as convenience** (LOW)

**Where:** `apps/desktop/README.md:59`
**Anchor:** `Run these commands from the repository ro`
**What:** Cargo resolves `.cargo/config.toml` by walking up from the CWD, not from `--manifest-path`, so "Run these commands from the repository root" is now the precondition that makes the documented `--target-dir` invocations produce `minos 14.0`; the sentence is justified in the next breath only by "A temporary Cargo target keeps generated binaries out of the source tree."
**Why it matters:** A reader who runs the same `--manifest-path` command from elsewhere gets a silently 11.0 binary with no gate objecting (see H1).
**Proposed fix:** Append one clause to that sentence — the repo-root `.cargo/config.toml` deployment-target pin is discovered from the CWD, so a cargo invocation started outside the repo root builds at rustc's 11.0 default.
**Regression-guard:** Optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

## What was done well

- The mechanism is the right one and correctly scoped: `[env]` in a repo-root `.cargo/config.toml` covers every crate under the tree (including `tools/desktop_lifecycle_spike`) with no per-crate duplication, and is inert on Linux/Windows, so a contributor on another OS is unaffected.
- `force = true` is the non-obvious correct choice, and the reason is recorded where it is read: an ambient `MACOSX_DEPLOYMENT_TARGET` would desync artifact from declaration without failing anything.
- The `rerun-if-env-changed` guards close a footgun the implementer discovered empirically (warm cache keeping `fixture-sidecar` at 11.0 while `supervisor` rebuilt at 14.0), and both `build.rs` comments state the cargo behaviour rather than narrating the change.
- `TestScannerControls` proves both arms of the scanner rather than only the flagging arm, with the negative controls (`test_accepts_the_release_target_phrasing`) doing genuine work — a target is correctly not a claim.
- The README distinguishes DECLARED from EXERCISED explicitly, cites the single `macosx_14_0_arm64` wheel as the reason the floor is HARD, and includes the `minos 30.0` control — the strongest and least intuitive fact in the spike — rather than the comfortable half of it.
- The tauri key path was verified against `tauri-utils 2.9.3`'s `MacConfig` rather than assumed, and the 10.13 default it displaces is named in both the config comment and the test's failure message.
- Commit hygiene is clean: conventional subject at 38 chars after the prefix, `%G?` = G, `Co-Authored-By` naming the authoring model, body stating gate results and the demonstrated-failing regression.
- No roadmap, `plans/`, or `state.json` progress edit; no external write; no new dependency; 207 LOC, well inside the review-quality threshold.
- Scope discipline held: the milestone explicitly does not verify macOS 14, and nothing in the diff — README, test names, or commit body — implies the support floor is discharged or that the other four release blockers moved.

Severity counts: C0 H2 M3 L1

## Recommended rectification order

H1, H2, M1, M3, M2, L1
