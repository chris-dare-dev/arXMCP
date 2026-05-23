# Phase 3 — CHALLENGE (sub-agent)

**Purpose:** dispatch a single sub-agent (the Challenger) to argue AGAINST each candidate in the synthesis catalog so Phase 4 prioritization receives honest feasibility signal.  This is the analog of the milestone-pipeline's Phase 3 adversary critique — except it critiques PROPOSED capabilities, not shipped code.

## Inputs

- `.claude/notes/capability-scouts/{ID}/artifacts/synthesis.md`
- (Optional) the 5 survey briefs for ground-checking — challenger reads these when it suspects a synthesis claim drifted from its source.

## Output

`.claude/notes/capability-scouts/{ID}/artifacts/challenge.md`

## Dispatch

Single `Agent` call with `subagent_type: general-purpose`, `model: sonnet` (no Opus override — the challenger workload fits comfortably in Sonnet's context).  Use `isolation: worktree` for repo-read isolation.

Use the canonical Challenger prompt from `references/capability-scout/agent-prompts.md` verbatim.  Substitute:
- `{ID}` → scout id
- `{SYNTHESIS_PATH}` → `.claude/notes/capability-scouts/{ID}/artifacts/synthesis.md`
- `{CHALLENGE_PATH}` → `.claude/notes/capability-scouts/{ID}/artifacts/challenge.md`

## Severity rubric (Challenger-specific)

The challenger uses a 4-tier rubric distinct from the standard CRITICAL/HIGH/MEDIUM/LOW critique format:

| Challenger tier | Maps to standard critique severity | Meaning |
|---|---|---|
| **BLOCKER** | CRITICAL | Candidate must be dropped or fundamentally redesigned (architecture-lock violation, infeasible compute, no-fork-incompatible OSS, breaks the MCP protocol pin).  Rare — calibrate carefully. |
| **MAJOR** | HIGH | Candidate is shippable but with a significant cost the synthesis didn't surface (cache-discipline collision needing redesign, eval-quality regression risk, effort under-estimated by ≥2x). |
| **MINOR** | MEDIUM | Candidate is shippable with light scope adjustment (env-var clamp missing, doc-placement drift, snippet-contract field naming). |
| **NONE** | n/a | Candidate survives the gauntlet cleanly. |

The orchestrator maps these to the standard format when populating `state.challenge_finding_counts` for the final report.

## The 10-axis CHALLENGER checklist

Every candidate gets evaluated against these axes.  arXMCP's hard architectural constraints live in `CLAUDE.md §4.7` (coding conventions) and `§8` (gotchas) and the design constitution under `.claude/notes/` — quote those by filename, do not paraphrase.

1. **Architecture-lock compatibility** — does it violate an arXMCP hard rule?  Specifically: `assert` banned for invariants (`CLAUDE.md §4.7`); pure-ASGI middleware only (`BaseHTTPMiddleware` banned); no `anthropic` SDK at runtime (the server is a tool provider, not an LLM caller); `server/` source never references `claude-opus`.
2. **No-fork policy** — does the candidate require importing or forking an existing `arxiv-mcp` repo or other external code?  `CLAUDE.md §8`: ideas, not code.  An OSS reference is study-only.
3. **Prompt-cache discipline (BP1/BP2)** — does it touch `tools/list` byte-stability, the role-prefix breakpoints in `server/prompts.py`, or the `EXPECTED_*_SHA256` pins?  See `.claude/notes/07-multi-agent-caching.md` and `.claude/notes/prompts-bp-discipline.md`.  A cache-prefix change is a real cost.
4. **MCP tool-surface contract** — does it add or change an MCP tool?  Adding a tool means re-pinning `EXPECTED_TOOL_SCHEMA_SHA256` (`CLAUDE.md §9`), and any new snippet-bearing result must honor the 150-char snippet contract (`.claude/docs/snippet-contract.md`).
5. **Local-first / single-workstation** — does it introduce a distributed-systems dependency, a non-loopback bind, or network egress beyond the corpus-ingest path?  `server/config.py::reject_non_loopback` is a hard guard.
6. **Doc-placement discipline** — do the candidate's artifacts respect the `CLAUDE.md §1` rule (Markdown only in allowed locations; everything agent-internal under `.claude/`)?
7. **Retrieval-quality regression** — does the candidate risk regressing nDCG@5 / Recall@10 on the eval harness (`make eval`)?  Does it need an eval-fixture update or re-curation per `.claude/docs/eval-curation.md`?
8. **Effort honesty** — is the candidate's effort estimate plausible?  Compare to arXMCP's historical milestone sizing (E-epic milestones `E<NN>_S<MM>` are typically S–M; epics that shipped 10 milestones like E13 were L).  Flag candidates that under-estimate.
9. **Value density** — does the candidate's value justify its scope?  A 6-week candidate with marginal value is a worse use of capacity than a 1-week candidate with comparable value.  Weigh against arXMCP's stated philosophy that the valuable LLM roles live UPSTREAM of verification (`CLAUDE.md §2` — "Lean kernel is the better critic"), so retrieval/pre-loading investment generally beats adversarial-LLM-critique investment.
10. **Sequencing dependencies** — does this candidate depend on another candidate, or on resolving a known stub (`cite_neighbors` handler, `make ingest` driver, the `papers` metadata table — all in `CLAUDE.md §7`)?  Should the catalog flag the DAG?

## After receiving the challenge

Parse the challenge to populate:

```bash
.claude/scripts/capability-scout/checkpoint.py <ID> --set challenge_path='".claude/notes/capability-scouts/<ID>/artifacts/challenge.md"'
.claude/scripts/capability-scout/checkpoint.py <ID> --set challenge_finding_counts='{"critical": N_BLOCKER, "high": N_MAJOR, "medium": N_MINOR, "low": N_CLEAN}'
.claude/scripts/capability-scout/checkpoint.py <ID> challenge-complete
```

## Anti-patterns

| Tempting belief | Reality |
|---|---|
| ">50% of candidates have MAJOR or BLOCKER objections — the synthesis was bad." | Possible.  Usually means the challenger prompt is too aggressive OR the synthesis under-considered architecture-lock constraints.  Re-read the challenge with that lens before re-running. |
| "Every candidate gets at least a MINOR objection — that's calibration." | No.  Padding objections is noise.  A clean candidate gets NONE.  If the challenger emits 0 NONEs the calibration is broken. |
| "BLOCKER findings should kill candidates outright." | Not always.  A BLOCKER + a credible redesign sketch leaves Phase 4 deciding whether the redesigned candidate is worth pursuing. |
| "The challenger should propose its own candidates." | No.  Phase 1's job.  The challenger evaluates the synthesis; it does not extend it. |
