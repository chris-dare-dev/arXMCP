# Research synthesis — desktop-distribution-spike-3

## Decision

Build and run a pinned, no-window Tauri 2 host against a purpose-built Rust
fixture sidecar on this Apple Silicon Mac. The fixture, not the supervisor,
binds and retains `127.0.0.1:0`; it reports the kernel-selected endpoint over a
bounded NDJSON control stream. The supervisor sends the startup token only over
the child's stdin and keeps that pipe open as the lifetime lease.

Use Tauri's single-instance plugin as the desktop-process guard, registered
before sidecar setup. Use a second advisory lock beneath the application-data
root as the sidecar-instance guard. Normal termination is authenticated
shutdown followed by bounded wait/reap. Escalation is process-group `SIGTERM`,
then bounded `SIGKILL`, then reap. Supervisor `SIGKILL` is proven only for a
cooperating fixture that observes stdin EOF; macOS does not provide evidence
that a dead parent can kill an arbitrarily wedged child.

The spike is GO only if the real pinned Tauri host passes the lifecycle and
30-cycle gates. If Tauri's shell handle cannot retain stdin, expose a usable
PID, or support the required cleanup, retain Tauri for UI/single-instance
activation and select a small native Rust guardian using
`std::process::Command`, explicit pipes, wait/kill, and process groups. Do not
weaken the no-orphan contract.

## Acceptance criteria

1. Build and execute a real Tauri 2 host pinned to the exact versions exercised
   by the spike, with `Cargo.lock` committed and generated targets/bundles kept
   outside Git. Register the single-instance plugin before sidecar ownership;
   a raced duplicate launch creates no second sidecar or listener.
2. The fixture owns a retained `127.0.0.1:0` listener and announces a bounded,
   canonical `bound` frame. The host validates version, sequence, PID, port,
   and loopback address, then distinguishes `/healthz` from `/readyz` using a
   deterministic monotonic deadline. A malformed announcement and never-ready
   child are rejected and cleaned up.
3. Generate a 256-bit startup token and transmit it only in a bounded stdin
   bootstrap frame. It must be absent from argv, the allowlisted environment,
   stdout/stderr, persisted logs, and assertion output. It may be used for
   authenticated readiness and shutdown without being logged.
4. Exercise graceful shutdown, ignored shutdown followed by bounded forced
   termination, child crash before/after readiness, startup timeout, duplicate
   desktop launch, and supervisor `SIGKILL`. The fixture and its same-group
   canary must be waited/reaped; a descendant that deliberately calls
   `setsid()` remains an explicit non-claim.
5. After every scenario, require PID absence, empty fixture process group,
   failed TCP connection, and no `/usr/sbin/lsof` listener. Run 30 fresh
   launch → ready → graceful-stop cycles and record latency plus exact
   orphan/listener totals; GO requires `0/0`.
6. Record the lifecycle states/frames, macOS primitives, exact dependency and
   toolchain versions, commands, fault matrix, raw-result digest, limitations,
   GO/NO-GO, and fallback in
   `.claude/notes/spikes/desktop-distribution-spike-3.md`. Commit no generated
   binaries, raw logs, credentials, model data, or Cargo target output.
7. Preserve the existing MCP schema, prompt/cache hashes, loopback-only
   boundary, PyInstaller onedir decision, centralized application-data root,
   and no-SPA/no-Node-build-chain product constraints. Run every applicable
   Rust and Python repository gate.

These criteria trace to the inline milestone brief sourced from the roadmap
spike at `plans/desktop-distribution-roadmap.md:169` and GitHub issue #386.

## Affected files

Expected source/evidence surface (the implementer may refine names without
widening scope):

- `tools/desktop_lifecycle_spike/Cargo.toml` and `Cargo.lock` — pinned isolated
  Rust/Tauri spike workspace.
- `tools/desktop_lifecycle_spike/build.rs`, `tauri.conf.json`, and minimal
  Tauri capability/config assets needed to run a no-window host with a bundled
  fixture sidecar.
- `tools/desktop_lifecycle_spike/src/main.rs` — serialized lifecycle actor,
  single-instance activation, framing, deadlines, token redaction, audit, and
  cleanup/fallback decision.
- `tools/desktop_lifecycle_spike/src/bin/fixture_sidecar.rs` — loopback-only
  fixture server, stdin lease, advisory lock, fault modes, and framed events.
- `tools/desktop_lifecycle_spike/tests/` and/or
  `tests/test_desktop_lifecycle_spike.py` — deterministic contract and
  repository-boundary guards; live macOS execution remains separately
  evidenced.
- `.claude/notes/spikes/desktop-distribution-spike-3.md` — durable ADR and
  measured evidence.
- `.claude/notes/milestones/desktop-distribution-spike-3/implement/synthesis.md`
  — implementation and check-gate record.

Production server integration, `apps/desktop/`, real dynamic-port support,
shim endpoint publication, signing/notarization, and automatic restart belong
to m3/m4 or spike 4 and are out of this timebox.

## Constraints and known risks

- `server/config.py` currently rejects port `0` and `server/cli.py` has no
  inherited-listener or bound-endpoint announcement seam. This spike proves
  the fixture protocol; it must not claim that the production server is ready.
- Tauri's direct-child kill does not prove descendant-tree cleanup. The fixture
  may use a process group and canary, but the MinerU-style `setsid()` escape is
  an explicit limitation.
- The production server drains in-flight requests for 30 seconds. Fixture
  timings may be shorter, but the protocol must reserve at least 35 seconds for
  the later production grace window.
- The host is macOS 26/Darwin 25 on arm64. A pass is not evidence for the
  planned macOS 14 support floor.
- Free disk is presently constrained. Generated Cargo/bundle outputs must use
  a unique temporary directory, be measured, and be removed after durable
  evidence is captured; do not delete unrelated caches or operator data.
- The stdout control channel is acceptable for the fixture only. m3 must choose
  a dedicated descriptor or explicit desktop logging mode for the real server.

## Open questions

1. Does the pinned Tauri shell API preserve the stdin writer and termination
   events needed for the lease and bounded reap?
2. Does the built macOS app enforce the single-instance callback under a raced
   duplicate launch, rather than only in mock/unit runtime?
3. Can Tauri meet process-group cleanup directly, or is the native Rust
   guardian the required production boundary?
4. What startup/stop distributions and exact orphan/listener totals result
   across the 30-cycle live run?

## Estimated implementation

Approximately 650–900 changed lines across 8–12 source, fixture, test, lock,
configuration, and evidence files. This is novel cross-language lifecycle
architecture, so Phase 2 uses the delegated path. The estimate may exceed the
default 800-line abort; the implementer must honor the mid-flight scope guard
and stop for explicit `--allow-large-diff` authorization if reached.

## External writes required

- `git push origin main`

Dependency downloads needed to build the pinned temporary Tauri workspace are
read-only network prerequisites, not external mutations. No package publish,
Apple credential use, notarization, deployment, or GitHub issue mutation is
required by implementation.
