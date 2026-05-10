# E04_S01 Adversary Critique

## Executive Summary
- Verdict: **fix-then-proceed**. Schema, idempotency, and the 10-row count-rows acceptance criterion are correctly met. But three real defects sit on the seam: a security regression (no `_validate_paper_id` in `load_embed_record`), silent data corruption on within-list duplicate `chunk_id`s in `EmbedRecord`, and HNSW index failures that get swallowed as warnings rather than failing the write whose acceptance criterion claims they exist.
- Acceptance criterion AC3 ("HNSW indices exist on `embedding_stmt` and `embedding_proof` after a write") is technically defended only by the integration test running `tbl.list_indices()` on a 10-row dataset. A future LanceDB API drift in the keyword names (e.g. `m`→`hnsw_m`) would log a WARNING, complete the write with a stale `lancedb_version`, and leave production tables unindexed across every paper for an unknown duration. The test would fail loudly — but only when run, and the WARNING-and-continue policy still ships partial-index state to production.
- `_build_arrow_table` builds `stmt_lookup` and `proof_lookup` via dict comprehension. Two embedding rows with the same `chunk_id` in `chunk_ids_stmt` silently collapse to the second row's vector. `EmbedRecord.__post_init__` validates cross-list overlap but not within-list duplication. Production data path is exposed.
- `load_embed_record(paper_id)` does `EMBEDDINGS_DIR / paper_id` without calling `_validate_paper_id`. The embedder explicitly added this check in E03_S02 (commit context: "Closes F13: ... defense-in-depth"). The store regresses defense-in-depth by skipping it.
- `EmbedRecord` does not validate L2 normalization. The integration test author normalizes synthetically; a future caller passing un-normalized vectors silently degrades ANN ranking quality. The class invariant claim ("BGE-M3 produces L2-normalized vectors") is not enforced at the boundary.
- The `getattr(merge_result, "num_inserted_rows", 0) or 0` pattern masks API drift: a renamed attribute would silently log `rows_inserted=0` for every successful write — observability rot, not data loss, but sufficient to confuse future debugging.
- The brief's `kind` enumeration is informal; the schema accepts arbitrary strings. Out-of-band: not a critical fail. But `embedding_eq` is silently set to `None` for every row regardless of kind — a future `embedding_eq` bug in E10_S03 cannot be caught here.
- The on-disk path is `var/arxmcp/index/lancedb/chunks.lance/`, not the brief's literal `var/arxmcp/index/lancedb/chunks` — LanceDB appends `.lance`. This is a documentation drift, not a functional bug, but worth flagging.

## Severity calibration table
| Severity | Definition | Target rate |
|---|---|---|
| CRITICAL | data loss / security breach / broken invariant | rare |
| HIGH | wrong behavior on common path | low |
| MEDIUM | subtle correctness or missing test | moderate |
| LOW | style, naming, minor docs | as found |

## Findings

### CRITICAL

#### F1 — `load_embed_record` skips `_validate_paper_id`, regressing E03_S02 F13 fix
- **What**: `load_embed_record(paper_id)` constructs `paper_dir = EMBEDDINGS_DIR / paper_id` with no path-traversal validation. The embedder's `_paper_is_up_to_date` (commit prior, E03_S02 F13) explicitly added `_validate_paper_id(paper_id)` as defense-in-depth.
- **Why it matters**: Threat 1 in `08-security-observability-ops.md` — an LLM-generated `paper_id="../../../etc/passwd"` would let `load_embed_record` traverse outside `EMBEDDINGS_DIR`. The chunker validates at the public entry-point, but every other helper that interpolates `paper_id` into a path was hardened in E03_S02 to also validate. This new helper opens a fresh hole. The function is exported via `__all__` and intended to be a public API.
- **Where**: `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/store.py:118-127` (function entry; specifically line 129 where `paper_dir = EMBEDDINGS_DIR / paper_id` is constructed without prior validation).
- **Fix sketch**: Import `_validate_paper_id` from `ingest.chunker` at module top and call it at the top of `load_embed_record`. Mirror the embedder's `_paper_is_up_to_date` discipline (which the embedder.py docstring at line 624-628 explicitly cites as the closure of F13).

