# Phase 3 — Sequence

**Status sentinel:** `<!-- status: pending -->` under `## Phase 3 — Sequence`. Delete it when this phase writes content.

**State postcondition:** MoSCoW assignments with Must ≤ 60% effort, RICE table for the Musts, Now/Next/Later lane assignment, Spike/discovery lane with one entry per `[MUST]` assumption, Now-lane milestones decomposed into stories ≤ 3 days each with Given/When/Then or bullet AC. No `{{TOKEN}}` placeholders remaining in the Sequence section.

## Step-by-step

1. **Read once at phase start:** this file. Frameworks lazy-load only if the default fails.
2. **MoSCoW assignment.** Place each epic from DECOMPOSE into Must / Should / Could / Won't. Initial pass is a draft.
3. **Run `score-moscow.py`** with the assignment as input. The Must total must be ≤ 60% of total effort:
   ```
   echo "<piped epic-id|bucket|effort lines>" | scripts/score-moscow.py
   ```
   Iterate until the script exits 0. If you can't get under the cap, gate.
4. **Run `score-rice.py` on the Musts** to rank within the bucket:
   ```
   echo "<id|reach|impact|confidence|effort>" | scripts/score-rice.py
   ```
   Confidence defaults to 50% when unevidenced — surface this with the `*` marker. Each `*` should map to a Spike-lane entry.
5. **Lane assignment** with rolling-wave detail decay:
   - **Now** — fully spec'd. Stories decomposed (next step) with AC. Highest-RICE Musts go here.
   - **Next** — shaped. Epic-level only. No stories yet.
   - **Later** — outcome-only. Lower confidence; the bet portfolio.
6. **Spike / discovery lane.** For every `[MUST]` assumption from REFINE, write a spike entry:
   ```
   <slug>-spike-N — <description> (≤ 3 days, validates [MUST] assumption: <ref>)
   ```
   Spikes are NOT epics — they're discovery items. Cap each at 3 days.
7. **Decompose Now-lane epics into milestones (stories).** Each milestone:
   - ID format: `<slug>-mN` — heading exactly `### <slug>-mN — Title` (H3, three hashes) so milestone-pipeline can grep. NOT H4 — H4 breaks the lookup.
   - Complexity: S (≤ 1 day), M (1–3 days), L (> 3 days — split via SPIDR, see `frameworks.md`).
   - Acceptance criteria: G/W/T for behavior; bullets for artifacts.
   - Dependencies: epic-id and prior milestone IDs.
   - Specialist suggestion: copy from parent epic.
8. **Verify INVEST at the milestone grain** — `S`mall is the most-likely fail. Anything > 3 days execution time gets split here.
9. **Delete the `<!-- status: pending -->` sentinel.**

## Auto-advance vs gate — decision table

| condition | action |
|---|---|
| Must ≤ 60%, RICE ranks unambiguous, Now lane has 1–4 milestones each ≤ 3 days | **auto-advance** to MATERIALIZE |
| `score-moscow.py` exits 1 (Must > 60%) and demoting any item is contested | **GATE** — show the must list with effort breakdown, ask user which to demote |
| Two Musts have RICE scores within 10% of each other AND different lane consequences | **GATE** — present both as A/B, accept user pick |
| Now lane has > 4 milestones | **GATE** — confirm; usually means epic is too big or stories aren't sliced enough |
| Any milestone is L (> 3 days) | **GATE** — show SPIDR axes, ask which to split on |
| Any `[MUST]` assumption has no spike | **GATE** — auto-emit spike with placeholder description, ask user to confirm or refine |

## Hard rules

- **`score-moscow.py` must exit 0 before advance.** No 60%+ Must lists, ever.
- **RICE Confidence default is 50%** with a `*` marker. The marker is the forcing function: every `*` becomes a Spike-lane item or stays in Next/Later until evidence arrives.
- **One Spike per `[MUST]`.** A `[MUST]` assumption without a Spike is the missing-discovery anti-pattern (see `anti-patterns.md` row 5).
- **Now-lane milestones use the exact heading format** `### <slug>-mN — Title`. Deviating breaks milestone-pipeline's lookup.
- **Stories ≤ 3 days.** Anything bigger is split here, not deferred. Use SPIDR if the user can't see a cut.
- **AC format split:** Given/When/Then for behavior-shaped stories; bulleted checklist for artifact-shaped stories. Mixing is fine within a roadmap; just be consistent within one story.

## Don'ts

- Don't fill the Now lane with everything. Now is "in-flight or next-up" — usually 1–4 milestones. Long Now lane = locked long horizon (anti-pattern row 3).
- Don't promote Should items to Must to "make sure they happen." That's the all-Must collapse.
- Don't auto-skip Spikes for unevidenced assumptions. Cheap insurance.
- Don't write story AC longer than ~7 bullets — that's a too-big story; split.
- Don't add story points or velocity numbers anywhere. T-shirt sizes only at epic grain; complexity tier (S/M/L) at milestone grain. Execution-time forecasting belongs to milestone-pipeline.

## Output template

```
## Phase 3 — Sequence

### MoSCoW assignment

- **Must** (≤ 60% of total effort): <epic-id, epic-id>
- **Should**: <epic-id>
- **Could**: <epic-id>
- **Won't (this cycle)**: <epic-id>

### RICE ranking — Musts

| ID | Reach | Impact | Confidence | Effort | Score |
|---|---:|---:|---:|---:|---:|
| <id> | <n> | <n.nn> | <n>% | <n.nn> | <n.n> |

_`*` indicates Confidence defaulted to 50%; spike scheduled in lane below._

### Now / Next / Later

- **Now** (fully spec'd): <epic-id>, <epic-id>
- **Next** (shaped): <epic-id>
- **Later** (outcome-only): <epic-id>

### Spike / discovery lane

- `<slug>-spike-1` — <description> (≤ 3 days, validates `[MUST]`: <assumption-ref>)

### Milestones — Now lane

### <slug>-m1 — <title>

**Description.** <2–4 sentences>

**Acceptance criteria.**
- [ ] <specific testable condition>
  OR
- Given <context>, When <event>, Then <outcome>.

**Dependencies.** <epic-id, prior-milestone-id, or none>

**Complexity.** S | M | L

**Specialist suggestion.** `<name>` (or `—`)
```
