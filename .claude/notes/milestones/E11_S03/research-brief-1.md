# Research Brief 1 — E11_S03: Re-embed Cost Budget and Partial Re-embed Strategy
## Axis: In-codebase mechanics and reusable primitives

**Date:** 2026-05-15
**Researcher:** agent (Sonnet 4.6, parallel branch 1 of 2)

---

## 1. In-codebase context

### 1.1 `ingest/chunker.py` — canonical-bytes function (Landmine A)

The canonical-bytes function lives in `ingest/chunker.py` at line 975:

```python
def _compute_chunk_id(paper_id: str, preamble_text: str, body_text: str) -> str:
    """Return ``arxiv:<paper_id>:<sha256(preamble_text + NFC(body_text))[:16]>``."""
    body_normalized = unicodedata.normalize("NFC", body_text)
    digest = hashlib.sha256(
        (preamble_text + body_normalized).encode("utf-8")
    ).hexdigest()[:16]
    return f"arxiv:{paper_id}:{digest}"
```

The input is `preamble_text + NFC(body_text)`, UTF-8 encoded.
`preamble_text` arrives pre-NFC (preamble.py normalizes at extraction time per
E02_S02 F6). The `body_text` is NFC-normalized for the hash but stored
unchanged.

**Critical: the canonical-bytes function IS the hash for chunk identity.**
The `chunk_id` format confirmed in `ingest/identifiers.py` line 50-54:

```
CHUNK_ID_PATTERN = rf"arxiv:({PAPER_ID_PATTERN}):[0-9a-f]{{16}}"
```

The docstring at `ingest/identifiers.py:50` states explicitly:
> "The 16-hex suffix is the `sha256(preamble_text + NFC(body_text))[:16]` per
> `ingest.chunker._compute_chunk_id`."

**Landmine A resolution:** `_compute_chunk_id` is a private function in
`chunker.py`. If the chunker logic changes in a way that changes `body_text`
content (e.g. a normalizer fix), the chunk_id **changes** because the hash
input changes — this is CORRECT and DESIRED: new content should get a new
chunk_id. BUT if `_compute_chunk_id` itself is changed (e.g. moving from
`preamble + NFC(body)` to just `NFC(body)` in the hash), ALL chunk_ids rotate
even for byte-identical content, defeating the entire partial re-embed
strategy.

**Recommendation:** `_compute_chunk_id` must be declared frozen as of
`chunker_version = "v1.0"` (current value in `ingest/chunker_types.py:28`).
Document this in `chunker_types.py`. Any change to `_compute_chunk_id` itself
should be treated as a schema migration, not a mere chunker_version bump.

### 1.2 `ingest/chunker_types.py` — version constants

```python
CHUNKER_VERSION = "v1.0"
```

`ingest/embedder.py` line 93:
```python
from ingest.chunker_types import CHUNKER_VERSION as EXPECTED_CHUNKER_VERSION
```

`EMBEDDER_VERSION` (embedder.py line 117):
```python
EMBEDDER_VERSION = f"bge-m3@{BGE_M3_COMMIT_SHA[:8]}"
```

### 1.3 `ingest/embedder.py` — sidecar idempotence (Landmine B)

The per-paper skip check in `_paper_is_up_to_date()` (lines 610-668) has
these conditions, quoted verbatim:
1. sidecar `embeddings_manifest.json` exists
2. `embeddings.npz` ALSO exists in the same directory
3. `sidecar.chunker_version == EXPECTED_CHUNKER_VERSION`
4. `sidecar.embedder_version == EMBEDDER_VERSION`
5. every chunk_id in the current `chunk_manifest.json` is present in `sidecar.embedded_chunks`

**Landmine B resolution:** When the re-embed script runs to copy embeddings
from an old LanceDB version (unchanged chunk_ids with NEW embedder_version),
the SIDECAR's `embedder_version` will NOT match the new `EMBEDDER_VERSION`
constant. This means:

- If we call `embed_paper()` directly, it will re-embed from scratch (correct,
  but wastes GPU for unchanged chunks).
