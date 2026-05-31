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

### Site (rect F1 — CRITICAL)

`ingest/store.py::write_chunks`, **AFTER** the existing `try/except Exception` block at `ingest/store.py:931-977` closes, **before** the `_append_store_stats(stats)` call at line 985. The WAP gate is OUTSIDE the best-effort swallow's scope so its `raise RuntimeError(...)` propagates to the caller. Placing the gate INSIDE the try block (the pre-rect-F1 specification) would have the `except Exception as exc: logger.error(...)` at lines 970-976 catch the gate's own raise — a structurally non-functional gate. The adversary critic flagged this as CRITICAL F1; corrected here.

### Code (rect F3 — HIGH; ValueError handling added)

```python
# WAP gate (corpus-integrity-completion-e1, per spike-1 decision; placed
# OUTSIDE the existing try/except at lines 931-977 per rect F1).
# Read the just-written marker back from disk and verify its chunk_count
# matches a fresh tbl.count_rows(). This catches marker-side failures
# (FM-1 reintroduced pre-m1 bug; FM-2 JSON serialization wrong value;
# FM-3 atomic rename truncated content; FM-7 int overflow on huge corpus;
# FM-10 swallowed write that left no file OR a stale prior marker — see
# §4 FM-10 row for the stale-marker case) without depending on a second
# tbl.count_rows() (which is itself tautological under the
# single-writer-per-dataset model per spike-1 §2 Problem 1).
try:
    re_read_marker = read_corpus_version(target_path)
except ValueError as exc:
    # FM-3 explicit path: atomic rename + os.replace produced a
    # truncated/corrupt JSON. read_corpus_version raises ValueError on
    # malformed JSON per server/corpus.py:525-538 (rect F3). Surface
    # this as a WAP-gate RuntimeError so the caller path is uniform.
    raise RuntimeError(
        f"WAP gate: corpus-version.json marker at {target_path} is "
        f"malformed and cannot be parsed: {exc}. Likely cause: a "
        f"truncated atomic rename, a partial write before os.replace, "
        f"or a JSON serialization bug in write_corpus_version_marker. "
        f"Run `make reconcile` to repair. "
        f"Runbook: docs/ops/corpus-drift-runbook.md."
    ) from exc

fresh_count = tbl.count_rows()
if re_read_marker is None:
    raise RuntimeError(
        f"WAP gate: corpus-version.json marker at {target_path} is "
        f"absent after write_corpus_version_marker returned. This is "
        f"the cold-clone case: no prior marker existed AND the write "
        f"was silently swallowed by the best-effort try/except above "
        f"(check the immediately preceding log line for a "
        f"'could not write corpus-version.json marker' warning). "
        f"Table count: {fresh_count}. "
        f"Run `make reconcile` to write a fresh marker. "
        f"Runbook: docs/ops/corpus-drift-runbook.md."
    )
if re_read_marker.chunk_count != fresh_count:
    raise RuntimeError(
        f"WAP gate: corpus-version.json marker at {target_path} reports "
        f"chunk_count={re_read_marker.chunk_count} but tbl.count_rows()="
        f"{fresh_count} for corpus_version={dataset_version}. Likely "
        f"causes: (1) a pre-m1-style len(chunks)-instead-of-count_rows "
        f"arithmetic regression in this call, OR (2) the marker write "
        f"was swallowed by the best-effort try/except above and the "
        f"PRIOR marker's chunk_count is what's being read back (check "
        f"the immediately preceding log line for a "
        f"'could not write corpus-version.json marker' warning). "
        f"Run `make reconcile` to repair the marker. "
        f"Runbook: docs/ops/corpus-drift-runbook.md."
    )
```

### Behavioral contract change (rect F1 — clarified)

The existing `try/except Exception` swallow at `ingest/store.py:931-977` (the m1-era "best-effort" contract for transient I/O failures around the marker write) is **PRESERVED**. The new gate adds a **second validation step that runs AFTER the swallow's scope has closed** — its `raise RuntimeError(...)` propagates to the caller (`ingest_one_paper` → `run_bulk_ingest`) as a per-paper failure signal. The existing best-effort guarantee for the marker write itself is unchanged; the gate is a strictly additive correctness check that fires only on detected divergence.

This is "option (ii)" from R2's open question on the swallow — the gentler change. R2's analysis: "[option ii] is strictly safer: it only raises when the gate DETECTS a divergence, not on every transient I/O hiccup."

### Gate is unconditional (rect F8 — LOW)

The gate runs unconditionally; no feature flag. Precedent: no other gate in `ingest/store.py` is feature-flagged, and the m1-era `tbl.count_rows()`-derived marker fix itself is unconditional. A future need to disable the gate for an unusual operator scenario (e.g. mid-migration spurious divergences) is out-of-scope for e1; if that need arises, an `ARXMCP_WAP_GATE_ENABLED` env var can be added then.

