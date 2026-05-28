# notebook-cutover — Per-notebook staging→active cutover for re-embedded datasets

**Owner:** Chris Dare
**Created:** 2026-05-28
**Status:** scoped
**Source:** operational gap discovered running `make re-embed-all` after notebook-preamble-recovery-m1

**Why this exists.** `tools/re_embed_all.py` reads each notebook's
active `lancedb` and writes the re-embedded result to a sibling
`lancedb-staging`. There is **no promotion step** — `make cutover`
(E11_S05) only swaps the *shared* corpus at `var/arxmcp/index/lancedb`.
Consequence discovered 2026-05-28: BOTH the embedder-truncation-m1
re-embed AND the notebook-preamble-recovery-m1 re-embed landed in
`<notebook>/lancedb-staging` and were never promoted. The MCP server
reads `<notebook>/lancedb`, so it has served **stale** embeddings
(512-token, zero preambles, corpus_version 369 / 49) this entire time
while two generations of improved embeddings sat un-promoted in staging.

**Live state at milestone creation (do NOT lose this — the operator
wants this staging data promoted, not recomputed):**

| Notebook | ACTIVE `lancedb` | STAGING `lancedb-staging` |
|---|---|---|
| bridgeland-stability | 6804 chunks, 0 preambles, 512-tok, **v369** | 10298 chunks, 5037 preambles (48%), 2048-tok, **v645** |
| shimura-varieties | (May-21 ingest), **v49** | fully re-embedded, **v143** |

The staging chunk-count rise (6804→10298) is the legitimate
`CHUNKER_VERSION` v1.0→v1.1 theorem-env-alias expansion (commit
97cc9ef), NOT a regression.

---

### notebook-cutover-m1 — Add atomic staging→active cutover + rollback for notebook datasets

**Description.** Add a per-notebook cutover capability so re-embedded
staging datasets can be promoted to the server's live read path. The
shared-corpus `make cutover` (E11_S05) is the design precedent — atomic
directory swap with rollback — but it is hardcoded to
`var/arxmcp/index/lancedb` and its 4-gate activation criteria (seed
eval, watchdog, ingest-complete, restore-drill) which do NOT apply to
per-notebook datasets. This milestone builds the notebook-scoped
equivalent.

**Design decisions (resolve in research; these are the starting
positions):**

1. **Cutover is a SEPARATE step, not auto-after-re-embed.** Keep
   `re_embed_all` writing to staging by default. Add a distinct
   `make notebook-cutover` target + a `tools/notebook_cutover.py`
   (or extend `tools/re_embed_all.py` with a `--cutover` flag). The
   reason cutover stays separate: the operator-followup B-3/AC6
   measurement workflow (`.claude/notes/milestones/embedder-truncation-m1/operator-followup.md`)
   needs BOTH active (old) and staging (new) present to compute the
   pre/post nDCG@5 delta. Auto-promoting would destroy that
   comparison. This mirrors the shared-corpus flow's deliberate
   re-embed/cutover separation.

2. **Atomic swap with timestamped backup.** Per notebook:
   `lancedb` → `lancedb-prev-<UTC-timestamp>`, then
   `lancedb-staging` → `lancedb`. Two `os.rename` calls (atomic on
   POSIX within a filesystem). Keep the most recent N=2 `lancedb-prev-*`
   backups; prune older ones to bound disk.

3. **Rollback** (`make notebook-cutover ARGS="--rollback --notebook=<slug>"`):
   inverse swap — restore the most recent `lancedb-prev-*` to
   `lancedb`, move the current `lancedb` back to `lancedb-staging`.

4. **Pre-cutover safety gates** (refuse + exit non-zero, no mutation):
   - staging dir missing or has no `chunks.lance` → refuse.
   - staging `corpus-version.json` version ≤ active version → refuse
     (would be a downgrade; operator passes `--force` to override).
   - server appears to be running (probe `127.0.0.1:7733/healthz`) →
     WARN loudly but allow (operator may have a reason); a hot swap
     while the server holds an open LanceDB handle is the risk.
   - active `lancedb` missing → this is the first-ingest case; just
     promote staging without a backup.

5. **BM25 index after cutover.** The re-embed bumps `corpus_version`;
   the BM25 index is version-keyed (`var/arxmcp/index/bm25/v<N>/`).
   Verify whether the cutover must trigger a BM25 rebuild for the
   newly-active version, or whether the first query rebuilds lazily
   (`ingest/bm25_indexer.py`). Research must resolve this — a cutover
   that leaves BM25 pointing at the old version is a silent
   retrieval-quality regression.

**Acceptance criteria.**

- **[AC1]** Given a notebook with a healthy `lancedb-staging` whose
  `corpus_version` > active, When `make notebook-cutover
  ARGS="--notebook=<slug>"` runs, Then `lancedb` holds the former
  staging content, a `lancedb-prev-<ts>` backup of the former active
  exists, and `lancedb-staging` no longer exists. Verified by a
  subprocess test against a synthetic 2-version fixture.
