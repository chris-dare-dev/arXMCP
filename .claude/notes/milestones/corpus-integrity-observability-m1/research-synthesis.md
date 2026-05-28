# Research Synthesis — corpus-integrity-observability-m1

**Merged from:** research-brief-1.md (in-codebase + seam) + research-brief-2.md (failure modes)
**Generated:** 2026-05-28
**Verdict:** INLINE, ~3–6 LOC in `ingest/store.py` + 1 regression test. Purely local. Closes task #26.

## 1. The locked design

**Keep the `corpus-version.json` marker write INSIDE `ingest/store.py::write_chunks`
(per-call), but derive the counts from the committed table instead of the
in-flight batch.** Both researchers independently converged on this and AGAINST
the roadmap m1's stated "move write_corpus_version_marker out of the per-paper
loop to once-per-run" — that move is wrong (see §4).

The exact change at `ingest/store.py:899-908` (verbatim today):
```python
paper_count = len({c.paper_id for c in chunks})
write_corpus_version_marker(
    target_path, version=dataset_version, chunker_version=CHUNKER_VERSION,
    embedder_version=embeddings.embedder_version,
    paper_count=paper_count, chunk_count=len(chunks),
)
```
becomes (approach A, researcher-1; the `tbl` handle is already in scope
post-`_create_indices`):
```python
chunk_count = tbl.count_rows()                       # O(1) — Lance fragment metadata
arrow = tbl.to_arrow().select(["paper_id"])          # NB: 0.30.x — NO to_arrow(columns=)
paper_count = len(set(arrow["paper_id"].to_pylist()))
write_corpus_version_marker(
    target_path, version=dataset_version, chunker_version=CHUNKER_VERSION,
    embedder_version=embeddings.embedder_version,
    paper_count=paper_count, chunk_count=chunk_count,
)
```

**Why this is correct.** `bulk_ingest`/`re_embed`/`notebook_textbook_ingest` call
`write_chunks` once per paper; the marker is overwritten each call, but now with
CUMULATIVE table counts, so the FINAL overwrite reflects the true table state.
`version` stays `dataset_version = tbl.version` (the post-index MVCC integer) —
UNCHANGED. `WriteStats.chunk_count` stays `len(chunks)` (per-batch — that is the
separate scout CAND-8, OUT OF SCOPE here).

## 2. Load-bearing facts (quoted, both briefs concur)

- **The bug + readers.** Marker `chunk_count`/`paper_count` are read ONLY by the
  `server/resources.py:337-344` startup INFO log + `server/corpus.py` `to_dict`.
  `corpus_info.version` (not the counts) gates `dataset.checkout(N)`, the BM25
  cache key, and the retrieval-cache namespace. **The fix touches no correctness
  path, no prompt-cache path, no tool schema.** `EXPECTED_TOOL_SCHEMA_SHA256` +
  `EXPECTED_BP1_SHA256` UNCHANGED; no `CHUNKER_VERSION` bump (KR-3 / X-gates).
- **Per-paper callers** (brief-1 §Caller survey, brief-2 §Callers): `bulk_ingest.py:319`
  (`ingest_one_paper`), `re_embed.py:528` (copy path) + `:558` (re-embed path),
  `tools/notebook_textbook_ingest.py:202`. All per-paper; all fixed by the
  in-`write_chunks` table-derived counts with NO caller edits.
- **lancedb 0.30.x trap (FM-5, both):** `to_arrow()` takes NO kwargs — must use
  `tbl.to_arrow().select(["paper_id"])`, never `to_arrow(columns=...)`. This is
  already documented in `ingest/re_embed.py:242,298,324` (the trap that bit the
  earlier re_embed work). `count_rows()` is confirmed O(1).
