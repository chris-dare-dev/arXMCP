<!-- scan provenance: generated 2026-07-25..29; moved here 2026-07-29 -->

> [!info] Discovery capability gap analysis — arXMCP scan, 2026-07-29
> **Method.** 6 diverse lenses -> duplicate/feasibility screen against 200 issues + 9 roadmaps + the R0-R7 briefs -> 2 adversarial judges (discovery leverage, solo-maintainer buildability) -> completeness critic. 31 candidates, 26 surviving capabilities in 6 themes.
> **Status.** **Partly executed.** Themes 1-4 became `plans/discovery-substrate/roadmap.yaml` -> issues **#211-#233** under milestone **#8**. Themes 5-6 (statement graph, object axis) were scoped OUT and are recorded in that roadmap's `goal.wont`. Every score in section 3 is a **prior, not a measurement** -- section 6 says so, and names the discovery-backtest spike that would settle it.
> **Origin.** Produced in a single principal-engineer review session; the board state it
> cites was read live from the GitHub API. Numbers are dated -- re-verify before acting on
> any of them.

# arXMCP — Discovery Capability Gap Analysis

*What more do LLM agents need from arXMCP to reach novel proofs and findings faster?*

Author: principal-engineer synthesis, 2026-07-25.
Inputs: six lens scans (31 candidate capabilities), a duplicate/feasibility screen against
200 tracked issues + nine `plans/*/roadmap.yaml` + eight `.claude/roadmap-briefs/R0–R7`,
two independent judge rankings, one completeness critique, and independent re-measurement
of the live 173-paper corpus.

All corpus numbers below tagged **[measured 2026-07-25]** were reproduced independently for
this document against `var/arxmcp/corpus/`. Where a lens's number and mine differ, mine is
quoted and the difference noted.

---

## 0. The thesis

arXMCP today is an excellent **mathematical reading surface** and it is honest about being
one. It takes arXiv HTML through LaTeXML, chunks it theorem-aware, embeds statement and
proof columns separately, and serves eight tools — `search_papers`, `get_chunk`,
`find_equation`, `get_definitions`, `find_lemma_by_name`, `get_paper`, `cite_neighbors`,
`lean_verify` (`server/tools.py:422-431`). The math fidelity is real: MathML with parallel
markup rather than PDF text extraction, per-paper macro tables, content-addressed chunks,
a per-revision provenance track in flight. An agent using arXMCP can find the right theorem,
read its actual statement with its actual notation, follow it to its proof, and walk the
citation graph. That is not a small thing and most of the six live roadmaps are correctly
aimed at making it better: proof-column retrieval, TED equation search, definition filters,
truthful tool schemas, license provenance, a real eval harness.

The class of discovery that supports is **synthesis**: an agent that reads faster and more
accurately than a human can assemble a survey, spot a connection between two papers, or
supply the right lemma to a proof attempt. That is genuinely useful and it is what the
retrieval-unlocks and evidence-engine tracks will deliver. It is not, however, the class of
discovery in the motivating context. Look at what the recent machine-found results actually
were. The Batyrev counterexample (Satriano–Usatine, arXiv:2607.19184, 2026-07-21) is a
*specific singular variety* with a negative stringy Hodge number — a finite computation on a
constructed object. The ℂ³ Jacobian counterexample (Alpöge/Fable, digested by Tao 2026-07-21)
is a *specific degree-7 map* with a three-point collision, found only after re-coordinatising
via resultants, symmetric powers and SL₂-equivariance because raw search was hopeless at
~1,329 constraints against ~360 degrees of freedom. The Grothendieck refutation (mathlib PR,
2026-07-11) is an *order-4 group scheme*. Every one of them is: construct or enumerate an
object → compute an invariant exactly → notice a violation → certify. None of them was
blocked on finding the right paper.

The structural reason arXMCP is not yet a discovery surface is narrower and more actionable
than "it needs objects and compute". It is this: **arXMCP has no representation of a negative
result, in either direction.** It cannot retrieve the literature's own negatives — the
sentences where an author writes "the hypothesis cannot be dropped, see Example 5.3", "this
bound is sharp", "it is not known whether the converse holds", "we do not know" — because
those are prose inside chunk bodies and `search_papers` is dense ANN over BGE-M3 statement
embeddings (`server/tools.py:255-257`), which ranks mathematical *topic* and is blind to
epistemic *stance*. It cannot compute a negative: `lean_verify`'s mode enum is
`Literal["full","syntax_only","tactic_step"]` (`server/handlers/lean_verify.py:736`) and its
status vocabulary has no token that can mean *this statement is false and here is the
witness*, even though `plausible` is physically installed at
`C:\Users\cedar\lean-repl-spike\repl\.lake\packages\plausible` and unreachable. And it cannot
*store* a negative: there is no attempt record, no coverage record, no computation record —
`grep -rn "counterexample|refut|attempt_id" server/ ingest/ tools/` returns exactly one hit,
the word "refutes" inside a prompt string at `server/prompts.py:150`. So the ~90% of a
counterexample hunt that consists of ground covered and found empty evaporates at session end,
every session, and the fleet re-walks it.

That single absence explains why the capability map below is empty in five of its seven
columns. A discovery loop is a *falsification* loop; arXMCP is instrumented end-to-end for the
half of it that reads and has nothing for the half that rules out. The two judges disagreed
about which half of the pipeline matters — one ranked objects and compute at 9, the other
ranked mining and hygiene at 9 and killed the object layer at 2 — and both were scoring the
same underlying fact from opposite ends: the finding step is unequipped, and the cheapest
equipment for it is already sitting on disk unread.

**The single biggest missing thing is the negative as a first-class object** — mined from the
corpus, computed by a falsifier, and recorded as a dated scoped census. Under it sits one
unnamed prerequisite that nine separate proposals each silently assumed: there is no
sentence-addressed layer and no shared mining substrate, so nine lexicons would ship with nine
incompatible span conventions and a summed 500–900 hand-adjudications — which is the labeling
campaign constraint 8 forbids, assembled from nine pieces that each truthfully claim to be a
bounded sample.

---

## 1. The capability map

The discovery loop, against what arXMCP provides at each stage. **SERVED** = works today.
**PLANNED** = a live roadmap or adjudicated brief owns it (cited). **ABSENT** = nothing in the
200 issues, nine roadmaps, or eight briefs.

