# E03_S02 Adversary Critique

## Executive Summary
- Verdict: **fix-then-proceed**. One CRITICAL soundness gap (sidecar handshake skips paper when NPZ is missing/corrupt), plus four HIGH issues that erode the brief's stated guarantees.
- The implementation correctly adapts the brief's "LanceDB pre-flight" to NPZ+sidecar (D1/D6). The skip semantics are mostly right but trust the sidecar without verifying its companion file exists.
- Acceptance-criterion AC #5 ("no race condition: if two embedder *processes* run concurrently") is asserted only via Python *threads* in `TestConcurrency` — never the multi-process scenario the brief named.
- Tests do not verify BP1 byte-stability of the sidecar across two real runs (a write→delete→re-write→bytes-equal cycle is missing). The current "second run is zero writes" only proves the skip *avoided* the write, not that the write *would* be byte-identical.
- The `_load_chunks` call happens BEFORE the skip check, so every chunk JSON is opened on every run — including for papers that are fully up to date. This breaks the brief's "fast (scalar scan, no vector load)" pre-flight contract at scale.
- The unrelated chunker.py tokenizer pinning (F7 from E03_S01) was smuggled in under this milestone's commit, conflating two independent change rationales.
- Sidecar tolerates orphan chunks (`embedded_chunks` may be a superset of the manifest) — defensible but undocumented in the docstring's bullet list (only acknowledged in an inline comment).
- New chunks since last embed are correctly re-embedded paper-wide (D8 path); per-chunk granularity is a deferred E04 optimisation.

## Severity calibration table
| Severity | Definition | Target rate |
|---|---|---|
| CRITICAL | data loss / security breach / broken invariant | rare |
| HIGH | wrong behavior on common path | low |
| MEDIUM | subtle correctness or missing test | moderate |
| LOW | style, naming, minor docs | as found |

## Findings

### CRITICAL

**F1. `_paper_is_up_to_date` skips paper when sidecar exists but `embeddings.npz` is missing/truncated/unreadable.**
- **What:** The skip predicate reads only the sidecar JSON. It never `stat`s or opens `embeddings.npz`. If a user manually deletes the NPZ (disk-recovery, partial cleanup, fs corruption), the sidecar still satisfies all four conditions and the paper is incorrectly skipped on the next run, leaving downstream consumers (E04_S01 reader, BM25 builder, etc.) facing a missing-NPZ error from a paper that the audit trail claims is "up to date".
- **Why it matters:** The brief's literal acceptance criterion 1 says "before encoding a chunk, the embedder checks whether the *target embedding column is already populated*". The implementation infers population from "chunk_id appears in sidecar's `embedded_chunks`" plus the comment "the sidecar is only written after the NPZ write succeeds, so a chunk appearing in the sidecar implies its vector is in the NPZ" — but that invariant only holds if no out-of-band actor touches the NPZ. The "implies" claim is unverified at read time. This is the broken-invariant pattern Phase 4's BP1 discipline guards against (07-multi-agent-caching.md). Self-healing is broken: a half-cleaned-up corpus (NPZ deleted, sidecar kept) silently stays half-broken across re-runs.
- **Where:** `ingest/embedder.py:601-617` (`_paper_is_up_to_date` — only checks sidecar) and the missing assertion in `embed_paper`'s skip branch at `ingest/embedder.py:797`.
- **Fix sketch:** Add `if not (EMBEDDINGS_DIR / paper_id / "embeddings.npz").exists(): return False` after the sidecar parse in `_paper_is_up_to_date`. Add a test `test_missing_npz_with_present_sidecar_forces_reembed` that deletes the NPZ, leaves the sidecar, and asserts the next run re-encodes.

### HIGH