- **re_embed already worked around this bug** (brief-2): `ingest/re_embed.py:149-151`
  comments that "corpus-version.json is overwritten by write_chunks on every
  per-paper call (no status field), so we carry the status contract in
  [re-embed-progress.json] instead of patching write_chunks." That companion file
  stays (it carries a status contract write_chunks doesn't); after this fix the
  marker's counts are simply correct.
- **Atomic marker write preserved.** `write_corpus_version_marker` keeps its
  PID+UUID tmpfile + `os.replace` mechanism (brief-1); only its caller's arguments
  change. Its signature is UNCHANGED under approach A.

## 3. Failure modes (brief-2, the primary deliverable)

- **FM-1 crash-safety — RESOLVED by keeping the per-call write.** Approach A
  writes a correct marker after EVERY paper (the table reflects all rows
  committed so far), so a mid-run crash always leaves a marker consistent with
  the committed table — strictly BETTER than today and equal to today's
  crash-continuity. (The once-per-run move would open a crash gap — a reason it
  was rejected.)
- **FM-2 cost — the one real trade-off (see §4).** `count_rows()` O(1) ✓. The
  distinct-`paper_id` scan via `to_arrow().select(["paper_id"])` materializes the
  `paper_id` column (~200 KB at the bridgeland 10,298-row scale; ~4 MB at 200K
  rows) per `write_chunks` call → O(N²) over a 200K-paper bulk run.
- **FM-3 MVCC version skew — non-issue.** Approach A reads/writes the marker
  inside `write_chunks` immediately after `_create_indices` (exactly as today),
  using `dataset_version = tbl.version`. No compaction window opens. (The
  once-per-run move would have introduced this skew — another reason it's wrong.)
- **FM-4 single-call callers — RESOLVED by keeping the write in `write_chunks`.**
  `notebook_textbook_ingest` + every test that calls `write_chunks` once still
  gets a marker, now with correct table counts. (Moving the write out was the
  CRITICAL break that both briefs flag against.)
- **FM-6 idempotency — improved.** Counting the table (not the batch) is
  inherently idempotent: a re-run upsert yields the same `count_rows()`.
- **FM-7 empty-chunks path** — `write_chunks([], ...)` returns early today;
  table-derived counts on a later non-empty call are correct. No regression.

## 4. Orchestrator synthesis note — divergences resolved

**Divergence 1 (vs the roadmap m1 design): "move the marker write once-per-run."
REJECTED.** Both researchers found this breaks single-call notebook callers
(FM-4, CRITICAL) and opens a crash gap (FM-1) + MVCC skew (FM-3). The roadmap's
"once per run" was the scout *challenger*'s suggestion to dodge an O(N²) scan;
the researchers found a strictly better trade-off. **m1's AC is therefore
RELAXED from "marker written once per run" to "marker counts == live table
counts after a multi-paper run"** — the once-per-run phrasing was a means, not
the end, and the means was wrong. (Documented as a deviation in the impl summary.)

**Divergence 2 (between the briefs): `paper_count` via per-call table scan (R1,
approach A) vs a caller-maintained running `seen_paper_ids` set (R2).** RESOLVED
→ **approach A for v1**, with R2's running-set documented as the escalation path.
Reasoning:
- The O(N²)-at-200K-papers concern is a FUTURE-scale issue: the 200K full-corpus
  bulk path is E11/E12, which CLAUDE.md §3 marks SCOPED-OUT/folded. The realistic
  paths today are the 50-paper seed and per-notebook re-embeds (tens of papers,
  ≤10K-row tables) — where the per-call column materialization is ~µs-ms and
  negligible (brief-1: ~200 KB Arrow buffer).
- Approach A is ~3 LOC in ONE file with ZERO caller edits; R2's running-set adds
  an optional `cumulative_paper_ids` param to `write_chunks` + accumulator logic
  in `bulk_ingest` AND `re_embed`'s two-path dispatch — materially more surface
  and risk for a correctness fix whose AC approach A fully meets.
- **Escalation hook:** if the Phase-3 adversary judges the per-call O(N) scan
  unacceptable, Phase-4 rectification adds R2's running-set (or a
  `finalize_corpus_marker` once-per-run-with-per-paper-fallback). Both briefs
  agree approach A is the right starting point and R2 is the documented fallback.

## 5. Acceptance criteria (from roadmap m1, AC-2 relaxed per §4)

1. After a multi-paper ingest/re-embed run, `corpus-version.json::chunk_count ==
   tbl.count_rows()` AND `paper_count ==` the distinct-`paper_id` count of the
   committed table.
2. ~~Marker written once per run~~ → **Marker counts reflect the cumulative table
   (not the last batch)**; the write stays in `write_chunks` (per-call) for
   crash-safety + single-call-caller correctness.
3. A regression test calls `write_chunks` ≥2 times with disjoint single-paper
   batches against one `lancedb_path`, then asserts the final marker's
   `chunk_count == tbl.count_rows()` and `paper_count == 2` — it MUST FAIL on the
   pre-fix code (which records the last batch: `chunk_count=<last>`, `paper_count=1`).
4. `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` UNCHANGED; no
   `CHUNKER_VERSION` bump; `make test` green.

## 6. Open questions (both resolved)

- **`WriteStats.chunk_count` (store.py:866)** — stays `len(chunks)` (per-batch);
  NOT changed here (scout CAND-8, out of scope). Both briefs agree.
- **`paper_count` seam** — RESOLVED in §4 (approach A; running-set is the
  documented escalation, not v1).
- **`re-embed-progress.json` companion** — unaffected; it carries a status
  contract the marker doesn't. No change.

No blocking open questions; implementation can proceed.

## 7. External writes required

**None** — purely local: `ingest/store.py` (+ one new/extended test under
`tests/`). No git push, PR, infra, or third-party API. (Both briefs concur.)
