# Desktop distribution spike 3 — lifecycle ownership

**Decision:** GO — use the pinned Tauri shell handle for direct-sidecar control,
with a native advisory supervisor lock as the simultaneous-launch guard.

**Measured on:** macOS 26.6, Apple Silicon (`aarch64-apple-darwin`)

**Raw-result digest:**
`dfc11ca3c99b9a8c4a19e237e03e257a4fef52d1052ef41f6cb7022a3ec96ab9`

## Decision record

The built no-window Tauri host retained the shell plugin's stdin writer, exposed
the direct-child PID, delivered raw bounded stdout/stderr events, and delivered a
termination event after both cooperative and signalled exits. These primitives
are sufficient for the direct-child contract. The native *process guardian*
fallback is not selected, but the simultaneous-launch run showed that Tauri's
single-instance plugin alone does not close a zero-delay startup race.

The single-instance plugin is registered before the shell plugin and before the
setup callback. Two hosts released from one external barrier produced zero Tauri
activation callbacks; the native `supervisor.lock` fallback selected one owner
before sidecar setup, the loser exited cleanly, and the shared event record
contained exactly one `sidecar_spawned` transition. A steady-state Tauri
activation remains supported, but the GO decision does not depend on it. The
fixture's own advisory lock remains a second guard beneath the application-data
root.

## Lifecycle and frame contract

The host serializes one lifecycle actor through these measured transitions:

1. `lifecycle_started` → `sidecar_spawned`
2. bounded stdin `init` frame → `bootstrap_sent`
3. bounded stdout `bound` frame → `bound_validated`
4. exact `/healthz` → authenticated `/readyz` → `ready_authenticated`
5. authenticated stdin `shutdown` → bounded wait → `sidecar_reaped`
6. on expiry: process-group `SIGTERM` → bounded wait → process-group
   `SIGKILL` → direct-child termination event/reap

Before the fixture creates its PID-named process group, a group signal can
legitimately return `ESRCH` while the child is still alive. The host then signals
the retained direct PID and still awaits its Tauri termination event. Abrupt
pre-bound and post-ready faults use `abort()` (so Rust `Drop` cleanup does not
run); after observing the direct-child exit, the host terminates and audits the
residual canary group.

All control frames are NDJSON protocol version 1 and capped at 4,096 bytes. The
canonical `bound` frame carries sequence 1, direct-child PID, PGID, same-group
canary PID, literal host `127.0.0.1`, and the nonzero kernel-selected port. The
host rejects malformed JSON, PID/PGID mismatches, zero ports, `0.0.0.0`, and
`::`. Readiness uses a monotonic 1,500 ms fixture deadline and retries only
transport-unavailable or explicit `starting` responses; malformed responses are
terminal contract failures.

The startup capability contains 256 random bits and the redaction canary prefix.
It is sent only in the bounded stdin bootstrap and shutdown frames. The sidecar
environment is cleared and receives only `ARXMCP_SPIKE_DATA_DIR`; argv contains
only the target-triple executable path. Both the host and external harness scan
raw stdout/stderr with cross-event tails, persisted fixture files, event
records, and live `ps eww` output without printing the secret. Failed or partial
`ps`/`lsof` probes are evidence failures, never clean absence.

## macOS primitives exercised

- Tauri 2 shell sidecar resolved as
  `fixture-sidecar-aarch64-apple-darwin` beside the real host executable.
- `flock`-style `fs2` advisory locking selected one supervisor during the
  measured simultaneous-launch race before either host could own a sidecar.
- `setpgid(0, 0)` made the fixture its own process-group leader; its canary
  inherited that PGID.
- Positive-PID `kill(pid, SIGTERM)` closed the measured pre-`setpgid` startup
  timeout when negative-PGID signalling correctly returned `ESRCH`.
- `kill(-pgid, SIGTERM)` and `kill(-pgid, SIGKILL)` enforced bounded group
  cleanup; the Tauri termination event proved the direct child was waited.
- Closing the inherited stdin pipe acted as the parent-lifetime lease. A real
  supervisor `SIGKILL` closed the lease and the cooperative fixture stopped its
  listener and waited its canary.
- `/usr/sbin/lsof`, `ps`, PID/executable identity, PGID membership, and a TCP
  connect attempt independently audited post-run cleanup.

## Versions and reproducible commands

