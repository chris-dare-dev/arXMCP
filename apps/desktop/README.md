# arXMCP desktop workspace

This directory is the production desktop boundary for arXMCP. It contains a
platform-neutral Rust contract crate, a model-free fixture sidecar, the
production Tauri shell (`crates/supervisor`), the server lifecycle adapter
that shell drives (`server/desktop_child.py`), the frozen Python runtime
(`pyinstaller/`, m7), and launch-plan authoring (m10 — the supervisor derives
its own plan when `ARXMCP_DESKTOP_LAUNCH_PLAN` is absent, which is the shape a
double-clicked application has).

`.app` bundle assembly landed in `desktop-distribution-m15`: `bundle.active`
is `true`, no `resources`/`externalBin`/`frameworks` is wired, and
`make desktop-bundle` produces `arXMCP.app` with the frozen child placed under
`Contents/Resources/` and the outer bundle sealed ad-hoc. See "Assembled
artifact layout" below for what the artifact actually contains and for what
its seal does and does not establish.

Still NOT here: release signing and notarization, blocked on an Apple
Developer ID certificate this project does not have. Every signature in the
artifact — each nested Mach-O and the outer bundle — is ad-hoc: a real seal,
tamper-evident locally, and **not** a distribution signature.

The decision behind the layout is recorded in
[`.claude/docs/adr-desktop-bundle-assembly.md`](../../.claude/docs/adr-desktop-bundle-assembly.md)
(Accepted). It also records, with its sources, why the notarization question
cannot be answered here and what a build-and-submit trial would have to submit
to answer it.

## Child payload layout and its trust assumption

The self-authoring arm resolves the payload through **two layouts, in order**
(`crates/supervisor/src/main.rs::child_payload_candidates`):

| context | supervisor at | payload at |
|---|---|---|
| dev / m7 onedir | `<dir>/supervisor` | `<dir>/arxmcp-desktop-child/` (sibling) |
| assembled `.app` | `Contents/MacOS/supervisor` | `Contents/Resources/arxmcp-desktop-child/` |

The bundle candidate is offered **only when the supervisor actually sits in
`…/Contents/MacOS`**, so outside a bundle there is exactly one candidate. The
first candidate that is PRESENT is selected; if neither is, the launch is
refused by name (`child payload root missing (checked the bundle Resources and
supervisor-sibling layouts)`) rather than proceeding against a root that does
not exist.

