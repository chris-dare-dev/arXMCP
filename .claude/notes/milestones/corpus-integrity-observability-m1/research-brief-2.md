# Research Brief — corpus-integrity-observability-m1

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-28T21:05:00Z

---

## In-codebase context

### The bug — verbatim code

`ingest/store.py:900-907`:
```python
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

`chunks` is the per-paper batch supplied to ONE `write_chunks` call. In a
50-paper run, the marker is overwritten 50 times; the final file holds the
counts of the last paper alone (e.g., `chunk_count=106`, `paper_count=1`
vs. `chunk_count=10298`, `paper_count=50` in the table).

### `version` is NOT affected

`dataset_version = int(getattr(tbl, "version", 0) or 0)` (line 862) reads
`tbl.version` AFTER `_create_indices` completes — this is the correct
post-index MVCC integer. The milestone brief confirms: "version is correct;
only the counts lie." The MVCC handshake (`server.corpus.open_chunks_table`
using this integer for `dataset.checkout(version=N)`) is unaffected.

### Callers of `write_chunks`

Every current production caller writes one paper per call:
- `ingest/bulk_ingest.py:319` — `version = write_chunks(chunks, embed_record, lancedb_path=lancedb_staging_path)` inside a per-paper loop
- `ingest/re_embed.py:528,558` — two paths (copy + re-embed), both per-paper
- `tools/notebook_textbook_ingest.py:202` — per-paper, notebook-scoped LanceDB

The `bulk_ingest.py` module docstring (line 10-18) explicitly acknowledges:
> `ingest.store.write_chunks` writes a `corpus-version.json` marker as a
> post-write step. Writing into the active dataset would advance the marker
> per-paper... The staging path keeps every per-paper write isolated.

This staging-path design was intentional; the per-paper marker overwrite was
documented as a known limitation, not an oversight.

### Server startup contract

`server/resources.py:329-336`:
```python
corpus_info = read_corpus_version(config.lancedb_path)
if corpus_info is None:
    marker = Path(config.lancedb_path) / "corpus-version.json"
    raise CorpusNotIngestedError(...)
```

`server/corpus.py:45`: "Missing `corpus-version.json` → `CorpusNotIngestedError`"

The server refuses to start if the marker is absent. The counts in the marker
are logged at INFO (`paper_count`, `chunk_count`) but not used for correctness
— confirmed by the milestone brief: "impact is purely observability (no
correctness reader)." The version integer IS used for `dataset.checkout(N)`.

### lancedb 0.30.x API constraints

Multiple files document the API breakage:
- `ingest/re_embed.py:242`: `# lancedb 0.30.x: to_arrow() takes no kwargs; project after load.`
- `ingest/re_embed.py:298`: same comment
- Confirmed by live introspection: `to_arrow(self) -> pa.Table` (no kwargs)
- `count_rows(self, filter: Optional[str] = None) -> int` is O(1) (confirmed live)
- `group_by` on a PyArrow table is the correct distinct-paper_id pattern:
  `tbl.to_arrow().select(["paper_id"]).group_by("paper_id").aggregate([]).num_rows`

---

## Failure-mode analysis — PRIMARY DELIVERABLE

### FM-1: Crash mid-run between last `write_chunks` and once-per-run marker write

**Trigger.** N papers written successfully to LanceDB; process crashes before
the post-loop `write_corpus_version_marker` call. The table has all N papers'
rows but the marker on disk is either (a) absent (first run) → server raises
`CorpusNotIngestedError` and refuses to start, or (b) stale from the PREVIOUS
run → server starts but pins an old version.

**Observable symptom.** (a) `CorpusNotIngestedError` at startup — operator
must re-run ingest or manually write the marker. (b) Silently serves old data
version with correct version integer from old marker — actually less harmful
than (a), but the counts are still wrong.

**Is the current per-paper marker a resilience feature?**
YES, partially. Today the per-paper marker overwrite means that after any
crash, the marker's `version` integer is at least as current as the last
successful per-paper commit. The tables rows ARE there (LanceDB MVCC committed
them), and the marker version points to that LanceDB version. Moving the
marker write outside the loop removes this crash-continuity property.

**Mitigation options:**
1. **Per-paper marker with TABLE counts** — keep marker write inside the loop,
   but compute `chunk_count` from `tbl.count_rows()` and `paper_count` from
   the distinct-paper_id scan after each write. This is crash-safe: after any
   crash the marker accurately reflects the current table state. Cost: O(N)
   marker writes, each costing `count_rows()` (O(1)) + `to_arrow().select(["paper_id"])` (O(table rows)).
2. **Once-per-run marker** — move marker write outside the loop. Crash-safe gap
   between last `write_chunks` and final marker write. Mitigated by the
   `re-embed-progress.json` sentinel pattern (`ingest/re_embed.py:152`) which
   is checked by E11_S05's cutover gating. The staging path never feeds the
   live server directly.

