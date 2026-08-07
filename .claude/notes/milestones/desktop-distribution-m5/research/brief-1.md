# desktop-distribution-m5 — implementation-ready research brief (general/solo)

Scope: m5 only (real single-cycle lifecycle, macOS, normal-shutdown path).
m6 (fault matrix, 30-cycle stress, socket-level loopback regression) is
explicitly out of scope and not designed here. m4's synthesis/brief-1/2/3
are read and treated as settled per the dispatch prompt; this brief does not
re-litigate the pre-bound-socket, clean-stdout, M2-wheel-child, real-MCP-smoke,
pure-ASGI-token-middleware, or host-existing-`/ui/` decisions.

## 1. TL;DR

Ship `server/desktop_child.py` as a new `python -m server.desktop_child`
entry point (no new console script, no `--desktop-child` flag on
`arxmcp-server` — `server/cli.py:23-29`'s own docstring bans a second config
surface) that hand-drives `uvicorn.Server.startup()`/`main_loop()`/`shutdown()`
instead of calling the all-in-one `.run()`, so the `bound` frame can be
emitted at the exact point uvicorn sets `self.started = True`
(`uvicorn/server.py:195`) — which is provably *after* the FastAPI lifespan
(including the eager BGE-M3/LanceDB warm-up, `server/main.py:461-494`) has
already completed, because `await self.lifespan.startup()` runs strictly
before the socket-wrapping loop (`uvicorn/server.py:104-146`). Pair this with
a new `apps/desktop/crates/supervisor` crate (fs2 lock → spawn →
`WebviewWindowBuilder::new(app, "main", WebviewUrl::External(bound.ui_url))`
after `bound` arrives → one MCP smoke → normal shutdown) using the exact
Tauri 2.11.5/tauri-plugin-shell 2.3.5/tauri-plugin-single-instance
2.4.3/tauri-build 2.6.3/fs2 0.4.3 pins already cached offline from Spike-3.
Main risk: honest LOC lands at ~1,000–1,600 across ~14–18 files — over the
800-LOC gate even after the m4→m5/m6 split, so flag this to the orchestrator
before Phase 2 rather than let the gate surprise mid-diff. Backup plan: if
Phase 2 still rejects the size, the trim that stays inside AC text is
dropping the Rust supervisor to two render states (starting, ready — m6 owns
degraded/failed) and sharing one real-server pytest fixture across AC1/AC2/AC4.

## 2. Prior art in this repo (file:line)

- `server/desktop_contract.py:1-709` — full Python wire contract (M3), reused
  as-is: `parse_frame`/`encode_frame`, `StartupToken`/`tokens_equal`
  (`hmac.compare_digest`), `MIN_GRACE_MS=35_000`,
  `STARTUP_TOKEN_HEADER="X-ArXMCP-Startup-Token"`,
  `ChildControlState`. `_parse_shutdown_semantics` (lines 420-442) already
  enforces `grace_ms >= MIN_GRACE_MS` at parse time — m5 code does not need
  to re-check this number.
- `apps/desktop/crates/desktop-contract/src/lib.rs:315-330` — Rust
  `read_frame<R: BufRead>`: bounded `take(FRAME_LIMIT+1).read_until(b'\n')`,
  `count==0`→EOF/`None`, `count>FRAME_LIMIT`→error. **No Python equivalent
  exists** (`server/desktop_contract.py` has no line reader) — this is the
  exact gap item 1 of the task asks to fill; the correct thin reader is
  `stream.readline(FRAME_LIMIT + 1)` on `sys.stdin.buffer` (Python's
  `readline(size)` caps total bytes exactly like Rust's `.take()`, stopping
  at `\n` or the cap, whichever first) — see §3.1.
- `apps/desktop/crates/fixture-sidecar/src/main.rs:76-96` (bind),
  `:166-236` (control-reader thread + `serve_until_stopped`'s
  `LeaseEvent::{Shutdown,Eof,Invalid}` handling) — the Rust child template;
  `Invalid` is a no-op (keep waiting), only `Shutdown`/`Eof` terminate. This
  is the exact state machine to port to a Python `threading.Thread`.
- `server/cli.py:1-219` — `main()` calls `uvicorn.run("server.main:app",
  host=cfg.bind_host, port=cfg.bind_port, lifespan="on", log_config=None)`
  (lines 209-215); its own docstring (lines 23-29) states *"Config comes
  from the environment, not from flags... Adding flags here would create a
  second source of truth"* — this is a **direct, specific argument against
  brief-1(m4)'s "prefer the flag" lean**, which did not weigh this docstring.
  See §3.1 for the entry-point decision.
- `server/config.py:825-838` (`validate_port_range`, unchanged — settled),
  `:62` (`LOOPBACK_HOSTS`), `:427` (`Config.data_dir: Path` — this is the
  exact field name to populate from `launch.data_root`, not `bind_port`).
