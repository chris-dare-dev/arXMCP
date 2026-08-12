# arXMCP desktop workspace

This directory is the production desktop boundary for arXMCP. It contains a
platform-neutral Rust contract crate, a model-free fixture sidecar, the
production Tauri shell (`crates/supervisor`), the server lifecycle adapter
that shell drives (`server/desktop_child.py`), the frozen Python runtime
(`pyinstaller/`, m7), and launch-plan authoring (m10 — the supervisor derives
its own plan when `ARXMCP_DESKTOP_LAUNCH_PLAN` is absent, which is the shape a
double-clicked application has).

Still NOT here: `.app` bundle assembly (`bundle.active` is `false` and no
`resources`/`externalBin` is wired, so there is no double-clickable artifact
yet — that is `desktop-distribution-m15`) and release signing/notarization
(blocked on an Apple Developer ID certificate this project does not have).

The bundle-assembly decision itself is recorded, ahead of the assembly diff, in
[`.claude/docs/adr-desktop-bundle-assembly.md`](../../.claude/docs/adr-desktop-bundle-assembly.md)
(Proposed). It also records, with its sources, why the notarization question
cannot be answered here and what a build-and-submit trial would have to submit
to answer it.

## Child payload layout and its trust assumption

The self-authoring arm looks for m7's onedir as a **sibling of the supervisor
executable**:

    <supervisor dir>/arxmcp-desktop-child/arxmcp-desktop-child

`child_argv[0]` is resolved inside that root by canonicalizing both sides and
requiring component-wise containment, and the root itself is refused if it is
a symlink. The child's bytes are then checked against the plan's
`identity_file` digest before it is trusted.

**The assumption an operator needs to know:** write access to that sibling
directory is equivalent to arbitrary code execution as the operator. Nothing
in the supervisor can close that — the defenses are install-location
permissions and, when they land, m15's bundle layout plus e4's code signing.
`std::env::current_exe()`, which anchors the whole resolution, is documented
by the Rust stdlib as *not* a security primitive; the PATH-search and
hardlink classes it names carry no privilege gradient here (the supervisor is
not setuid/setgid) but are recorded as accepted residual risk rather than
closed.

m15 re-points the containment check at the bundle root — that is one of its
acceptance criteria, and this section is the input it should not have to
re-derive. Its ADR (linked above, Proposed) proposes placing the payload at
`Contents/MacOS/arxmcp-desktop-child/`, i.e. keeping this sibling relation
inside the bundle rather than replacing it; until the assembled artifact
exists and that resolution is measured against it, treat the layout here as
the pre-bundle one and the ADR as the decision record, not as a description of
a built artifact.

## Supported boundary

macOS 14 or newer on Apple Silicon is the first release target. Linux x86-64
and Windows x86-64 are portability targets for the same workspace and wire
protocol, but are not release-supported until their packaging, process-control,
and signing gates land. The protocol uses platform-neutral grace/force/reap
semantics; a later adapter maps those to Unix process groups or Windows process
objects.

The 14.0 floor is INHERITED and HARD, not chosen: `faiss_cpu 1.13.2` publishes
exactly one arm64 macOS wheel, tagged `macosx_14_0_arm64`, with no lower-tagged
arm64 fallback, and 132 of the 200 Mach-O files in the Python closure declare
minOS 14.0 (measured 2026-08-09). The floor is declared in three places that
must agree: `bundle.macOS.minimumSystemVersion` in
`crates/supervisor/tauri.conf.json` (without it, Tauri's bundler default would
advertise 10.13 — four majors below what the faiss wheel needs), the repo-root
`.cargo/config.toml` pin `MACOSX_DEPLOYMENT_TARGET = "14.0"` that makes both
Rust binaries report `minos 14.0`, and this section.
`tests/test_desktop_support_floor.py` fails if the three drift apart, if the
BUILT binaries report a `minos` other than 14.0 (read off the artifacts under
`make desktop-conformance`, because agreeing declarations are not an agreeing
artifact), or if a macOS 14 compatibility claim in one of the known
claim shapes lands in the shipped docs or in a user-visible string without a
recorded macOS 14 test run. That last check is a best-effort regex calibrated
against a corpus of claim and non-claim sentences, not a parser: it will miss a
phrasing nobody has written down yet, so it is a backstop for the honesty
discipline rather than a substitute for it.

The floor is UNVERIFIED. `minos` is a build-time declaration by whoever
compiled the object, not a runtime gate — dyld on the macOS 26.6 development
host loaded and ran an image declaring `minos 30.0`, so the declaration
certifies nothing about execution, in either direction. No component of this
workspace has ever been executed on macOS 14: no macOS 14 SDK exists on the
development machine (the oldest present is 15.2), and the machine itself
(Apple M4 Max) cannot boot macOS 14 at all, including in a VM, because — per
Apple's documented platform policy — no macOS 14 build supports its SoC
(inferred, corroborated by the hardware ID and by this host's SDK inventory
bottoming out at 15.2; NOT measured by attempting an install). Static analysis
found nothing that contradicts the floor — a deliberately lenient symbol scan
(whole-`.tbd` tokenization, with negative and sensitivity controls) found no
imported dynamic symbol absent from the macOS 15.2 SDK stubs, and 15.2 is one
major above the floor; the leniency is bounded but non-zero, so the scan can
under-report a missing symbol and never over-report one — but "nothing
contradicts it" is not "it works", and the
ObjC/WebKit surface most likely to differ across macOS releases is resolved at
runtime and invisible to symbol analysis. Discharging this requires a Mac
still on macOS 14 or a hosted macOS 14 runner; until then, "macOS 14 or newer"
above means DECLARED, not exercised.

