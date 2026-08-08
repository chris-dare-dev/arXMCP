# Critique — desktop-distribution-m5 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** 1a542ee..4d797a7
**Diff stats:** 19 files, 7168 LOC (7059 insertions / 109 deletions; 5054 insertions are the regenerated `apps/desktop/Cargo.lock`)
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

The lifecycle design is sound and the evidence is real rather than mocked — the child genuinely pre-binds loopback outside `Config`, the capability gate is genuinely pure-ASGI and genuinely unreachable from `create_app`, and the MCP smoke genuinely crosses the wire. One HIGH lands: the new boot path is the only way to run this server that never installs the E13_S08 `RedactionFilter` or the default JSON log format, so the entire desktop distribution runs outside a shipped security control. The remaining ten MEDIUMs are cheap, localized, and mostly about the durability of the gate rather than the correctness of the cycle.

## Executive summary

- [HIGH] `server/desktop_child.py` calls bare `logging.basicConfig` and never `server.observability.logging_setup.configure`, so the desktop distribution runs the full MCP server with the Threat-8 redaction filter absent and the 12-factor JSON formatter not installed.
- [MEDIUM] **Axis 1 answer — the live-hash equivalence is VALID but narrower than the pin.** `compute_tool_schema_hash([Tool.model_validate(t) …])` re-canonicalizes through the same `ListToolsResult`+`sort_keys`+`ensure_ascii` path, so key ordering, whitespace and transport framing are correctly normalized away rather than being false-mismatch sources. The real gap is the other direction: the test rebuilds a FRESH envelope from `payload["result"]["tools"]`, discarding the wire's `nextCursor`/`_meta`, which is exactly the envelope the F6 fix put inside the pin.
- [MEDIUM] The `/readyz` header name is hardcoded as `b"x-arxmcp-startup-token"` instead of derived from `desktop_contract.STARTUP_TOKEN_HEADER`, so a contract rename silently 401s every desktop launch forever.
- [MEDIUM] The stdin shutdown lease is armed only AFTER `uvicorn.Server.startup()` returns, so a user quitting during the 5–30 s warm-up gets a ~40 s hang ending in SIGKILL.
- [MEDIUM] `make desktop-conformance` now spawns two supervisors with `stdout`/`stderr` on undrained `subprocess.PIPE` and a 300 s `wait()` — the textbook pipe-buffer deadlock, on a Tauri/WKWebView process that is not quiet.
- [MEDIUM] The gate now force-enables `ARXMCP_ENABLE_RERANK=1`, adding a real BGE-reranker-v2-m3 load (fail-closed on absence) to a suite carrying neither `requires_model` nor a declared model prerequisite.
- [MEDIUM] `apps/desktop/README.md:5` still says the workspace "does not yet contain the Tauri shell … or the production server lifecycle adapter" — this commit added both.
- [MEDIUM] Axes 2 (math fidelity), 6 (tier sequencing) and 7 (no-fork) are clean: no LaTeX/MathML/chunker path is touched, dependencies e2/m2/m3 are all landed, and every one of the 453 new lockfile entries resolves to `registry+…crates.io-index` with no git/fork source and no lifted-code header.

## Findings

**H1 — Desktop boot path never installs RedactionFilter or the JSON formatter** (HIGH)

