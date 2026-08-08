# Critique (merged) — desktop-distribution-m5

**Critics:** milestone-adversary-critic, milestone-arxmcp-critic, milestone-infra-safety-critic
**Commit range:** 1a542ee..4d797a7
**Diff stats:** 19 files, 2114 LOC hand-written (7168 including the 5054-line regenerated `apps/desktop/Cargo.lock`)
**Critique format version:** 1.0

> **Merge note.** Each critic authored its ids from 1 within its own file, so
> they collided across files. `findings.py merge` renumbered them into one
> gapless per-severity sequence in critic dispatch order; bodies are verbatim.
> **Phase 4 dispositions attach to the MERGED ids below**, not to the ids in
> the per-critic files. Re-running merge after a critic file changes will shift
> these ids - see milestone-pipeline-critique-format.md.
>
> - `milestone-adversary-critic` (adversary.md): ids unchanged
> - `milestone-arxmcp-critic` (arxmcp.md): H1->H2, M1->M6, M2->M7, M3->M8, M4->M9, M5->M10, M6->M11, M7->M12, M8->M13, M9->M14, M10->M15, L1->L3, L2->L4, L3->L5, L4->L6, L5->L7
> - `milestone-infra-safety-critic` (infra-safety.md): H1->H3, M1->M16, M2->M17, M3->M18, L1->L8, L2->L9, L3->L10, L4->L11

## Verdict

**SHIP-WITH-FIXES** — the most severe of the per-critic verdicts below.

### milestone-adversary-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES. The code is strong: the control-stream discipline (dup the
stdout pipe, point fd 1 at stderr, close the duped fd after one write) makes a
second `bound` frame structurally impossible, the pure-ASGI gate is genuinely
unreachable from `create_app`, and AC2 hashes LIVE wire bytes rather than a
mock. Two load-bearing docs — `apps/desktop/README.md` and CLAUDE.md § 4.5 —
still describe the world as it was before this diff and are now false in the
present tense. One real correctness gap remains: the child's uvicorn drain is
unbounded, so a normal quit with a live MCP stream ends in a supervisor
SIGKILL and never runs the lifespan shutdown.

### milestone-arxmcp-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES

The lifecycle design is sound and the evidence is real rather than mocked — the child genuinely pre-binds loopback outside `Config`, the capability gate is genuinely pure-ASGI and genuinely unreachable from `create_app`, and the MCP smoke genuinely crosses the wire. One HIGH lands: the new boot path is the only way to run this server that never installs the E13_S08 `RedactionFilter` or the default JSON log format, so the entire desktop distribution runs outside a shipped security control. The remaining ten MEDIUMs are cheap, localized, and mostly about the durability of the gate rather than the correctness of the cycle.

### milestone-infra-safety-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES

The infra surface is small and mostly disciplined: exit codes propagate correctly on every new `desktop-conformance` recipe line, both harness env vars are scoped to exactly the line that needs them, every new Cargo dependency is exact-`=`-pinned with a committed lockfile carrying zero git sources, and the `.gitignore` entry for `gen/` hides only derived JSON Schemas — the effective ACL lives in a `capabilities/` tree that does not exist, so the webview is granted zero Tauri commands. The one HIGH is that the target's stated ALL-OR-NOTHING zero-skip contract is enforced by convention only: I ran the suite with a mismatched marker expression and got `4 skipped, 9 passed`, exit 0, which is the m3 M4 failure mode wearing a new hat. The three MEDIUMs are latent rather than live — an unused `tauri-plugin-shell` that widens the grantable permission surface, an unpinned deny-by-default ACL, and no Rust toolchain pin behind a `clippy -D warnings` gate.

## Executive summary — milestone-adversary-critic

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

## Executive summary — milestone-arxmcp-critic

- [HIGH] `server/desktop_child.py` calls bare `logging.basicConfig` and never `server.observability.logging_setup.configure`, so the desktop distribution runs the full MCP server with the Threat-8 redaction filter absent and the 12-factor JSON formatter not installed.
- [MEDIUM] **Axis 1 answer — the live-hash equivalence is VALID but narrower than the pin.** `compute_tool_schema_hash([Tool.model_validate(t) …])` re-canonicalizes through the same `ListToolsResult`+`sort_keys`+`ensure_ascii` path, so key ordering, whitespace and transport framing are correctly normalized away rather than being false-mismatch sources. The real gap is the other direction: the test rebuilds a FRESH envelope from `payload["result"]["tools"]`, discarding the wire's `nextCursor`/`_meta`, which is exactly the envelope the F6 fix put inside the pin.
- [MEDIUM] The `/readyz` header name is hardcoded as `b"x-arxmcp-startup-token"` instead of derived from `desktop_contract.STARTUP_TOKEN_HEADER`, so a contract rename silently 401s every desktop launch forever.
- [MEDIUM] The stdin shutdown lease is armed only AFTER `uvicorn.Server.startup()` returns, so a user quitting during the 5–30 s warm-up gets a ~40 s hang ending in SIGKILL.
- [MEDIUM] `make desktop-conformance` now spawns two supervisors with `stdout`/`stderr` on undrained `subprocess.PIPE` and a 300 s `wait()` — the textbook pipe-buffer deadlock, on a Tauri/WKWebView process that is not quiet.
- [MEDIUM] The gate now force-enables `ARXMCP_ENABLE_RERANK=1`, adding a real BGE-reranker-v2-m3 load (fail-closed on absence) to a suite carrying neither `requires_model` nor a declared model prerequisite.
- [MEDIUM] `apps/desktop/README.md:5` still says the workspace "does not yet contain the Tauri shell … or the production server lifecycle adapter" — this commit added both.
- [MEDIUM] Axes 2 (math fidelity), 6 (tier sequencing) and 7 (no-fork) are clean: no LaTeX/MathML/chunker path is touched, dependencies e2/m2/m3 are all landed, and every one of the 453 new lockfile entries resolves to `registry+…crates.io-index` with no git/fork source and no lifted-code header.

