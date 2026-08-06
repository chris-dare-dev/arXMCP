# desktop-distribution-m4 — Ship the lifecycle walking skeleton

**Parent epic:** desktop-distribution-e2
**Complexity:** M

## Description

Connect the desktop supervisor to the relocatable server and existing `/ui/`. The slice owns a single instance, selects a loopback endpoint without widening the bind boundary, renders starting/ready/degraded/failed states, performs one MCP smoke request, and tears down cleanly after normal or forced exits.

## Acceptance criteria

- [ ] Given no running instance, when the app launches, then exactly one child server reaches health/readiness and the existing console renders in the desktop window.
- [ ] Given a ready instance, when an MCP smoke request crosses the configured local endpoint, then the normal MCP response is returned without schema changes.
- [ ] Given a second launch, then it activates the existing app or exits clearly without starting another server.
- [ ] Given shutdown, startup timeout, sidecar crash, or supervisor crash, then bounded cleanup leaves no child process or listener and writes redacted diagnostics.
- [ ] Lifecycle tests assert loopback-only binding and run 30 fixture-sidecar cycles without an orphan.

## Verification

- [ ] Project check command passes: `make test`.
- [ ] Desktop lifecycle and MCP smoke suites pass on a clean supported Mac.

## Dependencies

desktop-distribution-e2, desktop-distribution-m2, and desktop-distribution-m3.

## Notes

Suggested review: `mcp-protocol-reviewer`, `security-reviewer`.

## Roadmap reference

See `plans/desktop-distribution-roadmap.md`. To execute: `milestone-pipeline desktop-distribution-m4`.
