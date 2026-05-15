# E11_S03 — Research Brief 2: Operational Surface

**Axis:** GPU-hours budget validation, runbook design, embedding-space
mixing guards, failure modes, test surface, CLI surface.

**Peer brief axis:** `ingest/embedder.py` mechanics, `ingest/store.py`
LanceDB MVCC copy semantics, chunk_id canonicalization.

---

## 1. GPU-hours budget validation

### What the codebase actually says about throughput

`ingest/embedder.py` line 131-133:

```python
# Default batch size for CPU inference. ~32 chunks ≈ 32 forward passes
# through XLM-RoBERTa-large per call; on a 2020-era laptop this delivers
# acceptable throughput for the 50-paper seed corpus.
EMBED_BATCH_DEFAULT = 32
```

The comment anchors batch_size=32 as CPU-appropriate. There is **no
documented GPU throughput figure** anywhere in the codebase or design
notes — `.claude/notes/03-ingestion-pipeline.md:144` says "~1–2 days
for ~200K papers using bge-m3" but gives no chunks/sec figure.

### Brief's 32 chunks/sec on A6000 — is it right?

BGE-M3 is an XLM-RoBERTa-large backbone with 0.5B parameters. Published
benchmarks for RoBERTa-large on an A6000 (48 GB VRAM, ~300 TFLOPS FP16):

- HuggingFace sentence-transformers benchmarks show ~200–600 sentences/sec
  at batch=32 on A100 (similar FP16 throughput to A6000).
- BGE-M3 runs a single forward pass over padded batches; chunker-produced
  chunks are ≤512 tokens, so the forward pass is not at max sequence
  length on average. Effective throughput is likely **100–400 chunks/sec
  at batch=32–128 on an A6000**.

The brief's **32 chunks/sec is too conservative by 3–10×**. A more
accurate estimate for GPU operation at batch=64:

| scenario | chunks/sec (A6000) | 5M chunks | 250K chunks | 50K chunks |
|---|---|---|---|---|
| conservative | 100 | ~14h | ~42 min | ~8 min |
| mid-estimate | 200 | ~7h | ~21 min | ~4 min |
| optimistic | 400 | ~3.5h | ~10 min | ~2 min |

The brief's 44h for 5M at 32 c/s is for **CPU**, not GPU. At GPU speeds,
the model-swap scenario is more like **7–14h**. The runbook MUST surface
this range rather than anchoring on 32 c/s (a CPU figure), or the
operator will massively over-provision GPU time.

The correct interpretation: **32 c/s is `EMBED_BATCH_DEFAULT` on CPU.
GPU throughput is not characterized in the codebase.** The runbook
should document a benchmark command and give a range rather than a
single figure.

### Three scenarios + a fourth

The brief's three scenarios are realistic for the project's roadmap:

1. **Embedder model swap** (`bge-m3` SHA bump): all 5M chunks, full
   re-embed. GPU-hours range: 3.5–14h.
2. **Chunker logic fix (5% affected)**: ~250K chunks, GPU-hours: 10–42 min.
3. **Macro normalizer fix (~50K affected)**: ~50K chunks, GPU-hours: 2–8 min.

**Fourth scenario warranted:** ar5iv quality drift / re-fetch subset.
`.claude/notes/03-ingestion-pipeline.md:88-95` establishes that ar5iv
HTML is the primary parse source. If ar5iv ships a LaTeXML version bump
(the same failure mode tracked by `docs/ops/latexml-drift-runbook.md`),
the stored chunk content (body_text, body_canonical) may change for a
large fraction of papers, but the chunk_id — being content-addressable
— would change too, making those chunks "new" and triggering re-embed
for them. This is effectively scenario 2 but not caused by a chunker
logic change. The runbook should list it as a named scenario with its
own row in the GPU table.

---

## 2. Operational surface

### Runbook precedent

`docs/ops/bulk-ingest-runbook.md` (E11_S01) and `docs/ops/delta-loop.md`
(E11_S02) set the structural template:
- Scope note block (when to use this, what it does NOT do)
- Prerequisites (system binaries, environment, disk)
- Numbered steps with exact commands
- Smoke test / dry-run step before the multi-hour run
- Failure modes section
- "See also" cross-links

