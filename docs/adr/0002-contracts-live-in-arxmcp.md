# ADR-0002 — Bridge-contract ownership moves to arXMCP (D2)

**Status:** Accepted (provisional; no Stage-1 finding opposes it — no
fallback needed)
**Date:** 2026-07-04

## Context

The arXMCP ↔ consumer bridge exchanges written artifacts (proof
evidence bundles, claim/triangulation records, export manifests). The
schemas for these artifacts historically lived on the **consumer** side,
inverting producer/consumer discipline and leaving arXMCP's test suite blind
to contract drift (Stage-1 finding 06 §2.4.4, §2.5.2).

## Decision

- Contract ownership moves to arXMCP: a new top-level **`contracts/`**
  directory holds the JSON Schemas plus a `CONTRACTS.md` changelog —
  **producer-owns-contract**.
- The contracts are covered by arXMCP's own pytest suite.
- The website vendors **pinned copies** with a checksum drift test
  (mirroring the `EXPECTED_TOOL_SCHEMA_SHA256` pinning idiom already in
  this repo).
- A `GET /bridge/contracts` handshake endpoint (Workstream A) serves the
  artifact-type → version map plus schema SHA-256s at runtime.

## Consequences

- Contract changes are versioned events in the producer's history;
  consumers detect drift mechanically instead of at integration time.
- If ADR-0010's extraction triggers ever fire, `contracts/` custody
  transfers to the new orchestrator repo and **both** existing repos
  vendor from it (pre-agreed move; see ADR-0003/0010).
