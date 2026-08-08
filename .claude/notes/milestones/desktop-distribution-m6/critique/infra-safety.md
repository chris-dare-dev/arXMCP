# Critique — desktop-distribution-m6 — milestone-infra-safety-critic

**Critic:** milestone-infra-safety-critic
**Commit range:** c0dcf98..822dab7
**Diff stats:** 16 files, 1279 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

The dependency and fixture-pinning axes are clean — `libc` is exactly `=` pinned
at the workspace, `Cargo.lock` carries the matching checksum with no new
download, `--locked` genuinely holds, and the aggregate `fixtures.sha256`
recomputes byte-exact to its new pinned value. The tauri exit-code workaround
was audited against tauri 2.11.5's own source and is safe: the single-instance
plugin's socket unlink runs *before* the user callback, so `std::process::exit`
skips only `cleanup_before_exit()`, which touches nothing durable. What holds
this back is process and evidence hygiene under the exception path: the
`ps`/`lsof` discriminator provably cannot tell a broken probe from clean
absence, the two headline AC3/AC5 evidence tests can silently skip while
`make desktop-conformance` still exits 0, and a failed fault-matrix run can
strand a SIGTERM-immune orphan on the developer's machine.

## Executive summary

- [HIGH] `_probe_command`'s "found(0)/not-found(1)" discriminator is factually wrong for both tools — `lsof` and `ps` return 1 on genuine errors too (measured on this box), so a broken probe reads as verified absence, which is precisely what AC3 forbids.
- [HIGH] The zero-skip gate guard keys on `DESKTOP_SUPERVISOR_BIN` only, so the `make desktop-conformance` invocation that runs AC3's 30-cycle orphan audit and AC5's fixture loopback proof has no skip guard; both can vanish and the gate still exits 0.
- [HIGH] Nothing in the m6 fault matrix reaps the fixture-sidecar grandchild on the exception path; the `ignore-shutdown` arm ignores SIGTERM, stdin EOF and channel disconnect, so a timed-out run leaves a 5 ms-polling orphan holding a loopback listener.
- [MEDIUM] `assert wall < 30.0` in the escalation-ladder test measures tauri boot plus spawn, not the ladder, and contradicts the same test's own 90 s wait budget — the m3 "200 ms → 2 s under load" flake shape.
- [MEDIUM] `pyproject.toml`'s `requires_desktop_stack` description still says m5-only and never names the new hard `ps`/`lsof` prerequisite that `make test` can now reach.
- [LOW] `park_on_lease`'s `Err(_) => {}` arm has no backoff and no exit condition, so a persistent stdin I/O error spins the parked fixture at 100% CPU forever.
- [CLEAN] Cargo pinning, `Cargo.lock` consistency, `--locked` offline behavior, the `cfg(unix)` scoping of `libc`, and the `fixtures.sha256` update are all verified correct.
- [CLEAN] The tauri workaround is version-pinned (`tauri = "=2.11.5"`) and skips no durable cleanup — verified against tauri 2.11.5 `app.rs:1430-1437` and the plugin's `on_event` hook.

## Findings

**H1 — ps/lsof exit-code discriminator cannot detect a failed probe** (HIGH)

**Where:** `tests/test_desktop_contract.py:200`
**Anchor:** `    if completed.returncode not in (0, 1):`
**What:** The helper's docstring claims it raises on "an exit code other than the tool's documented found(0)/not-found(1) pair", but neither tool has such a pair — measured on this box, `lsof -nP --bogus` exits 1, `lsof -nP -iTCP:99999999` exits 1, and `ps -p notanumber` exits 1, exactly as a clean no-match does.
**Why it matters:** AC3 requires that "a failed or partial `ps`/`lsof` probe is an evidence failure, never clean absence", and this is the sole mechanism enforcing it — a `ps` restricted by `hidepid`, an `lsof` denied kernel access, or any malformed argument makes `_listener_lines` return `[]` and `_pid_is_gone` return `True`, so every orphan and residual-listener assertion in the 30-cycle audit and all six fault tests passes vacuously.
**Proposed fix:** Replace the PID probe with `os.kill(pid, 0)` — `ProcessLookupError` is unambiguous "gone", `PermissionError` is unambiguous "alive", and there is no subprocess to misreport. For `lsof`, make every absence probe carry its own positive control: query the dead port together with a port the test holds open (`-iTCP:<dead>,<control>`) and require the control row to appear, so an exit-1 with no control row is an error rather than absence. Fix the docstring's exit-code claim in the same edit — a stale comment is a bug per the code-comment contract.
**Regression-guard:** A test that monkeypatches `_probe_command`'s resolved binary to a stub exiting 1 with empty stdout and asserts `_listener_lines` / `_pid_is_gone` RAISE rather than report absence.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**H2 — AC3 and AC5 evidence can silently skip out of the conformance gate** (HIGH)