- **[AC2]** Given a completed cutover, When `--rollback` runs, Then
  the former active is restored to `lancedb` and the promoted content
  moves back to `lancedb-staging`. Round-trip is lossless (chunk
  counts + corpus_version match the pre-cutover state).
- **[AC3]** Given a staging `corpus_version` ≤ active, When cutover
  runs without `--force`, Then it refuses with exit non-zero and
  mutates nothing. With `--force`, it proceeds.
- **[AC4]** Given a missing/empty staging dir, When cutover runs,
  Then it refuses with a clear error and mutates nothing.
- **[AC5]** Given `--all-notebooks` (default), When cutover runs,
  Then every notebook with a promotable staging dir is cut over;
  per-notebook failures are isolated (one bad notebook does not abort
  the others) and surfaced in the summary + a non-zero exit.
- **[AC6]** Backup retention: after a cutover, at most N=2
  `lancedb-prev-*` dirs remain per notebook; older ones pruned.
- **[AC7]** BM25 consistency: after cutover, the BM25 index for the
  newly-active `corpus_version` either exists or is rebuilt by the
  cutover (resolve which in research). A query against the cut-over
  notebook must not silently fall back to a stale BM25 version.
- **[AC8]** `make notebook-cutover` help text + the
  `tools/notebook_cutover.py` docstring document the
  measure-then-promote workflow and the rollback command.
- **[AC9]** The TWO live staging datasets (bridgeland v645, shimura
  v143) are promotable by the new tool — verified by the operator
  running `make notebook-cutover` post-milestone (operator-deferred,
  cross-referenced in operator-followup.md). The pipeline tests use
  synthetic fixtures.
- **[X-1]** `EXPECTED_TOOL_SCHEMA_SHA256` UNCHANGED (no MCP surface).
- **[X-2]** `EXPECTED_BP1_SHA256` UNCHANGED.
- **[X-3]** `ruff check .` clean; `make test` green; 2900+ tests.
- **[X-4]** NO `CHUNKER_VERSION` bump.

**Out of scope (Won't list).**

- Auto-cutover inside `re_embed_all` (deliberately rejected — breaks
  the measurement workflow; see design decision 1).
- The shared-corpus `make cutover` (E11_S05) — unchanged; this is the
  notebook-scoped sibling.
- The 3 non-UTF-8 `.tex` papers (`1506.02744`, `1610.04128`,
  `2604.26329`) that failed preamble extraction in
  notebook-preamble-recovery-m1 — that's a Latin-1-decode-fallback fix
  in `ingest/preamble.py`, a separate milestone.
- The `PYTHON ?= python3` Makefile default that resolves to 3.9 on
  this workstation (operators must pass `PYTHON=python3.12` or use
  `uv run`). Real annoyance but affects ALL targets, not just these —
  separate cleanup. **Quick-win note:** the research may recommend
  documenting the `uv run` invocation in the new target's help text
  to spare the operator the 3.9 trap.
- Server-coordinated hot-swap (graceful handle release). The cutover
  warns if the server is up; coordinating a live reload is future work.

**Dependencies.** None blocking. The live staging data exists and is
healthy; AC9's promotion is the operator's post-milestone step.

**Complexity.** M.

**Specialist suggestions.** `security-reviewer` (path containment on
the notebook slug → directory rename surface, Threat 1) +
`determinism-reviewer` (corpus_version comparison + the BM25-version
consistency gate).

**External writes the implementation will require.** None — all
operations are local filesystem renames within `var/arxmcp/notebooks/`.
No git push, no PR, no infra mutation, no network egress.

**Notes for the researcher agents (phase 1).**

1. Read `make cutover` / the E11_S05 cutover implementation (find it
   via `grep -rl cutover tools/ ingest/ infra/`) — it is the atomic-
   swap + rollback precedent. Quote its swap sequence verbatim and
   adapt for the per-notebook path layout.
2. Resolve the BM25 consistency question (AC7) definitively: read
   `ingest/bm25_indexer.py` and how the notebook retrieval path picks
   the BM25 version. Does the first query rebuild lazily, or does a
   stale BM25 silently serve old results?
3. Confirm the notebook server-read path is `<slug>/lancedb` (not an
   alias) so the swap actually changes what's served. Check
   `server/` notebook retrieval resolution.
4. Quantify backup disk cost: a bridgeland `lancedb` is ~? MB; keeping
   N=2 `lancedb-prev-*` per notebook across all notebooks — is N=2 the
   right retention, or should it be configurable?
5. Threat-1: the `--notebook=<slug>` arg flows into a directory path.
   Reuse `tools._notebook_common.validate_slug` + `notebook_dir`
   (which already enforce the slug regex + symlink rejection). Do NOT
   re-implement.
