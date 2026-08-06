# Desktop Distribution and macOS Release — Roadmap

**Slug:** `desktop-distribution`
**Created:** 2026-08-06T01:56:15Z
**Status:** complete

<!--
This roadmap is itself the state. Re-invoking the `roadmap` skill on
this file resumes from the first un-populated phase. Sections below
contain `{{TOKEN}}` placeholders until their phase runs.

Phases:
  1. REFINE     — How-Might-We, sharpening questions, assumptions, OKR, Won't list
  2. DECOMPOSE  — technique, epics, INVEST, specialist suggestions
  3. SEQUENCE   — MoSCoW, RICE, Now/Next/Later, spike lane, Now-lane milestones
  4. MATERIALIZE — validation results, optional GitHub bundle, next-step handoff
-->

---

## Phase 1 — Refine

### How Might We

How might we make arXMCP installable and operable as a trustworthy native desktop product for a macOS researcher without coupling the core server to Apple-only assumptions or weakening its local-first and loopback-only guarantees?

### Sharpening questions answered

1. **Who is the first desktop user?** — A single researcher or operator on a personal Mac who wants arXMCP to launch, remain healthy, expose MCP locally, and present the existing operator console without managing Python processes manually.
2. **Is macOS a separate product?** — No. macOS is the first release target for a shared desktop supervisor; Windows and Linux should reuse the same supervisor/server contract when their packaging lanes begin.
3. **What should be reused?** — The existing `arxmcp-server`, `arxmcp-shim`, Streamable HTTP endpoint, readiness probes, and Jinja2+htmx `/ui/` console remain the product core. The desktop layer owns installation, lifecycle, native integration, and diagnostics rather than rewriting retrieval or ingestion.
4. **What does “production-grade” mean for this initiative?** — A signed and notarized installer, least-privilege runtime, deterministic release inputs, portable application-data paths, safe upgrades and rollback, observable lifecycle failures, documented support boundaries, and repeatable release gates.
5. **Does this require a repository split now?** — No. The current Python wheel and container package tightly coupled source trees together. The desktop code begins in the monorepo behind a versioned boundary and becomes extractable only if it later gains an independent release and ownership lifecycle.

### Assumptions

- `[MUST]` The Python server, native dependencies, model-loading path, and operator-console assets can be bundled into a relocatable macOS application without relying on the repository checkout or a pre-existing Python installation.
- `[MUST]` Every writable runtime path can be routed beneath an explicit application-data root while preserving current CLI, wheel, container, and test behavior.
- `[MUST]` A desktop supervisor can enforce one loopback-only server instance, authenticated lifecycle control, bounded startup/shutdown, crash recovery, and no orphan child processes.
- `[MUST]` Apple Developer ID signing and notarization credentials can be provisioned for the release pipeline before the public beta gate.
- `[SHOULD]` Tauri 2 plus a bundled Python sidecar is a maintainable cross-platform shell with materially less duplicated UI work than separate native applications.
- `[SHOULD]` Direct Developer ID distribution outside the Mac App Store is acceptable for the first production release.
- `[SHOULD]` macOS 14+ on Apple Silicon is an acceptable initial support floor; universal or Intel packaging can follow measured user demand.
- `[MIGHT]` Automatic in-app updates are needed for v1 rather than a signed, user-initiated update workflow with explicit rollback.

### Objective

Deliver a dependable desktop form of arXMCP that feels native to install and operate on macOS, preserves the security and retrieval behavior of the server, and establishes an honest cross-platform application boundary for later Windows and Linux releases.

### Key Results

