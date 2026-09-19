# ADR-0010 — Third-repo extraction triggers (`math-research-orchestrator`)

**Status:** Accepted (companion to ADR-0003; triggers recorded verbatim
from Stage-1 finding 06 §2.4.4)
**Date:** 2026-07-04

## Context

ADR-0003 keeps the exploration/orchestration layer inside this repo's
`.claude/` tree for now. That decision is only safe if the exit
condition is pre-agreed and concrete — otherwise the interim home
becomes permanent by inertia. Stage-1 finding 06 §2.4.4 defined the
triggers; they are recorded here verbatim so any future session can
evaluate them without re-litigating.

## The triggers (verbatim from finding 06 §2.4.4)

**Create the third repo (working name `math-research-orchestrator`)
when ANY of:**

1. Exploration/orchestration accumulates >~1,000 LOC of non-prompt code
   or needs its own dependency set (e.g., an open-problems crawler, a
   campaign scheduler);
2. A second machine or a remote execution surface enters the topology
   (the repo then owns deployment glue neither existing repo should);
3. Bridge contracts need consumers outside these two repos (publishing
   schemas independently becomes real);
4. The run-ledger/campaign state outgrows per-repo `.claude/notes/`
   (e.g., cross-article, cross-notebook longitudinal tracking).

**If created, its scope is:** `contracts/` custody transfers there (both
repos then vendor), exploration pipelines, cross-repo run ledger, and
optionally a companion frontend. It should contain **no retrieval, no
verification, no article rendering** — those stay put.

## Additional coupling (recorded for completeness)

- Trigger #2 also fast-forwards the authz upgrade: any remote surface
  ends the loopback-only justification for lightweight bearer-token
  profiles and upgrades authz to the MCP spec's OAuth 2.1
  resource-server profile (target-architecture adjudication; Stage-2
  orchestrator closure #8 currently treats the second machine as absent
  until evidenced).

## Consequences

- Checking these four lines is a standing checklist item for any
  milestone that grows exploration code, adds a machine, or exports
  contracts.
- The extraction plan (contracts custody move, envelope-wrapped
  artifacts) is pre-agreed in ADR-0002/0003, so firing a trigger is an
  execution task, not a design debate.
