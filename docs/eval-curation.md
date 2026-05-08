# Eval-fixture curation runbook (E05_S01)

This runbook documents the manual process by which a human curator
populates `tests/eval/fixtures/queries.json` with 20 hand-labeled
`(query, chunk_id, relevance)` triples. The output of this runbook is
the **ground-truth retrieval-quality dataset** used by the E05_S02
harness to compute nDCG@5 and Recall@10 against the pinned corpus.

The curation pass cannot be automated. The brief is explicit: *"the
implementer cannot automate the curation itself (that would make the
eval circular)."* An LLM-generated fixture would test whether the
retrieval system reproduces an LLM's preferences, not whether it
matches a human researcher's notion of relevance — the wrong target.

The runbook is the curator's contract. Skipping a step means the
metric you compute later is not the metric you advertised.

## When to (re)run this runbook

| Trigger | Required action |
|---|---|
| First-time curation (this milestone) | Full pass — produce 20 triples. |
| `CHUNKER_VERSION` bump (`ingest/chunker_types.py`) | Re-validate every `chunk_id`; re-curate where stale. |
| Seed corpus changes (papers added or replaced) | Re-curate any query whose `relevant_chunks` referenced a removed paper. |
| `schema_version` bump in `queries.json` | Update `created_at`; re-validate full file. |
| AC-7 quotas change in `tools/validate_eval_fixtures.py` | Adjust the `kind` distribution. |

The validator's `chunker_version` mismatch error is your tripwire — if
you see it, stop and re-curate. Do **not** edit the fixture's
`chunker_version` field to silence the error; that would invalidate
the stored chunk_ids without you noticing.

## Prerequisites

1. The 50-paper seed corpus has been chunked. Run:
   ```
   tools/fetch_seed.py
   # then the chunker — see ingest/chunker.py public API
   ```
   At completion, `var/arxmcp/corpus/chunks/<paper_id>/chunk_manifest.json`
   exists for each paper.
2. The chunked output is reviewable. The curator reads each
   manifest's `chunks` list (chunk_id + kind) AND the corresponding
   chunk body text — body lives in
   `var/arxmcp/corpus/chunks/<paper_id>/<chunk_id>.json` (per
   `ingest/chunker.py::_write_chunk`).
3. You know the math.AG domain well enough to judge "is this chunk
   the primary answer to that query?" Curate-by-keyword-match is the
   common failure mode and produces a worthless eval set.

## The 20-query design

Per the brief, queries should span the math.AG domain across three
dimensions. The 20-query budget is your pacing target:

- **Theorems (~7 queries):** Riemann-Roch, Grothendieck-Riemann-Roch,
  Serre duality, Hirzebruch-Riemann-Roch, Hodge index theorem, etc.
- **Constructions (~7 queries):** Picard group, derived category of
  coherent sheaves, Hilbert scheme, moduli of vector bundles,
  Chern character, blow-up of a subvariety, etc.
- **Proof techniques (~6 queries):** spectral sequences, resolution
  of singularities, descent along faithfully flat morphisms,
  reduction to the affine case, deformation arguments, etc.

**Phrasing diversity is mandatory.** Mix:
- Formal LaTeX-shaped: `"Spec(O_X) for affine schemes"`
- Mid-formal: `"Riemann-Roch theorem for algebraic curves"`
- Informal: `"how do we compute global sections of a line bundle"`
- Fragment: `"derived equivalence Picard"`

Skipping diversity makes the eval brittle to query-style perturbations
that real users will produce.

**Kind quotas (AC-7).** At least 5 of your 20 queries must have at
least one `relevant_chunks` entry resolving to a `kind="stmt"` chunk
(theorem statements). At least 5 queries must resolve to a
`kind="proof"` chunk. The chunker assigns these kinds at chunking
time; the manifest carries them. The validator reads the manifest to
enforce this. Plan your queries against the kind distribution
**before** you start labeling — most theorem chunks are `stmt`-kind
and proof-construction queries naturally pair with `proof`-kind.

## The labeling discipline

For each query:

1. Write the `query_text` first. Do NOT scan chunks looking for a
   matching theorem and back-form the query — that biases the eval
   toward the system's own preferred phrasing.
2. List **every** chunk in the corpus that you would expect to be in
   the top-10 if the system were perfect. Most queries have 1-3
   relevant chunks; some have more.
3. Grade each on the 0-3 scale:

| grade | meaning | example |
|---|---|---|
| **3** | Primary answer. The chunk literally is the theorem statement / construction asked for. | Query "Riemann-Roch for algebraic curves" → the chunk containing `\begin{theorem}[Riemann-Roch]...` |
| **2** | Direct addressee. The chunk addresses the question but is not the canonical statement. | Same query → a chunk that proves a corollary OF Riemann-Roch using its statement. |
| **1** | Useful context. Background a researcher would want one click away. | Same query → a chunk introducing line bundles on curves (foundational). |
| **0** | Not relevant. Do NOT include in `relevant_chunks` — absent chunks are graded 0 by default. | (do not list) |

