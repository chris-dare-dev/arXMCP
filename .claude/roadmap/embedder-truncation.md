# embedder-truncation — Chunker token-budget fix (C + B bundled)

**Owner:** Chris Dare
**Created:** 2026-05-27
**Status:** scoped
**Source:** post-ingest deep dive on the bridgeland-stability batch-3 run

**Related scan briefs (read these first):**

- [`.claude/notes/scans/chunk-truncation-and-skew-2026-05-27.md`](../notes/scans/chunk-truncation-and-skew-2026-05-27.md) — the smoking-gun
  finding (chunker truncation counts exactly equal embedder truncation
  counts) and the 1902.08184 honest-skew finding.
- [`.claude/notes/scans/preamble-without-raw-tex-2026-05-27.md`](../notes/scans/preamble-without-raw-tex-2026-05-27.md) — the
  companion finding on preamble extraction; **its own follow-up
  milestone, not bundled here.**

**Why bundled.** Both findings touch the same code surface (embedder
token budgeting). C is the trivial 1-line off-by-2 that makes B's
post-bump warning meaningful again. Shipping them apart would mean
re-running the same critique pass twice.

---

### embedder-truncation-m1 — Fix tokenizer special-tokens off-by-2 + raise BGE-M3 max to 2048

**Description.** Two changes, one commit triple:

1. **C — Embedder truncation-count off-by-2 (S, ≈30 min).** The
   pre-pass at [`ingest/embedder.py:415`](../../ingest/embedder.py:415)
   calls `tokenizer(...)` without `add_special_tokens=False`. The
   default `True` adds CLS+SEP (+2 tokens), so every chunk that the
   chunker emitted at exactly the 512-token cap gets re-counted as
   embedder-truncated. Scan brief found exact-match equality on every
   paper in the batch (46/46 on 1912.06504, 20/20 on 1912.06935,
   44/44 on 1902.08184). The actual embedding tokenizer call
   downstream MUST keep the default `add_special_tokens=True` — CLS+SEP
   are required for correct sentence-level embeddings. **Only the
   pre-pass tokenizer call changes.**

2. **B — Raise the BGE-M3 token budget from 512 to 2048 (M).**
   BGE-M3 supports native 8K-token context; the project caps at 512
   for historical reasons (see `ingest/chunker.py` token-budget
   constants). 70% of 1902.08184's chunker-truncated chunks are
   statement-class (`stmt`/`lemma`/`def`/`prop`); a truncated
   theorem statement is a direct math-fidelity hazard per
   [`.claude/notes/04-parsing-and-chunking.md`](../notes/04-parsing-and-chunking.md).
   Raise:

   - `BGE_M3_MAX_TOKENS`: 512 → **2048**
   - `STMT_MAX_TOKENS`: 512 → **1920** (128-token preamble headroom)
   - `PROOF_MAX_TOKENS`: 448 → **1856** (192-token headroom; proofs
     occasionally re-embed inline statements)

   Bump `CHUNKER_VERSION` so chunk_id hashes change deterministically;
   re-embed every paper in every LanceDB dataset under
   `var/arxmcp/index/lancedb/` (shared arXiv corpus) AND every
   `var/arxmcp/notebooks/<slug>/lancedb/` (per-notebook). Researcher
   agents must quantify the total chunk count and embed throughput
   to predict wall-clock; scan brief's ~40-min estimate covered only
   the 137 papers in the two notebook datasets.

   **No-fork compliance:** 2048 is within BGE-M3's native long-context
   capability, not a forked variant — no model swap, no new dep.

**Acceptance criteria.**

- **[C-1]** Given a chunker-emitted chunk where `chunk.truncated == False`,
  When the embedder runs its truncation pre-pass, Then the embedder's
  `truncated_count` for that chunk is 0. Add a regression test that
  fails today and passes after the fix.
- **[C-2]** Given the call site at `ingest/embedder.py:415` (or its
  current line if drift), When inspected, Then it passes
  `add_special_tokens=False`. A grep-based test or AST-based assertion
  is acceptable for stability.
- **[B-1]** Given `BGE_M3_MAX_TOKENS = 2048`, When the chunker is run
  on 1902.08184 (the canary — already on disk at
  `var/arxmcp/corpus/parsed/1902.08184/index.html`), Then fewer than
  5% of stmt/lemma/def/prop chunks are flagged `truncated=True`. The
  pre-fix baseline is the 70%-of-truncated-class number from the scan
  brief; quantify both pre- and post-numbers in the implementation
  summary.
