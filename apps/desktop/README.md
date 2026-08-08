# arXMCP desktop workspace

This directory is the production desktop boundary for arXMCP. It contains a
platform-neutral Rust contract crate, a model-free fixture sidecar, the
production Tauri shell (`crates/supervisor`), and the server lifecycle adapter
that shell drives (`server/desktop_child.py`). The frozen Python runtime,
release signing, and launch-plan authoring are not here yet; those belong to
the next desktop milestones.

## Supported boundary

macOS 14 or newer on Apple Silicon is the first release target. Linux x86-64
and Windows x86-64 are portability targets for the same workspace and wire
protocol, but are not release-supported until their packaging, process-control,
and signing gates land. The protocol uses platform-neutral grace/force/reap
semantics; a later adapter maps those to Unix process groups or Windows process
objects.

macOS is a target, not a fork. All platforms share `desktop-contract`, the
fixture bytes, sidecar identity rules, and lifecycle state machine. Platform
code may implement process and packaging primitives, but it may not create a
macOS-only server protocol or a second application-data layout. Python's
`server.application_paths.ApplicationPaths` remains the sole owner of the
internal data layout; the supervisor passes one canonical root.

This workspace deliberately has no Node/npm build chain. The future desktop
shell will continue to use the existing server-rendered operator console.

## Development and conformance commands

Run these commands from the repository root. A temporary Cargo target keeps
generated binaries out of the source tree.

```bash
make desktop-conformance PYTHON=.venv/bin/python
cargo fmt --all --manifest-path apps/desktop/Cargo.toml -- --check
cargo test --locked --manifest-path apps/desktop/Cargo.toml \
  --target-dir /private/tmp/arxmcp-desktop-target
cargo clippy --locked --manifest-path apps/desktop/Cargo.toml \
  --target-dir /private/tmp/arxmcp-desktop-target \
  --workspace --all-targets --all-features -- -D warnings
cargo build --locked --manifest-path apps/desktop/Cargo.toml \
  --target-dir /private/tmp/arxmcp-desktop-target \
  --bin fixture-sidecar
cargo build --locked --manifest-path apps/desktop/Cargo.toml \
  --target-dir /private/tmp/arxmcp-desktop-target \
  --bin supervisor
ARXMCP_FIXTURE_SIDECAR=/private/tmp/arxmcp-desktop-target/debug/fixture-sidecar \
  .venv/bin/python -m pytest tests/test_desktop_contract.py
DESKTOP_SUPERVISOR_BIN=/private/tmp/arxmcp-desktop-target/debug/supervisor \
  .venv/bin/python -m pytest tests/test_desktop_child.py \
  -m "requires_desktop_stack or not requires_desktop_stack"
make wheel-check PYTHON=.venv/bin/python
make test PYTHON=.venv/bin/python
```

`make desktop-conformance` is the mandatory combined boundary gate: it performs
both locked binary builds before the live Python process suites, so lifecycle
evidence cannot silently degrade to skipped tests in a clean checkout. The
expanded commands below it are useful when diagnosing one layer independently.
`DESKTOP_SUPERVISOR_BIN` is deliberately not `ARXMCP_`-prefixed — the real-child
tests import `server.main`, whose unknown-`ARXMCP_*` scan would FATAL on a
harness-only variable. Any skipped test in a run that sets it fails the session.

On Windows, use the target directory appropriate to the shell and point
`ARXMCP_FIXTURE_SIDECAR` at `fixture-sidecar.exe`. The Cargo commands remain
locked. `make` on the supported macOS development path runs through the
project's Python 3.12 virtual environment as shown.

## Versioned control protocol

The supervisor and child exchange at most 4,096 bytes per frame as UTF-8
NDJSON. Every frame has recursively sorted object keys, compact separators,
input-order arrays, JSON-safe integers, no floats, and exactly one trailing LF.
Duplicate keys are rejected. The streams have one owner each:

- retained child stdin carries `launch`, then an optional authenticated
  `shutdown`; closing stdin is the parent-lifetime lease;
- child stdout is control-only and emits exactly one token-free `bound` frame;
- child stderr contains redacted operational diagnostics and is the only stream
  the supervisor may persist at the declared log location.

The v1 `launch` frame carries the integer contract version, supervisor-expected
logical component/version/SHA-256 identity, canonical data root, request for
`127.0.0.1:0`, fixed probe paths, canonical log location, shutdown semantics,
and a startup capability. The child retains the port-zero listener and emits a
`bound` frame with the actual nonzero loopback port and URLs derived from that
single authority. Four independently supplied URLs are never trusted. The
sidecar hashes its own executable before binding, compares that digest with the
launch identity, and reports the computed value rather than reflecting input.