## Executive summary — milestone-infra-safety-critic

- [HIGH] `make desktop-conformance` exits 0 with 4 skipped tests if the marker name and the Makefile's `-m` string ever drift — empirically reproduced, not reasoned about.
- [MEDIUM] `tauri-plugin-shell` is registered and depended on but never called; the child is spawned with `std::process::Command`, so the plugin only widens the set of permissions a future capability file could grant the webview.
- [MEDIUM] The deny-by-default ACL (no `capabilities/` dir, generated `capabilities.json` is `{}`) is correct but unpinned by any test, and the generated manifest a reviewer could diff is now gitignored.
- [MEDIUM] No `rust-toolchain.toml` and no `rust-version` MSRV, while the gate runs `cargo clippy -D warnings` over ~400 newly-added transitive crates.
- [LOW] `.gitignore` ignores the whole `gen/` tree; Tauri's own template ignores `gen/schemas` specifically because `gen/android` / `gen/apple` are meant to be committed.
- [LOW] `wait_exit` returns `None` for both "budget expired" and "`try_wait` errored", so an error escalates to `SIGTERM` on a PID whose reap state is unknown.
- [LOW] The single-instance activation socket path `/tmp/com_arxmcp_desktop_si.sock` is hand-copied from plugin internals, world-squattable, and untested.
- [LOW] The 1×1 placeholder icon is the right call today (`bundle.active: false`) but nothing stops it becoming the shipped Linux app icon when bundling is enabled.

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

**H2 — Desktop boot path never installs RedactionFilter or the JSON formatter** (HIGH)

**Where:** `server/desktop_child.py:272`
**Anchor:** `    logging.basicConfig(level=os.environ`
**What:** The desktop child configures logging with bare `logging.basicConfig` and never calls `server.observability.logging_setup.configure(cfg.log_level, cfg.log_format)`, which is the sole installer of the E13_S08 `RedactionFilter` (grep: `server/cli.py:159` is its only caller in the tree).
**Why it matters:** Every desktop launch runs the full MCP server, writes its stderr to a persisted `<data_root>/logs/desktop-child.log`, and does so with the Threat-8 redaction invariant (`REDACTED_FIELDS` = query / body_canonical / body_raw_latex / mathml stripped at INFO+) structurally absent and the 12-factor JSON format silently downgraded to text — a shipped security control that `make up` has and the shipped desktop product does not.
**Proposed fix:** After `cfg = Config(data_dir=Path(frame.data_root))` succeeds and before `create_app(cfg)`, call `from server.observability.logging_setup import configure as _configure_logging; _configure_logging(cfg.log_level, cfg.log_format)` — mirroring `server/cli.py:159-163`. Keep the pre-Config `basicConfig` so the launch-rejection FATAL still lands on stderr.
**Regression-guard:** Add to `tests/test_desktop_child.py` a test asserting `RedactionFilter` appears in `logging.getLogger().filters` (or on a root handler) after the child's logging setup runs — e.g. call the extracted `_configure_child_logging(cfg)` helper directly and assert `any(isinstance(f, RedactionFilter) for f in logging.getLogger().filters)`, mirroring `tests/security/test_log_redaction.py::TestConfigure::test_configure_installs_redaction_filter_on_root`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security threat-model coverage

**H3 — desktop-conformance exits 0 with skips when the marker string drifts** (HIGH)

**Where:** `Makefile:158`
**Anchor:** `DESKTOP_SUPERVISOR_BIN="$(CURDIR)/apps/de`
**What:** `-m "requires_desktop_stack or not requires_desktop_stack"` is a tautology for ANY token, so pytest's own filter selects everything regardless of the name; the only thing that actually opts the four real-stack tests IN is `tests/conftest.py:110`'s substring check `marker not in markexpr`, and when that check fails the tests are silently skipped while pytest still exits 0.
**Why it matters:** The target's documented contract is ALL-OR-NOTHING with zero skips (the m3 M4 finding), and I reproduced the degradation directly — `pytest tests/test_desktop_child.py -m "foo or not foo"` returns `4 skipped, 9 passed`, exit 0 — so a rename of the marker, a typo in either the Makefile string or `_OPT_IN_MARKERS`, or a refactor of the conftest hook turns the authoritative desktop gate green while every real-server, supervisor-binary and MCP-smoke assertion is skipped; `pyproject.toml:364` is bare `addopts = "-q"` with no `--strict-markers`, so a misspelled marker on a test raises a warning, not an error.
**Proposed fix:** Two cheap halves. (a) Extend the existing Makefile-shape meta-test `tests/test_desktop_contract.py:310` (the m3 precedent that already pins `--bin fixture-sidecar`, `ARXMCP_FIXTURE_SIDECAR=` and build-before-run ordering) to also assert `--bin supervisor` in the target, `DESKTOP_SUPERVISOR_BIN=` in the target, `target.index("--bin supervisor") < target.index("DESKTOP_SUPERVISOR_BIN=")`, and — the load-bearing part — that the marker token appearing in the recipe's `-m` string is a member of `tests.conftest._OPT_IN_MARKERS` (import it; do not re-hardcode the literal). (b) Add a zero-skip guard: a `pytest_sessionfinish` hook in `tests/conftest.py` that sets `session.exitstatus` non-zero when any test reports `skipped` while `DESKTOP_SUPERVISOR_BIN` is set in the environment, so the gate fails loudly instead of degrading.
**Regression-guard:** A test asserting the Makefile's `-m` marker token is in `tests.conftest._OPT_IN_MARKERS`, plus a check that running `tests/test_desktop_child.py` with a non-matching marker expression and `DESKTOP_SUPERVISOR_BIN` set exits non-zero.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

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

