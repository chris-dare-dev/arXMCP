# Critique — desktop-distribution-spike-3 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** 010d85d70b550ed98ab343aedb0bca9d8e2a3e02..061fb6159c6c46dc78fbec2a87b38c7f4d46a43d
**Diff stats:** 15 files, 8927 LOC
**Critique format version:** 1.0

## Verdict

DO-NOT-SHIP

The pinned Tauri fixture establishes useful primitives, but the GO decision is not supported for three load-bearing lifecycle cases: neither child fault is an abrupt crash, the pre-bound audit can report an unaudited process group as clean, and the duplicate launch is not raced. The spike also leaks its Python harness into the production wheel despite explicitly claiming that subtree is non-wheel content. These are acceptance and distribution-boundary failures, not documentation polish.

## Executive summary

- [HIGH] Both child-crash faults unwind normally and let `Canary::drop` perform cleanup that an abrupt crash would skip.
- [HIGH] Missing listener metadata is hard-coded as a clean audit, making the crash-before-bound orphan total untrustworthy.
- [HIGH] The duplicate process starts only after the primary records readiness, so startup arbitration is never raced.
- [HIGH] The packaging-test skip hides the Rust subtree from its guard while namespace discovery still ships `run_spike.py` in the wheel.
- [MEDIUM] Normal shutdown is initiated inside the lifecycle task; no real Tauri `ExitRequested` path is intercepted or measured.
- [MEDIUM] The repository gate trusts self-authored GO/`ok` fields and does not bind the evidence to the reviewed source and lockfile.
- [MEDIUM] Every case gets a fresh data root, so advisory-lock contention and same-root post-crash reacquisition are not exercised.
- [MEDIUM] The listener audit ignores every `lsof` failure status, allowing an unavailable audit to look like zero listeners.

## Findings

**H1 — Crash faults are orderly exits** (HIGH)

**Where:** `tools/desktop_lifecycle_spike/src/bin/fixture_sidecar.rs:175`
**Anchor:** `return Err("injected crash before bound"`
**What:** Both child-crash fault branches return `Err`, so Rust unwinding runs `Canary::drop` and performs the cleanup that the supervisor is supposed to prove.
**Why it matters:** An actual signal or abort skips `Drop`, and the host's unexpected-termination branches currently return success without signaling the residual process group, so a same-group canary can survive a real child crash.
**Proposed fix:** Arm each crash only after the group and canary exist, terminate the fixture abruptly from the external harness before bound and after readiness, and make the host clean any residual group after an unexpected direct-child termination before it records success.
**Regression-guard:** Add live macOS cases that require a signal-based direct-child exit, record supervisor group cleanup after that exit, and then assert the canary PID, child PID, process group, and listener are all absent.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**H2 — Missing metadata is declared clean** (HIGH)

**Where:** `tools/desktop_lifecycle_spike/run_spike.py:223`
**Anchor:** `if meta is None:`
**What:** `_post_run_audit` returns `clean: True` without inspecting any process whenever `listener-meta.json` is absent.
**Why it matters:** The committed crash-before-bound case has no metadata and no live observation, so its zero-orphan and secret-clean contributions are assertions rather than bounded audits of the spawned PID and process group.
**Proposed fix:** Pass the PID from the mandatory `sidecar_spawned` record into the audit, derive the expected pre-bound PGID from that PID, and treat missing metadata after a spawn as incomplete evidence unless PID, executable identity, and group absence are checked independently.
**Regression-guard:** Replace the test that requires `_post_run_audit(None)` to be clean with cases proving that a recorded pre-bound spawn is unclean while its PID or PGID exists and becomes clean only after both disappear.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**H3 — Duplicate launch is not raced** (HIGH)

**Where:** `tools/desktop_lifecycle_spike/run_spike.py:312`
**Anchor:** `if not _wait_for_event(root / "events.nd`
**What:** The harness waits for `ready_authenticated` before it starts the duplicate host, so it exercises activation of an established primary rather than concurrent startup arbitration.
**Why it matters:** The exactly-one invariant is most vulnerable before the primary has spawned and locked its sidecar, and the required raced-launch case therefore remains unproven.
**Proposed fix:** Start two host processes from a common barrier or back-to-back before either can record readiness, let the single-instance and advisory-lock mechanisms select the winner, and audit both process outputs plus live listeners until the loser exits.
**Regression-guard:** Record external launch timestamps and require both processes to start before the winning host's readiness event, exactly one `sidecar_spawned` transition, exactly one live listener during arbitration, and clean exit of the loser.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first + Docker constraint

**H4 — Spike harness leaks into the Python wheel** (HIGH)

**Where:** `tests/test_wheel_packaging.py:65`
**Anchor:** `_SKIP_DIRS = frozenset(`
**What:** Skipping `desktop_lifecycle_spike` in the data-file walker does not exclude its namespace package from the existing `tools*` discovery rule, and the built wheel contains `tools/desktop_lifecycle_spike/run_spike.py`.
**Why it matters:** The milestone explicitly excludes production packaging integration, yet this change silently expands the shipped Python artifact and blinds the load-bearing package-data guard to the new subtree.
**Proposed fix:** Exclude `tools.desktop_lifecycle_spike*` in `[tool.setuptools.packages.find]`, make the static skip conditional on that explicit package exclusion, and keep the Cargo-only subtree out of both wheel package discovery and package data.
**Regression-guard:** Build the wheel in the packaging test and assert that no archive member starts with `tools/desktop_lifecycle_spike/`; also assert namespace-package discovery excludes that prefix.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M1 — Ordinary Tauri exit bypasses graceful shutdown** (MEDIUM)

