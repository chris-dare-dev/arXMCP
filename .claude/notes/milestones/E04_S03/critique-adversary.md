# E04_S03 Adversary Critique

## Executive Summary
- Verdict: **fix-then-proceed**. The brief's six ACs are met and the marker write rides the existing `_write_preamble_json` atomic-write pattern correctly. Issues are correctness-leaning around schema validation and silent failure paths, not architectural.
- One HIGH worth lifting: `from_dict` is permissive enough that `embedder_version=None`, integer types where strings are required, and `version=-1`/`paper_count=-5` all pass without raising. The "ValueError on corrupt" promise in the docstring is partially false.
- Marker-write swallow swallows only `OSError`; a `ValueError` (e.g. JSON serialization edge case, or any non-OSError thrown by `Path.mkdir` on a read-only mount under POSIX) would propagate AFTER the LanceDB write succeeded — splitting LanceDB-state vs. user-visible-error. Not a likely path, but the tradeoff was claimed in the impl summary as recoverable and that claim only holds for OSError.
- Path-traversal: the writer and reader do NOT carry the Threat 1 / TODO(E06) deferral note that `open_chunks_table` carries (server/corpus.py:55-64, 135-141). A consistent threat-model marker is missing on the two new public surfaces.
- Test fragility: `test_marker_carries_correct_aggregates` hardcodes `paper_count == 3` against an internal detail of `_make_corpus` (the `i % 3` rotation). A future, completely reasonable edit to `_make_corpus` silently breaks this test for the wrong reason.
- Test cross-file coupling: `tests/test_corpus_version.py` imports `_make_chunk` / `_make_corpus` / `_make_synthetic_embeddings` from `tests.test_store`. Two test files now hard-couple to test_store helpers; a refactor of `_make_chunk` semantics breaks both. Fixable by hoisting helpers to `tests/helpers.py` but not blocking.
- One LOW: `from_dict` raises `KeyError` on missing required fields, but the wrapper `read_corpus_version` re-raises as `ValueError`. The class-level `from_dict` test catches `KeyError` directly. Two callers, two error types — predict-once-write-once would have the dataclass raise `ValueError` itself.

## Severity calibration table
| Severity | Definition | Target rate |
|---|---|---|
| CRITICAL | data loss / security breach / broken invariant | rare |
| HIGH | wrong behavior on common path | low |
| MEDIUM | subtle correctness or missing test | moderate |
| LOW | style, naming, minor docs | as found |

## Findings

### CRITICAL
None.

### HIGH

**H1. `from_dict` silently accepts wrong-type and negative inputs — "raises on corrupt" promise broken**
- **What:** `CorpusVersionInfo.from_dict` calls `int(data["version"])`, `str(data["chunker_version"])`, `str(data["embedder_version"])` etc. without validating the source type. A marker with `"version": "3"` (string), `"chunker_version": 5` (int), `"embedder_version": null` (Python `None` → `str(None) == "None"`), `"version": -1`, or `"paper_count": -5` all deserialize cleanly. The reader's docstring claims "wrong type … raises `KeyError` / `ValueError`," and the wrapper's docstring promises a "recoverable corruption signal," but a corrupt-but-castable marker passes through.
- **Why it matters:** Cache-correctness contract: the `version` integer is the cache namespace key. A marker rewritten to `version=-1` (e.g., partial corruption, accidental sentinel from a mis-merged migration) deserializes to `-1` and downstream `open_chunks_table(version=-1)` will hit the F2 error path (E04_S02), but the corruption signal is lost — ops sees "LanceDB version -1 not accessible" instead of "corpus-version.json malformed." Same for `embedder_version: null` → silently stringified to `"None"` and passes through the equality check used by `embeddings.embedder_version or EMBEDDER_VERSION` if a future read consumer compares strings.
- **Where:** `server/corpus.py:251-258` (`from_dict` body); `server/corpus.py:276-279` (docstring claim); `server/corpus.py:296-301` (wrapper).
- **Fix sketch:** In `from_dict`, validate types BEFORE casting (`isinstance(data["version"], int)`, etc.) and validate domain constraints (`data["version"] >= 0`, `paper_count >= 0`, `chunk_count >= 0`, `embedder_version` non-empty). Raise `ValueError` (not `KeyError`) with a field-naming message. Then collapse the wrapper's two-arm try/except into one.

