# ADR-0003 — No third repo now; exploration lives in `.claude/` interim (D3)

**Status:** Accepted (provisional; fallback = create the third repo
early with contracts custody transferring per the pre-agreed extraction
plan)
**Date:** 2026-07-04

## Context

The exploration/orchestration layer (open-problem scans, notebook-
manifest proposals, campaign state) is architecturally homeless: it is
neither retrieval substrate (arXMCP) nor article rendering (website).
Stage-1 finding 06 §2.4.3–2.4.4 (Candidate B) weighed a dedicated
`math-research-orchestrator` repo against interim residence and
recommended staging.

## Decision

- **No third repo is created now.** Exploration/orchestration workflows
  live as `.claude/` pipelines **in the arXMCP repo** interim — they
  manipulate notebooks/corpora, respect propose→confirm, and emit
  arXMCP-native artifacts (notebook manifests).
- Every pipeline output is **envelope-wrapped** (the common bridge
  envelope) so artifacts survive a later repo move losslessly.
- The repo is created **only when a trigger fires** — the four concrete
  triggers are recorded verbatim in
  [ADR-0010](0010-third-repo-extraction-triggers.md).

## Consequences

- No new repo/deployment surface to maintain during Stage 2.
- The move stays cheap by construction (prompts + scripts + enveloped
  artifacts).
- Discipline required: exploration code accumulating in `.claude/` must
  be measured against ADR-0010's LOC trigger rather than growing
  silently.
