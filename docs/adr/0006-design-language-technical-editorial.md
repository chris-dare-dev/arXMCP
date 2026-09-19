# ADR-0006 — Design language: "Technical Editorial" (D6)

**Status:** Accepted (provisional; Directions A/B from the Stage-1
design study remain documented as per-surface donors)
**Date:** 2026-07-04

## Context

Stage-1 finding 07 developed three candidate design directions for the
operator frontend; §5-C selected Direction C.

An earlier revision of this ADR also governed reuse of an external
design system. That reuse was removed before publication and no external
design-system artifacts are vendored here, so the clause is struck
rather than carried as a rule nothing enforces.

## Decision

- The frontend design language is **"Technical Editorial"** (finding 07
  Direction C): **two content registers** — an editorial serif register
  for mathematics and a disciplined mono register for telemetry;
  **rules-not-cards** layout; **no hue in the 250–290° band**; the
  documented anti-pattern gates are enforced **as tests** from milestone
  one.
- **No external design-system artifacts are vendored.** Every component
  under `frontend-app/src/` is authored in this repository; neither
  third-party token values nor a built design-system bundle is imported.

## Consequences

- Design-gate tests (hue ban, register discipline, anti-patterns) are
  part of the Workstream-B acceptance criteria, not a style guide PDF.
- KaTeX/font assets are self-hosted (ADR-0001 invariant 3) and themed
  to the two registers.
