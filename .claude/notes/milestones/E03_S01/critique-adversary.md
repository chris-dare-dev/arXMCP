# E03_S01 Adversary Critique

## Executive Summary
- Verdict: **fix-then-proceed**. Implementation is largely sound but has 2 HIGH and several MEDIUM gaps that affect acceptance-criteria literal compliance and BP1 byte-stability.
- The NPZ-first deviation from the brief ("proceeds in batches over all chunks in the LanceDB table") is intentional and documented in research-synthesis.md D1, but the brief's explicit acceptance criteria phrased in terms of LanceDB columns (e.g. "embedding_eq is null on all rows after a run") are now structurally untestable in this milestone — that needs to be acknowledged in critique, not silently glossed over.
- Per-paper failure path is missing the `_append_embed_stats` call (failures are logged ONLY to embed.log, not embed-stats.jsonl) — this contradicts the brief's "embed-stats.jsonl entry written per run" criterion when the run had a failure.
- `embed-stats.jsonl` schema does not include `paper_count`, `chunk_count`, or `wall_clock_seconds` aggregates — only per-paper rows. The brief's literal language "per run, including paper count, chunk count, wall-clock seconds" is ambiguous between "per paper" and "per corpus run", but the per-paper interpretation alone misses a corpus-level summary entry.
- `torch.set_num_threads(os.cpu_count() or 4)` is invoked inside the lazy loader and unconditionally re-applies on every `_get_model` call (the lazy guard prevents that, but the call still mutates global PyTorch state at first model load — fine, but should be documented as a side effect).
- The fake tokenizer in tests uses `len(text.split()) + 2` to count tokens for the truncation pre-pass, which produces dramatically different counts than BGE-M3's real BPE tokenizer would; the truncation-count test verifies only the structural code path, not the real-model behavior.
- The fake model's `last_hidden_state` is constructed from `torch.arange(batch).reshape(-1,1,1) + 1.0` times an arange — the FIRST batch row uses `base=1.0`, but distinct rows produce co-linear vectors that all normalize to the same direction (different magnitudes only). L2 normalization makes them indistinguishable, so vector-distinctness assertions cannot be added from this fake without changes.
- Pre-existing chunker tokenizer-pinning gap (Threat 6 violation) acknowledged in implementation summary but not fixed even though it is a one-line change in scope of the touched file.

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

#### F1. Failed runs do not write to `embed-stats.jsonl` — violates explicit acceptance criterion
- **What.** `embed_paper`'s outer except branch logs to `embed.log` and returns an `EmbedStats` with `status="fail"`, but never calls `_append_embed_stats`. The brief's acceptance criterion "embed-stats.jsonl entry written per run" is the only line in the brief that quantifies what gets written and when, and the implementation diverges from it specifically for the failure path (the path where ops most needs to see what happened).
- **Why it matters.** Operators querying `embed-stats.jsonl` to count paper failures will silently undercount: the JSONL only ever shows successful papers. The brief's intent of an audit trail is broken. Combined with `embed.log` being a TSV (different schema, different parser), failure observability is fragmented.
- **Where.** `ingest/embedder.py:464–478` — the `except PER_PAPER_FAILURE_EXCEPTIONS` branch in `embed_paper` returns the failed `EmbedStats` without calling `_append_embed_stats(stats)`.
- **Fix sketch.** Append `_append_embed_stats(stats_for_failure)` inside the except branch before the `return`, so JSONL gets one row per paper attempt regardless of outcome. Test: extend `TestStatsLogging.test_failure_writes_fail_status` to assert the JSONL also contains a `status=="fail"` row.

