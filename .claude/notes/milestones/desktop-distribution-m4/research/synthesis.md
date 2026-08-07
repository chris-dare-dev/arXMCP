# Research synthesis — desktop-distribution-m4

Mode: `--deep` (3 researchers). Briefs: `research/brief-1.md` (explore),
`research/brief-2.md` (general/external), `research/brief-3.md` (adversarial).
Brief source: `legacy-prose plans/desktop-distribution-roadmap.md`.

## 1. Cross-agent agreement (highest-confidence findings)

These are load-bearing and were reached independently by two or more agents.

- **Pre-bound socket is the port-zero mechanism, and `Config` must not
  change.** brief-1 §6A/§7 and brief-3 Invariant #1 independently reject
  relaxing `server/config.py:825-838` `validate_port_range` (which rejects
  `0` today). Widening it would let Docker (`docker/Dockerfile.server`
  fixed `EXPOSE 7733` + healthcheck), systemd, `make up`, and any CLI
  operator request an unpredictable ephemeral bind where they currently get
  a clear fail-fast error. Correct path: bind `("127.0.0.1", 0)` OUTSIDE
  `Config`, retain the live socket, hand it to uvicorn. brief-3 additionally
  notes that a bind→close→rebind variant introduces a TOCTOU window —
  the fd itself must be handed over, not just the learned port number.
