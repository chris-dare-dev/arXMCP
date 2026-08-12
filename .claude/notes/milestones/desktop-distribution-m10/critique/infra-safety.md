# Critique — desktop-distribution-m10 — milestone-infra-safety-critic

**Critic:** milestone-infra-safety-critic
**Commit range:** b102c85..3327edb
**Diff stats:** 6 files, 1001 LOC (991 added / 10 removed)
**Critique format version:** 1.0

## Verdict

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

## Executive summary

- [HIGH] `CHILD_COMPONENT` and `CHILD_PAYLOAD_DIR` are hand-copied literals with no executable pin to `server/desktop_child.py::COMPONENT` or `desktop_package.BUNDLE_NAME`/`CHILD_EXE` — a rename breaks the shipped double-click path with every gate green.
- [MEDIUM] The sibling-directory execution-selection trust assumption (write access next to the supervisor = arbitrary code execution) lives only in `implement/synthesis.md`; it is absent from `apps/desktop/README.md`, `SECURITY.md`, the `resolve_inside` doc comment, and m15's acceptance criteria.
- [MEDIUM] `resolve_inside` canonicalizes the payload root but never establishes that the root IS a real directory under the supervisor's own parent, so a symlinked payload root passes containment — while the comment claims a symlink out of the root cannot.
- [MEDIUM] `DESKTOP_FIXTURE_COMPONENT` also rewrites the fixture's `Bound` echo, so the supervisor's bound-identity equality is satisfied by construction on the only end-to-end proof of the new arm.
- [MEDIUM] The Windows branch of the ported `platform_data_root` is reachable by neither gate (the parity matrix cannot run it; the Rust unit test `cfg!`s it away on this host) and carries no source-level pin.
- [MEDIUM] `smoke: false` is a first-of-its-kind plan shape and its teardown SIGKILLs the child, so the stdin-EOF lease and the bounded shutdown ladder are unasserted on the arm that actually ships.
- [LOW] `make desktop-conformance` neither serializes nor isolates the shared `apps/desktop/target/debug` tree and fixed loopback ports across its six pytest lines.
- [LOW] Supervisor stderr is captured to an undrained `PIPE` across a 180 s launch; a chatty webkit run can block the supervisor on a full pipe.

## Findings

**H1 — Bundle-layout and component constants pinned by inspection only** (HIGH)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:55`
**Anchor:** `const CHILD_COMPONENT: &str = "arxmcp-ser`
**What:** `CHILD_COMPONENT` (`main.rs:55`) and `CHILD_PAYLOAD_DIR` (`main.rs:51`) are string literals duplicated a third and fourth time in `tests/test_desktop_self_authored_launch.py:58,61`, and nothing in the tree asserts them equal to their real sources — `server/desktop_child.py:69::COMPONENT`, and `apps/desktop/pyinstaller/desktop_package.py:41-42::BUNDLE_NAME`/`CHILD_EXE` (which the `arxmcp_desktop.spec` `name=` at :158/:218 owns).
**Why it matters:** These two constants decide which binary the supervisor executes and whether it will accept the child that answers. A rename of the onedir bundle or of the frozen child's component makes the shipped double-click path fail at spawn or at bound-identity, while `make test`, `make desktop-conformance`, and `make desktop-package-check` all stay green — the self-authored test stages its own directory from its own literal and drives the fixture with its own literal, so both sides of the comparison move together. The milestone's own stated rule ("agreement is asserted by running BOTH implementations — never by inspection", `main.rs:22-25`) is applied to `data_root` and not to the pair that selects the executable.
**Proposed fix:** In `tests/test_desktop_self_authored_launch.py`, replace both literals with imports — `from server.desktop_child import COMPONENT as CHILD_COMPONENT`, and a path-loaded `desktop_package` module for `BUNDLE_NAME`/`CHILD_EXE` exactly as `tests/test_desktop_package.py` already does with its `dp` alias — and add one UNMARKED test that reads the two `const` lines out of `main.rs` and asserts they equal those Python values. Unmarked so a rename fails on every `make test`, not only under the desktop stack.
**Regression-guard:** A new unmarked `tests/test_desktop_self_authored_launch.py::test_rust_layout_constants_match_their_python_sources` that parses `const CHILD_PAYLOAD_DIR` / `const CHILD_COMPONENT` from `main.rs` and asserts equality with `desktop_package.BUNDLE_NAME` and `server.desktop_child.COMPONENT`.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — build-script discipline (mapped: cross-artifact constant pinning in the conformance gate)

