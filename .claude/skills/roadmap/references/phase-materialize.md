# Phase 4 — Materialize

**Status sentinel:** `<!-- status: pending -->` under `## Phase 4 — Materialize`. Delete it when this phase writes content.

**State postcondition:** roadmap doc passes `validate-roadmap.py`; Must-cap recorded; if `--github` was passed, per-issue body files plus `create-tickets.sh` written under `plans/<slug>-tickets/`; next-step handoff message rendered.

## Step-by-step

1. **Read once at phase start:** this file. Templates lazy-load only when `--github` is passed.
2. **Run `validate-roadmap.py`** on the roadmap doc:
   ```
   scripts/validate-roadmap.py plans/<slug>-roadmap.md
   ```
   Must exit 0. Any violation → fix in the relevant phase, do not paper over with `--allow`.
3. **Record Must-cap result.** Pull the Must percentage from `score-moscow.py` (re-run if the cached output is stale) and write it as `Must-cap: NN.N%` in the Materialize section.
4. **Check Now-lane AC presence.** `validate-roadmap.py` already enforces this (MILESTONE-AC check); record the result.
5. **GitHub bundle (only if `--github` was passed).** External-write boundary applies:
   - Create `plans/<slug>-tickets/` directory.
   - For each Now-lane milestone: render `<MILESTONE-ID>.md` from `references/templates/story-issue.md`. Substitute `{{TOKEN}}`s.
   - For each parent epic of a Now-lane milestone: render `<EPIC-ID>.md` from `references/templates/epic-issue.md`.
   - Write `plans/<slug>-tickets/create-tickets.sh`. The script's first lines are:
     ```bash
     #!/usr/bin/env bash
     set -euo pipefail
     echo "WARNING: this creates GitHub issues. Review the body files before continuing."
     read -r -p "continue? [y/N] " ans
     [[ "$ans" =~ ^[Yy]$ ]] || { echo "aborted"; exit 1; }
     ```
   - Followed by one `gh issue create --title "<title>" --body-file <path>` per body file, in dependency order (epics before stories).
   - Make the script `chmod +x`.
   - The skill **NEVER** runs the script. The user runs it manually after reviewing.
6. **Render the handoff message.** The Materialize section ends with a Next-step block:
   ```
   ### Next step

   First Now-lane milestone: `<slug>-m1`. To execute it end-to-end, run:

       milestone-pipeline <slug>-m1

   This skill will not invoke milestone-pipeline. Cache stays warmer if
   you start the milestone-pipeline session within 5 minutes.
   ```
7. **Delete the `<!-- status: pending -->` sentinel.**
8. **Print the user-facing summary** (this is the only message the user sees beyond the doc itself):
   ```
   roadmap '<slug>' complete.

     plans/<slug>-roadmap.md — review
     [optional] plans/<slug>-tickets/ — review then run create-tickets.sh
     next: milestone-pipeline <slug>-m1
   ```

## Auto-advance vs gate — decision table

MATERIALIZE never gates on validation results — those are hard checks, fix or fail. The only gate in this phase is the **external-write boundary** for the GitHub bundle:

| condition | action |
|---|---|
| `validate-roadmap.py` passes, `--github` not passed | **auto-complete** (no external writes pending) |
| `validate-roadmap.py` passes, `--github` passed | **auto-write** the bundle to `plans/<slug>-tickets/` (this is local; not external). Then **GATE** before any further automation: surface the bundle path, the script name, and the warning that running it creates GitHub issues. The user runs the script. |
| `validate-roadmap.py` fails | **STOP**. Report violations; user fixes the responsible phase and re-invokes the skill. |

## Hard rules

- **The skill never invokes `gh`, `git push`, or any network operation.** Per project external-write policy.
- **`create-tickets.sh` MUST start with the y/N confirmation prompt.** Even when the user just ran the skill, the script's first invocation should pause for confirmation. Different mental model when running from CLI later.
- **Milestone-pipeline handoff is OFFERED, never invoked.** Reason: cache (a fresh milestone-pipeline run is a fresh prompt prefix; auto-invoke saves nothing) plus the user gate (the user might want to review the roadmap first).
- **Doc must pass validation before complete.** No `--allow` shortcuts in normal flow. `--allow` is for explicit user overrides only, with a documented reason in the doc.
- **Byte-stable output.** No timestamps in the body of the roadmap doc beyond the Created header. Alphabetical key order in any structured metadata. This lets downstream skills (milestone-pipeline) cache reads of the doc.

## Don'ts

- Don't run `gh issue create` on the user's behalf. Even if the user "definitely" wants tickets created. Per-event authorization.
- Don't silence validation failures. Lint violations are signals, not noise.
- Don't write the handoff message to invoke milestone-pipeline automatically. Print the suggested command; let the user run it.
- Don't bundle Next/Later epics into `create-tickets.sh`. Only Now-lane milestones (and their parent epics) become tickets at this point. Next/Later become tickets when they enter Now in a future roadmap re-run.
- Don't add a "this is a draft" disclaimer to the doc. The roadmap is a bet, not a contract — the framing is in the Now/Next/Later structure already.

## Output template (Materialize section)

```
## Phase 4 — Materialize

### Validation

- `validate-roadmap.py`: pass
- Must-cap: NN.N% (≤ 60%)
- All Now-lane milestones have AC: yes
- Slug format valid: yes

### GitHub tickets

<!-- if --github not passed: -->
Not requested (run with `--github` to bundle epic + story bodies).

<!-- if --github passed: -->
Bundle written to `plans/<slug>-tickets/`:
- `<EPIC-ID>.md` — epic body
- `<STORY-ID>.md` — story body
- `create-tickets.sh` — copy-paste script (review then run manually)

To create tickets: `bash plans/<slug>-tickets/create-tickets.sh`

### Next step

First Now-lane milestone: `<slug>-m1`. To execute it end-to-end, run:

    milestone-pipeline <slug>-m1

This skill will not invoke milestone-pipeline. Cache stays warmer if
you start the milestone-pipeline session within 5 minutes.
```
