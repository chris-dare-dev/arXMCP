# desktop-distribution-m6 — implementation-ready plan (general researcher, single mode)

Base: `origin/main` `9adcf31` (m5 shipped: `server/desktop_child.py`,
`apps/desktop/crates/supervisor/`). This slice closes issue #397 and the last
two m4 falsifiability gaps (AC4's fault matrix, AC5's 30-cycle/loopback
regression) that m5's `README.md` and `synthesis.md` explicitly deferred here.

## 0. What already exists vs. what m6 adds — one-line map

| Layer | Exists (m5) | Missing (m6) |
|---|---|---|
| Supervisor lifecycle (`lifecycle.rs`) | spawn→launch→bound→health→ready→smoke→window→normal-shutdown; TERM→KILL→reap ladder unit-tested against a synthetic stubborn shell child (`shutdown_child_escalates_through_terminate_to_kill`, `lifecycle.rs:483-510`) | fault-injected end-to-end runs through the SAME `cycle()`/`run_cycle()` path (startup timeout, malformed bound, child crash, ignored shutdown) |
| Fixture sidecar (`fixture-sidecar/src/main.rs`) | clean, always-correct behavior only | a namespaced `extensions` fault switch (spike-3 precedent) |
| Real child (`server/desktop_child.py`) | normal boot + normal shutdown (AC4, m5) + bounded drain (H1) | one real-server fault: parent-lifetime EOF with NO shutdown frame (untested today — AC4 only exercises the authenticated-shutdown path) |
| 30-cycle stress | `tests/test_desktop_contract.py::test_fixture_sidecar_is_model_free_token_safe_and_bounded` proves ONE cycle, twice (2 stop modes) | 30 cycles, 30 distinct PIDs, self-asserting `ps`/`lsof` audits |
| Loopback assertion | wire-field equality only (`bound.endpoint == Endpoint("127.0.0.1", ...)`, e.g. `test_desktop_contract.py:438`) | live socket-level proof against the bound port + an out-of-band probe that nothing is reachable off-loopback |
| Rust-side redaction | none — `events.rs` Recorder persists only structural fields (event name, pid, seq, static `&'static str` reasons) | a named scrub primitive + a cross-language parity fixture |

## 1. Fault matrix — injection mechanism, supervisor behavior, assertion

Six faults were named across the orchestrator's task text and the AC bullets:
startup timeout, malformed `bound`, child-crash-before-bound,
child-crash-after-ready, supervisor-crash (SIGKILL), ignored-shutdown-force-
escalation. Five of six are **child-side** faults exercised through the
**fixture sidecar** driven by the **real supervisor binary** (so the code
under test is `lifecycle.rs`, not a mock of it); one (supervisor-crash) is
**supervisor-side** and is proven by the **child's own** parent-lifetime
lease — there is no supervisor code path to exercise for that case because,
by construction, the supervisor is dead.

### 1.1 Injection mechanism — new namespaced extension, not a new wire field

`Launch.extensions` is already the wire contract's sanctioned "compatible
addition" channel (`apps/desktop/README.md:88-92`: "compatible additions are
allowed only under `extensions`, whose top-level ASCII keys must be
namespaced"). Today `lifecycle.rs:120` hardcodes `extensions:
Extensions::new()` — the supervisor never populates it — and
`server/desktop_child.py` never reads `frame.extensions` for behavior
(confirmed: no `.extensions` reference anywhere in `_validate_launch`,
`_serve`, or `_watch_stdin`). This makes the extensions channel a safe,
zero-blast-radius fault-injection seam:

1. Add `test_fault: Option<String>` (`#[serde(default)]`) to the `Plan`
   struct (`main.rs:26-40`), alongside the existing test-only `smoke: bool`
   field (same precedent: a field that exists in the production schema but
   is only ever set by a test harness).
2. In `cycle()` (`lifecycle.rs:112-136`), when `plan.test_fault` is `Some`,
   insert `("org.arxmcp.test-fault", Value::String(fault))` into the
   `launch.extensions` map before `encode_frame`.