**Where:** `tests/test_desktop_contract.py:697`
**Anchor:** `        pytest.skip("build fixture-sidecar or set ARXMCP_FIXTURE`
**What:** `test_thirty_cycles_distinct_pids_no_orphans_no_listeners` (AC3) and `test_live_listener_is_loopback_only_at_socket_level` (AC5) skip when `_sidecar_binary()` returns `None`, and `conftest.py:58`'s zero-skip guard fires only when `DESKTOP_SUPERVISOR_BIN` is set — which is true for `Makefile:158` but not for `Makefile:157`, the invocation that actually runs these two tests.
**Why it matters:** `_sidecar_binary()` returns `None` even when `ARXMCP_FIXTURE_SIDECAR` is explicitly set but the path is not a file (wrong `DESKTOP_EXE_SUFFIX`, an interrupted `cargo build`, a `--target` build landing elsewhere), so the milestone's two headline acceptance criteria can disappear from the gate that exists to prove them while `make desktop-conformance` still exits 0 — the exact silent-degradation shape m5's H3 guard was written to kill, left uncovered on the other half of the gate.
**Proposed fix:** Two cheap symmetric changes. In `_sidecar_binary`, when `ARXMCP_FIXTURE_SIDECAR` is explicitly set but is not a file, `pytest.fail` instead of returning `None` — mirroring `_supervisor_binary` and `_fixture_binary`, which m6 already wrote that way. Then widen `conftest.py`'s `_DESKTOP_GATE_ENV` to a tuple including `ARXMCP_FIXTURE_SIDECAR` so `Makefile:157`'s session is equally all-or-nothing.
**Regression-guard:** Run `ARXMCP_FIXTURE_SIDECAR=/nonexistent python -m pytest tests/test_desktop_contract.py` and assert a non-zero exit; today it exits 0 with skips.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**H3 — No teardown reaps the grandchild; ignore-shutdown arm is SIGTERM-immune** (HIGH)

**Where:** `tests/test_desktop_child.py:1079`
**Anchor:** `        _stop_process(process)`
**What:** Every fault test's `finally` calls `_stop_process` on the supervisor only; the fixture-sidecar grandchild is never recorded for cleanup, and under the `ignore-shutdown` arm it installs `SIG_IGN` on SIGTERM (`fixture-sidecar/src/main.rs:191`) *and* falls through on both `LeaseEvent::Eof` and `TryRecvError::Disconnected`, so nothing short of SIGKILL ends it.
**Why it matters:** When `process.wait(timeout=90)` expires — which is exactly what happens if the escalation ladder this test exists to verify is broken — `_stop_process` SIGTERMs then SIGKILLs the supervisor mid-ladder, and the sidecar survives as a permanent orphan polling `accept()` every 5 ms and holding a loopback listener, on a milestone whose whole subject is "leaving no process and no listener"; the developer gets no signal and `kill -9` is the only remedy.
**Proposed fix:** Capture `child_pid` from the `child-spawn` event as soon as it appears and reap it in the same `finally` with `os.kill(pid, signal.SIGKILL)` guarded by `ProcessLookupError` (SIGTERM is useless for the ignore-shutdown arm). Back that with a session-scoped autouse fixture in `tests/conftest.py` that SIGKILLs any surviving PID recorded by a fault test, so a `KeyboardInterrupt` or a harness SIGTERM to pytest cannot strand one either.
**Regression-guard:** A test that spawns the `ignore-shutdown` arm, SIGKILLs the supervisor before its ladder completes, and asserts the harness reaps the sidecar PID within a bounded wait.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M1 — Escalation-ladder wall budget measures tauri boot, not the ladder** (MEDIUM)

**Where:** `tests/test_desktop_child.py:1082`
**Anchor:** `    assert wall < 30.0, f"escalation ladder took {wall`
**What:** `wall` starts before `_spawn_fault_supervisor`, so the 30 s ceiling covers plan authoring, supervisor exec, tauri app build, webview window creation, child spawn, readiness poll and smoke HTTP — while the ~800 ms shrunk ladder it names is a small fraction of it, and the same test tolerates 90 s at `process.wait`.
**Why it matters:** The assertion and the wait budget disagree by 3x, so a run taking 40 s passes the wait and then fails an assertion whose message blames the escalation ladder — the m3 "200 ms → 2 s under load" flake shape, aimed at the most boot-variable path in the suite.
**Proposed fix:** The `Recorder` already stamps a monotonic `elapsed_ms` on every event (`supervisor/src/events.rs:42`). Assert on the `child-ready` → `orphan-shutdown` `elapsed_ms` delta instead of wall clock: that measures only the ladder, excludes tauri boot entirely, and can keep a tight bound (a few seconds) without flaking.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M2 — Marker description stale; ps/lsof prerequisite undeclared** (MEDIUM)

