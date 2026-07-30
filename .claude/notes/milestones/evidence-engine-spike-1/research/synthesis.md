# Phase 1 synthesis — evidence-engine-spike-1

**Mode:** single (general → brief-2). Status `complete`, 0 injection attempts, all claims
live-verified against the on-disk `var/` tree + the running arXMCP MCP server.

## What this spike actually is
A **labeling-pace dry run**, not a code milestone. The owner (Chris) hand-labels the first 5
queries, we record owner-minutes/query, extrapolate to the ~20-query fixture, and decide whether
to keep n=20 or cut. **LLM grading is barred as circular** — every label is owner-authored, so the
substantive step is irreducibly human. There is **no production-code diff** in this spike.

## Affected files / artifacts (deduped)
- READ-ONLY inputs: `.claude/docs/eval-curation.md`, `tools/validate_eval_fixtures.py`,
  `tests/eval/fixtures/queries.json`, `tests/eval/test_retrieval_quality.py`,
  `server/handlers/search.py:711`, `ops/watchdog_eval.py:70-75`,
  `var/arxmcp/notebooks/bridgeland-stability/`, `var/arxmcp/corpus/chunks/*/chunk_manifest.json`.
- WRITES (this spike only): `.claude/notes/milestones/evidence-engine-spike-1/spike-note.md`
  (the deliverable) + a scratch label file `dry-run-labels.json` under the same dir.
  **Must NOT touch** `tests/eval/fixtures/queries.json` (5 queries breaks the validator's
  all-or-nothing 0-or-20 rule).

## Acceptance criteria (traced to roadmap `evidence-engine-spike-1`)
1. Owner hand-labels the first 5 queries → **actual owner-minutes/query recorded** and
   extrapolated to a full-fixture estimate.
2. If the extrapolated total > ~2 owner-days → cut fixture size to the smallest n that still
   supports D9-R02's paired-comparison math (synthesized floor: **n≈12–15**, never below the
   watchdog's hard **n=10**; decision-grade n≈30–50 is grown opportunistically later, out of scope).

## Dry-run design (the owner's protocol)
- **Mechanism today:** the already-running loopback MCP server. Per query:
  `search_papers(query, k=10)` → ranked candidate chunk_ids (envelope confirms
  `corpus_version 4454`, dense-only); `get_chunk(chunk_id)` for full body to confirm a grade-3.
  chunk_ids come back as `arxiv:<paper_id>:<16hex>` — exactly the fixture's `_CHUNK_ID_RE` shape.
- **Runbook per query:** (1) write `query_text` FIRST (don't back-form from chunks); (2) list the
  chunks a perfect top-10 would contain (owner-recall pooling, typ. 1–3); (3) grade each 0–3
  (3=primary answer, 2=direct addressee, 1=one-click context, 0=omit); (4) ≥1 grade-3 required or
  swap the query; (5) never list grade-0.
- **Timing:** wall-clock per query, start on "write query_text", stop on "last grade recorded".
- **Include ≥1 proof-anchored query** among the 5 (proof chunks are NOT retrievable via
  `search_papers` — `excluded_kinds:["proof"]` at `search.py:711`; find one via a paper's
  `chunk_manifest.json`) so the extrapolation captures the slower proof path (AC-7 needs ≥5 proof).
- **Prefer new-style (`YYMM.NNNNN`) paper anchors** — the validator silently drops all 25 old-style
  `math/NNNNNNN` manifests today (m1 blocker below).

## Two m1 blockers surfaced (record, do NOT fix in this read-only spike)
- **B1 — `make eval` can't run:** the harness pins `DEFAULT_LANCEDB_PATH = var/arxmcp/index/lancedb`
  (`ingest/store.py:126`), which is ABSENT; ingested data lives per-notebook at
  `var/arxmcp/notebooks/bridgeland-stability/lancedb/`. m1 must repoint the harness (or build the
  shared index) or `make eval` keeps skipping. Owns evidence-engine AC2.
- **B2 — validator old-style-manifest gap:** `validate_eval_fixtures.py` discovers 172/197
  manifests, silently dropping the 25 old-style `math/NNNNNNN` ones — a grade-3 anchor from
  Bridgeland's foundational `math/0212237` would FAIL AC-3. Fix the glob in m1 or restrict anchors
  to new-style papers.

## external_writes_required (verbatim from brief-2)
```yaml
external_writes_required: []
```

## Open questions (≤5)
1. Owner's working-day definition for the "~2 owner-days" budget (8h? 16h?) — sets the cut trigger.
2. Which 5 of the candidate queries (brief-2 Q6) does the owner accept, and does query-4 (old-style
   anchors) get replaced or deferred behind the B2 validator fix?
3. Does the owner want to label the proof-anchored query via the manifest-read path now, or defer
   the proof quota until the m1 labeling-report tool exists?
4. Is `n≈12–15` an acceptable fallback floor if the estimate blows the budget, given decision-grade
   is n≈30–50 later?