**M1 — Sibling-write execution risk recorded only in a per-milestone note** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:178`
**Anchor:** `/// RESIDUAL RISK, recorded not closed: the r`
**What:** The `resolve_inside` doc comment records only the PATH-search and Linux-hardlink `current_exe()` classes; the class this design actually adds — the payload root is a SIBLING directory, so anyone who can write next to the installed supervisor chooses `child_argv[0]` — appears only in `.claude/notes/milestones/desktop-distribution-m10/implement/synthesis.md` residual risk 2, and in neither `apps/desktop/README.md`, `SECURITY.md`, nor m15's acceptance criteria.
**Why it matters:** The two classes are ranked backwards for this deployment. The supervisor is not setuid/setgid, so an attacker who can steer `current_exe()` by PATH search or hardlink is already executing code as the invoking user and gains nothing — whereas the sibling-write class needs no trick at all and is the one an installer, an unpacked-in-Downloads copy, or a group-writable install directory makes real. `apps/desktop/README.md` is exactly where m15's AC7 says the artifact layout must be recorded, and m15 chooses the bundle mechanism; if the assumption is not there, that choice can be made without it.
**Proposed fix:** Add a short "child payload layout and its trust assumption" section to `apps/desktop/README.md` stating the `<supervisor dir>/arxmcp-desktop-child/arxmcp-desktop-child` convention, that write access to that directory is equivalent to arbitrary code execution as the operator, and that the defense is install-location permissions plus m15/e4 code signing. Amend the `main.rs:178` comment to name the sibling-write class first and to say why the PATH/hardlink classes carry no privilege gradient here.
**Regression-guard:** optional
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 1 — container/process hygiene (mapped: process-execution trust boundary)

**M2 — Containment never validates the payload root itself** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:185`
**Anchor:** `let canonical_root =`
**What:** `resolve_inside` canonicalizes the root and the candidate and requires the candidate to be inside the canonical root, but the root is whatever `supervisor_exe.parent()/arxmcp-desktop-child` canonicalizes TO (`main.rs:225-229`). If that entry is itself a symlink to `/tmp/evil`, `canonical_root` becomes `/tmp/evil`, the candidate resolves to `/tmp/evil/arxmcp-desktop-child`, containment holds, and an arbitrary binary is executed. The unit test at `main.rs:637` stages a symlinked CHILD, never a symlinked ROOT.
**Why it matters:** The doc comment claims "a symlink out of the payload root cannot [pass]" and the synthesis says canonicalize-then-contain "closes the ordinary relocated- or tampered-sidecar case". Relocation via a symlinked root is precisely an ordinary relocated-sidecar case and it is not closed. The trust domain is the same one M1 describes, so this is a claim-vs-check mismatch rather than a new privilege boundary — but the claim is what m15 will rely on when it re-points the check at the bundle root.
**Proposed fix:** Before canonicalizing, require the payload root to be a real directory whose canonical parent equals the canonical parent of `supervisor_exe` (compare `fs::canonicalize(supervisor_exe.parent()?)` against `canonical_root.parent()`), or take `symlink_metadata` on the root and refuse a symlink. Either is a few lines inside `resolve_inside`; then the comment's claim is true as written.
**Regression-guard:** optional — a `#[cfg(unix)]` sibling to `child_executable_escaping_the_payload_root_is_rejected` that symlinks the payload ROOT out of the staging base and asserts refusal.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 1 — container/process hygiene (mapped: path-containment correctness)

