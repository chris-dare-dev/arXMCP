# Research Synthesis — embedder-truncation-m1

**Generated:** 2026-05-27 (post-research-phase)
**Merge mode:** orchestrator (main session), two-brief standard merge
**Inputs:** `research-brief-1.md`, `research-brief-2.md`

---

## TL;DR

Implement C + B as scoped, with three explicit AC reframes that both
researchers either flagged or implied:

1. **B-2 AC was wrong as written.** `chunk_id` is body-content-addressable
   (`sha256(preamble_text + NFC(body_text))[:16]`), NOT version-keyed.
   The CHUNKER_VERSION field is metadata only. **Reframe:** the B-2 test
   asserts (a) re-emitted records carry `chunker_version="v1.1"` and
   (b) for a synthetic previously-truncated input, the chunk_id rotates
   because body_text grew, not because the version did.

2. **B-3 AC fixture path is the empty stub.** `tests/eval/fixtures/queries.json`
   has `"queries": []`. **Reframe:** measure against
   `var/arxmcp/notebooks/bridgeland-stability/queries.json` (10 curated
   queries with relevance labels). Pre-bump baseline is recorded in the
   implementation summary; post-bump must not regress.

3. **The re-embed is OPERATOR-DRIVEN, not pipeline-run.** Estimated
   3-8 hours of CPU compute (10,429 chunks × 4× longer × ~4× quadratic
   attention overhead). **Reframe:** Phase 2 implements the code +
   tests + a `make re-embed-all` driver; B-4 AC is verified by running
   the driver against a tiny synthetic dataset (subprocess test), not by
   running the full re-embed in the pipeline. The operator runs
   `make re-embed-all` at their cadence post-milestone.

---

## In-codebase context (merged, load-bearing constraints quoted verbatim)

### Token-budget constants (`ingest/chunker.py:86-90`)

```python
BGE_M3_MAX_TOKENS = 512
PROOF_HEADER_RESERVE = 64
PROOF_MAX_TOKENS = BGE_M3_MAX_TOKENS - PROOF_HEADER_RESERVE  # 448
PROOF_WINDOW_OVERLAP = 64
STMT_MAX_TOKENS = BGE_M3_MAX_TOKENS  # preamble headroom is E02_S02's responsibility
```

R1 + R2 both quoted this verbatim. Both note: only touch
`BGE_M3_MAX_TOKENS`, `STMT_MAX_TOKENS`, `PROOF_MAX_TOKENS`. Do NOT touch
`PROOF_HEADER_RESERVE` or `PROOF_WINDOW_OVERLAP`.

**Final target values (from roadmap brief):** `BGE_M3_MAX_TOKENS = 2048`,
`STMT_MAX_TOKENS = 1920`, `PROOF_MAX_TOKENS = 1856`. Implementation note:
`STMT_MAX_TOKENS` and `PROOF_MAX_TOKENS` will be set as **literal
integers**, not as derived expressions, because the headroom semantics
differ (128 for stmt, 192 for proof).

### The smoking-gun call site (R1 confirmed at `ingest/embedder.py:415-421`)

```python
pre = tokenizer(
    texts,
    padding=False,
    truncation=False,
    return_length=True,
)
```

**Change C is exactly one line:** add `add_special_tokens=False` to this
call. The downstream encoding call at line 437 (`padding=True,
truncation=True, max_length=MAX_TOKENS`) MUST retain the default
`add_special_tokens=True` — CLS+SEP are required for correct XLM-RoBERTa
sentence-level embeddings.

`MAX_TOKENS = 512` at `ingest/embedder.py:128` must also be raised to
2048 for change B.

### `chunk_id` mechanics (R1 + R2 agree)

`chunk_id` format is `arxiv:<paper_id>:<sha256(preamble_text +
NFC(body_text))[:16]>`. From `chunker_types.py` comments (R1 quote):

> "If you ever change `_compute_chunk_id` itself ... every chunk_id
> rotates even for byte-identical content. That is a SCHEMA migration,
> NOT a chunker_version bump."

This milestone does NOT touch `_compute_chunk_id`. Therefore:
`TestChunkerVersionFreeze::EXPECTED_COMPUTE_CHUNK_ID_SHA256 =
"6a49d455..."` at `tests/test_re_embed.py:756` stays pinned. **No
SHA re-pin for the chunk_id function itself.**

