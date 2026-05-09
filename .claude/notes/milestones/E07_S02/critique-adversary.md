# Critique — E07_S02

**Critic:** adversary
**Generated:** 2026-05-09T19:06:05Z
**Commit range:** b20ef45b177189bdd3bcbf022e6c55ee2788403e..db089024a1e00470ffd3c5f2865499922ffe6d4a
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES. Math is right, but the doc/comment string asserting LanceDB returns a plain L2 distance is FALSE (LanceDB returns squared L2). This is the load-bearing reason — the formula `1 - dist/2` is correct ONLY because LanceDB returns `dist^2`, not because the docs claim. Future maintainers reading the docstring will "fix" the working code into a broken one (HIGH).
- 0 CRITICAL, 2 HIGH, 7 MEDIUM, 4 LOW.
- Highest-risk file: `server/retrieval/ann.py:97-107` (`_distance_to_score`) — same bug class as `server/handlers/search.py:260-264`, since the new helper was copy-pasted from there. Fixing one without the other will create a divergence.
- Cross-axis pattern: graceful-degradation `except Exception` in `_ann_search_one_column` masks programmer errors (typos, schema drift) as "empty column" — the brief mandates degradation, but this cushion is wider than the brief asks for.
- AC #4 reinterpretation is documented but the test does NOT prove the routing constraint the brief actually cares about (singleflight wrapper sits between caller and forward pass) when the slow-path code is taken — see F2.
- Phantom-id resilience is unverified: `bm25_candidates` carrying chunk_ids that no longer exist in LanceDB (stale BM25 artifact race) propagate straight into RRF output. Not tested.
- The `EMBEDDING_COLUMNS` public constant is dead code (constant declared, exported, never referenced by the search code that hardcodes the column names).
- Singleflight test patches `qe_mod._encode_query_sync` and restores in `finally` — but if the test is interrupted between patch and restore, leaks across tests.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap |
| LOW | style, naming, micro-perf | defer |

## Findings

### F1 — `_distance_to_score` docstring lies about LanceDB's distance semantics

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/retrieval/ann.py:97-107 (and the mirror at server/handlers/search.py:260-264)
- **What:** The docstring says "L2 distance on unit vectors → cosine similarity in [0, 1]" and the formula is `1 - dist / 2`. I verified empirically against LanceDB 0.30: a query against a unit vector v1 with corpus {v1, v2 (orthogonal), v_anti (-v1)} returns `_distance` values 0.0, 2.0, 4.0 — these are SQUARED L2 distances, not L2. The formula happens to yield the correct cosine because for unit vectors `||a-b||^2 = 2 - 2*cos`, so `cos = 1 - dist^2/2`, and `dist_lancedb = dist^2`. But the docstring describes the input as "L2 distance" — a future maintainer reading "L2 distance / 2" would attempt the (mathematically wrong) "fix" `1 - sqrt(dist) / 2` and silently break ranking quality.
- **Why it matters:** Docs are load-bearing for retrieval-quality invariants; a maintainer "correcting" one helper while leaving the other will create cross-handler divergence in scoring. Also, `ingest/store.py:407` still says "Distance type left at the LanceDB default (l2)" — but LanceDB returns `l2_squared` for the L2 metric, not L2. Three sites with the same misleading framing.
- **Proposed fix:** Update the docstrings to: "LanceDB returns squared L2 distance for the L2 metric. For unit vectors `||a-b||^2 = 2 - 2*cos(a,b)`, so `cos = 1 - dist/2` is the correct conversion to bounded cosine similarity in [0, 1]." Add a unit test that asserts orthogonal-unit-vectors → score 0.0 AND antipodal-unit-vectors → score 0.0 (clamped from -1) AND identical-unit-vectors → 1.0, anchored against the LanceDB return values demonstrated above.
- **Regression guard:** New test `test_lancedb_returns_squared_l2_for_unit_vectors` that creates a 3-row corpus of {v, v_orth, -v}, queries with v, asserts `_distance` raw values are `[0.0, 2.0, 4.0]`, AND that `_distance_to_score` of those produces `[1.0, 0.0, 0.0]`. Pins both the LanceDB API contract AND the score formula.

