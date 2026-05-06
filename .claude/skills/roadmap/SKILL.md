---
name: roadmap
description: Refines a vague feature brief into a sequenced, prioritized roadmap document at `plans/<slug>-roadmap.md`. Runs four internal phases (refine, decompose, sequence, materialize), produces milestones with IDs `<slug>-mN` consumable by milestone-pipeline, and optionally emits per-issue GitHub body files plus a copy-paste `create-tickets.sh` when `--github` is passed. Use when planning a new feature epic, when an existing brief needs sequencing into milestones, or when the user asks for a roadmap, plan, or task breakdown. Do not use for trivial single-issue work or for milestones already scoped in `.claude/roadmap/`.
---

# roadmap

Take a problem statement (or a summary of the current conversation) and
produce a structured roadmap that pairs cleanly with `milestone-pipeline`
for execution. Four phases: **REFINE → DECOMPOSE → SEQUENCE → MATERIALIZE**.

## When to use

- Planning a new feature epic, sub-area expansion, or focused initiative
  that needs decomposition + sequencing before execution.
- An existing brief needs to be sharpened, sliced, prioritized, and
  shaped into milestones.
- The user asks for a "roadmap," "plan," or "task breakdown."

## When NOT to use

- Trivial one-issue work — just do it.
- Milestones already scoped in [.claude/roadmap/](.claude/roadmap/) (the
  master roadmap with EXX_SYY IDs) — those go straight to
  `milestone-pipeline`.
- Math-content review or sketcher → autoformalizer pipelines — see
  [01-mission-and-context.md](.claude/notes/01-mission-and-context.md);
  the adversarial-critic role is structurally different there.

## Inputs

```
roadmap <slug> [--brief "text"] [--title "human title"] [--github] [--repo-root /path]
```

- `<slug>` — roadmap identifier; regex `^[a-z][a-z0-9-]{2,30}$`, must NOT match `^e\d+$` (collides with `EXX_SYY` epic IDs).
- `--brief` — explicit brief text. If omitted: orchestrator summarizes the conversation in 2–4 sentences (and confirms with the user). If no conversation either, falls back to asking 3–5 sharpening questions à la addyosmani's `idea-refine`.
- `--title` — human-readable title for the doc header. Defaults to slug.
- `--github` — at MATERIALIZE end, bundle per-issue body files plus a copy-paste `create-tickets.sh` script. The skill **never** invokes `gh` itself.
- `--repo-root` — override repo-root detection (env `REPO_ROOT` also honored; falls back to `git rev-parse` and walking up from the script dir).

## The four phases

| phase | does | output |
|---|---|---|
| 1 — REFINE | How-Might-We reframe; sharpening Q&A; assumption tiers `[MUST]`/`[SHOULD]`/`[MIGHT]`; OKR (Objective + 3–5 KRs); Won't list | populated `## Phase 1 — Refine` section |
| 2 — DECOMPOSE | technique pick (default: vertical slicing); 2–6 epics ≤ 6 weeks; INVEST notes; specialist suggestion per epic | populated `## Phase 2 — Decompose` section |
| 3 — SEQUENCE | MoSCoW (Must ≤ 60% via `score-moscow.py`); RICE rank Musts; Now/Next/Later; Spike lane (one per `[MUST]`); Now-lane milestones with G/W/T or bullet AC | populated `## Phase 3 — Sequence` section |
| 4 — MATERIALIZE | `validate-roadmap.py`; record Must-cap; if `--github`: write `plans/<slug>-tickets/` bundle + `create-tickets.sh`; print handoff message | populated `## Phase 4 — Materialize` section + optional bundle |

The roadmap doc IS the state. Re-invoking the skill on a partially
populated roadmap reads the doc, finds the first phase whose
`<!-- status: pending -->` sentinel is present, and resumes there.

## Skill layout