The re-embed runbook MUST follow this structure exactly.

### Doc-layout: `docs/ops/re-embed-runbook.md` is correct

The CLAUDE.md §1 rule: `docs/ops/` is for operator-facing docs
referenced from the root README. A destructive multi-hour GPU operation
that modifies the corpus is plainly operator-facing. This path is right.
The root README's "Operations" section (added in E10_S04) must gain a
link to this runbook just as it links to `bulk-ingest-runbook.md`.

### Scheduling: one-shot, not scheduled

The brief states "human-initiated in v1." The E11_S02 pattern ships a
systemd timer for the nightly delta loop. The re-embed runbook must
explicitly state: **no systemd timer for re-embed**. Re-embed is
triggered by a human decision (embedder upgrade, chunker logic fix) not
a clock. The equivalent of E11_S02's flock guard should still be
recommended (to prevent two re-embed runs against the same staging
table), but as a shell one-liner, not a unit file.

---

## 3. Embedding-space mixing — code guard on top of the runbook

### Why the runbook warning alone is insufficient

The AC says "explicitly warns against mixing embedding spaces." But a
warning in a Markdown file is advisory; an operator under time pressure
who re-runs re-embed with a bumped embedder SHA against a staging table
that already has rows from the old embedder version will silently produce
a mixed-space table. ANN queries (cosine distance) over a mixed table
return meaningless ranks — a correctness failure with no loud error.

### How the active codebase enforces single-embedder-version

`ingest/embedder.py:_paper_is_up_to_date` (lines 603-685) enforces:

```python
if sidecar.get("embedder_version") != EMBEDDER_VERSION:
    return False
```

This is a per-paper skip guard, not a table-wide guard. `ingest/store.py`
`write_chunks` uses `merge_insert(on="chunk_id")` and does not check
the `embed_model` column on existing rows before writing.

### Recommended code guard for `re_embed.py`

Before writing any rows to the staging LanceDB table, `re_embed.py`
MUST:

1. Read the staging table's existing rows' distinct `embed_model` values.
2. If any row has `embed_model != target_embedder_version`, REFUSE with:
   ```
   RuntimeError: staging table contains rows with embed_model=<old>;
   refusing to mix embedding spaces. Use --from-version to copy or
   drop the table first.
   ```
3. Exception: if `--force-mixed-space` is passed, log a WARNING and
   proceed. This escape hatch is for the "copy unchanged" path, where
   copied rows retain the old embedder's vectors but are immediately
   replaced by the new embedder's vectors in the same run.

The guard should be skipped if the staging table is empty (clean start).

This closes the gap between the runbook warning and code enforcement.

---

## 4. Failure modes + safe-resume contract

### What happens if `re_embed.py` is killed mid-run?

Three cases:

**Case A: Killed during the diff/copy phase** (before any re-embed).
The staging table has some copied rows from the old version (same
`chunk_id`, same `embedder_version`). On restart with `--resume`, the
copy phase checks whether each chunk_id is already present in the
staging table and skips it. Safe.

**Case B: Killed during the re-embed phase** (new chunks being embedded
and written). The staging table has a mix: some copied rows AND some
newly-embedded rows. The resume guard checks chunk_id presence in the
staging table — already-written new-embed rows are skipped. Safe,
SUBJECT TO the embed-space mixing guard being relaxed during the resume
path (since the staging table now has rows from two embedder versions:
old-copied and new-embedded). The resume logic must know which chunks
are in the "copy" pool vs. the "re-embed" pool.

**Case C: Killed during HNSW index rebuild** (after all writes, during
`create_index`). On restart with `--resume`, all rows are present in the
staging table; no re-embed needed. The script just re-runs `create_index`.
The state file's `chunks_copied + chunks_reembedded == total` is the
signal that writes are complete.

### GPU OOM at chunk N of 5M

Mid-batch OOM: the in-flight batch fails; the paper's NPZ is not written
(the write is post-batch). The embedding sidecar for that paper is
absent or stale. On resume, the paper is re-embedded. Safe, same as
Case B.

