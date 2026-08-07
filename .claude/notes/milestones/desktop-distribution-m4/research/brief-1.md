# desktop-distribution-m4 — explore research brief

## 1. TL;DR

Add a **new Rust supervisor crate** in `apps/desktop/crates/` that spawns the
real `arxmcp-server` (not the fixture sidecar) over the M3 NDJSON contract,
plus a **new Python child-launcher module** that teaches `arxmcp-server` to
bind an ephemeral loopback socket, hand it to uvicorn pre-bound, and speak
the `Launch`→`Bound`→`Shutdown` protocol on stdin/stdout — nothing today
does either half. The main risk is scope: no Tauri shell exists anywhere in
`apps/desktop/` yet (only `desktop-contract` + `fixture-sidecar` crates), so
"renders starting/ready/degraded/failed states" is greenfield desktop-app
scaffolding, not a wiring task, and the honest LOC estimate (~1200–1900)
clears the Phase-2 800-LOC gate by a wide margin. Backup plan: split M4 into
a Python-side sub-slice (child-launcher + pre-bound-socket support, testable
headlessly against `desktop-conformance`'s existing fixture-sidecar harness)
and a Rust/Tauri sub-slice (window + single-instance + process lifecycle),
landing the walking skeleton without the window first if the gate forces a
split.

## 2. Prior art in this repo

- `server/desktop_contract.py:1-709` — the full Python half of the wire
  contract (M3). `ChildControlState`, `parse_frame`/`encode_frame`,
  `StartupToken`/`tokens_equal`, `MIN_GRACE_MS=35_000`,
  `STARTUP_TOKEN_HEADER="X-ArXMCP-Startup-Token"` all exist and are usable
  as-is. **Nothing in `server/` imports this module today** — only
  `tests/test_desktop_contract.py` does. M4 is the first production
  consumer.
- `apps/desktop/crates/desktop-contract/src/lib.rs:1-727` — the Rust mirror,
  byte-identical wire semantics, already a workspace member. A new
  supervisor crate depends on this via `path = "../desktop-contract"`
  exactly as `fixture-sidecar/Cargo.toml:9` does.
- `apps/desktop/crates/fixture-sidecar/src/main.rs:1-285` — the ONLY
  existing example of the child side of the protocol: binds
  `TcpListener::bind((Ipv4Addr::LOCALHOST, 0))` (line 76), emits `Bound` on
  stdout, serves `/healthz` unauthenticated and `/readyz`
  capability-gated via `X-ArXMCP-Startup-Token` (lines 260-278), and exits
  on a valid `Shutdown` frame or stdin EOF (`serve_until_stopped`,
  lines 216-236). This is the template for the **Python** child-launcher
  M4 must add for the real server — no equivalent exists in `server/`.
- `apps/desktop/README.md:98-103` states in its own words: *"Production
  port-zero adoption, authenticated server readiness, ordinary Tauri exit
  handling, and universal cleanup are explicitly deferred to the lifecycle
  walking skeleton."* — i.e. M4 by design, confirmed by the repo's own
  M3-era documentation.
- `tools/desktop_lifecycle_spike/src/main.rs:1-832` and
  `tools/desktop_lifecycle_spike/src/lib.rs:1-177` — Spike-3's disposable
  evidence code (see §7 for the reusable design elements). **Not the
  production home** — a different (older, pre-M3) wire format
  (`Bootstrap`/`Bound` with `pid`/`pgid`/`canary_pid` fields, `TOKEN_CANARY`
  prefix) that M3's `desktop-contract` crate superseded. Do not import or
  extend this crate; re-derive the same *design* against the current
  `desktop-contract` types.
- `server/cli.py:112-216` (`main()`) — the current sole production entry
  point. Calls `uvicorn.run("server.main:app", host=cfg.bind_host,
  port=cfg.bind_port, lifespan="on", log_config=None)` (lines 209-215) —
  a **fixed host/port from `Config`**, no pre-bound-socket path, no NDJSON
  protocol I/O. `Config.validate_port_range` (`server/config.py:825-838`)
  rejects any port outside `[1024, 65535]`, so `0` (ephemeral-port request)
  is rejected at the `Config` layer — confirming port-0 binding for the
  desktop child MUST happen at the raw-socket level, outside `Config`
  entirely, then be handed to uvicorn.
- `server/main.py:100-131` (`_BYTE_CAP_EXEMPT_PREFIXES`),
  `server/middleware.py:1-1582` — the full middleware stack
  (`OriginValidationMiddleware`, `HostValidationMiddleware`,
  `SecFetchSiteMiddleware`, `SecurityHeadersMiddleware`,
  `RequestBodySizeLimitMiddleware`, `SessionCapMiddleware`,
  `BodySizeCapMiddleware`). **No middleware anywhere checks
  `X-ArXMCP-Startup-Token`** — confirmed by
  `grep -rn STARTUP_TOKEN_HEADER server/` returning only the constant's
  definition and its `__all__` export in `desktop_contract.py`. The
  constant is currently dead code outside the fixture sidecar and the
  contract test.
- `server/health.py:252-364` — `/healthz` (always 200) and `/readyz`
  (503 until warm; also handles bootstrap-mode and degraded-mode bodies).
  Neither route reads any header. This is the endpoint the smoke-request
  AC and the "reaches health/readiness" AC will poll.
- `server/application_paths.py:1-50+`, in particular `_LAYOUT` (line 23-32)
  including `("logs", "logs")` — `ApplicationPaths.logs` resolves to
  `<data_root>/logs`, which is exactly the shape
  `desktop_contract._validate_paths` (`server/desktop_contract.py:467-478`)
  requires (`log_location` must be `data_root/logs/<file>`). The desktop
  launch's `data_root` should be passed straight through to
  `ApplicationPaths.resolve(root=...)` — this module is the sole owner of
  the on-disk layout and must not be duplicated or reimplemented.
- `tests/test_desktop_contract.py:1-497` — the full M3 conformance +
  live-process lifecycle suite (see §5 for structure).
- `Makefile:145-150` (`desktop-conformance`) — builds `fixture-sidecar`
  then runs `tests/test_desktop_contract.py` with
  `ARXMCP_FIXTURE_SIDECAR` pointed at the built binary. This is the
  target M4's new supervisor-side tests should be wired into (either by
  extension or a new target chained after it).