### MEDIUM

**M1. Marker-write swallow handles only `OSError`; non-OSError leaves LanceDB committed and exception propagating**
- **What:** `write_chunks` wraps the marker call in `try/except OSError` (ingest/store.py:680-697). The implementation summary defends this as "recoverable — server falls back to live-tip pinning." But `write_corpus_version_marker` can also raise `TypeError`/`ValueError` (e.g., a future caller passing a non-stringifiable `embedder_version`, or `int(version)` on a non-castable input — both are coverable today by tests, but the contract is now: ANY non-OSError post-LanceDB-commit propagates and the user sees a failure even though the dataset was successfully written.
- **Why it matters:** Splits visible state. The dataset_version is committed but the function raises, so the caller has no return value to use for pinning. Worse, the summary claims the design is "marker write failure does NOT abort the whole ingest" — but the OSError-only narrowing means non-OSError failures DO abort it (silently committing LanceDB). At minimum the docstring and the impl summary should agree.
- **Where:** `ingest/store.py:680-697`.
- **Fix sketch:** Either widen to `except Exception` (matching the stated "marker-write is best-effort" contract — the impl summary already commits to this) OR document explicitly that non-OSError propagates after LanceDB commit. Pick one and align the docstring. Also: log the post-commit `dataset_version` in the propagated exception path so triage can recover.

**M2. Path-traversal threat-model deferral is missing on new public surfaces**
- **What:** `server/corpus.py`'s `open_chunks_table` carries an explicit Threat 1 / TODO(E06) deferral block (server/corpus.py:55-64, 135-141). The two new public surfaces — `write_corpus_version_marker` (ingest/store.py:473) and `read_corpus_version` (server/corpus.py:261) — accept the same `lancedb_path` shape but do not carry the same deferral marker. A grep for "Threat 1" / "TODO(E06)" scanning the new code returns zero hits.
- **Why it matters:** 08-security-observability-ops.md Threat 1 (path traversal) is documented as deferred; the writer and reader honor that deferral by not validating, but they don't say so. A future maintainer reading `write_corpus_version_marker` in isolation could plumb a user-supplied path into it (it's in `__all__`) and bypass the unstated validation contract. The reader is already importable by anything in `server/`. Verified: `Path("../../etc") / "corpus-version.json"` resolves outside the corpus root.
- **Where:** `ingest/store.py:481-539` (writer docstring), `server/corpus.py:264-283` (reader docstring).
- **Fix sketch:** Add a one-paragraph block to both docstrings mirroring `open_chunks_table`'s Threat 1 wording: "Path-traversal validation is deferred to E06's tool-input boundary; callers passing user-supplied paths MUST validate against an allowlisted corpus root first."

**M3. `test_marker_carries_correct_aggregates` hardcodes a magic 3 against `_make_corpus` internals**
- **What:** The test asserts `info.paper_count == 3` because `_make_corpus(n)` uses `i % 3` to rotate paper IDs. A reasonable future edit to `_make_corpus` (e.g., to `i % 5` for richer fixtures) silently breaks E04_S03's aggregate test for an unrelated reason.
- **Why it matters:** Test fragility couples E04_S03's correctness signal to E04_S01's helper internals. The test should derive expected `paper_count` from the actual chunks list it built, not from the rotation constant.
- **Where:** `tests/test_corpus_version.py:343-352`.
- **Fix sketch:** Replace `assert info.paper_count == 3` with `assert info.paper_count == len({c.paper_id for c in chunks})` and `assert info.chunk_count == len(chunks)`. The test then validates the aggregate FORMULA, which is the actual contract.

