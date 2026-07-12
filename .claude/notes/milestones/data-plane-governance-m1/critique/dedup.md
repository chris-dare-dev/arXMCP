# Merged critique — data-plane-governance-m1 (dedup input)

Severity counts: C0 H0 M5 L9

Sources: adversary.md (ids unchanged: M1-M3, L1-L5), arxmcp.md (ids remapped: M1->M4, M2->M5, L1->L6, L2->L7, L3->L8, L4->L9).

---

# Critique — data-plane-governance-m1 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** cfb7c270ff7d3fabccdcde65bd6a0f5af2dcf2cb..90a10492558d65cdbb3f2d58cd4c9747c9718329
**Diff stats:** 2 files, 204 LOC (+204/−0: `.claude/docs/adr-data-plane-boundary.md` new 172; `CLAUDE.md` +32)
**Critique format version:** 1.0

Note: the dispatch prompt's head SHA (`…c97180ef`) does not exist in this repo; the
range above is state.json's `implementation_commit_range` (`…c9718329` = HEAD, matching
the described 2-file diff). CLAUDE.md line numbers below are worktree-relative — they run
+11 vs the committed file because of the uncommitted Obsidian frontmatter documented in
`preflight-deviation.md`; every finding also carries a verbatim Anchor.

## Verdict

SHIP-WITH-FIXES

The diff meets all three acceptance criteria, and every checkable file:line claim in the
ADR verified true against the code this session (status mapping, import chains, route
census, packaging, header locations). The three MEDIUMs are one-to-three-line
documentation-precision fixes: the binding CLAUDE.md short form drops the ADR's
shipped-distribution scope qualifier, the ADR misattributes a verbatim quote, and the
milestone commit's co-author trailer diverges from §4.3's stale mandated literal. Nothing
rises to a contract violation or an unmet acceptance criterion.

## Executive summary

- [MEDIUM] CLAUDE.md §4.8's scope line omits the ADR's "(and the shipped distribution)"
  qualifier — the auto-loaded binding text is narrower than the constitution it
  summarizes, leaving a wheel-shipped agent runner under `tools/` letter-compliant
  (CLAUDE.md:255).
- [MEDIUM] The ADR attributes the verbatim quote "agents, run memory, and model policy
  live outside" to the briefs-README standing policy; the words exist only at
  `R0-data-plane-governance.md:16` and the README's policy 1 reads differently (ADR:91).
- [MEDIUM] The milestone commit's trailer (`Claude Fable 5`) does not match the exact
  trailer CLAUDE.md §4.3 mandates (`Claude Opus 4.7 (1M context)`) — a stale doc mandate
  every recent commit violates, unfixed by a milestone whose theme is CLAUDE.md
  bindingness (CLAUDE.md:157).
- [LOW] Three precision nits in the new binding text: "R0 explicitly defers enforcement
  tooling" overstates R0's wont (ADR:88, ADR:150); the guard-test parenthetical implies
  pyproject-dep coverage no test provides (CLAUDE.md:262); §4.8 hardcodes the rot-prone
  `spend_constants.py:51` pin in a living doc (CLAUDE.md:276).
- [LOW] Adjacent, pre-existing: CLAUDE.md's three "7-tool" claims (:82, :306, :415) now
  sit in the same constitution set as an ADR correctly asserting 8 tools; plus the feat
  subject omits the milestone id that §4.3's template and recent precedent carry.

## Findings

**M1 — CLAUDE.md §4.8 scope drops the ADR's shipped-distribution clause** (MEDIUM)

**Where:** `CLAUDE.md:255`
**Anchor:** `(data-plane-governance-m1, Accepted 2026`
**What:** The binding short form says "Scope: the served process and the `server/` package." while ADR Decision 1 scopes the rules to "the served process and the `server/` package **(and the shipped distribution)**" — the qualifier that makes a `tools/`-resident agent loop in-scope.
**Why it matters:** CLAUDE.md is the text auto-loaded into every session; under its letter a non-orchestrator agent runner under `tools/` (which ships in the wheel per `pyproject.toml:20` and is server-imported at `server/routes/notebooks.py:66-74`) that avoids the `anthropic` SDK violates no §4.8 rule, while violating the ADR it summarizes — exactly the conventional-not-structural gap the ADR exists to close.
**Proposed fix:** One-line edit to CLAUDE.md §4.8's scope sentence: "Scope: the served process, the `server/` package, and the shipped distribution." No renumbering, no constitution-test phrase touched.
**Regression-guard:** None required now (R0 wont defers enforcement tooling); if a consuming track adds boundary lint, pin the phrase "shipped distribution" in both §4.8 and the ADR.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**M2 — ADR misattributes a verbatim quote to the briefs README** (MEDIUM)

