# Critique — desktop-distribution-m5 — milestone-infra-safety-critic

**Critic:** milestone-infra-safety-critic
**Commit range:** 1a542ee..4d797a7
**Diff stats:** 19 files, 7168 LOC (7059 insertions, 109 deletions)
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

The infra surface is small and mostly disciplined: exit codes propagate correctly on every new `desktop-conformance` recipe line, both harness env vars are scoped to exactly the line that needs them, every new Cargo dependency is exact-`=`-pinned with a committed lockfile carrying zero git sources, and the `.gitignore` entry for `gen/` hides only derived JSON Schemas — the effective ACL lives in a `capabilities/` tree that does not exist, so the webview is granted zero Tauri commands. The one HIGH is that the target's stated ALL-OR-NOTHING zero-skip contract is enforced by convention only: I ran the suite with a mismatched marker expression and got `4 skipped, 9 passed`, exit 0, which is the m3 M4 failure mode wearing a new hat. The three MEDIUMs are latent rather than live — an unused `tauri-plugin-shell` that widens the grantable permission surface, an unpinned deny-by-default ACL, and no Rust toolchain pin behind a `clippy -D warnings` gate.

## Executive summary

- [HIGH] `make desktop-conformance` exits 0 with 4 skipped tests if the marker name and the Makefile's `-m` string ever drift — empirically reproduced, not reasoned about.
- [MEDIUM] `tauri-plugin-shell` is registered and depended on but never called; the child is spawned with `std::process::Command`, so the plugin only widens the set of permissions a future capability file could grant the webview.
- [MEDIUM] The deny-by-default ACL (no `capabilities/` dir, generated `capabilities.json` is `{}`) is correct but unpinned by any test, and the generated manifest a reviewer could diff is now gitignored.
- [MEDIUM] No `rust-toolchain.toml` and no `rust-version` MSRV, while the gate runs `cargo clippy -D warnings` over ~400 newly-added transitive crates.
- [LOW] `.gitignore` ignores the whole `gen/` tree; Tauri's own template ignores `gen/schemas` specifically because `gen/android` / `gen/apple` are meant to be committed.
- [LOW] `wait_exit` returns `None` for both "budget expired" and "`try_wait` errored", so an error escalates to `SIGTERM` on a PID whose reap state is unknown.
- [LOW] The single-instance activation socket path `/tmp/com_arxmcp_desktop_si.sock` is hand-copied from plugin internals, world-squattable, and untested.
- [LOW] The 1×1 placeholder icon is the right call today (`bundle.active: false`) but nothing stops it becoming the shipped Linux app icon when bundling is enabled.

## Findings

**H1 — desktop-conformance exits 0 with skips when the marker string drifts** (HIGH)