- `server/main.py:412-452` (`_scan_unknown_arxmcp_env_vars` — FATAL on any
  undeclared `ARXMCP_*`), `:308-351` (`_KNOWN_INGEST_ENV_VARS` carve-out
  dict — the pattern to extend *if* an env var were ever needed, which it
  is not here), `:685-864` (`create_app(config)` — returns a plain
  `FastAPI` instance; middleware is registered via `app.add_middleware(...)`
  in LIFO order, lines 724-839; health router mounted at line 842).
- `server/health.py:264-363` (`readyz` handler) — reads no header today;
  returns the `warm: {embedder, lancedb, reranker}` map. Confirmed
  unmodified by this milestone (§3.3).
- `server/middleware.py:396-506` (`OriginValidationMiddleware`, the
  canonical pure-ASGI skeleton: `def __init__(self, app, ...)`,
  `async def __call__(self, scope, receive, send)`, path/type guard first,
  pass-through via `await self.app(scope, receive, send)`) — the template
  for the new `ReadyzStartupTokenMiddleware`. `LOOPBACK_ORIGIN_HOSTS` at
  line 104 (`{"127.0.0.1", "localhost", "::1"}`, any port) confirms the
  Tauri webview's `Origin` needs zero config change (§3.4).
- `server/main.py:156-174` region + repo-wide convention — `BaseHTTPMiddleware`
  is banned (E06_S01 F1); every existing middleware in `server/middleware.py`
  is pure-ASGI. The new middleware must match.
- `tests/test_desktop_contract.py:70` (`_readline_with_timeout(..., timeout:
  float = 5.0)`), `:133-176` (`_request`/`_spawn_sidecar`/`_stop_process`,
  all using `timeout=2` on socket-level ops), `:331-422`
  (`test_fixture_sidecar_is_model_free_token_safe_and_bounded` — the exact
  template to port for the real-server test: spawn, read `bound`, GET
  `/healthz`+`/readyz` unauthenticated/wrong-token/correct-token, send bad
  then good `shutdown`, assert `process.wait(timeout=3)==0`, assert the
  capability never appears in stdout remainder/argv/env/URLs, then
  `root.rglob("*")` sweep every on-disk artifact for the secret bytes).
- `Makefile:145-150` (`desktop-conformance`: `cargo fmt --check` →
  `cargo test --locked --workspace` → `cargo clippy -D warnings` →
  `cargo build --locked --bin fixture-sidecar` → pytest against the built
  binary). `apps/desktop/README.md:28-58` gives the exact commands; note the
  Makefile target does not build a supervisor bin yet — m5 must extend it.
- `apps/desktop/Cargo.toml:1-27` — workspace has **no Tauri dependency
  anywhere yet**; `[workspace.dependencies]` currently only
  `getrandom`/`serde`/`serde_json`/`sha2`, all pinned with `=`. m5 is the
  first milestone to add Tauri to this repo's tracked Cargo graph.
- `tools/desktop_lifecycle_spike/Cargo.toml:8-21` — the cached, GO'd version
  set: `tauri = "=2.11.5"`, `tauri-plugin-shell = "=2.3.5"`,
  `tauri-plugin-single-instance = "=2.4.3"`, `tauri-build = "=2.6.3"`,
  `fs2 = "0.4"` (resolves to cached `fs2-0.4.3`). Confirmed present offline
  at `~/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/{tauri-2.11.5,
  tauri-plugin-single-instance-2.4.3, fs2-0.4.3}` on this machine.
- `tools/desktop_lifecycle_spike/src/main.rs:700-765` (`fn main()`) — the
  single-instance-then-spawn pattern: `acquire_supervisor_lock()` (fs2,
  before `tauri::Builder`), then `tauri::Builder::default()
  .plugin(tauri_plugin_single_instance::init(...))
  .plugin(tauri_plugin_shell::init())
  .setup(move |app| { if !owns_supervisor_lock { app.handle().exit(0); ...}
  ... }).run(...)`. This is design precedent only (pre-M3 wire format per
  m4 synthesis §8) — reuse the *shape*, not the code.
- `tools/desktop_lifecycle_spike/build.rs` — minimal-viable `build.rs` is
  just `tauri_build::build()`; the spike's elaborate SHA-256
  source-provenance/icon-embedding logic is spike-only bookkeeping, not a
  required pattern for the production crate.
- `tools/desktop_lifecycle_spike/tauri.conf.json` — `"app": {"windows": []}`
  (no static window — created dynamically in `.setup()`),
  `"bundle": {"active": false, "icon": []}` (no bundler, no icon needed on
  macOS). **No capabilities/permissions JSON file exists anywhere in the
  spike** — confirmed by `find -iname "*capabilit*"` returning nothing.
