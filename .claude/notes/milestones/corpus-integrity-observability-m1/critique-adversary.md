# Critique — corpus-integrity-observability-m1

**Critic:** adversary
**Generated:** 2026-05-28T00:00:00Z
**Commit range:** 630112407cf79582899f1e859bbda10885c99151..8e58c4263b4bb29260b4bff620260f7d21ffa319
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the fix is correct, minimal (24 LOC + 3 tests, one file), and the regression test genuinely fails pre-fix (`assert 2 == 5`); the only material gaps are test-surface coverage, not correctness.
- Finding counts: 0 CRITICAL, 0 HIGH, 3 MEDIUM, 2 LOW.
- Highest-risk file:line is `ingest/store.py:917-919` — the per-call `count_rows()` + distinct-`paper_id` scan; correctness is sound, the residual concern is cost characterization and an untested empty/zero-row marker path.
- Approach-A's O(N)-per-call distinct scan is defensible: the 200K-paper bulk path is SCOPED-OUT per CLAUDE.md §3, and `bulk_ingest` is single-process-sequential — escalation to R2's running-set is documented but not warranted now. Recorded as F1 MEDIUM, not MAJOR.
- Cache byte-stability axis verified CLEAN: `EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_BP1_SHA256` files are untouched in the range; the marker counts are read only by `server/corpus.py` + a `server/resources.py:338` startup INFO log, never entering any prompt-cache key or tool-result payload (`version`, not counts, gates the cache).
- The documented single-writer MVCC model (`store.py:44-55`) makes the `dataset_version` (L862) vs `count_rows()` (L917) read-ordering consistent; no skew under the project's stated constraints. Noted, not a finding.
- The re_embed staging path is a strict improvement: the copy path seeds the staging table with every unchanged id + the re-embed path the changed ids, so the final per-paper marker now reflects the full cumulative staging corpus before cutover (pre-fix it held only the last paper's batch).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — O(N)-per-call distinct paper_id scan is O(N^2) over a bulk run

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/store.py:918-920
- **What:** `set(tbl.to_arrow().select(["paper_id"])["paper_id"].to_pylist())` materializes the full `paper_id` column on every per-paper `write_chunks` call. Over an N-paper sequential bulk run that is N scans of a growing table → O(N^2) total column materialization.
- **Why it matters:** At the seed (50-paper) and notebook (tens-of-papers, ≤10K-row) scale that actually runs this path today, the per-call cost is sub-millisecond and negligible. The O(N^2) profile only bites a 200K-paper full-corpus bulk run, which CLAUDE.md §3 marks SCOPED-OUT/folded (E11/E12). So this is a latent foot-gun, not a present bug — correctly characterized as MEDIUM, not MAJOR. Approach A's cost justification in the synthesis is sound.
- **Proposed fix:** None required for v1. If a future bulk-scale milestone reactivates the 200K path, escalate to research-brief-2's R2 running-set: thread an optional `cumulative_paper_ids: set[str] | None` through `write_chunks` that the caller (`bulk_ingest` / `re_embed`) accumulates, falling back to the table scan when `None` (preserves single-call-caller correctness). Do NOT pre-build this now — it adds caller surface for a scoped-out path.
- **Regression guard:** If escalated: a test asserting the running-set and table-scan paths produce identical `paper_count` for the same multi-paper sequence. Not required at v1.

### F2 — Zero-row / empty-chunks marker path is untested

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_store.py:1571-1630
- **What:** `write_chunks([], embeddings, ...)` does NOT early-return (`store.py:796-801` logs INFO then continues); it builds an empty arrow table, skips `merge_insert` (the `num_rows > 0` guard at `:832`), runs `_create_indices` on the table, then reaches the marker block and writes `chunk_count = tbl.count_rows()` / `paper_count = 0` on a fresh empty table. None of the 3 new tests exercise this path. The synthesis FM-7 claim that `write_chunks([])` "returns early today" is factually wrong about the code (it does not early-return) — the behavior happens to be benign, but the synthesis reasoning that justified skipping the test is incorrect.
- **Why it matters:** The first-ever-empty-call case creates a zero-row table and writes `chunk_count=0 / paper_count=0`. That is correct, but it is asserted-as-safe on a wrong premise (the synthesis thought there was an early return). A latent edit that later adds a real early-return before the marker write would silently leave NO marker on the empty path with zero test coverage to catch it.
- **Proposed fix:** Add a test asserting `write_chunks([], _make_synthetic_embeddings([]), lancedb_path=...)` writes a marker with `chunk_count == 0` and `paper_count == 0` (fresh path), AND that an empty call AFTER a non-empty write leaves the cumulative counts intact (the empty call must not zero out a populated marker). The second case is the higher-value assertion — it pins the cumulative-table semantics against the empty-batch edge.
- **Regression guard:** The two-assertion test above, under `TestCorpusVersionMarkerReconciliation`.

### F3 — Per-paper-caller dispatch paths (re_embed two-path, bulk_ingest loop) untested at the marker boundary

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/re_embed.py:528-562
- **What:** The 3 new tests call `write_chunks` directly with disjoint single-paper batches. They do NOT exercise the actual production callers: `re_embed`'s copy-path + re-embed-path double-dispatch into one `staging_lancedb_path` (`re_embed.py:528,558`), `bulk_ingest.ingest_one_paper` (`bulk_ingest.py:416` loop), or `tools/notebook_textbook_ingest` per-paper loop. The fix is verified at the unit boundary but the claim "all per-paper callers are fixed with no caller edits" (synthesis §2) is asserted, not test-covered.
- **Why it matters:** The re_embed path is the subtlest: copy_chunks and re_embed_chunks for the SAME paper can both call `write_chunks` against staging within one paper's processing, and the staging table accumulates across all papers. The cumulative-table marker semantics are exactly what makes the post-cutover marker correct, but there is no test pinning that a multi-paper re_embed run ends with `marker.chunk_count == staging_tbl.count_rows()`. Manual reasoning confirms it is correct (the copy path seeds every unchanged id), but a regression here would surface only at a live cutover — the exact failure mode this milestone exists to prevent.
- **Proposed fix:** Add one integration-style test that drives `re_embed`'s per-paper processing (or at minimum two write_chunks calls into a shared staging path mixing a copy-record and a re-embed-record) and asserts the final staging marker equals the cumulative staging table. If re_embed's internals are too heavy to drive in a unit test, a lighter test that simulates the copy+re-embed double-dispatch into one path is acceptable.
- **Regression guard:** The integration/simulation test above, under a re_embed or store test module.

### F4 — Marker `version` vs counts read-ordering relies on undocumented in-call invariant

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/store.py:862,917-919
- **What:** `dataset_version` is captured at `:862` (post-`_create_indices`), but `tbl.count_rows()` / `tbl.to_arrow()` execute later at `:917-919`, reading the live tip of the `tbl` handle. Under the project's documented single-writer-per-dataset model (`store.py:44-55`) these are guaranteed consistent — no write lands between L862 and L917 in-process. A concurrent external writer (explicitly out of scope, E11) could make the counts reflect a newer version than the stored `version`.
- **Why it matters:** This is a non-issue under the stated constraints (synthesis FM-3 correctly calls it so). It is LOW only because the consistency is implicit — a reader of the marker block has to walk back 55 lines to the docstring to know the counts and `version` are coherent. No behavior change needed.
- **Proposed fix:** Optional one-line comment at `:917` noting the counts are read under the same single-writer assumption that pins `dataset_version`, so marker `version`/counts are coherent. Pure documentation; defer.
- **Regression guard:** N/A (LOW, no behavior change).

### F5 — lancedb pinned `>=0.6` while fix depends on 0.30.x `to_arrow()` no-kwargs API

- **Severity:** LOW
- **Source:** adversary
- **File:** pyproject.toml:60
- **What:** `pyproject.toml:60` pins `lancedb>=0.6`. The installed version is 0.30.2 and the fix correctly uses `tbl.to_arrow().select(["paper_id"])` (the 0.30.x form — `to_arrow(columns=...)` fails in 0.30.x). But `.to_arrow()` on a Table handle did not exist across the entire `>=0.6` range, so the open lower bound is wider than the API the new code requires.
- **Why it matters:** This is pre-existing pin laxness, not introduced by this milestone, and the lockfile (uv.lock) resolves to 0.30.2 so real installs are fine. The fix correctly avoids the `to_arrow(columns=...)` trap (verified against the installed 0.30.2). Flagged only because this milestone newly adds a dependency on `Table.to_arrow()` against a floor that predates it.
- **Proposed fix:** Out of scope for this correctness milestone; if a dependency-hygiene pass happens, tighten the floor to the version that introduced `Table.to_arrow()`. Defer.
- **Regression guard:** N/A (LOW; covered transitively by uv.lock + the new tests running against the installed version).

## What was done well

- Tight, surgical diff: 24 LOC in one production file plus 3 focused tests; no scope creep, no collateral edits to the server surface.
- The regression test (`test_marker_reflects_table_after_per_paper_writes`) is a true regression — verified to fail pre-fix with `assert 2 == 5`, the exact production bug shape (last-paper-only counts), and passes on the fix.
- Correctly REJECTED the roadmap's "move marker write once-per-run" directive and documented why (FM-1 crash gap, FM-3 MVCC skew, FM-4 single-call-caller break) — a disciplined deviation backed by both researchers, recorded in the impl summary.
- Cache byte-stability preserved with zero ambiguity: the marker counts are read only by `server/corpus.py` + a startup INFO log; `version` (untouched) is the sole cache/checkout gate. Schema-hash and BP1-hash files are genuinely untouched in the range.
- Correctly used the lancedb 0.30.x `to_arrow().select([...])` form and called it out in a comment (`store.py:915`), avoiding the documented `to_arrow(columns=...)` trap that bit earlier re_embed work.
- `count_rows()` chosen over a full row scan for `chunk_count` — O(1) Lance fragment metadata, the right primitive.
- No `assert` introduced into non-test `ingest/store.py` (the `-O`-strip ban is respected); the test-only `assert`s are correct pytest usage.
- The fix is inherently idempotent (count-from-table, not count-from-batch), and the `test_reingest_marker_is_idempotent` test pins that an upsert re-run does not double-count.
- The existing best-effort `except Exception` swallow scope was correctly extended to wrap the new `count_rows()`/`to_arrow()` calls, so a marker-count failure cannot abort an otherwise-committed ingest — consistent with the documented "marker write is best-effort" contract.

## Recommended rectification order

1. F2 — add the empty/zero-row + empty-after-populated marker test (cheap, ≤15 LOC, closes a coverage gap the synthesis mis-justified).
2. F3 — add the re_embed copy+re-embed double-dispatch cumulative-marker test (the highest-value missing coverage; this is the live-cutover failure mode the milestone exists to prevent).
3. F1 — no action now; record the R2 running-set escalation as the documented path if the 200K bulk milestone reactivates.
4. F4 — optional one-line consistency comment at store.py:917; defer.
5. F5 — defer to a dependency-hygiene pass; out of scope here.

## Rectification status (filled by Phase 4)

- **F2 (MEDIUM) — FIXED.** Added two tests to `TestCorpusVersionMarkerReconciliation`:
  `test_empty_chunks_first_call_writes_zero_marker` (pins the real behavior — the
  empty path does NOT early-return; it writes a 0/0 marker) and
  `test_empty_chunks_after_populated_preserves_counts` (the higher-value case — an
  empty call after a populated write must NOT zero the marker). The latter FAILS on
  the true pre-fix base (`assert 0 == 3`). The synthesis FM-7 "returns early"
  premise is corrected in the test docstring.
- **F3 (MEDIUM) — FIXED.** Added
  `test_re_embed_copy_and_reembed_dispatch_marker_is_cumulative` simulating
  re_embed's copy-path + re-embed-path double-dispatch (re_embed.py:528,558) across
  3 papers (one appearing in BOTH paths) into one staging path; asserts the final
  marker == cumulative staging table (8 rows / 3 papers). FAILS on the true pre-fix
  base (`assert 3 == 8`) — the exact live-cutover failure mode the milestone exists
  to prevent.
- **F4 (LOW) — FIXED (cheap).** Added a one-line consistency comment at
  `ingest/store.py:917` noting the counts are read off the same `tbl` handle that
  pinned `dataset_version`, under the single-writer model, so marker `version`/counts
  are coherent. Pure documentation; closes the "implicit invariant" concern.
- **F1 (MEDIUM) — DEFERRED (no action warranted).** The adversary itself concluded
  "None required for v1": the O(N^2)-over-bulk profile only bites the SCOPED-OUT
  200K-paper path (CLAUDE.md §3). The R2 running-set escalation is documented in the
  research synthesis + implementation-summary as the path if a bulk-scale milestone
  reactivates. Recorded under deferred_findings.
- **F5 (LOW) — DEFERRED.** Pre-existing `lancedb>=0.6` pin laxness in
  `pyproject.toml:60`, not introduced by this milestone; uv.lock resolves to 0.30.2
  so real installs are fine. Out of scope for a correctness milestone; tighten in a
  future dependency-hygiene pass. Recorded under deferred_findings.

**Invalidation summary:** 5 findings raised (0 CRITICAL, 0 HIGH, 3 MEDIUM, 2 LOW).
3 FIXED (F2, F3, F4), 2 DEFERRED with documented rationale (F1 — adversary-endorsed
no-op; F5 — pre-existing, out of scope). 0 findings invalidated as wrong. The two
new tests are verified to fail on the true pre-fix base.