### HIGH

#### F2 — Within-list duplicate `chunk_id` in `EmbedRecord` silently overwrites embedding rows
- **What**: `_build_arrow_table` builds `stmt_lookup = {cid: embeddings.embedding_stmt[i] for i, cid in enumerate(embeddings.chunk_ids_stmt)}` and the symmetric `proof_lookup`. If `chunk_ids_stmt` contains the same `chunk_id` twice, the dict keeps only the second vector and the first is silently discarded. `EmbedRecord.__post_init__` validates cross-list overlap (line 198-203 of `schema.py`) and length-vs-shape, but does NOT check within-list duplication.
- **Why it matters**: A future bug in the per-paper NPZ writer (e.g. accidentally re-routing a chunk and appending a second row for the same chunk_id) would produce a corrupt LanceDB row whose `embedding_stmt` is whichever appeared last in the NPZ. The `chunk_id_set - embedded_set` missing-check at store.py:212 would still pass because `set` membership is unaffected by duplicates. This is the same class of silent-data-corruption bug that the existing cross-list check guards against — the within-list case is unprotected.
- **Where**: `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/store.py:200-207` (dict comprehension that silently collapses duplicates) and `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/schema.py:170-204` (`__post_init__` lacks within-list duplicate check).
- **Fix sketch**: Add `if len(set(self.chunk_ids_stmt)) != len(self.chunk_ids_stmt): raise ValueError("duplicate chunk_id in chunk_ids_stmt")` and the symmetric proof check inside `__post_init__`. One-line guard.

#### F3 — HNSW index failures are caught and logged but do not fail the write whose AC asserts indices exist
- **What**: `_create_indices` wraps every `create_index`/`create_scalar_index` call in a bare `except Exception` and logs at WARNING. If a future LanceDB version drift renames a kwarg (e.g. `m`→`hnsw_m`), every production write would silently skip indexing yet still increment `lancedb_version` and append a successful row to `store-stats.jsonl`. Acceptance criterion 3 ("HNSW indices exist on `embedding_stmt` and `embedding_proof` after a write") would be FALSE for production but the writer would not raise.
- **Why it matters**: The test asserts `list_indices()` includes the columns — but only on a 10-row synthetic test. In production, a silent skip means ANN searches fall back to brute-force scan over hundreds of thousands of vectors, latency balloons, and the only signal is a WARNING log line nobody reads. The implementer's docstring at store.py:30-32 frames this as deliberate ("rather than fail the whole write"), but the brief's AC says indices exist after a write — that's an invariant, not a best-effort.
- **Where**: `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/store.py:281-302` (try/except around both vector indices and the scalar index).
- **Fix sketch**: Bubble up the failure for HNSW vector indices (the AC-required ones) — let scalar-index failures stay as WARNING since they're a performance optimization, not correctness. Or: keep best-effort, but record the failure in `store-stats.jsonl` with an `index_failures: list[str]` field so the gap is observable structurally rather than only in unread logs.

#### F4 — `EmbedRecord` does not enforce L2 normalization; un-normalized vectors silently corrupt ANN results
- **What**: `EmbedRecord.__post_init__` validates shape and dtype but NOT that each row is L2-normalized to unit length. The store's docstring at line 276 ("BGE-M3 vectors are L2-normalized so l2 and cosine produce identical rankings") encodes this assumption but offers no enforcement. A future caller (or a regressed embedder) passing un-normalized vectors would silently produce wrong ANN rankings.
- **Why it matters**: BP1 / BP2 from `07-multi-agent-caching.md` says results must be deterministic for `(query, filters, k, corpus_version)`. ANN rank-order on un-normalized vectors with l2 distance differs from cosine in a way that does not fail any test — it just returns a different top-k. This invalidates the per-corpus result cache invariant. The integration test in this commit happens to normalize synthetic vectors at line 75 of `test_store.py`, so the test would pass even if `__post_init__` is silently dropped — meaning the test is not a regression guard for the invariant it relies on.
- **Where**: `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/schema.py:170-204` (post-init misses normalization check); `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/tests/test_store.py:75-86` (test silently masks the gap).
- **Fix sketch**: In `__post_init__`, after the dtype/shape checks, add `np.testing.assert_allclose(np.linalg.norm(self.embedding_stmt, axis=1), 1.0, atol=1e-3)` (and proof variant) when arrays are non-empty. Use `atol=1e-3` to tolerate float32 round-off from BGE-M3's pooling layer.

