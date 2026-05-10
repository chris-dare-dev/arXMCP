# E05_S02 — Research Brief 2 (retrieval-quality test)

## 1. In-codebase context

**Applicable design notes.** `05-storage-and-indexing.md` (dual-column
ANN, BGE-M3 1024-dim, HNSW M=16/efC=200), `06-mcp-server-design.md`
(`search_papers` payload shape, BP1 byte-stable rule), `07-multi-agent-
caching.md` (BP1: *"Sort results by `(score_desc, chunk_id_asc)`. Use
deterministic chunk IDs… No timestamps, no random tie-breaks. JSON keys
serialized in alphabetical order."*), `09-feature-priorities.md` (Tier-0
exit criterion: nDCG@5 ≥ 0.70 ANN-only).

**ANN search idiom.** `server/corpus.py:117` documents the live API:
*"The handle supports the standard LanceDB read API: `count_rows`,
`to_arrow`, `search`, `schema`, `version`."* No code in the tree calls
`tbl.search(...)` yet — `tests/test_store.py` only uses `tbl.to_arrow()`
for full scans. Research notes from sibling milestones confirm the
working idiom: E04_S02 brief 2 §183 — *"Experimentally: `tbl.checkout(v1)`
followed by `.search(query_vec).limit(1)`"* and E04_S04 brief 1 §33 —
*"`tbl.search().select([…]).limit(None).to_arrow()`"*. **The shape that
works in lancedb 0.30 is `tbl.search(np_vector, vector_column_name="…").
limit(K).to_arrow()`** (the column kwarg is required because the
`chunks` schema has TWO vector columns — `embedding_stmt` AND
`embedding_proof`; without the kwarg LanceDB raises). The result Arrow
table includes a synthesized `_distance` column (l2 distance, since
`store.py:408` says *"Distance type left at the LanceDB default (l2);
BGE-M3 vectors are L2-normalized so l2 and cosine produce identical
rankings."*). **Score = `1 - _distance / 2`** (cosine equivalence on
unit vectors); for ranking purposes use `-_distance` directly so smaller
is better → larger is better via negation.

**`encode_query` shape.** `server/query_encoder.py:235-276` returns
*"shape `(EMBEDDING_DIM,)` and dtype `np.float32`"* with `EMBEDDING_DIM
= 1024` (`ingest/embedder.py:122`), CLS-pooled and L2-normalized via
`F.normalize(p=2, dim=-1)`. It is `async`, so the test must `await` it
inside an `async def` test (pytest-asyncio is NOT installed —
`pyproject.toml` shows zero asyncio plugin), so we wrap with
`asyncio.run(encode_query(text))`. Tests exercising it (e.g.
`tests/test_query_encoder.py`) confirm the sync wrapper works.

**`open_chunks_table` + `read_corpus_version`.** Both live in
`server/corpus.py`. The brief AC says *"Pinned corpus version via
read_corpus_version()"* — call `info = read_corpus_version()`, then
`tbl = open_chunks_table(version=info.version)`. `read_corpus_version`
returns `None` on absent marker (cold start) — `corpus.py:317-376`.

**Existing conftest pattern.** `tests/conftest.py:17-64` already wires
two autouse `monkeypatch` fixtures (`_patched_store_stats_path`,
`_patched_bm25_stats_path`) that redirect `var/arxmcp/ops/*.jsonl`
writes into `tmp_path` so test runs do not pollute the dev tree. The
new test must follow the same discipline for `var/arxmcp/ops/eval/`
results — but the brief AC explicitly says *"Per-query JSONL and
aggregate JSON are written to `var/arxmcp/ops/eval/`"*. **Resolution:**
when the test runs against the real corpus (E05 mode), write to the
real path; the autouse `tmp_path` patches do NOT cover the eval dir
and SHOULD NOT be extended to (the eval result IS the production
artifact). Add a third autouse fixture only IF unit tests for
`metrics.py` need stub paths — they don't.

**`pytest_addoption` in conftest.** Standard pytest API, supported by
`pytest>=8.0` (pyproject.toml line 32). Add to the existing
`tests/conftest.py`:

```python
def pytest_addoption(parser):
    parser.addoption("--ndcg-min", action="store", default=0.70, type=float)
```

Pull via `request.config.getoption("--ndcg-min")` inside the test.

