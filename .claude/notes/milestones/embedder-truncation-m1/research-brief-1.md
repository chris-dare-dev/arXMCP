# Research Brief — embedder-truncation-m1

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-27T21:15:00Z

---

## In-codebase context

### Token budget constants (load-bearing, verbatim from `ingest/chunker.py:86-90`)

```python
BGE_M3_MAX_TOKENS = 512
PROOF_HEADER_RESERVE = 64
PROOF_MAX_TOKENS = BGE_M3_MAX_TOKENS - PROOF_HEADER_RESERVE  # 448
PROOF_WINDOW_OVERLAP = 64
STMT_MAX_TOKENS = BGE_M3_MAX_TOKENS  # preamble headroom is E02_S02's responsibility
```

The `PROOF_WINDOW_OVERLAP` constant is NOT in the brief's target list but must not regress. Only touch `BGE_M3_MAX_TOKENS`, `PROOF_MAX_TOKENS`, and `STMT_MAX_TOKENS`.

### The smoking-gun call site (verbatim from scan brief, confirmed at `ingest/embedder.py:415-420`)

```python
pre = tokenizer(
    texts,
    padding=False,
    truncation=False,
    return_length=True,
)
```

The `add_special_tokens` kwarg is absent — defaults to `True`, adding CLS+SEP (+2). The downstream encoding call at line 437 uses `add_special_tokens=True` implicitly (via `padding=True, truncation=True, max_length=MAX_TOKENS`) which is CORRECT — CLS+SEP are required for BGE-M3 sentence-level embeddings. **Only the pre-pass at line 415 needs `add_special_tokens=False`.**

`MAX_TOKENS = 512` is defined at `ingest/embedder.py:128`. This must be raised to 2048 for change B.

### CHUNKER_VERSION flow into chunk_id hashing

`CHUNKER_VERSION = "v1.0"` lives at `ingest/chunker_types.py:45` (single source of truth). It flows into:
1. Every `ChunkRecord.chunker_version` field (dataclass default, `chunker_types.py:121`)
2. Per-paper `chunk_manifest.json` written by the chunker
3. The embedder's re-embed skip logic: `ingest/embedder.py:93` — `from ingest.chunker_types import CHUNKER_VERSION as EXPECTED_CHUNKER_VERSION` — a bump forces re-embed for every paper whose sidecar carries the old version

The `chunk_id` hash itself is `sha256(preamble_text + NFC(body_text))[:16]` — it does NOT include `CHUNKER_VERSION` in the hash input. This is correct: changing the budget constant changes which `body_text` the chunker emits (longer bodies pass through without truncation), so chunk_ids rotate naturally via content change, not via version string injection. **A version bump does NOT by itself rotate unchanged chunks** — only chunks whose body_text changes (previously-truncated ones) get new IDs. The brief's "chunk_id hashes change deterministically" for B-2 should be read as: previously-truncated chunks get new IDs because their bodies grow.

From `chunker_types.py` comments: "If you ever change `_compute_chunk_id` itself ... every chunk_id rotates even for byte-identical content. That is a SCHEMA migration, NOT a chunker_version bump." This milestone does NOT touch `_compute_chunk_id`; the `TestChunkerVersionFreeze` SHA pin at `tests/test_re_embed.py:756` (`EXPECTED_COMPUTE_CHUNK_ID_SHA256 = "6a49d455..."`) does NOT need re-pinning.

### Tests that WILL break on CHUNKER_VERSION bump (`"v1.0"` → `"v1.1"`)

1. **`tests/test_chunker.py::TestFixtureSuite::test_chunker_version_matches_constant_globally`** — checks all 10 fixture `.expected.json` files for `"chunker_version": "v1.0"`. Will fail until all 10 files are regenerated.
2. **`tests/test_chunker.py::TestFixtureSuite::test_expected_chunk_ids_in_document_order`** — fixture `expected_chunk_ids` lists will be stale for any fixture containing a statement/section chunk whose body_text exceeds 1920/2048 new thresholds. All 10 synthetic fixtures are small (designed to exercise behavior, not stress token budgets), so their chunk bodies likely all fit within 1920 tokens and chunk_ids should remain stable. **Verify by inspection after bump.**
3. **`tests/test_chunker.py` (and `test_chunker_ids.py`) literal `"v1.0"` checks** — `test_chunker_version_on_all_chunks` (line 160) asserts `chunk.chunker_version == "v1.0"` directly. Must update to `"v1.1"`.
4. **`tests/test_chunker_ids.py::TestSingleVersionDefinition::test_v1_0_literal_count_in_ingest_package`** — counts `"v1.0"` occurrences in `ingest/`. Once `chunker_types.py` is updated to `"v1.1"`, the count of `"v1.0"` in `chunker_types.py` drops to 0, but the test allows 1 occurrence for it. This test must be updated to look for `"v1.1"` instead.
5. **`tests/test_embedder_idempotent.py`** — references `CHUNKER_VERSION` via import (not hardcoded), so it survives the bump.
6. **`tests/eval/fixtures/queries.json`** — contains `"chunker_version": "v1.0"` but has zero queries (`"queries": []`). Must update to `"v1.1"` per the chunker-fixtures runbook (step 3 of regeneration procedure).

