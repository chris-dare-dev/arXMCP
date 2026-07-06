# arXMCP integration — project-specific conventions

The `/roadmap` slash command writes outputs that other parts of arXMCP
consume. This file documents the contract on each side so the command
produces artifacts that pair cleanly with the rest of the project.

## Pairing with `milestone-pipeline`

`milestone-pipeline` is the execution slash command at
[.claude/commands/milestone-pipeline.md](.claude/commands/milestone-pipeline.md).
It runs ONE milestone end-to-end through Research → Implement → Critique
→ Rectify.

**Milestone-ID format consumed by milestone-pipeline:** arXMCP convention:

- `EXX_SYY` — the manually-authored master roadmap in `.claude/roadmap/`
  (legacy prose fallback).
- `<slug>-mN` — milestones produced by `/roadmap`, written to
  `plans/<slug>/roadmap.yaml` (roadmap/1 format).

**The /roadmap command must:**
- Use `<slug>-mN` IDs (e.g. `citation-graph-m1`, `citation-graph-m2`) —
  the ID grammar is enforced by `.claude/scripts/roadmap-validate.py`.
- Reject slug shapes that collide with EXX (regex `^e\d+$` is forbidden).

**Bridge in milestone-pipeline:**
[.claude/scripts/milestone-pipeline-init-state.sh](.claude/scripts/milestone-pipeline-init-state.sh)
resolves briefs via `milestone-pipeline-resolve-brief.py` — canonical source
is `plans/*/roadmap.yaml`; legacy prose fallback greps `### <ID> — ` headings
in `plans/*.md` AND `.claude/roadmap/*.md`. Ambiguous IDs exit 1 with the
candidate paths printed.

**Phase 4 handoff offer (do NOT auto-invoke):**
> "First Now-lane milestone: `<slug>-m1`. Run `milestone-pipeline <slug>-m1` to execute."

The user invokes manually. Auto-invoke would cost cache (fresh prompt
prefix) and remove the user gate.

## Ticket-system integration: GitHub Issues, manual

The project's [ROADMAP.md](ROADMAP.md) is explicit:

> "To create issues from these files, the maintainer runs (per sub-issue):
> `gh issue create --title "<title>" --body-file <(awk ...)`"

**Sub-agents never invoke `gh` (write verbs).** Per project external-write
policy.

When `--github` is passed:
- The materializer emits per-issue body files to
  `plans/<slug>/github/<item-id>.md` — bodies only, no issue creation.
- The orchestrator (main session) resolves the repo, asks for an explicit
  `[y]`, and only then runs `gh issue create` itself, one at a time, from
  the body files. On anything else the body files remain for manual use.

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
| Canonical roadmap | `plans/<slug>/roadmap.yaml` (roadmap/1) |
| Execution journal | `plans/<slug>/progress/agent.jsonl` (milestone pipeline appends) |
| GitHub issue body files | `plans/<slug>/github/<item-id>.md` (`--github` only) |

`plans/` should be added to `.gitignore` ONLY IF the team decides shaped
roadmaps are local artifacts. Default: commit them. They're cheap and
make pairing legible.

## What the /roadmap command must NOT touch

- `.claude/notes/` — design constitution, manually authored. Read-only.
- `.claude/roadmap/` — master roadmap, manually authored. Read-only.
- `ROADMAP.md` — executive summary. Read-only.
- `.claude/scripts/milestone-pipeline-*` and
  `.claude/references/milestone-pipeline-*` — registry-synced pipeline
  infrastructure. Never edited in-repo (edit the registry and re-sync).
- `.claude/commands/milestone-pipeline.md` — the orchestrating slash command itself.
- `plans/<slug>/progress/*.jsonl` — journals are milestone-pipeline-owned
  (one writer per file).
