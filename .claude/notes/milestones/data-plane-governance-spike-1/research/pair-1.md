---
milestone_id: "data-plane-governance-spike-1"
pair: "pair-1"
tracks: ["agent-platform", "evidence-engine"]
injection_attempts: 0
generated_by: { agent: claude-sonnet-5, role: disposition-research-analyst }
---

# Disposition brief — pair-1: agent-platform, evidence-engine

Grounding read: `CLAUDE.md` §4.8/§4.9, `.claude/docs/adr-data-plane-boundary.md`,
`.claude/docs/trust-language-policy.md`, `.claude/roadmap-briefs/README.md`. Both plan
dirs contain only `roadmap.yaml` + an empty `progress/.gitkeep` (no other files, no
progress recorded — genuinely untracked/unstarted). No prompt-injection attempts found in
any file read; all plan/doc content was treated as data. `injection_attempts: 0`.

---

## agent-platform

### 1. What it scopes

A truthful, budget-sane, spec-current MCP tool/resource/protocol surface: env-configurable
session caps sized for interactive use (today's lifetime ceiling is 3 search / 4 get_chunk
calls), a batched `TOOL_SCHEMA_VERSION` re-pin fixing false tool descriptions and adding
batch chunk fetch + semantic identifiers (W1), resource registration + a corpus-manifest
resource for discovery without spending capped calls, a review-only MCP 2026-07-28
migration coupling inventory, and — the item this section exists to scrutinize — "the
minimal orchestrator dispatch loop that makes real agent traffic exist at all" (brief,
`plans/agent-platform/roadmap.yaml:8`). Six epics (e1–e6), 8 milestones, 10 tasks, phase
`complete` (i.e., fully sequenced, ready to execute).

### 2. Boundary/trust alignment

**(a) Agent dispatch / agent loop / per-run agent memory scoped inside this repo — YES, CONFIRMED CONFLICT.** See §SPECIAL below for the full verbatim analysis. Summary: 6 items, all tagged `cg1` (`agent-platform-e5:125`, `agent-platform-spike-1:408`, `agent-platform-m8:422`, `agent-platform-t-dispatch-loop:440`, `agent-platform-t-transcript-recording:455`, `agent-platform-t-canned-task-run:470`), scope building the dispatch loop's actual code as work product of **this roadmap, in this repo** — never naming a separate repository. The ADR (`adr-data-plane-boundary.md:22-26`) names this exact file as the motivating case for Decision 2/3 and already schedules the fix as `data-plane-governance-t-agent-platform-amend` (`plans/data-plane-governance/roadmap.yaml:180-191`), whose acceptance criterion is verbatim: *"no item in it scopes a server-side dispatch loop or per-run agent memory inside this repo and the plan matches the recorded choice"* (`:189`).

**(b) Non-operator-gated write path — NONE FOUND; one item is a POSITIVE exemplar.** `agent-platform-e6` (`:129-139`) explicitly defers any in-server memory build ("deferring any in-server notes build unless corpus-integrated retrieval proves necessary") and routes its one write path — an orchestrator-side CLI proposing corpus-growth candidates — into *"a persistent per-notebook pending queue behind operator confirm in /ui/"* (`:132`). The ADR cites this shape by name as compliant: *"the agent-platform plan's 'pending queue behind operator confirm in /ui/' shape is the compliant pattern"* (`adr-data-plane-boundary.md:76-77`). No other write surface appears in this track (W1/e2 is read-path schema truthfulness; e3 registers read-only resource templates).

**(c) Bare "verified"/single-trust-enum tool surface — NOT APPLICABLE.** This track never touches `lean_verify` or any trust/status field; it is scoped to tool descriptions, budgets, resources, and protocol. §4.9 is R3's/R5's surface to implement, not this track's.

