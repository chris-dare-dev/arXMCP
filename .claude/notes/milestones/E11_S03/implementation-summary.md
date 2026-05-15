# E11_S03 — Implementation Summary

**One-line summary.** Partial re-embed driver
([ingest/re_embed.py](ingest/re_embed.py)) that exploits the
content-addressable chunk_id contract to limit GPU work to chunks
whose content actually changed. Includes the F1-class copy-path
guard, the embedding-space-mixing guard, LanceDB-write-side
`--resume`, atomic state-file checkpointing, scenario-by-scenario
GPU-hours runbook, `make re-embed` target, and a
schema-migration constraint on `_compute_chunk_id` documented in
`ingest/chunker_types.py`.

**Commit range.** `7c2bdea..HEAD`.

---

## Scope reminder

The synthesis re-shaped the brief along three axes (see
[research-synthesis.md](research-synthesis.md) D1–D15):

1. **GPU throughput corrected.** Brief's 32 c/s is the `EMBED_BATCH_DEFAULT`
   *CPU* constant, NOT GPU throughput. Real GPU runs see 100–400
   c/s on A6000. Runbook documents ranges (3.5–14h for 5M
   chunks, not 44h).
2. **Code guard, not just a runbook warning.** The brief's AC4
   says "explicitly warns against mixing embedding spaces." We
   ship the warning AND a runtime check: the staging table's
   distinct `embedder_version` values are inspected before any
   write; mismatch refuses.
3. **F1-class copy-path guard.** Inspired by E11_S01's F1 silent
   stale-embed reuse rectification, the copy path verifies that
   the OLD row's `embedder_version` matches the version recorded
   in the active `corpus-version.json` at run start. Mismatch
   refuses — a stale or corrupt source must NOT silently feed
   wrong vectors into the new corpus version.

---

## Acceptance criteria — status

- [x] **AC1** — 95% unchanged → 95% copied without re-compute.
      **Verified** by [TestCopyEfficacy::test_95_percent_copy](tests/test_re_embed.py):
      synthetic 100-chunk corpus across 10 papers, 5 chunks
      mutated; asserts `summary.chunks_copied == 95`,
      `chunks_re_embedded == 5`, `copy_fraction ≈ 0.95`. Embedder
      mocked to record calls.
- [x] **AC2** — `--resume` skips already-embedded chunks.
      **Verified** by [TestResume::test_resume_skips_done_chunks](tests/test_re_embed.py):
      stages 5 of 10 chunk_ids "already done" in the staging
      table; re-runs with `--resume`; asserts
      `summary.chunks_skipped_resume == 5` and only 5 chunks
      written.
- [x] **AC3** — Runbook has GPU-hours budget table for all
      scenarios. **Verified** by
      [TestRunbookContent::test_gpu_hours_table_present](tests/test_re_embed.py):
      all four scenarios named (model swap, chunker logic fix,
      macro normalizer, ar5iv re-fetch); throughput unit appears.
- [x] **AC4** — Runbook warns against mixing embedding spaces.
      **Verified** by
      [TestRunbookContent::test_warns_against_mixing_spaces](tests/test_re_embed.py):
      runbook contains the phrase and references
      `embedder_version` by column name. **Plus** the code guard:
      [TestSpaceMixingGuard::test_refuses_mixed_space](tests/test_re_embed.py)
      asserts the script raises when staging has a different
      embedder version.

---

## Files added / changed

### New

