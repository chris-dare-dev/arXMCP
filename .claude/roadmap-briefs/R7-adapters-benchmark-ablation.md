# R7 — adapters-benchmark-ablation

Phase 3 (benchmark strata start earlier, alongside the tracks they gate). Depends on: R2
(claim IR), R3 (attack-suite host), evidence-engine (harness + ledger). Gates: R6's
semantic metadata; future scale decisions.

## Brief (seed for /roadmap)

Two closing moves make the program honest and comparable. First, **versioned external
adapters**: the 2026 ecosystem ships hosted statement graphs and Lean services — TheoremGraph
(REST + MCP at api.theoremsearch.com; 68.1% combined edge precision across deterministic
98.8% / heuristic 76.6% / notation 42.7%; LLM-judged Lean alignments; CC-BY-NC-SA), Matlas
(8.07M statements, dependency unfolding, public API), LeanExplore/LeanSearch/Loogle, and the
S2/OpenAlex spine already planned in retrieval-unlocks. arXMCP composes with these rather
than rebuilding them — but never ingests their probabilistic edges as truth: every external
item enters a candidate layer preserving source system + version, extraction method,
confidence, exact candidate evidence, and a local acceptance state
(candidate / accepted / rejected / reviewed), with licensing posture enforced per adapter
(non-commercial data is queried live or cached per its terms, never redistributed, never
promoted into served evidence without a license check). TheoremGraph is also a *baseline
competitor* in evaluation, not just a source. Second, **the benchmark + ablation program**
that decides what was worth building: five suites with continue/kill gates — (1)
claim/citation resolution (explicit "Lemma 3.2 of [14]"; arXiv↔journal renumbering;
unnumbered and range citations; citations to proofs; similar-title collisions; corrected and
conflicting versions; unresolved negatives — precision, recall, calibration, abstention);
(2) context & alignment (dropped base-field/smoothness/genericity assumptions; the
ambient-vs-subcategory functor traps; notation shadowing; exact/specialization/one-way/
analogy relation labels; vacuous or inconsistent formalizations; intentionally truncated
statements — hypothesis-field accuracy and semantic-relation accuracy scored separately
from Lean compilation); (3) Lean verifier security (R3's attack suite as a permanent
regression population — required false-accept rate zero, forever); (4) computation
(independently known exact values; sign/convention traps; finite-search completeness traps;
theorem-scope mismatches; unsupported-input abstention; differential checks against an
independent implementation); (5) **downstream utility** — the only evidence that any of
this helps proof discovery: fixed-budget external agents run under controlled conditions
over five arms (retrieval baseline; + claim/context graph; + formal targets; + computation;
full bundles), measuring correct proof obligations identified, citations correctly used,
verified sublemmas, false theorem claims, token/cost/latency, and expert-rated progress,
on held-out material from ≥3 related subdomains with an expert set the builders never see.
Outputs adopt the Erdős-wiki 4-way provenance taxonomy (AI-standalone / AI+new-literature /
AI-on-known-literature / human-AI collaboration) plus verification-axis stamps, and the
whole program publishes an append-only correction ledger in the evidence-engine's
regression-ledger style. Agent *execution* for arm-testing runs outside the server (R0
boundary): the harness is a client, the server only serves.

## HMW / Objective

- **HMW:** How might we compose with the external math-data ecosystem without inheriting
  its noise or licenses, and measure — with kill criteria — whether each arXMCP layer
  actually improves research progress per token?
- **Objective:** Ship the adapter layer with candidate/acceptance discipline, the five
  benchmark suites, and the 5-arm ablation with published numbers and enforced gates.

## Key results

1. Adapter framework: per-adapter module with version pinning, license posture record,
   rate-limit budget, and the candidate-layer schema (source, method, confidence,
   evidence, local acceptance state); TheoremGraph + LeanExplore adapters land first;
   Matlas next; zero external candidate is ever served as arXMCP evidence without an
   explicit local acceptance record.
2. Suite 1 (claim resolution) runs against three systems: arXMCP R2, TheoremGraph
   adapter, and a naive-dense baseline — published side-by-side (the honest comparison
   the census claims require).
3. Suite 2 (context & alignment) includes the S_X/S_Ku functor trap, ≥5 dropped-assumption
   fixtures from real notebook papers, and ≥3 deliberately vacuous formalization fixtures;
   semantic-relation scoring is separate from compilation scoring by construction.
