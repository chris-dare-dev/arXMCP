# Research Synthesis — proof-verify-handler-wiring-m6

**Generated:** 2026-05-21
**Mode:** standard (2 researchers)
**Briefs merged:** `research-brief-1.md`, `research-brief-2.md`

---

## What's getting built (single-sentence)

Four CLI scripts under `tools/notebook_{init,fetch,ingest,purge}.py` that codify the ad-hoc bootstrap patterns I used to create the bridgeland-stability and shimura-varieties notebooks, plus tests under `tests/tools/test_notebook_scripts.py`. Variant 1 layout: global `corpus/`, per-notebook `lancedb/` + `bm25/` (BM25 path drift resolved below).

## Load-bearing constraints (verbatim)

From `CLAUDE.md §4.7`:
> "`assert` is BANNED for invariants — Python `-O` strips them. Use `if … raise RuntimeError(…)` instead."

From `ingest/bulk_ingest.py:461-466` (F2 closure):
> "`--parsed-dir` was a CLI footgun. The chunker reads from a hardcoded module-level `PARSED_DIR`; honoring the CLI override at the ar5iv-write step but ignoring it at the chunker step caused silent `chunker_returned_empty` failures. The parsed-dir is now fixed at `ingest.chunker.PARSED_DIR`."

From `ingest/bm25_indexer.py:104`:
> "`BM25_INDEX_ROOT = REPO_ROOT / "var" / "arxmcp" / "index" / BM25_DIR_NAME`" — hardcoded; no per-notebook output-dir parameter exists.

From `ingest/ar5iv_fetch.py` (already implemented):
- 100 MB cap (`AR5IV_MAX_RESPONSE_BYTES = 100 * 1024 * 1024`) — Threat 7 of `08-security-observability-ops.md`
- 429/503 handling returns `Ar5ivResult(hit=False, reason="http_<code>")`
- `<math` presence check on body bytes

From `ingest/identifiers.py::is_valid_paper_id`:
- Single source of truth for paper-ID validation (closed E06_S03 F11)
- Accepts BOTH new-style (`2303.07061`) AND old-style (`0705.3794`, `hep-th/0001234`). Bridgeland-stability corpus contains old-style IDs — using a narrower regex would reject them.

From the roadmap doc's own validation (line 379):
- Slug regex: `^[a-z][a-z0-9-]{2,30}$` (the same regex the roadmap skill enforces on its own slugs — canonical for notebook subsystem)

## Resolved disagreements and choices

### Disagreement 1: HTTP client for `notebook_fetch.py`

- **R-1 position:** Use `urllib.request` directly, matching the ad-hoc bootstrap scripts. Avoids new dependencies.
- **R-2 position:** Delegate to `ingest.ar5iv_fetch.try_cache`. Inherits the 100 MB cap, the User-Agent contract, the 429/503 handling, and the `<math` body check.

**Resolution: R-2's approach wins.** Delegating to `try_cache` inherits four pieces of security/correctness machinery for free; reimplementing them in `tools/notebook_fetch.py` is the path to silent drift. The ad-hoc bootstrap scripts pre-dated this delegation pattern; the production tool should use the shipped path.

Concrete shape: `notebook_fetch.py` reads `papers.txt`, pre-validates each line via `is_valid_paper_id`, then loops calling `try_cache(paper_id, cache_dir=DEFAULT_AR5IV_CACHE_DIR, parsed_dir=DEFAULT_PARSED_DIR)` with `time.sleep(3.0)` between non-first calls. The 3s sleep lives in the loop, not in `try_cache` (which docstrings as "No rate limiting" for the ar5iv CDN endpoint).

### Disagreement 2: BM25 output path — global vs per-notebook

- **R-1 position:** Accept the global BM25 path at `var/arxmcp/index/bm25/v<N>/`. The per-notebook `corpus_version` is unique per notebook (each starts from 1 in an empty LanceDB), so `v<N>` is implicitly per-notebook. Avoid scope creep into `ingest/bm25_indexer.py`.
- **R-2 position:** Flag as open question; potential scope expansion (would require adding `output_dir` param to `build_bm25_index`).

