---
milestone_id: "desktop-distribution-m10"
researcher_role: "general"
external_writes_required:
  - "git push origin main"   # per-event authorization; Phase 4 boundary only
sources:
  - url: "https://v2.tauri.app/develop/resources/"
    sha256: "b525196db9c6a6395b305752880a6502e1e2b23930ac64752d0086ed8cba640d"
    takeaway: "Tauri v2 resolves a bundled resource at runtime via app.path().resolve(path, BaseDirectory::Resource); the docs page fetched does not state the concrete macOS Contents/Resources vs Contents/MacOS split, so that must be verified against tauri-utils source, not assumed from prose (note: hash is over the WebFetch tool's summarized markdown, not raw page bytes -- this doc site did not curl cleanly in the time budget available, so treat the hash as provenance-of-this-brief only, not an independent content pin)."
  - url: "https://doc.rust-lang.org/std/env/fn.current_exe.html"
    sha256: "b2fb3298ff80dd4fd8ce43fa6144583d20e2f90003a59604a7a59230326d5658"
    takeaway: "std::env::current_exe() is explicitly NOT a security primitive: platforms differ on whether a symlink invocation returns the link or its target, and the docs name PATH-search and Linux-hardlink attacks that let a lower-privileged process cause it to return an attacker-controlled path. Any AC that says child_argv[0] must 'resolve inside the application bundle... rejected if outside' needs a canonicalize-then-contains check on the RESOLVED path, and the resolution step itself must not be trusted blindly for the tampered-sidecar defense the AC asks for. (Same raw-bytes caveat as above.)"
  - url: "https://v2.tauri.app/reference/config/#bundleresources"
    sha256: "ef865d9b1d12c076e48db46d8c4448eea3528f19922f03063e10e83f86879f57"
    takeaway: "Tauri v2 has two distinct embedding mechanisms -- bundle.resources (arbitrary files, placed under a $RESOURCE root) and bundle.externalBin (sidecar binaries, resolved by Tauri to a target-triple-suffixed filename at build time). Neither is currently configured in this repo's tauri.conf.json (bundle.active is false, no resources/externalBin keys), so 'the bundled frozen child' is not yet a wired concept anywhere in the tree this milestone can read from -- it must be designed, not just consumed. (Same raw-bytes caveat as above.)"
injection_attempts: 0
---

# Research brief (general) — desktop-distribution-m10

## External sources

See `sources:` above. Only three fetches were needed: the brief is implementable
with in-repo facts plus stdlib/Tauri path-resolution semantics; no
library/framework CHOICE is being made here (Tauri, PyInstaller and the wire
contract are all already fixed by m1–m9), so this was a verification pass on
"how does the runtime resolve a path inside its own bundle", not a survey.

**Load-bearing repo-state finding, not from the web:** `apps/desktop/crates/supervisor/tauri.conf.json`
currently reads `"bundle": {"active": false, ...}` with no `resources` or
`externalBin` key (confirmed by direct read, 2026-08-11). m7's synthesis
(`.claude/notes/milestones/desktop-distribution-m7/research/synthesis.md`)
built the PyInstaller onedir/onefile artifact and the `make desktop-package`
gate, but never touched `tauri.conf.json` — "the bundled frozen child" that
this milestone's brief takes as a given input is not yet reachable from the
supervisor by any committed mechanism. Phase 2 needs a decision (bundle.resources
vs externalBin vs a documented convention of "the frozen child ships as a
sibling directory next to the .app, located via `current_exe()`'s parent
chain") before `child_argv` derivation can be written — this is upstream of
the milestone's own stated scope and worth flagging to the implementer
explicitly rather than assuming m7 already answered it.

## Acceptance criteria the implementer must meet

1. With `ARXMCP_DESKTOP_LAUNCH_PLAN` unset, launching the bundled application
   reaches a ready server and a rendered window; the regression's RED state
   must be the documented `fail("ARXMCP_DESKTOP_LAUNCH_PLAN is required")` /
   `exit(2)` path at `apps/desktop/crates/supervisor/src/main.rs:65-72`, not
   merely an assertion that the new arm succeeds.
2. A self-authored plan is fed through the SAME `validate_plan` function at
   `main.rs:84-105` (not re-implemented, not asserted by inspection) and is
   refused under every one of its `!plan.smoke && (...)` five-knob rule —
   `test_bound_timeout_ms`, `test_fault`, `test_hide_window`,
   `test_shutdown_force_after_ms`, `test_shutdown_grace_ms` — since a
   self-authored plan is by definition never `smoke: true`.
3. The environment-supplied path (`load_plan`'s existing `PLAN_ENV` branch,
   `main.rs:70-81`) is byte-identically preserved; m5 lifecycle, m6 fault
   matrix (`apps/desktop/crates/supervisor/src/lifecycle.rs` tests), and m8
   frozen-child gates (`requires_desktop_package`, `requires_bundled_model`
   markers per root `CLAUDE.md` §4.5) run unmodified.
4. `child_argv[0]`'s resolved path (canonicalized, not the possibly-symlinked
   raw string per the `current_exe()` caveats above) must be proven inside the
   application bundle root, and rejected when it resolves outside — mirroring
   the existing `_inside()` / `relative_to()` containment pattern already used
   in this repo at `server/application_paths.py:59-67` and the Windows-fixed
   `Path.is_relative_to` pattern noted in root `CLAUDE.md` §3 (the 2026-07-12
   win32-portability push), rather than a hand-rolled string-prefix check.
