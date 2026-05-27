# Critique — textbook-ingest-m2

**Critic:** adversary
**Generated:** 2026-05-27T22:43:05Z
**Commit range:** 8804544..decc597
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: 0 CRITICAL, 2 HIGH, 4 MEDIUM, 2 LOW. The 21-column schema migration is functionally sound and the test surface is strong; the open issues are nullability skew between fresh and migrated tables, plus a stale docstring that lies about the m2 deliverable.
- Highest-risk file:line — `ingest/store.py:284-285` — `cast('arxiv' as string)` SQL produces NOT-NULL columns on migrated tables while `CHUNKS_SCHEMA_V1` declares them nullable, creating divergent on-disk schemas depending on upgrade path. Confirmed by direct reproduction.
- The provenance gap (schema constants landed in commit 26c04fa, writer landed in decc597) is real but mitigated by both commits being on `main` in the linear history. The m2 implementation summary documents this honestly; no information was hidden.
- Cache byte-stability axis is clean — `server/tools.py`, `server/prompts.py`, `server/schemas/search_papers_result.json`, `tests/test_server_tool_schema.py`, and `tests/test_prompts.py` were untouched by m2. BP1 and tool-schema pin tests pass (42/42).
- The 9 new tests cover all 5 ACs plus the FM-1 migration path and the FM-6 backfill semantics. Critical gap: no test exercises the merge_insert path after a migration with a `source_kind=None` row (which would now fail post-migration but succeed on a fresh table) — F3.
- The migration helper handles partial-failure recovery correctly (each `add_columns` is its own dataset version; restart resumes from `missing = target - existing`) — confirmed by reproduction. Documented constraint of single-writer holds.
- The "extend the parser_used enum" brief deviation (added as 7th column instead of modifying a nonexistent one) is correctly handled and documented; the deviation is coherent.
- Security axis clean: SQL literals are static source-code strings (no user input), enum guard covers source_kind typos at write time. `parser_used` is documentary-only — flagged as MEDIUM since `_ALLOWED_SOURCE_KINDS` exists but no parallel `_ALLOWED_PARSER_USED` does.

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

### F1 — Stale "migration NOT implemented" docstring in schema.py

- **Severity:** HIGH
- **Source:** adversary
- **File:** ingest/schema.py:16-26
- **What:** The module docstring still says "Existing-row migration is NOT implemented in this milestone" and "Until that lands, operators upgrading a pre-m2 LanceDB dataset must re-create the table (delete and re-ingest) rather than open in place." This contradicts m2's `_migrate_chunks_schema_if_needed` which DOES backfill on-open. The wording is exactly the "lying docstring" anti-pattern that F1 from the embedder-truncation-m1 critique flagged on the same file lines 13-15.
- **Why it matters:** Operators reading `ingest/schema.py` first (the canonical schema doc) will be told the wrong thing — that they must re-ingest from scratch. The m1 critique closed an identical issue on this exact file; landing m2 reintroduces a doc inconsistency on the same module by failing to retract the now-false claim.
- **Proposed fix:** Replace lines 16-26 with: "**Existing-row migration shipped in textbook-ingest-m2** as `ingest.store._migrate_chunks_schema_if_needed`. On `write_chunks`, the helper calls `tbl.add_columns(...)` for each m2 column absent from the on-disk table, backfilling `source_kind='arxiv'` + `license='arxiv-license'` via SQL expressions; the four textbook-only columns plus `parser_used` get NULL. Idempotent across retries (each `add_columns` is its own MVCC version)." Keep the column-list enumeration for navigation.
- **Regression guard:** Add a test in `tests/test_schema.py` or `tests/test_store.py` that greps the `ingest/schema.py` module docstring (via `importlib.metadata` or `inspect.getdoc`) for the substring "NOT implemented" and the substring "delete and re-ingest" — both must be absent. Mirrors the m1-F1 closure pattern.

### F2 — Migrated tables get NOT-NULL source_kind/license; fresh tables get nullable; divergent on-disk schemas