The CHUNKER_VERSION bump from `"v1.0"` to `"v1.1"` rotates only:
- The `chunker_version` field on every `ChunkRecord`
- The `chunk_manifest.json` per-paper sidecar version field
- The embedder's re-embed skip-logic comparison (forces re-embed)

Chunks whose body_text is unchanged (i.e., were never truncated at the
old budget) keep the same `chunk_id` hex suffix. Chunks whose body_text
grows under the new budget get a new hex suffix because body_text
changed. **This is the design intent, not a bug.**

### LanceDB dataset inventory (both researchers, verified via `count_rows()`)

| Dataset | Table | Row count | Current corpus_version |
|---|---|---|---|
| `var/arxmcp/notebooks/bridgeland-stability/lancedb` | `chunks` | 6,804 | 369 |
| `var/arxmcp/notebooks/shimura-varieties/lancedb` | `chunks` | 3,625 | 49 |
| `var/arxmcp/index/lancedb` | (absent) | 0 | n/a |

**Total re-embed scope: 10,429 chunks across 2 LanceDB datasets.**
Shared arXiv corpus is empty — no chunks to re-embed there. The
`demo-nb` and `csrf-victim` notebook dirs have no `lancedb/` subdir.

### `re_embed.py` IS NOT multi-dataset-aware (R2 FM-4, HIGH)

`ingest.re_embed.run_re_embed(active_lancedb_path=...)` takes a single
path. **Driver loop is missing.** The roadmap brief says "re-embed
every paper in every LanceDB dataset under
`var/arxmcp/notebooks/<slug>/lancedb/`" but the existing function
doesn't enumerate. **Mitigation:** add a `make re-embed-all` Makefile
target that discovers via `glob("var/arxmcp/notebooks/*/lancedb/")`
plus the active shared path if non-empty, and calls `run_re_embed()`
per dataset. R2 preferred a CLI flag `--all-datasets`; I prefer the
Makefile target — it matches the existing `make ingest`/`make eval`
pattern and keeps `re_embed.py` single-responsibility.

### Tests that break on `CHUNKER_VERSION` bump (R1 enumeration, verified count = 6 locations)

1. `tests/test_chunker.py::TestFixtureSuite::test_chunker_version_matches_constant_globally` — checks all 10 fixture `.expected.json` files for `"chunker_version": "v1.0"`.
2. `tests/test_chunker.py::TestFixtureSuite::test_expected_chunk_ids_in_document_order` — fixture `expected_chunk_ids` may rotate IF a fixture's body crosses the new 1920-token boundary. R1 inspected: all 10 synthetic fixtures are small and likely safe — verify after regen.
3. `tests/test_chunker.py` literal `"v1.0"` assertions at ≥ 4 line ranges (~157-160, ~313-316, ~778).
4. `tests/test_chunker_ids.py::TestSingleVersionDefinition::test_v1_0_literal_count_in_ingest_package` — scans `ingest/` for `"v1.0"` substring.
5. `tests/eval/fixtures/queries.json` `"chunker_version": "v1.0"` field (stub fixture, queries empty).
6. `var/arxmcp/notebooks/*/queries.json` may also pin `"chunker_version": "v1.0"` — verify and update if so (`bridgeland-stability/queries.json` was inspected this evening; the file does NOT have a `chunker_version` field, so no update needed — but verify `shimura-varieties/queries.json` too).

**`tests/test_embedder_idempotent.py` imports `CHUNKER_VERSION`** (not hardcoded) — survives the bump.

### `EMBED_BATCH_DEFAULT` concern (R2 FM-1, MEDIUM)

`ingest/embedder.py:133`: `EMBED_BATCH_DEFAULT = 32`. With XLM-RoBERTa
full attention (O(n²) in tokens), going 512 → 2048 is 4× length and
16× attention memory per chunk. Batch of 32 × 2048 tokens could blow
through CPU RAM.

