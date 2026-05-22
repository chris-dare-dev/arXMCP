# Verification Feedback for the Autoformalization Pipeline — Roadmap

**Slug:** `verification-feedback`
**Created:** 2026-05-22T15:50:10Z
**Status:** init

<!--
This roadmap is itself the state. Re-invoking the `roadmap` skill on
this file resumes from the first un-populated phase.

Phases:
  1. REFINE     — How-Might-We, sharpening questions, assumptions, OKR, Won't list
  2. DECOMPOSE  — technique, epics, INVEST, specialist suggestions
  3. SEQUENCE   — MoSCoW, RICE, Now/Next/Later, spike lane, Now-lane milestones
  4. MATERIALIZE — validation results, optional GitHub bundle, next-step handoff

Source brief: the capability-scout final report at
.claude/notes/capability-scouts/2026q2-verification-feedback-scan/artifacts/final-report.md
(top-ranked candidates CAND-2, CAND-1; CAND-3 + CAND-5 in the Spike lane).
-->

---

## Phase 1 — Refine

### How Might We

How might we give arXMCP's tactician and fixer agents real execution-based verification feedback — and a traversable proof chain — for the sketcher → autoformalizer → tactician → fixer pipeline, without breaking the local-first, no-`anthropic`-SDK-at-runtime architecture or the BP1/BP2 prompt-cache discipline?

### Sharpening questions answered

1. **Is this one milestone of work, or a multi-quarter program?** — One coherent epic-set. The capability-scout surfaced 14 candidates; this roadmap scopes only the top-ranked, internally-coherent slice (verification feedback + the citation-graph stub). The broader catalog stays in `.claude/notes/capability-scouts/2026q2-verification-feedback-scan/` for future cycles.
2. **What is the minimum that delivers user-visible value?** — Wiring `cite_neighbors` (scout CAND-2). The library already shipped and is tested (E09_S03); only the MCP boundary is missing, so it delivers the proof-chain workflow with zero new dependencies — the demoable floor.
3. **Does the Lean verification tool require the `E14_S06` "v2 design document" un-park trigger?** — Yes. `E14_S06` parks Lean toolchain integration as Tier-7/v2 with un-park trigger "a dedicated v2 design document exists." The research phase of the Lean epic produces exactly that document; this roadmap is the formal un-park.
4. **Should Mathlib search (scout CAND-5) be a committed epic here?** — No. It carries an unresolved scope-expansion question (a second, formal corpus) and an M-vs-L effort swing. It belongs in the Spike lane, informing a future cycle — not as a committed epic.
5. **Who curates the eval fixture?** — Owner-led or owner-reviewed: it needs research-math domain judgement. It is scoped as an epic but flagged as requiring owner input rather than fully-autonomous execution.

### Assumptions

- `[MUST]` A local Lean 4 toolchain (`lake exe repl`, the `leanprover-community/repl` JSON protocol) can be installed on arXMCP's target workstation and driven as a non-blocking `asyncio` subprocess. If false, the Lean verification epic is infeasible as designed. → validated by `verification-feedback-spike-2`.
- `[MUST]` A maintained Kùzu successor (e.g. `Vela-Engineering/kuzu`) is installable via a pinnable PyPI release with API parity to `kuzu==0.11.3`, OR `kuzu==0.11.3` remains adequate for the citation-graph epic. A `git+https://` pin is excluded — it is a Threat-6 supply-chain surface. → validated by `verification-feedback-spike-1`.
- `[SHOULD]` The `server/graph_queries.py::cite_neighbors` library is correct and complete as shipped (E09_S03, tested) — wiring is purely a boundary task with no library changes. Fallback if wrong: a small library-side fix folds into the same milestone.
- `[SHOULD]` Adding a `lean_verify` tool and threading the MCP `Context` through handlers does not regress BP1/BP2 prompt-cache discipline (tools/list byte-stability). Fallback: the `ctx` parameter is server-internal and not part of the tool input schema, so the schema hash should be unaffected — confirmed during implementation.
- `[MIGHT]` Curating 20 eval queries against the 50-paper math.AG seed corpus is tractable within a single milestone.

### Objective

Turn arXMCP from a passive retrieval substrate into a full agent-harness component — giving its downstream verification roles (tactician, fixer) structured Lean kernel execution feedback and a traversable citation/proof chain — while preserving the local-first, no-LLM-at-runtime, cache-disciplined architecture that every prior epic was built around.

