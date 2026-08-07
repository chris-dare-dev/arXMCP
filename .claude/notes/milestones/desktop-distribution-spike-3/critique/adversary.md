# Critique — desktop-distribution-spike-3 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** 010d85d70b550ed98ab343aedb0bca9d8e2a3e02..061fb6159c6c46dc78fbec2a87b38c7f4d46a43d
**Diff stats:** 15 files, 8,927 LOC (8,925 additions, 2 deletions; 5,054 lockfile + 1,751 normalized evidence)
**Critique format version:** 1.0

## Verdict

DO-NOT-SHIP

The committed run is useful but does not yet support the recorded GO decision. A child that stalls before `setpgid` can survive both group signals, the alleged duplicate-launch race is serialized after readiness, one crash scenario turns absent audit metadata into a clean result, and the executed binary is not bound to the reviewed pinned source. Rectify those gaps and regenerate the live evidence before this lifecycle protocol is used as the desktop ownership decision.

## Executive summary

- [HIGH] Group signalling treats `ESRCH` as successful even while the direct child is alive but has not yet created its PID-named process group, so the startup-timeout path can leave exactly the orphan it is meant to prevent.
- [HIGH] The duplicate process is launched only after the primary has recorded `ready_authenticated`; this is not the raced startup described by the research contract, synthesis, and ADR.
- [HIGH] `crash-before-bound` deliberately exits before listener metadata exists, while the harness defines missing metadata as a completely clean PID/group/listener audit and adds zero to both published totals.
- [HIGH] `host_is_tauri_binary` and dependency provenance are asserted by constants; the harness accepts arbitrary/stale executable paths and records no source/lock digest that ties those binaries to this diff.
- [HIGH] Even after separating 5,054 lockfile lines and 1,751 normalized-evidence lines, the diff contains 1,637 authored lifecycle-code lines and trips the mandatory review-quality auto-finding.
- [MEDIUM] Several post-spawn error returns skip bounded cleanup, and the harness itself deletes a failed run root without best-effort removal of a dirty process group.
- [MEDIUM] Secret and lifecycle evidence has fail-open edges: a failed `ps` scan is clean, chunk-split canaries evade the host scanner, and event sets erase ordering and multiplicity.
- [MEDIUM] The packaging guard suppresses this subtree from data-file checks but does not exclude its implicit namespace package, so `run_spike.py` still enters the Python wheel.

## Findings

**H1 — Startup timeout can miss a child before it creates its PGID** (HIGH)

**Where:** `tools/desktop_lifecycle_spike/src/main.rs:280`
**Anchor:** `if error.raw_os_error() == Some(libc::ES`
**What:** `signal_group` treats `kill(-pid, signal) == ESRCH` as success, although a newly spawned child remains live under that exact result until it calls `setpgid(0, 0)` after reading and validating bootstrap.
**Why it matters:** A loader/bootstrap stall before process-group creation receives neither `SIGTERM` nor `SIGKILL`, `force_group_stop` has no direct-child fallback, and the supervisor can exit while the timed-out child remains alive, violating the milestone's bounded forced-kill/reap invariant.
**Proposed fix:** Distinguish "group absent" from "child gone": when negative-PID signalling returns `ESRCH`, use the retained `CommandChild` handle to kill the direct child and await its termination event; because the fixture creates no descendant before `setpgid`, direct-child kill is the correct bounded fallback for this phase, while post-group failures should continue to signal the full group.
**Regression-guard:** Add a live `pre-group-timeout` fixture mode that blocks before `setpgid` and metadata creation, then assert the deadline invokes direct-child kill, observes termination/reap, and leaves the spawned PID absent.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**H2 — The duplicate case starts only after the primary is ready** (HIGH)

**Where:** `tools/desktop_lifecycle_spike/run_spike.py:312`
**Anchor:** `if not _wait_for_event(root / "events.nd`
**What:** The harness waits up to three seconds for the primary's `ready_authenticated` event before it starts the duplicate process, so no two launches contend during single-instance initialization or sidecar setup.
**Why it matters:** The implementation summary and ADR call this a raced duplicate launch, but the run proves only steady-state activation after the first listener is ready and therefore leaves the startup race behind the exactly-one-server decision unexercised.
**Proposed fix:** Introduce an external launch barrier and start two host processes concurrently before either can reach Tauri setup, then identify the winner without assuming launch order and require exactly one activation callback, one `sidecar_spawned` record, one live sidecar PGID, and one listener.
**Regression-guard:** Make the live duplicate case record both launch timestamps and fail unless their setup windows overlap while the merged evidence still contains exactly one sidecar and listener.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**H3 — Missing metadata is counted as a clean post-run audit** (HIGH)

