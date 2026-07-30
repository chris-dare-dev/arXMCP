---
project: source-truth
type: handoff
status: complete
authorship: agent-generated
handoff_kind: review
date: 2026-07-13
companion: HANDOFF-2026-07-13-source-truth-continuation.md
roadmap: plans/source-truth/roadmap.yaml
reviewer_target: opus
review_status: requested
milestones_covered:
- data-plane-governance-spike-1
- data-plane-governance-m2
- source-truth-spike-3
- source-truth-spike-4
- source-truth-m1
- source-truth-m2
- source-truth-m3
- source-truth-m5
tags:
- project/source-truth
- type/handoff
- authorship/agent-generated
- handoff/review
- review/requested
- project/arxmcp
aliases:
- source-truth — session review handoff (2026-07-13)
---

# HANDOFF (REVIEW) — source-truth session, 2026-07-13

> **Audience:** a high-effort Opus review session. **Goal:** independently scrutinize everything
> shipped this session — correctness, safety, whether the "done" claims are honest, the coding
> practices, and the program direction — against the diffs + live state. This is a REVIEW handoff
> (find problems); the companion continuation handoff
> ([[HANDOFF-2026-07-13-source-truth-continuation]]) is for the next builder. Roadmap:
> `plans/source-truth/roadmap.yaml`.

## 0. TL;DR — what this session did

