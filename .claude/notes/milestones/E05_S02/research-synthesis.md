# E05_S02 — Research Synthesis

**Inputs:** `research-brief-1.md`, `research-brief-2.md` (both Sonnet,
parallel). Both briefs converge cleanly on every load-bearing
decision. The few disagreements (Recall edge case, score-merge framing)
are surfaced and resolved below.

---

## D1 — Cold-start behavior matrix

**Both briefs agree.** The seed corpus has not been ingested
(`var/arxmcp/index/lancedb/` does not exist); the E05_S01 fixture is
`{queries: []}` (curation pending). The test must handle the cold
state without reddening `make test`.

| `read_corpus_version()` | `len(queries)` | Test behavior |
|---|---|---|
| `None` (no marker) | 0 | `pytest.skip("both pending")` |
| `None` | 20 | `pytest.skip("corpus not ingested")` |
| `CorpusVersionInfo` | 0 | `pytest.skip("queries not curated")` |
| `CorpusVersionInfo` | 20 | RUN: encode → ANN × 2 cols → merge → score → assert |

R2: *"Vacuous-pass would let CI green on a half-built repo and hide
the missing baseline; an error would block every dev box that hasn't
ingested. Skip is the only honest signal."* R1: same precedent from
E05_S01's `mode="seed"` exit-0 path.

**Decision:** Skip with a message that names the open gate. The
Tier-0 exit gate (E05_S03's `TIER-GATES.md`) is what asserts
prerequisites are present before this test runs.

## D2 — `metrics.py` location

**Both briefs agree.** Ship `tests/eval/metrics.py` per the brief
verbatim. R1: *"Production code (eventual `search_papers` MCP tool,
E06) does NOT need to compute nDCG at request time."* R2: *"a
premature move pollutes the production import graph with test-only
deps."*

**Decision:** `tests/eval/metrics.py`, sibling unit tests in
`tests/eval/test_metrics.py`. Add a TODO note for E11_S04 (drift
watchdog) which is the first non-test consumer.

## D3 — Score-merge / dedup semantics

**Both briefs agree on MAX similarity (MIN distance).** R1: *"the
two columns embed two DIFFERENT representations of the chunk
(statement-only vs statement+proof-window) into the SAME 1024-dim
BGE-M3 space. A high score on either column is genuine evidence."*
R2: *"SUM double-counts a chunk that happens to have both
embeddings... systematically biasing proof chunks upward."*

R1 also notes: in practice the dedup is rarely active because the
schema enforces *exactly one* of `embedding_stmt` / `embedding_proof`
per row — so the dedup is defense-in-depth against future schema
changes. Implementation: `dict[chunk_id, distance]`, keep smaller
distance, then sort and take top 10.

**Decision:** MIN-distance dedup (= MAX-similarity). Simple dict
keyed on chunk_id with `min()`-style update.

## D4 — Aggregate timestamp format

**Both briefs agree.** ISO-8601 UTC string,
`datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")`. Mirrors
`ingest/store.py:write_corpus_version_marker`'s `created_at`
discipline. The eval files are NOT in the BP1-cache path (per the
`corpus-version.json` precedent), so the timestamp is unproblematic
— but use ISO-8601 for grep-ability and consistency.

**Decision:** ISO-8601 UTC with `Z` suffix.

## D5 — nDCG formula: Järvelin–Kekäläinen, not Burges

**Both briefs agree.** Brief AC verbatim: *"DCG@5 = Σ (rel_i /
log2(i+1)) for i=1..5, normalized by ideal DCG@5."* This is the
plain `rel_i` form (Järvelin–Kekäläinen 2002). `sklearn.metrics
.ndcg_score` uses the Burges (2005) `2^rel - 1` form by default and
must NOT be used. Hand-roll ~10–15 LOC.

**Decision:** Plain-rel formula, hand-rolled, zero new deps.

## D6 — iDCG = 0 edge case

**Both briefs agree.** Return 0.0 (consistent with sklearn / TREC
convention). The standalone metric function MUST handle this even
though E05_S01 AC-2 forbids zero-grade-3 queries in the fixture —
the metric function cannot assume the AC.

