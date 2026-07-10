# /frontend-uplift

Run the canonical 4-phase arXMCP operator-console modernization pipeline:
**Discover (parallel scouts — incl. an ART-DIRECTION frame + a live-preview walk) → Synthesize → Challenge → Prioritize**

Usage:
```
/frontend-uplift                                            # ask for uplift id
/frontend-uplift <id>
/frontend-uplift <id> --brief "verbatim user scope"
/frontend-uplift <id> --pages "/foo,/bar"                   # override the default 3-route + 1-fragment set
/frontend-uplift <id> --mode lean|standard|deep|experiential  # default standard
/frontend-uplift <id> --surface tool|mixed|experiential|auto  # default tool (arXMCP is an S-2 console)
/frontend-uplift <id> --workflow                            # OPT-IN Gen-2 background Workflow path (off by default)
/frontend-uplift <id> --resume                              # resume from current state
```

`<id>` is a free-form slug.  Convention: date-tagged scope, e.g. `2026q2-jinja-polish` or `status-badge-a11y-v1`.  If no id is given, STOP and ask: "What uplift id should I use?"

The pipeline answers: **"Where can arXMCP's `/ui/` operator console become more attractive, sleek, and modern — with a real ART-DIRECTION THESIS (not cookie-cutter shadcn/AI-dashboard polish) — measured against 2026 SOTA scholarly / dev-tool platforms, vendor-able modern CSS / native-Web APIs, and the tool-motion vocabulary — without violating CLAUDE.md §4.7 (no-build-chain), the 8-CSS-variable token system, the CSP, or WCAG AA?"**  It does NOT produce code; it produces a ranked candidate report ready to feed `/milestone-pipeline` (single-candidate) or `/roadmap` (multi-candidate program).

**Standing default — art-direction thesis before ranking (the anti-cookie-cutter mandate).** Every run
establishes a **design frame BEFORE candidates are ranked**: the `frontend-uplift-art-direction-scout`
(dispatched in EVERY mode, lean included) reads the shared canon
(`.claude/references/frontend-design-language.md`) AND the repo house-thesis overlay
(`.claude/references/frontend-uplift/arxmcp-design-system.md` §9) and produces a visual thesis + 3
divergent directions + the active BAN-1..15 list + a surface map. Synthesis OPENS with that frame; the
challenger's Axis 11 blocks frameless/template output; Phase 4 ranks in PORTFOLIO LANES. **Polish without
direction is the failure this pipeline exists to prevent.** (For SHIPPING a designed surface in-session —
thesis → implement → self-score, not a discovery report — use the `/frontend-design` skill instead.)

**Standing default — the motion-jobs test (no quota).** Every motion candidate names the job it serves —
orientation / causality / feedback / continuity (motion-vocabulary §0). No job, no motion; there is no
quota to fill. Native/incumbent facility first. On arXMCP this means **CSS transitions + htmx swap
semantics** (`.htmx-request` / `.htmx-swapping` / `.htmx-settling` hooks, View Transitions on same-doc
swaps) — **never a JS animation engine** (anime.js / GSAP / Framer are npm-installable and thus automatic
Phase-3 BLOCKERs here; motion-vocabulary's web-library rows do not apply — read the JOB, map it to CSS/htmx).

**Standing default — surface awareness.** arXMCP's `/ui/` is entirely **S-2 tool** class (overlay §9
surface map). Experiential motion (parallax / scroll-zoom / WebGL / cursor theater — `EXP-*`, AP-1/2/3/5)
is **BLOCKED**; the `frontend-uplift-experiential-scout` is **NOT dispatched by default**. There is no
S-1/S-1m surface here to host it (loopback-only, no public/login/marketing surface). Borrow the reference
sites' *discipline* (hierarchy, type, whitespace, authored transitions), never their scroll theater.

---

## Step 0 — Initialize state + canon freshness

