# desktop-distribution-m4 — external research brief (agent-solo research role: general/external)

## 1. TL;DR

Every external dependency claimed by the brief is present and verified against
installed source: uvicorn 0.46.0 supports handing a pre-bound, non-inheritable
`socket.socket()` straight to `Server.serve(sockets=[sock])`/`.run(sockets=...)`
with `--workers`/reload provably irrelevant to that code path, mcp==1.27.1's
Streamable HTTP POST handler needs only `Content-Type: application/json` +
`Accept: application/json, text/event-stream` + (after `initialize`) the
`mcp-session-id` header, and Tauri 2.11.5 + tauri-plugin-shell 2.3.5 +
tauri-plugin-single-instance 2.4.3 + tauri-build 2.6.3 give a `cargo build`-only
(no `cargo tauri`, no Node) path to a runtime-URL window, a stdin/PID/stdout
sidecar handle, and second-launch focus. The biggest real risk is scope
creep from conflating "the relocatable server" (M2's already-shipped
installed-wheel `arxmcp-server`) with "a bundled/frozen, ambient-Python-free
executable" (Spike-1's explicit NO-GO, deferred to epic e4/"platform trust
gates"); the milestone's own text says "the relocatable server," matching M2,
not "the bundled server." Backup plan if the implementer or critic disagrees:
land M4 against the M2 installed wheel/venv `arxmcp-server` now and open a
new e4-lane milestone for PyInstaller onedir + signing/notarization, rather
than absorbing spike-1's open release blockers into this M-complexity slice.

## 2. Prior art in this repo

- `apps/desktop/Cargo.toml:1-19` — the `[workspace.dependencies]` table has
  **no** `tauri`/`tauri-plugin-*` entries yet; only `getrandom`, `serde`,
  `serde_json`, `sha2`. M4 is the first milestone that touches Tauri at all.
- `apps/desktop/crates/fixture-sidecar/src/main.rs:76-96` — the only existing
  example of port-zero binding in this repo: `TcpListener::bind((Ipv4Addr::LOCALHOST, 0))`,
  `set_nonblocking(true)`, then read back `local_addr()` before emitting
  `Bound`. This is the Rust-side analogue of what uvicorn needs on the Python
  side (Q1 below); no code anywhere yet does the Python half.
- `apps/desktop/crates/fixture-sidecar/src/main.rs:216-236,271-278` (Rust
  `shutdown`) and `.venv/.../uvicorn/server.py:271-278` (Python `shutdown`)
  independently converge on the same pattern: close the accept loop, then
  close the retained socket — confirms the M3 contract's "grace/force/reap"
  semantics map cleanly onto uvicorn's own `sockets=` shutdown path.
- `apps/desktop/README.md:60-136` — the versioned NDJSON wire protocol
  (`launch`→`bound`→`shutdown`), startup-token handling, and the explicit
  sentence "Production port-zero adoption, authenticated server readiness,
  ordinary Tauri exit handling, and universal cleanup are explicitly deferred
  to the lifecycle walking skeleton" — i.e. deferred to M4, confirming scope.
- `server/middleware.py:396-499` (`OriginValidationMiddleware`) — Origin
  values in `LOOPBACK_ORIGIN_HOSTS` (`127.0.0.1`, `localhost`, `::1`, any
  port) already pass; a Tauri window loading `http://127.0.0.1:<port>/ui/`
  and firing same-origin fetch/htmx requests needs **no** CSP or
  `allowed_origins` change (Q4).
- `server/_mcp_mount.py:1-80` — `/mcp` is mounted via
  `FastMCP.streamable_http_app()`, verified against `mcp==1.27.1`, with tools
  registered before mount (E06_S03 snapshot-at-mount constraint) — the smoke
  client just needs to hit `POST /mcp` after the child is `ready`.
- `tests/test_server_tool_schema.py:182-190` —
  `compute_tool_schema_hash(tools)` hashes the **live registered tool list**
  from `server/tools.py`, not any wire response; a read-only client-side
  `tools/list` call cannot touch it (Q2 confirmed).
