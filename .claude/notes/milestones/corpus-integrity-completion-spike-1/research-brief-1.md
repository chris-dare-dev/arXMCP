# Research Brief — corpus-integrity-completion-spike-1

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-31T23:30:00Z

---

## In-codebase context

### Tautology verification

Reading `ingest/store.py::write_chunks` end-to-end confirms the challenger's CAND-3 claim exactly.

The sequence in `write_chunks` (lines 862–987) is:

```python
# Line 874: post-index version resolved
dataset_version = int(getattr(tbl, "version", 0) or 0)

# Lines 877–888: WriteStats constructed, total_rows_after_commit left at 0
stats = WriteStats(
    chunk_count=len(chunks),
    ...
    # total_rows_after_commit is populated below (after count_rows()); the
    # stats row is appended AFTER that block so the audit log captures the
    # real value, not 0 (corpus-integrity-observability-e3 critique F1).
)

# Lines 938–953: count_rows() called BEFORE marker write
    chunk_count = tbl.count_rows()
    # corpus-integrity-observability-e3 (CAND-8): thread the total-row
    # count through WriteStats so callers can accumulate run-level
    # chunks_written for ingest-summary.json without an extra count_rows().
    stats.total_rows_after_commit = chunk_count
    paper_count = len(
        set(tbl.to_arrow().select(["paper_id"])["paper_id"].to_pylist())
    )
    write_corpus_version_marker(
        target_path,
        version=dataset_version,
        ...
        chunk_count=chunk_count,
    )
```

**The challenger's claim is confirmed:** `stats.total_rows_after_commit = chunk_count` is set from `tbl.count_rows()` at line 942, BEFORE `write_corpus_version_marker` is called at line 946. Any subsequent comparison `tbl.count_rows() == stats.total_rows_after_commit` is `chunk_count == chunk_count` — identity, never fires.

**Single-writer constraint (load-bearing from module docstring lines 44–55):**
> "The function is designed for a SINGLE writer per LanceDB dataset. Between `merge_insert` and `_create_indices`, a concurrent writer-B landing its own merge against the same dataset would shift `tbl.version`... Callers running concurrent ingest from multiple processes against the same dataset must serialize writes externally."

This means: in the single-writer model that this codebase enforces, there is ZERO chance the table mutates between the pre-marker `count_rows()` at line 938 and a post-marker `count_rows()`. They will return the same value under the single-writer contract. The value (a) catches is **not count divergence — it catches marker-write failures** (wrong JSON written, truncated file, `json.dumps` bug, path pointing to wrong filesystem).

---

### write_corpus_version_marker write path

From `ingest/store.py` lines 755–766:

```python
payload = json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n"
tmp = out_path.with_suffix(
    f"{out_path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
)
try:
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, out_path)
finally:
    with contextlib.suppress(OSError):
        tmp.unlink(missing_ok=True)
```

`os.replace` is POSIX-atomic when src and dst are on the same filesystem. The tmp is co-located with the destination (`out_path.with_suffix(...)` produces a file in the same directory), which is `lancedb_path/`. This satisfies the same-filesystem requirement for atomic replace (see `agent-conventions.md` memory note on cross-filesystem tmp trap).

The JSON is built as a Python dict and serialized with `json.dumps(sort_keys=True)`. The `chunk_count` field is `int(chunk_count)` — no float truncation, no format string.

**Plausible failure modes variant (a) actually catches:**
1. `tmp.write_text` writes partial content before a disk-full / SIGKILL at the byte boundary — BUT `os.replace` hasn't run, so `out_path` still has the OLD marker. Post-marker `count_rows()` != old marker's `chunk_count`. Fires correctly.
2. `json.dumps` produces a value with serialization drift (theoretically impossible for plain `int`, but future code changes to `doc` construction could introduce this).
3. The `except Exception` swallow at line 970 masks an exception INSIDE the `try` block BEFORE `os.replace` — the marker is not written or is stale. Post-marker `count_rows()` would need to verify the JUST-WRITTEN file's content, not just re-call `count_rows()`. This exposes a subtle issue: a post-marker `count_rows()` only catches that the count hasn't changed, not that the marker file itself contains the right `chunk_count` value.

**Critical refinement for variant (a):** The most precise WAP check is NOT `tbl.count_rows() == stats.total_rows_after_commit`. It should be: read back the just-written marker file and verify `marker["chunk_count"] == chunk_count`. This catches JSON construction bugs, partial writes where `os.replace` still atomically committed a truncated file (impossible on POSIX but possible if the filesystem is non-POSIX), and any other marker-write failure.

---

## Prior decisions and lessons

From `git log --oneline -20`:
- `297b690` — `corpus-integrity-completion-m3` is complete (end-to-end /readyz integration test)
- `c58c19e` — `corpus-integrity-completion-m1`: corpus-integrity alert rules shipped
- `5a8c7f0`, `1a398f7` — m1 and m2 complete

The three prior corpus-integrity-completion milestones (m1=alert rules, m2=operator runbook, m3=integration test) are all shipped. The WAP gate (CAND-3 from the challenger) is the next discrete work unit.

From agent memory (CAND-3 challenger note, §6.5): "The WAP gate logic needs rethinking (see CAND-3 finding) before implementation, but the candidate itself is sound."