**Decision:** lower `EMBED_BATCH_DEFAULT` from 32 → 8 unconditionally
in this milestone. The performance cost on small chunks (where 32 was
fine) is amortized over an embed pass dominated by the larger chunks
anyway. Note the change in the commit body. R2's alternative
(conditional on `MAX_TOKENS > 1024`) adds branching for negligible
benefit.

### Wall-clock expectation (R2 FM-5)

10,429 chunks × ~4× wall-clock per chunk (CPU O(n²) attention) ≈
**3-8 hours** of re-embed. Document in the implementation summary;
the operator runs `make re-embed-all` at their cadence. The pipeline
itself does NOT execute the re-embed.

### BP1/BP2 SHA byte-stability (X-1, X-2 — both researchers)

`server/tools.py::ALL_TOOLS` and `server/prompts.py` are NOT touched.
`EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_BP1_SHA256` stay pinned.
Verify by re-running their pin tests post-implementation.

### Design notes that apply

- **`04-parsing-and-chunking.md` § Rule 1:** "Theorem + proof are one
  chunk... A bare theorem statement is a retrieval black hole."
  → Statement truncation directly violates this; B remedies it.
- **`04-parsing-and-chunking.md` § Chunker versioning step 4:**
  "Atomic-swap the LanceDB version alias the MCP server reads."
  → B-4 maps to this; `write_corpus_version_marker` in
  `ingest/store.py:476` is the mechanism. The Makefile driver must
  honor this.
- **`07-multi-agent-caching.md` § Property 1:** "Pin tool JSON
  schemas... A casual edit to a tool description blows every sub-
  agent's cache." → X-1 satisfied by construction.
- **`07-multi-agent-caching.md` § Property 2:** chunk_ids must remain
  deterministic. Bumping the budget changes bodies of previously-
  truncated chunks deterministically — correct.
- **`chunker-fixtures.md` § "Regenerating after a chunker change"
  steps 0-4:** the regen procedure is the runbook — "All three
  changes (chunker source, fixture goldens, eval queries) [must
  land] in **one commit**."

### Snippet contract is unaffected (R2)

`snippet-contract.md`: snippet is the first 150 chars of `body_text`.
Longer chunks don't change the snippet (still 150-char prefix slice).
**No snippet-contract violation.**

---

## External sources (merged from R2)

- **BGE-M3 native context: 8192 tokens** (HuggingFace model card,
  `tokenizer_config.json:model_max_length = 8192` at pinned SHA
  5617a9f6). 2048 is well within native capability.
- **Embedding dim: 1024**, unchanged at any context length. **LanceDB
  ANN index byte-compatible.**
- **`max_position_embeddings = 8194`** (8192 + CLS + SEP). No
  FlashAttention — standard O(n²) full attention.
- **`add_special_tokens=True` is the HF tokenizer default.** This is
  the documented behavior; passing `add_special_tokens=False` in the
  pre-pass is the canonical idiom for length-without-special-tokens
  measurement.
- **No instruction prefix** required for BGE-M3 (unlike BGE-v1.5).

---

## Resolved disagreements

| # | R1 position | R2 position | Resolution |
|---|---|---|---|
| 1 | B-2 AC says "version bump changes chunk_id deterministically"; treats it as "previously-truncated chunks get new IDs because their bodies grow" | B-2 AC is **wrong as written**; the chunk_id hash is body-content-addressable and not version-sensitive; explicit reframe needed | **R2 wins on framing.** Both AGREE on the mechanic; R2 makes the AC reframe explicit. Test must assert (a) records carry `chunker_version="v1.1"` AND (b) a synthetic chunk whose body_text was previously truncated gets a new chunk_id post-bump. |
| 2 | B-3 "cannot be verified by running `make eval`" — passes vacuously | B-3 should use `var/arxmcp/notebooks/bridgeland-stability/queries.json` (10 populated queries) | **R2 wins.** Use the notebook fixture; record pre-bump baseline in implementation summary; tolerate ±0.05 noise (small-N). |
| 3 | Says "Run re-embed on all 2 LanceDB datasets" without flagging the gap | Explicitly flags: `run_re_embed()` is single-path; missing notebook-aware driver | **R2 wins.** Add `make re-embed-all` Makefile target. |
| 4 | Says use roadmap brief's `PROOF_MAX_TOKENS=1856`, contrasted with scan brief's "1920" suggestion | Confirms 1856 (192-token proof headroom) | **R1 = R2.** Apparent conflict was a misread of the scan brief; both say 1856 for proof, 1920 for stmt. Use those. |
| 5 | Doesn't address `EMBED_BATCH_DEFAULT` | Recommends lowering 32 → 8 due to O(n²) attention | **R2 wins.** Lower unconditionally to 8 in this milestone. Note in commit body. |