**Decision:** `if idcg == 0.0: return 0.0`.

## D7 — Recall edge case (zero relevant docs)

**Slight disagreement.** R1 doesn't address it explicitly. R2
proposes: *"return 1.0 (vacuously satisfied) and emit a warning, OR
exclude from mean. TREC convention is to exclude... but the
standalone metric function in `metrics.py` must still handle it
(return 0.0 with a guard)."*

**Decision:** Return 0.0 (not 1.0) when `|relevant_total| == 0`.
Rationale: 1.0 is misleading because "no relevant docs" is not
"all relevant docs retrieved" — a downstream mean over a fixture
with mixed zero-and-nonzero queries would be silently inflated by
the 1.0 cells. 0.0 is the conservative choice that matches the
nDCG=0 discipline. Document this in the metric's docstring.

## D8 — Atomic writes for aggregate JSON; append for JSONL

**Both briefs agree.** Aggregate is one row per `corpus_version`
(overwrite-style); use the canonical PID + UUID-suffix tmp +
`os.replace` + `try/finally` cleanup pattern from
`ingest/preamble._write_preamble_json`. JSONL is append-only,
non-atomic, mirroring `_append_store_stats` /
`_append_bm25_stats`.

**Decision:** Aggregate atomic; JSONL append. Both
`json.dumps(sort_keys=True, ensure_ascii=False)`.

## D9 — async `encode_query` from sync test

**Both briefs agree.** `pytest-asyncio` is NOT installed (verified
in `pyproject.toml`). Wrap with `asyncio.run(encode_query(q))` per
query. No concurrency benefit on a 20-query loop; simple is right.

**Decision:** `asyncio.run(encode_query(text))` per call.

## D10 — LanceDB ANN search idiom

**Both briefs agree.** lancedb 0.30+ idiom:

```python
result_arrow = (
    tbl.search(np_vec, vector_column_name="embedding_stmt")
       .limit(K)
       .to_arrow()
)
chunk_ids = result_arrow.column("chunk_id").to_pylist()
distances = result_arrow.column("_distance").to_pylist()
```

`vector_column_name` kwarg is REQUIRED on multi-vector schemas
(LanceDB raises otherwise — both briefs note this). `_distance` is
L2 (default); BGE-M3 vectors are L2-normalized so L2 == cosine
ranking. No `nprobes` / `refine_factor` tuning at Tier-0; use
defaults.

**Decision:** Standard LanceDB search; two calls (one per column).

## D11 — Validator is NOT called inside the test

**Both briefs agree.** R1: *"The validator already ran in `make
test`; re-running it inside the eval test is redundant."* The eval
test just `json.loads()` the fixture and iterates queries.

**Decision:** No call to `validate_eval_fixtures.validate()` from
the eval test.

## D12 — Conftest `pytest_addoption` for `--ndcg-min`

**Both briefs agree.** Standard pytest hook. Code:

```python
def pytest_addoption(parser):
    parser.addoption("--ndcg-min", action="store", default=0.70, type=float)