3. In `fixture-sidecar/src/main.rs`, after `parse_bootstrap`-equivalent
   validation (`validate_fixture_launch`, `main.rs:100-116`), read
   `launch.extensions.get("org.arxmcp.test-fault")` and branch on five
   literal strings, mirroring the spike's `Fault` enum
   (`tools/desktop_lifecycle_spike/src/bin/fixture_sidecar.rs:105-234`) but
   simplified — the production fixture spawns no canary, so there is no
   process-group/descendant plumbing to replicate:
   - `"startup-timeout"` — park before binding, forever (test-side timeout
     bounds the wait, see §1.2).
   - `"malformed-bound"` — write a truncated/invalid JSON line instead of
     the real `Bound` (byte-identical technique to the spike's
     `write_bound` `MalformedBound` arm), then continue into the normal
     serve loop so the process stays alive and reachable for cleanup.
   - `"crash-before-bound"` — sleep ~100ms, `std::process::abort()` before
     ever binding or writing `bound`.
   - `"crash-after-ready"` — bind and answer `/healthz`+`/readyz` normally,
     then `std::process::abort()` ~100ms after the first authorized
     `/readyz` 200.
   - `"ignore-shutdown"` — install `libc::signal(SIGTERM, SIG_IGN)`
     (requires adding `libc.workspace = true` to
     `fixture-sidecar/Cargo.toml`; the workspace already pins
     `libc = "=0.2.189"` at `apps/desktop/Cargo.toml:18`, so this is a
     zero-drift addition) and ignore valid `shutdown` frames too, forcing
     the full grace→TERM→force→KILL→reap ladder.
4. `desktop_child.py` needs **no change** — it structurally cannot read
   this extension (nothing in its code path looks at `frame.extensions`),
   so the production child stays byte-identical to m5 for four of these
   five faults. This is the cheapest possible guarantee that fault-
   injection code cannot leak into the real distribution.

### 1.2 Per-fault: supervisor behavior + assertion + already-handled vs. new

