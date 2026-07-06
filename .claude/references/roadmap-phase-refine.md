# Phase 1 — REFINE

**Goal:** turn a fuzzy brief into a sharp, evidence-backed problem statement
the rest of the pipeline can decompose without guessing.

**Writes:** `title`, `brief` (verbatim), `goal:` (and optionally `horizon:`),
plus provenance `generated_by:` and `generations:` in
`plans/<slug>/roadmap.yaml`. Advances `phase: init → refined`.

The refiner is the ONE sanctioned writer of the optional
`generated_by:`/`generations:` fields: it sets `generated_by` and appends
exactly one `generations` entry per revision (`rev` increments; existing
entries are never rewritten or deleted).

## Step-by-step

### 1. How-Might-We reframe

Restate the brief as ONE crisp HMW:

> "How might we **{do something concrete}** so that **{specific
> beneficiary}** can **{achieve a specific outcome}**?"

Rules:
- The middle clause names a real beneficiary (a persona, an agent, a
  downstream system) — not "the user" or "the platform".
- The outcome clause is observable — a metric, a test, or a user can
  confirm it.
- ≥2 credible reframings (different beneficiaries OR outcomes) is the
  Phase 1 gate: surface both with one-paragraph tradeoffs; do not pick alone.

### 2. Sharpening questions (3–5)

Answer from in-context evidence (conversation, codebase, `plans/`,
`CLAUDE.md`). An "I don't know" becomes a `must`-tier assumption — do not
ask the user yet.

1. **Who is this for, specifically?** Name them.
2. **What does success look like?** The single observable change.
3. **What are the real constraints?** Cite file paths (CLAUDE.md lines,
   configs) — "storage cap" alone is hand-wavy.
4. **What's been tried before?** Grep `plans/` for prior roadmaps at the
   same problem shape; cite `file:line`.
5. **Why now?** The triggering change (unblocked dependency, friction
   threshold, prior milestone landing).

### 3. Assumption tiering

Every claim about the world not yet evidence-backed gets exactly one tier:

| tier | meaning | action |
|---|---|---|
| `must` | wrong ⇒ the whole roadmap is invalid | ≤3-day spike in Phase 3. `validation:` REQUIRED (non-empty; validator-enforced) — name the spike or acceptance check. |
| `should` | wrong ⇒ one epic redesigned, not the roadmap | design a fallback at decomposition; `validation:` names the fallback or check |
| `might` | wrong ⇒ minor tweak | defer; `validation:` optional |

An untiered assumption is a forgotten `must` — the most dangerous kind.

### 4. Objective + key results + wont + evidence

- **objective** — one sentence, outcome-shaped, solo-appropriate. No OKR
  ritual scoring.
- **key_results** — ≥3 (validator-enforced), each leading-indicator shaped:
  a metric, a test outcome, or a user-observable change. "Ship X" is an
  output, not a result — if a KR can only be phrased that way, the outcome
  isn't real yet; go back to step 1.
- **wont** — ≥3 explicit non-goals, the most tempting ones verbatim. This is
  the load-bearing scope-discipline artifact.
- **evidence** — paths/links backing the framing (prior plans, notes, data).

## Output shape (YAML fields, Edit into roadmap.yaml)

```yaml
title: "arXMCP v2 — search index"
brief: |
  {verbatim brief — exactly as provided; NEVER paraphrased}
horizon: { start: 2026-07-06, end: 2026-08-14 }   # optional
goal:
  hmw: "How might we make the full corpus retrievable by meaning, not just filename?"
  objective: "Ship hybrid BM25+vector search over the full corpus as MCP tools."
  key_results:
    - "search_papers returns ranked results < 500 ms warm"
    - "Hybrid ranking beats BM25-only on the 20-query eval set"
    - "Full re-index embeds 0 unchanged chunks"
  assumptions:
    - tier: must
      text: "A local embedding model reaches acceptable recall on math text"
      validation: "spike-1 bake-off measures recall@10 on 20 canned queries"
    - tier: should
      text: "sqlite + mmap is fast enough; no external vector DB needed"
      validation: "m1 acceptance includes cold-start timing"
  wont:
    - "No cloud embedding APIs in v1"
    - "No cross-corpus federation"
    - "No UI beyond the MCP tool surface"
  evidence:
    - "plans/arxmcp-v1/roadmap.yaml — prior retrieval attempt"
generated_by: { agent: claude-fable-5, at: "2026-07-05" }
generations:
  - { rev: 1, at: "2026-07-05" }
```

`items:` stays untouched in Phase 1.

## Auto-advance vs gate

| Condition | Action |
|---|---|
| One credible HMW; every sharpening Q evidence-backed; every assumption tiered (musts with validation); wont ≥3 | **Auto-advance** — validate, then `--advance refined` |
| ≥2 credible HMW reframings | **GATE.** Surface both with tradeoffs; wait for `[a]`/`[b]`. |
| A sharpening Q has no in-context answer AND impacts decomposition | **GATE.** Ask the single most load-bearing question. |
| wont < 3 items | **Not a gate** — push until ≥3 exist. Empty wont = lazy scoping. |

## Hard rules

- **No code in Phase 1.** Output is a problem statement, not a design.
- **No paraphrasing the brief.** Verbatim in `brief:` — paraphrase biases
  every downstream decision.
- **Every constraint and prior-art citation has a file path.**
- **Every `must` assumption has a non-empty `validation:`** — the validator
  fails the file at phase ≥ refined otherwise.
- **Validate after every write** (`roadmap-validate.py --json`), and again
  after `--advance refined` (which activates the goal checks).
