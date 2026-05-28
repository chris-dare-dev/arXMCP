# Operator follow-up — embedder-truncation-m1

This milestone shipped the **code changes** for the C+B token-budget
bundle but deferred the **production re-embed + B-3 nDCG@5
measurement** to the operator. This file is the tracker.

## What's deferred

### 1. Production re-embed

Per the research synthesis (`research-synthesis.md` § "TL;DR"), the
~3-8 hour re-embed of every LanceDB dataset is operator-driven, not
pipeline-run. The Makefile target + driver shipped; the actual run
did not. Run when convenient:

```bash
# Sanity-check the discovery first.
/Users/chris.dare/Library/Python/3.9/bin/uv run python -m tools.re_embed_all --dry-run

# Then the real run (expect 3-8 hours of CPU; consider screen/tmux).
make re-embed-all
```

After the run, each notebook dataset's `corpus-version.json` should
have advanced by exactly +1.

### 2. B-3 — nDCG@5 no-regress measurement

The original AC pointed at `tests/eval/fixtures/queries.json` (empty
stub); the synthesis reframed to use
`var/arxmcp/notebooks/bridgeland-stability/queries.json` (10 curated
queries with relevance labels). The procedure:

1. **Pre-bump baseline** (skip if not captured beforehand): retrieval
   against the 10 queries was last measured by the spike at
   `.claude/notes/spikes/wiring-rerank-lift-100paper/note.md` —
   recorded `dense-only R@10 = 0.936`. This is the operator-side
   baseline to clear.
2. **Run `make re-embed-all`** (above) so post-bump chunks land in
   the per-notebook LanceDB.
3. **Run retrieval against `bridgeland-stability/queries.json`** —
   either via `make eval` once the eval driver supports notebook-
   scoped fixtures, or via an ad-hoc script that loops over the 10
   queries and computes nDCG@5 / R@10 against `expected_relevant_papers`.
4. **Assert ≤0.05 noise-floor regression** on R@10 (or whatever
   per-query metric is canonical at measurement time). Document the
   numbers in `.claude/docs/retrieval-quality-report.md`.

If a regression > 0.05 lands, the token-budget bump must be
re-evaluated — the math-fidelity gain is supposed to lift retrieval,
not regress it.

## Tracking provenance

This file was created in the `embedder-truncation-m1` rectification
phase as the fix for adversary finding **F7 (MEDIUM)** — "B-3 deferral
lacks a tracking artifact." See
`.claude/notes/milestones/embedder-truncation-m1/critique-merged.md`.

## Cross-reference: notebook-preamble-recovery-m1

The follow-up milestone `notebook-preamble-recovery-m1` shipped on
2026-05-28 and adds raw `.tex` fetching to the ar5iv path so
`extract_preamble` can run on every paper. It also adds a
`make ingest-recover-preambles` target that back-fills the 137
already-ingested ar5iv-only papers without re-running ingest.

**Recommended operator sequence:**

1. Run `make ingest-recover-preambles` (~7 minutes at 3 s/paper
   politeness; one-shot).
2. Then run `make re-embed-all` to rotate chunk_ids for the back-filled
   papers (preamble bytes flow into `_compute_chunk_id`'s hash). Expect
   `re_embedded ≫ copied` for the affected notebooks; 2-4 hours of
   additional CPU on top of the original B-3 measurement window.
3. THEN record the B-3 nDCG@5 baseline + post-bump numbers against
   `var/arxmcp/notebooks/bridgeland-stability/queries.json`. The
   preamble re-population is part of the measurement window — comparing
   pre-preamble vs post-preamble retrieval is a meaningful signal
   independent of the token-budget bump.

If you'd rather measure B-3 with the embedder-truncation-m1 changes in
isolation (no preamble confound), run `make eval` against the live
bridgeland-stability notebook BEFORE running `make ingest-recover-preambles`,
then re-measure AFTER. The delta isolates the preamble contribution.
