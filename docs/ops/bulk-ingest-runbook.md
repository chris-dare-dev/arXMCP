---
project: arxmcp
type: doc
tags:
- project/arxmcp
- type/doc
- authorship/agent-generated
authorship: agent-generated
---

# Bulk ingest runbook (E11_S01)

**Use when:** transitioning from the 50-paper math.AG seed corpus
to the ~200K-paper full corpus (math.AG, math.NT, math-ph, hep-th).
This runbook covers the **operator workflow** for the multi-day
ingest. The Python module `ingest.bulk_ingest` and the
`make ingest` target ship as scaffolding; the actual download,
LaTeXML pre-parse, and GPU embedding are gated on operator action.

> **The full milestone contract is NOT closed by `make ingest`
> alone.** The brief lists Kùzu citation-graph population
> alongside chunk ingest as part of the E11_S01 deliverables.
> **Step 6 (citation-graph population) is part of this
> milestone's contract.** A staging LanceDB without an
> accompanying Kùzu graph means the `cite_neighbors` tool will
> return empty results after cutover. Do NOT skip step 6.

> **AC4 (`pytest --hybrid --ndcg-min=0.70`) is deferred to E11_S04.**
> The 20-query eval fixture is hand-labeled and was tuned on the
> seed corpus; re-labeling against the full corpus is E11_S04's
> scope. After step 5 passes, this milestone is closed even
> though AC4 cannot yet be exercised.

> **Cutover note.** This runbook covers ingest INTO the staging
> LanceDB only. Promoting the staging dataset to active
> (`corpus-version.json` advancement, server restart) is **E11_S05's
> cutover-runbook**. Until that runbook fires, the active server
> sees no changes.

---

## Prerequisites

### System binaries

* **`aria2c`** — BitTorrent client. `brew install aria2` /
  `apt install aria2`.
* **`latexmlc`** — for the LaTeXML fallback when ar5iv misses.
  `brew install latexml` / `apt install latexml`. The same binary
  the E10_S04 drift detector uses.
* **GPU optional but recommended.** The embedder runs on CPU
  (`torch>=2.0`); a single A6000/4090 brings the ingest down from
  weeks to ~1-2 days. No code changes — `embed_paper` picks up
  whatever device PyTorch defaults to.

### Environment

```bash
export ARXMCP_CONTACT_EMAIL="you@example.com"   # arXiv TOS §3
```

### Disk

* `~300 GB` for the Academic Torrents extracted .tex source
  (`var/arxmcp/corpus/raw/`).
* `~20 GB` for the ar5iv HTML cache (`var/arxmcp/cache/ar5iv/`).
* `~100 GB` for the staging LanceDB
  (`var/arxmcp/index/lancedb-staging/`).
* `~30 GB` for chunked + embedded artifacts under
  `var/arxmcp/corpus/{chunks,embeddings}/`.

Plan ~500 GB of free space.

---

## Step 1 — Download the Academic Torrents arXiv source dump

The download is intentionally NOT automated; the magnet link
rotates with each new dump, and ~300 GB of bandwidth deserves
operator review.

```bash
# Verify aria2c is available + read the operator workflow.
ingest/bulk_download.sh
```

This prints the operator instructions and exits. Follow them:

1. Find the current arXiv source magnet at
   <https://academictorrents.com/browse.php?search=arxiv>.
2. Run aria2c against the magnet:
   ```bash
   aria2c \
     --file-allocation=none \
     --seed-ratio=0 \
     '<magnet-link-here>'
   ```
3. Extract per-paper `.tar.gz` tarballs into
   `var/arxmcp/corpus/raw/<paper_id>/`. The extraction step is
   tarball-specific (some Academic Torrent dumps are nested
   archives); adjust paths so the final layout is one directory
   per paper, with the paper's `.tex` files inside.

Expected wall time: ~6-12 hours on a 100 Mbit connection.

---

## Step 2 — Pre-parse via LaTeXML (optional — only for ar5iv misses)

The bulk-ingest orchestrator's fallback ladder is **ar5iv first,
LaTeXML on cache miss**. Most post-2007 papers will hit ar5iv;
the operator only needs to pre-parse the misses.

If you're confident the corpus is mostly post-2007 (the four
target subjects are dominated by post-2010 papers), skip this
step and let the orchestrator log ar5iv misses to
`ops/parser-failures/bulk.jsonl`. After the run, batch-pre-parse
just those papers with `tools/arxiv_fetch.py` and re-run
`make ingest --resume`.

If you want to pre-parse upfront:

```bash
find var/arxmcp/corpus/raw -mindepth 1 -maxdepth 1 -type d \
    -exec basename {} \; | sort | while read -r paper_id; do
    python -m tools.arxiv_fetch "$paper_id"
done
```

This populates `var/arxmcp/corpus/parsed/<paper_id>/index.html`
for every paper that has a usable `.tex`.

---

## Step 3 — Smoke test before the multi-day run

A dry-run + small-limit smoke test catches configuration mistakes
before they consume hours of compute.

```bash
# Dry-run prints the planned action per paper; no writes.
make ingest ARGS="--paper-ids-file=tools/seed-papers.txt --dry-run"

# Smoke test: ingest 5 papers from the existing seed list.
make ingest ARGS="--paper-ids-file=tools/seed-papers.txt --limit=5"
```

