# R5 — formal-target-registry

Phase 2. Depends on: R3 trust gate (environments, attestations, strict replay), R2 claim IR
(targets link claims), R1 (revision pinning), R0 (multi-axis trust records). Curation rides
researcher-workbench's labeling UI.

## Brief (seed for /roadmap)

The census (2026-07-11, scoped: AXLE, formal-conjectures, SorryDB, Herald, TheoremGraph,
LeanArchitect, Matlas) found no system serving new, typechecked formalizations of paper
statements pinned to both a corpus revision and a formal environment as a queryable API —
and the adjudication fixed the two traps this idea invites. First, typechecking is not
fidelity: TheoremGraph's own statement-only experiment produced 22/24 outputs that
typechecked while only 5/24 were semantically faithful, and research-grade statement
autoformalization runs ~23.5% (Herald, graduate-level); so faithfulness is a *human-review
axis*, never inferred from elaboration. Second, statements over axiomatized geometry are
*conditional*: a theorem proved from a declared `EnriquesKuContext` structure is a theorem
about any instance of the interface, not yet about an Enriques surface — the unrealized
assumptions are debt that must be tracked, surfaced, and never silently discharged. This
initiative builds a small, immutable, multi-axis-trust formal-target registry: pin and audit
Matthew Ballard's BridgelandStability as the anchor library (formalization.yaml verified
2026-07-11: Bridgeland 2007 §2–7 in general class-map form, Theorem 1.2 + Corollary 1.3,
one comparator-stub sorry, zero axiom declarations, Lean 4.29.0 + pinned Mathlib commit,
self-assessed "draft", author-only sampled review — a strong dependency candidate, not a
trusted standard); produce a declaration-by-declaration coverage matrix against the paper,
explicitly documenting that **§8 — the G̃L⁺(2,ℝ) and autoequivalence actions — is out of
scope upstream**, and schedule that action (upstream PR or a local extension module with
domain review) as its own milestone, because Serre-invariance targets consume exactly it;
then curate 5–10 targets (not 50) from the Enriques–Kuznetsov article and its load-bearing
citations, each carrying: the R2 claim link and R1 revision pin; the informal statement +
scoped context; the declared relation to the source (exact / equivalent / specialization /
one-way); a reviewed Lean signature in a named R3 environment; the explicit assumption
frontier (which primitives are interface structures, which are Mathlib-real); declaration
and expected-type hashes; proof/axiom/checker attestations from R3; human review records
(faithfulness review is mandatory and recorded with reviewer + date); and lifecycle states
(drafted → typechecked → faithfulness-reviewed → proved-conditional → realized), including
stale/conflicted/superseded. Several of the article's §8 numerical steps (the K_num(Ku)≅ℤ²
bookkeeping, the sign relation's lattice consequence, 2[E]=0 ⇒ [E]=0 in a torsion-free
lattice, the rank-component non-vanishing) are fully provable in Lean today over
`Module ℤ (Fin 2 → ℤ)`-grade structures — the registry's first entries should include
closed proofs, not only sorried skeletons, to exercise the whole attestation path.
LeanBlueprint/LeanArchitect-style informal↔formal linking is the workflow model; no bare
"verified" label exists anywhere in the schema.

## HMW / Objective

- **HMW:** How might we give the notebook's load-bearing statements machine-readable formal
  targets whose epistemic status — faithfulness, conditionality, axiom closure, review —
  cannot be misread, anchored on an audited pin of the field's one existing formalization?
- **Objective:** Ship the audited anchor pin + coverage matrix + §8 gap plan, and a 5–10
  entry registry with full multi-axis trust records, served through the MCP surface.

## Key results

1. **Anchor audit:** BridgelandStability pinned at a commit; built reproducibly in the
   exact env (Lean 4.29.0 + Mathlib 8a17838…); comparator run; axiom closure enumerated
   (R3 `audit_axioms`) over every target declaration; the coverage matrix
   (paper section/lemma → decl | absent) committed; comparator-stub vs target declarations
   distinguished; a thin adapter namespace isolates upstream churn. Published as
   `.claude/docs/bridgeland-anchor-audit.md` — trust label: "audited draft dependency".
2. **§8 action plan:** an owner decision selects upstream-contribution vs local extension
   for the G̃L⁺(2,ℝ) action (Lemma 8.2) and the Aut action; either way the work item has a
   domain-mathematician review step and its own comparator entries. Targets that do not
   need §8 (the numerical/lattice lemmas) proceed without it.
3. **Registry schema + storage:** immutable entries with the fields above; multi-axis
   trust record per the trust-language policy
   ([`.claude/docs/trust-language-policy.md`](../docs/trust-language-policy.md)); every entry
   references R1 manifest hash + R3 environment
   digest; supersession edges when a target is re-cut.
4. **First entries (5–10):** at minimum — (a) K_num lattice bookkeeping lemmas from the
   article's §8.4–8.6 as *closed* Lean proofs (torsion-free rank-2 arithmetic); (b) the
   Serre sign relation's lattice consequence as a closed conditional proof over an
   interface structure; (c) LNSZ Lemma 4.8 as a faithfulness-reviewed interface statement;
   (d) the article's main non-existence theorem as a conditional interface target with its
   full assumption frontier (Ku(X) SOD data, Serre formula, spherical objects, §8 action)
   explicitly listed as debt.