**Where:** `server/desktop_child.py:272`
**Anchor:** `    logging.basicConfig(level=os.environ`
**What:** The desktop child configures logging with bare `logging.basicConfig` and never calls `server.observability.logging_setup.configure(cfg.log_level, cfg.log_format)`, which is the sole installer of the E13_S08 `RedactionFilter` (grep: `server/cli.py:159` is its only caller in the tree).
**Why it matters:** Every desktop launch runs the full MCP server, writes its stderr to a persisted `<data_root>/logs/desktop-child.log`, and does so with the Threat-8 redaction invariant (`REDACTED_FIELDS` = query / body_canonical / body_raw_latex / mathml stripped at INFO+) structurally absent and the 12-factor JSON format silently downgraded to text — a shipped security control that `make up` has and the shipped desktop product does not.
**Proposed fix:** After `cfg = Config(data_dir=Path(frame.data_root))` succeeds and before `create_app(cfg)`, call `from server.observability.logging_setup import configure as _configure_logging; _configure_logging(cfg.log_level, cfg.log_format)` — mirroring `server/cli.py:159-163`. Keep the pre-Config `basicConfig` so the launch-rejection FATAL still lands on stderr.
**Regression-guard:** Add to `tests/test_desktop_child.py` a test asserting `RedactionFilter` appears in `logging.getLogger().filters` (or on a root handler) after the child's logging setup runs — e.g. call the extracted `_configure_child_logging(cfg)` helper directly and assert `any(isinstance(f, RedactionFilter) for f in logging.getLogger().filters)`, mirroring `tests/security/test_log_redaction.py::TestConfigure::test_configure_installs_redaction_filter_on_root`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security threat-model coverage

**M1 — AC2's live hash discards the ListToolsResult envelope the pin covers** (MEDIUM)

**Where:** `tests/test_desktop_child.py:307`
**Anchor:** `    live_hash = compute_tool_schema_hash`
**What:** The test extracts only `payload["result"]["tools"]` and feeds it to `compute_tool_schema_hash`, which internally constructs a FRESH `ListToolsResult(tools=tools)` — so the wire response's own `nextCursor` and any top-level `_meta` are dropped before hashing, which is precisely the envelope the E06_S06 F6 fix deliberately folded into the pin.
**Why it matters:** The AC's stated property ("the LIVE response bytes hash equal to `EXPECTED_TOOL_SCHEMA_SHA256`") is proven for the tool array but not for the envelope, so a future E07_S04 pagination cursor or a top-level `_meta` injection — a real BP1 prompt-cache-invalidating change the pin exists to catch — can appear on the desktop wire while this gate stays green.
**Proposed fix:** Hash the wire's own envelope rather than a reconstructed one: `ListToolsResult.model_validate(payload["result"])`, then reuse `_serialize_tools`/`compute_tool_schema_hash` on that instance (or assert `set(payload["result"]) == {"tools"}` alongside the existing tool-array hash). Either is ≤10 LOC and keeps the live-bytes provenance intact.
**Regression-guard:** In `test_ac2_mcp_smoke_live_schema_hash`, add `assert set(payload["result"]) == {"tools"}` so an envelope key appearing on the wire fails the gate instead of being silently discarded.
**Source critic:** milestone-arxmcp-critic
**Source axis:** cache byte-stability

**M2 — Capability header name hardcoded, not derived from the contract constant** (MEDIUM)

**Where:** `server/desktop_child.py:128`
**Anchor:** `        supplied = _get_header(headers, b"x-a`
**What:** `ReadyzStartupTokenMiddleware` matches the literal `b"x-arxmcp-startup-token"` while the Rust supervisor sends `arxmcp_desktop_contract::STARTUP_TOKEN_HEADER`; `server/desktop_contract.py:20` defines the same constant in Python but the child's import list omits it.
**Why it matters:** The header name is now stated in three places with only one of them authoritative, so a contract-level rename ships a supervisor that sends the new name and a child that checks the old one — every `/readyz` poll returns 401 until `READY_DEADLINE` and the desktop app quits with `lifecycle-failed`, with no test failing first.
**Proposed fix:** Import `STARTUP_TOKEN_HEADER` alongside the other contract names and use `STARTUP_TOKEN_HEADER.lower().encode("ascii")` in `__call__`; drop the literal.
**Regression-guard:** `assert STARTUP_TOKEN_HEADER.lower().encode("ascii") == b"x-arxmcp-startup-token"` plus an existing-style middleware test that builds the header name from the constant rather than a literal.
**Source critic:** milestone-arxmcp-critic
**Source axis:** MCP spec compliance

**M3 — Shutdown lease is not armed during the 5–30 s warm-up window** (MEDIUM)

