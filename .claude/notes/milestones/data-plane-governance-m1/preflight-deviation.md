# Preflight deviation — data-plane-governance-m1 (2026-07-11)

The pipeline preflight requires `git status --porcelain` empty. At init, the working
tree carried pre-existing uncommitted state from prior sessions, NOT from this run:

- Real content modifications documenting paper-metadata-m2 as shipped (CLAUDE.md §7
  get_paper hydration, README.md, docs/* runbooks, HANDOFF.md, two milestone
  state.json files, milestone-agent MEMORY.md files, capability-scout files).
- Six untracked plan directories (agent-platform, evidence-engine,
  researcher-workbench, retrieval-unlocks, scale-ops-hardening, trustworthy-release)
  — dispositioning these IS milestone m2 of this very roadmap; committing them here
  would preempt the owner decision.
- Assorted stat/CRLF churn on tracked markdown (empty `git diff` bodies).

Decision (orchestrator): proceed with a documented deviation rather than commit
another session's half-landed work under this milestone's name.

Mitigations:
1. This session's own pre-pipeline artifacts were committed separately (cfb7c27)
   before init, so the milestone diff range `implementation_base..HEAD` contains
   only m1 work.
2. Post-commit cleanliness checks are scoped to paths m1 touches; the pre-existing
   modifications are left byte-identical (verified by re-running
   `git status --porcelain` and diffing the file list against the init-time list).
3. The check gate (ruff + pytest) runs on the tree as-is; if failures appear, they
   are attributed against a pre-m1 baseline before any fix is attempted — unrelated
   failures are surfaced, not fixed, under this milestone.

Owner follow-up (surfaced in the final summary): commit or disposition the
pre-existing paper-metadata-m2 working-tree state in its own session.