**M6 — AC2's live hash discards the ListToolsResult envelope the pin covers** (MEDIUM)

**Where:** `tests/test_desktop_child.py:307`
**Anchor:** `    live_hash = compute_tool_schema_hash`
**What:** The test extracts only `payload["result"]["tools"]` and feeds it to `compute_tool_schema_hash`, which internally constructs a FRESH `ListToolsResult(tools=tools)` — so the wire response's own `nextCursor` and any top-level `_meta` are dropped before hashing, which is precisely the envelope the E06_S06 F6 fix deliberately folded into the pin.
**Why it matters:** The AC's stated property ("the LIVE response bytes hash equal to `EXPECTED_TOOL_SCHEMA_SHA256`") is proven for the tool array but not for the envelope, so a future E07_S04 pagination cursor or a top-level `_meta` injection — a real BP1 prompt-cache-invalidating change the pin exists to catch — can appear on the desktop wire while this gate stays green.
**Proposed fix:** Hash the wire's own envelope rather than a reconstructed one: `ListToolsResult.model_validate(payload["result"])`, then reuse `_serialize_tools`/`compute_tool_schema_hash` on that instance (or assert `set(payload["result"]) == {"tools"}` alongside the existing tool-array hash). Either is ≤10 LOC and keeps the live-bytes provenance intact.
**Regression-guard:** In `test_ac2_mcp_smoke_live_schema_hash`, add `assert set(payload["result"]) == {"tools"}` so an envelope key appearing on the wire fails the gate instead of being silently discarded.
**Source critic:** milestone-arxmcp-critic
**Source axis:** cache byte-stability

**M7 — Capability header name hardcoded, not derived from the contract constant** (MEDIUM)

**Where:** `server/desktop_child.py:128`
**Anchor:** `        supplied = _get_header(headers, b"x-a`
**What:** `ReadyzStartupTokenMiddleware` matches the literal `b"x-arxmcp-startup-token"` while the Rust supervisor sends `arxmcp_desktop_contract::STARTUP_TOKEN_HEADER`; `server/desktop_contract.py:20` defines the same constant in Python but the child's import list omits it.
**Why it matters:** The header name is now stated in three places with only one of them authoritative, so a contract-level rename ships a supervisor that sends the new name and a child that checks the old one — every `/readyz` poll returns 401 until `READY_DEADLINE` and the desktop app quits with `lifecycle-failed`, with no test failing first.
**Proposed fix:** Import `STARTUP_TOKEN_HEADER` alongside the other contract names and use `STARTUP_TOKEN_HEADER.lower().encode("ascii")` in `__call__`; drop the literal.
**Regression-guard:** `assert STARTUP_TOKEN_HEADER.lower().encode("ascii") == b"x-arxmcp-startup-token"` plus an existing-style middleware test that builds the header name from the constant rather than a literal.
**Source critic:** milestone-arxmcp-critic
**Source axis:** MCP spec compliance

**M8 — Shutdown lease is not armed during the 5–30 s warm-up window** (MEDIUM)

**Where:** `server/desktop_child.py:261`
**Anchor:** `        threading.Thread(`
**What:** `_watch_stdin` is started only after `await server.startup(sockets=[sock])` returns, so for the entire eager BGE-M3/LanceDB warm-up neither an authenticated `shutdown` frame nor stdin EOF is observed.
**Why it matters:** A user quitting the splash window during warm-up drives `shutdown_child`, which waits `grace_ms` (35 s) with nobody listening, then SIGTERMs into a `startup()` that does not poll `should_exit`, then SIGKILLs 5 s later — a ~40 s hang on a plain quit, with `shutdown_child` returning `-1` instead of a clean exit, on the single most common non-smoke exit path.
**Proposed fix:** Move the `threading.Thread(target=_watch_stdin, …).start()` call to immediately before `await server.startup(sockets=[sock])`. `server` already exists at that point, and the existing `if server.should_exit or not server.started: return 1` guard immediately after `startup()` then converts an early quit into a fast, clean exit-1 rather than a forced kill.
**Regression-guard:** A `requires_desktop_stack` test that writes a valid `shutdown` frame immediately after the launch frame (before `bound` is read) and asserts the child exits within `MIN_GRACE_MS` without needing SIGTERM.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security threat-model coverage

**M9 — AC3 spawns supervisors with undrained PIPEs and a 300 s wait** (MEDIUM)

**Where:** `tests/test_desktop_child.py:344`
**Anchor:** `            stdout=subprocess.PIPE,`
**What:** Both supervisor processes are spawned with `stdout=subprocess.PIPE` and `stderr=subprocess.PIPE`, then `first.wait(timeout=300)` / `second.wait(timeout=300)` are called with nothing reading either pipe until after the waits complete.
**Why it matters:** This is the classic `Popen` deadlock — a Tauri/WKWebView process that emits more than the ~64 KB pipe buffer to stderr blocks forever on write, the supervisor never exits, and `make desktop-conformance` burns 600 s before failing with `TimeoutExpired` for a reason that has nothing to do with single-instance arbitration.
**Proposed fix:** Replace the `wait()` pair with `first.communicate(timeout=300)` / `second.communicate(timeout=300)` (which drain both pipes concurrently) and take `errors` from their return values, or redirect both children's stderr to files under the data root — which has the bonus of putting supervisor stderr inside the AC3 64-hex secret sweep.
**Regression-guard:** No new test needed; the change is the guard. Optionally assert the captured stderr is non-empty on failure so the diagnostic path is exercised.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M10 — AC4 destroys the module-scoped fixture that later tests would share** (MEDIUM)

