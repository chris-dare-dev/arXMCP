# Rectify summary — desktop-distribution-spike-3

- **Rect commit:** `8d87a15764029aaac0524525a7131b3c040a5d2b` —
  `rect(desktop-distribution-spike-3): close H1-H4,H6-H9`
- **Fixed (14):** H1, H2, H3, H4, H6, H7, H8, H9, M4, M5, M6,
  M7, M9, M11.
- **Deferred (7):** H5, M1, M2, M3, M8, M10, L1.
- **Invalidated:** none; every HIGH anchor re-verified against live code.
- **External write:** `git push origin main` completed with per-event user
  authorization (`9a832b8..8d87a15`).

## Fixed

- **H1 — pre-PGID timeout:** negative-PGID `ESRCH` now falls back to the
  retained direct PID and still awaits the Tauri termination event. The live
  startup-timeout case records `direct_sigterm` and an independently clean PID
  audit without pretending a process group existed.
- **H2/H8 — duplicate startup race:** both hosts wait on one external barrier.
  The run showed that Tauri activation alone does not close the zero-delay
  race, so the researched native `supervisor.lock` fallback selects one owner
  before sidecar setup. Evidence requires overlapping startup, a clean loser,
  one `sidecar_spawned` transition, one listener, and one final owner.
- **H3/H7 — vacuous pre-bound audit:** crash-before-bound now writes durable
  PID, PGID, canary, and listener metadata before an abrupt abort. Missing
  metadata is unclean unless a `sidecar_spawned` record supplies a direct PID
  that can be independently audited.
- **H4/M9 — binary provenance:** `build.rs` embeds a SHA-256 over the tracked
  manifest, lockfile, configuration, harness, and Rust sources in both Mach-O
  binaries. The harness validates binary roles, exact dependency pins, and the
  source digest before any case; the repository gate recomputes the digest.
- **H6 — orderly crash faults:** both crash modes now call `abort()` after the
  group and canary exist. Rust `Drop` cannot perform the cleanup; the host
  explicitly signals and audits the residual group after direct-child exit.
- **H9/M4 — wheel leakage:** setuptools excludes
  `tools.desktop_lifecycle_spike*`. Static namespace discovery and the real
  contents-only wheel gate both prove the process-control harness is absent.
- **M5/M11 — fail-open probes:** process-secret scans require a successful row
  for every requested live PID. Listener audits distinguish the documented
  `lsof` no-match status from execution/permission errors and retain status plus
  a redacted stderr digest.
- **M6/M7 — evidence fidelity:** committed results retain exact ordered event
  traces with sequence/multiplicity validation. Separate streaming stdout and
  stderr scanners retain cross-event tails and reject every split canary.

## Deferred

- **H5 — review-size signal:** the user explicitly approved the large diff.
  The lockfile and normalized evidence remain isolated, and rewriting four
  signed local commits solely to repartition the same reviewed code would be a
  destructive history operation. Risk was mitigated by two independent
  critics and full Rust, live, wheel, and repository gates; the finding remains
  honestly deferred rather than invalidated.
- **M1 — universal cleanup epilogue:** the cited malformed-readiness path now
  performs bounded cleanup, but a single lifecycle-owner guard covering every
  recorder/control-write failure exceeds the MEDIUM rectification cap.
- **M2/M10 — same-root recovery/contention:** immediate same-root relaunch and
  standalone fixture-lock contention remain production-integration follow-up.
  The simultaneous host-level supervisor-lock contention itself is now live.
- **M3 — failed-case janitor:** a failure-preserving best-effort group janitor
  needs a dedicated hostile-helper test and exceeds the MEDIUM cap.
- **M8 — ordinary `ExitRequested`:** platform exit-event interception belongs
  with the real desktop shell; this fixture still proves authenticated internal
  shutdown and parent-crash EOF behavior.
- **L1 — long checkpoint subject:** signed history is not rewritten for a LOW
  log-style issue; future scope-stop subjects should use the shorter form.

## Regression coverage

- `tests/test_desktop_lifecycle_spike.py` covers missing-metadata failure,
  ordered traces, failed process/listener probes, current-source provenance,
  concurrent arbitration, direct-PID termination, and abrupt-crash group
  cleanup.
- `tests/test_wheel_packaging.py` verifies setuptools namespace exclusion.
- `tools/wheel_install_check.py --mode contents` rejects any actual wheel entry
  under `tools/desktop_lifecycle_spike/`.
- Rust unit coverage checks every cross-chunk canary split in addition to the
  existing protocol, token, bind, sidecar-name, and readiness contracts.

## Verification

- `cargo fmt --check`: **PASS**.
- `cargo test --locked --offline --all-targets`: **PASS — 9 passed**.
- `cargo clippy --locked --offline --all-targets -- -D warnings`: **PASS**.
- Rectified live matrix: **GO — 11/11 scenarios and 30/30 cycles**, with
  **0 orphan groups, 0 residual listeners, 0 secret failures**; aggregate
  SHA-256 `dfc11ca3c99b9a8c4a19e237e03e257a4fef52d1052ef41f6cb7022a3ec96ab9`.
- Focused Python lifecycle/packaging gate: **PASS — 31 passed, 2 skipped**.
- `tools/wheel_install_check.py --mode contents`: **PASS — 190 wheel entries,
  23 required files present, forbidden lifecycle prefix absent**.
- `make test PYTHON=.venv/bin/python`: **PASS — Ruff clean; 5,033 passed,
  43 skipped, 1 xfailed**.
- Findings register: **no open findings**.

The first concurrent live attempts intentionally remained NO-GO: they exposed
an inter-process NDJSON write race, a live-reader partial-tail race, and Tauri's
zero-delay activation gap. Each was fixed before the committed GO evidence was
regenerated; no failed evidence was promoted.