**(d) Categorical novelty claims — NONE FOUND**, but one **stale factual claim** feeds this track's own must-tier assumption and should be corrected in the same revision pass: evidence bullet `agent-platform-roadmap.yaml:63` states *"server/orchestrator/model_selector.py -- model-selection policy shipped in E08_S05 but referenced only by tests; no runtime dispatch loop exists on either tree."* The ADR explicitly falsifies the "referenced only by tests" clause: `model_selector.py` "is transitively imported at server startup via `server/observability/spend_constants.py:51` → `server/observability/__init__.py:30` → `server/main.py`, solely for the `MODEL_HAIKU_4_5` metric-label constant" (`adr-data-plane-boundary.md:39-43`). This is not a §4.9 novelty-claim violation (it's an internal file:line-cited fact, correctly shaped per §4.9(3) — it's just wrong), but it should not survive uncorrected into a committed plan, since the ADR that supersedes it is now the repo's constitution on this exact point. The "no runtime dispatch loop exists on either tree" half of the same sentence is **not** contradicted by the ADR and remains accurate.

### 3. R0–R7 relationship

**Directly interlocked with R0 (data-plane-governance) on exactly the orchestrator-loop-placement question** — the roadmap-briefs README says so explicitly: *"R0's boundary ADR resolves its orchestrator-loop placement"* (`.claude/roadmap-briefs/README.md:51`). That resolution is now Accepted (this ADR), so agent-platform is the **consuming** track, not a peer proposal — R0 has already decided the question this plan left open. Everything else in agent-platform (W1 truthful/batched tool schema, budget-cap relief, resource/manifest discovery, MCP-migration coupling inventory) is **complementary** to R0–R7, not overlapping: the README explicitly plans for "new tool registrations" from R1–R7 to "batch into the W1 tool-schema re-pin window" this track owns (`README.md:51`), i.e., R1–R7 depend on agent-platform's W1 machinery existing, they don't duplicate it. No other R-track scopes an orchestrator loop, budget caps, or tool-schema truthfulness, so there is no supersession beyond the loop-placement point.

### 4. Recommended disposition: **revise-then-commit**

**Rationale.** Five of six epics (e1–e4, e6) are sound, ADR-compliant, and complementary to R0–R7 — they should become a tracked active plan largely as written. The sixth (e5, "the minimal orchestrator dispatch loop") and its five descendant items are a confirmed, ADR-documented conflict with Decision 2/3, not a hypothetical one: the ADR names this file by path and quotes its own language as "boundary-compatible in language... but boundary-unenforced in structure" (`adr-data-plane-boundary.md:22-26`), and a fix task already exists and is sequenced for this exact file (`data-plane-governance-t-agent-platform-amend`). Vetoing the whole track would discard four sound, valuable, already-fully-sequenced epics over one well-scoped defect; committing as-is would land a plan that contradicts the repo's own just-Accepted ADR on its very first "now"-lane epic. The fix is mechanical and precisely bounded (see revisions below), which is exactly what distinguishes revise-then-commit from veto here.

