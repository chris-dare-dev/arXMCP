# E11_S01 Research Brief 2 — Bulk Ingest Scaffolding (MVCC / Pipeline / Fallback Ladder)

**Angle:** MVCC mechanics, per-paper pipeline integration, the fallback-ladder inversion, and shippable scope at code-delivery time.

---

## 1. The MVCC mechanism — what the code actually does

**SINGLE dataset, multiple internal versions.** Reading `server/corpus.py` and `ingest/store.py` together confirms the design:

- `DEFAULT_LANCEDB_PATH = var/arxmcp/index/lancedb/` — one directory, one table `chunks`, managed by LanceDB's own MVCC layer.
- Every `write_chunks()` call ends with `tbl.checkout(version=N)` pinning an integer that LanceDB increments internally (one `_versions/N.manifest` per write). No top-level `vN+1/` subdirectory is ever created by the writer.
- The post-index integer (after `_create_indices` rebuilds HNSW) is what gets written to `corpus-version.json`. Readers open the same single dataset and call `tbl.checkout(version=N)`.

**Critical conclusion:** The brief's language "`/var/arxmcp/index/lancedb/vN+1/`" is **misleading documentation drift**. The E11_S01 milestone brief uses this path form; the E11_S05 brief uses "new LanceDB directory." Neither matches the actual implementation. The real MVCC model is:

> "No symlinks are created or modified. LanceDB version int IS the corpus_version." — `ingest/store.py` module docstring.

E04_S01 notes the module docstring explicitly: "The writer surfaces that integer to the caller for downstream MVCC pinning." And `05-storage-and-indexing.md` lines 162–169 confirm: "No manual version subdirectories (v0001/, v0002/) and no symlinks."

**For bulk ingest, the correct plan is:** write directly into the existing `var/arxmcp/index/lancedb/` dataset via `write_chunks()`. The 50-paper seed corpus sits at some integer version N. Each paper's write bumps the internal LanceDB version. At the end of bulk ingest the version integer will be N+K (one or more versions per paper, because HNSW index rebuilds add extra versions). `corpus-version.json` continues to pin the old N throughout the run. E11_S05 advances it. This is already the behavior of `write_chunks` — no code changes are needed at the writer boundary.

**Single-writer constraint (documented):** `ingest/store.py` lines 44–55 explicitly document that `write_chunks` assumes one writer per LanceDB dataset. The bulk ingest must be single-process-sequential at the write boundary (no parallel `write_chunks` calls). Workers can parallelize download, ar5iv fetch, parse, chunk, and embed; writes must serialize.

---

## 2. Per-paper pipeline — the actual call sequence

The existing functions define a clear per-paper sequence:

```
paper_id → [ar5iv_fetch | latexml_parse | nougat_parse]
          → chunker.chunk_paper(paper_id)          # writes to var/arxmcp/corpus/chunks/<paper_id>/
          → embedder.embed_paper(paper_id)          # reads chunks/, writes embeddings/<paper_id>/
          → store.load_embed_record(paper_id)       # reads embeddings NPZ
          → store.write_chunks(chunks, embed_record) # upserts into LanceDB, returns version int
```

Key facts from reading the code:

- `chunk_paper(paper_id)` reads from `var/arxmcp/corpus/parsed/<paper_id>/index.html` and writes JSON to `var/arxmcp/corpus/chunks/<paper_id>/`. On failure it logs to `parser-failures/chunk.log` and returns `[]`. **The chunker itself is fault-tolerant** — an empty return is not an exception.
- `embed_paper(paper_id)` (in `ingest/embedder.py`) reads the chunks directory and writes an NPZ to `var/arxmcp/corpus/embeddings/<paper_id>/`. It's idempotent: if the sidecar exists with matching `chunker_version` and `embedder_version`, the paper is skipped. This makes `--resume` effectively free.
- `load_embed_record(paper_id)` returns `None` if the NPZ is absent (not an error). Returns `EmbedRecord` on success. Raises `ValueError` only if the sidecar is corrupt.
- `write_chunks(chunks, embeddings)` does `merge_insert` on `chunk_id`, then rebuilds HNSW indices. **It does not roll back on partial failure.** The `merge_insert` is the LanceDB-atomic boundary; if HNSW index creation fails, `indices_created["hnsw_stmt"] = False` is logged but the row data is already committed.

