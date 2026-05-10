# Critique — E09_S04

**Critic:** adversary
**Generated:** 2026-05-10T00:00:00Z
**Commit range:** 7d89e0e..b29fcf2
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES: tests pass (10/10) and the doc lands the
  AC-pinned phrases, but the 500 ms perf gate is calibrated against a
  150-edge synthetic graph that is structurally cheaper than the
  "50-paper seed corpus" AC#3 names, so the gate may pass for the
  wrong reason at Tier-3 scale.
- Counts: 0 CRITICAL, 1 HIGH, 5 MEDIUM, 3 LOW.
- Highest-risk file: `tests/test_proof_chain.py:338` — perf-gate
  assertion. The brief's "real corpus" measurement-of-record is being
  inferred from a synthetic stand-in without a measured gap analysis.
- Cross-axis note: every load-bearing AC#5 commitment in the doc is
  hedged with "deferred to E07_S04," meaning H7 closure as advertised
  in `implementation-summary.md:170-172` is contingent on
  out-of-scope work — the doc's "fully closed" framing is leaning
  on a future milestone.
- Axis 1 (cache byte-stability): N/A — only docs + tests changed.
- Axis 2 (math fidelity): N/A — no math-content code.
- Axis 3 (security): doc faithfully restates F2 contract, but the
  `_FakeResources` global-singleton pattern in
  `tests/test_proof_chain.py:130-140` carries the textbook leak risk
  flagged below (F4).
- Axis 6 (tier sequencing / imports): imports are clean; the
  `tests/_graph_helpers.py` reuse leaves existing tests untouched as
  advertised.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Perf gate measures a sparse synthetic graph, not the seed-corpus scale AC#3 names

- **Severity:** HIGH
- **Source:** adversary
- **File:** tests/test_proof_chain.py:338
- **What:** The 500 ms gate is asserted against
  `build_synthetic_kuzu_graph(n_papers=50, edges_per_paper=3)` which
  yields exactly 150 edges (and only 3 outgoing per paper).
  AC#3's "50-paper SEED corpus" is the real ingested corpus
  (`tools/seed-papers.txt`) whose citation density per
  E09_S01/S02 OpenAlex+INSPIRE ingest is materially higher (often
  10–60 references per math.AG paper). The synthetic graph is
  3–20× sparser than what the gate is supposed to measure.
- **Why it matters:** AC#3 is a project guarantee for Tier-3 scale.
  A green gate here gives false confidence: if real-corpus depth=2
  BFS from a hub paper blows past 500 ms, this test won't catch it.
  The implementation summary
  (`.claude/notes/milestones/E09_S04/implementation-summary.md:89-95`)
  acknowledges the synthetic divergence but ships the gate anyway.
- **Proposed fix:** Either (a) raise `edges_per_paper` to a
  realistically dense value (e.g. 15–30) so the synthetic graph
  approximates seed-corpus density at depth=2, OR (b) add an
  env-gated `@pytest.mark.bench` variant that loads the real
  ingested Kùzu db when present (skipping in CI), keeping the
  synthetic test as a fast smoke gate. Document the divergence
  explicitly in `docs/proof-chain-workflow.md:159-164` rather than
  burying it in the test docstring.
- **Regression guard:** Add an assertion that the synthetic graph
  built by the test has ≥ N edges (where N is a documented
  representative density), so anyone bumping the synthetic params
  trips a guard rather than silently lowering the gate's signal.

### F2 — Doc-pin disjunction in `chunk_id=None` test is overly permissive

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_proof_chain.py:386
- **What:** `test_doc_documents_chunk_id_none_fallback` asserts
  `"third round" in text or "exhausts" in text or "deferred to
  E07_S04" in text`. The brief's AC#5 mandates that the doc state
  the fallback "counts as a third round and exhausts the budget."
  The disjunction lets the doc drift to a state where only
  `"deferred to E07_S04"` survives — that satisfies the test but
  silently drops AC#5's "third round" framing.
