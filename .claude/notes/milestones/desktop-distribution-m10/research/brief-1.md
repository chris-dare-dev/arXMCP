---
milestone_id: "desktop-distribution-m10"
researcher_role: "explore"
injection_attempts: 0
---

# Research brief (explore) — desktop-distribution-m10

## Affected files / context

- `apps/desktop/crates/supervisor/src/main.rs` — the core change site.
  - `load_plan()` (:70-81): today `std::env::var_os(PLAN_ENV)` absent ->
    `fail("ARXMCP_DESKTOP_LAUNCH_PLAN is required")` -> `exit(2)`. This
    milestone adds a self-authoring arm here (or a new function called from
    here) that builds a `Plan` when the env var is unset, then still runs it
    through `validate_plan`.
  - `Plan` struct (:27-63, `#[serde(deny_unknown_fields)]`) — fields the
    self-authored plan must populate: `child_argv: Vec<String>`, `component`,
    `data_root` (wire-style absolute POSIX path per
    `desktop-contract`'s `validate_paths`), `identity_file`, `smoke: bool`
    (must be `false` for a real launch), `version`. The five `test_*` fields
    must stay `None`/default — `validate_plan` already refuses them when
    `!smoke` (see below), so a self-authored plan simply never sets them.
  - `validate_plan()` (:84-105) — pure function, already unit-tested
    (`plan_rejects_unknown_fields_and_empty_argv`,
    `test_only_knobs_are_refused_outside_smoke_mode`, both in the same
    `#[cfg(test)] mod tests` block, :320-360). AC2 requires feeding the
    self-authored plan through THIS SAME function (call it directly from a
    Rust test, not just eyeball the constructed struct).
  - `fail()` (:65-68) is the only call site of `process::exit(2)` in the
    file — the RED-state regression (AC1) must observe this exact path
    still exists for some other trigger, or more precisely must show the
    *documented* `exit(2)` reproduces before the fix and disappears (in the
    unset-env case) after it.
  - `main()` (:191) calls `load_plan()` first thing, then treats
    `plan.data_root` as already-absolute wire-style path, creates
    `root.join("logs")`, then proceeds through lock acquisition /
    single-instance arbitration / Tauri window / `lifecycle::run_cycle`.
    None of that changes for m10 — only what feeds `plan` upstream of it.
- `apps/desktop/crates/supervisor/src/lifecycle.rs` — consumes `plan`
  downstream: `file_sha256(&plan.identity_file)` (:109) computes the
  expected identity digest, `component: plan.component.clone()` (:112) feeds
  the `Launch` control frame, and `Command::new(&plan.child_argv[0])` (:158)
  plus `.args(&plan.child_argv[1..])` (:160) actually spawns the child. A
  self-authored plan's `child_argv[0]` therefore needs to be a real,
  spawnable path once resolved (see "bundle resolution" risk below) — the
  code that does the sha256 + spawn is unaffected as long as the plan shape
  is correct.
- `apps/desktop/crates/desktop-contract/src/lib.rs` — the Rust half of the
  wire contract `Launch`/`Bound`/`Shutdown` frames (`data_root`,
  `startup_token`, `validate_paths` at :343/:361, `StartupToken::parse` at
  :346/:381). Not touched by m10 directly, but the self-authored plan's
  `data_root` must satisfy the SAME `validate_paths` rule the environment
  path already satisfies (canonical, absolute, `log_location` beneath
  `data_root/logs`) — see `server/desktop_contract.py::_validate_paths`
  (:467-478) for the Python mirror, since the child validates the frame it
  receives independently.
- `server/desktop_child.py` — the Python child side. Nothing here changes
  for m10 (the plan is authored by the Rust supervisor, not the Python
  child), but two functions matter as reference/parity points:
  - `COMPONENT = "arxmcp-server-desktop-child"` (:69) — the value a
    self-authored plan's `component` field must match (tests key off
    `executable_identity().component`).
  - `identity_source_path()` (:98-110) and `executable_identity()`
    (:113-118) — show the frozen-vs-source identity split
    (`sys.frozen` -> `Path(sys.executable)`, i.e. the frozen executable
    IS its own identity file). A self-authored plan's `identity_file`
    should point at the SAME frozen executable path used as
    `child_argv[0]`, mirroring how `tests/test_desktop_child.py`'s
    `CHILD_ARGV = [sys.executable, "-m", "server.desktop_child"]` pairs
    with `identity_file: str(REPO_ROOT / "server" / "desktop_child.py")`
    in the source-checkout test plan (`test_desktop_child.py:415-421`,
    reused at :951-957).
