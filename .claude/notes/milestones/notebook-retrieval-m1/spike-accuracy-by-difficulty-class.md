# Spike: retrieval accuracy stratified by difficulty class — notebook-retrieval-m1

**Date:** 2026-05-28
**Mode:** READ-ONLY analysis. No code changed.
**Operator's hypothesis:** the full BM25→ANN→RRF→rerank pipeline matters for
detailed questions answered at a SURFACE level across many papers but DEEPLY by
only a select few — i.e. the depth-discrimination case that cross-encoder
reranking and hybrid sparse+dense were designed for. The prior aggregate "dense
is maximal" verdict may have AVERAGED AWAY a real rerank/hybrid win on the hard +
adversarial subset.

---

## 1. Verdict up front

**The hypothesis is TESTED by existing data — and on this fixture it is
REFUTED, with one genuinely interesting partial exception that does not rescue
it.** The 100-paper spike (`wiring-rerank-lift-100paper/poc.py`) DID stratify by
difficulty class — `poc.py:172-207` (`aggregate`) buckets every per-query row
into `easy`/`hard`/`adversarial` and `main()` (`poc.py:219-234`) emits per-class
lifts. The earlier fork-analysis note quoted only the aggregate; it did not
mislead, but it under-reported that the *stratified* numbers exist and contradict
the operator's directional prediction:

| class (n) | dense top-1 | hybrid top-1 | +rerank top-1 | full top-1 lift | rerank-only P@10 lift |
|---|---|---|---|---|---|
| easy (5) | 0.800 | 0.800 | **0.600** | **−0.200** | +0.000 |
| hard (10) | 0.800 | 0.800 | 0.800 | **+0.000** | +0.020 |
| adversarial (5) | **1.000** | 0.600 | 0.800 | **−0.200** | +0.000 |

The operator predicted rerank/hybrid would WIN on hard+adversarial. The data
shows the opposite signs everywhere the prediction was sharpest:

- On **adversarial** queries, dense-only already scores a **perfect 1.000
  top-1** — there is no failure for rerank to recover. Hybrid *breaks* it to
  0.600; rerank partially repairs hybrid's damage back to 0.800 but still
  lands BELOW dense-only. The adversarial class is dense-only's *best* class,
  not its worst — the exact inverse of the fixture author's design intent.
- On **hard** queries, the full pipeline is a wash (+0.000 top-1); rerank-only
  buys +0.020 P@10 over hybrid, which is noise at n=10.
- On **easy**, rerank actively destroys 2 of 5 top-1s.

So the aggregate did NOT hide a hard/adversarial win. The stratification was
performed and it confirms the aggregate's direction *within each class*.

**The one real exception** (and it is the operator's mechanism, vindicated in
miniature): `bridge-q9` — the fixture's flagship intra-notebook discrimination
case ("Stab(X) as complex manifold + covering structure"; all 39 papers say
"stability condition", only 4 own this sub-question). Dense-only puts the right
paper at **rank 2, not 1** (top-1 ✗, R@10=0.50). **Rerank promotes it to top-1
and lifts recall to 0.75.** This is precisely the surface-vs-deep win the
operator described — and it is the *single* query in 20 where rerank beats dense
on top-1. One win against three rerank-caused regressions (`bridge-q1`,
`shimura-q5`, `shimura-q10`) is a net −2. The mechanism the operator names is
**real but rare** on this corpus, and swamped by rerank's collateral damage.

---

## 2. What the 100-paper spike actually measured

Per-class, not pooled. The chain of evidence:

- `poc.py:124-169` runs each of 20 queries (10 bridgeland + 10 shimura) under
  three pipelines, tagging every row with `q["difficulty"]` (`poc.py:154`).
- `poc.py:172-207` aggregates into four buckets per pipeline: `overall`,
  `easy`, `hard`, `adversarial`.
- `poc.py:219-234` computes `full_top1_lift_over_dense` and
  `rerank_p10_lift_over_hybrid` PER class.
- `note.md:20-24` reports the per-class lift table verbatim; `note.md:30-35`
  enumerates the exact top-1 transitions.

I re-derived the numbers directly from `measurements.json` (the raw per-query
rows) — they match `note.md` exactly. The per-query transition table:

