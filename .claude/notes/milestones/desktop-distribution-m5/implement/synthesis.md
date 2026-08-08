# Implement synthesis — desktop-distribution-m5

Base `1a542ee` → commits `b9054f0` (server), `a9b7202` (desktop), `ffecb7e`
(tests), plus this checkpoint commit. `--allow-large-diff` was owner-authorized
for m5 before Phase 2; honest non-generated diff ≈ 1,290 LOC of hand-written
code (330 py entry point + 964 rs/toml/json crate + 617 test/gate lines minus
boilerplate) + a 5,054-line regenerated `Cargo.lock`.

## Built

- **AC1 — one real child reaches health/readiness; console renders; production
  entry point.** `server/desktop_child.py:1-330` (`python -m
  server.desktop_child`): bounded `read_frame` (`:66`), identity validation
  against a self-measured sha256 of the module source (`:92`,
  `_validate_launch:146`), pre-bound `127.0.0.1:0` socket held WITHOUT
  `listen()` (`main:298`), hand-driven
  `uvicorn.Server.startup()/main_loop()/shutdown()` so `bound` is emitted only
  after listen + eager-warm-up both hold (`_serve:224-268`). fd 1 is re-pointed
  at stderr after duping the control pipe (`main:279-283`), and the duped fd is
  closed after the single `bound` write — a second stdout write is structurally
  impossible. Test: `tests/test_desktop_child.py::test_ac1_real_child_ready_and_console`
  (argv `[sys.executable, "-m", "server.desktop_child"]` asserted; warm map
  asserted `{embedder,lancedb,reranker} == all-true` (child env carries
  `ARXMCP_ENABLE_RERANK=1` so all three axes are real); `/ui/` body carries the
  live console marker). Verified live: bound after ~5-8 s warm-up on this box.
- **AC2 — real MCP smoke, LIVE bytes hash.** Same shared fixture;
  `test_ac2_mcp_smoke_live_schema_hash` does a real `initialize` →
  `notifications/initialized` → `tools/list` over the announced endpoint and
  hashes the live response's tools with
  `tests/test_server_tool_schema.compute_tool_schema_hash` against
  `EXPECTED_TOOL_SCHEMA_SHA256` — equal, so no tool/schema drift; BP1/BP2 pins
  untouched (no `server/tools.py` change in the diff).
- **AC3 — zero-delay second launch, exactly one spawn.**
  `apps/desktop/crates/supervisor/` (workspace member added). fs2 lock under
  the received data root acquired BEFORE any Tauri machinery
  (`src/main.rs:acquire_supervisor_lock`); barrier env var reproduces Spike-3's
  simultaneous release. `test_ac3_zero_delay_race_single_spawn` releases two
  supervisors from a shared barrier and asserts exactly one `child-spawn`
  event, one `lock-contended`, a clean winner cycle
  (`mcp-smoke-ok`/`window-ready`/`shutdown-clean:0`), both exits 0, and no
  unexpected 64-hex string in any supervisor/child-written artifact. AC3 runs
  the REAL child (not the fixture sidecar the brief permitted), so it doubles
  as the supervisor's end-to-end smoke for one warm-up.
- **AC4 — normal shutdown, nothing left, probes assert their own success.**
  Child: stdin-EOF lease + authenticated `shutdown` in `_watch_stdin:191`;
  invalid frames ignored forever. Supervisor: shutdown frame + stdin drop →
  bounded grace wait → cooperative terminate via the `process_control` seam →
  `Child::kill` → reap (`lifecycle.rs:shutdown_child`).
  `test_ac4_normal_shutdown_leaves_nothing` proves exit 0, uses a connect
  probe first shown SUCCEEDING against the live server and then required to
  raise `ConnectionRefusedError`, asserts an empty stdout remainder, and
  sweeps argv/env/URLs/every on-disk artifact for the capability bytes.
