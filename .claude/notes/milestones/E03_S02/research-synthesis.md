# E03_S02 Research Synthesis — Idempotent re-embed

**Sources:** `research-brief-1.md` (Sonnet-A), `research-brief-2.md` (Sonnet-B)
**Status:** convergent on core; one resolved divergence (option (a) vs (b)).
**Written:** 2026-05-07

---

## Decisions where both researchers agreed

### D1. The brief's "pre-flight LanceDB query" must adapt to NPZ-first

The brief's literal `SELECT chunk_id, chunker_version FROM chunks WHERE
embedding_stmt IS NOT NULL OR embedding_proof IS NOT NULL` is
structurally impossible — E04_S01 (LanceDB) has not landed; E03_S01
ships NPZ-first. Same adaptation pattern as D1 of the E03_S01
synthesis: keep the brief's *intent* (skip already-embedded chunks
when version matches), change the *mechanism* to NPZ-aware.

### D2. `EXPECTED_CHUNKER_VERSION` must alias `CHUNKER_VERSION`, not redefine the literal

The brief says define `EXPECTED_CHUNKER_VERSION = "v1.0"` in
`embedder.py`. But `CHUNKER_VERSION = "v1.0"` is already the
single source of truth in `ingest/chunker_types.py` (locked by
`tests/test_chunker_ids.py::TestSingleVersionDefinition::test_v1_0_literal_count_in_ingest_package`,
which scans the entire `ingest/` tree and refuses any unauthorized
`"v1.0"` literal). Defining a second literal would either fail the
existing test (good!) or, if exempted, drift on the next bump.

**Resolution:**
```python
from ingest.chunker_types import CHUNKER_VERSION as EXPECTED_CHUNKER_VERSION
```
This satisfies the brief's requirement that `EXPECTED_CHUNKER_VERSION`
be "defined as a constant in exactly one place" because the literal
`"v1.0"` continues to live only in `chunker_types.py`. The embedder
exposes the alias under the brief's preferred name without holding a
second copy of the value.

### D3. The brief's "LanceDB MVCC writer serializes writes" concurrency claim must be restated

LanceDB does not exist yet. The actual concurrency safety comes from
`os.replace` (POSIX-atomic rename) inside `_write_embeddings_npz`. Two
processes writing the same paper's NPZ produce a last-writer-wins
outcome where neither reader ever sees a partial file. Module
docstring must document this NPZ-level atomicity, not LanceDB MVCC.
Both researchers flagged this independently.

### D4. `EmbedStats.chunks_skipped` is already in place

The `chunks_skipped: int` field landed in E03_S01 but is always 0
today. E03_S02 populates it. The `run_summary` JSONL line should
aggregate `chunks_skipped` across papers so an "all up to date" run
is observable from the audit trail.

### D5. The "Skipped N/N chunks — all up to date." log fires from `embed_corpus` run summary

Per-paper logs are too noisy. Fire at the corpus level when
`sum(chunks_skipped) == sum(total_chunks)` and `sum(chunks_processed)
== 0` across all papers.

---

## Decision with divergence — resolved

### D6. Skip-set storage: sidecar `embeddings_manifest.json` (option (b))

Researcher A recommended option (a) — read `chunk_ids_*` arrays out of
the NPZ + use `chunk_manifest.json`'s `chunker_version` as the version
oracle. No new file format.

Researcher B recommended option (b) — a per-paper sidecar
`embeddings_manifest.json` written alongside `embeddings.npz`,
recording `chunker_version`, `embedder_version`, and the set of
embedded chunks.

**Adopting option (b)** for these reasons:

1. **No `allow_pickle=True` exposure.** The NPZ stores chunk_ids as
   `dtype=object` arrays, which `np.load` only reads back with
   `allow_pickle=True`. Even though our own code wrote the file, opening
   pickle-bearing NPZs on every embed run is a needless surface. JSON
   sidecar avoids it entirely.

2. **`embedder_version` becomes a first-class skip dimension.** The
   brief literally only gates on `chunker_version`, but a `BGE_M3_
   COMMIT_SHA` bump produces vectors in a different embedding space
   that the new index would silently mix with old ones — that is the
   exact "broken invariant" pattern the BP1 discipline guards against.
   Recording `embedder_version` in the sidecar makes the invariant
   visible at every read; the skip logic can choose to gate on it
   (we will — see D7).

3. **O(1) skip pre-flight.** A single `json.loads(sidecar.read_text())`
   per paper, no NPZ open at all when the paper is fully up-to-date.
   Option (a)'s per-paper NPZ open is heavier than this.

4. **Schema mirrors `chunk_manifest.json` discipline.** Both are
   `*_manifest.json` files written atomically alongside the data
   they describe. Future maintainers see a consistent pattern.

### D7. Sidecar schema (alphabetical keys, sorted, no timestamps — BP1)

```json
{
  "chunker_version": "v1.0",
  "embedded_chunks": [
    {"chunk_id": "arxiv:2307.01156:a1b2c3d4e5f60718", "kind": "stmt"},
    ...
  ],
  "embedder_version": "bge-m3@5617a9f6",
  "paper_id": "2307.01156"
}
```

Written via the same atomic tmp + `os.replace` pattern as the NPZ.
Order: write NPZ first, then write sidecar. Reader rule: a paper is
"up to date" iff (sidecar exists) AND (`sidecar.chunker_version ==
EXPECTED_CHUNKER_VERSION`) AND (`sidecar.embedder_version ==
EMBEDDER_VERSION`) AND (every chunk_id in the current
`chunk_manifest.json` is in `sidecar.embedded_chunks`). If any
condition fails, re-embed the entire paper (NPZ rewrite is atomic so
partial-update concerns don't apply).

The brief's literal scope only mentions `chunker_version`. Adding the
`embedder_version` gate is an additive correctness improvement that
matches the brief's intent — the milestone's risk note is "at 200K
papers, re-embedding from scratch on every ingestion run would be
prohibitively slow," which applies equally to model SHA bumps. Without
the embedder_version gate, a model bump leaves stale vectors in place
silently; with it, the bump triggers re-embed (correct).

### D8. Mixed-paper handling (some chunks new, some up-to-date)

`np.savez` does not support partial NPZ updates. If a paper has even
one new or stale chunk, the entire paper's NPZ must be rewritten.
This is the simplest and matches the existing atomic-write pattern.

For E03_S02's scope, the "new chunks added since last embed" path is:
detect manifest carrying chunks not in the sidecar's `embedded_chunks`
list → re-encode the entire paper (not just the new chunks). The
brief's acceptance criterion "New chunks added since the last embed
run are embedded" is satisfied: the new chunks land in the rewritten
NPZ. The corpus-wide skip optimization is preserved because the cost
of re-encoding is paid only on papers that genuinely changed.

A more granular optimization (encode-only-new + merge-with-cached)
would require reading the existing NPZ's vectors and merging them with
freshly-encoded ones. That's a useful E04_S02 / E11 optimization but
not required by E03_S02's literal acceptance criteria.

---

## Decisions on test design

### D9. Three named tests covering the brief's three acceptance criteria

`tests/test_embedder_idempotent.py`:

1. `test_second_run_is_zero_writes` — embed twice on an unchanged
   corpus. Assert the second run's `chunks_processed == 0`,
   `chunks_skipped == total`, and the NPZ + sidecar mtimes are
   unchanged after the second run.

2. `test_chunker_version_mismatch_forces_reembed` — write a sidecar
   with a stale `chunker_version` (e.g. `"v0.9"`). Run embed. Assert
   the affected paper is re-embedded (`chunks_processed > 0`) and the
   sidecar now has `chunker_version == EXPECTED_CHUNKER_VERSION`.

3. `test_new_chunk_is_embedded_others_skipped` — embed paper P with
   chunks {A, B}. Add chunk C to the manifest. Run embed again.
   Assert the rewritten NPZ contains {A, B, C} and `chunks_processed
   == 3` (since the entire paper is rewritten, not just C — see D8).

Plus a regression guard for D2:
4. `test_expected_chunker_version_is_alias_for_canonical_constant` —
   assert `EXPECTED_CHUNKER_VERSION is CHUNKER_VERSION` (object
   identity, since aliasing).

Plus the brief's race-condition note:
5. `test_concurrent_writes_do_not_corrupt` — spawn two threads each
   calling `_write_embeddings_npz` and `_write_embeddings_manifest`
   for the same paper, with one writer producing slightly different
   chunk_ids. Assert the final NPZ + sidecar are well-formed and
   internally consistent (one of the two writers won; the other's
   tmp files are cleaned up; reader sees no partial file).

### D10. Test fixture must NOT exercise the real BGE-M3 model

Reuse the `_fake_model_factory` pattern from `test_embedder.py`. CI
must remain offline-capable.

---

## Open questions (deferred to implementation)

- **Backward compatibility with E03_S01 NPZs that have no sidecar:**
  the absence of a sidecar means "embed this paper from scratch." This
  is the desired behavior — the existing NPZs from before E03_S02 are
  treated as "unknown provenance, must re-encode." This forces one
  full re-embed corpus-wide on the E03_S02 upgrade, which is fine for
  the seed corpus. Documented behavior; no compat shim.

- **Sidecar schema evolution.** Future fields (e.g. truncation count,
  vector hashes) can be added. The reader skips unknown fields
  silently; missing required fields trigger re-embed. No schema
  version on the sidecar itself for now — `chunker_version` +
  `embedder_version` together carry enough provenance.

---

## External writes the implementation will require

| Path | Event | Notes |
|---|---|---|
| `ingest/embedder.py` | source edit | add `EXPECTED_CHUNKER_VERSION` alias, sidecar writer, skip logic, updated module docstring (POSIX-atomic concurrency, not LanceDB MVCC) |
| `var/arxmcp/corpus/embeddings/<paper_id>/embeddings_manifest.json` | per paper, when re-embed actually runs | sidecar JSON written atomically immediately after the NPZ via tmp + os.replace |
| `tests/test_embedder_idempotent.py` | new test file | 5 tests per D9 |
| `var/arxmcp/ops/embed-stats.jsonl` | existing | `run_summary` line gains aggregate `chunks_skipped` field |

No new dependencies. No third-party API call. No model download —
the BGE-M3 cache populated by E03_S01 is reused if any test calls the
real model (none do — all tests mock).
