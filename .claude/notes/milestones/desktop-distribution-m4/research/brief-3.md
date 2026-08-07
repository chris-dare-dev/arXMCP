# desktop-distribution-m4 — Adversarial research brief (agent C / role: adversarial)

Role: attack the brief's assumptions before code exists. No solution design.

## 0. Framing fact the brief itself omits

`apps/desktop/README.md:5-7` states in the tracked repo TODAY: "This directory
... does not yet contain the Tauri shell, the frozen Python runtime, ...  or
the production server lifecycle adapter; those belong to the next desktop
milestones." `apps/desktop/Cargo.toml` workspace members are exactly
`crates/desktop-contract` and `crates/fixture-sidecar` — **no Tauri
application crate exists in the tracked codebase.** The only Tauri app that
has ever run in this repo is the throwaway experiment at
`tools/desktop_lifecycle_spike/` (spike-3), which is explicitly a spike:
"No app bundle, signing, notarization, automatic restart, real server
changes, or PyInstaller integration was attempted"
(`.claude/notes/spikes/desktop-distribution-spike-3.md:153`). M4 is therefore
not "connecting" two existing things — it is building the Tauri shell, the
window, the supervisor, and the production Python entry point **for the
first time**, then wiring them to the existing `server/` and `/ui/`.

## 1. Assumption kill-list

| # | Brief assumption | Verdict | Evidence |
|---|---|---|---|
| A1 | Complexity is M (comparable to m1-m3) | **BREAKS** | m1 hit the 350-LOC checkpoint on its first pass (`.claude/notes/milestones/desktop-distribution-m1/implement/scope-exceeded.md:6-8`, 373 LOC). m2 delivered 901 insertions (`.claude/notes/milestones/desktop-distribution-m2/critique/adversary.md:38`), already over the 800-LOC ABORT ceiling, requiring `--allow-large-diff` (H1 invalidated only because the owner pre-approved it — `desktop-distribution-m2/findings.json` H1 resolution). m3's own research estimated 1,100–1,700 LOC and delivered 2,702 (`desktop-distribution-m3/implement/scope-exceeded.md:8-9`, `desktop-distribution-m3/findings.json` H1) — a 59-145% overrun of its own estimate. m3 built *only* the wire contract + a model-free test fixture; m4 must build a real Tauri app, window, supervisor, and a new production Python entry point — categorically more surface than any prior slice. Three-for-three prior "M" milestones in this exact family required the large-diff override. |
| A2 | "Connect the desktop supervisor to the relocatable server" implies wiring, not building | **BREAKS** | No supervisor, no Tauri app crate, no production Python entry point exist. See §0. |
| A3 | "Selects a loopback endpoint without widening the bind boundary" is compatible with current Config | **UNVERIFIABLE / likely BREAKS as naively implemented** | `server/cli.py:208-212` calls `uvicorn.run(host=cfg.bind_host, port=cfg.bind_port)` where `cfg.bind_port` is `field_validator("bind_port")` `validate_port_range` (`server/config.py:825-838`), which rejects anything outside `[1024, 65535]` — **port `0` is already rejected today.** The wire contract (`apps/desktop/crates/desktop-contract/src/lib.rs:338,356`) already requires the *request* to carry port `0` and the *bound* reply to carry a nonzero kernel-assigned port — i.e., "production port-zero adoption" is explicitly named as m4's job in `apps/desktop/README.md:101-103`. There is no existing code path that pre-resolves an OS-assigned ephemeral port into a concrete `ARXMCP_BIND_PORT` value before Config validation runs. See Invariant risk register #1. |
| A4 | M3's protocol is "not macOS-only" so M4 can build on it safely everywhere | **PARTIALLY HOLDS, easy to violate** | `apps/desktop/README.md:9-16`: the *wire protocol* is platform-neutral ("grace/force/reap semantics; a later adapter maps those to Unix process groups or Windows process objects"), but the only implemented process-control code (`setpgid`, `SIGTERM`/`SIGKILL`) lives in the spike, is Unix-only, and has zero `cfg(windows)` branches anywhere in the tracked crates (`grep cfg(windows)` → 0 hits in `apps/desktop/crates`). Release support is explicitly macOS-14-only for now (README:11-13), so M4 is not *required* to ship Windows — but if the supervisor bakes signal names/`setpgid`/`lsof` directly into the lifecycle-state-machine code (rather than behind the adapter seam the README already promises), the "protocol is not macOS-only" claim becomes false the moment M4 lands, not just deferred. |
| A5 | The 5 ACs can be tested by extending `tests/test_desktop_contract.py` / `make desktop-conformance` | **HOLDS as a pattern**, but the AC1/AC2 real-server path is new territory | `make desktop-conformance` (`Makefile:145-150`) already separates the Rust/fixture gate from `make test`; that split is the right precedent for AC5's 30-cycle fixture stress. But AC1 and AC2 require the **real** production server, which m3's fixture never touches (`apps/desktop/README.md:133-136`: "The fixture sidecar imports neither Python nor any model, corpus, LanceDB, or MCP-server module"). No existing test launches the real `server.cli.main` / `create_app()` under the desktop supervisor. |

