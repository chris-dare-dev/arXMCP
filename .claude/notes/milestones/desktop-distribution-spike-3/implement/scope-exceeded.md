# Scope exceeded — desktop-distribution-spike-3

## Guard

- Implementation base: `010d85d70b550ed98ab343aedb0bca9d8e2a3e02`.
- `ALLOW_LARGE_DIFF=false`; the Phase-2 stop thresholds are 350 changed
  lines, six files, or 800 total lines.
- The first coherent source/config slice reached 363 authored lines across
  five files, crossing the 350-line mid-flight threshold. Work stopped.
- Generating the acceptance-required `Cargo.lock` added 5,054 reproducibility
  lines and crossed both the six-file and 800-line hard stops. It is retained
  because an unlocked Tauri dependency graph would not be coherent progress.

## Partial implementation committed

- The isolated crate pins Tauri 2.11.5, shell 2.3.5, and single-instance
  2.4.3; `Cargo.lock` resolves them exactly and build output stays in a unique
  `/private/tmp` target directory.
- The real no-window Tauri host registers single-instance before shell setup,
  clears the child environment, generates a 256-bit token, sends it only in a
  bounded stdin bootstrap frame, retains the stdin lease, and consumes raw
  shell events through a capped buffer.
- The host validates protocol version, sequence, PID, loopback address, and
  dynamic port, distinguishes `/healthz` from authenticated `/readyz`, sends
  authenticated graceful shutdown, and waits for the termination event.
- The fixture establishes its own process group, holds a non-blocking advisory
  lock, binds `127.0.0.1:0`, serves bounded health/readiness requests, and
  closes its listener on authenticated shutdown or stdin EOF.
- The Python wheel guard now explicitly treats this source-only Rust/Tauri
  subtree as non-wheel content; Cargo remains its only build path.

## Remaining after rescope

- Replace the development executable-path spawn with the target-triple Tauri
  sidecar path and prove the built-app duplicate-launch callback creates no
  second child, lock owner, or listener.
- Add malformed-announcement, never-ready, ignored-shutdown, forced
  `SIGTERM`/`SIGKILL`, crash-before/after-ready, same-group canary, and
  supervisor-`SIGKILL` scenarios with bounded reap and cleanup audits.
- Add token-canary scans across argv, environment diagnostics, protocol bytes,
  and persisted logs; prove wildcard/IPv6-wildcard rejection end to end.
- Run and retain raw results for 30 fresh lifecycle cycles with PID,
  process-group, connection-probe, and `/usr/sbin/lsof` audits after every run.
- Write the durable spike ADR with the protocol/state machine, measurements,
  limitations, fallback, and an evidence-backed GO or NO-GO decision.

## Verification

- `cargo fmt --check`: PASS.
- `cargo test --locked --all-targets`: PASS (`2 passed`).
- `cargo clippy --locked --all-targets -- -D warnings`: PASS.
- Real no-window Tauri launch → ready → graceful stop: PASS (exit 0); a
  read-only process/listener audit found no residual matching process or TCP
  listener. This is one smoke cycle, not the milestone's 30-cycle evidence.
- Focused wheel package-data guard: PASS (`1 passed`).
- Sandboxed `make test PYTHON=.venv/bin/python`: environment-limited
  (`5006 passed, 43 skipped, 1 xfailed`; fourteen loopback-bind cases failed
  with `EPERM`; the one real package-data failure was fixed before rerun).
- Approved unsandboxed `make test PYTHON=.venv/bin/python`: PASS
  (`5021 passed, 43 skipped, 1 xfailed`; Ruff clean).
- Tauri-generated `gen/schemas/` and the 1.7 GiB Cargo target are not tracked;
  schemas were removed and target output remains under `/private/tmp`.

## External writes

- `git push origin main` remains Phase 4 only and requires per-event approval.
- Updating GitHub issue `chris-dare-dev/arXMCP#386` remains Phase 4 only and
  requires explicit authorization.
