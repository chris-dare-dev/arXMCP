# Synthesis — `/proof-verify` → arXMCP pivot

**Date:** 2026-05-20 (revised 2026-05-21)
**Trigger:** downstream `/proof-verify` pipeline migrating off NotebookLM onto arXMCP. Spike-4 (2026-05-21, downstream) confirmed our v1.27.1 substrate is healthy but flagged intra-notebook precision as the load-bearing problem. Downstream Q1/Q2 follow-up answered (no notebook scoping today; rerank provisioned-but-not-wired).
**Output:** classify each of downstream's R1–R4 against arXMCP's current capability state with measurement-backed evidence. Inputs to the roadmap-drafting next step.

---

## ✅ Verdict update (2026-05-21 PM) — m5 spike at proper-notebook scale: NO

The m5 product-viability spike fired against the two user-curated notebooks (bridgeland-stability 39 papers + shimura-varieties 12 papers) with 20 hand-labeled queries grounded in actually reading each paper's intro. **Full verdict, measurements, and per-query analysis at `.claude/notes/spikes/wiring-rerank-lift-100paper/note.md`.**

**Verdict: NO** — the 22-paper spike's NO result was not a small-fixture artifact. At 51-paper / 20-query scale with hand-labeled relevance:

| pipeline | mean R@10 | top-1 hit rate | mean total_ms |
|---|---|---|---|
| dense_only | 0.936 | **0.850** | **55** |
| hybrid | 0.909 | 0.750 | 59 |
| hybrid_rerank | 0.938 | 0.750 | 6703 |

Hybrid+rerank **regresses top-1 by 10 percentage points** and costs 122× the latency. Stratified by difficulty, the regression is concentrated on `easy` (-0.20) and `adversarial` (-0.20); `hard` is neutral. Theoretical analysis from the prior spike confirmed empirically: BM25 IDF is non-discriminating on topical-domain notebooks (shared vocabulary saturates the signal), and the general-domain cross-encoder rerank does not have enough math-specific signal to improve on dense-only's clean semantic ranking.

**The good news that came out of the same spike:** dense-only ALREADY hits top-1 on 85% of pointed sub-questions, and R@10 = 0.94 across all queries. For a downstream `found@K = (top-K ∩ known_relevant ≠ ∅)` rule (R4 path), this is sufficient: dense-only + per-call paper_id filter satisfies the product question at 85% precision and full recall@10.

**Implication for the pivot:** `proof-verify-handler-wiring-e3` (hybrid+rerank wiring) is CLOSED unimplemented. The full-pivot timeline collapses to the bare-minimum-wiring timeline (1-2 weeks). The `/proof-verify` consumer ships against dense+filter; rerank wiring is not evidence-justified.

---

---

## R1 — Per-area notebook scoping

> One curated notebook per research area (~100 papers each), queryable by notebook ID or paper-id-set per call.

**Status: PARTIALLY EXISTS (unwired) — operational workaround usable today.**

| Layer | What exists | Evidence |
|---|---|---|
| Storage | LanceDB `chunks.paper_id` scalar column with HNSW index | `ingest/schema.py:80` |
| Filter primitive | `BM25Phase` supports `filters={"paper_id": <str> \| <list>}` end-to-end | `server/retrieval/bm25.py:117, 670-687` (SUPPORTED_FILTER_KEYS frozenset + `_apply_supported_filters`) |
| MCP-tool schema | `search_papers` accepts `filters: dict[str, Any] \| None` | `server/handlers/search.py:109-112` |
| Handler behavior | **Drops the `filters` arg, returns `filter_warnings`** | `server/handlers/search.py:243-246` (`"filters arg is accepted but not yet processed (deferred to E07_S04)"`) |
| Operational workaround | One daemon per notebook via `ARXMCP_LANCEDB_PATH=<dir>` on different ports | Used today to unblock spike-4; 22-paper math.AG corpus is a working example at `var/arxmcp/index/lancedb-staging` |

**Wiring delta:** one LanceDB `.where()` call in `search.py`. The existing dense-only path becomes `chunks_table.search(query_vec).where(f"paper_id IN {tuple(allowed)}").limit(k*5)`. No schema change to the MCP tool surface (the `filters` arg already exists; only its behavior changes). No BP1 cache-hash repin (`EXPECTED_TOOL_SCHEMA_SHA256` stays stable per `tests/test_server_tool_schema.py:94`).

**Not on roadmap:** the dedicated `notebook_id` first-class concept (server-side notebook → paper-id mapping table, `set_active_notebook` MCP tool) is net-new and would require a new column on the chunks schema. Recommendation: stay client-managed at v1 — the client passes the notebook's paper-id list per call.

---

## R2 — Two-stage retrieval (dense → cross-encoder rerank, optionally + sparse fusion)

> Critical because dense-only score compression on small topologically-dense corpora is the failure mode spike-4 surfaced.

**Status: FULLY EXISTS AS CODE, NOT WIRED INTO LIVE HANDLER, NOT VALIDATED AT TARGET SCALE.**