### MEDIUM

#### F5 — `getattr(merge_result, "num_inserted_rows", 0) or 0` masks API drift
- **What**: If a future LanceDB renames `num_inserted_rows` (already happened once in 0.30 with `table_names`→`list_tables`), `getattr` returns the default `0`, the `or 0` short-circuits, and `store-stats.jsonl` permanently records `rows_inserted=0` for every write — even after a real insert.
- **Why it matters**: The store-stats log is the single source of audit truth for which write produced which dataset version. An uncalibrated `rows_inserted=0` is silently broken observability, not data loss — but it defeats the purpose of having the field in the first place. Confirmed via local check (`MergeResult` in 0.30.2 has `version`, `num_inserted_rows`, `num_updated_rows`, `num_deleted_rows`, `num_attempts`).
- **Where**: `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/store.py:388-389`.
- **Fix sketch**: Use direct attribute access `merge_result.num_inserted_rows` so a rename surfaces as `AttributeError` at write time. If softening is needed for forward-compat, log a WARNING when the attribute is missing rather than silently zeroing.

#### F6 — Acceptance test does not exercise idempotency over a NEW chunk_id added on the second write
- **What**: `TestIdempotency.test_second_write_no_duplicates` writes the same 10 chunks twice and asserts `count_rows() == 10`. `test_second_write_updates_existing_row` writes ONE chunk twice. Neither covers the realistic ingest case: an initial write of N chunks, then a second write of N+M chunks where M are new and N are unchanged. `merge_insert(...).when_matched_update_all().when_not_matched_insert_all()` should produce N+M rows total — the test never asserts this.
- **Why it matters**: An incidental bug in the merge_insert chain (e.g. a `when_not_matched_insert_all` typo collapsed to `when_not_matched_skip`) would pass both existing tests but silently drop new chunks in production. The brief's "idempotent on duplicate chunk_id" criterion is met; the broader correctness of upsert semantics on mixed insert+update is not tested.
- **Where**: `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/tests/test_store.py:300-329` (only existing-row update is covered).
- **Fix sketch**: Add `test_mixed_insert_and_update`: write 5 chunks, then write the same 5 + 3 new ones, assert `count_rows() == 8` and that the 5 originals' bodies are unchanged.

#### F7 — `_build_arrow_table` empty-input fast-path uses `pa.Table.from_pylist([], schema=...)` but does not return through the ops-log path
- **What**: When `chunks=[]`, `_build_arrow_table` returns an empty Arrow table at store.py:194. Then `write_chunks` skips `merge_insert` due to `arrow_table.num_rows > 0` guard, but still proceeds to `_create_indices(tbl)` and `_append_store_stats(stats)`. On an empty first write, this calls `create_index` on an empty column — which the try/except swallows — and writes a stats line with `chunk_count=0, rows_inserted=0`. Net effect: an empty table created, indexes skipped (logged WARNING), stats line written. The table is now in the dataset and subsequent writes work, but the user has no idea their input was empty.
- **Why it matters**: Empty `chunks` is more likely a programmer bug (driver loaded zero chunks for a paper, perhaps a manifest read error) than a deliberate no-op. Silent acceptance of empty input is a smell.
- **Where**: `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/store.py:189-194` (silent empty fast-path) and `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/store.py:378-380` (skip-merge guard).
- **Fix sketch**: Either raise `ValueError("write_chunks called with empty chunks list")` at the entry of `write_chunks`, or log at WARNING with explicit "no-op write" annotation. Don't silently no-op.