**Resolution: R-1's approach wins for the minimum-viable m6.** Per the milestone brief's `**Complexity.** S (~1 day)` framing, modifying `ingest/bm25_indexer.py` to add a per-notebook output path is out of scope. Accept the global BM25 path; the per-notebook `corpus_version` makes `v<N>` directories effectively per-notebook.

**Caveat to encode in the implementation summary:** the brief literally says `var/arxmcp/notebooks/<slug>/index/bm25/v<N>/` — that path is aspirational drift from what the code supports today. The implementation will write to `var/arxmcp/index/bm25/v<N>/` and the implementation-summary must document this deviation explicitly so a future operator doesn't search for the per-notebook path and conclude BM25 wasn't built.

**Note for a future milestone:** if hosting multiple notebooks in one daemon ever causes BM25 corpus_version collisions (two notebooks with overlapping version integers), a separate epic adds the per-notebook output-dir parameter to `build_bm25_index`. Not m6's problem today.

### Disagreement 3: `--force` flag's interaction with `pdf-deferred/`

- **R-1 position:** Doesn't address.
- **R-2 position:** Warn about pdf-deferred even with `--force` (conservative) OR require a third explicit flag like `--force --purge-pdf-deferred-too`.

**Resolution: warn-on-stderr always, but `--force` proceeds.** The operator typing `--force` is signaling intent; blocking the operation on a separate flag is overengineering. But silent loss of irrecoverable PDFs is bad — print a `WARN:` line to stderr listing the pdf-deferred files about to be deleted, then proceed. The script's `--help` text must call out this behavior.

### Disagreement 4: Brief says `ARXMCP_LANCEDB_PATH=...` but bulk_ingest doesn't read it

Both researchers caught this independently. The brief is wrong — `ARXMCP_LANCEDB_PATH` is the SERVER's env var (`server/config.py`), not a `bulk_ingest` CLI option. `bulk_ingest` uses `--lancedb-staging-path` only.

**Resolution: invoke `bulk_ingest.run_bulk_ingest()` programmatically with `lancedb_staging_path=Path("var/arxmcp/notebooks/<slug>/lancedb")`.** Don't shell out, don't set env vars. This is the documented mismatch from the brief; the implementation does the right thing.

## Failure modes the implementation must cover (R-2's 8, condensed)

The implementation MUST defend against each. The test file MUST cover at least items 1, 2, 3, 5, 8.

1. **Cross-notebook deletion via `--purge-corpus-too`** — compute paper-id uniqueness via set difference across all sibling `papers.txt` files. NEVER use `os.path.commonpath` for this.
2. **Slug path-traversal** — validate slug against `^[a-z][a-z0-9-]{2,30}$` as the FIRST check in every script. Belt-and-braces: after path construction, assert `(notebooks_base/slug).resolve()` is contained within `notebooks_base.resolve()`. `Path.resolve(strict=True)` is NOT a sufficient defense.
3. **`notebook_init.py` partial-state** — idempotency check at directory level, not file level. Partial state recovery requires manual deletion + re-run; document in docstring.
4. **HTTP 429 silently counted as "missing"** — surface as a distinct `rate_limited=R` category in the summary, separate from `missing=K`. Print the rate-limited IDs explicitly with "retry after backoff — do NOT drop these."
5. **Malformed `papers.txt` entries** — pre-validate each line via `is_valid_paper_id` BEFORE calling `try_cache`. Surface as `malformed=J` in the summary.
6. **`notebook_ingest.py` lancedb dir doesn't exist** — `mkdir(parents=True, exist_ok=True)` for the notebook dir AND the `ops/` subdir before invoking `bulk_ingest`.
7. **Stale BM25 from prior runs** — the indexer already handles this correctly (skips only when both `bm25.pkl` AND `chunk_ids.json` are present). `notebook_ingest.py` should log a warning if multiple `v<N>` directories exist for the same notebook's lancedb, suggesting `notebook_purge.py` to prune.
8. **`pdf-deferred/` data loss on purge** — print `WARN:` to stderr listing pdf-deferred files about to be deleted; proceed under `--force`, block on confirmation prompt otherwise (in addition to the typed-slug confirmation).