| Layer | What exists | Evidence |
|---|---|---|
| BM25 phase | `server/retrieval/bm25.py::BM25Phase` — `query(text, top_n) -> [(chunk_id, score)]` | `server/retrieval/bm25.py:532+` |
| ANN+RRF phase | `server/retrieval/ann.py::ANNPhase` + `server/retrieval/rrf.py::reciprocal_rank_fusion` | E07_S02 ship |
| Reranker phase | `server/retrieval/rerank.py::RerankPhase` — BGE-reranker-v2-m3 cross-encoder, pinned `revision=953dc6f6...`, `trust_remote_code=False`, semaphore + singleflight + Tier-3 cache hooks | E07_S03 ship |
| Startup loader | `Resources.startup` calls `_load_reranker_or_raise` when `enable_rerank=True`; `/readyz` flips `reranker:true` | `server/resources.py:357-360` |
| Hybrid orchestrator | `_run_hybrid_against_corpus` in the eval test (NOT in handler) | `tests/eval/test_retrieval_quality.py:328-486` |
| Live handler | **Dense-only ANN — does not invoke any of the above** | `server/handlers/search.py:217-225, 268` (`"retrieval_mode": "dense_only"`) |
| Eval gate | `pytest --hybrid --rerank --ndcg-min=0.80` harness ready; **fixture is empty stub** | `tests/eval/fixtures/queries.json` = `{"queries": []}`; `.claude/docs/retrieval-quality-report.md` marked PRELIMINARY throughout |

**Wiring delta:** lift the 80-LOC `_run_hybrid_against_corpus` helper into the handler. Handler reads `r.bm25_phase`, `r.ann_phase`, `r.rerank_phase` (all already on the Resources object). Output payload's `"retrieval_mode"` field changes from `"dense_only"` to `"hybrid"` or `"hybrid+rerank"` based on rerank-flag state. ~50 LOC net in `server/handlers/search.py`.

**Evidence against blindly wiring:** the rerank-lift spike (`.claude/notes/spikes/wiring-rerank-lift/`) measured all three pipelines against the real 22-paper math.AG corpus:

- Paper-level P@10 mean: **0.722 across all three configurations** (no lift)
- Adjacent-noise chunk leakage on Q1 (the hardest, cleanest test): dense_only **2/10** vs hybrid 4/10 vs hybrid+rerank 4/10 (rerank moved adjacent paper `2604.28085` into position 3 — a qualitative regression)
- Latency: dense=83ms, hybrid=57ms, hybrid+rerank=**6794ms** on CPU (80× cost)

The fixture is acknowledged-small; BM25 + RRF + cross-encoder typically demonstrate value at 100-paper+ scale where BM25 IDF discrimination becomes meaningful. **The 22-paper-scale NO does not generalize to 100-paper scale.** It does, however, mean **wiring hybrid+rerank as the live-handler default is unsupported by evidence and operationally costly without a GPU.**

---

## R3 — Intra-notebook precision SLO

> Calibration must measure relevant-vs-topologically-adjacent gap, not relevant-vs-gibberish.

**Status: NO MEASUREMENT FRAMEWORK FOR THIS — current eval design tests global relevance, not adjacent-noise.**

| Layer | What exists | Evidence |
|---|---|---|
| Metric primitives | `tests/eval/metrics.py::ndcg_at_k, recall_at_k` (relevance-graded; works for any relevance scheme) | E05_S03 |
| Query fixture format | per-query `relevant_chunks: [{chunk_id, relevance}]` | `tools/validate_eval_fixtures.py` schema |
| Fixture content | **EMPTY stub — never curated** | `tests/eval/fixtures/queries.json:5` |
| Curation runbook | `.claude/docs/eval-curation.md` (E05_S03 deliverable) — protocol for hand-labeling 20 queries against the seed corpus | docs ship; data never produced |
| Per-area / adjacent-noise framing | **Does not exist anywhere** | The eval was designed for global precision (`math.AG` query → math.AG chunks) not for intra-notebook discrimination |

**Wiring delta:** the metric primitives are fine, but the fixture's **schema interpretation must shift** from "globally-relevant chunks" to "relevant chunks within a known notebook." Practically: add a `notebook_paper_ids: [str]` field per query so the eval scopes ground truth to the relevant notebook. This is a fixture-format extension (~10 LOC change in `validate_eval_fixtures.py` + tests), but **the load-bearing work is curating 100-paper notebooks with chunk-level ground truth per query — this is multi-week analyst time, not engineering**.

**Not on roadmap:** the entire "intra-notebook adjacent-noise" framing is downstream's reframing. arXMCP's existing nDCG@5 ≥ 0.80 Tier-1 gate (`.claude/roadmap/README.md` Tier exit gates table) is about global precision. If downstream's notion of precision becomes a documented arXMCP SLO, the Tier-gate definition needs an explicit "intra-notebook" annotation.

---