Expected output (smoke):
```
loaded 50 paper ids from tools/seed-papers.txt
2026-05-15T... paper=... total=5 ok=N fail=M ar5iv_hits=K ...
total=5 ok=N fail=M skip=0 ar5iv_rate=... elapsed=...s
```

Inspect:

* `var/arxmcp/ops/ingestion.log` — progress + ar5iv hit rate.
* `var/arxmcp/ops/parser-failures/bulk.jsonl` — any failures.
* `var/arxmcp/index/lancedb-staging/` — should now exist with
  fresh chunks.

If the smoke test passes, continue to step 4.

---

## Step 4 — Full ingest

Generate a paper-id list for the 200K corpus. The list source
depends on operator setup — typical recipe:

```bash
# Example: list every paper extracted from the torrent.
find var/arxmcp/corpus/raw -mindepth 1 -maxdepth 1 -type d \
    -exec basename {} \; | sort > ops/all-papers.txt
wc -l ops/all-papers.txt
```

Kick off the full run:

```bash
# Foreground with progress logging. Plan for 1-2 days on GPU,
# ~1 week on CPU.
make ingest ARGS="--paper-ids-file=ops/all-papers.txt"
```

To resume an interrupted run:

```bash
make ingest ARGS="--paper-ids-file=ops/all-papers.txt"
```

There is no `--resume` flag at v1. The embedder is independently
idempotent: when its per-paper sidecar exists and the
`embedder_version` + `chunker_version` match, it short-circuits
without recomputing embeddings (see `ingest/embedder.py`'s
sidecar version check). Naive re-runs are therefore safe — they
will re-walk the chunker (cheap) but skip the GPU work for
already-processed papers.

---

## Step 5 — Verify the staging LanceDB

After ingest completes:

```bash
# AC1: ≥ 100K chunks in the staging LanceDB.
# AC5: ar5iv hit rate ≥ 70%.
# AC2: active corpus-version.json untouched.
ARXMCP_RUN_FULL_CORPUS_TESTS=1 \
    pytest -m requires_full_corpus \
    tests/test_bulk_ingest_sanity.py
```

All three tests must pass before considering the cutover (E11_S05).

---

## Step 6 — Populate the citation graph (E09)

The chunks + embeddings are necessary but not sufficient for the
`cite_neighbors` tool. Run the citation-graph ingest against the
new corpus:

```bash
python -m ingest.graph_ingest          # OpenAlex (math.AG, math.NT)
python -m ingest.inspire_ingest         # INSPIRE-HEP (hep-th, math-ph)
python -m ingest.intra_paper_refs       # intra-paper \ref{} chains
```

These modules already exist (shipped in E09).

---

## Step 7 — Hand off to the cutover runbook (E11_S05)

Once steps 4-6 are complete, the staging LanceDB holds the new
corpus and the active server still serves the seed corpus. The
cutover is the deliberate swap; it's documented separately in
`docs/ops/cutover-runbook.md` (E11_S05) and gates on the watchdog
eval passing (E11_S04).

Do NOT manually swap `corpus-version.json` outside the cutover
runbook. The cutover is atomic and tested; manual swaps risk
half-cutover states where the server reads a marker that points
at the staging dataset while in-flight sessions hold the old
LanceDB version handle.

---

## Failure modes + recovery

### Single-paper LaTeXML hangs / crashes

The orchestrator continues past per-paper failures. The hanging
process is bounded by the LaTeXML subprocess timeout (currently
300 seconds — see `tools/arxiv_fetch.py`). Check
`ops/parser-failures/bulk.jsonl` for the affected paper id.

### Network drops mid-ingest

The orchestrator does not retry network failures per-paper. Re-run
with `--resume` to pick up where you left off.

### Disk full

The staging LanceDB and the chunks/embeddings artifacts grow
linearly. If disk runs out, the in-flight `write_chunks` call may
fail mid-merge. Recovery:
1. Free disk space.
2. Re-run with `--resume`. LanceDB's `merge_insert` is idempotent
   per chunk_id, so the partial write is repaired.

### ar5iv 503 / 429

ar5iv is a static CDN — sustained 503s are unusual. If you see
them in the ingestion log, pause the run for an hour and resume.
The orchestrator treats ar5iv errors as cache misses (logs and
continues), so the run will not abort, but ar5iv-miss-then-LaTeXML
is slow at scale.

---

## See also

* `ingest/bulk_ingest.py` — the orchestrator module.
* `ingest/ar5iv_fetch.py` — ar5iv cache fetcher.
* `ingest/bulk_download.sh` — operator stub for the BitTorrent step.
* `docs/ops/cutover-runbook.md` (TODO — E11_S05) — staging → active
  cutover.
* `docs/ops/latexml-drift-runbook.md` (E10_S04) — what to do when
  LaTeXML drift is detected after a corpus is live.
* `.claude/notes/03-ingestion-pipeline.md` — design constitution
  for the ingest pipeline (the ar5iv-first ladder is canonical
  here).
* `.claude/notes/05-storage-and-indexing.md` — LanceDB MVCC
  semantics (why staging path, not `vN+1` subdirectories).
* `.claude/notes/milestones/E11_S01/research-synthesis.md` — design
  rationale for the scaffolding-only scope and D1-D14 decisions.