- **Why it matters:** Subtle AC erosion. The brief's exact wording is
  the load-bearing claim ("third round … exhausts the budget"); the
  test should pin the round-budget claim explicitly, not the
  deferral framing.
- **Proposed fix:** Tighten to require ALL of (a) some
  `chunk_id=None` phrasing, (b) the word `search_papers`, (c) a
  reference to the third round OR budget exhaustion specifically.
  Drop the `deferred to E07_S04` alternative — that phrase is about
  the v1 gap, not about the AC#5 invariant.
- **Regression guard:** Use the tightened assertion plus a single
  positive substring (`"third round"`) as a non-negotiable.

### F3 — `chunk_id=None` AC#7 test depends on a brittle implicit constant

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_proof_chain.py:238-268, tests/_graph_helpers.py:88-98
- **What:** `test_paper_missing_from_lancedb_returns_chunk_id_none`
  relies on the synthetic graph's edge construction wiring P_0 to
  cite P_{N-1}, P_{N-2}, P_{N-3} (modular wrap). This is a property
  of `EDGES_PER_PAPER = 3` AND the (i-k) mod n_papers loop. If a
  maintainer bumps `EDGES_PER_PAPER` higher (e.g. to densify the
  perf-gate graph for F1), P_0 still cites P_{N-1} — fine. But if a
  maintainer changes the edge construction order or drops the wrap,
  the test asserts `missing in by_pid` but the assertion's failure
  mode hides the structural change.
- **Why it matters:** Tests should not depend on implicit
  invariants of a helper function without explicitly asserting them.
- **Proposed fix:** Have `graph_corpus` explicitly construct the
  expected edge from `entry_paper_id` to `chunks_missing_paper`
  (either by configuring the helper to take an explicit edge list,
  or by asserting the wiring as a fixture-time invariant).
- **Regression guard:** Add a fixture assertion: `assert
  chunks_missing_paper in <papers cited by entry>` at
  `graph_corpus` setup time so a future structural change in the
  helper fails the fixture loudly, not the unrelated test.

### F4 — `fake_resources` fixture does not close LanceDB connection at teardown

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_proof_chain.py:109-140
- **What:** The fixture opens `lancedb.connect(...).open_table("chunks")`
  and stashes it on `_FakeResources().chunks_table`. The teardown
  block calls `reset_resources_for_tests()` (which clears the
  singleton) but never closes the lancedb handle. The Arrow buffers
  and file descriptors are only released when the GC reaps the
  `_FakeResources` instance; under pytest's per-test fixture scope
  this is usually fine, but a parallel test run or long suite can
  accumulate handles.
- **Why it matters:** Latent foot-gun. lancedb's `db.close()` /
  `table.close()` is the correct pattern for short-lived test
  connections; relying on GC ordering is a known source of
  Windows-CI "file in use" flakes (which arXMCP CI may not exercise
  today, but the synthesis advertises a Docker / cross-platform
  story).
- **Proposed fix:** Add an explicit `db.close()` (or `del db; del
  chunks_table`) in the `finally:` block after
  `reset_resources_for_tests()`.
- **Regression guard:** Not strictly needed — this is a resource
  hygiene fix. Optional: a fixture-finalizer assertion that no open
  lancedb handles remain at the singleton's clearance.

### F5 — "Update to server/graph_queries.py" deliverable interpreted as no-op

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** .claude/notes/milestones/E09_S04/implementation-summary.md:39-41
- **What:** The brief's deliverable list explicitly names
  "Update to server/graph_queries.py — verify cite_neighbors
  returns results fast enough for 2-round budget (target: ≤500ms
  for depth=2 on the 50-paper corpus)." The implementation summary
  reads this as "the perf target is a test assertion, not a code
  change" and ships no code change to graph_queries.py. The
  research synthesis (§ 9) reaches the same conclusion. But the
  brief's wording is ambiguous: a defensive reading expects at
  least a comment, a profiling hook, or a perf-target docstring
  callout on the `cite_neighbors` function pinning the 500ms
  contract at the library level.