- If we want to "copy" old embeddings, the sidecar path must be bypassed.
- The re-embed script CANNOT rely on `embed_paper()`'s sidecar idempotence to
  copy embeddings — the sidecar guard correctly blocks reuse when
  `embedder_version` changes.

**For the embedder-swap scenario (5M chunks):** all sidecars fail condition 4
above, so `embed_paper()` re-embeds everything — correct. No special handling
needed.

**For the chunker-fix scenario (5% papers changed):** unchanged chunk_ids
should copy old vectors from LanceDB, not re-embed. The sidecar CANNOT
distinguish "this embedding was produced by old embedder on an unchanged chunk"
from "this embedding was produced by new embedder" because the
`embedder_version` is the same in both cases (chunker bumped, embedder didn't).
The re-embed script's copy path must query LanceDB directly.

### 1.4 `ingest/store.py` — `write_chunks`, LanceDB MVCC, `corpus-version.json`

From `store.py` docstring (lines 57-72):

> "LanceDB version int IS the corpus_version. Writers use the current dataset;
> readers call `dataset.checkout(version=N)`. (The reader-side wrapper lives in
> `server.corpus.open_chunks_table`.)"
>
> "The integer returned by `write_chunks` is the LanceDB dataset version AFTER
> `_create_indices` has run."

`write_chunks` uses:
```python
tbl.merge_insert("chunk_id")
    .when_matched_update_all()
    .when_not_matched_insert_all()
    .execute(arrow_table)
```

The `corpus-version.json` postcondition writes `chunker_version` + `embedder_version`
from `CHUNKER_VERSION` (module-level import) and `embeddings.embedder_version`
(from the `EmbedRecord`). Critically, for the re-embed path the `EmbedRecord`
must carry the **new** `embedder_version` even when the embedding vectors were
copied from the old LanceDB version — otherwise the marker lies.

**MVCC and reading old version (Landmine D resolution):** LanceDB's
`dataset.checkout(version=N)` gives snapshot isolation. `lancedb>=0.6` (from
`pyproject.toml`). The pattern for reading the old version:

```python
db = lancedb.connect(str(old_lancedb_path))
old_tbl = db.open_table(CHUNKS_TABLE_NAME)
# checkout to specific old version (integer from corpus-version.json)
# lancedb 0.6+: old_tbl.checkout(N) or db.open_table(..., version=N)
```

There is NO efficient `add_columns` / `merge_columns` API between two
different LanceDB versions in `lancedb>=0.6`. The only path is: query old
table for unchanged chunk_ids → get their `embedding_stmt` + `embedding_proof`
vectors → write as new rows into the new table via `write_chunks`. This is
O(unchanged_chunks) I/O reads + O(new_chunks) GPU calls.

### 1.5 `ingest/schema.py` — relevant columns

From `CHUNKS_SCHEMA_V1` (schema.py lines 81-130):
- `chunk_id` — `pa.utf8(), nullable=False` (primary key, content-addressable)
- `embedding_stmt` — `pa.list_(pa.float32(), 1024), nullable=True`
- `embedding_proof` — `pa.list_(pa.float32(), 1024), nullable=True`
- `embedder_version` — `pa.utf8(), nullable=False`
- `chunker_version` — `pa.utf8(), nullable=False`

The `EmbedRecord` dataclass (schema.py lines 216-360) validates:
- L2-normalized vectors (`atol=1e-3`)
- No chunk_id appears in both `chunk_ids_stmt` and `chunk_ids_proof`
- Row-alignment of IDs to embedding arrays

**For the copy path:** copied vectors from the old LanceDB table should
already be L2-normalized (the embedder wrote them that way). The `EmbedRecord`
validator will pass. But the `embedder_version` on the new `EmbedRecord` must
be set to the **new** target `EMBEDDER_VERSION`.

### 1.6 `ingest/bulk_ingest.py` — staging discipline and `IngestSummary`

From `bulk_ingest.py`:
```python
DEFAULT_LANCEDB_STAGING_PATH = (
    REPO_ROOT / "var" / "arxmcp" / "index" / "lancedb-staging"
)

@dataclass
class IngestSummary:
    papers_total: int = 0
    papers_succeeded: int = 0
    papers_failed: int = 0
    papers_skipped: int = 0
    ar5iv_hits: int = 0
    ar5iv_misses: int = 0
    elapsed_seconds: float = 0.0
```

E11_S01 F1 fix (shipped): `ingest_one_paper` now checks `embed_stats.status != "ok"` before calling `load_embed_record` — the silent stale-embed reuse bug is closed.

**Landmine C — staging path for re_embed.py:** The re-embed script should
write to the SAME `lancedb-staging` path, not a separate staging. Rationale:
the re-embed output IS the next staging dataset for promotion. Using a
separate path would require an additional promotion step and break the
`corpus-version.json` handshake convention. However, re_embed.py must NOT
overwrite the current active LanceDB at `var/arxmcp/index/lancedb/` — it
writes to `lancedb-staging/` like bulk_ingest and oai_delta.

### 1.7 Cache bust after re-embed (from note 07)

From `07-multi-agent-caching.md`, Tier-1 cache key:
```
key = sha256(canonical_form(query) + filters_json + k + corpus_version)
```

And explicit quote:
> "**Tier 1 — Exact-query (SQLite LRU, 10K entries):** key includes
> `corpus_version: int` as a mandatory component; stale entries from old
> corpus versions are unreachable by construction after a restart with a new
> `corpus-version.json`."

A partial re-embed that writes to `lancedb-staging/` produces a new LanceDB
version integer. When the operator promotes staging to active
(`corpus-version.json` update), the server restart picks up the new version,
and all three cache tiers self-invalidate by construction. No special cache-
flush logic is needed in `re_embed.py` itself.

### 1.8 CLAUDE.md §7 — known stubs

The §7 stubs list does NOT mention `re_embed.py` as partially scaffolded. The
file does not exist at `ingest/re_embed.py`. This is a net-new deliverable.

---

## 2. Prior decisions and lessons

### 2.1 E11_S01 F1 — silent stale-embed reuse (most load-bearing lesson)

Quoted from `E11_S01/critique-merged.md`:
> "F1 — Silent stale-embed reuse on `embed_paper` failure ... `ingest_one_paper`
> calls `embed_paper(paper_id)` and discards its return value, then immediately
> calls `load_embed_record(paper_id)`. Per `ingest/embedder.py:850-883`,
> `embed_paper` catches `PER_PAPER_FAILURE_EXCEPTIONS` and returns an
> `EmbedStats(status="fail", ...)` without raising — the per-paper NPZ on
> disk is whatever it was BEFORE the call ... `load_embed_record` then reads
> the stale NPZ from a previous run and `ingest_one_paper` writes those stale
> vectors into the staging LanceDB."
>
> Fixed: "inspect `embed_paper`'s return value."

**Lesson for re_embed.py (Landmine E):** The copy path (unchanged chunk_ids)
must verify that the OLD row's `embedder_version` matches the OLD target, NOT
the new target. If an operator ran re_embed.py with `--target-embedder-version
vX` and the old LanceDB table has rows with `embedder_version=vY` (different
from vX), those rows must NOT be copied silently — they must be re-embedded or
flagged. This is the F1-class error in re-embed guise.

### 2.2 E11_S01 F3 — `--resume` was a no-op (don't repeat)

Quoted from `E11_S01/critique-merged.md`:
> "F3 — `--resume` flag is documented but a no-op ... The CLI advertises a
> `--resume` flag ... The flag's value is threaded into `run_bulk_ingest(...
> resume=resume...)`, but inside `run_bulk_ingest` the parameter is never read."
>
> "Proposed fix: Remove the flag from the CLI surface AND from the runbook;
> the embedder's sidecar idempotence already protects against duplicate
> embedding work at the embed step."

**Lesson for re_embed.py (Landmine G):** `--resume` MUST be real, not a
placeholder. Two implementation options:

1. **Resume from the LanceDB-write side** (recommended): on `--resume`, skip
   chunk_ids already present in the new staging LanceDB at the target version.
   This is queryable via `tbl.to_arrow(filter=...)` or a simple scan. Clean
   separation of concerns: LanceDB is the ground truth for what's done.
2. Resume from the embedder sidecar: only applies to chunks that needed
   re-embedding (new chunk_ids). Sidecars for unchanged (copied) chunks may
   NOT be updated by the copy path, so sidecar-based resume is incomplete.

**Pick option 1.** The staging LanceDB is the write-side checkpoint. The
`--resume` implementation: open the staging table, collect the set of
`chunk_id`s already present, skip those in the work queue.

### 2.3 Version constant pinning

`chunker_types.py` pins `CHUNKER_VERSION = "v1.0"` as single source of truth.
Tests pin the expected versions indirectly through `EXPECTED_CHUNKER_VERSION`
imports. No dedicated `test_chunker_version.py` was found; version integrity
is tested through the sidecar logic in `tests/test_embedder.py`.

---

## 3. External sources — LanceDB copy semantics

**LanceDB version pinned in `pyproject.toml`:** `lancedb>=0.6`.

**MVCC read of old version:** `db.open_table(name)` returns a table object;
calling `.checkout(version=N)` (method, not parameter to `open_table` in
≥0.6) pins the read to version N. Alternatively, `db.open_table(name,
version=N)` in some 0.6+ builds. The pattern is stable.

**No bulk column-copy API:** LanceDB has no `merge_columns_from_version()`
or equivalent. The only path to copy embeddings from version N to N+1 is:
1. `old_tbl.to_arrow(filter=f"chunk_id IN {unchanged_ids}")` — full row scan.
2. Construct a new `EmbedRecord` from the returned Arrow batches.
3. Pass to `write_chunks(chunks, embed_record, lancedb_path=staging_path)`.

This means the copy I/O cost is O(unchanged_chunks × row_width). At 5M chunks
× ~12 KB/row ≈ 60 GB LanceDB read for a full-corpus copy. That is
significantly cheaper than GPU time (~44 hours A6000), and is largely I/O
bound, but the implementer should profile the LanceDB Arrow scan speed at
scale before assuming disk I/O is negligible.

---

## 4. Landmine summary

**A. Canonical-bytes function stability:**
`_compute_chunk_id` in `chunker.py` is STABLE for content-identical chunks.
Changes to chunker *logic* (body_text content) correctly change chunk_ids.
Changes to `_compute_chunk_id` itself (the hash function) would silently
rotate all chunk_ids and break the partial re-embed identity assumption.
`_compute_chunk_id` must be frozen per version. **Recommend adding a
docstring constraint and a test that SHA-pinning the function signature is
enforced** (similar to `EXPECTED_TOOL_SCHEMA_SHA256` pattern).

**B. Sidecar bypass for copy path:**
The sidecar's `embedder_version` check correctly BLOCKS reuse when the
embedder bumps. The copy path in `re_embed.py` must NOT route through
`embed_paper()` for unchanged chunks — it must read directly from the old
LanceDB table. The sidecar IS still useful for the re-embed path (new chunks
that need fresh GPU work), where `embed_paper()` remains the right entry point.

**C. Staging path:**
`re_embed.py` writes to `var/arxmcp/index/lancedb-staging/` (same as
`bulk_ingest.py`). No separate staging path needed. The operator promotes
staging to active via the same `corpus-version.json` update step documented in
the bulk-ingest runbook.

**D. LanceDB copy semantics — no magic bulk API:**
Read unchanged rows from old version via `old_tbl.to_arrow(filter=...)`,
reconstruct `EmbedRecord`, call `write_chunks`. O(unchanged_chunks) I/O.
Confirm that `lancedb>=0.6` supports `checkout(version=N)` on a staging table
that may have been written by multiple separate runs (it does — MVCC is
filesystem-level).

**E. Old-row embedder_version guard (F1-class risk):**
When copying old rows, verify `old_row.embedder_version == OLD_EMBEDDER_VERSION`
before writing the row with `embedder_version = NEW_EMBEDDER_VERSION`. If there
is a mismatch (operator error, or the old table has mixed versions), refuse and
log an error. Do NOT silently copy a row whose embedder_version doesn't match
what we expect.

**F. Embedding space mixing:**
`re_embed.py` must refuse to write if the staging table already contains rows
with a DIFFERENT `embedder_version` than the target. The AC4 warning in the
runbook should be: "All rows in a single LanceDB table must have the same
`embedder_version`. ANN search is meaningless across different embedding
spaces. The re-embed script enforces this by refusing to mix versions."

**G. `--resume` is LanceDB-write-side (option 1):**
On `--resume`, scan the staging table for chunk_ids already written, subtract
from the work queue. This handles both the copy path AND the re-embed path
uniformly. The sidecar-based option (option 2) is incomplete because the copy
path may not update sidecars.

**H. AC1 verifiability — log data shape:**

Recommend a `ReEmbedSummary` dataclass mirroring `IngestSummary`:
```python
@dataclass
class ReEmbedSummary:
    papers_total: int = 0
    chunks_total: int = 0
    chunks_copied: int = 0        # unchanged chunk_ids; vectors read from old LanceDB
    chunks_re_embedded: int = 0   # new chunk_ids; GPU compute required
    chunks_skipped_resume: int = 0 # already in staging (--resume path)
    chunks_failed: int = 0
    elapsed_seconds: float = 0.0

    @property
    def copy_fraction(self) -> float:
        total = self.chunks_copied + self.chunks_re_embedded
        return self.chunks_copied / total if total else 0.0