```bash
.claude/scripts/frontend-uplift/init-uplift.sh <ID> [--brief "<verbatim user brief>"] [--pages "/foo,/bar"]
mkdir -p .claude/agent-memory/frontend-uplift-art-direction-scout \
         .claude/agent-memory/frontend-uplift-visual-scout \
         .claude/agent-memory/frontend-uplift-library-scout \
         .claude/agent-memory/frontend-uplift-inspiration-scout \
         .claude/agent-memory/frontend-uplift-experiential-scout \
         .claude/agent-memory/frontend-uplift-current-state-critic \
         .claude/agent-memory/frontend-uplift-challenger
```

Parse `--mode` (default `standard`), `--surface` (default `tool`), `--workflow` (default OFF) from the
argument string. Persist the **mode** to the existing `discover_mode` state field (for `--resume`):

```bash
.claude/scripts/frontend-uplift/checkpoint.py <ID> --set discover_mode='"standard"'   # or lean|deep|experiential
```

`--surface` is tracked **in-session only** — do NOT `--set surface` (it is not a seeded state field;
`checkpoint.py --set` rejects unknown keys). arXMCP is constitutionally **S-2 tool-class** (overlay §9:
every `/ui/` surface is S-2), so surface defaults to `tool` on resume — the flag exists only as the
`mixed|experiential` escape hatch, and even then the frame + challenger keep it S-2 in practice.

- If the state file already exists, the script prints `state already exists (phase=X) — resuming`.
- If resuming: run `status.sh` first, then skip to the appropriate phase below.
- The `mkdir -p` ensures per-agent memory dirs exist (including the two newly-synced scouts); safe to re-run.

**Canon freshness (advisory — surface loudly, NEVER blocks):**

```bash
python3 .claude/scripts/frontend-uplift-canon-lint.py check --root .
```

Report the result plainly (stamps / required sections / token collisions). It is advisory only —
a stale/failing lint does not halt the run; it tells the operator the taste canon may need a refresh.

```bash
.claude/scripts/frontend-uplift/status.sh <ID>
```

Read `.claude/references/frontend-uplift/state-schema.md` only if you need to inspect or write a field the scripts don't cover.

---

## Step 1 — Discover (two parallel waves)

Read `.claude/references/frontend-uplift/phase-discover.md` once at phase start.

### 1a — Preflight: ensure the dev server is up (REQUIRED)

The visual scout drives the live frontend at `http://127.0.0.1:7733`.  Before dispatching, run:

```bash
.claude/scripts/frontend-uplift/ensure-preview-up.sh
```

If exit status != 0, surface the recovery hint (`make up` — starts the FastAPI+Jinja2+htmx server; no separate frontend process exists by design, CLAUDE.md §4.7) and HALT before dispatching any agent.  Re-invoke `/frontend-uplift <ID>` after the dev server is up — `init-uplift.sh` is idempotent and `status.sh` will show the phase ready to advance.

### 1b — Mode → agent matrix (art-direction fires in EVERY mode)

The **art-direction-scout is dispatched in every mode** (never dropped — taste IS the deliverable gap).
Because arXMCP's default surface is **tool (S-2)**, the **experiential-scout is NOT dispatched by default**.

| Mode | Wave 1 (evidence) | Wave 2 (direction / outward) | Total |
|---|---|---|---|
| **lean** | visual-scout + current-state-critic | art-direction-scout | 3 |
| **standard** (default) | visual-scout + current-state-critic | art-direction-scout + library-scout + inspiration-scout | 5 |
| **deep** | visual-scout + current-state-critic (**critic bumped to `model: opus`, effort high**) | art-direction-scout + library-scout + inspiration-scout | 5 |
| **experiential** | visual-scout + current-state-critic | art-direction-scout + library-scout + inspiration-scout + experiential-scout | 6 |

**`experiential` mode is a documented no-op on the default tool surface.** The experiential-scout only
fires when BOTH `--mode experiential` AND `--surface mixed|experiential` are passed. Since arXMCP has no
S-1/S-1m surface (overlay §9), even then the art-direction-scout's surface map will classify everything
S-2 and the challenger's Axis 11 / AP-1/2/3 will BLOCK any experiential candidate. Offer the mode for
completeness; expect it to collapse to `standard`.

