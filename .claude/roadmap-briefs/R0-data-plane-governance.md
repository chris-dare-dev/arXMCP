# R0 — data-plane-governance

Phase 0. No dependencies. Small (days, mostly owner decisions + short ADR docs), but it
resolves ambiguities every other brief builds on.

## Brief (seed for /roadmap)

arXMCP's identity as a read-only proof-discovery data plane is currently conventional, not
structural: six of the seven plan directories are untracked working files (only
`plans/paper-metadata/roadmap.yaml` is committed), the untracked agent-platform plan scopes a
client-side orchestrator dispatch loop inside this repo, agent-facing trust language is
undefined (the `lean_verify` tool returns `status: "ok"` for anything that elaborates without
errors or sorries), and market/novelty claims in analysis documents are phrased categorically
("nobody ships X") rather than as scoped censuses. This initiative writes the constitution
before the construction: a data-plane boundary ADR (server = evidence and verified artifacts
only; agents, run memory, and model policy live outside; writes are offline/operator-gated);
an owner decision committing, revising, or vetoing each of the six untracked plan tracks; a
trust-language policy banning any single "verified" status in favor of multi-axis trust
records; an abstention policy making "unknown / ambiguous / unsupported" first-class tool
outcomes; and an evidence-ledger standard for novelty claims (dated, scoped, query-listed).
Do not build any new server capability in this track — it produces ADRs, policy docs, and
git-state decisions only.

## HMW / Objective

- **HMW:** How might we make arXMCP's data-plane boundary, trust vocabulary, and planning
  state explicit and binding, so that every subsequent track (R1–R7) inherits decided
  policy instead of re-litigating it?
- **Objective:** Ship the four governing documents and the plan-tracking decision, each
  short, owner-approved, and referenced from CLAUDE.md.

## Key results

1. An ADR at `.claude/docs/adr-data-plane-boundary.md` states: (a) the server never
   dispatches agents or holds per-run agent memory; (b) all writes are offline ingest or
   operator-gated console actions; (c) the agent-platform orchestrator loop is either moved
   to a separate repository or explicitly re-scoped as a client-side tool under `tools/`
   with zero server-side state — with the choice recorded and the agent-platform plan
   amended to match.
2. Each of the six untracked plan directories carries an owner disposition:
   committed to git, revised-then-committed, or vetoed-and-archived. Zero untracked
   "active" roadmaps remain.
3. A trust-language policy at `.claude/docs/trust-language-policy.md` bans any bare
   `verified: true` / single trust enum on the MCP surface; defines the multi-axis trust
   record dimensions (source grounding; claim completeness; assumption closure; formal
   alignment + its review; elaboration; proof closure; axiom audit; checker identity;
   assumption realization; numerical replay; review independence); and defines the
   abstention outcomes every tool must be able to return.
4. An evidence-ledger standard: any "no system does X" claim in repo docs must name the
   census set, queries, and date. Applied retroactively to the gap-analysis claims cited
   in these briefs.
5. CLAUDE.md §"Hard constraints" gains the boundary + trust-language rules so every
   future agent session inherits them.

## Scope — out (wont)

- No code changes to `server/` beyond none-at-all (this track is documents + git state).
- No renaming of existing tools yet (R3 owns the `lean_verify` surface change).
- No decision here about TheoremGraph/Matlas licensing posture (R7 owns adapters), except
  the general principle: non-commercially-licensed external data stays in a candidate
  layer and is never redistributed.

## Assumptions (tiered)

- **must** — The owner will actually disposition the six untracked plans in one sitting.
  *Validation:* the milestone's acceptance is the git state itself; if the owner defers,
  the tracks stay formally "proposed" and R2+ briefs treat their contents as suggestions.
- **should** — Moving the orchestrator loop out of this repo does not orphan the
  model-policy code in `server/orchestrator/` (it can stay as a library consumed by the
  external client). *Validation:* the ADR names the disposition of
  `server/orchestrator/model_selector.py` explicitly.

## Evidence (verified 2026-07-11)

- `git ls-files plans/` → only `paper-metadata` tracked; `git status` shows
  `?? plans/agent-platform/ evidence-engine/ researcher-workbench/ retrieval-unlocks/
  scale-ops-hardening/ trustworthy-release/`.
- agent-platform roadmap.yaml brief: orchestrator loop is specified "client-side, outside
  server/" — boundary-compatible but structurally unenforced.
- `server/handlers/lean_verify.py:290-298` — `status: "ok"` = no errors + no sorries;
  the trust-language gap this policy closes.
- stability-mflds `rigor.py` — an existing Rigor/Certificate lattice to align the
  trust-record vocabulary with rather than inventing a competing one.

## Milestone sketch

1. **m1 — boundary ADR + CLAUDE.md amendment** (S). Draft, owner review, commit.
2. **m2 — plan disposition** (S, owner-gated). Six decisions recorded; committed or
   archived.
3. **m3 — trust-language + abstention + evidence-ledger policies** (S). Three short docs;
   cross-referenced from the R3/R5 briefs' gates.

## Gates

- R1–R7 decomposition may begin before R0 completes, but no R-track milestone may
  *ship a tool-surface change* until m1 and m3 are merged (they define the vocabulary the
  tool contracts use).