**Specific revisions required before commit** (mirrors `data-plane-governance-t-agent-platform-amend`'s acceptance criterion, `plans/data-plane-governance/roadmap.yaml:189`):

1. **Re-scope all six `cg1`-tagged items** (`agent-platform-e5`, `-spike-1`, `-m8`, `-t-dispatch-loop`, `-t-transcript-recording`, `-t-canned-task-run`) so the loop's *implementation* (spike code, the router→role-prefix→model_selector→shim dispatch loop, transcript recording, the canned-task run) is scoped to execute in the **separate repository** the ADR mandates (Decision 2, Option A) — not "inside this roadmap's own scope" (`:23`) or as work product of "this repo" (`:120`). Reword `agent-platform-e5`'s summary (`:120`) from *"Build the client-side dispatch loop this repo has never had"* to name the external repo explicitly (name/path deferred to m2 per the ADR, `:101`).
2. **Convert the in-repo code links to library references.** `server/orchestrator/model_selector.py`, `server/orchestrator/id_canon.py`, `server/router.py`, `server/prompts.py`, and `shim/arxmcp_shim.py` stay in arXMCP (ADR Decision 3: `model_selector.py`/`id_canon.py` remain here as an "SDK-free, dispatch-free policy/canonicalization library"); the `links: code:` blocks on the six `cg1` items (e.g. `:127`, `:410`, `:428`, `:442`) should read as *consumed-as-a-dependency* references from the external loop repo, not as files this roadmap's tasks edit to build the loop.
3. **Reword the must-tier assumption** at `:22-24` — replace "is buildable inside this roadmap's own scope" with language scoping the spike/build to the new external repo (coordinated by, not contained in, this roadmap), and keep the validation's re-dating fallback (D7-R13, D9-R09, cap-sizing) unchanged since that logic doesn't depend on repo placement.
4. **Correct the stale evidence bullet at `:63`** — strike "referenced only by tests" per the ADR's Decision 3 finding; keep the rest of the sentence (still accurate).
5. **Knock-on: re-anchor `agent-platform-e6`'s `depends_on: [agent-platform-e5]` (`:136`)** to depend on the external loop's *output* (an existing recorded pipeline session) rather than an in-repo epic, once e5 is re-scoped.

None of these revisions touch `server/` code or change any other track's dependencies; they are documents-only edits to this one file, consistent with the ADR's own "documents-only milestone" framing (`adr-data-plane-boundary.md:120-121`).

---

## SPECIAL — agent-platform ADR-conflict analysis (verbatim)

Per the assignment: checking precisely whether any item scopes the dispatch loop, an agent
loop, or per-run agent memory **in this repo**. All six `cg1`-tagged items do; none of them
ever names a separate repository. Quoted verbatim, with line numbers from
`plans/agent-platform/roadmap.yaml`:

**Must-tier assumption, lines 22–24** (the load-bearing planning premise for the whole epic):
> `:23` — *"A minimal orchestrator dispatch loop that drives one real sketcher-to-fixer pipeline session -- client-side, outside server/, no anthropic SDK at runtime per CLAUDE.md 4.7 -- is buildable inside this roadmap's own scope, without first requiring the Stage-2 worktree merge or a working Lean toolchain"*

"Client-side, outside `server/`, no anthropic SDK at runtime" satisfies the **old, narrower, convention-only** reading of CLAUDE.md §4.7 (no SDK import inside the `server/` Python package). It does **not** satisfy the ADR's actual, structural rule: Decision 1 rule 3 — *"The orchestrator dispatch loop lives outside this repository"* — and Decision 2's explicit rejection of "Option B — a carve-out under `tools/orchestrator_loop/`" on the grounds that *"`tools/` is imported by the server at runtime and ships in the wheel, so 'client-side under `tools/`' reduces to dependency-direction rules policed by convention — exactly the conventional-not-structural gap this ADR exists to close"* (`adr-data-plane-boundary.md:95-98`). "Inside this roadmap's own scope" places the loop's construction inside **this repo's own plan tracking**, which is the precise shape the ADR was written to foreclose.

**Epic `agent-platform-e5`, line 120:**
> *"Build the client-side dispatch loop **this repo has never had** -- no anthropic SDK at runtime, outside server/, per CLAUDE.md 4.7: router -> role-prefixed turns -> the already-shipped model_selector.py policy -> tool calls over the existing shim."*

"This repo has never had" frames the loop as a gap **this repo** fills — again silent on a separate repository, and read plainly, scoping the build as arXMCP's own deliverable.

**Spike `agent-platform-spike-1`, lines 400, 406** (the first executable step, `lane: now`, `target_end: 2026-07-10` — i.e., already due):
> `:400` title — *"Thin client-side orchestrator loop prototype on one canned task"*
> `:406` — *"...a thin client-side loop (router -> role-prefixed turns -> model_selector policy -> tool calls over the shim) drives it end to end **outside server/** with no anthropic SDK import inside server/, then a complete transcript is produced"*

Acceptance is graded only against "outside `server/`" + "no SDK import inside `server/`" — both satisfied by code sitting anywhere else *in this repo*, e.g. under `tools/`, the exact placement the ADR rejected.

**Milestone `agent-platform-m8`, line 416, and task `agent-platform-t-dispatch-loop`, line 439:**
> `:416` — *"The client-side dispatch loop ... drives one full sketcher-to-fixer session against a canned task and records it -- **arXMCP's first real agent traffic**..."*
> `:439` — *"...when the client-side loop runs it, then server/router.py classifies a RouteTag, server/prompts.py supplies the role prefix, and server/orchestrator/model_selector.py picks the model -- **all client-side, zero anthropic SDK import inside server/**"*

Same pattern: the only tested boundary is "no SDK inside `server/`," never "not in this repository."

**Minimal revision to reach ADR compliance:** re-scope the six `cg1` items (§4 above) so the loop's driver code is built and executed in a **separate repository** that consumes arXMCP as a path/git dependency (ADR Decision 2, Option A — name/path deferred to milestone m2), calling `server/orchestrator/model_selector.py`, `id_canon.py`, `server/router.py`, and `server/prompts.py` as an imported library exactly as the acceptance criteria already describe — only the *location* of the loop's own code needs to move, not the call pattern. This is a documents-only edit to `plans/agent-platform/roadmap.yaml`; no `server/` source changes.

---

## evidence-engine

### 1. What it scopes

Turns arXMCP's fully-built-but-never-fired eval machinery into real numbers: hand-label the
20-query fixture and produce the first `make eval` nDCG@5/Recall@10 numbers behind a
pinned append-only regression ledger (the "FIX" milestone other tracks, including R2, depend
on); paired-significance comparison machinery; an 8–10 task agent-task ergonomics harness
(pass^k, tool-call count, wrong-tool-selection rate); a zero-labeling auto-benchmark mined
from intra-paper `\ref{}` chains; specialized-index evaluation anchors (theorem-name gold
set, MIRB internal-embedder anchor, TED-fusion sanity sweep); and production telemetry
(dense-path latency, cache-hit gate, cache economics). Six epics, phase `complete`
(fully sequenced).

### 2. Boundary/trust alignment

**(a) Agent dispatch / agent loop / per-run agent memory inside this repo — NO CONFIRMED CONFLICT; one item worth a forward-looking note.** `evidence-engine-e3`/`m3` ("Agent-task ergonomics eval," `:87-96` and `:270-280`) is explicitly *"an orchestrator-side harness **outside server/**"* that primarily **reuses an external, already-published OSS harness** — *"Reuse MCP-Universe (Apache-2.0) if its 1-task smoke test passes; fall back to a bespoke loop otherwise"* (`:90`, repeated `:273`). This is structurally closer to the ADR's own carve-out for "dev-time agent scaffolding" (`adr-data-plane-boundary.md:58-60`, which explicitly exempts things like the milestone-pipeline's own Claude-agent tooling from the served-process rule) than to agent-platform's production-facing loop: it is an offline benchmark client, never claims to be product infrastructure, and its preferred path (MCP-Universe) runs entirely outside this repo already. The one open question is the **conditional fallback** — "a bespoke loop otherwise" doesn't say where that code would live if MCP-Universe's smoke test fails. If it landed under `tools/`, it would inherit the exact packaging risk the ADR used to reject agent-platform's Option B (`tools/` ships in the wheel and is imported by the server at runtime). This is genuinely unresolved-but-low-probability: `evidence-engine-m3` is in the `next` lane and explicitly **not yet task-decomposed** ("shaped milestones, no task decomposition," roadmap comment `:256`), so there is no premature task committing this code to a specific path today. Compare directly against evidence-engine's own `wont` line at `:48`: *"No agentic proving eval until the worktree merge, Lean toolchain, and orchestrator dispatch loop **all land externally**"* — this sibling line in the **same roadmap** already anticipates the loop landing externally, suggesting the plan's authors were oriented toward external placement even before this ADR existed.

