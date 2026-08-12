# Critique (merged) — desktop-distribution-m10

**Critics:** milestone-adversary-critic, milestone-arxmcp-critic, milestone-infra-safety-critic
**Commit range:** b102c85..3327edb
**Diff stats:** 6 files, 991 insertions / 10 deletions (760 / 10 across the 4 non-notes files)
**Critique format version:** 1.0

> **Merge note.** Each critic authored its ids from 1 within its own file, so
> they collided across files. `findings.py merge` renumbered them into one
> gapless per-severity sequence in critic dispatch order; bodies are verbatim.
> **Phase 4 dispositions attach to the MERGED ids below**, not to the ids in
> the per-critic files. Re-running merge after a critic file changes will shift
> these ids - see milestone-pipeline-critique-format.md.
>
> - `milestone-adversary-critic` (adversary.md): ids unchanged
> - `milestone-arxmcp-critic` (arxmcp.md): H1->H3, M1->M5, M2->M6, M3->M7, M4->M8, M5->M9, M6->M10, M7->M11, L1->L3, L2->L4, L3->L5
> - `milestone-infra-safety-critic` (infra-safety.md): H1->H4, M1->M12, M2->M13, M3->M14, M4->M15, M5->M16, L1->L6, L2->L7, L3->L8

## Verdict

**SHIP-WITH-FIXES** — the most severe of the per-critic verdicts below.

### milestone-adversary-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES. The self-authoring arm is well-built and the RED-state
discipline is genuine — the runtime regression fails against any tree where
the arm was not wired, not merely asserting the new arm succeeds. Two real
defects sit outside the code under test: the workspace README still states in
the present tense that launch-plan authoring is not here yet, and the
self-authored plan hard-codes the Rust crate version as the *Python* child's
identity version, an unpinned cross-language coupling that every committed
gate is structurally blind to because the fixture compiles the same constant.
The scope-fenced `.app` gap is correctly out of scope and is not filed.

### milestone-arxmcp-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES

The self-authoring arm is well-built and unusually honest about what it does not
prove, and both gates are green — but the milestone's central deliverable, a
double-clicked launch reaching a ready child, depends on three literals
hand-copied across the Rust/Python boundary with no executable pin, and the one
that carries real risk (`version`) is a second, independently-maintained release
string whose agreement with `pyproject.toml` is coincidental today. That hazard
is structurally invisible to the GREEN arm because it runs against a Rust fixture
in the supervisor's own Cargo workspace, so the very substitution the
implementation discloses is what hides it. No CRITICAL: nothing is broken at this
tip, and the environment arm is genuinely preserved.

### milestone-infra-safety-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES

The self-authoring arm is the most carefully-reasoned change in this tree's desktop
track — the containment check is genuinely component-wise on canonicalized paths, the
data-root port is pinned by RUNNING both implementations, and the one deliberate
divergence from Python is asserted rather than described. The gap is that the same
"pin it by execution, never by inspection" rule the milestone states for `data_root`
is NOT applied to the two hand-copied constants that decide which binary gets
executed and whether the child is accepted (H1), and the fixture override quietly
converts the only arm-level identity check into a tautology (M3). Nothing here is a
security regression against the shipped surface; the residual-risk record is broadly
honest, though it ranks the two `current_exe()` classes backwards (M1).

## Executive summary — milestone-adversary-critic

- [CRITICAL] `apps/desktop/README.md:7` still says "launch-plan authoring [is] not here yet" — the exact deliverable this diff lands, in the README the workspace's own code cites.
- [HIGH] `compose_self_authored_plan` sets `version: env!("CARGO_PKG_VERSION")` (Rust workspace `0.1.0`), but the real child compares against `importlib.metadata.version("arxmcp")`; the two agree only by coincidence today and nothing pins them.
- [HIGH] Mandatory diff-size auto-finding: 991/10 total, 760/10 excluding notes, both over 400, with `allow_large_diff: false` in `state.json`.
- [MEDIUM] AC5's "byte-for-byte" parity is false for path-normalizing values — reproduced live against the built binary: `HOME=/a//b` and `HOME=/a/./b` give Rust `/a//b/…` vs Python `/a/b/…`. Production is benign (later canonicalization), the AC's wording is not.
- [MEDIUM] The `DESKTOP_FIXTURE_COMPONENT` residual-risk entry argues its safety backwards: `lifecycle.rs` strips ONLY `ARXMCP_*`, so a non-prefixed variable is *inherited* by the child — that property is what makes the knob deliverable, not undeliverable. The real safety rests on the fixture shipping nowhere, which is stated separately.
- [MEDIUM] CLAUDE.md §4.5's `requires_desktop_stack` prose still scopes the marker to m5/m6 "boot the ACTUAL server" tests; m10 adds 13 marked tests that boot the fixture instead.
- [MEDIUM] `arxmcp-server-desktop-child` and `arxmcp-desktop-child` are copied literals in Rust and in the new Python module rather than derived from `server/desktop_child.py::COMPONENT` and `arxmcp_desktop.spec`, so the fixture-based gate is self-consistent and blind to a rename.
- [LOW] `--print-data-root` is an ungated test seam living in the production binary, while the same milestone's `validate_plan` refuses test knobs outside smoke mode.

## Executive summary — milestone-arxmcp-critic

- [HIGH] The self-authored plan pins the child's expected `version` to the
  SUPERVISOR crate's `CARGO_PKG_VERSION`, while the real frozen child reports
  `importlib.metadata.version("arxmcp")` — two unlinked strings, both `0.1.0`
  only by coincidence. A bump of either makes every double-clicked launch die at
  `executable identity mismatch`, and no gate catches it.
- [MEDIUM] `CHILD_COMPONENT` is hand-copied from `server/desktop_child.py::COMPONENT`
  with no pin, and the new `DESKTOP_FIXTURE_COMPONENT` override makes the GREEN
  arm's component equality true by construction — the one check that would have
  caught the copy is the one the test disarms.