**Where:** `tests/test_desktop_child.py:397`
**Anchor:** `def test_ac4_normal_shutdown_leaves_noth`
**What:** `test_ac4_normal_shutdown_leaves_nothing` shuts down the module-scoped `real_child` server and asserts the port is refused, with correctness resting entirely on it happening to be the last `requires_desktop_stack` test in file order (the docstring says "Runs LAST" but nothing enforces it).
**Why it matters:** m6 explicitly owns the fault matrix, the 30-cycle stress and the socket-level loopback regression, all of which will add `requires_desktop_stack` tests to this file — any of them appended after AC4 silently receives a dead server and fails for an unrelated reason, and a `-k`/`-p no:randomly` change or a file reorder trips the same wire today.
**Proposed fix:** Give AC4 its own function-scoped child (boot cost is already paid once per test-session for the module fixture, so add a second short-lived boot) or move the teardown assertions into the `real_child` fixture's `finally` block so no test owns the kill. Cheapest interim: add `@pytest.mark.order(...)`-free enforcement by having the fixture expose a `stopped` flag that AC1/AC2 assert is False.
**Regression-guard:** In the `real_child` fixture, set `namespace.stopped = True` when the child is stopped and add `assert not real_child.stopped` at the top of AC1 and AC2, so a reordering fails loudly and immediately.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing

**M11 — Conformance gate silently acquires a real reranker-model prerequisite** (MEDIUM)

