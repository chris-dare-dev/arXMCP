# ADR — arXMCP data-plane boundary (data-plane-governance-m1)

**Status:** Accepted (see Owner approval record)
**Date:** 2026-07-12 · **Owner:** Chris Dare (per OWNERS.md)
**Roadmap item:** `data-plane-governance-m1` (plans/data-plane-governance/roadmap.yaml)
**Source brief:** `.claude/roadmap-briefs/R0-data-plane-governance.md` (adjudicated
gap-analysis program, 2026-07-11)

This is the repo's first ADR. It makes arXMCP's data-plane identity *structural* rather
than conventional: what the server may never do, where the agent loop lives, what happens
to the orchestrator library, and how restrictively-licensed external data is handled.
CLAUDE.md §4.8 carries the binding short form; this document is the rationale and the
record.

## Context and problem statement

- arXMCP's mission is to be the **substrate** under multi-agent proving pipelines — "the
  server returns grounded evidence only; it does not reason, summarize, or mutate state
  via MCP" (server MCP instructions; `.claude/notes/01-mission-and-context.md`). The
  boundary has been convention, not constitution: no document a future session must obey
  states it.
- The untracked `plans/agent-platform/roadmap.yaml` scopes a "minimal orchestrator
  dispatch loop" that is boundary-*compatible* in language ("client-side, outside
  `server/`, no anthropic SDK at runtime per CLAUDE.md 4.7") but boundary-*unenforced* in
  structure: nothing but discipline keeps a loop under this repo out of the served
  process, the wheel, or the dependency tree.
- The 2026-07-11 adjudicated gap analysis (§7.4) concluded the product is "outputs whose
  epistemic status cannot be misread" and recommended the boundary be made structural.
  Its trust-language finding anchors here too: `server/handlers/lean_verify.py:290-298`
  maps "no error messages and no sorries" to `status: "ok"` — a bare status a downstream
  agent can over-read. Trust-language policy is milestone m3's scope; this ADR fixes the
  *boundary* so m3's rules attach to a defined surface.
- Verified facts this ADR must not contradict (research briefs 1–2, 2026-07-11):
  - `server/` contains **no** agent dispatch and **no** per-run agent memory: zero
    `anthropic` imports (guard test `tests/test_langfuse_doc.py` ~:179-207 enforces the
    CLAUDE.md §4.7 ban); `server/session.py` counters are budget caps, not agent memory;
    the `Arxmcp-Agent-Role` header is observability labeling of the *calling* agent.
  - `server/orchestrator/model_selector.py` is **not** "referenced only by tests" (a
    stale claim in the agent-platform plan's evidence): it is transitively imported at
    server startup via `server/observability/spend_constants.py:51` →
    `server/observability/__init__.py:30` → `server/main.py`, solely for the
    `MODEL_HAIKU_4_5` metric-label constant. `tests/test_model_selector.py` pins the
    module path and bans model-id strings elsewhere in `server/`.
  - "Under `tools/` " is **not** process isolation: the server imports `tools.*` at
    runtime (`server/routes/notebooks.py:64-74`) and `pyproject.toml` packages
    `tools*` into the single distribution — a loop under `tools/` would ship in the
    wheel beside the server.
  - Write surfaces that exist today: ~18 offline ingest CLIs (`tools/notebook_*.py`,
    `python -m ingest.*`, `make ingest`) and 11 operator-gated mutating routes under
    `/ui/api` (`server/routes/notebooks.py`), including POST `…/ingest` which runs the
    ingest task **in the server process** — an operator-gated console action, not an
    offline one. The MCP surface itself registers 8 tools, none of which mutates corpus
    state.

## Decision 1 — the three boundary rules (binding)

Scope of the rules: **the served process and the `server/` package** (and the shipped
distribution). They do not govern the repo's dev-time agent scaffolding under `.claude/`
— the milestone pipeline that authored this ADR is itself Claude agents, and outlawing it
would be self-contradictory.

1. **No agent dispatch, no per-run agent memory, server-side.** The server MUST NOT
   dispatch LLM/agent calls, embed an agent loop, or hold per-run agent state (run
   memory, transcripts, model conversation state). The `anthropic` SDK MUST NOT appear in
   `server/` imports or in `pyproject.toml` runtime dependencies (existing guard:
   `tests/test_langfuse_doc.py`). Observability labeling of a *calling* agent's role and
   per-session budget counters are not agent memory and remain permitted.
2. **Writes only via offline ingest or operator-gated console actions.** Corpus and
   index state changes MUST enter only through (a) offline ingest CLIs run by the
   operator, or (b) the loopback-only `/ui/` console's explicit operator actions
   (including its in-process ingest dispatch). The MCP tool surface stays read-only over
   corpus state; `lean_verify` computes but MUST NOT persist corpus-visible state.
   Carve-out: server-internal operational writes (retrieval-cache SQLite, logs, metrics,
   ingest-status transitions, health markers) are implementation detail, not corpus
   writes. Any *future* agent-suggested write path MUST terminate in an operator-confirm
   step (the agent-platform plan's "pending queue behind operator confirm in /ui/" shape
   is the compliant pattern).
3. **The orchestrator loop lives outside this repository** (Decision 2). No `server/`
   module may import the loop; the loop holds no state the server reads.

## Decision 2 — orchestrator-loop placement: separate repository (Option A)

**Chosen: Option A — a separate repository** hosting the client-side dispatch loop
(router → role-prefixed turns → model policy → MCP tool calls over the existing shim),
consuming arXMCP as a local path/git dependency.

- Why: the repo boundary is the only enforcement mechanism that requires no new tooling
  (R0 explicitly defers enforcement tooling); the `anthropic` SDK never enters arXMCP's
  dependency tree, wheel, or container; the existing server-scoped SDK-ban test stays
  sufficient as-is. This matches the adjudicated gap-analysis recommendation and the
  briefs-README standing policy ("agents, run memory, and model policy live outside").
- **Option B — a carve-out under `tools/orchestrator_loop/` — was considered and
  rejected** because the research falsified its central premise: `tools/` is imported by
  the server at runtime and ships in the wheel, so "client-side under tools/" reduces to
  dependency-direction rules policed by convention — exactly the conventional-not-
  structural gap this ADR exists to close. B remains cheaper day-to-day; the owner chose
  structure over friction (approval record below).
- Follow-ups this choice creates: milestone m2's `t-agent-platform-amend` aligns
  `plans/agent-platform/roadmap.yaml` (its loop items execute in the new repo; its
  in-repo code links become library references). The loop repo's name/path is deferred
  to m2. The loop's tests run in its own repo; cross-repo sync friction is accepted on
  this single-workstation setup.

## Decision 3 — disposition of `server/orchestrator/`

**Chosen: keep `server/orchestrator/` (model_selector.py, id_canon.py) in arXMCP,
in place, as an SDK-free, dispatch-free policy/canonicalization library** consumed by the
external loop repo.

- The true consumer set (recorded here to retire the stale "tests-only" claim):
  `server/observability/spend_constants.py:51` (runtime import of `MODEL_HAIKU_4_5` for
  spend metrics — reaches the running server transitively), `tests/test_model_selector.py`
  (path pin `orchestrator/model_selector.py`; model-id allow-list; `python -O` invariant
  test), `tests/test_spend_constants.py`, `tests/test_langfuse_doc.py` (doc-lint), and —
  prospectively — the external loop repo.
- Relocation was rejected: it would break the runtime import and the test pins, i.e.
  `server/` code changes, which this documents-only milestone forbids (roadmap wont) and
  which buy nothing: the module is pure lookup, boundary-compatible where it sits.
- Nothing in this decision licenses the module to grow dispatch behavior: rule 1 governs.

## Decision 4 — candidate layer for non-commercially-licensed external data

Non-commercially-licensed external data (e.g. CC-BY-NC-SA TheoremGraph dumps) enters
ONLY a candidate layer: it is never redistributed (not served over MCP, not bundled into
any release, image, or backup intended to leave this workstation), and never promoted
into served evidence (chunks, indices, graph) without an explicit per-source license
check recorded at promotion time. Candidate entries carry provenance (source system +
version, fetch date, license) so the check is auditable. Adapter-level enforcement and
the acceptance-state schema are R7's to define (this ADR fixes the principle, not the
mechanism).

