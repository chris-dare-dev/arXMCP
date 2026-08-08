# Windows lifecycle portability decision

Status: **UNCERTAIN — native harness ready; product run blocked by one path defect**
Decision date: 2026-08-08
Roadmap: `plans/windows-distribution/roadmap.yaml`
Tracking issue: https://github.com/chris-dare-dev/arXMCP/issues/410
## Decision

Reuse the shared desktop v1 wire contract, application-data layout, and lifecycle state machine on Windows. Implement Windows process-tree ownership as a platform adapter based on a native Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`; do not create a Windows-only protocol or lifecycle fork.

The external-observation harness is suitable for the product proof, but the formal spike remains `UNCERTAIN` until one fresh complete 33-case run executes against the real Rust fixture. Dry-run evidence proves the harness, not the product.

## Evidence

- The repaired external-observation dry run passed 33/33 scenario repetitions with zero missing observations and zero failed exit-code queries.
- Observed dry-run exits matched the contract: normal `0`, duplicate contender `73`, malformed bound `43`, crash before bound `41`, and crash after readiness `42`.
- The dry Launch/Bound bridge verified the child image and completed launch, health, readiness, shutdown, and exit-code capture.
- The formal product run had zero cases because the initial native link lacked `kernel32.lib`; consequently Job Object cleanup, shared behavior, and protocol-fork counts remained unmeasured.
- After the official Windows 11 SDK component was installed, the locked Rust workspace built and all 8 Rust contract tests passed.
- The native Python contract run then passed 25 tests and failed 2 at launch validation. Rust canonicalizes the prepared data root to an extended-length `\\?\C:\...` path, while the launch value remains a conventional `C:\...` path; bytewise comparison rejects two equivalent Windows paths before the fixture emits `Bound`.

## Required implementation and promotion gate

1. Normalize both sides of the Windows data-root comparison to one canonical representation without changing the serialized v1 contract.
2. Rebuild the locked fixture and require the Rust workspace tests plus `tests/test_desktop_contract.py` to pass without failures or skips attributable to the live sidecar.
3. Run `windows_lifecycle_probe.py --mode complete` once for all 11 scenarios and three repetitions against the freshly built fixture.
4. Require exactly 33 complete cases, zero Job Object cleanup failures, zero shared behavior/layout failures, and zero required Windows-only protocol forks.
5. Preserve raw process, socket, protocol, listener, and queried-exit evidence from that single fresh generation; do not mix dry-run, WSL, macOS, or earlier-attempt observations into product fields.

Canonical local evidence: `.claude/notes/spikes/windows-distribution-spike-1/`.
