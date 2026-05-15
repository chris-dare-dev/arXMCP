# E11_S01 Research Brief — Researcher 1

**Milestone:** E11_S01 — Academic Torrents bulk ingest scaffolding  
**Date:** 2026-05-15  
**Scope posture:** scaffolding-only (operator runs the actual ingest)

---

## 1. In-codebase context — what is reusable

### `tools/arxiv_fetch.py` — the fetch primitive

The module ships `fetch_eprint`, `parse_with_latexml`, `politeness_sleep`,
`build_user_agent`, and `detect_parse_success`. Key constraints:

- **Politeness contract:** `POLITENESS_SLEEP_SECONDS = 3.0`. Caller is
  responsible for calling `politeness_sleep(last_request_at)` BEFORE each
  request; `fetch_eprint` does NOT enforce inter-call spacing.
- **Timeout:** `fetch_eprint(timeout=60.0)` (default); `parse_with_latexml`
  uses `LATEXML_TIMEOUT_SECONDS = 300`.
- **ar5iv:** NOT implemented here. The module only knows about
  `export.arxiv.org/e-print/`. ar5iv integration is new code for E11_S01.
- **ARXMCP_CONTACT_EMAIL** is mandatory — `build_user_agent` raises if
  absent. This must propagate to every sub-process in the bulk ingest.
- **Byte-size cap:** `MAX_RESPONSE_BYTES = 200 MB`. Per-paper safety guard
  against large tarballs (Threat 7).

### `tools/fetch_seed.py` — iteration pattern

Pattern for the bulk ingest loop:

```python
paper_ids = read_seed_list(path)
for paper_id in paper_ids:
    if already_parsed(paper_id, parsed_dir):  # idempotency gate
        continue
    politeness_sleep(last_request_at)
    outcome = process_paper(paper_id)
    write_log(log_path, outcomes, elapsed)
```

`process_paper` is: fetch → find_main_tex → latexml → detect_parse_success.
The bulk ingest orchestrator (`ingest/bulk_ingest.py`) should follow this
exact pattern, extended with the ar5iv-first path:

1. ar5iv cache check (new)
2. local LaTeXML on miss
3. log failure to `ops/parser-failures/` (never raise; always continue)

The `PER_PAPER_FAILURE_EXCEPTIONS` tuple is the canonical catch surface.

### `ingest/chunker.py` — public API

`chunk_paper(paper_id: str) -> list[ChunkRecord]` reads
`var/arxmcp/corpus/parsed/<paper_id>/index.html` and writes chunk JSON to
`var/arxmcp/corpus/chunks/<paper_id>/`. Bulk ingest calls this after
parsing. The chunker already catches per-paper exceptions and returns `[]`
on failure (logs to `ops/parser-failures/chunk.log`).

### `ingest/embedder.py` — public API

The embedder reads chunk JSON from `var/arxmcp/corpus/chunks/<paper_id>/`
and writes NPZ embeddings to `var/arxmcp/corpus/embeddings/<paper_id>/`.
The entry point for one paper is the `embed_paper(paper_id)` pattern
(read chunk manifests, batch encode, write NPZ + sidecar). Bulk ingest
calls this after `chunk_paper`.

### `ingest/store.py` — writer API

`write_chunks(chunks, embeddings, lancedb_path=None) -> int` is the
LanceDB upsert. Returns the post-index LanceDB version integer.

**Critical MVCC finding:** the brief text says `lancedb/vN+1/` — that is
WRONG. There is no separate directory per version. LanceDB's MVCC is
internal to the dataset: every `write_chunks` call increments the internal
version counter. The disk layout is:

```
var/arxmcp/index/lancedb/
  chunks.lance/          # single LanceDB dataset; internal versions managed
  corpus-version.json    # pins the "active" version (server reads at startup)
```

Confirmed in `ingest/store.py` docstring: "LanceDB's on-disk layout puts
the actual files under `var/arxmcp/index/lancedb/chunks.lance/`". Confirmed
in `.claude/notes/05-storage-and-indexing.md` (lines 157-169):
> "No manual version subdirectories (v0001/, v0002/, etc.) and no symlinks.
> LanceDB MVCC manages corpus versions natively."

The brief's `/var/arxmcp/index/lancedb/vN+1/` language is erroneous. The
implementer writes to the same `DEFAULT_LANCEDB_PATH`; the resulting version
integer is returned by `write_chunks` and stored in the corpus-version marker.

**The E11_S01 brief says NOT to advance `corpus-version.json`.** Verified in
`write_chunks`: it calls `write_corpus_version_marker(...)` as a
postcondition of every write. This means every successful `write_chunks`
call WILL update `corpus-version.json`. There is a contradiction between the
brief's AC and the existing code behavior. The implementer must either:
(a) Pass a SEPARATE `lancedb_path` for the bulk ingest writes (e.g.
`var/arxmcp/index/lancedb-staging/`) and NOT copy the `corpus-version.json`
to the canonical location until E11_S05, OR (b) accept that each paper
write advances the marker and the AC "corpus-version.json still pins old
version" is about the staging path never becoming canonical. Option (a) is
cleaner and more explicit.