- `server/application_paths.py:24-32` (`_LAYOUT`, includes
  `("logs", "logs")`), `:81-89` (`_platform_data_root`), `:93-183`
  (`ApplicationPaths.resolve`) — sole owner of the on-disk layout (settled,
  m4 synthesis §6 Invariant #6). The Rust supervisor must receive the
  resolved root as a string, never reimplement platform defaults via a Rust
  `dirs`/`directories` crate.

## 3. Recommended approach

### 3.1 Python desktop-child entry point

**Decision: `python -m server.desktop_child`, invoked by the Rust
supervisor as `sys.executable -m server.desktop_child` (no new console
script, no CLI flag).** This overrides brief-1(m4)'s lean toward a
`--desktop-child` flag, given the explicit "second source of truth"
argument in `server/cli.py:23-29` that brief-1 didn't weigh against this
specific case. A separate module also lets `Launch.executable.component`
carry a distinct identity string (e.g. `"arxmcp-server-desktop-child"`) that
never collides with `arxmcp-server`'s own identity, matching the
Rust fixture-sidecar's `COMPONENT = "arxmcp-fixture-sidecar"` precedent
(`fixture-sidecar/src/main.rs:14`) more cleanly than an argv flag would.

Call sequence in `server/desktop_child.py::main()`:

1. `frame = read_frame(sys.stdin.buffer)`. New thin reader, mirroring
   `desktop-contract/src/lib.rs:315-330` exactly:
   ```python
   def read_frame(stream: BinaryIO) -> bytes | None:
       chunk = stream.readline(FRAME_LIMIT + 1)  # bounded like Rust's take()
       if not chunk:
           return None  # EOF before any frame
       if len(chunk) > FRAME_LIMIT:
           raise DesktopContractError("control frame exceeds 4096 bytes")
       return chunk
   ```
   `None` → exit(2), no `Launch` received (mirrors
   `SidecarError::MissingLaunch`).
2. `launch = parse_frame(frame)`; must be a `Launch` (else exit 2).
3. Validate `launch.executable` identity. **Open design gap, flag
   explicitly, do not silently borrow the Rust semantics**: the Rust
   sidecar hashes its own single compiled binary
   (`fixture-sidecar/src/main.rs:119-134`) — Python has no equivalent
   single-file "executable". Recommend: `sha256 =
   hashlib.sha256(Path(__file__).read_bytes()).hexdigest()` (hash
   `desktop_child.py`'s own source, the closest analogue to "hash your own
   executable before binding"), `component = "arxmcp-server-desktop-child"`,
   `version = importlib.metadata.version("arxmcp")` (reuse the `_version()`
   pattern at `server/cli.py:77-91`). This is weaker identity proof than a
   compiled binary's hash (doesn't cover imported dependencies) — note it
   as a known limitation, not a silent gap.
4. `sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); sock.bind(("127.0.0.1", 0))`.
   **Do not call `sock.listen()`** — verified against
   `asyncio/base_events.py::BaseEventLoop.create_server`'s `sock=` branch:
   it does `sock.setblocking(False)` then wraps in `Server(...)`, and
   `Server._start_serving()` is what calls `sock.listen(self._backlog)` —
   this happens *inside* `uvicorn.Server.startup()` (see next point), not
   before. Read the assigned port via `sock.getsockname()[1]` (available
   immediately post-`bind()`, no `listen()` needed).
5. Build `cfg = Config(data_dir=Path(launch.data_root), ...)` (do **not**
   set `bind_port`; it stays at its validated default and is unused —
   settled). `app = create_app(cfg)`.
6. **Wrap, don't register**: `app = ReadyzStartupTokenMiddleware(app,
   expected_token=launch.startup_token)` — a plain Python object wrapping
   the ASGI callable, done *only* in this module (§3.3).
7. Drive uvicorn manually instead of calling `.run()`/`.serve()` (which
   give no hook between socket-bind and main-loop):
   ```python
   config = uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="on", log_config=None)
   server = uvicorn.Server(config)
   with server.capture_signals():
       await server.startup(sockets=[sock])
       if server.should_exit or not server.started:
           return 1  # lifespan startup failed — NEVER emit `bound`
       emit_bound_frame(launch, port, sha256)   # stdout, exactly once, then stop
       stop_event = start_shutdown_watcher(server, launch)  # background thread
       await server.main_loop()
       await server.shutdown(sockets=[sock])
   return 0
   ```
   **Exact citation for "where the socket is guaranteed listening"**
   (this is the load-bearing new finding of this research pass):
   `uvicorn/server.py:104` — `startup()` first does `await
   self.lifespan.startup()`. That call runs FastAPI's `lifespan()`
   generator up to its `yield` — i.e. `server/main.py:490
   (await Resources.startup(config))`, the full eager BGE-M3/LanceDB
   warm-up — to completion, **strictly before** any socket branch runs
   (`server/main.py:61-66` documents this as intentional: "lazy load would
   make the first tools/call hang... eager-loads BGE-M3 BEFORE yield").
   Only after that does `uvicorn/server.py:125-146` (the `sockets is not
   None` branch) run `await loop.create_server(create_protocol, sock=sock,
   ...)` for each pre-bound socket — which is what triggers
   `Server._start_serving()`'s `sock.listen(self._backlog)`
   (`asyncio/base_events.py`, verified by direct read of the installed
   3.12 stdlib). `self.started = True` (`uvicorn/server.py:195`) is set
   only after that loop finishes. **Net effect**: the instant
   `server.startup()` returns with `server.started` true, the socket is
   both (a) in `LISTEN` state and (b) behind a FastAPI app whose lifespan
   startup — including the eager warm-up — has already fully run. This is
   a stronger guarantee than "not emitted early": it means `/readyz` is
   structurally very unlikely to ever serve a 503 to the desktop window,
   because no HTTP request can reach the process before that warm-up
   finished. Do not over-claim `resources.warm` is *unconditionally* true
   at that instant (per-resource warm state in `server/health.py:264-363`
   wasn't fully audited here) — tests should still poll `/readyz` with a
   bounded timeout, not assert instant-200.
8. Emit `bound` (`encode_frame`, one write + flush to `sys.stdout.buffer`,
   then never write stdout again — settled, matches
   `apps/desktop/README.md:69` "child stdout is control-only").
9. `return await asyncio.run(...)`-wrapped driver; `sys.exit(code)`.

### 3.2 Shutdown + lease

Background `threading.Thread` (blocking stdin reads must not block the
asyncio loop), started right after `bound` is emitted:

```python
def _watch_stdin(stream, server, launch):
    while True:
        raw = read_frame(stream)
        if raw is None:                       # stdin EOF — parent-lifetime lease
            server.should_exit = True
            return
        try:
            frame = parse_frame(raw)
        except DesktopContractError:
            continue                          # garbage — ignore, keep waiting
        if (isinstance(frame, Shutdown)
                and frame.contract == launch.contract
                and tokens_equal(frame.startup_token, launch.startup_token)):
            server.should_exit = True
            return
        # wrong contract / wrong token / wrong kind — Invalid, keep waiting
