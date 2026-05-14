# Critique — E10_S01

**Critic:** adversary
**Generated:** 2026-05-14T16:10:52Z
**Commit range:** 49dbd29..88b9dcc
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES driven by **F1**: an empty-string `term`
  argument bypasses the 100-entry pagination contract and dumps the
  paper's entire definitions table in a single response — a directly
  reachable correctness + DoS-ish surface on a common foot-gun input.
- 1 HIGH, 3 MEDIUM, 2 LOW. Zero CRITICAL — the cache hashes re-pin
  cleanly, the regex genuinely rejects single quotes, and idempotency
  holds in the single-writer happy path.
- Highest-risk file: `server/handlers/definitions.py:104` (the
  `term is not None` gate accepts `""` and short-circuits past
  pagination).
- Cross-axis pattern: at least two issues (F1, F3) trace back to a
  "term mode is unbounded" assumption — the handler treats the term
  branch as if it's always at most a handful of rows, but the prefix-
  match step has no row cap.
- Cache discipline is clean: `TOOL_SCHEMA_VERSION` bumped, schema hash
  re-pinned, BP1 re-pinned, schemas/search_papers_result.json bumped
  in lockstep; tests pass.
- Math fidelity is mostly clean — the regex correctly handles `@` in
  internal command names, `\let` with both char-literal and macro
  targets, nested braces, escaped `\{` / `\}`, and real `\\`-in-body
  parses correctly (manually exercised).
- "What was done well" section (below) lists 8 substantive wins —
  this is not an adversarial-for-its-own-sake critique.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Empty-string `term` returns entire paper, bypassing pagination

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/handlers/definitions.py:104
- **What:** The handler's mode discriminator is
  `if term is not None:` (line 104). An MCP caller passing
  `term=""` therefore enters the **term-lookup branch**, not the
  paginated full-table branch. In `_term_lookup` the empty needle
  flows through to step 3, where
  `r["symbol_raw"].casefold().startswith("")` is `True` for every
  row, so every row is returned with `next_cursor=None` and no
  page cap. I reproduced this by hand:
  `needle = ''.casefold(); [r for r in rows if r['symbol_raw']
  .casefold().startswith(needle)]` returns the full row set.
- **Why it matters:** Breaks the brief's load-bearing
  "paginated at 100 entries per page" contract on a common foot-gun
  input (every JSON client that sends an empty string instead of
  omitting the field hits this). For a pathological hep-th preamble
  with thousands of `\newcommand`s, the single response can also
  blow past the 256 KB inline cap (the handler does not call
  `enforce_byte_cap`; see F4). The exact-match and `symbol_raw`-
  exact steps return `[]` for an empty term, so the prefix step is
  the only one that fires — and it has no cap.
- **Proposed fix:** Treat falsy `term` as "no term". Add an early
  guard immediately after the `is_valid_paper_id` check:
  ```python
  if term is not None and not term:
      term = None
  ```
  (or equivalently make the mode test `if term:` instead of
  `if term is not None:`). Add a regression test:
  `term=""` must return paginated full-table behavior with
  `next_cursor` populated when total > 100. Document in the tool
  description that `term=""` is treated as omitted.
- **Regression guard:**
  `tests/test_definitions_index.py::TestHandlerTermLookup::
  test_empty_string_term_is_treated_as_unfiltered` (new) — stage
  150 macros, call with `term=""`, assert `len(definitions)==100`
  and `next_cursor is not None`.

### F2 — Race between concurrent indexer calls for the same paper

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/index_definitions.py:369-382
- **What:** `index_definitions_for_paper` does
  `tbl.delete(safe_filter)` (line 371) then `tbl.add(arrow_table)`
  (line 382) with no per-paper lock. Two concurrent runs for the
  same `paper_id` can interleave as:
  `A.delete → B.delete → A.add → B.add`, leaving DUPLICATE rows
  (the handler's full-table mode would then return the same
  symbol twice with different `definition_id`s and the symbol-
  sorted page is non-deterministic). Worse:
  `A.add → B.delete → B.add` discards A's writes entirely. The
  implementation summary calls the operation "atomic per-paper"
  (lines 134-135 of the summary) but the delete/add pair is two
  separate LanceDB MVCC commits.