**Where:** `tools/desktop_lifecycle_spike/src/main.rs:577`
**Anchor:** `.run(tauri::generate_context!());`
**What:** The host uses Tauri's convenience `run` path without handling `RunEvent::ExitRequested`, while its only authenticated shutdown is initiated internally after readiness.
**Why it matters:** A real operator or platform exit has not been shown to prevent exit, drain through the authenticated shutdown protocol, await reap, and then complete; it instead falls back to the stdin-EOF crash behavior.
**Proposed fix:** Build the app and run it with an exit-event callback backed by the serialized lifecycle actor, prevent the first exit request, complete bounded authenticated shutdown and reap, then issue the final guarded exit.
**Regression-guard:** Add a live scenario that requests ordinary Tauri exit while ready and requires `shutdown_sent` and `sidecar_reaped` to precede host termination without using the parent-crash sentinel.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security threat-model coverage

**M2 — Committed GO is not bound to reviewed source** (MEDIUM)

**Where:** `tests/test_desktop_lifecycle_spike.py:80`
**Anchor:** `assert payload["decision"] == "GO"`
**What:** The repository test trusts the harness-produced `decision`, `ok`, totals, and literal `host_is_tauri_binary` fields without tying them to a digest of the current Rust, harness, configuration, and `Cargo.lock` inputs.
**Why it matters:** The spike source can stop compiling or regress after this run while `make test` continues to accept stale committed GO evidence byte-for-byte.
**Proposed fix:** Put a deterministic tracked-input digest and exact commit in the evidence, recompute that digest in the Python gate, verify the aggregate digest from all case digests, and provide a macOS-only opt-in command that rebuilds and reruns the live gate.
**Regression-guard:** Verify that changing any copied tracked spike input invalidates the evidence check, while an unchanged tree validates the input and aggregate digests.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M3 — Advisory-lock recovery is never exercised** (MEDIUM)

**Where:** `tools/desktop_lifecycle_spike/run_spike.py:296`
**Anchor:** `root = Path(tempfile.mkdtemp(prefix=f"{s`
**What:** Every case receives a new data root, and the Tauri duplicate is stopped before spawning a second sidecar, so neither lock contention nor same-root reacquisition after supervisor crash occurs.
**Why it matters:** The advisory lock is documented as the second exactly-one guard, but its busy-owner and stale-path recovery behavior contributes no measured evidence to the GO decision.
**Proposed fix:** Add a same-root contention case that proves a second fixture cannot acquire the live lock, then reuse the parent-crash root and retained lock pathname for an immediate normal relaunch before deleting the scratch directory.
**Regression-guard:** Require a live `lifecycle lock busy` result while the first owner exists and successful ready/stop events from a second host using the identical data root after the crashed run is clean.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first + Docker constraint

**M4 — Listener audit fails open on lsof errors** (MEDIUM)

**Where:** `tools/desktop_lifecycle_spike/run_spike.py:204`
**Anchor:** `check=False,`
**What:** `_listener_rows` ignores the `lsof` return code and stderr, so any diagnostic failure with empty stdout is interpreted as no listener.
**Why it matters:** The exact zero-listener total is only trustworthy if the independent macOS audit ran successfully rather than being unavailable or denied.
**Proposed fix:** Distinguish the documented no-match status from execution and permission failures, retain the return code plus a redacted stderr digest in normalized evidence, and fail the case when the audit did not complete successfully.
**Regression-guard:** Stub `lsof` to return an unexpected nonzero status with empty stdout and assert the post-run audit is not clean; separately retain the real no-match case as clean.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

## What was done well

- Cache byte-stability is axis-verified clean: no MCP tool definition, result envelope, prompt constant, or cache-key path changed, so no schema or BP hash re-pin is warranted.
- Math fidelity is axis-verified clean: the diff does not touch LaTeX, MathML, paper bytes, chunking, macro preservation, or embedding inputs.
- MCP compliance is axis-verified clean: the Streamable HTTP mount, JSON-RPC methods, SSE framing, and tool-result content shape are untouched.
- The child really retains a kernel-assigned `127.0.0.1:0` listener and reports it over a bounded frame; there is no bind-close-rebind port race.
- Security-sensitive primitives are concrete: 256-bit randomness, stdin-only token transport, a cleared child environment, loopback announcement validation, and bounded control frames are present.
- Tier sequencing is axis-verified clean: this isolated fixture consumes no pending corpus, retrieval, security, or observability tier capability.
- The no-fork axis is clean: the committed lockfile resolves registry crates, with no git dependency, submodule, or copied `arxiv-mcp` source.
- The live matrix records eleven named scenarios and exactly thirty fresh normal cycles with distinct result digests and reported 0/0 orphan/listener totals.
- Generated binaries, Cargo targets, app bundles, Node/npm assets, frontend code, production server configuration, and production data-root contracts remain out of the commit.
- The ADR accurately limits the result to macOS 26.6 on Apple Silicon and explicitly avoids claiming macOS 14, arbitrary `setsid()` descendants, a wedged child after parent death, or production Python integration.

Severity counts: C0 H4 M4 L0

## Recommended rectification order

H1, H2, H3, H4, M1, M2, M3, M4

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed: <finding ids>
- Deferred: <finding ids>
- Invalidated: <finding ids with reasons>
- Regression tests added: <file paths>