- **uvicorn supports it.** uvicorn 0.46.0 (pinned, installed) accepts
  `sockets=[sock]` (`Server.run(sockets=...)` wraps `Server.serve(sockets=...)`;
  both agents' phrasings describe the same supported API).
- **The child server is the M2 installed wheel, not a PyInstaller bundle.**
  brief-2 §Q5 recommends resolving the child by explicit path/env. Pulling
  PyInstaller `onedir` into M4 re-opens all five Spike-1 release blockers.
- **`external_writes_required` is exactly one item.** `git push origin main`,
  with `Fixes #397` riding it. Both the orchestrator and brief-2
  independently verified that `milestone-pipeline-issue-note.py` no-ops for
  this id because `plans/desktop-distribution/roadmap.yaml` does not exist.

## 2. Stream-ownership finding (handoff gap #3 — RESOLVED)

`server/cli.py:214` passes `log_config=None`, so uvicorn's loggers propagate
to the root logger's stderr handler. **Child stdout is already clean**, so the
single `bound` control frame needs no dedicated inherited file descriptor and
no new stream plumbing. The implementation must still (a) emit exactly one
frame then stop writing to stdout for the process lifetime, and (b) keep the
`RedactionFilter` (`server/observability/log_filter.py:62`) on the stderr path.

## 3. Scope — the gate WILL fire

| Agent | Estimate | Scope covered |
|---|---:|---|
| brief-1 (explore) | 1,200–1,900 LOC | Python child + Rust supervisor + tests |
| brief-2 (general) | 900–1,400 LOC, 12–16 files | Rust/Tauri half + child resolver; defers Python half to brief-1 |
| brief-3 (adversarial) | **2,100–3,750 LOC** | Itemized: Tauri app 400–700, supervisor 700–1,100, Python entry 250–450, MCP smoke 80–150, Rust redaction writer 80–150, tests 600–1,200 |

All three exceed the pipeline's 800-LOC ABORT. brief-3 grounds its number in
delivered history: m1 = 373 LOC, m2 = 901, m3 = 2,702 against its own
1,100–1,700 estimate (a 59–145% overrun). Three-for-three prior "M" milestones
in this family required `--allow-large-diff`.

**brief-3's split proposal (its recommended default):**

- **m4a** — real single-cycle lifecycle: Python desktop entry point, minimal
  supervisor crate, Tauri window on `/ui/`, one real MCP smoke, AC1/AC2/AC3,
  and AC4's *normal*-shutdown path only.
- **m4b** — fault matrix (startup timeout, sidecar crash, supervisor crash),
  30-cycle stress, loopback socket-level regression; fixture-based plus at
  least one real-server fault case to keep AC4 honest.

## 4. Falsifiability — where a walking skeleton can lie

brief-3 §2 gives one row per AC. The four that most change the test design:

- **AC1** can pass by wiring the supervisor to the already-built
  `fixture-sidecar` and never booting the real server. Catch: assert the
  child's argv/module target is the production entry point, and that
  `/readyz` only greens after the real eager BGE-M3 load.
- **AC2** can pass by hitting `/healthz` and calling it "the MCP smoke".
  Catch: require a real `initialize` + `tools/list`, and hash the **live
  response bytes** against `EXPECTED_TOOL_SCHEMA_SHA256`
  (`tests/test_server_tool_schema.py:94`). A smoke that never compares that
  constant does not prove "without schema changes".
- **AC3** can pass by launching sequentially with a sleep — proving nothing
  about the race Spike-3 measured. Catch: reproduce the external-barrier
  simultaneous release and assert exactly one spawn event.
- **AC4** can pass with a `ps`/`lsof` audit that treats an EMPTY result as
  clean. Spike-3's own methodology forbids this: "Failed or partial ps/lsof
  probes are evidence failures, never clean absence". Catch: assert the probe
  itself succeeded, then recursively scan every persisted diagnostic for the
  capability bytes.
- **AC5's letter is fixture-scoped** ("30 fixture-sidecar cycles"), so the
  stress loop legitimately stays on the fast fixture. Catch: require 30
  DISTINCT PIDs, not one reused process.

## 5. Open decision the implementer must NOT make silently

`X-ArXMCP-Startup-Token` on `/readyz` is documented in `apps/desktop/README.md`
but enforced nowhere in production. No AC strictly requires it. The decision —
add a desktop-path-scoped pure-ASGI middleware, or defer with a written note —
must be explicit. If added it must be pure-ASGI: brief-3 Invariant #3 flags
this as exactly the task that tempts a `BaseHTTPMiddleware` shortcut, which is
project-banned (E06_S01 F1).

## 6. Invariant risk register (brief-3 §5, condensed)

1. Port range — do not widen `validate_port_range`. (See §1.)
2. Loopback bind — second-order: a widened port validator plus an existing
   `ARXMCP_UNSAFE_NETWORK_BIND=1` yields an unpredictable externally-reachable port.
3. `BaseHTTPMiddleware` ban — see §5.
4. `EXPECTED_TOOL_SCHEMA_SHA256` / BP1 / BP2 — see AC2 above.
5. Unknown-`ARXMCP_*` FATAL (`server/main.py:412-450`) — thread launch data over
   the NDJSON frames, not a new env var; never weaken the scan.
6. `ApplicationPaths` sole ownership — the Rust supervisor must RECEIVE the
   resolved root, never reimplement `_platform_data_root` via a Rust `dirs` crate.
7. Capability leakage — M4 adds genuinely new surfaces absent in M3's headless
   fixture: webview URL/query params, Tauri IPC events, OS crash dumps, and a
   Rust-side diagnostics writer with no `RedactionFilter` equivalent.

## 7. Cross-platform honesty

The wire protocol is platform-neutral, but all implemented process control
(`setpgid`, TERM/KILL) is Unix-only and `grep cfg(windows)` returns 0 hits in
`apps/desktop/crates`. M4 need not ship Windows, but if signal names and
`setpgid` are baked into the lifecycle state machine rather than kept behind
the adapter seam `apps/desktop/README.md` already promises, the "not
macOS-only" claim becomes false the moment M4 lands.

## 8. Reuse inventory — do NOT rewrite

`server/application_paths.py` (`ApplicationPaths`), `server/desktop_contract.py`,
`apps/desktop/crates/desktop-contract`, `apps/desktop/crates/fixture-sidecar`,
the existing `/ui/` console (host it; build no new UI), the `/mcp` mount, and
the `desktop-conformance` gate philosophy. Spike-3 code is design precedent
only — it targets a pre-M3 wire format and is explicitly not the production home.

## 9. Open questions (max 5)

1. **Split m4a/m4b, or run whole under `--allow-large-diff`?** — OWNER DECISION,
   blocking Phase 2.
2. Token-gate `/readyz` on the desktop path, or defer with a written note? (§5)
3. Does the 30-cycle stress live in `make test` or only `make desktop-conformance`?
   Baseline suite is already 322 s.
4. Is a third reviewer warranted for the Tauri/webview attack surface (window
   content exposure, IPC command surface)? brief-3 §4 argues the named
   `mcp-protocol-reviewer` + `security-reviewer` do not cover it.
5. "Relocatable" (M4 brief) vs "bundled" (epic e2 outcome) server — brief-2
   flags this as a real interpretation tension; option (c) reads it as M2's
   installed wheel.

## external_writes_required

- `git push origin main` (per-event authorization; `CLAUDE.md` §4.4). Closing
  issue #397 rides `Fixes #397` on that same push and is NOT a separate write.

## Estimated diff size + file count (Phase-2 gate input)

Whole M4: **2,100–3,750 LOC across ~20–30 files** — exceeds the 800-LOC ABORT.
m4a alone: ~800–1,400 LOC. m4b alone: ~700–1,300 LOC.
