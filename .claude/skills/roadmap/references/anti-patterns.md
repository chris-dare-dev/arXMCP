# Anti-patterns the `roadmap` skill must guard against

Twelve named, well-documented planning anti-patterns. Each row: tempting
belief / reality / what to do instead. Cite the originator where the
trail is clear. The skill's phase docs reference this file by name when
they catch the symptom.

| # | tempting belief | reality | what to do |
|---|---|---|---|
| 1 | **Planning Theatre.** "A thicker plan = more control. Document everything; review nothing." | Over-detailed roadmaps decay on contact with reality and are read by no one. (ProdPad, Bastow) | Now / Next / Later with horizon-decreasing certainty. Ship the plan that gets read. |
| 2 | **All-Must MoSCoW.** "Everything is Must, otherwise we won't ship it." | The prioritization signal collapses; team ships at random under deadline pressure. (DSDM canon) | Enforce ≤ 60% Must by effort. Demote until the cap holds. `score-moscow.py` is the gate. |
| 3 | **Locked long horizons.** "A 12-month committed roadmap shows leadership." | A fiction by month 3, a liability by month 6. (Cagan, *Inspired*; Perri, *Escaping the Build Trap*) | Commit only to *Now*. Treat *Later* as bets, not deliverables. |
| 4 | **Story-point inflation.** "Higher velocity = better team." | Points inflate to meet target; nothing actually changes. (Cohn, "How to Prevent Estimate Inflation") | This skill stays out of points entirely. Emit T-shirt sizes (S/M/L) at epic grain only. |
| 5 | **Missing discovery / spike track.** "Delivery time is sacred — research is waste." | Team builds the wrong thing and burns delivery time fixing it. (Cagan, dual-track; Patton) | SEQUENCE phase MUST emit a Spike lane for every unvalidated `[MUST]` assumption. |
| 6 | **Conflating milestones with epics.** "An epic *is* a release." | Team optimizes for closing the epic, not shipping value. (Patton, "epic confusion") | Epics = work containers; milestones = outcome events. Keep them separate. The skill emits both. |
| 7 | **Horizontal-only slicing.** "Layered work is more efficient — DB sprint, then API, then UI." | Nothing demoable until the last sprint; integration risk piles up. (Patton + Cockburn, walking-skeleton) | Vertical slices, default. Deviate explicitly with reason in the technique field. |
| 8 | **Roadmap as commitment, not bet.** "A roadmap is a contract." | Forces delivery of scope you've already learned is wrong. (Bastow; Gothelf, *Lean UX*) | Each lane is a confidence tier: Now committed, Next shaped, Later hypothesis. Make the framing explicit. |
| 9 | **Missing Definition of Done.** "Done is obvious." | Every team member's "done" is different; rework explodes at integration. (2020 Scrum Guide — DoD elevated to commitment) | Bake DoD into the project (here: project check command green + tests passing) and re-check it in MATERIALIZE. |
| 10 | **Velocity worship.** "Velocity = productivity." | Goodhart's law: a metric that becomes a target stops being a measure. Teams game points and avoid risky work. | Skill emits *no* velocity number. Forecast happens at execution time, by milestone-pipeline, not in the roadmap. |
| 11 | **Estimating without slicing.** "Big number for big thing is fine." | Large unsliced items have unknowable variance; the estimate is a guess shaped like a number. | Slice first (SPIDR — see frameworks.md), estimate the slices, or skip estimation per #NoEstimates. |
| 12 | **"We'll add acceptance criteria later."** | "Done" becomes whatever the dev shipped. QA lengthens. Trust erodes. | AC at refinement, before the story is sprint-ready. G/W/T for behavior; bullets for artifacts. `validate-roadmap.py` enforces it. |

## Skill-specific anti-rationalizations

The orchestrator may catch itself rehearsing one of these. When it does, stop.

| tempting belief | reality |
|---|---|
| "REFINE is overkill — the user already wrote a brief." | REFINE *also* surfaces assumptions, names the Won't list, and writes Key Results. None of these are in a typical brief. Run REFINE. |
| "The decomposition is obvious — skip DECOMPOSE." | DECOMPOSE picks the *technique* (vertical, by-actor, by-protocol) and tags epics enabler-vs-value. Skipping means the implementer guesses. Run it. |
| "Most items are genuinely Must — the cap is wrong here." | Almost never true. If the brief implies > 60% Must, the brief is undersliced or the team is over-committed. Force-rank or split. |
| "I'll write the GitHub bodies and just run `gh` myself — saves a step." | The skill never invokes `gh`. Per project policy, ticket creation is manual. Bodies + `create-tickets.sh` go in `plans/<slug>-tickets/`; user runs the script. |
| "Skip the spike — I'm confident in the assumption." | Confidence without evidence defaults to 50% (RICE Low tier). A spike ≤ 3 days converts confidence to evidence. Cheap insurance against re-work. |
| "Auto-invoke milestone-pipeline at MATERIALIZE end — saves the user a step." | Auto-invoke costs cache (fresh prompt prefix) and removes the user gate. Offer; do not invoke. |

## Sources

- Bastow, Janna — [Why I invented the Now-Next-Later roadmap (ProdPad)](https://www.prodpad.com/blog/invented-now-next-later-roadmap/)
- DSDM / Agile Business Consortium — [MoSCoW prioritisation](https://www.agilebusiness.org/dsdm-project-framework/moscow-prioritisation.html) (the 60% rule)
- Cagan, Marty — *Inspired*; SVPG — [Dual-Track Agile](https://www.svpg.com/dual-track-agile/)
- Cohn, Mike — [How to Prevent Estimate Inflation](https://www.mountaingoatsoftware.com/blog/how-to-prevent-estimate-inflation)
- Patton, Jeff — [The new backlog is a map](https://jpattonassociates.com/the-new-backlog/)
- 2020 Scrum Guide — [What's new vs 2017](https://www.scrum.org/resources/blog/scrum-guide-2020-and-2017-side-side-comparison) (DoD as commitment)
- North, Dan — [Introducing BDD](https://dannorth.net/blog/introducing-bdd/) (Given/When/Then origin)
- Anthropic — [Multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) (the no-paraphrasing-summarizer rule)