```

Tests read via `request.config.getoption("--ndcg-min")`. The
`--ndcg-min=0.50` AC2 path tests a real failure assertion: a
`pytest.fail()` inside the test if `ndcg5_mean < threshold`.

**Decision:** Add `pytest_addoption` to existing `tests/conftest.py`.
Pass into the test as a fixture `ndcg_min(request)` for clean
indirection.

## D13 — How to test the threshold-failure path (AC2)

The brief's AC2 says *"`pytest --ndcg-min=0.50` fails if nDCG@5 is
below 0.50 (threshold enforcement verified in test)"*. This means
the implementation must include a test that confirms the
`pytest.fail()` fires when the threshold is not met.

**Decision:** Cannot literally invoke the retrieval test against a
real-but-bad corpus (no corpus exists). Lock the threshold-failure
path with a unit test against a synthetic per-query results list
that artificially produces `ndcg5_mean = 0.3`; assert that the
threshold-check helper raises (or returns False if we factor it
out). Add a separate `test_metrics.py::test_threshold_check_*`
case. The actual `test_retrieval_quality.py` test then trusts the
helper.

## D14 — Single source of truth for `EMBEDDING_DIM` / `CHUNKS_TABLE_NAME`

R2 calls this out specifically. Existing constants:
- `EMBEDDING_DIM = 1024` lives in `ingest/embedder.py` (and re-exported
  via `ingest/schema.py`).
- `CHUNKS_TABLE_NAME` lives in `ingest/store.py`.

**Decision:** Import these from their canonical homes; never
literalize `1024` or `"chunks"` in the test or metrics code. Add a
single-source-of-truth scan test if the literal would otherwise
proliferate.

## D15 — Test runtime budget (AC: under 120s)

Per the brief AC: *"Test runtime under 120 seconds for 20 queries
against 50-paper corpus."* On a 50-paper corpus (~1K chunks), each
ANN top-10 is sub-millisecond; the bottleneck is the BGE-M3 query
encode (~50–200ms per query on CPU, faster on GPU). 20 queries × 2
encodes (no — encode once per query, 2× search) = ~4 sec encode +
~40ms search. Total well under 120s.

**Risk:** if `encode_query` cold-loads the model on first call (per
E03_S03's lazy-load), the first call could add 5–30s. The test runs
once per `make test`; 30s + 4s + write = well under 120s. No
optimization needed at Tier-0.

## D16 — Where the eval result files actually go

Brief: `var/arxmcp/ops/eval/results-<corpus_version>.jsonl` and
`aggregate-<corpus_version>.json`. Both researchers note: do NOT
autouse-patch this directory in `conftest.py`. The eval result IS
the production audit artifact (drift baseline for E11_S04).

But: the threshold-failure unit test in `test_metrics.py` MUST NOT
write to the real path. Resolution: the unit tests against
`metrics.py` operate on Python lists; no filesystem touch. The
retrieval-quality test that DOES write the files only runs in the
`(corpus + queries)` complete-state cell of D1; in the cold-start
cells it skips before any write.

## File layout

```
tests/eval/metrics.py          # NEW: ndcg_at_k + recall_at_k pure fns
tests/eval/test_metrics.py     # NEW: unit tests for metrics
tests/eval/test_retrieval_quality.py  # NEW: end-to-end harness
tests/conftest.py              # APPEND: pytest_addoption(--ndcg-min)
                               # APPEND: ndcg_min fixture
```

No changes to `tests/eval/__init__.py`, `tests/eval/fixtures/__init__.py`,
or `pyproject.toml`. No new dependencies (numpy, lancedb, pytest already
in tree).

## Open questions (residual)

**None blocking implementation.** Both researchers raised the same
four open questions and gave aligned, opinionated answers. The
synthesis above locks each.

The "what shape should `aggregate-<corpus_version>.json` have"
question is answered by the brief verbatim:
`{corpus_version, ndcg5_mean, recall10_mean, query_count, timestamp}`.
Both briefs agree this stays at exactly 5 keys (alphabetical:
`corpus_version, ndcg5_mean, query_count, recall10_mean, timestamp`).

## External writes the implementation will require

Combined and deduped from both briefs:

| type | target | why | blocking? |
|---|---|---|---|
| filesystem write (in-tree) | `tests/eval/metrics.py` | pure-fn nDCG + Recall | no |
| filesystem write (in-tree) | `tests/eval/test_metrics.py` | unit tests for metrics | no |
| filesystem write (in-tree) | `tests/eval/test_retrieval_quality.py` | end-to-end harness | no |
| filesystem write (in-tree) | `tests/conftest.py` (modified) | `pytest_addoption(--ndcg-min)` + fixture | no |
| filesystem write (var/, runtime only) | `var/arxmcp/ops/eval/results-<v>.jsonl` | per-query results (gitignored; only on real-corpus runs) | no |
| filesystem write (var/, runtime only) | `var/arxmcp/ops/eval/aggregate-<v>.json` | drift baseline (gitignored; only on real-corpus runs) | no |

**No git push, no PR, no ticket, no infra mutation, no third-party
API call.** The milestone is purely local. Phase 4's external-write
gate has nothing to authorize.

The runtime `var/` writes happen ONLY when the user has a populated
LanceDB corpus AND a curated `queries.json`; on a cold-start dev
box (the current state) the test skips and nothing is written.