**Per-paper transaction boundary:** LanceDB's `merge_insert` is the only atomic boundary. A parse or chunk failure before `write_chunks` is called means zero rows are written for that paper. A failure during `write_chunks` leaves rows in LanceDB but potentially without an HNSW index rebuild (which is caught and logged). The net behavior: each paper is safe to retry independently. The idempotent `merge_insert(on="chunk_id")` means re-running a paper that partially succeeded just overwrites the same chunk_ids.

**This is per-paper-transactional in the important sense:** a single paper failure cannot corrupt other papers' data. The corpus is always in a valid (if incomplete) LanceDB state.

---

## 3. The fallback-ladder inversion — ar5iv FIRST

The brief specifies: (a) ar5iv → (b) LaTeXML → (c) Nougat. This is correct but the current seed fetch pipeline inverts it: `tools/fetch_seed.py` fetches from `/e-print/` first (raw .tex), then runs local LaTeXML.

The design note `03-ingestion-pipeline.md` lines 87–95 is explicit:

> "Run our local LaTeXML only on ar5iv cache misses. Saves weeks of CPU."

For the Academic Torrents dump, the correct per-paper fetch order is:
1. **ar5iv first.** GET `https://ar5iv.labs.arxiv.org/html/<arxiv_id>` with 5s timeout. 200 → parse the HTML5 content directly. 404 → cache miss, continue. Other → retry once.
2. **LaTeXML fallback.** Only if ar5iv misses. The Academic Torrents dump gives us the raw `.tex` tarball on disk already (no `/e-print/` fetch needed). Run local LaTeXML subprocess on the extracted `.tex`.
3. **Nougat PDF fallback.** Only if LaTeXML fails. Fetch PDF from `https://arxiv.org/pdf/<arxiv_id>.pdf`. Run Nougat. Log as `parser_used="nougat"`.
4. **Total failure.** Write a JSON line to `ops/parser-failures/bulk.jsonl` and continue. Do NOT abort the loop.

**Important for the Academic Torrents path:** the torrent dump contains pre-extracted `.tex` tarballs. The `ar5iv` check skips the entire local-parse stack for the ~70–90% of post-2007 papers that are cached. The new module `ingest/ar5iv_fetch.py` needs to: fetch the HTML, check for a minimal-content signal (e.g., `<body>` length > 2000 bytes and no "not processed" error banner), and cache the HTML to `var/arxmcp/cache/ar5iv/<arxiv_id>.html`.

---

## 4. What is shippable in this session

| Deliverable | Ship now? | Rationale |
|---|---|---|
| `ingest/ar5iv_fetch.py` | YES | Pure HTTP fetch + local cache logic. Fully testable without corpus. |
| `ingest/bulk_ingest.py` | YES | Orchestrator — linear per-paper loop. Can be smoke-tested against 1 paper from the existing seed. |
| `ingest/bulk_download.sh` | YES (as stub) | Script header + `aria2c` invocation comment. Mark `TODO: operator runs this`. |
| `tests/test_bulk_ingest_sanity.py` | YES, skip by default | Mark `@pytest.mark.requires_full_corpus` — analogous to `requires_model`. Test verifies ≥ 100K chunks only when marker env var set. At code-ship time it must PASS (by skipping), not fail. |
| `tests/test_ar5iv_fetch.py` | YES | Mock the HTTP call with `responses` or `httpx` fixtures. Fully runnable. |
| `ops/ingestion.log` | NO | Operator-produced artifact. |
| Actual ingest run | NO | GPU-days. Operator only. |

**The `make ingest` stub update:** change it from `exit 1` to invoke `python -m ingest.bulk_ingest --help`. Include `--limit=N` and `--resume` in the help text as first-class flags. The operator can run `make ingest ARGS="--limit=5"` for a smoke test with just 5 papers.

---

## 5. Design decisions — opinionated choices

**Linear, not job-queue.** A single-process sequential loop (download → parse → chunk → embed → write, one paper at a time) is the right v1 architecture for two reasons: (a) the `write_chunks` single-writer constraint is already documented; (b) the embedding step requires GPU memory and batching is handled inside `embedder.py` at the paper level. A job-queue adds operational complexity (broker, workers, state) that isn't warranted until we need multi-GPU parallelism (a v2 concern). The loop should process papers in a deterministic order (sorted by `paper_id`) for crash-resume reproducibility.