```
This exactly mirrors `fixture-sidecar/src/main.rs:166-236`'s
`LeaseEvent::{Shutdown,Eof,Invalid}` handling. Setting `server.should_exit`
from a non-asyncio OS thread is the same pattern uvicorn's own
`handle_exit()` signal handler uses (`uvicorn/server.py:341-346`) — safe
under CPython's GIL for a plain bool assignment; `main_loop()`'s
`on_tick()` polls it every 0.1s (`uvicorn/server.py:232-239`).

**`MIN_GRACE_MS` (35,000ms) is honored by construction, not by a timer in
this module.** `desktop_contract._parse_shutdown_semantics`
(`server/desktop_contract.py:420-442`) already rejects any `Launch` whose
`grace_ms < MIN_GRACE_MS` at parse time — the Python entry point cannot
receive a non-compliant grace value. Leave
`uvicorn.Config(timeout_graceful_shutdown=...)` at its **default (`None`)**
— `uvicorn/config.py:218` defaults to `None`, and `Server.shutdown()`'s
`asyncio.wait_for(self._wait_tasks_to_complete(), timeout=None)` then waits
*unboundedly* for in-flight connections to drain, which is a superset of
"at least grace_ms", not a violation. The **outer** bound
(`force_after_ms`/TERM→KILL) is enforced by the Rust supervisor at the OS
process level (§3.5) — do not double-bound it inside uvicorn.

**Three shutdown triggers, three behaviors:**
- Stdin EOF → `should_exit=True` (parent-lifetime lease fires).
- Valid authenticated `shutdown` frame → `should_exit=True`.
- Invalid frame (bad token, wrong contract, garbage bytes, wrong `kind`) →
  ignored, thread keeps reading (never exits on invalid input — this is
  the AC4/AC1 "invalid shutdown must not stop the server" behavior the
  fixture sidecar's own test already proves at
  `tests/test_desktop_contract.py:371-380`).

### 3.3 Pure-ASGI `/readyz` capability middleware

**Mount point: nowhere near `server/main.py::create_app`.** Wrap the
returned app object *inside* `server/desktop_child.py` only:
```python
app = create_app(cfg)
app = ReadyzStartupTokenMiddleware(app, expected_token=launch.startup_token)
```
Any plain object implementing `async def __call__(self, scope, receive,
send)` satisfies the ASGI callable protocol FastAPI/uvicorn expect — no
`app.add_middleware()` call is needed, which sidesteps any ordering
subtlety in Starlette's `user_middleware` list entirely. `make up`,
Docker, `create_app()` callers in tests, and every existing `/readyz`
caller never construct `server.desktop_child`, so they are structurally
unreachable from this class.

```python
class ReadyzStartupTokenMiddleware:
    """Pure-ASGI. Desktop-child-only: constructed by server/desktop_child.py,
    never by server.main.create_app. Gates GET /readyz on
    X-ArXMCP-Startup-Token; every other path passes through untouched."""

    def __init__(self, app: ASGIApp, expected_token: StartupToken) -> None:
        self.app = app
        self._expected_token = expected_token

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http" or scope["path"] != READINESS_PATH:
            await self.app(scope, receive, send)
            return
        headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
        supplied = _get_header(headers, b"x-arxmcp-startup-token")
        if supplied is None or not _candidate_matches(supplied, self._expected_token):
            await _send_json_error(send, status=401, body={"error": "unauthorized"})
            return
        await self.app(scope, receive, send)