### `ingest/extract_equations.py` + `ingest/embed_equations.py`

E10_S03b equation pipeline. `extract_equations_for_paper(paper_id)` writes
rows to the `equations` LanceDB table. `embed_pending_equations(...)` runs
BGE-M3 over pending equation rows. Bulk ingest must invoke both after each
paper's `write_chunks` call.

### `ingest/graph_ingest.py` + `ingest/inspire_ingest.py` + `ingest/intra_paper_refs.py`

All three are already shipped. They operate on the Kùzu graph at
`var/arxmcp/index/kuzu/`. Bulk ingest should call graph ingest as a
post-corpus-write batch step (not per-paper — these are IO-bound against
external APIs).

### `Makefile::ingest`

Currently exits 1 with a message: "not yet implemented (the seed corpus
tooling lives in tools/)". E11_S01 makes this real for the first time:
the implementer should wire `make ingest` to
`$(PYTHON) -m ingest.bulk_ingest`.

---

## 2. Prior decisions and lessons

### The seed corpus failure rate and what it means

The existing `fetch_seed.py` with 50 papers uses the `export.arxiv.org/e-print/`
path exclusively. CLAUDE.md §7 notes "2/50 papers have raw TeX, both failed
LaTeXML — meaning the existing fetcher's failure rate is ALREADY ~96%." This
strongly suggests the operator has NOT completed the seed fetch (the fetcher
is fine; the network or LaTeXML environment was not set up). This is NOT a
bug in the fetcher itself. The bulk ingest should:

- Implement the ar5iv-first path aggressively. The `.claude/notes/03-ingestion-pipeline.md`
  Source 6 is explicit: "ar5iv has already done the LaTeXML CPU work for
  ~90% of post-2007 arXiv papers."
- Treat the `export.arxiv.org/e-print/` path as the ONLY fallback for
  ar5iv misses, NOT as the primary. The seed fetch tool used it as primary
  because ar5iv integration hadn't been built yet.
- The per-IP 3-second politeness delay on `export.arxiv.org` makes it
  unusable for bulk backfill. ar5iv is a static cache — no rate limit is
  documented; 5s timeout with retry is fine.

### LanceDB MVCC — no vN+1 directory

The brief's `lancedb/vN+1/` language is fiction. See section 1 above.

### Nougat — defer to follow-up

Nougat is `nougat-ocr` on PyPI (Apache 2.0, maintained through 2025).
It adds `transformers` + `torch` (already present) but requires a GPU for
practical throughput (~1 PDF/min on CPU). The project's `.claude/notes/03-ingestion-pipeline.md`
lines 195-197 scope out "pre-2007 PostScript" explicitly. Most post-2007
papers with no `.tex` are pre-2007 era or withdrawn. Recommendation:
v1 of bulk_ingest treats papers with no usable `.tex` as "skip and log to
`ops/parser-failures/`". Nougat is a separate milestone follow-up.

### `make ingest` as a project landmark

Per CLAUDE.md §7: "`make ingest` was the only mention of production ingest
in CLAUDE.md." Implementing this milestone effectively makes `make ingest`
real for the first time. The Makefile target currently exits 1.

### Eval fixture is NOT empty

`tests/eval/fixtures/queries.json` has 4 queries (not 20). The cold-start
matrix in `test_retrieval_quality.py` requires a `CorpusVersionInfo` (i.e.,
`corpus-version.json` must exist and be valid) AND a non-empty fixture to
RUN instead of SKIP. With 4 queries, the test will RUN but nDCG@5 will be
unreliable (too few queries for statistical validity). The AC "eval passes"
is better stated as "test does not error" — the nDCG@5 threshold with 4
queries is not a robust gate.

### Tool schema — no changes

E11_S01 ships no new MCP tools and modifies no tool descriptions. The
`EXPECTED_TOOL_SCHEMA_SHA256` in `tests/test_server_tool_schema.py` does
NOT need re-pinning.

### `aria2c` and system deps

`aria2c` is a system dep like `latexmlc`. The `bulk_download.sh` script
must `command -v aria2c || { echo "aria2c not found; brew install aria2"; exit 1; }`.

### Academic Torrents URL pattern

arXiv source dumps on Academic Torrents are per-month, per-year archives.
The typical naming is `arXiv_src_YYMM_NNN.tar`. There is no per-category
filter at download time — the full dump must be downloaded and filtered at
extraction. The tarball's metadata XML (OAI-PMH format baked into the dump)
contains the subject categories. Key: the implementer must find the
active torrent hash(es) for the arXiv src dump. Academic Torrents search:
`https://academictorrents.com/search.php?q=arxiv+src`. Total size for the
full src dump is ~1.5 TB; for 4 categories, extraction-filtered size is
a few hundred GB.

---

## 3. External sources

### Academic Torrents arXiv dump

- URL: `https://academictorrents.com/search.php?q=arxiv+source`
- Format: `.tar` archives containing per-paper `.tar.gz` tarballs, organized
  by arXiv ID prefix. Metadata XML per paper includes `subject_class`.
