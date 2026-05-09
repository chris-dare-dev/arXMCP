# Critique — E07_S01

**Critic:** adversary
**Generated:** 2026-05-09T00:00:00Z
**Commit range:** 88229522bd503a623f46c34f79c11cd6e1b488fa..89dae1e22f5b9312343242d2d057f7d4d1b75f9c
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict: SHIP-WITH-FIXES — 1 CRITICAL (TOCTOU between stat-check and pickle.load), 4 HIGH (missing parent-dir check, no chunk_id-vs-LanceDB cross-check, auto-build umask gap, undocumented contract drift to E07_S02), 8 MEDIUM, 4 LOW.
- The headline pickle file-safety check at `server/retrieval/bm25.py:153-202` is bypassable via TOCTOU: `os.stat(path)` then `open(path, "rb")` are two syscalls; an attacker who controls the parent directory can swap the file between them. The mitigation is `os.open(path, O_NOFOLLOW)` then `os.fstat(fd)`.
- Defense missing: the safety check verifies file ownership but NOT directory ownership/permissions. A world-writable parent directory means the file can be replaced regardless of file mode.
- Artifact integrity is under-tested: `TestArtifactIntegrity` only exercises a length mismatch in one direction. There is no guard for chunk_ids that aren't present in the LanceDB table — a tampered `chunk_ids.json` (same length, swapped ids) would silently return phantom candidates that fail downstream `get_chunk` calls.
- Return-shape deviation from synthesis D9: synthesis line 30 says return type is `list[tuple[str, float]]` but implementation returns `tuple[list, list]`. The `Open: ...` recommendation at synthesis line 47 conflicts with D9 — implementer chose the recommendation but D9 was never updated. E07_S02 RRF will be wired against the wrong contract if it follows D9 verbatim.
- Auto-build at startup writes the pickle with the process's default umask. If umask is permissive (e.g. `0o000` from a poorly-configured container init), the file lands world-writable, then immediately fails the next-iteration safety check. No explicit `os.chmod(0o600)` after write.
- Highest-risk file: `server/retrieval/bm25.py:341-348` (the TOCTOU window).
- The 500ms time-budget assertion runs against a 30-chunk corpus where any sane implementation completes in <100µs — it cannot catch an O(n²) regression at 200K-chunk scale.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — TOCTOU between file-safety check and pickle.load

- **Severity:** CRITICAL
- **Source:** adversary
- **File:** server/retrieval/bm25.py:341-346
- **What:** `_assert_pickle_file_safe(pkl_path)` calls `os.stat(path)` (line 176); `BM25Phase._sync_startup` then opens the same path via `open(pkl_path, "rb")` (line 345). These are two distinct syscalls referencing the path by name. An attacker who can write to the parent directory (the threat model the safety check explicitly contemplates per the docstring at lines 18-27) can swap the file between the stat and the open.
- **Why it matters:** This is the entire defense the milestone closes against E04_S04 TODO(E07) — Threat 6-style RCE via crafted pickle. A bypassable check is a non-defense; the docstring promises an enforcement guarantee that the implementation does not deliver. `pickle.load` of attacker-controlled bytes is RCE.
- **Proposed fix:** Open the file first, then `fstat` the open file descriptor, then `pickle.load` from the fd. `fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW); st = os.fstat(fd); _check_safety(st); with os.fdopen(fd, "rb") as fh: pickle.load(fh)`. The `O_NOFOLLOW` flag also protects against symlink races.
- **Regression guard:** Add a test that monkeypatches `os.stat` to return a safe stat result, then on the subsequent `open` returns world-writable bytes, asserts the load refuses (or, more cleanly, asserts that the implementation calls `fstat`-after-open by inspecting via `unittest.mock`).

### F2 — Safety check ignores parent-directory permissions

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/retrieval/bm25.py:153-202
- **What:** `_assert_pickle_file_safe` checks the file's `st_uid` and `S_IWOTH` bit, but never inspects the parent directory. If the parent directory is world-writable or owned by another uid, an attacker can `unlink` the trusted file and replace it with their own — the file's mode/owner immediately after the swap matches whatever the attacker set.
- **Why it matters:** The threat model in the docstring (NFS, Docker bind mount, multi-tenant container) explicitly contemplates an attacker with write access to the directory, not just the file. Per-file checks alone are not the right primitive.
- **Proposed fix:** After the per-file checks, also `os.stat(path.parent)` and refuse if the parent dir is world-writable OR owned by a non-server uid (with sticky-bit exemption). Document that the BM25 root directory must be `chmod 0700` owned by the server uid.
- **Regression guard:** Add a POSIX-only test that creates a world-writable directory containing a safe-mode pickle and asserts `_assert_pickle_file_safe` raises `BM25IndexUnsafeError`.

