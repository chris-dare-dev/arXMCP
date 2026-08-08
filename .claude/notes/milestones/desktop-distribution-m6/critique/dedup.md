# Critique (merged) — desktop-distribution-m6

**Critics:** milestone-adversary-critic, milestone-arxmcp-critic, milestone-infra-safety-critic
**Commit range:** c0dcf98..822dab7
**Diff stats:** 16 files, 1279 LOC (+1240 / -39; ex-`.claude/` +977 / -37)
**Critique format version:** 1.0

> **Merge note.** Each critic authored its ids from 1 within its own file, so
> they collided across files. `findings.py merge` renumbered them into one
> gapless per-severity sequence in critic dispatch order; bodies are verbatim.
> **Phase 4 dispositions attach to the MERGED ids below**, not to the ids in
> the per-critic files. Re-running merge after a critic file changes will shift
> these ids - see milestone-pipeline-critique-format.md.
>
> - `milestone-adversary-critic` (adversary.md): ids unchanged
> - `milestone-arxmcp-critic` (arxmcp.md): H1->H3, M1->M4, M2->M5, M3->M6, M4->M7, M5->M8, M6->M9, M7->M10, M8->M11, L1->L2, L2->L3, L3->L4, L4->L5
> - `milestone-infra-safety-critic` (infra-safety.md): H1->H4, H2->H5, H3->H6, M1->M12, M2->M13, L1->L6

## Verdict

**SHIP-WITH-FIXES** — the most severe of the per-critic verdicts below.

### milestone-adversary-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES. The fault matrix genuinely drives the real supervisor — the
per-arm exit codes (`0` cooperative vs `-1` force-killed) discriminate supervisor
behavior from fixture cooperation, and the tauri 2.11 exit-code bug is a real
production find with coverage in both directions. Two defects are load-bearing:
the README's newly-authored process-group non-claim is factually false against
shipped code (the production child spawns descendants, some via
`start_new_session=True`), and two evidence mechanisms — `lsof` error-vs-absence
and the zero-skip gate on the contract-suite half of `make desktop-conformance` —
can each report success while the AC3/AC5 evidence is absent. None of these
require redesign; all four fixes are small and local.

### milestone-arxmcp-critic — SHIP-WITH-FIXES

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

### milestone-infra-safety-critic — SHIP-WITH-FIXES

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

## Executive summary — milestone-adversary-critic

- [CRITICAL] `apps/desktop/README.md:139` states "neither the production child
  nor the fixture spawns descendants today, so a `setsid()`-style escape cannot
  occur." The production child hosts `IngestTaskTracker`
  (`asyncio.create_subprocess_exec(sys.executable, "-m", "tools.notebook_ingest", …)`)
  and `ParseTaskTracker`, whose helpers use `start_new_session=True` — literally
  `setsid()`. The scoped non-claim is inverted: the hazard is the shipped design.
- [HIGH] `_listener_lines` reads an `lsof` **error** as verified clean absence.
  Measured on this box: `lsof` exits 1 both for no-match and for hard errors
  (stderr carries the discriminator, stdout is empty in both). AC3 names exactly
  this: "a failed or partial `ps`/`lsof` probe is an evidence failure, never
  clean absence."
- [HIGH] `Makefile:157` runs `tests/test_desktop_contract.py` **without**
  `DESKTOP_SUPERVISOR_BIN`, so the m5-H3 zero-skip guard is inert for that
  session. The two headline m6 tests (AC3's 30-cycle stress, AC5's socket-level
  loopback) `pytest.skip` when the sidecar path misses, and
  `make desktop-conformance` still exits 0 — satisfying AC6 with AC3+AC5 gone.
- [MEDIUM] The Rust redaction is call-site discipline at one site, not a writer
  property, while `redact.rs:5` claims the scrub is "applied to every persisted
  string derived from raw child output". Nothing structurally binds a future
  `Recorder::record` to it.
- [MEDIUM] `pyproject.toml:374`'s `requires_desktop_stack` registration still
  says "desktop-distribution-m5" and describes only real-server boot; CLAUDE.md
  §4.5 was updated to m5/m6 + fault matrix. CLAUDE.md declares pyproject the
  derivation source, so the authoritative half is now the staler one.
- [MEDIUM] The `IgnoreShutdown` arm has no self-destruct: it ignores stdin EOF,
  shutdown frames, `Disconnected`, and SIGTERM with no wall-clock bound, so a
  failing or timing-out `test_fault_ignored_shutdown_force_escalates` leaks an
  unkillable orphan holding a loopback listener — in the no-orphans milestone.
- [LOW] `park_on_lease`'s `Err(_) => {}` arm has no backoff and no deadline.
- [NOTE] `state.json:36` carries `"allow_large_diff": true`, so the mandatory
  >400-LOC auto-finding is deliberately NOT filed. Arithmetic stated above so
  the omission is auditable. Commit hygiene, signing, trailers, and the
  one-writer rule were all checked and are clean.

## Executive summary — milestone-arxmcp-critic

- [HIGH] The `ignore-shutdown` fixture arm ignores stdin EOF, shutdown frames and SIGTERM; the test's `finally` kills only the supervisor, so a timeout or Ctrl-C strands a permanently-unkillable-by-TERM child holding a loopback port.
- [MEDIUM] The fault tests wait 90 s on a supervisor whose own internal budget is up to ~198 s (health 60 + ready 120 + smoke 15 + ladder), so timing out under load is reachable without any bug — and timing out is precisely what triggers the HIGH.
- [MEDIUM] The 30-cycle stress and socket-loopback tests are unmarked, so they run in the default `make test`; `_probe_command` raises rather than skips when `lsof` is absent, reintroducing the issue-#206 "fresh box hard-fails `make test`" class.
- [MEDIUM] `test_shutdown_grace_ms` / `test_bound_timeout_ms` / `test_fault` are ungated fields of the production `Plan`; a plan setting the grace knob makes the wire frame promise 35 s while the supervisor waits 400 ms.
- [MEDIUM] `redact.rs`'s module doc claims "two independent implementations that can drift"; the Python half is a one-line `str.replace` inside the assertion, so AC2's "same standard as the Python `RedactionFilter`" is met by redefinition, not by parity.
- [MEDIUM] `redact::scrub` is applied at exactly one call site rather than at the `Recorder` persistence boundary, so the next diagnostic that persists child bytes has to remember on its own.
- [MEDIUM] The spike's `wildcard-v4` / `wildcard-v6` arms were dropped from the ported matrix with no recorded non-claim; nothing tests a child that binds a wildcard while announcing loopback.
- [MEDIUM] `contract-fixtures/` gained a non-frame `.jsonl` inside the wire-contract aggregate digest and has no inventory guard, so a future fixture can land with zero consumer coverage and only a digest bump as evidence.

