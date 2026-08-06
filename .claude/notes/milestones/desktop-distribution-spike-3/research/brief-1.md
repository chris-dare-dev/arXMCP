---
milestone_id: "desktop-distribution-spike-3"
researcher_role: "explore"
injection_attempts: 0
---

# Research Brief — desktop-distribution-spike-3

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-08-06T21:58:09Z

## In-codebase context

This spike should return **GO only if a real Tauri 2 host proves ownership of a
fixture sidecar through every normal and crash path; `Child.kill()` on ordinary
app exit is not sufficient evidence.**

Load-bearing constitution constraints:

- `01-mission-and-context.md:136-140`: **“Single source of truth for the corpus.
  One ingestion pipeline, one storage layer, one MCP server process.”** and
  **“Local-first. No paid cloud services in the critical path.”**
- `02-architecture-overview.md:18-22,82-84`: **“One long-running Streamable HTTP
  MCP server”** bound to `127.0.0.1`; four client-owned processes would defeat
  shared models, indices, and caches.
- `06-mcp-server-design.md:340-345,487-500`: `/healthz` and `/readyz` are distinct;
  real shutdown must **“drain in-flight requests with a 30-second deadline”**;
  the existing loopback-only Jinja2+htmx console is **“NOT an SPA”** and retains
  its no-Node-build-chain product boundary. A Rust desktop build does not
  authorize a UI rewrite.
- `08-security-observability-ops.md:3-7,203-215`: the threat is local untrusted
  input; logs are structured and sensitive fields stay out of INFO+. The desktop
  protocol must keep the startup token out of argv and all log/control diagnostics.

- **CONFLICT — the real server cannot yet accept a race-free dynamic port.**
  `server/config.py:825-838` rejects port `0`, while `server/cli.py:208-215` passes
  only a numeric host/port to Uvicorn and exposes no inherited-listener or bound-
  endpoint channel. Selecting a free port by bind → close → child bind has a TOCTOU
  race. The fixture can prove a protocol, but the ADR must make the later production
  seam explicit rather than claim the real server is ready.
- **CONFLICT — normal Tauri cleanup cannot by itself satisfy supervisor-crash
  cleanup.** macOS has no Linux-style parent-death signal. A `finally`/exit callback
  cannot run after `SIGKILL`; the child therefore needs an OS-backed lifetime lease
  whose EOF is caused by supervisor death, or a separate guardian fallback.

No MCP tool or prompt changes belong in this spike: do not re-pin
`EXPECTED_TOOL_SCHEMA_SHA256`, BP1, or BP2. Preserve `kuzu==0.11.3`, canonical
`index/kuzu/`, and `tests/conftest.py`'s load-bearing
`KMP_DUPLICATE_LIB_OK=TRUE` macOS guard. Do not introduce invariant `assert`,
`BaseHTTPMiddleware`, a runtime `anthropic` SDK, or forked `arxiv-mcp` code.

## Affected files / context

- There is no tracked Cargo/Tauri workspace or `cargo-tauri` command today. Keep
  the experiment disposable under a code-only path such as
  `tools/desktop_lifecycle_spike/`, with generated bundles/`target/` outside the
  repository; reserve the production `apps/desktop/` workspace for m3.
- Reuse the environment allowlist in `tools/desktop_sidecar_spike.py:19-57`:
  force `127.0.0.1`, explicit data/cache/temp roots, offline flags, and no ambient
  Python/dynamic-loader variables. Do not extend its packaging probe into a second
  lifecycle implementation.
- `server/health.py:5-17,252-265` makes liveness-before-readiness intentional.
  The fixture must model both states and startup timeout, not expose one generic
  “ready” bit.
- `server/main.py:650-677` gives real resource shutdown a 30-second budget.
  Fixture bounds may be shorter, but the protocol must carry a production grace
  deadline of at least 30 seconds plus supervisor margin before force-kill.
- `tools/wheel_install_check.py:827-835` terminates/kills only the direct child.
  `tools/arxiv_fetch.py:700-741` is the stronger precedent: new session/process
  group, group kill, bounded pipe drain, and reap. The known MinerU grandchild can
  escape by creating its own session, so do not overclaim arbitrary descendant
  containment.
- `tests/test_server_startup.py:777-840` covers `EADDRINUSE`, not instance
  ownership. `shim/arxmcp_shim.py:64-99,162-167` still defaults to port 7733;
  m3/m4 must later publish the dynamic endpoint to shim registration without
  putting the startup secret in its `--server` argument.

## Prior decisions and lessons

