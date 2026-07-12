# Roadmap briefs — proof-discovery data plane (adjudicated program, 2026-07-11)

Eight roadmap-ready briefs (R0–R7) decomposing the corrected gap-analysis program
(gap-analysis rev 2, §6–§7: https://claude.ai/code/artifact/2fce1969-cddc-4e5a-a656-592fd5026da6)
into inputs for the `/roadmap` pipeline (Refine → Decompose → Sequence → Materialize).
Each file is a self-contained prompt: paste its **Brief** block as the seed and let the
pipeline refine; the remaining sections carry the evidence, assumptions, decomposition
sketch, and gates the refiner/decomposer should consume.

These briefs supersede the gap-analysis's original 90-day sequence. They encode the
adjudicated corrections: trust and truth before capability; multi-axis trust records
instead of a "verified" ladder; claim IR instead of enriched chunks; provider boundaries
instead of merged libraries; conditional interface targets instead of skeleton corpora.

## The briefs

| ID | Slug suggestion | One-liner | Phase |
|---|---|---|---|
| R0 | `data-plane-governance` | Boundary ADR, plan-tracking decision, trust-language + evidence-ledger policy | 0 |
| R1 | `source-truth` | Revision/span/checksum identity, truncation persistence, printed numbers, per-paper license provenance, corpus manifest | 0 |
| R2 | `claim-graph` | Claim IR v1: blocks/claims/citation-occurrences, evidence-carrying resolution with abstention, scoped assumptions, typed symbol/theory context | 1 |
| R3 | `verification-contract` | Sound Lean surface: 5-operation split, target binding, axiom audit, strict replay, OS isolation, attack suite, named environments | 0–1 |
| R4 | `verified-computation` | stability-mflds as separately-released provider; certified pilot ops with independent oracles; explicit abstention; G12 coordination | 2 |
| R5 | `formal-target-registry` | Pin+audit BridgelandStability; 5–10 reviewed conditional targets with multi-axis trust and assumption debt; §8 action gap | 2 |
| R6 | `proof-structure-and-bundles` | Evidence-backed proof DAGs, example lane, weak technique facets, budgeted progressive evidence bundles, analogy with unmatched-assumption reports | 3 |
| R7 | `adapters-benchmark-ablation` | Versioned external adapters (TheoremGraph/Matlas/LeanExplore), five benchmark suites, the 5-arm downstream ablation, provenance taxonomy | 3 |

## Dependency order

```
R0 ─┬─▶ R1 ─┬─▶ R2 ─┬─▶ R6 ─┐
    │       │       │       ├─▶ R7 (ablation gates everything after it)
    └─▶ R3 ─┴─▶ R5 ─┤       │
            └─▶ R4 ─┴───────┘
```

- R0 and R1 have no dependencies and can start immediately.
- R3's contract work can start immediately; its cache/warm-pool tail waits for its own
  isolation + attack-suite gates.
- R2 requires R1 (identity) and the evidence-engine FIX milestone (populated eval fixture).
- R4 and R5 require R3's gates (no trust-bearing artifact ships over an unsound verifier).
- R6 and R7 require R2's claim IR; R7's ablation is the continue/kill gate for R6-style
  semantic metadata.

## Interlocks with the seven existing plan tracks

| Existing track | Interlock |
|---|---|
| `paper-metadata` (tracked) | R1 extends its store with license + revision fields; R2 uses it for bibliography→work resolution |
| `evidence-engine` (untracked) | R2's fixture work merges with FIX — one 50-query fixture, not two; R7's ablation extends its agent-task eval |
| `agent-platform` (untracked) | All new tool registrations batch into the W1 tool-schema re-pin window; R0's boundary ADR resolves its orchestrator-loop placement |
| `retrieval-unlocks` (untracked) | R1's withdrawal hygiene and R2's S2 citation-context hydration are already partially planned there — dedupe at decomposition |
| `trustworthy-release` (untracked) | R1's license provenance subsumes its textbook-license defect fix; its citation contract (quote_sha256) is the base R2/R5 provenance extends; **no PyPI publish before R1 gates pass** |
| `scale-ops-hardening` (untracked) | R3's sandbox composes with its parser-containment work; nothing in R1–R7 gates on corpus scale |
| `researcher-workbench` (untracked) | R2 assumption review and R5 target curation route through its labeling UI |

## Standing policies these briefs assume (from R0)

1. **Data-plane only.** The server never runs agents, never holds per-run agent memory,
   and takes writes only through offline/operator-gated ingest.
2. **No bare "verified".** Every artifact carries a multi-axis trust record; no API
   compresses it into one status enum.
3. **Evidence-ledger phrasing.** Novelty/"nobody does X" claims are recorded as scoped,
   dated censuses with queries, never as categorical facts.
4. **Abstention is a success state.** "Unknown", "ambiguous", "not in corpus",
   "unsupported by provider" are first-class results, tested like any other.

Authored 2026-07-11 from the adjudicated gap analysis. Working files, not committed
project state, until the owner promotes them (R0 decision).