4. Suite 3 is R3's attack population, frozen and grown; any false accept is a P0.
5. Suite 4 fixtures include the CH-discriminant convention traps and the
   Enriques-abstention case from R4.
6. The 5-arm ablation: harness spec (fixed model, fixed budget per arm, ≥3 runs/task,
   spend ceiling per evidence-engine's pattern); task set of 8–12 research-grade tasks
   drawn from the notebook's domain (including the standing "audit the Enriques–Kuznetsov
   article" tasks: resolve its ~15 load-bearing citations; recompute its K_num steps;
   catch the seeded S²≅[4]-class error; state one theorem against R5 targets); held-out
   split + external expert grading; results in the regression ledger; **continue/kill
   applied**: an arm that shows no lift freezes its layer's expansion (R6 kill rule) and
   the verdict is recorded like the six frozen architecture decisions.
7. Provenance stamps on all harness outputs (4-way taxonomy + verification axes);
   correction ledger live from the first published number.

## Scope — out (wont)

- No redistribution of CC-BY-NC-SA or otherwise restricted external data; no silent
  caching beyond each service's terms; adapters degrade to abstention when offline.
- No agent orchestration inside the server; the ablation harness is a client program
  (per R0, plausibly in the orchestrator's new home repo).
- No leaderboard theater: suites 1–4 are regression instruments; only suite 5 makes
  utility claims, and only with expert grading.
- No benchmark publication before real numbers exist (trustworthy-release's rule,
  inherited).

## Assumptions (tiered)

- **must** — evidence-engine's harness + ledger land first (FIX, agent-task eval,
  spend ceilings). *Validation:* entry gate; if the agent-task harness stalls, suites 1–4
  still ship (they are server-side and cheap) and suite 5 waits.
- **must** — External expert grading capacity exists for suite 5 (the owner cannot grade
  arms they built). *Validation:* identify ≥1 external grader (or a strict blinding
  protocol) before the ablation is scheduled; otherwise suite 5 reports mechanical
  metrics only (verified sublemmas, citation correctness) and says so.
- **should** — TheoremGraph's API terms permit adapter + benchmark use. *Validation:*
  terms check + contact if ambiguous (page lists a UW contact); fallback: local HF-dump
  evaluation under its CC-BY-NC-SA for the comparison, no serving.
- **should** — 8–12 tasks suffice for a decision-grade ablation with 3 runs/arm inside
  budget. *Validation:* power check on pilot variance from the first 3 tasks; widen only
  if the ceiling allows.

## Evidence (verified 2026-07-11)

- TheoremGraph hosted API/MCP + precision table (theoremsearch.com/theorem-graph);
  Matlas public API (arXiv:2604.17484); LeanExplore MCP (arXiv:2506.11085).
- FormalQualBench's own audit discipline (Aristotle scores excluded as unaudited) — the
  model for honest side-by-side reporting.
- Erdős AI-contributions wiki taxonomy (github.com/teorth/erdosproblems/wiki) — adopted
  verbatim for provenance stamps.
- evidence-engine roadmap (regression ledger; agent-task eval; spend ceilings; the
  "recorded verdict" pattern for frozen decisions) — the harness and governance this
  track extends rather than duplicates.
- The adjudicated gap analysis §7.4: the ablation is the continue/kill authority for all
  semantic-metadata expansion.

## Milestone sketch

1. **m1 — adapter framework + TheoremGraph/LeanExplore adapters + license posture** (M).
2. **m2 — suites 1–2 fixtures + runners + side-by-side report** (L).
3. **m3 — suites 3–4 integration (adopt R3/R4 populations; freeze + grow)** (S).
4. **m4 — ablation harness spec + task curation (incl. the article-audit tasks)** (M,
   owner-in-loop).
5. **m5 — the 5-arm run + expert grading + published verdicts + correction ledger** (L,
   spend-capped).

## Gates

- **Entry:** R2 exit gate (suite 1 needs the system under test); R3 trust gate (suite 3);
  evidence-engine ledger live.
- **Exit / standing authority:** every layer of R4–R6 carries a recorded
  continue/kill/frozen verdict citing this track's numbers — the same governance the
  repo already applies to its six frozen retrieval decisions.