Spike 1 chose a relocatable PyInstaller onedir sidecar (`ddd1d50`, rectified by
`0180e72`); m1/m2 then centralized paths and proved installed-wheel confinement
(`1b8385f`, `3e2dd21`, rectified through `edfc05a`). Use one explicit temporary
application-data root and do not reopen either packaging or path design.

Current host evidence is macOS 26.6 / Darwin 25.6 on arm64, Rust/Cargo 1.93, Node
25, and npm 11. No Tauri plugin is vendored and the shell/single-instance crates
are not locally cached, so pin exact versions and commit `Cargo.lock`; dependency
resolution may require network access. A pass on this host is not evidence for
the roadmap's macOS 14 support floor—record that limit in the ADR.

## External sources

None — role `explore` was repository-only. The implementation must capture the
exact Tauri/core/plugin versions it actually runs instead of relying on an
unpinned API recollection.

## Acceptance criteria the implementer must meet

1. Build a minimal Tauri 2 host with the single-instance plugin registered before
   any spawn. Race two concurrent launches; the second activates the first or exits,
   and evidence shows exactly one sidecar PID/process group and one listener.
2. Have the fixture bind and retain `127.0.0.1:0`, then emit the kernel-assigned
   endpoint in a framed control message. Prove `/healthz` precedes `/readyz` and
   enforce bounded startup timeout. Never use bind-close-rebind port selection.
3. Send a unique startup token through child stdin/private pipe, never argv or
   environment; keep that writer open as the lifetime lease. Scan `ps` command
   output, captured stdout/stderr, and every generated log for the token without
   printing it in assertion failures. Verify the child owns no wildcard or IPv6-
   wildcard listener.
4. Exercise graceful authenticated shutdown, hung shutdown → `SIGTERM` → bounded
   `SIGKILL`, child crash before and after readiness, and supervisor `SIGKILL` from
   an external harness. Put the fixture and same-group grandchild canary in a
   distinct process group; always wait/reap.
5. After every path, require PID absence, empty process group, failed TCP connect,
   and empty `lsof -nP -iTCP:<port> -sTCP:LISTEN`. Run 30 fresh launch → ready →
   graceful-stop cycles and record startup/stop latency plus exact orphan/listener
   totals (required result: 0/0).
6. Commit only source/tests and `.claude/notes/spikes/desktop-distribution-spike-3.md`.
   The ADR records protocol frames/state machine, macOS primitives, exact versions,
   fault-matrix evidence, scope limits, GO/NO-GO, and fallback. Keep bundles, logs,
   raw measurements, sockets, and Cargo target output in temporary paths.

## Recommendation

Use **framed bidirectional stdio as both authenticated control channel and lifetime
lease**: supervisor sends `init{version, token, data_root}` and later
`shutdown{token}` on stdin; the fixture emits `bound`, `healthy`, `ready`, and
`stopped` frames on stdout while human logs go to stderr with token redaction. The
supervisor alone retains stdin's write end. A fixture watchdog blocks on stdin and
initiates shutdown on EOF, so an abrupt supervisor death has an OS-generated signal
that does not depend on Tauri callbacks. The fixture binds loopback port `0` itself,
eliminating the allocation race; readiness must also prove the expected per-launch
identity so a stale local listener cannot be mistaken for this child.

Make the sidecar create its own process group at entry. Normal stop is authenticated
command → bounded wait/reap; escalation is group `SIGTERM` → bounded wait → group
`SIGKILL` → reap. If Tauri's shell child API cannot preserve writable stdin,
observable PID, and group signaling, choose one fallback: a small cross-platform
Rust guardian spawned with `std::process::Command` inside the Tauri host. It owns the
pipe and process-group primitives; do not weaken the contract to direct-child kill.

## Risks and open questions

- A descendant that calls `setsid()` escapes the process group; scope the result to
  the fixture/server group and record the existing MinerU exception separately.
- Pipe EOF is reliable only if no descendant inherits a duplicate write end; set
  close-on-exec and verify this with the grandchild canary.
- Logs and control frames sharing stdout would violate the current logging shape in
  real integration; this spike may reserve fixture stdout, but m3 must select a
  dedicated FD or an explicit desktop logging mode.
- No blocking open question: the experiment itself decides whether the Tauri shell
  API passes; failure selects the Rust guardian fallback above.

## External writes the implementation will require

| type | target | why |
|---|---|---|
| git push | `origin/main` | Publish spike source, tests, and ADR after per-event authorization. |
| GitHub issue mutation | `chris-dare-dev/arXMCP#386` | Link the lifecycle decision/evidence after explicit authorization. |