**Where:** `tests/test_desktop_child.py:85`
**Anchor:** `    env["ARXMCP_ENABLE_RERANK"] = "1"`
**What:** The child env force-enables rerank purely so the AC1 warm map can assert all-three-true; `server/resources.py:726` then loads BGE-reranker-v2-m3 at startup and raises when it cannot, so `make desktop-conformance` now hard-requires a cached (or downloadable) third model.
**Why it matters:** The project's own convention double-gates real model loads behind `requires_model` plus a per-model env var (`ARXMCP_RUN_REAL_BGE_RERANKER=1`); this test carries neither, and the `requires_desktop_stack` marker text in `pyproject.toml` names only "BGE-M3/LanceDB warm-up" — so a fresh clone running the mandatory boundary gate fails on a HuggingFace fetch the gate never declared.
**Proposed fix:** Drop `ARXMCP_ENABLE_RERANK=1` and assert what the desktop default actually warms (`ready["warm"]["embedder"] is True and ready["warm"]["lancedb"] is True` and `isinstance(ready["warm"]["reranker"], bool)`); or keep it and add `requires_model` to AC1 plus the reranker download to the `requires_desktop_stack` marker description.
**Regression-guard:** Assert the reranker prerequisite explicitly — either `assert "ARXMCP_ENABLE_RERANK" not in _child_env()` (if dropped) or a marker-text test asserting `"reranker"` appears in the `requires_desktop_stack` registration string.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M12 — Hardcoded machine-global /tmp socket path in the supervisor** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:107`
**Anchor:** `    let mut stream = UnixStream::connect(`
**What:** `notify_running_instance` connects to the literal `/tmp/com_arxmcp_desktop_si.sock`, re-deriving a third-party plugin's private socket path by hand, and writes the process cwd plus full argv to it.
**Why it matters:** Two hits at once — the local-first constraint forbids hardcoded `/tmp` absolute paths (all runtime state belongs under the received data root), and `/tmp` is world-writable on macOS, so any local user can pre-bind that path and receive the loser's cwd/argv or deny single-instance activation; the synthesis already records the machine-global collision between a conformance run and a real installed app.
**Proposed fix:** Derive the path from the identifier in `tauri.conf.json` via a single named constant beside `BARRIER_ENV`/`PLAN_ENV` with a comment pinning the plugin version whose derivation it mirrors, and skip the notify when `fs::metadata(...).uid()` is not the current uid. If activation is not load-bearing for m5, gate the whole call behind the plan (`plan.smoke == false`) so conformance runs never touch a machine-global path.
**Regression-guard:** A Rust unit test asserting the socket path is produced by the named constant/derivation function (not a scattered literal) and that the notify is skipped in smoke mode.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first + Docker constraint

**M13 — 453 new transitive crates enter the shipped surface with no supply-chain gate** (MEDIUM)

**Where:** `apps/desktop/Cargo.toml:22`
**Anchor:** `tauri = "=2.11.5"`
**What:** The lockfile goes from 27 to 480 packages (`git show 1a542ee:apps/desktop/Cargo.lock | grep -c '^name = '` → 27; at `4d797a7` → 480) and neither `make desktop-conformance` nor any other target runs `cargo audit` / `cargo deny`; no license or advisory census is recorded anywhere in the diff.
**Why it matters:** This is the first commit to put a 453-crate transitive graph into a distribution that ships to end users, in a repo whose E13 security audit is a completed epic — an advisory or a non-permissive transitive license would reach a release with nothing in the tree able to notice.
**Proposed fix:** Add a `cargo audit --file apps/desktop/Cargo.lock` (or `cargo deny check advisories licenses`) step to `desktop-conformance`, tolerant of the tool being absent only via an explicit opt-out variable, and record the license census in `apps/desktop/README.md` beside the existing "Supported boundary" section. Note the `=`-pinning of every direct dep is already correct and should stay.
**Regression-guard:** The Makefile step itself; plus a test asserting `apps/desktop/Cargo.lock` contains no `source = "git` entry, which cheaply pins the no-fork half.
**Source critic:** milestone-arxmcp-critic
**Source axis:** no-fork policy

**M14 — apps/desktop/README.md now contradicts the tree it documents** (MEDIUM)

**Where:** `apps/desktop/README.md:5`
**Anchor:** `not yet contain the Tauri shell, the fro`
**What:** The README states the workspace "does not yet contain the Tauri shell … or the production server lifecycle adapter; those belong to the next desktop milestones", and its "Development and conformance commands" block omits `--bin supervisor` and `DESKTOP_SUPERVISOR_BIN`; this commit added the Tauri shell, the lifecycle adapter, and both gate steps.
**Why it matters:** `apps/desktop/README.md` is the only operator-facing doc for the desktop boundary (the doc-placement rule forbids any other Markdown there), and the code-comment contract makes a stale statement a bug — an operator reproducing the gate by hand from this file builds only the fixture sidecar and never the supervisor.
**Proposed fix:** Update the opening paragraph to name the supervisor crate and the production lifecycle adapter as landed, list what is still absent (frozen Python runtime, release signing, launch-plan authoring), and add the two new `desktop-conformance` lines to the expanded command block.
**Regression-guard:** Optional for MEDIUM; a cheap one is a test asserting `"supervisor"` appears in `apps/desktop/README.md` whenever `apps/desktop/crates/supervisor/` exists.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M15 — 2 s MCP-smoke timeout with no retry can quit a healthy desktop app** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/lifecycle.rs:30`
**Anchor:** `const PROBE_TIMEOUT: Duration = Duration`
**What:** `mcp_smoke`'s three POSTs each use `PROBE_TIMEOUT` (2 s) for connect, read and write, with no `poll_until` retry — unlike the health and readiness probes, which retry for 60 s and 120 s respectively.
**Why it matters:** In the production (`smoke:false`) path a single transient 2 s overrun makes `cycle` return `Err`, which drives `run_cycle` → `handle.exit(1)` → the whole desktop app quits after the console was one step from rendering; the machine in question has just finished loading BGE-M3 and LanceDB, which is exactly when a 2 s budget is least safe, and the user sees no reason (m5 ships no failed render state).
**Proposed fix:** Give the smoke its own budget — either a dedicated `SMOKE_TIMEOUT: Duration = Duration::from_secs(15)` passed to `mcp_post`, or wrap `mcp_smoke` in the existing `poll_until` with a 60 s deadline. In the non-smoke path, prefer recording `mcp-smoke-failed` and still navigating the window over exiting the app.
**Regression-guard:** A Rust unit test that drives `mcp_post` against a deliberately slow loopback listener and asserts the smoke budget, not `PROBE_TIMEOUT`, governs it.
**Source critic:** milestone-arxmcp-critic
**Source axis:** MCP spec compliance

**M16 — Unused tauri-plugin-shell widens the grantable webview permission surface** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:169`
**Anchor:** `.plugin(tauri_plugin_shell::init())`
**What:** The shell plugin is initialized and declared as a dependency (`apps/desktop/crates/supervisor/Cargo.toml:18`), but nothing in the crate calls it — the child is spawned with `std::process::Command` at `apps/desktop/crates/supervisor/src/lifecycle.rs:133`, and a repo-wide grep finds only the `init()` line and the two manifest entries.
**Why it matters:** Registering it adds `shell` to the compiled ACL manifest, so `shell:allow-execute` / `allow-spawn` / `allow-open` / `allow-kill` become grantable to a webview that renders HTTP content served by the child; today's zero-capability posture makes that inert, but it converts a future one-line `shell:default` grant plus a console XSS into local command execution, and it carries build and supply-chain weight for no functional benefit.
**Proposed fix:** Delete the `.plugin(tauri_plugin_shell::init())` line, drop `tauri-plugin-shell.workspace = true` from the supervisor manifest and `tauri-plugin-shell = "=2.3.5"` from `apps/desktop/Cargo.toml:24` (no other crate references it), then re-run `cargo build --locked` and commit the refreshed `Cargo.lock`.
**Regression-guard:** Optional — assert `tauri_plugin_shell` does not appear in `apps/desktop/crates/supervisor/src/`.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline (build-script + dependency hygiene)

**M17 — Deny-by-default Tauri ACL is correct but unpinned by any test** (MEDIUM)

**Where:** `.gitignore:77`
**Anchor:** `apps/desktop/crates/supervisor/gen/`
**What:** The supervisor has no `capabilities/` directory and `tauri.conf.json` declares no `app.security.capabilities`, so the generated `gen/schemas/capabilities.json` is `{}` and the webview is granted zero Tauri commands — the correct posture — but nothing asserts it, and the generated artifact that would surface the drift is now ignored.
**Why it matters:** The window navigates to `bound.ui_url` (HTTP content served by the child), so the ACL is the boundary between a console-side scripting bug and host access; a future capability file can be added in a single commit with the gate noticing nothing, and the previously-visible `gen/schemas/acl-manifests.json` diff is no longer available as an incidental review signal.
**Proposed fix:** Add a short test beside the other desktop conformance tests asserting that `apps/desktop/crates/supervisor/capabilities/` is absent-or-empty and that the parsed `tauri.conf.json` has no `app.security.capabilities` key, so any future grant must land together with an explicit, reviewable test edit.
**Regression-guard:** `tests/test_desktop_child.py::test_supervisor_grants_no_webview_capabilities`
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline (build-script + generated-artifact hygiene)

**M18 — No Rust toolchain pin or MSRV behind a `clippy -D warnings` gate** (MEDIUM)

**Where:** `apps/desktop/Cargo.toml:22`
**Anchor:** `tauri = "=2.11.5"`
**What:** The workspace has no `rust-toolchain.toml` and no `rust-version` in any manifest, while `Makefile:152-154` gates on `cargo fmt --check` and `cargo clippy --all-targets --all-features -D warnings`.
**Why it matters:** `-D warnings` makes any lint added in a future stable Rust a hard gate failure unrelated to the change under test, and this diff sharply increases the exposure by putting the whole tauri dependency tree behind that gate; separately, tauri 2.11 raises the effective MSRV well above the edition-2021 floor, so a developer on an older toolchain gets an obscure transitive-crate error instead of a clear "upgrade rustc" message.
**Proposed fix:** Add `apps/desktop/rust-toolchain.toml` pinning `[toolchain] channel = "<the version the gate was measured on>"` with `components = ["clippy", "rustfmt"]`, and add a matching `rust-version` to `[workspace.package]` so `cargo build` fails with the real reason on an old toolchain.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

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

**L3 — /readyz 401 responses bypass the whole server middleware stack** (LOW)

**Where:** `server/desktop_child.py:130`
**Anchor:** `            await _send_json_error(`
**What:** The gate wraps the `create_app` result from outside, so it is strictly outermost; a 401 is emitted without ever reaching `SecurityHeadersMiddleware`, `OriginValidationMiddleware`, `SecFetchSiteMiddleware`, or the tracing/metrics middlewares.
**Why it matters:** `/readyz` 401s are the only responses the desktop process can emit without `X-Content-Type-Options: nosniff` / `X-Frame-Options`, and they are invisible to `/metrics` — a small but real asymmetry with every other error response the server produces.
**Proposed fix:** Append the same two header tuples `SecurityHeadersMiddleware` adds (`X_CONTENT_TYPE_OPTIONS`, `X_FRAME_OPTIONS` from `server/middleware.py`) to the 401 in `_matches`' caller, rather than relaying through `_send_json_error` unmodified.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security threat-model coverage

**L4 — cycle() carries a dead `_smoke` parameter** (LOW)

**Where:** `apps/desktop/crates/supervisor/src/lifecycle.rs:92`
**Anchor:** `    _smoke: bool,`
**What:** `run_cycle` threads `smoke` into `cycle`, which never reads it (the underscore prefix is the only thing keeping clippy quiet).
**Why it matters:** A dead parameter invites a future reader to believe `cycle` branches on smoke mode when the branch actually lives entirely in `run_cycle`.
**Proposed fix:** Delete the parameter and its call-site argument.
**Regression-guard:** Optional; `-D warnings` already covers reintroduction if the underscore is dropped.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**L5 — MCP smoke never terminates its session** (LOW)

**Where:** `apps/desktop/crates/supervisor/src/lifecycle.rs:188`
**Anchor:** `    let tool_count = mcp_smoke(port, plan)?;`
**What:** The smoke performs `initialize` → `notifications/initialized` → `tools/list` but never issues the spec's `DELETE` with the `Mcp-Session-Id`, so the SDK's `StreamableHTTPSessionManager` retains that transport and its task for the child's lifetime.
**Why it matters:** Bounded at one leaked session per app launch and it perturbs nothing (`SessionCapMiddleware` only inspects `tools/call`), but it is a spec-recommended teardown the supervisor is uniquely positioned to do correctly.
**Proposed fix:** Add a final `http::request(port, "DELETE", MCP_PATH, &session_headers, None, PROBE_TIMEOUT)` in `mcp_smoke`, ignoring the status.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** MCP spec compliance

**L6 — AC1 asserts the announced host, not the actual bind** (LOW)

**Where:** `tests/test_desktop_child.py:219`
**Anchor:** `    assert bound.endpoint.host == "127.0.0`
**What:** `Endpoint(host="127.0.0.1", …)` in `_make_bound` and `sock.bind(("127.0.0.1", 0))` in `main` are two independent literals; AC1 asserts only the announced one.
**Why it matters:** A future edit to the bind literal would keep this assertion green while the child listened on a non-loopback address — the one thing `Config.reject_non_loopback` exists to prevent and which this path bypasses by construction. m6 explicitly owns the socket-level loopback regression, so this is a pointer, not a scope complaint.
**Proposed fix:** Add a source/AST assertion in the existing `test_ac5_desktop_child_never_touches_config_bind_port` style that `server/desktop_child.py` contains exactly one `bind(` call and its host argument is the literal `"127.0.0.1"`; leave the socket-level probe to m6.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first + Docker constraint

**L7 — read_frame does not resync after an oversized frame** (LOW)

**Where:** `server/desktop_child.py:70`
**Anchor:** `    chunk = stream.readline(FRAME_LIMIT + 1`
**What:** On an over-long line `readline(FRAME_LIMIT + 1)` returns the first 4097 bytes and raises, but `_watch_stdin`'s `except DesktopContractError: continue` resumes reading mid-line, so the tail of that line is parsed as a fresh frame.
**Why it matters:** Not exploitable — every actionable frame still requires a constant-time token match — but the docstring claims byte-for-byte parity with the Rust reader's `take()` semantics, and the Rust side's framing recovery differs.
**Proposed fix:** On the oversized branch, drain to the next `\n` before raising (`while not chunk.endswith(b"\n") and chunk: chunk = stream.readline(FRAME_LIMIT + 1)`), so the reader always resumes on a frame boundary.
**Regression-guard:** Optional; extend `test_read_frame_matches_rust_reader_semantics` with an oversized line followed by a valid frame and assert the valid frame is what comes back next.
**Source critic:** milestone-arxmcp-critic
**Source axis:** MCP spec compliance

**L8 — `.gitignore` ignores the whole `gen/` tree, not the canonical `gen/schemas`** (LOW)

**Where:** `.gitignore:75`
**Anchor:** `# Tauri build regenerates crate-local gen`
**What:** The comment correctly describes `gen/schemas`, but the pattern on the next line ignores every future child of `gen/`.
**Why it matters:** Tauri's own template ignores `gen/schemas` specifically because `gen/android` and `gen/apple` are generated *project* trees that are meant to be committed; if a mobile target is ever initialized under this crate the project would be silently untracked. Low, because this is a desktop-only supervisor with `bundle.active: false`.
**Proposed fix:** Narrow the pattern to `apps/desktop/crates/supervisor/gen/schemas/`, matching the comment and the upstream convention.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

**L9 — `wait_exit` conflates a `try_wait` error with a timeout before signalling** (LOW)

**Where:** `apps/desktop/crates/supervisor/src/lifecycle.rs:405`
**Anchor:** `Err(_) => return None,`
**What:** `wait_exit` returns `None` both when the grace budget expires and when `child.try_wait()` errors, and `shutdown_child` treats `None` as "still running" and immediately sends `SIGTERM` to `control.child.id()`.
**Why it matters:** On the error arm the child's reap state is unknown, so the PID could in principle already be reaped and recycled and the signal would land on an unrelated process; today nothing else reaps this child so it is theoretical, but the escalation ladder's PID safety currently rests on that being true rather than on the code.
**Proposed fix:** Return `Result<Option<i64>, ()>` (or an explicit three-state enum) and, on the error arm, skip `request_terminate` entirely and go straight to the handle-based `child.kill()` / `child.wait()`, which cannot target a recycled PID.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Open scan — subprocess / process hygiene

**L10 — Single-instance socket path is hand-copied from plugin internals and squattable** (LOW)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:107`
**Anchor:** `let mut stream = UnixStream::connect("/tm`
**What:** The loser path reimplements the client half of `tauri-plugin-single-instance`'s macOS protocol against a hardcoded `/tmp/com_arxmcp_desktop_si.sock`, duplicating a derivation that lives inside the pinned plugin, and no test exercises it.
**Why it matters:** `/tmp` is world-writable, so any local user can pre-bind that path and either absorb the loser's `cwd` + argv or block the winner's listener, degrading duplicate-activation silently; and because the derivation is a copy rather than a call, a plugin upgrade can break activation with the exact-pin bump as the only signal. The code comment already concedes the correctness half ("drift only degrades activation"), but nothing covers the squat case or pins the coupling.
**Proposed fix:** Derive the path from the plugin's own public helper if one is exposed at `=2.4.3`; otherwise record the derivation as a named constant next to the identifier in `tauri.conf.json` and add a unit test asserting the two agree, so a future identifier change cannot silently orphan the socket.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Open scan — subprocess / process hygiene

**L11 — Placeholder 1×1 icon can silently become the shipped app icon** (LOW)

**Where:** `apps/desktop/crates/supervisor/tauri.conf.json:10`
**Anchor:** `"active": false,`
**What:** `icons/icon.png` is a valid 70-byte 1×1 RGBA PNG committed solely to satisfy `tauri-codegen`, and nothing in the repo marks it as a placeholder or blocks bundling on it.
**Why it matters:** With `bundle.active: false` it is inert and never shipped, but when a later milestone flips that flag the macOS and Windows bundlers fail loudly for a missing `.icns` / `.ico` while the Linux `.deb` / AppImage path would silently ship a 1×1 transparent icon.
**Proposed fix:** Add a one-line assertion to the desktop tests that either `bundle.active` is `false` or every icon listed in `bundle.icon` is at least 256×256, so enabling bundling forces a real icon in the same change.
**Regression-guard:** Optional.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Axis 4 — Makefile / build script discipline

## What was done well

### From milestone-adversary-critic

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

### From milestone-arxmcp-critic

- The AC2 smoke is genuinely un-fakeable: it crosses a real socket to the announced endpoint, negotiates a real `Mcp-Session-Id`, sends the required `notifications/initialized`, and hashes with the *same* `compute_tool_schema_hash` the pin test uses — a mocked or stubbed response cannot satisfy it, and the handshake shape is spec-correct for Streamable HTTP (`Accept: application/json, text/event-stream`, protocol-version header, session id echoed on subsequent POSTs, `json_response=True` making the single-shot JSON assumption correct rather than lucky).
- The AC6 scoping argument is structural rather than declarative: constructing `ReadyzStartupTokenMiddleware` only in the desktop boot path makes the 14 existing `/readyz` callers unreachable by construction, and `test_middleware_is_desktop_scoped_not_shared` pins it by asserting the class name is absent from `server/main.py` and that neither `BaseHTTPMiddleware` nor `add_middleware` appears in the child's AST.
- Excluding docstrings from `_code_identifiers` is the right instinct — it stops prose from either masking a violation or manufacturing one, and it is what makes the AC5 `bind_port` scan real evidence instead of a grep.
- The fd discipline in `main`/`_serve` (dup the control pipe, point fd 1 at stderr, close the duped fd after the single `bound` write) makes a second stdout frame structurally impossible rather than merely unlikely, and the supervisor's `await_bound` drain thread records `unexpected-stdout` if one ever appears anyway.
- Hand-driving `startup()`/`main_loop()`/`shutdown()` is correct and faithful: it replicates uvicorn's own `_serve` sequence including the `config.load()` and `lifespan_class` construction, and it is the only way to emit `bound` at the exact boundary where both LISTEN state and lifespan warmth hold.
- The Rust diagnostic surface is disciplined by design — every `fail()`/`Err` value is a `&'static str`, `events.rs` records structural fields only, and the AC3 test enforces it adversarially by asserting that the only 64-hex string anywhere under the data root is the known identity digest.
- Rejecting the spike's "register the single-instance plugin on every launch" shape after measuring that the loser's listener can kill the fs2 winner mid-boot is exactly the right call, and the deviation is documented with its consequence rather than buried.
- `MIN_GRACE_MS` is honored by construction (`timeout_graceful_shutdown` left `None`, with the parse layer already rejecting a smaller `grace_ms`) rather than by a second hand-maintained constant that could drift from the wire contract.
- Marker discipline is otherwise correct: `requires_desktop_stack` was added to BOTH `pyproject.toml` and `tests/conftest.py::_OPT_IN_MARKERS`, the `-m "requires_desktop_stack or not requires_desktop_stack"` expression genuinely opts in under the substring-matching hook, AC3 `pytest.fail`s rather than skips on a missing binary, and the file carries no secondary skip guard — so the gate fails loudly, per the `requires_latexmlc` precedent.
- The no-fork axis is clean and verifiable: every `source =` line in the regenerated lockfile is `registry+https://github.com/rust-lang/crates.io-index`, all direct deps are `=`-pinned, and no file carries a lifted-code header. The in-repo reuse of `acquire_supervisor_lock` / `await_launch_barrier` from `tools/desktop_lifecycle_spike/` is this repo's own MIT code and a ~12-line fs2 idiom, not an external lift.

### From milestone-infra-safety-critic

- Exit codes propagate correctly on both new recipe lines: each is a single simple command (a `VAR=value cmd` prefix assignment, not a `;`-chained compound), so make aborts the target on a non-zero status, and a missing `cargo` yields shell exit 127 rather than a silent skip.
- `ARXMCP_FIXTURE_SIDECAR` and `DESKTOP_SUPERVISOR_BIN` are each scoped to exactly one recipe line, so the m5 real-child run genuinely cannot see the fixture-sidecar path — the AC1 assertion is not being satisfied by a leaked variable.
- Keeping the supervisor harness var un-prefixed is the right call and the Makefile comment explains why, so the next reader will not "fix" it into `ARXMCP_DESKTOP_SUPERVISOR_BIN` and trip the child's unknown-env FATAL scan.
- `cargo build --locked --bin supervisor` is placed before the pytest line that consumes the binary, preserving the m3 build-before-run ordering property (the gap is only that nothing asserts it for the new pair).
- Every new dependency is exact-`=`-pinned in `[workspace.dependencies]` and consumed via `.workspace = true`, `Cargo.lock` is committed, and it carries zero `git+` sources — all four cargo invocations in the gate pass `--locked`, so the build is reproducible from the lockfile.
- The `.gitignore` entry hides nothing security-relevant: `gen/schemas/*` are derived JSON Schemas plus a manifest of *available* permissions, while the *granted* set lives in `capabilities/**` (tracked, currently absent) and the plugin surface is visible in the exact-pinned `Cargo.toml`.
- `build.rs` is a bare `tauri_build::build()` with no network access, no codegen from remote sources, and no `curl | bash`; committing the tiny icon instead of generating it at build time keeps the build hermetic and deterministic, which is the right trade.
- Process shutdown is bounded at every step — 35s grace, then `SIGTERM`, then 5s, then a handle-based `kill()` + `wait()` — and the escalation only runs on PIDs that `try_wait` has confirmed unreaped, so there is no wrong-PID reap after recycling on the normal path.
- Every wait in the supervisor carries a deadline (`BOUND_TIMEOUT`, `HEALTH_DEADLINE`, `READY_DEADLINE`, the barrier's 10s, `poll_until`, `wait_exit`); there is no unbounded poll loop, and the child's `stdin`-EOF lease means even an abrupt supervisor death cannot leave an orphan.
- The `requires_desktop_stack` marker is registered in BOTH `pyproject.toml` and `tests/conftest.py::_OPT_IN_MARKERS`, which is exactly the pairing whose omission caused issue #206; the marked tests also correctly carry no secondary skip guard, so opting in with a missing binary calls `pytest.fail` rather than skipping.

Severity counts: C2 H3 M18 L11


## Cross-critic agreement

The following findings cluster within 5 lines of each other in the same file. Multiple critics flagged the same area - these are the strongest signals to fix first.

- **C1, M14** at `apps/desktop/README.md:5-5` (CRITICAL): apps/desktop/README.md denies the shell this diff just built; apps/desktop/README.md now contradicts the tree it documents
- **M7, L2, L3** at `server/desktop_child.py:128-130` (MEDIUM): Capability header name hardcoded, not derived from the contract constant; The desktop 401 short-circuits the SecurityHeaders invariant; /readyz 401 responses bypass the whole server middleware stack
- **M3, M2** at `apps/desktop/crates/supervisor/src/lifecycle.rs:388-393` (MEDIUM): No test drives shutdown_child's TERM or KILL escalation; The post-SIGKILL reap inside "bounded shutdown" is unbounded
- **M4, M12, L10** at `apps/desktop/crates/supervisor/src/main.rs:103-107` (MEDIUM): Loser activation is dead code on Linux, contradicting the seam claim; Hardcoded machine-global /tmp socket path in the supervisor; Single-instance socket path is hand-copied from plugin internals and squattable
- **M13, M18** at `apps/desktop/Cargo.toml:22-22` (MEDIUM): 453 new transitive crates enter the shipped surface with no supply-chain gate; No Rust toolchain pin or MSRV behind a `clippy -D warnings` gate
- **L8, M17** at `.gitignore:75-77` (MEDIUM): `.gitignore` ignores the whole `gen/` tree, not the canonical `gen/schemas`; Deny-by-default Tauri ACL is correct but unpinned by any test

## Recommended rectification order

C1, C2, H1, H2, H3, M1, M5, M2, M3, M4, M7, M8, M14, M9, M10, M11, M6, M15, M12, M13, M16, M17, M18, L1, L2, L3, L4, L5, L6, L7, L8, L9, L10, L11

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
