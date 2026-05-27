# Critique — textbook-ingest-m3

**Critic:** adversary
**Generated:** 2026-05-27T23:35:00Z
**Commit range:** 397a869^..397a869
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES. Both SHAs verified live-passing at HEAD; SQLite v2→v3
  migration is correct + idempotent; Pydantic pattern validation rejects
  every realistic edge case (case, trailing/leading newline, empty,
  whitespace, suffix). The cache discipline of the milestone is clean.
- One HIGH finding: the m3 description edit promises that
  `filters.paper_id` is "validated against the arXiv or textbook:<slug>
  format" but the handler `server/handlers/search.py:175` still calls
  `is_valid_arxiv_paper_id`, which REJECTS textbook IDs. Any agent that
  reads the new description and sends a textbook paper_id will be hard-
  errored with `"filters['paper_id'] contains 1 invalid arXiv IDs"`.
- Counts: 0 CRITICAL, 1 HIGH, 3 MEDIUM, 1 LOW.
- The HIGH is the contract-drift root cause documented at length in
  `ingest/identifiers.py:160-178` (m1's own docstring: "once m2 ships,
  [callers] opt into the union by switching to `is_valid_paper_id`").
  m3 did not perform the switch and the synthesis miscited which
  validator search.py uses.
- Cache-byte-stability axis (the primary axis for m3): hash recomputation
  via the live test passes — `c8210225...` and `41305993...` are correct.
  `_meta._tool_schema_version` is correctly stripped from the BP1 payload
  per `_live_tools_payload` (test_prompts.py:464); the version bump alone
  does NOT drift BP1 — the description text edit is the actual driver.
- Migration coverage: a v1→v3 path test and an open-twice idempotency
  test are MISSING (MEDIUM). v0→v3 is exercised transitively by the
  pre-existing `store` conftest fixture so the m3 ALTER does run against
  freshly-created tables.
- Docs are clean. The `prompts-bp-discipline.md` "Textbook-family BP1
  bump" section is well-structured. Three schema-version-pin tests
  correctly auto-track via dynamic import.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Cross-critic agreement

_None — no file:line region was flagged by ≥ 2 critics._

<!-- end:cross-critic-agreement -->

## Findings

### F1 — search_papers description lies about textbook filter acceptance

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/handlers/search.py:175 (paired with server/tools.py:183)
- **What:** The m3 description edit in `server/tools.py:183` now reads
  "each validated against the arXiv or textbook:<slug> format" and the
  research synthesis D1 (research-synthesis.md) asserts "`is_valid_paper_id`
  returns True for `textbook:<slug>`; users via the `filters` argument
  may legitimately send a textbook paper_id". But the actual handler
  guard at `server/handlers/search.py:175` calls
  `is_valid_arxiv_paper_id(pid)` — which `ingest/identifiers.py:171`
  describes as a "Strict arXiv-only check — rejects the textbook form
  even though `is_valid_paper_id` accepts it." The error message at
  `search.py:179` then surfaces as `"filters['paper_id'] contains 1
  invalid arXiv IDs; first invalid: 'textbook:my-book'"` — the word
  "arXiv" is hard-coded into the error.
- **Why it matters:** Any sub-agent (sketcher / autoformalizer / tactician)
  that obeys the new tool description and sends a textbook paper_id in
  `filters` is hard-errored. The new BP1 cache bump exists precisely to
  invalidate every agent's prior `tools/list` snapshot so they see this
  new description — but the substrate behind the description is broken.
  This is the exact contract chain m1 set up: `ingest/identifiers.py:161`
  literally says "*once m2 ships, [callers] opt into the union by
  switching to `is_valid_paper_id`*". m2 has shipped (visibly: the
  research-synthesis cites m2 finalize as the base commit `0ac2bd4`).
  m3 was the milestone that was supposed to perform the switch in
  lockstep with the BP1 invalidation that announces it. The switch did
  not happen; the announcement did.