**Where:** `Makefile:158`
**Anchor:** `DESKTOP_SUPERVISOR_BIN="$(CURDIR)/apps/de`
**What:** `-m "requires_desktop_stack or not requires_desktop_stack"` is a tautology for ANY token, so pytest's own filter selects everything regardless of the name; the only thing that actually opts the four real-stack tests IN is `tests/conftest.py:110`'s substring check `marker not in markexpr`, and when that check fails the tests are silently skipped while pytest still exits 0.
**Why it matters:** The target's documented contract is ALL-OR-NOTHING with zero skips (the m3 M4 finding), and I reproduced the degradation directly — `pytest tests/test_desktop_child.py -m "foo or not foo"` returns `4 skipped, 9 passed`, exit 0 — so a rename of the marker, a typo in either the Makefile string or `_OPT_IN_MARKERS`, or a refactor of the conftest hook turns the authoritative desktop gate green while every real-server, supervisor-binary and MCP-smoke assertion is skipped; `pyproject.toml:364` is bare `addopts = "-q"` with no `--strict-markers`, so a misspelled marker on a test raises a warning, not an error.
**Proposed fix:** Two cheap halves. (a) Extend the existing Makefile-shape meta-test `tests/test_desktop_contract.py:310` (the m3 precedent that already pins `--bin fixture-sidecar`, `ARXMCP_FIXTURE_SIDECAR=` and build-before-run ordering) to also assert `--bin supervisor` in the target, `DESKTOP_SUPERVISOR_BIN=` in the target, `target.index("--bin supervisor") < target.index("DESKTOP_SUPERVISOR_BIN=")`, and — the load-bearing part — that the marker token appearing in the recipe's `-m` string is a member of `tests.conftest._OPT_IN_MARKERS` (import it; do not re-hardcode the literal). (b) Add a zero-skip guard: a `pytest_sessionfinish` hook in `tests/conftest.py` that sets `session.exitstatus` non-zero when any test reports `skipped` while `DESKTOP_SUPERVISOR_BIN` is set in the environment, so the gate fails loudly instead of degrading.
**Regression-guard:** A test asserting the Makefile's `-m` marker token is in `tests.conftest._OPT_IN_MARKERS`, plus a check that running `tests/test_desktop_child.py` with a non-matching marker expression and `DESKTOP_SUPERVISOR_BIN` set exits non-zero.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M1 — Unused tauri-plugin-shell widens the grantable webview permission surface** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:169`
**Anchor:** `.plugin(tauri_plugin_shell::init())`
**What:** The shell plugin is initialized and declared as a dependency (`apps/desktop/crates/supervisor/Cargo.toml:18`), but nothing in the crate calls it — the child is spawned with `std::process::Command` at `apps/desktop/crates/supervisor/src/lifecycle.rs:133`, and a repo-wide grep finds only the `init()` line and the two manifest entries.
**Why it matters:** Registering it adds `shell` to the compiled ACL manifest, so `shell:allow-execute` / `allow-spawn` / `allow-open` / `allow-kill` become grantable to a webview that renders HTTP content served by the child; today's zero-capability posture makes that inert, but it converts a future one-line `shell:default` grant plus a console XSS into local command execution, and it carries build and supply-chain weight for no functional benefit.
**Proposed fix:** Delete the `.plugin(tauri_plugin_shell::init())` line, drop `tauri-plugin-shell.workspace = true` from the supervisor manifest and `tauri-plugin-shell = "=2.3.5"` from `apps/desktop/Cargo.toml:24` (no other crate references it), then re-run `cargo build --locked` and commit the refreshed `Cargo.lock`.
**Regression-guard:** Optional — assert `tauri_plugin_shell` does not appear in `apps/desktop/crates/supervisor/src/`.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline (build-script + dependency hygiene)

**M2 — Deny-by-default Tauri ACL is correct but unpinned by any test** (MEDIUM)

**Where:** `.gitignore:77`
**Anchor:** `apps/desktop/crates/supervisor/gen/`
**What:** The supervisor has no `capabilities/` directory and `tauri.conf.json` declares no `app.security.capabilities`, so the generated `gen/schemas/capabilities.json` is `{}` and the webview is granted zero Tauri commands — the correct posture — but nothing asserts it, and the generated artifact that would surface the drift is now ignored.
**Why it matters:** The window navigates to `bound.ui_url` (HTTP content served by the child), so the ACL is the boundary between a console-side scripting bug and host access; a future capability file can be added in a single commit with the gate noticing nothing, and the previously-visible `gen/schemas/acl-manifests.json` diff is no longer available as an incidental review signal.
**Proposed fix:** Add a short test beside the other desktop conformance tests asserting that `apps/desktop/crates/supervisor/capabilities/` is absent-or-empty and that the parsed `tauri.conf.json` has no `app.security.capabilities` key, so any future grant must land together with an explicit, reviewable test edit.
**Regression-guard:** `tests/test_desktop_child.py::test_supervisor_grants_no_webview_capabilities`
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline (build-script + generated-artifact hygiene)

