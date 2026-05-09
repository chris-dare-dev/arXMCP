# E07_S01 — Research synthesis

## Both researchers agree on these load-bearing facts

1. **BM25 ships as `rank_bm25` pickle + `chunk_ids.json` sidecar** at `var/arxmcp/index/bm25/v<N>/{bm25.pkl, chunk_ids.json}`, NOT a LanceDB FTS index. The brief's "LanceDB scalar + FTS predicates" is fictional — `create_fts_index` is not called anywhere. (Brief 1 §1.4, Brief 2 §1.1.)

2. **Filter columns do not exist on the `chunks` table.** Verified in `ingest/schema.py:69-118`. None of `categories`, `year_min`, `year_max`, `authors`, `include_withdrawn` are present. The brief's AC `BM25Phase.query("\\Spec", filters={"categories": ["math.AG"]})` cannot be satisfied as written. The `papers` metadata table planned in E06_S03 brief 1 has not been built. (Both briefs §1.2 / §1.5.)

3. **`body_canonical` is a typo for `body_text`.** The chunks table has `body_text` (canonical macro-expanded prose) and `body_tokens` (whitespace-joined token stream), not `body_canonical`. The brief's fallback path is unreachable as written. (Both briefs §1.2 / §2.)

4. **`build_bm25_index` has zero production call sites** (E04_S04 critique H1 still unresolved — `bm25_indexer.py` ships the build, but nothing in `server/` invokes it). E07_S01 must either auto-build at server startup if the artifact is missing, or fail-fast with a clear error. (Brief 2 §2.)

5. **Pickle loader hardening is a hard requirement** carried over from E04_S04's TODO(E07) at `ingest/bm25_indexer.py:62-71`: "the loader … MUST verify file ownership matches process UID and refuse world-writable paths before calling `pickle.load`." This milestone owns it. (Both briefs §2 / §3.)

6. **`rank_bm25.BM25Okapi.get_scores` is read-only after construction** — pure NumPy ops on indexed `idf`/`doc_freqs`/`doc_len` arrays. Safe under the GIL for concurrent readers; no locks needed. (Both briefs §2.)

## Decisions for the implementer (adopted, not open)

| ID | Decision | Rationale |
|---|---|---|
| D1 | **Architecture: in-memory pickle, not LanceDB FTS.** | Forced by E04_S04 reality; H4 critique-remediation rejected Tantivy. |
| D2 | **Filter handling: accept the `filters` arg, surface ignored ones via `filter_warnings: list[str]`.** | Precedent: `server/handlers/search.py:131-141`. Reinterprets the AC: assert `filter_warnings` is non-empty for unimplemented filter keys; `paper_id` filter is honored (it's a real column). |
| D3 | **Auto-build via `build_bm25_index(lancedb_path, corpus_version)` if `bm25.pkl` missing for the pinned `corpus_version`.** | Closes E04_S04 H1. Idempotent-skip already handles the warm-start no-op. Fail-fast (raise) only if both load AND build fail. |
| D4 | **Pickle hardening REQUIRED in `BM25Phase.__init__`.** | Stat-check `os.stat(path).st_uid == os.geteuid()` + refuse `mode & 0o002` (world-writable). Reject before `pickle.load`. Closes the TODO(E07). |
| D5 | **Eager load in `Resources.startup` via `loop.run_in_executor`.** | `/readyz` honest about readiness. Failure = new `BM25IndexUnavailableError` subclass of `ResourceStartupError` (mirrors `CorpusNotIngestedError` at `server/resources.py:98-105`). |
| D6 | **Query tokenization parity: `ingest.tokenizer.tokenize_body(text).split()`.** | Index-time tokenization is the same call (`bm25_indexer.py:340`); without it, `\Spec` raw never matches `Spec` indexed. The "byte-faithful" rule applies upstream of caching (Tier-1 cache normalizes `query.strip()` only), not here. |
| D7 | **Filter ordering: over-fetch `top_n * 4 = 800` from BM25, post-filter, truncate to `top_n` (default 200).** | Brief 2 recommendation. Matches `search.py:115` over-fetch pattern. Re-fitting BM25 per-subcorpus would change IDFs and cost ~100ms+. |
| D8 | **File layout: `server/retrieval/bm25.py` + `server/retrieval/__init__.py` + `tests/retrieval/test_bm25.py` + `tests/retrieval/__init__.py`.** | New package boundary; the existing `tests/test_bm25.py` covers the indexer (build side), the new file covers the loader (query side). |
| D9 | **`BM25Phase.query` returns `tuple[list[tuple[str, float]], list[str]]` (RECONCILED with the "Open" section below).** | The first element is the materialized ``(chunk_id, score)`` candidate list (matches the brief AND the `ANNPhase` return shape E07_S02 will produce). The second element is the `filter_warnings` list — see "Open: how to surface filter_warnings" below; option (a) was adopted, and this row was updated by the E07_S01 rectification (F5 fix from the adversary critique) so D9 and the Open recommendation no longer disagree. E07_S02 RRF unpacks via `candidates, warnings = bm25_phase.query(...)` and propagates `warnings` into the search envelope. |
| D10 | **No modifications to `server/handlers/search.py`.** | E07_S02 owns the integration into the search handler (RRF fusion). E07_S01 lands the standalone `BM25Phase` only. |

## Reinterpreted acceptance criteria

The brief's literal ACs are partially impossible (filter columns don't exist). Reinterpretation:

| Brief AC | Reinterpretation | How verified |
|---|---|---|
| `BM25Phase.query("étale cohomology")` returns non-empty <500ms | Unchanged | Time-boxed assertion in test |
| `BM25Phase.query("\\Spec", filters={"categories": ["math.AG"]})` returns only math.AG chunks | **Reinterpreted**: `filters` arg with unsupported keys returns ALL matching chunks AND a non-empty `filter_warnings`. Use `paper_id` filter (a real column) for an "actually narrows" assertion. | New assertions on the standalone `BM25Phase.query(...)` return-shape extension OR a `result_envelope` wrapper |
| Returned list length ≤ 200 | Unchanged | Test fixture with > 200 candidates |
| `chunk_id` values present in LanceDB table | Unchanged | Cross-check against `r.chunks_table` |
| `pytest tests/retrieval/test_bm25.py` passes | Unchanged | The whole-suite check |

**Open: how to surface `filter_warnings`.** Two options:
- (a) Change `BM25Phase.query` return shape to `tuple[list[tuple[str, float]], list[str]]` — returns warnings alongside candidates. Couples the API to filter semantics.
- (b) Keep return shape per brief; warnings live on a separate `BM25Phase.last_filter_warnings` instance attribute (or returned via an out-param dict). Decouples but introduces hidden state.
- **Recommendation: (a)** — explicit > implicit; the upstream caller (E07_S02 RRF) gets the warnings without an extra API call. Update `BM25Phase.query` signature to return `tuple[list[tuple[str, float]], list[str]]`. Document the deviation in the implementation summary.

## External writes the implementation will require

None. Purely-internal retrieval milestone:
- `server/retrieval/bm25.py` (new)
- `server/retrieval/__init__.py` (new)
- `server/resources.py` (modify — add `bm25_phase` field + startup wire-up)
- `tests/retrieval/test_bm25.py` (new)
- `tests/retrieval/__init__.py` (new)

No git push, PR creation, ticket mutation, infra change, or third-party API call. All artifacts live under `var/arxmcp/index/bm25/v<N>/` (already produced by E04_S04) and Python source under the new `server/retrieval/` + `tests/retrieval/` packages.
