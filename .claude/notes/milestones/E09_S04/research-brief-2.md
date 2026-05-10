# E09_S04 — research brief 2

Independent brief. The brief's worked example contains two falsifiable
inventions: (a) the chunk_ids `arxiv:1803.01010:stmt-thm-grr`, etc. do
not match `CHUNK_ID_RE`, and (b) `1803.01010` / `0901.0101` /
`1205.4344` are NOT in the seed corpus. The integration test
absolutely cannot use those literal IDs. The doc, however, can — see
"Open questions" for the recommended split.

## 1. In-codebase context

### `server/handlers/chunk.py` — exact handler shape (load-bearing)

The handler returns `chunk.body_text` nested under `chunk` (not at
top level). Quote (lines 63–74):

> ```
> chunk = {
>     "body_text": row["body_text"] or "",
>     "chunk_id": row["chunk_id"],
>     ...
> }
> payload = {"chunk": chunk, "found": True, ...}
> ```

AC#2 says round 2 returns "non-null body_text for all returned
chunk_ids" — the test must read `result["chunk"]["body_text"]`, not
`result["body_text"]`. Also: an unknown but well-formed chunk_id
returns `{found: false, chunk: None}` (lines 52–60) — NOT a raise.
The test must guard against that, and the brief's AC#2 says
"non-null body_text" which is only sound if the test sets up real
chunk rows for each candidate.

Validation: `if not is_valid_chunk_id(chunk_id): raise ValueError(...)`
(line 39). The format is hard-pinned at `ingest/identifiers.py:52`:

> `CHUNK_ID_PATTERN = rf"arxiv:({PAPER_ID_PATTERN}):[0-9a-f]{{16}}"`

### `server/handlers/search.py` — `paper_id` is NOT a real filter

This is critical. The brief's AC#5 says when `chunk_id=None` the
agent uses `search_papers(paper_id=<paper_id>)`. The actual handler
signature (lines 79–96) has no `paper_id` argument; it has only
`filters: dict[str, Any] | None` which is **explicitly ignored at
v1**:

> `# F6: surface ignored filter/cursor warnings explicitly` …
> `"filters arg is accepted but not yet processed (deferred to E07_S04)"`

The doc's "use `search_papers(paper_id=…)`" advice is therefore
prescriptive about a future contract. The doc must say "pass
`{"paper_id": "<id>"}` in `filters`; v1 will ignore it and surface a
`filter_warnings` entry, returning a generic top-k that won't be
paper-scoped". This is a real surface flaw in the AC; the test
cannot exercise that branch as a real fallback, only document it.

### `server/tools.py` — `cite_neighbors` IS already registered

Brief implies registration is pending. Quote (lines 187–198):

> `ALL_TOOLS: tuple[ToolMeta, ...] = (… CITE_NEIGHBORS,)`

and (line 387): `CITE_NEIGHBORS.name: handle_cite_neighbors`.

But `handle_cite_neighbors` (server/handlers/citations.py) is the
**v1 stub** — it returns `{neighbors: [], infrastructure_status:
"deferred", …}` and ignores `chunk_id`. The library
`server.graph_queries.cite_neighbors` (E09_S03, real) is NOT wired to
the handler. E09_S04 has TWO choices: (a) wire the handler to the
real query (in scope of "verify cite_neighbors fast enough") or
(b) leave the handler stub and have the integration test call
`server.graph_queries.cite_neighbors` directly. The brief's
deliverable list says "Update to `server/graph_queries.py` — verify
`cite_neighbors` returns results fast enough" — that wording covers
the library, not the handler. The test should call the library
directly; wiring the handler is a separate scope (likely E06_S04 or
E09_S05).

### `tests/test_graph_queries.py` — `kuzu_db` fixture pattern

The fixture (lines 62–94) builds a 5-paper synthetic graph in
`tmp_path` via `kuzudb_schema.apply_schema` + `graph_ingest._merge_cite`.
That same pattern is the right shape for E09_S04. The test file
also includes a `_build_lancedb` helper (lines 426–457) that
materializes a tiny `chunks` LanceDB table from
`ingest.schema.CHUNKS_SCHEMA_V1`. That is exactly what the round-2
test needs: rows with `chunk_id`, `paper_id`, `kind`, plus the
required placeholders (`section_path=[]`, `body_text=""`,
`body_tokens=""`, `chunker_version="test"`, `embedder_version="test"`).