### F2 — Singleflight test does not exercise the constraint the brief actually pins

- **Severity:** HIGH
- **Source:** adversary
- **File:** tests/retrieval/test_ann.py:570-685
- **What:** The brief AC #4 says "Both embedding calls go through the shared Singleflight wrapper." The implementation reinterprets to "the (single) encode call goes through the singleflight" and tests this via `get_singleflight_dedup_count()`. But the dedup-counter test (`test_concurrent_identical_queries_dedup_to_one`) only proves the FAST PATH (caller-2 hits caller-1's in-flight future) is wired. It does NOT prove the SLOW PATH — the actual call from `ANNPhase.query` — routes through `encode_query` rather than `_encode_query_sync` directly. A future refactor that imports `_encode_query_sync` for "speed" would (a) keep one ANNPhase call passing the dedup test (no concurrent waiter), and (b) only fail the concurrent test by accident. The current test passes BOTH whether or not ANNPhase hits the singleflight — because the test patches `_encode_query_sync` and the singleflight wraps `_encode_query_sync`, the routing is forced regardless of caller behavior.
- **Why it matters:** The brief AC is a routing assertion (caller goes through the wrapper). The test is a wrapper-behavior assertion (the wrapper dedups). If a future change has ANNPhase bypass `encode_query`, neither test catches it. Also: the brief's stated observation surface (`/debug/cache-stats`) does not exist; the implementation correctly uses the in-process getter, but the Resources docstring at server/resources.py:30-32 already documents the two-tier model — verify the test asserts BOTH the singleflight AND the absence of `r.embed_semaphore` acquisition (since the implementation summary explicitly says ANNPhase doesn't acquire it, the future handler MUST — that contract is untested).
- **Proposed fix:** Add a test that monkey-patches `server.query_encoder.encode_query` itself (not the underlying sync helper) with a counter, calls `ANNPhase.query("x", bm25_candidates=[])` once, and asserts the patched function was invoked exactly once. This proves the routing through `encode_query` regardless of how the singleflight inside it behaves.
- **Regression guard:** `test_ann_phase_query_routes_through_encode_query` per above.

### F3 — `_ann_search_one_column` `except Exception` swallows programmer errors as "empty column"

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/retrieval/ann.py:126-142
- **What:** The bare `except Exception` catches everything: zero-row column, missing HNSW (legitimate degradation per brief risk note), AND a typo in `vector_column_name`, AND a schema drift where `_distance` column shape changes, AND a numpy dtype mismatch. I verified empirically: `tbl.search(vec, vector_column_name="typoooo")` raises `RuntimeError: lance error: LanceError(Index): column typoooo does not exist` — the helper would silently return [] and log WARNING. A test that uses `column="embedding_porf"` (typo) would still pass `test_dual_corpus_returns_results` because the OTHER column would carry the test.
- **Why it matters:** The brief's graceful-degradation mandate is for "column has no rows / no HNSW", not "wrong column name". The current cushion is wider than asked; bugs that should crash loud at startup or test time slip into runtime as "empty result + WARNING".
- **Proposed fix:** Catch a narrow set: `(lance.error.LanceError, ValueError, KeyError)` — with a comment naming WHY each is in the set. Specifically check the column EXISTS in the table schema before searching; if it doesn't, raise hard at startup (or fail-loud at first query). Alternative: add an `EMBEDDING_COLUMNS` schema check in `ANNPhase.__init__` that asserts both column names exist on `chunks_table.schema` (the constant is already declared).
- **Regression guard:** `test_typo_column_raises_at_init` that constructs `ANNPhase(chunks_table)` then asserts a constructor-time guard rejects a corpus where one of the EMBEDDING_COLUMNS is missing from the schema.

