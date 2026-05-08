# E04_S04 Adversary Critique

## Executive Summary
- Verdict: **fix-then-proceed**. The implementation closes every brief AC and is well-structured, but two pre-merge concerns warrant attention before E07 wires the index into the query path.
- Module is clean, idempotent, atomic, and follows the established codebase patterns; the H4 docstring is verbatim and locked by a regression test.
- `build_bm25_index` is **never called from production code** — no `write_chunks` hook, no CLI entry, no `__main__`. Index will not exist at server start unless someone manually invokes it. This is the only HIGH finding.
- Pickle-security paragraph in the module docstring is well-reasoned but is *documentation-only*: nothing in the loader (E07) is constrained yet to "trusted-local". Defense-in-depth markers (e.g. an explicit allow-list / `RestrictedUnpickler` plan) belong here as a TODO that future loaders must honor.
- Empty-string (`body_tokens=""`) edge isn't handled distinctly from `None` — produces empty token lists in the corpus, which `BM25Okapi` accepts but yields degenerate IDFs. Low-likelihood (schema requires non-empty) but worth a guard.
- Test for "Spec mathrm_Pic" is good; the disjoint-vocabulary negative test is *weak* (asserts only that target ISN'T returned; doesn't assert the *expected* decoy IS returned).
- `f"v{` literal-scan test is fragile against a future zero-padding refactor — flagged LOW.
- Atomic-write helpers are duplicated for the **fourth** module; not a defect but a real bug-multiplier risk acknowledged in implementation summary; flagged MEDIUM.

## Severity calibration table

| Severity | Definition | Count |
|---|---|---|
| CRITICAL | Data loss / security broken / invariant violated | 0 |
| HIGH | Wrong behavior on common path | 1 |
| MEDIUM | Subtle correctness or missing test | 4 |
| LOW | Style, fragility, doc nits | 5 |

## Findings

### HIGH

#### H1. `build_bm25_index` has zero production call sites
- **What**: The function is exported from `ingest/bm25_indexer.py` but is not invoked by any module in `ingest/`, `server/`, or any CLI/script. After `write_chunks` succeeds, nothing builds the BM25 index. E07 will load `bm25.pkl` from a directory that may not exist.
- **Why it matters**: The brief says "Idempotent if files exist" — implying re-runs are safe — but it does not specify *who calls it*. Without a caller, the AC "Index built from non-null body_tokens in pinned LanceDB version" is satisfied only by the test harness. A first-time deployer running `python -m ingest.store ...` will end up with a corpus that has no BM25 index, and E07's lexical-search path will crash on missing files. Either `write_chunks` should auto-call it (analogous to how `write_corpus_version_marker` is called from inside `write_chunks` per E04_S03) or a deferred-to-Eepic note must explicitly state where the wire-up lives.
- **Where**: `ingest/bm25_indexer.py:182-306` (no callers); `ingest/store.py` (no invocation after `write_chunks`); `.claude/notes/milestones/E04_S04/research-synthesis.md:74-87` (D5 says "trust the caller's `corpus_version`" but does not say *who* the caller is).
- **Fix sketch**: Add a one-line invocation at the end of `write_chunks` (after `write_corpus_version_marker`) gated behind a parameter like `build_bm25: bool = True`, or document explicitly in the milestone summary which downstream milestone owns the wire-up. If the latter, add a TODO(EXX) marker in `bm25_indexer.py`.

### MEDIUM

#### M1. Pickle threat-model is documented, not enforced
- **What**: Module docstring states the BM25 pickle "MUST be treated as trusted-local". But there is no plan / TODO in `bm25_indexer.py` for the loader (E07) to validate trust. `pickle.load` on an attacker-replaced `bm25.pkl` is RCE; the only mitigation is filesystem permissions on `var/arxmcp/index/bm25/`.
- **Why it matters**: Threat 6 (`08-security-observability-ops.md`) bans pickle for model weights. The BM25 pickle is *application data* — but the same attacker model applies if `var/` is on a shared filesystem (NFS, Docker bind-mount, multi-tenant container). The implementation's "trust local" framing is correct but lacks a concrete control. Without a pinned hash, file permission check, or `RestrictedUnpickler`, defense-in-depth is zero. This is the H4 closure's *only* lingering security debt.
- **Where**: `ingest/bm25_indexer.py:30-37` (docstring "Pickle security" paragraph); the BM25 pickle write at `ingest/bm25_indexer.py:289-290`.
- **Fix sketch**: Add a TODO marker at the writer that names the loader's required check (e.g. `# TODO(E07): loader must verify file ownership matches process UID and refuse world-writable paths`), and store a SHA-256 of the pickle in `chunk_ids.json` (or alongside it) so the loader has a tamper detector even on a mode-0644 file.

