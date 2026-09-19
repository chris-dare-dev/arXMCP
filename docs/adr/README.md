# Architecture Decision Records (ADRs)

Decision records for the Stage-2 build-out (2026-07), ratifying the
gating decisions D1–D9 from the Stage-1 synthesis
(`_pipeline/stage-1-discovery/synthesis/workstreams.md` §1, outside this
repo) plus the third-repo extraction triggers. Recorded here per WS-0's
mandate: "record the D1 ADR, D2–D9 decisions, and the third-repo
extraction triggers in the repos' constitutional documents."

**Status semantics:** every ADR below is *Accepted (provisional)* — the
decisions were closed by the Stage-2 orchestrator under the owner's
standing brief (`_pipeline/stage-2-build/ORCHESTRATOR-DECISIONS.md`),
are grounded in Stage-1 evidence, and remain open to owner veto. Each
records its veto/fallback path.

Agent-facing constitutional context lives in `CLAUDE.md` (§4.7 links
here) and `.claude/notes/`; these ADRs are the durable, operator-facing
record.

| ADR | Decision | One-liner |
|---|---|---|
| [0001](0001-build-time-node-vite-allowed.md) | D1 | Node/Vite allowed **build-time only**; every runtime invariant preserved |
| [0002](0002-contracts-live-in-arxmcp.md) | D2 | Bridge-contract ownership moves to arXMCP (`contracts/`, producer-owns-contract) |
| [0003](0003-no-third-repo-now.md) | D3 | No third repo now; exploration pipelines live in `.claude/` interim |
| [0004](0004-spa-lives-in-arxmcp.md) | D4 | The `/app` SPA lives in this repo (`frontend-app/` → static `dist/`) |
| [0005](0005-capability-gating-call-time-denial.md) | D5 | Capability gating is call-time behavioral denial — never `tools/list` filtering |
| [0006](0006-design-language-technical-editorial.md) | D6 | Design language = Technical Editorial; no external design-system artifacts are vendored |
| [0007](0007-math-rendering-two-track.md) | D7 | Math rendering is two-track: MathML Core (stored docs) + KaTeX (chunk text) |
| [0008](0008-retrieval-contract-dense-only.md) | D8 | Retrieval contract pinned `dense_only`; hybrid re-opens only on new measured verdict |
| [0009](0009-proving-verdict-taxonomy.md) | D9 | Proving outputs use the five-verdict taxonomy, abstained-by-default |
| [0010](0010-third-repo-extraction-triggers.md) | — | The four extraction triggers for a future `math-research-orchestrator` repo |