- **Severity:** HIGH
- **Source:** adversary
- **File:** ingest/store.py:283-291
- **What:** `_TEXTBOOK_MIGRATION_DEFAULTS["source_kind"] = "cast('arxiv' as string)"` produces a column with `nullable=False` on LanceDB's on-disk schema, because the SQL cast returns a non-null literal value and LanceDB infers nullability from the expression. Same for `license`. Verified by direct reproduction: after migrating a 14-col legacy table, `tbl.schema.field("source_kind").nullable` is False, but `CHUNKS_SCHEMA_V1.field("source_kind").nullable` is True (matching a freshly-created v21 table).
- **Why it matters:** Two LanceDB datasets that pass m2's `_migrate_chunks_schema_if_needed` end up with DIFFERENT on-disk schemas: a freshly-bootstrapped dataset has nullable=True for `source_kind`/`license`; a legacy-then-migrated dataset has nullable=False for the same columns. Any downstream code (m4 cross-corpus filter, e5 license enforcement, an ops dashboard reading `tbl.schema`) that asks "is source_kind nullable?" gets path-dependent answers. The m2 docstring + `.claude/docs/snippet-contract.md:182` both claim "all nullable" — both are wrong for the migrated branch. Latent: a future write of `source_kind=None` (e.g. a bug or a stale fixture) will succeed on a fresh table and fail with `lance error: Invalid user input: The field 'source_kind' contained null values' on a migrated table. The enum guard catches None at write time TODAY but is the only thing preventing this divergence from becoming a P0.
- **Proposed fix:** Two options, prefer option (a). (a) Replace the SQL with a cast that explicitly preserves nullability: `"cast('arxiv' as string)"` → wrap as a coalesce against a typed-null, e.g. `"COALESCE(cast('arxiv' as string), cast(NULL as string))"`. If LanceDB SQL doesn't accept that, fall back to (b): after every `add_columns` call in `_migrate_chunks_schema_if_needed`, call `tbl.alter_columns({"source_kind": {"nullable": True}})` to re-mark the column as nullable. The simplest concrete fix is to land an `alter_columns` pass at the end of the migration helper that walks the 7 m2 columns and sets nullable=True to match `CHUNKS_SCHEMA_V1`.
- **Regression guard:** Add `tests/test_store.py::TestSchemaMigrationGuard::test_post_migration_nullability_matches_canonical` — build a 14-col legacy table, run the migration, assert that for every m2 column, `tbl.schema.field(col).nullable == CHUNKS_SCHEMA_V1.field(col).nullable`. Then verify a `merge_insert` of an Arrow batch with `source_kind=None` against the migrated table fails with the SAME error as it would on a fresh table (both should fail at the enum guard, not at differing lance-rs depths).