#### F2. `embed_corpus` writes no run-level summary entry; brief language "per run" is unmet
- **What.** The brief says: `embed-stats.jsonl entry written per run, including paper count, chunk count, wall-clock seconds, and the pinned BGE_M3_COMMIT_SHA`. The implementation writes one JSONL row per paper but never writes a corpus-run summary line that aggregates `paper_count`, `chunk_count`, and `wall_clock_seconds`. A `bge_m3_commit_sha` field exists per paper but never as an aggregate row that an ops dashboard can ingest as a single "embed_corpus completed" event.
- **Why it matters.** The brief's plural "paper count, chunk count" pretty unambiguously implies a corpus-level summary. Without it, downstream ops tooling has to re-derive these aggregates from per-paper rows (which is fine in principle, but loses the natural "run boundary" event). E11's "scale targets" comparisons are run-level.
- **Where.** `ingest/embedder.py:596–657` — `embed_corpus` returns a `list[EmbedStats]` but never writes a "run-summary" JSONL line.
- **Fix sketch.** After the for-loop in `embed_corpus`, append a JSONL line of the form `{"event": "run_summary", "paper_count": N, "chunk_count": sum(s.chunks_processed), "elapsed_s": total_elapsed, "bge_m3_commit_sha": BGE_M3_COMMIT_SHA, "started_at": ..., "completed_at": ...}`. Add a test that asserts the file has both per-paper rows AND a run-summary row.

### MEDIUM

#### F3. Truncation pre-pass uses `tokenizer.encode(text)` which can drift from `tokenizer(...)` truncation — count may be off
- **What.** `_encode_batch` does two passes through the tokenizer for each batch: first a Python loop calling `tokenizer.encode(text, add_special_tokens=True)` to count truncations, then a single `tokenizer(...)` call with `padding=True, truncation=True, max_length=MAX_TOKENS` to actually encode. These are NOT guaranteed to produce identical token-id sequences for non-trivial inputs (different `add_special_tokens` defaults, batch-pair handling, normalizer application order). For BGE-M3's `XLMRobertaTokenizerFast`, they generally agree, but the explicit promise that "the count is accurate" in the docstring overstates the guarantee.
- **Why it matters.** The truncation count surfaced in `EmbedStats.truncated_count` is what ops uses to decide whether to tighten the chunker budget. If the count drifts, the operational signal is wrong.
- **Where.** `ingest/embedder.py:278–283` — pre-count uses `tokenizer.encode`; the actual encode call at line 284 uses different invocation form.
- **Fix sketch.** Either (a) call `tokenizer(text, add_special_tokens=True, truncation=False)` once per text and check `len(input_ids[0]) > MAX_TOKENS`, then re-encode the batch with truncation; or (b) do the batch encode with `return_overflowing_tokens=True` / `return_length=True` and read length from the same call. Option (b) is one tokenizer call total, not 2× pass.

#### F4. Embedder catches `FileNotFoundError` as a per-paper failure but `_load_chunks` raises it for a missing chunk file (not a missing manifest) — the same error code can mean two structurally different failures
- **What.** `_load_chunks` returns `[]` (silent skip, no error) when the manifest is missing, but raises `FileNotFoundError` (caught by the per-paper envelope) when a manifest entry references a chunk file that does not exist on disk. These are very different failure modes (chunker did not run vs. corpus is corrupt), but they get the same `status="fail"` row and identical handling. The clean-skip case (manifest absent) goes through the success path with `chunks_processed=0`, while the corrupt-manifest case goes through the failure path.
- **Why it matters.** Ops cannot distinguish "chunker hasn't run yet for this paper" from "corpus state is internally inconsistent". The latter is a P0 corruption signal; the former is a routine wait.
- **Where.** `ingest/embedder.py:378–397` — `_load_chunks` returns `[]` at line 379 when manifest absent, raises `FileNotFoundError` at line 395 when chunk file missing.
- **Fix sketch.** Either define a more specific exception type for corpus-corruption failures (e.g. `ChunkFileMissingError(OSError)`) that gets logged with a different `error_class` tag, or differentiate via `EmbedStats.error` text and document the discrimination in the docstring. Adding a `error_class` field on `EmbedStats` (e.g. `"manifest_missing" | "chunk_missing" | "json_corrupt"`) gives ops a queryable field instead of free-text grepping.