- `.claude/notes/spikes/desktop-distribution-spike-1.md` — PyInstaller 6.21
  `onedir` NO-GO for release (759 MB, 74 s build, OpenMP collision, no
  macOS-14 claim, ad-hoc-only signing); explicitly names five release
  blockers, all still open, all belonging to epic e4 not e2/M4 (Q5).
- `.claude/notes/milestones/desktop-distribution-m2/rectify/summary.md:24-76`
  — M2 shipped: installed `arxmcp-server` relocatable, all writer paths
  proven under `ARXMCP_DATA_DIR`, settings persistence proven, provenance
  canonicalized. This is "the relocatable server" the M4 brief names.
- `pyproject.toml:99` — `arxmcp-server = "server.cli:main"` console script
  already exists and is what M2 relocated; no new entrypoint needed for the
  installed-wheel path.
- `plans/desktop-distribution-roadmap.md:88-115` — epic split: e2 ("Native
  launch reaches a healthy MCP session," M4's parent) vs. e4 ("macOS artifact
  passes platform trust gates" — signing/notarization/Developer ID, size L,
  Next-lane, not yet materialized into milestones). PyInstaller bundling and
  its release blockers are e4's job, not e2/M4's.
- `.claude/references/github-conventions.md:20-43` — `Fixes #N` closes an
  issue only as a side effect of the already user-gated push landing; the
  ANNOTATE-class issue-note script is a separate, independent mechanism.
- `.claude/scripts/milestone-pipeline-issue-note.py:89,161` — scans
  `plans/*/roadmap.yaml`; `plans/desktop-distribution-tickets/` has no
  `roadmap.yaml` (desktop-distribution is legacy prose), so the script warns
  "not found in any plans/*/roadmap.yaml" and exits 0 — a verified no-op for
  this ID (Q6).
- `plans/desktop-distribution-tickets/github-object-map.json:72` — confirms
  `{"number": 397, "id": "desktop-distribution-m4", "kind": "milestone"}` on
  `chris-dare-dev/arXMCP` (GitHub, not GitLab — this repo's remote is GitHub,
  confirmed via `git remote -v`).

## 3. Relevant Nalej MCP context

Not applicable — this is the arXMCP repo (not a Nalej platform repo); no
Nalej MCP tools were queried, per repo scope.

## 4. Existing skills/agents that could implement this

None found under `.claude/agents/` specific to Tauri/desktop supervisors;
the milestone's own specialist suggestions (`mcp-protocol-reviewer`,
`security-reviewer`) are the closest match and are already named in the
brief.

## 5. External sources reviewed

