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

## 3. notebook-preamble-recovery-m1 — AC3 explicit operator deliverable

**AC3:** the back-fill must recover preamble.json for ≥ 90% of the 137
already-ingested ar5iv-only papers (the count as of 2026-05-28; verify
via `ls var/arxmcp/corpus/parsed/ | wc -l` at run time).

**Checklist (operator):**
1. Run `make ingest-recover-preambles` (estimated ~7 minutes at 3 s/paper
   politeness for 137 papers; longer if any 503 backoff hits).
2. Read the final summary line — record `total=N` and
   `preamble_recovered=P`.
3. Compute `P / N`. AC3 PASS iff `P / N ≥ 0.90`.
4. If AC3 FAILS: inspect the stderr categories — `withdrawn_404`
   (unrecoverable; subtract from denominator before re-judging),
   `security_events` (investigate the tarball), `other_fetch_errors`
   (re-run; transient).
5. Record `P`, `N`, and the pass/fail ratio in this file under a new
   "AC3 measurement (recorded by operator on YYYY-MM-DD)" section.

## 4. notebook-preamble-recovery-m1 — AC6 `get_definitions` canary

**AC6:** after the back-fill + a subsequent `make re-embed-all`, the
`get_definitions` MCP tool must return `total > 0` for at least one
canary paper that previously returned `{total: 0,
index_status: "absent"}`.

**Checklist (operator):**
1. Pick a canary paper from the bridgeland-stability notebook that is
   known to use `\newcommand` (any paper from the 2010s-era list; e.g.
   `1207.4980` which uses `\AA`, `\Hom`, etc.).
2. BEFORE running `make ingest-recover-preambles`, call
   `get_definitions` for the canary via the MCP server and confirm the
   current state is `{total: 0, index_status: "absent"}`.
3. Run `make ingest-recover-preambles` then `make re-embed-all`.
4. After re-embed completes AND the definitions indexer has run (see
   `ingest/index_definitions.py` — may need a separate
   `python -m ingest.index_definitions` invocation; check the runbook),
   call `get_definitions` for the canary again.
5. AC6 PASS iff the post-back-fill result has `total > 0` AND each
   definition row carries `lhs` + `rhs` + `paper_id == <canary>`.
6. Record canary paper_id, before-total, after-total, and a sample
   definition row in this file under a new "AC6 measurement" section.

## Why these checklists live here

Per the F5 finding in the notebook-preamble-recovery-m1 critique
(`.claude/notes/milestones/notebook-preamble-recovery-m1/critique-merged.md`):
"deferred-to-operator with no enumerated check" is the exact failure
mode this file was created to prevent. Explicit checklist items force
the deliverable into the operator's workflow rather than letting it
silently drop.