**Where:** `.claude/docs/adr-data-plane-boundary.md:91`
**Anchor:** `  briefs-README standing policy ("agents`
**What:** Decision 2 cites 'the briefs-README standing policy ("agents, run memory, and model policy live outside")', but that quoted string appears only in `.claude/roadmap-briefs/R0-data-plane-governance.md:16`; the README's standing policy 1 reads "The server never runs agents, never holds per-run agent memory, and takes writes only through offline/operator-gated ingest."
**Why it matters:** This is a citation-grade constitution document R1–R7 will quote; a grep-verification of the attributed source returns zero hits, eroding trust in the ADR's other citations (the exact failure class research brief-2 risk 5 warned against).
**Proposed fix:** Reattribute the quote to the R0 brief (`R0-data-plane-governance.md:16`), or keep the README attribution and quote its actual standing-policy-1 wording. One line.
**Regression-guard:** None (doc citation fix); verify with `grep -rn "live outside" .claude/roadmap-briefs/` resolving to the cited file.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness (factual claims)

**M3 — Commit trailer diverges from §4.3's mandated literal string** (MEDIUM)

**Where:** `CLAUDE.md:157`
**Anchor:** `  Co-Authored-By: Claude Opus 4.7 (1M co`
**What:** The milestone commit (90a1049) carries `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` while CLAUDE.md §4.3 states the co-author trailer "is mandatory on every commit" and gives exactly one string, `Claude Opus 4.7 (1M context)` — a literal no recent commit uses (prior commits use `Claude Opus 4.8`, then `Claude Fable 5`).
**Why it matters:** A milestone whose deliverable is "CLAUDE.md as binding constitution" ships via a commit that violates the letter of the binding doc's own commit rule, and the stale mandate keeps generating this ambiguity every milestone (the prior critique cycle hit the adjacent unsigned-commit-waiver gap).
**Proposed fix:** Do not rewrite the signed commit. Fix the doc side: amend §4.3's trailer bullet to be model-agnostic, e.g. "Co-author trailer naming the actual authoring model is mandatory: `Co-Authored-By: <authoring Claude model> <noreply@anthropic.com>`" (≤3 LOC). Flagging severity honestly: the trailer IS present and credits the real model, and research brief-2 AC7 pre-cleared the Fable 5 string as "stale precedent, not a pin" — this is doc drift, not the CRITICAL missing-trailer analog.
**Regression-guard:** None; future commits self-check via `git log --format='%(trailers:key=Co-Authored-By)'` against the amended wording.
**Source critic:** milestone-adversary-critic
**Source axis:** Commit hygiene

**L1 — ADR says R0 "explicitly defers enforcement tooling"; R0 never does** (LOW)

**Where:** `.claude/docs/adr-data-plane-boundary.md:88`
**Anchor:** `  (R0 explicitly defers enforcement tool`
**What:** Decision 2 claims "(R0 explicitly defers enforcement tooling)" and the Consequences section files enforcement tooling under "per R0 wont" (ADR:150), but R0's wont section (`R0-data-plane-governance.md:55-60`) names only no-`server/`-code, no tool renames, and no TheoremGraph/Matlas decisions — the tooling deferral is a sound inference from "this track is documents + git state", not an explicit statement.
**Why it matters:** A reader grepping R0 for "enforcement" finds nothing, so the adverb "explicitly" mildly overstates the source in a document whose value is quote-fidelity.
**Proposed fix:** Drop "explicitly" (or rephrase: "R0 scopes this track to documents + git state, deferring enforcement tooling"). One word to one line.
**Regression-guard:** Optional at this severity.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness (factual claims)

**L2 — Guard-test cite implies pyproject coverage that no test provides** (LOW)