1. By the macOS v1 release, a non-developer can install the release artifact on a clean supported Mac and launch it without Terminal, Python, Homebrew, or a Gatekeeper bypass; signature, hardened-runtime, and notarization verification all pass.
2. By the macOS beta gate, 30 automated launch → ready → MCP request → quit cycles complete with zero orphan server processes, zero non-loopback listeners, and actionable diagnostics for forced startup and crash failures.
3. By the macOS v1 release, clean install, upgrade, failed-update recovery, rollback, and uninstall-preserving-data scenarios pass without corpus, notebook, configuration, or backup loss.
4. At every release candidate, the existing project test/lint gate and the desktop packaging/E2E/security gates pass, with zero unresolved CRITICAL or HIGH findings in the desktop threat-model review.
5. By the macOS v1 release, the desktop/server compatibility contract is versioned and a Windows/Linux packaging feasibility smoke demonstrates that no macOS-only assumption entered the shared supervisor protocol.

### Won't (explicit out-of-scope)

- Mac App Store distribution in the first release cycle.
- A cloud-hosted, multi-tenant, or remotely reachable arXMCP service.
- A rewrite of the existing Jinja2+htmx operator console as a SPA.
- A macOS-only fork of the server or an immediate split into multiple source repositories.
- Public Windows or Linux installers before the macOS v1 gates are met.
- Bundling or automatically downloading the full 200K-paper corpus as part of the application installer.
- Mobile applications or remote administration from another device.

---

## Phase 2 — Decompose

### Technique

Vertical slicing with explicit enabler stories. Each value epic ends in an operator-demonstrable release gate, while portable paths and bundle contracts are isolated as prerequisites rather than a long horizontal “desktop infrastructure” phase.

### Epics

#### desktop-distribution-e1 — Portable runtime contract proven

- **Type:** enabler
- **Specialist suggestion:** `security-reviewer` and `determinism-reviewer` — see `.agents/skills/roadmap/references/specialist-contracts.md`.
- **Outcome:** The installed server starts from an arbitrary read-only application location, routes every mutation beneath one explicit application-data root, exposes a versioned supervisor contract, and preserves wheel/container/CLI compatibility.
- **Estimated size:** M
- **INVEST check:** I clean, N clean, V clean, E clean, S clean, T clean; it is independently testable through relocation and compatibility fixtures.
- **Dependencies:** none
- **Won't conflict check:** none

#### desktop-distribution-e2 — Native launch reaches a healthy MCP session

- **Type:** value
- **Specialist suggestion:** `mcp-protocol-reviewer` and `security-reviewer` — see `.agents/skills/roadmap/references/specialist-contracts.md`.
- **Outcome:** A development-signed desktop shell starts exactly one bundled server, waits on readiness, opens the existing console, serves MCP through the existing loopback contract, reports failures, and shuts down without an orphan.
- **Estimated size:** M
- **INVEST check:** I borderline because it consumes e1’s contract; N/V/E/S/T clean. Dependency is explicit and the shell remains independently demoable against a fixture sidecar.
- **Dependencies:** desktop-distribution-e1
- **Won't conflict check:** none

#### desktop-distribution-e3 — First-run operator reaches ready state safely

- **Type:** value
- **Specialist suggestion:** `security-reviewer` — see `.agents/skills/roadmap/references/specialist-contracts.md`.
- **Outcome:** A new operator can choose storage, understand disk/model requirements, initialize or adopt local data, register the MCP shim, and reach a truthful ready/degraded state without Terminal use or silent network/model activity.
- **Estimated size:** M
- **INVEST check:** I borderline on e1/e2 lifecycle APIs; N/V/E/S/T clean. The first-run journey is separately testable with clean-home fixtures and declined/cancelled paths.
- **Dependencies:** desktop-distribution-e1, desktop-distribution-e2
- **Won't conflict check:** none; full-corpus download remains explicitly excluded

#### desktop-distribution-e4 — macOS artifact passes platform trust gates

