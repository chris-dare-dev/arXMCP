# Research Brief 1 — E11_S02: OAI-PMH delta loop

**Researcher:** Agent 1 of 2  
**Date:** 2026-05-15

---

## 1. In-codebase context

### Politeness contract (`tools/arxiv_fetch.py`)

The 3-second politeness sleep is defined as:

```python
POLITENESS_SLEEP_SECONDS = 3.0
```

and applied via `politeness_sleep(start_time, min_interval=POLITENESS_SLEEP_SECONDS)` which computes elapsed time and sleeps only the remainder. This applies exclusively to `export.arxiv.org` (the `/e-print/` endpoint). `ingest/ar5iv_fetch.py` explicitly documents: "No rate limiting. ar5iv is a CDN-fronted static cache… Politeness contract is separate from arxiv.org."

The OAI-PMH endpoint is also on `export.arxiv.org`, so the 3-second per-IP constraint applies to OAI-PMH page requests. However, OAI-PMH responses are batches of hundreds of metadata records per page, NOT per-paper — the sleep budget applies to ListRecords page fetches (~1 per 500-record batch), not per-paper.

### `ingest/bulk_ingest.py` — E11_S01 reference implementation

Key exports for reuse:

- `ingest_one_paper(paper_id, *, lancedb_staging_path, ar5iv_cache_dir, parsed_dir, skip_ar5iv)` — the per-paper pipeline: ar5iv → latexml → chunk → embed → `write_chunks`. **Use this directly in the delta loop.** Do not implement a second per-paper function.
- `DEFAULT_LANCEDB_STAGING_PATH` = `REPO_ROOT / "var/arxmcp/index/lancedb-staging"` — the staging dataset path. The delta loop writes here identically to the bulk ingest.
- `PaperOutcome`, `IngestSummary` — result types suitable for logging.
- The single-writer constraint: `write_chunks` must not be called concurrently. The delta loop is sequential at the write boundary (same as bulk ingest).

The module docstring at `ingest/bulk_ingest.py:13-15` states the rationale for staging: "Writing into the active dataset would advance the marker per-paper and break the brief's AC2." The delta loop must follow the same discipline.

### `ingest/store.py` — MVCC and corpus-version.json

`DEFAULT_LANCEDB_PATH = REPO_ROOT / "var" / "arxmcp" / "index" / "lancedb"`. The `write_chunks` function uses LanceDB's `merge_insert` and returns the post-index dataset version integer. `CORPUS_VERSION_MARKER_NAME = "corpus-version.json"` is co-located with the LanceDB dataset directory. The store writes `corpus-version.json` as a post-write step inside `write_chunks`. **This is the authoritative activation step — no filesystem touch or symlink.**

The store's docstring at lines 56-72 clarifies that the returned integer is the post-`_create_indices` version (not the post-merge version), and callers should treat it as opaque.

### `.claude/notes/05-storage-and-indexing.md` — LanceDB MVCC (load-bearing)

Direct quote: "Manual symlink swaps (`current -> v0007`) are **explicitly prohibited** under the new design. Use LanceDB's native MVCC mechanism instead."

And: "LanceDB exposes native versioning: every `write` operation on a dataset creates a new integer version… The MCP server reads `corpus-version.json` at startup and calls `dataset.checkout(version=N)` once; that pinned view is used for the entire process lifetime. **No symlinks are created or modified.**"

The disk layout (`05-storage-and-indexing.md` lines 164-168) shows:
```
index/
  lancedb/
    chunks/              # single LanceDB dataset; internal versions managed by LanceDB MVCC
    corpus-version.json  # marker file
    # NOTE: No manual version subdirectories (v0001/, v0002/, etc.) and no symlinks.
```

### `.claude/notes/06-mcp-server-design.md` lines 346–354

Quote: "The MCP server does NOT auto-switch — it continues using its pinned version. Restart the server to pick up the new corpus. (Rationale: agents in the middle of a session expect index stability.)"

### `.claude/notes/03-ingestion-pipeline.md`

OAI-PMH is called out as the delta channel (lines 29-45): "Rate limit: ~1 request per 4 seconds, with required `from`/`until` windowing and resumption tokens. Filter at the source via `set=math` or `set=physics:hep-th`." The pipeline diagram shows OAI-PMH producing paper IDs that flow into the same per-paper job queue as the bulk seed.