#### F5. NPZ ZIP timestamps are deterministic (epoch-1980), but `np.savez` writes archive members in **kwargs insertion order** — non-alphabetical archive ordering tied to call-site order
- **What.** Verified empirically: `np.savez` writes the archive members in the order keyword arguments are passed. The implementation passes them as `chunk_ids_stmt, embedding_stmt, chunk_ids_proof, embedding_proof` (line 349–352). Per-byte file determinism therefore depends on a specific kwarg call order rather than alphabetical key sort. Per `07-multi-agent-caching.md` § "Property 2" "JSON keys serialized in alphabetical order" — the discipline is alphabetical-by-default. The NPZ is downstream of the BP1 cache so this isn't a direct cache key, but it is a per-corpus-version artifact whose hash should be stable.
- **Why it matters.** A future refactor that reorders the kwargs (e.g. moves `embedding_*` before `chunk_ids_*` for readability) would silently change the byte content of every existing NPZ, invalidating any external hash-based cache built on top. This is a very-low-likelihood but not-zero risk.
- **Where.** `ingest/embedder.py:347–353` — `np.savez(fh, chunk_ids_stmt=..., embedding_stmt=..., chunk_ids_proof=..., embedding_proof=...)`.
- **Fix sketch.** Either (a) document the call-site kwarg order as load-bearing in the docstring with an inline note; or (b) sort and pass alphabetically (`chunk_ids_proof, chunk_ids_stmt, embedding_proof, embedding_stmt`) — and add a test that locks the byte hash of an NPZ produced from a fixed input.

#### F6. The fake model factory produces colinear vectors before normalization — vector-distinctness invariants cannot be tested
- **What.** `_FakeOutput.__init__` builds `last_hidden_state = base * arange.repeat(...)` where `base[i] = i + 1` and `arange = [0, 1, 2, ..., hidden-1]`. After CLS slice, row `i` is `(i+1) * [0, 1, 2, ..., 1023]`. Every row is a positive scalar multiple of the same vector. After L2-normalization, every row collapses to **exactly the same** unit vector (`[0, 1, 2, ..., 1023] / norm`). This is unique only by zero (the first token is multiplied by `i+1` then by 0; the dim-0 component is always 0). The shape and L2-norm tests pass, but a test asserting "different inputs produce different vectors" cannot be added against this fake — and worse, a buggy implementation that returned the SAME constant vector for every chunk would still pass `TestVectorContract.test_shape_1024_and_l2_normalized`.
- **Why it matters.** The fake-model factory is the test surface for every routing/F3-fallback/atomic-write test. An implementation regression that, say, swapped two rows or zeroed all vectors in a buggy code path would not be caught by the existing fake-based tests because the fake's vectors are themselves nearly-degenerate. The brief's specific test "embed 5 chunks, assert vector shape (1024,), assert correct column routing" technically passes, but the underlying invariants are not meaningfully exercised.
- **Where.** `tests/test_embedder.py:158–179` — `_FakeOutput.__init__` and `_FakeModel.__call__`.
- **Fix sketch.** Use `torch.randn(batch, seq_len, hidden, generator=torch.Generator().manual_seed(seed_per_row))` so each row is a distinct random vector that L2-normalizes to a distinct unit vector. Then add a test assertion `assert not np.allclose(vectors[i], vectors[j])` for `i != j`.