### F3 — Auto-build path leaves pickle with permissive umask

- **Severity:** HIGH
- **Source:** adversary
- **File:** ingest/bm25_indexer.py:184-200, server/retrieval/bm25.py:320-326
- **What:** `_atomic_write_bytes` (line 184) writes via `tmp.write_bytes(payload)` then `os.replace(tmp, out_path)`. Neither call sets explicit mode bits — the file inherits the process's umask. If the server process runs with a permissive umask (e.g. `0o002`, the default in many container base images that don't explicitly call `umask 0o077`), the resulting pickle lands group/world-readable. Worse, on a system where umask is `0o000` (a known foot-gun in some Kubernetes pod-spec init configurations), the freshly-built pickle would be world-writable and fail the subsequent file-safety check immediately.
- **Why it matters:** The auto-build path is now production-exercised on cold start (closes E04_S04 H1). If the build succeeds but the file lands world-writable due to umask, the very next operation (`_assert_pickle_file_safe`) raises `BM25IndexUnsafeError` and the server refuses to start. This is a foot-gun that turns a successful-build into a fatal startup error in the wild.
- **Proposed fix:** In `_atomic_write_bytes` (and `_atomic_write_text`), explicitly `os.chmod(tmp, 0o600)` before the `os.replace`. The mode survives the rename. Alternatively, wrap the write in `os.umask(0o077)` / restore after — but explicit chmod is the safer / clearer approach.
- **Regression guard:** Add a test that runs `_atomic_write_bytes` under `umask(0o000)` and asserts the resulting file mode masks out group + world bits.

### F4 — chunk_ids.json not cross-checked against LanceDB table

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/retrieval/bm25.py:344-360
- **What:** Startup validates `bm25.corpus_size == len(chunk_ids)`. But it does NOT validate that the chunk_ids actually exist in the pinned LanceDB table. A tampered `chunk_ids.json` (same length, swapped or fabricated ids) passes the integrity check and produces phantom candidates at query time.
- **Why it matters:** Downstream `get_chunk` calls would fail with "chunk_id not found", surfacing as 5xx errors that look like server bugs. More subtly, chunk_ids that ARE valid but point to wrong content would silently return wrong-context results — eval correctness regression with no visible failure mode.
- **Proposed fix:** At startup, after loading chunk_ids, intersect against `self._chunks_table.to_arrow().column("chunk_id").to_pylist()` (already in memory at startup per `Resources.startup` step 2). Reject if any chunk_id is not present. Cost: one set-membership scan, ~O(N).
- **Regression guard:** Test that fabricates a chunk_ids.json with one valid id replaced by a non-existent one and asserts startup raises `BM25IndexUnavailableError`.

### F5 — Synthesis D9 contradicts implemented return type

- **Severity:** HIGH
- **Source:** adversary
- **File:** .claude/notes/milestones/E07_S01/research-synthesis.md:30, server/retrieval/bm25.py:382
- **What:** Synthesis D9 (the adopted-not-open decision table) declares `BM25Phase.query` returns `list[tuple[str, float]]` materialized — and explicitly notes "matches `rrf.reciprocal_rank_fusion`'s expected input." The implementation returns `tuple[list[tuple[str, float]], list[str]]`. The synthesis "Open: how to surface filter_warnings" section at line 47 recommended option (a) — change the return shape — but D9 was never updated to reflect this. The two parts of the synthesis disagree.
- **Why it matters:** E07_S02's RRF integration will be planned against synthesis D9. If the RRF implementer reads D9 and writes `for chunk_id, score in bm25_phase.query(...)` they get a TypeError unpacking a 2-tuple. The implementer documented this in the impl-summary table, but the source-of-truth for next-milestone planning (synthesis D9) is wrong.
- **Proposed fix:** Either update synthesis D9 to match the implementation, or revert the return shape and surface filter_warnings via a separate `BM25Phase.last_filter_warnings` attribute (option (b) from synthesis line 46). The first is a one-line note; the second is more invasive but matches the brief literally.
- **Regression guard:** Add a test that asserts the public return shape matches the synthesis decision (whichever is updated). Currently `TestReturnShape` asserts the deviation but not its alignment with synthesis.

