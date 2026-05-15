# E11_S03 — Research Synthesis

Merged from [research-brief-1.md](research-brief-1.md) (in-codebase
mechanics: chunk_id canonicalization, LanceDB MVCC copy, sidecar
bypass) and [research-brief-2.md](research-brief-2.md) (operational
surface: GPU throughput, runbook, mixing guard, CLI, test surface).
The briefs converge tightly on the mechanics and complement each
other on operations. One major divergence resolved: GPU throughput
(Brief 2 corrected the brief's 32 c/s CPU figure to 100–400 c/s
on A6000).

---

## 1. Headline findings (consensus)

| # | finding | resolution |
|---|---|---|
| 1 | **The canonical-bytes function is `ingest/chunker.py::_compute_chunk_id`** — `sha256(preamble_text + NFC(body_text))[:16]`. Stable across chunker logic changes; UNSTABLE across changes to the function itself. | `_compute_chunk_id` is frozen per `chunker_version`. Any edit to that function is a SCHEMA migration, not a `chunker_version` bump. Document this constraint in `chunker_types.py` and ship a regression guard. |
| 2 | **No bulk column-copy API in LanceDB ≥0.6.** The only way to copy embeddings from version N to N+1 is read old rows via `to_arrow(filter=f"chunk_id IN [...]")` → reconstruct an `EmbedRecord` → write via the existing `write_chunks`. | Re-embed script reads from old LanceDB version + reconstructs EmbedRecord + calls `write_chunks` for both copy AND re-embed paths. |
| 3 | **Sidecar idempotence cannot serve the copy path.** When the embedder bumps, the sidecar's `embedder_version` check correctly BLOCKS reuse — but the copy path must reuse the old vectors anyway. The copy path must NOT route through `embed_paper`. | Copy path queries old LanceDB directly; re-embed path uses `embed_paper`. Two clean code paths. |
| 4 | **Staging-path discipline preserved.** Re-embed writes to `var/arxmcp/index/lancedb-staging/` (same as E11_S01, E11_S02). The active `corpus-version.json` is NEVER advanced by re-embed. | Activation is E11_S05's cutover. Re-embed advances only the staging LanceDB's internal version integer. |
| 5 | **F1-class silent stale-vector risk.** Copying old rows whose `embedder_version` doesn't match the OLD target embedder version would silently insert wrong vectors. The very thing E11_S01's F1 closed in the bulk path applies here in the copy path. | The copy path MUST verify `old_row.embedder_version == OLD_EMBEDDER_VERSION` (read from `corpus-version.json` at run start) before copying. Mismatch → refuse + log. |
| 6 | **Code guard for embedding-space mixing, not just a runbook warning.** The AC4 warning in Markdown is advisory. The script MUST refuse to write into a staging table containing rows with a different `embedder_version` than the target. | `re_embed.py` reads staging table's distinct `embedder_version` values at start; refuses if any disagree with target. The `--force-mixed-space` escape hatch is rejected as a footgun (see §3 divergence). |
| 7 | **GPU throughput: 100–400 c/s on A6000, not 32 c/s.** The brief's 32 c/s is `EMBED_BATCH_DEFAULT` — a CPU constant. The 5M-chunk re-embed is 7–14h on GPU, not 44h. The other two scenarios scale similarly. | Runbook documents a RANGE (conservative 100 / mid 200 / optimistic 400) per scenario AND a benchmark command so operators can self-calibrate. |
| 8 | **`--resume` is LanceDB-write-side, not sidecar-side.** On resume, scan the staging table for chunk_ids already written and subtract from the work queue. This works uniformly for copy AND re-embed paths. | NO sidecar-based resume. NO repeating E11_S01 F3 (no-op `--resume`). The flag's contract is enforced by a regression test. |
| 9 | **`corpus-version.json` discipline on interruption.** `write_chunks` writes the marker as a postcondition. Per-paper writes during re-embed would advance the staging marker every paper. | Two options identified by Brief 1: (a) skip marker write per paper, batch at end; (b) write `{"status":"in-progress"}` sentinel that the server refuses to load. **D8 below picks option (b)** — minimal surgery, mirrors the design note's atomic activation contract. |
| 10 | **No tool-schema changes.** No new MCP tools. `TOOL_SCHEMA_VERSION` stays at 6. | No hash repins. |