- `pyproject.toml:82-97` (`[project.scripts]`) — `arxmcp-shim` and
  `arxmcp-server` are the only two console scripts. No
  desktop-child-mode script exists; M4 needs either a new flag/subcommand
  on `arxmcp-server` or a new console-script entry (see §6).

## 3. Relevant Nalej MCP context

Not applicable — this milestone is entirely internal to the arXMCP repo;
Nalej platform MCP tools (ArgoCD, AWS, service-mesh, etc.) have no bearing
on a desktop Tauri/Rust+Python lifecycle contract. No `search_platform_knowledge`
findings were relevant; skipped per repo scope.

## 4. Existing skills/agents that could implement this

None of the repo's bespoke `.claude/agents/` (milestone-* pipeline agents)
specialize in Rust/Tauri or desktop process lifecycles; the milestone brief's
own specialist suggestions (`mcp-protocol-reviewer`, `security-reviewer`) are
review-time critics, not implementers. No existing skill/agent should be
dispatched in place of the standard `milestone-implementer`.

## 5. External sources reviewed

| Source | URL | Key finding | Relevance | License |
|---|---|---|---|---|
| uvicorn source (installed, `.venv`) | `.venv/lib/python3.12/site-packages/uvicorn/server.py:74-77` | `Server.run(sockets=...)` / `Server.serve(sockets=...)` accepts a list of pre-bound `socket.socket` objects (uvicorn **0.46.0**, installed version, verified by direct read, not docs) | Confirms the ephemeral-port-then-handoff pattern is directly supported without a custom ASGI-server fork | BSD-3 (uvicorn) |
| uvicorn source | `.venv/lib/python3.12/site-packages/uvicorn/config.py:369-408` | `Config.configure_logging()` is a full no-op when `log_config=None` (the exact value `server/cli.py:213` already passes) — no dictConfig runs, uvicorn's `uvicorn.access`/`uvicorn.error` loggers get no handlers of their own and propagate to root | Directly answers the stream-ownership question (§ below); no doc/web source needed, verified against the pinned dependency itself | BSD-3 (uvicorn) |
| Tauri single-instance plugin (used in Spike-3, not fetched externally — version pin read from `tools/desktop_lifecycle_spike/run_spike.py:694`) | n/a (local file) | `"tauri-plugin-single-instance": "2.4.3"` pinned in the spike's `tauri.conf.json`-equivalent | M4's supervisor, if it adopts Tauri, has a version precedent already spiked and GO'd | MIT/Apache-2.0 (Tauri ecosystem, standard) |

