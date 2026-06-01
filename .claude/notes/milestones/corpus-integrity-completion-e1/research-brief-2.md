# Research Brief — corpus-integrity-completion-e1

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-31T00:00:00Z

---

## In-codebase context

### Placement verified

The binding decision (`decision.md §3 Site`) places the gate **AFTER** `ingest/store.py:931-977` (the `try/except Exception` swallow block), **before** `_append_store_stats(stats)` at line 985. Verified by reading the actual source: line 970 is `except Exception as exc:`, line 977 closes the except block, and line 985 is `_append_store_stats(stats)`. The gate's `raise RuntimeError(...)` will propagate through the call stack to `ingest_one_paper → run_bulk_ingest` as intended.

### `read_corpus_version` confirmed behavior

From `server/corpus.py:479-538` — verbatim load-bearing constraints:

- Line 523: `if not marker_path.is_file(): return None` — returns `None` when absent (not when a *directory* exists at that path — see FM-12 below).
- Line 527-530: `except json.JSONDecodeError as exc: raise ValueError(...)` — raises `ValueError` on malformed JSON.
- Line 535-538: re-raises `ValueError` on `from_dict` failure (missing required fields, wrong type).

**The function reads from `resolved_path / CORPUS_VERSION_MARKER_NAME` where `resolved_path = Path(lancedb_path)`.** Crucially: `lancedb_path` in `write_chunks` is the DIRECTORY path of the LanceDB dataset, not a file path. The marker is a file INSIDE that directory. This is the same `target_path` the gate code will receive — not a file path. This is fine; `read_corpus_version(target_path)` correctly resolves to `target_path / "corpus-version.json"`.

### monkeypatch target verified

`ingest/store.py` calls `write_corpus_version_marker(...)` as a bare module-level name — NOT via a `self.` reference or a local alias. This means `monkeypatch.setattr(ingest.store, "write_corpus_version_marker", lambda ...)` DOES intercept calls made inside `write_chunks`, because Python name resolution at call time looks up `write_corpus_version_marker` in `ingest.store`'s module namespace. The test plan's monkeypatch pattern (`monkeypatch.setattr(store_mod, "write_corpus_version_marker", ...)`) is correct.

**However**: `read_corpus_version` is imported from `server.corpus`, not defined in `ingest.store`. For Mutation C (malformed marker), the lambda writes the file directly via `target_path.write_text("not valid json")` — this bypasses the need to monkeypatch `read_corpus_version` and correctly causes the subsequent `read_corpus_version(target_path)` call to raise `ValueError`. This approach is sound.

### Import direction

`ingest/bm25_indexer.py:87` already uses `from server.corpus import open_chunks_table`. The new `from server.corpus import read_corpus_version` import in `ingest/store.py` is consistent with this established `ingest → server.corpus` precedent. No new import direction is being introduced.

### LanceDB `count_rows()` semantics

`ingest/store.py` module docstring (lines 38-55): **"LanceDB's own MVCC layer serializes concurrent writers."** Under the single-writer-per-dataset model, `tbl.count_rows()` inside the gate reads from the same `tbl` handle opened at the top of `write_chunks`. This handle reflects the post-`merge_insert`, post-`_create_indices` committed state. LanceDB's `count_rows()` is documented as O(1) (fragment metadata scan, not a full row scan) and reflects committed rows visible to this open handle — not a cross-session isolation boundary. There is no case where committed rows are invisible to a `count_rows()` on the same handle in the same process.

### No MCP tool surface changes

This milestone touches only `ingest/store.py`, `tests/test_write_chunks_wap_gate.py`, and `docs/ops/corpus-drift-runbook.md`. No MCP tools are added, removed, or modified. `EXPECTED_TOOL_SCHEMA_SHA256` does NOT need re-pinning.

### No feature flag

`decision.md §3`: "The gate runs unconditionally; no feature flag." This matches the project convention — no other gate in `ingest/store.py` is feature-flagged.

### Doc placement: `docs/ops/corpus-drift-runbook.md`