#### F8 — Test fixture monkeypatches `STORE_STATS_PATH` but no test covers the unpatched path; pytest-xdist parallel runs might still race
- **What**: The autouse fixture `_patched_store_paths` uses `monkeypatch.setattr(store_mod, "STORE_STATS_PATH", tmp_path / "ops" / "store-stats.jsonl")`. Each test gets its own `tmp_path`. But the module-level `STORE_STATS_PATH` is still the production path on import — if any test runs WITHOUT this fixture (e.g. a new test in another file that imports `write_chunks`), the production `var/arxmcp/ops/store-stats.jsonl` gets polluted on a developer machine.
- **Why it matters**: This is exactly the kind of silent test-time side effect that bites once it's been merged. The fixture lives in `test_store.py` only and is not shared via `conftest.py`. Future tests that exercise the writer without this fixture will write to the developer's checkout's `var/` tree.
- **Where**: `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/tests/test_store.py:111-123` (autouse fixture scoped to file only).
- **Fix sketch**: Move the `STORE_STATS_PATH` patch into a `conftest.py` autouse fixture at the `tests/` package level, or have `write_chunks` accept a `stats_path: Path | None = None` kwarg defaulting to `STORE_STATS_PATH` so tests pass an explicit path rather than monkeypatching module state.

#### F9 — Brief literally specifies path `var/arxmcp/index/lancedb/chunks` but actual on-disk path is `var/arxmcp/index/lancedb/chunks.lance/`
- **What**: The brief's title and acceptance criterion say "Table created at var/arxmcp/index/lancedb/chunks". Verified locally: LanceDB 0.30.2 creates the table at `var/arxmcp/index/lancedb/chunks.lance/` (note the `.lance` suffix). This is LanceDB's internal naming convention.
- **Why it matters**: A reader who follows the brief literally and `Path("var/arxmcp/index/lancedb/chunks").exists()` will see False. Documentation drift between the brief, the docstring, and the actual filesystem layout. The first acceptance criterion is technically not met as stated.
- **Where**: `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/store.py:5` (docstring), `:74` (path constant), and the brief's acceptance criterion.
- **Fix sketch**: Either change docstring/comments to reflect `chunks.lance/` reality, or add a one-line note that the directory is `<dataset_dir>/<table_name>.lance/` per LanceDB's storage layout. Tests already use `db.list_tables()` and `db.open_table()` correctly — they don't path-stat — so the code is fine; only the brief's-language docstring is misleading.

#### F10 — `kind` column accepts arbitrary strings; no schema-level enum constraint matches the brief's enumeration
- **What**: The brief says `kind` is a string but elsewhere lists `stmt`, `proof`, `section`, `definition`, `lemma` etc. The schema does not constrain values. The chunker emits a closed set, but a future driver bug could insert `"theroem"` (typo) or empty string `""` and the write would succeed.
- **Why it matters**: An invalid `kind` poisons the dual-encoding routing rule and breaks downstream search behavior silently. PyArrow does not natively support enum types, but a runtime guard inside `_build_arrow_table` against an `_ALLOWED_KINDS` set would catch typos at write time.
- **Where**: `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/store.py:230` (kind written verbatim, no validation).
- **Fix sketch**: Either define `_ALLOWED_KINDS = frozenset({"stmt","proof","section","definition","lemma","proposition","corollary","remark","theorem"})` at module top and `assert chunk.kind in _ALLOWED_KINDS` inside `_build_arrow_table`, or add a comment that `kind` validation is the chunker's responsibility (already true) and the store trusts upstream.

### LOW

#### F11 — `_atomic_write_json` is dead code in `store.py`
- **What**: `_atomic_write_json` is defined at store.py:417-435 but no caller exists in the new code (verified via repo-wide grep). The implementation summary acknowledges this at line 70.
- **Why it matters**: Dead code in a single-purpose module is rot. If a future side-file is needed, the helper can be lifted from `embedder.py` or `preamble.py` (both have similar discipline). Keeping it dead-but-discoverable doesn't pay rent.
- **Where**: `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/store.py:417-435`.
- **Fix sketch**: Delete the function. If it's wanted later, copy from preamble.py.

