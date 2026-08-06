# desktop-distribution-e2 — Native launch reaches a healthy MCP session

**Type:** value
**Estimated size:** M

## Outcome

A development-signed desktop shell starts exactly one bundled server, waits on readiness, opens the existing console, serves MCP through the existing loopback contract, reports failures, and shuts down without an orphan.

## Scope

In scope:
- Cross-platform desktop workspace with macOS as the first target.
- Fixture sidecar and real-server lifecycle integration.
- Single-instance ownership, dynamic loopback endpoint, readiness, shutdown, and crash diagnostics.
- One end-to-end MCP smoke without tool-schema changes.

Out of scope:
- A new SPA or rewritten operator console.
- Production signing/notarization and auto-update.
- Public Windows/Linux packages.

## Stories under this epic

- desktop-distribution-m3 — Define the desktop/server contract.
- desktop-distribution-m4 — Ship the lifecycle walking skeleton.

## Specialist review (suggested)

`mcp-protocol-reviewer` and `security-reviewer`.

## INVEST notes

Dependency on desktop-distribution-e1 is explicit. The result is independently demoable against a fixture sidecar and testable through lifecycle and MCP smoke suites.

## Roadmap reference

Generated from `plans/desktop-distribution-roadmap.md`; see it for OKRs, assumptions, sequencing, and scope exclusions.