### 1c — Wave 1: evidence scouts (one turn)

Dispatch **visual-scout + current-state-critic** in ONE assistant turn (two `Agent` tool blocks),
`subagent_type` = the agent name, `isolation: worktree`. Model: `sonnet` (in `deep` mode dispatch
current-state-critic at `model: opus`). The canonical SYSTEM prompts live in the agent files
(`.claude/agents/frontend-uplift-*.md`); the orchestrator's per-agent USER prompt supplies the
placeholders `{ID}`, `{UPLIFT_BRIEF}`, `{BRIEF_PATH}`, `{SCREENSHOT_DIR}`, `{PAGES}` (see
`references/frontend-uplift/agent-prompts.md` for the placeholder contract).

| Agent | Brief path |
|---|---|
| `visual-scout` | `.claude/notes/frontend-uplifts/<ID>/discover/visual-scout-brief.md` |
| `current-state-critic` | `.claude/notes/frontend-uplifts/<ID>/discover/current-state-critic-brief.md` |

Wait for both to return before Wave 2 — the art-direction-scout consumes their evidence.

### 1d — Wave 2: direction + outward scouts (one turn), fed Wave-1 evidence

Dispatch the wave-2 set for the mode (see matrix) in ONE assistant turn. The **art-direction-scout**
(`model: opus`, effort high) reads the shared canon + the repo overlay §9 + the Wave-1 evidence, and
produces the run's design FRAME (thesis + 3 divergent directions + BAN list + surface map + 4–8
direction-defining candidates). Supply it these placeholders:

- `{ID}`, `{UPLIFT_BRIEF}` → run id + verbatim brief
- `{SURFACE}` → the parsed `--surface` (default `tool`)
- `{BRIEF_PATH}` → `.claude/notes/frontend-uplifts/<ID>/discover/art-direction-scout-brief.md`
- `{TARGETS}` → any exemplar URLs from `--brief` (empty = the canonical REF-1..9 library, design-language §4)
- Wave-1 evidence: the `visual-scout-brief.md` + `<ID>/screenshots/*.png` (it Reads the PNGs) and the `current-state-critic-brief.md` (its `{VISUAL_MANIFEST}` / `{CURRENT_STATE_BRIEF}` inputs; if screenshots are absent it scores from source at `~ inferred`/`✓ code` tiers and says so)

| Agent | Brief path |
|---|---|
| `art-direction-scout` | `.claude/notes/frontend-uplifts/<ID>/discover/art-direction-scout-brief.md` |
| `library-scout` | `.claude/notes/frontend-uplifts/<ID>/discover/library-scout-brief.md` |
| `inspiration-scout` | `.claude/notes/frontend-uplifts/<ID>/discover/inspiration-scout-brief.md` |
| `experiential-scout` (only if `--mode experiential` + `--surface mixed\|experiential`) | `.claude/notes/frontend-uplifts/<ID>/discover/experiential-scout-brief.md` |

The **library-scout's output space is vendored, self-hosted, dependency-free CSS/JS only** (htmx is
already vendored). It must NOT propose anything requiring npm / a bundler / a CDN asset / an SPA
framework — those are automatic Phase-3 BLOCKERs (CLAUDE.md §4.7). Its agent file already pins this;
keep the constraint front-of-mind when reading its brief.

Record each dispatch and advance state:
```bash
for agent in visual-scout current-state-critic art-direction-scout library-scout inspiration-scout; do
  .claude/scripts/frontend-uplift/checkpoint.py <ID> --append agents_dispatched="\"$agent\""
done
.claude/scripts/frontend-uplift/checkpoint.py <ID> discover-running
```
(In `lean`, dispatch only `visual-scout` + `current-state-critic` + `art-direction-scout`. Add
`experiential-scout` to the loop only when the experiential combination is explicitly requested.)

### 1e — Return briefs

As each agent returns:
```bash
.claude/scripts/frontend-uplift/checkpoint.py <ID> --append agents_returned='"<agent-name>"'
.claude/scripts/frontend-uplift/checkpoint.py <ID> --append discover_briefs='"<brief-path>"'
```

