# proof-verify-handler-wiring-m3 — implementation summary

## One-line summary

New operator runbook at `docs/ops/notebook-modes.md` covering
per-daemon vs per-call `paper_id` filter deployment modes, session-cap
discipline, and 6 named failure modes; linked from the README's
runbook table.

## Commit range

`9e17617..<HEAD-after-feat-commit>`. Base SHA recorded in
`state.json::implementation_base`. Only one implementation commit
expected at the time of writing (orchestrator will append `rect` +
`chore` commits per the standard triple if Phase 3 surfaces findings).

## Acceptance criteria status

From the milestone brief at
`plans/proof-verify-handler-wiring-roadmap.md:230-245`:

- [x] **Doc section exists and is linked from root `README.md` or
  `docs/install.md`.** New file at `docs/ops/notebook-modes.md`
  (351 lines, matches the prose-density of existing runbooks under
  `docs/ops/`). README row added at `README.md:76-77` (one row
  appended to the existing operator-runbook table). The synthesis
  D1 resolution chose `docs/ops/` over `docs/install.md` per the
  precedent of 10 existing runbooks under that path; the brief's
  "docs/install.md or docs/notebooks.md" suggestion was superseded
  by the actual project convention.
- [x] **Doc explicitly names the 22-paper math.AG corpus at
  `var/arxmcp/index/lancedb-staging` as the working example for
  downstream cross-reference.** Named in the Summary table's
  trailing paragraph and the Mode 1 launch example. Labeled as
  the **developer-only / spike** path; canonical production path
  (`var/arxmcp/index/lancedb`) and the per-notebook Variant 1
  path (`var/arxmcp/notebooks/<slug>/lancedb/`) named alongside
  per synthesis D2.
- [x] **Doc states the per-call paper_id list size budget.**
  Mode 2 "Per-call budget" table names `MAX_PAPER_ID_FILTER_ITEMS
  = 100` at `server/handlers/search.py:108` with the 256 KB
  envelope cap from `server/config.py:58` as the secondary bound.
  Per synthesis D3, the hard cap is stated as the guarantee
  rather than inventing a higher "tested-N".
- [x] **Doc cites the `EXPECTED_TOOL_SCHEMA_SHA256` stability
  commitment.** "Schema stability commitment" section cites
  `tests/test_server_tool_schema.py::EXPECTED_TOOL_SCHEMA_SHA256`
  + `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`, quotes
  `07-multi-agent-caching.md` Property 1, and references the m2
  rect F6 `_meta`-strip contract at `server/tools.py::register_all`.
- [x] **No code changes — pure docs.** Only `docs/ops/notebook-modes.md`
  (new) and `README.md` (+1 row) touched. No `server/`, `ingest/`,
  `tests/`, or other source-tree files changed.

## New / changed files

- **NEW:** `docs/ops/notebook-modes.md` (~351 lines).
- **EDIT:** `README.md` (+1 row in the runbook table at line 77).
- **NEW (state):** `.claude/notes/milestones/proof-verify-handler-wiring-m3/`
  with research briefs + synthesis + this summary.

## Tests

No new tests. Pure-docs milestone. The existing test surface
(notably `tests/test_server_tool_schema.py` for BP1 byte-stability)
remains intact.

`make test`: **2259 passed, 9 skipped, 1 xfailed.** Identical to
the m2-complete baseline. Ruff clean.

## External writes required

**None.** Pure-docs change. Phase 4 has no external-write
authorization gates to fire.

## Deviations from the brief

- **Doc location.** Brief allowed
  `docs/install.md` or `docs/notebooks.md`. The synthesis (R-1's
  surfacing of the established `docs/ops/` precedent at
  `README.md:63-76` — 10 existing runbooks) chose
  `docs/ops/notebook-modes.md` instead. The brief's parenthetical
  was advisory rather than prescriptive; the doc-placement rule in
  `CLAUDE.md §1` (docs/ for README-linked operator content) is
  satisfied identically by `docs/ops/`.
- **"Tested up to N" wording.** Brief suggested phrasing like
  "tested up to N" for the paper_id budget. The synthesis (D3) ruled
  that no m1/m2 evidence supports a tested-N higher than the hard
  cap of 100, so the doc states the cap explicitly with the
  exercising test path (`TestRectificationGuards`) rather than
  inventing a number.
- **`lancedb-staging` labeling.** Brief named the path as "the
  working example." The synthesis (D2) labels it explicitly as
  **developer-only / spike** and names the canonical production
  path and per-notebook path alongside, so an operator reading
  the doc doesn't mistake the spike path for a production
  convention.

## What this unblocks

Track A of the proof-verify-handler-wiring roadmap is now one
milestone short of done. The downstream `/proof-verify` pipeline
has both the runtime substrate (m1: filter wiring, m2:
filters_applied echo) and the operator-facing documentation (m3)
to deploy in either per-daemon or per-call mode. m4 (notebook
ingest end-to-end) follows in the Next lane.