### F3 — No test for post-migration writes that exercise nullability or merge-update semantics on m2 columns

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_store.py:1029-1079
- **What:** `TestSchemaMigrationGuard::test_migration_adds_seven_columns_with_arxiv_defaults` writes one new arXiv chunk after migration and asserts the legacy row got `source_kind="arxiv"`. It does NOT exercise: (i) re-writing the same legacy chunk_id with `merge_insert` to update an m2 column (does an update of legacy `source_kind` from `"arxiv"` to `"textbook"` work?); (ii) writing a chunk with a populated `parser_used` value against the migrated table (does the NOT-NULL skew from F2 reach a real code path?); (iii) writing a chunk with `source_kind=None` post-migration (proves whether F2's behavioral divergence is reachable from a real driver bug). Without these, F2 stays latent and the upsert contract is only tested on the fresh-table path.
- **Why it matters:** The implementer's claim "merge_insert round-trips both arXiv-shaped and textbook-shaped chunks in the same table without column drift" (AC paraphrase) is only proven for FRESH tables (TestMixedCorpusInSameTable, line 902). On a MIGRATED table, that path is untested. The asymmetry is exactly the kind of latent foot-gun that surfaces months after ship when a real upgrade happens.
- **Proposed fix:** Add `TestSchemaMigrationGuard::test_merge_insert_update_on_migrated_table` — build a 14-col legacy table, migrate, then `write_chunks([chunk_with_same_chunk_id_as_legacy_row, source_kind="textbook"])` and assert the row was updated (not duplicated) and `source_kind=="textbook"`. Add `TestSchemaMigrationGuard::test_textbook_chunk_into_migrated_table` — same setup, then write a brand-new textbook chunk and assert all 7 m2 columns survived. ~30 LOC.
- **Regression guard:** Same tests are the guard.

### F4 — `parser_used` enum is documentary-only; no `_ALLOWED_PARSER_USED` parallel to `_ALLOWED_SOURCE_KINDS`

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/store.py:158-161, ingest/chunker_types.py:142-147
- **What:** `_ALLOWED_SOURCE_KINDS = frozenset({"arxiv", "textbook"})` is enforced in `_build_arrow_table` at write time. The parallel constant for `parser_used` does not exist; `_build_arrow_table` writes `chunk.parser_used` as-is. The synthesis D2 + chunker_types.py:175-180 docstring + 05-storage-and-indexing.md:80 all describe `parser_used` as an enum domain `{"ar5iv", "latexml", "mineru+latexml"}` with None for failure. The brief itself says "Extend the existing parser_used enum with mineru+latexml" — i.e. it IS supposed to be an enum. Today a chunker bug or upstream driver typo (`"latexm"`, `"ar5iv2"`, `"mineru"` alone without `+latexml`) lands silently.
- **Why it matters:** Same class as F10-from-E04_S01 (the `kind` enum guard that motivated `_ALLOWED_KINDS`). Without enforcement, `parser_used` typos pollute the chunks table and downstream chunk-grained re-parse decisions (synthesis D2 motivation) read the wrong provenance. The fix is symmetric and cheap.
- **Proposed fix:** Add `_ALLOWED_PARSER_USED = frozenset({"ar5iv", "latexml", "mineru+latexml"})` in `ingest/store.py` next to `_ALLOWED_SOURCE_KINDS`. In `_build_arrow_table`, add (after the source_kind guard): `if chunk.parser_used is not None and chunk.parser_used not in _ALLOWED_PARSER_USED: raise ValueError(...)`. The `is not None` clause preserves the documented `None` semantics for failure/unknown.
- **Regression guard:** Add `tests/test_store.py::TestParserUsedEnumGuard::test_invalid_parser_used_raises` and `::test_none_parser_used_accepted` and `::test_each_valid_parser_used_accepted`. ~20 LOC.

### F5 — `test_migration_unhandled_column_raises` mocks a module constant in a way that doesn't simulate the realistic future-m3 case

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_store.py:1081-1097
- **What:** The test patches `ingest.store.CHUNKS_SCHEMA_V1` to a schema with a fake `future_m3_col`, then calls `_migrate_chunks_schema_if_needed` on a 14-col legacy table. The realistic m3 scenario is: m3 lands new column(s) AND extends `_TEXTBOOK_MIGRATION_DEFAULTS` (or, more likely, lands a new `_M3_MIGRATION_DEFAULTS` table the helper consults). The test only exercises the negative branch (m3 forgot to update the defaults dict). It does NOT cover the positive branch (m3 added a column AND a default and migrations stack correctly across multiple milestones). The mock-a-module-constant pattern is also brittle to a hypothetical store.py refactor that re-imports `CHUNKS_SCHEMA_V1` into a different namespace.
- **Why it matters:** Trip-wire tests only catch the failure mode they encode. The next milestone that adds a chunks-table column will rely on this test as the "did I remember to extend defaults" reminder; if the test is brittle (the `patch("ingest.store.CHUNKS_SCHEMA_V1", ...)` form depends on a specific module-level alias), a future store.py refactor could silently delete the guarantee. Lower-priority than F1-F4 because the unhandled-column RuntimeError on real m3 work would still fire — just less helpfully.
- **Proposed fix:** Either (a) supplement the negative-branch test with a positive-branch one — `test_migration_extensible_with_new_default` — that monkey-patches `_TEXTBOOK_MIGRATION_DEFAULTS` to include a `future_m3_col` key with a real SQL expression, patches `CHUNKS_SCHEMA_V1` to include the field, runs the migration, and asserts the column was added; or (b) document the brittleness in a short comment above the test so a future reader knows the patch surface is intentional.
- **Regression guard:** The added test in (a).

### F6 — Backfill SQL `cast(NULL as int)` produces int32 — load-bearing but unverified by an explicit type-check assertion

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/store.py:287-288, tests/test_store.py:1029-1067
- **What:** The migration uses `cast(NULL as int)` for `page_start` / `page_end`. `CHUNKS_SCHEMA_V1` declares these as `pa.int32()`. I verified by reproduction that LanceDB's `add_columns` interprets `int` as `int32`, NOT `int64`. This is correct today, but it's implicit — if a future LanceDB version changes the default SQL `int` width to `int64`, the migration silently produces a type-mismatched column versus `CHUNKS_SCHEMA_V1`. `test_migration_adds_seven_columns_with_arxiv_defaults` (line 1029) only asserts `len(tbl.schema.names) == 21` and "column X in schema.names" — it does NOT assert per-column types match `CHUNKS_SCHEMA_V1`.
- **Why it matters:** Defends against silent LanceDB-side regressions and self-documents the load-bearing nature of `int` → `int32`. The fix is two assertions, no code change. Lower-priority because the symptom would surface as a write failure on the next `merge_insert` (Arrow schema mismatch), not as silent corruption — but a write-time failure halfway through a 200K-paper ingest is bad recovery surface.
- **Proposed fix:** Either (a) change `cast(NULL as int)` to `cast(NULL as int32)` (more explicit, matches CHUNKS_SCHEMA_V1's pa.int32() directly), AND test it; or (b) add to `test_migration_adds_seven_columns_with_arxiv_defaults`:
  ```python
  for col_name in ["source_kind", "license", "chapter", "page_start",
                    "page_end", "textbook_slug", "parser_used"]:
      assert tbl2.schema.field(col_name).type == CHUNKS_SCHEMA_V1.field(col_name).type, (
          f"migration type mismatch for {col_name}"
      )
  ```
  Prefer (a) + (b) — both are 1-2 LOC.
- **Regression guard:** Assertion above plus `test_migration_int_columns_are_int32_not_int64`.

### F7 — `_build_arrow_table` accepts `source_kind=None` if a future caller bypasses the dataclass default

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/store.py:422-427
- **What:** The enum guard is `if chunk.source_kind not in _ALLOWED_SOURCE_KINDS: raise`. `None not in _ALLOWED_SOURCE_KINDS` is True, so the guard DOES reject None (correctly). HOWEVER the error message says "is not in the allowed set {'arxiv', 'textbook'}" — for a None input that error is correct but unhelpful (the operator sees `source_kind=None` and is told "use 'arxiv' or 'textbook'" — they have to mentally translate "your ChunkRecord forgot to set the field" into the fix). LOW severity because the error IS raised, just with a slightly cryptic message.
- **Why it matters:** Cosmetic; rectifier may skip this unless it's a one-line fix. The right error message would mention "the ChunkRecord default is 'arxiv'; populate `source_kind` explicitly or rely on the default."
- **Proposed fix:** Slight wording change to include `None` as a special case: `if chunk.source_kind is None: raise ValueError(f"chunk {chunk.chunk_id} has source_kind=None; the ChunkRecord default is 'arxiv' — populate explicitly or rely on the default")`. ~5 LOC.
- **Regression guard:** None required for LOW.

### F8 — `_make_textbook_chunk` test helper hardcodes `chunker_version=CHUNKER_VERSION` but the textbook chunker (e3) hasn't shipped — fixture may drift

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/test_store.py:803-836
- **What:** The textbook chunker chunks are tested via `_make_textbook_chunk(...)` using `chunker_version=CHUNKER_VERSION` ("v1.1"). The textbook chunker proper lands in e3 with its own version stamp — at that point, real textbook chunks may carry a different version string (e.g. "v1.1+textbook" or "tb-v1"), and the test fixture will diverge from production. The test still passes m2's contract (store doesn't validate chunker_version against the chunk source_kind), but the implicit assumption "textbook chunks share the arXiv chunker version" is undocumented.
- **Why it matters:** LOW — m2 is a storage milestone, not a chunker milestone. The test is correct for what m2 ships. The risk is future drift; the right fix is a comment, not a code change.
- **Proposed fix:** Add a comment above `_make_textbook_chunk` noting that the textbook chunker proper (e3) may use a different `chunker_version` and this helper will need updating when e3 lands. ~2 LOC of comment.
- **Regression guard:** None.

## What was done well

- The 21-column schema migration is functionally correct and idempotent across retries (verified by direct reproduction of partial-failure scenarios).
- The implementer correctly identified the brief's "extend the parser_used enum" as a hidden 7th-column requirement and added it cleanly. The deviation is documented in the implementation summary.
- AC-to-test mapping is exhaustive: each of the 5 ACs maps to a specific test class in `test_store.py`, and the synthesis FM-1 (migration mechanism) and FM-6 (NULL-vs-default ambiguity) get dedicated coverage.
- BP1 cache discipline was correctly preserved — `EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_BP1_SHA256` were untouched, and the doc explicitly defers the cache invalidation to m3. 42 pin tests still pass.
- The `_ALLOWED_SOURCE_KINDS` enum guard mirrors the existing `_ALLOWED_KINDS` pattern, keeping the codebase internally consistent.
- The SQL backfill choice (token-string instead of NULL for `source_kind`/`license`) is well-justified by the FM-6 mitigation — preserves `WHERE license = 'arxiv-license'` filter semantics on legacy rows.
- The doc updates land in the right places (`.claude/docs/snippet-contract.md` section (f) + `.claude/notes/05-storage-and-indexing.md` inline update) per the repo's strict doc-placement rule.
- The implementation summary honestly documents the unusual provenance (schema constants in 26c04fa, writer in decc597) rather than hiding it.
- `_migrate_chunks_schema_if_needed` walks `CHUNKS_SCHEMA_V1` in declared order (line 340) so post-migration column ordering matches the canonical schema — defensive against potential snapshot-test drift across hosts.
- The unhandled-column trip-wire (line 324-331) is exactly the right shape for catching a future m3 mistake — fail-loud rather than silent-skip.

## Recommended rectification order

1. **F1 (HIGH)** — retract the stale "migration NOT implemented" docstring in `ingest/schema.py`. One-line fix in critical-path doc. No test surface impact.
2. **F2 (HIGH)** — fix the nullability skew between fresh and migrated tables. Either explicit `alter_columns` after migration or a different SQL form. Couple with the F3 test additions so the fix's correctness is provable.
3. **F3 (MEDIUM)** — add merge_insert-on-migrated-table tests. Naturally pairs with F2's verification.
4. **F4 (MEDIUM)** — add `_ALLOWED_PARSER_USED` enum guard. Symmetric, cheap, closes the brief's "extend the parser_used enum" expectation.
5. **F6 (MEDIUM)** — assert column types in migration tests. 2-line addition.
6. **F5 (MEDIUM)** — extend `test_migration_unhandled_column_raises` with a positive-branch sibling. ~15 LOC.
7. **F7, F8 (LOW)** — defer or fix inline if cheap (≤ 3 LOC each).

## Rectification status

- F1 — fixed in `23e9ceb` (ingest/schema.py module docstring rewritten to reflect the shipped migration). Regression guard: docstring text now accurately documents `_migrate_chunks_schema_if_needed`, the SQL backfill semantics, MVCC-version-per-add_columns recovery, and idempotency.
- F2 — fixed in `23e9ceb` (ingest/store.py:_migrate_chunks_schema_if_needed now calls `alter_columns({path, nullable: True})` after each `add_columns` so post-migration nullability matches the canonical schema). Regression guard: `tests/test_store.py::TestSchemaMigrationGuard::test_post_migration_nullability_matches_canonical`. Direct reproduction script confirmed source_kind / license were nullable=False pre-fix and nullable=True post-fix.
- F3 — fixed in `23e9ceb`. Tests: `TestSchemaMigrationGuard::test_merge_insert_update_on_migrated_table` and `test_textbook_chunk_into_migrated_table` exercise the upsert path on migrated tables for arXiv updates and new textbook writes respectively.
- F4 — fixed in `23e9ceb` (added `_ALLOWED_PARSER_USED` enum guard in `_build_arrow_table`). Regression guards: `TestParserUsedEnumGuard` — 3 tests (invalid raises, None accepted, each valid value accepted).
- F5 — fixed in `23e9ceb` (added `test_migration_extensible_with_new_default` positive-branch sibling). Documented patch-surface brittleness in the negative-branch test's docstring.
- F6 — fixed in `23e9ceb` (added per-column TYPE assertions to `test_migration_adds_seven_columns_with_arxiv_defaults`). Defends against future LanceDB SQL int-width drift.
- F7 — deferred (LOW; cosmetic error-message wording for the None case; tracked for hygiene pass).
- F8 — deferred (LOW; comment about future textbook-chunker version drift; e3 will update the helper when it lands).

**Summary:** 6 fixed (F1, F2, F3, F4, F5, F6), 0 invalidated, 2 deferred (F7, F8). Adversary invalidation rate 0/2 HIGH = 0% (well under 40% threshold; the adversary was accurate on both load-bearing findings).