- **Proposed fix:**
  1. In `server/handlers/search.py:68`: change the import to
     `from ingest.identifiers import is_valid_paper_id` (the union form).
  2. At `server/handlers/search.py:175`: rewrite the comprehension to
     `invalid = [pid for pid in paper_ids if not is_valid_paper_id(pid)]`.
  3. At `server/handlers/search.py:177-180`: revise the error message
     to drop the word "arXiv" — e.g. `f"filters['paper_id'] contains
     {len(invalid)} invalid IDs (neither arXiv nor textbook:<slug> form);
     first invalid: {invalid[0]!r}"`.
  4. Spot-check `_escape_paper_id_literal` (line 120) — the LanceDB
     escape function is content-agnostic and will work for the colon
     in `textbook:my-book` as a SQL string-literal payload (the colon
     is not a SQL meta-character). No further change required there.
  5. The other handlers (`server/handlers/lemma.py:94`,
     `server/handlers/definitions.py:89`, `server/handlers/paper.py:65`)
     legitimately stay on `is_valid_arxiv_paper_id` — their tool
     descriptions don't promise textbook support and the m3 brief
     touched only `SEARCH_PAPERS`. Do not widen those.
- **Regression guard:** add a test in `tests/test_search_filter.py`
  shaped like:
  ```python
  def test_textbook_paper_id_in_filter_accepted(self, fake_resources):
      # F1 regression — m3 description promised textbook acceptance;
      # validator must match.
      from server.handlers.search import _build_paper_id_predicate
      # Single str + list form both
      assert "textbook:my-book" in _build_paper_id_predicate("textbook:my-book")
      pred = _build_paper_id_predicate(["textbook:my-book", "2401.00001"])
      assert "textbook:my-book" in pred and "2401.00001" in pred
  ```
  AND a negative test: garbage like `"textbook:UPPERCASE"` and
  `"textbook:x"` (too-short slug) still rejected.

### F2 — Missing migration coverage for v1→v3 path

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_notebook_api.py:660-720 (TestNotebookKindMigration)
- **What:** The new `TestNotebookKindMigration` exercises only the
  v2→v3 path (seeds a v2 DB then opens — see lines 660-720). The
  most-pessimistic legacy path — a v1 DB that pre-dates m9's
  `notebook_ingest_runs` table — runs BOTH the v1→v2 ALTER and the
  v2→v3 ALTER in sequence on the same connection. That code path
  exists in `server/notebooks_store.py:162-197` (the implementation
  has both the `< 2` block creating `notebook_ingest_runs` AND the
  `< 3` block adding `notebook_kind`) but no test seeds a v1 DB to
  prove the two ALTERs interleave cleanly.
- **Why it matters:** Real legacy DBs in operator hands may be at v1
  (m9 shipped earlier). The captured-snapshot pattern
  (`current_version` is read ONCE at line 116 and reused in all three
  `if` blocks) is correct for forward-only ordered migrations and was
  verified manually, but the test surface does not lock it. A future
  edit that, e.g., re-reads `current_version` between blocks would
  silently break the v1→v3 path with no test failure.
- **Proposed fix:** add a `test_v1_to_v3_migration_runs_both_blocks`
  test that:
  - Manually creates a v1 schema (notebooks + notebook_papers tables
    only — no `notebook_ingest_runs`).
  - Sets `PRAGMA user_version = 1`.
  - Opens via `NotebooksStore.open(db_path)`.
  - Asserts: (a) `notebook_ingest_runs` table now exists; (b) the
    `notebooks` table has `notebook_kind TEXT NOT NULL DEFAULT 'arxiv'`;
    (c) `PRAGMA user_version` is 3; (d) any pre-existing notebook row
    backfilled to `notebook_kind == 'arxiv'`.
- **Regression guard:** the test itself is the guard. ~30 LOC.

### F3 — paper_id row description in search_papers_result.json drifted

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/schemas/search_papers_result.json:48-49
- **What:** The `paper_id` field description in the result-row schema
  still reads "arXiv paper id without 'arxiv:' prefix. May or may not
  carry a version suffix (vN) depending on what the chunker indexed."
  The m3 commit bumped `version` 12→13 with a description that
  documents the SEARCH_PAPERS-level filter widening, but the per-row
  `paper_id` field documentation was NOT widened to reflect that result
  rows from textbook chunks will carry a `textbook:<slug>` paper_id.
  Cross-reference: `chunk_id.pattern` on line 42 was widened in m1 to
  cover both branches; the `paper_id` field is the other half of that
  pair and was left unchanged.
