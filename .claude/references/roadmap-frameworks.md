# Frameworks (long-tail) — organized by trigger

Lazy-loaded. The phase docs reference this file ONLY when the default
framework set fails to scope a decision. Do not read this whole file —
jump to the section whose **Trigger** matches the situation.

The default frameworks (always-loaded in phase docs) are: OKR,
Now/Next/Later, MoSCoW (60% cap), RICE (confidence default 0.5),
vertical slicing, Given/When/Then acceptance, Spike/discovery lane.

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

**Don't use when:** you can't make Cost of Delay numeric (in dollars or
relative score). SAFe-style WSJF substitutes opinions for the dollars
Reinertsen actually wanted (Yip's critique).

**Solo-project note:** rare — personal projects seldom carry external
deadlines.

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

**Solo-project note:** rare — a roadmap small enough to hand-rank beats
ICE.

---

### Kano model

**Trigger:** deciding which features matter to satisfaction vs which
delight, especially for new products.

**Summary:** 5 categories — Must-be / One-dimensional / Attractive /
Indifferent / Reverse — measured via the functional/dysfunctional
question pair (Kano 1984).

**Use when:** the brief explicitly contrasts "table stakes" vs
"differentiator" features and a vocabulary is needed.

**Don't use when:** internal/dev-tool work — there's no satisfaction
survey to run.

---

## When vertical slicing produces an item too big

### SPIDR — story-splitting heuristic

**Trigger:** an item is too big and no split is obvious. Walk SPIDR in
order; first axis that yields independent slices wins.

**Summary (Mike Cohn / Mountain Goat):**
- **S**pike — split research as a standalone time-boxed item
- **P**aths — split by user path (happy path, sad path, error path)
- **I**nterfaces — split by UI / channel / platform
- **D**ata — subset the data (one record type, one tenant, one corpus slice)
- **R**ules — subset the business rules (one rule first, then the full set)

**Use when:** SEQUENCE produces a task that needs > ~3 `estimate_days`.

**Don't use when:** the item is small but unfamiliar — research first
(an actual spike), don't pre-emptively split.

---

### INVEST — quality gate

**Trigger:** an epic or task has been sliced; verify it's ready.

**Summary (Bill Wake 2003):**
- **I**ndependent — can ship without other items in flight
- **N**egotiable — details aren't a contract
- **V**aluable — delivers something the user can name
- **E**stimable — you can ballpark the size
- **S**mall — fits the lane's time box
- **T**estable — has acceptance criteria

**Use when:** finishing DECOMPOSE or SEQUENCE for any epic > S size.

---

## When the brief is genuinely structural / domain-rich

### User Story Mapping (Patton 2014)

**Trigger:** user-facing product with a discoverable journey.

**Summary:** horizontal backbone of user activities (top of map),
vertical ribs of stories under each, sliced into release rows; first
row = walking skeleton (Cockburn).

**Use when:** REFINE produces an objective whose key results all describe
user behavior changes through a multi-step journey.

**Don't use when:** infrastructure / library / protocol work where there
is no narrative actor at the system level.

---

### Event Storming (Brandolini 2013)

**Trigger:** domain-rich systems, DDD adoption, or the brief implies a
complex sequence of state transitions.

**Summary:** sticky-note workshop where domain events (orange) drive
out commands, aggregates, policies. Three variants — Big Picture,
Process Modelling, Software Design.

**Use when:** the brief describes a process with non-trivial event flow
(e.g. a multi-stage ingest pipeline: fetch → parse → normalize → index).

**Don't use when:** CRUD / stateless tooling — no interesting events.

---

### Impact Mapping (Adzic 2012)

**Trigger:** the brief reads like a feature list, not a behavior change —
output confused with outcome.

**Summary:** mind-map tree Goal → Actor → Impact → Deliverable
(Why → Who → How → What). Forces naming the behavior change before
naming the feature.

**Use when:** REFINE — if the brief is feature-shaped, use Impact Mapping
as the reframe lens; the output reshapes the objective + key results.

---

## When the cadence is wrong

### Shape Up (Singer 2019)

**Trigger:** novel work, fixed-time-variable-scope, mature shaping skill.

**Summary:** 6-week cycles + 2-week cool-down. Pitches (problem,
appetite, solution sketch, rabbit holes, no-gos). Betting table (no
backlog grooming). Hill charts (uphill = figuring out, downhill =
executing).

**Use when:** the team is small and senior, the work is novel, and
estimating is essentially fake — a common solo-project profile.

**Don't use when:** discovery-heavy or compliance-heavy work; or when
feedback is needed more often than every 6 weeks.

**Effect on this pipeline's output:** if the user opts in, MATERIALIZE
suggests a "next pitch" framing rather than Now/Next/Later. The default
stays Now/Next/Later because Shape Up is opt-in.

---

### GIST (Gilad)

**Trigger:** explicit experiment-tracking wanted.

**Summary:** Goals → Ideas → Step-projects → Tasks. Strength: explicit
thread from outcome to task; first-class place for Ideas as a
hypothesis pool.

**Use when:** the brief describes a *bet portfolio* with multiple
experiments, not a feature pipeline.

**Don't use when:** committed-scope work; GIST's strength (idea pool)
is wasted.

---

## When estimation is the wrong frame

### #NoEstimates (Duarte, Zuill)

**Trigger:** estimation costs more than it yields.

**Summary:** replace per-item estimation with throughput-based
forecasting. Slice small enough that count-of-items ≈ size.

**Use when:** stable cycle-time distribution and small slices (tasks
≤ 3 days).

**Don't use when:** fixed-bid contracts or strong uncertainty (Alleman
critique).

**In this pipeline:** the default IS #NoEstimates-shaped — T-shirt sizes
at epic grain, `estimate_days` only on tasks/spikes, no story points
anywhere. Items live or die by acceptance + slice size, not points.

---

## When the acceptance format itself is up for grabs

### Given / When / Then (Dan North 2006)

**Trigger:** behavior-shaped item (state + trigger + observable outcome).

**Summary:**
- Given <some context>
- When <some event>
- Then <some outcome>

**Use when:** the acceptance describes behavior. In roadmap/1, now-lane
milestones and tasks REQUIRE ≥1 acceptance string (validator-enforced);
write them GWT-shaped in one line: `"Given X, when Y, then Z"`.

**Don't use when:** the item produces an artifact whose acceptance is a
property list — then plain assertion strings are clearer, but keep the
"then"-style observable phrasing so they stay gradeable.

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