- **Why it matters:** The brief's idempotency clause "re-running for
  a paper that already has entries replaces them" is only true in
  the single-writer happy path. A future ingest driver that
  shells out to a worker pool (E11_S01) per the roadmap will
  almost certainly run concurrent per-paper indexers. The
  test_idempotent_per_paper_replace test runs sequentially and
  does not catch this.
- **Proposed fix:** Either (a) document the single-writer
  contract explicitly in the module docstring AND in the
  implementation summary's "idempotency" claim, OR (b) wrap the
  delete+add pair in a per-paper file-system lock (a tiny
  `fcntl.flock` on `lancedb_path/.locks/<paper_id>.lock`). Option
  (a) is cheap for v1 since the E11 driver is not built yet; the
  rectifier should pick (a) and add a `# CONCURRENCY:` line to
  the docstring.
- **Regression guard:** Module docstring sentence
  "Single-writer-per-paper contract: callers must serialize
  concurrent index_definitions_for_paper(paper_id=X) calls."

### F3 — Broad `except Exception` masks real LanceDB delete failures

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/index_definitions.py:372-378
- **What:** The `try: tbl.delete(safe_filter)` block catches every
  `Exception` (line 372) and logs at DEBUG level with the comment
  "A first-write into an empty table can fail on some LanceDB
  versions with `no records to delete`; treat as benign." But this
  swallows every other class of error too — schema-mismatch
  errors, filesystem permission errors, table-corruption errors.
  The subsequent `tbl.add` call may then crash with a less-helpful
  error or silently succeed (writing the new rows on top of the
  un-deleted prior rows, producing duplicates).
- **Why it matters:** The original problem the broad-except was
  meant to handle ("no records to delete") is a single, well-
  defined error string in LanceDB; catching it specifically would
  let real errors surface. Today, a filesystem-permission failure
  on the LanceDB directory would log "delete predicate raised on
  <paper_id> (likely empty table)" at DEBUG and then proceed to
  add rows the writer thinks it inserted but didn't.
- **Proposed fix:** Narrow the except to the specific LanceDB
  exception class(es) actually raised by an empty-table delete
  (probe with a quick test). If LanceDB raises a generic
  `RuntimeError`, match on `"no records to delete"` in the message.
  Fall back to re-raising on any other error.
- **Regression guard:**
  `tests/test_definitions_index.py::TestIndexer::
  test_delete_failure_surfaces_for_non_benign_errors` (new) —
  monkeypatch `tbl.delete` to raise `PermissionError`, assert the
  indexer re-raises rather than swallowing.

### F4 — Handler does not enforce the 256 KB result byte cap

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/handlers/definitions.py:126-135
- **What:** Per `server/tools.py:34-36`, "tools enforce the 256 KB
  cap themselves via `enforce_byte_cap`." The new
  `handle_get_definitions` returns the envelope directly without
  calling `enforce_byte_cap`. A page of 100 macros with verbose
  expansions (a few hundred bytes each) is comfortably under cap,
  but a single page of pathologically long
  `\DeclareMathOperator{\X}{<huge body>}` entries could exceed
  it. More immediately relevant: when F1 is exploited (or before
  it is fixed), an unbounded `term=""` response is unbounded by
  count AND by size.
- **Why it matters:** The cap is the contract that prevents a
  single tool response from blowing past the MCP body-size
  middleware exemption. Even after F1 is fixed, an operator
  raising `PAGE_SIZE` would have no guardrail.
- **Proposed fix:** Wrap the final `envelope({...})` returns in
  `structured, blocks = enforce_byte_cap(envelope({...}))` and
  return the structured payload. For this handler there is no
  natural `chunk_id` for the resource_link fallback; pass
  `chunk_id=None` and accept that the truncation path will only
  shrink the body. Alternative: leave as-is and add a one-line
  comment documenting that the per-page cap (100 × ~few-hundred
  bytes) is well under 256 KB by construction, and that any
  PAGE_SIZE bump must re-evaluate.
- **Regression guard:**
  `tests/test_definitions_index.py::TestHandlerFullTableMode::
  test_response_under_byte_cap` — assert
  `len(json.dumps(result).encode()) < config.result_byte_cap`
  for the 250-macro fixture.