No arXiv/CNCF/OSS web search was run: the milestone is a pure wiring/lifecycle
task fully specified by the repo's own M2/M3 contract and spike evidence: a
fresh external survey would not out-inform code already in this tree, and the
`.claude/notes/milestones/desktop-distribution-spike-3` GO decision already
represents the external-tool selection (Tauri, `fs2`, `libc` signal helpers).
Deep-mode external sourcing was not requested (`DEEP_MODE` not set to
`true`).

## 6. Recommended approach

Two independently landable halves; implement the Python half first since
it is testable headlessly and unblocks the Rust half's own tests.

**A. Python child-launcher (`server/desktop_launcher.py`, new).**
A new module, imported by a new `main()`-equivalent (either a
`--desktop-child` argparse flag added to `server/cli.py:94-109`'s parser, or
a new `arxmcp-server-desktop-child` console script in `pyproject.toml`
alongside the two existing entries at `pyproject.toml:82-97` — prefer the
flag, since it keeps one script name Claude Code / docs already reference).
Responsibilities, mirroring `fixture-sidecar/src/main.rs` structure:
1. Read one `Launch` frame from stdin via `server.desktop_contract.parse_frame`
   (reuse `read_frame`-equivalent framing — Python side currently has no
   `read_frame` helper, only `parse_frame` on a full `bytes` blob; add a
   thin stdin-line reader).
2. Validate `launch.executable` identity (component/sha256/version) against
   the running interpreter/package — mirror
   `fixture-sidecar::validate_fixture_launch` (lines 98-117).
3. Bind `socket.socket(AF_INET, SOCK_STREAM)` to `("127.0.0.1", 0)`,
   read back the OS-assigned port.
4. Build `Config` with `data_dir=launch.data_root` (NOT `bind_port` — that
   field stays at its `Config`-validated default and is simply unused on
   this path since the raw socket bypasses it), construct the app via
   `server.main.create_app`, then run uvicorn via
   `uvicorn.Server(uvicorn.Config(app, ...)).run(sockets=[sock])`
   (confirmed supported, §5) instead of `uvicorn.run(host=, port=)`.
5. Once the ASGI server's socket is listening (before or via a startup
   hook), emit exactly one `Bound` frame on stdout via `encode_frame`, then
   flush and stop writing to stdout for the rest of the process lifetime.
6. Spawn a background reader thread/task on stdin for the `Shutdown` frame
   (token-checked via `tokens_equal`) OR stdin EOF — either terminates the
   uvicorn server via its `should_exit` flag, honoring `MIN_GRACE_MS`
   (35s) before a force path.