**F2. AC #5 "two embedder *processes*" is tested only with Python threads.**
- **What:** `TestConcurrency.test_concurrent_writes_do_not_corrupt` spawns two `threading.Thread`s, but the brief AC says "if two embedder *processes* run concurrently on the same corpus". `os.replace` atomicity is a multi-process guarantee (POSIX), not a thread guarantee — the GIL serialises threaded `np.savez` calls anyway, so the test is dramatically weaker than the AC requires. A real concurrent-write bug (e.g. a dropped `os.replace`, a non-atomic JSON write) could pass this thread-only test and only fire under multi-process load.
- **Why it matters:** AC #5 is one of the milestone's five named criteria. It is being claimed satisfied with a test that does not exercise the failure mode the AC describes. If the embedder is invoked twice from the corpus driver in parallel processes (the realistic deployment shape), the threading-only test gives false confidence.
- **Where:** `tests/test_embedder_idempotent.py:611-660`.
- **Fix sketch:** Replace `threading.Thread` with `multiprocessing.Process` in the test, or add a second test using `subprocess.Popen` to run two writers in fully separate processes. Both must finish without leaving `*.tmp` files and with parseable NPZ + sidecar.

**F3. `_load_chunks` opens every chunk JSON before the skip check.**
- **What:** In `_embed_paper_impl`, `chunks = _load_chunks(paper_id)` runs at line 773 — BEFORE the skip check at line 797. `_load_chunks` opens every per-chunk JSON file. For a paper that is fully up to date, the entire chunk corpus is read off disk and parsed into Python dicts before the skip predicate is even consulted.
- **Why it matters:** The brief explicitly describes the skip-set construction as "fast (scalar scan, no vector load)". At 50 papers this is invisible; at the milestone's risk-noted 200K papers, this is N×M JSON opens on every re-run for zero useful work — the exact pattern the milestone is supposed to prevent. The implementation comment at line 793-795 ("The check is a single JSON parse — no NPZ open, no model load") is misleading: it ignores the N JSON parses already done by `_load_chunks`.
- **Where:** `ingest/embedder.py:773` (load) vs `ingest/embedder.py:797` (skip check).
- **Fix sketch:** Move the up-to-date check earlier. Read just the manifest's `chunk_id` list (one JSON parse) to populate `manifest_chunk_ids`, run `_paper_is_up_to_date`, and only call `_load_chunks` when the skip path returns False. The set of chunk_ids is already in the manifest.

**F4. No test verifies BP1 byte-stability of the sidecar across two real runs.**
- **What:** `test_second_run_is_zero_writes` asserts the second run *did not write* the sidecar (mtime unchanged). `test_sidecar_has_alphabetical_keys_and_no_timestamps` and `test_embedded_chunks_in_document_order` assert schema invariants from one run. There is no test that does: run, capture sidecar bytes, delete sidecar, run again, capture sidecar bytes, assert byte-identical.
- **Why it matters:** The sidecar is what the skip predicate depends on. If a future change introduces a non-deterministic field (timestamp, set iteration, dict ordering), the skip path could falsely re-embed because two byte-stable runs produce different sidecars. BP1 in 07-multi-agent-caching.md is load-bearing for the whole agentic-cache invariant.
- **Where:** `tests/test_embedder_idempotent.py` (no such test exists).
- **Fix sketch:** Add `test_sidecar_bytes_are_run_over_run_stable`: write sidecar via `_patched_embed_paper`, capture `sidecar.read_bytes()`, delete the sidecar (force re-write), call `_patched_embed_paper` again with a fresh fake_model, assert `bytes_b == bytes_a`.

**F5. The unrelated chunker tokenizer-pinning change rides this milestone's commit.**
- **What:** `ingest/chunker.py:_get_tokenizer` was modified to pin `revision=BGE_M3_COMMIT_SHA`, with the docstring claiming this closes "F7 from the E03_S01 adversary critique". That change has nothing to do with idempotent re-embed; it's an E03_S01 rectification item that was carried into the E03_S02 commit. This conflates rectification of a previous milestone's critique with the new milestone's deliverable.
- **Why it matters:** The git log loses the trace that F7 was rectified — anyone bisecting later will assume the fix arrived in E03_S02 even though the milestone-pipeline state for E03_S01 says rectification is done. It also creates a circular-import hazard: `ingest.chunker._get_tokenizer` now lazy-imports `ingest.embedder.BGE_M3_COMMIT_SHA`. A future top-level import added by either side would close the cycle.
- **Where:** `ingest/chunker.py:218-244`.
- **Fix sketch:** Either (a) revert the chunker change from this commit and land it as a separate `rect(E03_S01)` commit, or (b) leave it but update the commit body to call out the secondary E03_S01 rectification explicitly. Also consider hoisting `BGE_M3_COMMIT_SHA` into `ingest/chunker_types.py` (which neither module imports from cyclically) to remove the circular-import hazard.