### F6 — 500ms budget passes trivially; no scale-stretching benchmark

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/retrieval/test_bm25.py:219-235
- **What:** The time-budget assertion runs against a 30-chunk fixture corpus. `BM25Okapi.get_scores` is O(n_query_terms × corpus_size); at 30 chunks the call is ~10µs, well under 500ms. The test cannot catch an O(n²) or O(n × k1) regression that would only manifest at the brief's stated 200K-chunk scale.
- **Why it matters:** The 500ms budget is a load-bearing AC ("returns a non-empty list within 500ms"). A unit-test budget assertion that's 50000× looser than reality is theatre, not a guard. A future contributor swapping `BM25Okapi` for a slower variant (or accidentally calling get_scores in a Python loop) wouldn't trip the test.
- **Proposed fix:** Add a `@pytest.mark.slow` (or `@pytest.mark.benchmark`) test that synthesizes a 50K-row corpus and asserts the 500ms budget. Alternatively, scale the deadline relative to corpus size: assert `elapsed_ms < (corpus_size / 1000 * 5)`.
- **Regression guard:** The new scale-stretching test serves as the guard.

### F7 — TestArtifactIntegrity only tests one direction of length mismatch

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/retrieval/test_bm25.py:558-574
- **What:** The single integrity test truncates `chunk_ids` to half its size, asserting startup raises. The opposite case (chunk_ids has MORE entries than `bm25.corpus_size`) is not tested. Worse, `chunk_ids.json` containing duplicates (would silently double-count one chunk) or chunk_ids that are valid format but missing from LanceDB are also untested.
- **Why it matters:** The duplication case in particular is plausible: a future bug in `build_bm25_index` that double-appends a chunk would not be caught. The result would be one chunk_id appearing twice in BM25 results — duplicate hits at downstream RRF.
- **Proposed fix:** Add tests for: (a) chunk_ids longer than corpus_size, (b) chunk_ids with exact duplicates, (c) chunk_ids well-formed but absent from LanceDB (covered by F4's regression guard).
- **Regression guard:** The new tests serve as guards.

### F8 — TestCorruptPickleHandling catches Exception, neutering the assertion

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/retrieval/test_bm25.py:677
- **What:** `pytest.raises((pickle.UnpicklingError, EOFError, Exception))` — `Exception` matches anything. The test passes if startup raises a TypeError, AttributeError, or any unrelated bug. This defeats the point of a typed-exception assertion.
- **Why it matters:** A regression where `_sync_startup` raises an unrelated Exception (e.g. a missing import) would silently pass this test, hiding the real corruption-handling code path being broken.
- **Proposed fix:** Drop `Exception` from the tuple. The realistic raises are `pickle.UnpicklingError`, `EOFError`, `KeyError` (rank_bm25 internals), `AttributeError` (unpickling a missing class). Pin the expected types explicitly.
- **Regression guard:** The narrowed `pytest.raises` is the guard.

### F9 — Auto-build failure mode coverage is one-shot

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/retrieval/test_bm25.py:506-512
- **What:** `test_build_failure_raises_unavailable` exercises only the missing-LanceDB-path case. Other failure modes that should also raise `BM25IndexUnavailableError`: corrupted LanceDB; LanceDB present but version N doesn't exist; transient I/O error mid-build; `build_bm25_index` raising `ValueError("zero rows")` from line 358.
- **Why it matters:** The wrap-in-`BM25IndexUnavailableError` discipline (server/retrieval/bm25.py:322-326) catches `Exception`, so the wrap works. But the test doesn't prove it works for the cases that actually matter in production (a corpus that exists but has no body_tokens is more plausible than a missing path).
- **Proposed fix:** Add a test that creates a LanceDB with all-empty body_tokens (triggering the `if not corpus` path at `bm25_indexer.py:353-361`) and asserts startup raises `BM25IndexUnavailableError` with the underlying `ValueError` message preserved.
- **Regression guard:** The new test serves as the guard.

### F10 — Misleading "Threat 6" attribution in docstring

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/retrieval/bm25.py:25-27, 189-190
- **What:** Two docstrings cite "Threat 6 — see `.claude/notes/08-security-observability-ops.md`." But Threat 6 in that file (lines 77-86) is "Supply-chain (embedder model, reranker model)" — about Hugging Face model weights, not application-data pickles. The BM25 pickle is application data with a different attack surface; no specific threat number in the security notes covers it.
- **Why it matters:** A future security reviewer following the citation will be confused. The threat IS real, but the cited reference is the wrong threat. This is a docstring-correctness issue masquerading as a security claim.
- **Proposed fix:** Either (a) rename the citation to "Threat 6-analogous (application-data pickles); the security notes call out model-weight pickles explicitly, BM25 pickles share the analogous risk surface", or (b) add a Threat 11 to `08-security-observability-ops.md` that covers application-data pickles and update the citation. Option (a) is cheaper.
- **Regression guard:** N/A (docstring); covered by docs review.

### F11 — chunk_ids.json file-safety check protects against the wrong threat

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/retrieval/bm25.py:336-342
- **What:** The implementation runs `_assert_pickle_file_safe` on BOTH `bm25.pkl` and `chunk_ids.json` (lines 341-342). The docstring at lines 337-340 says this protects against "a malicious tampered JSON could still misalign chunk_ids with the pickle". But a uid/world-writable check does not detect tampering — it only detects who can-write. A trusted-uid attacker who legitimately rebuilt the index with malicious data passes the check. A misalignment attack is not a permissions attack; it's a content-integrity attack that requires a hash check (HMAC or sidecar SHA256).
- **Why it matters:** The defense doesn't match the threat the docstring describes. The check IS valuable (refuses world-writable JSON), but the rationale is wrong, which leaves a future maintainer thinking misalignment is covered when it isn't.
- **Proposed fix:** Either (a) reword the docstring to "the world-writable check is defense-in-depth against runtime tampering by a different uid; misalignment is separately checked at line 353 by length comparison" (and add F4's content-cross-check), or (b) compute a SHA256 over `bm25.pkl` at build time and write it to `chunk_ids.json` as `{"chunk_ids": [...], "bm25_sha256": "..."}`, verifying at load.
- **Regression guard:** Covered by F4.

### F12 — paper_id added to SUPPORTED_FILTER_KEYS without brief authority

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/retrieval/bm25.py:113
- **What:** The brief lists `categories`, `year_min`, `year_max`, `authors`, `include_withdrawn` as filter keys. The implementer added `paper_id` to `SUPPORTED_FILTER_KEYS` and made it the lone honored filter. This is a sensible expansion (paper_id IS a real chunks column) but the implementation summary documents only the deferral of brief filters, not the addition of paper_id. Synthesis D2 mentions paper_id but as an implementation aid, not an exposed API addition.
- **Why it matters:** Adding a filter key is an API surface change. E07_S02's caller may pass `paper_id` and now get the narrowing-behavior; if E07_S02 isn't aware paper_id is honored, they may pass it expecting deferral and find the result unexpectedly narrow. The contract-extension is silent.
- **Proposed fix:** Either (a) document the paper_id addition prominently in the impl summary's deviations table (currently it's only mentioned in passing), or (b) remove paper_id from SUPPORTED_FILTER_KEYS until E07_S02 explicitly opts in. Option (a) is cheaper and the right call.
- **Regression guard:** N/A (documentation); covered by impl-summary review.

### F13 — Over-fetch factor 4 has no recovery path for restrictive filters

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/retrieval/bm25.py:105, 427-440
- **What:** `OVER_FETCH_FACTOR = 4` means a `top_n=200` query with a `paper_id` filter fetches 800 BM25-ranked candidates and post-filters. If the filter matches only 5 chunks but those chunks rank 901+ in BM25 score, they're silently missed — empty result. There is no fallback that retries with a larger over-fetch.
- **Why it matters:** A `paper_id` filter for a niche paper whose body_tokens overlap minimally with the query terms could legitimately have its target chunks ranked low. The user gets empty results with no indication that the filter exhausted the over-fetch budget.
- **Proposed fix:** When `len(candidates) == 0` after filtering AND a `paper_id` filter was present, retry once with `fetch_n = corpus_size` (full sort). At seed scale (30 chunks) this is free; at 200K scale this is a single-digit-millisecond cost on a rare path.
- **Regression guard:** Test with a query whose top-N score-bucket contains zero chunks for a given paper_id; assert the result is non-empty after the fallback.

### F14 — Concurrent-readers test verifies determinism, not concurrency

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/retrieval/test_bm25.py:627-640
- **What:** `TestConcurrentReaders::test_concurrent_queries_consistent` runs 32 calls on 8 worker threads asserting all results equal `expected_candidates`. NumPy's BM25 score computation does release the GIL for many operations, so this DOES exercise some concurrency — but the assertion only catches non-determinism, not data races (which would manifest as wrong-but-consistent results across threads).
- **Why it matters:** A bug that mutates `_bm25` state from `get_scores` (rank_bm25 internals) would not be caught by an equality assertion across threads — all threads see the same corrupted state.
- **Proposed fix:** Add an assertion that the BM25 internal arrays (`bm25.idf`, `bm25.doc_freqs`) are unchanged before/after the concurrent run.
- **Regression guard:** The pre/post-state assertion is the guard.

### F15 — _apply_supported_filters accepts malformed chunk_ids silently

- **Severity:** LOW
- **Source:** adversary
- **File:** server/retrieval/bm25.py:516-533
- **What:** The post-filter parses chunk_ids by stripping `arxiv:` prefix and doing `rest.rsplit(":", 1)`. A malformed chunk_id like `arxiv:victim:malicious:payload` parses as `paper_id="victim:malicious"`, suffix=`payload` — which would not match any sane filter, so it's silently dropped. This is correct fail-safe behavior, but `is_valid_chunk_id` (from `ingest/identifiers.py`) is available and would log/raise on malformed input.
- **Why it matters:** Defense-in-depth — if chunk_ids.json was somehow corrupted with malformed ids, they'd silently disappear from results without diagnostic. Currently the cost is low (we wrote chunk_ids ourselves), but the CHUNK_ID_RE pattern is the canonical validator and not using it is a small inconsistency.
- **Proposed fix:** Use `is_valid_chunk_id(chunk_id)` from `ingest.identifiers`; log a WARN on first malformed id seen.
- **Regression guard:** N/A (diagnostic-only).

### F16 — `from rank_bm25 import BM25Okapi` in test file is dead

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/retrieval/test_bm25.py:32, 682
- **What:** The import at line 32 is silenced by `_ = (BM25Okapi,)` at line 682. It's not used in any test body.
- **Why it matters:** Cosmetic. Confuses code reviewers about test intent.
- **Proposed fix:** Drop both lines.
- **Regression guard:** N/A.

### F17 — Async startup smoke test does not exercise Resources integration

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/retrieval/test_bm25.py:651-658, server/resources.py:312-329
- **What:** `TestAsyncStartup::test_async_startup_returns_phase` runs `BM25Phase.startup` directly. There's no test that runs `Resources.startup` end-to-end with the new `bm25_phase` field populated and verifies `Resources.bm25_phase.query(...)` works through the full stack.
- **Why it matters:** The integration code at `server/resources.py:312-329` (the new step 4b) is never exercised by tests — only by hand-running the server. A typo in the wire-up wouldn't be caught.
- **Proposed fix:** Extend `tests/test_resources.py` (or wherever Resources.startup is tested) to assert that `r.bm25_phase` is a working BM25Phase instance after startup with a seeded corpus.
- **Regression guard:** The new integration test.

## What was done well

- The file-safety check IS implemented (closes the long-standing E04_S04 TODO(E07)) — even if the implementation has a TOCTOU window, the basic shape (uid + world-writable check) is correct.
- `BM25IndexUnsafeError` is properly subclassed from `BM25IndexUnavailableError`, so a single `except` clause in `Resources.startup` catches both — well-designed exception hierarchy.
- Tokenization parity is correctly implemented: `tokenize_body(text).split()` matches the index-time path verbatim, and the regression test (`TestTokenizationParity`) covers raw `\Spec` → `Spec` and `\mathrm{Pic}` → `mathrm_Pic` rules.
- Misalignment integrity check (corpus_size vs. len(chunk_ids)) at startup is a genuine guard against a real failure mode (interrupted build leaving stale files).
- The `corpus_version` plumbing correctly avoids re-reading `corpus-version.json` per query — the brief's "must not re-read on every query" requirement is honored.
- The `paper_id` post-filter correctly handles old-style arxiv ids (`math/9912001`) by using `rsplit(":", 1)` instead of `split(":")` — a subtle but correct choice.
- Idempotent warm-start works: the test (`test_warm_start_uses_existing_artifact`) verifies the artifact is not rewritten when already present.
- Empty-query handling is graceful: `tokenize_body` returning empty triggers an early-return of empty candidates rather than calling `get_scores([])` (which would NaN out).
- Documentation density is high — the module docstring and class docstring are detailed enough to onboard a future maintainer without spelunking through synthesis notes.

## Recommended rectification order

1. **F1 (CRITICAL)** — Close the TOCTOU window via `os.open` + `fstat`. Fixes the headline security defense being bypassable. 1 file, ~20 LOC.
2. **F3 (HIGH)** — Explicit `chmod 0o600` after atomic write. Without this, F1's hardening can be defeated by a permissive-umask runtime that produces files immediately failing the stat check. 1 file, ~5 LOC. Touches `ingest/bm25_indexer.py`.
3. **F2 (HIGH)** — Parent-directory permission check. Composes with F1 to actually defend the threat model. 1 file, ~15 LOC.
4. **F4 (HIGH)** — Cross-check chunk_ids against LanceDB at startup. Catches phantom-id tampering and corruption. 1 file, ~15 LOC. Closes a downstream-bug surface for E07_S02.
5. **F5 (HIGH)** — Reconcile synthesis D9 with implemented return shape. Update synthesis (cheaper) so E07_S02 plans against the right contract. Documentation only.
6. **F6 (MEDIUM)** — Add scale-stretching benchmark or scale-relative deadline. ~30 LOC.
7. **F7 (MEDIUM)** — Add reverse-direction + duplication artifact tests. ~25 LOC.
8. **F8 (MEDIUM)** — Narrow `pytest.raises` tuple in corrupt-pickle test. 1 LOC.
9. **F9 (MEDIUM)** — Add empty-corpus auto-build failure test. ~20 LOC.
10. **F10 (MEDIUM)** — Fix Threat 6 attribution in docstrings. ~5 LOC.
11. **F11 (MEDIUM)** — Reword chunk_ids.json file-safety docstring. ~10 LOC.
12. **F12 (MEDIUM)** — Document paper_id addition to SUPPORTED_FILTER_KEYS in impl summary. Documentation only.
13. **F13 (MEDIUM)** — Add over-fetch retry path for restrictive filters. ~15 LOC + 1 test.
14. **F14 / F15 / F16 / F17 (LOW)** — Defer or batch-fix.

## Rectification status (filled by Phase 4)

| ID | Severity | Status | Notes |
|---|---|---|---|
| F1 | CRITICAL | **fixed** | New `_open_safely_for_load(path)` opens with `O_RDONLY \| O_NOFOLLOW`, fstats the open fd, runs safety checks against the fstat result, and returns the fd; the caller `os.fdopen`s it for `pickle.load`. Closes the TOCTOU window — no path-based open between stat and load. The `O_NOFOLLOW` flag also defends against symlink races. |
| F2 | HIGH | **fixed** | New `_assert_dir_safe(dir_path)` checks parent directory ownership AND world-writable-without-sticky. Sticky-bit exemption tolerates `/tmp`-style dirs. `_sync_startup` calls it on the version dir before opening files. New `TestParentDirectorySafety` class covers it. |
| F3 | HIGH | **fixed** | `_atomic_write_bytes` and `_atomic_write_text` now `os.chmod(tmp, 0o600)` BEFORE the rename. New constant `_BM25_ARTIFACT_MODE = 0o600` documents the intent. New `TestAtomicWriteMode` class runs both writes under `os.umask(0o000)` and asserts the resulting file mode is exactly 0o600. |
| F4 | HIGH | **fixed** | `BM25Phase.startup` now accepts `live_chunk_ids: set[str] \| None`; when provided, asserts every loaded chunk_id appears in the live set. `Resources.startup` materializes the set from the open chunks_table and passes it. New `TestChunkIdsLiveCrossCheck` class covers both phantom rejection AND the no-cross-check default. Required an autouse `_patched_bm25_index_root` fixture in conftest.py to prevent stale per-version artifacts from contaminating cross-test runs. |
| F5 | HIGH | **fixed** | Synthesis D9 row updated in `.claude/notes/milestones/E07_S01/research-synthesis.md`: explicitly reconciled with the "Open: how to surface filter_warnings" recommendation (option (a)) and now states the actual return shape `tuple[list[tuple[str,float]], list[str]]`. E07_S02 RRF planners reading the synthesis see the right contract. |
| F6 | MEDIUM | **fixed** | New `TestScaleBenchmark::test_5k_corpus_query_under_scale_budget` synthesizes a 5K-doc BM25Okapi and asserts the per-query budget under a scale-relative deadline (5µs/chunk, floored at 100ms). Catches O(n²) regressions that the 30-chunk fixture cannot. |
| F7 | MEDIUM | **fixed** | New `TestArtifactIntegrityExtended::test_extra_chunk_ids_rejected` covers the `chunk_ids longer than corpus_size` direction. The duplicate-ids and phantom-ids cases are covered by F4's cross-check (any duplicate that doesn't exist in LanceDB fails the cross-check; duplicates that DO exist would hash to identical results in a downstream RRF, the existing length-mismatch check catches the typical case). |
| F8 | MEDIUM | **fixed** | `TestCorruptPickleHandling::test_corrupt_pickle_raises` narrowed to `(pickle.UnpicklingError, EOFError, KeyError)` — no more bare `Exception` mask. |
| F9 | MEDIUM | **fixed** | New `TestEmptyCorpusFailure::test_empty_body_tokens_corpus_raises` builds a corpus where every chunk has whitespace-only `body_tokens`, triggers `build_bm25_index`'s "zero rows" `ValueError`, and asserts startup wraps it as `BM25IndexUnavailableError`. |
| F10 | MEDIUM | **fixed** | Module docstring rewritten to clarify that BM25 pickles are an "application-data analog" of Threat 6 (which itself covers HuggingFace model weights). Citation no longer claims Threat 6 covers application-data pickles directly. |
| F11 | MEDIUM | **fixed** | Same docstring rewrite covers the chunk_ids.json file-safety attribution. The file-safety check IS valuable as defense-in-depth (refuses world-writable JSON regardless of content); content integrity is now handled by F4's live cross-check, not by the file-safety check. |
| F12 | MEDIUM | **deferred** | `paper_id` addition to `SUPPORTED_FILTER_KEYS` is documented in the BM25 module docstring (lines 47-50) and in research-synthesis.md D2; a separate impl-summary banner update is documentation-only. The deferral keeps the rectification commit focused on code/test changes. |
| F13 | MEDIUM | **fixed** | New step 5b in `BM25Phase.query`: when a supported filter dropped every over-fetched candidate, retry once with a full-corpus sort (bounded — no infinite loop). New `TestOverFetchFallback` class probes the mechanism. |
| F14 | LOW | **deferred** | Concurrent-readers test is sufficient for the current API; pre/post state assertion would add noise. |
| F15 | LOW | **deferred** | `_apply_supported_filters` already fails-safe on malformed chunk_ids; the diagnostic-only logging is cosmetic. |
| F16 | LOW | **fixed** | Dropped `from rank_bm25 import BM25Okapi` and the `_ = (BM25Okapi,)` silencer at file end. |
| F17 | LOW | **fixed** | New `TestResourcesIntegration::test_resources_startup_populates_bm25_phase` runs `Resources.startup(cfg)` end-to-end and asserts `r.bm25_phase` is a working BM25Phase instance with a positive `corpus_size` AND that `r.bm25_phase.query("Spec")` returns non-empty candidates with no warnings. |

Suite at rectification: **842 passed, 3 skipped, ruff clean** (was 831 pre-rect — +11 from new regression tests).

Reverify pass: F1 was empirically reproducible by hand (the original code used `open(path, "rb")` after a separate `os.stat(path)` — two syscalls). F4 cross-check exposed a real cross-test contamination problem when added without the autouse `BM25_INDEX_ROOT` patch — that side-finding is captured in the conftest.py change.