- [MEDIUM] `CHILD_PAYLOAD_DIR` is hand-copied from `arxmcp_desktop.spec`'s
  `name=`; the test stages the directory from its own copy of the same literal,
  so a spec rename is green in both languages and dead in production.
- [MEDIUM] `platform_data_root` has a SECOND undocumented divergence from Python
  (`XDG_DATA_HOME`/`LOCALAPPDATA` set, no `HOME`/`USERPROFILE`), reachable on
  Linux, and `test_data_root_parity_has_exactly_one_documented_divergence`
  asserts a claim the matrix cannot support.
- [MEDIUM] The only executable pin between the ported function and its Python
  original runs behind `requires_desktop_stack`; `make test` — the repo's stated
  authority — never runs it, and `server/application_paths.py` carries no
  back-pointer telling an editor a Rust port exists.
- [MEDIUM] `assert len(spawned) == 1` is captioned as proving the child came from
  the payload root; the `child-spawn` event records only `child_pid`, so nothing
  in the module asserts provenance.
- [MEDIUM] `std::env::args()` panics on non-UTF-8 argv and now sits at the first
  statement of `main()` on every platform, replacing the controlled `exit(2)`
  contract on exactly the launch path this milestone adds.
- [MEDIUM] 770 code LOC against a pre-authorized ~520 budget; disclosed, not
  excused, and comment/test-dominated.

## Executive summary — milestone-infra-safety-critic

- [HIGH] `CHILD_COMPONENT` and `CHILD_PAYLOAD_DIR` are hand-copied literals with no executable pin to `server/desktop_child.py::COMPONENT` or `desktop_package.BUNDLE_NAME`/`CHILD_EXE` — a rename breaks the shipped double-click path with every gate green.
- [MEDIUM] The sibling-directory execution-selection trust assumption (write access next to the supervisor = arbitrary code execution) lives only in `implement/synthesis.md`; it is absent from `apps/desktop/README.md`, `SECURITY.md`, the `resolve_inside` doc comment, and m15's acceptance criteria.
- [MEDIUM] `resolve_inside` canonicalizes the payload root but never establishes that the root IS a real directory under the supervisor's own parent, so a symlinked payload root passes containment — while the comment claims a symlink out of the root cannot.
- [MEDIUM] `DESKTOP_FIXTURE_COMPONENT` also rewrites the fixture's `Bound` echo, so the supervisor's bound-identity equality is satisfied by construction on the only end-to-end proof of the new arm.
- [MEDIUM] The Windows branch of the ported `platform_data_root` is reachable by neither gate (the parity matrix cannot run it; the Rust unit test `cfg!`s it away on this host) and carries no source-level pin.
- [MEDIUM] `smoke: false` is a first-of-its-kind plan shape and its teardown SIGKILLs the child, so the stdin-EOF lease and the bounded shutdown ladder are unasserted on the arm that actually ships.
- [LOW] `make desktop-conformance` neither serializes nor isolates the shared `apps/desktop/target/debug` tree and fixed loopback ports across its six pytest lines.
- [LOW] Supervisor stderr is captured to an undrained `PIPE` across a 180 s launch; a chatty webkit run can block the supervisor on a full pipe.

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

**H3 — Self-authored plan pins child version to the supervisor crate** (HIGH)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:212`
**Anchor:** `        version: env!("CARGO_PKG_VERSION").to_`
**What:** `compose_self_authored_plan` sets the plan's expected child `version` to the supervisor crate's `CARGO_PKG_VERSION` (`apps/desktop/Cargo.toml` `[workspace.package].version = "0.1.0"`), but the real frozen child reports `importlib.metadata.version("arxmcp")` (`server/desktop_child.py:88-93`), which comes from `pyproject.toml:103` — a separately maintained string that happens to also read `0.1.0` today.
**Why it matters:** `server/desktop_child.py:182` refuses the launch frame outright with `DesktopContractError("executable identity mismatch")` on a version difference, so the first release that bumps either version string turns every double-clicked launch — the entire deliverable of this milestone — into a hard boot failure, and the m10 GREEN arm cannot see it because its child is the fixture sidecar, a crate in the supervisor's own Cargo workspace that inherits the identical `version.workspace = true`.
**Proposed fix:** Do not derive the child's expected version from the supervisor's crate. Either (a) read it from a build-time constant generated from `pyproject.toml` (the same source m7's bundle ships), or (b) follow `tests/test_desktop_child.py:423`'s existing pattern and derive the plan's `version` from the payload's own recorded identity rather than asserting one. Whichever is chosen, add an UNMARKED test that parses `pyproject.toml`'s `[project].version` and `apps/desktop/Cargo.toml`'s `[workspace.package].version` and fails when the self-authored plan would name the wrong one.
**Regression-guard:** A new unmarked `tests/` assertion pinning `compose_self_authored_plan`'s version source against `pyproject.toml [project].version`, so it fails on a Python-side bump without needing `make desktop-conformance`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**H4 — Bundle-layout and component constants pinned by inspection only** (HIGH)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:55`
**Anchor:** `const CHILD_COMPONENT: &str = "arxmcp-ser`
**What:** `CHILD_COMPONENT` (`main.rs:55`) and `CHILD_PAYLOAD_DIR` (`main.rs:51`) are string literals duplicated a third and fourth time in `tests/test_desktop_self_authored_launch.py:58,61`, and nothing in the tree asserts them equal to their real sources — `server/desktop_child.py:69::COMPONENT`, and `apps/desktop/pyinstaller/desktop_package.py:41-42::BUNDLE_NAME`/`CHILD_EXE` (which the `arxmcp_desktop.spec` `name=` at :158/:218 owns).
**Why it matters:** These two constants decide which binary the supervisor executes and whether it will accept the child that answers. A rename of the onedir bundle or of the frozen child's component makes the shipped double-click path fail at spawn or at bound-identity, while `make test`, `make desktop-conformance`, and `make desktop-package-check` all stay green — the self-authored test stages its own directory from its own literal and drives the fixture with its own literal, so both sides of the comparison move together. The milestone's own stated rule ("agreement is asserted by running BOTH implementations — never by inspection", `main.rs:22-25`) is applied to `data_root` and not to the pair that selects the executable.
**Proposed fix:** In `tests/test_desktop_self_authored_launch.py`, replace both literals with imports — `from server.desktop_child import COMPONENT as CHILD_COMPONENT`, and a path-loaded `desktop_package` module for `BUNDLE_NAME`/`CHILD_EXE` exactly as `tests/test_desktop_package.py` already does with its `dp` alias — and add one UNMARKED test that reads the two `const` lines out of `main.rs` and asserts they equal those Python values. Unmarked so a rename fails on every `make test`, not only under the desktop stack.
**Regression-guard:** A new unmarked `tests/test_desktop_self_authored_launch.py::test_rust_layout_constants_match_their_python_sources` that parses `const CHILD_PAYLOAD_DIR` / `const CHILD_COMPONENT` from `main.rs` and asserts equality with `desktop_package.BUNDLE_NAME` and `server.desktop_child.COMPONENT`.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — build-script discipline (mapped: cross-artifact constant pinning in the conformance gate)

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