| Source | URL / location | Key finding | Relevance |
|---|---|---|---|
| uvicorn source (installed) | `.venv/lib/python3.12/site-packages/uvicorn/server.py:74-278` | `Server.run`/`.serve(sockets=[sock])` accepts a pre-bound socket list; both `startup(sockets=...)` and `shutdown(sockets=...)` receive the **same** list, and `shutdown` explicitly `sock.close()`s each one — caller must not double-close. | Confirms Q1's exact API and that uvicorn owns socket teardown. |
| uvicorn source (installed) | `.venv/.../uvicorn/main.py:604-624` vs `server.py:81-98` | `reload`/`workers>1` branching lives ONLY in the CLI-style `uvicorn.run()` wrapper (`main.py`), which dispatches to `ChangeReload`/`Multiprocess` supervisor classes; calling `Server(config).serve(sockets=...)` directly (as an asyncio task, which M4 must do) never touches that branch. | Confirms `--workers`/reload are provably irrelevant to the pre-bound-socket path, as the brief assumed. |
| Python socket module semantics (PEP 446, stdlib) | n/a (language spec) | `socket.socket()` is non-inheritable-by-default since Python 3.4; no explicit `set_inheritable(False)` call is needed unless something upstream flips it. | Answers "must the socket be non-inheritable" — yes, and it already is by default. |
| mcp SDK source (installed) | `.venv/.../mcp/server/streamable_http.py:407-527,825-881` | POST handler requires `Accept` containing `application/json` (plus `text/event-stream` unless JSON-only mode), `Content-Type: application/json`; `initialize` is exempted from the session-id/protocol-version header checks, all later requests are not; `mcp-session-id` and `mcp-protocol-version` are the two header constants. `DEFAULT_NEGOTIATED_VERSION="2025-03-26"`, `LATEST_PROTOCOL_VERSION="2025-11-25"` (`mcp/types.py:27,35`). | Gives the exact minimal wire sequence for Q2: `initialize` (no session header required) → capture `mcp-session-id` from the response → subsequent `tools/list`/`ping` POSTs carry that header. |
| tauri crate source (cargo registry cache) | `~/.cargo/registry/src/.../tauri-2.11.5/src/webview/webview_window.rs:279-310` | `WebviewWindowBuilder::new(app, label, WebviewUrl::External(url))` builds a window at an arbitrary runtime URL from inside `.setup()`; no `dangerous_remote_domain_ipc_access` symbol exists anywhere in this crate version (grep-verified) — that config key lives only in the legacy `tauri-utils::config_v1` compat shim and `ipc/authority.rs`, and is only needed to expose the Tauri **JS IPC bridge** to a non-`tauri://` origin. | Confirms Q4: creating the window at a computed loopback URL needs no static `tauri.conf.json` URL; IPC/capabilities are irrelevant unless the `/ui/` page calls `window.__TAURI__` (it doesn't — it's plain htmx). |
| tauri-plugin-shell source | `~/.cargo/registry/src/.../tauri-plugin-shell-2.3.5/src/process/mod.rs:31-84,305` | `Command::spawn()` returns `(Receiver<CommandEvent>, CommandChild)`; `CommandChild::write()` (stdin), `.pid()`, `.kill()`; `CommandEvent::{Stdout,Stderr,Terminated,Error}` variants give bounded, event-driven stdout/stderr plus a terminal event. | Confirms Q3's "retained stdin + direct PID + bounded stdout/stderr + termination event" is a direct 1:1 match to the M3 wire contract's stream ownership rules — no hand-rolled process wrapper needed. |
| tauri-plugin-single-instance source | `~/.cargo/registry/src/.../tauri-plugin-single-instance-2.4.3/src/lib.rs:1-40` | `tauri_plugin_single_instance::init(\|app, args, cwd\| {...})` fires the callback (typically "focus existing window") on a second launch instead of a second process starting. | Satisfies AC3 ("activates the existing app or exits clearly") directly — this is the whole mechanism, not a building block. |
| tauri-build source | `~/.cargo/registry/src/.../tauri-build-2.6.3/src/lib.rs:469-620,595-670` | `try_build()` reads only local files (`tauri.conf.json`, `Cargo.toml`, capability JSON via `acl::build`); the only network-shaped call site (`reqwest`/`ureq`) does not exist in this file; icon (`.ico`) handling is gated `if target_triple.contains("windows")` — macOS `cargo build` needs **no** icon files at build time. | Confirms Q3: a plain `cargo build` (not `cargo tauri build`) on macOS needs no network and no icons; icon/bundle/signing machinery is bundler-only, out of scope for M4's walking skeleton. |
| Cargo registry cache listing | `~/.cargo/registry/cache/*/tauri-*.crate`, `~/.cargo/registry/src/*/tauri-*` | `tauri-2.11.5`, `tauri-build-2.6.3` (and stale `2.5.3`), `tauri-plugin-shell-2.3.5`, `tauri-plugin-single-instance-2.4.3` all present offline. | Confirms the Spike-3 pins are real and cached — no network fetch needed to build. |
| `plans/desktop-distribution-roadmap.md` (this repo) | n/a | e2's outcome text says "starts exactly one **bundled** server" — the one piece of internal text in tension with the "use the M2 relocatable wheel, not PyInstaller" recommendation below. | Flagged explicitly in §8 (Risks) so the critic can weigh it; the milestone's own AC text and M2/M3 precedent outweigh one epic-outcome adjective, in this researcher's read. |