---

## 2. Load-bearing quotes

### `ingest/chunker.py:975` — canonical-bytes (the chunk-identity contract)

> `def _compute_chunk_id(paper_id: str, preamble_text: str, body_text: str) -> str:`
> `    body_normalized = unicodedata.normalize("NFC", body_text)`
> `    digest = hashlib.sha256((preamble_text + body_normalized).encode("utf-8")).hexdigest()[:16]`
> `    return f"arxiv:{paper_id}:{digest}"`

### `ingest/embedder.py:603-685` — sidecar idempotence

> `if sidecar.get("embedder_version") != EMBEDDER_VERSION: return False`

### `ingest/store.py:57-72` — LanceDB-version-is-corpus-version

> "LanceDB version int IS the corpus_version. Writers use the
> current dataset; readers call `dataset.checkout(version=N)`."

### `.claude/notes/07-multi-agent-caching.md` — cache key includes corpus_version

> "Tier 1 — Exact-query (SQLite LRU, 10K entries): key includes
> `corpus_version: int` as a mandatory component; stale entries
> from old corpus versions are unreachable by construction after
> a restart with a new `corpus-version.json`."

(Implication: a re-embed staging write that does NOT advance the
active marker keeps all live cache valid; activation happens only
when E11_S05 promotes.)

### `ingest/embedder.py:131-133` — the 32 figure is CPU, not GPU

> "Default batch size for CPU inference. ~32 chunks ≈ 32 forward
> passes through XLM-RoBERTa-large per call; on a 2020-era laptop
> this delivers acceptable throughput for the 50-paper seed corpus."

---

## 3. Divergence + resolution

### `--force-mixed-space` escape hatch — REJECT

- Brief 2 proposed a `--force-mixed-space` CLI flag as an escape
  hatch for the "copy unchanged, then re-embed changed in the
  same run" scenario where the staging table transiently holds
  rows from two embedder versions.
- Brief 1 didn't propose the flag.

**Resolution:** REJECT the flag. The mixed-space transient only
exists if the copy phase runs FIRST and the re-embed phase runs
SECOND, against the SAME embedder version target. In that case,
the copy phase wrote rows with `embedder_version = NEW_TARGET`
(because the copy path re-stamps the row with the target version,
per Brief 1 §1.5). There is no transient mixed-space state — the
guard never fires legitimately. A `--force-mixed-space` flag is
operator-foot-gun territory and should not exist.

Concretely: the copy path takes the OLD row's embedding VECTORS
(which are valid by content-identity) and writes them as a new
row whose `embedder_version` column is the NEW target. The
embedding space is the same (BGE-M3 weights didn't change, only
the chunker bumped) — `embedder_version` is metadata. When the
embedder TRULY bumps (model-swap scenario), the copy path is NOT
exercised (Brief 1 §1.3: every sidecar fails; everything re-embeds).

**The mixing guard fires only when an operator misconfigures the
target version.** That's exactly when it should fire. No escape
hatch.

### Re-embed staging path: shared with bulk-ingest or separate?

- Brief 1 §1.6 says SHARED (`lancedb-staging/`).
- Brief 2 open Q1 flags this as ambiguous; recommends documenting
  that re-embed must run AFTER a complete bulk-ingest cycle.

**Resolution:** SHARED, with explicit sequencing documented in
the runbook. The re-embed runbook's preamble states: "Re-embed
operates on the contents of `lancedb-staging/`. If a bulk-ingest
or delta-loop run is in flight, the `flock` guard at
`var/arxmcp/ops/.delta.lock` and `.bulk.lock` (precedent: E11_S02)
serializes. Re-embed adds its own
`var/arxmcp/ops/.re-embed.lock`."