**Where:** `tools/desktop_lifecycle_spike/run_spike.py:223`
**Anchor:** `if meta is None:`
**What:** `_post_run_audit(None)` fabricates `pid_absent`, `process_group_empty`, `connect_refused`, and `clean` as true, and `crash-before-bound` takes exactly that path because the fixture crashes before writing `listener-meta.json`.
**Why it matters:** One of the eleven advertised fault cases performs no PID, PGID, canary, TCP, or `lsof` audit at all yet contributes zero to the published orphan/listener totals, so the "after every scenario" acceptance criterion and exact 0/0 result are not established.
**Proposed fix:** Move the injected crash to after process-group/canary/listener metadata is durably written but before the `bound` frame is emitted, and make absent metadata a failed/incomplete audit unless an alternate independently captured spawn identity is supplied.
**Regression-guard:** Replace the current assertion that `_post_run_audit(None)` is clean with a rejection test, then require the regenerated `crash-before-bound` evidence to show `metadata_present: true`, a same-group canary, PID/group absence, empty `lsof`, and refused TCP.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**H4 — Tauri binary provenance is hard-coded, not verified** (HIGH)

**Where:** `tools/desktop_lifecycle_spike/run_spike.py:462`
**Anchor:** `"host_is_tauri_binary": True,`
**What:** The harness unconditionally writes `host_is_tauri_binary: true` and hard-codes the three dependency versions while accepting arbitrary `--host` and `--fixture` paths, with no embedded or independently computed source/Cargo.lock digest tying the executed binaries to the reviewed tree.
**Why it matters:** A stale or substitute executable can receive the same positive Tauri/pin attestation, so the committed hashes prove only which opaque bytes ran, not the acceptance-critical claim that the real pinned no-window Tauri fixture represented this diff.
**Proposed fix:** Have the harness own the `cargo build --locked` step or require the host and fixture to emit build provenance containing a digest over `Cargo.toml`, `Cargo.lock`, `build.rs`, config, and Rust sources; derive the Tauri/version fields from validated build metadata and reject any mismatch before running a case.
**Regression-guard:** Add provenance-validator tests that reject a shell-script host, a stale source digest, and mismatched Cargo metadata, plus a positive test whose recorded digest recomputes from the current tracked spike sources.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**H5 — Review quality is at risk across 8,927 changed lines** (HIGH)

**Where:** no specific file
**Anchor:** `15 files changed, 8925 insertions(+), 2 deletions(-)`
**What:** The range changes 8,927 lines; 5,054 are the required Cargo lock and 1,751 are normalized live evidence, but the remaining surface still includes 1,637 authored Rust/Python lifecycle-code lines plus tests, configuration, and decision prose in one review unit.
**Why it matters:** This exceeds the canonical 400-LOC defect-detection threshold even after generated/reproducibility bulk is accounted for, making missed lifecycle, cleanup, and evidence bugs materially more likely; `allow_large_diff: true` authorizes scope but does not waive the mandatory adversary auto-finding.
**Proposed fix:** Preserve the lock and normalized evidence as isolated artifacts, split the authored implementation into reviewable protocol/fixture, supervisor, harness/audit, and test tranches, and rerun critique against those focused diffs before treating the GO as durable.
**Regression-guard:** Add a local review-size check based on `git diff --numstat` that reports lock/evidence separately and requires each authored implementation tranche to remain at or below 400 changed LOC unless the critic explicitly records the mandatory HIGH.
**Source critic:** milestone-adversary-critic
**Source axis:** Diff size

**M1 — Readiness contract errors bypass bounded cleanup** (MEDIUM)

**Where:** `tools/desktop_lifecycle_spike/src/main.rs:470`
**Anchor:** `wait_ready(&mut sidecar, bound.port, dea`
**What:** The normal path propagates a malformed readiness response with `?` and exits `run_cycle` without calling `force_group_stop`, as do several recorder/control-write errors after the child has spawned.
**Why it matters:** Those failures rely only on supervisor exit closing stdin and never perform the promised bounded TERM/KILL/reap sequence while the supervisor is still alive, which becomes an orphan risk if the sidecar is unresponsive to EOF.
**Proposed fix:** Put the owned sidecar behind one cleanup epilogue/guard that runs for every non-terminal return, records the original error, attempts authenticated stop when possible, escalates to group/direct-child termination as appropriate, and awaits the termination event before `handle.exit`.
**Regression-guard:** Add a malformed-ready fault plus an injected recorder/write failure and assert each path records bounded cleanup and leaves no PID, group, or listener.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**M2 — Parent-crash recovery never reacquires the same lock** (MEDIUM)

