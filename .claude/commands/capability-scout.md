# /capability-scout

Run the canonical 4-phase arXMCP capability-discovery pipeline:
**Survey (5 parallel scouts) → Synthesize → Challenge → Prioritize**

Usage:
```
/capability-scout                                            # ask for scout id
/capability-scout <id>
/capability-scout <id> --brief "verbatim user scope"
/capability-scout <id> --lean       # 3 scouts only (comparative + adversary + research-frontier)
/capability-scout <id> --deep       # 5 scouts; adversary uses Opus
/capability-scout <id> -- resume from current state
```

`<id>` is a free-form slug.  Convention: date-tagged topic, e.g. `2026q2-retrieval-gap-scan` or `lean-verification-survey-v1`.  If no id is given, STOP and ask: "What scout id should I use?"

The pipeline answers: **"What capabilities should arXMCP build next, given 2026 state-of-the-art in research-math retrieval, scientific-document RAG, MCP tooling, and agentic-mathematics research?"**  It does NOT produce code; it produces a ranked candidate report ready to feed `/roadmap`.

---

## Step 0 — Initialize state

```bash
.claude/scripts/capability-scout/init-scout.sh <ID> [--brief "<verbatim user brief>"]
mkdir -p .claude/agent-memory/capability-scout-comparative \
         .claude/agent-memory/capability-scout-research-frontier \
         .claude/agent-memory/capability-scout-oss-trends \
         .claude/agent-memory/capability-scout-multi-agent \
         .claude/agent-memory/capability-scout-adversary \
         .claude/agent-memory/capability-scout-challenger
```

- If the state file already exists, the script prints `state already exists (phase=X) — resuming`.
- If resuming: run status first, then skip to the appropriate phase below.
- The `mkdir -p` ensures per-agent memory dirs exist; safe to re-run.

```bash
.claude/scripts/capability-scout/status.sh <ID>
```

Read `.claude/references/capability-scout/state-schema.md` only if you need to inspect or write a field that isn't covered by the scripts.

---

## Step 1 — Survey (parallel, 5 scouts in ONE turn)

Read `.claude/references/capability-scout/phase-survey.md` once at phase start.

Set the survey mode (default standard):
```bash
.claude/scripts/capability-scout/checkpoint.py <ID> --set survey_mode='"standard"'
```

Then dispatch all 5 scouts in **one assistant turn** containing 5 `Agent` tool blocks.  Each uses `subagent_type: general-purpose`, sonnet (or Opus on the adversary when `--deep`), `isolation: worktree`.  The canonical prompts live in `.claude/references/capability-scout/agent-prompts.md` — copy verbatim and substitute `{ID}`, `{SCOUT_BRIEF}`, `{BRIEF_PATH}`.

| Scout name (state field) | Brief path |
|---|---|
| `comparative` | `.claude/notes/capability-scouts/<ID>/survey/comparative-brief.md` |
| `research-frontier` | `.claude/notes/capability-scouts/<ID>/survey/research-frontier-brief.md` |
| `oss-trends` | `.claude/notes/capability-scouts/<ID>/survey/oss-trends-brief.md` |
| `multi-agent` | `.claude/notes/capability-scouts/<ID>/survey/multi-agent-brief.md` |
| `adversary` | `.claude/notes/capability-scouts/<ID>/survey/adversary-brief.md` |

Record each dispatch and advance state:
```bash
for scout in comparative research-frontier oss-trends multi-agent adversary; do
  .claude/scripts/capability-scout/checkpoint.py <ID> --append scouts_dispatched="\"$scout\""
done
.claude/scripts/capability-scout/checkpoint.py <ID> survey-running
```

As each scout returns, record:
```bash
.claude/scripts/capability-scout/checkpoint.py <ID> --append scouts_returned='"<scout-name>"'
.claude/scripts/capability-scout/checkpoint.py <ID> --append survey_briefs='"<brief-path>"'
```

When all dispatched scouts have returned:
```bash
.claude/scripts/capability-scout/checkpoint.py <ID> survey-complete
```

---

## Step 2 — Synthesize (main session)

Read `.claude/references/capability-scout/phase-synthesize.md` once at phase start.

```bash
.claude/scripts/capability-scout/checkpoint.py <ID> synthesize-running
```

Read EVERY brief end-to-end.  Build the unified opportunity catalog at:
```
.claude/notes/capability-scouts/<ID>/artifacts/synthesis.md
```

Use the fixed candidate-entry shape and 7-category taxonomy from phase-synthesize.md.  Deduplicate across briefs.  Surface cross-cutting tensions explicitly.

```bash
.claude/scripts/capability-scout/checkpoint.py <ID> --set synthesis_path='".claude/notes/capability-scouts/<ID>/artifacts/synthesis.md"'
.claude/scripts/capability-scout/checkpoint.py <ID> --set candidate_count=<N>
.claude/scripts/capability-scout/checkpoint.py <ID> synthesize-complete
```

---

## Step 3 — Challenge (single sub-agent)

Read `.claude/references/capability-scout/phase-challenge.md` once at phase start.

```bash
.claude/scripts/capability-scout/checkpoint.py <ID> challenge-running
```

Single `Agent` call with `subagent_type: general-purpose`, sonnet, `isolation: worktree`.  Use the canonical Challenger prompt from `agent-prompts.md` verbatim.  Substitute `{ID}`, `{SYNTHESIS_PATH}`, `{CHALLENGE_PATH}`.

The challenger writes to:
```
.claude/notes/capability-scouts/<ID>/artifacts/challenge.md
```

