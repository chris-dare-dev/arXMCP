---
project: arxmcp
type: handoff
status: complete
authorship: agent-generated
tags:
- project/arxmcp
- type/handoff
- authorship/agent-generated
---

# Handoff — proof-discovery data-plane program (2026-07-12)

**Read this top-to-bottom before touching anything in this thread.** It covers a
multi-session arc: a deep gap analysis, an adversarial adjudication of that analysis, an
eight-brief roadmap program derived from it, two roadmaps run through `/roadmap`, one
milestone run through `/milestone-pipeline` to completion, and two concurrent background
sessions that landed unrelated fixes on `main` while this was happening. Everything below
was re-verified against live repo state at handoff time (git log, journals, roadmap YAML,
lock file) — it is not a memory of intentions, it is what actually landed.

---

## 0. TL;DR for the next session

- **Where this came from:** the user asked for a deep gap analysis of arXMCP as a
  proof-discovery substrate for Bridgeland-stability / derived-category research, informed
  by Q2-2026 SOTA. I produced one, published as a Claude Artifact. The user then pasted an
  **independent GPT-5.6 critique** of that analysis and asked me to verify every claim and
  either defend or concede, then turn the corrected result into extensive, roadmap-ready
  prompts. I did — 8 briefs (`R0`–`R7`) plus an adjudication section in the artifact.
- **Then the user said "launch the roadmap"** and I ran the repo's own `/roadmap` pipeline
  (4-phase: Refine → Decompose → Sequence → Materialize) twice, producing
  `plans/data-plane-governance/roadmap.yaml` and `plans/source-truth/roadmap.yaml`.
- **Then "y"** → I ran `/milestone-pipeline data-plane-governance-m1` end-to-end (Research →
  Implement → Critique → Rectify), landing the repo's **first ADR**
  (`.claude/docs/adr-data-plane-boundary.md`, Accepted) and CLAUDE.md **§4.8**.
- **Current git state (verified just now):** local `main` == `origin/main` == `4b4976e`.
  Nothing to push. Two *other* sessions ran concurrently and independently: one fixed a
  Windows test bug I'd flagged (`0caf834`), another finished the pre-existing
  paper-metadata-m2 work that had been sitting uncommitted since before this session even
  started (`2b12ebc`, `4b4976e`, plus a LaTeXML Windows fix `2bba5c9`). **Neither of those
  sessions' work is this program's to re-litigate** — they're independent, already merged,
  already clean.
- **What's NOT done yet, in dependency order:**
  1. `data-plane-governance-spike-1` (owner sits with the six untracked plan dirs) → then
     `data-plane-governance-m2` (disposition them) and `data-plane-governance-m3` (trust
     language, lands as CLAUDE.md §4.9) — both only need `m1`, which is done, so both are
     startable now; `m2` additionally needs `spike-1`.
  2. `source-truth-spike-1` and `source-truth-spike-2` — no dependencies, startable now —
     then `source-truth-m1`.
  3. `R2`–`R7` (claim graph, verification contract, verified computation, formal-target
     registry, proof structure/bundles, adapters/benchmark/ablation) have briefs written
     but have **not** been through `/roadmap` yet — no `plans/<slug>/` exists for them.
- **The working tree is dirty again** (Obsidian-stamped docs, six *still*-untracked plan
  dirs, some agent-memory/scratch dirs) — this is now a **documented recurring pattern** on
  this box, not a surprise. See §5.

---

## 1. Why this program exists (user's original ask, verbatim intent)

