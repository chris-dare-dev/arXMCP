# Desktop distribution spike 3 — lifecycle ownership

**Decision:** GO — use the pinned Tauri shell handle as the direct-sidecar
guardian for the production desktop implementation.

**Measured on:** macOS 26.6, Apple Silicon (`aarch64-apple-darwin`)

**Raw-result digest:**
`63a96d6dbe98ff4df0711a77ebe1fa493ee8eabdf68c3e7be983baf05dab8964`

## Decision record

The built no-window Tauri host retained the shell plugin's stdin writer, exposed
the direct-child PID, delivered raw bounded stdout/stderr events, and delivered a
termination event after both cooperative and signalled exits. These primitives
are sufficient for the direct-child contract, so the native Rust guardian
fallback is not selected.

The single-instance plugin is registered before the shell plugin and before the
setup callback. A raced second launch was routed to the first process, produced
one activation callback, and the shared event record contained exactly one
`sidecar_spawned` transition. The fixture's advisory lock remains a second guard
beneath the application-data root.

## Lifecycle and frame contract

The host serializes one lifecycle actor through these measured transitions:

1. `lifecycle_started` → `sidecar_spawned`
2. bounded stdin `init` frame → `bootstrap_sent`
3. bounded stdout `bound` frame → `bound_validated`
4. exact `/healthz` → authenticated `/readyz` → `ready_authenticated`
5. authenticated stdin `shutdown` → bounded wait → `sidecar_reaped`
6. on expiry: process-group `SIGTERM` → bounded wait → process-group
   `SIGKILL` → direct-child termination event/reap

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
raw stdout/stderr, persisted fixture files, event records, and live `ps eww`
output without printing the secret.

## macOS primitives exercised

- Tauri 2 shell sidecar resolved as
  `fixture-sidecar-aarch64-apple-darwin` beside the real host executable.
- `setpgid(0, 0)` made the fixture its own process-group leader; its canary
  inherited that PGID.
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
  `24ae008caa9d715e47a351f2786c31268941a9faf516a4fe46714e381cd722bc`
- Fixture binary SHA-256:
  `8d8b45ebc976bfa2d9a6b776210a26a9ca1629a872f932f39296027aee8824b7`

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
`ps -axo pid=,pgid=,comm=`, `ps eww -p <pids> -o command=`, and a loopback TCP
connection after each scenario.

## Fault matrix and measurements

All eleven cases passed: normal shutdown, duplicate launch, startup timeout,
malformed bound frame, IPv4 wildcard announcement, IPv6 wildcard announcement,
never-ready, crash before bound, crash after readiness, ignored shutdown with
TERM-to-KILL escalation, and parent `SIGKILL` with stdin-EOF cleanup.

Thirty additional fresh launch → ready → graceful-stop cycles passed. Latency
was 377.372 ms minimum, 390.912 ms mean, and 406.493 ms maximum. Across the fault
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
- No app bundle, signing, notarization, automatic restart, real server changes,
  or PyInstaller integration was attempted.

The spike leaves the MCP schema, prompt/cache hashes, loopback-only server
boundary, PyInstaller onedir decision, centralized application-data root, and
the no-SPA/no-Node-build-chain constraints unchanged.
