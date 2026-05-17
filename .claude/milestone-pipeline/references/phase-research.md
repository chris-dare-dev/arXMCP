# Phase 1 — Research

**State precondition:** `state.phase == "init"` (or already `research-running`
on resume).

**State postcondition:** `state.phase == "research-complete"`,
`state.research_briefs` populated, `state.research_synthesis` points at the
merged-brief file, `state.external_writes_required` initially populated by
the researchers.

## Step-by-step

1. Read once at phase start:
   - This file
   - `references/agent-prompts.md` (extract the Researcher prompt for the
     active mode)
2. Pick the research mode:
   - **Standard** (default): 2× Sonnet `general-purpose` agents in parallel,
     each in `isolation: worktree`.
   - **Deep** (`--deep`): 1× Opus `general-purpose` agent. No worktree
     (read-only research; the worktree is for implementers, not readers).
   - **Single** (`--single`): 1× Sonnet `general-purpose` agent. For very
     small milestones where two passes would be wasted budget.
3. Update state to `research-running`:
   ```bash
   checkpoint.py {ID} research-running
   checkpoint.py {ID} --set 'research_mode="standard"'  # or "deep" / "single"
   ```
4. Compute output paths:
   ```
   <repo-root>/.claude/notes/milestones/{ID}/research-brief-1.md
   <repo-root>/.claude/notes/milestones/{ID}/research-brief-2.md   # standard mode only
   ```
5. **Dispatch ALL researchers in ONE assistant turn** (multiple Agent tool
   calls in the same response). Sequential dispatch defeats parallelism.
   For each researcher: substitute `{ID}`, `{MILESTONE_BRIEF}`,
   `{BRIEF_PATH}`, `{REPO_ROOT}` into the Researcher prompt from
   `agent-prompts.md` and pass it verbatim.
6. Each researcher returns only `{path, status, summary}`. Read the briefs
   from disk on demand — never paste their content into the channel.
7. Merge the briefs (orchestrator, in main session — NOT a sub-agent) into:
   ```
   <repo-root>/.claude/notes/milestones/{ID}/research-synthesis.md
   ```
   Merge rules:
   - Quote — don't paraphrase — anything load-bearing.
   - Where the two briefs disagree, surface BOTH positions and pick one
     with reasoning. Do not silently average.
   - Combine the "External writes the implementation will require" lists
     into a deduped union.
8. Persist state:
   ```bash
   checkpoint.py {ID} --set 'research_briefs=[{...},{...}]'
   checkpoint.py {ID} --set 'research_synthesis="<abs path>"'
   checkpoint.py {ID} --set 'external_writes_required=[{...}]'
   checkpoint.py {ID} research-complete
   ```

## Hard rules

- **Single assistant turn for parallel dispatch.** This is a load-bearing
  rule from `addyosmani/agent-skills` (`references/orchestration-patterns.md`,
  Pattern 3). Two Agent calls in two consecutive turns serialize.
- **Merge happens in the main session.** Per addyosmani, an extra
  "summarizer" sub-agent between fan-out and merge doubles cost and loses
  nuance. The orchestrator merges directly.
- **Researchers do not read each other's output.** They write to declared
  paths; only the orchestrator reads.
- **Researchers do not write code.** They are read-only; if a researcher
  proposes a code change inline, the merge step strips it.
- **External writes are flagged here, not skipped.** Phase 4 reads the
  `external_writes_required` list and gates on user authorization.

## Don'ts

- Don't run a third "synthesizer" sub-agent that paraphrases the
  researchers. That's the meta-summarizer anti-pattern. Synthesis = main
  session.
- Don't echo brief contents through the message channel. The summary
  field is `≤ 3 lines × 80 chars`. The orchestrator opens the file when
  it needs the full text.
- Don't dispatch researchers without an assigned brief path. Two
  researchers writing to the same path is data loss.
- Don't skip the "External writes" section in the merged synthesis. An
  empty list means the milestone is purely local — say so explicitly so
  Phase 4 has nothing to gate.