**(b) Non-operator-gated write path — NONE FOUND.** `evidence-engine-e1`'s labeling report script explicitly wraps `search.py`'s internals with *"no new route, no server change"* (`:67`); hand-labels land in a test fixture (`tests/eval/fixtures/queries.json`) via direct owner file edits, not an agent-suggested write path; the run-manifest ledger (`var/arxmcp/ops/eval/ledger.jsonl`) is a metrics/log-shaped artifact, matching the ADR's explicit carve-out for "logs, metrics" as "implementation detail, not corpus writes" (`adr-data-plane-boundary.md:73-74`) — it records eval runs, it does not mutate corpus/index state.

**(c) Bare "verified"/single-trust-enum tool surface — NOT APPLICABLE.** This track never modifies any MCP tool response shape or `lean_verify`; "formalize-and-verify a trivial claim" (one of e3's 8-10 curated tasks) *exercises* the existing surface as a black-box client, it doesn't touch its trust vocabulary. §4.9 is R3's/R5's to implement.

**(d) Categorical novelty claims — NONE FOUND.** The brief's "never-measured era" framing and evidence bullet *"tests/eval/fixtures/queries.json — verified empty (queries: [])"* (`:53`) are internal, file:line-cited codebase facts about arXMCP itself, correctly shaped per §4.9(3) ("internal codebase facts are cited at file:line"), not external "no system does X" claims requiring a dated census.

### 3. R0–R7 relationship

**Foundational/complementary, not superseded.** Per the roadmap-briefs README's interlock table: *"R2's fixture work merges with FIX — one 50-query fixture, not two; R7's ablation extends its agent-task eval"* (`README.md:50`) — and the dependency-order note states R2 *requires* "the evidence-engine FIX milestone (populated eval fixture)" (`README.md:40`). So R2 and R7 are **downstream consumers** of evidence-engine's `evidence-engine-m1` (FIX) and `-e3`/`m3` outputs, not competing or superseding tracks. The fixture-size framing is compatible, not conflicting: evidence-engine targets ~20 queries now with explicit opportunistic growth "toward n≈30-50" (`:44`, wont list) and never claims exclusivity or a hard ceiling, leaving room for R2 to add queries later toward the README's "one 50-query fixture" combined target — a future coordination point for R2's own decomposition, not a defect in evidence-engine's plan as written today. No R-track scopes eval-fixture curation, agent-task ergonomics grading, or the auto-benchmark itself, so there is no overlap requiring resolution now.

### 4. Recommended disposition: **commit-as-is**

**Rationale.** All six epics are sound, internally consistent with the "no acting on the numbers, no LLM-judge grading, no labeling-workbench UI" discipline in its own `wont` list, and align cleanly with §4.8 (no write path outside the offline-report/owner-labeling pattern; the one agent-facing harness is explicitly a client, not server-embedded dispatch) and §4.9 (no trust-vocabulary changes, no novelty claims lacking internal citation). Its relationship to R0–R7 is strictly upstream/foundational — R2 and R7 are gated on this track's outputs, not competing with them — so it complements rather than duplicates the roadmap-briefs program. This should become a tracked active plan as written.

**Forward-looking note (not a blocking revision):** when `evidence-engine-m3` is task-decomposed (currently unshaped, `next` lane), the decomposition should make explicit that if the MCP-Universe reuse path fails its smoke test and the "bespoke loop" fallback (`:90`, `:273`) triggers, that fallback's driver code must not be added under `tools/` or any path packaged by `pyproject.toml` into the distribution — either reuse the (now-external, per this ADR) agent-platform loop repo as a dependency, or keep the harness genuinely dev-only and outside the shipped wheel. This mirrors the exact reasoning the ADR used to reject agent-platform's Option B (`adr-data-plane-boundary.md:95-98`) and costs one sentence to preempt at decomposition time; it does not block committing this track now, since no task currently scopes that code to any specific location.

**Secondary observation (cross-track, informational only):** `agent-platform-e5`/`m8` (`plans/agent-platform/roadmap.yaml:120,416`) frames its single-task pipeline-session transcript as *"the evidence-engine track's agent-behavior eval input,"* but `evidence-engine-e3`/`m3` as written does not reference consuming that transcript — it scopes an independent 8-10 task harness via MCP-Universe or a bespoke loop. This is not a boundary or trust conflict and needs no disposition change, but the two sibling tracks should reconcile whether evidence-engine's harness consumes agent-platform's recorded session or is fully independent of it; this is naturally addressed alongside agent-platform's m2 amendment (§SPECIAL above) since both touch the same loop-output question.
