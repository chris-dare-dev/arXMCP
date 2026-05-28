# Spike: maximal-accuracy fork analysis — notebook-retrieval-m1

**Date:** 2026-05-27
**Mode:** READ-ONLY analysis. No code changed.
**Question the operator posed:** for *maximal retrieval accuracy off the bat*,
does Fork A (lazy per-call notebook resources) lose accuracy vs Fork C (eager
`ARXMCP_NOTEBOOK` startup warming)? And — deeper — is a per-notebook-isolated
index better or worse than a shared mega-corpus + `filters.paper_id` scoping?

---

## 1. Verdict up front

- **Fork A does NOT lose meaningful retrieval accuracy vs Fork C.** The live
  `search_papers` path is **dense-only ANN over `embedding_stmt`** — it never
  calls `BM25Phase`, `ANNPhase`, or `RerankPhase` (verified: those `.query()`
  methods have zero non-test callers in `server/handlers/`). The only
  accuracy-relevant warmup that the eager path does — BGE-M3 weights load — is
  a **process-wide singleton shared across all notebooks** (`server/query_encoder.py`),
  so it is paid once regardless of fork. There is no per-notebook ANN
  index *build* at startup (the HNSW indices were built at ingest); startup
  only *opens* a handle. Cold-start "degradation" is therefore latency-only
  (first-query model load + LanceDB open), not a ranking-quality difference.
- **Per-notebook-isolated index IS the maximal-accuracy architecture** — and
  it is what both forks already deliver. It is *equivalent in recall* to
  shared-corpus-with-prefilter (because arXMCP already pushes the filter INTO
  the ANN scan via `prefilter=True`, `search.py:484`), and *strictly better
  than shared-corpus-with-post-filter* (which arXMCP does NOT use). So there
  is no recall left on the table.
- **Per-notebook BM25 IDF is moot for accuracy** because BM25 is not on the
  live retrieval path at all — and the one place it was measured, BM25 fusion
  *regressed* top-1 by 10 points on these exact notebooks (the shared-vocabulary
  IDF problem). Do not add it for accuracy.
- **Reranker is architecture-neutral AND off by default** for a measured reason:
  it produced **zero precision lift and a −10pt top-1 regression at 122× latency**
  on the bridgeland+shimura fixtures (`wiring-rerank-lift-100paper/note.md`).
- **Recommendation: Fork C (eager `ARXMCP_NOTEBOOK`) for m1 is already
  maximal-accuracy.** The choice between Fork C and Fork A is **purely
  operational** (one-notebook-per-process vs many-per-process), not an accuracy
  trade. Pick Fork C for m1 as the synthesis already resolved; it loses nothing
  on quality.

---

## 2. Fork A lazy vs Fork C eager — the accuracy delta

The eager path is `Resources.startup` (`server/resources.py:282-689`). Walking
it for *accuracy-relevant* work (as opposed to latency-relevant):

| startup step | accuracy-relevant? | shared across notebooks? |
|---|---|---|
| `read_corpus_version` (`:306`) | no (a version pin) | n/a |
| `open_chunks_table_with_fallback` (`:332`) | **yes — degraded fallback** (see below) | no (per-notebook handle) |
| `_get_tokenizer` / `_get_model` BGE-M3 (`:357-358`) | yes (the encoder) | **YES — module singleton** |
| reranker load + warmup (`:363-494`) | only if `enable_rerank` (default off) | yes |
| `BM25Phase.startup` (`:387`) | yes IF BM25 were on the path — **it is not** | global pickle, version-keyed |
| `ANNPhase(chunks_table)` (`:404`) | constructor is *cheap* — caches the table ref + probes which embedding columns have rows (`ann.py:280`); **does not build an index** | no |
| `RetrievalCache.open` (`:505`) | performance, not correctness | per-process |

**The decisive fact:** the live handler `handle_search_papers` (`search.py:294-583`)
does its own `r.chunks_table.search(query_vec, vector_column_name="embedding_stmt")`
at `:480` and **never touches `r.bm25_phase` / `r.ann_phase` / `r.rerank_phase`**.
So the BM25 warming and the ANNPhase column-probe at startup are dead weight on
the live retrieval path — a lazy fork that skips them loses *nothing*. (They
matter only for the `tests/eval` harness and the unwired E07_S04 orchestrator.)

What a lazy fork must replicate to be accuracy-equivalent:

1. **Open the right LanceDB handle** at the notebook's pinned `corpus_version`.
   Trivial; same `open_chunks_table_with_fallback` call.
