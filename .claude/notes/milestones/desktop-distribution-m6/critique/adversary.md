# Critique — desktop-distribution-m6 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** c0dcf98..822dab7
**Diff stats:** 16 files, 1279 LOC (+1240 / -39; ex-`.claude/` +977 / -37)
**Critique format version:** 1.0

## Verdict

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

## Executive summary

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

**L1 — `park_on_lease` error arm has no backoff and no deadline** (LOW)

**Where:** `apps/desktop/crates/fixture-sidecar/src/main.rs:182`
**Anchor:** `Err(_) => {}`
**What:** A persistent `ContractError::Io` from stdin makes the startup-timeout park loop spin at 100% CPU indefinitely, since the arm neither sleeps, counts, nor bounds; `Ok(None)` (EOF) is the only terminating path besides a valid shutdown frame.
**Why it matters:** Fixture-only and hard to trigger (a dead writer yields EOF, not an error), so impact is confined to a wedged conformance run rather than production — flagged as low-confidence and low-severity accordingly.
**Proposed fix:** Add a small `std::thread::sleep(POLL_INTERVAL)` in the error arm and an overall park deadline consistent with M3's bound, so a pathological stdin cannot burn a core for the life of the process.
**Regression-guard:** None required at this severity.
**Source critic:** milestone-adversary-critic
**Source axis:** Dead code / leftovers

## What was done well

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

Severity counts: C1 H2 M3 L1

## Recommended rectification order

C1, H1, H2, M1, M2, M3, L1
