# Implement synthesis — desktop-distribution-m10

## Built

One acceptance criterion per bullet, in the amended roadmap's order.

- **AC1 — unset variable reaches a ready server and a rendered window, with
  the documented `exit(2)` as the RED state.** `main.rs::load_plan()`'s `None`
  arm no longer calls `fail("ARXMCP_DESKTOP_LAUNCH_PLAN is required")`; it
  calls `self_authored_plan()` (`apps/desktop/crates/supervisor/src/main.rs`,
  `load_plan` and `self_authored_plan`). Three tests discriminate rather than
  merely assert success:
  - `tests/test_desktop_self_authored_launch.py::test_the_pre_m10_required_plan_failure_no_longer_exists`
    — UNMARKED, so it runs on every `make test`: the pre-m10 failure string
    exists in the file only inside a comment, never on a live line.
  - `::test_red_state_missing_payload_still_exits_two` — the `exit(2)` path is
    intact (a staged supervisor with NO sibling payload still exits 2) but the
    reason names the self-authoring arm, and the assertion `PRE_M10_FAILURE
    not in stderr` fails against any tree where the arm was not wired.
  - `::test_self_authored_launch_reaches_ready_and_window` — the GREEN arm,
    walked to `child-bound` -> `child-ready` -> `mcp-smoke-ok` ->
    `window-ready` with `window_ordered_in: true`, and then asserted STILL
    RUNNING (a `smoke: true` self-authored plan would have quit).
- **AC2 — self-authored plan refused under every rule, non-vacuously.** The
  plan goes through the same `validate_plan` (`load_plan`, self-authored arm).
  `compose_self_authored_plan` is the single composer, so
  `main.rs::tests::self_authored_plan_with_empty_argv_is_refused_by_the_same_validator`
  reaches the OTHER branch (`child_argv.is_empty()`) on a plan this code
  authored — the branch the brief says AC2 proves nothing without, because a
  self-authored plan is never `smoke: true` and the five `!smoke`-gated knobs
  are refused for free. `::self_authored_plan_passes_the_shared_validator`
  covers the positive side plus `smoke == false` and all five knobs `None`.
- **AC3 — the environment path is byte-identically preserved.**
  `tests/test_desktop_child.py` is UNTOUCHED — `git diff` names four files and
  that is not one of them, which is why the new tests are their own module.
  `load_plan`'s `Some(path)` branch has identical logic; the only edit is that
  it now returns `(plan, "environment")` instead of `plan`, so a triage
  session can tell the arms apart (brief-2 risk 5: both terminate at the same
  `fail()` sites). Guarded from the other side by
  `::test_the_environment_arm_is_unchanged_by_the_new_one`: a staged tree with
  a perfectly good payload plus a MALFORMED supplied plan must still fail with
  `launch plan malformed`, so a supervisor that silently preferred the layout
  would be caught.
- **AC4 — containment against m7's onedir root.** `resolve_inside()`
  canonicalizes BOTH sides and uses component-wise `Path::starts_with`,
  mirroring `server/application_paths.py::_inside` (:59-67) rather than a
  string prefix. `main.rs::tests::child_executable_escaping_the_payload_root_is_rejected`
  stages a symlink whose literal path is under the payload root and whose
  target is not, and asserts refusal; `::missing_child_payload_is_refused`
  covers absence. The onedir name is taken from `arxmcp_desktop.spec`'s
  `name="arxmcp-desktop-child"`, shared by its `EXE` (:153) and `COLLECT`
  (:209), which is what makes the layout `<root>/arxmcp-desktop-child/arxmcp-desktop-child`.
- **AC5 — `data_root` agrees with `_platform_data_root` by RUNNING both.**
  `platform_data_root()` is the Rust port; `--print-data-root` is a
  diagnostic-only argv flag that prints it and exits 0 (authors no plan,
  spawns nothing). `::test_data_root_parity_with_python` is parametrized over
  a 9-row env matrix — `HOME`, `USERPROFILE`, `XDG_DATA_HOME`, `LOCALAPPDATA`,
  empty-string-means-absent, spaces and non-ASCII — and compares the
  subprocess's stdout against `_platform_data_root(row)` for each row. The
  `_plan_free_env` helper strips those four variables from the inherited
  environment rather than trusting the runner's.
- **AC6 — frozen-case `identity_file` / `child_argv[0]` convergence.**
  `self_authored_plan` sets both to the same resolved executable, which is the
  frozen shape (`identity_source_path()` returns `Path(sys.executable)`), not
  the source-checkout shape every existing fixture uses. Asserted in
  `::self_authored_plan_passes_the_shared_validator`.