- Rust: `rustc 1.93.0 (254b59607 2026-01-19)`; LLVM 21.1.8
- Cargo: `cargo 1.93.0 (083ac5135 2025-12-15)`
- Tauri: exactly 2.11.5
- `tauri-plugin-shell`: exactly 2.3.5
- `tauri-plugin-single-instance`: exactly 2.4.3
- Host binary SHA-256:
  `af33e3baef1c354f6c5676262d20ac7ec3ef32378454b50e0ce453a9c7ab6464`
- Fixture binary SHA-256:
  `cd2019f17c6d1b91d550f9f95d6510266a1717430b0d285dc426f964848f30ce`
- Tracked-source SHA-256 embedded in both binaries:
  `484fdb957b2bb26a49b95dea32a8d093747b6ff179e0938f8af49a8403120912`

```bash
cargo test --locked --target-dir /private/tmp/arxmcp-spike3-target \
  --manifest-path tools/desktop_lifecycle_spike/Cargo.toml
cargo clippy --locked --target-dir /private/tmp/arxmcp-spike3-target \
  --manifest-path tools/desktop_lifecycle_spike/Cargo.toml \
  --all-targets -- -D warnings
cargo build --locked --target-dir /private/tmp/arxmcp-spike3-target \
  --manifest-path tools/desktop_lifecycle_spike/Cargo.toml --bins
.venv/bin/python tools/desktop_lifecycle_spike/run_spike.py \
  --host /private/tmp/arxmcp-spike3-target/debug/lifecycle-host \
  --fixture /private/tmp/arxmcp-spike3-target/debug/fixture-sidecar \
  --output .claude/notes/milestones/desktop-distribution-spike-3/implement/lifecycle-results.json \
  --scratch /private/tmp/arxmcp-spike3-scratch --cycles 30
```

The live audit used `/usr/sbin/lsof -nP -iTCP:<port> -sTCP:LISTEN`,
`ps -axo pid=,pgid=,comm=`, `ps eww -p <pids> -o pid=,command=`, and a loopback
TCP connection after each scenario.

## Fault matrix and measurements

All eleven cases passed: normal shutdown, duplicate launch, startup timeout,
malformed bound frame, IPv4 wildcard announcement, IPv6 wildcard announcement,
never-ready, crash before bound, crash after readiness, ignored shutdown with
TERM-to-KILL escalation, and parent `SIGKILL` with stdin-EOF cleanup.

Thirty additional fresh launch → ready → graceful-stop cycles passed. Latency
was 383.352 ms minimum, 397.257 ms mean, and 408.178 ms maximum. Across the fault
matrix and all cycles, the exact totals were:

- orphan process groups: **0**
- residual listeners or successful post-stop connects: **0**
- secret scan failures: **0**

The normalized per-case evidence, latencies, audit booleans, binary digests, and
raw-result digests are committed in
`implement/lifecycle-results.json`. Ephemeral raw streams and run roots were
digested in memory and removed; no binary, raw log, credential, model data, or
Cargo target output is committed.

## Limitations and non-claims

- This proves a purpose-built fixture protocol, not the production Python
  server. Production port-zero support, endpoint publication, and desktop
  integration remain m3/m4 work.
- The production protocol reserves 35,000 ms for drain and shutdown. The fixture
  uses a 350 ms shutdown grace to keep the fault matrix bounded.
- Parent `SIGKILL` cleanup is proven only for a cooperating child that observes
  stdin EOF. A wedged child cannot be killed by a parent that no longer exists.
- Process-group cleanup does not cover a descendant that deliberately calls
  `setsid()`; that MinerU-style escape remains an explicit non-claim.
- Fixture stdout is the control stream. Production must choose a dedicated
  descriptor or explicit desktop logging mode.
- The run proves macOS 26.6 on arm64, not the planned macOS 14 support floor.
- Tauri's activation callback did not fire in the simultaneous-start run; the
  production design must retain the native supervisor lock and treat the plugin
  as a UX activation path rather than its sole ownership primitive.
- No app bundle, signing, notarization, automatic restart, real server changes,
  or PyInstaller integration was attempted.

The spike leaves the MCP schema, prompt/cache hashes, loopback-only server
boundary, PyInstaller onedir decision, centralized application-data root, and
the no-SPA/no-Node-build-chain constraints unchanged.