### Key Results

1. The proof-chain workflow is executable end-to-end through the MCP surface: an agent traverses from a chunk to its citation neighbors via the `cite_neighbors` tool with zero direct-library calls (today: impossible — the handler is a stub returning `infrastructure_status: "deferred"`).
2. The tactician and fixer receive structured Lean kernel feedback (compilation status, error severities + source positions, proof state, remaining goals) through a `lean_verify` MCP tool — closing the execution-feedback gap all five capability scouts independently ranked #1.
3. `make eval` reports a real, non-skipped nDCG@5 / Recall@10 figure against a curated 20-query fixture (today: skipped — `tests/eval/fixtures/queries.json` is an empty stub), giving every future retrieval-behavior change a regression backstop.
4. Zero regressions at every milestone: `make test` green, `ruff check .` clean, BP1/BP2 prompt-cache discipline intact — every MCP-tool change re-pins `EXPECTED_TOOL_SCHEMA_SHA256` deliberately and never bypasses it.

### Won't (explicit out-of-scope)

- Mathlib corpus ingestion / a `search_mathlib` tool (scout CAND-5) — the scope-expansion decision (does arXMCP host a second, formal corpus?) is unresolved; Spike-lane only this cycle.
- Proof-state-conditioned retrieval / `search_by_proof_state` (scout CAND-6) — hard-depends on the Lean tool shipping first; deferred to a follow-on cycle.
- GNN citation re-ranking (CAND-9) and Matryoshka/dual-resolution embeddings (CAND-15) — v2 backlog; the 50-paper seed corpus is too small for either to pay off.
- Chunk-level v1-vs-v3 structural diff (the hard half of CAND-13) — version *listing* may enter a later cycle; the structural diff is v2.
- Any outbound network enrichment (Semantic Scholar SPECTER2/TLDR, remote citation fallback) — violates the local-first principle; explicitly excluded.
- Any LLM-based critic or `anthropic`-SDK-at-runtime path — architecture-lock (`CLAUDE.md §4.7`); the Lean kernel is the only critic, exposed as a thin wrapper, never a free-running LLM.
- Authoring the `server/prompts.py` SYSTEM_PROMPT — orchestrator-author scope, tracked separately from this roadmap.

---

## Phase 2 — Decompose

### Technique

Vertical slicing + enabler stories. Each value epic delivers an independently demoable capability slice through the MCP surface; the eval-fixture epic is a pure enabler that backstops future retrieval work. No journey/event-storming/impact-mapping shape applies — the work is tool-surface additions, not a discoverable user journey.

### Epics

#### verification-feedback-e1 — Proof chains traversable through the MCP surface

- **Type:** value
- **Specialist suggestion:** `cache-stability-reviewer` and `determinism-reviewer` — see `.claude/skills/roadmap/references/specialist-contracts.md` (touches the `cite_neighbors` tool schema and the retrieval cache key)
- **Outcome:** an agent traverses from a chunk to its `cites` / `cited_by` / `depends_on` neighbors via the `cite_neighbors` MCP tool within the existing 500 ms gate, with zero direct-library calls and the F2 path-validation contract honored.
- **Estimated size:** S
- **INVEST check:** I clean (independent of e2/e3/e4), N clean, V clean (demoable — the proof-chain workflow becomes usable), E clean, S clean, T clean.
- **Dependencies:** none. `verification-feedback-spike-1` informs the Kùzu pin but e1 proceeds on `kuzu==0.11.3` regardless.
- **Won't conflict check:** none.

#### verification-feedback-e2 — Tactician and fixer receive Lean kernel execution feedback

- **Type:** value
- **Specialist suggestion:** `security-reviewer` and `mcp-protocol-reviewer` — see `.claude/skills/roadmap/references/specialist-contracts.md` (subprocess invocation + tool input validation + Lean sandbox; new MCP tool registration + progress notifications)
- **Outcome:** a `lean_verify` MCP tool returns structured Lean 4 kernel output (status, error severities + source positions, proof state, remaining goals, `sorry` locations) in `full` and `syntax_only` modes; gated behind `ARXMCP_ENABLE_LEAN` (default off); long calls emit MCP progress notifications. Folds scout candidates CAND-1, CAND-4a (`syntax_only`), and CAND-12 (progress notifications).
- **Estimated size:** M
- **INVEST check:** I clean (independent of e1), N clean, V clean, E **borderline** — the Lean toolchain is a system-level dependency, not a pip dep; `verification-feedback-spike-2` de-risks it before implementation. S clean (M ≤ 6 weeks), T clean.
- **Dependencies:** none hard. `verification-feedback-spike-2` should resolve before implementation begins.
- **Won't conflict check:** none — `lean_verify` is a thin kernel wrapper, not an LLM critic, so it honors the no-LLM-at-runtime lock.