5. **Serving:** targets attach to R2 claims (`get_claim` gains a `formal_targets` field);
   a `get_formal_targets(claim, required_axes)` tool filters by trust axes; nothing serves
   without its axes.
6. **Curation workflow:** drafting may use models (R3 ops in the loop); every entry's
   faithfulness review is human, recorded through the workbench labeling instrument, and
   sized to owner capacity (tens of statements, per the eval-fixture lesson).

## Scope — out (wont)

- No 50-statement corpus; growth only after review capacity + downstream utility (R7) are
  demonstrated.
- No claim that a conditional proof instantiates geometry; realization obligations are
  tracked debt, and the schema cannot express "realized" without a reviewed instance.
- No formalization program for Coh(X), Fourier–Mukai, Serre duality, or Enriques surfaces
  inside arXMCP (independent Lean projects; the registry only pins releases).
- No Mathlib PRs from this track (upstream contributions, if chosen for §8, follow
  Mathlib's AI-disclosure policy and are their own owner-gated effort).

## Assumptions (tiered)

- **must** — The pinned BridgelandStability commit builds on this workstation in
  reasonable time/disk. *Validation:* R3-m5's build smoke covers it; failure demotes the
  anchor to statement-mining only (its definitions transcribed, not imported) with the
  decision recorded.
- **must** — The owner can complete faithfulness review for 5–10 entries within ~2
  owner-days total. *Validation:* time-box the first 2 entries; if the rate extrapolates
  worse, cut registry size, never review depth.
- **should** — The §8 action is formalizable at interface level (the action on slicings +
  central charges) without new Mathlib prerequisites beyond the anchor's own frame.
  *Validation:* a 2–3 day spike states (not proves) the action and the cover-element
  relation in the anchor's vocabulary; failure narrows v1 targets to the §8-free subset.
- **might** — Upstream (Ballard) is receptive to a §8 contribution. *Validation:* a short
  issue/inquiry before the owner decision; no dependency on the answer.

## Evidence (verified 2026-07-11)

- `formalization.yaml` (raw.githubusercontent.com/mattrobball/BridgelandStability/main):
  §2–7 scope; §8 excluded; 1 sorry (Spec.lean:52 comparator stub; proof file sorry-free);
  0 axioms; draft label; sampled non-independent review; Lean 4.29.0 + Mathlib commit
  8a178386ffc0f5fef0b77738bb5449d50efeea95.
- TheoremGraph statement-only experiment: 22/24 typecheck vs 5/24 faithful — the
  typecheck≠fidelity constant.
- Herald: 96.7% miniF2F statements vs 23.5% graduate-level — why curation is human-gated.
- The article (`enriques-kuznetsov-stability.mdx` §8): the concrete lattice steps that are
  closable today; the §8.3 cover-element analysis that consumes the missing §8 action.
- formal-conjectures conventions (statement-only entries, status taxonomy) and
  LeanArchitect/leanblueprint linking as workflow prior art.

## Milestone sketch

1. **m1 — anchor pin + reproducible build + audit + coverage matrix** (M).
2. **m2 — §8 decision + interface spike** (M, owner-gated).
3. **m3 — registry schema + attestation wiring to R3** (M).
4. **m4 — first entries: closed lattice lemmas + reviewed interface statements** (M→L,
   owner review in loop).
5. **m5 — serving surface (`formal_targets` on claims; query tool; W1 batch)** (S→M).

## Gates

- **Entry:** R3 trust gate green (no registry entry without attestations); R2 m1 landed
  (claims to link to).
- **Exit:** every entry has zero non-allowlisted axioms, a strict replay attestation, a
  recorded human faithfulness review, and an explicit assumption frontier conforming to the
  trust-language policy
  ([`.claude/docs/trust-language-policy.md`](../docs/trust-language-policy.md)); the article's
  main theorem entry correctly shows its §8-action debt (this is a named acceptance test).

## Evidence-ledger census (2026-07-12)

Per [`.claude/docs/evidence-ledger-standard.md`](../docs/evidence-ledger-standard.md):

> **Claim (`:9-11`):** "no system serving new, typechecked formalizations of paper statements
> pinned to both a corpus revision and a formal environment as a queryable API."
> **Census set:** AXLE, formal-conjectures, SorryDB, Herald, TheoremGraph, LeanArchitect,
> Matlas. **Queries run:** per system — does it serve *pinned-and-served* paper-statement
> formalizations as a queryable API? **Date:** 2026-07-11, re-affirmed 2026-07-12
> (TheoremGraph's 68.1 / 98.8 / 76.6 / 42.7 precision table and its 22/24-typecheck-vs-5/24-
> faithful result byte-verified). **Verdict:** confirmed — each of the seven serves a different
> shape (conjecture banks, sorry-tracking, autoformalization, dependency graphs, statement
> mining); none is the pinned registry this track scopes. **Scope:** scoped over the seven
> named systems; closed commercial / non-English registries not checked.

**Correction (evidence-ledger `updated` discipline).** The "§8 excluded" phrasing at `:26-27`
and `:113` is a correct *inference* from BridgelandStability's stated "covers Sections 2–7"
scope — **not** a sentence any of its sources (`formalization.yaml`, `README.md`, coverage
site) asserts (byte-verified 2026-07-12; §8's identity as the group-action section comes from
Bridgeland 2007's own table of contents, not the repo). R5-m1's coverage matrix should phrase
it "scope statement is §2–7; §8-absence is inferred, not asserted." The engineering plan
(track §8 as debt) is unaffected.