**M3 — Fixture echo makes the arm's bound-identity check tautological** (MEDIUM)

**Where:** `apps/desktop/crates/fixture-sidecar/src/main.rs:285`
**Anchor:** `component: expected_component(),`
**What:** `DESKTOP_FIXTURE_COMPONENT` loosens the fixture's inbound equality check (`:236`) AND rewrites the identity the fixture echoes back in `make_bound` (`:285`), so the supervisor's bound-identity comparison ends up comparing the plan's component against itself. The one end-to-end proof of the new arm (`tests/test_desktop_self_authored_launch.py:259`) therefore cannot distinguish a correct `CHILD_COMPONENT` from any other string.
**Why it matters:** The echo rewrite is what turns a test-only relaxation into a lost assertion: with it, m10's GREEN arm proves plan authoring and spawn, not identity binding, and there is no other arm-level identity evidence (H1's constant is unpinned; `tests/test_desktop_child.py:863` pins only the Python side). The commit comment calls this keeping the comparison "an honest equality check" — it is honest but vacuous.
**Proposed fix:** Keep the override for the inbound check but have the GREEN test additionally assert the negative: one run with `DESKTOP_FIXTURE_COMPONENT` left UNSET against a self-authored plan naming `CHILD_COMPONENT` must fail to reach `child-bound`, proving the equality is load-bearing. Alternatively echo `COMPONENT` unchanged and assert the supervisor's refusal reason.
**Regression-guard:** optional
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — build-script discipline (mapped: test-harness override scope)

