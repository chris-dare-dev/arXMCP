# R6 — proof-structure-and-bundles

Phase 3. Depends on: R2 (claim IR, typed context, equation attachment), R1 (spans), R0
(abstention). Gated by: R7's ablation (continue/kill for semantic metadata). Feeds: R7's
downstream-utility arms.

## Brief (seed for /roadmap)

With claims, contexts, and citations first-class (R2), the next payloads are the ones 2026's
ablation evidence actually supports: worked proofs and structured, budgeted context — not
semantic technique taxonomies. The evidence base: similar prior *proofs* gave Rango a 45%
relative lift (ICSE'25 Distinguished Paper); dependency-graph-shaped context beat flat
search for formalization (TheoremGraph's 5/24→8/24); informal drafts roughly double formal
success (Draft-Sketch-Prove); hand-curated technique wikis died (Tricki froze within ~2
years); no system tags informal papers by technique at scale; and Rethlas/Archon's stated
thesis is that statement-level retrieval transfers techniques *without* labels. But ordered
citation lists are not proof skeletons — papers omit routine steps, cite whole theories,
introduce constructions, split cases, and change goals without citing anything. This
initiative builds three things. (1) **Evidence-backed proof DAGs**: per proof block, a
typed-action-node graph — introduce/construct object; unfold or change definition;
reduce/transform goal; invoke result (edge to the R2-resolved claim); transport across an
equivalence; restrict/induce along a functor; split cases; derive contradiction; perform
computation; discharge side condition — every node carrying its source span, confidence,
extraction method, and review state, with **explicit unknown-gap nodes** where the text
skips; deterministic signals first (resolved citations + the equation spine from R2's
attachment), local-llm volume + Claude-gated sampling for the rest, per the delegation
policy. (2) **The example/counterexample lane**: `kind`-facet search over the chunker's
existing environment types, plus an index of instantiated objects (specific Mukai vectors,
specific spherical objects, nodal-case counterexamples) so "how does this fail on nodal
Enriques" is a query. Technique facets ride on top only as weak, multi-label,
low-trust annotations (wall-crossing; deformation; spectral sequence; HN-length induction;
mutation through an exceptional collection; lattice obstruction; degeneration;
Serre-action contradiction) — evaluated solely by measured retrieval/premise-selection lift
in R7, never authoritative, never the primary index. (3) **Budgeted progressive evidence
bundles** replacing the one-call "attack kit": a small claim card first (statement,
hypotheses, typed bindings, trust axes); expandable sections (assumptions detail; proof
DAG; formal targets; computation receipts; similar proofs; analogies; contrary evidence)
each priced against an explicit token/evidence budget; a **coverage/missingness manifest**
("no formal target; 2 unresolved citations; assumptions machine-inferred") so absence reads
as absence; deterministic ordering and snapshot identity (R1 manifest hash) for cache
discipline; `<retrieved_…>` injection posture inherited. Analogy lanes (K3 ↔ Enriques ↔
abelian ↔ cubic-threefold) return candidate analogies **with unmatched-assumption and
type-diff reports** — and are never marked "safe", because hypothesis recovery is
incomplete by construction; an empty generated diff is labeled "no diff found", not "no
diff exists".

## HMW / Objective

- **HMW:** How might we serve proof structure, worked instances, and composed context in
  forms the ablation evidence supports — evidence-backed, budgeted, missingness-honest —
  without smuggling in authoritative semantic labels or context bloat?
- **Objective:** Ship proof DAGs v1 with unknown gaps, the example lane, weak technique
  facets behind a lift gate, and progressive bundles with budgets + missingness manifests.

## Key results

1. Proof DAG IR: action-node table keyed to proof blocks; ten node types as above; every
   node has span + method ∈ {deterministic, llm} + confidence + review state; unknown-gap
   nodes are mandatory wherever consecutive nodes don't textually connect; DAGs attach to
   the R2 claim of the proved statement.
2. Extraction quality is measured, not assumed: a 20-proof hand-annotated golden set from
   the Bridgeland notebook; node/edge precision + recall reported; deterministic-only
   baseline reported separately from LLM-augmented (so the marginal value of the LLM pass
   is visible and killable).
3. `get_proof_structure(claim)` serves the DAG with evidence; "which proofs invoke
   [resolved claim X] inside a case-split" is answerable by graph query (the structural
   replacement for technique tags).
4. Example lane: `kind ∈ {example, remark, counterexample}` facets on search; an
   instantiated-object index (object expression → blocks) with the same evidence
   discipline; "examples instantiating a wall computation for v=(2,0,-2)-type classes"
   resolves.
5. Technique facets: multi-label weak annotations with per-label calibration; **shipped
   dark** (stored, not served) until R7's ablation shows lift; a kill criterion is written
   before the first label is computed.
6. Bundles: `build_evidence_bundle(goal, budget, trust_filter)` returns claim card +
   expansion handles + missingness manifest; deterministic ordering; total tokens ≤ budget
   (tested); every included item carries its trust axes; contrary-evidence section
   included when R2 edges of type `contradicts/corrects` exist.
7. Analogy lane: cross-surface candidate retrieval with unmatched-assumption report
   (from R2 typed context diffs) + explicit "unknowns" list; acceptance test: the K3→
   Enriques S²-analogy case surfaces the 2-torsion/typed-functor diff (the article's
   error, §5 of the gap analysis) rather than a clean match.

## Scope — out (wont)

- No authoritative technique ontology; no hand-curated taxonomy maintenance commitments.
- No one-call maximal context packs; budgets and progression are constitutive, not
  optional.
- No cross-run agent memory (external agents own run memory; the server may *ingest*
  curated attempt artifacts offline through the normal operator-gated path — that ingest
  design is a later, separate brief if wanted).
- No serving of DAGs as "the proof" — they are structural evidence over the text, and the
  response schema says so.

## Assumptions (tiered)

- **must** — R2's claim resolution + equation attachment landed at its precision gate
  (DAG invoke-edges inherit that precision). *Validation:* entry gate.
- **must** — The 20-proof golden set is affordable owner work (~1–2 owner-days).
  *Validation:* time-box the first 5; shrink the set before shrinking annotation depth.
- **should** — Deterministic signals alone yield useful skeletons (invoke edges + equation
  spine + section structure) with LLM augmentation as measurable delta. *Validation:* the
  split reporting in KR2; if the deterministic baseline carries most of the value, the LLM
  pass stays optional per-notebook.
- **should** — Bundle budgets compose with the 3-tier cache and BP discipline (bundles are
  deterministic given snapshot + budget). *Validation:* cache-key design review against
  `.claude/notes/07-multi-agent-caching.md` before implementation.

## Evidence (verified 2026-07-11)

- Rango (arXiv:2412.14063) +45% from similar proofs; TheoremGraph ablation 5/24→8/24;
  Draft-Sketch-Prove (arXiv:2210.12283) ~doubling; Tricki frozen (tricki.org, Gowers'
  post-mortem); Rethlas/Archon (arXiv:2604.03789) retrieval-transfers-techniques thesis;
  REFACTOR/LEGO/DreamProver: techniques captured as reusable artifacts, not tags.
- `ingest/chunker.py` `_env_kind` — environment kinds already typed at ingest; the example
  lane is largely serving paid-for structure (matches retrieval-unlocks' "unlock" pattern).
- R2's `citation_occurrences` + equation attachment — the deterministic spine.
- MMAT (arXiv:2607.04394) KB-Manager card types (Source/Concept/Analysis/Lean/
  PartialProof/Obstruction) — independent convergence on the bundle sections.
- Context-bloat/lost-in-the-middle and injection cautions: bundle budgets + missingness
  manifest + `<retrieved_…>` posture are the mitigations, inherited from the existing
  snippet contract.

## Milestone sketch

1. **m1 — DAG IR + deterministic skeleton pass + golden set** (L).
2. **m2 — LLM augmentation + split-quality report** (M).
3. **m3 — example/instantiated-object lane** (M).
4. **m4 — bundles v1 (card + expansions + budget + missingness)** (L).
5. **m5 — analogy lane with diff reports** (M).
6. **m6 — technique facets (dark) + kill criterion** (S).

## Gates

- **Entry:** R2 exit gate; R1 manifest.
- **Exit:** golden-set precision/recall published; the analogy acceptance test passes;
  bundle budget property-tested; facets remain dark until R7 lift.
- **Kill rule (from R7):** if the 5-arm ablation shows no held-out lift from DAGs or
  facets at fixed budget, stop extending semantic metadata and reinvest in R2 precision
  and R4/R5 coverage — the gap analysis's own §6 commitment.

## Evidence-ledger census (2026-07-12)

Per [`.claude/docs/evidence-ledger-standard.md`](../docs/evidence-ledger-standard.md), the
brief's external absence claim — previously categorical — now carries a census:

> **Claim (`:15`):** "no system tags informal papers by technique at scale."
> **Census set:** Mathematics Subject Classification / AutoMSC; math-aware content
> classification (arXiv:2110.04040); formula-concept / POS tagging for math; human-curated
> technique wikis (Tricki, nLab, ProofWiki).
> **Queries run:** `tag mathematics papers by proof technique at scale automatic classification
> 2026`; `Tricki mathematics proof techniques wiki status active or frozen`.
> **Date:** 2026-07-12. **Verdict:** confirmed, **scoped and non-exhaustive** — surfaced work is
> *subject* classification (MSC/AutoMSC), *content-similarity* (arXiv:2110.04040), or
> *formula-concept* tagging, none by proof technique; technique wikis are small/static (Tricki
> live since Tao's 2009 launch, no scaled ongoing contribution). **Not checked:** closed
> commercial indexers, non-English systems.

(The companion "Tricki froze within ~2 years" is a single-system historical fact, not an
absence census; it needs only a freshness re-check — done above: the site remains reachable
but static.)