**M5 — CHILD_COMPONENT hand-copied, and the GREEN arm disarms the check** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:55`
**Anchor:** `const CHILD_COMPONENT: &str = "arxmcp-serve`
**What:** The component string is copied by hand from `server/desktop_child.py:69`, and the new `DESKTOP_FIXTURE_COMPONENT` override makes the fixture answer to whatever the test names, so the supervisor's bound-identity comparison for the component field is satisfied by construction in the only end-to-end test that exercises it.
**Why it matters:** A rename of `server/desktop_child.py::COMPONENT` leaves the self-authored plan naming a component the frozen child will refuse, and both `make test` and `make desktop-conformance` stay green — the substitution the module docstring discloses (fixture for frozen child) also silently removes the last check on this literal.
**Proposed fix:** Add an unmarked test that reads `server/desktop_child.py`'s `COMPONENT` and the Rust `CHILD_COMPONENT` constant from source and asserts equality (the repo already does exactly this style of derived pin in `tests/test_marker_doc_consistency.py` and `tests/test_wheel_packaging.py`). Independently, record in the test module docstring that the component half of the identity comparison is not proven by the GREEN arm.
**Regression-guard:** `tests/test_desktop_self_authored_launch.py` unmarked assertion `CHILD_COMPONENT == server.desktop_child.COMPONENT`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M6 — CHILD_PAYLOAD_DIR unpinned against the PyInstaller spec name** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:51`
**Anchor:** `const CHILD_PAYLOAD_DIR: &str = "arxmcp-desk`
**What:** The onedir directory and executable name are hand-copied from `apps/desktop/pyinstaller/arxmcp_desktop.spec:158` / `:218`; the Python test re-declares the same literal at `tests/test_desktop_self_authored_launch.py:57` and stages the directory from its own copy, so the test never reads the spec.
**Why it matters:** Renaming the spec's `name=` — which m15 is explicitly expected to touch when it re-points the containment check at the bundle root — leaves the self-authoring arm exiting 2 with `child payload root missing` in production while every gate stays green, because the fixture layout is built from the stale literal on both sides.
**Proposed fix:** Derive the constant on the test side from the spec (`re`-extract `name=` from `arxmcp_desktop.spec`, or import the value m7's `desktop_package.py` already carries) and assert it equals the Rust `CHILD_PAYLOAD_DIR`, in the same unmarked test proposed for M1.
**Regression-guard:** Unmarked assertion that the spec's `EXE`/`COLLECT` `name=` equals `CHILD_PAYLOAD_DIR` in `main.rs`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M7 — A second, undocumented divergence from _platform_data_root** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:149`
**Anchor:** `            .ok_or("self-authored plan: no HOM`
**What:** The port refuses whenever neither `HOME` nor `USERPROFILE` is set, but Python only uses `home` as a *fallback* for the platform base — with `XDG_DATA_HOME` set and no `HOME` (Linux), or `LOCALAPPDATA` set and no `USERPROFILE`/`HOME` (Windows), `_platform_data_root` returns a real path and never touches `Path.home()`, while Rust errors out.
**Why it matters:** The doc comment at `main.rs:136-142` and the test named `test_data_root_parity_has_exactly_one_documented_divergence` (`tests/test_desktop_self_authored_launch.py:337`) both assert exactly ONE divergence; there are two, the second is reachable on Linux (a platform the matrix does run on), and no `_PARITY_MATRIX` row sets `XDG_DATA_HOME` without `HOME`, so the assertion of exhaustiveness is unearned rather than merely optimistic.
**Proposed fix:** Add `{"XDG_DATA_HOME": "/parity/xdg"}` and `{"LOCALAPPDATA": "C:/parity/local"}` rows to `_PARITY_MATRIX`; then either move the `home` lookup below the platform branch so it is only evaluated when the branch actually needs it (matching Python), or widen the doc comment and the test name to record two divergences instead of one.
**Regression-guard:** The two new `_PARITY_MATRIX` rows — on Linux they fail today against the current port.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first + Docker constraint

**M8 — The cross-language pin never runs under `make test`** (MEDIUM)

**Where:** `server/application_paths.py:81`
**Anchor:** `def _platform_data_root(env: Mapping[str, `
**What:** `_platform_data_root` now has a Rust duplicate, but the file carries no marker saying so, and the only assertion holding the two together is `requires_desktop_stack`-marked, i.e. deselected by default since issue #206 and run only by `make desktop-conformance`.
**Why it matters:** CLAUDE.md §4.1 names `make test` as the authority a change must be green under before pushing; an agent editing this Python function — the exact silent-drift hazard both m10 research briefs named — gets a fully green `make test` with the Rust half already diverged, and nothing in the Python file points at the port.
**Proposed fix:** Add a one-line comment above `_platform_data_root` naming `apps/desktop/crates/supervisor/src/main.rs::platform_data_root` and the gate that pins them (`make desktop-conformance`), so drift ownership is legible at the edit site. Optionally strengthen with an unmarked test that hashes the Python function's source and fails when it changes without the Rust file changing in the same commit.
**Regression-guard:** Not strictly required at MEDIUM; the comment is the minimum, an unmarked source-pin test is the durable form.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M9 — Test comment claims provenance the assertion does not check** (MEDIUM)

**Where:** `tests/test_desktop_self_authored_launch.py:284`
**Anchor:** `        assert len(spawned) == 1, _events(ro`
**What:** The caption above this line reads "The spawned child is the one inside the payload root, not an ambient binary of the same name", but the assertion only counts spawn events; `lifecycle.rs:174` records `child-spawn` with `{"child_pid": ...}` and no path, so the event carries nothing that could prove provenance.
**Why it matters:** This is the milestone's containment story at the end-to-end level, and a reader (or a Phase-4 rectifier) will take the caption as the guarantee — the real proof lives only in `lifecycle.rs`'s digest comparison, which the module never names, so a regression that resolved `child_argv[0]` outside the payload root would be caught by the Rust unit test alone and this assertion would keep passing.
**Proposed fix:** Either add `child_path` to the `child-spawn` event payload and assert it is under `supervisor.parent / CHILD_PAYLOAD_DIR`, or rewrite the caption to say what is actually asserted (exactly one spawn cycle) and cross-reference `child_executable_escaping_the_payload_root_is_rejected` as where containment is proven.
**Regression-guard:** Optional at MEDIUM; the durable form is the `child_path` field plus a containment assertion in `test_self_authored_launch_reaches_ready_and_window`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M10 — `std::env::args()` panics on non-UTF-8 argv, now on every launch** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:383`
**Anchor:** `    if std::env::args().nth(1).as_deref() ==`
**What:** `std::env::args()` is documented to panic if any argument is not valid Unicode; the pre-m10 use at `:360` was inside `notify_running_instance`, i.e. macOS-only and reachable only on the single-instance loser path, whereas this call is now the first statement `main()` executes on every platform and every launch.
**Why it matters:** The supervisor's whole failure contract is a controlled `fail()` → `exit(2)` with a named reason; a non-UTF-8 argument (an `open --args` invocation, a mis-encoded desktop entry, a relaunch carrying a filename argument) now aborts with a Rust panic message instead, on precisely the double-click path this milestone exists to make survivable.
**Proposed fix:** One-line change to `std::env::args_os().nth(1).as_deref() == Some(std::ffi::OsStr::new(DATA_ROOT_PROBE_ARG))`, which cannot panic and compares identically for the ASCII flag.
**Regression-guard:** A Rust or Python test launching the staged supervisor with a non-UTF-8 argv byte and asserting `exit(2)` (or a normal launch) rather than a panic exit code.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security threat-model coverage

**M11 — Diff scope 770 code LOC against a ~520 pre-authorized budget** (MEDIUM)

**Where:** no specific file
**What:** `git diff --stat b102c85..3327edb` is 991 insertions / 10 deletions over 6 files; excluding the notes commit, 770 insertions over 4 files, against the brief's measured ~520 LOC / ~7 files estimate.
**Why it matters:** The critique-format calibration anchors put a diff over 400 LOC at HIGH; it is demoted here because the overrun is dominated by comment prose (~90 of 363 added `main.rs` lines) and a 377-line test module rather than by unreviewed production logic, and because the implementer reported the 350-line checkpoint crossing rather than crossing it silently.
**Proposed fix:** No code change. Record the overrun in the milestone's rectify notes so the epic's remaining LOC estimates (m15 in particular, which re-points the same functions) are re-based off the measured 770 rather than the original ~520.
**Regression-guard:** Not applicable — process finding.
**Source critic:** milestone-arxmcp-critic
**Source axis:** open scan

**M12 — Sibling-write execution risk recorded only in a per-milestone note** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:178`
**Anchor:** `/// RESIDUAL RISK, recorded not closed: the r`
**What:** The `resolve_inside` doc comment records only the PATH-search and Linux-hardlink `current_exe()` classes; the class this design actually adds — the payload root is a SIBLING directory, so anyone who can write next to the installed supervisor chooses `child_argv[0]` — appears only in `.claude/notes/milestones/desktop-distribution-m10/implement/synthesis.md` residual risk 2, and in neither `apps/desktop/README.md`, `SECURITY.md`, nor m15's acceptance criteria.
**Why it matters:** The two classes are ranked backwards for this deployment. The supervisor is not setuid/setgid, so an attacker who can steer `current_exe()` by PATH search or hardlink is already executing code as the invoking user and gains nothing — whereas the sibling-write class needs no trick at all and is the one an installer, an unpacked-in-Downloads copy, or a group-writable install directory makes real. `apps/desktop/README.md` is exactly where m15's AC7 says the artifact layout must be recorded, and m15 chooses the bundle mechanism; if the assumption is not there, that choice can be made without it.
**Proposed fix:** Add a short "child payload layout and its trust assumption" section to `apps/desktop/README.md` stating the `<supervisor dir>/arxmcp-desktop-child/arxmcp-desktop-child` convention, that write access to that directory is equivalent to arbitrary code execution as the operator, and that the defense is install-location permissions plus m15/e4 code signing. Amend the `main.rs:178` comment to name the sibling-write class first and to say why the PATH/hardlink classes carry no privilege gradient here.
**Regression-guard:** optional
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 1 — container/process hygiene (mapped: process-execution trust boundary)

**M13 — Containment never validates the payload root itself** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:185`
**Anchor:** `let canonical_root =`
**What:** `resolve_inside` canonicalizes the root and the candidate and requires the candidate to be inside the canonical root, but the root is whatever `supervisor_exe.parent()/arxmcp-desktop-child` canonicalizes TO (`main.rs:225-229`). If that entry is itself a symlink to `/tmp/evil`, `canonical_root` becomes `/tmp/evil`, the candidate resolves to `/tmp/evil/arxmcp-desktop-child`, containment holds, and an arbitrary binary is executed. The unit test at `main.rs:637` stages a symlinked CHILD, never a symlinked ROOT.
**Why it matters:** The doc comment claims "a symlink out of the payload root cannot [pass]" and the synthesis says canonicalize-then-contain "closes the ordinary relocated- or tampered-sidecar case". Relocation via a symlinked root is precisely an ordinary relocated-sidecar case and it is not closed. The trust domain is the same one M1 describes, so this is a claim-vs-check mismatch rather than a new privilege boundary — but the claim is what m15 will rely on when it re-points the check at the bundle root.
**Proposed fix:** Before canonicalizing, require the payload root to be a real directory whose canonical parent equals the canonical parent of `supervisor_exe` (compare `fs::canonicalize(supervisor_exe.parent()?)` against `canonical_root.parent()`), or take `symlink_metadata` on the root and refuse a symlink. Either is a few lines inside `resolve_inside`; then the comment's claim is true as written.
**Regression-guard:** optional — a `#[cfg(unix)]` sibling to `child_executable_escaping_the_payload_root_is_rejected` that symlinks the payload ROOT out of the staging base and asserts refusal.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 1 — container/process hygiene (mapped: path-containment correctness)

**M14 — Fixture echo makes the arm's bound-identity check tautological** (MEDIUM)

**Where:** `apps/desktop/crates/fixture-sidecar/src/main.rs:285`
**Anchor:** `component: expected_component(),`
**What:** `DESKTOP_FIXTURE_COMPONENT` loosens the fixture's inbound equality check (`:236`) AND rewrites the identity the fixture echoes back in `make_bound` (`:285`), so the supervisor's bound-identity comparison ends up comparing the plan's component against itself. The one end-to-end proof of the new arm (`tests/test_desktop_self_authored_launch.py:259`) therefore cannot distinguish a correct `CHILD_COMPONENT` from any other string.
**Why it matters:** The echo rewrite is what turns a test-only relaxation into a lost assertion: with it, m10's GREEN arm proves plan authoring and spawn, not identity binding, and there is no other arm-level identity evidence (H1's constant is unpinned; `tests/test_desktop_child.py:863` pins only the Python side). The commit comment calls this keeping the comparison "an honest equality check" — it is honest but vacuous.
**Proposed fix:** Keep the override for the inbound check but have the GREEN test additionally assert the negative: one run with `DESKTOP_FIXTURE_COMPONENT` left UNSET against a self-authored plan naming `CHILD_COMPONENT` must fail to reach `child-bound`, proving the equality is load-bearing. Alternatively echo `COMPONENT` unchanged and assert the supervisor's refusal reason.
**Regression-guard:** optional
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — build-script discipline (mapped: test-harness override scope)