From the existing comment at `ingest/store.py:934-937`:
> "# F4 (corpus-integrity-observability-m1 critique): these counts are read off the SAME `tbl` handle that pinned `dataset_version` above, under the single-writer-per-dataset model (module docstring, 'MVCC handshake'). No write lands between L862 and here in-process, so the marker's `version` and its counts are coherent. A concurrent external writer is out of scope (E11)."

This comment acknowledges coherence under single-writer but does NOT address the marker-write itself failing.

---

## External sources

This spike is purely local. The MCP spec and prompt-caching docs are not relevant to the WAP gate variant decision. No external sources consulted.

---

## Recommendation

**Ship variant (c) — both (a) and (b) — but redefine what (a) actually does.**

The roadmap pre-recommendation of (c) is confirmed, but variant (a) must be re-scoped: the post-marker second `count_rows()` is a **necessary but insufficient** WAP check. The correct (a) implementation is:

1. After `write_corpus_version_marker(...)` returns, read back the marker file from disk (`corpus-version.json`) and parse its `chunk_count`.
2. Verify `marker_on_disk["chunk_count"] == chunk_count` (the value passed to `write_corpus_version_marker`).
3. On mismatch: **raise** (not log+continue). A marker that lies about chunk count is a correctness regression — the server's startup will pin the wrong version with wrong metadata. The `except Exception` wrapper in `write_chunks` already swallows this as best-effort, but the WAP check should occur INSIDE the `try` block so a mismatch raises and is caught + logged at the `except` level, not silently ignored.

Why `raise` inside the `try` rather than log+continue: the marker's `chunk_count` is the server's startup authority. An incorrect value causes downstream cache namespace collisions and incorrect `/status` display. This is not a recoverable state — the ingest should be re-runnable.

For variant (b): `bulk_ingest.run_bulk_ingest` already accumulates `chunks_written` across the per-paper loop (line 389: `chunks_written += outcome.chunks_written`). The right shape is: after the loop, call `tbl.count_rows()` on the staging dataset ONCE and compare against `chunks_written`. Note: because `write_chunks` uses `merge_insert` (idempotent upsert), `chunks_written` (sum of `len(chunks)` per paper) may differ from `tbl.count_rows()` if any papers are re-ingested (updates, not inserts). The correct comparison for (b) is: `tbl.count_rows() >= chunks_written` with a tolerance, OR restrict (b) to FIRST-TIME ingest runs only (no prior rows). The simpler implementation: accumulate `WriteStats.total_rows_after_commit` from the last `write_chunks` call in the loop and use that as the end-of-run total — it already reflects the final cumulative row count.

**The LOC cost:** (a) adds ~10 LOC inside `write_chunks` (read-back + parse + compare). (b) adds ~5 LOC in `run_bulk_ingest` (final `count_rows()` + comparison). (c) = ~15 LOC total. Negligible.

**Runtime cost:** LanceDB `count_rows()` is O(1) per Lance fragment metadata (as documented in project notes). The marker file read-back is a single filesystem read of a ~200-byte JSON file. Neither adds measurable overhead.

---

## Open questions

1. **Exact failure-modes difference between variants (a) and (b):**
   - (a) catches: marker-file write failures (disk-full pre-`os.replace`, JSON serialization bugs, wrong `chunk_count` value passed to `write_corpus_version_marker`). Does NOT catch per-batch arithmetic errors or LanceDB write failures (LanceDB's MVCC already handles those).
   - (b) catches: end-of-run bulk-ingest divergence — N papers processed but final `tbl.count_rows()` does not match expectations. In practice post-m1, the original per-batch arithmetic bug is fixed, so (b) mainly catches unexpected LanceDB version conflicts or external tampering.
   - Overlap: neither variant catches a LanceDB HNSW index failure (already caught by `_create_indices`).

2. **Are there other multi-call callers of `write_chunks` that need `expected_total` wiring?**
   Production callers of `write_chunks` (excluding test helpers):
   - `ingest/bulk_ingest.py:322` — primary target for variant (b)
   - `ingest/re_embed.py:528,558` — calls `write_chunks` twice per paper (copy path + re-embed path). Does NOT accumulate a final expected total. The re-embed driver is a per-paper operation; it would need the same end-of-run gate if used for bulk re-embedding. This is a gap: if `run_re_embed_papers` is ever called over N papers, no final count_rows() gate exists.
   - `tools/notebook_textbook_ingest.py:202` — single call per notebook. Variant (a) covers this call site automatically.
   The implementer must decide whether to wire (b)-equivalent logic in `re_embed.py`'s outer loop. Recommended: yes, but as a follow-up to avoid scope creep in e1.

3. **Should the post-marker check raise on mismatch or log+continue?**
   Recommendation above: raise inside the `try` so the `except Exception` in `write_chunks` catches it as a best-effort failure and logs at ERROR level. The LanceDB row write has already committed; the operator can re-run `make reconcile` to fix the marker. Do NOT abort the ingest silently — log the error and return the `dataset_version` so the caller sees the version but can detect the anomaly from the error log.

---

## External writes the implementation will require

None — this spike is purely local (decision document). The eventual e1 milestone implementation is also purely local (code + tests, committed to main, no push until user authorizes per §4.4).
