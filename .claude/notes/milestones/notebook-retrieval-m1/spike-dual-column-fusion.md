# Spike: dual-column fusion (embedding_proof) — notebook-retrieval-m1

**Date:** 2026-05-28
**Mode:** READ-ONLY empirical. No server code changed.
**Harness:** `.claude/notes/spikes/dual-column-fusion/poc_dual.py`
**Raw data:** `.claude/notes/spikes/dual-column-fusion/measurements_dual.json`
**Predecessor:** `spike-accuracy-by-difficulty-class.md` §4 + §6 (Experiment B) —
this spike RUNS the experiment that note specified.

---

## 1. Verdict up front — NO-GO

**The operator's hypothesis is now empirically CLOSED. The unused
`embedding_proof` column carries RECALL signal, not TOP-1 PRECISION signal —
and fusing it into the default retrieval path costs more precision than it
buys recall.** Against the prior spike's own decision rule ("wire dual-column
iff it lifts the hard class ≥ +0.10 top-1 with no easy regression"), BOTH
fusion designs fail decisively:

| pipeline | overall top-1 | easy top-1 | hard top-1 | adversarial top-1 | overall R@10 |
|---|---|---|---|---|---|
| `dense_only` (baseline, live path) | **0.80** | 0.80 | 0.70 | **1.00** | 0.909 |
| `dense_dual_paper` (paper-level RRF) | 0.50 **(−0.30)** | 0.60 (−0.20) | 0.60 (−0.10) | 0.20 **(−0.80)** | 0.883 (−0.026) |
| `dense_dual_chunk` (chunk-level RRF) | 0.70 (−0.10) | 0.60 (−0.20) | 0.70 **(+0.00)** | 0.80 (−0.20) | 0.934 **(+0.025)** |

- **Hard-class top-1 lift** (the decision metric): `dual_paper` −0.10,
  `dual_chunk` +0.00. Neither reaches the +0.10 bar.
- **Easy regresses** for both arms (−0.20).
- The decision rule's "if it does NOT lift, dense-only `embedding_stmt` is the
  confirmed ceiling" branch is the one we land on.

**Keep the live path dense-only over `embedding_stmt`. Do NOT wire dual-column
fusion as the default `search_papers` retrieval mode.** The proof embeddings
stay ingested-but-unqueried — correctly so for a top-1-precision tool.

---

## 2. What was measured

Three bm25-free, rerank-free pipelines against the same curated
`queries.json` (20 queries: 10 bridgeland + 10 shimura; paper-level relevance
labels; difficulty-tagged) the m5 spike used. All run against the CURRENT
corpus — i.e. AFTER embedder-truncation-m1 (512→2048 token budget) and the
preamble-recovery re-embed, so the vectors differ slightly from the m5 spike's
pre-re-embed corpus (baseline top-1 0.80 here vs 0.85 there = a 1-query shift
at n=20, within noise).

- **`dense_only`** — single ANN over `embedding_stmt`, limit 50, dedup to
  unique paper_ids. This is the live `search_papers` path verbatim.
- **`dense_dual_paper`** — ANN over `embedding_stmt` + ANN over
  `embedding_proof` (prefiltered `kind='proof'`), dedup EACH to unique
  paper_ids, then RRF-fuse the two PAPER lists. Rewards a paper that surfaces
  in BOTH columns — the depth-boost hypothesis in its strongest form.
- **`dense_dual_chunk`** — same two ANN searches, RRF-fused at CHUNK level
  (mirrors the production `server/retrieval/ann.py::ANNPhase` fusion
  granularity), then dedup to papers. The "ship-as-is via ANNPhase" comparison.

Both dual arms **prefilter the proof search to `kind='proof'`** so the
4133/1961 zero-vector non-proof rows cannot pollute the proof arm. (A unit
query vs a zero vector has fixed squared-L2 distance 1, which outranks any
proof chunk with cosine < 0.5 — the production ANNPhase does NOT prefilter and
would suffer this pollution; this spike measures the CLEAN proof signal, so
the verdict is an upper bound on what ANNPhase-as-is could achieve.)

Prereq verified live before running: bridgeland 6804 chunks / 2671 proof (all
non-zero `embedding_proof`); shimura 3625 / 1664 (all non-zero).

---

## 3. The two failure mechanisms

