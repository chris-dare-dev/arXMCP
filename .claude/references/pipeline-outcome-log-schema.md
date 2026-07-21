# `outcomes.jsonl` schema and capture guarantees

Documents the record `pipeline-outcome-log.py` appends — one labelled JSON
line per pipeline run. The script is the enforcement; this file documents
intent and the field sources. The corpus is the dataset a future cross-run
calibration step (or `claude-otel`) would read. Capture is advisory: a failure
here never aborts a host pipeline's terminal transition.

## File location

`<repo-root>/.claude/notes/pipeline-outcomes/outcomes.jsonl`

Override the whole path with `$PIPELINE_OUTCOME_LOG`. Repo root resolves
`$REPO_ROOT` -> `git rev-parse --show-toplevel` -> walk up to a `.git/`
(the synced copy lives at `<root>/.claude/scripts/`). One record is appended
per `emit`; the file is never rewritten in place.

## Record schema

One JSON object per line. Column set is stable — columns with no producer in
this fleet stay `null` rather than being dropped, so a later pipeline can
populate them without a format migration.

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | int | Record format version (currently `1`). |
| `run_id` | str | Random hex id, unique per emit. The authoritative join key. |
| `emitted_at` | str | UTC RFC3339 (`...Z`) timestamp of the emit. |
| `pipeline` | str | Pipeline family: `milestone` or `roadmap`. |
| `id` | str | Milestone id (`<slug>-mN`, `adhoc-...`) or roadmap slug. |
| `source_state_path` | str \| null | Where the columns were read from (see below). |
| `created_at` | str \| null | Run start (from `state.json`). |
| `updated_at` | str \| null | Last state write (from `state.json`). |
| `phase` | str \| null | The `state.json` phase AS READ at emit time — a verbatim snapshot, never overwritten by the declared outcome. |
| `outcome` | str \| null | The run's outcome. Terminal emits DECLARE it via `--outcome` (ordering-proof); defaults to `phase` when undeclared; `--field outcome=` overrides last. `outcome != phase` marks a state write that lagged the emit — auditable, not corruption. |
| `critique_finding_counts` | obj \| null | `{critical, high, medium, low}` at critique time. |
| `fixed_findings` | array | Finding ids the rectify phase closed. |
| `rectification_count` | int | `len(fixed_findings)` — the LOCKED definition. |
| `rectification_commit` | str \| null | SHA of the `rect(<id>): ...` commit. |
| `token_cost` | null | Intentionally unset here; see below. |
| `candidate_count` | null | Discovery column — no producer in this fleet. |
| `challenge_finding_counts` | null | Discovery column — no producer in this fleet. |

## Field sources per family

`emit` reads the milestone `state.json` when `--state` is given; the roadmap
family has no `state.json`, so its columns arrive via `--field k=v`. `--field`
is applied last and overrides any state-derived value.

| Field | Milestone source | Roadmap source |
|---|---|---|
| `source_state_path` | the `--state` path (state.json) | `plans/<slug>/roadmap.yaml` (`--field`) |
| `created_at` / `updated_at` | `state.json` | `null` (or `--field`) |
| `phase` | `state.phase` (snapshot) | `null` |
| `outcome` | `--outcome complete` (declared; `state.phase` when undeclared) | `--field outcome=complete` |
| `critique_finding_counts` | `state.critique_finding_counts` | `null` |
| `fixed_findings` / `rectification_count` | `state.fixed_findings` | `null` / `0` |
| `rectification_commit` | `state.rectification_commit` | `null` |

The milestone field map lands directly on the downstream `state.json`
documented in `milestone-pipeline-state-schema.md`
(`created_at` / `updated_at` / `phase` / `critique_finding_counts` /
`fixed_findings` / `rectification_commit` are all present there).

## token_cost

`token_cost` is intentionally `null`. There is no metric push, no external
telemetry backend, and no credential fetch of any kind in this script. If the
fleet later wants per-run token cost, `claude-otel` is the place to host it —
backfilled by joining on `run_id`. Build no integration here.

## Emit sites (2 live)

| Family | When | Wired by |
|---|---|---|
| `milestone` | after `milestone-pipeline-checkpoint.py <id> complete` | the `/milestone-pipeline` command, post-checkpoint |
| `roadmap` | when the materializer returns `complete` (`roadmap-phase-materialize.md`) | the `/roadmap` command, at materialize-complete |

A spike is a milestone sub-mode, not a separate family — it emits through the
milestone site. Each emit is best-effort and runs after the terminal
transition has already been recorded, so it can never gate that transition.

### The emit race, and why terminal emits declare their outcome

The emit-after-transition ordering is LLM-followed, not enforced. Before the
`--outcome` flag, an emit that ran between the rectification-data write and
the phase flip snapshot a stale `phase` into BOTH columns and no second emit
followed — the run was recorded `rectify-running` forever (OSE `g7-3-a-m1` /
`g5-1-a-m1`, 2026-07-16 review). Terminal emit sites now pass
`--outcome complete`, which makes the `outcome` column ordering-proof while
`phase` keeps the honest snapshot; the script prints a non-fatal stderr note
when they diverge. Duplicate rows per id are legal and expected (append-only);
readers take the LAST row per id as authoritative.

### Backfilled rows

A retroactively-emitted row (a missed terminal emit repaired later) is a LATE
emit, not a special record: `emitted_at` is the repair time, `updated_at` /
`phase` come from the state file as it stands. Mark such rows with
`--field backfilled=true` — the one sanctioned extra column beyond the stable
set — so a reader can separate capture-time telemetry (e.g. emit latency) from
repaired history.

## Concurrency guarantees

- **(a) Append-only, single-line writes.** Each record is one `write()` to an
  `O_APPEND` handle. On POSIX a write under `PIPE_BUF` is atomic, so
  interleaved records never corrupt each other. The file is only ever
  appended to.
- **(b) Advisory lock where available.** The append takes an `fcntl` advisory
  lock when the module is present. `fcntl` is absent on native Windows
  (ImportError-guarded); there the milestone `.lock` already serializes runs,
  so concurrent cross-pipeline emits are the only unguarded case and are rare.
- **(c) Best-effort by contract.** `emit` wraps its work in a catch-all: any
  failure prints a warning to stderr and still exits 0. A capture problem must
  never abort a host pipeline's terminal transition. Read-side (`summary`)
  tolerates malformed lines by skipping them.

## Gitignore situation (per-repo, inconsistent)

There is no fleet-wide gitignore step. `.claude/notes/` coverage varies by
consumer repo: some ignore all of `.claude/*` via an allowlist (safe), others
ignore only specific `.claude/notes/milestones/*` paths — in the latter,
`.claude/notes/pipeline-outcomes/outcomes.jsonl` would be committable.

Recommendation: add a per-repo `.claude/notes/pipeline-outcomes/` entry to that
repo's `.gitignore` (the log is local-only working data, not a tracked
artifact). The registry distributes the *script* via `sync-repos.py`; the log
itself is never distributed and never committed by the pipeline.

## Corpus scope

Default is a per-repo corpus (matches the local-only gitignore story and needs
no configuration). A single shared corpus — `$PIPELINE_OUTCOME_LOG` pointed at
a common location — is only worth it if cross-repo trajectory calibration is
later wanted. Recommend the per-repo default now; build neither integration.
