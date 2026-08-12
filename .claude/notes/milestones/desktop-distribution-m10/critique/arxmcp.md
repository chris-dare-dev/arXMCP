# Critique — desktop-distribution-m10 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** b102c85..3327edb
**Diff stats:** 6 files, 1001 LOC (991 insertions, 10 deletions; 4 files / 770 LOC excluding notes)
**Critique format version:** 1.0

## Verdict

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

## Executive summary

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

## Findings

**H1 — Self-authored plan pins child version to the supervisor crate** (HIGH)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:212`
**Anchor:** `        version: env!("CARGO_PKG_VERSION").to_`
**What:** `compose_self_authored_plan` sets the plan's expected child `version` to the supervisor crate's `CARGO_PKG_VERSION` (`apps/desktop/Cargo.toml` `[workspace.package].version = "0.1.0"`), but the real frozen child reports `importlib.metadata.version("arxmcp")` (`server/desktop_child.py:88-93`), which comes from `pyproject.toml:103` — a separately maintained string that happens to also read `0.1.0` today.
**Why it matters:** `server/desktop_child.py:182` refuses the launch frame outright with `DesktopContractError("executable identity mismatch")` on a version difference, so the first release that bumps either version string turns every double-clicked launch — the entire deliverable of this milestone — into a hard boot failure, and the m10 GREEN arm cannot see it because its child is the fixture sidecar, a crate in the supervisor's own Cargo workspace that inherits the identical `version.workspace = true`.
**Proposed fix:** Do not derive the child's expected version from the supervisor's crate. Either (a) read it from a build-time constant generated from `pyproject.toml` (the same source m7's bundle ships), or (b) follow `tests/test_desktop_child.py:423`'s existing pattern and derive the plan's `version` from the payload's own recorded identity rather than asserting one. Whichever is chosen, add an UNMARKED test that parses `pyproject.toml`'s `[project].version` and `apps/desktop/Cargo.toml`'s `[workspace.package].version` and fails when the self-authored plan would name the wrong one.
**Regression-guard:** A new unmarked `tests/` assertion pinning `compose_self_authored_plan`'s version source against `pyproject.toml [project].version`, so it fails on a Python-side bump without needing `make desktop-conformance`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M1 — CHILD_COMPONENT hand-copied, and the GREEN arm disarms the check** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:55`
**Anchor:** `const CHILD_COMPONENT: &str = "arxmcp-serve`
**What:** The component string is copied by hand from `server/desktop_child.py:69`, and the new `DESKTOP_FIXTURE_COMPONENT` override makes the fixture answer to whatever the test names, so the supervisor's bound-identity comparison for the component field is satisfied by construction in the only end-to-end test that exercises it.
**Why it matters:** A rename of `server/desktop_child.py::COMPONENT` leaves the self-authored plan naming a component the frozen child will refuse, and both `make test` and `make desktop-conformance` stay green — the substitution the module docstring discloses (fixture for frozen child) also silently removes the last check on this literal.
**Proposed fix:** Add an unmarked test that reads `server/desktop_child.py`'s `COMPONENT` and the Rust `CHILD_COMPONENT` constant from source and asserts equality (the repo already does exactly this style of derived pin in `tests/test_marker_doc_consistency.py` and `tests/test_wheel_packaging.py`). Independently, record in the test module docstring that the component half of the identity comparison is not proven by the GREEN arm.
**Regression-guard:** `tests/test_desktop_self_authored_launch.py` unmarked assertion `CHILD_COMPONENT == server.desktop_child.COMPONENT`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M2 — CHILD_PAYLOAD_DIR unpinned against the PyInstaller spec name** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:51`
**Anchor:** `const CHILD_PAYLOAD_DIR: &str = "arxmcp-desk`
**What:** The onedir directory and executable name are hand-copied from `apps/desktop/pyinstaller/arxmcp_desktop.spec:158` / `:218`; the Python test re-declares the same literal at `tests/test_desktop_self_authored_launch.py:57` and stages the directory from its own copy, so the test never reads the spec.
**Why it matters:** Renaming the spec's `name=` — which m15 is explicitly expected to touch when it re-points the containment check at the bundle root — leaves the self-authoring arm exiting 2 with `child payload root missing` in production while every gate stays green, because the fixture layout is built from the stale literal on both sides.
**Proposed fix:** Derive the constant on the test side from the spec (`re`-extract `name=` from `arxmcp_desktop.spec`, or import the value m7's `desktop_package.py` already carries) and assert it equals the Rust `CHILD_PAYLOAD_DIR`, in the same unmarked test proposed for M1.
**Regression-guard:** Unmarked assertion that the spec's `EXE`/`COLLECT` `name=` equals `CHILD_PAYLOAD_DIR` in `main.rs`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M3 — A second, undocumented divergence from _platform_data_root** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:149`
**Anchor:** `            .ok_or("self-authored plan: no HOM`
**What:** The port refuses whenever neither `HOME` nor `USERPROFILE` is set, but Python only uses `home` as a *fallback* for the platform base — with `XDG_DATA_HOME` set and no `HOME` (Linux), or `LOCALAPPDATA` set and no `USERPROFILE`/`HOME` (Windows), `_platform_data_root` returns a real path and never touches `Path.home()`, while Rust errors out.
**Why it matters:** The doc comment at `main.rs:136-142` and the test named `test_data_root_parity_has_exactly_one_documented_divergence` (`tests/test_desktop_self_authored_launch.py:337`) both assert exactly ONE divergence; there are two, the second is reachable on Linux (a platform the matrix does run on), and no `_PARITY_MATRIX` row sets `XDG_DATA_HOME` without `HOME`, so the assertion of exhaustiveness is unearned rather than merely optimistic.
**Proposed fix:** Add `{"XDG_DATA_HOME": "/parity/xdg"}` and `{"LOCALAPPDATA": "C:/parity/local"}` rows to `_PARITY_MATRIX`; then either move the `home` lookup below the platform branch so it is only evaluated when the branch actually needs it (matching Python), or widen the doc comment and the test name to record two divergences instead of one.
**Regression-guard:** The two new `_PARITY_MATRIX` rows — on Linux they fail today against the current port.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first + Docker constraint

**M4 — The cross-language pin never runs under `make test`** (MEDIUM)

**Where:** `server/application_paths.py:81`
**Anchor:** `def _platform_data_root(env: Mapping[str, `
**What:** `_platform_data_root` now has a Rust duplicate, but the file carries no marker saying so, and the only assertion holding the two together is `requires_desktop_stack`-marked, i.e. deselected by default since issue #206 and run only by `make desktop-conformance`.
**Why it matters:** CLAUDE.md §4.1 names `make test` as the authority a change must be green under before pushing; an agent editing this Python function — the exact silent-drift hazard both m10 research briefs named — gets a fully green `make test` with the Rust half already diverged, and nothing in the Python file points at the port.
**Proposed fix:** Add a one-line comment above `_platform_data_root` naming `apps/desktop/crates/supervisor/src/main.rs::platform_data_root` and the gate that pins them (`make desktop-conformance`), so drift ownership is legible at the edit site. Optionally strengthen with an unmarked test that hashes the Python function's source and fails when it changes without the Rust file changing in the same commit.
**Regression-guard:** Not strictly required at MEDIUM; the comment is the minimum, an unmarked source-pin test is the durable form.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M5 — Test comment claims provenance the assertion does not check** (MEDIUM)

**Where:** `tests/test_desktop_self_authored_launch.py:284`
**Anchor:** `        assert len(spawned) == 1, _events(ro`
**What:** The caption above this line reads "The spawned child is the one inside the payload root, not an ambient binary of the same name", but the assertion only counts spawn events; `lifecycle.rs:174` records `child-spawn` with `{"child_pid": ...}` and no path, so the event carries nothing that could prove provenance.
**Why it matters:** This is the milestone's containment story at the end-to-end level, and a reader (or a Phase-4 rectifier) will take the caption as the guarantee — the real proof lives only in `lifecycle.rs`'s digest comparison, which the module never names, so a regression that resolved `child_argv[0]` outside the payload root would be caught by the Rust unit test alone and this assertion would keep passing.
**Proposed fix:** Either add `child_path` to the `child-spawn` event payload and assert it is under `supervisor.parent / CHILD_PAYLOAD_DIR`, or rewrite the caption to say what is actually asserted (exactly one spawn cycle) and cross-reference `child_executable_escaping_the_payload_root_is_rejected` as where containment is proven.
**Regression-guard:** Optional at MEDIUM; the durable form is the `child_path` field plus a containment assertion in `test_self_authored_launch_reaches_ready_and_window`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M6 — `std::env::args()` panics on non-UTF-8 argv, now on every launch** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:383`
**Anchor:** `    if std::env::args().nth(1).as_deref() ==`
**What:** `std::env::args()` is documented to panic if any argument is not valid Unicode; the pre-m10 use at `:360` was inside `notify_running_instance`, i.e. macOS-only and reachable only on the single-instance loser path, whereas this call is now the first statement `main()` executes on every platform and every launch.
**Why it matters:** The supervisor's whole failure contract is a controlled `fail()` → `exit(2)` with a named reason; a non-UTF-8 argument (an `open --args` invocation, a mis-encoded desktop entry, a relaunch carrying a filename argument) now aborts with a Rust panic message instead, on precisely the double-click path this milestone exists to make survivable.
**Proposed fix:** One-line change to `std::env::args_os().nth(1).as_deref() == Some(std::ffi::OsStr::new(DATA_ROOT_PROBE_ARG))`, which cannot panic and compares identically for the ASCII flag.
**Regression-guard:** A Rust or Python test launching the staged supervisor with a non-UTF-8 argv byte and asserting `exit(2)` (or a normal launch) rather than a panic exit code.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security threat-model coverage

**M7 — Diff scope 770 code LOC against a ~520 pre-authorized budget** (MEDIUM)

**Where:** no specific file
**What:** `git diff --stat b102c85..3327edb` is 991 insertions / 10 deletions over 6 files; excluding the notes commit, 770 insertions over 4 files, against the brief's measured ~520 LOC / ~7 files estimate.
**Why it matters:** The critique-format calibration anchors put a diff over 400 LOC at HIGH; it is demoted here because the overrun is dominated by comment prose (~90 of 363 added `main.rs` lines) and a 377-line test module rather than by unreviewed production logic, and because the implementer reported the 350-line checkpoint crossing rather than crossing it silently.
**Proposed fix:** No code change. Record the overrun in the milestone's rectify notes so the epic's remaining LOC estimates (m15 in particular, which re-points the same functions) are re-based off the measured 770 rather than the original ~520.
**Regression-guard:** Not applicable — process finding.
**Source critic:** milestone-arxmcp-critic
**Source axis:** open scan

**L1 — `--print-data-root`'s side-effect-free claim is unasserted** (LOW)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:60`
**Anchor:** `const DATA_ROOT_PROBE_ARG: &str = "--print-`
**What:** The doc comment states the probe "authors no plan, spawns nothing, and touches no filesystem state", but no test asserts it; every `_PARITY_MATRIX` row uses an uncreatable path (`/parity/home`, `C:/parity/local`), so a regression that created the derived root would fail to create it and go unnoticed rather than being caught.
**Why it matters:** This is a diagnostic flag on the SHIPPED supervisor binary, and its safety guarantee is the only reason adding it to a production surface is acceptable.
**Proposed fix:** Add one row using a `tmp_path`-derived writable `HOME` and assert the derived data root does NOT exist after the probe exits.
**Regression-guard:** Optional at LOW.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security threat-model coverage

**L2 — Source-guard test recognizes only `//`-prefixed comment lines** (LOW)

**Where:** `tests/test_desktop_self_authored_launch.py:83`
**Anchor:** `        if PRE_M10_FAILURE in line and not line`
**What:** The RED-state source guard classifies a line as "live" unless it is lstrip-prefixed with `//`; a `/* ... */` block comment, or a trailing `// ...` after code on the same line, would be misclassified in either direction.
**Why it matters:** The guard is the only unmarked (every-`make test`) protection against a revert of the self-authoring arm, so a false negative retires it silently.
**Proposed fix:** Match on the `fail(` call shape instead of the bare string — e.g. flag any line containing `fail("` and `PRE_M10_FAILURE` — which is what "live" actually means here.
**Regression-guard:** Optional at LOW.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**L3 — CLAUDE.md §4.5's `requires_desktop_stack` description not amended** (LOW)

**Where:** `CLAUDE.md:1`
**Anchor:** `# CLAUDE.md — Context for Claude agents wor`
**What:** §4.5's `requires_desktop_stack` bullet enumerates the m5/m6 lifecycle and fault-matrix tests as what the marker covers; m10 added a fourth `desktop-conformance` line and a new marked module without amending it, and `tests/test_marker_doc_consistency.py` re-derives only the marker COUNT and names, not their descriptions.
**Why it matters:** §4.5 is the section an agent reads to learn what `make desktop-conformance` proves; the doc now understates the gate, which is the same hand-maintained-snapshot drift §3 already warns about.
**Proposed fix:** One sentence in the `requires_desktop_stack` bullet naming `tests/test_desktop_self_authored_launch.py` and the fact that it is the only conformance line running with `ARXMCP_DESKTOP_LAUNCH_PLAN` deliberately absent.
**Regression-guard:** Optional at LOW.
**Source critic:** milestone-arxmcp-critic
**Source axis:** open scan

## Axis walk (non-finding record)

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

## What was done well

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

Severity counts: C0 H1 M7 L3

## Recommended rectification order

H1, M3, M1, M2, M5, M6, M4, L1, L2, L3, M7

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
