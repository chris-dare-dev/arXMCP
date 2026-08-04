
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

## verification-contract (2026-08-03)
- Third consecutive arXMCP roadmap validator-clean on arrival at Phase 4 — upstream single-session phases keep making this gate a formality; still run it first.
- When the orchestrator hands a rich, pre-vetted link list with explicit per-item hints (e.g. "docX.md (m1, m3)"), honor the hints literally rather than inferring broader placement — several epics (e2-e6) and one milestone (m6) legitimately got zero links because no hint named them; resist the urge to backfill "for symmetry".
- For a doc with no item hint at all in the dispatch (evidence-ledger-standard.md here), the defensible move was co-locating it with its paired governance doc (trust-language-policy.md) on the milestone that authors schema-conforming docs — not inventing a new epic-level slot.
- goal.evidence citing bare `arXiv:YYMM.NNNNN` (no scheme) should be normalized to `https://arxiv.org/abs/YYMM.NNNNN` for links.url — validator does not enforce a URL format but full URLs match the style of every other url: entry in this repo's roadmaps.
- Existing spike items already carried a links.note pointing at `goal.assumptions[N] (...)` prose (not a real path) from an earlier phase — left those untouched rather than overwriting; links blocks accumulate across phases, this phase only adds.
- `roadmap-init.py --advance complete` re-emits the file but preserved all 12 links: blocks (5 pre-existing from spikes/decompose-phase + 7 written this phase) — grep count before/after advance is a cheap confirmation the rewrite didn't drop anything.