| query | class | dense | hybrid | +rerank | note |
|---|---|---|---|---|---|
| bridge-q1 | easy | ✓ | ✓ | **✗** | rerank demotes the Bridgeland-original paper to rank 2 |
| bridge-q4 | adversarial | ✓ | ✗ | ✓ | hybrid breaks it; rerank repairs |
| bridge-q6 | hard | ✓ | ✗ | ✗ | KS wall-crossing; neither hybrid nor rerank recover |
| bridge-q8 | adversarial | ✓ | ✗ | ✓ | hybrid breaks GM-varieties; rerank repairs |
| bridge-q9 | hard | ✗ | ✗ | **✓** | **the one true rerank win — depth discrimination** |
| shimura-q5 | hard | ✓ | ✓ | **✗** | rerank demotes to rank 3 |
| shimura-q8 | hard | ✗ | ✓ | ✓ | hybrid wins (distinctive vocab) |
| shimura-q10 | adversarial | ✓ | ✓ | **✗** | rerank demotes to rank 2 |

Net rerank-vs-dense top-1: **+1 (bridge-q9) − 3 (q1, shimura-q5, shimura-q10)
= −2**. The hybrid-vs-dense story is separately bad: hybrid breaks 3 adversarial
top-1s (q4, q8 + the aggregate) by injecting BM25 lexical noise, and rerank only
sometimes cleans up after it.

**Caveat the operator should weigh, in their favor:** n=5 per stratum (easy,
adversarial) and n=10 (hard). A single query flips a class top-1 rate by 0.20
(easy/adversarial) or 0.10 (hard). These are not statistically powered class
estimates — they are directional. The honest read is "no evidence of a
hard/adversarial rerank win, and a real-but-isolated win on exactly one
depth-discrimination query." The fixture is too small to *prove* rerank never
helps the hard class; it is large enough to refute "rerank systematically wins
the hard class."

The eval harness (`tests/eval/metrics.py`, `tests/eval/test_retrieval_quality.py`)
does **NOT** support difficulty stratification — `grep difficulty tests/eval/`
returns nothing, and the metrics are CHUNK-level nDCG/recall keyed on grade-3
labels, a different relevance model than the spike's PAPER-level labels. The
spike's `poc.py` is the *only* stratified measurement; it bypasses the harness
entirely. `queries.json`'s `curated_by` field confirms the intent verbatim:
"Each query is tagged with a difficulty class so the m5 spike can stratify
lift/regression by difficulty." The fixture was built for exactly this test;
the test was run; it did not support the hypothesis.

---

## 3. Mechanism analysis per stage — the surface-vs-deep case

**Dense ANN over `embedding_stmt`** (`search.py:480-482`). The operator's
failure-mode prediction — "a chunk that MENTIONS a topic and one that DEEPLY
treats it have similar cosine" — is real in principle, and `bridge-q9` is the
one query where it bites (deep paper at rank 2). But the data says it bites
*rarely*: BGE-M3's statement embeddings discriminate "this paragraph is ABOUT
Bridgeland stability on Enriques" from a passing mention well enough to put the
owning paper at top-1 on 17/20 queries, and at top-1 on **all 5 adversarial
queries**. The adversarial class — built to be dense's failure case — is dense's
strongest. The mechanism is sound; its empirical frequency on a topically-curated
notebook is low.

**BM25 sparse** (`server/retrieval/bm25.py`, via `poc.py:110`). Honest both
directions: in principle, exact term-frequency should reward the deep-treatment
paper that repeats the precise term. In practice on these notebooks it
*regresses* top-1 by 10 points (0.850→0.750), concentrated on adversarial queries
(`note.md:39-44`). The reason is the shared-math-vocabulary IDF problem: within a
notebook curated around one topic, "stability condition" / "derived category"
have near-uniform IDF, so BM25 contributes rank-noise, not rank-signal, and RRF
blending then *dilutes* the clean dense ranking. The IDF problem NEUTRALIZES the
operator's hoped-for term-frequency win — and worse, the adversarial queries
(where adjacent papers share the most vocabulary) are exactly where BM25 does the
most damage (bridge-q4, q8 both break under hybrid). For this corpus, BM25
fusion is net-negative on the operator's own target subset.