2. **Share the BGE-M3 singleton** — do NOT open a second encoder. Both research
   briefs flag this (`query_encoder.py` module-level). A lazy fork that
   accidentally re-instantiated the encoder would waste ~1.5 GB but would NOT
   change ranking (same weights). So even the worst lazy mistake here is a
   latency/memory bug, not an accuracy bug.

**Cold-start window analysis.** With lazy loading, the FIRST query against a
new notebook pays: BGE-M3 load (only if not already warm from another notebook —
but it is a shared singleton, so warm after the first query to *any* notebook)
+ LanceDB open (~tens of ms) + the LanceDB query itself. **None of these
degrade ranking.** There is no "ANN index not yet built" state, because the
HNSW index is a persisted artifact built at ingest (`ingest/store.py:592`,
`IVF_HNSW_SQ, num_partitions=1`), not a runtime build. The handle either opens
with the index present (indexed ANN) or, on a pre-index version pin, LanceDB
silently falls back to brute-force ANN over the same vectors — which for a
~50-paper / few-thousand-chunk notebook is **exact** (brute-force = perfect
recall), so even that fallback is accuracy-positive, just slower.

**The one real eager-path accuracy feature: the degraded fallback.**
`open_chunks_table_with_fallback` (`resources.py:332`) retries at `version-1`
on corruption and stamps a `DegradedState`. A lazy fork must call the *same*
helper, not a bare `open_table`, or it would crash instead of degrading
gracefully. This is a correctness/robustness parity requirement, not a ranking
delta — but it is the single startup behavior a lazy implementation could get
wrong. Flag it for the m2 implementer.

**Conclusion:** cold-start degradation is **negligible-to-nonexistent** for
ranking quality. The accuracy difference between Fork A and Fork C is zero;
the difference is operational (process lifecycle) and latency (first-query
warm cost), both of which the eval lens below does not even measure.

---

## 3. Per-notebook-isolated index vs shared-corpus + filter — the deep question

This is where "maximal accuracy" is actually decided, and the code already
resolves it in favor of isolation-or-equivalent.

### arXMCP uses a PRE-filter, not a post-filter

`search.py:472-489`:

```python
search_q = r.chunks_table.search(query_vec, vector_column_name="embedding_stmt")
if paper_id_predicate is not None:
    search_q = search_q.where(paper_id_predicate, prefilter=True)
arrow = search_q.limit(k * 5 if level != "theorem" else k).to_arrow()
```

`prefilter=True` pushes `paper_id IN (...)` **into** the ANN scan. LanceDB
restricts the vector search to the filtered subset BEFORE selecting the top-k.
The handler docstring (`:472-478`) names the exact failure mode it avoids:
"avoiding the postfilter case where a small filter set could leave fewer than
k results after corpus-wide ANN candidates are discarded." A `scalar_paper_id`
index exists (`store.py:602`) to make this prefilter efficient.

**This means the "shared mega-corpus + post-filter starves relevant chunks
before the filter applies" risk DOES NOT EXIST in arXMCP** — arXMCP never
post-filters. The shared-corpus-with-prefilter and the per-notebook-isolated
index are therefore **recall-equivalent**: in both, the ANN candidate pool IS
exactly the notebook's chunks. There is no global top-k bottleneck.

### Empirical confirmation (the prefilter spike)

`.claude/notes/spikes/lancedb-ann-where-composition/note.md` measured exactly
this on the bridgeland notebook:

- 10/10 returned chunks were inside the filter set (no leakage).
- Top-1 with the filter == top-1 without the filter (`0705.3794`) — the
  prefilter did not perturb ranking *within* the set.
- Filtered query was **~1.5 ms vs ~50 ms unfiltered** (30× faster — the filter
  shrinks the search space).

So prefilter-on-shared and isolated-index produce the same ranked rows.

### Are there downsides to a *tiny* isolated index? Investigated — no.

1. **ANN index params tuned for a large corpus underperforming on a small one.**
   Checked `ingest/store.py:592-599`: params are *fixed* (`IVF_HNSW_SQ`,
   `num_partitions=1`, `m=16`, `ef_construction=200`) and the docstring
   explicitly pins `num_partitions=1` as "the auto-promoted value for small
   corpora" that "does NOT require the 256-row minimum" (`store.py:23-27`). The
   notebook index and any shared index use the *same* params — there is no
   large-vs-small divergence. With `num_partitions=1`, HNSW degenerates toward
   a single graph over all vectors → effectively exhaustive-quality recall on a
   small set. **No downside; if anything, near-perfect recall.**
