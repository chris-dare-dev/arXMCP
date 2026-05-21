# Research Brief — proof-verify-handler-wiring-m6

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-21T00:00:00Z

## In-codebase context

### Design notes that apply

- `03-ingestion-pipeline.md` — the ar5iv-first fallback ladder is the load-bearing strategy
- `04-parsing-and-chunking.md` — `PARSED_DIR` is module-level in `ingest/chunker.py:78` (`PARSED_DIR = REPO_ROOT / "var" / "arxmcp" / "corpus" / "parsed"`); the notebook scripts MUST NOT attempt to override it — Variant 1 keeps `corpus/parsed/` global
- `07-multi-agent-caching.md` — no MCP tool changes here; cache note is non-load-bearing for m6 (pure tooling)
- `08-security-observability-ops.md` — Threat 7 cap (100 MB) is already enforced in `ingest/ar5iv_fetch.py` via `AR5IV_MAX_RESPONSE_BYTES = 100 * 1024 * 1024`

### Existing notebook directory layout (ground truth)

The two notebooks already on disk set the canonical shape:

```
var/arxmcp/notebooks/bridgeland-stability/
    papers.txt          # commented header + one paper_id per line
    queries.json        # full eval queries (schema_version, notebook_slug, queries[])
    lancedb/            # per-notebook LanceDB (corpus-version.json inside)
    [no bm25/ — not yet built]

var/arxmcp/notebooks/shimura-varieties/
    papers.txt
    queries.json
    pdf-deferred/       # manifest.json + deferred PDFs (not in bridgeland)
    lancedb/
```

The brief says `index/bm25/` under the notebook — but **no notebook has a BM25 index built yet**. The existing global BM25 lives at `var/arxmcp/index/bm25/v<N>/`. For per-notebook BM25 the implementer must pass a per-notebook root to `build_bm25_index`. The function signature is:

```python
# ingest/bm25_indexer.py:245-248
def build_bm25_index(
    lancedb_path: str | Path,
    corpus_version: int,
) -> None:
```