### State file sentinel

Analogous to E11_S01's staging-path discipline and E11_S02's
`oai-pmh-state.json`:

```json
{
  "from_lancedb_version": 7,
  "to_lancedb_staging_version": null,
  "embedder_version_target": "bge-m3@5617a9f6",
  "last_paper_id_written": "2401.12345",
  "chunks_copied": 4750000,
  "chunks_reembedded": 12500,
  "chunks_removed": 800,
  "total_chunks_source": 5000000,
  "status": "in_progress",
  "started_utc": "2026-05-15T06:00:00Z",
  "last_checkpoint_utc": "2026-05-15T08:14:37Z"
}
```

Path: `var/arxmcp/ops/re-embed-state.json`.

`to_lancedb_staging_version` is null until the final `create_index`
completes and the staging table's version integer is recorded. It is
the signal that the run is complete and the staging table is ready for
promotion.

### `corpus-version.json` MUST NOT advance on interruption

The active marker lives at:
`var/arxmcp/index/lancedb/corpus-version.json`

The staging marker lives at:
`var/arxmcp/index/lancedb-staging/corpus-version.json`
(written by `write_chunks` as its postcondition per E04_S03 / E11_S01
synthesis D2.)

`re_embed.py` writes to the **staging LanceDB**. It MUST NOT touch the
active corpus-version.json. This is the same discipline as E11_S01 and
E11_S02. Promotion (staging → active) remains E11_S05's cutover runbook.
The state file's `to_lancedb_staging_version` tracks the staging marker;
the active marker is untouched until cutover.

---

## 5. Test surface — proving AC1, AC2, AC4

### AC1 — 95% unchanged → 95% copied without re-compute

```python
# tests/test_re_embed.py::TestCopyEfficacy::test_95_percent_copy

def test_95_percent_copy(tmp_path, monkeypatch):
    # Synthetic: 100 chunks across 10 papers, 5 chunks have new content.
    # chunker_version bumped for 5 chunks → new chunk_ids.
    # Remaining 95 chunk_ids are identical between old and new.
    # Embedder is mocked to record which chunk_ids it is called with.
    # re_embed.py runs; assert:
    #   summary.chunks_copied == 95
    #   summary.chunks_reembedded == 5
    #   embedder_mock.call_count == 1  # one batch of 5
```

The embedder mock MUST be installed at the `_encode_batch` level (not
`embed_paper` level) so the copy-vs-re-embed accounting is accurate.

### AC2 — `--resume` skips already-embedded chunks

```python
# tests/test_re_embed.py::TestResume::test_resume_skips_done_chunks

def test_resume_skips_done_chunks(tmp_path, monkeypatch):
    # Synthetic 10-chunk run. Halt after writing 5 (mock SIGINT or
    # early exit via monkeypatched write_chunks). State file has
    # last_paper_id_written=paper_3, chunks_reembedded=5.
    # Re-run with --resume; assert embedder called for chunks 6-10 only.
    # second_run.chunks_reembedded == 5 (the remaining 5)
    # OR 0 if all chunks were in copy pool.
```

The `--resume` contract: skip chunk_ids already present in the staging
table AND already past `last_paper_id_written` in paper order.

### AC4 — Runbook warns against mixing embedding spaces

```python
# tests/test_re_embed_runbook.py::TestRunbookContent

import pathlib

RUNBOOK = pathlib.Path("docs/ops/re-embed-runbook.md")

def test_runbook_warns_against_mixing_spaces():
    text = RUNBOOK.read_text()
    assert "mixing embedding spaces" in text.lower()
    assert "embedding_space" in text.lower() or "embed_model" in text.lower()
```

### Guard test — staging table with wrong embedder version

```python
# tests/test_re_embed.py::TestSpaceMixingGuard::test_refuses_mixed_space

def test_refuses_mixed_space(tmp_path):
    # Write rows with embed_model="bge-m3@aaaaaaaaa" into staging table.
    # Run re_embed with target embedder_version="bge-m3@5617a9f6".
    # Assert RuntimeError raised with message containing "refusing to mix".
```

---