| Fault | Injected via | Supervisor path exercised | Already handled (m5)? | New assertion |
|---|---|---|---|---|
| Startup timeout | fixture `"startup-timeout"` | `await_bound`'s `recv_timeout(BOUND_TIMEOUT)` (`lifecycle.rs:231-233`) fires → `Err("bound frame timeout")` → `run_cycle`'s `Err` arm → `shutdown_child(orphan)` (`lifecycle.rs:88-93`) | **Partially.** The timeout-then-cleanup *code path* exists; it has never been exercised end-to-end. `BOUND_TIMEOUT = 240s` (`lifecycle.rs:29`) makes this too slow to run at test speed as-is. | Add a test-only override, e.g. `ARXMCP_DESKTOP_BOUND_TIMEOUT_MS`, read once at supervisor startup (same pattern as `BARRIER_ENV`/`PLAN_ENV`, `main.rs:23-24` — both already `ARXMCP_`-prefixed and already scrubbed from the child's env by the existing `ARXMCP_` removal loop, `lifecycle.rs:153-157`, so nothing new leaks to the child). Set it to a few seconds for this one test process only; unset, `BOUND_TIMEOUT` stays 240s for real launches. Assert: supervisor exits non-zero, `lifecycle-failed` event recorded with `reason: "bound frame timeout"`, `child-spawn` PID from the event log is no longer running (`ps -p <pid>` empty) within a bounded window after supervisor exit. |
| Malformed `bound` frame | fixture `"malformed-bound"` | `await_bound`'s `parse_frame(&frame)` (`lifecycle.rs:236`) → `Err("bound frame invalid")` → same `Err` cleanup arm | **No.** No test drives a real subprocess through this parse-failure branch; it is currently only unit-proven at the byte-level contract layer (`test_desktop_contract.py::test_wildcards_zero_ports_url_mismatch_and_path_escape_are_rejected`, which never touches the supervisor's `await_bound`). | Assert supervisor records `lifecycle-failed` with `reason: "bound frame invalid"` (never treat a garbage frame as `Ok`), and that the fixture's `child-spawn` PID is reaped — `shutdown_child` must still work even though the supervisor never learned the fixture's port, because it drives cleanup purely off the retained `ChildStdin`/`Child` handle, not the port. |
| Child crash before bound | fixture `"crash-before-bound"` | `await_bound`'s background reader thread's `read_frame` returns an I/O error (pipe EOF from the aborted process) → `.recv_timeout(...).map_err(...)` → `Err("bound frame read failed")` or `Err("child stdout closed before bound")` | **No** — same as above, first real exercise of this arm. | Assert the correct one of the two error strings (whichever `abort()`'s pipe-close timing actually produces — pin the observed one, don't guess), and that no listening socket exists at all (the fixture aborted before `TcpListener::bind`, so this case additionally proves the supervisor never treats a partial spawn as a live child). |
| Child crash after ready | fixture `"crash-after-ready"` | Cycle proceeds normally through `child-ready`; the abort happens asynchronously. Either the in-flight `mcp_smoke`/`navigate_window` call fails (connection reset) and `cycle()` returns `Err`, or (race) the cycle completes and the RunEvent::Exit handler later finds a dead child on `shutdown_child`'s first `wait_exit` | **No.** | Assert BOTH outcomes are handled without a panic and without an orphan: either `run_cycle`'s `Err` arm fires (`lifecycle.rs:88-93`), or (if the smoke path raced ahead of the abort) `shutdown_child`'s `wait_exit(grace_ms)` immediately observes `Some(exit_code)` on the already-dead process rather than hanging the full grace window. This is the one fault where the assertion must tolerate a two-way race — assert the observable invariant ("no live PID, no live listener, bounded wall time"), not a single fixed code path. |
| Supervisor crash (SIGKILL) | kill the **supervisor process itself**, not the fixture | **None** — by construction there is no supervisor code running after it is SIGKILLed. The only thing that can clean up is the child's own parent-lifetime lease. | **Design exists, untested against a live process.** `desktop_child.py`'s `_watch_stdin` (`server/desktop_child.py:244-271`) already treats bare stdin EOF as `server.should_exit = True` — this is the exact mechanism a dead parent triggers (its held write-end fd closes → kernel delivers EOF to the child's read end). Same for the fixture (`LeaseEvent::Closed` branch, `fixture-sidecar/src/main.rs:263-268`, already exercised for the fixture via `test_fixture_sidecar_is_model_free_token_safe_and_bounded[stdin-eof]`, but that test calls `.close()` from a *cooperating* Python parent, not from an actually-SIGKILLed one). | Two tests, cheapest first: (a) **fixture** — spawn the real `supervisor` binary via `subprocess.Popen`, tail `supervisor-events.ndjson` (bounded poll) until `child-bound` appears (gives child PID + port), then `os.kill(supervisor_pid, signal.SIGKILL)`. Assert, within a bounded window with no grace/force timers involved (the parent is gone, there is nothing to negotiate with): `ps -p <child_pid>` empty, and a connect attempt to the recorded port raises `ConnectionRefusedError`. (b) **real server** — see §6, this doubles as the mandatory real-server fault case. |
| Ignored shutdown, force escalation | fixture `"ignore-shutdown"` | `shutdown_child`'s full ladder: `wait_exit(grace_ms)` times out → `request_terminate` (SIGTERM, ignored) → `wait_exit(force_after_ms)` times out → `control.child.kill()` (SIGKILL) → `wait_exit(REAP_BUDGET_MS)` | **Unit-tested with a synthetic `/bin/sh` child** (`lifecycle.rs:483-510`, m5 rectify M3), **never through the full `cycle()`→`run_cycle()` supervisor path with a real spawned-and-bound fixture.** | Assert `shutdown_child` returns `-1` (force-killed, no exit code — mirrors the existing unit test's assertion), total wall time stays bounded (well under `grace_ms + force_after_ms + REAP_BUDGET_MS`; use short test overrides for `grace_ms`/`force_after_ms` the same way the unit test uses `200`/`200` rather than the wire-mandated `MIN_GRACE_MS=35_000`/`FORCE_AFTER_MS=5_000` — the *wire* launch frame's `shutdown.grace_ms`/`force_after_ms` are what the fixture and supervisor negotiate, so shrink them via the `Plan`, not by inventing a second override path), and the PID is unrecoverable afterward (`process_control::request_terminate(pid)` returns `false`, mirroring `lifecycle.rs:509`). |

**Why the fixture, not the real child, for five of six:** the real child's
5–30s eager BGE-M3/LanceDB warm-up (`server/main.py:61-66`) makes a fault
matrix with several deliberately-slow cases (startup timeout especially)
prohibitively expensive if run against it — this is exactly the m3/m4
precedent (`desktop-distribution-m3/rectify/summary.md:75-78`,
brief-3.md §7) that put the fixture-based conformance path in a separate,
cheap, fast-iterating gate. The fixture is model-free and already proven
safe by spike-3's 11-case fault matrix (`spike-3.md:117-129`) — m6 is
reproducing that proof against the **production** `lifecycle.rs`/`main.rs`
supervisor rather than the throwaway spike host, which is the actual gap
m4's brief-3 (§2, AC4 row) flagged.

## 2. The two Spike-3 non-claims must stay non-claims

Spike-3 recorded exactly two limits (`.claude/notes/spikes/desktop-distribution-spike-3.md:143-146`):

1. "Parent `SIGKILL` cleanup is proven only for a cooperating child that
   observes stdin EOF. A wedged child cannot be killed by a parent that no
   longer exists."
2. "Process-group cleanup does not cover a descendant that deliberately
   calls `setsid()`; that MinerU-style escape remains an explicit non-claim."

**How m6 keeps both honest, concretely:**

- Non-claim #1 is *sharper* in production than in the spike, because the
  production supervisor (`process_control.rs`) never adopted the spike's
  process-group model at all — `request_terminate` signals a single
  positive PID (`libc::kill(pid, libc::SIGTERM)`, `process_control.rs:16`),
  not a process group. This is a **narrower** claim than the spike made,
  and it must be stated as narrower, not silently inherited. The §1
  supervisor-crash test (and §6) proves the *cooperating* case — a child
  that is alive and correctly polling `stdin` — self-terminates on EOF. It
  must **not** be phrased or asserted in a way that implies "any crashed
  parent's child dies," because a child parked in uninterruptible I/O (a
  stalled LanceDB/Kuzu read — the exact hazard `REAP_BUDGET_MS`'s docstring
  at `lifecycle.rs:41-45` already names for the *normal* shutdown path)
  would not observe the EOF promptly and is explicitly out of scope. Write
  this as a **named limitation in the test docstring and in
  `apps/desktop/README.md`'s "Secret handling"/lifecycle section**, next to
  the existing "fault matrix and universal cleanup remain deferred"
  sentence (`README.md:117-118`) which m6 should now replace with the
  precise, narrower claim plus its limit — not a claim of universal
  cleanup.
