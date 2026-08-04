
## paper-metadata (2026-07-05)
- Known-stub lists (CLAUDE.md §7) + the newest HANDOFF "not done" section are the fastest evidence sources for a genuinely-pending brief; every claim got a file path.
- Checked candidate briefs against LOCKED spike decisions first — HANDOFF suggested textbook BM25, but notebook-retrieval-m2 spikes locked dense-only as the accuracy ceiling; picking it would have burned the roadmap on a closed question.
- Byte-stability constraints (EXPECTED_TOOL_SCHEMA_SHA256 / BP1) are recurring arXMCP must/should assumptions for any MCP-surface change; encode them as KRs, not just assumptions.
- Single-line briefs only for roadmap-init.py --brief: the scaffold template indents only the first line of the block scalar, so a multi-line brief would emit invalid YAML.

## source-truth (2026-07-11)
- Adjudicated briefs at .claude/roadmap-briefs/R*.md pre-draft HMW/KRs/tiered assumptions; the refiner's job shifts to re-verifying every file:line claim at source (targeted Read with offset + Grep) and adapting to schema shape — not inventing framing. One pre-converged HMW = auto-advance; re-litigating an adjudicated frame is noise.
- Absence-of-column claims verify cheapest by grepping the schema file for the proposed column names (truncated|source_span|printed_number...) — a comment-only hit proves the columns don't exist.
- Cross-track interlocks (trustworthy-release D8-R04 owner ruling, agent-platform W1 tool-schema window) encode as should-tier assumptions whose validation clause names the sequencing fallback (owner-gated milestone; resources-surface-only manifest if W1 slips).
- The tools/list byte-stability pin went into a KR ("make test stays green including the schema-hash pin") per the paper-metadata lesson — validator accepted; keep doing this for any MCP-surface-touching roadmap.
- Reading roadmap-validate.py's goal checks (lines ~116-126) before writing made the validate loop pass first try on both runs.

## data-plane-governance (2026-07-11)
- Adjudicated briefs (.claude/roadmap-briefs/R*.md) arrive with pre-drafted HMW/KRs/assumptions: adapt into schema shape but re-verify every file:line claim anyway — found real drift (brief cited CLAUDE.md section "Hard constraints", which only exists at README.md:135) and encoded the drift as a might-tier assumption instead of copying it into a KR.
- Git-state evidence goes stale as the pipeline itself scaffolds plan dirs: "six untracked plans" grew to eight (data-plane-governance/, source-truth/ scaffolds). Scope disposition KRs to the NAMED pre-existing tracks, never to "zero untracked dirs".
- Docs-only/governance roadmaps still get observable KRs: phrase them as git-state predicates ("git status plans/ shows zero untracked pre-existing tracks") and doc-content predicates ("policy bans X and the R3/R5 gates reference it"), not "write the ADR".
- An alternative HMW beneficiary whose outcome belongs to a downstream track (here R3's honest-trust-signal tool surface, explicitly in this brief's wont) is not a credible reframing — no gate.
- Env header claimed "not a git repo" but git worked; trust `git rev-parse --is-inside-work-tree` over the harness env line before dropping git-state evidence.

## verification-contract (2026-08-03)
- Adjudicated R3 brief's file:line citations had gone stale between authoring (2026-07-11) and refine (2026-08-03) because an unrelated landed milestone (axiom_audit, issues #205/#281/#332) inserted ~450 lines into `server/handlers/lean_verify.py` above the cited block. Re-grepping for the cited *behavior* (`status = "ok"`, `#check`/`maxHeartbeats 5000` wrapping) found the same logic at new line numbers — always re-verify line numbers even when the brief is otherwise fully trusted, not just the existence of the claim.
- Orchestrator supplied an explicit "current-state correction" in the dispatch prompt (axiom_audit partially closed the founding soundness case). Folded it into evidence as its own bullet rather than editing the brief's KRs/wont — the correction updates *understanding of current reality*, not the track's scope, so it belongs in evidence, not in objective/key_results.
- Cross-track "inherited finding" pointers (F7, owned by this track's m7 but with its telemetry half already shipped standalone in `lean-repl-observability-m1`) satisfy the "do not drop it" instruction by citing the standalone doc in evidence AND keeping the brief's own KR8 wording (which already names the gauge dependency) verbatim — no need to invent a 9th KR.
- Multi-must-tier brief (2 must + 2 should) with pre-written validation clauses ports directly into schema shape with no rewriting needed; roadmap-validate.py's `goal` check only inspects must-tier for a non-empty `validation`, so should-tier validation strings are good practice but not enforced — kept them anyway per the phase-refine reference's stronger guidance.
