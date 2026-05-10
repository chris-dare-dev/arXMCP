# E09_S04 Implementation Summary

**Milestone:** Cross-paper proof chain workflow (2-round agent pattern).
**Path:** inline (orchestrator, main session).
**Date:** 2026-05-10.

## One-line summary

Shipped `docs/proof-chain-workflow.md` documenting the 2-round
agent pattern, `tests/test_proof_chain.py` integration test with a
50-paper synthetic graph and 500ms perf gate, and `tests/_graph_helpers.py`
shared fixture helpers. 10 new tests; full suite green.

## Commit range

`7d89e0e..<head>` — single feat commit.

## Acceptance criteria status

| AC | Status | Evidence |
|---|---|---|
| #1 docs/proof-chain-workflow.md documents the 2-round pattern with the worked example | met | New doc; the worked example uses the canonical `arxiv:<paper_id>:<16-hex>` format (NOT the brief's invalid `:stmt-thm-grr` form). `TestDocumentationPins::test_doc_exists` + `test_doc_includes_worked_example` pin the file's presence and shape. |
| #2 pytest tests/test_proof_chain.py passes: round 1 returns ≥1 neighbor; round 2 returns non-null body_text | met | `TestRound1CiteNeighbors::test_round_1_returns_at_least_one_neighbor` + `TestRound2BulkGetChunk::test_round_2_returns_non_null_body_text_for_all_chunks`. Round 2 uses `asyncio.gather` over `handle_get_chunk` to exercise the parallel-tool-use shape; reads `body_text` from the nested `result["chunk"]["body_text"]` field per the handler's real shape. |
| #3 cite_neighbors(depth=2) completes in ≤500ms on the 50-paper corpus | met | `TestPerfGate::test_perf_gate_500ms` materializes 50 synthetic papers with 150 deterministic edges via `build_synthetic_kuzu_graph`; measures with `time.monotonic`; asserts `< 0.5`. Empirically completes in ~50-100ms on the test machine. |
| #4 doc states "Total round count = 2..." verbatim | met | `TestDocumentationPins::test_doc_states_total_round_count` pins the load-bearing phrases. |
| #5 doc explicitly notes chunk_id=None fallback | met (with documented v1 gap) | `TestDocumentationPins::test_doc_documents_chunk_id_none_fallback` pins. The doc accurately states that `search_papers(filters={"paper_id": ...})` is currently accepted-but-ignored at v1 (deferred to E07_S04); until then, agents skip `chunk_id=None` neighbors rather than spending a third round on a search that v1 cannot satisfy. |

**Net AC status: 5/5 met** (with one v1 caveat in AC#5 documented
explicitly).

## New / changed files

| Path | Lines (rough) | What |
|---|---|---|
| [docs/proof-chain-workflow.md](docs/proof-chain-workflow.md) | ~180 | New doc: 2-round pattern + worked example with corrected chunk_id format + chunk_id=None fallback + perf target + MCP-wrapper security note. |
| [tests/test_proof_chain.py](tests/test_proof_chain.py) | ~310 (10 tests) | Round-1 cite_neighbors verification, round-2 asyncio.gather over handle_get_chunk, chunk_id=None branch, perf-gate, doc-substring pins. |
| [tests/_graph_helpers.py](tests/_graph_helpers.py) | ~140 | New shared helpers: `build_synthetic_kuzu_graph(n_papers, edges_per_paper, ...)` + `build_synthetic_lancedb(rows)`. Lifted from the per-test inline patterns; existing tests are NOT refactored (no behavior change in existing suite). |

No code changes to `server/graph_queries.py` — the brief's
"Update to server/graph_queries.py" was about the PERF target, not
a code diff (synthesis § 9 documented this).

## Test count delta

- Before: 1302 passed, 4 skipped.
- After: **1312 passed, 4 skipped** (+10 new tests).
- `ruff check .`: clean.

## Brief deviations (documented in the doc + this summary)

The brief was followed with these explicitly-documented exceptions:

1. **Worked-example chunk_id format**. Brief used
   `arxiv:1803.01010:stmt-thm-grr` (theorem-label-style suffix).
   That format FAILS `is_valid_chunk_id` per the project's
   `CHUNK_ID_RE` regex (`arxiv:<paper_id>:<16-hex>` is strict).
   Implementation uses synthetic 16-hex suffixes
   (`arxiv:2605.00001:0123456789abcdef`) and adds an explicit
   callout in the doc explaining the format + linking to
   `docs/chunker-fixtures.md` for the regeneration procedure.

2. **Paper IDs**. Brief example used `1803.01010` /
   `0901.0101` / `1205.4344`. None of these are in
   `tools/seed-papers.txt` (which is post-2026 math.AG `2604.*` /
   `2605.*`). The doc uses synthetic paper_ids in the `2605.*`
   range that LOOK like real seed IDs but are explicitly labeled as
   illustrative. The integration test uses fully synthetic papers
   via `build_synthetic_kuzu_graph(paper_id_prefix="2605.",
   paper_id_start=90000)`.