5. The `startup_token` is freshly generated per launch (the self-authoring
   code path must call the same `generate_startup_token()` from
   `arxmcp_desktop_contract` that `lifecycle.rs:110` already uses for the
   environment-supplied path — do not invent a second generator), never
   persisted, and absent from argv and every persisted diagnostic — the m6
   redaction scan (`apps/desktop/crates/supervisor/src/redact.rs`) needs an
   explicit test case exercising the self-authored path, since today it is
   only exercised via `lifecycle::run_cycle` with an externally-loaded plan.
6. `make test` and `make desktop-conformance` exit 0 (root `CLAUDE.md` §9
   documents both commands; `desktop-conformance` builds both Rust binaries
   and exports `DESKTOP_SUPERVISOR_BIN` + `ARXMCP_FIXTURE_SIDECAR`, so a skip
   anywhere in that session is itself a failure per §4.5's
   `requires_desktop_stack` rule).
7. `data_root` must come from the SAME `_platform_data_root()` Python function
   at `server/application_paths.py:81-89` — but note this is a **Python**
   function and `main.rs` is Rust with no FFI boundary into it today; the
   supervisor's self-authoring code must either replicate the exact
   platform-branch logic in Rust (`LOCALAPPDATA`/`AppData\Local` on Windows,
   `~/Library/Application Support` on macOS, `XDG_DATA_HOME`/`~/.local/share`
   on Linux, all suffixed `arXMCP`) or invoke the Python child once to ask it
   — the brief's wording assumes parity exists; it does not exist as
   cross-language-callable code yet, so Phase 2 must pick one and the choice
   is itself risk-bearing (see below).

## Risks and open questions

1. **Two independent "derive `child_argv`/`data_root`" implementations must
   never drift.** The brief's phrasing ("derives ... from `_platform_data_root`")
   reads as reuse, but `_platform_data_root` is Python and the supervisor is
   Rust with no committed bridge. A hand-copied Rust port of the four-branch
   `home`/platform logic is the obvious path and is also the classic silent-drift
   hazard this repo's own memory has hit before (win32-portability push,
   `CLAUDE.md` §3) — recommend a single regression that runs BOTH
   implementations against a matrix of env-var combinations and asserts
   byte-identical output, not a one-time eyeball comparison.
2. **The bundled frozen child has no wired bundle mechanism yet** (see
   External sources above) — `tauri.conf.json` has no `resources` or
   `externalBin` entry. This is the single largest unknown: whichever
   mechanism Phase 2 picks (Tauri resource, Tauri sidecar/externalBin, or an
   ad-hoc sibling-directory convention resolved off `current_exe()`) changes
   where `child_argv[0]` is expected to live and therefore what "resolves
   inside the application bundle" (AC4) even means structurally on each OS.
3. **`current_exe()` is explicitly not a security primitive** (Rust stdlib
   docs, source above) — canonicalizing it and checking containment closes
   the ordinary relocated/tampered-sidecar case AC4 asks for, but a
   privileged-process PATH-search or hardlink attack against `current_exe()`
   itself is a known unclosed class the stdlib docs name outright. Worth
   recording as an accepted residual risk in the implementer's synthesis
   rather than silently assuming the containment check is airtight.
4. **`smoke: true` is structurally unreachable from the self-authored arm**
   (a double-clicked `.app` never sets it), which makes AC2's "refused under
   every rule that refuses an externally supplied one" trivially true for the
   five `!smoke`-gated knobs specifically — worth a test that also proves the
   OTHER `validate_plan` rule (`child_argv.is_empty()`) is independently
   reachable and refused on a self-authored plan with an empty derived argv,
   so the AC is exercised on both of `validate_plan`'s current branches, not
   just the one the brief calls out by name.
5. **`data_root` must independently satisfy `main.rs:194-196`'s
   `root.is_absolute()` check** and the `fs::create_dir_all(root.join("logs"))`
   step at `main.rs:197-199` — both already run unconditionally after
   `load_plan()` regardless of which arm produced the plan, so no new
   validation is needed there, but a self-authored `data_root` that resolves
   to a relative path (e.g. a platform branch bug) fails at the SAME `fail()`
   call the environment-supplied path uses, which is good for AC1's "reproduce
   the exit(2) as RED state" framing but bad if a bug in the new arm is
   mistaken for the environment-path bug during test triage — name the arm in
   the recorder event or an error-message suffix if `validate_plan`/`fail()`
   is touched at all.

## external_writes_required

- `git push origin main` — the only external write any implementation of
  this milestone plausibly needs; per-event authorization happens in Phase 4
  main-thread only (root `CLAUDE.md` §4.4, `agent-conventions.md` §8). No
  package publish, no deploy, no mutating API call, no `gh` invocation
  anywhere in scope — the milestone is entirely local Rust + Python source
  changes plus local test/build gates (`make test`,
  `make desktop-conformance`).