- **AC7 — startup token fresh per launch, never persisted.** No new generator:
  the token is still `lifecycle.rs`'s single `generate_startup_token()` call,
  and `Plan` still has no `startup_token` field (already pinned by
  `plan_rejects_unknown_fields_and_empty_argv`, which asserts
  `deny_unknown_fields` rejects that key). The m6 secret sweep is EXTENDED to
  this path: after the GREEN arm, every 64-hex string in every file under the
  derived data root must be the staged child's identity digest. The new
  `supervisor-started` field is a static arm label, never a path or a secret.
- **AC8 — gates.** See "Check gate results".

## Branching note

Commits landed on `worktree-agent-a516b74e7ba202f0e`, NOT on `main`.
CLAUDE.md §4.1 says all work lands on `main` directly, and the dispatch
instructed `git checkout main` inside the worktree — but git refuses:

```
fatal: 'main' is already used by worktree at '/Users/chris.dare/Personal/SourceCode/arXMCP'
```

The shared checkout holds `main`, and a worktree-isolated agent cannot run git
against the parent. This is the same mechanical constraint recorded at
`ui-uplift-m7`. The orchestrator fast-forwards `main` onto this branch in
Phase 4. §4.4 push policy observed: no push was made or attempted.

A second worktree fact worth recording: this worktree's HEAD was `bcc2fbb`,
one commit BEHIND the dispatched `{IMPLEMENTATION_BASE}` `b102c85` — i.e. it
predated the roadmap amendment that narrowed m10 and added m15. It was
fast-forwarded with `git reset --hard b102c85` before any edit, so the
implementation is against the amended brief. An agent that had trusted its
worktree HEAD would have implemented the pre-amendment ACs.

## Files touched

- `apps/desktop/crates/supervisor/src/main.rs` — the self-authoring arm,
  the `_platform_data_root` port, the containment check, the plan composer,
  the `--print-data-root` probe, and six new unit tests.
- `apps/desktop/crates/fixture-sidecar/src/main.rs` — `DESKTOP_FIXTURE_COMPONENT`
  override so the fixture can answer to the frozen child's component name.
  Test infrastructure only; the binary never ships.
- `tests/test_desktop_self_authored_launch.py` — new module (see AC3).
- `Makefile` — one `desktop-conformance` line for the new module; the only
  line in that target that runs with `ARXMCP_DESKTOP_LAUNCH_PLAN` absent.

## Deferred

Deliberate non-goals, each with the reason it is not a gap:

- **`.app` bundle assembly.** Out of scope by owner decision (research
  synthesis, "DECIDED 2026-08-11 ... split"): `tauri.conf.json` is untouched,
  `bundle.active` is still `false`, and no `resources`/`externalBin` key was
  added. `child_payload_root()` is the ONE function m15 re-points at the
  bundle root.
- **The GREEN arm runs against the fixture sidecar staged in m7's onedir
  SHAPE, not against the real frozen child.** No committed gate builds the
  Rust supervisor and the ~0.75 GB PyInstaller bundle in the same session —
  `desktop-conformance` builds the binaries, `desktop-package-check` builds the
  bundle — so a test needing both would either skip (which the zero-skip guard
  turns into a failure) or fail outright. The alternative was to weaken the
  proof to "child spawned"; instead the fixture was given a component
  override, which keeps the proof at `window-ready`. The real-artifact proof
  is m15's, and this is stated in the test module's own docstring, not only
  here.
- **`bundle.resources` vs `externalBin` vs sibling-directory** was not
  decided. m10 commits to the sibling-directory convention as the layout it
  reads TODAY; the mechanism ADR is m15's.
- **Windows.** The new Python module skips at module level on win32 (POSIX
  exec bits + `SIGKILL`), consistent with §4.1's POSIX authority. The Rust
  unit tests, including the platform-branch test, run everywhere `cargo test`
  does; the symlink assertion is `cfg(unix)`-gated.

## Residual risks — recorded, not closed

1. **`std::env::current_exe()` is not a security primitive.** The Rust stdlib
   documents that platforms differ on symlink resolution and names PATH-search
   and Linux-hardlink classes in which a lower-privileged process can cause it
   to return an attacker-chosen path. The containment check closes the
   ordinary relocated- and tampered-sidecar case AC4 asks for; it does NOT
   close those classes, and nothing in this milestone should be read as
   claiming otherwise. Recorded in the `resolve_inside` doc comment, in the
   test module docstring, and here.
