<!-- scan provenance: generated 2026-07-25..29; moved here 2026-07-29 -->

> [!info] Projects v2 view specifications — arXMCP scan, 2026-07-29
> **Method.** Exact filter strings for board #3, written because GitHub exposes no `createProjectV2View` mutation and `gh project` has no `view-create` -- views are web-UI only.
> **Status.** **Implemented.** All 5 new views exist (#8-#12), `Now - current focus` was repointed, `View 1` renamed to `All items`, and every view now carries a group-by. Kept as the reference for what each filter means and why.
> **Origin.** Produced in a single principal-engineer review session; the board state it
> cites was read live from the GitHub API. Numbers are dated -- re-verify before acting on
> any of them.

# arXMCP board — view specs (paste into the web UI)

GitHub exposes no `createProjectV2View` mutation and `gh project` has no `view-create`, so
these are the only part of the PM work that cannot be scripted. Board:
**https://github.com/users/chris-dare-dev/projects/3**

Counts are what each filter returns as of 2026-07-26, after the label backfill.

## Add these

| # | View name | Filter | Group by | Returns |
|---|---|---|---|---|
| 1 | **Pipeline queue** | `is:open label:"type:milestone" lane:"Now" -label:blocked` | Milestone | **9** — exactly what `/milestone-pipeline` can pick up now |
| 2 | **Blocked & gated** | `is:open label:blocked,gate:owner,gate:data` | Milestone | 61 |
| 3 | **Findings** | `is:open label:"type:finding"` | Priority | 14 |
| 4 | **Hardening** | `is:open milestone:"Boundary hardening — contracts, epochs, and the ops layer"` | Priority | 9 |
| 5 | **Recently done** | `is:closed` (sort: Closed ↓) | — | 37 — handoff + changelog source |
| 6 | **By area** | `is:open label:"area:lean"` (clone per area) | Milestone | varies |

Sort views 1–4 by **Priority ↓** then **Size ↑** so the cheapest Must-items sit at the top.

## Fix these

- **`Now - current focus`** — repoint its filter from `lane:Now` (returns **86**, unusable) to
  the Pipeline-queue filter above, or delete it in favour of view 1.
- **`View 1`** — unnamed default left over from board creation. Rename or delete.
- **`By status`** — keep; Status is correctly maintained (all 37 closed items show `Done`,
  and the 6 built-in project workflows are enabled).

## Why `area:*` gets filtered views rather than a grouped one

Projects v2 can only *group* by single-select fields, Milestone, Assignee and a few built-ins —
never by label. Component is doctrinally a label (`github-conventions.md`: "Per-repo component
labels are `area:*`"), so the per-area slice has to be a filter. If you would rather group by
area, the alternative is a single-select **Area** project field, which contradicts the
labels-vs-fields split in the conventions doc — I'd keep the labels.