`.claude/notes/08-security-observability-ops.md` documents the daily ops cadence (lines 228-241): OAI-PMH starts at 00:00 UTC; new version written at 04:00; `corpus-version.json` updated atomically at 04:05 (no symlink swap); restic backup at 04:10. The failure-mode table (lines 199-201) documents "OAI-PMH endpoint 503: Pause delta loop with exponential backoff (max 1 hour)."

The metrics schema already includes `arxmcp_ingest_oai_pmh_lag_seconds` (gauge) as a defined metric.

### `pyproject.toml` — pytest markers

Registered markers relevant to integration tests:
- `requires_model` — downloads/loads a real ML model; skipped by default
- `requires_full_corpus` — asserts against a fully-ingested 200K-paper corpus; gated by `ARXMCP_RUN_FULL_CORPUS_TESTS=1`
- `requires_latexmlc` — needs `latexmlc` binary

No marker exists for "requires a live OAI-PMH endpoint." The test suite for this milestone must use mocked responses and requires no new marker.

---

## 2. Prior decisions and lessons

### CRITICAL: "fresh LanceDB directory" language is wrong

The brief states: "The ingestion process writes the new version to a fresh LanceDB directory." This is factually incorrect and contradicts the design constitution. From `.claude/notes/05-storage-and-indexing.md`:

> "No manual version subdirectories (v0001/, v0002/, etc.) and no symlinks. LanceDB MVCC manages corpus versions natively."

The E11_S01 critique (`critique-merged.md`) called out the same mistake in the E11_S01 brief and confirmed the correct pattern: write into the staging LanceDB dataset (`var/arxmcp/index/lancedb-staging/`) via `write_chunks`; the LanceDB version integer increments internally. After the delta run is complete and validated (optionally by E11_S04 watchdog), `corpus-version.json` is updated with the new integer.

**The implementer must NOT create new directories like `lancedb-v2/`, `lancedb-delta/`, or `lancedb-vN+1/`.** The delta loop writes to the same staging dataset as E11_S01, and E11_S05's cutover promotes that staging path.

### Staging-path discipline from E11_S01

