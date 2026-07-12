
## paper-metadata (2026-07-05)
- Arrived with validator already exit 0 — the per-phase validate-after-every-write loop upstream means the Phase-4 gate is a formality when phases were run in one session.
- Reliable link sources in arXMCP: the pattern file an epic mirrors (server/notebooks_store.py), the handler it rewires (server/handlers/paper.py), and the hash-pin test it must not break (tests/test_server_tool_schema.py) — all verified via ls before writing.
- Neither refiner nor materializer scope-bounds sanction writing the generated_by/generations header fields shown in roadmap-example.yaml; skipped them (validator does not require them) — registry should either drop them from the golden example or assign a writer.

## source-truth (2026-07-11)
- Second consecutive arXMCP roadmap to arrive validator-clean at Phase 4 — single-session upstream phases make the entry gate a formality; still run it first, it costs one command.
- When an epic has exactly one milestone, don't mirror the milestone's code list onto the epic — differentiate (epic got the migration-precedent pair ingest/schema.py + ingest/store.py:330; m2 kept the full 4-path set). paper-metadata house style: epic and milestone links diverge.
- Line-anchored links (path:NNN / path:NNN-MMM) verify with one Grep per symbol; store.py:330, chunker.py:406-418, license_policy.py:44-53 all held exactly.
- .claude/roadmap-briefs/R<N>-<slug>.md is a reliable note: anchor for the foundation epic; skip plans/*/roadmap.yaml cross-track refs in links: — goal.evidence already carries them, links stay sparse.
- Spike-note wikilinks authored upstream ("[[<slug> spike-N ...]]") are the sanctioned to-be-created-by-spike form — leave them untouched rather than converting to paths.

## data-plane-governance (2026-07-11)
- Second consecutive roadmap arriving validator-clean (exit 0 on arrival): when all four phases run in one session, the Phase-4 gate is a formality — budget effort for links, not validation debugging.
- Governance/docs-only roadmaps create files that do not exist yet (.claude/docs/adr-*.md, trust-language-policy.md) — those target paths must NOT go in links.code; link instead the verified evidence anchors the items read or amend: server/handlers/lean_verify.py, server/orchestrator/model_selector.py, plans/agent-platform/roadmap.yaml, root CLAUDE.md/README.md, and .claude/roadmap-briefs/*.md (all Glob-confirmed).
- External-repo evidence without a URL (stability-mflds rigor.py) gets no url: link — goal.evidence carrying only a prose pointer is not a copyable URL; never invent one.
- roadmap-init.py --advance rewrites roadmap.yaml (comment on the phase line is preserved but the file is re-emitted) — do all links/status Edits BEFORE advancing, then re-validate once after; Edit anchors may not survive the rewrite.
- Dependency order for the handoff offer: when m2 and m3 both depend only on m1 (m2 also via spike-1), file order == sequenced order is the correct tiebreak; target_end confirms it.