7. **Open design gap (flag for the implementer, do not silently decide):**
   the wire contract's own README (`apps/desktop/README.md:105-118`)
   documents the startup token as valid on the `/readyz` header, but no
   production middleware enforces it (§2). M4's AC only requires "reaches
   health/readiness" and "one MCP smoke request" — neither strictly
   requires token-gating `/readyz`/`/mcp`. Decide explicitly whether M4
   adds a new `StartupTokenMiddleware` (scoped ONLY to the desktop-child
   code path, not the normal `arxmcp-server` boot, to avoid breaking every
   existing docker/CLI/test caller of `/readyz`) or defers auth to a later
   milestone. Either way, document the decision — do not let it lapse
   silently as the fixture sidecar's behavior implies but the real server
   doesn't implement.

**B. Rust supervisor (new crate `apps/desktop/crates/supervisor`).**
New `Cargo.toml` workspace member (add to `apps/desktop/Cargo.toml:2-5`
`members`), depending on `arxmcp-desktop-contract` (path dep, mirrors
`fixture-sidecar/Cargo.toml:9`) plus `fs2` (single-instance lock,
precedented at `tools/desktop_lifecycle_spike/src/main.rs:5,128,669`) and
`libc` (process-group signaling, precedented at lines 300-389 of the same
file). Responsibilities: acquire the single-instance file lock in
`ApplicationPaths`-equivalent runtime dir; on lock failure, activate the
existing instance (if Tauri: `tauri-plugin-single-instance` 2.4.3, already
spiked GO at `run_spike.py:694,735`) or exit cleanly per AC3; on lock
success, `setpgid`-isolate and spawn the real `arxmcp-server --desktop-child`
(from A above) with the `Launch` frame on its stdin; read the `Bound` frame
off its stdout with a bounded timeout (startup-timeout AC); poll
`/healthz`→`/readyz` to detect ready/degraded; issue one MCP smoke
`tools/list` or `initialize` JSON-RPC POST to the `mcp_url` from `Bound`;
render starting/ready/degraded/failed state (webview pointed at the
server's own `/ui/`, per `apps/desktop/README.md:25-26` — "The future
desktop shell will continue to use the existing server-rendered operator
console", i.e. **do not build new UI**, just host the existing `/ui/`);
on shutdown/crash/timeout, close stdin (EOF lease) then TERM→wait→KILL→reap
the process group, mirroring `signal_owned_child`/`terminate_gracefully`
at `tools/desktop_lifecycle_spike/src/main.rs:300-389`.

**C. Tests.** Extend `tests/test_desktop_contract.py` (or a sibling
`tests/test_desktop_supervisor.py`) with the 30-cycle fixture-sidecar
lifecycle stress test the AC names explicitly — note the AC says
*"fixture-sidecar cycles"*, i.e. the mandated stress loop still targets the
FAST fixture sidecar (no BGE-M3/LanceDB load), not the real server; keep it
that way for the 30-iteration bound to stay fast. A separate, smaller
(non-looped) test should exercise the real Python child-launcher end to end
(desktop-conformance-style) since AC1/AC2 name the real server explicitly
("exactly one child server reaches health/readiness", "MCP smoke request").
Wire both into `Makefile:145-150`'s `desktop-conformance` target or a new
target chained after it — do not silently skip on missing Cargo, per the
existing `desktop-conformance` all-or-nothing gate philosophy stated in its
own comment (`Makefile:142-144`).

## 7. Alternatives considered

- **Reuse `tools/desktop_lifecycle_spike` code directly** — rejected; it
  targets a different, pre-M3 wire format (`Bootstrap`/`pid`/`pgid`/
  `canary_pid`, `TOKEN_CANARY` prefix) that the M3 `desktop-contract` crate
  superseded, and the milestone brief explicitly frames this as "evidence
  code, NOT the production home." Reuse the *design* (fs2 lock, TERM→wait→
  KILL→reap, single-instance plugin ordering), not the code.
- **Bind the port inside `Config` by allowing `bind_port=0`** — rejected;
  `Config.validate_port_range` (`server/config.py:825-838`) intentionally
  rejects `0` and the docstring frames rejecting `0.0.0.0`/out-of-range as
  load-bearing security posture (Threat 4/5). Widening that validator to
  accept `0` would also affect every non-desktop boot path
  (`docker/Dockerfile.server`, `make up`, the wheel install) that reads
  `ARXMCP_BIND_PORT`. The pre-bound-socket approach (bind outside `Config`,
  hand the live socket to uvicorn) avoids touching `Config` at all.
