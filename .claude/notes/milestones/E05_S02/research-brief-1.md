# E05_S02 — Research Brief 1

Milestone: nDCG@5 + Recall@10 measurement. Target deliverables:
`tests/eval/test_retrieval_quality.py`, `tests/eval/metrics.py`, a
`--ndcg-min` pytest option in `tests/conftest.py`, and side-effect
writes to `var/arxmcp/ops/eval/results-<corpus_version>.jsonl` +
`aggregate-<corpus_version>.json`.

## 1 — In-codebase context

**Apply notes:** `05-storage-and-indexing.md` (retrieval design and
"the durable index uses BGE-M3, end-to-end" rule), `06-mcp-server-design.md`
(byte-stable result canonicalization), `07-multi-agent-caching.md`
(BP1 byte-stability for prompt-cached artifacts; this milestone's
`results-*.jsonl` is OUTSIDE that scope but `aggregate-*.json` keys
must still be alphabetical), `08-security-observability-ops.md`
(Threat 1 path-traversal still relevant — but `lancedb_path` is
config-derived here, not tool-input). `09-feature-priorities.md` is
SUPERSEDED but still cited for the Tier-0 → Tier-1 gate; the live
authority is `.claude/roadmap/E05-eval-harness.md` (read in full).

**Load-bearing constraints from `05-storage-and-indexing.md`:**

> "**Hard rule:** `BAAI/bge-m3` is the sole embedder for arXMCP v1,
> used for both corpus indexing and query-time encoding."

> "Distance type left at the LanceDB default (l2); BGE-M3 vectors are
> L2-normalized so l2 and cosine produce identical rankings."
> (`ingest/store.py:_create_indices` docstring)

> "Retrieval fuses both via Reciprocal Rank Fusion at query time over
> `embedding_stmt` ANN and `embedding_proof` ANN results."

The brief overrides RRF for THIS milestone with "merged and sorted by
score, deduped by `chunk_id`" — a simpler concat+max merge. RRF is
deferred to E07.

**`server/query_encoder.py`** exposes `encode_query(query_text: str) ->
np.ndarray` (async, 1024-dim L2-normalized float32). Module docstring
asserts it matches `ingest.embedder._encode_batch` exactly — same SHA,
same CLS-pool + L2-norm chain. **The eval test must `await
encode_query(...)`** — implies `pytest-asyncio` (already a dep? must
verify) OR wrap with `asyncio.run()`. Test calls one query at a time;
no concurrency benefit. Use `asyncio.run(encode_query(q))` per query.

**`server/corpus.py:open_chunks_table(lancedb_path=None, version=None)`**
returns a fresh handle pinned via `tbl.checkout(N)`. Returns standard
LanceDB `Table` with `.search(...)`, `.to_arrow()`, `.count_rows()`.

**`server/corpus.py:read_corpus_version(lancedb_path=None) ->
CorpusVersionInfo | None`** returns `None` for absent marker
(cold-start) and raises `ValueError` for malformed. The dataclass has
`.version: int` which is the LanceDB int we pin to.

**`ingest/store.py`** owns `DEFAULT_LANCEDB_PATH = REPO_ROOT / "var" /
"arxmcp" / "index" / "lancedb"`. The schema (`ingest/schema.py`)
defines `embedding_stmt` and `embedding_proof` as
`pa.list_(pa.float32(), 1024)` — both nullable; rows have at most one
populated.

**`tools/validate_eval_fixtures.py`** is the fixture loader. Public API
is `validate(fixture_path, chunks_dir) -> ValidationResult`; result has
`.mode in {"seed", "complete"}`, `.query_count`. Importable. **For
E05_S02 we DO NOT call `validate()`** — we just `json.loads()` the
fixture and iterate `data["queries"]`. The validator already ran in
`make test`; re-running it inside the eval test is redundant.