#### F12 — `lancedb_path: str | Path | None = None` defaulting to `DEFAULT_LANCEDB_PATH` invites accidental writes to production directory
- **What**: A developer who calls `write_chunks(chunks, embed)` from a debug REPL with no `lancedb_path` will write to the repo's actual `var/arxmcp/index/lancedb/` path. There's no warning or `--dry-run`-style safety.
- **Why it matters**: The argument is documented in the docstring but the default is silent. An interactive notebook session could accidentally pollute the developer's checkout-local LanceDB.
- **Where**: `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/store.py:330-334`.
- **Fix sketch**: Either drop the default (require explicit `lancedb_path`) or log INFO at write time with the resolved path so developers see `using lancedb_path=/absolute/path/var/arxmcp/index/lancedb`.

#### F13 — Docstring at `store.py:24-25` claims `num_partitions=1` is auto-promoted, but does not verify or test that claim
- **What**: The docstring states "LanceDB IVF-HNSW with `num_partitions=1` (the auto-promoted value for small corpora) does NOT require the 256-row IVF training threshold". This is asserted as fact based on Researcher B's reading. Verified in local test (10-row + create_index works), but not asserted in test code.
- **Why it matters**: If LanceDB raises the auto-promotion threshold in a future version, the 10-chunk integration test will start failing with an obscure IVF training error, and debugging will require re-deriving the threshold rule.
- **Where**: `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/store.py:24-26`.
- **Fix sketch**: Either add an explicit `num_partitions=1` kwarg to `create_index` so the assumption is pinned (defensive), or document the version range under which the auto-promotion holds.

#### F14 — `WriteStats.indices_created` schema lists strings like `"hnsw:embedding_stmt"` and `"scalar:paper_id"` but the field is unstructured
- **What**: `indices_created: list[str]` is a heterogeneous string list. Programmatic consumers of `store-stats.jsonl` (e.g. an ops dashboard) cannot easily filter "did the HNSW index for embedding_stmt succeed?" without parsing strings.
- **Why it matters**: Cosmetic, but `07-multi-agent-caching.md` BP1 emphasizes byte-stable, alphabetical, deterministic output. A structured field (`{"hnsw_stmt": True, "hnsw_proof": True, "scalar_paper_id": True}`) would be more machine-readable and follows the canonicalization discipline.
- **Where**: `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/store.py:91, 100`, `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/store.py:103`.
- **Fix sketch**: Replace `indices_created: list[str]` with a `dict[str, bool]` or structured list of `{"name": ..., "column": ..., "type": ...}` dicts. Sort keys at serialization time (already done via `sort_keys=True`).