## R4 — Rank-based `found` semantics

> `found = (top-K contains a chunk from the known-relevant set)` or `found = (top rerank score crosses a threshold that is empirically sharp on rerank output)`.

**Status: TOP-K SEMANTICS WORK TODAY; SCORE-THRESHOLD SEMANTICS UNVALIDATED.**

| Sub-claim | Evidence |
|---|---|
| `found = (top-K contains a relevant chunk)` works today | Spike measured top-1 paper match across all 3 queries on dense-only: **3/3 queries hit a known-relevant paper at position 1**. `found@1` = 100% on this fixture. |
| Dense-only scores are NOT sharp enough for a `found = (score > T)` rule | Downstream spike-4 measured `calibration_gap=0.0628` even after corpus rebuild — well below the 0.10 threshold their `found` rule was designed for. |
| Rerank scores' discriminative power is **unmeasured** | The spike captured rerank rank-order behavior but did NOT log per-candidate `sigmoid(logit)` values, so we cannot today assert that rerank produces a sharper top-1-vs-rest gap than cosine. This is the highest-value follow-up measurement. |

**Wiring delta:** if downstream chooses rank-based `found@K` (recommended path given the evidence), no server-side work is needed beyond R1's `filters` wiring — they can implement `found = (top-K paper_ids ∩ known_relevant != ∅)` client-side on the existing dense-only path. The score-threshold path needs (a) the score-discrimination spike and (b) the hybrid+rerank handler wiring; both currently blocked on evidence.

---

## Cross-cutting findings

### Finding A — the wiring surgery is small; the eval debt is the real blocker

The 80-LOC handler lift is well-bounded engineering. The 100-paper curated fixture with chunk-level relevance is months-deferred analyst work that NOTHING in arXMCP's history has produced (`tests/eval/fixtures/queries.json` mtime 2026-05-08; never populated). Without that fixture, every claim about hybrid lift, rerank value, latency budget, and Tier-1 gate satisfaction is unmeasured.

### Finding B — downstream's R1+R4 path is the cheapest unblock

Per spike: dense-only ANN against the 22-paper notebook already returns the right paper at position 1 for every pointed query tested. If downstream uses `found = (top-K contains known-relevant)` semantics, they don't actually need the hybrid pipeline. R1 (filters wiring) is the only required handler change; ~1 week of engineering.

### Finding C — rerank is a future-tense investment, not a current necessity

`ARXMCP_ENABLE_RERANK=False` as default is correct given the current evidence. The spike actively warns against changing the default. If/when the 100-paper-fixture re-spike returns YES, default-on becomes considerable; until then, opt-in via env var is the right contract.

### Finding D — the 3-call-per-session MCP cap is intentional

`server/session.py:54` pins `MAX_SEARCH_PAPERS_CALLS = 3` per E08_S04 Rule 2 ("prevent runaway retrieval loops"). Downstream's fresh-session-per-query workaround is the correct workaround for their use case (per-claim retrieval). If a higher cap becomes the right answer for downstream, the constant is configurable but the design intent should be revisited.

### Finding E — the operational workaround scales fine for downstream's scale

22-paper corpus uses ~3.5 GB RAM (BGE-M3 + LanceDB + reranker if enabled). 10 notebooks × per-daemon = 35 GB peak. On commodity workstation hardware that's borderline; on a server it's trivial. Per-daemon is fine indefinitely up to ~10 notebooks, marginal at 20, painful at 50. Single-daemon multi-tenant becomes structurally necessary only at the next order of magnitude.

---

## Decision matrix

| Requirement | Status | Wiring delta | Blocked by |
|---|---|---|---|
| R1 — notebook scoping | unwired primitive exists; operational workaround works | thread `filters` arg through to `chunks_table.where()` in `search.py`; ~50 LOC | nothing |
| R2 — two-stage retrieval | full pipeline exists as code, not in handler | lift `_run_hybrid_against_corpus` into handler; ~80 LOC | **evidence at 100-paper scale (Finding A blocker)** |
| R3 — intra-notebook SLO | metric primitives exist; framing missing | extend fixture schema + curate 100-paper labels per query | multi-week analyst time |
| R4 — rank-based found | top-K semantics work today | nothing (client-side rule) | nothing (for top-K); R2+R3 wiring (for score-threshold) |

---

## What to ask downstream next

1. **Confirm rank-based `found@K` is acceptable** (vs score-threshold). If yes, R1 wiring alone unblocks the pivot at high confidence.
2. **Provide the 100-paper notebook fixture** with chunk-level relevance for the rerank-lift re-spike. Without this, R2 stays unproven and the handler-wiring milestone for hybrid+rerank cannot be evidence-justified.
3. **Confirm operational topology:** is one-daemon-per-notebook acceptable as the long-term architecture, or is single-daemon multi-tenant a hard requirement?
4. **Decide who owns the notebook → paper-id mapping** — client-side (recommended given Finding B) or server-side (more work, opens session-state and authz questions).
