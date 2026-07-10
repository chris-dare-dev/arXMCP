# `findings.json` schema and the findings register

The findings register is the machine-tracked record of every Phase-3 critique
finding. It exists so Phase 4 can ENFORCE "every CRITICAL/HIGH is
fixed-or-invalidated before complete" from data instead of re-reading prose —
the single biggest quality lever in the pipeline. One object per finding.

`milestone-pipeline-findings.py` is the only writer and the only gate authority.
This file documents intent; the script is the enforcement.

## File location

`<repo-root>/.claude/notes/milestones/<id>/findings.json`

Same ephemeral tier as `state.json` — gitignore it. `state.json` and
`findings.json` are derived, disposable state; the durable evidence is the
`*.md` under `critique/` and `rectify/`. Do not commit the register, do not move
it into a tracked path. `init-state.sh` creates the milestone state dir but does
not itself add an ignore entry, so add `.claude/notes/` (or at least
`.claude/notes/milestones/`) to the consuming repo's ignore rules once. The
register's build-gate analog is the script's own self-test — see below.

`<id>` is the same milestone id space as `state.json`: `<slug>-mN`,
`<slug>-spike-N`, or `adhoc-YYYYMMDD-<sha7>`. The script constrains the id to a
path-traversal floor (`^[A-Za-z0-9][A-Za-z0-9._-]*$`) so a typo'd or hostile id
can never escape the milestone tier.

## Register shape

```json
{
  "milestone_id": "<id>",
  "critique_format_version": "1.0",
  "critique_files": ["adversary.md", "oss.md"],
  "generated_at": "<UTC RFC3339>",
  "findings": {
    "C1": {
      "id": "C1",
      "severity": "CRITICAL",
      "title": "External write in the diff",
      "file": "src/deploy.py",
      "line": 42,
      "anchor": "subprocess.run([\"git\", \"push\"])",
      "source_critic": "milestone-adversary-critic",
      "source_axis": "external-write boundary",
      "source_file": "dedup.md",
      "status": "open",
      "resolution": null,
      "history": []
    }
  }
}
```

| Field | Meaning |
|---|---|
| `id` | Authored id from the critique header (`C1`, `H2`, ...); letter matches severity. |
| `severity` | CRITICAL / HIGH / MEDIUM / LOW. |
| `title` / `anchor` / `file` / `line` | Re-derived from the critique on every `extract`. |
| `source_critic` / `source_axis` / `source_file` | Provenance. |
| `status` | `open` → `fixed` \| `deferred` \| `invalidated`. |
| `resolution` | Required note recorded by `set`; `null` while open. |
| `history` | Append-only `{status, at, resolution}` disposition trail. |

## Status machine (forward-only, v1 has no reopen)

```
open → fixed
open → deferred → fixed
open → invalidated
```

`fixed` and `invalidated` are terminal. Setting a finding to its current status
is an idempotent no-op. `set` requires `--resolution` for any real transition.
Every consumer loads through a STRICT validator: an out-of-vocabulary status or
severity is a hard error, so a hand-edited register can never fail the gate
OPEN.

## Invocations

All via `python3 "$REPO_ROOT/.claude/scripts/milestone-pipeline-findings.py"`
with `REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel)}"`. The script
resolves the repo root itself (env → git → walk), so a synced copy inside a
consumer repo needs no path wiring.

| Command | Purpose |
|---|---|
| `extract --id <ID> [<critique.md> ...]` | Parse critique(s) → merge-safe register write. Defaults to `critique/dedup.md`. PRESERVES status/resolution/history by id and REFUSES to drop a registered id or critique file. |
| `extract --check <critique.md> [...]` | Lint only; exit 1 listing every malformed block, never a silent skip. |
| `set <ID> <ids> <fixed\|deferred\|invalidated> --resolution "..."` | The ONLY sanctioned status writer. Comma-list ids; forward-only machine. |
| `gate <ID>` | Exit 3 while any CRITICAL/HIGH is open (lists them); warn-only exit 0 on open MEDIUM/LOW; no-op exit 0 when no register exists (legacy/ad-hoc). |
| `summary <ID> [--field NAME]` | Derive `finding_counts`, per-file counts, and `open`/`fixed`/`deferred`/`invalidated` id arrays for `state.json`. |
| `summary --counts-for <critique.md>` | C/H/M/L tally of one file (replaces `grep -c '^### CRITICAL'`). |
| `dedupe <critique.md>` | Cross-critic agreement clustering through the same fail-loud parser. |

## Gate authority (one authority, two call sites)

The gate logic lives ONLY in `gate <ID>`. Two callers subprocess-invoke it and
never re-implement it:

- `milestone-pipeline-checkpoint.py`'s `complete` transition — the backstop:
  refuse on exit 3, and refuse when `state.findings_register` is set but the
  register file is absent (a new-format run can never complete ungated). No-op
  for a null marker (legacy/ad-hoc).
- The `/milestone-pipeline` Phase-4 command body — the friendly early check,
  run before the external-write authorization prompt.

## Derived state fields (never hand-maintained)

`state.json`'s `critique_finding_counts`, `fixed_findings`, `deferred_findings`,
and `invalidated_findings` are COMPUTED from the register, not appended by hand:

- `critique_finding_counts` ← `summary --counts-for <merged critique file>`
- `fixed_findings` / `deferred_findings` / `invalidated_findings` ←
  `summary --field fixed_findings` / `... deferred_findings` / `... invalidated_findings`

See `milestone-pipeline-state-schema.md` for those fields and
`milestone-pipeline-critique-format.md` for the critique shape the parser reads.

## Sibling regulated artifact

The register mirrors the roadmap/1 pattern one granularity down: it tracks
findings against the implementation DIFF, while the roadmap
(`plans/<slug>/roadmap.yaml`, schema `data/scripts/roadmap-schema.json`, golden
example `data/references/roadmap-example.yaml`) tracks milestone-granularity
plan items. The two are orthogonal — the register never touches `roadmap.yaml`.
Completion still flows to the roadmap only via
`milestone-pipeline-record-progress.py`'s journal append (one-writer rule
intact).

## Build gate

`python3 data/scripts/milestone-pipeline-findings.py --self-test` must exit 0.
Run it after any change to the script or the critique format — it is the
registry's build-gate analog for the register, mirroring the
`roadmap-validate.py` golden-fixture gate in `CLAUDE.md`.