def _candidate_matches(raw: bytes, expected: StartupToken) -> bool:
    try:
        candidate = StartupToken.parse(raw.decode("ascii"))
    except (UnicodeDecodeError, DesktopContractError):
        return False
    return tokens_equal(candidate, expected)   # hmac.compare_digest — reuse, don't reimplement
```
Skeleton follows `OriginValidationMiddleware` (`server/middleware.py:396-506`)
exactly: `__init__(self, app, ...)`, `async def __call__(self, scope,
receive, send)`, type/path guard first, `await self.app(...)` pass-through.
`_get_header`/`_send_json_error` are existing private helpers already used
by `OriginValidationMiddleware` — reuse them (import from
`server.middleware`, or duplicate the two ~5-line helpers locally if an
import would create an awkward `desktop_child → middleware` private-symbol
dependency; either is acceptable, note the choice in the PR).

**How the token reaches it without becoming a Config field or env var**:
it never leaves the process's own memory — `launch.startup_token` (parsed
from the private stdin `Launch` frame) is passed as a plain Python object
via the middleware constructor's `expected_token` kwarg. It touches no
`os.environ`, no `Config` field, so `server/main.py:412-452`'s
unknown-`ARXMCP_*` scan is never in the picture — settled by construction,
not by a carve-out entry.

### 3.3b Every existing test that touches `/readyz`, and why each still passes

`grep -rln readyz tests/` → 14 files: `test_bootstrap_mode.py`,
`test_compose_server.py`, `test_corpus_count_reconciliation.py`,
`test_corpus_freshness.py`, `test_cutover.py`, `test_desktop_contract.py`,
`test_failure_modes.py`, `test_k8s_manifests.py`, `test_runbook_index.py`,
`test_security.py`, `test_server_startup.py`,
`test_server_startup_integration.py`, `test_shim.py`,
`test_status_endpoint.py`, `test_ui_html_pages.py`.

- `test_k8s_manifests.py:154-161` and `test_runbook_index.py:163` assert
  against static YAML/doc *content* ("`readinessProbe.httpGet.path ==
  '/readyz'`"), never construct an app — unaffected structurally.
- `test_desktop_contract.py` exercises the **fixture sidecar's** own
  `/readyz` (Rust HTTP server, not FastAPI) — unrelated code path.
- The remaining 11 (`test_security.py:308-309,854`,
  `test_bootstrap_mode.py`, etc.) all call `client.get("/readyz")` against
  a `TestClient`/`httpx` client built over `server.main.create_app(...)`,
  exactly the shared app-construction path at `server/main.py:685`. Since
  `ReadyzStartupTokenMiddleware` is instantiated **only** inside the new
  `server/desktop_child.py` module and never imported by `create_app`,
  none of these 11 can reach it — they hit the unmodified
  `server.health.readyz` handler with the same no-header, no-auth request
  shape as today. Add one grep-based regression guard in the new desktop
  test file: `assert "ReadyzStartupTokenMiddleware" not in
  Path("server/main.py").read_text()` — cheap, catches an accidental
  future merge of the middleware into the shared factory.

### 3.4 Rust supervisor crate

`apps/desktop/Cargo.toml` — add `"crates/supervisor"` to `members`, and
add 5 new pinned entries to the existing `[workspace.dependencies]` table
(matching the repo's established `=`-pin style used for
getrandom/serde/serde_json/sha2):
```toml
fs2 = "=0.4.3"
tauri = "=2.11.5"
tauri-build = "=2.6.3"
tauri-plugin-shell = "=2.3.5"
tauri-plugin-single-instance = "=2.4.3"
```
New `apps/desktop/crates/supervisor/Cargo.toml`:
```toml
[package]
name = "arxmcp-desktop-supervisor"
version.workspace = true
edition.workspace = true
license.workspace = true
publish.workspace = true
build = "build.rs"

[dependencies]
arxmcp-desktop-contract = { path = "../desktop-contract" }
fs2.workspace = true
serde_json.workspace = true
tauri.workspace = true
tauri-plugin-shell.workspace = true
tauri-plugin-single-instance.workspace = true

[build-dependencies]
tauri-build.workspace = true