#### verification-feedback-e3 — Retrieval changes have a measurable regression backstop

- **Type:** enabler
- **Specialist suggestion:** `—` (eval-fixture curation is test data; milestone-pipeline's adversary critic suffices)
- **Outcome:** `make eval` produces a non-skipped nDCG@5 / Recall@10 figure against a curated 20-query fixture, so future retrieval-behavior epics have a regression backstop. Folds scout candidate CAND-14.
- **Estimated size:** S
- **INVEST check:** I clean, N clean, V **borderline** — an enabler with no direct user-visible behavior; its value is realized by future retrieval epics, which is the accepted nature of an enabler epic. E clean, S clean, T clean.
- **Dependencies:** none.
- **Won't conflict check:** none.

#### verification-feedback-e4 — Incremental per-tactic verification

- **Type:** value
- **Specialist suggestion:** `security-reviewer` and `mcp-protocol-reviewer` — see `.claude/skills/roadmap/references/specialist-contracts.md` (extends the Lean subprocess with a session-scoped REPL pool)
- **Outcome:** `lean_verify` gains an `incremental` mode — submit one tactic against a held `proof_state_id`, receive the resulting goal state — backed by a session-scoped REPL pool keyed on `Mcp-Session-Id`. This is scout candidate CAND-4b, which the Phase-3 challenger explicitly recommended splitting out from CAND-4a as its own M-sized, dependent epic.
- **Estimated size:** M
- **INVEST check:** I **borderline** — depends on e2 (the REPL subprocess and `lean_verify` tool must exist first); dependency noted explicitly. N clean, V clean, E clean, S clean, T clean.
- **Dependencies:** `verification-feedback-e2`.
- **Won't conflict check:** none.

---

## Phase 3 — Sequence

### MoSCoW assignment

Verified by `score-moscow.py` — Must = 50.0% of total effort (≤ 60% cap).

- **Must** (≤ 60% of total effort): `verification-feedback-e1`, `verification-feedback-e2`
- **Should**: `verification-feedback-e3`
- **Could**: `verification-feedback-e4`
- **Won't (this cycle)**: —

### RICE ranking — Musts

Verified by `score-rice.py`. Reach is a relative breadth figure; Effort in person-weeks (S=1, M=3); Confidence is evidenced, not defaulted.

| ID | Reach | Impact | Confidence | Effort | Score |
|---|---:|---:|---:|---:|---:|
| verification-feedback-e1 | 4000 | 3.00 | 95% | 1.00 | 11400.0 |
| verification-feedback-e2 | 5000 | 3.00 | 80% | 3.00 | 4000.0 |

_No `*` markers — both Confidence values are evidenced (e1: the `cite_neighbors` library is shipped + tested, 4-brief scout triangulation; e2: 5-brief triangulation, discounted to 80% because the Lean toolchain integration is unproven on the target workstation until `verification-feedback-spike-2`)._

e1 ranks above e2 — consistent with the capability-scout's own RICE-light ranking (CAND-2 was the single highest-RICE candidate in the 14-item catalog). Wire `cite_neighbors` first: it is the smaller effort against a more certain payoff and builds confidence before the larger Lean epic.

### Now / Next / Later

- **Now** (fully spec'd, milestones decomposed below): `verification-feedback-e1`, `verification-feedback-e2`
- **Next** (shaped, awaiting capacity): `verification-feedback-e3`
- **Later** (outcome-only, low-confidence horizon): `verification-feedback-e4`

### Spike / discovery lane

- `verification-feedback-spike-1` — Confirm a maintained Kùzu successor (`Vela-Engineering/kuzu` or another) is installable via a pinnable PyPI release with API parity to `kuzu==0.11.3`; if none is, confirm `0.11.3` remains adequate. A `git+https://` pin is explicitly out of bounds. (≤ 3 days, validates `[MUST]` assumption: maintained-Kùzu-pinnable-or-0.11.3-adequate.)
- `verification-feedback-spike-2` — Confirm a local Lean 4 REPL (`lake exe repl`) can be installed on the target workstation and driven as a non-blocking `asyncio` subprocess; decide raw `leanprover-community/repl` JSON protocol vs the LeanDojo Python API as the backend. (≤ 3 days, validates `[MUST]` assumption: Lean-toolchain-subprocess-feasible.)
- `verification-feedback-spike-3` — Scope decision for a future Mathlib-search cycle (scout CAND-5): does arXMCP host a Mathlib declaration corpus at all, and is a pre-built declaration index downloadable (effort M) or must it be generated from a 2–4 GB mathlib4 build (effort L)? (≤ 3 days; informs a future cycle — not a `[MUST]` of this roadmap.)

### Milestones — Now lane

### verification-feedback-m1 — Wire the `cite_neighbors` MCP handler to the live library

**Description.** Replace the v1 stub body in `server/handlers/citations.py` (which returns `{neighbors: [], infrastructure_status: "deferred"}`) with a real call to the shipped, tested `server/graph_queries.py::cite_neighbors` library. Re-align the handler `direction` enum to the library's, honor the F2 path-validation contract, and add a `graph_version` component to the cache key so a graph re-ingest invalidates stale neighbors. The library needs no changes — this is purely the MCP boundary.

**Acceptance criteria.**
- [ ] `server/handlers/citations.py` calls `server.graph_queries.cite_neighbors(...)`; the stub `infrastructure_status: "deferred"` path is removed.
- [ ] Handler `direction` enum re-aligned to the library's `Literal["cites","cited_by","depends_on"]`; `EXPECTED_TOOL_SCHEMA_SHA256` re-pinned via `pytest --update-tool-schema-hash`.
- [ ] Kùzu and LanceDB paths are derived from Config / `get_resources()`, never from agent-supplied JSON (F2 path-validation contract from the E09_S03 critique).
- [ ] `cite_neighbors` cache entries include a `graph_version` key component; a citation-graph re-ingest invalidates stale results (correctness requirement, not an optimization).
- Given an ingested chunk with citation edges, When an agent calls `cite_neighbors`, Then real neighbors are returned within the 500 ms gate — verified by `tests/test_proof_chain.py` exercising the handler, not only the library.
- [ ] `make test` green, `ruff check .` clean.

**Dependencies.** none. `verification-feedback-spike-1` informs the Kùzu dependency pin but does not block m1 (it proceeds on `kuzu==0.11.3`).

**Complexity.** M

**Specialist suggestion.** `cache-stability-reviewer`, `determinism-reviewer`

### verification-feedback-m2 — Lean REPL subprocess harness + `ARXMCP_ENABLE_LEAN` gate

**Description.** Add a managed local Lean 4 REPL subprocess, driven via `asyncio.create_subprocess_exec` so it never blocks the event loop (pure-ASGI rule). Start and stop it conditionally inside the async `lifespan` based on a new `ARXMCP_ENABLE_LEAN` env var (default off, mirroring `ARXMCP_ENABLE_RERANK`), so the server starts cleanly on workstations without a Lean toolchain. Apply E13_S03-style sandbox discipline.

**Acceptance criteria.**
- [ ] `ARXMCP_ENABLE_LEAN` env var added to `server/config.py`, default `false`.
- [ ] The Lean REPL subprocess is managed inside the async `lifespan` in `server/main.py`; no synchronous or event-loop-blocking startup path; no first-call cold-start race.
- [ ] A one-page Lean-sandbox sub-design (modeled on the E13_S03 LaTeXML sandbox: subprocess timeout, filesystem isolation to a temp dir, memory cap) is committed under `.claude/docs/`.
- Given `ARXMCP_ENABLE_LEAN=false`, When the server starts, Then no Lean subprocess is spawned and all 7 existing MCP tools work unchanged.
- [ ] A `requires_lean_repl` pytest marker is added; Lean-dependent tests skip cleanly when the Lean binary is absent.
- [ ] `make test` green, `ruff check .` clean.

**Dependencies.** `verification-feedback-e2`. `verification-feedback-spike-2` should resolve before this milestone begins.

**Complexity.** M

**Specialist suggestion.** `security-reviewer`

### verification-feedback-m3 — `lean_verify` MCP tool with `full` + `syntax_only` modes

**Description.** Register a `lean_verify` MCP tool that accepts a Lean 4 snippet, context imports, and a `mode` of `full` or `syntax_only`, drives the m2 REPL subprocess, and returns structured kernel output. `full` runs kernel verification; `syntax_only` short-circuits after elaboration (cheap sketch validation for the autoformalizer).

**Acceptance criteria.**
- [ ] `server/handlers/lean_verify.py` handler added; tool registered in `server/tools.py::ALL_TOOLS`; `EXPECTED_TOOL_SCHEMA_SHA256` re-pinned.
- [ ] Result schema returns `{status, messages:[{severity,position,text}], proof_state, goals_remaining, sorry_goals, compilation_success}`; a frozen result-row schema file is added; the 150-char snippet contract does not apply (no `snippet` field) and that is documented.
- Given a Lean 4 snippet with a type error, When `lean_verify` is called with `mode="full"`, Then `compilation_success` is `false` and `messages` carries the error with severity + source position.
- Given a proof with a remaining `sorry`, When `lean_verify` is called, Then `sorry_goals` lists the goal and `goals_remaining` is non-empty.
- Given any snippet, When `lean_verify` is called with `mode="syntax_only"`, Then the call returns after elaboration without full kernel verification.
- [ ] The Lean REPL subprocess enforces a hard memory cap — the `RLIMIT_AS` address-space limit deferred from m2 (see `.claude/docs/lean-sandbox-design.md` "Memory cap" row, D4) lands here, because m3 is where agent-supplied Lean source first reaches `LeanRepl.query`. POSIX: `resource.setrlimit(RLIMIT_AS, ...)` via a `preexec_fn`. A `@requires_lean_repl` test submits a high-allocation snippet and asserts the REPL is bounded rather than OOM-killing the parent.
- [ ] `make test` green, `ruff check .` clean.

**Dependencies.** `verification-feedback-m2`.

**Complexity.** M

**Specialist suggestion.** `mcp-protocol-reviewer`, `security-reviewer`

### verification-feedback-m4 — Progress notifications for long-running tools

**Description.** Thread the MCP `Context` through tool handlers and emit `report_progress()` notifications during `lean_verify` calls (5–30 s Lean elaboration), so the calling agent sees progress rather than an apparent hang. Folds scout candidate CAND-12; sequenced with the Lean epic because that is where the long-running call lives.

**Acceptance criteria.**
- [ ] Handler signatures and the `server/tools.py` registration wiring are updated to pass `ctx: Context`; the 7 existing handlers are unchanged in behavior.
- Given a `lean_verify` call that runs longer than 2 s, When it executes, Then at least one `notifications/progress` message is emitted before the result.
- [ ] No BP1/BP2 cache-discipline regression — the `tools/list` bytes are unchanged by the `ctx` plumbing (the `ctx` parameter is server-internal, not part of any tool input schema), so `EXPECTED_TOOL_SCHEMA_SHA256` is unchanged by this milestone.
- [ ] `make test` green, `ruff check .` clean.

**Dependencies.** `verification-feedback-m3`.

**Complexity.** M

**Specialist suggestion.** `mcp-protocol-reviewer`

---

## Phase 4 — Materialize

### Validation

- `validate-roadmap.py`: pass
- Must-cap: 50.0% (≤ 60%)
- All Now-lane milestones have AC: yes
- Slug format valid: yes (`verification-feedback` — matches `^[a-z][a-z0-9-]{2,30}$`, does not collide with `^e\d+$`)

### GitHub tickets

Not requested (run the `roadmap` skill with `--github` to bundle epic + story body files plus a copy-paste `create-tickets.sh`).

### Next step

First Now-lane milestone: `verification-feedback-m1` (wire the `cite_neighbors` handler — the highest-RICE, lowest-risk move). To execute it end-to-end through Research → Implement → Critique → Rectify, run:

    /milestone-pipeline verification-feedback-m1

`milestone-pipeline`'s `init-state.sh` searches both `.claude/roadmap/*.md` and `plans/*.md`, so it will find this milestone brief. This roadmap will not invoke milestone-pipeline. Before starting the Lean epic (m2–m4), run `verification-feedback-spike-2` to de-risk the Lean toolchain `[MUST]` assumption; similarly `verification-feedback-spike-1` before deciding the Kùzu dependency pin.

---

<!-- end:roadmap -->