- **Skip the Tauri window and ship a headless supervisor only** — rejected
  as satisfying the AC as written ("existing console renders in the
  desktop window") but flagged in Risks as the most likely place the
  800-LOC gate forces an actual split.

## 8. Risks and unknowns

- **Scope size.** No Tauri app scaffold exists in `apps/desktop/` today —
  only the two contract/fixture crates. Standing up a window shell,
  single-instance activation, MCP smoke call, and 30-cycle lifecycle test
  is realistically 1200-1900 LOC across Rust + Python + tests + Cargo/Tauri
  config, well past the Phase-2 800-LOC hard gate. Flag for explicit
  splitting (Python child-launcher first, Rust/Tauri shell second) rather
  than attempting one 4-phase pipeline pass.
- **STARTUP_TOKEN_HEADER enforcement gap.** The wire contract's own README
  documents token-gated `/readyz`; nothing in `server/` enforces it today.
  Silently NOT adding this in M4 leaves the desktop child's `/readyz` open
  to any loopback process (weaker than the fixture sidecar's own posture).
  Silently ADDING it without scoping to the desktop-child code path could
  break existing test/CLI/docker callers of `/readyz`. Must be an explicit
  design decision, not a default.
- **uvicorn pre-bound-socket + lifespan interaction.** `uvicorn.Server.run(
  sockets=[...])` bypasses `uvicorn.run(host=, port=)`'s own socket setup,
  but the FastAPI `lifespan` context (which does the heavy BGE-M3/LanceDB
  warm-up in `server/main.py:460-677`) is unaffected by the swap — verify
  with a smoke test, not by inspection alone, since this exact combination
  (custom `Config`/`Server` construction + FastAPI lifespan +
  `sockets=` handoff) has no existing test coverage in this repo.
- **Cross-platform TERM/process-group semantics.** `desktop-contract`'s
  `ShutdownSemantics.reap` is deliberately platform-neutral
  (`"graceful-force-reap"`) per `apps/desktop/README.md:14-16`; the actual
  `setpgid`/`SIGTERM`/`SIGKILL` implementation is POSIX-only (as the spike's
  `libc` usage already is). Confirm the milestone's AC ("bounded cleanup...
  writes redacted diagnostics") is scoped to macOS (the only release target
  per `apps/desktop/README.md:11-16`) so a Windows process-object adapter is
  correctly deferred, not silently assumed.
- **GPG signing / conventional commits** — routine repo convention
  (`CLAUDE.md §4.3`); no special risk beyond the usual three-commit
  pattern given the cross-language (Rust+Python) diff surface.
- **Sync-wave / cross-cluster / IRSA wiring** — not applicable; this repo
  has no Kubernetes/ArgoCD surface (single-user desktop app project).

## 9. External-write actions required

None identified at research time. This is a pure local code change (new
Rust crate, new Python module, new tests, Cargo.toml/Makefile edits) with no
GitLab, Confluence, AWS, or ArgoCD interaction. The only external write at
implementation completion will be the routine `git push` to `main` per
`CLAUDE.md §4.1/§4.4` — subject to the same per-event "push when the user
asks" authorization as every other change in this repo, not a new class of
external write.

## 10. Open questions for the user

- Should M4 land the Tauri window shell in the same pass as the Python
  child-launcher, or should the implementer propose a Phase-2 split (child
  process control + real-server lifecycle first; window/UI shell as a
  follow-up slice) given the LOC estimate in §8? The roadmap's own
  `desktop-distribution-e2` outcome text implies the full window-to-MCP
  path is the value slice, but the M4 brief text itself ("walking
  skeleton") suggests a headless-first cut may be acceptable — this
  wasn't disambiguated in the roadmap doc.
