# Timeline call — `/proof-verify` handler-wiring pivot

**Companion to:** `.claude/notes/proof-verify-pivot/synthesis.md` and `plans/proof-verify-handler-wiring-roadmap.md`.

**Revised 2026-05-21** — incorporates user offer to curate two notebooks (bridgeland-stability + shimura-varieties), which collapses the e2 fixture timeline from 3–6 weeks to ~1 week and splits the timeline into two distinct gates:

1. **Operational unblock (N-weeks)** — downstream can stop spinning per-notebook daemons and use per-call `filters` on a single daemon.
2. **Product-viability gate (M-weeks)** — does the dense+filter (optionally hybrid+rerank) approach actually find 6-of-100 needles in a topically-clustered notebook?

**Revised 2026-05-21 PM** — m5 spike FIRED with verdict NO. The product-viability gate question is answered: dense-only (+ per-call filter) hits **top-1 = 0.850** and **R@10 = 0.936** across 20 hand-labeled queries on the two notebooks. Hybrid+rerank produces zero P@10 lift and -0.10 top-1 regression at 122× latency cost. **Full pivot timeline collapses to bare-minimum wiring; e3 closed unimplemented.** Verdict at `.claude/notes/spikes/wiring-rerank-lift-100paper/note.md`.

## N weeks — bare-minimum wiring

**N = 1–2 weeks.** Confidence: **HIGH**.

Scope: roadmap's Now lane (m1 + m2 + m3) plus `proof-verify-handler-wiring-spike-1`. Delivers R1 (per-call notebook scoping via `filters={"paper_id":[...]}`) end-to-end with operator docs.

| Milestone | Size | Notes |
|---|---|---|
| spike-1 | ≤ 1 day | LanceDB ANN + `.where()` composition validation |
| m1 | M (1–3 days) | ~50 LOC handler change + ~150 LOC tests |
| m2 | S (≤ 1 day) | `filters_applied` output field + CHANGES.md |
| m3 | S (≤ 1 day) | docs/install.md or docs/notebooks.md |

**Confidence rationale (HIGH):**
- The filter primitive (`paper_id IN (...)`) is shipped + tested at `BM25Phase._apply_supported_filters` (`server/retrieval/bm25.py:670-687`).
- The surgery is well-mapped (~50 LOC in one handler file).
- The 22-paper math.AG corpus is already the spike fixture — no setup required.
- No tool input-schema change → no `EXPECTED_TOOL_SCHEMA_SHA256` repin → no BP1 cache discipline disruption.
- Downstream's `found@K=1` rule is already satisfied by dense-only per the spike (3/3 queries hit a known-relevant paper at top-1).

**What could blow the timeline:** spike-1 returns NO and LanceDB ANN doesn't compose with `.where()` correctly; remediation would be a candidate-filter post-hoc pattern with a 2x latency hit. Probability: low (LanceDB's docs claim full support, and the same construct is used in `tests/retrieval/test_ann.py` with scalar filters per E07_S02). If it does, add ~3 days for the post-hoc filter path.

## M weeks — product-viability gate (does the approach actually work?)

**M = 3–4 weeks calendar time end-to-end.** Confidence: **MEDIUM-HIGH** (was MEDIUM before the user-curation offer).

This is the timeline to a definitive YES/NO/UNCERTAIN verdict on whether the dense+filter (and conditionally hybrid+rerank) approach actually solves the 6-of-100-needles product question. Scope: full roadmap (Now lane × 5 milestones) + the conditional e3 if the verdict is YES.

| Phase | Duration | Notes |
|---|---|---|
| User curates the two notebooks | ≤ 1 week (user-owned) | 100 arXiv IDs + ~10 sub-questions + paper-level labels per notebook |
| m4 — ingest both notebooks | S (~1 day) | Reuses bulk_ingest infrastructure shipped 2026-05-20 |
| m5 — re-spike at 100-paper scale, write verdict | M (~2 days) | Lifts existing POC; adds chunk-leakage + score-distribution metrics |
| **Verdict gate** | — | YES = wire e3; NO = architecture change; UNCERTAIN = sparse-fusion sub-spike first |
| e3 — Handler wiring for hybrid+rerank (conditional) | M (~1–2 weeks) | ~80 LOC lift + per-call `rerank: bool` argument + cache discipline + ~300 LOC tests |
| Final downstream re-probe | ≤ 2 days | Closes the loop end-to-end |

Total: ~3 weeks to verdict (1 week user curation + 1 week m4+m5); +1–2 weeks for conditional e3 implementation. **If the verdict is NO, the full pivot stops at the 3-week mark with a clear architecture-change recommendation — that is the correct outcome, not a failure.**

**Confidence rationale (MEDIUM-HIGH):**

- **The largest variance source (analyst time for the fixture) is eliminated** by the user curating directly.
- **The remaining engineering is well-bounded:** m4 reuses the bulk_ingest infrastructure that landed 2026-05-20; m5 is a fixture extension to the spike POC that already exists at `.claude/notes/spikes/wiring-rerank-lift/poc.py`.
- **The product-viability verdict itself is the unknown** — but it's a known-unknown, with a clear path to resolution, and the outcome IS the deliverable.
- **No GPU.** All measurements remain CPU-bound. If the verdict is YES on hybrid+rerank, the 6.8s/query latency cost informs whether rerank ships as opt-in (likely) or default-on (unlikely without GPU work).

## Blocked behind UNCERTAIN

One item remains UNCERTAIN at the end of the M timeline:

1. **Score-distribution sharpness for a `found = (score > T)` rule.** The spike-3 verdict will measure rank-based precision. If downstream wants a score-threshold rule on top, a small follow-up spike (≤ 1 day) measures the per-pipeline score-distribution sharpness (top-1-vs-rest gap, max-score percentile). Independent of the rank-lift question; can run alongside m5 if downstream wants the data in the same pass.

## Recommendation to downstream (revised 2026-05-21 PM, post-m5)

**Single-track plan — Track B's verdict closed it down to Track A only:**

- **Track A — operational unblock (N = 1–2 weeks, HIGH confidence):** spike-1 + m6 + m1 + m2 + m3. Downstream stops spinning per-notebook daemons; uses per-call `filters={"paper_id":[...]}` on a single daemon serving multiple notebooks. With dense-only ANN's measured 0.850 top-1 hit rate and 0.936 R@10 on the m5 fixture, this is sufficient for `/proof-verify`'s `found@K` semantics.

- **Track B — CLOSED with NO verdict.** The e3 hybrid+rerank wiring is not evidence-justified. Closed without implementation per the m5 spike's measurements: zero P@10 lift, -10pp top-1 regression, 122× latency cost. The 22-paper spike's NO held up at proper notebook scale.

**If `/proof-verify` later finds dense-only's 85% top-1 insufficient for some specific subset of claims**, the recommended next investigation is the sparse-vector fusion sub-spike (BGE-M3 has a sparse head currently unused by arXMCP). That's a separate ~3-day spike, NOT a roadmap commitment. See the m5 note's "architecture-change candidates" section for the full ranked list of options.
