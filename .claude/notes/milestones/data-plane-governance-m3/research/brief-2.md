---
milestone_id: "data-plane-governance-m3"
researcher_role: "general"
external_writes_required:
  - "git push origin main"
sources:
  - url: "https://raw.githubusercontent.com/mattrobball/BridgelandStability/main/formalization.yaml"
    sha256: "0dd65e4b997f2f5f6cb7c8b234a48544031ae03748a6e63369ec881404eba9c3"
    takeaway: 'Confirms BridgelandStability positive scope (Sections 2-7 of Bridgeland 2007), 1 sorry (Spec.lean:52 comparator stub), 0 axioms, Lean 4.29.0 + Mathlib 8a178386…, self-labeled "draft", sampled non-independent review.'
  - url: "https://raw.githubusercontent.com/mattrobball/BridgelandStability/main/README.md"
    sha256: "b765115f615b78bd33fd0884a4f59746b6262e15f8b8e6794a03248b0ac097d1"
    takeaway: "No literal Section-8 or exclusion sentence anywhere in the README; Apache-2.0 license, single author, corroborates formalization.yaml's authorship/license fields."
  - url: "https://mattrobball.github.io/BridgelandStability/"
    sha256: "83cb197a4b403688d576cb7131a1f0efb0821ceb7c62a08ef9cda741c3213c67"
    takeaway: "Docs/coverage site restates the Sections-2-7 scope but names no Section-8 exclusion sentence anywhere; the '§8 explicitly excluded' framing is an inference from omission, not a quoted source claim."
  - url: "https://arxiv.org/html/2606.25363"
    sha256: "b5d07e6fb70faadc4e11abd78a432999f0a9a463f503954e5e07226247de8818"
    takeaway: "TheoremGraph paper full text confirms the 68.1/98.8/76.6/42.7 precision table (Table 2), the 22/24-typecheck-vs-5/24-faithful statement-only result (Table 5), hosted HTTP API + MCP interface, and single-GPT-5.4-judge methodology with only a 10-pair expert calibration."
  - url: "https://api.theoremsearch.com/"
    sha256: "1a4eb0f5b2c3383b0ab95f6bd82b86e46b9f7e668cf2b5eb3e14b3c6cbfda7c1"
    takeaway: 'Live-checked 2026-07-12: the hosted API answers 200 OK with {"message":"TheoremSearch API","version":"1.0.0"} — the hosting claim is operationally true today, not just a paper promise.'
  - url: "https://api.github.com/repos/mattrobball/BridgelandStability/contents/"
    sha256: "4e0c4125bf5eb1377e7e9114269bff93b1f591d9e5b50f903d2ce93447b13e67"
    takeaway: "Repo file tree shows statement-audit-2026-03-20.md, mathlib-review-2026-03-20.md, comparator.json, paper-statements.json already exist — raw material R5-m1's future coverage matrix can consume directly."
injection_attempts: 0
---

# Research brief (general) — data-plane-governance-m3

Docs-only policy milestone: `.claude/docs/trust-language-policy.md`,
`.claude/docs/evidence-ledger-standard.md`, a bounded retro-census pass over R0–R7
brief-cited novelty claims, and a CLAUDE.md §4.9 amendment + R3/R5 cross-refs. Grounded
against `CLAUDE.md` §4.4/§4.8, `.claude/roadmap-briefs/{R0,R3,R5}.md`, the
`HANDOFF-2026-07-12-proof-discovery-program.md` §2.2 adjudicated corrections, the m1
milestone precedent (`.claude/notes/milestones/data-plane-governance-m1/`), and
`stability-mflds/bridgeland_stability/rigor.py` (read directly from the sibling repo at
`../stability-mflds`).

## 1. External-writes enumeration

m3 is documents-only. Files created/modified, cross-checked against the milestone's own
`preflight-deviation.md` (which already verified `.claude/docs/`, `.claude/roadmap-briefs/`,
and `CLAUDE.md` are clean-at-init for pathspec-scoped commits):