### Test plan for the e1 milestone (rect F2 + F3 — HIGH; rect F4 — MEDIUM)

All tests are written against the gate's POST-swallow placement (rect F1), so a `pytest.raises(RuntimeError)` on the test side correctly receives the gate's raise:

1. **Positive path:** real `write_chunks` → gate passes silently. Reuses the multi-call fixture from `tests/_corpus_helpers.py::seed_corpus_multi_paper` shipped by m3.
2. **Mutation A — wrong marker value:** `monkeypatch.setattr(store_mod, "write_corpus_version_marker", lambda *a, **kw: real_marker(*a, **{**kw, "chunk_count": 1}))`. Assert the WAP gate raises `RuntimeError` with the count-mismatch error message + diagnostic (the chunk_count=1 vs cumulative table count test pattern from m3's mutation test).
3. **Mutation B — missing marker (cold-clone case):** `monkeypatch.setattr(store_mod, "write_corpus_version_marker", lambda *a, **kw: None)` (the lambda intentionally does nothing — the marker file is never written). Assert the WAP gate raises the MISSING-marker error AND the test's `caplog` captures the swallow's "could not write corpus-version.json marker" warning emitted by the existing except block.
4. **Mutation C — malformed marker (rect F3 — corrected):** `monkeypatch.setattr(store_mod, "write_corpus_version_marker", lambda *a, **kw: target_path.write_text("not valid json"))`. Assert the WAP gate raises the malformed-marker error (the new `except ValueError → raise RuntimeError` arm catches this path).
5. **Mutation D — stale-marker case (rect F4 — added):** Pre-seed the LanceDB with a valid marker (e.g. via `seed_corpus_multi_paper(n_papers=2)`), then make a third `write_chunks` call whose `write_corpus_version_marker` is monkeypatched to raise an `IOError`. Assert (a) the existing swallow's warning was logged AND (b) the WAP gate raises the COUNT-MISMATCH error (because the stale prior marker has a smaller chunk_count than the post-third-call `tbl.count_rows()`). This is the production-common path the synthesis's original FM-10 description missed — the operator sees a count mismatch, NOT a missing marker, and the error message guides them to check the preceding swallow-warning log line.

All mutation tests live in a new test file (likely `tests/test_write_chunks_wap_gate.py` per the e1 milestone's discretion).

### Operator-actionability (rect F6 — MEDIUM)

Each gate error message cites:
- The full LanceDB path (`target_path`)
- The diagnostic numerical state (claimed count, actual count, corpus_version)
- The likely-cause enumeration (pre-m1 regression vs swallow-stale-marker vs missing-marker vs malformed)
- Cross-reference to the preceding swallow-warning log line (so operators can distinguish swallow-induced cases from arithmetic regressions)
- The remediation command (`make reconcile`)
- The runbook URL (`docs/ops/corpus-drift-runbook.md` — shipped by m2)

**The e1 milestone also extends `docs/ops/corpus-drift-runbook.md` with a new section** covering the WAP-gate `RuntimeError` failure path: symptom (the gate's RuntimeError text shows up in the ingest log), quick triage (check the preceding "could not write corpus-version.json marker" warning to distinguish a swallowed I/O failure from an arithmetic regression), remediation (`make reconcile`), and escalation. Without this extension, the runbook only covers the two Prometheus-alert paths (`ArXMCPCorpusCountRowsFailed`, `ArXMCPCorpusUnindexedRows`) — operators following the gate's `runbook_url` would arrive at a runbook that doesn't mention their actual failure path. The runbook extension lands in the SAME commit as the gate code (no separate-tracker drift).

This is sufficient for a 2am-pager scenario: the operator can immediately reach for `make reconcile` and consult the (newly-extended) runbook for context.

## 4. Failure-mode coverage

Variant (a) catches:
- **FM-1** Pre-m1 bug shape (`chunk_count = len(chunks)` reintroduced) — marker-stored value differs from fresh `count_rows()`.
- **FM-2** JSON serialization wrong value (float truncation, int overflow under future schema change).
- **FM-3** Atomic rename completes but file silently truncated — `read_corpus_version` raises `ValueError`, the gate's new `except ValueError → raise RuntimeError` arm surfaces it (rect F3).
- **FM-7** Marker chunk_count int overflow.
- **FM-10 (rect F4 — corrected from a misleading "PARTIAL" claim):** Swallowed marker-write exception fires DIFFERENT arms of the gate depending on prior state. (a) On a **cold-clone** call (no prior marker file at `target_path`), `read_corpus_version` returns `None` and the gate raises the MISSING-marker error. (b) On the **production-common** path (second+ `write_chunks` call on a dataset that already has a marker from prior runs), the swallowed marker write leaves the PRIOR marker file on disk. `read_corpus_version` returns the stale `CorpusVersionInfo`; the gate fires on the count-mismatch arm (stale `chunk_count` ≠ fresh `count_rows()`), NOT on the MISSING-marker arm. The gate STILL catches the failure, but the operator-visible error text says "count mismatch," not "missing marker." The corrected error messages in §3 explicitly cite the preceding swallow-warning log line so operators can distinguish the stale-swallow case from a true arithmetic regression. This stale-swallow case is exercised by Mutation D in the §3 test plan.

Variant (a) does NOT catch (and these are EXPLICITLY out-of-scope per the parent roadmap's Won't list):
- FM-4 caller arithmetic errors in `bulk_ingest.py` (m1 fixed the original instance; m3 integration test catches future regression at the write boundary via the multi-call fixture).
- FM-5 TOCTOU race (excluded by single-writer-per-dataset constraint).
- FM-6 schema drift (validated by `server.corpus.read_corpus_version` at read time).
- FM-8 marker file written to wrong path (config validation problem).
- FM-9 silently skipped paper (failure log already captures this).
- FM-11 sibling marker writers (`server/routes/notebooks._rewrite_corpus_version_marker`, `tools/notebook_reconcile_marker.py`) — tracked in m3 follow-up F2-extension for a future ops-hardening epic.

The coverage is precisely what the parent roadmap KR-3 promised: "`ingest/store.py::write_chunks` raises `RuntimeError` on a post-`write_corpus_version_marker` second `count_rows()` mismatch against the just-written marker file" — with the spike-corrected understanding that the comparison is marker-stored vs. fresh `count_rows()`, not pre-marker `count_rows()` vs. post-marker `count_rows()`.

## 5. Estimated effort for the e1 milestone

- **~35 LOC production code** in `ingest/store.py` (the gate + the `from server.corpus import read_corpus_version` import — rect F3 added the ValueError handling arm so the count grew from ~25 to ~35 LOC).
- **Import direction verified (rect F5):** `ingest/bm25_indexer.py:87` already does `from server.corpus import open_chunks_table`, establishing the `server → ingest` direction is acceptable in the project's module-dependency graph. The new `read_corpus_version` import in `ingest/store.py` is consistent with this precedent — e1 does NOT need to do a separate import-direction verification.
- **~120 LOC test code** in a new `tests/test_write_chunks_wap_gate.py` (4 mutation tests + 1 positive + 1 sanity — Mutation D for the stale-marker case was added per rect F4).
- **~30 LOC documentation** extending `docs/ops/corpus-drift-runbook.md` with the WAP-gate `RuntimeError` failure-path section per rect F6.
- **Total: ~185 LOC**, well within the **S** complexity rating (≤ 1 week execution) that the parent roadmap's Phase 2 §e1 already assigned.

## 6. Spike-1 deferrals (recorded for future epic awareness)

- **No (b) variant ships in the corpus-integrity-completion epic** (rect F7 — narrowed from a too-strong "ever"). The idempotent-re-run false-positive landmine is structural under the current `WriteStats` shape. Future work that needs caller-arithmetic detection would route through a `chunks_written_distinct` field on `WriteStats` so the bulk driver can track distinct chunk_ids — but that's out-of-scope here. If a future epic re-litigates (b), the spike's binding character covers only this epic; that future epic would run its own spike.
- **Sibling marker writers** (`server/routes/notebooks._rewrite_corpus_version_marker`, `tools/notebook_reconcile_marker.py`) need their own WAP gates if the operator ever experiences a regression in those paths. Tracked under m3 follow-up F2-extension; not e1's problem.
- **`ingest/re_embed.py`** calls `write_chunks` twice per paper (copy + re-embed). The (a) gate inside `write_chunks` covers EVERY call automatically — no separate wiring required. This is a structural advantage of (a) over (b) noted by R1.
- **Mid-session live drift** (CAND-5 from the capability-scout, deferred from this epic) remains explicitly Won't — the WAP gate is write-time only; cross-restart drift is the m2 startup reconciliation's job.

## 7. Spike outcome summary

The spike achieved its purpose. The roadmap's pre-recommendation of (c) is REFUTED with concrete codebase grounding. The future `e1` milestone has a precise, opinionated implementation contract that catches ~5 failure modes (FM-1, FM-2, FM-3, FM-7, FM-10) at fail-fast latency, with a defensible Won't list (5 out-of-scope failure modes) and clear continuity with the m1 + m2 + m3 deliverables (the gate uses m1's `tbl.count_rows()`-derived marker invariant, raises `RuntimeError` with m2's runbook URL, and is covered by m3's multi-call integration test fixture pattern).

The e1 milestone is unblocked.