### MEDIUM

**F6. Skip-path docstring in `_embed_paper_impl` claims "no NPZ open, no model load" but skips mentioning the N chunk-JSON parses already done.**
- **What:** Line 793-795 comment: "The check is a single JSON parse — no NPZ open, no model load." Misleading: by the time this comment fires, `_load_chunks` has already done N JSON parses for the per-chunk files plus one for the manifest.
- **Why it matters:** Documentation drift. Future maintainers will read this and assume the skip path is O(1), not O(N).
- **Where:** `ingest/embedder.py:791-795`.
- **Fix sketch:** Update the comment to "The skip check itself parses one JSON file (the sidecar). The chunks themselves were loaded above to populate `manifest_chunk_ids`." (or fix F3 first and the comment becomes accurate.)

**F7. `_paper_is_up_to_date` accepts orphan chunks in sidecar without exposing this in the docstring's numbered conditions list.**
- **What:** The numbered list in the docstring (1-4) describes the skip conditions. Condition 4 says "every chunk_id in `manifest_chunk_ids` is in the sidecar's `embedded_chunks`". The actual implementation also tolerates `embedded_chunks` being a superset of the manifest (orphan chunks). This tolerance is mentioned only in an inline comment at line 613-616, not in the docstring's numbered list.
- **Why it matters:** A reader who only reads the docstring will think the symmetric containment must hold. They might also expect a re-embed to be triggered when a chunk is removed from the manifest. Orphan vectors will silently sit in the NPZ until E04_S02's GC runs — a cosmetic-but-visible footprint.
- **Where:** `ingest/embedder.py:578-617`.
- **Fix sketch:** Move the orphan-tolerance note into the docstring's numbered list (e.g. condition 4 becomes "every chunk_id in `manifest_chunk_ids` is in the sidecar's `embedded_chunks`; orphan entries in the sidecar are tolerated and will be GC'd by E04_S02"). Add a test `test_orphan_chunks_in_sidecar_do_not_block_skip` that explicitly covers this.

**F8. `_paper_is_up_to_date` accepts a `set[str]` parameter but the caller builds it from a set comprehension that silently drops duplicates.**
- **What:** Caller at line 796: `manifest_chunk_ids = {c["chunk_id"] for c in chunks}`. If `_load_chunks` returns duplicate chunk_ids (a corpus corruption case), the duplicates collapse silently. The encode loop later iterates `chunks` (the list), so duplicates are encoded twice in the NPZ; the sidecar's `embedded_chunks` list also contains duplicates. The skip predicate then trivially returns True on any subsequent run because every chunk_id IS in the sidecar.
- **Why it matters:** Duplicate chunk_ids in a manifest are a corpus-corruption signal that should surface as an error, not be silently collapsed. The chunker is responsible for unique chunk_ids per paper, but the embedder has no defense against a bad input.
- **Where:** `ingest/embedder.py:796` (set comprehension), `_load_chunks` at line 625-671 has no dedup check.
- **Fix sketch:** Add a dedup check in `_load_chunks` that raises `_ManifestCorruptError` if any chunk_id appears more than once in the manifest. Or change the caller to detect `len(set(ids)) != len(ids)` and raise.

**F9. `_paper_is_up_to_date` `embedded_ids` set discards entries that are dicts without a `chunk_id` key without warning.**
- **What:** Line 612: `embedded_ids = {entry.get("chunk_id") for entry in embedded if isinstance(entry, dict)}`. If a sidecar entry is a dict but missing `chunk_id`, `entry.get("chunk_id")` returns `None`, which goes into the set. So `None in embedded_ids` is true. If `manifest_chunk_ids` happens to contain `None` (it never should, but the type hint says `set[str]`), this would falsely pass the subset check.
- **Why it matters:** Defensive code that silently swallows corruption. A sidecar with malformed entries (dict missing `chunk_id`) should not pass the skip predicate.
- **Where:** `ingest/embedder.py:612`.
- **Fix sketch:** Filter `None` out: `embedded_ids = {cid for entry in embedded if isinstance(entry, dict) and (cid := entry.get("chunk_id")) is not None}`. Or better, raise `_SidecarCorruptError` (new exception class) and treat as "corrupt sidecar" → re-embed.