#### F15 — Cache byte-stability: `WriteStats.to_dict` keys are not alphabetical at construction
- **What**: `WriteStats.to_dict` returns keys in source-literal order (chunk_count, elapsed_s, indices_created, lancedb_version, rows_inserted, rows_updated). The `_append_store_stats` writer calls `json.dumps(..., sort_keys=True)` so the on-disk bytes ARE sorted — but the dict itself is not. Borderline LOW: BP1 (07-multi-agent-caching.md) requires alphabetical serialization, which is satisfied by `sort_keys=True`. Still, the source-literal order is not alphabetical (`elapsed_s` precedes `indices_created` precedes `lancedb_version` ... actually that's alphabetical). Closer reading: it IS alphabetical. False alarm — but worth verifying.
- **Why it matters**: Verified the keys ARE alphabetical (chunk_count, elapsed_s, indices_created, lancedb_version, rows_inserted, rows_updated). Clean. Only flagging because the audit was non-trivial.
- **Where**: `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/store.py:99-107`.
- **Fix sketch**: No fix needed; clean. Filed as LOW for traceability.

### Axis-by-axis sweep (axes not surfaced as findings)

- **Math fidelity**: The store inserts `chunk.body_text` and `chunk.body_tokens` verbatim into Arrow utf8 columns. No modification, no normalization, no truncation. Clean.
- **MCP 2025-06-18 spec compliance**: N/A — this is the storage layer; no MCP server surface is touched in this commit. Clean.
- **Local-first + Docker constraint**: `lancedb.connect(str(target_path))` resolves to the local filesystem path. No remote `lancedb+s3://` or `lancedb+http://` URIs are introduced. The `var/arxmcp/index/lancedb/` default is a relative path under the repo root (resolved via `REPO_ROOT`). Clean.
- **Tier sequencing**: This milestone is Tier 0; depends only on E02_S04 (chunker) and E03_S01 (embedder), both shipped. No reverse dependency. Clean.
- **No-fork policy**: `lancedb` and `pyarrow` added as PyPI deps with version pins (`>=0.6` and `>=14.0`). No vendored copies, no submodules, no `git+...` URLs. Clean.

## What was done well
- Schema field declaration matches the brief's column order verbatim — useful for byte-stability audits.
- `EmbedRecord` cross-list overlap check (`stmt_set & proof_set`) is exactly the kind of invariant guard that the F4-from-E03_S02 retro called for.
- D7 missing-chunk validation in `_build_arrow_table` is a clear `ValueError` with sorted chunk_id list — debuggable failure mode.
- D8 `body_tokens=None` raise is unambiguous; refused the silent-coerce-to-empty-string path.
- The `pa.schema(` scan test (`TestSingleSourceOfTruth.test_store_imports_schema_does_not_redefine`) is a genuine source-of-truth guard — simple but high-value.
- The `= 1024` literal scan in `TestSingleSourceOfTruth.test_no_stray_1024_literal_in_new_files` enforces D4 at test time.
- `merge_insert(on="chunk_id").when_matched_update_all().when_not_matched_insert_all()` is the correct shape for idempotent upsert.
- Real LanceDB on `tmp_path` (no mocking) — the integration tests exercise the actual library, surfacing real API drift sooner than mocks would.
- Defensive `getattr(tables_obj, "tables", tables_obj)` handles the lancedb 0.30 `ListTablesResponse` return-type drift gracefully.
- The `embedder.py` deps (`EMBEDDING_DIM`, `EMBEDDINGS_DIR`, etc.) are imported via named symbol — no string-path duplication.

## Recommended rectification order
1. F1 (CRITICAL — security regression; one-line fix)
2. F2 (HIGH — data corruption guard; one-line fix in `__post_init__`)
3. F3 (HIGH — invariant violation under API drift; small refactor)
4. F4 (HIGH — silent ANN ranking corruption; one assert per array)
5. F5 (MEDIUM — observability rot; direct-attr access)
6. F6 (MEDIUM — missing test for mixed insert+update)
7. F7 (MEDIUM — silent empty-input fast-path)
8. F8 (MEDIUM — test fixture scope risks production-tree pollution)
9. F9 (MEDIUM — docstring/brief literal-path drift)
10. F10 (MEDIUM — `kind` validation gap)
11. F11 (LOW — dead code)
12. F12 (LOW — production-default risk)
13. F13 (LOW — undocumented LanceDB version assumption)
14. F14 (LOW — unstructured ops field)
15. F15 (LOW — verification-only, no fix needed)

## Rectification status

Phase 4 ran in the orchestrator's main session. The CRITICAL + all 3
HIGH + 6 of 6 MEDIUM + 4 of 5 LOW findings landed in a single
`rect(E04_S01)` commit. F12 deferred (low-impact production-default
risk) and F15 invalidated (the critic acknowledged it was clean).

| ID | Severity | Status | Notes |
|---|---|---|---|
| F1 | CRITICAL | **fixed** in `rect(E04_S01)` | `load_embed_record` now calls `_validate_paper_id` before any path concat. Regression: `TestPaperIdValidation.test_load_embed_record_rejects_path_traversal` covers `../`, malformed IDs, and empty strings. |
| F2 | HIGH | **fixed** in `rect(E04_S01)` | `EmbedRecord.__post_init__` now raises on within-list duplicates (Counter-based identification of which chunk_id appeared twice). Regression: `TestWithinListDuplicateRejected` covers both stmt and proof lists. |
| F3 | HIGH | **fixed** in `rect(E04_S01)` | HNSW vector-index failures bubble up as hard errors. Empty columns (zero non-null rows) get a structured `False` in the `indices_created` dict via the new `_count_non_null` pre-check — distinguishes "legitimate empty column" from "API drift," resolving the AC vs. small-corpus tension. |
| F4 | HIGH | **fixed** in `rect(E04_S01)` | `EmbedRecord.__post_init__` validates `np.linalg.norm(rows, axis=1) ≈ 1.0 ± 1e-3` for both columns. Reorder of validations puts ID-set invariants (duplicate, overlap) BEFORE the L2-norm check so domain-validity errors take priority. Regression: `TestL2NormEnforcement` (4 tests). |
| F5 | MEDIUM | **fixed** in `rect(E04_S01)` | Direct attribute access on `MergeResult` (`int(merge_result.num_inserted_rows)` / `num_updated_rows`); a future LanceDB rename surfaces as `AttributeError` at write time, not as silently-zeroed observability. |
| F6 | MEDIUM | **fixed** in `rect(E04_S01)` | `TestMixedInsertAndUpdate.test_first_n_then_n_plus_m` writes 5 chunks, then 5+3, asserts row count == 8 — the realistic upsert path the previous tests didn't cover. |
| F7 | MEDIUM | **fixed** in `rect(E04_S01)` | `write_chunks` logs INFO when called with empty `chunks` so the no-op state is observable in logs rather than silent. Tests for the empty-input path are out of scope (existing tests don't pass empty). |
| F8 | MEDIUM | **fixed** in `rect(E04_S01)` | The `_patched_store_paths` autouse fixture moved from `tests/test_store.py` into the new `tests/conftest.py`, so any future test in any file that exercises `ingest.store` is auto-protected from polluting the developer's `var/arxmcp/ops/store-stats.jsonl`. |
| F9 | MEDIUM | **fixed** in `rect(E04_S01)` | Module docstring updated to acknowledge LanceDB's `<table>.lance/` on-disk layout: "LanceDB's on-disk layout puts the actual files under `var/arxmcp/index/lancedb/chunks.lance/`". |
| F10 | MEDIUM | **fixed** in `rect(E04_S01)` | `_ALLOWED_KINDS = frozenset({...})` defined at module top; `_build_arrow_table` raises if `chunk.kind` is not in the set. Regression: `TestKindValidation.test_invalid_kind_raises` and `test_all_chunker_kinds_pass` (which scans the chunker's `_THEOREM_ENV_KINDS` to catch a future chunker change that adds a new kind without updating the allowed set). |
| F11 | LOW | **fixed** in `rect(E04_S01)` | `_atomic_write_json` deleted; comment notes that future side-files should copy from `preamble._write_preamble_json`. Now-unused imports (contextlib, os, uuid) also removed. |
| F12 | LOW | **deferred** | Production-default risk on `lancedb_path=None` — kept the default for ergonomics; a future ingest-driver milestone should require explicit paths. |
| F13 | LOW | **fixed** in `rect(E04_S01)` | `num_partitions=1` pinned explicitly on `create_index` so a future LanceDB change to the auto-promotion threshold can't break the small-corpus test. |
| F14 | LOW | **fixed** in `rect(E04_S01)` | `WriteStats.indices_created` is now `dict[str, bool]` keyed by canonical name (`hnsw_stmt`, `hnsw_proof`, `scalar_paper_id`). Regression: `TestStructuredIndicesCreated`. |
| F15 | LOW | **invalidated** | The critic verified WriteStats keys ARE alphabetical and noted the finding was filed for traceability only. No fix needed. |

**Test count:** 28 → 39 store tests (11 new regression guards: path-traversal validation, within-list duplicates × 2, L2-norm enforcement × 4, mixed insert+update, kind validation × 2, structured indices_created). Full suite: 446 passed, 2 skipped, ruff clean.
