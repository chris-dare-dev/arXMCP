# E07_S01 — BM25Phase research brief (Researcher 2)

## 1. In-codebase context

**BM25 index storage.** A pickle of `rank_bm25.BM25Okapi` plus a row-aligned
`chunk_ids.json` sidecar, **not** a LanceDB FTS index. Built by
`ingest/bm25_indexer.py:225-393` (`build_bm25_index`) and persisted at
`var/arxmcp/index/bm25/v<N>/{bm25.pkl, chunk_ids.json}` via the
`_bm25_version_dir(corpus_version)` helper at line 108. `bm25.pkl` is
`pickle.HIGHEST_PROTOCOL` of the fitted `BM25Okapi(corpus)` object;
`chunk_ids.json` is a JSON array of `chunk_id` strings, ordered to match
the in-pickle corpus rows. Re-confirmed by tests at
`tests/test_bm25.py:230-237` which load both and assert
`bm25.corpus_size == len(chunk_ids)`. **There is no LanceDB FTS index** —
no `create_fts_index` call exists anywhere in `ingest/` or `server/`
(verified via grep). The brief's wording about "LanceDB scalar + FTS
predicates" is aspirational design language that does not match what
shipped in E04_S04.

**Chunks-table schema (the load-bearing surprise).**
`ingest/schema.py:69-118` declares only these columns:
`chunk_id, paper_id, kind, section_path, theorem_name, theorem_label,
body_text, body_tokens, embedding_stmt, embedding_proof, embedding_eq,
chunker_version, embedder_version, preamble_ref`. **None of
`categories`, `year_min`, `year_max`, `authors`, `include_withdrawn`
exist on the chunks table.** The E06_S03 synthesis (line 28) calls this
out explicitly: "no metadata source today" — `get_paper` returns
`null` for all of them. The `papers` metadata table proposed in
E06_S03 brief 1 (line 105) was deferred and has not been built. So the
brief's AC `BM25Phase.query("\\Spec", filters={"categories": ["math.AG"]})`
**cannot be satisfied as written** — the predicate column does not
exist. See Open Questions.

**`body_tokens` shape.** `pa.field("body_tokens", pa.utf8(),
nullable=False)` — a single whitespace-joined string per row
(`schema.py:86`). `rank_bm25` expects a `list[list[str]]` corpus and a
per-query `list[str]`; the bridge is `body.split()` performed at index
build time (`bm25_indexer.py:340`) and again at query time
(`bm25.get_scores(query.split())` per `tests/test_bm25.py:274`). There
is no `body_canonical` column despite the brief's fallback note —
`body_text` is the closest analog (the macro-expanded canonical body;
see design note `05-storage-and-indexing.md:38`). The fallback path is
unreachable as written.

**Existing test pattern.** `tests/test_bm25.py:77-120` (`_curated_corpus`)
builds 20 synthetic ChunkRecords with hand-crafted `body_tokens`
strings, writes them via `write_chunks` to a `tmp_path` LanceDB, calls
`build_bm25_index`, then loads `bm25.pkl` + `chunk_ids.json` directly
and queries with `bm25.get_scores(["Spec", "mathrm_Pic"])`. This is
exactly the pattern E07_S01 tests should reuse — it is fast (no model),
deterministic, and exercises the production read path.

**Search handler integration seam.** `server/handlers/search.py:104-117`
is the dense-only ANN path. It calls `r = get_resources()`, then
`r.chunks_table.search(query_vec, vector_column_name="embedding_stmt")
.limit(...)`. The E07_S02 fusion will need `BM25Phase.query(...)` to
return `list[tuple[str, float]]` so RRF can interleave it with
ANN results. Recommendation: keep the BM25 return shape as stated in
the brief (`list[tuple[str, float]]`) — it is the same shape ANNPhase
will produce and matches `rrf.reciprocal_rank_fusion`'s expected input
per E07_S02 brief.

