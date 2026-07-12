
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