**Where:** `pyproject.toml:374`
**Anchor:** `    "requires_desktop_stack: desktop-distribution-m5 rea`
**What:** `CLAUDE.md` was updated to `desktop-distribution-m5/m6` in this range but the marker description it mirrors still reads m5-only, and neither text declares that `ps` and `lsof` are now hard prerequisites that raise `RuntimeError` rather than skipping.
**Why it matters:** The unmarked `test_thirty_cycles…` and `test_live_listener…` gate on the fixture binary existing at the default build path, so on any box that has run `make desktop-conformance` a subsequent plain `make test` runs them and hard-fails if `lsof` is absent — the `requires_latexmlc` / issue-#206 failure shape the marker's own text cites as its precedent, now reachable from the everyday target.
**Proposed fix:** Update the `requires_desktop_stack` string to m5/m6 and name `ps` + `lsof` as prerequisites with install hints (`apt install lsof`; present by default on macOS), matching how `requires_latexmlc` and `requires_pdflatex` document theirs. Mention the same two tools in `apps/desktop/README.md`'s new "Fault matrix and cleanup claims (m6)" section, which currently describes the probes' self-assertion discipline without saying they must be installed.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**L1 — park_on_lease error arm has no backoff and no exit condition** (LOW)

**Where:** `apps/desktop/crates/fixture-sidecar/src/main.rs:182`
**Anchor:** `            Err(_) => {}`
**What:** The startup-timeout park loop swallows every `read_frame` error and immediately retries with no sleep and no attempt counter, so a persistent stdin I/O error (as opposed to EOF, which returns cleanly) becomes an unbounded hot loop.
**Why it matters:** The sibling `spawn_control_reader` at `:286` at least escapes when its channel send fails; this loop has no escape at all, so the one arm designed to sit parked while the supervisor times out is also the one that can spin a core indefinitely — the failure class this milestone exists to eliminate.
**Proposed fix:** Bound the arm: sleep `POLL_INTERVAL` on error and return after a small consecutive-error count (three is plenty), so a wedged stdin ends the fixture rather than burning a core.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

## What was done well

- **Cargo pinning is exact and the lockfile is honest.** `libc = "=0.2.189"` sits in `[workspace.dependencies]` with an `=` pin matching every other entry; `Cargo.lock` already carried `libc 0.2.189` with its checksum, so the diff is a single `+ "libc",` edge under `arxmcp-fixture-sidecar` — no new download, and `--locked` (used on all four cargo invocations in `desktop-conformance`) genuinely holds offline.
- **The new dependency is platform-scoped rather than unconditional.** `[target.'cfg(unix)'.dependencies]` keeps `libc` off the Windows build, paired with a `#[cfg(not(unix))] fn ignore_sigterm() {}` stub — the right shape, and the Cargo.toml comment says exactly why the dependency exists in one line.
- **The fixture digest update is verifiable and verified.** Recomputing the documented algorithm (lexicographic `.jsonl`, `UTF-8 filename` + NUL + bytes) over the directory reproduces the new pin `69eae062…` byte-exact, with `redaction-vectors.jsonl` as the single added input; both the Rust (`desktop-contract/tests/contract.rs:128`) and Python (`test_desktop_contract.py:386`) gates independently re-derive it.
- **The tauri exit-code workaround skips nothing durable, and that is checkable rather than asserted.** Against tauri 2.11.5's own `app.rs:1430-1437`, `on_event_loop_event` dispatches plugin hooks *before* the user callback, so `tauri-plugin-single-instance`'s `RunEvent::Exit` → `destroy` → `socket_cleanup` unlinks `/tmp/com_arxmcp_desktop_si.sock` before `std::process::exit` runs; the only thing skipped is `cleanup_before_exit()`, which clears in-process resource tables and (Windows-only) hides a window — nothing that survives the process.
- **The workaround is pinned to the version it was measured against.** `tauri = "=2.11.5"` is an exact pin, and the comment states the measured behavior ("a failed cycle exited 0") rather than a guess, so a future bump is a deliberate act with the rationale sitting next to the code.
- **Test-only knobs are structurally incapable of reaching production.** The four `test_*` plan fields are `#[serde(default)]` Options asserted absent in the golden-plan unit test, the fault switch rides a namespaced `org.arxmcp.test-fault` extension the production child never reads, and the shrunk grace/force budgets change only this process's local waits — the wire frame keeps `MIN_GRACE_MS`, so no contract bump was needed and none was taken.
- **Probe self-checks are present where they matter most.** `_assert_loopback_only` asserts lsof *finds* the listener before trusting its address column, `_connect_probe` proves a successful connect before the test expects a refusal, and the 30-cycle audit proves each listener live over HTTP before stopping it — a broken probe cannot satisfy both halves.
- **The README states the non-claims instead of implying universal cleanup.** The new m6 section names both spike-3 limits explicitly — a dead parent cannot kill a wedged child, and the supervisor signals only the direct child PID, never a process group — plus the condition under which the second must be re-opened.
- **Redaction runs before truncation, and the ordering is documented as load-bearing.** `redact::scrub` is applied to the full frame and only then cut to 256 chars, with the comment stating why a boundary cut must not leave a partial secret; the deliberate non-redaction of partial and case-shifted near-misses is pinned by shared vectors both languages consume.
- **No shell-hygiene regressions in the build path.** `desktop-conformance` remains one command per recipe line (no `;` chaining, so exit codes propagate), no `sudo`, no destructive defaults, and the m6 changes required no Makefile edit at all.

Severity counts: C0 H3 M2 L1

## Recommended rectification order

H1, H2, H3, M1, M2, L1

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed: <finding ids>
- Deferred: <finding ids>
- Invalidated: <finding ids with reasons>
- Regression tests added: <file paths>
