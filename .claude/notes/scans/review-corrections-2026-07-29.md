<!-- scan provenance: generated 2026-07-25..29; moved here 2026-07-29 -->

> [!info] Reviewer's own thesis and its corrections — arXMCP scan, 2026-07-29
> **Method.** Written BEFORE the agent output landed, so the synthesis would be a judgement rather than a relay, then corrected twice against primary sources.
> **Status.** **Provenance record.** Retains two corrections of my own claims: (1) the recent counterexamples came from cross-subfield literature synthesis, NOT search over objects -- Batyrev was an existing Kiem-Li closed form -- which demoted the CAS-bridge proposal; (2) the `formal-conjectures` 'novelty' claim was RETRACTED after finding R5's 2026-07-11 census. Kept because the reasoning that produced a wrong answer is worth as much as the answer.
> **Origin.** Produced in a single principal-engineer review session; the board state it
> cites was read live from the GitHub API. Numbers are dated -- re-verify before acting on
> any of them.

# My own read, written BEFORE seeing the agents' output

Recorded so the synthesis is a judgement, not a relay. Everything here is from my own
reading of `ingest/schema.py`, `server/tools.py`'s surface as documented in README/api,
`ingest/kuzudb_schema.py`, and the 232 roadmap items.

## The one-sentence gap

arXMCP is a high-fidelity mathematical **reading** surface. `CHUNKS_SCHEMA_V1` contains
not one field that models a mathematical *object* or a *claim as an entity*.
`theorem_name` / `theorem_label` / `printed_number` are **typographic** facts about how a
theorem was *printed* — not semantic facts about what it *says*. The citation graph is
paper→paper. So the corpus is a bag of provenance-carrying text with edges between
documents.

## Why that matters for the motivating examples

**FIRST DRAFT (wrong — recorded so the correction is visible).** I assumed the recent
machine-found counterexamples came from *systematic search over concrete objects*:
a computable predicate + a generator of candidates + a cheap falsification oracle +
scale. On that model arXMCP's gap would be "it cannot compute", and the fix would be a
CAS / structured-database bridge.

**CORRECTED, after reading the actual sources (2026-07-25).** That model does not match
either flagship result.

- **Batyrev, stringy Hodge numbers** (Satriano–Usatine, arXiv:2607.19184, 2026-07-21,
  ChatGPT-assisted). The counterexample is `X = M₀ × ℙ¹` where `M₀` is the coarse moduli
  space of rank-2 semistable bundles with trivial determinant over a genus-3 curve —
  7-dimensional, Gorenstein terminal, with `h²,⁵_st(X) = −1`. The proof is **standard
  algebra applied to an existing closed-form formula** — Kiem–Li 2004, Thm 6.1, for
  `E_st(M₀; u,v)`. **No enumeration. No computer algebra. No polytope database.** The
  hard step was knowing that a 2004 result about moduli of bundles resolves a question in
  motivic integration / mirror symmetry.
- **Jacobian conjecture** (Alpoge, 2026-07-20, Fable 5-assisted; Tao's digestion
  2026-07-21). A degree-7 `C³` example with a three-point collision. Tao states plainly
  that such a polynomial "looks highly unlikely to be located by brute force."

So the empirical lever is **not** search-over-objects. It is **cross-subfield synthesis**:
connecting an available formula/technique in one literature to an open question in
another. **That is precisely what arXMCP exists to serve** — which validates the
project's core bet much more strongly than my first draft credited.

Kevin Buzzard's account of the general pattern (Xena, 2026-07-20) agrees and adds the
workflow: humans pick **existential** conjectures (a counterexample is cheap where a
proof is not) → the model proposes a candidate in natural language → **Lean formalizes
and verifies** → a human checks the formal statement matches the intended mathematics.
He names the enabling infrastructure: frontier-model access, autoformalization tooling,
and **DeepMind's `formal-conjectures` repository, which pre-formalizes conjecture
statements**.

## What this changes

1. **My lever B (CAS / database bridge) is demoted.** Neither result came from
   enumeration. A compute surface is still worth having — it falsifies a *proposed*
   candidate cheaply — but it is a second-order lever, not the missing primary one. If
   the agents' computational-mathematics lens comes back weighting this highest, that is
   an over-reading of the evidence and I should say so.
2. **Lever A (conjecture as a first-class entity) is strongly confirmed**, and there is
   an existing open corpus to stand on — `formal-conjectures` — rather than build from
   nothing. Status, known cases, and the *existential vs universal* character of a
   conjecture are exactly the fields that would let an agent pick targets the way these
   humans did.
3. **The sharpest retrieval gap is now nameable.** The Batyrev query is, in substance:
   *"for which families is this invariant known in closed form?"* That is
   retrieval-by-**available-result-shape**, not retrieval-by-prose-similarity. arXMCP's
   dense BGE-M3 search over statement text cannot express it, and no planned roadmap item
   does either. This is the residue I most expect the lenses to miss.

## Verified: the `formal-conjectures` join (my strongest single finding)

All checked live 2026-07-25 against the GitHub API, not asserted from memory:

- `google-deepmind/formal-conjectures` — **Apache-2.0**, **6.5 MB**, 1143 stars, 974 `.lean`
  files, last pushed **2026-07-25** (actively maintained, today).
- It has a top-level **`FormalConjectures/Arxiv/`** tree whose subdirectories are named
  **by arXiv ID**: `0911.2077`, `1308.0994`, `2501.03234`, `math.0110202`, …
