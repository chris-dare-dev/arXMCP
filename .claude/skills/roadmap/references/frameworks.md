# Frameworks (long-tail) — organized by trigger

Lazy-loaded. The phase docs reference this file ONLY when the default
framework set fails to scope a decision. Do not read this whole file —
jump to the section whose **Trigger** matches the situation.

The default frameworks (always-loaded in phase docs) are: OKR,
Now/Next/Later, MoSCoW (60% cap), RICE (Confidence default 50%),
vertical slicing, Given/When/Then or bullet AC, Spike/discovery lane.

Everything below is **lazy** — invoked only when the default is wrong
for the problem shape.

---

## When MoSCoW + RICE isn't the right cut

### WSJF — Weighted Shortest Job First

**Trigger:** the work has time-sensitive economic value (regulatory
deadline, market window, opportunity decay). Cost-of-Delay is real.

**Summary:** rank by Cost of Delay ÷ Job Size. SAFe variant uses
relative scoring (Fibonacci) for both numerator and denominator.

**Use when:** RICE under-weights time. Reinertsen: "If you only quantify
one thing, quantify the Cost of Delay."

**Don't use when:** the team can't make Cost of Delay numeric (in dollars
or relative score). SAFe-style WSJF substitutes opinions for the dollars
Reinertsen actually wanted (Yip's critique).

**In arXMCP context:** rare. The project has no external deadlines for
v1.

---

### ICE — Impact × Confidence × Ease

**Trigger:** growth/experimentation backlog, fast triage needed, Reach
is roughly constant across ideas.

**Summary:** each factor 1–10; multiply.

**Use when:** you have many ideas and need a 10-second triage before
deeper RICE on the top-N.

**Don't use when:** committed roadmap items where false precision (the
1–10 scale) hides disagreement; the multiplication amplifies whoever
scores highest most aggressively.

**In arXMCP context:** rare. The project's roadmap is small enough that
hand-ranking beats ICE.

---

### Kano model

**Trigger:** deciding which features matter to satisfaction vs which
delight, especially for new products.

**Summary:** 5 categories — Must-be / One-dimensional / Attractive /
Indifferent / Reverse — measured via the functional/dysfunctional
question pair (Kano 1984).

**Use when:** the brief explicitly contrasts "table stakes" vs
"differentiator" features and the team needs a vocabulary.

**Don't use when:** internal/dev-tool work — there's no satisfaction
survey to run.

**In arXMCP context:** mostly internal. Skip unless an epic explicitly
targets external researcher delight.

---

## When vertical slicing produces a story too big

### SPIDR — story-splitting heuristic

**Trigger:** a story is too big and the user can't see how to split it.
Walk SPIDR in order; first axis that yields independent slices wins.

**Summary (Mike Cohn / Mountain Goat):**
- **S**pike — split research as a standalone time-boxed item
- **P**aths — split by user path (happy path, sad path, error path)
- **I**nterfaces — split by UI / channel / platform
- **D**ata — subset the data (one paper, one chunk type, one tenant)
- **R**ules — subset the business rules (free tier, then paid; one rule, then full set)

**Use when:** SEQUENCE phase produces a milestone that needs > ~3 days.

**Don't use when:** the story is small but unfamiliar — research first
(an actual Spike), don't pre-emptively split.

**In arXMCP context:** **D**ata is the most common axis (split by paper
subset, chunk type, or arXiv category). Use SPIDR to get from "build the
search server" to milestones each ≤ 3 days.

---

### INVEST — story quality gate

**Trigger:** a story has been sliced; verify it's sprint-ready.

**Summary (Bill Wake 2003):**
- **I**ndependent — can ship without other items in flight
- **N**egotiable — details aren't a contract
- **V**aluable — delivers something the user can name
- **E**stimable — team can ballpark size
- **S**mall — fits in a sprint
- **T**estable — has acceptance criteria

**Use when:** finishing DECOMPOSE or SEQUENCE for any epic > S size. The
phase doc references INVEST in the validation pass.

---

## When the brief is genuinely structural / domain-rich

### User Story Mapping (Patton 2014)

**Trigger:** user-facing product with a discoverable journey.

**Summary:** horizontal backbone of user activities (top of map),
vertical ribs of stories under each, sliced into release rows; first
row = walking skeleton (Cockburn).

**Use when:** REFINE produces an Objective whose KRs all describe
user behavior changes through a multi-step journey.