## 2. Falsifiability table — one row per AC

| AC | Cheap lie that passes | Assertion that would catch it |
|---|---|---|
| AC1 — "exactly one child server reaches health/readiness and the console renders" | Wire the supervisor to `fixture-sidecar` (already built, already exercised 30x in CI) and never actually spawn the real `server.cli.main`/`create_app()` process. `test_desktop_contract.py` already proves the *fixture* protocol end-to-end; a test suite that only re-uses that harness "proves" AC1 without ever booting the real embedder-backed server. | Assert the child process's argv/module target is the production entry point (not `fixture-sidecar`), assert `/readyz` only turns green after the real eager BGE-M3 load completes (not immediately, per `server/main.py:61-66`'s own documented 5-30s warm-up), and assert the rendered window actually requests `/ui/` HTML from that process (not a static/mocked page). |
| AC2 — "MCP smoke request ... normal MCP response ... without schema changes" | Hit `/healthz` or `/readyz` and call that the "MCP smoke" (cheapest possible interpretation — no MCP framing at all), or hardcode/mock the expected JSON-RPC response instead of round-tripping through the real `/mcp` Streamable-HTTP endpoint. | Require an actual MCP `initialize` handshake followed by `tools/list`, and assert the returned tool list hashes to `EXPECTED_TOOL_SCHEMA_SHA256` (`tests/test_server_tool_schema.py:94`) computed from the *live* response bytes, not a fixture. A test that never imports/compares against `EXPECTED_TOOL_SCHEMA_SHA256` is not proving "without schema changes." |
| AC3 — "a second launch activates the existing app or exits clearly without starting another server" | Launch sequentially with a sleep between the two processes so there is no real contention — trivially passes with either plugin or lock present, proves nothing about the race. Spike-3 already found this exact failure mode: "Tauri's single-instance plugin alone does not close a zero-delay startup race" (`.claude/notes/spikes/desktop-distribution-spike-3.md:17-18`). | Reproduce the spike's external-barrier technique — both processes started and held, then released simultaneously (`tools/desktop_lifecycle_spike/run_spike.py:579-636`, `acquire_supervisor_lock` at `tools/desktop_lifecycle_spike/src/main.rs:661`) — and assert exactly one `sidecar_spawned`/equivalent event in the shared record, not merely "the second process exited." |
| AC4 — "bounded cleanup leaves no child process or listener and writes redacted diagnostics" | A "no orphan" audit that greps `ps`/`lsof` and treats an EMPTY result as "clean," without asserting the probe itself succeeded. Spike-3's own methodology explicitly warns against this: "Failed or partial `ps`/`lsof` probes are evidence failures, never clean absence" (`.claude/notes/spikes/desktop-distribution-spike-3.md:61-62`). Similarly, "redacted diagnostics" could ship as an unredacted crash dump written by the new Rust supervisor (no `RedactionFilter`-equivalent exists in Rust — only in Python at `server/observability/log_filter.py:62`) and nobody notices because the test only checks that *a* diagnostics file exists, not that the capability token is absent from it. | Assert the probe command's own exit code / stdout non-degeneracy (e.g. `lsof` must return either a real listener line or a documented "no such process" status, not a silently-empty stream from a broken invocation), AND recursively scan every persisted diagnostic artifact (supervisor crash log, Python stderr, any dump file) for the exact capability-token bytes — mirroring the m3 H4 fix's "recursively traverse causes, contexts, args, decoder documents, and source objects" discipline (`desktop-distribution-m3/rectify/summary.md:23-26`). |
| AC5 — "loopback-only binding + 30 fixture-sidecar cycles without an orphan" | Reuse ONE process across all 30 "cycles" (restart its internal state instead of actually spawning/reaping a new OS process each time), or assert loopback-only by checking `Endpoint("127.0.0.1", …)` equality on the parsed wire frame (`tests/test_desktop_contract.py:353`) instead of an actual socket-level check that nothing is also reachable on a non-loopback interface. | Require 30 distinct PIDs (spike-3 measured this for real: "orphan process groups: 0" over 30 fresh launch→ready→graceful-stop cycles, `.claude/notes/spikes/desktop-distribution-spike-3.md:122-128`) and require the loopback assertion to open a live socket connection to the reported port the same way `tests/test_desktop_contract.py:135` already does (`http.client.HTTPConnection("127.0.0.1", port, ...)`), plus an out-of-band `lsof`/connect probe against `0.0.0.0`/the LAN interface to prove nothing else is listening. |

