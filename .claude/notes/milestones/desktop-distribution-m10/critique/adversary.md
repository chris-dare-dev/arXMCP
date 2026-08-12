# Critique — desktop-distribution-m10 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** b102c85..3327edb
**Diff stats:** 6 files, 991 insertions / 10 deletions (760 / 10 across the 4 non-notes files)
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES. The self-authoring arm is well-built and the RED-state
discipline is genuine — the runtime regression fails against any tree where
the arm was not wired, not merely asserting the new arm succeeds. Two real
defects sit outside the code under test: the workspace README still states in
the present tense that launch-plan authoring is not here yet, and the
self-authored plan hard-codes the Rust crate version as the *Python* child's
identity version, an unpinned cross-language coupling that every committed
gate is structurally blind to because the fixture compiles the same constant.
The scope-fenced `.app` gap is correctly out of scope and is not filed.

## Executive summary

- [CRITICAL] `apps/desktop/README.md:7` still says "launch-plan authoring [is] not here yet" — the exact deliverable this diff lands, in the README the workspace's own code cites.
- [HIGH] `compose_self_authored_plan` sets `version: env!("CARGO_PKG_VERSION")` (Rust workspace `0.1.0`), but the real child compares against `importlib.metadata.version("arxmcp")`; the two agree only by coincidence today and nothing pins them.
- [HIGH] Mandatory diff-size auto-finding: 991/10 total, 760/10 excluding notes, both over 400, with `allow_large_diff: false` in `state.json`.
- [MEDIUM] AC5's "byte-for-byte" parity is false for path-normalizing values — reproduced live against the built binary: `HOME=/a//b` and `HOME=/a/./b` give Rust `/a//b/…` vs Python `/a/b/…`. Production is benign (later canonicalization), the AC's wording is not.
- [MEDIUM] The `DESKTOP_FIXTURE_COMPONENT` residual-risk entry argues its safety backwards: `lifecycle.rs` strips ONLY `ARXMCP_*`, so a non-prefixed variable is *inherited* by the child — that property is what makes the knob deliverable, not undeliverable. The real safety rests on the fixture shipping nowhere, which is stated separately.
- [MEDIUM] CLAUDE.md §4.5's `requires_desktop_stack` prose still scopes the marker to m5/m6 "boot the ACTUAL server" tests; m10 adds 13 marked tests that boot the fixture instead.
- [MEDIUM] `arxmcp-server-desktop-child` and `arxmcp-desktop-child` are copied literals in Rust and in the new Python module rather than derived from `server/desktop_child.py::COMPONENT` and `arxmcp_desktop.spec`, so the fixture-based gate is self-consistent and blind to a rename.
- [LOW] `--print-data-root` is an ungated test seam living in the production binary, while the same milestone's `validate_plan` refuses test knobs outside smoke mode.

## Findings

**C1 — Workspace README says launch-plan authoring is not here yet** (CRITICAL)