- **[B-2]** Given `CHUNKER_VERSION` is bumped, When the chunk_id hash
  is computed for a known-input fixture, Then the hash changes
  deterministically. Add an explicit "version-bump invalidates old
  hashes" test in `tests/test_chunker.py` (or equivalent), not just
  the new constant value.
- **[B-3]** Given the re-embed of every LanceDB dataset, When
  `make eval` runs against the 20-query curated fixture from
  `tests/eval/fixtures/queries.json`, Then nDCG@5 does NOT regress
  relative to the pre-bump baseline. Allow ±0.02 noise floor; record
  the baseline numerically in the implementation summary.
- **[B-4]** Given the re-embed completes, When `corpus-version.json`
  in each LanceDB directory is read, Then the version advanced by
  exactly 1 and no orphan `lancedb-staging` directories remain on
  disk.
- **[B-5]** Documentation: update
  [`.claude/notes/04-parsing-and-chunking.md`](../notes/04-parsing-and-chunking.md)
  and [`.claude/docs/chunker-fixtures.md`](../docs/chunker-fixtures.md)
  to record the new token budgets and the BGE-M3 native long-context
  capability claim (with the model card link).
- **[X-1]** `EXPECTED_TOOL_SCHEMA_SHA256` UNCHANGED — no MCP surface
  edit. Pin the test value in the implementation summary as proof of
  no drift.
- **[X-2]** `EXPECTED_BP1_SHA256` UNCHANGED — no prompt-prefix edit.
  Same pin.
- **[X-3]** `ruff check .` clean and `make test` green; 2100+ tests
  passing on macOS / Linux (per the CLAUDE.md status snapshot).
  `requires_model` opt-in tests may be invoked but are not a hard
  gate.

**Out of scope (explicit Won't list).**

- The 1902.08184 chunk-count skew (725 chunks). Scan brief confirmed
  honest representation of a 200-page book-grade manuscript with 355
  `ltx_theorem_*` environments. Manage downstream via per-paper
  retrieval caps, not chunker truncation. Separate concern.
- Per-paper preamble back-fill from raw `.tex` (the
  preamble-without-raw-tex scan brief's recommendation). Its own
  milestone — DO NOT bundle here; it touches `tools/notebook_fetch.py`
  and `tools/arxiv_fetch.py`, not the embedder.
- Switching to a 32K-context embedder (JinaAI-v3, Stella, etc.).
  Out of scope; 2048 is within BGE-M3's native capability, so no-fork
  policy is honored and no model swap is needed.
- Re-embed of any operator-side corpus the researchers can't see
  (e.g. backups, archived snapshots). Limit scope to live LanceDB
  datasets reachable from the repo.

**Dependencies.** None.

**Complexity.** M (C is S, B is M; bundled as M overall).

**Specialist suggestions.** `determinism-reviewer` for the
`CHUNKER_VERSION` bump's effect on chunk_id stability;
`cache-stability-reviewer` to confirm no SHA re-pin is needed.

**External writes the implementation will require.** None — all
changes are local. The re-embed is local CPU; no API calls, no PRs,
no infra mutations.

**Notes for the researcher agents (phase 1).**

1. Quantify the total chunk count across all LanceDB datasets to
   predict re-embed wall-clock — scan brief covered only the 137
   notebook papers. Use `count_rows()` on each LanceDB.
2. Confirm via BGE-M3's HuggingFace model card that
   `max_position_embeddings ≥ 2048`. If anything pins a 512 limit at
   the tokenizer or model-config level, surface it — this would
   invalidate B and force a smaller bump.
3. Check whether any existing test fixtures (golden chunker outputs)
   pin specific chunk_ids that will need re-pinning after the
   `CHUNKER_VERSION` bump. The chunker-fixtures runbook at
   [`.claude/docs/chunker-fixtures.md`](../docs/chunker-fixtures.md)
   should cover the regen procedure; cite verbatim if so.
4. The `requires_model` test marker (per CLAUDE.md §4.5) means
   real-model tests are skipped by default — make sure the
   acceptance tests for C-1 and B-2 use synthetic inputs that don't
   need a real BGE-M3 download.
