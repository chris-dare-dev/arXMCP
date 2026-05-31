# Binding Decision — corpus-integrity-completion-spike-1

**Status:** BINDING (≤ ½ day spike per the parent roadmap §Spike lane)
**Feeds:** Future `corpus-integrity-completion-e1` epic milestone
**Author:** main orchestrator session
**Date:** 2026-05-31

This document is the SOLE deliverable of the spike. It is the binding implementation contract that the future `e1` milestone consumes when its own `/milestone-pipeline` invocation runs.

---

## 1. The decision in one sentence

**Ship variant (a) ONLY** for the e1 WAP gate, where (a) is **redefined** as a *marker-file readback verify* — read the just-written `corpus-version.json` back from disk, parse its `chunk_count`, compare against a fresh `tbl.count_rows()`, and raise on mismatch. The roadmap's pre-recommendation of (c) is **REFUTED**; variant (b) does NOT ship.

## 2. What the roadmap pre-recommended, and why it was wrong

The parent roadmap (`plans/corpus-integrity-completion-roadmap.md`) §Sharpening Q2 pre-recommended option **(c) — ship both** variants:

- **(a)** post-marker second `tbl.count_rows()` in `write_chunks`
- **(b)** caller-provided `expected_total` threaded from `ingest/bulk_ingest.py`
- **(c)** ship BOTH

Both researchers caught **different load-bearing problems** with this pre-recommendation:

### Problem 1 — variant (a) as literally written is itself tautological

R1 confirmed the challenger's claim against `ingest/store.py:938-953`: `stats.total_rows_after_commit = tbl.count_rows()` is set BEFORE `write_corpus_version_marker(...)` is called. Under the single-writer-per-dataset model (`ingest/store.py` module docstring lines 44-55), the table CANNOT mutate between the pre-marker and a post-marker `count_rows()`. Both reads return the same value — comparing them is `chunk_count == chunk_count`, identity.

**The fix:** the WAP gate must compare the marker-file's STORED VALUE (read back from disk and parsed) against a fresh `count_rows()`. Two different observations of two different state surfaces. This is the canonical WAP "Write — Audit — Publish" shape (R1 §"Critical refinement for variant (a)").

### Problem 2 — variant (b) false-fires on idempotent re-runs

R2 traced through the staging-LanceDB's idempotency contract: `ingest/store.py::write_chunks` uses `merge_insert` (upsert) and the per-paper embedder uses sidecar-file idempotency checks. On a RESUMED bulk run (operator partial-completion is the production-normal case), `expected_total = sum(len(chunks))` would overcount re-processed papers while `tbl.count_rows()` correctly reports the distinct row count.

A 200K-paper bulk operator running in stages would trigger (b)'s false-positive on every resume — the gate becomes unusable noise.

