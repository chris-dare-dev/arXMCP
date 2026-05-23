# State schema — capability-scout

`scripts/init-scout.sh`, `scripts/checkpoint.py`, and `scripts/status.sh` all read/write `.claude/notes/capability-scouts/{ID}/state.json`. This file defines the schema.

## Path layout

```
.claude/notes/capability-scouts/{ID}/
├── state.json                       ← THIS schema
├── survey/
│   ├── comparative-brief.md
│   ├── research-frontier-brief.md
│   ├── oss-trends-brief.md
│   ├── multi-agent-brief.md
│   └── adversary-brief.md
└── artifacts/
    ├── synthesis.md                 ← Phase 2 deliverable
    ├── challenge.md                 ← Phase 3 deliverable
    └── final-report.md              ← Phase 4 deliverable (also surfaced as the user-facing artifact)
```

## State.json schema

```json
{
  "id": "2026q2-retrieval-gap-scan",
  "kind": "capability-scout",
  "created_at": "2026-05-22T15:00:00Z",
  "updated_at": "2026-05-22T15:47:00Z",
  "phase": "survey-complete",
  "phase_history": [
    { "phase": "init",             "at": "2026-05-22T15:00:00Z" },
    { "phase": "survey-running",   "at": "2026-05-22T15:01:00Z" },
    { "phase": "survey-complete",  "at": "2026-05-22T15:47:00Z" }
  ],
  "scout_brief": "Find capability gaps a 2026-era research-math retrieval MCP server would expect us to fill.",
  "survey_mode": "standard",
  "survey_briefs": [
    ".claude/notes/capability-scouts/2026q2-retrieval-gap-scan/survey/comparative-brief.md",
    ".claude/notes/capability-scouts/2026q2-retrieval-gap-scan/survey/research-frontier-brief.md",
    ".claude/notes/capability-scouts/2026q2-retrieval-gap-scan/survey/oss-trends-brief.md",
    ".claude/notes/capability-scouts/2026q2-retrieval-gap-scan/survey/multi-agent-brief.md",
    ".claude/notes/capability-scouts/2026q2-retrieval-gap-scan/survey/adversary-brief.md"
  ],
  "scouts_dispatched": ["comparative", "research-frontier", "oss-trends", "multi-agent", "adversary"],
  "scouts_returned":   ["comparative", "research-frontier", "oss-trends", "multi-agent", "adversary"],
  "synthesis_path": ".claude/notes/capability-scouts/2026q2-retrieval-gap-scan/artifacts/synthesis.md",
  "candidate_count": 14,
  "challenge_path": ".claude/notes/capability-scouts/2026q2-retrieval-gap-scan/artifacts/challenge.md",
  "challenge_finding_counts": { "critical": 1, "high": 3, "medium": 5, "low": 2 },
  "final_report_path": ".claude/notes/capability-scouts/2026q2-retrieval-gap-scan/artifacts/final-report.md",
  "ranked_candidates": [
    { "id": "CAND-1", "title": "Lean kernel verification-trace tool", "rice": 240.0, "rank": 1 },
    { "id": "CAND-7", "title": "cite_neighbors MCP tool wiring", "rice": 180.0, "rank": 2 }
  ]
}
```

## Field reference

| Field | Type | Mutator | Notes |
|---|---|---|---|
| `id` | str | init | Scout id (slug).  Immutable. |
| `kind` | str | init | Always `"capability-scout"`.  Disambiguates from milestone state if both live side-by-side. |
| `created_at` / `updated_at` | str | init / every write | UTC ISO8601 with `Z` suffix. |
| `phase` | str | `checkpoint.py <ID> <new-phase>` | One of the 9 phases.  Forward-only. |
| `phase_history` | list[{phase, at}] | every advance | Append-only audit trail. |
| `scout_brief` | str | init `--brief` OR `--set scout_brief=...` | Free-form user-supplied description.  Read by every Phase 1 sub-agent. |
| `survey_mode` | str \| null | main session `--set` | `"standard"` (5 agents — 4 scouts + adversary), `"lean"` (3 — comparative + adversary + research-frontier), `"deep"` (5 with Opus override on adversary). |
| `survey_briefs` | list[str] | main session `--append` per scout return | Paths to written briefs, in dispatch order. |
| `scouts_dispatched` | list[str] | main session `--append` at dispatch | Names of scouts fired.  Subset of `{comparative, research-frontier, oss-trends, multi-agent, adversary}`. |
| `scouts_returned` | list[str] | main session `--append` per return | Subset of `scouts_dispatched`.  `status.sh` computes the diff as `pending`. |
| `synthesis_path` | str \| null | Phase 2 `--set` | Path to `artifacts/synthesis.md`. |
| `candidate_count` | int | Phase 2 `--set` | Count of distinct candidates in the synthesis catalog. |
| `challenge_path` | str \| null | Phase 3 `--set` | Path to `artifacts/challenge.md`. |
| `challenge_finding_counts` | dict | Phase 3 `--set` | `{critical, high, medium, low}` counts from the challenger's severity tags (re-mapped: BLOCKER → critical, MAJOR → high, MINOR → medium, NONE → low/clean). |
| `final_report_path` | str \| null | Phase 4 `--set` | Path to `artifacts/final-report.md`. |
| `ranked_candidates` | list[{id, title, rice, rank}] | Phase 4 `--set` | RICE-ranked top candidates (top-N from the synthesis, typically N=10). |

## Phase transitions (forward-only, single-step)

```
init
 └─→ survey-running       (Phase 1 start — orchestrator dispatches 5 scouts)
      └─→ survey-complete  (all dispatched scouts returned)
           └─→ synthesize-running   (Phase 2 — main session merging)
                └─→ synthesize-complete  (synthesis.md written)
                     └─→ challenge-running   (Phase 3 — challenger sub-agent)
                          └─→ challenge-complete  (challenge.md written)
                               └─→ prioritize-running   (Phase 4 — main session ranking)
                                    └─→ complete         (final-report.md written; pipeline done)
```

`checkpoint.py` refuses backward and skipped transitions.

## Programmatic access patterns

Read a field:
```bash
.claude/scripts/capability-scout/checkpoint.py <ID> --get phase
```

Set a field:
```bash
.claude/scripts/capability-scout/checkpoint.py <ID> --set survey_mode='"standard"'
.claude/scripts/capability-scout/checkpoint.py <ID> --set candidate_count=14
```

Append to a list:
```bash
.claude/scripts/capability-scout/checkpoint.py <ID> --append scouts_dispatched='"comparative"'
```

Advance phase:
```bash
.claude/scripts/capability-scout/checkpoint.py <ID> survey-running
```