## Test surface (acceptance criteria #7 requires `tests/tools/test_notebook_scripts.py`)

Pre-conditions:
- Create `tests/tools/__init__.py` (does NOT exist; pytest discovery needs it).
- Use `tmp_path` fixtures — do NOT touch live `var/arxmcp/notebooks/`.
- Mock all network calls (`urllib.request.urlopen` or `ingest.ar5iv_fetch.try_cache` directly).
- Honor the project's `KMP_DUPLICATE_LIB_OK=TRUE` autouse fixture from `tests/conftest.py`.

Required test cases (one per failure mode, plus happy-path):
- `test_init_happy_path` — slug validates, dir created, files have expected schema.
- `test_init_idempotent_directory_level` — second run is no-op even with one file deleted.
- `test_init_rejects_bad_slug` — `../corpus`, `Bridgeland`, `a-b`, `aa`, `a` * 35 all rejected.
- `test_fetch_happy_path` — mock returns valid HTML; summary reports `fetched=N`.
- `test_fetch_distinguishes_rate_limit_from_miss` — mock returns 429 for one ID; summary has separate `rate_limited=` category.
- `test_fetch_rejects_malformed_papers_txt_lines` — line with URL is reported as `malformed=`.
- `test_ingest_creates_missing_dirs` — runs against fresh slug with no pre-existing notebook dir.
- `test_purge_typed_slug_confirmation` — wrong slug typed → script aborts, dir untouched.
- `test_purge_purge_corpus_too_set_difference` — paper shared with sibling notebook is NOT deleted from corpus.
- `test_purge_warns_about_pdf_deferred` — captures stderr output naming the pdf files.

## Implementation order (recommended for the implementer)

1. **Slug validation helper** in a shared module (e.g. `tools/_notebook_common.py`) — reused by all four scripts. Single source of truth for the regex.
2. **`notebook_init.py`** — smallest, most independent. Lands first.
3. **`notebook_fetch.py`** — depends on `is_valid_paper_id` + `try_cache`. Tests can mock `try_cache`.
4. **`notebook_ingest.py`** — depends on `run_bulk_ingest` programmatic call + `build_bm25_index`. The most complex; lands third.
5. **`notebook_purge.py`** — most security-sensitive due to FM-1, FM-2, FM-8. Lands last so the other three can be developed without race conditions.
6. **Tests** — co-developed with each script, NOT batched at the end.

## Orchestrator synthesis note

The two briefs converged cleanly on the major architectural choices (delegate HTTP, accept global BM25 path) but diverged on rigor — R-1 was implementation-pattern-focused, R-2 was failure-mode-focused. The synthesis preserves R-2's full FM-1..FM-8 list as binding requirements; the test surface above maps directly to those modes.

Both researchers independently caught the brief's `ARXMCP_LANCEDB_PATH` error (it's a server env var, not a bulk_ingest one). Strong corroboration; resolved unambiguously.

## Open questions (orchestrator-resolved)

All open questions from both briefs are resolved in the disagreements section above. No remaining blockers for implementation.

## External writes the implementation will require

| type | target | why |
|---|---|---|
| network fetch | `https://ar5iv.labs.arxiv.org/html/<paper_id>` | `notebook_fetch.py` ar5iv fetches for missing parsed HTML; operator-initiated, inherits `try_cache`'s 5s timeout + 100 MB cap |
| network fetch | `https://arxiv.org/html/<paper_id>v<N>` | Alternate URL form delegated through `try_cache` (already handled today) |

No git push, no PR creation, no infra mutation, no third-party API. Tests run against `tmp_path`. Phase 4 has no external-write authorizations to gate.