**M4 — Windows data-root branch is reachable by neither gate and unpinned** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:151`
**Anchor:** `let base = if cfg!(target_os = "windows") {`
**What:** The 9-row parity matrix (`tests/test_desktop_self_authored_launch.py:302`) runs the real binary, so on this host it can only ever exercise the macOS branch; the Rust unit test compares against a `cfg!`-selected expectation, so it also cannot see the Windows branch. Nothing pins the Windows arm of either implementation, and the new module skips wholesale on win32.
**Why it matters:** Drift shows up as data bifurcation with no error: the double-clicked application derives root A while `ApplicationPaths`, the CLI, and every ops tool derive root B, so the app looks like it has an empty corpus and the operator's ingest lands somewhere the app never reads. The Python function is also private (`_platform_data_root`), now cross-language load-bearing, with its only executable pin gated behind `requires_desktop_stack` — a Python-side edit is invisible to plain `make test`.
**Proposed fix:** Add one UNMARKED test that (a) monkeypatches `sys.platform` to `"win32"` and asserts `_platform_data_root` output for a fixed `LOCALAPPDATA`/`USERPROFILE` row, and (b) asserts the Rust Windows branch source text at `main.rs:151-153` still reads `LOCALAPPDATA` with the `home/AppData/Local` fallback. A one-sided edit then fails on every `make test` instead of waiting for a Windows runner that does not exist.
**Regression-guard:** optional
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — build-script discipline (mapped: gate reachability of a ported function)

**M5 — Bounded shutdown and no-orphan unasserted on the smoke:false arm** (MEDIUM)

**Where:** `tests/test_desktop_self_authored_launch.py:212`
**Anchor:** `os.kill(pid, signal.SIGKILL)`
**What:** Every supervisor plan in `tests/test_desktop_child.py` is `smoke: true` (`:422`, `:948`), so the self-authored arm is the first `smoke: false` launch any gate has run — the first where the supervisor does not self-exit after a cycle. Its teardown SIGTERMs the supervisor and then unconditionally SIGKILLs every recorded `child-spawn` pid, so the stdin-EOF parent-lifetime lease (`apps/desktop/crates/supervisor/src/lifecycle.rs:50`) and the `RunEvent::Exit` grace→TERM→KILL ladder are never observed on this arm; an orphan and a clean reap produce the same green result.
**Why it matters:** The no-orphan invariant is m6's central claim and the operator-visible failure is a full server with BGE-M3 resident and a loopback port held after the window closes. The mechanism is shared code and is proven under `smoke: true`, which is why this is a coverage gap rather than a demonstrated bug — but m10 introduces the shape that ships and does not carry the evidence onto it.
**Proposed fix:** In `_reap`, after `process.terminate()` and the 15 s wait, assert each spawned pid is gone BEFORE falling back to SIGKILL — keeping the SIGKILL as an unconditional safety net after the assertion is recorded, so a failing run still leaves no orphan behind. Roughly five lines, and it turns the lease into an asserted property of the production arm.
**Regression-guard:** optional
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — build-script discipline (mapped: cleanup evidence on the new gate line)

**L1 — desktop-conformance is concurrency-sensitive and says nothing about it** (LOW)

**Where:** `Makefile:175`
**Anchor:** `ARXMCP_FIXTURE_SIDECAR="$(CURDIR)/apps/de`
**What:** All six pytest lines in `desktop-conformance` point at the same `apps/desktop/target/debug` binaries and the same fixed loopback ports, and the target carries no lock, no per-invocation temp/port isolation, and no comment telling an operator (or a parallel agent session) that two simultaneous runs interfere. The 30-cycle orphan stress is the most sensitive line.
**Why it matters:** CLAUDE.md §3's concurrency note says this box regularly has two or three agent sessions running at once; a gate that fails only under self-concurrency produces a false RED that costs a triage cycle and, worse, invites someone to weaken the test rather than serialize the run.
**Proposed fix:** Add a one-line recipe comment plus a `make help` note that `desktop-conformance` must not run concurrently with another copy of itself, or take the same `.claude/notes/milestones/.lock`-style guard the pipeline already uses. Longer term, give the port-binding tests an ephemeral port per run.
**Regression-guard:** optional
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**L2 — Supervisor stderr captured to an undrained pipe for the whole launch** (LOW)

**Where:** `tests/test_desktop_self_authored_launch.py:265`
**Anchor:** `stderr=subprocess.PIPE,`
**What:** The GREEN test opens the supervisor with `stderr=subprocess.PIPE` and never reads it — no `communicate()`, no reader thread — across a window that can reach 180 s per event wait, then calls `process.wait(timeout=15)` with the pipe still unread.
**Why it matters:** If the run emits more than the OS pipe buffer (macOS webkit/Tauri startup is capable of it), the supervisor blocks on write and the test fails at a timeout that reads like a lifecycle bug. Draining it also closes the one channel the 64-hex token sweep does not cover — the sweep only walks files under the derived data root.
**Proposed fix:** Use `stderr=subprocess.DEVNULL`, or capture it via a reader thread and feed the collected text through the same `_HEX64` allowlist the file sweep uses.
**Regression-guard:** optional
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — build-script discipline (mapped: harness robustness)

**L3 — Unknown argv is silently ignored by the production binary** (LOW)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:383`
**Anchor:** `if std::env::args().nth(1).as_deref() == So`
**What:** The diagnostic probe is honored only at `argv[1]`, and any other argument — including a typo'd `--print-dataroot` or a stray flag — is silently ignored while the supervisor proceeds to a full launch.
**Why it matters:** Silent acceptance of unrecognized argv is the shape that later hides a real flag regression, and the probe is compiled into the shipped binary rather than sitting behind a `#[cfg]`. Neither is harmful today (the probe authors no plan, spawns nothing, touches no state), which is why this is LOW.
**Proposed fix:** Refuse any unrecognized argument with `fail(...)` before `load_plan()`, keeping the single recognized probe flag. One `match` arm.
**Regression-guard:** optional
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 1 — container/process hygiene (mapped: entrypoint argument discipline)

## What was done well

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

Severity counts: C0 H1 M5 L3

## Recommended rectification order

H1, M3, M2, M5, M4, M1, L2, L1, L3

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed: <finding ids>
- Deferred: <finding ids>
- Invalidated: <finding ids with reasons>
- Regression tests added: <file paths>