---

## Implementation plan (orchestrator decision: INLINE path)

Estimated LOC: ~50 hand-written + ~10 fixture regens × ~200 LOC each
of regenerated JSON. Files touched: ~10. At the boundary of inline-vs-
delegated; choosing INLINE because the changes are mechanical, the
synthesis is detailed, and the fixture regen is procedural.

**Sequence (single feat commit):**

1. **C — Embedder pre-pass fix.** Add `add_special_tokens=False` at
   `ingest/embedder.py:415`. Add regression test
   `tests/test_embedder.py::TestTruncationCount::test_pre_pass_excludes_special_tokens`
   that mocks the tokenizer to verify the fix without `requires_model`.

2. **B — Token budgets + version bump.**
   - `ingest/chunker.py`: `BGE_M3_MAX_TOKENS=2048`, `STMT_MAX_TOKENS=1920` (literal int), `PROOF_MAX_TOKENS=1856` (literal int).
   - `ingest/chunker_types.py`: `CHUNKER_VERSION = "v1.1"`.
   - `ingest/embedder.py`: `MAX_TOKENS=2048`, `EMBED_BATCH_DEFAULT=8`.

3. **Fixture regeneration** per `chunker-fixtures.md`: loop over the 10
   `_FIXTURE_SUITE_IDS` to regenerate `.expected.json` files. Update
   `tests/eval/fixtures/queries.json`'s `chunker_version` field.