macOS is a target, not a fork. All platforms share `desktop-contract`, the
fixture bytes, sidecar identity rules, and lifecycle state machine. Platform
code may implement process and packaging primitives, but it may not create a
macOS-only server protocol or a second application-data layout. Python's
`server.application_paths.ApplicationPaths` remains the sole owner of the
internal data layout; the supervisor passes one canonical root.

This workspace deliberately has no Node/npm build chain. The future desktop
shell will continue to use the existing server-rendered operator console.

## Development and conformance commands

Run these commands from the repository root — that is a correctness
precondition, not a convenience: cargo discovers the repo-root
`.cargo/config.toml` deployment-target pin by walking up from the CWD, not from
`--manifest-path`, so a cargo invocation started outside the repo root builds
at rustc's 11.0 default instead of the 14.0 floor. A temporary Cargo target
keeps generated binaries out of the source tree.

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
30-cycle stress run proves 30 distinct PIDs with zero residual processes,
listeners, or process groups, and loopback is asserted at socket level against
the live port.

Every evidence probe carries its own control, because a failed or partial
probe is an evidence failure and never clean absence — and exit codes cannot
establish that: `lsof --bogus` and `ps -p notanumber` both exit 1 with an
empty stdout, exactly as a clean no-match does. PID liveness therefore uses
`os.kill(pid, 0)` (no subprocess to misreport); every `lsof` absence query
rides the same invocation as a control port the harness is holding open, and
a reply omitting it raises; the process-group probe reads the whole table and
requires its own PID in the listing. **`lsof` and `ps` are hard prerequisites
of these tests** (present by default on macOS; `apt install lsof` /
`procps` on Linux) — the marked tests are opt-in precisely so a box without
them does not fail a plain `make test`.

Three non-claims REMAIN non-claims — a passing fault matrix here is not
universal cleanup:

- **A parent that no longer exists cannot kill a wedged child.** Supervisor
  SIGKILL cleanup is proven only for a cooperating child that is alive and
  observing stdin EOF; a child parked in uninterruptible I/O (for example a
  stalled LanceDB/Kuzu read) would outlive its dead parent.
- **Descendants of the production child are NOT cleaned up on the forced
  path.** The supervisor signals only the direct child PID, never a process
  group. The *fixture* spawns no descendants, so a passing fault matrix
  proves nothing about them either way. The *production* child does: it
  installs `ingest_tracker` and `parse_tracker` (`server/main.py`), whose
  helpers run `asyncio.create_subprocess_exec` and spawn LaTeXML/MinerU with
  `start_new_session=True` — literally `setsid()`. So on the forced rung
  (grace → TERM → KILL) the child dies without running the FastAPI lifespan,
  `ingest_tracker.shutdown()` never fires, and a `tools.notebook_ingest`
  grandchild is reparented to init still holding its notebook's LanceDB
  staging directory.

  The cooperative path is **not** a mitigation either, and must not be
  described as one: both trackers' `shutdown()` cancel only the asyncio
  wrappers, and their own docstrings state the case — the subprocess
  "receives no signal from cancelling the asyncio wrapper" and "continues
  running until the OS reaps it" (`server/ingest_tracker.py:345`,
  `server/parse_tracker.py:301`). `os.killpg` exists in this tree only on the
  per-call wall-TIMEOUT paths (`ingest/textbook_parser.py:479`,
  `tools/arxiv_fetch.py`, `tools/cdm_eval.py:375`), never on shutdown. So a
  descendant outlives BOTH shutdown paths, bounded only by its own wall
  timeout; the next-boot `mark_orphaned_runs_failed` /
  `mark_orphaned_parses_failed` sweeps repair the database row, not the
  process. Descendant cleanup is an open item for a future
  desktop-distribution milestone — it is not covered here and must not be
  read as covered.

- **The wildcard-bind arms were not ported.** The spike's `wildcard-v4` /
  `wildcard-v6` faults are absent from this matrix, so nothing exercises a
  child that binds `0.0.0.0` while announcing `127.0.0.1`. The supervisor
  performs no runtime probe of the actual bind, so such an arm would document
  a gap rather than close one. `wildcard-bound.jsonl` proves only that a
  frame cannot *announce* a wildcard; AC5's socket-level check proves the
  kernel state of a well-behaved child.

### `make desktop-conformance` is macOS-only today (issue #423)

The gate's contract is zero skips, and two of its tests skip off macOS: the
native-window regression (`tests/test_desktop_child.py`) has no
positive-controllable window probe outside System Events, and
`tests/test_desktop_contract.py`'s win32 `skipif` already tripped the same
gate. So the gate is red on Linux and Windows with no way to make it green,
and that is recorded here rather than papered over — the "Supported boundary"
section above names both as portability, not release, targets. Weakening the
zero-skip rule was rejected: a skip-tolerant gate is how lifecycle evidence
silently degrades. Everything else in this workspace stays platform-neutral
(`cargo test`, `cargo clippy`, the contract fixtures, `make test`); wiring a
non-macOS window probe with its own same-run control is the work a future
milestone owes before this claim can be dropped.

### What `window-ready` does and does not attest (issue #423)

The event carries one axis, `window_ordered_in`, and the name is the claim:
the toolkit reported the native window ordered in — on macOS a bare
`NSWindow.isVisible` via tao. AppKit reports that property true for a window
that is fully obscured by another, positioned off every display, zero-sized,
or on another Space, and nothing reads the WebView's render state. It is
nonetheless a real observation, not a restatement of "navigate returned Ok":
it was measured `false` for a `.visible(false)` build and `true` for the
default one, and the `test_hide_window` plan knob commits that negative
control as `test_fault_hidden_window_fails_the_cycle`. "A user can see the
window" is NOT established by this event and must not be inferred from it.

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