When all dispatched agents have returned:
```bash
.claude/scripts/frontend-uplift/checkpoint.py <ID> discover-complete
```

---

## Step 2 — Synthesize (main session) — OPENS with the design frame

Read `.claude/references/frontend-uplift/phase-synthesize.md` once at phase start.

```bash
.claude/scripts/frontend-uplift/checkpoint.py <ID> synthesize-running
```

Read EVERY brief end-to-end AND look at the screenshots under `.claude/notes/frontend-uplifts/<ID>/screenshots/`.  Build the unified modernization-candidate catalog at:
```
.claude/notes/frontend-uplifts/<ID>/artifacts/synthesis.md
```

**The synthesis OPENS by ADOPTING the art-direction-scout's frame** (thesis + chosen direction + BAN
list + surface map) as its first section — then places every candidate against it as
`[DIRECTION-DEFINING]` / direction-compatible / `[polish]`. A frameless catalog is a Phase-3 BLOCKER.
If the art-direction-scout failed, build a PROVISIONAL frame from the overlay §9 + canon §8 and say so.

Use the fixed candidate-entry shape and taxonomy from `phase-synthesize.md`.  Deduplicate across briefs.  Surface FOUNDATIONAL candidates (the ones others depend on — e.g. the `prefers-reduced-motion` gate unlocks every animation candidate; `:focus-visible` unlocks every interactive-affordance candidate — **note: both already shipped in `app.css`, so verify before flagging as net-new**).  Cross-link tool-motion vocabulary `[MOT-N]` primitives from `.claude/references/frontend-uplift-motion-vocabulary.md`.

```bash
.claude/scripts/frontend-uplift/checkpoint.py <ID> --set synthesis_path='".claude/notes/frontend-uplifts/<ID>/artifacts/synthesis.md"'
.claude/scripts/frontend-uplift/checkpoint.py <ID> --set candidate_count=<N>
.claude/scripts/frontend-uplift/checkpoint.py <ID> synthesize-complete
```

---

## Step 3 — Challenge (single sub-agent) — 11-axis checklist

Read `.claude/references/frontend-uplift/phase-challenge.md` once at phase start.

```bash
.claude/scripts/frontend-uplift/checkpoint.py <ID> challenge-running
```

Single `Agent` call with `subagent_type: frontend-uplift-challenger`, `model: opus` (effort high),
`isolation: worktree`. The canonical Challenger SYSTEM prompt is the agent file at
`.claude/agents/frontend-uplift-challenger.md`; the orchestrator passes a short USER prompt supplying
`{ID}`, `{SYNTHESIS_PATH}`, `{CHALLENGE_PATH}` (see `agent-prompts.md` for the placeholder contract).

The challenger walks the **11-axis** FRONTEND checklist — the arXMCP-stack axes 1–10 (no-build-chain,
`prefers-reduced-motion`, a11y regression, vendored-asset weight, CSP impact, mobile, 8-token discipline,
effort honesty, motion anti-patterns, sequencing) PLUS **Axis 11 — distinctiveness / anti-template**:
score the proposal against BAN-1..15 + the §10 cookie-cutter rubric (it Reads
`.claude/references/frontend-design-language.md` directly — there is no `get_reference` tool here) and
BLOCK a frameless or template-leaning synthesis. The challenger writes to:
```
.claude/notes/frontend-uplifts/<ID>/artifacts/challenge.md
```

Record:
```bash
.claude/scripts/frontend-uplift/checkpoint.py <ID> --set challenge_path='".claude/notes/frontend-uplifts/<ID>/artifacts/challenge.md"'
.claude/scripts/frontend-uplift/checkpoint.py <ID> --set challenge_finding_counts='{"critical":N_BLOCKER,"high":N_MAJOR,"medium":N_MINOR,"low":N_CLEAN}'
.claude/scripts/frontend-uplift/checkpoint.py <ID> challenge-complete
```

(BLOCKER → critical, MAJOR → high, MINOR → medium, NONE → low.)