#### M2. Empty-string `body_tokens` produces degenerate corpus rows
- **What**: The filter `if body is None: continue` skips nulls but **passes through empty strings**. `"".split()` is `[]`, an empty token list. `BM25Okapi` with mixed empty + non-empty docs computes IDFs with zero-length docs in the average, distorting `b`-normalized scores.
- **Why it matters**: Schema declares `body_tokens` non-nullable but does NOT declare it non-empty. A regression in `tokenizer.tokenize_body` that returns `""` for an edge-case latex source (e.g. preamble-only chunk) silently corrupts BM25 ranking instead of failing fast. The test corpus has no empty-string row, so the existing test suite cannot detect this drift.
- **Where**: `ingest/bm25_indexer.py:261-266`; schema at `ingest/schema.py:77` (`pa.field("body_tokens", pa.utf8(), nullable=False)` — no min-length).
- **Fix sketch**: Either (a) skip empty token lists with `if not tokens: continue` and log a per-chunk warning, or (b) raise `ValueError` if any non-null body has empty tokens. The first preserves Tier-0 progress; the second matches D8's empty-corpus discipline.

#### M3. Atomic-write helpers duplicated across four modules
- **What**: `_atomic_write_bytes` / `_atomic_write_text` (this commit) join near-identical implementations in `preamble.py:274`, `embedder.py:464,563`, and `store.py:568`. Acknowledged in implementation-summary §"Notable design choices" as deferred housekeeping.
- **Why it matters**: A bug found in one (e.g. tmp file leaks on Windows because `unlink(missing_ok=True)` semantics differ; or a race where `tmp.with_suffix` clobbers an existing suffix) must be patched in four places. Per the project's no-fork policy this is on-brand for now, but the bug-multiplier risk is real and growing linearly with each milestone.
- **Where**: `ingest/bm25_indexer.py:118-149`; `ingest/preamble.py:268-281`; `ingest/embedder.py:458-475, 557-575`; `ingest/store.py:562-576`.
- **Fix sketch**: Extract to `ingest/_atomic_io.py` (or similar) in a *standalone* housekeeping commit with no behavior change. Out-of-scope for E04_S04 but should be tracked.

#### M4. Disjoint-vocabulary test asserts the wrong invariant
- **What**: `TestQueryAccuracy.test_query_disjoint_vocabulary_does_not_match_target` queries `["manifold", "cohomology"]` against the corpus and asserts only that `chunk_ids[top_idx] != target_chunk_id`. A query for `["xyz", "qrs"]` (nonsense) would also pass this assertion — `argmax` over all-zero scores returns index 0, which IS the target, so the test would fail; but a query that returns *any* non-target chunk passes regardless of relevance.
- **Why it matters**: The test does not verify that BM25 ranks the *expected* chunk (the cohomology decoy at index 15) at the top. A future regression in BM25Okapi's tokenization could rank a random decoy first and the test would still pass. This weakens the AC's "matching chunk top" semantics.
- **Where**: `tests/test_bm25.py:283-291`.
- **Fix sketch**: Strengthen to `assert chunk_ids[top_idx] == chunks[15].chunk_id` (the cohomology decoy) and add a comment naming why that index is expected. This catches both "target-leaks-into-results" and "BM25 ranks unrelated chunks first" regressions.

### LOW

#### L1. `f"v{` literal-scan test is brittle against zero-padding refactors
- **What**: `TestSingleSourceOfTruth.test_no_stray_v_string_literal` scans for `f"v{` substring across `ingest/` and `server/`. A future refactor adopting `f"v{corpus_version:03d}"` for sortable directory names would still pass (the literal lives in one function), but if anyone adds a *legitimate* `f"v{python_version}"` for an unrelated reason, the test fails.
- **Why it matters**: The intent (single-source-of-truth for the BM25 directory pattern) is correct, but the implementation tests for *absence of a string fragment*, not for *call-graph dominance*. A docstring containing `f"v{N}"` as a code example would also fail.
- **Where**: `tests/test_bm25.py:464-486`.
- **Fix sketch**: Either narrow to a more specific marker (e.g. `'BM25_INDEX_ROOT / f"v{'`) or move to a static-analysis approach (e.g. AST-based: only `_bm25_version_dir` may construct paths under `BM25_INDEX_ROOT`). Out-of-scope to fix here, just flagging.