**M3 — No Rust toolchain pin or MSRV behind a `clippy -D warnings` gate** (MEDIUM)

**Where:** `apps/desktop/Cargo.toml:22`
**Anchor:** `tauri = "=2.11.5"`
**What:** The workspace has no `rust-toolchain.toml` and no `rust-version` in any manifest, while `Makefile:152-154` gates on `cargo fmt --check` and `cargo clippy --all-targets --all-features -D warnings`.
**Why it matters:** `-D warnings` makes any lint added in a future stable Rust a hard gate failure unrelated to the change under test, and this diff sharply increases the exposure by putting the whole tauri dependency tree behind that gate; separately, tauri 2.11 raises the effective MSRV well above the edition-2021 floor, so a developer on an older toolchain gets an obscure transitive-crate error instead of a clear "upgrade rustc" message.
**Proposed fix:** Add `apps/desktop/rust-toolchain.toml` pinning `[toolchain] channel = "<the version the gate was measured on>"` with `components = ["clippy", "rustfmt"]`, and add a matching `rust-version` to `[workspace.package]` so `cargo build` fails with the real reason on an old toolchain.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**L1 — `.gitignore` ignores the whole `gen/` tree, not the canonical `gen/schemas`** (LOW)

**Where:** `.gitignore:75`
**Anchor:** `# Tauri build regenerates crate-local gen`
**What:** The comment correctly describes `gen/schemas`, but the pattern on the next line ignores every future child of `gen/`.
**Why it matters:** Tauri's own template ignores `gen/schemas` specifically because `gen/android` and `gen/apple` are generated *project* trees that are meant to be committed; if a mobile target is ever initialized under this crate the project would be silently untracked. Low, because this is a desktop-only supervisor with `bundle.active: false`.
**Proposed fix:** Narrow the pattern to `apps/desktop/crates/supervisor/gen/schemas/`, matching the comment and the upstream convention.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**L2 — `wait_exit` conflates a `try_wait` error with a timeout before signalling** (LOW)

**Where:** `apps/desktop/crates/supervisor/src/lifecycle.rs:405`
**Anchor:** `Err(_) => return None,`
**What:** `wait_exit` returns `None` both when the grace budget expires and when `child.try_wait()` errors, and `shutdown_child` treats `None` as "still running" and immediately sends `SIGTERM` to `control.child.id()`.
**Why it matters:** On the error arm the child's reap state is unknown, so the PID could in principle already be reaped and recycled and the signal would land on an unrelated process; today nothing else reaps this child so it is theoretical, but the escalation ladder's PID safety currently rests on that being true rather than on the code.
**Proposed fix:** Return `Result<Option<i64>, ()>` (or an explicit three-state enum) and, on the error arm, skip `request_terminate` entirely and go straight to the handle-based `child.kill()` / `child.wait()`, which cannot target a recycled PID.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Open scan — subprocess / process hygiene