This is operator-facing documentation already existing in `docs/ops/` and referenced by the root README's ops section. Extending it is consistent with the doc-placement rule (§1). The CLAUDE.md rule permits `docs/` for "user-facing documentation referenced by the root README." Runbook extensions go in `docs/ops/`, not `.claude/`.

---

## Prior decisions and lessons

From `decision.md §3 Site` (verbatim): "The WAP gate is OUTSIDE the best-effort swallow's scope so its `raise RuntimeError(...)` propagates to the caller. Placing the gate INSIDE the try block (the pre-rect-F1 specification) would have the `except Exception as exc: logger.error(...)` at lines 970-976 catch the gate's own raise — a structurally non-functional gate."

From agent memory (2026-05-31, corpus-integrity-observability-e3): "Startup-set gauges live in `server/health.py`. New sentinel-bridged gauges MUST go in `server/metrics.py`." Not directly relevant for e1 (no new gauges), but confirms the e1 gate raises rather than emitting a gauge.

From `bulk_ingest.py` module docstring: "**Single-writer constraint:** the loop is sequential at the write boundary. No parallel `write_chunks` calls." Confirmed: `run_bulk_ingest` processes papers sequentially — `write_chunks` is called once per paper in a for loop, not via `asyncio` or `ThreadPoolExecutor`.

---

## Failure-mode stress test

### FM-1: Pre-m1 bug shape (`chunk_count = len(chunks)` reintroduced)

**Attack scenario:** A future developer reverts the m1 fix in `write_corpus_version_marker`, reintroducing `chunk_count=len(chunks)` (the per-batch count) instead of `tbl.count_rows()` (cumulative count). On a multi-paper run of 50 papers with 106 chunks each, the marker stores 106 but the table holds 5300.

**Gate arm:** COUNT-MISMATCH arm. `re_read_marker.chunk_count = 106`, `fresh_count = 5300`. Fires correctly.

### FM-2: JSON serialization wrong value (float truncation)

**Attack scenario:** A future change writes `chunk_count: 847.0` (float) to the JSON, and `from_dict` parses it as float rather than int, producing a `CorpusVersionInfo` with `chunk_count = 847.0`. Python `== 847` comparison returns `True` for int-vs-float, so the gate would NOT fire even though the type is wrong.

**Actual behavior:** `CorpusVersionInfo.from_dict` must coerce to `int`. If it does, no false-negative. If a DIFFERENT float-truncation scenario produces `847.9 → 847` (rounded down vs 848 actual rows), count-mismatch arm fires. This is FM-2's real risk: silent truncation. The `int(chunk_count)` cast at `write_corpus_version_marker:748` already guards this at write time — the JSON always stores an integer literal.

### FM-3: Atomic rename completes but file truncated

**Attack scenario:** `os.replace` succeeds but the tmp file was incomplete (kernel buffer not flushed, disk full mid-write). The JSON is truncated.

**Gate arm:** `read_corpus_version` raises `json.JSONDecodeError → ValueError`. The gate's `except ValueError → raise RuntimeError` (malformed-marker arm) catches this. Confirmed by `server/corpus.py:527-530`.

### FM-7: Marker chunk_count int overflow

**Attack scenario:** At 2^63 rows (academic concern), `int(chunk_count)` wraps to negative. JSON stores a negative value. `re_read_marker.chunk_count < 0` while `fresh_count > 0`.

**Gate arm:** COUNT-MISMATCH arm fires (different values). The error message makes the negative count visible.

### FM-10: Swallowed marker-write exception (stale prior marker)

**Attack scenario (production-common path):** Third `write_chunks` call on an existing dataset. `write_corpus_version_marker` raises `IOError` (e.g., disk full). The `except Exception` swallow at line 970-976 logs a warning and silently continues. The prior marker (from the second call) remains on disk with `chunk_count=2000`. Fresh `tbl.count_rows()=2954`.