Per `.claude/docs/chunker-fixtures.md` § "Regenerating after a chunker change" (verbatim): "All three changes (chunker, fixture goldens, eval queries) [must land] in **one commit** so the repo is never in a state where `pytest tests/test_chunker.py::TestFixtureSuite::test_chunker_version_matches_constant_globally` fails."

### Design notes that apply

- **`04-parsing-and-chunking.md` § Rule 1**: "Theorem + proof are one chunk... A bare theorem statement is a retrieval black hole." Statement truncation directly violates this.
- **`04-parsing-and-chunking.md` § Chunker versioning step 4**: "Atomic-swap the LanceDB version alias the MCP server reads." — B-4 maps to this; `write_corpus_version_marker` in `ingest/store.py:476` is the mechanism.
- **`07-multi-agent-caching.md` § Property 1**: "Pin tool JSON schemas... A casual edit to a tool description blows every sub-agent's cache." X-1 confirms no tool schema change; EXPECTED_TOOL_SCHEMA_SHA256 must remain unchanged.
- **`07-multi-agent-caching.md` § Property 2**: chunk_ids must remain deterministic. Bumping the budget changes bodies of previously-truncated chunks deterministically — correct.

### LanceDB datasets (counted via `count_rows()`)

| Dataset | Table | Row count |
|---|---|---|
| `var/arxmcp/notebooks/bridgeland-stability/lancedb` | `chunks` | 6804 |
| `var/arxmcp/notebooks/shimura-varieties/lancedb` | `chunks` | 3625 |
| `var/arxmcp/index/lancedb` | (not present) | 0 |

**Total: 10,429 rows across 2 LanceDB datasets.** The `demo-nb` and `csrf-victim` notebook directories exist but have no `lancedb/` subdirectory. No shared `var/arxmcp/index/lancedb` dataset exists yet.

Current `corpus-version.json` state:
- bridgeland-stability: `version: 369`, `chunker_version: "v1.0"`
- shimura-varieties: `version: 49`, `chunker_version: "v1.0"`

---

## Prior decisions and lessons

### Git log (last 20 commits, relevant)

- `f187af4` — `textbook-ingest-m1`: added `textbook:<slug>` to `_PAPER_ID_RE` in `chunker.py` and `identifiers.py`. Byte-equality test `test_chunker_pattern_equals_canonical` enforces these stay in sync. This milestone does NOT touch `_PAPER_ID_RE`, so no risk here.
- `97cc9ef` — unknown theorem env names mapped to `"stmt"` + short-form aliases. This expanded the `_THEOREM_ENV_KINDS` dict. A CHUNKER_VERSION bump is appropriate when chunk behavior changes — the prior bump was deferred here; this milestone is the first legitimate reason to bump to `"v1.1"`.

### TestSingleVersionDefinition constraint

`tests/test_chunker_ids.py::TestSingleVersionDefinition::test_v1_0_literal_count_in_ingest_package` scans ALL `.py` files in `ingest/` for the string `"v1.0"`. It expects exactly 1 occurrence in `chunker_types.py` and 1 in `tokenizer.py`. After the bump: the test must be updated to scan for `"v1.1"` in `chunker_types.py` (1 occurrence) and ensure `tokenizer.py` still has `"v1.0"` for `TOKENIZER_VERSION` (that does not change). **The test must also be updated to allow `"v1.1"` for `chunker_types.py`, not 0.**

### Eval fixture baseline for B-3

`tests/eval/fixtures/queries.json` has `"queries": []` — the eval fixture is a stub. **B-3 cannot be verified by running `make eval`** because there are no queries. The implementer should record "baseline nDCG@5 = N/A (stub fixture)" in the implementation summary. B-3 passes vacuously; the spirit of the criterion is satisfied by the CHUNKER_VERSION bump triggering a re-embed that preserves LanceDB integrity, not by an actual nDCG measurement.

### BP1/BP2 SHA pinning

Neither `server/prompts.py` nor `server/tools.py` are touched. `EXPECTED_TOOL_SCHEMA_SHA256` (X-1) and `EXPECTED_BP1_SHA256` (X-2) do not change. The cache note (`07-multi-agent-caching.md`) is satisfied.

### PROOF_HEADER_RESERVE and proof windows