All commits are on `main` and PUSHED (`origin/main == 32f4d69`; a concurrent `8045da6` memory-consolidation
commit sits unpushed on top — not this session's). Every milestone ran the full 4-phase
`/milestone-pipeline` (Research → Implement → Critique → Rectify) with 2 opus critics each.

| # | Work | Repo | Key SHAs (branch `main`) | State |
|---|---|---|---|---|
| 1 | data-plane-governance spike-1 (owner sitting) + m2 (disposition 6 plan tracks) | arXMCP | d7bfe2b, 616e3a8, ad64b5d | SHIPPED (docs/plan-tracking) |
| 2 | source-truth spike-3 (span-anchor stability) + spike-4 (schema-v2 migration dry-run) | arXMCP | b2df5f7 | SHIPPED (measurement/validation) |
| 3 | source-truth-m1 — revision registry + OAI-PMH license provenance (advisory) | arXMCP | 0f2bd11, 846724a, ebc4637, 823c43c, bddfd90 | SHIPPED + LIVE (registry populated) |
| 4 | source-truth-m2 — chunks schema v2 (spans/truncation/printed-numbers) | arXMCP | 2572f2f, ac0ff62, 2345b08, 60de766 | SHIPPED + LIVE (19,581 rows hydrated) |
| 5 | source-truth-m5 — get_chunk surfaces the 5 fields | arXMCP | b92fcc7, 55238ed, 624fd94 | SHIPPED (needs server restart to serve) |
| 6 | source-truth-m3 — arxmcp://corpus-manifest resource | arXMCP | d2d9fe6, e183413, 32f4d69 | SHIPPED (needs server restart to serve) |

**Live-behavior vs dormant.** LIVE data mutations: m1 populated per-notebook `documents.db` registries;
m2 hydrated 5 new columns on the live `chunks` tables (19,581 rows). NEW served surfaces (test-verified
but only on the wire after a `make up` restart): m5's `get_chunk` fields, m3's `arxmcp://corpus-manifest`
resource. DORMANT: serving is unchanged — license is advisory (`license_ref`), the operator override flag
is recorded but not consumed. The fail-closed flip is m4 (NOT in this session, owner-gated).

---

## 1. data-plane-governance — spike-1 + m2 (SHAs d7bfe2b, 616e3a8, ad64b5d)

Owner "sitting" over the six previously-untracked plan directories, then executed the dispositions into
git. spike-1 produced a disposition matrix (3 parallel research pair-briefs) → owner accepted all six as
recommended (2 commit-as-is: evidence-engine, scale-ops-hardening; 4 revise-then-commit: agent-platform,
researcher-workbench, retrieval-unlocks, trustworthy-release; 0 veto). m2 amended `agent-platform`'s
`roadmap.yaml` to move the orchestrator dispatch loop out of this repo per the data-plane ADR (Decision
2/3), applied the 3 smaller doc-only revisions, and committed all 6 tracks.

### What to SCRUTINIZE
- **The agent-platform ADR amend** (d7bfe2b): did it truly re-scope ALL SIX `cg1`-tagged items (e5,
  spike-1, m8, t-dispatch-loop, t-transcript-recording, t-canned-task-run) to the external repo? The
  acceptance criterion is `plans/data-plane-governance/roadmap.yaml:189` ("no item scopes a server-side
  dispatch loop or per-run agent memory inside this repo"). Grep the amended `plans/agent-platform/
  roadmap.yaml` for residual in-repo loop-build directives.
- The 4 revise-then-commit tracks (616e3a8): are the doc-only revisions faithful to §4.8/§4.9 and the
  R1/R2/R5 interlocks the briefs cited, or did they drift? These are plan docs, not code — low blast radius.

## 2. source-truth spike-3 + spike-4 (SHA b2df5f7)

Two validation spikes that gated m2. **spike-3** re-parsed 5 papers and found the `(element_id,
char_offsets, text_hash)` span anchor UNSTABLE across a re-parse (char-offsets matched 11%; the SAME
local LaTeXML build twice matched 100% — so the drift is ar5iv-vs-local *pipeline* drift, not LaTeXML
nondeterminism) → verdict: anchor on `(revision_checksum + normalized_text_hash)` string only.
**spike-4** dry-ran the 5-column migration on a COPY of the live LanceDB dir → clean in-place extension
for string columns via the existing `_migrate_chunks_schema_if_needed`.

### What to SCRUTINIZE
- spike-3's n=5 and its "only one LaTeXML version tested" caveat: the checksum+text-hash design rests on
  it. Is the whole-section-16%-vs-chunk-body-88% stability split it reports credible? (This decided m2's
  entire `source_span` shape.)
- spike-4 ran on a scratch COPY (not the live table) — confirm the dry-run methodology, and that the
  struct-vs-string finding (structs fail DataFusion's SQL-cast) is what actually forced `source_span` to
  be a string.

## 3. source-truth-m1 — registry + OAI-PMH license (SHAs 0f2bd11, 846724a, ebc4637, 823c43c, bddfd90)

New `server/documents_store.py` per-notebook SQLite revision registry + `tools/oai_license.py` (OAI-PMH
GetRecord license client + advisory 3-way `license_status`) + `tools/notebook_documents_backfill.py` +
coverage report. **Spike-driven pivot:** license comes from OAI-PMH (`oaipmh.arxiv.org/oai`), NOT the
Atom client the roadmap assumed (spike-1: Atom = 0/30). Live-verified that old-style papers carry no
license at all (arXiv-side gap). Three owner-approved decisions: 3-way status, raw-source abstention
marker, >20%-on-unknown escalation. **Go-live:** backfilled both notebooks — bridgeland 9.9% unknown (no
escalation), fourier 19.2%.

### What to SCRUTINIZE
- **The Retry-After:0 fix** (rect 823c43c, `tools/oai_license.py`): the critique caught a real busy-loop
  (a `503 + Retry-After: 0` spun with zero delay). Verify the clamp `wait = max(wait, POLITENESS_SLEEP_SECONDS)`
  actually floors it and the regression test is non-vacuous.
- **Untrusted-XML safety:** `defusedxml` (not plain ElementTree), redirect-pinning, byte-cap, id-validation
  before URL interpolation. Both critics called Axis-3 clean — try to break it.
- **0-re-embed is structural:** the backfill must never import `ingest.embedder`. Confirm.
- **The go-live coverage numbers** (9.9% / 19.2%): re-run `python -m tools.documents_coverage_report` and
  check the census is honest (3-way, `unknown` never folded). The escalation gate is on `unknown` alone.

## 4. source-truth-m2 — chunks schema v2 (SHAs 2572f2f, ac0ff62, 2345b08, 60de766)

5 nullable columns (`source_revision_id`, `source_span`, `truncated`, `printed_number`, `license_ref`) +
the printed-number extractor + a 0-re-embed backfill. `source_span` = the spike-3 JSON string
`{rev,txt,id}` resolving via chunk-body text-hash. Backfill = `merge_insert(...).when_matched_update_all()`
read-modify-write mirroring `ingest/embed_equations.py` (NOT `Table.update()` / `write_chunks`).
**Go-live VERIFIED:** hydrated both notebooks (19,581 rows) with **0 embedding mismatches** (bit-identical
vs a pre-snapshot), row/chunk_id counts unchanged, source_span resolved 14,947/15,106 (bridgeland) +
4,475/4,475 (fourier), 4+3 F2-suspected old-style papers flagged.

### What to SCRUTINIZE
- **The 0-re-embed guarantee** — the highest-value claim. The go-live compared embeddings against a
  pre-snapshot and found 0 mismatches, but scrutinize the `merge_insert` read-modify-write mechanism for
  any float round-trip / dtype coercion / column reorder that a snapshot-diff could miss.
- **The 159 `chunk_id_not_reproduced` abstentions** (all bridgeland): these are chunks whose chunk_id the
  backfill's re-chunk didn't reproduce (source_span=null). Is that a preamble-resolution divergence
  (rect M1's concern) or expected? The rect added a real-preamble round-trip test — check it's honest.
- **printed_number F2 blind spot:** spike-2 confirmed old-style pre-`\newtheorem` papers render theorems
  as plain bold text (0 recoverable). The extractor flags these per-notebook; verify the flag threshold.
- The rect (2345b08) adapted M4 ("skip terminal abstentions" was unimplementable) — check the adaptation
  is sound, not a dodge.

## 5. source-truth-m5 — get_chunk surfaces the 5 fields (SHAs b92fcc7, 55238ed, 624fd94)

`get_chunk`'s response `chunk` dict gains the 5 m2 columns, **each via `row.get()`** (the landmine: 2
live `-pdfs` notebooks are still on the 21-col schema → bracket-indexing would 500). `TOOL_SCHEMA_VERSION`
17→18 + a standalone `EXPECTED_TOOL_SCHEMA_SHA256` re-pin; BP1 verified unaffected. `license_ref` is
advisory (NOT wired into serving/truncation — that's m4). **Deviations:** single research brief (not 2);
inline implement + inline rectify (the delegated implementer returned empty/spurious once, so it was done
inline).

### What to SCRUTINIZE
- **`row.get()` on ALL FIVE fields** — a single `row["..."]` would 500 `get_chunk` on the `-pdfs`
  notebooks in production. The rect added a WIRE-level null-survival test (M1). Verify no field slipped.
- **`license_ref` stays advisory** — grep `server/` to confirm it is NOT wired into `is_open_access` /
  the `license_truncated` branch. A premature m4 wiring here would be a real defect.
- **The schema-hash re-pin** (b92fcc7): `TOOL_SCHEMA_VERSION` bumped 17→18, `EXPECTED_TOOL_SCHEMA_SHA256`
  re-pinned, GET_CHUNK description/inputSchema byte-identical (so BP1 didn't move). Run
  `tests/test_server_tool_schema.py tests/test_prompts.py` and confirm both green.
- **`chunk.truncated` overloading:** it's INGEST provenance, distinct from serving `truncated_for_license`
  / `body_truncated`. The rect added a disambiguation comment + snippet-contract §h. Judge whether an
  agent could still be misled.

## 6. source-truth-m3 — arxmcp://corpus-manifest resource (SHAs d2d9fe6, e183413, 32f4d69)

New read-only, on-read-generated MCP resource: a content-addressed snapshot of the m1 registry (per-revision
checksums + status), 3-way license census, corpus_version + index versions, withdrawn/superseded
invalidation edges, and the per-notebook override flag. `content_hash` = sha256 of the canonical
`snapshot` alone (metadata outside the boundary). It's a RESOURCE → outside the `tools/list` hash (no
schema re-pin). New pure module `server/corpus_manifest.py` + 24 tests.

### What to SCRUTINIZE
- **Content-hash DETERMINISM** — the load-bearing property. `json.dumps(sort_keys=True)` orders dict keys,
  but the `revisions` value is an ARRAY (sort_keys does NOT sort arrays). Confirm `revisions` + the rollup
  input are explicitly `sorted((work_id, arxiv_version))`, and read-stability is tested.
- **The read-purity fix** (rect e183413, M1): the adversary empirically confirmed the ORIGINAL read WROTE
  to `notebooks.db` (`OperatorSettingsStore.open` created the `operator_settings` table on a table-absent
  db). The fix uses a `mode=ro` sqlite connection. Verify it genuinely cannot create the table (the rect's
  test snapshots `sqlite_master`), and that the module's "a read never writes" docstring is now TRUE.
- **Invalidation is fixture-only:** 0 live withdrawn/superseded rows exist, so the `invalidated` /
  `active_rollup_sha256`-exclusion logic is proven ONLY by a synthetic `upsert_records` fixture. Check the
  fixture is real and the exclusion is correct.
- **Allowlist-by-projection:** `license_uri` + `display_name` are deliberately EXCLUDED; only `override.note`
  (+ `set_by`/`set_at` after the L2 rect) are operator-freeform, neutralized by the payload-wide
  `<retrieved_manifest>` escape-on-emit. Confirm no external string leaks unescaped.

---

## N+1. Cross-cutting durable gotchas + decisions

1. **The running MCP server serves OLD code.** m5's `get_chunk` fields + m3's manifest resource appear on
   the wire only after `make up`. Do NOT flag "the fields aren't in the live server" as a defect — the
   tests (incl. a real-wire `call_tool` test) verify them; live serving needs a restart. Judge on
   "correct + test-verified", not "not yet activated".
2. **Concurrent sessions land on `main` throughout** — this repo runs multiple sessions on one working
   tree. Commits from other sessions interleave with this session's (kuzu-close `6c5ff0d`/`463b870`,
   Windows-test `07f69e7`/`16dc91f`, ingest-robustness `89f58df`/`1cdc2bb`, auto-id `880fcfd`,
   memory-consolidation `8045da6`). None of those are this session's to review. Use the per-item SHAs in §0.
3. **The 2 `-pdfs` (MinerU) notebooks are un-hydrated** (pre-m2 schema, no `documents.db`) → m5 surfaces
   their 5 fields as null, m3 marks them `registry_present:false`. This is a correct abstention, a known
   accepted state, NOT a bug. Full hydration is a tracked fast-follow.
4. **Serving is advisory this session.** `license_ref` and the override flag change no serving behavior;
   the fail-closed flip is m4 (owner-gated). Judge m1/m5's license work on "advisory + honestly labeled".
5. **Pipeline-discipline deviations (all recorded in-milestone):** m5 ran a single research brief + inline
   implement/rectify (proportionate to a ~122-LOC serving change); m2/m3 delegated rectify (volume). The
   m5 implementer delegate returned empty once (spurious) → done inline. These are noted, not hidden.
6. **Roadmap `links.code` for m3 was STALE** (said `server/resources.py` — the process-lifecycle dataclass
   — when the real surface is `server/mcp_resources.py`). Research caught it; the roadmap text was not
   edited (one-writer rule). Reviewers reading the roadmap should not expect `server/resources.py` changes.

## N+2. Verification evidence (as of handoff)

- **Per-milestone gates GREEN** (Windows, `.venv/Scripts/python.exe -m pytest`): m1 spot-verified the new
  suites + full-suite claim (4009 passed); m2 240 changed-file tests + the tools/list pin; m5 66 + a
  wire-level test; m3 52 + the pin. Every milestone confirmed `EXPECTED_TOOL_SCHEMA_SHA256` intact (m5
  re-pinned it deliberately to a new value `5189d7a6…`; m1/m2/m3 left it untouched). `ruff` clean per diff.
- **Go-lives VERIFIED (not just claimed):** m1's registry populated (coverage report emitted real
  numbers); m2's live hydration compared embeddings against a pre-snapshot → **0 mismatches on 19,581
  rows**, row/chunk_id counts unchanged.
- **Critique invalidation rates** (all < 40%): m1 14%, m2 11%, m5 0%, m3 25%.
- **NOT verified / left behind:** the live MCP server (needs restart to serve m5/m3 — the wire tests stand
  in); the `-pdfs` hydration (out of scope); m4 (not started). The m2 `159 chunk_id_not_reproduced`
  abstentions were flagged + reason-coded but their root cause (preamble divergence?) was not chased to
  ground — a candidate scrutiny target.

## N+3. How to review (repro + response contract)

- **Diff access:** repo `arXMCP` (this checkout), branch `main`, session range
  `git log --oneline 5e9ceb2..32f4d69` (per-item SHAs in §0; concurrent-session commits interleave — filter
  to the `data-plane-governance` / `source-truth` / `feat(server|tools|ingest)` + `rect`/`chore(notes)`
  subjects listed above).
- **Review axes:** (1) correctness/safety of each change; (2) honesty of the done-claims vs evidence
  (esp. the m2 0-re-embed and the m3 read-purity, both of which had a claim the critique corrected);
  (3) coding practices (idioms, tests, blast radius — the untrusted-XML + content-hash + merge_insert
  surfaces); (4) program direction — is m4 (owner-gated fail-closed cutover) the right next step, and is
  the R2–R7 sequencing (R3 first) still sound?
- **Calibrate the verdict to state:** m5/m3 are test-verified-but-not-yet-served (restart pending) — judge
  on "safe + honest", not "not live". `license_ref`/override are dormant — judge on "safe to activate in m4".
- **Response format:** per-finding — severity (CRITICAL/HIGH/MED/LOW), the claim it refutes, evidence
  (file:line / command output), suggested disposition. End with an overall verdict: SHIP / SHIP-WITH-FIXES
  / NO-GO, **scoped per milestone** (data-plane-governance-m2, source-truth-m1/m2/m3/m5).

*Where to resume building: [[HANDOFF-2026-07-13-source-truth-continuation]].*