**Gate arm:** COUNT-MISMATCH arm (`2000 ≠ 2954`). **Confirmed**: `read_corpus_version(target_path)` reads any file at the path — it is NOT scoped to files "just written." It reads whatever `corpus-version.json` exists at `target_path`. The stale prior marker is correctly read back and its `chunk_count` diverges from `fresh_count`. Gate fires on the count-mismatch arm, NOT the missing-marker arm. The error message in `decision.md §3` explicitly instructs operators to check the preceding swallow-warning log line to distinguish this case from a true arithmetic regression.

**Cold-clone sub-case (FM-10a):** First `write_chunks` call ever; `write_corpus_version_marker` raises. No prior marker exists. `read_corpus_version` returns `None`. Gate fires on MISSING-marker arm. Correct.

### FM-4: Caller arithmetic errors in `bulk_ingest.py`

**Spike's out-of-scope claim:** Verified. `bulk_ingest.py` does not pass `chunk_count` or `expected_total` arguments to `write_chunks` — the count is derived entirely inside `write_chunks` via `tbl.count_rows()`. The gate cannot catch arithmetic errors in the caller that are external to the count written in the marker. The gate only covers the marker-vs-table divergence at write time. Caller arithmetic that feeds into a DIFFERENT field (e.g. `rows_inserted` in `WriteStats`) is out of scope.

### FM-5: TOCTOU race

**Spike's out-of-scope claim:** Confirmed. The single-writer-per-dataset constraint (`bulk_ingest.py` docstring line 44-46: "No parallel `write_chunks` calls") means no concurrent writer can land rows between `tbl.count_rows()` inside the gate and the time the gate reads the marker. Under single-writer: no TOCTOU risk.

### FM-6: Schema-version drift (`dataset_version` mismatch)

**NEW failure mode the spike missed.** The WAP gate reads `re_read_marker.chunk_count` but NOT `re_read_marker.version`. The marker's `version` field stores `dataset_version` (the LanceDB dataset version integer). If `write_corpus_version_marker` were called with the wrong `version` argument (e.g., stale version from a prior call), the chunk count could still match, but the marker would point to the wrong LanceDB version — readers would pin to the wrong snapshot. **Gate arm:** None — the gate does NOT check `marker.version == dataset_version`. This is an out-of-scope correctness risk but the spike's test plan does not include a mutation for it. It does not violate the gate's stated acceptance criteria ("raises when `chunk_count` does not match") but is worth noting as a gap for a future follow-on.

### FM-11: Sibling marker writers

**Spike's out-of-scope claim:** Confirmed. `server/routes/notebooks._rewrite_corpus_version_marker` and `tools/notebook_reconcile_marker.py` write markers via separate code paths that do NOT call `ingest.store.write_chunks`. The WAP gate fires only inside `write_chunks`, so sibling writers are structurally out of scope for e1.

### FM-12 (NEW): `target_path` is a directory conflict at the marker location

**New failure mode not in the spike's FM-1..FM-11 matrix.** `read_corpus_version` uses `marker_path.is_file()` (line 523) — not `marker_path.exists()`. The code comment on that line (`# Closes M5 from the E04_S03 critique`) explicitly notes that `is_file()` avoids the `IsADirectoryError` that `exists()` would miss. If a directory named `corpus-version.json` exists at the marker path (a degenerate case, but possible if a failed atomic rename left a tmp directory), `is_file()` returns `False` and `read_corpus_version` returns `None`. Gate fires on the MISSING-marker arm, giving an actionable error. This edge case is handled correctly by the existing code without any additional gate logic.

### FM-13 (NEW): `re_embed.py` double `write_chunks` call per paper

**New failure mode the spike missed (partially).** `ingest/re_embed.py:528` calls `write_chunks(copy_chunks, copy_record, ...)` then `re_embed.py:558` calls `write_chunks(re_embed_chunks, re_embed_record, ...)` — TWO calls per paper, both against the same staging LanceDB path. The WAP gate fires inside EACH call. After the first call (copy path), the gate reads the marker and sees the copy-path chunk count matches `tbl.count_rows()`. After the second call (re-embed path), the gate reads the marker again and sees the re-embed-path count matches `tbl.count_rows()` at that point.