For round-2, the synthetic LanceDB rows MUST include a non-empty
`body_text` so AC#2's "non-null body_text" assertion is meaningful.

### `server/resources.py` + `get_resources()`

`server/handlers/chunk.py` calls `r = get_resources()` (line 44).
`server/tools.py:220` raises `ResourcesNotReadyError` if the
singleton was never set. The integration test must therefore call
`set_resources(_FakeResources())` before invoking
`handle_get_chunk`. The pattern is established at
`tests/test_tools_all.py:482-496`:

> `class _FakeResources: config = cfg; corpus_info = _FakeCorpusInfo()`

Plus the LanceDB chunks_table must hang off the fake — i.e.
`_FakeResources.chunks_table = lancedb.connect(...).open_table("chunks")`.

### Time-bound test precedent

`time.monotonic` is used in `tests/test_server_startup.py:211`,
`tests/retrieval/test_bm25.py:228,1000`,
`tests/retrieval/test_ann.py:898`,
`tests/retrieval/test_rerank.py:774`, and
`tests/eval/test_retrieval_quality.py:424` (uses
`_time.monotonic` with `* 1000.0` to get ms). No `pytest-benchmark`
in `pyproject.toml`. No `bench` marker. Only two markers:
`requires_model` and `eval`. The `eval` marker is "Skipped via the
cold-start matrix when fixture or corpus is missing".

### `tests/conftest.py` autouse fixtures

Four autouse fixtures fire on EVERY test:
`_patched_store_stats_path`, `_patched_bm25_stats_path`,
`_patched_bm25_index_root`, `_reset_session_state_for_tests`,
`_patched_cache_db_path`. The new test inherits these — no opt-out
needed. The `KMP_DUPLICATE_LIB_OK` workaround (line 38) is also
already in place for tests that import faiss + torch in the same
process.

### Eval fixture (E05_S01)

`tests/eval/fixtures/queries.json` is `{"queries": []}` — an empty
stub. The brief's claim "uses a known entry theorem chunk_id from
the eval fixture (E05_S01)" is **false** today. There IS no entry
theorem there. The test must synthesize its own.

## 2. Prior decisions and lessons

- **Seed corpus is post-2604 math.AG.** `tools/seed-papers.txt` IDs
  are all `2604.*` and `2605.*`. The brief's `1803.01010`,
  `0901.0101`, `1205.4344` are NOT in the seed. Even if they were,
  GRR is from 1971 — the canonical paper isn't on arXiv at all.
- **Brief's `:stmt-thm-grr` suffix is invalid.** Per
  `CHUNK_ID_RE`, the suffix is exactly 16 lowercase hex chars.
  `is_valid_chunk_id("arxiv:1803.01010:stmt-thm-grr")` returns
  False, and `handle_get_chunk` raises `ValueError` BEFORE doing
  anything. Putting that literal in the integration test guarantees
  failure on line 1. Putting it in the doc is fine ONLY if the doc
  flags it as illustrative.
- **Performance methodology.** `pytest-benchmark` is not a
  dependency; do NOT add it. Project precedent is `time.monotonic()`
  diffs around the call site. Use it.
- **"Against seed corpus" is not literally feasible in CI.** No CI
  setup ingests the seed corpus into Kùzu + LanceDB. The right
  pattern, per E09_S03 test discipline, is a synthetic 50-paper
  Kùzu graph (extending `kuzu_db` from `test_graph_queries.py`)
  plus a synthetic `chunks` LanceDB with realistic chunk_ids. This
  matches `test_max_results_caps_returned_count` precedent and
  exercises the same code path the production graph would.
- **F-finding inheritance.** From E09_S01/S02/S03, the only ones
  that touch this milestone are: F1/F5 (chunk_id=None on missing
  paper / kind-priority fallback) — the doc must accurately
  describe these; F2 (path-traversal at MCP boundary) — irrelevant
  for a docs/test milestone since the wrapper isn't being added.
- **E02_S05's "fixture update procedure"** does exist as
  `docs/chunker-fixtures.md` (regeneration runbook on
  `chunker_version` bumps, per E02_S05 implementation summary). The
  brief's link is real, not broken. If the worked-example chunk_ids
  were ever pinned to real corpus output, they'd need to be
  regenerated alongside that runbook.

## 3. External sources