- **Why it matters:** Documentation drift. An MCP client parsing the
  result envelope's JSON Schema will see `paper_id` as "arXiv … vN"
  and apply arXiv-only post-processing. Less load-bearing than F1
  (this is a description string, not a validator), but the m3 brief
  was specifically "the BP1 cache-invalidation checkpoint for the
  whole textbook-ingest family" — so this field's drift was supposed
  to be closed here.
- **Proposed fix:** in `server/schemas/search_papers_result.json:49`,
  rewrite the description to:
  `"Paper identifier without prefix. Two shapes (textbook-ingest-m1):
  arXiv (e.g. '2401.00001', optionally with 'vN' suffix) or textbook
  ('textbook:<slug>'). The chunk_id field above pins the regex for
  both branches."`
  Then re-bump `version` 13→14, re-pin `EXPECTED_TOOL_SCHEMA_SHA256`
  AGAIN, and re-pin `EXPECTED_BP1_SHA256` AGAIN. **Or** — preferred —
  bundle this with F1 in one rect commit so the cache invalidates
  exactly once more (12→14, not 12→13 then 13→14). The two-step
  cache invalidation defeats the whole "coordinated checkpoint"
  thesis of m3.
- **Regression guard:** keep `test_schema_version_matches_after_m2_bump`
  in `tests/test_search_filter.py` (already there). Optionally add a
  micro-test that grep-asserts the word "textbook" appears in the
  `paper_id` field description (defends against future drift).

### F4 — No idempotency-on-second-open test for the v3 migration

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_notebook_api.py:732-749 (test_v3_schema_user_version_set)
- **What:** `test_v3_schema_user_version_set` opens a fresh DB ONCE
  and asserts `PRAGMA user_version == 3`. It does not close + re-open
  the store to verify the v2→v3 block (line 192 `if current_version
  < 3:`) is a no-op on a current DB. Manual verification (via
  `NotebooksStore.open` against a v3 DB) confirms it IS idempotent —
  the connection's `PRAGMA user_version` is now 3 before the snapshot
  is captured, so all three migration blocks are skipped. But the
  test surface does not lock this.
- **Why it matters:** A future contributor adding a v4 migration
  could subtly break re-open idempotency (e.g. by using
  `CREATE TABLE` instead of `CREATE TABLE IF NOT EXISTS`) and not
  notice until production. The m1 memory written 2026-05-27 on
  stale-docstring-anti-pattern noted that m1's `schema.py:13-15`
  docstring claimed the migration helper "is not yet implemented"
  while m2 had landed it; an analogous trap here is "migration runs
  once" being only narrative-claimed, not test-locked.
- **Proposed fix:** extend `test_v3_schema_user_version_set` (or add
  a sibling `test_open_is_idempotent_against_v3`) to:
  1. Open + close a fresh DB → asserts version == 3.
  2. Re-open + close → asserts version still == 3, no row count
     change, no schema diff (`PRAGMA table_info(notebooks)` byte-
     equal across opens).
- **Regression guard:** the test itself.

### F5 — Notebook GET-by-slug endpoint absent; notebook_kind never reachable via single-notebook GET

- **Severity:** LOW
- **Source:** adversary
- **File:** server/routes/notebooks.py (no `@router.get("/notebooks/{slug}")`)
- **What:** `NotebooksStore.get_notebook` was extended in m3 to return
  `notebook_kind` in the dict (line 261 in notebooks_store.py), but
  there is no public route that surfaces a single notebook's metadata.
  Callers can only see `notebook_kind` via `GET /notebooks` (list) or
  `POST /notebooks` (echo on create). Multiple internal sites call
  `store.get_notebook(slug)` for existence checks (e.g. routes lines
  381, 413, 572, 788, 870) and now pay an extra column-fetch cost
  for a field they never use.
- **Why it matters:** Cosmetic + micro-perf only. Operators eyeballing
  a single notebook's metadata go through the list endpoint, which is
  fine. No regression risk.
- **Proposed fix:** none required for m3. If e4 (cross-corpus search)
  needs single-notebook metadata at the MCP surface, that milestone
  can add `GET /notebooks/{slug}`. If readers want to avoid the
  unused column-fetch on existence checks, refactor
  `get_notebook(slug, *, fields=...)` later. Both are deferred.
