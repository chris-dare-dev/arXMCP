# Anti-patterns the roadmap pipeline must guard against

Twelve named, well-documented planning anti-patterns. Each row: tempting
belief / reality / what to do instead. Cite the originator where the
trail is clear. The phase docs reference this file by name when they
catch the symptom.

| # | tempting belief | reality | what to do |
|---|---|---|---|
| 1 | **Planning Theatre.** "A thicker plan = more control. Document everything; review nothing." | Over-detailed roadmaps decay on contact with reality and are read by no one. (ProdPad, Bastow) | Now / next / later with horizon-decreasing certainty. Ship the plan that gets read. |
| 2 | **All-Must MoSCoW.** "Everything is must, otherwise we won't ship it." | The prioritization signal collapses; work ships at random under deadline pressure. (DSDM canon) | Enforce ≤ 60% must over non-wont epics. Demote until the cap holds. `roadmap-score-moscow.py` and `roadmap-validate.py` are the gates. |
| 3 | **Locked long horizons.** "A 12-month committed roadmap shows leadership." | A fiction by month 3, a liability by month 6. (Cagan, *Inspired*; Perri, *Escaping the Build Trap*) | Commit only to *now*. Treat *later* as bets, not deliverables. |
| 4 | **Story-point inflation.** "Higher velocity = better team." | Points inflate to meet target; nothing actually changes. (Cohn, "How to Prevent Estimate Inflation") | This pipeline stays out of points entirely. T-shirt `size` at epic grain; `estimate_days` only on tasks/spikes. |
| 5 | **Missing discovery / spike track.** "Delivery time is sacred — research is waste." | You build the wrong thing and burn delivery time fixing it. (Cagan, dual-track; Patton) | SEQUENCE MUST emit a `<slug>-spike-N` item for every unvalidated `must` assumption. |
| 6 | **Conflating milestones with epics.** "An epic *is* a release." | You optimize for closing the epic, not shipping value. (Patton, "epic confusion") | Epics = work containers; milestones = outcome checkpoints with acceptance. roadmap/1 keeps them separate `kind`s. |
| 7 | **Horizontal-only slicing.** "Layered work is more efficient — DB sprint, then API, then UI." | Nothing demoable until the last sprint; integration risk piles up. (Patton + Cockburn, walking-skeleton) | Vertical slices, default. Deviate explicitly with a stated reason. |
| 8 | **Roadmap as commitment, not bet.** "A roadmap is a contract." | Forces delivery of scope you've already learned is wrong. (Bastow; Gothelf, *Lean UX*) | Each lane is a confidence tier: now committed, next shaped, later hypothesis. Make the framing explicit. |
| 9 | **Missing Definition of Done.** "Done is obvious." | Everyone's "done" is different; rework explodes at integration. (2020 Scrum Guide — DoD elevated to commitment) | Bake DoD into the project (check command green + tests passing) and re-check it in MATERIALIZE. |
| 10 | **Velocity worship.** "Velocity = productivity." | Goodhart's law: a metric that becomes a target stops being a measure. Teams game points and avoid risky work. | The pipeline emits *no* velocity number. Forecast happens at execution time, by the milestone pipeline, not in the roadmap. |
| 11 | **Estimating without slicing.** "Big number for big thing is fine." | Large unsliced items have unknowable variance; the estimate is a guess shaped like a number. | Slice first (SPIDR — see `roadmap-frameworks.md`), estimate the slices, or skip estimation per #NoEstimates. |
| 12 | **"We'll add acceptance criteria later."** | "Done" becomes whatever got shipped. Grading has nothing to grade against. | Acceptance at sequencing, before an item enters the now lane. Given/When/Then strings; `roadmap-validate.py` enforces them on now-lane items. |

## Pipeline-specific anti-rationalizations

The orchestrator may catch itself rehearsing one of these. When it does, stop.

| tempting belief | reality |
|---|---|
| "REFINE is overkill — the user already wrote a brief." | REFINE *also* surfaces assumptions, names the wont list, and writes key results. None of these are in a typical brief. Run REFINE. |
| "The decomposition is obvious — skip DECOMPOSE." | DECOMPOSE picks the *technique* and tags epics value-vs-enabler. Skipping means the implementer guesses. Run it. |
| "Most items are genuinely must — the cap is wrong here." | Almost never true. A brief implying > 60% must is undersliced or overcommitted. Force-rank or split. |
| "I'll write a prose roadmap doc — YAML is unfriendly." | The YAML IS the artifact; the vault compiler renders the prose views. A hand doc bypasses the schema, the validator, and the pipeline handoff. |
| "These ids are ugly — renumber for cleanliness." | IDs are write-once. Journals, issues, and pipeline state point at them. Tombstone drops to `retired:`; never renumber, never reuse. |
| "I'll just run `gh` myself and create the issues — saves a step." | Phase agents never invoke `gh`. Materialization is the orchestrator running `roadmap-to-github.py` — dry-run review, `--apply` only on an explicit per-run `[y]`. |
| "Skip the spike — I'm confident in the assumption." | Confidence without evidence defaults to 0.5 (RICE low tier). A spike ≤ 3 days converts confidence to evidence. Cheap insurance against rework. |
| "Auto-invoke the milestone pipeline at MATERIALIZE end — saves the user a step." | Auto-invoke removes the user gate and costs a fresh prompt prefix. Offer; do not invoke. |
| "Track execution status in roadmap.yaml while implementing." | One writer per file: plan structure is agent-owned; progress is append-only journals under `plans/<slug>/progress/`. Mixing them corrupts both. |

## Sources

- Bastow, Janna — [Why I invented the Now-Next-Later roadmap (ProdPad)](https://www.prodpad.com/blog/invented-now-next-later-roadmap/)
- DSDM / Agile Business Consortium — [MoSCoW prioritisation](https://www.agilebusiness.org/dsdm-project-framework/moscow-prioritisation.html) (the 60% rule)
- Cagan, Marty — *Inspired*; SVPG — [Dual-Track Agile](https://www.svpg.com/dual-track-agile/)
- Cohn, Mike — [How to Prevent Estimate Inflation](https://www.mountaingoatsoftware.com/blog/how-to-prevent-estimate-inflation)
- Patton, Jeff — [The new backlog is a map](https://jpattonassociates.com/the-new-backlog/)
- 2020 Scrum Guide — [What's new vs 2017](https://www.scrum.org/resources/blog/scrum-guide-2020-and-2017-side-side-comparison) (DoD as commitment)
- North, Dan — [Introducing BDD](https://dannorth.net/blog/introducing-bdd/) (Given/When/Then origin)
- Anthropic — [Multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) (the no-paraphrasing-summarizer rule)