- Non-claim #2 requires no new test, because it is currently **vacuously
  true and should stay documented as such, not silently dropped**: neither
  `desktop_child.py` nor the production `fixture-sidecar` spawns any
  descendant process (unlike the spike's canary). Do not attempt to
  "prove" process-group cleanup by adding a canary-spawning fixture
  variant — that would import a hazard (and a `setsid()` escape test) that
  doesn't exist in the shipped system and isn't asked for by any AC. State
  it once, explicitly, in the README's fault-matrix section: "the
  supervisor signals only the direct child PID; the current child and
  fixture spawn no descendants, so process-group/`setsid()` escape is not
  applicable today — a future milestone that adds a subprocess-spawning
  child (e.g. a bundled model-conversion tool) must re-open this design."

## 3. 30-cycle stress — where it runs, PID/orphan/listener evidence

**Where:** `tests/test_desktop_contract.py`, **not**
`tests/test_desktop_child.py` and **not** through the Tauri supervisor. The
file already directly subprocess-drives `fixture-sidecar` without Tauri
(`_spawn_sidecar`, `test_desktop_contract.py:146-167`); reuse that exact
pattern in a loop. This keeps the 30 cycles fast (each cycle is a
model-free Rust binary boot + one HTTP round trip + shutdown — spike-3
measured 383–408ms per cycle, `spike-3.md:123`) and keeps it inside the
existing `make desktop-conformance` gate's fast half
(`ARXMCP_FIXTURE_SIDECAR=... pytest tests/test_desktop_contract.py`,
`Makefile:157`), not the slower real-server half (`Makefile:158`). Running
30 cycles through the full Tauri supervisor+window would multiply AC3's
per-launch cost (window creation, single-instance plugin registration) by
30 for no additional evidence value, since the property under test —
"an OS process gets created and fully reaped 30 times with no leak" — does
not depend on the Tauri layer at all.

**PID distinctness:** capture `process.pid` (the OS PID `subprocess.Popen`
assigns, not a wire field) into a `list[int]` across all 30 cycles; assert
`len(set(pids)) == 30`. This is only meaningful if each cycle spawns a
**fresh** process — do not reuse one `Popen` across iterations (the m4
brief's exact "cheap lie" example, brief-3.md §2 AC5 row: "Reuse ONE process
across all 30 'cycles'").

**Orphan/listener audits, self-asserting per the spike-3 discipline
("Failed or partial `ps`/`lsof` probes are evidence failures, never clean
absence," `spike-3.md:61-62`, restated in brief-3.md §2 AC5 row):**

- After each cycle's clean shutdown, capture the bound port (from the real
  `Bound` wire frame, already parsed) and immediately run
  `/usr/sbin/lsof -nP -iTCP:<port> -sTCP:LISTEN` (macOS path, matching
  spike-3's exact invocation, `spike-3.md:111`). Assert the subprocess call
  itself **succeeds** (`returncode in (0, 1)` — `lsof` exits `1` for "no
  matches," which is the expected clean-absence signal; any other exit code
  or a `FileNotFoundError`/`TimeoutExpired` is a **probe failure**, must
  raise, never be swallowed into "assume clean"), and assert its stdout is
  empty.
- After each cycle, run `ps -p <pid>` (or `ps -axo pid=` grep) for the
  captured PID; a non-zero `ps -p` exit with empty output is the expected
  "process gone" signal — same self-assertion discipline: distinguish
  "command ran and found nothing" from "command could not run."
- Aggregate all 30 cycles' evidence into one assertion block at the end
  (not per-iteration `assert`, so one failure doesn't hide the shape of the
  other 29) — mirrors AC3's `errors = (streams[1], streams[3])` pattern of
  attaching full diagnostic context to the final assertion
  (`test_desktop_child.py:429-430`).

**Deadlines — bounded, not aggressive (m3's 200ms→2000ms lesson,
`desktop-distribution-m3/rectify/summary.md:75-78`, and m5's own
child-suite growth from 13.44s→35.57s once a real bound was exercised):**
give each cycle's bound-frame wait a few-seconds budget (the fixture binds
in milliseconds normally, per spike-3's measured 383–408ms full cycle
latency, so a multi-second per-cycle deadline is generous headroom, not
aggressive), and give the whole 30-cycle test a wall-clock ceiling generous
enough to absorb CI/repo load (e.g. 60–120s for 30 cycles at ~0.4s/cycle
baseline) without being so loose it masks a real hang. Do **not** copy the
spike's exact numbers verbatim without re-measuring on this machine first —
the m4 brief's own caveat about the 322s `make test` figure
("not independently re-timed... re-verify at implementation time,"
brief-3.md §7) applies here too.

## 4. Rust-side redaction parity

**What actually needs redacting on the Rust side, precisely:** the
supervisor's own persisted diagnostics (`events.rs`'s
`supervisor-events.ndjson` and any new fault-matrix diagnostic artifact) are
already structurally safe by construction — every field written today is
either a static `&'static str` reason, a PID, a port, a tool count, or a
boolean (`lifecycle.rs`'s `json!({...})` call sites; `main.rs:170-174`'s
`activated` field). The **one** value that could ever appear in a Rust-side
string is the startup capability, and the existing regression tests already
prove its absence via a **post-hoc structural sweep**
(`_HEX64` regex + allow-list, `test_ac3_zero_delay_race_single_spawn`,
`test_desktop_child.py:449-463`), not active redaction. `RedactionFilter`
(`server/observability/log_filter.py:62-105`) is a different mechanism
solving a different problem (it strips **named fields** — `query`,
`body_canonical`, `body_raw_latex`, `mathml` — from **structured log
records**, and is installed on the Python logger via
`_configure_child_logging`, `server/desktop_child.py:230-241`, m5 H2). There
is no Rust equivalent of *that* filter today because the supervisor never
logs query/chunk/LaTeX content — it doesn't touch MCP payloads at that
granularity (`http.rs`'s `mcp_smoke`/`mcp_post` only inspect status codes
and the `tools` array length, `lifecycle.rs:267-323`).

**What "the same standard" should mean, concretely, for m6:** not literally
porting `REDACTED_FIELDS` to Rust (there is nothing in scope that would
carry those field names), but porting the **invariant class** —
active-scrub-before-persist, applied uniformly, never call-site-optional —
for the one secret the Rust side ever handles. Add one named function,
e.g. `redact::scrub(input: &str, secret: &str) -> String` (new
`apps/desktop/crates/supervisor/src/redact.rs`), that replaces every
occurrence of `secret` in `input` with a fixed placeholder (e.g.
`"[REDACTED]"`), and route every **string field derived from process
output** (not the already-safe structured fields) through it before
persisting — this becomes newly relevant in m6 specifically because the
fault-matrix diagnostics (§1) are the first place the supervisor may want
to persist a **tail of raw child stderr/stdout bytes** for post-mortem
value (e.g. "why did the child crash"), which m5 never needed since the
normal path only persists structural events. If the implementer decides
NOT to add a raw-output diagnostic capture in m6 (the ACs do not strictly
require one — only that "every persisted diagnostic is scanned recursively
and proven free of the startup capability"), then the minimal-diff answer
is: **keep the existing post-hoc sweep as the primary control** (extend the
`_HEX64` sweep pattern to cover every new fault-matrix artifact path, same
as AC3/AC4 already do), and add the `redact::scrub` primitive only if a
new raw-capture diagnostic is introduced. Do not build an unused redaction
module — that would be dead code the comment-density standard forbids.

**Proving parity with a shared test, not two independent ones:** follow the
`fixtures.sha256`/`contract-fixtures/*.jsonl` precedent already established
for exactly this cross-language-drift problem
(`apps/desktop/README.md:134-138`: "Adding or changing a fixture requires
an intentional digest update that must pass independently in both
languages"). Add one new fixture,
`apps/desktop/contract-fixtures/redaction-vectors.jsonl`, each line a JSON
object `{"input": "...", "secret": "...", "expected": "..."}` covering: the
secret at the start/middle/end of a string, the secret embedded in a JSON
string value, the secret repeated twice, a **partial** match shorter than
the full 64-hex secret (must NOT be redacted — proves no over-eager
substring stripping), and mixed case (hex tokens are lowercase by
construction — `StartupToken` — so an uppercase near-miss must also NOT be
redacted). Both `redact::scrub` (Rust) and an equivalent Python helper
(only needed if Python ever independently re-implements this same
operation — if it doesn't, per the paragraph above, skip the Python side of
the fixture and say so explicitly rather than inventing a Python consumer
with no caller) load the same file and assert `scrub(input, secret) ==
expected` line-for-line. This is the same technique — one fixture, two
readers, one pinned digest — that already prevents wire-contract drift; it
generalizes cleanly to redaction vectors without inventing a new mechanism.

## 5. Socket-level loopback assertion

**The gap named by AC:** existing tests assert loopback via the **parsed
wire field** (`bound.endpoint == Endpoint("127.0.0.1", bound.endpoint.port)`,
e.g. `test_desktop_contract.py:438`, `test_desktop_child.py:276`) — this
proves the *frame says* 127.0.0.1, not that the *kernel* only bound
loopback. `desktop_child.py:362-364` already binds with
`sock.bind(("127.0.0.1", 0))` (correct), and the wire contract already
rejects a `bound` frame announcing `0.0.0.0`/`::`
(`test_desktop_contract.py`'s `wildcard-bound.jsonl` negative fixture) — but
neither of those is a socket-level probe against the *live, running*
listener.

**The probe, concretely:** after the child/fixture is bound and ready,
attempt a **live TCP connect** to the announced port on the machine's
non-loopback address(es), not just 127.0.0.1. Two complementary checks:

1. **Positive (already done, keep):** `socket.create_connection(("127.0.0.1",
   port), timeout=2)` succeeds (`_connect_probe`,
   `test_desktop_child.py:185-190`, already self-asserting).
2. **Negative, new:** enumerate the host's non-loopback IPv4 addresses (e.g.
   `socket.gethostbyname_ex(socket.gethostname())` filtered to non-
   `127.0.0.0/8`, or read `en0`'s address via
   `ipconfig getifaddr en0` on macOS as a fallback), and attempt
   `socket.create_connection((lan_ip, port), timeout=2)`. This **must**
   raise (`ConnectionRefusedError`/`OSError`/timeout — any of these is
   "not reachable"; the failure *mode* isn't the point, non-connection is).
   Also independently corroborate with `lsof -nP -iTCP:<port> -sTCP:LISTEN`
   (already used elsewhere) and assert the returned listener line's local
   address is `127.0.0.1:<port>`, never `*:<port>` or the LAN IP.

**Behavior on a machine with no external interface (CI runner, airplane
mode, container with only loopback):** step 2's address enumeration can
legitimately come back empty. This is **not** a probe failure and must not
be asserted as one — but it also must not be silently skipped without a
record, per the "never clean absence" discipline. Record it explicitly:
when no non-loopback address is discoverable, the test should
**additionally** assert against the IPv4 wildcard-equivalent check that
already exists at the wire-contract level (the `wildcard-bound.jsonl`
negative fixture proves the *frame* cannot say `0.0.0.0`) plus one more
independent structural check — `lsof`'s local-address column showing
`127.0.0.1` and not `*`/`0.0.0.0` — so the test degrades to "two
independent structural proofs" rather than "zero proof," and the skip
condition itself is asserted and logged (`pytest` warning or a recorded
`SimpleNamespace` flag), not silently absorbed. Do not `pytest.skip()` the
whole test on a loopback-only host — the wildcard/`lsof` half still runs
unconditionally.

## 6. The mandatory real-server fault case

**Which one, and why it's the cheapest:** the **supervisor-crash / bare
stdin-EOF-with-no-shutdown-frame** case (§1's sixth row). It requires:

- **No new code in `server/desktop_child.py`** — `_watch_stdin`
  (`server/desktop_child.py:244-271`) already treats bare EOF identically
  to an authenticated shutdown for the purpose of setting
  `server.should_exit`; this is a genuinely already-shipped code path that
  m5's AC4 never exercised (AC4 always sends an authenticated `shutdown`
  frame before/instead of closing stdin — see `test_ac4_normal_shutdown_
  leaves_nothing`, `test_desktop_child.py:466-536`, which never calls bare
  `process.stdin.close()` without first writing a valid `Shutdown` frame).
- **One real child boot**, reusing the exact fixture pattern the `real_child`
  module fixture already establishes (`test_desktop_child.py:213-261`) —
  spawn `CHILD_ARGV`, send `launch`, wait for `bound`. Given the module-
  scoped `real_child` fixture is shared across AC1/AC2/AC4 and AC4 already
  stops it, this new test needs **its own** function-scoped boot (one extra
  ~5–30s warm-up in the conformance gate — acceptable, and consistent with
  the task framing's "~4.7s to boot" figure for a lightly-warmed
  configuration; re-measure locally before committing to a specific
  deadline, since m5's own measurements ranged 5–30s depending on load).
- **No supervisor/Tauri binary involved at all** — this specific fault only
  needs to prove the **child's** self-cleanup contract, which is
  independent of what killed its parent. This is the honest scope: it
  proves "a cooperating, live child observing EOF exits cleanly," which is
  exactly non-claim #1's boundary (§2) — it deliberately does **not**
  attempt to prove cleanup of a wedged child, and the test docstring must
  say so explicitly (mirroring `_wedge_an_inflight_request`'s docstring
  style, `test_desktop_child.py:135-151`, which already states what it
  does and does NOT prove).

**Assertion:** `process.stdin.close()` with no prior `Shutdown` frame write;
assert `process.wait(timeout=<a few seconds>) == 0` (should be near-
instant — there is no grace/force negotiation on this path, since the child
isn't waiting for a supervisor response, it just observes EOF and drains);
assert the connect probe that succeeded pre-close now raises
`ConnectionRefusedError` post-exit (same self-asserting pattern as AC4);
sweep the log file + stdout remainder + argv/env for the capability bytes
(same sweep AC4 already performs). This single test simultaneously
discharges AC bullet 1's "supervisor crash" fault-matrix requirement (at
the fixture layer, per §1's row) *and* the standalone "at least one real-
server fault case" AC bullet — do not build two unrelated fault scenarios
where one well-chosen one covers both.

## 7. Honest LOC + file estimate

| Area | File(s) | Est. LOC |
|---|---|---|
| Fault-injection extension plumbing | `apps/desktop/crates/supervisor/src/main.rs` (`Plan.test_fault` field + threading into `cycle()`), `lifecycle.rs` (extensions insert) | 20–40 |
| Fault-injection behaviors | `apps/desktop/crates/fixture-sidecar/src/main.rs` (5 fault arms, mirroring but simplifying the spike's ~130-LOC `Fault` handling) | 100–160 |
| `fixture-sidecar/Cargo.toml` | `libc.workspace = true` | 1 |
| Test-only bound-timeout override | `main.rs` (env read, mirrors `BARRIER_ENV`) | 10–15 |
| Rust redaction primitive (only if a raw-capture diagnostic is added, §4) | new `apps/desktop/crates/supervisor/src/redact.rs` + `main.rs`/`lifecycle.rs` wiring | 0 (if skipped) or 40–70 |
| Cross-language redaction fixture | `apps/desktop/contract-fixtures/redaction-vectors.jsonl` + reader glue in both languages | 30–60 |
| Fault-matrix tests (Rust integration, driving the real supervisor binary against the fixture) | new `tests/test_desktop_contract.py` functions (5 fault cases + 1 supervisor-crash-via-fixture case) | 220–320 |
| 30-cycle stress + PID/orphan/listener audit | `tests/test_desktop_contract.py` (new function) | 90–140 |
| Socket-level loopback regression | `tests/test_desktop_contract.py` or `tests/test_desktop_child.py` (new function) | 60–100 |
| Real-server EOF fault case | `tests/test_desktop_child.py` (new function + small fixture) | 70–110 |
| README/CLAUDE.md doc updates (non-claims, marker doc, fault-matrix section rewrite) | `apps/desktop/README.md`, `CLAUDE.md` §4.5 | 20–40 |
| **Total (hand-written, excluding regenerated lockfiles)** | | **~620–1,050** |

**This plausibly exceeds 800 LOC**, primarily driven by the fault-matrix
test surface (six distinct fault scenarios, each needing its own harness
setup/teardown even where they share fixtures) plus the 30-cycle and
loopback regressions. Unlike m4/m5, this is **test-and-fixture-heavy, not
new-runtime-surface-heavy** — the production `desktop_child.py` gets zero
new lines, and the supervisor's non-test-only production code changes are
small (extensions threading, one env override). If the actual diff lands
under 800, `--allow-large-diff` is unnecessary; if it lands over, the owner
authorized this path per-milestone (m5's synthesis: "`--allow-large-diff`
was owner-authorized for m5 before Phase 2" — m5-specific, not a standing
grant) and **m6 needs its own explicit authorization**, not an assumption
that m5's applies. Flag this at Phase 2 kickoff rather than discovering it
mid-diff (the exact failure mode brief-3.md §4 warned about for m4).

## 8. external_writes_required

- `git push origin main` — per-event authorization (CLAUDE.md External
  System Write Policy); not performed by this research phase.
- **m6 closes issue #397.** Per the dispatch context, ride `Fixes #397` on
  the final commit that lands this milestone's work (m5's synthesis
  explicitly deferred this: "`Fixes #397` deliberately absent — m6 closes
  that issue," `desktop-distribution-m5/implement/synthesis.md:142`).
- No GitLab issue creation, no MR, no ArgoCD/AWS mutation — this milestone
  is entirely in-repo (Rust/Python source + tests + docs), no deploy-repo
  or infra surface touched.

## Alternatives considered

- **Run the 30-cycle stress and fault matrix through the full Tauri
  supervisor+window for every case.** Rejected: multiplies per-case cost by
  the window/single-instance-plugin overhead for zero additional evidence
  on cases that are purely about `lifecycle.rs`'s process-control logic;
  the supervisor-crash and 30-cycle cases specifically don't need a
  rendered window at all.
- **Inject faults via a new `ARXMCP_DESKTOP_FAULT` env var on the
  fixture-sidecar process instead of a wire-frame extension.** Rejected:
  the wire contract already has a sanctioned, tested, namespaced channel
  for exactly this ("compatible additions... under `extensions`"); adding
  a parallel env-var-based side-channel duplicates a mechanism that exists
  specifically to avoid ad hoc signaling, and env vars crossing the
  ARXMCP_-prefix boundary invite the exact FATAL-scan hazard invariant #5
  (brief-3.md §5) warns about if it ever leaked to the child by mistake.
- **Reimplement `REDACTED_FIELDS`/`RedactionFilter` verbatim in Rust.**
  Rejected: nothing in the supervisor's current or near-future scope emits
  `query`/`body_canonical`/`body_raw_latex`/`mathml` — porting an unused
  field list is dead code against the comment-density/no-dead-code
  standard; the actual shared risk is the startup-capability token, which
  gets its own narrower, actually-exercised primitive (§4).
- **Prove non-claim #2 (setsid escape) with a canary-spawning test.**
  Rejected: no shipped component spawns descendants; building a test
  fixture that does would test a scenario that cannot occur today and
  would misrepresent scope as "handled" when it is genuinely "not
  applicable yet."

## Risks and unknowns

- **`BOUND_TIMEOUT` test-only override is a new supervisor-env-var
  surface.** Must be scrubbed from the child's env by the existing
  `ARXMCP_`-prefix removal loop automatically (it already is, since the
  loop is blanket over all `ARXMCP_*` keys, `lifecycle.rs:153-157`) —
  verify this holds for whatever exact name is chosen; don't special-case
  it and accidentally exempt it from the scrub.
- **Malformed-bound and crash-before-bound races**: the exact error string
  the supervisor produces depends on OS-level pipe-close timing (whether
  the reader thread's `read_frame` sees a clean EOF or an I/O error first).
  Pin whichever is *actually observed* on this machine rather than
  asserting a guessed string — a flaky assertion on an unobserved race is
  worse than a slightly looser one.
- **30-cycle wall-clock budget and `lsof`/`ps` availability**: both are
  macOS/BSD-specific (`/usr/sbin/lsof`, BSD `ps` flags) — same
  cross-platform caveat brief-3.md §6 already raised for m4 and which m5
  did not need to resolve (macOS-only conformance gate today). If CI ever
  runs this on Linux, the flags differ (GNU `ps`, `lsof` is usually present
  but argument-compatible) — not blocking for m6 since the gate is
  documented macOS-only, but don't hardcode assumptions that would silently
  no-op elsewhere; fail loudly if the probe binary is missing rather than
  skip.
- **Sync-wave / GitOps / IRSA scope**: none apply — this milestone has no
  deploy-repo, Helm, or AWS surface.
- **Conventional-commit + GPG signing**: standard; final commit message
  should read `feat(desktop): add lifecycle fault matrix, stress and
  loopback regression\n\nFixes #397` (or equivalent, split across commits
  per file-group as m5 did — server/py, desktop/rs, tests — each still
  needing `Fixes #397` only on the commit that closes the loop, or on the
  final checkpoint commit per m5's precedent of one closing reference).

## Open questions for the user

None — the AC text, m5's synthesis/rectify, and brief-3.md's falsifiability
table are sufficient to plan m6 without further specification. The one
judgment call flagged for Phase 2 (not Phase 1) is whether to invoke
`--allow-large-diff` up front given the >800 LOC likelihood (§7) — that is
an authorization decision for the orchestrator/owner at Phase 2 kickoff,
not a question this research phase needs answered to produce a complete
plan.