### F5 — `table_names()` is deprecated in LanceDB

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/index_definitions.py:310
- **What:** Running `tests/test_definitions_index.py` emits 60
  `DeprecationWarning: table_names() is deprecated, use
  list_tables() instead` warnings. The code uses
  `if DEFINITIONS_TABLE_NAME in db.table_names():`. A future
  LanceDB upgrade will remove this method.
- **Why it matters:** Future LanceDB pin bump will break the
  indexer with a less-than-obvious error.
- **Proposed fix:** Swap to `list_tables()`. The same change is
  not made in `server/resources.py:432`, which also uses
  `db_conn.table_names()` — fix both call sites in the same
  patch.
- **Regression guard:** None — ruff would catch a re-introduction
  if a project lint rule for deprecated-method-names existed,
  but absent that, the deprecation warning in the test run is
  the regression signal.

### F6 — AC4 test fails open if LanceDB ever stops emitting `*_idx` names

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/test_definitions_index.py:330-334
- **What:** `test_scalar_indexes_created` asserts:
  ```python
  index_names = {ix["name"] for ix in tbl.list_indices()}
  assert "paper_id_idx" in index_names or "paper_id" in index_names
  assert "symbol_raw_idx" in index_names or "symbol_raw" in index_names
  ```
  The `or` clause hedges against a LanceDB rename. If a future
  version returns a third name (e.g. `paper_id_btree_idx`) the
  test fails open. Worse: if `list_indices()` returns an empty
  list AND the LanceDB API returns a different key shape (not
  `{"name": ...}` but `{"column": ...}`), the set comprehension
  silently yields `set()` and the assertion crashes with KeyError
  — but a `column`-keyed return on a populated index list would
  also fail loudly. Acceptable, but the test should also assert
  the index COLUMN, not just its name.
- **Why it matters:** AC4 is the brief's "B-tree index on
  (paper_id, symbol) is present after ingestion" — the test is
  the only line of defense against the indexer silently dropping
  the `create_scalar_index` calls (e.g. if the broad-except in
  `_ensure_scalar_indexes` swallowed every failure).
- **Proposed fix:** Tighten the assertion to also check the
  `columns` field on each index entry (LanceDB ≥ 0.6 returns
  `{"name", "columns", ...}`). Assert that at least one index
  has `"paper_id" in columns` and at least one has
  `"symbol_raw" in columns`.
- **Regression guard:** The strengthened assertion itself is the
  guard.

## What was done well

- BP1 cache discipline closed end-to-end:
  `TOOL_SCHEMA_VERSION` bumped from 1 → 2,
  `EXPECTED_TOOL_SCHEMA_SHA256` re-pinned via the official
  `pytest --update-tool-schema-hash` flag, `EXPECTED_BP1_SHA256`
  re-pinned, `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` re-pinned,
  and `server/schemas/search_papers_result.json::version` bumped
  to 2. All five hash anchors landed; tests pass.
- The decision to keep `symbol == symbol_raw` at v1 (synthesis
  D3) is correctly documented in the module docstring and the
  implementation summary's "deviations from the brief" section
  — the brief's example was load-bearing-wrong (the LEFT side of
  `\newcommand` is the NAME, not the expansion).
- `is_valid_paper_id` is invoked at the handler boundary BEFORE
  the string is interpolated into a LanceDB filter; I exercised
  the regex against five injection variants
  (`1234.56789' OR '1'='1`, `2401.01234' --`, etc.) and all
  rejected. Single-quote bypass is impossible by construction.
- `_decode_cursor` is appropriately tolerant: empty string → 0,
  garbage → 0, b64-of-non-int → 0, negative → 0 (clamped). No
  4xx for stale cursors per the design note's intent.
- `parse_macro_line` correctly handles `@` in internal command
  names, `\let` with both `\target` and char-literal targets,
  nested-brace bodies, escaped `\{` / `\}`, and real `\\` in
  bodies (e.g. `\newcommand{\nl}{\\}` with TWO literal
  backslashes parses to `expansion="\\\\"`).
- The dedup-by-`symbol_raw` ordered-dict in
  `build_definitions_for_paper` correctly produces last-seen-wins
  semantics for `\renewcommand` even though the preamble extractor
  sorts alphabetically (the alphabetic-vs-source-order caveat is
  explicitly documented in the implementation summary).
- The empty-preamble-paper case is covered at three layers:
  builder, indexer, and handler — all return empty results
  without errors.