**`--paper-ids-file=<path>` is required.** The operator needs to be able to run `python -m ingest.bulk_ingest --paper-ids-file=math.ag.txt` on a subset. Without this flag, every run attempts 200K papers. This is the primary ergonomic control.

**`--dry-run` is a table-stakes safety valve.** `--dry-run` prints the per-paper action plan (which path would be taken: ar5iv/latexml/nougat) without writing to LanceDB or disk. Makes the operator confident before starting a 2-day run.

**Parser-failures format: JSON lines.** One JSON object per line to `ops/parser-failures/bulk.jsonl`. Fields: `paper_id`, `parser_attempted` (list of "ar5iv"|"latexml"|"nougat"), `failure_reason`, `timestamp`. One file, appendable, machine-queryable. NOT one file per paper (that's 200K files, a filesystem and ops nightmare).

**`aria2c` dependency note.** Add a brew/apt install note to `docs/install.md`. Do not attempt to install it programmatically; the operator is expected to have it. `bulk_download.sh` should check for `aria2c` at the top and emit a clear error if absent.

**The ar5iv cache directory** already exists in the Makefile bootstrap: `mkdir -p var/arxmcp/cache/ar5iv`. No new bootstrap changes needed.

---

## 6. Load-bearing constraints from design notes

From `03-ingestion-pipeline.md` lines 87–95 (ar5iv priority):
> "Run our local LaTeXML only on ar5iv cache misses. Saves weeks of CPU."

From `05-storage-and-indexing.md` lines 162–169 (MVCC):
> "No manual version subdirectories (v0001/, v0002/, etc.) and no symlinks. LanceDB MVCC manages corpus versions natively."

From `ingest/store.py` lines 44–55 (single-writer):
> "Callers running concurrent ingest from multiple processes against the same dataset must serialize writes externally (e.g. a flock on `<lancedb_path>/.write-lock`). The Tier-0 ingestion pipeline has exactly one writer."

These three constraints dictate: sequential writes, ar5iv-first fallback ladder, no new dataset directories.

---

## Open questions — different angles from peer brief

**The MVCC mechanism — resolved here.** The implementation is ONE dataset, multiple internal LanceDB version integers. The brief's "vN+1 directory" language is documentation drift. Design around the existing `write_chunks` interface; no new directory structure.

**Linear vs. job-queue.** Pick linear for v1. The single-writer constraint and GPU batching don't benefit from a queue until multi-GPU. Reconsider at E11_S02 (nightly delta) where parallel fetch vs. single-writer is a real tension.

**`≥100K chunks` AC — skip by default.** Mark `@pytest.mark.requires_full_corpus` and gate on env var `ARXMCP_RUN_FULL_CORPUS_TESTS=1`. At code-ship time the test skips (the table has ~8K chunks from the 50-paper seed). A smoke-test AC should be added: `ingest_one_paper(paper_id)` returns a non-empty chunks list (runnable against the existing seed).

**`--dry-run` — yes, ship it.** The operator is running a 2-day job. A dry-run that prints the planned parser path per paper is the minimum safety valve.

**`--paper-ids-file` — yes, required.** Without it the tool is unusable for partial ingestion (weekend math.AG run vs. weekday hep-th run).

**Parser-failures format — JSON lines to one file.** Not a directory of per-paper files. One `ops/parser-failures/bulk.jsonl` with structured fields.

**`aria2c` install note in `docs/install.md` — yes.** One sentence. `brew install aria2` on macOS, `apt install aria2` on Debian. `bulk_download.sh` should check for it with `command -v aria2c`.

**`bulk_download.sh` at v1 — stub with TODO is acceptable.** The magnet link for Academic Torrents arXiv dumps changes periodically. Document the search process (`https://academictorrents.com/browse.php?search=arxiv`) rather than hardcoding a stale link. The script can be a commented-out `aria2c` invocation with the operator-facing comment "find the current magnet link at ...".

---

## External writes required

None at code-shipping time. The milestone deliverables (`ingest/bulk_ingest.py`, `ingest/ar5iv_fetch.py`, `ingest/bulk_download.sh`, `tests/test_bulk_ingest_sanity.py`) are code artifacts only. The actual LanceDB write (to the existing `var/arxmcp/index/lancedb/` dataset) happens when the operator runs `make ingest`. `corpus-version.json` is NOT advanced during this milestone; that is E11_S05.
