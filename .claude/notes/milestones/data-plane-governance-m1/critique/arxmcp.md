# Critique — data-plane-governance-m1 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** cfb7c270ff7d3fabccdcde65bd6a0f5af2dcf2cb..90a10492558d65cdbb3f2d58cd4c9747c9718329
**Diff stats:** 2 files, 204 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

The diff delivers exactly what the milestone charters — an owner-approved boundary ADR whose falsifiable claims verify against the code (11/11 mutating `/ui/api` routes, the 8-tool `ALL_TOOLS` registration, the `spend_constants.py:51` runtime import, `lean_verify.py:290-298`, `pyproject.toml` `tools*` packaging, and the 18-script CLI count all re-checked exact) plus a purely additive CLAUDE.md §4.8 that keeps every phrase pin green (`tests/test_constitution_ui_claims.py` re-run: 28/28 pass). Two MEDIUM documentation-integrity defects keep it from a clean SHIP: the ADR misattributes its central standing-policy quotation to a document that does not contain it, and the host CLAUDE.md still asserts a 7-tool surface in present tense two sections away from binding text governed by the ADR's verified 8-tool fact. Both are one-to-two-line markdown fixes fully inside this milestone's docs-only scope. No CRITICAL or HIGH issues; the boundary rules themselves are sound, correctly scoped, and consistent with the local-first and threat-model doctrine.

## Executive summary

- [MEDIUM] ADR:91 attributes the quotation "agents, run memory, and model policy live outside" to the briefs-README standing policy; the string exists only in `R0-data-plane-governance.md:16` — the repo's first ADR carries a citation that fails verbatim verification.
- [MEDIUM] CLAUDE.md:415 still claims "`tools/list` returns 7 frozen tool meta records" (present tense, §6 capabilities) while the ADR it now links records the verified 8-tool surface — the binding doc contradicts its constitution on the exact surface rule 2 governs.
- [LOW] ADR:17's mission quotation lives at `server/mcp_instructions.py:48`; the co-cited mission note contains neither the sentence nor the phrase.
- [LOW] ADR:50 "runs the ingest task in the server process" overstates locality — the route spawns a supervised child subprocess; rule 2's own "in-process ingest dispatch" wording is the accurate form.
- [LOW] CLAUDE.md:462 "make ingest is a stub that exits 1" contradicts the ADR's write-surface inventory (Makefile:188 is the shipped E11_S01 bulk orchestrator).
- [LOW] Rule 2 constitutionalizes `/ui/` console writes without noting the console's open security audit (E13 scope-out, tracked at chris-dare-dev/arXMCP#9).

## Findings

**M1 — ADR misattributes its standing-policy quotation to the briefs README** (MEDIUM)

**Where:** `.claude/docs/adr-data-plane-boundary.md:91`
**Anchor:** `  briefs-README standing policy ("agents`
**What:** Decision 2 attributes the quotation "agents, run memory, and model policy live outside" to "the briefs-README standing policy", but that string exists only at `.claude/roadmap-briefs/R0-data-plane-governance.md:16` — the briefs README's standing policy 1 uses different wording ("The server never runs agents, never holds per-run agent memory, and takes writes only through offline/operator-gated ingest").
**Why it matters:** The milestone's product is a citable constitution, and a reader who greps the named source for the quoted words finds nothing — the repo's first ADR would teach future sessions that its citations do not verify.
**Proposed fix:** Re-attribute the quotation to `R0-data-plane-governance.md:16` (e.g. "...matches the adjudicated gap-analysis recommendation and R0's framing ('agents, run memory, and model policy live outside', R0-data-plane-governance.md:16), restated as briefs-README standing policy 1"). While editing, qualify the "model policy" clause against Decision 3 — dispatch-time policy decisions live outside; the inert `model_selector` lookup table stays in-repo — so the quoted words and Decision 3 cannot be read as contradicting.
**Regression-guard:** Optional (MEDIUM). A quotes-verify doc-lint would brush against R0's no-enforcement-tooling wont; cheapest guard is a one-line re-verify item on m3's checklist when §4.9 lands.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing

**M2 — CLAUDE.md claims a 7-tool surface; the linked ADR records 8** (MEDIUM)

