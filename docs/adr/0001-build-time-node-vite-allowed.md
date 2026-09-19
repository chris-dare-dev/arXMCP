# ADR-0001 — Build-time Node/Vite allowed; all runtime invariants preserved (D1)

**Status:** Accepted (provisional — Stage-2 orchestrator closure #1 under the
owner's standing brief; open to owner veto, see below)
**Date:** 2026-07-04
**Amends:** the project constitution (`CLAUDE.md` §4.7 and the historical
"no SPA / no Node build chain" framing in §2/§5/§6 and
`.claude/notes/06-mcp-server-design.md` § "Browser UI surface")

## Context

The owner's brief mandates a modern operator frontend (motion language
drawing on anime.js, and 3D/WebGL-class visualization) that the zero-JS
Jinja2+htmx console cannot satisfy. The constitution to date banned any
Node build chain outright — a rule written when "the MCP tool surface is
the UI." Stage-1 analysis (findings 10 §2.2/§2.5, 08 §4-1, 09 §4-1)
concluded the ban conflates two different things: a **runtime** Node
process (genuinely dangerous to the single-process, loopback, offline
posture) and a **build-time** toolchain that emits static files.

## Decision

Node/Vite (and npm-managed frontend dependencies) are permitted as
**build-time-only** tooling:

- The Vite build emits static assets committed/served as `dist/`,
  statically mounted at `/app` by the **existing FastAPI process**.
- **Every runtime invariant is preserved, unamended:**
  1. **Single Python process** — no Node/bun/npm process exists at
     runtime (E2E process-list check is the enforcing test).
  2. **Loopback-only** — `/app` is served on `127.0.0.1:7733` behind the
     same middleware stack; no new listener.
  3. **No runtime network fetches** — all JS/CSS/fonts/KaTeX assets are
     self-hosted; E2E network capture asserts loopback-only.
  4. **Lockfile-reproducible assets** — the build is reproducible from a
     committed lockfile; no CDN, no postinstall network surprises beyond
     the lockfile graph.
  5. **CSP at `/app` is stricter than `/ui/`** — `script-src 'self'`
     with no `unsafe-inline` (the `/ui/` htmx console needs
     `unsafe-inline`; the SPA must not).
- `/ui/` is untouched and retained as the zero-JS fallback console
  (strangler pattern; Stage-2 orchestrator closure #5).

## Consequences

- Unlocks Workstream B (Vite + React SPA at `/app`) and the richer
  observability/3D surfaces.
- Adds a lockfile/supply-chain surface at **build time**; mitigated by
  lockfile pinning and the loopback/no-runtime-fetch invariants, and in
  scope for the #9 security-audit amendment
  (`docs/security/issue-9-scope-amendment-draft.md`).
- CI-less repo: the reproducible-build and process-list checks are local
  E2E tests, not CI gates.

## Veto / fallback path

Revert this ADR; Workstream B falls back to Option A (extend Jinja+htmx
with SSE), and the motion/3D language is **formally cut from the brief**
(not silently degraded) per finding 10 §2.4.
