# E09_S04 Research Synthesis

**Milestone:** Cross-paper proof chain workflow (2-round agent pattern)
— docs + integration test that closes H7 in combination with E09_S03's
`cite_neighbors` implementation.
**Inputs merged:** [research-brief-1.md](research-brief-1.md),
[research-brief-2.md](research-brief-2.md).
**Date:** 2026-05-10.

Both researchers converged on the same five critical brief issues
(below). They differ only on test-corpus sizing (R1: 5 papers, R2:
50 papers); the synthesis picks 50 because AC#3 names "50-paper
corpus" explicitly and the perf-gate target is calibrated for that
scale.

---

## 1. FIVE critical brief issues that change the implementation

These are factual problems with the brief that both briefs flagged.

### 1.1 Brief's chunk_id format is INVALID per `CHUNK_ID_RE`

Brief example: `arxiv:1803.01010:stmt-thm-grr`.
Project regex (`ingest/identifiers.py:52`): `arxiv:<paper_id>:[0-9a-f]{16}`.

`is_valid_chunk_id("arxiv:1803.01010:stmt-thm-grr")` returns `False`,
and `handle_get_chunk` would raise `ValueError` BEFORE any lookup. The
brief's IDs are not implementable.

**Resolution:** rewrite the worked example with the canonical
`:<16-hex>` format and synthetic-but-realistic hex values
(e.g. `arxiv:2605.03890:0123456789abcdef`). Add a one-paragraph
callout in `docs/proof-chain-workflow.md`:

> Chunk IDs in this document use synthetic 16-hex suffixes for
> readability. The production format is
> `arxiv:<paper_id>:<sha256(preamble + NFC(body))[:16]>` —
> see `ingest/identifiers.py` and `docs/chunker-fixtures.md`
> (E02_S05) for the regeneration procedure.

### 1.2 Brief's paper IDs are NOT in the seed corpus

`tools/seed-papers.txt` is exclusively `2604.*` / `2605.*` (50
post-2026 math.AG IDs). The brief's `1803.01010` (the supposed
Grothendieck-Riemann-Roch source), `0901.0101`, `1205.4344` aren't
there. Worse, GRR is from 1971 — the canonical paper isn't on arXiv
at all; only later expositions are.

**Resolution:** drop GRR from the worked example. Use a synthetic
fixture corpus (matching `tests/test_graph_queries.py::kuzu_db`'s
pattern) for the test. Use synthetic paper_id values in the doc that
LOOK like the seed corpus (`2605.*` range) without claiming to be
specific papers.

### 1.3 `search_papers(paper_id=<id>)` is NOT implementable at v1

Brief AC#5: when `chunk_id=None`, the agent uses
`search_papers(paper_id=<paper_id>)` and that counts as a third
round. But `server/handlers/search.py` has no `paper_id` parameter
— only `filters: dict[str, Any] | None` which is **explicitly
ignored at v1**:

> "filters arg is accepted but not yet processed (deferred to E07_S04)"

The brief's fallback prescription is currently unimplementable.

**Resolution:** the doc must accurately describe this:

> When a `CitationNeighbor` has `chunk_id=None`, the agent calls
> `search_papers(query=<keyword>, filters={"paper_id": "<paper_id>"})`.
> The `filters` argument is **accepted but ignored at v1**
> (deferred to E07_S04); the server surfaces a `filter_warnings`
> entry on the response. Until E07_S04 lands, papers with
> `chunk_id=None` are dead-ends in the proof-chain workflow and
> the agent should skip them rather than spending a third round on
> a paper-scoped search that v1 cannot satisfy. The "3-round
> budget exhausted" framing applies once E07_S04 makes the filter
> real.

The test exercises the `chunk_id=None` branch (the synthetic fixture
puts exactly one paper in Kùzu but NOT in LanceDB) but does NOT call
`search_papers` — it asserts the result has a None chunk_id and
documents the skip.

### 1.4 `get_chunk` returns `body_text` NESTED under `chunk`

`server/handlers/chunk.py:63-74`: `payload = {"chunk": chunk, "found":
True, ...}` where `chunk["body_text"] = row["body_text"] or ""`.

AC#2 says "non-null body_text" — the test must read
`result["chunk"]["body_text"]`, NOT `result["body_text"]`.

**Resolution:** the test reads the nested field; the doc shows it
nested in the worked example.

### 1.5 The eval-fixture (E05_S01) is EMPTY

`tests/eval/fixtures/queries.json` is `{"queries": []}` — the brief's
"known entry theorem chunk_id from the eval fixture" doesn't exist.

**Resolution:** the integration test synthesizes its own entry chunk
(matches `test_graph_queries.py::CHUNK_A` pattern). No dependency on
the still-unpopulated eval fixture.

---

## 2. Handler-wiring scope decision

`server/tools.py` already registers `CITE_NEIGHBORS` and routes it to
`handle_cite_neighbors` in `server/handlers/citations.py`. The handler
is a v1 STUB returning `{neighbors: [], infrastructure_status:
"deferred"}`. The real library
(`server.graph_queries.cite_neighbors` from E09_S03) is NOT wired.

