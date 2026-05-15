# Partial re-embed runbook (E11_S03)

**Use when:** the chunker (`CHUNKER_VERSION`) or the embedder
(`EMBEDDER_VERSION`) has been bumped and the LanceDB corpus must
be re-stamped with the new version while AVOIDING the GPU-day
cost of re-embedding every chunk. The re-embed script copies
unchanged embeddings from the active LanceDB version into the
staging dataset, and only re-runs the embedder for chunks whose
content actually changed.

> **Staging-path discipline (inherited from E11_S01).** Writes go
> to `var/arxmcp/index/lancedb-staging/`. The active
> `corpus-version.json` is NEVER advanced by this script —
> promotion is E11_S05's atomic cutover.

> **NEVER mix embedding spaces.** ANN cosine distance is
> meaningless across different `embedder_version` values. The
> re-embed script enforces this with a code guard (see §
> "Embedding-space mixing — code guard" below) in addition to
> this runbook warning. The guard fires if the staging table
> already contains rows whose `embedder_version` disagrees with
> the target.

---

## When the partial path applies

| Bump | Partial re-embed applies? | Why |
|---|---|---|
| `chunker_version` (logic fix that affects some papers) | YES | Only changed papers' chunk_ids rotate; the rest are byte-identical and can be copied. |
| `embedder_version` (BGE-M3 commit SHA changed) | NO | The embedding VECTORS depend on the model. Every chunk must be re-embedded; the partial path's copy step finds zero matches. |
| Macro-normalizer fix | YES | Only affected papers' body_text changes; rest unchanged. |
| ar5iv quality drift / re-fetch subset | YES | Only re-fetched papers have changed body_text. |

If the embedder bumped (no copy candidates), this script still
runs end-to-end; the runtime just reflects the full re-embed cost
because every chunk takes the GPU path.

---

## GPU-hours budget

**Caveat.** BGE-M3 GPU throughput is not characterized in this
codebase. The figures below assume 100–400 chunks/sec on an A6000
at batch_size=64 (sentence-transformers benchmarks). Throughput
on smaller GPUs (T4, RTX 3090) is lower; benchmark before
committing to a long run.

| Scenario | Chunks re-embedded | Conservative (100 c/s) | Mid (200 c/s) | Optimistic (400 c/s) |
|---|---|---|---|---|
| Embedder model swap (BGE-M3 SHA bump) | 5,000,000 | ~14h | ~7h | ~3.5h |
| Chunker logic fix (~5% of papers affected) | 250,000 | ~42 min | ~21 min | ~10 min |
| Macro normalizer fix | 50,000 | ~8 min | ~4 min | ~2 min |
| ar5iv re-fetch subset (~10K papers) | 250,000 | ~42 min | ~21 min | ~10 min |

To benchmark on YOUR hardware before committing:

```bash
make re-embed ARGS="--paper-ids-file=tools/seed-papers.txt --dry-run"
```

This re-chunks the 50-paper seed and reports the diff (`copy=
... reembed=... drop=...`) per paper. Run without `--dry-run`
against a small subset to time the actual GPU pass and divide by
the printed `re_embedded` count for chunks/sec.

---

## Prerequisites

* **The active LanceDB must exist** at
  `var/arxmcp/index/lancedb/` with a valid `corpus-version.json`
  carrying both `version` and `embedder_version`. The re-embed
  driver reads `embedder_version` from this file to gate the F1-
  class copy-path guard.
* **The chunker fixtures must be regenerated** if the chunker
  logic changed (per `.claude/docs/chunker-fixtures.md`).
* **GPU is optional but strongly recommended.** A CPU run on a
  200K-paper corpus is a multi-day operation; on an A6000 it's
  hours.
* **`uv`** on PATH for `make re-embed`.

---

## Procedure

### Step 1 — Dry-run to compute the diff

```bash
make re-embed ARGS="--paper-ids-file=tools/seed-papers.txt --dry-run"
```

This prints `<paper_id> copy=<N> reembed=<N> drop=<N>` per paper.
Sum the columns to estimate the GPU-hour cost for the full
corpus.

### Step 2 — Smoke-run against a subset

```bash
make re-embed ARGS="--paper-ids-file=tools/seed-papers.txt"
```

Inspect:
* `var/arxmcp/ops/re-embed-state.json` — should show
  `status: "complete"` and `chunks_copied + chunks_re_embedded ==
  chunks_target`.
* `var/arxmcp/index/lancedb-staging/` — should have a fresh
  LanceDB version integer; `corpus-version.json` carries the
  TARGET `embedder_version`.

### Step 3 — Full run

```bash
make re-embed
```

(With no `--paper-ids-file`, the driver enumerates every paper
from the active LanceDB.) Expected wall-clock per the budget
table above. Monitor:

```bash
tail -f var/arxmcp/ops/re-embed-state.json
```

`last_checkpoint_utc` advances after each paper.

### Step 4 — Verify staging marker

After the run completes:

```bash
cat var/arxmcp/index/lancedb-staging/corpus-version.json
```

Confirm `version` advanced and `embedder_version` matches the
new target.

### Step 5 — Hand off to the cutover runbook (E11_S05)

Do NOT manually swap `corpus-version.json`. E11_S05's atomic
cutover handles the staging → active promotion + server restart.

---

## Embedding-space mixing — code guard

Beyond this runbook warning, the script enforces:

* Before any write, the staging table's distinct
  `embedder_version` values are checked. If any disagree with the
  target, the script refuses with a clear error.
* Each old row copied through the partial path is checked
  against the active `corpus-version.json`'s recorded
  `embedder_version`. A mismatch refuses (F1-class guard;
  prevents silent stale-vector reuse — the same class of bug
  E11_S01 F1 closed in the bulk path).
* The copied row's `embedder_version` column is stamped with the
  NEW target. The VECTOR is content-identity-valid (no embedder
  bump → same model → same vector space); only the metadata
  column is rewritten.

If you absolutely must mix embedding spaces — e.g. an A/B
comparison — do it in a SEPARATE LanceDB dataset, not in the
staging path the production server reads from.

---

## Resume semantics — `--resume`

The `--resume` flag is **LanceDB-write-side**:

* On startup, the script scans the staging table's existing
  `chunk_id`s.
* Any chunk_id already in the staging table is skipped (counted
  as `chunks_skipped_resume`).
* This is uniform across the copy AND re-embed paths.

`--resume` is NOT sidecar-based (sidecars don't update on the
copy path). Don't add a `--resume-from-paper-id` flag — the
chunk_id presence check is sufficient.

If you killed mid-run AND `var/arxmcp/index/lancedb-staging/` has
partial state from a DIFFERENT target embedder version, do NOT
use `--resume`; drop the staging dataset and start fresh.

---

## Failure modes

### GPU OOM mid-batch

The embedder's per-paper sidecar is post-batch; a mid-batch OOM
leaves the paper's sidecar absent or stale. On resume, the
sidecar is regenerated. Safe.

### Chunker raises on one paper

The driver isolates failures per paper. A chunker raise on
paper X appends a row to
`var/arxmcp/ops/parser-failures/re-embed.jsonl` and continues.

### Disk fills mid-run

`write_chunks` will fail; the failing paper is logged as failed;
the run continues. Free disk and `--resume`.

### `corpus-version.json` in the active path is missing

The driver refuses to start. The active LanceDB must have a
valid marker — run a bulk ingest (E11_S01) or restore from a
backup first.

### Staging dataset has a stale embedder_version

The code guard fires and refuses. Either drop the staging
dataset (`rm -rf var/arxmcp/index/lancedb-staging/`) or change
the target embedder version to match the existing rows
(`--target-embedder-version=...`).

---

## State file schema

`var/arxmcp/ops/re-embed-state.json`:

```json
{
  "status": "complete | in_progress | complete_with_failures",
  "from_lancedb_path": ".../lancedb",
  "to_lancedb_staging_path": ".../lancedb-staging",
  "old_embedder_version": "bge-m3@aaaaaaaa",
  "target_embedder_version": "bge-m3@bbbbbbbb",
  "target_chunker_version": "v1.0",
  "papers_total": 200000,
  "last_paper_id_written": "2401.12345",
  "chunks_copied": 4750000,
  "chunks_re_embedded": 12500,
  "chunks_dropped": 800,
  "started_utc": "2026-05-15T06:00:00Z",
  "last_checkpoint_utc": "2026-05-15T08:14:37Z"
}
```

---

## See also

* [ingest/re_embed.py](../../ingest/re_embed.py) — the driver module.
* [ingest/chunker_types.py](../../ingest/chunker_types.py) — the
  `CHUNKER_VERSION` constant and the schema-migration constraint
  on `_compute_chunk_id`.
* [docs/ops/bulk-ingest-runbook.md](bulk-ingest-runbook.md) — the
  full-corpus bulk ingest (E11_S01).
* [docs/ops/delta-loop.md](delta-loop.md) — the nightly OAI-PMH
  delta loop (E11_S02).
* [.claude/notes/05-storage-and-indexing.md](../../.claude/notes/05-storage-and-indexing.md)
  — LanceDB MVCC semantics; why no `vN+1/` directories.
* [.claude/notes/milestones/E11_S03/research-synthesis.md](../../.claude/notes/milestones/E11_S03/research-synthesis.md)
  — design rationale + D1-D15 decisions.
