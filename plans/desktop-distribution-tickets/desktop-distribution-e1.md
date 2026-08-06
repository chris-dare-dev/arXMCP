# desktop-distribution-e1 — Portable runtime contract proven

**Type:** enabler
**Estimated size:** M

## Outcome

The installed server starts from an arbitrary read-only application location, routes every mutation beneath one explicit application-data root, exposes a versioned supervisor contract, and preserves wheel/container/CLI compatibility.

## Scope

In scope:
- Central application-path resolver and traversal validation.
- Installed-wheel relocation and write-confinement tests.
- Versioned desktop/server launch contract.
- Compatibility with current CLI, wheel, Docker, Compose, and explicit path overrides.

Out of scope:
- Desktop visual design and onboarding.
- macOS signing, notarization, and installer production.
- Repository extraction or package renaming.

## Stories under this epic

- desktop-distribution-m1 — Centralize application paths.
- desktop-distribution-m2 — Make the installed server relocatable.
- desktop-distribution-m3 — Define the desktop/server contract.

## Specialist review (suggested)

`security-reviewer` and `determinism-reviewer`.

## INVEST notes

Independently testable through relocation and compatibility fixtures; no prerequisite epic. Negotiable implementation, valuable prerequisite, estimable, small enough for the M band, and testable.

## Roadmap reference

Generated from `plans/desktop-distribution-roadmap.md`; see it for OKRs, assumptions, sequencing, and scope exclusions.