Paths are platform-neutral wire strings, not host-language path objects. They
use `/` separators and are either POSIX absolute (`/var/...`) or uppercase,
drive-qualified Windows absolute (`C:/Users/...`). Empty, `.`, and `..`
segments, repeated or trailing separators, backslashes, and ASCII controls are
rejected identically by Rust and Python. The runtime adapter alone converts a
validated wire path to the native filesystem representation.

Readers reject any major other than 1 before lifecycle side effects. They
accept any same-major minor while still requiring every v1 field. Core objects
are strict: compatible additions are allowed only under `extensions`, whose
top-level ASCII keys must be namespaced (for example,
`org.arxmcp.future`). Nested extension objects retain ordinary JSON key
semantics; only their values remain subject to the shared depth and safe-number
bounds. This catches misspelled security fields without turning a minor
addition into a breaking change.

Shutdown reserves at least 35,000 ms for cooperative server drain. The wire
contract then names a bounded force deadline, the stdin-EOF lifetime lease, and
the graceful/force/reap guarantee without encoding Unix signal names. M3 proves
these contract semantics with the fixture. M5 delivered production port-zero
adoption, authenticated server readiness, and ordinary Tauri exit handling
against the real server: the child imposes its OWN drain deadline (half of the
launch frame's `grace_ms`) so the FastAPI lifespan shutdown — which closes the
LanceDB and Kuzu handles — always runs strictly inside the supervisor's grace
window instead of being cut short by a force kill.

## Fault matrix and cleanup claims (m6)

M6 drives the REAL supervisor (`lifecycle.rs`) against fault-injected fixture
arms selected by the `org.arxmcp.test-fault` launch extension — the contract's
sanctioned compatible-addition channel, read only by the fixture sidecar and
never by `server/desktop_child.py`. Covered: startup timeout, malformed
`bound` (whose persisted diagnostic is scrubbed by `supervisor/src/redact.rs`
before it is written), crash before bound, crash after ready, ignored shutdown
with the full grace/TERM/KILL/reap escalation, and supervisor SIGKILL. A
30-cycle stress run proves 30 distinct PIDs with zero residual processes or
listeners, and loopback is asserted at socket level against the live port. All
evidence probes assert their own success: a failed or partial `ps`/`lsof` is an
evidence failure, never clean absence.

Two spike-3 non-claims REMAIN non-claims — a passing fault matrix here is not
universal cleanup:

- **A parent that no longer exists cannot kill a wedged child.** Supervisor
  SIGKILL cleanup is proven only for a cooperating child that is alive and
  observing stdin EOF; a child parked in uninterruptible I/O (for example a
  stalled LanceDB/Kuzu read) would outlive its dead parent.
- **Process-group escape is not applicable, not handled.** The supervisor
  signals only the direct child PID — never a process group — and neither the
  production child nor the fixture spawns descendants today, so a
  `setsid()`-style escape cannot occur. A future milestone that adds a
  subprocess-spawning child must re-open this design before shipping it.

## Secret handling

A live startup token is 32 bytes from the operating-system CSPRNG, hex encoded
in memory. It is accepted only in the bounded stdin `launch` and `shutdown`
frames and in the `X-ArXMCP-Startup-Token` readiness header. It is never an
argument, environment variable, URL/query value, `bound` field, object
representation, exception detail, stdout/stderr diagnostic, or persisted
manifest/log artifact. The fixture sidecar accepts no command-line arguments.

The all-zero token committed in `contract-fixtures/` is conspicuously nonsecret
test data. It must never be generated for, or accepted as evidence of, a live
production capability. Process tests generate a fresh capability and scan the
control output, child arguments/environment, URLs, stderr log, and runtime tree
for its absence.

## Shared fixtures

Rust and Python both consume every `.jsonl` file in `contract-fixtures/` and
re-emit positive frames byte for byte. The set covers the v1 exchange, Unicode
and spaces in POSIX and Windows paths, a compatible future minor extension, an
incompatible major, duplicate and unknown core fields, wildcard binding,
mismatched URL authority, invalid executable identity, and an oversized frame.

`fixtures.sha256` pins one aggregate SHA-256. Its input is each `.jsonl` file in
lexicographic filename order, encoded as `UTF-8 filename`, one NUL byte, then
the exact file bytes. Adding or changing a fixture requires an intentional
digest update that must pass independently in both languages.

`redaction-vectors.jsonl` (m6) pins the redaction scrub the same way: the Rust
production scrubber (`supervisor/src/redact.rs`) and the Python parity test
consume the same vectors, so exact-match `[REDACTED]` replacement — including
the deliberate NON-redaction of partial and case-shifted near-misses — cannot
drift between languages.

The fixture sidecar imports neither Python nor any model, corpus, LanceDB, or
MCP-server module. It owns `127.0.0.1:0`, serves unauthenticated `/healthz` and
capability-authenticated `/readyz`, ignores invalid shutdown capabilities, and
exits on a valid shutdown frame or stdin EOF.
