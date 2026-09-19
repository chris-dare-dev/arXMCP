# ADR-0005 — Capability gating is call-time denial, never `tools/list` filtering (D5)

**Status:** Accepted (no fallback — violating this torches the
multi-agent prompt-cache economy)
**Date:** 2026-07-04

## Context

Workstream A adds capability profiles (per-profile tool allowlists,
caps, notebook scoping). The naive design — filtering `tools/list` per
profile — would break the **BP1 prompt-cache discipline**: the
`tools/list` response bytes and `EXPECTED_TOOL_SCHEMA_SHA256` are frozen
so every pipeline agent shares one prompt-cache prefix
(`.claude/notes/07-multi-agent-caching.md`). Stage-1 finding 06 §2.6.3
and finding 04 (no reusable prior art — design natively) ground this;
the shipped `ARXMCP_ENABLE_LEAN` / `lean_status="disabled"` pattern is
the in-repo precedent.

## Decision

- `tools/list` **always returns all registered tools, byte-identically**,
  regardless of profile. The BP1 guard (byte-stability assertion) is a
  fixture in every capability test.
- A disabled/denied capability is enforced **at call time**: the call
  returns a **structured error envelope** (documented `error_code`,
  machine-parseable, mirroring `lean_status="disabled"`) — never a
  transport-level error, never a missing tool.
- Per D5, **no per-profile `tools/list` filtering exists anywhere in the
  codebase** — grep-enforced by test.

## Consequences

- Agents can share one cached prompt prefix across profiles; capability
  changes cost zero cache invalidation.
- Denied calls are observable (audit rows) instead of invisible
  (missing tools).
- UI surfaces must present "tool exists but this profile may not call
  it" — a small UX cost accepted deliberately.