**Existing `tests/conftest.py` patterns:** two autouse fixtures
(`_patched_store_stats_path`, `_patched_bm25_stats_path`) redirect
ops-log paths to `tmp_path`. Both wrap import in try/except so absent
deps no-op the patch. For E05_S02 we must add a third: redirect the
`var/arxmcp/ops/eval/` directory to `tmp_path` IN ALL TESTS EXCEPT THE
RETRIEVAL-QUALITY TEST ITSELF (or never autouse it — see Open Q (b)).
The brief says results are "written, not committed" — i.e., they go
under `var/` as a real artifact. **Do NOT autouse-patch the eval
directory.** The eval test writes to the real `var/arxmcp/ops/eval/`
because those files are the drift-detection baseline E11_S04 reads.

**Conftest pytest hooks:** the `--ndcg-min` option goes via
`pytest_addoption(parser)` at the top of `tests/conftest.py`, exposed
via a fixture `ndcg_min(request) -> float` reading
`request.config.getoption("--ndcg-min", default=0.70)`.

**LanceDB ANN API** (from `tests/test_store.py` + the `tbl.search`
docs comment in `server/corpus.py`):
```python
results = (
    tbl.search(query_vector, vector_column_name="embedding_stmt")
       .limit(10)
       .to_arrow()
)
```
The Arrow result includes a `_distance` column (l2 distance, lower =
closer). Convert to similarity via `score = 1 - dist/2` for normalized
vectors, OR just sort ascending on `_distance` and use the raw
distance as inverse-score.

## 2 — Prior decisions and lessons

**E05_S01 user-blocked / data-blocked split (this milestone is the
SAME pattern, even more strongly).** From E05_S01 implementation
summary: *"3 of 7 [ACs] are user-blocked (the curation pass)."* For
E05_S02, **all** ACs except the one demanding `metrics.py` unit tests
and the conftest plumbing are blocked on TWO data states:

  1. The 20-query fixture must be populated (E05_S01 ships it as
     `queries: []`; the user has not curated yet).
  2. The 50-paper seed corpus must be ingested (chunked + embedded +
     written to LanceDB). `var/arxmcp/index/lancedb/` does not exist
     in the current worktree (only `var/arxmcp/ops/parser-failures/`
     is present).

**Lift the E05_S01 behavior matrix.** Define a 3×N matrix:

| `read_corpus_version()` | `len(queries)` | Test behavior |
|---|---|---|
| `None` (no marker) | 0 | SKIP `"both pending"` |
| `None` | 20 | SKIP `"corpus not ingested"` |
| `CorpusVersionInfo` | 0 | SKIP `"queries not curated"` |
| `CorpusVersionInfo` | 20 | RUN: encode → ANN × 2 cols → merge → score → assert |

Skipping (not failing) is the right call: a cold-start `make test`
shouldn't redden over user-blocked data. The pytest pattern is
`pytest.skip("...")` early in the test body. **The exit-gate command
in `TIER-GATES.md` (E05_S03) is what enforces "this MUST run and pass"
— the test itself stays SKIP-friendly so `make test` is green on a
fresh checkout.**

**BP1 (07-multi-agent-caching.md):** "JSON keys serialized in
alphabetical order. No timestamps, no random tie-breaks." The brief
explicitly puts `timestamp` in `aggregate-*.json` — but per the
prompt's framing, "it's NOT cache-keyed" so this is fine. Mirror
`ingest/store.py:write_corpus_version_marker` discipline:
`json.dumps(..., sort_keys=True, ensure_ascii=False)` plus atomic
write via `tmp + os.replace()` (copy from `ingest/preamble.py`'s
`_write_preamble_json`). The `results-*.jsonl` is line-per-query and
each line should also be `sort_keys=True`.

**Recent hardening pattern from E04_S01–S03 critiques:** narrow
exception handling, structured `dict` ops payloads, atomic writes via
PID+UUID-suffixed tmp + `os.replace`. Every recent commit has a
"close N MEDIUMs from Phase 3 critique" footer — the implementer
should expect the critic to flag: (a) non-atomic writes,
(b) empty-corpus crash paths, (c) NaN/0 division in nDCG when there
are no relevant chunks, (d) `bool` masquerading as `int` in relevance,
(e) `_distance` vs cosine confusion.