**L3 — Single-instance socket path is hand-copied from plugin internals and squattable** (LOW)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:107`
**Anchor:** `let mut stream = UnixStream::connect("/tm`
**What:** The loser path reimplements the client half of `tauri-plugin-single-instance`'s macOS protocol against a hardcoded `/tmp/com_arxmcp_desktop_si.sock`, duplicating a derivation that lives inside the pinned plugin, and no test exercises it.
**Why it matters:** `/tmp` is world-writable, so any local user can pre-bind that path and either absorb the loser's `cwd` + argv or block the winner's listener, degrading duplicate-activation silently; and because the derivation is a copy rather than a call, a plugin upgrade can break activation with the exact-pin bump as the only signal. The code comment already concedes the correctness half ("drift only degrades activation"), but nothing covers the squat case or pins the coupling.
**Proposed fix:** Derive the path from the plugin's own public helper if one is exposed at `=2.4.3`; otherwise record the derivation as a named constant next to the identifier in `tauri.conf.json` and add a unit test asserting the two agree, so a future identifier change cannot silently orphan the socket.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Open scan — subprocess / process hygiene

**L4 — Placeholder 1×1 icon can silently become the shipped app icon** (LOW)

**Where:** `apps/desktop/crates/supervisor/tauri.conf.json:10`
**Anchor:** `"active": false,`
**What:** `icons/icon.png` is a valid 70-byte 1×1 RGBA PNG committed solely to satisfy `tauri-codegen`, and nothing in the repo marks it as a placeholder or blocks bundling on it.
**Why it matters:** With `bundle.active: false` it is inert and never shipped, but when a later milestone flips that flag the macOS and Windows bundlers fail loudly for a missing `.icns` / `.ico` while the Linux `.deb` / AppImage path would silently ship a 1×1 transparent icon.
**Proposed fix:** Add a one-line assertion to the desktop tests that either `bundle.active` is `false` or every icon listed in `bundle.icon` is at least 256×256, so enabling bundling forces a real icon in the same change.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

## What was done well

- Exit codes propagate correctly on both new recipe lines: each is a single simple command (a `VAR=value cmd` prefix assignment, not a `;`-chained compound), so make aborts the target on a non-zero status, and a missing `cargo` yields shell exit 127 rather than a silent skip.
- `ARXMCP_FIXTURE_SIDECAR` and `DESKTOP_SUPERVISOR_BIN` are each scoped to exactly one recipe line, so the m5 real-child run genuinely cannot see the fixture-sidecar path — the AC1 assertion is not being satisfied by a leaked variable.
- Keeping the supervisor harness var un-prefixed is the right call and the Makefile comment explains why, so the next reader will not "fix" it into `ARXMCP_DESKTOP_SUPERVISOR_BIN` and trip the child's unknown-env FATAL scan.
- `cargo build --locked --bin supervisor` is placed before the pytest line that consumes the binary, preserving the m3 build-before-run ordering property (the gap is only that nothing asserts it for the new pair).
- Every new dependency is exact-`=`-pinned in `[workspace.dependencies]` and consumed via `.workspace = true`, `Cargo.lock` is committed, and it carries zero `git+` sources — all four cargo invocations in the gate pass `--locked`, so the build is reproducible from the lockfile.
- The `.gitignore` entry hides nothing security-relevant: `gen/schemas/*` are derived JSON Schemas plus a manifest of *available* permissions, while the *granted* set lives in `capabilities/**` (tracked, currently absent) and the plugin surface is visible in the exact-pinned `Cargo.toml`.
- `build.rs` is a bare `tauri_build::build()` with no network access, no codegen from remote sources, and no `curl | bash`; committing the tiny icon instead of generating it at build time keeps the build hermetic and deterministic, which is the right trade.
- Process shutdown is bounded at every step — 35s grace, then `SIGTERM`, then 5s, then a handle-based `kill()` + `wait()` — and the escalation only runs on PIDs that `try_wait` has confirmed unreaped, so there is no wrong-PID reap after recycling on the normal path.
- Every wait in the supervisor carries a deadline (`BOUND_TIMEOUT`, `HEALTH_DEADLINE`, `READY_DEADLINE`, the barrier's 10s, `poll_until`, `wait_exit`); there is no unbounded poll loop, and the child's `stdin`-EOF lease means even an abrupt supervisor death cannot leave an orphan.
- The `requires_desktop_stack` marker is registered in BOTH `pyproject.toml` and `tests/conftest.py::_OPT_IN_MARKERS`, which is exactly the pairing whose omission caused issue #206; the marked tests also correctly carry no secondary skip guard, so opting in with a missing binary calls `pytest.fail` rather than skipping.

Severity counts: C0 H1 M3 L4

## Recommended rectification order

H1, M1, M2, M3, L1, L2, L3, L4

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed: <finding ids>
- Deferred: <finding ids>
- Invalidated: <finding ids with reasons>
- Regression tests added: <file paths>