[[bin]]
name = "supervisor"
path = "src/main.rs"
```
`tauri.conf.json` minimum (mirrors
`tools/desktop_lifecycle_spike/tauri.conf.json` exactly, only the
identifier/name changed):
```json
{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "arXMCP",
  "version": "0.1.0",
  "identifier": "com.arxmcp.desktop",
  "app": { "windows": [] },
  "bundle": { "active": false, "icon": [] }
}
```
`"app.windows": []` — no static window; created imperatively once `bound`
arrives (below). `"bundle.active": false` — no `.app` packaging in m5
(that's e4's job, settled by m4 synthesis); confirms plain `cargo build`
needs no icons (`tauri-build`'s icon step is gated
`if target_triple.contains("windows")`, verified in m4 brief-2 against
`tauri-build-2.6.3` source — macOS needs none).

`build.rs`: the spike's elaborate SHA-256/icon-embedding logic is
spike-only evidence bookkeeping — the production crate needs only:
```rust
fn main() { tauri_build::build() }
```

**Capabilities/permissions files: none required for m5.** `find -iname
"*capabilit*"` across the spike returns nothing, and capability/ACL JSON
only gates the webview's JS-side `invoke()` calls — `/ui/` is plain htmx
with no `window.__TAURI__` usage (confirmed by m4 brief-2 §6.4), and the
Rust-side `Command::spawn()`/window creation happen entirely in native
Rust code inside `.setup()`, which needs no capability grant at all.

**`cargo build --locked` works offline, no `cargo tauri` CLI**: confirmed
twice — m4 brief-2's direct read of `tauri-build-2.6.3::try_build()`
(reads only local `tauri.conf.json`/`Cargo.toml`/capability JSON, no
network call site) and the spike's own README precedent
(`apps/desktop/README.md:36-43` invokes `cargo build`/`cargo test`/`cargo
clippy` directly, never `cargo tauri`).

**Window creation for a URL not known until `bound` arrives** — verified
against the cached crate source
(`~/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/tauri-2.11.5/src/webview/webview_window.rs:101`,
`pub fn new<L: Into<String>>(manager: &'a M, label: L, url: WebviewUrl) -> Self`):
```rust
// inside .setup(move |app| { ... })
let handle = app.handle().clone();
tauri::async_runtime::spawn(async move {
    let bound = spawn_child_and_await_bound(&handle, launch_params).await?;
    let url: tauri::Url = bound.ui_url.parse().expect("bound.ui_url is validated http://127.0.0.1:<port>/ui/");
    tauri::WebviewWindowBuilder::new(&handle, "main", tauri::WebviewUrl::External(url))
        .title("arXMCP")
        .build()
        .expect("create desktop window after bound frame");
});
```
**Does `OriginValidationMiddleware`/CSP admit this window as-is? Yes, no
change needed.** `server/middleware.py:104`
(`LOOPBACK_ORIGIN_HOSTS = {"127.0.0.1", "localhost", "::1"}`, any port)
and the CSP block scoped to `/ui/*` (`server/main.py` region around line
777-783, prefix-matched) apply identically to any HTTP client hitting
`/ui/` — a Tauri webview making an ordinary GET is indistinguishable at
the HTTP layer from curl or a normal browser tab already exercising this
same code path today.

### 3.5 Single-instance arbitration

Native advisory lock via `fs2::FileExt::try_lock_exclusive()` on a file
under the resolved data root (e.g. `<data_root>/supervisor.lock`),
acquired in `fn main()` **before** `tauri::Builder::default()` is even
constructed — exact precedent at
`tools/desktop_lifecycle_spike/src/main.rs:725-729`
(`acquire_supervisor_lock`) and `:740-744` (`.setup(move |app| { if
!owns_supervisor_lock { app.handle().exit(0); return Ok(()); } ... })`).
On lock failure: exit(0) without ever spawning a child. `fs2` is the
**primary** defense (checked first, before any Tauri/plugin machinery).
`tauri-plugin-single-instance` (registered on every launch, winner and
loser alike, at `:735-738`) is **activation UX only** — its callback fires
in an *already-running* winning process on a subsequent OS-level launch
(dock reopen, second `open`); it does not by itself close the zero-delay
race (Spike-3's own finding, cited in m4 synthesis §6 and brief-3 §1 A-row
AC3). The fs2 check must gate spawning; the plugin must not be relied on
alone.

## 4. Test plan — 7 ACs

Baseline `make test` runtime is asserted ~322s in m4's adversarial brief
(unverified staleness noted there — re-time at implementation).
Recommend **one session-scoped pytest fixture** that boots the real
`server.desktop_child` process once and shares it across the AC1/AC2/AC4
assertions below, so the 5-30s BGE-M3 warm-up (`server/main.py:61-66`) is
paid once per test run, not 3×.

| AC | Test file | Assertion | Defeats cheap lie | `make` target |
|---|---|---|---|---|
| AC1 (single real child reaches health/readiness; console renders; entry point ≠ fixture sidecar) | `tests/test_desktop_child.py` | (a) spawned argv/module is `[sys.executable, "-m", "server.desktop_child"]`, never references `fixture-sidecar`/`ARXMCP_FIXTURE_SIDECAR`; (b) first successful `/readyz` response's `warm` map is `{"embedder": true, "lancedb": true, "reranker": true}`, not merely HTTP 200; (c) GET `bound.ui_url` returns real `/ui/` HTML (assert a known page marker) | Wiring to `fixture-sidecar` and never booting the real server (m4 brief-3 AC1 row) | `desktop-conformance` (real BGE-M3 boot — too slow for `make test`) |
| AC2 (real MCP smoke; live bytes hash `EXPECTED_TOOL_SCHEMA_SHA256`) | same file, same fixture | `initialize` → capture `mcp-session-id` → `tools/list`; hash the **live** response bytes with the same function `tests/test_server_tool_schema.py:182-190` uses; assert equal to `EXPECTED_TOOL_SCHEMA_SHA256` (`tests/test_server_tool_schema.py:94`) | Calling `/healthz` and naming it "the smoke", or mocking the JSON-RPC response (m4 brief-3 AC2 row) | `desktop-conformance` |
| AC3 (second launch, no delay: exactly one spawn) | new `apps/desktop/crates/supervisor/tests/` (or a Python-driven dual-process test) | Reproduce Spike-3's external-barrier technique (`tools/desktop_lifecycle_spike/run_spike.py:579-636`, `await_launch_barrier`): start two supervisor processes held at a shared barrier, release simultaneously, assert exactly one records `owns_supervisor_lock=true` and spawns; the other exits 0 pre-spawn. Fixture sidecar as the spawned child is acceptable here (AC3 tests supervisor-level arbitration, not the real server) — note this explicitly as a scope choice, not a silent cut | Sequential launch with a sleep, proving nothing about the race (m4 brief-3 AC3 row) | `desktop-conformance` |
| AC4 (m5 slice: *normal*-shutdown only — no fault matrix) | `tests/test_desktop_child.py`, shares the AC1/AC2 fixture | After the MCP smoke: send authenticated `shutdown`, `process.wait(timeout=...)`, assert `returncode == 0`; run `lsof -nP -iTCP:<port> -sTCP:LISTEN` (or connect-attempt) **and assert the probe command itself exited 0/succeeded**, not merely that its output was empty; if the supervisor writes ANY diagnostics file in m5, recursively scan it (`root.rglob("*")`) for the capability-token bytes, mirroring `tests/test_desktop_contract.py:413-416` | "Empty `ps`/`lsof` output" treated as clean absence without checking the probe itself succeeded (m4 brief-3 AC4 row, citing Spike-3's own methodology) | `desktop-conformance` |
| AC5 (`validate_port_range` unchanged; no non-desktop path gains ephemeral bind) | a config-layer unit test (e.g. extend `tests/test_config.py` if it exists, else a new small file) | `Config(bind_port=0)` still raises (regression, zero new infra); structural check that `server/desktop_child.py` never constructs `Config(bind_port=...)` | A "quick fix" that widens the validator instead of pre-binding outside `Config` | `make test` (fast, no subprocess) |
| AC6 (`X-ArXMCP-Startup-Token` on `/readyz`, desktop-path-scoped, pure-ASGI, existing callers unaffected) | `tests/test_desktop_child.py::test_readyz_middleware_*` (pure-ASGI unit test via `httpx.ASGITransport`, no subprocess) | No header → 401; wrong/malformed token → 401 via `tokens_equal`; correct token → 200 passthrough; a request to `/mcp` or `/healthz` with no token unaffected (path-scoping proof); regression grep: `"ReadyzStartupTokenMiddleware" not in Path("server/main.py").read_text()` | A `BaseHTTPMiddleware` shortcut, or registering it inside `create_app` and silently breaking the 11 existing `/readyz` callers (§3.3b) | `make test` (pure-ASGI, no Rust/subprocess needed) |
| AC7 (`make test` + `make desktop-conformance` exit 0) | n/a — CI-gate outcome | Both targets green | — | both |

**Deadlines**: per m4 brief-3's precedent (m3 had to raise a 200ms deadline
to 2000ms under repository load), set per-poll HTTP timeouts to `>= 2.0s`
(matching `tests/test_desktop_contract.py`'s existing `timeout=2`
convention) and an **overall** bound-frame + first-ready-response wait
budget of `>= 60s` for the real-server tests (the eager warm-up alone is
documented at up to ~30s, `server/main.py:61-66`) — do not reuse the
fixture-sidecar's tight sub-second assumptions for the real-server tests.

## 5. Honest LOC + file estimate (m5 alone)

| Component | Files | LOC |
|---|---:|---:|
| `server/desktop_child.py` (entry point, `read_frame`, driver, shutdown watcher, `ReadyzStartupTokenMiddleware`) | 1 | 300–450 |
| `apps/desktop/crates/supervisor/` (`Cargo.toml`, `build.rs`, `tauri.conf.json`, `src/main.rs` — fs2 lock, spawn via `tauri-plugin-shell`, read `bound` w/ bounded timeout, poll `/healthz`+`/readyz`, one MCP smoke `initialize`+`tools/list`, window creation, normal-shutdown-only two-state render: starting→ready) | 5–6 | 500–750 |
| `tests/test_desktop_child.py` (real-server AC1/AC2/AC4/AC6, shared fixture) | 1 | 200–320 |
| `apps/desktop/crates/supervisor/tests/` (AC3 race test) | 1–2 | 120–220 |
| Config regression test (AC5) | 1 (new or extended) | 20–50 |
| `apps/desktop/Cargo.toml` / `Makefile` edits (workspace member, `desktop-conformance` extension to build+run the supervisor bin) | 2 | 30–60 |
| **Total** | **~11–13** | **~1,170–1,850** |

**This exceeds the 800-LOC ABORT gate.** Say so plainly to the
orchestrator before Phase 2 rather than let it surface mid-diff — the
m4→m5/m6 split already shrank the surface (m5 drops the fault matrix, the
30-cycle stress, and 2 of the supervisor's 4 render states), but the
combination of a first-ever Tauri crate + a first-ever real-server desktop
boot test still clears the gate by a wide margin. If Phase 2 pushes back,
the remaining trim room is: (a) reuse the AC3 race test's process spawn
code as a thin wrapper around AC1's real-child spawn code rather than a
parallel implementation, and (b) confirm with the orchestrator whether
`--allow-large-diff` (the path all three m1-m3 desktop milestones already
took, per m4 brief-3 §3) is pre-authorized for m5 too.

## 6. Alternatives considered

- **`--desktop-child` flag on `arxmcp-server`** — rejected; contradicts
  `server/cli.py:23-29`'s explicit "no second config source" design
  rationale, which m4's brief-1 didn't weigh against this specific case.
- **New `arxmcp-server-desktop-child` console script in `pyproject.toml`**
  — rejected as unnecessary; `python -m server.desktop_child` needs zero
  packaging changes and is exactly analogous to the already-documented
  `python -m server.main` equivalence at `server/cli.py:31,69-70`.
- **`app.add_middleware(ReadyzStartupTokenMiddleware, ...)` inside
  `create_app()`** — rejected; would make the token-gate a property of
  every boot path (Docker, `make up`, every test), breaking the 11 existing
  unauthenticated `/readyz` callers (§3.3b) and requiring a Config field or
  env var to carry the token in, reopening the unknown-`ARXMCP_*` FATAL
  scan risk the milestone explicitly warns against.
- **Calling `uvicorn.Server(...).run(sockets=[sock])` directly** — rejected;
  it is a fully blocking all-in-one call with no hook point between
  socket-bind and main-loop, so there is no safe place to emit `bound`
  without racing the listen state. Hand-driving `startup()`/`main_loop()`/
  `shutdown()` (§3.1 step 7) is the only way to guarantee correct ordering.
- **Bounding `uvicorn.Config(timeout_graceful_shutdown=grace_ms/1000)`
  inside the Python child** — rejected for m5; the default (`None`, wait
  unboundedly for connections to drain) is already a superset of "at least
  grace_ms", and double-bounding it risks a mismatch with the supervisor's
  own outer TERM/KILL timer. Revisit only if m6's fault matrix needs a
  tighter internal deadline.
- **Reusing `tools/desktop_lifecycle_spike` code directly** — rejected
  (settled, m4 synthesis §8): pre-M3 wire format, evidence code only.

## 7. Risks and unknowns

- **`Resources.warm` per-component timing not fully audited.** §3.1's
  ordering guarantee (bound emitted after both listen AND lifespan startup
  complete) is solid, but whether *every* one of `embedder`/`lancedb`/
  `reranker` is synchronously warm at that exact instant depends on
  `Resources` internals not read in this pass — tests must poll `/readyz`
  with a bounded timeout (§4 deadlines), not assert instant-200.
- **`sha256` identity for a Python child has no established convention.**
  §3.1 step 3's "hash `desktop_child.py`'s own source" is this brief's
  proposal, not a pre-existing pattern — flag to the security reviewer
  explicitly rather than let it pass as settled.
- **Cross-platform**: process spawn/lock work is macOS-only for m5
  (release boundary per `apps/desktop/README.md:11-16`, settled). If any
  signal name or `setpgid` call is needed for the *normal*-shutdown path
  (it should not be — normal shutdown is stdin-EOF/shutdown-frame driven,
  not signal-driven), keep it behind a named seam per m4 synthesis §6
  Invariant, not inlined.
- **GPG signing / conventional commits** — routine; Rust+Python cross-
  language diff, same 3-commit pattern as m1-m3.
- **Sync-wave / IRSA / cross-cluster** — not applicable (single-user
  desktop app, no Kubernetes surface).

## 8. external_writes_required

- `git push origin main` — gated per-event per `CLAUDE.md` External System
  Write Policy; no other write applies (no GitLab/Confluence/AWS/ArgoCD
  surface in this repo).
- **No `Fixes #397` trailer on m5's push.** Per the dispatch prompt, m5
  does not close issue #397 — m6 does. `.claude/scripts/
  milestone-pipeline-issue-note.py` remains a no-op for both ids (no
  `plans/desktop-distribution/roadmap.yaml` exists, confirmed by m4
  brief-2 §2), so no automated progress-comment write fires either.

## 9. Open questions for the user

None — the task's 8 numbered items were all resolvable from installed
source + existing repo precedent within this research pass. The one
genuine design choice this brief makes (not merely reports) is §3.1's
entry-point mechanism (`python -m server.desktop_child` over a flag or
console script) and §3.1 step 3's sha256-of-own-source identity
convention — both are flagged inline as decisions for the implementer/
critic to explicitly ratify or overturn, not silent defaults.