2. **IDF/BM25 statistics over a tiny corpus being non-discriminative.** Real
   concern *in general* — but BM25 is **not on the live path** (§4). Moot.
3. **Reranker candidate-set differences.** Off by default and measured-harmful
   (§5). Moot.

### Why isolation is also *qualitatively* preferable

`textbook-ingest-roadmap.md:41` ([MUST]) mandates notebook chunks live ONLY in
per-notebook lancedb, "never in the shared arXiv corpus … wrong means
`search_papers` defaults pollute the arXiv-only query semantics." A shared
mega-corpus would require every notebook query to carry a (possibly 50-element)
`paper_id IN (...)` predicate and would risk cross-notebook leakage on any code
path that forgets the filter. The isolated index makes leakage **structurally
impossible** — the wrong papers aren't in the index to begin with. For
"maximal accuracy" read as *precision against the intended scope*, isolation
is the safer ceiling.

**Section verdict:** per-notebook-isolated index (Fork C/A) is recall-equivalent
to shared+prefilter and strictly safer than shared+post-filter (which arXMCP
doesn't use anyway). It is the maximal-accuracy choice. There is no recall
sacrifice from isolating.

---

## 4. BM25 IDF-scope analysis

The question (per-notebook IDF over ~50 papers vs shared IDF over the whole
corpus, which is more accurate for an intra-notebook query) has two answers:

**Answer for the live path: it does not matter, because BM25 is not used.**
`handle_search_papers` is dense-only. `BM25Phase.query` (`bm25.py:529`) has no
caller in `server/handlers/`. The BM25 artifacts (`v369`, `v49`) exist and
`Resources.startup` loads them, but the handler never queries them.

**Answer if BM25 *were* wired (for completeness, and as a warning):** the
notebook's BM25 index was built at ingest over **only the notebook's chunks**
(`ingest/bm25_indexer.py` builds from the lancedb at the pinned version;
`bridgeland v369` = bridgeland chunks only). `BM25Phase.query` calls
`get_scores` over that loaded corpus (`bm25.py:571`) and post-filters by
paper_id (`:606`). So IDF is *already* notebook-scoped, not shared-scoped — and
that is the more-discriminating choice in principle (IDF computed over the
relevant population).

**But the measurement says notebook-scoped BM25 still hurts.** The 100-paper
spike (`wiring-rerank-lift-100paper/note.md:39-44, 82-89`) found that fusing
BM25 (notebook-scoped) into the dense ranking *regressed* top-1 from 0.850 to
0.750 — because within a topical notebook the core vocabulary ("stability
condition", "derived category") has near-uniform IDF *even when scoped to the
notebook*, so BM25 contributes rank-noise, and RRF blending degrades the clean
dense ranking. Narrowing IDF scope to the notebook does not rescue it; the
vocabulary is uniform at *both* scopes for a curated topical notebook.

**BM25 IDF-scope verdict:** for intra-notebook queries, notebook-scoped IDF is
the better of the two BM25 options, but **neither beats dense-only**. Do not
add BM25 for accuracy. (If a future need arises, the spike points at BGE-M3's
*sparse head* — same-model features, no IDF-on-narrow-vocab problem — as the
right investigation, not classic BM25.)

---

## 5. Reranker behavior

The reranker (`RerankPhase`) is **architecture-neutral** — it reranks whatever
candidate set it receives, and the candidate set for a notebook query (the
notebook's chunks) is identical under both forks. Confirmed off the live path
(no caller) and `enable_rerank=False` by default.

The candidate-set *quality* difference between architectures is nil (both feed
the notebook's chunks). The reranker's measured behavior on these notebooks is
the relevant caution: zero P@10 lift, −10pt top-1, 122× latency
(`retrieval-quality-report.md:18-29`). The cross-encoder is general-domain and
its scores compress when all candidates share specialized math vocabulary. So
the reranker is both architecture-neutral AND not worth enabling for accuracy.

---

## 6. The maximal-accuracy recommendation

**Fork C eager + per-notebook isolated index is already the maximal-accuracy
configuration, and Fork A would be accuracy-equivalent.** Concretely:

1. **Retrieval substrate:** dense-only ANN over `embedding_stmt`, BGE-M3 shared
   singleton, per-notebook HNSW index opened (not rebuilt) at the notebook's
   pinned `corpus_version`. This is what both forks deliver.
2. **Scoping:** isolation makes the candidate pool exactly the notebook —
   recall-equivalent to shared+prefilter, strictly safer than shared+post-filter.
3. **Do NOT add for accuracy:** BM25 fusion (measured −10pt top-1), the
   cross-encoder reranker (measured −10pt top-1, 122× latency). Both are
   net-negative on these notebooks.
4. **The fork choice is operational, not accuracy-driven.** Fork C = one
   notebook per process (simplest, makes the server bootable today, automatic
   cache isolation). Fork A = many notebooks per process (needs the cache-key
   slug fix + `SCHEMA_VERSION` bump). Choose on operator workflow; either
   yields identical ranked results.

Measured baseline this configuration achieves on the realistic eval lens
(bridgeland+shimura, 20 hand-labeled queries, `retrieval-quality-report.md`):
**Recall@10 = 0.936, top-1 hit rate = 0.850, ~55 ms/query.** Dense-only at the
*notebook-isolated* scale is the structural ceiling the project has measured;
nothing on the table improves it without a new encoder/architecture.

If the operator wants to push past 0.85 top-1 *later* (not m1), the spike's
ranked options are: (1) query reformulation + dense fusion (cheapest, no
arch change), (2) BGE-M3 sparse-head fusion (~3-day sub-spike), (3) math-domain
reranker, (4) ColBERT. None are m1.

---

## 7. Quantification gap

The accuracy claims here are **already measured**, not theoretical — the
100-paper spike ran the bridgeland `queries.json` (the exact rich fixture the
operator pointed at) under dense-only / hybrid / hybrid+rerank and recorded
per-query rows in
`.claude/notes/spikes/wiring-rerank-lift-100paper/measurements.json`. So the
deep architecture question (dense-only-isolated vs adding BM25/rerank) is
settled empirically on the right target.

What is **not** separately measured, and what would settle any residual doubt
about *Fork A vs Fork C specifically*:

- **Experiment:** run the bridgeland `queries.json` twice — once via a Fork C
  server (`ARXMCP_NOTEBOOK=bridgeland-stability`) and once via a Fork A lazy
  per-call path — and diff the ranked `chunk_id` lists per query.
- **Predicted result:** **byte-identical ranked lists.** Both open the same
  lancedb at the same `corpus_version` and run the same dense ANN with the same
  BGE-M3 singleton. The only way they could differ is a lazy implementation bug
  (e.g. re-instantiating the encoder with different dtype, or skipping
  `open_chunks_table_with_fallback`'s degraded path) — which would be a defect,
  not an inherent fork property.
- **Cost:** one BGE-M3 warm (~10-30 s) + ~20 queries × 55 ms × 2 forks ≈ under
  a minute of compute once a Fork A prototype exists. Requires a built server +
  BGE-M3 (not run here — this is analysis). **Not worth running for m1**: the
  prediction is byte-identical and the synthesis already chose Fork C, for which
  there is no second path to diff against.

---

## 8. Open questions / risks

1. **Brute-force fallback on a pre-index version pin.** If a notebook's pinned
   `corpus_version` predates the HNSW index build, LanceDB serves brute-force
   ANN (`store.py:66-67, 839`). For a ~50-paper notebook this is *exact* (recall
   = 1.0) and only ~50 ms slower — accuracy-positive. Risk is latency-only at
   notebook scale; would matter at 10K+ chunks. Verify the bridgeland/shimura
   handles open with the index present, not in fallback.
2. **Lazy fork must reuse `open_chunks_table_with_fallback`, not bare
   `open_table`** — the single startup behavior with accuracy/robustness
   consequence (the degraded-version retry). m2-implementer note.
3. **Lazy fork must reuse the BGE-M3 singleton** (`query_encoder`). A second
   encoder wastes memory but does not change ranking — so this is a
   memory/latency risk, not an accuracy risk. Still flag it.
4. **The eval lens is paper-level, K-capped.** `queries.json`
   `expected_relevant_papers` sets average ~2-4 papers, so `P@10` is
   structurally capped well below 1.0; **Recall@10 and top-1 hit rate are the
   honest reads**, per the spike note. Any future "did the fork lose accuracy?"
   check should compare those two metrics, not P@10.
5. **Empty/missing notebook (AC5)** must return a typed error / empty result,
   not a 500 — orthogonal to ranking but part of "accuracy off the bat" in the
   sense of not silently returning the wrong (empty shared) corpus.
6. **Cache correctness under Fork A** (the slug-in-key fix R2 insists on) is a
   *correctness* risk, not an accuracy-of-retrieval risk — but a cache collision
   would serve notebook-A's rows for a notebook-B query, which the operator
   would experience AS an accuracy failure. Fork C sidesteps it entirely (one
   process = one corpus_version = isolated cache). Another reason Fork C is the
   safe m1 choice.