- Inside, the Lean namespace is literally the arXiv id — `namespace Arxiv.«2501.03234»` —
  and the header carries the arXiv URL, title and authors.
- Statements are decorated: `@[category research open, AMS 11]` — i.e. each carries a
  **status** (`research open` vs `test` etc.) and an **AMS subject class**.
- Each formal statement sits directly under a docstring containing the **informal LaTeX
  statement** — a paired informal↔formal record.

So the three pieces join with **no new infrastructure**: arXMCP already keys its corpus on
`paper_id`; `formal-conjectures` keys conjectures on the same arXiv ids; and arXMCP
already runs a Lean 4 kernel with mathlib built (`lean_verify`). That yields, nearly for
free: conjecture-as-entity **with status**, subject-area slicing via AMS class, a
paper→conjecture link into the existing corpus, ground-truth informal↔formal pairs for the
definitional-alignment problem, and a *target* for `lean_verify` rather than only a
snippet.

**NOVELTY CLAIM — RETRACTED (2026-07-25).** I checked the 200 issues and the 9
`plans/*/roadmap.yaml` and found zero hits, and concluded this was novel. **That check was
incomplete and the conclusion was wrong.** There is a *second* planning layer I did not
know existed: `.claude/roadmap-briefs/R0–R7`. `R5-formal-target-registry.md` records a
prior-art census dated **2026-07-11** whose scope is, verbatim: "AXLE, **formal-conjectures**,
SorryDB, Herald, TheoremGraph, LeanArchitect, Matlas". And the capability analysis
correctly routes it: "External conjecture sets (`formal-conjectures`, `erdosproblems`) are
**R7-KR1's** adapter layer."

So the *idea* is already owned. The lens agents inventoried the brief set; I did not — the
screener even names this exact failure mode for one of its own lenses ("inventoried only the
six materialised roadmaps and missed the brief set those were materialised from"). I made
the same mistake.

**What survives** is narrower and still worth having: the measured specifics above
(Apache-2.0, 6.5 MB, 974 files, `Arxiv/` tree keyed by arXiv id, `@[category research open,
AMS 11]` status + AMS decorations, paired informal↔formal docstrings, actively maintained
as of today) are fresh evidence that **sharpens R7-KR1's adapter scoping** — in particular
the arXiv-id join key and the status attribute, which are what make it cheap. That is a
scoping contribution to an existing item, not a new capability.

**Method lesson for the PM work:** any novelty check on this project must cover *three*
layers — issues, `plans/*/roadmap.yaml`, **and** `.claude/roadmap-briefs/R0–R7` — plus the
2026-07 do-not-do list. Two of the three are invisible on the GitHub board, which is itself
a finding.

**Adjacent prior ruling I must respect:** the plan has already *rejected* native Mathlib
ingestion in favour of composing with **LeanExplore's local MCP server**
(`plans/trustworthy-release/roadmap.yaml:44-55`, `plans/retrieval-unlocks/roadmap.yaml:44`;
D2-R08 killed), pending `verification-feedback-spike-3` — "already scoped, never executed".
So mathlib *declaration search / premise selection* is a settled compose-don't-build
decision and must not be re-proposed. `formal-conjectures` is the opposite case: 6.5 MB
rather than 1.5M LOC, so ingesting it is cheap and does not reopen that ruling.

## The three things I expect to matter most

**A. A conjecture / claim as a first-class entity.** Status (open / proven / disproven /
withdrawn / independent), known cases, known counterexamples, sharpness, and the papers
that moved it. Nothing in the schema or the graph models this. Without it an agent
cannot ask the first question a mathematician asks: *where is the frontier of this
problem?*

**B. A falsification / computation surface.** A sandboxed, pinned, replayable bridge to
computer algebra and structured mathematical databases, sitting beside `lean_verify` as
a second *compute* tool under the same multi-axis trust discipline. This is what turns
reading into searching. Note the Kreuzer–Skarke reflexive-polytope database is literally
the object family behind the Batyrev-type result. (Size/licence must be checked, not
assumed — the 4D list is very large; a targeted slice is the only local-first option.)

**C. Negative-result / dead-branch memory.** A corpus-visible, operator-gated ledger of
what was attempted and why it failed. It is the cheapest and most systematically
discarded artifact of any proof search, and the data-plane ADR permits it *if* it enters
through the operator-gated write path and is served read-only.

## The prerequisite under A and C

**Canonical statement identity** — the ability to assert that four differently-printed
theorems are *the same claim*. Without it, a conjecture index, a statement-granularity
dependency graph, and a dead-branch ledger all degenerate into string matching. I expect
this to be the "unnamed prerequisite" the completeness critic was asked to find. If the
agents do not surface it, that is a miss.

## A cheap one I expect to be under-rated

**Hypothesis-usage tracking.** Counterexample hunting *is* the search for where a
hypothesis is load-bearing. `retrieval-unlocks-m1` gives stmt↔proof linkage; the residue
beyond it is "which hypothesis of this statement does this proof step actually consume,
and what is known if you drop it".

## Checks I will run against the agents' output

- Did anyone name canonical statement identity as a prerequisite rather than a feature?
- Did the compute-surface proposal respect the read-only data-plane ADR *explicitly*,
  or does it smuggle a write path / an agent loop into `server/`?
- Are external datasets named with a **checked** licence and size, or gestured at?
- Did anyone re-propose something already in the 200 issues? (Screener should have caught
  it; I spot-check.)
- Is the Lean lens distinct from what `plans/lean-verify-continuation` + the existing
  roadmaps already cover, or is it restating them?
