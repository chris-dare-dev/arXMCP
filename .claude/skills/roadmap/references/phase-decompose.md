# Phase 2 — Decompose

**Status sentinel:** `<!-- status: pending -->` under `## Phase 2 — Decompose`. Delete it when this phase writes content.

**State postcondition:** technique selected, 2–6 epics emitted (each ≤ 6 weeks), each tagged enabler-vs-value, each with INVEST notes and a specialist suggestion (or `—` if none applies). No `{{TOKEN}}` placeholders remaining in the Decompose section.

## Step-by-step

1. **Read once at phase start:** this file plus `references/specialist-contracts.md`. The frameworks lazy-load only if the default fails — don't pre-load `frameworks.md`.
2. **Pick a technique.** Default: **vertical slicing + enabler stories**. Deviate ONLY when the brief shape implies otherwise:
   - User-facing journey with discoverable steps → User Story Mapping (`frameworks.md`).
   - Domain-rich event flow (e.g. corpus ingestion pipeline) → Event Storming.
   - Stakeholder confuses output with outcome → Impact Mapping (Goal → Actor → Impact → Deliverable).
   - Otherwise: vertical slicing.
3. **Write the technique field** with the choice and a one-line reason.
4. **Decompose into 2–6 epics, each ≤ 6 weeks.** More than 6 epics = the milestone is itself a roadmap; split. Fewer than 2 = the milestone doesn't need a roadmap; just spec a single thing.
5. **Tag each epic enabler-vs-value:**
   - **value** — produces user-visible behavior change, demoable to a non-engineer.
   - **enabler** — infrastructure / refactor / spike that makes future value epics possible.
   - At least one value epic per roadmap. Pure-enabler roadmaps fail the "outcome > output" test.
6. **For each epic, suggest a specialist** based on the path heuristic:
   - Touches `parser/`, `chunker/`, `*.tex`, `*.xml`, `*.mathml` → `latex-parser-reviewer`
   - Touches tool schemas, JSON serialization, `chunk_id` construction, retrieval cache → `cache-stability-reviewer` and `determinism-reviewer`
   - Touches `server/transport/`, `shim/`, HTTP handlers → `mcp-protocol-reviewer`
   - Touches subprocess invocation, network egress, tool input validation, LaTeXML, model loading → `security-reviewer`
   - Otherwise: `—` (skip suggestion; milestone-pipeline's adversary critic suffices)

   Output: "Specialist suggestion: `<name>` — see `.claude/skills/roadmap/references/specialist-contracts.md`."

7. **Run INVEST on each epic.** Note any letter that's borderline. Specifically: an epic that fails **I**ndependent (depends heavily on another epic in the same roadmap) needs explicit dependency notes; an epic that fails **S**mall (>6 weeks) must be split.
8. **Estimate size at T-shirt grain only.** S (≤ 1 week), M (1–3 weeks), L (3–6 weeks). Anything > L gets split here, not deferred to SEQUENCE.
9. **Delete the `<!-- status: pending -->` sentinel.**

## Auto-advance vs gate — decision table

| condition | action |
|---|---|
| Single technique fits cleanly, 2–6 epics, all INVEST clean | **auto-advance** to SEQUENCE |
| Two architecturally divergent decomposition cuts of comparable merit (e.g. split-by-data-tier vs split-by-protocol) | **GATE** — present both as options A/B with their epic lists, accept user pick |
| Any epic > L size after splitting | **GATE** — surface; ask user to split further or accept the size with rationale |
| All epics are enablers (no value epic) | **GATE** — confirm; pure-enabler roadmaps are sometimes correct (e.g. infrastructure milestone) but usually not |

Gate format is fast keystroke (numbered options, single-letter response).

## Hard rules

- **Default is vertical slicing.** Deviation requires a reason in the technique field.
- **Each epic has a specialist suggestion field.** Empty (i.e. literal `—`) is fine for epics that don't match any heuristic; missing the field at all is a violation.
- **Cap is 6 weeks per epic, 6 epics per roadmap.** The roadmap skill is for *one milestone of work*. Multi-quarter scope is the project's master roadmap (`.claude/roadmap/`), authored elsewhere.
- **Outcome-framed epic titles, not feature-framed.** "Cited theorems traversable in <2s" beats "Add citation graph endpoint."
- **The Won't list (from REFINE) constrains DECOMPOSE.** If an epic implies a Won't item, surface the conflict and stop — REFINE got something wrong.

## Don'ts

- Don't break the "≤ 6 epics" cap by listing stories at the epic level. Stories belong in SEQUENCE under Now-lane epics.
- Don't list every epic with every specialist. Heuristic is path-based.
- Don't include time estimates beyond T-shirt sizes. Days/weeks at the epic grain are fake; resist the urge.
- Don't pre-emptively split a story into milestones. SEQUENCE owns story-grain decomposition for the Now lane.

## Output template

```
## Phase 2 — Decompose

### Technique

<technique>. <one-line reason>.

### Epics

#### <slug>-e1 — <outcome-framed title>

- **Type:** value
- **Specialist suggestion:** `<name>` — see `.claude/skills/roadmap/references/specialist-contracts.md` (or `—` if none)
- **Outcome:** <measurable behavior change>
- **Estimated size:** S | M | L
- **INVEST check:** I clean, N clean, V clean, E clean, S clean, T clean (or note borderline letters)
- **Dependencies:** none | <epic-id, epic-id>
- **Won't conflict check:** none | <flag>

(repeat for each epic)
```