## 3. Scope verdict

**M is not honest for M4.** Evidence, itemized:

- Baseline: m3 delivered 2,702 insertions / 26 files building *only* the wire
  contract library (726 LOC) + a model-free fixture binary + shared fixtures
  + tests. No window, no real supervisor, no production entry point.
- M4 additionally requires, per the brief's own text: (a) a new Tauri
  application crate (window, `tauri.conf.json`, bundle scaffolding,
  single-instance + shell-plugin wiring — the closest committed analogue,
  the spike's `main.rs`, is 832 LOC by itself, `tools/desktop_lifecycle_spike/src/main.rs`,
  and that version never rendered a real window or drove a real server);
  (b) a production supervisor crate distinct from the spike/fixture path,
  reusing but not duplicating `desktop-contract`; (c) a NEW Python desktop
  entry point (reads the `launch` frame off stdin, resolves an ephemeral
  loopback port, emits the `bound` frame, wires `/healthz` + authenticated
  `/readyz`, honors `ApplicationPaths` installed mode) — none of which exists
  today; (d) an MCP smoke client; (e) single-instance production arbitration
  (plugin + `supervisor.lock`, both already shown necessary by spike-3);
  (f) the full fault matrix (shutdown/timeout/sidecar-crash/supervisor-crash)
  reproduced against the *real* server, not just the fixture; (g) 30-cycle
  stress plus loopback-only regression tests.