**Cross-encoder rerank** (`server/retrieval/rerank.py`, BGE-reranker-v2-m3).
This is the operator's strongest theoretical lever and deserves the most care.
The crux question — "was the −10pt aggregate measured on a set where dense was
already near-perfect, so rerank could only churn?" — is **partly yes**: on the
adversarial class dense is 1.000, so rerank can only hold or hurt, and it hurts
(shimura-q10 demotion). But the deeper finding is structural: `rerank.py:376`
truncates every candidate body to `max_length=512` tokens. A "deep treatment"
chunk's distinguishing content (a full proof, a long construction) is exactly
what gets truncated, so the cross-encoder scores a *clipped* view — it cannot
see the depth signal it was supposed to exploit. Combined with the documented
score-compression on specialized math vocabulary (`note.md:86-87`: the
general-domain reranker's logits compress when all 50 candidates are dense math),
the cross-encoder's depth-discrimination ability is structurally hobbled on this
corpus. `bridge-q9` shows it CAN win when the signal survives truncation; the
512-token clip plus general-domain training means it usually can't.

**RRF fusion** (`server/retrieval/rrf.py`, via `ann.py:306-349`). RRF is
rank-based (`ann.py:327`: "Scores are NOT consumed — RRF is rank-based"), so it
can only help if BM25's *ranks* carry signal dense's miss. Given BM25's
IDF-noise on this corpus, RRF mostly **dilutes** — it averages a clean dense
ranking with a noisy sparse one. The 3 adversarial hybrid-breakages are RRF
dilution in action.

---

## 4. The dual-column underutilization finding — REAL and orthogonal

This is the most actionable finding in this spike, and it is independent of the
BM25/rerank question.

Chunks carry TWO embedding columns: `embedding_stmt` and `embedding_proof`
(`ann.py:89`). The embedder routes `kind == "proof"` chunks to `embedding_proof`
and everything else to `embedding_stmt` (`ingest/embedder.py:1028`). **The live
search queries `embedding_stmt` ONLY** (`search.py:481`) AND explicitly excludes
proof chunks from results (`search.py:539`: `"excluded_kinds": ["proof"]`). The
spike's `dense_only` path does the same (`poc.py:96`).

**Consequence for the surface-vs-deep case:** a "deep treatment" of a topic is,
by definition, often a *proof* — the paper that PROVES the named theorem has its
depth in the proof body, which lives in `embedding_proof`, which the live path
never touches and actively excludes. The operator's intuition that "depth lives
somewhere dense-only misses" is correct — but the missed signal is not in BM25 or
the reranker. **It is in the proof column the live path discards.** For
`bridge-q9` and `bridge-q2` ("only these PROVE a new instance"), the
proof-statement distinction is exactly the depth axis.

This is genuinely untested. Neither the spike nor the live path nor the eval
harness ever queries `embedding_proof`. The handler's own comment
(`search.py:468-470`) concedes the gap: "embedding_proof is for proof bodies;
mixing without RRF would produce inconsistent rankings (E07 is the right venue
for dual-column fusion)." A dual-column query — ANN over BOTH columns, fused by
RRF (which IS sound here: the two columns are the same model's same-space
vectors, no IDF problem) — could surface the deep-treatment paper that the
statement-only column ranks second. This is a different lever than the one the
operator named, pointing at the same target.

---

## 5. The decisive recommendation for notebook-retrieval-m1

**Keep dense-only as m1's shipped path. Do NOT wire BM25/RRF (measured
net-negative on the exact target subset). Do NOT default-on the reranker
(measured −2 net top-1, 122× latency, structurally hobbled by 512-token
truncation).** The fork-analysis note's AC2 conclusion stands: dense-only over
`embedding_stmt` is the maximal-accuracy *single-column* configuration the
project has measured.

**But the operator is not wrong that there is accuracy left on the table — they
have the right target and the wrong lever.** The lever is NOT classic BM25 or the
general-domain cross-encoder; it is the unused `embedding_proof` column (§4) and,
secondarily, query-adaptive rerank gated to the depth-discrimination subset.

Concrete m1 disposition:

1. **m1 ships dense-only `embedding_stmt`** — unchanged, lowest risk, measured
   ceiling on this fixture (R@10=0.936, top-1=0.850).