- **MCP 2025-06-18 spec.** "Round budget" is **NOT** an MCP standard
  term. `.claude/notes/07-multi-agent-caching.md:314` uses
  "budget" only in the context of "budget is being spent" (cache
  spend). The 3-round cap is a project-level Sonnet B / E08
  invariant, not a wire-protocol concept. The doc must phrase it as
  a project guarantee, not a spec citation.
- **`pytest-benchmark`.** Verified absent from `pyproject.toml` and
  `uv.lock`. Adding it would be a new dep + a dev/CI cost; not
  warranted for one perf gate. Use `time.monotonic`.

## Open questions (with recommendations)

- **Worked-example chunk_id format.** Use the real
  `arxiv:<paper_id>:<16-hex>` format with synthetic-but-realistic
  hex (e.g. `arxiv:2605.03890:0123456789abcdef`). Drop GRR. Pick
  one entry theorem from `seed-papers.txt`. The doc retains
  realism; the integration test uses the SAME synthetic IDs. The
  brief's `:stmt-thm-grr` is not portable past the regex check.
- **Test infrastructure.** Synthetic fixture, full stop. Extend
  `test_graph_queries.py::kuzu_db` to a 50-paper variant with a
  realistic citation density (each paper cites 3–5 random
  predecessors), plus a matching synthetic LanceDB chunks table
  built via `_build_lancedb` (lift to a shared helper —
  `tests/_graph_helpers.py`?). The brief's "against seed corpus"
  language is aspirational for CI; ship the synthetic and document
  the gap.
- **Performance assertion.** `time.monotonic` directly, with the
  500ms gate INSIDE the test body — no skip-when-not-bench. The
  test is one run of `cite_neighbors(depth=2, max_results=50)` over
  the synthetic 50-paper graph; ~50 BFS results from a Kùzu
  embedded DB on tmp_path will run in well under 100ms locally and
  CI. If flaky, raise to 1000ms with a comment.
- **Test marker.** Don't introduce a new marker. The test runs
  always (it's pure-Python + tmp_path + Kùzu, no external deps).
  Adding a `bench` marker for one assertion is overkill.
- **Round-2 parallelism.** Use `asyncio.gather` — the doc claims
  "issued in parallel in a single round", and the test should
  prove the pattern works concurrently (not just sequentially).
  `gather` over N `handle_get_chunk(...)` coroutines is two extra
  lines. Failures are clearer than a sequential loop.
- **Does `search_papers` accept `paper_id` as a filter?** No, only
  via the `filters` dict and v1 ignores it (with a
  `filter_warnings` entry). The doc's AC#5 fallback prescription
  must say so explicitly: "pass `filters={"paper_id": …}`; v1 ignores
  it and surfaces `filter_warnings`; full support lands in
  E07_S04."
- **AC#5 chunk_id=None branch in the test.** Build the synthetic
  LanceDB with EXACTLY one paper missing from the chunks table —
  exercises `_lookup_chunk_ids_for_papers` returning `None` for
  that paper. Then assert that the agent-pattern code in the test
  routes to `search_papers` (or skips) for that one paper. Mirror
  E09_S03's `test_f1_chunk_id_none_for_paper_missing_from_real_lancedb`.
- **E02_S05 fixture update procedure.** Real — `docs/chunker-fixtures.md`.
  If the worked example uses real corpus IDs, link to that runbook.
  If synthetic, link is unnecessary — note that the IDs are
  illustrative and not regenerated.

## External writes the implementation will require

| Kind | Target | Notes |
|---|---|---|
| filesystem write | `docs/proof-chain-workflow.md` | new doc with worked example + 2-round explainer |
| filesystem write | `tests/test_proof_chain.py` | new test with synthetic Kùzu + LanceDB fixtures + 500ms gate |
| filesystem write (optional) | `tests/_graph_helpers.py` | shared `build_synthetic_kuzu_graph(n_papers, edges)` + `build_synthetic_lancedb(rows)` lifted from `test_graph_queries.py` |
| filesystem write (optional) | `server/handlers/citations.py` | wire stub to `server.graph_queries.cite_neighbors` — only if E09_S04 takes scope; otherwise defer to E06_S04 |
| no | git push, PR, ticket, third-party API | none required |

The "Update to `server/graph_queries.py`" deliverable in the brief
is misleading — there is no actual code change implied by the AC; the
500ms target is a TEST assertion, not a graph_queries diff. If
profiling shows the synthetic-50 case violates 500ms, only THEN do
we touch graph_queries (likely a `LIMIT` push-down or an early
break). Document the no-op in the implementation summary.