## 6. Recommended approach

For the questions in this researcher's remit specifically:

1. **Port-zero handoff (Q1).** In the Python child-launcher (wherever the
   implementer wires it — see brief-1 for the exact module), create
   `sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)`, `sock.bind(("127.0.0.1", 0))`,
   `sock.listen(...)`, read `port = sock.getsockname()[1]`, emit the `Bound`
   frame with that port, THEN construct `uvicorn.Config(app, host="127.0.0.1", port=port)`
   (port value is cosmetic once sockets are passed) and call
   `await uvicorn.Server(config).serve(sockets=[sock])` (or `.run(sockets=[sock])`
   if run outside an existing event loop). Do not call `sock.close()`
   yourself — `Server.shutdown()` does it. Do not set `set_inheritable`;
   default is already non-inheritable. `--workers`/`reload` are dead code on
   this path (confirmed above) — do not wire them into the child-launcher's
   CLI surface at all, and a test asserting `config.workers == 1` /
   `config.reload is False` on the desktop launch path is good verification
   the implementer should add, not skip.

2. **MCP smoke (Q2).** The smoke sequence is exactly:
   `POST /mcp` `initialize` (headers: `Content-Type: application/json`,
   `Accept: application/json, text/event-stream`) → read `mcp-session-id`
   from the response headers → `POST /mcp` `notifications/initialized`
   (same headers + `mcp-session-id`) → `POST /mcp` `tools/list` or `ping`
   (same headers + `mcp-session-id`, optionally `mcp-protocol-version`).
   This is read-only against `server/tools.py`'s registration and
   `EXPECTED_TOOL_SCHEMA_SHA256`/BP1/BP2 are structurally unreachable from a
   client request — no hash re-pin will ever be needed for this smoke.

