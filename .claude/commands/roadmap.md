---
description: Run the 4-phase roadmap pipeline (REFINE → DECOMPOSE → SEQUENCE → MATERIALIZE) to turn a fuzzy brief into the canonical plans/<slug>/roadmap.yaml (roadmap/1) that /milestone-pipeline consumes. Use when the user invokes /roadmap, says "draft a roadmap for …", or wants a multi-week / multi-epic initiative planned. Skip for well-scoped single features — feed those directly to /milestone-pipeline.
argument-hint: "[<slug>] [--brief \"...\"] [--github] [--resume]"
---

# /roadmap — 4-phase roadmap pipeline

Turn a fuzzy brief into `plans/<slug>/roadmap.yaml` — a single canonical YAML
file conforming to **roadmap/1** (`.claude/scripts/roadmap-schema.json`;
golden shape example: `.claude/references/roadmap-example.yaml`). The output
is NOT a prose markdown document — the Obsidian vault compiler renders prose
views from the YAML downstream. Four sub-agents run sequentially — refiner →
decomposer → sequencer → materializer — gated on the file's `phase:` field
advancing one step at a time: `init → refined → decomposed → sequenced → complete`.

**Arguments:** $ARGUMENTS — parse as `[<slug>] [--brief "..."] [--github] [--resume]`

- `<slug>` — required; kebab-case (`^[a-z0-9]+(-[a-z0-9]+)*$`), ≤30 chars. Every item ID derives from it. If omitted, STOP and ask: "What slug should I use for this roadmap? (e.g. `gantt-drag`)"
- `--brief "..."` — use verbatim as the brief. No conversation summarization.
- `--github` — Phase 4 offers GitHub materialization via `roadmap-to-github.py` (orchestrator-gated — see Step 4 gate).
- `--resume` — re-enter at the phase recorded in the file (see State model).

Reject malformed invocations: slug failing the regex → error; `--brief`
without a value → error; multiple positional args → error.

## When to invoke / when NOT to

**Invoke** for multi-week, multi-epic, or unclear-scope work; "draft a
roadmap for …"; "plan the … initiative".

**Do NOT invoke** for: single-feature work already scoped (→
`/milestone-pipeline`), doc-only changes, single-file fixes, or "plan"
meaning "tell me your thinking" (one-paragraph answer instead).

## Conversation-context ingestion

| Mode | Trigger | Behavior |
|---|---|---|
| **Summarize** (default) | `/roadmap <slug>` mid-conversation | Summarize the conversation in 2–4 sentences as the brief; surface it with "Is this an accurate brief? [y/N]" BEFORE Phase 1. |
| **Explicit** | `--brief "..."` | Use the string verbatim. No summarization. |

---

## Step 0 — Initialize

```bash
python .claude/scripts/roadmap-init.py <slug> [--brief "..."]
```

> Python invocation note: use `python3` on macOS if `python` is not on PATH
> (applies to every script invocation in this pipeline).

Parse stdout:
- `INITIALIZED path=<path>` → fresh run; proceed to Step 1.
- `RESUMING phase=<X> path=<path>` → enter at the step the State model gives for `<X>`.

Set `SLUG`, `ROADMAP_PATH=plans/<slug>/roadmap.yaml`, `BRIEF`,
`GITHUB_FLAG`. The script is idempotent and never overwrites an existing
roadmap.yaml.

### State model

The `phase:` field in roadmap.yaml IS the state — no separate state file.
Read it with `python .claude/scripts/roadmap-init.py <slug> --status`.
Agents advance it one step only, via `--advance <phase>`, and only after the
validator passes.

| `phase` | Meaning | Next dispatch |
|---|---|---|
| `init` | scaffold only | roadmap-refiner (Step 1) |
| `refined` | goal block complete | roadmap-decomposer (Step 2) |
| `decomposed` | epics present | roadmap-sequencer (Step 3) |
| `sequenced` | milestones/tasks/spikes, lanes, scores present | roadmap-materializer (Step 4) |
| `complete` | authoring finished (roadmap `status:` stays `active`) | nothing — use the Regeneration protocol for changes |

