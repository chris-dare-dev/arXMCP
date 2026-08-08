# Critique — desktop-distribution-m5 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** 1a542ee..4d797a7
**Diff stats:** 19 files, 2114 LOC hand-written (7168 including the 5054-line regenerated `apps/desktop/Cargo.lock`)
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES. The code is strong: the control-stream discipline (dup the
stdout pipe, point fd 1 at stderr, close the duped fd after one write) makes a
second `bound` frame structurally impossible, the pure-ASGI gate is genuinely
unreachable from `create_app`, and AC2 hashes LIVE wire bytes rather than a
mock. Two load-bearing docs — `apps/desktop/README.md` and CLAUDE.md § 4.5 —
still describe the world as it was before this diff and are now false in the
present tense. One real correctness gap remains: the child's uvicorn drain is
unbounded, so a normal quit with a live MCP stream ends in a supervisor
SIGKILL and never runs the lifespan shutdown.

## Executive summary

- [CRITICAL] `apps/desktop/README.md:5` still says the workspace "does not yet
  contain the Tauri shell ... or the production server lifecycle adapter", and
  `:103` still defers port-zero adoption, authenticated readiness and Tauri
  exit handling to a future milestone. This diff delivered all of them, and
  `process_control.rs:5` cites that README as the platform authority.
- [CRITICAL] `CLAUDE.md:258` still reads "**Nine test markers exist**" and
  enumerates the three added since; `pyproject.toml` now registers ten, and
  `requires_desktop_stack` appears in neither the count nor the list.
- [HIGH] `server/desktop_child.py:242` leaves `timeout_graceful_shutdown` at
  `None`; the docstring calls that "a superset of the contract's floor". With
  an open `GET /mcp/` SSE stream the drain never completes, so quit costs a
  40-second hang and a SIGKILL that skips the FastAPI lifespan shutdown.
- [MEDIUM] `/status` and `/ui/status-badge` are documented supersets of
  `/readyz`, are served on the same ephemeral port, and are ungated — so the
  AC6 capability gate is not a readiness-confidentiality control.
- [MEDIUM] `shutdown_child`'s final post-SIGKILL `child.wait()` is unbounded,
  inside the one function the AC calls "bounded cleanup".
- [MEDIUM] Nothing exercises `shutdown_child`'s TERM or KILL escalation
  branches; every test drives a child that exits on the first cooperative
  signal.
- [MEDIUM] `notify_running_instance` is `#[cfg(unix)]` but speaks the plugin's
  macOS Unix-socket protocol; on Linux the plugin uses DBus, so the loser can
  never activate the winner there.
- [MEDIUM] AC3's 64-hex leak sweep covers the data root but never the
  supervisor's own stdout/stderr, which are captured to unread PIPEs.

Scope note: `state.json:36` records `allow_large_diff: true` (owner-authorized
before Phase 2), so the mandatory >400-LOC auto-finding is deliberately NOT
filed. Arithmetic for audit: 2109 insertions / 5 deletions excluding
`Cargo.lock`; 7059 / 109 including it.

## Findings

**C1 — apps/desktop/README.md denies the shell this diff just built** (CRITICAL)

**Where:** `apps/desktop/README.md:5`
**Anchor:** `not yet contain the Tauri shell, the frozen`
**What:** The README states in the present tense that the workspace "does not yet contain the Tauri shell, the frozen Python runtime, release signing, or the production server lifecycle adapter", and at `:103` that "Production port-zero adoption, authenticated server readiness, ordinary Tauri exit handling, and universal cleanup are explicitly deferred to the lifecycle walking skeleton" — this diff shipped the Tauri shell (`crates/supervisor`), the lifecycle adapter (`server/desktop_child.py` + `lifecycle.rs`), port-zero adoption, authenticated readiness and `RunEvent::Exit` handling, with no README update.
**Why it matters:** `process_control.rs:5` cites this README's "Supported boundary" section as the authority for the platform seam, and its "Development and conformance commands" block omits the supervisor build and `DESKTOP_SUPERVISOR_BIN` that `make desktop-conformance` now runs — so the one doc an agent is pointed at describes a workspace two milestones stale and gives a conformance recipe that no longer reproduces the gate.
**Proposed fix:** Rewrite `:3-7` to say the workspace now contains the contract crate, the fixture sidecar and the production supervisor + desktop-child lifecycle adapter, and that the frozen Python runtime and release signing remain deferred. Amend `:100-103` to record that m5 delivered port-zero adoption, authenticated readiness and ordinary Tauri exit handling, leaving the fault matrix / universal cleanup to m6. Add the two new lines to the command block (`cargo build --bin supervisor`, and the `DESKTOP_SUPERVISOR_BIN=... pytest tests/test_desktop_child.py -m "..."` invocation).
**Regression-guard:** Extend the existing doc-consistency test family with a check that `apps/desktop/README.md` contains no "does not yet contain"/"deferred to the lifecycle walking skeleton" phrase while `apps/desktop/crates/supervisor/src/main.rs` exists.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**C2 — CLAUDE.md still claims nine test markers; there are ten** (CRITICAL)