**M15 — Windows data-root branch is reachable by neither gate and unpinned** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:151`
**Anchor:** `let base = if cfg!(target_os = "windows") {`
**What:** The 9-row parity matrix (`tests/test_desktop_self_authored_launch.py:302`) runs the real binary, so on this host it can only ever exercise the macOS branch; the Rust unit test compares against a `cfg!`-selected expectation, so it also cannot see the Windows branch. Nothing pins the Windows arm of either implementation, and the new module skips wholesale on win32.
**Why it matters:** Drift shows up as data bifurcation with no error: the double-clicked application derives root A while `ApplicationPaths`, the CLI, and every ops tool derive root B, so the app looks like it has an empty corpus and the operator's ingest lands somewhere the app never reads. The Python function is also private (`_platform_data_root`), now cross-language load-bearing, with its only executable pin gated behind `requires_desktop_stack` — a Python-side edit is invisible to plain `make test`.
**Proposed fix:** Add one UNMARKED test that (a) monkeypatches `sys.platform` to `"win32"` and asserts `_platform_data_root` output for a fixed `LOCALAPPDATA`/`USERPROFILE` row, and (b) asserts the Rust Windows branch source text at `main.rs:151-153` still reads `LOCALAPPDATA` with the `home/AppData/Local` fallback. A one-sided edit then fails on every `make test` instead of waiting for a Windows runner that does not exist.
**Regression-guard:** optional
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — build-script discipline (mapped: gate reachability of a ported function)

**M16 — Bounded shutdown and no-orphan unasserted on the smoke:false arm** (MEDIUM)

**Where:** `tests/test_desktop_self_authored_launch.py:212`
**Anchor:** `os.kill(pid, signal.SIGKILL)`
**What:** Every supervisor plan in `tests/test_desktop_child.py` is `smoke: true` (`:422`, `:948`), so the self-authored arm is the first `smoke: false` launch any gate has run — the first where the supervisor does not self-exit after a cycle. Its teardown SIGTERMs the supervisor and then unconditionally SIGKILLs every recorded `child-spawn` pid, so the stdin-EOF parent-lifetime lease (`apps/desktop/crates/supervisor/src/lifecycle.rs:50`) and the `RunEvent::Exit` grace→TERM→KILL ladder are never observed on this arm; an orphan and a clean reap produce the same green result.
**Why it matters:** The no-orphan invariant is m6's central claim and the operator-visible failure is a full server with BGE-M3 resident and a loopback port held after the window closes. The mechanism is shared code and is proven under `smoke: true`, which is why this is a coverage gap rather than a demonstrated bug — but m10 introduces the shape that ships and does not carry the evidence onto it.
**Proposed fix:** In `_reap`, after `process.terminate()` and the 15 s wait, assert each spawned pid is gone BEFORE falling back to SIGKILL — keeping the SIGKILL as an unconditional safety net after the assertion is recorded, so a failing run still leaves no orphan behind. Roughly five lines, and it turns the lease into an asserted property of the production arm.
**Regression-guard:** optional
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — build-script discipline (mapped: cleanup evidence on the new gate line)

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

**L3 — `--print-data-root`'s side-effect-free claim is unasserted** (LOW)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:60`
**Anchor:** `const DATA_ROOT_PROBE_ARG: &str = "--print-`
**What:** The doc comment states the probe "authors no plan, spawns nothing, and touches no filesystem state", but no test asserts it; every `_PARITY_MATRIX` row uses an uncreatable path (`/parity/home`, `C:/parity/local`), so a regression that created the derived root would fail to create it and go unnoticed rather than being caught.
**Why it matters:** This is a diagnostic flag on the SHIPPED supervisor binary, and its safety guarantee is the only reason adding it to a production surface is acceptable.
**Proposed fix:** Add one row using a `tmp_path`-derived writable `HOME` and assert the derived data root does NOT exist after the probe exits.
**Regression-guard:** Optional at LOW.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security threat-model coverage

**L4 — Source-guard test recognizes only `//`-prefixed comment lines** (LOW)

**Where:** `tests/test_desktop_self_authored_launch.py:83`
**Anchor:** `        if PRE_M10_FAILURE in line and not line`
**What:** The RED-state source guard classifies a line as "live" unless it is lstrip-prefixed with `//`; a `/* ... */` block comment, or a trailing `// ...` after code on the same line, would be misclassified in either direction.
**Why it matters:** The guard is the only unmarked (every-`make test`) protection against a revert of the self-authoring arm, so a false negative retires it silently.
**Proposed fix:** Match on the `fail(` call shape instead of the bare string — e.g. flag any line containing `fail("` and `PRE_M10_FAILURE` — which is what "live" actually means here.
**Regression-guard:** Optional at LOW.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**L5 — CLAUDE.md §4.5's `requires_desktop_stack` description not amended** (LOW)

**Where:** `CLAUDE.md:1`
**Anchor:** `# CLAUDE.md — Context for Claude agents wor`
**What:** §4.5's `requires_desktop_stack` bullet enumerates the m5/m6 lifecycle and fault-matrix tests as what the marker covers; m10 added a fourth `desktop-conformance` line and a new marked module without amending it, and `tests/test_marker_doc_consistency.py` re-derives only the marker COUNT and names, not their descriptions.
**Why it matters:** §4.5 is the section an agent reads to learn what `make desktop-conformance` proves; the doc now understates the gate, which is the same hand-maintained-snapshot drift §3 already warns about.
**Proposed fix:** One sentence in the `requires_desktop_stack` bullet naming `tests/test_desktop_self_authored_launch.py` and the fact that it is the only conformance line running with `ARXMCP_DESKTOP_LAUNCH_PLAN` deliberately absent.
**Regression-guard:** Optional at LOW.
**Source critic:** milestone-arxmcp-critic
**Source axis:** open scan

**L6 — desktop-conformance is concurrency-sensitive and says nothing about it** (LOW)

**Where:** `Makefile:175`
**Anchor:** `ARXMCP_FIXTURE_SIDECAR="$(CURDIR)/apps/de`
**What:** All six pytest lines in `desktop-conformance` point at the same `apps/desktop/target/debug` binaries and the same fixed loopback ports, and the target carries no lock, no per-invocation temp/port isolation, and no comment telling an operator (or a parallel agent session) that two simultaneous runs interfere. The 30-cycle orphan stress is the most sensitive line.
**Why it matters:** CLAUDE.md §3's concurrency note says this box regularly has two or three agent sessions running at once; a gate that fails only under self-concurrency produces a false RED that costs a triage cycle and, worse, invites someone to weaken the test rather than serialize the run.
**Proposed fix:** Add a one-line recipe comment plus a `make help` note that `desktop-conformance` must not run concurrently with another copy of itself, or take the same `.claude/notes/milestones/.lock`-style guard the pipeline already uses. Longer term, give the port-binding tests an ephemeral port per run.
**Regression-guard:** optional
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**L7 — Supervisor stderr captured to an undrained pipe for the whole launch** (LOW)

**Where:** `tests/test_desktop_self_authored_launch.py:265`
**Anchor:** `stderr=subprocess.PIPE,`
**What:** The GREEN test opens the supervisor with `stderr=subprocess.PIPE` and never reads it — no `communicate()`, no reader thread — across a window that can reach 180 s per event wait, then calls `process.wait(timeout=15)` with the pipe still unread.
**Why it matters:** If the run emits more than the OS pipe buffer (macOS webkit/Tauri startup is capable of it), the supervisor blocks on write and the test fails at a timeout that reads like a lifecycle bug. Draining it also closes the one channel the 64-hex token sweep does not cover — the sweep only walks files under the derived data root.
**Proposed fix:** Use `stderr=subprocess.DEVNULL`, or capture it via a reader thread and feed the collected text through the same `_HEX64` allowlist the file sweep uses.
**Regression-guard:** optional
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — build-script discipline (mapped: harness robustness)

**L8 — Unknown argv is silently ignored by the production binary** (LOW)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:383`
**Anchor:** `if std::env::args().nth(1).as_deref() == So`
**What:** The diagnostic probe is honored only at `argv[1]`, and any other argument — including a typo'd `--print-dataroot` or a stray flag — is silently ignored while the supervisor proceeds to a full launch.
**Why it matters:** Silent acceptance of unrecognized argv is the shape that later hides a real flag regression, and the probe is compiled into the shipped binary rather than sitting behind a `#[cfg]`. Neither is harmful today (the probe authors no plan, spawns nothing, touches no state), which is why this is LOW.
**Proposed fix:** Refuse any unrecognized argument with `fail(...)` before `load_plan()`, keeping the single recognized probe flag. One `match` arm.
**Regression-guard:** optional
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 1 — container/process hygiene (mapped: entrypoint argument discipline)

## What was done well

### From milestone-adversary-critic

- **The RED state genuinely discriminates.** `test_red_state_missing_payload_still_exits_two` asserts the documented `exit(2)` AND that the pre-m10 reason string is absent from stderr, so it fails against any tree where the arm was not wired — the discriminating shape the brief demanded, not the "assert the new arm succeeds" shape it forbade. The unmarked source-scan half runs on every `make test`, so a revert is caught without the desktop stack.
- **AC2's vacuity was closed the way the research asked.** `compose_self_authored_plan` was extracted specifically so the `child_argv.is_empty()` branch is reachable on a plan this code authored, and the positive test additionally pins `smoke == false` and all five knobs `None`.
- **The cross-language parity is pinned by RUNNING both**, via a diagnostic flag rather than by inspection — and the one deliberate divergence (Python's `Path.home()` fallback vs Rust refusing) is asserted on both sides so it cannot quietly become two. I re-derived the matrix independently against the built binary; every row shape it ships agrees exactly.
- **The containment check is the real thing.** `resolve_inside` canonicalizes both sides and uses component-wise `starts_with`, and the escape test stages an actual symlink whose literal path is under the root — a string-prefix implementation would pass that test's setup and fail its assertion.
- **The residual risks are recorded rather than implied closed** — `current_exe()`'s non-primitive status appears in the doc comment, the module docstring and the synthesis, and the sibling-directory write-access class was added by the implementer rather than inherited from the brief.
- **The environment arm is guarded from both sides.** Not just "`test_desktop_child.py` is untouched" but a positive test that a staged tree with a perfectly good payload plus a malformed supplied plan still fails on the supplied plan — which catches a supervisor that silently preferred the layout.
- **The Makefile line arms the zero-skip guard correctly**, exporting BOTH `DESKTOP_SUPERVISOR_BIN` and `ARXMCP_FIXTURE_SIDECAR`, so the new evidence cannot go missing behind a green run — the m6 finding stays rectified.
- **The token scan is a faithful extension of the m6 technique**, and it is non-vacuous: `redact.rs`'s own documentation confirms the `StartupToken` is 64 lowercase hex, exactly what `_HEX64` matches, and the `allowed` set is the same identity-digest construction `test_desktop_child.py:488` uses.
- **Commit hygiene is clean.** Both commits are GPG-signed (`%G? = G`), carry `Co-Authored-By: Claude Opus 5`, use in-repo types and scopes, and the range touches no `plans/`, no roadmap, and performs no external write.

### From milestone-arxmcp-critic

- The RED state is reproduced from two independent sides — an unmarked source guard that a revert trips on every `make test`, and a runtime `exit(2)` assertion that additionally requires the pre-m10 string to be ABSENT from stderr — which is exactly the discrimination AC1 demanded and the thing most implementations would have skipped.
- AC2's vacuity trap was seen and closed rather than argued around: `compose_self_authored_plan` exists specifically so `validate_plan`'s `child_argv.is_empty()` branch is reached on a plan this code authored, instead of leaning on the five `!smoke` knobs that a self-authored plan refuses for free.
- AC3 is proven from both directions — `tests/test_desktop_child.py` is byte-identical, AND a supplied-but-malformed plan over a perfectly good staged payload must still fail with `launch plan malformed`, which catches the silent-preference regression a one-sided check would miss.
- The containment check is a genuine canonicalize-then-contain with component-wise `starts_with`, tested with a real symlink whose literal path sits under the payload root — not the string-prefix check the brief warned against.
- `std::env::current_exe()` is documented as not a security primitive in three places (the `resolve_inside` doc comment, the test module docstring, the synthesis) with the specific PATH-search and hardlink classes named, and the sibling-directory attack this design ADDS is recorded as its own separate risk rather than folded into the first.
- The one deliberate divergence from Python that was found is asserted on both sides rather than commented, so it cannot quietly become two — the technique is right even though M3 shows a second divergence slipped past it.
- The startup-token evidence reuses m6's technique correctly: `_HEX64` matches lowercase 64-hex, which is exactly what `generate_startup_token()` emits (`desktop-contract/src/lib.rs:90-99`), so the scan over every file under the derived data root would genuinely catch a persisted token rather than being decorative.
- The new module was placed outside `tests/test_desktop_child.py` for the explicit purpose of keeping that file byte-identical, and the Makefile line documents in-comment why it is the only conformance line that runs with the plan variable absent.
- The env-isolation helpers are careful in the way that matters: `_plan_free_env` REMOVES the plan variable and every variable `_platform_data_root` reads rather than overwriting them, so an ambient `XDG_DATA_HOME` on the runner cannot send the supervisor to a root the test then looks for elsewhere.
- Every file:line citation in the new doc comments checked out against source — `_platform_data_root` at `:81-89`, `_inside` at `:59-67`, and the spec's `EXE` at `:153` / `COLLECT` at `:209` are all accurate, which is rarer in this repo than it should be.

### From milestone-infra-safety-critic

- The containment check is genuinely component-wise on canonicalized paths (`main.rs:184-191`), not a string prefix — a `payload-root-evil` sibling and a `..` traversal both fail correctly, which is the failure mode this repo has already been bitten by once (`server/routes/ui.py`, the 2026-07-12 win32 push).
- `data_root` parity is pinned by RUNNING both implementations across a 9-row matrix including empty-string-means-absent, spaces, and non-ASCII; the `--print-data-root` probe exists precisely so the assertion is executable rather than eyeballed, and that is the right instinct.
- The one divergence from the Python original (refuse instead of `Path.home()`) is both the safer choice and asserted from both sides, so it cannot silently become two.
- The RED state is discriminated twice — an unmarked source-level check that the pre-m10 failure string is dead, plus a runtime check that `exit(2)` survives for a NEW reason — which is exactly what the acceptance criterion asked for and what most implementations skip.
- `compose_self_authored_plan` exists solely so AC2 can reach `validate_plan`'s non-vacuous branch on a plan this code authored; recognizing that the `!smoke` knobs are refused for free is a sharper reading than the criterion required.
- `_plan_free_env` REMOVES the launch-plan variable and every `_platform_data_root` input rather than overwriting them, so an ambient `XDG_DATA_HOME` on the runner cannot make the gate lie.
- `DESKTOP_FIXTURE_COMPONENT` is deliberately not `ARXMCP_`-prefixed, so `lifecycle.rs:168`'s environment scrub could never deliver it to a child — the same reasoning as `DESKTOP_SUPERVISOR_BIN`, applied consistently.
- The new Makefile line is the only one in `desktop-conformance` that runs with `ARXMCP_DESKTOP_LAUNCH_PLAN` absent, and it sets both binary variables so the zero-skip guard arms — the unset-plan evidence cannot go missing behind a green run.
- The startup-token sweep is real, not decorative: `generate_startup_token` emits 64 lowercase hex (`apps/desktop/crates/desktop-contract/src/lib.rs:90-99`), which the `_HEX64` allowlist scan does match, so a leaked token in any persisted artifact would fail the test.
- AC3 is defended from both directions — `tests/test_desktop_child.py` is byte-identical, and a malformed supplied plan against a perfectly good staged payload must still fail, so a supervisor that silently preferred the layout would be caught.

Severity counts: C1 H4 M16 L8


## Cross-critic agreement

The following findings cluster within 5 lines of each other in the same file. Multiple critics flagged the same area - these are the strongest signals to fix first.

- **M6, H4, M5, L3** at `apps/desktop/crates/supervisor/src/main.rs:51-60` (HIGH): CHILD_PAYLOAD_DIR unpinned against the PyInstaller spec name; Bundle-layout and component constants pinned by inspection only; CHILD_COMPONENT hand-copied, and the GREEN arm disarms the check; `--print-data-root`'s side-effect-free claim is unasserted
- **M7, M15** at `apps/desktop/crates/supervisor/src/main.rs:149-151` (MEDIUM): A second, undocumented divergence from _platform_data_root; Windows data-root branch is reachable by neither gate and unpinned
- **H1, H3** at `apps/desktop/crates/supervisor/src/main.rs:212-212` (HIGH): Self-authored plan names the Rust crate version as the Python child's identity; Self-authored plan pins child version to the supervisor crate
- **M10, L1, L8** at `apps/desktop/crates/supervisor/src/main.rs:383-383` (MEDIUM): `std::env::args()` panics on non-UTF-8 argv, now on every launch; Ungated test seam in the production binary; Unknown argv is silently ignored by the production binary

## Recommended rectification order

C1, H1, H2, H3, H4, M2, M4, M1, M3, M7, M5, M6, M9, M10, M8, M11, M14, M13, M16, M15, M12, L2, L1, L3, L4, L5, L7, L6, L8

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:

## Carried from milestone-arxmcp-critic — Axis walk (non-finding record)

- **Axis 1 — cache byte-stability: CLEAN.** The diff touches no `server/tools.py`, `server/prompts.py`, tool handler, or result envelope; `EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_BP1_SHA256` need no re-pin.
- **Axis 2 — math fidelity: CLEAN.** No LaTeX, MathML, chunker, preamble, or parser path is touched.
- **Axis 3 — security: findings M6, L1.** The containment check is canonicalize-then-contain with component-wise `starts_with`, correctly mirroring `_inside` (`server/application_paths.py:59-67`, citation verified accurate). `DESKTOP_FIXTURE_COMPONENT` is non-`ARXMCP_`-prefixed, so `lifecycle.rs`'s `ARXMCP_*` scrub cannot deliver it, and the fixture binary ships nowhere today (`tauri.conf.json` `bundle.active` is still `false`). The self-authored arm's digest self-consistency (`identity_file == child_argv[0]`, so `file_sha256(&plan.identity_file)` at `lifecycle.rs:110` digests the very file it executes) is a real reduction in what the identity comparison proves relative to the environment arm, but it is recorded as residual risk 2 in the implement synthesis and is inherent to self-authoring — not filed.
- **Axis 4 — MCP 2025-06-18 spec compliance: CLEAN.** No wire surface, SSE framing, `tools/list` shape, or method name is touched; the `mcp-smoke-ok` step runs unmodified.
- **Axis 5 — local-first: finding M3.** No cloud, S3, or multi-host dependency added. `std::env::temp_dir()` (not a hardcoded `/tmp`) backs the Rust unit-test staging, and every hardcoded string path (`/tmp`, `/nonexistent-home`, `/parity/*`) is a lookup value that is never created on disk.
- **Axis 6 — tier sequencing: CLEAN.** Dependencies are m7 and m9, both shipped; `.app` assembly is correctly deferred to m15 per the 2026-08-11 roadmap narrowing, and `tauri.conf.json` is untouched.
- **Axis 7 — no-fork policy: CLEAN.** No manifest change (`pyproject.toml`, `uv.lock`, `Cargo.toml`, `Cargo.lock` all untouched), no submodule, no vendored file, no upstream-attribution header.
- **Axis 8 — test surface: findings H1, M1, M2, M4, M5, L1, L2.** `tests/conftest.py` and its `KMP_DUPLICATE_LIB_OK` guard are untouched; no MCP tool was added, so no schema re-pin is due.
- **m9 standing regression: CLEAN.** `tests/test_desktop_support_floor.py::_shipped_event_sources` globs `apps/desktop/crates/**/*.rs`, so both changed Rust files are inside the macOS-14 claim scanner; none of the ~90 new comment lines or the new `self-authored plan: …` error strings matches a claim shape, and no shipped Markdown was added.
- **Doc placement (§4.6): CLEAN.** The only new Markdown is `.claude/notes/milestones/desktop-distribution-m10/implement/synthesis.md`; nothing landed in `server/`, `ingest/`, `tests/`, `tools/`, `shim/`, `docker/`, or `infra/`.
- **Banned patterns: CLEAN.** No `assert` in shipped Python (the new asserts are all under `tests/`, the one ruff-`S101`-exempt tree), no `BaseHTTPMiddleware`, no `anthropic` import, no `claude-opus` reference in `server/`, no `git push`/`gh` call inside implemented code.