The correct pattern (confirmed by E11_S01's critique as "the right call"): delta writes go to `DEFAULT_LANCEDB_STAGING_PATH` = `var/arxmcp/index/lancedb-staging/`. The active `corpus-version.json` at `var/arxmcp/index/lancedb/` is NOT touched until E11_S05 activation.

### E11_S01 critique findings that apply to the delta loop

- **F1 (stale embed reuse):** `ingest_one_paper` has been fixed to check `embed_paper`'s return value; the delta loop gets this fix for free by calling `ingest_one_paper`.
- **F3/IS2 (resume flag):** No `--resume` flag should be added to the delta loop CLI. Idempotence comes from the embedder sidecar (re-runs skip already-embedded papers).
- **IS1 (Python version guard):** The delta loop's Makefile target must include the version guard pattern from other targets.
- **Single-writer constraint:** The delta loop is sequential. No concurrent `write_chunks` calls.

---

## 3. External sources

### OAI-PMH 2.0 spec

Canonical reference: http://www.openarchives.org/OAI/openarchivesprotocol.html

Key protocol facts:
- Verb `ListRecords` with `metadataPrefix=arXiv` or `metadataPrefix=arXivRaw` returns up to 1000 records per page.
- `arXivRaw` format provides: identifier, datestamp, setSpec, categories, abstract, authors, license, version history. **No .tex source** — OAI-PMH is metadata only.
- `from` and `until` parameters use ISO 8601 date format (`YYYY-MM-DD` for day-granularity harvesting).
- `set` parameter filters by category: `set=math` (all math), `set=math:AG`, `set=physics:hep-th`, `set=physics:math-ph`. Multiple `set` filters require multiple requests.
- Incomplete list (>1 page) returns a `<resumptionToken>` in the response; subsequent requests use `verb=ListRecords&resumptionToken=<token>` (no other parameters).
- A `resumptionToken` may be empty in the FINAL response page — this signals list complete, not an error. The token may also carry attributes: `expirationDate`, `cursor`, `completeListSize`.
- HTTP response is XML (`Content-Type: text/xml`).
- arXiv OAI-PMH endpoint: `http://export.arxiv.org/oai2` (HTTP, not HTTPS — see Landmine D below).
- arXiv sets available at: http://export.arxiv.org/oai2?verb=ListSets

### `arXiv` vs `arXivRaw` metadata format

- `arXiv`: older format; abstracts in Unicode; does not include version history.
- `arXivRaw`: newer; includes `<versions>`, `<categories>`, `<license>`, `<journal-ref>`. Use `arXivRaw` to detect new vs updated papers and to populate the `papers` metadata table correctly.

---

## 4. Critical landmines

### A. Absolute path `/var/arxmcp/ops/new-version-ready` is wrong

The brief says "signals the MCP server via a filesystem touch of `/var/arxmcp/ops/new-version-ready`." Every other path in this project uses relative paths anchored to `REPO_ROOT` (e.g. `REPO_ROOT / "var" / "arxmcp" / "ops"`). An absolute `/var/arxmcp/` path will fail on macOS workstations (no `/var/arxmcp/` root) and Docker deployments with mounted volumes under different host paths.

**Recommendation:** Use `REPO_ROOT / "var" / "arxmcp" / "ops" / "new-version-ready"`. However, the filesystem touch is redundant with `corpus-version.json` — the server reads `corpus-version.json` at startup and does not poll for the touch file. **Recommend dropping the touch file entirely** and relying on the standard `corpus-version.json` update as the sole signal. Document in the operator runbook that restarting the server is required after a delta run.

### B. "Fresh LanceDB directory" language is wrong

See Section 2 above. The implementer must use the staging-path discipline from E11_S01: write to `var/arxmcp/index/lancedb-staging/` via `ingest_one_paper`. No new directories. The version integer increments within the single staging dataset.

### C. systemd is Linux-only; macOS operators need an alternative

The brief specifies `ops/systemd/arxmcp-delta.service` and `arxmcp-delta.timer`. systemd does not exist on macOS. The CLAUDE.md at Section 3 (Status snapshot) and `.claude/notes/08-security-observability-ops.md` describe a single-workstation deployment likely running macOS (Apple M-series hardware is listed in the workstation requirements section).

**Recommendation:** Ship both:
1. `ops/systemd/arxmcp-delta.service` + `arxmcp-delta.timer` — for Linux/Docker deployments.
2. A `crontab` snippet in `docs/ops/delta-loop.md` as the macOS alternative: `0 2 * * * /path/to/uv run python -m ingest.oai_delta`.

Do NOT add a launchd plist — that's more complex than a crontab and harder to maintain. The `cron` fallback covers both macOS and Linux and is sufficient for a single-workstation deployment.

### D. OAI-PMH endpoint is HTTP, not HTTPS

The endpoint is `http://export.arxiv.org/oai2` (confirmed in `.claude/notes/03-ingestion-pipeline.md:30` and `.claude/notes/08-security-observability-ops.md:284`). TLS verification does not apply to this endpoint. Note that `tools/arxiv_fetch.py` uses `https://export.arxiv.org/e-print/` (HTTPS) for the source tarball endpoint — the OAI-PMH endpoint is the exception.

**Recommendation:** Use HTTP for OAI-PMH. Flag this in `docs/ops/delta-loop.md` as an arXiv infrastructure limitation. Add a comment in `ingest/oai_delta.py` referencing the E13 security audit. This is a known gap; no workaround exists since arXiv does not offer HTTPS on OAI-PMH.

### E. Two separate rate limits: OAI-PMH pages vs per-paper fetches

The brief conflates two distinct rate-limit contexts:
1. **OAI-PMH `ListRecords` page fetches** (to `export.arxiv.org`): Covered by the 3-second politeness sleep from `tools/arxiv_fetch.py`. Each page returns up to 1000 records; at 500 papers/day, 1-2 OAI-PMH pages suffice. The sleep between pages is the correct application of the politeness contract here.
2. **Per-paper ar5iv fetches** (to `ar5iv.labs.arxiv.org`): No rate limit. Per `ingest/ar5iv_fetch.py` docstring: "No rate limiting. ar5iv is a CDN-fronted static cache."
3. **Per-paper `/e-print/` fetches** (to `export.arxiv.org`): Only needed for ar5iv misses. The 3-second sleep applies here, between individual paper fetches.

The delta loop's politeness budget applies to: (a) 1-2 OAI-PMH pages (2 × 3s = 6s overhead), and (b) per-paper `/e-print/` fetches for ar5iv misses only. The brief's "3 seconds per fetch, 500 papers = 25 minutes" is only correct if ALL 500 papers miss ar5iv and require `/e-print/` fallback. With ≥70% ar5iv hit rate, the actual fetch time is ≤8 minutes.

The implementer should apply `politeness_sleep` only before OAI-PMH page requests and before `/e-print/` fetch calls — the `ingest_one_paper` function handles the latter internally via `ar5iv_fetch.try_cache` (no sleep) and the latexml fallback path (needs sleep injected before the `/e-print/` call if the delta loop adds network fetching of raw source).

### F. MCP server old-version regression guard is missing

The brief's AC says the filesystem touch signals the server but the server does NOT auto-reload. There is no test that verifies the server continues serving the OLD version during a delta run. The E11_S05 milestone includes a formal cutover activation with a `/readyz` check, but E11_S02 has no such guard.

**Recommendation:** The delta loop should log the current active `corpus-version.json` integer at start and end of each run. The operator runbook should document that the active server remains pinned to the pre-run version until an explicit restart. No automated regression guard is needed in E11_S02 (that's E11_S05's job).

### G. Test marker for integration test

The `tests/test_oai_delta.py` unit test (mocked OAI-PMH + mocked `ingest_one_paper`) requires no marker — it uses no real models, no real corpus, no `latexmlc`. No marker needed.

An optional smoke test that calls the live OAI-PMH endpoint would require a new marker (e.g. `requires_network`). Do not add such a test — it would be flaky in offline environments and the mocked test suite is sufficient.

### H. `ingest_one_paper` is the correct reuse point

The delta loop should call `ingest_one_paper(paper_id, lancedb_staging_path=DEFAULT_LANCEDB_STAGING_PATH, ...)` directly. Do NOT implement a second per-paper function. Rationale: E11_S01 rectified all HIGH findings in `ingest_one_paper` (F1 embed-status check, F2 parsed_dir decoupling, F3 resume-flag removal); a parallel implementation would re-introduce those bugs. The staging path is an explicit parameter.

The delta loop adds one thing `ingest_one_paper` does not do: the OAI-PMH metadata harvest, which populates the `papers` table with title/authors/abstract/categories. This should be a pre-step before calling `ingest_one_paper`, using the `arXivRaw` metadata fetched during the OAI-PMH harvest.

---

## Open questions

None that must be resolved before writing code. The following are scoped decisions the implementer should make and document:

1. **`papers` table population:** The OAI-PMH harvest provides rich metadata (title, authors, abstract, categories, license, version history). The `papers` table schema in `ingest/schema.py` (or via LanceDB) needs to be written to during the delta run. E11_S02 should populate the `papers` table; confirm it was NOT populated by E11_S01 bulk ingest (the bulk-ingest module only calls `write_chunks`, not a `write_papers` equivalent).

2. **Withdrawn paper handling:** The brief scopes this to "setting `withdrawn=true` in the metadata." The `papers` table schema in `.claude/notes/05-storage-and-indexing.md` includes `withdrawn: bool`. The implementer should upsert withdrawn status on the paper record; chunks from withdrawn papers do NOT need to be deleted (out of scope per the brief).

3. **Date windowing:** The delta run should harvest the previous calendar day (`yesterday`). On the first run, if `oai-pmh-state.json` has no prior date, default to the previous day (not a full backfill). Full backfill is E11_S01's job.

---

## External writes the implementation will require

None. The implementation is entirely local:
- `ingest/oai_delta.py` — new Python module in the local repo
- `ops/oai-pmh-state.json` — local state file (created by the delta runner)
- `ops/systemd/arxmcp-delta.service` + `arxmcp-delta.timer` — local config files
- `docs/ops/delta-loop.md` — local documentation (note: per CLAUDE.md §1, this goes in `docs/ops/` because it is operator-facing and linked from the root README or `docs/install.md`)
- `tests/test_oai_delta.py` — local test file
- All LanceDB writes go to `var/arxmcp/index/lancedb-staging/` (local, gitignored)

No pushes, PRs, tickets, infra mutations, or third-party API calls required to implement this milestone. The OAI-PMH fetch itself (HTTP GET to `http://export.arxiv.org/oai2`) is a read-only operation with no side effects on any external system.
