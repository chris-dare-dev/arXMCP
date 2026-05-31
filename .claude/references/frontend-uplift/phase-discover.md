# Phase 1 — DISCOVER (parallel)

**Purpose:** dispatch 4 agents in a single assistant turn so they run concurrently in their own context windows.  The visual scout drives the live preview; the other 3 do code/web research in parallel.

## Preflight — verify dev server is up

BEFORE dispatching the visual scout, the slash command body MUST run:

```bash
.claude/scripts/frontend-uplift/ensure-preview-up.sh
```

If exit status != 0, halt and surface the recovery hint (`make up` — starts the FastAPI+Jinja2+htmx server on 127.0.0.1:7733; no separate frontend process exists by design per CLAUDE.md §4.7). Re-invoke `/frontend-uplift <ID>` after starting the server — the init-uplift.sh script is idempotent, so it picks up where it left off.

The other 3 scouts (library, inspiration, current-state-critic) do NOT depend on the dev server.  In principle they could fire even if the preview is down.  In practice, the orchestrator should still halt the whole phase on preflight failure — partial discovery without visual evidence is low-signal.

## Dispatch matrix

| Mode | Agents fired | When to choose |
|---|---|---|
| **standard** (default) | visual-scout + library-scout + inspiration-scout + current-state-critic (4) | Default — the canonical configuration |
| **lean** | visual-scout + current-state-critic (2) | When the user wants a quick scan and library/inspiration discovery is intentionally deferred |

Set via `checkpoint.py <ID> --set discover_mode='"standard"'` BEFORE dispatch so resume can see the original choice.

## Dispatch protocol (CRITICAL — single turn)

Fire **all selected agents in one assistant message** containing N `Agent` tool blocks.  Sequential dispatch destroys diversity and doubles wall-clock.

Each agent's system prompt lives in `.claude/agents/frontend-uplift-*.md` (the canonical source — `references/frontend-uplift/agent-prompts.md` is now a thin pointer to those files + the placeholder contract). The orchestrator dispatches each agent via `subagent_type: frontend-uplift-<role>` and supplies a short user prompt with these substitutions:

- `{ID}` → uplift slug
- `{UPLIFT_BRIEF}` → `state.uplift_brief` verbatim
- `{BRIEF_PATH}` → `.claude/notes/frontend-uplifts/{ID}/discover/<agent-short-name>-brief.md`
- `{SCREENSHOT_DIR}` → `state.screenshot_dir` (only used by the visual scout)
- `{PAGES}` → comma-joined `state.pages_to_walk` (empty = default 3-route + 1-fragment set; see arxmcp-design-system.md §3)

Use `isolation: worktree` on every agent — each gets a worktree-isolated repo state.  Visual-scout uses the live frontend at `http://127.0.0.1:7733`; that's a process-external resource (worktrees don't affect it).

## Subagent_type and model

| Agent | Sub-agent type | Model | Tools beyond default |
|---|---|---|---|
| visual-scout | `frontend-uplift-visual-scout` | sonnet | Add `Bash` (for image-tool inspection), `mcp__Claude_Preview__*` family (load via ToolSearch if deferred) |
| library-scout | `frontend-uplift-library-scout` | sonnet | Standard `Bash + Read + Grep + Glob + WebSearch + WebFetch + Write` |
| inspiration-scout | `frontend-uplift-inspiration-scout` | sonnet | Same as library-scout |
| current-state-critic | `frontend-uplift-current-state-critic` | sonnet | Standard (no Web tools needed; codebase-only) |

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
- **All 4 scouts fail** → halt; surface to the user.
