# ADR-0004 — The `/app` SPA lives in the arXMCP repo (D4)

**Status:** Accepted (provisional; moot if ADR-0001 is vetoed)
**Date:** 2026-07-04

## Context

Given ADR-0001, the SPA needs a home: this repo, the website repo, or a
third repo. Stage-1 finding 10 §2.5/§4-8 adjudicated (superseding the
option-(c) lean in finding 01 §3-P0).

## Decision

The Vite + React SPA lives **in the arXMCP repo**: source under
`frontend-app/`, build output as static `dist/` served at `/app` by the
existing FastAPI process.

Rationale:

- **Same-origin serving** — no CORS surface at all.
- Inherits the loopback middleware stack (Origin/Host validation,
  Sec-Fetch-Site, body caps, security headers) with zero duplication.
- **Version lockstep** with `/api/v1`: one commit changes an endpoint
  and its consumer; no cross-repo contract dance for the operator UI.
- The existing `frontend/` (htmx console assets) stays as-is; the
  strangler boundary is directory-level.

## Consequences

- The repo gains a `package.json`/lockfile and a build step (build-time
  only, per ADR-0001).
- The public-repo posture question (Stage-2 flagged item #4) covers the
  SPA source too; nothing secret may land in `frontend-app/`.