**F10. `_FakeModel.call_count` resets per-test but is not asserted to never exceed batch boundaries — fragile for high-batch tests.**
- **What:** `_fake_model_factory` uses `seed_base = 1000 * self.call_count`. With batches of size 32, seed ranges are [1000, 1032), [2000, 2032), etc. — no collision in current tests. But a future test that uses batch_size or paper-chunk-counts >= 1000 would silently produce identical seeds across batches, masking BP1 regressions in the test fixture itself.
- **Why it matters:** The fake model is supposed to produce row-distinct vectors (closes F6 from E03_S01). At >=1000 chunks per call, this property breaks silently.
- **Where:** `tests/test_embedder_idempotent.py:160` and `tests/test_embedder.py:_fake_model_factory`.
- **Fix sketch:** Use `seed_base = 1_000_000 * self.call_count` (or `(self.call_count, batch_index)` tuple-hashed seed) to make collision practically impossible. Or assert `len(texts) < 1000` defensively in the fake.

**F11. "All up to date" log uses `%d/%d` with both args being `total_skipped` — the log loses the "out of total" semantic.**
- **What:** Line 1010-1013: `logger.info("Skipped %d/%d chunks — all up to date.", total_skipped, total_skipped)`. The brief's example `"Skipped N/N chunks — all up to date."` reads as "Skipped N out of N", but with both arguments equal it's tautological. The denominator should be the corpus's actual total chunk count (skipped + processed + manifest-absent contributions).
- **Why it matters:** Operational telemetry. The log message looks informative ("X/Y chunks") but Y = X by construction, conveying no extra information.
- **Where:** `ingest/embedder.py:1008-1013`.
- **Fix sketch:** Compute the real total: `total_chunks = total_skipped + total_processed`. Or, more useful: include paper count in the log: `"Skipped %d chunks across %d papers — all up to date."` matches the brief's intent without the spurious denominator.

**F12. Log fires only when `results and total_processed == 0 and total_skipped > 0`, missing the case where every paper had `_load_chunks` return [].**
- **What:** If the corpus directory exists but every paper has `chunk_manifest.json` absent (a state that shouldn't happen given embed_corpus's pre-filter at line 968, but reachable via direct `embed_paper` calls in batch), `total_processed=0` and `total_skipped=0`. The log doesn't fire. That's correct for THIS path.
- **Why it matters:** This is fine, but the implementation comment at line 1003-1005 says "every paper was a clean skip and no chunks were processed" — which doesn't quite match the actual condition (the AND with `total_skipped > 0` is the load-bearing piece).
- **Where:** `ingest/embedder.py:1001-1013`.
- **Fix sketch:** Tighten the comment to match the actual semantics, or test that mixed manifest-absent + skipped corpora produce the right log behavior.

### LOW

**F13. `_embed_paper_impl` re-validates `paper_id` indirectly only through `_load_chunks` path lookups.**
- **What:** `embed_paper` calls `_validate_paper_id(paper_id)` at line 729, but `_embed_paper_impl` is also reachable via the `embed_corpus` pathway (which validates separately at line 981). No double-validation is required, but the pre-flight skip path computes paths from `paper_id` (line 601: `EMBEDDINGS_DIR / paper_id / EMBEDDINGS_MANIFEST_NAME`) without checking if `paper_id` is well-formed.
- **Why it matters:** Defense-in-depth. If `_paper_is_up_to_date` is ever called from a new code path that doesn't pre-validate, a path-traversal `paper_id` like `"../../etc"` could read arbitrary JSON files.
- **Where:** `ingest/embedder.py:575-617`.
- **Fix sketch:** Add `_validate_paper_id(paper_id)` as the first line of `_paper_is_up_to_date`, or document it as a precondition in the docstring.

**F14. `EMBEDDINGS_MANIFEST_NAME` is module-level but `embeddings.npz` filename is a string literal repeated three times.**
- **What:** "embeddings.npz" appears as a string literal at lines 9 (docstring), 37 (docstring), 889 (write), and could be referenced from `_paper_is_up_to_date` for F1's fix.
- **Why it matters:** Single source of truth discipline (mirrors how `EMBEDDINGS_MANIFEST_NAME` was extracted at line 498).
- **Where:** `ingest/embedder.py:889`.
- **Fix sketch:** Add `EMBEDDINGS_NPZ_NAME = "embeddings.npz"` near `EMBEDDINGS_MANIFEST_NAME` and reference both consistently.

