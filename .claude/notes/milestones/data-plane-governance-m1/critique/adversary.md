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

Severity counts: C0 H0 M3 L5

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
