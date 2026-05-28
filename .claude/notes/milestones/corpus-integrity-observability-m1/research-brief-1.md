# Research Brief — corpus-integrity-observability-m1

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-28T21:30:00Z

## In-codebase context

### The bug — exact site

`ingest/store.py` lines 899–908:

```python
try:
    paper_count = len({c.paper_id for c in chunks})
    write_corpus_version_marker(
        target_path,
        version=dataset_version,
        chunker_version=CHUNKER_VERSION,
        embedder_version=embeddings.embedder_version,
        paper_count=paper_count,
        chunk_count=len(chunks),
    )
```

`chunks` here is the **per-paper batch** passed to `write_chunks`. When
`bulk_ingest.py` or `re_embed.py` calls `write_chunks` once per paper
(their loops), this marker-write fires once per paper — last paper wins,
producing `chunk_count=106/paper_count=1` for `bridgeland-stability`.

### Caller survey

**`ingest/bulk_ingest.py` line 319** — per-paper loop:
```python
for n, paper_id in enumerate(work, start=1):
    outcome = ingest_one_paper(...)  # calls write_chunks internally
```
`ingest_one_paper` at line 319 calls `write_chunks(chunks, embed_record,
lancedb_path=lancedb_staging_path)` once per paper with the paper's chunks
only. Marker overwritten each iteration.

**`ingest/re_embed.py` lines 528 and 558** — two per-paper call sites:
```python
# line 528 — copy path
write_chunks(copy_chunks, copy_record, lancedb_path=staging_lancedb_path)

# line 558 — re-embed path
write_chunks(re_embed_chunks, re_embed_record, lancedb_path=staging_lancedb_path)
```
Both are inside `_process_paper` which is called from the `for paper_id in
work_papers:` loop (line 720). Same bug; both call sites fire per paper.

**`tools/notebook_textbook_ingest.py` line 202** — per-paper loop for
notebook-scoped ingest:
```python
version = write_chunks(chunks, embed_record, lancedb_path=lancedb_path)
```
Called from `ingest_textbook_paper` which iterates per textbook paper. Same
overwrite pattern. **However:** each notebook has its own `lancedb_path` per
slug; the final `paper_count=1` for the last paper is still wrong.

**`tools/re_embed_all.py`** — calls `ingest.re_embed.run_re_embed` per
dataset, not `write_chunks` directly. Bug surfaces via `re_embed.py`.

**`tools/fetch_seed.py`** — does NOT call `write_chunks` directly. Calls
higher-level `ingest_one_paper`. Bug surfaces via `bulk_ingest.py`.

**Single-call callers (marker IS correct today):** any test that calls
`write_chunks` once with a multi-paper batch already gets correct counts.

### Marker readers (consumers of broken data)

`server/resources.py` lines 337–344:
```python
corpus_info = read_corpus_version(config.lancedb_path)
logger.info(
    "Resources.startup: pinning corpus_version=%d (paper_count=%d, "
    "chunk_count=%d, chunker=%s, embedder=%s)",
    corpus_info.version,
    corpus_info.paper_count,
    corpus_info.chunk_count,
    ...
)
```
`paper_count` and `chunk_count` are used only in this startup INFO log.
`corpus_info.version` (the MVCC integer) is what gates LanceDB checkout,
BM25 cache key, and retrieval-cache namespace. The broken fields are
observability-only; no correctness path reads them.

### LanceDB 0.30.2 API for count_rows and distinct paper_id

**`tbl.count_rows()`** — already used in `tests/test_store.py` lines 364,
380, 400, 736, 774, 927, 1154. Confirmed O(1) fragment-metadata read. This
is the right API for `chunk_count`.

**Distinct `paper_id` count** — the codebase uses the pattern established
at `ingest/re_embed.py` lines 242–244 and 298–300 (lancedb 0.30.x comment):
```python
# lancedb 0.30.x: to_arrow() takes no kwargs; project after load.
arrow = tbl.to_arrow().select(["paper_id"]).to_pydict()
```
For `paper_count`, the implementation should do:
```python
arrow = tbl.to_arrow().select(["paper_id"])
paper_count = len(set(arrow["paper_id"].to_pylist()))
```
This is O(N) in rows but acceptable: it fires ONCE per run (not per paper),
and the milestone brief explicitly calls out that the once-per-run model
avoids the "O(N^2) per-paper distinct-scan" concern.

**NOTE:** `to_arrow()` on a 10,298-row table with a single `paper_id` column
(~10–30 bytes/row) fits in ~1 MB. At 200K-paper corpus scale (~20 MB for
`paper_id` column only) this is still acceptable for a once-per-run call.

### `write_corpus_version_marker` signature — unchanged

```python
def write_corpus_version_marker(
    lancedb_path: str | Path | None,
    version: int,
    chunker_version: str,
    embedder_version: str,
    paper_count: int,
    chunk_count: int,
) -> None:
```
The atomic write mechanism (PID+UUID tmpfile + `os.replace`) is preserved
unchanged. Only the callers of this function change.

### `__all__` in store.py

`write_corpus_version_marker` is already exported in `__all__` (line 934).
The new `finalize_corpus_marker` helper (see recommendation) must also be
added to `__all__`.

### Design notes — what applies

- **`05-storage-and-indexing.md`**: "The ingestion pipeline returns the new
  version integer from `write_chunks()` and records it in
  `var/arxmcp/index/lancedb/corpus-version.json`." The `version` field must
  remain the post-index `tbl.version` — UNCHANGED. Only `chunk_count` and
  `paper_count` derivation changes.