Record:
```bash
.claude/scripts/capability-scout/checkpoint.py <ID> --set challenge_path='".claude/notes/capability-scouts/<ID>/artifacts/challenge.md"'
.claude/scripts/capability-scout/checkpoint.py <ID> --set challenge_finding_counts='{"critical":N_BLOCKER,"high":N_MAJOR,"medium":N_MINOR,"low":N_CLEAN}'
.claude/scripts/capability-scout/checkpoint.py <ID> challenge-complete
```

(The mapping is **BLOCKER → critical, MAJOR → high, MINOR → medium, NONE → low** for state-field consistency with milestone-pipeline.)

---

## Step 4 — Prioritize (main session)

Read `.claude/references/capability-scout/phase-prioritize.md` once at phase start.

```bash
.claude/scripts/capability-scout/checkpoint.py <ID> prioritize-running
```

Run in the **main session** (NOT a sub-agent) — the user reviews this report directly and may iterate on it.

Read synthesis + challenge end-to-end.  Score every candidate via **RICE-light** (Reach 1/3/10 × Impact 0.5/1/3 × Confidence-by-triangulation 0.3–1.0 / Effort-by-tshirt 0.25–8).  Apply challenger penalties (halve on un-redesigned BLOCKER; -25% on MAJOR).  Write:
```
.claude/notes/capability-scouts/<ID>/artifacts/final-report.md
```

with these sections in order:

1. Executive summary (top-3, theme, caveat)
2. Quick-glance ranking table
3. Top-10 in detail (synthesis entry + challenger objections + RICE breakdown)
4. Recommended next steps (`/roadmap` first pick, Spike-lane candidates, parking lot)
5. Honest limitations
6. Cross-reference index

**Always OFFER but NEVER auto-invoke `/roadmap`.**  Include the offer footer when the top-3 candidates have RICE ≥ 3.0; the user types `/roadmap <slug>` if they want to proceed.

Record:
```bash
.claude/scripts/capability-scout/checkpoint.py <ID> --set final_report_path='".claude/notes/capability-scouts/<ID>/artifacts/final-report.md"'
.claude/scripts/capability-scout/checkpoint.py <ID> --set ranked_candidates='[{"id":"CAND-1","title":"Lean verification-trace tool","rice":8.0,"rank":1},...]'
.claude/scripts/capability-scout/checkpoint.py <ID> complete
```

Print a 5-line final summary: scout id, total candidates, top-3 by RICE, BLOCKER count, recommended next step.

---

## State machine

```
init → survey-running → survey-complete
     → synthesize-running → synthesize-complete
     → challenge-running → challenge-complete
     → prioritize-running → complete
```

`status.sh` prints elapsed time per phase and which scouts are still pending.

---

## Common rationalizations (anti-pattern guard)

| Tempting belief | Reality |
|---|---|
| "Skip the adversary scout — the other 4 cover the gaps." | The adversary is the only scout that traverses arXMCP end-to-end.  Without it, every candidate is a "new shiny thing" with no anchor. |
| "Fire scouts one at a time to read each brief as it lands." | Sequential dispatch doubles wall-clock and kills diversity.  ONE turn, 5 tool blocks. |
| "Synthesize from TL;DRs only." | Triangulation lives in matching specific claims across briefs.  Read every brief end-to-end. |
| "Skip the challenger — the synthesis is good enough." | Synthesis is biased toward shiny new capability.  Without an adversary on the synthesis, Phase 4 ranks aspirational candidates blind to architecture-lock cost. |
| "Auto-invoke /roadmap on the top candidate." | NEVER.  Offer-and-wait.  External-write gates are non-negotiable. |
| "Inflate severity to surface more findings." | The challenger's NONE is a credible result.  Padding objections erodes signal. |

---

## Don'ts

- **Don't run Phase 4 as a sub-agent.**  It needs the user's review surface.
- **Don't let the synthesizer write the challenge.**  Synthesis = main session; challenge = sub-agent.  Distinct on purpose.
- **Don't auto-invoke `/roadmap`.**  Offer-and-wait.
- **Don't manufacture candidates.**  Every catalog entry traces to ≥1 survey brief.
- **Don't bypass `scripts/init-scout.sh`.**  State directory naming is load-bearing.
- **Don't `git push` at any phase.**  Scout artifacts live under `.claude/notes/capability-scouts/` — only the downstream `/roadmap` invocation may produce commits.

---

## Sub-agent memory

All `capability-scout-*` agents have `memory: project` in their frontmatter.  Their memory accumulates under `.claude/agent-memory/<agent-name>/` across scout runs.  Do NOT clear or overwrite these directories — they carry institutional memory across scouts (which arXiv categories are richest, which docs carry primary evidence, recurring synthesis blind spots, etc.).

---

## References

Phase references (`phase-survey.md`, `phase-synthesize.md`, `phase-challenge.md`, `phase-prioritize.md`) and the agent-prompts source (`agent-prompts.md`) are all surfaced INLINE at their phase entries — no need to list them here.  Cross-cutting references the phase bodies don't already link:

- `.claude/references/capability-scout/state-schema.md` — `state.json` field reference; read only when inspecting/writing a field beyond what scripts cover
- `.claude/references/capability-scout/source-registry.md` — curated comparable systems / research venues / OSS projects / multi-agent papers (loaded by sub-agents at Phase 1 start, NOT by the main session)
- `CLAUDE.md` §4.7 + §7 + §8 — arXMCP architecture locks, known stubs, and the no-fork policy (the Challenger's checklist axes)
- `.claude/notes/07-multi-agent-caching.md` — BP1/BP2 prompt-cache discipline (Challenger checklist axis #3)
- `.claude/references/milestone-pipeline-critique-format.md` — canonical severity rubric
- `.claude/commands/milestone-pipeline.md` — the build-pipeline this scout feeds via `/roadmap`
- `.claude/commands/roadmap.md` — the roadmap pipeline this scout offers handoff to