**M4. Cross-file test helper coupling — two files now break together**
- **What:** `tests/test_corpus_version.py` imports `_make_chunk`, `_make_corpus`, `_make_synthetic_embeddings` from `tests.test_store` (tests/test_corpus_version.py:36-40). `test_mvcc.py` already does the same (per repo conventions). A signature change to `_make_chunk` now breaks at least three test files at once.
- **Why it matters:** Test-time SoT is fine, but `tests/test_store.py` is now an unmarked helper module. Refactoring that file requires running every test file, not just the one being changed. Not blocking but fragile as the test surface grows.
- **Where:** `tests/test_corpus_version.py:36-40`.
- **Fix sketch:** Hoist `_make_chunk`, `_make_corpus`, `_make_synthetic_embeddings` into `tests/helpers.py` (or `tests/_fixtures.py`). Both `test_store.py` and `test_corpus_version.py` import from there. Defer to a follow-up if it complicates this milestone's PR.

**M5. `read_corpus_version` does not validate that `marker_path` is a regular file**
- **What:** `if not marker_path.exists():` (server/corpus.py:288) treats a directory at `<lancedb_path>/corpus-version.json` as "exists, not a file" and falls through to `marker_path.read_text(...)`, which raises `IsADirectoryError` (a subclass of `OSError`, not `ValueError`). The reader's documented contract is: absent → `None`, corrupt → `ValueError`. A directory-shaped path slot at the marker location is technically corruption, but it propagates as `OSError`.
- **Why it matters:** Mostly a contract-completeness issue. In adversarial cases (a previous failed atomic-rename leaving `corpus-version.json` as a stray directory, or a deliberate symlink), the reader's exception type contract leaks an `OSError` that the wrapper is not trying to catch.
- **Where:** `server/corpus.py:284-289`.
- **Fix sketch:** Change to `if not marker_path.is_file(): return None` (or split: missing → `None`, exists-but-not-file → `ValueError`). The current behavior is reasonable, but the docstring should call it out, or the code should normalize.

