# Critique — desktop-distribution-m6 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** c0dcf98..822dab7
**Diff stats:** 16 files, 1279 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

The highest-value check available — the aggregate `fixtures.sha256` re-pin — is
correct, intentional, and verifies independently in both languages, and the
`org.arxmcp.test-fault` extension is genuinely invisible to the production child,
so the two axes that could have blocked the milestone are clean. The one HIGH is
that the `ignore-shutdown` arm builds a deliberately SIGTERM-immune process and
nothing anywhere SIGKILLs it if the suite times out or is interrupted, so a bad
run strands an immortal listener on the developer's machine — the exact residue
the milestone exists to disprove. Everything else is calibration, coverage, and
two claims that read stronger than what was measured.

## Executive summary

- [HIGH] The `ignore-shutdown` fixture arm ignores stdin EOF, shutdown frames and SIGTERM; the test's `finally` kills only the supervisor, so a timeout or Ctrl-C strands a permanently-unkillable-by-TERM child holding a loopback port.
- [MEDIUM] The fault tests wait 90 s on a supervisor whose own internal budget is up to ~198 s (health 60 + ready 120 + smoke 15 + ladder), so timing out under load is reachable without any bug — and timing out is precisely what triggers the HIGH.
- [MEDIUM] The 30-cycle stress and socket-loopback tests are unmarked, so they run in the default `make test`; `_probe_command` raises rather than skips when `lsof` is absent, reintroducing the issue-#206 "fresh box hard-fails `make test`" class.
- [MEDIUM] `test_shutdown_grace_ms` / `test_bound_timeout_ms` / `test_fault` are ungated fields of the production `Plan`; a plan setting the grace knob makes the wire frame promise 35 s while the supervisor waits 400 ms.
- [MEDIUM] `redact.rs`'s module doc claims "two independent implementations that can drift"; the Python half is a one-line `str.replace` inside the assertion, so AC2's "same standard as the Python `RedactionFilter`" is met by redefinition, not by parity.
- [MEDIUM] `redact::scrub` is applied at exactly one call site rather than at the `Recorder` persistence boundary, so the next diagnostic that persists child bytes has to remember on its own.
- [MEDIUM] The spike's `wildcard-v4` / `wildcard-v6` arms were dropped from the ported matrix with no recorded non-claim; nothing tests a child that binds a wildcard while announcing loopback.
- [MEDIUM] `contract-fixtures/` gained a non-frame `.jsonl` inside the wire-contract aggregate digest and has no inventory guard, so a future fixture can land with zero consumer coverage and only a digest bump as evidence.

## Findings

**H1 — ignore-shutdown arm can strand a SIGTERM-immune child** (HIGH)

**Where:** `tests/test_desktop_child.py:1062`
**Anchor:** `def test_fault_ignored_shutdown_force_es`
**What:** The `ignore-shutdown` fixture arm installs `SIG_IGN` for SIGTERM (`apps/desktop/crates/fixture-sidecar/src/main.rs:188`) and ignores both `LeaseEvent::Eof` and `TryRecvError::Disconnected` (`:332`), so only SIGKILL ends it — but this test's `finally` at line 1079 calls `_stop_process(process)` on the SUPERVISOR only, and no fixture, conftest hook, or atexit handler reaps the child.
**Why it matters:** Any path that leaves the supervisor without reaching its KILL rung — the 90 s `process.wait` raising `TimeoutExpired`, an assertion firing earlier in the `try`, or a Ctrl-C during `make desktop-conformance` — strands a process that spins a 5 ms accept loop on a live loopback port forever, which is exactly the "bounded cleanup leaves no process and no listener" claim the milestone exists to establish.
**Proposed fix:** In the `finally` of every fault test (or in a shared helper wrapping `_spawn_fault_supervisor`), after `_stop_process(process)` iterate `_events_by_name(root, "child-spawn")` and `os.kill(pid, signal.SIGKILL)` under `contextlib.suppress(ProcessLookupError, PermissionError)`. Defense in depth: give the `IgnoreShutdown` arm a hard self-destruct (`abort()` after ~60 s from launch) so the immortality is bounded even outside the harness.
**Regression-guard:** A test that spawns the `ignore-shutdown` arm, kills the supervisor without letting the ladder run, then asserts `_pid_is_gone(child_pid)` inside 5 s — it must fail against the current `finally`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first + Docker constraint (no residue on the workstation)