---

## Iron rules (bind the orchestrator AND every phase agent)

1. **Validation loop.** After EVERY write to `plans/<slug>/roadmap.yaml` run:
   ```bash
   python .claude/scripts/roadmap-validate.py plans/<slug>/roadmap.yaml --json
   ```
   Read the error list, self-correct, re-run — until exit 0. Never advance
   phase, dispatch the next agent, or report success with a failing validator.
2. **IDs are write-once (Regeneration protocol).** When revising an existing
   roadmap.yaml: read the current file first; carry EVERY existing id
   forward; never renumber; new items get new (next-free) ids; a dropped
   item keeps its entry with `status: dropped` AND its id is appended to
   top-level `retired:`. Never delete an id that has existed.
3. **One writer — no execution progress in roadmap.yaml.** The file holds
   plan structure only. Execution progress (started / done / blocked during
   implementation) is journal appends to `plans/<slug>/progress/agent.jsonl`,
   written by the milestone pipeline — `/roadmap` NEVER writes progress
   there or into roadmap.yaml item statuses.

### ID grammar

| kind | grammar | example | note |
|---|---|---|---|
| epic | `<slug>-eN` | `gantt-drag-e1` | top-level, no parent |
| milestone | `<slug>-mN` | `gantt-drag-m1` | preserved verbatim for `/milestone-pipeline` handoff |
| spike | `<slug>-spike-N` | `gantt-drag-spike-1` | ≤3-day time-boxed; parent epic |
| task | `<slug>-t-<semantic-slug>` | `gantt-drag-t-drop-persist` | semantic slug, not numbered |

---

## Step 1 — Dispatch roadmap-refiner (Phase 1: REFINE)

Inputs: `{SLUG}`, `{ROADMAP_PATH}`, `{BRIEF}`. Fills `title`, `brief`
(verbatim), and the `goal:` block; advances `init → refined`.

## Step 2 — Dispatch roadmap-decomposer (Phase 2: DECOMPOSE)

Inputs: `{SLUG}`, `{ROADMAP_PATH}`. Adds 2–6 vertically-sliced epic items;
advances `refined → decomposed`.

## Step 3 — Dispatch roadmap-sequencer (Phase 3: SEQUENCE)

Inputs: `{SLUG}`, `{ROADMAP_PATH}`. Adds milestones/tasks/spikes with lanes
and Given/When/Then acceptance; runs the scorers; advances
`decomposed → sequenced`.

