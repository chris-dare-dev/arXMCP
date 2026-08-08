# Implement synthesis — desktop-distribution-m6

Base `c0dcf98` → commits `b0a407d` (desktop crates), `4a543ef` (tests+docs),
plus the checkpoint commit. Honest hand-written diff ≈ 980 LOC
(326 rs/toml/jsonl/md in part 1 + 651 test/doc lines in part 2, +1 Cargo.lock
line) across 14 files. `--allow-large-diff` was owner-authorized for m6 in
advance (recorded in state.json); no mid-flight STOP applied per dispatch.

## Built

- **AC1 — fault matrix, bounded cleanup, no process, no listener.** The REAL
  supervisor (`lifecycle.rs`/`main.rs`) is driven against six fixture-sidecar
  fault arms selected by the namespaced `org.arxmcp.test-fault` launch
  extension (`lifecycle.rs:119-125` inserts it from the test-only
  `Plan.test_fault`, `main.rs:47-53`; arms in
  `fixture-sidecar/src/main.rs:109-196`). Tests
  (`tests/test_desktop_child.py:929-1214`): startup timeout
  (`test_fault_startup_timeout_bounded_cleanup`, bound-timeout shrunk via
  `Plan.test_bound_timeout_ms` — production stays 240 s), malformed bound
  (`test_fault_malformed_bound_scrubbed_and_reaped` — cleanup works with no
  port ever learned), crash-before-bound (reason pinned from live
  observation: "child stdout closed before bound"; orphan reap −1),
  crash-after-ready (two-way race asserted as the invariant — no PID, no
  listener, bounded, failure recorded), ignored shutdown
  (`test_fault_ignored_shutdown_force_escalates` — full
  grace→TERM→force→KILL→reap ladder through the production cycle path,
  supervisor-LOCAL budget shrink only; wall asserted < 30 s vs the wire's
  42 s), and supervisor SIGKILL
  (`test_fault_supervisor_sigkill_cooperating_child_self_cleans` via the
  `never-ready` arm's stable post-bound window). New `orphan-shutdown` event
  (`lifecycle.rs:91-96`) makes the Err-arm reap outcome observable.
- **AC2 — recursive diagnostic scans + Rust-side redaction to the Python
  standard.** New `supervisor/src/redact.rs` (`scrub`: exact-match
  `[REDACTED]`, scrub-before-truncate) wired into the one raw-capture persist
  site, the new `bound-frame-invalid` diagnostic (`lifecycle.rs:253-262`).
  The malformed-bound arm EMBEDS the capability in its invalid frame
  (`fixture-sidecar/src/main.rs:128-135`), so the matrix proves
  scrub-before-persist end-to-end: the persisted event carries `[REDACTED]`
  and no 64-hex token. Parity rides ONE shared fixture,
  `contract-fixtures/redaction-vectors.jsonl` (9 vectors incl. partial and
  uppercase near-misses that must NOT be redacted), consumed by the Rust
  unit test (`redact.rs:31-49`) and Python
  (`test_desktop_contract.py::test_redaction_vectors_shared_fixture_parity`).
  `fixtures.sha256` updated intentionally; both language digest gates pass
  independently. Every fault test ends in `_sweep_fault_artifacts`
  (`test_desktop_child.py:912-923`): recursive `_HEX64` scan over the whole
  data root + supervisor streams, allow-listing only the fixture identity
  digest.
- **AC3 — 30 cycles, 30 distinct PIDs, zero orphans/listeners,
  self-asserting probes.**
  `test_desktop_contract.py::test_thirty_cycles_distinct_pids_no_orphans_no_listeners`:
  30 FRESH `subprocess.Popen` fixture spawns (alternating
  authenticated-shutdown / stdin-EOF), one live HTTP round trip per cycle,
  `len(set(pids)) == 30`, aggregated evidence block. `_probe_command`
  (`test_desktop_contract.py:183-201`) raises on any probe that did not
  itself succeed — missing binary, timeout, exit code outside found(0)/
  not-found(1) — so a failed/partial `ps`/`lsof` can never read as clean
  absence. Wall ceiling 120 s (measured ~4 s on this box) per the
  bounded-not-aggressive rule.
- **AC4 — real-server fault case.**
  `test_desktop_child.py::test_real_server_bare_stdin_eof_is_bounded_cleanup`:
  own real-child boot, bare `stdin.close()` with NO shutdown frame — the
  supervisor-crash scenario on shipped code (`_watch_stdin`'s EOF arm,
  previously untested; m5 AC4 always sent an authenticated frame). Exit 0
  strictly inside `grace_ms`, connect probe flips from proven-connect to
  `ConnectionRefusedError`, pid/listener probes self-assert, full artifact
  secret sweep. **Zero new lines in `server/desktop_child.py`.**
- **AC5 — socket-level loopback.** `_assert_loopback_only`
  (`test_desktop_contract.py:242-270`): lsof must FIND the live listener and
  every row's local address must be `127.0.0.1:<port>` (never `*`/`0.0.0.0`),
  plus a refused TCP connect on every discoverable non-loopback IPv4
  (getaddrinfo + TEST-NET-1 route-lookup discovery). Applied to the fixture
  (`test_live_listener_is_loopback_only_at_socket_level`) AND the live real
  server (inside the AC4 EOF test). A loopback-only host degrades to the
  structural checks and RECORDS it via `warnings.warn` — never a silent
  skip.
- **AC6 — gates.** See Check gate results. The two spike-3 non-claims are
  restated as named limits in the test docstrings and in
  `apps/desktop/README.md` §"Fault matrix and cleanup claims (m6)", which
  replaces the old "fault matrix … deferred" sentence.

## Production bug found and fixed (in-scope)

tauri 2.11's run loop does NOT propagate `AppHandle::exit(code)` into the
process exit status — a failed lifecycle exited 0 (measured live before the
fix; m5's AC3 asserts a success 0 so it could not catch this). `main.rs`
now captures `RunEvent::ExitRequested { code }` and exits with it after the
`RunEvent::Exit` child shutdown (`main.rs:240-271`). Every fault test now
asserts supervisor exit 1.

## Branching note

All commits directly on `main` per CLAUDE.md §4.1 (single-user project, no
feature branches); dispatch confirmed main-checkout work, no worktree.

## Deviations from the brief

Recorded in full at `artifacts/implementer-a-deviations.md`: (1) bound-timeout
override is a Plan field, not an env var; (2) grace/force shrink is
supervisor-local only — the contract's `MIN_GRACE_MS` floor rejects the
brief's wire-level shrink; (3) sixth fixture arm `never-ready` creates the
supervisor-SIGKILL window; (4) `redact::scrub` built AND production-wired
(brief left it conditional) because `bound-frame-invalid` is a real
raw-capture site; (5) Python's half of the redaction vectors is a test-level
reference — no production Python substring scrubber exists.

## Files touched

- `apps/desktop/crates/supervisor/src/main.rs` — test-only Plan knobs; exit-code
  propagation fix.
- `apps/desktop/crates/supervisor/src/lifecycle.rs` — fault-extension insert,
  bound-timeout/budget plumbing, scrubbed `bound-frame-invalid` diagnostic,
  `orphan-shutdown` event.
- `apps/desktop/crates/supervisor/src/redact.rs` — NEW scrub primitive + shared
  vector unit test.
- `apps/desktop/crates/fixture-sidecar/src/main.rs` — six fault arms.
- `apps/desktop/crates/fixture-sidecar/Cargo.toml` — cfg(unix) libc dep.
- `apps/desktop/Cargo.lock` — one-line regen for the fixture libc dep.
- `apps/desktop/contract-fixtures/redaction-vectors.jsonl` — NEW shared vectors.
- `apps/desktop/contract-fixtures/fixtures.sha256` — intentional digest update.
- `apps/desktop/README.md` — fault-matrix section + non-claims + vector doc.
- `tests/test_desktop_contract.py` — probe helpers, redaction parity, 30-cycle
  stress, loopback regression (31 → 34).
- `tests/test_desktop_child.py` — fault-matrix harness + 6 fault tests +
  real-server EOF test (18 → 25).
- `CLAUDE.md` — §4.5 `requires_desktop_stack` bullet extended for m6.
- NOT modified: `server/desktop_child.py`, `server/config.py`,
  `server/main.py`, `server/middleware.py`, `server/tools.py`,
  `server/prompts.py`, `Makefile` (existing gate already covers the new
  tests), `pyproject.toml` (no new marker).

## Deferred

- No canary-spawning fixture / `setsid()`-escape test — non-claim #2 is
  vacuously true today (no shipped component spawns descendants) and is
  documented as not-applicable rather than "handled" (README).
- Wedged-child-after-parent-death cleanup — explicitly out of scope
  (non-claim #1); stated in docstrings + README.
- `Fixes #397` deliberately absent from these commits — it rides the FINAL
  milestone commit at the orchestrator's external-write boundary.

## external_writes_required

- `git push origin main` (per-event authorization; NOT performed here).
- `Fixes #397` on the final milestone commit (orchestrator-owned).

## Test deltas

- `tests/test_desktop_contract.py`: +3 (redaction parity, 30-cycle stress,
  loopback socket regression) → 34.
- `tests/test_desktop_child.py`: +7, all `requires_desktop_stack` (6 fault
  matrix + 1 real-server EOF) → 25.
- Rust: +1 supervisor unit test (redaction vectors) → 11 supervisor + 8
  contract = 19 (was 18).
- `make test`: 5,082 → **5,085 passed**, 47 → **54 skipped** (exactly the 7
  new opt-in marks), 1 xfailed. Zero regressions.

## Check gate results

- `cargo fmt --all --manifest-path apps/desktop/Cargo.toml -- --check`: PASS
- `cargo clippy --locked --target-dir /private/tmp/arxmcp-desktop-target
  --workspace --all-targets --all-features -- -D warnings`: PASS
- `cargo test --locked --workspace`: PASS — 19 (8 contract + 11 supervisor)
- `make desktop-conformance PYTHON=.venv/bin/python`: PASS, exit 0 —
  **34 passed** (contract, 4.00 s) + **25 passed** (child, 41.95 s),
  ZERO skips
- `make test PYTHON=.venv/bin/python`: PASS, exit 0 — 5,085 / 54 / 1 in
  5 m 18 s; ruff clean
- m5 H3 guard: `DESKTOP_SUPERVISOR_BIN=/nonexistent pytest
  tests/test_desktop_child.py -m "foo or not foo"` → **exit 1** (11 skips
  named, incl. the 7 new tests)
- git status: clean (state.json + notes artifacts in the checkpoint commit)