- The `index_status="absent"` vs `"ok"` distinction lets a caller
  distinguish "no index built yet" from "indexed but no matches"
  — non-trivial design discipline.
- The 250-macro pagination test exercises a 3-page traversal end-
  to-end (page1 → page2 → page3) and asserts the final page's
  `next_cursor is None`. Good coverage for a non-trivial path.

## Recommended rectification order

1. **F1** — empty-string `term` bypass. Highest leverage:
   single-line fix in the handler, single regression test, closes
   the HIGH-severity DoS-adjacent surface.
2. **F4** — byte-cap enforcement. Cheap to add if rectifier
   chooses code path (wrap the three `envelope()` returns) or
   cheaper still to document the constraint. Recommend documenting
   for v1.
3. **F3** — narrow the broad-except. Cheap, surfaces real errors,
   prevents silent data corruption.
4. **F2** — concurrency contract. Document the single-writer
   contract in the module docstring; full locking deferred to E11.
5. **F5** — `table_names()` → `list_tables()`. Two-call-site fix;
   batch with any other deprecated-API cleanups.
6. **F6** — tighten AC4 test assertion. Cheapest of the bunch but
   lowest impact; rectifier may defer.

## Rectification status (Phase 4)

Re-verify step ran for all 6 findings. None were invalidated; the
cited file:line regions matched the critique's "what" claim in every
case.

- **F1 (HIGH) — fixed.** `server/handlers/definitions.py` —
  empty/whitespace-only `term` now collapses to `None` at the
  boundary BEFORE the mode discriminator. Regression test
  `TestHandlerTermLookup::test_empty_string_term_falls_through_to_full_table`
  exercises a 150-macro corpus and asserts paginated response. A
  second regression
  `test_whitespace_only_term_falls_through_to_full_table` covers the
  whitespace edge case.
- **F2 (MEDIUM) — fixed (doc-only).** Module docstring of
  `ingest/index_definitions.py` now carries a **CONCURRENCY:** block
  declaring the single-writer-per-paper contract and pointing at E11
  as the place where a real lock will land. Different papers may
  still run in parallel without coordination.
- **F3 (MEDIUM) — fixed.** `ingest/index_definitions.py`
  `index_definitions_for_paper` — replaced the broad `except
  Exception` with a precondition check via
  `_table_has_any_rows_for_paper`. The delete is invoked only when
  there is something to delete; any genuine LanceDB error now
  propagates. Regression test
  `TestIndexer::test_delete_failure_surfaces_not_swallowed`
  monkeypatches `tbl.delete` to raise `PermissionError` and asserts
  the indexer re-raises.
- **F4 (MEDIUM) — fixed.** `server/handlers/definitions.py` — all
  three `envelope({...})` return sites are now wrapped in
  `enforce_byte_cap`. A new `_cap` helper centralizes the invocation
  and discards the unused `content_blocks` return. No separate
  regression test added: the byte-cap helper is already exercised in
  `tests/test_tools_all.py::TestByteCapEnforcement` and the
  pagination test exercises the wrapped path with the 250-macro
  fixture.
- **F5 (LOW) — fixed.** Both `table_names()` call sites
  (`ingest/index_definitions.py` and `server/resources.py`) now use
  a `try: open_table → except ValueError/FileNotFoundError` pattern
  instead. This sidesteps both the deprecation warning AND the
  paginated-wrapper return shape of `list_tables()` on the pinned
  LanceDB version — an unexpected bug surfaced during rectification.
  The original critique suggested swapping to `list_tables()`
  directly, but the LanceDB 0.6 release returns a paginated object
  that does NOT support `in` membership.
- **F6 (LOW) — fixed.**
  `tests/test_definitions_index.py::TestIndexer::test_scalar_indexes_created`
  now asserts the indexed COLUMNS (via the `columns` attribute on
  the Index dataclass, with a fallback for older releases that
  surface only `name`). The assertion binds to the load-bearing
  invariant rather than to a name suffix.

**Invalidation rate:** 0 / 6 findings invalidated on re-verify (0%).
The adversary critic was well-calibrated.

**Test count delta after rectify:** 1348 passing (+3 from
post-implement 1345; net +37 vs. baseline 1311). 4 skipped, 0 failed,
ruff clean.