**Where:** `CLAUDE.md:258`
**Anchor:** `- **Nine test markers exist** (registered in `
**What:** § 4.5's marker section asserts "Nine test markers exist" and its parenthetical names the three added since the list was written; this diff registers a tenth (`requires_desktop_stack`) in `pyproject.toml` and wires it into `tests/conftest.py::_OPT_IN_MARKERS`, but neither the count, the parenthetical, nor the bulleted enumeration was updated.
**Why it matters:** § 4.5 is the checklist agents follow when adding an opt-in marker (it is the section that documents the `_OPT_IN_MARKERS` + `pyproject.toml` pairing rule, added because registering only one of the two created issue #206); a count that is false and an enumeration that silently omits the newest marker is exactly how the next agent concludes `make desktop-conformance` has no opt-in surface.
**Proposed fix:** Change "Nine" to "Ten", extend the parenthetical to "the four added since this list was written are `requires_mineru`, `requires_restic`, `requires_wheel_build` and `requires_desktop_stack`", and add a bullet for `requires_desktop_stack` naming `make desktop-conformance` and `DESKTOP_SUPERVISOR_BIN` as its prerequisites. This is the same in-place amendment pattern the parenthetical already uses.
**Regression-guard:** A test that parses the marker names out of `pyproject.toml` `[tool.pytest.ini_options].markers` and asserts every one of them appears verbatim in CLAUDE.md § 4.5.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**H1 — Unbounded uvicorn drain turns a normal quit into a SIGKILL** (HIGH)

**Where:** `server/desktop_child.py:242`
**Anchor:** `    config = uvicorn.Config(`
**What:** The child never sets `timeout_graceful_shutdown`, and the `_serve` docstring at `:233-237` defends that as "honored by construction: `timeout_graceful_shutdown` stays `None` (unbounded drain — a superset of the contract's floor)"; but `uvicorn.Server.shutdown()` with no graceful timeout spins `while (connections or tasks) and not force_exit`, and `mcp/server/streamable_http.py:659` establishes a long-lived SSE response on `GET /mcp/` with `Accept: text/event-stream` regardless of the app's `json_response=True` setting, so a client holding the spec's server-to-client stream keeps the drain loop running forever.
**Why it matters:** On the normal user-quit path (`main.rs:197` `RunEvent::Exit` -> `shutdown_child`) the supervisor waits `MIN_GRACE_MS` (35 s), sends SIGTERM — which uvicorn's captured handler maps to the `should_exit` the child has already set, so it changes nothing — waits `FORCE_AFTER_MS` (5 s), then SIGKILLs. The child therefore dies without ever reaching `await self.lifespan.shutdown()`, so the FastAPI lifespan's LanceDB/Kùzu handle closes never run — the exact unclean-close class CLAUDE.md § 3 records as the kuzu 0.11.3 mandatory-lock hazard — and every quit with a connected MCP agent costs 40 s and records `shutdown-unclean` / `child_exit: -1`.
**Proposed fix:** Pass a self-imposed bound derived from the launch frame, e.g. `uvicorn.Config(..., timeout_graceful_shutdown=max(1, launch.shutdown.grace_ms // 1000 - 5))`, so the child force-closes lingering connections and reaches the lifespan shutdown strictly inside the supervisor's grace window. Correct the docstring: an unbounded drain is not a superset of the floor — the floor constrains how long the SUPERVISOR waits, and says nothing about the child bounding itself.
**Regression-guard:** A `requires_desktop_stack` test that opens `GET /mcp/` with `Accept: text/event-stream` against the live child, sends the authenticated `shutdown` frame, and asserts `process.wait(timeout=...)` returns 0 well inside `MIN_GRACE_MS`.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**M1 — /status and /ui/status-badge leak readiness past the /readyz gate** (MEDIUM)

**Where:** `server/desktop_child.py:102`
**Anchor:** `class ReadyzStartupTokenMiddleware:`
**What:** The middleware gates only `scope["path"] == READINESS_PATH`, but `create_app` also mounts `/status` (`server/health.py:617`, whose own docstring calls it "A SUPERSET of `/readyz`" — 503/`fail` before warm, 200/`pass|warn` after) and `/ui/status-badge` (`server/routes/ui.py:241`), both fed by the same `compute_health_status` snapshot and both reachable unauthenticated on the child's ephemeral port; `SecFetchSiteMiddleware` passes any request with no `Sec-Fetch-Site` header (`server/middleware.py:622`), so a plain local HTTP client is unaffected by it.
**Why it matters:** The module docstring frames the token as a capability the child accepts "only from the private stdin `launch` frame", implying readiness is a privileged observation; in fact any local process can read readiness plus corpus version, notebook count, disk utilisation, backup recency and uptime with no capability at all — so the gate buys no confidentiality, only a supervisor-identity handshake. Nothing in the code, the tests, or the synthesis records that residual, so the next reader will over-trust it.
**Proposed fix:** Either widen the middleware's path set to `{READINESS_PATH, "/status", "/ui/status-badge"}` (the supervisor uses none of the latter two, so nothing in-tree breaks), or — if leaving them open is deliberate — say so explicitly in the `ReadyzStartupTokenMiddleware` docstring: "this gate authenticates the supervisor on `/readyz`; it is NOT a readiness-confidentiality control, since `/status` and `/ui/status-badge` report the same warm state unauthenticated."
**Regression-guard:** N/A (MEDIUM); if the widening path is taken, extend `TestReadyzStartupTokenMiddleware::test_other_paths_...` with 401 cases for `/status` and `/ui/status-badge`.
**Source critic:** milestone-adversary-critic
**Source axis:** Security / input handling

**M2 — The post-SIGKILL reap inside "bounded shutdown" is unbounded** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/lifecycle.rs:393`
**Anchor:** `    match control.child.wait() {`
**What:** `shutdown_child` bounds the cooperative wait (`grace_ms`) and the post-TERM wait (`force_after_ms`) with `wait_exit`, but the final reap after `control.child.kill()` is a bare blocking `child.wait()` with no deadline.
**Why it matters:** The function's own doc comment and AC4 both call this path "bounded"; a child wedged in uninterruptible sleep (a stalled LanceDB/Kùzu read on a slow or disconnected volume is the realistic shape here) does not respond to SIGKILL until the I/O completes, and because this runs on the `RunEvent::Exit` handler in `main.rs:199` the whole app hangs on quit with no diagnostic. I am flagging this as a low-probability but nameable state rather than a routine one.
**Proposed fix:** Reuse the existing bounded helper — `wait_exit(&mut control.child, REAP_BUDGET_MS).unwrap_or(-1)` with a small budget (2000 ms) — and record an event when the reap budget is exhausted so a leaked process is visible rather than silent. Leaving a zombie for the OS to reap at supervisor exit is strictly better than an unbounded hang on the UI quit path.
**Regression-guard:** N/A (MEDIUM).
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**M3 — No test drives shutdown_child's TERM or KILL escalation** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/lifecycle.rs:388`
**Anchor:** `    let _ = process_control::request_terminate(co`
**What:** Every test exercises only the first branch: AC3's supervisor run has the child exit on the shutdown frame (`shutdown-clean`, `child_exit: 0`), AC4 sends the frame by hand to a bare child, and the Rust unit test `wait_exit_reaps_a_fast_child_and_times_out_on_a_slow_one` tests `wait_exit` and `request_terminate` in isolation but never `shutdown_child`'s composition of them — so the `request_terminate` -> second `wait_exit` -> `kill` -> reap sequence is entirely uncovered.
**Why it matters:** This is the safety net for exactly the H1 case above (an unresponsive child) and for m6's fault matrix, and it is the only code that prevents an orphaned server process holding the ephemeral port and the LanceDB directory. The synthesis's Deferred list names "interactive-quit coverage" as the gap, not the escalation branches, so the hole is undisclosed. Note the AC only requires the normal path, so this is a coverage observation rather than an unmet criterion.
**Proposed fix:** Add a Rust unit test that builds a `ChildControl` around a child that ignores stdin EOF (`/bin/sleep 60` with a piped stdin), with `grace_ms`/`force_after_ms` overridden to small values, and asserts `shutdown_child` returns within the two budgets and that the PID is gone afterwards. Making `grace_ms`/`force_after_ms` injectable for the test is a two-field change since they are already `ChildControl` fields.
**Regression-guard:** N/A (MEDIUM).
**Source critic:** milestone-adversary-critic
**Source axis:** Test discipline

**M4 — Loser activation is dead code on Linux, contradicting the seam claim** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:103`
**Anchor:** `#[cfg(unix)]`
**What:** `notify_running_instance` is gated on `#[cfg(unix)]` while its own doc comment says it is the "Client half of tauri-plugin-single-instance's macOS protocol"; the plugin's Linux implementation is DBus-based (`platform_impl/linux.rs` uses `zbus`, registering `<identifier>.SingleInstance`) and never creates a Unix socket, so on Linux the `UnixStream::connect("/tmp/com_arxmcp_desktop_si.sock")` always fails and the loser silently exits without activating anything. (The macOS path is correct — the plugin derives `/tmp/{identifier with '.' and '-' replaced by '_'}_si.sock`, which matches the literal exactly.)
**Why it matters:** `apps/desktop/README.md:11-17` promises Linux x86-64 as a portability target of "the same workspace and wire protocol" and forbids "a macOS-only server protocol", and the implement synthesis states flatly that "activation still works". On Linux the second launch is a no-op with no window focus and no event recorded, and nothing in the tree says so. AC3's second clause is still satisfied ("or exits clearly"), so this is a portability/comment-accuracy defect, not an unmet criterion.
**Proposed fix:** Narrow the cfg to `#[cfg(target_os = "macos")]` with a `#[cfg(not(target_os = "macos"))]` stub returning `Ok(())`, and amend the doc comment to state that Linux activation requires a DBus client half that is not yet implemented. Record a `lock-contended` field such as `{"activated": false}` so the loser's outcome is observable in the event log.
**Regression-guard:** N/A (MEDIUM).
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**M5 — AC3's leak sweep never reads the supervisor's own stdout/stderr** (MEDIUM)

**Where:** `tests/test_desktop_child.py:388`
**Anchor:** `    allowed = {identity.sha256.encode("ascii")}`
**What:** The structural 64-hex sweep walks `root.rglob("*")` only; both supervisor processes are spawned with `stdout=subprocess.PIPE` and `stderr=subprocess.PIPE`, and those bytes are read at `:362` purely to decorate an assertion message — they are never scanned for the capability or for any unexpected 64-hex string. Nothing outside the data root is covered either.
**Why it matters:** The supervisor's stderr is precisely where a leak would surface (`fail()` uses `eprintln!`, and any future `{:?}` on a frame or a panic payload lands there), so the milestone's strongest anti-leak evidence has a hole exactly at the stream the README's "Secret handling" section names ("never a ... stdout/stderr diagnostic"). Separately, leaving both PIPEs unread across `first.wait(timeout=300)` is the classic pipe-buffer deadlock: a chatty WebKit process on macOS filling the 64 KB buffer turns the test into a five-minute hang before it fails.
**Proposed fix:** Replace the `wait(timeout=300)` + post-hoc `stderr.read()` pair with `out, err = proc.communicate(timeout=300)` for both processes (which drains the pipes concurrently and eliminates the deadlock), then feed `out + err` for both supervisors into the same `_HEX64` allow-list scan and into the `secret not in ...` check.
**Regression-guard:** N/A (MEDIUM).
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**L1 — The shared-child fixture's "AC4 runs last" contract is prose-only** (LOW)

**Where:** `tests/test_desktop_child.py:160`
**Anchor:** `@pytest.fixture(scope="module")`
**What:** One module-scoped `real_child` boots a real server shared by AC1, AC2 and AC4; AC4 terminates it, and the only thing keeping AC1/AC2 ahead of it is source order plus a docstring sentence ("Runs LAST among the shared-fixture tests because it stops the child").
**Why it matters:** Reordering the file, or any future `-p randomly` / `-n auto` run, leaves AC1 and AC2 talking to a dead child. The failure would be loud (`ConnectionRefusedError`), and neither `pytest-randomly` nor `pytest-xdist` is installed today, which is why this is LOW rather than higher — but the invariant is unasserted and free to assert.
**Proposed fix:** Add `assert real_child.process.poll() is None` as the first line of AC1 and AC2 so a reordering fails with the real reason, or have AC4 take a function-scoped child of its own so the ordering constraint disappears entirely.
**Regression-guard:** N/A (LOW).
**Source critic:** milestone-adversary-critic
**Source axis:** Test discipline

**L2 — The desktop 401 short-circuits the SecurityHeaders invariant** (LOW)

**Where:** `server/desktop_child.py:130`
**Anchor:** `            await _send_json_error(`
**What:** `ReadyzStartupTokenMiddleware` wraps the fully-built app, making it the OUTERMOST layer, so its 401 is emitted before `SecurityHeadersMiddleware` ever runs and carries neither `X-Content-Type-Options: nosniff` nor `X-Frame-Options: DENY`.
**Why it matters:** `server/middleware.py:31-36` states the mount order was chosen specifically "so even error responses from inner middlewares (e.g. OriginValidation's 403) carry the security headers"; the desktop child is now the one response in the tree that violates that stated invariant. Impact is small (a loopback JSON 401), which is why this is LOW.
**Proposed fix:** Add the two headers to the `_send_json_error` call's response, or pass them explicitly, e.g. by emitting the 401 through a small local helper that appends `(b"x-content-type-options", b"nosniff")` and `(b"x-frame-options", b"DENY")` before the body.
**Regression-guard:** N/A (LOW).
**Source critic:** milestone-adversary-critic
**Source axis:** Security / input handling

## What was done well

- The control-stream discipline is the strongest part of the diff: duping the
  real stdout to `protocol_fd`, pointing fd 1 at stderr, and `os.close`-ing the
  duped fd immediately after the single `bound` write makes a second control
  frame structurally impossible rather than merely unlikely — and AC4 confirms
  it by asserting the stdout remainder is empty.
- Hand-driving `startup()` / `main_loop()` / `shutdown()` is correctly
  motivated: uvicorn's `startup()` really does `await lifespan.startup()`
  before `loop.create_server(sock=...)`, so `bound` genuinely lands after both
  the warm-up and the LISTEN transition, and the `should_exit or not started`
  guard catches the lifespan-failure path uvicorn signals by flag rather than
  by exception.
- `ReadyzStartupTokenMiddleware` is enforced as unreachable from `create_app`
  by structure and by test — the AST identifier scan deliberately excludes
  docstrings so prose can neither mask nor fake a `BaseHTTPMiddleware` or
  `add_middleware` reference. That is a materially better guard than a grep.
- AC2 hashes the LIVE `tools/list` wire bytes through the same
  `compute_tool_schema_hash` the pin test uses; a mocked or replayed response
  cannot satisfy it, and it independently re-proves the BP1 surface is
  untouched.
- AC4's connect probe is the honest shape the AC demanded: it must first
  SUCCEED against the live server and then raise the specific
  `ConnectionRefusedError`, so a silently-broken probe fails one side or the
  other.
- AC3's leak check scans for ANY unexpected 64-hex string rather than for the
  known token, which catches a leak of a value the test does not know — the
  right generalisation for a race whose winner is nondeterministic.
- Acquiring the fs2 lock before any Tauri machinery, and the reasoning for why
  the loser must never register the single-instance listener (the plugin's
  notify path exits whichever process connects second), is a genuine
  correctness insight, not a workaround.
- Dependency hygiene is clean: every new Cargo dependency is `=`-pinned,
  `Plan` carries `deny_unknown_fields` with a unit test proving a stray
  `startup_token` field is rejected, and the barrier path is confined to the
  data root.
- The deviations section is candid about the two live-discovered changes (the
  `tauri-codegen` icon requirement and the `webview-data-url` feature) and
  about what was deferred, which made this review faster and is the behaviour
  the pipeline wants to reward.

Severity counts: C2 H1 M5 L2

## Recommended rectification order

C1, C2, H1, M1, M5, M2, M3, M4, L1, L2