#### F7. Pre-existing chunker tokenizer-pinning gap (Threat 6) — acknowledged in summary but not fixed
- **What.** The implementation summary § "Pre-existing tokenizer-pinning gap" calls out that `ingest/chunker.py:_get_tokenizer` calls `AutoTokenizer.from_pretrained("BAAI/bge-m3")` with no `revision=` and concedes "Fixing it is a one-line change in a follow-up." The chunker IS a file modified by this commit (line 214–219 in the diff). Adding `revision=BGE_M3_COMMIT_SHA` to the chunker's tokenizer load is genuinely a one-line change, in scope of the touched file, and closes a Threat-6 violation. Deferring to a follow-up exposes BP1 byte-stability risk because the chunker writes `body_tokens` from this unpinned tokenizer.
- **Why it matters.** If HuggingFace silently rotates the tokenizer-only files for the floating `BAAI/bge-m3` tag (without the model weights changing), `body_tokens` produced by the chunker drift across runs while `chunker_version` stays the same. That is a dormant cache-poisoning bomb directly inside the touched file.
- **Where.** `ingest/chunker.py:214–223` (touched in this commit's diff for an unrelated docstring update).
- **Fix sketch.** In `ingest/chunker.py`, change `AutoTokenizer.from_pretrained("BAAI/bge-m3")` to `AutoTokenizer.from_pretrained("BAAI/bge-m3", revision=BGE_M3_COMMIT_SHA)`, importing the constant from `ingest.embedder`. Add an assertion in `tests/test_chunker.py` mirroring `TestThreat6.test_tokenizer_loaded_with_pinned_revision`.

#### F8. Acceptance criterion `embedding_eq is null on all rows after a run` is structurally untestable — NPZ has no such column
- **What.** The brief explicitly says `embedding_eq is null on all rows after a run`. The NPZ file has no `embedding_eq` array. The implementation says (line 21–22) "the embedder never populates it" — true at the LanceDB level once E04_S01 wires the writer, but at the embedder's actual write surface the column simply doesn't exist as a concept yet. This is intentional per D1 of research-synthesis.md, but the criterion is now LITERALLY UNTESTABLE in this milestone, and there's no test that asserts the absence (e.g. `assert "embedding_eq" not in npz.files`).
- **Why it matters.** A future refactor of `_write_embeddings_npz` that adds a third array (e.g. for a different reason) named `embedding_eq` would silently start populating the column when E04_S01's writer fans out NPZ → LanceDB. The negative invariant should be locked.
- **Where.** Tests do not assert `"embedding_eq" not in npz.files`; the embedder doesn't construct the array, but no test guards the negative.
- **Fix sketch.** In `TestRouting.test_kind_section_definition_route_to_embedding_stmt` (or a dedicated test), add `assert "embedding_eq" not in npz.files`.

#### F9. Empty-paper handling produces a `(0, 1024)` zero array that passes through `np.savez` — the zero-row matrix is real bytes, not absent
- **What.** Lines 565–572: when `rows_proof` is empty, `embedding_proof = np.zeros((0, EMBEDDING_DIM), dtype=np.float32)`. This is then written into the NPZ. A reader that does `for chunk_id, vec in zip(npz["chunk_ids_proof"], npz["embedding_proof"]):` correctly iterates zero rows. But a reader that does `if npz["embedding_proof"].size > 0:` succeeds (size is 0); a reader that does `if "embedding_proof" in npz.files:` always succeeds. The "absent" semantics the brief calls for (`embedding_proof is left NULL`) is implemented as a zero-row 2-D array, not as a missing key.
- **Why it matters.** When E04_S01 reads the NPZ to populate LanceDB rows, it must explicitly check `len(chunk_ids_proof) > 0` rather than relying on key presence. If E04_S01 maps NPZ keys to LanceDB nullable columns by key existence, every row in every paper will have a non-null (zero-vector) `embedding_proof`. That zero vector is a valid 1024-dim vector with `L2 norm = 0` (un-normalized), and ANN search would find it as the "least similar" answer to any query — but it would still be returned.
- **Where.** `ingest/embedder.py:565–572`.
- **Fix sketch.** Document explicitly in the docstring of `_write_embeddings_npz` that `embedding_proof` and `embedding_stmt` arrays may have zero rows, and that consumers must check `chunk_ids_*` length rather than key presence. Add a test that loads an all-stmt paper's NPZ and confirms `embedding_proof.shape[0] == 0`.

#### F10. Token budget enforcement: warn fires only AFTER per-batch encode, but the brief implies a per-chunk warning
- **What.** Lines 536–545: the WARNING log fires once per paper, summarizing `truncated_total` for the entire paper. The brief's text "enforced by an assertion that logs a warning and truncates to 512 tokens rather than raising — truncation should be extremely rare" reads naturally as a per-chunk warning when truncation actually happens, so an operator can identify WHICH chunk overflowed. The current implementation says "5 of 200 chunks were truncated" without saying which ones.
- **Why it matters.** When ops sees truncation, they need to debug WHY (which preamble was huge, which body was huge, which kind). A summary warning loses the per-chunk identifiers.
- **Where.** `ingest/embedder.py:536–545`.
- **Fix sketch.** During the pre-count loop, when `len(ids) > MAX_TOKENS`, also log a debug-level message with `(paper_id, chunk_id, kind, len(ids))`. Keep the WARNING summary at paper level.

### LOW

#### F11. `_get_model` re-imports `torch` inside the function body (line 219) when it's already imported on line 201
- **What.** Lines 201–221 import `torch` twice: once at line 201 inside the `try:` block (suppressed import for `noqa: F401, PLC0415`), and once again at line 219. The second import is functionally a no-op due to module caching but stylistically redundant.
- **Why it matters.** Style. Reads as if the author was unsure whether the first import would survive the `try:` scope (it does — Python imports are cached on `sys.modules`).
- **Where.** `ingest/embedder.py:201, 219`.
- **Fix sketch.** Remove the second `import torch` at line 219; the first import already brings the name into scope.

#### F12. `_FakeTokenizer.encode` is a poor approximation of BGE-M3 token counts (word-split ≪ BPE token count)
- **What.** `_FakeTokenizer.encode` returns `list(range(len(text.split()) + 2))`. BGE-M3's real BPE tokenizer typically produces ~1.3–2.5x as many tokens as whitespace-split words for English math text. A test input of 1000 words → 1002 fake tokens → reliably triggers truncation; but a test input of 600 words → 602 fake tokens → triggers truncation, while the real tokenizer might produce 1500+ tokens. Tests cannot meaningfully exercise the boundary.
- **Why it matters.** Real-world boundary cases (preamble + body just barely over MAX_TOKENS) are not exercisable without a real tokenizer. The skipped real-model test (env-var-gated) is the only path.
- **Where.** `tests/test_embedder.py:140–143`.
- **Fix sketch.** Document in the fake's docstring that token counts are upper-bounds-by-construction; mention that real-tokenizer boundary exercise requires the env-var-gated path.

#### F13. `EmbedStats.to_dict()` is alphabetical-key-ordered but `_append_embed_stats` also passes `sort_keys=True` to `json.dumps` — redundant
- **What.** `to_dict()` builds the dict in alphabetical key order at the source; `json.dumps(..., sort_keys=True)` sorts again. The second sort is defensive but redundant. Keeping both is fine; the comment in `to_dict` could note that sorting is enforced at serialization.
- **Why it matters.** Minor — defensive duplication of sort discipline. No functional issue.
- **Where.** `ingest/embedder.py:143–154, 420`.
- **Fix sketch.** Optional: drop one of the two sorts and add a comment that the other is load-bearing.

#### F14. `TestPerPaperFailure.test_invalid_paper_id_raises` does not actually exercise per-paper failure isolation in `embed_corpus`
- **What.** The test invokes `embed_paper("../etc/passwd")` directly (which validates outside the envelope and raises). The class is named `TestPerPaperFailure` but the test scenario is "invalid paper_id at API entry", not "per-paper failure during corpus iteration". A test that stages multiple papers, makes one of them raise inside the encode path, and asserts the others still succeed is missing.
- **Why it matters.** The brief says `embed_corpus` should isolate per-paper failures. There's no test that proves it does.
- **Where.** `tests/test_embedder.py:563–570`.
- **Fix sketch.** Add a test: stage 2 papers, monkeypatch `_load_chunks` to raise `OSError` for paper 1, assert paper 2 still succeeds and `embed_corpus` returns 2 results with `[0].status == "fail"`, `[1].status == "ok"`.

#### F15. `embed_corpus(corpus_path=...)` parameter shadows the natural reading of "corpus" as the LanceDB-backed corpus
- **What.** The brief signature is `embed_corpus(lancedb_path: str, corpus_path: str, batch_size: int = 32)`. The implementation makes BOTH `lancedb_path` and `corpus_path` optional with `None` defaults. The brief shows them as required positional. While the optional default of `None` is operationally convenient (defaults read from `CHUNKS_DIR`), the signature now diverges from the brief.
- **Why it matters.** Brief signature compliance — if E04_S01 imports `embed_corpus` and calls it as `embed_corpus(lancedb_path, corpus_path, batch_size)` with positional args, the call still works because the parameter ordering is preserved, but the type annotation drift (`str | None` vs `str`) is a minor API surface change.
- **Where.** `ingest/embedder.py:596–599`.
- **Fix sketch.** Either keep `str | None` defaults but add a comment that the brief signature has been intentionally widened; or restore `str` and require callers to pass the path explicitly.

## What was done well
- Single source of truth for `BGE_M3_COMMIT_SHA` is enforced by an actual test (`TestModuleContract.test_bge_m3_commit_sha_defined_exactly_once`) that scans the entire `ingest/` tree — solid defensive testing of a critical invariant.
- Threat 6 compliance is excellent: `revision=BGE_M3_COMMIT_SHA, trust_remote_code=False`, both model AND tokenizer pinned, with dedicated `TestThreat6` tests asserting the exact load kwargs.
- Atomic NPZ writes via tmp + `os.replace` correctly mirror `preamble._write_preamble_json`'s discipline; the `np.savez`-auto-extension footgun is documented inline at line 340–345 — that's exactly the kind of hard-won subtlety future maintainers need.
- `model.eval()` is called explicitly with a docstring that calls out exactly why (XLM-RoBERTa dropout would otherwise produce non-deterministic vectors and break BP1) — better than a comment-free `model.eval()` call.
- F3 fallback (`preamble_text = ""` when `load_preamble` returns `None`) mirrors the chunker's discipline and has a dedicated test.
- NFC normalization is applied in `_build_embed_input` with explicit reference to BP1 byte-stability and tokenizer discipline.
- The reuse of `_validate_paper_id` and `_sanitize_log_field` from `ingest.chunker` rather than re-implementing them means the security regex hardening from E02_S01 is automatically inherited (Threat 1).
- `PER_PAPER_FAILURE_EXCEPTIONS = (OSError, ValueError, FileNotFoundError)` discipline matches `chunker.py` exactly; programmer-bug exceptions intentionally propagate.
- The lazy `_get_model` / `_get_tokenizer` pattern means importing `ingest.embedder` does not download 2.3 GB on import, which is essential for testability and for the chunker's lighter-weight pipeline.
- Routing rule `column = "embedding_proof" if kind == "proof" else "embedding_stmt"` is future-proof against new chunker `kind` values (lemma, proposition, corollary, etc., all of which the chunker emits per `_THEOREM_ENV_KINDS`).

## Recommended rectification order
1. F1 (HIGH — failed runs missing from embed-stats.jsonl)
2. F2 (HIGH — corpus run-summary entry missing)
3. F7 (MEDIUM — chunker tokenizer pinning, one-line Threat 6 fix)
4. F4 (MEDIUM — distinguish manifest-missing vs chunk-missing failures)
5. F6 (MEDIUM — fake model produces near-degenerate vectors)
6. F9 (MEDIUM — document zero-row NPZ array semantics + lock the negative)
7. F8 (MEDIUM — assert `embedding_eq` absent in NPZ)
8. F3 (MEDIUM — truncation-count tokenizer drift)
9. F10 (MEDIUM — per-chunk debug log on truncation)
10. F5 (MEDIUM — document NPZ kwarg ordering as load-bearing)
11. F14 (LOW — add a real per-paper-failure-isolation test)
12. F15 (LOW — signature drift from brief)
13. F12 (LOW — fake-tokenizer docstring on token-count approximation)
14. F11 (LOW — duplicate torch import)
15. F13 (LOW — duplicate sort_keys discipline)

## Rectification status

Phase 4 ran in the orchestrator's main session. All HIGH and most MEDIUM
findings landed in a single `rect(E03_S01)` commit; LOW findings were
deferred per the milestone-pipeline rectifier contract.

| ID | Severity | Status | Notes |
|---|---|---|---|
| F1 | HIGH | **fixed** in `rect(E03_S01)` | failure path now appends to `embed-stats.jsonl` via `_append_embed_stats(stats)`; regression test `test_failure_writes_fail_status_to_jsonl` |
| F2 | HIGH | **fixed** in `rect(E03_S01)` | `embed_corpus` now appends an `event="run_summary"` JSONL line via new `_append_run_summary` helper; regression test `test_run_summary_appended_to_jsonl` |
| F3 | MEDIUM | **fixed** in `rect(E03_S01)` | truncation pre-pass now uses single `tokenizer(texts, padding=False, truncation=False, return_length=True)` call matching the encode call style |
| F4 | MEDIUM | **fixed** in `rect(E03_S01)` | added `_ChunkFileMissingError` / `_ManifestCorruptError` / `_ChunkJsonCorruptError` subclasses + `EmbedStats.error_class` enum field; regression test `test_error_class_chunk_missing` |
| F5 | MEDIUM | **fixed** in `rect(E03_S01)` | NPZ kwargs now alphabetical (`chunk_ids_proof, chunk_ids_stmt, embedding_proof, embedding_stmt`); regression test `test_npz_keys_are_alphabetical` locks the order |
| F6 | MEDIUM | **fixed** in `rect(E03_S01)` | `_FakeOutput` now uses seeded `torch.randn` per row so post-L2-normalization vectors are distinguishable; the previous colinear-rows construction was bug-camouflaging |
| F7 | MEDIUM | **fixed** in `rect(E03_S01)` | `ingest/chunker.py:_get_tokenizer` now passes `revision=BGE_M3_COMMIT_SHA`; lazy import inside the function avoids the chunker→embedder→chunker cycle; regression test `test_chunker_tokenizer_loaded_with_pinned_revision` |
| F8 | MEDIUM | **fixed** in `rect(E03_S01)` | added `assert "embedding_eq" not in npz.files` to `test_kind_section_definition_route_to_embedding_stmt` |
| F9 | MEDIUM | **fixed** in `rect(E03_S01)` | `_write_embeddings_npz` docstring now documents the zero-row sentinel semantics explicitly; consumers MUST check `len(chunk_ids_*) > 0` not key presence |
| F10 | MEDIUM | **fixed** in `rect(E03_S01)` | `_encode_batch` now accepts `chunk_ids` and emits per-chunk DEBUG log on truncation; paper-level WARNING summary still fires |
| F11 | LOW | **fixed** in `rect(E03_S01)` | duplicate `import torch` in `_get_model` removed — folded into the rect commit since it's a one-liner trivially adjacent to F3/F10 changes |
| F12 | LOW | deferred | fake-tokenizer docstring approximation note |
| F13 | LOW | deferred | redundant `sort_keys=True` discipline |
| F14 | LOW | **fixed** in `rect(E03_S01)` | added `test_per_paper_failure_isolation` that stages 2 papers, makes one fail mid-corpus, asserts the other still completes and `run_summary.fail_count == 1` |
| F15 | LOW | deferred | `embed_corpus` signature widening (`str | None` defaults) |

**Test count:** 26 → 31 embedder tests (5 new regression tests). Full
suite: 352 passed, 1 skipped, ruff clean.