2. **File a dual-column fusion sub-spike** as the NEXT accuracy investigation
   (this is option (d) in the operator's framing, and I judge it the real lever).
   It is measurable-before-committing — see §6. This is the operator's hypothesis
   *redirected* to the stage that actually carries the depth signal.
3. **Do NOT go query-adaptive-rerank for m1.** The single rerank win (bridge-q9)
   does not justify the routing complexity + 122× latency on the matched subset,
   *until* the dual-column spike is ruled out. If dual-column also fails to lift
   bridge-q9-class queries, revisit a depth-gated reranker with the 512-token
   truncation lifted (BGE-reranker-v2-m3 supports 8192).

This IS measurable before committing — the project has the fixture, the labels,
and the harness scaffolding. The operator should not take this verdict on
analysis alone for the dual-column claim; §6 is the experiment.

---

## 6. The exact settle-it experiment (specify, do NOT run)

Two experiments. The first re-confirms the BM25/rerank verdict with full nDCG@5
stratification (the existing spike used a paper-level proxy, not the harness
metric). The second tests the dual-column hypothesis, which nothing has measured.

**Prereqs (both):** a built bridgeland + shimura notebook corpus at
`var/arxmcp/notebooks/<slug>/lancedb` (already present — the spike ran against
it), BGE-M3 weights (~2.3 GB, auto-downloaded), and for rerank
BGE-reranker-v2-m3 (~2.3 GB). macOS needs `KMP_DUPLICATE_LIB_OK=TRUE`.

**Experiment A — re-run with nDCG@5 stratified by class.** Extend `poc.py`'s
`metrics()` (`poc.py:68-90`) to also compute `ndcg_at_k` / `recall_at_k` from
`tests/eval/metrics.py` (needs a chunk-level relevance map; derive grade-3 for
chunks whose `paper_id ∈ expected_relevant_papers`, grade-0 otherwise — a
coarse but defensible mapping). Then:

```bash
KMP_DUPLICATE_LIB_OK=TRUE \
ARXMCP_RUN_REAL_BGE_RERANKER=1 \
  uv run python .claude/notes/spikes/wiring-rerank-lift-100paper/poc.py
```

Report nDCG@5 / top-1 / R@10 per `{dense_only, hybrid, hybrid_rerank} ×
{easy, hard, adversarial}`. Predicted result: matches §1 (no class-level rerank
win). Cost: ~5–8 min (BGE-M3 warm + reranker load + 60 pipeline×query runs on
CPU). This closes the "but you only measured paper-level proxy, not nDCG" gap.

**Experiment B — dual-column fusion (the real test).** Add a fourth pipeline
`dense_dual`: run ANN over `embedding_stmt` AND `embedding_proof` separately
(drop the `excluded_kinds=["proof"]` filter for this column), then RRF-fuse the
two ranked lists (reuse `server/retrieval/rrf.py` — same-space vectors, no IDF
issue). Compare `dense_dual` vs `dense_only` per class. **This requires the
notebook corpus to actually have proof chunks embedded** — verify first:

```bash
KMP_DUPLICATE_LIB_OK=TRUE uv run python -c "
import lancedb, pyarrow.compute as pc
t = lancedb.connect('var/arxmcp/notebooks/bridgeland-stability/lancedb').open_table('chunks')
a = t.to_arrow()
import pyarrow as pa
print('proof chunks:', pc.sum(pc.equal(a['kind'], 'proof')).as_py(), '/ total', a.num_rows)
"
```

If proof-chunk count is ~0, the notebooks were ingested statement-only and
Experiment B needs a re-ingest first (out of m1 scope — flag it). If proof chunks
exist, the dual-column pipeline is ~30 lines on top of `poc.py` and runs in the
same ~5 min. **Success criterion:** `dense_dual` lifts top-1 / R@10 on the hard
class (especially bridge-q2, bridge-q9) without regressing easy. A lift here
would justify wiring dual-column fusion into the live handler (the E07 venue the
code comment already names) — and would vindicate the operator's instinct via a
stage they didn't name.

**Decision rule:** if Experiment B lifts the hard class ≥ +0.10 top-1 with no
easy regression, wire dual-column fusion for a future milestone (not m1). If it
does not, dense-only `embedding_stmt` is the confirmed ceiling and the operator's
hypothesis is fully closed — the depth signal isn't recoverable with the current
encoder, and the next lever is a math-domain encoder (out of all near-term scope).
