---
milestone_id: "desktop-distribution-spike-3"
researcher_role: "general"
generated: "2026-08-06T22:02:41Z"
external_writes_required:
  - "git push origin main"
sources:
  - url: "https://v2.tauri.app/develop/sidecar/"
    sha256: "f5e8c5d356a2f88900214ac3cef4e429a4b0c1f68cf25b66d31b64f616c6f316"
    takeaway: "Tauri 2 bundles target-triple sidecars and its Rust API returns both a child handle and an event receiver."
  - url: "https://docs.rs/crate/tauri-plugin-shell/2.3.5/source/src/process/mod.rs"
    sha256: "a16eaa5b4deaa36282033298457f067c7881cafe983b2efe2d42a4687943b824"
    takeaway: "The pinned plugin exposes piped stdin, stdout/stderr and termination events plus PID and direct-child kill operations."
  - url: "https://docs.rs/crate/tauri-plugin-single-instance/2.4.3"
    sha256: "1929e69253d1e8010d68395ba3736812729a70a0eea306a8a1a9808b316df1e2"
    takeaway: "The plugin supports macOS, reports duplicate argv/cwd to the primary instance, and must be registered first."
  - url: "https://docs.rs/tauri/2.11.5/tauri/struct.App.html"
    sha256: "1603ac8a6018ed74f649776b2ced69d32be12b35603ea2e03ba7fe731643f89b"
    takeaway: "Tauri App::run exits the process directly, so lifecycle safety cannot depend on Rust destructors."
  - url: "https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/pipe.2.html"
    sha256: "bf4f54be34e25547bb986ea2cf22bb416b9353e2bc6406ef8761572e45017279"
    takeaway: "macOS closes a crashed process's descriptors and a pipe reader observes EOF after every writer is closed."
  - url: "https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/kqueue.2.html"
    sha256: "89581e15d32ad4f9303241a39d5d8e63fd0fd88e4ea446a0d630c958d65c73ef"
    takeaway: "EVFILT_PROC with NOTE_EXIT can corroborate parent-process death on macOS, but is a fallback rather than the primary lease."
injection_attempts: 0
---

# Research brief (general) — desktop-distribution-spike-3

## External sources

Use an actual Tauri 2 backend, pinned for the spike to `tauri==2.11.5`,
`tauri-plugin-shell==2.3.5`, and `tauri-plugin-single-instance==2.4.3`, with
`Cargo.lock` committed and builds run `--locked`. Tauri's sidecar API supplies
the primitives needed here: a `CommandChild` with PID, stdin writer, and
direct-child `kill`, plus streamed stdout/stderr/error/termination events. Keep
all lifecycle authority in Rust; expose no shell commands or permissions to the
webview. Register the single-instance plugin first, as its own documentation
requires, and treat its callback only as activation of the existing primary.
Never log or retain the duplicate process's raw argv or cwd.

Apple's `pipe(2)` semantics make the inherited stdin pipe the simplest macOS
parent-liveness lease: when the supervisor is killed, the kernel closes its
only write descriptor and a cooperating child observes EOF. `kqueue(2)`
`EVFILT_PROC/NOTE_EXIT` is a useful macOS corroboration or native-supervisor
fallback, but the pipe is simpler and portable. Neither mechanism lets an
already-dead supervisor force-kill an arbitrarily wedged child; the spike can
prove cooperative child cleanup, not that stronger guarantee.

## In-codebase context and prior decisions

The constitution requires: “One long-running Streamable HTTP MCP server bound
to `127.0.0.1`” (`.claude/notes/02-architecture-overview.md:20`) and “One
ingestion pipeline, one storage layer, one MCP server process”
(`.claude/notes/01-mission-and-context.md:136`). It also says “Local-first. No
paid cloud services in the critical path” (line 139) and “Every byte the MCP
server returns must be reproducible bit-for-bit across calls” (line 133).
Accordingly, an ephemeral desktop port is runtime transport state, never MCP
result data; this spike must not change a tool schema, prompt, cache key, or
their pinned hashes. The loopback-only rule is restated at
`.claude/notes/06-mcp-server-design.md:537`.

Spike 1 already chose a provisional PyInstaller `onedir` sidecar launched
directly with no ambient Python; spike 2 chose one desktop-owned data root.
Preserve both decisions. This milestone is only a fixture and protocol proof,
not production server integration, packaging, signing, notarization, or a
second server implementation. Put Rust fixture/spike source under a non-
Markdown `tools/` subtree, generated targets and run artifacts under a unique
`/private/tmp` directory, and the durable decision/evidence under
`.claude/notes/spikes/desktop-distribution-spike-3.md`. Do not add Node/npm or a
frontend build chain.

- **BRIEF/CODEBASE CONFLICT:** the real server cannot currently perform safe
  child-owned dynamic binding. `server/config.py:825-838` rejects port `0`,
  while `server/cli.py:208-215` hands a fixed port to `uvicorn.run` and has no
  bound-port announcement channel. Do not “find” a free port in the supervisor,
  close it, then ask the child to rebind it; that is a TOCTOU race. Prove
  child-bound `127.0.0.1:0` with the fixture and leave the production seam to
  desktop milestones m3/m4.

- The production shutdown contract drains requests for 30 seconds before
  closing stores (`.claude/notes/06-mcp-server-design.md:487`). The eventual
  supervisor grace window must therefore be at least 35 seconds before a hard
  kill; use proportionally shortened, explicit fixture timing only in this
  spike.

## Executable spike design