- **Why it matters:** The library function carries no inline
  documentation of the 500ms expectation. A future maintainer
  refactoring `cite_neighbors` has no in-source signal that the
  performance is a contract — only the test pins it. Test-only
  performance contracts are fragile because they're invisible at
  read time.
- **Proposed fix:** Add a docstring section to
  `server/graph_queries.py::cite_neighbors` recording the 500ms
  target and linking to `docs/proof-chain-workflow.md` and the
  perf-gate test. Optionally add a one-line `logger.debug` timing
  hook to support operator-time investigation.
- **Regression guard:** No new test needed — the existing perf-gate
  test is the runtime guard; the docstring is the documentation
  guard.

### F6 — `asyncio.run(coro)` per test invocation may reset Kùzu native handles

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_proof_chain.py:143-144
- **What:** Each test uses `_run = asyncio.run`. Five tests in
  the file create independent event loops. `cite_neighbors` opens
  `kuzu.Database(...)` inside the coroutine and relies on `del db`
  to release. Combined with the per-test `tmp_path` fixture, each
  test materializes a fresh kuzu db from scratch — which is what's
  happening here (the fixture is function-scope, not session).
  This wastes test time and re-pays the `apply_schema` cost five
  times for what could be a session-scoped fixture.
- **Why it matters:** Test latency, not correctness. The 14.9s
  suite runtime is mostly fixture rebuild — fine for now but a
  guardrail concern as the suite grows.
- **Proposed fix:** Promote `graph_corpus` to `scope="session"` (or
  at least `scope="module"`) by parameterizing it on `tmp_path_factory`
  rather than `tmp_path`. Each test that uses it then shares the
  same on-disk kuzu db. Skip this if the orchestrator prefers the
  per-test isolation; document the choice in the test docstring.
- **Regression guard:** None required — pure perf cleanup.

### F7 — `body_text` perf test asserts trivially because handler does no parsing

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/test_proof_chain.py:223-230
- **What:** `test_round_2_returns_non_null_body_text_for_all_chunks`
  asserts `body["chunk"]["body_text"]` is truthy. The fixture sets
  `body_text="Statement of theorem for {paper_id}..."` which is
  always non-empty. `handle_get_chunk` returns the field directly
  without transformation. The test proves only that the LanceDB
  row's `body_text` column survives a round-trip through the
  handler — a useful smoke check but not a meaningful AC#2
  assertion about cross-paper proof-chain content.