## 6. CLI surface

Mirror `bulk_ingest.py` and `oai_delta.py` flag conventions:

| flag | default | notes |
|---|---|---|
| `--from-corpus-version=<int>` | reads from `corpus-version.json` | source LanceDB version to copy unchanged embeddings from |
| `--lancedb-staging-path=<path>` | `var/arxmcp/index/lancedb-staging/` | matches E11_S01/S02 |
| `--paper-ids-file=<path>` | all papers in source LanceDB | scope to subset for smoke test |
| `--dry-run` | false | print diff (unchanged/new/removed) without writing |
| `--resume` | false | skip chunk_ids already in staging table |
| `--force-mixed-space` | false | escape hatch to allow mixed re-embed (DANGEROUS; logged as WARNING) |
| `--batch-size=<int>` | 32 | forward to `_encode_batch`; recommend 64 on GPU |

**No `--to-version` flag.** The staging LanceDB's next integer is always
the target; callers do not choose it.

**`--resume` MUST be implemented.** Per E11_S01 critique F3, a `--resume`
flag that does nothing is worse than no flag at all. The implementation:
read the state file's `last_paper_id_written`; skip all papers with
`paper_id <= last_paper_id_written` (assuming sorted paper order,
matching `bulk_ingest.py`'s pattern). Then check per-chunk whether the
chunk_id is already in the staging table.

---

## Open questions

1. **Does the staging table for re-embed share the same path as the
   bulk-ingest staging path?** If yes, a bulk-ingest and a re-embed
   running simultaneously (or sequentially without promotion) could
   collide. The implementer must decide whether re-embed uses the same
   `lancedb-staging/` or a separate `lancedb-reembed/`. The flock guard
   handles the concurrent case, but sequential collision (bulk-ingest
   staging data partially written, then re-embed overwrites it) is a
   state machine problem. Recommend: document clearly that re-embed MUST
   run AFTER `lancedb-staging/` is in a complete post-bulk-ingest state.

2. **The `--resume` flag + embedding-space mixing guard interaction.**
   On resume, the staging table already has rows from two embedder
   versions (old-copied + new-embedded-so-far). The mixing guard fires
   unless it's relaxed for the resume path. The implementer must decide:
   is the guard skipped for `--resume` runs? Or is the guard scoped to
   chunks in the "to re-embed" pool only? This must be explicit in code
   with a comment.

3. **Benchmark command for GPU throughput.** The runbook should include
   a self-measuring benchmark:
   ```bash
   python -m ingest.re_embed --paper-ids-file=tools/seed-papers.txt \
       --limit=100 --dry-run=false --batch-size=64 2>&1 | grep elapsed
   ```
   The implementer should add a `--benchmark-only` flag or document the
   `elapsed_s` in the state file so operators can project GPU time before
   committing to a 5M-chunk run. This is a gap in the brief.

4. **`ingest/store.py`'s `write_chunks` does not accept a "copy
   embeddings from row X" path.** The brief's step 3 ("copy unchanged
   embeddings from old LanceDB version") requires either: (a) reading
   old NPZ files directly (if they still exist under
   `var/arxmcp/corpus/embeddings/`), or (b) reading the old LanceDB
   version and extracting the embedding columns. The implementer must
   confirm which path is taken and whether `write_chunks` needs a new
   parameter or whether re-embed bypasses `write_chunks` entirely and
   writes directly to the LanceDB dataset. This is the biggest
   implementation-mechanics open question — the peer brief may resolve
   it.

---

## External writes the implementation will require

| type | target | why |
|---|---|---|
| local file write | `var/arxmcp/index/lancedb-staging/` | staging LanceDB rows (copy + re-embed) |
| local file write | `var/arxmcp/ops/re-embed-state.json` | resume sentinel + checkpoint |
| local file write | `docs/ops/re-embed-runbook.md` | operator runbook (deliverable) |
| local file write | `ingest/re_embed.py` | new module (deliverable) |
| local file write | root `README.md` | add link to re-embed-runbook.md in Operations section |

No pushes, PRs, tickets, infra mutations, or third-party API calls.
All writes are local and operator-initiated.