## Executive summary — milestone-infra-safety-critic

- [HIGH] `_probe_command`'s "found(0)/not-found(1)" discriminator is factually wrong for both tools — `lsof` and `ps` return 1 on genuine errors too (measured on this box), so a broken probe reads as verified absence, which is precisely what AC3 forbids.
- [HIGH] The zero-skip gate guard keys on `DESKTOP_SUPERVISOR_BIN` only, so the `make desktop-conformance` invocation that runs AC3's 30-cycle orphan audit and AC5's fixture loopback proof has no skip guard; both can vanish and the gate still exits 0.
- [HIGH] Nothing in the m6 fault matrix reaps the fixture-sidecar grandchild on the exception path; the `ignore-shutdown` arm ignores SIGTERM, stdin EOF and channel disconnect, so a timed-out run leaves a 5 ms-polling orphan holding a loopback listener.
- [MEDIUM] `assert wall < 30.0` in the escalation-ladder test measures tauri boot plus spawn, not the ladder, and contradicts the same test's own 90 s wait budget — the m3 "200 ms → 2 s under load" flake shape.
- [MEDIUM] `pyproject.toml`'s `requires_desktop_stack` description still says m5-only and never names the new hard `ps`/`lsof` prerequisite that `make test` can now reach.
- [LOW] `park_on_lease`'s `Err(_) => {}` arm has no backoff and no exit condition, so a persistent stdin I/O error spins the parked fixture at 100% CPU forever.
- [CLEAN] Cargo pinning, `Cargo.lock` consistency, `--locked` offline behavior, the `cfg(unix)` scoping of `libc`, and the `fixtures.sha256` update are all verified correct.
- [CLEAN] The tauri workaround is version-pinned (`tauri = "=2.11.5"`) and skips no durable cleanup — verified against tauri 2.11.5 `app.rs:1430-1437` and the plugin's `on_event` hook.

## Findings

**C1 — README's setsid non-claim is false: the child spawns descendants** (CRITICAL)

**Where:** `apps/desktop/README.md:139`
**Anchor:** `- **Process-group escape is not applicab`
**What:** The newly-authored non-claim asserts "neither the production child nor the fixture spawns descendants today, so a `setsid()`-style escape cannot occur", but the production child (`server/desktop_child.py:371` → `create_app`) installs `app.state.ingest_tracker` (`server/main.py:619`) whose `server/ingest_tracker.py:244` runs `asyncio.create_subprocess_exec(sys.executable, "-m", "tools.notebook_ingest", slug, …)` from the `/ui/` console ingest action the supervisor navigates the window to (`server/routes/notebooks.py:2309`), and `app.state.parse_tracker` (`server/main.py:626`) whose helpers spawn with `start_new_session=True` (`ingest/textbook_parser.py:459`; `tools/arxiv_fetch.py:703-704` states this is "equivalent to `os.setsid()` after fork").
**Why it matters:** The bullet is the milestone's stated cleanup boundary, and it is inverted in the unsafe direction — a `setsid()` escape is the shipped sandbox design, not a hypothetical. The live residual: on the supervisor's forced path (grace → TERM → KILL, the exact path the ignore-shutdown arm exists to exercise) the child dies without running the FastAPI lifespan, so `ingest_tracker.shutdown()` (`server/main.py:651`) never fires and the `tools.notebook_ingest` grandchild is reparented to init still holding the notebook's LanceDB staging directory — while a reader of this README concludes the case cannot arise.
**Proposed fix:** Rewrite the second bullet to say what is true: the supervisor signals only the direct child PID, never a process group; the *fixture* spawns no descendants, so the matrix proves nothing about descendants; and the *production* child already does spawn them (name `ingest_tracker`, `parse_tracker`, and the `start_new_session=True` LaTeXML/MinerU helpers), so a forced kill of the child orphans them today. State the mitigation that exists — the cooperative path runs `ingest_tracker.shutdown()`'s SIGTERM→2s→SIGKILL — and record descendant cleanup on the forced path as an open item for a named future milestone rather than as an inapplicable case.
**Regression-guard:** A source-derived test in the repo's existing style (`tests/test_assert_ban.py`, `tests/test_wheel_packaging.py`): assert that if `grep -rE "create_subprocess_exec|subprocess\.(Popen|run)" server/ ingest/` is non-empty, `apps/desktop/README.md` must NOT contain the string "spawns descendants today" — so the doc cannot re-assert descendant-freedom while the tree contradicts it.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**H1 — `lsof` error is read as verified clean absence, violating AC3** (HIGH)

**Where:** `tests/test_desktop_contract.py:200`
**Anchor:** `if completed.returncode not in (0, 1):`
**What:** `_probe_command`'s docstring claims "an exit code other than the tool's documented found(0)/not-found(1) pair raises", but `lsof` does not have such a pair — it returns 1 for **any** error as well as for no-match, so `_listener_lines` (`:210`) returns `[]` on a failed probe and every `assert _listener_lines(port) == []` reads as verified absence.
**Why it matters:** AC3 names this exact requirement — "a failed or partial `ps`/`lsof` probe is an evidence failure, never clean absence" — so the AC is unmet by its own load-bearing helper. Measured on this box: `lsof -nP -iTCP:notaport -sTCP:LISTEN` → rc=1, stdout empty, stderr `lsof: unknown service notaport…`; `lsof … /nonexistent/path` → rc=1, stdout empty, stderr `status error`. Four tests then assert listener absence with no positive control in the same test that `lsof` can find anything at all — `test_thirty_cycles_distinct_pids_no_orphans_no_listeners` (all 30 cycles), `test_fault_crash_after_ready_bounded_cleanup`, `test_fault_ignored_shutdown_force_escalates`, `test_fault_supervisor_sigkill_cooperating_child_self_cleans` — so a systematically broken `lsof` passes the whole AC3 audit silently.
**Proposed fix:** In `_probe_command`, treat exit-1-with-diagnostics as an error: `if completed.returncode == 1 and completed.stderr.strip(): raise RuntimeError(f"probe failed (exit 1 with diagnostics, not a clean no-match): {completed.stderr!r}")` (allowlist any platform-benign warning explicitly rather than blanket-ignoring stderr). Additionally give the four absence-only tests a positive control: capture `_listener_lines(port)` once while the listener is provably live (the 30-cycle test already does an HTTP round trip at that moment) and assert it is non-empty before asserting `== []` after teardown, mirroring `_assert_loopback_only`'s existing `assert lines, "…probe/server failure"`.
**Regression-guard:** A unit test that monkeypatches `subprocess.run` to return `CompletedProcess(returncode=1, stdout=b"", stderr=b"lsof: unknown service…")` and asserts `_probe_command` raises rather than returning; plus asserting `_listener_lines` propagates that raise instead of returning `[]`.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**H2 — Contract-suite conformance line is not zero-skip gated** (HIGH)