### F4 — `EMBEDDING_COLUMNS` constant declared and exported but never consumed

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/retrieval/ann.py:89, 257-268, 289
- **What:** `EMBEDDING_COLUMNS = ("embedding_stmt", "embedding_proof")` is declared as a module constant, named in `__all__`, but nowhere referenced — the two `_ann_search_one_column` calls hardcode `column="embedding_stmt"` and `column="embedding_proof"` as string literals. The constant's documented purpose ("Listed explicitly so `embedding_eq` (reserved for E10_S03) is NEVER searched here") is unenforced; a future engineer adding `embedding_eq` to the list will see no behavior change because the loop is hardcoded.
- **Why it matters:** Either dead code (which lies in the documentation as load-bearing) or future-proofing that doesn't actually proof anything. Both are bugs. A reader skim-reading the file will assume the constant is the source of truth.
- **Proposed fix:** Either (a) refactor the `query` method to iterate `for column in EMBEDDING_COLUMNS:` so the constant is the single source of truth, or (b) delete the constant + the `__all__` entry. Recommend (a) — also eliminates the duplication.
- **Regression guard:** A test that monkey-patches `EMBEDDING_COLUMNS` to `("embedding_stmt",)` and asserts only one `_ann_search_one_column` call is made.

### F5 — Phantom chunk_ids in BM25 list propagate to RRF output untreated

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/retrieval/ann.py:273-281
- **What:** `bm25_ids = [cid for cid, _score in bm25_candidates]` extracts every chunk_id from the BM25 list and feeds it directly into RRF. If the BM25 artifact is stale relative to LanceDB (between snapshots, or after a partial re-ingest), the BM25 list may contain chunk_ids that no longer exist in the chunks table. RRF will fuse them happily, and they appear in the returned top-50 as legitimate candidates. The downstream Phase 3 reranker (E07_S03) would then attempt to look them up and fail. This is not tested.
- **Why it matters:** E07_S01's `BM25Phase.startup` does cross-check live chunk_ids at startup (server/resources.py:329-339), so the production startup path is OK — but `ANNPhase.query` runs at every request and has no defense if a future change loosens that startup check or if the corpus is mutated mid-process. The per-query cost of intersecting with the live id set is negligible at seed scale.
- **Proposed fix:** Document the invariant (BM25 list is a subset of live chunk_ids; ANNPhase trusts this) at the docstring level. Optionally add a debug-only assertion. If documenting only, add a test that proves the phantom-id case produces a non-error result (i.e., the phantom appears in output, NOT a crash) — so future maintainers know the contract.
- **Regression guard:** `test_phantom_bm25_id_appears_in_output` — pass `[("nonexistent:chunk:0000", 1.0)]` as BM25 candidates, assert the result includes that id (proving the documented behavior is intentional, not a bug).

### F6 — Sequential ANN searches with no latency budget assertion

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/retrieval/ann.py:257-268
- **What:** Two sequential `tbl.search(...)` calls. The implementation summary says "Seed-scale latency is sub-10ms each; sequential is fine. Parallel adds complexity that isn't yet justified." But no test asserts a latency budget, and at production scale (1M+ chunks per the design note) sub-10ms is optimistic. There is no regression guard against a future LanceDB change that bumps per-call latency 10×.
- **Why it matters:** Phase 2 sits between Phase 1 (BM25, fast) and Phase 3 (reranker, slow). The hybrid latency budget is dominated by Phase 3 if Phase 3 is enabled, but with `ARXMCP_ENABLE_RERANK=false` (the default), Phase 2 IS the latency budget. Brief says nothing about latency, but the design doc at .claude/notes/05-storage-and-indexing.md:316-331 sets the implicit expectation.
- **Proposed fix:** No code change needed for v1, but add a test that asserts `ANNPhase.query` against the dual-corpus fixture completes in < 500ms (generous; pins against catastrophic regression). Document the parallel-fan-out follow-up TODO inline at the call site.
- **Regression guard:** `test_query_latency_under_500ms` — wall-clock around `asyncio.run(ann_phase.query(...))` against the 8-row dual fixture.