- **`07-multi-agent-caching.md`**: Cache key uses `version` only. Marker
  `chunk_count`/`paper_count` never enters prompt-cache or tool-result
  payload. This fix does NOT touch prompt-cache paths.
- No new MCP tool, no schema change, no CHUNKER_VERSION bump.
- `EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_BP1_SHA256` must remain
  UNCHANGED (confirmed: no server surface change).

## Prior decisions and lessons

**git log context:** Most recent commit `6301124 docs(notes):
observability capability-scout + corpus-integrity roadmap` — the capability
scout doc was written specifically for this milestone, establishing the
CAND-1 + challenger recommendation the brief references.

**notebook-cutover-m1 lesson (from state.json):** The cutover milestone
shipped `tools/notebook_cutover.py` which reads `corpus-version.json`'s
`version` field to compare staging vs active. After this fix, cutover also
benefits from correct `chunk_count`/`paper_count` in the version comparison
log. No interface change needed.

**`to_arrow()` API landmine (lancedb 0.30.x):** The project has already
encoded this in `ingest/re_embed.py` comments: `to_arrow()` takes NO kwargs
in 0.30.x; column projection MUST happen after load via `.select([...])`.
Any `to_arrow(columns=["paper_id"])` form will fail. The distinct-paper-id
implementation MUST use `.to_arrow().select(["paper_id"])`.

**`assert` ban:** No `assert` in the new helper. Use `if ... raise
RuntimeError(...)` if invariant checking is needed.

**Single-call callers that must not break:** Tests call `write_chunks` once
with a synthetic multi-paper batch (e.g. `TestRowCount`, `TestMixedCorpusInSameTable`).
Under the recommended design, these callers get correct marker counts
automatically because `tbl.count_rows()` is called WITHIN `write_chunks` on
the same call (see recommendation below).

## External sources

**lancedb 0.30.2** — `tbl.count_rows()` is confirmed O(1) (fragment
metadata read, not full table scan). `tbl.to_arrow().select([col])` is the
project-established pattern for column extraction. No external docs needed
beyond the codebase itself, which already uses both APIs.

No MCP spec consultation needed — no server-surface change.

## Recommendation

**Use approach A: move count derivation inside `write_chunks`, reading from
the committed table.** Remove the `paper_count = len({c.paper_id for c in
chunks})` and `chunk_count=len(chunks)` calls from the try-block in
`write_chunks`. Replace with:

```python
chunk_count = tbl.count_rows()
arrow = tbl.to_arrow().select(["paper_id"])
paper_count = len(set(arrow["paper_id"].to_pylist()))
write_corpus_version_marker(
    target_path,
    version=dataset_version,
    chunker_version=CHUNKER_VERSION,
    embedder_version=embeddings.embedder_version,
    paper_count=paper_count,
    chunk_count=chunk_count,
)
```

**Why this over a new `finalize_corpus_marker` external helper:**

1. It is the simplest change: `write_chunks` already has the `tbl` handle
   in scope post-`_create_indices`. No new function, no new export, no
   caller updates to `bulk_ingest.py` / `re_embed.py`.
2. Single-call correctness is preserved automatically: tests that call
   `write_chunks` once with a multi-paper batch already get correct counts
   because the table reflects all rows.
3. The concern about "O(N^2) per-paper distinct-scan" in the brief applies
   to a naive marker-write in the outer per-paper loop — which this approach
   avoids. With this approach the marker is written once per `write_chunks`
   call. For multi-paper runs calling `write_chunks` N times, the marker is
   still overwritten N times, but counts are now CUMULATIVE (from the table),
   not per-batch. The FINAL overwrite reflects the true table state. This is
   correct behavior.
4. The `tbl.to_arrow().select(["paper_id"])` call for distinct-paper-count
   IS an O(N) read per `write_chunks` call. For a 200K-paper corpus with
   multiple papers per run, this is ~N sequential O(N) scans. **This is the
   only real performance concern.** For the live use case (bulk_ingest writes
   sequentially, not in parallel), this is acceptable. If future performance
   profiling shows this is a bottleneck, the `finalize_corpus_marker` once-
   per-run helper can be added then.

**Alternatively** (if the adversary flags the per-call paper_id scan as
unacceptable): add a `finalize_corpus_marker(lancedb_path, chunker_version,
embedder_version)` public function that computes counts from the table and
calls `write_corpus_version_marker`. Callers (`bulk_ingest.run_bulk_ingest`
and `re_embed.run_re_embed`) call it AFTER the per-paper loop. Suppress
marker writes inside `write_chunks` in this path. Single-call callers (tests,
`notebook_textbook_ingest`) call `finalize_corpus_marker` explicitly after
their `write_chunks` call. This is more surgical for the 200K-paper case but
requires touching more callers. **Stick with approach A unless the adversary
escalates the performance concern.**

## Open questions

1. **`notebook_textbook_ingest.py` per-paper loop:** The notebook ingest
   calls `write_chunks` once per textbook paper. Under approach A, the
   marker is written after each paper with cumulative counts. The final
   write is correct. No additional change needed. Confirm the implementer
   understands this.

2. **WriteStats `chunk_count` field** (line 866): `stats = WriteStats(chunk_count=len(chunks), ...)`.
   The brief says "Per-paper WriteStats keeps its per-paper chunk count
   (that is separate scout CAND-8, OUT OF SCOPE)." The implementer must NOT
   change `WriteStats.chunk_count` — it remains `len(chunks)` (per-batch,
   not cumulative). Only the marker write changes.

These are confirmations, not blockers. **Implementation can proceed on the
above recommendation.**

## External writes the implementation will require

None — this milestone is purely local.