The scan brief recommends `PROOF_HEADER_RESERVE = 128` (up from 64) to give 192 tokens of headroom in proof windows. But the brief's AC targets `PROOF_MAX_TOKENS: 448 → 1856` (i.e. `2048 - 192 = 1856`), which implies `PROOF_HEADER_RESERVE = 192` or just setting `PROOF_MAX_TOKENS = 1856` directly. The brief is explicit: `PROOF_MAX_TOKENS: 448 → 1856`. Use the brief's numbers, not the scan brief's slightly different suggestion.

---

## External sources

**BGE-M3 HuggingFace model card** (https://huggingface.co/BAAI/bge-m3, fetched 2026-05-27):

> "multilingual; unified fine-tuning (dense, sparse, and colbert) from bge-m3-unsupervised"
> Sequence Length: **8192**

The model card states BGE-M3 supports inputs "of different granularities, spanning from short sentences to long documents of **up to 8192 tokens**." The usage example shows `max_length=8192` as the default and explicitly states: "If you don't need such a long length, you can set a smaller value to speed up the encoding process."

**No 512-token hard limit exists at the model or tokenizer config level.** The 512 limit in the codebase is a project-imposed constant (`MAX_TOKENS = 512` in `embedder.py`, `BGE_M3_MAX_TOKENS = 512` in `chunker.py`). Raising to 2048 requires only changing these constants — no model-config change, no tokenizer config change, no new dependency. 2048 is well within the native 8192 capability.

**Embedding dimension (1024) is unchanged at any context length.** LanceDB schema and ANN index remain byte-compatible.

---

## Recommendation

**Implement in this order:**

1. **Change C first** (one line): at `ingest/embedder.py:415`, add `add_special_tokens=False` to the pre-pass tokenizer call. Add one synthetic regression test (`TestTokenBudget` class in `tests/test_embedder.py` is the right home) that stages a chunk with `truncated=False` and asserts `truncated_count == 0` after the pre-pass. Add a grep-based test (C-2) that asserts `add_special_tokens=False` appears at the pre-pass call site.

2. **Change B**: raise constants in `chunker.py` (`BGE_M3_MAX_TOKENS=2048`, `STMT_MAX_TOKENS=1920`, `PROOF_MAX_TOKENS=1856`) and `embedder.py` (`MAX_TOKENS=2048`). Bump `CHUNKER_VERSION` in `chunker_types.py` from `"v1.0"` to `"v1.1"`. Update `TestSingleVersionDefinition` in `test_chunker_ids.py` to scan for `"v1.1"`. Regenerate all 10 chunker fixture `.expected.json` files per the runbook (the `_compute_chunk_id` function is unchanged so only previously-truncated fixture chunks get new IDs — and synthetic fixtures likely have none). Update `tests/eval/fixtures/queries.json` `"chunker_version"` to `"v1.1"`. Update hardcoded `"v1.0"` strings in test assertions (`test_chunker_version_on_all_chunks`, `test_default_chunker_version`, `test_all_chunks_have_chunker_version`). Add the B-2 test asserting version-bump invalidates old sidecar.

3. **Run re-embed** on all 2 LanceDB datasets (10,429 total rows, ~137 papers). Expect B-4 corpus-version.json to advance +1 on each.

4. **Update docs** per B-5: `.claude/notes/04-parsing-and-chunking.md` token budget section + `.claude/docs/chunker-fixtures.md` version note.

---

## Open questions

1. **B-3 baseline is N/A**: `tests/eval/fixtures/queries.json` has zero queries. B-3 cannot be evaluated. The implementer should record "eval fixture is stub; B-3 N/A, passes vacuously" in the implementation summary and proceed. No action required before writing code.

2. **`test_chunker_version_on_all_chunks` exact location**: lines 157-160 and 313-316 in `tests/test_chunker.py` both assert `chunk.chunker_version == "v1.0"` literally. The implementer must grep for ALL literal `"v1.0"` strings in `tests/` (not just `ingest/`) and update them. The test at line 778 (`test_default_chunker_version`) also asserts `record.chunker_version == "v1.0"`. Total: ~4 locations in `tests/test_chunker.py`, plus `TestSingleVersionDefinition` in `test_chunker_ids.py`.

3. **Fixture chunk_id stability check**: all 10 synthetic fixtures use small HTML designed to exercise behavior, not fill token budgets. None likely hit 1920 tokens in a statement body. Confirm by running the chunker on each fixture after the bump and comparing IDs — the runbook procedure handles this. No risk of surprise ID rotations on synthetic fixtures.

**No other open questions — implementation can proceed on the above recommendation.**

---

## External writes the implementation will require

None — this milestone is purely local. The re-embed run is local CPU; no API calls, no git push, no PRs, no infra mutations.