**Aggregate JSON schema echo.** Brief schema mirrors `WriteStats`/
`store-stats.jsonl` and `bm25-stats.jsonl` discipline: alphabetical
keys, `json.dumps(sort_keys=True)`. The `corpus-version.json` writer
(`store.py:472-575`) is the canonical pattern: PID + UUID-suffix tmp +
`os.replace` for the aggregate (a single-write artifact); JSONL is
append-mode for results.

**No existing `metrics.py`.** `tests/eval/` currently holds
`__init__.py`, `fixtures/`, and `test_fixtures.py`. The brief calls for
new `tests/eval/metrics.py`.

## 2. Prior decisions and lessons

**Cold-start protocol from E05_S01 (load-bearing).** E05_S01's validator
returned `mode="seed"` and exited 0 when `len(queries) == 0` AND/OR no
manifests existed (`tools/validate_eval_fixtures.py:564-584`). The
E05_S02 metric harness has the same dilemma: at the moment of merge,
`queries.json` ships with `queries: []` (per E05_S01 D2) and the seed
corpus is not yet ingested. **Recommend: `pytest.skip()` with a clear
message** ("eval cold-start: queries.json is empty (curation pending)
OR LanceDB corpus absent — see docs/eval-curation.md"). Vacuous-pass
(the alternative) silently encodes "test ran, no signal." A skip is
the correct semantic — there is literally nothing to measure. This
matches the existing convention: `tests/test_embedder.py` skips a
BGE-M3 integration test when the model isn't downloaded
(implementation-summary E05_S01 §"530 passed, 2 skipped … env-gated
BGE-M3 integration").

**BP1 discipline (07-multi-agent-caching.md).** *"JSON keys serialized
in alphabetical order."* Aggregate JSON: `{ndcg5_mean, query_count,
recall10_mean, timestamp, …, version}` MUST be `sort_keys=True`. The
`timestamp` field is FINE because eval result files do NOT enter the
prompt-cache path (they are ops-side audit, not server-side output).
This mirrors the `corpus-version.json` precedent (`store.py:512-515`):
*"The `created_at` timestamp is debug-only and outside BP1 scope (the
marker file is a runtime config artifact, not a cached artifact, and
never enters the prompt cache or tool result payload)."* Same here.

**Atomic-write discipline (E04_S03 / E03_S02 / E02_S02).** The
canonical pattern from `store.py:567-575` and `preamble.py`'s
`_write_preamble_json` is PID + UUID-suffix tmp + `os.replace` +
`try/finally` cleanup. **Recommend: aggregate JSON uses this
pattern** (it's a one-shot file per corpus_version; partial writes
break drift detection). **JSONL uses simple append** (multi-line; same
discipline as `store-stats.jsonl` `_append_store_stats` at
`store.py:450-464` — *"Append mode is non-atomic but acceptable for an
ops log"*).

**Single source of truth pattern.** E04_S04 + E05_S01 enforced this:
re-importing constants vs. literalizing strings. **Apply here:** import
`EMBEDDING_DIM`, `CHUNKS_TABLE_NAME` from their canonical homes; never
hardcode `1024` or `"chunks"`.

**Things that always break (from rectification critiques).** F1 from
multiple critiques: validate inputs at function boundaries (e.g.
chunk_ids in fixture must validate against `_CHUNK_ID_RE`). F11
patterns: don't ship dead code; dead helpers in a test module surface
in CI as ruff F401.

## 3. External sources

**nDCG@k canonical formula (Järvelin–Kekäläinen 2002).** The brief uses
the plain `rel_i` form: `DCG@k = Σ_{i=1..k} rel_i / log2(i+1)`, then
`nDCG@k = DCG@k / IDCG@k`. The Burges (2005) variant `(2^rel - 1) /
log2(i+1)` is the LambdaMART/sklearn default and emphasizes top-grade
docs more aggressively. **Brief is unambiguous: use plain form.**
sklearn's `sklearn.metrics.ndcg_score` uses the BURGES form by default
(its docs: *"DCG = Σ (2^y - 1)/log2(rank+1)"*) — DO NOT use sklearn;
hand-roll the J-K form (~10 LOC). Edge cases: IDCG = 0 (no graded
relevance for query) → return 0.0 (consistent with sklearn behavior
and TREC convention).

**Recall@k formula.** `recall@k = |relevant_in_top_k| / |relevant_total|`.
Brief constrains "relevant" = grade-3 (highly relevant). Edge case:
zero grade-3 chunks for a query → undefined. **Recommend: return 1.0
(vacuously satisfied) and emit a warning; OR exclude from mean.**
TREC convention is to exclude zero-relevant queries from the mean
(otherwise the metric is undefined). E05_S01 AC-2 already enforces
≥1 grade-3 per query at fixture-validation time, so this branch
should be UNREACHABLE in production — but the standalone metric
function in `metrics.py` must still handle it (return 0.0 with a
guard, since the standalone fn cannot assume the AC).

**LanceDB ANN API (0.30+).** `Table.search(query_vector,
vector_column_name="…").limit(K).to_arrow()` is the public idiom.
The result includes the original columns + `_distance`. The
`vector_column_name` kwarg is REQUIRED on multi-vector schemas
(otherwise raises `ValueError("multiple vector columns found, …")`).
For HNSW the `nprobes` knob defaults to 1 — fine for top-10 on a
50-paper corpus. **Don't tune `nprobes` or `refine_factor`** at this
milestone; baseline is the point.

**`pytest_addoption` API.** Standard pytest hook (≥3.x). Custom CLI
flag persists in `request.config.getoption("--ndcg-min")`. `type=float`
is enforced by argparse under the hood.

## Open questions

- **(a) Cold-start behavior.** **Recommend `pytest.skip("…")`** when
  `read_corpus_version()` returns `None` OR `queries.json` has zero
  entries. Vacuous-pass would let CI green on a half-built repo and
  hide the missing baseline; an error would block every dev box that
  hasn't ingested. Skip is the only honest signal.
- **(b) Where `metrics.py` lives.** Brief says `tests/eval/metrics.py`.
  **Recommend ship there now; relocate to a `eval/` top-level package
  in E07/E11 when the server's reranker pipeline imports it.** The
  test-located module is fine for Tier-0 (only the test itself imports
  it); a premature move pollutes the production import graph with
  test-only deps. Add a TODO comment in the file.
- **(c) Score-merge dedup.** Same chunk_id appears in both
  `embedding_stmt` ANN top-k and `embedding_proof` top-k.
  **Recommend MAX score** (smaller `_distance`). Rationale: a chunk's
  best-channel match is the most defensible single-number score, and
  matches the spirit of *"Reciprocal Rank Fusion at query time"*
  (`05-storage-and-indexing.md:296`) at the rank-1 level. SUM
  double-counts a chunk that happens to have both embeddings (only
  proof chunks do, since stmt chunks have `embedding_proof = NULL`),
  systematically biasing proof chunks upward — wrong.
- **(d) Aggregate-JSON write pattern.** **Recommend
  PID+UUID-tmp+`os.replace`** (the `store.py:567-575` pattern).
  Aggregate is one row per corpus_version; a partial write breaks
  E11_S04 drift detection. JSONL: append-mode `_append_*` pattern.
- **(e) `--ndcg-min` flag.** Yes — `pytest_addoption` is the
  standard hook (pytest ≥3.x). Test reads via
  `request.config.getoption("--ndcg-min")`.
- **(f) `timestamp` format.** **Recommend ISO-8601 string
  (`datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")`)** matching the
  `corpus-version.json` `created_at` discipline (`store.py:559`).
  Eval files are NOT in the BP1-cache path (per the
  `corpus-version.json` precedent quoted above), so the timestamp is
  unproblematic — but use ISO-8601 over epoch-int for grep-ability
  and consistency with sibling artifacts.

## External writes the implementation will require

| type | target | why |
|---|---|---|
| filesystem write (in-tree) | `tests/eval/test_retrieval_quality.py` | new test file (NEW) |
| filesystem write (in-tree) | `tests/eval/metrics.py` | standalone `ndcg_at_k` + `recall_at_k` |
| filesystem write (in-tree) | `tests/eval/test_metrics.py` | unit tests for the two metric fns |
| filesystem write (in-tree) | `tests/conftest.py` | append `pytest_addoption` for `--ndcg-min` |
| filesystem write (var/, runtime) | `var/arxmcp/ops/eval/results-<v>.jsonl` | per-query results (gitignored) |
| filesystem write (var/, runtime) | `var/arxmcp/ops/eval/aggregate-<v>.json` | drift baseline (gitignored) |

**No git push, no PR creation, no ticket, no infra mutation, no
third-party API call.** The milestone is local. The runtime `var/`
writes happen only when the user has a populated LanceDB corpus AND a
curated `queries.json`; on a cold-start dev box the test skips and
nothing is written.
