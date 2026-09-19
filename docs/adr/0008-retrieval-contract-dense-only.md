# ADR-0008 — The retrieval contract is dense-only, pinned as an enum (D8)

**Status:** Accepted (n/a fallback — this records shipped reality plus a
re-open condition)
**Date:** 2026-07-04

## Context

Stage-1 finding 211 R-B (errata E-3/E-4) settled a fact several planning
documents had wrong: the shipped retrieval mode is **dense-only ANN over
BGE-M3 `embedding_stmt`** — `"retrieval_mode": "dense_only"` is
hardcoded in the `search_papers` payload. The hybrid
BM25→ANN+RRF→BGE-reranker pipeline exists **as modules only**
(`server/retrieval/`), is invoked by no live query path, and its wiring
epic closed 2026-05-21 with verdict **NO** (zero P@10 lift, −10 pp
top-1, 122× latency at 51-paper/20-query scale —
`plans/proof-verify-handler-wiring-roadmap.md`).

## Decision

- The Stage-2 bridge contract carries **`retrieval_mode` as an enum with
  `dense_only` as the sole current value**. Consumers may parse the
  string (the cutover roadmap warns they will); any change to it is a
  **versioned contract event**, never a silent switch.
- **Hybrid re-opens only on a new measured verdict at materially larger
  corpus scale** (the roadmap's own re-open condition). It is a
  RISKS-register watch item, **not a schedulable workstream**. No
  Stage-2/3 plan may contain hybrid-wiring work.
- `find_equation`'s TED+dense fusion is equation-index fusion, not text
  hybrid retrieval, and is unaffected.

## Consequences

- Latency budgets and architecture prose must say "dense-only" —
  documents claiming a live hybrid stack are wrong by definition
  (finding 211 is the override).
- The evidence-gating discipline is the control: re-scheduling hybrid
  without a new measurement is the failure mode this ADR exists to
  block.