**M1 — 90s fault-test wait is shorter than the supervisor's own budget** (MEDIUM)

**Where:** `tests/test_desktop_child.py:1077`
**Anchor:** `assert process.wait(timeout=90) == 1`
**What:** Four fault tests bound the supervisor at 90 s, but the supervisor's own worst case on the same path is `HEALTH_DEADLINE` 60 s + `READY_DEADLINE` 120 s + `SMOKE_TIMEOUT` 15 s + grace/force/reap — roughly 198 s (`apps/desktop/crates/supervisor/src/lifecycle.rs:37-46`), and only the grace/force rungs were shrunk by the test knobs.
**Why it matters:** On a loaded box (CLAUDE.md §3 records two or three concurrent agent sessions on this machine) a slow child start makes the test time out even though behavior is correct — a flake, and in the `ignore-shutdown` arm the flake is also the trigger for H1's stranded process.
**Proposed fix:** Either shrink the supervisor-side deadlines with the same test-only-knob mechanism already used for grace/force/bound, or raise the test wait above the supervisor's own ceiling and assert the *ladder* duration instead of wall time — the NDJSON events already carry `elapsed_ms`, so `orphan-shutdown.elapsed_ms - child-ready.elapsed_ms < 5000` measures what line 1082's `wall < 30.0` is trying to measure without folding in startup load.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M2 — Stress and loopback tests run unmarked in the default `make test`** (MEDIUM)

**Where:** `tests/test_desktop_contract.py:687`
**Anchor:** `def test_thirty_cycles_distinct_pids_no_o`
**What:** This test and `test_live_listener_is_loopback_only_at_socket_level` (`:763`) carry no `requires_desktop_stack` marker, so on any box with a built `fixture-sidecar` at the default path they run on every `make test` — 30 real process spawns plus ~60 `ps`/`lsof` subprocesses — and `_probe_command` (`:191`) *raises* `RuntimeError` rather than skipping when `lsof` is absent.
**Why it matters:** CLAUDE.md §4.5 records issue #206 closing exactly this class ("a fresh clone with no LaTeXML hard-failed its first `make test`"); `lsof` is not installed by default on most Linux distros, so a Linux developer who has built the Rust binaries now hard-fails the default suite on a tool the default suite has no business needing.
**Proposed fix:** Add `@pytest.mark.requires_desktop_stack` to both tests **and**, in the same change, append `-m "requires_desktop_stack or not requires_desktop_stack"` to the `tests/test_desktop_contract.py` line of the `desktop-conformance` recipe (`Makefile`), mirroring the `test_desktop_child.py` line — otherwise the conftest opt-in hook deselects them and AC3/AC5 lose their evidence.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M3 — Test-only shutdown knobs are ungated in the production plan schema** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:57`
**Anchor:** `    pub test_shutdown_grace_ms: Option<u64`
**What:** `test_shutdown_grace_ms`, `test_shutdown_force_after_ms`, `test_bound_timeout_ms` and `test_fault` are ordinary `Plan` fields with no `cfg`, env, or `smoke`-mode gate; `lifecycle.rs:190` honors the grace knob unconditionally while the wire frame it just sent still declares `grace_ms: MIN_GRACE_MS`.
**Why it matters:** The child derives its own drain deadline from the frame's `grace_ms` (README m5 section), so a plan carrying `test_shutdown_grace_ms: 400` makes the supervisor force-kill a real server that believes it has 17.5 s to close its LanceDB and Kùzu handles — the wire frame becomes a promise the supervisor does not keep, with no code path preventing it.
**Proposed fix:** Honor all four knobs only when `plan.smoke` is true (every fault test already sets `"smoke": True`), and `fail()` at `load_plan` if any knob is present with `smoke: false`. Alternatively clamp `grace_ms` to `MIN_GRACE_MS` unless `cfg!(debug_assertions)`.
**Regression-guard:** Optional — a `Plan` unit test asserting a non-smoke plan carrying `test_shutdown_grace_ms` is rejected.
**Source critic:** milestone-arxmcp-critic
**Source axis:** MCP/wire contract compatibility

**M4 — "Two independent implementations" overclaims the redaction parity** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/redact.rs:8`
**Anchor:** `//! two independent implementations that`
**What:** There is only one implementation: `scrub` in Rust. The Python side (`tests/test_desktop_contract.py:652`) computes `vector["input"].replace(vector["secret"], "[REDACTED]")` inside the assertion, so it can never disagree with the vector file's `expected` for a reason other than a bad vector, and the Python `RedactionFilter` AC2 names is a named-field dropper that is never invoked.
**Why it matters:** CLAUDE.md §4.9 rule 1 is exactly about not letting a record claim more trust than was measured; the docstring at `:657` is honest about the mechanism mismatch, but the module doc and AC2's "redacts to the same standard as the Python `RedactionFilter`" are not, and a future reader will believe cross-language parity is guarded when it is not.
**Proposed fix:** Reword `redact.rs:5-8` to what is true — "behavior is pinned by a shared vector file so an intentional change must be re-approved in both the Rust implementation and the Python reference semantic" — and record in the m6 completion notes that AC2's `RedactionFilter` clause was satisfied by an equivalent-standard argument, not by parity, since Python has no substring scrubber to compare against.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** cache byte-stability / contract-fixture discipline