**My recommendation: per-paper marker with TABLE counts** (see Recommendation section).

### FM-2: `count_rows()` cost

**Trigger.** `count_rows()` is called inside the per-paper loop after every
`write_chunks` on the Bridgeland table (~10,298 rows; full corpus ~5M rows).

**Observable symptom.** Confirmed via live introspection: `count_rows(self,
filter=None)` is O(1) in LanceDB 0.30.x (it reads a metadata manifest, not the
data files). Safe to call per-paper at any table size. No perf regression.

**Distinct paper_id count cost.** `tbl.to_arrow().select(["paper_id"])` loads
the full `paper_id` column. At 10,298 rows × ~20 bytes/paper_id ≈ 200 KB Arrow
buffer. At 200K rows × 20 bytes ≈ 4 MB. This is acceptable once per run, but
per-paper on a 200K-paper run means 200K × 4 MB = 800 GB of total I/O — not
acceptable. However: PyArrow `group_by("paper_id").aggregate([])` is efficient
but still requires materializing the column. The better pattern for the
per-paper case is a **running counter**: maintain `seen_paper_ids: set[str]`
in the calling loop and pass `len(seen_paper_ids)` to the marker. This
eliminates the O(N²) full-table scan while remaining crash-safe.

**Cheaper alternative:** `tbl.count_rows()` for `chunk_count` (O(1)), and the
running set maintained by the caller for `paper_count` — no full-table scan
needed. This is the recommended seam.

### FM-3: MVCC version skew between marker and table state

**Trigger.** Once-per-run marker write happens AFTER some unrelated
cleanup/compaction runs on the LanceDB dataset. `_create_indices` inside
`write_chunks` may advance `tbl.version` by 1–3 versions per call (per
`ingest/store.py:68-72`). If a compaction or cleanup runs between the last
`write_chunks` return and the once-per-run marker write, `tbl.version` will
have advanced, potentially to a version that no client yet holds a
`checkout()` for.

**Observable symptom.** Marker records a version N+k (k>0) that was produced
by compaction, not by the last `write_chunks`. The server checks this version
via `dataset.checkout(version=N+k)` — this succeeds (the data is present), but
`N+k` might be a compaction-only version with no data change. In practice,
single-writer constraint (per `ingest/store.py:44-55`) prevents concurrent
compaction during ingest. Risk is LOW for this milestone.

**Mitigation.** The once-per-run marker must read `tbl.version` at the same
point the marker is written, not cache the version from the last
`write_chunks` return. Implementation must do `final_version =
int(getattr(tbl, "version", 0) or 0)` immediately before the marker write.

### FM-4: Single-call callers lose their marker — CRITICAL RISK

**Trigger.** `tools/notebook_textbook_ingest.py:202` calls `write_chunks` for
a single-paper notebook LanceDB. If `write_corpus_version_marker` is moved
ENTIRELY out of `write_chunks` (e.g., into `bulk_ingest.py` and `re_embed.py`
only), this caller's notebook-scoped LanceDB never gets a marker.

**Observable symptom.** Server startup against a notebook LanceDB (used in
notebook retrieval path) raises `CorpusNotIngestedError`. All notebook-MCP
tool calls fail. Tests seeding notebook LanceDB via `write_chunks` would also
fail to produce a marker.

**Also affected:** all tests calling `write_chunks` directly (dozens of test
files). They currently rely on `write_chunks` writing a marker as a side effect.

**FLAGGED CONFLICT:** Moving the marker write entirely out of `write_chunks`
breaks the existing single-call contract. **The marker write must remain in
`write_chunks` for the single-paper case to work correctly.** The fix must be
in the multi-paper callers, not in `write_chunks` itself.

### FM-5: lancedb 0.30.x `to_arrow()` kwargs trap

**Trigger.** Any implementation that calls `tbl.to_arrow(columns=["paper_id"])`
or `tbl.to_arrow(filter=...)` on a lancedb 0.30.x table.

**Observable symptom.** `TypeError: to_arrow() got an unexpected keyword
argument 'columns'` at runtime. This is a KNOWN breakage — documented with
comment `# lancedb 0.30.x: to_arrow() takes no kwargs; project after load.`
in `ingest/re_embed.py:242,298,324` and confirmed via live introspection.

**Mitigation.** Always use `tbl.to_arrow().select(["paper_id"])` (no kwargs),
consistent with the existing project pattern.

### FM-6: Idempotency / re-run correctness

**Trigger.** Running ingest twice on the same paper set (idempotent upsert via
`merge_insert`). After the second run, `tbl.count_rows()` returns the same N
rows (upsert, not append). The marker counts will still be accurate.