---

## Step 4 — Prioritize (main session) — PORTFOLIO LANES

Read `.claude/references/frontend-uplift/phase-prioritize.md` once at phase start.

```bash
.claude/scripts/frontend-uplift/checkpoint.py <ID> prioritize-running
```

Run in the **main session** (NOT a sub-agent) — the user reviews this report directly.

Read synthesis + challenge end-to-end.  **Assign every candidate to exactly ONE portfolio lane**, then
compute RICE-light **only WITHIN a lane** (cross-lane ranking mathematically buries structural design
under XS polish):

1. **`a11y-safety-debt`** — MANDATORY lane, listed FIRST, never ranked away (WCAG / reduced-motion / focus / CSP / autoescape debt).
2. **`signature-direction`** — the art-direction frame's direction-defining moves (what makes it recognizably arXMCP, not a template).
3. **`foundations`** — token/CSS-architecture work others depend on.
4. **`workflow`** — operator-workflow improvements on the dense surfaces.
5. **`polish`** — cosmetic paper-cuts.

**RICE-light** (R 1/3/10 × Visual-Impact 0.5/1/3 × Triangulation-Confidence 0.3–1.0 / Effort-by-tshirt 0.25–8), computed within each lane.  Apply challenger penalties (drop on un-redesigned BLOCKER; halve on redesigned BLOCKER; -25% on MAJOR; no adjustment on MINOR / NONE) AND a **foundational-candidate bonus** (+30% on candidates synthesis flagged as foundational).  Write:
```
.claude/notes/frontend-uplifts/<ID>/artifacts/final-report.md
```

with these sections in order:

1. Executive summary (top pick per lane, theme, caveat)
2. Design frame recap (thesis + chosen direction + BAN list — carried from synthesis)
3. Quick-glance ranking table (grouped by lane; a11y-safety-debt lane first)
4. Lane-by-lane detail (a11y-safety-debt FIRST; then signature-direction, foundations, workflow, polish — synthesis entry + challenger objections + within-lane RICE + DAG note)
5. Recommended next steps (a11y-safety-debt first; then 1–2 `/milestone-pipeline`-ready; `/spike` candidates; parking lot)
6. Visual evidence index (screenshots × candidates)
7. Honest limitations
8. Cross-reference index

**Always OFFER but NEVER auto-invoke `/milestone-pipeline` or `/roadmap`.**  Include the offer footer when candidates clear the documented thresholds; the user types the next command if they want to proceed.

Record:
```bash
.claude/scripts/frontend-uplift/checkpoint.py <ID> --set final_report_path='".claude/notes/frontend-uplifts/<ID>/artifacts/final-report.md"'
.claude/scripts/frontend-uplift/checkpoint.py <ID> --set ranked_candidates='[{"id":"UPL-1","title":"...","lane":"a11y-safety-debt","rice":52.0,"rank":1},...]'
.claude/scripts/frontend-uplift/checkpoint.py <ID> complete
```

Print a 5-line final summary: uplift id, total candidates, lanes populated, top pick per lane, BLOCKER count, recommended next step.

---

## Optional Gen-2 path — `--workflow` (OPT-IN, off by default)

arXMCP ships the synced Gen-2 machinery (`.claude/scripts/frontend-uplift-workflow.mjs`, the
`pipeline-synthesizer` / `pipeline-prioritizer` agents). It is **not the default** — the Gen-1
in-session pipeline above is the tested, canonical path. When (and ONLY when) the user passes
`--workflow`:

1. **Step 0 / 0.5 STILL run in the MAIN session first** — the repo's own `init-uplift.sh` +
   `ensure-preview-up.sh` (and the canon lint). The Workflow JS cannot exec scripts, drive the browser,
   or seed a notebook.
2. Then invoke the **Workflow tool** with
   `scriptPath: ".claude/scripts/frontend-uplift-workflow.mjs"` and
   `args: { id, brief, mode, surface, pages, targets, url }`. It runs DISCOVER → SYNTHESIZE → CHALLENGE
   → PRIORITIZE as a background workflow, offloading SYNTHESIZE/PRIORITIZE to the tool-capped
   `pipeline-synthesizer` / `pipeline-prioritizer` agents.
