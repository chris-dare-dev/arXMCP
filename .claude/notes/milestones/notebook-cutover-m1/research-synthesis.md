# Research Synthesis — notebook-cutover-m1

**Generated:** 2026-05-28 (post-research-phase)
**Merge mode:** orchestrator (main session), two-brief standard merge + orchestrator code verification
**Inputs:** `research-brief-1.md`, `research-brief-2.md`

---

## ⚠️ Premise correction (READ FIRST — affects whether this milestone should ship now)

The two researchers **directly conflicted** on the load-bearing question:
does the MCP server read per-notebook `<slug>/lancedb` at query time?

- **R1:** NO. The server reads `config.lancedb_path` (the SHARED corpus
  `var/arxmcp/index/lancedb`). The notebook query path "is NOT yet wired
  into the MCP retrieval pipeline."
- **R2:** YES. `server/routes/notebooks.py:273` stores
  `lancedb_path = str(nb_dir / "lancedb")`, "the server reads
  `<slug>/lancedb` directly."

**Orchestrator resolution (verified against the code, not averaged):**
**R1 is correct.** Evidence:

- `server/config.py:97`: `lancedb_path: Path = Path("var/arxmcp/index/lancedb")`
  — the retrieval substrate is the shared corpus.
- `server/handlers/search.py:384`: the `search_papers` handler calls
  `get_resources()`, which opens `config.lancedb_path`. No per-notebook
  path is consulted.
- The `notebooks_store.lancedb_path` SQLite column (what R2 found) is
  read ONLY by `server/notebooks_store.py`'s list/get metadata methods
  — never by any retrieval handler. R2 mistook the metadata record for
  the query path.
- There is NO notebook-scoped search route in `server/routes/notebooks.py`.

**Consequence — the milestone's stated urgency was wrong.** Earlier in
this session the operator was told "the server has served stale
embeddings this whole time; the cutover makes the new embeddings live."
That framing is **incorrect**: the MCP server never read the per-notebook
`lancedb` at all. The per-notebook `lancedb` is:
- the INGEST target (`notebook_ingest.py` writes it),
- the re-embed SOURCE (`re_embed_all.py` reads it),
- NOT in any live query path today.

**What the cutover actually buys (corrected value proposition):**
1. **Compounding re-embed source.** Without cutover, every
   `re_embed_all` reads the stale active (`v369`/`v49`) and writes a
   fresh staging — so improvements never compound; they keep landing in
   staging and getting overwritten on the next run. Cutover advances the
   active so the next re-embed builds on the improved version.
2. **Future-proofing.** When the notebook query path IS wired into the
   MCP server (a separate, larger milestone), it will read
   `<slug>/lancedb` (per `notebooks_store`), so having the active
   dir hold the good data matters then.

