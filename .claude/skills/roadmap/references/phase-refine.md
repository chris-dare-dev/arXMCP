# Phase 1 — Refine

**Status sentinel:** `<!-- status: pending -->` under `## Phase 1 — Refine`. Delete it when this phase writes content.

**State postcondition:** REFINE section populated with How-Might-We, sharpening questions, assumption tiers, Objective + 3–5 KRs, and Won't list. No `{{TOKEN}}` placeholders remaining in the Refine section.

## Step-by-step

1. **Read once at phase start:** this file and `references/anti-patterns.md`. Discard from working memory after writing the Refine section.
2. **Acquire the brief.** Three sources, in priority order:
   - `--brief "..."` flag passed to the skill — explicit wins.
   - Conversation summary (the orchestrator has the transcript) — when invoked mid-conversation, summarize in 2–4 sentences and confirm with the user before proceeding.
   - **Cold-start fallback** — when there is no conversation and no `--brief`, ask 3–5 sharpening questions à la addyosmani's `idea-refine`. Wait for answers. Then summarize the answers as the brief.
3. **Reframe as How-Might-We.** Format: `How might we [desired outcome] for [specific user] without [key constraint]?` Verify against the goodness checklist:
   - Narrow enough to be actionable
   - Broad enough to allow multiple solutions
   - Contains a tension or constraint
   - NOT solution-embedded ("how might we build a chatbot" — too narrow)
   - NOT vague ("how might we make users happy" — too broad)
4. **Sharpening questions.** Even with a brief, write 3–5 sharpening questions and answer them from in-context evidence (the brief, the conversation, files in `.claude/notes/` and the project source). When evidence runs out, ask the user.
5. **Surface assumptions in three tiers.** Use the bracket markers — `validate-roadmap.py` parses them.
   - `[MUST]` — dealbreakers. Wrong = the idea fails. Each `[MUST]` must be validated by Phase 4 OR have a SEQUENCE-phase Spike scheduled.
   - `[SHOULD]` — significantly affects success but doesn't kill it. Wrong = adjust approach. Design a fallback in DECOMPOSE.
   - `[MIGHT]` — secondary. Wrong = small impact. Defer validation.
6. **Write Objective + Key Results.** One Objective, qualitative + aspirational, action-oriented. 3–5 outcome-shaped KRs ("p95 latency < 2s on 50-paper corpus"), not output-shaped ("ship the cache layer"). Validate each KR against SMART (Specific, Measurable, Time-related at minimum).
7. **Write the Won't list.** Explicit out-of-scope items. Aim for 3–8. The skill's effectiveness is the things it doesn't do.
8. **Delete the `<!-- status: pending -->` sentinel** under `## Phase 1 — Refine`. Edit the roadmap file to insert the populated content.

## Auto-advance vs gate — decision table

| condition | action |
|---|---|
| HMW reframe is unambiguous, KRs are measurable, all assumptions tiered | **auto-advance** to DECOMPOSE |
| Brief is irreducibly vague after one sharpening pass (multiple credible interpretations remain) | **GATE** — surface 2–3 interpretations, ask user to pick or refine |
| User answered fewer than 3 sharpening questions (skipped them) | **GATE** — confirm before advancing; skipped questions are the most common source of bad roadmaps |
| All assumptions are `[MIGHT]` or all are `[MUST]` | **soft warning** — re-tier; mono-tier assumptions usually mean tiers weren't applied |

The gate is a fast keystroke: print the options as numbered, accept `1/2/3` or `n` for none. Cache stays warm.

## Hard rules

- **REFINE always runs.** Even when the user provides a polished brief. Reason: REFINE *also* surfaces assumptions and the Won't list, which most briefs lack.
- **HMW format is fixed.** Deviating breaks the readability of the doc and the lint script's expectations.
- **No outputs about decomposition or sequencing here.** Tempting to write epics in the brief; resist. DECOMPOSE phase owns that.
- **Cold-start fallback is mandatory.** If there's no conversation and no `--brief`, asking sharpening questions is the right move. Do not invent a brief.
- **The Won't list is non-negotiable.** A roadmap without a Won't list is a wishlist.

## Don'ts

- Don't write more than 5 sharpening questions. The signal-to-noise of question 6+ is poor.
- Don't tier all assumptions `[MUST]`. The tier system collapses; same failure mode as All-Must MoSCoW.
- Don't skip the user-confirmation step when summarizing the conversation as a brief. The agent's summary is *not* ground truth for the user's intent.
- Don't mix Objective and KR. Objective is the *why*, qualitative; KRs are the *did-it-happen*, measurable.
- Don't paste large quotes from `.claude/notes/` into the Refine section. Cite by filename. The roadmap doc is meant to be readable as a whole.

## Output template (substitute into `plans/<slug>-roadmap.md`)

```
## Phase 1 — Refine

### How Might We

How might we <desired outcome> for <specific user> without <key constraint>?

### Sharpening questions answered

1. **<question>** — <answer, 1–2 sentences with citation if from notes>
2. ...

### Assumptions

- `[MUST]` <assumption>
- `[SHOULD]` <assumption>
- `[MIGHT]` <assumption>

### Objective

<qualitative, aspirational, action-oriented>

### Key Results

1. <measurable + time-bound>
2. ...

### Won't (explicit out-of-scope)

- <thing>
- <thing>
```