**Where:** `server/desktop_child.py:261`
**Anchor:** `        threading.Thread(`
**What:** `_watch_stdin` is started only after `await server.startup(sockets=[sock])` returns, so for the entire eager BGE-M3/LanceDB warm-up neither an authenticated `shutdown` frame nor stdin EOF is observed.
**Why it matters:** A user quitting the splash window during warm-up drives `shutdown_child`, which waits `grace_ms` (35 s) with nobody listening, then SIGTERMs into a `startup()` that does not poll `should_exit`, then SIGKILLs 5 s later — a ~40 s hang on a plain quit, with `shutdown_child` returning `-1` instead of a clean exit, on the single most common non-smoke exit path.
**Proposed fix:** Move the `threading.Thread(target=_watch_stdin, …).start()` call to immediately before `await server.startup(sockets=[sock])`. `server` already exists at that point, and the existing `if server.should_exit or not server.started: return 1` guard immediately after `startup()` then converts an early quit into a fast, clean exit-1 rather than a forced kill.
**Regression-guard:** A `requires_desktop_stack` test that writes a valid `shutdown` frame immediately after the launch frame (before `bound` is read) and asserts the child exits within `MIN_GRACE_MS` without needing SIGTERM.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security threat-model coverage

**M4 — AC3 spawns supervisors with undrained PIPEs and a 300 s wait** (MEDIUM)

**Where:** `tests/test_desktop_child.py:344`
**Anchor:** `            stdout=subprocess.PIPE,`
**What:** Both supervisor processes are spawned with `stdout=subprocess.PIPE` and `stderr=subprocess.PIPE`, then `first.wait(timeout=300)` / `second.wait(timeout=300)` are called with nothing reading either pipe until after the waits complete.
**Why it matters:** This is the classic `Popen` deadlock — a Tauri/WKWebView process that emits more than the ~64 KB pipe buffer to stderr blocks forever on write, the supervisor never exits, and `make desktop-conformance` burns 600 s before failing with `TimeoutExpired` for a reason that has nothing to do with single-instance arbitration.
**Proposed fix:** Replace the `wait()` pair with `first.communicate(timeout=300)` / `second.communicate(timeout=300)` (which drain both pipes concurrently) and take `errors` from their return values, or redirect both children's stderr to files under the data root — which has the bonus of putting supervisor stderr inside the AC3 64-hex secret sweep.
**Regression-guard:** No new test needed; the change is the guard. Optionally assert the captured stderr is non-empty on failure so the diagnostic path is exercised.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M5 — AC4 destroys the module-scoped fixture that later tests would share** (MEDIUM)

**Where:** `tests/test_desktop_child.py:397`
**Anchor:** `def test_ac4_normal_shutdown_leaves_noth`
**What:** `test_ac4_normal_shutdown_leaves_nothing` shuts down the module-scoped `real_child` server and asserts the port is refused, with correctness resting entirely on it happening to be the last `requires_desktop_stack` test in file order (the docstring says "Runs LAST" but nothing enforces it).
**Why it matters:** m6 explicitly owns the fault matrix, the 30-cycle stress and the socket-level loopback regression, all of which will add `requires_desktop_stack` tests to this file — any of them appended after AC4 silently receives a dead server and fails for an unrelated reason, and a `-k`/`-p no:randomly` change or a file reorder trips the same wire today.
**Proposed fix:** Give AC4 its own function-scoped child (boot cost is already paid once per test-session for the module fixture, so add a second short-lived boot) or move the teardown assertions into the `real_child` fixture's `finally` block so no test owns the kill. Cheapest interim: add `@pytest.mark.order(...)`-free enforcement by having the fixture expose a `stopped` flag that AC1/AC2 assert is False.
**Regression-guard:** In the `real_child` fixture, set `namespace.stopped = True` when the child is stopped and add `assert not real_child.stopped` at the top of AC1 and AC2, so a reordering fails loudly and immediately.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing

**M6 — Conformance gate silently acquires a real reranker-model prerequisite** (MEDIUM)