- **Regression guard:** none required.

## What was done well

- **SHA recomputation discipline.** Both `EXPECTED_TOOL_SCHEMA_SHA256`
  and `EXPECTED_BP1_SHA256` re-pin correctly at HEAD; the live test
  suite confirms `c8210225...` and `41305993...` are the actual
  computed hashes. The `--update-tool-schema-hash` flag's "version
  must be bumped first" guard was respected (`TOOL_SCHEMA_VERSION`
  12→13 is in the same commit as the hash bump).
- **BP1 byte-identity correctly carved out from `_meta`.** The
  `_live_tools_payload` projection at `tests/test_prompts.py:464`
  ships only `[{name, description}]` — `_meta.tool_schema_version`
  is intentionally excluded so the version bump alone does NOT
  invalidate BP1. The actual BP1 driver is the description text edit.
  This is the right discipline per `tests/test_prompts.py:798-810`.
- **Coordinated-checkpoint thesis honored.** m1's chunk-id regex
  widening and m2's chunks-schema migration deliberately deferred
  their BP1-re-pins. m3 bundles the single BP1 invalidation, the
  description edit, AND the version bump in ONE commit — matching
  the `853011e` (verification-feedback-m3) precedent.
- **`SYSTEM_PROMPT` left alone.** Synthesis D3 correctly identified
  that adding textbook-aware language to the still-placeholder
  `SYSTEM_PROMPT` would be aspirational drift; m3 honored that.
- **Migration safety.** The v2→v3 ALTER uses `NOT NULL DEFAULT 'arxiv'`
  which SQLite handles in O(1) via the column-descriptor default —
  no row-rewrite, no data loss. The migration-summary text in
  `notebooks_store.py:181-191` correctly cites this property.
- **Pydantic pattern soundness.** `Field(default="arxiv",
  pattern="^(arxiv|textbook)$")` was verified against Pydantic 2.13.4
  to correctly reject every edge case I probed: `"Arxiv"` (case),
  `"arxiv\n"` / `"\narxiv"` (anchored trailing/leading newline — the
  F3 trap from m1), `""` (empty), `"arxiv extra"` (suffix), `"arxivX"`
  (no-separator suffix).
- **Annotated comment ledger discipline.** The new
  `EXPECTED_BP1_SHA256` literal at `tests/test_prompts.py:642-644`
  carries a multi-line comment ledger explaining the v12 → v13 bump,
  the SHA new value, AND a cross-reference to
  `prompts-bp-discipline.md`. The ledger pattern is consistent with
  the historical layers in the same file (lines 604-631).
- **prompts-bp-discipline.md updated.** The new "Textbook-family BP1
  bump" section (`.claude/notes/prompts-bp-discipline.md:235-277`) is
  the same structure as the historical sections, with a clear "what
  changed / what didn't / new SHAs" tabulation.
- **`pytest --update-tool-schema-hash` used (not hand-edited).** The
  test-schema literal at line 95 was regenerated via the flag — the
  preferred path documented in the module docstring. The flag's F2
  guard (refuses without a version bump) was respected.

## Recommended rectification order

1. **F1 — search.py validator widening.** Highest leverage. Fixes
   a real shippable bug (description promises what handler rejects)
   AND is small (~5 LOC + 2 tests). Doing F3 BEFORE F1 means a
   second BP1 invalidation that should be avoided; doing F1 then F3
   together in one rect commit lets one further re-pin (12→14, not
   12→13 then 13→14) cover both.
2. **F3 — paper_id row description in JSON schema.** Bundle into
   the same rect commit as F1 to avoid a second BP1 invalidation.
   Re-pin both `EXPECTED_TOOL_SCHEMA_SHA256` (auto via flag) and
   `EXPECTED_BP1_SHA256` (manual) once more.
3. **F2 — v1→v3 migration test.** ~30 LOC. Independent of F1/F3.
4. **F4 — idempotency-on-second-open test.** ~15 LOC. Independent.
5. **F5 — defer.** Cosmetic; if you don't fix it, file under
   `deferred_findings`.

## Rectification status

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