**`dense_dual_paper` — equal weight destroys the clean dense ranking.**
Paper-level RRF gives the proof column the SAME vote as the statement column.
A paper whose proof body wanders into a neighbour's vocabulary gets boosted
toward top-1, displacing the paper whose STATEMENT is actually on-topic. The
damage is worst exactly where the prior spike predicted dense's strength:
the **adversarial class craters 1.00 → 0.20**. Adversarial queries are built
so adjacent papers share the most vocabulary — and proof bodies, being longer
and more discursive than statements, share even MORE. The proof column injects
maximal noise precisely on the subset where papers are hardest to tell apart.
This is the BM25-on-a-mono-topic-notebook problem (m5 spike §3) in a new guise:
a second signal with no discriminating power dilutes a clean one.

**`dense_dual_chunk` — gentler, because dilution cuts both ways.** Chunk-level
RRF interleaves proof chunks among the far more numerous statement chunks, so
each proof chunk's reciprocal-rank contribution is small and a single noisy
proof chunk rarely reaches a paper's top-1 slot. This preserves top-1 better
(−0.10 overall vs −0.30) AND is the only arm that lifts recall (+0.025 overall,
+0.05 hard). But it still regresses easy (−0.20) and adversarial (−0.20) — the
same noise, merely attenuated — for a net-negative top-1.

---

## 4. The flagship depth query refutes the mechanism directly

`bridge-q9` is the fixture's purpose-built depth-discrimination case ("Stab(X)
as complex manifold + covering structure" — all 39 papers say "stability
condition"; only a few OWN this sub-question; the owning paper's depth is in
its PROOF). If the proof column carried top-1 depth signal anywhere, it is here.

| pipeline | bridge-q9 rank of best paper | R@10 |
|---|---|---|
| `dense_only` | 2 (top-1 ✗) | 0.50 |
| `dense_dual_paper` | 2 (top-1 ✗) | 0.75 |
| `dense_dual_chunk` | **4** (top-1 ✗) | **1.00** |

Neither arm promotes q9 to top-1. The proof column DOES pull more of the
relevant papers into the top-10 (recall 0.50 → 0.75 → 1.00) — but it pushes
the single BEST paper DOWN (rank 2 → 4 under chunk fusion). **This is the whole
finding in one query: the proof column improves recall and degrades top-1
precision simultaneously.** The depth signal exists, but the general-domain
BGE-M3 encoder renders it as "this paper is ALSO about the topic," not "this
paper treats it MOST deeply." Turning depth into a top-1 ranking is exactly
what the current encoder cannot do.

---

## 5. The one residual, weak option (not a recommendation)

`dense_dual_chunk` is the only configuration in two spikes that lifts recall
without a latency penalty (the second ANN adds ~10 ms; per-query ~60 ms, same
order as dense-only — the 342 ms "overall mean" for dense_only is skewed by the
one-time 5.8 s cold model-load on bridge-q1). The hard-class recall lift is
+0.05 and several queries reach R@10=1.00 that dense missed.

IF a future product surface wants a **recall-oriented "find every paper that
TOUCHES topic X"** mode — distinct from the default top-1-precision
`search_papers` — `dense_dual_chunk` with the `kind='proof'` prefilter is the
configuration to use. But:
- the recall lift is small (+0.025 overall) and within noise at n=20;
- it is a SEPARATE tool/mode, never the default path (it costs top-1);
- it would also need the proof-arm prefilter the production ANNPhase lacks.

I do not recommend building this now. It is a documented option if a
recall-mode requirement ever materializes.

---

## 6. Disposition

1. **Live `search_papers` stays dense-only over `embedding_stmt`.** Confirmed
   accuracy ceiling across two spikes (BM25/RRF/rerank net-negative; dual-column
   net-negative on top-1). The `excluded_kinds=["proof"]` filter is correct.
2. **`embedding_proof` stays ingested-but-unqueried.** It is not dead weight in
   principle (it carries recall signal) but it is not wireable into a
   precision-first default. Keep populating it (cheap at ingest); revisit only
   under a recall-mode requirement or a math-domain encoder swap.
3. **The operator's hypothesis is fully closed.** Across rerank, hybrid, and
   now dual-column, the depth-discrimination win the operator correctly
   identified as a TARGET is not recoverable from the current encoder on these
   notebooks. The next lever — if this target is ever reprioritized — is a
   math-specialized embedding model (e.g. a fine-tuned encoder that separates
   "mentions" from "proves"), which is out of all near-term scope and would be
   its own epic.
4. **No fork-A coupling.** This verdict is independent of the fork-A per-call
   notebook routing (m2): dual-column would have been a retrieval-MODE change,
   orthogonal to WHICH notebook is served. m2 (fork A) proceeds on its own
   merits as the multi-notebook routing endpoint; it does not depend on and is
   not blocked by this NO-GO.

**Bottom line:** the proof column is a recall lever, not a precision lever, and
the default path wants precision. dense-only `embedding_stmt` remains the
shipped, measured-maximal configuration.