**Where:** `tests/test_desktop_child.py:85`
**Anchor:** `    env["ARXMCP_ENABLE_RERANK"] = "1"`
**What:** The child env force-enables rerank purely so the AC1 warm map can assert all-three-true; `server/resources.py:726` then loads BGE-reranker-v2-m3 at startup and raises when it cannot, so `make desktop-conformance` now hard-requires a cached (or downloadable) third model.
**Why it matters:** The project's own convention double-gates real model loads behind `requires_model` plus a per-model env var (`ARXMCP_RUN_REAL_BGE_RERANKER=1`); this test carries neither, and the `requires_desktop_stack` marker text in `pyproject.toml` names only "BGE-M3/LanceDB warm-up" — so a fresh clone running the mandatory boundary gate fails on a HuggingFace fetch the gate never declared.
**Proposed fix:** Drop `ARXMCP_ENABLE_RERANK=1` and assert what the desktop default actually warms (`ready["warm"]["embedder"] is True and ready["warm"]["lancedb"] is True` and `isinstance(ready["warm"]["reranker"], bool)`); or keep it and add `requires_model` to AC1 plus the reranker download to the `requires_desktop_stack` marker description.
**Regression-guard:** Assert the reranker prerequisite explicitly — either `assert "ARXMCP_ENABLE_RERANK" not in _child_env()` (if dropped) or a marker-text test asserting `"reranker"` appears in the `requires_desktop_stack` registration string.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M7 — Hardcoded machine-global /tmp socket path in the supervisor** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/main.rs:107`
**Anchor:** `    let mut stream = UnixStream::connect(`
**What:** `notify_running_instance` connects to the literal `/tmp/com_arxmcp_desktop_si.sock`, re-deriving a third-party plugin's private socket path by hand, and writes the process cwd plus full argv to it.
**Why it matters:** Two hits at once — the local-first constraint forbids hardcoded `/tmp` absolute paths (all runtime state belongs under the received data root), and `/tmp` is world-writable on macOS, so any local user can pre-bind that path and receive the loser's cwd/argv or deny single-instance activation; the synthesis already records the machine-global collision between a conformance run and a real installed app.
**Proposed fix:** Derive the path from the identifier in `tauri.conf.json` via a single named constant beside `BARRIER_ENV`/`PLAN_ENV` with a comment pinning the plugin version whose derivation it mirrors, and skip the notify when `fs::metadata(...).uid()` is not the current uid. If activation is not load-bearing for m5, gate the whole call behind the plan (`plan.smoke == false`) so conformance runs never touch a machine-global path.
**Regression-guard:** A Rust unit test asserting the socket path is produced by the named constant/derivation function (not a scattered literal) and that the notify is skipped in smoke mode.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first + Docker constraint

**M8 — 453 new transitive crates enter the shipped surface with no supply-chain gate** (MEDIUM)

**Where:** `apps/desktop/Cargo.toml:22`
**Anchor:** `tauri = "=2.11.5"`
**What:** The lockfile goes from 27 to 480 packages (`git show 1a542ee:apps/desktop/Cargo.lock | grep -c '^name = '` → 27; at `4d797a7` → 480) and neither `make desktop-conformance` nor any other target runs `cargo audit` / `cargo deny`; no license or advisory census is recorded anywhere in the diff.
**Why it matters:** This is the first commit to put a 453-crate transitive graph into a distribution that ships to end users, in a repo whose E13 security audit is a completed epic — an advisory or a non-permissive transitive license would reach a release with nothing in the tree able to notice.
**Proposed fix:** Add a `cargo audit --file apps/desktop/Cargo.lock` (or `cargo deny check advisories licenses`) step to `desktop-conformance`, tolerant of the tool being absent only via an explicit opt-out variable, and record the license census in `apps/desktop/README.md` beside the existing "Supported boundary" section. Note the `=`-pinning of every direct dep is already correct and should stay.
**Regression-guard:** The Makefile step itself; plus a test asserting `apps/desktop/Cargo.lock` contains no `source = "git` entry, which cheaply pins the no-fork half.
**Source critic:** milestone-arxmcp-critic
**Source axis:** no-fork policy

**M9 — apps/desktop/README.md now contradicts the tree it documents** (MEDIUM)

**Where:** `apps/desktop/README.md:5`
**Anchor:** `not yet contain the Tauri shell, the fro`
**What:** The README states the workspace "does not yet contain the Tauri shell … or the production server lifecycle adapter; those belong to the next desktop milestones", and its "Development and conformance commands" block omits `--bin supervisor` and `DESKTOP_SUPERVISOR_BIN`; this commit added the Tauri shell, the lifecycle adapter, and both gate steps.
**Why it matters:** `apps/desktop/README.md` is the only operator-facing doc for the desktop boundary (the doc-placement rule forbids any other Markdown there), and the code-comment contract makes a stale statement a bug — an operator reproducing the gate by hand from this file builds only the fixture sidecar and never the supervisor.
**Proposed fix:** Update the opening paragraph to name the supervisor crate and the production lifecycle adapter as landed, list what is still absent (frozen Python runtime, release signing, launch-plan authoring), and add the two new `desktop-conformance` lines to the expanded command block.
**Regression-guard:** Optional for MEDIUM; a cheap one is a test asserting `"supervisor"` appears in `apps/desktop/README.md` whenever `apps/desktop/crates/supervisor/` exists.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M10 — 2 s MCP-smoke timeout with no retry can quit a healthy desktop app** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/lifecycle.rs:30`
**Anchor:** `const PROBE_TIMEOUT: Duration = Duration`
**What:** `mcp_smoke`'s three POSTs each use `PROBE_TIMEOUT` (2 s) for connect, read and write, with no `poll_until` retry — unlike the health and readiness probes, which retry for 60 s and 120 s respectively.
**Why it matters:** In the production (`smoke:false`) path a single transient 2 s overrun makes `cycle` return `Err`, which drives `run_cycle` → `handle.exit(1)` → the whole desktop app quits after the console was one step from rendering; the machine in question has just finished loading BGE-M3 and LanceDB, which is exactly when a 2 s budget is least safe, and the user sees no reason (m5 ships no failed render state).
**Proposed fix:** Give the smoke its own budget — either a dedicated `SMOKE_TIMEOUT: Duration = Duration::from_secs(15)` passed to `mcp_post`, or wrap `mcp_smoke` in the existing `poll_until` with a 60 s deadline. In the non-smoke path, prefer recording `mcp-smoke-failed` and still navigating the window over exiting the app.
**Regression-guard:** A Rust unit test that drives `mcp_post` against a deliberately slow loopback listener and asserts the smoke budget, not `PROBE_TIMEOUT`, governs it.
**Source critic:** milestone-arxmcp-critic
**Source axis:** MCP spec compliance

**L1 — /readyz 401 responses bypass the whole server middleware stack** (LOW)

**Where:** `server/desktop_child.py:130`
**Anchor:** `            await _send_json_error(`
**What:** The gate wraps the `create_app` result from outside, so it is strictly outermost; a 401 is emitted without ever reaching `SecurityHeadersMiddleware`, `OriginValidationMiddleware`, `SecFetchSiteMiddleware`, or the tracing/metrics middlewares.
**Why it matters:** `/readyz` 401s are the only responses the desktop process can emit without `X-Content-Type-Options: nosniff` / `X-Frame-Options`, and they are invisible to `/metrics` — a small but real asymmetry with every other error response the server produces.
**Proposed fix:** Append the same two header tuples `SecurityHeadersMiddleware` adds (`X_CONTENT_TYPE_OPTIONS`, `X_FRAME_OPTIONS` from `server/middleware.py`) to the 401 in `_matches`' caller, rather than relaying through `_send_json_error` unmodified.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security threat-model coverage

**L2 — cycle() carries a dead `_smoke` parameter** (LOW)

**Where:** `apps/desktop/crates/supervisor/src/lifecycle.rs:92`
**Anchor:** `    _smoke: bool,`
**What:** `run_cycle` threads `smoke` into `cycle`, which never reads it (the underscore prefix is the only thing keeping clippy quiet).
**Why it matters:** A dead parameter invites a future reader to believe `cycle` branches on smoke mode when the branch actually lives entirely in `run_cycle`.
**Proposed fix:** Delete the parameter and its call-site argument.
**Regression-guard:** Optional; `-D warnings` already covers reintroduction if the underscore is dropped.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**L3 — MCP smoke never terminates its session** (LOW)

**Where:** `apps/desktop/crates/supervisor/src/lifecycle.rs:188`
**Anchor:** `    let tool_count = mcp_smoke(port, plan)?;`
**What:** The smoke performs `initialize` → `notifications/initialized` → `tools/list` but never issues the spec's `DELETE` with the `Mcp-Session-Id`, so the SDK's `StreamableHTTPSessionManager` retains that transport and its task for the child's lifetime.
**Why it matters:** Bounded at one leaked session per app launch and it perturbs nothing (`SessionCapMiddleware` only inspects `tools/call`), but it is a spec-recommended teardown the supervisor is uniquely positioned to do correctly.
**Proposed fix:** Add a final `http::request(port, "DELETE", MCP_PATH, &session_headers, None, PROBE_TIMEOUT)` in `mcp_smoke`, ignoring the status.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** MCP spec compliance

**L4 — AC1 asserts the announced host, not the actual bind** (LOW)

**Where:** `tests/test_desktop_child.py:219`
**Anchor:** `    assert bound.endpoint.host == "127.0.0`
**What:** `Endpoint(host="127.0.0.1", …)` in `_make_bound` and `sock.bind(("127.0.0.1", 0))` in `main` are two independent literals; AC1 asserts only the announced one.
**Why it matters:** A future edit to the bind literal would keep this assertion green while the child listened on a non-loopback address — the one thing `Config.reject_non_loopback` exists to prevent and which this path bypasses by construction. m6 explicitly owns the socket-level loopback regression, so this is a pointer, not a scope complaint.
**Proposed fix:** Add a source/AST assertion in the existing `test_ac5_desktop_child_never_touches_config_bind_port` style that `server/desktop_child.py` contains exactly one `bind(` call and its host argument is the literal `"127.0.0.1"`; leave the socket-level probe to m6.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first + Docker constraint

**L5 — read_frame does not resync after an oversized frame** (LOW)

**Where:** `server/desktop_child.py:70`
**Anchor:** `    chunk = stream.readline(FRAME_LIMIT + 1`
**What:** On an over-long line `readline(FRAME_LIMIT + 1)` returns the first 4097 bytes and raises, but `_watch_stdin`'s `except DesktopContractError: continue` resumes reading mid-line, so the tail of that line is parsed as a fresh frame.
**Why it matters:** Not exploitable — every actionable frame still requires a constant-time token match — but the docstring claims byte-for-byte parity with the Rust reader's `take()` semantics, and the Rust side's framing recovery differs.
**Proposed fix:** On the oversized branch, drain to the next `\n` before raising (`while not chunk.endswith(b"\n") and chunk: chunk = stream.readline(FRAME_LIMIT + 1)`), so the reader always resumes on a frame boundary.
**Regression-guard:** Optional; extend `test_read_frame_matches_rust_reader_semantics` with an oversized line followed by a valid frame and assert the valid frame is what comes back next.
**Source critic:** milestone-arxmcp-critic
**Source axis:** MCP spec compliance

## What was done well

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

Severity counts: C0 H1 M10 L5

## Recommended rectification order

H1, M2, M3, M9, M4, M5, M6, M1, M10, M7, M8, L1, L2, L3, L4, L5

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed: <finding ids>
- Deferred: <finding ids>
- Invalidated: <finding ids with reasons>
- Regression tests added: <file paths>