- **Why it matters:** The test would pass even if the handler
  silently swapped `body_text` with a different column (e.g.
  returned `chunk_id` in place of `body_text`), as long as the
  swapped column is non-empty. A stronger assertion would
  substring-match the synthetic body content ("Statement of
  theorem for") to prove the handler actually surfaces the
  body_text field.
- **Proposed fix:** Tighten to `assert "Statement of theorem for"
  in body["chunk"]["body_text"]` so a field-swap regression
  surfaces.
- **Regression guard:** The tightened assertion itself.

### F8 — Doc substring pin `"3-round cap from E08"` is fragile to line wrap

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/test_proof_chain.py:372
- **What:** `test_doc_states_total_round_count` asserts `"3-round
  cap from E08" in text`. The doc currently has this on one line
  (`docs/proof-chain-workflow.md:28`). A markdown reformatter or
  manual reflow could insert a newline (`"3-round cap\nfrom E08"`)
  — the test would fail despite the doc carrying the AC#4 content
  faithfully.
- **Why it matters:** Brittle pin. The fix is trivial.
- **Proposed fix:** Normalize whitespace before the substring check
  (`text_norm = " ".join(text.split())`).
- **Regression guard:** The normalized assertion.

### F9 — Doc's worked example uses `await get_chunk(...)` inside a `for` comprehension that is not valid Python

- **Severity:** LOW
- **Source:** adversary
- **File:** docs/proof-chain-workflow.md:97-102
- **What:** The code block reads:
  ```
  bodies = await asyncio.gather(
      get_chunk(neighbor.chunk_id)
      for neighbor in result
      if neighbor.chunk_id is not None
  )
  ```
  This passes a generator to `asyncio.gather`, but
  `asyncio.gather` accepts coroutines as positional arguments, not
  an iterable. The canonical form is
  `asyncio.gather(*[get_chunk(...) for n in result if ...])`.
  The test uses the correct splatted form
  (`tests/test_proof_chain.py:218-220`); the doc example does not.
  A reader who copy-pastes the doc example gets `TypeError`.
- **Why it matters:** The worked example is the agent author's
  reference. A non-runnable example degrades the doc's value as
  a starting point for sub-agent prompt authors.
- **Proposed fix:** Edit `docs/proof-chain-workflow.md:97-102`
  to splat the comprehension:
  `bodies = await asyncio.gather(*[get_chunk(n.chunk_id) for n in
  result if n.chunk_id is not None])`.
- **Regression guard:** Optional — extract the doc's code block
  and `compile()` it in a doc-pin test.

## What was done well

- AC mapping in `implementation-summary.md:20-29` is honest and
  itemized; the v1 caveat on AC#5 is called out rather than papered
  over.
- The synthetic graph helper at `tests/_graph_helpers.py:26-101`
  has a clean docstring describing the wrap-around semantics
  (`P_0 cites P_{N-1}, P_{N-2}, P_{N-3}`), which is exactly the
  property the AC#7 test depends on.
- `tests/_graph_helpers.py:104-147` consolidates the
  `_build_lancedb` helper without refactoring existing tests —
  diff-focused; matches the milestone's stated philosophy.
- The doc's "Security note" (`docs/proof-chain-workflow.md:186-211`)
  faithfully restates F2's path-traversal contract for the future
  MCP-tool wrapper boundary.
- Doc accurately describes the v1 `search_papers(filters=...)` gap
  and explicitly states it's accepted-but-ignored
  (`docs/proof-chain-workflow.md:117-153`), which is the
  honest framing.
- The fixture's teardown via `reset_resources_for_tests()` is
  correctly wired in `finally:` block — the singleton clear *does*
  run on test failure, so the leak risk other tests would face is
  bounded.
- Test count delta (+10) matches the test class count claimed in
  the summary; no orphan/disabled tests.
- The 16-hex-suffix chunk_id format used in the doc respects
  `CHUNK_ID_RE` from `ingest/identifiers.py` — the brief's
  invalid `:stmt-thm-grr` form was correctly rejected and a
  callout was added documenting the synthetic-vs-real distinction.
- Round-2 parallelism via `asyncio.gather` in the test
  (`tests/test_proof_chain.py:218`) is the correct coroutine
  shape for the documented "N parallel tool_use blocks in a
  single assistant turn" pattern — the doc's claim and the test's
  semantics align.
- `_FakeResources` pattern (`tests/test_proof_chain.py:130-140`)
  matches the established
  `tests/test_tools_all.py:482-496` pattern cited in the
  implementation summary — consistent test-infra style.

## Recommended rectification order

1. F1 — the only HIGH; perf-gate signal quality is the
   load-bearing concern. Either densify the synthetic graph or
   add an env-gated real-corpus variant.
2. F9 — trivial doc fix; the worked example is the doc's primary
   payload and a copy-pasteable `TypeError` undermines it.
3. F2 — tighten the doc-pin disjunction so AC#5's "third round"
   framing can't silently drift.
4. F7 — strengthen the body_text assertion (one-line edit, high
   signal-to-effort).
5. F3 — make the AC#7 test's edge-wiring dependency explicit at
   fixture time.
6. F5 — add a docstring section to `cite_neighbors` pinning the
   500ms target at the library level.
7. F4 — close the lancedb handle on teardown (cheap; pre-empt CI
   flake risk).
8. F8 — normalize whitespace in the doc-pin assertion.
9. F6 — promote fixture scope (pure perf; defer if not blocking).

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate. -->
