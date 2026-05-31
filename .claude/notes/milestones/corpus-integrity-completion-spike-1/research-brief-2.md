# Research Brief — corpus-integrity-completion-spike-1

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-31T23:15:00Z

## In-codebase context

### Load-bearing prior decisions

From `ingest/store.py` module docstring (verbatim, lines 44–55):
> "**Single-writer assumption (F11 from the E04_S02 critique).** The function is designed
> for a SINGLE writer per LanceDB dataset. Between `merge_insert` and `_create_indices`,
> a concurrent writer-B landing its own merge against the same dataset would shift
> `tbl.version` such that writer-A's returned integer points to writer-B's post-merge
> state, not writer-A's own post-index state. Callers running concurrent ingest from
> multiple processes against the same dataset must serialize writes externally (e.g. a
> flock on `<lancedb_path>/.write-lock`). The Tier-0 ingestion pipeline has exactly one
> writer (the corpus driver), so this is a documented constraint rather than an enforced
> one."

From `ingest/store.py:919–927` (the m1 fix, verbatim comments):
> "corpus-integrity-observability-m1: derive the marker counts from the COMMITTED TABLE,
> not the in-flight `chunks` batch. The per-paper callers... call write_chunks once per
> paper, so the marker is overwritten each call — with `len(chunks)`/`len({paper_ids})`
> it recorded only the LAST paper's counts."

The current `write_chunks` (lines 938–953) does a `count_rows()` + `write_corpus_version_marker()`
in a `try/except Exception` block that **swallows failures** — if the marker write fails, the
function logs an error and returns `dataset_version` successfully. This is the "best-effort"
contract:
> "the LanceDB row write has already committed and the dataset_version is what the caller
> needs" (`ingest/store.py:905–910`).

From `ingest/bulk_ingest.py:322–325`, `ingest_one_paper` calls:
```python
version = write_chunks(chunks, embed_record, lancedb_path=lancedb_staging_path)
outcome.chunks_written = len(chunks)
```
`IngestSummary` has no `expected_total` field. There is no end-of-run assertion in
`run_bulk_ingest` comparing expected total vs `tbl.count_rows()`. The bulk driver passes
`total_rows_after_commit=0` to `write_ingest_summary()` (line 416) with the comment
"not available at this level; 0 is safe."

### The m3 critique surfaces the still-open gap

From `corpus-integrity-completion-m3/critique-merged.md F1` (verbatim):
> "The actual pre-m1 bug shape lived in **multi-call cumulative** ingest where `len(chunks)`
> reflected only the LAST batch... the m3 fixture does not exercise that shape."

The m3 integration test (`tests/test_server_startup_integration.py`) calls `write_chunks`
exactly ONCE via `_seed_corpus`. The test does NOT catch a reintroduced `len(chunks)` bug
shape because for a single call, `len(chunks) == tbl.count_rows()`. The m3 critique explicitly
left this open as the F1 finding, deferred to a future milestone.

### The roadmap's e1 brief (verbatim, §Decompose corpus-integrity-completion-e1):
> "**Outcome:** `ingest/store.py::write_chunks` raises `RuntimeError` whenever the
> just-written `corpus-version.json` marker's `chunk_count` does not match a fresh
> `tbl.count_rows()`. The pre-m1 bug shape (`chunk_count` from last per-paper batch)
> fails the write boundary, not the next-restart inspection. `ingest/bulk_ingest.py`
> accumulates expected per-paper totals and asserts equality at end-of-run."

From roadmap §Spike lane (verbatim):
> "pick between (a) a SECOND `tbl.count_rows()` AFTER `write_corpus_version_marker`
> returns, comparing the live table against the just-written marker file's `chunk_count`
> (catches filesystem/serialization failure in the marker write itself), or (b) a
> `expected_total` parameter threaded from the BULK caller (`ingest/bulk_ingest.py`) that
> accumulates expected per-paper counts and is asserted equal to `tbl.count_rows()` at
> end of run (catches per-paper-batch arithmetic errors). Recommendation in the Spike:
> ship BOTH."

### The challenger's "tautology" critique