### F7 — Singleflight test patches `_encode_query_sync` directly, may leak across tests

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/retrieval/test_ann.py:610-619, 658-674
- **What:** Both `TestSingleflightContract` tests do `qe_mod._encode_query_sync = _fake_sync` and restore in `finally`. If the test is interrupted by KeyboardInterrupt during the `try` block (or a future bug raises a non-Exception subclass), the restore in `finally` runs but the dedup state is corrupt for any test running after. Compare with the `monkeypatch` fixture (used by `_mocked_bge`) which has pytest-managed teardown guarantees regardless of interrupt path.
- **Why it matters:** Test isolation. A future refactor that changes test ordering could surface phantom failures with no obvious cause.
- **Proposed fix:** Replace the manual `try/finally` with `monkeypatch.setattr(qe_mod, "_encode_query_sync", _fake_sync)` so pytest handles the teardown. Add `qe_mod._reset_for_tests()` to a fixture-scoped finalizer so the dedup counter is guaranteed-reset between every test in the class.
- **Regression guard:** Implicit — the `monkeypatch` fixture's teardown is the guard.

### F8 — `_mocked_bge` patches `encode_query` in two modules; brittle to future refactor

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/retrieval/test_ann.py:182-211
- **What:** The fixture monkey-patches `encode_query` in BOTH `server.query_encoder` AND `server.retrieval.ann`. The comment says "Also patch the import seen by server.retrieval.ann" — this is correct because Python's `from ... import ...` binds the name at the importing module's namespace. But if a future module imports `encode_query` (e.g. a hypothetical `server.retrieval.hybrid` that orchestrates BM25 + ANN + reranker), the fixture won't patch it and any test that uses `_mocked_bge` against that module would silently call the real BGE-M3.
- **Why it matters:** Mock surface is brittle. Better to patch the single source.
- **Proposed fix:** Either patch only `qe_mod.encode_query` and use `import server.query_encoder as qe; qe.encode_query(...)` style in `ann.py` (eliminates the dual-patch), or patch the underlying `_encode_query_sync` (one site, all callers downstream). The latter is what `TestSingleflightContract` already does.
- **Regression guard:** A lint-level rule (e.g. ruff `TID252`) that bans `from server.query_encoder import encode_query` — forces the namespace pattern.

### F9 — `top_n > corpus_size` not tested; relies on RRF/LanceDB to silently truncate

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/retrieval/ann.py:283-284
- **What:** `top_n` defaults to 50, `PER_COLUMN_LIMIT` is also 50, and the test corpus has 8 rows. `fused[:top_n]` will return all 8 (no error), but no test explicitly asserts behavior when `top_n > len(unique_ids_across_lists)`. Edge case: `top_n=1000000` on a tiny corpus — should return at most `len(union)` results, not crash.
- **Why it matters:** Caller passing `top_n=999999` (e.g. via env-var misconfig) should be defensively handled at the API boundary, not implicitly by RRF's slice. A pathologically large `top_n` could allocate an oversized buffer somewhere downstream.
- **Proposed fix:** Add a test `test_top_n_larger_than_corpus_truncates_to_corpus_size`. Optionally add an upper bound (`if top_n > 10_000: raise ValueError(...)`) — defensive but explicit.
- **Regression guard:** The new test.

### F10 — `query_text` validation absent at ANNPhase boundary; relies on caller

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/retrieval/ann.py:202-242
- **What:** `query_text` is passed verbatim to `encode_query`, which calls `_canonicalize` (NFC + strip). Empty strings, whitespace-only strings, and 100MB strings all reach the tokenizer. `server/handlers/search.py:80` validates `min_length=1, max_length=2000` at the schema layer — but ANNPhase as a peer of BM25Phase has no such guard at its own boundary. A future caller that invokes ANNPhase from a non-validated context (e.g. a debug script, a future internal RPC, a test fixture) bypasses the validation.
- **Why it matters:** Defense in depth. If the only validator is at the FastAPI handler, an attacker who compromises any internal call chain bypasses it.
- **Proposed fix:** Add `if not query_text.strip(): raise ValueError("query_text must contain non-whitespace characters")` at the top of `ANNPhase.query`, alongside the existing `top_n < 1` check. Add an upper-bound check (`if len(query_text) > 10_000: raise ValueError(...)`) — note: `2000` is the handler limit; `10_000` here is generous defense in depth, not a tight bound.
- **Regression guard:** `test_empty_query_rejected` and `test_oversized_query_rejected`.

### F11 — Implementation summary's "Deviation 3" is genuinely a non-deviation; brief never asked for handler integration