**The fix:** variant (b) does not ship. Per-paper variant-(a) coverage already catches the same bug class (FM-1 from R2's matrix) at the write boundary, with fail-fast latency advantage.

### Problem 3 — both researchers' (b) escape hatches collapse to (a)

R1 offered an escape hatch: "use `WriteStats.total_rows_after_commit` from the last call" as the expected-total. R2 separately analyzed the same shape and noted it's equivalent to reading the writer's own report — i.e. (b) collapses into (a) when the false-positive risk is engineered around.

**Conclusion:** there is no shape of (b) that genuinely adds coverage beyond what (a) provides while remaining false-positive-free on resumable runs.

## 3. The binding implementation shape for e1

### Site

`ingest/store.py::write_chunks`, immediately after `write_corpus_version_marker(...)` returns (inside the existing `try:` block at lines 938-977).

### Code

```python
# WAP gate (corpus-integrity-completion-e1, per spike-1 decision):
# Read the just-written marker back from disk and verify its chunk_count
# matches a fresh tbl.count_rows(). This catches marker-side failures
# (FM-1 reintroduced pre-m1 bug; FM-2 JSON serialization wrong value;
# FM-3 atomic rename truncated content; FM-7 int overflow on huge corpus;
# FM-10 swallowed write that produced no file) without depending on a
# second tbl.count_rows() (which is itself tautological under the
# single-writer-per-dataset model per spike-1 §2 Problem 1).
re_read_marker = read_corpus_version(target_path)
fresh_count = tbl.count_rows()
if re_read_marker is None:
    raise RuntimeError(
        f"WAP gate: corpus-version.json marker at {target_path} could "
        f"not be read back after write (write_corpus_version_marker "
        f"either silently swallowed an exception or wrote a malformed "
        f"JSON that fails parse). Table count: {fresh_count}. "
        f"Run `make reconcile` to repair. "
        f"Runbook: docs/ops/corpus-drift-runbook.md."
    )
if re_read_marker.chunk_count != fresh_count:
    raise RuntimeError(
        f"WAP gate: corpus-version.json marker at {target_path} reports "
        f"chunk_count={re_read_marker.chunk_count} but tbl.count_rows()="
        f"{fresh_count} for corpus_version={dataset_version}. This "
        f"indicates a marker-write arithmetic or serialization failure "
        f"(e.g. a pre-m1-style len(chunks)-instead-of-count_rows "
        f"regression). Run `make reconcile` to repair the marker. "
        f"Runbook: docs/ops/corpus-drift-runbook.md."
    )
```

### Behavioral contract change

The existing `try/except Exception` swallow at `ingest/store.py:970-977` (the m1-era "best-effort" contract for transient I/O failures around the marker write) is **PRESERVED**. The new gate adds a **second validation step** that runs after `write_corpus_version_marker` returns successfully. The gate raises **only when divergence is detected** — the existing best-effort guarantee for transient I/O on the marker write itself is unchanged.

This is "option (ii)" from R2's open question on the swallow — the gentler change. R2's analysis: "[option ii] is strictly safer: it only raises when the gate DETECTS a divergence, not on every transient I/O hiccup."

### Test plan for the e1 milestone

1. **Positive path:** real `write_chunks` → gate passes silently. Reuses the multi-call fixture from `tests/_corpus_helpers.py::seed_corpus_multi_paper` shipped by m3.
2. **Mutation A — wrong marker value:** `monkeypatch.setattr(store_mod, "write_corpus_version_marker", lambda *a, **kw: real_marker(*a, **{**kw, "chunk_count": 1}))`. Assert the WAP gate raises `RuntimeError` with the divergence error message + diagnostic.
3. **Mutation B — missing marker:** `monkeypatch.setattr(store_mod, "write_corpus_version_marker", lambda *a, **kw: None)`. Assert the WAP gate raises the MISSING-marker error.
4. **Mutation C — malformed marker:** `monkeypatch.setattr(store_mod, "write_corpus_version_marker", lambda *a, **kw: target.write_text("not valid json"))`. Assert `read_corpus_version` returns None and the gate raises.

All three mutation tests live in a new test file (likely `tests/test_write_chunks_wap_gate.py` per the e1 milestone's discretion).

### Operator-actionability

Both error messages cite:
- The full LanceDB path (`target_path`)
- The diagnostic numerical state (claimed count, actual count, corpus_version)
- The remediation command (`make reconcile`)
- The runbook URL (`docs/ops/corpus-drift-runbook.md` — shipped by m2)

This is sufficient for a 2am-pager scenario: the operator can immediately reach for `make reconcile` and consult the runbook for context.

## 4. Failure-mode coverage

Variant (a) catches:
- **FM-1** Pre-m1 bug shape (`chunk_count = len(chunks)` reintroduced) — marker-stored value differs from fresh `count_rows()`.
- **FM-2** JSON serialization wrong value (float truncation, int overflow under future schema change).
- **FM-3** Atomic rename completes but file silently truncated.
- **FM-7** Marker chunk_count int overflow.
- **FM-10** Swallowed marker-write exception — `read_corpus_version` returns None, MISSING-marker error raises.

Variant (a) does NOT catch (and these are EXPLICITLY out-of-scope per the parent roadmap's Won't list):
- FM-4 caller arithmetic errors in `bulk_ingest.py` (m1 fixed the original instance; m3 integration test catches future regression at the write boundary via the multi-call fixture).
- FM-5 TOCTOU race (excluded by single-writer-per-dataset constraint).
- FM-6 schema drift (validated by `server.corpus.read_corpus_version` at read time).
- FM-8 marker file written to wrong path (config validation problem).
- FM-9 silently skipped paper (failure log already captures this).
- FM-11 sibling marker writers (`server/routes/notebooks._rewrite_corpus_version_marker`, `tools/notebook_reconcile_marker.py`) — tracked in m3 follow-up F2-extension for a future ops-hardening epic.

The coverage is precisely what the parent roadmap KR-3 promised: "`ingest/store.py::write_chunks` raises `RuntimeError` on a post-`write_corpus_version_marker` second `count_rows()` mismatch against the just-written marker file" — with the spike-corrected understanding that the comparison is marker-stored vs. fresh `count_rows()`, not pre-marker `count_rows()` vs. post-marker `count_rows()`.

## 5. Estimated effort for the e1 milestone

- **~25 LOC production code** in `ingest/store.py` (the gate + a brief import of `read_corpus_version` from `server.corpus` if not already imported in `ingest/store.py`; the e1 implementer must verify the import direction is acceptable per the project's module-dependency graph).
- **~80 LOC test code** in a new `tests/test_write_chunks_wap_gate.py` (3 mutation tests + 1 positive + 1 sanity).
- **Total: ~110 LOC**, well within the **S** complexity rating (≤ 1 week execution) that the parent roadmap's Phase 2 §e1 already assigned.

## 6. Spike-1 deferrals (recorded for future epic awareness)

- **No (b) variant ever ships** — the idempotent-re-run false-positive landmine is structural. If future work needs caller-arithmetic detection, the right shape is to ADD a `chunks_written_distinct` field to `WriteStats` and have the bulk driver track distinct chunk_ids — but this is out-of-scope for the corpus-integrity-completion epic.
- **Sibling marker writers** (`server/routes/notebooks._rewrite_corpus_version_marker`, `tools/notebook_reconcile_marker.py`) need their own WAP gates if the operator ever experiences a regression in those paths. Tracked under m3 follow-up F2-extension; not e1's problem.
- **`ingest/re_embed.py`** calls `write_chunks` twice per paper (copy + re-embed). The (a) gate inside `write_chunks` covers EVERY call automatically — no separate wiring required. This is a structural advantage of (a) over (b) noted by R1.
- **Mid-session live drift** (CAND-5 from the capability-scout, deferred from this epic) remains explicitly Won't — the WAP gate is write-time only; cross-restart drift is the m2 startup reconciliation's job.

## 7. Spike outcome summary

The spike achieved its purpose. The roadmap's pre-recommendation of (c) is REFUTED with concrete codebase grounding. The future `e1` milestone has a precise, opinionated implementation contract that catches ~5 failure modes (FM-1, FM-2, FM-3, FM-7, FM-10) at fail-fast latency, with a defensible Won't list (5 out-of-scope failure modes) and clear continuity with the m1 + m2 + m3 deliverables (the gate uses m1's `tbl.count_rows()`-derived marker invariant, raises `RuntimeError` with m2's runbook URL, and is covered by m3's multi-call integration test fixture pattern).

The e1 milestone is unblocked.