- [ingest/re_embed.py](ingest/re_embed.py) — partial re-embed
  driver. `ReEmbedSummary` dataclass; `compute_diff` (copy /
  re-embed / drop partition); `_read_old_embedder_version` (F1
  guard's authoritative reference); `_check_staging_embedder_versions`
  (D5 mixing guard); `_load_old_rows` + `_build_copy_embed_record`
  (copy path with F1 guard); `_subset_embed_record` (extracts
  new-chunk subset from a full-paper `EmbedRecord`);
  `_staging_chunk_ids` + `--resume` plumbing;
  `_index_old_chunk_ids_by_paper`; `run_re_embed` (top-level
  orchestrator with atomic state-file checkpoints); `_cli`.
- [tests/test_re_embed.py](tests/test_re_embed.py) — 23 tests
  covering all 4 ACs + regression guards (compute_diff,
  state-file persistence, F1 mismatch refusal, target-version
  stamping, proof routing, dry-run, paper-id validation,
  `_compute_chunk_id` source-stability check, Makefile target
  presence, runbook content × 3).
- [docs/ops/re-embed-runbook.md](docs/ops/re-embed-runbook.md)
  — operator runbook: when-partial-applies table, GPU-hours
  budget with 4 scenarios × 3 throughput ranges, prerequisites,
  step-by-step procedure, embedding-space-mixing code guard
  callout, `--resume` semantics, failure modes, state-file
  schema.

### Changed

- [Makefile](Makefile) — added `make re-embed` target with the
  Python version guard pattern (matches `make ingest` /
  `make delta`).
- [ingest/chunker_types.py](ingest/chunker_types.py) — added a
  "Schema-migration constraint" docstring on `CHUNKER_VERSION`
  pinning the canonical-bytes function `_compute_chunk_id` as
  byte-stable. Closes synthesis Landmine A.

### Not touched

- `ingest/chunker.py`, `ingest/embedder.py`, `ingest/store.py`,
  `server/*`, hash-anchored tests. The re-embed driver consumes
  these unchanged; no schema bumps or hash repins.
  `TOOL_SCHEMA_VERSION` stays at 6.

---

## Test results

```
1577 passed, 7 skipped in 80.61s
```

- 7 skipped: 4 `requires_model` + 3 `requires_full_corpus`.
- Net delta: **+23 tests** (1554 → 1577).
- `ruff check .` is clean.

---

## Design landmines (record-of-decision)

1. **`_compute_chunk_id` is the chunk-identity contract.** Any
   change to this function rotates every chunk_id even for
   byte-identical content, invalidating the partial-re-embed
   correctness assumption. Documented as a schema-migration
   constraint in `chunker_types.py` with a regression-guard test
   in `TestChunkerVersionFreeze`.

2. **No LanceDB bulk column-copy API.** Per synthesis #2, the
   only path to copy old embeddings is read old rows via
   `to_arrow(...)` → reconstruct `EmbedRecord` → write via
   `write_chunks`. We accept the O(unchanged_chunks) I/O cost;
   it's still 10–100× cheaper than GPU recompute.

3. **Sidecar idempotence cannot serve the copy path.** When the
   embedder bumps, the sidecar's `embedder_version` check
   correctly blocks reuse. The copy path queries LanceDB
   directly. Two clean code paths: copy (LanceDB) vs re-embed
   (embedder + sidecar).

4. **Staging-path discipline preserved.** Re-embed writes to
   `var/arxmcp/index/lancedb-staging/`. Active marker NEVER
   touched.

5. **F1-class silent stale-vector risk.** The copy path verifies
   `old_row.embedder_version == OLD_EMBEDDER_VERSION` (read from
   the active marker at run start) before any copy. Mismatch
   refuses with a clear `RuntimeError`.

6. **Embedding-space mixing.** Code guard rejects writes into a
   staging table whose existing rows have a different
   `embedder_version` than the target. No `--force-mixed-space`
   escape hatch (synthesis §3: rejected as foot-gun).

7. **`--resume` is LanceDB-write-side.** No no-op flag (closes
   E11_S01 F3 lesson). Sidecar-based resume rejected because the
   copy path doesn't update sidecars.

8. **State-file checkpoint after every paper.** Atomic write
   via tmp + rename. Status ladder: `in_progress` → `complete`
   or `complete_with_failures`.

9. **Per-paper failure isolation.** Chunker or embedder
   exceptions on one paper are logged to `re-embed.jsonl` and
   continue; the run does not crash on a single bad paper.

10. **Schema-migration constraint on `_compute_chunk_id`** is
    documented and tested (regression guard).

---

## External writes required at code-ship

**None.** All operations are local to the repo's `var/` tree.

Operator runtime writes (gated on operator action):
- `var/arxmcp/index/lancedb-staging/` chunks rows
- `var/arxmcp/ops/re-embed-state.json`
- `var/arxmcp/ops/parser-failures/re-embed.jsonl`

---

## Verification against the synthesis "Done-when" checklist

- [x] All 4 brief ACs covered by verifiable tests at code-ship.
- [x] `_compute_chunk_id` stability documented in
  `chunker_types.py`; regression guard in
  `TestChunkerVersionFreeze`.
- [x] Staging-path discipline preserved — active marker never
  touched.
- [x] F1-class guard in place: copy path verifies old row's
  `embedder_version`.
- [x] Code guard for embedding-space mixing in place; test
  exercises it.
- [x] `--resume` actually works (LanceDB-write-side); test
  verifies.
- [x] GPU-hours table in runbook lists 4 scenarios with ranges.
- [x] Runbook warns explicitly against mixing embedding spaces.
- [x] `make re-embed` target in Makefile mirrors `make ingest`
  pattern.
- [x] State file schema matches D9.
- [x] No `TOOL_SCHEMA_VERSION` bump.
- [x] `make test` green; ruff clean.

---

## Open follow-ups (NOT this milestone)

- **E11_S05 cutover.** This driver writes to staging; the
  atomic swap into the active LanceDB + server restart is
  E11_S05's contract.
- **GPU throughput characterization.** The runbook ranges 100–400
  c/s but the codebase has no documented A6000 benchmark. A
  follow-up could ship a `tools/bench_embedder.py` that reports
  realistic chunks/sec on the operator's hardware.
- **`--from-corpus-version=<int>` flag.** Currently the driver
  reads from the active corpus marker. A future enhancement
  could let the operator copy embeddings from an explicit older
  LanceDB version integer (LanceDB MVCC supports this).
