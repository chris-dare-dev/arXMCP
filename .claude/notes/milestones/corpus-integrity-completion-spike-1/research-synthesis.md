# Research Synthesis — corpus-integrity-completion-spike-1

**Synthesizer:** main orchestrator session (NOT a sub-agent)
**Generated:** 2026-05-31
**Briefs merged:** `research-brief-1.md` (in-codebase + variant feasibility), `research-brief-2.md` (failure-mode matrix + blast-radius)
**Verdict:** SPIKE OUTCOME — the roadmap's pre-recommendation of variant (c) [both] is **REFUTED**. The binding spike decision is variant **(a) ONLY**, redefined per R1's correction as a marker-file READBACK verify (NOT a literal second `count_rows()` which is itself tautological under the single-writer model). Variant (b) does NOT ship per R2's idempotent-re-run false-positive analysis.

This is exactly the kind of value a spike delivers — both researchers independently caught DIFFERENT load-bearing problems with the roadmap pre-recommendation, and together they reshape the e1 implementation brief.

---

## 1. The binding spike decision

**Ship variant (a) ONLY for the e1 epic. Do NOT ship variant (b). Refute the roadmap's pre-recommendation of (c).**

The implementation shape for e1's WAP gate is:

```python
# Inside ingest/store.py::write_chunks, AFTER write_corpus_version_marker(...) returns:
re_read_marker = read_corpus_version(target_path)
fresh_count = tbl.count_rows()
if re_read_marker is None or re_read_marker.chunk_count != fresh_count:
    raise RuntimeError(
        f"WAP gate: corpus-version.json marker at {target_path} has "
        f"chunk_count={re_read_marker.chunk_count if re_read_marker else 'MISSING'} "
        f"but tbl.count_rows()={fresh_count} for corpus_version={dataset_version}. "
        f"This indicates a marker serialization or file-truncation failure. "
        f"Run `make reconcile` to repair. Runbook: docs/ops/corpus-drift-runbook.md."
    )
```

This is option (ii) from R2's open question — preserve the existing "best-effort" `try/except Exception` swallow for transient I/O failures while adding a check that fires on detected divergence. The gate raises ONLY when it actually catches a discrepancy.

---

## 2. R1's load-bearing correction — the "second count_rows()" is itself tautological

R1 §"Tautology verification" (verbatim):

> "**The challenger's claim is confirmed:** `stats.total_rows_after_commit = chunk_count` is set from `tbl.count_rows()` at line 942, BEFORE `write_corpus_version_marker` is called at line 946. Any subsequent comparison `tbl.count_rows() == stats.total_rows_after_commit` is `chunk_count == chunk_count` — identity, never fires."

R1 §"Single-writer constraint" (verbatim):

> "Under the single-writer model that this codebase enforces, there is ZERO chance the table mutates between the pre-marker `count_rows()` at line 938 and a post-marker `count_rows()`. They will return the same value under the single-writer contract. The value (a) catches is **not count divergence — it catches marker-write failures** (wrong JSON written, truncated file, `json.dumps` bug, path pointing to wrong filesystem)."

R1 §"Critical refinement for variant (a)" (verbatim):

> "The most precise WAP check is NOT `tbl.count_rows() == stats.total_rows_after_commit`. It should be: read back the just-written marker file and verify `marker['chunk_count'] == chunk_count`. This catches JSON construction bugs, partial writes where `os.replace` still atomically committed a truncated file (impossible on POSIX but possible if the filesystem is non-POSIX), and any other marker-write failure."

**Synthesizer resolution:** R1 is correct. The literal "second `count_rows()`" from the roadmap pre-recommendation IS itself tautological under the single-writer model. The correct gate compares the **marker-file's STORED VALUE** (read back from disk) against a FRESH `count_rows()` — this catches both marker-side failures (FM-2, FM-3, FM-7 from R2's matrix) AND a hypothetical reintroduction of the pre-m1 bug shape (FM-1: a wrong `chunk_count` value would land in the marker, would NOT equal the fresh `count_rows()`).

---

## 3. R2's load-bearing correction — variant (b) false-fires on idempotent re-runs

R2 §"Variant (b)'s epistemic problem" (verbatim):

> "**Critical observation:** On a FRESH staging LanceDB (no prior rows), `len(chunks)` summed IS a valid expected total because every write is an insert (no updates). On a RE-RUN against an existing staging LanceDB (some papers already ingested), the `merge_insert` performs upserts — rows already present are updated, not inserted twice. So `tbl.count_rows()` after re-run == count of DISTINCT chunk_ids, while `expected_total` accumulated from `len(chunks)` overcounts re-processed papers. This means variant (b) would produce **false positives on idempotent re-runs** unless the bulk driver explicitly tracks whether each paper was a fresh-write vs. re-run."

> "This is NOT a problem for variant (a): `count_rows()` vs. just-written marker are both based on the SAME post-merge table state, regardless of upsert behavior."

R2 §"Failure-mode coverage decision" (verbatim):