**M5 — Scrub runs at one call site, not at the persistence boundary** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/lifecycle.rs:268`
**Anchor:** `            let _ = recorder.record("bound-`
**What:** `redact::scrub` has exactly one production caller — this `bound-frame-invalid` arm. `Recorder::record` (`apps/desktop/crates/supervisor/src/events.rs:38`) serializes and writes whatever `fields` it is handed with no scrub of its own.
**Why it matters:** The audit is complete today (the only other child-derived persist, `unexpected-stdout`, records a byte count), but the invariant "scrub before persist" is enforced by author discipline rather than by the writer, so the next diagnostic that persists a child-derived string reopens the capability-leak path with no test to catch it — and AC2 describes the *writer* as the thing that redacts.
**Proposed fix:** Give `Recorder` the `StartupToken` (or a scrub closure) at construction and scrub the serialized line inside `record` immediately before `write_all`, keeping the call-site scrub as belt-and-braces. That makes the guarantee structural and costs ~10 LOC.
**Regression-guard:** Optional — a Rust unit test that hands `Recorder::record` a field containing the token and asserts the written line contains `[REDACTED]`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security threat-model coverage

**M6 — Wildcard-bind fault arms dropped with no recorded non-claim** (MEDIUM)

**Where:** `apps/desktop/crates/fixture-sidecar/src/main.rs:41`
**Anchor:** `    /// Ignore stdin EOF, shutdown frames`
**What:** The spike's `Fault` set (`tools/desktop_lifecycle_spike/src/lib.rs:14-24`) has nine arms including `WildcardV4` and `WildcardV6`; the ported enum has seven and silently omits both, and the README's "Two spike-3 non-claims REMAIN non-claims" section records only the dead-parent and process-group narrowings.
**Why it matters:** `wildcard-bound.jsonl` proves a frame cannot *announce* a wildcard and `_assert_loopback_only` proves the kernel state of a well-behaved child, but nothing exercises a child that binds `0.0.0.0` while announcing `127.0.0.1` — the supervisor performs no runtime check of the actual bind, so AC5's socket-level claim has no negative case and a reader comparing the matrix to the spike sees an unexplained gap.
**Proposed fix:** Either add a `wildcard-v4` arm (bind `Ipv4Addr::UNSPECIFIED`, still announce `127.0.0.1`) plus a test asserting `_assert_loopback_only` *fails* on it, or record the omission alongside the other two non-claims in `apps/desktop/README.md` with the reason (the supervisor has no runtime bind probe, so the arm would document a gap rather than close one).
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M7 — contract-fixtures has no inventory guard for its aggregate digest** (MEDIUM)

**Where:** `apps/desktop/contract-fixtures/fixtures.sha256:1`
**Anchor:** `69eae0627027c9214636435f378099e126de38e`
**What:** The re-pin is correct — recomputed independently as `69eae062…d7835` over the 13 `.jsonl` files in lexicographic order with the `name`+NUL+bytes encoding, matching both language gates — but the digest now covers a file that is not a wire frame, and no test asserts that every `.jsonl` in the directory is claimed by `POSITIVE_FIXTURES`, `NEGATIVE_FIXTURES`, `incompatible-major.jsonl`, or the redaction consumer.
**Why it matters:** The aggregate digest is the only thing that notices a new file there, and a digest bump is indistinguishable from an intentional one — so a future frame fixture can land with zero parse coverage, and a redaction-vector edit now invalidates the wire-contract pin (and vice versa), coupling two contracts that change for different reasons.
**Proposed fix:** Add an inventory test in both languages asserting `set(dir.glob("*.jsonl")) == POSITIVE ∪ NEGATIVE ∪ {"incompatible-major.jsonl", "redaction-vectors.jsonl"}`, so adding a fixture forces a conscious consumer decision rather than only a digest bump. Optionally split `redaction-vectors.jsonl` into its own pin.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** cache byte-stability / contract-fixture discipline

**M8 — AC3's "zero orphan process groups" has no pgid probe** (MEDIUM)

**Where:** `tests/test_desktop_contract.py:205`
**Anchor:** `def _pid_is_gone(pid: int) -> bool:`
**What:** The stress audit proves 30 distinct PIDs, 30 `ps -p` absences and 30 empty `lsof` results, but never inspects a process group; the milestone AC's "zero orphan process groups" clause is answered only by the README's "process-group escape is not applicable, not handled".
**Why it matters:** The narrowing is honest and correct today (neither the fixture nor the production child spawns descendants), but it is argued in prose rather than probed, so the day a child does spawn a helper the suite reports clean absence for a group it never looked at — and the AC will still read as satisfied.
**Proposed fix:** Add `_pgid_is_empty(pgid)` using `ps -o pid= -g <pgid>` through `_probe_command`, capture the child's pgid from `ps -o pgid= -p <pid>` while it is alive, and assert the group is empty after each cycle. ~10 LOC, and it turns the non-claim into a measured one.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing (m4 umbrella acceptance criteria)

**L1 — Redundant Arc handle for the captured exit code** (LOW)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:244`
**Anchor:** `    let requested_exit: Arc<Mutex<i32>> = `
**What:** `requested_exit` is created only to be cloned into `exit_code_slot` on the next line and is never read afterwards, leaving a second strong reference alive for the rest of `main`.
**Why it matters:** Pure noise in the one function a reader opens to understand the tauri 2.11 exit-code workaround.
**Proposed fix:** `let exit_code_slot: Arc<Mutex<i32>> = Arc::new(Mutex::new(0));` and drop the extra binding.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** open scan (dead code)

**L2 — park_on_lease retries read errors with no bound and no sleep** (LOW)

**Where:** `apps/desktop/crates/fixture-sidecar/src/main.rs:182`
**Anchor:** `            Err(_) => {}`
**What:** A `read_frame` error re-enters the loop immediately; only `Ok(None)` (EOF) exits. A persistent `ContractError::Io` therefore spins a core with no backoff and no exit path.
**Why it matters:** The realistic case is EOF, so this is latent — but it is the one arm of the fault matrix whose failure mode is "burn CPU forever" rather than "exit", which is the opposite of what the milestone claims about bounded cleanup.
**Proposed fix:** Return `Err(SidecarError::Io)` on a read error, or at minimum `std::thread::sleep(POLL_INTERVAL)` before continuing.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** open scan (silently swallowed errors)

**L3 — Probe binary fallback path is macOS-shaped** (LOW)

**Where:** `tests/test_desktop_contract.py:191`
**Anchor:** `    binary = shutil.which(argv[0]) or f"/u`
**What:** The fallback when `shutil.which` misses is `/usr/sbin/<tool>`, which is where macOS keeps `lsof`; most Linux distros install it at `/usr/bin/lsof` (and `ps` at `/bin/ps`).
**Why it matters:** On a Linux box with a trimmed `PATH` the fallback never resolves and the probe raises "unavailable" even though the tool is installed — an evidence failure attributed to the wrong cause.
**Proposed fix:** Try a small candidate list (`/usr/sbin/`, `/usr/bin/`, `/bin/`) before giving up.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first + Docker constraint

**L4 — Redaction-vector floor of 7 is below the 9 shipped vectors** (LOW)

**Where:** `apps/desktop/crates/supervisor/src/redact.rs:43`
**Anchor:** `        assert!(count >= 7, "redaction vect`
**What:** Both the Rust guard here and the Python guard at `tests/test_desktop_contract.py:670` assert `>= 7` against a file that ships 9 vectors, so two can be deleted without either gate noticing.
**Why it matters:** The named-case assertions below (partial match, uppercase near-miss) cover two of the nine; the other seven are protected only by this floor and the aggregate digest, and a digest bump is exactly what a vector edit already requires.
**Proposed fix:** Pin the exact count (`== 9`) so a deletion is a deliberate two-language edit, matching the discipline `fixtures.sha256` already imposes.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

## What was done well

- The aggregate `fixtures.sha256` re-pin is genuinely correct: recomputed from scratch it reproduces `69eae062…d7835` byte-for-byte, the Rust and Python digest tests use the same lexicographic `name`+NUL+bytes encoding, and both are in the gate — the single highest-risk item in this diff is clean.
- The fault switch rides `org.arxmcp.test-fault`, which satisfies `valid_extension_key`'s namespacing rule as a direct child of `extensions`, and `server/desktop_child.py` never reads `launch.extensions` at all (its only mention is `extensions={}` when constructing its own `bound`), so the compatible-addition argument holds and no contract bump is owed.
- In production `plan.test_fault` is `None`, so the launch frame still encodes `"extensions":{}` — the emitted wire bytes are unchanged, which is what keeps the m3 byte-stability discipline intact rather than merely claimed.
- The malformed-bound arm is the right shape for a redaction test: the fixture deliberately embeds the real capability in the invalid frame, so the persisted diagnostic proves scrub-before-persist against a live secret instead of a synthetic one, and `scrub` correctly runs before the 256-char truncation so a boundary cut cannot bisect the token.
- `_sweep_fault_artifacts` is structural rather than value-based — the test cannot know the supervisor-generated token, so it allowlists the one legitimate 64-hex string (the fixture's own digest) and rejects every other. That is the strictly stronger form of the check.
- `_probe_command` treats a missing binary, a timeout, or an undocumented exit code as an evidence failure instead of clean absence, and `_assert_loopback_only` self-checks that `lsof` actually *found* the listener before trusting its columns — both are the discipline that makes a negative result mean something.
- The fault-injection arms are a reimplementation, not a lift: the ported `Fault` enum drops serde, drops two variants, renames `Normal`→`None`, and is selected through the wire extension rather than the spike's `FromStr` CLI path. Arm *names* are shared, which is the intended use of the repo's own spike as design precedent.
- The README's "Two spike-3 non-claims REMAIN non-claims" section is exactly the right register — it states what a passing matrix does *not* prove (a dead parent cannot kill a wedged child; process-group escape is not-applicable rather than handled) instead of letting a green suite imply universal cleanup.
- The tauri 2.11 exit-code fix is a real production bug found by the fault matrix rather than by reasoning, it is documented at the site with how it was measured, and `Recorder::record` flushes per line so the added `std::process::exit` cannot lose events.
- Test knobs were kept off the wire deliberately and the reason is written down at both sites (`main.rs:50-53`, `lifecycle.rs:187-189`) — the mechanism needs gating (M3), but the intent and its risk were reasoned about openly rather than glossed.

Severity counts: C0 H1 M8 L4

## Recommended rectification order

H1, M3, M1, M2, M5, M4, M8, M6, M7, L2, L4, L1, L3

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