---

## 4. Design decisions

### D1. Module: `ingest/re_embed.py`

Owns:
- `ReEmbedSummary` dataclass (mirrors `IngestSummary`).
- `compute_diff(old_chunk_ids, new_chunk_ids) -> (copy, reembed, drop)`.
- `copy_unchanged_embeddings(...)` — reads from old LanceDB via
  `to_arrow(filter=...)`, reconstructs `EmbedRecord`, calls
  `write_chunks` against staging.
- `re_embed_changed_papers(...)` — calls `embed_paper` for each
  paper that has new chunk_ids; assembles `EmbedRecord`; writes.
- `run_re_embed(...)` — top-level orchestrator (state file,
  resume, mixing guard, sentinel corpus-version.json).
- `_cli(...)` — argparse + dispatch.

### D2. Reuse `_compute_chunk_id` + `chunk_paper` + `embed_paper` unchanged

The chunker is invoked over every paper to produce the NEW chunk
set; the diff against the OLD set drives copy vs. re-embed. No
shortcut "trust the old chunk_ids" — the chunker bump may have
changed any chunk's content.

### D3. Staging path: shared `lancedb-staging/`

Per §3 resolution.

### D4. CLI flags

```
--from-corpus-version=<int>     # default: read from active corpus-version.json
--lancedb-staging-path=<path>   # default: var/arxmcp/index/lancedb-staging
--paper-ids-file=<path>         # default: all papers in source LanceDB
--target-embedder-version=<str> # default: ingest.embedder.EMBEDDER_VERSION
--batch-size=<int>              # default: 64 (GPU-friendly)
--dry-run                       # print diff (copy/re-embed/drop) without writes
--resume                        # LanceDB-write-side: skip chunk_ids already in staging
```

NO `--force-mixed-space`. NO `--to-version` (always next integer).
NO `--benchmark-only` — `--dry-run + --limit` covers it.

### D5. Embedding-space mixing guard

Before any write:
1. Open staging table (if it exists).
2. `SELECT DISTINCT embedder_version FROM chunks`.
3. If non-empty AND any value != target → refuse with a clear
   `RuntimeError`. Cite the runbook section in the message.

### D6. F1-class copy-path guard

Before copying any row:
1. Verify `old_row.embedder_version == OLD_EMBEDDER_VERSION` (the
   version recorded in the active `corpus-version.json` at run
   start).