**Where:** `CLAUDE.md:415`
**Anchor:** `- **`tools/list`** returns 7 frozen tool`
**What:** CLAUDE.md §6 ("Capabilities you can rely on — These all work TODAY") asserts "`tools/list` returns 7 frozen tool meta records" while the newly linked ADR states the verified 8-tool registration (adr:52; `server/tools.py:207-336` registers search_papers, get_chunk, find_equation, get_definitions, find_lemma_by_name, get_paper, cite_neighbors, lean_verify).
**Why it matters:** §4.8 rule 2 governs "the MCP tool surface" and singles out `lean_verify` — the very tool the host document's own present-tense surface count omits — so the binding doc now contradicts its constitution about the membership of the surface being bound.
**Proposed fix:** Update CLAUDE.md:415 to "returns 8 frozen tool meta records"; optionally annotate the §3 E06 history row ("7-tool surface", CLAUDE.md:82) as at-E06-ship rather than current. Docs-only; the roadmap wont bans only `server/` changes.
**Regression-guard:** Optional (MEDIUM). If ever desired, extend `tests/test_constitution_ui_claims.py` with a count assertion tying the CLAUDE.md claim to `len(ALL_TOOLS)` — defer per R0's enforcement-tooling wont.
**Source critic:** milestone-arxmcp-critic
**Source axis:** MCP spec compliance

**L1 — CLAUDE.md 'make ingest is a stub' contradicts ADR write inventory** (LOW)

**Where:** `CLAUDE.md:462`
**Anchor:** `- **`make ingest`** is a stub that exits`
**What:** CLAUDE.md §7 still lists `make ingest` as "a stub that exits 1 with a redirect" while the ADR's write-surface enumeration (adr:48-49) records it as a real offline ingest CLI — Makefile:188 is the shipped E11_S01 bulk orchestrator, and CLAUDE.md §3 already marks E11 SHIPPED.
**Why it matters:** An agent applying rule 2 needs an accurate inventory of the "offline ingest CLIs" write channel, and the binding doc's stub claim contradicts both the constitution it links and its own status table.
**Proposed fix:** Rewrite the CLAUDE.md:462 bullet to reflect the shipped E11 orchestrator (or delete it from §7 "Known stubs"); one bullet edit, docs-only.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing

**L2 — Rule 2 blesses /ui/ writes without noting the open security audit** (LOW)