**M6. `embedder_version` fallback in `write_chunks` masks an upstream contract violation**
- **What:** Line 686 of `ingest/store.py`: `embedder_version=embeddings.embedder_version or EMBEDDER_VERSION`. The `EmbedRecord.embedder_version` field defaults to `""` (empty string). If an upstream caller hands `write_chunks` an `EmbedRecord` with the default-empty `embedder_version`, the fallback silently substitutes the live `EMBEDDER_VERSION` constant. This means the marker reports `EMBEDDER_VERSION` even when the actual rows in LanceDB were written with `embedder_version = ""` (no validation in `_build_arrow_table`).
- **Why it matters:** The marker file's `embedder_version` is supposed to identify what model produced the embeddings in the dataset. The fallback substitutes wrong information when `EmbedRecord.embedder_version` is empty — ops would see a "bge-m3@<sha>" stamp on the marker that does NOT match what's in the rows. Per the schema, `embedder_version` is non-nullable in the LanceDB column (ingest/schema.py:104), so the row-level write with empty string would still land — but the marker would lie.
- **Where:** `ingest/store.py:686`; `ingest/schema.py:151` (the `""` default).
- **Fix sketch:** Either (a) raise `ValueError` if `embeddings.embedder_version` is falsy (forces upstream to set it explicitly, in line with `load_embed_record`'s discipline at ingest/store.py:230-234), or (b) drop the fallback and always pass `embeddings.embedder_version` straight through. The fallback is a foot-gun for a non-validated EmbedRecord path.

**M7. Atomic-write tmp-name collision possible if a marker write is interrupted twice in the same PID**
- **What:** The tmp suffix is `f"{out_path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"`. UUID4 makes a per-call collision astronomically unlikely. But `try/finally with contextlib.suppress(OSError): tmp.unlink(missing_ok=True)` only cleans up the tmp file used in THIS call — a previous interrupted call (process killed between `write_text` and `os.replace`) leaves a stray tmp on disk forever. Subsequent successful runs do NOT clean those up.
- **Why it matters:** Disk-clutter rather than corruption. The directory is `var/arxmcp/index/lancedb/`, which is the LanceDB dataset root. LanceDB's own directory listing tolerates random extra files, but ops `du -sh` becomes noisy after enough crashes. Not a correctness issue, but worth either a glob-cleanup at write start (matching the discipline used in some atomic-rename idioms) or a doc note that the cleanup is best-effort.
- **Where:** `ingest/store.py:558-566`.
- **Fix sketch:** At the top of the writer, before creating the new tmp, glob `out_path.parent` for `corpus-version.json.*.tmp` and `unlink(missing_ok=True)` each — a 5-line sweep that bounds the leak. OR document that stale tmp files are debris and ops sweeps them. (The preamble.py / embedder.py atomic-write pattern has the same gap; fixing here without fixing those creates inconsistency, so consider a follow-up.)

### LOW

**L1. `from_dict` raises `KeyError` on missing required fields; wrapper re-raises as `ValueError`**
- **What:** Two callers, two error types. The dataclass test (`test_from_dict_strict_on_required_fields`, tests/test_corpus_version.py:108-113) expects `KeyError`; the wrapper test (`test_raises_on_missing_required_field`, tests/test_corpus_version.py:222-228) expects `ValueError`. Anyone using `CorpusVersionInfo.from_dict` directly must catch BOTH `KeyError` and `ValueError`.
- **Why it matters:** Predictable error-type discipline says one input class → one exception class. Right now `from_dict` raises three (`KeyError` for missing, `TypeError` for None-passed-to-int, `ValueError` for non-castable string). Cleaner to wrap the whole body in a try/except → re-raise as `ValueError`.
- **Where:** `server/corpus.py:251-258`.
- **Fix sketch:** Wrap the body of `from_dict` in `try` and re-raise `(KeyError, TypeError, ValueError)` as `ValueError(f"...field {missing_field}...")`. The wrapper then becomes a passthrough.

**L2. `created_at` format omits microseconds — collisions possible within the same second**
- **What:** `datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")` (ingest/store.py:550). Two `write_chunks` calls within the same second produce identical `created_at` but distinct `version` integers. Since `created_at` is debug-only and `version` is the truth, this is harmless — but it's worth a sentence in the docstring.
- **Why it matters:** A debugger looking at two consecutive marker files (e.g., via a backup tool) cannot distinguish them by `created_at` alone. Cosmetic.
- **Where:** `ingest/store.py:550`.
- **Fix sketch:** Either switch to `"%Y-%m-%dT%H:%M:%S.%fZ"` (microsecond precision, still ISO-8601), or add a one-line comment that `created_at` is second-resolution and the source of truth is `version`.

**L3. Cache-contract docstring duplicated across two modules with subtle wording differences**
- **What:** The cache-key formula appears in `server/corpus.py:74-78` and is REFERENCED but not duplicated in `ingest/store.py:486-507`. The reader's per-class docstring (`CorpusVersionInfo`, server/corpus.py:217-221) says "MUST NOT enter cache keys"; the module-level docstring says "Only `version`." Same idea, different word — easy for future maintainers to drift one without the other.
- **Why it matters:** Docs in two places drift in real codebases. The brief asked for ONE comment in `server/corpus.py`; the impl ships two (module + class docstring) plus references in `ingest/store.py`. Consider collapsing to a single source-of-truth paragraph.
- **Where:** `server/corpus.py:66-80`, `server/corpus.py:217-221`, `ingest/store.py:486-507`.
- **Fix sketch:** Pick one location (module docstring) and reference it from the other two with `(see module docstring)`.

**L4. `tests/test_corpus_version.py:158-176` uses `monkeypatch` to redirect `DEFAULT_LANCEDB_PATH`, and a parallel test does the same in `test_store.py` — no conftest fixture covers it**
- **What:** The autouse `_patched_store_stats_path` only redirects `STORE_STATS_PATH`. `DEFAULT_LANCEDB_PATH` is also writable by the writer when `lancedb_path=None`, but only one test exercises the default path (`test_default_path`), and it monkeypatches in-place. No conftest gate prevents an accidentally-`None` `lancedb_path` in some future test from writing into the real `var/arxmcp/index/lancedb/` tree.
- **Why it matters:** Mirrors the F8 fix from E04_S01 — a checkout-pollution concern. Currently no test does pollute (verified by grep), so this is preventative not corrective.
- **Where:** `tests/conftest.py:18-43`; `tests/test_corpus_version.py:135-149`.
- **Fix sketch:** In a follow-up, extend `_patched_store_stats_path` to also redirect `DEFAULT_LANCEDB_PATH` to `tmp_path / "lancedb"` for consistency. Not blocking E04_S03.

**L5. `__all__` exports don't include the constant `EMBEDDER_VERSION` re-import line that `from_dict` callers will need**
- **What:** Cosmetic. The new code adds `from ingest.embedder import EMBEDDER_VERSION` and `from ingest.chunker_types import CHUNKER_VERSION` at ingest/store.py:91-93, but these are not re-exported from `ingest/store.py.__all__`. A test or driver that does `from ingest.store import CHUNKER_VERSION` (a reasonable read-through) would fail. The current call sites import from the SoT module directly, so this is fine, but it's inconsistent with `CORPUS_VERSION_MARKER_NAME` getting added to `__all__`.
- **Why it matters:** Pure style. Would not change behavior.
- **Where:** `ingest/store.py:708-716`.
- **Fix sketch:** No-op or add the constants to `__all__` if the project convention is to re-export.

## What was done well
- Atomic-write pattern (PID + UUID-suffixed tmp, `os.replace`, `try/finally` cleanup) faithfully copies the project's existing `_write_preamble_json` discipline. Same-fs guarantee surfaced explicitly in the docstring.
- Single-source-of-truth: `CORPUS_VERSION_MARKER_NAME` defined once in `ingest/store.py` and imported from `server/corpus.py`. No bare strings duplicated.
- The writer/reader path-default symmetry (`lancedb_path: str | Path | None = None` defaulting to `DEFAULT_LANCEDB_PATH`) is consistent with E04_S02's `open_chunks_table` and the broader pattern.
- BP1-discipline awareness: alphabetical key sorting in both `to_dict()` and the JSON serializer, terminating newline, `ensure_ascii=False`. The decision to keep `created_at` is justified explicitly (runtime config artifact, not a cached one).
- Cache-contract paragraph in `server/corpus.py`'s module docstring quotes the brief's wording verbatim and connects to `07-multi-agent-caching.md` § "Tier 1 — Exact-query" with the exact key formula.
- Test coverage maps cleanly to the brief's six ACs (`TestWriteOnIngest`, `TestAtomicWrite`, `TestReadMarker`, `TestCacheContract`, `TestVersionIncrements`) and adds a `TestCorpusVersionInfoDataclass` class for round-trip + leniency.
- The lenient-on-`created_at` discipline in `from_dict` is correct: it's the only field marked debug-only, and a future schema reduction that drops it should not break readers.
- The `try/except OSError` design rationale is documented in the implementation summary AND in the inline comment block at ingest/store.py:673-679 — future maintainers see the intent.
- The `_create_indices`-then-marker order matches E04_S02's MVCC handshake invariant: the marker records the post-index version, not the post-merge version.
- Documentation cross-references are tight: docstrings name `E04_S02`, `E08_S03`, `E06`, and the relevant design docs by file. A reviewer can navigate the contract net without reverse-search.

## Recommended rectification order
1. H1 — tighten `from_dict` validation (type + domain). Touches one method, big payoff.
2. M1 — align the swallow scope with the documented intent (widen to `Exception` OR document the propagation).
3. M2 — add Threat 1 / TODO(E06) deferral block to writer + reader docstrings.
4. M3 — derive `paper_count` from the chunks list in the test (not the magic 3).
5. M6 — decide on the `embedders.embedder_version or EMBEDDER_VERSION` fallback.
6. M5 — `is_file()` instead of `exists()`.
7. L1 — collapse `from_dict` error types to `ValueError`.
8. M4, M7, L2-L5 — follow-ups, do not block this milestone.

## Rectification status

Phase 4 ran in the orchestrator's main session. The single HIGH (H1)
plus 5 of 7 MEDIUM plus 1 LOW landed in a single `rect(E04_S03)`
commit. M4 (cross-file helper coupling), M7 (stale tmp leak), and
the LOW polish items L2-L5 deferred per the LOW-threshold rectifier
contract.

| ID | Severity | Status | Notes |
|---|---|---|---|
| H1 | HIGH | **fixed** in `rect(E04_S03)` | `from_dict` now validates type AND domain (`isinstance` checks for str/int, `version >= 1`, `paper_count/chunk_count >= 0`, bool excluded from int via explicit `isinstance(value, bool)` guard, non-empty string check). All errors normalize to `ValueError` with field-naming messages. 6 new regression tests (negative version, negative paper_count, string version, None embedder_version, int chunker_version, bool-as-version). |
| M1 | MEDIUM | **fixed** in `rect(E04_S03)` | Marker-write swallow widened from `except OSError` to `except Exception` — matches the documented "best-effort" contract. Comment block at the call site explains the rationale and explicitly notes the post-LanceDB-commit error-propagation concern. |
| M2 | MEDIUM | **fixed** in `rect(E04_S03)` | `write_corpus_version_marker` and `read_corpus_version` docstrings now carry the same `.. warning::` block + `TODO(E06)` marker as `open_chunks_table`. Two regression tests (`TestThreat1Deferral`) ensure the markers cannot drift. |
| M3 | MEDIUM | **fixed** in `rect(E04_S03)` | `test_marker_carries_correct_aggregates` now derives `expected_paper_count = len({c.paper_id for c in chunks})` and `expected_chunk_count = len(chunks)` instead of hardcoding `3`. Test validates the formula, not the magic number. |
| M4 | MEDIUM | **deferred** | Cross-file helper coupling. The fix is to hoist `_make_chunk` / `_make_corpus` / `_make_synthetic_embeddings` to `tests/helpers.py`. Touches 3 test files; deferred to a follow-up to keep this commit focused. |
| M5 | MEDIUM | **fixed** in `rect(E04_S03)` | `read_corpus_version` switched from `.exists()` to `.is_file()` so a directory at the marker location returns `None` (the documented absent-marker contract) rather than raising `IsADirectoryError`. Regression: `test_returns_none_when_marker_is_a_directory`. |
| M6 | MEDIUM | **fixed** in `rect(E04_S03)` | `write_chunks` no longer falls back to `EMBEDDER_VERSION` when `embeddings.embedder_version` is empty; it passes the value straight through. The fallback masked an upstream contract violation that would have produced markers disagreeing with the actual rows. |
| M7 | MEDIUM | **deferred** | Stale tmp file accumulation under crash conditions. Affects all three atomic-write call sites (`preamble`, `embedder`, `store`); fixing one without fixing the others creates inconsistency. Worth a separate cleanup-discipline commit. |
| L1 | LOW | **fixed** in `rect(E04_S03)` | Folded into the H1 fix — `from_dict` now raises a single `ValueError` for all schema violations (missing field, wrong type, domain violation). Regression test renamed `test_from_dict_missing_required_field_raises_value_error`. |
| L2 | LOW | **deferred** | `created_at` second-resolution timestamp. Cosmetic; `version` integer is the source of truth. |
| L3 | LOW | **deferred** | Cache-contract docstring duplicated. Cosmetic; the brief required ONE comment in `server/corpus.py`, which lands at the module level. |
| L4 | LOW | **deferred** | Conftest fixture preventative. No test currently pollutes the real `var/` tree (verified by grep); preventative cleanup deferrable. |
| L5 | LOW | **deferred** | `__all__` re-export of imported constants. Pure style. |

**Test count:** 18 → 27 corpus-version tests (9 new regression
guards: 6 H1 type/domain validation, 1 M5 directory-at-marker, 2 M2
threat-1 deferral docstring scans). Full suite: 489 passed, 2
skipped, ruff clean.
