# E04_S02 Adversary Critique

## Executive Summary
- Verdict: **fix-then-proceed**. Implementation lands every brief AC, tests pass, and the MVCC handshake docstring is verbatim — but several latent issues will bite the moment E06 wires up real concurrency.
- Most consequential gap: `open_chunks_table` returns a fresh `tbl` *object* per call but the underlying `lancedb.connect()` may share a `Connection` (and via it a Table) across calls. `tbl.checkout()` mutates in place. Two concurrent calls with different `version=` arguments may stamp on each other. This is asserted in the docstring ("each call opens a fresh table handle") but is not test-verified.
- Test for the canonical AC ("write 10 (v1), 5 more (v2), checkout(v1).count==10 / checkout(v2).count==15") is satisfied, but it opens `tbl_a` BEFORE opening `tbl_b`, then asserts on `tbl_a` BEFORE opening `tbl_b`. The opposite ordering — open both, then assert — would catch the shared-handle hazard. As written the test would silently pass even if the handles are not independent.
- `except Exception` in the version-not-found path masks `OSError` / `RuntimeError` / `KeyboardInterrupt` (the last is a `BaseException`, so safe — but `OSError` for disk-full or permission denied is reported as "LanceDB version N is not accessible" which is misleading).
- `test_no_symlinks_under_lancedb_root` is robust — `rglob("*")` over a populated LanceDB directory returns dozens of entries — but the test relies on `write_chunks` having actually written something. If `write_chunks` is ever changed to lazy-create on first read, the test passes vacuously. A `> 0` assertion on the number of inspected entries would harden it.
- The `__import__("tests.test_store", fromlist=["_make_chunk"])._make_chunk(...)` invocation in `test_checkout_pre_and_post_second_write` is awkward and circumvents the existing module-level `from tests.test_store import _make_corpus, _make_synthetic_embeddings` block at the top of the file. There is no reason `_make_chunk` should not be in that import list.
- Threat-1 path-traversal: implementation summary explicitly defers this to E06. That's defensible IF and ONLY IF E06's tool-input boundary actually enforces it. The current state ships a public API that accepts an unvalidated `str | Path` from any caller. Worth a docstring `WARNING` (not just a note in the Threat-1 paragraph).
- Default-path inconsistency: `ingest.store.write_chunks(lancedb_path=None)` defaults to `DEFAULT_LANCEDB_PATH`. `server.corpus.open_chunks_table(lancedb_path)` has NO default and NO `DEFAULT_LANCEDB_PATH` import. Asymmetry: the writer can be called with no args; the reader cannot. Minor, but a likely future paper-cut.

## Severity calibration table
| Severity | Definition | Target rate |
|---|---|---|
| CRITICAL | data loss / security breach / broken invariant | rare |
| HIGH | wrong behavior on common path | low |
| MEDIUM | subtle correctness or missing test | moderate |
| LOW | style, naming, minor docs | as found |

## Findings

### CRITICAL

(none)

### HIGH

