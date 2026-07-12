# Rectify disposition — data-plane-governance-m1

**Rectifier:** milestone-rectifier (Phase-4 exception delegate; implementer ran inline in main session)
**Rect commit:** `910e93906b49876b2df150206e0af31c68d960ee` — `rect(data-plane-governance-m1): close M1-M5, L1-L3` (GPG `%G?=G`; trailers: Reviewed-by milestone-adversary-critic, milestone-arxmcp-critic; Co-Authored-By Claude Fable 5)
**Diff:** 2 files, +20/−14 (`CLAUDE.md`, `.claude/docs/adr-data-plane-boundary.md`) — docs-only; test-delta rule exempt
**Re-verification:** every acted-on finding anchor matched live text exactly (W=10 prose window; 0 drift, 0 invalidated → invalidation rate 0%, well under the 40% stale-critique threshold)
**Attempts/caps:** 1 attempt per finding; 1 gate round; no escalation

Line numbers below are worktree-relative (CLAUDE.md carries an `obsidian-strip`
clean filter: worktree runs +22 lines vs the committed blob — frontmatter + trailing
Obsidian links; committed positions are per the commit's hunk headers).

## Dispositions

| id | verdict | resolution (for findings.py set, verbatim) | file:line touched |
|----|---------|--------------------------------------------|-------------------|
| M1 | fixed | CLAUDE.md 4.8 scope sentence now reads "the served process, the server/ package, and the shipped distribution", matching ADR Decision 1; rect 910e939 | CLAUDE.md:256-258 |
| M2 | fixed | ADR Decision 2 quote reattributed to R0-data-plane-governance.md:16 (grep of the cited source now resolves) with "restated as briefs-README standing policy 1"; rect 910e939 | .claude/docs/adr-data-plane-boundary.md:87-94 |
| M3 | fixed | CLAUDE.md 4.3 co-author-trailer mandate made model-agnostic in bullet and heredoc example (Co-Authored-By: authoring Claude model); no signed commit rewritten; rect 910e939 | CLAUDE.md:144-148, 170 |
| M4 | fixed | same edit as M2 (dedup cluster) plus the Decision-3 qualification: the "model policy" living outside is dispatch-time policy while the inert model_selector lookup table stays in-repo; rect 910e939 | .claude/docs/adr-data-plane-boundary.md:87-94 |
| M5 | fixed | CLAUDE.md 6 tools/list count corrected 7 to 8 (re-verified live: ALL_TOOLS in server/tools.py registers exactly 8 tools incl. lean_verify, in both HEAD and worktree); rect 910e939 | CLAUDE.md:418 |
| L1 | fixed | ADR:88 false adverb removed: "R0 explicitly defers enforcement tooling" now "R0 scopes this track to documents + git state, deferring enforcement tooling", matching R0's actual wont; fixed with M2 (same editing session, cross-critic cluster L1+M2+M4); rect 910e939 | .claude/docs/adr-data-plane-boundary.md:88 |
| L2 | fixed | CLAUDE.md 4.8 rule 1 guard-test cite scoped to the import half (tests/test_langfuse_doc.py greps server/ imports only); pyproject half marked convention-only, enforcement tooling deferred per the ADR; fixed with M1 (same 4.8 editing session); rect 910e939 | CLAUDE.md:263-267 |
| L3 | fixed | CLAUDE.md 4.8 rot-prone spend_constants.py:51 line pin dropped (module name kept; the dated ADR record retains :51); fixed with M1 (same 4.8 editing session); rect 910e939 | CLAUDE.md:279 |
| L4 | deferred | LOW deferred by policy; M5 fixed the present-tense 6 claim; the remaining 7-tool mentions (CLAUDE.md:82 at-E06-ship history row, :306 layout comment) go to the pending paper-metadata-m2 docs-sync per the critique's own proposed disposition | — |
| L5 | deferred | LOW deferred; record-only per the finding (no retroactive amend of the signed feat commit); the optional 4.3 note on long-slug-id subject overflow is left to the owner docs-sync | — |
| L6 | deferred | LOW deferred; the make-ingest bullet sits in CLAUDE.md 7 directly beside the uncommitted paper-metadata-m2 hunk owned by another session — editing there would entangle hunk-scoped staging with work that is not this milestone's to commit | — |
| L7 | deferred | LOW deferred; recording the open /ui/ security-audit caveat in ADR rule 2 is a normative threat-model addition better owned by the m3 trust-language milestone or the #9 audit follow-up than a rect one-liner | — |
| L8 | deferred | LOW deferred; context-bullet precision only — rule 2's own normative wording ("in-process ingest dispatch") is accurate per the critic; reword ADR:50-52 in a docs-sync | — |
| L9 | deferred | LOW deferred; mission-quote citation polish at ADR:17 (true home server/mcp_instructions.py:48); the two quote-fidelity MEDIUMs are fixed, this see-also refinement goes to the docs-sync | — |

Invalidated: none.

## Fix-selection rationale

- Severity policy applied: no CRITICAL/HIGH existed; all five MEDIUMs were 1–3-line
  doc-scoped corrections (well under the 30-LOC cap) → fixed.
- LOW default is defer. Three LOWs (L1, L2, L3) were taken under the trivially-cheap-
  and-adjacent exception: they sit inside the exact regions the MEDIUM fixes edit, and
  the deduped critique's "Recommended rectification order" itself bundles them
  ("M1+L2+L3 are one CLAUDE.md 4.8 editing session; M2+L1 are one ADR editing session";
  L1+M2+M4 is the cross-critic agreement cluster). L4–L9 deferred with reasons above.

## Verification detail (per acted-on finding)

- M1: ADR:57-58 confirmed "(and the shipped distribution)"; CLAUDE.md 4.8 scope lacked it.
- M2/M4: `grep -rn "live outside" .claude/roadmap-briefs/` → exactly one hit,
  R0-data-plane-governance.md:16; briefs-README standing policy 1 wording differs.
- M3: CLAUDE.md 4.3 mandated the literal `Claude Opus 4.7 (1M context)`; last 8 commits
  use `Claude Opus 4.8` / `Claude Fable 5` — stale mandate confirmed. Both occurrences
  (bullet :157, heredoc example :169, pre-fix numbering) updated.
- M5: `server/tools.py` ALL_TOOLS = 8 ToolMeta entries in HEAD and worktree.
- L1: R0 wont section names only no-server-code / no-renames / no-TheoremGraph-decision;
  "enforcement" appears nowhere in R0.
- L2: `TestNoServerSideAnthropic` greps `^(from anthropic|import anthropic)` under
  server/ only; no pyproject-dep check exists in the test file.
- L3: anchor matched; pin dropped from the living doc only.
- Constitution-test pins checked before editing: `tests/test_constitution_ui_claims.py`
  pins the stale-UI-phrase absence, `/ui/` + operator-console mentions, and the
  "Browser UI surface" cross-reference — none intersect the edited lines.

## Check gate results (docs-only scope per dispatch)

- `./.venv/Scripts/python.exe -m ruff check .` → **PASS** ("All checks passed!")
- `./.venv/Scripts/python.exe -m pytest tests/test_constitution_ui_claims.py -q --tb=short -p no:warnings` → **PASS** (28/28)
- Full suite: SKIP per dispatch — 68 pre-existing dirty-tree failures are attributed in
  `implement/synthesis.md` and are not this milestone's.
- Regression tests added: none (doc-only rect; exempt from the test-delta rule).

## Staging integrity (pre-dirty tree)

- CLAUDE.md fixes staged hunk-scoped: `git diff CLAUDE.md` → split via content-marker
  filter (dropped the one hunk containing `metadata_status=`) → `git apply --cached`.
- Verified pre-commit: staged diff = 5 rect hunks only; verified post-commit: worktree
  residue = exactly the one pre-existing paper-metadata-m2 7 hunk (`@@ -442,11 +442,14`),
  byte-preserved and uncommitted. No other pre-dirty file touched or staged.
- ADR was clean pre-edit; staged whole-file.

## external_writes_required (NOT executed here)

- `git push origin main` (main is now 3 ahead of origin/main: cfb7c27 feat-roadmap,
  90a1049 feat, 910e939 rect) — parked in state for the main session's Phase-4d gate.

## Not done here (main-session responsibilities)

- No `findings.py set` calls (register writes are the orchestrator's).
- No state.json / checkpoint writes, no roadmap.yaml or progress-journal edits.
- No push/publish/deploy.