> "1. **(a) catches more failure modes.** FM-1, FM-2, FM-3, FM-7 are all marker-side failures caught by (a). FM-4 (bulk arithmetic) is the only mode caught by (b) alone — but as shown above, implementing (b) correctly for re-run safety is non-trivial.
>
> 2. **(b) produces false positives on idempotent re-runs.** The staging LanceDB is designed for re-runs (embedder sidecar check, `merge_insert` upsert). A bulk operator running the 200K-paper ingest in stages would trigger (b)'s false-positive constantly, making the gate unusable in practice."

**Synthesizer resolution:** R2 is correct. The staging LanceDB's idempotency contract (`merge_insert` upsert + embedder sidecar check) is structural to the bulk-ingest design — operators run partial / resumable bulk jobs. Variant (b)'s naive `sum(len(chunks)) == count_rows()` would fire on every resumed run, masking real divergences when they eventually appear. **Variant (b) does NOT ship.**

---

## 4. R1 vs R2 — the surface-level disagreement

R1 recommended **(c) BOTH** (with the (a)-redefinition correction). R2 recommended **(a) ONLY** (with the (b)-false-positive analysis).

The disagreement collapses on inspection:

- R1's (b) recommendation depends on the `expected_total` accumulating correctly. R1 says (verbatim): "accumulate `WriteStats.total_rows_after_commit` from the last `write_chunks` call in the loop and use that as the end-of-run total — it already reflects the final cumulative row count."
- R2 traced through the case where `merge_insert` upserts existing rows on a resumed run — the cumulative count is correct (distinct chunk_ids), but the EXPECTED accumulated from per-paper `len(chunks)` overcounts re-processed papers.

R1's escape hatch ("use `WriteStats.total_rows_after_commit` from the last call") would work — because `WriteStats.total_rows_after_commit` is itself `tbl.count_rows()` from inside `write_chunks` — but then **(b) collapses into (a)**. The "expected" value is just the writer's report of `count_rows()`, and the "actual" value is the bulk driver's read of `count_rows()` — these are the same observation through two different code paths. R1's (b) shape is effectively a defense-in-depth read of the writer's own report; it adds operational cost (end-of-run latency) without catching a distinct failure mode.

**Synthesizer pick:** R2's analysis is stronger. (b) does not ship.

---

## 5. Failure-mode coverage matrix (consolidated from R2's 11-mode analysis)

| # | Failure mode | Caught by (a)? | Notes |
|---|---|---|---|
| FM-1 | Pre-m1 bug: `len(chunks)` instead of `tbl.count_rows()` as marker value | YES — marker stored vs. fresh count_rows mismatch fires |
| FM-2 | JSON serialization wrong chunk_count value (float truncation, etc) | YES — readback detects |
| FM-3 | Atomic rename completes but file truncated/corrupted | YES — readback (json.loads or chunk_count missing) detects |
| FM-4 | Per-paper batch len() summed wrong (caller arithmetic) | NO — outside (a)'s scope. **But m1 fixed the original instance; future regression caught by m3 integration test (positive path) + (a) at write boundary.** |
| FM-5 | TOCTOU between count_rows and marker write | OUT OF SCOPE — single-writer constraint excludes this |
| FM-6 | Schema-version field drifts (version int wraps, chunker_version wrong) | OUT OF SCOPE — `server.corpus.read_corpus_version` validates schema at read time |
| FM-7 | Marker chunk_count int overflow on 200K+ row corpus | YES — readback detects |
| FM-8 | Marker file written to wrong path | OUT OF SCOPE — config validation |
| FM-9 | run_bulk_ingest silently skips a paper | OUT OF SCOPE — failure log already captures this |
| FM-10 | `write_corpus_version_marker` exception is swallowed (best-effort contract) | **PARTIAL — (a)'s `read_corpus_version` returns None if no marker file exists; the gate raises on that case, so it DOES catch a fully-swallowed write.** |
| FM-11 | Sibling marker writer (`server/routes/notebooks._rewrite_corpus_version_marker`) | OUT OF SCOPE — documented in m3 follow-up F2-extension |

Variant (a)'s coverage: FM-1, FM-2, FM-3, FM-7, FM-10. Out-of-scope items (FM-4, FM-5, FM-6, FM-8, FM-9, FM-11) are either covered by other shipped mechanisms (m1's table-derived count, m2's runbook, m3's integration test, the single-writer constraint, the `read_corpus_version` schema validator) or deferred as out-of-epic items (FM-11 to a future ops-hardening epic).

---

## 6. Blast-radius + operator-actionability (consolidated from R2)

When variant (a) fires:
- The LanceDB table commit has succeeded (MVCC version N is on disk).
- The marker file is on disk but with wrong content.
- `write_chunks` raises `RuntimeError`.
- The caller (`ingest_one_paper` in `bulk_ingest.py`) propagates to `run_bulk_ingest`'s loop; the paper records as a failure; the next paper proceeds.
- The operator sees a per-paper error WITH the diagnostic info (lancedb_path, marker_count, actual_count, dataset_version, runbook URL).
- `make reconcile` is the remediation path (recounts + rewrites the marker correctly). It already exists, ships with m1, has full coverage in m2's runbook.