**Observable symptom.** None — the count-from-table approach is inherently
idempotent: count what's in the table, not what was just written. This is
BETTER than the current per-batch `len(chunks)` approach which always records
only the last batch.

### FM-7: Empty-chunks path — edge case

**Trigger.** `write_chunks([], embed_record, ...)` — the empty-chunks path logs
INFO and returns 0. If the once-per-run marker reads counts from the table
AFTER an empty `write_chunks` call at the end of the loop, the counts are
correct (unchanged). No regression.

---

## Prior decisions and lessons

- `git log --oneline -20`: no prior work on this milestone; `state.json` shows
  `phase: research-running`, `research_briefs: []`.
- `ingest/re_embed.py:149-151` documents: "`corpus-version.json` is overwritten
  by `write_chunks` on every per-paper call (no `status` field), so we carry
  the status contract in this companion file instead of patching `write_chunks`."
  This comment is a DIRECT acknowledgment of the bug. The re_embed author knew
  the per-paper overwrite happened and worked around it with the
  `re-embed-progress.json` sentinel. The fix should close this known gap.
- Banned patterns confirmed not at risk: no `assert`, no `BaseHTTPMiddleware`,
  no `anthropic` import, no tool schema change → `EXPECTED_TOOL_SCHEMA_SHA256`
  stays unchanged.
- `KMP_DUPLICATE_LIB_OK=TRUE` in `tests/conftest.py` not touched.
- `kuzu==0.11.3` pin, `var/arxmcp/index/kuzu/` path — not touched by this
  milestone.

---

## External sources

LanceDB 0.30.x `count_rows()` and `to_arrow()` API confirmed via live Python
introspection in this repo's `uv` environment (lancedb installed). No external
doc fetch needed — the project's own code (`ingest/re_embed.py:242,298,324`)
already documents the to_arrow no-kwargs constraint. This milestone does not
touch the MCP tool surface, prompt cache, or server tool schema.

---

## Recommendation

**Implement per-paper marker with TABLE-derived counts — not once-per-run.**

Rationale: moving the marker write out of `write_chunks` breaks the
single-caller contract (FM-4, CRITICAL). The correct fix is to keep
`write_corpus_version_marker` inside `write_chunks`, but compute counts from
the committed table state: `chunk_count = tbl.count_rows()` (O(1)) and
`paper_count` passed as an explicit parameter that multi-paper callers compute
via a running set maintained in their loop. This is crash-safe (every paper
write produces a correct marker), avoids O(N²) table scans, and requires no
API changes to `write_corpus_version_marker`.

**Concrete implementation seam:**

1. In `write_chunks`: replace `len(chunks)` with `tbl.count_rows()` for
   `chunk_count`. Keep `paper_count=len({c.paper_id for c in chunks})` as
   default but add an optional `cumulative_paper_ids: set[str] | None = None`
   parameter — when provided, use `len(cumulative_paper_ids)` instead. This
   lets single-paper callers keep zero-change behavior while multi-paper
   callers pass their running accumulator.
2. In `bulk_ingest.py::run_bulk_ingest`: maintain `seen_paper_ids: set[str]`
   accumulating all processed paper_ids, pass to `write_chunks` each call.
3. In `re_embed.py::run_re_embed` (the per-paper dispatch `_process_one_paper`
   plus caller): same pattern.
4. The regression test: call `write_chunks` twice with disjoint paper batches
   (2 calls, 1 paper each), assert final marker has `chunk_count == tbl.count_rows()`
   and `paper_count == 2`. This FAILS on pre-fix code (marker records last
   paper's count = 1).

**Alternative (once-per-run helper in callers):** achieves the marker-accuracy
goal but is NOT crash-safe between last write_chunks and the marker write,
breaks single-caller notebooks, and requires callers to import + call
`write_corpus_version_marker` directly. Argue against this seam.

---

## Open questions

1. **`cumulative_paper_ids` parameter shape:** the implementer must decide
   whether to add an optional `cumulative_paper_ids` parameter to
   `write_chunks`, or instead return `chunk_count` from `tbl.count_rows()`
   unconditionally and let the caller still pass `paper_count` explicitly.
   The latter is simpler (no new parameter) and correct: replace only
   `chunk_count=len(chunks)` with `chunk_count=tbl.count_rows()`, and leave
   `paper_count` computation to the callers (who already compute it as
   `len({c.paper_id for c in chunks})` per paper). Multi-paper callers
   accumulate a set externally and pass on the final call only — but this
   still only writes the correct count on the LAST call. The cleanest solution
   is to pass the running accumulated paper set each call. This is a seam
   decision the implementer must make before writing code.

---

## External writes the implementation will require

None — this milestone is purely local. No git push, no ticket mutations, no
infra changes, no external API calls. The fix is confined to `ingest/store.py`,
`ingest/bulk_ingest.py`, `ingest/re_embed.py`, and a new test file.