**Where:** `Makefile:157`
**Anchor:** `ARXMCP_FIXTURE_SIDECAR="$(CURDIR)/apps/d`
**What:** The m5-H3 zero-skip guard in `tests/conftest.py:59-62` fires only when `DESKTOP_SUPERVISOR_BIN` is set, and line 157 exports only `ARXMCP_FIXTURE_SIDECAR` (there is no `export` directive in the Makefile, and each recipe line is its own shell), so the entire `tests/test_desktop_contract.py` run is unguarded — including the two new m6 tests, which both begin `if binary is None: pytest.skip(...)`.
**Why it matters:** AC3's 30-cycle stress and AC5's socket-level loopback proof are the milestone's two headline evidence artifacts, and both sit on the unguarded line. A realistic trigger exists: `_sidecar_binary()` resolves and `is_file()`-checks the exact path the Makefile hard-codes, so an ambient `CARGO_TARGET_DIR` (a standard cargo env var) sends `cargo build` elsewhere, the hard-coded `$(CURDIR)/apps/desktop/target/debug/fixture-sidecar` does not exist, both tests skip, and `make desktop-conformance` still exits 0 — satisfying AC6 with AC3 and AC5 silently absent. The conftest comment already names this failure mode ("the real-stack tests just skip and the session still exits 0"); m6 reproduced it on the other line.
**Proposed fix:** Export a gate marker on line 157 too — either add `DESKTOP_SUPERVISOR_BIN="…/supervisor$(DESKTOP_EXE_SUFFIX)"` to that line, or widen `tests/conftest.py`'s `_DESKTOP_GATE_ENV` into a tuple `("DESKTOP_SUPERVISOR_BIN", "ARXMCP_FIXTURE_SIDECAR")` and arm the guard when any is set. Independently, convert the two m6 tests' `pytest.skip` to `pytest.fail` when a gate env var is present, matching `_supervisor_binary()`/`_fixture_binary()`'s existing fail-loud behavior in `test_desktop_child.py`.
**Regression-guard:** Extend the existing Makefile-derived test family (`test_desktop_conformance_marker_token_is_a_registered_opt_in_marker`, `tests/test_desktop_contract.py:422`) with a check that EVERY `pytest` line in the `desktop-conformance` recipe is prefixed by at least one env var the conftest gate recognizes.
**Source critic:** milestone-adversary-critic
**Source axis:** Repo-gate compliance

**H3 — ignore-shutdown arm can strand a SIGTERM-immune child** (HIGH)

**Where:** `tests/test_desktop_child.py:1062`
**Anchor:** `def test_fault_ignored_shutdown_force_es`
**What:** The `ignore-shutdown` fixture arm installs `SIG_IGN` for SIGTERM (`apps/desktop/crates/fixture-sidecar/src/main.rs:188`) and ignores both `LeaseEvent::Eof` and `TryRecvError::Disconnected` (`:332`), so only SIGKILL ends it — but this test's `finally` at line 1079 calls `_stop_process(process)` on the SUPERVISOR only, and no fixture, conftest hook, or atexit handler reaps the child.
**Why it matters:** Any path that leaves the supervisor without reaching its KILL rung — the 90 s `process.wait` raising `TimeoutExpired`, an assertion firing earlier in the `try`, or a Ctrl-C during `make desktop-conformance` — strands a process that spins a 5 ms accept loop on a live loopback port forever, which is exactly the "bounded cleanup leaves no process and no listener" claim the milestone exists to establish.
**Proposed fix:** In the `finally` of every fault test (or in a shared helper wrapping `_spawn_fault_supervisor`), after `_stop_process(process)` iterate `_events_by_name(root, "child-spawn")` and `os.kill(pid, signal.SIGKILL)` under `contextlib.suppress(ProcessLookupError, PermissionError)`. Defense in depth: give the `IgnoreShutdown` arm a hard self-destruct (`abort()` after ~60 s from launch) so the immortality is bounded even outside the harness.
**Regression-guard:** A test that spawns the `ignore-shutdown` arm, kills the supervisor without letting the ladder run, then asserts `_pid_is_gone(child_pid)` inside 5 s — it must fail against the current `finally`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first + Docker constraint (no residue on the workstation)

**H4 — ps/lsof exit-code discriminator cannot detect a failed probe** (HIGH)

**Where:** `tests/test_desktop_contract.py:200`
**Anchor:** `    if completed.returncode not in (0, 1):`
**What:** The helper's docstring claims it raises on "an exit code other than the tool's documented found(0)/not-found(1) pair", but neither tool has such a pair — measured on this box, `lsof -nP --bogus` exits 1, `lsof -nP -iTCP:99999999` exits 1, and `ps -p notanumber` exits 1, exactly as a clean no-match does.
**Why it matters:** AC3 requires that "a failed or partial `ps`/`lsof` probe is an evidence failure, never clean absence", and this is the sole mechanism enforcing it — a `ps` restricted by `hidepid`, an `lsof` denied kernel access, or any malformed argument makes `_listener_lines` return `[]` and `_pid_is_gone` return `True`, so every orphan and residual-listener assertion in the 30-cycle audit and all six fault tests passes vacuously.
**Proposed fix:** Replace the PID probe with `os.kill(pid, 0)` — `ProcessLookupError` is unambiguous "gone", `PermissionError` is unambiguous "alive", and there is no subprocess to misreport. For `lsof`, make every absence probe carry its own positive control: query the dead port together with a port the test holds open (`-iTCP:<dead>,<control>`) and require the control row to appear, so an exit-1 with no control row is an error rather than absence. Fix the docstring's exit-code claim in the same edit — a stale comment is a bug per the code-comment contract.
**Regression-guard:** A test that monkeypatches `_probe_command`'s resolved binary to a stub exiting 1 with empty stdout and asserts `_listener_lines` / `_pid_is_gone` RAISE rather than report absence.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**H5 — AC3 and AC5 evidence can silently skip out of the conformance gate** (HIGH)