- Itemized LOC estimate (Rust + Python + tests, excluding generated
  `Cargo.lock`/`tauri.conf.json` boilerplate which still counts toward the
  pipeline's file/LOC gate):
  - Tauri app crate (window, plugins, bundle config, main.rs): 400–700 LOC
  - Production supervisor crate (lifecycle state machine reusing
    `desktop-contract`, adapted from the spike's 832+177 LOC host/lib but
    hardened to the repo's comment-density and error-handling bar): 700–1,100 LOC
  - New Python desktop entry point + port-resolution + readiness wiring: 250–450 LOC
  - MCP smoke client (Rust or Python): 80–150 LOC
  - Redacted-diagnostics writer (Rust-side, since no Rust equivalent to
    `RedactionFilter` exists): 80–150 LOC
  - Tests (Rust lifecycle tests + Python `test_desktop_contract.py`
    extensions + a new real-server integration test + 30-cycle stress):
    600–1,200 LOC
  - **Total: ~2,100–3,750 LOC**, comfortably past the 800-LOC ABORT ceiling
    and likely past even m3's actual 2,702, given m3's own estimate was
    itself 59-145% low.
- **This will not land under the pipeline's inline or ordinary-delegated
  path.** Expect the Phase-2 800-LOC ABORT to fire immediately unless
  `--allow-large-diff` is invoked up front, or the milestone is split before
  Phase 2 begins.

**Smallest defensible slice that still satisfies all 5 ACs (a real split, not
a scope cut):**

1. **m4a — Real single-cycle lifecycle, macOS only, no fault matrix.** New
   Python desktop entry point + minimal supervisor crate + Tauri window
   pointing at `/ui/` + one real MCP smoke call + AC1/AC2/AC3 (single- and
   dual-launch) + AC4's *normal*-shutdown path only. Skip startup-timeout,
   sidecar-crash, and supervisor-crash fault injection.
2. **m4b — Fault matrix + 30-cycle stress + loopback-socket-level
   regression.** Extends `make desktop-conformance` with the fault-injection
   cases and the 30-cycle orphan-audit AC5 requires, against the fixture
   (cheap, already proven safe by spike-3) plus at least one real-server
   fault case (sidecar crash) to keep AC4 honest.

This split keeps each slice inside or close to the 300-800 delegated band and
avoids repeating the pattern in §4.

## 4. The prior-milestone deferral — is M4 about to repeat it?

m3 deferred H1 ("Cumulative diff exceeds the review limit") with the
rationale: "The owner explicitly authorized the large-diff path before
implementation... Risk is mitigated by two independent critics plus locked
Rust, zero-skip desktop, wheel, and full repository gates"
(`desktop-distribution-m3/findings.json` H1). That mitigation bundle is real
and specific to m3's content (a self-contained wire-protocol library with
byte-exact cross-language fixtures — a shape that two independent critics
can meaningfully review in one pass). m4's content is different in kind: it
spans a new UI surface (Tauri window/webview), OS-level process control, a
new Python startup path, and secret-handling code duplicated in a second
language (Rust diagnostics writer) — a shape where "two critics read one
large diff" is a much weaker mitigation, because the failure modes are
scattered across process boundaries rather than concentrated in one
contract module. Given m1 (373 LOC), m2 (901 LOC), and m3 (2,702 LOC) all
required this same path, repeating it a fourth time without first shrinking
the slice (§3) would be habitual, not legitimated by content. For the
large-diff path to be legitimate *this specific time*, at minimum: (a) the
new Rust supervisor and the new Python entry point must each get an
independent security pass (the two specialists the brief already names,
`mcp-protocol-reviewer` + `security-reviewer`, are necessary but the brief
does not name a third reviewer for the Tauri/webview attack surface — window
content exposure, IPC command surface — which is genuinely new relative to
m1-m3); (b) the port-zero Config question (§ Invariant #1) must be resolved
as a designed decision before implementation starts, not discovered mid-diff;
(c) the split in §3 should be seriously considered as the default, with
`--allow-large-diff` reserved for m4b only.

## 5. Invariant risk register

| Invariant | Current guard | M4 threat |
|---|---|---|
| **#1 — Server never binds a privileged or unpredictable port** | `server/config.py:825-838` `validate_port_range`: `@field_validator("bind_port")` rejects any value outside `[1024, 65535]`, so `ARXMCP_BIND_PORT=0` is rejected TODAY. `server/cli.py:208-212` calls `uvicorn.run(port=cfg.bind_port)` directly — no existing pre-resolution step. | The wire contract already requires ephemeral (port-0) request/nonzero-reply semantics (`apps/desktop/crates/desktop-contract/src/lib.rs:338,356`) and `apps/desktop/README.md:101` names "production port-zero adoption" as explicitly m4's job. Two implementation paths exist: (a) relax `validate_port_range` to accept `0`, which would let **any** caller — Docker (`docker/Dockerfile.server:176` fixed `EXPOSE 7733` + healthcheck against `127.0.0.1:7733`), systemd, or a plain CLI operator — request an unpredictable ephemeral bind where today they get an immediate, clear validation error; or (b) pre-bind a socket outside Config to learn the OS-assigned port, then set `ARXMCP_BIND_PORT` to that *concrete* number before `Config()` ever runs — which never touches the general-purpose validator, but introduces a bind→close→rebind TOCTOU window unless the fd itself is handed to uvicorn. Whichever direction lands, it is a genuine invariant change; the brief must not let the implementer casually pick (a) because it looks like "one line in a validator." |
| **#2 — Server binds loopback only (`reject_non_loopback_bind`)** | `server/config.py:722-750`, gated by `LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})` (`server/config.py:62`) and `ARXMCP_UNSAFE_NETWORK_BIND`. | Low direct threat — the desktop path never needs `0.0.0.0`. Real threat is indirect: if #1 is resolved by widening `validate_port_range`, an operator/CI script that already (mis)sets `ARXMCP_UNSAFE_NETWORK_BIND=1` *and* now also sets `ARXMCP_BIND_PORT=0` gets an unpredictable externally-reachable ephemeral port instead of today's fail-fast port-range error — a second-order interaction the brief doesn't mention. |
| **#3 — `BaseHTTPMiddleware` ban (E06_S01 F1)** | `server/main.py:48-59,156-174`: `BodySizeCapMiddleware` is deliberately pure-ASGI because `BaseHTTPMiddleware` silently no-ops on streaming bodies. | Not directly exercised by the lifecycle skeleton, but the MCP-smoke/readiness-auth work (AC2, AC4) is exactly the kind of "just add a small auth check" task that tempts a `BaseHTTPMiddleware` shortcut for validating the `X-ArXMCP-Startup-Token` header on `/readyz`. Any new middleware for the desktop boundary must follow the existing pure-ASGI pattern, not reintroduce the F1 bug class. |
| **#4 — `EXPECTED_TOOL_SCHEMA_SHA256` / BP1 / BP2 byte stability** | `tests/test_server_tool_schema.py:94` (UPDATE-ANCHOR), cross-checked in ~15 test files (`grep -rl EXPECTED_TOOL_SCHEMA_SHA256 tests/` → 12+ files). | Low direct threat if the desktop MCP smoke only *calls* `tools/list`/`initialize` read-only. Real threat is AC2's own falsifiability gap (see §2 AC2 row): a smoke test that never imports/compares `EXPECTED_TOOL_SCHEMA_SHA256` cannot actually prove "without schema changes," even if no code change touches `server/tools.py`. |
| **#5 — Unknown-`ARXMCP_*`-env-var startup FATAL** | `server/main.py:412-450` `_scan_unknown_arxmcp_env_vars`, carve-out dict `_KNOWN_INGEST_ENV_VARS` at `server/main.py:308-351`. | The new desktop entry point almost certainly needs to pass *something* to the child process — a startup-capability token, a resolved data root, a resolved port. The wire contract already threads these over stdin/stdout NDJSON frames, not env vars (`apps/desktop/README.md:60-118`), which is the safe path that avoids this guard entirely. The risk is a shortcut: if an implementer instead reaches for `ARXMCP_DESKTOP_MODE=1` or similar as a quick signal, and it is not declared on `Config` or added to `_KNOWN_INGEST_ENV_VARS`, `make up`/the desktop launch FATALs at server startup with a scary env-var error — or, worse, someone "fixes" it by weakening the scan rather than declaring the var properly. |
| **#6 — `ApplicationPaths` sole ownership of the mutable layout** | `server/application_paths.py:92-183`, `ApplicationPaths.resolve()`; `apps/desktop/README.md:18-23`: "Python's `server.application_paths.ApplicationPaths` remains the sole owner of the internal data layout; the supervisor passes one canonical root." | The Rust supervisor needs to *display* or *reason about* the data root (for the launch manifest's canonical data root field) without reconstructing platform-specific defaults itself. `server/application_paths.py:81-89` `_platform_data_root` already encodes the macOS/Windows/Linux default paths in Python — the temptation is for the new Rust supervisor code to reimplement the same `AppData/Local` / `Application Support` / `XDG_DATA_HOME` logic independently (e.g. via a Rust `dirs`/`directories` crate) rather than always receiving the resolved root from the Python side or a single shared source of truth. Two independent implementations of "where is the data root" is exactly the kind of drift `ApplicationPaths` was built to prevent (m1's whole purpose). |
| **#7 — Startup capability absence from argv/env/URLs/logs/errors/manifests** | `apps/desktop/README.md:105-118`: token is 32 CSPRNG bytes, hex, accepted only via stdin `launch`/`shutdown` frames and the `X-ArXMCP-Startup-Token` header; never argv/env/URL/bound-field/exception/log/manifest. `server/desktop_contract.py:206` (H4 fix, m3) already proves payload-free decoder errors. | M4 introduces genuinely new leak surfaces that did not exist when this rule was written for a headless fixture: (1) **Tauri window content** — if the webview is ever given the loopback URL with the token embedded as a query param instead of only via the `X-ArXMCP-Startup-Token` header, `document.location`/browser history/devtools would expose it; (2) **Tauri IPC events** — if the supervisor emits a JS-visible event carrying lifecycle state, a careless implementation could attach the raw capability instead of an opaque state enum; (3) **crash dumps** — Tauri/OS-level crash reporters (if enabled) could capture process memory including the token; (4) **the new Rust-side diagnostics writer** (see AC4 falsifiability row) has no `RedactionFilter`-equivalent today and must independently re-implement the token-scrubbing discipline `server/desktop_contract.py:206` and `server/observability/log_filter.py:62` already prove in two different modules — a third, Rust-language redaction implementation with no shared test proving parity across all three is a plausible drift point. |

## 6. Cross-platform honesty — where a macOS-only assumption enters M4

- **Process groups / `setpgid`.** Only implemented today in the spike
  (`tools/desktop_lifecycle_spike/src/bin/fixture_sidecar.rs:122-124`,
  `unsafe { libc::setpgid(0, 0) }`), zero `cfg(windows)` branches anywhere in
  `apps/desktop/crates/`. Windows has no process-group signal equivalent;
  the nearest primitive is Job Objects (`CreateJobObject` +
  `TerminateJobObject`/`AssignProcessToJobObject`), a fundamentally different
  API shape, not a signal name swap.
- **Signal names (`SIGTERM`/`SIGKILL`).** The wire contract deliberately
  encodes "grace/force/reap" as *semantics*, not signal names
  (`apps/desktop/README.md:98-103`) — this was clearly done on purpose to
  keep the contract portable. The threat is the *supervisor implementation*
  hard-coding `kill(-pgid, SIGTERM)` inline in the lifecycle state machine
  rather than behind a named adapter function/trait the README already
  promises ("a later adapter maps those to Unix process groups or Windows
  process objects" — README:15-16). If M4 doesn't introduce that seam now,
  a future Windows milestone has to retrofit it into code that was never
  designed with the boundary in mind.
- **`lsof`/`ps` in tests.** Spike-3's audit tooling used
  `/usr/sbin/lsof -nP -iTCP:<port> -sTCP:LISTEN` and `ps -axo pid=,pgid=,comm=`
  directly (`.claude/notes/spikes/desktop-distribution-spike-3.md:111-113`).
  Neither exists on Windows. If M4's new AC5 orphan-audit test copies this
  verbatim rather than gating it behind `sys.platform`/`cfg(unix)` (with an
  honest non-claim or a `netstat`/`Get-NetTCPConnection` equivalent for
  Windows), the test either silently no-ops or hard-fails on any future CI
  runner that isn't macOS/Linux.
- **Bundle layout / `.app` paths.** No bundle work is in scope for M4 per
  the epic decomposition (`desktop-distribution-e4` "macOS artifact passes
  platform trust gates" is a *separate*, dependency-only epic — see
  `plans/desktop-distribution-roadmap.md:108-116`), so this is a smaller risk
  for M4 specifically, but the sidecar-binary resolution path (how the
  supervisor finds its child executable — `fixture-sidecar-aarch64-apple-darwin`
  naming per spike-3 §"macOS primitives exercised") is target-triple-suffixed
  and that convention needs to hold for `-x86_64-pc-windows-msvc`/
  `-x86_64-unknown-linux-gnu` even if only macOS ships this cycle.
- **What keeps the "not macOS-only" promise honest for M4 specifically:**
  the process-control code (signal/PGID/Job-Object specifics) and the
  orphan-audit probe must each sit behind a named, single-call seam — even
  if only the Unix implementation is written this milestone — rather than
  being inlined into the lifecycle state machine or the test harness. This
  is a testable structural property (does a `grep` for `setpgid`/`SIGTERM`/
  `lsof` outside one clearly-named module return zero hits?), not a
  documentation promise.
- **Precedent this is not hypothetical:** m3 already produced exactly this
  failure once — H2 "Positive fixtures are not Windows-portable"
  (`desktop-distribution-m3/findings.json` H2,
  `apps/desktop/contract-fixtures/launch-v1.jsonl:1`) — fixed by unifying the
  path grammar. Cross-platform assumptions leaking into "just the wire
  format" already happened; M4 has a much larger surface (real process
  control, not just path strings) to get wrong the same way.

## 7. Test-suite hazards

- **Host-state-dependent flakiness precedent (not hypothetical):** m2's
  first full-suite rectify run failed 4 tests because real host disk-free
  space crossed the operator's 10 GiB safety threshold and created the
  `var/arxmcp/ops/ingest-paused` sentinel mid-run
  (`desktop-distribution-m2/rectify/summary.md:71-76`). m3's first full-suite
  run separately found the fixture's 200 ms HTTP read deadline "too
  aggressive under repository load," raised to 2,000 ms
  (`desktop-distribution-m3/rectify/summary.md:75-78`, corroborated by the
  `timeout=2` call sites already in `tests/test_desktop_contract.py:135,161,173,176,443,473,492`).
  Both failure modes are "passes on a quiet machine, flakes under load" —
  exactly the shape M4's 30-cycle stress test and any new
  disk/CPU-sensitive fault-injection case (e.g. simulating a slow-starting
  server under startup-timeout) will reproduce unless deadlines are set with
  headroom from the start, not discovered after a red CI run.
- **Prediction: which M4 tests will be flaky under load.** (a) Any
  fault-matrix case with a fixed millisecond deadline shorter than ~1–2s
  (mirrors the exact m3 finding); (b) the 30-cycle stress test if run
  against the *real* production server (embedder warm-up variance, not the
  fixture) rather than the fixture-sidecar the AC text actually specifies;
  (c) the second-launch race test (AC3) if the external-barrier release
  itself has scheduler jitter under CPU contention, producing an
  occasional double-owner false negative/positive.
- **Bounded-but-not-aggressive deadlines:** follow the already-established
  2,000 ms precedent for HTTP-level readiness polls; for the AC1/AC2 real
  server smoke path, the deadline must additionally accommodate
  `server/main.py:61-66`'s own documented 5-30s eager BGE-M3 warm-up — a
  sub-second or even sub-10s deadline on the *real*-server path would be a
  self-inflicted flake independent of the desktop code being tested.
- **Will 30 real lifecycle cycles fit in `make test`'s existing runtime
  (asserted 322s baseline)?** No, and the repo has already made this exact
  decision once: `make desktop-conformance` (`Makefile:145-150`) is a
  dedicated target, separate from `make test`, that builds Rust first and
  then runs `tests/test_desktop_contract.py` alone — m3's own rectify
  summary reports this ran "27 Python tests with zero skips" as an
  independent gate, not folded into the main suite
  (`desktop-distribution-m3/rectify/summary.md:64-65`). The honest split for
  M4 is the same: the 30-cycle stress (AC5) and any real-server fault
  cases belong in an extended `make desktop-conformance`, not `make test`;
  `make test` should only gain the config-layer/unit-level assertions (e.g.
  a `validate_port_range` regression test) that don't require building Rust
  or spawning subprocesses. (Note: the 322s figure was supplied as given
  context for this research and was not independently re-timed within this
  brief's budget — re-verify at implementation time since suite content
  changes every milestone.)

## 8. Specialist coverage gap

The brief names `mcp-protocol-reviewer` and `security-reviewer`. Given the
new Tauri window/webview surface (§5 #7) and the new Rust-side redaction
code with no cross-language parity test, a reviewer with actual Tauri/webview
IPC-security familiarity is not obviously covered by either named specialist
— worth an explicit decision (not a default assumption) at Phase 2/3, not
raised here as a blocking finding since this brief does not design solutions.