**Don't use when:** infrastructure / library / protocol work where there
is no narrative actor. arXMCP's MCP server is mostly *infrastructure
for agents* — Story Mapping is a poor fit at the system level. It
*could* fit at the meta-roadmap level ("the researcher's journey:
discover paper → traverse citations → ground a proof").

---

### Event Storming (Brandolini 2013)

**Trigger:** domain-rich systems, DDD adoption, cross-team alignment,
or the brief implies a complex sequence of state transitions.

**Summary:** sticky-note workshop where domain events (orange) drive
out commands, aggregates, policies. Three variants — Big Picture,
Process Modelling, Software Design.

**Use when:** the brief describes a process with non-trivial event
flow (corpus ingestion is one — fetch → tar → LaTeXML → normalize →
chunk → embed → write).

**Don't use when:** CRUD / stateless tooling — no interesting events.

---

### Impact Mapping (Adzic 2012)

**Trigger:** stakeholders confuse output with outcome. The brief reads
like a feature list, not a behavior change.

**Summary:** mind-map tree Goal → Actor → Impact → Deliverable
(Why → Who → How → What). Forces naming the behavior change before
naming the feature.

**Use when:** REFINE phase — if the user's brief is feature-shaped,
suggest Impact Mapping as a reframe lens. The output reshapes the
Objective + KRs.

---

## When the cadence is wrong

### Shape Up (Singer 2019)

**Trigger:** novel work, fixed-time-variable-scope team, mature
shaping skill.

**Summary:** 6-week cycles + 2-week cool-down. Pitches (problem,
appetite, solution sketch, rabbit holes, no-gos). Betting table
(no backlog grooming). Hill charts (uphill = figuring out, downhill =
executing).

**Use when:** the team is small senior, the work is novel, and
estimating is essentially fake. arXMCP's profile fits.

**Don't use when:** discovery-heavy or compliance-heavy work; or when
the team needs more frequent feedback than 6 weeks.

**Effect on this skill's output:** if the user opts in, MATERIALIZE
suggests a "next pitch" framing rather than Now/Next/Later. The skill's
default stays Now/Next/Later because Shape Up is opt-in.

---

### GIST (Gilad)

**Trigger:** the team wants explicit experiment-tracking.

**Summary:** Goals → Ideas → Step-projects → Tasks. Strength: explicit
thread from outcome to task; first-class place for Ideas as a
hypothesis pool.

**Use when:** the brief describes a *bet portfolio* with multiple
experiments, not a feature pipeline.

**Don't use when:** the work is committed-scope; GIST's strength
(idea pool) is wasted.

---

## When estimation is the wrong frame

### #NoEstimates (Duarte, Zuill)

**Trigger:** team finds estimation meetings cost more than they yield.

**Summary:** replace per-item estimation with throughput-based
forecasting. Slice small enough that count-of-stories ≈ size.

**Use when:** the team has a stable cycle-time distribution and small
slices (each story ≤ 1 day average).

**Don't use when:** fixed-bid contracts or strong uncertainty (Alleman
critique).

**In this skill:** the default IS #NoEstimates-shaped — emit T-shirt
sizes only at epic grain, no story points anywhere. Stories live or
die by AC + complexity tier (S/M/L), not points.

---

## When the AC format itself is up for grabs

### Given / When / Then (Dan North 2006)

**Trigger:** behavior-shaped story (state + trigger + observable
outcome).

**Summary:**
- Given <some context>
- When <some event>
- Then <some outcome>

**Use when:** the AC describes a behavior. Example: "Given a paper_id
in the math.AG corpus, When the agent calls search_papers, Then a
chunk_id is returned in <2s p95."

**Don't use when:** the story produces an artifact whose AC is a
property list. Then bullets are clearer.

---

### Bulleted AC (the project's existing convention)

**Trigger:** artifact-shaped story (the story produces an X with
properties Y, Z, W).

**Summary:** plain checklist:
```
- [ ] specific testable condition
- [ ] another specific testable condition
```

**Use when:** the story is "build / install / configure / structure
something." Most arXMCP infrastructure stories fit here.

**Don't use when:** the story is about behavior under conditions —
G/W/T captures the conditions explicitly.

---

## Sources

- Bastow, Janna — [Now/Next/Later](https://www.prodpad.com/blog/invented-now-next-later-roadmap/)
- Reinertsen, Don — [Black Swan Farming on WSJF](https://blackswanfarming.com/wsjf-weighted-shortest-job-first/)
- Cohn, Mike — [SPIDR](https://www.mountaingoatsoftware.com/blog/five-simple-but-powerful-ways-to-split-user-stories), [Stories, Epics, Themes](https://www.mountaingoatsoftware.com/blog/stories-epics-and-themes)
- Wake, Bill — [INVEST](https://xp123.com/invest-in-good-stories-and-smart-tasks/)
- Patton, Jeff — [Story Mapping](https://www.jpattonassociates.com/wp-content/uploads/2015/03/story_mapping.pdf)
- Brandolini, Alberto — [EventStorming](https://www.eventstorming.com/)
- Adzic, Gojko — [Impact Mapping](https://www.impactmapping.org/book.html)
- Singer, Ryan — [Shape Up](https://basecamp.com/shapeup)
- Gilad, Itamar — [GIST](https://itamargilad.com/gist-framework/)
- Duarte, Vasco — [#NoEstimates Q&A on InfoQ](https://www.infoq.com/articles/book-review-noestimates/)
- North, Dan — [Introducing BDD](https://dannorth.net/blog/introducing-bdd/)
- DSDM / Agile Business Consortium — [MoSCoW](https://www.agilebusiness.org/dsdm-project-framework/moscow-prioritisation.html)