**Where:** `tests/test_desktop_contract.py:697`
**Anchor:** `        pytest.skip("build fixture-sidecar or set ARXMCP_FIXTURE`
**What:** `test_thirty_cycles_distinct_pids_no_orphans_no_listeners` (AC3) and `test_live_listener_is_loopback_only_at_socket_level` (AC5) skip when `_sidecar_binary()` returns `None`, and `conftest.py:58`'s zero-skip guard fires only when `DESKTOP_SUPERVISOR_BIN` is set — which is true for `Makefile:158` but not for `Makefile:157`, the invocation that actually runs these two tests.
**Why it matters:** `_sidecar_binary()` returns `None` even when `ARXMCP_FIXTURE_SIDECAR` is explicitly set but the path is not a file (wrong `DESKTOP_EXE_SUFFIX`, an interrupted `cargo build`, a `--target` build landing elsewhere), so the milestone's two headline acceptance criteria can disappear from the gate that exists to prove them while `make desktop-conformance` still exits 0 — the exact silent-degradation shape m5's H3 guard was written to kill, left uncovered on the other half of the gate.
**Proposed fix:** Two cheap symmetric changes. In `_sidecar_binary`, when `ARXMCP_FIXTURE_SIDECAR` is explicitly set but is not a file, `pytest.fail` instead of returning `None` — mirroring `_supervisor_binary` and `_fixture_binary`, which m6 already wrote that way. Then widen `conftest.py`'s `_DESKTOP_GATE_ENV` to a tuple including `ARXMCP_FIXTURE_SIDECAR` so `Makefile:157`'s session is equally all-or-nothing.
**Regression-guard:** Run `ARXMCP_FIXTURE_SIDECAR=/nonexistent python -m pytest tests/test_desktop_contract.py` and assert a non-zero exit; today it exits 0 with skips.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**H6 — No teardown reaps the grandchild; ignore-shutdown arm is SIGTERM-immune** (HIGH)

**Where:** `tests/test_desktop_child.py:1079`
**Anchor:** `        _stop_process(process)`
**What:** Every fault test's `finally` calls `_stop_process` on the supervisor only; the fixture-sidecar grandchild is never recorded for cleanup, and under the `ignore-shutdown` arm it installs `SIG_IGN` on SIGTERM (`fixture-sidecar/src/main.rs:191`) *and* falls through on both `LeaseEvent::Eof` and `TryRecvError::Disconnected`, so nothing short of SIGKILL ends it.
**Why it matters:** When `process.wait(timeout=90)` expires — which is exactly what happens if the escalation ladder this test exists to verify is broken — `_stop_process` SIGTERMs then SIGKILLs the supervisor mid-ladder, and the sidecar survives as a permanent orphan polling `accept()` every 5 ms and holding a loopback listener, on a milestone whose whole subject is "leaving no process and no listener"; the developer gets no signal and `kill -9` is the only remedy.
**Proposed fix:** Capture `child_pid` from the `child-spawn` event as soon as it appears and reap it in the same `finally` with `os.kill(pid, signal.SIGKILL)` guarded by `ProcessLookupError` (SIGTERM is useless for the ignore-shutdown arm). Back that with a session-scoped autouse fixture in `tests/conftest.py` that SIGKILLs any surviving PID recorded by a fault test, so a `KeyboardInterrupt` or a harness SIGTERM to pytest cannot strand one either.
**Regression-guard:** A test that spawns the `ignore-shutdown` arm, SIGKILLs the supervisor before its ladder completes, and asserts the harness reaps the sidecar PID within a bounded wait.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M1 — Redaction is one call site, not the writer `redact.rs` claims** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/redact.rs:5`
**Anchor:** `//! standard" is this exact-match scrub `
**What:** The module doc says the scrub is "applied to every persisted string derived from raw child output", but `Recorder::record` (`events.rs:38`) performs no scrubbing and `redact::scrub` is invoked at exactly one site (`lifecycle.rs:266`); the largest raw-child-output sink under the data root — `logs/desktop-child.log`, the child's stderr fd wired at `lifecycle.rs:163` — is never touched by it (it is defended independently by the Python `RedactionFilter`).
**Why it matters:** AC2 asks the "Rust-side diagnostics writer" to redact; what shipped is call-site discipline with no enforcement, so the safety property holds today only because every other `record` call passes structural fields. A future diagnostic that persists a child-derived string is a one-line regression with no guard, and the doc as written tells the next author the coverage is already universal.
**Proposed fix:** Either (a) narrow the doc to what is true — name the single `bound-frame-invalid` call site, note that child stderr is the Python filter's responsibility, and state that any new child-derived string field MUST route through `scrub` — or (b) make it a writer property: hold the `StartupToken` in `Recorder` and scrub every string leaf of `fields` inside `record`, which also removes the ordering hazard entirely.
**Regression-guard:** A source-derived test (repo precedent: `tests/test_assert_ban.py`) asserting that every `recorder.record(` / `.record(` call in `apps/desktop/crates/supervisor/src/**.rs` whose `json!` body contains a non-literal `String`/`&str` expression also contains `redact::scrub`.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**M2 — pyproject marker text still m5-only while CLAUDE.md was updated** (MEDIUM)