**F15. Implementation summary claims "2 files changed" but the actual diff touches 4.**
- **What:** `.claude/notes/milestones/E03_S02/implementation-summary.md` line 5: "Files changed: 2 (1 new test file, 1 modified embedder)". Actual `git diff --stat`: 4 files (chunker.py, embedder.py, test_embedder.py, test_embedder_idempotent.py).
- **Why it matters:** Audit-trail accuracy. The summary undersells the chunker.py and test_embedder.py changes that were carried in the commit.
- **Where:** `.claude/notes/milestones/E03_S02/implementation-summary.md:5`.
- **Fix sketch:** Update the line to "Files changed: 4 (1 new test file, 1 modified embedder, 1 modified chunker [F7 carryover from E03_S01], 1 modified existing test)".

## What was done well

- D2 alias resolution is clean: `from ingest.chunker_types import CHUNKER_VERSION as EXPECTED_CHUNKER_VERSION` keeps the literal in one place and is explicitly tested via object-identity assertion in `test_expected_chunker_version_is_alias`.
- Sidecar schema is alphabetical-keys, sorted via `json.dumps(sort_keys=True)`, no timestamps — matches BP1 byte-stability discipline.
- Atomic write pattern (tmp + `os.replace`) reused consistently from the NPZ writer; tmp filenames carry PID + UUID suffix to avoid cross-process collisions.
- Crash recovery between NPZ and sidecar writes is correctly handled: a crash leaving NPZ-without-sidecar triggers a re-embed (sidecar absence → not-up-to-date).
- `EmbedStats.chunks_skipped` is wired into both per-paper and run-summary JSONL rows; the audit trail correctly captures the new state.
- Self-healing on corrupt sidecar: `_read_embeddings_manifest` swallows `JSONDecodeError`, `OSError`, `UnicodeDecodeError` and returns `None`, forcing re-embed (matches `preamble._read_existing_preamble` discipline).
- Embedder version gate (D7) is an additive correctness improvement that closes the silent-mix-of-embedding-spaces footgun the brief literally only gates on chunker_version against.
- Tests are self-contained and offline-capable: the `_fake_model_factory` pattern means CI runs without the BGE-M3 model download.
- The `embed_paper` direct entry point benefits from the same skip logic via `_embed_paper_impl` — no API surface gap for callers bypassing `embed_corpus`.
- Empty-corpus log gate (`if results and ...`) correctly suppresses the "all up to date" log when nothing was actually checked.

## Recommended rectification order

1. F1 (CRITICAL — soundness gap on missing NPZ)
2. F3 (HIGH — pre-flight cost regression at scale)
3. F2 (HIGH — multi-process AC coverage)
4. F4 (HIGH — BP1 sidecar byte-stability test)
5. F5 (HIGH — chunker change scope)
6. F8 (MEDIUM — duplicate chunk_id handling)
7. F9 (MEDIUM — sidecar entry validation)
8. F7 (MEDIUM — orphan tolerance docstring)
9. F11 (MEDIUM — log message denominator)
10. F6 (MEDIUM — misleading comment in skip path)
11. F10 (MEDIUM — fake-model seed collision)
12. F12 (MEDIUM — log gate comment drift)
13. F13 (LOW — _paper_is_up_to_date defense-in-depth)
14. F14 (LOW — embeddings.npz filename constant)
15. F15 (LOW — implementation summary file count)

## Rectification status

Phase 4 ran in the orchestrator's main session. CRITICAL + all HIGH +
all MEDIUM landed in a single `rect(E03_S02)` commit; one LOW
(`F14`) folded in as a one-line change; remaining LOWs deferred per
the rectifier contract. F5 and F15 are **invalidated** on re-verify.