- **Severity:** LOW
- **Source:** adversary
- **File:** .claude/notes/milestones/E07_S02/implementation-summary.md:57
- **What:** The summary lists "Handler integration deferred" as deviation 3. Re-reading the brief Deliverables section verbatim: only `server/retrieval/ann.py`, `server/retrieval/rrf.py`, and `tests/retrieval/test_ann.py` are listed. The brief never requested handler integration. So this is not a deviation — it's correct scope. Calling it a "deviation" in the summary creates a false signal that the implementer dropped something the brief required.
- **Why it matters:** Process hygiene only — a downstream rectifier reading the deviation list might attempt to "fix" the non-deviation and waste effort.
- **Proposed fix:** Reword Deviation 3 in the summary as a "Followup" or "Out of scope, by design" note.
- **Regression guard:** N/A.

### F12 — `Resources.ann_phase` typed as `Any | None`; no startup-success postcondition

- **Severity:** LOW
- **Source:** adversary
- **File:** server/resources.py:234
- **What:** `ann_phase: Any | None = None`. After `Resources.startup` completes successfully, `ann_phase` is always non-None. But the type system can't see this — every consumer must handle the None case (or risk an AttributeError). Compare with `chunks_table: Any` (no `| None`) which expresses the post-startup guarantee. Same critique applies to `bm25_phase`.
- **Why it matters:** Type-safety foot-gun. A future handler that does `r.ann_phase.query(...)` will type-check fine but crash at runtime if Resources isn't fully warm.
- **Proposed fix:** Document the lifecycle explicitly: `ann_phase` is `None` only between `__init__` and `startup` completion, but the dataclass is internal so the safer pattern is `field(init=False, default=None)` plus an `is_resource_warm("ann")` predicate. Or accept the current state and add `assert r.warm` to consumers.
- **Regression guard:** N/A; doc-level only.

### F13 — `Singleflight.dedup_count` getter exists on `Resources.rerank_singleflight` but `query_encoder` uses a separate counter

- **Severity:** LOW
- **Source:** adversary
- **File:** server/resources.py:198-201, server/query_encoder.py:184
- **What:** Two singleflight implementations live in two modules: `server.resources.Singleflight` (generic, future reranker) and `server.query_encoder` (embedder-specific, used by ANNPhase). They each maintain their own dedup counter. The brief AC #4 mentions a singleflight; if a future eval cross-references the counters they will not aggregate. Not new in E07_S02 but the new ANNPhase exercise of `query_encoder`'s singleflight is the first non-test consumer.
- **Why it matters:** Observability hygiene. If a metrics scraper exposes both counters as `arxmcp_embed_singleflight_dedup_total` and `arxmcp_rerank_singleflight_dedup_total`, that's fine; if it accidentally exposes only one, the other is invisible.
- **Proposed fix:** Document at `Resources.rerank_singleflight` that the counter must be exposed as a separate Prometheus series in E07_S03+.
- **Regression guard:** N/A.

### F14 — Logging spam risk on stmt-only production corpus

- **Severity:** LOW
- **Source:** adversary
- **File:** server/retrieval/ann.py:138-141
- **What:** `_ann_search_one_column` logs at WARNING when a column search fails (e.g. zero-row `embedding_proof` column on a stmt-only seed corpus). This is currently the production state per the implementation summary's documented degradation case. A WARNING per query × N queries × multi-agent fan-out → ops gets log spam.
- **Why it matters:** Log noise erodes signal. WARNING is meant to surface unexpected states; "we're on a stmt-only corpus" is expected per the brief risk note.
- **Proposed fix:** Two options: (a) demote to DEBUG when the failure mode is "expected empty"; (b) check the column's row count once at `__init__` and skip the search entirely if it's zero, eliminating the per-query exception path. Option (b) is cleaner — also addresses F3.
- **Regression guard:** `test_stmt_only_corpus_no_warning_logs` using `caplog`.

## What was done well