- `server/application_paths.py::_platform_data_root()` (:81-89) — the
  function the brief names as the `data_root` source: on darwin returns
  `~/Library/Application Support/arXMCP`; on win32
  `%LOCALAPPDATA%\arXMCP`; else `$XDG_DATA_HOME/.local/share/arXMCP`. This
  is PYTHON code; the Rust supervisor has no existing binding to it. m10's
  self-authoring arm in `main.rs` must either (a) reimplement the same
  three-branch logic in Rust (drift risk — two independent
  implementations of the "installed" default that must never diverge), or
  (b) shell out to Python to compute it, or (c) some other single-owner
  mechanism. This is the single biggest open design question this brief
  surfaces — worth flagging explicitly to the implementer, since the
  milestone's own description says "deriving `data_root` from
  `_platform_data_root`" but that function lives in a different language
  runtime than the code that must call it.
- `server/desktop_contract.py::generate_startup_token()` (:78-80) /
  `StartupToken` (:52-76) — Python side of "fresh `startup_token` per
  launch"; already used by the environment-supplied path
  (`tests/test_desktop_child.py` builds `Launch` frames with
  `generate_startup_token()`). The Rust side's equivalent is
  `apps/desktop/crates/desktop-contract/src/lib.rs:90
  generate_startup_token()`. Note the STARTUP TOKEN IS NOT PART OF THE
  `Plan` STRUCT AT ALL (`main.rs:27-63` has no `startup_token` field) —
  it is generated later, inside `lifecycle.rs`'s launch-frame construction
  (confirmed by the plan_rejects_unknown_fields_and_empty_argv test using
  a plan JSON WITH a `startup_token` key and asserting
  `serde_json::from_slice` REJECTS it, because `deny_unknown_fields`
  doesn't recognize that key on `Plan`). So m10 does not need to touch
  token generation at all — token freshness is already handled downstream
  of `load_plan()`, for both the environment and (once added)
  self-authored arms alike. This matters for AC5: the redaction proof
  extension is about the DIAGNOSTICS WRITER (`redact.rs`) and event
  `Recorder`, not about `Plan`/`load_plan`.
- `apps/desktop/crates/supervisor/src/redact.rs` (56 lines) — the
  redaction-to-standard code AC5 says must be "extended" to cover this
  path. Read this file in Phase 2 before claiming AC5 is met; it is short
  enough to read in full.
- `apps/desktop/crates/supervisor/src/events.rs` (65 lines) — `Recorder`,
  used throughout `main.rs` (`recorder.record(...)`) for the
  "lock-contended" / "supervisor-started" / "duplicate-activation" /
  "shutdown-on-exit" diagnostic events. A self-authored-plan event (or at
  minimum, no accidental token leakage into an existing event) should be
  checked against this file's serialization path.
- `apps/desktop/crates/supervisor/tauri.conf.json` — currently
  `"bundle": {"active": false, ...}` with `minimumSystemVersion: "14.0"`
  (set by m9) but NO `resources` or `externalBin` entries. **This is a gap
  the milestone brief does not mention**: for "launching the bundled
  application" (AC1) to be a real end-to-end proof rather than a
  same-checkout simulation, SOMETHING has to configure Tauri to bundle the
  PyInstaller-frozen child (from m7's `make desktop-package` output,
  `var/desktop-package/dist/<BUNDLE_NAME>/`) as a resource/externalBin
  inside the `.app`, and `bundle.active` has to flip to `true` (or the
  test harness has to fake an equivalent layout). Flag this as scope risk
  to the implementer: "derive `child_argv` from the bundled frozen child"
  presumes the frozen child is IN the bundle, which today it structurally
  is not wired to be.
- `apps/desktop/pyinstaller/desktop_package.py` (`build_bundle()` :290,
  `BUNDLE_NAME` constant, `distpath`) and
  `apps/desktop/pyinstaller/arxmcp_desktop.spec` (`child_exe = EXE(...)`
  :153, `probe_exe = EXE(...)` :185, `COLLECT(...)` :209) — m7's output
  shape. The self-authored `child_argv[0]` path resolution (AC4: "resolves
  inside the application bundle... rejected if it resolves outside it")
  will need to know this onedir layout to compute both the expected
  in-bundle path AND the containment check.
- `tests/test_desktop_child.py` (1611 lines) — existing environment-path
  test surface that AC3 requires be preserved byte-identically. Notable
  landmarks: `CHILD_ARGV` (:88), the two existing `ARXMCP_DESKTOP_LAUNCH_PLAN`
  writers (:429, :957 — the ONLY writers of that env var in the whole tree
  per the roadmap's own m10 framing), `SUPERVISOR_BIN_ENV`,
  `test_ac3_zero_delay_race_single_spawn` (~:405-460, m5 AC3),
  presumably further down: the m6 fault matrix tests (startup timeout,
  malformed bound frame, child crash, supervisor crash, ignored shutdown)
  and m8's frozen-child boot test. A `grep -n "requires_desktop_stack"
  tests/test_desktop_child.py` in Phase 2 will enumerate every test that
  AC3 says must run "unmodified" — useful as a literal diff-scope fence.
- `apps/desktop/crates/supervisor/src/main.rs`'s own `#[cfg(test)] mod
  tests` (:316-403) is the natural home for the new Rust-side unit tests:
  a `load_plan`-equivalent test for the self-authoring arm (though
  `load_plan` itself calls `fail()` which `exit()`s, so the self-authoring
  logic likely needs to be split into its own pure, testable function the
  same way `validate_plan` was split out of `load_plan` — same pattern,
  reapply it).
- `Makefile` `desktop-conformance` target (:161-169) and
  `desktop-package`/`desktop-package-check` targets (:179-196) — AC6 says
  both `make test` and `make desktop-conformance` must exit 0; neither
  currently exercises the unset-`ARXMCP_DESKTOP_LAUNCH_PLAN` path (every
  existing invocation sets the env var), which is exactly the roadmap
  finding that motivated this milestone.

## Acceptance criteria the implementer must meet

1. RED-state regression: with `ARXMCP_DESKTOP_LAUNCH_PLAN` unset, the
   CURRENT tree must be shown to `exit(2)` via `fail("ARXMCP_DESKTOP_LAUNCH_PLAN
   is required")` in `main.rs:70-73`; a test that only checks the new arm's
   success is explicitly disallowed by the brief.
2. Self-authored plan refused by `validate_plan` under every rule that
   refuses an external one — call `validate_plan()` directly (it's already
   `pub`-visible to the `#[cfg(test)] mod tests` block, or make it
   accessible) on the self-authored `Plan` value, not just inspect fields.
3. Byte-identical preservation of the m5/m6/m8 environment-path gates —
   scope the diff so `load_plan()`'s existing `Some(path)` branch is
   untouched logic, only the `None` branch changes from `fail(...)` to a
   new self-authoring call.
4. `child_argv[0]` bundle-containment check — resolves inside the app
   bundle, rejected if outside. No existing containment-check code was
   found in `main.rs`/`lifecycle.rs`; this is new logic, and needs a
   canonical "app bundle root" reference point (likely
   `std::env::current_exe()` of the supervisor itself, since on macOS the
   supervisor binary's own path IS inside `<App>.app/Contents/MacOS/`, and
   siblings/resources live under `<App>.app/Contents/Resources/`).
5. Startup token freshness/non-persistence — already the existing design
   (token generated in `lifecycle.rs`, never on `Plan`); AC5 is really
   about extending the m6 redaction SCAN's coverage to include whatever new
   code path or diagnostic event m10 adds, not about changing token
   handling itself.
6. `make test` and `make desktop-conformance` exit 0 — `desktop-conformance`
   already runs `requires_desktop_stack` tests with zero skips; a new test
   for the unset-env arm will need to run WITHOUT
   `ARXMCP_DESKTOP_LAUNCH_PLAN` set (every current desktop-stack test sets
   it), which is a genuinely new test-harness shape, not a copy of an
   existing test.

## Risks and open questions

1. **Cross-language `_platform_data_root` duplication.** The brief says
   derive `data_root` from `_platform_data_root`, but that function is
   Python (`server/application_paths.py:81-89`) and `main.rs` is Rust with
   no existing Python interop. Reimplementing the three-branch
   (win32/darwin/xdg) logic in Rust risks silent drift between the two
   "installed default" implementations — worth a same-milestone test that
   pins both to the same expected value per platform, or a documented
   single-owner decision (e.g., Rust computes it and Python's function
   becomes the non-desktop-boot-path default only).
2. **Bundle resource wiring is presumed, not present.** `tauri.conf.json`
   has `bundle.active: false` and no `resources`/`externalBin` entries
   today. AC1 ("launching the bundled application reaches a ready server")
   is not achievable as a genuine end-to-end proof until something
   configures Tauri to actually embed the PyInstaller output. This may be
   in-scope for m10 or may be a silently-assumed prerequisite the
   implementer needs to flag back — the roadmap epic e3 intro doesn't
   mention it either.
3. **`identity_file` vs `child_argv[0]` coupling risk.** For the
   environment-path test plans, `identity_file` points at
   `server/desktop_child.py` (source) while `child_argv` invokes
   `sys.executable -m server.desktop_child` — i.e., identity is NOT
   `child_argv[0]` in the source-checkout case. For the FROZEN case,
   `identity_source_path()` in Python returns `Path(sys.executable)` (the
   frozen executable itself), meaning `identity_file` and `child_argv[0]`
   converge to the same path once frozen. The self-authoring Rust code
   must construct the frozen-case plan correctly (`identity_file ==
   child_argv[0]`), which differs from every existing test fixture's
   shape — a naive copy of the test-plan-building pattern would be wrong.
4. **`validate_plan`'s `!plan.smoke` branch interacting with a real
   launch.** A self-authored production plan MUST have `smoke: false` (a
   double-clicked `.app` should not exit after one cycle), which means it
   automatically falls under the strict branch of `validate_plan` that
   refuses all five test-only knobs — correct, but worth an explicit test
   asserting the self-authored plan's `smoke` field really is `false`
   (accidentally defaulting it to `true` would make a shipped app quit
   after one MCP smoke, which would look like "works in testing, broken
   for real users").
5. **No existing Rust test harness runs with the plan env var absent.**
   Every `requires_desktop_stack` Python test that spawns the supervisor
   binary sets `ARXMCP_DESKTOP_LAUNCH_PLAN` deliberately (both call sites
   in `tests/test_desktop_child.py`). A conformance-gate test for the
   unset case needs a new fixture shape — likely a Rust `#[test]` in
   `main.rs`'s own test module (fast, no subprocess) plus, if the AC1
   "reaches a ready server and a rendered window" claim needs a real
   end-to-end proof, a new `requires_desktop_stack` Python test that
   explicitly REMOVES the var from `env` before spawning — the opposite of
   every existing pattern in that file.
