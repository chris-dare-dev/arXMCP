---
name: handoff
description: Generate rigorous session-handoff documents at a session boundary — a
  CONTINUATION handoff (the next builder session resumes exactly where this one stopped)
  and/or a REVIEW handoff (a high-effort Fable 5 or Opus session runs a principal-engineer
  audit of everything the session shipped across its milestones). Authors against
  the fleet handoff contract (`.claude/references/handoff-contract.md`) so the frontmatter
  is well-formed and the Obsidian vault Handoffs base claims it. Use at session end,
  when context is running long, or when the user says 'handoff', 'wrap up the session',
  'pass this to the next session', or 'get this reviewed'. NOT for milestone execution
  state (/milestone-pipeline owns that) and NOT for durable lessons or preferences
  (that's memory).
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
type: skill
status: active
tags:
- type/skill
- status/active
- project/claude-registry
- type/handoff
- authorship/agent-generated
project: claude-registry
authorship: agent-generated
---

# Handoff — session-boundary continuation + review docs

Author a **continuation** handoff (where to resume) and/or a **review** handoff (an external
audit of what shipped) against the canonical contract in
`.claude/references/handoff-contract.md`. Provider-neutral — works identically from Claude Code,
Codex, and OpenCode; the Obsidian vault surfacing is automatic on machines that have it and
degrades silently everywhere else.

## When NOT to use
- To record a durable lesson or preference — that's memory, not a handoff.
- To advance or close a milestone — `/milestone-pipeline` owns execution state; a handoff only
  *describes* it, and never edits `roadmap.yaml` or a progress journal.
- Mid-task notes for yourself — handoffs are session-boundary artifacts.

## Arguments

`/handoff [continuation|review|both] [slug] [free-text notes]`

- **kind** — omit to decide from the session: shipped milestone-scale work (commits landed across
  ≥1 milestone) → `both`; mid-stream or light session → `continuation` only. Say which you chose
  and why in the final report.
- **slug** — omit to infer from the session's roadmap. This is the `roadmap/1` slug (the `slug:`
  in `plans/<slug>/roadmap.yaml`), used in the filename, `project:` frontmatter, and roadmap link.
- **notes** — anything the user wants emphasized (e.g. "reviewer should focus on the live flip").

## Steps

1. **Read the contract first**: `.claude/references/handoff-contract.md` — filename grammar,
   frontmatter schema, and both body templates. Do not improvise frontmatter keys; legacy variants
   (`type: session-handoff`, `handoff-kind:`) make the doc invisible to the vault Handoffs base.

2. **Resolve the slug + roadmap.** If no slug was given, find the program the session worked on:
   ```bash
   ls plans/*/roadmap.yaml 2>/dev/null
   ```
   Pick the roadmap whose milestones the session touched. The slug is its `slug:` field; the
   roadmap path is `plans/<slug>/roadmap.yaml`. If the repo has no roadmap, still write the
   handoff — use a short kebab slug for the work and omit the `roadmap:` key.

3. **Inventory the session** (this is the substance — be thorough and honest):
   - Repos touched + commit ranges: `git log --oneline <base>..HEAD` in each repo the session
     committed to; note pushed-vs-unpushed.
   - Milestones/epics covered (roadmap ids), and each one's honest state:
     SHIPPED / LIVE / DORMANT / in-flight (CI running, tag-bump pending, …).
   - Live-behavior changes vs dormant (flag-off / not-yet-activated) mechanisms — reviewers and
     resumers both need the split.
   - Open threads, gates awaiting confirmation, landmines discovered (cross-cutting follow-ups).
   - What was verified vs what was claimed-but-not-verified.

4. **Name the file(s).** Into `plans/<slug>/` (create it if absent):
   `HANDOFF-$(date +%Y-%m-%d)-<slug>[-<detail>]-<continuation|session-review>.md`.

5. **Write the handoff(s)** from the contract's templates — continuation §4, review §5 — with the
   full frontmatter schema (§3). Both docs cross-link via `companion:` + a body link. Secrets by
   store path / env-var name only, never a literal value. Review handoffs: every work item gets a
   **What to SCRUTINIZE** subsection, and the final section gives the reviewer diff access
   (repo + branch + SHA range) and the response contract.

6. **Self-check** (no validator ships in this port — check by eye against the contract):
   - `type: handoff` and `handoff_kind:` present and matching the filename suffix;
   - `companion:` on each doc points at the other (when both were written);
   - no literal secret values anywhere;
   - review handoff: every work item has a **What to SCRUTINIZE** block, and §N+3 has the SHA
     ranges + response contract.

7. **Report** to the user:
   - paths written, and which kind(s);
   - the reviewer dispatch instruction (review kind): open a fresh high-effort **Fable 5** or
     **Opus** session, provide the review handoff plus repo access, and ask for the response
     contract defined in the handoff's final section;
   - anything unverified or unresolved you had to leave behind.

## Notes

- **A handoff never writes the roadmap.** In this fleet `roadmap.yaml` has one writer class (the
  roadmap phase agents) and progress lives in append-only journals under
  `plans/<slug>/progress/*.jsonl`. The platform registry's "insert a review checkpoint into the
  roadmap" step is deliberately NOT ported — it would violate the one-writer-per-file rule.
- **Vault surfacing is automatic.** On a machine with the Obsidian vault above the repos, a
  detached hook stamps frontmatter and links the handoff into the Handoffs base from the
  `type: handoff` frontmatter — this skill's only job is correct frontmatter. Machines without the
  vault still get a well-formed markdown handoff.
- One session, one date, one slug → at most one continuation + one review; supersede by writing a
  newer-dated pair, not by editing history.
- When the review verdict later arrives and findings are dispositioned, flip the review handoff's
  `review_status:` to `closed`.