#### L2. `time.sleep(0.01)` for mtime delta is filesystem-dependent
- **What**: `TestIdempotency.test_partial_state_triggers_rebuild` sleeps 10ms before re-running, asserting `pkl_path.stat().st_mtime_ns != mtime_pkl_before`. On filesystems with mtime resolution coarser than 10ms (some NFS, FAT32, ZFS-with-sync-tuned-down), the delta is not observable and the test flakes intermittently.
- **Why it matters**: APFS/ext4/btrfs (the realistic dev/CI targets) have nanosecond resolution, so this is unlikely to flake in practice. But the assertion pivots on a clock-tick rather than a semantic property (e.g. file inode change). The same correctness check could be made deterministic by comparing `stat().st_ino` (atomic-replace creates a new inode) rather than mtime.
- **Where**: `tests/test_bm25.py:359-367`.
- **Fix sketch**: Replace `mtime` comparison with `st_ino` comparison and remove the sleep — atomic replace via `os.replace` always changes the inode on POSIX. Cleaner and faster.

#### L3. `corpus_version` is not validated as non-negative
- **What**: `_bm25_version_dir(-1)` produces `var/arxmcp/index/bm25/v-1/`. LanceDB rejects negative versions inside `open_chunks_table` (raises `ValueError`), so the path never gets created. But if validation order changes — e.g. someone caches the directory before opening LanceDB — a negative `corpus_version` could create a confusing on-disk artifact.
- **Why it matters**: Defense-in-depth. The schema for `CorpusVersionInfo.from_dict` validates `version >= 1` (E04_S03 H1 close); the BM25 indexer should mirror that discipline.
- **Where**: `ingest/bm25_indexer.py:78-86, 182-247`.
- **Fix sketch**: Add `if not isinstance(corpus_version, int) or corpus_version < 1: raise ValueError(...)` at the top of `build_bm25_index`. One line, matches sibling validation in `CorpusVersionInfo`.

#### L4. `chunk_count=0` on idempotent skip is semantically wrong
- **What**: When the function skips, it logs `BM25Stats(chunk_count=0, ...)`. The actual chunk count of the existing index is unknown without loading the pickle, so 0 is a *placeholder*. Ops dashboards counting "total chunks indexed" by summing `chunk_count` will undercount on every skipped row.
- **Why it matters**: Mostly a stats-aggregation footgun, not a correctness bug. The `skipped=True` flag lets dashboards filter, but a naive query "AVG(chunk_count) over the last week" will be skewed by every no-op rebuild.
- **Where**: `ingest/bm25_indexer.py:240-246`.
- **Fix sketch**: Either (a) load `chunk_ids.json` in the skip branch and report its length, or (b) document the convention `chunk_count=0 IFF skipped=True` in the `BM25Stats` docstring so dashboards know to ignore.

#### L5. Stats brief mismatch — no `paper_count`
- **What**: Brief AC: "Build time for 50 papers logged." The implementation logs `chunk_count` and `corpus_version` only. The corpus's *paper count* is recoverable from `corpus-version.json` (`paper_count` field) but is not denormalized into the BM25 stats line, so a reader of `bm25-stats.jsonl` cannot answer "how many papers in this index" without joining.
- **Why it matters**: Minor. The brief is loose ("Build time for 50 papers logged" reads as "build for a 50-paper test corpus is logged" rather than "paper_count column is logged"). Implementation-summary calls this AC as satisfied. But ops triage is easier when the stats line is self-contained.
- **Where**: `ingest/bm25_indexer.py:90-115` (`BM25Stats` dataclass).
- **Fix sketch**: Add `paper_count: int = 0` to `BM25Stats`, populate by reading `read_corpus_version(lancedb_path).paper_count` (already imported via `server.corpus`). Or accept the deviation and document it.

## What was done well

- **H4 closure is verbatim and locked**: `TestModuleContract.test_docstring_h4_remediation_sentence` whitespace-collapses and substring-matches the AC sentence — robust against line-wrap drift.
- **Single-source-of-truth discipline**: `_bm25_version_dir` confines the `f"v{N}"` literal; constants live in `bm25_indexer.py` (not `store.py`), matching the embedder/preamble pattern.
- **Atomic writes done right**: PID + UUID-suffixed tmp + `os.replace` + `try/finally` + `contextlib.suppress(OSError)`. Mirrors `preamble._write_preamble_json`. Order chosen carefully (text first, binary second) so a crash leaves a partial state the idempotent skip rebuilds.
- **`is_file()` not `exists()`** for the idempotent skip — closes the same class of bug E04_S03 M5 closed.
- **Threat 1 deferral marker** present and locked by `TestModuleContract.test_docstring_threat1_deferral`.
- **Empty-corpus raise**: D8 implemented with a clear `ValueError` and a regression test.
- **Stats logging mirrors `store-stats.jsonl`**: `_patched_bm25_stats_path` autouse fixture closes the F8/L4 pollution-prevention pattern from earlier milestones.
- **Test fixtures don't pollute `var/`**: every test monkey-patches `BM25_INDEX_ROOT` into `tmp_path`, no developer-checkout pollution.
- **No-fork policy honored**: `rank-bm25>=0.2` added directly; no patches, no vendoring.
- **Test surface is broad**: 14 tests across 8 classes, covering every AC plus partial-state, empty-corpus, atomic-write, and stats-key-ordering regressions.

