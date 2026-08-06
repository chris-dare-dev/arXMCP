# desktop-distribution-m3 — Define the desktop/server contract

**Parent epic:** desktop-distribution-e1, desktop-distribution-e2
**Complexity:** M

## Description

Add the cross-platform desktop workspace and a fixture sidecar, then define the versioned launch manifest exchanged between supervisor and server: executable identity, compatibility version, data root, dynamic loopback endpoint, startup token, health/readiness URLs, log location, and shutdown semantics.

## Acceptance criteria

- [ ] `apps/desktop/README.md` states supported boundaries, development commands, and why macOS is a target rather than a fork.
- [ ] A schema-versioned manifest rejects unknown incompatible major versions and tolerates documented compatible minor additions.
- [ ] Secrets and startup tokens are never accepted in command-line arguments or persisted in logs.
- [ ] A fixture sidecar lets desktop lifecycle tests run without loading BGE-M3 or a corpus.
- [ ] Contract fixtures are byte-stable and testable from both Rust and Python.

## Verification

- [ ] Project check command passes: `make test`.
- [ ] Rust and Python contract conformance fixtures produce identical canonical payloads.

## Dependencies

desktop-distribution-e2, desktop-distribution-m1, and desktop-distribution-spike-3.

## Notes

Suggested review: `mcp-protocol-reviewer`, `security-reviewer`, `determinism-reviewer`.

## Roadmap reference

See `plans/desktop-distribution-roadmap.md`. To execute: `milestone-pipeline desktop-distribution-m3`.
