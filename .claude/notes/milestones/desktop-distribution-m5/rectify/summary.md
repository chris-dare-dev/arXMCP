# Rectify summary — desktop-distribution-m5

**Critique:** `.claude/notes/milestones/desktop-distribution-m5/critique/dedup.md`
(C2 H3 M18 L11 = 34 findings, 3 critics)
**Commit range critiqued:** `1a542ee..4d797a7`
**Invalidation rate:** 0% (0 of 34). Every blocking finding was re-verified
against live code before rectification; none rested on a stale snapshot.

## Dispositions

| id | disposition | resolution |
|----|-------------|------------|
| C1, M14 | fixed | `apps/desktop/README.md` rewritten — the opening paragraph names the supervisor crate and the lifecycle adapter as landed (frozen runtime / signing / plan authoring still deferred), the command block gains `cargo build --bin supervisor` and the `DESKTOP_SUPERVISOR_BIN` pytest invocation, and the M3 paragraph records m5's port-zero adoption, authenticated readiness and Tauri exit handling. |
| C2 | fixed | `CLAUDE.md` 4.5 now says **Ten** markers, names all four added since the list was written, and carries a `requires_desktop_stack` bullet. |
| H1 | fixed | `server/desktop_child.py` passes `timeout_graceful_shutdown=_graceful_timeout_seconds(launch)`; the `_serve` docstring no longer calls an unbounded drain "a superset of the contract's floor". **Trigger corrected — see below.** |
| H2 | fixed | `main()` calls `_configure_child_logging(cfg)` between `Config(...)` and `create_app(cfg)`, mirroring `server/cli.py:159`, so the desktop boot path installs the E13_S08 `RedactionFilter` and the 12-factor JSON formatter. |
| H3 | fixed | (a) the Makefile's `-m` marker token is asserted to be a member of `tests.conftest._OPT_IN_MARKERS` (imported, not re-hardcoded), plus `--bin supervisor` build-before-run ordering; (b) `tests/conftest.py` fails any session that skips while `DESKTOP_SUPERVISOR_BIN` is set. |
| M1 | fixed | Documented rather than widened — with evidence. See below. |
| M2 | fixed | The post-SIGKILL reap uses `wait_exit(child, REAP_BUDGET_MS = 2000).unwrap_or(-1)`; an exhausted budget returns -1, which the caller already records as `shutdown-unclean`. |
| M3 | fixed | New Rust test `shutdown_child_escalates_through_terminate_to_kill` drives a child that ignores stdin EOF **and** SIGTERM through the whole grace/TERM/force/KILL/reap ladder with 200 ms budgets. |
| M4 | fixed | `notify_running_instance` narrowed from `cfg(unix)` to `cfg(target_os = "macos")`; the non-macOS arm returns `ErrorKind::Unsupported` and names the plugin's DBus transport. The loser records `lock-contended` with an `activated` field. |
| M5, M9 | fixed | AC3 replaces `wait()` + post-hoc `stderr.read()` with `communicate(timeout=300)` on both supervisors (killing the undrained-PIPE deadlock) and feeds all four captured streams through the same `_HEX64` allow-list sweep. |
| M6 | fixed | AC2 asserts `set(payload["result"]) == {"tools"}` before hashing, so a wire `nextCursor` or top-level `_meta` fails the gate instead of being discarded by the reconstructed envelope. |
| M7 | fixed | `STARTUP_TOKEN_HEADER_BYTES` derived from `desktop_contract.STARTUP_TOKEN_HEADER`; the literal is gone from the module. |
| M8 | fixed | The `_watch_stdin` thread starts **before** `await server.startup(...)`, so a quit during the 5-30 s warm-up becomes a fast clean exit instead of a ~40 s hang ending in SIGKILL. |
| M10, L1 | fixed | The `real_child` namespace carries a `stopped` flag; AC4 sets it, AC1/AC2 assert it is False, so a reorder fails with the real reason. |
| M11 | fixed | Kept `ARXMCP_ENABLE_RERANK=1` (dropping it would weaken AC1's all-true warm evidence) and **declared** the prerequisite: the `requires_desktop_stack` registration now names the fail-closed BGE-reranker-v2-m3 load. |
| M12, L10 | fixed | Named `SINGLE_INSTANCE_SOCKET` constant pinned by a unit test against the `tauri.conf.json` identifier derivation; the notify refuses a socket this uid does not own and is skipped entirely in smoke mode. |
| M15 | fixed | `mcp_post` uses a dedicated `SMOKE_TIMEOUT` of 15 s instead of the 2 s `PROBE_TIMEOUT`. |
| M16 | fixed | `tauri_plugin_shell::init()` removed and the dependency dropped from both manifests; `Cargo.lock` regenerated (**480 -> 470** packages). Removes `shell:allow-execute` / `spawn` / `open` / `kill` from the grantable webview ACL. |
| M17 | fixed | `test_supervisor_grants_no_webview_capabilities` pins the deny-by-default ACL. |
| M13 | **deferred** | Half landed (`test_desktop_lockfile_has_no_git_sources` pins the no-fork axis). The `cargo audit` / `cargo deny` step adds an uninstalled third-party tool to the **mandatory** gate and needs an explicit opt-out variable plus a recorded license census — a supply-chain milestone, not a rectification. |
| M18 | **deferred** | Pinning a `rust-toolchain` channel is a cross-machine policy decision (every developer and CI then downloads that exact toolchain) and belongs with the packaging / release-signing milestone that also owns the MSRV claim. Nothing in this diff regresses without it. |
| L2-L9, L11 | **deferred** | LOW, per the Phase-4 severity policy. None is a correctness or security regression introduced by this diff; m6 owns the fault matrix and the socket-level loopback regression. |
| - | invalidated | **None.** |

**Totals: 23 fixed - 11 deferred - 0 invalidated.**

## The two decisions that were asked for explicitly

### M1 — document the residual; do NOT widen the middleware

Widening `ReadyzStartupTokenMiddleware` to `{/readyz, /status, /ui/status-badge}`
**would break the shipped product.** `server/frontend/templates/base.html:133`
polls `/ui/status-badge` with `hx-get` on `load, every 10s`, and that poll comes
from the Tauri webview, which holds no capability — gating it would return 401
on every desktop console page. The critique's "the supervisor uses neither, so
nothing in-tree breaks" is true of the supervisor and false of the console.

So the docstring now states the residual precisely: this gate authenticates the
*supervisor* on `/readyz`; it is **not** a readiness-confidentiality control,
because `/status` and `/ui/status-badge` report the same warm snapshot
unauthenticated on the same ephemeral port.

### tauri-plugin-shell — removed

Nothing calls it (the child is spawned with `std::process::Command`), and
registering it puts `shell` in the compiled ACL manifest, making
`shell:allow-execute` / `allow-spawn` / `allow-open` / `allow-kill` grantable to
a webview that renders HTTP served by the child. Deleting it narrows that
surface for free and drops 10 packages from the shipped dependency graph.

## H1 — the defect is real, the critique's trigger is not

The critique's mechanism ("an open `GET /mcp/` SSE stream keeps the drain loop
running forever") **does not reproduce**, and copying it into the regression
guard produced a green test that could never bite. Measured live:

| shape | `timeout_graceful_shutdown` | result |
|---|---|---|
| held SSE stream (`GET /mcp/`, body unread) | none (pre-fix) | exit 0 in **1.15 s** |
| held SSE stream | launch-derived | exit 0 in **1.15 s** |
| half-sent request (headers, `Content-Length` body never sent) | none (pre-fix) | **no exit at 60 s** — killed |
| half-sent request | launch-derived | exit 0 in **17.91 s** |

`sse_starlette`'s `_shutdown_watcher` locates the uvicorn `Server` through
`signal.getsignal(SIGTERM).__self__` — which resolves because `_serve` runs
inside `Server.capture_signals()` — and closes its own streams when it sees
`should_exit`. SSE is therefore rescued; **any other** incomplete request cycle
is not, because `connection.shutdown()` can only clear `keep_alive` when a
response is in progress.

The underlying defect is exactly as filed: unbounded drain -> the supervisor
SIGKILLs at grace + force -> `lifespan.shutdown()` never runs -> LanceDB/Kuzu
handles stay open (CLAUDE.md section 3's kuzu 0.11.3 mandatory-lock hazard).
AC4 now wedges a half-sent request across the shutdown instead of an SSE stream.

**Deviation from the proposed fix, stated:** the critique proposed
`grace_ms // 1000 - 5` (30 s of a 35 s window). Shipped
`max(1, grace_ms // 2000)` (17 s) instead — the point of the fix is that the
lifespan shutdown *runs*, and leaving it 5 s of a 35 s window is a thin margin
for the very LanceDB/Kuzu close that motivates the change. Half leaves the same
margin again. Both satisfy "strictly inside the grace window".

## Regression coverage added

| file | what it now guards |
|---|---|
| `tests/test_desktop_contract.py` | Makefile marker token is in `_OPT_IN_MARKERS` (H3a); supervisor build-before-run ordering; README describes the shipped workspace (C1); `Cargo.lock` has no git sources (M13-half); zero webview capabilities + no shell plugin (M16/M17) |
| `tests/conftest.py` | any skip in a `DESKTOP_SUPERVISOR_BIN` session fails the session (H3b) |
| `tests/test_marker_doc_consistency.py` | **new** — CLAUDE.md 4.5's count and enumeration derived from `pyproject.toml` (C2); `_OPT_IN_MARKERS` subset of registered (issue #206 pairing); reranker prerequisite declared (M11) |
| `tests/test_desktop_child.py` | drain bound derived from the launch frame and actually handed to `uvicorn.Config` (H1); `RedactionFilter` + `JsonFormatter` installed and the helper called from the boot path (H2); header derived from the contract constant (M7); AC4 wedges an undrainable request and asserts exit 0 inside `grace_ms` (H1 live); AC2 envelope assertion (M6); `stopped` flag (M10/L1); AC3 stream sweep (M5/M9) |
| `apps/desktop/crates/supervisor/src/lifecycle.rs` | full TERM/KILL/reap escalation, bounded (M2/M3) |
| `apps/desktop/crates/supervisor/src/main.rs` | socket path matches the configured identifier (M12/L10) |

## Verification — actual gate output

```
$ .venv/bin/python -m ruff check .
All checks passed!

$ cargo fmt --all --manifest-path apps/desktop/Cargo.toml -- --check
(clean, no output)

$ cargo clippy --locked --manifest-path apps/desktop/Cargo.toml \
    --target-dir /private/tmp/arxmcp-desktop-target \
    --workspace --all-targets --all-features -- -D warnings
Finished `dev` profile [unoptimized] target(s) in 1.29s

$ cargo test --locked --manifest-path apps/desktop/Cargo.toml --workspace
test result: ok. 8 passed; 0 failed   (contract integration)
test result: ok. 10 passed; 0 failed  (supervisor unit)      => 18 total, was 16

$ make desktop-conformance PYTHON=.venv/bin/python
31 passed in 0.81s      (tests/test_desktop_contract.py, was 27)
18 passed in 35.57s     (tests/test_desktop_child.py, was 13; ZERO skips)
EXIT=0

$ make test PYTHON=.venv/bin/python
5082 passed, 47 skipped, 1 xfailed, 83 warnings in 318.89s (0:05:18)
EXIT=0
```

Test count **5069 -> 5082** (+13); skips unchanged at 47; no test lost.
`test_desktop_child.py` went 13.44 s -> 35.57 s, which is the ~18 s bounded
drain now genuinely being exercised — the earlier 13.44 s was the tell that the
first H1 guard was a false green.

H3 guard verified against the reported failure mode:

```
$ DESKTOP_SUPERVISOR_BIN=/nonexistent pytest tests/test_desktop_child.py -m "foo or not foo"
DESKTOP_SUPERVISOR_BIN is set, so this run is the desktop conformance gate
and must have ZERO skips; 4 test(s) skipped:
  - tests/test_desktop_child.py::test_ac1_real_child_ready_and_console
  - tests/test_desktop_child.py::test_ac2_mcp_smoke_live_schema_hash
  - tests/test_desktop_child.py::test_ac3_zero_delay_race_single_spawn
  - tests/test_desktop_child.py::test_ac4_normal_shutdown_leaves_nothing
EXIT=1        (was 0 — the m3 M4 failure mode wearing a new hat)
```

Findings register gate: `desktop-distribution-m5: gate OK - no open findings.`

## external_writes_required

- `git push origin main` — **NOT executed here.** The user authorizes pushes
  per event (CLAUDE.md 4.4); this rectification stops at that boundary.
