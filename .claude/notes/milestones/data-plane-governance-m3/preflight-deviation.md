# Phase 0 preflight deviation — data-plane-governance-m3

**Recorded:** 2026-07-12 · **Init HEAD:** `23b8628` · **Lock:** taken

## The deviation

`milestone-pipeline.md` Phase 0 requires a clean working tree
(`git status --porcelain` empty). At m3 init the tree was **dirty**. Proceeding
with the deviation on record rather than committing unrelated work or blocking —
identical posture to the `data-plane-governance-m1` preflight deviation, and
consistent with the documented recurring pattern on this workstation (concurrent
sessions land commits mid-work; an Obsidian frontmatter stamper habitually
re-stamps `docs/*` and `plans/*.md`).

## What was dirty at init (none of it is m3's)

**Modified (19, all the Obsidian frontmatter stamper):**
- `README.md`, `docs/README.md`, `docs/api.md`, `docs/architecture.md`,
  `docs/evaluation.md`, `docs/install.md`, `docs/observability/README.md`,
  `docs/ops/README.md`, `docs/releasing.md`, `docs/support.md`, `docs/usage.md`
- `plans/*.md` (corpus-integrity-completion, corpus-integrity-observability,
  notebook-ops-hardening, notebook-paper-discovery, notebook-surface-expansion,
  proof-verify-handler-wiring, textbook-ingest, ui-attractive-polish,
  verification-feedback)

**Untracked:**
- The **six untracked plan dirs** (`plans/agent-platform`, `evidence-engine`,
  `researcher-workbench`, `retrieval-unlocks`, `scale-ops-hardening`,
  `trustworthy-release`) — **`data-plane-governance-m2`'s scope. Do not touch.**
- `.agents/`, `.codex/`, `AGENTS.md` (Codex mirror scaffolding)
- `.claude/agent-memory/milestone-*/` (sub-agent project memory — append-only)
- `.claude/launch.json`, `.claude/notes/notebooks/`, `var/` (gitignored data tree)
- `.claude/notes/HANDOFF-2026-07-12-proof-discovery-program.md` (this program's handoff)
- `.claude/notes/milestones/data-plane-governance-m1/staging-all.patch` (m1 scratch)

## Why the deviation is safe

Every file m3 writes is **clean at init** — verified by pathspec:
- `git status --porcelain -- CLAUDE.md` → empty (the §4.9 amendment lands clean;
  the committed `## Related notes (Obsidian)` trailer is tracked, not pending)
- `git status --porcelain -- .claude/docs/` → empty (new `trust-language-policy.md`
  and `evidence-ledger-standard.md` are clean additions)
- `git status --porcelain -- .claude/roadmap-briefs/` → empty (R0/R3/R5 census +
  cross-ref edits land clean)

So m3's diff cannot entangle with the pre-existing dirt.

## Commit discipline for this milestone

- **Explicit pathspecs only** (`git commit -F - -- <paths>`). Never `git add -A` /
  `git add .` — that would sweep the Obsidian stamps, the six m2-scope plan dirs,
  and the Codex mirror into an m3 commit.
- **Re-check target-file cleanliness immediately before each commit** — the
  Obsidian stamper may re-stamp `CLAUDE.md` concurrently; if it does, hunk-scope
  the §4.9 addition (as m1 did for §4.8).
- **Re-fetch + re-verify ancestry before any push** (external-write boundary;
  concurrent sessions push to `main` here).