Both are real but NEITHER is urgent, and NEITHER has live-serving
impact today. This is surfaced to the operator before the implement
phase (see the orchestrator's check-in).

---

## Resolved disagreements

| # | R1 | R2 | Resolution |
|---|---|---|---|
| 1 | Server reads SHARED corpus; notebook query path not wired | Server reads `<slug>/lancedb` directly | **R1 correct** (orchestrator verified: config.py:97 + search.py:384 + no notebook search route). R2 confused metadata column with query path. |
| 2 | BM25 consistency: build post-swap, idempotent-skip | BM25 consistency: build PRE-swap (safest) | **R2 correct on ordering.** Build BM25 for the staging version BEFORE the renames — if the build fails, no directory mutation has happened (clean refusal). Both agree the cutover must BUILD (not defer) the BM25 for the new version; live BM25 dirs are v5/49/81/101/157/369 — v645/v143 do NOT exist yet. |
| 3 | New file `tools/notebook_cutover.py` | New file `tools/notebook_cutover.py` | AGREE. |
| 4 | `--all-notebooks` default | (didn't specify) | R1's `--all-notebooks` default with `--notebook=<slug>` to restrict. |
| 5 | Server-running gate: warn but allow | Server-running: warn; print "RESTART SERVER" post-swap | Combine: warn if `/healthz` 200; print restart hint post-swap (FM-2 — open LanceDB handle follows inode, server won't pick up the swap without restart anyway). |

## Load-bearing constraints (quoted)

- **E11_S05 atomic-swap precedent** (`ops/cutover.py`, both briefs quote verbatim):
  ```python
  os.rename(active_path, rollback_path)        # step 1
  try:
      os.rename(staging_path, active_path)     # step 2
  except OSError as exc:
      os.rename(rollback_path, active_path)    # restore on failure
      raise CutoverError(...)
  ```
  Plus the cross-filesystem `st_dev` equality guard (EXDEV protection) — MUST replicate.
- **Two-rename window (R2 FM-1):** between step 1 and step 2 there is no
  canonical `lancedb`. Crash there → server won't start. Mitigation: print
  the manual-recovery commands to stdout BEFORE the swap begins.
- **`05-storage-and-indexing.md`:** "Manual symlink swaps explicitly
  prohibited." `os.rename` (dir move, no symlink) is compliant. The N=7
  MVCC-version retention is about LanceDB-internal versions, NOT the
  directory-level `lancedb-prev-*` backups (N=2 here) — no contradiction.
- **Threat 1:** `--notebook=<slug>` → reuse `validate_slug` + `notebook_dir`
  from `_notebook_common.py` (regex + resolve-containment + symlink reject).
  Do NOT re-implement.
- **LanceDB dir is move-safe** (R2): manifest references are relative;
  `os.rename` of the whole dir on one filesystem preserves consistency.

## Disk footprint (both briefs agree)

| Dataset | active | staging | N=2 backup overhead |
|---|---|---|---|
| bridgeland-stability | 505 MB | 923 MB | ~1 GB |
| shimura-varieties | 57 MB | 143 MB | ~114 MB |

N=2 retention hardcoded for v1.

## Failure modes (merged, R2's enumeration)

FM-1 crash between renames → print recovery commands pre-swap.
FM-2 server holds open handle → warn + "RESTART SERVER" hint (no live impact today anyway, per the premise correction).
FM-3 disk-full during prune → WARNING not ERROR; prune failure non-fatal, exit 0 if core swap succeeded.
FM-4 BM25 staleness → BUILD pre-swap (AC7).
FM-5 slug path traversal → validate_slug + notebook_dir.
FM-6 rollback with no backup → clean refusal, exit non-zero.
FM-7 concurrent cutover + re-embed → document "don't run both"; advisory only.

## Implementation plan (if the operator green-lights the implement phase)

INLINE. New `tools/notebook_cutover.py` (~250 LOC) + `make notebook-cutover` + tests.

1. `tools/notebook_cutover.py`: `discover_promotable(notebooks_base)`,
   `perform_cutover(slug)` (build BM25 pre-swap → 2-rename with st_dev guard
   + rollback-on-step-2-failure → prune to N=2), `perform_rollback(slug)`,
   `main()` with `--notebook` / `--all-notebooks` (default) / `--rollback` / `--force`.
2. Reuse `validate_slug` + `notebook_dir` (Threat 1). Reuse `build_bm25_index`.
3. `make notebook-cutover` target (help text: restart-server hint, ARGS footgun, don't-run-concurrent).
4. Tests in `tests/tools/test_notebook_scripts.py` (or a new file): AC1 swap+backup, AC2 rollback lossless, AC3 downgrade-refuse, AC4 missing-staging-refuse, AC5 all-notebooks isolation, AC6 N=2 prune, FM-1 recovery-message, FM-5 slug-traversal, FM-6 rollback-no-backup. All synthetic-fixture (no model).
5. The `PYTHON ?= python3` 3.9 trap (bit the operator twice) — document the `uv run` invocation in the target help.

## Open questions

None for implementation. The one open ITEM is a PRODUCT decision, not a code question: **given the corrected premise (no live-serving impact today), does the operator still want this milestone now, or is the more valuable work wiring the notebook query path into the MCP server?** Surfaced to the operator.

## External writes the implementation will require

None — local `os.rename` / `shutil.rmtree` within `var/arxmcp/notebooks/` + a BM25 write to `var/arxmcp/index/bm25/v<N>/`. No git push / PR / infra / API. The operator-invocation of the cutover on LIVE data (AC9) is operator-deferred (and was auto-mode-blocked earlier this session — correctly).

## Orchestrator synthesis note

The R1/R2 conflict on the server-read path was the single most
important output of this research phase — it inverts the milestone's
urgency. The orchestrator resolved it by reading the code directly
(config.py:97, search.py:384, the absence of a notebook search route)
rather than averaging the two briefs. R2's other contributions
(build-BM25-before-rename, the 7 failure modes, LanceDB move-safety)
are adopted. R1's contributions (E11_S05 verbatim swap sequence, disk
measurement, the corrected query-path framing) are adopted.

The pipeline is PAUSED at research-complete pending an operator
go/no-go on the implement phase, because the corrected premise
materially changes the milestone's priority and the operator approved
it under the incorrect "server serves stale data" framing.