4. **Each query MUST have at least one grade-3 chunk** (AC-2).
   Without a grade-3 there is no ideal-DCG denominator and the nDCG
   computation diverges. If you cannot find a grade-3 chunk for a
   given `query_text`, the query is not curatable against this
   corpus — pick a different query.
5. **Do not include zero-relevance chunks.** Listing every chunk
   you think might be borderline-relevant inflates the relevance set
   and corrupts Recall@10.

The lower the false-positive rate in your `relevant_chunks` list, the
more discriminative the resulting nDCG@5 score.

## Editing `queries.json` mechanically

The fixture file format (per
`tools/validate_eval_fixtures.py::DEFAULT_FIXTURE_PATH`):

```json
{
  "schema_version": "1.0",
  "chunker_version": "v1.0",
  "created_at": "2026-05-08",
  "queries": [
    {
      "query_id": "q01",
      "query_text": "Riemann-Roch theorem for algebraic curves",
      "relevant_chunks": [
        {"chunk_id": "arxiv:2301.00001:abc123def4567890", "relevance": 3},
        {"chunk_id": "arxiv:2301.00002:ff11223344556677", "relevance": 1}
      ]
    }
  ]
}
```

- `query_id`: zero-padded `q01`..`q20`. Unique within the file
  (validator enforces).
- `query_text`: arbitrary non-empty string.
- `relevant_chunks`: non-empty list.
- `chunk_id`: copy verbatim from a `chunk_manifest.json`. Do not
  reconstruct by hand — the SHA-256 suffix is content-addressed and
  one mistyped hex character marks the entry as stale.
- `relevance`: integer 0-3 (the validator rejects 4+, floats, and
  booleans).

**Never include** a `created_at` per-query field, an `_curation_status`
flag, or any other key not in the brief schema. The validator rejects
unknown top-level keys at the next schema bump; per-query unknown
keys are currently allowed but discouraged for byte-stability.

## Validating your work

Run the validator after every edit:

```
python tools/validate_eval_fixtures.py
```

Or via pytest:

```
pytest tests/eval/test_fixtures.py
```

Both invocations are equivalent — the pytest wrapper calls the
validator's `validate()` function. Failures print a single `FAIL:`
line citing the exact AC item or invariant that fired (e.g. `"AC-2
requires ≥ 1 grade-3 per query"`).

The validator runs as part of `make test`. Do not commit a fixture
that breaks `make test`.

## On `created_at`

The fixture's top-level `created_at` field is intentionally a fixed
string, not a `datetime.now()` call. Update it on `schema_version`
bumps only — not on every edit. The field is documentation, not
runtime input. The validator does not read it.

This convention exists because the fixture lives in source control;
mutating `created_at` on every edit creates churn and obscures the
real signal in `git blame` (which curator added which query). The
brief's design (`07-multi-agent-caching.md` BP1 byte-stability) does
not strictly require this — the fixture isn't in the cache key — but
the convention preserves the audit trail.

## When the curator's quota collides with reality

Sometimes a planned query has no grade-3 chunk in the seed corpus.
Two responses:

1. **Pick a different query** (preferred). The 20-query budget has
   slack — drop a marginal query rather than label a 2 as a 3.
2. **Add the paper** to the seed corpus. Coordinate with whoever owns
   `tools/seed-papers.txt`; this changes the corpus, so plan it
   deliberately.

Do **not** rationalize "this is a 3 because I want this query in".
The validator can't catch that, and it silently corrupts every nDCG@5
number you compute thereafter.

## When you're done

1. The fixture has exactly 20 entries.
2. Every entry has at least one grade-3 `chunk_id`.
3. At least 5 queries reference `kind="stmt"` chunks; at least 5
   reference `kind="proof"` chunks.
4. `python tools/validate_eval_fixtures.py` exits 0.
5. `make test` is green.

Commit with the message `data(eval): hand-labeled 20-query fixture
(E05_S01)`. The implementer cannot author this commit; the curator
is the author of record.

## Related

- `tools/validate_eval_fixtures.py` — the validator's docstring
  documents the full behavior matrix and per-error explanation.
- `tests/eval/test_fixtures.py` — locks the validator's behavior
  against regression.
- `ingest/chunker_types.py::CHUNKER_VERSION` — the constant whose
  bump triggers a re-curation pass.
- E05_S02 — consumer of this fixture; computes the actual nDCG@5
  number used in the Tier-0 exit gate.