**Critical decision (R2 §Variant (a) — raises inside `write_chunks` post-marker):** Variant (a)'s gate fires AT THE END of `write_chunks` AFTER the LanceDB row commit. This is the right place — the table state is correct; the marker is what's broken; the per-paper failure is recoverable.

---

## 7. Resolved open questions

- **R1 Q1 + R2 implicit:** What does (a) catch that (b) doesn't, and vice versa? Resolved by the synthesis matrix above (§5). (a) catches marker-side failures; (b) would catch caller-arithmetic but ships with the false-positive landmine, so it doesn't ship.
- **R1 Q2:** Should the post-marker check raise on mismatch or log+continue? **RAISE** — both researchers agreed. The marker is the server's startup authority; a wrong value is a correctness regression, not a recoverable best-effort omission.
- **R1 Q3 + R2 sole open question:** Should the marker-write exception swallow be preserved or removed? **PRESERVE the swallow for transient I/O; ADD the readback gate as a separate check that raises on detected divergence (option ii).** Both researchers converged on this shape.
- **R1 §3:** Other multi-call callers of `write_chunks`? `ingest/re_embed.py` calls write_chunks twice per paper (copy + re-embed). For e1 scope: the WAP gate inside `write_chunks` covers re_embed.py automatically — every call gets the gate. No additional wiring needed. The original (b) would have required separate wiring for re_embed's loop — another reason (a) wins.

---

## 8. Concrete deliverables for the e1 milestone brief

The spike's binding output for the future e1 milestone:

1. **Implementation site:** `ingest/store.py::write_chunks`, immediately after `write_corpus_version_marker(...)` returns (inside the existing `try:` block).
2. **Implementation shape (~15 LOC):**
   ```python
   # WAP gate (corpus-integrity-completion-e1):
   re_read_marker = read_corpus_version(target_path)
   fresh_count = tbl.count_rows()
   if re_read_marker is None:
       raise RuntimeError(
           f"WAP gate: corpus-version.json marker at {target_path} could "
           f"not be read back after write. Run `make reconcile` to repair."
       )
   if re_read_marker.chunk_count != fresh_count:
       raise RuntimeError(
           f"WAP gate: corpus-version.json marker at {target_path} has "
           f"chunk_count={re_read_marker.chunk_count} but tbl.count_rows()="
           f"{fresh_count} for corpus_version={dataset_version}. This indicates "
           f"a marker serialization or file-truncation failure. Run "
           f"`make reconcile` to repair. Runbook: docs/ops/corpus-drift-runbook.md."
       )
   ```
3. **Behavioral contract change:** The existing `try/except Exception` swallow at `ingest/store.py:970-977` is PRESERVED for the original `write_corpus_version_marker` call. The new gate adds a SECOND validation step that raises only when divergence is detected — the existing best-effort guarantee for transient I/O failures is preserved.
4. **Test plan (e1's implementation):**
   - Positive: real `write_chunks` call → gate passes.
   - Mutation A: monkeypatch `write_corpus_version_marker` to write `chunk_count=1` against a 30-row table → gate raises with the expected error message + diagnostic.
   - Mutation B: monkeypatch `read_corpus_version` to return None → gate raises the MISSING-marker error.
   - Mutation C: monkeypatch `read_corpus_version` to return wrong `chunk_count` (mismatch path).
5. **Out-of-scope for e1 (documented as Won't):**
   - Variant (b) — caller `expected_total` from `bulk_ingest.py`. The idempotent-re-run false-positive analysis blocks it.
   - Sibling marker writers (`server/routes/notebooks._rewrite_corpus_version_marker`, `tools/notebook_reconcile_marker.py`) — m3 follow-up F2-extension.

---

## 9. External writes the implementation will require

Both briefs agree: **NONE during the spike.** The spike's output is a decision document; no code changes. The e1 milestone (when it runs through `/milestone-pipeline corpus-integrity-completion-e1` later) will have its own external-writes assessment, but that's not this spike's concern.

---

## 10. Orchestrator synthesis note

The spike achieved its purpose. Both researchers independently caught DIFFERENT load-bearing problems with the roadmap's pre-recommendation of (c):
- **R1** caught the tautology refinement: the literal "second `count_rows()`" is itself tautological under single-writer; the correct gate compares the **marker FILE'S stored value** (readback) against fresh `count_rows()`.
- **R2** caught the (b) false-positive landmine: idempotent `merge_insert` upserts make `sum(len(chunks))` overcount re-processed papers, while `count_rows()` correctly reports distinct rows. (b) would false-fire on every resumed bulk run.

The spike's binding output: ship (a) only, redefined as marker-file readback verify. The roadmap's pre-recommendation of (c) is REFUTED with concrete codebase grounding.

**Implementation path for the SPIKE itself:** Phase 2 authors a binding decision document at `.claude/notes/milestones/corpus-integrity-completion-spike-1/decision.md`. No source code changes ship in this milestone — only the artifact that will feed the future e1 implementation brief. Inline orchestrator implementation; one decision document; trivial under the 500 LOC / 5 files threshold.