- **AC5 — `validate_port_range` untouched.** `server/config.py` not in the
  diff. `test_ac5_port_zero_still_rejected_by_config` (0/80/65536 all raise)
  plus an AST-level identifier scan proving `server/desktop_child.py` never
  references `bind_port` (docstrings excluded so prose can't mask or fake it).
- **AC6 — `X-ArXMCP-Startup-Token` on `/readyz`, pure-ASGI, desktop-scoped.**
  `ReadyzStartupTokenMiddleware` (`server/desktop_child.py:104`), a plain
  object wrapper following the `OriginValidationMiddleware` skeleton,
  constructed ONLY in the desktop-child boot path; `create_app` untouched, so
  the 14 existing `/readyz` test files are structurally unreachable from it.
  Constant-time compare via `tokens_equal`. `TestReadyzStartupTokenMiddleware`
  covers 401 (absent/wrong/malformed), pass-through, path scoping, lifespan
  scopes, and the structural guards (`ReadyzStartupTokenMiddleware` absent
  from `server/main.py`; no `BaseHTTPMiddleware`/`add_middleware` identifier
  in the child module).
- **AC7 — gates.** See Check gate results; `make desktop-conformance` now also
  builds the supervisor and runs `tests/test_desktop_child.py` with ZERO skips
  via the `-m "requires_desktop_stack or not requires_desktop_stack"`
  expression.

## Deviations from the brief (§3 followed otherwise)

1. **tauri-codegen requires a window icon even with `bundle.active:false`** —
   the brief's "no icon needed on macOS" claim is wrong for
   `generate_context!`; a committed 70-byte 1×1 PNG (same bytes the spike's
   build.rs generated) replaces the spike's build-time icon synthesis.
2. **`webview-data-url` tauri feature enabled** — the two-state render
   (starting page → console) uses an inline `data:` URL; without the feature
   the app aborts with a non-unwinding panic (found live, first race run).
3. **Lock loser never registers the single-instance plugin** (spike registered
   it on every launch). The plugin's macOS listener socket is machine-global
   (`/tmp/com_arxmcp_desktop_si.sock`) and its notify path `exit(0)`s
   whichever process connects second — a loser-registered listener could kill
   the fs2 WINNER mid-boot. The loser instead plays only the client half of
   the plugin wire protocol (activation notify) and exits 0. Consequence:
   activation still works, arbitration is deterministic. Known limitation:
   the socket is per-identifier machine-global, so a concurrently running real
   desktop app would win the plugin handshake against a conformance run.
4. **Supervisor child-spawn uses `std::process::Command`** (retained pipes +
   ARXMCP_* env scrubbing + direct reaping), not tauri-plugin-shell's event
   stream; the shell plugin is still registered per the spike shape.
5. **Supervisor configuration is one launch-plan JSON file**
   (`ARXMCP_DESKTOP_LAUNCH_PLAN`) carrying child argv, component/version,
   identity file, resolved `data_root` (RECEIVED, per the ApplicationPaths
   invariant — no Rust `dirs` crate anywhere) and smoke flag.
6. **`DESKTOP_SUPERVISOR_BIN` is deliberately not `ARXMCP_`-prefixed** — the
   test file imports `server.main` (module-level app construction), whose
   unknown-`ARXMCP_*` scan FATALs on undeclared vars; the scan itself is
   untouched (invariant #5).
7. **Child stdout fd redirect** (dup control fd, `dup2` stderr onto fd 1) —
   not in the brief; guarantees the control stream stays single-frame even if
   a model loader prints to stdout during warm-up.
8. **`ruff format` not applied** — the repo's gate is `ruff check` only and
   the existing tree is not ruff-format-formatted; formatting new files would
   diverge from sibling style without a gate to hold it.

## Branching note

All commits directly on `main` per CLAUDE.md §4.1 (single-user project, no
feature branches; dispatch confirmed main-checkout work, no worktree).

## Files touched

- `server/desktop_child.py` — NEW desktop-child entry point + pure-ASGI
  `/readyz` capability middleware (constructed here only).
- `apps/desktop/Cargo.toml` — supervisor workspace member; `=`-pinned
  fs2/libc/tauri/tauri-build/tauri-plugin-shell/tauri-plugin-single-instance.
- `apps/desktop/Cargo.lock` — regenerated for the Tauri graph (tauri 2.11.5,
  fs2 0.4.3, libc 0.2.189 — matches the Spike-3 cached set).
- `apps/desktop/crates/supervisor/{Cargo.toml,build.rs,tauri.conf.json,
  icons/icon.png,src/{main,lifecycle,http,events,process_control}.rs}` — NEW
  supervisor crate (8 unit tests).
- `tests/test_desktop_child.py` — NEW: AC1-AC6 tests (4 heavy marked, 9 fast).
- `tests/conftest.py` — `requires_desktop_stack` added to `_OPT_IN_MARKERS`.
- `pyproject.toml` — marker registration (no packaging change; wheel-check run
  anyway, PASS).
- `Makefile` — `desktop-conformance` builds the supervisor and runs the new
  suite with zero skips.
- `.gitignore` — tauri-build's regenerated `gen/schemas` never enters git.

## Deferred (m6 / later, per the m5 slice)

- Fault matrix (startup-timeout, child-crash, supervisor-crash), 30-cycle
  stress, socket-level loopback regression — m6.
- Degraded/failed render states (m5 ships starting → ready only).
- Production launch-plan authoring (who writes the plan JSON for a bundled
  app) and the frozen Python runtime — e4.
- Non-smoke window-close shutdown path is implemented
  (`RunEvent::Exit` → bounded shutdown) but only the smoke path is
  test-exercised; interactive-quit coverage belongs to m6's fault matrix.
- `Fixes #397` deliberately absent — m6 closes that issue.

## external_writes_required

- `git push origin main` (per-event authorization; not performed).

## Test deltas

- NEW `tests/test_desktop_child.py`: 13 tests (AC1/AC2/AC3/AC4 marked
  `requires_desktop_stack`; AC5/AC6 + entry-point plumbing fast).
- NEW Rust unit tests: 8 in the supervisor crate (plan parsing, barrier
  containment, lock exclusivity, HTTP parser, redirect resolution,
  wait/terminate/reap, sha256 vector).
- `make test` count: 5,069 passed / 47 skipped / 1 xfailed (baseline
  5,060/43/1 → +9 new passing, +4 opt-in skips; zero regressions).

## Check gate results

- `cargo fmt --all --manifest-path apps/desktop/Cargo.toml -- --check`: PASS
- `cargo clippy --locked --target-dir /private/tmp/arxmcp-desktop-target
  --workspace --all-targets --all-features -- -D warnings`: PASS
- `make desktop-conformance PYTHON=.venv/bin/python`: PASS — 27 + 13 tests,
  ZERO skips (fmt, locked workspace test, clippy, both binaries, fixture
  suite, real-child + supervisor-race suite)
- `make test PYTHON=.venv/bin/python`: PASS (exit 0; ruff clean; counts above)
- `make wheel-check PYTHON=.venv/bin/python`: PASS
- git status: clean (state.json + this synthesis committed in the checkpoint
  commit)