## Recommended rectification order

1. **H1** — wire-up clarification. Either add the call in `write_chunks` or document the deferral with a TODO marker. Single line of code or one paragraph.
2. **M2** — empty-string `body_tokens` guard. One-line filter + a regression test.
3. **M4** — strengthen disjoint-vocabulary test to assert the *expected* decoy is top-1.
4. **M1** — add SHA-256 sidecar or TODO marker for the future loader to enforce.
5. **L3** — `corpus_version` non-negative validation.
6. **L4 / L5 / L2 / L1 / M3** — defer to housekeeping batches; flag in tech-debt log.

## Rectification status

**Phase 4 commit:** see `state.json` `rectification_commit` field.

| Finding | Severity | Status | Where fixed |
|---|---|---|---|
| H1 — no production caller | HIGH | **deferred-with-doc** | `ingest/bm25_indexer.py` module docstring "Production wire-up deferral (H1 from the E04_S04 critique)" paragraph documents that `write_chunks` does NOT auto-call `build_bm25_index` because per-batch builds would be wasteful and incorrect; the corpus driver (E07 or future) is the right caller. Manual-build instructions documented inline. |
| M1 — pickle defense not enforced | MEDIUM | **fixed (TODO marker)** | `ingest/bm25_indexer.py` module docstring TODO(E07) block names the loader's required ownership/world-writable check. Concrete control left to the consumer, not the writer. |
| M2 — empty-string `body_tokens` | MEDIUM | **fixed** | `ingest/bm25_indexer.py` body-token loop now skips both `None` and empty token lists; logs WARN per skipped chunk; `empty_chunks_skipped` counter recorded in stats. |
| M3 — atomic-write helpers duplicated | MEDIUM | **deferred (LOW-threshold)** | Acknowledged in `implementation-summary.md`; extraction is a separate housekeeping commit per F11 of E04_S02. No new instances introduced. |
| M4 — disjoint-vocabulary test weak | MEDIUM | **fixed** | `tests/test_bm25.py` `test_query_disjoint_vocabulary_does_not_match_target` now asserts `chunks[16]` (the cohomology decoy) IS top-1, not just `top != target`. |
| L1 — `f"v{` literal-scan brittleness | LOW | **deferred (LOW-threshold)** | Documented limitation; AST-based version is a future refinement. |
| L2 — sleep-based mtime delta | LOW | **fixed** | `tests/test_bm25.py` `test_partial_state_triggers_rebuild` now compares `st_ino` (atomic-replace yields a fresh inode); `time.sleep(0.01)` removed. |
| L3 — `corpus_version` not validated | LOW | **fixed** | `ingest/bm25_indexer.py` `build_bm25_index` now raises `ValueError` if `corpus_version` is not a positive int (excludes `bool` to mirror `CorpusVersionInfo.from_dict`). |
| L4 — `chunk_count=0` on skip is misleading | LOW | **fixed (documented convention)** | `BM25Stats` docstring now states "when skipped=True, count fields are 0 — aggregators MUST filter on skipped == False before averaging." Skipped-path stats explicitly pass `chunk_count=0, empty_chunks_skipped=0, paper_count=0`. |
| L5 — no `paper_count` in stats | LOW | **fixed** | `BM25Stats.paper_count` added; populated from the de-duplicated `paper_id` set built during the body-token loop (no extra LanceDB read needed). |

**Regression tests added in this rectification batch:**
- `TestQueryAccuracy.test_query_disjoint_vocabulary_does_not_match_target` — strengthened to assert `chunks[16].chunk_id` is top-1 (M4).
- `TestStatsLogging.test_stats_line_appended_on_build` — extended to assert `empty_chunks_skipped == 0` and `paper_count == 20` for the curated corpus (L4 + L5).
- `TestBM25StatsDataclass.test_to_dict_alphabetical_keys` — now expects 6 keys including `empty_chunks_skipped` and `paper_count` (L4 + L5 schema lock).
- `TestIdempotency.test_partial_state_triggers_rebuild` — switched to `st_ino` comparison (L2).

**Suite at rectification time:** 503 passed, 2 skipped, ruff clean.