The pre-spike `store.py:938-942` was:
```python
chunk_count = tbl.count_rows()       # <- read from table
write_corpus_version_marker(..., chunk_count=chunk_count)  # <- write to marker
```
This is NOT a WAP gate — it's just "read-then-write." No post-write re-read verifies
the marker file's content matched the value that was written. The tautology: the
same `chunk_count` value is used for both, so the only divergence it could catch is
a marker-write I/O failure (not arithmetic errors). The roadmap's variant (a) fixes
this by doing a SECOND `count_rows()` AFTER `write_corpus_version_marker` returns,
then reading back the marker file and comparing the two.

**But wait:** variant (a) as literally stated ("read marker file's chunk_count, compare
to fresh count_rows()") would catch JSON serialization or file-truncation bugs, but NOT
the pre-m1 bug shape (wrong arithmetic in chunk_count). For variant (a) to catch
arithmetic errors, the second `count_rows()` must be compared against the marker's
`chunk_count` field — if the marker was written with a wrong value (e.g. `len(last_batch)`
instead of the true cumulative), then `second_count_rows() != marker.chunk_count` will
fire. This works — as long as the `count_rows()` returns the full cumulative table count.

**Variant (b)** at the bulk-driver boundary: `run_bulk_ingest` accumulates
`expected_total += outcome.chunks_written` per paper, then at end of run asserts
`expected_total == tbl.count_rows()`. This catches per-paper arithmetic errors
(wrong `len(chunks)` summing) but fires AFTER the entire multi-hour bulk run.

## Prior decisions and lessons

From git log (recent), m1–m3 are all complete. The integration test (m3) is the
last shipped mile. The WAP gate (e1) is the sole remaining "Next lane" item before
the spike. No sibling milestone for corpus-integrity is in-flight.

From m3 state.json `follow_ups`:
> "F2-extension: add a second mutation test that monkey-patches
> `server/routes/notebooks._rewrite_corpus_version_marker` (the parallel marker writer
> that mirrors `ingest/store.py::write_corpus_version_marker` but bypasses the
> module-local binding)."

This identifies `server/routes/notebooks.py:_rewrite_corpus_version_marker` as a SIBLING
marker writer outside the WAP gate's scope. The WAP gate in `write_chunks` does NOT cover
the notebook-route reconcile path.

The `assert`-ban (CLAUDE.md §4.7) is load-bearing: the WAP gate MUST use
`if condition: raise RuntimeError(...)`, not `assert condition`.

### Banned pattern risk
`assert` is banned for invariants per `CLAUDE.md §4.7`. Both WAP gate variants must use
`if divergence: raise RuntimeError(...)`. The error message is the operator's first
signal — it must contain all necessary diagnostic context.

## Failure-mode coverage matrix

| # | Failure mode | Caught by (a)? | Caught by (b)? | Notes |
|---|---|---|---|---|
| FM-1 | **Pre-m1 bug: `len(chunks)` instead of `tbl.count_rows()` used as chunk_count in marker** (multi-call cumulative) | YES — second `count_rows()` == 30 but marker says 1 (last batch) → mismatch detected per paper at write-time | YES — `expected_total` accumulates correctly (30), but actual per call is 1; end-of-run 30 != 30 ONLY if the table itself is wrong. ACTUALLY: if `len(chunks)` is used as the marker value but `tbl.count_rows()` returns the cumulative 30, then expected_total == 30 == tbl.count_rows() at end-of-run, so (b) would PASS. (b) catches bulk arithmetic drift, not marker arithmetic drift. | (a) catches this; (b) does NOT because expected_total is `len(chunks)` summed which IS the cumulative real value — the bug is only in the marker, not in the table. |
| FM-2 | **JSON serialization produces wrong chunk_count value** (e.g. float truncation, integer overflow in dumps) | YES — post-write re-read of marker shows wrong count vs fresh count_rows() | NO — bulk driver compares to tbl.count_rows(), not to marker file content | (a) is the right gate here |
| FM-3 | **Atomic rename completes but file is silently truncated/corrupted** (OS-level partial write before rename) | YES — post-write re-read detects truncation (json.loads fails or chunk_count missing) | NO | (a) adds defense-in-depth for filesystem failures |
| FM-4 | **Per-paper batch `len()` summed wrong** (programming error in bulk driver arithmetic — e.g. `chunks_written += len(chunks[:-1])`) | NO — marker writes the table count correctly; (a) compares table vs marker and they match | YES — expected_total would diverge from tbl.count_rows() at end of run | (b) is the gate; (a) is blind to caller arithmetic |
| FM-5 | **TOCTOU: concurrent write between count_rows() and marker write** | PARTIAL — the second count_rows() in (a) would catch a DELTA introduced after the marker write, but this is outside the single-writer constraint. Under single-writer assumption, zero risk. | NO — same TOCTOU blind spot | Under documented single-writer assumption, this is out-of-scope |
| FM-6 | **Schema-version field of marker drifts but chunk_count stays correct** (e.g. `version` int wraps, or chunker_version gets wrong value) | NO — (a) only compares chunk_count | NO — (b) only compares total row count | Outside scope of BOTH variants; the marker schema is validated at read time by `server.corpus.read_corpus_version` |
| FM-7 | **Marker chunk_count int overflow on 200K+ row corpus** (Python int is unbounded so not a runtime error, but the value silently truncated by a future JSON serializer change or uint32 field) | YES — second count_rows() returns the real count; if the written marker is truncated, they diverge | NO — expected_total at bulk driver also uses the same arithmetic | (a) catches this; edge case, very low probability |
| FM-8 | **Marker file written to wrong path** (lancedb_path kwarg misconfigured — the marker lands in a staging dir but the read-path checks the active dir) | NO — (a) re-reads the marker from the SAME path written; it finds the newly written file and they match | NO | Neither catches this; out-of-scope (config validation problem, not arithmetic) |
| FM-9 | **`run_bulk_ingest` silently skips a paper** (paper lands in failures log but is not counted in expected_total) | NO — marker still reflects real table count | PARTIAL — if a skipped paper had chunks that somehow got written (not the normal path), the total diverges. Under normal skip path (write never called), both totals are consistent. | Low-risk under normal operation |
| FM-10 | **`write_corpus_version_marker` exception is swallowed** (current best-effort contract) — marker is never written at all | NO — (a) requires the marker to exist to read it back; if write raised, the gap is logged but NOT raised | NO — bulk driver doesn't know marker was skipped | **BOTH variants miss this.** The current swallow contract is the gap. WAP gate requires re-raising marker failures, not swallowing them. |
| FM-11 | **`sibling marker writer` (`server/routes/notebooks._rewrite_corpus_version_marker`) writes wrong chunk_count** | NO — (a) is inside `write_chunks`; the reconcile route bypasses it entirely | NO — (b) is in `bulk_ingest`; the reconcile route is not a bulk ingest | **BOTH miss this.** Acknowledged in m3 F2-extension follow-up. |

**Summary:** (a) catches FM-1, FM-2, FM-3, FM-7 (marker-side failures). (b) catches FM-4 (caller arithmetic failures). FM-5, FM-6, FM-8, FM-9, FM-10, FM-11 are outside both variants' scope.

## Blast-radius analysis

### Variant (a) — raises inside `write_chunks` post-marker

**State when it fires:**
- `tbl.merge_insert` has already committed (MVCC version N written to disk).
- `write_corpus_version_marker` has already run (marker file is on disk, with wrong count or truncated).
- `write_chunks` raises `RuntimeError` — the caller sees an exception.

**What the caller does:**
- `ingest_one_paper` in `ingest/bulk_ingest.py` has no try/except around `write_chunks`;
  the exception propagates to `run_bulk_ingest`'s loop. The paper's outcome records
  `chunks_written = 0` (since the assignment is AFTER the `write_chunks` call at line 325).
  The paper is counted as a failure. `_log_parser_failure` is called.
- The staging LanceDB still has the committed rows. The marker is on disk with the wrong
  count. `make reconcile` (or `tools/notebook_reconcile_marker.py`) is the remediation
  — it reads the actual table count and rewrites the marker correctly.
- **Does the operator need manual reconciliation?** YES, for the staging LanceDB's marker.
  But since it's the staging LanceDB (not the active one), the server is unaffected.
  The bulk run continues to the next paper.

**Does (a) duplicate `make reconcile`?** NO — `make reconcile` is a post-hoc repair
tool. (a) is a fail-fast gate that stops the ingest from silently succeeding with a wrong
marker. They are complementary: (a) fails loud, reconcile heals. Without (a), the
wrong marker lands silently; reconcile would only run if the operator knew to run it.

### Variant (b) — raises at end of `run_bulk_ingest`

**State when it fires:**
- All per-paper `write_chunks` calls have succeeded. All per-paper markers have been
  written (individually, with whatever chunk_count was used).
- The final `tbl.count_rows()` at end-of-run doesn't match `expected_total`.
- **This is a hours-later surprise.** A 200K-paper run that fires at paper 200,000
  means the entire run is "suspect" — the operator must decide which paper(s) have
  wrong markers.
- The current `IngestSummary` has `papers_total`, `papers_succeeded`, `papers_failed`
  but NOT a per-paper breakdown of expected vs actual chunks. Implementing (b) requires
  adding that tracking or relying on `store-stats.jsonl` audit log.

**Can the bulk be resumed?** YES — `ingest_one_paper` is idempotent (embedder sidecar
check; `merge_insert` upsert). The operator can re-run with `--limit` or re-run
selectively. But the debugging cost to identify WHICH paper has the wrong count is high.

**Does (b) duplicate `make reconcile`?** NO — (b) catches arithmetic bugs. Reconcile
heals existing marker drift. Reconcile would FIX the problem but cannot identify the
source of the divergence (it would just recount and rewrite each marker, masking the bug).

### Blast-radius asymmetry: operator-actionable error messages

Per CLAUDE.md §4.7, both must use `if ... raise RuntimeError(...)`. The error message
content:

**Variant (a) — inside `write_chunks`:**
```
RuntimeError: WAP gate (a): corpus-version.json marker at {lancedb_path} was written
with chunk_count={marker_count} but tbl.count_rows()={actual_count} at corpus_version
{dataset_version}. This indicates a marker serialization or file-truncation failure.
Runbook: docs/ops/corpus-drift-runbook.md. Run `make reconcile` to repair.
```
Include: `lancedb_path`, `marker_count` (read back from file), `actual_count`, `dataset_version`.

**Variant (b) — at end of `run_bulk_ingest`:**
```
RuntimeError: WAP gate (b): expected_total={expected_total} chunks across
{papers_total} papers but tbl.count_rows()={actual_count} in staging LanceDB at
{lancedb_staging_path} (delta={actual_count - expected_total}).
Check store-stats.jsonl for per-paper chunk counts. Runbook: docs/ops/corpus-drift-runbook.md.
```
Include: `expected_total`, `papers_total`, `actual_count`, `lancedb_staging_path`, delta.

The messages can share the `docs/ops/corpus-drift-runbook.md` reference (already shipped in m2).

## What does NEITHER catch?

1. **FM-10: swallowed marker-write exception.** The current `try/except Exception` block
   in `write_chunks` (lines 970–977) swallows marker-write failures with a log error.
   **Both (a) and (b) cannot fire if the marker was never written.** Implementing (a)
   requires ALSO removing the swallow — the marker-write must be allowed to raise, and
   the post-write re-read must be inside the same `try` block. This is a load-bearing
   behavioral change to the "best-effort" contract.

2. **FM-11: sibling marker writers.** `server/routes/notebooks._rewrite_corpus_version_marker`
   and `tools/notebook_reconcile_marker.py` both write `corpus-version.json` directly without
   calling `ingest.store.write_corpus_version_marker`. Any arithmetic bug in those writers
   is outside the WAP gate scope. Documented in m3 follow-up F2-extension.

3. **Mid-session live drift (deferred per roadmap Won't §CAND-5).** Between server startup
   and the next restart, new chunks can be ingested (notebook ingest, textbook ingest)
   without updating `Resources.startup_chunk_count`. The WAP gate at write-time fires
   correctly but the in-memory cache goes stale. Deferred per the roadmap: "Revisit only
   if KR-2's alert rules miss a documented mid-session scenario."

## Variant (b)'s epistemic problem: caller-provided "expected" is the same arithmetic

The spike prompt asks: "Is that genuinely a CALLER-provided expectation, or is it just
deferring the same arithmetic from the writer to the caller?"

Direct answer from reading `bulk_ingest.py`: `expected_total` would be accumulated as
`sum(outcome.chunks_written for each paper)` where `outcome.chunks_written = len(chunks)`.
The chunker's output IS the source of truth for how many chunks should have been written.
So `expected_total` = sum of `len(chunks)` across all papers. `tbl.count_rows()` at
end-of-run should equal this sum if no rows were deduplicated (idempotent upserts).

**Critical observation:** On a FRESH staging LanceDB (no prior rows), `len(chunks)` summed
IS a valid expected total because every write is an insert (no updates). On a RE-RUN
against an existing staging LanceDB (some papers already ingested), the `merge_insert`
performs upserts — rows already present are updated, not inserted twice. So
`tbl.count_rows()` after re-run == count of DISTINCT chunk_ids, while `expected_total`
accumulated from `len(chunks)` overcounts re-processed papers. This means variant (b)
would produce **false positives on idempotent re-runs** unless the bulk driver
explicitly tracks whether each paper was a fresh-write vs. re-run.

This is NOT a problem for variant (a): `count_rows()` vs. just-written marker are
both based on the SAME post-merge table state, regardless of upsert behavior.

## Failure-mode coverage decision

**Recommendation: Ship variant (a) ONLY.**

Reasoning:

1. **(a) catches more failure modes.** FM-1, FM-2, FM-3, FM-7 are all marker-side
   failures caught by (a). FM-4 (bulk arithmetic) is the only mode caught by (b) alone —
   but as shown above, implementing (b) correctly for re-run safety is non-trivial.

2. **(b) produces false positives on idempotent re-runs.** The staging LanceDB is
   designed for re-runs (embedder sidecar check, `merge_insert` upsert). A bulk
   operator running the 200K-paper ingest in stages would trigger (b)'s false-positive
   constantly, making the gate unusable in practice.

3. **(a) fires at write-time, not hours later.** Fail-fast per paper is operationally
   superior. An error at paper 50 of 200K lets the operator fix the issue before
   investing a 2-day GPU run.

4. **(a) requires a critical behavioral change: re-raise marker-write failures.**
   The current `try/except Exception` swallow must become either (i) a raise, or (ii)
   a conditional raise only when the post-write re-read fails. Option (ii) is the
   gentler change: if the marker was never written at all, the re-read raises
   `FileNotFoundError` which becomes the RuntimeError.

5. **The m3 integration test already catches the divergence-detection path at startup.**
   The WAP gate at write-time adds orthogonal fail-fast coverage: the integration test
   catches "server boots with divergent corpus" (startup-time); variant (a) catches
   "write produces divergent marker" (write-time). Both are needed for defense-in-depth.

**Does the WAP gate add value over the m3 startup-time check?** YES — the value is
fail-fast at write-time vs. wait-until-restart. An operator running bulk ingest
overnight gets the error at paper N+1, not the next morning when they restart the
server. The m3 test catches divergence in CI; (a) catches it in production before
the wrong marker is ever live.

## Open questions

One non-blocking question: the current "best-effort" marker-write contract (the swallow)
was explicitly designed in `ingest/store.py:905–910` to prevent marker failures from
aborting ingest. Changing to a raise changes this contract. The implementer should
decide whether to: (i) fully re-raise (breaking the best-effort guarantee), or (ii)
do the post-write re-read as a SEPARATE validation step that raises on divergence
but does NOT re-raise the original marker-write exception if the marker happens to
have been written correctly anyway. Option (ii) is strictly safer: it only raises when
the gate DETECTS a divergence, not on every transient I/O hiccup.

**Recommendation:** Option (ii) — add a post-marker-write re-read block that:
```python
# After write_corpus_version_marker returns successfully:
re_read_marker = read_corpus_version(target_path)
if re_read_marker is None or re_read_marker.chunk_count != actual_count:
    raise RuntimeError(f"WAP gate (a): ...")
```
This preserves the best-effort contract for transient I/O failures (the original exception
propagates), while adding a check for the case where the marker was written but with
wrong content.

If the implementer finds this too subtle, option (i) is also acceptable — the important
thing is the gate EXISTS. Document the behavior change in the implementation summary.

## External writes the implementation will require

None — this milestone is purely local. The implementation modifies `ingest/store.py`
and tests. No git push, PR, or infra mutation is needed from the sub-agent. The
eventual `git push origin main` is a Phase 4 main-thread user-authorized event.