**Where:** `tools/desktop_lifecycle_spike/run_spike.py:296`
**Anchor:** `root = Path(tempfile.mkdtemp(prefix=f"{s`
**What:** Every scenario creates and then deletes a fresh application-data root, so the parent-crash case never immediately relaunches against the same `lifecycle.lock` after EOF cleanup.
**Why it matters:** The durable protocol selects the advisory file lock as its second exactly-one guard, but the run does not verify that crash cleanup releases that guard for the next supervisor rather than leaving recovery blocked or overlapping.
**Proposed fix:** Allow `_run_case` to receive a retained root, run `parent-crash`, then launch a normal recovery host against that identical root within the audit deadline and require successful lock acquisition with no overlap between the old and new sidecar identities.
**Regression-guard:** Record a `parent-crash-relaunch` live case whose evidence contains the old PID/group cleanup, the new sidecar's successful readiness, exactly one lock owner/listener at every sample, and final clean shutdown.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**M3 — Failed cases can leave the very orphan they detect** (MEDIUM)

**Where:** `tools/desktop_lifecycle_spike/run_spike.py:393`
**Anchor:** `shutil.rmtree(root)`
**What:** After a dirty audit or caught exception, `_run_case` removes the evidence root but performs no best-effort termination/reap of the known PID or PGID before continuing to the next case.
**Why it matters:** A regression in the cleanup logic can make the safety harness itself leave a fixture/canary or listener running on the workstation, contaminate later cases, and erase the metadata needed to clean it manually.
**Proposed fix:** Preserve the first dirty audit as the case result, then in `finally` validate the recorded identities, send bounded TERM/KILL to the known group or direct PID, re-audit cleanup without converting the case to pass, and only then remove the root.
**Regression-guard:** Use a helper process that ignores EOF/TERM to prove a deliberately failed case remains `ok: false` while the harness nevertheless kills/reaps it and leaves the scratch root removable.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**M4 — The wheel skip still packages the Python spike harness** (MEDIUM)

**Where:** `tests/test_wheel_packaging.py:65`
**Anchor:** `_SKIP_DIRS = frozenset(`
**What:** Adding `desktop_lifecycle_spike` to the data-file walk suppresses Cargo/config files from the guard but does not exclude `tools.desktop_lifecycle_spike` from setuptools' implicit-namespace discovery, which still finds and packages `run_spike.py` under the wheel's `tools*` include.
**Why it matters:** The milestone declares the whole subtree source-only and production integration out of scope, yet the shipped Python artifact gains a development-only process-control harness and the new test falsely documents that it is not wheel content.
**Proposed fix:** Add `exclude = ["tools.desktop_lifecycle_spike*"]` under `[tool.setuptools.packages.find]`, keep the non-Python data skip, and derive the guard from the actual discovered package list rather than only the filesystem walk.
**Regression-guard:** Build the wheel in the packaging test/opt-in wheel gate and assert no archive member starts with `tools/desktop_lifecycle_spike/`, including `run_spike.py`.
**Source critic:** milestone-adversary-critic
**Source axis:** Packaging boundary

**M5 — A failed process-secret inspection is reported clean** (MEDIUM)

**Where:** `tools/desktop_lifecycle_spike/run_spike.py:154`
**Anchor:** `return TOKEN_CANARY not in result.stdout`
**What:** `_secret_process_scan` ignores the `ps` return code and whether every requested live PID produced a row, so an unavailable, denied, or raced-away inspection with empty output returns true.
**Why it matters:** `process_secret_scan_clean` can claim the token was absent from argv/environment even when no argv/environment was inspected, weakening an explicit security acceptance result without leaving evidence of the failed probe.
**Proposed fix:** Request `pid=,command=`, require an acceptable zero exit status and one parsed row for every expected live PID, and record scan status/count separately from the token-match result so probe failure is never equivalent to absence.
**Regression-guard:** Mock `subprocess.run` with nonzero/empty and partial-PID outputs and require false, then retain a positive multi-PID case that contains no canary.
**Source critic:** milestone-adversary-critic
**Source axis:** Security / input handling

**M6 — Evidence discards lifecycle order and event multiplicity** (MEDIUM)

**Where:** `tools/desktop_lifecycle_spike/run_spike.py:338`
**Anchor:** `names = {str(item.get("event")) for item`
**What:** `_run_case` collapses the sequenced NDJSON records into a set of names, gates only on subset inclusion plus the sidecar-spawn count, and commits the sorted set while deleting the raw records.
**Why it matters:** Out-of-order, duplicated, or unexpected transitions can still produce `ok: true`, and the durable evidence cannot substantiate the ADR's exact serialized lifecycle or its claim of one duplicate activation callback.
**Proposed fix:** Validate consecutive recorder sequence numbers and an exact per-scenario state-machine trace, retain a normalized ordered event list with public counts in the evidence, and fail on duplicate/unexpected transitions unless the scenario explicitly permits them.
**Regression-guard:** Feed the validator a reordered normal trace, duplicate activation, duplicate shutdown, and omitted intermediate state and require each to fail while the canonical eleven traces pass.
**Source critic:** milestone-adversary-critic
**Source axis:** Test discipline