R1 explicitly recommends NOT wiring the handler in this milestone.
R2 says "TWO choices" with the same lean. Both researchers note that
wiring the handler creates the F2 path-traversal contract surface
that E09_S03 explicitly deferred to E06_S04 / E09_S04.

**Pick:** do NOT wire `handle_cite_neighbors` to the real library in
this milestone. The integration test calls
`server.graph_queries.cite_neighbors` directly. The handler-wiring is
a separate concern that lands when the MCP-tool wrapper formalizes
the path-validation boundary (a future E06_S04 / E09_S05 milestone).

This is consistent with the brief's deliverable list:

> "Update to `server/graph_queries.py` — verify `cite_neighbors`
> returns results fast enough for 2-round budget"

That wording refers to the library, not the handler.

---

## 3. Test infrastructure — synthetic 50-paper Kùzu graph

AC#3: "`cite_neighbors(depth=2)` completes in ≤500ms on the 50-paper
seed corpus." The literal seed corpus on disk isn't materialized in
CI (no `make ingest`). The test MUST use a synthetic fixture.

R1: recommends 5 papers (mirrors `test_graph_queries.py`) + optional
env-gated real-corpus test.
R2: recommends 50 papers (matches AC#3 wording) + full synthetic.

**Pick R2 with a twist:** 50 synthetic papers for the perf-gate
test. The smaller 5-paper case is already covered by
`test_graph_queries.py`. The 50-paper test is what AC#3 is asking for.

**Citation density:** R2 suggests "each paper cites 3-5 random
predecessors." Deterministic version: each paper P_i cites P_{i-1},
P_{i-2}, P_{i-3} (mod 50). That gives every paper exactly 3 outgoing
edges and 3 incoming, total 150 edges. `depth=2` from P_0 reaches up
to 3 + 9 = 12 papers (after dedup). Comfortably under `max_results=50`.

**LanceDB chunks fixture:** mirror R2's "lift to shared helper"
recommendation. Extract `_build_lancedb` from
`tests/test_graph_queries.py::TestE09S03RectificationGuards` into a
shared helper at `tests/_graph_helpers.py`. The 50-paper fixture
creates one `kind="stmt"` chunk per paper, plus ONE paper that exists
in Kùzu but NOT in LanceDB — exercises the `chunk_id=None` branch.

---

## 4. Performance methodology

Both researchers agree:

- **No `pytest-benchmark`** (not a dep; not warranted for one gate).
- **Use `time.monotonic()`** directly inside the test body — matches
  established project precedent (`test_server_startup.py:211`,
  `tests/retrieval/test_*.py`, `tests/eval/test_retrieval_quality.py:424`).
- **No new test marker.** The test runs always — pure Python +
  `tmp_path` + Kùzu has no external dep.

**Assertion:** `assert elapsed_seconds < 0.5` with a one-line
comment explaining the AC#3 budget.

If the synthetic test flakes on slow CI, raise the threshold to 1.0
with a TODO. R1 suggests this preemptively; I agree as a contingency.

---

## 5. Round-2 parallelism

Both: use `asyncio.gather(*[handle_get_chunk(cid) for cid in chunk_ids])`.

The doc claims "issued in parallel in a single round." The test must
prove the pattern works concurrently, not sequentially. `gather` is
two lines. `result["chunk"]["body_text"]` is what each gather'd
coroutine produces.

---

## 6. AC checklist mapped to deliverables

| AC | Status | How |
|---|---|---|
| #1 docs/proof-chain-workflow.md documents 2-round pattern with worked example | new doc | corrected chunk_id format, synthetic IDs |
| #2 pytest tests/test_proof_chain.py passes | new test | round 1: cite_neighbors returns ≥1 neighbor; round 2: asyncio.gather over handle_get_chunk, body_text non-null |
| #3 cite_neighbors(depth=2) ≤500ms on 50-paper corpus | test assertion | 50 synthetic papers + 150 edges + perf_counter |
| #4 doc states "Total round count = 2..." | new doc | verbatim sentence |
| #5 doc explicitly notes chunk_id=None fallback to search_papers | new doc | with the v1-can't-filter caveat |

---

## 7. F-finding inheritance from E09_S01/S02/S03

- **F2 (E09_S03; path-traversal contract):** the doc must restate
  the MCP-wrapper boundary contract for `cite_neighbors` and reach
  similar language for `get_chunk`. Both handlers must derive paths
  from `Resources`/`Config`. The doc is the right place to document
  this for the proof-chain workflow specifically.
- **F7 (E09_S03; `limit(1_000_000)`):** still open. Out of scope
  here; flag in the doc as a Tier-3-scaling concern that intersects
  with the 500ms target. At full Tier-3 corpus, the perf gate may
  need re-evaluation.
- **F10 (E09_S03; defensive empty-rels):** still deferred. Not
  exercised by this milestone.

No other F-findings apply.

---

## 8. Open questions resolved in this synthesis

1. ✅ **Worked-example chunk_id format**: `arxiv:<paper>:<16-hex>` with
   synthetic hex. Drop GRR. Use synthetic paper_id in the 2605.*
   range.
2. ✅ **Test infrastructure**: synthetic 50-paper Kùzu fixture with
   deterministic citation density, synthetic LanceDB chunks table.
   No real-corpus dependency.
3. ✅ **Performance assertion**: `time.monotonic()` direct, no
   marker, `assert < 0.5`.
4. ✅ **Test marker**: none. Test runs always.
5. ✅ **Round-2 parallelism**: `asyncio.gather`.
6. ✅ **`search_papers(paper_id=...)`**: doc accurately describes it
   as "accepted via `filters` but ignored at v1; deferred to
   E07_S04." Test does NOT exercise the search fallback.
7. ✅ **Handler wiring**: do NOT wire `handle_cite_neighbors` to the
   real library here. Test calls library directly. Stays in scope
   per the brief's "Update to `server/graph_queries.py`" wording.
8. ✅ **AC#5 chunk_id=None branch**: one paper in the synthetic
   fixture exists in Kùzu but NOT in LanceDB; test asserts result
   has `chunk_id=None` and documents the skip-rather-than-search
   policy.
9. ✅ **Eval fixture (E05_S01)**: empty today; synthesize own
   entry chunk in the test. No dependency.
10. ✅ **`E02_S05` fixture-update procedure**: real
    (`docs/chunker-fixtures.md`). Doc links to it for the chunk_id
    regeneration policy when `chunker_version` bumps.

---

## 9. Phase-2 implementation outline

**Files to write:**

- `docs/proof-chain-workflow.md` (new) — the 2-round pattern doc
  with corrected worked example.
- `tests/test_proof_chain.py` (new) — integration test:
  - 50-paper synthetic Kùzu graph (each paper cites 3 predecessors
    mod 50)
  - Synthetic LanceDB with one `kind="stmt"` chunk per paper EXCEPT
    one ("paper not in chunked corpus") to exercise the
    `chunk_id=None` branch
  - Round 1: `await cite_neighbors(...)` from the library
  - Round 2: `asyncio.gather(*[handle_get_chunk(cid) for cid in
    chunk_ids if cid is not None])`
  - Assertions: ≥1 neighbor, non-null body_text for all, perf gate
  - `chunk_id=None` branch: assert at least one result has
    `chunk_id is None`; assert it's NOT passed to `get_chunk`
- `tests/_graph_helpers.py` (new) — lift `_build_lancedb` and add a
  `build_synthetic_kuzu_graph(n_papers, edges_per_paper)` helper for
  reuse. Refactor `tests/test_graph_queries.py` to import from this
  helper (clean refactor; no behavior change).

**No code changes to `server/graph_queries.py`** unless the perf
test fails. The brief's "Update to server/graph_queries.py" line is
misleading — it's a TEST assertion, not a graph-queries diff.

**Test infrastructure:** `set_resources()` with a `_FakeResources`
that carries the synthetic `chunks_table`. Pattern is established at
`tests/test_tools_all.py:482-496`.

---

## 10. External writes the implementation will require

Both briefs agree: pure-local milestone.

| type | target | why |
|---|---|---|
| code | `docs/proof-chain-workflow.md`, `tests/test_proof_chain.py`, `tests/_graph_helpers.py` (new) | new doc + test + shared helper |
| edits | `tests/test_graph_queries.py`, `tests/test_intra_paper_refs.py` | refactor to use the shared helper (no behavior change) |
| filesystem write (operator-only) | none new | (everything is `tmp_path`-bound in tests) |

**No HTTP calls.** No new runtime dependencies.

**Phase 4 boundary**: no `git push`, no GitHub mutations. The
`external_writes_required` list at the milestone gate is empty.

---

## 11. Severity-tagged risk register for Phase 3

The adversary critic should focus here:

- **CRITICAL**: worked-example chunk_ids fail `CHUNK_ID_RE` (would
  block any reader who tries to use them); `tests/test_proof_chain.py`
  doesn't exercise the actual library function.
- **HIGH**: perf gate target wrong (synthetic 50 papers vs real
  50-paper corpus diverge significantly); the test's
  `set_resources(_FakeResources())` doesn't restore state at teardown
  (poisons other tests); the doc's `chunk_id=None` fallback advice
  is inconsistent with v1 (`search_papers` doesn't filter).
- **MEDIUM**: shared helper refactor breaks existing tests; round-2
  parallelism not actually exercised (only sequential); doc doesn't
  link to `docs/chunker-fixtures.md` regeneration procedure.
- **LOW**: doc tone too prescriptive about Sonnet B; missing
  "Total round count = 2" verbatim (AC#4).

---

**End of synthesis.** Phase 2 reads this in full + both briefs.
R2's brief has the more concrete handler shapes and file:line
citations; R1's is broader on the design rationale and the F-finding
inheritance details.