**Past pattern: `tmp_path` + monkeypatch for stats files.** Already
landed in `tests/conftest.py`. For `metrics.py` unit tests, no
filesystem touched at all — pure functions on lists.

## 3 — External sources

**nDCG canonical formula.** Two gain conventions exist:
- **Linear gain** (the brief): `gain_i = rel_i`, `DCG@k = Σ_{i=1..k}
  rel_i / log2(i+1)`. This is Järvelin & Kekäläinen (2002, original).
- **Exponential gain** (TREC, sklearn default): `gain_i = 2^rel_i - 1`,
  `DCG@k = Σ (2^rel_i - 1) / log2(i+1)`. Used by `sklearn.metrics
  .ndcg_score`.

**The brief is unambiguous: linear.** *"DCG@5 = Σ (rel_i / log2(i+1))
for i=1..5, normalized by ideal DCG@5."* Implement linear; do NOT use
`sklearn.metrics.ndcg_score` (it would silently apply exponential
gain). Rolling our own is ~15 LOC and zero deps. Confirms D7 from
E05_S01 ("pure-Python validator, no jsonschema dep") — same
discipline.

For `i=1..5` indexing convention: the discount denominator is
`log2(i+1)` so position 1 → `log2(2)=1`, position 2 → `log2(3)`. Use
`math.log2`.

**iDCG@5** is computed from the sorted-descending ground-truth
relevances of the query, truncated to 5. If a query has fewer than 5
relevant chunks, pad with zeros (no ideal gain at those ranks).

**iDCG = 0 edge case.** If a query has no positive-relevance chunks
(all 0s), iDCG = 0 → division by zero. The brief's E05_S01 fixture AC
says *"At least one grade-3 chunk_id must exist per query"* — so iDCG
> 0 always holds. Defend with an assertion anyway and treat
iDCG == 0 as nDCG = 0 (not NaN).

**Recall@10 canonical formula.** From the brief:
> "fraction of grade-3 ('highly relevant') chunks for each query that
> appear in the top-10 ANN results, averaged over all queries."

`recall@10 = |grade3_relevant ∩ top10_retrieved| / |grade3_relevant|`.
Note: only grade-3 counts toward the denominator — grade-1/2 chunks
are ignored for Recall, even though they contribute to nDCG. This
asymmetry is intentional per brief.

**LanceDB `Table.search()` API** (verified against
`tests/test_store.py` + `server/corpus.py:117` docstring claim
*"`search`, `schema`, `version`"*):
```python
result_arrow = (
    tbl.search(np_vec, vector_column_name="embedding_stmt")
       .limit(10)
       .to_arrow()
)
chunk_ids = result_arrow.column("chunk_id").to_pylist()
distances = result_arrow.column("_distance").to_pylist()
```
Two calls (one per column), then merge by chunk_id taking MIN distance
(equivalently MAX similarity). See Open Q (c).

**sklearn `ndcg_score` IS NOT what we want** despite being the
"canonical" reference: it (a) uses exponential gain and (b) requires
parallel y_true / y_score arrays the same length as the document set,
which is awkward when most docs are unlabeled. Roll our own.

## Open questions (resolved with opinions)