**Where:** `pyproject.toml:374`
**Anchor:** `"requires_desktop_stack: desktop-distrib`
**What:** The diff amended CLAUDE.md §4.5 to "desktop-distribution-m5/m6 … including the m6 fault matrix that drives the real supervisor against fault-injected fixture-sidecar arms", but left the registration in `pyproject.toml` reading "desktop-distribution-m5 real-lifecycle tests that boot the ACTUAL server … and/or the built Tauri supervisor binary".
**Why it matters:** CLAUDE.md §4.5 states its inventory is *derived from* `pyproject.toml`, so the authoritative source is now the staler of the two, and `pytest --markers` — what an operator actually reads — never mentions the fault matrix. `tests/test_marker_doc_consistency.py` only compares the marker COUNT and checks each name appears in §4.5; it never compares description text, so this drift is unguarded in both directions.
**Proposed fix:** Amend the `requires_desktop_stack` registration string to match CLAUDE.md §4.5's wording (m5/m6, fault matrix, fixture-sidecar arms), noting that most m6 arms drive the fixture rather than the real server so the ~2.3 GB reranker prerequisite is conservative rather than universal.
**Regression-guard:** Add a case to `tests/test_marker_doc_consistency.py` asserting that for each registered marker, the milestone ids named in the pyproject registration are a superset of those named in the §4.5 bullet for the same marker.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**M3 — `IgnoreShutdown` arm has no self-destruct; a failing test leaks an orphan** (MEDIUM)

**Where:** `apps/desktop/crates/fixture-sidecar/src/main.rs:332`
**Anchor:** `Ok(LeaseEvent::Shutdown | LeaseEvent::Eo`
**What:** With `fault == IgnoreShutdown` the fixture ignores shutdown frames, stdin EOF, `TryRecvError::Disconnected`, and SIGTERM (`ignore_sigterm()` at `:145`) with no wall-clock bound; the only non-SIGKILL exit is a non-`WouldBlock` accept error at `:349`, which never fires in practice.
**Why it matters:** If `test_fault_ignored_shutdown_force_escalates` fails or times out before the supervisor completes its ladder, the `finally: _stop_process(process)` reaps only the SUPERVISOR — SIGTERM then SIGKILL after 2s — leaving the fixture permanently alive, reparented to init, holding an ephemeral loopback listener that nothing in the suite will ever reap. The milestone whose thesis is "zero orphan process groups, zero residual listeners" ships the one fixture arm that can create both, in the arm most likely to time out.
**Proposed fix:** Give the arm a hard deadline: capture `Instant::now()` when `ignore_sigterm()` installs, and in `serve_until_stopped`'s loop `std::process::abort()` once ~60s has elapsed under `Fault::IgnoreShutdown` — far beyond the shrunk 400ms/400ms ladder the test drives, so it cannot mask a real escalation failure, but bounded enough that a failed run self-cleans.
**Regression-guard:** Optional — a Rust unit test on the deadline constant, or a suite-level check that no `fixture-sidecar` process outlives the pytest session.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**M4 — 90s fault-test wait is shorter than the supervisor's own budget** (MEDIUM)

**Where:** `tests/test_desktop_child.py:1077`
**Anchor:** `assert process.wait(timeout=90) == 1`
**What:** Four fault tests bound the supervisor at 90 s, but the supervisor's own worst case on the same path is `HEALTH_DEADLINE` 60 s + `READY_DEADLINE` 120 s + `SMOKE_TIMEOUT` 15 s + grace/force/reap — roughly 198 s (`apps/desktop/crates/supervisor/src/lifecycle.rs:37-46`), and only the grace/force rungs were shrunk by the test knobs.
**Why it matters:** On a loaded box (CLAUDE.md §3 records two or three concurrent agent sessions on this machine) a slow child start makes the test time out even though behavior is correct — a flake, and in the `ignore-shutdown` arm the flake is also the trigger for H1's stranded process.
**Proposed fix:** Either shrink the supervisor-side deadlines with the same test-only-knob mechanism already used for grace/force/bound, or raise the test wait above the supervisor's own ceiling and assert the *ladder* duration instead of wall time — the NDJSON events already carry `elapsed_ms`, so `orphan-shutdown.elapsed_ms - child-ready.elapsed_ms < 5000` measures what line 1082's `wall < 30.0` is trying to measure without folding in startup load.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M5 — Stress and loopback tests run unmarked in the default `make test`** (MEDIUM)

**Where:** `tests/test_desktop_contract.py:687`
**Anchor:** `def test_thirty_cycles_distinct_pids_no_o`
**What:** This test and `test_live_listener_is_loopback_only_at_socket_level` (`:763`) carry no `requires_desktop_stack` marker, so on any box with a built `fixture-sidecar` at the default path they run on every `make test` — 30 real process spawns plus ~60 `ps`/`lsof` subprocesses — and `_probe_command` (`:191`) *raises* `RuntimeError` rather than skipping when `lsof` is absent.
**Why it matters:** CLAUDE.md §4.5 records issue #206 closing exactly this class ("a fresh clone with no LaTeXML hard-failed its first `make test`"); `lsof` is not installed by default on most Linux distros, so a Linux developer who has built the Rust binaries now hard-fails the default suite on a tool the default suite has no business needing.
**Proposed fix:** Add `@pytest.mark.requires_desktop_stack` to both tests **and**, in the same change, append `-m "requires_desktop_stack or not requires_desktop_stack"` to the `tests/test_desktop_contract.py` line of the `desktop-conformance` recipe (`Makefile`), mirroring the `test_desktop_child.py` line — otherwise the conftest opt-in hook deselects them and AC3/AC5 lose their evidence.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M6 — Test-only shutdown knobs are ungated in the production plan schema** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:57`
**Anchor:** `    pub test_shutdown_grace_ms: Option<u64`
**What:** `test_shutdown_grace_ms`, `test_shutdown_force_after_ms`, `test_bound_timeout_ms` and `test_fault` are ordinary `Plan` fields with no `cfg`, env, or `smoke`-mode gate; `lifecycle.rs:190` honors the grace knob unconditionally while the wire frame it just sent still declares `grace_ms: MIN_GRACE_MS`.
**Why it matters:** The child derives its own drain deadline from the frame's `grace_ms` (README m5 section), so a plan carrying `test_shutdown_grace_ms: 400` makes the supervisor force-kill a real server that believes it has 17.5 s to close its LanceDB and Kùzu handles — the wire frame becomes a promise the supervisor does not keep, with no code path preventing it.
**Proposed fix:** Honor all four knobs only when `plan.smoke` is true (every fault test already sets `"smoke": True`), and `fail()` at `load_plan` if any knob is present with `smoke: false`. Alternatively clamp `grace_ms` to `MIN_GRACE_MS` unless `cfg!(debug_assertions)`.
**Regression-guard:** Optional — a `Plan` unit test asserting a non-smoke plan carrying `test_shutdown_grace_ms` is rejected.
**Source critic:** milestone-arxmcp-critic
**Source axis:** MCP/wire contract compatibility

**M7 — "Two independent implementations" overclaims the redaction parity** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/redact.rs:8`
**Anchor:** `//! two independent implementations that`
**What:** There is only one implementation: `scrub` in Rust. The Python side (`tests/test_desktop_contract.py:652`) computes `vector["input"].replace(vector["secret"], "[REDACTED]")` inside the assertion, so it can never disagree with the vector file's `expected` for a reason other than a bad vector, and the Python `RedactionFilter` AC2 names is a named-field dropper that is never invoked.
**Why it matters:** CLAUDE.md §4.9 rule 1 is exactly about not letting a record claim more trust than was measured; the docstring at `:657` is honest about the mechanism mismatch, but the module doc and AC2's "redacts to the same standard as the Python `RedactionFilter`" are not, and a future reader will believe cross-language parity is guarded when it is not.
**Proposed fix:** Reword `redact.rs:5-8` to what is true — "behavior is pinned by a shared vector file so an intentional change must be re-approved in both the Rust implementation and the Python reference semantic" — and record in the m6 completion notes that AC2's `RedactionFilter` clause was satisfied by an equivalent-standard argument, not by parity, since Python has no substring scrubber to compare against.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** cache byte-stability / contract-fixture discipline

