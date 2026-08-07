# Session handoff — 2026-08-07 — desktop-distribution-m4

This snapshot is for an **Opus 5 agent** taking the next desktop milestone. It
supersedes the previous ingest-focused handoff; that history remains available
in git.

## Mission

Run `desktop-distribution-m4` through the repository's full
`milestone-pipeline`: **Research → Implement → Critique → Rectify**.

M4 is the first production walking skeleton. It must connect one native desktop
supervisor to the relocatable Python server and the existing `/ui/` console,
prove one real MCP exchange, expose honest lifecycle states, and leave no child
or listener behind across normal and faulted exits.

- GitHub issue: [#397](https://github.com/chris-dare-dev/arXMCP/issues/397)
- Parent outcome epic: [#389](https://github.com/chris-dare-dev/arXMCP/issues/389)
- Local ticket: `plans/desktop-distribution-tickets/desktop-distribution-m4.md`
- Roadmap source: `plans/desktop-distribution-roadmap.md`, M4 section
- Pipeline command: `milestone-pipeline desktop-distribution-m4`

Do not close #397 before the implementation is complete. Prefer `Fixes #397`
in the final rectification commit so the user-gated push to `main` closes it.

## Repository state at handoff

- Branch: `main`
- Local and `origin/main` HEAD: `3ed0fa07f41cf92cd78edd6bee970476b895c5d7`
- HEAD subject: `chore(notes): finalize m3 state`
- M2 dependency [#395](https://github.com/chris-dare-dev/arXMCP/issues/395):
  closed/completed
- M3 dependency [#396](https://github.com/chris-dare-dev/arXMCP/issues/396):
  closed/completed
- M4 [#397](https://github.com/chris-dare-dev/arXMCP/issues/397): open,
  agent-ready, Must/Now, Desktop 2 release gate
- M3 final gate: Ruff clean; 5,060 passed, 43 skipped, 1 xfailed
- M3 desktop gate: 8 Rust tests and 27 Python tests, zero skips

The worktree was clean before this handoff file was replaced. This handoff is
the only intended local modification. Verify with `git status --short` before
starting the pipeline and preserve any user changes that appear later.

## M4 acceptance contract

1. With no existing instance, launch exactly one child server, reach
   health/readiness, and render the existing console in the desktop window.
2. Send one real MCP smoke request to the announced local endpoint and receive
   the normal response without changing the MCP tool schema.
3. A second launch activates the existing application or exits clearly without
   starting another server.
4. Normal shutdown, startup timeout, child crash, and supervisor crash use
   bounded cleanup, leave no process/listener, and emit only redacted
   diagnostics.
5. Run 30 fixture-sidecar lifecycle cycles with zero orphans and zero residual
   listeners.
6. Pass the desktop lifecycle/MCP smoke gates on a clean supported Mac and pass
   `make test`.

Treat the above as the minimum demonstrable slice. Do not absorb signing,
notarization, auto-update, first-run corpus acquisition, Windows/Linux release
packaging, or polished macOS distribution; those are later milestones.

## Read these first

Read completely, in this order:

1. `AGENTS.md`
2. `.claude/commands/milestone-pipeline.md`
3. `plans/desktop-distribution-tickets/desktop-distribution-m4.md`
4. `plans/desktop-distribution-roadmap.md`
5. `apps/desktop/README.md`
6. `.claude/notes/spikes/desktop-distribution-spike-1.md`
7. `.claude/notes/spikes/desktop-distribution-spike-3.md`
8. `.claude/notes/milestones/desktop-distribution-m2/rectify/summary.md`
9. `.claude/notes/milestones/desktop-distribution-m3/rectify/summary.md`
10. `server/application_paths.py`
11. `server/desktop_contract.py`
12. `apps/desktop/crates/desktop-contract/src/lib.rs`
13. `apps/desktop/crates/fixture-sidecar/src/main.rs`
14. `server/cli.py`, `server/config.py`, `server/main.py`, and
    `server/health.py`

The spike code under `tools/desktop_lifecycle_spike/` is disposable evidence,
not the production home. Reuse its measured design and project-owned ideas,
but production code belongs under `apps/desktop/` and the appropriate
`server/` modules.

## What M1–M3 already guarantee

### Relocatable application data

`server.application_paths.ApplicationPaths` is the sole owner of the mutable
layout. In installed mode, all first-party writes derive from one canonical
`ARXMCP_DATA_DIR`; M2's full wheel gate proved installed server, UI, notebook,
cache, logs, corpus markers, settings, and ingest defaults remain confined.

Do not reconstruct `corpus/`, `index/`, `cache/`, or notebook paths in Rust.
The supervisor passes one root; Python owns its internal layout.

### Versioned control protocol

M3 shipped a shared Rust/Python contract with these load-bearing rules:

- UTF-8 canonical NDJSON, one LF, maximum 4,096 bytes per frame.
- `launch → bound → shutdown` lifecycle with incompatible-major rejection.
- `launch` and `shutdown` carry a 256-bit startup capability; `bound` never
  does.
- The capability never enters argv, environment, URLs, representations,
  exception graphs, persisted manifests, or operational logs.
- Paths are platform-neutral wire strings using `/`, accepted as POSIX
  absolute or uppercase drive-qualified Windows absolute paths.
- Only top-level extension keys require namespaces; nested JSON keys remain
  forward-compatible.
- The child verifies its own executable SHA-256 before binding and emits the
  independently computed digest.
- Endpoint authority is literal `127.0.0.1` with a retained, kernel-selected
  nonzero port; URLs are derived from that one authority.
- Shutdown reserves at least 35 seconds for the production server drain and
  retains stdin EOF as the parent-lifetime lease.

Do not introduce a second protocol for macOS. Windows and Linux must be able to
reuse the same contract later.

### Measured lifecycle primitives

Spike 3 produced a GO on macOS arm64:

- Tauri 2 can retain child stdin, direct PID, bounded stdout/stderr, and the
  termination event.
- A native advisory `supervisor.lock` must arbitrate before spawn. The Tauri
  single-instance callback did **not** close the simultaneous-start race; use
  it for steady-state activation UX, not as the sole ownership primitive.
- Direct-child/process-group TERM → bounded wait → KILL → reap worked.
- Stdin EOF stopped the cooperating child after supervisor death.
- Eleven fault scenarios plus 30 clean cycles produced zero orphan groups,
  zero residual listeners, and zero secret failures.

Keep the spike's explicit non-claims: a parent that is already dead cannot
kill a wedged child, and a descendant that deliberately creates a new session
escapes ordinary process-group cleanup. Do not launder those limits into a
universal-cleanup claim.

### Runtime packaging decision

Spike 1 selected pinned PyInstaller `onedir` provisionally. It relocated and
ran without ambient Python, but it is not release-ready: real-model/OpenMP,
support-floor, signing, and notarization gates remain. The named fallback is
python-build-standalone plus the locked installed wheel, not an unbounded hook
chase. M4 needs a walking skeleton, not a signed beta.

## Current production gaps — do not assume these are solved

These are the first research targets for M4:

1. **Port-zero production startup is absent.** `Config.validate_port_range`
   rejects `0`, and `server.cli.main` calls `uvicorn.run(..., port=...)`. The
   existing CLI neither retains a pre-bound socket nor learns/publishes the
   kernel-selected port. Do not merely relax the validator: the child must own
   the exact listener it announces.
2. **The real server is not a control-protocol child.** No production entry
   point reads the M3 `launch` frame before side effects, emits `bound`, owns a
   retained control channel, accepts authenticated `shutdown`, or treats stdin
   EOF as its desktop lease.
3. **Control and logging streams need an explicit decision.** M3 reserves
   child stdout for the control frame and stderr for redacted diagnostics.
   Confirm the current JSON logging destination and prevent any server log,
   warning, traceback, or library output from corrupting the control stream.
   A dedicated inherited descriptor is acceptable only if the shared contract
   and packaging story are updated deliberately in both languages.
4. **Desktop readiness authentication is absent.** `/readyz` currently accepts
   no startup-capability header. Add a desktop-only enforcement path that does
   not alter ordinary source/container behavior and never makes the token an
   environment/config value. `/healthz` may remain unauthenticated liveness.
5. **No production desktop supervisor/window crate exists.** The workspace
   currently contains only `desktop-contract` and `fixture-sidecar`. M4 must
   productionize the smallest Tauri supervisor/window slice under
   `apps/desktop/` with exact dependency pins and no Node/npm build chain.
6. **The dynamic UI window is unwired.** Load the existing server-rendered
   `bound.ui_url`; do not clone the console into a Rust or SPA frontend. Define
   starting, ready, degraded, and failed states honestly and honor the current
   loopback Origin/Host/CSP defenses.
7. **The real MCP smoke is unwired.** Exercise Streamable HTTP against the
   announced `/mcp` authority with a real initialize/session exchange and a
   stable method such as `tools/list` or ping. The normal MCP response must be
   observed; do not add or rename tools and do not re-pin schema/BP hashes
   unless an intentional schema change is separately approved.
8. **Installed-bundle handoff is not yet one command.** Research whether M4
   launches the prepared PyInstaller `onedir` artifact, an installed-wheel
   fixture from M2, or a narrowly scoped development adapter. The acceptance
   language says relocatable/bundled server and clean supported Mac, so a
   source-checkout-only demo is insufficient.

## Recommended architecture to test in Phase 1

This is a hypothesis, not permission to skip pipeline research:

```text
Tauri supervisor
  ├─ acquire native lock under ApplicationPaths root
  ├─ generate startup capability in memory
  ├─ spawn bundled desktop-child executable with cleared environment
  ├─ send canonical launch frame over retained private control input
  ├─ validate token-free bound frame + executable identity
  ├─ poll /healthz, then capability-authenticated /readyz
  ├─ perform MCP initialize + smoke on bound.mcp_url
  ├─ point one native window at bound.ui_url
  └─ shutdown frame → grace → TERM → KILL → reap/audit

Python desktop-child entry point
  ├─ read/validate launch before binding or mutable side effects
  ├─ bind and retain socket at 127.0.0.1:0
  ├─ construct Config/create_app with the supplied application root
  ├─ serve uvicorn using the retained socket
  ├─ emit one canonical bound frame on the private control output
  ├─ enforce startup capability on desktop /readyz only
  └─ react to authenticated shutdown or stdin EOF with bounded app drain
```

Prefer a dedicated desktop-child entry point over weakening the normal
`arxmcp-server` CLI contract. Ordinary source, wheel, Docker/Compose, `make up`,
explicit bind ports, and existing environment validation must remain unchanged.

## Security and correctness invariants

- Literal loopback only. Never bind `0.0.0.0`, wildcard IPv6, hostname-derived
  addresses, or a close/rebind-selected port.
- Keep the startup capability off argv/env/URLs/logs/errors/manifests and out
  of Tauri events or window state exposed to web content.
- Validate the child executable's independently computed identity before
  trusting its endpoint.
- Acquire the native supervisor lock before any child setup; a second launch
  must not create a transient second listener.
- Keep control frames bounded and duplicate-key-free; reject malformed output
  before opening the UI.
- Treat malformed bound/readiness/MCP responses as terminal startup failures,
  not retryable transport noise.
- Preserve the 30-second server resource drain and M3's ≥35-second supervisor
  grace reservation before force escalation.
- Persist only redacted diagnostics beneath `ApplicationPaths.logs`.
- Preserve pure-ASGI middleware; `BaseHTTPMiddleware` remains banned.
- Preserve MCP `tools/list` byte stability and BP1/BP2 hashes.
- No runtime Anthropic SDK and no copied code from `arxiv-mcp` repositories.
- No new SPA or Node/npm build chain. The desktop window hosts `/ui/`.

## Minimum verification matrix

Phase 1 should refine exact commands, but M4 should end with evidence at least
this strong:

- Rust format, locked tests, and strict Clippy for the entire desktop workspace.
- `make desktop-conformance PYTHON=.venv/bin/python` remains green with zero
  skips.
- Focused production desktop-child tests for frame order, retained port zero,
  authenticated readiness, log/control isolation, executable mismatch, EOF,
  graceful shutdown, and TERM/KILL fallback.
- A real Tauri walking-skeleton smoke on the supported Mac proving the window
  reaches the existing `/ui/` URL.
- A real MCP initialize/session + smoke request over the announced endpoint,
  with `tools/list` bytes/hash unchanged.
- Simultaneous first-launch arbitration and steady-state second-launch
  behavior.
- Startup timeout, malformed bound, never-ready, child crash, supervisor crash,
  and ignored-shutdown scenarios with independent PID/listener audits.
- Thirty fresh fixture-sidecar cycles with zero orphans/listeners/secrets.
- Relocation from a read-only application location with every write beneath a
  temporary application-data root.
- `make wheel-check`, the applicable bundled-runtime gate, and `make test`.

Do not substitute unit mocks for the live fault matrix. Keep committed evidence
normalized and secret-free; do not commit binaries, app bundles, model caches,
raw process streams, credentials, Cargo targets, or runtime data.

## Pipeline and git discipline

- Run the milestone pipeline; do not implement M4 ad hoc.
- All work lands directly on `main`; no feature branch or PR.
- The pipeline lock must be acquired/released through its scripts, never by
  deleting `.lock`.
- Standard implementation is likely to exceed the pipeline's review-size
  threshold. Stop for the user's explicit `--allow-large-diff` approval if the
  scope gate fires; do not infer it from the approval given for M3.
- Use signed conventional commits, mandatory co-author trailer, and hooks.
- Run `make test PYTHON=.venv/bin/python` before every commit.
- Never push without a fresh per-event user authorization.
- External writes should be declared during research. Expected minimum:
  `git push origin main`; do not mutate GitHub project metadata implicitly.
- Never auto-start the next milestone after M4 completes.

## Suggested first commands

```bash
git status --short
git log -1 --oneline --decorate
gh issue view 397 --repo chris-dare-dev/arXMCP
bash .claude/scripts/milestone-pipeline-status.sh desktop-distribution-m4
milestone-pipeline desktop-distribution-m4
```

If this environment invokes slash commands rather than shell executables, use
`/milestone-pipeline desktop-distribution-m4` through the agent interface.

## Copy/paste kickoff for Opus 5

> You are taking over arXMCP at `main` after desktop-distribution-m3. Read
> `AGENTS.md` and `.claude/notes/HANDOFF.md` completely, verify that local and
> `origin/main` begin at `3ed0fa0`, and inspect issue #397. Then run
> `desktop-distribution-m4` end-to-end through the milestone pipeline. Treat
> M3's contract, M2's relocatable application root, Spike 3's native-lock and
> process-group findings, loopback-only binding, secret isolation, no-Node UI,
> and MCP schema byte stability as load-bearing. Research the real port-zero
> uvicorn socket handoff, control/log stream separation, desktop-only readiness
> authentication, bundled-runtime entry point, Tauri window loading, MCP
> handshake, single-instance arbitration, and fault cleanup before coding.
> Keep ordinary server/container behavior unchanged, add live regression
> evidence, run all required gates, and stop for fresh authorization before
> every push or other external write.