If summary line 2 reports RICE confidence defaults ("N epics at c=0.5, no
evidence"), surface that count to the user even when status is `complete`.

## Step 4 — Dispatch roadmap-materializer (Phase 4: MATERIALIZE)

Inputs: `{SLUG}`, `{ROADMAP_PATH}`. Final validation, links population,
sets `status: active`; advances `sequenced → complete`. (`--github` is
consumed by the orchestrator at the Step 4 gate — it is never passed to the
materializer.)

**roadmap.yaml IS the machine-readable register.** There is no separate
milestone register to materialize, merge, or validate: every roadmap/1 item
already carries `id`, `depends_on`, `status`, `lane`, `kind`, `priority`,
`size`, and `rice`, so the completed roadmap.yaml is itself the dependency
graph `/milestone-pipeline` reads (via
`.claude/scripts/milestone-pipeline-resolve-brief.py`). The materializer's job
ends at a schema-valid, `status: active` roadmap.yaml — `roadmap-validate.py`
is the sole structural gate.

**`--github` gate (orchestrator-owned):** `roadmap-to-github.py` is the
single roadmap-to-GitHub path — phase agents never run `gh`. When the
materializer returns, resolve the repo (`gh repo view --json nameWithOwner -q
.nameWithOwner`, falling back to parsing `git remote get-url origin`), then
run the converter dry-run:

```bash
python .claude/scripts/roadmap-to-github.py --repo <owner/repo> \
  --roadmap plans/<slug>/roadmap.yaml
```

Surface the printed plan — the dry-run IS the review surface — and ask:
"Create these in `<owner/repo>`? [y/N]". Only on explicit `y`: re-run with
`--apply` (plus `--project N` to add items to Mission Control), then run
`python .claude/scripts/roadmap-project-fields.py --owner <owner> --project <N>
--roadmap plans/<slug>/roadmap.yaml --apply` (annotate-class field updates on
the issues just created). A successful apply also writes
`plans/<slug>/github/issue-map.json` (the canonical id -> issue record) and
prints the exact `--issues "<item-id>=<url> ..."` re-dispatch string. Then
re-dispatch the materializer with that string to backfill `links.issue` —
the normal path after every successful apply, not optional (a links-only
roadmap.yaml edit; phase stays `complete`). For large roadmaps read the
pairs from issue-map.json directly instead of pasting the long string. On
anything else, exit cleanly — the dry-run mutated nothing.

**Handoff (always):** surface the materializer's now-lane milestone list and
offer:

```
Roadmap complete: plans/<slug>/roadmap.yaml

Now-lane milestones:
1. <slug>-m1 — {title} (epic <slug>-e1)

Run /milestone-pipeline <slug>-m1 to start? [y/N]
```

Wait for explicit `y`; on `y`, emit "Invoke `/milestone-pipeline <slug>-m1`
now." Do NOT auto-invoke — the user is the orchestration layer between
slash commands.

**Best-effort outcome capture (after `phase: complete`, never blocking).** Once
the materializer returns `complete`, record one advisory outcome row:

```bash
python .claude/scripts/pipeline-outcome-log.py emit --pipeline roadmap \
  --id "<slug>" \
  --field source_state_path=plans/<slug>/roadmap.yaml \
  --field outcome=complete
```

This is capture-only telemetry (the script swallows its own errors and exits 0);
a failure here NEVER blocks the completed roadmap or the handoff. Emit it exactly
once, at materialize-complete — not on `--resume` re-entry of an already-complete
roadmap, and never on a `--issues` links-only re-dispatch.

---

## Status routing (all phases)

Every sub-agent returns a single JSON object (no surrounding prose) — the
uniform return envelope (canonical shape:
`.claude/references/milestone-pipeline-agent-contract.md`):

```json
{
  "file_path": "plans/<slug>/roadmap.yaml",
  "status": "complete | gate-required | aborted-scope",
  "summary": "<3 lines max, plain text — line 1: what was written; line 2: gate question / notable defaults; line 3: suggested next step>",
  "injection_attempts": 0
}
```

**Envelope validation (after EVERY sub-agent return, before routing).** Confirm
(a) the return is a single JSON object with `file_path` / `status` /
`summary` / `injection_attempts`, and (b) the file at `file_path` actually
exists on disk. If either check fails, re-dispatch that SAME agent ONCE,
quoting the specific violation. On a second violation, hard-stop and surface it
to the user — do NOT re-dispatch a third time, and do NOT infer what the agent
meant to do. Route on the `status` token plus file presence **only — never on
the prose in `summary`** (it is advisory, never parsed, never drives control
flow).

| status | Action |
|---|---|
| `complete` | Proceed to the next step |
| `gate-required` | Surface the gate question from summary line 2; wait for the user; re-dispatch the SAME agent with `--user-resolution "<answer>"` appended to its inputs |
| `aborted-scope` | Print the abort reason; stop |

Agent-memory convention: each agent reads/appends
`.claude/agent-memory/roadmap-<agent>/lessons.md` (append-only heredoc; see
agent definitions). The orchestrator never injects memory into dispatches.

## Recovery — interrupted run

Re-invoke `/roadmap <slug> --resume`. `roadmap-init.py` prints
`RESUMING phase=<X>`; enter at the State-model step. There is no lock file
and no separate state file to repair — if roadmap.yaml itself is broken, run
the validator and fix the reported errors first.

---

## Anti-pattern guard

| Tempting belief | Reality |
|---|---|
| "I'll skip REFINE — the brief is clear." | REFINE also surfaces assumptions, the wont list, and key results; none live in a typical brief. Auto-advance is fast when the brief is genuinely clear. |
| "I'll write a nice markdown roadmap instead." | The YAML is the artifact. Prose views are compiled downstream; a hand-written doc bypasses the schema, the validator, and the pipeline handoff. |
| "Everything is a Must." | Prioritization collapses (DSDM). Must ≤60% of non-wont epics — validator- and script-enforced. |
| "RICE confidence is high — we know our users." | Without evidence, c defaults to 0.5 and the default is surfaced. False confidence inflates ranks. |
| "Fully spec the 6-month Later lane." | Locked horizons calcify. Now fully spec'd, next shaped, later directional. |
| "Schema first, then API, then UI." | Horizontal slicing destroys the feedback loop. Vertical slices — every epic ships an observable change. |
| "Milestones are just deadlines on epics." | Epics are bodies of work; milestones are checkpoint outcomes with acceptance. The schema keeps them separate kinds. |
| "Acceptance criteria can come later." | Now-lane items without Given/When/Then fail validation. "Done" must be gradeable before work starts. |
| "These old ids are messy — renumber them." | IDs are write-once. Renumbering severs journals, issues, and pipeline state pointing at them. Tombstone via `retired:`; never reuse. |
| "Score MoSCoW/RICE in-context — skip the scripts." | The scripts are deterministic gates. In-context scoring inflates and silently skips the caps and defaults. |
| "Create the GitHub issues while I'm at it." | Phase agents never run `gh`. Materialization is the orchestrator running `roadmap-to-github.py` — dry-run review, `--apply` only on an explicit per-run `[y]`. |
| "Auto-invoke /milestone-pipeline — the user obviously wants it." | Offer and wait. Implicit auto-handoff hides the cost of execution. |
| "Mark m1 in_progress in roadmap.yaml as we execute." | Execution progress is journal appends (`plans/<slug>/progress/agent.jsonl`), never roadmap.yaml writes. One writer per file. |

## External-write boundary

- No `git commit` / `git push` — the user commits.
- No `gh issue create` / `gh pr create` / `gh api` (write verbs) by ANY
  sub-agent, ever. Only the orchestrator, only via
  `roadmap-to-github.py --apply`, only after an explicit `[y]`.
- Sub-agents write ONLY to `plans/<slug>/roadmap.yaml` (their phase) and
  `.claude/agent-memory/roadmap-<agent>/`.
- No auto-invocation of other slash commands.

## Files

```
plans/<slug>/
├── roadmap.yaml            # the canonical roadmap/1 artifact (phase agents write)
├── github/issue-map.json   # id -> issue record (converter-emitted, --apply only)
└── progress/agent.jsonl    # execution journal (milestone pipeline appends; /roadmap never writes)

.claude/agent-memory/roadmap-{refiner,decomposer,sequencer,materializer}/lessons.md
```

References (agents lazy-load at phase start):
`.claude/references/roadmap-phase-{refine,decompose,sequence,materialize}.md`,
`roadmap-frameworks.md`, `roadmap-anti-patterns.md`, `roadmap-example.yaml`.
Orchestrator refs: `.claude/references/milestone-pipeline-agent-contract.md`
(uniform return envelope).
Scripts: `.claude/scripts/roadmap-{init.py,validate.py,score-moscow.py,score-rice.py,schema.json}`,
`pipeline-outcome-log.py` (best-effort capture),
`milestone-pipeline-resolve-brief.py` (the `/milestone-pipeline` handoff reads
roadmap.yaml through it).