3. Record the returned `runId` to `.claude/notes/frontend-uplifts/<ID>/workflow-run-id.txt` for
   `--resume` (`Workflow({ scriptPath: ..., resumeFromRunId: "<its content>" })`).

> **The Workflow tool requires the user's explicit opt-in per run** — `--workflow` is never taken
> automatically, and if the harness build provides no Workflow tool, do NOT re-inline the transforms;
> fall back to the Gen-1 in-session path above.

---

## State machine

```
init → discover-running → discover-complete
     → synthesize-running → synthesize-complete
     → challenge-running → challenge-complete
     → prioritize-running → complete
```

`status.sh` prints elapsed time per phase, which agents are pending, and the count of screenshots captured.

---

## Common rationalizations (anti-pattern guard)

| Tempting belief | Reality |
|---|---|
| "Skip the art-direction-scout in lean mode — it's just taste." | Taste IS the deliverable gap.  The art-direction-scout is in EVERY mode; dropping it re-creates the cookie-cutter output this pipeline exists to prevent. |
| "Better cards, nicer shadows, some motion — that's the uplift." | Polish on an undirected layout is still the generic AI dashboard (design-language §1).  The FRAME comes first (thesis + direction + BAN list), THEN candidates.  A run whose top candidates are all `[polish]` must SAY so (Phase 4). |
| "Skip the preview-up check — the agents can figure it out." | NO.  The visual scout can't run without the dev server.  Preflight is load-bearing. |
| "Fire all scouts in one blind wave." | NO.  Two waves: Wave 1 (visual + current-state) produces the evidence the art-direction-scout reads in Wave 2.  Parallel WITHIN a wave; never serialize a wave into one-at-a-time. |
| "Synthesize from TL;DRs only." | Triangulation lives in matching specific claims across briefs.  Read every brief end-to-end + look at screenshots + OPEN with the frame. |
| "Skip the challenger — the synthesis is good enough." | Synthesis biases toward "more polish".  Without the 11-axis adversary (incl. Axis 11 distinctiveness) Phase 4 ranks aspirational candidates blind to no-build-chain compliance / a11y / CSP / template risk. |
| "Cross-rank all candidates by RICE." | NO.  Portfolio lanes first (a11y-safety-debt mandatory + first), RICE only WITHIN a lane — else structural design is buried under XS polish. |
| "Auto-invoke /milestone-pipeline on the top candidate." | NEVER.  Offer-and-wait. |
| "Inflate severity to surface more findings." | The challenger's NONE is a credible result.  Aim 30–60% NONE; padding erodes signal. |
| "Propose Framer Motion / anime.js / GSAP / shadcn / Tailwind to upgrade the look." | Automatic Phase-3 BLOCKER.  CLAUDE.md §4.7 forbids npm / Node / build chain.  Motion here = CSS transitions + htmx swap hooks + View Transitions; read the motion JOB, map it to the native facility. |
| "Propose parallax / scroll-zoom / WebGL on `/ui/notebooks/<slug>`." | BAN-12 + AP-1/2/3 on an S-2 tool surface → challenger BLOCKS.  There is no S-1/S-1m surface in arXMCP; experiential motion has nowhere to live. |
| "Invent new color tokens beyond the 8 CSS variables." | Token-discipline violation.  Extend `frontend/static/app.css:4-19` explicitly — don't parallel-define. |
| "Re-propose `prefers-reduced-motion` / dark-mode / `:focus-visible` — the overlay §7 lists them as gaps." | Those SHIPPED in `ui-attractive-polish-m1..m5` (overlay §9 drift note).  Verify against the live `app.css` before flagging any as net-new. |

---

## Don'ts