- No per-category torrent — must download full dump and filter at extraction.
- Aria2c invocation: `aria2c --seed-ratio=1 --max-overall-download-limit=0 <magnet>`.
- Total size: ~1.5 TB full src dump; ~300 GB for math.AG+math.NT+math-ph+hep-th.

### ar5iv labs cache

- Primary URL: `https://ar5iv.labs.arxiv.org/html/<arxiv_id>`
- Secondary (replacing ar5iv): `https://arxiv.org/html/<arxiv_id>`
- Response: HTTP 200 = HTML5+MathML, ready for the chunker.
- HTTP 404 = cache miss (paper not processed). HTTP 429/503 = rate-limited
  (treat as miss; do NOT retry immediately — log and fall back to LaTeXML).
- Rate limit: not officially documented; the system is a static HTML cache
  on CDN. Recommend 5s timeout, no sleep between requests.
- The ar5iv response is ALREADY parsed HTML — skip `parse_with_latexml`
  and write directly to `var/arxmcp/corpus/parsed/<paper_id>/index.html`.

### Nougat

- PyPI: `nougat-ocr` (Apache 2.0). Last release: v0.1.17 (2024-02).
- Requires `torch` + GPU for production throughput. CPU is ~1 page/min.
- Deferred from this milestone per recommendation below.

### aria2c

- macOS: `brew install aria2`. Debian/Ubuntu: `apt install aria2`.
- Well-maintained (last release 2023). Handles BitTorrent natively.
- `aria2c --file-allocation=none --seed-ratio=0 <magnet>` for download-only.

---

## Open questions

**1. Should this milestone narrow to scaffolding-only?** YES. The actual
ingest run requires a GPU, multi-hundred-GB download, and live network access
to ar5iv/arxiv/OpenAlex/INSPIRE-HEP. The milestone-pipeline session cannot
execute this. Deliver code; operator runs it. ACs split as:

| AC | Verifiable at code-ship? |
|---|---|
| Code compiles, tests pass | YES |
| `ingest/bulk_download.sh` exists and is correct | YES (review) |
| `ingest/bulk_ingest.py` exists and handles all parser paths | YES (unit tests with mocks) |
| `tests/test_bulk_ingest_sanity.py` exists | YES |
| `corpus-version.json` still pins old version | YES (staging path) |
| New LanceDB version >= 100K chunks | NO — requires operator run |
| ar5iv cache hit rate >= 70% logged | NO — requires operator run |
| eval --hybrid --ndcg-min=0.70 passes | NO — requires operator run + fixture |

**2. Nougat scope.** Defer. v1 bulk_ingest treats no-tex papers as
"skip and log". Wiring Nougat adds ~5 GB model download, GPU dep, and scope
for an E12 follow-up with no near-term retrieval benefit (most missing-tex
papers are pre-2007 or withdrawn).

**3. ar5iv cache integration.** Implement with `httpx` or `urllib.request`
at 5s timeout. No rate limit enforcement needed (static CDN). Cache
responses to `var/arxmcp/cache/ar5iv/<paper_id>/index.html` on disk (the
Makefile `bootstrap` already creates `var/arxmcp/cache/ar5iv/`).

**4. MVCC version layout — no vN+1 directory.** The implementer must NOT
create a separate directory per version. LanceDB manages this internally.
To isolate the bulk ingest write from the active `corpus-version.json`,
use a staging LanceDB path (e.g. `var/arxmcp/index/lancedb-staging/`).
E11_S05 promotes the staging version to canonical.

**5. The eval AC.** With only 4 queries in `queries.json`, the nDCG@5
test is underpowered. The AC should be: "if `queries.json` has >= 10
queries AND `corpus-version.json` is valid, the test runs; if either is
absent/empty, the test SKIPS — AC is vacuously satisfied." Operator must
curate queries (E11_S04) before this AC has teeth.

**6. GPU vs CPU.** The embedder already works on CPU (`torch>=2.0` is in
`pyproject.toml`; no CUDA requirement). The orchestrator should be
GPU-agnostic; operator controls hardware via the PyTorch device selection
environment. No GPU-specific code in `bulk_ingest.py`.

**7. `make ingest` target.** Implement BOTH: update the Makefile stub to
`$(PYTHON) -m ingest.bulk_ingest` AND ship the Python module. This is the
first real implementation of `make ingest`.

**8. Parser-failures format.** JSON lines. One record per failure:
```json
{"paper_id": "2401.00001", "parser": "ar5iv|latexml|none", "error_class": "HTTPError|TimeoutExpired|...", "message": "...", "timestamp": "2026-05-15T12:00:00Z"}
```
This matches the existing `store-stats.jsonl` discipline and is machine-queryable.

---

## External writes required

None at code-shipping time. The operator's run of `make ingest` will:
- Download ~300 GB via BitTorrent (Academic Torrents)
- Fetch parsed HTML from ar5iv (network)
- Write to `var/arxmcp/index/lancedb-staging/`
- Call OpenAlex and INSPIRE-HEP for citation graph ingest

All of these are operator-runtime, not code-shipping, writes.
