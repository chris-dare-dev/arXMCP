# Canonical sub-agent prompts — frontend-uplift

**Single source of truth: the agent files at `.claude/agents/frontend-uplift-*.md`.**

Each scout / critic / challenger has a dedicated agent definition file. When
the orchestrator dispatches an `Agent` tool block in Phase 1 or Phase 3, it
uses the agent's defined system prompt + a per-run user prompt that supplies
the placeholders below.

This file used to inline all 5 prompts verbatim — but maintaining the same
prompt in two places drifted across runs. The agent files are now the
single source; this file documents only the placeholder contract.

---

## Agent files (one per role)

| Phase | Role | Agent file | Subagent type |
|---|---|---|---|
| 1 | Visual scout | `.claude/agents/frontend-uplift-visual-scout.md` | `frontend-uplift-visual-scout` |
| 1 | Library scout | `.claude/agents/frontend-uplift-library-scout.md` | `frontend-uplift-library-scout` |
| 1 | Inspiration scout | `.claude/agents/frontend-uplift-inspiration-scout.md` | `frontend-uplift-inspiration-scout` |
| 1 | Current-state critic | `.claude/agents/frontend-uplift-current-state-critic.md` | `frontend-uplift-current-state-critic` |
| 3 | Challenger | `.claude/agents/frontend-uplift-challenger.md` | `frontend-uplift-challenger` |

In the slash-command body, dispatch each named agent directly:

```
Agent(
  description: "Visual scout for {ID}",
  subagent_type: "frontend-uplift-visual-scout",
  isolation: "worktree",
  prompt: <the user-prompt block below — see § Placeholder contract>
)
```

## Placeholder contract

Each agent's body refers to placeholders the orchestrator fills in the user
prompt passed to the dispatch:

| Placeholder | When to substitute | Notes |
|---|---|---|
| `{ID}` | every agent | the uplift id passed to `/frontend-uplift` (e.g. `2026q2-jinja-polish`) |
| `{UPLIFT_BRIEF}` | every agent | verbatim user brief; if no `--brief`, the empty string |
| `{BRIEF_PATH}` | the 4 Phase-1 scouts | `.claude/notes/frontend-uplifts/<ID>/discover/<scout-name>-brief.md` |
| `{SCREENSHOT_DIR}` | the visual scout only | `.claude/notes/frontend-uplifts/<ID>/screenshots` |
| `{PAGES}` | the visual scout only | CSV of routes from `--pages`, or empty for the default page set (see `arxmcp-design-system.md` §3) |
| `{SYNTHESIS_PATH}` | the challenger only | `.claude/notes/frontend-uplifts/<ID>/artifacts/synthesis.md` |
| `{CHALLENGE_PATH}` | the challenger only | `.claude/notes/frontend-uplifts/<ID>/artifacts/challenge.md` |

The orchestrator's per-agent user-prompt is typically a few lines providing
context, e.g.:

```
Dispatch the visual scout for {ID}.
Uplift brief:
{UPLIFT_BRIEF}
Write your brief to: {BRIEF_PATH}
Screenshots go to: {SCREENSHOT_DIR}
Routes: {PAGES} (empty = the default page set from arxmcp-design-system.md §3).
```

The agent's own system prompt (in the agent file) contains the structured-brief
format, hard rules, and severity calibration — the user prompt only supplies
the per-run inputs.

## Default page set (visual scout)

When `{PAGES}` is empty, walk the canonical set documented in
`arxmcp-design-system.md` §3. arXMCP's UI is small by design (Jinja2 + vendored
htmx, no SPA, no Node build chain — CLAUDE.md §4.7), so the default is
**3 routes + 1 polling fragment**:

1. `/ui/` — landing
2. `/ui/notebooks/<seeded-slug>` — detail (requires a seeded notebook)
3. `/ui/notebooks/<seeded-slug>/papers/<paper_id>/preview` — ar5iv preview (requires a seeded paper)
4. `/ui/status-badge` — operability fragment

If the target deployment is empty, the visual scout seeds via `POST /ui/api/notebooks`
+ `POST /ui/api/notebooks/<slug>/papers` before walking.