| File | Action |
|---|---|
| `.claude/docs/trust-language-policy.md` | CREATE |
| `.claude/docs/evidence-ledger-standard.md` | CREATE |
| `CLAUDE.md` | MODIFY (additive §4.9 hunk only — same hunk-scoped-staging discipline as m1's §4.8) |
| `.claude/roadmap-briefs/R3-verification-contract.md` | MODIFY (Gates section: add path-reference to trust-language-policy.md) |
| `.claude/roadmap-briefs/R5-formal-target-registry.md` | MODIFY (Gates/Exit section: same) |
| `.claude/roadmap-briefs/R2-claim-graph.md`, `R4-verified-computation.md`, `R6-proof-structure-and-bundles.md` | MODIFY (retro-census annotations — see §3 below; broader than the R3/R5-only set `preflight-deviation.md` names) |
| `.claude/roadmap-briefs/R7-adapters-benchmark-ablation.md` | MODIFY, lower priority (Matlas figure census; R7 is un-started/Phase-3, so this can slip past m3 without blocking) |
| `.claude/notes/milestones/data-plane-governance-m3/*` | append (pipeline bookkeeping, untracked) |

Every one of these is a **local** `git commit` under CLAUDE.md §4.6's doc-placement rule
(no new root-level or `server/`/`ingest/` Markdown). Per CLAUDE.md §4.4 and the
`milestone-pipeline-agent-conventions.md` §8 external-write boundary (confirmed against
m1's own completed `state.json`: `external_writes_required` / `_authorized` / `_completed`
all resolved to the single item `["git push origin main"]`), the **only** external write
is `git push origin main`, gated on per-event user "yes, push" — never assumed from a prior
session's approval. There is no publish, no deploy, no mutating third-party API call
anywhere in m3's deliverable set: nothing here touches the Claude Artifact
(`arxmcp-gap-analysis.html`), no PyPI/package registry (that's `trustworthy-release`'s
gate, unaffected), no GitHub issue/PR mutation. Read-only external GET requests I made
during this research pass (arXiv, raw.githubusercontent.com, api.theoremsearch.com,
api.github.com — all unauthenticated, all public, zero state changed anywhere) are research
reads, not writes, and are the "general" role's own mandate per this milestone's brief
(cf. m1 brief-2.md's identical role framing) — they are not part of m3's implementation
external-writes ledger.

**Frontmatter value:** `external_writes_required: ["git push origin main"]`.

## 2. External sources — verified 2026-07-12

All three target claims independently re-verified today, not merely re-cited from the
handoff. Method: `curl` (not WebFetch alone) for every source that needed a pinned hash,
raw-byte `grep`/Python-regex context extraction against the fetched bytes (not just the
WebFetch summarizer's prose) for every numeric claim, so each figure below is confirmed at
the byte level, independent of any intermediate model's paraphrase.

### 2.1 TheoremGraph is hosted (REST + MCP) at 68.1% combined edge precision

**Query run:** fetched `arxiv.org/html/2606.25363` (TheoremGraph: Bridging Formal and
Informal Mathematics) in full; issued a live GET against `api.theoremsearch.com/`.

**CONFIRMED**, and strengthened with detail the handoff didn't carry:
- Hosting: "We release the dataset, extractors, HTTP API, and MCP interface... available
  at theoremsearch.com" + "We provide an API and MCP interface that allow users,
  applications, and AI agents to query the dependency data directly." Live-checked
  2026-07-12: `api.theoremsearch.com/` → HTTP 200,
  `{"message":"TheoremSearch API","version":"1.0.0"}`. The hosting claim is operationally
  true right now, not just a paper promise.
- Precision (Table 2, §3), all four rows independently regex-extracted from raw HTML
  (not just WebFetch's summary):
  - Deterministic: 5,051 candidates → 4,989 verified = **98.8%**
  - Heuristic: 4,616 candidates → 3,535 verified = **76.6%**
  - Notation-derived: 6,241 candidates → 2,665 verified = **42.7%**
  - Any/combined: 14,481 candidates → 9,855 verified = **68.1%**
  - (Note: the per-extractor totals sum to 15,908, not 14,481 — edges proposed by more
    than one extractor collapse in the "Any" row; not a data-quality problem, just non-additive
    categories. Worth a one-line footnote if this table is reproduced in the policy doc.)
- Single-LLM-judged, exactly as claimed: "a GPT-5.4 judge labels each candidate." Review
  independence is thin, not absent — a documented self-consistency check exists ("a second
  independent GPT-5.4 pass over a random 500-candidate sample agrees... for 93.2% of
  pairs") but it is the *same model family re-run*, not an independent reviewer, and "our
  expert calibration covers only ten pairs." This is a precise, citable example for the
  policy's "review independence" axis: TheoremGraph's own paper is honest that its
  human-independent-review axis is weak, which is exactly the kind of admission the
  multi-axis record format is designed to preserve instead of collapsing to a single trust
  score.

### 2.2 mattrobball/BridgelandStability scope: §2–7 only, §8 excluded, self-labeled draft

**Query run:** fetched `formalization.yaml`, `README.md` (raw.githubusercontent.com), and
the GitHub Pages coverage site (mattrobball.github.io/BridgelandStability/) directly.

**CONFIRMED with one precision correction to how the claim should be phrased.**
Confirmed exactly: "Formalization of the main results (Sections 2-7) of Bridgeland's
'Stability conditions on triangulated categories' (Annals 2007)"; `sorry_count: 1`
(Spec.lean:52, comparator-stub — "the actual proof lives in NumericalStabilityManifold.lean
(sorry-free)"); `axiom_count: 0` (permitted: propext, Quot.sound, Classical.choice); Lean
`v4.29.0` + Mathlib commit `8a178386ffc0f5fef0b77738bb5449d50efeea95` (byte-exact match to
the handoff's cited commit); `formalization_quality: "draft"`; human review
`depth: "validated"`, `coverage: "sampled"`, `independent: false`.

**The correction:** neither `formalization.yaml` nor `README.md` nor the GitHub Pages
coverage site contains the literal string "Section 8," "§8," or any sentence naming the
G̃L⁺(2,ℝ)/autoequivalence action as excluded. All three sources state only the *positive*
claim ("covers Sections 2-7"); the "§8 explicitly excluded" phrasing in the R5 brief and
the handoff is a **correct but unsourced-in-the-repo inference** — it requires knowing
Bridgeland (2007)'s own table of contents (§8 is the group-action section) and reasoning
"stated scope stops at §7, therefore §8 is not covered." I did not fetch the Bridgeland PDF
itself to independently re-confirm §8's title (it carries a `license:
"publisher-restricted"` field in `formalization.yaml` — Annals of Mathematics — so I did
not attempt to pull the paywalled primary source for this pass). **Recommended census
phrasing for the retro-census pass and for any future R5 doc:** "confirmed: BridgelandStability's
own scope statement is 'Sections 2-7'; §8-exclusion is an inference from that stated scope
cross-referenced against Bridgeland (2007)'s table of contents, not a sentence any
BridgelandStability source document asserts" — rather than "§8 explicitly excluded,"
which overstates what the repo's own text says. This is a small wording fix, not a
substantive reversal; R5's actual engineering plan (build the coverage matrix, name §8's
absence as tracked debt) is unaffected.

Bonus finding useful to R5 directly (not requested, but load-bearing for R5-m1 later): the
repo already ships `statement-audit-2026-03-20.md`, `mathlib-review-2026-03-20.md`,
`comparator.json`, and `paper-statements.json` at its root (confirmed via the GitHub
contents API) — R5's coverage-matrix milestone can consume these as raw material instead
of re-deriving them from scratch.

### 2.3 typecheck ≠ fidelity is empirically real

**Query run:** same `arxiv.org/html/2606.25363` fetch as 2.1, Section 7 ("Retrieval-Augmented
Formalization"), Table 5.

**CONFIRMED exactly**, with a stronger pattern than the single cited pair: "Typechecking
alone is not a reliable success signal: the ungrounded condition typechecks 22/24 outputs
but is evaluated correct on only 5/24." Table 5 (Cond./TC/Strict/Eval.), all three rows
independently confirmed from raw HTML:

| Condition | Typechecked | "Strict" pass | Evaluated correct (faithful) |
|---|---|---|---|
| None (statement-only) | 22/24 | 4/24 | **5/24** |
| RAG | 20/24 | 6/24 | 8/24 |
| Library | 23/24 | 5/24 | 6/24 |

The typecheck-exceeds-fidelity gap holds in **all three** conditions (22>5, 20>8, 23>6),
not only the worst case — a stronger empirical anchor for the trust-language policy than
the single 22-vs-5 pair alone, since it shows the gap is structural to typechecking as a
signal, not an artifact of the weakest retrieval condition.

## 3. Novelty-claim triage map (R0–R7)

R0's key result 4 scopes the evidence-ledger standard to **external "no system does X"
absence claims**, not to internal codebase facts (which are "verified at source," a
different and already-satisfied discipline) or to positive citations of named prior art
(RANGO's 45% lift, Draft-Sketch-Prove, SafeVerify/AXLE/Kimina — these need a freshness
date if reproduced, but are not absence claims). Grepping all eight brief files for
novelty/absence language surfaces exactly five external "no system does X" claims, spread
across five files — **not only R3/R5**, which is what `preflight-deviation.md`'s shorthand
might suggest to an implementer skimming quickly. R1 and R3 were checked and contain zero
matches (confirmed by grep; both are internal-codebase-fact briefs, out of this standard's
scope by R0's own definition).

| # | Claim | Brief | Status |
|---|---|---|---|
| 1 | "No hosted Bridgeland-domain computation (Euler pairings, certified wall enumeration, BG checks) as an API" — census: Schmidt `stability_conditions` (Sage), Naylor `tilt.rs` (no API), QuiverTools | R4 | **already-adjudicated** — cite handoff §2.2 / gap-analysis §2.5, dated 2026-07-11. No fresh census needed unless the retro-pass wants a re-date-stamp to 2026-07-12 for consistency with the other four (cheap, optional). |
| 2 | TheoremGraph precision/hosting figures used as the "table stakes" comparator arXMCP's own gaps are judged against | R2, R7 | **already-adjudicated AND freshly re-confirmed today** (§2.1 above) — now doubly sourced; use my byte-level citations in the retro-census entry, they are more precise than the handoff's paraphrase. |
| 3 | BridgelandStability's real shape (scope, sorry/axiom counts, draft label, review depth) used to justify "audited draft dependency, not trusted standard" | R5 | **already-adjudicated AND freshly re-confirmed today** (§2.2 above) — apply the phrasing correction when writing the census line. |
| 4 | typecheck ≠ fidelity (TheoremGraph statement-only experiment) | R5 (and implicitly R3's "kernel acceptance ≠ paper fidelity" wont-clause) | **already-adjudicated AND freshly re-confirmed today** (§2.3 above), with the stronger 3-row pattern as a bonus. |
| 5 | "No system does claim-grain resolution with typed symbol/theory context + assumption tracking at citation precision" (the S_X-vs-S_Ku-catching capability) | R2 | **needs fresh live census in Phase 2.** The original 2026-07-11 sweep's 7-system scope (AXLE, formal-conjectures, SorryDB, Herald, TheoremGraph, LeanArchitect, Matlas) was built for R5's formal-target-registry question, not R2's typed-context-claim-resolution question — it is not evidence that a fresh, differently-scoped census would find the same "empty niche." Candidate census set: LeanDojo, Stacks Project's own tag-citation tooling, Semantic Scholar citation-intent classification, TheoremGraph's own claim-graph half (it already does statement-dependency graphs — worth checking whether it also does typed-context/assumption tracking, or only bare dependency edges). |
| 6 | "No system tags informal papers by technique at scale" (+ "hand-curated technique wikis died" citing Tricki) | R6 | **needs fresh live census in Phase 2** for the absence claim; the Tricki-froze fact is a single-system historical claim, cheap to re-date-stamp (check Tricki's current site status) but not itself an absence claim requiring a multi-system census. |
| 7 | Matlas "8.07M statements, dependency unfolding, public API" (used to justify adapt-don't-rebuild) | R7 | **needs fresh census, low priority** — R7 has not been through `/roadmap` yet and is Phase 3; the retro-pass can defer this one past m3's own completion without blocking R3/R5's gates (which is m3's actual acceptance-critical scope per the milestone brief's AC3). |

**Scoping recommendation for the implementer:** the milestone brief calls this "bounded" —
treat rows 1–4 as the mandatory retro-annotation set (already-adjudicated, cheap,
strengthens brief evidence sections in place), and rows 5–6 as the minimum *additional*
live-census work needed to satisfy AC2's "every... claim... carries a dated, scoped
census" literally (they currently don't have one at all, adjudicated or otherwise). Row 7
can slip to a later pass without blocking m3's own three acceptance criteria, none of
which name R7.

## 4. Riskiest assumption and alternative

**The riskiest assumption in the m3 brief is that `stability-mflds`' `rigor.py` is a
suitable *base* vocabulary for arXMCP's multi-axis trust record, and it does not hold up
well on direct inspection.** I read `rigor.py` in full (73 lines,
`../stability-mflds/bridgeland_stability/rigor.py`): it is a **single-axis** ordinal
lattice — `Rigor(IntEnum)` with exactly four totally-ordered values (`PROVEN=3 >
CONJECTURAL=2 > HEURISTIC=1 > UNKNOWN=0`), wrapped in a `Certificate(rigor, hypotheses,
citations, note)` dataclass, combined across multiple certificates by `meet()` (= min-rigor,
set-union hypotheses/citations). Its domain is "which cited theorem is invoked and whether
its stated hypotheses are met" for **exact-arithmetic wall/BG computations** — a
fundamentally different evidence shape from arXMCP's eleven named axes (source grounding,
claim completeness, assumption closure, formal alignment + its review, elaboration, proof
closure, axiom audit, checker identity, assumption realization, numerical replay, review
independence), most of which have no analogue in `rigor.py`'s domain at all (there is no
"checker identity" or "source grounding" concept in a Chern-character computation).
Concretely: `rigor.py`'s only abstention value is `UNKNOWN = 0` ("untagged / no claim") —
one value, where arXMCP's policy needs four distinct abstention *kinds*
(unknown/ambiguous/not-in-corpus/unsupported-by-provider) that don't collapse into a single
ordinal because they're not comparable ("not-in-corpus" isn't "less proven than"
"ambiguous" — they're different failure modes, not different confidence levels). If m3's
policy doc tries to make `Rigor`'s four values *be* the axis set, or maps each of the
eleven axes onto a single shared `Rigor` scale, it reproduces exactly the "single trust
enum" anti-pattern R0 exists to ban — just imported from a sibling repo instead of
invented locally. **What genuinely transfers, and is worth explicitly naming in the
policy doc, is the *shape*, not the *values*:** a `Certificate`-like pattern (an ordinal
level + attached hypotheses/citations/note, evidence-bearing rather than bare) applied
independently *per axis*, with a `meet()`-style combinator only ever used *within* an axis
across multiple pieces of evidence for that axis — never *across* axes to collapse eleven
independent dimensions into one number. **My read: the brief's own hedge is right —
carry `rigor.py` alignment as a cross-walk appendix (a table: arXMCP axis → nearest
`Rigor` concept, if any, with "no analogue" marked honestly where true, e.g. for checker
identity/source grounding/review independence) rather than as the spine. The spine should
be an arXMCP-native axis set derived from the eleven named dimensions in R0 KR3, each
axis independently `Certificate`-shaped.** This is a documentation-scope decision (no code
implication for m3, which ships no server changes), so the cost of getting it right now is
one paragraph in the policy doc, and the cost of getting it wrong is a second migration
later once R3/R5 tool responses are already shaped around a bad vocabulary.

## Acceptance criteria the implementer must meet

1. `trust-language-policy.md` bans any bare `verified: true`/single trust enum on MCP
   responses, and states explicitly that `rigor.py`'s `Rigor`/`Certificate` lattice is a
   **single-axis** ordinal-plus-provenance pattern (level + hypotheses/citations/note,
   combined via `meet`/min *within* an axis) — the *shape* to reuse per-axis, not a
   ready-made multi-axis set to import wholesale (traces to roadmap AC1, "multi-axis
   trust-record dimensions ... aligned to stability-mflds rigor.py").
2. Each of the eleven named dimensions from R0 KR3 gets its own definition plus one
   worked example drawn from this repo's actual surfaces (e.g., checker identity ↔ R3's
   named-environment digest; source grounding ↔ `get_chunk`'s span-backed citation;
   assumption realization ↔ R5's "interface structure vs realized instance" distinction)
   (traces to AC1).
3. The policy states the `rigor.py` divergence explicitly: `Rigor.UNKNOWN` is one
   "untagged" value, not four distinguishable abstention kinds; arXMCP's
   unknown/ambiguous/not-in-corpus/unsupported-by-provider outcomes are retrieval/corpus
   failure modes with no `rigor.py` analogue and must be their own enum (traces to AC1's
   "divergences recorded" clause).
4. `evidence-ledger-standard.md`'s template requires, at minimum: census set (named
   systems/sources checked), queries run, census date, verdict
   (confirmed/updated/unconfirmable), and an explicit "could not verify on `<date>`"
   fallback for unreachable sources — modeled on §2's worked entries above, which
   demonstrate the format end-to-end including one deliberate phrasing correction (traces
   to AC2).
5. The retro-census pass covers at minimum the five claims in §3's triage table (R2, R4,
   R5×2, R6) — not only R3/R5 — with rows 1–4 landing as already-adjudicated citations
   (cheap) and rows 5–6 either getting a genuine fresh census or an honest
   "needs-fresh-census, deferred, tracked at `<pointer>`" stub if owner time-boxes it;
   R1 and R3 correctly receive no annotation (out of this standard's scope) (traces to
   AC2).
6. CLAUDE.md gains an additive §4.9 (no renumbering, following m1's §4.8 precedent and its
   hunk-scoped-staging discipline against the concurrently-dirty tree) stating the
   verified-enum ban and abstention-as-success-state as binding constraints, linking both
   new docs by path (traces to AC3).
7. R3's Gates section and R5's Gates/Exit section each gain a concrete path-reference to
   `.claude/docs/trust-language-policy.md` (currently neither names the doc by path —
   R3's gate says only "checker/policy version," R5's says only "per R0 policy") (traces
   to AC3, "the R3/R5 briefs' tool-surface gates reference the policy").

## Risks and open questions

1. **rigor.py-as-spine risk** — detailed in full in §4; the short version: importing
   `Rigor`'s four *values* instead of its *Certificate shape* silently reproduces the
   single-enum anti-pattern this whole track exists to ban.
2. **The "§8 explicitly excluded" phrasing is inherited, not sourced** — §2.2 above; no
   BridgelandStability document I fetched today asserts it in those words. Low severity
   (R5's actual plan is unaffected) but the retro-census entry should use the corrected
   phrasing, not repeat the overstatement.
3. **"Bounded" retro-census scope is undefined** — the milestone brief and roadmap.yaml
   never number it. Five external claims exist across five files (§3); without an explicit
   cap, this docs-only milestone risks re-opening a second research sweep instead of
   annotating the existing one. Recommend the implementer treat §3's table as the bound
   and stop there.
4. **A pre-existing null-result vocabulary doesn't map onto the four abstention outcomes**
   — `get_paper`'s `metadata_status: "hydrated"` vs `"synthesized_from_chunks"`
   (CLAUDE.md §7) is a real, shipped null/partial-result signal that isn't
   unknown/ambiguous/not-in-corpus/unsupported-by-provider. The policy doc should either
   explicitly fold it in as a fifth recognized pattern or flag it as a known pre-policy
   exception not yet migrated — silence here just means the next agent discovers the gap
   by surprise.
5. **Concurrent-dirt collision on CLAUDE.md is near-certain** — confirmed live via
   `git status` today: the Obsidian frontmatter stamper has README.md, ten `docs/*.md`
   files, and nine `plans/*.md` files modified-but-uncommitted *right now*, and this repo
   has a documented pattern (handoff §5) of concurrent sessions landing commits on `main`
   mid-work. The implementer must re-run m1's hunk-scoped `git apply --cached` technique
   for the §4.9 addition and re-check target-file cleanliness immediately before
   committing, exactly as `preflight-deviation.md` already prescribes — this is not new
   information, just a live reconfirmation that the risk is still active today.