The user runs arXMCP: a local-first, read-only MCP server exposing a research-math arXiv
corpus (math.AG/math.NT/math-ph/hep-th) to multi-agent Claude pipelines, with a long-term
goal of pairing it with **Bridgeland stability conditions / derived-category** research —
homological algebra and algebraic geometry proof discovery. The user's own website carries
an article, **`enriques-kuznetsov-stability`**, whose novel closing theorem ("the Kuznetsov
component of a generic unnodal Enriques surface admits no Serre-invariant Bridgeland
stability condition") has *not* been externally reviewed, and whose earlier draft shipped a
real error (conflating the ambient Serre functor S_X with the Kuznetsov-component Serre
functor S_Ku — caught only by a literature check against Li–Nuer–Stellari–Zhao). That
article is the running case study throughout this program: it is both motivation ("earlier
models struggled to prove new statements") and a ready-made benchmark ("audit this article"
is proposed as a standing eval).

The explicit ask had four parts:
1. A gap analysis of **what arXMCP itself should serve** (metadata, techniques, proofs) to
   let multi-agent workflows attack problems from many angles with maximal context — with
   an explicit steer that *semantic technique-tagging is probably the wrong answer* because
   it over-relies on semantics.
2. A **meta-gap analysis**: even the refined 2026 Lean-verification/agentic-proof standard
   has room for marginal, unshipped improvements — find them.
3. Grounded in **actual Q2-2026 novel research** on LLM/agentic proof assistance (not just
   Lean tooling in isolation).
4. A hard architectural constraint, stated explicitly: **arXMCP will never run the agents;
   it is only ever the server providing metadata, paper facts, references, and (maybe)
   Lean-verified information.**

## 2. What I actually did, phase by phase

### 2.1 — The gap analysis (first deliverable)

Deep-read the arXMCP codebase (all 8 MCP tools, schemas, the Lean REPL harness,
`server/`, `ingest/`, all seven `plans/*/roadmap.yaml` at the time), the sibling
`stability-mflds` exact-arithmetic package, the two live notebooks (`bridgeland-stability`
~200 papers, `fourier-duality` ~65), and the Enriques article's proof source. Fanned out
**five parallel research agents** (prover SOTA; Lean agent-infra; autoformalization +
Mathlib coverage; agentic-research-math + retrieval infra; Bridgeland-domain tooling) —
each independently web-verified, none reused training-data guesses.

Landmark findings from that sweep (all independently re-verified later, see §2.2):
- Competition-grade Lean proving is saturated (miniF2F ~99% pass@1); the wall is
  **research-level math** — RLMEval best 10.3%, FATE-X 33% for one system, ~26-point drop
  just from restating problems outside Mathlib's frame (TaoBench).
- **`mattrobball/BridgelandStability`** — a Mathlib maintainer's AI-written Lean 4
  formalization of Bridgeland's 2007 paper (through Thm 1.2 / Cor 1.3) shipped in April
  2026. This became the single most load-bearing external fact in the whole program.
- Statement-grain math retrieval (Matlas, TheoremGraph) went from novel to "table stakes"
  in the ~90 days before the analysis.
- Confirmed empty niches: hosted stability-condition computation (walls, Euler pairings,
  BG checks) as an API; semantic cite-checking with hypotheses for math; a
  typechecked+paper-aligned+version-pinned statement corpus served as a queryable API.

I published this as **Claude Artifact `arxmcp-gap-analysis.html`**
(URL: `https://claude.ai/code/artifact/2fce1969-cddc-4e5a-a656-592fd5026da6` — rev 1),
structured §0 exec summary → §1 capability map → §2 landscape → §3 tiered gaps (A:
statement-grain structure, B: verified computation, C: Lean data plane, D: multi-agent
enablement) → §4 meta-gaps (M1–M7) → §5 Enriques case study → §6 sequencing.

### 2.2 — The adversarial adjudication (rev 2)

The user pasted a long, sharp critique from a different model (GPT-5.6) attacking the
report's empirical spine and its reading of the codebase, and asked me to **verify every
claim, defend or concede each, then reorganize.** I did NOT rubber-stamp either side — I
re-fetched primary sources (BridgelandStability's actual `formalization.yaml`,
TheoremGraph's live site, FormalQualBench's actual score table, the MechMath/RLMEval
abstracts) and re-read the exact cited lines in **this** codebase.

**Verdict distribution:** ~11 claims fully conceded (critique was right), 4 partially
conceded, 4 defended (critique was wrong or unverifiable). The concessions that actually
changed the plan:
- **arXMCP has no claim graph** — the `\ref{}` intra-paper pass collapses every resolved
  reference into ONE paper→paper self-edge (`ingest/intra_paper_refs.py`); Kùzu has paper
  nodes only. `theorem_label` is the author's TeX `\label` key, **not** the printed
  "Lemma 3.2" — auto-generated IDs are nulled (`ingest/chunker.py:406-418`).
- **`lean_verify`'s trust surface is unsound**: `status: "ok"` ⇔ no error-severity messages
  AND no sorry goals (`server/handlers/lean_verify.py:290-298`) — a bare `axiom h : False`
  passes. `syntax_only` still elaborates via `#check`-wrapping; it is not syntax-only.
- **BridgelandStability's real shape**: §2–7 of Bridgeland's paper only — **§8 (the
  G̃L⁺(2,ℝ)/autoequivalence action) is explicitly excluded**, and that action is exactly
  what Serre-invariance arguments (the article's core move) consume. 1 comparator-stub
  sorry, 0 extra axioms, self-labeled "draft", author-only sampled review.
- **TheoremGraph IS hosted** (REST + MCP at `api.theoremsearch.com`) at **68.1% combined
  edge precision** (98.8% deterministic / 76.6% heuristic / 42.7% notation-derived) with
  single-LLM-judged Lean alignments — a probabilistic candidate graph, not resolved truth.
- **stability-mflds' Enriques support is record-only** — `varieties.py` explicitly sets
  `faithful_computation_supported=False`; a guard raises on every Surface-consuming entry
  point for torsion-canonical surfaces; real support needs a Néron–Severi lattice refactor
  tracked as **G12** in that sibling repo. (Counter-defended: the provider is *further
  along on trust* than the critique credited — it already has a `Rigor`/`Certificate`
  provenance lattice and, after its own "PROVEN on false verdicts" defect A4, an
  independent oracle with differential testing against a frozen corpus.)
- **The article's shipped error is a typed-identity transport error**, not a dropped
  hypothesis: S_X² = [4] is TRUE on D^b(X); the bug was silently transporting that identity
  to the *different* functor S_Ku on the *different* category Ku(X). A flat
  hypothesis-list mechanism would not have caught this — you need symbols bound to their
  ambient category/theory (a typed context graph), which reframed Gap A5 upward.
- **Replaced the whole "verification ladder" idea** (none → numeric → typechecked →
  kernel-proved) with a **multi-axis trust record** — typecheck ≠ fidelity is empirically
  proven by TheoremGraph's own statement-only experiment (22/24 typechecked, only 5/24
  semantically faithful to the source paper).

All corrections were applied **in place** in the artifact (rev 2, same URL) plus a new
**§7 adjudication section** with the full claim-by-claim table. This is the authoritative
version of the analysis — if anyone asks "what does the gap analysis say", read rev 2 /
§7, not rev 1's uncorrected claims.

### 2.3 — The eight roadmap briefs

Corrected §6 into **eight self-contained, paste-ready briefs** at
`.claude/roadmap-briefs/R0-R7*.md` (+ `README.md` with the dependency graph), each with:
a "Brief" block (verbatim seed for `/roadmap`), HMW/objective, measurable key results,
tiered assumptions with validation clauses, an explicit `wont` list, verified file:line
evidence, a milestone sketch, and gates.

| ID | One-liner | Phase | Roadmap status |
|---|---|---|---|
| **R0** | Boundary ADR, plan-tracking governance, trust-language + evidence-ledger policy | 0 | **`/roadmap`'d → `data-plane-governance`. m1 DONE.** |
| **R1** | Revision/span/checksum identity, truncation persistence, printed numbers, per-paper license provenance, corpus manifest | 0 | **`/roadmap`'d → `source-truth`. Not started.** |
| R2 | Claim IR v1: blocks/claims/citation-occurrences, evidence-carrying resolution w/ abstention, typed symbol/theory context | 1 | Brief only |
| R3 | Sound Lean surface: 5-op split (parse/elaborate/check/audit-axioms/strict-replay), target binding, OS isolation, attack suite | 0–1 | Brief only |
| R4 | stability-mflds as a separately-released provider; certified pilot ops w/ independent oracles; explicit Enriques abstention | 2 | Brief only |
| R5 | Pin+audit BridgelandStability; 5–10 reviewed conditional formal targets w/ multi-axis trust; the §8 action gap | 2 | Brief only |
| R6 | Evidence-backed proof DAGs, example lane, weak technique facets (dark until proven useful), budgeted progressive bundles | 3 | Brief only |
| R7 | Versioned external adapters (TheoremGraph/Matlas/LeanExplore), 5 benchmark suites, the 5-arm downstream ablation | 3 | Brief only |

**Dependency shape** (from the README): R0, R1 → {R2, R3} → {R4, R5} → {R6, R7}. R7's
ablation is the standing **continue/kill authority** over R6-style semantic metadata —
nothing in R6 may expand without measured lift.

**Standing policies every brief assumes** (from R0, now partially codified — see §3.1):
data-plane-only (server never runs agents, never holds per-run agent memory, takes writes
only via offline/operator-gated ingest); no bare `"verified"` — always a multi-axis trust
record; evidence-ledger phrasing for novelty claims (dated, scoped, query-listed, never
categorical); abstention (`unknown`/`ambiguous`/`unsupported`) is a first-class, tested
success state.

### 2.4 — `/roadmap` run twice (R0 → `data-plane-governance`, R1 → `source-truth`)

I loaded the repo's own `.claude/commands/roadmap.md` pipeline definition and ran it
**faithfully as the orchestrator** — not a shortcut, the actual 4-phase sub-agent pipeline
(`roadmap-refiner` → `roadmap-decomposer` → `roadmap-sequencer` → `roadmap-materializer`),
dispatching pairs of Refiner/Decomposer/Sequencer/Materializer agents in parallel across
the two tracks, verifying the validator (`roadmap-validate.py`) after every write, and
never hand-scoring MoSCoW/RICE (always via the deterministic scripts).

Both roadmaps landed at `status: active, phase: complete`:

**`plans/data-plane-governance/roadmap.yaml`** — 3 epics, 3 now-lane milestones, 1 spike,
8 tasks. RICE flagged `data-plane-governance-e2` at the c=0.5 no-evidence default (its
delivery hinges on the un-validated owner-sitting assumption).

**`plans/source-truth/roadmap.yaml`** — 4 epics, 5 milestones (m1 now; m2/m3/m5 next; m4
later), 4 spikes. RICE flagged e2/e3/e4 at c=0.5 default.

Both were committed in **`cfb7c27`** — `feat(roadmap): R0-R7 briefs + 2 phase-0 roadmaps`
— along with the eight brief files, before any milestone execution began.

### 2.5 — `/milestone-pipeline data-plane-governance-m1` run to completion

Full four-phase execution, faithfully per `.claude/commands/milestone-pipeline.md`:

- **Phase 0 (preflight/gate):** the working tree was ALREADY dirty at init from a *prior*
  session's uncommitted paper-metadata-m2 work (not this session's, not this milestone's).
  I documented this explicitly in
  `.claude/notes/milestones/data-plane-governance-m1/preflight-deviation.md` and proceeded
  with the deviation on record rather than either committing someone else's unfinished
  work or blocking indefinitely.
- **Phase 1 (Research, standard mode, 2 agents in parallel):** `explore` role mapped every
  codebase fact the ADR needed (who imports `model_selector.py`, every write surface, doc
  tests that pin CLAUDE.md content); `general` role built the decision analysis
  (orchestrator-loop placement options with pros/cons, ADR format, licensing wording,
  external-writes ledger). **Both independently found the same load-bearing correction**:
  the agent-platform plan's evidence claim "`model_selector.py` referenced only by tests"
  is **false** — `server/observability/spend_constants.py:51` imports it at runtime,
  transitively reached from server startup. I synthesized both briefs into
  `research/synthesis.md` and set the Phase-2 path decision: **inline** (est. ≤300 LOC, 2
  files, no novel architecture).
- **Owner checkpoint (AskUserQuestion, 4 questions, all answered "Recommended"):**
  1. Orchestrator-loop home → **separate repository** (not a `tools/` carve-out — research
     falsified "under tools/ = isolation": the server imports `tools.*` at runtime and
     `tools*` ships in the wheel).
  2. CLAUDE.md anchor → **new §4.8** (zero renumbering; CLAUDE.md has no existing "Hard
     constraints" section — that name is used, for *different* lists, in README.md and
     `.claude/notes/README.md`).
  3. The pre-existing paper-metadata-m2 hunk in CLAUDE.md → **leave uncommitted**
     (hunk-scoped staging around it, not swept in).
  4. ADR approval mode → **"approve on decisions"** (your four answers here ARE the
     recorded owner approval; ADR lands `Status: Accepted` directly, not `Proposed`).
- **Phase 2 (Implement, inline):** wrote `.claude/docs/adr-data-plane-boundary.md` (172
  lines, the repo's first ADR — 5 Decisions + an explicit Owner-approval-record section)
  and CLAUDE.md §4.8 (32 added lines). **Hunk-scoped git staging**: split the CLAUDE.md
  diff by hunk in Python, staged ONLY the §4.8 hunk via `git apply --cached`, leaving the
  pre-existing §7 hunk untouched and uncommitted. Committed as `90a1049`
  (`feat(repo): data-plane boundary ADR + CLAUDE.md 4.8`).
  - **Test-gate attribution work** (this is the origin of the now-standing baseline
    discipline, §5): full suite showed 68 failures. I did NOT accept "68 failures" at
    face value — I spun up a throwaway worktree at the pre-milestone commit (`cfb7c27`),
    ran the same failing files there, and mechanically + empirically attributed **zero**
    of the 68 to this milestone's 2-file docs-only diff (grep showed no failing test even
    references the two touched files outside comments/docstrings; the
    `test_model_selector` failures reproduced identically at the pre-milestone baseline).
    Recorded in `implement/synthesis.md`.
- **Phase 3 (Critique, 2 agents in parallel — always-on adversary + the `arxmcp` overlay
  critic, which fires on every diff):** adversary found **C0 H0 M3 L5**; overlay found
  **C0 H0 M2 L4**. Fan-in: merged, id-remapped to avoid collisions, deduped (1 cross-critic
  agreement cluster covering 3 findings), extracted into the findings register — **14
  total, C0 H0 M5 L9**. All ADR file:line factual claims were independently re-verified
  true by both critics.
- **Phase 4 (Rectify, delegated to `milestone-rectifier`** — triggered because
  implementation ran inline in the main session, per the pipeline's trigger-3 rule): fixed
  all 5 MEDIUMs (each 1–3 lines: a scope clause, a misattributed quote, a stale mandate
  string, a stale tool count, a qualifying clause) plus 3 LOWs bundled into the same
  editing sessions under the "trivially-cheap-and-adjacent" exception; deferred 6 LOWs with
  individual reasons (mostly "belongs in a later docs-sync, not a rect"). **0% invalidation
  rate** — every anchor the critics cited matched live text exactly. Committed as
  `910e939` (`rect(data-plane-governance-m1): close M1-M5, L1-L3`, GPG-signed, both
  `Reviewed-by:` trailers). Findings gate: OK, no open findings.
  - **External-write boundary respected**: `git push origin main` was the single required
    external write. I stopped and asked. User said "y". **Concurrency rule paid off
    immediately**: by the time of the re-fetch, another session had already committed
    `0caf834` (the Windows F2 fix I'd flagged, see below) on top of my rect commit *and
    pushed it*. Ancestry check confirmed my 3 commits were already on `origin/main`, so the
    authorized push executed as a truthful no-op. Ledger balanced, `complete` transition,
    lock released, outcome telemetry logged.
  - **Closing `chore(notes)` commit** (`6e0ef1a`): the full pipeline-artifact tree (research
    briefs, both critiques + dedup, findings.json, rectify disposition + summary,
    preflight-deviation record, gate log, staging patch) — deliberately excluding
    `staging-all.patch` (a full-file snapshot of the *other* session's uncommitted hunk,
    not mine to commit).
- **Two follow-up chips spawned** (via `spawn_task`) for out-of-scope-but-real issues found
  during gate attribution: (a) the Windows `str(rel)` vs posix-literal path bug in
  `test_model_selector.py`'s F2 guard — **picked up and fixed by the user in a separate
  session**, commit `0caf834`; (b) dispositioning the uncommitted paper-metadata-m2 work —
  **picked up and finished by the user in a separate session**, commits `2b12ebc` /
  `2bba5c9` / `4b4976e`.

## 3. Exact current repo state (re-verified at handoff time, 2026-07-12)

### 3.1 — git

```
main == origin/main == 4b4976e   (nothing to push, nothing to pull)

4b4976e chore(notes): finalize paper-metadata m1+m2 state          <- OTHER SESSION
a6d6329 chore(skill): deep-tier synthesizer for capability-scout    <- OTHER SESSION
a7d47ad docs(ops): stamp authorship frontmatter on runbooks         <- OTHER SESSION
2bba5c9 fix(tools): invoke latexmlc via perl.exe on Windows         <- OTHER SESSION
2b12ebc feat(server): get_paper hydrated metadata (paper-metadata-m2)  <- OTHER SESSION
6e0ef1a chore(notes): finalize data-plane-governance-m1 -> complete <- THIS PROGRAM
0caf834 chore(tests): fix F2 guard rel-path match on Windows        <- spawned chip, other session
910e939 rect(data-plane-governance-m1): close M1-M5, L1-L3          <- THIS PROGRAM
90a1049 feat(repo): data-plane boundary ADR + CLAUDE.md 4.8         <- THIS PROGRAM
cfb7c27 feat(roadmap): R0-R7 briefs + 2 phase-0 roadmaps            <- THIS PROGRAM
```

`get_paper` now serves real hydrated title/authors/abstract/year/categories
(`metadata_status="hydrated"`, wrapped in `<retrieved_chunk>` delimiters) — CLAUDE.md §7 is
already updated to say so (verified live at line 456: "serves real
authors/title/abstract/year/categories"). The old "still returns NULL" wording is gone.

### 3.2 — Milestone/roadmap execution state

| Roadmap item | Effective status | Evidence |
|---|---|---|
| `data-plane-governance-m1` | **done** | `plans/data-plane-governance/progress/agent.jsonl` — journal has `in_progress` then `done` (note: `rect 910e939`) |
| `data-plane-governance-spike-1` | not started | no journal entry, no `.claude/notes/milestones/data-plane-governance-spike-1/` dir |
| `data-plane-governance-m2` | not started | same |
| `data-plane-governance-m3` | not started | same |
| `source-truth-*` (all 9 items) | not started | `plans/source-truth/progress/agent.jsonl` does not exist / is empty; no milestone dirs |

No lock file at `.claude/notes/milestones/.lock` — no pipeline is mid-flight. Confirmed via
`bash .claude/scripts/milestone-pipeline-status.sh <id>` pattern / direct file check.

**Reminder on how to read `plans/<slug>/roadmap.yaml` item status**: the YAML's own
`status:` field on each item (e.g. `planned`) is **never** updated by the milestone
pipeline — that's the one-writer rule. The *effective* status the dependency gate actually
checks is the roadmap's `status` **overlaid by the latest journal event**. So
`data-plane-governance-m1`'s roadmap.yaml still says `status: planned` — that is correct
and expected; its true status is `done`, readable only from the journal or by running the
gate script.

### 3.3 — Working tree dirt (as of handoff)

```
 M README.md, docs/README.md, docs/api.md, docs/architecture.md, docs/evaluation.md,
   docs/install.md, docs/observability/README.md, docs/ops/README.md, docs/releasing.md,
   docs/support.md, docs/usage.md                     <- Obsidian vault frontmatter stamper
 M .claude/roadmap/corpus-integrity-completion-roadmap.md (+8 more plans/*.md)  <- same stamper
 M tests/conftest.py                                   <- from another session, uninspected

?? .agents/  .codex/  AGENTS.md                        <- Codex mirror scaffolding
?? .claude/agent-memory/milestone-{adversary-critic,implementer,rectifier,researcher}/*
?? .claude/launch.json                                 <- local dev-server launch config
?? .claude/notes/milestones/data-plane-governance-m1/staging-all.patch  <- my own scratch
?? .claude/notes/notebooks/                            <- ?? unexplored, check before touching
?? plans/agent-platform/  plans/evidence-engine/  plans/researcher-workbench/
?? plans/retrieval-unlocks/  plans/scale-ops-hardening/  plans/trustworthy-release/
   <- THE SIX UNTRACKED PLANS — this is EXACTLY what data-plane-governance-m2 exists to
      disposition. They are STILL untracked. Do not commit them speculatively; do not
      delete them; m2's whole job is deciding each one's fate.
?? var/                                                 <- gitignored data tree, expected
```

**Do not "clean up" this dirt reflexively.** Per the now-documented pattern (§5), sessions
in this repo habitually leave real uncommitted work sitting for days-to-weeks, and
concurrent sessions land commits mid-session. Before any commit: `git status`, diff-inspect
anything you didn't personally just write, and commit with **explicit pathspecs**
(`git commit -F - -- <paths>`), never `git add -A` / `git add .`.

## 4. What's next — concrete, ready-to-invoke options

In rough priority (all are independently startable except where noted):

1. **`data-plane-governance-spike-1`** then **`-m2`** — the owner disposition of the six
   untracked plan directories (`agent-platform`, `evidence-engine`, `researcher-workbench`,
   `retrieval-unlocks`, `scale-ops-hardening`, `trustworthy-release`). This is genuinely
   owner-gated: each needs a decision (commit as-is / revise-then-commit / veto-and-archive).
   `spike-1` *is* that sitting; `m2` executes the git-state consequences. Small, fast,
   mostly you deciding rather than me building.
2. **`data-plane-governance-m3`** — trust-language + abstention + evidence-ledger policy
   docs, lands as CLAUDE.md **§4.9**. Only depends on `m1` (done) — startable immediately,
   independent of `m2`. This is the policy the whole R2–R7 program's "no bare verified"
   discipline formally rests on; doing it soon derisks everything downstream.
3. **`source-truth-spike-1`** (license-URI coverage on a 30-paper mixed-ID sample via
   `tools/_arxiv_api.py`) and **`source-truth-spike-2`** (printed-number extraction
   coverage on 20 Bridgeland papers) — both zero-dependency, both gate `source-truth-m1`.
   These are exactly the kind of cheap, fast, evidence-generating spikes that should run
   before committing to the bigger `source-truth-m2` schema migration.
4. **Run `/roadmap` for R2–R7** — none of the other six briefs have been turned into
   `plans/<slug>/roadmap.yaml` yet. They're fully written (see
   `.claude/roadmap-briefs/R2..R7-*.md`) and ready to seed the pipeline exactly like R0/R1
   were. Natural order per the dependency graph: R3 (verification contract) is arguably
   most urgent since it's the trust foundation for R4/R5 and touches the one component
   (`lean_verify`) with a confirmed live soundness gap.
5. **Re-verify the paper-ingest task and notebook state** — a background chip from an
   earlier point in this arc was ingesting the Feb–Jul 2026 Bridgeland/Enriques papers
   (Pertusi's survey, Kuznetsov–Liu–Perry, Liu's Bridgeland–Enriques-K3 paper) into the
   `bridgeland-stability` notebook. Confirm it landed before relying on notebook contents
   for anything downstream — check `var/arxmcp/notebooks/bridgeland-stability/papers.txt`
   for the new arXiv IDs.

**None of these should be started without the user's go-ahead** — per this repo's own
`/milestone-pipeline` contract, never auto-start the next milestone; per this session's own
established pattern, ask before dispatching agents.

## 5. Standing lessons now codified for this repo (read before running ANY pipeline here)

Two memory files exist specifically for continuity across sessions in this repo — **read
them before starting new work**:

- **`arxmcp-gap-analysis-2026q2.md`** (memory) — the adjudicated gap-analysis facts, the R0–
  R7 program shape, and the verified corrections (BridgelandStability's real scope, the
  TheoremGraph precision numbers, `lean_verify`'s unsoundness, Enriques needing G12). This
  is the "why" behind the whole roadmap program.
- **`arxmcp-windows-test-baseline.md`** (memory, written by whichever session ran after
  this one) — codifies that this Windows box carries **~55 accepted platform failures**
  (symlink privilege errors, colon-in-filename, POSIX-literal asserts, kuzu file-lock
  teardown, cp1252 decode, stale fixture state) that are NOT regressions and should never
  be chased to zero. **Gate discipline going forward: attribute by failure-SET comparison
  against the prior session's recorded baseline** (exactly the throwaway-worktree technique
  used for `data-plane-governance-m1` above), never by expecting a clean `pytest` run.
  Also notes: pytest's final summary line gets eaten by a teardown crash on this box — count
  `FAILED` lines or read `.pytest_cache/v/cache/lastfailed` instead of trusting the tail.
  And: **concurrent sessions land commits on `main` mid-work here** — this is now expected
  behavior, not an anomaly to investigate. Always re-fetch + re-verify ancestry before any
  push, exactly as the milestone-pipeline's own concurrency rules already mandate.

**Two model attributions exist in git history for the "authoring model" trailer** —
`Claude Opus 4.7 (1M context)` (old CLAUDE.md-mandated string, now stale) and
`Claude Fable 5` (what this session and the two concurrent ones actually used). CLAUDE.md
§4.3 was corrected during the m1 rectify pass to say "the actual authoring model" instead
of hardcoding one — use whichever model is actually running the session.

## 6. Key file map (for fast orientation)

```
.claude/roadmap-briefs/                      the 8 R0-R7 briefs + README (dependency graph)
plans/data-plane-governance/roadmap.yaml     R0's roadmap — m1 DONE, spike-1/m2/m3 next
plans/source-truth/roadmap.yaml              R1's roadmap — nothing started yet
.claude/docs/adr-data-plane-boundary.md      the repo's first ADR (Accepted) — READ THIS
                                              before doing anything that touches the
                                              orchestrator/agent-loop boundary question
CLAUDE.md §4.8                               binding short form of the ADR
.claude/notes/milestones/data-plane-governance-m1/
  ├── preflight-deviation.md                 why the tree was pre-dirty at m1 init
  ├── research/{brief-1,brief-2,synthesis}.md   the verified codebase facts (esp. the
                                              spend_constants.py:51 correction)
  ├── implement/synthesis.md                 the 68-failure gate-attribution work
  ├── critique/{adversary,arxmcp,dedup}.md   C0 H0 M5 L9, 0% invalidation
  ├── findings.json                          the register (8 fixed, 6 deferred)
  ├── rectify/{disposition,summary}.md       what got fixed and why, verbatim
  └── state.json                             phase: complete, full external-write ledger
```

The published gap-analysis artifact (rev 2, with §7 adjudication) remains the canonical
strategic document:
`https://claude.ai/code/artifact/2fce1969-cddc-4e5a-a656-592fd5026da6`

---

**End of handoff.** A fresh session picking this up should: (1) re-run `git status` /
`git log` to catch anything that happened between this handoff and pickup (this repo has a
demonstrated pattern of concurrent sessions), (2) read both memory files in §5, (3) ask the
user which of §4's options to run next rather than assuming.