| # | Stage | The agent's actual question | What arXMCP does today | Status |
|---|---|---|---|---|
| 1 | **Notice** | "Where is there an unguarded claim, an anomaly, a live target?" | `search_papers` dense ANN over `embedding_stmt`. Ranks topic, not stance. `kind='conjecture'` **is written** by the chunker (`ingest/chunker.py:230-231,263`) and **no tool reads it** — 94 conjecture + 36 problem environments sit unreachable. | **ABSENT** (kind facet is #40 / retrieval-unlocks-m5, definition-only; R6-KR4 extends it) |
| 2 | **Locate the frontier** | "What in this area is open? What was quietly settled in 2019 by a paper I already ingested? What is claimed sharp?" | Nothing. No conjecture entity, no resolution evidence, no sharpness/necessity index. 262 boundary assertions across 90+/173 papers are pure prose. | **ABSENT** |
| 3 | **Understand hypothesis usage** | "What does this theorem actually assume, including what §0 said and never repeated? Where is each hypothesis used?" | `get_chunk(include_referenced=True)` resolves stmt↔proof (#36, closed). Conventions chunks (`kind∈{convention,assumption,notation,hypothesis}`, `ingest/store.py:133-167`) are written and **nothing joins them** to the theorem. | **PARTIAL / PLANNED** (R2-m3 `effective_hypotheses`; R2-KR3 `get_claim_context`) |
| 4 | **Reduce the search space** | "What reduction shrinks this problem? Which hypotheses came free from a WLOG?" | Nothing. The Kùzu model is `papers` nodes + `cites FROM papers TO papers` (`ingest/kuzudb_schema.py:73-90`) — no implication, reduction, or equivalence relation exists at any grain. | **PARTIAL / PLANNED** (R2-KR1 `restates`/`specializes`/`invokes`; R6-KR1 in-proof "reduce/transform goal". **Paper-level reductions with their added hypotheses: ABSENT**) |
| 5 | **Construct / enumerate a candidate** | "Give me the family. Give me one explicit object of this shape." | Nothing. The entire schema is text- and citation-shaped; no object table, no numeric-attribute index, no predicate scan. All eight tools return text or Lean results. | **ABSENT** |
| 6 | **Test / falsify** | "Is this false? Show me a witness." | Nothing. `lean_verify` proves; it has no refutation mode and no status token that can express *false*. A hand-rolled `#eval` returns an untyped string in an `info`-severity `messages[]` row (`server/handlers/lean_verify.py:309-330`). No CAS, no exact-arithmetic path. `ascii_form` — the executable form of the corpus's own equations — is written as `""` unconditionally (`ingest/extract_equations.py:195,264` **[verified]**). | **ABSENT** |
| 7 | **Verify** | "Is this proof correct? Under what axioms, against which library?" | `lean_verify` with env/proofState continuation. Real. Hardening planned. But the result envelope carries **no library identity at all** — `grep -niE 'toolchain\|mathlib_rev\|lean_version'` over the 42 KB handler returns 0. | **SERVED**, hardening **PLANNED** (R3-KR1–KR5, R3-m1 honest statuses, R3-m5 named envs) |
| 8 | **Record** | "Has this been tried? Has this been computed? Was this range covered? Is it actually new?" | Nothing. No attempt record, no computation record, no coverage record, no novelty census. `grep -rn "counterexample\|refut\|attempt_id" server/ ingest/ tools/` → 1 hit, a prompt string. | **ABSENT** (adjacent: #69 basic-memory free-text notes; R6 scope-out defers curated attempt ingest) |

Two cross-cutting rows, because they are gaps in *fidelity* rather than in the loop:

| # | Modality | What the corpus holds | What arXMCP serves | Status |
|---|---|---|---|---|
| 9 | **Diagrams** | **[measured]** 323 captioned `ltx_figure` floats in 55/173 papers; **1,483 inline `<svg>` in 120/173 papers**, class `ltx_picture ltx_markedasmath` with ids like `S3.Ex25.m1.1.1.pic1` — i.e. TikZ/tikz-cd renderings that **LaTeXML itself classified as mathematics**, 262 of them literally inside `<math>` elements; plus 203 `ltx_graphics` / 561 `<img>`. | Nothing. `figure` is in the chunker's non-recursed list (`ingest/chunker.py:757`) and `grep -rn 'ltx_figure\|ltx_graphics\|tikz' ingest/ server/` returns **0** **[verified]**. Zero of 200 issues, zero of nine roadmaps, zero of eight briefs. | **ABSENT** |
| 10 | **Notation across papers** | 164 `preamble.json` files on disk; 14,537 macros, 3,429 distinct symbols, **661 (19.3%) genuinely divergent after typographic normalisation** — `\D` spans derived category / D-modules / the disc; `\H` spans cohomology / quaternions / upper half plane. | `get_definitions` **requires** a `paper_id` (`server/handlers/definitions.py:68-69`); `DEFINITIONS_SCHEMA_V1` has `paper_id` non-nullable and no term column. No corpus-level view of a symbol, no two-paper diff. | **ABSENT** (adjacent: #40's corpus-wide term index, deliberately gated) |

Read down the Status column: the loop is served at exactly one stage (7), partial at two (3, 4),
and absent at five (1, 2, 5, 6, 8) plus both fidelity rows. Every live roadmap improves stage 3
and the retrieval that feeds stage 1. Nothing in the current plan touches 2, 5, 6, 8, 9, or 10.

---

## 2. The prerequisites

Three capabilities that many others depend on. Two are in the proposal set below; naming them
here because sequencing without them produces nine incompatible half-builds.

### P1 — The span-addressed sentence layer and one shared mining substrate

Nine of the surviving proposals are the *same mechanism* wearing different subject matter:
a curated regex lexicon over already-parsed LaTeXML prose, emitting a match with a verbatim
evidence span, a per-match confidence, an abstention token, and a hand-scored precision sample.
Each independently specifies a span field (`cue_span`, `char_span`, `sentence`, `evidence span`)
and each independently budgets "author a lexicon + hand-score 50–100 matches".

None of that infrastructure exists. There is no sentence segmentation anywhere in `ingest/` or
`server/` — the one component that needed it worked around its absence:
`ingest/extract_equations.py:44` states *"No sentence tokenization at v1"* and falls back to the
enclosing `<p>` capped at 4,000 chars. There is no lexicon file format, no match table, no
precision sampler, no coverage reporter.

Three consequences of leaving this unnamed. **(a)** Nine incompatible offset conventions, which
makes the highest-value object in the corpus — a single sentence that is simultaneously a
necessity claim, a technique cue, and a scope reference — structurally inexpressible, so the
miners can never compound. **(b)** Evidence spans that break silently when chunk boundaries move,
a failure `source-truth-m2` already hit and documented as requiring abstention. **(c)** The summed
hand-scoring is 500–900 adjudications — a labeling campaign, forbidden by constraint 8, assembled
from nine individually-honest "bounded sampling exercises".

Build it once and each miner becomes a versioned YAML file plus one sampler run. Nine M-sized
proposals collapse to one M and eight S's, **and they become joinable.**

### P2 — A measured discovery backtest

There is no instrument that measures discovery, and none is planned. `evidence-engine` measures
*retrieval* — nDCG, pass^k over ~8–10 curated tasks (#19) — which ranks chunks, not theorems.
Consequently 31 proposals were ranked entirely on argument, and the two judges' theses disagree
at the root about which half of the pipeline matters, with nothing that could settle it.

The instrument is cheap and mechanical: publicly dated discoveries exist, the corpus already
versions itself, ingest is date-filterable through the OAI delta harvest, and "were the
ingredients reachable from a corpus frozen before this date" is answerable per ingredient with
verdicts `reachable-in-k-calls` / `present-but-unretrievable` / `absent-from-corpus` /
`unanswerable-by-current-surface`. Three cases at ~1 owner-day each is **less than the owner cost
of any single L-sized proposal it would help rank**, and it is the only spend here that reduces
the risk of the other spends.

### P3 — One census record type, one verdict vocabulary

Five separate proposals independently invented a census artifact, and defined it five different
ways. That fragmentation is a trust-policy failure in slow motion: CLAUDE.md §4.9 rule 3 binds
novelty claims to be dated scoped censuses, and five parallel schemas with five verdict enums
guarantees at least one of them grows a token that reads as "novel".

Note a correction the screen surfaced and which must not be repeated in issue text: the
evidence-ledger standard (`.claude/docs/evidence-ledger-standard.md`, **Accepted 2026-07-12**)
already exists, already carries a 5-field census template in §4, and its retro pass over R0–R7 is
**done**. The claim that "the trust policy mandates an artifact the system has no way to emit" is
false as stated. What is genuinely absent is a *runner* for a claim class the standard explicitly
does not govern — mathematical-result novelty — and the right move is to extend that standard with
a new claim class, not fork a parallel one.

**Two conditions, not capabilities, that also gate work below.** *Corpus closure*: every high
scorer undercuts itself with the same number — **[measured]** only ~10% of statement-level
citation locators resolve to a paper this corpus contains, so dependency cones are shallow, the
negative-space complement view cannot rank, and cross-paper reduction targets have almost nothing
to resolve against. That is one common cause, and nobody proposed the decision to grow with a
stopping rule. *A warm Mathlib-resident Lean environment*: R3-m5/m7's, nobody's deliverable in
this set, and four Theme-2 items are scheduled fiction until it lands — the known residual is that
a 30 s query timeout is shorter than a cold `import Mathlib`.

---

## 3. Proposed capabilities

Scores carried from the two judges as **D** (discovery leverage, 0–10) and **B** (buildability
and durability for a solo maintainer, 0–10). Where a capability merges several proposals, the
range is given and the disagreement noted. Boundary compliance is stated per capability against
the binding constraints: **[5]** = data-plane ADR, **[6]** = trust language, **[7]** = license,
**[8]** = owner-hours.

Themes are ordered by leverage.

---

### Theme 1 — Mine the literature's own negative space

**Thesis.** The corpus already contains a large, unretrievable record of what is false, sharp,
necessary, reduced, and open — written by mathematicians who checked. Every one of those sentences
is either a candidate killed before a run is spent, or a pointer at an existing counterexample
object to mutate, or an unguarded claim worth attacking. Nine proposals arrived at the same
deterministic-regex mechanism because cross-synthesis §5 items 10–12 ban LLMs at ingest and item
16 discourages new tools, leaving prose mining as nearly the only unclaimed move. That convergence
is not validation — it is a narrow search space — and the correct response is to build the
mechanism *once*, then treat each miner as a data file.

---

**1.1 `span-substrate` — sentence layer, lexicon format, match table, precision sampler**
*(new; extracted by the completeness critic from nine proposals)*

- **Blocked today.** Nine capabilities each need a stable verbatim evidence span and a way to
  publish measured precision. Neither exists; `ingest/extract_equations.py:44` documents the
  workaround ("No sentence tokenization at v1", 4,000-char paragraph fallback).
- **Mechanism.** (a) `ingest/sentences.py` emits `sentences(sentence_id, chunk_id, paper_id,
  ordinal, text, char_start, char_end)` with `sentence_id` content-addressed over
  (chunk_id, normalised text, ordinal) — stable under re-ingest, *visibly* invalid when the text
  changes. Segmentation is math-aware: never split inside `<math>`, inside a `\cite` group, or on
  a closed abbreviation list (Prop., Thm., Cor., resp., i.e., e.g., cf.). (b) One
  `markers(match_id, sentence_id, lexicon_id, lexicon_version, class, cue_span, confidence,
  extractor_status)` table for **all** miners. (c) A lexicon is a committed YAML file: id,
  version, classes, cue regexes, suppression guards, chunk-kind restriction. (d)
  `tools/lexicon_audit.py` samples stratified by class, and emits per-class precision plus a
  coverage denominator as a dated record in the existing 5-field census format.
- **Surface.** `new-index`, `new-offline-cli`, `schema-change`, `extend-mcp-tool` (one
  `filters.marker_class` key for all miners, riding the next W1 batch).
- **Why it accelerates.** Converts ~9 M-sized items into one M plus eight S's; converts 500–900
  scattered adjudications into one sampler per lexicon; and — the part that actually matters —
  makes the miners *compound*, because a single sentence carrying a necessity marker AND a
  technique cue AND a scope reference becomes a join rather than three unrelated rows.
- **Size** M. **Depends on** nothing.
- **Risks.** Research-math segmentation is hard (display math mid-sentence, enumerated
  hypotheses) — must emit `segmentation_status=unsegmentable` and let miners fall back to
  paragraph grain rather than guess. Centralisation risk: ship the sentences table and match
  schema first, sampler second, so a miner can write rows before the sampler exists. Keep the
  lexicon format declarative regex + guards; the moment it becomes a rules engine it acquires its
  own maintenance burden.
- **Boundary.** [5] offline CLI writes, MCP reads, no LLM anywhere — this is precisely the
  substitution cross-synthesis §5 item 10 leaves open. [6] `extractor_status` and confidence are
  separate axes with the cue span as evidence; `no-cue-matched` (abstention) distinct from
  `not-indexed` (operational). [7] corpus-internal, no external data. [8] ~2 owner-days, of which
  only the abbreviation guard list is judgement; *net across the family it reduces owner-hours by
  roughly an order of magnitude.*
- **Scores.** D — / B — (unscored by the judges; it postdates them). My assessment: **D 6, B 9.**

---

**1.2 `boundary-markers` — necessity, sharpness, counterexample pointers, unsupported assertions**
*(merges L1-claim-status and L5-negative-space; judge 1 explicitly flagged the overlap: "build one miner, not two")*

- **Blocked today.** An agent evaluating whether a hypothesis is essential must read whole papers.
  An agent looking for an unguarded claim has no way to find one. Dense ANN over statement
  embeddings ranks topic, never stance (`server/tools.py:255-257`); querying "is the normality
  hypothesis necessary here" returns topically similar theorems and never the sentence "normality
  cannot be omitted, as Example 5.3 shows".
- **Mechanism.** One lexicon under `span-substrate` with classes {necessity, sharp,
  converse-fails, counterexample-pointer, open, asserted-unsupported}. Necessity:
  `cannot be (omitted|dropped|removed|weakened)`, `is (necessary|essential)`, `fails without`.
  Sharp: `sharp`, `best possible`, `cannot be improved`. Open: `it is (not known|unknown) whether`.
  `asserted-unsupported`: `it is (well[- ]known|standard|classical) that` with **no `ltx_bibref`
  anchor in the sentence and no local proof chunk** — deterministic, because
  `ingest/intra_paper_refs.py:126-127` makes the citation test exact. Restrict candidates by
  existing chunk kinds (remark / example / question / problem) for high precision. Target
  attachment resolves via an `\ref` anchor, else nearest preceding theorem-kind chunk in-section,
  with `attribution ∈ {anchored, adjacency, unattributed}` as its **own axis**.
- **Surface.** lexicon file + `find_claim_boundary(...)` or an additive `markers` block on
  `get_chunk`.
- **Why it accelerates.** Serves loop stages 2 and 6 in opposite directions from one pass. A
  `necessity` marker is a mathematician saying *already checked, and here is the witness* — it
  kills a candidate before a full pipeline run and points at an existing counterexample object to
  mutate, which is the fastest route to a new one. An `asserted-unsupported` or bare `sharp` with
  no supporting example is the inverse: the highest-yield place to attack. The fastest route to a
  novel result is usually not a famous conjecture — it is the paper where the author wrote "we
  expect this holds without properness".
- **Size** M (S once the substrate exists). **Depends on** `span-substrate`.
- **Risks.** Precision is the whole quality story: `sharp` collides with `\sharp` and sheaf
  notation; "necessary and sufficient" is not a necessity marker; "need not hold" appears as both
  boundary claim and ordinary exposition. Recall is capped — a counterexample stated as a bare
  example with no cue is invisible, so an empty result must never read as "no boundary exists".
  **The complement view** ("theorems with no recorded necessity witness, ranked by dependency-cone
  size") is the discovery payload and also the dangerous part: it must be cut from v1 or
  hard-gated behind measured precision, because a low-precision complement actively misdirects
  target selection and reads as a categorical openness claim.
- **Boundary.** [5] offline miner, read-only serving. [6] confidence, attribution and
  `cite_present` are three separate axes with **no inference between them**; the server asserts
  only *paper P states this*, never that the claim is true; the complement view emits only
  `no-witness-found-in-scope` with corpus + corpus_version + queries + date. [7] corpus-internal.
  [8] ~half a day of lexicon authoring (boundary language is highly stereotyped) plus one sampler
  run.
- **Scores.** **D 7 / B 7.5** (claim-status D7/B8; negative-space D7/B7). No disagreement.
- **Measured signal [measured 2026-07-25].** 262 boundary assertions across 90+/173 papers.
  Thin in absolute terms; judge 1 docked for exactly this and was right to.

---

**1.3 `reduction-and-status` — global reductions with their hypothesis delta; dated resolution evidence**
*(merges the residuals of L1-reduction-graph, L4-open-problem-ledger, and L5-frontier-ledger leg 2)*

- **Blocked today.** Two questions, one mechanism. *(a)* The moves that make a counterexample
  findable are problem transformations — "the conjecture in dimension n follows from the cubic
  homogeneous case", "it suffices to treat Picard rank 1" — and no relation between two statements
  exists at any grain. *(b)* An agent has no way to learn that a conjecture it is attacking was
  settled in 2019 by a paper already in the notebook.
- **Mechanism.** Two lexicons. *Reduction*: `phrase_class ∈ {suffices-to, reduces-to, wlog}` mined
  **from non-proof chunks only**, each row carrying (i) the verbatim `hypothesis_delta` — the added
  assumptions in the WLOG/reduction sentence, which *is* the specification a candidate object must
  satisfy — and (ii) an honest `scope ∈ {global, local, unknown}` permitted to be
  unknown-dominated in v1. *Resolution*: a closed grammar over citing sentences ("we
  prove/settle/resolve/disprove Conjecture N of [k]", "a counterexample to Conjecture …")
  producing per-row evidence with its citing `chunk_id` and a `resolution_status ∈
  {no-evidence-in-corpus, claimed-resolved, claimed-refuted, ambiguous}` **derived only from
  evidence rows and defaulting to abstention**.
- **Surface.** two lexicon files + `reduction_paths(statement)` / a resolution block.
- **Why it accelerates.** Reduction: this is the step an LLM is worst at from parametric memory
  and it is what made the Jacobian result tractable — Tao's digestion records brute force as
  hopeless and tractability as coming entirely from classical re-coordinatisation. Run backwards,
  the same edges answer "which hypotheses were free?", the mechanical route to a generalisation.
  Resolution: pure anti-waste — do not spend a run on what a paper you already ingested settled.
- **Size** M. **Depends on** `span-substrate`, and (for cross-paper targets) `statement-refs`.
- **Risks.** Highest precision risk in the family: "it suffices to show" is overwhelmingly an
  ordinary local proof step, so v1 may be `scope=unknown`-dominated — which must be *reported*, not
  papered over. An index whose dominant value is `unknown` costs the same to maintain as one that
  works: ship the high-precision low-recall global filter or do not ship. On resolution, the error
  is asymmetric — a false `claimed-resolved` steers an agent *away* from a live target, the
  expensive direction — so the grammar must be biased hard to abstention and spot-checked before
  serving. The famous global reductions (Bass–Connell–Wright) are already in parametric memory, so
  expected marginal yield at 173 papers is modest.
- **Boundary.** [5] offline, read-only. [6] the server asserts only *paper P states this
  reduction* / *paper Q claims to resolve this* — extraction confidence and mathematical
  correctness are separate axes and the latter is never asserted; `scope=unknown` and
  `no-evidence-in-corpus` are tested outcomes distinct from operational failure. [7]
  corpus-internal. [8] ~1 day of pattern curation across both lexicons plus a ~40-sentence
  spot-check.
- **Scores.** **D 5.5 / B 6.5** (reduction D6/B6; open-problem residual D4/B7; frontier leg D5/B5).
  Judges converged; both discounted for precision and for the small conjecture population
  (94 conjecture + 36 problem environments, 221 verb hits across 86/173 papers).
- **Residue against existing plan.** `equivalent-to` / `follows-from` / `implies` and all in-proof
  reduction steps are **R2-KR1's `claim_edges` and R6-KR1's "reduce/transform goal" node** and must
  not be re-implemented. Kind-faceted conjecture retrieval is **#40's** filter builder extended.
  External conjecture sets (`formal-conjectures`, `erdosproblems`) are **R7-KR1's** adapter layer
  and **R5's** status taxonomy.

---

**1.4 `technique-transfer-map` — proof-technique facets, plus the time × subfield vacancy view**
*(merges L5-technique-facet with the completeness critic's A4; the merge is what changes the verdict)*

- **Blocked today.** The move a research mathematician makes when stuck is "find proofs of
  similarly-shaped statements that got through by degenerating to the boundary". `filters=
  {'include_kinds':['proof']}` shipped (#37) and its **only** access is dense cosine over proof
  prose — which the project's own D2 chapter documents as the weakest measured instrument on
  exactly this material (MIRB, arXiv:2505.15585: best commercial 13–18 nDCG@10 on premise/proof
  retrieval; bge-reranker-v2-m3 made it *worse*). `CHUNKS_SCHEMA_V1` has no column describing what
  a proof *does*.
- **Mechanism.** A technique lexicon (~25 classes: dévissage, degeneration, deformation, base
  change/descent, char-p/Frobenius, spectral sequence, duality, wall-crossing, obstruction theory,
  compactness, specialization, GAGA, weight arguments, dimension count …) under `span-substrate`,
  used as a **pre-filter** on the dense proof route so dense ranks *within* a methodologically
  correct set. Then — the part that converts it from comfort into a generator — cross-tabulate
  against two axes the corpus already has for free: **paper date and arXiv category**. Emit
  `technique_adoption(class, category, year, n_papers, n_proofs, first_seen)` and two views:
  *emergence* (recently-appeared, rising) and **vacancy** (technique T dense in category A, A
  adjacent to B by shared definition vocabulary and citation neighbourhood, T's count in B ≈ 0),
  ranked by adjacency strength × density in A.
- **Surface.** lexicon file + `filters.techniques` (W1 batch) + a read-only
  `arxmcp://notebooks/{slug}/transfer-map` resource (BP1-neutral, no tool-schema re-pin).
- **Why it accelerates.** Judge 1 scored the bare facet a 4 and was right: "a better-ranked list of
  prose" is the mode the empirical record says did not produce recent results — an agent that reads
  five wall-crossing proofs is not thereby closer to a counterexample. The vacancy view is a
  different object: it is a **target generator**, and it automates the ordinary way most publishable
  mathematics actually happens — a technique matures in one corner and the first person to carry it
  next door gets a result that is genuinely new and genuinely tractable. It is also the complement
  of `boundary-markers`: that finds unwitnessed hypotheses (where a counterexample might live);
  this finds unapplied machinery (where a proof might live).
- **Size** M. **Depends on** `span-substrate`.
- **Risks.** A vacancy is *overwhelmingly likely* to have a good mathematical reason the corpus
  does not state — the technique does not apply, or it was tried and failed unpublished. This is a
  hypothesis queue with a high false-positive rate by construction; the ranking exists to make the
  first ten worth reading, not to make any row trustworthy. Adjacency by shared vocabulary will
  link superficially ("moduli space"). **At 173 papers the cell table is very sparse** and this
  should not ship on a small notebook — measure the non-empty cell count first and drop the view if
  degenerate. arXiv category may be too coarse (math.AG covers wildly different subfields);
  citation-community clustering is the fallback and is more machinery. Lexicon bias toward the two
  live notebooks is real and should be stated, not hidden.
- **Boundary.** [5] offline writer, read-only resource, zero LLM at index time (satisfies §5 items
  10/11 by construction rather than evading them). [6] a vacancy is emitted only as a dated scoped
  census naming the corpus, corpus_version, lexicon version, the exact query that returned zero,
  and the date; the schema has **no token meaning "novel" or "unexplored"**; adjacency confidence
  and technique confidence never infer from each other. [7] corpus-internal. [8] ~1 owner-day
  *authoring* a vocabulary the owner already has — authoring does not scale with corpus size, which
  is the distinction that separates this from a labeling campaign — plus a 50-label spot check. A
  30-pattern subset over the six measured-densest classes is a legitimate v0.5.
- **Scores.** **D 4 → 6 / B 6** (facet alone D4/B8; the transfer view is what earns the raise).
  This is where I depart from judge 1: the facet alone deserved its 4, and the two free axes fix it.
- **Measured signal.** 3,893 `ltx_proof` environments; an *uncurated* 12-pattern lexicon already
  fires 2,913 cue hits (dévissage 1,032, wall-crossing 642, duality 347, char-p 196 …).

---

**1.5 `revision-drift` — arXiv version comments and statement-level diffs**
*(L1-revision-fossils, screened to two parts)*

- **Blocked today.** `ingest/oai_delta.py:116-118` harvests arXivRaw *precisely because* that format
  "includes `<versions>`" — and `_parse_listrecords` at `:479-492` extracts only `raw:categories`.
  The per-version `<comments>` field, where authors write "v3: corrected an error in the proof of
  Proposition 5.2, pointed out by …", flows past and is discarded on every harvest. Nothing diffs
  v1 against v2.
- **Mechanism.** *(a)* Parse `<versions>/<version>/{date, comments}` in `_parse_listrecords` and
  classify with a lexicon (correction / expansion / admin) — near-free, rides the existing
  operator-run harvest, lands as **additive columns on source-truth's document/revision registry**,
  not a parallel store. *(b)* An **on-demand, per-paper** `tools/revision_diff.py` that refetches
  the earlier version through the existing politeness-contracted fetcher, re-runs the shipped
  chunker, and diffs at chunk grain — exact rather than fuzzy, because `chunk_id` is a content hash
  (`ingest/chunker.py:1026-1050`), so a changed statement is a `theorem_label` present in both
  versions with different `chunk_id`s. Emits `statement_drift(..., delta_kind ∈ {hypothesis-added,
  hypothesis-removed, conclusion-weakened, renumbered, other, unknown})`.
- **Surface.** `extend-mcp-tool`, `new-offline-cli`, `schema-change` (additive on the R1 registry).
- **Why it accelerates.** A hypothesis added between v1 and v2 is the strongest available evidence
  that the hypothesis is load-bearing — a referee or reader found a counterexample to the v1
  statement — and it is the best available pointer at a **nearby unpublished counterexample**: the
  v1 statement is false, someone knows why, and very often nobody wrote it down. Run the other way,
  a hypothesis *removed* is a proven generalisation to chain. arXiv leaves all prior versions online
  without notation, so a silently-corrected paper looks pristine.
- **Size** M ((a) is S). **Depends on** source-truth's registry; the delta classifier uses
  `span-substrate`'s lexicon format.
- **Risks.** Refetching old versions must honour the arXiv politeness contract and **ar5iv coverage
  of old versions is not guaranteed**, forcing the slow local LaTeXML path. Author comments are
  frequently "minor changes", so the correction signal is sparse — **measure yield on one notebook
  before generalising**, and be willing to ship only part (a). Renumbering produces false drift.
- **Boundary.** [5] ingest-side and operator-invoked; no agent-triggered fetch. Author comments are
  third-party text, wrapped as `<retrieved_chunk>`, never treated as instructions. [6] the server
  asserts only *the statement text changed between these versions* — never "v1 was wrong", a
  separate axis it does not compute. [7] arXiv metadata is the corpus's existing licensed source.
  [8] ~half a day of comment-classification regexes plus a yield measurement.
- **Scores.** **D 7 / B 7.** No disagreement; both docked for sparsity.
- **Residue against existing plan.** The per-revision registry itself is
  `source-truth-e1`/`m1` (R1-KR2); withdrawal *serving* is **#41**. This adds only the comments
  field and the statement diff — I grepped `source-truth/roadmap.yaml`, `R1-source-truth.md` and
  all 200 issues for `comment|errata|corrigendum|drift|diff`: absent.

---

**1.6 `attention-queue` — rank every human-resolvable abstention by downstream unblock value**
*(new; completeness critic A5)*

- **Blocked today.** Constraint 8 names owner-hours as *the* binding resource, and every proposal
  dutifully prices its own owner cost — then none treats owner attention as schedulable. Each
  instead opens a private review backlog: a top-50 entity-identity pass, a 100-match precision
  audit, a 50-claim audit, a ~60-decomposition golden set, a per-batch promotion confirm, an
  accept/reject queue, a per-census query plan forever. Nothing can compare a minute spent on one
  against a minute spent on another, and the run-time abstentions where sixty seconds of the one
  qualified human converts an unusable row into a served one are invisible. This project's own
  history is the evidence: the eval fixtures sat unlabeled for months.
- **Mechanism.** One read-only view, no new store. Each index declares (in `span-substrate`'s
  lexicon file format) which of its outcome tokens are **human-resolvable** — `ambiguous`,
  `unattached`, `undecomposed`, `identity-ambiguous`. An offline aggregator emits
  `attention(item_id, source_index, question_kind, the_actual_question, evidence_refs[],
  unblock_score, estimated_seconds)`, where `unblock_score` is *computed*: how many served rows
  change if answered, how many agent queries touched the affected chunk, how many downstream
  indexes are blocked. Served as `arxmcp://attention` (BP1-neutral) plus a `/ui/` card answerable
  through the existing propose→confirm flow.
- **Surface.** `new-served-artifact`, `new-offline-cli`, `ui-console`.
- **Why it accelerates.** It is the anti-rot mechanism for everything else here, and the only
  proposal that treats the binding constraint as an object. It makes the deterministic-mining bet
  survivable — nine lexicons with nine private backlogs decay silently; nine feeding one ranked
  queue decay visibly and get triaged. It converts abstention from a cost into a channel: the trust
  policy already forces honest abstention everywhere, and every honest abstention is currently a
  dead end for the agent *and* the owner. And it is the ADR-compatible form of the collaboration
  modality all six lenses missed — not the agent asking the human, but the corpus computing which
  question is worth the human's next minute.
- **Size** S. **Depends on** `span-substrate` (degrades to a hand-wired aggregator over two or
  three indexes without it).
- **Risks.** A queue nobody works is worse than none — cap the served view at ~20 rows and let the
  rest be invisible; its job is to name the next half-hour, not to inventory debt. `unblock_score`
  will be wrong and must show its components. Needs a recorded `deferred` outcome or rows reappear
  every sweep.
- **Boundary.** [5] offline aggregator writes; MCP serves read-only; resolutions enter **only**
  through the `/ui/` operator-confirm path — explicitly not the env-gated auto-accept that
  cross-synthesis §5 item 18 kills. No per-run state: derived from index state, not from any run.
  [6] surfaces abstention tokens verbatim with evidence and never converts an unresolved row into a
  resolved-looking one. [8] adds no obligation; it makes nine unschedulable obligations schedulable.
- **Scores.** D — / B — (postdates the judges). My assessment: **D 3, B 9** — no discovery value
  directly, very high durability value.

---

### Theme 2 — The Lean lane: refute before you prove

**Thesis.** Every result in the motivating context was a refutation, and arXMCP can only attempt to
prove. Refutation is also asymmetrically cheap: falsifying a candidate lemma in seconds prunes a
branch that would otherwise consume a tactician's entire turn budget, so a sketcher can emit ten
candidate strengthenings and have nine killed before any proof attempt starts. Everything else in
this theme is throughput on the proving step — real owner-weeks, but downstream of finding, and
none of it gated a recent result.

---

**2.1 `refutation-lane` — falsification with kernel-checked witnesses and honest abstention**
*(L2-refutation-lane, ruled NOVEL)*

- **Blocked today.** `mode` is `Literal["full","syntax_only","tactic_step"]`
  (`server/handlers/lean_verify.py:736`); the status vocabulary is
  `ok/error/sorry/incomplete/timeout/unavailable/invalid-input` (`server/tools.py:404-406`). There
  is no mode that searches for a counterexample and no token that can express *false*. A hand-rolled
  `plausible` call returns an untyped string in an `info`-severity `messages[]` row
  (`server/handlers/lean_verify.py:309-330`), structurally indistinguishable from a trace, with no
  witness field, no receipt, and a 30 s budget shared with elaboration. `plausible` is installed at
  `…/repl/.lake/packages/plausible` and unreachable.
- **Mechanism.** A `refute` **mode on the existing Lean surface** (not a new tool), running a
  three-stage ladder in the pinned env: (1) `decide` on a caller-supplied finite instantiation when
  a `Decidable` instance exists; (2) `Plausible` randomised search with caller-supplied sample count
  and a **recorded seed**, which also shrinks the witness; (3) abstain. Three distinct tested
  outcomes: `refuted` — carries the shrunk witness **and a receipt**, a machine-generated
  `theorem _receipt : ¬ P <witness> := by decide` re-elaborated in a *fresh* environment, so the
  refutation is kernel-backed and pasteable into a paper; `no-counterexample-found` — abstention
  carrying searched-space description, sample count, seed, shrink depth, phrased as a dated scoped
  census, **never as "true"**; `unsupported-by-provider` — no `Decidable`/`SampleableExt` instance,
  which is abstention, not error. `native_decide` **forbidden by default** because it injects
  `Lean.ofReduceBool` into the axiom set; if ever enabled it is its own trust axis. The search
  budget is a caller parameter **separate from the elaboration timeout**, hard-capped to fit one
  single-shot response.
- **Surface.** `extend-mcp-tool`, `schema-change`, `eval-harness`.
- **Why it accelerates.** This is the workflow of every result in the motivating context and arXMCP
  structurally cannot do it. The Grothendieck refutation is exactly this shape — an order-4 object,
  checked. The single largest reduction in wasted model turns available anywhere in this analysis.
- **Size** M. **Depends on** R3-m1 (honest statuses), R3-m2 (isolation, before agent-supplied
  long-running search ships), R3-m5/m7 (a Mathlib-resident env — `Plausible` over anything
  interesting needs Mathlib imported, which does not fit today's 30 s cold-import budget).
- **Risks.** **Do not oversell it.** Derived categories and stability conditions mostly lack
  `Decidable`/`SampleableExt` instances, so stage 3 will dominate on the headline targets; the honest
  value concentrates on the numerical/lattice/combinatorial sub-lemmas — which, per R5's own reading
  of the Enriques–Kuznetsov §8.4–8.6 steps over `Module ℤ (Fin 2 → ℤ)`, is precisely where the
  closable work is. `no-counterexample-found` will be misread as "true" by any consumer that ignores
  the field: enforce with **no boolean anywhere in the refutation envelope** plus an adversarial
  test, not documentation. Budgets must fit one `application/json` response — state the cap, do not
  pretend to be a model checker.
- **Boundary.** [5] pure compute, nothing persisted — the explicit `lean_verify` carve-out. [6] the
  cleanest instance of the policy in this analysis: three distinct outcomes, `refuted` carrying its
  own evidence, two tested abstentions held distinct from `timeout`/`unavailable`, and no axis
  inferred from another (a `Plausible` non-refutation never implies provability); the axiom axis
  stays R3's. [7] mathlib and plausible are Apache-2.0, local, nothing redistributed. [8] ~1–2 days
  including the adversarial tests that make "no-counterexample-found ≠ true" unfakeable; **the
  recurring cost is supplying finite instantiations, which is genuine mathematical judgement and
  cannot be automated away — say so.**
- **Scores.** **D 8 / B 7.** No disagreement. Both judges' highest-ranked Lean item.

---

**2.2 `directional-definition-probe` — strictly-stronger / strictly-weaker / incomparable**
*(L2-defn-differential, screened to one idea)*

- **Blocked today.** Nothing compares a paper's notion of an object with mathlib's.
  `get_definitions` returns LaTeX macro expansions (`ingest/schema.py:301-311`) — notation, not
  semantics — with no formal counterpart. R5 makes faithfulness a *human* axis at ~2 owner-days for
  5–10 entries; there is no mechanical signal at any point in the plan.
- **Mechanism.** A **two-obligation mode of the refutation lane**, not a new tool: test
  `∀x, P x → Q x` and `∀x, Q x → P x` as two *separate* obligations, so the report distinguishes
  "my transcription is strictly stronger" / "strictly weaker" / "incomparable" rather than emitting
  an equivalence verdict. Each direction runs the `decide`→`Plausible` ladder and returns a
  kernel-checked discriminating witness when one exists. The word "equivalent" does not appear in
  the schema.
- **Surface.** `extend-mcp-tool`, `schema-change`.
- **Why it accelerates.** Definitional mismatch is the failure mode that makes autoformalization
  output *worthless rather than wrong-and-fixable* — TheoremGraph's statement-only experiment
  produced 22/24 typechecking against 5/24 semantically faithful, the constant R5 cites as its
  founding fact. The directional split is the one field that changes what the agent does next.
- **Size** S (as a mode). **Depends on** `refutation-lane`.
- **Risks.** Same instance-availability ceiling. A sampled agreement is weak evidence and will be
  over-trusted — mandatory space and count fields, never a boolean.
- **Boundary.** [5] compute-only. [6] no bare "equivalent"; `agreed-on-N-samples` is an abstention
  carrying its own scope; **the faithfulness axis remains human-owned (R5-KR6) and this attaches
  evidence to it without setting it** — the policy forbids inferring one axis from another.
- **Scores.** **D 4 / B 6.**
- **Residue against existing plan.** The binder/hypothesis diff and the unmatched-assumption report
  belong to **R6-m5 / R6-KR7** (whose own acceptance test is the K3→Enriques 2-torsion diff) and
  must be dropped from scope. The witness search is 2.1's.

---

**2.3 `lean-name-inventory` — pinned-mathlib identifier resolution and deprecation repair**
*(L2-lean-name-linter, ruled NOVEL)*

- **Blocked today.** An agent writing `simpa using Finset.sum_range_succ_comm` must burn a full
  `lean_verify` round-trip — a 30 s budget (`server/lean_repl.py:63`) shorter than a cold
  `import Mathlib` — to discover the name does not exist at mathlib@v4.31.0, or exists under a
  `@[deprecated]` alias, or needs `open Polynomial`. No name-resolution surface exists; model
  training data is systematically older than the pin, so stale-name failure is the modal
  first-attempt failure.
- **Mechanism.** `tools/lean_decl_inventory.py` drives **one** Lean command in the already-built env
  (`import Mathlib` + a walk over `(← getEnv).constants` and `Lean.Linter.deprecatedAttr`) into a
  SQLite artifact of `(name, namespace, decl_kind, is_deprecated, replacement_name, module,
  universe_params)`. **No embeddings, no vector column, no retrieval ranking** — a name set plus a
  rename map, a few tens of MB. Serving is a pure lookup returning per identifier
  `resolved` / `deprecated(replacement)` / `unknown-in-env` / `ambiguous-without-open` /
  `not-an-identifier`, plus a `suggested_rewrite` applying **only** deprecation renames — mechanical
  and information-preserving, never a semantic guess. Keyed by the R3 environment digest so a
  mathlib bump invalidates visibly. Zero Lean subprocess at serve time.
- **Surface.** `new-offline-cli`, `new-index`, `new-mcp-tool` (riding W1).
- **Why it accelerates.** Collapses N failed elaborations into one sub-second call. It is the only
  mathlib-facing capability here **not blocked behind R3's environment and isolation gates**.
- **Size** S. **Depends on** an environment digest (R3-m5, or an interim digest over the lake
  manifest).
- **Risks.** A conservative identifier scanner over-reports on syntax it does not model
  (`_root_`, dot-notation, projections) — **abstain (`not-an-identifier`) rather than report
  `unknown-in-env`; a false "unknown" is the damaging error and must be impossible by
  construction.** Refuse to serve on digest mismatch rather than serve stale truth. **Hold the
  artifact to name/kind/module/deprecation metadata only — the moment it carries statements or
  docstrings it becomes the in-server Mathlib corpus killed at cross-synthesis §5 item 2.**
- **Boundary.** [5] offline CLI builds, read-only lookup, no persisted per-run state. [6] each
  identifier carries its own verdict; `unknown-in-env` and `ambiguous-without-open` are abstentions
  distinct from `env-digest-mismatch` (operational). [7] mathlib is Apache-2.0; the artifact is
  derived name metadata built locally and never redistributed, with the check recorded anyway. [8]
  **~0 owner-hours of judgement.**
- **Scores.** **D 3 / B 9** — the widest defensible split in the set. Judge 1: "no agent finds a
  counterexample because it resolved a deprecated name faster" — true in the limit, and it is
  scoring a constant-factor item on a marginal-discovery axis. Judge 2 is right on the decision;
  judge 1 is right on sequencing. **Build it; charge it to the throughput budget, not the discovery
  budget.**

---

**2.4 `goal-search-mode` — `exact?`/`apply?`/`rw?` against a held proof state, with an exhaustiveness axis**
*(L2-typed-premise-oracle Route B only)*

- **Blocked today.** An agent stuck at a goal has two options: guess a name and spend 30 s, or search
  the *arXiv* corpus, which contains no Lean. A failed neural search is indistinguishable from an
  absent lemma, so the agent oscillates.
- **Mechanism.** A mode on the Lean surface that runs `exact?`/`apply?`/`rw?` against a **held**
  `proof_state` continuation token under its **own hard sub-budget separate from the elaboration
  timeout**, returning structured tactic-script rows rather than untyped info strings, plus a named
  epistemic axis `search_exhaustiveness ∈ {exhaustive-over-index, truncated-at-k,
  unsupported-pattern, budget-exhausted, env-unavailable}`.
- **Surface.** `extend-mcp-tool`, `schema-change`.
- **Why it accelerates.** An exhaustive negative is a *decision*, and a decision unblocks a stuck
  agent: build the machinery, or pick a different target.
- **Size** S–M. **Depends on** R3-m7 warm Mathlib envs.
- **Risks.** `exact?`/`apply?` are unbounded searches inside a single-shot budget; `budget-exhausted`
  must be abstention, never "no match".
- **Boundary.** [5] compute-only. [6] `search_exhaustiveness` is a named axis; abstentions distinct
  from operational failure; any "no lemma of this shape" is a scoped dated census over a named
  environment digest. Note the `LeanSearchClient` package's `#leansearch`/`#moogle` commands are
  **HTTP clients to remote services and must be explicitly blocked in the sandbox policy, not merely
  unused** (constraints 1–2).
- **Scores.** **D 3 / B 5.**
- **Residue against existing plan.** **Route A (a local Loogle index) is not new work** — it is the
  content of the unrun spike **#186 / trustworthy-release-m13 / verification-feedback-spike-3**,
  under a standing compose-don't-ingest posture (cross-synthesis §5 item 2; D2.md:154 explicitly
  names "local `loogle` for type-directed lookup" as *tracked evaluation work*). Answer it there
  first. Filing a build issue against an unrun spike is how a solo maintainer acquires an artifact
  nobody decided to own.

---

**2.5 `obligation-decomposition` — sorries into standalone, content-addressed lemmas**
*(L2-obligation-decomposition, ruled NOVEL)*

- **Blocked today.** Sorries come back as `{goal: <pretty-printed string>, position, proof_state_id}`
  (`server/handlers/lean_verify.py:333-355`). Three consequences: `proof_state_id` is
  generation-scoped and fail-closed rejected after any respawn (`:102-132`); the timeout path
  respawns (`:937-972`), so **one 30 s timeout destroys the entire decomposition**; a `proofState` is
  a point in one process's snapshot tree, so N sorries cannot be attacked by N workers; and `sorry`
  taints the declaration with `sorryAx`, so no partial result can be cached or reused.
- **Mechanism.** `decompose_obligations(snippet, env)`: walk the unassigned `MVarId` frontier and for
  each sorry emit a **self-contained `theorem` statement** (goal type with local context lifted into
  explicit binders via `abstractMVars` + `mkForallFVars`, instance binders preserved
  **instance-implicit and verbatim, never re-synthesised**) plus a **content hash** over
  (environment digest, ordered imports, pretty-printed abstracted type, binder order) — process-
  independent by construction, so it survives respawns and is stable across attempts. Also returns
  dependency edges (which obligations share fvars) and a machine-generated **assembly**: the original
  proof term with each `sorry` replaced by an application of the corresponding lemma, resubmittable
  in `mode="full"` for a genuine whole-declaration kernel check. When the lift cannot be done
  soundly (let-bound context, dependent motive, universe issues) it **abstains for that obligation**
  (`not-liftable`, with a reason).
- **Surface.** `new-mcp-tool`, `schema-change`, `external-repo` (the orchestrator consumes it).
- **Why it accelerates.** The parallelism and durability unlock for the whole
  sketcher→autoformalizer→tactician→fixer pipeline; nothing in R0–R7 has it, and a census against the
  pinned REPL source confirms upstream exposes no decomposition primitive to compose with either
  (R3:135-146: cmd/file/proofStep/pickle*/unpickle* only). A research formalization is 10–40
  obligations, today attacked serially through a REPL whose every timeout invalidates all
  outstanding state.
- **Size** L. **Depends on** R3-m1, R3-m5/m7.
- **Risks.** **The hardest engineering here and the most likely to be mis-sized.** The soundness
  hazard is the whole story: a mis-lifted binder yields a lemma that is provable but *not the one
  needed*, and the assembly then fails late and confusingly — or succeeds vacuously. `not-liftable`
  must be the default for anything not provably safe, with an adversarial fixture set covering
  let-bound contexts, dependent motives, universe-polymorphic goals. **Spike the lift on 5 real
  skeletons before committing; if it abstains on the majority, cut it rather than ship partial — a
  decomposition that silently changes the statement is worse than none.** Ongoing tax is tracking
  Lean/REPL internals across a pin triple that moves together.
- **Boundary.** [5] **this is precisely the ADR carve-out**: the server *computes* a structured
  artifact (statements + hashes + assembly) that the agent's **own** loop uses as memory; hashes are
  returned, never persisted; no run state, no transcripts. The server-side sorry ledger was
  correctly rejected rather than smuggled in. [6] `not-liftable` is a tested abstention; the
  operation asserts nothing about whether any obligation is true — the only kernel verdict comes from
  resubmitting the assembly through the R3 check path.
- **Scores.** **D 5 / B 4** — judge 2's lowest non-killed score. Throughput on formalize, measured in
  owner-days saved, not findings.

---

**2.6 `formal-env-stamp` — library identity on every Lean result**
*(the surviving rider of L6-formal-crosswalk, which both judges otherwise killed)*

- **Blocked today.** `grep -niE 'toolchain|mathlib_rev|lean_version'` over the 42,658-byte
  `server/handlers/lean_verify.py` returns **0 matches**. A Lean result from arXMCP cannot be
  compared against, let alone composed with, any external Lean artifact, and importing an artifact
  built against a different Mathlib is discovered 40 minutes into a proof attempt.
- **Mechanism.** A `formal_env` object — `{lean_toolchain, mathlib_rev, repl_commit}` — on every
  `lean_verify` result envelope, sourced from the pin already on this box (repl 0cc6026 / Mathlib
  fabf563a / v4.31.0). **Rides the next batched TOOL_SCHEMA_VERSION window; must not mint its own
  re-pin** (the schema-version cascade trap is documented in the lean-verify-continuation handoff).
- **Size** S. **Depends on** the W1 window (agent-platform-e2 / #65 / #72).
- **Boundary.** [6] descriptive identity, not a trust verdict — it introduces no new status token.
- **Scores.** **D 3 (kill as a capability) / B 7.** Both judges converged: **land it as hygiene, not
  as a discovery capability.**

---

### Theme 3 — The census contract: negatives that survive the session

**Thesis.** A discovery search that cannot remember what it ruled out is a random walk. Ninety
percent of a counterexample hunt is ground covered and found empty, and today all of it evaporates
at session end — so successive sessions re-cover it, parallel agents duplicate it, and no result can
carry the evidence its own trust policy requires. Five proposals independently invented a census
artifact; the correct build is **one record type with one verdict vocabulary and several producers.**

---

**3.1 `census-record` — one type, one verdict vocabulary, several producers**
*(merges the census halves of L4-novelty-census, L6-novelty-census, L3-fingerprint-census, L3-falsify-census, and boundary-markers' complement view)*

- **Blocked today.** Every proposal that can answer "nothing found" defines its own scope object,
  date field, and verdict enum — differently. With five schemas, at least one grows a token that
  reads as "novel", which is the exact failure CLAUDE.md §4.9 rule 3 exists to prevent.
- **Mechanism.** Extend `.claude/docs/evidence-ledger-standard.md` (Accepted 2026-07-12) with a new
  claim class for search/coverage results, keeping its existing 5-field template. One content-
  addressed record: `{census_id, claim_ref, scope (named sets + corpus_version + external snapshot
  dates + explicit coverage caveats), verbatim queries, run_date, per-source results, verdict,
  reachability denominator}`. **The verdict vocabulary is the deliverable**, and it must keep three
  things that cannot collapse into each other: an answer (`exhausted-in-scope` / `no-hit-in-scope`),
  a partial (`budget-exhausted-at-N` / `truncated-at-k`), and an operational halt
  (`controls-failed` / `unavailable`). **There is no member meaning "novel" or "new".** Served
  read-only at `arxmcp://census/{census_id}` so an attempt record, a conjecture row, and a paper
  draft can all cite it by id, and a re-run at a later corpus_version produces a diff.
- **Surface.** `new-served-artifact`, `new-index`, `new-offline-cli`.
- **Why it accelerates.** It is what makes every other negative in this document durable and
  citable, and it is the mechanism by which "is this still open?" becomes a diff instead of a
  recurring manual chore.
- **Size** S–M. **Depends on** nothing.
- **Risks.** Scope inflation — an agent citing a `census_id` presenting a notebook-scoped negative as
  literature-wide. Mitigate structurally: the verdict token is unusable without its scope, because
  they live in the same object. Corpus drift silently invalidates old records; the served view must
  expose `corpus_version` and flag staleness.
- **Boundary.** [5] offline producers, operator-gated promotion, read-only serving. [6] this *is* the
  policy's enforcement mechanism. [7] external snapshot dates and licenses recorded per source.
- **Scores.** D — / B — (a merge). My assessment: **D 5, B 8.**

---

**3.2 `discovery-backtest` — reachability audit against dated, known discoveries** *(prerequisite P2)*

- **Blocked today.** No instrument measures discovery. 31 proposals were ranked on argument; the two
  judges disagree at the root with nothing to settle it.
- **Mechanism.** `tools/backtest_reachability.py` over a committed case file. Each case names a dated
  result, a cutoff strictly before it, and a **hand-decomposed ingredient list derived by reading the
  published account backwards** — the reductions used, the object family searched, the invariant
  computed, the prior partial results, the hypothesis that turned out removable. Ingest pre-cutoff
  literature into a scratch notebook; for each ingredient run the real MCP tools and record
  `reachable-in-k-calls(tool, query, rank)` / `present-but-unretrievable` / `absent-from-corpus` /
  `unanswerable-by-current-surface`. The load-bearing output column is **attribution**: which
  proposed capability would have changed each unreachable cell. It does **not** claim "the agent
  would have found it" — that is unfalsifiable. It claims only which ingredients were reachable.
- **Surface.** `new-offline-cli`, `eval-harness`, `new-served-artifact`.
- **Why it accelerates.** It is the only spend here that decides the other spends. It can settle the
  judges' central disagreement directly: if the ingredient lists are dominated by
  `absent-from-corpus` and `unanswerable-by-current-surface` on the object/compute axis, judge 1 is
  right; if by `present-but-unretrievable`, judge 2 is. The ingredient decomposition is also reusable
  — it is the first honest description this project would have of what a discovery is made of, and it
  can seed the eval fixture `evidence-engine` already needs.
- **Size** M. **Depends on** nothing.
- **Risks.** **Hindsight bias is the central hazard** — knowing the answer makes it easy to write an
  ingredient list the corpus happens to contain. Mitigate by *commit order*: the ingredient list is
  written from the published account only, committed **before** the harness runs, never edited after
  seeing results. Three cases is a very small n and will be over-read: report as a scoped census, not
  as a ranking. The 2026 results skew toward object-and-computation discoveries, biasing the
  instrument toward judge 1's thesis — include at least one case whose route was a literature
  connection, or state the bias.
- **Boundary.** [5] offline CLI against a scratch notebook, wrapping handler internals per the #26
  precedent (no new route, no server change); **no agent is run** — the harness calls tools and
  records verdicts, it does not attempt the mathematics. [6] per-ingredient verdicts with the query
  and rank as evidence; `unanswerable-by-current-surface` distinct from `absent-from-corpus`; emitted
  as a dated scoped census naming cases and cutoffs, so it can never say "arXMCP would have found X".
- **Scores.** D — / B — (postdates the judges). My assessment: **D 6, B 7.**

---

**3.3 `attempt-ledger` — deduplicated negative memory, with the run telemetry stripped**
*(L4-attempt-ledger, with a boundary correction)*

- **Blocked today.** Nothing models an attempt. A fleet of parallel sketchers re-walks identical dead
  branches within one run and across every run; the *why* of each failure — the most valuable and
  most-discarded artifact of a proof search — is gone at session end. This is **not** what #69 buys:
  basic-memory gives free-text Markdown notes with no claim identity, no deduplication, no
  `corpus_version` binding, and nothing joinable to a `chunk_id`.
- **Mechanism.** Three legs. *(1)* The record schema lives in the **separate orchestrator repo** as
  append-only JSONL. *(2)* `tools/notebook_attempts_ingest.py` validates, **deduplicates** — same
  (claim, approach_tag, failure_mode) collapses to one row with `n_observations` and first/last-seen
  dates, which is what turns six wasted parallel agents into one useful fact — and writes a
  per-notebook SQLite sibling (the `server/documents_store.py:11-20` placement). *(3)* Read-only
  resource, wrapped through `wrap_retrieved_text` (`server/tools.py:589-660`) under its own tag,
  because ledger text is agent-authored and therefore untrusted on the way back in.
  **Integrity rule, load-bearing:** strong outcomes (`refuted`/`succeeded`) require machine-checkable
  evidence — a Lean message with source position, a witness, a `census_id`, or a `chunk_id` —
  and self-reported prose **auto-downgrades to `inconclusive`**.
- **Surface.** `external-repo`, `new-offline-cli`, `new-index`, `new-served-artifact`.
- **Why it accelerates.** The AlphaEvolve/FunSearch lesson transplanted to proof search: what makes
  those systems find new mathematics is a persistent database of past candidates *and their
  evaluations* resurfaced into later generations. arXMCP's fleet restarts every time.
- **Size** M. **Depends on** R2's claim identity (for the key) and agent-platform-e5 / #68 (the
  external orchestrator repo, which does not exist yet).
- **⚠ Boundary correction — this is a trojan horse as originally proposed.** The pitched record
  carries `model`, `wall/token cost`, `action`, and `approach_tag`. Those are run telemetry and
  model-conversation state — the category ADR Decision 1 forbids server-side. The defense that the
  artifact is "distilled, deduplicated, operator-promoted, not run state" fails: dedup plus an
  operator confirm is a *freshness and volume* transformation, not a category change — **the ADR
  bans the kind of data, not the age of it.** The second-order violation is worse: serving
  `arxmcp://claims/{id}/attempts` back to the fleet makes the server the shared branch-selection
  memory for parallel agents, the closest anything here comes to the server *being* the agent.
  **Strip `model`, `action`, `approach_tag`, and cost; keep only
  `(claim_id, failure_mode, machine-checkable evidence ref, n_observations, corpus_version)`.**
  That is a corpus-derived refutation fact and is boundary-clean.
- **Other risks.** Agent self-diagnosis of *why* it failed is unreliable (mitigated by the integrity
  rule). Prompt-injection channel back into the fleet — keep it resource-only, never a
  `search_papers` source. Over-trust: serve `n_observations` and dates, never an aggregate verdict.
- **Scores.** **D 6 / B 5.**
- **Residue against existing plan.** R6's scope-out already reads: *"No cross-run agent memory
  (external agents own run memory; the server may ingest curated attempt artifacts offline through
  the normal operator-gated path — that ingest design is a later, separate brief if wanted)."* This
  is that deferred design and nothing more.

---

**3.4 `novelty-census-runner` — claim-level prior art across the API clients already in-tree**
*(L6-novelty-census; L4-novelty-census folds into it)*

- **Blocked today.** arXMCP's search reaches only the ingested notebook (order 10² papers), so an
  empty result is indistinguishable from "nobody has done this" — the most expensive false conclusion
  available to a discovery pipeline. Verification falls entirely on the owner's own literature sweep,
  performed fresh at the end of every run and never reusable.
- **Mechanism.** `tools/novelty_census.py`, an **operator-invoked offline CLI** (egress at CLI time,
  exactly like `ingest/graph_ingest.py`). Input: a claim plus a query plan the operator edits.
  Executes against the clients already in-tree — arXiv Atom (`tools/_arxiv_api.py`), OpenAlex
  (`ingest/graph_ingest.py`), INSPIRE-HEP (`ingest/inspire_ingest.py`) — plus Semantic Scholar once
  #42 lands. Emits a `census-record` (3.1). Part of the query set should be generated mechanically
  (conclusion spans, alias names, `find_equation` TED forms) so the census does not depend solely on
  an agent's imagination — that is the one idea worth keeping from the corpus-internal variant.
- **Size** M. **Depends on** `census-record`. (The stated dependencies on object-refs and the formal
  crosswalk should be **cut** — they only auto-draft a query plan the operator must edit anyway.)
- **Risks.** Query-plan quality is the entire value, and **a badly-scoped census that returns empty is
  worse than no census because it manufactures false confidence.** Structural mitigation: verbatim
  queries and named coverage caveats stored in the record, so the weakness is inspectable. Coverage
  of mathematics in OpenAlex/S2 is uneven and INSPIRE is hep-focused — the blind-spot field is
  load-bearing, not decorative. **Do not move this to a query-time MCP tool**; that would put live
  egress on the serving path.
- **Boundary.** [5] offline runner, read-only serving, no query-time network from the server. [6]
  verdict scoped and dated by construction; the pre-registered rule prevents post-hoc threshold
  shopping. [7] public metadata only (ids, titles, years, counts) — no full text, nothing enters the
  redistributable path. [8] **~15–30 owner-minutes per census, forever, non-amortising** — only a
  human can judge whether the queries cover the claim. Honest, and it replaces hours of unrecorded
  searching.
- **Scores.** **D 5 / B 5.**
- **⚠ Interaction.** If `own-work-lane` is ever built (see §5), the census scope must name the local
  lane as a **separate, separately-reported set**, never folded into the corpus denominator —
  otherwise the owner's own unpublished claim registers as prior art against the owner's own new
  claim.

---

**3.5 `computation-key-and-replay` — the two fields a Markdown note cannot express**
*(the residual of L3-computation-ledger, filed against #69 rather than as a new store)*

- **Blocked today.** Nothing can answer "has this computation already been run, and with what
  result?" Every session re-derives and re-pays.
- **Mechanism.** Two fields, not a new subsystem: **(a)** a content-addressed key
  `sha256(engine_id@version ‖ canonicalised program ‖ sorted params ‖ seed)` that makes cache-hit
  dedup and "has this exact computation been run?" *decidable* rather than prose-searchable;
  **(b)** a `replay_status ∈ {never-replayed, replayed-match, replayed-divergent, replay-unavailable}`
  axis where **divergence demotes rather than deletes**, and engines whose determinism is not
  established are honestly marked `replay-unavailable` rather than pretended deterministic.
- **Size** S. **Depends on** whichever computation lane exists (see §5 on the compute boundary).
- **Risks.** A program that reads the clock or the filesystem is not a pure function of its key, so
  the canonicaliser must reject obviously-impure programs or the content-addressing claim is false.
  Randomised strategies make `replayed-divergent` common enough to devalue the axis.
- **Boundary.** [5] **structural guard required**: the writer module must not be importable from
  `server/handlers/`, with a test, mirroring the existing `tests/test_langfuse_doc.py` import guard —
  one careless commit turns a read-only tool surface into a writable one.
- **Scores.** **D 6 / B 5.**
- **Residue.** The table, the CLIs, and the resource template all fold into **#69 / agent-platform-e6**
  (D2-R02, D2-R14), whose operator-confirmed-CLI write pattern is already this shape, and whose
  ledger idiom already exists as `var/arxmcp/ops/eval/ledger.jsonl`.

---

### Theme 4 — Fidelity debt: serve what you already parsed

**Thesis.** Four capabilities in this analysis have their entire input sitting on disk, already
parsed, already licensed, and simply dropped. This theme is not new data acquisition; it is the
cheapest work in the document and it includes one whole modality that six independent lenses missed.
Constraint 4 — math fidelity over retrieval recall — is invoked everywhere for MathML and silently
violated for diagrams.

---

**4.1 `figure-lane` — serve the corpus's diagrams, captions, and TikZ source**
*(new; completeness critic A3, independently re-measured for this document)*

- **Blocked today [measured 2026-07-25].** Across 173 parsed papers: **323 captioned `ltx_figure`
  floats in 55 papers (32%); 1,483 inline `<svg>` in 120 papers (69%)**, class
  `ltx_picture ltx_markedasmath` with ids of the form `S3.Ex25.m1.1.1.pic1` — i.e. TikZ/tikz-cd
  renderings that **LaTeXML itself classified as mathematics**, 262 of them inside `<math>`
  elements; plus 203 `ltx_graphics` and 561 `<img>`. None of it is reachable: `figure` is in the
  chunker's non-recursed list (`ingest/chunker.py:757`) and
  `grep -rn 'ltx_figure|ltx_graphics|tikz' ingest/ server/` returns **0**. Zero of 200 issues, zero
  of nine roadmaps, zero of eight briefs mention figures or diagrams. So `\ref{fig:3}` resolves to
  nothing, and an agent told "the wall-and-chamber decomposition of Figure 3" receives a pointer to
  something that does not exist in the corpus.
- **Mechanism.** An offline pass over the retained LaTeXML HTML emitting `figures(figure_id,
  paper_id, chunk_id, label, printed_number, caption_text, asset_kind ∈ {svg-inline, raster,
  tikz-source, absent}, asset, referring_chunk_ids[])`. **Where LaTeXML preserved TikZ/tikz-cd
  source, keep it** — a commutative diagram's source is a machine-readable statement of a
  diagram-chase obligation and is worth strictly more than its picture. Caption text joins retrieval
  as its own kind behind an opt-in filter (the #37 proof-column posture), not folded into the
  default lane. `\ref{fig:…}` resolution reuses the `ltx_ref` anchor machinery. Serve a `figures`
  block on `get_chunk` and `get_figure(figure_id)` returning caption + label + printed number +
  referring statements + the asset (SVG as text, raster base64, size-capped) so a multimodal agent
  can actually look at it. **Explicitly not proposed: any figure understanding, OCR, or captioning —
  the server serves the artifact and the author's caption; interpretation is the agent's.**
- **Why it accelerates.** In this corpus's subject matter the diagram frequently carries content the
  prose only gestures at: a wall-and-chamber decomposition of the stability manifold *is* the
  specification of where to look for a destabilising object; a commutative diagram *is* the statement
  of a compatibility; a Newton polygon *is* the object. Three effects: an agent evaluating a candidate
  against a paper's geometry can see the geometry; `\ref{fig:N}` stops dead-ending, the same class of
  broken traversal `statement-refs` fixes for theorems; and preserved tikz-cd source is the cheapest
  bridge from a paper's homological algebra to a Lean statement anyone has proposed. **The density
  argument is decisive against the alternatives:** at 323 captioned floats plus 1,483 in-math
  diagrams, this is ~6× denser than the tables item killed for thinness (52 captioned tables
  **[measured]**) and infinitely denser than the ancillary-files item judge 1 ranked a top-4 bet
  (**0** ancillary directories — see §5).
- **Size** M. **Depends on** nothing.
- **Risks.** LaTeXML figure output is heterogeneous: some diagrams survive as inline SVG, some are
  rasterised, some are lost. `asset_kind=absent` must be first-class, and **the SVG-vs-raster
  distribution is the single number that decides this item's value — measure it in a ~30-figure spot
  check before building.** Asset bytes inflate responses: hard size cap, metadata-only fallback,
  never on a default `search_papers` row. Figures are arXiv-licensed content and must inherit the
  per-chunk `license_ref` gate and be excluded from any export by default. Only 32% of papers have a
  captioned float, so caption search alone has limited reach — the in-math diagram half is the larger
  prize and the less certain one.
- **Boundary.** [5] offline indexer over bytes already on disk; read-only serving; no rendering, no
  interpretation server-side. [6] `asset_kind` and `resolution` are separate axes; `absent` (the
  author's figure did not survive parsing) is an abstention distinct from `not-indexed`; a caption is
  the author's text wrapped as `<retrieved_chunk>`, never a description the server vouches for. [7]
  inherits the existing `license_ref` gate; excluded from the deterministic export tar by default.
  [8] ~2 hours for the spot check, then mechanical.
- **Scores.** D — / B — (postdates the judges). My assessment: **D 6, B 7.** This is the largest
  single miss in the six-lens scan.

---

**4.2 `scope-envelope` — standing-hypothesis resolution on retrieved statements**
*(L1-scope-envelope, screened to an R2-m3 amendment)*

- **Blocked today.** A search for "rationality criterion" returns a row for `Theorem 3.4: X is
  rational` carrying only `{chunk_id, label, paper_id, score, section_path, snippet, source_kind}`
  (`server/handlers/search.py:1066-1079` — `kind` is not even emitted). The paper's §0 "Conventions:
  throughout, k is algebraically closed of characteristic 0" exists in the corpus **as its own chunk
  with `kind='convention'`** (`ingest/store.py:133-167`) and nothing joins the two. So the agent
  proposes a characteristic-p counterexample to a characteristic-0 theorem and returns a confident
  wrong answer after a full pipeline run.
- **Mechanism.** A **zero-LLM deterministic resolver** — `section_path`-prefix containment over the
  already-written `convention|assumption|notation|hypothesis` chunk kinds, plus a curated
  heading-synonym set (*Conventions*, *Notation and conventions*, *Setup*, *Standing assumptions*) —
  added as **R2-m3's measured baseline arm** so the marginal value of R2's local-llm pass is visible
  and killable (the same split-reporting discipline R6-KR2 imposes on DAG extraction). Plus a
  byte-cheap `scope_status` token on existing `search_papers` rows, so an out-of-scope statement is
  visible at ranking time without spending a second capped call.
- **Size** S. **Depends on** R2-m1/m2.
- **Why it accelerates.** This is the single largest manufacturer of false counterexamples in math.AG
  and it is a one-field fix. Kodaira vanishing holds in characteristic 0 and fails in characteristic
  p (Raynaud); nearly every math.AG paper puts `char k = 0` in a conventions block and never repeats
  it. Same for algebraically-closed, properness, Q-factoriality, and "variety means irreducible and
  reduced".
- **Risks.** Recall gap on papers stating conventions inline in §1 prose rather than in a marked
  environment — the chunker only tags what the author environment-marked. Heading synonyms are
  per-subfield. `section_path` prefix semantics need care for appendices and untitled §0.
- **Boundary.** [5] query-time resolution, or an ingest-computed column via the existing
  `_migrate_chunks_schema_if_needed` add_columns loop. [6] four first-class abstention tokens;
  `resolved` asserts only *these chunks are in prefix scope*, **never** *the theorem's hypotheses are
  exactly these*. [8] ~1–2 h curating synonyms plus a ~30-resolution hand audit.
- **Scores.** **D 5 / B 9** — a real split. Judge 1: a filter, not a generator. Judge 2 is right on
  the decision: on a solo-maintainer budget, preventing one confidently-wrong full run is worth more
  than a marginal improvement in candidate generation, and this is S-sized with no external data and
  no labeling.
- **Residue.** The hypothesis capability itself is **R2-KR3 / R2-m3 `effective_hypotheses`**
  (with `stated|inherited|inferred` provenance). This contributes the deterministic baseline arm and
  the search-row token — an acceptance-criterion amendment, not a lane.

---

**4.3 `notation-consensus` — corpus-wide symbol classes and a two-paper transport check**
*(L5-notation-reconciler, screened; the term layer struck)*

- **Blocked today.** `get_definitions` **requires** a `paper_id` and serves only that paper's macros
  (`server/handlers/definitions.py:68-69`); `DEFINITIONS_SCHEMA_V1` has `paper_id` non-nullable, no
  term column, no divergence field; and `ingest/index_definitions.py` states *"Scope at v1:
  preamble-derived definitions only"* — so the definitions table has never contained a mathematical
  definition, only a macro. There is no corpus-level view of a symbol and no way to compare two
  papers.
- **Mechanism.** *(1)* A symbol-consensus index over the **164 `preamble.json` files already on
  disk**: `symbol_raw → normalised-expansion class → paper_ids`, normalisation stripping the
  typographic layer (`\mathop`, `\ensuremath`, `\operatorname`, `\mathrm`, spacing, braces), with the
  **ruleset versioned and raw expansions retained** so a caller can disagree. *(2)*
  `notation_check(source_paper_id, target_paper_id)` — every symbol whose expansion class differs
  between two papers. *(3)* As a rider, not a capability: the env aliases `defi` (74) and `dfn` (49)
  are absent from `_THEOREM_ENV_KINDS` (`ingest/chunker.py:206-252`) and fall through to
  `kind="stmt"` — **~123 mislabelled definition environments, ~10% of the corpus's 1,199
  definition-family environments**, which will silently under-serve #40's planned `kind=definition`
  filter.
- **Why it accelerates.** Converts the most common *silent* failure in cross-paper reasoning into a
  cheap precondition check. Before a tactician builds an argument on a result imported from another
  paper, one call names every symbol whose meaning differs — the difference between a real proof and
  a plausible-looking wrong one. It also makes the sketcher school-aware, which is exactly the tacit
  knowledge a human advisor supplies and a corpus of chunks does not.
- **Size** M (the symbol layer alone is S). **Depends on** nothing.
- **Risks.** The macro layer is a **proxy**: two papers can agree on `\D` and still mean different
  things by "stable"; a symbol divergence can be harmless. Frame it as a high-precision *warning*
  surface, never an equivalence checker. Normalisation is itself a judgement (`\mathcal` vs
  `\mathscr`) and must be versioned and auditable. **The transport risk that actually kills a
  formalization is corpus↔Mathlib divergence, not corpus↔corpus, and `notation_check` cannot see it.**
  The alias fix mutates `kind` on existing rows — a real `corpus_version` migration with cache
  invalidation, not a quiet backfill.
- **Boundary.** [5] offline CLI over existing artifacts; `scope` is one optional argument on an
  existing tool riding W1. **Explicitly no LLM notation extractor** — that is where TheoremGraph
  spends model calls and where §5 item 10 draws the line. [6] `divergence` carries its own evidence
  (the competing expansions plus the papers asserting each) and is never collapsed into a boolean
  "compatible"; `single-source` and `not-in-corpus` are tested abstentions.
- **Scores.** **D 4 / B 9** — the widest split after the name linter, and both are right about
  different things. Judge 2's cheapness case is unanswerable (the measurement below was produced in
  one script run over files already on disk); judge 1's ceiling case is also correct. **Build it as
  hygiene; do not expect a finding from it.**
- **Measured signal.** 14,537 macros, 3,429 distinct symbols, 860 raw-divergent, **661 (19.3%) still
  divergent after normalisation**. Worst offenders semantically real: `\kk` 11 classes, `\HH` 8,
  `\D`/`\H`/`\A`/`\RHom` 7 each.
- **Residue.** The corpus-wide **term**→definition index is **#40's** explicitly gated item
  (*"stays gated on observed filter usage rather than building blind"*) and must be raised there, not
  here.

---

**4.4 `ascii-form` — populate the executable rendering of the corpus's own equations**
*(the ingest half of L1-cas-bridge; the generic kernel does not survive — see §5)*

- **Blocked today.** `ingest/schema.py:340` declares an `ascii_form` column and
  `ingest/extract_equations.py` writes the literal empty string for every row at **both** call sites
  (`:195`, `:264`) **[verified]**. So an agent that wants to test equation (3.7) must re-transcribe
  LaTeX or MathML into Sage/Macaulay2 by hand — the exact step where transcription hallucination
  enters silently and poisons the downstream result, with no way for the human collaborator to
  notice.
- **Mechanism.** Populate `ascii_form` with a CAS-executable rendering derived from the stored
  MathML, resolving author macros from the shipped definitions table, plus a
  `cas_form_status ∈ {executable, partial, unconvertible}` axis where `unconvertible` will be the
  honest majority and must be reported. **The conversion source is much better than the original
  proposal assumed:** `server/retrieval/equations.py:94-101` records that LaTeXML runs
  `--format=html5` and emits **parallel markup**, so the stored `mathml` column already carries a
  Content-MathML `<annotation-xml>` (`<apply>`/`<ci>`/`<cn>`) plus an x-tex annotation. Content
  MathML → CAS is a mechanical mapping, not the lossy presentation-MathML guess the risk register
  feared.
- **Size** M. **Depends on** nothing — but see the caveat below.
- **Risks.** A format converter is a long tail that never quite finishes, and the golden-fixture
  suite is a permanent liability. **The honest caveat: the equations table has apparently never been
  materialised on this workstation** (the value-equation-index screen found only `chunks.lance` +
  `corpus-version.json` in every populated notebook), so step one is running the existing
  `ingest/index_equations.py` over one notebook — until then this populates a column nothing reads.
- **Boundary.** [5] offline ingest write, the sanctioned path. [6] `unconvertible`/`partial` are
  first-class abstentions distinct from operational status; the server never asserts that a
  conversion is mathematically faithful.
- **Scores.** **D 6 / B 6.**

---

### Theme 5 — Structure: the statement graph, goal-shaped retrieval, and the ingest frontier

**Thesis.** arXMCP models statements as chunks and relations as paper→paper citations. The question
that decides whether a suspected counterexample is worth chasing — *if Lemma 3.2 is false, what
dies?* — is unaskable, and the question that costs the most tool calls in a proof attempt — *get me
the exact statement of the thing this step invokes* — takes 3–5 calls and a guess. Both are the same
missing edge. This theme is also where the corpus-closure condition bites hardest and must be stated
honestly rather than designed around.

---

**5.1 `statement-refs` — cross-paper locator resolution, persistence, and the reverse direction**
*(L5-stmt-dep-graph, screened to three residuals)*

- **Blocked today.** An agent reads "by [7, Theorem 1.2]" and calls `cite_neighbors`. What comes back
  is the paper plus **one arbitrary representative chunk**, selected by kind priority
  (`server/graph_queries.py:76,:217-231`; `server/graph_types.py:29-31` documents it as "the first
  `kind='stmt'` chunk by best-effort priority"). The reverse question cannot be asked at all: the
  Kùzu model has only `papers` nodes and `cites FROM papers TO papers`
  (`ingest/kuzudb_schema.py:73-90`), and the intra-paper pass that *does* resolve `\ref{}` labels
  discards every resolved pair into one paper self-loop (`ingest/intra_paper_refs.py:301-310`).
- **Mechanism.** Three things and only three. **(a) The cross-paper leg**: parse a locator out of
  `ltx_cite` inner text ("[7, Theorem 1.2]"), follow the in-markup `href="#bib.bibN"` to the
  `ltx_bibitem`, and join the locator to a target chunk on `printed_number` (chunks schema v2,
  chunker-native) falling back to `theorem_label`. **(b) Persist** the intra-paper pairs as a served
  queryable index rather than throwaway eval qrels. **(c) The reverse `used_by` direction** — the
  blast cone, the only genuinely unaskable query today. Storage is a Kùzu `statements`/`uses` pair
  or, if #62's archived-Kùzu rel-ALTER dry run comes back negative, a **standalone SQLite edge table
  with no capability loss at depth 2** — the hedge is designed in, not bolted on. Each edge carries
  `extractor ∈ {label-exact, locator+printed_number, locator+title-resolved}` with its own confidence
  and evidence span.
- **Why it accelerates.** If you suspect Lemma 3.2 is false, the thing you need first is its
  downstream cone — every statement whose proof leans on it. That query is unaskable today and it is
  also what tells you whether a suspected counterexample is *interesting* (load-bearing) or a
  curiosity (a leaf). It is the ranking signal `boundary-markers`' complement view needs to be more
  than a list.
- **Size** L (much smaller after the funded half). **Depends on** evidence-engine-e4.
- **Risks.** **Chunk-boundary replay must reproduce content-addressed chunk_ids exactly or the index
  mis-anchors** — the known-hard part, which `source-truth-m2`'s backfill already hit and documented
  as requiring abstention. Locator→`printed_number` precision is unmeasured (author numbering vs
  LaTeXML auto-numbering; "Theorem 1.2(iii)"; ranges). **~90% of edges will be dangling and MUST be
  modelled as first-class `unresolved` rows — dropping them would make a 10%-complete graph look
  complete.**
- **Boundary.** [5] offline CLI writes, MCP reads, pure regex/scalar lookup, no LLM. [6] each edge
  carries its `extractor` axis with its own confidence and evidence; `resolution="unresolved"`
  (abstention) distinct from `graph_status="absent"` (operational); **confidence never inferred across
  axes** — a `label-exact` intra-paper edge lends no confidence to a `title-resolved` cross-paper one.
  [7] all mined bytes are the corpus's own LaTeXML output under the existing `license_ref`; the
  external TheoremGraph HF dataset (`uw-math-ai/theorem-matching`, CC-BY-SA-4.0) may be used only as
  an offline candidate-layer precision cross-check and never redistributed.
- **Scores.** **D 7 / B 7.** Both docked for the ~10% ceiling.
- **Measured signal.** 15,406 `ltx_cite` elements; 2,879 carry a Theorem/Lemma/Proposition/Corollary
  locator; **2,829 (98.3%) resolve to a specific `bib.bibN` via the href**; 728 bibitems carry an
  explicit arXiv id needing **no network call**; only 285 target a paper in this corpus.
- **Residue against existing plan.** The intra-paper `\ref{}` extractor with chunk-boundary replay,
  **including the ~50-pair hand audit**, is already funded as `evidence-engine-e4` — **#14** (epic),
  **#20** (`tools/build_dependency_eval.py`, D9-R15), **#24** (spike). **Build it once as #20's
  generator with this index as its second consumer.** Richer paper-grain edge context is **#42**.

---

**5.2 `goal-shaped-retrieval` — conclusion-span embedding and an unmet-hypothesis list**
*(L4-hypothesis-conclusion, screened to the conclusion-side consumer)*

- **Blocked today.** A tactician holding a proof state — hypotheses {X smooth projective, ρ(X)=2,
  −K_X nef}, goal {H¹(X,L)=0} — has no way to express it. Every retrieval path scores a whole
  statement against a prose string; no column separates assumption from conclusion. So the agent
  writes a sentence and hopes.
- **Mechanism.** A `conclusion`-span embedding column plus an additive
  `search_papers(goal=…, context_hypotheses=[…])` mode scoring `cos(conclusion_emb, goal)` with a
  hypothesis-coverage term, returning a per-row **`unmet_hypotheses[]` subgoal list** — actionable
  output rather than a ranked blob — and publishing the **measured corpus decomposition rate** so a
  caller knows what fraction of the corpus this mode can see. `retrieval_mode` names the route
  honestly, as every other path already does.
- **Why it accelerates.** This is the premise-selection bottleneck at the sketcher→autoformalizer
  handoff, and the one place where a better embedder demonstrably will not help (MIRB). The
  retrieval-unlocks roadmap already tests the other lever (#47 embedder bake-off); nothing tests this
  one. Downstream it is the substrate for hypothesis-gap targeting: rank conclusions by how *narrow*
  the hypothesis set is that anyone has proved them under, and you have a ranked list of where a
  counterexample could live.
- **Size** L. **Depends on** R2-m3 (`effective_hypotheses`) — **it must consume that, not build a
  second hypothesis extractor, and cannot ship ahead of R2's precision gate.**
- **Risks.** The one irreducible labeling cost in the analysis (~60 hand-checked decompositions), in a
  project that has already been burned by labeled artifacts that never got labeled. A **wrong** split
  is worse than none — it produces confidently wrong `unmet_hypotheses`. Adds an embedding pass per
  statement span, an ingest-cost increase to measure against the `scale-ops-hardening` linearisation
  work before fleet-wide rollout. Thin incremental value: the column is useless until the ranking mode
  lands.
- **Boundary.** [6] `decomposition_status` carries `undecomposed` distinctly from operational status;
  coverage is published rather than implied.
- **Scores.** **D 6 / B 5.**

---

**5.3 `frontier-ranking-term` — rank un-ingested works by statement-level proof-step demand**
*(L5-dependency-frontier, screened to a scoring contribution)*

- **Blocked today [measured via the lens, consistent with my count].** Of 2,829 statement-level
  locators resolving to a bibliography entry, only 285 target a paper this corpus contains — so
  roughly **nine of ten proof-step dependency walks dead-end**. The notebook membership model is a
  hand-maintained `papers.txt`. The operator has no signal about which missing work would unblock the
  most reasoning.
- **Mechanism.** A scoring contribution **inside `notebook-paper-discovery-e4`'s existing ranker**,
  not a new lane: rank candidates by distinct citing *statements*, weighted by whether the citing
  chunk is a `kind='proof'` chunk of one of the notebook's own theorems, times distinct locators
  cited from that work — with the offline arXiv-id-from-bibitem tier (**728 measured cases**) kept
  separate as the high-confidence, zero-network path.
- **Why it accelerates.** It closes the loop and makes everything else compound: each ingest cycle
  guided by this converts dead-end chains into traversable ones, which raises the yield of
  `statement-refs`, which sharpens the ranking. It also gives an honest quantitative answer to "is my
  corpus good enough for this problem yet?" — **which is the operational form of the corpus-closure
  condition in §2.**
- **Size** S. **Depends on** `statement-refs`; must not ship ahead of its precision audit.
- **Risks.** Citation-demand ranking biases toward classical heavily-cited works rather than the
  frontier — surface demand rank *and* recency and let the operator judge; it is a proposal surface,
  not an autopilot.
- **Boundary.** [5] offline report; the "add to notebook" action lives in `/ui/` and terminates in the
  existing operator-confirm ingest flow — explicitly **not** the env-gated auto-accept that §5 item 18
  kills. [6] emitted as a dated scoped census with the citing sentences as per-row evidence;
  `unresolved-target` rows reported as a first-class category, because an honest frontier must show
  what it could not identify.
- **Scores.** **D 3 / B 7.**
- **Residue.** The CLI, the resource, the UI card, and the operator-gated add are **all already
  delivered** by `notebook-paper-discovery-e2`/`e4`, D2-R05's `arxmcp://notebooks/{slug}/digest`, and
  **#144**. Only the ranking signal is new — and it is genuinely inexpressible in e4's BGE-M3
  similarity or e3's S2/OpenAlex channels.

---

### Theme 6 — The object axis, gated by one measurement

**Thesis.** Every counterexample hunt terminates in an object, and arXMCP has none — this is the only
completely empty stage in the capability map with no partial credit anywhere. It is also where the
two judges disagreed most violently (9 vs 2-with-kill) and where both were half right. The
resolution is to **stage it behind a cheap measurement**, because the honest question is not "should
we ingest object data" but "does this corpus even mention objects by canonical name?" — and nobody
measured.

---

**6.1 `object-label-census` — extract canonical object identifiers from corpus text, and measure**
*(L6-object-refs, ruled NOVEL, re-scoped to lead with its own measurement)*

- **Blocked today.** An agent testing a concrete object — a specific elliptic curve, a reflexive
  polytope, a Fano threefold — cannot ask what the corpus already says about *that object*. The chunks
  schema models no external object identifier; `SUPPORTED_FILTER_KEYS` is
  `frozenset({"paper_id","source_kind"})` (`server/handlers/search.py:265`); the graph's only external
  ids are bibliographic and, per D6's own referee check, exposed on **zero** server surfaces. The only
  route is dense semantic search on a label like `11.a1` — precisely the input BGE-M3 handles worst.
- **Mechanism.** A deterministic, LLM-free extractor riding the DOM walk the chunker already does,
  producing `object_refs(chunk_id, paper_id, namespace, label, surface_form, char_span, confidence)`.
  Namespaces declared in a committed `resolvers.yaml`: label grammar (regex **plus required context
  tokens** to suppress false positives), canonical URL template, license class, `served|candidate`
  flag. Launch namespaces: LMFDB label grammars, OEIS A-numbers, Kreuzer–Skarke polytope references,
  MSC classes (from the arXivRaw `msc-class` field already flowing through `ingest/oai_delta.py` —
  the explicit escape hatch D6-R08 sanctioned), Mathlib declaration names. Serve `object_refs` on
  chunk rows, a `filters={'object_ref': 'lmfdb:11.a1'}` key, and an `arxmcp://resolvers` resource
  publishing the namespace→template→license map. **arXMCP stores label strings and URL templates. It
  stores no third-party object data, ever.**
- **Why it accelerates.** Counterexample hunts in math.AG/NT are object-indexed, not concept-indexed —
  the owner's own stability-manifolds programme turns on a named object (the rank-107 Chern vector),
  and the expensive question is always *what is already known about this one*. It also creates the
  handoff the compute tier needs: once the agent holds a label, it can hand that to CYTools/PARI/Sage
  **in the orchestrator** — a pivot impossible today because the label never leaves the prose.
- **Size** M. **Depends on** nothing. **Ship the measurement first.**
- **Risks.** **Short-label grammars are the whole risk**: `11.a1` and `1.1.1.1` collide with equation
  numbers and version strings, so context gating is mandatory and precision must be measured.
  Namespace maintenance is a recurring per-namespace tax with upstream drift. Scope creep toward
  mirroring the resolved object must be a stated non-goal — the license classes are the guardrail.
  **My prior, unmeasured, is that canonical external object labels are rare in a Bridgeland/math.AG
  corpus; measure occurrence density on the live notebook before funding half a day per namespace.**
- **Boundary.** [5] extraction inside offline ingest; **no query-time network fetch** — the registry
  serves URL templates and dereferencing is the orchestrator's job. [6] each ref carries confidence
  with `surface_form` and `char_span` as evidence; `not-in-corpus` and `ambiguous` distinct from
  `unavailable`. [7] `resolvers.yaml` records a license class per namespace; anything non-commercial
  or unclear is flagged candidate-layer, never redistributed, never promoted without a recorded check.
- **Scores.** **D 5 / B 6.**
- **Trim.** Drop Stacks tags (duplicates **#43**'s `theorem_label` minting) and bare DOIs/arXiv ids
  (D6-R05's paper-level half) from the launch set.

---

**6.2 `object-family-registry` — families and enumerators, with zero object rows stored**
*(the resolution of the judges' 9-vs-2 split on L1-object-layer / L3-fingerprint-census)*

- **Blocked today.** Loop stage 5 has no data at all, and no proposal survives that would supply it at
  acceptable cost.
- **Mechanism.** Not an object store. A **registry**: `object_families(family_name, enumerator
  {module, version, invocation}, license_posture_record, canonical_ref, bridge_to_definitions)` — the
  family's name, a pointer to the enumerator and its version, a recorded per-source license check,
  and the join to corpus definition vocabulary and R2 claim identity so a search result can report
  "and here is the enumerable set, N members, enumerated by X@v". **Zero object rows are stored in
  arXMCP.** The orchestrator enumerates outside the server. Filed as an **adapter instance under
  R7-KR1's existing framework** (which already specifies "per-adapter module with version pinning,
  license posture record, rate-limit budget, and the candidate-layer schema"), never as a second
  parallel framework.
- **Why it accelerates.** It gives the orchestrator exactly what it needs — the family, its
  enumerator, and the corpus statements that quantify over it — while keeping arXMCP out of the
  business of hosting 473,800,776 polytopes. It also converts the "is the failure essential or an
  artifact" question from philosophy into a census: if a violation occurs at one object and nowhere
  else in the family it is an artifact; on a positive-dimensional subfamily it is essential.
- **Size** M as a registry (the original XL was the object rows). **Depends on** `object-label-census`
  (its measurement gates whether any family is worth registering), R7-KR1, `census-record`.
- **⚠ License status — unresolved and blocking.** Two lenses assert **incompatible licenses for OEIS**:
  one says CC BY-SA 4.0 per the `oeis/oeisdata` LICENSE and concludes it may be promoted to served
  evidence; the other says CC BY-NC-SA and concludes candidate-layer-only. **These cannot both be
  right and the screen ruled both NOVEL without cross-reading them.** The worst case is that both are
  right about *different artifacts* (the git repo vs oeis.org content), meaning a served row's license
  depends on which file the operator downloaded — exactly the ambiguity constraint 7's recorded
  per-source check exists to eliminate. **Nothing OEIS-derived ships until that check is recorded.**
  Separately: LMFDB's *code* is GPL-2+ but its *data* license is not stated on the same page; GRDB's
  terms were not located. GRDB is reported as **CC0** by one lens and is the only candidate that
  clears cleanly on the evidence in hand — and it is math.AG, the corpus's centre of mass.
- **Other risks.** Mission drift from "research-mathematics corpus" to "mathematical data plane"
  should be an explicit owner decision, not a side effect. Family↔corpus-vocabulary bridging is fuzzy
  and needs conservative thresholds.
- **Boundary.** [5] offline registration, read-only serving, the agent does the mathematics. [6]
  absence answers are dated scoped censuses naming the family, the exact enumerator version, the
  predicate, and the date — never "no such object exists". [7] this is the constraint the whole design
  is organised around.
- **Scores.** **D 9 / B 2 (kill as proposed)** — the widest disagreement in the analysis. Judge 1 is
  right about the modality: it is the only proposal touching loop stage 5, and every recent
  counterexample terminated in an object. Judge 2 is right about the build: XL, license-encumbered,
  duplicates R7-KR1, and — decisively — judge 1's own worked example ("ingest the 4,319
  three-dimensional reflexive polytopes and compute the stringy E-function") **requires PALP/CYTools,
  i.e. the compute lane, whose generic form the screen struck and routed to R4.** The registry form
  is my resolution: **judge 2 on the decision, judge 1 on the importance.**

---

## 4. Sequencing

Six themes, ordered by leverage, sequenced against the existing roadmaps.

**Wave 0 — measure before spending (weeks 1–2).**
Nothing here is a capability; all of it decides capabilities.
1. `discovery-backtest` (3.2), three cases. **Follows nothing.** ~4 owner-days.
2. Three cheap measurements that each gate an M-sized item and cost hours: the **figure asset-kind
   spot check** (~30 figures — decides whether 4.1 is a full lane or caption-and-reference indexing
   only); the **object-label density scan** on the live notebook (decides whether Theme 6 has any
   input); and **materialising the equations table** on one notebook (`ingest/index_equations.py`
   has apparently never been run — decides whether 4.4 populates a column anything reads).

**Wave 1 — the substrate and the free wins (weeks 3–8).** Nothing here waits on anything unbuilt.
3. `span-substrate` (1.1). **Follows nothing.** The single highest-return build in the document.
4. `notation-consensus` (4.3) + the `defi`/`dfn` alias migration. **Follows nothing**; the alias fix
   needs a `corpus_version` migration window.
5. `figure-lane` (4.1), scope set by the Wave-0 spot check. **Follows nothing.**
6. `census-record` (3.1) as an extension of the **already-Accepted** evidence-ledger standard.
7. `lean-name-inventory` (2.3) + `formal-env-stamp` (2.6). **Both ride the W1 batched
   TOOL_SCHEMA_VERSION window — `agent-platform-e2` / #65 / #72 / #87 — and must not mint their own
   re-pin.**

**Wave 2 — the miners (weeks 9–16).** Each is a YAML file plus a sampler run once 1.1 exists.
8. `boundary-markers` (1.2), **claim index only; the complement view is gated on measured precision.**
9. `technique-transfer-map` (1.4), with the vacancy view gated on a non-empty-cell count.
10. `reduction-and-status` (1.3).
11. `revision-drift` (1.5) part (a) only — the `<comments>` parse — landing as **additive columns on
    `source-truth-e1`/`m1`'s revision registry**, which it must follow. Part (b), the statement diff,
    is gated on measured yield.
12. `attention-queue` (1.6), as soon as two miners exist to feed it.

**Wave 3 — structure and hypotheses (parallel with Wave 2, different dependencies).**
13. `statement-refs` (5.1). **Must follow `evidence-engine-e4` (#14/#20/#24)** — build the
    intra-paper extractor once, as #20's generator, with this as its second consumer. Serving rides W1.
14. `frontier-ranking-term` (5.3). **Folds into `notebook-paper-discovery-e4`'s ranker.** Must follow
    5.1's precision audit.
15. `scope-envelope` (4.2). **Must follow `R2-m1`/`m2` and lands as an acceptance-criterion amendment
    to `R2-m3`**, as its measured deterministic baseline arm — not a lane.
16. `goal-shaped-retrieval` (5.2). **Must follow `R2-m3`'s precision gate** and consume its
    `effective_hypotheses`.

**Wave 4 — the Lean lane (gated on R3, which is not this document's to schedule).**
17. `refutation-lane` (2.1). **Must follow `R3-m1`** (honest statuses), **`R3-m2`** (isolation, before
    agent-supplied long-running search ships), and **`R3-m5`/`m7`** (a warm Mathlib-resident env).
18. `directional-definition-probe` (2.2) as a mode of 2.1; attaches evidence to **R5-KR6**'s
    human-owned faithfulness axis without setting it.
19. `goal-search-mode` (2.4) after `R3-m7`. **Do not file Route A (Loogle) — answer spike #186 first.**
20. `obligation-decomposition` (2.5). **Spike the `abstractMVars` lift on 5 real skeletons before
    committing; cut rather than ship partial.**

**Wave 5 — memory and objects (gated on things outside this repo).**
21. `attempt-ledger` (3.3), **telemetry fields stripped**, after `agent-platform-e5` / #68 gives the
    orchestrator repo somewhere to live.
22. `novelty-census-runner` (3.4); benefits from #42's S2 client but does not require it.
23. `computation-key-and-replay` (3.5), filed against **#69**, only if a computation lane exists.
24. `object-family-registry` (6.2) as an **R7-KR1 adapter instance**, only if Wave 0's density scan and
    a recorded license check both clear.

### Where the owner-hours go

This is the binding resource and the sequencing above is a claim about it. The **irreducible
judgement spend** across the whole document is roughly:

| Item | Owner-hours | Kind |
|---|---|---|
| `discovery-backtest`, 3 ingredient decompositions | ~3 days | mathematical reading — not automatable |
| `span-substrate`, abbreviation/segmentation guards | ~0.5 day | judgement |
| 5–6 lexicons (boundary, technique, reduction, resolution, revision-comment) | ~0.5 day each ≈ 3 days | **authoring** — does not scale with corpus size, reusable across every future notebook |
| One precision sampler run per lexicon | ~2 h each ≈ 1.5 days | bounded sampling, *not* a campaign |
| Figure spot check; object-label density scan; notation ruleset review | ~1 day total | measurement |
| `goal-shaped-retrieval` golden decompositions | ~1 day | **the one true labeling cost** — and the one item that should be cut first if hours are short |
| `refutation-lane` finite instantiations | recurring, per use | mathematical judgement, permanently |
| `novelty-census-runner` query plans | 15–30 min per census, forever | non-amortising |

Everything else is mechanical. Total discretionary first-pass ≈ **3–4 owner-weeks**, and the analysis's
single strongest sequencing claim is: **spend the first four days on the backtest, before any L or XL
commitment.** It costs less than the owner-hours of a single L item and it is the only thing that can
distinguish the two judges' theses with evidence rather than argument.

The distinction that makes the mining family survivable is **authoring versus labeling**: a lexicon is
a vocabulary the owner already has, written once, reusable forever, independent of corpus size. A
golden fixture set or an entity-identity review queue grows with every notebook and is a permanent
liability. Wave 2 is entirely authoring. Wave 3 contains the one labeling item, and it is explicitly
the first cut.

---

## 5. Explicitly NOT proposed

### 5.1 Screener DUPLICATE rulings — coverage was checked

| Proposal | Ruling | Already owned by |
|---|---|---|
| Chunk-level intra-paper dependency DAG | DUPLICATE | **R2-KR5** verbatim ("intra-paper `\ref{}` edges land at claim grain, superseding the self-edge"), **R2-m2**, **R6-KR1/KR3**, **#20**, **#24** |
| Cross-paper statement identity + conjecture-frontier artifact | DUPLICATE | **R2-KR1** (dual identity + `restates` edges), **R2 brief :21-22** (cross-version alias maps), **R6-KR6/KR7**, **#84**. Its core signal — dense cosine clustering of statements across papers — is on **R2's wont list verbatim**: *"No cross-paper semantic similarity edges (that is retrieval, already served)."* |
| Canonical claim identity + evidence-attached alias graph | DUPLICATE | **R2-KR1/KR2**, **R2-m1/m2**, **R7-KR1**, **#69**. The lens inventoried only the six materialised roadmaps and missed the brief set those were materialised *from*. |
| Statement-grain dependency graph + refutation blast radius | DUPLICATE | **R2-KR5/KR1**, **R2-m2**, **R6-KR3**, **#20/#24/#62** |

### 5.2 Killed on measurement — including one that was a top-4 ranked bet

- **The ancillary-files lane (`anc/` code and data artifacts).** This is the most important
  correction in the analysis. Judge 1 scored it **8** and listed it **fourth among top bets** ("the
  highest leverage-per-owner-hour discovery signal in the set"). It has **zero input**. The same
  capability was already ruled INFEASIBLE earlier in the same screening round on a measured census,
  and the screener then ruled its twin NOVEL without cross-reading its own kill list. I reproduced the
  measurement independently: **`find raw -maxdepth 3 -type d -iname anc` returns 0 across all 173 raw
  paper directories**, and the only two subdirectories in the entire corpus are
  `2412.08531/Figures` and `2502.18894/figures` **[measured 2026-07-25]**. Judge 1's stated value —
  "hand an agent the author's own search harness and the job collapses to changing one loop bound" —
  has literally no input on this corpus. Only the `claim_bounds` idea (mining stated verification
  bounds — "verified for all n ≤ 10⁶") survives, and since that is a lexicon it belongs in
  `span-substrate` as a sixth marker class, not an L-sized lane. **Re-open only on a re-measured,
  pre-committed threshold after the corpus takes on computational papers; the census is one command.**
- **Table extraction as a first-class atom.** Killed on measurement: **52 captioned `ltx_table`
  floats across 173 papers (0.30/paper) [measured]** — the 28,968 raw `<table>` tags are LaTeXML
  equation-alignment markup, not tabular data — and the captions that exist are symbolic reference
  tables, not numeric experimental records. For calibration: the figure lane has ~6× the captioned
  density and ~29× the total mathematical-artifact density.
- **Value-level equation fingerprinting** (evaluate expressions at pinned points to match by value
  rather than tree shape). Sound idea, no substrate: the **equations table has never been
  materialised** on this workstation, and there is no MathML→SymPy import path — only
  `parse_latex`, an ANTLR parser over a deliberately limited LaTeX subset, against research math.AG
  with per-paper macro preambles. The correct next action is the coverage spike, not an index issue.

### 5.3 Judges' kills, and the one I am adding

- **`compute` as a generic multi-engine CAS tool with agent-supplied programs** (judge 2: **4**).
  **R4-verified-computation already adjudicated this design space in the opposite direction**: named,
  oracle-checked operations behind a pinned separately-released provider with replayable receipts, and
  an exit gate of *"zero unsupported inputs answered with numbers"*. A `cas_eval` executing
  agent-supplied source is the anti-pattern that gate exists to prevent — no oracle, no replay
  witness, no scope statement. It also multiplies moving parts beyond a solo maintainer's reach: four
  engines pinned across Windows and WSL2, two with no native Windows build, a warm pool for the WSL
  boundary, per-engine result mappings, and an ACE surface strictly worse than `lean_verify` that
  inherits the documented grandchild-reaping gap and a `RLIMIT_AS` that is a no-op on the tier-1 host
  (**#7**, still open). **What survives is the ingest half (`ascii-form`, 4.4) and the boundary
  statement: if a computational tool is ever wanted, it goes through R4's receipt-and-oracle
  discipline.**
  **⚠ Trojan horse to note if this is ever revisited:** the proposal specified **python-flint
  in-process**, and *every* sandbox argument in it — managed child, wall timeout, kill/respawn,
  RLIMIT_AS, fresh temp CWD, no egress — describes the *subprocess* engines and silently does not
  apply to the in-process one. Separately, a CAS is a general filesystem interpreter, so "persists
  nothing corpus-visible" is a convention, not a property; `lean_verify` is defensible under ADR rule
  2 largely by accident of what Lean elaboration can do.
- **The falsification harness** (offline family × predicate search with telemetry, resumable cursor,
  kill-by budget, KAT controls; judge 2: **3**). The concept is right and the exhausted-vs-budget
  distinction is genuinely load-bearing — but the harness has **no dependency on arXMCP at all** (a
  family enumerator plus a predicate touches no chunk, no equation, no notebook), and the owner has
  already built telemetry + resumable cache + kill-by budget once in the adjacent `stability-mflds`
  repo as the direct remediation of the 67-CPU-hour runaway. Building it here makes a third copy and
  repeats the placement error the boundary ADR corrected for the dispatch loop. **What survives is the
  served census record and its three-token verdict vocabulary, folded into `census-record` (3.1); the
  harness belongs in the external repo where the enumerators live.**
- **The local hammer lane** (LeanHammer/Duper premise-selection ladder). INFEASIBLE as a
  local-only build: LeanHammer's headline 33.3% is measured **with** its remote `Cloud.premiseSelector`
  against `leanpremise.net`, which constraints 1–2 require disabling, and there is no measured
  substitute; Zipperposition ships prebuilt per-platform binaries with no documented Windows support,
  so the realistic route is a second Mathlib-linked lake project in WSL2 kept in lock-step across six
  pinned components. And the surviving fallback rung is not a capability: **`aesop` is already
  installed at `…/repl/.lake/packages/aesop`, so an agent can write `by aesop` inside a `lean_verify`
  snippet today.**
- **An in-server Mathlib formalization-frontier ledger.** ALREADY-REJECTED — cross-synthesis §5 item 2
  (D2-R08), *"compose, don't ingest"*, with the scope decision tracked as unrun spike **#186**. The
  proposal's own admission is fatal on its own terms: *"name-based matching across an informal/formal
  boundary is weak; 'stability condition' will not lexically match `Bridgeland` anything"* — so it
  returns abstention exactly where a decision is needed.
- **A literature↔formal-library crosswalk** (judge 1: **3**, kill). I fetched the live
  `mathlib4/docs/references.bib`: ~400 entries heavily skewed to foundational monographs, so against a
  math.AG/NT notebook of order 10² research preprints the expected number of `cited_by_decl` edges is
  approximately zero. The declaration-dump leg is the already-killed in-server Mathlib corpus. **Only
  the `formal_env` stamp survives** (2.6) and it is hygiene, not a capability.
- **A second, corpus-internal novelty census** (judge 1: **3**, kill). Its motivating claim is false —
  the evidence-ledger standard governs planning-document absence claims, not mathematical novelty, and
  the mandated artifact exists with the retro pass complete. Two censuses is one too many; its
  mechanical query generation folds into 3.4.
- **MCP prompts shipping the discovery protocols** (judge 1: **2**, kill). Force-multiplier on three
  capabilities that do not exist; three of its four proposed prompts describe workflows over unbuilt
  tools; **#73** already grows `initialize.instructions` into the decision table that is their
  substance, so duplicating it creates two texts to keep consistent; and the interop justification
  targets a multi-client population D6-R09 and §5 item 19 already measured as **zero pre-PyPI**. The
  defensible fragment — register the primitive at all, hash-pinned, with **one** prompt and a
  with/without axis in the **#19** harness so "does the protocol help" is measured — is an hour of
  testing hygiene, and should not be filed until at least one Wave-2 capability has landed.
- **The forward contradiction screen** (a conclusion-polarity matcher selecting "candidate
  contradictions"). **R2's wont list draws the line explicitly**: *"No semantic entailment/cite-checking
  verdicts… judging support/conflict is the calling agent's job."* A polarity matcher that *selects*
  results as contradictions is a shallow entailment verdict on the wrong side of that line. Its
  dominant failure — a false-negative screen manufacturing confidence — is the most expensive error
  class here. R6-KR6/KR7 already own the forward direction. Only the reverse/generator facet survives,
  and it is the same object as `boundary-markers`' complement view, so it should not be filed twice.
- **`object_refs` launch namespaces for Stacks tags and bare DOIs/arXiv ids** — covered by **#43** and
  **D6-R05** respectively.
- **A corpus-wide term→definition index** — **#40**'s explicitly gated item (*"stays gated on observed
  filter usage rather than building blind"*), and the gating rationale still holds since nothing has
  yet observed `kind=definition` filter usage.

### 5.4 Deferred with a named unresolved risk, not killed

- **The git-pinned own-work lane** (ingesting the researcher's own result ledgers, `source_kind='local'`
  with a `result_status` axis read only from an explicit ledger field). Genuinely valuable — an agent
  asked about rank 107 currently cannot see that the owner already burned 67 CPU-hours establishing the
  u-side recursion is irreducible — and D2-R02/**#69** already anticipates the schema mechanism. It is
  **deferred here on two boundary risks that must be settled in writing first.** (i) The path allowlist
  must exclude anything transcript-shaped (`.claude/notes/`, session logs, run state); the line between
  a committed `HANDOFF.md` and a session transcript is thin enough that ingesting the wrong side turns
  the server into the per-run agent memory store constraint 5 forbids. (ii) **A prior-art citation
  loop**: `result_status` is an owner-authored, non-peer-reviewed trust token riding on served
  `search_papers` rows, and both census runners then query the corpus for prior art — so the owner's own
  unpublished claim can register as prior art against the owner's own new claim. Fix is one line: the
  census scope must name the local lane as a separate, separately-reported set, never folded into the
  corpus denominator. `redistributable=false` must be fail-closed.

---

## 6. Confidence and open questions

### Where this analysis is weakest

**1. Nothing here is measured against discovery, and that is the whole point of P2.** Thirty-one
proposals were ranked on argument by two judges whose theses disagree at the root — one holding that
the finding step (objects, compute, refutation) is what matters, the other that the corpus-mining and
hygiene side is what a solo maintainer can actually hold. Both are internally coherent and neither
produced evidence. Every score in §3 should be read as a prior, not a measurement.

**2. The screening process demonstrably failed at least once, in a way that inverted a top-4 bet.**
The ancillary-files lane was ruled INFEASIBLE on a measured census and its twin was ruled NOVEL in the
same round, then scored an 8 and ranked fourth. That was caught only because I re-ran the census. It is
reasonable to assume the same class of error survives elsewhere — most plausibly in items whose
density was asserted rather than measured. **The three items in this document that rest on unmeasured
density are `object-label-census` (my own stated prior is that it is thin), the in-math half of
`figure-lane` (asset-kind distribution unmeasured), and `technique-transfer-map`'s vacancy cell
count.** All three are gated on a measurement in Wave 0 for exactly this reason.

**3. Six lenses converged on one mechanism because the search space was narrow, not because the
mechanism is validated.** Nine of the thirty-one survivors are the identical construction — curated
regex lexicon over parsed prose, evidence span, confidence, abstention, precision sample — because
cross-synthesis §5 items 10–12 ban LLMs at ingest and item 16 discourages new tools, leaving
deterministic prose mining as nearly the only unclaimed move. That convergence looks like
triangulation and is not. If the do-not-do list's LLM-at-ingest ban is ever revisited on new evidence,
a large fraction of Theme 1 should be re-derived rather than ported.

**4. One lens's framing became the evaluation frame for all six.** The "loop stage" decomposition —
notice → locate → understand → construct → test → verify → record — originated in a single lens and
then organised both judges' theses and this document's §1. It is a good frame. It is also unexamined,
and it structurally under-weights anything that is not a stage: measurement, owner attention, and
modalities (diagrams, time, rate) were all scored at zero by construction until the completeness pass
recovered them.

**5. Corpus size is doing more work in these numbers than anyone acknowledged.** 262 boundary
assertions, 94 conjectures, 52 tables, 285 in-corpus citation targets, 323 captioned figures — every
one of those is a 173-paper number, and several proposals are thin *only* because the corpus is small.
Which of them scale linearly with ingest and which are structurally rare is unknown, and it changes the
ranking materially.

### The spikes that would settle it

| # | Spike | Settles | Cost |
|---|---|---|---|
| S1 | **Three-case discovery backtest** (P2 / 3.2), ingredient lists committed before the harness runs | The judges' root disagreement; whether the object/compute axis or the retrieval/mining axis is the actual bottleneck; re-decides every L and XL item | ~4 owner-days |
| S2 | **Figure asset-kind distribution** over ~30 sampled figures: inline SVG vs raster vs tikz-source vs absent | Whether `figure-lane` is a full modality lane or caption-and-reference indexing only — the difference between M and S | ~2 h |
| S3 | **Object-label density scan** on the live notebook per namespace, with a pre-committed threshold | Whether Theme 6 has any input at all in math.AG, and therefore whether the registry is worth registering | ~3 h |
| S4 | **Materialise the equations table** on one notebook (`ingest/index_equations.py` has apparently never been run) and measure Content-MathML→CAS convertibility | Whether `ascii-form` populates a column anything reads, and the honest `unconvertible` fraction | ~4 h |
| S5 | **Lexicon precision dry run**: author *one* lexicon (boundary markers) against `span-substrate` and hand-score 50 matches | Whether the entire Theme-1 bet clears a usable precision bar before five more lexicons are funded | ~1 day |
| S6 | **`abstractMVars` lift on 5 real skeletons** | Whether `obligation-decomposition` is L or impossible; the proposal's own stated cut criterion | ~1 day |
| S7 | **OEIS license determination**, recorded per constraint 7, resolving the CC BY-SA vs CC BY-NC-SA contradiction across two lenses; same for LMFDB *data* and GRDB terms | Whether any external object/sequence source may be served evidence or is candidate-layer only | ~2 h |
| S8 | **Corpus-closure curve**: recompute the statement-level internal resolution rate (today ~10%) after each ingest cycle | Whether a stopping rule exists for "the corpus is good enough for this problem", which six capabilities' ceilings depend on | free, once 5.1 exists |

### Questions this analysis cannot answer

- Does the owner want arXMCP to *hold* an object axis at all, or to remain a literature plane that
  hands labels and enumerator pointers to an external compute repo? §6.2 assumes the latter; that is a
  scope judgement, not a technical finding.
- Is the warm Mathlib-resident environment (R3-m5/m7) actually scheduled? Four Theme-2 items are
  scheduled fiction until it lands, and because it is "planned elsewhere" it received no scoring
  pressure from either judge.
- Is `evidence-engine-e4` (#14/#20/#24) going to run? Theme 5's cost estimate assumes its intra-paper
  extractor exists; if it does not, `statement-refs` roughly doubles.
- Should the do-not-do list's LLM-at-ingest ban be re-examined now that R2-m3 itself plans a local-llm
  extraction pass with Claude-gated acceptance sampling? Theme 1's purity is partly a self-imposed
  constraint the project has already relaxed for the adjacent case.