## Decision 5 — CLAUDE.md anchor

**Chosen: a new `### 4.8 Data-plane boundary — hard constraints (binding)` subsection**
appended under §4 "Working conventions — READ BEFORE COMMITTING", adjacent to the §4.7
rules it generalizes. Rationale: §-numbers are cited pervasively across tests, comments,
and plans, so nothing may be renumbered; CLAUDE.md has no existing "Hard constraints"
section (that header names *different* lists in README.md:~135 and
.claude/notes/README.md:~20), and a third same-named block would invite confusion.
Milestone m3's trust-language rules land as §4.9 or extend §4.8.

## Consequences

- Good: R1–R7 tracks gain a citable, owner-approved boundary; the agent-platform track's
  placement question is closed; a future reader can distinguish "server never runs
  agents" (constitution) from "no anthropic SDK in server/" (mechanism).
- Bad / accepted costs: two working trees for one owner (loop repo); cross-repo sync on
  schema/prompt changes; the boundary between this repo's `plans/agent-platform/` items
  and the loop repo's execution must be kept straight by m2's amendment.
- Deliberately NOT decided here (per R0 wont): m2's plan dispositions, m3's
  trust-language/abstention/evidence-ledger policies, any enforcement tooling (grep
  tests, dependency linters — consuming tracks own those), all R7 adapter/licensing
  specifics, and any `server/` code change.
- Known ambient hazards recorded for the next session: the working tree carries
  uncommitted paper-metadata-m2 doc/state updates (not this milestone's; see
  `.claude/notes/milestones/data-plane-governance-m1/preflight-deviation.md`); the
  Obsidian vault stamper may add cosmetic frontmatter to this file post-commit (no clean
  filter covers `.claude/docs/`); `AGENTS.md` (untracked Codex mirror) will drift from
  the amended CLAUDE.md until regenerated.

## Owner approval record

- **2026-07-12 — Approved (Accepted).** Approval granted interactively by the owner at
  the milestone-pipeline consolidated checkpoint (AskUserQuestion, session of
  2026-07-11/12), with the three decisions supplied explicitly: orchestrator-loop
  placement = **separate repository**; CLAUDE.md anchor = **new §4.8**; pre-existing
  paper-metadata-m2 working-tree hunks = **leave uncommitted** (m1 commits use
  hunk-scoped staging). Approval mode chosen by owner: "Approve on decisions" — the ADR
  lands as Accepted with this record, and the CLAUDE.md amendment lands in the same
  reviewed diff.
- Edits requested: none at approval time. (Post-critique rectifications, if any, are
  recorded by the pipeline's rect commit, not by re-opening this record.)