**M8 — Scrub runs at one call site, not at the persistence boundary** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/lifecycle.rs:268`
**Anchor:** `            let _ = recorder.record("bound-`
**What:** `redact::scrub` has exactly one production caller — this `bound-frame-invalid` arm. `Recorder::record` (`apps/desktop/crates/supervisor/src/events.rs:38`) serializes and writes whatever `fields` it is handed with no scrub of its own.
**Why it matters:** The audit is complete today (the only other child-derived persist, `unexpected-stdout`, records a byte count), but the invariant "scrub before persist" is enforced by author discipline rather than by the writer, so the next diagnostic that persists a child-derived string reopens the capability-leak path with no test to catch it — and AC2 describes the *writer* as the thing that redacts.
**Proposed fix:** Give `Recorder` the `StartupToken` (or a scrub closure) at construction and scrub the serialized line inside `record` immediately before `write_all`, keeping the call-site scrub as belt-and-braces. That makes the guarantee structural and costs ~10 LOC.
**Regression-guard:** Optional — a Rust unit test that hands `Recorder::record` a field containing the token and asserts the written line contains `[REDACTED]`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security threat-model coverage

**M9 — Wildcard-bind fault arms dropped with no recorded non-claim** (MEDIUM)

**Where:** `apps/desktop/crates/fixture-sidecar/src/main.rs:41`
**Anchor:** `    /// Ignore stdin EOF, shutdown frames`
**What:** The spike's `Fault` set (`tools/desktop_lifecycle_spike/src/lib.rs:14-24`) has nine arms including `WildcardV4` and `WildcardV6`; the ported enum has seven and silently omits both, and the README's "Two spike-3 non-claims REMAIN non-claims" section records only the dead-parent and process-group narrowings.
**Why it matters:** `wildcard-bound.jsonl` proves a frame cannot *announce* a wildcard and `_assert_loopback_only` proves the kernel state of a well-behaved child, but nothing exercises a child that binds `0.0.0.0` while announcing `127.0.0.1` — the supervisor performs no runtime check of the actual bind, so AC5's socket-level claim has no negative case and a reader comparing the matrix to the spike sees an unexplained gap.
**Proposed fix:** Either add a `wildcard-v4` arm (bind `Ipv4Addr::UNSPECIFIED`, still announce `127.0.0.1`) plus a test asserting `_assert_loopback_only` *fails* on it, or record the omission alongside the other two non-claims in `apps/desktop/README.md` with the reason (the supervisor has no runtime bind probe, so the arm would document a gap rather than close one).
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M10 — contract-fixtures has no inventory guard for its aggregate digest** (MEDIUM)

**Where:** `apps/desktop/contract-fixtures/fixtures.sha256:1`
**Anchor:** `69eae0627027c9214636435f378099e126de38e`
**What:** The re-pin is correct — recomputed independently as `69eae062…d7835` over the 13 `.jsonl` files in lexicographic order with the `name`+NUL+bytes encoding, matching both language gates — but the digest now covers a file that is not a wire frame, and no test asserts that every `.jsonl` in the directory is claimed by `POSITIVE_FIXTURES`, `NEGATIVE_FIXTURES`, `incompatible-major.jsonl`, or the redaction consumer.
**Why it matters:** The aggregate digest is the only thing that notices a new file there, and a digest bump is indistinguishable from an intentional one — so a future frame fixture can land with zero parse coverage, and a redaction-vector edit now invalidates the wire-contract pin (and vice versa), coupling two contracts that change for different reasons.
**Proposed fix:** Add an inventory test in both languages asserting `set(dir.glob("*.jsonl")) == POSITIVE ∪ NEGATIVE ∪ {"incompatible-major.jsonl", "redaction-vectors.jsonl"}`, so adding a fixture forces a conscious consumer decision rather than only a digest bump. Optionally split `redaction-vectors.jsonl` into its own pin.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** cache byte-stability / contract-fixture discipline

**M11 — AC3's "zero orphan process groups" has no pgid probe** (MEDIUM)

**Where:** `tests/test_desktop_contract.py:205`
**Anchor:** `def _pid_is_gone(pid: int) -> bool:`
**What:** The stress audit proves 30 distinct PIDs, 30 `ps -p` absences and 30 empty `lsof` results, but never inspects a process group; the milestone AC's "zero orphan process groups" clause is answered only by the README's "process-group escape is not applicable, not handled".
**Why it matters:** The narrowing is honest and correct today (neither the fixture nor the production child spawns descendants), but it is argued in prose rather than probed, so the day a child does spawn a helper the suite reports clean absence for a group it never looked at — and the AC will still read as satisfied.
**Proposed fix:** Add `_pgid_is_empty(pgid)` using `ps -o pid= -g <pgid>` through `_probe_command`, capture the child's pgid from `ps -o pgid= -p <pid>` while it is alive, and assert the group is empty after each cycle. ~10 LOC, and it turns the non-claim into a measured one.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing (m4 umbrella acceptance criteria)

**M12 — Escalation-ladder wall budget measures tauri boot, not the ladder** (MEDIUM)

**Where:** `tests/test_desktop_child.py:1082`
**Anchor:** `    assert wall < 30.0, f"escalation ladder took {wall`
**What:** `wall` starts before `_spawn_fault_supervisor`, so the 30 s ceiling covers plan authoring, supervisor exec, tauri app build, webview window creation, child spawn, readiness poll and smoke HTTP — while the ~800 ms shrunk ladder it names is a small fraction of it, and the same test tolerates 90 s at `process.wait`.
**Why it matters:** The assertion and the wait budget disagree by 3x, so a run taking 40 s passes the wait and then fails an assertion whose message blames the escalation ladder — the m3 "200 ms → 2 s under load" flake shape, aimed at the most boot-variable path in the suite.
**Proposed fix:** The `Recorder` already stamps a monotonic `elapsed_ms` on every event (`supervisor/src/events.rs:42`). Assert on the `child-ready` → `orphan-shutdown` `elapsed_ms` delta instead of wall clock: that measures only the ladder, excludes tauri boot entirely, and can keep a tight bound (a few seconds) without flaking.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**M13 — Marker description stale; ps/lsof prerequisite undeclared** (MEDIUM)

**Where:** `pyproject.toml:374`
**Anchor:** `    "requires_desktop_stack: desktop-distribution-m5 rea`
**What:** `CLAUDE.md` was updated to `desktop-distribution-m5/m6` in this range but the marker description it mirrors still reads m5-only, and neither text declares that `ps` and `lsof` are now hard prerequisites that raise `RuntimeError` rather than skipping.
**Why it matters:** The unmarked `test_thirty_cycles…` and `test_live_listener…` gate on the fixture binary existing at the default build path, so on any box that has run `make desktop-conformance` a subsequent plain `make test` runs them and hard-fails if `lsof` is absent — the `requires_latexmlc` / issue-#206 failure shape the marker's own text cites as its precedent, now reachable from the everyday target.
**Proposed fix:** Update the `requires_desktop_stack` string to m5/m6 and name `ps` + `lsof` as prerequisites with install hints (`apt install lsof`; present by default on macOS), matching how `requires_latexmlc` and `requires_pdflatex` document theirs. Mention the same two tools in `apps/desktop/README.md`'s new "Fault matrix and cleanup claims (m6)" section, which currently describes the probes' self-assertion discipline without saying they must be installed.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**L1 — `park_on_lease` error arm has no backoff and no deadline** (LOW)

**Where:** `apps/desktop/crates/fixture-sidecar/src/main.rs:182`
**Anchor:** `Err(_) => {}`
**What:** A persistent `ContractError::Io` from stdin makes the startup-timeout park loop spin at 100% CPU indefinitely, since the arm neither sleeps, counts, nor bounds; `Ok(None)` (EOF) is the only terminating path besides a valid shutdown frame.
**Why it matters:** Fixture-only and hard to trigger (a dead writer yields EOF, not an error), so impact is confined to a wedged conformance run rather than production — flagged as low-confidence and low-severity accordingly.
**Proposed fix:** Add a small `std::thread::sleep(POLL_INTERVAL)` in the error arm and an overall park deadline consistent with M3's bound, so a pathological stdin cannot burn a core for the life of the process.
**Regression-guard:** None required at this severity.
**Source critic:** milestone-adversary-critic
**Source axis:** Dead code / leftovers

**L2 — Redundant Arc handle for the captured exit code** (LOW)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:244`
**Anchor:** `    let requested_exit: Arc<Mutex<i32>> = `
**What:** `requested_exit` is created only to be cloned into `exit_code_slot` on the next line and is never read afterwards, leaving a second strong reference alive for the rest of `main`.
**Why it matters:** Pure noise in the one function a reader opens to understand the tauri 2.11 exit-code workaround.
**Proposed fix:** `let exit_code_slot: Arc<Mutex<i32>> = Arc::new(Mutex::new(0));` and drop the extra binding.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** open scan (dead code)

**L3 — park_on_lease retries read errors with no bound and no sleep** (LOW)

**Where:** `apps/desktop/crates/fixture-sidecar/src/main.rs:182`
**Anchor:** `            Err(_) => {}`
**What:** A `read_frame` error re-enters the loop immediately; only `Ok(None)` (EOF) exits. A persistent `ContractError::Io` therefore spins a core with no backoff and no exit path.
**Why it matters:** The realistic case is EOF, so this is latent — but it is the one arm of the fault matrix whose failure mode is "burn CPU forever" rather than "exit", which is the opposite of what the milestone claims about bounded cleanup.
**Proposed fix:** Return `Err(SidecarError::Io)` on a read error, or at minimum `std::thread::sleep(POLL_INTERVAL)` before continuing.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** open scan (silently swallowed errors)

**L4 — Probe binary fallback path is macOS-shaped** (LOW)

**Where:** `tests/test_desktop_contract.py:191`
**Anchor:** `    binary = shutil.which(argv[0]) or f"/u`
**What:** The fallback when `shutil.which` misses is `/usr/sbin/<tool>`, which is where macOS keeps `lsof`; most Linux distros install it at `/usr/bin/lsof` (and `ps` at `/bin/ps`).
**Why it matters:** On a Linux box with a trimmed `PATH` the fallback never resolves and the probe raises "unavailable" even though the tool is installed — an evidence failure attributed to the wrong cause.
**Proposed fix:** Try a small candidate list (`/usr/sbin/`, `/usr/bin/`, `/bin/`) before giving up.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first + Docker constraint

**L5 — Redaction-vector floor of 7 is below the 9 shipped vectors** (LOW)

**Where:** `apps/desktop/crates/supervisor/src/redact.rs:43`
**Anchor:** `        assert!(count >= 7, "redaction vect`
**What:** Both the Rust guard here and the Python guard at `tests/test_desktop_contract.py:670` assert `>= 7` against a file that ships 9 vectors, so two can be deleted without either gate noticing.
**Why it matters:** The named-case assertions below (partial match, uppercase near-miss) cover two of the nine; the other seven are protected only by this floor and the aggregate digest, and a digest bump is exactly what a vector edit already requires.
**Proposed fix:** Pin the exact count (`== 9`) so a deletion is a deliberate two-language edit, matching the discipline `fixtures.sha256` already imposes.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**L6 — park_on_lease error arm has no backoff and no exit condition** (LOW)

**Where:** `apps/desktop/crates/fixture-sidecar/src/main.rs:182`
**Anchor:** `            Err(_) => {}`
**What:** The startup-timeout park loop swallows every `read_frame` error and immediately retries with no sleep and no attempt counter, so a persistent stdin I/O error (as opposed to EOF, which returns cleanly) becomes an unbounded hot loop.
**Why it matters:** The sibling `spawn_control_reader` at `:286` at least escapes when its channel send fails; this loop has no escape at all, so the one arm designed to sit parked while the supervisor times out is also the one that can spin a core indefinitely — the failure class this milestone exists to eliminate.
**Proposed fix:** Bound the arm: sleep `POLL_INTERVAL` on error and return after a small consecutive-error count (three is plenty), so a wedged stdin ends the fixture rather than burning a core.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

## What was done well

### From milestone-adversary-critic

- **The fault matrix genuinely discriminates supervisor behavior from fixture
  cooperation.** Each arm pins a *different* supervisor-side outcome —
  `orphan-shutdown.child_exit == 0` for startup-timeout and malformed-bound
  (cooperative reap), `== -1` for crash-before-bound and ignore-shutdown — and
  `-1` is only reachable through `shutdown_child`'s grace → TERM → force → KILL
  ladder. An arm cannot pass merely because the fixture exited tidily.
- **`fixtures.sha256` was independently recomputed and is exact.** Re-deriving
  the manifest (lexicographic name, NUL, bytes) over all 13 fixtures reproduces
  `69eae0627027c9214636435f378099e126de38e615f9f118f3ffaca7bf6d7835` byte-for-byte;
  the bump is the intentional consequence of adding `redaction-vectors.jsonl`.
- **The tauri 2.11 exit-code find is real and guarded in BOTH directions.** The
  six fault tests pin nonzero, and m5's pre-existing
  `test_ac3_zero_delay_race_single_spawn` already asserts `first_code == 0 and
  second_code == 0` on the success path, so the fix cannot regress either way.
  `ExitRequested { code: Some(..) }` correctly ignores the `None` a window-close
  emits, so a user quit still exits 0.
- **Scrub runs before truncation.** `lifecycle.rs:266-267` scrubs the full
  `from_utf8_lossy` frame and only then takes 256 chars — the one ordering that
  makes the downstream structural 64-hex sweep sound, since a boundary cut
  through an unscrubbed token would leave a partial secret the `[0-9a-f]{64}`
  regex cannot see.
- **The second raw-stdout path leaks nothing.** The post-`bound` drain thread
  records only a byte count (`lifecycle.rs:254`), so a child dumping the token
  after a valid bound frame cannot reach the event log.
- **The 30-cycle stress spawns 30 real, fully-started processes.** Each cycle
  reads a `bound` frame and completes an HTTP `/healthz` round trip before being
  stopped, alternating authenticated shutdown and bare stdin EOF; the `ps`/`lsof`
  audits are per-cycle and aggregated into `bad == []`, so one bad cycle cannot
  hide behind twenty-nine good ones.
- **`never-ready` is a well-judged sixth arm.** It creates a deterministic
  live-listener window for the supervisor-SIGKILL test without making the fixture
  uncooperative, which is what keeps that test an honest test of parent death
  rather than of the fixture.
- **Test-only knobs are contained.** They ride the `Plan` rather than a second
  env override path, are `#[serde(default)] Option<_>` under `deny_unknown_fields`,
  keep the WIRE frame at the `MIN_GRACE_MS` contract floor while shrinking only
  local waits, and are pinned absent-by-default by a unit test. Verified
  independently that `server/desktop_child.py` never inspects `extensions`
  (`:198` sets `extensions={}` only), so the namespaced fault key is inert in
  production.
- **The deviations artifact discloses the weakest link itself** — deviation 5
  states plainly that the Python redaction half is a test-level reference rather
  than a production scrubber, instead of letting AC2's wording imply more.
- **Commit and process hygiene are clean.** Three commits, all `%G? = G`, all
  carrying `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`, conventional
  subjects ≤ 53 chars; no `plans/` path and no roadmap checkbox touched, so the
  one-writer rule is intact; the diff performs no external write.

### From milestone-arxmcp-critic

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

### From milestone-infra-safety-critic

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

Severity counts: C1 H6 M13 L6


## Cross-critic agreement

The following findings cluster within 5 lines of each other in the same file. Multiple critics flagged the same area - these are the strongest signals to fix first.

- **H1, H4, M11** at `tests/test_desktop_contract.py:200-205` (HIGH): `lsof` error is read as verified clean absence, violating AC3; ps/lsof exit-code discriminator cannot detect a failed probe; AC3's "zero orphan process groups" has no pgid probe
- **M4, H6, M12** at `tests/test_desktop_child.py:1077-1082` (HIGH): 90s fault-test wait is shorter than the supervisor's own budget; No teardown reaps the grandchild; ignore-shutdown arm is SIGTERM-immune; Escalation-ladder wall budget measures tauri boot, not the ladder
- **M1, M7** at `apps/desktop/crates/supervisor/src/redact.rs:5-8` (MEDIUM): Redaction is one call site, not the writer `redact.rs` claims; "Two independent implementations" overclaims the redaction parity
- **M2, M13** at `pyproject.toml:374-374` (MEDIUM): pyproject marker text still m5-only while CLAUDE.md was updated; Marker description stale; ps/lsof prerequisite undeclared
- **L1, L3, L6** at `apps/desktop/crates/fixture-sidecar/src/main.rs:182-182` (LOW): `park_on_lease` error arm has no backoff and no deadline; park_on_lease retries read errors with no bound and no sleep; park_on_lease error arm has no backoff and no exit condition

## Recommended rectification order

C1, H1, H2, H3, H4, H5, H6, M1, M2, M3, M6, M4, M5, M8, M7, M11, M9, M10, M12, M13, L1, L3, L5, L2, L4, L6

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
