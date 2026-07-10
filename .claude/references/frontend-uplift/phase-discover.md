# Phase 1 — DISCOVER (two parallel waves)

**Purpose:** dispatch scouts in TWO waves. **Wave 1 (evidence)** — visual-scout (drives the live preview) + current-state-critic (reads the code) — run concurrently and land first. **Wave 2 (direction/outward)** — the art-direction-scout (which READS the Wave-1 evidence to ground its frame) plus the library + inspiration scouts — run concurrently after Wave 1. The **art-direction-scout is dispatched in EVERY mode** (it produces the design FRAME — thesis + 3 directions + BAN list + surface map — that Phase 2 opens with and Axis 11 enforces; dropping it re-creates the cookie-cutter output the pipeline exists to prevent). Parallel WITHIN a wave; never serialize a wave into one-at-a-time dispatch.

## Preflight — verify dev server is up

BEFORE dispatching the visual scout, the slash command body MUST run:

```bash
.claude/scripts/frontend-uplift/ensure-preview-up.sh
```

If exit status != 0, halt and surface the recovery hint (`make up` — starts the FastAPI+Jinja2+htmx server on 127.0.0.1:7733; no separate frontend process exists by design per CLAUDE.md §4.7). Re-invoke `/frontend-uplift <ID>` after starting the server — the init-uplift.sh script is idempotent, so it picks up where it left off.

The other scouts (library, inspiration, current-state-critic, art-direction) do NOT depend on the dev server.  In principle they could fire even if the preview is down.  In practice, the orchestrator should still halt the whole phase on preflight failure — partial discovery without visual evidence is low-signal (and the art-direction-scout's frame is weaker without the visual manifest).

## Dispatch matrix (art-direction fires in EVERY mode; experiential-scout BLOCKED by default)

arXMCP's `/ui/` is entirely **S-2 tool** class (overlay §9), so the **experiential-scout is NOT dispatched by default**.  `--surface` defaults to `tool`.

| Mode | Wave 1 (evidence) | Wave 2 (direction / outward) | Total |
|---|---|---|---|
| **standard** (default) | visual-scout + current-state-critic | art-direction-scout + library-scout + inspiration-scout | 5 |
| **lean** | visual-scout + current-state-critic | art-direction-scout | 3 |
| **deep** | visual-scout + current-state-critic (**critic at `model: opus`, effort high**) | art-direction-scout + library-scout + inspiration-scout | 5 |
| **experiential** | visual-scout + current-state-critic | art-direction-scout + library-scout + inspiration-scout + experiential-scout | 6 |

`experiential` mode adds the experiential-scout **only** when `--surface mixed|experiential` is ALSO passed — and since arXMCP has no S-1/S-1m surface, the art-direction-scout's surface map classifies everything S-2 and the challenger's AP-1/2/3 / Axis 11 will BLOCK any experiential candidate.  Treat the mode as a documented no-op on the default tool surface.

Set the mode via `checkpoint.py <ID> --set discover_mode='"standard"'` BEFORE dispatch so resume can see the original choice.  **Do NOT `--set surface`** — it is not a seeded state field (`checkpoint.py --set` rejects unknown keys); surface is tracked in-session and defaults to `tool` (arXMCP is constitutionally S-2 tool-class, overlay §9).

## Dispatch protocol (CRITICAL — two waves, parallel within each)

Fire **Wave 1's agents in one assistant message**, wait for both to return, then fire **Wave 2's agents in one assistant message**.  Sequential dispatch WITHIN a wave destroys diversity and doubles wall-clock; collapsing the two waves into one blind turn starves the art-direction-scout of the evidence it grounds its frame on.

Each agent's system prompt lives in `.claude/agents/frontend-uplift-*.md` (the canonical source — `references/frontend-uplift/agent-prompts.md` is now a thin pointer to those files + the placeholder contract). The orchestrator dispatches each agent via `subagent_type: frontend-uplift-<role>` and supplies a short user prompt with these substitutions:

- `{ID}` → uplift slug
- `{UPLIFT_BRIEF}` → `state.uplift_brief` verbatim
- `{BRIEF_PATH}` → `.claude/notes/frontend-uplifts/{ID}/discover/<agent-short-name>-brief.md`
- `{SCREENSHOT_DIR}` → `state.screenshot_dir` (only used by the visual scout)
- `{PAGES}` → comma-joined `state.pages_to_walk` (empty = default 3-route + 1-fragment set; see arxmcp-design-system.md §3 + §9 surface map)
- `{SURFACE}` → the parsed `--surface` (default `tool`) — passed to the art-direction-scout (and experiential-scout if fired)
- `{TARGETS}` → exemplar URLs from `--brief` (empty = the canonical REF-1..9 library, frontend-design-language §4) — art-direction-scout
- **Wave-2 evidence feed:** the art-direction-scout also receives the Wave-1 outputs — the `visual-scout-brief.md` + `{SCREENSHOT_DIR}/*.png` (it Reads the PNGs) and the `current-state-critic-brief.md` (its `{VISUAL_MANIFEST}` / `{CURRENT_STATE_BRIEF}` inputs). If screenshots are absent (preview degraded), it scores from source at `~ inferred`/`✓ code` tiers and says so.

Use `isolation: worktree` on every agent — each gets a worktree-isolated repo state.  Visual-scout uses the live frontend at `http://127.0.0.1:7733`; that's a process-external resource (worktrees don't affect it).