**Resources singleton.** `server/resources.py:209-326` (`Resources`
dataclass + `startup`). Add a `bm25_phase: BM25Phase` field
(populated after step 2, before step 5). `Resources.shutdown()` at
line 328-349 currently only un-warms and drains the BGE-M3 executor;
add a no-op or `bm25_phase = None` clear there — the pickle is loaded
into RAM, no file handle to close.

**`ingest/bm25_indexer.py` artifact lifecycle.** `build_bm25_index`
(line 225) is the build side; **eager** load of the entire
`BM25Okapi` object into memory via `pickle.dumps(bm25,
protocol=pickle.HIGHEST_PROTOCOL)` at line 374. The artifact is
process-private — no shared-memory or mmap. The E04_S04 critique
(`critique-adversary.md` H1) flags that **nothing currently calls
`build_bm25_index` from production code paths**: "After `write_chunks`
succeeds, nothing builds the BM25 index. E07 will load `bm25.pkl` from
a directory that may not exist." The implementer must either invoke
`build_bm25_index` from a startup hook or document that ingest must
run it manually before server startup.

## 2. Prior decisions and lessons

**E04_S04 shipped only `body_tokens`, not `body_canonical`.** Confirmed
via `schema.py:81-86` — only `body_text` (canonical macro-expanded) and
`body_tokens` (whitespace-joined token stream) exist. The brief's
fallback "to the prose `body_canonical` BM25 index" is for an
artifact that does not exist. If the `body_tokens` index is missing,
the only fallback is to tokenize `body_text` on the fly into a fresh
in-memory `BM25Okapi` — recommend logging WARNING and raising rather
than silently degrading.

**rank_bm25, not LanceDB FTS.** `pyproject.toml:71` pins
`"rank-bm25>=0.2"`; no `tantivy` dep exists. Per
`research-synthesis.md` D1 (E04_S04): "A 30-line custom implementation
introduces fresh correctness risk … for no benefit at Tier-0." The
shipped indexer is `BM25Okapi(corpus, k1=1.5, b=0.75)`. The brief's
"LanceDB supports combined scalar + FTS predicates" is fiction at
this codebase layer. **BM25Phase must scan the in-memory pickle and
post-filter against LanceDB scalar columns separately** (see Open
Questions).

**E04_S04 critique lessons.** From `critique-adversary.md`:
- H1: "build_bm25_index has zero production call sites." The
  implementer should either auto-build at server startup if
  `bm25.pkl` is missing for the pinned `corpus_version`, OR fail-fast
  with a clear error message.
- M1: "Pickle threat-model is documented, not enforced." The
  `bm25_indexer.py:62-70` docstring mandates the loader "verify file
  ownership matches process UID and refuse world-writable paths
  before calling `pickle.load`." `BM25Phase.__init__` MUST honor this.
- L4 lesson: idempotent skip leaves count fields at 0 — irrelevant for
  the loader but a reminder that the artifact is the single source of
  truth.

**Top-200 cap.** Brief states `top_n=200` as default. Per
`05-storage-and-indexing.md:323-325` ("Take top-200") this is the
canonical Phase-1 candidate count, with E07_S02 then reducing to top-50
via RRF. Make `top_n` a kwarg (default 200) so eval tests can vary it.

**Performance pin.** `BM25Okapi.get_scores(query)` returns a numpy array
of length `corpus_size` (~250-1000 for the 50-paper seed corpus per
`E01_S01-S03` summary). Cost is O(N · |query|) per call — a few ms
even at corpus_size=10K. The 500ms AC is **trivially met IFF the
pickle is loaded ONCE at startup**. The failure mode to avoid is
re-`pickle.load`-ing on every query (would add ~100ms+ for a 100K-row
corpus). Recommendation: load `bm25.pkl` + `chunk_ids.json` exactly
once in `BM25Phase.__init__`, cache as instance attributes,
`asyncio.to_thread`-wrap `get_scores` since it is CPU-bound numpy.