#### F1. Shared-table-handle hazard between concurrent `open_chunks_table` calls is asserted but not test-verified
- **What**: The module docstring (server/corpus.py:26-32) and function docstring (server/corpus.py:83-87) both claim "each call opens a fresh table handle" so concurrent callers get independent pinned views. But `lancedb.connect(path)` may return a cached Connection (LanceDB documents internal connection caching by URI), and a cached Connection's `open_table()` MAY return the same `Table` object across calls. Since `tbl.checkout(N)` mutates in place, two callers asking for `version=v_a` and `version=v_b` may stamp on each other's view. Implementation has no test that opens v_a and v_b *interleaved* and confirms each handle still returns its own count.
- **Why it matters**: The whole point of MVCC is that two readers can independently pin to different versions. If LanceDB internally caches the table, the docstring's promise is wrong, and an MCP server caching multiple per-version handles (E06) would silently see all of them collapse to whichever version was checked-out last. This breaks the canonical MVCC invariant the milestone exists to provide.
- **Where**: `server/corpus.py:107-108` (the `db = lancedb.connect(...)` + `db.open_table(...)` lines) and `tests/test_mvcc.py:99-108` (the test that opens both handles sequentially but doesn't interleave).
- **Fix sketch**: Add a test `test_two_handles_with_different_versions_are_independent` that opens `tbl_a = open_chunks_table(p, v_a)`, opens `tbl_b = open_chunks_table(p, v_b)`, then asserts `tbl_a.count_rows() == 10` AND `tbl_b.count_rows() == 15` AND `tbl_a.version == v_a` AND `tbl_b.version == v_b`. If the test fails on lancedb 0.30.x, either change the implementation to disable connection caching (`lancedb.connect(path, read_consistency_interval=...)` or open via a fresh `LanceDataset` / `lance.dataset(...)`) or document the constraint and require callers to serialize.

#### F2. The `except Exception` in version-not-found path swallows real I/O errors
- **What**: `server/corpus.py:113` catches `Exception` and re-raises everything as `ValueError("LanceDB version N is not accessible")`. If the underlying call raises `OSError` (disk full, permission denied, file vanished mid-call) or `RuntimeError` (LanceDB internal panic), the user sees a misleading "version not accessible" error pointing at the wrong root cause.
- **Why it matters**: Triage friction. A disk-full incident reported as "version 3 is not accessible (live tip is 5)" sends ops down the wrong path. Per `08-security-observability-ops.md` the project values clear failure modes; this masks them.
- **Where**: `server/corpus.py:113`.
- **Fix sketch**: Narrow the `except` to the specific LanceDB exception types that signal "version doesn't exist" — empirically these are `ValueError` and lancedb's `LookupError`/`KeyError` family. Let `OSError` and `RuntimeError` propagate. A safe implementation: `except (ValueError, LookupError, KeyError) as exc:` for the re-wrap path.

#### F3. Default-path asymmetry: writer accepts `None`, reader does not
- **What**: `ingest.store.write_chunks(lancedb_path=None)` falls back to `DEFAULT_LANCEDB_PATH` (ingest/store.py:482). `server.corpus.open_chunks_table(lancedb_path)` has no default and no `DEFAULT_LANCEDB_PATH` import. Callers must hard-code or re-import the path.
- **Why it matters**: Couples every reader to knowledge of where the LanceDB lives. The MCP server (E06) and eval harness (E05) will both need to read from the same default path the writer uses; making each of them re-derive `var/arxmcp/index/lancedb` is fragile and violates the single-source-of-truth pattern the rest of the codebase observes (`CHUNKS_TABLE_NAME`, `BGE_M3_COMMIT_SHA`).
- **Where**: `server/corpus.py:59-60` (signature) vs `ingest/store.py:452,482` (writer default).
- **Fix sketch**: Either (a) import `DEFAULT_LANCEDB_PATH` from `ingest.store` (or hoist it to a config module to avoid `server` importing `ingest`) and default to it, or (b) explicitly document why the reader requires an explicit path. Option (a) is preferred — make the contract symmetric.

### MEDIUM

#### F4. The MVCC test would silently pass even if the two handles share state
- **What**: `tests/test_mvcc.py:99-108` opens `tbl_a`, asserts `tbl_a.count_rows() == 10`, THEN opens `tbl_b` and asserts `tbl_b.count_rows() == 15`. With this ordering, even if `tbl_a` is invalidated when `tbl_b` is opened, the `tbl_a` assertion has already fired. This test does NOT verify the canonical MVCC invariant of two independent pinned views.
- **Why it matters**: The brief AC is "checkout(v1).count_rows AND checkout(v2).count_rows differ." The interleaved-then-asserted form is the only one that actually proves both handles remain pinned.
- **Where**: `tests/test_mvcc.py:99-108`.
- **Fix sketch**: Reorder: open both handles first, THEN assert both counts. Equivalently, add a sibling test as in F1.

#### F5. `test_no_symlinks_under_lancedb_root` may pass vacuously if the write path changes
- **What**: `tests/test_mvcc.py:201-204` walks `(tmp_path / "lancedb").rglob("*")` and asserts no `is_symlink()`. If `write_chunks` is ever refactored to be lazy-on-read (or fails before creating files), `rglob` returns empty and the test passes without inspecting a single entry.
- **Why it matters**: AC4 ("no symlinks under var/arxmcp/index/lancedb/") needs a positive enforcement signal. Defensive tests should prove they actually inspected something.
- **Where**: `tests/test_mvcc.py:200-204`.
- **Fix sketch**: Collect the rglob results into a list, assert `len(entries) > 0` first, then iterate and check `is_symlink()`.

#### F6. `test_invalid_version_raises_value_error` couples to implementation message text
- **What**: `tests/test_mvcc.py:127` matches `"not accessible"` — that's the implementation's own error message, not LanceDB's. If a future rewrite changes the wording (e.g. "unknown LanceDB version"), the test breaks even though behavior is identical.
- **Why it matters**: Non-load-bearing message text shouldn't be an AC. Test brittleness over an irrelevant axis.
- **Where**: `tests/test_mvcc.py:127`, paired against `server/corpus.py:121-125`.
- **Fix sketch**: Match a stable substring that's part of the API contract (e.g. the literal `"version"` or the requested integer `999_999` interpolated into the message). Alternatively pin both ends: assert the message contains `"999999"` (the requested version).

#### F7. `test_writes_against_checked_out_table_raise` matches a generic `ValueError`
- **What**: `tests/test_mvcc.py:180-181` uses `pytest.raises(ValueError)` to catch the LanceDB write-guard error. LanceDB's exception type for "table cannot be modified when checked out" may be a `ValueError` subclass today, but lancedb releases have shifted these to `RuntimeError` or a custom `lance.error.LanceError` in the past. The test docstring even acknowledges this ("the exact subclass may shift across lancedb releases").
- **Why it matters**: The brittleness is acknowledged but not mitigated. If LanceDB reclassifies the error, the test fails despite correct behavior.
- **Where**: `tests/test_mvcc.py:180-181`.
- **Fix sketch**: Catch a wider net: `with pytest.raises((ValueError, RuntimeError, Exception)):` — but at that point assert `"checked out" in str(exc)` to confirm it's the right error. Or pin lancedb harder in `pyproject.toml` (which the synthesis explicitly declined).

#### F8. `_make_chunk` import indirection is awkward and inconsistent
- **What**: `tests/test_mvcc.py:86-90` uses `__import__("tests.test_store", fromlist=["_make_chunk"])._make_chunk(...)` to access a helper. The same file already does `from tests.test_store import (_make_corpus, _make_synthetic_embeddings)` at line 34-37. Why not add `_make_chunk` to that import?
- **Why it matters**: Confuses readers. Looks like there's a circular-import or scoping reason for the indirection — there isn't.
- **Where**: `tests/test_mvcc.py:34-37` and `tests/test_mvcc.py:86-90`.
- **Fix sketch**: Add `_make_chunk` to the existing import block; replace the `__import__` call with a direct invocation.

#### F9. Threat-1 path-validation deferral lacks a tracker / WARNING
- **What**: Implementation summary and module docstring (server/corpus.py:41-46) both note that path validation is deferred to E06's tool-input layer. There's no `WARNING:` block in the function docstring, no `# TODO(E06):` marker in the code, and no test covering the deferred case.
- **Why it matters**: If E06 forgets to wire path validation, this function silently accepts a `lancedb_path="../../etc/passwd"` from any caller. The defer is reasonable but should be tracked.
- **Where**: `server/corpus.py:59-105` (no warning in the docstring); also the implementation summary explicitly says "Path validation (Threat 1) is deferred to E06" — but no codebase-side TODO or test marker exists.
- **Fix sketch**: Add a `.. warning::` block to the docstring and a `# TODO(E06): enforce path validation per Threat 1` comment near `Path(lancedb_path)`. Or, even better, accept only a config-derived `Path` (typed as a sentinel `LanceDBPath = NewType('LanceDBPath', Path)`) so callers can't accidentally pass user input.

#### F10. `version=None` path differs subtly from explicit-latest path — no test asserts equivalence
- **What**: When `version is None`, the function returns the `tbl` from `db.open_table()` directly. When `version=` is the live tip integer, the function additionally calls `tbl.checkout(N)`. These produce semantically equivalent handles in lancedb 0.30.2 (live-tip checkout is a no-op), but no test asserts they behave identically.
- **Why it matters**: The implementation summary claims `version=None` "uses the same function for both pinned and live-tip access" — but the code paths diverge. A future LanceDB change to checkout semantics could expose the divergence.
- **Where**: `server/corpus.py:110-125`.
- **Fix sketch**: Add `test_checkout_at_live_tip_equals_checkout_none` — write once, capture `v`, open with `version=v`, open with `version=None`, assert both `count_rows()` and `version` match.

#### F11. Concurrent-writer race window between `merge_insert` and `_create_indices`
- **What**: The brief's comment in `ingest/store.py:528-534` notes that `tbl.version` is the post-index version. But between `merge_insert` (line 506) and `_create_indices` (line 523), a concurrent writer-B could land its own merge_insert. Then writer-A's `tbl.version` reads writer-B's version, not writer-A's own post-index version. Writer-A logs writer-B's integer to `store-stats.jsonl` as if it were writer-A's own.
- **Why it matters**: Concurrent ingestion is plausible (two `write_chunks` calls in different processes hitting the same dataset). The store-stats log becomes corrupted as a chronology. More importantly: writer-A's caller pins to writer-B's integer, missing writer-A's just-written rows entirely.
- **Where**: `ingest/store.py:506-535`. The race window is implementation-wide rather than at any single line.
- **Fix sketch**: Either (a) document that `write_chunks` is single-writer-only and add a filesystem-level lock (a flock on `lancedb_path / ".write-lock"`), or (b) capture the version *before* and *after* and report both. The synthesis claims "LanceDB serializes writers at the dataset level" but that's about ATOMICITY, not the read-after-merge race in the writer's own code path. Worth surfacing in the docstring at minimum.

#### F12. The connection-cost concern raised in research synthesis is not addressed in the API surface
- **What**: Research synthesis open-question: "Should `open_chunks_table` connect to the LanceDB DB on every call or cache the connection?" Implementation chose every-call, deferring caching to E06. But the public API does NOT expose any caching primitive — E06 has to either re-implement the connect/open/checkout sequence externally or build its own LRU on top.
- **Why it matters**: For an MCP server handling 10+ search_papers/sec, every call paying ~ms-scale `lancedb.connect` cost adds 10-100ms latency overhead per second. The API as shipped offers no escape valve. E06 will end up with two implementations: the function in `corpus.py` and a parallel cached version.
- **Where**: `server/corpus.py:59-133`. Whole API surface.
- **Fix sketch**: Either (a) split into `_open_chunks_table_uncached(path, version)` and a `@functools.lru_cache`-decorated `open_chunks_table(path, version)` wrapper, or (b) document the API as "uncached primitive — see E06 for the caching layer." The current docstring says "callers that want to cache should cache the *returned* handle" but that conflicts with the in-place-mutation warning: caching a returned handle then calling `checkout(N+1)` on it would invalidate every cached pin to ≤N.

### LOW

#### F13. `open_chunks_table` return type annotated as `object` rather than `lancedb.table.Table`
- **What**: `server/corpus.py:62` annotates the return as `-> object`. The research synthesis sketch (line 88) used `"lancedb.table.Table"` (string-quoted). Implementation regressed to bare `object`, removing IDE-completion support for callers.
- **Why it matters**: Callers see no type info; downstream `mypy` / pyright treat results as untyped.
- **Where**: `server/corpus.py:62`.
- **Fix sketch**: Use `"lancedb.table.Table"` as a forward-ref string (lazy-import-safe). Or import `TYPE_CHECKING` block.

#### F14. The function docstring's exception block says ValueError "is re-raised with a clearer message" — but the catch is `except Exception`, not `except ValueError`
- **What**: `server/corpus.py:90-96` documents `ValueError` as "underlying LanceDB exception is re-raised with a clearer message." But the actual catch (line 113) is `except Exception` — far broader. Docstring under-promises and over-catches.
- **Why it matters**: Docstring drift makes future maintenance error-prone.
- **Where**: `server/corpus.py:90-96` and `server/corpus.py:113`.
- **Fix sketch**: Either narrow the `except` (per F2) or update the docstring to honestly say "any LanceDB exception is re-raised as ValueError."

#### F15. `live_version = getattr(tbl, "version", "?")` — sentinel `"?"` is fragile in the error string
- **What**: `server/corpus.py:120` uses `"?"` as a string sentinel when `tbl.version` is unavailable. The error message then reads "live tip is ?" which is awkward and would interpolate `'?'` quoted in some logging configs.
- **Why it matters**: Trivial cosmetic but the sentinel is stringly-typed and `getattr(tbl, "version", None)` would let the f-string render as `None` more naturally.
- **Where**: `server/corpus.py:120-124`.
- **Fix sketch**: `live_version = getattr(tbl, "version", None)` and let the f-string render `None` directly.

#### F16. Module docstring duplicates AC5 sentence in two places (writer + reader); risk of drift
- **What**: The verbatim AC5 sentence "No symlink swaps. LanceDB version int IS the corpus_version. Writers use the current dataset; readers call dataset.checkout(version=N)." appears in both `ingest/store.py:44-47` and (slightly reformatted) `server/corpus.py:5-8`. Tests assert it in `ingest/store.py` only (`TestDocstringContract`). If the reader-side phrasing drifts (e.g. someone fixes the slight reformatting), the test won't catch it.
- **Why it matters**: Single-source-of-truth applies to docstrings too. The brief AC5 references `ingest/store.py` specifically, so this is OK strictly, but the duplication is a future-drift hazard.
- **Where**: `ingest/store.py:44-47` and `server/corpus.py:5-8`.
- **Fix sketch**: Either centralize the constant as `CORPUS_MVCC_HANDSHAKE_DOC = "..."` and reference it from both, or extend the test to assert the sentence appears in both modules. Lowest-risk fix: extend the existing `TestDocstringContract` test to also assert the sentence appears in `server.corpus.__doc__`.

## What was done well
- Verbatim AC5 docstring sentence landed in `ingest/store.py:44-47` and is enforced by `TestDocstringContract` with whitespace-collapsed substring matching — robust to wrapping changes.
- The post-index vs post-merge `tbl.version` decision (D2) is correctly defended in the docstring AND the inline comment at `ingest/store.py:528-534`. The reasoning (indexed ANN at the pinned version) is sound and resolves the Sonnet-A/Sonnet-B disagreement convincingly.
- Single-source-of-truth scan (`TestSingleSourceOfTruth`) catches both string variants of `"chunks"` AND verifies object identity via `is` — strong guard.
- Live-tested API: research synthesis explicitly notes the implementer ran a small experiment against lancedb 0.30.2 to verify `tbl.checkout` semantics rather than going from documentation.
- Lazy-import of `lancedb` (server/corpus.py:98) follows the existing project discipline from `ingest.store`.
- No `pyproject.toml` change — milestone is pure code + tests, no dependency surface.
- Test naming is descriptive and maps cleanly to the AC table in the implementation summary.
- `Path.exists()` precondition gives a clear `FileNotFoundError` instead of an opaque LanceDB internal error — good DX choice.
- Logger debug call (server/corpus.py:127-132) records both pinned and live-tip versions — useful for ops correlation.
- Module docstrings (server/corpus.py:1-47) explain the rationale for the writer/reader split and the in-place-mutation gotcha — future readers don't need to spelunk lancedb internals to understand the design.

## Recommended rectification order
1. **F1** — add interleaved test that opens two handles at different versions and asserts both stay pinned. If the test fails, escalate to a CRITICAL implementation fix.
2. **F4** — reorder the canonical MVCC test to open both handles first, then assert (cheap; reduces F1 risk surface).
3. **F11** — document the writer-side race window explicitly OR add a write-lock.
4. **F2** — narrow `except Exception` to the right LanceDB exception types.
5. **F3** — add `DEFAULT_LANCEDB_PATH` symmetry between writer and reader.
6. **F12** — clarify caching contract in the docstring; consider exposing `_uncached` primitive for E06.
7. **F9** — add `WARNING` block + `TODO(E06)` for path validation.
8. **F10** — add equivalence test for `version=None` vs explicit-latest.
9. **F8** — fix the awkward `__import__` call in `tests/test_mvcc.py:86`.
10. **F5** — assert `len(rglob_entries) > 0` before iterating in `test_no_symlinks_under_lancedb_root`.
11. **F6**, **F7** — relax test brittleness on message text and exception subclass.
12. **F13**, **F14**, **F15**, **F16** — cosmetic / docstring fixes.

## Rectification status

Phase 4 ran in the orchestrator's main session. All 3 HIGH + 8 of 9
MEDIUM + 4 of 4 LOW findings landed in a single `rect(E04_S02)` commit.
F7 (lancedb exception subclass brittleness) was **invalidated** on
re-verify — the existing `pytest.raises(ValueError)` is correct for
the lancedb 0.30.x API and the test docstring already acknowledges
the version dependency.

| ID | Severity | Status | Notes |
|---|---|---|---|
| F1 | HIGH | **fixed** in `rect(E04_S02)` | Live-verified that `lancedb.connect` returns a fresh `Connection` per call. Added `TestHandleIndependence.test_two_handles_with_different_versions_are_independent` that opens both handles, asserts `tbl_a is not tbl_b`, and re-checks `tbl_a` after `tbl_b` is opened. |
| F2 | HIGH | **fixed** in `rect(E04_S02)` | Narrowed `except Exception` to `except (ValueError, LookupError, KeyError)`. Added `TestNarrowExceptionCatch.test_oserror_propagates_unchanged` and `test_runtimeerror_propagates_unchanged` (monkeypatches `LanceTable.checkout` to raise the foreign exception). |
| F3 | HIGH | **fixed** in `rect(E04_S02)` | `server.corpus` now imports `DEFAULT_LANCEDB_PATH` from `ingest.store`; `open_chunks_table` defaults `lancedb_path=None`. Regression: `TestSingleSourceOfTruth.test_corpus_imports_default_path_from_store` (object-identity check). |
| F4 | MEDIUM | **fixed** in `rect(E04_S02)` | The canonical MVCC test now opens BOTH handles before asserting — silent-pass-on-shared-handle-bug regression closed. |
| F5 | MEDIUM | **fixed** in `rect(E04_S02)` | `test_no_symlinks_under_lancedb_root` now asserts `len(entries) > 0` before iterating. |
| F6 | MEDIUM | **fixed** in `rect(E04_S02)` | `test_invalid_version_raises_value_error` now matches the requested version integer `"999999"` (stable API contract), not the implementation-specific message text. |
| F7 | MEDIUM | **invalidated** | The lancedb 0.30 exception is a `ValueError`; the test docstring acknowledges the cross-version brittleness. A wider catch would mask real bugs. Keeping the narrow match. |
| F8 | MEDIUM | **fixed** in `rect(E04_S02)` | `_make_chunk` joins the existing `from tests.test_store import (...)` block; the awkward `__import__` indirection is gone. |
| F9 | MEDIUM | **fixed** in `rect(E04_S02)` | `server.corpus` module + function docstrings carry an explicit `.. warning::` block plus a `TODO(E06)` comment near the path resolution naming the deferral. |
| F10 | MEDIUM | **fixed** in `rect(E04_S02)` | New `TestNoneVsLatestEquivalence.test_checkout_at_live_tip_equals_checkout_none` asserts both code paths produce identical `count_rows()` and `version`. |
| F11 | MEDIUM | **fixed** in `rect(E04_S02)` | `ingest.store` module docstring gains a "Single-writer assumption" paragraph explicitly documenting the merge-vs-index race window and prescribing external serialization for multi-writer scenarios (deferred to E11). |
| F12 | MEDIUM | **fixed** in `rect(E04_S02)` | Module docstring's new "Caching contract" paragraph names the function as the "uncached primitive" and prescribes the E06 caching pattern (cache returned handle, never call checkout on it). |
| F13 | LOW | **fixed** in `rect(E04_S02)` | Return type annotated as `"lancedb.table.Table"` via `TYPE_CHECKING` block; IDE/type-checker support restored. |
| F14 | LOW | **fixed** in `rect(E04_S02)` | Function docstring's `Raises` block updated to honestly describe the narrowed catch (F2 fix). |
| F15 | LOW | **fixed** in `rect(E04_S02)` | `live_version = getattr(tbl, "version", None)` instead of the `"?"` string sentinel. F-string renders `None` naturally. |
| F16 | LOW | **fixed** in `rect(E04_S02)` | New `TestSingleSourceOfTruth.test_corpus_docstring_states_mvcc_handshake` asserts the AC5 sentence appears in BOTH `ingest.store.__doc__` AND `server.corpus.__doc__` — drift in either direction is now regression-locked. |

**Test count:** 10 → 16 MVCC tests (6 new regression guards: handle
independence, default-path symmetry, corpus-side docstring contract,
None-vs-latest equivalence, OSError propagation, RuntimeError
propagation). Full suite: 462 passed, 2 skipped, ruff clean.
