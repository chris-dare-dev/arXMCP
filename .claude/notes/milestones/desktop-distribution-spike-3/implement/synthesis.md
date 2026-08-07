# Implementation Summary — desktop-distribution-spike-3

**One-line summary:** Prove direct-sidecar lifecycle ownership with a pinned Tauri host.
**Commit range:** 010d85d70b550ed98ab343aedb0bca9d8e2a3e02..3f24b54b5b6ee6fd5b9c948ca81ad98f023dee05
**Branch:** main
**Date:** 2026-08-07T14:42:56Z

## Acceptance criteria status

- [x] Build and execute a real, exactly pinned Tauri 2 host with a committed
  `Cargo.lock`, single-instance arbitration first, a target-triple sidecar, and
  no committed build output — met (`tauri` 2.11.5, shell 2.3.5,
  single-instance 2.4.3; the duplicate race produced exactly one sidecar).
- [x] Retain `127.0.0.1:0`, validate a bounded canonical `bound` frame,
  distinguish health/readiness with a monotonic deadline, and clean malformed,
  wildcard, never-bound, and never-ready cases — met.
- [x] Generate a 256-bit token, transport it only over bounded stdin frames,
  and keep it out of argv, the allowlisted environment, output, logs, and test
  diagnostics — met by host full-token scans and independent canary scans.
- [x] Exercise graceful shutdown, TERM-to-KILL escalation, crashes before and
  after readiness, startup timeout, duplicate launch, and supervisor `SIGKILL`
  with a same-group canary and direct-child reap — met across eleven live cases.
- [x] Audit PID/executable absence, an empty fixture process group, refused TCP,
  and no `lsof` listener after every case, then pass 30 fresh cycles with exact
  orphan/listener totals of 0/0 — met; cycle latency was 377.372/390.912/406.493
  ms minimum/mean/maximum.
- [x] Record states, frames, macOS primitives, exact versions and commands,
  fault results, raw digest, limitations, decision, and fallback in the durable
  ADR while committing no generated binaries or raw logs — met; decision GO,
  raw aggregate SHA-256 `63a96d6dbe98ff4df0711a77ebe1fa493ee8eabdf68c3e7be983baf05dab8964`.
- [x] Preserve MCP schema/cache/prompt pins, loopback-only behavior, PyInstaller
  onedir, centralized data-root, and no-SPA/no-Node constraints, and pass all
  applicable gates — met; no production server or frontend surface changed.

## New and changed files

- `.claude/agent-memory/milestone-implementer/lessons.md` — records the stable
  Tauri adjacent-sidecar/target-triple resolution lesson.
- `.claude/notes/milestones/desktop-distribution-spike-3/implement/lifecycle-results.json`
  — normalized evidence for eleven cases and thirty cycles.
- `.claude/notes/milestones/desktop-distribution-spike-3/implement/scope-exceeded.md`
  — records the pre-authorized large-diff scope checkpoint.
- `.claude/notes/spikes/desktop-distribution-spike-3.md` — durable lifecycle ADR,
  measurements, decision, fallback, and non-claims.
- `tests/test_wheel_packaging.py` — excludes the source-only Rust workspace from
  Python wheel package-data scanning.
- `tools/desktop_lifecycle_spike/Cargo.toml` — pins Tauri dependencies and
  space-conscious deterministic development/test profiles.
- `tools/desktop_lifecycle_spike/Cargo.lock` — locks the exact Rust graph.
- `tools/desktop_lifecycle_spike/build.rs` — invokes the pinned Tauri build seam.
- `tools/desktop_lifecycle_spike/tauri.conf.json` — defines the no-window,
  non-bundling spike host.
- `tools/desktop_lifecycle_spike/src/lib.rs` — defines bounded frames, fault
  vocabulary, loopback validation, and 256-bit token creation.
- `tools/desktop_lifecycle_spike/src/main.rs` — owns single-instance routing,
  target-triple sidecar launch, health/readiness, redaction, and group cleanup.
- `tools/desktop_lifecycle_spike/src/bin/fixture_sidecar.rs` — provides the
  retained loopback listener, stdin lease, advisory lock, canary, and faults.
- `tools/desktop_lifecycle_spike/run_spike.py` — drives the live matrix, process
  and listener audits, secret scans, raw digests, and thirty-cycle gate.

## New and changed tests

- `tools/desktop_lifecycle_spike/src/lib.rs` — tests token entropy/shape, frame
  bounds, and wildcard/identity rejection.
- `tools/desktop_lifecycle_spike/src/bin/fixture_sidecar.rs` — tests bounded
  framing and authenticated readiness.
- `tools/desktop_lifecycle_spike/src/main.rs` — tests scenario coverage,
  target-triple naming, and exact probe responses.
- `tests/test_desktop_lifecycle_spike.py` — pins dependencies and source
  boundaries, tests harness secret handling, and makes committed GO/0/0 evidence
  plus all invalid-bound rejections a repository gate.
- `tests/test_wheel_packaging.py` — retains its existing wheel tests while
  recognizing the non-Python spike source tree.

Verification completed:

- `cargo test --locked ...` — 8 passed.
- `cargo clippy --locked ... --all-targets -- -D warnings` — passed.
- `cargo build --locked ... --bins` — produced real arm64 Mach-O host/fixture.
- `run_spike.py ... --cycles 30` — GO; 11/11 cases and 30/30 cycles passed,
  with 0 orphan groups, 0 listeners, and 0 secret-scan failures.
- focused Python gate — 27 passed, 2 skipped.
- `make test PYTHON=.venv/bin/python` — ruff clean; 5,029 passed, 43 skipped,
  1 xfailed. The initial managed run's 14 loopback `EPERM` results were eliminated
  by the required identical unsandboxed rerun.

## Deviations from the brief

None — implementation follows the brief exactly. The explicit
`startup-timeout` case supplements the required malformed and never-ready cases,
and the native Rust guardian fallback was not selected because the pinned Tauri
shell handle retained stdin, exposed the PID, and delivered termination events.
The authorized large diff is primarily the normalized 41-run evidence artifact;
no production integration was added.

## External writes the orchestrator must authorize

| type | target | why | blocking |
|---|---|---|---|
| git push | `origin/main` | Publish the locally committed spike result. | false |