**Where:** `CLAUDE.md:262`
**Anchor:** `   rule; guard test: `tests/test_langfu`
**What:** §4.8 rule 1 states a two-part requirement (SDK out of `server/` imports AND out of `pyproject.toml` runtime deps) and names "guard test: `tests/test_langfuse_doc.py`", but `TestNoServerSideAnthropic` (tests/test_langfuse_doc.py:183-207) greps `server/` imports only — nothing anywhere tests pyproject deps for `anthropic`.
**Why it matters:** A future session adding `anthropic` to pyproject (e.g. for a `tools/` CLI) can run the named guard, see green, and conclude rule 1 holds; the ADR itself is honest about this ("the existing **server-scoped** SDK-ban test stays sufficient as-is") but the short form lost the nuance.
**Proposed fix:** Qualify the parenthetical: "guard test for the import half: `tests/test_langfuse_doc.py`; the pyproject half is currently convention-only (enforcement tooling deferred per the ADR)". ~1 line. Flagged as a judgment call: the existing sentence is defensible if read carefully ("one mechanism of this rule"), so this is precision hardening, not an error.
**Regression-guard:** Optional at this severity.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**L3 — Binding §4.8 hardcodes a rot-prone spend_constants.py line pin** (LOW)

**Where:** `CLAUDE.md:276`
**Anchor:** `   the `spend_constants.py:51` runtime `
**What:** The living, binding CLAUDE.md duplicates the ADR's dated snapshot pin `spend_constants.py:51`; any future edit above line 51 of that module makes the binding text state a wrong line while the ADR (correctly, as a dated record) keeps it.
**Why it matters:** Line-pin rot in CLAUDE.md §4.8 creates a false-fact irritation in the exact section future sessions are told is binding, for zero informational gain over "recorded in the ADR".
**Proposed fix:** Drop the line number in CLAUDE.md only: "its real consumer set — including the `spend_constants.py` runtime import — is recorded in the ADR". The ADR keeps `:51` (verified correct today).
**Regression-guard:** Optional at this severity.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**L4 — Stale "7-tool surface" now contradicts the ADR's 8-tool census** (LOW)

**Where:** `CLAUDE.md:82`
**Anchor:** `| E06 — MCP server | ✅ SHIPPED | FastAPI`
**What:** Pre-existing committed text claims a 7-tool surface three times (CLAUDE.md:82, :306 "7-tool registration", :415 "returns 7 frozen tool meta records") while the newly-referenced constitution ADR correctly records 8 tools (verified: `server/tools.py:207-336` registers exactly 8, incl. `lean_verify`).
**Why it matters:** The diff deliberately (and correctly, per research guidance) avoided copying the stale count into §4.8, but linking the ADR from CLAUDE.md makes the intra-file contradiction live for every reader; recorded as ADJACENT pre-existing drift, not a defect of this diff — defer to a docs-sync commit if not fixed here (≤3 LOC).
**Proposed fix:** Update the three counts to 8 (and "7-tool registration" in the §5 layout listing) in a `docs(repo)` sync, or leave to the pending paper-metadata-m2 doc-sync session that already owns CLAUDE.md staleness.
**Regression-guard:** Optional at this severity.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**L5 — feat subject omits the milestone id the §4.3 template carries** (LOW)

**Where:** no specific file
**Anchor:** `feat(repo): data-plane boundary ADR + CLAUDE.md 4.8`
**What:** §4.3's three-commit pattern shows `feat(<scope>): <topic> (E<NN>_S<MM>)` and recent slug-era precedent follows it ("feat(tools): metadata backfill CLI (paper-metadata-m1)", "feat(infra): k3s deploy manifests (k3s-rancher-deploy-m1)"), but 90a1049's subject carries no "(data-plane-governance-m1)".
**Why it matters:** `git log --oneline --grep=<milestone-id>` misses the feat commit by subject (the id does appear on body line 1, so full-message grep still finds it); appending the id would have blown the ≤50-char rule the same section mandates — the two §4.3 rules conflict for long slug ids.
**Proposed fix:** Nothing retroactive (commit is signed; do not amend). Optionally note in §4.3 that for long slug ids the milestone id goes on body line 1 instead of the subject — which is what this commit did.
**Regression-guard:** Optional at this severity.
**Source critic:** milestone-adversary-critic
**Source axis:** Commit hygiene

## What was done well

- Every load-bearing citation in the ADR verified exact this session: `server/handlers/lean_verify.py:290-298` status mapping (verbatim logic match), `server/observability/spend_constants.py:51` → `server/observability/__init__.py:30` runtime import chain, all 11 mutating `/ui/api` routes (:302–:2112), the 8-tool `ALL_TOOLS` census (`server/tools.py:207-336`), `pyproject.toml:20` packaging of `tools*`, and the two distinct "Hard constraints" headers (`README.md:135`, `.claude/notes/README.md:20`).
- The lean_verify claim survives adversarial reading: the handler contains zero persistence (no file, sqlite, or cache writes anywhere in `server/handlers/lean_verify.py`), so "computes; never persists corpus-visible state" is fact today, not just norm.
- The ADR actively retires upstream errors instead of propagating them — the "referenced only by tests" model_selector claim is replaced with the verified consumer graph, and the stale "7-tool surface" count was kept OUT of the new binding text per research guidance.
- Option B was rejected on verified structural grounds (runtime `tools.*` imports at `server/routes/notebooks.py:66-74`; wheel packaging), recorded with rationale and the owner's values call — giving m2's `t-agent-platform-amend` something concrete to cite.
- Hunk-scoped staging held under a dirty tree: the commit contains only the §4.8 hunk; the pre-existing paper-metadata-m2 §7 hunk remains uncommitted and byte-identical (re-verified: sole remaining CLAUDE.md worktree hunk is the documented §7 one).
- Constitution-test discipline: additive-only, zero renumbering, stale phrase not reintroduced; `tests/test_constitution_ui_claims.py` passes (re-run this session).
- Commit hygiene beyond the trailer nit: GPG-signed (%G?=G — the prior milestone's unsigned-commit deviation did not recur), conventional `feat(repo)` subject ≤50 chars, heredoc body, milestone id on body line 1.
- Check-gate attribution done right: 68 dirty-tree pytest failures attributed with BOTH mechanistic (no failing test reads the two markdown files) and empirical evidence (the F2 pair reproduced at baseline cfb7c27 in a clean worktree, root-caused to the Windows path bug at `tests/test_model_selector.py:424` with a one-line fix proposed as owner follow-up).
- External-write boundary honored: nothing pushed (`main` is 2 ahead of `origin/main`); `git push origin main` is parked in `external_writes_required` for the Phase-4d gate exactly as brief-2 reasoned.
- The scope carve-outs are self-consistent rather than rule-swallowing: dev-time `.claude/` agent scaffolding exempted (the ADR would otherwise outlaw the pipeline that authored it), the operational-writes carve-out is enumerated and category-bounded, and the in-process `/ui/` ingest route (:2112, via `IngestTaskTracker` on app.state) is correctly classified as an operator-gated console action rather than "offline".



## Cross-critic agreement

The following findings cluster within 5 lines of each other in the same file. Multiple critics flagged the same area - these are the strongest signals to fix first.

- **L1, M2, M4** at `.claude/docs/adr-data-plane-boundary.md:88-91` (MEDIUM): ADR says R0 "explicitly defers enforcement tooling"; R0 never does; ADR misattributes a verbatim quote to the briefs README; ADR misattributes its standing-policy quotation to the briefs README

## Recommended rectification order

M1, M2, M3, L2, L3, L1, L4, L5

(M1+L2+L3 are one CLAUDE.md §4.8 editing session; M2+L1 are one ADR editing session —
note the ADR's approval record says post-critique rectifications are recorded by the rect
commit, not by re-opening the record; M3 is a §4.3 amendment; L4 may be deferred to the
pending paper-metadata-m2 docs-sync; L5 is record-only.)

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:


---

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

**M4 — ADR misattributes its standing-policy quotation to the briefs README** (MEDIUM)

**Where:** `.claude/docs/adr-data-plane-boundary.md:91`
**Anchor:** `  briefs-README standing policy ("agents`
**What:** Decision 2 attributes the quotation "agents, run memory, and model policy live outside" to "the briefs-README standing policy", but that string exists only at `.claude/roadmap-briefs/R0-data-plane-governance.md:16` — the briefs README's standing policy 1 uses different wording ("The server never runs agents, never holds per-run agent memory, and takes writes only through offline/operator-gated ingest").
**Why it matters:** The milestone's product is a citable constitution, and a reader who greps the named source for the quoted words finds nothing — the repo's first ADR would teach future sessions that its citations do not verify.
**Proposed fix:** Re-attribute the quotation to `R0-data-plane-governance.md:16` (e.g. "...matches the adjudicated gap-analysis recommendation and R0's framing ('agents, run memory, and model policy live outside', R0-data-plane-governance.md:16), restated as briefs-README standing policy 1"). While editing, qualify the "model policy" clause against Decision 3 — dispatch-time policy decisions live outside; the inert `model_selector` lookup table stays in-repo — so the quoted words and Decision 3 cannot be read as contradicting.
**Regression-guard:** Optional (MEDIUM). A quotes-verify doc-lint would brush against R0's no-enforcement-tooling wont; cheapest guard is a one-line re-verify item on m3's checklist when §4.9 lands.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing

**M5 — CLAUDE.md claims a 7-tool surface; the linked ADR records 8** (MEDIUM)

**Where:** `CLAUDE.md:415`
**Anchor:** `- **`tools/list`** returns 7 frozen tool`
**What:** CLAUDE.md §6 ("Capabilities you can rely on — These all work TODAY") asserts "`tools/list` returns 7 frozen tool meta records" while the newly linked ADR states the verified 8-tool registration (adr:52; `server/tools.py:207-336` registers search_papers, get_chunk, find_equation, get_definitions, find_lemma_by_name, get_paper, cite_neighbors, lean_verify).
**Why it matters:** §4.8 rule 2 governs "the MCP tool surface" and singles out `lean_verify` — the very tool the host document's own present-tense surface count omits — so the binding doc now contradicts its constitution about the membership of the surface being bound.
**Proposed fix:** Update CLAUDE.md:415 to "returns 8 frozen tool meta records"; optionally annotate the §3 E06 history row ("7-tool surface", CLAUDE.md:82) as at-E06-ship rather than current. Docs-only; the roadmap wont bans only `server/` changes.
**Regression-guard:** Optional (MEDIUM). If ever desired, extend `tests/test_constitution_ui_claims.py` with a count assertion tying the CLAUDE.md claim to `len(ALL_TOOLS)` — defer per R0's enforcement-tooling wont.
**Source critic:** milestone-arxmcp-critic
**Source axis:** MCP spec compliance

**L6 — CLAUDE.md 'make ingest is a stub' contradicts ADR write inventory** (LOW)

**Where:** `CLAUDE.md:462`
**Anchor:** `- **`make ingest`** is a stub that exits`
**What:** CLAUDE.md §7 still lists `make ingest` as "a stub that exits 1 with a redirect" while the ADR's write-surface enumeration (adr:48-49) records it as a real offline ingest CLI — Makefile:188 is the shipped E11_S01 bulk orchestrator, and CLAUDE.md §3 already marks E11 SHIPPED.
**Why it matters:** An agent applying rule 2 needs an accurate inventory of the "offline ingest CLIs" write channel, and the binding doc's stub claim contradicts both the constitution it links and its own status table.
**Proposed fix:** Rewrite the CLAUDE.md:462 bullet to reflect the shipped E11 orchestrator (or delete it from §7 "Known stubs"); one bullet edit, docs-only.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing

**L7 — Rule 2 blesses /ui/ writes without noting the open security audit** (LOW)

**Where:** `.claude/docs/adr-data-plane-boundary.md:68`
**Anchor:** `2. **Writes only via offline ingest or o`
**What:** Rule 2 constitutionalizes the `/ui/` console as one of exactly two legitimate write entry points without recording that the console is not yet security-audited (E13 scoped it out; CLAUDE.md §6 tracks it at chris-dare-dev/arXMCP#9).
**Why it matters:** R1–R7 sessions will cite this rule as write-surface doctrine, and omitting the known audit gap invites reading "operator-gated" as "audited" — a quiet threat-model overstatement.
**Proposed fix:** Add one sentence to rule 2 or the known-ambient-hazards list: "the /ui/ console's security audit remains open (E13 scope-out, chris-dare-dev/arXMCP#9); rule 2 legitimizes the channel, not its current audit state."
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security

**L8 — 'Runs the ingest task in the server process' overstates locality** (LOW)

**Where:** `.claude/docs/adr-data-plane-boundary.md:50`
**Anchor:** `    `/ui/api` (`server/routes/notebooks.`
**What:** The context bullet says POST `…/ingest` "runs the ingest task in the server process", but the route at `server/routes/notebooks.py:2112` spawns a child subprocess supervised by an in-process asyncio task (route docstring: "INSERT row → spawn subprocess task"), so the heavy ingest work executes outside the server process while dispatch, tracking, and status transitions are in-process.
**Why it matters:** Rule 2's own normative wording ("in-process ingest dispatch", adr:71) is accurate, and the context bullet's looser phrasing is the kind of over-claim a future reader can quote against the code — in a document whose value is that its claims verify.
**Proposed fix:** Reword adr:50-52 to "dispatches and supervises the ingest task in the server process (the work runs in a spawned child subprocess) — an operator-gated console action, not an offline one."
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security

**L9 — Mission quotation cited to a note that does not contain it** (LOW)

**Where:** `.claude/docs/adr-data-plane-boundary.md:17`
**Anchor:** `- arXMCP's mission is to be the **substr`
**What:** The quotation "the server returns grounded evidence only; it does not reason, summarize, or mutate state via MCP" is cited to "(server MCP instructions; `.claude/notes/01-mission-and-context.md`)", but the sentence exists only at `server/mcp_instructions.py:48` — the mission note contains neither the sentence nor the phrase "grounded evidence only".
**Why it matters:** Same citable-constitution property as M4, and the quote's real home is a code file the ADR could pin with the file:line precision it uses everywhere else.
**Proposed fix:** Cite `server/mcp_instructions.py:48` for the quotation and keep `.claude/notes/01-mission-and-context.md` as a separate see-also for the substrate framing.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** MCP spec compliance

## What was done well

- Every load-bearing factual citation re-verified exact against code: `server/observability/spend_constants.py:51` import, `server/observability/__init__.py:30` side-effect import, all 11 mutating `/ui/api` route decorators at the exact lines cited (302/466/561/628/756/849/938/1168/1274/1667/2112, mounted at `/ui/api` per `server/main.py:762`), the 8-tool `ALL_TOOLS` registration, `lean_verify.py:290-298` status mapping, `pyproject.toml` `include = ["server*", "ingest*", "tools*", "shim*"]`, and the "~18 offline ingest CLIs" figure (exactly 18 matching scripts under `tools/`).
- `lean_verify` is described accurately on both axes that matter: the bare-status trust gap at :290-298 is real at exactly the cited lines, and no persistence path exists in the handler — "computes; never persists corpus-visible state" is true today and then bound normatively (MUST NOT) for the future, without preempting m3's trust-language scope.
- Rule scoping ("the served process and the `server/` package") explicitly avoids outlawing the `.claude/` agent scaffolding that authored the ADR — the self-reference trap was seen and closed in the text itself.
- The rule-2 carve-out does not weaken the note-08 threat model: it names exactly the operational writes that already exist (retrieval-cache SQLite, logs, metrics, ingest-status transitions, health markers), licenses nothing new, and adds an operator-confirm bound on any future agent-suggested write path.
- Stale upstream claims were retired rather than propagated: the agent-platform plan's "model_selector referenced only by tests" line is corrected with the verified consumer graph, and CLAUDE.md's stale "7-tool surface" was kept out of the new binding text (the residual host-doc staleness is M5, not a defect of the new text).
- Option B was rejected on research-falsified grounds (server imports `tools.*` at runtime at `server/routes/notebooks.py:66-74`; the wheel packages `tools*`) with the loser and its cheaper-day-to-day virtue recorded — exactly what m2's `t-agent-platform-amend` needs to execute.
- Tier sequencing respected end-to-end: all four roadmap wont items honored (docs-only diff, no tool renames, principle-only candidate layer, no enforcement tooling), m2/m3/R7 scope explicitly deferred in a "deliberately NOT decided" list, and no pending-tier infrastructure consumed (`.claude/roadmap/README.md` shows zero ⏳ markers).
- CLAUDE.md §4.8 is purely additive at the renumber-free anchor; I independently re-ran `tests/test_constitution_ui_claims.py` (the only test that parses CLAUDE.md): 28/28 pass; axis 1 (cache byte-stability) is clean — nothing in the diff touches or implies changes to `server/tools.py`, `server/prompts.py`, tool result envelopes, `EXPECTED_TOOL_SCHEMA_SHA256`, or the BP1 hash.
- Commit hygiene exemplary on a dirty tree: hunk-scoped staging kept the pre-existing paper-metadata-m2 modifications out (the range diff contains only the ADR and §4.8), the commit is GPG-signed (status G) with the correct current-model co-author trailer and a conventional subject within limits.
- Axes with nothing to flag are clean rather than fabricated: math fidelity is n/a (no LaTeX/MathML/chunking path exists in a docs-only diff); no-fork is clean (no dependency, submodule, or vendored-code change anywhere in the range); local-first is actively strengthened (candidate-layer data "never leaves this workstation"; the loop repo consumes arXMCP as a local path/git dependency, respecting the no-PyPI-before-R1 interlock).


## Recommended rectification order

M4, M5, L9, L8, L6, L7

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed: <finding ids>
- Deferred: <finding ids>
- Invalidated: <finding ids with reasons>
- Regression tests added: <file paths>