2. **A second `current_exe()` class this design adds:** the payload root is a
   SIBLING directory of the supervisor executable, so anyone who can write
   next to the installed supervisor chooses `child_argv[0]`. Canonicalization
   does not help — the attacker's file is genuinely inside the root. The
   defense is filesystem permissions on the install location plus (later) code
   signing of the assembled bundle, which is m15's surface, not m10's.
3. **Cross-language drift is bounded but not eliminated.** The parity matrix
   pins the branches this platform can reach; the Windows branch is exercised
   only by the Rust unit test's `cfg!` arm, because no Windows runner runs the
   matrix. A `_platform_data_root` change on a branch the matrix cannot reach
   would drift silently until a Windows gate exists.
4. **One deliberate divergence from Python, asserted rather than hidden:**
   with neither `HOME` nor `USERPROFILE` set, Python falls back to
   `Path.home()` (a passwd read) and Rust refuses. Guessing a home for a
   process about to create a data root there is the worse failure.
   `::test_data_root_parity_has_exactly_one_documented_divergence` pins both
   sides of it, so it cannot quietly become two.
5. **`DESKTOP_FIXTURE_COMPONENT` widens the fixture's identity check.** It is
   test-only and non-`ARXMCP_`-prefixed (so `lifecycle.rs`'s `ARXMCP_*` scrub
   could never deliver it), and the fixture binary ships nowhere — but it does
   mean the fixture no longer refuses a foreign component name when that
   variable is set.

## external_writes_required

- `git push origin main` — copied verbatim from the research synthesis; the
  only one, and unchanged by this implementation. Per-event authorization at
  Phase 4, main thread. No push was made or attempted.

## Test deltas

- `tests/test_desktop_self_authored_launch.py` — NEW, 14 collected tests
  (1 unmarked source guard, 13 `requires_desktop_stack`, of which 9 are the
  parity matrix's parametrized rows).
- `apps/desktop/crates/supervisor/src/main.rs` `#[cfg(test)] mod tests` — 5
  new Rust unit tests (supervisor unit total 11 -> 17 including the shared
  helpers). No existing test was modified or deleted.

## Check gate results

Both run at commit `90e857e`, in this worktree, with the venv passed
explicitly because the Makefile's `PYTHON ?= python3` resolves to a 3.9 on
this box and fails the version gate.

- **`make test PYTHON=.venv/bin/python`: exit 0.** `5145 passed, 94 skipped,
  1 xfailed, 84 warnings in 200.95s`; `ruff check .` clean. The one new
  UNMARKED test is inside that 5145; the 13 `requires_desktop_stack` tests are
  inside the 94 skipped, which is correct — they are opt-in and
  `desktop-conformance` is where they run.
- **`make desktop-conformance PYTHON=.venv/bin/python`: exit 0.** Zero skips
  in every line, which the `DESKTOP_SUPERVISOR_BIN` / `ARXMCP_FIXTURE_SIDECAR`
  guard would have failed on:
  - `cargo fmt --all -- --check`: clean.
  - `cargo test --locked --workspace`: `8 passed` (desktop-contract) +
    **`17 passed`** (supervisor — 11 before this milestone) + 0 for the
    fixture and doc-test targets. 0 failed.
  - `cargo clippy --locked --workspace --all-targets --all-features
    -D warnings`: clean.
  - `tests/test_desktop_contract.py`: `42 passed in 4.63s`.
  - `tests/test_desktop_child.py`: `30 passed in 47.28s` — the m5/m6 gates
    AC3 requires run unmodified, against a file this milestone did not edit.
  - `tests/test_desktop_support_floor.py`: `33 passed in 0.39s`.
  - `tests/test_desktop_self_authored_launch.py`: **`14 passed in 1.99s`** —
    the new line, and the only one with `ARXMCP_DESKTOP_LAUNCH_PLAN` absent.
- `git status --porcelain`: clean.

## Scope report

`git diff --stat b102c85..HEAD` = **760 insertions, 10 deletions, 4 files**,
against a pre-authorized budget of ~520 LOC / ~7 files.

The 350-line checkpoint was crossed after the Rust half (377 lines, 2 files)
and is reported here rather than treated as a stop, per the dispatch. The
overrun is real and not excused by generated content — there is none in this
diff — but it is documentation-dense in this repo's style: of the 363 added
lines in `main.rs`, roughly 90 are `//` / `//!` comment lines recording the
`current_exe()` residual risk, the AC2-vacuity argument, the frozen-vs-source
identity split, and the one deliberate Python divergence. The Python module is
377 lines for 14 tests. Fewer files than budgeted (4 vs 7) because the arm
landed in one Rust file rather than being split. Well under the 800-line
abort; no partial-commit protocol was triggered.