- **Don't drop the art-direction-scout in any mode.**  The frame is the whole point.
- **Don't accept a frameless synthesis.**  Synthesis OPENS with the adopted frame; a bare catalog is an Axis-11 BLOCKER.
- **Don't run Phase 4 as a sub-agent** (Gen-1 path).  It needs the user's review surface.
- **Don't cross-rank lanes.**  RICE within a lane only; a11y-safety-debt is never ranked away.
- **Don't let the synthesizer write the challenge.**  Distinct roles.
- **Don't auto-invoke `/milestone-pipeline` or `/roadmap`.**  Offer-and-wait.
- **Don't skip the preflight `ensure-preview-up.sh` check.**  The whole Phase 1 hinges on a reachable dev server.
- **Don't dispatch the experiential-scout by default.**  arXMCP is S-2 tool-class; it fires only on an explicit `--mode experiential --surface mixed|experiential` and its output is expected to be BLOCKED.
- **Don't take `--workflow` automatically.**  The Gen-2 Workflow path is opt-in per run; the Gen-1 in-session path is the default.
- **Don't manufacture candidates.**  Every catalog entry traces to ≥1 discover brief.
- **Don't bypass `scripts/init-uplift.sh`.**  State directory naming is load-bearing.
- **Don't `git push` at any phase.**  Uplift artifacts are gitignored under `.claude/notes/frontend-uplifts/`.

---

## Sub-agent memory

All `frontend-uplift-*` agents (art-direction, visual, library, inspiration, experiential, current-state-critic, challenger) have `memory: project`.  Their memory accumulates under `.claude/agent-memory/<agent-name>/` across uplift runs.  Do NOT clear or overwrite these directories — they carry institutional memory (which directions survived challenge/production, which inspiration platforms have the richest signal, preview-tool corner cases, recurring synthesis blind spots).

---

## References

Phase references (`phase-discover.md`, `phase-synthesize.md`, `phase-challenge.md`, `phase-prioritize.md`), the agent-prompts source (`agent-prompts.md`), and the house-thesis overlay (`arxmcp-design-system.md` — §9 is the repo house thesis) are surfaced INLINE at their phase entries.  The **shared canon** the folded doctrine draws on (SYNCED — never edit these):

- `.claude/references/frontend-design-language.md` — THE taste canon: §1 anti-reference, §3 surface classes, §4 REF-1..9 library, §5 BAN-1..15, §6 premium-instrument spec (S-2), §8 direction seeds, §9 house-thesis contract, §10 cookie-cutter rubric, §14 evidence tiers + DQS
- `.claude/references/frontend-uplift-motion-vocabulary.md` — §0 surface model + motion-jobs test + `[MOT-N]` tool-motion tokens + §8 AP-1..7 anti-patterns
- `.claude/references/frontend-uplift-experiential-motion.md` — `[EXP-N]` experiential tokens (INERT here — no S-1/S-1m surface; retained for the `--surface mixed|experiential` escape hatch only)
- `.claude/references/frontend-uplift-source-registry.md` — exemplar sites + toolkit + art-direction reference index

Cross-cutting references the phase bodies don't already link:

- `.claude/references/frontend-uplift/state-schema.md` — `state.json` field reference
- `CLAUDE.md §4.7` — arXMCP architectural locks (no-build-chain / pure-ASGI / no-anthropic-SDK / no-fork / no-`assert`) — challenger axis #1
- `.claude/references/milestone-pipeline-critique-format.md` — canonical severity rubric
- `.claude/commands/milestone-pipeline.md` — single-candidate handoff target
- `.claude/commands/roadmap.md` — multi-candidate program handoff target
- `.claude/notes/06-mcp-server-design.md` § "Browser UI surface" — design tokens, templates, htmx swap patterns, the m4 status-badge, the tight preview CSP

**INERT-here machinery (retained, not deleted — say so rather than removing):** the synced
`.claude/scripts/frontend-uplift-mjs-lint.sh` (a Workflow-dialect syntax gate) only bites on the opt-in
`--workflow` path; and any **bundle-budget** axis from the upstream canon does not apply — arXMCP has no
bundler (the live axis here is *vendored single-file weight*, challenger axis 4, e.g. htmx's ~14 KB gz).
