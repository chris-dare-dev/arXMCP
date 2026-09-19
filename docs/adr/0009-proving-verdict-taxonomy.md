# ADR-0009 — Proving outputs use the five-verdict taxonomy, abstained-by-default (D9)

**Status:** Accepted (no fallback — this is the soundness core)
**Date:** 2026-07-04

## Context

The proving workstream (WS-D) turns ProofTasks into evidence. The
central failure mode of LLM-assisted mathematics is the
confidently-wrong proof; Stage-1 finding 05 §4.3 designed the verdict
taxonomy against it, and the Stage-2 acceptance bar (orchestrator
closure #7) is *sound workflows*: known-answer tests where FALSE
statements **must be rejected** and OPEN statements **must yield
abstention**.

## Decision

Every proving output carries exactly one of five verdicts:

| Verdict | Meaning |
|---|---|
| `proven-formal` | Machine-checked (Lean kernel accepts; `lean_verify` evidence attached) |
| `proven-informal-checked` | Informal proof that passed the defined checking workflow |
| `plausible-unverified` | Argument produced, checks not passed — explicitly NOT a proof |
| `refuted` | Counterexample/disproof with evidence |
| `abstained` | No sound conclusion reached — **the default** |

- **Abstained-by-default:** absence of successful verification yields
  `abstained`, never a downgraded "probably true".
- **Machine-checkable award rules:** each verdict has explicit,
  testable award criteria; the KAT suite (FALSE-must-reject,
  OPEN-must-abstain) enforces them.
- **Per-verdict evidence bundles:** every verdict ships the evidence
  that justifies it (kernel transcript, check log, counterexample,
  abstention trace) in the bridge envelope (ADR-0002).

## Consequences

- Downstream surfaces (article badges, notebooks) render verdicts
  mechanically; no prose reinterpretation.
- Verdict vocabularies from other pipelines do **not** unify with this
  one by fiat (the cite-audit measurement showed vocabularies don't
  merge); mappings are explicit contract work.