**Where:** `apps/desktop/README.md:7`
**Anchor:** `release signing, and launch-plan authoring a`
**What:** The README's opening paragraph asserts in the present tense that "The frozen Python runtime, release signing, and launch-plan authoring are not here yet; those belong to the next desktop milestones", which this diff falsifies for launch-plan authoring (and which m7 already falsified for the frozen Python runtime, now living at `apps/desktop/pyinstaller/`).
**Why it matters:** `apps/desktop/README.md` is the load-bearing orientation document for this workspace and is cited from its own source (`process_control.rs`); a reader following it will conclude the supervisor still requires `ARXMCP_DESKTOP_LAUNCH_PLAN` and that no self-authoring path exists — the exact misreading that made this milestone's brief wrong in the first place, and the same "do not yet" pattern already corrected once at m5.
**Proposed fix:** Amend the sentence to name what has landed: the frozen Python runtime is under `apps/desktop/pyinstaller/` (m7) and launch-plan self-authoring is in `crates/supervisor/src/main.rs::self_authored_plan` (m10, reading m7's onedir as a sibling of the supervisor executable), leaving release signing and `.app` assembly (m15) as the outstanding items. One sentence, no structural change.
**Regression-guard:** Extend `tests/test_desktop_support_floor.py` with a scan asserting `apps/desktop/README.md` contains no "not here yet"/"do not yet" claim naming a directory or symbol that resolves in the tree — the same derived-from-disk shape that file already uses for the minOS declarations.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**H1 — Self-authored plan names the Rust crate version as the Python child's identity** (HIGH)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:212`
**Anchor:** `version: env!("CARGO_PKG_VERSION").to_owne`
**What:** `compose_self_authored_plan` hard-codes the supervisor crate's `CARGO_PKG_VERSION`, but `server/desktop_child.py:182` refuses a launch whose `executable.version` differs from `identity.version`, and that value is `importlib.metadata.version("arxmcp")` (`server/desktop_child.py:88-95`) — the Python distribution version, with a `"0+unknown"` exception fallback.
**Why it matters:** The two are `0.1.0` today only by coincidence (`apps/desktop/Cargo.toml:10` and `pyproject.toml:103`); bumping either one alone, or any bundle in which `importlib.metadata` cannot see the `arxmcp` dist-info, makes the real frozen child refuse every self-authored launch with "executable identity mismatch" — and no committed gate can see it, because the fixture sidecar validates against its OWN `CARGO_PKG_VERSION`, which is the same workspace constant. Every environment-supplied plan avoids this by reading the version FROM the child (`tests/test_desktop_child.py:423`); only the new arm hard-codes it.
**Proposed fix:** Pin the coupling with an unmarked test in the m10 module that parses `apps/desktop/Cargo.toml`'s `[workspace.package] version` and `pyproject.toml`'s `[project] version` and asserts equality, with a failure message naming this arm as the consumer — mirroring the three-declaration agreement check `tests/test_desktop_support_floor.py` already runs for the minOS floor. Record in the `compose_self_authored_plan` doc comment that the field is the CHILD's version and only happens to be derivable from the crate.
**Regression-guard:** `tests/test_desktop_self_authored_launch.py::test_self_authored_plan_version_matches_the_python_distribution` — unmarked, so it runs on every `make test`.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**H2 — Diff exceeds the 400-LOC defect-detection cliff** (HIGH)

**Where:** no specific file
**What:** The range is 991 insertions / 10 deletions across 6 files; excluding `.claude/` notes and agent memory it is 760 / 10 across 4 files, against a pre-authorized estimate of ~520 LOC, and `state.json` carries `"allow_large_diff": false` — so unlike the m6/m7/m8/m10 precedents on the ui-uplift track there is no recorded waiver.
**Why it matters:** Review quality degrades measurably past ~400 changed lines, and this diff crosses it on the code files alone; the pipeline's own 350-line checkpoint was passed and reported rather than acted on.
**Proposed fix:** Not waivable by the implementer — record the overrun and its justification at the orchestrator level, or split. For the record, the comment-density defence holds up on inspection but the arithmetic in the synthesis is wrong in the implementer's own favour: `main.rs` gained 355 lines, not 363, of which 115 (32%) are `//`/`///`/`//!` lines and 16 are blank, leaving ~224 lines of code. The comments carry real content (the `current_exe()` residual risk, the AC2-vacuity argument, the frozen-vs-source identity split, the one Python divergence) and are not padding.
**Regression-guard:** N/A — procedural.
**Source critic:** milestone-adversary-critic
**Source axis:** Diff size

**M1 — AC5's byte-for-byte parity fails on path-normalizing env values** (MEDIUM)

**Where:** `tests/test_desktop_self_authored_launch.py:302`
**Anchor:** `_PARITY_MATRIX: tuple[dict[str, str], ...] =`
**What:** The 9-row matrix varies only WHICH variable is read, never the SHAPE of its value, and the Rust and Python implementations disagree on values that `pathlib` normalizes: Python's `Path()` collapses `//` and `/./`, Rust's `PathBuf::join` preserves them. Reproduced live against the built `apps/desktop/target/debug/supervisor` on 2026-08-11 — `HOME=/a//b` gives Rust `/a//b/Library/Application Support/arXMCP` vs Python `/a/b/…`; `HOME=/a/./b` and `USERPROFILE=/p/./q` diverge the same way; `HOME=/a/`, `HOME=//net/share` and `XDG_DATA_HOME=/x//y` all agree.
**Why it matters:** AC5 asks for byte-for-byte agreement "across a matrix of the platform env vars each branch reads", and the matrix's own docstring claims a wrong-variable port "would diverge on one of these" — true, but it silently excludes the value-normalization class, so the executable pin is narrower than both the AC and the docstring say. Production consequence is nil (`self_authored_plan` canonicalizes `data_root` after `create_dir_all`, and `ApplicationPaths.resolve` calls `.resolve()`), which is exactly why this is MEDIUM and not HIGH — but the divergence is real and undocumented.
**Proposed fix:** Either add the normalizing rows and make the Rust side match (fold the derived path through `Path::components()`), or — cheaper and more honest — add the rows with the divergence asserted as a second documented exception alongside the `Path.home()` one, and narrow the docstring to say the pin covers variable SELECTION and canonical values, with normalization deliberately out of scope because both consumers canonicalize.
**Regression-guard:** Optional — extend `_PARITY_MATRIX` with `{"HOME": "/a//b"}` and `{"HOME": "/a/./b"}`.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**M2 — The fixture-override residual risk argues its safety backwards** (MEDIUM)

**Where:** `.claude/notes/milestones/desktop-distribution-m10/implement/synthesis.md:165`
**Anchor:** `5. **`DESKTOP_FIXTURE_COMPONENT` widens the`
**What:** The residual-risk entry reassures with "(so `lifecycle.rs`'s `ARXMCP_*` scrub could never deliver it)", but `lifecycle.rs:167-169` removes only keys starting with `ARXMCP_` and otherwise inherits the supervisor's whole environment — so a NON-prefixed variable is precisely the kind that IS delivered to the child, which is how `test_self_authored_launch_reaches_ready_and_window` delivers it. The non-prefix is an enablement property, not a containment one; the code comment at `fixture-sidecar/src/main.rs:15-21` states it correctly, the risk register inverts it.
**Why it matters:** A residual-risk register whose mitigation is backwards is worse than one that omits the risk — a later reader will reason that no ambient value can reach the fixture and skip the check that actually matters. The genuine containment argument is the one stated separately in the same bullet (the fixture crate ships nowhere: `tauri.conf.json` has `bundle.active: false`, no `externalBin`, and no test asserts the fixture refuses a foreign component, so nothing silently degrades either).
**Proposed fix:** Replace the parenthetical with the true argument: the variable IS inherited by the child (nothing scrubs a non-`ARXMCP_` key), and containment rests entirely on the fixture-sidecar binary never appearing in a shipped artifact — which `tauri.conf.json`'s `bundle.active: false` and the absent `externalBin` key make structurally true today and which m15 must re-check when it turns bundling on.
**Regression-guard:** Optional — an m15-scoped assertion that `tauri.conf.json`'s bundle inputs never name `fixture-sidecar`.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**M3 — CLAUDE.md's requires_desktop_stack prose no longer describes the marker** (MEDIUM)

**Where:** `CLAUDE.md:297`
**Anchor:** `- **`requires_desktop_stack`** — desktop-dis`
**What:** The marker's documentation scopes it to "desktop-distribution-m5/m6 real-lifecycle tests that boot the ACTUAL server … and/or the built Tauri supervisor binary", and enumerates the m6 fault matrix, the 30-cycle orphan stress and the socket-level loopback proof; m10 adds 13 tests under the same marker that boot the fixture sidecar and a new `desktop-conformance` line, and none of that is reflected.
**Why it matters:** `tests/test_marker_doc_consistency.py` re-derives only the marker NAMES and count from `pyproject.toml`, so prose drift of this kind is unguarded — and this section is exactly where an agent looks to learn what `make desktop-conformance` proves, which now includes the only line in that target that runs with `ARXMCP_DESKTOP_LAUNCH_PLAN` absent.
**Proposed fix:** Append one clause naming m10: the marker also covers the self-authored-launch module, whose end-to-end arm drives the fixture sidecar staged in m7's onedir shape rather than the real server, and whose `desktop-conformance` line is the only one with the plan variable deliberately unset.
**Regression-guard:** Optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**M4 — Component and payload-directory names are copied literals, not derived** (MEDIUM)

**Where:** `tests/test_desktop_self_authored_launch.py:61`
**Anchor:** `CHILD_COMPONENT = "arxmcp-server-desktop-chi`
**What:** `arxmcp-server-desktop-child` exists as a literal in `main.rs:55`, in this test module at :61, and in `server/desktop_child.py:69`; `arxmcp-desktop-child` exists in `main.rs:51`, at :58 here, and as `arxmcp_desktop.spec`'s `EXE`/`COLLECT` `name=`. The module already imports `_platform_data_root` from `server.application_paths`, so importing `server.desktop_child.COMPONENT` would have been free, and the spec name has no pin at all.
**Why it matters:** Because the end-to-end arm stages its own directory using its own literal and drives a fixture that is told the component name via `DESKTOP_FIXTURE_COMPONENT`, the whole proof is self-consistent: rename `COMPONENT` in `desktop_child.py`, or `name=` in the spec, and the self-authored plan points at a directory that does not exist or names a component the real child refuses — with `make test` and `make desktop-conformance` both still green. This is the same blind spot as the version finding, one level down.
**Proposed fix:** Import `COMPONENT` from `server.desktop_child` in the test module instead of re-declaring it, and add an unmarked assertion that `main.rs`'s `CHILD_COMPONENT` and `CHILD_PAYLOAD_DIR` literals equal `server.desktop_child.COMPONENT` and the `name=` parsed out of `apps/desktop/pyinstaller/arxmcp_desktop.spec` respectively — a source-text scan is adequate and matches the existing `test_the_pre_m10_required_plan_failure_no_longer_exists` shape.
**Regression-guard:** Optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Test discipline

**L1 — Ungated test seam in the production binary** (LOW)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:383`
**Anchor:** `if std::env::args().nth(1).as_deref() == So`
**What:** `--print-data-root` is checked unconditionally at the top of `main()` in every build, including a release one, while the same milestone's `validate_plan` refuses the five test-only plan knobs outside smoke mode.
**Why it matters:** It is a small, self-consistent inconsistency rather than a vulnerability — the flag prints only a path derived from the caller's own environment and exits — but it establishes an argv-shaped test surface with no gate and no assertion that it is inert on the production path, which is the sort of seam that grows.
**Proposed fix:** Either wrap the probe in `#[cfg(debug_assertions)]` (the conformance builds are debug, so the parity test is unaffected while a release binary loses the seam), or leave it and add one line to the doc comment recording the deliberate decision that a diagnostic argv flag is acceptable where a plan knob is not.
**Regression-guard:** Optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Dead code / leftovers

**L2 — AC3's m8 clause is satisfied by non-reachability, not by evidence** (LOW)

**Where:** `.claude/notes/milestones/desktop-distribution-m10/implement/synthesis.md:33`
**Anchor:** `- **AC3 — the environment path is byte-ident`
**What:** AC3 names "the m5 lifecycle, m6 fault matrix, and m8 frozen-child gates"; the synthesis answers only for `tests/test_desktop_child.py` (m5/m6, run green under `desktop-conformance`) and never mentions m8, whose gate is `make desktop-model-check` / `make desktop-package-check` and was not run by either the implementer or the orchestrator.
**Why it matters:** The clause is in fact satisfied — `tests/test_desktop_bundled_model.py` contains no reference to the supervisor or to `ARXMCP_DESKTOP_LAUNCH_PLAN` (verified by grep at `3327edb`), so a supervisor-and-fixture-only diff cannot reach it — but that reasoning appears nowhere, so the AC reads as answered when it was actually skipped.
**Proposed fix:** Add one sentence to the AC3 bullet recording that the m8 gate was not run and why it does not need to be: `tests/test_desktop_bundled_model.py` neither drives the supervisor nor writes the plan variable, so the diff is structurally out of its reach.
**Regression-guard:** Optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

## What was done well

- **The RED state genuinely discriminates.** `test_red_state_missing_payload_still_exits_two` asserts the documented `exit(2)` AND that the pre-m10 reason string is absent from stderr, so it fails against any tree where the arm was not wired — the discriminating shape the brief demanded, not the "assert the new arm succeeds" shape it forbade. The unmarked source-scan half runs on every `make test`, so a revert is caught without the desktop stack.
- **AC2's vacuity was closed the way the research asked.** `compose_self_authored_plan` was extracted specifically so the `child_argv.is_empty()` branch is reachable on a plan this code authored, and the positive test additionally pins `smoke == false` and all five knobs `None`.
- **The cross-language parity is pinned by RUNNING both**, via a diagnostic flag rather than by inspection — and the one deliberate divergence (Python's `Path.home()` fallback vs Rust refusing) is asserted on both sides so it cannot quietly become two. I re-derived the matrix independently against the built binary; every row shape it ships agrees exactly.
- **The containment check is the real thing.** `resolve_inside` canonicalizes both sides and uses component-wise `starts_with`, and the escape test stages an actual symlink whose literal path is under the root — a string-prefix implementation would pass that test's setup and fail its assertion.
- **The residual risks are recorded rather than implied closed** — `current_exe()`'s non-primitive status appears in the doc comment, the module docstring and the synthesis, and the sibling-directory write-access class was added by the implementer rather than inherited from the brief.
- **The environment arm is guarded from both sides.** Not just "`test_desktop_child.py` is untouched" but a positive test that a staged tree with a perfectly good payload plus a malformed supplied plan still fails on the supplied plan — which catches a supervisor that silently preferred the layout.
- **The Makefile line arms the zero-skip guard correctly**, exporting BOTH `DESKTOP_SUPERVISOR_BIN` and `ARXMCP_FIXTURE_SIDECAR`, so the new evidence cannot go missing behind a green run — the m6 finding stays rectified.
- **The token scan is a faithful extension of the m6 technique**, and it is non-vacuous: `redact.rs`'s own documentation confirms the `StartupToken` is 64 lowercase hex, exactly what `_HEX64` matches, and the `allowed` set is the same identity-digest construction `test_desktop_child.py:488` uses.
- **Commit hygiene is clean.** Both commits are GPG-signed (`%G? = G`), carry `Co-Authored-By: Claude Opus 5`, use in-repo types and scopes, and the range touches no `plans/`, no roadmap, and performs no external write.

Severity counts: C1 H2 M4 L2

## Recommended rectification order

C1, H1, M2, M4, M1, M3, L2, L1, H2