- **Pure-RRF separation.** `rrf.py` is a clean, dependency-free utility that's easy to test in isolation. The choice to make RRF rank-only (ignoring source scores) follows the original Cormack-Clarke-Büttcher 2009 paper exactly and composes cleanly across BM25 + ANN scoring families.
- **Determinism discipline.** Sort key `(fused_score desc, chunk_id asc)` matches the project-wide convention from server/handlers/search.py:128 and 06-mcp-server-design.md, preserving prompt-cache byte-stability across multi-agent fan-out.
- **Documented graceful-degradation tree** at server/retrieval/ann.py:28-42 enumerates the three empty-input cases (BM25 empty, proof column empty, all empty) with the exact behavior for each. Brief risk note explicitly addressed.
- **Lifecycle parity.** `ann_phase` field added to `Resources` dataclass alongside `bm25_phase`, with cheap-construction at startup matching the BM25 pattern (server/resources.py:345-353). No new async-startup classmethod needed.
- **Test fixture discipline.** `_dual_corpus` builds 5 stmt + 3 proof chunks with disjoint paper_ids (2307.0xxxx / 2307.1xxxx) — easy to assert "both kinds present in output" by id-prefix matching, no need to re-query the table.
- **30-test coverage** for ~270 LOC of implementation is generous: covers RRF formula correctness with explicit tiebreak math, edge cases (zero/negative k, empty inputs), score conversion, dual-corpus smoke, pure-ANN fallback, descending-sort, top-n cap, graceful degradation in two flavors, and singleflight contract.
- **Brief AC traceability** in test docstrings: every test names the brief AC it covers (`test_pure_ann_fallback_with_empty_bm25` → AC #1, etc.). Easy for the rectifier to verify nothing was dropped.
- **Documented research deviations.** The implementation summary calls out (1) one-encoder vs the brief's two, (2) the missing `/debug/cache-stats` endpoint, and (3) deferred handler integration. Each deviation is justified, not silently absorbed.
- **Resources integration test** (`test_resources_startup_populates_ann_phase`) is the right end-to-end probe: it calls `Resources.startup` rather than constructing ANNPhase directly, catching wiring bugs that pure-unit tests would miss.
- **`encode_query` is awaited ONCE** in `ANNPhase.query` (server/retrieval/ann.py:250), correctly avoiding a redundant forward pass — the singleflight would dedup it anyway, but the dedup-counter contract assumes the caller doesn't burn it gratuitously.

## Recommended rectification order

1. **F1** — Fix the docstring lie before any future maintainer "corrects" the formula. Cheap (3-line edit + 1 test) and unblocks correct reasoning about all dense-search code in the repo.
2. **F2** — Add the routing test for the singleflight wrapper. Low LOC, closes the gap between brief AC #4 (routing) and the current test (wrapper-behavior).
3. **F3** — Narrow the `except Exception` in `_ann_search_one_column`. Pair with F4 (use `EMBEDDING_COLUMNS` to validate at init) since both are about the same code region.
4. **F4** — Either consume `EMBEDDING_COLUMNS` in the search loop or delete it. Pairs with F3.
5. **F10** — Add `query_text` validation at the ANNPhase boundary. Defense-in-depth, 4-line change.
6. **F5** — Document the phantom-id contract; add the regression test that pins the behavior.
7. **F7** — Replace manual patch/restore with `monkeypatch`. One-line-per-test.
8. **F14** — Demote the per-query WARNING to DEBUG (or skip the search at init). Pairs with F3.
9. **F6** — Add the latency budget regression test. No production code change.
10. **F8** — Lint rule against bare `from ... import encode_query`. Defer if cheaper alternatives don't exist.
11. **F9** — Add the `top_n > corpus_size` test.
12. **F11, F12, F13** — Doc-level fixes; defer or batch.

## Rectification status (filled by Phase 4)

| ID | Severity | Status | Notes |
|---|---|---|---|
| F1 | HIGH | **fixed** | Empirically verified LanceDB returns squared L2: a unit-vector query against `{v, v_orth, -v}` yields `_distance = [0.0, 2.0, 4.0]`. Rewrote docstrings in `server/retrieval/ann.py:_distance_to_score`, `server/handlers/search.py:_distance_to_score`, AND `ingest/store.py:407` to call out the squared-L2 contract. Added `TestLanceDBDistanceSemantics` class (2 tests) pinning both the LanceDB return-value contract AND the formula correctness. |
| F2 | HIGH | **fixed** | New `TestSingleflightContract::test_ann_phase_query_routes_through_encode_query` monkey-patches `encode_query` itself (not the underlying sync helper) with a counter; asserts `ANNPhase.query` invokes it exactly once per call. Catches a future refactor that bypasses the singleflight by importing `_encode_query_sync` directly. |
| F3 | MEDIUM | **fixed** | Narrowed `_ann_search_one_column`'s `except Exception` to `(ValueError, KeyError, RuntimeError)`. Added `ANNPhase.__init__` schema-validation: refuses to construct if any `EMBEDDING_COLUMNS` entry is missing from `chunks_table.schema.names`. New `TestSchemaValidation::test_missing_column_raises_at_init` covers it. |
| F4 | MEDIUM | **fixed** | `ANNPhase.query` now iterates `self._searchable_columns` (which is filtered through `EMBEDDING_COLUMNS`) instead of hardcoding two strings. The constant is now the single source of truth — adding `embedding_eq` (E10_S03) to `EMBEDDING_COLUMNS` would automatically wire it. |
| F5 | MEDIUM | **fixed** | Added phantom-id contract documentation to `ANNPhase.query` docstring and new `TestPhantomBm25Ids::test_phantom_bm25_id_appears_in_output` test that pins the documented behavior (phantom appears in output, no crash). The startup cross-check (E07_S01 F4) is the canonical guard. |
| F6 | MEDIUM | **fixed** | New `TestLatencyBudget::test_query_under_500ms_against_dual_corpus` pins a generous 500ms budget on the 8-row dual fixture. Catches catastrophic O(n²) regressions without flaking on slow CI. |
| F7 | MEDIUM | **fixed** | Refactored both `TestSingleflightContract` tests to use `monkeypatch.setattr` instead of manual `try/finally`. pytest-managed teardown is guaranteed even on KeyboardInterrupt. |
| F8 | MEDIUM | **deferred** | Patching surface is a known brittleness but the trade-off (single-source patch via `_encode_query_sync` vs name-namespace patches) is documented in the test docstring; a lint-rule layer to enforce it would be over-engineered for the current scale. |
| F9 | MEDIUM | **fixed** | New `TestTopNLargerThanCorpus::test_top_n_larger_than_corpus_returns_union_size` calls `query(top_n=100)` against an 8-row corpus and asserts the result is `len ≤ 8` without crashing. |
| F10 | MEDIUM | **fixed** | Added `query_text` validation at `ANNPhase.query` entry: empty / whitespace-only / >10,000 chars all raise `ValueError`. Defense-in-depth above the FastAPI handler's 2,000-char Pydantic limit. New `TestQueryTextValidation` class (4 tests). |
| F11 | LOW | **deferred** | Documentation finding; the implementation summary's wording will be cleaned up alongside other doc passes. |
| F12 | LOW | **deferred** | Documentation finding; `ann_phase: Any \| None` matches the existing dataclass discipline (`bm25_phase` is also `Any \| None`). Tightening would be a cross-cutting refactor. |
| F13 | LOW | **deferred** | Documentation finding about future Prometheus exposure; out of scope for this milestone. |
| F14 | MEDIUM | **fixed** | Added `_column_has_rows` helper + `_searchable_columns` set computed once at `ANNPhase.__init__`. The per-query path skips empty columns entirely — no per-query WARN. New `TestStmtOnlyCorpusLogQuiet::test_stmt_only_corpus_no_per_query_warning` asserts zero WARNs across 2 queries on a stmt-only corpus. A one-time WARN at init still fires when BOTH columns are empty. |

Suite at rectification: **884 passed, 3 skipped, ruff clean** (was 872 pre-rect — +12 from regression tests).

Reverify pass: F1 was empirically reproduced via a 6-line standalone LanceDB script (the `[0.0, 2.0, 4.0]` distances are now baked into the regression test). F2 was diagnosed by tracing the previous test path: it would pass even if `ANNPhase` bypassed `encode_query`, because the dedup behavior was assertion-tested independently of the routing. F3+F4 reverify exposed that `EMBEDDING_COLUMNS` was decorative; the consolidation now makes it load-bearing.