| ID | Severity | Status | Notes |
|---|---|---|---|
| F1 | CRITICAL | **fixed** in `rect(E03_S02)` | `_paper_is_up_to_date` now also requires `embeddings.npz` to exist on disk (not just the sidecar). Two regression tests: `test_returns_false_when_npz_missing` (helper-level) and `test_missing_npz_with_present_sidecar_forces_reembed` (public-API-level). |
| F2 | HIGH | **fixed** in `rect(E03_S02)` | added `TestMultiProcessConcurrency.test_concurrent_processes_do_not_corrupt` using `subprocess.Popen` so two real OS processes race on the same NPZ + sidecar. The threading-only test from F2's complaint stays in place as a complementary scenario. |
| F3 | HIGH | **fixed** in `rect(E03_S02)` | new helper `_read_manifest_chunk_ids` reads only the manifest's chunk_id list (one JSON parse) for the skip pre-flight; per-chunk JSONs are NOT opened on the up-to-date path. The skip cost is now 2 JSON parses per paper instead of N+2. |
| F4 | HIGH | **fixed** in `rect(E03_S02)` | `TestSidecarByteStability.test_sidecar_bytes_are_run_over_run_stable` writes a sidecar, deletes it, re-runs, and asserts byte-equality. |
| F5 | HIGH | **invalidated** | the chunker tokenizer-pinning change lives in commit `490c850` (E03_S01 rect), not `6f183be` (E03_S02 feat). The critic was given the range `8ee41be..6f183be` which includes both commits, conflating the rectification of E03_S01's F7 with this milestone's deliverable. The E03_S02 commit touches exactly 2 files. |
| F6 | MEDIUM | **fixed** in `rect(E03_S02)` | misleading comment naturally corrected by the F3 refactor — the skip path now genuinely opens only 2 JSON files. |
| F7 | MEDIUM | **fixed** in `rect(E03_S02)` | orphan-tolerance lifted from inline comment into the numbered docstring conditions of `_paper_is_up_to_date`; new test `test_orphan_chunks_in_sidecar_do_not_block_skip`. |
| F8 | MEDIUM | **fixed** in `rect(E03_S02)` | `_load_chunks` and `_read_manifest_chunk_ids` both raise `_ManifestCorruptError` on duplicate chunk_id; regression test `test_duplicate_chunk_id_in_manifest_raises_corrupt`. |
| F9 | MEDIUM | **fixed** in `rect(E03_S02)` | `_paper_is_up_to_date` now rejects sidecar entries that are non-dict, dict-but-missing `chunk_id`, or where `chunk_id` is not a string; regression test `test_returns_false_on_malformed_sidecar_entry`. |
| F10 | MEDIUM | **fixed** in `rect(E03_S02)` | `_fake_model_factory` seed multiplier raised from 1000 to 1_000_000 in both `tests/test_embedder.py` and `tests/test_embedder_idempotent.py` so cross-batch seed collision requires >=1M chunks per batch. |
| F11 | MEDIUM | **fixed** in `rect(E03_S02)` | "all up to date" log changed to `"Skipped %d chunks across %d papers — all up to date."` — drops the tautological N/N denominator, gains the paper count. |
| F12 | MEDIUM | **fixed** in `rect(E03_S02)` | comment at the gate updated to describe the actual semantics (the load-bearing AND with `total_skipped > 0`). |
| F13 | LOW | deferred | optional defense-in-depth `_validate_paper_id` inside `_paper_is_up_to_date` — actually folded in as part of the F1 fix since the function already touched paper_id-derived paths. So this is **fixed** too: `_paper_is_up_to_date` now calls `_validate_paper_id` as its first line. |
| F14 | LOW | **fixed** in `rect(E03_S02)` | new module-level `EMBEDDINGS_NPZ_NAME = "embeddings.npz"` constant; sole call site in `_embed_paper_impl` references it. |
| F15 | LOW | **invalidated** | the implementation summary's "Files changed: 2" claim is correct for this milestone's commit (`6f183be`). The critic conflated the diff range `8ee41be..6f183be` (which spans both `rect(E03_S01)` 490c850 and `feat(E03_S02)` 6f183be, totalling 4 files) with the milestone's own commit. |

**Test count:** 19 → 26 idempotent tests (7 new regression guards: NPZ presence at helper + public API levels, sidecar byte-stability, multiprocess concurrency, malformed sidecar entries, orphan tolerance, duplicate chunk_id rejection). Full suite: 378 passed, 1 skipped, ruff clean.
