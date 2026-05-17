# arXMCP integration — project-specific conventions

The `roadmap` skill writes outputs that other parts of arXMCP consume.
This file documents the contract on each side so the skill produces
artifacts that pair cleanly with the rest of the project.

## Pairing with `milestone-pipeline`

`milestone-pipeline` is the execution slash command at
[.claude/commands/milestone-pipeline.md](.claude/commands/milestone-pipeline.md).
It runs ONE milestone end-to-end through Research → Implement → Critique
→ Rectify.

**Milestone-ID format consumed by milestone-pipeline:** any string. The
init-state.sh script greps for `### <ID> — ` headings. arXMCP convention:

- `EXX_SYY` — the manually-authored master roadmap in `.claude/roadmap/`.
- `<slug>-mN` — milestones produced by THIS skill, written to `plans/`.

**The roadmap skill must:**
- Use `<slug>-mN` IDs (e.g. `citation-graph-m1`, `citation-graph-m2`).
- Write the milestone block in the format milestone-pipeline parses:
  ```
  ### <slug>-mN — Title

  **Description.** ...

  **Acceptance criteria.**
  - [ ] ...
  ```
- Reject slug shapes that collide with EXX (regex `^e\d+$` is forbidden;
  validated by `init-roadmap.sh`).

**Bridge in milestone-pipeline:** [.claude/milestone-pipeline/scripts/init-state.sh](.claude/milestone-pipeline/scripts/init-state.sh)
searches BOTH `.claude/roadmap/*.md` AND `plans/*.md` for milestone briefs.
On collision (same ID in both directories) it exits 1 with both paths
printed. Optional override: `--brief-from <path>`.

**Phase 4 handoff offer (do NOT auto-invoke):**
> "First Now-lane milestone: `<slug>-m1`. Run `milestone-pipeline <slug>-m1` to execute."

The user invokes manually. Auto-invoke would cost cache (fresh prompt
prefix) and remove the user gate.

## Ticket-system integration: GitHub Issues, manual

The project's [ROADMAP.md](ROADMAP.md) is explicit:

> "To create issues from these files, the maintainer runs (per sub-issue):
> `gh issue create --title "<title>" --body-file <(awk ...)`"

**The roadmap skill never invokes `gh`.** Per project external-write
policy.

When `--github` is passed:
- Per-issue body files written to `plans/<slug>-tickets/<ID>.md` from
  `references/templates/epic-issue.md` and `story-issue.md`.
- A copy-paste `plans/<slug>-tickets/create-tickets.sh` is written, with
  one `gh issue create` invocation per body file. The script's first
  line is a confirmation prompt.

The user runs the script manually after reviewing. The skill prints:

> "Tickets bundle written to `plans/<slug>-tickets/`. Review the bodies,
> then run `bash plans/<slug>-tickets/create-tickets.sh` to create them
> on GitHub. The skill never invokes `gh` itself."

## Repo conventions to mirror

| convention | source | apply where |
|---|---|---|
| Conventional commits, `<type>(<scope>): <subject>` ≤ 50 chars after prefix | [recent commits](.git) | Any commit the skill or its scripts produce |
| Conventional scopes: `server`, `ingest`, `shim`, `infra`, `tests`, `skill`, `roadmap`, `notes` | repo history | Pick the closest match |
| GPG signing (`commit.gpgsign=true`) | git config | Commits the user makes from skill output; never `--no-gpg-sign` |
| Co-author trailer: `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` | repo history | Suggest in `create-tickets.sh` and any commit suggestions |
| Pre-commit hooks honored | git config | Never `--no-verify` |
| Project check: `make test` (once E01_S01 lands a Makefile); fallback `ruff check . && pytest -q` | [.claude/roadmap/epic-01-vertical-slice.md](.claude/roadmap/epic-01-vertical-slice.md) | Reference in story AC; run during MATERIALIZE validation if available |
| Python 3.11+, ruff, pytest | [E01_S01 acceptance criteria](.claude/roadmap/epic-01-vertical-slice.md) | Story AC for any Python milestone |

## Constitution rules the skill must respect

From [.claude/notes/README.md](.claude/notes/README.md):

> "No AWS S3 / no requester-pays buckets" — flag if any epic depends on it.
>
> "No forking" of existing arXiv-MCP repos — flag if any epic proposes a vendored copy or git submodule of `pulkitharkawat/arxiv-mcp` or similar.
>
> "Must run locally in Docker" — flag if any epic requires multi-host coordination (k8s, etc.) for v1.
>
> "Math fidelity over coverage" — 50K papers indexed correctly beats 500K with PyPDF mangling. Apply during DECOMPOSE when ranking parser-vs-scale tradeoffs.

The Refine phase produces a brief; if the brief implies any of these
rule violations, surface it explicitly in the Won't section.

## File and path conventions

| produces | path |
|---|---|
| Roadmap doc | `plans/<slug>-roadmap.md` |
| GitHub epic body files | `plans/<slug>-tickets/<EPIC-ID>.md` |
| GitHub story body files | `plans/<slug>-tickets/<STORY-ID>.md` |
| Copy-paste ticket script | `plans/<slug>-tickets/create-tickets.sh` |

`plans/` should be added to `.gitignore` ONLY IF the team decides shaped
roadmaps are local artifacts. Default: commit them. They're cheap and
make pairing legible.

## What the skill must NOT touch

- `.claude/notes/` — design constitution, manually authored. Read-only.
- `.claude/roadmap/` — master roadmap, manually authored. Read-only.
- `ROADMAP.md` — executive summary. Read-only.
- `.claude/milestone-pipeline/` — pipeline supporting infrastructure (scripts + references).
  The roadmap skill triggers a one-time bridge edit (init-state.sh + state-schema.md)
  during initial install; ongoing runs do not modify it.
- `.claude/commands/milestone-pipeline.md` — the orchestrating slash command itself.