**Single-writer confirmation:** `re_embed.py` processes papers sequentially (no async fan-out confirmed by the code at lines 508-562 — no `asyncio.create_task`, no `ThreadPoolExecutor`). The two `write_chunks` calls per paper are sequential. No race condition. The gate fires twice and passes twice on the happy path. On failure (e.g., re-embed write crashes after copy succeeds), the gate fires on the second call and raises, leaving the staging dataset in a partially-written state — but this is expected behavior for fail-fast gating. The caller (`re_embed.py:558`) is wrapped in a try block that logs the failure and continues to the next paper.

**Impact on test plan:** Mutation B (missing marker on the SECOND call) is a realistic re_embed.py scenario. The positive-path test in `test_write_chunks_wap_gate.py` should include a two-call scenario to confirm the gate passes twice correctly.

### FM-14 (NEW): `dataset_version` in marker differs from `corpus_version` argument

**New failure mode.** `write_corpus_version_marker` is called with `version=dataset_version` where `dataset_version = int(getattr(tbl, "version", 0) or 0)` (store.py:874). If `tbl.version` returns a stale cached value (e.g., from a library bug), the marker stores the wrong version. The WAP gate checks `chunk_count` but NOT `marker.version == dataset_version`. This is a schema-version-integrity gap. The gate does NOT catch this failure mode. **Out-of-scope for e1** per acceptance criteria (which only requires `chunk_count` comparison), but worth documenting as a future follow-on.

---

## External sources

### LanceDB `merge_insert` and `count_rows()` semantics

LanceDB `>=0.6` (project pin in `pyproject.toml`: `"lancedb>=0.6"`). LanceDB uses Lance's columnar MVCC: each `merge_insert` completes atomically and increments the dataset version. `count_rows()` on an open `Table` handle reads fragment metadata from the committed tip of the dataset. There is no "session-visible-only" distinction inside a single process — `count_rows()` reflects all committed writes. Under the single-writer model (documented in `bulk_ingest.py` and `ingest/store.py:44-55`), the `count_rows()` in the WAP gate always reflects the table state after the preceding `merge_insert` + `_create_indices` completed.

**No external doc verification required** — the codebase's own comments are authoritative on the single-writer contract, and the gate's correctness argument does not depend on multi-reader isolation semantics.

### Python `pathlib.Path.is_file()` on macOS APFS

`is_file()` performs a `stat()` syscall. On APFS (macOS), stat is subject to VFS metadata consistency (APFS is fully journaled with ACID semantics). A file written via `os.replace()` (atomic rename via `renameat2`/`rename(2)`) is visible to a subsequent `is_file()` in the same process on the same filesystem without additional barriers. No hazard for the gate.

### `pytest monkeypatch.setattr` module-level function intercept

`monkeypatch.setattr(module, "fn_name", replacement)` replaces the attribute in the module's `__dict__`. Since Python resolves bare name calls (`write_corpus_version_marker(...)` inside `write_chunks`) via the enclosing module's globals dict at call time (NOT at definition time), this monkeypatch correctly intercepts the call. Confirmed by reading that `write_corpus_version_marker` is called as a bare name in `ingest/store.py:946` — not via a local `_marker_fn = write_corpus_version_marker` alias or a closure. The test plan's pattern (`monkeypatch.setattr(store_mod, "write_corpus_version_marker", ...)`) is correct.

---

## Cross-check: threat model and logging redaction

The WAP gate's `RuntimeError` messages include `target_path` (an absolute filesystem path like `/Users/chris.dare/Personal/SourceCode/arXMCP/var/arxmcp/index/lancedb`) and `fresh_count` / `re_read_marker.chunk_count` (integer counts).

**Threat model analysis:** `08-security-observability-ops.md` §Logging states: "Sensitive fields (full query text, chunk bodies) are logged at DEBUG only, never at INFO or above." The WAP gate's `RuntimeError` is raised — NOT logged by `ingest/store.py`. The caller (`bulk_ingest.py::run_bulk_ingest`) catches the RuntimeError and logs it. The `RedactionFilter` in `server/observability/log_filter.py` redacts `REDACTED_FIELDS = {"query", "body_canonical", "body_raw_latex", "mathml"}` — but `target_path` and `chunk_count` are NOT in `REDACTED_FIELDS`. 