```
.claude/skills/roadmap/
├── SKILL.md                       # this file — orchestrator only
├── references/
│   ├── phase-refine.md            # Phase 1 detail
│   ├── phase-decompose.md         # Phase 2 detail
│   ├── phase-sequence.md          # Phase 3 detail
│   ├── phase-materialize.md       # Phase 4 detail
│   ├── frameworks.md              # long-tail, organized by trigger
│   ├── anti-patterns.md           # 12 anti-patterns + skill-specific
│   ├── arxmcp-integration.md      # project conventions, milestone-pipeline pairing
│   ├── specialist-contracts.md    # 5 specialist contracts (no agents yet)
│   └── templates/
│       ├── roadmap.md             # plans/<slug>-roadmap.md template
│       ├── epic-issue.md          # GitHub epic body template
│       └── story-issue.md         # GitHub story body template
└── scripts/
    ├── init-roadmap.sh            # idempotent scaffold; resume on re-run
    ├── score-rice.py              # RICE ranking + --example
    ├── score-moscow.py            # Must-cap validator + --example/--example-fail
    └── validate-roadmap.py        # roadmap.md linter
```

## Orchestration model — single-thread, gated forward-only

The skill is **single-thread** — it does not spawn sub-agents. addyosmani's
planning skills (`idea-refine`, `planning-and-task-breakdown`,
`spec-driven-development`) follow the same pattern: planning is well-served
by single-pass synthesis with file-handoff between phases. Avoiding
fan-out keeps the prompt cache cheap.

**Gating discipline.** Each phase auto-advances when its output is
unambiguous. Three named contested-fork triggers stop the skill and ask
the user (each gate is a fast keystroke — `y/n` or numbered options — so
the prompt cache stays warm across the pause):

1. **REFINE-vague** — brief is irreducibly vague after one sharpening pass; multiple credible interpretations remain.
2. **DECOMPOSE-fork** — two architecturally divergent decomposition cuts of comparable merit (e.g. split-by-data-tier vs split-by-protocol).
3. **SEQUENCE-cap** — Must-list breaches the 60% cap and trimming is contested.

Otherwise, auto-advance. Each phase's reference file has a full
decision table.

**External-write boundary.** The skill writes ONLY to the local `plans/`
directory. It NEVER invokes `gh`, `git push`, or any network operation.
Per [arxmcp-integration.md](references/arxmcp-integration.md), ticket
creation is manual: `--github` writes a bundle + script the user runs.

## State recovery

The roadmap doc is the state file:

- Each `## Phase N — <name>` section starts with `<!-- status: pending -->`.
- When a phase populates its section, it deletes the sentinel.
- `init-roadmap.sh` re-run on an existing doc reports the first phase
  with the sentinel as the next phase to populate.
- `validate-roadmap.py` only flags `{{TOKEN}}` placeholders in
  populated phases (sentinel removed). Untouched phases are silent.

This survives compaction, session restart, `/loop` resumes, and the
user pausing for review between phases.

## Anti-pattern guard table

Load-bearing self-discipline. When you catch yourself thinking the left
column, stop and read the right.

| tempting belief | reality |
|---|---|
| "REFINE is overkill — the user already wrote a brief." | REFINE *also* surfaces assumptions, names the Won't list, writes Key Results. Most briefs lack all three. Run REFINE. |
| "The decomposition is obvious — skip DECOMPOSE." | DECOMPOSE picks the *technique* (vertical, by-actor, by-protocol) and tags epics enabler-vs-value. Skip means the implementer guesses. |
| "Most items are genuinely Must — the cap is wrong here." | Almost never true. If the brief implies > 60% Must, the brief is undersliced or the team is over-committed. Force-rank or split. |
| "I'll write the GitHub bodies and just run `gh` myself — saves a step." | The skill never invokes `gh`. Ticket creation is manual per project policy. Bodies + `create-tickets.sh` go in `plans/<slug>-tickets/`. |
| "Skip the spike — I'm confident in the assumption." | Confidence without evidence defaults to 50% (RICE Low tier). A spike ≤ 3 days converts confidence to evidence. |
| "Auto-invoke milestone-pipeline at MATERIALIZE end." | Auto-invoke costs cache (fresh prompt prefix) and removes the user gate. Offer; do not invoke. |
| "Sub-agents would parallelize this." | Planning is well-served by single-pass synthesis. addyosmani's planners are single-thread. Fan-out adds cost without clarity. |
| "Inflate this finding to MUST so it gets attention." | Inflate once and the tier system collapses. The 60% cap exists for this reason. |
| "Write story points to make milestones comparable." | Skill emits T-shirt sizes at epic grain only. Velocity worship is anti-pattern row 10. Forecast is milestone-pipeline's job. |

