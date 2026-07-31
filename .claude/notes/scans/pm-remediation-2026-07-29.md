<!-- scan provenance: generated 2026-07-25..29; moved here 2026-07-29 -->

> [!info] Board / project-management remediation — arXMCP scan, 2026-07-29
> **Method.** Live read of the GitHub API + all `plans/*/roadmap.yaml`. 11 findings (F1-F11) on labels, milestones, fields, views and unmaterialized tracks.
> **Status.** **Executed in full.** F1-F11 are all closed: 14 repo-local labels created and backfilled onto 171 issues, `type:milestone` fixed at the registry source and synced fleet-wide, 6 milestone descriptions written, 3 unmaterialized roadmaps created-and-closed (#234-#275), 5 views added and all 12 grouped, 11 legacy prose plans archived. Read this as a RECORD, not a to-do list.
> **Origin.** Produced in a single principal-engineer review session; the board state it
> cites was read live from the GitHub API. Numbers are dated -- re-verify before acting on
> any of them.

# arXMCP — project-management remediation

Scope: the **GitHub** project surface for `chris-dare-dev/arXMCP` (the request said
GitLab; the project lives on GitHub — 6 milestones, 200 issues, Projects v2 board #3
"arXMCP - Delivery", plus the user-level board #2 "Mission Control").

Every fact below was read live from the GitHub API and from `plans/*/roadmap.yaml`
on 2026-07-25.

---

## 0. What is already good

This is a well-run board, and the remediation below is refinement, not rescue.

- **The plan→issue path is real and doctrinal.** `plans/<slug>/roadmap.yaml` (schema
  `roadmap/1`) → `roadmap-to-github.py` (dry-run default, idempotent via a hidden
  `<!-- roadmap-gh: slug/id -->` marker) → `plans/<slug>/github/issue-map.json`.
  190 of 232 roadmap items are materialized.
- **The hierarchy is genuinely nested**, not flat: 35 `epic` issues → milestone issues →
  task issues, wired with **native GitHub sub-issues**. Only 10 of 200 issues are
  parentless, and those are the hand-filed pre-roadmap ones (#1–#10).
- **Project automation is on** — all 6 built-in workflows enabled; every closed issue in
  the project correctly shows `Status: Done` (19/19). The Status field is not stale.
- **The doctrine is written down** and citable: `.claude/references/github-conventions.md`
  defines the ANNOTATE/STRUCTURAL write split, the labels-vs-fields division, and the
  write-once ID-in-title rule.

## 1. Findings

### F1 — `kind: milestone` and `kind: task` collapse to one label *(highest leverage)*

`.claude/scripts/roadmap-to-github.py:56`:

```python
LABELS_BY_KIND = {
    "epic": ["epic"], "milestone": ["type:task"],
    "task": ["type:task"], "spike": ["type:spike"],
}
```

`/milestone-pipeline` is invoked **with milestone ids** (`/milestone-pipeline
evidence-engine-m1`). Those are the only issues that are units of execution. On the
board they are indistinguishable from leaf tasks — 146 issues share `type:task`.

**Consequence:** the single view this project's workflow needs — *"what can I hand to
the pipeline right now"* — cannot be built. The existing "Now - current focus" view
returns **108 items** because epics, their milestones, and their tasks all inherit
`lane: now` from the roadmap. There are in fact only **27 now-lane milestones** across
the 9 tracks.

**Fix:** a repo-local `type:milestone` label, backfilled from the id suffix `-m<N>`
(exact, mechanical). Fleet follow-up: teach the registry converter to emit it.

### F2 — 97 roadmap items declare `depends_on`; **zero** issues carry `blocked`

The dependency graph is fully specified in the YAML and entirely absent from the board.
The fleet label `blocked` exists and is unused. Same for the whole gating vocabulary.

### F3 — 27 of 30 labels are dead

Applied today: `type:task` (146), `epic` (35), `type:spike` (9). **Never applied:**
`sev:critical|high|medium|low`, `gate:owner`, `gate:data`, `agent-ready`, `blocked`,
`parked`, `cross-repo`, `type:feature|bug|docs|infra|finding|chore|refactor`.

`agent-ready` ("scoped tightly enough for autonomous pickup") is the most valuable
unused label in a repo whose entire execution model is autonomous milestone pickup.

### F4 — no `area:*` component labels at all

`github-conventions.md` explicitly reserves `area:*` as the per-repo component class.
arXMCP has none (nor does any sibling repo in the fleet). For a system with eight clean
subsystems this is the biggest navigational miss: you cannot ask "everything touching
retrieval" or "everything touching Lean".

Derivable **mechanically** from each item's `links.code` paths — validated: **177 of 232
items** self-assign; the 55 that don't are policy/governance items → `area:governance`.

### F5 — all six milestone descriptions are empty

`GET /repos/chris-dare-dev/arXMCP/milestones` → `description: null` on all 6. A milestone
page shows a title and a bar. The objective, key results, and entry-point milestone ids
all exist in the roadmap YAML and are not projected anywhere a human or agent will look.

### F6 — Size unset on 161/196 board items (82%); Priority unset on 71 (36%)

Not a sync bug — `roadmap-project-fields.py` works. The **source data** only carries
`size:` on the ~6 epics per track (6 of 28, 6 of 34, …). Priority is set on roughly
two-thirds. So the "By priority" view is partly blind and size is unusable for planning.

### F7 — three roadmaps (42 items) were never materialized

`data-plane-governance` (15), `paper-metadata` (9), `source-truth` (18) have
`phase: complete, status: active` and **no** `github/issue-map.json`. They are invisible
on the board — including `data-plane-governance`, which produced the **binding** ADRs
that CLAUDE.md §4.8/§4.9 now cite as constitutional.

Note: parts of `source-truth` and `paper-metadata` are already **done** in git history, so
materializing wholesale would create-then-close ~20 issues. Recommend materializing the
**open residue only**.

### F8 — 11 legacy prose roadmaps in `plans/*.md` are outside the system entirely

`corpus-integrity-completion`, `corpus-integrity-observability`, `lean-repl-observability`,
`license-serving-removal`, `notebook-ops-hardening`, `notebook-paper-discovery`,
`notebook-surface-expansion`, `proof-verify-handler-wiring`, `textbook-ingest`,
`ui-attractive-polish`, `verification-feedback`. Not `roadmap/1`, not on the board.
`roadmap-migrate.py` exists for exactly this conversion. Several are already shipped and
should simply be tombstoned.

### F9 — issues #1–#10 carry zero labels; four closed ones have no milestone

These are the E13 security threat-model follow-ups plus early findings. They are exactly
the population `type:finding` + `sev:*` exists for. #1, #3, #5, #8 (closed) have no
milestone, so they are absent from every milestone's historical record.

### F10 — the cross-track spine is not represented on the board

`M0` (Stage-2 worktree merge) → `W1` (batched tool-schema re-pin) → `FIX` (eval fixture
populated) is the documented global ordering that ~15 milestones across all six tracks
assume. It lives in a markdown file. Nothing on the board expresses it, so the board
cannot tell you that a "Now" item is actually gated.

### F11 — view inventory is thin and one view is an unnamed default

Board #3 has 7 views: `View 1` (unnamed leftover), `Roadmap`, `By priority`, `Epics`,
`Now - current focus`, `Spikes`, `By status`. Missing: the agent queue, blocked/gated
work, findings by severity, per-area slices, recently-completed.

**Constraint discovered:** GitHub exposes **no** `createProjectV2View` mutation and
`gh project` has no `view-create`. Views must be created in the web UI. Fields *can* be
created via API. So the view work below is exact filter strings to paste, not something
a script can do.

---

## 2. Proposed changes

### 2.1 Labels to create (repo-local, 14)

| label | colour | purpose |
|---|---|---|
| `type:milestone` | `c2e0c6` | the unit `/milestone-pipeline` consumes — fixes F1 |
| `area:mcp-surface` | `1d76db` | tools.py, handlers, shim, session, router |
| `area:ingest` | `5319e7` | fetch → parse → chunk → embed → index |
| `area:retrieval` | `0052cc` | BM25/ANN/RRF/rerank + the 3-tier cache |
| `area:graph` | `006b75` | Kùzu citation graph and its ingest |
| `area:corpus` | `0e8a16` | notebooks, documents registry, metadata, licensing |
| `area:lean` | `b60205` | Lean kernel, `lean_verify`, formalization |
| `area:textbook` | `d93f0b` | MinerU + LaTeXML PDF path |
| `area:eval` | `fbca04` | harness, fixtures, regression ledger |
| `area:ops` | `bfd4f2` | ops, observability, backup, cutover, infra |
| `area:security` | `e11d21` | threat model, sandboxing, content security |
| `area:ui` | `d876e3` | `/ui/` console and frontend assets |
| `area:docs` | `0075ca` | operator-facing docs and adoption |
| `area:governance` | `cfd3d7` | boundary ADRs, trust policy, plan-track hygiene |

### 2.2 Label backfill (dry-run verified: 171 issues touched)

`arxmcp-board-backfill.py` derives, from roadmap truth only:
`area:*` from `links.code`; `type:milestone` from `kind`; `blocked` from a `depends_on`
whose issue is still open. Dry-run default, idempotent, paced at 1 write/s.

This is a **bulk** annotate — `github-conventions.md` allows un-prompted ANNOTATE only
"never in bulk", so it is user-gated.

Not automated (needs judgement, ~20 issues): `type:finding` + `sev:*` on #1–#10 and any
critique-derived issue; `gate:owner` / `gate:data` on the ~10 named owner decisions and
the FIX-gated items; `agent-ready` on the pipeline-ready set.

### 2.3 Milestone descriptions

Six drafted from each roadmap's `goal.objective` + top-3 `key_results` + the now-lane
entry-point ids + a link to the YAML and issue-map. ~1.0–1.3 KB each.

### 2.4 Views to add (web UI — exact specs)

| name | filter | group by | why |
|---|---|---|---|
| **Pipeline queue** | `is:open label:"type:milestone" lane:Now -label:blocked -label:"gate:owner"` | Milestone | the "what can I run now" view that does not exist today |
| **Blocked & gated** | `is:open label:blocked,gate:owner,gate:data` | Milestone | makes F2/F10 visible |
| **Findings** | `is:open label:"type:finding"` | Priority | security/critique remediation queue |
| **By area** (×N or one) | `is:open label:"area:lean"` etc. | Milestone | subsystem slices |
| **Recently done** | `is:closed` sorted by Closed ↓ | — | handoff + changelog source |
| rename `View 1` | — | — | unnamed leftover |

Then re-point **Now - current focus** at `label:"type:milestone" lane:Now` so it returns
~27 rather than 108.

### 2.5 Source-data fixes (in `plans/*/roadmap.yaml`)

- add `size:` to milestone/task items (fixes F6 at source), then re-run
  `roadmap-project-fields.py --apply`;
- materialize the **open residue** of `data-plane-governance`, `paper-metadata`,
  `source-truth` as a 7th milestone;
- triage the 11 legacy `plans/*.md`: tombstone the shipped ones, migrate the live ones
  via `roadmap-migrate.py`.

### 2.6 Fleet-registry follow-up (NOT arXMCP-local)

`roadmap-to-github.py`, `roadmap-project-fields.py`, `roadmap-schema.json` and
`github-conventions.md` are **registry-synced** (`.claude/.registry-manifest.json`) —
CLAUDE.md forbids editing synced copies. So these belong in `claude-registry`:

1. `LABELS_BY_KIND["milestone"] = ["type:task", "type:milestone"]`;
2. optional `area:` derivation from `links.code` in the converter;
3. `blocked` emission from `depends_on`;
4. adding `type:milestone` to `tools/labels.yml` so the whole fleet gets it.

Doing (1)–(4) upstream means every sibling repo inherits the fix; doing them in arXMCP
alone means the next `--apply` re-materializes without them.

---

## 3. Structure for the NEW work (from the two analyses)

Two analyses produced work that has nowhere to live on the board today.

### 3.1 From the architecture review — 78 surviving findings

These are **findings**, not roadmap items, and the fleet has a label for exactly this
(`type:finding` + `sev:*`) that has never been used. Proposal: file the **8 "must" hardening
items** as issues under a new milestone, and keep the rest as a referenced document rather than
78 issues (filing 78 would drown the board and most are S-sized cleanups).

**New milestone — "Boundary hardening: contracts, epochs, and the ops layer"**
Covers C1–C4 and H1–H7's must-list: the backup contract reconciliation, the Tier-2 cache key,
the `lean_verify` axiom axis, `ops/` packaging + `[project.scripts]`, corpus-version
invalidation, `/metrics` demutation, and the `assert` fix. ~8–12 issues, all S/M, no
dependencies on anything unbuilt. This is the highest-confidence work in either analysis
because every item is verified and small.

### 3.2 From the capability analysis — 26 capabilities in 6 themes

The analysis already sequences these into waves with explicit gating. Mapping waves to
milestones (a roadmap slug maps to one GitHub milestone, per doctrine):

| Proposed milestone | Roadmap slug | Contents | Gated? |
|---|---|---|---|
| **Discovery substrate — mine the corpus's negative space** | `discovery-substrate` | Wave 0 measurement spikes (S1–S4), `span-substrate` (P1), the five miners, plus Theme 4 fidelity debt (figure lane, notation consensus, `ascii-form`) | No — nothing waits on anything unbuilt |
| **Refutation and durable negatives** | `refutation-and-memory` | Theme 2 (refutation lane, `lean-name-inventory`, `formal-env-stamp`) + Theme 3 (census record, discovery backtest, attempt ledger) | Yes — on R3-m1/m2/m5/m7 and on `agent-platform-e5` |
| **Statement structure and the object axis** | *(defer)* | Themes 5–6 | Yes — on Wave-0 measurements; **file as `parked` with the un-park trigger in the body**, per the label's own contract |

**Recommended first move regardless of structure:** the analysis's own strongest sequencing
claim is to spend the first ~4 owner-days on the **discovery backtest** (P2) *before* any L or
XL commitment, because it is the only thing that can settle the two judges' root disagreement
with evidence rather than argument. That is one `type:spike` issue.

### 3.3 Authoring path

Doctrine (`roadmap-phase-materialize.md`) is unambiguous: author `plans/<slug>/roadmap.yaml`,
run `roadmap-validate.py`, run `roadmap-to-github.py` **dry-run**, review the printed plan, then
`--apply` on explicit per-run authorization, then `roadmap-project-fields.py --apply`, then
backfill `links.issue`.

The capability analysis is already in roadmap/1 shape — each capability carries title, mechanism,
size, `depends_on`, risks, and a blocked-today statement — so hand-authoring the YAML from it is
mechanical. The alternative is for you to run `/roadmap discovery-substrate` and let the 4-phase
planning pipeline author it, which is the more doctrinal route and produces RICE scores.