**CRITICAL CONSTRAINT:** `build_bm25_index` writes to `BM25_INDEX_ROOT` which is hardcoded as `REPO_ROOT / "var" / "arxmcp" / "index" / "bm25"`. There is no parameter to override the output root. The implementer must either:
1. Call `build_bm25_index` and then move/copy artifacts to the per-notebook path, OR
2. Accept that per-notebook BM25 writes to `var/arxmcp/index/bm25/v<N>/` keyed by corpus_version (which is the per-notebook corpus_version, so it's implicitly per-notebook by version number)

**Recommendation:** Option 2 is simpler and correct. The per-notebook corpus_version is distinct from the global corpus. The BM25 index at `var/arxmcp/index/bm25/vN/` keyed by notebook's corpus_version IS the per-notebook BM25. The milestone brief's `var/arxmcp/notebooks/<slug>/index/bm25/v<N>/` path is aspirational drift — the actual `build_bm25_index` function cannot produce that path without modification.

**FLAG: the brief's BM25 path `var/arxmcp/notebooks/<slug>/index/bm25/v<N>/` conflicts with `BM25_INDEX_ROOT` being hardcoded in `ingest/bm25_indexer.py:104`.** The implementer has two options: accept the global BM25 path (simpler), or add a `bm25_root` override parameter to `build_bm25_index`.

### `_read_paper_ids` contract (load-bearing)

```python
# ingest/bulk_ingest.py:172-196
def _read_paper_ids(path: Path) -> list[str]:
    """Load a newline-separated list of paper ids.
    Blanks and ``#``-comment lines are skipped. Each id is
    validated against ``is_valid_paper_id`` — malformed entries
    raise so the operator catches typos before a multi-day run.
    """
```

`papers.txt` must be `#`-comment-prefixed headers + one paper_id per line. The existing notebooks already use this format. `notebook_init.py` should produce a file in this exact format.

### `bulk_ingest` CLI surface (what `notebook_ingest.py` wraps)

```python
# ingest/bulk_ingest.py:439-487 (CLI flags)
--paper-ids-file   required; Path to papers.txt
--lancedb-staging-path  default DEFAULT_LANCEDB_STAGING_PATH; override for per-notebook
--ar5iv-cache-dir  default DEFAULT_AR5IV_CACHE_DIR
--limit
--dry-run
```

**CRITICAL:** The `--parsed-dir` flag was removed (closed F2 per bulk_ingest.py:461-466): "The chunker reads from a hardcoded module-level PARSED_DIR; honoring the CLI override at the ar5iv-write step but ignoring it at the chunker step caused silent chunker_returned_empty failures. The parsed-dir is now fixed at `ingest.chunker.PARSED_DIR`."

This means `notebook_ingest.py` calls `bulk_ingest` with `--lancedb-staging-path=var/arxmcp/notebooks/<slug>/lancedb` and that is the only per-notebook override needed. The parsed HTML is always global at `var/arxmcp/corpus/parsed/<paper_id>/index.html`.

### Ad-hoc scripts — the m6 work in prototype form

The four ad-hoc scripts (`/tmp/bridgeland_fetch.py`, `/tmp/bridgeland_fetch_batch2.py`, `/tmp/shimura_fetch.py`, `/tmp/bridgeland_ingest.sh`, `/tmp/bridgeland_ingest_batch2.sh`, `/tmp/shimura_ingest.sh`) establish these patterns:

1. **HTTP client:** `urllib.request` with `User-Agent` header. No `requests`/`httpx`. Timeout=30s for HTML fetches (not 3s — the 3s is the inter-request politeness sleep).
2. **Politeness:** `time.sleep(3.0)` between fetches, applied before every non-first request.
3. **Cache check:** `target.exists() and target.stat().st_size > 1024` is the cache hit test.
4. **ar5iv URL pattern:** both `https://arxiv.org/html/<id>v<N>` and `https://ar5iv.labs.arxiv.org/html/<id>` are accepted. The paper_id regex is `r"/html/(\d{4}\.\d{4,5}|\d{7})(?:v\d+)?$"`.
5. **`<math` signal check:** raw body bytes must contain `b"<math"` (the shimura script uses this; bridgeland uses `b"<math"` too).
6. **Ingest pattern:** per-paper invocation of `python -m ingest.bulk_ingest --paper-ids-file=<tmpfile> --lancedb-staging-path=<notebook-lancedb>`, one paper at a time via a temp file.
7. **papers.txt format:** comment header lines (`# ...`) followed by one paper_id per line.
8. **queries.json format:** `{"schema_version": "1.0", "notebook_slug": ..., "queries": [...]}`.

**NOTE:** The shimura fetch script contains `assert slug is not None` at line 103. This is a **banned pattern** (CLAUDE.md §4.7: "`assert` is BANNED for invariants"). The implementer must use `if slug is None: raise RuntimeError(...)` instead.

### Politeness contract clarification

`ingest/ar5iv_fetch.py` docstring: "No rate limiting. ar5iv is a CDN-fronted static cache. The 5-second timeout is the only safety; no inter-request sleep." However the ad-hoc scripts use `time.sleep(3.0)` between ALL fetches (both `arxiv.org/html` and `ar5iv.labs.arxiv.org`). The `tools/arxiv_fetch.py:29` has `POLITENESS_SLEEP_SECONDS = 3.0` for `export.arxiv.org`. The brief says "Honors the 3s politeness sleep against arxiv.org / ar5iv.labs.arxiv.org." Follow the brief: apply the 3s sleep for both endpoints in `notebook_fetch.py`.

### `corpus_version` determination for BM25

The per-notebook LanceDB's `corpus-version.json` contains the version number. For `bridgeland-stability`, the last ingested paper left `{"version": 157, ...}` in `var/arxmcp/notebooks/bridgeland-stability/lancedb/corpus-version.json`. `notebook_ingest.py` must read this file post-ingest to get the version and pass it to `build_bm25_index`.

### Banned pattern note: `assert` in shimura ad-hoc script

Line 103 of `/tmp/shimura_fetch.py`: `assert slug is not None` — this is the banned pattern. The notebook_fetch.py CLI script being written for m6 should NOT accept non-arXiv items at all (it operates from `papers.txt` which contains only arXiv IDs), so there is no slug vs. kind dispatch needed. The PDF path is out of scope for m6.

### Test infrastructure

`tests/tools/` does NOT exist. The implementer must create this directory. Tests should follow the project pattern of `uv run python -m pytest`. The Makefile `test` target runs `ruff check . && pytest` with no special args, so the new `tests/tools/test_notebook_scripts.py` will be picked up automatically.

### What `notebook_fetch.py` reads from papers.txt

`notebook_fetch.py <slug>` reads `var/arxmcp/notebooks/<slug>/papers.txt` using the same `_read_paper_ids` logic (skip `#`-lines, skip blanks). For each paper_id, check whether `var/arxmcp/corpus/parsed/<paper_id>/index.html` exists. If missing, fetch from `ar5iv.labs.arxiv.org/html/<paper_id>` with `time.sleep(3.0)` between fetches. Fetched HTML is written to `var/arxmcp/corpus/parsed/<paper_id>/index.html` (NOT to a notebook-local path — Variant 1, global corpus).

## Prior decisions and lessons

- **`--parsed-dir` was intentionally removed from `bulk_ingest` CLI** (F2 fix). `notebook_ingest.py` MUST NOT attempt to pass `--parsed-dir`. This is a silent footgun.
- **Single-writer constraint** (`ingest/store.py:44-55`): the bulk_ingest loop is sequential at the write boundary. Per-paper ingest (one paper per `bulk_ingest` invocation, as done in the ad-hoc bash scripts) is correct.
- **Embedder short-circuits cleanly on re-run** (`ingest/embedder.py:914-936`): already-processed papers skip the embed step. This makes re-runs of `notebook_ingest.py` safe.
- **No `assert` for invariants** (CLAUDE.md §4.7). The shimura bootstrap script violates this. The m6 scripts must use `if ... raise RuntimeError(...)` or `raise ValueError(...)`.
- **KMP_DUPLICATE_LIB_OK=TRUE** in `tests/conftest.py` is load-bearing. `tests/tools/` tests must not remove or shadow it.
- **BM25 pickle security**: `_BM25_ARTIFACT_MODE = 0o600` — the atomic write helper sets explicit permissions. This is already handled by `build_bm25_index` internally.
- **Global BM25 path** (`var/arxmcp/index/bm25/`) vs notebook-local (`var/arxmcp/notebooks/<slug>/index/bm25/`): the brief aspires to notebook-local; the code only supports global. Recommendation below picks one.
- **Recent git log** shows no notebook-tooling commits — all recent work is E13 security audit. m6 is net-new tooling with no prior implementation to build on beyond the ad-hoc `/tmp/` scripts.
- **`tests/tools/` does not exist** — the implementer must create `tests/tools/__init__.py` (or `tests/tools/.gitkeep` if the discovery doesn't require it) before writing `test_notebook_scripts.py`.

## External sources

`urllib.request` (stdlib) is the correct HTTP client for the four notebook scripts. Rationale:
1. All six ad-hoc bootstrap scripts use `urllib.request` — this is the established pattern.
2. Adding `requests` or `httpx` as a new runtime dependency for tooling-only scripts violates the project's principle of avoiding unnecessary deps.
3. The ingest pipeline (`ingest/ar5iv_fetch.py`, `ingest/oai_delta.py`, `ingest/graph_ingest.py`, `ingest/inspire_ingest.py`) all use `urllib.request` — no `httpx` anywhere in the codebase.
4. TLS verification is enabled by default in `urllib.request`; no `verify=False` risk.

No MCP spec or prompt-caching docs are relevant — m6 touches no server surface.

## Recommendation

Implement the four scripts as CLI Python modules in `tools/` following the pattern of the ad-hoc bootstrap scripts, with these specific choices:

1. **`notebook_init.py <slug>`**: creates `var/arxmcp/notebooks/<slug>/papers.txt` (with a `# <slug> notebook — add one arXiv paper_id per line` header) and `queries.json` (with `schema_version: "1.0"`, `notebook_slug: <slug>`, `queries: []`). Idempotent: if the notebook dir already exists, print `notebook exists; skipping` and exit 0. Use `if` not `assert` everywhere.

2. **`notebook_fetch.py <slug>`**: read papers.txt using the `_read_paper_ids` logic. For each paper_id, check `var/arxmcp/corpus/parsed/<paper_id>/index.html`. If missing, fetch from `ar5iv.labs.arxiv.org/html/<paper_id>` with `urllib.request`, `timeout=30`, `time.sleep(3.0)` before each fetch (skip sleep on first), check `b"<math"` in body. Print summary `fetched=N from_cache=M missing=K` at end; print missing IDs explicitly. Use `urllib.request` only.

3. **`notebook_ingest.py <slug>`**: invoke `ingest.bulk_ingest` programmatically (import `run_bulk_ingest`, `_read_paper_ids`) rather than shelling out — avoids the bash per-paper-tmpfile pattern. Pass `lancedb_staging_path=var/arxmcp/notebooks/<slug>/lancedb`. After ingest succeeds, read `corpus-version.json` to get the version, then call `build_bm25_index(lancedb_path=..., corpus_version=N)`. Accept the global BM25 path (`var/arxmcp/index/bm25/vN/`) — do NOT attempt to add a `bm25_root` parameter to `build_bm25_index`. Log output goes to `var/arxmcp/notebooks/<slug>/ops/ingest.log`. Exit 0 on success, non-zero on failure.

4. **`notebook_purge.py <slug>`**: default: `shutil.rmtree(var/arxmcp/notebooks/<slug>/)` with interactive confirmation (print prompt, read from `input()`, compare to slug). `--force` skips confirmation. `--purge-corpus-too` additionally removes `var/arxmcp/corpus/parsed/<paper_id>/`, `corpus/chunks/<paper_id>/`, `corpus/embeddings/<paper_id>/` for paper_ids in this notebook's `papers.txt` that do NOT appear in any other notebook's `papers.txt`.

5. **Tests in `tests/tools/test_notebook_scripts.py`**: use `tmp_path` fixtures; mock the network calls. Create `tests/tools/__init__.py` (empty). Test: happy path init/fetch/ingest/purge, ar5iv-miss-with-manual-drop (mock returning no-math body), purge confirmation gate (incorrect typed-slug → script aborts without deleting).

**The BM25 path drift (brief says notebook-local, code only supports global):** use the global BM25 path. The per-notebook corpus_version is unique (it starts from 1 in the empty notebook lancedb and advances per paper), so `var/arxmcp/index/bm25/v<N>/` is effectively per-notebook. The milestone brief's per-notebook path is aspirational; implementing it would require modifying `build_bm25_index` which is a non-trivial change out of m6's scope.

## Open questions

No open questions — implementation can proceed on the above recommendation. The one drift (BM25 path) is resolved in favor of the global path.

## External writes the implementation will require

| type | target | why |
|---|---|---|
| network fetch | `https://ar5iv.labs.arxiv.org/html/<paper_id>` | `notebook_fetch.py` fetches ar5iv HTML for paper_ids missing from `var/arxmcp/corpus/parsed/`; operator-initiated, not orchestrator-gated |
| network fetch | `https://arxiv.org/html/<paper_id>v<N>` | alternate URL form for the same fetch; same operator trigger |

All other work is purely local filesystem operations. No git push, no PR, no infra mutation.