4. **Test updates** (all literal `"v1.0"` → `"v1.1"` outside of
   `tokenizer.py`'s `TOKENIZER_VERSION`):
   - `tests/test_chunker.py` (~4 locations)
   - `tests/test_chunker_ids.py::TestSingleVersionDefinition` (scan
     pattern + count)
   - Add B-2 test
     `tests/test_chunker.py::TestVersionBumpInvalidatesOldSidecar`.

5. **Re-embed driver loop.** Add `make re-embed-all` Makefile target +
   small Python helper (`tools/re_embed_all.py` or extend
   `ingest/re_embed.py` with a thin `main()` that takes `--all-notebooks`).
   Add subprocess test
   `tests/test_re_embed.py::TestAllNotebooksDriver::test_glob_discovers_all_lancedb_datasets`
   against a `tmp_path` mock of `var/arxmcp/notebooks/*/lancedb/`.

6. **Docs:**
   - `.claude/notes/04-parsing-and-chunking.md`: update token-budget
     section with new constants and the math-fidelity rationale.
   - `.claude/docs/chunker-fixtures.md`: note the
     v1.0 → v1.1 bump as the canonical example of the procedure.

7. **Pre-commit and `make test`** must be green before the feat commit.

**Note for Phase 4 (rectify) and the operator:** the re-embed itself
(3-8 hours of CPU) does NOT run in this pipeline. The operator runs
`make re-embed-all` post-milestone at their cadence. B-4 AC is
verified by the subprocess test of the driver against a synthetic
dataset; the actual cutover is operator-driven.

---

## Open questions (consolidated, deduped)

1. **Confirm fixture chunk_id stability post-bump.** All 10 synthetic
   fixtures are designed to exercise behavior, not stress token
   budgets, so chunk_ids likely survive intact. The regen procedure
   handles either case. Implementer must run the chunker on each
   fixture post-bump and diff. No action needed before writing code;
   the runbook covers it.

2. **`shimura-varieties/queries.json` `chunker_version` field?**
   Verify whether this fixture pins the chunker version; if so, update
   in lockstep with the bump.

3. **Re-embed driver: separate file or extend `re_embed.py`?**
   Implementation choice. I lean: add a thin `tools/re_embed_all.py`
   wrapper + `make re-embed-all` target. Keeps `re_embed.py`'s
   single-path contract unchanged.

4. **Partial-failure semantics for the driver loop.** If notebook 1
   succeeds and notebook 2 fails mid-embed, what's the right behavior?
   `run_re_embed()` has resume via `re-embed-progress.json`. The
   driver should report per-dataset success/failure and exit non-zero
   on any failure — fail-loudly so the operator catches it.

---

## External writes the implementation will require

**None.** This milestone is purely local:

- No `git push`
- No `gh issue create` / `gh pr create`
- No external API calls
- No infra mutations
- The re-embed run is local CPU (deferred to operator post-milestone,
  not part of the implementation phase)

`external_writes_required = []` in state.json.

---

## Orchestrator synthesis note

Both researchers converged on the implementation shape but diverged
on AC framing. R2's failure-mode analysis (FM-1 through FM-8)
correctly surfaced two AC reframes (B-2 mechanics, B-3 fixture path)
and one new scope item (re-embed driver loop) that the original
roadmap brief glossed over. The synthesis adopts R2's reframes
verbatim because R1's narrative actually agreed on the mechanics — it
just didn't surface the reframe explicitly.

R1's strongest contribution: the precise enumeration of test
locations that break on the CHUNKER_VERSION bump (6 locations,
listed above). Implementation Phase 2 follows R1's punchlist there.

R2's strongest contribution: the `EMBED_BATCH_DEFAULT=32 → 8`
recommendation grounded in BGE-M3's full-attention O(n²) cost. Without
this, the re-embed would likely OOM on CPU for a 32-batch of 2048-
token inputs.

---

## Acceptance criteria (final, AFTER reframe)

| AC | Original | Final (post-synthesis) |
|---|---|---|
| C-1 | embedder pre-pass `truncated_count == 0` for non-truncated chunk; regression test | UNCHANGED |
| C-2 | call site at `ingest/embedder.py:415` passes `add_special_tokens=False`; grep-based assertion ok | UNCHANGED |
| B-1 | < 5% truncated rate on stmt/lemma/def/prop chunks for 1902.08184 canary | UNCHANGED. The canary is at `var/arxmcp/corpus/parsed/1902.08184/index.html` (already on disk). Implementer measures by running chunker on it and counting `truncated=True` records of `kind ∈ {stmt, lemma, def, prop}`. |
| B-2 | CHUNKER_VERSION bump changes chunk_id hash deterministically; explicit version-bump test | **REFRAMED:** records carry `chunker_version="v1.1"`; for a synthetic chunk whose body_text was previously truncated at 512 but now fits at 2048, the chunk_id rotates because body_text grew. Test asserts BOTH claims. |
| B-3 | nDCG@5 on `tests/eval/fixtures/queries.json` does NOT regress ±0.02 | **REFRAMED:** measure against `var/arxmcp/notebooks/bridgeland-stability/queries.json` (10 populated queries with relevance labels). Record pre-bump baseline in implementation summary; allow ±0.05 noise (small-N). |
| B-4 | corpus-version.json advances +1 per dataset; no orphan staging dirs | **REFRAMED:** the `make re-embed-all` driver, when run against a synthetic 2-dataset fixture, advances each `corpus-version.json` by +1 and leaves no `lancedb-staging` orphans. Verified by subprocess test in Phase 2. The actual production re-embed is operator-driven (3-8 hours estimated) and runs post-milestone. |
| B-5 | Doc updates to `.claude/notes/04-parsing-and-chunking.md` + `.claude/docs/chunker-fixtures.md` | UNCHANGED |
| X-1 | EXPECTED_TOOL_SCHEMA_SHA256 UNCHANGED | UNCHANGED |
| X-2 | EXPECTED_BP1_SHA256 UNCHANGED | UNCHANGED |
| X-3 | ruff + make test green; 2100+ tests passing | UNCHANGED |

**New AC added (scope clarification):**

| AC | Description |
|---|---|
| B-6 | `make re-embed-all` target exists, discovers `var/arxmcp/notebooks/*/lancedb/` via glob, calls `run_re_embed()` per dataset, propagates per-dataset success/failure to a non-zero exit on any failure. |
| B-7 | `EMBED_BATCH_DEFAULT` lowered from 32 to 8 (CPU O(n²) attention guard). Documented in commit body. |