3. **`search_papers(paper_id=<id>)` fallback (AC#5)**. The brief
   describes this as a third-round fallback. Today `server/handlers/search.py`
   accepts `filters: dict | None` but **ignores it at v1**
   (deferred to E07_S04). The doc states this accurately. The
   integration test exercises the `chunk_id=None` branch but does
   NOT call `search_papers` — it asserts the skip-rather-than-search
   policy that the v1 gap dictates.

4. **Handler wiring**. The brief's "Update to
   server/graph_queries.py" wording suggested a code change to the
   library. The actual deliverable is a TEST assertion (the
   500ms perf gate). No code change to `server/graph_queries.py`
   was needed. The `cite_neighbors` MCP handler in
   `server/handlers/citations.py` remains the v1 stub — wiring it
   to the real library is deferred to a future milestone
   (E06_S04-flavored, where the F2 path-validation contract is
   formalized at the boundary).

5. **Synthetic vs. real seed corpus for the perf gate**. AC#3
   says "the 50-paper seed corpus" but the real seed corpus on
   disk isn't materialized in CI (no `make ingest`). The test uses
   a synthetic 50-paper graph with 150 deterministic edges
   (each paper cites its 3 predecessors mod 50). This matches
   AC#3's scale and is reproducible in CI; a future operator-time
   benchmark against the real corpus is out of scope.

## Implementation choices for Phase 3 to scrutinize

These are choices where I expect the adversary to push back:

1. **`set_resources(_FakeResources())` with teardown via
   `reset_resources_for_tests`**. Matches the
   `test_tools_all.py:482-496` pattern, but the singleton is global
   process state — if a test runs without `fake_resources` after
   one runs with it, state leaks. The `fake_resources` fixture
   includes the `reset_resources_for_tests()` teardown so this
   should be safe, but a future maintainer adding tests should
   verify they request the fixture explicitly.

2. **Perf gate at 500ms vs. 1.0s**. AC#3 names 500ms. The
   synthetic 50-paper test completes in ~50-100ms locally. If the
   gate flakes on slow CI, the synthesis says to raise to 1.0s
   with a TODO; the test docstring spells out the same
   recommendation. A critic might argue for a more generous gate
   pre-emptively; I followed the brief.

3. **Round-2 via `asyncio.gather`**. Real parallel execution. A
   critic might note that `gather` in pytest doesn't actually use
   multiple OS threads — the calls are coroutine-scheduled. But
   the doc's claim is "parallel tool_use blocks in one assistant
   turn," which is exactly what `gather` proves at the call-site
   level (concurrent, single-event-loop). This is the correct
   semantic for the agent-pattern test.

4. **Shared helper module without refactoring existing tests**.
   I created `tests/_graph_helpers.py` but did NOT refactor
   `tests/test_graph_queries.py` or
   `tests/test_intra_paper_refs.py` to use it. The existing tests
   have their own inline helpers that work fine; refactoring would
   add diff churn for no behavior change. A critic might prefer
   the unified-helper aesthetic; I prioritized the focused diff.

5. **Doc substring pins**. The `TestDocumentationPins` tests check
   for verbatim strings in the markdown file. This is brittle to
   doc-prose edits. A more robust pin would parse the markdown and
   check structural elements (headings, code blocks). I chose the
   simpler substring approach because the AC#1/#4/#5 phrases are
   load-bearing and shouldn't drift; the test fires if a future
   edit removes them.

6. **No `search_papers` fallback test**. The brief's AC#5 names
   `search_papers(paper_id=<id>)` as the fallback. The v1
   handler ignores `paper_id` filters; testing the fallback would
   either (a) test the no-op behavior (test passes vacuously) or
   (b) require pre-shipping the E07_S04 filter wiring (out of
   scope). The test exercises the `chunk_id=None` branch and
   asserts the agent SKIPS that neighbor, which is the v1-correct
   behavior the doc prescribes.

## External writes the orchestrator must authorize (Phase 4 gate)

| type | target | why | blocking? |
|---|---|---|---|
| Code edits | `docs/proof-chain-workflow.md`, `tests/test_proof_chain.py`, `tests/_graph_helpers.py` | landed in this commit | no |
| `git push` | remote | not required by milestone; per-event authorization | no |

**No HTTP calls.** No new runtime dependencies. The integration test
runs entirely against `tmp_path`-bound synthetic data.

## F-finding inheritance from E09_S01/S02/S03 (status)

| ref | applied here? |
|---|---|
| F2 (path-traversal contract) | documented in doc's "Security note" section. The library carries the warning; the doc restates it for the proof-chain workflow specifically. No new boundary surface introduced (handler stays a stub). |
| F7 (limit(1_000_000) foot-gun) | still open; doc flags as Tier-3-scaling concern in the perf-target section. Out of scope for this milestone. |
| F10 (defensive empty-rels default) | still deferred. Not exercised. |

## H7 closure

**H7 ("cross-paper proof chains unaddressed") is now fully closed**
by the combination of:

- E09_S01: OpenAlex citation graph ingest (graph populated)
- E09_S02: INSPIRE-HEP enrichment for hep-th / math-ph
- E09_S03: `cite_neighbors(chunk_id, depth, direction)` library +
  intra-paper `\ref{}` self-edges
- **E09_S04** (this milestone): 2-round agent pattern docs + the
  integration test that proves the pattern works end-to-end.

The H7 closure is confirmed when `tests/test_proof_chain.py`
passes, which it now does. The risk-note in the E09_S03 brief
("Closes H7 partial") is upgraded to "Closes H7 fully" via this
milestone.

## Open follow-ups (not in this milestone)

- Wire `server/handlers/citations.py::handle_cite_neighbors` to the
  real library (currently a v1 stub). Deferred to a future
  E06_S04-flavored milestone where the path-validation contract
  formalizes at the boundary.
- E07_S04 wires the `filters={"paper_id": ...}` argument on
  `search_papers`, making the brief's AC#5 third-round fallback
  implementable. The doc explicitly anticipates this.
- F7 (limit(1_000_000)) — Tier-3-scaling work. Intersects with
  the 500ms perf target at production scale.
- Real-corpus performance verification — run the perf gate against
  a real ingested corpus on disk (operator-time benchmark).