**M7 — Output secret scans lose matches across event chunks** (MEDIUM)

**Where:** `tools/desktop_lifecycle_spike/src/main.rs:193`
**Anchor:** `fn output_is_clean(&self, bytes: &[u8]) `
**What:** `output_is_clean` scans each raw Tauri stdout/stderr event independently, so the canary prefix or full token split across two pipe-reader events is absent from both individual byte slices and passes.
**Why it matters:** Pipe/event boundaries are not message boundaries, and a split diagnostic write can leak the startup secret while both the host scan and external harness remain green because Tauri consumes rather than forwards sidecar output.
**Proposed fix:** Maintain separate streaming scanners for stdout and stderr that retain the final `TOKEN_CANARY.len() - 1` bytes between events, scan the combined tail plus new bytes, and clear those tails only after termination.
**Regression-guard:** Split the canary at every byte boundary across two synthetic events and require every split to fail, with clean adjacent chunks retained as controls.
**Source critic:** milestone-adversary-critic
**Source axis:** Security / input handling

**L1 — The scope-checkpoint commit subject exceeds the limit** (LOW)

**Where:** no specific file
**Anchor:** `feat(tools): partial — milestone desktop-distribution-spike-3 scope exceeded`
**What:** Commit `830112e` uses a 63-character subject after the type prefix and describes a state (`partial`) rather than an imperative action, exceeding the repository's 50-character conventional-subject rule.
**Why it matters:** This is minor history/readability drift, but the scope checkpoint is the hardest commit in the range to scan in logs and is the one most likely to be used as precedent for future mid-flight commits.
**Proposed fix:** If the unpushed implementation history is intentionally rebuilt for the review split, shorten it to an imperative subject such as `feat(tools): checkpoint Tauri lifecycle spike`; otherwise defer history rewriting and enforce the limit on future commits with a local commit-message check.
**Regression-guard:** Not required at LOW; a commit-message test should count only the text after `<type>(<scope>): ` and reject values over 50 characters.
**Source critic:** milestone-adversary-critic
**Source axis:** Commit hygiene

## What was done well

- The crate pins Tauri 2.11.5, shell 2.3.5, single-instance 2.4.3, and tauri-build 2.6.3 exactly; Cargo.lock v4 contains 477 packages, with all 476 external packages coming from the crates.io registry with checksums and no git/fork source.
- The spike stays outside production integration: the config has no windows and no active bundle, the target-triple sidecar is staged beside the host, the fixture itself retains `127.0.0.1:0`, and no MCP schema, prompt/cache pin, frontend, Node, or server source changed.
- Secret handling in the authored path is disciplined: 256 random bits come from `getrandom`, the sidecar environment is cleared to one non-secret data-root variable, argv contains no capability, stdin carries the bootstrap/shutdown token, and no canary appears in committed evidence or prose.
- The normal and forced paths use the right macOS building blocks once the process group exists: stdin EOF is the supervisor-death lease, `setpgid` covers the direct fixture plus canary, TERM escalates to KILL, and termination events are awaited.
- The ADR clearly limits the proof to a cooperative direct child, explicitly excludes `setsid()` escapees and the macOS 14 floor, preserves the 35-second production grace requirement, and gives a concrete native-guardian fallback rather than weakening the no-orphan contract.
- The normalized evidence is internally consistent where it has subjects: it contains eleven named fault cases and exactly thirty cycle objects, all 41 per-run digests are unique, the aggregate digest recomputes exactly, and the reported 377.372/390.912/406.493 ms latency figures match the stored values.
- Test discipline is substantial: Rust unit tests cover framing/token/loopback basics, the Python guard covers the declared matrix and committed totals, and my focused rerun produced 27 passed and 2 expected skips; `cargo fmt --check` and focused Ruff also pass.
- External-write and one-writer boundaries are clean: the range changes no roadmap/state progress file, adds no executable push/publish/deploy path, leaves `main` ahead of `origin/main`, and records the future push as authorization-gated prose only.
- All four commit objects carry `gpgsig` blocks and the mandatory Codex co-author trailer, no `--no-verify`/`--no-gpg-sign` bypass appears, and only the checkpoint subject has the low-severity length defect recorded above.

Severity counts: C0 H5 M7 L1

## Recommended rectification order

H1, H3, H2, H4, H5, M1, M3, M5, M7, M6, M2, M4, L1