- **Type:** value
- **Specialist suggestion:** `security-reviewer` and `determinism-reviewer` — see `.agents/skills/roadmap/references/specialist-contracts.md`.
- **Outcome:** A pinned, reproducible macOS application bundle and installer are Developer ID signed, hardened, notarized, stapled, checksum/SBOM accompanied, Gatekeeper accepted, and verified on a clean supported Apple Silicon Mac.
- **Estimated size:** L
- **INVEST check:** I borderline on e1/e2 bundle inputs and external Apple credentials; N/V/E/S/T clean. Credential provisioning is an explicit discovery item and release verification is automated.
- **Dependencies:** desktop-distribution-e1, desktop-distribution-e2
- **Won't conflict check:** none; direct distribution only, not Mac App Store

#### desktop-distribution-e5 — Upgrades and failures preserve operator data

- **Type:** value
- **Specialist suggestion:** `security-reviewer` and `determinism-reviewer` — see `.agents/skills/roadmap/references/specialist-contracts.md`.
- **Outcome:** Version upgrades, rejected or interrupted updates, server crashes, rollback, and uninstall preserve or intentionally remove the correct state, with preflight backup, schema compatibility checks, redacted diagnostics, and a tested recovery path.
- **Estimated size:** M
- **INVEST check:** I borderline because it requires a real packaged build; N/V/E/S/T clean. Data-safety scenarios form an independently executable release suite.
- **Dependencies:** desktop-distribution-e1, desktop-distribution-e2, desktop-distribution-e4
- **Won't conflict check:** none; automatic background update remains negotiable

#### desktop-distribution-e6 — macOS v1 is supportable and cross-platform-ready

- **Type:** value
- **Specialist suggestion:** `mcp-protocol-reviewer` and `security-reviewer` — see `.agents/skills/roadmap/references/specialist-contracts.md`.
- **Outcome:** The release candidate passes lifecycle, MCP, accessibility, upgrade, security, and support-readiness gates; release/runbook ownership is explicit; and Windows/Linux fixture builds validate the shared protocol without promising public installers.
- **Estimated size:** M
- **INVEST check:** I borderline because it is the integration/release gate; N/V/E/S/T clean. Its scope is bounded to acceptance, support, and cross-platform feasibility rather than new product features.
- **Dependencies:** desktop-distribution-e2, desktop-distribution-e3, desktop-distribution-e4, desktop-distribution-e5
- **Won't conflict check:** none; Windows/Linux public releases remain outside this cycle

---

## Phase 3 — Sequence

### MoSCoW assignment

- **Must** (57.1% of total effort): desktop-distribution-e1, desktop-distribution-e2, desktop-distribution-e4
- **Should**: desktop-distribution-e3, desktop-distribution-e5
- **Could**: desktop-distribution-e6
- **Won't (this cycle)**: Mac App Store distribution, public Windows/Linux installers, cloud or remote operation, full-corpus bundling

### RICE ranking — Musts

| ID | Reach | Impact | Confidence | Effort | Score |
|---|---:|---:|---:|---:|---:|
| desktop-distribution-e2 | 1 | 3.00 | 60% | 1.50 | 1.2 |
| desktop-distribution-e1 | 1 | 2.00 | 75% | 1.50 | 1.0 |
| desktop-distribution-e4 | 1 | 3.00 | 50% * | 3.00 | 0.5 |

_`*` indicates Confidence defaulted to 50%; credential/notarization evidence is scheduled in the spike lane._

### Now / Next / Later