Full table with rebuttals and source citations: [anti-patterns.md](references/anti-patterns.md).

## Per-phase reference

Read ONE per phase entry; discard from working memory after writing the phase output.

- Phase 1 — [phase-refine.md](references/phase-refine.md)
- Phase 2 — [phase-decompose.md](references/phase-decompose.md)
- Phase 3 — [phase-sequence.md](references/phase-sequence.md)
- Phase 4 — [phase-materialize.md](references/phase-materialize.md)

Cross-cutting:
- [arxmcp-integration.md](references/arxmcp-integration.md) — milestone-pipeline pairing, GitHub conventions, repo conventions to mirror.
- [specialist-contracts.md](references/specialist-contracts.md) — five pre-defined specialist contracts (`latex-parser-reviewer`, `cache-stability-reviewer`, `mcp-protocol-reviewer`, `security-reviewer`, `determinism-reviewer`).
- [frameworks.md](references/frameworks.md) — long-tail frameworks (WSJF, Kano, Shape Up, GIST, ICE, SPIDR, INVEST, Story Mapping, Event Storming, Impact Mapping, #NoEstimates), organized by trigger. Read only when the default fails.
- [anti-patterns.md](references/anti-patterns.md) — 12 named anti-patterns + skill-specific anti-rationalizations.

## Quick start

```bash
# Scaffold (looks up brief from conversation or --brief)
.claude/skills/roadmap/scripts/init-roadmap.sh citation-graph --title "Citation graph traversal"

# Then invoke the skill (after slash registration):
#   roadmap citation-graph --brief "..."

# Lint at any time:
.claude/skills/roadmap/scripts/validate-roadmap.py plans/citation-graph-roadmap.md

# Score helpers:
.claude/skills/roadmap/scripts/score-moscow.py --example
.claude/skills/roadmap/scripts/score-rice.py --example
```

## Pairing with milestone-pipeline

`milestone-pipeline` (sibling skill at
[.claude/skills/milestone-pipeline/](.claude/skills/milestone-pipeline/))
executes ONE milestone end-to-end. The roadmap skill produces milestones
with IDs `<slug>-mN`; milestone-pipeline consumes them via the bridge in
[init-state.sh](.claude/skills/milestone-pipeline/scripts/init-state.sh)
(searches both `.claude/roadmap/*.md` and `plans/*.md`; loud-fails on
collision). The MATERIALIZE phase prints a suggested next-step
invocation; the user runs it manually.

## Token economy

- SKILL.md ≤ 300 lines (this file). Anthropic's published cap is 500
  for "optimal performance"; we go tighter.
- Phase docs read at most ONE per phase entry. Discard after writing.
- `frameworks.md` is lazy — read only when the default cuts fail.
- Script outputs go to stdout/stderr; only `Bash` results enter context.
- Roadmap doc is byte-stable: alphabetical metadata, no timestamps in
  body. Lets milestone-pipeline cache reads of it.

## Project conventions this skill respects

- **Conventional commits**, scope `roadmap` for skill changes, `skill` for cross-skill.
- **GPG signing** (`commit.gpgsign=true`). Never `--no-gpg-sign`.
- **Co-author trailer**: `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- **Pre-commit hooks** are honored. Never `--no-verify`.
- **External-write policy**: ticket creation is manual via
  `gh issue create`; the skill writes the bundle, the user runs it.
- **Constitution**: [.claude/notes/](.claude/notes/) is the source of
  truth — quoted, not paraphrased, in any roadmap derived from it.