`child_argv[0]` is then resolved inside the selected root by canonicalizing
both sides and requiring component-wise containment, and the root itself is
refused if it is a symlink — unchanged by the layout split, and deliberately
reached rather than skipped: a symlinked root counts as *present*, so it is
selected and refused, never silently traded for the other layout. The child's bytes are then checked in two independent ways before it is
trusted, and the difference between them matters (issues #435 / #436):

1. **The `identity_file` digest is a self-consistency check, not a tamper
   check.** It hashes the file and compares against the identity the child
   reports about itself — but `identity_file == child_argv[0]`, so both sides
   read the same bytes and a tampered child matches itself. It establishes
   that the process which answered the handshake is the file the supervisor
   launched, and that it agrees about its own component and version. Nothing
   more. An earlier version of this section implied otherwise.
2. **The code signature is the integrity check** (`lifecycle::verify_signature`,
   release builds only, macOS). Its reference lives in the signature blob
   rather than in the bytes under test, so it catches what the digest cannot:
   a flipped byte in the signed child now refuses to launch instead of
   executing normally. **Measured limit:** the payload is ad-hoc signed, so
   `codesign --force --sign -` re-signs a tampered or swapped binary and
   verification passes again. Anyone who can write to the payload can defeat
   it — which is the same residual risk the next paragraph already states,
   and what e4's release signing closes by giving the check an identity to
   pin. Scope today: corruption, failed updates, and casual tampering.

**The assumption an operator needs to know:** write access to the payload
directory — whichever layout is in force — is equivalent to arbitrary code
execution as the operator. Nothing in the supervisor can close that; the
defenses are install-location permissions and e4's release signing.
`std::env::current_exe()`, which anchors the whole resolution, is documented
by the Rust stdlib as *not* a security primitive; the PATH-search and
hardlink classes it names carry no privilege gradient here (the supervisor is
not setuid/setgid) but are recorded as accepted residual risk rather than
closed.

**Why two layouts instead of one.** m15 first assembled the bundle with the
payload beside the supervisor in `Contents/MacOS/`, per the ADR's Decision 2,
and measured that `codesign` cannot seal such a bundle at all. The ADR was
amended: **Decision 2a** moves the payload to `Contents/Resources/`, which
seals — so the bundled payload stops being a sibling, while the onedir shape
every developer run and every m10 gate uses stays exactly as it was. Both arms
and the refusal are tested, in `main.rs`'s unit tests and again against the
real bundled binary in
`tests/test_desktop_bundle.py::TestDualLayoutResolution`.

## Assembled artifact layout

Written from the artifact, not from the decision. Measured 2026-08-12 on
macOS 26.6 / Apple Silicon, from `make desktop-bundle`:

    arXMCP.app/
      Contents/
        Info.plist                       CFBundleExecutable=supervisor
                                         CFBundleIdentifier=com.arxmcp.desktop
                                         LSMinimumSystemVersion=14.0
        _CodeSignature/                  the outer seal, over everything below
        MacOS/
          supervisor                     the Tauri shell; minos 14.0
        Resources/
          icon.icns                      the app icon
          arxmcp-desktop-child/          m7's PyInstaller onedir, placed here
            arxmcp-desktop-child         frozen server child; minos 11.0
            arxmcp-desktop-probe         frozen verification probe; minos 11.0
            _internal/                   ~5,300 files, 180 Mach-O, ~0.75 GB
        Frameworks/                      absent — not used by this layout

Note the executable is `supervisor` (the cargo bin name), not `arXMCP`
(`productName`, which names the bundle directory). Nothing should hard-code
either: `desktop_package.bundle_executable()` reads `CFBundleExecutable`.

**What the build does, in order** — `apps/desktop/pyinstaller/desktop_package.py
assemble`: pre-sign every nested Mach-O bottom-up (deepest path first, one
`codesign` per file, ad-hoc identity by default; **never** `codesign --deep`,
which is the shortcut the ADR's evidence rows E4/E6 record surviving local
verification and failing the notary) → `tauri build` for the shell → copy the
payload into `Contents/Resources/` → re-seal the outer bundle. The seal must
succeed: assembly RAISES rather than leaving an unsealed `.app` on disk.
`tauri-cli` is pinned (`cargo install --locked --version`) into
`var/desktop-package/`.

**What the seal does and does not say. e4 inherits this.**

1. **The outer bundle seals, and that is all it means.** `codesign
   --verify --strict` reports "valid on disk / satisfies its Designated
   Requirement" over the whole bundle, and every nested Mach-O carries its own
   ad-hoc signature underneath. It is an ad-hoc seal: no identity, no
   certificate, and it settles nothing about Apple's notary — E6 in the ADR is
   the recorded case where local verification passed and the notary refused.

   The location is load-bearing and was learned the hard way. With the payload
   at `Contents/MacOS/` (the ADR's original Decision 2), `codesign` treats
   every file there as a nested code object and refuses the bundle at the
   first non-Mach-O one:

       <app>: code object is not signed at all
       In subcomponent: .../Contents/MacOS/arxmcp-desktop-child/_internal/tools/sbom.sh

   That is a property of the location, not of this payload: a six-byte
   `data.txt` reproduces it, and the same file under `Contents/Resources/`
   seals. `tests/test_desktop_bundle.py::TestOuterSeal` re-runs that A/B
   control on every gate run, so any future seal failure can be attributed to
   the layout or to the host rather than guessed at.

2. **Gatekeeper path translocation is UNVERIFIED.** Setting
   `com.apple.quarantine` on the bundle and launching it through `open(1)`
   yields exit 0 and no process, so translocation never gets a chance to
   occur. The reason narrowed when the payload moved: the bundle now has a
   valid outer seal and the quarantined launch is still refused, so what
   remains is the ad-hoc identity — reaching that path needs the Developer ID
   signature e4 is blocked on. What IS measured: the bundle relocated whole to
   an arbitrary path and launched through LaunchServices resolves the payload
   inside the relocated bundle, off its own `current_exe()`. Translocation
   relocates the bundle as a unit too, so that is evidence for the
   expectation — it is not the expectation itself.

**Two declared floors, and they disagree.** The Tauri shell reports
`minos 14.0` (pinned by `.cargo/config.toml`); the two PyInstaller-produced
executables report `minos 11.0`, because this project does not compile the
CPython bootloader and inherits whatever the upstream wheel declared. Across
the payload's 180 Mach-O files: 111 at 14.0, 36 at 12.0, 33 at 11.0. The
frozen half therefore UNDER-declares the real floor, which the `faiss_cpu`
`macosx_14_0_arm64` wheel fixes at 14.0. Nothing enforces `minos` at runtime
(see "Supported boundary"), so this changes no behaviour — it removes an
inference that the artifact agreed with itself. The values are pinned in
`tests/test_desktop_bundle.py`.

The `.app` is the only distribution target (`bundle.targets: ["app"]`). DMG
versus zip is not decided here; only a notarization submission forces it.

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
frames and in the `X-ArXMCP-Startup-Token` readiness header. **The supervisor**
never puts it in an argument, environment variable, URL/query value, `bound`
field, object representation, exception detail, or diagnostic. The fixture
sidecar accepts no command-line arguments.

That sentence used to end "…or persisted manifest/log artifact", stated
unconditionally, and issue #438 measured it false: the child's stderr fd was
wired straight to `logs/desktop-child.log` and a live token was sitting in
that file at 0644. The claim was about what the SUPERVISOR writes; the log is
whatever the CHILD writes, and nothing was interposed.

What defends those two sinks now, stated as mechanism rather than as a promise:

- **`logs/desktop-child.log`** — child stderr is piped, not handed over as a
  file descriptor, and relayed line by line through
  `redact::scrub_child_text` before it reaches disk (#438). This covers writes
  that bypass Python's own `RedactionFilter` entirely, such as the interpreter's
  raw `Fatal Python error:` block (#468).
- **`logs/supervisor-events.ndjson`** — the `bound-frame-invalid` diagnostic,
  the only place child-chosen bytes are persisted, uses the same function.
- **Both files are created 0600** (#488), and existing ones are chmod'd on
  open, because a file created by an earlier version keeps its mode otherwise.

`scrub_child_text` removes the exact token AND any run of 32+ hex digits in
either case. The case-insensitive half is #439: the casing of an echoed copy is
chosen by the child, so exact matching missed an UPPERCASE copy and a 32-char
prefix, from which `tr A-F a-f` recovered the capability. **Trade-off:** this
also redacts legitimate long digests, so an executable `sha256` reads as
`[REDACTED-HEX]` in the child log. Accepted deliberately — distinguishing a
digest from a secret inside arbitrary child-controlled text is exactly the kind
of cleverness that fails, and `events.rs` already promises the event log carries
"never any 64-hex digest".

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