- **Now** (fully spec'd, in-flight or next-up): desktop-distribution-e1, desktop-distribution-e2
- **Next** (shaped, awaiting capacity): desktop-distribution-e4, desktop-distribution-e3, desktop-distribution-e5
- **Later** (outcome-only, low-confidence horizon): desktop-distribution-e6

### Spike / discovery lane

- `desktop-distribution-spike-1` — Build a disposable relocatable macOS sidecar containing the installed wheel, templates, native libraries, and model-loading code; launch it from a read-only path with no ambient Python, record size/startup/missing-library findings, and choose the bundling mode in an ADR (≤ 3 days, validates `[MUST]`: relocatable bundled runtime).
- `desktop-distribution-spike-2` — Inventory runtime writes and prototype one explicit application-data root against source, wheel, and container fixtures; enumerate compatibility aliases and the migration sequence for remaining hard-coded defaults (≤ 3 days, validates `[MUST]`: writable paths can be routed safely).
- `desktop-distribution-spike-3` — Exercise Tauri sidecar spawning, single-instance ownership, dynamic loopback-port handoff, graceful stop, forced kill, parent crash, and orphan detection on macOS; record the lifecycle protocol and fallback if Tauri cannot enforce it (≤ 3 days, validates `[MUST]`: safe single-instance supervisor lifecycle).
- `desktop-distribution-spike-4` — Provision or verify the Apple Developer account path and complete a throwaway `codesign` → hardened runtime → `notarytool` → staple → Gatekeeper dry run without committing credentials (≤ 3 days, validates `[MUST]`: signing and notarization credentials are available).

### Milestones — Now lane

<!--
Each Now-lane milestone is its own H3 below. Heading format is
`### <slug>-mN — Title` exactly — milestone-pipeline's init-state.sh
greps for this. Do not change it.
-->

### desktop-distribution-m1 — Centralize application paths

**Description.** Introduce a single typed application-path resolver rooted at `ARXMCP_DATA_DIR`, with explicit paths for corpus, indices, notebooks, caches, logs, backups, and temporary state. Preserve the existing `var/arxmcp` source-checkout default while making installed-runtime behavior independent of the working directory.

**Acceptance criteria.**
- [ ] One module owns derivation and validation of every runtime root consumed by the server and desktop contract.
- [ ] Relative, absolute, missing, read-only, symlink, Unicode, and whitespace-containing roots have deterministic tests on supported Python platforms.
- [ ] No application path can escape the configured root through `..`, symlink traversal, or inconsistent resolution.
- [ ] Existing environment-variable values and source-checkout defaults remain backward compatible.
- [ ] `make test` exits 0.

**Dependencies.** desktop-distribution-e1, desktop-distribution-spike-2

**Complexity.** M

**Specialist suggestion.** `security-reviewer`, `determinism-reviewer`

### desktop-distribution-m2 — Make the installed server relocatable

**Description.** Route the server, notebook registry, retrieval stores, and operational outputs through the centralized path contract for installed-runtime flows. Add a wheel relocation smoke that starts in bootstrap mode from an arbitrary working directory and proves no write lands beside the application or checkout.

**Acceptance criteria.**
- [ ] The installed `arxmcp-server` starts with a temporary application-data root from outside the repository and reaches `/healthz` in bootstrap mode.
- [ ] Notebook, cache, log, corpus-marker, and settings writes observed in the smoke remain beneath that root.
- [ ] The wheel, Docker/Compose, `make up`, and existing explicit per-store overrides retain their current behavior.
- [ ] A regression test fails if an installed-runtime code path derives a writable location from `cwd` or repository root.
- [ ] `make test` exits 0.

**Dependencies.** desktop-distribution-e1, desktop-distribution-m1, desktop-distribution-spike-1

**Complexity.** M

**Specialist suggestion.** `security-reviewer`, `determinism-reviewer`

### desktop-distribution-m3 — Define the desktop/server contract

**Description.** Add the cross-platform desktop workspace and a fixture sidecar, then define the versioned launch manifest exchanged between supervisor and server: executable identity, compatibility version, data root, dynamic loopback endpoint, startup token, health/readiness URLs, log location, and shutdown semantics.

**Acceptance criteria.**
- [ ] `apps/desktop/README.md` states supported boundaries, development commands, and why macOS is a target rather than a fork.
- [ ] A schema-versioned manifest rejects unknown incompatible major versions and tolerates documented compatible minor additions.
- [ ] Secrets and startup tokens are never accepted in command-line arguments or persisted in logs.
- [ ] A fixture sidecar lets desktop lifecycle tests run without loading BGE-M3 or a corpus.
- [ ] Contract fixtures are byte-stable and testable from both Rust and Python.

**Dependencies.** desktop-distribution-e2, desktop-distribution-m1, desktop-distribution-spike-3

**Complexity.** M

**Specialist suggestion.** `mcp-protocol-reviewer`, `security-reviewer`, `determinism-reviewer`

### desktop-distribution-m4 — Ship the lifecycle walking skeleton

**Description.** Connect the desktop supervisor to the relocatable server and existing `/ui/`. The slice owns a single instance, selects a loopback endpoint without widening the bind boundary, renders starting/ready/degraded/failed states, performs one MCP smoke request, and tears down cleanly after normal or forced exits.

**Acceptance criteria.**
- [ ] Given no running instance, when the app launches, then exactly one child server reaches health/readiness and the existing console renders in the desktop window.
- [ ] Given a ready instance, when an MCP smoke request crosses the configured local endpoint, then the normal MCP response is returned without schema changes.
- [ ] Given a second launch, then it activates the existing app or exits clearly without starting another server.
- [ ] Given shutdown, startup timeout, sidecar crash, or supervisor crash, then bounded cleanup leaves no child process or listener and writes redacted diagnostics.
- [ ] Lifecycle tests assert loopback-only binding and run 30 fixture-sidecar cycles without an orphan.

**Dependencies.** desktop-distribution-e2, desktop-distribution-m2, desktop-distribution-m3

**Complexity.** M

**Specialist suggestion.** `mcp-protocol-reviewer`, `security-reviewer`

---

## Phase 4 — Materialize

### Validation

- `validate-roadmap.py`: pass
- Must-cap: 57.1% (≤ 60%)
- All Now-lane milestones have AC: yes
- Slug format valid: yes

### GitHub delivery system

The separately authorized materialization workflow completed on 2026-08-05:

- Program tracker: [#398](https://github.com/chris-dare-dev/arXMCP/issues/398)
- Release-gate milestones: [Desktop 0](https://github.com/chris-dare-dev/arXMCP/milestone/13), [Desktop 1](https://github.com/chris-dare-dev/arXMCP/milestone/14), [Desktop 2](https://github.com/chris-dare-dev/arXMCP/milestone/15), [Desktop 3](https://github.com/chris-dare-dev/arXMCP/milestone/16), and [Desktop 4](https://github.com/chris-dare-dev/arXMCP/milestone/17)
- Delivery project: [arXMCP - Delivery](https://github.com/users/chris-dare-dev/projects/3), reused instead of creating a second project
- Initiative views: [Portfolio](https://github.com/users/chris-dare-dev/projects/3/views/13), [Now](https://github.com/users/chris-dare-dev/projects/3/views/14), [Release gates](https://github.com/users/chris-dare-dev/projects/3/views/15), and [Discovery](https://github.com/users/chris-dare-dev/projects/3/views/16)
- Machine-readable reconciliation map: `plans/desktop-distribution-tickets/github-object-map.json`

Fifteen open issues were created: four time-boxed spikes, six epics, four implementation-ready Now milestones, and the program tracker. Every item is in the Delivery project with Status, Lane, Priority, Size, and release-gate milestone populated.

### Local ticket bundle

Bundle written to `plans/desktop-distribution-tickets/`:
- `desktop-distribution-e1.md` — Now-lane portable-runtime epic body
- `desktop-distribution-e2.md` — Now-lane lifecycle epic body
- `desktop-distribution-m1.md` through `desktop-distribution-m4.md` — implementation-ready story bodies
- `create-tickets.sh` — reconciled receipt that exits without creating duplicates now that the issues exist

### Next step

First Now-lane milestone: `desktop-distribution-m1`. To execute it end-to-end, run:

    milestone-pipeline desktop-distribution-m1

The roadmap skill does not invoke milestone-pipeline automatically.

---

<!-- end:roadmap -->
