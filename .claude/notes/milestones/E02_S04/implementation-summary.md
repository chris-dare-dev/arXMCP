# E02_S04 — Implementation summary

**One-line:** Content-addressable chunk_id (`arxiv:<paper_id>:<sha256(preamble_text + NFC(body_text))[:16]>`), single-source CHUNKER_VERSION constant in `chunker_types.py`, per-paper `chunk_manifest.json` written via the same atomic tmp+rename pattern from E02_S02.

**Implementation path:** Inline. Synthesis was unambiguous after both researchers converged on every load-bearing decision.

**Commit range:** Single commit on top of `802520d`.

## Acceptance criteria

| Criterion | Status |
|---|---|
| chunk_id matches `arxiv:<paper_id>:<sha256(preamble_normalized + body_text)[:16]>` exactly | Pass — TestChunkIDFormat (4 tests including the formula-pin) |
| Re-running chunker on unchanged paper produces byte-identical chunk_ids | Pass — TestChunkIDDeterminism::test_two_runs_same_paper_identical_ids |
| Modifying body_text produces a different chunk_id | Pass — TestChunkIDDeterminism::test_body_mutation_changes_chunk_id |
| chunker_version == "v1.0" on every chunk; defined as a single constant | Pass — TestChunkerVersionConstant (3 tests) |
| chunk_manifest.json exists for every paper after a chunker run | Pass on fixture — TestChunkManifest (6 tests). 50-paper integration deferred to user verification |
| CHUNKER_VERSION is the only place "v1.0" is defined | Pass — TestSingleVersionDefinition::test_v1_0_literal_count_in_chunker_modules (chunker.py = 0, chunker_types.py = 1) |

## Architectural decisions (made during synthesis)

1. **CHUNKER_VERSION lives in `chunker_types.py`, not `chunker.py`.** The brief literal text said `chunker.py`, but the dataclass default needs to reference the constant; defining it in `chunker.py` would create a circular import (`chunker.py` already imports `ChunkRecord` from `chunker_types.py`). Both researchers independently flagged this and recommended `chunker_types.py`. The acceptance criterion ("the only place `"v1.0"` is defined") is satisfied: literal count in `chunker.py = 0`, in `chunker_types.py = 1`.

2. **Hash input includes NFC normalization of `body_text`.** The stored `body_text` is left unchanged; only the hash sees the normalised form. Mirrors the discipline `tokenize_body` uses for BM25 input. Without this, two hosts with different default Unicode forms could produce different chunk_ids for the same logical content.

3. **Empty-string fallback for missing preamble.** When `extract_preamble` raises (F3 graceful path), `_resolve_preamble_doc` returns None and `preamble_text = ""`. The chunk_id remains content-addressable on body_text alone — stable across re-runs, just preamble-independent.

4. **Output filenames use the 16-char hash suffix** (`<hash_suffix>.json`), not the legacy `idx<N>.json`. Avoids colon-in-filename portability issues and aligns the on-disk artifact with its content-addressable identity.

5. **`_resolve_preamble_ref` renamed to `_resolve_preamble_doc`** and now returns the full `PreambleDoc | None` instead of just `preamble_hash`. The chunker pulls both `preamble_hash` (→ `chunk.preamble_ref`) and `preamble_text` (→ chunk_id hash input) from the same call. Avoids a second `extract_preamble` call.

6. **TOKENIZER_VERSION (E02_S03) and CHUNKER_VERSION (E02_S04) are independent constants.** Both happen to be `"v1.0"` but track different invariants — `CHUNKER_VERSION` invalidates chunk_id hashes (structural chunking change); `TOKENIZER_VERSION` invalidates `body_tokens` BM25 cache (tokenizer regex change).

7. **64-bit collision handling.** The `[:16]` SHA-256 prefix gives ~1-in-90k collision probability across 20M chunks (200K-paper end state). The implementation additionally fails loudly on any duplicate `chunk_id` per paper via a `seen_chunk_ids` set check — so a real collision (or a logic bug producing identical content) surfaces as a clean error rather than a silent file-overwrite.

## New / changed files

- `ingest/chunker_types.py` — `CHUNKER_VERSION = "v1.0"` constant; field default uses `field(default=CHUNKER_VERSION)`.
- `ingest/chunker.py` — added `_compute_chunk_id`, `_write_chunk_manifest`; renamed `_resolve_preamble_ref` → `_resolve_preamble_doc` and returns `PreambleDoc | None`; chunk_ids now stamped after collection (post `preamble_ref`/`body_tokens` wire-ins); output filenames use hash suffix; manifest written last.
- `tests/test_chunker_ids.py` (new) — 22 tests across TestChunkIDFormat, TestChunkIDDeterminism, TestChunkerVersionConstant, TestChunkManifest, TestOutputFilenames, TestSingleVersionDefinition.
- `tests/test_chunker.py` — `test_chunk_ids_monotonic` rewritten to `test_chunk_ids_content_addressable_format` (asserts the new pattern); existing `test_output_*` tests now filter `chunk_manifest.json` from the per-chunk JSON sweep.
- `tests/test_preamble.py` — F3 source-check test updated to reference the renamed `_resolve_preamble_doc` function.

**Test result:** `make test PYTHON=python3.13` → 282 passed (260 prior + 22 new), 0 failed, ruff clean.

## External writes

| type | target | why |
|---|---|---|
| filesystem write | `ingest/chunker.py`, `ingest/chunker_types.py`, `tests/test_chunker_ids.py`, `tests/test_chunker.py`, `tests/test_preamble.py` | new + modified source files; committed |
| filesystem write | `var/arxmcp/corpus/chunks/<paper_id>/<hash_suffix>.json` (×N per paper) | renamed runtime output; gitignored |
| filesystem write | `var/arxmcp/corpus/chunks/<paper_id>/chunk_manifest.json` | new per-paper manifest; gitignored |

No git push, PR, ticket, infra mutation, or third-party API call.

## Out of scope (deferred to later milestones)

- LanceDB MVCC version-bump handling (E04_S02). The chunker_version on stored rows is now consumable by the writer.
- Re-embed skip logic (E03_S02). The embedder will read `chunker_version` and re-embed only when it changes.
- Eval harness query fixture curation (E05_S01). The manifest schema is now fixed for the eval harness to consume.