Recommendation: **conditional GO**. Build a minimal no-window Tauri app and a
direct fixture sidecar around one serialized Rust lifecycle actor with states
`Idle -> Starting -> Ready -> Stopping -> Exited|Failed`. The actor alone owns
the `CommandChild`, event receiver, token, timers, and transition log. Do not
auto-restart: crash evidence and exactly-one accounting must stay deterministic.

Use two independent exactly-one guards. First, the Tauri single-instance plugin
prevents a duplicate desktop process from reaching setup; its callback records
a public activation counter and raises the primary window if one exists.
Second, the sidecar itself takes a non-blocking exclusive advisory lock under
`ARXMCP_DATA_DIR` before binding, and holds the open descriptor for its entire
life. Test lock ownership, not lock-file existence: macOS releases the lock on
process death, so stale pathnames are harmless and immediate relaunch cannot
overlap a still-exiting orphan.

The parent generates a 256-bit startup token. Clear the child's environment and
allowlist only non-secret values such as the data-root path. Put neither token
nor endpoint in argv; send a bounded, canonical NDJSON bootstrap frame over
stdin. Keep the sole stdin writer inside the lifecycle actor. The child acquires
the lease, binds exactly `127.0.0.1:0`, learns the kernel-selected port, and
emits one bounded newline-delimited `bound` frame on stdout containing protocol
version, monotonic sequence, PID, and port—but no token. Reserve fixture stdout
for protocol frames and stderr for redacted structured diagnostics. The parent
buffers byte-stream events into size-capped lines and rejects malformed,
duplicate, out-of-order, non-loopback, or wrong-PID announcements.

After `bound`, poll the exact loopback `/readyz` endpoint on a fixed monotonic
schedule until a fixed deadline, requiring the expected JSON readiness state,
not merely HTTP 200. Authenticate fixture readiness and shutdown control with
the startup token in a non-logged header/frame. On ordinary Tauri
`ExitRequested`, call `prevent_exit`, write authenticated `shutdown`, await a
termination event, then request final exit with a recursion guard. Do not rely
on `Drop`: Tauri documents that `App::run` ultimately uses
`std::process::exit`. On timeout, consume the direct-child kill handle, await a
bounded termination/reap event, and independently verify process and listener
absence.

The child runs a dedicated stdin reader. A clean shutdown frame closes its
listener and exits; EOF is treated identically, proving cleanup after supervisor
`SIGKILL` so long as no duplicate writer descriptor exists. Keep the fixture a
single direct listener process: Tauri's kill handle does not prove process-tree
cleanup. For each run, record public run ID, transition sequence, PID, port,
latencies, exit mode/code, and postcondition checks. Plant a known token canary
and scan `ps -o command=`, captured stdout/stderr, and persisted logs for it.

If any Tauri gate fails, retain Tauri for UI/single-instance activation but move
child ownership to a small native Rust supervisor/watchdog using
`std::process::Command`, explicit pipes, wait/kill, and a process group, with
pipe EOF plus macOS `kqueue` parent watching. Future platforms can substitute a
Windows Job Object or Linux parent-death/cgroup adapter. If that design still
cannot meet the bounded no-orphan postcondition, record **NO-GO** rather than
weakening it; a `launchd`-owned service is a different ownership model and needs
a later architecture decision.

## Acceptance criteria the implementer must meet

1. Run a real pinned Tauri app and target-triple fixture sidecar without Node,
   demonstrating backend spawn/events and primary-instance activation on a
   duplicate launch; the duplicate creates no second child or listener.
2. Demonstrate child-owned `127.0.0.1:0` binding, validated `bound` framing, and
   deterministic deadline-based `/readyz` polling; cover malformed announcement
   and never-ready timeout cleanup.
3. Demonstrate authenticated graceful shutdown, ignore-shutdown then bounded
   forced kill, spontaneous child crash, and Tauri termination-state handling.
4. Kill the supervisor with `SIGKILL`; show stdin EOF makes the child close its
   listener, then immediately relaunch and reacquire the advisory lease.
5. Complete 30 sequential ready/stop cycles. After every scenario and cycle,
   define one bounded audit deadline and record zero matching live process
   identities and zero TCP listeners using both PID/executable inspection and
   `/usr/sbin/lsof -nP` plus a port connection probe.
6. Prove the token canary is absent from argv, environment-derived diagnostics,
   protocol output, and persisted logs; reject every non-loopback bind or
   announcement before readiness.
7. Record versions, commands, raw per-run results, aggregate orphan/listener
   counts, lifecycle state/protocol, macOS primitives, limitations, and the
   fallback decision in the `.claude/notes/spikes/` ADR. A GO requires all
   deterministic gates; otherwise record NO-GO and the failing evidence.

## Risks and open questions

1. **Parent-crash ceiling:** pipe EOF proves cleanup only for a responsive
   fixture. macOS offers no demonstrated kernel primitive here that lets a dead
   supervisor kill a totally wedged child. State this boundary in the ADR.
2. `CommandChild::kill` targets the direct child, not descendants. The fixture
   must spawn none; production subprocess-tree policy remains an m3/m4 concern.
3. The real server's port-zero and announcement seam is unresolved by design in
   this timebox; m3 must choose socket inheritance or add child-owned bind/report.
4. macOS single-instance behavior must be tested from the built app/binary, not
   inferred from unit tests; record exact invocation and callback count.

## External writes the implementation will require

- `{type: git push, target: origin/main, why: publish the completed milestone commits}`

No PR, issue mutation, package publication, Apple notarization, infrastructure
change, or third-party API write is required for this local fixture spike.