**Where:** `.claude/docs/adr-data-plane-boundary.md:68`
**Anchor:** `2. **Writes only via offline ingest or o`
**What:** Rule 2 constitutionalizes the `/ui/` console as one of exactly two legitimate write entry points without recording that the console is not yet security-audited (E13 scoped it out; CLAUDE.md §6 tracks it at chris-dare-dev/arXMCP#9).
**Why it matters:** R1–R7 sessions will cite this rule as write-surface doctrine, and omitting the known audit gap invites reading "operator-gated" as "audited" — a quiet threat-model overstatement.
**Proposed fix:** Add one sentence to rule 2 or the known-ambient-hazards list: "the /ui/ console's security audit remains open (E13 scope-out, chris-dare-dev/arXMCP#9); rule 2 legitimizes the channel, not its current audit state."
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security

**L3 — 'Runs the ingest task in the server process' overstates locality** (LOW)

**Where:** `.claude/docs/adr-data-plane-boundary.md:50`
**Anchor:** `    `/ui/api` (`server/routes/notebooks.`
**What:** The context bullet says POST `…/ingest` "runs the ingest task in the server process", but the route at `server/routes/notebooks.py:2112` spawns a child subprocess supervised by an in-process asyncio task (route docstring: "INSERT row → spawn subprocess task"), so the heavy ingest work executes outside the server process while dispatch, tracking, and status transitions are in-process.
**Why it matters:** Rule 2's own normative wording ("in-process ingest dispatch", adr:71) is accurate, and the context bullet's looser phrasing is the kind of over-claim a future reader can quote against the code — in a document whose value is that its claims verify.
**Proposed fix:** Reword adr:50-52 to "dispatches and supervises the ingest task in the server process (the work runs in a spawned child subprocess) — an operator-gated console action, not an offline one."
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security

**L4 — Mission quotation cited to a note that does not contain it** (LOW)

**Where:** `.claude/docs/adr-data-plane-boundary.md:17`
**Anchor:** `- arXMCP's mission is to be the **substr`
**What:** The quotation "the server returns grounded evidence only; it does not reason, summarize, or mutate state via MCP" is cited to "(server MCP instructions; `.claude/notes/01-mission-and-context.md`)", but the sentence exists only at `server/mcp_instructions.py:48` — the mission note contains neither the sentence nor the phrase "grounded evidence only".
**Why it matters:** Same citable-constitution property as M1, and the quote's real home is a code file the ADR could pin with the file:line precision it uses everywhere else.
**Proposed fix:** Cite `server/mcp_instructions.py:48` for the quotation and keep `.claude/notes/01-mission-and-context.md` as a separate see-also for the substrate framing.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** MCP spec compliance

## What was done well

- Every load-bearing factual citation re-verified exact against code: `server/observability/spend_constants.py:51` import, `server/observability/__init__.py:30` side-effect import, all 11 mutating `/ui/api` route decorators at the exact lines cited (302/466/561/628/756/849/938/1168/1274/1667/2112, mounted at `/ui/api` per `server/main.py:762`), the 8-tool `ALL_TOOLS` registration, `lean_verify.py:290-298` status mapping, `pyproject.toml` `include = ["server*", "ingest*", "tools*", "shim*"]`, and the "~18 offline ingest CLIs" figure (exactly 18 matching scripts under `tools/`).
- `lean_verify` is described accurately on both axes that matter: the bare-status trust gap at :290-298 is real at exactly the cited lines, and no persistence path exists in the handler — "computes; never persists corpus-visible state" is true today and then bound normatively (MUST NOT) for the future, without preempting m3's trust-language scope.
- Rule scoping ("the served process and the `server/` package") explicitly avoids outlawing the `.claude/` agent scaffolding that authored the ADR — the self-reference trap was seen and closed in the text itself.
- The rule-2 carve-out does not weaken the note-08 threat model: it names exactly the operational writes that already exist (retrieval-cache SQLite, logs, metrics, ingest-status transitions, health markers), licenses nothing new, and adds an operator-confirm bound on any future agent-suggested write path.
- Stale upstream claims were retired rather than propagated: the agent-platform plan's "model_selector referenced only by tests" line is corrected with the verified consumer graph, and CLAUDE.md's stale "7-tool surface" was kept out of the new binding text (the residual host-doc staleness is M2, not a defect of the new text).
- Option B was rejected on research-falsified grounds (server imports `tools.*` at runtime at `server/routes/notebooks.py:66-74`; the wheel packages `tools*`) with the loser and its cheaper-day-to-day virtue recorded — exactly what m2's `t-agent-platform-amend` needs to execute.
- Tier sequencing respected end-to-end: all four roadmap wont items honored (docs-only diff, no tool renames, principle-only candidate layer, no enforcement tooling), m2/m3/R7 scope explicitly deferred in a "deliberately NOT decided" list, and no pending-tier infrastructure consumed (`.claude/roadmap/README.md` shows zero ⏳ markers).
- CLAUDE.md §4.8 is purely additive at the renumber-free anchor; I independently re-ran `tests/test_constitution_ui_claims.py` (the only test that parses CLAUDE.md): 28/28 pass; axis 1 (cache byte-stability) is clean — nothing in the diff touches or implies changes to `server/tools.py`, `server/prompts.py`, tool result envelopes, `EXPECTED_TOOL_SCHEMA_SHA256`, or the BP1 hash.
- Commit hygiene exemplary on a dirty tree: hunk-scoped staging kept the pre-existing paper-metadata-m2 modifications out (the range diff contains only the ADR and §4.8), the commit is GPG-signed (status G) with the correct current-model co-author trailer and a conventional subject within limits.
- Axes with nothing to flag are clean rather than fabricated: math fidelity is n/a (no LaTeX/MathML/chunking path exists in a docs-only diff); no-fork is clean (no dependency, submodule, or vendored-code change anywhere in the range); local-first is actively strengthened (candidate-layer data "never leaves this workstation"; the loop repo consumes arXMCP as a local path/git dependency, respecting the no-PyPI-before-R1 interlock).

Severity counts: C0 H0 M2 L4

## Recommended rectification order

M1, M2, L4, L3, L1, L2

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed: <finding ids>
- Deferred: <finding ids>
- Invalidated: <finding ids with reasons>
- Regression tests added: <file paths>
