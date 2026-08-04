
## paper-metadata (2026-07-05)
- Two-epic cut for stub-filling work: (1) data-plane slice (source -> store -> backfill CLI, observable without server changes) then (2) surface slice (handler wiring). Keeps e1 INVEST-independent because the CLI makes it demoable alone.
- With only 2 non-wont epics the 60% must-cap forces exactly one must — decide the payoff-vs-enabler question early (store slice won: nothing downstream works without it).
- Tag both slices value (not enabler) when each has an observable output; a backfilled store visible via CLI counts as observable.

## data-plane-governance (2026-07-11)
- Governance/docs tracks slice vertically as decision lifecycles (draft -> owner approval -> committed citable state), not doc-type layers; each epic = one decision cluster downstream tracks can cite.
- With 3 non-wont epics the 60% must-cap allows exactly one must. When two epics jointly gate downstream work (boundary ADR + trust policy both gate R-track tool-surface changes), give must to the one that also feeds an intra-track depends_on and let Phase 3 RICE re-rank the rest.
- An owner-gated decision batch (six plan dispositions) deserves its own epic: its approval mode and failure fallback (defer -> track stays 'proposed') differ from drafting epics, keeping INVEST-Negotiable clean and the must-tier assumption localized.
- Committed documents / git-state changes tag value, not enabler, when the documents ARE the track's product (extends the paper-metadata precedent: observable output counts, and observable git state is output).
- Orphan scope hiding in a wont ("only the general principle lands here") must be explicitly assigned to an epic summary or Phase 3 may drop it — the licensing candidate-layer principle went into e1.

## source-truth (2026-07-11)
- When a refiner brief ships a milestone sketch whose seams each already end at an observable surface (registry+report, served chunk fields, MCP resource, fresh-install behavior), the epic cut can mirror those seams 1:1 — 4 vertical epics, no re-grouping needed.
- Keep tool-visible field surfacing INSIDE the schema epic, not as a separate "surface it" epic — a standalone surfacing epic is the banned horizontal split; external-window (W1) ordering belongs to Phase 3 milestone sequencing within the epic.
- Isolate owner-gated work into its own terminal epic (fail-closed cutover): the human gate then never blocks sibling epics, and the override escape hatch keeps the epic Negotiable.
- With 4 non-wont epics the must-cap allows exactly 2 musts — spend them on the KR critical path (registry, chunk fields) and demote both gates (manifest, cutover) to should even when they block downstream tracks; blocking-ness is a dependency fact, not a MoSCoW rank.

## verification-contract (2026-08-03)
- Security/soundness tracks: don't merge a milestone sketch's L-sized milestone with an adjacent M-sized one just because the brief groups them prose-wise ("operations + adversarial validation") — check estimated weeks first. Kept m3 (five operations, L) and m4 (attack suite, M) as separate epics with a depends_on edge instead, avoiding an XL epic; only merged the two milestones that were both forbidden-until-gate anyway (m6 cache + m7 pools) into one epic, since their shared "blocked behind the trust gate" status made the merge low-risk even before weeks-accounting.
- When a brief names an explicit blocking gate ("performance work forbidden before the trust gate"), encode it as depends_on from the gated epic to EVERY epic that carries the gate's prerequisite milestones (not just the last one) — makes the constraint machine-checkable via the DAG rather than living only in prose.
- MoSCoW priority and dependency-blocking-ness are different axes (reconfirmed from data-plane-governance): the attack-suite and named-environment epics both block the trust gate but were still tagged `should` (not `must`) to stay under the 60% must-cap, since e1/e2/e3 (schema honesty, isolation boundary, core operations) were the higher business-priority must-haves.
- A pure OS-sandboxing epic (Job Object/container spike + landed boundary) is legitimately `enabler`, not `value` — even though it's security-critical — because it ships no new agent-facing capability by itself; tag it enabler and name its downstream value consumer explicitly in the summary so the 40% enabler-cap reviewer can see why it's there.
- CLAUDE.md §4.9-style "no bare verified" constraints belong in epic summaries as explicit reassurance sentences ("none of these operations is presented as a safe-to-trust verdict until X"), not just in the goal block — keeps a future regeneration from silently drifting the epic back into implying trust before the gate.