## Subagent_type and model

| Agent | Wave | Sub-agent type | Model | Tools beyond default |
|---|---|---|---|---|
| visual-scout | 1 | `frontend-uplift-visual-scout` | sonnet | Add `Bash` (for image-tool inspection), the browser-preview family — `mcp__Claude_Browser__*` (current) / `mcp__Claude_Preview__*` (legacy alias); load via ToolSearch if deferred |
| current-state-critic | 1 | `frontend-uplift-current-state-critic` | sonnet (deep → **opus**) | Standard (no Web tools needed; codebase-only) |
| art-direction-scout | 2 | `frontend-uplift-art-direction-scout` | **opus** (effort high) | `Read + Grep + Glob + Bash + WebSearch + WebFetch + Write + Edit` (reads Wave-1 briefs + PNGs) |
| library-scout | 2 | `frontend-uplift-library-scout` | sonnet | Standard `Bash + Read + Grep + Glob + WebSearch + WebFetch + Write` |
| inspiration-scout | 2 | `frontend-uplift-inspiration-scout` | sonnet | Same as library-scout |
| experiential-scout (only on `--mode experiential` + `--surface mixed\|experiential`) | 2 | `frontend-uplift-experiential-scout` | sonnet | Same as library-scout |

## Default page set (visual-scout — 3 routes + 1 fragment)

arXMCP's operator console is small by design (CLAUDE.md §4.7 forbids a Node/npm
build chain — the UI is 3 Jinja2 templates + a single CSS file + vendored htmx).
When `pages_to_walk` is empty, the visual scout walks:

1. `/ui/` — landing (notebook list + create form)
2. `/ui/notebooks/<seeded-slug>` — detail (paper list, URL paste, upload, ingest, rename, delete)
3. `/ui/notebooks/<seeded-slug>/papers/<paper_id>/preview` — ar5iv preview (tight CSP)
4. `/ui/status-badge` — operability fragment (the footer badge poll)

If the target deployment is empty, the visual scout MUST seed a notebook + paper
via `POST /ui/api/notebooks` + `POST /ui/api/notebooks/<slug>/papers` before
walking routes 2 and 3.

User override via `init-uplift.sh --pages "/foo,/bar"` replaces this list verbatim
(stored in `state.pages_to_walk`).

## Per-route capture spec (visual-scout)

For each route:
- Viewport screenshot at 1440×900 → `{SCREENSHOT_DIR}/<route-slug>-desktop.png`
- Mobile screenshot at 390×844 (iPhone 12) → `{SCREENSHOT_DIR}/<route-slug>-mobile.png`
- DOM snapshot of `<main>` (text content + element hierarchy)
- Console-log dump (warnings + errors)
- Network summary (4xx/5xx, slow >1500ms)

`<route-slug>` derivation: strip leading `/`, replace remaining `/` with `-`, fall back to `home` for `/`. E.g. `/ui/notebooks/seed-notebook` → `ui-notebooks-seed-notebook`.

## Returning briefs into state

When an agent returns, the main session:

```bash
.claude/scripts/frontend-uplift/checkpoint.py <ID> --append agents_returned='"<agent-name>"'
.claude/scripts/frontend-uplift/checkpoint.py <ID> --append discover_briefs='"<brief-path>"'
```

When `len(agents_returned) == len(agents_dispatched)`:

```bash
.claude/scripts/frontend-uplift/checkpoint.py <ID> discover-complete
```

## Severity rubric (visual-scout + current-state-critic)

| Severity | Meaning |
|---|---|
| **CRITICAL** | Visual gap that erodes credibility on first load (e.g., page genuinely broken, or hero has visible jank).  Rare. |
| **HIGH** | Visual gap that scholarly / dev-tool comparators all have and arXMCP lacks (e.g., no `:focus-visible` styling, no `prefers-reduced-motion` gate). |
| **MEDIUM** | Quality-of-life gap that compounds across many routes. |
| **LOW** | Cosmetic / single-surface paper-cut. |

Calibrate HONESTLY.  A clean route with no gaps is a credible result.

## Failure modes

- **Visual scout's preview tool can't reach 127.0.0.1:7733** → preflight should have caught this; if it failed silently, the visual scout returns a "preview-unreachable" brief and the orchestrator surfaces to the user before advancing state.
- **A library / inspiration scout returns a thin brief** (< 5 candidates) → re-dispatch ONCE with a stricter prompt suffix.  Accept the second attempt's result; weight accordingly in synthesis.
- **A scout hangs for >30 min** → kill the task; re-dispatch with the same prompt.
- **The art-direction-scout fails** → the frame is PROVISIONAL; the synthesizer builds one from overlay §9 + canon §8 and says so, and the challenger's Axis 11 treats a frameless catalog as a run-level BLOCKER.
- **All scouts in a wave fail** → halt; surface to the user (Wave 2 cannot proceed without Wave-1 evidence).