```

The AC1 "95% unchanged → 95% copied" assertion is `summary.copy_fraction >= 0.95`.
Log at INFO per paper; log aggregate at the end. Append a JSONL line per paper
to `var/arxmcp/ops/re-embed.jsonl` (same pattern as `ops/ingestion.log`).

---

## 5. Open questions

1. **`corpus-version.json` NOT advancing on interrupt:** The brief specifies
   "if re-embed is interrupted, corpus-version.json must NOT advance." In the
   current architecture, `write_corpus_version_marker()` is called by
   `write_chunks()` as a postcondition of each `merge_insert`. This means every
   per-paper write advances the marker. The implementer must decide: (a) skip the
   marker write during re-embed (write it only at the end), or (b) write a
   sentinel "in-progress" corpus-version.json that the server refuses to load.
   **Recommend (b):** write `{"status": "in-progress", "target_version": N}` at
   start; overwrite with the real version at the end. The server's startup code
   must check for `status != "complete"` and refuse to boot from an in-progress
   marker.

2. **Does `lancedb>=0.6` support `checkout(version=N)` on the staging table?**
   The staging table is a standard LanceDB dataset. Versioning is available on
   any dataset. Confirm with `lance.dataset().checkout_version(N)` or
   `tbl.checkout(N)`. This should work but must be tested with an actual
   lancedb 0.6+ install.

3. **What is `OLD_EMBEDDER_VERSION`?** The re-embed script must know the
   embedder version of the old LanceDB rows to validate Landmine E's guard.
   Two sources: (a) read from the existing `corpus-version.json` before the
   run starts, or (b) read `embedder_version` from sampled old rows. Option (a)
   is authoritative and cheap. **Recommend (a).**

4. **`docs/ops/re-embed-runbook.md` path:** The brief specifies
   `docs/ops/re-embed-runbook.md`. Under the repo's strict doc-placement rule
   (CLAUDE.md §1), `docs/` is for user-facing documentation referenced by the
   root README. Operator runbooks are arguably user-facing. Both the bulk-ingest
   runbook (`docs/ops/bulk-ingest-runbook.md`) and the delta-loop runbook
   (`docs/ops/delta-loop.md`) already live in `docs/ops/`. Use the same path.
   The root README should NOT link to it (precedent: bulk-ingest-runbook is
   also unlinked per E11_S02 F12 deferral).

---

## 6. External writes the implementation will require

| type | target | why |
|---|---|---|
| new file | `ingest/re_embed.py` | the partial re-embed script (primary deliverable) |
| new file | `docs/ops/re-embed-runbook.md` | operator runbook (secondary deliverable) |
| none | — | no pushes, PRs, tickets, infra mutations, or third-party API calls required |

The implementation is entirely local. No schema changes to `CHUNKS_SCHEMA_V1`
(the `embedder_version` column already exists). No new Makefile targets are
strictly required by the brief, but a `make re-embed ARGS="..."` target should
be added following the `make ingest` precedent (IS1-class operator
reproducibility).