**Path exposure in log output:** The path string `target_path` in the RuntimeError message WILL appear in the ingest log if the caller logs the exception. For a single-user localhost system, this is acceptable per the threat model (§1: "This is a single-developer, localhost-only system"). The `ingest_tracker.py` path-redaction logic applies only to subprocess stderr, not to ingest log records. This is a **deliberate, documented scope limitation** — not a regression.

**The gate does NOT introduce a new logging-redaction regression** because: (a) path values in error messages have always been in ingest logs (e.g., `store.py:972-976` already logs `target_path`), and (b) `RedactionFilter` is installed on the MCP server's root logger (`server/main.py:888-900`), NOT on the ingest process's logger (which is a separate process).

---

## Cross-check: cache discipline (`07-multi-agent-caching.md`)

From `07-multi-agent-caching.md` (verbatim): "Tier 1 — Exact-query (SQLite LRU, 10K entries): key includes `corpus_version: int` as a mandatory component; stale entries from old corpus versions are unreachable by construction after a restart with a new `corpus-version.json`."

The WAP gate runs at WRITE time inside `ingest/store.py::write_chunks`, which is an ingest-process concern. The server-side caches read `corpus-version.json` at startup (read time). The gate's `raise RuntimeError(...)` prevents the ingest from completing normally — it does NOT write a new `corpus-version.json` with a wrong `chunk_count` that the server would later consume. Therefore: **the gate does NOT invalidate cache stability**. On the contrary, it prevents a corrupt marker from ever reaching the server's startup read path. Cache discipline is unaffected.

The `created_at` field in `corpus-version.json` is explicitly declared "outside BP1 scope" in `write_corpus_version_marker`'s docstring. The WAP gate does not modify this field or introduce any non-determinism into the marker content.

---

## Recommendation

**Ship the gate exactly as specified in `decision.md §3`.** The three-arm gate (ValueError → RuntimeError, None → RuntimeError, count-mismatch → RuntimeError) placed OUTSIDE the existing `try/except` block is the correct implementation. The monkeypatch test pattern is valid. Import of `read_corpus_version` from `server.corpus` is consistent with established precedent.

**One adjustment to the positive-path test:** add a two-`write_chunks`-call scenario (reusing `seed_corpus_multi_paper`) to confirm the gate passes twice in sequence, matching the `re_embed.py` production pattern. This does not change the acceptance criteria; it is a coverage addition.

**Do NOT add a `marker.version == dataset_version` check** (FM-14) in this milestone — it is out of scope and would require threading `dataset_version` through to the gate differently. File as a follow-on.

---

## Open questions

1. **Positive-path test scope for re_embed.py pattern:** The test plan specifies "multi-call fixture from `tests/_corpus_helpers.py::seed_corpus_multi_paper`" but does not explicitly say whether the positive test exercises TWO sequential `write_chunks` calls on the same path (as in `re_embed.py`) or one call per paper. The implementer should confirm the positive test calls `write_chunks` at least twice on the same LanceDB path to cover the stale-marker happy path (where the second call reads the marker written by the first call and finds it correct).

2. **`docs/ops/corpus-drift-runbook.md` extension anchor:** The spike requires the runbook extension in the same commit. The existing runbook has no WAP-gate section. The implementer must pick an appropriate H2/H3 placement (recommend after "## Likely causes" as a new subsection "### S5 — WAP gate RuntimeError at ingest time"). Confirm the anchor is not referenced from external sources that would break.

No other open questions — the implementation can proceed on the above recommendation.

---

## External writes the implementation will require

None — this milestone is purely local. No git push, PR creation, ticket, infra mutation, or third-party API call is required. The implementer commits to `main` directly per the project's single-user workflow (CLAUDE.md §4.1).