**(a) Cold-start behavior — SKIP, error, or pass?** SKIP. Implement
the 4-cell behavior matrix above and call `pytest.skip("corpus not
ingested" / "queries not curated" / "both pending")` with the message
that names which gate is open. Acceptance criterion 1 ("--ndcg-min=0.70
passes on the 50-paper seed corpus after E03 and E04 are complete") is
phrased conditionally; AC2 ("--ndcg-min=0.50 fails if nDCG@5 below
0.50") only applies once the test runs. Skipping on absent data
preserves a green `make test` on a cold-start dev box (matches the
E05_S01 "seed mode warns and exits 0" precedent). The Tier-0 exit gate
(E05_S03's `TIER-GATES.md`) is what asserts these inputs exist before
running.

**(b) `metrics.py` location — `tests/eval/` or production code?**
**`tests/eval/metrics.py`.** The brief says "Metric computation
utilities in `tests/eval/metrics.py`." The functions are pure
(`ndcg_at_k(retrieved, ground_truth, k) -> float`,
`recall_at_k(retrieved, ground_truth_set, k) -> float`) so they're
trivially testable from `tests/eval/test_metrics.py` (a sibling).
Production code (the eventual `search_papers` MCP tool, E06) does NOT
need to compute nDCG at request time — it's only used by the eval
harness and the future drift watchdog (E11_S04, which can import from
`tests/eval/metrics.py` via path injection or duplicate the ~30 LOC).
If the watchdog needs a non-test home later, promote the module then.
**Do not over-engineer for a forward dep that may never need it.**

**(c) Dedup semantics: stmt-top10 score 0.9 + proof-top10 score 0.85
for same chunk X — max, sum, or first-wins?** **Take MIN distance
(equivalently MAX similarity).** Rationale: the two columns embed two
DIFFERENT representations of the chunk (statement-only vs
statement+proof-window) into the SAME 1024-dim BGE-M3 space. A high
score on either column is genuine evidence the chunk is relevant.
Summing scores would double-count chunks that happen to be in both
top-10 lists (only possible when a chunk has BOTH `embedding_stmt`
AND `embedding_proof` populated — but per the schema and the routing
rule in `ingest/store.py:_build_arrow_table`, exactly one of the two
embeddings is populated per chunk). **In practice the dedup is
trivial because no chunk can appear in both result sets** — the
proof-rows are disjoint from the stmt-rows (NULL embedding columns
get filtered out of LanceDB ANN). The dedup-by-chunk_id step is
defense-in-depth against future schema changes; MAX-similarity is the
right default. Implement it as: build a `dict[chunk_id, distance]`
keeping the smaller distance, then sort and take top 10.

**(d) Aggregate-file timestamp format?** **ISO-8601 UTC with `Z`
suffix**, mirroring `ingest/store.py:write_corpus_version_marker`'s
`datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")`. Rationale: that
is the project's established timestamp idiom (also in
`embed-stats.jsonl`); ISO-8601 is human-greppable and machine-parsable;
the brief explicitly schemas `{timestamp}` so it must be present;
the file is NOT cache-keyed so BP1 timestamp-prohibition does not
apply. Epoch ints would force every consumer to re-format. **Do not
omit the timestamp** — E11_S04's drift watchdog needs to know which
of N aggregate files is freshest if multiple corpus_versions accumulate
on disk.

## External writes the implementation will require

| type | target | why |
|---|---|---|
| filesystem write | `tests/eval/test_retrieval_quality.py` | new pytest test (the milestone deliverable) |
| filesystem write | `tests/eval/metrics.py` | pure-function nDCG + Recall utilities |
| filesystem write | `tests/eval/test_metrics.py` | unit tests locking metrics.py contracts |
| filesystem write | `tests/conftest.py` | append `pytest_addoption(--ndcg-min)` + `ndcg_min` fixture |
| filesystem write (runtime, on test execution only) | `var/arxmcp/ops/eval/results-<corpus_version>.jsonl` | per-query JSONL output (atomic via tmp+rename); created only when test runs (i.e., corpus + queries present) |
| filesystem write (runtime, on test execution only) | `var/arxmcp/ops/eval/aggregate-<corpus_version>.json` | aggregate metrics; created only when test runs |

**No git push, no PR creation, no ticket, no infra mutation, no
third-party API call.** The milestone is purely local. The two `var/`
files are first-time additions to the `var/arxmcp/ops/eval/` directory
(which does not yet exist); `mkdir(parents=True, exist_ok=True)` at
write time. The directory and its contents are gitignored under
`var/`. The next external write the project does is whatever Tier-1
work follows; nothing in E05_S02 reaches outside the worktree.