## 3. External sources

**rank_bm25** (https://github.com/dorianbrown/rank_bm25): `BM25Okapi`
is the right variant (defaults k1=1.5, b=0.75). API: `get_scores(query:
list[str]) -> np.ndarray`, `get_top_n(query, documents, n)` (we don't
use the latter — we want chunk_ids, not corpus rows). Thread safety:
**`get_scores` is read-only after construction**; multiple greenlets/
threads can call it concurrently. No locking required — closes the
brief's "thread-safe for concurrent reads" requirement.

**LanceDB FTS** (https://lancedb.github.io/lancedb/fts/): Not used by
the codebase. Mentioned for reference only — would be the natural
implementation if E04_S04 had taken that path. Switching now is
out-of-scope for E07_S01; keep `rank_bm25`.

**Cache contract** (`07-multi-agent-caching.md:132-134`): "do not
lowercase, do not strip punctuation. `\'etale` and `étale` produce
different lexical matches." The brief's byte-faithful constraint
maps directly: pass the raw query string to `BM25Phase.query`, do
nothing more than `.split()` (Python default whitespace split, which
preserves Unicode and backslashes).

## Open questions

1. **The `categories`/`year_min`/`year_max`/`authors`/`include_withdrawn`
   filter columns do not exist on the LanceDB chunks table.** The brief
   AC `BM25Phase.query("\\Spec", filters={"categories": ["math.AG"]})`
   cannot return "only math.AG chunks" because no chunk knows its
   category. Three options the implementer must pick from before
   coding:
   (a) Accept `filters` arg, ignore non-existent fields, surface a
   `filter_warnings` field analogous to `search.py:133-141`. Test the
   AC by skipping the assertion or marking `xfail` until a `papers`
   table lands.
   (b) Block on building a minimal `papers` metadata table — out-of-
   scope per the "tier-0 only Sonnet A's E04_S04" dependency line.
   (c) Restrict `filters` v1 to fields actually present on chunks
   (`paper_id`, `kind`) and document `categories` etc. as deferred.
   **Recommendation: (a)** — matches E06_S03 F6 precedent
   (`search.py:133`) and unblocks the BM25 phase. Update the AC to
   match reality: assert `filter_warnings` is non-empty when
   unimplemented filters are passed.

2. **Where does `build_bm25_index` get invoked in production?** The
   E04_S04 H1 finding is unresolved. Recommended: `BM25Phase.__init__`
   calls `build_bm25_index(lancedb_path, corpus_version)` if the
   per-version files are missing — leverages the existing idempotent-
   skip behavior so warm starts pay nothing.

3. **Filter interaction with BM25 ranking.** Two valid orderings:
   (a) Compute BM25 over the full corpus, take top-N candidates, then
   filter by scalar predicates (post-hoc). Loses candidates if
   filters are restrictive.
   (b) Filter chunk_ids to a subset first, then compute BM25 over only
   those rows. Requires re-fitting `BM25Okapi` per-query — IDFs change
   with subcorpus → expensive (~100ms+).
   **Recommendation: (a)** — over-fetch (e.g. `top_n * 4 = 800` from
   BM25), then post-filter, then truncate to `top_n=200`. Matches
   `search.py:115` over-fetch pattern.

## External writes the implementation will require

None. This milestone is purely internal:

- `server/retrieval/bm25.py` — new file (`BM25Phase` class)
- `server/retrieval/__init__.py` — new package marker
- `tests/retrieval/test_bm25.py` — new file
- `tests/retrieval/__init__.py` — new package marker
- `server/resources.py` — add `bm25_phase` field + startup wire-up

No git push, PR creation, ticket movement, infra mutation, or third-
party API call required. The implementation reads `var/arxmcp/index/
bm25/v<N>/` (already produced by E04_S04's build path) and writes
nothing at runtime.
