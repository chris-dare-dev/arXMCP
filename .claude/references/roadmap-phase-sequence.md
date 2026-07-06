# Phase 3 — SEQUENCE

**Goal:** decide what ships now (fully spec'd), next (shaped), later
(directional); score it; spike every unvalidated `must` assumption.

**Writes:** milestone/task/spike entries in `items:`, `lane`/date/estimate
fields, epic `rice:` blocks and final `priority:` values in
`plans/<slug>/roadmap.yaml`. Advances `phase: decomposed → sequenced`.

## Step-by-step

### 1. MoSCoW with the script-enforced cap

Finalize every epic's `priority:`, then run:

```bash
python .claude/scripts/roadmap-score-moscow.py plans/<slug>/roadmap.yaml --json
```

Hard rule (DSDM): **must ≤ 60% of non-wont epics.** Exit 1 = violation —
demote epics in the YAML and re-run. Do not reason the cap away in-context:
if "most items are genuinely must", the roadmap is undersliced or
overcommitted. Do not proceed to RICE until exit 0.

### 2. RICE the epics (compute-only script)

Fill raw factors into each non-wont epic's `rice:` block:

- **r** (reach) — users/sessions/events affected per period. For solo
  projects, honest small integers beat vanity thousands.
- **i** (impact) — 0.25 / 0.5 / 1 / 2 / 3, discrete steps only.
- **c** (confidence) — 0–1. **Default 0.5 when there is no evidence.**
  0.8 with anecdotal evidence; 1.0 only with data. Every 0.5 default is
  surfaced to the user by name.
- **e** (effort) — person-weeks, > 0.

```bash
python .claude/scripts/roadmap-score-rice.py plans/<slug>/roadmap.yaml --json
```

The script computes `score = r*i*c/e` and a descending `rank` but NEVER
writes the file — PyYAML round-trips destroy comments and key order
(registry byte-stability rule). **The sequencer agent writes the reported
`score:`/`rank:` values into the `rice:` blocks itself via Edit**, then
re-validates.

### 3. Lane assignment (rolling-wave detail decay)

| lane | detail level | horizon |
|---|---|---|
| `now` | fully spec'd: milestones + tasks with Given/When/Then acceptance, estimates, dates | current cycle |
| `next` | shaped: milestone-level only, deps named, no task decomposition | cycle+1 |
| `later` | directional: title + one-line summary | beyond |

Rules: now = top-ranked musts that fit capacity (solo default ≈ 1 epic per
2 weeks); next = remaining musts + top shoulds; later = the rest. No
now-lane item depends on a next/later item. Every milestone carries a
`lane` — validator-enforced at phase ≥ sequenced. Resist spec'ing later —
it locks horizons.

### 4. Milestones, tasks, spikes

- **Milestone** `<slug>-mN` — an outcome checkpoint, not a deadline on an
  epic. `parent:` epic; `lane`; `target_start`/`target_end` (ISO,
  start ≤ end); `depends_on` spikes/milestones it needs. These ids are
  consumed verbatim by `/milestone-pipeline`. Milestones SHOULD carry a
  1–2 sentence `summary:` — `milestone-pipeline-resolve-brief.py` folds it
  into the pipeline brief; a milestone without one leaves the pipeline to
  derive scope from acceptance strings alone.
- **Task** `<slug>-t-<semantic-slug>` — `parent:` milestone (or epic);
  `estimate_days` ≤ 3 (bigger → split via SPIDR, `roadmap-frameworks.md`);
  lane matches its milestone; `priority` optional.
- **Spike** `<slug>-spike-N` — one per unvalidated `must` assumption from
  `goal.assumptions`; `parent:` the epic it de-risks; `estimate_days` ≤ 3,
  time-boxed (overrun = escalate, don't extend); finding recorded via
  `links.note`. The dependent milestone lists it in `depends_on`.

**Acceptance:** every now-lane milestone and task needs ≥1 acceptance
string (validator-enforced), Given/When/Then shaped:
`"Given {context}, when {action}, then {observable outcome}"`.

## Output shape (items appended under the epics)

```yaml
  - id: arxmcp-v2-search-spike-1
    kind: spike
    title: "Embedding model bake-off on 50-paper sample"
    parent: arxmcp-v2-search-e1
    lane: now
    estimate_days: 1
    target_end: 2026-07-08
    acceptance:
      - "Given 20 canned queries, when 2 local models are compared, then recall@10 is recorded per model"
    links:
      note: ["[[embedding bake-off]]"]

  - id: arxmcp-v2-search-m1
    kind: milestone
    title: "Corpus indexed end-to-end"
    summary: "Full corpus chunked, embedded, and queryable from a persistent on-disk index."
    parent: arxmcp-v2-search-e1
    lane: now
    target_start: 2026-07-06
    target_end: 2026-07-24
    depends_on: [arxmcp-v2-search-spike-1]
    acceptance:
      - "Given the full corpus, when the index build runs, then it completes in < 30 min"

  - id: arxmcp-v2-search-t-chunk-schema
    kind: task
    title: "Define chunk + document schema"
    parent: arxmcp-v2-search-m1
    lane: now
    priority: must
    estimate_days: 1
    acceptance:
      - "Given a fresh clone, when the migration runs twice, then the second run is a no-op"
```

And on each scored epic:

```yaml
    rice: { r: 6, i: 2, c: 0.5, e: 1.5, score: 4.0, rank: 1 }
```

## Sanity checklist before advancing

- [ ] `roadmap-score-moscow.py` exit 0
- [ ] Every non-wont epic has complete `rice:` with script-computed
      score/rank written back
- [ ] Every now-lane milestone/task has ≥1 GWT acceptance string
- [ ] Every task `estimate_days` ≤ 3
- [ ] Every unvalidated `must` assumption has a spike (or cited evidence)
- [ ] No now-lane item depends on a next/later item
- [ ] Dates ISO, start ≤ end

## Auto-advance vs gate

| Condition | Action |
|---|---|
| Checklist clean | **Auto-advance** — validate, `--advance sequenced`, re-validate (lane checks activate) |
| Must/should cut-line has ≥2 credible readings | **GATE.** Surface both with capacity-cost tradeoffs. |
| c=0.5 default on many musts | **Not a gate**, but MUST surface the count by name before the rank is accepted. |
| RICE rank contradicts user-stated priority | **GATE.** Show the conflict; the user picks the winning signal. |
| A now-lane item lacks GWT or a task exceeds 3 days | **Not a gate** — re-slice or write the acceptance; never advance broken. |

## Hard rules

- **Cap and scores come from the scripts** — never hand-waved in-context.
- **c defaults to 0.5 without evidence** — a higher value needs a one-line
  evidence citation.
- **later lane gets no task decomposition.**
- **Every `must` assumption: spike or evidence.** Neither is malpractice.
- **IDs write-once** — regeneration carries all ids; drops tombstone to
  `retired:`.