3. **Bundled-runtime handoff (Q5 — the scope lever).** Recommend **(c)**: a
   narrow, explicit-path/env resolver (e.g. `ARXMCP_DESKTOP_SERVER_EXE`,
   defaulting to the dev venv's `arxmcp-server` console script or
   `sys.executable -m server.cli`) rather than **(a)** building the
   PyInstaller onedir bundle inside M4. Reasoning:
   - The milestone brief's own wording is "the relocatable server" —
     definite article, matching M2's already-shipped installed-wheel
     deliverable, not a new distributable artifact.
   - Spike-1 (the only feasibility work on PyInstaller onedir) is an
     explicit **release** NO-GO with five open blockers (OpenMP collision,
     no macOS-14 claim, ad-hoc-only signing, unsanitized `direct_url.json`,
     un-productized `latex2mathml` hook) — none of which M4's AC text asks
     the implementer to close.
   - The roadmap's own epic split puts signing/notarization/bundle-trust in
     e4 ("macOS artifact passes platform trust gates," size L, Next-lane,
     not yet materialized), separate from e2 ("Native launch reaches a
     healthy MCP session," M4's parent).
   - AC5 explicitly scopes the 30-cycle stress test to the **fixture
     sidecar** (Rust, model-free) — the milestone's own acceptance criteria
     do not require the 74 s/759 MB PyInstaller build to be exercised
     end-to-end at all; only AC1/AC2 (health/readiness, one MCP smoke)
     need a real Python server child, and the M2 installed wheel already
     satisfies that with no new build step.
   - Cost/benefit: (c) is near-zero incremental LOC beyond what brief-1
     already scopes for the child-launcher (an env/config lookup plus a
     default), keeps the fast (~seconds) test loop the fixture-sidecar
     pattern established, and defers zero AC — every M4 AC is satisfied
     without touching PyInstaller. Option (a) would import spike-1's
     unresolved release blockers into an M-complexity milestone and blow
     the diff-size gate; option (b) is effectively identical to (c) with a
     fixed path instead of a configurable one — (c) is strictly better
     because it is also what any future e4 bundling milestone will need to
     plug into (swap the resolved path from "dev venv" to "frozen
     executable" with no supervisor-side code change).
   - **Reject (a) outright for M4.** If the critique phase disagrees,
     require it to name which specific M4 AC needs PyInstaller — none do.

4. **Window creation and CSP (Q4).** Use `WebviewWindowBuilder::new(app, "main", WebviewUrl::External(bound_url))`
   inside `.setup()`, called only after the sidecar's `Bound` frame is
   received (matches the "port is unknown until the child emits `bound`"
   constraint). No capability/permission grants are needed for the window
   content itself (no `invoke()` calls from the `/ui/` htmx pages); no
   `dangerous_remote_domain_ipc_access` entry is needed for the same reason.
   `OriginValidationMiddleware`'s loopback allow-list already accepts
   same-origin requests from `http://127.0.0.1:<port>` at any port — no
   `server/middleware.py` change is required for the desktop window to
   function.

## 7. Alternatives considered

- **uvicorn `--fd`/`config.fd`** — rejected for Q1: designed for an
  externally-passed file descriptor (e.g. systemd socket activation), uses
  `socket.fromfd(..., socket.AF_UNIX, ...)` internally (line 150 of
  `server.py`) — wrong address family for a TCP loopback listener; `sockets=`
  is the correct, already-AF_INET-safe API.
- **A raw `httpx`/`curl` one-shot GET to `/healthz` as the "MCP smoke"** —
  rejected: does not exercise `/mcp` at all, does not prove the Streamable
  HTTP session handshake works, and the milestone brief explicitly asks for
  "the normal MCP response... without schema changes," which requires the
  real JSON-RPC exchange described in §6.2 above.
- **`cargo tauri build`/full bundler in M4** — rejected: pulls in the
  Node-free-but-CLI-dependent Tauri CLI, icon/bundle config, and (on macOS)
  moves toward `.app` packaging that this milestone's AC text never asks
  for; `cargo build --bin <supervisor>` is sufficient for a development
  desktop shell that exercises the lifecycle.
- **Full PyInstaller onedir bundle inside M4 (option a in Q5)** — rejected;
  see §6.3 reasoning in full.

## 8. Risks and unknowns

- **Textual tension:** `desktop-distribution-e2`'s outcome line says "starts
  exactly one **bundled** server," which could be read as requiring
  PyInstaller. This researcher reads "bundled" loosely (any packaged/child
  server, matching M2's relocatable wheel) given the AC text, the roadmap's
  own e4 split, and spike-1's explicit deferral language — but the
  implementer/critic should treat this as a flagged, not fully resolved,
  interpretation question, not silently pick a side.
- **Socket lifetime across the `asyncio.create_task`/thread boundary**: if
  the child-launcher spawns uvicorn inside a background thread with its own
  event loop (rather than as a task on the process's single loop), the
  pre-bound socket must be created before the thread starts and handed in;
  getting this wrong reintroduces a bind-time TOCTOU race the M3 contract's
  "child retains the port-zero listener" language is designed to prevent.
- **`Accept` header defaults**: if the implementer's HTTP client (e.g. a
  bare `httpx.AsyncClient`) doesn't default to sending
  `Accept: application/json, text/event-stream`, the smoke request will get
  a 406 that looks like an MCP-layer bug but is actually a client header
  omission — worth a code comment at the smoke call site.
- **Tauri window creation timing**: `WebviewWindowBuilder::build()` must be
  deferred until after the `Bound` frame arrives on the sidecar's stdout —
  if the implementer follows a typical Tauri tutorial pattern (window
  created eagerly with a static `tauri.conf.json` URL), that pattern does
  not fit this milestone's dynamic-port requirement and must be explicitly
  overridden.
- **macOS Gatekeeper on an unsigned dev binary**: even a plain `cargo build`
  binary that spawns a child process and opens a network listener may
  trigger a first-run Gatekeeper/firewall prompt on the development
  machine; this is a UX nuisance for local dev/testing, not an AC blocker,
  and should not be treated as a signing requirement creeping into M4.

## 9. External-write actions required

external_writes_required:
- `git push origin main` — per `CLAUDE.md` §4.4, gated per-event; no other
  branch/MR path exists in this repo (single-user, single-workstation,
  trunk-only).
- Closing GitHub issue `#397` (`chris-dare-dev/arXMCP`) rides a `Fixes #397`
  trailer on the same user-gated `git push origin main` — this is NOT an
  independent write. Verified: `.claude/scripts/milestone-pipeline-issue-note.py`
  (the automated ANNOTATE-class progress-comment script) scans only
  `plans/*/roadmap.yaml`; there is no `plans/desktop-distribution/roadmap.yaml`
  (desktop-distribution lives as legacy prose at
  `plans/desktop-distribution-roadmap.md`), so the script prints
  `warning: desktop-distribution-m4 not found in any plans/*/roadmap.yaml`
  and exits 0 — a genuine no-op, not a silent success. If the implementer
  wants a progress comment posted mid-pipeline, it must be done manually
  (e.g. `gh issue comment 397 ...`), which is itself a separate external
  write requiring its own explicit authorization per `github-conventions.md`'s
  ANNOTATE class.
- No AWS/cloud, ArgoCD, Confluence, or Jira writes apply — this repo has none
  of that infrastructure; the only external system in scope is GitHub via
  `git push` (+ optional manual `gh issue`/`gh pr` calls, none required by
  the AC text).

No external write was performed by this research pass; all evidence above
was gathered read-only.

## 10. Open questions for the user

- Does "the relocatable server" in the M4 brief mean M2's installed wheel
  (this brief's read), or does the e2 epic's "bundled server" wording mean
  Chris wants PyInstaller onedir wired into M4 itself, accepting spike-1's
  open release blockers as in-scope debt? This materially changes the
  diff-size estimate (see below) and should be confirmed before
  implementation starts if the orchestrator/critic can't resolve it from
  the AC text alone.

## Estimated diff size + file count (for the Phase-2 scope gate)

For the **recommended option** (Q5 option (c): M2 installed wheel/venv
`arxmcp-server` as the child, resolved via explicit path/env, no PyInstaller
build in M4):

- New Rust supervisor crate (`apps/desktop/crates/supervisor/` or similar):
  `Cargo.toml`, `src/main.rs` (window creation, sidecar spawn/lifecycle,
  single-instance wiring, starting/ready/degraded/failed state rendering),
  `tauri.conf.json`, a minimal `capabilities/default.json` — roughly
  5-7 new files, ~450-700 LOC (this overlaps with, and should be
  reconciled against, brief-1's ~1200-1900 LOC estimate which additionally
  scopes the Python child-launcher; this brief's number is the Rust/Tauri
  half plus the child-resolver env lookup only).
- Python child-launcher additions (server-side port-zero wiring, env-based
  executable resolution): 1-2 new/modified files
  (e.g. `server/desktop_launch.py` or extending `server/cli.py`), ~150-250
  LOC — see brief-1 for the authoritative estimate on this half.
- Tests: lifecycle stress harness reusing the existing
  `desktop-conformance` fixture-sidecar pattern for the 30-cycle AC, plus a
  new smoke test exercising the real `arxmcp-server` child for AC1/AC2 —
  2-4 new test files, ~300-500 LOC.
- **This option avoids** any PyInstaller `.spec` file, any new build-time
  dependency, and any change to `pyproject.toml` packaging — keeping the
  diff inside a single M-complexity milestone's plausible envelope
  (roughly 900-1,400 LOC total across ~12-16 files, before whatever
  brief-1's Python-side count adds).
- **If Q5 option (a) is chosen instead** (PyInstaller onedir built inside
  M4): add a `.spec` file, `pyproject.toml`/`Makefile` build-step changes,
  and re-opening all five spike-1 release blockers as in-scope work —
  this would push the milestone well past a single M-complexity slice and
  is the strongest argument for staying on option (c).