2. Mismatch → refuse + log + skip the row.
3. The copy path stamps `embedder_version = TARGET_EMBEDDER_VERSION`
   on the new row (mechanically simple: it's a metadata column).
   The embedding VECTORS are valid by content-identity.

### D7. `--resume` semantics — LanceDB-write-side only

Implementation:
```python
if args.resume:
    existing_ids = set(
        staging_tbl.to_arrow(columns=["chunk_id"]).to_pydict()["chunk_id"]
    )
    work_queue = [c for c in work_queue if c.chunk_id not in existing_ids]
```

Regression guard: `TestResume::test_resume_skips_done_chunks`
asserts the second-run embedder mock receives ONLY the
not-yet-written chunks. Mirrors E11_S01 F3 + IS2 lesson — no
no-op flags.

### D8. `corpus-version.json` sentinel on the staging path

Per Brief 1 open Q1, option (b): the re-embed script writes
`{"status":"in-progress","target_version":N,"started_utc":"..."}`
to the STAGING `corpus-version.json` at run start. Overwrites
with the real version doc at run end (via `write_chunks`'s
postcondition + a final consolidation step).

The active `corpus-version.json` at `var/arxmcp/index/lancedb/`
is NEVER touched. Server startup checks `status == "complete"`
on whatever marker it's pointed at — if it's pointed at staging
and finds `in-progress`, it refuses to boot. (Out of scope to
implement the server-side check in this milestone — that's
E11_S05's cutover. v1 just writes the sentinel; server code
already inspects the marker structure.)

Actually — re-examining: the server reads ONLY the active
marker, never the staging marker. So the staging-side sentinel
is harmless to the server. It serves operator monitoring +
`re_embed.py --resume` detection. **Keep the sentinel
implementation, scoped to operator/script use.**

### D9. State file: `var/arxmcp/ops/re-embed-state.json`

Mirror Brief 2's schema. Persist after every paper:

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

Atomic write via tmp + rename (precedent: E11_S02
`_write_state`). On successful completion: `status = "complete"`,
`to_lancedb_staging_version = <int>`.

### D10. `flock` reentrancy guard

Shell wrapper at `ops/cron/arxmcp-re-embed.sh` (optional v1 —
operators primarily invoke `make re-embed`). Lock file:
`var/arxmcp/ops/.re-embed.lock`. Same pattern as E11_S02.

### D11. Makefile target: `make re-embed`

Mirrors `make ingest` + `make delta` from E11_S01 + E11_S02.
Includes the Python version guard.

### D12. Runbook: `docs/ops/re-embed-runbook.md`

Sections (mirror E11_S01 + E11_S02 structure):
1. Scope note (when to use; what it does NOT do — namely
   activate the new corpus).
2. Prerequisites (GPU optional; A6000 or equivalent; the OLD
   corpus must exist at `var/arxmcp/index/lancedb/`).
3. **GPU-hours budget table** — 4 scenarios (model swap, chunker
   fix, macro normalizer fix, ar5iv re-fetch subset), 3 columns
   (conservative / mid / optimistic).
4. Step-by-step procedure (dry-run → small smoke test → full run).
5. **Embedding-space mixing warning** — explicit AC4 language.
6. Failure modes (GPU OOM, mid-batch kill, disk full, mid-index
   build).
7. Resume semantics — explicit walkthrough of the LanceDB-write-side
   resume contract.
8. Sentinel + state-file location.
9. See also: cross-links to bulk + delta runbooks, E11_S05 cutover.

### D13. Test surface — 5 ACs verifiable at code-ship

Per Brief 2 §5:
- AC1: `TestCopyEfficacy::test_95_percent_copy` — 100 chunks, 5
  mutated, mocked embedder, assert `chunks_copied == 95` and
  embedder called once.
- AC2: `TestResume::test_resume_skips_done_chunks` — halt at
  mid-paper, re-run with `--resume`, assert remaining chunks
  embedded.
- AC3: `TestRunbookContent::test_gpu_hours_table_present` —
  asserts all 4 scenarios appear.
- AC4: `TestRunbookContent::test_warns_against_mixing_spaces`.
- D5 guard: `TestSpaceMixingGuard::test_refuses_mixed_space` —
  staging table with stale `embedder_version` → `RuntimeError`.

Plus regression guards:
- `TestComputeChunkIdFrozen::test_signature_unchanged` — pins the
  `_compute_chunk_id` function's source-bytes SHA so a future PR
  edit forces a deliberate test update (Brief 1 Landmine A).
- `TestCopyPathStampsTargetVersion::test_embedder_version_rewritten` —
  copy path takes old vectors but writes the new `embedder_version`
  on the row.
- `TestCopyPathRefusesOnVersionMismatch::test_refuses_old_row_with_wrong_version`
  — F1-class guard test.

### D14. No tool-schema changes

`TOOL_SCHEMA_VERSION` stays at 6.

### D15. README link to the runbook

Per Brief 2 open Q (advisory): NOT in this milestone. Precedent
(E11_S01 F12 / E11_S02 IS3) — link both runbooks in a single
later doc-tidy. Track as a deferred item.

---

## 5. Forced cross-file changes

| File | Change | Why |
|---|---|---|
| `ingest/re_embed.py` (NEW) | Core re-embed module + CLI | D1, D2, D4-D9 |
| `ops/cron/arxmcp-re-embed.sh` (NEW; OPTIONAL) | flock wrapper | D10 — defer to operator if not needed v1 |
| `Makefile` (MODIFY) | Add `make re-embed` target with Python guard | D11 |
| `docs/ops/re-embed-runbook.md` (NEW) | Operator runbook | D12 |
| `tests/test_re_embed.py` (NEW) | All ACs + regression guards | D13 |
| `ingest/chunker_types.py` (MODIFY) | Docstring constraint pinning `_compute_chunk_id` source-stability | Landmine A |

NOT touched: `server/`, `ingest/store.py`, `ingest/embedder.py`,
`ingest/chunker.py` (the `_compute_chunk_id` function is FROZEN,
not modified), hash-anchored tests.

---

## 6. Landmines (consolidated)

1. **`_compute_chunk_id` is frozen per `chunker_version`.** Any
   change to that function is a schema migration.
2. **Sidecar idempotence cannot serve the copy path** when the
   embedder bumps. Copy path queries LanceDB directly.
3. **No bulk column-copy API.** Read old rows → reconstruct
   EmbedRecord → write via `write_chunks`.
4. **Staging-path discipline.** Active marker NEVER touched.
5. **F1-class silent stale-vector risk.** Copy path must verify
   `old_row.embedder_version == OLD_TARGET`.
6. **Embedding-space mixing.** Code guard, not just runbook.
7. **GPU throughput is 100–400 c/s, not 32 c/s.** Runbook ranges
   + benchmark command.
8. **`--resume` is LanceDB-write-side.** No no-op flags.
9. **`corpus-version.json` discipline.** Staging sentinel only;
   active marker untouched.
10. **`assert` banned for invariants.**
11. **HEREDOC commits, GPG signed, no `--no-verify`.**

---

## 7. AC coverage at code-ship

| AC | Coverage |
|---|---|
| 95% unchanged → 95% copied without re-compute | Verifiable: `TestCopyEfficacy` with synthetic 100-chunk corpus + mocked embedder. |
| `--resume` skips already-embedded chunks | Verifiable: `TestResume` halts and re-runs. |
| Runbook has GPU-hours table for all scenarios | Verifiable: runbook-content test. |
| Runbook warns against mixing embedding spaces | Verifiable: runbook-content test. |

All ACs verifiable at code-ship. None operator-gated.

---

## 8. External writes required

**None.** All local. The re-embed script writes to:
- `var/arxmcp/index/lancedb-staging/` rows
- `var/arxmcp/ops/re-embed-state.json`
- `var/arxmcp/index/lancedb-staging/corpus-version.json` (sentinel
  + final marker)

No HTTP fetches. No pushes, PRs, tickets, infra mutations,
third-party API calls.

---

## 9. Suggested implementation order

1. `ingest/re_embed.py` core: `ReEmbedSummary`, `compute_diff`,
   `copy_unchanged_embeddings`, `re_embed_changed_papers`,
   `run_re_embed`, `_cli`.
2. `tests/test_re_embed.py` — all 5 ACs + 4 regression guards.
3. `Makefile` — `make re-embed`.
4. `docs/ops/re-embed-runbook.md` — operator runbook.
5. `ingest/chunker_types.py` — docstring constraint.
6. `make test` (full suite); ruff clean; commit.

---

## 10. Done-when checklist

- [ ] All 4 brief ACs covered by verifiable tests at code-ship.
- [ ] `_compute_chunk_id` stability documented in
  `chunker_types.py`; regression test in place.
- [ ] Staging-path discipline preserved — active marker never
  touched.
- [ ] F1-class guard in place: copy path verifies old row's
  `embedder_version`.
- [ ] Code guard for embedding-space mixing in place; tests
  exercise it.
- [ ] `--resume` actually works (LanceDB-write-side); test
  verifies.
- [ ] GPU-hours table in runbook lists 4 scenarios with ranges.
- [ ] Runbook warns explicitly against mixing embedding spaces.
- [ ] `make re-embed` target in Makefile mirrors `make ingest`
  pattern.
- [ ] State file schema matches D9.
- [ ] No `TOOL_SCHEMA_VERSION` bump.
- [ ] `make test` green; ruff clean.
