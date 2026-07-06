# Phase 2 — DECOMPOSE

**Goal:** turn the refined objective into 2–6 vertically-sliced epics that
each ship an observable change in ≤6 weeks.

**Writes:** epic entries in `items:` of `plans/<slug>/roadmap.yaml`.
Advances `phase: refined → decomposed`.

## Step-by-step

### 1. Pick the technique

Default is **vertical slicing + enabler epics**. Reach for the long tail
(`roadmap-frameworks.md`) only when the problem shape demands it:

| Problem shape | Technique | Why |
|---|---|---|
| Multi-step user-visible journey | User Story Mapping (Patton) | preserves end-to-end coherence |
| Bounded contexts unclear | Event Storming (Brandolini) | surfaces domain seams |
| Output→outcome link fuzzy | Impact Mapping (Adzic) | kills "seems useful" features |
| Anything else | **Vertical slicing** | default; cheapest habit |

Non-default choice ⇒ one-sentence rationale in the epic summaries.

### 2. Slice vertically

Each epic must cut through every relevant layer (storage → service → UI
when applicable) and deliver something observable on completion. Size to
≤6 weeks at one-person pace — S/M/L; an XL epic gets split before it lands
in the file.

**Anti-pattern: horizontal slicing** (schema-first / API-second / UI-last).
Nothing is demoable until the last layer; the downstream critique phase has
nothing to grade; integration risk piles up.

### 3. Tag value-vs-enabler

Every epic carries `value` or `enabler` in `tags:`. `value` = observable
user/system change (target ≥60% of epics). `enabler` = pure infrastructure
that unblocks named downstream value epics. Over ~40% enabler means the
outcome thread is lost — re-slice. A pure-enabler chain is a reorganization
disguised as a roadmap.

### 4. INVEST check (per epic)

| Letter | Question | Failure signal |
|---|---|---|
| Independent | Lands without siblings half-done? | "e2 needs e1's schema to compile" — split or merge |
| Negotiable | Scope can shift mid-flight? | all-or-nothing ⇒ too big, split |
| Valuable | Observable change deliverable? | enabler with no named value consumer |
| Estimable | Can you T-shirt it? | "no idea" ⇒ needs a Phase 3 spike |
| Small | ≤6 weeks solo? | XL ⇒ SPIDR / story-map split |
| Testable | Will critique have something to grade? | no diff ⇒ not an epic |

Failing two letters ⇒ re-cut.

### 5. Draft MoSCoW priorities

Assign `priority: must|should|could|wont` now. The validator enforces
must ≤60% of non-wont epics at every phase — Phase 3 re-checks with
`roadmap-score-moscow.py` and RICE-ranks on top.

### 6. Dependency graph

`depends_on` between epics only, and only real predecessors. Must be a DAG
(validator runs Kahn's). A forming cycle means two epics are too coupled —
merge or split.

## Output shape (items appended to roadmap.yaml)

```yaml
items:
  - id: arxmcp-v2-search-e1
    kind: epic
    title: "Index core"
    summary: "Chunking, embedding, and on-disk index for the corpus — vertical slice to a queryable index."
    priority: must
    size: M
    tags: [value, index, infra]

  - id: arxmcp-v2-search-e2
    kind: epic
    title: "Query layer"
    summary: "Hybrid BM25+vector retrieval exposed as MCP search tools."
    priority: should
    size: M
    depends_on: [arxmcp-v2-search-e1]
    tags: [value, search, mcp]
```

Epics are top-level: `kind: epic`, no `parent` (validator rejects parented
epics). No milestones/tasks/spikes in Phase 2 — that is SEQUENCE's job.

## Auto-advance vs gate

| Condition | Action |
|---|---|
| Every epic INVEST-clean; DAG holds; ≥60% value; all ≤L | **Auto-advance** — validate, then `--advance decomposed` |
| ≥2 credible decomposition cuts (by-feature vs by-layer; vertical vs hybrid) | **GATE.** Surface both with tradeoffs; wait for `[a]`/`[b]`. |
| Enabler epics > 40% | **Not a gate** — re-slice to expose value sooner. |
| An epic is XL | **Not a gate** — SPIDR and re-cut before writing. |

## Hard rules

- **IDs `<slug>-eN`, write-once.** Regeneration carries every existing id;
  new epics take the next free N; drops become `status: dropped` +
  `retired:` entry. Never renumber.
- **No milestone/task decomposition in Phase 2.**
- **`depends_on` targets must exist** — the validator rejects dangling refs.
- **Respect the wont list** — an epic that implements a wont item is a scope
  breach, not initiative.
- **Validate after every write** (`roadmap-validate.py --json`); watch
  `item-ids`, `deps`, `must-cap`.
